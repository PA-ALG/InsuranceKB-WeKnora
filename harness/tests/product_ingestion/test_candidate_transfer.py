import base64
import copy
import gzip
import hashlib
import json
import typing

import pytest


def wire(value: typing.Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def example() -> tuple[typing.Any, ...]:
    source = {
        "text": "历史原文e\u0301\r\n<>&\u2028，证据",
        "revision_id": "rev",
        "block_id": "block",
    }
    field: dict[str, typing.Any] = {
        "value": None,
        "evidence": [],
        "concept_ids": [],
        "conditions": [],
        "exceptions": [],
    }
    base = {
        "scope": {"tenant_id": 1, "space_id": "space", "raw_kb_id": "raw", "wiki_kb_id": "wiki"},
        "release_id": "release",
        "activation_epoch": 9,
        "candidate_sha256": "a" * 64,
        "manifest_digest": "b" * 64,
        "published_projection": {
            "sources": [source],
            "definitions": [],
            "fields": [field],
            "pages": [],
        },
    }
    candidate = {
        "request": {
            "base_request": {
                "sources": [source, {"text": "新增原文"}],
                "existing_definitions": [],
                "existing_fields": [field],
                "existing_pages": [],
            }
        },
        "compile_result": {"output": {"definitions": [], "fields": [field], "pages": []}},
        "raw_response": "原始响应及失败原因，不得丢弃 e\u0301\r\n<>&\u2028",
    }
    return candidate, base


def encoder() -> typing.Any:
    from insurance_harness.product_ingestion.candidate_transfer import encode_candidate_transfer

    return encode_candidate_transfer


def decode_transfer_fixture(transfer: typing.Any, base: typing.Any) -> typing.Any:
    """Test receiver only; production receiving authority is Go."""
    from insurance_harness.product_ingestion.candidate_transfer import SLOTS
    from insurance_harness.product_ingestion.compilation import published_compile_members

    assert transfer["base"] == {key: base[key] for key in transfer["base"]}
    raw = gzip.decompress(base64.b64decode(transfer["payload"]))
    assert len(raw) == transfer["decoded_bytes"]
    assert hashlib.sha256(raw).hexdigest() == transfer["payload_sha256"]
    delta = json.loads(raw)
    candidate = delta["candidate"]
    for slot, (parents, key, kind) in SLOTS.items():
        parent = candidate
        for part in parents:
            parent = parent[part]
        projection = base["published_projection"]
        if kind == "sources":
            rows = projection[kind]
        elif kind == "definitions":
            rows = published_compile_members(projection, "definitions")
        elif kind == "fields":
            rows = published_compile_members(projection, "fields")
        else:
            rows = published_compile_members(projection, "pages")
        parent[key] = [
            item["inline"] if "inline" in item else rows[item["base_index"]]
            for item in delta["members"][slot]
        ]
    assert hashlib.sha256(wire(candidate)).hexdigest() == transfer["manifest_sha256"]
    return candidate


def test_reference_transfer_keeps_delta_and_response_without_mutating_inputs() -> None:
    candidate, base = example()
    before = wire((candidate, base))
    transfer = json.loads(encoder()(wire(candidate), base))
    packed = gzip.decompress(base64.b64decode(transfer["payload"]))
    delta = json.loads(packed)
    assert delta["members"]["sources"] == [{"base_index": 0}, {"inline": {"text": "新增原文"}}]
    assert delta["members"]["existing_fields"] == [{"base_index": 0}]
    assert delta["candidate"]["raw_response"] == candidate["raw_response"]
    assert "历史原文" not in packed.decode()
    assert transfer["manifest_sha256"] == hashlib.sha256(wire(candidate)).hexdigest()
    assert transfer["base"] == {
        key: value for key, value in base.items() if key != "published_projection"
    }
    assert wire((candidate, base)) == before


def test_large_original_candidate_uses_bounded_delta_encoding() -> None:
    candidate, base = example()
    candidate["raw_response"] = "重复原响应" * 600_000
    assert len(wire(candidate)) > 8 * 1024 * 1024
    assert len(encoder()(wire(candidate), base)) < 8 * 1024 * 1024


def test_null_collection_compatibility_does_not_normalize_scalar_values() -> None:
    candidate, base = example()
    base["published_projection"]["fields"][0]["evidence"] = None
    # The candidate is independent of the original projection in production.
    candidate = copy.deepcopy(candidate)
    candidate["request"]["base_request"]["existing_fields"][0]["evidence"] = []
    candidate["compile_result"]["output"]["fields"][0]["evidence"] = []
    transfer = json.loads(encoder()(wire(candidate), base))
    packed = json.loads(gzip.decompress(base64.b64decode(transfer["payload"])))
    assert packed["members"]["existing_fields"] == [{"base_index": 0}]
    candidate["request"]["base_request"]["existing_fields"][0]["value"] = []
    transfer = json.loads(encoder()(wire(candidate), base))
    packed = json.loads(gzip.decompress(base64.b64decode(transfer["payload"])))
    assert "inline" in packed["members"]["existing_fields"][0]


def test_duplicate_json_is_not_sanitized_by_encoder() -> None:
    _, base = example()
    with pytest.raises(ValueError):
        encoder()(b'{"request":{},"request":{}}', base)


def test_transport_preserves_legal_decomposed_unicode_and_line_separators() -> None:
    candidate, base = example()
    exact = "e\u0301\r\n<>&\u2028"
    candidate["request"]["base_request"]["sources"][0]["text"] = exact
    candidate["raw_response"] = exact
    transfer = json.loads(encoder()(wire(candidate), base))
    assert decode_transfer_fixture(transfer, base) == candidate
