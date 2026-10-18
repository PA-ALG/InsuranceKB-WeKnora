"""Number reading beyond the acceptance cases (review R1 on PR #220).

A number is read whole with its sign, never by a suffix, so a statement cannot pass on the tail of
a larger or fractional number or on the opposite sign; equal values written differently still
match, ranges included; an unreadable or overlong run fails closed without failing the
check (R1, R3, R4).
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
        ("18周岁-65周岁", {"18周岁", "65周岁"}),
        ("18周岁 - 65周岁", {"18周岁", "65周岁"}),
        ("5000元-1万元", {"5000元", "10000元"}),
        ("每年-3.5%", {"-3.5%"}),
        ("每月 − 15000元", {"-15000元"}),
        ("1. 20年长期保障", {"1.2年"}),  # a point is a decimal point, list or not: fails closed
        ("1. 20年长期保障；2. 3次给付", {"1.2年", "2.3次"}),
        ("期限如下：\n12. 50年", {"12.5年"}),
        ("给付12. 50元", {"12.5元"}),
        ("计划三5000元；计划一2万元", {"5000元", "20000元"}),  # a label digit is not the number
        ("保险期间 20 年，10 万元", {"20年", "100000元"}),
        ("一万零5元，1万零5千元", {"10005元", "15000元"}),
        ("18周岁 -65周岁", {"18周岁", "65周岁"}),
        ("每年 -3.5%", {"-3.5%"}),
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
        ("甲产品收益为负 三点五%。", "收益为3.5%。"),  # review R2 on PR #227
        ("甲产品给付5 千元。", "给付1000元。"),
        ("甲产品保障3 个 月。", "保障20年。"),
        ("甲产品为1 5日。", "为5日。"),
        ("甲产品保障三点 5年。", "保障5年。"),
        ("甲产品给付一万零5元。", "给付5元。"),  # review R3 on PR #227
        ("甲产品给付1万零5千元。", "给付5000元。"),
        ("甲产品给付12. 50元。", "给付50元。"),  # review R2 (second round) on PR #227
        ("甲产品收益为-3. 5%。", "收益为5%。"),
        ("甲产品给付金额：12. 50元。", "给付金额为50元。"),  # third round on PR #227
        ("甲产品收益率：3. 5%。", "收益率为5%。"),
        ("甲产品给付金额为50元。", "给付金额：12. 50元。"),
        ("甲产品期限为50年。", "期限如下：\n12. 50年"),
        ("首年收益率：1. 5%；次年收益率：2. 5%。", "收益率均为5%。"),  # fourth round on PR #227
        ("收益率均为5%。", "首年收益率：1. 5%；次年收益率：2. 5%。"),
        ("甲项金额：1. 50元。\n\n乙项金额：2. 50元。", "各项金额均为50元。"),
        ("两款产品每年-3.5%。", "每年3.5%"),
        ("两款产品每年负三点五%。", "每年3.5%"),
    ],
    ids=[
        "suffix of a larger amount",
        "suffix of a fraction",
        "percentage in words",
        "unreadable",
        "opposite sign in words",
        "opposite sign",
        "sign across a space",
        "power across a space",
        "unit across spaces",
        "digits across a space",
        "fraction across a space",
        "mixed numeral with powers",
        "arabic numeral with powers",
        "decimal point before a space",
        "signed decimal before a space",
        "decimal after a colon",
        "percentage after a colon",
        "decimal in the claim",
        "decimal on its own line in the claim",
        "two field decimals in the statement",
        "two field decimals in the claim",
        "decimals in two paragraphs",
        "sign after a word ending in a unit",
        "sign in words after such a word",
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
        ("甲产品适用年龄为18周岁至65周岁。", "18周岁-65周岁"),
        ("甲产品适用年龄为18周岁 - 65周岁。", "18周岁至65周岁"),
        ("甲产品金额范围5000元-1万元。", "5000元至1万元"),
        ("两款产品每年负三点五%。", "每年-3.5%"),
    ],
)
def test_the_same_value_written_differently_passes(statement: str, value: str) -> None:
    assert problems(statement, value) == []


def test_an_overlong_number_is_refused_by_length_without_failing_the_check() -> None:
    found = problems("万" * 1500 + "元", "1万元")
    assert "STATEMENT_LENGTH" in found and "NUMBER_UNSUPPORTED" in found


@pytest.mark.parametrize(
    "general",
    ["示例产品2. 0的专属保障。", "示例产品２． ０的专属保障。", "示例产品2.0的专属保障。"],
)
def test_a_product_named_with_a_point_is_still_named(general: str) -> None:
    fact = Fact("P1", "示例产品2.0", "医疗险", "present", "15日", "P1/f", "a" * 64)
    concept = ConceptInput("f", "字段", "", (fact,))
    draft = ConceptDraft("f", general, "解释。", (StatementDraft("为15日。", ("P1/f",)),))
    assert "PRODUCT_NAMED" in check_concept(draft, concept, {"示例产品2.0", "P1"})
