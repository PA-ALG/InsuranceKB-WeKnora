"""WeKnora source transport: streamed download, hashes, retries, limits and cancellation."""

import asyncio
import hashlib
from pathlib import Path

import httpx
import pytest
import respx

from insurance_harness.adapters.weknora import (
    WeKnoraClientError,
    WeKnoraDownloadTooLarge,
    WeKnoraIntegrityError,
    WeKnoraTransientError,
)
from insurance_harness.config import HarnessSettings
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from tests.ingest.weknora_source.helpers import BODY, MD5, META_URL, _knowledge, _source_client

DOWNLOAD_URL = f"{META_URL}/download"
SHA256 = hashlib.sha256(BODY).hexdigest()


def _download_temp_files(tmp_path: Path) -> list[Path]:
    return list(tmp_path.glob("insurancekb-source-*"))


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
