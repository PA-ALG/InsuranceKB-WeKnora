"""G3 platform product-ingestion durable artifacts.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_ingestion_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("space_id", sa.String(36), nullable=False),
        sa.Column("raw_knowledge_base_id", sa.String(128), nullable=False),
        sa.Column("wiki_knowledge_base_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("retry_of_run_id", sa.String(36), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("retry_field_keys", sa.JSON(), nullable=False),
        sa.Column("expected_upload_count", sa.Integer(), nullable=False),
        sa.Column("upload_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploads_sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("uploads_sealed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("root_job_id", sa.String(36), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "space_id", "idempotency_key", name="uq_product_runs_idempotency"
        ),
    )
    op.create_index("ix_product_ingestion_runs_space_id", "product_ingestion_runs", ["space_id"])

    op.create_table(
        "product_ingestion_materials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("space_id", sa.String(36), nullable=False),
        sa.Column("knowledge_id", sa.String(128), nullable=False),
        sa.Column("original_filename", sa.String(1024), nullable=False),
        sa.Column("upload_ordinal", sa.Integer(), nullable=False),
        sa.Column("source_revision_id", sa.String(256), nullable=True),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column("file_sha256", sa.String(64), nullable=True),
        sa.Column("native_manifest_sha256", sa.String(64), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("inferred_material_role", sa.String(64), nullable=True),
        sa.Column("product_identity_sha256", sa.String(64), nullable=True),
        sa.UniqueConstraint("run_id", "knowledge_id", name="uq_product_material_knowledge"),
        sa.UniqueConstraint("run_id", "upload_ordinal", name="uq_product_material_ordinal"),
    )
    op.create_index(
        "ix_product_ingestion_materials_run_id", "product_ingestion_materials", ["run_id"]
    )

    op.create_table(
        "product_ingestion_stages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("space_id", sa.String(36), nullable=False),
        sa.Column("stage_key", sa.String(128), nullable=False),
        sa.Column("dependency_sha256", sa.String(64), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False, unique=True),
        sa.Column("parent_job_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "stage_key", name="uq_product_stage_key"),
    )
    op.create_index("ix_product_ingestion_stages_run_id", "product_ingestion_stages", ["run_id"])

    op.create_table(
        "product_ingestion_windows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("space_id", sa.String(36), nullable=False),
        sa.Column("stage_key", sa.String(128), nullable=False),
        sa.Column("window_key", sa.String(128), nullable=False),
        sa.Column("dependency_sha256", sa.String(64), nullable=False),
        sa.Column("tasks", sa.JSON(), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("selected_field_keys", sa.JSON(), nullable=True),
        sa.Column("cached_attempt_ids", sa.JSON(), nullable=True),
        sa.Column("reservation_generation", sa.Integer(), nullable=True),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "run_id", "stage_key", "window_key", name="uq_product_window_key"
        ),
    )
    op.create_index("ix_product_ingestion_windows_run_id", "product_ingestion_windows", ["run_id"])

    op.create_table(
        "product_ingestion_stage_settlements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("stage_id", sa.String(36), nullable=False, unique=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("space_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("missing_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("model_call_count", sa.Integer(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_product_ingestion_stage_settlements_run_id",
        "product_ingestion_stage_settlements",
        ["run_id"],
    )

    op.create_table(
        "product_ingestion_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("call_id", sa.String(128), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("window_id", sa.String(36), nullable=False),
        sa.Column("space_id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=True),
        sa.Column("request_bytes", sa.LargeBinary(), nullable=True),
        sa.Column("raw", sa.LargeBinary(), nullable=True),
        sa.Column("raw_sha256", sa.String(64), nullable=True),
        sa.Column("raw_ref", sa.String(512), nullable=False),
        sa.Column("diagnostic", sa.Text(), nullable=True),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("selected_field_keys", sa.JSON(), nullable=False),
        sa.Column("cached_attempt_ids", sa.JSON(), nullable=False),
        sa.UniqueConstraint("space_id", "call_id", name="uq_product_call_scope"),
        sa.UniqueConstraint("window_id", name="uq_product_call_window"),
    )
    op.create_index("ix_product_ingestion_calls_run_id", "product_ingestion_calls", ["run_id"])

    op.create_table(
        "product_ingestion_field_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("window_id", sa.String(36), nullable=False),
        sa.Column("call_id", sa.String(128), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("space_id", sa.String(36), nullable=False),
        sa.Column("entity_id", sa.String(256), nullable=False),
        sa.Column("field_key", sa.String(256), nullable=False),
        sa.Column("task_sha256", sa.String(64), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("cache_identity", sa.JSON(), nullable=False),
        sa.Column("validation_version", sa.String(256), nullable=False),
        sa.Column("model_policy_sha256", sa.String(64), nullable=False),
        sa.Column("prompt_policy_sha256", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("validated_result", sa.JSON(), nullable=True),
        sa.Column("raw_ref", sa.String(512), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reused_from_attempt_id", sa.String(36), nullable=True),
        sa.UniqueConstraint(
            "window_id", "entity_id", "field_key", name="uq_product_window_field"
        ),
    )
    op.create_index(
        "ix_product_ingestion_field_attempts_run_id",
        "product_ingestion_field_attempts",
        ["run_id"],
    )
    op.create_index(
        "ix_product_ingestion_field_attempts_space_id",
        "product_ingestion_field_attempts",
        ["space_id"],
    )
    op.create_index(
        "ix_product_ingestion_field_attempts_cache_key",
        "product_ingestion_field_attempts",
        ["cache_key"],
    )

    op.create_table(
        "product_ingestion_window_settlements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("window_id", sa.String(36), nullable=False, unique=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("space_id", sa.String(36), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("missing_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_product_ingestion_window_settlements_run_id",
        "product_ingestion_window_settlements",
        ["run_id"],
    )

    op.create_table(
        "product_ingestion_run_finalizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False, unique=True),
        sa.Column("space_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("missing_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("model_call_count", sa.Integer(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_product_ingestion_run_finalizations_space_id",
        "product_ingestion_run_finalizations",
        ["space_id"],
    )


def downgrade() -> None:
    op.drop_table("product_ingestion_run_finalizations")
    op.drop_table("product_ingestion_window_settlements")
    op.drop_table("product_ingestion_field_attempts")
    op.drop_table("product_ingestion_calls")
    op.drop_table("product_ingestion_stage_settlements")
    op.drop_table("product_ingestion_windows")
    op.drop_table("product_ingestion_stages")
    op.drop_table("product_ingestion_materials")
    op.drop_table("product_ingestion_runs")
