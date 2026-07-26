"""CanonicalEnvelopeV1 reference 编码器（OpenSpec 034，033 §8.4）。

把受支持的 Python 值编码为 RFC 8785（JCS）兼容的确定性 UTF-8 JSON 字节。
非法输入一律以 :class:`CanonicalEncodingError` 拒绝，不静默归一化；仅有的
两处规范化是规范明文规定的 datetime→UTC 与 Decimal 定点化。
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
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    return text


def _canonical_datetime(value: _dt.datetime) -> str:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise CanonicalEncodingError(
            "naive_datetime", "datetime must be timezone-aware"
        )
    utc = value.astimezone(_dt.UTC)
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


def _tree(value: object, depth: int) -> _JsonTree:
    if isinstance(value, bool):
        return value
    if value is None:
        return {"$s": CanonicalSentinel.NULL.value}
    if isinstance(value, CanonicalSentinel):
        return {"$s": value.value}
    if isinstance(value, str):
        return _validate_text(value, role="text")
    if isinstance(value, float):
        raise CanonicalEncodingError(
            "float_forbidden", "binary float cannot participate in identity"
        )
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE_INT:
            raise CanonicalEncodingError(
                "int_out_of_range",
                f"|{value}| exceeds 2^53-1; use Decimal instead",
            )
        return value
    if isinstance(value, Decimal):
        return {"$decimal": _canonical_decimal(value)}
    if isinstance(value, _dt.datetime):
        return {"$datetime": _canonical_datetime(value)}
    if isinstance(value, _dt.date):
        return {
            "$date": f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
        }
    if depth >= MAX_DEPTH and isinstance(
        value, (CanonicalSet, set, frozenset, list, tuple, dict)
    ):
        raise CanonicalEncodingError(
            "max_depth_exceeded", f"nesting depth exceeds {MAX_DEPTH}"
        )
    if isinstance(value, (CanonicalSet, set, frozenset)):
        items = value.items if isinstance(value, CanonicalSet) else value
        encoded: dict[bytes, _JsonTree] = {}
        for item in items:
            item_tree = _tree(item, depth + 1)
            encoded.setdefault(_dumps(item_tree).encode("utf-8"), item_tree)
        return {
            "$set": [encoded[key] for key in sorted(encoded)],
        }
    if isinstance(value, (list, tuple)):
        return [_tree(item, depth + 1) for item in value]
    if isinstance(value, dict):
        members: dict[str, _JsonTree] = {}
        for key in value:
            if not isinstance(key, str):
                raise CanonicalEncodingError(
                    "non_string_key",
                    f"map key must be str, got {type(key).__name__}",
                )
            _validate_text(key, role="map key")
            if key.startswith("$"):
                raise CanonicalEncodingError(
                    "reserved_key", f"map key {key!r} uses reserved '$' prefix"
                )
        for key in sorted(value, key=lambda k: k.encode("utf-16-be")):
            members[key] = _tree(value[key], depth + 1)
        return members
    raise CanonicalEncodingError(
        "unsupported_type", f"type {type(value).__name__} is not encodable"
    )


def canonical_bytes(value: object) -> bytes:
    """按 CanonicalEnvelopeV1 编码为确定性 UTF-8 JSON 字节。"""

    return _dumps(_tree(value, depth=0)).encode("utf-8")
