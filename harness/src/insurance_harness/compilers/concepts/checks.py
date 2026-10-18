"""Deterministic checks on one concept draft (S3e-3 Spec §4.1).

The general text names no entry of the release. Each statement cites claims of its concept, and
every "number + unit" it states is found in a cited value; a statement with numbers cites no value
holding none of them, so "both are 15 days" cannot cite a 20-day product. Text is compared after
NFKC with whitespace and thousands separators removed.

A number is read whole, never by a suffix: Arabic or Chinese numerals with 万, 亿 and 点 as one
run (so 一万五千元 is 15000元, not 5000元), with its minus sign (负, or a hyphen that does not
join a range: see number_tokens), and 百分之 as a percentage. Both sides are read to their
value, so 十五日 and 15日, or 10万元 and 100000元, are the same fact. A run that cannot be read,
or is longer than any amount, stays as written and so matches only the same writing: it fails
closed.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection
from decimal import Decimal

from insurance_harness.compilers.concepts.synthesis import ConceptDraft, ConceptInput

DEFINITION_MAX, EXPLANATION_MAX, STATEMENT_MAX = 120, 400, 200
STATEMENTS = range(1, 7)

_NUMERAL = "0-9.零〇一二两三四五六七八九十百千万亿点"
_UNITS = "个月|周岁|日|天|月|年|岁|%|元|次|倍"  # longer first: 个月 and 周岁 are not 月 and 岁
# A run starts at its first numeral, so no number is read by a suffix; 负 is always its sign.
_TOKEN = re.compile(
    rf"(?<![{_NUMERAL}])(?P<sign>负)?(?:百分之(?P<percent>[{_NUMERAL}]+)"
    rf"|(?P<number>[{_NUMERAL}]+)(?P<unit>{_UNITS}))"
)
_HYPHENS = "-−"
_NUMERAL_CHAR = re.compile(rf"[{_NUMERAL}]")
_LONGEST_RUN = 32  # longer runs are not read (they stay as written), which also bounds recursion
_THOUSANDS = re.compile(r"(?<=[0-9]),(?=[0-9]{3})")
_ARABIC = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
           "八": 8, "九": 9, **{str(digit): digit for digit in range(10)}}  # fmt: skip
_POWERS = {"十": 10, "百": 100, "千": 1000}
_LARGE = (("亿", 10**8), ("万", 10**4))


# A list point: a one- or two-digit integer opening a line or following a sentence or list
# separator, then a point and whitespace. Such a point is ambiguous on its own (给付金额：12. 50元
# may be 12.5元), so it counts as a list number only when the text numbers its items 1, 2, ...
# in order (a run may restart at 1, every run has at least two items). Then each of those points
# becomes a boundary before whitespace is removed ("1. 20年…；2. …" reads 20年, not 1.2年); in any
# other text every point stays a decimal point.
_LIST_POINT = re.compile(r"(^|[\n；;。：:])(\s*)([0-9]{1,2})\.(?=\s)", re.MULTILINE)


def _numbered_list(numbers: list[int]) -> bool:
    expected = 1
    for number in numbers:
        if number == expected:
            expected += 1
        elif number == 1 and expected > 2:
            expected = 2  # a new list starts once the previous one had two items
        else:
            return False
    return expected > 2


def _without_list_points(text: str) -> str:
    markers = list(_LIST_POINT.finditer(text))
    if not _numbered_list([int(marker[3]) for marker in markers]):
        return text
    return _LIST_POINT.sub(lambda marker: f"{marker[1]}{marker[2]}{marker[3]}|", text)


# One or more Chinese digits without any power, directly followed by Arabic digits, are a label
# (计划三5000元, 第一2万元): the number starts at the Arabic digits. A numeral with powers keeps
# them (一万零5元, 1万零5千元), and 零 is never a label.
_LABEL = re.compile(r"^[一二两三四五六七八九]+(?=[0-9])")


def _normalized(text: str) -> str:
    text = _without_list_points(unicodedata.normalize("NFKC", text))
    return _THOUSANDS.sub("", "".join(text.split()))


def _compact(text: str) -> str:
    """NFKC without whitespace and nothing else: names are compared as written."""
    return "".join(unicodedata.normalize("NFKC", text).split())


def _below_ten_thousand(run: str) -> Decimal | None:
    """15, 1.5, 十五, 一百零五, 5千, 三点五, 二〇二六; None when the run is not one number."""
    if _ARABIC.fullmatch(run):
        return Decimal(run)
    if "点" in run:
        whole, _, fraction = run.partition("点")
        integer = _below_ten_thousand(whole)
        if integer is None or "." in whole or not fraction:
            return None
        if any(char not in _DIGITS for char in fraction):
            return None
        return integer + Decimal("0." + "".join(str(_DIGITS[char]) for char in fraction))
    if not run or any(char not in _DIGITS and char not in _POWERS for char in run):
        return None
    if not any(char in _POWERS for char in run):
        return Decimal("".join(str(_DIGITS[char]) for char in run))  # read place by place
    total, digit, last = 0, None, 10**5
    for char in run:
        if char in _DIGITS:
            if digit not in (None, 0):
                return None  # two digits in a row, except after 零 (一百零五)
            digit = _DIGITS[char]
        else:
            power = _POWERS[char]
            if power >= last:
                return None
            total, digit, last = total + (1 if digit is None else digit) * power, None, power
    return Decimal(total + (digit or 0))


def _number(run: str) -> Decimal | None:
    for mark, power in _LARGE:
        if mark in run:
            high, _, low = run.partition(mark)
            above = _number(high) if high else Decimal(1)
            below = _number(low) if low else Decimal(0)
            if above is None or below is None or below >= power:
                return None
            return above * power + below
    return _below_ten_thousand(run)


def _token(sign: bool, run: str, unit: str) -> str:
    value = _number(run) if len(run) <= _LONGEST_RUN else None
    written = run if value is None else format(value.normalize(), "f")
    return ("-" if sign else "") + written + unit


def number_tokens(text: str) -> set[str]:
    """Every "number + unit" in text, with each number written as its signed decimal value.

    A hyphen before a number is its minus sign unless it joins a range: right after a numeral
    (18-65周岁) or right after a whole "number + unit" (18周岁-65周岁, 5000元-1万元). After a word
    that merely ends in a unit character (每年-3.5%) it stays a sign.
    """
    normalized = _normalized(text)
    tokens, previous_end = set(), -1
    for match in _TOKEN.finditer(normalized):
        start = match.start()
        hyphen = start - 1
        sign = match["sign"] is not None or (
            hyphen >= 0
            and normalized[hyphen] in _HYPHENS
            and hyphen != previous_end
            and not (hyphen >= 1 and _NUMERAL_CHAR.fullmatch(normalized[hyphen - 1]))
        )
        run = match["percent"] if match["percent"] is not None else match["number"]
        label = _LABEL.match(run)
        if label and match["percent"] is None:
            run, sign = run[label.end() :], False  # a label stands between any sign and the number
        tokens.add(_token(sign, run, "%" if match["percent"] is not None else match["unit"]))
        previous_end = match.end()
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
    general = _compact(draft.definition + "\n" + draft.explanation)
    if any(name and name in general for name in map(_compact, names)):
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
