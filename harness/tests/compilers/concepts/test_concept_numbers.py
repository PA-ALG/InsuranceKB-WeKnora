"""Number reading beyond the acceptance cases (review R1 on PR #220).

A number is read whole with its sign, never by a suffix, so a statement cannot pass on the tail of
a larger or fractional number or on the opposite sign; equal values written differently still
match; an unreadable or overlong run fails closed without failing the check (R1, R3).
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
        ("负三点五%", {"-3.5%"}),
        ("为-15000元", {"-15000元"}),
        ("18-65周岁", {"65周岁"}),
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
        ("甲产品收益为负三点五%。", "收益3.5%。"),
        ("甲产品差额为-15000元。", "差额一万五千元。"),
    ],
    ids=[
        "suffix of a larger amount",
        "suffix of a fraction",
        "percentage in words",
        "unreadable",
        "opposite sign in words",
        "opposite sign",
    ],
)
def test_a_number_the_value_does_not_hold_is_refused(statement: str, value: str) -> None:
    assert "NUMBER_UNSUPPORTED" in problems(statement, value)


@pytest.mark.parametrize(
    ("statement", "value"),
    [
        ("甲产品给付15000元。", "给付一万五千元。"),
        ("甲产品报销百分之二十。", "按20%报销。"),
        ("甲产品最高10万元。", "最高十万元。"),
        ("甲产品差额为-15000元。", "差额为负一万五千元。"),
    ],
)
def test_the_same_value_written_differently_passes(statement: str, value: str) -> None:
    assert problems(statement, value) == []


def test_an_overlong_number_is_refused_by_length_without_failing_the_check() -> None:
    found = problems("万" * 1500 + "元", "1万元")
    assert "STATEMENT_LENGTH" in found and "NUMBER_UNSUPPORTED" in found
