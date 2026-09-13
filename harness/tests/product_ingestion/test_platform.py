from __future__ import annotations

import base64
import hashlib
import importlib
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.product_ingestion.models import ProductScope


def canonical(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
        .encode()
    )


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def module():
    try:
        return importlib.import_module("insurance_harness.product_ingestion.platform")
    except ModuleNotFoundError:
        pytest.fail("platform signed source adapter is not implemented")


@pytest.fixture
def snapshot():
    key = Ed25519PrivateKey.generate()
    scope = ProductScope(
        tenant_id="1", space_id="space", raw_knowledge_base_id="raw", wiki_knowledge_base_id="wiki"
    )
    first = "平安测试（2026）两全保险\n保险条款\n"
    text = first + "平安其他（2025）两全保险"
    native = b'{"fixture":"native page offsets"}'
    body = {
        "contract": "g3-platform-source-snapshot.830.v1",
        "scope": {"tenant_id": 1, "space_id": "space", "raw_kb_id": "raw", "wiki_kb_id": "wiki"},
        "receipt": {
            "contract": "knowledge-revision-source.v1",
            "knowledge_id": "knowledge",
            "parse_attempt": 1,
            "revision_source_id": "a" * 64,
            "file_sha256": "b" * 64,
            "object_sha256": "b" * 64,
            "size": 100,
            "mime_type": "application/pdf",
            "page_count": 2,
            "manifest_algorithm": "fixture-v1",
            "manifest_digest": "c" * 64,
            "chunk_count": 2,
            "binding_digest": "d" * 64,
            "retention_state": "persistent",
        },
        "parser_identity_sha256": "e" * 64,
        "native_capture_sha256": sha(native),
        "markdown": text,
        "native": {
            "SchemaVersion": "fixture",
            "SourceSHA256": "b" * 64,
            "RawSHA256": "f" * 64,
            "SanitizedSHA256": sha(native),
            "SanitizedJSON": base64.b64encode(native).decode(),
        },
        "chunks": [
            {"id": "block", "index": 0, "content": text, "content_sha256": sha(text.encode())},
            {
                "id": "unmapped",
                "index": 1,
                "content": "无法定位的片段",
                "content_sha256": sha("无法定位的片段".encode()),
            },
        ],
        "chunk_page_mappings": [
            {
                "chunk_id": "block",
                "status": "EXACT_BLOCK",
                "source_page_number": 1,
                "block_global_start": 0,
                "block_global_end": len(text),
                "page_spans": [
                    {
                        "page_number": 1,
                        "block_codepoint_start": 0,
                        "block_codepoint_end": len(first),
                        "global_codepoint_start": 0,
                        "global_codepoint_end": len(first),
                    },
                    {
                        "page_number": 2,
                        "block_codepoint_start": len(first),
                        "block_codepoint_end": len(text),
                        "global_codepoint_start": len(first),
                        "global_codepoint_end": len(text),
                    },
                ],
            },
            {"chunk_id": "unmapped", "status": "UNRESOLVED", "page_spans": []},
        ],
    }

    def sign(value=body):
        value = {k: v for k, v in value.items() if k != "snapshot_sha256"}
        digest = sha(value["contract"].encode() + b"\0" + canonical(value))
        domain = "weknora.g3-platform-source-snapshot.830.v1"
        return canonical(
            {
                "contract": "g3-platform-signed-source-snapshot.830.v1",
                "snapshot": {**value, "snapshot_sha256": digest},
                "authority": {
                    "contract": "g3-platform-snapshot-authority.830.v1",
                    "domain": domain,
                    "key_id": "fixture-key",
                    "payload_sha256": digest,
                    "signature": base64.b64encode(
                        key.sign(domain.encode() + b"\0" + digest.encode())
                    ).decode(),
                },
            }
        )

    return scope, body, sign, {"fixture-key": key.public_key()}


def decode(snapshot, raw=None, **kwargs):
    scope, _body, sign, keys = snapshot
    return module().decode_source_snapshot(
        raw or sign(),
        scope=scope,
        knowledge_id="knowledge",
        parse_attempt=1,
        public_keys=keys,
        **kwargs,
    )


def test_signed_platform_source_keeps_native_original_chunks_and_exact_first_page_ranges(snapshot):
    result = decode(snapshot)
    assert len(result.blocks) == 1
    assert result.unresolved_chunk_ids == ("unmapped",)
    assert len(result.snapshot["chunks"]) == 2
    first = "平安测试（2026）两全保险\n保险条款\n"
    assert result.first_page_ranges == {"block": ((0, len(first)),)}
    assert result.blocks[0].text.endswith("平安其他（2025）两全保险")
    material = result.routing_material(material_id="source-1", file_name="保险条款.pdf")
    assert material["first_page_ranges"] == result.first_page_ranges


def test_tampered_or_wrong_scope_snapshot_is_refused(snapshot):
    scope, body, sign, keys = snapshot
    altered = json.loads(sign())
    altered["snapshot"]["chunks"][0]["content"] += "伪造"
    with pytest.raises(ValueError):
        decode(snapshot, canonical(altered))
    wrong = {**body, "scope": {**body["scope"], "tenant_id": 2}}
    with pytest.raises(ValueError):
        decode(snapshot, sign(wrong))
    with pytest.raises(ValueError):
        module().decode_source_snapshot(
            sign(), scope=scope, knowledge_id="other", parse_attempt=1, public_keys=keys
        )


def test_unknown_signer_and_signed_invalid_chunk_coordinates_fail_closed(snapshot):
    scope, body, sign, _keys = snapshot
    with pytest.raises(ValueError):
        module().decode_source_snapshot(
            sign(), scope=scope, knowledge_id="knowledge", parse_attempt=1, public_keys={}
        )
    altered = json.loads(json.dumps(body))
    altered["chunk_page_mappings"][0]["page_spans"][0]["block_codepoint_end"] = 999999
    with pytest.raises(ValueError):
        decode(snapshot, sign(altered))


def test_signed_chunk_offsets_must_address_the_same_markdown_text(snapshot):
    _scope, body, sign, _keys = snapshot
    changed = json.loads(json.dumps(body))
    changed["markdown"] = "替" * len(changed["markdown"])
    with pytest.raises(ValueError, match="chunk position"):
        decode(snapshot, sign(changed))


def test_signed_processing_receipt_is_checked_in_source_decoder(snapshot):
    from tests.product_ingestion.test_processing_receipts import receipt, sealed

    _scope, body, sign, _keys = snapshot
    usage = receipt()
    usage["parse_attempt"] = 1
    body["processing_receipt"] = sealed(usage)
    assert decode(snapshot, sign(body)).snapshot["processing_receipt"]["counts"]["attempts"] == 0
    body["processing_receipt"]["counts"]["attempts"] = 9
    with pytest.raises(ValueError, match="SOURCE_PROCESSING_RECEIPT_INVALID"):
        decode(snapshot, sign(body))
