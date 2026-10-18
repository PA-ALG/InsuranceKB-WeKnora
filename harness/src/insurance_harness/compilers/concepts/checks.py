"""Deterministic checks on one concept draft (S3e-3 Spec §4.1).

The general text names no entry of the release. Each statement cites claims of its concept, and
every "number + unit" it states is found in a cited value; a statement with numbers cites no value
holding none of them, so "both are 15 days" cannot cite a 20-day product. Text is compared after
NFKC with whitespace and thousands separators removed. Chinese numerals count as numbers: they
are read to their value on both sides, so 十五日 and 15日 are the same fact and neither escapes the
check.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection
from decimal import Decimal

from insurance_harness.compilers.concepts.synthesis import ConceptDraft, ConceptInput

DEFINITION_MAX, EXPLANATION_MAX, STATEMENT_MAX = 120, 400, 200
STATEMENTS = range(1, 7)

# Longer units first, so 个月, 周岁 and 万元 are not read as 月, 岁 and 元.
_TOKEN = re.compile(
    r"(?P<number>[0-9]+(?:\.[0-9]+)?|[零〇一二两三四五六七八九十百千]+)"
    r"(?P<unit>万元|个月|周岁|日|天|月|年|岁|%|元|次|倍)"
)
_THOUSANDS = re.compile(r"(?<=[0-9]),(?=[0-9]{3})")
_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
           "八": 8, "九": 9}  # fmt: skip
_POWERS = {"十": 10, "百": 100, "千": 1000}


def _normalized(text: str) -> str:
    return _THOUSANDS.sub("", "".join(unicodedata.normalize("NFKC", text).split()))


def _chinese(numeral: str) -> int:
    """十五 -> 15, 一百零五 -> 105; digits alone (二〇二六) read place by place."""
    if not any(char in _POWERS for char in numeral):
        return int("".join(str(_DIGITS[char]) for char in numeral))
    total, digit = 0, None
    for char in numeral:
        if char in _DIGITS:
            digit = _DIGITS[char]
        else:
            total += (1 if digit is None else digit) * _POWERS[char]
            digit = None
    return total + (digit or 0)


def number_tokens(text: str) -> set[str]:
    """Every "number + unit" in text, with the number written as its plain decimal value."""
    tokens = set()
    for match in _TOKEN.finditer(_normalized(text)):
        number = match["number"]
        if number[0].isdigit():
            value = format(Decimal(number).normalize(), "f")
        else:
            value = str(_chinese(number))
        tokens.add(value + match["unit"])
    return tokens


def _value_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "；".join(str(item) for item in value)
    return str(value)


def _within(text: str, limit: int) -> bool:
    return bool(text.strip()) and len(text) <= limit


def check_concept(draft: ConceptDraft, concept: ConceptInput, names: Collection[str]) -> list[str]:
    """Problem codes in a fixed order; an empty list means the draft passes."""
    problems: list[str] = []
    if not _within(draft.definition, DEFINITION_MAX):
        problems.append("DEFINITION_LENGTH")
    if not _within(draft.explanation, EXPLANATION_MAX):
        problems.append("EXPLANATION_LENGTH")
    if any(not _within(statement.text, STATEMENT_MAX) for statement in draft.statements):
        problems.append("STATEMENT_LENGTH")
    general = _normalized(draft.definition + "\n" + draft.explanation)
    if any(name and name in general for name in map(_normalized, names)):
        problems.append("PRODUCT_NAMED")
    values = {fact.slug: number_tokens(_value_text(fact.value)) for fact in concept.facts}
    if any(ref not in values for statement in draft.statements for ref in statement.refs):
        problems.append("REF_UNKNOWN")
    if any(not statement.refs for statement in draft.statements):
        problems.append("REF_MISSING")
    unsupported = unmatched = False
    for statement in draft.statements:
        stated = number_tokens(statement.text)
        cited = [values[ref] for ref in statement.refs if ref in values]
        if not stated:
            continue
        unsupported |= not stated <= set().union(*cited)
        unmatched |= any(not stated & tokens for tokens in cited)
    if unsupported:
        problems.append("NUMBER_UNSUPPORTED")
    if unmatched:
        problems.append("NUMBER_UNMATCHED_REF")
    if len(draft.statements) not in STATEMENTS:
        problems.append("STATEMENT_COUNT")
    return problems
