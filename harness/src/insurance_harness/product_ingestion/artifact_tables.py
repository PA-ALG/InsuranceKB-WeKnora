"""ORM tables for non-field product artifacts and model-call checkpoints."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from insurance_harness.db.base import Base
from insurance_harness.db.models import _uuid


class ProductArtifact(Base):
    __tablename__ = "product_ingestion_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "artifact_kind",
            "artifact_key",
            name="uq_product_artifact_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    space_id: Mapped[str] = mapped_column(String(36), index=True)
    stage_key: Mapped[str] = mapped_column(String(128))
    artifact_kind: Mapped[str] = mapped_column(String(128))
    artifact_key: Mapped[str] = mapped_column(String(256))
    contract_name: Mapped[str] = mapped_column(String(128))
    contract_version: Mapped[str] = mapped_column(String(64))
    dependency_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(32))
    origin_call_id: Mapped[str | None] = mapped_column(String(128))
    producer_job_id: Mapped[str] = mapped_column(String(36))
    producer_generation: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProductStageModelCall(Base):
    __tablename__ = "product_ingestion_stage_calls"
    __table_args__ = (
        UniqueConstraint("space_id", "call_id", name="uq_product_stage_call_scope"),
        UniqueConstraint(
            "run_id",
            "stage_key",
            "operation_key",
            name="uq_product_stage_call_operation",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    call_id: Mapped[str] = mapped_column(String(128))
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    space_id: Mapped[str] = mapped_column(String(36), index=True)
    stage_key: Mapped[str] = mapped_column(String(128))
    operation_key: Mapped[str] = mapped_column(String(128))
    job_id: Mapped[str] = mapped_column(String(36))
    generation: Mapped[int]
    attempt: Mapped[int]
    dependency_sha256: Mapped[str] = mapped_column(String(64))
    input_sha256: Mapped[str] = mapped_column(String(64))
    model_policy_sha256: Mapped[str] = mapped_column(String(64))
    prompt_policy_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    request_sha256: Mapped[str | None] = mapped_column(String(64))
    request_bytes: Mapped[bytes | None] = mapped_column(LargeBinary)
    raw: Mapped[bytes | None] = mapped_column(LargeBinary)
    raw_sha256: Mapped[str | None] = mapped_column(String(64))
    raw_ref: Mapped[str] = mapped_column(String(512))
    diagnostic: Mapped[str | None] = mapped_column(Text)
    usage: Mapped[dict[str, int]] = mapped_column(JSON)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
