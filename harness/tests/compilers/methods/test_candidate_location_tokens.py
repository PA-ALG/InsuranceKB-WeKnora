"""SK-2d supplemental RED: containment must not cut retained numeric/identifier tokens."""

import pytest

from tests.compilers.methods.test_candidate_locations import LONG, Scenario, found


@pytest.mark.parametrize("left,right", [
    ("12.5%", "12.5"), ("15", "1"), ("12.5%", "12"), ("A15", "A1"),
])
@pytest.mark.parametrize("reverse", [False, True])
def test_containment_cannot_cut_a_numeric_or_identifier_token(
    left: str, right: str, reverse: bool
) -> None:
    raw, copy = LONG + "预算" + left, LONG + "预算" + right
    if reverse:
        raw, copy = copy, raw
    assert not found(Scenario(((raw,),)).run(copy))


@pytest.mark.parametrize("suffix", ["12.5%", "-5%", "A15"])
def test_complete_numeric_tokens_still_locate(suffix: str) -> None:
    raw = LONG + "预算" + suffix
    assert found(Scenario(((raw,),)).run(raw)) == ("P1S1",)
