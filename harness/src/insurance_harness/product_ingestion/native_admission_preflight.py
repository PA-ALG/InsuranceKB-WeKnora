"""Deterministic wire binding before strict admission, with immutable raw custody.

No I/O or semantic repair: only unique exact quote locations and unambiguous
reference namespaces may be bound. All domain invariants still belong to the
strict projector; a rejected response never yields a partial projection.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCompileRequest830G3V1,
)
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import FieldAssertion
from insurance_harness.knowledge_compiler.evidence_occurrences import exact_quote_occurrences
from insurance_harness.product_ingestion.extraction import decode_model_json
from insurance_harness.product_ingestion.native_admission import (
    NativeAdmissionProjection,
    project_native_admission_response,
)
from insurance_harness.product_ingestion.native_admission_context import (
    render_native_admission_context,
)
from insurance_harness.product_ingestion.native_admission_contract import (
    NATIVE_DEPENDENCY_POLICY,
    NativeAdmissionResponseV2,
)
from insurance_harness.product_ingestion.native_discovery import NativeDiscoverySnapshot
from insurance_harness.product_ingestion.platform import DecodedSourceSnapshot
from insurance_harness.product_ingestion.stages import json_bytes


@dataclass(frozen=True, slots=True)
class NativeAdmissionPreflight:
    projection: NativeAdmissionProjection | None
    canonical: bytes
    receipt: dict[str, Any]
    failure: str | None


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bind_v2(value: dict[str, Any], context: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    NativeAdmissionResponseV2.model_validate(value)
    sources = {row["source_ref"]: row["spans"] for row in context["source_options"]}
    for kind in ("definitions", "pages"):
        for i, row in enumerate(value[kind]):
            for j, evidence in enumerate(row["evidence"]):
                spans = sources.get(evidence["source_ref"])
                if spans is None:
                    raise ValueError("native admission foreign evidence source")
                old, quote = evidence["start"], evidence["quote"]
                matches = sorted(
                    {
                        span["start"] + start
                        for span in spans
                        for start in exact_quote_occurrences(
                            span["quote"], quote, ((0, len(span["quote"])),)
                        )
                    }
                )
                # An exact offered offset disambiguates repeated quotations.
                if old in matches:
                    continue
                if len(matches) != 1:
                    raise ValueError("native admission quote binding must occur exactly once")
                evidence["start"] = matches[0]
                changes.append(
                    {
                        "path": f"/{kind}/{i}/evidence/{j}/start",
                        "old": old,
                        "new": matches[0],
                        "reason": "unique_exact_quote",
                        "source_ref": evidence["source_ref"],
                        "quote_sha256": _digest(quote.encode()),
                        "occurrence_count": 1,
                    }
                )
    old_ids = {row["concept_id"] for row in context["existing_knowledge"]["definitions"]}
    member_refs = {row["member_ref"] for kind in ("definitions", "pages") for row in value[kind]}
    valid_refs = old_ids | {row["member_ref"] for row in value["definitions"]}
    keys: dict[str, list[str]] = {}
    for row in value["definitions"]:
        keys.setdefault(row["canonical_key"], []).append(row["member_ref"])
    for i, page in enumerate(value["pages"]):
        for j, ref in enumerate(page["concept_refs"]):
            if ref in valid_refs:
                continue
            matches = keys.get(ref, [])
            if ref in member_refs or len(matches) != 1:
                raise ValueError("native admission ambiguous or foreign concept reference")
            page["concept_refs"][j] = matches[0]
            changes.append(
                {
                    "path": f"/pages/{i}/concept_refs/{j}",
                    "old": ref,
                    "new": matches[0],
                    "reason": "unique_exact_canonical_key",
                    "occurrence_count": 1,
                }
            )


def preflight_native_admission_response(
    *,
    raw: bytes,
    request: BatchConceptCompileRequest830G3V1,
    entity_id: str,
    snapshot: NativeDiscoverySnapshot,
    source: DecodedSourceSnapshot,
    context: dict[str, Any],
    wire_protocol: str | None = None,
    effective_fields: tuple[FieldAssertion, ...] | None = None,
) -> NativeAdmissionPreflight:
    """Return a full strict projection or a rejection, retaining the binding audit."""
    changes: list[dict[str, Any]] = []
    canonical = raw
    value: dict[str, Any] | None = None
    projection = None
    failure = None
    phase = "context"
    expansion = None
    try:
        expected = render_native_admission_context(
            request=request,
            entity_id=entity_id,
            snapshot=snapshot,
            source=source,
            max_context_bytes=context["max_context_bytes"],
            dependency_policy=context.get("dependency_policy"),
            isolation_enabled=context.get("isolation_enabled", False),
            relation_capability=context.get("relation_capability"),
            effective_fields=effective_fields,
        )
        if json_bytes(expected) != json_bytes(context):
            raise ValueError("native admission context mismatch")
        phase = "binding"
        if context.get("dependency_policy") == NATIVE_DEPENDENCY_POLICY:
            decoded = decode_model_json(raw)
            if not isinstance(decoded, dict):
                raise ValueError("native admission response must be an object")
            value = decoded
            if wire_protocol is not None:
                from insurance_harness.product_ingestion.native_admission_wire import (
                    WIRE_PROTOCOL,
                    expand_wire_response,
                )
                from insurance_harness.product_ingestion.native_relation_wire import (
                    RELATION_WIRE_PROTOCOL,
                    expand_relation_wire_response,
                )

                if wire_protocol == RELATION_WIRE_PROTOCOL:
                    value, expansion = expand_relation_wire_response(value, context)
                elif wire_protocol == WIRE_PROTOCOL and "relation_capability" not in context:
                    value, expansion = expand_wire_response(value, context)
                else:
                    raise ValueError("native admission wire protocol invalid")
            else:
                _bind_v2(value, context, changes)
            canonical = json_bytes(value)
        elif wire_protocol is not None:
            raise ValueError("native admission wire requires dependency policy")
        phase = "strict_projection"
        projection = project_native_admission_response(
            raw=canonical,
            request=request,
            entity_id=entity_id,
            snapshot=snapshot,
            source=source,
            context=context,
            effective_fields=effective_fields,
        )
    except ValueError as exc:
        failure = str(exc)
    finally:
        if value is not None:
            canonical = json_bytes(value)
    receipt = {
        "contract": "native-admission-wire-preflight.830.v1",
        "original_sha256": _digest(raw),
        "canonical_sha256": _digest(canonical),
        "context_sha256": _digest(json_bytes(context)),
        "source_snapshot_sha256": snapshot.source_snapshot_sha256,
        "native_snapshot_sha256": snapshot.snapshot_sha256,
        "changes": changes,
        "status": "PASS" if projection is not None else "REJECTED",
        "strict_projection": "PASS"
        if projection is not None
        else ("REJECTED" if phase == "strict_projection" else "NOT_RUN"),
        "error": {"phase": phase, "detail": failure} if failure is not None else None,
        **({"wire_expansion": expansion} if expansion is not None else {}),
    }
    return NativeAdmissionPreflight(projection, canonical, receipt, failure)
