"""Derive local failure seeds from one exact, validated independent review."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from insurance_harness.product_ingestion.native_dependency_closure import Node
from insurance_harness.product_ingestion.stages import json_bytes

if TYPE_CHECKING:
    from insurance_harness.product_ingestion.discovery_stage import IndependentDiscoveryFinalOutcome


def validated_review_seeds(selection: dict[str, Any], receipt: dict[str, Any]) -> frozenset[Node]:
    """Verify the first review against the original closed group before pruning."""
    from insurance_harness.product_ingestion.discovery_stage import _validated_independent_review

    unsigned = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    context, response, proof = (receipt[k] for k in ("context", "response", "proof"))
    compact = {k: v for k, v in selection.items() if k != "domains"}
    if (
        receipt.get("contract") != "native-review-pruning-input.830.v1"
        or receipt.get("receipt_sha256") != hashlib.sha256(json_bytes(unsigned)).hexdigest()
        or context.get("contract") != "product-discovery-review-context.830.v10"
        or context.get("dependency_selection") != compact
        or context.get("request_hash") != selection["request_hash"]
        or context.get("entity_id") != selection["entity_id"]
        or set(context.get("review_member_ids", ())) != set(selection["retained_member_ids"])
        or proof.get("contract") != "product-discovery-review-proof.830.v1"
        or proof.get("actual_review_context_sha256")
        != hashlib.sha256(json_bytes(context)).hexdigest()
        or proof.get("actual_review_raw_sha256") != hashlib.sha256(json_bytes(response)).hexdigest()
        or proof.get("final_composed_output_hash") != context.get("output_hash")
    ):
        raise ValueError("native pruning initial review binding mismatch")
    checked, review, decision = _validated_independent_review(
        response, context=context, final_composed_output_hash=context["output_hash"]
    )
    if (
        proof.get("decision") != decision
        or proof.get("review") != review.model_dump(mode="json")
        or proof.get("disposition_checks")
        != [row.model_dump(mode="json") for row in checked.disposition_checks]
    ):
        raise ValueError("native pruning initial review proof mismatch")
    bindings = {
        row["review_candidate_id"]: row
        for row in selection["review_bindings"]
        if row["candidate_key"] in selection["retained_candidates"]
    }
    if set(bindings) != {row["candidate_id"] for row in context["dispositions"]} or any(
        row.get("member_id") != bindings[row["candidate_id"]]["member_id"]
        for row in context["dispositions"]
    ):
        raise ValueError("native pruning review ownership mismatch")
    from insurance_harness.product_ingestion.review_quality import review_qualifications

    seeds: set[Node] = {
        ("member", key)
        for key, qualification in review_qualifications(context, review.page_scores).items()
        if qualification.band != "ACCEPTED"
    }
    seeds.update(
        ("candidate", bindings[row.candidate_id]["candidate_key"])
        for row in checked.disposition_checks
        if row.decision in {"REJECT", "NEEDS_HUMAN"}
    )
    return frozenset(seeds)


def review_pruning_input(
    *, selection: dict[str, Any], outcome: IndependentDiscoveryFinalOutcome, run_id: str
) -> dict[str, Any] | None:
    """Require the normal StageCall's proof, never infer seeds from failure text."""
    from insurance_harness.product_ingestion.discovery_composition import _review_call_matches

    if outcome.decision not in {"PENDING", "REJECTED"}:
        return None
    rows = {row.artifact_kind: row for row in outcome.drafts if row.artifact_key == "product"}
    context, response, proof = (
        json.loads(rows[k].payload)
        for k in ("discovery_review_context", "discovery_review_response", "discovery_review_proof")
    )
    if not _review_call_matches(
        outcome,
        proof,
        rows["discovery_review_response"],
        rows["discovery_review_proof"],
        hashlib.sha256(json_bytes(context)).hexdigest(),
        context["output_hash"],
        run_id,
        True,
        quality_policy=context.get("quality_policy"),
    ):
        raise ValueError("native pruning review call custody mismatch")
    value = {
        "contract": "native-review-pruning-input.830.v1",
        "context": context,
        "response": response,
        "proof": proof,
    }
    receipt = {**value, "receipt_sha256": hashlib.sha256(json_bytes(value)).hexdigest()}
    return receipt if validated_review_seeds(selection, receipt) else None
