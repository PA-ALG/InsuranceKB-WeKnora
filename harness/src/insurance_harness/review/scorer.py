"""Independent review scores for compiled fields, from their rules, value and quotes alone.

The reviewer sees, per item, only what the caller prepared: a title, the field rules as data
text, the stated state and value, and the quotes cut from the source. It never sees how the
value was compiled (prompts, segment choice, page text, examples), and the compile model does
not grade itself (blueprint §6.3). Each item gets a score in [0, 1]: how likely its state and
value are fully and accurately supported by its quotes and consistent with its rules.

Batches are sent and checked one at a time, in input order. An answer that does not score every
key of its batch exactly once with a number in [0, 1] is refused with a fixed reason code and is
never retried here: the completion adapter is the only retry owner of a call chain.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

# Appended where an oversized item's quotes are cut: a low score beats a field nobody reviewed.
TRUNCATION_MARK = "……（引文截断）"

_SYSTEM = (
    "你是独立审核员。请求的 items 中每个条目给出 key、title（名称）、rules（判断规则）、"
    "state（状态）、value（取值）与 quotes（原文引文）。\n"
    "对每个条目，只依据它自己的 quotes 判断：其 state 与 value 是否被引文完整、准确地支持，"
    "并且符合 rules。state 为 present 时，value 应完整准确地表述引文所写的内容，不多不少；"
    "state 为 absent_explicitly 时，引文应明确写明该项不存在、不适用或不提供。\n"
    "不得使用引文以外的知识或推测。引文不足以支持、取值有遗漏或多出、与规则不符时给低分；"
    f"引文末尾带有“{TRUNCATION_MARK}”表示引文不完整。\n"
    '只输出一个 JSON 对象：{"scores": [{"key": "<条目 key>", "score": <0 到 1 之间的数>}]}。'
    "每个条目恰好一项，key 原样照抄，score 表示该状态与取值正确的可信度，不输出其他内容。"
)


@dataclass(frozen=True)
class ReviewItem:
    logical_key: str
    title: str
    rules: str  # field definition and boundary rules: data text the caller prepares
    state: str  # "present" | "absent_explicitly"
    value: str | None
    quotes: tuple[str, ...]


class Completion(Protocol):
    def complete(self, *, system: str, user: str) -> str: ...


class ReviewOutputError(ValueError):
    """The answer is unusable; carries a reason code, never the answer text."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def review_batches(items: Sequence[ReviewItem], *, max_chars: int) -> list[list[ReviewItem]]:
    """Consecutive items while their quotes fit max_chars; an oversized item goes alone, cut.

    Batching a batch again returns it unchanged: a cut item keeps the first max_chars quote
    characters followed by the mark, and cutting it again yields the same item.
    """
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError("max_chars must be a positive integer")
    batches: list[list[ReviewItem]] = []
    size = 0
    open_batch = False
    for item in items:
        chars = _chars(item)
        if chars > max_chars:
            batches.append([_cut(item, max_chars)])
            open_batch = False
        elif open_batch and size + chars <= max_chars:
            batches[-1].append(item)
            size += chars
        else:
            batches.append([item])
            size, open_batch = chars, True
    return batches


def score_items(
    items: Sequence[ReviewItem], completion: Completion, *, max_chars: int = 60_000
) -> dict[str, float]:
    """{logical_key: score} for every item; one completion call per batch, none when empty."""
    keys = [item.logical_key for item in items]
    if len(set(keys)) != len(keys):
        raise ValueError("review item keys must be unique")
    scores: dict[str, float] = {}
    for batch in review_batches(items, max_chars=max_chars):
        answer = completion.complete(system=_SYSTEM, user=_request(batch))
        scores.update(_parse(answer, [item.logical_key for item in batch]))
    return scores


def _chars(item: ReviewItem) -> int:
    return sum(len(quote) for quote in item.quotes)


def _cut(item: ReviewItem, max_chars: int) -> ReviewItem:
    kept: list[str] = []
    left = max_chars
    for quote in item.quotes:
        if left <= 0:
            break
        kept.append(quote[:left])
        left -= len(kept[-1])
    kept[-1] += TRUNCATION_MARK
    return replace(item, quotes=tuple(kept))


def _request(batch: Sequence[ReviewItem]) -> str:
    entries = [
        {
            "key": item.logical_key,
            "title": item.title,
            "rules": item.rules,
            "state": item.state,
            "value": item.value,
            "quotes": list(item.quotes),
        }
        for item in batch
    ]
    return json.dumps({"items": entries}, ensure_ascii=False)


def _reject_constant(name: str) -> float:
    raise ValueError("non-finite number")


def _unique_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    # A repeated member would silently keep only its last value.
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate member")
        document[key] = value
    return document


def _parse(answer: str, keys: Sequence[str]) -> dict[str, float]:
    """Every key of the batch exactly once, or the fixed reason code without the answer text."""
    try:
        scores = _scores(answer)
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ReviewOutputError("REVIEW_OUTPUT_INVALID") from None
    if set(scores) != set(keys):
        raise ReviewOutputError("REVIEW_OUTPUT_INVALID")
    return scores


def _scores(answer: str) -> dict[str, float]:
    """The one accepted shape; anything else raises ValueError."""
    document = json.loads(
        answer, object_pairs_hook=_unique_members, parse_constant=_reject_constant
    )
    if (
        not isinstance(document, dict)
        or set(document) != {"scores"}
        or not isinstance(document["scores"], list)
    ):
        raise ValueError("unexpected answer shape")
    scores: dict[str, float] = {}
    for row in document["scores"]:
        if not isinstance(row, dict) or set(row) != {"key", "score"}:
            raise ValueError("unexpected row shape")
        key, score = row["key"], row["score"]
        # bool is an int subclass: a JSON true must not become a score of 1. The range check
        # runs before any float conversion: it holds for integers of any size, and NaN or an
        # overflowing float (parsed as infinity) never passes it.
        if (
            not isinstance(key, str)
            or key in scores
            or type(score) not in (int, float)
            or not 0 <= score <= 1
        ):
            raise ValueError("unexpected key or score")
        scores[key] = float(score)
    return scores
