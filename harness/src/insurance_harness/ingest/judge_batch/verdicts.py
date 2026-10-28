"""Read the judge's answers back, strictly and all-or-none (RV7 Spec §2.2).

The session files are first compared byte for byte with the manifest prepare kept outside the
session (review R2); only then are the requests rebuilt and their answers read. Answers are
untrusted: strict JSON without duplicate keys or non-finite numbers, types checked before values,
one fixed error code (review R7). Every point the plan put to the judge is answered exactly once,
in request order. Nothing is written unless the whole run is valid, and the same answers always
give the same verdicts.
"""

from __future__ import annotations

import datetime
import json
from collections import Counter
from pathlib import Path
from typing import Any

from insurance_harness.eval.judge import JudgeProtocolError
from insurance_harness.eval.judge_files import FileJudgeClient, stored_requests
from insurance_harness.ingest.judge_batch.manifest import check_run_root, check_sessions, write_json
from insurance_harness.ingest.judge_batch.points import JudgeBatchError
from insurance_harness.ingest.judge_batch.sessions import prompt

_KEYS = ("slug", "verdict", "category", "reason")


def load_plan(run_root: Path) -> dict[str, Any]:
    try:
        plan: dict[str, Any] = json.loads((run_root / "plan.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise JudgeBatchError("PLAN_MISSING") from None
    return plan


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate key")
        document[key] = value
    return document


def _non_finite(value: str) -> object:
    raise ValueError(f"non-finite number {value}")


def _strict(raw: str) -> object:
    try:
        return json.loads(raw, object_pairs_hook=_unique, parse_constant=_non_finite)
    except (ValueError, RecursionError):
        raise JudgeBatchError("ANSWER_INVALID") from None


def _answer(
    raw: str, asked: list[dict[str, Any]], categories: set[str], approve: str
) -> list[dict[str, Any]]:
    answer = _strict(raw)
    if not isinstance(answer, dict) or list(answer) != ["points"]:
        raise JudgeBatchError("ANSWER_INVALID")
    got = answer["points"]
    if not isinstance(got, list) or len(got) != len(asked):
        raise JudgeBatchError("ANSWER_INVALID")
    rows = []
    for row, point in zip(got, asked, strict=True):
        if (
            not isinstance(row, dict)
            or set(row) != set(_KEYS)
            or not all(isinstance(row[key], str) for key in _KEYS)
        ):
            raise JudgeBatchError("ANSWER_INVALID")
        slug, verdict, category, reason = (str(row[key]) for key in _KEYS)
        if (
            slug != point["slug"]
            or verdict not in {"approve", "reject"}
            or not reason.strip()
            or (verdict == "approve") != (category == approve)
            or (verdict == "reject" and category not in categories)
        ):
            raise JudgeBatchError("ANSWER_INVALID")
        rows.append(
            {
                "slug": slug,
                "verdict": verdict,
                "category": category,
                "reason": reason.strip(),
                "change": point["change"],
            }
        )
    return rows


def _session_rows(
    session_dir: Path, model: str, categories: set[str], approve: str
) -> list[tuple[str, dict[str, Any]]]:
    try:
        requests = stored_requests(session_dir)
    except JudgeProtocolError:
        raise JudgeBatchError("REQUEST_CHANGED") from None
    client = FileJudgeClient(session_dir, model_id=model)
    rows: list[tuple[str, dict[str, Any]]] = []
    for request in requests:
        try:
            raw = client.complete(request)
        except JudgeProtocolError:
            # The requests matched the manifest, so only the answer can be missing or unreadable.
            raise JudgeBatchError("ANSWER_MISSING") from None
        question = json.loads(request.user)
        for row in _answer(raw, question["points"], categories, approve):
            rows.append((question["product"], row))
    if client.unconsumed():
        raise JudgeBatchError("COVERAGE_MISMATCH")
    return rows


def ingest(run_root: Path) -> dict[str, Any]:
    check_run_root(run_root)
    plan = load_plan(run_root)
    check_sessions(run_root, sorted(plan["sessions"]))
    rules = prompt()
    categories, approve = set(rules["reject_categories"]), rules["approve_category"]
    by_product: dict[str, list[dict[str, Any]]] = {}
    for session, entry in sorted(plan["sessions"].items()):
        answered = _session_rows(
            run_root / "sessions" / session, plan["model"], categories, approve
        )
        seen = [row["slug"] for _, row in answered]
        if sorted(seen) != sorted(entry["slugs"]) or len(set(seen)) != len(seen):
            raise JudgeBatchError("COVERAGE_MISMATCH")
        for product, row in answered:
            by_product.setdefault(product, []).append(row)
    if sorted(by_product) != sorted(
        product for entry in plan["sessions"].values() for product in entry["products"]
    ):
        raise JudgeBatchError("COVERAGE_MISMATCH")
    previous = _previous_summary(run_root)
    products: dict[str, Any] = {}
    for product, rows in sorted(by_product.items()):
        verdicts = Counter(row["verdict"] for row in rows)
        products[product] = {
            "points": len(rows),
            "approve": verdicts["approve"],
            "reject": verdicts["reject"],
            "reject_by": dict(
                sorted(Counter(r["category"] for r in rows if r["verdict"] == "reject").items())
            ),
        }
    # Re-running keeps the first ingest time: it is the review time the published claims carry.
    unchanged = previous is not None and previous.get("products") == products
    ingested_at = (
        previous["ingested_at"]
        if unchanged and previous is not None
        else datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    )
    for product, rows in by_product.items():
        write_json(run_root / "verdicts" / f"{product}.json", rows)
    summary = {
        "ingested_at": ingested_at,
        "policy_ref": plan["policy_ref"],
        "reviewer": plan["reviewer"],
        "products": products,
    }
    write_json(run_root / "summary.json", summary)
    return summary


def _previous_summary(run_root: Path) -> dict[str, Any] | None:
    try:
        data: dict[str, Any] = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data


def load_verdicts(run_root: Path, product: str) -> list[dict[str, Any]]:
    try:
        rows: list[dict[str, Any]] = json.loads(
            (run_root / "verdicts" / f"{product}.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        raise JudgeBatchError("VERDICTS_MISSING") from None
    return rows


def load_summary(run_root: Path) -> dict[str, Any]:
    summary = _previous_summary(run_root)
    if summary is None:
        raise JudgeBatchError("VERDICTS_MISSING")
    return summary


def judged_points(run_root: Path, product: str) -> dict[str, dict[str, Any]]:
    """Slug -> the point as prepared: its change, the content the judge saw and the live one."""
    try:
        changes = json.loads(
            (run_root / "data" / f"changes-{product}.json").read_text(encoding="utf-8")
        )
        return {point["slug"]: point for point in changes["points"]}
    except (OSError, ValueError, KeyError, TypeError):
        raise JudgeBatchError("CHANGES_MISSING") from None
