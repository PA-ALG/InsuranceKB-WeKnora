"""Frozen UPG-07 history-preserving migrations for the v0.8.2 adoption.

This release-specific policy is shared by report generation and verification.
Remove it when a reviewed upstream migration preserves the same history. It is
not a configurable override mechanism and does not authorize database writes.
"""

from __future__ import annotations

import hashlib

TARGET = {
    "repository": "https://github.com/Tencent/WeKnora.git",
    "commit": "3e8b0bfc80b845b2d4b2ed683994748741450a97",
    "tree": "9533ab2071e71f4bc2ebb09c85d3ac246841ff9a",
}
HEAD = 110
HASHES = {
    "migrations/versioned/000077_remove_wiki_log.up.sql": (
        "ce67743466cf0d1cc43f5562c4c32a63366e09cc9922f7e95b4f0ab65cd4b0bf",
        "161172d066c4f0f00605745ff2ac69646b75a866783857109ac1a18328b5fc2a",
    ),
    "migrations/versioned/000077_remove_wiki_log.down.sql": (
        "93668b2406871639bf6b11421023a6832b2caecf208603b944530c611bea77d3",
        "da2c4ed60be8001957efa5fcd4a3a96828d6bb7c14a6bf378650061e0c269eb5",
    ),
}


def reviewed_rows() -> list[dict[str, str]]:
    return [
        {
            "path": path,
            "upstream_sha256": upstream_sha,
            "project_sha256": project_sha,
            "requirement": "UPG-07",
        }
        for path, (upstream_sha, project_sha) in HASHES.items()
    ]


def check_preservations(
    target: dict[str, str],
    head: int,
    upstream: dict[str, bytes],
    project: dict[str, bytes],
) -> list[dict[str, str]] | None:
    """Return reviewed differences, or None for an unapproved migration set."""
    if target != TARGET or head != HEAD:
        return [] if project == upstream else None
    if project.keys() != upstream.keys():
        return None
    changed = {path for path in project if project[path] != upstream[path]}
    if changed != HASHES.keys():
        return None
    for path, (upstream_sha, project_sha) in HASHES.items():
        if (
            hashlib.sha256(upstream[path]).hexdigest() != upstream_sha
            or hashlib.sha256(project[path]).hexdigest() != project_sha
        ):
            return None
    return reviewed_rows()


def validate_report_preservations(
    target: dict[str, object],
    official: dict[str, object],
    verdict: object,
) -> None:
    """Reject a report that loses the exact, independently reviewed exception."""
    if set(target) != set(TARGET):
        raise ValueError("thin report migration preservation target is not closed")
    rows = official.get("reviewed_preservations")
    if target == TARGET or rows is not None:
        if (
            target != TARGET
            or official.get("head") != HEAD
            or verdict != "manual_review_required"
            or rows != reviewed_rows()
        ):
            raise ValueError("thin report migration preservation binding is invalid")
