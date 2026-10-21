"""S8a acceptance (protected, written by Claude): Claim-level changes between the Active release
and a product's new compile, so only real changes are published and conflicts never reach the live
page (Spec docs/design/slices/S8a-Claim级增量发布.md §4).
RED until S8a: insurance_harness.changes is missing.

Synthetic data only: product P moves from terms v1 + brochure to terms v2 + brochure; product Q is
untouched. No model calls, no network.
"""

import hashlib

import pytest

from insurance_harness.bundle.assemble import assemble
from insurance_harness.bundle.client import Release, ReleaseMember
from insurance_harness.changes import ChangeSet, Verdict, decide_changes
from insurance_harness.contracts.enums import (
    ChangedBy,
    ClaimState,
    LocatorKind,
    ReviewKind,
    ReviewStatus,
    SourceClass,
    UnknownReason,
)
from insurance_harness.contracts.knowledge import Claim, Evidence, Locator, Maintenance

TERMS_V1, TERMS_V2, BROCHURE, Q_TERMS = "k-terms-v1", "k-terms-v2", "k-brochure", "k-q-terms"
CURRENT = {TERMS_V2, BROCHURE}


def evidence(knowledge_id: str, quote: str) -> Evidence:
    sha = hashlib.sha256(knowledge_id.encode()).hexdigest()
    return Evidence(
        source_ref=f"source:v1:{knowledge_id}:1:{sha}",
        file_sha256=sha,
        locator=Locator(kind=LocatorKind.PDF_TEXT_SPAN, page=1, start=0, end=len(quote)),
        quote=quote,
        access_scope="space",
    )


def claim(
    entity: str,
    field: str,
    value: str | None,
    *proof: Evidence,
    lock: bool = False,
    revision: int = 0,
    first: str | None = None,
) -> Claim:
    present = value is not None
    key = f"{entity}/{field}"
    return Claim(
        claim_id=key,
        logical_key=key,
        subject_ref=entity,
        predicate=field,
        state=ClaimState.PRESENT if present else ClaimState.UNKNOWN,
        value=value,
        evidence=list(proof),
        origin=SourceClass.SOURCE_SUPPORTED,
        expert_lock=lock,
        unknown_reason=None if present else UnknownReason.NOT_IN_MATERIAL,
        maintenance=Maintenance(revision_no=revision, first_release_id=first),
    )


def release(*claims: Claim) -> Release:
    return Release(
        id="rel-base",
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


BASE = release(
    claim(
        "P", "waiting", "90日", evidence(TERMS_V1, "等待期为90日"), revision=1, first="rel-first"
    ),
    claim("P", "grace", "60日", evidence(TERMS_V1, "宽限期为60日"), revision=1, first="rel-first"),
    claim("P", "cooling", "15日", evidence(TERMS_V1, "犹豫期为15日")),
    claim("P", "sum_limit", "100万元", evidence(BROCHURE, "保额上限100万元")),
    claim("P", "coverage", "住院医疗费用", evidence(BROCHURE, "保障住院医疗费用")),
    claim("P", "deductible", "1万元", evidence(BROCHURE, "年免赔额1万元")),
    claim("P", "renewal", "保证续保20年", evidence(BROCHURE, "保证续保期间20年")),
    claim("P", "occupation", None),
    claim("P", "locked", "专家值", evidence(BROCHURE, "专家依据"), lock=True),
    claim("P", "old_only", "仅旧条款", evidence(TERMS_V1, "仅旧条款有")),
    claim("P", "still_unknown", None),
    claim("Q", "waiting", "180日", evidence(Q_TERMS, "等待期为180日")),
)

INCOMING = [
    claim("P", "waiting", "90 日", evidence(TERMS_V2, "等待期为90日。")),
    claim("P", "grace", "30日", evidence(TERMS_V2, "宽限期为30日")),
    claim("P", "cooling", None),
    claim("P", "sum_limit", "1,000,000元", evidence(BROCHURE, "保额上限100万元")),
    claim("P", "coverage", "被保险人住院产生的医疗费用", evidence(BROCHURE, "保障住院医疗费用")),
    claim("P", "deductible", "5000元", evidence(TERMS_V2, "年免赔额5000元")),
    claim("P", "renewal", "保证续保期间为二十年", evidence(BROCHURE, "每二十年为一个保证续保期间")),
    claim("P", "occupation", "1-4类职业", evidence(TERMS_V2, "1-4类职业可投保")),
    claim("P", "locked", "模型值", evidence(TERMS_V2, "模型依据")),
    claim("P", "new_field", "新值", evidence(TERMS_V2, "新条款新增内容")),
    claim("P", "still_unknown", None),
]

EXPECTED = {
    "P/waiting": Verdict.REFRESH,
    "P/grace": Verdict.SUPERSEDE,
    "P/cooling": Verdict.SUPERSEDE,
    "P/sum_limit": Verdict.UNCHANGED,
    "P/coverage": Verdict.UNCHANGED,
    "P/deductible": Verdict.CONFLICT,
    "P/renewal": Verdict.KEEP,
    "P/occupation": Verdict.FILL,
    "P/locked": Verdict.CONFLICT,
    "P/old_only": Verdict.RETRACT,
    "P/new_field": Verdict.ADD,
    "P/still_unknown": Verdict.UNCHANGED,
}


@pytest.fixture
def changes() -> ChangeSet:
    return decide_changes(BASE, "P", INCOMING, CURRENT)


def test_every_field_of_the_product_gets_its_verdict(changes: ChangeSet) -> None:
    assert {item.logical_key: item.verdict for item in changes.items} == EXPECTED


def test_only_real_changes_are_published_with_their_maintenance_record(changes: ChangeSet) -> None:
    members = {member.logical_key: member for member in changes.members}
    assert set(members) == {"P/waiting", "P/grace", "P/cooling", "P/occupation", "P/new_field"}
    assert members["P/grace"].value == "30日"
    assert members["P/cooling"].state == ClaimState.UNKNOWN
    revisions = {key: member.maintenance.revision_no for key, member in members.items()}
    assert revisions == {
        "P/waiting": 1,
        "P/grace": 2,
        "P/cooling": 1,
        "P/occupation": 1,
        "P/new_field": 0,
    }
    assert members["P/grace"].maintenance.first_release_id == "rel-first"
    assert members["P/waiting"].maintenance.first_release_id == "rel-first"
    assert members["P/new_field"].maintenance.first_release_id is None
    for key, member in members.items():
        assert member.maintenance.changed_by == ChangedBy.COMPILE
        assert member.maintenance.changed_at
        assert member.maintenance.reason == EXPECTED[key].value


def test_retractions_are_removals_and_conflicts_become_review_items(changes: ChangeSet) -> None:
    assert list(changes.removals) == ["P/old_only"]
    conflicts = sorted(changes.review_items, key=lambda item: item.target)
    assert [item.target for item in conflicts] == ["P/deductible", "P/locked"]
    for item in conflicts:
        assert item.kind == ReviewKind.CONFLICT
        assert item.status == ReviewStatus.OPEN
        assert item.evidence


def test_another_product_is_never_touched(changes: ChangeSet) -> None:
    touched = (
        [item.logical_key for item in changes.items]
        + [member.logical_key for member in changes.members]
        + list(changes.removals)
    )
    assert not [key for key in touched if key.startswith("Q/")]


def test_the_change_set_assembles_into_a_candidate_without_unchanged_members(
    changes: ChangeSet,
) -> None:
    bundle = assemble(
        list(changes.members),
        compiler_identity="harness/changes@test",
        base=BASE.head,
        removals=list(changes.removals),
    )
    slugs = {member.logical_slug for member in bundle.members}
    assert slugs == {"P/waiting", "P/grace", "P/cooling", "P/occupation", "P/new_field"}
    assert not slugs & set(bundle.removals)
    for unchanged in (
        "P/sum_limit",
        "P/coverage",
        "P/renewal",
        "P/deductible",
        "P/locked",
        "Q/waiting",
    ):
        assert unchanged not in slugs


def test_a_recompile_of_the_same_materials_publishes_nothing() -> None:
    current = {TERMS_V1, BROCHURE}
    same = decide_changes(BASE, "P", [], current)
    assert not same.members
    assert not same.removals
    assert {item.verdict for item in same.items} == {Verdict.KEEP}


def test_withdrawn_materials_retract_sourced_claims_and_keep_unknowns_and_expert_values() -> None:
    gone = decide_changes(BASE, "P", [], set())
    verdicts = {item.logical_key: item.verdict for item in gone.items}
    kept = ("P/occupation", "P/still_unknown", "P/locked")
    assert {verdicts[key] for key in kept} == {Verdict.KEEP}
    sourced = {key for key in verdicts if key not in kept}
    assert {verdicts[key] for key in sourced} == {Verdict.RETRACT}
    assert set(gone.removals) == sourced
    assert not gone.members
