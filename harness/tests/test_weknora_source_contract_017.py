"""OpenSpec 017 B1: WeKnora source transport contract."""

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import ValidationError

from insurance_harness.adapters.weknora import (
    WeKnoraChunk,
    WeKnoraClient,
    WeKnoraClientError,
    WeKnoraDownloadTooLarge,
    WeKnoraIntegrityError,
    WeKnoraKnowledge,
    WeKnoraPaginationLimit,
    WeKnoraTransientError,
)
from insurance_harness.config import HarnessSettings
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from tests.conftest import BASE_URL

KID = "knowledge-017"
META_URL = f"{BASE_URL}/api/v1/knowledge/{KID}"
DOWNLOAD_URL = f"{META_URL}/download"
CHUNKS_URL = f"{BASE_URL}/api/v1/chunks/{KID}"
BODY = b"insurance source document"
MD5 = hashlib.md5(BODY).hexdigest()  # noqa: S324 - upstream WeKnora contract is MD5
SHA256 = hashlib.sha256(BODY).hexdigest()


def _metadata(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": KID,
        "tenant_id": "tenant-1",
        "knowledge_base_id": "kb-1",
        "title": "保险条款",
        "file_name": "terms.pdf",
        "file_type": "pdf",
        "file_size": len(BODY),
        "file_hash": MD5,
        "processed_at": "2026-07-13T08:30:00Z",
        "updated_at": "2026-07-13T08:31:00Z",
        "parse_status": "completed",
    }
    data.update(overrides)
    return data


def _knowledge(**overrides: object) -> WeKnoraKnowledge:
    return WeKnoraKnowledge.model_validate(_metadata(**overrides))


def _chunk(index: int, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": f"chunk-{index}",
        "tenant_id": "tenant-1",
        "knowledge_id": KID,
        "knowledge_base_id": "kb-1",
        "content": f"第 {index} 段",
        "chunk_index": index,
        "start_at": index * 10,
        "end_at": index * 10 + 9,
        "metadata": {"section": "保障责任"},
        "content_hash": f"hash-{index}",
    }
    data.update(overrides)
    return data


def _source_client(settings: HarnessSettings, tmp_path: Path) -> WeKnoraClient:
    configured = settings.model_copy(
        update={
            "source_max_file_bytes": 1024,
            "source_download_chunk_bytes": 4,
            "source_temp_dir": tmp_path,
        }
    )
    return WeKnoraClient(configured)


def _download_temp_files(tmp_path: Path) -> list[Path]:
    return list(tmp_path.glob("insurancekb-source-*"))


@pytest.mark.parametrize("field", ["chunk_index", "start_at", "end_at"])
@pytest.mark.parametrize("invalid", [True, "1", 1.0, -1])
def test_chunk_offsets_require_non_negative_strict_integers(
    field: str,
    invalid: object,
) -> None:
    with pytest.raises(ValidationError):
        WeKnoraChunk.model_validate(_chunk(0, **{field: invalid}))


def test_chunk_offsets_allow_none_but_reject_reversed_range() -> None:
    compatible = WeKnoraChunk.model_validate(
        _chunk(0, chunk_index=None, start_at=None, end_at=None)
    )
    assert compatible.chunk_index is None
    assert compatible.start_at is None
    assert compatible.end_at is None

    with pytest.raises(ValidationError, match="start_at"):
        WeKnoraChunk.model_validate(_chunk(0, start_at=20, end_at=19))


@pytest.mark.parametrize(
    "knowledge_id",
    ["../wiki", "x?admin=true", "x/y", "x#frag", "x" * 129],
)
@pytest.mark.parametrize("operation", ["metadata", "download", "chunks"])
@respx.mock
async def test_unsafe_knowledge_id_fails_before_any_http_request(
    client: WeKnoraClient,
    adapter_scope: KnowledgeScope,
    knowledge_id: str,
    operation: str,
) -> None:
    with pytest.raises(ScopeViolation, match="scope mismatch"):
        if operation == "metadata":
            await client.get_knowledge(adapter_scope, knowledge_id)
        elif operation == "download":
            async with client.download_knowledge(
                adapter_scope,
                _knowledge(id=knowledge_id),
            ):
                pytest.fail("unsafe download identity must not yield")
        else:
            await client.list_chunks(adapter_scope, knowledge_id)

    assert len(respx.calls) == 0


@respx.mock
async def test_numeric_metadata_identity_normalizes_to_safe_download_path(
    settings: HarnessSettings,
    adapter_scope: KnowledgeScope,
    tmp_path: Path,
) -> None:
    client = _source_client(settings, tmp_path)
    metadata_url = f"{BASE_URL}/api/v1/knowledge/123"
    download_url = f"{metadata_url}/download"
    respx.get(metadata_url).mock(
        return_value=httpx.Response(
            200,
            json={"data": _metadata(id=123)},
        )
    )
    download_route = respx.get(download_url).mock(
        return_value=httpx.Response(200, content=BODY)
    )
    try:
        knowledge = await client.get_knowledge(adapter_scope, "123")
        assert knowledge.id == 123

        async with client.download_knowledge(adapter_scope, knowledge) as downloaded:
            assert downloaded.path.read_bytes() == BODY

        assert download_route.call_count == 1
    finally:
        await client.aclose()


@pytest.mark.parametrize("unsafe_id", [True, -1])
@respx.mock
async def test_non_path_safe_numeric_metadata_identity_fails_before_download_http(
    settings: HarnessSettings,
    adapter_scope: KnowledgeScope,
    tmp_path: Path,
    unsafe_id: object,
) -> None:
    client = _source_client(settings, tmp_path)
    values = _knowledge().model_dump()
    values["id"] = unsafe_id
    knowledge = WeKnoraKnowledge.model_construct(**values)
    try:
        with pytest.raises(ScopeViolation, match="scope mismatch"):
            async with client.download_knowledge(adapter_scope, knowledge):
                pytest.fail("unsafe numeric identity must not yield")

        assert len(respx.calls) == 0
    finally:
        await client.aclose()


@respx.mock
async def test_b1_1_metadata_consumes_source_revision_fields(
    client: WeKnoraClient,
    adapter_scope: KnowledgeScope,
) -> None:
    respx.get(META_URL).mock(
        return_value=httpx.Response(200, json={"success": True, "data": _metadata()})
    )

    knowledge = await client.get_knowledge(adapter_scope, KID)

    assert knowledge.file_name == "terms.pdf"
    assert knowledge.file_type == "pdf"
    assert knowledge.file_size == len(BODY)
    assert knowledge.file_hash == MD5
    assert knowledge.processed_at == datetime(2026, 7, 13, 8, 30, tzinfo=UTC)
    assert knowledge.updated_at == datetime(2026, 7, 13, 8, 31, tzinfo=UTC)


@pytest.mark.parametrize("field", ["processed_at", "updated_at"])
@respx.mock
async def test_b1_1_naive_source_timestamp_fails_closed(
    client: WeKnoraClient,
    adapter_scope: KnowledgeScope,
    field: str,
) -> None:
    respx.get(META_URL).mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "data": _metadata(**{field: "2026-07-13T08:30:00"})},
        )
    )

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        await client.get_knowledge(adapter_scope, KID)


@pytest.mark.parametrize(
    "overrides",
    [
        {"file_size": -1},
        {"file_size": True},
        {"file_size": "25"},
        {"file_hash": "not-an-md5"},
    ],
)
@respx.mock
async def test_b1_1_malformed_file_identity_fails_closed(
    client: WeKnoraClient,
    adapter_scope: KnowledgeScope,
    overrides: dict[str, object],
) -> None:
    respx.get(META_URL).mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "data": _metadata(**overrides)},
        )
    )

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        await client.get_knowledge(adapter_scope, KID)


@pytest.mark.parametrize("failure_status", [408, 429, 503])
@respx.mock
async def test_b1_2_chunks_consume_offsets_metadata_and_restart_whole_pagination(
    client: WeKnoraClient,
    adapter_scope: KnowledgeScope,
    failure_status: int,
) -> None:
    route = respx.get(CHUNKS_URL).mock(
        side_effect=[
            httpx.Response(200, json={"data": [_chunk(0), _chunk(1)]}),
            httpx.Response(failure_status, text="retry page two"),
            httpx.Response(200, json={"data": [_chunk(0), _chunk(1)]}),
            httpx.Response(200, json={"data": [_chunk(2)]}),
        ]
    )

    chunks = await client.list_chunks(adapter_scope, KID, page_size=2)

    assert [chunk.id for chunk in chunks] == ["chunk-0", "chunk-1", "chunk-2"]
    assert chunks[0].start_at == 0
    assert chunks[0].end_at == 9
    assert chunks[0].metadata == {"section": "保障责任"}
    assert chunks[0].content_hash == "hash-0"
    assert [call.request.url.params["page"] for call in route.calls] == ["1", "2", "1", "2"]


@respx.mock
async def test_b1_6_chunk_pagination_exhaustion_never_returns_partial_list(
    client: WeKnoraClient,
    adapter_scope: KnowledgeScope,
) -> None:
    route = respx.get(CHUNKS_URL).mock(
        side_effect=[
            httpx.Response(200, json={"data": [_chunk(0), _chunk(1)]}),
            httpx.Response(503, text="page two failed"),
        ]
        * 3
    )

    with pytest.raises(WeKnoraTransientError):
        await client.list_chunks(adapter_scope, KID, page_size=2)

    assert route.call_count == 6
    assert [call.request.url.params["page"] for call in route.calls] == [
        "1",
        "2",
        "1",
        "2",
        "1",
        "2",
    ]


@respx.mock
async def test_b1_6_page_size_above_server_cap_still_fetches_every_chunk(
    client: WeKnoraClient,
    adapter_scope: KnowledgeScope,
) -> None:
    route = respx.get(CHUNKS_URL).mock(
        side_effect=[
            httpx.Response(200, json={"data": [_chunk(i) for i in range(100)]}),
            httpx.Response(200, json={"data": [_chunk(100)]}),
        ]
    )

    chunks = await client.list_chunks(adapter_scope, KID, page_size=101)

    assert len(chunks) == 101
    assert [call.request.url.params["page_size"] for call in route.calls] == ["100", "100"]


@respx.mock
async def test_b1_6_full_pages_stop_at_configured_page_limit_without_partial_result(
    settings: HarnessSettings,
    adapter_scope: KnowledgeScope,
) -> None:
    configured = settings.model_copy(
        update={"source_max_chunk_pages": 2, "source_max_chunks_per_knowledge": 100}
    )
    client = WeKnoraClient(configured)
    route = respx.get(CHUNKS_URL).mock(
        side_effect=[
            httpx.Response(200, json={"data": [_chunk(0), _chunk(1)]}),
            httpx.Response(200, json={"data": [_chunk(2), _chunk(3)]}),
        ]
    )
    try:
        with pytest.raises(WeKnoraPaginationLimit):
            await client.list_chunks(adapter_scope, KID, page_size=2)
        assert route.call_count == 2
    finally:
        await client.aclose()


@respx.mock
async def test_b1_6_chunk_count_limit_fails_without_returning_partial_result(
    settings: HarnessSettings,
    adapter_scope: KnowledgeScope,
) -> None:
    configured = settings.model_copy(
        update={"source_max_chunk_pages": 10, "source_max_chunks_per_knowledge": 3}
    )
    client = WeKnoraClient(configured)
    route = respx.get(CHUNKS_URL).mock(
        side_effect=[
            httpx.Response(200, json={"data": [_chunk(0), _chunk(1)]}),
            httpx.Response(200, json={"data": [_chunk(2), _chunk(3)]}),
        ]
    )
    try:
        with pytest.raises(WeKnoraPaginationLimit):
            await client.list_chunks(adapter_scope, KID, page_size=2)
        assert route.call_count == 2
    finally:
        await client.aclose()


@pytest.mark.parametrize("status", [408, 429, 500, 503])
@respx.mock
async def test_b1_5_idempotent_get_retries_transient_statuses(
    client: WeKnoraClient,
    adapter_scope: KnowledgeScope,
    status: int,
) -> None:
    route = respx.get(META_URL).mock(
        side_effect=[
            httpx.Response(status, text="transient"),
            httpx.Response(200, json={"data": _metadata()}),
        ]
    )

    assert (await client.get_knowledge(adapter_scope, KID)).id == KID
    assert route.call_count == 2


@respx.mock
async def test_non_idempotent_post_is_never_automatically_retried(
    client: WeKnoraClient,
) -> None:
    url = f"{BASE_URL}/api/v1/knowledgebase/wiki-kb/wiki/folders"
    route = respx.post(url).mock(return_value=httpx.Response(503, text="uncertain create"))

    with pytest.raises(WeKnoraTransientError):
        await client.create_wiki_folder("wiki-kb", "保障责任")

    assert route.call_count == 1


@respx.mock
async def test_b1_3_download_streams_validates_hash_and_cleans_success_file(
    settings: HarnessSettings,
    adapter_scope: KnowledgeScope,
    tmp_path: Path,
) -> None:
    client = _source_client(settings, tmp_path)
    route = respx.get(DOWNLOAD_URL).mock(
        return_value=httpx.Response(
            200,
            headers={"content-length": str(len(BODY))},
            content=BODY,
        )
    )
    try:
        async with client.download_knowledge(adapter_scope, _knowledge()) as downloaded:
            assert downloaded.path.read_bytes() == BODY
            assert downloaded.byte_count == len(BODY)
            assert downloaded.upstream_md5 == MD5
            assert downloaded.original_digest == SHA256
            retained_path = downloaded.path
        assert not retained_path.exists()
        assert route.call_count == 1
        assert _download_temp_files(tmp_path) == []
    finally:
        await client.aclose()


@respx.mock
async def test_b1_5_hash_mismatch_retries_complete_download_then_succeeds(
    settings: HarnessSettings,
    adapter_scope: KnowledgeScope,
    tmp_path: Path,
) -> None:
    client = _source_client(settings, tmp_path)
    bad = b"different bytes"
    route = respx.get(DOWNLOAD_URL).mock(
        side_effect=[
            httpx.Response(200, content=bad),
            httpx.Response(200, content=bad),
            httpx.Response(200, content=BODY),
        ]
    )
    try:
        async with client.download_knowledge(adapter_scope, _knowledge()) as downloaded:
            assert downloaded.original_digest == SHA256
        assert route.call_count == 3
        assert _download_temp_files(tmp_path) == []
    finally:
        await client.aclose()


@pytest.mark.parametrize("failure_status", [408, 429, 503])
@respx.mock
async def test_b1_5_download_retries_transient_statuses(
    settings: HarnessSettings,
    adapter_scope: KnowledgeScope,
    tmp_path: Path,
    failure_status: int,
) -> None:
    client = _source_client(settings, tmp_path)
    route = respx.get(DOWNLOAD_URL).mock(
        side_effect=[
            httpx.Response(failure_status, text="retry download"),
            httpx.Response(200, content=BODY),
        ]
    )
    try:
        async with client.download_knowledge(adapter_scope, _knowledge()) as downloaded:
            assert downloaded.byte_count == len(BODY)
        assert route.call_count == 2
        assert _download_temp_files(tmp_path) == []
    finally:
        await client.aclose()


class _ReadErrorStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.closed = False

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        yield b"partial"
        raise httpx.ReadTimeout("stream stalled")

    async def aclose(self) -> None:
        self.closed = True


@respx.mock
async def test_b1_5_download_retries_stream_timeout_from_a_new_response(
    settings: HarnessSettings,
    adapter_scope: KnowledgeScope,
    tmp_path: Path,
) -> None:
    client = _source_client(settings, tmp_path)
    broken = _ReadErrorStream()
    route = respx.get(DOWNLOAD_URL).mock(
        side_effect=[
            httpx.Response(200, stream=broken),
            httpx.Response(200, content=BODY),
        ]
    )
    try:
        async with client.download_knowledge(adapter_scope, _knowledge()) as downloaded:
            assert downloaded.original_digest == SHA256
        assert broken.closed
        assert route.call_count == 2
        assert _download_temp_files(tmp_path) == []
    finally:
        await client.aclose()


@respx.mock
async def test_b1_5_truncation_exhaustion_is_non_transient_and_cleans_attempts(
    settings: HarnessSettings,
    adapter_scope: KnowledgeScope,
    tmp_path: Path,
) -> None:
    client = _source_client(settings, tmp_path)
    route = respx.get(DOWNLOAD_URL).mock(
        return_value=httpx.Response(
            200,
            headers={"content-length": str(len(BODY) + 10)},
            content=BODY,
        )
    )
    try:
        with pytest.raises(WeKnoraIntegrityError) as exc:
            async with client.download_knowledge(adapter_scope, _knowledge()):
                pass
        assert not isinstance(exc.value, WeKnoraTransientError)
        assert route.call_count == 3
        assert _download_temp_files(tmp_path) == []
    finally:
        await client.aclose()


@respx.mock
async def test_b1_5_hash_mismatch_exhaustion_is_non_transient(
    settings: HarnessSettings,
    adapter_scope: KnowledgeScope,
    tmp_path: Path,
) -> None:
    client = _source_client(settings, tmp_path)
    route = respx.get(DOWNLOAD_URL).mock(
        return_value=httpx.Response(200, content=b"wrong on every attempt")
    )
    try:
        with pytest.raises(WeKnoraIntegrityError) as exc:
            async with client.download_knowledge(adapter_scope, _knowledge()):
                pass
        assert not isinstance(exc.value, WeKnoraTransientError)
        assert route.call_count == 3
        assert _download_temp_files(tmp_path) == []
    finally:
        await client.aclose()


@respx.mock
async def test_b1_3_size_limit_is_permanent_without_retry_and_cleans_file(
    settings: HarnessSettings,
    adapter_scope: KnowledgeScope,
    tmp_path: Path,
) -> None:
    client = _source_client(settings, tmp_path)
    route = respx.get(DOWNLOAD_URL).mock(
        return_value=httpx.Response(200, content=b"x" * 1025)
    )
    try:
        with pytest.raises(WeKnoraDownloadTooLarge):
            async with client.download_knowledge(adapter_scope, _knowledge()):
                pass
        assert route.call_count == 1
        assert _download_temp_files(tmp_path) == []
    finally:
        await client.aclose()


@respx.mock
async def test_b1_5_download_other_4xx_is_permanent_without_retry(
    settings: HarnessSettings,
    adapter_scope: KnowledgeScope,
    tmp_path: Path,
) -> None:
    client = _source_client(settings, tmp_path)
    route = respx.get(DOWNLOAD_URL).mock(return_value=httpx.Response(404, text="missing"))
    try:
        with pytest.raises(WeKnoraClientError) as exc:
            async with client.download_knowledge(adapter_scope, _knowledge()):
                pass
        assert exc.value.status_code == 404
        assert route.call_count == 1
        assert _download_temp_files(tmp_path) == []
    finally:
        await client.aclose()


@respx.mock
async def test_b1_4_download_scope_mismatch_fails_before_http(
    settings: HarnessSettings,
    adapter_scope: KnowledgeScope,
    tmp_path: Path,
) -> None:
    client = _source_client(settings, tmp_path)
    route = respx.get(DOWNLOAD_URL).mock(return_value=httpx.Response(200, content=BODY))
    try:
        with pytest.raises(ScopeViolation, match="scope mismatch"):
            async with client.download_knowledge(
                adapter_scope,
                _knowledge(knowledge_base_id="another-kb"),
            ):
                pass
        assert route.call_count == 0
    finally:
        await client.aclose()


class _HangingStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.closed = False

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        self.started.set()
        yield b"partial"
        await asyncio.Event().wait()

    async def aclose(self) -> None:
        self.closed = True


@respx.mock
async def test_b1_6_download_cancellation_closes_response_and_cleans_file(
    settings: HarnessSettings,
    adapter_scope: KnowledgeScope,
    tmp_path: Path,
) -> None:
    client = _source_client(settings, tmp_path)
    stream = _HangingStream()
    respx.get(DOWNLOAD_URL).mock(return_value=httpx.Response(200, stream=stream))

    async def consume() -> None:
        async with client.download_knowledge(adapter_scope, _knowledge()):
            raise AssertionError("download must not yield a partial file")

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(stream.started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed
        assert _download_temp_files(tmp_path) == []
    finally:
        await client.aclose()
