"""Value normalization ported from goldenset/normalize.py.

The goldenset/ originals are removed when that legacy directory retires in S7.
This module has no dependency on the legacy implementation. Decimal arithmetic
preserves distinct large amounts; dates are parsed after width normalization.
"""

import re
import unicodedata
from datetime import date
from decimal import Decimal

_ENUM_SYNONYMS: dict[str, str] = {
    "是": "yes", "有": "yes", "true": "yes", "支持": "yes",
    "否": "no", "无": "no", "false": "no", "不支持": "no",
}
_CN_UNIT_EXPONENT: dict[str, int] = {"百": 2, "千": 3, "万": 4, "亿": 8}
_DATE_PATTERNS = (
    re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$"),
    re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$"),
    re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日?$"),
    re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})$"),
)


def normalize_text(value: str) -> str:
    """Remove whitespace; normalize character width, punctuation and case."""
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"\s+", "", value)
    table = {
        ord("。"): ".", ord("、"): ",", ord("“"): '"', ord("”"): '"',
        ord("‘"): "'", ord("’"): "'", ord("—"): "-", ord("【"): "[", ord("】"): "]",
    }
    return value.translate(table).lower()


def _parse_date(value: str) -> date | None:
    for pattern in _DATE_PATTERNS:
        match = pattern.fullmatch(value)
        if match:
            year, month, day = (int(group) for group in match.groups())
            try:
                return date(year, month, day)
            except ValueError:
                return None
    return None


def _parse_number(value: str) -> Decimal | None:
    # Preserve enumeration punctuation: 、 must never become a thousands separator.
    text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))
    match = re.fullmatch(
        r"(?P<currency>人民币)?"
        r"(?P<number>-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
        r"(?P<units>[百千万亿]*)(?P<suffix>元|人民币|%)?",
        text,
    )
    if not match:
        return None
    if match.group("currency") and match.group("suffix") == "%":
        return None
    sign, digits, exponent = Decimal(match.group("number").replace(",", "")).as_tuple()
    assert isinstance(exponent, int)  # The numeric grammar excludes NaN and infinity.
    scale = sum(_CN_UNIT_EXPONENT[unit] for unit in match.group("units"))
    scale -= 2 if match.group("suffix") == "%" else 0
    # Multiplication/division would round to the active Decimal context precision.
    # Powers of ten only change the exponent, preserving every input digit.
    return Decimal((sign, digits, exponent + scale))


def values_equal(left: str | None, right: str | None) -> bool:
    """Compare normalized text, dates, numeric amounts and enum synonyms."""
    if left is None or right is None:
        return left is None and right is None
    number_a, number_b = _parse_number(left), _parse_number(right)
    if number_a is not None or number_b is not None:
        # A textual list must not equal a valid amount via punctuation normalization.
        return number_a is not None and number_b is not None and number_a == number_b
    a, b = normalize_text(left), normalize_text(right)
    if a == b:
        return True
    if _ENUM_SYNONYMS.get(a) is not None and _ENUM_SYNONYMS.get(a) == _ENUM_SYNONYMS.get(b):
        return True
    date_a, date_b = _parse_date(a), _parse_date(b)
    if date_a is not None and date_b is not None:
        return date_a == date_b
    return False
