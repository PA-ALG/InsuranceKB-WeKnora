"""One fixed-point closure for local and aggregated native dependency domains."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping

Node = tuple[str, str]
Edge = tuple[Node, Node]


def unavailable_closure(
    *,
    edges: Iterable[Edge],
    unavailable: Iterable[Node],
    definitions: Mapping[str, Node],
    pages: Mapping[Node, tuple[str, ...]],
) -> frozenset[Node]:
    """Propagate failed requirements and remove unused definitions to a fixed point.

    Edges point from a dependent to its requirement. Candidate/member ownership
    is represented by reciprocal edges, so shared owners remain an atomic group.
    """
    dependents: dict[Node, set[Node]] = defaultdict(set)
    for node, required in edges:
        dependents[required].add(node)
    blocked = set(unavailable)
    pending = deque(blocked)
    while True:
        while pending:
            for dependent in dependents[pending.popleft()]:
                if dependent not in blocked:
                    blocked.add(dependent)
                    pending.append(dependent)
        used = {concept for page, refs in pages.items() if page not in blocked for concept in refs}
        orphans = {node for concept, node in definitions.items() if concept not in used} - blocked
        if not orphans:
            return frozenset(blocked)
        blocked.update(orphans)
        pending.extend(orphans)
