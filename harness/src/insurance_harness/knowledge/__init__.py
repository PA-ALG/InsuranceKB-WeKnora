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
    ImportReport,
    MergePolicy,
    MergeReport,
    ProposedClaim,
    ProposedEvidence,
    value_hash,
)
from insurance_harness.knowledge.pages import (
    RenderedPage,
    build_page_claims,
    product_page_slug,
    render_product_page,
)
from insurance_harness.knowledge.publisher import (
    PublishResult,
    RollbackResult,
    current_snapshot_id,
    default_snapshot_label,
    publish_product_version,
    rollback_to_snapshot,
    snapshot_claim_set,
)
from insurance_harness.knowledge.review import (
    derive_review_key,
    ensure_review_item,
    get_review_item,
)

__all__ = [
    "ALLOWED_REVIEW_ACTIONS",
    "AUTHORITY_BY_DOC_ROLE",
    "CONFIDENCE_TO_FLOAT",
    "ConflictJudgeRequest",
    "ConflictJudgement",
    "ImportReport",
    "MergeEngine",
    "MergeError",
    "MergePolicy",
    "MergeReport",
    "ProposedClaim",
    "ProposedEvidence",
    "PublishResult",
    "RenderedPage",
    "RollbackResult",
    "apply_change_item",
    "apply_conflict_judgements",
    "authority_of",
    "build_page_claims",
    "current_snapshot_id",
    "default_snapshot_label",
    "derive_review_key",
    "ensure_review_item",
    "get_review_item",
    "guess_doc_role",
    "import_pred_jsonl",
    "import_pred_records",
    "load_pred_records",
    "overturn_review",
    "policy_from_settings",
    "product_page_slug",
    "publish_claim",
    "publish_product_version",
    "read_conflict_judgements",
    "reject_change_item",
    "render_product_page",
    "resolve_review",
    "retract_source",
    "rollback_to_snapshot",
    "snapshot_claim_set",
    "to_proposed_claim",
    "value_hash",
    "write_conflict_judge_queue",
]
