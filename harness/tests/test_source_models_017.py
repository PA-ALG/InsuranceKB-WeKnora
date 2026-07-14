"""SourceDocument and directory replay contracts for OpenSpec 017 B2."""

import asyncio
import hashlib
import json
import math
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.goldenset.pdf import PageText, ScannedPdfError
from insurance_harness.sources import (
    DIRECTORY_REPLAY_PROCESSED_AT,
    DirectoryDocumentSource,
    DirectorySourceRequest,
    MaterializationStage,
    MaterializedBatch,
    SourceChunk,
    SourceDocument,
    SourceMaterializationError,
    SourceRevision,
    SourceScope,
)


def _revision(**changes: Any) -> SourceRevision:
    values: dict[str, Any] = {
        "file_hash": "a" * 64,
        "processed_at": datetime(2026, 7, 13, 8, 30, tzinfo=UTC),
        "parser_fingerprint": "pdfplumber@0.11:text-v1",
    }
    values.update(changes)
    return SourceRevision(**values)


def _document(**changes: Any) -> SourceDocument:
    values: dict[str, Any] = {
        "source_id": "replay:fixture/a.pdf",
        "scope": None,
        "knowledge_id": None,
        "raw_kb_id": None,
        "title": "a",
        "file_name": "a.pdf",
        "file_type": "application/pdf",
        "source_revision": _revision(),
        "original_digest": "b" * 64,
        "pages": [PageText(page_no=1, text="policy text")],
        "chunks": [
            SourceChunk(
                chunk_id="chunk-1",
                chunk_index=0,
                start_at=0,
                end_at=11,
                content="policy text",
                content_hash="c" * 64,
                metadata={"tags": ["policy"], "origin": {"kind": "fixture"}},
            )
        ],
    }
    values.update(changes)
    return SourceDocument(**values)


def test_models_are_frozen_and_nested_collections_are_deeply_immutable() -> None:
    revision = _revision()
    chunk = _document().chunks[0]
    default_chunk = SourceChunk(chunk_id="chunk-default", content="default metadata")
    document = _document()

    with pytest.raises(ValidationError):
        revision.file_hash = "c" * 64
    with pytest.raises(ValidationError):
        chunk.content = "changed"
    with pytest.raises(ValidationError):
        chunk.content_hash = "d" * 64
    with pytest.raises(TypeError):
        chunk.metadata["new"] = "value"  # type: ignore[index]
    with pytest.raises(TypeError):
        default_chunk.metadata["new"] = "value"  # type: ignore[index]
    with pytest.raises(TypeError):
        chunk.metadata["origin"]["kind"] = "changed"
    with pytest.raises(AttributeError):
        chunk.metadata["tags"].append("changed")
    with pytest.raises(ValidationError):
        document.pages += (PageText(page_no=2, text="changed"),)
    with pytest.raises(ValidationError):
        document.chunks += (chunk,)
    with pytest.raises(ValidationError):
        document.pages[0].text = "changed"

    assert isinstance(document.pages, tuple)
    assert isinstance(document.chunks, tuple)


def test_source_scope_can_only_project_a_complete_attested_knowledge_scope(
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = bound_scope(
        tenant_id="tenant-source",
        raw_kb_id="raw-source",
        wiki_kb_id="wiki-source",
    )

    projected = SourceScope.from_knowledge_scope(scope)

    assert projected.model_dump() == {
        "space_id": scope.space_id,
        "tenant_id": "tenant-source",
        "raw_kb_id": "raw-source",
        "wiki_kb_id": "wiki-source",
    }
    scoped_document = _document(
        scope=projected,
        knowledge_id="knowledge-source",
        raw_kb_id="raw-source",
    )
    assert scoped_document.scope == projected

    with pytest.raises(ValidationError, match="attested"):
        SourceScope(
            space_id=scope.space_id,
            tenant_id="tenant-source",
            raw_kb_id="raw-source",
            wiki_kb_id="wiki-source",
        )

    forged = KnowledgeScope(
        space_id=scope.space_id,
        tenant_id="tenant-source",
        raw_kb_id="raw-source",
        wiki_kb_id="wiki-source",
    )
    with pytest.raises(ScopeViolation, match="scope mismatch"):
        SourceScope.from_knowledge_scope(forged)


def test_source_document_rejects_empty_pages() -> None:
    with pytest.raises(ValidationError):
        _document(pages=())


@pytest.mark.parametrize(
    "pages",
    [
        (PageText(page_no=0, text="zero"),),
        (PageText(page_no=1, text="one"), PageText(page_no=1, text="duplicate")),
        (PageText(page_no=2, text="out of order"), PageText(page_no=1, text="one")),
        (PageText(page_no=1, text="one"), PageText(page_no=3, text="gap")),
    ],
)
def test_source_document_requires_contiguous_one_based_pages(
    pages: tuple[PageText, ...],
) -> None:
    with pytest.raises(ValidationError, match="contiguous"):
        _document(pages=pages)


def test_source_document_rejects_duplicate_chunk_ids_before_lineage_mapping() -> None:
    chunks = (
        SourceChunk(
            chunk_id="duplicate-chunk",
            chunk_index=0,
            content="等待期为90天",
        ),
        SourceChunk(
            chunk_id="duplicate-chunk",
            chunk_index=1,
            content="完全不匹配的另一段内容",
        ),
    )

    with pytest.raises(ValidationError, match="duplicate chunk_id"):
        _document(chunks=chunks)


@pytest.mark.parametrize(
    "metadata",
    [
        {1: "integer key", "1": "string key"},
        {"nested": [{2: "integer key"}]},
        {"value": math.nan},
        {"value": math.inf},
        {"value": -math.inf},
    ],
)
def test_source_chunk_rejects_non_json_safe_metadata(metadata: dict[Any, Any]) -> None:
    with pytest.raises(ValidationError):
        SourceChunk(chunk_id="chunk-invalid", content="text", metadata=metadata)


@pytest.mark.parametrize("field", ["chunk_index", "start_at", "end_at"])
@pytest.mark.parametrize("invalid", [True, "1", 1.0, -1])
def test_source_chunk_offsets_require_non_negative_strict_integers(
    field: str,
    invalid: object,
) -> None:
    with pytest.raises(ValidationError):
        SourceChunk.model_validate(
            {
                "chunk_id": "chunk-invalid-offset",
                "content": "text",
                field: invalid,
            }
        )


def test_source_chunk_offsets_allow_none_but_reject_reversed_range() -> None:
    compatible = SourceChunk(
        chunk_id="chunk-compatible",
        content="text",
        chunk_index=None,
        start_at=None,
        end_at=None,
    )
    assert compatible.chunk_index is None
    assert compatible.start_at is None
    assert compatible.end_at is None

    with pytest.raises(ValidationError, match="start_at"):
        SourceChunk(
            chunk_id="chunk-reversed",
            content="text",
            start_at=20,
            end_at=19,
        )


def test_revision_is_sha256_of_sorted_compact_canonical_json() -> None:
    revision = _revision()
    canonical = json.dumps(
        {
            "file_hash": "a" * 64,
            "parser_fingerprint": "pdfplumber@0.11:text-v1",
            "processed_at": "2026-07-13T08:30:00Z",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()

    assert revision.value == hashlib.sha256(canonical).hexdigest()


def test_revision_normalizes_equivalent_timezones_and_is_stable() -> None:
    utc = _revision()
    same_in_shanghai = _revision(
        processed_at=datetime(2026, 7, 13, 16, 30, tzinfo=timezone(timedelta(hours=8)))
    )

    assert same_in_shanghai.processed_at == datetime(2026, 7, 13, 8, 30, tzinfo=UTC)
    assert same_in_shanghai.value == utc.value == _revision().value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("file_hash", "b" * 64),
        ("processed_at", datetime(2026, 7, 13, 8, 30, 1, tzinfo=UTC)),
        ("parser_fingerprint", "pdfplumber@0.11:text-v2"),
    ],
)
def test_each_revision_component_changes_the_digest(field: str, value: Any) -> None:
    assert _revision(**{field: value}).value != _revision().value


def test_revision_rejects_naive_timestamp_and_forged_value() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        _revision(processed_at=datetime(2026, 7, 13, 8, 30))
    with pytest.raises(ValidationError, match="source revision mismatch"):
        _revision(value="0" * 64)


def test_source_document_is_json_serializable_without_runtime_paths() -> None:
    payload = _document().model_dump(mode="json")

    assert payload["source_revision"]["value"] == _revision().value
    assert payload["pages"] == [{"page_no": 1, "text": "policy text"}]
    assert payload["chunks"][0]["metadata"] == {
        "tags": ["policy"],
        "origin": {"kind": "fixture"},
    }
    assert "local_paths" not in json.dumps(payload)


def test_directory_source_requires_explicit_replay_identity_and_parser() -> None:
    with pytest.raises(TypeError):
        DirectoryDocumentSource(replay_identity="fixture")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        DirectoryDocumentSource(parser_fingerprint="parser-v1")  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_directory_source_sorts_pdfs_hashes_files_and_keeps_paths_runtime_only(
    tmp_path: Path,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    second = product_dir / "b.pdf"
    first = product_dir / "a.pdf"
    second.write_bytes(b"second pdf bytes")
    first.write_bytes(b"first pdf bytes")
    (product_dir / "ignored.txt").write_text("ignored")
    loaded: list[str] = []

    def page_loader(path: Path) -> list[PageText]:
        loaded.append(path.name)
        return [PageText(page_no=1, text=f"page from {path.name}")]

    request = DirectorySourceRequest(product_dir=product_dir)
    source = DirectoryDocumentSource(
        replay_identity="golden:product-001",
        parser_fingerprint="fixture-parser-v1",
        page_loader=page_loader,
    )
    assert request.model_dump(mode="json") == {"product_dir": str(product_dir)}

    async with source.materialize(request) as batch:
        assert [document.file_name for document in batch.documents] == ["a.pdf", "b.pdf"]
        assert loaded == ["a.pdf", "b.pdf"]
        materialized_paths = tuple(batch.local_paths.values())
        assert materialized_paths != (first, second)
        assert [path.read_bytes() for path in materialized_paths] == [
            first.read_bytes(),
            second.read_bytes(),
        ]
        with pytest.raises(TypeError):
            batch.local_paths[batch.documents[0].source_id] = second  # type: ignore[index]

        for document, original, snapshot in zip(
            batch.documents, (first, second), materialized_paths, strict=True
        ):
            expected_hash = hashlib.sha256(original.read_bytes()).hexdigest()
            assert document.scope is None
            assert document.knowledge_id is None
            assert document.raw_kb_id is None
            assert document.source_id == f"golden:product-001/{original.name}"
            assert document.original_digest == expected_hash
            assert document.source_revision.file_hash == expected_hash
            assert document.source_revision.processed_at == DIRECTORY_REPLAY_PROCESSED_AT
            assert document.pages == (
                PageText(page_no=1, text=f"page from {snapshot.name}"),
            )
            assert document.chunks == ()

        dumped = batch.model_dump(mode="json")
        assert "local_paths" not in dumped
        assert str(product_dir) not in json.dumps(dumped)

    assert first.exists() and second.exists()
    assert all(not path.exists() for path in materialized_paths)


@pytest.mark.asyncio
async def test_directory_hash_pages_and_runtime_path_share_one_snapshot(
    tmp_path: Path,
) -> None:
    original = tmp_path / "document.pdf"
    original.write_bytes(b"version one")

    def mutating_loader(snapshot: Path) -> list[PageText]:
        snapshot_bytes = snapshot.read_bytes()
        original.write_bytes(b"version two")
        return [PageText(page_no=1, text=snapshot_bytes.decode())]

    source = DirectoryDocumentSource(
        replay_identity="replay:snapshot",
        parser_fingerprint="fixture-parser-v1",
        page_loader=mutating_loader,
    )
    async with source.materialize(DirectorySourceRequest(product_dir=tmp_path)) as batch:
        document = batch.documents[0]
        runtime_path = batch.local_paths[document.source_id]
        assert document.pages[0].text == "version one"
        assert runtime_path.read_bytes() == b"version one"
        assert document.original_digest == hashlib.sha256(b"version one").hexdigest()

    assert original.read_bytes() == b"version two"
    assert not runtime_path.exists()


@pytest.mark.asyncio
async def test_directory_rejects_pdf_symlink_even_when_target_exists(tmp_path: Path) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"outside")
    (product_dir / "linked.pdf").symlink_to(outside)
    source = DirectoryDocumentSource(
        replay_identity="replay:symlink",
        parser_fingerprint="fixture-parser-v1",
        page_loader=lambda _: [PageText(page_no=1, text="must not parse")],
    )

    with pytest.raises(SourceMaterializationError) as caught:
        async with source.materialize(DirectorySourceRequest(product_dir=product_dir)):
            pytest.fail("must not yield")

    assert caught.value.stage is MaterializationStage.DISCOVERY


@pytest.mark.asyncio
async def test_directory_fifo_named_pdf_fails_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "pipe.pdf"
    os.mkfifo(fifo)
    source = DirectoryDocumentSource(
        replay_identity="replay:fifo",
        parser_fingerprint="fixture-parser-v1",
        page_loader=lambda _: pytest.fail("FIFO must not reach parser"),
    )

    async def consume() -> None:
        with pytest.raises(SourceMaterializationError) as caught:
            async with source.materialize(DirectorySourceRequest(product_dir=tmp_path)):
                pytest.fail("must not yield")
        assert caught.value.stage is MaterializationStage.INTEGRITY

    await asyncio.wait_for(consume(), timeout=0.5)


@pytest.mark.asyncio
async def test_directory_materialization_does_not_block_event_loop(tmp_path: Path) -> None:
    (tmp_path / "document.pdf").write_bytes(b"pdf")
    started = threading.Event()
    release = threading.Event()

    def blocking_loader(_: Path) -> list[PageText]:
        started.set()
        assert release.wait(timeout=2)
        return [PageText(page_no=1, text="ready")]

    source = DirectoryDocumentSource(
        replay_identity="replay:threaded",
        parser_fingerprint="fixture-parser-v1",
        page_loader=blocking_loader,
    )

    async def consume() -> None:
        async with source.materialize(DirectorySourceRequest(product_dir=tmp_path)):
            return

    task = asyncio.create_task(consume())
    try:
        assert await asyncio.to_thread(started.wait, 1)
        await asyncio.wait_for(asyncio.sleep(0), timeout=0.1)
    finally:
        release.set()
    await asyncio.wait_for(task, timeout=2)


@pytest.mark.asyncio
async def test_directory_prepare_cancellation_propagates_before_worker_finishes(
    tmp_path: Path,
) -> None:
    (tmp_path / "document.pdf").write_bytes(b"pdf")
    started = threading.Event()
    release = threading.Event()

    def blocking_loader(_: Path) -> list[PageText]:
        started.set()
        assert release.wait(timeout=2)
        return [PageText(page_no=1, text="finished later")]

    source = DirectoryDocumentSource(
        replay_identity="replay:cancel-prepare",
        parser_fingerprint="fixture-parser-v1",
        page_loader=blocking_loader,
    )

    async def consume() -> None:
        async with source.materialize(DirectorySourceRequest(product_dir=tmp_path)):
            pytest.fail("cancelled preparation must not yield")

    task = asyncio.create_task(consume())
    assert await asyncio.to_thread(started.wait, 1)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.2)
    finally:
        release.set()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_directory_context_cancellation_cleans_runtime_snapshot(tmp_path: Path) -> None:
    (tmp_path / "document.pdf").write_bytes(b"pdf")
    entered = asyncio.Event()
    runtime_paths: list[Path] = []
    source = DirectoryDocumentSource(
        replay_identity="replay:cancel-context",
        parser_fingerprint="fixture-parser-v1",
        page_loader=lambda _: [PageText(page_no=1, text="page")],
    )

    async def consume() -> None:
        async with source.materialize(DirectorySourceRequest(product_dir=tmp_path)) as batch:
            runtime_paths.extend(batch.local_paths.values())
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime_paths and all(not path.exists() for path in runtime_paths)


@pytest.mark.asyncio
async def test_directory_materialization_is_reproducible_and_does_not_delete_inputs(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "document.pdf"
    pdf.write_bytes(b"stable bytes")
    source = DirectoryDocumentSource(
        replay_identity="replay:stable",
        parser_fingerprint="fixture-parser-v1",
        page_loader=lambda _: [PageText(page_no=1, text="stable page")],
    )
    request = DirectorySourceRequest(product_dir=tmp_path)

    async with source.materialize(request) as first:
        first_dump = first.model_dump(mode="json")
    async with source.materialize(request) as second:
        second_dump = second.model_dump(mode="json")

    assert first_dump == second_dump
    assert pdf.read_bytes() == b"stable bytes"


@pytest.mark.asyncio
async def test_scanned_second_pdf_fails_the_whole_batch_before_yield(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.pdf").write_bytes(b"first")
    (tmp_path / "b.pdf").write_bytes(b"second")
    loaded: list[str] = []

    def page_loader(path: Path) -> list[PageText]:
        loaded.append(path.name)
        if path.name == "b.pdf":
            raise ScannedPdfError("scanned")
        return [PageText(page_no=1, text="valid")]

    source = DirectoryDocumentSource(
        replay_identity="replay:all-or-nothing",
        parser_fingerprint="fixture-parser-v1",
        page_loader=page_loader,
    )
    yielded = False

    with pytest.raises(SourceMaterializationError) as caught:
        async with source.materialize(DirectorySourceRequest(product_dir=tmp_path)):
            yielded = True

    assert yielded is False
    assert loaded == ["a.pdf", "b.pdf"]
    assert caught.value.stage is MaterializationStage.PAGE_PARSE


@pytest.mark.asyncio
async def test_directory_parse_failure_is_typed_but_cancellation_is_not_wrapped(
    tmp_path: Path,
) -> None:
    (tmp_path / "document.pdf").write_bytes(b"pdf")

    def broken_loader(_: Path) -> list[PageText]:
        raise ValueError("corrupt")

    broken = DirectoryDocumentSource(
        replay_identity="replay:broken",
        parser_fingerprint="fixture-parser-v1",
        page_loader=broken_loader,
    )
    with pytest.raises(SourceMaterializationError) as caught:
        async with broken.materialize(DirectorySourceRequest(product_dir=tmp_path)):
            pytest.fail("must not yield")
    assert caught.value.stage is MaterializationStage.PAGE_PARSE
    assert isinstance(caught.value.__cause__, ValueError)

    def cancelled_loader(_: Path) -> list[PageText]:
        raise asyncio.CancelledError

    cancelled = DirectoryDocumentSource(
        replay_identity="replay:cancelled",
        parser_fingerprint="fixture-parser-v1",
        page_loader=cancelled_loader,
    )
    with pytest.raises(asyncio.CancelledError):
        async with cancelled.materialize(DirectorySourceRequest(product_dir=tmp_path)):
            pytest.fail("must not yield")


@pytest.mark.asyncio
async def test_invalid_loader_pages_are_typed_page_parse_failure(tmp_path: Path) -> None:
    (tmp_path / "document.pdf").write_bytes(b"pdf")
    source = DirectoryDocumentSource(
        replay_identity="replay:invalid-pages",
        parser_fingerprint="fixture-parser-v1",
        page_loader=lambda _: [
            PageText(page_no=1, text="one"),
            PageText(page_no=1, text="duplicate"),
        ],
    )

    with pytest.raises(SourceMaterializationError) as caught:
        async with source.materialize(DirectorySourceRequest(product_dir=tmp_path)):
            pytest.fail("must not yield")

    assert caught.value.stage is MaterializationStage.PAGE_PARSE
    assert caught.value.source_revision is not None
    assert len(caught.value.dead_letter_key) == 64
    assert isinstance(caught.value.__cause__, ValidationError)


def test_dead_letter_key_is_stable_and_stage_specific() -> None:
    first = SourceMaterializationError(
        "failed",
        stage=MaterializationStage.PAGE_PARSE,
        space_id="space-1",
        knowledge_id="knowledge-1",
        source_id="ignored-when-knowledge-present",
        source_revision="revision-1",
    )
    repeated = SourceMaterializationError(
        "different message",
        stage=MaterializationStage.PAGE_PARSE,
        space_id="space-1",
        knowledge_id="knowledge-1",
        source_id="another-source",
        source_revision="revision-1",
    )
    other_stage = SourceMaterializationError(
        "failed",
        stage=MaterializationStage.CHUNKS,
        space_id="space-1",
        knowledge_id="knowledge-1",
        source_revision="revision-1",
    )

    canonical = json.dumps(
        {
            "knowledge_id": "knowledge-1",
            "revision": "revision-1",
            "source_id": None,
            "space_id": "space-1",
            "stage": "page_parse",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    assert first.dead_letter_key == hashlib.sha256(canonical).hexdigest()
    assert repeated.dead_letter_key == first.dead_letter_key
    assert other_stage.dead_letter_key != first.dead_letter_key

    missing = SourceMaterializationError(
        "missing", stage=MaterializationStage.DOWNLOAD
    )
    literal_unknown = SourceMaterializationError(
        "literal",
        stage=MaterializationStage.DOWNLOAD,
        source_id="unknown",
        source_revision="unknown",
    )
    assert missing.dead_letter_key != literal_unknown.dead_letter_key


def test_materialized_batch_requires_exact_unique_source_path_mapping(tmp_path: Path) -> None:
    document = _document()
    with pytest.raises(ValidationError, match="local_paths"):
        MaterializedBatch(documents=(document,), local_paths={})
    with pytest.raises(ValidationError, match="local_paths"):
        MaterializedBatch(
            documents=(document,),
            local_paths={document.source_id: tmp_path / "a.pdf", "extra": tmp_path / "b.pdf"},
        )
    with pytest.raises(ValidationError, match="duplicate"):
        MaterializedBatch(
            documents=(document, document),
            local_paths={document.source_id: tmp_path / "a.pdf"},
        )


@pytest.mark.asyncio
async def test_no_pdf_is_a_discovery_failure_and_never_yields(tmp_path: Path) -> None:
    source = DirectoryDocumentSource(
        replay_identity="replay:empty",
        parser_fingerprint="fixture-parser-v1",
        page_loader=lambda _: pytest.fail("loader must not run"),
    )
    yielded = False

    with pytest.raises(SourceMaterializationError) as caught:
        async with source.materialize(DirectorySourceRequest(product_dir=tmp_path)):
            yielded = True

    assert yielded is False
    assert caught.value.stage is MaterializationStage.DISCOVERY
    assert caught.value.source_revision is None
    assert len(caught.value.dead_letter_key) == 64
    assert str(tmp_path) not in str(caught.value)
