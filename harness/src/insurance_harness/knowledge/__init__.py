"""知识域主链（change 007）：Claim 落库 → 增量合并 → 审核门禁 → 页面编译发布。

数据模型/裁决序权威：docs/insurance-kb/03；验收条款：
openspec/changes/007-claims-changeset-publish/specs/mainchain.md。
"""

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
from insurance_harness.knowledge.merge import (
    MergeEngine,
    MergeError,
    apply_change_item,
    apply_conflict_judgements,
    overturn_review,
    policy_from_settings,
    publish_claim,
    read_conflict_judgements,
    reject_change_item,
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
from insurance_harness.knowledge.source_revision import (
    SourceRevisionReport,
    notify_source_revision,
)

__all__ = [
    "ActionExecution",
    "ALLOWED_REVIEW_ACTIONS",
    "AUTHORITY_BY_DOC_ROLE",
    "CONFIDENCE_TO_FLOAT",
    "ConflictJudgeRequest",
    "ConflictJudgement",
    "CoverageGap",
    "CoverageGapCode",
    "FallbackAnswer",
    "ImportReport",
    "ImportPartitionReport",
    "LegacyPageOwnership",
    "MergeEngine",
    "MergeError",
    "MergePolicy",
    "MergeReport",
    "PageOwnershipCollision",
    "ProposedClaim",
    "ProposedEvidence",
    "SourceImportContext",
    "SourceImportIdentity",
    "SourceRevisionReport",
    "FrozenEvidence",
    "PublishResult",
    "PublishAction",
    "PublishPlan",
    "RawFallbackPolicy",
    "RawFallbackProvider",
    "RawHit",
    "ReleasePlanExecutor",
    "ReleasePublisher",
    "ReconcileResult",
    "SnapshotBuildError",
    "SnapshotFactView",
    "SnapshotFactsResult",
    "SnapshotReadError",
    "SnapshotReader",
    "WikiPageClient",
    "WikiWriteVerificationError",
    "RenderedPage",
    "RollbackResult",
    "apply_change_item",
    "apply_conflict_judgements",
    "authority_of",
    "build_page_claims",
    "build_snapshot_facts",
    "current_snapshot_id",
    "default_snapshot_label",
    "derive_review_key",
    "ensure_review_item",
    "get_review_item",
    "guess_doc_role",
    "import_pred_jsonl",
    "import_pred_records",
    "load_pred_records",
    "notify_source_revision",
    "overturn_review",
    "policy_from_settings",
    "product_page_slug",
    "publish_claim",
    "read_conflict_judgements",
    "reject_change_item",
    "render_product_page",
    "render_snapshot_pages",
    "resolve_review",
    "retract_source",
    "snapshot_claim_set",
    "to_proposed_claim",
    "value_hash",
    "write_conflict_judge_queue",
]
