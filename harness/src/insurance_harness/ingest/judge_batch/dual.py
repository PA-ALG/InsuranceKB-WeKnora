"""Bind two blind, independent rounds to exactly the frozen candidate content."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from insurance_harness.eval.judge import JudgeRequest
from insurance_harness.eval.judge_files import stored_requests
from insurance_harness.ingest.judge_batch.execution import binding, digest, proof, read_json, sha
from insurance_harness.ingest.judge_batch.launch import run_script
from insurance_harness.ingest.judge_batch.manifest import write_json, write_session
from insurance_harness.ingest.judge_batch.points import JudgeBatchError


def round_record(root: Path) -> dict[str, Any]:
    return {
        "input": binding(root),
        "sessions": proof(root),
        "outputs": {
            p.relative_to(root).as_posix(): sha(p)
            for p in [root / "summary.json", *sorted((root / "verdicts").glob("*.json"))]
        },
    }


def seal(root: Path) -> None:
    write_json(root / "round-seal.json", round_record(root))
    if read_json(root / "plan.json")["round"] == 2:
        write_json(root.parent / "dual-review.json", combined(root.parent))


def verified_round(root: Path) -> dict[str, Any]:
    record: dict[str, Any] = read_json(root / "round-seal.json")
    if record != round_record(root):
        raise JudgeBatchError("REVIEW_RECORD_INVALID")
    return record


def rows(root: Path) -> dict[str, list[dict[str, Any]]]:
    summary = read_json(root / "summary.json")
    return {
        product: read_json(root / "verdicts" / f"{product}.json") for product in summary["products"]
    }


def prepare_second(root: Path) -> dict[str, Any]:
    first = verified_round(root)
    parent = read_json(root / "plan.json")
    if parent["round"] != 1:
        raise JudgeBatchError("DUAL_REVIEW_REQUIRED")
    approved = {r["slug"] for rr in rows(root).values() for r in rr if r["verdict"] == "approve"}
    child = root / "second"
    planned_sessions = {}
    manifest = {}
    prepared = {}
    for session in sorted(parent["sessions"]):
        original = root / "sessions" / session
        requests = []
        slugs: list[str] = []
        products: list[str] = []
        needed = {"AGENTS.md"}
        for request in stored_requests(original):
            question = json.loads(request.user)
            selected = [
                {k: v for k, v in p.items() if k not in {"live", "change"}}
                for p in question["points"]
                if p["slug"] in approved
            ]
            if not selected:
                continue
            needed.update(m["file"] for m in question["materials"])
            question["points"] = selected
            slugs.extend(p["slug"] for p in selected)
            products.append(question["product"])
            requests.append(
                JudgeRequest(request.system, json.dumps(question, ensure_ascii=False, indent=1))
            )
        if not requests:
            continue
        planned_sessions[session] = {"products": sorted(set(products)), "slugs": sorted(slugs)}
        source_files = read_json(root / "manifest.json")["sessions"][session]["files"]
        texts = {p: (original / p).read_text(encoding="utf-8") for p in source_files if p in needed}
        texts["run.json"] = json.dumps({"session": session, **planned_sessions[session]}) + "\n"
        prepared[session] = (requests, texts)
    plan = {**parent, "round": 2, "parent_binding": digest(first), "sessions": planned_sessions}
    if child.exists():
        if read_json(child / "plan.json") != plan:
            raise JudgeBatchError("REVIEW_INPUTS_CHANGED")
        binding(child)
        for session, (requests, texts) in prepared.items():
            stored = stored_requests(child / "sessions" / session)
            if [r.sha256 for r in stored] != [r.sha256 for r in requests]:
                raise JudgeBatchError("REQUEST_CHANGED")
            for name, text in texts.items():
                if (child / "sessions" / session / name).read_text(encoding="utf-8") != text:
                    raise JudgeBatchError("SESSION_CHANGED")
        return plan
    stage = Path(tempfile.mkdtemp(prefix=".second-preparing-", dir=root))
    try:
        for session, (requests, texts) in prepared.items():
            manifest[session] = {
                "files": write_session(stage / "sessions" / session, requests, texts)
            }
        (stage / "data").mkdir()
        (stage / "sessions").mkdir(exist_ok=True)
        write_json(stage / "manifest.json", {"sessions": manifest})
        write_json(stage / "plan.json", plan)
        script = stage / "run.sh"
        script.write_text(run_script(child, sorted(planned_sessions)))
        script.chmod(0o700)
        stage.rename(child)
    except BaseException:
        shutil.rmtree(stage)
        raise
    return plan


def check_second(root: Path) -> None:
    if not (root / "second" / "plan.json").is_file():
        raise JudgeBatchError("DUAL_REVIEW_REQUIRED")
    prepare_second(root)  # existing child: verify the exact deterministic projection, zero writes


def combined(root: Path) -> dict[str, Any]:
    check_second(root)
    first = verified_round(root)
    second = verified_round(root / "second")
    plan = read_json(root / "second" / "plan.json")
    if plan.get("parent_binding") != digest(first):
        raise JudgeBatchError("REVIEW_INPUTS_CHANGED")
    threads = [p["thread"] for r in (first, second) for p in r["sessions"].values()]
    if len(threads) != len(set(threads)):
        raise JudgeBatchError("SESSION_NOT_INDEPENDENT")
    initial = rows(root)
    later = rows(root / "second")
    approved = {r["slug"] for rr in initial.values() for r in rr if r["verdict"] == "approve"}
    all_second = [r for rr in later.values() for r in rr]
    if {r["slug"] for r in all_second} != approved or len(all_second) != len(approved):
        raise JudgeBatchError("COVERAGE_MISMATCH")
    by_slug = {r["slug"]: r for r in all_second}
    result: dict[str, list[dict[str, Any]]] = {}
    improvements = []
    for product, rr in initial.items():
        result[product] = []
        for row in rr:
            final = (
                row
                if row["verdict"] == "reject"
                else {**by_slug[row["slug"]], "change": row["change"]}
            )
            result[product].append(final)
            if final["verdict"] == "reject":
                improvements.append(
                    {"product": product, **final, "round": 1 if row["verdict"] == "reject" else 2}
                )
    summary = read_json(root / "summary.json")
    summary["ingested_at"] = read_json(root / "second" / "summary.json")["ingested_at"]
    summary["review_protocol"] = "dual-v1"
    summary["products"] = {
        product: {
            "points": len(rr),
            "approve": sum(r["verdict"] == "approve" for r in rr),
            "reject": sum(r["verdict"] == "reject" for r in rr),
            "reject_by": dict(Counter(r["category"] for r in rr if r["verdict"] == "reject")),
        }
        for product, rr in result.items()
    }
    return {
        "bindings": {"first": digest(first), "second": digest(second)},
        "summary": summary,
        "verdicts": result,
        "improvements": improvements,
    }


def verified(root: Path) -> dict[str, Any]:
    try:
        record: dict[str, Any] = read_json(root / "dual-review.json")
        if record != combined(root):
            raise JudgeBatchError("REVIEW_RECORD_INVALID")
        return record
    except (KeyError, TypeError, ValueError):
        raise JudgeBatchError("REVIEW_RECORD_INVALID") from None
