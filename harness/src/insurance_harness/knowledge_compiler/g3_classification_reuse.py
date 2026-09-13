"""Reuse captured classification; never rewrite model receipts or serving state.

A changed downstream extraction plan is not a classification dependency. This
adapter replays the existing pure resolver against the current entity snapshot.
Revision changes require a separate classification attempt, not a relabelled old
request. The signed D admission separately binds the explicit reuse receipt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from insurance_harness.run_admission.g3_models import G3AuthorizedMaterialV1

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
from .g3_title_routing import TitleRoutingOverlayV1, apply_title_routing_overlay
from .schema_pack_catalog_830_g3 import SchemaPackCatalogV1


def replay_classification(
    *,
    source_corpus: BatchCorpusV1,
    source_proposals: ProposalBatchV1,
    current_corpus: BatchCorpusV1,
    catalog: SchemaPackCatalogV1,
    existing_entities: ExistingEntitySnapshotV1,
    policy: BatchResolutionPolicyV1,
    compiler_version: str = "batch-entity-resolution-compiler.830.g3.v1",
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
        compiler_version=compiler_version,
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


class G3ClassificationReuseV2(G3ClassificationReuseV1):
    """Original C authority plus a separately reproducible deterministic overlay."""

    contract: Literal["g3-classification-reuse.830.v2"]
    title_overlay: TitleRoutingOverlayV1


class G3ClassificationOriginV1(BaseModel):
    """One unchanged, independently authorized historical C result."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    contract: Literal["g3-classification-origin.830.v1"]
    source_chain_manifest_hash: Hash
    source_terminal_receipt_sha256: Hash
    source_admission_digest: Hash
    source_proposals_sha256: Hash
    source_resolution_sha256: Hash
    source_corpus_sha256: Hash
    source_materials: tuple[G3AuthorizedMaterialV1, ...] = Field(min_length=1)
    title_overlay: TitleRoutingOverlayV1 | None = None

    @model_validator(mode="after")
    def validate_materials(self) -> Self:
        keys = tuple(row.material_id for row in self.source_materials)
        sources = tuple(row.source_revision_receipt_sha256 for row in self.source_materials)
        if (
            keys != tuple(sorted(keys))
            or len(keys) != len(set(keys))
            or len(sources) != len(set(sources))
        ):
            raise ValueError("classification origin materials must be canonical and distinct")
        if self.title_overlay is not None and (
            self.title_overlay.source_proposals_sha256 != self.source_proposals_sha256
            or self.title_overlay.corpus_sha256 != self.source_corpus_sha256
        ):
            raise ValueError("classification origin overlay binding mismatch")
        return self


class G3ClassificationReuseV3(BaseModel):
    """A current D input composed only from verified historical C origins."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    contract: Literal["g3-classification-reuse.830.v3"]
    origins: tuple[G3ClassificationOriginV1, ...] = Field(min_length=2)
    current_corpus_sha256: Hash
    current_proposals_sha256: Hash
    current_catalog_sha256: Hash
    current_snapshot_sha256: Hash
    current_policy_sha256: Hash
    current_resolution_sha256: Hash
    current_request_sha256: Hash
    receipt_sha256: Hash

    @property
    def source_terminal_receipt_sha256(self) -> str:
        """Compatibility anchor for the signed D plan; always a real C terminal."""

        return self.origins[0].source_terminal_receipt_sha256

    @model_validator(mode="after")
    def validate_composite(self) -> Self:
        origin_keys = tuple(
            (row.source_chain_manifest_hash, row.source_terminal_receipt_sha256)
            for row in self.origins
        )
        if origin_keys != tuple(sorted(origin_keys)) or len(origin_keys) != len(set(origin_keys)):
            raise ValueError("classification reuse origins must be canonical and distinct")
        for values in (
            tuple(row.source_terminal_receipt_sha256 for row in self.origins),
            tuple(row.source_admission_digest for row in self.origins),
            tuple(row.source_corpus_sha256 for row in self.origins),
            tuple(row.source_proposals_sha256 for row in self.origins),
            tuple(
                material.material_id for row in self.origins for material in row.source_materials
            ),
            tuple(
                material.source_revision_receipt_sha256
                for row in self.origins
                for material in row.source_materials
            ),
        ):
            if len(values) != len(set(values)):
                raise ValueError("classification reuse origin scope overlap")
        if self.receipt_sha256 != batch_sha256_830_g3(
            self.contract, self.model_dump(exclude={"receipt_sha256"})
        ):
            raise ValueError("classification reuse receipt hash mismatch")
        return self


ClassificationReuse = G3ClassificationReuseV1 | G3ClassificationReuseV2 | G3ClassificationReuseV3


def parse_classification_reuse(value: object) -> ClassificationReuse:
    adapter = TypeAdapter(ClassificationReuse)
    if isinstance(value, (bytes, str)):
        return adapter.validate_json(value)
    return adapter.validate_python(value)


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


def _composite_request_binding(request: BatchConceptCompileRequest830G3V1) -> dict[str, str]:
    return {
        "current_corpus_sha256": request.resolution_inputs.corpus.corpus_sha256,
        "current_proposals_sha256": request.resolution_inputs.proposals.proposals_sha256,
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
    title_overlay: TitleRoutingOverlayV1 | None = None,
) -> ClassificationReuse:
    payload = {
        "contract": "g3-classification-reuse.830.v1",
        "source_chain_manifest_hash": source_chain_manifest_hash,
        "source_terminal_receipt_sha256": source_terminal_receipt_sha256,
        "source_admission_digest": source_admission_digest,
        "source_resolution_sha256": source_resolution_sha256,
        **_request_binding(request),
    }
    if title_overlay is not None:
        title_overlay = TitleRoutingOverlayV1.model_validate(title_overlay)
        payload.update(
            contract="g3-classification-reuse.830.v2",
            source_proposals_sha256=title_overlay.source_proposals_sha256,
            title_overlay=title_overlay,
        )
    result = parse_classification_reuse(
        {
            **payload,
            "receipt_sha256": batch_sha256_830_g3(payload["contract"], payload),
        }
    )
    return result


def build_composite_classification_reuse(
    *,
    request: BatchConceptCompileRequest830G3V1,
    origins: tuple[G3ClassificationOriginV1, ...],
) -> G3ClassificationReuseV3:
    """Bind a canonical set of real C origins to one recomputed current request."""

    request = BatchConceptCompileRequest830G3V1.model_validate(request)
    payload = {
        "contract": "g3-classification-reuse.830.v3",
        "origins": origins,
        **_composite_request_binding(request),
    }
    return G3ClassificationReuseV3.model_validate(
        {
            **payload,
            "receipt_sha256": batch_sha256_830_g3(payload["contract"], payload),
        }
    )


def validate_composite_parent_materials(
    receipt: G3ClassificationReuseV3,
    *,
    parent: object,
) -> None:
    receipt = G3ClassificationReuseV3.model_validate(receipt)
    expected = tuple(
        sorted(
            (material for origin in receipt.origins for material in origin.source_materials),
            key=lambda row: row.material_id,
        )
    )
    try:
        actual = tuple(parent.c_materials)  # type: ignore[attr-defined]
    except (AttributeError, TypeError):
        raise ValueError("classification reuse parent materials missing") from None
    if actual != expected:
        raise ValueError("classification reuse parent material union mismatch")


def validate_reuse_binding(
    receipt: ClassificationReuse,
    *,
    request: BatchConceptCompileRequest830G3V1,
) -> None:
    receipt = parse_classification_reuse(receipt)
    if isinstance(receipt, G3ClassificationReuseV3):
        if any(
            getattr(receipt, key) != value
            for key, value in _composite_request_binding(request).items()
        ):
            raise ValueError("classification reuse current request mismatch")
        inputs = request.resolution_inputs
        resolution = resolve_batch(
            catalog=request.catalog,
            corpus=inputs.corpus,
            proposals=inputs.proposals,
            existing_entities=inputs.existing_entities,
            policy=inputs.policy,
            compiler_version=request.resolution.compiler_version,
        )
        if resolution != request.resolution:
            raise ValueError("classification reuse current matching mismatch")
        return
    expected = _request_binding(request)
    if isinstance(receipt, G3ClassificationReuseV2):
        overlay = receipt.title_overlay
        if (
            overlay.effective_proposals_sha256 != expected["source_proposals_sha256"]
            or overlay.corpus_sha256 != expected["source_corpus_sha256"]
            or overlay.catalog_sha256 != expected["current_catalog_sha256"]
        ):
            raise ValueError("classification reuse title overlay binding mismatch")
        expected["source_proposals_sha256"] = overlay.source_proposals_sha256
    if any(getattr(receipt, key) != value for key, value in expected.items()):
        raise ValueError("classification reuse current request mismatch")
    inputs = request.resolution_inputs
    resolution = replay_classification(
        source_corpus=inputs.corpus,
        source_proposals=inputs.proposals,
        current_corpus=inputs.corpus,
        catalog=request.catalog,
        existing_entities=inputs.existing_entities,
        policy=inputs.policy,
        compiler_version=request.resolution.compiler_version,
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


@dataclass(frozen=True)
class _VerifiedClassificationOrigin:
    corpus: BatchCorpusV1
    proposals: ProposalBatchV1
    effective_proposals: ProposalBatchV1
    source_materials: tuple[G3AuthorizedMaterialV1, ...]


def _verify_classification_origin(
    origin: G3ClassificationOriginV1,
    *,
    request: BatchConceptCompileRequest830G3V1,
    ledger_root,
    admission_root,
) -> _VerifiedClassificationOrigin:
    """Reopen one real C chain and return only its already signed outputs."""

    import hashlib
    from pathlib import Path

    from insurance_harness.model_policy import PolicyReceipt
    from insurance_harness.model_policy import g3_bounded_gateway as gateway
    from insurance_harness.run_admission.g3_models import (
        G3BoundedApprovalEnvelopeV1,
        G3ModelProcessingAuthorizationEnvelopeV1,
        G3StageTerminalReceiptV1,
        canonical_json,
    )
    from insurance_harness.run_admission.profiles.g3_bounded_execution import (
        validate_g3_parent_scope,
    )

    from .batch_canonical_830_g3 import batch_json_bytes_830_g3

    root = Path(ledger_root)
    admissions = Path(admission_root)

    def read(path, model, file_sha=None):
        raw = gateway._read_secure_ledger_file(path)
        if file_sha is not None and hashlib.sha256(raw).hexdigest() != file_sha:
            raise ValueError("classification reuse origin artifact digest mismatch")
        value = model.model_validate_json(raw)
        if canonical_json(value.model_dump(mode="json", round_trip=True)) != raw:
            raise ValueError("classification reuse noncanonical origin")
        return value

    def read_ref(ref, model):
        path = Path(ref.artifact_ref)
        try:
            relative = path.relative_to(admissions)
        except ValueError:
            raise ValueError("classification reuse origin artifact path mismatch") from None
        if (
            len(relative.parts) != 3
            or relative.parts[0] != "sha256"
            or relative.parts[1] != ref.sha256
        ):
            raise ValueError("classification reuse origin artifact path mismatch")
        raw = gateway._read_secure_ledger_file(path)
        if len(raw) != ref.bytes or hashlib.sha256(raw).hexdigest() != ref.sha256:
            raise ValueError("classification reuse origin artifact digest mismatch")
        value = model.model_validate_json(raw)
        if canonical_json(value.model_dump(mode="json", round_trip=True)) != raw:
            raise ValueError("classification reuse noncanonical origin artifact")
        return value

    chain = root / "chains" / origin.source_chain_manifest_hash
    terminal = read(chain / "stage-terminals/C_CLASSIFY.json", G3StageTerminalReceiptV1)
    if (
        terminal.status != "SUCCESS"
        or terminal.stage != "C_CLASSIFY"
        or terminal.receipt_sha256 != origin.source_terminal_receipt_sha256
        or terminal.stage_output_sha256 != origin.source_resolution_sha256
        or terminal.admission_artifact_digest != origin.source_admission_digest
    ):
        raise ValueError("classification reuse requires original successful C")
    approval = read(
        admissions / "sha256" / origin.source_admission_digest / "approval-envelope.json",
        G3BoundedApprovalEnvelopeV1,
        origin.source_admission_digest,
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
    validate_g3_parent_scope(parent.payload, plan)
    if (
        plan.stage != "C_CLASSIFY"
        or plan.chain_manifest_hash != origin.source_chain_manifest_hash
        or plan.chain_id != terminal.chain_id
        or plan.parent_authorization_digest != terminal.parent_authorization_digest
        or parent.payload.c_materials != origin.source_materials
    ):
        raise ValueError("classification reuse original plan mismatch")

    corpus_refs = tuple(
        ref
        for ref in plan.eligibility_lock.input_artifacts
        if ref.contract == "batch-corpus.830.g3.v1"
    )
    catalog_refs = tuple(
        ref
        for ref in plan.eligibility_lock.input_artifacts
        if ref.contract == "schema-pack-catalog.830.g3.v1"
    )
    if len(corpus_refs) != 1 or len(catalog_refs) != 1:
        raise ValueError("classification reuse source or catalog dependency changed")
    corpus = read_ref(corpus_refs[0], BatchCorpusV1)
    if (
        corpus.corpus_sha256 != origin.source_corpus_sha256
        or catalog_refs[0].sha256
        != hashlib.sha256(batch_json_bytes_830_g3(request.catalog)).hexdigest()
    ):
        raise ValueError("classification reuse source or catalog dependency changed")

    corpus_materials = tuple(row.material_id for row in corpus.entries)
    if corpus_materials != tuple(row.material_id for row in origin.source_materials):
        raise ValueError("classification reuse origin material scope mismatch")
    for entry, material in zip(corpus.entries, origin.source_materials, strict=True):
        if (
            entry.entry_sha256 != material.corpus_entry_sha256
            or hashlib.sha256(canonical_json(entry.receipt.model_dump(mode="json"))).hexdigest()
            != material.source_revision_receipt_sha256
            or hashlib.sha256(
                canonical_json([block.model_dump(mode="json") for block in entry.blocks])
            ).hexdigest()
            != material.w1_sha256
        ):
            raise ValueError("classification reuse origin material binding mismatch")

    proposals = read(chain / "stage-results/C_CLASSIFY/proposal-batch.json", ProposalBatchV1)
    original_resolution = read(
        chain / "stage-results/C_CLASSIFY/resolution.json", BatchEntityResolutionV1
    )
    if (
        proposals.proposals_sha256 != origin.source_proposals_sha256
        or proposals.corpus_sha256 != corpus.corpus_sha256
        or original_resolution.batch_sha256 != origin.source_resolution_sha256
        or original_resolution.proposals_sha256 != proposals.proposals_sha256
        or original_resolution.corpus_sha256 != corpus.corpus_sha256
    ):
        raise ValueError("classification reuse original result mismatch")
    effective = (
        apply_title_routing_overlay(
            origin.title_overlay,
            corpus=corpus,
            catalog=request.catalog,
            source_proposals=proposals,
        )
        if origin.title_overlay is not None
        else proposals
    )
    model_receipts = {row.request_sha256: row for row in proposals.model_receipts}
    seen = []
    for call in plan.request_manifest.calls:
        call_terminal, semantic, policy_raw, _ = gateway._read_successful_g3_stage_call(
            plan=plan,
            call=call,
            admission_artifact_digest=origin.source_admission_digest,
            ledger_root=root,
        )
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
        call.request_body_sha256 for call in plan.request_manifest.calls
    }:
        raise ValueError("classification reuse incomplete original calls")
    return _VerifiedClassificationOrigin(
        corpus=corpus,
        proposals=proposals,
        effective_proposals=effective,
        source_materials=parent.payload.c_materials,
    )


def _validate_composite_outputs(
    receipt: G3ClassificationReuseV3,
    request: BatchConceptCompileRequest830G3V1,
    verified: tuple[_VerifiedClassificationOrigin, ...],
) -> None:
    """Check that current corpus/proposals are the exact canonical origin union."""

    import hashlib

    from insurance_harness.run_admission.g3_models import canonical_json

    if len(verified) != len(receipt.origins) or any(
        row.corpus.corpus_sha256 != origin.source_corpus_sha256
        or row.proposals.proposals_sha256 != origin.source_proposals_sha256
        or row.source_materials != origin.source_materials
        for origin, row in zip(receipt.origins, verified, strict=True)
    ):
        raise ValueError("classification reuse origin result binding mismatch")
    current_corpus = request.resolution_inputs.corpus
    current_proposals = request.resolution_inputs.proposals
    scopes = {
        (row.corpus.tenant_id, row.corpus.space_id, row.corpus.raw_kb_id, row.corpus.wiki_kb_id)
        for row in verified
    }
    current_scope = (
        current_corpus.tenant_id,
        current_corpus.space_id,
        current_corpus.raw_kb_id,
        current_corpus.wiki_kb_id,
    )
    if scopes != {current_scope}:
        raise ValueError("classification reuse origin source scope mismatch")
    entries = tuple(
        sorted(
            (entry for row in verified for entry in row.corpus.entries),
            key=lambda entry: entry.material_id,
        )
    )
    material_ids = tuple(entry.material_id for entry in entries)
    source_receipts = tuple(
        hashlib.sha256(canonical_json(entry.receipt.model_dump(mode="json"))).hexdigest()
        for entry in entries
    )
    if (
        len(material_ids) != len(set(material_ids))
        or len(source_receipts) != len(set(source_receipts))
        or entries != current_corpus.entries
    ):
        raise ValueError("classification reuse origin material or source overlap")
    proposal_rows = tuple(
        sorted(
            (proposal for row in verified for proposal in row.effective_proposals.proposals),
            key=lambda proposal: proposal.material_id,
        )
    )
    model_receipts = tuple(
        sorted(
            (binding for row in verified for binding in row.proposals.model_receipts),
            key=lambda binding: binding.request_sha256,
        )
    )
    payload = {
        "contract": "batch-identity-proposals.830.g3.v1",
        "corpus_sha256": current_corpus.corpus_sha256,
        "model_receipts": model_receipts,
        "proposals": proposal_rows,
    }
    merged = ProposalBatchV1.model_validate(
        {
            **payload,
            "proposals_sha256": batch_sha256_830_g3(payload["contract"], payload),
        }
    )
    if merged != current_proposals:
        raise ValueError("classification reuse current proposals are not the exact origin union")


def validate_classification_reuse(
    receipt: ClassificationReuse,
    *,
    request: BatchConceptCompileRequest830G3V1,
    ledger_root=None,
    admission_root=None,
    parent=None,
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

    receipt = parse_classification_reuse(receipt)
    root = Path(ledger_root if ledger_root is not None else gateway.G3_LEDGER_ROOT)
    admissions = Path(
        admission_root if admission_root is not None else evaluator._ADMISSION_STORE_ROOT
    )

    if isinstance(receipt, G3ClassificationReuseV3):
        verified = tuple(
            _verify_classification_origin(
                origin,
                request=request,
                ledger_root=root,
                admission_root=admissions,
            )
            for origin in receipt.origins
        )
        _validate_composite_outputs(receipt, request, verified)
        if parent is not None:
            validate_composite_parent_materials(receipt, parent=parent)
        validate_reuse_binding(receipt, request=request)
        return

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
        or original_resolution.batch_sha256 != receipt.source_resolution_sha256
        or original_resolution.proposals_sha256 != proposals.proposals_sha256
        or original_resolution.corpus_sha256 != receipt.source_corpus_sha256
    ):
        raise ValueError("classification reuse original result mismatch")
    effective = (
        apply_title_routing_overlay(
            receipt.title_overlay,
            corpus=request.resolution_inputs.corpus,
            catalog=request.catalog,
            source_proposals=proposals,
        )
        if isinstance(receipt, G3ClassificationReuseV2)
        else proposals
    )
    if effective != request.resolution_inputs.proposals:
        raise ValueError("classification reuse effective proposals mismatch")
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
