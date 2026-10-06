"""Source matching must preserve numbers, negation, identity and page boundaries."""

import pytest

from insurance_harness.evidence.quote_verification import QuoteMatch, verify_quote


@pytest.mark.parametrize(
    ("source", "quote", "expected"),
    [
        ("期间为90日。", "90日", QuoteMatch.EXACT),
        ("期间为９０日。", "90日", QuoteMatch.NORMALIZED),
        ("期间为\n90 日。", "期间为90日", QuoteMatch.NORMALIZED),
        ("• 期间为90日\n● 可申请", "期间为90日可申请", QuoteMatch.NORMALIZED),
        ("依照定义的术语[1]办理。\n1 术语是指本条事项。", "术语办理", QuoteMatch.NORMALIZED),
        ("依照定义的术语¹办理。\n1 术语是指本条事项。", "术语办理", QuoteMatch.NORMALIZED),
        ("依照定义的术语1办理。\n1 术语是指本条事项。", "术语办理", QuoteMatch.NOT_FOUND),
        ("期间为90日。", "180日", QuoteMatch.NOT_FOUND),
        ("不得给付。", "可以给付", QuoteMatch.NOT_FOUND),
        ("期间为90日。", "期间为90日!", QuoteMatch.NOT_FOUND),
        ("A•B", "AB", QuoteMatch.NOT_FOUND),
        ("术语1办理", "术语办理", QuoteMatch.NOT_FOUND),
        ("费用1万元。\n1 费用是指本条事项。", "费用万元。", QuoteMatch.NOT_FOUND),
        ("期间1年。\n1 期间是指本条事项。", "期间年。", QuoteMatch.NOT_FOUND),
        ("编号1A。\n1 编号是指本条事项。", "编号A。", QuoteMatch.NOT_FOUND),
        ("比例1.5%。\n1 比例是指本条事项。", "比例.5%。", QuoteMatch.NOT_FOUND),
        ("费用１万元。\n１ 费用是指本条事项。", "费用万元。", QuoteMatch.NOT_FOUND),
        ("编号١A。\n١ 编号是指本条事项。", "编号A。", QuoteMatch.NOT_FOUND),
        ("1.金额100元", "金额10元", QuoteMatch.NOT_FOUND),
        ("唯一内容", "", QuoteMatch.NOT_FOUND),
        ("唯一内容", " \n", QuoteMatch.NOT_FOUND),
    ],
)
def test_quote_matching_is_conservative(source: str, quote: str, expected: QuoteMatch) -> None:
    assert verify_quote(source, quote) is expected
