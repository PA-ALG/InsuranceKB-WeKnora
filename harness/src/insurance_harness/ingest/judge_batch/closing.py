"""Close a human-queue candidate's leftovers through the machine route (RV7 Spec §2.4, RV6d).

Points the judge rejected are rejected; points a machine candidate of this run already published
are rejected as superseded. One point per request, so a point someone already decided is reported
as such without blocking the others; a run can resume. A dry run sends nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from insurance_harness.bundle.client import PlatformClient, PlatformError
from insurance_harness.ingest.judge_batch.points import JudgeBatchError
from insurance_harness.ingest.judge_batch.sessions import check_run_root, write_json
from insurance_harness.ingest.judge_batch.verdicts import load_summary, load_verdicts


def _published(run_root: Path, product: str) -> tuple[list[str], str | None]:
    """Slugs and candidate of this product's live publication, if this run published it."""
    try:
        live = json.loads((run_root / "publish-live.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], None
    row = live.get("products", {}).get(product) or {}
    if row.get("status") != "published":
        return [], None
    return list(row.get("slugs") or []), row.get("candidate")


def close_points(
    run_root: Path,
    *,
    client: PlatformClient,
    product: str,
    candidate: str,
    issue: int,
    live: bool = False,
) -> dict[str, Any]:
    check_run_root(run_root)
    summary = load_summary(run_root)
    plan = json.loads((run_root / "plan.json").read_text(encoding="utf-8"))
    rows = load_verdicts(run_root, product)
    rejected = sorted(row["slug"] for row in rows if row["verdict"] == "reject")
    published, new_candidate = _published(run_root, product)
    superseded = sorted(published)
    reviewer, policy_ref = summary["reviewer"], summary["policy_ref"]
    result: dict[str, Any] = {
        "product": product,
        "candidate": candidate,
        "supersede": superseded,
        "reject": rejected,
        "closed": {},
        "live": live,
    }
    if not live:
        return result
    plans = [
        (slug, f"已由模型评审候选 {new_candidate} 发布，本点关闭（运维 Issue #{issue}）")
        for slug in superseded
    ] + [(slug, f"模型评审（{reviewer}）拒绝，运维 Issue #{issue}") for slug in rejected]
    for slug, reason in plans:
        try:
            client.reject_points(plan["space_id"], candidate, [slug], reason, policy_ref)
            result["closed"][slug] = "rejected"
        except PlatformError as error:
            if error.code != "MEMBER_DECIDED":
                result["stopped"] = {"slug": slug, "code": error.code}
                write_json(run_root / f"close-{product}.json", result)
                raise JudgeBatchError(error.code) from None
            result["closed"][slug] = "already_decided"
    write_json(run_root / f"close-{product}.json", result)
    return result
