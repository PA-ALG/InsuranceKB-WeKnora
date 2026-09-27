from pathlib import Path

import pytest

from insurance_harness.knowledge_compiler import g3_bounded_model_execution as runtime
from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import batch_json_bytes_830_g3
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCandidateBundle830G3V1,
    aligned_existing_fields,
    validate_batch_candidate,
)
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import free_page_id
from insurance_harness.model_policy import ModelIdentity
from insurance_harness.run_admission.g3_models import canonical_json


@pytest.fixture(scope="module")
def candidate() -> BatchConceptCandidateBundle830G3V1:
    return validate_batch_candidate(
        (
            Path(__file__).parent / "fixtures/batch_concept_compile_830_g3/candidate.json"
        ).read_bytes()
    )


def identity() -> ModelIdentity:
    return ModelIdentity(
        provider="g3-user-gateway",
        family="gemini",
        deployment_id="gemini-3.7-flash-medium",
        role="verify",
        policy_version="g3-user-gemini-gateway-v1",
    )


def test_review_windows_cover_novel_members_once_and_bound_exact_source(
    candidate: BatchConceptCandidateBundle830G3V1,
) -> None:
    request, output = candidate.request, candidate.compile_result.output
    windows = runtime.derive_gemini_d_review_windows(request, output)
    old = {(field.entity_id, field.field_key): field for field in aligned_existing_fields(request)}
    expected = {
        (field.entity_id, field.field_key)
        for field in output.fields
        if old.get((field.entity_id, field.field_key)) != field
    }
    actual = [(w["entity_id"], key) for w in windows for key in w["field_keys"]]
    assert set(actual) == expected and len(actual) == len(expected)
    refs = [ref for w in windows for ref in w["review_refs"]]
    assert set(refs) == {r["review_ref"] for r in runtime._g3_d_review_targets(request, output)}
    assert len(refs) == len(set(refs))
    for window in windows:
        assert len(window["field_keys"]) <= 10
        assert bool(window["field_keys"]) != bool(window["review_refs"])
        context = runtime.render_gemini_d_review_window_context(identity(), request, output, window)
        assert len(batch_json_bytes_830_g3(context)) <= 262144
        assert (
            sum(len(s["quote"]) for row in context["source_options"] for s in row["spans"]) <= 24000
        )
        assert all("text" not in row["source"] for row in context["source_options"])
        offered = {row["source_ref"]: row["spans"] for row in context["source_options"]}
        partition = context["candidate_partition"]
        for row in (
            *partition["fields"],
            *partition["pages"],
            *partition["owned_novel_definitions"],
        ):
            for evidence in row["evidence"]:
                assert "quote" not in evidence
                assert any(
                    s["start"] <= evidence["start"] and evidence["end"] <= s["end"]
                    for s in offered[evidence["source_ref"]]
                )


def test_field_only_review_requires_its_own_call_and_reject_propagates(
    candidate: BatchConceptCandidateBundle830G3V1,
) -> None:
    request, output = candidate.request, candidate.compile_result.output
    windows = runtime.derive_gemini_d_review_windows(request, output)
    reviews = []
    rejected = False
    for w in windows:
        field_reject = bool(w["field_keys"]) and not rejected
        rejected = rejected or field_reject
        raw = canonical_json(
            {
                "contract": "g3-d-review-semantic-references.local.v1",
                "decision": "REJECT" if field_reject else "PASS",
                "reasons": ["field evidence unsupported"] if field_reject else [],
                "scores": [
                    dict(
                        review_ref=ref,
                        business_value=20,
                        reuse=20,
                        evidence_quality=20,
                        definability=15,
                        novel_identity=10,
                        name_stability=10,
                    )
                    for ref in w["review_refs"]
                ],
            }
        )
        reviews.append(runtime.project_gemini_d_review_window_response(raw, request, output, w))
        if field_reject:
            assert reviews[-1].page_scores == {}
    assert (
        runtime.aggregate_gemini_d_review_window_outputs(request, output, reviews).decision
        == "REJECT"
    )
    with pytest.raises(ValueError, match="count"):
        runtime.aggregate_gemini_d_review_window_outputs(request, output, reviews[1:])
    with pytest.raises(ValueError, match="foreign"):
        runtime.render_gemini_d_review_window_context(
            identity(), request, output, {**windows[0], "field_keys": ()}
        )


def test_changed_carry_content_is_reviewed_and_unchanged_pages_are_not_novel(
    candidate: BatchConceptCandidateBundle830G3V1,
) -> None:
    request, output = candidate.request, candidate.compile_result.output
    carried = aligned_existing_fields(request)
    key = (carried[0].entity_id, carried[0].field_key)
    changed = carried[0].model_copy(update={"valid_time": "changed effective version"})
    changed_output = output.model_copy(
        update={
            "fields": tuple(
                changed if (f.entity_id, f.field_key) == key else f for f in output.fields
            )
        }
    )
    fields = runtime._g3_review_scope(request, changed_output)["fields"]
    assert key in fields
    assert key in runtime._g3_review_scope(request, changed_output)["tasks"]
    page = output.pages[0]
    shadow = request.model_copy(
        update={"base_request": request.base_request.model_copy(update={"existing_pages": (page,)})}
    )
    assert free_page_id(page) not in runtime._g3_novel_page_ids(shadow, output)
    edited = page.model_copy(update={"body": page.body + " revised"})
    changed_pages = output.model_copy(update={"pages": (edited,)})
    assert free_page_id(edited) in runtime._g3_novel_page_ids(shadow, changed_pages)
