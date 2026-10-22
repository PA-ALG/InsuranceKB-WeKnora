"""Entity-level revert (S8b): restore one entity's members from an older release.

    python -m insurance_harness.changes.revert --space S --entity E --to-release R \\
        --reason "<why>" [--activate] [--dry-run]

The candidate carries the entity's members whose digest differs from the active release
(copied unchanged from the older release) and removes the entity's members the older
release did not have. Other entities' later changes stay. A revert is always a person's
decision; the report holds slugs, counts and identifiers only, never member content.
"""

import argparse
import json
import os
import sys
from collections.abc import Iterable
from typing import Any

from insurance_harness.bundle.client import (
    DecisionInput,
    PlatformClient,
    PlatformError,
    Release,
    ReleaseMember,
)
from insurance_harness.contracts.bundle import CONTRACT_VERSION, BundleMember, CandidateBundle
from insurance_harness.contracts.enums import Origin
from insurance_harness.ingest.source_map import API_KEY_ENV, BASE_URL_ENV

IDENTITY = "harness/changes.revert@1"


def _entity_members(members: Iterable[ReleaseMember], entity_id: str) -> dict[str, ReleaseMember]:
    """The entity record and the entity's claims; pages and concepts have their own publishing."""
    owned: dict[str, ReleaseMember] = {}
    for member in members:
        payload = member.payload if isinstance(member.payload, dict) else {}
        if (member.kind == "entity" and payload.get("entity_id") == entity_id) or (
            member.kind == "claim" and payload.get("subject_ref") == entity_id
        ):
            owned[member.logical_slug] = member
    return owned


def revert_bundle(
    active: Release, target: Release, entity_id: str, *, compiler_identity: str
) -> CandidateBundle | None:
    """The delta that makes the entity look as it did in ``target``; None when it already does."""
    now = _entity_members(active.members, entity_id)
    then = _entity_members(target.members, entity_id)
    members = [
        BundleMember(
            kind=old.kind,
            logical_slug=slug,
            payload=old.payload,
            member_digest=old.member_digest,
            evidence_refs=list(old.evidence_refs),
            access_scope=old.access_scope,
        )
        for slug, old in sorted(then.items())
        if slug not in now or now[slug].member_digest != old.member_digest
    ]
    removals = sorted(slug for slug in now if slug not in then)
    if not members and not removals:
        return None
    return CandidateBundle(
        contract_version=CONTRACT_VERSION,
        base_release_id=active.id,
        base_epoch=active.epoch,
        origin=Origin.REVERT,
        members=members,
        removals=removals,
        compiler_identity=compiler_identity,
    )


def _stale_concepts(active: Release, entity_id: str) -> list[str]:
    prefix = entity_id + "/"
    return sorted(
        member.logical_slug
        for member in active.members
        if member.kind == "concept"
        and isinstance(member.payload, dict)
        and isinstance(member.payload.get("based_on"), dict)
        and any(str(key).startswith(prefix) for key in member.payload["based_on"])
    )


def _emit(report: dict[str, Any], status: int = 0) -> int:
    print(json.dumps(report, ensure_ascii=False))
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--space", required=True)
    parser.add_argument("--entity", required=True)
    parser.add_argument("--to-release", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.reason.strip() or not args.entity.strip():
        return _emit({"stopped": "INVALID_ARGUMENTS"}, 2)
    report: dict[str, Any] = {
        "entity": args.entity,
        "to_release": args.to_release,
        "dry_run": args.dry_run,
    }
    try:
        client = PlatformClient(os.environ[BASE_URL_ENV], os.environ[API_KEY_ENV])
    except KeyError:
        return _emit({**report, "stopped": "CONFIGURATION_MISSING"}, 2)
    try:
        active = client.active(args.space)
        if active is None:
            return _emit({**report, "stopped": "NO_ACTIVE_RELEASE"}, 2)
        target = client.release(args.space, args.to_release)
        bundle = revert_bundle(active, target, args.entity, compiler_identity=IDENTITY)
        report.update(
            base_release_id=active.id, stale_concepts=_stale_concepts(active, args.entity)
        )
        if bundle is None:
            return _emit({**report, "no_changes": True})
        report.update(
            no_changes=False,
            members=[m.logical_slug for m in bundle.members],
            removals=list(bundle.removals),
        )
        if args.dry_run:
            return _emit(report)
        candidate = client.submit(args.space, bundle)
        report.update(candidate_id=candidate.id, candidate_status=candidate.status)
        decision = client.decide(
            args.space,
            candidate.id,
            DecisionInput(outcome="approve", mode="human", reason=args.reason.strip()),
        )
        report["decision_id"] = decision.id
        if args.activate:
            released = client.activate(args.space, candidate.id, decision.id)
            check = client.release(args.space, released.id)
            digests = {m.logical_slug: m.member_digest for m in check.members}
            if any(digests.get(m.logical_slug) != m.member_digest for m in bundle.members) or any(
                slug in digests for slug in bundle.removals
            ):
                raise PlatformError("RELEASE_MISMATCH")
            report.update(release_id=released.id, epoch=released.epoch)
    except PlatformError as error:
        return _emit({**report, "stopped": error.code}, 2)
    return _emit(report)


if __name__ == "__main__":
    sys.exit(main())
