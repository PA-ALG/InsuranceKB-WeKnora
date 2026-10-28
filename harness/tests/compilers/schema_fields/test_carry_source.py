"""S12c-4 acceptance (protected, written by Claude): which published claims a recompile may carry
(Spec docs/design/slices/S12c-4-复用已审证据段.md §2.1, §2.4). Only this product's present claims
whose every quote cites a material of this compile with the same knowledge, attempt and sha.
"""

from __future__ import annotations

import hashlib
from typing import Any

from insurance_harness.bundle.client import Release, ReleaseMember
from insurance_harness.compilers.schema_fields.carry import CarriedQuote, CarryRequest, carry_for
from insurance_harness.contracts.enums import ClaimState, LocatorKind, SourceClass, UnknownReason
from insurance_harness.contracts.knowledge import Claim, ClaimValue, Evidence, Locator, Provenance
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.source_ref import SourceRevision

TERMS, BROCHURE = "a" * 64, "b" * 64
PAGES = [
    PageText("terms.pdf", TERMS, 1, "等待期为90日。\n"),
    PageText("terms.pdf", TERMS, 2, "宽限期为60日。\n"),
    PageText("brochure.pdf", BROCHURE, 1, "犹豫期为15日。\n"),
]
REVISIONS = {"terms.pdf": SourceRevision("k-terms", 3), "brochure.pdf": SourceRevision("k-bro", 1)}


def quote(text: str, *, page: int = 1, knowledge: str = "k-terms", attempt: int = 3,
          sha: str = TERMS) -> Evidence:
    return Evidence(
        source_ref=f"source:v1:{knowledge}:{attempt}:{sha}", file_sha256=sha,
        locator=Locator(kind=LocatorKind.PDF_TEXT_SPAN, page=page, start=0, end=len(text)),
        quote=text, access_scope="space",
    )


def expert(text: str) -> Evidence:
    sha = hashlib.sha256(text.encode()).hexdigest()
    return Evidence(
        source_ref=f"expert:v1:rev-1:{sha}", file_sha256=sha,
        locator=Locator(kind=LocatorKind.EXPERT_REVISION, revision_record_id="rev-1"),
        quote=text, access_scope="space",
    )


def claim(predicate: str, value: ClaimValue, *evidence: Evidence, subject: str = "p",
          **attributes: Any) -> Claim:
    state = ClaimState.UNKNOWN if value is None else ClaimState.PRESENT
    return Claim(
        claim_id=f"{subject}/{predicate}", logical_key=f"{subject}/{predicate}",
        subject_ref=subject, predicate=predicate, state=state, value=value,
        evidence=list(evidence),
        origin=attributes.pop("origin", SourceClass.SOURCE_SUPPORTED),
        unknown_reason=UnknownReason.NOT_IN_MATERIAL if state == ClaimState.UNKNOWN else None,
        provenance=Provenance(compiler="schema_fields", compiler_version="cards", model="m"),
        **attributes,
    )


def release(*claims: Claim, extra: list[ReleaseMember] | None = None) -> Release:
    members = [
        ReleaseMember(
            kind="claim", logical_slug=item.logical_key,
            member_digest=hashlib.sha256(item.model_dump_json().encode()).hexdigest(),
            payload=item.model_dump(mode="json"),
        )
        for item in claims
    ]
    return Release(id="rel-9", epoch=9, members=[*members, *(extra or [])])


def carry(active: Release | None) -> Any:
    return carry_for(CarryRequest(active), "p", REVISIONS, PAGES, None)


def test_only_this_products_present_claims_on_unchanged_materials_are_carried() -> None:
    result = carry(release(
        claim("waiting_period", "90日", quote("等待期为90日。"), quote("宽限期为60日。", page=2)),
        claim("cooling_off_period", "15日", quote("犹豫期为15日。", knowledge="k-bro", attempt=1,
                                                  sha=BROCHURE)),
        claim("waiting_period", "30日", quote("等待期为90日。"), subject="other"),
        claim("grace_period", None),
        # A material re-parsed (other attempt) or replaced (other sha) is no longer this
        # compile's material: the whole claim is skipped, never partly carried.
        claim("death_benefit", "保额", quote("等待期为90日。"), quote("宽限期为60日。", attempt=4)),
        claim("premium_term", "10年", quote("等待期为90日。", sha="c" * 64)),
        claim("revised_field", "专家值", expert("专家修订后的取值"),
              origin=SourceClass.EXPERT_REVISION),
    ))
    assert result is not None
    assert result.release_id == "rel-9"
    assert dict(result.quotes) == {
        "waiting_period": (
            CarriedQuote("terms.pdf", 1, "等待期为90日。"),
            CarriedQuote("terms.pdf", 2, "宽限期为60日。"),
        ),
        "cooling_off_period": (CarriedQuote("brochure.pdf", 1, "犹豫期为15日。"),),
    }


def test_unreadable_payloads_and_non_claim_members_are_ignored() -> None:
    junk = [
        ReleaseMember(kind="claim", logical_slug="p/broken", member_digest="0" * 64,
                      payload={"subject_ref": "p", "predicate": "broken"}),
        ReleaseMember(kind="entity", logical_slug="entity/p", member_digest="1" * 64,
                      payload={"entity_id": "p"}),
    ]
    result = carry(release(claim("waiting_period", "90日", quote("等待期为90日。")), extra=junk))
    assert result is not None
    assert set(result.quotes) == {"waiting_period"}


def test_no_active_release_carries_nothing_and_an_empty_carry_has_no_digest() -> None:
    assert carry(None) is None
    empty = carry(release(claim("grace_period", None)))
    assert empty is not None and dict(empty.quotes) == {} and empty.digest is None


def test_the_digest_names_the_carried_quotes_not_the_release() -> None:
    first = carry(release(claim("waiting_period", "90日", quote("等待期为90日。"))))
    again = carry_for(
        CarryRequest(release(claim("waiting_period", "九十日", quote("等待期为90日。")))
                     .model_copy(update={"id": "rel-10", "epoch": 10})),
        "p", REVISIONS, PAGES, None,
    )
    other = carry(release(claim("waiting_period", "60日", quote("宽限期为60日。", page=2))))
    assert first is not None and again is not None and other is not None
    assert first.digest is not None and len(first.digest) == 64
    assert first.digest == again.digest, "the same quotes from a newer release carry the same input"
    assert first.digest != other.digest
