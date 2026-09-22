"""Synthetic compiler protocol fixtures: no provider or publication effects."""

import hashlib
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as g3
from insurance_harness.knowledge_compiler import batch_entity_resolution_830_g3 as resolution_api
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCandidateBundle830G3V1,
    BatchConceptCompileRequest830G3V1,
)
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
    AuditDisposition,
    CompileOutput,
    CompileRequest,
    ExecutionRecord,
    HumanBatchAdmission,
    ReviewOutput,
    ReviewResult,
)
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    ConceptDefinition,
    FieldAssertion,
    FreeWikiPage,
)

ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json"


def hashed[ModelT: BaseModel](
    cls: type[ModelT], domain: str, hash_field: str, **payload: object
) -> ModelT:
    return cls.model_validate({**payload, hash_field: g3._batch_sha256(domain, payload)})


@lru_cache(maxsize=1)
def published_subset_inputs() -> tuple[
    BatchConceptCandidateBundle830G3V1,
    CompileRequest,
    resolution_api.BatchCorpusV1,
    resolution_api.ProposalBatchV1,
    resolution_api.ExistingEntitySnapshotV1,
    resolution_api.BatchEntityResolutionV1,
    tuple[tuple[str, str], ...],
    dict[str, Any],
    g3.EntityCompileBinding830G3V1,
]:
    """Current fixture has five entities; current C selects only one of them."""
    parent = g3.validate_batch_candidate(FIXTURE.read_bytes())
    old = parent.request
    selected_binding = next(
        row for row in old.entity_bindings if row.resolution_disposition == "CREATE"
    )
    mids = set(selected_binding.source_material_ids)
    corpus_payload = old.resolution_inputs.corpus.model_dump(exclude={"corpus_sha256"})
    corpus_payload["entries"] = tuple(
        row for row in old.resolution_inputs.corpus.entries if row.material_id in mids
    )
    corpus = hashed(
        resolution_api.BatchCorpusV1, "batch-corpus.830.g3.v1", "corpus_sha256", **corpus_payload
    )
    receipt = old.resolution_inputs.proposals.model_receipts[0]
    material_bindings = tuple(row for row in receipt.material_bindings if row.material_id in mids)
    # This is an explicitly synthetic transport receipt, not a live model audit.
    receipt = receipt.model_copy(
        update={
            "material_bindings": material_bindings,
            "input_sha256": g3._batch_sha256(
                "batch-classifier-input.830.g3.v1",
                {"corpus_sha256": corpus.corpus_sha256, "material_bindings": material_bindings},
            ),
        }
    )
    proposals = hashed(
        resolution_api.ProposalBatchV1,
        "batch-identity-proposals.830.g3.v1",
        "proposals_sha256",
        contract="batch-identity-proposals.830.g3.v1",
        corpus_sha256=corpus.corpus_sha256,
        model_receipts=(receipt,),
        proposals=tuple(
            row for row in old.resolution_inputs.proposals.proposals if row.material_id in mids
        ),
    )
    entities = tuple(
        resolution_api.ExistingEntityV1(
            entity_id=row.entity_id,
            entity_version=row.entity_version,
            product_id=None,
            product_version_id=None,
            issuer=row.issuer,
            name=row.display_name,
            product_code=row.product_code,
            version_label=row.version_label,
            filing_or_registration=resolution_api.VersionAnchorV1(
                kind=row.version_anchor.kind, value=row.version_anchor.observed_value
            ),
            approved_aliases=(),
            identity_evidence_sha256s=tuple(
                sorted(
                    {
                        g3._batch_sha256("fixture-identity-evidence", e.evidence)
                        for e in row.resolution_evidence
                    }
                )
            ),
        )
        for row in old.entity_bindings
    )
    existing_payload = old.resolution_inputs.existing_entities.model_dump(
        exclude={"snapshot_sha256"}
    )
    existing_payload.update(
        base_release_id="release-platform-parent", base_activation_epoch=6, entities=entities
    )
    existing = hashed(
        resolution_api.ExistingEntitySnapshotV1,
        "existing-entities.830.g3.v1",
        "snapshot_sha256",
        **existing_payload,
    )
    resolution = resolution_api.resolve_batch(
        catalog=old.catalog,
        corpus=corpus,
        proposals=proposals,
        existing_entities=existing,
        policy=old.resolution_inputs.policy,
    )
    refs = tuple(
        (row.material_id, entity.proposal_ref)
        for row in proposals.proposals
        for entity in row.entities
    )
    new_bindings = g3._build_entity_bindings(
        catalog=old.catalog, proposals=proposals, resolution=resolution, selected_decision_refs=refs
    )
    selected = {row.entity_id: row for row in new_bindings}
    combined = tuple(selected.get(row.entity_id, row) for row in old.entity_bindings)
    sources = {(row.revision_id, row.block_id): row for row in old.base_request.sources}
    evidence_rows: tuple[ConceptDefinition | FieldAssertion | FreeWikiPage, ...] = (
        *parent.compile_result.output.definitions,
        *parent.compile_result.output.fields,
        *parent.compile_result.output.pages,
    )
    required = {(e.revision_id, e.block_id) for row in evidence_rows for e in row.evidence}
    required.update(
        (e.evidence.revision_id, e.evidence.block_id)
        for row in old.entity_bindings
        for e in row.resolution_evidence
    )
    required.update(
        (row.revision_id, row.block_id) for entry in corpus.entries for row in entry.blocks
    )
    base = CompileRequest.model_validate(
        {
            **old.base_request.model_dump(),
            "base_release_id": existing.base_release_id,
            "base_activation_epoch": existing.base_activation_epoch,
            "existing_definitions": parent.compile_result.output.definitions,
            "existing_fields": parent.compile_result.output.fields,
            "existing_pages": parent.compile_result.output.pages,
            "existing_entity_versions": old.base_request.entity_versions,
            "sources": tuple(sources[key] for key in sorted(sources)),
            "profile_identity": g3._profile_set_identity(combined),
        }
    )
    binding_payload = dict(
        contract="published-base-binding.830.g3.v1",
        release_id=existing.base_release_id,
        activation_epoch=existing.base_activation_epoch,
        candidate_sha256=parent.candidate_hash,
        manifest_digest=hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        entity_bindings=old.entity_bindings,
    )
    return (
        parent,
        base,
        corpus,
        proposals,
        existing,
        resolution,
        refs,
        binding_payload,
        selected_binding,
    )


def build(
    refresh_fields: tuple[tuple[str, str], ...] = (),
    changed: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> tuple[
    BatchConceptCandidateBundle830G3V1,
    BatchConceptCompileRequest830G3V1,
    g3.EntityCompileBinding830G3V1,
]:
    parent, base, corpus, proposals, existing, resolution, refs, payload, selected = (
        published_subset_inputs()
    )
    if changed:
        payload = changed(payload)
    cls = getattr(g3, "PublishedBaseBinding830G3V1", None)
    assert cls is not None, "platform published base binding is not implemented"
    binding = hashed(cls, "published-base-binding.830.g3.v1", "binding_sha256", **payload)
    request = g3.build_batch_compile_request(
        base_request=base,
        catalog_json=(ROOT / "docs/insurance-kb/evidence/830-g3/catalog/catalog.json").read_bytes(),
        profile_confirmation_json=(
            ROOT / "docs/insurance-kb/evidence/830-g3/profile-user-confirmation.json"
        ).read_bytes(),
        corpus=corpus,
        proposals=proposals,
        existing_entities=existing,
        policy=parent.request.resolution_inputs.policy,
        resolution=resolution,
        selected_decision_refs=refs,
        published_base=binding,
        refresh_fields=tuple(
            g3.FieldRefresh830G3V1(entity_id=e, field_key=f) for e, f in refresh_fields
        ),
    )
    return parent, request, selected


def test_current_product_only_c_carries_other_published_bindings_without_model_replay() -> None:
    parent, request, selected = build()
    assert len(request.resolution_inputs.proposals.proposals) == 1
    assert len(request.entity_bindings) == len(parent.request.entity_bindings)
    for row in request.entity_bindings:
        if row.entity_id != selected.entity_id:
            assert row in parent.request.entity_bindings
    assert g3.aligned_existing_fields(request) == parent.compile_result.output.fields


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: {**p, "release_id": "other"},
        lambda p: {**p, "activation_epoch": 7},
        lambda p: {**p, "entity_bindings": p["entity_bindings"][:-1]},
    ],
)
def test_published_binding_must_cover_exact_parent_identity(
    mutation: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    with pytest.raises(ValueError):
        build(changed=mutation)


def test_failed_field_refresh_excludes_only_selected_base_field_from_carry() -> None:
    *_, selected = published_subset_inputs()
    pair = (selected.entity_id, selected.required_fields[0])
    parent, request, _ = build(refresh_fields=(pair,))
    actual = g3.aligned_existing_fields(request)
    assert len(actual) == len(parent.compile_result.output.fields) - 1
    assert pair not in {(row.entity_id, row.field_key) for row in actual}


def test_refresh_cannot_target_a_carried_unselected_product() -> None:
    parent, *_ = published_subset_inputs()
    other = next(
        row for row in parent.request.entity_bindings if row.resolution_disposition == "MATCH"
    )
    with pytest.raises(ValueError):
        build(refresh_fields=((other.entity_id, other.required_fields[0]),))


def test_legacy_candidate_bytes_are_unchanged() -> None:
    raw = FIXTURE.read_bytes()
    assert g3._canonical_json(g3.validate_batch_candidate(raw)).encode() == raw


def refresh_candidate_fixture() -> tuple[
    BatchConceptCandidateBundle830G3V1, BatchConceptCandidateBundle830G3V1, tuple[str, str]
]:
    *_, selected = published_subset_inputs()
    pair = (selected.entity_id, selected.required_fields[0])
    parent, request, _ = build(refresh_fields=(pair,))
    field = FieldAssertion(
        space_id=request.base_request.space_id,
        entity_id=pair[0],
        field_key=pair[1],
        state="unknown",
        value=None,
        attempted=True,
        unknown_reason="PROTOCOL_FIXTURE_EXTRACTION_FAILED",
        entity_version=request.base_request.entity_versions[pair[0]],
    )
    output = CompileOutput(
        request_hash=g3.compile_request_hash_g3(request.base_request),
        fields=(field,),
        audit=(
            AuditDisposition(
                key=field.assertion_id, disposition="field_rule", reason="VALIDATED_FIELD_ARTIFACT"
            ),
        ),
    )
    delta = g3.record_model_compile(
        request,
        output,
        run_id="fixture-field-projection",
        implementation="synthetic-platform-field-projector.v1",
        raw=g3._canonical_json(output),
    )
    composed = g3.record_composed_output(
        request, delta, g3.compose_batch_output(request, delta), run_id="fixture-base-carry"
    )
    review_output = ReviewOutput(
        request_hash=g3.compile_request_hash_g3(request.base_request),
        output_hash=g3.compile_output_hash_g3(composed.output),
        decision="PASS",
        reasons=("SYNTHETIC_PROTOCOL_FIXTURE_ONLY",),
    )
    raw = g3._canonical_json(review_output)
    review = ReviewResult(
        output=review_output,
        execution=ExecutionRecord(
            run_id="fixture-review",
            implementation="synthetic-review.v1",
            context_hash=g3._batch_sha256(
                "batch-concept-review-context.830.g3.v1",
                g3.review_context_g3(request, composed.output),
            ),
            raw_output=raw,
            raw_output_hash=hashlib.sha256(raw.encode()).hexdigest(),
        ),
    )
    result = g3.assemble_candidate_bundle(
        request,
        delta,
        composed,
        review,
        HumanBatchAdmission(
            contract="concept-admission.830.g2.v1", status="NEEDS_HUMAN", pending_page_ids=()
        ),
    )
    return parent, result, pair


def test_refresh_delta_replaces_exactly_one_and_retains_every_other_field() -> None:
    parent, result, pair = refresh_candidate_fixture()
    assert len(result.model_compile_result.output.fields) == 1
    previous = {(row.entity_id, row.field_key): row for row in parent.compile_result.output.fields}
    actual = {(row.entity_id, row.field_key): row for row in result.compile_result.output.fields}
    assert len(actual) == len(previous)
    assert all(value == actual[key] for key, value in previous.items() if key != pair)
    assert actual[pair].unknown_reason == "PROTOCOL_FIXTURE_EXTRACTION_FAILED"
    wrong = next(value for key, value in previous.items() if key != pair)
    output = result.model_compile_result.output.model_copy(
        update={"fields": (*result.model_compile_result.output.fields, wrong)}
    )
    invalid = g3.record_model_compile(
        result.request,
        output,
        run_id="fixture-bad-projection",
        implementation="synthetic-invalid-projector",
        raw=g3._canonical_json(output),
    )
    with pytest.raises(ValueError, match="DELTA_FIELD_COVERAGE_MISMATCH"):
        g3.compose_batch_output(result.request, invalid)


def test_omitted_incremental_defaults_survive_typed_revalidation() -> None:
    request = g3.validate_batch_candidate(FIXTURE.read_bytes()).request
    assert request.published_base is None and request.refresh_fields == ()
    again = g3.BatchConceptCompileRequest830G3V1.model_validate(request)
    assert again == request
    assert '"refresh_fields"' not in again.model_dump_json()
    assert '"published_base"' not in again.model_dump_json()
    for key, value in (("published_base", None), ("refresh_fields", [])):
        wire = request.model_dump(mode="json")
        wire[key] = value
        with pytest.raises(ValueError, match="EMPTY_INCREMENTAL_EXTENSION_MUST_BE_OMITTED"):
            g3.BatchConceptCompileRequest830G3V1.model_validate(wire)
