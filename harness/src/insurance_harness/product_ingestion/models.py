"""Strict DTOs for durable G3 product ingestion."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProductRunState(StrEnum):
    ACCEPTING_UPLOADS = "accepting_uploads"
    AWAITING_SOURCES = "awaiting_sources"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    NEEDS_CONFIRMATION = "needs_confirmation"


class FieldOutcomeKind(StrEnum):
    VERIFIED = "verified"
    NOT_PROVIDED = "not_provided"
    EXTRACTION_FAILED = "extraction_failed"


class CallState(StrEnum):
    RESERVED = "reserved"
    DISPATCHING = "dispatching"
    RECORDED = "recorded"
    INTERRUPTED = "interrupted"


class WindowReservationAction(StrEnum):
    DISPATCH = "dispatch"
    RECORDED = "recorded"
    INTERRUPTED = "interrupted"
    ALL_CACHED = "all_cached"


class ProductScope(_FrozenModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    space_id: str = Field(min_length=1, max_length=36)
    raw_knowledge_base_id: str = Field(min_length=1, max_length=128)
    wiki_knowledge_base_id: str = Field(min_length=1, max_length=128)


class SourceDependency(_FrozenModel):
    source_revision_id: str = Field(min_length=1, max_length=256)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FieldCacheIdentity(_FrozenModel):
    """Business dependency key; execution-policy identities are provenance only."""

    product_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    entity_id: str = Field(min_length=1, max_length=256)
    field_key: str = Field(min_length=1, max_length=256)
    source_dependencies: tuple[SourceDependency, ...] = Field(min_length=1)
    schema_adapter_id: str = Field(min_length=1, max_length=256)
    schema_adapter_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def _unique_sources(self) -> FieldCacheIdentity:
        pairs = [(item.source_revision_id, item.source_sha256) for item in self.source_dependencies]
        if len(pairs) != len(set(pairs)):
            raise ValueError("source_dependencies must be unique")
        return self

    @property
    def cache_key(self) -> str:
        payload = self.model_dump(mode="json")
        payload["source_dependencies"] = sorted(
            payload["source_dependencies"],
            key=lambda item: (item["source_revision_id"], item["source_sha256"]),
        )
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(b"g3-field-cache.830.v1\0" + encoded).hexdigest()


class OriginalKnowledgeRef(_FrozenModel):
    knowledge_id: str = Field(min_length=1, max_length=128)
    original_filename: str = Field(min_length=1, max_length=1024)
    upload_ordinal: int = Field(ge=0)


class SealedSourceRef(_FrozenModel):
    knowledge_id: str = Field(min_length=1, max_length=128)
    source_revision_id: str = Field(min_length=1, max_length=256)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    native_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(ge=1)
    inferred_material_role: str = Field(min_length=1, max_length=64)
    product_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class WindowTaskSpec(_FrozenModel):
    entity_id: str = Field(min_length=1, max_length=256)
    field_key: str = Field(min_length=1, max_length=256)
    task_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cache_identity: FieldCacheIdentity
    validation_version: str = Field(min_length=1, max_length=256)
    model_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_payload: dict[str, Any]

    @model_validator(mode="after")
    def _same_field(self) -> WindowTaskSpec:
        if (self.entity_id, self.field_key) != (
            self.cache_identity.entity_id,
            self.cache_identity.field_key,
        ):
            raise ValueError("task and cache identity must address the same field")
        return self


class FieldOutcomeWrite(_FrozenModel):
    entity_id: str | None = None
    field_key: str = Field(min_length=1, max_length=256)
    task_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cache_identity: FieldCacheIdentity
    outcome: FieldOutcomeKind
    reason: str | None = None
    validated_result: dict[str, Any] | None = None
    raw_ref: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def _valid_shape(self) -> FieldOutcomeWrite:
        if self.entity_id is not None and self.entity_id != self.cache_identity.entity_id:
            raise ValueError("entity_id does not match cache identity")
        if self.field_key != self.cache_identity.field_key:
            raise ValueError("field_key does not match cache identity")
        if self.outcome in {FieldOutcomeKind.VERIFIED, FieldOutcomeKind.NOT_PROVIDED}:
            if self.validated_result is None:
                raise ValueError("validated outcomes require validated_result")
        elif self.validated_result is not None or not (self.reason or "").strip():
            raise ValueError("extraction_failed requires reason and no validated_result")
        return self


class MaterialSnapshot(_FrozenModel):
    material_id: str
    knowledge_id: str
    original_filename: str
    upload_ordinal: int
    source: SealedSourceRef | None


class ProductRunScanEntry(_FrozenModel):
    """Identity-only cursor entry for background reconciliation."""

    run_id: str
    created_at: datetime


class ProductRunSnapshot(_FrozenModel):
    run_id: str
    scope: ProductScope
    state: ProductRunState
    version: int
    workflow_version: Literal[1, 2] = 1
    retry_of_run_id: str | None
    attempt: int
    retry_field_keys: tuple[str, ...]
    expected_upload_count: int
    upload_deadline_at: datetime
    uploads_sealed_at: datetime | None
    source_deadline_at: datetime
    materials: tuple[MaterialSnapshot, ...]
    success_count: int
    missing_count: int
    failure_count: int
    model_call_count: int
    usage: dict[str, int]
    terminal_reason: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class WindowSnapshot(_FrozenModel):
    window_id: str
    job_id: str
    run_id: str
    stage_key: str
    window_key: str
    tasks: tuple[WindowTaskSpec, ...]


class StageSnapshot(_FrozenModel):
    stage_id: str
    run_id: str
    stage_key: str
    dependency_sha256: str
    job_id: str
    parent_job_id: str | None
    state: str
    success_count: int
    missing_count: int
    failure_count: int
    model_call_count: int
    usage: dict[str, int]
    started_at: datetime | None
    finished_at: datetime | None


class CallSnapshot(_FrozenModel):
    call_id: str
    run_id: str
    job_id: str
    generation: int
    attempt: int
    state: CallState
    request_sha256: str | None
    request_bytes: bytes | None
    raw: bytes | None
    raw_sha256: str | None
    raw_ref: str
    diagnostic: str | None
    reserved_at: datetime
    dispatched_at: datetime | None
    recorded_at: datetime | None
    selected_field_keys: tuple[tuple[str, str], ...]
    cached_attempt_ids: tuple[str, ...]


class FieldAttemptSnapshot(_FrozenModel):
    attempt_id: str
    run_id: str
    window_id: str
    call_id: str
    entity_id: str
    field_key: str
    task_sha256: str
    cache_identity: FieldCacheIdentity
    validation_version: str
    model_policy_sha256: str
    prompt_policy_sha256: str
    outcome: FieldOutcomeKind
    reason: str | None
    validated_result: dict[str, Any] | None
    raw_ref: str
    attempt: int
    created_at: datetime
    reused_from_attempt_id: str | None


class WindowSettlement(_FrozenModel):
    success_count: int
    missing_count: int
    failure_count: int


class WindowReservation(_FrozenModel):
    action: WindowReservationAction
    call: CallSnapshot | None
    dispatch_tasks: tuple[WindowTaskSpec, ...]
    cached: tuple[FieldAttemptSnapshot, ...] = ()
    outcomes: tuple[FieldOutcomeWrite, ...] = ()
