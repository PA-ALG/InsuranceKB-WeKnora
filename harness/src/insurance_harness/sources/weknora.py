"""Production WeKnora implementation of the immutable document-source boundary."""

import asyncio
import re
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from insurance_harness.adapters.weknora import (
    DownloadedKnowledge,
    WeKnoraChunk,
    WeKnoraIntegrityError,
    WeKnoraKnowledge,
)
from insurance_harness.adapters.weknora.models import is_safe_knowledge_id
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.goldenset.pdf import PageText, extract_pages

from .models import (
    ProcessedAtOrdering,
    SourceChunk,
    SourceDocument,
    SourceRevision,
    SourceScope,
)
from .protocol import MaterializationStage, MaterializedBatch, SourceMaterializationError

_MD5_RE = re.compile(r"^[0-9a-f]{32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class WeKnoraSourceRequest(BaseModel):
    """Serializable, ordered set of WeKnora knowledge identities."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    knowledge_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("knowledge_ids")
    @classmethod
    def _non_empty_unique_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized):
            raise ValueError("knowledge_ids must contain non-empty strings")
        if any(not is_safe_knowledge_id(item) for item in normalized):
            raise ValueError("knowledge_ids contain an unsafe identity")
        if len(normalized) != len(set(normalized)):
            raise ValueError("knowledge_ids must be unique")
        return normalized


class _SourceClient(Protocol):
    async def get_knowledge(
        self,
        scope: KnowledgeScope,
        knowledge_id: str,
    ) -> WeKnoraKnowledge: ...

    def download_knowledge(
        self,
        scope: KnowledgeScope,
        knowledge: WeKnoraKnowledge,
    ) -> AbstractAsyncContextManager[DownloadedKnowledge]: ...

    async def list_chunks(
        self,
        scope: KnowledgeScope,
        knowledge_id: str,
    ) -> list[WeKnoraChunk]: ...


PageLoader = Callable[[Path], list[PageText]]


class WeKnoraDocumentSource:
    """Materialize complete, revision-stable WeKnora documents all-or-nothing."""

    def __init__(
        self,
        client: _SourceClient,
        scope: KnowledgeScope,
        *,
        parser_fingerprint: str,
        page_loader: PageLoader | None = None,
        source_max_documents_per_batch: int = 8,
        source_max_batch_bytes: int = 256 * 1024 * 1024,
        source_max_batch_pages: int = 20_000,
        source_max_batch_chunks: int = 200_000,
    ) -> None:
        self._source_scope = SourceScope.from_knowledge_scope(scope)
        self._client = client
        self._scope = scope
        self._parser_fingerprint = parser_fingerprint.strip()
        if not self._parser_fingerprint:
            raise ValueError("parser_fingerprint must not be empty")
        self._page_loader = page_loader or extract_pages
        self._source_max_documents_per_batch = _positive_limit(
            "source_max_documents_per_batch", source_max_documents_per_batch
        )
        self._source_max_batch_bytes = _positive_limit(
            "source_max_batch_bytes", source_max_batch_bytes
        )
        self._source_max_batch_pages = _positive_limit(
            "source_max_batch_pages", source_max_batch_pages
        )
        self._source_max_batch_chunks = _positive_limit(
            "source_max_batch_chunks", source_max_batch_chunks
        )

    @asynccontextmanager
    async def materialize(
        self,
        request: WeKnoraSourceRequest,
    ) -> AsyncIterator[MaterializedBatch]:
        if len(request.knowledge_ids) > self._source_max_documents_per_batch:
            raise SourceMaterializationError(
                "knowledge batch exceeds document limit",
                stage=MaterializationStage.METADATA,
                space_id=self._scope.space_id,
                source_id="weknora-batch",
            )
        documents: list[SourceDocument] = []
        local_paths: dict[str, Path] = {}
        usage = _BatchUsage()
        async with AsyncExitStack() as stack:
            for knowledge_id in request.knowledge_ids:
                document, path = await self._materialize_one(stack, knowledge_id, usage)
                documents.append(document)
                local_paths[document.source_id] = path
            yield MaterializedBatch(
                documents=tuple(documents),
                local_paths=local_paths,
            )

    async def _materialize_one(
        self,
        stack: AsyncExitStack,
        knowledge_id: str,
        usage: "_BatchUsage",
    ) -> tuple[SourceDocument, Path]:
        knowledge = await self._metadata(knowledge_id, source_revision=None)
        try:
            processed_at = _require_materialization_metadata(knowledge)
        except Exception as exc:
            raise self._error(
                knowledge_id,
                MaterializationStage.METADATA,
                source_revision=None,
                message="knowledge metadata is incomplete",
            ) from exc
        if _parse_status(knowledge) != "completed":
            raise self._error(
                knowledge_id,
                MaterializationStage.PARSE_STATE,
                source_revision=None,
                message="knowledge parse is not completed",
            )

        try:
            revision = SourceRevision(
                file_hash=knowledge.file_hash,
                ordering=ProcessedAtOrdering(value=processed_at),
                parser_fingerprint=self._parser_fingerprint,
            )
        except Exception as exc:
            raise self._error(
                knowledge_id,
                MaterializationStage.METADATA,
                source_revision=None,
                message="knowledge revision metadata is invalid",
            ) from exc

        try:
            downloaded = await stack.enter_async_context(
                self._client.download_knowledge(self._scope, knowledge)
            )
        except WeKnoraIntegrityError as exc:
            raise self._error(
                knowledge_id,
                MaterializationStage.INTEGRITY,
                source_revision=revision.value,
                message="knowledge download failed integrity validation",
            ) from exc
        except Exception as exc:
            raise self._error(
                knowledge_id,
                MaterializationStage.DOWNLOAD,
                source_revision=revision.value,
                message="knowledge download failed",
            ) from exc

        try:
            await asyncio.to_thread(_require_download_identity, knowledge, downloaded)
        except Exception as exc:
            raise self._error(
                knowledge_id,
                MaterializationStage.INTEGRITY,
                source_revision=revision.value,
                message="download identity does not match metadata",
            ) from exc
        usage.byte_count += downloaded.byte_count
        if usage.byte_count > self._source_max_batch_bytes:
            raise self._error(
                knowledge_id,
                MaterializationStage.DOWNLOAD,
                source_revision=revision.value,
                message="knowledge batch exceeds byte limit",
            )

        try:
            loaded_pages = await _load_pages(self._page_loader, downloaded.path)
            pages = _require_valid_pages(loaded_pages)
        except Exception as exc:
            raise self._error(
                knowledge_id,
                MaterializationStage.PAGE_PARSE,
                source_revision=revision.value,
                message="downloaded source could not be parsed into pages",
            ) from exc
        usage.page_count += len(pages)
        if usage.page_count > self._source_max_batch_pages:
            raise self._error(
                knowledge_id,
                MaterializationStage.PAGE_PARSE,
                source_revision=revision.value,
                message="knowledge batch exceeds page limit",
            )

        try:
            upstream_chunks = await self._client.list_chunks(self._scope, knowledge_id)
            chunks = tuple(_source_chunk(chunk) for chunk in upstream_chunks)
        except Exception as exc:
            raise self._error(
                knowledge_id,
                MaterializationStage.CHUNKS,
                source_revision=revision.value,
                message="knowledge chunks could not be materialized",
            ) from exc
        usage.chunk_count += len(chunks)
        if usage.chunk_count > self._source_max_batch_chunks:
            raise self._error(
                knowledge_id,
                MaterializationStage.CHUNKS,
                source_revision=revision.value,
                message="knowledge batch exceeds chunk limit",
            )

        refreshed = await self._metadata(knowledge_id, source_revision=revision.value)
        if _parse_status(refreshed) != "completed":
            raise self._error(
                knowledge_id,
                MaterializationStage.PARSE_STATE,
                source_revision=revision.value,
                message="knowledge parse state drifted during materialization",
            )
        if (
            refreshed.file_hash != knowledge.file_hash
            or refreshed.processed_at != knowledge.processed_at
        ):
            raise self._error(
                knowledge_id,
                MaterializationStage.INTEGRITY,
                source_revision=revision.value,
                message="knowledge revision drifted during materialization",
            )

        document = SourceDocument(
            source_id=knowledge_id,
            scope=self._source_scope,
            knowledge_id=knowledge_id,
            raw_kb_id=self._source_scope.raw_kb_id,
            title=knowledge.title.strip() or Path(knowledge.file_name).stem,
            file_name=knowledge.file_name,
            file_type=knowledge.file_type,
            source_revision=revision,
            original_digest=downloaded.original_digest,
            pages=pages,
            chunks=chunks,
        )
        return document, downloaded.path

    async def _metadata(
        self,
        knowledge_id: str,
        *,
        source_revision: str | None,
    ) -> WeKnoraKnowledge:
        try:
            return await self._client.get_knowledge(self._scope, knowledge_id)
        except Exception as exc:
            raise self._error(
                knowledge_id,
                MaterializationStage.METADATA,
                source_revision=source_revision,
                message="knowledge metadata could not be loaded",
            ) from exc

    def _error(
        self,
        knowledge_id: str,
        stage: MaterializationStage,
        *,
        source_revision: str | None,
        message: str,
    ) -> SourceMaterializationError:
        return SourceMaterializationError(
            message,
            stage=stage,
            space_id=self._scope.space_id,
            knowledge_id=knowledge_id,
            source_revision=source_revision,
        )


def _require_materialization_metadata(knowledge: WeKnoraKnowledge) -> datetime:
    if not knowledge.file_name.strip():
        raise ValueError("file_name is required")
    if not knowledge.file_type.strip():
        raise ValueError("file_type is required")
    if _MD5_RE.fullmatch(knowledge.file_hash.strip().lower()) is None:
        raise ValueError("file_hash is required")
    if knowledge.processed_at is None:
        raise ValueError("processed_at is required")
    return knowledge.processed_at


def _positive_limit(name: str, value: int) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass(slots=True)
class _BatchUsage:
    byte_count: int = 0
    page_count: int = 0
    chunk_count: int = 0


def _parse_status(knowledge: WeKnoraKnowledge) -> str:
    return knowledge.parse_status.strip().lower()


def _require_download_identity(
    knowledge: WeKnoraKnowledge,
    downloaded: DownloadedKnowledge,
) -> None:
    if downloaded.upstream_md5.strip().lower() != knowledge.file_hash:
        raise ValueError("download MD5 mismatch")
    if knowledge.file_size is not None and downloaded.byte_count != knowledge.file_size:
        raise ValueError("download size mismatch")
    if _SHA256_RE.fullmatch(downloaded.original_digest.strip().lower()) is None:
        raise ValueError("download SHA-256 is invalid")
    if not downloaded.path.is_file() or downloaded.path.stat().st_size != downloaded.byte_count:
        raise ValueError("downloaded file does not match byte count")


async def _load_pages(page_loader: PageLoader, path: Path) -> list[PageText]:
    task = asyncio.create_task(asyncio.to_thread(page_loader, path))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A worker thread cannot be force-cancelled. Do not let it delay caller
        # cancellation; consume its eventual result after the download context closes.
        task.add_done_callback(_consume_page_loader_result)
        raise


def _consume_page_loader_result(task: "asyncio.Task[list[PageText]]") -> None:
    try:
        task.result()
    except BaseException:
        pass


def _require_valid_pages(pages: list[PageText]) -> tuple[PageText, ...]:
    if not pages:
        raise ValueError("PDF yielded no pages")
    if any(not isinstance(page, PageText) for page in pages):
        raise ValueError("page loader returned an invalid page")
    page_numbers = [page.page_no for page in pages]
    if any(type(number) is not int for number in page_numbers) or page_numbers != list(
        range(1, len(pages) + 1)
    ):
        raise ValueError("pages must use contiguous one-based page numbers")
    return tuple(pages)


def _source_chunk(chunk: WeKnoraChunk) -> SourceChunk:
    return SourceChunk(
        chunk_id=str(chunk.id),
        chunk_index=chunk.chunk_index,
        start_at=chunk.start_at,
        end_at=chunk.end_at,
        content=chunk.content,
        content_hash=chunk.content_hash,
        metadata={} if chunk.metadata is None else chunk.metadata,
    )
