"""Read the judge's answers back, strictly and all-or-none (RV7 Spec §2.2).

Every request is rebuilt from its stored file and checked against its hash before its answer is
read; every point the plan put to the judge is answered exactly once, in request order. Nothing is
written unless the whole run is valid, and the same answers always give the same verdicts.
"""

from __future__ import annotations

import datetime
import json
from collections import Counter
from pathlib import Path
from typing import Any

from insurance_harness.eval.judge import JudgeProtocolError
from insurance_harness.eval.judge_files import FileJudgeClient, stored_requests
from insurance_harness.ingest.judge_batch.points import JudgeBatchError
from insurance_harness.ingest.judge_batch.sessions import check_run_root, prompt, write_json

_KEYS = {"slug", "verdict", "category", "reason"}


def _plan(run_root: Path) -> dict[str, Any]:
    try:
        plan: dict[str, Any] = json.loads((run_root / "plan.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise JudgeBatchError("PLAN_MISSING") from None
    return plan


def _answer(
    raw: str, asked: list[dict[str, Any]], categories: set[str], approve: str
) -> list[dict[str, Any]]:
    try:
        answer = json.loads(raw)
    except ValueError:
        raise JudgeBatchError("ANSWER_INVALID") from None
    got = answer.get("points") if isinstance(answer, dict) and set(answer) == {"points"} else None
    if not isinstance(got, list) or len(got) != len(asked):
        raise JudgeBatchError("ANSWER_INVALID")
    rows = []
    for row, point in zip(got, asked, strict=True):
        if (
            not isinstance(row, dict)
            or set(row) != _KEYS
            or row["slug"] != point["slug"]
            or row["verdict"] not in {"approve", "reject"}
            or not isinstance(row["reason"], str)
            or not row["reason"].strip()
            or (row["verdict"] == "approve") != (row["category"] == approve)
            or (row["verdict"] == "reject" and row["category"] not in categories)
        ):
            raise JudgeBatchError("ANSWER_INVALID")
        rows.append({**row, "reason": row["reason"].strip(), "change": point["change"]})
    return rows


def ingest(run_root: Path) -> dict[str, Any]:
    check_run_root(run_root)
    plan = _plan(run_root)
    rules = prompt()
    categories, approve = set(rules["reject_categories"]), rules["approve_category"]
    by_product: dict[str, list[dict[str, Any]]] = {}
    for session, entry in sorted(plan["sessions"].items()):
        session_dir = run_root / "sessions" / session
        try:
            requests = stored_requests(session_dir)
        except JudgeProtocolError:
            raise JudgeBatchError("REQUEST_CHANGED") from None
        client = FileJudgeClient(session_dir, model_id=plan["model"])
        seen: list[str] = []
        for request in requests:
            try:
                raw = client.complete(request)
            except JudgeProtocolError as error:
                code = "REQUEST_CHANGED" if "changed" in str(error) else "ANSWER_MISSING"
                raise JudgeBatchError(code) from None
            question = json.loads(request.user)
            for row in _answer(raw, question["points"], categories, approve):
                seen.append(row["slug"])
                by_product.setdefault(question["product"], []).append(row)
        if (
            client.unconsumed()
            or sorted(seen) != sorted(entry["slugs"])
            or len(set(seen)) != len(seen)
        ):
            raise JudgeBatchError("COVERAGE_MISMATCH")
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
