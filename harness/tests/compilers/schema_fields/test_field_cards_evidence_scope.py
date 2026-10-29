"""S12c-5 acceptance after the #425 Owner rulings (Spec §7): step-one selection vs the value.

Protected file: written by Claude. R1: the customer profile stays a profile, so step one selects
every passage saying who the product is for and the value compresses it. R2: a condition deciding
whether a payment is made or continues is coverage, pure verification procedure is not; content
decides, not the section heading.
"""

from __future__ import annotations

import re

from insurance_harness.compilers.schema_fields.cards import all_cards

VERIFICATION = "disability_status_verification_and_reassessment_rules"
RECOVERY = "disability_recovery_and_benefit_termination_rules"
# An entry-age bound copied into a value: "出生满28日", "0周岁", "18至55周岁", "55周岁".
AGE_BOUND = re.compile(r"出生满|\d+\s*(?:至\s*\d+\s*)?周岁")


def _targets(key: str) -> dict[str, str]:
    return {target: content for content, target in all_cards()[key]["excludes"]}


def test_step_one_selects_every_passage_saying_who_the_product_is_for() -> None:
    includes = all_cards()["target_customer_profile"]["includes"]
    for basis in ("投保年龄条款", "产品特色", "保障概述", "保险期间条款"):
        assert basis in includes, basis
    assert "年龄段 + 保障需求" in includes
    assert "客群画像" in all_cards()["target_customer_profile"]["definition"]


def test_profile_examples_compress_instead_of_copying_entry_age_bounds() -> None:
    for example in all_cards()["target_customer_profile"]["examples"]:
        assert example["state"] == "present"
        assert not AGE_BOUND.search(example["value"]), example["product_id"]
        assert len(example["value"]) <= 50, example["product_id"]


def test_a_named_sales_case_stays_out_of_the_profile() -> None:
    assert any("具体人物" in content for content in _targets("target_customer_profile").values())


def test_continuation_conditions_are_coverage_and_procedures_are_verification() -> None:
    for key in ("coverage_responsibilities", "coverage_summary"):
        card = all_cards()[key]
        assert "能否继续给付的实质条件" in card["includes"], key
        assert "不按所在小节标题" in card["includes"], key
        targets = "".join(_targets(key))
        assert VERIFICATION in targets and RECOVERY in targets, key
        procedure = next(c for t, c in _targets(key).items() if VERIFICATION in t)
        assert "纯手续" in procedure and "无法核验" in procedure, key


def test_verification_keeps_procedural_consequences_and_leaves_recovery() -> None:
    includes = all_cards()[VERIFICATION]["includes"]
    assert "因无法核验" in includes and "不含因已恢复而停止给付" in includes
    assert any(RECOVERY in target for target in _targets(VERIFICATION))
