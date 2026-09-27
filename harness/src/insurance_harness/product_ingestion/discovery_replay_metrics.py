"""Verify durable discovery replay custody before accounting for reused calls."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, TypeGuard

from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.product_ingestion.artifact_models import (
    ArtifactOrigin,
    StageCallState,
)
from insurance_harness.product_ingestion.artifact_tables import (
    ProductArtifact,
    ProductStageModelCall,
)
from insurance_harness.product_ingestion.discovery import (
    DEPENDENCY_DISCOVERY_REVIEW_PROMPT,
    INDEPENDENT_DISCOVERY_PROMPT,
    INDEPENDENT_DISCOVERY_REVIEW_PROMPT,
    PROVENANCE_DISCOVERY_REVIEW_PROMPT,
)
from insurance_harness.product_ingestion.models import ProductScope
from insurance_harness.product_ingestion.native_admission_contract import (
    native_admission_prompt,
)
from insurance_harness.product_ingestion.native_admission_wire import (
    WIRE_PROMPT,
    WIRE_PROTOCOL,
)
from insurance_harness.product_ingestion.native_discovery import (
    NATIVE_DISCOVERY_EXECUTION_PROMPT,
)

if TYPE_CHECKING:
    from insurance_harness.product_ingestion.store import ProductIngestionStore


def verified_discovery_replay_calls(
    session: Session,
    products: ProductIngestionStore,
    scope: ProductScope,
    run_id: str,
) -> dict[str, ProductStageModelCall]:
    """Return distinct recorded ancestor calls supported by exact child rule records."""
    markers = session.scalars(
        select(ProductArtifact).where(
            ProductArtifact.run_id == run_id,
            ProductArtifact.space_id == scope.space_id,
            ProductArtifact.artifact_kind.in_(
                (
                    "discovery_window_replay_receipt",
                    "discovery_review_proof",
                    "native_discovery_execution",
                    "native_admission_execution",
                )
            ),
        )
    ).all()
    if not markers:
        return {}
    child = products._run(session, scope, run_id)
    ancestors: set[str] = set()
    visited = {run_id}
    ancestor_id = child.retry_of_run_id
    while ancestor_id:
        if ancestor_id in visited:
            raise ValueError("discovery replay ancestry cycle")
        visited.add(ancestor_id)
        ancestor = products._run(session, scope, ancestor_id)
        ancestors.add(ancestor.id)
        ancestor_id = ancestor.retry_of_run_id
    calls: dict[str, ProductStageModelCall] = {}
    for marker in markers:
        admission_v2 = False
        if marker.artifact_kind in {
            "native_discovery_execution",
            "native_admission_execution",
        }:
            _verify_replay_marker(marker, stage_key="discovery")
            proof = _object(marker.payload)
            source_run = proof.get("replayed_from_run_id")
            if source_run is None:
                continue
            admission = marker.artifact_kind == "native_admission_execution"
            prefix = "native-admission" if admission else "native-discovery"
            admission_v2 = (
                admission and proof.get("contract") == "native-admission-execution-receipt.830.v2"
            )
            if not admission_v2 and proof.get("contract") != prefix + "-execution-receipt.830.v1":
                raise ValueError("native replay receipt contract changed")
            input_sha = proof.get("input_sha256")
            if not _hash(input_sha) or proof.get("operation_key") != prefix + "-" + input_sha:
                raise ValueError("native replay operation/input changed")
            operation = prefix + "-" + input_sha
            native_context_row = _matching_child_artifact(
                session,
                scope,
                run_id,
                "native_admission_context" if admission else "native_discovery_context",
                marker.artifact_key,
                input_sha,
            )
            from insurance_harness.product_ingestion.native_relation_wire import (
                RELATION_WIRE_PROMPT,
                RELATION_WIRE_PROTOCOL,
            )

            prompt_sha = hashlib.sha256(
                RELATION_WIRE_PROMPT
                if admission_v2
                and _object(native_context_row.payload).get("wire_protocol")
                == RELATION_WIRE_PROTOCOL
                else WIRE_PROMPT
                if admission_v2
                and _object(native_context_row.payload).get("wire_protocol") == WIRE_PROTOCOL
                else native_admission_prompt(
                    _object(native_context_row.payload).get("dependency_policy")
                )
                if admission
                else NATIVE_DISCOVERY_EXECUTION_PROMPT
            ).hexdigest()
            call_id = proof.get("model_call_id")
            raw_sha = proof.get("raw_sha256")
        elif marker.artifact_kind == "discovery_review_proof":
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
            call_id = proof.get("source_call_id")
            if proof.get("model_call_id") != call_id:
                raise ValueError("discovery replay review call identity changed")
            context_row = _matching_child_artifact(
                session,
                scope,
                run_id,
                "discovery_review_context",
                marker.artifact_key,
                input_sha,
            )
            context = _object(context_row.payload)
            version = context.get("contract")
            refined = bool(version == "product-discovery-review-context.830.v10"
                and context.get("dependency_selection", {}).get("initial_review_sha256"))
            if marker.artifact_key != "product" and (
                version != "product-discovery-review-context.830.v10"
                or refined or marker.artifact_key != "initial:" + output_hash
            ):
                raise ValueError("discovery replay review artifact key changed")
            if refined:
                from insurance_harness.product_ingestion.discovery_stage import (
                    independent_review_operation_key,
                )

                operation = independent_review_operation_key(
                    output_hash, context_row.payload_sha256, refined=True
                )
                if proof.get("operation_key") != operation:
                    raise ValueError("discovery replay refined operation changed")
            if version not in {
                None,
                "product-discovery-review-context.830.v3",
                "product-discovery-review-context.830.v4",
                "product-discovery-review-context.830.v5",
                "product-discovery-review-context.830.v6",
                "product-discovery-review-context.830.v9",
                "product-discovery-review-context.830.v10",
            }:
                raise ValueError("discovery replay review context contract changed")
            from insurance_harness.product_ingestion.relation_review import RELATION_REVIEW_PROMPT

            prompt = (
                RELATION_REVIEW_PROMPT
                if version == "product-discovery-review-context.830.v9"
                else DEPENDENCY_DISCOVERY_REVIEW_PROMPT
                if version in {
                    "product-discovery-review-context.830.v6",
                    "product-discovery-review-context.830.v10",
                }
                else PROVENANCE_DISCOVERY_REVIEW_PROMPT
                if version == "product-discovery-review-context.830.v5"
                else INDEPENDENT_DISCOVERY_REVIEW_PROMPT
            )
            prompt_sha = hashlib.sha256(prompt).hexdigest()
            _matching_child_artifact(
                session,
                scope,
                run_id,
                "discovery_review_response",
                marker.artifact_key,
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
            source_operation = receipt.get("source_operation_key")
            if not isinstance(source_operation, str) or not source_operation.startswith(
                "independent-discovery-window-"
            ):
                raise ValueError("discovery replay window operation changed")
            operation = source_operation
            input_sha = receipt.get("source_input_sha256")
            prompt_sha = hashlib.sha256(INDEPENDENT_DISCOVERY_PROMPT).hexdigest()
            if receipt.get("source_prompt_sha256") != prompt_sha:
                raise ValueError("discovery replay window prompt changed")
            _matching_child_artifact(
                session,
                scope,
                run_id,
                "discovery_context",
                marker.artifact_key,
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
        if admission_v2:
            _verify_admission_v2_custody(proof, native_context_row.payload, call, prompt_sha)
        calls[call_id] = call
    return calls


def _verify_admission_v2_custody(
    proof: dict[str, Any], content: bytes, call: ProductStageModelCall, prompt_sha: str
) -> None:
    """Read historical accounting evidence; do not authorize replay or publication."""
    from insurance_harness.product_ingestion.native_relation_wire import RELATION_WIRE_PROTOCOL

    protocol = _object(content).get("wire_protocol")
    if (
        protocol not in (None, WIRE_PROTOCOL, RELATION_WIRE_PROTOCOL)
        or proof.get("wire_protocol") != protocol
        or proof.get("prompt_sha256") != prompt_sha
        or proof.get("model_policy_sha256") != call.model_policy_sha256
        or not isinstance(proof.get("template_id"), str)
        or not proof["template_id"]
        or not call.request_bytes
        or proof.get("request_sha256") != call.request_sha256
        or hashlib.sha256(call.request_bytes).hexdigest() != call.request_sha256
    ):
        raise ValueError("native admission replay policy/request changed")
    messages = _object(call.request_bytes).get("messages")
    if (
        not isinstance(messages, list)
        or len(messages) != 2
        or not isinstance(messages[0], dict)
        or messages[0].get("role") != "system"
        or not isinstance(messages[0].get("content"), str)
        or hashlib.sha256(messages[0]["content"].encode()).hexdigest() != prompt_sha
        or messages[1] != {"role": "user", "content": content.decode()}
    ):
        raise ValueError("native admission replay request content changed")


def _object(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("discovery replay payload is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("discovery replay payload must be an object")
    return value


def _hash(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _verify_payload(row: ProductArtifact) -> None:
    if hashlib.sha256(row.payload).hexdigest() != row.payload_sha256:
        raise ValueError("discovery replay artifact bytes changed")


def _verify_replay_marker(marker: ProductArtifact, *, stage_key: str) -> None:
    if (
        marker.stage_key != stage_key
        or marker.origin != ArtifactOrigin.RULE.value
        or marker.origin_call_id is not None
    ):
        raise ValueError("discovery replay child custody changed")
    _verify_payload(marker)


def _matching_child_artifact(
    session: Session,
    scope: ProductScope,
    run_id: str,
    kind: str,
    key: str,
    digest: object,
) -> ProductArtifact:
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
        row is None
        or row.origin != ArtifactOrigin.RULE.value
        or row.origin_call_id is not None
        or row.payload_sha256 != digest
    ):
        raise ValueError("discovery replay child artifact binding changed")
    _verify_payload(row)
    return row
