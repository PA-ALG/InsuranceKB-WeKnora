"""Canonical hashing for G3 batch bodies that preserve exact multiline text."""

from __future__ import annotations

import hashlib

from .concept_free_wiki_830_g2 import concept_canonical_bytes


def _validate_object_type(object_type: str) -> None:
    if type(object_type) is not str or not object_type or not object_type.isascii():
        raise ValueError("G3 batch hash object type must be non-empty ASCII")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in object_type):
        raise ValueError("G3 batch hash object type contains a control character")


def batch_canonical_bytes_830_g3(object_type: str, payload: object) -> bytes:
    """Return the shared canonical preimage while preserving TAB/LF/CR body text."""

    _validate_object_type(object_type)
    return concept_canonical_bytes(object_type, payload)


def batch_sha256_830_g3(object_type: str, payload: object) -> str:
    """Hash one canonical G3 batch payload without adding a G2 domain suffix."""

    return hashlib.sha256(batch_canonical_bytes_830_g3(object_type, payload)).hexdigest()


__all__ = ["batch_canonical_bytes_830_g3", "batch_sha256_830_g3"]
