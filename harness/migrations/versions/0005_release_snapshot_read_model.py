"""ReleaseSnapshot immutable read model and durable publish saga (OpenSpec 018).

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-15

Legacy snapshots stay current and auditable as read_model_version=0.  Historical
SnapshotFact rows are deliberately not fabricated from mutable Claim state.
"""

import sqlalchemy as sa
from alembic import context, op
from alembic.util.exc import CommandError

from insurance_harness.knowledge.release_guard_ddl_018 import (
    create_guard_statements,
    drop_guard_statements,
)

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
}

LEGACY_SPACE_ID = "legacy-default"
_PRE_SCOPE_REVISIONS = {"0001", "0002"}


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def _upgrade_release_snapshots() -> None:
    with op.batch_alter_table("release_snapshots", naming_convention=NAMING_CONVENTION) as batch:
        batch.add_column(
            sa.Column(
                "status",
                sa.String(16),
                nullable=False,
                server_default=sa.text("'published'"),
            )
        )
        batch.add_column(
            sa.Column(
                "read_model_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch.add_column(
            sa.Column("projection_frozen_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.alter_column(
            "published_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
        )
        batch.create_check_constraint(
            "ck_release_snapshots_status",
            "status IN ('building', 'publishing', 'published', 'failed')",
        )
        batch.create_check_constraint(
            "ck_release_snapshots_read_model_version",
            "read_model_version IN (0, 1)",
        )
        batch.create_index("ix_release_snapshots_status", ["status"], unique=False)

    # ``0`` exists only to backfill pre-0005 rows.  Every post-migration INSERT
    # that omits the column must be a version-1 release, including raw SQL.
    with op.batch_alter_table(
        "release_snapshots", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.alter_column(
            "status",
            existing_type=sa.String(16),
            existing_nullable=False,
            server_default=sa.text("'building'"),
        )
        batch.alter_column(
            "read_model_version",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default=sa.text("1"),
        )


def _create_snapshot_facts() -> None:
    op.create_table(
        "snapshot_facts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "space_id",
            sa.String(36),
            sa.ForeignKey("knowledge_spaces.id", name="fk_snapshot_facts_space"),
            nullable=False,
        ),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("claim_id", sa.String(36), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.String(36), nullable=False),
        sa.Column("product_version_id", sa.String(36), nullable=False),
        sa.Column("product_code", sa.String(64), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("version_label", sa.String(64), nullable=False),
        sa.Column("predicate", sa.String(128), nullable=False),
        sa.Column("field_name", sa.String(255), nullable=False),
        sa.Column("field_group", sa.String(64), nullable=False),
        sa.Column("value_state", sa.String(32), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "space_id",
            "snapshot_id",
            "claim_id",
            "revision_no",
            name="uq_snapshot_fact_claim_revision",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "snapshot_id"],
            ["release_snapshots.space_id", "release_snapshots.id"],
            name="fk_snapshot_facts_space_snapshot",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "claim_id"],
            ["claims.space_id", "claims.id"],
            name="fk_snapshot_facts_space_claim",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id", "revision_no"],
            ["claim_revisions.claim_id", "claim_revisions.revision_no"],
            name="fk_snapshot_facts_claim_revision",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "product_id"],
            ["insurance_products.space_id", "insurance_products.id"],
            name="fk_snapshot_facts_space_product",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "product_version_id"],
            ["product_versions.space_id", "product_versions.id"],
            name="fk_snapshot_facts_space_product_version",
        ),
        sa.CheckConstraint(
            "value_state IN ('present', 'absent_explicitly')",
            name="ck_snapshot_facts_value_state",
        ),
    )
    op.create_index(
        "ix_snapshot_facts_reader",
        "snapshot_facts",
        [
            "space_id",
            "snapshot_id",
            "product_id",
            "product_version_id",
            "predicate",
        ],
    )


def _create_release_operations() -> None:
    op.create_table(
        "release_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "space_id",
            sa.String(36),
            sa.ForeignKey("knowledge_spaces.id", name="fk_release_operations_space"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("base_snapshot_id", sa.String(36), nullable=True),
        sa.Column("target_snapshot_id", sa.String(36), nullable=True),
        sa.Column("parent_operation_id", sa.String(36), nullable=True),
        sa.Column("previous_operation_id", sa.String(36), nullable=True),
        sa.Column("publish_plan", sa.JSON(), nullable=True),
        sa.Column("plan_digest", sa.String(64), nullable=True),
        sa.Column("plan_frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_no", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("space_id", "id", name="uq_release_operations_space_id"),
        sa.ForeignKeyConstraint(
            ["space_id", "base_snapshot_id"],
            ["release_snapshots.space_id", "release_snapshots.id"],
            name="fk_release_operations_space_base_snapshot",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "target_snapshot_id"],
            ["release_snapshots.space_id", "release_snapshots.id"],
            name="fk_release_operations_space_target_snapshot",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "parent_operation_id"],
            ["release_operations.space_id", "release_operations.id"],
            name="fk_release_operations_space_parent",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "previous_operation_id"],
            ["release_operations.space_id", "release_operations.id"],
            name="fk_release_operations_space_previous",
        ),
        sa.CheckConstraint(
            "kind IN ('publish', 'rollback', 'reconcile')",
            name="ck_release_operations_kind",
        ),
        sa.CheckConstraint(
            "status IN ('building', 'running', 'succeeded', 'failed')",
            name="ck_release_operations_status",
        ),
        sa.CheckConstraint("retry_no >= 0", name="ck_release_operations_retry_no"),
    )
    op.create_index(
        "ix_release_operations_lease",
        "release_operations",
        ["status", "lease_expires_at"],
    )


def _create_publish_attempts() -> None:
    op.create_table(
        "publish_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "space_id",
            sa.String(36),
            sa.ForeignKey("knowledge_spaces.id", name="fk_publish_attempts_space"),
            nullable=False,
        ),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("retry_no", sa.Integer(), nullable=False),
        sa.Column("action_no", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("snapshot_id", sa.String(36), nullable=True),
        sa.Column("slug", sa.String(1024), nullable=False),
        sa.Column("created_new", sa.Boolean(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "space_id",
            "operation_id",
            "retry_no",
            "action_no",
            name="uq_publish_attempt_action",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "operation_id"],
            ["release_operations.space_id", "release_operations.id"],
            name="fk_publish_attempts_space_operation",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "snapshot_id"],
            ["release_snapshots.space_id", "release_snapshots.id"],
            name="fk_publish_attempts_space_snapshot",
        ),
        sa.CheckConstraint(
            "operation IN ('upsert', 'delete')",
            name="ck_publish_attempts_operation",
        ),
        sa.CheckConstraint(
            "status IN ('started', 'succeeded', 'failed', 'collision')",
            name="ck_publish_attempts_status",
        ),
        sa.CheckConstraint("retry_no >= 0", name="ck_publish_attempts_retry_no"),
        sa.CheckConstraint("action_no >= 0", name="ck_publish_attempts_action_no"),
    )
    op.create_index(
        "ix_publish_attempts_operation",
        "publish_attempts",
        ["operation_id", "retry_no"],
    )


def _create_reconciliation_jobs() -> None:
    op.create_table(
        "reconciliation_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "space_id",
            sa.String(36),
            sa.ForeignKey("knowledge_spaces.id", name="fk_reconciliation_jobs_space"),
            nullable=False,
        ),
        sa.Column("source_operation_id", sa.String(36), nullable=False),
        sa.Column("source_plan_digest", sa.String(64), nullable=False),
        sa.Column("reconcile_operation_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "space_id",
            "source_operation_id",
            name="uq_reconciliation_jobs_source_operation",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "source_operation_id"],
            ["release_operations.space_id", "release_operations.id"],
            name="fk_reconciliation_jobs_space_source_operation",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "reconcile_operation_id"],
            ["release_operations.space_id", "release_operations.id"],
            name="fk_reconciliation_jobs_space_reconcile_operation",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_reconciliation_jobs_status",
        ),
    )
    op.create_index(
        "ix_reconciliation_jobs_status",
        "reconciliation_jobs",
        ["space_id", "status"],
    )


def upgrade() -> None:
    _upgrade_release_snapshots()
    _create_snapshot_facts()
    _create_release_operations()
    _create_publish_attempts()
    _create_reconciliation_jobs()
    dialect_name = op.get_bind().dialect.name
    for statement in create_guard_statements(dialect_name):
        op.execute(sa.text(statement))


def _unsafe_downgrade_counts() -> dict[str, int]:
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


def _downgrade_crosses_enterprise_scope() -> bool:
    """Return whether this command will also execute the 0003 downgrade."""
    destination = context.get_revision_argument()
    if destination is None:
        return True
    if isinstance(destination, tuple):
        return any(revision_id in _PRE_SCOPE_REVISIONS for revision_id in destination)
    return destination in _PRE_SCOPE_REVISIONS


def _enterprise_scope_downgrade_conflicts() -> list[str]:
    """Mirror 0003's immutable compatibility checks before 0005 changes DDL."""
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
            "SELECT snapshot_id, claim_id, count(*) AS conflict_count FROM snapshot_claims "
            "GROUP BY snapshot_id, claim_id HAVING count(*) > 1",
        ),
    )
    conflicts = []
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
        conflicts.append(f"current_release singleton(rows={pointers!r}, count={len(pointers)})")
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
    conflicts = _enterprise_scope_downgrade_conflicts()
    if conflicts:
        raise CommandError(
            "cannot downgrade 0003 before DDL: global business-key conflicts: "
            + "; ".join(conflicts)
        )


def downgrade() -> None:
    # Alembic invokes each revision independently.  On SQLite, 0005 DDL is
    # otherwise durable before 0003 can reject an unsafe multi-revision
    # downgrade, violating 0003's fail-before-DDL contract.
    if _downgrade_crosses_enterprise_scope():
        _validate_enterprise_scope_downgrade()

    unsafe = {name: count for name, count in _unsafe_downgrade_counts().items() if count}
    if unsafe:
        raise RuntimeError(f"0005 downgrade refused: release read-model data exists {unsafe}")

    dialect_name = op.get_bind().dialect.name
    for statement in drop_guard_statements(dialect_name):
        op.execute(sa.text(statement))

    op.drop_index("ix_reconciliation_jobs_status", table_name="reconciliation_jobs")
    op.drop_table("reconciliation_jobs")
    op.drop_index("ix_publish_attempts_operation", table_name="publish_attempts")
    op.drop_table("publish_attempts")
    op.drop_index("ix_release_operations_lease", table_name="release_operations")
    op.drop_table("release_operations")
    op.drop_index("ix_snapshot_facts_reader", table_name="snapshot_facts")
    op.drop_table("snapshot_facts")

    with op.batch_alter_table("release_snapshots", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_index("ix_release_snapshots_status")
        batch.drop_constraint("ck_release_snapshots_read_model_version", type_="check")
        batch.drop_constraint("ck_release_snapshots_status", type_="check")
        batch.alter_column(
            "published_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
        batch.drop_column("projection_frozen_at")
        batch.drop_column("read_model_version")
        batch.drop_column("status")
