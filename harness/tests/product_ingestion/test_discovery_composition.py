import hashlib
import json
from types import SimpleNamespace

import pytest

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
from insurance_harness.product_ingestion.stages import artifact, json_bytes
from tests.product_ingestion.test_compilation import (
    composed_discovery_case,
    independent_discovery_review,
)


def case():
    request, delta, page, composed = composed_discovery_case()
    free = delta.output.model_copy(
        update={
            "fields": (),
            "audit": tuple(
                row for row in delta.output.audit if row.key == compiler.free_page_id(page)
            ),
        }
    )
    fields = delta.output.model_copy(
        update={
            "pages": (),
            "definitions": (),
            "audit": tuple(
                row for row in delta.output.audit if row.key != compiler.free_page_id(page)
            ),
        }
    )
    field_delta = compiler.record_model_compile(
        request,
        fields,
        run_id="fields",
        implementation="fixture-field-projector",
        raw=compiler._canonical_json(fields),
    )
    review = independent_discovery_review().output
    context = {
        "request_hash": review.request_hash,
        "output_hash": review.output_hash,
        "review_member_ids": list(review.page_scores),
        "dispositions": [{"candidate_id": "new-page"}],
    }
    response = {
        "contract": "product-discovery-review.830.v1",
        "review": review,
        "disposition_checks": [
            {"candidate_id": "new-page", "decision": "ACCEPT", "reason": "valuable"}
        ],
    }
    context_bytes, response_bytes = json_bytes(context), json_bytes(response)
    proof = {
        "contract": "product-discovery-review-proof.830.v1",
        "decision": "ACCEPTED",
        "final_composed_output_hash": review.output_hash,
        "actual_review_context_sha256": hashlib.sha256(context_bytes).hexdigest(),
        "actual_review_raw_sha256": hashlib.sha256(response_bytes).hexdigest(),
        "model_call_id": "call-review",
        "review": review,
        "disposition_checks": [
            {"candidate_id": "new-page", "decision": "ACCEPT", "reason": "valuable"}
        ],
    }
    from insurance_harness.product_ingestion.artifact_models import ArtifactOrigin

    drafts = tuple(
        artifact(
            kind,
            "product",
            raw,
            "a" * 64,
            origin=ArtifactOrigin.MODEL
            if kind != "discovery_review_context"
            else ArtifactOrigin.RULE,
            call_id="call-review" if kind != "discovery_review_context" else None,
        )
        for kind, raw in (
            ("discovery_review_context", context_bytes),
            ("discovery_review_response", response_bytes),
            ("discovery_review_proof", json_bytes(proof)),
        )
    )
    outcome = SimpleNamespace(
        decision="ACCEPTED",
        reviewed_output=free,
        review_output=review,
        review_context_sha256=proof["actual_review_context_sha256"],
        review_raw_sha256=proof["actual_review_raw_sha256"],
        drafts=drafts,
    )
    return request, field_delta, free, composed, outcome


def test_two_stage_merge_preserves_fields_and_truthful_composite_review():
    from insurance_harness.product_ingestion.compilation import assemble_platform_candidate
    from insurance_harness.product_ingestion.discovery_composition import (
        compose_discovery_review,
        merge_discovery_delta,
    )

    request, field_delta, free, composed, outcome = case()
    delta = merge_discovery_delta(
        request=request, field_delta=field_delta, free_output=free, run_id="run"
    )
    assert delta.output.fields == field_delta.output.fields
    assert compiler.compose_batch_output(request, delta) == composed
    review = compose_discovery_review(
        request=request, final_output=composed, free_output=free, outcome=outcome, run_id="run"
    )
    assert review.execution.implementation == "platform-combined-field-discovery-review.830.g3.v1"
    assert "COMPOSITE_FIELD_AND_FREE_REVIEW" in review.output.reasons
    assert json.loads(review.execution.raw_output) == review.output.model_dump(mode="json")
    assert review.execution.context_hash != outcome.review_context_sha256
    candidate = assemble_platform_candidate(
        request=request, delta=delta, run_id="run", independent_review=review
    )
    assert candidate.compile_result.output == composed


@pytest.mark.parametrize("drift", ["hash", "raw", "partial", "decision"])
def test_composite_review_rejects_stale_or_partial_model_proof(drift):
    from insurance_harness.product_ingestion.discovery_composition import compose_discovery_review

    request, _field_delta, free, composed, outcome = case()
    if drift == "hash":
        outcome.review_context_sha256 = "f" * 64
    elif drift == "raw":
        outcome.drafts = tuple(
            row for row in outcome.drafts if row.artifact_kind != "discovery_review_response"
        )
    elif drift == "partial":
        outcome.reviewed_output = free.model_copy(update={"pages": ()})
    else:
        outcome.decision = "PENDING"
    with pytest.raises(ValueError):
        compose_discovery_review(
            request=request, final_output=composed, free_output=free, outcome=outcome, run_id="run"
        )


@pytest.mark.parametrize("fenced", [False, True])
def test_composite_accepts_auditable_parent_call_without_claiming_child_model_call(fenced):
    from insurance_harness.product_ingestion.artifact_models import ArtifactOrigin
    from insurance_harness.product_ingestion.discovery import INDEPENDENT_DISCOVERY_REVIEW_PROMPT
    from insurance_harness.product_ingestion.discovery_composition import compose_discovery_review

    request, _field_delta, free, composed, outcome = case()
    response = next(r for r in outcome.drafts if r.artifact_kind == "discovery_review_response")
    content = response.payload.decode()
    if fenced:
        content = "```json\n" + content + "\n```"
    provider_raw = json_bytes({"choices": [{"message": {"content": content}}]})
    raw_sha = hashlib.sha256(provider_raw).hexdigest()
    call = SimpleNamespace(
        run_id="parent",
        call_id="parent-call",
        stage_key="compilation",
        operation_key="independent-discovery-final-review-" + outcome.review_output.output_hash,
        state="recorded",
        input_sha256=outcome.review_context_sha256,
        prompt_policy_sha256=hashlib.sha256(INDEPENDENT_DISCOVERY_REVIEW_PROMPT).hexdigest(),
        raw=provider_raw,
        raw_sha256=raw_sha,
        diagnostic=None,
    )
    outcome.replayed_call = call
    drafts = []
    for row in outcome.drafts:
        payload = json.loads(row.payload)
        if row.artifact_kind == "discovery_review_proof":
            payload.update(
                model_call_id=call.call_id,
                replayed_from_run_id=call.run_id,
                source_call_id=call.call_id,
                source_raw_sha256=raw_sha,
            )
        drafts.append(
            artifact(
                row.artifact_kind,
                "product",
                json_bytes(payload),
                "a" * 64,
                origin=ArtifactOrigin.RULE,
            )
        )
    outcome.drafts = tuple(drafts)
    result = compose_discovery_review(
        request=request, final_output=composed, free_output=free, outcome=outcome, run_id="child"
    )
    assert result.output.output_hash == outcome.review_output.output_hash
    call.raw_sha256 = "0" * 64
    with pytest.raises(ValueError):
        compose_discovery_review(
            request=request,
            final_output=composed,
            free_output=free,
            outcome=outcome,
            run_id="child",
        )
