"""Publish the shipped navigation when its version is not the one live (QA3 Spec §3.2).

Product publishes add the navigation only while the Head has none, so a new navigation version
(new question terms, groups or overview fields) needs a candidate of its own. That candidate holds
exactly the navigation member on the current Head and is decided by the machine with the
navigation version as its policy: the navigation carries no product facts, so no field score
applies. A navigation equal to the live one publishes nothing.

The activated release is read back: only a release of this candidate holding the navigation with
the target digest is "published". Past the activation the outcome may already be live, so an
unreadable or mismatched read-back stops as "unknown" and sends nothing more; running the command
again reads the Active first and reports "current" when the navigation did go live.

usage: python -m insurance_harness.catalog.publish_navigation --space ID [--dry-run]

Reads the platform from HARNESS_WEKNORA_BASE_URL / HARNESS_WEKNORA_API_KEY. Prints one JSON line:
{"status": "published" | "current" | "dry_run", "navigation_version": ..., "release_id"?, "epoch"?}
and exits 0, or {"stopped": <code>} — with "status": "unknown" and the candidate id once the
activation was sent — and exits 2.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import NoReturn

from insurance_harness.bundle.assemble import BundleError, assemble
from insurance_harness.bundle.canonical import member_digest
from insurance_harness.bundle.client import DecisionInput, PlatformClient, PlatformError
from insurance_harness.catalog.navigation import NavigationError, load_navigation
from insurance_harness.contracts.bundle import ReviewPlan
from insurance_harness.contracts.enums import ReviewMode
from insurance_harness.ingest.source_map import API_KEY_ENV, BASE_URL_ENV

REASON = "导航与问法词表更新，不含事实"


class _Stopped(Exception):
    def __init__(self, code: str, report: dict[str, object] | None = None) -> None:
        self.code = code
        self.report = report or {}
        super().__init__(code)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _Stopped("INVALID_ARGUMENTS")


def _publish(space: str, dry_run: bool) -> dict[str, object]:
    try:
        navigation = load_navigation()
    except NavigationError as error:
        raise _Stopped(error.code) from None
    payload = navigation.model_dump(mode="json")
    slug = f"navigation/{navigation.navigation_id}"
    digest = member_digest(payload)
    report: dict[str, object] = {"navigation_version": navigation.navigation_version}
    try:
        client = PlatformClient(os.environ.get(BASE_URL_ENV, ""), os.environ.get(API_KEY_ENV, ""))
        active = client.active(space)
        if active is None:
            raise _Stopped("NO_ACTIVE_RELEASE")  # a navigation alone never makes a first release
        live = {member.logical_slug: member.member_digest for member in active.members}
        if live.get(slug) == digest:
            return {"status": "current", **report}
        if dry_run:
            return {"status": "dry_run", **report}
        policy = f"navigation:{navigation.navigation_version}"
        bundle = assemble(
            [],
            compiler_identity=policy,
            base=active.head,
            navigations=[navigation],
            review_plan=[ReviewPlan(mode=ReviewMode.MACHINE, policy_ref=policy)],
        )
        candidate = client.submit(space, bundle)
        decision = client.decide(
            space,
            candidate.id,
            DecisionInput(outcome="approve", mode="machine", policy_ref=policy, reason=REASON),
        )
        receipt = client.activate(space, candidate.id, decision.id)
    except PlatformError as error:
        raise _Stopped(error.code) from None
    except BundleError as error:
        raise _Stopped(error.reason) from None
    unknown = {"status": "unknown", **report, "candidate_id": candidate.id}
    try:
        if receipt.candidate_id != candidate.id:
            raise PlatformError("RELEASE_MISMATCH")
        release = client.release(space, receipt.id)
    except PlatformError as error:
        raise _Stopped(error.code, unknown) from None
    held = {member.logical_slug: member.member_digest for member in release.members}
    if (release.id, release.candidate_id, held.get(slug)) != (receipt.id, candidate.id, digest):
        raise _Stopped("RELEASE_MISMATCH", unknown)
    return {"status": "published", **report, "release_id": release.id, "epoch": release.epoch}


def main(argv: list[str] | None = None) -> int:
    try:
        parser = _Parser(description=__doc__)
        parser.add_argument("--space", required=True)
        parser.add_argument("--dry-run", action="store_true")
        args = parser.parse_args(argv)
        result = _publish(args.space, args.dry_run)
    except _Stopped as stopped:
        print(json.dumps({"stopped": stopped.code, **stopped.report}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
