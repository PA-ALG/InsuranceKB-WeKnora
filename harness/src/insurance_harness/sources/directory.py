"""Explicit, deterministic Directory replay implementation of DocumentSource."""

import asyncio
import hashlib
import os
import stat
import tempfile
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..goldenset.pdf import PageText, extract_pages
from .models import SourceDocument, SourceRevision
from .protocol import MaterializationStage, MaterializedBatch, SourceMaterializationError

# Directory replay has no upstream processing clock. A fixed Unix epoch UTC sentinel makes
# unchanged fixture bytes and parser fingerprints reproduce the exact same source revision.
DIRECTORY_REPLAY_PROCESSED_AT = datetime(1970, 1, 1, tzinfo=UTC)

PageLoader = Callable[[Path], list[PageText]]


class DirectorySourceRequest(BaseModel):
    """Serializable request; product_dir is explicit and never copied into source DTOs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    product_dir: Path


class DirectoryDocumentSource:
    """Fixture/Golden replay source; never a production fallback."""

    def __init__(
        self,
        *,
        replay_identity: str,
        parser_fingerprint: str,
        page_loader: PageLoader | None = None,
    ) -> None:
        self._replay_identity = replay_identity.strip().rstrip("/")
        self._parser_fingerprint = parser_fingerprint.strip()
        if not self._replay_identity:
            raise ValueError("replay_identity must not be empty")
        if not self._parser_fingerprint:
            raise ValueError("parser_fingerprint must not be empty")
        self._page_loader = page_loader or extract_pages

    @asynccontextmanager
    async def materialize(
        self,
        request: DirectorySourceRequest,
    ) -> AsyncIterator[MaterializedBatch]:
        prepare_task = asyncio.create_task(asyncio.to_thread(self._prepare_batch, request))
        try:
            prepared = await asyncio.shield(prepare_task)
        except asyncio.CancelledError:
            # A Python worker thread cannot be force-cancelled. Keep the task alive and
            # clean its snapshot as soon as it finishes, while propagating cancellation
            # to the caller immediately.
            prepare_task.add_done_callback(_cleanup_cancelled_prepare)
            raise
        try:
            yield prepared.batch
        finally:
            cleanup_task = asyncio.create_task(
                asyncio.to_thread(prepared.temp_dir.cleanup)
            )
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                await asyncio.shield(cleanup_task)
                raise

    def _prepare_batch(self, request: DirectorySourceRequest) -> "_PreparedBatch":
        temp_dir = tempfile.TemporaryDirectory(prefix="insurancekb-replay-")
        try:
            batch = self._build_batch(request, Path(temp_dir.name))
        except BaseException:
            temp_dir.cleanup()
            raise
        return _PreparedBatch(batch=batch, temp_dir=temp_dir)

    def _build_batch(
        self,
        request: DirectorySourceRequest,
        snapshot_dir: Path,
    ) -> MaterializedBatch:
        product_dir = request.product_dir
        if product_dir.is_symlink():
            raise SourceMaterializationError(
                "directory replay root must not be a symlink",
                stage=MaterializationStage.DISCOVERY,
                source_id=self._replay_identity,
            )
        try:
            root = product_dir.resolve(strict=True)
        except OSError as exc:
            raise SourceMaterializationError(
                "directory replay root is unavailable",
                stage=MaterializationStage.DISCOVERY,
                source_id=self._replay_identity,
            ) from exc
        if not root.is_dir():
            raise SourceMaterializationError(
                "directory replay root is not a directory",
                stage=MaterializationStage.DISCOVERY,
                source_id=self._replay_identity,
            )

        paths = sorted(root.glob("*.pdf"), key=lambda path: path.name)
        if not paths:
            raise SourceMaterializationError(
                "directory replay contains no PDF files",
                stage=MaterializationStage.DISCOVERY,
                source_id=self._replay_identity,
            )

        documents: list[SourceDocument] = []
        local_paths: dict[str, Path] = {}
        for path in paths:
            source_id = f"{self._replay_identity}/{path.name}"
            if path.is_symlink() or path.parent != root:
                raise SourceMaterializationError(
                    f"{path.name}: replay PDF must be a direct regular file",
                    stage=MaterializationStage.DISCOVERY,
                    source_id=source_id,
                )
            snapshot_path = snapshot_dir / path.name
            try:
                digest = _snapshot_file(path, snapshot_path)
            except Exception as exc:
                raise SourceMaterializationError(
                    f"{path.name}: failed to snapshot replay source",
                    stage=MaterializationStage.INTEGRITY,
                    source_id=source_id,
                ) from exc
            revision = SourceRevision(
                file_hash=digest,
                processed_at=DIRECTORY_REPLAY_PROCESSED_AT,
                parser_fingerprint=self._parser_fingerprint,
            )
            try:
                loaded_pages = self._page_loader(snapshot_path)
                if not loaded_pages:
                    raise SourceMaterializationError(
                        f"{path.name}: PDF yielded no pages",
                        stage=MaterializationStage.PAGE_PARSE,
                        source_id=source_id,
                        source_revision=revision.value,
                    )
                document = SourceDocument(
                    source_id=source_id,
                    scope=None,
                    knowledge_id=None,
                    raw_kb_id=None,
                    title=path.stem,
                    file_name=path.name,
                    file_type="application/pdf",
                    source_revision=revision,
                    original_digest=digest,
                    pages=tuple(loaded_pages),
                    chunks=(),
                )
            except SourceMaterializationError:
                raise
            except Exception as exc:
                raise SourceMaterializationError(
                    f"{path.name}: PDF page extraction failed",
                    stage=MaterializationStage.PAGE_PARSE,
                    source_id=source_id,
                    source_revision=revision.value,
                ) from exc
            documents.append(document)
            local_paths[source_id] = snapshot_path

        return MaterializedBatch(documents=tuple(documents), local_paths=local_paths)


@dataclass(frozen=True)
class _PreparedBatch:
    batch: MaterializedBatch
    temp_dir: tempfile.TemporaryDirectory[str]


def _cleanup_cancelled_prepare(task: "asyncio.Task[_PreparedBatch]") -> None:
    try:
        prepared = task.result()
    except BaseException:
        # _prepare_batch cleans its own temp directory on every failure.
        return
    asyncio.get_running_loop().run_in_executor(None, prepared.temp_dir.cleanup)


def _snapshot_file(source: Path, destination: Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    try:
        source_stat = os.fstat(descriptor)
        if not stat.S_ISREG(source_stat.st_mode):
            raise ValueError("replay source is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=True) as input_stream:
            descriptor = -1
            with destination.open("xb") as output_stream:
                for block in iter(lambda: input_stream.read(1024 * 1024), b""):
                    output_stream.write(block)
                    digest.update(block)
        destination.chmod(0o400)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return digest.hexdigest()
