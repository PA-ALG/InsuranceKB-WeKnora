"""Close a human-queue candidate's leftovers through the machine route (RV7 Spec §2.4, RV6d).

The judge saw this batch's content, not the leftover's, so a verdict carries over only to a point
whose proposed content is exactly what the judge saw (review R3). What the candidate proposes is
read from the platform (RV6e `review_detail`), never from a file the operator supplies: a file of
the same shape could stand for content the judge never saw (review round 2, R3). Before anything
is closed, the candidate must be pending for this product and every claim it proposes must parse;
a failed read sends nothing. Judge-rejected points are rejected; approved points are rejected as
superseded only when this batch's completed attempt published them and Active still holds the
very member it published. A point whose content differs, a judged point the candidate lacks and a
pending point the batch never judged all stay open for people. One point per request, so a point
someone already decided is reported as such; a run can resume. A dry run reads but sends nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from insurance_harness.bundle.client import CandidateDetail, PlatformClient, PlatformError
from insurance_harness.contracts.knowledge import Claim
from insurance_harness.ingest.judge_batch import records
from insurance_harness.ingest.judge_batch.manifest import check_run_root, write_json
from insurance_harness.ingest.judge_batch.points import JudgeBatchError, content_of
from insurance_harness.ingest.judge_batch.verdicts import (
    judged_points,
    load_plan,
    load_summary,
    load_verdicts,
)


def _detail(client: PlatformClient, space_id: str, candidate: str) -> CandidateDetail:
    try:
        return client.review_detail(space_id, candidate)
    except PlatformError as error:
        if error.code == "CANDIDATE_NOT_FOUND":
            raise JudgeBatchError("CANDIDATE_NOT_PENDING") from None
        raise JudgeBatchError(error.code) from None


def _proposed(detail: CandidateDetail, product: str) -> tuple[dict[str, str], list[str]]:
    """Slug -> content of each claim the pending candidate proposes, and its pending points."""
    if detail.status != "pending" or product not in detail.subjects:
        raise JudgeBatchError("CANDIDATE_NOT_PENDING")
    proposed: dict[str, str] = {}
    for member in detail.bundle_members:
        if member.kind != "claim":
            continue
        try:
            claim = Claim.model_validate(member.payload)
        except ValidationError:
            raise JudgeBatchError("CANDIDATE_CONTENT_INVALID") from None
        if claim.logical_key != member.logical_slug:
            raise JudgeBatchError("CANDIDATE_CONTENT_INVALID")
        proposed[member.logical_slug] = content_of(claim)
    open_points = [point for point in detail.points if point.status == "pending"]
    if any(point.kind == "claim" and point.slug not in proposed for point in open_points):
        raise JudgeBatchError("CANDIDATE_CONTENT_INVALID")  # a claim point with no claim to read
    return proposed, sorted(point.slug for point in open_points)


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
    summary, space_id = load_summary(run_root), load_plan(run_root)["space_id"]
    points = judged_points(run_root, product)
    verdicts = {row["slug"]: row["verdict"] for row in load_verdicts(run_root, product)}
    proposed, pending = _proposed(_detail(client, space_id, candidate), product)
    attempt = records.current(run_root, product)
    published = attempt if attempt is not None and attempt.status == "published" else None
    ours = {} if published is None else records.published_members(run_root, published)
    try:
        active = client.active(space_id)
    except PlatformError as error:
        raise JudgeBatchError(error.code) from None
    live_now = {m.logical_slug: m.member_digest for m in active.members} if active else {}
    supersede, reject, skipped = [], [], {}
    for slug, verdict in sorted(verdicts.items()):
        judged = points[slug]["content"] if slug in points else None
        if slug not in proposed:
            skipped[slug] = "not_in_candidate"
        elif proposed[slug] != judged:
            skipped[slug] = "content_differs"
        elif verdict == "reject":
            reject.append(slug)
        elif (
            published is not None
            and published.contents.get(slug) == judged
            and slug in ours
            and live_now.get(slug) == ours[slug]
        ):
            supersede.append(slug)
        else:
            skipped[slug] = "not_live"
    result: dict[str, Any] = {
        "product": product,
        "candidate": candidate,
        "supersede": supersede,
        "reject": reject,
        "skipped": skipped,
        "unreviewed": [slug for slug in pending if slug not in verdicts],
        "closed": {},
        "live": live,
    }
    if not live:
        return result
    reviewer, policy_ref = summary["reviewer"], summary["policy_ref"]
    by = None if published is None else published.candidate
    plans = [
        (slug, f"已由模型评审候选 {by} 发布，本点关闭（运维 Issue #{issue}）") for slug in supersede
    ] + [(slug, f"模型评审（{reviewer}）拒绝，运维 Issue #{issue}") for slug in reject]
    for slug, reason in plans:
        try:
            client.reject_points(space_id, candidate, [slug], reason, policy_ref)
            result["closed"][slug] = "rejected"
        except PlatformError as error:
            if error.code != "MEMBER_DECIDED":
                result["stopped"] = {"slug": slug, "code": error.code}
                write_json(run_root / f"close-{product}.json", result)
                raise JudgeBatchError(error.code) from None
            result["closed"][slug] = "already_decided"
    write_json(run_root / f"close-{product}.json", result)
    return result
