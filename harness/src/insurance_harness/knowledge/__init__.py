"""Lazy public facade for the knowledge domain.

Keeping this package initializer import-light lets pure contract modules be used
without importing ORM, publisher, or runtime infrastructure. Existing public
names remain available and load their owning module only when requested.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from insurance_harness.knowledge.authority import (
        AUTHORITY_BY_DOC_ROLE,
        CONFIDENCE_TO_FLOAT,
        authority_of,
        guess_doc_role,
    )
    from insurance_harness.knowledge.fallback import (
        FallbackAnswer,
        RawFallbackPolicy,
        RawFallbackProvider,
        RawHit,
    )
    from insurance_harness.knowledge.importer import (
        import_pred_jsonl,
        import_pred_records,
        load_pred_records,
        to_proposed_claim,
    )
    from insurance_harness.knowledge.incremental_changes import (
        ChangeItemDraftV1,
        ChangeSetDraftV1,
        IncrementalCompilationError,
        VerifiedFactV1,
        compile_incremental_changes,
    )
    from insurance_harness.knowledge.merge import (
        MergeEngine,
        MergeError,
        ReviewDecisionConflict,
        ReviewPreconditionRequired,
        ReviewStale,
        apply_change_item,
        apply_conflict_judgements,
        derive_overturn_key,
        policy_from_settings,
        publish_claim,
        read_conflict_judgements,
        reject_change_item,
        request_review_overturn,
        resolve_review,
        retract_source,
        write_conflict_judge_queue,
    )
    from insurance_harness.knowledge.models import (
        ALLOWED_REVIEW_ACTIONS,
        ConflictJudgement,
        ConflictJudgeRequest,
        ImportPartitionReport,
        ImportReport,
        MergePolicy,
        MergeReport,
        ProposedClaim,
        ProposedEvidence,
        SourceImportContext,
        SourceImportIdentity,
        value_hash,
    )
    from insurance_harness.knowledge.pages import (
        RenderedPage,
        build_page_claims,
        product_page_slug,
        render_product_page,
        render_snapshot_pages,
    )
    from insurance_harness.knowledge.projection import (
        ChangeItemProjection,
        ReviewAggregate,
        claim_revisions,
        load_review_aggregate,
        load_review_aggregates,
        project_change_item,
    )
    from insurance_harness.knowledge.publisher import (
        PublishResult,
        ReleasePublisher,
        RollbackResult,
        current_snapshot_id,
        default_snapshot_label,
        snapshot_claim_set,
    )
    from insurance_harness.knowledge.reader import (
        CoverageGap,
        CoverageGapCode,
        SnapshotFactsResult,
        SnapshotReader,
        SnapshotReadError,
    )
    from insurance_harness.knowledge.reconcile import ReconcileResult
    from insurance_harness.knowledge.release_plan import (
        ActionExecution,
        LegacyPageOwnership,
        PageOwnershipCollision,
        PublishAction,
        PublishPlan,
        ReleasePlanExecutor,
        WikiPageClient,
        WikiWriteVerificationError,
    )
    from insurance_harness.knowledge.retractions import RetractionProofV1
    from insurance_harness.knowledge.review import (
        derive_review_key,
        ensure_review_item,
        get_review_item,
    )
    from insurance_harness.knowledge.snapshots import (
        FrozenEvidence,
        SnapshotBuildError,
        SnapshotFactView,
        build_snapshot_facts,
    )
    from insurance_harness.knowledge.source_authority import (
        FactScopeV1,
        MaterialBindingReceiptV1,
        SourceAuthorityV1,
        compare_source_authority,
    )
    from insurance_harness.knowledge.source_lifecycle import (
        BackfillResolutionResult,
        EventAggregateKind,
        EventLinks,
        LifecycleBusinessIntent,
        LifecycleBusinessOutcome,
        LifecycleDecision,
        LifecycleDecisionResult,
        LifecycleHeadIdentity,
        LifecycleState,
        PersistedLifecycleResult,
        SourceLifecycleBlocked,
        SourceLifecycleContention,
        SourceLifecycleError,
        coordinate_source_lifecycle,
        decide_source_lifecycle,
        resolve_source_lifecycle_backfill_issue,
        source_lifecycle_lock_key,
    )
    from insurance_harness.knowledge.source_revision import (
        SourceRevisionReport,
        notify_source_revision,
    )

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
__all__ = (
    "AUTHORITY_BY_DOC_ROLE",
    "CONFIDENCE_TO_FLOAT",
    "authority_of",
    "guess_doc_role",
    "FallbackAnswer",
    "RawFallbackPolicy",
    "RawFallbackProvider",
    "RawHit",
    "import_pred_jsonl",
    "import_pred_records",
    "load_pred_records",
    "to_proposed_claim",
    "ChangeItemDraftV1",
    "ChangeSetDraftV1",
    "IncrementalCompilationError",
    "VerifiedFactV1",
    "compile_incremental_changes",
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
    "RenderedPage",
    "build_page_claims",
    "product_page_slug",
    "render_product_page",
    "render_snapshot_pages",
    "ChangeItemProjection",
    "ReviewAggregate",
    "claim_revisions",
    "load_review_aggregate",
    "load_review_aggregates",
    "project_change_item",
    "PublishResult",
    "ReleasePublisher",
    "RollbackResult",
    "current_snapshot_id",
    "default_snapshot_label",
    "snapshot_claim_set",
    "CoverageGap",
    "CoverageGapCode",
    "SnapshotFactsResult",
    "SnapshotReader",
    "SnapshotReadError",
    "ReconcileResult",
    "ActionExecution",
    "LegacyPageOwnership",
    "PageOwnershipCollision",
    "PublishAction",
    "PublishPlan",
    "ReleasePlanExecutor",
    "WikiPageClient",
    "WikiWriteVerificationError",
    "RetractionProofV1",
    "derive_review_key",
    "ensure_review_item",
    "get_review_item",
    "FrozenEvidence",
    "SnapshotBuildError",
    "SnapshotFactView",
    "build_snapshot_facts",
    "FactScopeV1",
    "MaterialBindingReceiptV1",
    "SourceAuthorityV1",
    "compare_source_authority",
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
    "SourceRevisionReport",
    "notify_source_revision",
)


def __getattr__(name: str) -> object:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *__all__))
