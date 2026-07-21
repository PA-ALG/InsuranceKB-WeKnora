"""Immutable document-source boundary (OpenSpec 017)."""

from .directory import (
    DIRECTORY_REPLAY_PROCESSED_AT,
    DirectoryDocumentSource,
    DirectorySourceRequest,
)
from .lineage import LineageResult, LineageStatus, match_quote_to_chunks
from .models import (
    GenerationOrdering,
    ProcessedAtOrdering,
    SourceChunk,
    SourceDocument,
    SourceOrdering,
    SourceRevision,
    SourceScope,
    source_ordering_identity_token,
)
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
    "GenerationOrdering",
    "ProcessedAtOrdering",
    "SourceChunk",
    "SourceDocument",
    "SourceMaterializationError",
    "SourceOrdering",
    "SourceRevision",
    "SourceScope",
    "WeKnoraDocumentSource",
    "WeKnoraSourceRequest",
    "match_quote_to_chunks",
    "source_ordering_identity_token",
]
