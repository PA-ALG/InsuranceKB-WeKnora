"""Reuse captured classification; never rewrite model receipts or serving state.

A changed downstream extraction plan is not a classification dependency. This
adapter replays the existing pure resolver against the current entity snapshot.
Revision changes require a separate classification attempt, not a relabelled old
request. The signed D admission separately binds the explicit reuse receipt.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from .batch_canonical_830_g3 import batch_sha256_830_g3
from .batch_concept_compile_830_g3 import BatchConceptCompileRequest830G3V1, Hash
from .batch_entity_resolution_830_g3 import (
    BatchCorpusV1,
    BatchEntityResolutionV1,
    BatchResolutionPolicyV1,
    ExistingEntitySnapshotV1,
    ProposalBatchV1,
    resolve_batch,
)
from .schema_pack_catalog_830_g3 import SchemaPackCatalogV1


def replay_classification(
    *,
    source_corpus: BatchCorpusV1,
    source_proposals: ProposalBatchV1,
    current_corpus: BatchCorpusV1,
    catalog: SchemaPackCatalogV1,
    existing_entities: ExistingEntitySnapshotV1,
    policy: BatchResolutionPolicyV1,
) -> BatchEntityResolutionV1:
    """Re-match unchanged captured materials without any provider or parsing IO."""
    old = BatchCorpusV1.model_validate(source_corpus)
    current = BatchCorpusV1.model_validate(current_corpus)
    proposals = ProposalBatchV1.model_validate(source_proposals)
    if old != current or proposals.corpus_sha256 != old.corpus_sha256:
        raise ValueError("classification reuse requires unchanged source revisions")
    return resolve_batch(
        catalog=catalog,
        corpus=current,
        proposals=proposals,
        existing_entities=existing_entities,
        policy=policy,
    )


class G3ClassificationReuseV1(BaseModel):
    """A reference to old work, authorized as an input of the new D plan.

    Creating this record alone grants no capability. Runtime must reopen the
    original successful call ledger before accepting it as a prior-stage input.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    contract: Literal["g3-classification-reuse.830.v1"]
    source_chain_manifest_hash: Hash
    source_terminal_receipt_sha256: Hash
    source_admission_digest: Hash
    source_proposals_sha256: Hash
    source_resolution_sha256: Hash
    source_corpus_sha256: Hash
    current_catalog_sha256: Hash
    current_snapshot_sha256: Hash
    current_policy_sha256: Hash
    current_resolution_sha256: Hash
    current_request_sha256: Hash
    receipt_sha256: Hash

    @model_validator(mode="after")
    def check_hash(self) -> Self:
        if self.receipt_sha256 != batch_sha256_830_g3(
            self.contract, self.model_dump(exclude={"receipt_sha256"})
        ):
            raise ValueError("classification reuse receipt hash mismatch")
        return self


def _request_binding(request: BatchConceptCompileRequest830G3V1) -> dict[str, str]:
    return {
        "source_proposals_sha256": request.resolution_inputs.proposals.proposals_sha256,
        "source_corpus_sha256": request.resolution_inputs.corpus.corpus_sha256,
        "current_catalog_sha256": request.catalog.catalog_sha256,
        "current_snapshot_sha256": request.resolution_inputs.existing_entities.snapshot_sha256,
        "current_policy_sha256": request.resolution_inputs.policy.policy_sha256,
        "current_resolution_sha256": request.resolution.batch_sha256,
        "current_request_sha256": request.request_sha256,
    }


def build_classification_reuse(
    *,
    request: BatchConceptCompileRequest830G3V1,
    source_chain_manifest_hash: str,
    source_terminal_receipt_sha256: str,
    source_admission_digest: str,
    source_resolution_sha256: str,
) -> G3ClassificationReuseV1:
    payload = {
        "contract": "g3-classification-reuse.830.v1",
        "source_chain_manifest_hash": source_chain_manifest_hash,
        "source_terminal_receipt_sha256": source_terminal_receipt_sha256,
        "source_admission_digest": source_admission_digest,
        "source_resolution_sha256": source_resolution_sha256,
        **_request_binding(request),
    }
    return G3ClassificationReuseV1.model_validate(
        {
            **payload,
            "receipt_sha256": batch_sha256_830_g3(payload["contract"], payload),
        }
    )


def validate_reuse_binding(
    receipt: G3ClassificationReuseV1,
    *,
    request: BatchConceptCompileRequest830G3V1,
) -> None:
    receipt = G3ClassificationReuseV1.model_validate(receipt)
    if any(getattr(receipt, key) != value for key, value in _request_binding(request).items()):
        raise ValueError("classification reuse current request mismatch")
    inputs = request.resolution_inputs
    resolution = replay_classification(
        source_corpus=inputs.corpus,
        source_proposals=inputs.proposals,
        current_corpus=inputs.corpus,
        catalog=request.catalog,
        existing_entities=inputs.existing_entities,
        policy=inputs.policy,
    )
    if resolution != request.resolution:
        raise ValueError("classification reuse current matching mismatch")


def _verify_historical_authority(parent, approval) -> None:
    from insurance_harness.run_admission.g3_trust_policy import (
        load_g3_root_trust_policy,
        verify_delegated_stage_signature,
        verify_parent_authorization,
    )

    verify_parent_authorization(load_g3_root_trust_policy(), parent)
    verify_delegated_stage_signature(parent, approval)


def validate_classification_reuse(
    receipt: G3ClassificationReuseV1,
    *,
    request: BatchConceptCompileRequest830G3V1,
    ledger_root=None,
    admission_root=None,
) -> None:
    """Reopen the historical ledger, then rematch against the bound current state.

    This is an input verifier, not an authorization entry point. The caller must
    already have verified a current signed D admission containing this exact
    receipt in all input/provenance/rights locks. Historical C is never rewritten.
    """
    import hashlib
    from pathlib import Path

    from insurance_harness.model_policy import PolicyReceipt
    from insurance_harness.model_policy import g3_bounded_gateway as gateway
    from insurance_harness.run_admission import evaluator
    from insurance_harness.run_admission.g3_models import (
        G3BoundedApprovalEnvelopeV1,
        G3ModelProcessingAuthorizationEnvelopeV1,
        G3StageTerminalReceiptV1,
        canonical_json,
    )

    from .batch_canonical_830_g3 import batch_json_bytes_830_g3

    receipt = G3ClassificationReuseV1.model_validate(receipt)
    root = Path(ledger_root if ledger_root is not None else gateway.G3_LEDGER_ROOT)
    admissions = Path(
        admission_root if admission_root is not None else evaluator._ADMISSION_STORE_ROOT
    )

    def read(path, model, file_sha=None):
        raw = gateway._read_secure_ledger_file(path)
        if file_sha is not None and hashlib.sha256(raw).hexdigest() != file_sha:
            raise ValueError("classification reuse origin artifact digest mismatch")
        value = model.model_validate_json(raw)
        if canonical_json(value.model_dump(mode="json", round_trip=True)) != raw:
            raise ValueError("classification reuse noncanonical origin")
        return value

    chain = root / "chains" / receipt.source_chain_manifest_hash
    terminal = read(chain / "stage-terminals/C_CLASSIFY.json", G3StageTerminalReceiptV1)
    if (
        terminal.status != "SUCCESS"
        or terminal.stage != "C_CLASSIFY"
        or terminal.receipt_sha256 != receipt.source_terminal_receipt_sha256
        or terminal.stage_output_sha256 != receipt.source_resolution_sha256
        or terminal.admission_artifact_digest != receipt.source_admission_digest
    ):
        raise ValueError("classification reuse requires original successful C")
    approval = read(
        admissions / "sha256" / receipt.source_admission_digest / "approval-envelope.json",
        G3BoundedApprovalEnvelopeV1,
        receipt.source_admission_digest,
    )
    plan = approval.payload
    parent = read(
        admissions
        / "sha256"
        / terminal.parent_authorization_digest
        / "model-processing-authorization.json",
        G3ModelProcessingAuthorizationEnvelopeV1,
        terminal.parent_authorization_digest,
    )
    _verify_historical_authority(parent, approval)
    if (
        plan.stage != "C_CLASSIFY"
        or plan.chain_manifest_hash != receipt.source_chain_manifest_hash
        or plan.chain_id != terminal.chain_id
        or plan.parent_authorization_digest != terminal.parent_authorization_digest
    ):
        raise ValueError("classification reuse original plan mismatch")
    proposals = read(chain / "stage-results/C_CLASSIFY/proposal-batch.json", ProposalBatchV1)
    original_resolution = read(
        chain / "stage-results/C_CLASSIFY/resolution.json", BatchEntityResolutionV1
    )
    if (
        proposals.proposals_sha256 != receipt.source_proposals_sha256
        or proposals != request.resolution_inputs.proposals
        or original_resolution.batch_sha256 != receipt.source_resolution_sha256
        or original_resolution.proposals_sha256 != proposals.proposals_sha256
        or original_resolution.corpus_sha256 != receipt.source_corpus_sha256
    ):
        raise ValueError("classification reuse original result mismatch")
    # These classification inputs are unchanged; no 55MB native parse is needed.
    for contract, value in (
        ("batch-corpus.830.g3.v1", request.resolution_inputs.corpus),
        ("schema-pack-catalog.830.g3.v1", request.catalog),
    ):
        refs = [ref for ref in plan.eligibility_lock.input_artifacts if ref.contract == contract]
        if (
            len(refs) != 1
            or refs[0].sha256 != hashlib.sha256(batch_json_bytes_830_g3(value)).hexdigest()
        ):
            raise ValueError("classification reuse source or catalog dependency changed")
    model_receipts = {row.request_sha256: row for row in proposals.model_receipts}
    seen = []
    for call in plan.request_manifest.calls:
        completed = gateway._read_successful_g3_stage_call(
            plan=plan,
            call=call,
            admission_artifact_digest=receipt.source_admission_digest,
            ledger_root=root,
        )
        call_terminal, semantic, policy_raw, _ = completed
        rows = tuple(
            row
            for row in proposals.proposals
            if row.model_request_sha256 == call.request_body_sha256
        )
        binding = model_receipts.get(call.request_body_sha256)
        if (
            tuple(row.material_id for row in rows) != call.material_ids
            or call_terminal.projection_sha256
            != batch_sha256_830_g3("g3-c-call-projection.830.v1", {"proposals": rows})
            or binding is None
            or binding.execution_receipt_sha256 != call_terminal.receipt_sha256
            or binding.raw_output_sha256 != hashlib.sha256(semantic).hexdigest()
            or binding.policy_receipt != PolicyReceipt.model_validate_json(policy_raw)
        ):
            raise ValueError("classification reuse call projection or model receipt mismatch")
        seen.append(call_terminal.receipt_sha256)
    if tuple(seen) != terminal.call_terminal_sha256s or set(model_receipts) != {
        c.request_body_sha256 for c in plan.request_manifest.calls
    }:
        raise ValueError("classification reuse incomplete original calls")
    validate_reuse_binding(receipt, request=request)
