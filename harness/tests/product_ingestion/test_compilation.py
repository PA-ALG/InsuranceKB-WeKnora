import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
from insurance_harness.knowledge_compiler import batch_entity_resolution_830_g3 as resolver
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
    ExecutionRecord,
    ReviewOutput,
    ReviewResult,
    ValueScore,
    free_page_id,
)
from insurance_harness.knowledge_compiler.g3_field_tasks import (
    FieldTaskEvidenceResultV1,
    adapt_catalog_field_tasks,
)
from insurance_harness.product_ingestion.compilation import (
    assemble_platform_candidate,
    build_existing_snapshot,
    build_platform_compile_request,
    project_field_attempts,
)
from insurance_harness.product_ingestion.models import FieldOutcomeKind, ProductScope

ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "harness/tests/fixtures/batch_concept_compile_830_g3"
CATALOG = ROOT / "docs/insurance-kb/evidence/830-g3/catalog/catalog.json"
CONFIRMATION = ROOT / "docs/insurance-kb/evidence/830-g3/profile-user-confirmation.json"


@lru_cache(maxsize=1)
def candidates():
    parent = compiler.validate_batch_candidate((FIXTURES / "candidate.json").read_bytes())
    child = compiler.validate_batch_candidate(
        (FIXTURES / "platform-incremental-candidate.json").read_bytes()
    )
    return parent, child


def scope_for(parent):
    base = parent.request.base_request
    return ProductScope(
        tenant_id=str(base.tenant_id),
        space_id=base.space_id,
        raw_knowledge_base_id=base.raw_kb_id,
        wiki_knowledge_base_id=base.wiki_kb_id,
    )


def base_body(parent, child):
    binding = child.request.published_base
    assert binding is not None
    base = parent.request.base_request
    entity_versions = {row.entity_id: row.entity_version for row in parent.request.entity_bindings}
    members = tuple(
        {
            "kind": row.kind,
            "logical_slug": row.member_id,
            "revision_id": parent.candidate_hash,
            "member_digest": compiler._batch_sha256("batch-concept-member.830.g3.v1", row),
        }
        for row in parent.page_manifest.members
    )
    return {
        "contract": "g3-platform-base-snapshot.830.v1",
        "scope": {
            "tenant_id": base.tenant_id,
            "space_id": base.space_id,
            "raw_kb_id": base.raw_kb_id,
            "wiki_kb_id": base.wiki_kb_id,
        },
        "release_id": binding.release_id,
        "activation_epoch": binding.activation_epoch,
        "preparation_id": "platform-parent-preparation",
        "candidate_sha256": parent.candidate_hash,
        "manifest_digest": binding.manifest_digest,
        "published_projection_contract": "g3-platform-published-projection.830.v1",
        "published_projection": {
            "contract": "g3-platform-published-projection.830.v1",
            "origin_contract": "published-batch-read-projection.830.g3.v2",
            "parent": {
                "release_id": base.base_release_id,
                "activation_epoch": base.base_activation_epoch,
            },
            "sources": base.sources,
            "catalog": {
                "catalog_id": parent.request.catalog.catalog_id,
                "catalog_version": parent.request.catalog.catalog_version,
                "catalog_sha256": parent.request.catalog.catalog_sha256,
            },
            "entity_bindings": parent.request.entity_bindings,
            "entity_versions": entity_versions,
            "definitions": parent.compile_result.output.definitions,
            "fields": parent.compile_result.output.fields,
            "pages": parent.compile_result.output.pages,
            "page_members": parent.page_manifest.members,
            "navigation_assignments": parent.navigation_assignments,
            "candidate_hash": parent.candidate_hash,
        },
        "members": members,
        "snapshot_sha256": "a" * 64,
    }


@lru_cache(maxsize=1)
def platform_request():
    parent, child = candidates()
    scope = scope_for(parent)
    body = base_body(parent, child)
    current = child.request.resolution_inputs
    existing = build_existing_snapshot(scope=scope, base_body=body, policy=current.policy)
    resolution = resolver.resolve_batch(
        catalog=child.request.catalog,
        corpus=current.corpus,
        proposals=current.proposals,
        existing_entities=existing,
        policy=current.policy,
        compiler_version=resolver.COMPILER_VERSION_V2,
    )
    refs = tuple(
        sorted(
            (row.material_id, item.proposal_ref)
            for row in resolution.decisions
            for item in row.children
        )
    )
    refresh = tuple(
        {"entity_id": row.entity_id, "field_key": row.field_key}
        for row in child.request.refresh_fields
    )
    request = build_platform_compile_request(
        scope=scope,
        base_body=body,
        catalog_json=CATALOG.read_bytes(),
        profile_confirmation_json=CONFIRMATION.read_bytes(),
        corpus=current.corpus,
        proposals=current.proposals,
        policy=current.policy,
        resolution=resolution,
        selected_refs=refs,
        refresh_fields=refresh,
    )
    return parent, request


def test_existing_snapshot_is_derived_from_real_signed_parent_closure():
    parent, child = candidates()
    scope = scope_for(parent)
    body = base_body(parent, child)
    existing = build_existing_snapshot(
        scope=scope,
        base_body=body,
        policy=child.request.resolution_inputs.policy,
    )

    assert existing.head_receipt_sha256 == body["snapshot_sha256"]
    assert existing.base_release_id == body["release_id"]
    assert existing.entities
    assert {row.entity_id: row.entity_version for row in existing.entities} == body[
        "published_projection"
    ]["entity_versions"]

    changed = copy.deepcopy(body)
    changed["published_projection"]["entity_versions"][existing.entities[0].entity_id] = (
        "drifted-version"
    )
    with pytest.raises(ValueError, match="published base"):
        build_existing_snapshot(
            scope=scope,
            base_body=changed,
            policy=child.request.resolution_inputs.policy,
        )

    changed = copy.deepcopy(body)
    changed["members"][0]["member_digest"] = "b" * 64
    with pytest.raises(ValueError, match="published base members"):
        build_existing_snapshot(
            scope=scope,
            base_body=changed,
            policy=child.request.resolution_inputs.policy,
        )


def test_compile_request_replays_only_current_c_and_carries_exact_parent():
    parent, request = platform_request()

    assert request.published_base is not None
    assert request.published_base.entity_bindings == parent.request.entity_bindings
    assert len(request.resolution_inputs.proposals.proposals) == 1
    assert len(request.entity_bindings) == len(parent.request.entity_bindings)
    assert request.refresh_fields
    assert request.base_request.existing_fields == parent.compile_result.output.fields
    compiler.BatchConceptCompileRequest830G3V1.model_validate(request)


def attempt(task, *, outcome, result=None, reason=None):
    return SimpleNamespace(
        entity_id=task.entity_id,
        field_key=task.field_key,
        task_sha256=task.task_sha256,
        outcome=outcome,
        validated_result=None if result is None else result.model_dump(mode="json"),
        reason=reason,
        raw_ref="raw:recorded-field-window",
    )


def test_field_projection_revalidates_success_and_maps_ordinary_failure_to_unknown():
    _, request = platform_request()
    tasks = adapt_catalog_field_tasks(request)
    assert len(tasks) == 1
    task = tasks[0]
    unknown = FieldTaskEvidenceResultV1.create(
        task=task,
        state="unknown",
        value=None,
        evidence=(),
        unknown_reason="NOT_STATED_IN_SOURCE",
        concept_ids=(),
        conditions=(),
        exceptions=(),
        valid_time="",
        source_blocks=request.base_request.sources,
    )
    projected = project_field_attempts(
        request=request,
        attempts=(attempt(task, outcome=FieldOutcomeKind.NOT_PROVIDED, result=unknown),),
        run_id="platform-field-projection",
    )
    assert projected.output.fields[0].state == "unknown"
    assert projected.output.fields[0].unknown_reason == "NOT_STATED_IN_SOURCE"
    assert projected.execution.implementation == "platform-field-artifact-projector.830.g3.v1"

    failed = project_field_attempts(
        request=request,
        attempts=(
            attempt(
                task,
                outcome=FieldOutcomeKind.EXTRACTION_FAILED,
                reason="FIELD_VALIDATION_FAILED",
            ),
        ),
        run_id="platform-field-failure",
    )
    assert failed.output.fields[0].state == "unknown"
    assert failed.output.fields[0].unknown_reason == ("EXTRACTION_FAILED:FIELD_VALIDATION_FAILED")

    with pytest.raises(ValueError, match="task"):
        project_field_attempts(
            request=request,
            attempts=(
                SimpleNamespace(
                    **{
                        **attempt(
                            task,
                            outcome=FieldOutcomeKind.NOT_PROVIDED,
                            result=unknown,
                        ).__dict__,
                        "task_sha256": "b" * 64,
                    }
                ),
            ),
            run_id="platform-field-forged",
        )


def test_candidate_uses_rule_structural_review_and_retains_parent_fields():
    parent, request = platform_request()
    task = adapt_catalog_field_tasks(request)[0]
    delta = project_field_attempts(
        request=request,
        attempts=(
            attempt(
                task,
                outcome=FieldOutcomeKind.EXTRACTION_FAILED,
                reason="MISSING_FIELD",
            ),
        ),
        run_id="platform-field-stage",
    )
    candidate = assemble_platform_candidate(request=request, delta=delta, run_id="platform-run")

    assert candidate.review_result.execution.implementation == (
        "platform-structural-evidence-review.830.g3.v1"
    )
    assert candidate.review_result.output.reasons == ("PLATFORM_STRUCTURAL_EVIDENCE_VALIDATED",)
    assert candidate.admission.status == "NEEDS_HUMAN"
    assert candidate.admission.pending_page_ids == ()
    assert len(candidate.compile_result.output.fields) == len(parent.compile_result.output.fields)
    compiler.validate_candidate_bundle(candidate)
    assert json.loads(compiler._canonical_json(candidate))["candidate_hash"] == (
        candidate.candidate_hash
    )


@lru_cache(maxsize=1)
def discovery_delta():

    from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
        AuditDisposition,
        free_page_id,
    )
    from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
        Evidence,
        FreeWikiPage,
    )

    _, request = platform_request()
    task = adapt_catalog_field_tasks(request)[0]
    delta = project_field_attempts(
        request=request,
        attempts=(
            attempt(task, outcome=FieldOutcomeKind.EXTRACTION_FAILED, reason="MISSING_FIELD"),
        ),
        run_id="discovery-field-stage",
    )
    allowed = {(row.revision_id, row.block_id) for row in task.allowed_sources}
    source = next(
        row for row in request.base_request.sources if (row.revision_id, row.block_id) in allowed
    )
    quote = source.text[:30]
    evidence = Evidence(
        **source.model_dump(exclude={"text"}),
        start=0,
        end=len(quote),
        quote=quote,
        quote_hash=hashlib.sha256(quote.encode()).hexdigest(),
    )
    page = FreeWikiPage(
        space_id=request.base_request.space_id,
        entity_id=task.entity_id,
        entity_version=task.entity_version,
        stable_key="independent-process-fixture",
        title="独立流程测试",
        body=quote,
        evidence=(evidence,),
    )
    output = delta.output.model_copy(
        update={
            "pages": (page,),
            "transformation": "SYNTHESIZE",
            "audit": (
                *delta.output.audit,
                AuditDisposition(
                    key=free_page_id(page), disposition="new_page", reason="fixture independent use"
                ),
            ),
        }
    )
    result = compiler.record_model_compile(
        request,
        output,
        run_id="discovery-projection",
        implementation="fixture-discovery-projector",
        raw=compiler._canonical_json(output),
    )
    return request, result, page


def test_new_free_page_cannot_use_field_only_rule_review():
    request, delta, _ = discovery_delta()
    with pytest.raises(ValueError, match="INDEPENDENT_DISCOVERY_REVIEW_REQUIRED"):
        assemble_platform_candidate(request=request, delta=delta, run_id="new-page-no-review")


@lru_cache(maxsize=1)
def composed_discovery_case():
    request, delta, page = discovery_delta()
    return request, delta, page, compiler.compose_batch_output(request, delta)


def independent_discovery_review(*, total=100, decision="PASS", drift=None, missing_score=False):
    request, _, page, output = composed_discovery_case()
    # Explicit review fixture inputs, never inferred from source length/confidence.
    values = [25, 20, 20, 15, 10, 10]
    reduction = 100 - total
    for index, value in enumerate(values):
        take = min(reduction, value)
        values[index] -= take
        reduction -= take
    assert reduction == 0
    score = ValueScore(
        **dict(
            zip(
                (
                    "business_value",
                    "reuse",
                    "evidence_quality",
                    "definability",
                    "novel_identity",
                    "name_stability",
                ),
                values,
                strict=True,
            )
        )
    )
    reviewed = ReviewOutput(
        request_hash=(
            "f" * 64
            if drift == "request"
            else compiler.compile_request_hash_g3(request.base_request)
        ),
        output_hash=("e" * 64 if drift == "output" else compiler.compile_output_hash_g3(output)),
        decision=decision,
        reasons=(
            "Independent fixture checked new page against original sources and existing fields.",
        ),
        page_scores={} if missing_score else {free_page_id(page): score},
    )
    raw = compiler._canonical_json(reviewed)
    context_hash = compiler._batch_sha256(
        "batch-concept-review-context.830.g3.v1", compiler.review_context_g3(request, output)
    )
    return ReviewResult(
        output=reviewed,
        execution=ExecutionRecord(
            run_id="independent-discovery-review-fixture",
            implementation="platform-independent-discovery-review.830.g3.v1",
            context_hash="d" * 64 if drift == "context" else context_hash,
            raw_output=raw,
            raw_output_hash=hashlib.sha256(raw.encode()).hexdigest(),
        ),
    )


def test_accepted_new_page_retains_exact_independent_review_and_existing_members():
    request, delta, page, composed = composed_discovery_case()
    review = independent_discovery_review()
    candidate = assemble_platform_candidate(
        request=request,
        delta=delta,
        run_id="accepted-discovery",
        independent_review=review,
    )
    assert candidate.review_result == review
    assert candidate.review_result.execution.raw_output == compiler._canonical_json(review.output)
    assert candidate.compile_result.output == composed
    assert page in candidate.compile_result.output.pages
    assert all(
        old in candidate.compile_result.output.pages for old in request.base_request.existing_pages
    )
    assert candidate.admission.status == "NEEDS_HUMAN"
    assert candidate.admission.pending_page_ids == ()
    assert candidate.review_result.output.page_scores[free_page_id(page)].total == 100
    assert (
        len(
            {
                candidate.model_compile_result.execution.run_id,
                candidate.compile_result.execution.run_id,
                candidate.review_result.execution.run_id,
            }
        )
        == 3
    )


@pytest.mark.parametrize(
    "drift,reason",
    [
        ("request", "REVIEW_NOT_APPROVED_OR_STALE"),
        ("output", "REVIEW_NOT_APPROVED_OR_STALE"),
        ("context", "EXECUTION_CONTEXT_MISMATCH"),
    ],
)
def test_new_page_rejects_stale_independent_review_binding(drift, reason):
    request, delta, _, _ = composed_discovery_case()
    review = independent_discovery_review(drift=drift)
    # These execution records have valid raw integrity; only the requested binding is stale.
    assert json.loads(review.execution.raw_output) == review.output.model_dump(mode="json")
    with pytest.raises(ValueError, match=reason):
        assemble_platform_candidate(
            request=request,
            delta=delta,
            run_id="stale-discovery-" + drift,
            independent_review=review,
        )


@pytest.mark.parametrize(
    "missing_score,total,decision,reason",
    [
        (True, 100, "PASS", "PAGE_ADMISSION_REJECTED"),
        (False, 59, "PASS", "PAGE_ADMISSION_REJECTED"),
        (False, 100, "REJECT", "REVIEW_NOT_APPROVED_OR_STALE"),
    ],
)
def test_new_page_missing_low_or_rejected_review_cannot_form_candidate(
    missing_score,
    total,
    decision,
    reason,
):
    request, delta, _, _ = composed_discovery_case()
    review = independent_discovery_review(
        total=total,
        decision=decision,
        missing_score=missing_score,
    )
    with pytest.raises(ValueError, match=reason):
        assemble_platform_candidate(
            request=request,
            delta=delta,
            run_id="unqualified-discovery",
            independent_review=review,
        )


@pytest.mark.parametrize("total", [60, 79])
def test_new_page_midrange_score_is_pending_not_automatic_ready(total):
    request, delta, page, _ = composed_discovery_case()
    review = independent_discovery_review(total=total)
    candidate = assemble_platform_candidate(
        request=request,
        delta=delta,
        run_id="pending-discovery",
        independent_review=review,
    )
    assert candidate.admission.status == "NEEDS_HUMAN"
    assert candidate.admission.pending_page_ids == (free_page_id(page),)
    assert candidate.review_result.output.page_scores[free_page_id(page)].total == total
    assert candidate.review_result == review


def test_go_published_null_collections_preserve_exact_parent_and_request_hash():
    parent, expected = platform_request()
    _, child = candidates()
    body = json.loads(
        json.dumps(base_body(parent, child), default=lambda row: row.model_dump(mode="json"))
    )
    collection_keys = {
        "definitions": ("aliases",),
        "fields": ("evidence", "concept_ids", "conditions", "exceptions"),
        "pages": ("concept_ids", "conditions", "exceptions"),
    }
    changed = 0
    for kind, keys in collection_keys.items():
        for row in body["published_projection"][kind]:
            for key in keys:
                if row[key] == []:
                    row[key] = None
                    changed += 1
    assert changed > 0
    original = copy.deepcopy(body)
    current = expected.resolution_inputs
    actual = build_platform_compile_request(
        scope=scope_for(parent),
        base_body=body,
        catalog_json=CATALOG.read_bytes(),
        profile_confirmation_json=CONFIRMATION.read_bytes(),
        corpus=current.corpus,
        proposals=current.proposals,
        policy=current.policy,
        resolution=expected.resolution,
        selected_refs=tuple(
            sorted(
                (p.material_id, c.proposal_ref)
                for p in expected.resolution.decisions
                for c in p.children
            )
        ),
        refresh_fields=tuple(
            {"entity_id": row.entity_id, "field_key": row.field_key}
            for row in expected.refresh_fields
        ),
    )
    assert body == original
    assert actual == expected
    assert actual.request_sha256 == expected.request_sha256


@pytest.mark.parametrize(
    "kind,row,model",
    [
        (
            "fields",
            {
                "value": None,
                "unknown_reason": None,
                "evidence": None,
                "concept_ids": None,
                "conditions": None,
                "exceptions": None,
            },
            "FieldAssertion",
        ),
        (
            "definitions",
            {"title": None, "body": None, "aliases": None, "evidence": None},
            "ConceptDefinition",
        ),
        (
            "pages",
            {
                "title": None,
                "body": None,
                "concept_ids": None,
                "conditions": None,
                "exceptions": None,
                "evidence": None,
            },
            "FreeWikiPage",
        ),
    ],
)
def test_null_collection_adapter_never_defaults_scalar_or_required_evidence(kind, row, model):
    from insurance_harness.knowledge_compiler import concept_free_wiki_830_g2 as contract
    from insurance_harness.product_ingestion.compilation import _published_compile_members

    original = copy.deepcopy(row)
    projected = _published_compile_members({kind: [row]}, kind)[0]
    assert row == original
    for key in ("value", "unknown_reason", "title", "body"):
        if key in row:
            assert projected[key] is None
    if kind != "fields":
        assert projected["evidence"] is None
    with pytest.raises(ValueError):
        getattr(contract, model).model_validate(projected)


def test_null_collection_adapter_rejects_wrong_collection_type_on_valid_parent_field():
    from pydantic import ValidationError

    from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import FieldAssertion
    from insurance_harness.product_ingestion.compilation import _published_compile_members

    parent, _ = candidates()
    row = parent.compile_result.output.fields[0].model_dump(mode="json")
    FieldAssertion.model_validate(row)
    row["conditions"] = "bad"
    actual = _published_compile_members({"fields": [row]}, "fields")[0]
    assert actual["conditions"] == "bad"
    with pytest.raises(ValidationError) as error:
        FieldAssertion.model_validate(actual)
    assert [(item["loc"], item["type"]) for item in error.value.errors()] == [
        (("conditions",), "tuple_type")
    ]
