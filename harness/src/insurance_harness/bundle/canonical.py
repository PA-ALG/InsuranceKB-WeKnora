"""The platform's member digest: canonical JSON exactly as Go writes it (S4g Spec §2.1).

S3b froze ``member_digest = sha256(json.Marshal(json.Unmarshal(payload)))`` on the Go side. Go
decodes every number as float64, sorts object keys, escapes ``<``, ``>``, ``&`` and the line and
paragraph separators, and writes all other non-ASCII characters as UTF-8. This module reproduces
that byte for byte; internal/enterprise/release/testdata/canonical_vectors.json pins both sides.
Values Go would silently rewrite (NaN, infinities, integers beyond 2^53, lone surrogates) are
refused, because their digests could not agree.
"""

import hashlib
import math
from decimal import Decimal

_SHORT_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}
_UNICODE_ESCAPED = {"<", ">", "&", "\u2028", "\u2029"}
_SAFE_INTEGER = 2**53


def canonical_json(value: object) -> bytes:
    """Compact JSON with sorted keys, identical to Go's json.Marshal of the decoded value."""
    parts: list[str] = []
    _write(value, parts)
    return "".join(parts).encode("utf-8")


def member_digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _write(value: object, parts: list[str]) -> None:
    if value is None:
        parts.append("null")
    elif value is True:
        parts.append("true")
    elif value is False:
        parts.append("false")
    elif isinstance(value, str):
        parts.append(_string(value))
    elif isinstance(value, int):
        if abs(value) > _SAFE_INTEGER:
            raise ValueError("integer beyond 2^53 would lose precision as a JSON number")
        parts.append(str(value))
    elif isinstance(value, float):
        parts.append(_float(value))
    elif isinstance(value, dict):
        parts.append("{")
        for index, key in enumerate(sorted(value)):
            if not isinstance(key, str):
                raise ValueError("object keys must be strings")
            if index:
                parts.append(",")
            parts.append(_string(key))
            parts.append(":")
            _write(value[key], parts)
        parts.append("}")
    elif isinstance(value, list | tuple):
        parts.append("[")
        for index, item in enumerate(value):
            if index:
                parts.append(",")
            _write(item, parts)
        parts.append("]")
    else:
        raise ValueError(f"{type(value).__name__} is not a JSON value")


def _string(text: str) -> str:
    out = ['"']
    for char in text:
        code = ord(char)
        if char in _SHORT_ESCAPES:
            out.append(_SHORT_ESCAPES[char])
        elif code < 0x20 or char in _UNICODE_ESCAPED:
            out.append(f"\\u{code:04x}")
        elif 0xD800 <= code <= 0xDFFF:
            raise ValueError("lone surrogate cannot be encoded as UTF-8")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _float(number: float) -> str:
    """Go's float64 encoding: shortest digits, fixed point in [1e-6, 1e21), else exponent."""
    if not math.isfinite(number):
        raise ValueError("NaN and infinities are not JSON numbers")
    if number == 0:
        return "-0" if math.copysign(1.0, number) < 0 else "0"
    shortest = Decimal(repr(number))
    if 1e-6 <= abs(number) < 1e21:
        text = format(shortest, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    sign, digits, exponent = shortest.as_tuple()
    assert isinstance(exponent, int)
    mantissa = "".join(map(str, digits)).rstrip("0") or "0"
    power = len(digits) - 1 + exponent
    head = mantissa[0] + ("." + mantissa[1:] if len(mantissa) > 1 else "")
    text = f"{'-' if sign else ''}{head}e{'+' if power >= 0 else '-'}{abs(power):02d}"
    # Go trims the leading zero of a two-digit negative exponent: e-07 becomes e-7.
    return text[:-2] + text[-1] if text[-3:-1] == "-0" else text
