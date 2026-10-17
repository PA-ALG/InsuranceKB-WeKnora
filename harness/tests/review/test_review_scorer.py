"""RV2a acceptance: the independent review scorer (Spec §3.1, §4).

Protected file: written by Claude. Items are batched by quote length in input order; an oversized
item goes alone with its quotes cut at the limit and marked. A request carries only the items' own
fields, never compile context. The answer must score every key exactly once with a number in
[0, 1]; anything else is refused once, without retry and without echoing the answer. An empty
input sends nothing.
"""

from __future__ import annotations

import json

import pytest

from insurance_harness.review.scorer import (
    TRUNCATION_MARK,
    ReviewItem,
    ReviewOutputError,
    review_batches,
    score_items,
)

SECRET = "SECRET-模型输出原文"


def item(key: str, *quotes: str, state: str = "present") -> ReviewItem:
    return ReviewItem(
        logical_key=f"E1/{key}",
        title=f"标题{key}",
        rules=json.dumps({"description": f"规则{key}"}, ensure_ascii=False),
        state=state,
        value=f"取值{key}" if state == "present" else None,
        quotes=quotes,
    )


class Fake:
    """Returns the queued answers in order, then scores every requested key 0.5."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.requests: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.requests.append((system, user))
        if self.answers:
            return self.answers.pop(0)
        keys = [entry["key"] for entry in json.loads(user)["items"]]
        return json.dumps({"scores": [{"key": key, "score": 0.5} for key in keys]})


def keys(batches: list[list[ReviewItem]]) -> list[list[str]]:
    return [[entry.logical_key for entry in batch] for batch in batches]


def sent_keys(fake: Fake) -> list[list[str]]:
    return [[entry["key"] for entry in json.loads(user)["items"]] for _, user in fake.requests]


# --- batching ----------------------------------------------------------------


def test_batches_fill_up_to_the_quote_limit_in_input_order() -> None:
    items = [item("a", "12345"), item("b", "123", "45"), item("c", "1"), item("d", "123456789")]
    batches = review_batches(items, max_chars=10)
    # a + b is exactly the limit; c + d is too; b + c would exceed it.
    assert batches == [[items[0], items[1]], [items[2], items[3]]]


def test_an_oversized_item_goes_alone_with_its_quotes_cut_and_marked() -> None:
    big = item("big", "abcdef", "ghijkl")
    items = [item("a", "123"), big, item("c", "45")]
    batches = review_batches(items, max_chars=8)
    assert keys(batches) == [["E1/a"], ["E1/big"], ["E1/c"]]
    cut = batches[1][0]
    assert "".join(cut.quotes) == "abcdefgh" + TRUNCATION_MARK
    assert (cut.logical_key, cut.title, cut.rules, cut.state, cut.value) == (
        big.logical_key,
        big.title,
        big.rules,
        big.state,
        big.value,
    )
    # The cut item is still sent: a low score beats a field nobody reviewed.
    fake = Fake()
    assert score_items([big], fake, max_chars=8) == {"E1/big": 0.5}
    [(_, user)] = fake.requests
    assert "".join(json.loads(user)["items"][0]["quotes"]) == "abcdefgh" + TRUNCATION_MARK


def test_each_batch_is_one_request_and_the_scores_merge() -> None:
    items = [item("a", "12345"), item("b", "12345"), item("c", "12345")]
    fake = Fake()
    assert score_items(items, fake, max_chars=10) == {"E1/a": 0.5, "E1/b": 0.5, "E1/c": 0.5}
    assert sent_keys(fake) == [["E1/a", "E1/b"], ["E1/c"]]


# --- request -------------------------------------------------------------------


def test_a_request_carries_only_the_items_own_fields() -> None:
    items = [item("a", "引文一", "引文二"), item("b", "引文三", state="absent_explicitly")]
    fake = Fake()
    assert score_items(items, fake) == {"E1/a": 0.5, "E1/b": 0.5}
    [(system, user)] = fake.requests
    assert json.loads(user) == {
        "items": [
            {
                "key": "E1/a",
                "title": "标题a",
                "rules": items[0].rules,
                "state": "present",
                "value": "取值a",
                "quotes": ["引文一", "引文二"],
            },
            {
                "key": "E1/b",
                "title": "标题b",
                "rules": items[1].rules,
                "state": "absent_explicitly",
                "value": None,
                "quotes": ["引文三"],
            },
        ]
    }
    for text in ("E1/a", "标题a", "规则a", "取值a", "引文一", "引文三"):
        assert text not in system


def test_the_instructions_are_the_same_whatever_is_reviewed() -> None:
    first, second = Fake(), Fake()
    score_items([item("a", "引文一")], first)
    score_items([item("z", "另一段完全不同的引文", state="absent_explicitly")], second)
    assert first.requests[0][0] == second.requests[0][0]


# --- answer ----------------------------------------------------------------------

PAIR = [item("a", "引文一"), item("b", "引文二")]


def answer(*rows: object) -> str:
    return json.dumps({"scores": list(rows)}, ensure_ascii=False)


def row(key: str, score: object) -> dict[str, object]:
    return {"key": key, "score": score}


REFUSED = {
    "missing key": answer(row("E1/a", 0.9)),
    "extra key": answer(row("E1/a", 0.9), row("E1/b", 0.9), row(SECRET, 0.9)),
    "duplicate key": answer(row("E1/a", 0.9), row("E1/a", 0.8), row("E1/b", 0.9)),
    "above one": answer(row("E1/a", 1.2), row("E1/b", 0.9)),
    "below zero": answer(row("E1/a", -0.1), row("E1/b", 0.9)),
    "boolean": answer(row("E1/a", True), row("E1/b", 0.9)),
    "string": answer(row("E1/a", "0.9"), row("E1/b", 0.9)),
    "null": answer(row("E1/a", None), row("E1/b", 0.9)),
    "not a number": '{"scores": [{"key": "E1/a", "score": NaN}, {"key": "E1/b", "score": 0.9}]}',
    "not json": f"评分如下：{SECRET}",
    "not an object": json.dumps([row("E1/a", 0.9), row("E1/b", 0.9)]),
    "scores not a list": json.dumps({"scores": {"E1/a": 0.9, "E1/b": 0.9}}),
}


@pytest.mark.parametrize("text", REFUSED.values(), ids=REFUSED.keys())
def test_an_answer_that_does_not_score_every_key_once_in_range_is_refused(text: str) -> None:
    fake = Fake(text)
    with pytest.raises(ReviewOutputError) as caught:
        score_items(PAIR, fake)
    assert caught.value.reason == "REVIEW_OUTPUT_INVALID"
    assert SECRET not in str(caught.value) and SECRET not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert isinstance(caught.value, ValueError)
    assert len(fake.requests) == 1  # no retry here: models/ is the only retry owner


def test_scores_may_come_in_any_order_and_as_whole_numbers() -> None:
    text = answer(row("E1/b", 1), row("E1/a", 0))
    assert score_items(PAIR, Fake(text)) == {"E1/a": 0.0, "E1/b": 1.0}


def test_nothing_to_review_sends_nothing() -> None:
    fake = Fake()
    assert score_items([], fake) == {}
    assert review_batches([], max_chars=10) == []
    assert fake.requests == []
