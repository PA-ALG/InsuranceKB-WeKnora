"""Immutable document-source boundary (OpenSpec 017)."""

from .directory import (
    DIRECTORY_REPLAY_PROCESSED_AT,
    DirectoryDocumentSource,
    DirectorySourceRequest,
)
from .lineage import LineageResult, LineageStatus, match_quote_to_chunks
from .models import SourceChunk, SourceDocument, SourceRevision, SourceScope
from .protocol import (
    DocumentSource,
    MaterializationStage,
    MaterializedBatch,
    SourceMaterializationError,
)
from .weknora import WeKnoraDocumentSource, WeKnoraSourceRequest

__all__ = [
    "DIRECTORY_REPLAY_PROCESSED_AT",
    "DirectoryDocumentSource",
    "DirectorySourceRequest",
    "DocumentSource",
    "LineageResult",
    "LineageStatus",
    "MaterializedBatch",
    "MaterializationStage",
    "SourceChunk",
    "SourceDocument",
    "SourceMaterializationError",
    "SourceRevision",
    "SourceScope",
    "WeKnoraDocumentSource",
    "WeKnoraSourceRequest",
    "match_quote_to_chunks",
]
