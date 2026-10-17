"""Regression (PR #195 review R3): every malformed answer becomes the fixed reason code.

A repeated JSON member must not silently keep its last value, and a number no score can be
(an integer of hundreds of digits, a float that overflows to infinity) is refused like any other
out-of-range score instead of escaping as OverflowError or ValueError.
"""

from __future__ import annotations

import json

import pytest

from insurance_harness.review.scorer import ReviewItem, ReviewOutputError, score_items

ITEMS = [ReviewItem("E1/a", "标题", "规则", "present", "取值", ("引文",))]


class Fixed:
    def __init__(self, answer: str) -> None:
        self.answer, self.calls = answer, 0

    def complete(self, *, system: str, user: str) -> str:
        self.calls += 1
        return self.answer


BIG = "9" * 401
REFUSED = {
    "repeated score member": '{"scores": [{"key": "E1/a", "score": 0.1, "score": 1}]}',
    "repeated key member": '{"scores": [{"key": "E1/x", "key": "E1/a", "score": 0.5}]}',
    "repeated top-level member": '{"scores": [], "scores": [{"key": "E1/a", "score": 0.5}]}',
    "401-digit integer": '{"scores": [{"key": "E1/a", "score": ' + BIG + "}]}",
    "negative 401-digit integer": '{"scores": [{"key": "E1/a", "score": -' + BIG + "}]}",
    "integer beyond the digit limit": '{"scores": [{"key": "E1/a", "score": ' + "1" * 5000 + "}]}",
    "float overflowing to infinity": '{"scores": [{"key": "E1/a", "score": 1e400}]}',
    "negative infinity": '{"scores": [{"key": "E1/a", "score": -1e400}]}',
    "Infinity literal": '{"scores": [{"key": "E1/a", "score": Infinity}]}',
    "nesting too deep": "[" * 100_000 + "]" * 100_000,
}


@pytest.mark.parametrize("answer", REFUSED.values(), ids=REFUSED.keys())
def test_malformed_answers_become_the_fixed_reason_code(answer: str) -> None:
    completion = Fixed(answer)
    with pytest.raises(ReviewOutputError) as caught:
        score_items(ITEMS, completion)
    assert caught.value.reason == "REVIEW_OUTPUT_INVALID"
    assert str(caught.value) == "REVIEW_OUTPUT_INVALID"
    assert caught.value.__cause__ is None
    assert completion.calls == 1


@pytest.mark.parametrize("score", [0, 1, 0.5, 1e-300, 0.30000000000000004, 1.0])
def test_ordinary_scores_still_pass(score: float) -> None:
    answer = json.dumps({"scores": [{"key": "E1/a", "score": score}]})
    assert score_items(ITEMS, Fixed(answer)) == {"E1/a": float(score)}
