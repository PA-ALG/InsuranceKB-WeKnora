"""Preserve validated window ownership independently of its isolation policy.

Only the projector has the exact local-reference to formal-member mapping. This
internal domain preserves it for server-side aggregation; it neither rewrites the
model input nor expands the source or publication authority of a response.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from insurance_harness.knowledge_compiler.concept_compile_830_g2 import free_page_id
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    ConceptDefinition,
    FreeWikiPage,
)
from insurance_harness.product_ingestion.stages import json_bytes

if TYPE_CHECKING:
    from insurance_harness.product_ingestion.native_admission_contract import (
        NativeAdmissionResponseV2,
    )
    from insurance_harness.product_ingestion.native_discovery import NativeDiscoverySnapshot


def build_window_dependency_domain(
    *,
    request_hash: str,
    snapshot: NativeDiscoverySnapshot,
    context: dict[str, Any],
    raw: bytes,
    response: NativeAdmissionResponseV2,
    projected: Mapping[str, ConceptDefinition | FreeWikiPage],
    review_bindings: Sequence[dict[str, Any]],
    retained_candidates: frozenset[str],
    isolated_candidates: Sequence[dict[str, Any]],
    effective_dependencies: list[list[list[str]]],
) -> dict[str, Any]:
    """Seal the window domain while all validated local member refs still exist.

    Members' final content hashes are bound by the aggregate after PDF geometry
    projection. Coordinates may change during that step; formal IDs may not.
    """
    if len(snapshot.windows) != 1:
        raise ValueError("dependency domain requires one captured window")
    members = [
        {
            "member_ref": ref,
            "member_id": member.concept_id
            if isinstance(member, ConceptDefinition)
            else free_page_id(member),
            "member_type": "definition" if isinstance(member, ConceptDefinition) else "page",
        }
        for ref, member in sorted(projected.items())
    ]
    by_ref = {row["member_ref"]: row["member_id"] for row in members}
    decisions = {row.candidate_ref: row for row in response.decisions}
    expected = {
        (row.candidate_ref, ref) for row in response.decisions for ref in row.member_refs or (None,)
    }
    observed = {(row["candidate_ref"], row["member_ref"]) for row in review_bindings}
    if (
        observed != expected
        or len(observed) != len(review_bindings)
        or len({row["review_candidate_id"] for row in review_bindings}) != len(review_bindings)
        or any(
            row["candidate_ref"] not in decisions
            or row["member_id"] != by_ref.get(row["member_ref"])
            for row in review_bindings
        )
    ):
        raise ValueError("dependency domain review binding mismatch")
    value = {
        "contract": "native-window-dependency-domain.830.v1",
        "request_hash": request_hash,
        "scope": snapshot.scope,
        "knowledge_id": snapshot.knowledge_id,
        "parse_attempt": snapshot.parse_attempt,
        "source_snapshot_sha256": snapshot.source_snapshot_sha256,
        "window_id": snapshot.windows[0].window_id,
        "native_snapshot_sha256": snapshot.snapshot_sha256,
        "entity_id": context["entity"]["entity_id"],
        "entity_version": context["entity"]["entity_version"],
        "admission_context": context,
        "admission_context_sha256": hashlib.sha256(json_bytes(context)).hexdigest(),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "response": response.model_dump(mode="json"),
        "members": members,
        "review_bindings": sorted(review_bindings, key=lambda row: row["review_candidate_id"]),
        "retained_candidates": sorted(retained_candidates),
        "isolated_candidates": list(isolated_candidates),
        "effective_dependencies": effective_dependencies,
    }
    return {**value, "domain_sha256": hashlib.sha256(json_bytes(value)).hexdigest()}


def validate_window_member_bindings(
    response: NativeAdmissionResponseV2,
    projected: Mapping[str, ConceptDefinition | FreeWikiPage],
    context: dict[str, Any],
) -> None:
    """Check semantic ownership after geometry projection without guessing refs."""
    from insurance_harness.product_ingestion.native_admission_contract import (
        NativeDefinition,
        NativePage,
    )

    concepts = {
        row["concept_id"]: row["concept_id"] for row in context["existing_knowledge"]["definitions"]
    }
    concepts.update(
        {
            ref: row.concept_id
            for ref, row in projected.items()
            if isinstance(row, ConceptDefinition)
        }
    )
    for source in (*response.definitions, *response.pages):
        member = projected[source.member_ref]
        keys = (
            ("canonical_key", "sense_key", "aliases")
            if isinstance(source, NativeDefinition)
            else ("stable_key", "conditions", "exceptions", "valid_time")
        )
        if (
            isinstance(source, NativeDefinition) != isinstance(member, ConceptDefinition)
            or any(getattr(source, key) != getattr(member, key) for key in ("title", "body", *keys))
            or isinstance(member, FreeWikiPage)
            and isinstance(source, NativePage)
            and member.concept_ids != tuple(concepts[ref] for ref in source.concept_refs)
        ):
            raise ValueError("aggregate local member semantics mismatch")
        # Native geometry may split evidence indexes. It cannot rewrite segment
        # text or turn a generated statement into a source-supported statement.
        if member.content_provenance is None or [
            (row.origin, row.text) for row in member.content_provenance.segments
        ] != [(row.origin, row.text) for row in source.content_provenance.segments]:
            raise ValueError("aggregate member provenance changed during projection")
