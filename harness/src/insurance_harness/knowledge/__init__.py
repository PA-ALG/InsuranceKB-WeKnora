"""Lazy public facade for the knowledge domain.

Keeping this package initializer import-light lets pure contract modules be used
without importing ORM, publisher, or runtime infrastructure. Existing public
names remain available and load their owning module only when requested.
"""

from __future__ import annotations

from importlib import import_module
from typing import Final

_GROUPS: Final[dict[str, tuple[str, ...]]] = {
    "authority": ("AUTHORITY_BY_DOC_ROLE", "CONFIDENCE_TO_FLOAT", "authority_of", "guess_doc_role"),
    "fallback": ("FallbackAnswer", "RawFallbackPolicy", "RawFallbackProvider", "RawHit"),
    "importer": (
        "import_pred_jsonl",
        "import_pred_records",
        "load_pred_records",
        "to_proposed_claim",
    ),
    "incremental_changes": (
        "ChangeItemDraftV1",
        "ChangeSetDraftV1",
        "IncrementalCompilationError",
        "VerifiedFactV1",
        "compile_incremental_changes",
    ),
    "merge": (
        "MergeEngine",
        "MergeError",
        "ReviewDecisionConflict",
        "ReviewPreconditionRequired",
        "ReviewStale",
        "apply_change_item",
        "apply_conflict_judgements",
        "derive_overturn_key",
        "policy_from_settings",
        "publish_claim",
        "read_conflict_judgements",
        "reject_change_item",
        "request_review_overturn",
        "resolve_review",
        "retract_source",
        "write_conflict_judge_queue",
    ),
    "models": (
        "ALLOWED_REVIEW_ACTIONS",
        "ConflictJudgement",
        "ConflictJudgeRequest",
        "ImportPartitionReport",
        "ImportReport",
        "MergePolicy",
        "MergeReport",
        "ProposedClaim",
        "ProposedEvidence",
        "SourceImportContext",
        "SourceImportIdentity",
        "value_hash",
    ),
    "pages": (
        "RenderedPage",
        "build_page_claims",
        "product_page_slug",
        "render_product_page",
        "render_snapshot_pages",
    ),
    "projection": (
        "ChangeItemProjection",
        "ReviewAggregate",
        "claim_revisions",
        "load_review_aggregate",
        "load_review_aggregates",
        "project_change_item",
    ),
    "publisher": (
        "PublishResult",
        "ReleasePublisher",
        "RollbackResult",
        "current_snapshot_id",
        "default_snapshot_label",
        "snapshot_claim_set",
    ),
    "reader": (
        "CoverageGap",
        "CoverageGapCode",
        "SnapshotFactsResult",
        "SnapshotReader",
        "SnapshotReadError",
    ),
    "reconcile": ("ReconcileResult",),
    "release_plan": (
        "ActionExecution",
        "LegacyPageOwnership",
        "PageOwnershipCollision",
        "PublishAction",
        "PublishPlan",
        "ReleasePlanExecutor",
        "WikiPageClient",
        "WikiWriteVerificationError",
    ),
    "retractions": ("RetractionProofV1",),
    "review": ("derive_review_key", "ensure_review_item", "get_review_item"),
    "snapshots": (
        "FrozenEvidence",
        "SnapshotBuildError",
        "SnapshotFactView",
        "build_snapshot_facts",
    ),
    "source_authority": (
        "FactScopeV1",
        "MaterialBindingReceiptV1",
        "SourceAuthorityV1",
        "compare_source_authority",
    ),
    "source_lifecycle": (
        "BackfillResolutionResult",
        "EventAggregateKind",
        "EventLinks",
        "LifecycleBusinessIntent",
        "LifecycleBusinessOutcome",
        "LifecycleDecision",
        "LifecycleDecisionResult",
        "LifecycleHeadIdentity",
        "LifecycleState",
        "PersistedLifecycleResult",
        "SourceLifecycleBlocked",
        "SourceLifecycleContention",
        "SourceLifecycleError",
        "coordinate_source_lifecycle",
        "decide_source_lifecycle",
        "resolve_source_lifecycle_backfill_issue",
        "source_lifecycle_lock_key",
    ),
    "source_revision": ("SourceRevisionReport", "notify_source_revision"),
}

_EXPORTS: Final[dict[str, str]] = {
    name: f"insurance_harness.knowledge.{module}"
    for module, names in _GROUPS.items()
    for name in names
}
__all__ = tuple(_EXPORTS)


def __getattr__(name: str) -> object:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *__all__))
