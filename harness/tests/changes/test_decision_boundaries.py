"""Additional S8a core boundaries, independent of the frozen acceptance fixture."""

import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest

from insurance_harness.bundle.client import Release, ReleaseMember
from insurance_harness.changes import Verdict, decide_changes
from insurance_harness.changes.normalize import values_equal
from insurance_harness.contracts.enums import (
    ClaimState,
    LocatorKind,
    SourceClass,
    UnknownReason,
)
from insurance_harness.contracts.knowledge import Claim, ClaimValue, Evidence, Locator, Maintenance


def proof(document: str, quote: str = "依据", attempt: int = 1) -> Evidence:
    fingerprint = hashlib.sha256(document.encode()).hexdigest()
    return Evidence(
        source_ref=f"source:v1:{document}:{attempt}:{fingerprint}",
        file_sha256=fingerprint,
        locator=Locator(kind=LocatorKind.PDF_TEXT_SPAN, page=1, start=0, end=len(quote)),
        quote=quote,
        access_scope="space",
    )


def claim(
    entity: str,
    predicate: str,
    value: ClaimValue,
    *evidence: Evidence,
    state: ClaimState | None = None,
    **attributes: Any,
) -> Claim:
    state = state or (ClaimState.UNKNOWN if value is None else ClaimState.PRESENT)
    return Claim(
        claim_id=f"{entity}/{predicate}",
        logical_key=f"{entity}/{predicate}",
        subject_ref=entity,
        predicate=predicate,
        state=state,
        value=value,
        evidence=list(evidence),
        origin=SourceClass.SOURCE_SUPPORTED,
        unknown_reason=UnknownReason.NOT_IN_MATERIAL if state == ClaimState.UNKNOWN else None,
        **attributes,
    )


def released(*claims: Claim, slugs: tuple[str, ...] | None = None) -> Release:
    return Release(
        id="release-base",
        epoch=3,
        members=[
            ReleaseMember(
                kind="claim",
                logical_slug=slugs[index] if slugs else item.logical_key,
                member_digest=hashlib.sha256(item.model_dump_json().encode()).hexdigest(),
                payload=item.model_dump(mode="json"),
            )
            for index, item in enumerate(claims)
        ],
    )


@pytest.mark.parametrize(("left", "right", "expected"), [
    (1000000, "100万元", True), (0.85, "85%", True), (1, 1.0, True),
    (9007199254740993, "9007199254740992", False),
    (True, True, True), (True, 1, False), (False, 0, False), (True, "true", False),
    ([" Ａ ", "90 日"], ["a", "90日"], True),
    (["A", "B"], ["B", "A"], False), (["A", "A"], ["A"], False),
    (["A"], "['A']", False), ([], [], True), (None, None, True),
])
def test_typed_values_compare_without_collapsing_types(
    left: ClaimValue, right: ClaimValue, expected: bool,
) -> None:
    assert values_equal(left, right) is expected
    assert values_equal(right, left) is expected


@pytest.mark.parametrize(("entity", "field", "old", "new"), [
    ("health", "benefits", ["住院", "门诊"], ["住院", "门诊", "急诊"]),
    ("endowment", "participating", False, True),
])
def test_two_product_structures_use_the_same_conflict_rule_and_actual_member_slug(
    entity: str, field: str, old: ClaimValue, new: ClaimValue,
) -> None:
    base = claim(entity, field, old, proof("brochure", "旧说法"))
    incoming = claim(entity, field, new, proof("new-terms", "新说法"))
    result = decide_changes(released(base, slugs=("published/field",)), entity, [incoming],
                            {"brochure", "new-terms"})
    assert result.items[0].verdict == Verdict.CONFLICT
    assert result.items[0].base_slug == "published/field"
    assert not result.members and not result.removals
    review = result.review_items[0]
    assert review.target == "published/field"
    assert review.evidence == sorted({base.evidence[0].quote_sha256,
                                      incoming.evidence[0].quote_sha256})
    expected = '["住院","门诊","急诊"]' if isinstance(new, list) else "true"
    assert review.resolution_candidate == expected


def test_new_document_is_relative_to_every_base_claim_of_the_product() -> None:
    limit = claim("health", "limit", "1万元", proof("brochure", "旧上限"))
    # This document is new for limit, but already supports another claim in the product.
    waiting = claim("health", "waiting", "30日", proof("terms", "等待期"))
    incoming = claim("health", "limit", "2万元", proof("terms", "新上限"))
    result = decide_changes(released(limit, waiting), "health", [incoming],
                            {"brochure", "terms"})
    assert {item.logical_key: item.verdict for item in result.items} == {
        "health/limit": Verdict.KEEP, "health/waiting": Verdict.KEEP,
    }
    assert not result.members and not result.review_items


def test_another_products_document_remains_new_for_the_selected_product() -> None:
    base = claim("health", "limit", "1万元", proof("brochure", "旧上限"))
    unrelated = claim("endowment", "participating", True, proof("shared", "有分红"))
    incoming = claim("health", "limit", "2万元", proof("shared", "新上限"))
    result = decide_changes(released(base, unrelated), "health", [incoming],
                            {"brochure", "shared"})
    assert [(item.logical_key, item.verdict) for item in result.items] == [
        ("health/limit", Verdict.CONFLICT),
    ]


def test_parse_attempt_changes_do_not_make_a_new_document() -> None:
    base = claim("health", "waiting", "30日", proof("terms", "旧说法"))
    incoming = claim("health", "waiting", "60日", proof("terms", "新说法", attempt=9))
    result = decide_changes(released(base), "health", [incoming], {"terms"})
    assert result.items[0].verdict == Verdict.KEEP


@pytest.mark.parametrize(("locked", "same", "expected"), [
    (False, False, Verdict.SUPERSEDE), (True, False, Verdict.CONFLICT),
    (False, True, Verdict.REFRESH), (True, True, Verdict.REFRESH),
])
def test_withdrawal_and_expert_lock_rule_precedence(
    locked: bool, same: bool, expected: Verdict,
) -> None:
    base = claim("health", "waiting", "30日", proof("old", "旧说法"), expert_lock=locked)
    incoming = claim("health", "waiting", "30 日" if same else "60日",
                     proof("current", "新说法"))
    result = decide_changes(released(base), "health", [incoming], {"current"})
    assert result.items[0].verdict == expected


def test_refresh_keeps_expert_lock_when_compiler_does_not_repeat_it() -> None:
    base = claim("health", "waiting", "30日", proof("old"), expert_lock=True)
    incoming = claim("health", "waiting", "30 日", proof("current"))
    result = decide_changes(released(base), "health", [incoming], {"current"})
    assert result.items[0].verdict == Verdict.REFRESH
    assert result.members[0].expert_lock
    assert not incoming.expert_lock


def test_state_must_match_even_when_both_values_are_none_and_quotes_match() -> None:
    base = claim("health", "excluded", None, proof("current"),
                 state=ClaimState.ABSENT_EXPLICITLY)
    incoming = claim("health", "excluded", None)
    result = decide_changes(released(base), "health", [incoming], {"current"})
    assert result.items[0].verdict == Verdict.KEEP
    reverse = decide_changes(released(incoming), "health", [base], {"current"})
    assert reverse.items[0].verdict == Verdict.FILL


def test_identical_nonempty_quote_sets_make_reworded_values_equivalent() -> None:
    base = claim("health", "benefit", "医疗费用", proof("old", "同一原文"))
    incoming = claim("health", "benefit", "住院期间合理支出", proof("current", "同一原文"),
                     proof("current", "同一原文"))
    result = decide_changes(released(base), "health", [incoming], {"current"})
    assert result.items[0].verdict == Verdict.REFRESH


@pytest.mark.parametrize("base_uppercase", [False, True])
def test_quote_hash_hex_case_does_not_change_equivalence_or_mutate_claims(
    base_uppercase: bool,
) -> None:
    old_proof, new_proof = proof("brochure", "同一原文"), proof("new", "同一原文")
    if base_uppercase:
        old_proof = old_proof.model_copy(update={"quote_sha256": old_proof.quote_sha256.upper()})
    else:
        new_proof = new_proof.model_copy(update={"quote_sha256": new_proof.quote_sha256.upper()})
    base = claim("health", "benefit", "医疗费用", old_proof)
    incoming = claim("health", "benefit", "住院期间合理支出", new_proof)
    before = (base.model_dump_json(), incoming.model_dump_json())
    result = decide_changes(released(base), "health", [incoming], {"brochure", "new"})
    assert result.items[0].verdict == Verdict.UNCHANGED
    assert not result.members and not result.review_items
    assert (base.model_dump_json(), incoming.model_dump_json()) == before


def test_review_quote_hash_union_deduplicates_hex_case_and_keeps_a_stable_identity() -> None:
    shared_old, shared_new = proof("brochure", "共同依据"), proof("new", "共同依据")
    shared_old = shared_old.model_copy(update={"quote_sha256": shared_old.quote_sha256.upper()})
    old_proof, new_proof = proof("brochure", "旧依据"), proof("new", "新依据")
    new_proof = new_proof.model_copy(update={"quote_sha256": new_proof.quote_sha256.upper()})
    base = claim("health", "benefit", "旧值", shared_old, old_proof)
    incoming = claim("health", "benefit", "新值", shared_new, new_proof)
    before = (base.model_dump_json(), incoming.model_dump_json())
    mixed = decide_changes(released(base), "health", [incoming], {"brochure", "new"})
    expected = sorted({item.quote_sha256.lower() for item in (*base.evidence, *incoming.evidence)})
    assert mixed.review_items[0].evidence == expected
    assert len(mixed.review_items[0].evidence) == 3
    normalized_base = base.model_copy(update={"evidence": [
        item.model_copy(update={"quote_sha256": item.quote_sha256.lower()})
        for item in base.evidence
    ]})
    normalized_incoming = incoming.model_copy(update={"evidence": [
        item.model_copy(update={"quote_sha256": item.quote_sha256.lower()})
        for item in incoming.evidence
    ]})
    lower = decide_changes(released(normalized_base), "health", [normalized_incoming],
                           {"brochure", "new"})
    assert mixed.review_items == lower.review_items
    assert (base.model_dump_json(), incoming.model_dump_json()) == before


def test_no_incoming_retracts_only_fully_withdrawn_unlocked_evidence() -> None:
    gone = claim("health", "gone", "旧值", proof("withdrawn"))
    mixed = claim("health", "mixed", "仍有效", proof("withdrawn"), proof("current"))
    locked = claim("health", "locked", "专家值", proof("withdrawn"), expert_lock=True)
    unknown = claim("health", "unknown", None)
    result = decide_changes(released(mixed, unknown, gone, locked), "health", [], {"current"})
    assert [(item.logical_key, item.verdict) for item in result.items] == [
        ("health/gone", Verdict.RETRACT), ("health/locked", Verdict.KEEP),
        ("health/mixed", Verdict.KEEP), ("health/unknown", Verdict.KEEP),
    ]
    assert list(result.removals) == ["health/gone"]


def test_new_unknown_fields_are_published_and_input_maintenance_is_not_reused() -> None:
    stale = Maintenance(revision_no=8, first_release_id="wrong", last_changed_release_id="wrong")
    incoming = claim("endowment", "unknown", None, maintenance=stale)
    result = decide_changes(released(), "endowment", [incoming], set())
    assert result.items[0].verdict == Verdict.ADD
    maintenance = result.members[0].maintenance
    assert maintenance.revision_no == 0
    assert maintenance.first_release_id is None
    assert maintenance.last_changed_release_id is None
    assert maintenance.reason == "add"
    timestamp = datetime.fromisoformat(maintenance.changed_at or "")
    assert timestamp.utcoffset() == UTC.utcoffset(timestamp)
    assert incoming.maintenance == stale


def test_no_active_release_adds_present_and_unknown_claims_without_inventing_a_head() -> None:
    incoming = [claim("endowment", "participating", True, proof("current")),
                claim("endowment", "cash_value", None)]
    result = decide_changes(None, "endowment", incoming, {"current"})
    assert [item.verdict for item in result.items] == [Verdict.ADD, Verdict.ADD]
    assert all(item.base_slug is None for item in result.items)
    assert {item.logical_key for item in result.members} == {
        "endowment/participating", "endowment/cash_value",
    }
    assert all(item.maintenance.first_release_id is None for item in result.members)
    assert not result.removals and not result.review_items


def test_fill_preserves_first_release_and_discards_incoming_release_metadata() -> None:
    base = claim("endowment", "cash_value", None,
                 maintenance=Maintenance(revision_no=3, first_release_id="first"))
    incoming = claim("endowment", "cash_value", 5000, proof("current"),
                     maintenance=Maintenance(revision_no=99, last_changed_release_id="wrong"))
    result = decide_changes(released(base), "endowment", [incoming], {"current"})
    maintenance = result.members[0].maintenance
    assert (maintenance.revision_no, maintenance.first_release_id) == (4, "first")
    assert maintenance.last_changed_release_id is None


def test_order_of_all_outputs_is_independent_of_input_order() -> None:
    base = [claim("health", "z", "旧值", proof("old")),
            claim("health", "c", "旧值", proof("current", "旧说法"))]
    incoming = [claim("health", "c", "新值", proof("new", "新说法")),
                claim("health", "b", None), claim("health", "a", None)]
    first = decide_changes(released(*base), "health", incoming, {"current", "new"})
    second = decide_changes(released(*reversed(base)), "health", list(reversed(incoming)),
                            {"new", "current"})
    assert first.items == second.items
    assert first.review_items == second.review_items
    assert first.removals == second.removals
    assert [item.logical_key for item in first.items] == ["health/a", "health/b", "health/c",
                                                         "health/z"]
    assert [member.logical_key for member in first.members] == ["health/a", "health/b"]


@pytest.mark.parametrize("duplicate_side", ["active", "incoming"])
def test_duplicate_logical_keys_fail_closed(duplicate_side: str) -> None:
    item = claim("health", "waiting", "30日", proof("current"))
    base = released(item, item) if duplicate_side == "active" else released(item)
    incoming = [item, item] if duplicate_side == "incoming" else [item]
    with pytest.raises(ValueError, match="duplicate"):
        decide_changes(base, "health", incoming, {"current"})


def test_duplicate_base_slugs_cannot_alias_two_logical_keys() -> None:
    a, b = claim("health", "a", None), claim("health", "b", None)
    with pytest.raises(ValueError, match="duplicate"):
        decide_changes(released(a, b, slugs=("same", "same")), "health", [], set())


def test_cross_product_incoming_cannot_be_added_to_the_requested_product() -> None:
    with pytest.raises(ValueError, match="subject_ref"):
        decide_changes(released(), "health", [claim("endowment", "participating", None)], set())


def test_incoming_key_cannot_overwrite_another_products_member() -> None:
    foreign = claim("endowment", "participating", None)
    incoming = claim("health", "participating", None).model_copy(
        update={"logical_key": foreign.logical_key},
    )
    with pytest.raises(ValueError, match="subject_ref"):
        decide_changes(released(foreign), "health", [incoming], set())


@pytest.mark.parametrize(("old", "new"), [
    (None, "30日"), ("60日", "30日"), ("30日", "30 日"),
])
def test_replacement_rejects_a_base_slug_that_assembly_cannot_replace(
    old: str | None, new: str,
) -> None:
    evidence = () if old is None else (proof("withdrawn"),)
    base = claim("health", "waiting", old, *evidence)
    incoming = claim("health", "waiting", new, proof("current"))
    with pytest.raises(ValueError, match="BASE_SLUG_MISMATCH"):
        decide_changes(released(base, slugs=("published/field",)), "health", [incoming],
                       {"current"})


def test_retraction_uses_actual_base_slug_even_when_it_differs_from_logical_key() -> None:
    base = claim("health", "waiting", "30日", proof("withdrawn"))
    result = decide_changes(released(base, slugs=("published/field",)), "health", [], set())
    assert list(result.removals) == ["published/field"]


@pytest.mark.parametrize("withdrawn", [False, True])
def test_add_cannot_overwrite_a_kept_or_retracted_base_claims_alias_slug(withdrawn: bool) -> None:
    base = claim("health", "old", "已有值", proof("current"))
    incoming = claim("health", "new", None)
    current = set() if withdrawn else {"current"}
    with pytest.raises(ValueError, match="ACTIVE_SLUG_OWNERSHIP_COLLISION"):
        decide_changes(released(base, slugs=(incoming.logical_key,)), "health", [incoming], current)


@pytest.mark.parametrize("payload", [
    {"subject_ref": "endowment", "logical_key": "endowment/old", "legacy_field": "older"},
    None, "opaque old payload", ["not a claim object"],
])
def test_malformed_foreign_claim_payload_does_not_block_selected_product(payload: Any) -> None:
    active = released(claim("health", "known", None))
    active.members.append(ReleaseMember(
        kind="claim", logical_slug="foreign/old", member_digest="a" * 64, payload=payload,
    ))
    result = decide_changes(active, "health", [claim("health", "new", None)], set())
    assert [(item.logical_key, item.verdict) for item in result.items] == [
        ("health/known", Verdict.KEEP), ("health/new", Verdict.ADD),
    ]
    assert [item.logical_key for item in result.members] == ["health/new"]


@pytest.mark.parametrize("collision", ["slug", "raw_key"])
def test_malformed_foreign_claim_still_reserves_its_slug_and_raw_logical_key(
    collision: str,
) -> None:
    incoming = claim("health", "new", None)
    slug = incoming.logical_key if collision == "slug" else "foreign/old"
    key = incoming.logical_key if collision == "raw_key" else "foreign/key"
    active = Release(id="base", epoch=1, members=[ReleaseMember(
        kind="claim", logical_slug=slug, member_digest="a" * 64,
        payload={"subject_ref": "endowment", "logical_key": key, "legacy_field": "older"},
    )])
    reason = "subject_ref" if collision == "raw_key" else "ACTIVE_SLUG_OWNERSHIP_COLLISION"
    with pytest.raises(ValueError, match=reason):
        decide_changes(active, "health", [incoming], set())


def test_duplicate_selected_keys_fail_even_when_their_base_slugs_differ() -> None:
    duplicate = claim("health", "waiting", None)
    with pytest.raises(ValueError, match="duplicate"):
        decide_changes(released(duplicate, duplicate, slugs=("health/a", "health/b")),
                       "health", [], set())


@pytest.mark.parametrize("source_ref", [
    "other:v1:current:1:" + "a" * 64,
    "source:v1::1:" + "a" * 64,
    "source:v1:current:0:" + "a" * 64,
    "source:v1:current:1:short",
    "source:v1:current:1:" + "a" * 64 + ":extra",
    "source:v1:current:1:" + "a" * 64,
])
@pytest.mark.parametrize("side", ["active", "incoming"])
def test_invalid_or_inconsistent_source_references_fail_closed(source_ref: str, side: str) -> None:
    evidence = proof("current").model_copy(update={"source_ref": source_ref})
    item = claim("health", "waiting", "30日", evidence)
    base = released(item) if side == "active" else released()
    incoming = [item] if side == "incoming" else []
    with pytest.raises(ValueError, match="source_ref"):
        decide_changes(base, "health", incoming, {"current"})
