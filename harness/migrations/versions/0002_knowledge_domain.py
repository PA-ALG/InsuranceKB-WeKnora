"""知识域表（change 007，docs/insurance-kb/03 §8 剩余部分）

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "claims",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("subject_type", sa.String(32), nullable=False),
        sa.Column("product_version_id", sa.String(36), sa.ForeignKey("product_versions.id")),
        sa.Column("concept_id", sa.String(36)),
        sa.Column("predicate", sa.String(128), nullable=False),
        sa.Column("value_state", sa.String(32), nullable=False),
        sa.Column("value", sa.JSON()),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_to", sa.Date()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("extraction_method", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("superseded_by", sa.String(36), sa.ForeignKey("claims.id")),
        sa.Column("pending_judge", sa.Boolean(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_claims_status", "claims", ["status"])
    op.create_index("ix_claims_schema_version", "claims", ["schema_version"])
    op.create_index("ix_claims_version", "claims", ["product_version_id"])
    op.create_index("ix_claims_subject", "claims", ["product_version_id", "predicate"])
    # 发布态部分唯一索引（03 §8）：NULL 维度不去重，应用层兜底
    op.create_index(
        "uq_claims_published",
        "claims",
        ["product_version_id", "concept_id", "predicate", "effective_from"],
        unique=True,
        sqlite_where=sa.text("status = 'published'"),
        postgresql_where=sa.text("status = 'published'"),
    )

    op.create_table(
        "claim_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("claim_id", sa.String(36), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("knowledge_id", sa.String(255), nullable=False),
        sa.Column("chunk_id", sa.String(64)),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer()),
        sa.Column("section", sa.String(255)),
        sa.Column("table_ref", sa.String(255)),
        sa.Column("timestamp_ms", sa.Integer()),
        sa.Column("authority_level", sa.Integer(), nullable=False),
        sa.Column("doc_role", sa.String(32), nullable=False),
        sa.Column("extraction_method", sa.String(32), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_evidence_claim", "claim_evidence", ["claim_id"])
    op.create_index("ix_evidence_knowledge", "claim_evidence", ["knowledge_id"])

    op.create_table(
        "claim_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("claim_id", sa.String(36), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("before", sa.JSON()),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("change_item_id", sa.String(36)),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("reason", sa.String(255)),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("claim_id", "revision_no", name="uq_claim_revision"),
    )
    op.create_index("ix_revisions_claim", "claim_revisions", ["claim_id"])

    op.create_table(
        "change_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("knowledge_ids", sa.JSON()),
        sa.Column("external_record_id", sa.String(128)),
        sa.Column("source_revision", sa.String(64)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "source_kind", "external_record_id", "source_revision", name="uq_changeset_source"
        ),
    )

    op.create_table(
        "change_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("change_set_id", sa.String(36), sa.ForeignKey("change_sets.id"), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("claim_id", sa.String(36), sa.ForeignKey("claims.id")),
        sa.Column("proposed", sa.JSON(), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("decision_basis", sa.JSON()),
        *_timestamps(),
    )
    op.create_index("ix_items_changeset", "change_items", ["change_set_id"])

    op.create_table(
        "conflicts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "change_item_id", sa.String(36), sa.ForeignKey("change_items.id"), nullable=False
        ),
        sa.Column("existing_claim_id", sa.String(36), sa.ForeignKey("claims.id")),
        sa.Column("proposed", sa.JSON(), nullable=False),
        sa.Column("decision_basis", sa.JSON()),
        sa.Column("status", sa.String(32), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_conflicts_status", "conflicts", ["status"])

    op.create_table(
        "review_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("review_key", sa.String(64), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("subject", sa.JSON(), nullable=False),
        sa.Column("allowed_actions", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("resolution", sa.JSON()),
        sa.Column("risk_level", sa.String(16), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("review_key", name="uq_review_key"),
    )
    op.create_index("ix_review_status_risk", "review_items", ["status", "risk_level"])

    op.create_table(
        "release_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("rendered_pages", sa.JSON()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_by", sa.String(128), nullable=False),
        sa.Column("notes", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint("label", name="uq_snapshot_label"),
    )

    op.create_table(
        "snapshot_claims",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "snapshot_id", sa.String(36), sa.ForeignKey("release_snapshots.id"), nullable=False
        ),
        sa.Column("claim_id", sa.String(36), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("snapshot_id", "claim_id", name="uq_snapshot_claim"),
    )
    op.create_index("ix_snapshot_claims_snapshot", "snapshot_claims", ["snapshot_id"])

    op.create_table(
        "current_release",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column(
            "snapshot_id", sa.String(36), sa.ForeignKey("release_snapshots.id"), nullable=False
        ),
        *_timestamps(),
    )


def downgrade() -> None:
    op.drop_table("current_release")
    op.drop_index("ix_snapshot_claims_snapshot", table_name="snapshot_claims")
    op.drop_table("snapshot_claims")
    op.drop_table("release_snapshots")
    op.drop_index("ix_review_status_risk", table_name="review_items")
    op.drop_table("review_items")
    op.drop_index("ix_conflicts_status", table_name="conflicts")
    op.drop_table("conflicts")
    op.drop_index("ix_items_changeset", table_name="change_items")
    op.drop_table("change_items")
    op.drop_table("change_sets")
    op.drop_index("ix_revisions_claim", table_name="claim_revisions")
    op.drop_table("claim_revisions")
    op.drop_index("ix_evidence_knowledge", table_name="claim_evidence")
    op.drop_index("ix_evidence_claim", table_name="claim_evidence")
    op.drop_table("claim_evidence")
    op.drop_index("uq_claims_published", table_name="claims")
    op.drop_index("ix_claims_subject", table_name="claims")
    op.drop_index("ix_claims_version", table_name="claims")
    op.drop_index("ix_claims_schema_version", table_name="claims")
    op.drop_index("ix_claims_status", table_name="claims")
    op.drop_table("claims")
