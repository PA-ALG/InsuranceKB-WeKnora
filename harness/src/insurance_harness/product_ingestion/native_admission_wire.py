"""Refs-only provider boundary; source bytes and the v2 domain stay server-owned.

No inference, normalization, I/O or publication. A catalog ref selects one existing
offered span. Segment origin/text remain exactly as declared by the provider.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

from insurance_harness.product_ingestion.native_admission_contract import (
    NATIVE_ADMISSION_DEPENDENCY_PROMPT,
    NATIVE_DEPENDENCY_POLICY,
    NativeAdmissionResponseV2,
)
from insurance_harness.product_ingestion.native_evidence_wire import bind_evidence_refs
from insurance_harness.product_ingestion.stages import json_bytes

WIRE_PROTOCOL = "native-knowledge-admission.830.v3"
WIRE_PURPOSE = "g3-native-admission-v3"
WIRE_PROMPT = (
    NATIVE_ADMISSION_DEPENDENCY_PROMPT.replace(
        b"SOURCE_SUPPORTED segments refer to exact\n"
        b"evidence indexes. Evidence uses only an offered source_ref, "
        b"Unicode start and exact quote.\n"
        b"MODEL_GENERATED segments have empty evidence indexes.",
        b"SOURCE_SUPPORTED segments select offered evidence_refs. The server binds exact original\n"
        b"quotes and offsets; do not return evidence, evidence_indexes, start or quote.\n"
        b"MODEL_GENERATED segments have empty evidence_refs.",
    ).replace(b"For the v2 response", b"For the v3 response")
    + b"""
Use native-knowledge-admission.830.v3. Each content_provenance segment returns
text, origin and evidence_refs, in catalog order without duplicates. A paraphrase
of the source is SOURCE_SUPPORTED, not MODEL_GENERATED. Keep additional explanation
in a separate MODEL_GENERATED segment; never invent product-specific facts.
Before rejecting a candidate as Schema-covered, compare its subject, recipient,
trigger, condition, exception and consequence. A field covering a suspension
trigger does not cover the insurer's responsibility during suspension. Preserve
the subjects of disclosure inquiries, not merely the general duty to answer.
These instructions do not replace independent review of semantic correctness.
"""
)


def evidence_catalog(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    identities: set[tuple[str, int, str]] = set()
    for source in context["source_options"]:
        for i, span in enumerate(source["spans"], 1):
            ref = f"{source['source_ref']}:{i}"
            identity = (source["source_ref"], span["start"], span["quote"])
            if ref in catalog or identity in identities:
                raise ValueError("native admission ambiguous evidence catalog")
            identities.add(identity)
            catalog[ref] = dict(zip(("source_ref", "start", "quote"), identity, strict=True))
    return catalog


def render_wire_context(context: dict[str, Any]) -> dict[str, Any]:
    """Adapt an already verified v2 context without repeating the source text."""
    if (
        context.get("contract") != "native-knowledge-admission-context.830.v2"
        or context.get("dependency_policy") != NATIVE_DEPENDENCY_POLICY
    ):
        raise ValueError("native admission wire requires v2 dependency context")
    evidence_catalog(context)
    value = deepcopy(context)
    value["contract"] = "native-knowledge-admission-context.830.v3"
    value["wire_protocol"] = WIRE_PROTOCOL
    for source in value["source_options"]:
        for i, span in enumerate(source["spans"], 1):
            span["evidence_ref"] = f"{source['source_ref']}:{i}"
    schema = value["response_schema"]
    schema["title"] = "NativeAdmissionResponseV3Wire"
    schema["properties"]["contract"]["const"] = WIRE_PROTOCOL
    for name in ("NativeDefinition", "NativePage"):
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
    if len(json_bytes(value)) > value["max_context_bytes"]:
        raise ValueError("native admission wire context budget exceeded")
    return value


def expand_wire_response(
    value: Any, context: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Expand refs in catalog order, then validate the existing strict v2 shape."""
    catalog = evidence_catalog(context)
    wire_context = render_wire_context(context)
    original = json_bytes(value)
    expanded = deepcopy(value)
    try:
        if expanded["contract"] != WIRE_PROTOCOL:
            raise ValueError("native admission wire contract mismatch")
        expanded["contract"] = "native-knowledge-admission.830.v2"
        bind_evidence_refs(expanded, catalog)
        NativeAdmissionResponseV2.model_validate(expanded)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("native admission wire malformed envelope") from exc
    return expanded, {
        "contract": "native-admission-wire-expansion.830.v1",
        "wire_protocol": WIRE_PROTOCOL,
        "wire_value_sha256": hashlib.sha256(original).hexdigest(),
        "expanded_sha256": hashlib.sha256(json_bytes(expanded)).hexdigest(),
        "catalog_sha256": hashlib.sha256(json_bytes(catalog)).hexdigest(),
        "wire_context_sha256": hashlib.sha256(json_bytes(wire_context)).hexdigest(),
    }
