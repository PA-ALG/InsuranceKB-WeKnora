"""Pure quote-to-chunk lineage mapping (OpenSpec 017 B4)."""

import hashlib
import re
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import SourceChunk

LineageStatus = Literal["linked", "page_only", "ambiguous"]


class LineageResult(BaseModel):
    """Immutable, serializable result of matching one verified quote."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lineage_status: LineageStatus
    chunk_id: str | None = None
    chunk_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _require_consistent_link(self) -> "LineageResult":
        if self.lineage_status == "linked":
            if self.chunk_id is None or self.chunk_hash is None:
                raise ValueError("linked lineage requires exactly one chunk identity")
        elif self.chunk_id is not None or self.chunk_hash is not None:
            raise ValueError("non-linked lineage cannot carry a chunk identity")
        return self


def _without_whitespace(value: str) -> str:
    """Remove whitespace only; preserve case, Unicode forms and punctuation."""
    return re.sub(r"\s+", "", value)


def _chunk_hash(chunk: SourceChunk) -> str:
    return hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()


def match_quote_to_chunks(
    quote: str,
    chunks: Sequence[SourceChunk],
) -> LineageResult:
    """Map a quote to a unique containing chunk without inferring a PDF page."""
    normalized_quote = _without_whitespace(quote)
    if not normalized_quote:
        return LineageResult(lineage_status="page_only")

    matches = [
        chunk
        for chunk in chunks
        if normalized_quote in _without_whitespace(chunk.content)
    ]
    if len(matches) == 1:
        match = matches[0]
        return LineageResult(
            lineage_status="linked",
            chunk_id=match.chunk_id,
            chunk_hash=_chunk_hash(match),
        )
    if matches:
        return LineageResult(lineage_status="ambiguous")
    return LineageResult(lineage_status="page_only")
