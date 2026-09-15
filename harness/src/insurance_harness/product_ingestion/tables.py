"""SQLAlchemy persistence for platform-owned product ingestion artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from insurance_harness.db.base import Base
from insurance_harness.db.models import _uuid


class ProductRun(Base):
    __tablename__ = "product_ingestion_runs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "space_id", "idempotency_key", name="uq_product_runs_idempotency"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128))
    space_id: Mapped[str] = mapped_column(String(36), index=True)
    raw_knowledge_base_id: Mapped[str] = mapped_column(String(128))
    wiki_knowledge_base_id: Mapped[str] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    retry_of_run_id: Mapped[str | None] = mapped_column(String(36))
    attempt: Mapped[int]
    retry_field_keys: Mapped[list[str]] = mapped_column(JSON)
    expected_upload_count: Mapped[int]
    upload_deadline_at: Mapped[datetime]
    uploads_sealed_at: Mapped[datetime | None]
    source_deadline_at: Mapped[datetime]
    state: Mapped[str] = mapped_column(String(32))
    version: Mapped[int]
    workflow_version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    uploads_sealed: Mapped[bool]
    created_at: Mapped[datetime]
    started_at: Mapped[datetime | None]
    root_job_id: Mapped[str | None] = mapped_column(String(36))


class ProductMaterial(Base):
    __tablename__ = "product_ingestion_materials"
    __table_args__ = (
        UniqueConstraint("run_id", "knowledge_id", name="uq_product_material_knowledge"),
        UniqueConstraint("run_id", "upload_ordinal", name="uq_product_material_ordinal"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128))
    space_id: Mapped[str] = mapped_column(String(36))
    knowledge_id: Mapped[str] = mapped_column(String(128))
    original_filename: Mapped[str] = mapped_column(String(1024))
    upload_ordinal: Mapped[int]
    source_revision_id: Mapped[str | None] = mapped_column(String(256))
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    native_manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    page_count: Mapped[int | None]
    inferred_material_role: Mapped[str | None] = mapped_column(String(64))
    product_identity_sha256: Mapped[str | None] = mapped_column(String(64))


class ProductStage(Base):
    __tablename__ = "product_ingestion_stages"
    __table_args__ = (
        UniqueConstraint("run_id", "stage_key", name="uq_product_stage_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    space_id: Mapped[str] = mapped_column(String(36))
    stage_key: Mapped[str] = mapped_column(String(128))
    dependency_sha256: Mapped[str] = mapped_column(String(64))
    job_id: Mapped[str] = mapped_column(String(36), unique=True)
    parent_job_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime]


class ProductWindow(Base):
    __tablename__ = "product_ingestion_windows"
    __table_args__ = (
        UniqueConstraint("run_id", "stage_key", "window_key", name="uq_product_window_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    space_id: Mapped[str] = mapped_column(String(36))
    stage_key: Mapped[str] = mapped_column(String(128))
    window_key: Mapped[str] = mapped_column(String(128))
    dependency_sha256: Mapped[str] = mapped_column(String(64))
    tasks: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    job_id: Mapped[str] = mapped_column(String(36), unique=True)
    created_at: Mapped[datetime]
    selected_field_keys: Mapped[list[list[str]] | None] = mapped_column(JSON)
    cached_attempt_ids: Mapped[list[str] | None] = mapped_column(JSON)
    reservation_generation: Mapped[int | None]
    reserved_at: Mapped[datetime | None]


class ProductStageSettlement(Base):
    __tablename__ = "product_ingestion_stage_settlements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    stage_id: Mapped[str] = mapped_column(String(36), unique=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    space_id: Mapped[str] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(32))
    success_count: Mapped[int]
    missing_count: Mapped[int]
    failure_count: Mapped[int]
    model_call_count: Mapped[int]
    usage: Mapped[dict[str, int]] = mapped_column(JSON)
    finished_at: Mapped[datetime]


class ProductModelCall(Base):
    __tablename__ = "product_ingestion_calls"
    __table_args__ = (
        UniqueConstraint("space_id", "call_id", name="uq_product_call_scope"),
        UniqueConstraint("window_id", name="uq_product_call_window"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    call_id: Mapped[str] = mapped_column(String(128))
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    window_id: Mapped[str] = mapped_column(String(36))
    space_id: Mapped[str] = mapped_column(String(36))
    job_id: Mapped[str] = mapped_column(String(36))
    generation: Mapped[int]
    attempt: Mapped[int]
    state: Mapped[str] = mapped_column(String(16))
    request_sha256: Mapped[str | None] = mapped_column(String(64))
    request_bytes: Mapped[bytes | None] = mapped_column(LargeBinary)
    raw: Mapped[bytes | None] = mapped_column(LargeBinary)
    raw_sha256: Mapped[str | None] = mapped_column(String(64))
    raw_ref: Mapped[str] = mapped_column(String(512))
    diagnostic: Mapped[str | None] = mapped_column(Text)
    reserved_at: Mapped[datetime]
    dispatched_at: Mapped[datetime | None]
    recorded_at: Mapped[datetime | None]
    selected_field_keys: Mapped[list[list[str]]] = mapped_column(JSON)
    cached_attempt_ids: Mapped[list[str]] = mapped_column(JSON)


class ProductFieldAttempt(Base):
    __tablename__ = "product_ingestion_field_attempts"
    __table_args__ = (
        UniqueConstraint("window_id", "entity_id", "field_key", name="uq_product_window_field"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    window_id: Mapped[str] = mapped_column(String(36))
    call_id: Mapped[str] = mapped_column(String(128))
    tenant_id: Mapped[str] = mapped_column(String(128))
    space_id: Mapped[str] = mapped_column(String(36), index=True)
    entity_id: Mapped[str] = mapped_column(String(256))
    field_key: Mapped[str] = mapped_column(String(256))
    task_sha256: Mapped[str] = mapped_column(String(64))
    cache_key: Mapped[str] = mapped_column(String(64), index=True)
    cache_identity: Mapped[dict[str, Any]] = mapped_column(JSON)
    validation_version: Mapped[str] = mapped_column(String(256))
    model_policy_sha256: Mapped[str] = mapped_column(String(64))
    prompt_policy_sha256: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(Text)
    validated_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    raw_ref: Mapped[str] = mapped_column(String(512))
    attempt: Mapped[int]
    created_at: Mapped[datetime]
    reused_from_attempt_id: Mapped[str | None] = mapped_column(String(36))


class ProductWindowSettlement(Base):
    __tablename__ = "product_ingestion_window_settlements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    window_id: Mapped[str] = mapped_column(String(36), unique=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    space_id: Mapped[str] = mapped_column(String(36))
    success_count: Mapped[int]
    missing_count: Mapped[int]
    failure_count: Mapped[int]
    usage: Mapped[dict[str, int]] = mapped_column(JSON)
    finished_at: Mapped[datetime]


class ProductRunFinalization(Base):
    __tablename__ = "product_ingestion_run_finalizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), unique=True)
    space_id: Mapped[str] = mapped_column(String(36), index=True)
    state: Mapped[str] = mapped_column(String(32))
    success_count: Mapped[int]
    missing_count: Mapped[int]
    failure_count: Mapped[int]
    model_call_count: Mapped[int]
    usage: Mapped[dict[str, int]] = mapped_column(JSON)
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime]
