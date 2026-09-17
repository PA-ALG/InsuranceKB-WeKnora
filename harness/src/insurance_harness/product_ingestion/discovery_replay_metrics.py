"""Verify durable discovery replay custody before accounting for reused calls."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select

from insurance_harness.product_ingestion.artifact_models import ArtifactOrigin, StageCallState
from insurance_harness.product_ingestion.artifact_tables import (
    ProductArtifact,
    ProductStageModelCall,
)
from insurance_harness.product_ingestion.discovery import (
    INDEPENDENT_DISCOVERY_PROMPT,
    INDEPENDENT_DISCOVERY_REVIEW_PROMPT,
)


def verified_discovery_replay_calls(session, products, scope, run_id):
    """Return distinct recorded ancestor calls supported by exact child rule records."""
    markers = session.scalars(
        select(ProductArtifact).where(
            ProductArtifact.run_id == run_id,
            ProductArtifact.space_id == scope.space_id,
            ProductArtifact.artifact_kind.in_((
                "discovery_window_replay_receipt", "discovery_review_proof",
            )),
        )
    ).all()
    if not markers:
        return {}
    child = products._run(session, scope, run_id)
    ancestors = set()
    visited = {run_id}
    ancestor_id = child.retry_of_run_id
    while ancestor_id:
        if ancestor_id in visited:
            raise ValueError("discovery replay ancestry cycle")
        visited.add(ancestor_id)
        ancestor = products._run(session, scope, ancestor_id)
        ancestors.add(ancestor.id)
        ancestor_id = ancestor.retry_of_run_id
    calls = {}
    for marker in markers:
        if marker.artifact_kind == "discovery_review_proof":
            _verify_payload(marker)
            proof = _object(marker.payload)
            if proof.get("replayed_from_run_id") is None:
                continue
            _verify_replay_marker(marker, stage_key="compilation")
            if proof.get("contract") != "product-discovery-review-proof.830.v1":
                raise ValueError("discovery replay review proof contract changed")
            output_hash = proof.get("final_composed_output_hash")
            if not _hash(output_hash):
                raise ValueError("discovery replay final output hash missing")
            operation = "independent-discovery-final-review-" + output_hash
            input_sha = proof.get("actual_review_context_sha256")
            prompt_sha = hashlib.sha256(INDEPENDENT_DISCOVERY_REVIEW_PROMPT).hexdigest()
            call_id = proof.get("source_call_id")
            if proof.get("model_call_id") != call_id:
                raise ValueError("discovery replay review call identity changed")
            _matching_child_artifact(
                session, scope, run_id, "discovery_review_context", "product", input_sha,
            )
            _matching_child_artifact(
                session, scope, run_id, "discovery_review_response", "product",
                proof.get("actual_review_raw_sha256"),
            )
            source_run = proof.get("replayed_from_run_id")
            raw_sha = proof.get("source_raw_sha256")
        else:
            _verify_replay_marker(marker, stage_key="discovery")
            receipt = _object(marker.payload)
            if receipt.get("contract") != "product-discovery-window-replay-receipt.830.v1":
                raise ValueError("discovery replay window receipt contract changed")
            if receipt.get("source_stage_key") != "discovery":
                raise ValueError("discovery replay window stage changed")
            operation = receipt.get("source_operation_key")
            if not isinstance(operation, str) or not operation.startswith(
                "independent-discovery-window-"
            ):
                raise ValueError("discovery replay window operation changed")
            input_sha = receipt.get("source_input_sha256")
            prompt_sha = hashlib.sha256(INDEPENDENT_DISCOVERY_PROMPT).hexdigest()
            if receipt.get("source_prompt_sha256") != prompt_sha:
                raise ValueError("discovery replay window prompt changed")
            _matching_child_artifact(
                session, scope, run_id, "discovery_context", marker.artifact_key,
                input_sha,
            )
            call_id = receipt.get("source_call_id")
            source_run = receipt.get("replayed_from_run_id")
            raw_sha = receipt.get("source_raw_sha256")
        if source_run not in ancestors or not isinstance(call_id, str):
            raise ValueError("discovery replay source is not an ancestor call")
        call = session.scalar(
            select(ProductStageModelCall).where(
                ProductStageModelCall.space_id == scope.space_id,
                ProductStageModelCall.call_id == call_id,
            )
        )
        if (
            call is None
            or call.run_id != source_run
            or call.stage_key != marker.stage_key
            or call.operation_key != operation
            or call.input_sha256 != input_sha
            or call.prompt_policy_sha256 != prompt_sha
            or call.state != StageCallState.RECORDED.value
            or call.dispatched_at is None
            or call.diagnostic
            or not call.raw
            or call.raw_sha256 != raw_sha
            or hashlib.sha256(call.raw).hexdigest() != raw_sha
        ):
            raise ValueError("discovery replay parent call provenance changed")
        calls[call_id] = call
    return calls


def _object(payload):
    try:
        value = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("discovery replay payload is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("discovery replay payload must be an object")
    return value


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value
    )


def _verify_payload(row):
    if hashlib.sha256(row.payload).hexdigest() != row.payload_sha256:
        raise ValueError("discovery replay artifact bytes changed")


def _verify_replay_marker(marker, *, stage_key):
    if (
        marker.stage_key != stage_key
        or marker.origin != ArtifactOrigin.RULE.value
        or marker.origin_call_id is not None
    ):
        raise ValueError("discovery replay child custody changed")
    _verify_payload(marker)


def _matching_child_artifact(session, scope, run_id, kind, key, digest):
    if not _hash(digest):
        raise ValueError("discovery replay child artifact hash missing")
    row = session.scalar(
        select(ProductArtifact).where(
            ProductArtifact.run_id == run_id,
            ProductArtifact.space_id == scope.space_id,
            ProductArtifact.artifact_kind == kind,
            ProductArtifact.artifact_key == key,
        )
    )
    if (
        row is None or row.origin != ArtifactOrigin.RULE.value
        or row.origin_call_id is not None or row.payload_sha256 != digest
    ):
        raise ValueError("discovery replay child artifact binding changed")
    _verify_payload(row)
