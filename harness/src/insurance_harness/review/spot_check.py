"""Stratified spot-check sampling of what a release brought live as machine review (RV4 Spec §2.3).

The sample covers the machine-reviewed claims a release brought live: new since its base release,
or with a different member digest. An unchanged claim was sampled with the release that introduced
it, so it is not drawn again. The release itself says which pack an entry belongs to: the profile
whose classification labels meet the entry's; a claim of no pack is drawn by the default rule as
"unassigned/rest". Each pack has a must-check layer, taken whole, and a
rest layer drawn by rate with a minimum; the release id and pack seed the draw, so the same release
under the same policy always gives the same sample. Generic over packs and fields: they are data.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from insurance_harness.bundle.client import Release, ReleaseMember
from insurance_harness.catalog.spot_check import SpotCheckPolicy

UNASSIGNED = "unassigned"


@dataclass(frozen=True)
class Pick:
    slug: str
    stratum: str  # "<pack>/must" or "<pack>/rest", opaque to the platform


def _payload(member: ReleaseMember) -> dict[str, object]:
    return member.payload if isinstance(member.payload, dict) else {}


def _strings(value: object) -> set[str]:
    return {item for item in value if isinstance(item, str)} if isinstance(value, list) else set()


def _packs_by_entity(release: Release) -> dict[str, str]:
    profiles = [
        (_strings(_payload(m).get("classification_labels")), _payload(m).get("schema_pack_id"))
        for m in release.members
        if m.kind == "presentation_profile"
    ]
    packs: dict[str, str] = {}
    for member in release.members:
        if member.kind != "entity":
            continue
        payload = _payload(member)
        labels = _strings(payload.get("classification_labels"))
        pack = next((p for wanted, p in profiles if wanted & labels and isinstance(p, str)), None)
        entity_id = payload.get("entity_id")
        if isinstance(entity_id, str) and pack:
            packs[entity_id] = pack
    return packs


def _machine(member: ReleaseMember) -> bool:
    review = _payload(member).get("review")
    return member.kind == "claim" and isinstance(review, dict) and review.get("mode") == "machine"


def sample(release: Release, base: Release | None, policy: SpotCheckPolicy) -> list[Pick]:
    """The release's spot-check picks, ordered by slug."""
    before = {m.logical_slug: m.member_digest for m in base.members} if base else {}
    packs = _packs_by_entity(release)
    layers: dict[str, list[str]] = {}
    for member in release.members:
        if not _machine(member) or before.get(member.logical_slug) == member.member_digest:
            continue
        subject = _payload(member).get("subject_ref")
        pack = packs.get(subject, UNASSIGNED) if isinstance(subject, str) else UNASSIGNED
        layers.setdefault(pack, []).append(member.logical_slug)
    picks: list[Pick] = []
    claims = {m.logical_slug: _payload(m) for m in release.members if m.kind == "claim"}
    for pack, slugs in layers.items():
        rule = policy.for_pack(pack) if pack != UNASSIGNED else policy.default
        # Without a pack no field list applies: an unassigned claim is always "unassigned/rest".
        must_check = set(rule.must_check) if pack != UNASSIGNED else set()
        must = sorted(s for s in slugs if claims[s].get("predicate") in must_check)
        rest = sorted(set(slugs) - set(must))
        wanted = max(rule.minimum - len(must), math.ceil(rule.rate * len(rest)))
        drawn = random.Random(f"{release.id}/{pack}").sample(rest, min(len(rest), wanted))
        picks += [Pick(slug, f"{pack}/must") for slug in must]
        picks += [Pick(slug, f"{pack}/rest") for slug in drawn]
    return sorted(picks, key=lambda pick: pick.slug)
