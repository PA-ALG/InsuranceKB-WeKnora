"""Strict DTOs for immutable non-field artifacts and their model calls."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ArtifactOrigin(StrEnum):
    MODEL = "model"
    RULE = "rule"
    PLATFORM_SOURCE = "platform_source"


class StageCallState(StrEnum):
    RESERVED = "reserved"
    DISPATCHED = "dispatched"
    RECORDED = "recorded"
    INTERRUPTED = "interrupted"


class StageCallAction(StrEnum):
    DISPATCH = "dispatch"
    RECORDED = "recorded"
    INTERRUPTED = "interrupted"


class ArtifactDraft(_FrozenModel):
    artifact_kind: str = Field(min_length=1, max_length=128)
    artifact_key: str = Field(min_length=1, max_length=256)
    contract_name: str = Field(min_length=1, max_length=128)
    contract_version: str = Field(min_length=1, max_length=64)
    dependency_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: bytes = Field(min_length=1)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    origin: ArtifactOrigin
    origin_call_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def _validated_origin_and_hash(self) -> ArtifactDraft:
        identity_values = (
            self.artifact_kind,
            self.artifact_key,
            self.contract_name,
            self.contract_version,
        )
        if any("\x00" in item for item in identity_values):
            raise ValueError("artifact identity must not contain NUL")
        if hashlib.sha256(self.payload).hexdigest() != self.payload_sha256:
            raise ValueError("payload does not match payload_sha256")
        if self.origin is ArtifactOrigin.MODEL and self.origin_call_id is None:
            raise ValueError("model artifact requires origin_call_id")
        if self.origin is not ArtifactOrigin.MODEL and self.origin_call_id is not None:
            raise ValueError("non-model artifact cannot claim an origin_call_id")
        return self


class ArtifactSnapshot(_FrozenModel):
    artifact_id: str
    run_id: str
    stage_key: str
    artifact_kind: str
    artifact_key: str
    contract_name: str
    contract_version: str
    dependency_sha256: str
    payload: bytes
    payload_sha256: str
    origin: ArtifactOrigin
    origin_call_id: str | None
    producer_job_id: str
    producer_generation: int
    created_at: datetime


class StageCallSnapshot(_FrozenModel):
    call_id: str
    run_id: str
    stage_key: str
    operation_key: str
    job_id: str
    generation: int
    attempt: int
    dependency_sha256: str
    input_sha256: str
    model_policy_sha256: str
    prompt_policy_sha256: str
    state: StageCallState
    request_sha256: str | None
    request_bytes: bytes | None
    raw: bytes | None
    raw_sha256: str | None
    raw_ref: str
    diagnostic: str | None
    usage: dict[str, int]
    reserved_at: datetime
    dispatched_at: datetime | None
    recorded_at: datetime | None


class StageCallReservation(_FrozenModel):
    action: StageCallAction
    call: StageCallSnapshot


class StageCallMetrics(_FrozenModel):
    model_call_count: int = Field(ge=0)
    unsettled_call_count: int = Field(default=0, ge=0)
    usage: dict[str, int]
