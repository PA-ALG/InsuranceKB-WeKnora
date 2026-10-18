"""Number tokens beyond the acceptance cases: how numbers and units are read for the checks."""

from __future__ import annotations

import pytest

from insurance_harness.compilers.concepts.checks import number_tokens


@pytest.mark.parametrize(
    ("text", "tokens"),
    [
        ("自签收之日起十五日", {"15日"}),
        ("一百八十日内", {"180日"}),
        ("一百零五周岁", {"105周岁"}),
        ("２０％", {"20%"}),
        ("10,000元或1.50倍", {"10000元", "1.5倍"}),
        ("十万元", {"10万元"}),
        ("3 个月", {"3个月"}),
        ("缴费期满", set()),
    ],
)
def test_numbers_are_read_to_their_value_with_the_longest_unit(text: str, tokens: set[str]) -> None:
    assert number_tokens(text) == tokens
