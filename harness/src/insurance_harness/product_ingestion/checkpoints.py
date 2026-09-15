"""Versioned references to completed stages; no copied execution or source payloads."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from insurance_harness.product_ingestion.models import (
    MaterialSnapshot,
    ProductScope,
    StageSnapshot,
)

PLAN_KIND = "checkpoint_plan"
RECEIPT_KIND = "checkpoint_receipt"
LEGACY_STAGE_ORDER = (
    "uploads",
    "source",
    "routing",
    "identity",
    "field_plan",
    "extract",
    "synthesis",
    "compilation",
    "review",
    "publish",
    "verify",
)
# These are declared stage output dependencies, not failure-message classifications.
LEGACY_REQUIRED_OUTPUTS = {
    "uploads": (),
    "source": ("source_snapshot",),
    "routing": ("routing",),
    "identity": ("identity", "base_snapshot"),
    "field_plan": ("compile_request", "field_plan"),
    "extract": (),
    "synthesis": ("compile_delta",),
    "compilation": ("candidate", "preparation"),
    "review": ("system_decision", "ready"),
    "publish": ("publish_authorization", "publication"),
    "verify": ("verification",),
}

STAGE_ORDER = (*LEGACY_STAGE_ORDER[:8], "preparation", *LEGACY_STAGE_ORDER[8:])
REQUIRED_OUTPUTS = {
    **LEGACY_REQUIRED_OUTPUTS,
    "compilation": ("candidate",),
    "preparation": ("preparation",),
}


# Only declared versioned outputs gate reuse; historical payloads stay immutable.
CURRENT_ARTIFACT_CONTRACTS = {"candidate": ("product-candidate.v2", "2")}


def stage_order(workflow_version):
    if workflow_version == 1:
        return LEGACY_STAGE_ORDER
    if workflow_version == 2:
        return STAGE_ORDER
    raise ValueError("unsupported product workflow version")


def required_outputs(workflow_version):
    stage_order(workflow_version)
    return LEGACY_REQUIRED_OUTPUTS if workflow_version == 1 else REQUIRED_OUTPUTS


class Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    def encoded(self):
        return self.model_dump_json().encode()

    def digest(self):
        return hashlib.sha256(self.encoded()).hexdigest()


class ArtifactReference(Frozen):
    artifact_id: str
    run_id: str
    stage_key: str
    artifact_kind: str
    artifact_key: str
    contract_name: str
    contract_version: str
    dependency_sha256: str
    payload_sha256: str
    producer_job_id: str
    producer_generation: int
    origin: str
    origin_call_id: str | None


class CallReference(Frozen):
    kind: Literal["field", "stage"]
    record_id: str
    run_id: str
    call_id: str
    state: str
    request_sha256: str | None
    raw_sha256: str | None


class FieldReference(Frozen):
    attempt_id: str
    run_id: str
    entity_id: str
    field_key: str
    task_sha256: str
    outcome: str
    call_id: str


class CheckpointPlan(Frozen):
    contract: Literal[
        "product-stage-checkpoint-plan.830.v1", "product-stage-checkpoint-plan.830.v2"
    ] = "product-stage-checkpoint-plan.830.v2"
    scope: ProductScope
    origin_run_id: str
    origin_version: int = Field(gt=0)
    upload_run_id: str
    resume_stage: str
    materials: tuple[MaterialSnapshot, ...]
    reused_stages: tuple[StageSnapshot, ...]
    artifacts: tuple[ArtifactReference, ...]
    calls: tuple[CallReference, ...] = ()
    fields: tuple[FieldReference, ...] = ()

    @property
    def workflow_version(self):
        return 1 if self.contract.endswith(".v1") else 2

    @model_validator(mode="after")
    def valid(self):
        order = stage_order(self.workflow_version)
        keys = tuple(s.stage_key for s in self.reused_stages)
        if self.resume_stage not in order or keys != order[: order.index(self.resume_stage)]:
            raise ValueError("checkpoint stages must form an exact completed dependency prefix")
        if any(s.state not in {"succeeded", "partial_success"} for s in self.reused_stages):
            raise ValueError("checkpoint cannot claim incomplete execution")
        for values in (
            [r.artifact_id for r in self.artifacts],
            [(r.artifact_kind, r.artifact_key) for r in self.artifacts],
            [(r.kind, r.record_id) for r in self.calls],
            [r.attempt_id for r in self.fields],
            [(r.entity_id, r.field_key) for r in self.fields],
        ):
            if len(values) != len(set(values)):
                raise ValueError("duplicate checkpoint member")
        if len(self.encoded()) > 131072:
            raise ValueError("checkpoint reference capacity exceeded")
        return self


class CheckpointReceipt(Frozen):
    contract: Literal[
        "product-stage-checkpoint-receipt.830.v1", "product-stage-checkpoint-receipt.830.v2"
    ] = "product-stage-checkpoint-receipt.830.v2"
    scope: ProductScope
    run_id: str
    plan_sha256: str
    reused_stages: tuple[StageSnapshot, ...]
    field_sha256: dict[str, str]
    reused_call_ids: tuple[str, ...]
    reused_usage: dict[str, int]
    unsettled_call_count: int = Field(default=0, ge=0)


def field_digest(snapshot):
    return hashlib.sha256(snapshot.model_dump_json().encode()).hexdigest()
