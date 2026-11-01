"""Publish only changed Claims of one product; --dry-run sends no remote writes.

Uses the current source map (or registry) and the Active release read for this invocation. Conflicts
remain local review reports, unchanged members retain their base digest, and NEEDS_REBASE stops
without retrying. The first-publish command remains available for products without published Claims.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from insurance_harness.bundle.assemble import BundleError, assemble
from insurance_harness.bundle.client import DecisionInput, PlatformClient, PlatformError, Release
from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.catalog.navigation import NavigationError, load_navigation
from insurance_harness.catalog.spot_check import SpotCheckPolicyError, load_spot_check_policy
from insurance_harness.changes import decide_changes
from insurance_harness.changes.options import (
    PublishParser,
    decision_input,
    registry_inputs,
    review_claims,
    review_inputs,
    source_options,
)
from insurance_harness.changes.reporting import summarize, write_reviews
from insurance_harness.changes.sources import publication_entries
from insurance_harness.compilers.schema_fields.claims import claims_from, require_cards_version
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.compilers.schema_fields.page import ProductPage, product_page
from insurance_harness.contracts.bundle import CandidateBundle, ReviewPlan
from insurance_harness.contracts.enums import ReviewMode
from insurance_harness.contracts.knowledge import Claim
from insurance_harness.contracts.navigation import NavigationProfile
from insurance_harness.eval.product_sources import check_product_id, display_name, source_directory
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.weknora_pages import SourcePagesError
from insurance_harness.ingest.registry import RegistryError
from insurance_harness.ingest.source_map import (
    API_KEY_ENV,
    BASE_URL_ENV,
    SourceMapError,
    load_source_map,
    load_trusted_pages,
    reader_from_env,
)
from insurance_harness.ingest.version_metadata import registry_metadata
from insurance_harness.review.routing import Route, Scores, labelled
from insurance_harness.review.spot_check import sample

REPO = Path(__file__).resolve().parents[5]


def delta_bundle(
    claims: tuple[Claim, ...],
    removals: tuple[str, ...],
    active: Release | None,
    page: ProductPage,
    navigation: NavigationProfile,
    review: Route,
    scores: Scores | None,
    compiler_identity: str,
) -> CandidateBundle:
    existing = {member.logical_slug for member in active.members} if active else set()
    return assemble(
        labelled(claims, review, scores),
        compiler_identity=compiler_identity,
        base=active.head if active else None,
        entities=[] if f"entity/{page.entity.entity_id}" in existing else [page.entity],
        profiles=[] if f"presentation/{page.profile.profile_id}" in existing else [page.profile],
        navigations=[] if f"navigation/{navigation.navigation_id}" in existing else [navigation],
        review_plan=[ReviewPlan(mode=review.mode, policy_ref=review.policy_ref)],
        removals=removals,
    )


def main(argv: list[str] | None = None) -> int:
    parser = PublishParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--product", required=True)
    source_options(parser, required=True)
    parser.add_argument("--decide")
    parser.add_argument("--reason")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--route", action="store_true")
    parser.add_argument("--review-policy", type=Path)
    parser.add_argument("--scores", type=Path)
    parser.add_argument("--spot-check-policy", type=Path)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--dry-run", action="store_true")
    try:
        args = parser.parse_args(argv)
        check_product_id(args.product)
        decision = decision_input(args.decide, args.reason)
        policy, scores = review_inputs(args, decision)
    except ValueError:
        return _emit({"stopped": "INVALID_ARGUMENTS"}, 2)
    if args.activate and decision is None:
        return _emit({"stopped": "INVALID_REQUEST"}, 2)
    try:
        spot_check = load_spot_check_policy(args.spot_check_policy) if args.route else None
    except SpotCheckPolicyError as error:
        return _emit({"stopped": error.code}, 2)
    try:
        output = CompileOutput.model_validate_json(
            (args.run_root / args.product / "output.json").read_text(encoding="utf-8"),
        )
    except (OSError, ValueError):
        return _emit({"stopped": "OUTPUT_UNREADABLE"}, 2)
    if output.entity_id != args.product:
        return _emit({"stopped": "OUTPUT_MISMATCH"}, 2)
    registry_map, registered, metadata = None, None, None
    if args.registry:
        try:
            registry_map, facts = registry_inputs(args.registry, [args.product])
            registered = facts[args.product]
            metadata = registry_metadata(args.registry, args.product)
        except RegistryError as error:
            return _emit({"stopped": error.code}, 2)
        if output.pack_id != registered[1]:
            return _emit({"stopped": "OUTPUT_MISMATCH"}, 2)
    summary: dict[str, Any] = {
        "product": args.product,
        "dry_run": args.dry_run,
        "candidate_id": None,
        "decision_id": None,
        "release_id": None,
    }
    try:
        version = require_cards_version(output)
        name = (
            registered[0] if registered else display_name(source_directory(args.repo, args.product))
        )
        page = product_page(
            args.repo / SCHEMA_PACK_CATALOG,
            output.pack_id,
            entity_id=args.product,
            name=name,
            metadata=metadata,
        )
        navigation = load_navigation()
        source_map = registry_map if registry_map is not None else load_source_map(args.source_map)
        # An explicit empty current material set withdraws sourced Claims. A missing product
        # remains an invalid selection; do not confuse omission with withdrawal.
        if args.product not in source_map.products:
            raise SourceMapError("SOURCE_MAP_INVALID")
        entries = publication_entries(source_map.products[args.product], output.materials)
        reader = reader_from_env()
        client = PlatformClient(os.environ[BASE_URL_ENV], os.environ[API_KEY_ENV])
        active = client.active(source_map.space_id)
        pages, sources = load_trusted_pages(reader, source_map.space_id, entries)
        incoming = claims_from(
            output,
            SegmentedSource(
                pages.evidence,
                table_headers=pages.table_headers,
            ),
            sources,
        )
        changes = decide_changes(
            active, args.product, incoming, {entry.knowledge_id for entry in entries}
        )
        summary.update(summarize(changes, active))
        summary.update(
            space_id=source_map.space_id,
            cards_version=version,
            base_release_id=active.id if active else None,
        )
        # No-op is about Claim changes, even when page metadata is missing from Active.
        write_reviews(args.run_root, args.product, changes)
        if summary["no_changes"]:
            return _emit(summary)
        review = review_claims(policy, output.pack_id, list(changes.members), scores)
        summary["review"] = review.mode.value
        if review.reasons:
            summary["reasons"] = list(review.reasons)
        bundle = delta_bundle(
            changes.members,
            changes.removals,
            active,
            page,
            navigation,
            review,
            scores,
            f"harness/schema_fields@{version}",
        )
        summary.update(members=len(bundle.members), removals=len(bundle.removals))
        if args.dry_run:
            return _emit(summary)
        activate = args.activate
        if review.mode == ReviewMode.MACHINE:
            decision = DecisionInput(
                outcome="approve", mode="machine", policy_ref=review.policy_ref
            )
            activate = True
        candidate = client.submit(source_map.space_id, bundle)
        summary.update(candidate_id=candidate.id, candidate_status=candidate.status)
        if decision is not None:
            recorded = client.decide(source_map.space_id, candidate.id, decision)
            summary["decision_id"] = recorded.id
            if activate:
                released = client.activate(source_map.space_id, candidate.id, recorded.id)
                summary.update(release_id=released.id, epoch=released.epoch)
                activated_id = released.id
                released = client.release(source_map.space_id, activated_id)
                digests = {member.logical_slug: member.member_digest for member in released.members}
                if (
                    released.id != activated_id
                    or any(
                        digests.get(member.logical_slug) != member.member_digest
                        for member in bundle.members
                    )
                    or any(slug in digests for slug in bundle.removals)
                ):
                    raise PlatformError("RELEASE_MISMATCH")
                if review.mode == ReviewMode.MACHINE and spot_check is not None:
                    picks = [
                        (pick.slug, pick.stratum) for pick in sample(released, active, spot_check)
                    ]
                    count = 0
                    try:
                        for start in range(0, len(picks), 500):
                            count += len(
                                client.submit_samples(
                                    source_map.space_id,
                                    released.id,
                                    picks[start : start + 500],
                                )
                            )
                        summary["samples"] = count
                    except PlatformError as error:
                        summary["samples"] = {"stopped": error.code}
    except (PlatformError, SourcePagesError, SourceMapError, NavigationError) as error:
        return _emit({**summary, "stopped": error.code}, 2)
    except BundleError as error:
        return _emit({**summary, "stopped": "BUNDLE_INVALID", "reason": error.reason}, 2)
    except (ValidationError, ValueError):
        return _emit({**summary, "stopped": "BUNDLE_INVALID", "reason": "CONVERSION_FAILED"}, 2)
    except OSError:
        return _emit({**summary, "stopped": "LOCAL_IO_FAILED"}, 2)
    return _emit(summary)


def _emit(summary: dict[str, Any], status: int = 0) -> int:
    print(json.dumps(summary, ensure_ascii=False))
    return status


if __name__ == "__main__":
    sys.exit(main())
