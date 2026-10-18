"""Number reading beyond the acceptance cases (review R1 on PR #220).

A number is read whole, never by a suffix, so a statement cannot pass on the tail of a larger or
fractional number; equal values written differently still match; an unreadable run fails closed.
"""

from __future__ import annotations

import pytest

from insurance_harness.compilers.concepts.checks import check_concept, number_tokens
from insurance_harness.compilers.concepts.synthesis import (
    ConceptDraft,
    ConceptInput,
    Fact,
    StatementDraft,
)


@pytest.mark.parametrize(
    ("text", "tokens"),
    [
        ("自签收之日起十五日", {"15日"}),
        ("一百八十日内", {"180日"}),
        ("一百零五周岁", {"105周岁"}),
        ("２０％", {"20%"}),
        ("10,000元或1.50倍", {"10000元", "1.5倍"}),
        ("十万元与10万元", {"100000元"}),
        ("给付一万五千元", {"15000元"}),
        ("1.5万元", {"15000元"}),
        ("保障三点五年", {"3.5年"}),
        ("百分之五十", {"50%"}),
        ("3 个月", {"3个月"}),
        ("115日", {"115日"}),
        ("十十日", {"十十日"}),
        ("缴费期满", set()),
    ],
)
def test_numbers_are_read_whole_to_their_value(text: str, tokens: set[str]) -> None:
    assert number_tokens(text) == tokens


def problems(statement: str, value: str) -> list[str]:
    fact = Fact("P1", "甲产品", "医疗险", "present", value, "P1/f", "a" * 64)
    concept = ConceptInput("f", "字段", "", (fact,))
    draft = ConceptDraft("f", "定义。", "解释。", (StatementDraft(statement, ("P1/f",)),))
    return check_concept(draft, concept, {"甲产品", "P1"})


@pytest.mark.parametrize(
    ("statement", "value"),
    [
        ("甲产品给付一万五千元。", "给付5000元。"),
        ("甲产品保障三点五年。", "保障5年。"),
        ("甲产品报销百分之五十。", "按20%报销。"),
        ("甲产品为十十日。", "为10日。"),
    ],
    ids=["suffix of a larger amount", "suffix of a fraction", "percentage in words", "unreadable"],
)
def test_a_number_the_value_does_not_hold_is_refused(statement: str, value: str) -> None:
    assert "NUMBER_UNSUPPORTED" in problems(statement, value)


@pytest.mark.parametrize(
    ("statement", "value"),
    [
        ("甲产品给付15000元。", "给付一万五千元。"),
        ("甲产品报销百分之二十。", "按20%报销。"),
        ("甲产品最高10万元。", "最高十万元。"),
    ],
)
def test_the_same_value_written_differently_passes(statement: str, value: str) -> None:
    assert problems(statement, value) == []
