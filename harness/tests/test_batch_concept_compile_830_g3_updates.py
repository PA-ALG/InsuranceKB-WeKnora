"""Explicit replacements retain identity, old inputs and the final review fence."""

import gzip
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import pytest

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
    AuditDisposition,
    ExecutionRecord,
    ReviewResult,
    free_page_id,
)


@lru_cache(maxsize=1)
def original() -> Any:
    return compiler.validate_batch_candidate(
        (
            Path(__file__).parent / "fixtures/batch_concept_compile_830_g3/candidate.json"
        ).read_bytes()
    )


def enabled_request() -> Any:
    payload = original().request.model_dump(mode="json", exclude={"request_sha256"})
    payload["knowledge_update_policy"] = "explicit-same-identity.830.v1"
    payload["request_sha256"] = compiler._batch_sha256(original().request.contract, payload)
    return compiler.BatchConceptCompileRequest830G3V1.model_validate(payload)


def update_case(
    kind: str,
    *,
    request: Any = None,
    changes: Any = None,
    disposition: Literal["update", "new_page"] = "update",
) -> tuple[Any, Any, Any, Any]:
    bundle = original()
    request = request or enabled_request()
    collection = "pages" if kind == "page" else "definitions"
    old = getattr(request.base_request, "existing_" + collection)[0]
    revised = old.model_copy(
        update=changes if changes is not None else {"body": old.body + " 更新说明。"}
    )
    identity = free_page_id(revised) if kind == "page" else revised.concept_id
    output = bundle.model_compile_result.output.model_copy(
        update={
            "request_hash": compiler.compile_request_hash_g3(request.base_request),
            collection: (revised,),
            "audit": (
                *bundle.model_compile_result.output.audit,
                AuditDisposition(
                    key=identity, disposition=disposition, reason="SYNTHETIC_UPDATE_TEST"
                ),
            ),
        }
    )
    recorded = compiler.record_model_compile(
        request,
        output,
        run_id="synthetic-update",
        implementation="fixture-update",
        raw=compiler._canonical_json(output),
    )
    return request, recorded, old, revised


@pytest.mark.parametrize("kind", ["page", "definition"])
def test_explicit_update_replaces_one_member_without_mutating_base(kind: str) -> None:
    request, delta, old, revised = update_case(kind)
    before = compiler._canonical_json(request)
    compiler.validate_delta_output(request, delta)
    output = compiler.compose_batch_output(request, delta)
    identity = free_page_id(revised) if kind == "page" else revised.concept_id
    members = {row.concept_id: row for row in output.definitions} | {
        free_page_id(row): row for row in output.pages
    }
    assert members[identity] == revised
    assert len([row for row in output.audit if row.key == identity]) == 1
    assert next(row for row in output.audit if row.key == identity).disposition == "update"
    for row in (*request.base_request.existing_definitions, *request.base_request.existing_pages):
        key = row.concept_id if hasattr(row, "concept_id") else free_page_id(row)
        assert members[key] == (revised if key == identity else row)
    assert compiler._canonical_json(request) == before
    assert compiler.compile_output_hash_g3(output) != original().review_result.output.output_hash


@pytest.mark.parametrize("kind", ["page", "definition"])
@pytest.mark.parametrize("mode", ["undeclared", "missing", "unchanged", "duplicate"])
def test_invalid_update_is_rejected_before_composition(kind: str, mode: str) -> None:
    changes = (
        {"stable_key" if kind == "page" else "sense_key": "new-identity"}
        if mode == "missing"
        else {}
        if mode == "unchanged"
        else None
    )
    request, delta, _old, _new = update_case(
        kind, changes=changes, disposition="new_page" if mode == "undeclared" else "update"
    )
    if mode == "duplicate":
        collection = "pages" if kind == "page" else "definitions"
        output = delta.output.model_copy(update={collection: getattr(delta.output, collection) * 2})
        delta = compiler.record_model_compile(
            request,
            output,
            run_id="duplicate-update",
            implementation="fixture-update",
            raw=compiler._canonical_json(output),
        )
    with pytest.raises(compiler.BatchConceptCompileError):
        compiler.compose_batch_output(request, delta)


@pytest.mark.parametrize("origin", ["SCHEMA_DEFINITION", "EXPERT_REVISION_RECORD"])
def test_update_cannot_rewrite_protected_definition(origin: str) -> None:
    base = original().request.base_request
    protected = base.existing_definitions[0].model_copy(update={"origin": origin})
    base = base.model_copy(update={"existing_definitions": (protected,)})
    output = original().compile_result.output.model_copy(
        update={
            "request_hash": compiler.compile_request_hash_g3(base),
            "definitions": (protected.model_copy(update={"body": "invalid replacement"}),),
        }
    )
    with pytest.raises(ValueError, match="PROTECTED_DEFINITION_REPLACED"):
        compiler._validate_output_g3(base, output)


def test_update_policy_is_explicit_and_changes_compiler_identity() -> None:
    request, delta, _old, _new = update_case("page", request=original().request)
    with pytest.raises(compiler.BatchConceptCompileError, match="KNOWLEDGE_UPDATES_NOT_ENABLED"):
        compiler.validate_delta_output(request, delta)
    assert compiler.compiler_context_g3(request)["output_mode"] == "NEW_MEMBERS_ONLY"
    assert (
        compiler.compiler_context_g3(enabled_request())["output_mode"] == "NEW_AND_UPDATED_MEMBERS"
    )
    assert enabled_request().request_sha256 != request.request_sha256


@pytest.mark.parametrize("value", [None, "", "unrecognized-policy"])
def test_empty_or_unknown_update_policy_is_rejected(value: Any) -> None:
    payload = original().request.model_dump(mode="json", exclude={"request_sha256"})
    payload["knowledge_update_policy"] = value
    payload["request_sha256"] = compiler._batch_sha256(original().request.contract, payload)
    with pytest.raises(ValueError):
        compiler.BatchConceptCompileRequest830G3V1.model_validate(payload)


def build_update_bundle() -> Any:
    request, page_delta, _old, page = update_case("page")
    _request, definition_delta, _old, definition = update_case("definition")
    output = page_delta.output.model_copy(
        update={
            "definitions": definition_delta.output.definitions,
            "audit": (*page_delta.output.audit, definition_delta.output.audit[-1]),
        }
    )
    delta = compiler.record_model_compile(
        request,
        output,
        run_id="synthetic-update",
        implementation="fixture-update",
        raw=compiler._canonical_json(output),
    )
    final = compiler.compose_batch_output(request, delta)
    composed = compiler.record_composed_output(
        request, delta, final, run_id="synthetic-composition"
    )
    review_data = original().review_result.output.model_dump(mode="json")
    score = dict(
        business_value=25,
        reuse=20,
        evidence_quality=20,
        definability=15,
        novel_identity=10,
        name_stability=10,
    )
    review_data.update(
        output_hash=compiler.compile_output_hash_g3(final),
        reasons=["SYNTHETIC_PROTOCOL_FIXTURE_NOT_MODEL_REVIEW"],
        page_scores={free_page_id(page): score, definition.concept_id: score},
    )
    review_output = type(original().review_result.output).model_validate(review_data)
    raw = compiler._canonical_json(review_output)
    review = ReviewResult(
        output=review_output,
        execution=ExecutionRecord(
            run_id="synthetic-independent-review",
            implementation="fixture-update-review",
            context_hash=compiler._batch_sha256(
                "batch-concept-review-context.830.g3.v1", compiler.review_context_g3(request, final)
            ),
            raw_output=raw,
            raw_output_hash=hashlib.sha256(raw.encode()).hexdigest(),
        ),
    )
    return compiler.assemble_candidate_bundle(
        request, delta, composed, review, original().admission
    )


def test_full_update_candidate_matches_cross_language_vector_and_rejects_stale_review() -> None:
    bundle = build_update_bundle()
    fixture = (
        Path(__file__).parent
        / "fixtures/batch_concept_compile_830_g3/knowledge-updates-candidate.json.gz"
    )
    raw = gzip.decompress(fixture.read_bytes())
    assert compiler._canonical_json(bundle).encode() == raw
    assert compiler.validate_batch_candidate(raw) == bundle
    with pytest.raises(compiler.BatchConceptCompileError):
        compiler.validate_candidate_bundle(
            bundle.model_copy(update={"review_result": original().review_result})
        )


def test_real_model_display_respects_update_policy_and_legacy_omission() -> None:
    from insurance_harness.knowledge_compiler import g3_bounded_model_execution as bounded

    for request in (original().request, enabled_request()):
        _sources, _by_ref, source_keys = bounded._g3_d_source_index(request)
        context = bounded._g3_d_display_context(request, source_keys)
        assert context["output_mode"] == compiler.compiler_context_g3(request)["output_mode"]
        semantic = context["semantic_request"]
        assert isinstance(semantic, dict)
        assert ("knowledge_update_policy" in semantic) == bool(request.knowledge_update_policy)


@pytest.mark.parametrize("mode", ["missing", "low", "pending"])
def test_fully_rehashed_candidate_cannot_bypass_update_scores(mode: str) -> None:
    bundle = build_update_bundle()
    data = bundle.review_result.output.model_dump(mode="json")
    identity = next(iter(data["page_scores"]))
    if mode == "missing":
        data["page_scores"] = {}
    else:
        data["page_scores"][identity]["business_value"] = 0
        if mode == "low":
            data["page_scores"][identity]["reuse"] = 0
    reviewed = type(bundle.review_result.output).model_validate(data)
    raw = compiler._canonical_json(reviewed)
    review = bundle.review_result.model_copy(
        update={
            "output": reviewed,
            "execution": bundle.review_result.execution.model_copy(
                update={
                    "raw_output": raw,
                    "raw_output_hash": hashlib.sha256(raw.encode()).hexdigest(),
                }
            ),
        }
    )
    with pytest.raises(ValueError, match="ADMISSION"):
        compiler.assemble_candidate_bundle(
            bundle.request,
            bundle.model_compile_result,
            bundle.compile_result,
            review,
            bundle.admission,
        )
