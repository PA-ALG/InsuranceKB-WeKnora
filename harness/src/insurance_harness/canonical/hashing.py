"""CanonicalEnvelopeV1 domain-separated SHA-256（OpenSpec 034，033 §8.4）。"""

from __future__ import annotations

import hashlib
import re
from typing import Final

from .encoder import canonical_bytes
from .errors import CanonicalEncodingError

DOMAIN_SEPARATOR: Final[bytes] = b"insurancekb.canonical-envelope"
HASH_SCHEMA_VERSION: Final[str] = "1"

_OBJECT_TYPE_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9._-]{0,63}$"
)


def canonical_hash(object_type: str, value: object) -> str:
    """返回 64 位小写 hex 的 domain-separated SHA-256。

    preimage =
    ``DOMAIN_SEPARATOR ‖ 0x00 ‖ HASH_SCHEMA_VERSION ‖ 0x00 ‖ object_type ‖
    0x00 ‖ canonical_bytes``。更换算法或编码规则必须升
    ``HASH_SCHEMA_VERSION``，不得静默重算历史对象。
    """

    if not _OBJECT_TYPE_RE.fullmatch(object_type):
        raise CanonicalEncodingError(
            "invalid_object_type",
            f"object_type {object_type!r} must match {_OBJECT_TYPE_RE.pattern}",
        )
    preimage = (
        DOMAIN_SEPARATOR
        + b"\x00"
        + HASH_SCHEMA_VERSION.encode("ascii")
        + b"\x00"
        + object_type.encode("ascii")
        + b"\x00"
        + canonical_bytes(value)
    )
    return hashlib.sha256(preimage).hexdigest()
