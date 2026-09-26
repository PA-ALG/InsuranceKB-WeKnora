"""Compile and review discovery with one bounded, dependency-aware refinement.

The pipeline receives only the final delta, proof and artifacts. StageCall remains
owned by discovery_stage; this module neither persists nor publishes anything.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
    CompileOutput,
    CompileResult,
    ReviewResult,
)
from insurance_harness.product_ingestion.artifact_models import ArtifactDraft
from insurance_harness.product_ingestion.discovery_composition import (
    compose_discovery_review,
    merge_discovery_delta,
)
from insurance_harness.product_ingestion.discovery_stage import (
    run_independent_discovery_final_review,
)
from insurance_harness.product_ingestion.models import ProductRunState
from insurance_harness.product_ingestion.stages import artifact, json_bytes

if TYPE_CHECKING:
    from insurance_harness.jobs import JobSnapshot
    from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
    from insurance_harness.product_ingestion.composition import ProductScopeServices
    from insurance_harness.product_ingestion.models import (
        ProductRunSnapshot,
        ProductScope,
        StageSnapshot,
    )


@dataclass(frozen=True, slots=True)
class ReviewedDiscoveryCompilation:
    delta: CompileResult
    review: ReviewResult | None
    drafts: tuple[ArtifactDraft, ...]
    state: ProductRunState


async def compile_reviewed_discovery(
    *,
    service: ProductScopeServices,
    artifacts: ProductArtifactStore,
    scope: ProductScope,
    run: ProductRunSnapshot,
    stage: StageSnapshot,
    job: JobSnapshot,
    request: compiler.BatchConceptCompileRequest830G3V1,
    field_delta: CompileResult,
    discovery_candidates: dict[str, Any],
) -> ReviewedDiscoveryCompilation:
    """Compose, review, optionally prune explicit local failures and review once."""

    async def attempt(candidates: dict[str, Any]) -> Any:
        free = CompileOutput.model_validate(candidates["output"])
        combined = await asyncio.to_thread(
            merge_discovery_delta,
            request=request,
            field_delta=field_delta,
            free_output=free,
            run_id=run.run_id,
        )
        final = await asyncio.to_thread(compiler.compose_batch_output, request, combined)
        final_hash = await asyncio.to_thread(compiler.compile_output_hash_g3, final)
        outcome = await run_independent_discovery_final_review(
            service=service,
            artifacts=artifacts,
            scope=scope,
            run=run,
            stage=stage,
            job=job,
            request=request,
            discovery_candidates=candidates,
            final_composed_output=final,
            final_composed_output_hash=final_hash,
        )
        return free, combined, final, outcome

    free, combined, final, outcome = await attempt(discovery_candidates)
    prior_drafts: tuple[ArtifactDraft, ...] = ()
    selection = discovery_candidates.get("dependency_selection")
    pending = 0
    if selection is not None and selection.get("contract") == "native-dependency-selection.830.v2":
        from insurance_harness.product_ingestion.native_dependency_aggregate import (
            prune_aggregate_selection,
        )
        from insurance_harness.product_ingestion.native_review_pruning import review_pruning_input

        pending = len(selection["isolated_candidates"])
        receipt = await asyncio.to_thread(
            review_pruning_input, selection=selection, outcome=outcome, run_id=run.run_id
        )
        if receipt is not None:
            pruned = await asyncio.to_thread(prune_aggregate_selection, selection, receipt)
            pending = pruned.pending_candidate_count
            # Empty survivors retain the first failure; no second model call.
            if pruned.output.pages or pruned.output.definitions:
                initial_hash = compiler.compile_output_hash_g3(final)
                initial = outcome
                prior_drafts = tuple(
                    row.model_copy(update={"artifact_key": "initial:" + initial_hash})
                    for row in initial.drafts
                )
                candidates = {
                    **discovery_candidates,
                    "output": pruned.output.model_dump(mode="json"),
                    "dependency_selection": pruned.selection,
                    "dispositions": [
                        row
                        for row in discovery_candidates["dispositions"]
                        if row["candidate_id"] in pruned.retained_review_ids
                    ],
                }
                free, combined, final, outcome = await attempt(candidates)
                value = {
                    "contract": "native-review-pruning.830.v1",
                    "initial_final_hash": initial_hash,
                    "new_final_hash": compiler.compile_output_hash_g3(final),
                    "selection": pruned.selection,
                }
                prior_drafts += (
                    artifact(
                        "native_review_pruning",
                        "product",
                        json_bytes(value),
                        stage.dependency_sha256,
                    ),
                )
                summary = {
                    **outcome.summary,
                    "reused": bool(initial.summary.get("reused") or outcome.summary.get("reused")),
                    "call_ids": sorted(
                        set(initial.summary.get("call_ids", ()))
                        | set(outcome.summary.get("call_ids", ()))
                    ),
                }
                outcome = replace(outcome, summary=summary)
    if pending:
        summary = {
            **outcome.summary,
            "dependency_policy": "candidate-dependencies.830.v1",
            "pending_candidate_count": pending,
        }
        outcome = replace(outcome, summary=summary)
    # One product summary and one product proof; first-attempt artifacts are audit only.
    final_drafts = tuple(
        artifact(
            row.artifact_kind,
            row.artifact_key,
            json_bytes(outcome.summary),
            stage.dependency_sha256,
        )
        if row.artifact_kind == "discovery_final_summary"
        else row
        for row in outcome.drafts
    )
    outcome = replace(outcome, drafts=final_drafts)
    drafts = prior_drafts + final_drafts
    if outcome.decision == "ACCEPTED":
        review = await asyncio.to_thread(
            compose_discovery_review,
            request=request,
            final_output=final,
            free_output=free,
            outcome=outcome,
            run_id=run.run_id,
        )
        drafts += (
            artifact(
                "composite_review",
                "product",
                review.model_dump_json().encode(),
                stage.dependency_sha256,
            ),
        )
        return ReviewedDiscoveryCompilation(
            combined,
            review,
            drafts,
            ProductRunState.PARTIAL_SUCCESS if pending else ProductRunState.SUCCEEDED,
        )
    return ReviewedDiscoveryCompilation(
        field_delta,
        None,
        drafts,
        ProductRunState.SUCCEEDED
        if outcome.decision == "EMPTY" and not pending
        else ProductRunState.PARTIAL_SUCCESS,
    )
