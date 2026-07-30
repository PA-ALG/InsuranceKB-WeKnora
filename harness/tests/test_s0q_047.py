"""OpenSpec 047: bounded S0-Q input and diagnostic contracts."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256

import httpx
import pytest
import respx
from pydantic import SecretStr

import insurance_harness.s0q_047 as s0q
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


def _reference_manifest_digest(
    chunks: list[dict[str, object]],
    *,
    knowledge_id: str = "knowledge-1",
    parse_attempt: int = 3,
) -> str:
    lines = [
        "weknora.chunk_manifest",
        "v1",
        knowledge_id,
        str(parse_attempt),
        str(len(chunks)),
    ]
    for chunk in chunks:
        content = chunk["content"]
        assert isinstance(content, str)
        lines.append(
            f"{chunk['chunk_index']}:{chunk['id']}:"
            f"{sha256(content.encode()).hexdigest()}"
        )
    return sha256(("\n".join(lines) + "\n").encode()).hexdigest()


def _bundle_payload() -> dict[str, object]:
    chunks: list[dict[str, object]] = [
        {
            "id": "chunk-1",
            "knowledge_id": "knowledge-1",
            "parse_attempt": 3,
            "chunk_index": 0,
            "content": "本合同为不保证续保合同。",
            "start_at": 0,
            "end_at": 13,
            "page_number": 30,
            "structural_type": "text",
        },
        {
            "id": "chunk-2",
            "knowledge_id": "knowledge-1",
            "parse_attempt": 3,
            "chunk_index": 1,
            "content": "计划一免赔额10000元；计划二免赔额0元。",
            "start_at": 14,
            "end_at": 36,
            "page_number": 31,
            "structural_type": "table",
        },
    ]
    return {
        "artifact_kind": "weknora_w1_exact_revision",
        "capture_state": "completed",
        "text_origin": "w1_exact_attempt_chunks",
        "source_path": "dataset/source/terms.pdf",
        "source_bytes": 1234,
        "source_sha256": _DIGEST_A,
        "knowledge_id": "knowledge-1",
        "parse_attempt": 3,
        "parser_identity": _revision_data()["parser_identity"],
        "completed_at": "2026-07-30T10:00:00Z",
        "manifest": {
            "algorithm": "weknora.chunk_manifest.v1",
            "digest": _reference_manifest_digest(chunks),
            "chunk_count": 2,
        },
        "chunks": chunks,
        "anchors": [
            {
                "page_number": 30,
                "chunk_id": "chunk-1",
                "quote": "不保证续保",
                "structural_type": "text",
            },
            {
                "page_number": 31,
                "chunk_id": "chunk-2",
                "quote": "计划一免赔额10000元",
                "structural_type": "table",
            },
        ],
    }


def test_s0q_canonical_json_is_mapping_order_independent() -> None:
    left = {"b": 2, "a": {"y": 2, "x": 1}}
    right = {"a": {"x": 1, "y": 2}, "b": 2}

    assert s0q.canonical_json_bytes(left) == s0q.canonical_json_bytes(right)
    assert s0q.canonical_sha256(left) == s0q.canonical_sha256(right)


def test_s0q_admits_complete_digest_bound_w1_bundle() -> None:
    bundle = s0q.admit_frozen_w1_bundle(
        _bundle_payload(),
        expected_source_path="dataset/source/terms.pdf",
        expected_source_sha256=_DIGEST_A,
        required_table_page=31,
    )

    assert bundle.parse_attempt == 3
    assert bundle.manifest.chunk_count == len(bundle.chunks) == 2
    assert len(bundle.bundle_digest) == 64
    with pytest.raises(Exception, match="frozen"):
        bundle.source_path = "other.pdf"


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda payload: payload["parser_identity"].pop("app_commit"),
            "parser identity",
        ),
        (
            lambda payload: payload["manifest"].__setitem__("digest", _DIGEST_C),
            "manifest digest",
        ),
        (
            lambda payload: payload["chunks"].reverse(),
            "chunk order",
        ),
        (
            lambda payload: payload["anchors"][1].__setitem__("quote", "不存在的引文"),
            "anchor",
        ),
    ],
)
def test_s0q_bundle_failures_are_typed_blocked_on_input(
    mutate: object,
    reason: str,
) -> None:
    payload = _bundle_payload()
    assert callable(mutate)
    mutate(payload)

    with pytest.raises(s0q.S0QBlockedOnInput, match=reason) as exc_info:
        s0q.admit_frozen_w1_bundle(
            payload,
            expected_source_path="dataset/source/terms.pdf",
            expected_source_sha256=_DIGEST_A,
            required_table_page=31,
        )

    assert exc_info.value.status == "BLOCKED_ON_INPUT"
    assert exc_info.value.bucket == s0q.S0QErrorBucket.INPUT_INTEGRITY


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("capture_state", "draft"),
        ("text_origin", "manually_cleaned_markdown"),
    ],
)
def test_s0q_rejects_draft_or_manually_cleaned_input(
    key: str,
    value: str,
) -> None:
    payload = _bundle_payload()
    payload[key] = value

    with pytest.raises(s0q.S0QBlockedOnInput):
        s0q.admit_frozen_w1_bundle(
            payload,
            expected_source_path="dataset/source/terms.pdf",
            expected_source_sha256=_DIGEST_A,
            required_table_page=31,
        )


def test_s0q_requires_table_anchor_on_the_frozen_page() -> None:
    payload = _bundle_payload()
    anchors = payload["anchors"]
    assert isinstance(anchors, list)
    anchors.pop()

    with pytest.raises(s0q.S0QBlockedOnInput, match="table anchor"):
        s0q.admit_frozen_w1_bundle(
            payload,
            expected_source_path="dataset/source/terms.pdf",
            expected_source_sha256=_DIGEST_A,
            required_table_page=31,
        )
