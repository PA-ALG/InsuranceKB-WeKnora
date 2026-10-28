"""Publish judge-approved changes as machine review, one product at a time (RV7 Spec §2.3).

A product with an attempt on record continues it (records.py); otherwise the change set is
recomputed against the current Active with the real rules, on exactly the inputs the judge relied
on (review R4). A point counts as published only when Active holds exactly the judged content
(review R5); every other approved point must still be a judged change with the content and the
live value the judge saw. Claims carry the judge's reviewer as machine review and the policy goes
on the machine decision, never a person's. A dry run sends nothing and records nothing; the first
failure stops.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from insurance_harness.bundle.client import (
    DecisionInput,
    PlatformClient,
    PlatformError,
    Release,
)
from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.catalog.navigation import load_navigation
from insurance_harness.catalog.spot_check import SpotCheckPolicy, load_spot_check_policy
from insurance_harness.changes.options import registry_inputs
from insurance_harness.changes.types import Verdict
from insurance_harness.compilers.schema_fields.claims import require_cards_version
from insurance_harness.compilers.schema_fields.page import product_page
from insurance_harness.compilers.schema_fields.publish import REPO
from insurance_harness.compilers.schema_fields.publish_changes import delta_bundle
from insurance_harness.contracts.bundle import CandidateBundle
from insurance_harness.contracts.enums import ReviewMode
from insurance_harness.ingest.judge_batch import records
from insurance_harness.ingest.judge_batch.manifest import check_run_root, write_json
from insurance_harness.ingest.judge_batch.points import (
    JUDGED,
    JudgeBatchError,
    content_of,
    live_claim,
    rebuild,
)
from insurance_harness.ingest.judge_batch.verdicts import (
    judged_points,
    load_plan,
    load_summary,
    load_verdicts,
)
from insurance_harness.ingest.source_map import PageReader
from insurance_harness.review.routing import Route, Scores


def _approved(run_root: Path, product: str) -> dict[str, dict[str, Any]]:
    """Approved slug -> the point as the judge saw it."""
    points = judged_points(run_root, product)
    approved = {
        row["slug"] for row in load_verdicts(run_root, product) if row["verdict"] == "approve"
    }
    if not approved <= set(points):
        raise JudgeBatchError("VERDICTS_MISMATCH")
    return {slug: points[slug] for slug in sorted(approved)}


def live_contents(active: Release | None, slugs: list[str]) -> dict[str, str | None]:
    """Each slug's content in Active, None when Active has no such claim."""
    found = {slug: live_claim(active, slug) for slug in slugs}
    return {slug: None if claim is None else content_of(claim) for slug, claim in found.items()}


def build(
    run_root: Path,
    product: str,
    *,
    registry: Path,
    compile_root: Path,
    reader: PageReader,
    active: Release | None,
    repo: Path = REPO,
) -> tuple[CandidateBundle | None, dict[str, Any]]:
    approved = _approved(run_root, product)
    if not approved:
        return None, {"status": "nothing_approved", "claims": 0}
    summary = load_summary(run_root)
    try:
        basis = load_plan(run_root)["basis"][product]
    except (KeyError, TypeError):
        raise JudgeBatchError("PLAN_MISSING") from None
    rebuilt = rebuild(
        product,
        registry=registry,
        compile_root=compile_root,
        reader=reader,
        active=active,
        basis=basis,
    )
    items = {item.logical_key: item for item in rebuilt.changes.items}
    members = {claim.logical_key: claim for claim in rebuilt.changes.members}
    live = live_contents(active, list(approved))
    chosen = []
    for slug, point in approved.items():
        if live[slug] == point["content"]:
            continue  # exactly the judged content is already live
        item = items.get(slug)
        if (
            item is None
            or item.verdict not in JUDGED
            or slug not in members
            or content_of(members[slug]) != point["content"]
        ):
            raise JudgeBatchError("CONTENT_CHANGED")
        base = live_claim(active, item.base_slug) if item.verdict != Verdict.ADD else None
        if (None if base is None else content_of(base)) != point.get("live_content"):
            raise JudgeBatchError("CONTENT_CHANGED")  # the judge compared against another value
        chosen.append(members[slug])
    if not chosen:
        return None, {"status": "already_published", "claims": 0}
    route = Route(mode=ReviewMode.MACHINE, policy_ref=summary["policy_ref"], reasons=())
    scores = Scores(
        reviewer=summary["reviewer"],
        reviewed_at=summary["ingested_at"],
        by_key={claim.logical_key: 1.0 for claim in chosen},
    )
    page = product_page(
        repo / SCHEMA_PACK_CATALOG, rebuilt.pack, entity_id=product, name=rebuilt.name
    )
    version = require_cards_version(rebuilt.output)
    bundle = delta_bundle(
        tuple(chosen),
        (),
        active,
        page,
        load_navigation(),
        route,
        scores,
        f"harness/schema_fields@{version}",
    )
    now = {m.logical_slug: m.member_digest for m in active.members} if active else {}
    for member in bundle.members:
        if member.kind != "claim" and now.get(member.logical_slug, member.member_digest) != (
            member.member_digest
        ):
            raise JudgeBatchError("WOULD_OVERWRITE")
    claims = [m for m in bundle.members if m.kind == "claim"]
    if any((m.payload.get("review") or {}).get("mode") != "machine" for m in claims):
        raise JudgeBatchError("LABEL_NOT_MACHINE")
    changes: dict[str, int] = {}
    for member in claims:
        name = items[member.logical_slug].verdict.value
        changes[name] = changes.get(name, 0) + 1
    info = {
        "status": "ready",
        "claims": len(claims),
        "slugs": sorted(m.logical_slug for m in claims),
        "contents": {m.logical_slug: approved[m.logical_slug]["content"] for m in claims},
        "changes": changes,
        "others": sorted(m.logical_slug for m in bundle.members if m.kind != "claim"),
        "base_epoch": active.epoch if active else None,
    }
    return bundle, info


def _decision(summary: dict[str, Any], issue: int) -> DecisionInput:
    return DecisionInput(
        outcome="approve",
        mode="machine",
        policy_ref=summary["policy_ref"],
        reason=f"模型评审（{summary['reviewer']}）批准，运维 Issue #{issue}",
    )


def _product(
    run_root: Path,
    product: str,
    *,
    space_id: str,
    registry: Path,
    compile_root: Path,
    reader: PageReader,
    client: PlatformClient,
    issue: int,
    live: bool,
    policy: SpotCheckPolicy | None,
    repo: Path,
) -> dict[str, Any]:
    record = records.current(run_root, product)
    if record is not None and record.status == "published":
        now = live_contents(client.active(space_id), record.slugs)
        if now != record.contents:
            raise JudgeBatchError("CONTENT_CHANGED")
        return {"status": "already_published", "claims": len(record.slugs), **record.summary()}
    if record is not None and record.status == "in_progress":
        if not live or policy is None:
            return {"status": "in_progress", "pending": record.pending, **record.summary()}
        done = records.advance(run_root, record, client=client, space_id=space_id, policy=policy)
        return {"status": "published", "claims": len(done.slugs), **done.summary()}
    active = client.active(space_id)
    bundle, info = build(
        run_root,
        product,
        registry=registry,
        compile_root=compile_root,
        reader=reader,
        active=active,
        repo=repo,
    )
    contents = info.pop("contents", {})
    if bundle is None or not live or policy is None:
        return info
    summary = load_summary(run_root)
    record = records.start(run_root, product, bundle, contents, _decision(summary, issue))
    done = records.advance(
        run_root, record, client=client, space_id=space_id, policy=policy, base=active
    )
    return {**info, **done.summary(), "status": "published"}


def publish_batch(
    run_root: Path,
    *,
    registry: Path,
    compile_root: Path,
    reader: PageReader,
    client: PlatformClient,
    issue: int,
    live: bool = False,
    spot_check_policy: Path | None = None,
    repo: Path = REPO,
    products: list[str] | None = None,
) -> dict[str, Any]:
    check_run_root(run_root)
    summary = load_summary(run_root)
    selected = sorted(products or summary["products"])
    out_path = run_root / f"publish-{'live' if live else 'dry'}.json"
    result: dict[str, Any] = {"live": live, "stopped": None, "products": {}}
    policy = load_spot_check_policy(spot_check_policy) if live else None
    space_id = registry_inputs(registry, selected)[0].space_id
    for product in selected:
        try:
            info = _product(
                run_root,
                product,
                space_id=space_id,
                registry=registry,
                compile_root=compile_root,
                reader=reader,
                client=client,
                issue=issue,
                live=live,
                policy=policy,
                repo=repo,
            )
        except (JudgeBatchError, PlatformError) as error:
            result["stopped"] = {"product": product, "code": error.code}
            write_json(out_path, result)
            return result
        result["products"][product] = info
        write_json(out_path, result)
    return result
