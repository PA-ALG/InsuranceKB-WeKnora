from __future__ import annotations

# Partial test doubles isolate the stated boundary; admission is tested separately.
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import (
    batch_sha256_830_g3,
)
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCompileRequest830G3V1,
    validate_batch_candidate,
)
from insurance_harness.knowledge_compiler.batch_entity_resolution_830_g3 import (
    BatchCorpusV1,
    ProposalBatchV1,
)
from insurance_harness.knowledge_compiler.g3_classification_reuse import (
    G3ClassificationOriginV1,
    _VerifiedClassificationOrigin,
)
from insurance_harness.run_admission.g3_models import (
    G3AuthorizedMaterialV1,
    G3BoundedAdmissionPlanV1,
    G3ModelProcessingAuthorizationV1,
    canonical_json,
)

FIXTURE = Path(__file__).parent / "fixtures/batch_concept_compile_830_g3/candidate.json"


def _material(index: int) -> G3AuthorizedMaterialV1:
    return G3AuthorizedMaterialV1(
        material_id=f"material-{index}",
        corpus_entry_sha256=f"{index + 10:064x}",
        source_revision_receipt_sha256=f"{index + 20:064x}",
        w1_sha256=f"{index + 30:064x}",
        native_page_map_sha256=f"{index + 40:064x}",
    )


def _origin(api: ModuleType, index: int) -> G3ClassificationOriginV1:
    result: G3ClassificationOriginV1 = api.G3ClassificationOriginV1(
        contract="g3-classification-origin.830.v1",
        source_chain_manifest_hash=f"{index:064x}",
        source_terminal_receipt_sha256=f"{index + 2:064x}",
        source_admission_digest=f"{index + 4:064x}",
        source_proposals_sha256=f"{index + 6:064x}",
        source_resolution_sha256=f"{index + 8:064x}",
        source_corpus_sha256=f"{index + 10:064x}",
        source_materials=(_material(index),),
        title_overlay=None,
    )
    return result


def _batch(contract: str, **payload: object) -> dict[str, Any]:
    value = {"contract": contract, **payload}
    digest_field = {
        "batch-corpus.830.g3.v1": "corpus_sha256",
        "batch-identity-proposals.830.g3.v1": "proposals_sha256",
    }[contract]
    return {**value, digest_field: batch_sha256_830_g3(contract, value)}


def _verified_origins_for_current_request(
    api: ModuleType, request: BatchConceptCompileRequest830G3V1
) -> tuple[tuple[G3ClassificationOriginV1, ...], tuple[_VerifiedClassificationOrigin, ...]]:
    current_corpus = request.resolution_inputs.corpus
    current_proposals = request.resolution_inputs.proposals
    split = 2
    entries_by_origin = (current_corpus.entries[:split], current_corpus.entries[split:])
    proposals_by_id = {row.material_id: row for row in current_proposals.proposals}
    verified = []
    origins = []
    for index, entries in enumerate(entries_by_origin, start=1):
        corpus = BatchCorpusV1.model_validate(
            _batch(
                current_corpus.contract,
                tenant_id=current_corpus.tenant_id,
                space_id=current_corpus.space_id,
                raw_kb_id=current_corpus.raw_kb_id,
                wiki_kb_id=current_corpus.wiki_kb_id,
                entries=entries,
            )
        )
        proposals = ProposalBatchV1.model_validate(
            _batch(
                current_proposals.contract,
                corpus_sha256=corpus.corpus_sha256,
                model_receipts=current_proposals.model_receipts if index == 1 else (),
                proposals=tuple(proposals_by_id[entry.material_id] for entry in entries),
            )
        )
        materials = tuple(
            _material(index * 10 + material_index).model_copy(
                update={
                    "material_id": entry.material_id,
                    "corpus_entry_sha256": entry.entry_sha256,
                }
            )
            for material_index, entry in enumerate(entries)
        )
        origin = _origin(api, index).model_copy(
            update={
                "source_corpus_sha256": corpus.corpus_sha256,
                "source_proposals_sha256": proposals.proposals_sha256,
                "source_materials": materials,
            }
        )
        origins.append(origin)
        verified.append(
            api._VerifiedClassificationOrigin(
                corpus=corpus,
                proposals=proposals,
                effective_proposals=proposals,
                source_materials=materials,
            )
        )
    return tuple(origins), tuple(verified)


def test_composite_contract_binds_current_request_and_exposes_real_anchor() -> None:
    from insurance_harness.knowledge_compiler import g3_classification_reuse as api

    request = validate_batch_candidate(FIXTURE.read_bytes()).request
    origins = (_origin(api, 1), _origin(api, 2))
    receipt = api.build_composite_classification_reuse(request=request, origins=origins)

    restored = api.parse_classification_reuse(
        canonical_json(receipt.model_dump(mode="json", round_trip=True))
    )
    assert isinstance(restored, api.G3ClassificationReuseV3)
    assert restored.origins == origins
    assert restored.source_terminal_receipt_sha256 == origins[0].source_terminal_receipt_sha256
    assert restored.current_corpus_sha256 == request.resolution_inputs.corpus.corpus_sha256
    assert restored.current_proposals_sha256 == request.resolution_inputs.proposals.proposals_sha256
    api.validate_reuse_binding(restored, request=request)


def test_composite_contract_rejects_noncanonical_or_overlapping_origins() -> None:
    from insurance_harness.knowledge_compiler import g3_classification_reuse as api

    request = validate_batch_candidate(FIXTURE.read_bytes()).request
    first, second = _origin(api, 1), _origin(api, 2)
    with pytest.raises(ValueError, match="canonical"):
        api.build_composite_classification_reuse(request=request, origins=(second, first))

    overlap = second.model_copy(update={"source_materials": first.source_materials})
    with pytest.raises(ValueError, match="overlap"):
        api.build_composite_classification_reuse(request=request, origins=(first, overlap))


def test_composite_parent_materials_must_equal_origin_union() -> None:
    from insurance_harness.knowledge_compiler import g3_classification_reuse as api

    request = validate_batch_candidate(FIXTURE.read_bytes()).request
    receipt = api.build_composite_classification_reuse(
        request=request, origins=(_origin(api, 1), _origin(api, 2))
    )
    parent = SimpleNamespace(
        c_materials=tuple(
            sorted(
                (receipt.origins[0].source_materials + receipt.origins[1].source_materials),
                key=lambda row: row.material_id,
            )
        )
    )
    api.validate_composite_parent_materials(receipt, parent=parent)
    parent.c_materials = parent.c_materials[:-1]
    with pytest.raises(ValueError, match="parent material"):
        api.validate_composite_parent_materials(receipt, parent=parent)


def test_composite_reopens_every_origin_without_fabricating_a_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.knowledge_compiler import g3_classification_reuse as api

    request = validate_batch_candidate(FIXTURE.read_bytes()).request
    receipt = api.build_composite_classification_reuse(
        request=request, origins=(_origin(api, 1), _origin(api, 2))
    )
    reopened = []

    def reopen(origin: G3ClassificationOriginV1, **_kwargs: object) -> SimpleNamespace:
        reopened.append(origin.source_terminal_receipt_sha256)
        return SimpleNamespace(origin=origin)

    monkeypatch.setattr(api, "_verify_classification_origin", reopen)
    monkeypatch.setattr(api, "_validate_composite_outputs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api, "validate_reuse_binding", lambda *_args, **_kwargs: None)
    api.validate_classification_reuse(receipt, request=request)
    assert reopened == [origin.source_terminal_receipt_sha256 for origin in receipt.origins]
    assert receipt.source_terminal_receipt_sha256 in reopened
    assert receipt.receipt_sha256 == batch_sha256_830_g3(
        receipt.contract, receipt.model_dump(exclude={"receipt_sha256"})
    )


def test_composite_outputs_require_one_matching_result_per_origin() -> None:
    from insurance_harness.knowledge_compiler import g3_classification_reuse as api

    request = validate_batch_candidate(FIXTURE.read_bytes()).request
    receipt = api.build_composite_classification_reuse(
        request=request, origins=(_origin(api, 1), _origin(api, 2))
    )
    incomplete = (
        api._VerifiedClassificationOrigin(
            corpus=request.resolution_inputs.corpus,
            proposals=request.resolution_inputs.proposals,
            effective_proposals=request.resolution_inputs.proposals,
            source_materials=receipt.origins[0].source_materials,
        ),
    )
    with pytest.raises(ValueError, match="origin result binding"):
        api._validate_composite_outputs(receipt, request, incomplete)


def test_composite_outputs_accept_origins_in_the_current_four_field_scope() -> None:
    from insurance_harness.knowledge_compiler import g3_classification_reuse as api

    request = validate_batch_candidate(FIXTURE.read_bytes()).request
    origins, verified = _verified_origins_for_current_request(api, request)
    receipt = api.build_composite_classification_reuse(request=request, origins=origins)

    api._validate_composite_outputs(receipt, request, verified)


def test_runtime_accepts_v3_and_checks_the_real_anchor_and_current_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.knowledge_compiler import g3_bounded_model_execution as runtime
    from insurance_harness.knowledge_compiler import g3_classification_reuse as api

    request = validate_batch_candidate(FIXTURE.read_bytes()).request
    receipt = api.build_composite_classification_reuse(
        request=request, origins=(_origin(api, 1), _origin(api, 2))
    )
    artifacts = {
        receipt.contract: [canonical_json(receipt.model_dump(mode="json", round_trip=True))],
        request.contract: [canonical_json(request.model_dump(mode="json", round_trip=True))],
    }
    parent = SimpleNamespace(
        c_materials=tuple(
            sorted(
                (material for origin in receipt.origins for material in origin.source_materials),
                key=lambda row: row.material_id,
            )
        )
    )
    observed = []
    monkeypatch.setattr(
        api,
        "validate_classification_reuse",
        lambda reuse, **kwargs: observed.append((reuse, kwargs)),
    )
    plan = SimpleNamespace(
        stage="D_COMPILE",
        prior_terminal_receipt_sha256=receipt.source_terminal_receipt_sha256,
    )
    runtime._validate_g3_prior_stage_results(
        cast(G3BoundedAdmissionPlanV1, plan),
        artifacts,
        parent=cast(G3ModelProcessingAuthorizationV1, parent),
    )
    assert observed == [(receipt, {"request": request, "parent": parent})]
    plan.prior_terminal_receipt_sha256 = "f" * 64
    with pytest.raises(ValueError, match="prior"):
        runtime._validate_g3_prior_stage_results(
            cast(G3BoundedAdmissionPlanV1, plan),
            artifacts,
            parent=cast(G3ModelProcessingAuthorizationV1, parent),
        )
