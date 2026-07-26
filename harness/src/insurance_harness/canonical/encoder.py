"""CanonicalEnvelopeV1 reference 编码器（OpenSpec 034，033 §8.4）。

把受支持的 Python 值编码为 RFC 8785（JCS）兼容的确定性 UTF-8 JSON 字节。
类型判定使用 exact type（子类拒绝，防止 IntEnum/StrEnum 等与裸原语同
hash）；无序集合只受理 :class:`CanonicalSet`（裸 ``set`` 会在编码前被
Python 相等性折叠，破坏确定性与 float 拒绝）。非法输入一律以
:class:`CanonicalEncodingError` 拒绝；仅有的两处规范化是规范明文规定的
datetime→UTC 与 Decimal 定点化。
"""

from __future__ import annotations

import datetime as _dt
import json
import unicodedata
from decimal import Decimal
from typing import Final

from .errors import CanonicalEncodingError
from .values import CanonicalSentinel, CanonicalSet

MAX_DEPTH: Final[int] = 100
_MAX_SAFE_INT: Final[int] = 2**53 - 1
MAX_DECIMAL_ADJUSTED: Final[int] = 100
MAX_DECIMAL_DIGITS: Final[int] = 100

_JsonTree = str | int | bool | list["_JsonTree"] | dict[str, "_JsonTree"]


def _validate_text(text: str, *, role: str) -> str:
    for ch in text:
        code = ord(ch)
        if 0xD800 <= code <= 0xDFFF:
            raise CanonicalEncodingError(
                "surrogate_forbidden", f"{role} contains surrogate U+{code:04X}"
            )
        if code == 0x0D:
            raise CanonicalEncodingError(
                "carriage_return_forbidden", f"{role} contains U+000D"
            )
        if code < 0x20 and ch not in ("\n", "\t"):
            raise CanonicalEncodingError(
                "control_char_forbidden",
                f"{role} contains control character U+{code:04X}",
            )
    if not unicodedata.is_normalized("NFC", text):
        raise CanonicalEncodingError(
            "non_nfc_text", f"{role} is not Unicode NFC"
        )
    return text


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise CanonicalEncodingError(
            "decimal_not_finite", f"decimal {value} is not finite"
        )
    _sign, digits, _exp = value.as_tuple()
    if len(digits) > MAX_DECIMAL_DIGITS or abs(value.adjusted()) > (
        MAX_DECIMAL_ADJUSTED
    ):
        raise CanonicalEncodingError(
            "decimal_out_of_range",
            f"decimal exceeds {MAX_DECIMAL_DIGITS} digits or "
            f"10^±{MAX_DECIMAL_ADJUSTED} magnitude",
        )
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    return text


def _canonical_datetime(value: _dt.datetime) -> str:
    try:
        offset = (
            value.tzinfo.utcoffset(value) if value.tzinfo is not None else None
        )
    except (ValueError, TypeError, RuntimeError, OverflowError) as exc:
        raise CanonicalEncodingError(
            "unsupported_type", f"tzinfo failed to provide utcoffset: {exc!r}"
        ) from exc
    if offset is None:
        raise CanonicalEncodingError(
            "naive_datetime", "datetime must be timezone-aware"
        )
    try:
        utc = value.astimezone(_dt.UTC)
    except OverflowError as exc:
        raise CanonicalEncodingError(
            "datetime_out_of_range",
            "datetime cannot be represented in UTC",
        ) from exc
    text = (
        f"{utc.year:04d}-{utc.month:02d}-{utc.day:02d}"
        f"T{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}"
    )
    if utc.microsecond:
        text += "." + f"{utc.microsecond:06d}".rstrip("0")
    return text + "Z"


def _dumps(tree: _JsonTree) -> str:
    return json.dumps(
        tree, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def _tree(value: object, depth: int) -> _JsonTree:  # noqa: C901
    if type(value) is bool:
        return value
    if value is None:
        return {"$s": CanonicalSentinel.NULL.value}
    if type(value) is CanonicalSentinel:
        return {"$s": value.value}
    if type(value) is str:
        return _validate_text(value, role="text")
    if type(value) is float:
        raise CanonicalEncodingError(
            "float_forbidden", "binary float cannot participate in identity"
        )
    if type(value) is int:
        if abs(value) > _MAX_SAFE_INT:
            raise CanonicalEncodingError(
                "int_out_of_range",
                f"|{value}| exceeds 2^53-1; use Decimal instead",
            )
        return value
    if type(value) is Decimal:
        return {"$decimal": _canonical_decimal(value)}
    if type(value) is _dt.datetime:
        return {"$datetime": _canonical_datetime(value)}
    if type(value) is _dt.date:
        return {
            "$date": f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
        }
    if type(value) in (CanonicalSet, list, tuple, dict) and depth >= MAX_DEPTH:
        raise CanonicalEncodingError(
            "max_depth_exceeded", f"nesting depth exceeds {MAX_DEPTH}"
        )
    if type(value) is CanonicalSet:
        encoded: dict[bytes, _JsonTree] = {}
        for item in value.items:
            item_tree = _tree(item, depth + 1)
            encoded.setdefault(_dumps(item_tree).encode("utf-8"), item_tree)
        return {"$set": [encoded[key] for key in sorted(encoded)]}
    if type(value) is list or type(value) is tuple:
        return [_tree(item, depth + 1) for item in value]
    if type(value) is dict:
        for key in value:
            if type(key) is not str:
                raise CanonicalEncodingError(
                    "non_string_key",
                    f"map key must be str, got {type(key).__name__}",
                )
            _validate_text(key, role="map key")
            if key.startswith("$"):
                raise CanonicalEncodingError(
                    "reserved_key", f"map key {key!r} uses reserved '$' prefix"
                )
        members: dict[str, _JsonTree] = {}
        for key in sorted(value, key=lambda k: k.encode("utf-16-be")):
            members[key] = _tree(value[key], depth + 1)
        return members
    raise CanonicalEncodingError(
        "unsupported_type", f"type {type(value).__name__} is not encodable"
    )


def canonical_bytes(value: object) -> bytes:
    """按 CanonicalEnvelopeV1 编码为确定性 UTF-8 JSON 字节。"""

    return _dumps(_tree(value, depth=0)).encode("utf-8")
