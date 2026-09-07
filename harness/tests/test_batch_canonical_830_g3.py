from __future__ import annotations

import hashlib
import importlib
import importlib.util

import pytest

from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    concept_canonical_bytes,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import (
    schema_wiki_canonical_bytes,
    schema_wiki_sha256,
)


def _canonical_api() -> tuple[object, object]:
    name = "insurance_harness.knowledge_compiler.batch_canonical_830_g3"
    if importlib.util.find_spec(name) is None:
        return schema_wiki_canonical_bytes, schema_wiki_sha256
    module = importlib.import_module(name)
    return module.batch_canonical_bytes_830_g3, module.batch_sha256_830_g3


def test_multiline_body_is_preserved_and_line_endings_are_distinct() -> None:
    canonical, sha256 = _canonical_api()
    lf = {"material_id": "m1", "body": "first\nsecond"}
    crlf = {"material_id": "m1", "body": "first\r\nsecond"}

    lf_bytes = canonical("corpus-entry.830.g3.v1", lf)  # type: ignore[operator]
    crlf_bytes = canonical("corpus-entry.830.g3.v1", crlf)  # type: ignore[operator]

    assert lf_bytes.endswith(b'{"body":"first\\nsecond","material_id":"m1"}')
    assert crlf_bytes.endswith(b'{"body":"first\\r\\nsecond","material_id":"m1"}')
    assert lf_bytes != crlf_bytes
    assert sha256("corpus-entry.830.g3.v1", lf) == hashlib.sha256(lf_bytes).hexdigest()  # type: ignore[operator]
    assert sha256("corpus-entry.830.g3.v1", crlf) == hashlib.sha256(crlf_bytes).hexdigest()  # type: ignore[operator]


def test_control_free_payload_is_byte_identical_to_shared_canonical() -> None:
    canonical, sha256 = _canonical_api()
    payload = {"contract": "fixture.v1", "id": "m1", "values": ["中文", 1, True, None]}

    assert canonical("fixture.v1", payload) == concept_canonical_bytes("fixture.v1", payload)  # type: ignore[operator]
    assert sha256("fixture.v1", payload) == schema_wiki_sha256("fixture.v1", payload)  # type: ignore[operator]


def test_domain_and_body_invalid_values_remain_rejected() -> None:
    canonical, _ = _canonical_api()
    for domain in ("", "域.v1", "bad\ndomain"):
        with pytest.raises((TypeError, ValueError, UnicodeEncodeError)):
            canonical(domain, {"value": "ok"})  # type: ignore[operator]
    for value in ("bad\x00body", "bad\x7fbody", "e\u0301"):
        with pytest.raises((TypeError, ValueError)):
            canonical("fixture.v1", {"value": value})  # type: ignore[operator]
    with pytest.raises((TypeError, ValueError)):
        canonical("fixture.v1", {"value": 1.5})  # type: ignore[operator]
    with pytest.raises((TypeError, ValueError)):
        canonical("fixture.v1", {"bad\nkey": "value"})  # type: ignore[operator]
