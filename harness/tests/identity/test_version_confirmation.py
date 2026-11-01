"""PV-3 acceptance (written by Claude): a person's version choice is held to the same rules.

Spec docs/design/slices/PV-3-培训材料按版本归属与人工闭环.md §3. Only consistent versions can be
chosen; an undated material may be given any type-consistent version of its family, recorded as
a person's version decision; applying an answer judges the material again and refuses a choice
whose evidence has changed; an older brand question cannot carry a product choice past the
version rules.
"""

import pytest

from insurance_harness.identity.attribution import Attribution, attribute
from insurance_harness.identity.confirmation import ConfirmationError, choices, conclude
from tests.identity.test_training_versions import (
    NURSING,
    YXJY_PAR,
    YXJY_PLAIN,
    ZYBH_2024,
    ZYBH_2026,
    deck,
    version,
)

PARALLEL = deck("御享金越销售方法.pptx", "御享金越销售方法\n2023年11月")
UNDATED = deck("御享金越分红培训.pptx", "御享金越分红产品培训")
NO_ROLE = deck("智盈倍护_20240527.pptx", "智盈倍护\n2024年5月")


def key_of(question: Attribution, registry: list, value: str | None) -> str:
    return next(c.key for c in choices(question, registry) if c.value == value)


def test_a_person_picks_one_consistent_version() -> None:
    registry = [YXJY_PLAIN, YXJY_PAR]
    question = attribute(PARALLEL, registry)
    result = conclude(question, key_of(question, registry, "1734"), PARALLEL, registry)
    assert (result.outcome, result.product_id, result.role) == (
        "SUPPLEMENT",
        "1734",
        "sales_training",
    )
    basis = result.version_basis
    assert basis is not None
    assert (basis.version_decided_by, basis.role_decided_by) == ("person", "machine")
    assert basis.candidates == question.version_basis.candidates  # the evidence the person saw


def test_changed_evidence_makes_the_choice_stale() -> None:
    registry = [YXJY_PLAIN, YXJY_PAR]
    question = attribute(PARALLEL, registry)
    third = version(
        "1735",
        "平安御享金越终身寿险",
        "schemapack_whole_life_insurance",
        "2023-11-01",
        "2024-01-11",
        status="discontinued",
    )
    with pytest.raises(ConfirmationError) as stale:
        conclude(question, key_of(question, registry, "1734"), PARALLEL, [*registry, third])
    assert stale.value.code == "CHOICE_STALE"


def test_an_undated_material_takes_a_type_consistent_version_as_a_persons_decision() -> None:
    registry = [YXJY_PLAIN, YXJY_PAR]
    question = attribute(UNDATED, registry)
    assert [c.value for c in choices(question, registry)] == ["1734", None]
    result = conclude(question, key_of(question, registry, "1734"), UNDATED, registry)
    assert result.product_id == "1734"
    assert result.version_basis is not None and result.version_basis.version_decided_by == "person"


def test_a_role_answer_keeps_the_machines_version() -> None:
    registry = [ZYBH_2024, ZYBH_2026]
    question = attribute(NO_ROLE, registry)
    result = conclude(question, key_of(question, registry, "sales_training"), NO_ROLE, registry)
    assert (result.outcome, result.product_id, result.role) == (
        "SUPPLEMENT",
        "2635",
        "sales_training",
    )
    basis = result.version_basis
    assert basis is not None
    assert (basis.version_decided_by, basis.role_decided_by) == ("machine", "person")


def test_a_role_answer_is_stale_once_the_version_is_no_longer_unique() -> None:
    registry = [ZYBH_2024, ZYBH_2026]
    question = attribute(NO_ROLE, registry)
    twin = version(
        "2636",
        "平安智盈倍护终身护理保险",
        NURSING,
        "2024-04-23",
        "2024-09-01",
        status="discontinued",
    )
    with pytest.raises(ConfirmationError) as stale:
        conclude(question, key_of(question, registry, "sales_training"), NO_ROLE, [*registry, twin])
    assert stale.value.code == "CHOICE_STALE"


def test_an_older_brand_question_cannot_choose_past_the_version_rules() -> None:
    registry = [ZYBH_2024, ZYBH_2026]
    upload = deck("智盈倍护产品培训_20240527.pptx", "智盈倍护产品培训\n2024年5月")
    older = Attribution(
        outcome="NEEDS_CONFIRM",
        reason="brand_candidates",
        role="sales_training",
        candidates=("2635", "2648"),
        policy_ref="attribution-policy@2026-11-01.1",
    )
    with pytest.raises(ConfirmationError) as stale:
        conclude(older, key_of(older, registry, "2648"), upload, registry)
    assert stale.value.code == "CHOICE_STALE"


def test_conflicting_dates_can_only_be_ignored() -> None:
    registry = [ZYBH_2024, ZYBH_2026]
    upload = deck("智盈倍护培训（2024年6月版）.pptx", "智盈倍护培训\n2024年4月")
    question = attribute(upload, registry)
    offered = choices(question, registry)
    assert [c.kind for c in offered] == ["ignore"]
    result = conclude(question, offered[0].key, upload, registry)
    assert (result.outcome, result.reason) == ("IGNORED", "confirmed_ignore")
