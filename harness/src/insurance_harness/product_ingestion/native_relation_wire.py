"""V4 provider wire owns its real envelope, schema and receipt; v3 remains frozen."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

from insurance_harness.product_ingestion.native_admission_contract import NATIVE_DEPENDENCY_POLICY
from insurance_harness.product_ingestion.native_admission_wire import WIRE_PROMPT, evidence_catalog
from insurance_harness.product_ingestion.native_evidence_wire import bind_evidence_refs
from insurance_harness.product_ingestion.native_relation_admission import (
    PREDICATE_MEANING,
    RELATION_CAPABILITY,
    NativeRelationResponse,
)
from insurance_harness.product_ingestion.stages import json_bytes

RELATION_WIRE_PROTOCOL = "native-knowledge-admission.830.v4"
RELATION_WIRE_PURPOSE = "g3-native-admission-v4"
RELATION_WIRE_PROMPT = (
    WIRE_PROMPT.replace(
        b"native-knowledge-admission.830.v3", b"native-knowledge-admission.830.v4"
    ).replace(b"For the v3 response", b"For the v4 response")
    + b"""
This version explicitly permits the supplied product-concept relation capability.
A relation proposal has only predicate and object_ref. The sole permitted predicate
is benefit_reduced_by_advance_payment. Its authoritative meaning is:
"""
    + PREDICATE_MEANING.encode()
    + b"""
Propose it only when original source evidence establishes that relationship. Do not
invent an attached product entity from an unnamed insurance category: supply a useful
concept definition or refer to an offered existing concept_id. For a relation page,
set stable_key to $relation and concept_refs to exactly [object_ref]. Return no subject
ID, version, target revision, final stable key or business_relation payload. The server
binds them. All relation body, conditions, exceptions and valid_time must be supported
by source evidence; generated explanations may remain in separate ordinary pages.
When updating an existing relation, keep its exact target and predicate and supply the
offered exact page revision. Other unresolved structural claims still require entity
resolution. This capability does not grant publication authority.
"""
)


def render_relation_wire_context(context: dict[str, Any]) -> dict[str, Any]:
    if (
        context.get("contract") != "native-knowledge-admission-context.830.v2"
        or context.get("dependency_policy") != NATIVE_DEPENDENCY_POLICY
        or context.get("relation_capability") != RELATION_CAPABILITY
        or context.get("response_schema") != NativeRelationResponse.model_json_schema()
    ):
        raise ValueError("native relation wire capability/context mismatch")
    evidence_catalog(context)
    value = deepcopy(context)
    value["contract"] = "native-knowledge-admission-context.830.v4"
    value["wire_protocol"] = RELATION_WIRE_PROTOCOL
    for source in value["source_options"]:
        for i, span in enumerate(source["spans"], 1):
            span["evidence_ref"] = f"{source['source_ref']}:{i}"
    schema = value["response_schema"]
    schema["title"] = "NativeAdmissionResponseV4Wire"
    schema["properties"]["contract"]["const"] = RELATION_WIRE_PROTOCOL
    for name in ("NativeDefinition", "NativeRelationPage"):
        row = schema["$defs"][name]
        del row["properties"]["evidence"]
        row["required"].remove("evidence")
    del schema["$defs"]["NativeEvidenceSelection"]
    segment = schema["$defs"]["KnowledgeContentSegment"]
    del segment["properties"]["evidence_indexes"]
    segment["required"].remove("evidence_indexes")
    segment["properties"]["evidence_refs"] = {
        "type": "array",
        "items": {"type": "string", "minLength": 1},
        "uniqueItems": True,
    }
    segment["required"].append("evidence_refs")
    # A missing proposal means ordinary page; explicit null is never accepted.
    schema["$defs"]["NativeRelationPage"]["properties"]["relation"] = {
        "$ref": "#/$defs/RelationProposal"
    }
    # Expose the exact target set accepted by the domain projector. Versions
    # remain comparison context; they are not interchangeable reference IDs.
    targets = sorted(
        {context["entity"]["entity_id"]}
        | {row["concept_id"] for row in context["existing_knowledge"]["definitions"]}
        | {row["page_id"] for row in context["existing_knowledge"]["pages"]}
    )
    decision = schema["$defs"]["NativeAdmissionDecisionV2"]
    decision["properties"]["existing_target"] = {
        "enum": [*targets, None],
        "description": "REFERENCE selects an offered entity_id, concept_id or page_id. "
        "For the current product copy entity.entity_id, never entity_version. "
        "All other decisions require null.",
    }
    decision["allOf"] = [
        {
            "if": {"properties": {"decision": {"const": "REFERENCE"}}},
            "then": {"properties": {"existing_target": {"enum": targets}}},
            "else": {"properties": {"existing_target": {"type": "null"}}},
        }
    ]
    if len(json_bytes(value)) > value["max_context_bytes"]:
        raise ValueError("native relation wire context budget exceeded")
    return value


def expand_relation_wire_response(
    value: Any, context: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    wire_context = render_relation_wire_context(context)
    catalog = evidence_catalog(context)
    original = json_bytes(value)
    expanded = deepcopy(value)
    try:
        if expanded["contract"] != RELATION_WIRE_PROTOCOL:
            raise ValueError("native relation wire contract mismatch")
        expanded["contract"] = "native-knowledge-admission.830.v2"
        bind_evidence_refs(expanded, catalog)
        NativeRelationResponse.model_validate(expanded)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("native relation wire malformed envelope") from exc
    return expanded, {
        "contract": "native-admission-wire-expansion.830.v1",
        "wire_protocol": RELATION_WIRE_PROTOCOL,
        "wire_value_sha256": hashlib.sha256(original).hexdigest(),
        "expanded_sha256": hashlib.sha256(json_bytes(expanded)).hexdigest(),
        "catalog_sha256": hashlib.sha256(json_bytes(catalog)).hexdigest(),
        "wire_context_sha256": hashlib.sha256(json_bytes(wire_context)).hexdigest(),
    }
