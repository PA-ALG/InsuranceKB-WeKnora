"""Materialize verified failed C classifications as isolated audit decisions."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from insurance_harness.model_policy import g3_bounded_gateway as gateway
from insurance_harness.run_admission.g3_models import (
    G3BoundedAdmissionPlanV1,
    G3CallTerminalReceiptV1,
    canonical_json,
)

from .batch_canonical_830_g3 import batch_sha256_830_g3
from .batch_entity_resolution_830_g3 import (
    BatchCorpusV1,
    BatchResolutionPolicyV1,
    CorpusEntryV1,
    Hash,
    MaterialDecisionV1,
    _entry_source_reasons,
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class VerifiedFailedClassificationQuarantineV1(_FrozenModel):
    contract: Literal["g3-verified-failed-classification-quarantine.830.v1"]
    historical_attempt: Literal[True]
    admission_artifact_digest: Hash
    chain_manifest_hash: Hash
    call_id: str
    call_ordinal: int
    call_terminal_receipt_sha256: Hash
    call_request_sha256: Hash
    raw_response_sha256: Hash
    semantic_sha256: Hash
    source_corpus_sha256: Hash
    corpus_entry_sha256: Hash
    source_receipt_binding_sha256: Hash
    resolution_policy_sha256: Hash
    decision: MaterialDecisionV1
    receipt_sha256: Hash

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if (
            self.decision.material_id == ""
            or self.decision.disposition != "QUARANTINE"
            or self.decision.reason_codes != ("MODEL_RECEIPT_INVALID",)
            or self.receipt_sha256
            != batch_sha256_830_g3(self.contract, self.model_dump(exclude={"receipt_sha256"}))
        ):
            raise ValueError("failed classification quarantine receipt mismatch")
        return self


class VerifiedFailedClassificationQuarantineBatchV1(_FrozenModel):
    contract: Literal["g3-verified-failed-classification-quarantine-batch.830.v1"]
    chain_manifest_hash: Hash
    source_corpus_sha256: Hash
    resolution_policy_sha256: Hash
    decisions: tuple[VerifiedFailedClassificationQuarantineV1, ...] = Field(min_length=1)
    batch_sha256: Hash

    @model_validator(mode="after")
    def validate_batch(self) -> Self:
        keys = tuple((row.call_ordinal, row.call_id) for row in self.decisions)
        if (
            keys != tuple(sorted(set(keys)))
            or any(row.chain_manifest_hash != self.chain_manifest_hash for row in self.decisions)
            or any(row.source_corpus_sha256 != self.source_corpus_sha256 for row in self.decisions)
            or any(
                row.resolution_policy_sha256 != self.resolution_policy_sha256
                for row in self.decisions
            )
            or self.batch_sha256
            != batch_sha256_830_g3(self.contract, self.model_dump(exclude={"batch_sha256"}))
        ):
            raise ValueError("failed classification quarantine batch mismatch")
        return self


def _source_receipt_binding(entry: CorpusEntryV1) -> str:
    receipt = entry.receipt
    value = getattr(receipt, "source_receipt_sha256", None)
    if value is None:
        value = getattr(receipt, "binding_digest", None)
    if not isinstance(value, str):
        raise ValueError("classification source receipt is not hash bound")
    return value


def _decision(material_id: str, policy: BatchResolutionPolicyV1) -> MaterialDecisionV1:
    payload = {
        "material_id": material_id,
        "disposition": "QUARANTINE",
        "reason_codes": ("MODEL_RECEIPT_INVALID",),
        "children": (),
        "queue_id": policy.queue_id,
        "queue_owner": policy.queue_owner,
        "evidence_ids": (),
    }
    return MaterialDecisionV1.model_validate(
        {
            **payload,
            "decision_sha256": batch_sha256_830_g3("material-decision.830.g3.v1", payload),
        }
    )


def _require_admission_input(
    plan: G3BoundedAdmissionPlanV1, contract: str, value: BaseModel
) -> None:
    raw = canonical_json(value.model_dump(mode="json", round_trip=True))
    matching = tuple(
        ref for ref in plan.eligibility_lock.input_artifacts if ref.contract == contract
    )
    if (
        len(matching) != 1
        or matching[0].sha256 != hashlib.sha256(raw).hexdigest()
        or matching[0].bytes != len(raw)
    ):
        raise ValueError("failed classification admission input mismatch")


def build_verified_failed_classification_quarantines(
    *,
    plan: G3BoundedAdmissionPlanV1,
    admission_digest: str,
    corpus: BatchCorpusV1,
    policy: BatchResolutionPolicyV1,
    failed_terminals: tuple[G3CallTerminalReceiptV1, ...],
    ledger_root: Path | None = None,
) -> VerifiedFailedClassificationQuarantineBatchV1:
    """Verify immutable failed leaves and emit only their named-queue decisions."""

    from insurance_harness.run_admission.profiles.g3_bounded_execution import (
        validate_g3_bounded_plan,
    )

    try:
        plan = validate_g3_bounded_plan(plan)
        corpus = BatchCorpusV1.model_validate(corpus)
        policy = BatchResolutionPolicyV1.model_validate(policy)
    except (TypeError, ValueError) as exc:
        raise ValueError("failed classification input is invalid") from exc
    if plan.stage != "C_CLASSIFY":
        raise ValueError("failed classification quarantine requires C_CLASSIFY")
    if corpus.space_id != plan.space_id:
        raise ValueError("failed classification admission input mismatch")
    _require_admission_input(plan, corpus.contract, corpus)
    _require_admission_input(plan, policy.contract, policy)
    call_by_id = {call.call_id: call for call in plan.request_manifest.calls}
    entry_by_id = {entry.material_id: entry for entry in corpus.entries}
    decisions: list[VerifiedFailedClassificationQuarantineV1] = []
    for supplied_terminal in sorted(failed_terminals, key=lambda item: item.ordinal):
        if (
            supplied_terminal.status != "FAILED"
            or supplied_terminal.reason_code != "INVALID_PROVIDER_RESPONSE"
        ):
            raise ValueError("failed classification terminal is required")
        call = call_by_id.get(supplied_terminal.call_id)
        if call is None or call.request_body_sha256 != supplied_terminal.request_body_sha256:
            raise ValueError("failed classification request binding mismatch")
        if len(call.material_ids) != 1:
            raise ValueError("failed classification must bind exactly one material")
        entry = entry_by_id.get(call.material_ids[0])
        if entry is None or _entry_source_reasons(entry, corpus):
            raise ValueError("failed classification source binding mismatch")
        try:
            recorded = gateway.read_g3_recorded_call(
                plan=plan,
                call=call,
                admission_artifact_digest=admission_digest,
                ledger_root=ledger_root,
            )
        except Exception as exc:
            raise ValueError("failed classification recorded call is invalid") from exc
        if recorded.terminal != supplied_terminal:
            raise ValueError("failed classification terminal binding mismatch")
        decision = _decision(entry.material_id, policy)
        payload: dict[str, object] = {
            "contract": "g3-verified-failed-classification-quarantine.830.v1",
            "historical_attempt": True,
            "admission_artifact_digest": admission_digest,
            "chain_manifest_hash": plan.chain_manifest_hash,
            "call_id": call.call_id,
            "call_ordinal": call.ordinal,
            "call_terminal_receipt_sha256": supplied_terminal.receipt_sha256,
            "call_request_sha256": call.request_body_sha256,
            "raw_response_sha256": hashlib.sha256(recorded.response_bytes).hexdigest(),
            "semantic_sha256": hashlib.sha256(recorded.semantic_bytes).hexdigest(),
            "source_corpus_sha256": corpus.corpus_sha256,
            "corpus_entry_sha256": entry.entry_sha256,
            "source_receipt_binding_sha256": _source_receipt_binding(entry),
            "resolution_policy_sha256": policy.policy_sha256,
            "decision": decision,
        }
        decisions.append(
            VerifiedFailedClassificationQuarantineV1.model_validate(
                {
                    **payload,
                    "receipt_sha256": batch_sha256_830_g3(
                        "g3-verified-failed-classification-quarantine.830.v1", payload
                    ),
                }
            )
        )
    batch_payload: dict[str, object] = {
        "contract": "g3-verified-failed-classification-quarantine-batch.830.v1",
        "chain_manifest_hash": plan.chain_manifest_hash,
        "source_corpus_sha256": corpus.corpus_sha256,
        "resolution_policy_sha256": policy.policy_sha256,
        "decisions": tuple(decisions),
    }
    return VerifiedFailedClassificationQuarantineBatchV1.model_validate(
        {
            **batch_payload,
            "batch_sha256": batch_sha256_830_g3(
                "g3-verified-failed-classification-quarantine-batch.830.v1", batch_payload
            ),
        }
    )


__all__ = [
    "VerifiedFailedClassificationQuarantineBatchV1",
    "VerifiedFailedClassificationQuarantineV1",
    "build_verified_failed_classification_quarantines",
]
