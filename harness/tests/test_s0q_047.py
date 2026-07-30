"""OpenSpec 047: bounded S0-Q input and diagnostic contracts."""

from __future__ import annotations

from collections.abc import Mapping

import httpx
import pytest
import respx
from pydantic import SecretStr

from insurance_harness.adapters.weknora.admin_client import WeKnoraAdminClient

_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_DIGEST_C = "c" * 64


def _revision_data() -> dict[str, object]:
    return {
        "knowledge_id": "knowledge-1",
        "parse_attempt": 3,
        "file_digest": {"algorithm": "sha256", "value": _DIGEST_A},
        "parser_identity": {
            "app_version": "v0.7.1",
            "app_commit": "80a5003cc99a427098afe184eee6601916d3d156",
            "docreader": "docreader@sha256:1234",
            "parser_engine": "docreader",
            "chunk_size": 512,
            "chunk_overlap": 64,
            "separators_digest": _DIGEST_B,
            "chunker_config_digest": _DIGEST_C,
            "embedding_model_id": "embedding-fixed",
        },
        "chunk_manifest": {
            "algorithm": "weknora.chunk_manifest.v1",
            "digest": _DIGEST_B,
            "chunk_count": 2,
        },
        "completed_at": "2026-07-30T10:00:00Z",
    }


@respx.mock
async def test_s0q_reads_typed_w1_revision_descriptor() -> None:
    route = respx.get(
        "https://weknora.example/api/v1/knowledge/knowledge-1/revision"
    ).respond(json={"success": True, "data": _revision_data()})
    client = WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        descriptor = await client.get_knowledge_revision(
            SecretStr("reader-key"),
            "knowledge-1",
        )
    finally:
        await client.aclose()

    assert route.call_count == 1
    assert descriptor.knowledge_id == "knowledge-1"
    assert descriptor.parse_attempt == 3
    assert descriptor.file_digest.value == _DIGEST_A
    assert descriptor.parser_identity.app_commit.startswith("80a5003")
    assert descriptor.chunk_manifest.algorithm == "weknora.chunk_manifest.v1"
    assert descriptor.chunk_manifest.chunk_count == 2


@respx.mock
async def test_s0q_revision_descriptor_rejects_missing_parser_identity() -> None:
    data = _revision_data()
    parser_identity = data["parser_identity"]
    assert isinstance(parser_identity, dict)
    parser_identity.pop("app_commit")
    respx.get(
        "https://weknora.example/api/v1/knowledge/knowledge-1/revision"
    ).respond(json={"success": True, "data": data})
    client = WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        with pytest.raises(ValueError, match="revision descriptor"):
            await client.get_knowledge_revision(
                SecretStr("reader-key"),
                "knowledge-1",
            )
    finally:
        await client.aclose()


def _chunk(
    *,
    chunk_id: str,
    chunk_index: int,
    attempt: int = 3,
) -> dict[str, object]:
    return {
        "id": chunk_id,
        "knowledge_id": "knowledge-1",
        "parse_attempt": attempt,
        "chunk_index": chunk_index,
        "content": f"content-{chunk_index}",
    }


def _chunk_page(
    *,
    page: int,
    items: list[dict[str, object]],
    attempt: int = 3,
) -> dict[str, object]:
    return {
        "success": True,
        "data": items,
        "total": 2,
        "page": page,
        "page_size": 1,
        "revision": {
            "knowledge_id": "knowledge-1",
            "parse_attempt": attempt,
            "manifest_digest": _DIGEST_B,
            "chunk_count": 2,
        },
    }


@respx.mock
async def test_s0q_walks_all_exact_attempt_chunk_pages() -> None:
    route = respx.get(
        "https://weknora.example/api/v1/knowledge/knowledge-1/revisions/3/chunks"
    ).mock(
        side_effect=[
            httpx.Response(
                200,
                json=_chunk_page(
                    page=1,
                    items=[_chunk(chunk_id="c1", chunk_index=0)],
                ),
            ),
            httpx.Response(
                200,
                json=_chunk_page(
                    page=2,
                    items=[_chunk(chunk_id="c2", chunk_index=1)],
                ),
            ),
        ]
    )
    client = WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        listing = await client.list_knowledge_revision_chunks(
            SecretStr("reader-key"),
            "knowledge-1",
            parse_attempt=3,
            page_size=1,
        )
    finally:
        await client.aclose()

    assert route.call_count == 2
    assert listing.revision.parse_attempt == 3
    assert listing.revision.chunk_count == listing.total == 2
    assert [item["id"] for item in listing.items] == ["c1", "c2"]


@respx.mock
async def test_s0q_rejects_cross_attempt_chunk_page() -> None:
    respx.get(
        "https://weknora.example/api/v1/knowledge/knowledge-1/revisions/3/chunks"
    ).mock(
        side_effect=[
            httpx.Response(
                200,
                json=_chunk_page(
                    page=1,
                    items=[_chunk(chunk_id="c1", chunk_index=0)],
                ),
            ),
            httpx.Response(
                200,
                json=_chunk_page(
                    page=2,
                    items=[_chunk(chunk_id="c2", chunk_index=1, attempt=4)],
                    attempt=4,
                ),
            ),
        ]
    )
    client = WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        with pytest.raises(ValueError, match="revision chunk response"):
            await client.list_knowledge_revision_chunks(
                SecretStr("reader-key"),
                "knowledge-1",
                parse_attempt=3,
                page_size=1,
            )
    finally:
        await client.aclose()


@respx.mock
async def test_s0q_deletes_only_the_exact_scratch_knowledge_base_id() -> None:
    route = respx.delete(
        "https://weknora.example/api/v1/knowledge-bases/s0q-scratch-047"
    ).respond(json={"success": True})
    client = WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        await client.delete_knowledge_base(
            SecretStr("admin-key"),
            "s0q-scratch-047",
        )
    finally:
        await client.aclose()

    assert route.call_count == 1
    request = route.calls[0].request
    assert isinstance(request.headers, Mapping)
    assert request.headers["X-API-Key"] == "admin-key"
