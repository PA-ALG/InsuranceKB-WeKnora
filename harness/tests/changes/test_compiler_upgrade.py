"""S12c-1b acceptance (protected, written by Claude): a compiler upgrade reaches review.

Spec docs/design/slices/S12c-1b-编译器升级的变更判定.md. With unchanged materials, a different
value from the same compiler identity stays KEEP (the S8 churn guard); from a different compiler
identity it becomes UPGRADE and is published like SUPERSEDE, so review decides.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from insurance_harness.bundle.assemble import BundleError
from insurance_harness.bundle.client import Release, ReleaseMember
from insurance_harness.changes import Verdict, decide_changes
from insurance_harness.changes.reporting import summarize
from insurance_harness.compilers.schema_fields.claims import compiler_version
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.contracts.enums import (
    ClaimState,
    LocatorKind,
    SourceClass,
    UnknownReason,
)
from insurance_harness.contracts.knowledge import (
    Claim,
    ClaimValue,
    Evidence,
    Locator,
    Maintenance,
    Provenance,
)

OLD = "cards-2026-10-18a"
NEW = "cards-2026-10-18a+value:2026-10-27.1"
ENTITY = "p1"


def proof(document: str, quote: str) -> Evidence:
    fingerprint = hashlib.sha256(document.encode()).hexdigest()
    return Evidence(
        source_ref=f"source:v1:{document}:1:{fingerprint}",
        file_sha256=fingerprint,
        locator=Locator(kind=LocatorKind.PDF_TEXT_SPAN, page=1, start=0, end=len(quote)),
        quote=quote,
        access_scope="space",
    )


def claim(
    value: ClaimValue,
    *evidence: Evidence,
    identity: str,
    predicate: str = "waiting_period",
    **attributes: Any,
) -> Claim:
    state = ClaimState.UNKNOWN if value is None else ClaimState.PRESENT
    return Claim(
        claim_id=f"{ENTITY}/{predicate}",
        logical_key=f"{ENTITY}/{predicate}",
        subject_ref=ENTITY,
        predicate=predicate,
        state=state,
        value=value,
        evidence=list(evidence),
        origin=SourceClass.SOURCE_SUPPORTED,
        unknown_reason=UnknownReason.NOT_IN_MATERIAL if state == ClaimState.UNKNOWN else None,
        provenance=Provenance(compiler="schema_fields", compiler_version=identity, model="m"),
        **attributes,
    )


def released(*claims: Claim) -> Release:
    return Release(
        id="release-base",
        epoch=7,
        members=[
            ReleaseMember(
                kind="claim",
                logical_slug=item.logical_key,
                member_digest=hashlib.sha256(item.model_dump_json().encode()).hexdigest(),
                payload=item.model_dump(mode="json"),
            )
            for item in claims
        ],
    )


def live(value: ClaimValue = "等待期90日", **attributes: Any) -> Claim:
    evidence = [proof("terms", "等待期为90日")] if value is not None else []
    return claim(
        value,
        *evidence,
        identity=OLD,
        maintenance=Maintenance(revision_no=2),
        **attributes,
    )


def verdict_of(base: Claim, incoming: Claim | None, current: set[str]) -> Verdict:
    changes = decide_changes(released(base), ENTITY, [incoming] if incoming else [], current)
    [item] = changes.items
    return item.verdict


def test_a_different_value_from_an_upgraded_compiler_is_an_upgrade_published_like_supersede() -> (
    None
):
    incoming = claim("等待期180日", proof("terms", "等待期为180日"), identity=NEW)
    changes = decide_changes(released(live()), ENTITY, [incoming], {"terms"})
    [item] = changes.items
    assert item.verdict == Verdict.UPGRADE
    assert item.reason == "upgrade"
    [member] = changes.members
    assert member.value == "等待期180日"
    assert member.maintenance.revision_no == 3, "an upgrade is a revision, like supersede"
    assert member.maintenance.reason == "upgrade"
    assert not changes.removals and not changes.review_items
    assert summarize(changes, released(live()))["counts"]["upgrade"] == 1


def test_an_upgraded_compiler_answering_unknown_is_also_sent_to_review() -> None:
    incoming = claim(None, identity=NEW)
    changes = decide_changes(released(live()), ENTITY, [incoming], {"terms"})
    assert [item.verdict for item in changes.items] == [Verdict.UPGRADE]
    [member] = changes.members
    assert member.state == ClaimState.UNKNOWN
    assert member.maintenance.reason == "upgrade"


@pytest.mark.parametrize(
    ("incoming", "current", "expected"),
    [
        (
            claim("等待期180日", proof("terms", "等待期为180日"), identity=OLD),
            {"terms"},
            Verdict.KEEP,
        ),
        (claim(None, identity=OLD), {"terms"}, Verdict.KEEP),
        (
            claim("等待期180日", proof("rider", "等待期为180日"), identity=OLD),
            {"terms", "rider"},
            Verdict.CONFLICT,
        ),
    ],
    ids=["churn", "churn-to-unknown", "new-material"],
)
def test_the_same_compiler_identity_keeps_the_churn_guard(
    incoming: Claim,
    current: set[str],
    expected: Verdict,
) -> None:
    assert verdict_of(live(), incoming, current) == expected


def test_an_upgrade_never_overrides_an_expert_lock() -> None:
    incoming = claim("等待期180日", proof("terms", "等待期为180日"), identity=NEW)
    assert verdict_of(live(expert_lock=True), incoming, {"terms"}) == Verdict.CONFLICT


def test_new_material_with_an_upgrade_stays_a_conflict() -> None:
    incoming = claim("等待期180日", proof("rider", "等待期为180日"), identity=NEW)
    assert verdict_of(live(), incoming, {"terms", "rider"}) == Verdict.CONFLICT


@pytest.mark.parametrize(
    ("base", "incoming", "current", "expected"),
    [
        (
            live(),
            claim("等待期180日", proof("terms2", "等待期为180日"), identity=NEW),
            {"terms2"},
            Verdict.SUPERSEDE,
        ),
        (live(), None, set(), Verdict.RETRACT),
        (
            live(None),
            claim("等待期180日", proof("terms", "等待期为180日"), identity=NEW),
            {"terms"},
            Verdict.FILL,
        ),
        (
            live(),
            claim("等待期90日", proof("terms", "等待期为90日"), identity=NEW),
            {"terms"},
            Verdict.UNCHANGED,
        ),
    ],
    ids=["withdrawn", "retracted", "fill", "equivalent"],
)
def test_other_rules_are_unchanged_by_an_upgrade(
    base: Claim,
    incoming: Claim | None,
    current: set[str],
    expected: Verdict,
) -> None:
    assert verdict_of(base, incoming, current) == expected


def output(cards: str | None, protocol: str | None) -> CompileOutput:
    return CompileOutput(
        pack_id="medical",
        entity_id=ENTITY,
        model="m",
        cards_version=cards,
        value_protocol=protocol,
    )


def test_the_compiler_identity_joins_the_card_version_and_the_value_protocol() -> None:
    assert compiler_version(output("cards-a", "2026-10-27.1")) == "cards-a+value:2026-10-27.1"
    assert compiler_version(output("cards-a", None)) == "cards-a", (
        "earlier outputs publish as before"
    )
    assert compiler_version(output(" cards-a ", " ")) == "cards-a"
    with pytest.raises(BundleError) as error:
        compiler_version(output("  ", "2026-10-27.1"))
    assert error.value.reason == "CARDS_VERSION_UNKNOWN"


def test_the_churn_guard_resumes_once_a_claim_is_published_under_the_new_identity() -> None:
    """#397 R2: until first published under the new identity, a claim may upgrade again."""
    first = claim("等待期90日", proof("terms", "等待期为90日"), identity=NEW)
    assert verdict_of(live(), first, {"terms"}) == Verdict.UNCHANGED
    later = claim("等待期180日", proof("terms", "等待期为180日"), identity=NEW)
    assert verdict_of(live(), later, {"terms"}) == Verdict.UPGRADE
    published = decide_changes(released(live()), ENTITY, [later], {"terms"}).members[0]
    churn = claim("等待期一百八十日", proof("terms", "等待期为一百八十日"), identity=NEW)
    assert verdict_of(published, churn, {"terms"}) == Verdict.KEEP
