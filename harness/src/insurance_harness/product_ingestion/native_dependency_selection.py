"""Select a closed set from one fully validated native admission response.

This module owns dependency propagation only. It cannot validate sources, call a
model, alter existing knowledge, or authorize publication.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    ConceptDefinition,
    FreeWikiPage,
)

if TYPE_CHECKING:
    from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
        BatchConceptCompileRequest830G3V1,
    )
    from insurance_harness.knowledge_compiler.concept_compile_830_g2 import CompileOutput
    from insurance_harness.product_ingestion.native_admission_contract import (
        NativeAdmissionResponseV2,
    )


def select_native_dependencies(
    response: NativeAdmissionResponseV2,
    projected: Mapping[str, ConceptDefinition | FreeWikiPage],
) -> tuple[frozenset[str], tuple[dict[str, Any], ...], list[list[list[str]]]]:
    """Return retained candidate refs and an audit of all isolated candidates."""
    decisions = {row.candidate_ref: row for row in response.decisions}
    Node = tuple[str, str]
    dependents: dict[Node, set[Node]] = defaultdict(set)
    blocked: set[Node] = set()
    queue: deque[Node] = deque()

    def depends(node: Node, required: Node) -> None:
        dependents[required].add(node)

    def isolate(node: Node) -> None:
        if node not in blocked:
            blocked.add(node)
            queue.append(node)

    for row in response.decisions:
        if len(set(row.depends_on)) != len(row.depends_on) or any(
            ref not in decisions or ref == row.candidate_ref for ref in row.depends_on
        ):
            raise ValueError("native admission candidate dependency invalid")
        node = ("candidate", row.candidate_ref)
        for ref in row.depends_on:
            depends(node, ("candidate", ref))
        for ref in row.member_refs:
            member = ("member", ref)
            # Shared members are indivisible; all contributing candidates must
            # be available. Virtual member nodes avoid a quadratic owner clique.
            depends(node, member)
            depends(member, node)
        if row.decision in {"PENDING", "REQUIRES_ENTITY_RESOLUTION", "REJECT"}:
            isolate(node)
    definitions = {
        member.concept_id: ref
        for ref, member in projected.items()
        if isinstance(member, ConceptDefinition)
    }
    pages = {ref: member for ref, member in projected.items() if isinstance(member, FreeWikiPage)}
    for ref, page in pages.items():
        for concept in page.concept_ids:
            if concept in definitions:
                depends(("member", ref), ("member", definitions[concept]))
    while True:
        while queue:
            for dependent in dependents[queue.popleft()]:
                isolate(dependent)
        used = {
            concept
            for ref, page in pages.items()
            if ("member", ref) not in blocked
            for concept in page.concept_ids
        }
        orphans = {
            ref
            for concept, ref in definitions.items()
            if concept not in used and ("member", ref) not in blocked
        }
        if not orphans:
            break
        for ref in orphans:
            isolate(("member", ref))
    kept = frozenset(ref for ref in decisions if ("candidate", ref) not in blocked)
    audit = tuple(
        {
            "candidate_ref": row.candidate_ref,
            "decision": row.decision,
            "member_refs": sorted(row.member_refs),
            "depends_on": sorted(row.depends_on),
            "reason_code": "NATIVE_CANDIDATE_UNAVAILABLE"
            if row.decision in {"PENDING", "REQUIRES_ENTITY_RESOLUTION", "REJECT"}
            else "NATIVE_DEPENDENCY_UNAVAILABLE",
            "reason": row.reason,
        }
        for row in sorted(response.decisions, key=lambda row: row.candidate_ref)
        if row.candidate_ref not in kept
    )
    edges = sorted(
        [[list(node), list(required)] for required, nodes in dependents.items() for node in nodes]
    )
    return kept, audit, edges


def validate_dependency_selection(
    selection: dict[str, Any], member_ids: set[str], request_hash: str
) -> None:
    """Bind the immutable selection envelope to the members sent for final review."""
    from insurance_harness.product_ingestion.native_admission_contract import (
        NATIVE_DEPENDENCY_POLICY,
    )
    from insurance_harness.product_ingestion.stages import json_bytes

    payload = {k: v for k, v in selection.items() if k != "selection_sha256"}
    if (
        selection.get("contract") != "native-dependency-selection.830.v1"
        or selection.get("dependency_policy") != NATIVE_DEPENDENCY_POLICY
        or selection.get("request_hash") != request_hash
        or selection.get("selection_sha256") != hashlib.sha256(json_bytes(payload)).hexdigest()
        or set(selection.get("retained_member_ids", ())) != member_ids
    ):
        raise ValueError("native dependency selection binding mismatch")
    context = selection["admission_context"]
    if (
        context.get("isolation_enabled") is not True
        or context.get("contract") != "native-knowledge-admission-context.830.v2"
        or context.get("dependency_policy") != NATIVE_DEPENDENCY_POLICY
        or hashlib.sha256(json_bytes(context)).hexdigest() != selection["admission_context_sha256"]
    ):
        raise ValueError("native dependency selection context mismatch")
    from insurance_harness.product_ingestion.native_relation_admission import admission_response

    response = admission_response(selection["response"], context)
    refs = {r.candidate_ref for r in response.decisions}
    kept = set(selection["retained_candidates"])
    isolated = {r["candidate_ref"] for r in selection["isolated_candidates"]}
    if kept & isolated or kept | isolated != refs:
        raise ValueError("native dependency selection coverage mismatch")


def resolve_native_review_entity(
    *,
    request: BatchConceptCompileRequest830G3V1,
    candidate_output: CompileOutput,
    selection: dict[str, Any],
    entity_id: str | None = None,
) -> str:
    """Resolve comparison scope from verified ownership, never the whole release.

    Definitions remain global comparison knowledge; only entity-specific Schema
    and page views are scoped. This does not prune the selection or final output.
    """
    from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
        compile_request_hash_g3,
    )
    from insurance_harness.knowledge_compiler.concept_compile_830_g2 import free_page_id

    member_ids = {row.concept_id for row in candidate_output.definitions} | {
        free_page_id(row) for row in candidate_output.pages
    }
    validate_dependency_selection(
        selection, member_ids, compile_request_hash_g3(request.base_request)
    )
    selected = selection.get("entity_id")
    owner = selection["admission_context"].get("entity")
    bindings = [row for row in request.entity_bindings if row.entity_id == selected]
    if (
        not isinstance(selected, str)
        or not selected
        or not isinstance(owner, dict)
        or owner.get("entity_id") != selected
        or (entity_id is not None and entity_id != selected)
        or len(bindings) != 1
    ):
        raise ValueError("native review entity scope mismatch")
    version = bindings[0].entity_version
    if owner.get("entity_version") != version or any(
        (page.entity_id, page.entity_version) != (selected, version)
        for page in candidate_output.pages
    ):
        raise ValueError("native review entity scope mismatch")
    return selected
