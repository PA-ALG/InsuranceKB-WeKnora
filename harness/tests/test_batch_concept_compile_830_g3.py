from __future__ import annotations

import importlib
import importlib.util
import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

ROOT = Path(__file__).parents[2]
BASE_BUNDLE = ROOT / "docs/insurance-kb/evidence/830-g2/b-source-complete-candidate-bundle.json"
CATALOG = ROOT / "docs/insurance-kb/evidence/830-g3/catalog/catalog.json"
ALIGNMENTS = (
    ROOT
    / "docs/insurance-kb/evidence/830-g3/unknown-field-key-alignment-exact-fixture.json"
)
G3_FIXTURE = ROOT / "harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json"
G3_PREPARATION = (
    ROOT / "harness/tests/fixtures/batch_concept_compile_830_g3/preparation-request.json"
)
G3_PROVENANCE = ROOT / "harness/tests/fixtures/batch_concept_compile_830_g3/provenance.json"


def _fixture_request_json() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(G3_FIXTURE.read_bytes())["request"])


def _rehash_binding(module: ModuleType, binding: dict[str, Any]) -> None:
    binding["binding_sha256"] = module._batch_sha256(
        binding["contract"],
        {key: value for key, value in binding.items() if key != "binding_sha256"},
    )


def _validate_rehashed_request(module: ModuleType, request: dict[str, Any]) -> Any:
    request["request_sha256"] = module._batch_sha256(
        request["contract"],
        {key: value for key, value in request.items() if key != "request_sha256"},
    )
    return module.BatchConceptCompileRequest830G3V1.model_validate(request)


@lru_cache(maxsize=1)
def _expanded_selected_material_inputs(module: ModuleType) -> tuple[Any, ...]:
    resolution_api = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_entity_resolution_830_g3"
    )
    concept_api = importlib.import_module(
        "insurance_harness.knowledge_compiler.concept_free_wiki_830_g2"
    )
    g2 = _g2()
    request = module.validate_batch_candidate(G3_FIXTURE.read_bytes()).request
    selected = next(
        item for item in request.entity_bindings if item.resolution_disposition == "CREATE"
    )
    material_id = selected.source_material_ids[0]
    entry = next(
        item
        for item in request.resolution_inputs.corpus.entries
        if item.material_id == material_id
    )
    refs = tuple(
        sorted(
            (ref.material_id, ref.proposal_ref)
            for binding in request.entity_bindings
            for ref in binding.resolution_refs
        )
    )
    existing_field_block = next(
        (item for item in entry.blocks if item.block_id.endswith("-field-body")), None
    )
    if existing_field_block is not None:
        return (
            request,
            request.base_request,
            request.resolution_inputs.corpus,
            request.resolution_inputs.proposals,
            request.resolution,
            existing_field_block,
            refs,
        )
    identity_block = entry.blocks[0]
    field_block = identity_block.model_copy(
        update={
            "block_id": identity_block.block_id + "-field-body",
            "text": "保险责任正文：本示例产品按合同约定承担给付责任。",
        }
    )
    entry_payload = entry.model_dump(mode="json", exclude={"entry_sha256"})
    entry_payload["blocks"] = sorted(
        (*entry.blocks, field_block), key=lambda item: (item.revision_id, item.block_id)
    )
    entry_payload["entry_sha256"] = resolution_api._batch_sha256(
        "corpus-entry.830.g3.v1", entry_payload
    )
    expanded_entry = resolution_api.CorpusEntryV1.model_validate(entry_payload)

    corpus = request.resolution_inputs.corpus
    corpus_payload = corpus.model_dump(mode="json", exclude={"corpus_sha256"})
    corpus_payload["entries"] = sorted(
        (
            expanded_entry if item.material_id == material_id else item
            for item in corpus.entries
        ),
        key=lambda item: item.material_id,
    )
    corpus_payload["corpus_sha256"] = resolution_api._batch_sha256(
        corpus.contract, corpus_payload
    )
    expanded_corpus = resolution_api.BatchCorpusV1.model_validate(corpus_payload)
    field_evidence = resolution_api.ProposalEvidenceV1(
        evidence_id=material_id + "-coverage-field",
        entity_proposal_ref=selected.resolution_refs[0].proposal_ref,
        purpose="field",
        field_key="coverage_responsibilities",
        evidence=concept_api.evidence_for(field_block, 0, len(field_block.text)),
    )

    proposals = request.resolution_inputs.proposals
    proposal_rows = []
    for proposal in proposals.proposals:
        if proposal.material_id != material_id:
            proposal_rows.append(proposal)
            continue
        proposal_payload = proposal.model_dump(mode="json", exclude={"proposal_sha256"})
        proposal_payload["corpus_entry_sha256"] = expanded_entry.entry_sha256
        proposal_payload["evidence"] = sorted(
            (*proposal.evidence, field_evidence), key=lambda item: item.evidence_id
        )
        proposal_payload["proposal_sha256"] = resolution_api._batch_sha256(
            "material-proposal.830.g3.v1", proposal_payload
        )
        proposal_rows.append(
            resolution_api.MaterialProposalV1.model_validate(proposal_payload)
        )
    receipt_rows = []
    for receipt in proposals.model_receipts:
        material_bindings = tuple(
            item.model_copy(update={"corpus_entry_sha256": expanded_entry.entry_sha256})
            if item.material_id == material_id
            else item
            for item in receipt.material_bindings
        )
        input_sha256 = resolution_api._batch_sha256(
            "batch-classifier-input.830.g3.v1",
            {
                "corpus_sha256": expanded_corpus.corpus_sha256,
                "material_bindings": [
                    item.model_dump(mode="json") for item in material_bindings
                ],
            },
        )
        receipt_rows.append(
            receipt.model_copy(
                update={
                    "material_bindings": material_bindings,
                    "input_sha256": input_sha256,
                }
            )
        )
    proposals_payload = proposals.model_dump(mode="json", exclude={"proposals_sha256"})
    proposals_payload.update(
        corpus_sha256=expanded_corpus.corpus_sha256,
        model_receipts=receipt_rows,
        proposals=proposal_rows,
    )
    proposals_payload["proposals_sha256"] = module._batch_sha256(
        proposals.contract, proposals_payload
    )
    expanded_proposals = resolution_api.ProposalBatchV1.model_validate(proposals_payload)
    expanded_resolution = resolution_api.resolve_batch(
        catalog=request.catalog,
        corpus=expanded_corpus,
        proposals=expanded_proposals,
        existing_entities=request.resolution_inputs.existing_entities,
        policy=request.resolution_inputs.policy,
    )
    base_payload = request.base_request.model_dump(mode="json")
    base_payload["sources"] = sorted(
        (*request.base_request.sources, field_block),
        key=lambda item: (item.revision_id, item.block_id),
    )
    expanded_base = g2.CompileRequest.model_validate(base_payload)
    return (
        request,
        expanded_base,
        expanded_corpus,
        expanded_proposals,
        expanded_resolution,
        field_block,
        refs,
    )


@lru_cache(maxsize=1)
def _proper_expanded_request(module: ModuleType) -> tuple[Any, Any]:
    (
        request,
        expanded_base,
        expanded_corpus,
        expanded_proposals,
        expanded_resolution,
        field_block,
        refs,
    ) = _expanded_selected_material_inputs(module)
    return (
        module.build_batch_compile_request(
            base_request=expanded_base,
            catalog_json=CATALOG.read_bytes(),
            profile_confirmation_json=(
                ROOT / "docs/insurance-kb/evidence/830-g3/profile-user-confirmation.json"
            ).read_bytes(),
            corpus=expanded_corpus,
            proposals=expanded_proposals,
            existing_entities=request.resolution_inputs.existing_entities,
            policy=request.resolution_inputs.policy,
            resolution=expanded_resolution,
            selected_decision_refs=refs,
        ),
        field_block,
    )


def _record_delta_with_page(
    module: ModuleType, request: Any, *, entity_id: str, evidence: Any
) -> Any:
    concept_api = importlib.import_module(
        "insurance_harness.knowledge_compiler.concept_free_wiki_830_g2"
    )
    g2 = _g2()
    original = module.validate_batch_candidate(G3_FIXTURE.read_bytes())
    page = concept_api.FreeWikiPage(
        space_id=request.base_request.space_id,
        entity_id=entity_id,
        stable_key="fixture-owner-carry-source-page",
        title="Owner carry source fixture",
        body="Synthetic protocol page grounded in one carried source.",
        evidence=(evidence,),
        entity_version=request.base_request.entity_versions[entity_id],
    )
    audit = (
        *original.model_compile_result.output.audit,
        g2.AuditDisposition(
            key=g2.free_page_id(page),
            disposition="new_page",
            reason="SYNTHETIC_OWNER_CARRY_SOURCE_FIXTURE",
        ),
    )
    output = original.model_compile_result.output.model_copy(
        update={
            "request_hash": request.base_request.request_hash,
            "pages": (page,),
            "audit": tuple(sorted(audit, key=lambda item: item.key)),
        }
    )
    raw = module._canonical_json(output)
    return module.record_model_compile(
        request,
        output,
        run_id="fixture-owner-carry-source-run",
        implementation="fixture-static-protocol-compiler",
        raw=raw,
    )


def _g2() -> ModuleType:
    return importlib.import_module(
        "insurance_harness.knowledge_compiler.concept_compile_830_g2"
    )


def _current_alignment_validator() -> Any:
    """Use the current seam until the G3 module exists; never fail on a missing import."""

    name = "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    if importlib.util.find_spec(name) is None:
        return lambda request, output, _rows: _g2().validate_output(request, output)
    return importlib.import_module(name).validate_unknown_field_key_alignments


def _aligned_output(*, tamper_unknown_reason: bool) -> tuple[Any, Any, tuple[dict[str, Any], ...]]:
    g2 = _g2()
    catalog_api = importlib.import_module(
        "insurance_harness.knowledge_compiler.schema_pack_catalog_830_g3"
    )
    bundle = g2.CandidateBundle.model_validate_json(BASE_BUNDLE.read_text())
    catalog = catalog_api.validate_catalog(CATALOG.read_bytes())
    medical = next(
        entry
        for entry in catalog.entries
        if entry.pack.schema_pack_id == "schemapack_medical_insurance"
    )
    required = tuple(
        field.field_key for section in medical.profile.sections for field in section.fields
    )
    request_data = bundle.request.model_dump(mode="json")
    request_data.update(
        base_release_id="release-9cb493e3-8d27-4a0f-8f29-93e2a078725b",
        base_activation_epoch=5,
        existing_definitions=[
            item.model_dump(mode="json") for item in bundle.compile_result.output.definitions
        ],
        existing_fields=[
            item.model_dump(mode="json") for item in bundle.compile_result.output.fields
        ],
        existing_pages=[
            item.model_dump(mode="json") for item in bundle.compile_result.output.pages
        ],
        existing_entity_versions=bundle.request.entity_versions,
        required_fields={entity_id: list(required) for entity_id in bundle.request.entity_versions},
        schema_identity="catalog:fixture",
        profile_identity="profile-set:fixture",
    )
    request = g2.CompileRequest.model_validate(request_data)
    fields = []
    for field in bundle.compile_result.output.fields:
        if field.field_key == "social_insurance_requirement":
            field = field.model_copy(update={"field_key": "social_insurance_requirements"})
            if tamper_unknown_reason and field.entity_id == "ping-an-e-sheng-bao":
                field = field.model_copy(update={"unknown_reason": "TAMPERED_BUT_STILL_UNKNOWN"})
        fields.append(field)
    audit = [
        g2.AuditDisposition(
            key=definition.concept_id,
            disposition="alias_link",
            reason="BASE_CARRYOVER",
        )
        for definition in bundle.compile_result.output.definitions
    ]
    audit.extend(
        g2.AuditDisposition(
            key=field.assertion_id,
            disposition="field_rule",
            reason="BASE_CARRYOVER",
        )
        for field in fields
    )
    audit.extend(
        g2.AuditDisposition(
            key=g2.free_page_id(page),
            disposition="alias_link",
            reason="BASE_CARRYOVER",
        )
        for page in bundle.compile_result.output.pages
    )
    output = bundle.compile_result.output.model_copy(
        update={
            "request_hash": request.request_hash,
            "fields": tuple(fields),
            "audit": tuple(sorted(audit, key=lambda item: item.key)),
        }
    )
    rows = tuple(json.loads(ALIGNMENTS.read_text())["alignments"])
    return request, output, rows


def test_unknown_alignment_rejects_changed_unknown_reason() -> None:
    request, output, rows = _aligned_output(tamper_unknown_reason=True)

    with pytest.raises(ValueError, match="BASE_UNKNOWN_KEY_MIGRATION_INELIGIBLE"):
        _current_alignment_validator()(request, output, rows)


def test_unknown_alignment_rejects_rehashed_false_member_digest() -> None:
    request, output, rows = _aligned_output(tamper_unknown_reason=False)
    contracts = importlib.import_module(
        "insurance_harness.knowledge_compiler.schema_wiki_contracts"
    )
    changed = dict(rows[0])
    changed["old_member_digest"] = "0" * 64
    changed["alignment_sha256"] = contracts.schema_wiki_sha256(
        changed["contract"],
        {key: value for key, value in changed.items() if key != "alignment_sha256"},
    )

    with pytest.raises(ValueError, match="BASE_UNKNOWN_KEY_MIGRATION_REQUIRED"):
        _current_alignment_validator()(request, output, (changed, rows[1]))


def test_g3_canonical_json_preserves_multiline_content() -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )

    assert module._canonical_json({"body": "first\nsecond\tvalue\rline"}) == (
        '{"body":"first\\nsecond\\tvalue\\rline"}'
    )


def test_batch_candidate_rejects_duplicate_json_key() -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    wire = G3_FIXTURE.read_text()
    duplicate = wire.replace(
        '{"admission":',
        '{"contract":"batch-concept-candidate-bundle.830.g3.v1","admission":',
        1,
    )

    with pytest.raises(module.BatchConceptCompileError, match="BATCH_CANDIDATE_INVALID"):
        module.validate_batch_candidate(duplicate)


def test_entity_binding_rejects_control_character_in_identity() -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    bundle = module.validate_batch_candidate(G3_FIXTURE.read_bytes())
    changed = bundle.request.entity_bindings[0].model_dump(mode="json")
    changed["product_code"] = "18\t14"
    changed["binding_sha256"] = module._batch_sha256(
        changed["contract"],
        {key: value for key, value in changed.items() if key != "binding_sha256"},
    )

    with pytest.raises(ValueError):
        module.EntityCompileBinding830G3V1.model_validate(changed)


@pytest.mark.parametrize(
    "field_name",
    (
        "display_name",
        "issuer",
        "product_code",
        "version_label",
        "version_anchor",
        "entity_key_sha256",
        "version_candidate_key_sha256",
    ),
)
def test_request_rejects_rehashed_binding_identity_drift(field_name: str) -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    request = _fixture_request_json()
    binding = next(
        item
        for item in request["entity_bindings"]
        if item["resolution_disposition"] == "MATCH"
    )
    if field_name == "version_anchor":
        binding[field_name] = deepcopy(binding[field_name])
        binding[field_name]["observed_value"] += "-TAMPER"
        binding[field_name]["normalized_value"] += "-TAMPER"
    elif field_name.endswith("_sha256"):
        binding[field_name] = "0" * 64
    else:
        binding[field_name] += "-TAMPER"
    _rehash_binding(module, binding)

    with pytest.raises(ValueError, match="RESOLUTION_REFERENCE_INVALID"):
        _validate_rehashed_request(module, request)


@pytest.mark.parametrize(
    "field_name", ("entity_key_sha256", "version_candidate_key_sha256")
)
def test_request_rejects_create_binding_key_drift_from_exact_candidate(
    field_name: str,
) -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    request = _fixture_request_json()
    binding = next(
        item
        for item in request["entity_bindings"]
        if item["resolution_disposition"] == "CREATE"
    )
    binding[field_name] = "0" * 64
    _rehash_binding(module, binding)

    with pytest.raises(ValueError, match="RESOLUTION_REFERENCE_INVALID"):
        _validate_rehashed_request(module, request)


def test_request_rejects_evidence_borrowed_from_unselected_child() -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    request = _fixture_request_json()
    target, foreign = request["entity_bindings"][:2]
    target["resolution_evidence"].append(deepcopy(foreign["resolution_evidence"][0]))
    target["resolution_evidence"].sort(
        key=lambda item: (item["material_id"], item["evidence_id"])
    )
    _rehash_binding(module, target)

    with pytest.raises(ValueError, match="RESOLUTION_EVIDENCE_MISSING"):
        _validate_rehashed_request(module, request)


def test_request_rejects_rehashed_fabricated_profile_confirmation() -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    request = _fixture_request_json()
    confirmation = request["profile_confirmation"]
    confirmation["receipt"]["actor"] = "fabricated-confirmation-actor"
    confirmation["receipt_semantic_sha256"] = module._batch_sha256(
        confirmation["receipt"]["contract"], confirmation["receipt"]
    )

    with pytest.raises(ValueError, match="PROFILE_CONFIRMATION_MISMATCH"):
        _validate_rehashed_request(module, request)


@pytest.mark.parametrize("changed_part", ("text", "source_type"))
def test_request_rejects_different_bytes_for_same_corpus_source_identity(
    changed_part: str,
) -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    request = _fixture_request_json()
    corpus_block = request["resolution_inputs"]["corpus"]["entries"][0]["blocks"][0]
    base_source = next(
        item
        for item in request["base_request"]["sources"]
        if (item["revision_id"], item["block_id"])
        == (corpus_block["revision_id"], corpus_block["block_id"])
    )
    if changed_part == "text":
        base_source["text"] += "\nTAMPER_OUTSIDE_EVIDENCE"
    else:
        base_source["source_type"] = "EXPERT_REVISION_RECORD"

    with pytest.raises(ValueError, match="SOURCE_CLOSURE_MISMATCH"):
        _validate_rehashed_request(module, request)


def test_actual342_fixture_round_trips_complete_base_and_registered_sources() -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    wire = G3_FIXTURE.read_bytes()
    bundle = module.validate_batch_candidate(wire)
    base_bundle = _g2().CandidateBundle.model_validate_json(BASE_BUNDLE.read_bytes())
    request = bundle.request

    assert module._canonical_json(bundle).encode() == wire
    assert request.base_request.existing_definitions == (
        base_bundle.compile_result.output.definitions
    )
    assert request.base_request.existing_fields == base_bundle.compile_result.output.fields
    assert request.base_request.existing_pages == base_bundle.compile_result.output.pages
    assert request.base_request.existing_entity_versions == base_bundle.request.entity_versions
    assert len(request.base_request.existing_fields) == 134
    assert len(request.unknown_field_key_alignments) == 2
    assert len(bundle.model_compile_result.output.fields) == 208
    assert len(bundle.compile_result.output.fields) == 342
    assert len({field.assertion_id for field in bundle.compile_result.output.fields}) == 342
    assert {
        entry.receipt.contract for entry in request.resolution_inputs.corpus.entries
    } == {"knowledge-revision-source.v1"}
    assert len(request.base_request.sources) == 27
    assert sorted(len(entry.blocks) for entry in request.resolution_inputs.corpus.entries) == [
        1,
        1,
        1,
        1,
        2,
    ]
    field_evidence = [
        evidence
        for proposal in request.resolution_inputs.proposals.proposals
        for evidence in proposal.evidence
        if evidence.purpose == "field"
    ]
    assert len(field_evidence) == 1
    assert any(
        field.state == "present"
        and field.field_key == field_evidence[0].field_key
        and field.evidence == (field_evidence[0].evidence,)
        for field in bundle.model_compile_result.output.fields
    )
    assert len(wire) < 8 * 1024 * 1024


def test_builder_replays_c_and_reconstructs_exact_fixture_request() -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    request = module.validate_batch_candidate(G3_FIXTURE.read_bytes()).request
    refs = tuple(
        sorted(
            (ref.material_id, ref.proposal_ref)
            for binding in request.entity_bindings
            for ref in binding.resolution_refs
        )
    )

    rebuilt = module.build_batch_compile_request(
        base_request=request.base_request,
        catalog_json=CATALOG.read_bytes(),
        profile_confirmation_json=(
            ROOT / "docs/insurance-kb/evidence/830-g3/profile-user-confirmation.json"
        ).read_bytes(),
        corpus=request.resolution_inputs.corpus,
        proposals=request.resolution_inputs.proposals,
        existing_entities=request.resolution_inputs.existing_entities,
        policy=request.resolution_inputs.policy,
        resolution=request.resolution,
        selected_decision_refs=refs,
    )

    assert rebuilt == request


def test_builder_accepts_all_blocks_from_selected_material() -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    rebuilt, field_block = _proper_expanded_request(module)

    assert field_block in rebuilt.base_request.sources


def test_request_rejects_missing_selected_body_block() -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    request, field_block = _proper_expanded_request(module)
    changed_base = request.base_request.model_copy(
        update={
            "sources": tuple(
                item
                for item in request.base_request.sources
                if (item.revision_id, item.block_id)
                != (field_block.revision_id, field_block.block_id)
            )
        }
    )

    with pytest.raises(module.BatchConceptCompileError, match="SOURCE_CLOSURE_MISMATCH"):
        module._validate_request_closure(
            request.model_copy(update={"base_request": changed_base})
        )


def test_request_rejects_unselected_extra_source_block() -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    request, field_block = _proper_expanded_request(module)
    extra = field_block.model_copy(
        update={
            "block_id": field_block.block_id + "-not-selected",
            "text": "未选择材料的额外正文块。",
        }
    )
    changed_base = request.base_request.model_copy(
        update={
            "sources": tuple(
                sorted(
                    (*request.base_request.sources, extra),
                    key=lambda item: (item.revision_id, item.block_id),
                )
            )
        }
    )

    with pytest.raises(module.BatchConceptCompileError, match="SOURCE_CLOSURE_MISMATCH"):
        module._validate_request_closure(
            request.model_copy(update={"base_request": changed_base})
        )


def test_delta_field_can_use_selected_material_body_block() -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    concept_api = importlib.import_module(
        "insurance_harness.knowledge_compiler.concept_free_wiki_830_g2"
    )
    request, field_block = _proper_expanded_request(module)
    material_id = next(
        entry.material_id
        for entry in request.resolution_inputs.corpus.entries
        if field_block in entry.blocks
    )
    binding = next(
        item for item in request.entity_bindings if material_id in item.source_material_ids
    )
    original = module.validate_batch_candidate(G3_FIXTURE.read_bytes())
    evidence = concept_api.evidence_for(field_block, 0, len(field_block.text))
    fields = tuple(
        item.model_copy(
            update={
                "state": "present",
                "value": field_block.text,
                "unknown_reason": None,
                "evidence": (evidence,),
            }
        )
        if (item.entity_id, item.field_key)
        == (binding.entity_id, "coverage_responsibilities")
        else item
        for item in original.model_compile_result.output.fields
    )
    output = original.model_compile_result.output.model_copy(
        update={"request_hash": request.base_request.request_hash, "fields": fields}
    )
    result = module.record_model_compile(
        request,
        output,
        run_id="fixture-selected-body-field-run",
        implementation="fixture-static-protocol-compiler",
        raw=module._canonical_json(output),
    )

    module.validate_delta_output(request, result)


def test_delta_page_can_use_own_carried_evidence_source() -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    request = module.validate_batch_candidate(G3_FIXTURE.read_bytes()).request
    owner_field = next(
        item for item in request.base_request.existing_fields if item.evidence
    )
    result = _record_delta_with_page(
        module,
        request,
        entity_id=owner_field.entity_id,
        evidence=owner_field.evidence[0],
    )

    module.validate_delta_output(request, result)


def test_delta_page_rejects_other_owner_only_carried_source() -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    request = module.validate_batch_candidate(G3_FIXTURE.read_bytes()).request
    owners = tuple(request.base_request.existing_entity_versions)
    target_owner, foreign_owner = owners
    target_keys = {
        (evidence.revision_id, evidence.block_id)
        for item in (
            *request.base_request.existing_fields,
            *request.base_request.existing_pages,
        )
        if item.entity_id == target_owner
        for evidence in item.evidence
    }
    foreign_evidence = next(
        evidence
        for item in request.base_request.existing_fields
        if item.entity_id == foreign_owner
        for evidence in item.evidence
        if (evidence.revision_id, evidence.block_id) not in target_keys
    )
    result = _record_delta_with_page(
        module,
        request,
        entity_id=target_owner,
        evidence=foreign_evidence,
    )

    with pytest.raises(module.BatchConceptCompileError, match="CROSS_ENTITY_EVIDENCE"):
        module.validate_delta_output(request, result)


def test_builder_rejects_missing_actual_base_match() -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    request = module.validate_batch_candidate(G3_FIXTURE.read_bytes()).request
    refs = tuple(
        sorted(
            (ref.material_id, ref.proposal_ref)
            for binding in request.entity_bindings
            if binding.entity_id != "ping-an-e-sheng-bao-hui-xiang"
            for ref in binding.resolution_refs
        )
    )

    with pytest.raises(module.BatchConceptCompileError, match="BASE_ENTITY_MATCH_REQUIRED"):
        module.build_batch_compile_request(
            base_request=request.base_request,
            catalog_json=CATALOG.read_bytes(),
            profile_confirmation_json=(
                ROOT / "docs/insurance-kb/evidence/830-g3/profile-user-confirmation.json"
            ).read_bytes(),
            corpus=request.resolution_inputs.corpus,
            proposals=request.resolution_inputs.proposals,
            existing_entities=request.resolution_inputs.existing_entities,
            policy=request.resolution_inputs.policy,
            resolution=request.resolution,
            selected_decision_refs=refs,
        )


def test_composition_has_exact_alignment_and_independent_execution_raws() -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    bundle = module.validate_batch_candidate(G3_FIXTURE.read_bytes())
    request = bundle.request
    aligned = module.aligned_existing_fields(request)
    old = {
        (field.entity_id, field.field_key): field
        for field in request.base_request.existing_fields
    }
    carried = {
        (field.entity_id, field.field_key): field
        for field in aligned
    }

    assert len(aligned) == 134
    assert sum(key[1] == "social_insurance_requirement" for key in old) == 2
    assert sum(key[1] == "social_insurance_requirements" for key in carried) == 2
    assert all(
        carried[key] == field
        for key, field in old.items()
        if key[1] != "social_insurance_requirement"
    )
    assert bundle.compile_result.execution.raw_output == module._canonical_json(
        bundle.compile_result.output
    )
    assert bundle.model_compile_result.execution.raw_output == module._canonical_json(
        bundle.model_compile_result.output
    )
    assert bundle.review_result.execution.raw_output == module._canonical_json(
        bundle.review_result.output
    )
    assert len(
        {
            bundle.model_compile_result.execution.run_id,
            bundle.compile_result.execution.run_id,
            bundle.review_result.execution.run_id,
        }
    ) == 3


def test_manifest_projects_all_field_payloads_and_profile_sections() -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    bundle = module.validate_batch_candidate(G3_FIXTURE.read_bytes())
    field_members = {
        member.member_id: member
        for member in bundle.page_manifest.members
        if member.kind == "field_assertion"
    }
    overviews = [
        member
        for member in bundle.page_manifest.members
        if member.kind == "entity_overview"
    ]

    assert len(field_members) == 342
    assert all(
        field_members[field.assertion_id].payload == field.model_dump(mode="json")
        for field in bundle.compile_result.output.fields
    )
    assert len(overviews) == 5
    assert sorted(
        sum(len(section["fields"]) for section in member.payload["sections"])
        for member in overviews
    ) == [62, 67, 67, 67, 79]
    assert sorted(len(member.payload["sections"]) for member in overviews) == [7, 7, 7, 8, 8]


def test_actual342_preparation_post_capacity_receipt_matches_exact_bytes() -> None:
    module = importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )
    post = G3_PREPARATION.read_bytes()
    payload = json.loads(post)
    provenance = json.loads(G3_PROVENANCE.read_bytes())

    assert module._canonical_json(payload).encode() == post
    assert payload["preparation_id"] == "fixture-g3-actual342"
    assert module.validate_batch_candidate(
        json.dumps(
            payload["batch_concept_candidate_bundle"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).candidate_hash
    assert provenance["fixture_counts"] == {
        "entities": 5,
        "fields": 342,
        "carried_fields": 132,
        "aligned_fields": 2,
        "delta_fields": 208,
        "source_blocks": 27,
    }
    assert provenance["preparation_post_bytes"] == len(post) == 2_254_490
    assert provenance["serialized_bytes"]["handler_limit"] == 8 * 1024 * 1024
    assert len(post) < provenance["serialized_bytes"]["handler_limit"]
