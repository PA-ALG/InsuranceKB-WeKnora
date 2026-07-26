"""CanonicalEnvelopeV1：唯一 canonical serialization 与 digest 合同。

OpenSpec 034（033 §8.4 C0）。语言中立规范见
``docs/insurance-kb/25-canonical-envelope-v1.md``；跨语言向量见
``vectors/canonical_vectors_v1.json``。本包零 harness 内部依赖、无 I/O。
"""

from .encoder import MAX_DEPTH, canonical_bytes
from .errors import REASON_CODES, CanonicalEncodingError
from .hashing import DOMAIN_SEPARATOR, HASH_SCHEMA_VERSION, canonical_hash
from .values import CanonicalSentinel, CanonicalSet

__all__ = [
    "MAX_DEPTH",
    "REASON_CODES",
    "DOMAIN_SEPARATOR",
    "HASH_SCHEMA_VERSION",
    "CanonicalEncodingError",
    "CanonicalSentinel",
    "CanonicalSet",
    "canonical_bytes",
    "canonical_hash",
]
