"""Explicit, immutable source-sealing recovery; never a parse or field retry."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from insurance_harness.product_ingestion.models import OriginalKnowledgeRef, ProductScope

RECOVERY_PREFIX = "processing-recovery.v1:"
RECOVERY_V2_PREFIX = "processing-recovery.v2:"
RECOVERY_V3_PREFIX = "processing-recovery.v3:"
RECOVERY_KIND = "processing_recovery_plan"


class ProcessingRecoveryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    contract: Literal["product-processing-recovery-plan.830.v1"] = (
        "product-processing-recovery-plan.830.v1"
    )
    mode: Literal["RECAPTURE_COMPLETED_SOURCES"] = "RECAPTURE_COMPLETED_SOURCES"
    scope: ProductScope
    origin_run_id: str = Field(min_length=1)
    origin_version: int = Field(gt=0)
    upload_run_id: str = Field(min_length=1)
    materials: tuple[OriginalKnowledgeRef, ...]

    def encoded(self) -> bytes:
        return self.model_dump_json().encode()

    def digest(self) -> str:
        return hashlib.sha256(self.encoded()).hexdigest()


class SourceSnapshotReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    knowledge_id: str = Field(min_length=1)
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class SealedSourceRecoveryPlan(ProcessingRecoveryPlan):
    contract: Literal["product-processing-recovery-plan.830.v2"] = (
        "product-processing-recovery-plan.830.v2"
    )
    mode: Literal["REUSE_SEALED_SOURCES"] = "REUSE_SEALED_SOURCES"
    source_snapshots: tuple[SourceSnapshotReference, ...]


class RecordedBaseIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    release_id: str = Field(min_length=1)
    activation_epoch: int = Field(ge=0)
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class RecordedIdentityReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    call_id: str
    record_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    raw_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    base_identity: RecordedBaseIdentity


class RecordedIdentityRecoveryPlan(SealedSourceRecoveryPlan):
    contract: Literal["product-processing-recovery-plan.830.v3"] = (
        "product-processing-recovery-plan.830.v3"
    )
    mode: Literal["REPLAY_RECORDED_IDENTITY"] = "REPLAY_RECORDED_IDENTITY"
    identity_call: RecordedIdentityReference


def recorded_identity_reference(call) -> RecordedIdentityReference:
    """Bind actual recorded bytes and original execution identity, never a new dispatch."""
    if (
        str(call.state) != "recorded"
        or call.stage_key != "identity"
        or call.operation_key != "current-product-identity"
        or call.diagnostic is not None
        or not call.raw
        or not call.request_bytes
        or call.dispatched_at is None
        or call.recorded_at is None
        or hashlib.sha256(call.raw).hexdigest() != call.raw_sha256
        or hashlib.sha256(call.request_bytes).hexdigest() != call.request_sha256
    ):
        raise ValueError("recorded identity call is incomplete")
    try:
        request = json.loads(call.request_bytes)
        messages = request["messages"]
        if len(messages) != 2 or [m["role"] for m in messages] != ["system", "user"]:
            raise ValueError("recorded identity request invalid")
        content = messages[1]["content"].encode()
        if (
            hashlib.sha256(content).hexdigest() != call.input_sha256
            or hashlib.sha256(messages[0]["content"].encode()).hexdigest()
            != call.prompt_policy_sha256
        ):
            raise ValueError("recorded identity input invalid")
        base = RecordedBaseIdentity.model_validate(json.loads(content)["base_identity"])
    except (KeyError, TypeError, AttributeError, UnicodeError) as error:
        raise ValueError("recorded identity request invalid") from error
    values = {
        key: getattr(call, key)
        for key in (
            "call_id",
            "run_id",
            "stage_key",
            "operation_key",
            "job_id",
            "generation",
            "attempt",
            "dependency_sha256",
            "input_sha256",
            "model_policy_sha256",
            "prompt_policy_sha256",
            "request_sha256",
            "raw_sha256",
            "raw_ref",
            "usage",
        )
    }
    for key in ("reserved_at", "dispatched_at", "recorded_at"):
        stamp = getattr(call, key)
        values[key] = (
            stamp.replace(tzinfo=UTC).isoformat()
            if stamp.tzinfo is None
            else stamp.astimezone(UTC).isoformat()
        )
    digest = hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return RecordedIdentityReference(
        call_id=call.call_id,
        record_sha256=digest,
        request_sha256=call.request_sha256,
        raw_sha256=call.raw_sha256,
        input_sha256=call.input_sha256,
        model_policy_sha256=call.model_policy_sha256,
        prompt_policy_sha256=call.prompt_policy_sha256,
        base_identity=base,
    )


def material_references(run):
    return tuple(
        OriginalKnowledgeRef(
            knowledge_id=row.knowledge_id,
            original_filename=row.original_filename,
            upload_ordinal=row.upload_ordinal,
        )
        for row in run.materials
    )
