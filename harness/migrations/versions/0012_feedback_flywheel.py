"""Space-scoped durable feedback flywheel (OpenSpec 015).

Revision ID: 0012
Revises: 0005
Create Date: 2026-07-18
"""

import sqlalchemy as sa
from alembic import context, op
from alembic.util.exc import CommandError

revision = "0012"
down_revision = "0005"
branch_labels = None
depends_on = None

LEGACY_SPACE_ID = "legacy-default"
_PRE_SCOPE_REVISIONS = {"0001", "0002"}
_PRE_RELEASE_REVISIONS = {"0001", "0002", "0003", "0004"}


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "flywheel_checkpoints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "space_id",
            sa.String(36),
            sa.ForeignKey("knowledge_spaces.id", name="fk_flywheel_checkpoint_space"),
            nullable=False,
        ),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("cursor", sa.String(512), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "space_id", "source_id", name="uq_flywheel_checkpoint_source"
        ),
    )
    op.create_table(
        "knowledge_gaps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "space_id",
            sa.String(36),
            sa.ForeignKey("knowledge_spaces.id", name="fk_knowledge_gaps_space"),
            nullable=False,
        ),
        sa.Column("gap_key", sa.String(512), nullable=False),
        sa.Column("product_id", sa.String(36), nullable=True),
        sa.Column("field_id", sa.String(128), nullable=True),
        sa.Column("concept_id", sa.String(36), nullable=True),
        sa.Column("signal_types", sa.JSON(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column("sample_trace_ids", sa.JSON(), nullable=False),
        sa.Column("sample_questions", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("space_id", "gap_key", name="uq_knowledge_gap_key"),
        sa.UniqueConstraint("space_id", "id", name="uq_knowledge_gaps_space_id"),
        sa.ForeignKeyConstraint(
            ["space_id", "product_id"],
            ["insurance_products.space_id", "insurance_products.id"],
            name="fk_knowledge_gap_space_product",
        ),
        sa.CheckConstraint("hit_count >= 0", name="ck_knowledge_gap_hit_count"),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'reopened')",
            name="ck_knowledge_gap_status",
        ),
    )
    op.create_index(
        "ix_knowledge_gaps_space_status",
        "knowledge_gaps",
        ["space_id", "status"],
    )
    op.create_table(
        "flywheel_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "space_id",
            sa.String(36),
            sa.ForeignKey("knowledge_spaces.id", name="fk_flywheel_observation_space"),
            nullable=False,
        ),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("trace_id", sa.String(255), nullable=False),
        sa.Column("trace_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("signal_types", sa.JSON(), nullable=False),
        sa.Column("alignment_reason", sa.String(32), nullable=False),
        sa.Column("product_id", sa.String(36), nullable=True),
        sa.Column("field_id", sa.String(128), nullable=True),
        sa.Column("concept_id", sa.String(36), nullable=True),
        sa.Column("gap_id", sa.String(36), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "space_id", "source_id", "trace_id", name="uq_flywheel_observation_trace"
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "gap_id"],
            ["knowledge_gaps.space_id", "knowledge_gaps.id"],
            name="fk_flywheel_observation_space_gap",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "product_id"],
            ["insurance_products.space_id", "insurance_products.id"],
            name="fk_flywheel_observation_space_product",
        ),
        sa.CheckConstraint(
            "alignment_reason IN "
            "('aligned', 'no_actionable_match', 'multi_product_ambiguity')",
            name="ck_flywheel_observation_alignment_reason",
        ),
    )
    op.create_index(
        "ix_flywheel_observations_unaligned",
        "flywheel_observations",
        ["space_id", "alignment_reason", "trace_timestamp"],
    )


def _destination_crosses(revisions: set[str]) -> bool:
    destination = context.get_revision_argument()
    if destination is None:
        return True
    if isinstance(destination, tuple):
        return any(revision_id in revisions for revision_id in destination)
    return destination in revisions


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


def downgrade() -> None:
    # A multi-revision downgrade invokes 0012 before older revisions can reject
    # incompatible state. SQLite DDL may auto-commit, so mirror every downstream
    # destructive preflight before dropping the first flywheel table.
    if _destination_crosses(_PRE_SCOPE_REVISIONS):
        _validate_enterprise_scope_downgrade()
    if _destination_crosses(_PRE_RELEASE_REVISIONS):
        unsafe_release = {
            name: count for name, count in _release_state_counts().items() if count
        }
        if unsafe_release:
            raise RuntimeError(
                f"0005 downgrade refused: release read-model data exists {unsafe_release}"
            )
    unsafe_flywheel = {
        name: count for name, count in _flywheel_state_counts().items() if count
    }
    if unsafe_flywheel:
        raise RuntimeError(
            f"0012 downgrade refused: durable flywheel data exists {unsafe_flywheel}"
        )

    op.drop_index(
        "ix_flywheel_observations_unaligned",
        table_name="flywheel_observations",
    )
    op.drop_table("flywheel_observations")
    op.drop_index("ix_knowledge_gaps_space_status", table_name="knowledge_gaps")
    op.drop_table("knowledge_gaps")
    op.drop_table("flywheel_checkpoints")
