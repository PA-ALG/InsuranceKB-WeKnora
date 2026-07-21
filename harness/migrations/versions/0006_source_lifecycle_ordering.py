"""Durable source lifecycle head, event ledger, and ambiguity issue (OpenSpec 021).

Revision ID: 0006
Revises: 0012
Create Date: 2026-07-19

Historical 017 source identities are recorded as unresolved issues; this migration
never guesses a head from hashes or timestamps. Downgrade mirrors all older
destructive preflights before the first 0006 DDL operation.
"""

import json
import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import context, op
from alembic.util.exc import CommandError
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

revision = "0006"
down_revision = "0012"
branch_labels = None
depends_on = None

_SOURCE_REVISION_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
_RETRACT_EVENT_TOKEN = re.compile(r"^retract:[0-9a-fA-F]{56}$")
_SAFE_KNOWLEDGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_SOURCE_LINEAGE_STATUSES = frozenset({"linked", "page_only", "ambiguous"})
_BACKFILL_REASON = "historical_017_source_ordering_unavailable"
_TOMBSTONE_BACKFILL_REASON = (
    "historical_017_source_ordering_unavailable_with_tombstone_event"
)
_SourceKey = tuple[str, str, str, str]

LEGACY_SPACE_ID = "legacy-default"
_PRE_SCOPE_REVISIONS = {"0001", "0002"}
_PRE_RELEASE_REVISIONS = {"0001", "0002", "0003", "0004"}
_PRE_FLYWHEEL_REVISIONS = {
    "0001",
    "0002",
    "0003",
    "0004",
    "0005",
}

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
}

SQLITE_CREATE_APPEND_ONLY_GUARDS = (
    """
    CREATE TRIGGER trg_source_events_update_guard_021
    BEFORE UPDATE ON source_events
    FOR EACH ROW
    BEGIN
        SELECT RAISE(ABORT, 'source events are append-only');
    END
    """,
    """
    CREATE TRIGGER trg_source_events_delete_guard_021
    BEFORE DELETE ON source_events
    FOR EACH ROW
    BEGIN
        SELECT RAISE(ABORT, 'source events are append-only');
    END
    """,
)

SQLITE_DROP_APPEND_ONLY_GUARDS = (
    "DROP TRIGGER IF EXISTS trg_source_events_delete_guard_021",
    "DROP TRIGGER IF EXISTS trg_source_events_update_guard_021",
)

POSTGRESQL_CREATE_APPEND_ONLY_GUARDS = (
    """
    CREATE FUNCTION guard_source_events_append_only_021() RETURNS trigger
    LANGUAGE plpgsql AS $guard$
    BEGIN
        RAISE EXCEPTION 'source events are append-only'
            USING ERRCODE = '23514';
    END;
    $guard$
    """,
    """
    CREATE TRIGGER trg_source_events_update_guard_021
    BEFORE UPDATE ON source_events
    FOR EACH ROW EXECUTE FUNCTION guard_source_events_append_only_021()
    """,
    """
    CREATE TRIGGER trg_source_events_delete_guard_021
    BEFORE DELETE ON source_events
    FOR EACH ROW EXECUTE FUNCTION guard_source_events_append_only_021()
    """,
)

POSTGRESQL_DROP_APPEND_ONLY_GUARDS = (
    "DROP TRIGGER IF EXISTS trg_source_events_delete_guard_021 ON source_events",
    "DROP TRIGGER IF EXISTS trg_source_events_update_guard_021 ON source_events",
    "DROP FUNCTION IF EXISTS guard_source_events_append_only_021()",
)


def _timestamps() -> list[sa.Column[Any]]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def _add_parent_scope_keys() -> None:
    with op.batch_alter_table(
        "knowledge_spaces", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.create_unique_constraint(
            "uq_knowledge_spaces_scope_raw",
            ["id", "tenant_id", "raw_kb_id"],
        )
    with op.batch_alter_table(
        "change_sets", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.create_unique_constraint(
            "uq_change_sets_space_id", ["space_id", "id"]
        )
    with op.batch_alter_table(
        "change_items", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.create_unique_constraint(
            "uq_change_items_change_set_id", ["change_set_id", "id"]
        )


def _create_source_heads() -> None:
    op.create_table(
        "source_heads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("space_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("raw_kb_id", sa.String(255), nullable=False),
        sa.Column("knowledge_id", sa.String(255), nullable=False),
        sa.Column("head_revision", sa.String(64), nullable=False),
        sa.Column("ordering_kind", sa.String(16), nullable=False),
        sa.Column("ordering_processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ordering_generation", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("last_event_id", sa.String(36), nullable=True),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("head_updated_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "space_id", "knowledge_id", name="uq_source_heads_space_knowledge"
        ),
        sa.UniqueConstraint(
            "space_id",
            "tenant_id",
            "raw_kb_id",
            "knowledge_id",
            name="uq_source_heads_scoped_source",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "tenant_id", "raw_kb_id"],
            ["knowledge_spaces.id", "knowledge_spaces.tenant_id", "knowledge_spaces.raw_kb_id"],
            name="fk_source_heads_scope_raw",
        ),
        sa.CheckConstraint(
            "(ordering_kind = 'processed_at' "
            "AND ordering_processed_at IS NOT NULL AND ordering_generation IS NULL) "
            "OR (ordering_kind = 'generation' "
            "AND ordering_processed_at IS NULL AND ordering_generation >= 0)",
            name="ck_source_heads_ordering_shape",
        ),
        sa.CheckConstraint(
            "state IN ('active', 'deleted')", name="ck_source_heads_state"
        ),
        sa.CheckConstraint("version >= 1", name="ck_source_heads_version"),
    )
    op.create_index(
        "ix_source_heads_scope_state", "source_heads", ["space_id", "state"]
    )


def _create_source_events() -> None:
    op.create_table(
        "source_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("space_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("raw_kb_id", sa.String(255), nullable=False),
        sa.Column("knowledge_id", sa.String(255), nullable=False),
        sa.Column("input_revision", sa.String(64), nullable=False),
        sa.Column("ordering_kind", sa.String(16), nullable=False),
        sa.Column("ordering_processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ordering_generation", sa.Integer(), nullable=True),
        sa.Column("desired_state", sa.String(16), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("before_head", sa.JSON(), nullable=True),
        sa.Column("after_head", sa.JSON(), nullable=True),
        sa.Column("causation_id", sa.String(255), nullable=True),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("change_set_id", sa.String(36), nullable=True),
        sa.Column("tombstone_change_item_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "space_id",
            "knowledge_id",
            "id",
            name="uq_source_events_source_id",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "tenant_id", "raw_kb_id"],
            ["knowledge_spaces.id", "knowledge_spaces.tenant_id", "knowledge_spaces.raw_kb_id"],
            name="fk_source_events_scope_raw",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "tenant_id", "raw_kb_id", "knowledge_id"],
            [
                "source_heads.space_id",
                "source_heads.tenant_id",
                "source_heads.raw_kb_id",
                "source_heads.knowledge_id",
            ],
            name="fk_source_events_scoped_head",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "change_set_id"],
            ["change_sets.space_id", "change_sets.id"],
            name="fk_source_events_space_change_set",
        ),
        sa.ForeignKeyConstraint(
            ["change_set_id", "tombstone_change_item_id"],
            ["change_items.change_set_id", "change_items.id"],
            name="fk_source_events_tombstone_item",
        ),
        sa.CheckConstraint(
            "(ordering_kind = 'processed_at' "
            "AND ordering_processed_at IS NOT NULL AND ordering_generation IS NULL) "
            "OR (ordering_kind = 'generation' "
            "AND ordering_processed_at IS NULL AND ordering_generation >= 0)",
            name="ck_source_events_ordering_shape",
        ),
        sa.CheckConstraint(
            "desired_state IN ('active', 'deleted')",
            name="ck_source_events_desired_state",
        ),
        sa.CheckConstraint(
            "decision IN ('accepted_create', 'accepted_advance', "
            "'accepted_delete', 'accepted_reactivate', 'idempotent', "
            "'stale', 'blocked_deleted')",
            name="ck_source_events_decision",
        ),
        sa.CheckConstraint(
            "tombstone_change_item_id IS NULL OR change_set_id IS NOT NULL",
            name="ck_source_events_tombstone_link",
        ),
    )
    op.create_index(
        "ix_source_events_source_time",
        "source_events",
        ["space_id", "knowledge_id", "decided_at"],
    )
    op.create_index(
        "ix_source_events_scope_decision",
        "source_events",
        ["space_id", "decision", "decided_at"],
    )


def _create_backfill_issues() -> None:
    op.create_table(
        "source_lifecycle_backfill_issues",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("space_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("raw_kb_id", sa.String(255), nullable=False),
        sa.Column("knowledge_id", sa.String(255), nullable=False),
        sa.Column("observed_revisions", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("resolved_revision", sa.String(64), nullable=True),
        sa.Column("resolved_ordering_kind", sa.String(16), nullable=True),
        sa.Column("resolved_processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_generation", sa.Integer(), nullable=True),
        sa.Column("expected_state", sa.String(16), nullable=True),
        sa.Column("resolved_by", sa.String(128), nullable=True),
        sa.Column("resolution_reason", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "space_id",
            "knowledge_id",
            name="uq_source_lifecycle_issues_space_knowledge",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "tenant_id", "raw_kb_id"],
            ["knowledge_spaces.id", "knowledge_spaces.tenant_id", "knowledge_spaces.raw_kb_id"],
            name="fk_source_lifecycle_issues_scope_raw",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved')",
            name="ck_source_lifecycle_issues_status",
        ),
        sa.CheckConstraint(
            "(status = 'open' "
            "AND resolved_revision IS NULL AND resolved_ordering_kind IS NULL "
            "AND resolved_processed_at IS NULL AND resolved_generation IS NULL "
            "AND expected_state IS NULL AND resolved_by IS NULL "
            "AND resolution_reason IS NULL AND resolved_at IS NULL) "
            "OR (status = 'resolved' AND resolved_revision IS NOT NULL "
            "AND expected_state IN ('active', 'deleted') AND resolved_by IS NOT NULL "
            "AND resolution_reason IS NOT NULL AND resolved_at IS NOT NULL "
            "AND ((resolved_ordering_kind = 'processed_at' "
            "AND resolved_processed_at IS NOT NULL AND resolved_generation IS NULL) "
            "OR (resolved_ordering_kind = 'generation' "
            "AND resolved_processed_at IS NULL AND resolved_generation >= 0)))",
            name="ck_source_lifecycle_issues_resolution_shape",
        ),
    )
    op.create_index(
        "ix_source_lifecycle_issues_scope_status",
        "source_lifecycle_backfill_issues",
        ["space_id", "status"],
    )


def _valid_revision(value: object) -> str | None:
    if not isinstance(value, str) or _SOURCE_REVISION_HEX.fullmatch(value) is None:
        return None
    return value.lower()


def _valid_retract_event_token(value: object) -> str | None:
    if not isinstance(value, str) or _RETRACT_EVENT_TOKEN.fullmatch(value) is None:
        return None
    return value.lower()


def _valid_knowledge_id(value: object) -> str | None:
    if not isinstance(value, str) or _SAFE_KNOWLEDGE_ID.fullmatch(value) is None:
        return None
    return value


def _singleton_knowledge_id(value: object) -> str | None:
    decoded = value
    if isinstance(decoded, str):
        try:
            decoded = json.loads(decoded)
        except (TypeError, ValueError):
            return None
    if not isinstance(decoded, list) or len(decoded) != 1:
        return None
    return _valid_knowledge_id(decoded[0])


def _observed_historical_revisions(
    connection: Connection,
) -> tuple[dict[_SourceKey, set[str]], set[_SourceKey]]:
    """Return only identities that satisfy the durable 017 source contracts."""
    observed: defaultdict[_SourceKey, set[str]] = defaultdict(set)
    tombstone_sources: set[_SourceKey] = set()

    evidence_rows = connection.execute(
        sa.text(
            "SELECT c.space_id AS space_id, ks.tenant_id AS tenant_id, "
            "ks.raw_kb_id AS raw_kb_id, e.knowledge_id AS knowledge_id, "
            "e.source_revision AS source_revision, e.lineage_status AS lineage_status "
            "FROM claim_evidence e "
            "JOIN claims c ON c.id = e.claim_id "
            "JOIN knowledge_spaces ks "
            "ON ks.id = c.space_id AND ks.raw_kb_id = e.raw_kb_id "
            "WHERE ks.binding_status = 'bound' "
            "AND ks.tenant_id IS NOT NULL AND ks.raw_kb_id IS NOT NULL "
            "AND e.lineage_status IS NOT NULL AND e.source_revision IS NOT NULL"
        )
    ).mappings()
    for row in evidence_rows:
        revision = _valid_revision(row["source_revision"])
        knowledge_id = _valid_knowledge_id(row["knowledge_id"])
        lineage_status = row["lineage_status"]
        if (
            revision is None
            or knowledge_id is None
            or lineage_status not in _SOURCE_LINEAGE_STATUSES
        ):
            continue
        observed[
            (
                str(row["space_id"]),
                str(row["tenant_id"]),
                str(row["raw_kb_id"]),
                knowledge_id,
            )
        ].add(revision)

    change_set_rows = connection.execute(
        sa.text(
            "SELECT cs.space_id AS space_id, ks.tenant_id AS tenant_id, "
            "ks.raw_kb_id AS raw_kb_id, cs.knowledge_ids AS knowledge_ids, "
            "cs.source_kind AS source_kind, "
            "cs.external_record_id AS external_record_id, "
            "cs.source_revision AS source_revision "
            "FROM change_sets cs "
            "JOIN knowledge_spaces ks ON ks.id = cs.space_id "
            "WHERE ks.binding_status = 'bound' "
            "AND ks.tenant_id IS NOT NULL AND ks.raw_kb_id IS NOT NULL "
            "AND cs.source_kind IN ('document', 'recompile') "
            "AND cs.external_record_id IS NOT NULL "
            "AND cs.source_revision IS NOT NULL"
        )
    ).mappings()
    for row in change_set_rows:
        external_record_id = _valid_knowledge_id(row["external_record_id"])
        knowledge_id = _singleton_knowledge_id(row["knowledge_ids"])
        if external_record_id is None or knowledge_id != external_record_id:
            # Legacy retracts use a `legacy:*` external ID which can never match
            # the singleton original knowledge ID.
            continue
        source_kind = row["source_kind"]
        token = _valid_revision(row["source_revision"])
        is_tombstone = False
        if token is None and source_kind == "document":
            token = _valid_retract_event_token(row["source_revision"])
            is_tombstone = token is not None
        if token is None:
            # A recompile row can never turn a retract token into source identity.
            continue
        key = (
            str(row["space_id"]),
            str(row["tenant_id"]),
            str(row["raw_kb_id"]),
            knowledge_id,
        )
        observed[key].add(token)
        if is_tombstone:
            # This audit token proves historical deletion state existed, but does
            # not recover the original source revision, ordering, or desired head.
            tombstone_sources.add(key)

    return dict(observed), tombstone_sources


def _backfill_historical_017_sources(connection: Connection) -> None:
    """Create one unresolved ledger row per historical source, never a head."""
    observed, tombstone_sources = _observed_historical_revisions(connection)
    if not observed:
        return

    now = datetime.now(UTC)
    issues = sa.table(
        "source_lifecycle_backfill_issues",
        sa.column("id", sa.String(36)),
        sa.column("space_id", sa.String(36)),
        sa.column("tenant_id", sa.String(255)),
        sa.column("raw_kb_id", sa.String(255)),
        sa.column("knowledge_id", sa.String(255)),
        sa.column("observed_revisions", sa.JSON()),
        sa.column("reason", sa.Text()),
        sa.column("status", sa.String(16)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    values = [
        {
            "id": str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    "insurancekb:021:source-backfill:"
                    f"{space_id}\0{knowledge_id}",
                )
            ),
            "space_id": space_id,
            "tenant_id": tenant_id,
            "raw_kb_id": raw_kb_id,
            "knowledge_id": knowledge_id,
            # Sorting is canonical set serialization only; it never selects a head.
            "observed_revisions": sorted(revisions),
            "reason": (
                _TOMBSTONE_BACKFILL_REASON
                if (space_id, tenant_id, raw_kb_id, knowledge_id)
                in tombstone_sources
                else _BACKFILL_REASON
            ),
            "status": "open",
            "created_at": now,
            "updated_at": now,
        }
        for (space_id, tenant_id, raw_kb_id, knowledge_id), revisions in sorted(
            observed.items()
        )
    ]
    if connection.dialect.name == "postgresql":
        connection.execute(
            postgresql_insert(issues)
            .values(values)
            .on_conflict_do_nothing(index_elements=["space_id", "knowledge_id"])
        )
    else:
        connection.execute(
            sqlite_insert(issues)
            .values(values)
            .on_conflict_do_nothing(index_elements=["space_id", "knowledge_id"])
        )


def _add_last_event_foreign_key() -> None:
    with op.batch_alter_table(
        "source_heads", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.create_foreign_key(
            "fk_source_heads_last_event",
            "source_events",
            ["space_id", "knowledge_id", "last_event_id"],
            ["space_id", "knowledge_id", "id"],
        )


def _create_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    statements = (
        SQLITE_CREATE_APPEND_ONLY_GUARDS
        if dialect == "sqlite"
        else POSTGRESQL_CREATE_APPEND_ONLY_GUARDS
    )
    for statement in statements:
        op.execute(sa.text(statement))


def upgrade() -> None:
    _add_parent_scope_keys()
    _create_source_heads()
    _create_source_events()
    _create_backfill_issues()
    if not op.get_context().as_sql:
        _backfill_historical_017_sources(op.get_bind())
    _add_last_event_foreign_key()
    _create_append_only_guards()


def _drop_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    statements = (
        SQLITE_DROP_APPEND_ONLY_GUARDS
        if dialect == "sqlite"
        else POSTGRESQL_DROP_APPEND_ONLY_GUARDS
    )
    for statement in statements:
        op.execute(sa.text(statement))


def _destination_crosses(revisions: set[str]) -> bool:
    destination = context.get_revision_argument()
    if destination is None:
        return True
    if isinstance(destination, tuple):
        return any(revision_id in revisions for revision_id in destination)
    return destination in revisions


def _validate_current_topology() -> None:
    versions = list(
        op.get_bind().scalars(
            sa.text("SELECT version_num FROM alembic_version ORDER BY version_num")
        )
    )
    if versions != [revision]:
        raise RuntimeError(
            "0006 downgrade refused before DDL: unexpected migration topology "
            f"{versions!r}; expected exactly [{revision!r}]"
        )


def _lifecycle_state_counts() -> dict[str, int]:
    connection = op.get_bind()
    return {
        table: int(connection.scalar(sa.text(f"SELECT count(*) FROM {table}")) or 0)
        for table in (
            "source_heads",
            "source_events",
            "source_lifecycle_backfill_issues",
        )
    }


def _enterprise_scope_conflicts() -> list[str]:
    connection = op.get_bind()
    checks = (
        (
            "insurance_products.product_code",
            ("product_code",),
            "SELECT product_code, count(*) AS conflict_count FROM insurance_products "
            "GROUP BY product_code HAVING count(*) > 1",
        ),
        (
            "product_versions(product_id, version_label)",
            ("product_id", "version_label"),
            "SELECT product_id, version_label, count(*) AS conflict_count "
            "FROM product_versions GROUP BY product_id, version_label HAVING count(*) > 1",
        ),
        (
            "product_documents(product_id, sha256)",
            ("product_id", "sha256"),
            "SELECT product_id, sha256, count(*) AS conflict_count FROM product_documents "
            "GROUP BY product_id, sha256 HAVING count(*) > 1",
        ),
        (
            "claims published key",
            ("product_version_id", "concept_id", "predicate", "effective_from"),
            "SELECT product_version_id, concept_id, predicate, effective_from, "
            "count(*) AS conflict_count FROM claims WHERE status = 'published' "
            "AND product_version_id IS NOT NULL AND concept_id IS NOT NULL "
            "AND predicate IS NOT NULL AND effective_from IS NOT NULL "
            "GROUP BY product_version_id, concept_id, predicate, effective_from "
            "HAVING count(*) > 1",
        ),
        (
            "change_sets(source_kind, external_record_id, source_revision)",
            ("source_kind", "external_record_id", "source_revision"),
            "SELECT source_kind, external_record_id, source_revision, "
            "count(*) AS conflict_count FROM change_sets "
            "WHERE external_record_id IS NOT NULL AND source_revision IS NOT NULL "
            "GROUP BY source_kind, external_record_id, source_revision HAVING count(*) > 1",
        ),
        (
            "review_items.review_key",
            ("review_key",),
            "SELECT review_key, count(*) AS conflict_count FROM review_items "
            "GROUP BY review_key HAVING count(*) > 1",
        ),
        (
            "release_snapshots.label",
            ("label",),
            "SELECT label, count(*) AS conflict_count FROM release_snapshots "
            "GROUP BY label HAVING count(*) > 1",
        ),
        (
            "snapshot_claims(snapshot_id, claim_id)",
            ("snapshot_id", "claim_id"),
            "SELECT snapshot_id, claim_id, count(*) AS conflict_count "
            "FROM snapshot_claims GROUP BY snapshot_id, claim_id HAVING count(*) > 1",
        ),
    )
    conflicts: list[str] = []
    for label, key_columns, query in checks:
        rows = connection.execute(sa.text(query)).mappings()
        conflicts.extend(
            f"{label}({', '.join(f'{column}={row[column]!r}' for column in key_columns)}, "
            f"count={row['conflict_count']})"
            for row in rows
        )
    pointers = connection.execute(
        sa.text("SELECT id, space_id FROM current_release ORDER BY id, space_id")
    ).all()
    if len(pointers) > 1:
        conflicts.append(
            f"current_release singleton(rows={pointers!r}, count={len(pointers)})"
        )
    return conflicts


def _validate_enterprise_scope_downgrade() -> None:
    connection = op.get_bind()
    space_ids = list(
        connection.scalars(sa.text("SELECT id FROM knowledge_spaces ORDER BY id"))
    )
    if space_ids and space_ids != [LEGACY_SPACE_ID]:
        raise CommandError(
            "cannot downgrade 0003 before DDL: expected no knowledge space or exactly "
            f"one named {LEGACY_SPACE_ID!r}; found {space_ids!r}"
        )
    conflicts = _enterprise_scope_conflicts()
    if conflicts:
        raise CommandError(
            "cannot downgrade 0003 before DDL: global business-key conflicts: "
            + "; ".join(conflicts)
        )


def _release_state_counts() -> dict[str, int]:
    connection = op.get_bind()
    statements = {
        "version_1_snapshots": (
            "SELECT count(*) FROM release_snapshots WHERE read_model_version = 1"
        ),
        "snapshot_facts": "SELECT count(*) FROM snapshot_facts",
        "release_operations": "SELECT count(*) FROM release_operations",
        "publish_attempts": "SELECT count(*) FROM publish_attempts",
        "reconciliation_jobs": "SELECT count(*) FROM reconciliation_jobs",
    }
    return {
        name: int(connection.scalar(sa.text(statement)) or 0)
        for name, statement in statements.items()
    }


def _flywheel_state_counts() -> dict[str, int]:
    connection = op.get_bind()
    return {
        table: int(connection.scalar(sa.text(f"SELECT count(*) FROM {table}")) or 0)
        for table in (
            "flywheel_checkpoints",
            "flywheel_observations",
            "knowledge_gaps",
        )
    }


def _validate_downgrade_before_ddl() -> None:
    _validate_current_topology()

    unsafe_lifecycle = {
        name: count for name, count in _lifecycle_state_counts().items() if count
    }
    if unsafe_lifecycle:
        raise RuntimeError(
            "0006 downgrade refused before DDL: durable source lifecycle data exists "
            f"{unsafe_lifecycle}"
        )

    observed, _tombstone_sources = _observed_historical_revisions(op.get_bind())
    if observed:
        raise RuntimeError(
            "0006 downgrade refused before DDL: source-aware provenance cannot be "
            f"preserved by 0012 ({len(observed)} scoped source(s))"
        )

    if _destination_crosses(_PRE_SCOPE_REVISIONS):
        _validate_enterprise_scope_downgrade()

    if _destination_crosses(_PRE_RELEASE_REVISIONS):
        unsafe_release = {
            name: count for name, count in _release_state_counts().items() if count
        }
        if unsafe_release:
            raise RuntimeError(
                "0005 downgrade refused: release read-model data exists "
                f"{unsafe_release}"
            )

    if _destination_crosses(_PRE_FLYWHEEL_REVISIONS):
        unsafe_flywheel = {
            name: count for name, count in _flywheel_state_counts().items() if count
        }
        if unsafe_flywheel:
            raise RuntimeError(
                "0012 downgrade refused: durable flywheel data exists "
                f"{unsafe_flywheel}"
            )


def downgrade() -> None:
    _validate_downgrade_before_ddl()
    _drop_append_only_guards()
    with op.batch_alter_table(
        "source_heads", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.drop_constraint("fk_source_heads_last_event", type_="foreignkey")
    op.drop_index(
        "ix_source_lifecycle_issues_scope_status",
        table_name="source_lifecycle_backfill_issues",
    )
    op.drop_table("source_lifecycle_backfill_issues")
    op.drop_index("ix_source_events_scope_decision", table_name="source_events")
    op.drop_index("ix_source_events_source_time", table_name="source_events")
    op.drop_table("source_events")
    op.drop_index("ix_source_heads_scope_state", table_name="source_heads")
    op.drop_table("source_heads")
    with op.batch_alter_table(
        "change_items", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.drop_constraint("uq_change_items_change_set_id", type_="unique")
    with op.batch_alter_table(
        "change_sets", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.drop_constraint("uq_change_sets_space_id", type_="unique")
    with op.batch_alter_table(
        "knowledge_spaces", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.drop_constraint("uq_knowledge_spaces_scope_raw", type_="unique")
