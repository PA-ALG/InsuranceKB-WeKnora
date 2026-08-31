#!/usr/bin/env python3
"""Generate the mechanical B0 branch/worktree index without mutating Git state."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


FORMAL_BASE = "99205db986eae2a9fa4bc956c053b94298d0b114"
OUTPUT = Path("docs/insurance-kb/evidence/830-b0/branch-worktree/branch-worktree-manifest.json")

CANDIDATE_REFS = {
    "refs/remotes/origin/main": {
        "disposition": "KEEP",
        "target_goal": "G1",
        "reason": "830 clean integration base and the merged 815 implementation authority.",
    },
    "refs/heads/codex/830-b0-asset-baseline": {
        "disposition": "KEEP",
        "target_goal": "B0",
        "reason": "The sole B0 Evidence Pack and authority-pointer delivery branch.",
    },
    "refs/heads/codex/830-technical-blueprint": {
        "disposition": "REWIRE",
        "target_goal": "B0",
        "reason": "Only the three authorized 830 documents are selected; the mixed branch is never merged as a unit.",
    },
    "refs/heads/codex/ec-01-execution-815": {
        "disposition": "FREEZE",
        "target_goal": None,
        "reason": "Frozen source of the 815 C7 evidence-base commit and runtime receipts.",
    },
    "refs/heads/codex/815-technical-route": {
        "disposition": "FREEZE",
        "target_goal": None,
        "reason": "Historical 815 route authority retained for audit, not execution.",
    },
    "refs/heads/codex/mvp-815-delivery": {
        "disposition": "FREEZE",
        "target_goal": None,
        "reason": "Historical delivery lane; effective code was rebuilt and merged by PR 123.",
    },
    "refs/heads/codex/mvp-815-handoff": {
        "disposition": "FREEZE",
        "target_goal": None,
        "reason": "Historical handoff lane; PR 124 and the B0 pack are the current audit chain.",
    },
}


def git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.rstrip("\n")


def goal_or_pr(refname: str) -> str:
    short = refname.removeprefix("refs/heads/").removeprefix("refs/remotes/")
    match = re.search(r"(?:^|/|-)pr[-/](\d+)(?:-|$)", short, re.IGNORECASE)
    if match:
        return f"PR-{match.group(1)}"
    match = re.search(r"(?:^|/)(\d{3})(?:-|/|$)", short)
    if match:
        return f"GOAL_OR_CHANGE-{match.group(1)}"
    if "830" in short:
        return "ROUTE-830"
    if "815" in short:
        return "MVP-815"
    return "NOT_MECHANICALLY_INFERRED"


def divergence(head: str) -> dict[str, object]:
    merge_base = git("merge-base", FORMAL_BASE, head, check=False)
    if not merge_base:
        return {
            "merge_base_with_formal_base": None,
            "formal_base_unique_commits": None,
            "ref_unique_commits": None,
            "reason": "NO_MERGE_BASE",
        }
    counts = git("rev-list", "--left-right", "--count", f"{FORMAL_BASE}...{head}")
    base_unique, ref_unique = [int(value) for value in counts.split()]
    return {
        "merge_base_with_formal_base": merge_base,
        "formal_base_unique_commits": base_unique,
        "ref_unique_commits": ref_unique,
        "reason": None,
    }


def head_metadata(head: str) -> dict[str, str]:
    raw = git("show", "-s", "--format=%aI%x09%an%x09%ae%x09%s", head)
    activity, author, email, subject = raw.split("\t", 3)
    return {
        "last_activity": activity,
        "head_author": author,
        "head_author_email": email,
        "head_subject": subject,
        "owner": author,
        "owner_basis": "HEAD_COMMIT_AUTHOR_PROXY_NOT_BRANCH_ACL",
    }


def ref_records() -> list[dict[str, object]]:
    raw = git(
        "for-each-ref",
        "--sort=refname",
        "--format=%(refname)%09%(objectname)%09%(authordate:iso-strict)%09%(authorname)%09%(authoremail)%09%(subject)",
        "refs/heads",
        "refs/remotes",
    )
    records: list[dict[str, object]] = []
    for line in raw.splitlines():
        refname, head, activity, author, email, subject = line.split("\t", 5)
        if refname.endswith("/HEAD"):
            continue
        candidate = CANDIDATE_REFS.get(refname)
        records.append(
            {
                "ref": refname,
                "kind": "LOCAL_BRANCH" if refname.startswith("refs/heads/") else "REMOTE_TRACKING_BRANCH",
                "head": head,
                "last_activity": activity,
                "head_author": author,
                "head_author_email": email,
                "head_subject": subject,
                "owner": author,
                "owner_basis": "HEAD_COMMIT_AUTHOR_PROXY_NOT_BRANCH_ACL",
                "goal_or_pr": goal_or_pr(refname),
                **divergence(head),
                "review_scope": "FINITE_CANDIDATE" if candidate else "INDEX_ONLY/OUT_OF_SCOPE",
                "disposition": candidate["disposition"] if candidate else None,
                "target_goal": candidate["target_goal"] if candidate else None,
                "disposition_reason": candidate["reason"] if candidate else None,
                "physical_action": "RETAIN; NO DELETE; NO WHOLE-BRANCH MERGE",
            }
        )
    return records


def parse_worktrees() -> list[dict[str, str]]:
    raw = git("worktree", "list", "--porcelain")
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in [*raw.splitlines(), ""]:
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value if value else "true"
    return records


def worktree_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for entry in parse_worktrees():
        path = Path(entry["worktree"])
        head = entry["HEAD"]
        branch = entry.get("branch")
        candidate = CANDIDATE_REFS.get(branch or "")
        status = git("status", "--porcelain=v1", cwd=path, check=False)
        status_lines = status.splitlines() if status else []
        records.append(
            {
                "path": str(path),
                "head": head,
                "branch": branch,
                "detached": entry.get("detached") == "true",
                "locked": entry.get("locked"),
                **head_metadata(head),
                "goal_or_pr": goal_or_pr(branch or str(path)),
                **divergence(head),
                "clean": len(status_lines) == 0,
                "dirty_entry_count": len(status_lines),
                "status_basis": "git status --porcelain=v1; filenames intentionally omitted",
                "review_scope": "FINITE_CANDIDATE" if candidate else "INDEX_ONLY/OUT_OF_SCOPE",
                "disposition": candidate["disposition"] if candidate else None,
                "target_goal": candidate["target_goal"] if candidate else None,
                "disposition_reason": candidate["reason"] if candidate else None,
                "physical_action": "RETAIN; NO DELETE; WORKTREE IS NOT AN ARCHIVE",
            }
        )
    return records


def main() -> None:
    repo = Path(git("rev-parse", "--show-toplevel"))
    observed_head = git("rev-parse", "HEAD")
    refs = ref_records()
    worktrees = worktree_records()
    payload = {
        "contract": "weknora.830.b0-branch-worktree-manifest.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": str(repo),
        "formal_base": FORMAL_BASE,
        "observed_branch": git("branch", "--show-current"),
        "observed_head_before_evidence_commit": observed_head,
        "head_binding_rule": (
            "The observed head must be an ancestor of final HEAD; every intervening commit must use only "
            "authorized B0 paths and carry the required B0/NEXT_PHYSICAL_RESULT message."
        ),
        "scope_statement": (
            "All current refs under refs/heads and refs/remotes plus all registered worktrees. "
            "Non-candidates are mechanical INDEX_ONLY/OUT_OF_SCOPE entries. No ref or worktree was removed."
        ),
        "owner_limit": "Git has no branch ACL owner; owner is mechanically represented by HEAD commit author.",
        "refs": refs,
        "worktrees": worktrees,
        "counts": {
            "refs": len(refs),
            "local_branches": sum(item["kind"] == "LOCAL_BRANCH" for item in refs),
            "remote_tracking_branches": sum(item["kind"] == "REMOTE_TRACKING_BRANCH" for item in refs),
            "candidate_refs": sum(item["review_scope"] == "FINITE_CANDIDATE" for item in refs),
            "index_only_refs": sum(item["review_scope"] == "INDEX_ONLY/OUT_OF_SCOPE" for item in refs),
            "worktrees": len(worktrees),
            "candidate_worktrees": sum(item["review_scope"] == "FINITE_CANDIDATE" for item in worktrees),
            "index_only_worktrees": sum(item["review_scope"] == "INDEX_ONLY/OUT_OF_SCOPE" for item in worktrees),
            "clean_worktrees": sum(bool(item["clean"]) for item in worktrees),
            "dirty_worktrees": sum(not bool(item["clean"]) for item in worktrees),
            "deleted_refs": 0,
            "removed_worktrees": 0,
        },
    }
    output = repo / OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
