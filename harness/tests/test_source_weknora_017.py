"""WeKnora DocumentSource contracts for OpenSpec 017 T3."""

import asyncio
import hashlib
import json
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

import insurance_harness.sources.weknora as weknora_source_module
from insurance_harness.adapters.weknora import (
    DownloadedKnowledge,
    WeKnoraChunk,
    WeKnoraIntegrityError,
    WeKnoraKnowledge,
)
from insurance_harness.config import HarnessSettings
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.goldenset.pdf import PageText, ScannedPdfError
from insurance_harness.sources import (
    MaterializationStage,
    SourceMaterializationError,
    WeKnoraDocumentSource,
    WeKnoraSourceRequest,
)
from insurance_harness.sources.models import ProcessedAtOrdering, SourceRevision

BODY_A = b"source document a"
BODY_B = b"source document b"
PROCESSED_AT = datetime(2026, 7, 14, 2, 30, tzinfo=UTC)


def _knowledge(knowledge_id: str, **overrides: object) -> WeKnoraKnowledge:
    body = BODY_A if knowledge_id == "knowledge-a" else BODY_B
    values: dict[str, object] = {
        "id": knowledge_id,
        "tenant_id": "tenant-source",
        "knowledge_base_id": "raw-source",
        "title": f"Title {knowledge_id}",
        "file_name": f"{knowledge_id}.pdf",
        "file_type": "application/pdf",
        "file_size": len(body),
        "file_hash": hashlib.md5(body, usedforsecurity=False).hexdigest(),
        "processed_at": PROCESSED_AT,
        "updated_at": PROCESSED_AT + timedelta(minutes=1),
        "parse_status": "completed",
        "error_message": "",
    }
    values.update(overrides)
    return WeKnoraKnowledge.model_validate(values)


def _chunk(knowledge_id: str, index: int = 0) -> WeKnoraChunk:
    return WeKnoraChunk(
        id=f"{knowledge_id}-chunk-{index}",
        tenant_id="tenant-source",
        knowledge_id=knowledge_id,
        knowledge_base_id="raw-source",
        chunk_index=index,
        start_at=index * 20,
        end_at=index * 20 + 19,
        content=f"chunk content {knowledge_id} {index}",
        content_hash=f"content-hash-{knowledge_id}-{index}",
        metadata={
            "section": "benefits",
            "nested": {"labels": ["insurance", knowledge_id]},
        },
    )


def _download(
    tmp_path: Path,
    knowledge_id: str,
    *,
    body: bytes | None = None,
    byte_count: int | None = None,
    upstream_md5: str | None = None,
    original_digest: str | None = None,
) -> DownloadedKnowledge:
    content = body if body is not None else (
        BODY_A if knowledge_id == "knowledge-a" else BODY_B
    )
    path = tmp_path / f"download-{knowledge_id}.pdf"
    path.write_bytes(content)
    return DownloadedKnowledge(
        path=path,
        byte_count=len(content) if byte_count is None else byte_count,
        upstream_md5=(
            hashlib.md5(content, usedforsecurity=False).hexdigest()
            if upstream_md5 is None
            else upstream_md5
        ),
        original_digest=(
            hashlib.sha256(content).hexdigest()
            if original_digest is None
            else original_digest
        ),
    )


MetadataResult = WeKnoraKnowledge | BaseException
DownloadResult = DownloadedKnowledge | BaseException
ChunkResult = list[WeKnoraChunk] | BaseException


class _FakeWeKnoraClient:
    """In-memory adapter boundary with the real context-managed download semantics."""

    def __init__(
        self,
        *,
        metadata: dict[str, list[MetadataResult]],
        downloads: dict[str, DownloadResult],
        chunks: dict[str, ChunkResult],
    ) -> None:
        self.metadata = metadata
        self.downloads = downloads
        self.chunks = chunks
        self.calls: list[str] = []
        self.metadata_call_counts: dict[str, int] = {}
        self.chunk_started: dict[str, asyncio.Event] = {}
        self.chunk_release: dict[str, asyncio.Event] = {}

    async def get_knowledge(
        self,
        scope: KnowledgeScope,
        knowledge_id: str,
    ) -> WeKnoraKnowledge:
        del scope
        self.calls.append(f"metadata:{knowledge_id}")
        call_index = self.metadata_call_counts.get(knowledge_id, 0)
        self.metadata_call_counts[knowledge_id] = call_index + 1
        versions = self.metadata[knowledge_id]
        result = versions[min(call_index, len(versions) - 1)]
        if isinstance(result, BaseException):
            raise result
        return result

    @asynccontextmanager
    async def download_knowledge(
        self,
        scope: KnowledgeScope,
        knowledge: WeKnoraKnowledge,
    ) -> AsyncIterator[DownloadedKnowledge]:
        del scope
        knowledge_id = str(knowledge.id)
        self.calls.append(f"download_enter:{knowledge_id}")
        result = self.downloads[knowledge_id]
        if isinstance(result, BaseException):
            raise result
        try:
            yield result
        finally:
            result.path.unlink(missing_ok=True)
            self.calls.append(f"download_exit:{knowledge_id}")

    async def list_chunks(
        self,
        scope: KnowledgeScope,
        knowledge_id: str,
    ) -> list[WeKnoraChunk]:
        del scope
        self.calls.append(f"chunks:{knowledge_id}")
        started = self.chunk_started.get(knowledge_id)
        release = self.chunk_release.get(knowledge_id)
        if started is not None and release is not None:
            started.set()
            await release.wait()
        result = self.chunks[knowledge_id]
        if isinstance(result, BaseException):
            raise result
        return result


def _client(
    tmp_path: Path,
    *knowledge_ids: str,
) -> _FakeWeKnoraClient:
    return _FakeWeKnoraClient(
        metadata={knowledge_id: [_knowledge(knowledge_id)] for knowledge_id in knowledge_ids},
        downloads={
            knowledge_id: _download(tmp_path, knowledge_id)
            for knowledge_id in knowledge_ids
        },
        chunks={knowledge_id: [_chunk(knowledge_id)] for knowledge_id in knowledge_ids},
    )


def _source(
    client: _FakeWeKnoraClient,
    bound_scope: Callable[..., KnowledgeScope],
    *,
    page_loader: Callable[[Path], list[PageText]] | None = None,
) -> WeKnoraDocumentSource:
    scope = bound_scope(
        tenant_id="tenant-source",
        raw_kb_id="raw-source",
        wiki_kb_id="wiki-source",
    )
    return WeKnoraDocumentSource(
        client=client,
        scope=scope,
        parser_fingerprint="pdfplumber@0.11:text-v1",
        page_loader=page_loader or (lambda _: [PageText(page_no=1, text="policy page")]),
    )


def _source_with_limits(
    client: _FakeWeKnoraClient,
    bound_scope: Callable[..., KnowledgeScope],
    *,
    source_max_documents_per_batch: int = 8,
    source_max_batch_bytes: int = 256 * 1024 * 1024,
    source_max_batch_pages: int = 20_000,
    source_max_batch_chunks: int = 200_000,
    page_loader: Callable[[Path], list[PageText]] | None = None,
) -> WeKnoraDocumentSource:
    scope = bound_scope(
        tenant_id="tenant-source",
        raw_kb_id="raw-source",
        wiki_kb_id="wiki-source",
    )
    return WeKnoraDocumentSource(
        client=client,
        scope=scope,
        parser_fingerprint="pdfplumber@0.11:text-v1",
        page_loader=page_loader or (lambda _: [PageText(page_no=1, text="policy page")]),
        source_max_documents_per_batch=source_max_documents_per_batch,
        source_max_batch_bytes=source_max_batch_bytes,
        source_max_batch_pages=source_max_batch_pages,
        source_max_batch_chunks=source_max_batch_chunks,
    )


def test_weknora_request_is_non_empty_unique_and_serializable() -> None:
    request = WeKnoraSourceRequest.model_validate(
        {"knowledge_ids": [" knowledge-a ", "knowledge-b"]}
    )

    assert request.knowledge_ids == ("knowledge-a", "knowledge-b")
    assert json.loads(request.model_dump_json()) == {
        "knowledge_ids": ["knowledge-a", "knowledge-b"]
    }

    for invalid in (
        [],
        [""],
        ["   "],
        ["knowledge-a", "knowledge-a"],
        ["knowledge-a", " knowledge-a "],
        ["../wiki"],
        ["x?admin=true"],
        ["x/y"],
        ["x#frag"],
        ["x" * 129],
    ):
        with pytest.raises(ValidationError):
            WeKnoraSourceRequest.model_validate({"knowledge_ids": invalid})

    uuid = "0193b8a0-1111-7000-8000-000000000001"
    assert WeKnoraSourceRequest(knowledge_ids=(uuid, "knowledge-a")).knowledge_ids == (
        uuid,
        "knowledge-a",
    )


def test_batch_limit_settings_defaults_and_positive_validation(
    settings: HarnessSettings,
) -> None:
    assert settings.source_max_documents_per_batch == 8
    assert settings.source_max_batch_bytes == 256 * 1024 * 1024
    assert settings.source_max_batch_pages == 20_000
    assert settings.source_max_batch_chunks == 200_000

    for field in (
        "source_max_documents_per_batch",
        "source_max_batch_bytes",
        "source_max_batch_pages",
        "source_max_batch_chunks",
    ):
        values = settings.model_dump()
        values[field] = 0
        with pytest.raises(ValidationError):
            HarnessSettings.model_validate(values)


@pytest.mark.parametrize(
    "limit_name",
    [
        "source_max_documents_per_batch",
        "source_max_batch_bytes",
        "source_max_batch_pages",
        "source_max_batch_chunks",
    ],
)
@pytest.mark.parametrize("invalid", [0, -1, True, 1.5])
def test_weknora_source_requires_positive_integer_batch_limits(
    bound_scope: Callable[..., KnowledgeScope],
    tmp_path: Path,
    limit_name: str,
    invalid: int,
) -> None:
    client = _client(tmp_path, "knowledge-a")

    with pytest.raises(ValueError, match=limit_name):
        _source_with_limits(
            client,
            bound_scope,
            source_max_documents_per_batch=(
                invalid if limit_name == "source_max_documents_per_batch" else 8
            ),
            source_max_batch_bytes=(
                invalid if limit_name == "source_max_batch_bytes" else 256 * 1024 * 1024
            ),
            source_max_batch_pages=(
                invalid if limit_name == "source_max_batch_pages" else 20_000
            ),
            source_max_batch_chunks=(
                invalid if limit_name == "source_max_batch_chunks" else 200_000
            ),
        )


@pytest.mark.asyncio
async def test_document_limit_fails_before_any_client_call(
    bound_scope: Callable[..., KnowledgeScope],
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, "knowledge-a", "knowledge-b")
    source = _source_with_limits(
        client,
        bound_scope,
        source_max_documents_per_batch=1,
    )
    yielded = False

    with pytest.raises(SourceMaterializationError) as caught:
        async with source.materialize(
            WeKnoraSourceRequest(knowledge_ids=("knowledge-a", "knowledge-b"))
        ):
            yielded = True

    assert yielded is False
    assert caught.value.stage is MaterializationStage.METADATA
    assert client.calls == []


@pytest.mark.parametrize(
    ("budget", "expected_stage"),
    [
        ("bytes", MaterializationStage.DOWNLOAD),
        ("pages", MaterializationStage.PAGE_PARSE),
        ("chunks", MaterializationStage.CHUNKS),
    ],
)
@pytest.mark.asyncio
async def test_cumulative_batch_budget_failure_cleans_all_downloads_and_never_yields(
    bound_scope: Callable[..., KnowledgeScope],
    tmp_path: Path,
    budget: str,
    expected_stage: MaterializationStage,
) -> None:
    client = _client(tmp_path, "knowledge-a", "knowledge-b")
    first = client.downloads["knowledge-a"]
    second = client.downloads["knowledge-b"]
    assert isinstance(first, DownloadedKnowledge)
    assert isinstance(second, DownloadedKnowledge)
    limits = {
        "source_max_batch_bytes": len(BODY_A) if budget == "bytes" else 10_000,
        "source_max_batch_pages": 1 if budget == "pages" else 10_000,
        "source_max_batch_chunks": 1 if budget == "chunks" else 10_000,
    }
    source = _source_with_limits(
        client,
        bound_scope,
        source_max_batch_bytes=limits["source_max_batch_bytes"],
        source_max_batch_pages=limits["source_max_batch_pages"],
        source_max_batch_chunks=limits["source_max_batch_chunks"],
    )
    yielded = False

    with pytest.raises(SourceMaterializationError) as caught:
        async with source.materialize(
            WeKnoraSourceRequest(knowledge_ids=("knowledge-a", "knowledge-b"))
        ):
            yielded = True

    assert yielded is False
    assert caught.value.stage is expected_stage
    assert not first.path.exists()
    assert not second.path.exists()


def test_weknora_source_requires_attested_scope_and_explicit_non_empty_parser(
    bound_scope: Callable[..., KnowledgeScope],
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, "knowledge-a")
    forged = KnowledgeScope(
        space_id="space-forged",
        tenant_id="tenant-source",
        raw_kb_id="raw-source",
        wiki_kb_id="wiki-source",
    )

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        WeKnoraDocumentSource(
            client=client,
            scope=forged,
            parser_fingerprint="parser-v1",
        )

    scope = bound_scope(
        tenant_id="tenant-source",
        raw_kb_id="raw-source",
        wiki_kb_id="wiki-source",
    )
    with pytest.raises(ValueError, match="parser_fingerprint"):
        WeKnoraDocumentSource(client=client, scope=scope, parser_fingerprint="  ")


@pytest.mark.asyncio
async def test_materialize_success_preserves_dtos_sequence_revision_and_path_lifetime(
    bound_scope: Callable[..., KnowledgeScope],
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, "knowledge-a", "knowledge-b")
    loader_threads: list[int] = []
    caller_thread = threading.get_ident()

    def page_loader(path: Path) -> list[PageText]:
        assert path.exists()
        loader_threads.append(threading.get_ident())
        client.calls.append(f"page:{path.stem.removeprefix('download-')}")
        return [PageText(page_no=1, text=f"page from {path.name}")]

    source = _source(client, bound_scope, page_loader=page_loader)
    request = WeKnoraSourceRequest(knowledge_ids=("knowledge-a", "knowledge-b"))

    async with source.materialize(request) as batch:
        assert client.calls == [
            "metadata:knowledge-a",
            "download_enter:knowledge-a",
            "page:knowledge-a",
            "chunks:knowledge-a",
            "metadata:knowledge-a",
            "metadata:knowledge-b",
            "download_enter:knowledge-b",
            "page:knowledge-b",
            "chunks:knowledge-b",
            "metadata:knowledge-b",
        ]
        assert loader_threads and all(thread_id != caller_thread for thread_id in loader_threads)
        assert [document.source_id for document in batch.documents] == [
            "knowledge-a",
            "knowledge-b",
        ]
        assert set(batch.local_paths) == {"knowledge-a", "knowledge-b"}
        assert all(path.exists() for path in batch.local_paths.values())
        assert "local_paths" not in batch.model_dump(mode="json")

        first = batch.documents[0]
        expected_revision = SourceRevision(
            file_hash=hashlib.md5(BODY_A, usedforsecurity=False).hexdigest(),
            ordering=ProcessedAtOrdering(value=PROCESSED_AT),
            parser_fingerprint="pdfplumber@0.11:text-v1",
        )
        assert first.scope is not None
        assert first.scope.model_dump() == {
            "space_id": first.scope.space_id,
            "tenant_id": "tenant-source",
            "raw_kb_id": "raw-source",
            "wiki_kb_id": "wiki-source",
        }
        assert first.knowledge_id == "knowledge-a"
        assert first.raw_kb_id == "raw-source"
        assert first.title == "Title knowledge-a"
        assert first.file_name == "knowledge-a.pdf"
        assert first.file_type == "application/pdf"
        assert first.source_revision == expected_revision
        assert first.original_digest == hashlib.sha256(BODY_A).hexdigest()
        assert first.pages == (
            PageText(page_no=1, text="page from download-knowledge-a.pdf"),
        )
        assert first.chunks[0].model_dump(mode="json") == {
            "chunk_id": "knowledge-a-chunk-0",
            "chunk_index": 0,
            "start_at": 0,
            "end_at": 19,
            "content": "chunk content knowledge-a 0",
            "content_hash": "content-hash-knowledge-a-0",
            "metadata": {
                "section": "benefits",
                "nested": {"labels": ["insurance", "knowledge-a"]},
            },
        }

    assert client.calls[-2:] == [
        "download_exit:knowledge-b",
        "download_exit:knowledge-a",
    ]
    assert all(not path.exists() for path in batch.local_paths.values())


@pytest.mark.parametrize("parse_status", ["", "pending", "failed", "cancelled"])
@pytest.mark.asyncio
async def test_non_completed_metadata_is_parse_state_failure_before_download(
    bound_scope: Callable[..., KnowledgeScope],
    tmp_path: Path,
    parse_status: str,
) -> None:
    client = _client(tmp_path, "knowledge-a")
    client.metadata["knowledge-a"] = [
        _knowledge("knowledge-a", parse_status=parse_status)
    ]
    source = _source(client, bound_scope)

    with pytest.raises(SourceMaterializationError) as caught:
        async with source.materialize(
            WeKnoraSourceRequest(knowledge_ids=("knowledge-a",))
        ):
            pytest.fail("non-completed source must not yield")

    assert caught.value.stage is MaterializationStage.PARSE_STATE
    assert caught.value.source_revision is None
    assert client.calls == ["metadata:knowledge-a"]


@pytest.mark.parametrize("missing", ["file_name", "file_type", "file_hash", "processed_at"])
@pytest.mark.asyncio
async def test_missing_required_metadata_fails_at_metadata_stage(
    bound_scope: Callable[..., KnowledgeScope],
    tmp_path: Path,
    missing: str,
) -> None:
    client = _client(tmp_path, "knowledge-a")
    client.metadata["knowledge-a"] = [
        _knowledge("knowledge-a", **{missing: None if missing == "processed_at" else ""})
    ]
    source = _source(client, bound_scope)

    with pytest.raises(SourceMaterializationError) as caught:
        async with source.materialize(
            WeKnoraSourceRequest(knowledge_ids=("knowledge-a",))
        ):
            pytest.fail("incomplete metadata must not yield")

    assert caught.value.stage is MaterializationStage.METADATA
    assert caught.value.source_revision is None
    assert client.calls == ["metadata:knowledge-a"]


@pytest.mark.asyncio
async def test_adapter_scope_mismatch_is_typed_metadata_failure(
    bound_scope: Callable[..., KnowledgeScope],
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, "knowledge-a")
    client.metadata["knowledge-a"] = [ScopeViolation("scope mismatch")]
    source = _source(client, bound_scope)

    with pytest.raises(SourceMaterializationError) as caught:
        async with source.materialize(
            WeKnoraSourceRequest(knowledge_ids=("knowledge-a",))
        ):
            pytest.fail("scope mismatch must not yield")

    assert caught.value.stage is MaterializationStage.METADATA
    assert isinstance(caught.value.__cause__, ScopeViolation)


@pytest.mark.parametrize(
    ("download_result", "stage"),
    [
        (OSError("download unavailable"), MaterializationStage.DOWNLOAD),
        (WeKnoraIntegrityError("hash mismatch"), MaterializationStage.INTEGRITY),
    ],
)
@pytest.mark.asyncio
async def test_download_failures_are_wrapped_by_failure_class(
    bound_scope: Callable[..., KnowledgeScope],
    tmp_path: Path,
    download_result: BaseException,
    stage: MaterializationStage,
) -> None:
    client = _client(tmp_path, "knowledge-a")
    client.downloads["knowledge-a"] = download_result
    source = _source(client, bound_scope)

    with pytest.raises(SourceMaterializationError) as caught:
        async with source.materialize(
            WeKnoraSourceRequest(knowledge_ids=("knowledge-a",))
        ):
            pytest.fail("download failure must not yield")

    assert caught.value.stage is stage
    assert caught.value.source_revision is not None
    assert caught.value.space_id is not None
    assert caught.value.knowledge_id == "knowledge-a"


@pytest.mark.parametrize("invalid", ["md5", "size", "sha256"])
@pytest.mark.asyncio
async def test_download_identity_mismatch_is_integrity_failure(
    bound_scope: Callable[..., KnowledgeScope],
    tmp_path: Path,
    invalid: str,
) -> None:
    client = _client(tmp_path, "knowledge-a")
    if invalid == "md5":
        client.downloads["knowledge-a"] = _download(
            tmp_path, "knowledge-a", upstream_md5="0" * 32
        )
    elif invalid == "size":
        client.downloads["knowledge-a"] = _download(
            tmp_path, "knowledge-a", byte_count=len(BODY_A) + 1
        )
    else:
        client.downloads["knowledge-a"] = _download(
            tmp_path, "knowledge-a", original_digest="not-a-sha256"
        )
    downloaded = client.downloads["knowledge-a"]
    assert isinstance(downloaded, DownloadedKnowledge)
    source = _source(client, bound_scope)

    with pytest.raises(SourceMaterializationError) as caught:
        async with source.materialize(
            WeKnoraSourceRequest(knowledge_ids=("knowledge-a",))
        ):
            pytest.fail("integrity mismatch must not yield")

    assert caught.value.stage is MaterializationStage.INTEGRITY
    assert not downloaded.path.exists()


@pytest.mark.parametrize("failure", [ScannedPdfError("scanned"), ValueError("corrupt")])
@pytest.mark.asyncio
async def test_scanned_or_corrupt_pdf_is_page_parse_failure(
    bound_scope: Callable[..., KnowledgeScope],
    tmp_path: Path,
    failure: Exception,
) -> None:
    client = _client(tmp_path, "knowledge-a")

    def broken_loader(_: Path) -> list[PageText]:
        raise failure

    source = _source(client, bound_scope, page_loader=broken_loader)
    with pytest.raises(SourceMaterializationError) as caught:
        async with source.materialize(
            WeKnoraSourceRequest(knowledge_ids=("knowledge-a",))
        ):
            pytest.fail("page failure must not yield")

    assert caught.value.stage is MaterializationStage.PAGE_PARSE
    assert caught.value.__cause__ is failure
    assert client.calls[-1] == "download_exit:knowledge-a"


@pytest.mark.asyncio
async def test_chunk_failure_is_typed_and_never_yields(
    bound_scope: Callable[..., KnowledgeScope],
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, "knowledge-a")
    client.chunks["knowledge-a"] = RuntimeError("chunk pagination failed")
    source = _source(client, bound_scope)
    yielded = False

    with pytest.raises(SourceMaterializationError) as caught:
        async with source.materialize(
            WeKnoraSourceRequest(knowledge_ids=("knowledge-a",))
        ):
            yielded = True

    assert yielded is False
    assert caught.value.stage is MaterializationStage.CHUNKS
    assert client.calls[-1] == "download_exit:knowledge-a"


@pytest.mark.asyncio
async def test_invalid_upstream_chunk_offsets_are_typed_chunks_failure(
    bound_scope: Callable[..., KnowledgeScope],
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, "knowledge-a")
    client.chunks["knowledge-a"] = [
        WeKnoraChunk.model_construct(
            id="chunk-invalid",
            tenant_id="tenant-source",
            knowledge_id="knowledge-a",
            knowledge_base_id="raw-source",
            chunk_index=0,
            start_at=-1,
            end_at=10,
            content="invalid offsets",
            content_hash="hash-invalid",
            metadata={},
        )
    ]
    source = _source(client, bound_scope)

    with pytest.raises(SourceMaterializationError) as caught:
        async with source.materialize(
            WeKnoraSourceRequest(knowledge_ids=("knowledge-a",))
        ):
            pytest.fail("invalid chunk offsets must not yield")

    assert caught.value.stage is MaterializationStage.CHUNKS


@pytest.mark.asyncio
async def test_download_file_identity_check_does_not_block_event_loop(
    bound_scope: Callable[..., KnowledgeScope],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path, "knowledge-a")
    started = threading.Event()
    release = threading.Event()
    heartbeat = asyncio.Event()
    original = weknora_source_module._require_download_identity

    def blocking_identity(
        knowledge: WeKnoraKnowledge,
        downloaded: DownloadedKnowledge,
    ) -> None:
        started.set()
        release.wait(timeout=1)
        original(knowledge, downloaded)

    async def beat() -> None:
        while not started.is_set():
            await asyncio.sleep(0)
        heartbeat.set()

    monkeypatch.setattr(
        weknora_source_module,
        "_require_download_identity",
        blocking_identity,
    )
    source = _source(client, bound_scope)

    async def consume() -> None:
        async with source.materialize(
            WeKnoraSourceRequest(knowledge_ids=("knowledge-a",))
        ):
            return

    heartbeat_task = asyncio.create_task(beat())
    consume_task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(heartbeat.wait(), timeout=0.2)
    finally:
        release.set()
        await consume_task
        await heartbeat_task


@pytest.mark.parametrize("drift", ["file_hash", "processed_at", "parse_status"])
@pytest.mark.asyncio
async def test_metadata_drift_after_complete_materialization_fails_closed(
    bound_scope: Callable[..., KnowledgeScope],
    tmp_path: Path,
    drift: str,
) -> None:
    client = _client(tmp_path, "knowledge-a")
    changed: object
    expected_stage = MaterializationStage.INTEGRITY
    if drift == "file_hash":
        changed = "0" * 32
    elif drift == "processed_at":
        changed = PROCESSED_AT + timedelta(seconds=1)
    else:
        changed = "pending"
        expected_stage = MaterializationStage.PARSE_STATE
    client.metadata["knowledge-a"] = [
        _knowledge("knowledge-a"),
        _knowledge("knowledge-a", **{drift: changed}),
    ]
    source = _source(client, bound_scope)

    with pytest.raises(SourceMaterializationError) as caught:
        async with source.materialize(
            WeKnoraSourceRequest(knowledge_ids=("knowledge-a",))
        ):
            pytest.fail("drifted source must not yield")

    assert caught.value.stage is expected_stage
    assert caught.value.source_revision is not None
    assert client.calls[-1] == "download_exit:knowledge-a"


@pytest.mark.asyncio
async def test_second_document_failure_cleans_first_and_yields_zero_documents(
    bound_scope: Callable[..., KnowledgeScope],
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, "knowledge-a", "knowledge-b")
    first_path = client.downloads["knowledge-a"]
    second_path = client.downloads["knowledge-b"]
    assert isinstance(first_path, DownloadedKnowledge)
    assert isinstance(second_path, DownloadedKnowledge)
    client.chunks["knowledge-b"] = RuntimeError("second chunks failed")
    source = _source(client, bound_scope)
    yielded = False

    with pytest.raises(SourceMaterializationError) as caught:
        async with source.materialize(
            WeKnoraSourceRequest(knowledge_ids=("knowledge-a", "knowledge-b"))
        ):
            yielded = True

    assert yielded is False
    assert caught.value.stage is MaterializationStage.CHUNKS
    assert not first_path.path.exists()
    assert not second_path.path.exists()
    assert client.calls[-2:] == [
        "download_exit:knowledge-b",
        "download_exit:knowledge-a",
    ]


@pytest.mark.asyncio
async def test_preparation_cancellation_propagates_and_closes_download(
    bound_scope: Callable[..., KnowledgeScope],
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, "knowledge-a")
    downloaded = client.downloads["knowledge-a"]
    assert isinstance(downloaded, DownloadedKnowledge)
    started = asyncio.Event()
    client.chunk_started["knowledge-a"] = started
    client.chunk_release["knowledge-a"] = asyncio.Event()
    source = _source(client, bound_scope)

    async def consume() -> None:
        async with source.materialize(
            WeKnoraSourceRequest(knowledge_ids=("knowledge-a",))
        ):
            pytest.fail("cancelled preparation must not yield")

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), timeout=1)
    assert downloaded.path.exists()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not downloaded.path.exists()
    assert client.calls[-1] == "download_exit:knowledge-a"


@pytest.mark.asyncio
async def test_blocked_page_loader_cancellation_returns_promptly_and_cleans_download(
    bound_scope: Callable[..., KnowledgeScope],
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, "knowledge-a")
    downloaded = client.downloads["knowledge-a"]
    assert isinstance(downloaded, DownloadedKnowledge)
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    unhandled: list[dict[str, object]] = []
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()

    def capture_unhandled(
        _: asyncio.AbstractEventLoop,
        context: dict[str, object],
    ) -> None:
        unhandled.append(context)

    def blocking_loader(_: Path) -> list[PageText]:
        started.set()
        assert release.wait(timeout=2)
        finished.set()
        raise RuntimeError("late page loader failure")

    source = _source(client, bound_scope, page_loader=blocking_loader)

    async def consume() -> None:
        async with source.materialize(
            WeKnoraSourceRequest(knowledge_ids=("knowledge-a",))
        ):
            pytest.fail("cancelled page parsing must not yield")

    loop.set_exception_handler(capture_unhandled)
    task = asyncio.create_task(consume())
    try:
        assert await asyncio.to_thread(started.wait, 1)
        assert downloaded.path.exists()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(task), timeout=0.2)
        assert not downloaded.path.exists()
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 1)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        loop.set_exception_handler(previous_handler)
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    assert unhandled == []
