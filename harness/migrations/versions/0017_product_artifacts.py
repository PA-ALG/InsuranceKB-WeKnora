"""G3 non-field immutable artifacts and model-call checkpoints.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_ingestion_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("space_id", sa.String(36), nullable=False),
        sa.Column("stage_key", sa.String(128), nullable=False),
        sa.Column("artifact_kind", sa.String(128), nullable=False),
        sa.Column("artifact_key", sa.String(256), nullable=False),
        sa.Column("contract_name", sa.String(128), nullable=False),
        sa.Column("contract_version", sa.String(64), nullable=False),
        sa.Column("dependency_sha256", sa.String(64), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("origin_call_id", sa.String(128), nullable=True),
        sa.Column("producer_job_id", sa.String(36), nullable=False),
        sa.Column("producer_generation", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "artifact_kind",
            "artifact_key",
            name="uq_product_artifact_identity",
        ),
    )
    op.create_index(
        "ix_product_ingestion_artifacts_run_id",
        "product_ingestion_artifacts",
        ["run_id"],
    )
    op.create_index(
        "ix_product_ingestion_artifacts_space_id",
        "product_ingestion_artifacts",
        ["space_id"],
    )

    op.create_table(
        "product_ingestion_stage_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("call_id", sa.String(128), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("space_id", sa.String(36), nullable=False),
        sa.Column("stage_key", sa.String(128), nullable=False),
        sa.Column("operation_key", sa.String(128), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("dependency_sha256", sa.String(64), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("model_policy_sha256", sa.String(64), nullable=False),
        sa.Column("prompt_policy_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=True),
        sa.Column("request_bytes", sa.LargeBinary(), nullable=True),
        sa.Column("raw", sa.LargeBinary(), nullable=True),
        sa.Column("raw_sha256", sa.String(64), nullable=True),
        sa.Column("raw_ref", sa.String(512), nullable=False),
        sa.Column("diagnostic", sa.Text(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("space_id", "call_id", name="uq_product_stage_call_scope"),
        sa.UniqueConstraint(
            "run_id",
            "stage_key",
            "operation_key",
            name="uq_product_stage_call_operation",
        ),
    )
    op.create_index(
        "ix_product_ingestion_stage_calls_run_id",
        "product_ingestion_stage_calls",
        ["run_id"],
    )
    op.create_index(
        "ix_product_ingestion_stage_calls_space_id",
        "product_ingestion_stage_calls",
        ["space_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_ingestion_stage_calls_space_id",
        table_name="product_ingestion_stage_calls",
    )
    op.drop_index(
        "ix_product_ingestion_stage_calls_run_id",
        table_name="product_ingestion_stage_calls",
    )
    op.drop_table("product_ingestion_stage_calls")
    op.drop_index(
        "ix_product_ingestion_artifacts_space_id",
        table_name="product_ingestion_artifacts",
    )
    op.drop_index(
        "ix_product_ingestion_artifacts_run_id",
        table_name="product_ingestion_artifacts",
    )
    op.drop_table("product_ingestion_artifacts")
