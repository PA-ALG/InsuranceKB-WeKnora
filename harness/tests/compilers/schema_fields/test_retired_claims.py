"""S5a acceptance: republishing a product replaces it whole, nothing of it lingers (Spec §2.1).

Protected file: written by Claude. A candidate is a delta: activation keeps every base member the
bundle does not list under removals. So a claim of this product that the new compile no longer
yields must be removed explicitly, while other products' claims and the shared entity and profile
members are never touched. A removal that overlaps a member, repeats or is blank is refused before
anything is sent, as the platform would refuse it.
"""

from __future__ import annotations

from typing import Any

import pytest

from insurance_harness.bundle.assemble import BundleError, retired_claims
from insurance_harness.bundle.client import Head, Release, ReleaseMember
from insurance_harness.compilers.schema_fields.claims import candidate_bundle
from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision

SHA = "ab" * 32


def member(kind: str, slug: str, payload: Any) -> ReleaseMember:
    return ReleaseMember(kind=kind, logical_slug=slug, member_digest="d" * 64, payload=payload)


def claim(subject: str, predicate: str) -> ReleaseMember:
    return member(
        "claim", f"{subject}/{predicate}", {"subject_ref": subject, "predicate": predicate}
    )


ACTIVE = Release(
    id="rel_1",
    epoch=3,
    members=[
        member("entity", "entity/P1", {"entity_id": "P1"}),
        member("presentation_profile", "presentation/profile_a", {"profile_id": "profile_a"}),
        claim("P1", "waiting_period"),
        claim("P1", "premium_grace_period"),
        claim("P1", "old_field"),
        claim("P2", "waiting_period"),
        member("claim", "P1/odd", "not an object"),
    ],
)


def test_only_this_products_claims_that_are_gone_are_retired() -> None:
    keep = {"P1/waiting_period", "P1/premium_grace_period"}
    assert retired_claims(ACTIVE, "P1", keep) == ["P1/old_field"]
    assert retired_claims(ACTIVE, "P1", set()) == [
        "P1/old_field",
        "P1/premium_grace_period",
        "P1/waiting_period",
    ]
    assert retired_claims(ACTIVE, "P2", set()) == ["P2/waiting_period"]
    assert retired_claims(ACTIVE, "P3", set()) == []
    assert retired_claims(None, "P1", set()) == []


class Page:
    def __init__(self) -> None:
        self.document, self.document_sha256, self.page = "保险条款.pdf", SHA, 1
        self.text = "1.4 等待期\n自本合同生效之日起90日内为等待期。\n"


SOURCE = SegmentedSource([Page()])
SOURCES = {"保险条款.pdf": SourceRevision(knowledge_id="k-1", parse_attempt=2)}
OUTPUT = CompileOutput(
    pack_id="pack",
    entity_id="P1",
    model="m",
    fields=[
        FieldResult(
            field_key="waiting_period",
            state="present",
            value="90日",
            evidence=SOURCE.evidence(["D1P1S1"]),
            segment_ids=["D1P1S1"],
        )
    ],
    cards_version="cards-x",
)


def bundle(removals: list[str]) -> Any:
    return candidate_bundle(
        OUTPUT,
        SOURCE,
        SOURCES,
        compiler_identity="harness/schema_fields@cards-x",
        base=Head(release_id="rel_1", epoch=3),
        removals=removals,
    )


def test_the_bundle_carries_the_removals() -> None:
    built = bundle(["P1/old_field", "P1/premium_grace_period"])
    assert built.removals == ["P1/old_field", "P1/premium_grace_period"]
    assert [m.logical_slug for m in built.members] == ["P1/waiting_period"]
    assert bundle([]).removals == []


@pytest.mark.parametrize(
    "removals",
    [["P1/waiting_period"], ["P1/old_field", "P1/old_field"], [" "], [""]],
    ids=["overlaps a member", "repeated", "blank", "empty"],
)
def test_a_bad_removal_is_refused_before_anything_is_sent(removals: list[str]) -> None:
    with pytest.raises(BundleError) as refused:
        bundle(removals)
    assert refused.value.reason == "REMOVAL_OVERLAP"
