"""S8b acceptance (protected, written by Claude): reverting one entity to an older release copies
that entity's older members and removes the ones the older release did not have, leaving every
other entity's later changes alone (Spec docs/design/slices/S8b-自动变基与实体回退.md §4).
RED until S8b: insurance_harness.changes.revert is missing.
"""

import hashlib
import json
from typing import Any

from insurance_harness.bundle.client import Release, ReleaseMember
from insurance_harness.changes.revert import revert_bundle
from insurance_harness.contracts.enums import Origin


def member(kind: str, slug: str, payload: dict[str, Any]) -> ReleaseMember:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return ReleaseMember(
        kind=kind,
        logical_slug=slug,
        member_digest=digest,
        payload=payload,
        evidence_refs=[f"source:v1:k-{slug.replace('/', '-')}:1:" + "a" * 64],
        access_scope="space",
    )


def claim(slug: str, value: str) -> ReleaseMember:
    subject, predicate = slug.split("/")
    return member("claim", slug, {"subject_ref": subject, "predicate": predicate, "value": value})


ENTITY_A = member("entity", "entity/A", {"entity_id": "A", "names": ["甲"]})
R1 = Release(
    id="rel-1",
    epoch=1,
    members=[
        ENTITY_A,
        claim("A/f1", "v1"),
        claim("A/f2", "v1"),
        claim("B/f1", "v1"),
    ],
)
R2 = Release(
    id="rel-2",
    epoch=2,
    members=[
        ENTITY_A,
        claim("A/f1", "v2"),
        claim("A/f2", "v1"),
        claim("A/f3", "new"),
        claim("B/f1", "v2"),
    ],
)


def test_reverting_one_entity_restores_its_old_members_and_keeps_the_others() -> None:
    bundle = revert_bundle(R2, R1, "A", compiler_identity="harness/revert@test")
    assert bundle is not None
    assert bundle.origin == Origin.REVERT
    assert (bundle.base_release_id, bundle.base_epoch) == ("rel-2", 2)
    members = {m.logical_slug: m for m in bundle.members}
    assert set(members) == {"A/f1"}, "only members that differ from the active release are sent"
    old = next(m for m in R1.members if m.logical_slug == "A/f1")
    assert members["A/f1"].payload == old.payload
    assert members["A/f1"].member_digest == old.member_digest
    assert list(members["A/f1"].evidence_refs) == old.evidence_refs
    assert bundle.removals == ["A/f3"]


def test_an_entity_that_did_not_change_needs_no_revert() -> None:
    assert revert_bundle(R2, R1, "B", compiler_identity="harness/revert@test") is not None
    unchanged = Release(id="rel-3", epoch=3, members=list(R2.members))
    assert revert_bundle(unchanged, R2, "A", compiler_identity="harness/revert@test") is None
