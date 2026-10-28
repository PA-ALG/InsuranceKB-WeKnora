"""Publish judge-approved changes as machine review, one product at a time (RV7 Spec §2.3).

The change set is recomputed against the current Active with the real rules; every approved point
must still be a judged change with exactly the content the judge saw. Points already live (a
previous run) are skipped, so a run can resume. Claims carry the judge's policy and reviewer as
machine review, never a person's decision. A dry run sends nothing; the first failure stops.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from insurance_harness.bundle.client import (
    DecisionInput,
    PlatformClient,
    PlatformError,
    Release,
    publish,
)
from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.catalog.navigation import load_navigation
from insurance_harness.catalog.spot_check import load_spot_check_policy
from insurance_harness.changes.options import registry_inputs
from insurance_harness.changes.types import Verdict
from insurance_harness.compilers.schema_fields.claims import require_cards_version
from insurance_harness.compilers.schema_fields.page import product_page
from insurance_harness.compilers.schema_fields.publish import REPO
from insurance_harness.compilers.schema_fields.publish_changes import delta_bundle
from insurance_harness.contracts.bundle import CandidateBundle
from insurance_harness.contracts.enums import ReviewMode
from insurance_harness.ingest.judge_batch.points import (
    JUDGED,
    JudgeBatchError,
    content_of,
    rebuild,
)
from insurance_harness.ingest.judge_batch.sessions import check_run_root, write_json
from insurance_harness.ingest.judge_batch.verdicts import load_summary, load_verdicts
from insurance_harness.ingest.source_map import PageReader
from insurance_harness.review.routing import Route, Scores
from insurance_harness.review.spot_check import sample


def _judged(run_root: Path, product: str) -> dict[str, str]:
    """Approved slug -> the content fingerprint the judge saw."""
    try:
        changes = json.loads(
            (run_root / "data" / f"changes-{product}.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        raise JudgeBatchError("CHANGES_MISSING") from None
    shown = {point["slug"]: point["content"] for point in changes["points"]}
    approved = {
        row["slug"] for row in load_verdicts(run_root, product) if row["verdict"] == "approve"
    }
    if not approved <= set(shown):
        raise JudgeBatchError("VERDICTS_MISMATCH")
    return {slug: shown[slug] for slug in sorted(approved)}


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
    judged = _judged(run_root, product)
    if not judged:
        return None, {"status": "nothing_approved", "claims": 0}
    summary = load_summary(run_root)
    rebuilt = rebuild(
        product, registry=registry, compile_root=compile_root, reader=reader, active=active
    )
    verdicts = {item.logical_key: item.verdict for item in rebuilt.changes.items}
    members = {claim.logical_key: claim for claim in rebuilt.changes.members}
    chosen = []
    for slug, seen in judged.items():
        verdict = verdicts.get(slug)
        if verdict == Verdict.UNCHANGED:
            continue  # already live from a previous run
        if verdict not in JUDGED or slug not in members or content_of(members[slug]) != seen:
            raise JudgeBatchError("CONTENT_CHANGED")
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
        name = verdicts[member.logical_slug].value
        changes[name] = changes.get(name, 0) + 1
    info = {
        "status": "ready",
        "claims": len(claims),
        "slugs": sorted(m.logical_slug for m in claims),
        "changes": changes,
        "others": sorted(m.logical_slug for m in bundle.members if m.kind != "claim"),
        "base_epoch": active.epoch if active else None,
    }
    return bundle, info


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
            if bundle is not None and live:
                info.update(_go_live(client, space_id, bundle, active, summary, issue, policy))
        except (JudgeBatchError, PlatformError) as error:
            result["stopped"] = {"product": product, "code": error.code}
            write_json(out_path, result)
            return result
        result["products"][product] = info
        write_json(out_path, result)
    return result


def _go_live(
    client: PlatformClient,
    space_id: str,
    bundle: CandidateBundle,
    active: Release | None,
    summary: dict[str, Any],
    issue: int,
    policy: Any,
) -> dict[str, Any]:
    decision = DecisionInput(
        outcome="approve",
        mode="machine",
        policy_ref=summary["policy_ref"],
        reason=f"模型评审（{summary['reviewer']}）批准，运维 Issue #{issue}",
    )
    published = publish(client, space_id, bundle, decision=decision, activate=True)
    release = published.release
    if release is None:
        raise PlatformError("RELEASE_MISMATCH")
    picks = [(pick.slug, pick.stratum) for pick in sample(release, active, policy)]
    submitted = 0
    for start in range(0, len(picks), 500):
        submitted += len(client.submit_samples(space_id, release.id, picks[start : start + 500]))
    return {
        "status": "published",
        "candidate": published.candidate.id,
        "release": release.id,
        "epoch": release.epoch,
        "samples": submitted,
    }
