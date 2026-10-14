"""S4d acceptance: the extraction prompt asks for complete values and contiguous quotes.

Protected file: written by Claude. Pins §3.2 of the S4d spec. The effect is
measured by the real-call experiments; this only pins that the rules exist.
"""

from insurance_harness.compilers.schema_fields.prompt import SYSTEM_PROMPT


def test_values_must_be_complete_rather_than_summarized() -> None:
    assert "不得概括" in SYSTEM_PROMPT


def test_quotes_must_be_one_contiguous_span() -> None:
    assert "连续" in SYSTEM_PROMPT
