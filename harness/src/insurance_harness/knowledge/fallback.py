"""Curated-first RAW fallback policy (OpenSpec 018 R5.1-R5.3)."""

from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.knowledge.reader import (
    CoverageGap,
    SnapshotFactsResult,
)


class RawHit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    space_id: str
    raw_kb_id: str
    text: str
    source_ref: str | None = None


class FallbackAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    review_status: Literal["unreviewed_raw"] = "unreviewed_raw"
    hits: tuple[RawHit, ...]


class RawFallbackProvider(Protocol):
    async def search(
        self,
        scope: KnowledgeScope,
        gap: CoverageGap,
        query: str,
    ) -> Sequence[RawHit]: ...


class RawFallbackPolicy:
    """Call RAW only for a typed coverage gap and never merge curated facts."""

    def __init__(self, provider: RawFallbackProvider) -> None:
        self._provider = provider

    async def answer(
        self,
        scope: KnowledgeScope,
        curated: SnapshotFactsResult | CoverageGap,
        *,
        query: str,
    ) -> SnapshotFactsResult | FallbackAnswer:
        if isinstance(curated, SnapshotFactsResult):
            return curated

        hits = tuple(await self._provider.search(scope, curated, query))
        if any(
            hit.space_id != scope.space_id or hit.raw_kb_id != scope.raw_kb_id
            for hit in hits
        ):
            raise ScopeViolation("scope mismatch")
        return FallbackAnswer(hits=hits)
