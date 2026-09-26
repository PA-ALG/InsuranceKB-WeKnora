"""Compile complete native windows into one explicit, closed dependency domain.

The caller supplies validated window projections, not graph internals. Local refs
stay namespaced while equal formal members share ownership. This module never
changes source evidence, calls a model, or authorizes publication.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from insurance_harness.knowledge_compiler.concept_compile_830_g2 import CompileOutput, free_page_id
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    ConceptDefinition,
    FreeWikiPage,
)
from insurance_harness.product_ingestion.native_dependency_closure import (
    Edge,
    Node,
    unavailable_closure,
)
from insurance_harness.product_ingestion.stages import json_bytes

if TYPE_CHECKING:
    from collections.abc import Sequence

    from insurance_harness.product_ingestion.native_admission import NativeAdmissionProjection
    from insurance_harness.product_ingestion.native_discovery import NativeDiscoverySnapshot


@dataclass(frozen=True, slots=True)
class NativeAggregateSelection:
    output: CompileOutput
    selection: dict[str, Any]
    retained_review_ids: frozenset[str]
    pending_candidate_count: int


def _sha(value: object) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def _members(output: CompileOutput) -> dict[str, ConceptDefinition | FreeWikiPage]:
    rows: dict[str, ConceptDefinition | FreeWikiPage] = {
        row.concept_id: row for row in output.definitions
    }
    rows.update({free_page_id(row): row for row in output.pages})
    if len(rows) != len(output.definitions) + len(output.pages) or output.fields:
        raise ValueError("aggregate window member identity is invalid")
    if any(row.business_relation is not None for row in output.pages):
        raise ValueError("aggregate typed relations are not supported")
    return rows


def _window(snapshot: NativeDiscoverySnapshot) -> dict[str, Any]:
    if snapshot.phase != "snapshot" or len(snapshot.windows) != 1:
        raise ValueError("aggregate requires final single-window snapshots")
    return {
        "scope": snapshot.scope,
        "knowledge_id": snapshot.knowledge_id,
        "parse_attempt": snapshot.parse_attempt,
        "source_snapshot_sha256": snapshot.source_snapshot_sha256,
        "native_snapshot_sha256": snapshot.snapshot_sha256,
        "window_count": snapshot.window_count,
        "window_id": snapshot.windows[0].window_id,
        "candidate_count": len(snapshot.candidates),
    }


def aggregate_native_dependencies(
    *,
    snapshots: Sequence[NativeDiscoverySnapshot],
    projections: Sequence[NativeAdmissionProjection],
) -> NativeAggregateSelection:
    """Aggregate every known window; an empty captured window needs no model call."""
    windows = sorted((_window(row) for row in snapshots), key=lambda row: row["window_id"])
    domains = []
    for projection in projections:
        if projection.dependency_domain is None:
            raise ValueError("aggregate dependency domain is missing")
        members = _members(projection.output)
        domains.append(
            {
                "domain": projection.dependency_domain,
                "output": projection.output.model_dump(mode="json"),
                "member_sha256": {key: _sha(row) for key, row in sorted(members.items())},
            }
        )
    return _compile(windows, sorted(domains, key=lambda row: row["domain"]["window_id"]))


def _compile(
    windows: list[dict[str, Any]],
    domains: list[dict[str, Any]],
    review_seeds: frozenset[Node] = frozenset(),
    review_pruning: dict[str, Any] | None = None,
) -> NativeAggregateSelection:
    from insurance_harness.product_ingestion.native_admission_contract import (
        NATIVE_DEPENDENCY_POLICY,
    )
    from insurance_harness.product_ingestion.native_dependency_selection import (
        select_native_dependencies,
    )
    from insurance_harness.product_ingestion.native_relation_admission import admission_response

    if len(windows) < 2 or not domains:
        raise ValueError("aggregate requires multiple complete windows with candidates")
    base = windows[0]
    source_keys = (
        "scope",
        "knowledge_id",
        "parse_attempt",
        "source_snapshot_sha256",
        "window_count",
    )
    if (
        base["window_count"] != len(windows)
        or [row["window_id"] for row in windows] != list(range(len(windows)))
        or any(any(row[k] != base[k] for k in source_keys) for row in windows)
        or len({row["native_snapshot_sha256"] for row in windows}) != len(windows)
    ):
        raise ValueError("aggregate source window coverage mismatch")
    by_snapshot = {row["native_snapshot_sha256"]: row for row in windows}
    expected = {row["native_snapshot_sha256"] for row in windows if row["candidate_count"]}
    observed = [row["domain"]["native_snapshot_sha256"] for row in domains]
    if len(set(observed)) != len(observed) or set(observed) != expected:
        raise ValueError("aggregate admission window coverage mismatch")
    first = domains[0]["domain"]
    owner = (first["entity_id"], first["entity_version"], first["request_hash"])
    members: dict[str, ConceptDefinition | FreeWikiPage] = {}
    audits: dict[str, Any] = {}
    candidates: dict[str, dict[str, Any]] = {}
    bindings = []
    edges: set[Edge] = set()
    unavailable: set[Node] = set()
    for item in domains:
        domain = item["domain"]
        window = by_snapshot[domain["native_snapshot_sha256"]]
        unsigned = {k: v for k, v in domain.items() if k != "domain_sha256"}
        context = domain["admission_context"]
        if (
            domain["contract"] != "native-window-dependency-domain.830.v1"
            or domain["domain_sha256"] != _sha(unsigned)
            or domain["admission_context_sha256"] != _sha(context)
            or any(domain[k] != window[k] for k in (*source_keys[:-1], "window_id"))
            or (domain["entity_id"], domain["entity_version"], domain["request_hash"]) != owner
            or context["dependency_policy"] != NATIVE_DEPENDENCY_POLICY
            or context["isolation_enabled"] is not False
            or context["native_snapshot_sha256"] != domain["native_snapshot_sha256"]
            or context["source_snapshot_sha256"] != domain["source_snapshot_sha256"]
            or (context["entity"]["entity_id"], context["entity"]["entity_version"]) != owner[:2]
        ):
            raise ValueError("aggregate window domain binding mismatch")
        response = admission_response(domain["response"], context)
        output = CompileOutput.model_validate(item["output"])
        local = _members(output)
        if output.request_hash != owner[2] or item["member_sha256"] != {
            key: _sha(row) for key, row in sorted(local.items())
        }:
            raise ValueError("aggregate final member content binding mismatch")
        mapping = {row["member_ref"]: row["member_id"] for row in domain["members"]}
        declared = {row.member_ref for row in (*response.definitions, *response.pages)}
        if (
            len(mapping) != len(domain["members"])
            or set(mapping) != declared
            or set(mapping.values()) != set(local)
        ):
            raise ValueError("aggregate local member mapping mismatch")
        projected = {ref: local[key] for ref, key in mapping.items()}
        from insurance_harness.product_ingestion.native_dependency_domain import (
            validate_window_member_bindings,
        )

        validate_window_member_bindings(response, projected, context)
        if any(member.space_id != domain["scope"]["space_id"] for member in local.values()):
            raise ValueError("aggregate member space mismatch")
        kept, isolated, local_edges = select_native_dependencies(response, projected)
        if (
            domain["retained_candidates"] != sorted(kept)
            or domain["isolated_candidates"] != list(isolated)
            or domain["effective_dependencies"] != local_edges
        ):
            raise ValueError("aggregate local closure mismatch")
        if any((page.entity_id, page.entity_version) != owner[:2] for page in output.pages):
            raise ValueError("aggregate member owner mismatch")
        for key, member in local.items():
            if key in members and members[key] != member:
                raise ValueError("aggregate formal member content conflict")
            members[key] = member
        for audit in output.audit:
            if audit.key not in local:
                raise ValueError("aggregate audit member mismatch")
            # Same formal content may carry different explanatory audit wording.
            audits.setdefault(audit.key, audit)
        namespace = _sha({**window, "entity_id": owner[0], "entity_version": owner[1]})
        candidate_keys = {
            row.candidate_ref: _sha([namespace, row.candidate_ref]) for row in response.decisions
        }
        if len(candidate_keys) != window["candidate_count"]:
            raise ValueError("aggregate native candidate coverage mismatch")
        for row in response.decisions:
            key = candidate_keys[row.candidate_ref]
            candidates[key] = {
                "candidate_key": key,
                "window_id": window["window_id"],
                "candidate_ref": row.candidate_ref,
                "decision": row.decision,
                "member_ids": sorted(mapping[ref] for ref in row.member_refs),
            }
            if row.decision in {"PENDING", "REQUIRES_ENTITY_RESOLUTION", "REJECT"}:
                unavailable.add(("candidate", key))
        for local_node, required in local_edges:
            converted = [
                (kind, candidate_keys[ref] if kind == "candidate" else mapping[ref])
                for kind, ref in (local_node, required)
            ]
            edges.add((converted[0], converted[1]))
        prefix = _sha([owner[0], domain["native_snapshot_sha256"]]) + ":"
        expected_bindings = {
            (row.candidate_ref, ref)
            for row in response.decisions
            for ref in row.member_refs or (None,)
        }
        actual = {(row["candidate_ref"], row["member_ref"]) for row in domain["review_bindings"]}
        if actual != expected_bindings or len(actual) != len(domain["review_bindings"]):
            raise ValueError("aggregate review ownership coverage mismatch")
        for binding in domain["review_bindings"]:
            ref = binding["member_ref"]
            expected_id = (
                domain["native_snapshot_sha256"]
                + ":"
                + binding["candidate_ref"]
                + ":"
                + (ref or "audit")
            )
            if binding["review_candidate_id"] != expected_id or binding["member_id"] != mapping.get(
                ref
            ):
                raise ValueError("aggregate review ownership binding mismatch")
            bindings.append(
                {
                    "review_candidate_id": prefix + binding["review_candidate_id"],
                    "candidate_key": candidate_keys[binding["candidate_ref"]],
                    "member_id": binding["member_id"],
                }
            )
    definitions = {
        key: ("member", key) for key, row in members.items() if isinstance(row, ConceptDefinition)
    }
    pages = {
        ("member", key): row.concept_ids
        for key, row in members.items()
        if isinstance(row, FreeWikiPage)
    }
    # All local references were already resolved; sharing a formal ID is the
    # only way a cross-window dependency can arise here.
    for node, concepts in pages.items():
        for concept in concepts:
            if concept in definitions:
                edges.add((node, definitions[concept]))
    blocked = unavailable_closure(
        edges=edges,
        unavailable=unavailable | set(review_seeds),
        definitions=definitions,
        pages=pages,
    )
    retained = sorted(key for key in candidates if ("candidate", key) not in blocked)
    retained_members = {key for key in members if ("member", key) not in blocked}
    retained_review = frozenset(
        row["review_candidate_id"] for row in bindings if row["candidate_key"] in retained
    )
    output = CompileOutput(
        request_hash=owner[2],
        fields=(),
        definitions=tuple(
            member
            for key, member in sorted(members.items())
            if key in retained_members and isinstance(member, ConceptDefinition)
        ),
        pages=tuple(
            sorted(
                (
                    member
                    for key, member in members.items()
                    if key in retained_members and isinstance(member, FreeWikiPage)
                ),
                key=lambda row: (row.entity_id, row.stable_key),
            )
        ),
        audit=tuple(audits[key] for key in sorted(retained_members) if key in audits),
        transformation="SYNTHESIZE" if retained_members else "EXTRACT",
    )
    value = {
        "contract": "native-dependency-selection.830.v2",
        **({"review_pruning": review_pruning} if review_pruning is not None else {}),
        "dependency_policy": NATIVE_DEPENDENCY_POLICY,
        "request_hash": owner[2],
        "entity_id": owner[0],
        "entity_version": owner[1],
        "windows": windows,
        "domains": domains,
        "candidates": [candidates[key] for key in sorted(candidates)],
        "review_bindings": sorted(bindings, key=lambda row: row["review_candidate_id"]),
        "effective_dependencies": sorted([[list(a), list(b)] for a, b in edges]),
        "retained_candidates": retained,
        "retained_member_ids": sorted(retained_members),
        "isolated_candidates": sorted(set(candidates) - set(retained)),
    }
    selection = {**value, "selection_sha256": _sha(value)}
    return NativeAggregateSelection(
        output, selection, retained_review, len(candidates) - len(retained)
    )


def validate_aggregate_selection(
    selection: dict[str, Any], output: CompileOutput | None = None
) -> CompileOutput:
    """Rebuild the closure and exact content binding; a matching hash alone is insufficient."""
    expected = _compile(selection["windows"], selection["domains"])
    if selection.get("review_pruning") is not None:
        from insurance_harness.product_ingestion.native_review_pruning import validated_review_seeds

        receipt = selection["review_pruning"]
        seeds = validated_review_seeds(expected.selection, receipt)
        if not seeds:
            raise ValueError("native pruning requires explicit local failure seeds")
        expected = _compile(selection["windows"], selection["domains"], seeds, receipt)
    if selection != expected.selection or (output is not None and output != expected.output):
        raise ValueError("aggregate dependency selection binding mismatch")

    return expected.output


def prune_aggregate_selection(
    selection: dict[str, Any], receipt: dict[str, Any]
) -> NativeAggregateSelection:
    """Apply exactly one review's failures through the same dependency closure."""
    from insurance_harness.product_ingestion.native_review_pruning import validated_review_seeds

    if "review_pruning" in selection:
        raise ValueError("native aggregate may be pruned only once")
    validate_aggregate_selection(selection)
    seeds = validated_review_seeds(selection, receipt)
    if not seeds:
        raise ValueError("native pruning requires explicit local failure seeds")
    return _compile(selection["windows"], selection["domains"], seeds, receipt)
