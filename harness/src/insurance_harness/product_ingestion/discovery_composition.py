"""Join independent discovery with fields and record an explicit composite review.

The model's real input and response remain in discovery artifacts. This adapter's
execution describes a deterministic full-candidate check, never an LLM call.
"""

from __future__ import annotations

import hashlib
import json

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
    CompileOutput,
    ExecutionRecord,
    ReviewResult,
)
from insurance_harness.product_ingestion.compilation import _derived_run_id

COMPOSITE_REVIEW = "platform-combined-field-discovery-review.830.g3.v1"


def merge_discovery_delta(*, request, field_delta, free_output, run_id):
    compiler.validate_delta_output(request, field_delta)
    free_output = CompileOutput.model_validate(free_output)
    if free_output.fields or free_output.request_hash != field_delta.output.request_hash:
        raise ValueError("independent discovery cannot change schema fields")
    if field_delta.output.pages or field_delta.output.definitions:
        raise ValueError("schema delta must not contain free discovery members")
    audit = (*field_delta.output.audit, *free_output.audit)
    if len({row.key for row in audit}) != len(audit):
        raise ValueError("duplicate field/discovery disposition")
    output = field_delta.output.model_copy(
        update={
            "pages": free_output.pages,
            "definitions": free_output.definitions,
            "audit": tuple(sorted(audit, key=lambda row: row.key)),
            "transformation": "SYNTHESIZE"
            if free_output.pages or free_output.definitions
            else field_delta.output.transformation,
        }
    )
    merged = compiler.record_model_compile(
        request,
        output,
        run_id=_derived_run_id(run_id, "field-discovery-join"),
        implementation="platform-field-discovery-projector.830.g3.v1",
        raw=compiler._canonical_json(output),
    )
    compiler.validate_delta_output(request, merged)
    return merged


def _review_call_matches(outcome, proof, response_row, proof_row, context_hash, final_hash, run_id):
    from insurance_harness.product_ingestion.artifact_models import ArtifactOrigin, StageCallState
    from insurance_harness.product_ingestion.discovery import INDEPENDENT_DISCOVERY_REVIEW_PROMPT
    from insurance_harness.product_ingestion.extraction import _json
    from insurance_harness.product_ingestion.model_execution import ConfiguredFieldTransport

    replayed = getattr(outcome, "replayed_call", None)
    if replayed is None:
        return (
            response_row.origin == proof_row.origin == ArtifactOrigin.MODEL
            and bool(response_row.origin_call_id)
            and response_row.origin_call_id
            == proof_row.origin_call_id
            == proof.get("model_call_id")
            and not proof.get("replayed_from_run_id")
        )
    if (
        response_row.origin != ArtifactOrigin.RULE
        or proof_row.origin != ArtifactOrigin.RULE
        or response_row.origin_call_id is not None
        or proof_row.origin_call_id is not None
        or replayed.run_id == run_id
        or replayed.run_id != proof.get("replayed_from_run_id")
        or replayed.call_id != proof.get("source_call_id")
        or replayed.call_id != proof.get("model_call_id")
        or replayed.stage_key != "compilation"
        or replayed.state != StageCallState.RECORDED
        or replayed.operation_key != "independent-discovery-final-review-" + final_hash
        or replayed.input_sha256 != context_hash
        or replayed.diagnostic
        or replayed.prompt_policy_sha256
        != hashlib.sha256(INDEPENDENT_DISCOVERY_REVIEW_PROMPT).hexdigest()
        or not replayed.raw
        or hashlib.sha256(replayed.raw).hexdigest() != replayed.raw_sha256
        or replayed.raw_sha256 != proof.get("source_raw_sha256")
    ):
        return False
    try:
        semantic = _json(ConfiguredFieldTransport.decode_response(replayed.raw))
        return semantic == json.loads(response_row.payload)
    except (TypeError, ValueError):
        return False


def compose_discovery_review(*, request, final_output, free_output, outcome, run_id):
    """Verify exact all-or-none proof, then attest to this adapter's real work."""
    from insurance_harness.product_ingestion.discovery import DiscoveryReview

    if (
        outcome.decision != "ACCEPTED"
        or outcome.reviewed_output != free_output
        or free_output.fields
        or outcome.review_output is None
    ):
        raise ValueError("independent discovery was not accepted as an exact group")
    rows = {row.artifact_kind: row for row in outcome.drafts if row.artifact_key == "product"}
    try:
        context_row = rows["discovery_review_context"]
        response_row = rows["discovery_review_response"]
        proof_row = rows["discovery_review_proof"]
        context = json.loads(context_row.payload)
        proof = json.loads(proof_row.payload)
        checked = DiscoveryReview.model_validate_json(response_row.payload)
    except (KeyError, ValueError) as error:
        raise ValueError("independent review proof is incomplete") from error
    context_hash = hashlib.sha256(context_row.payload).hexdigest()
    response_hash = hashlib.sha256(response_row.payload).hexdigest()
    final_hash = compiler.compile_output_hash_g3(final_output)
    request_hash = compiler.compile_request_hash_g3(request.base_request)
    review = checked.review
    member_ids = {row.concept_id for row in free_output.definitions} | {
        compiler.free_page_id(row) for row in free_output.pages
    }
    final_members = {row.concept_id: row for row in final_output.definitions} | {
        compiler.free_page_id(row): row for row in final_output.pages
    }
    expected_members = {row.concept_id: row for row in free_output.definitions} | {
        compiler.free_page_id(row): row for row in free_output.pages
    }
    checks = {row.candidate_id for row in checked.disposition_checks}
    if (
        proof.get("contract") != "product-discovery-review-proof.830.v1"
        or proof.get("decision") != "ACCEPTED"
        or proof.get("final_composed_output_hash") != final_hash
        or proof.get("actual_review_context_sha256") != context_hash
        or proof.get("actual_review_raw_sha256") != response_hash
        or outcome.review_context_sha256 != context_hash
        or outcome.review_raw_sha256 != response_hash
        or not _review_call_matches(
            outcome, proof, response_row, proof_row, context_hash, final_hash, run_id
        )
        or proof.get("review") != review.model_dump(mode="json")
        or proof.get("disposition_checks")
        != [row.model_dump(mode="json") for row in checked.disposition_checks]
        or review != outcome.review_output
        or review.decision != "PASS"
        or (review.request_hash, review.output_hash) != (request_hash, final_hash)
        or (context.get("request_hash"), context.get("output_hash")) != (request_hash, final_hash)
        or set(review.page_scores) != member_ids
        or set(context.get("review_member_ids", ())) != member_ids
        or any(score.total < 80 for score in review.page_scores.values())
        or any(final_members.get(key) != value for key, value in expected_members.items())
        or len(checks) != len(checked.disposition_checks)
        or checks != {row["candidate_id"] for row in context.get("dispositions", ())}
        or any(row.decision != "ACCEPT" for row in checked.disposition_checks)
    ):
        raise ValueError("independent discovery review proof is stale or invalid")
    combined = review.model_copy(
        update={
            "reasons": (
                *review.reasons,
                "COMPOSITE_FIELD_AND_FREE_REVIEW",
                "FREE_REVIEW_CONTEXT_SHA256:" + context_hash,
                "FREE_REVIEW_RESPONSE_SHA256:" + response_hash,
            )
        }
    )
    raw = compiler._canonical_json(combined)
    return ReviewResult(
        output=combined,
        execution=ExecutionRecord(
            run_id=_derived_run_id(run_id, "composite-review"),
            implementation=COMPOSITE_REVIEW,
            context_hash=compiler._batch_sha256(
                "batch-concept-review-context.830.g3.v1",
                compiler.review_context_g3(request, final_output),
            ),
            raw_output=raw,
            raw_output_hash=hashlib.sha256(raw.encode()).hexdigest(),
        ),
    )
