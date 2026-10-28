"""Close a human-queue candidate's leftovers through the machine route (RV7 Spec §2.4, RV6d).

The judge saw this batch's content, not the leftover's, so a verdict carries over only to a point
whose proposed content is exactly what the judge saw (review R3). A service key cannot read a
pending candidate's members, so the operator supplies the bundle as submitted; before anything is
closed it must agree with the platform: the candidate is pending for this product, its sizes and
base match, and its slugs group against the current Head exactly as the platform's preview does.
Judge-rejected points are rejected; approved points are rejected as superseded only when this
batch's completed attempt published them and Active still holds the judged content. One point per
request, so a point someone already decided is reported as such; a run can resume. A dry run reads
but sends nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from insurance_harness.bundle.client import PlatformClient, PlatformError, Release
from insurance_harness.contracts.bundle import CandidateBundle
from insurance_harness.contracts.knowledge import Claim
from insurance_harness.ingest.judge_batch import records
from insurance_harness.ingest.judge_batch.manifest import check_run_root, write_json
from insurance_harness.ingest.judge_batch.points import JudgeBatchError, content_of
from insurance_harness.ingest.judge_batch.publishing import live_contents
from insurance_harness.ingest.judge_batch.verdicts import (
    judged_points,
    load_plan,
    load_summary,
    load_verdicts,
)


def _submitted(path: Path) -> CandidateBundle:
    try:
        return CandidateBundle.model_validate_json(path.read_bytes())
    except (OSError, ValueError, ValidationError):
        raise JudgeBatchError("CANDIDATE_BUNDLE_MISMATCH") from None


def _delta(bundle: CandidateBundle, active: Release | None) -> dict[str, list[str]]:
    """The platform's preview grouping (release.compareMembers) of this bundle against Head."""
    head = {m.logical_slug: m.member_digest for m in active.members} if active else {}
    delta: dict[str, list[str]] = {"added": [], "changed": [], "removed": [], "unchanged": []}
    for member in bundle.members:
        if member.logical_slug not in head:
            delta["added"].append(member.logical_slug)
        elif head[member.logical_slug] != member.member_digest:
            delta["changed"].append(member.logical_slug)
        else:
            delta["unchanged"].append(member.logical_slug)
    delta["removed"] = [slug for slug in bundle.removals if slug in head]
    touched = {m.logical_slug for m in bundle.members} | set(bundle.removals)
    delta["unchanged"] += [slug for slug in head if slug not in touched]
    return {group: sorted(slugs) for group, slugs in delta.items()}


def _proposed(
    client: PlatformClient, space_id: str, product: str, candidate: str, bundle: CandidateBundle
) -> tuple[dict[str, str], Release | None]:
    """Slug -> content the target candidate proposes, once the file is shown to be its bundle."""
    queued = [i for i in client.review_queue(space_id, "pending") if i.candidate_id == candidate]
    if not queued or product not in queued[0].subjects:
        raise JudgeBatchError("CANDIDATE_NOT_PENDING")
    item, base = queued[0], bundle.base_release_id or ""
    preview = client.preview(space_id, candidate)
    active = client.active(space_id)
    if (
        (item.members, item.removals, item.base_release_id)
        != (len(bundle.members), len(bundle.removals), base)
        or preview.base_release_id != base
        or preview.head_release_id != (active.id if active else "")
        or preview.delta.model_dump() != _delta(bundle, active)
    ):
        raise JudgeBatchError("CANDIDATE_BUNDLE_MISMATCH")
    try:
        claims = [Claim.model_validate(m.payload) for m in bundle.members if m.kind == "claim"]
    except ValidationError:
        raise JudgeBatchError("CANDIDATE_BUNDLE_MISMATCH") from None
    return {claim.logical_key: content_of(claim) for claim in claims}, active


def close_points(
    run_root: Path,
    *,
    client: PlatformClient,
    product: str,
    candidate: str,
    candidate_bundle: Path,
    issue: int,
    live: bool = False,
) -> dict[str, Any]:
    check_run_root(run_root)
    summary, space_id = load_summary(run_root), load_plan(run_root)["space_id"]
    points = judged_points(run_root, product)
    verdicts = {row["slug"]: row["verdict"] for row in load_verdicts(run_root, product)}
    proposed, active = _proposed(client, space_id, product, candidate, _submitted(candidate_bundle))
    attempt = records.current(run_root, product)
    published = attempt if attempt is not None and attempt.status == "published" else None
    now = live_contents(active, sorted(verdicts))
    supersede, reject, skipped = [], [], {}
    for slug, verdict in sorted(verdicts.items()):
        judged = points[slug]["content"] if slug in points else None
        if slug not in proposed:
            skipped[slug] = "not_in_candidate"
        elif proposed[slug] != judged:
            skipped[slug] = "content_differs"
        elif verdict == "reject":
            reject.append(slug)
        elif published is not None and published.contents.get(slug) == judged == now[slug]:
            supersede.append(slug)
        else:
            skipped[slug] = "not_live"
    result: dict[str, Any] = {
        "product": product,
        "candidate": candidate,
        "supersede": supersede,
        "reject": reject,
        "skipped": skipped,
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
