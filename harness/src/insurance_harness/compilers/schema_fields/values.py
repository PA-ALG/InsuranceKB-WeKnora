"""Data-driven value normalization, ported from V5 value_constraints.py.

Legacy originals retire in S7. Preserve conditional prose rather than guessing
an option from a substring. Amounts use exact decimal scaling; durations do not
assume that a month or year has a fixed number of days.
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from insurance_harness.compilers.schema_fields.definitions import FieldDefinition


class ValueConstraintKind(StrEnum):
    FREE_TEXT = "free_text"
    SINGLE = "single_choice"
    MULTI = "multi_choice"
    AMOUNT = "amount"
    DURATION = "duration"


@dataclass(frozen=True)
class ValueConstraint:
    kind: ValueConstraintKind
    allowed_values: tuple[str, ...] = ()
    multi_select: bool = False
    nullable: bool = False
    allow_other: bool = False


_SPLIT_OPTIONS = re.compile(r"[、,，;；]+")
_NEGATIVE = frozenset(
    {"否", "无", "false", "不可", "不能", "不可以", "不支持", "不保证", "不允许", "不得"}
)
_POSITIVE = frozenset({"是", "有", "true", "可以", "可", "支持", "保证", "允许", "能够"})
_CN_DIGITS = dict(zip("零一二三四五六七八九", range(10), strict=True)) | {"两": 2}


def parse_value_spec(spec: str | None) -> ValueConstraint:
    """Compile catalog guidance without inventing a closed set for open examples."""
    text = (spec or "").strip()
    if text in {"金额", "货币金额"}:
        return ValueConstraint(ValueConstraintKind.AMOUNT)
    if text in {"时长", "期限"}:
        return ValueConstraint(ValueConstraintKind.DURATION)
    multi = "多选" in text
    nullable = "可为空" in text or "可以为空" in text
    open_ended = bool(re.search(r"等\s*(?:[（(]|$)", text)) or any(
        marker in text for marker in ("按实际产品", "包括但不限于")
    )
    quoted = re.search(r'[“"]([^”"]+)[”"]', text)
    if quoted:
        text = quoted.group(1)
    text = text.replace("可选值", "").replace("取值为", "")

    def remove_qualifier(match: re.Match[str]) -> str:
        return (
            ""
            if any(
                marker in match.group(1)
                for marker in (
                    "多选",
                    "可为空",
                    "可以为空",
                    "标签化",
                    "按实际产品",
                )
            )
            else match.group(0)
        )

    text = re.sub(r"[（(]([^（）()]*)[）)]", remove_qualifier, text)
    text = re.sub(r"\s*等\s*$", "", text).strip()
    options = tuple(
        dict.fromkeys(part.strip() for part in _SPLIT_OPTIONS.split(text) if part.strip())
    )
    if len(options) < 2:
        return ValueConstraint(ValueConstraintKind.FREE_TEXT, nullable=nullable)
    return ValueConstraint(
        ValueConstraintKind.MULTI if multi else ValueConstraintKind.SINGLE,
        options,
        multi,
        nullable,
        open_ended or "其他" in options,
    )


def _option_key(value: str) -> str:
    # Orthographic payment-frequency variant only; never rewrite the quote.
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).replace("交", "缴")


def _single_option(value: str, constraint: ValueConstraint) -> str | None:
    key = _option_key(value)
    for option in constraint.allowed_values:
        if _option_key(option) == key:
            return option
    # Complete synonyms only. Substring matching could erase a negation or an
    # exception in expressions such as "不保证续保" or "有条件支持".
    if key in _NEGATIVE and "否" in constraint.allowed_values:
        return "否"
    if key in _POSITIVE and "是" in constraint.allowed_values:
        return "是"
    return None


def _decimal_text(number: Decimal) -> str:
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _amount(value: str) -> str:
    compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))
    match = re.fullmatch(
        r"(?:人民币)?(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
        r"(百|千|万|亿|万亿)?(?:元|人民币)?",
        compact,
    )
    if match is None:
        return value
    number = Decimal(match.group(1).replace(",", ""))
    sign, digits, exponent = number.as_tuple()
    assert isinstance(exponent, int)
    scale = {None: 0, "百": 2, "千": 3, "万": 4, "亿": 8, "万亿": 12}[match.group(2)]
    return _decimal_text(Decimal((sign, digits, exponent + scale))) + "元"


def _small_chinese_integer(text: str) -> int | None:
    if len(text) == 1 and text in _CN_DIGITS:
        return _CN_DIGITS[text]
    if text.count("十") == 1:
        left, right = text.split("十")
        if (not left or left in _CN_DIGITS) and (not right or right in _CN_DIGITS):
            return _CN_DIGITS.get(left, 1) * 10 + _CN_DIGITS.get(right, 0)
    return None


def _duration(value: str) -> str:
    compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))
    match = re.fullmatch(
        r"(\d+(?:\.\d+)?|[零一二两三四五六七八九十]+)(天|日|个月|月|年|周|小时)", compact
    )
    if match is None:
        return value
    raw_number, unit = match.groups()
    if raw_number[0].isdigit():
        number = _decimal_text(Decimal(raw_number))
    else:
        chinese = _small_chinese_integer(raw_number)
        if chinese is None:
            return value
        number = str(chinese)
    return number + {"天": "日", "月": "个月"}.get(unit, unit)


def normalize_field_value(definition: FieldDefinition, value: str | None) -> str | None:
    """Normalize only unambiguous supported values; retain all other text intact."""
    if value is None:
        return None
    constraint = parse_value_spec(definition.value_spec)
    if constraint.kind is ValueConstraintKind.AMOUNT:
        return _amount(value)
    if constraint.kind is ValueConstraintKind.DURATION:
        return _duration(value)
    if constraint.kind is ValueConstraintKind.SINGLE:
        return _single_option(value, constraint) or value
    if constraint.kind is ValueConstraintKind.MULTI:
        options = [_single_option(part, constraint) for part in _SPLIT_OPTIONS.split(value)]
        if any(option is None for option in options):
            return value
        return "、".join(option for option in constraint.allowed_values if option in options)
    return value
