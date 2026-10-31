"""Local-live provisioning: knowledge lookup by SHA-256, parse attempts and typed chunks."""

from __future__ import annotations

import json
from importlib import import_module

import pytest
import respx
from pydantic import SecretStr


@respx.mock
async def test_r3_3_find_knowledge_by_sha256_paginates_beyond_first_page() -> None:
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    base = "https://weknora.example/api/v1/knowledge-bases/raw-kb/knowledge"
    digest = "a" * 64
    first_page = respx.get(
        base,
        params={"page": 1, "page_size": 100},
    ).respond(
        json={
            "success": True,
            "data": [
                {"id": f"other-{index}", "metadata": {"sha256": "b" * 64}}
                for index in range(100)
            ],
            "total": 101,
            "page": 1,
            "page_size": 100,
        }
    )
    second_page = respx.get(
        base,
        params={"page": 2, "page_size": 100},
    ).respond(
        json={
            "success": True,
            "data": [{"id": "matching-101", "metadata": {"sha256": digest}}],
            "total": 101,
            "page": 2,
            "page_size": 100,
        }
    )
    client = admin.WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        matches = await client.find_knowledge_by_sha256(
            SecretStr("tenant-key"),
            "raw-kb",
            digest,
        )
    finally:
        await client.aclose()

    assert [item["id"] for item in matches] == ["matching-101"]
    assert first_page.called and second_page.called


@respx.mock
async def test_r3_3_parse_attempt_reads_strict_span_envelope() -> None:
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    route = respx.get(
        "https://weknora.example/api/v1/knowledge/knowledge-1/spans"
    ).respond(
        json={
            "success": True,
            "data": {"knowledge_id": "knowledge-1", "current_attempt": 3},
        }
    )
    client = admin.WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        attempt = await client.get_knowledge_parse_attempt(
            SecretStr("tenant-key"), "knowledge-1"
        )
    finally:
        await client.aclose()

    assert attempt == 3
    assert route.called


@pytest.mark.parametrize(
    "data",
    (
        {"knowledge_id": "other", "current_attempt": 3},
        {"knowledge_id": "knowledge-1", "current_attempt": 0},
        {"knowledge_id": "knowledge-1", "current_attempt": True},
        {"knowledge_id": "knowledge-1"},
    ),
)
@respx.mock
async def test_r3_3_parse_attempt_rejects_mismatched_identity_and_invalid_attempt(
    data: dict[str, object],
) -> None:
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    respx.get(
        "https://weknora.example/api/v1/knowledge/knowledge-1/spans"
    ).respond(json={"success": True, "data": data})
    client = admin.WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        with pytest.raises(ValueError, match="span"):
            await client.get_knowledge_parse_attempt(
                SecretStr("tenant-key"), "knowledge-1"
            )
    finally:
        await client.aclose()


@respx.mock
async def test_r3_3_typed_chunks_preserve_outer_pagination_and_plain_defaults_text() -> None:
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    base = "https://weknora.example/api/v1/chunks/knowledge-1"
    plain = respx.get(base, params={"page": 1, "page_size": 100}).respond(
        json={"success": True, "data": [{"id": "text-1"}]}
    )
    ocr_1 = respx.get(
        base,
        params={"page": 1, "page_size": 1, "chunk_type": "image_ocr"},
    ).respond(
        json={
            "success": True,
            "data": [{"id": "ocr-1"}],
            "total": 2,
            "page": 1,
            "page_size": 1,
        }
    )
    ocr_2 = respx.get(
        base,
        params={"page": 2, "page_size": 1, "chunk_type": "image_ocr"},
    ).respond(
        json={
            "success": True,
            "data": [{"id": "ocr-2"}],
            "total": 2,
            "page": 2,
            "page_size": 1,
        }
    )
    caption = respx.get(
        base,
        params={"page": 1, "page_size": 1, "chunk_type": "image_caption"},
    ).respond(
        json={
            "success": True,
            "data": [{"id": "caption-1"}],
            "total": 1,
            "page": 1,
            "page_size": 1,
        }
    )
    reparse = respx.post(
        "https://weknora.example/api/v1/knowledge/knowledge-1/reparse"
    ).respond(json={"success": True, "data": {"id": "knowledge-1"}})
    client = admin.WeKnoraAdminClient("https://weknora.example/api/v1")
    key = SecretStr("tenant-key")
    config = admin.KnowledgeProcessConfig(
        enable_multimodel=True,
        vlm_config=admin.VLMProcessConfig(enabled=True, model_id="vlm-1"),
    )
    try:
        assert await client.list_chunks(key, "knowledge-1") == [{"id": "text-1"}]
        ocr = await client.list_typed_chunks(
            key, "knowledge-1", chunk_type="image_ocr", page_size=1
        )
        captions = await client.list_typed_chunks(
            key, "knowledge-1", chunk_type="image_caption", page_size=1
        )
        assert await client.reparse_knowledge(key, "knowledge-1", config) == {
            "id": "knowledge-1"
        }
    finally:
        await client.aclose()

    assert [item["id"] for item in ocr.items] == ["ocr-1", "ocr-2"]
    assert (ocr.total, ocr.page, ocr.page_size) == (2, 2, 1)
    assert [item["id"] for item in captions.items] == ["caption-1"]
    assert plain.called and ocr_1.called and ocr_2.called and caption.called
    assert "chunk_type" not in plain.calls[0].request.url.params
    assert json.loads(reparse.calls[0].request.content) == {
        "process_config": config.as_payload()
    }
