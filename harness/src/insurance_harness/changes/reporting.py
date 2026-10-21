"""Content-free incremental publish reports and local conflict artifacts."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

from insurance_harness.bundle.client import Release
from insurance_harness.changes.types import ChangeSet, Verdict


def summarize(changes: ChangeSet, active: Release | None) -> dict[str, Any]:
    counts = Counter(item.verdict.value for item in changes.items)
    changed = {claim.logical_key for claim in changes.members} | set(changes.removals)
    stale = sorted(
        member.logical_slug
        for member in (active.members if active else [])
        if member.kind == "concept"
        and isinstance(member.payload, dict)
        and isinstance(member.payload.get("based_on"), dict)
        and changed.intersection(member.payload["based_on"])
    )
    return {
        "counts": {verdict.value: counts[verdict.value] for verdict in Verdict},
        "conflicts": [
            item.logical_key for item in changes.items if item.verdict == Verdict.CONFLICT
        ],
        "stale_concepts": stale,
        "no_changes": not changes.members and not changes.removals,
        "candidate_id": None,
        "candidate_status": None,
        "decision_id": None,
        "release_id": None,
        "epoch": None,
    }


def write_reviews(run_root: Path, product: str, changes: ChangeSet) -> None:
    """Report beside this product's output, never another authority for the review queue."""
    directory = run_root / product
    rows = [
        json.dumps(
            {"slug": item.target, "verdict": "conflict", "hashes": sorted(set(item.evidence))},
            ensure_ascii=False,
        )
        for item in changes.review_items
    ]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "review_items.jsonl").write_text(
        "".join(row + "\n" for row in rows),
        encoding="utf-8",
    )
