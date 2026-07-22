"""Non-authority async stage ports for the OpenSpec 028 contract kernel."""

from __future__ import annotations

from typing import Protocol

from insurance_harness.runtime.models import (
    CandidateFactBatch,
    ConsensusResult,
    GapResult,
    GovernanceResult,
    IntakeContext,
    MaterializedBatch,
    ProductCompilationInput,
    ResolvedRouteSet,
    RoutedSections,
    VerifiedFactBatch,
)


class MaterializeStage(Protocol):
    async def run(self, context: IntakeContext) -> MaterializedBatch: ...


class ClassifyRouteStage(Protocol):
    async def run(self, batch: MaterializedBatch) -> RoutedSections: ...


class ResolveTemplateStage(Protocol):
    async def run(self, routed: RoutedSections) -> ResolvedRouteSet: ...


class ExtractStage(Protocol):
    async def run(self, compilation: ProductCompilationInput) -> CandidateFactBatch: ...


class VerifyStage(Protocol):
    async def run(self, candidates: CandidateFactBatch) -> VerifiedFactBatch: ...


class GapStage(Protocol):
    async def run(self, verified: VerifiedFactBatch) -> GapResult: ...


class ConsensusStage(Protocol):
    async def run(
        self,
        verified: VerifiedFactBatch,
        gap: GapResult,
    ) -> ConsensusResult: ...


class KnowledgeSink(Protocol):
    async def apply(self, consensus: ConsensusResult) -> GovernanceResult: ...
