"""Versioned references to completed stages; no copied execution or source payloads."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from insurance_harness.product_ingestion.models import (
    MaterialSnapshot,
    ProductScope,
    StageSnapshot,
)
from insurance_harness.product_ingestion.recovery import RecordedIdentityReference

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
    "synthesis": ("compile_delta", "field_validation"),
    "compilation": ("candidate", "preparation"),
    "review": ("system_decision", "ready"),
    "publish": ("publish_authorization", "publication"),
    "verify": ("verification",),
}

STAGE_ORDER = (*LEGACY_STAGE_ORDER[:8], "preparation", *LEGACY_STAGE_ORDER[8:])
CURRENT_STAGE_ORDER = (
    *STAGE_ORDER[:7],
    "discovery",
    *STAGE_ORDER[7:],
)
REQUIRED_OUTPUTS = {
    **LEGACY_REQUIRED_OUTPUTS,
    "compilation": ("candidate",),
    "preparation": ("preparation",),
}
CURRENT_REQUIRED_OUTPUTS = {
    **REQUIRED_OUTPUTS,
    "discovery": ("discovery_candidates", "discovery_delta", "discovery_summary"),
}

# These rows are append-only accounting from individual source attempts. They
# remain on the originating run, but are not completed stage outputs and must
# never become recovery inputs merely because their stage later succeeded.
CHECKPOINT_AUDIT_ONLY_KINDS = frozenset({"source_processing_attempt"})


def is_checkpoint_reusable_artifact(artifact_kind: str) -> bool:
    return artifact_kind not in CHECKPOINT_AUDIT_ONLY_KINDS


# Only declared versioned outputs gate reuse; historical payloads stay immutable.
CURRENT_ARTIFACT_CONTRACTS = {
    "candidate": ("product-candidate.v2", "2"),
    "compile_delta": ("product-compile_delta.v2", "2"),
    "field_validation": ("product-field_validation.v1", "1"),
    "discovery_candidates": ("product-discovery_candidates.v1", "1"),
    "discovery_delta": ("product-discovery_delta.v1", "1"),
    "discovery_summary": ("product-discovery_summary.v1", "1"),
    "discovery_context": ("product-discovery_context.v1", "1"),
    "discovery_window_audit": ("product-discovery_window_audit.v1", "1"),
    "discovery_window_replay_receipt": ("product-discovery_window_replay_receipt.v1", "1"),
    "discovery_response": ("product-discovery_response.v1", "1"),
    "discovery_proposal": ("product-discovery_proposal.v1", "1"),
    "discovery_review_context": ("product-discovery_review_context.v1", "1"),
    "discovery_review_response": ("product-discovery_review_response.v1", "1"),
    "discovery_review_proof": ("product-discovery_review_proof.v1", "1"),
    "reviewed_discovery_delta": ("product-reviewed_discovery_delta.v1", "1"),
    "discovery_final_summary": ("product-discovery_final_summary.v1", "1"),
    "composite_review": ("product-composite_review.v1", "1"),
    "rebased_base_snapshot": ("product-rebased_base_snapshot.v1", "1"),
    "rebased_compile_request": ("product-rebased_compile_request.v1", "1"),
    "rebased_identity": ("product-rebased_identity.v1", "1"),
    "rebased_compile_delta": ("product-rebased_compile_delta.v1", "1"),
    "rebased_discovery_disposition": ("product-rebased_discovery_disposition.v1", "1"),
}


def stage_order(workflow_version):
    if workflow_version == 1:
        return LEGACY_STAGE_ORDER
    if workflow_version == 2:
        return STAGE_ORDER
    if workflow_version == 3:
        return CURRENT_STAGE_ORDER
    raise ValueError("unsupported product workflow version")


def required_outputs(workflow_version):
    stage_order(workflow_version)
    if workflow_version == 1:
        return LEGACY_REQUIRED_OUTPUTS
    return REQUIRED_OUTPUTS if workflow_version == 2 else CURRENT_REQUIRED_OUTPUTS


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


class IdentityRetryReference(Frozen):
    record_id: str
    stage: StageSnapshot
    generation: int = Field(gt=0)
    proof: RecordedIdentityReference


class ConfirmedFailureReference(Frozen):
    """A completed HTTP rejection may be sent again only in a linked run."""

    record_id: str
    run_id: str
    call_id: str
    job_id: str
    generation: int = Field(gt=0)
    request_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    raw_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    diagnostic: Literal["provider_http_status"]


class VersionedCheckpoint(Frozen):
    execution_workflow_version: Literal[2] | None = None

    @model_serializer(mode="wrap")
    def preserve_old_wire(self, handler):
        value = handler(self)
        if not self.contract.endswith(".v7"):
            value.pop("execution_workflow_version", None)
        if not self.contract.endswith((".v3", ".v4", ".v5", ".v6")):
            value.pop("retry_calls", None)
        if not self.contract.endswith((".v4", ".v5", ".v6")):
            value.pop("failed_calls", None)
        if not self.supports_rebase:
            value.pop("audited_calls", None)
            value.pop("failed_discovery_artifact", None)
            value.pop("failed_discovery_stage", None)
            value.pop("prior_rebase_artifacts", None)
            value.pop("rebased_base_sha256", None)
            value.pop("rebased_discovery_disposition_sha256", None)
        return value

    @property
    def supports_rebase(self) -> bool:
        return self.contract.endswith((".v6", ".v7"))

    @property
    def field_only_rebase(self) -> bool:
        return self.contract.endswith(".v7")

    @model_validator(mode="after")
    def valid_retry_contract(self):
        if self.contract.endswith(".v7"):
            if self.execution_workflow_version != 2:
                raise ValueError("checkpoint v7 requires execution_workflow_version 2")
        elif self.execution_workflow_version is not None:
            raise ValueError("explicit execution workflow requires checkpoint v7")
        if self.retry_calls and not self.contract.endswith((".v3", ".v5", ".v6")):
            raise ValueError("retry references require checkpoint v3")
        if len(self.retry_calls) > 1:
            raise ValueError("only one recorded identity retry is supported")
        if self.failed_calls and not self.contract.endswith((".v4", ".v5", ".v6")):
            raise ValueError("failure references require checkpoint v4")
        if len(self.failed_calls) > 1 or (self.failed_calls and self.retry_calls):
            raise ValueError("only one identity failure mode is supported")
        return self


class CheckpointPlan(VersionedCheckpoint):
    contract: Literal[
        "product-stage-checkpoint-plan.830.v1",
        "product-stage-checkpoint-plan.830.v2",
        "product-stage-checkpoint-plan.830.v3",
        "product-stage-checkpoint-plan.830.v4",
        "product-stage-checkpoint-plan.830.v5",
        "product-stage-checkpoint-plan.830.v6",
        "product-stage-checkpoint-plan.830.v7",
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
    retry_calls: tuple[IdentityRetryReference, ...] = ()
    failed_calls: tuple[ConfirmedFailureReference, ...] = ()
    audited_calls: tuple[CallReference, ...] = ()
    prior_rebase_artifacts: tuple[ArtifactReference, ...] = ()
    failed_discovery_artifact: ArtifactReference | None = None
    failed_discovery_stage: StageSnapshot | None = None

    @property
    def contract_version(self):
        return self.contract.rsplit(".v", 1)[1]

    @property
    def workflow_version(self):
        if self.contract.endswith(".v7"):
            return self.execution_workflow_version
        if self.contract.endswith(".v1"):
            return 1
        return 3 if self.contract.endswith((".v5", ".v6")) else 2

    def artifact_is_effective_after_rebase(self, artifact_kind: str) -> bool:
        if not self.field_only_rebase:
            return True
        return artifact_kind != "compile_delta" and not artifact_kind.startswith("discovery_")

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
        if self.retry_calls:
            ref = self.retry_calls[0]
            if (
                self.resume_stage != "identity"
                or ref.stage.stage_key != "identity"
                or ref.stage.state not in {"blocked", "dead_letter"}
                or ref.stage.finished_at is None
                or any(
                    c.record_id == ref.record_id or c.call_id == ref.proof.call_id
                    for c in self.calls
                )
            ):
                raise ValueError("invalid or intersecting identity retry reference")
        if self.failed_calls:
            if (
                self.resume_stage != "identity"
                or any(c.call_id == self.failed_calls[0].call_id for c in self.calls)
            ):
                raise ValueError("invalid or intersecting confirmed failure reference")
        if self.audited_calls and not self.supports_rebase:
            raise ValueError("audited calls require checkpoint v6")
        if self.prior_rebase_artifacts:
            kinds = {r.artifact_kind for r in self.prior_rebase_artifacts}
            required = {
                "rebased_base_snapshot", "rebased_compile_request",
                "rebased_identity", "rebased_compile_delta",
            }
            if (
                not self.supports_rebase
                or not required <= kinds
                or kinds - required != (
                    {"rebased_discovery_disposition"} if len(kinds) == 5 else set()
                )
                or len(self.prior_rebase_artifacts) != len(kinds)
                or len({r.artifact_id for r in self.prior_rebase_artifacts}) != len(kinds)
                or any(r.stage_key != "checkpoint" for r in self.prior_rebase_artifacts)
            ):
                raise ValueError("invalid prior checkpoint rebase")
        if bool(self.failed_discovery_artifact) != bool(self.failed_discovery_stage):
            raise ValueError("incomplete discovery failure proof")
        if self.failed_discovery_artifact:
            if (
                not self.contract.endswith(".v6")
                or (self.resume_stage, self.failed_discovery_artifact.artifact_kind,
                    self.failed_discovery_stage.stage_key) not in {
                    ("discovery", "discovery_summary", "discovery"),
                    ("compilation", "discovery_final_summary", "compilation"),
                }
                or self.failed_discovery_stage.run_id != self.failed_discovery_artifact.run_id
            ):
                raise ValueError("invalid discovery failure proof")
        if len(self.encoded()) > 131072:
            raise ValueError("checkpoint reference capacity exceeded")
        return self


class CheckpointReceipt(VersionedCheckpoint):
    contract: Literal[
        "product-stage-checkpoint-receipt.830.v1",
        "product-stage-checkpoint-receipt.830.v2",
        "product-stage-checkpoint-receipt.830.v3",
        "product-stage-checkpoint-receipt.830.v4",
        "product-stage-checkpoint-receipt.830.v5",
        "product-stage-checkpoint-receipt.830.v6",
        "product-stage-checkpoint-receipt.830.v7",
    ] = "product-stage-checkpoint-receipt.830.v2"
    scope: ProductScope
    run_id: str
    plan_sha256: str
    reused_stages: tuple[StageSnapshot, ...]
    field_sha256: dict[str, str]
    reused_call_ids: tuple[str, ...]
    reused_usage: dict[str, int]
    unsettled_call_count: int = Field(default=0, ge=0)
    retry_calls: tuple[IdentityRetryReference, ...] = ()
    failed_calls: tuple[ConfirmedFailureReference, ...] = ()
    rebased_base_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    rebased_discovery_disposition_sha256: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$"
    )


def field_digest(snapshot):
    return hashlib.sha256(snapshot.model_dump_json().encode()).hexdigest()
