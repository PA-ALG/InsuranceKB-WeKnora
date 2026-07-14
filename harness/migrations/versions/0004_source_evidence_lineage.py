"""Source-aware ClaimEvidence lineage (OpenSpec 017).

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-14

The columns are nullable so rows created before 017 remain readable. Downgrade
drops the audit data while preserving the legacy Evidence fields.
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
}


def upgrade() -> None:
    with op.batch_alter_table(
        "claim_evidence", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.add_column(sa.Column("raw_kb_id", sa.String(255), nullable=True))
        batch.add_column(sa.Column("source_revision", sa.String(64), nullable=True))
        batch.add_column(sa.Column("file_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("original_digest", sa.String(64), nullable=True))
        batch.add_column(sa.Column("parser_version", sa.String(255), nullable=True))
        batch.add_column(sa.Column("chunk_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("lineage_status", sa.String(16), nullable=True))
        batch.add_column(sa.Column("stale_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint(
            "ck_evidence_lineage_status",
            "lineage_status IS NULL OR "
            "lineage_status IN ('linked', 'page_only', 'ambiguous')",
        )
        batch.create_check_constraint(
            "ck_evidence_source_audit",
            "(lineage_status IS NULL AND raw_kb_id IS NULL "
            "AND source_revision IS NULL AND file_hash IS NULL "
            "AND original_digest IS NULL AND parser_version IS NULL "
            "AND chunk_hash IS NULL AND stale_at IS NULL) OR "
            "(lineage_status IS NOT NULL AND raw_kb_id IS NOT NULL "
            "AND source_revision IS NOT NULL AND file_hash IS NOT NULL "
            "AND original_digest IS NOT NULL AND parser_version IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_evidence_chunk_shape",
            "lineage_status IS NULL OR "
            "(lineage_status = 'linked' AND chunk_id IS NOT NULL "
            "AND chunk_hash IS NOT NULL) OR "
            "(lineage_status IN ('page_only', 'ambiguous') "
            "AND chunk_id IS NULL AND chunk_hash IS NULL)",
        )
        batch.create_index(
            "ix_evidence_source_revision",
            ["knowledge_id", "source_revision"],
            unique=False,
        )
        batch.create_index(
            "ix_evidence_stale", ["stale_at", "knowledge_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "claim_evidence", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.drop_index("ix_evidence_stale")
        batch.drop_index("ix_evidence_source_revision")
        batch.drop_constraint("ck_evidence_chunk_shape", type_="check")
        batch.drop_constraint("ck_evidence_source_audit", type_="check")
        batch.drop_constraint("ck_evidence_lineage_status", type_="check")
        batch.drop_column("stale_at")
        batch.drop_column("lineage_status")
        batch.drop_column("chunk_hash")
        batch.drop_column("parser_version")
        batch.drop_column("original_digest")
        batch.drop_column("file_hash")
        batch.drop_column("source_revision")
        batch.drop_column("raw_kb_id")
