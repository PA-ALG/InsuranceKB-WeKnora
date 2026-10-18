"""RV4c acceptance: stratified sampling of newly published machine-reviewed claims (Spec §2.3).

Protected file: written by Claude. Only claims that went live as machine review in this release
(new, or changed since the base release) are sampled: an unchanged claim was sampled with the
release that introduced it. Each pack has a must-check layer, taken whole, and a rest layer sampled
by rate with a minimum; the release id seeds the draw, so the same release gives the same sample.
"""

from __future__ import annotations

from typing import Any

from insurance_harness.bundle.client import Release, ReleaseMember
from insurance_harness.catalog.spot_check import PackRule, SpotCheckPolicy
from insurance_harness.review.spot_check import Pick, sample


def member(kind: str, slug: str, payload: dict[str, Any], digest: str = "d") -> ReleaseMember:
    return ReleaseMember(kind=kind, logical_slug=slug, member_digest=digest * 64, payload=payload)


def claim(entity: str, field: str, mode: str = "machine", digest: str = "d") -> ReleaseMember:
    return member(
        "claim",
        f"{entity}/{field}",
        {
            "subject_ref": entity,
            "predicate": field,
            "state": "present",
            "value": "v",
            "review": {"mode": mode},
        },
        digest,
    )


def entity(entity_id: str, label: str) -> ReleaseMember:
    return member(
        "entity",
        f"entity/{entity_id}",
        {"entity_id": entity_id, "names": [entity_id], "classification_labels": [label]},
    )


def profile(pack: str, label: str) -> ReleaseMember:
    return member(
        "presentation_profile",
        f"presentation/profile_{pack}",
        {
            "profile_id": f"profile_{pack}",
            "schema_pack_id": pack,
            "classification_labels": [label],
            "sections": [],
        },
    )


def release(release_id: str, claims: list[ReleaseMember]) -> Release:
    structure = [
        profile("ci", "ci_label"),
        profile("med", "med_label"),
        entity("P1", "ci_label"),
        entity("P2", "med_label"),
        entity("P9", "other"),
    ]
    return Release(id=release_id, epoch=2, members=[*structure, *claims])


def rule(rate: float, minimum: int, must: list[str] | None = None) -> PackRule:
    return PackRule(rate=rate, minimum=minimum, target=0.9, must_check=must or [])


POLICY = SpotCheckPolicy(
    version="t",
    default=rule(1.0, 0),
    packs={"ci": rule(0.5, 3, ["exclusions"]), "med": rule(0.0, 1)},
)


def test_only_claims_new_or_changed_as_machine_review_are_sampled() -> None:
    base = release("rel-1", [claim("P1", "a"), claim("P1", "b"), claim("P2", "c")])
    current = release(
        "rel-2",
        [
            claim("P1", "a"),  # unchanged since the base: sampled with the base already
            claim("P1", "b", digest="e"),  # changed
            claim("P1", "c"),  # new
            claim("P1", "h", mode="human"),  # a person decided it
            claim("P2", "c"),
        ],
    )
    assert {pick.slug for pick in sample(current, base, POLICY)} == {"P1/b", "P1/c"}
    assert {pick.slug for pick in sample(current, None, POLICY)} >= {"P2/c"}


def test_each_pack_takes_its_must_check_layer_whole_and_samples_the_rest() -> None:
    claims = [
        claim("P1", "exclusions"),
        *(claim("P1", f"f{i}") for i in range(10)),
        *(claim("P2", f"g{i}") for i in range(4)),
        claim("P9", "z"),
    ]
    picks = sample(release("rel-7", claims), None, POLICY)
    by_stratum: dict[str, list[str]] = {}
    for pick in picks:
        by_stratum.setdefault(pick.stratum, []).append(pick.slug)
    assert by_stratum["ci/must"] == ["P1/exclusions"]
    assert len(by_stratum["ci/rest"]) == 5  # max(3 - 1, ceil(0.5 * 10))
    assert len(by_stratum["med/rest"]) == 1  # rate 0 still meets the minimum
    assert by_stratum["unassigned/rest"] == ["P9/z"]  # no pack: the default rule
    assert [pick.slug for pick in picks] == sorted(pick.slug for pick in picks)


def test_the_release_id_seeds_a_reproducible_draw() -> None:
    claims = [claim("P1", f"f{i}") for i in range(20)]
    first = sample(release("rel-7", claims), None, POLICY)
    again = sample(release("rel-7", list(reversed(claims))), None, POLICY)
    assert first == again and all(isinstance(pick, Pick) for pick in first)


def test_a_small_layer_is_taken_whole() -> None:
    picks = sample(release("rel-7", [claim("P1", "f1"), claim("P1", "f2")]), None, POLICY)
    assert [pick.slug for pick in picks] == ["P1/f1", "P1/f2"]
