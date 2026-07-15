"""增量合并引擎（change 007；裁决序严格按 docs/insurance-kb/03 §6.2，specs K3/K4）。

五种 ChangeItem：add / enrich / supersede / conflict / retract（03 §2.5）。
所有变更经由不可变 ChangeSet；每次应用写 ClaimRevision 留痕；自动裁决全部写
decision_basis 可翻案（翻案 = 新 ChangeSet）。裁决序④不实调模型：冲突请求进
claude-session 队列（复用 compiler judge-queue 的 JSONL 形态），回写后按 llm_verdict 裁决。
"""

import hashlib
import json
import logging
import re
from collections.abc import Callable
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from insurance_harness.goldenset.baseline import RunFingerprint
    from insurance_harness.knowledge.quality_gate import QualityGate

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from insurance_harness.config import HarnessSettings
from insurance_harness.db.base import utcnow
from insurance_harness.db.models import InsuranceProduct, ProductVersion
from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
    require_current_scope,
)
from insurance_harness.knowledge.models import (
    ConflictJudgement,
    ConflictJudgeRequest,
    LineageStatus,
    MergePolicy,
    MergeReport,
    ProposedClaim,
    ProposedEvidence,
    SourceImportIdentity,
    normalize_value,
)
from insurance_harness.knowledge.review import (
    _require_scoped_review_subject,
    derive_review_key,
    ensure_review_item,
)
from insurance_harness.knowledge.source_revision import (
    derive_retract_event_key,
    validate_retract_tombstone,
)
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    ClaimEvidence,
    ClaimRevision,
    Conflict,
    ReviewItem,
)

RiskResolver = Callable[[str], str]

_LOG = logging.getLogger(__name__)

_STATUS_RANK = {"published": 0, "candidate": 1, "draft": 2}


class MergeError(RuntimeError):
    pass


def _scope_mismatch() -> ScopeViolation:
    return ScopeViolation("scope mismatch")


def _claim_business_subject(claim: Claim) -> tuple[str | None, str | None, str]:
    return claim.product_version_id, claim.concept_id, claim.predicate


def _proposal_business_subject(
    proposed: dict[str, Any],
) -> tuple[str | None, str | None, str | None]:
    product_version_id = proposed.get("product_version_id")
    concept_id = proposed.get("concept_id")
    predicate = proposed.get("predicate")
    return (
        str(product_version_id) if product_version_id is not None else None,
        str(concept_id) if concept_id is not None else None,
        str(predicate) if predicate is not None else None,
    )


def _sort_evidence(
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        evidence,
        key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True),
    )


def _canonical_fact_proposal(proposed: dict[str, Any]) -> dict[str, Any]:
    """Canonical persisted/adjudicated proposal fields.

    ``field_name`` and evidence ``doc_title`` are display-only: neither is persisted
    on Claim/ClaimEvidence nor used by adjudication, so they are intentionally ignored.
    Evidence ordering is also non-semantic and is normalized before comparison.
    """
    try:
        parsed = ProposedClaim.model_validate(proposed)
    except ValidationError as exc:
        raise _scope_mismatch() from exc
    canonical = parsed.model_dump(mode="json", exclude={"field_name"})
    canonical["concept_id"] = proposed.get("concept_id")
    evidence: list[dict[str, Any]] = []
    for raw_evidence in canonical["evidence"]:
        row = dict(raw_evidence)
        row.pop("doc_title", None)
        evidence.append(row)
    canonical["evidence"] = _sort_evidence(evidence)
    return canonical


def _require_claim_matches_proposal(
    session: Session,
    claim: Claim,
    proposed: dict[str, Any],
) -> None:
    claim_fact = {
        "space_id": claim.space_id,
        "product_version_id": claim.product_version_id,
        "concept_id": claim.concept_id,
        "predicate": claim.predicate,
        "value_state": claim.value_state,
        "value": claim_value_text(claim),
        "effective_from": (
            claim.effective_from.isoformat() if claim.effective_from else None
        ),
        "confidence": claim.confidence,
        "extraction_method": claim.extraction_method,
        "schema_version": claim.schema_version,
        "pending_judge": claim.pending_judge,
    }
    proposal_fact = {key: proposed[key] for key in claim_fact}
    if claim_fact != proposal_fact:
        raise _scope_mismatch()
    evidence = _sort_evidence(
        [
            ProposedEvidence(
                knowledge_id=row.knowledge_id,
                raw_kb_id=row.raw_kb_id,
                source_revision=row.source_revision,
                file_hash=row.file_hash,
                original_digest=row.original_digest,
                parser_version=row.parser_version,
                chunk_id=row.chunk_id,
                chunk_hash=row.chunk_hash,
                lineage_status=cast(LineageStatus | None, row.lineage_status),
                stale_at=(
                    row.stale_at.replace(tzinfo=UTC)
                    if row.stale_at is not None and row.stale_at.tzinfo is None
                    else row.stale_at
                ),
                quote=row.quote,
                page=row.page,
                doc_role=row.doc_role,
                authority_level=row.authority_level,
                extraction_method=row.extraction_method,
            ).model_dump(mode="json", exclude={"doc_title"})
            for row in _evidence_for_claim(session, claim)
        ]
    )
    if evidence != proposed["evidence"]:
        raise _scope_mismatch()


def _require_scoped_product_version(
    session: Session, scope: KnowledgeScope, product_version_id: str
) -> None:
    found = session.execute(
        select(ProductVersion.id)
        .join(InsuranceProduct, InsuranceProduct.id == ProductVersion.product_id)
        .where(
            ProductVersion.id == product_version_id,
            ProductVersion.space_id == scope.space_id,
            InsuranceProduct.space_id == scope.space_id,
        )
    ).scalar_one_or_none()
    if found is None:
        raise _scope_mismatch()


def _require_scoped_claim(
    session: Session, scope: KnowledgeScope, claim_or_id: Claim | str
) -> Claim:
    claim_id = claim_or_id.id if isinstance(claim_or_id, Claim) else claim_or_id
    claim = session.execute(
        select(Claim).where(
            Claim.id == claim_id,
            Claim.space_id == scope.space_id,
        )
    ).scalar_one_or_none()
    if claim is None:
        raise _scope_mismatch()
    return claim


def _require_scoped_change_set(
    session: Session, scope: KnowledgeScope, change_set_or_id: ChangeSet | str
) -> ChangeSet:
    change_set_id = (
        change_set_or_id.id
        if isinstance(change_set_or_id, ChangeSet)
        else change_set_or_id
    )
    change_set = session.execute(
        select(ChangeSet).where(
            ChangeSet.id == change_set_id,
            ChangeSet.space_id == scope.space_id,
        )
    ).scalar_one_or_none()
    if change_set is None:
        raise _scope_mismatch()
    return change_set


def _require_scoped_change_item(
    session: Session, scope: KnowledgeScope, item_or_id: ChangeItem | str
) -> ChangeItem:
    item_id = item_or_id.id if isinstance(item_or_id, ChangeItem) else item_or_id
    item = session.execute(
        select(ChangeItem)
        .join(ChangeSet, ChangeSet.id == ChangeItem.change_set_id)
        .where(
            ChangeItem.id == item_id,
            ChangeSet.space_id == scope.space_id,
        )
    ).scalar_one_or_none()
    if item is None:
        raise _scope_mismatch()
    return item


def _require_scoped_conflict(
    session: Session, scope: KnowledgeScope, conflict_id: str
) -> Conflict:
    conflict = session.execute(
        select(Conflict)
        .join(ChangeItem, ChangeItem.id == Conflict.change_item_id)
        .join(ChangeSet, ChangeSet.id == ChangeItem.change_set_id)
        .where(
            Conflict.id == conflict_id,
            ChangeSet.space_id == scope.space_id,
        )
    ).scalar_one_or_none()
    if conflict is None:
        raise _scope_mismatch()
    if conflict.existing_claim_id is not None:
        _require_scoped_claim(session, scope, conflict.existing_claim_id)
    proposed_space_id = conflict.proposed.get("space_id")
    if proposed_space_id is not None and proposed_space_id != scope.space_id:
        raise _scope_mismatch()
    return conflict


def _require_conflict_parent_semantics(
    item: ChangeItem,
    conflict: Conflict,
) -> None:
    if conflict.change_item_id != item.id:
        raise _scope_mismatch()
    if conflict.existing_claim_id != item.proposed.get("existing_claim_id"):
        raise _scope_mismatch()
    item_claim = item.proposed.get("claim")
    if not isinstance(item_claim, dict):
        raise _scope_mismatch()
    if _canonical_fact_proposal(item_claim) != _canonical_fact_proposal(
        conflict.proposed
    ):
        raise _scope_mismatch()


def _require_scoped_item_aggregate(
    session: Session, scope: KnowledgeScope, item_or_id: ChangeItem | str
) -> tuple[ChangeItem, Claim | None, Claim | None, tuple[Conflict, ...]]:
    """Guard a child ChangeItem through its ChangeSet and every referenced Claim."""
    item = _require_scoped_change_item(session, scope, item_or_id)
    claim = (
        _require_scoped_claim(session, scope, item.claim_id)
        if item.claim_id is not None
        else None
    )
    existing_id = item.proposed.get("existing_claim_id")
    placeholder_id = item.proposed.get("placeholder_claim_id")
    existing = (
        _require_scoped_claim(session, scope, str(existing_id))
        if existing_id
        else None
    )
    placeholder = (
        _require_scoped_claim(session, scope, str(placeholder_id))
        if placeholder_id
        else None
    )
    old = existing or placeholder
    proposed_claim = item.proposed.get("claim")
    canonical_proposed: dict[str, Any] | None = None
    if isinstance(proposed_claim, dict):
        canonical_proposed = _canonical_fact_proposal(proposed_claim)
        proposed_space_id = proposed_claim.get("space_id")
        if proposed_space_id is not None and proposed_space_id != scope.space_id:
            raise _scope_mismatch()
        proposed_version_id = proposed_claim.get("product_version_id")
        if proposed_version_id:
            _require_scoped_product_version(
                session, scope, str(proposed_version_id)
            )
        if claim is not None:
            _require_claim_matches_proposal(
                session,
                claim,
                canonical_proposed,
            )
    if old is not None:
        subject = (
            _claim_business_subject(claim)
            if claim is not None
            else _proposal_business_subject(proposed_claim)
            if isinstance(proposed_claim, dict)
            else None
        )
        if subject is None or subject != _claim_business_subject(old):
            raise _scope_mismatch()
    conflicts = tuple(
        session.execute(
            select(Conflict)
            .join(ChangeItem, ChangeItem.id == Conflict.change_item_id)
            .join(ChangeSet, ChangeSet.id == ChangeItem.change_set_id)
            .where(
                Conflict.change_item_id == item.id,
                ChangeSet.space_id == scope.space_id,
            )
        ).scalars()
    )
    for conflict in conflicts:
        _require_conflict_parent_semantics(item, conflict)
        if conflict.existing_claim_id is not None:
            _require_scoped_claim(session, scope, conflict.existing_claim_id)
        proposed_space_id = conflict.proposed.get("space_id")
        if proposed_space_id is not None and proposed_space_id != scope.space_id:
            raise _scope_mismatch()
        proposed_version_id = conflict.proposed.get("product_version_id")
        if proposed_version_id:
            _require_scoped_product_version(session, scope, str(proposed_version_id))
    return item, claim, old, conflicts


def validate_scoped_change_set_items(
    session: Session,
    scope: KnowledgeScope,
    change_set: ChangeSet,
) -> int:
    """Validate every child item and its referenced aggregate in one scope."""
    require_current_scope(session, scope)
    change_set = _require_scoped_change_set(session, scope, change_set)
    items = tuple(
        session.scalars(
            select(ChangeItem).where(ChangeItem.change_set_id == change_set.id)
        )
    )
    for item in items:
        _require_scoped_item_aggregate(session, scope, item)
    return len(items)


def _require_scoped_conflict_aggregate(
    session: Session,
    scope: KnowledgeScope,
    conflict_id: str,
) -> tuple[Conflict, ChangeItem, Claim | None, Claim | None]:
    conflict = _require_scoped_conflict(session, scope, conflict_id)
    item, claim, old, _ = _require_scoped_item_aggregate(
        session, scope, conflict.change_item_id
    )
    return conflict, item, claim, old


def policy_from_settings(settings: HarnessSettings) -> MergePolicy:
    """低风险 enrich 自动通过阈值可配（K4.4）；默认关闭=全走审核。"""
    return MergePolicy(
        auto_apply_enrich=settings.merge_auto_apply_enrich,
        enrich_auto_min_confidence=settings.merge_enrich_auto_min_confidence,
    )


# ------------------------------------------------------------------ 留痕原语


def _snapshot(claim: Claim) -> dict[str, Any]:
    return {
        "id": claim.id,
        "predicate": claim.predicate,
        "value_state": claim.value_state,
        "value": claim.value,
        "status": claim.status,
        "confidence": claim.confidence,
        "effective_from": claim.effective_from.isoformat() if claim.effective_from else None,
        "superseded_by": claim.superseded_by,
        "current_revision": claim.current_revision,
    }


def _write_revision(
    session: Session,
    claim: Claim,
    *,
    before: dict[str, Any] | None,
    change_item_id: str | None,
    actor: str,
    reason: str | None = None,
) -> ClaimRevision:
    """每次 ChangeItem 应用产生一条不可变修订（03 §5.1，K3.3）。"""
    claim.current_revision += 1
    revision = ClaimRevision(
        claim_id=claim.id,
        revision_no=claim.current_revision,
        before=before,
        after=_snapshot(claim),
        change_item_id=change_item_id,
        actor=actor,
        reason=reason,
    )
    session.add(revision)
    session.flush()
    return revision


def _evidence_rows(claim_id: str, prop: ProposedClaim) -> list[ClaimEvidence]:
    return [
        ClaimEvidence(
            claim_id=claim_id,
            knowledge_id=e.knowledge_id,
            raw_kb_id=e.raw_kb_id,
            source_revision=e.source_revision,
            file_hash=e.file_hash,
            original_digest=e.original_digest,
            parser_version=e.parser_version,
            chunk_id=e.chunk_id,
            chunk_hash=e.chunk_hash,
            lineage_status=e.lineage_status,
            stale_at=e.stale_at,
            quote=e.quote,
            page=e.page,
            authority_level=e.authority_level,
            doc_role=e.doc_role,
            extraction_method=e.extraction_method,
        )
        for e in prop.evidence
    ]


def _create_claim(session: Session, prop: ProposedClaim, *, status: str) -> Claim:
    claim = Claim(
        space_id=prop.space_id,
        subject_type="product_version",
        product_version_id=prop.product_version_id,
        predicate=prop.predicate,
        value_state=prop.value_state,
        value=None if prop.value is None else {"text": prop.value},
        effective_from=prop.effective_from,
        status=status,
        confidence=prop.confidence,
        extraction_method=prop.extraction_method,
        schema_version=prop.schema_version,
        pending_judge=prop.pending_judge,
    )
    session.add(claim)
    session.flush()
    for row in _evidence_rows(claim.id, prop):
        session.add(row)
    session.flush()
    return claim


def claim_value_text(claim: Claim) -> str | None:
    if claim.value is None:
        return None
    text = claim.value.get("text")
    return None if text is None else str(text)


def _evidence_for_claim(session: Session, claim: Claim) -> list[ClaimEvidence]:
    return list(
        session.execute(
            select(ClaimEvidence)
            .join(Claim, Claim.id == ClaimEvidence.claim_id)
            .where(
                ClaimEvidence.claim_id == claim.id,
                Claim.space_id == claim.space_id,
            )
        ).scalars()
    )


def claim_evidence(
    session: Session, scope: KnowledgeScope, claim_id: str
) -> list[ClaimEvidence]:
    require_current_scope(session, scope)
    claim = _require_scoped_claim(session, scope, claim_id)
    return _evidence_for_claim(session, claim)


def _authority_for_claim(session: Session, claim: Claim) -> int:
    return min(
        (e.authority_level for e in _evidence_for_claim(session, claim)),
        default=6,
    )


def claim_authority(
    session: Session, scope: KnowledgeScope, claim: Claim
) -> int:
    require_current_scope(session, scope)
    claim = _require_scoped_claim(session, scope, claim)
    return _authority_for_claim(session, claim)


def _require_publish_context(
    session: Session,
    scope: KnowledgeScope,
    claim: Claim,
    *,
    change_item_id: str | None,
    superseding: Claim | None = None,
) -> tuple[Claim, Claim | None]:
    """Validate the complete publish aggregate without mutating it."""
    claim = _require_scoped_claim(session, scope, claim)
    superseding = (
        _require_scoped_claim(session, scope, superseding)
        if superseding is not None
        else None
    )
    if change_item_id is None:
        raise _scope_mismatch()
    item, item_claim, old, _ = _require_scoped_item_aggregate(
        session, scope, change_item_id
    )
    if item_claim is None or item_claim.id != claim.id:
        raise _scope_mismatch()
    existing_id = item.proposed.get("existing_claim_id")
    placeholder_id = item.proposed.get("placeholder_claim_id")
    if item.action == "add":
        if (
            item.proposed.get("mode") == "unknown_placeholder"
            or existing_id
            or placeholder_id
            or superseding is not None
        ):
            raise _scope_mismatch()
    elif item.action == "enrich" and item.proposed.get("mode") == "fill_unknown":
        if (
            not placeholder_id
            or existing_id
            or old is None
            or superseding is None
            or superseding.id != old.id
        ):
            raise _scope_mismatch()
    elif item.action in ("supersede", "conflict"):
        if (
            not existing_id
            or placeholder_id
            or old is None
            or superseding is None
            or superseding.id != old.id
        ):
            raise _scope_mismatch()
    else:
        raise _scope_mismatch()
    if superseding is not None:
        # effective_from/effective_to are version/adjudication dimensions: K3.2
        # intentionally permits a newer effective_from to supersede an older fact.
        if _claim_business_subject(claim) != _claim_business_subject(superseding):
            raise _scope_mismatch()
    if not _evidence_for_claim(session, claim):
        raise MergeError(f"claim {claim.id} 无证据，不允许发布")
    others = session.execute(
        select(Claim).where(
            Claim.space_id == scope.space_id,
            Claim.product_version_id == claim.product_version_id,
            Claim.predicate == claim.predicate,
            Claim.status == "published",
            Claim.id != claim.id,
        )
    ).scalars().all()
    for other in others:
        if superseding is None or other.id != superseding.id:
            raise MergeError(
                f"({claim.product_version_id}, {claim.predicate}) 已有 published claim "
                f"{other.id}，必须经 supersede/conflict 流程"
            )
    return claim, superseding


def publish_claim(
    session: Session,
    scope: KnowledgeScope,
    claim: Claim,
    *,
    change_item_id: str | None,
    actor: str,
    reason: str | None = None,
    superseding: Claim | None = None,
) -> None:
    """candidate/draft → published；无 Evidence 不允许发布（03 原则 2）。

    应用层兜底"同主语同谓词只允许一条已发布"（部分唯一索引的 NULL 维度不去重，K1.2）。
    """
    require_current_scope(session, scope)
    claim, superseding = _require_publish_context(
        session,
        scope,
        claim,
        change_item_id=change_item_id,
        superseding=superseding,
    )
    before = _snapshot(claim)
    claim.status = "published"
    _write_revision(
        session, claim, before=before, change_item_id=change_item_id, actor=actor, reason=reason
    )
    if superseding is not None and superseding.status != "superseded":
        _supersede_claim(
            session, superseding, claim, change_item_id=change_item_id, actor=actor, reason=reason
        )


def _supersede_claim(
    session: Session,
    old: Claim,
    new: Claim,
    *,
    change_item_id: str | None,
    actor: str,
    reason: str | None = None,
) -> None:
    before = _snapshot(old)
    old.status = "superseded"
    old.superseded_by = new.id
    _write_revision(
        session, old, before=before, change_item_id=change_item_id, actor=actor, reason=reason
    )


def _retract_claim(
    session: Session,
    claim: Claim,
    *,
    change_item_id: str | None,
    actor: str,
    reason: str | None = None,
) -> None:
    before = _snapshot(claim)
    claim.status = "retracted"
    _write_revision(
        session, claim, before=before, change_item_id=change_item_id, actor=actor, reason=reason
    )


# ------------------------------------------------------------------ 合并引擎


class MergeEngine:
    """一批 ProposedClaim vs 已有 Claim → ChangeItem 五种动作（K3）。"""

    def __init__(
        self,
        session: Session,
        *,
        scope: KnowledgeScope,
        policy: MergePolicy | None = None,
        risk_of: RiskResolver | None = None,
        created_by: str = "merge-engine",
        quality_gate: "QualityGate | None" = None,
        run_fingerprint: "RunFingerprint | None" = None,
    ) -> None:
        require_current_scope(session, scope)
        self.session = session
        self.scope = scope
        self.policy = policy or MergePolicy()
        self.risk_of: RiskResolver = risk_of or (lambda predicate: "low")
        self.created_by = created_by
        # 019 Q4.2：gate 是自动发布的唯一权威，policy 布尔位只表达"运营是否允许自动化"。
        self.quality_gate = quality_gate
        self.run_fingerprint = run_fingerprint
        self.judge_queue: list[ConflictJudgeRequest] = []

    def _gate_ok(self, prop: ProposedClaim, risk: str, action: str) -> bool:
        """Q4.2/Q4.5：自动发布必须过 gate；**fail-closed**——无 gate/画像/指纹一律不自动，
        走 ReviewItem（design.md:17「布尔开关不能绕过 Gate，缺画像统一走 ReviewItem」）。

        pending_judge 交给 gate 裁定为权威，但 merge 层**保留独立短路做纵深防御**：
        注入的 gate 万一不 honor pending，pending 候选也绝不自动发布。gate 抛异常/签名不符时同样
        fail-closed——不得让一个坏 gate 崩掉整批 apply_batch。
        """
        if self.quality_gate is None:
            return False
        if prop.pending_judge:  # 纵深防御：pending 不自动发布，不依赖注入 gate 是否 honor
            return False
        try:
            return self.quality_gate.decide(
                prop.predicate, risk, action, self.run_fingerprint,
                pending_judge=prop.pending_judge,
            ).eligible
        except Exception as exc:  # noqa: BLE001 —— 坏 gate 一律 fail-closed（走 ReviewItem），不崩批
            # 保留可审计原因，让运营能区分"gate 故障"与"候选质量不足"。
            # 只记异常类型 + 简短消息到日志，不入业务数据、不带堆栈。
            _LOG.warning(
                "quality_gate.decide raised %s for predicate=%r action=%s → fail-closed: %s",
                type(exc).__name__, prop.predicate, action, exc,
            )
            return False

    # -- ChangeSet ---------------------------------------------------------

    def open_change_set(
        self,
        *,
        source_kind: str,
        knowledge_ids: list[str] | None = None,
        external_record_id: str | None = None,
        source_revision: str | None = None,
    ) -> tuple[ChangeSet, bool]:
        """批级幂等（K2.3）：同 (source_kind, external_record_id, source_revision)
        的已存在 ChangeSet 直接返回 (existing, False)。"""
        require_current_scope(self.session, self.scope)
        if external_record_id is not None:
            existing = self.session.execute(
                select(ChangeSet).where(
                    ChangeSet.space_id == self.scope.space_id,
                    ChangeSet.source_kind == source_kind,
                    ChangeSet.external_record_id == external_record_id,
                    ChangeSet.source_revision == source_revision,
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing, False
        change_set = ChangeSet(
            space_id=self.scope.space_id,
            source_kind=source_kind,
            knowledge_ids=knowledge_ids,
            external_record_id=external_record_id,
            source_revision=source_revision,
            status="pending",
            created_by=self.created_by,
        )
        self.session.add(change_set)
        self.session.flush()
        return change_set, True

    # -- 批应用 --------------------------------------------------------------

    def apply_batch(self, change_set: ChangeSet, proposals: list[ProposedClaim]) -> MergeReport:
        require_current_scope(self.session, self.scope)
        change_set = _require_scoped_change_set(self.session, self.scope, change_set)
        for prop in proposals:
            if prop.space_id != self.scope.space_id:
                raise _scope_mismatch()
            _require_scoped_product_version(
                self.session,
                self.scope,
                prop.product_version_id,
            )
        report = MergeReport(change_set_id=change_set.id)
        for prop in proposals:
            self._apply_one(change_set, prop, report)
        report.judge_queue_size = len(self.judge_queue)
        statuses = {
            item.decision
            for item in self.session.execute(
                select(ChangeItem).where(ChangeItem.change_set_id == change_set.id)
            ).scalars()
        }
        if statuses <= {"auto_applied", "approved"}:
            change_set.status = "applied"
        elif statuses & {"auto_applied", "approved"}:
            change_set.status = "partially_applied"
        else:
            change_set.status = "pending"
        self.session.flush()
        return report

    def _active_claim(self, product_version_id: str, predicate: str) -> Claim | None:
        rows = self.session.execute(
            select(Claim).where(
                Claim.space_id == self.scope.space_id,
                Claim.product_version_id == product_version_id,
                Claim.predicate == predicate,
                Claim.status.in_(("published", "candidate", "draft")),
            )
        ).scalars().all()
        if not rows:
            return None
        return sorted(rows, key=lambda c: (_STATUS_RANK[c.status], c.created_at))[0]

    def _apply_one(self, change_set: ChangeSet, prop: ProposedClaim, report: MergeReport) -> None:
        existing = self._active_claim(prop.product_version_id, prop.predicate)
        if prop.value_state == "unknown":
            # K2.2：unknown 只落 draft 占位（禁止发布），已有事实时不产生任何变更
            if existing is None:
                self._add_unknown_placeholder(change_set, prop)
                report.bump("add")
            return
        if existing is None:
            self._do_add(change_set, prop, report)
        elif existing.value_state == "unknown":
            self._do_fill_unknown(change_set, prop, existing, report)
        elif prop.value_hash == _existing_value_hash(existing):
            self._do_enrich_append(change_set, prop, existing, report)
        else:
            self._adjudicate(change_set, prop, existing, report)

    # -- add ----------------------------------------------------------------

    def _add_unknown_placeholder(self, change_set: ChangeSet, prop: ProposedClaim) -> None:
        claim = _create_claim(self.session, prop, status="draft")
        item = self._new_item(
            change_set,
            action="add",
            claim_id=claim.id,
            proposed={"claim": _prop_dump(prop), "mode": "unknown_placeholder"},
            decision="auto_applied",
            basis={"note": "unknown 占位 draft，禁止发布，等待后批 enrich 补全（K2.2）"},
        )
        _write_revision(
            self.session, claim, before=None, change_item_id=item.id,
            actor=self.created_by, reason="add unknown placeholder",
        )

    def _do_add(self, change_set: ChangeSet, prop: ProposedClaim, report: MergeReport) -> None:
        risk = self.risk_of(prop.predicate)
        claim = _create_claim(self.session, prop, status="candidate")
        item = self._new_item(
            change_set,
            action="add",
            claim_id=claim.id,
            proposed={"claim": _prop_dump(prop)},
            decision="needs_review",
            basis=None,
        )
        _write_revision(
            self.session, claim, before=None, change_item_id=item.id,
            actor=self.created_by, reason="add candidate",
        )
        auto = (
            self.policy.auto_apply_add
            and risk != "high"
            and self._gate_ok(prop, risk, "add")  # pending/异常 fail-closed 见 _gate_ok
        )
        if auto:
            item.decision = "auto_applied"
            publish_claim(
                self.session, self.scope, claim, change_item_id=item.id,
                actor=self.created_by, reason="auto add",
            )
        else:
            self._gate(item, prop, risk, report, new_claim_id=claim.id)
        report.bump("add")

    # -- enrich ---------------------------------------------------------------

    def _do_fill_unknown(
        self, change_set: ChangeSet, prop: ProposedClaim, placeholder: Claim, report: MergeReport
    ) -> None:
        """补 unknown 占位（03 §2.5 enrich 的"补 unknown 字段"分支）。"""
        risk = self.risk_of(prop.predicate)
        claim = _create_claim(self.session, prop, status="candidate")
        item = self._new_item(
            change_set,
            action="enrich",
            claim_id=claim.id,
            proposed={
                "claim": _prop_dump(prop),
                "mode": "fill_unknown",
                "placeholder_claim_id": placeholder.id,
            },
            decision="needs_review",
            basis=None,
        )
        _write_revision(
            self.session, claim, before=None, change_item_id=item.id,
            actor=self.created_by, reason="enrich fill unknown",
        )
        if self._enrich_auto_ok(prop, risk):
            item.decision = "auto_applied"
            publish_claim(
                self.session, self.scope, claim, change_item_id=item.id, actor=self.created_by,
                reason="auto enrich fill", superseding=placeholder,
            )
        else:
            self._gate(item, prop, risk, report, new_claim_id=claim.id)
        report.bump("enrich")

    def _do_enrich_append(
        self, change_set: ChangeSet, prop: ProposedClaim, existing: Claim, report: MergeReport
    ) -> None:
        """同值追加证据，confidence 上调（03 §2.5 enrich）。"""
        risk = self.risk_of(prop.predicate)
        seen = {
            (
                e.knowledge_id,
                e.source_revision,
                e.chunk_id,
                e.chunk_hash,
                e.lineage_status,
                e.page,
                normalize_value(e.quote),
            )
            for e in _evidence_for_claim(self.session, existing)
        }
        new_evidence = [
            e for e in prop.evidence
            if (
                e.knowledge_id,
                e.source_revision,
                e.chunk_id,
                e.chunk_hash,
                e.lineage_status,
                e.page,
                normalize_value(e.quote),
            )
            not in seen
        ]
        new_confidence = min(0.99, max(existing.confidence, prop.confidence) + 0.05)
        if not new_evidence and new_confidence <= existing.confidence:
            return  # 无增量：不产生 ChangeItem（幂等）
        item = self._new_item(
            change_set,
            action="enrich",
            claim_id=existing.id,
            proposed={
                "mode": "append_evidence",
                "evidence": [e.model_dump(mode="json") for e in new_evidence],
                "confidence": new_confidence,
            },
            decision="needs_review",
            basis=None,
        )
        if self._enrich_auto_ok(prop, risk):
            item.decision = "auto_applied"
            _apply_enrich_append(self.session, self.scope, item, actor=self.created_by)
        else:
            self._gate(item, prop, risk, report, new_claim_id=existing.id)
        report.bump("enrich")

    def _enrich_auto_ok(self, prop: ProposedClaim, risk: str) -> bool:
        """K4.4 + 019 Q4.2：默认关闭；开启后仅 risk=low、confidence≥阈值、非 pending_judge，
        且过 QualityGate（注入时）。"""
        return (
            self.policy.auto_apply_enrich
            and risk == "low"
            and prop.confidence >= self.policy.enrich_auto_min_confidence
            and self._gate_ok(prop, risk, "enrich")  # pending/异常 fail-closed 见 _gate_ok
        )

    # -- 冲突裁决序（03 §6.2 逐级短路） -----------------------------------------

    def _adjudicate(
        self, change_set: ChangeSet, prop: ProposedClaim, existing: Claim, report: MergeReport
    ) -> None:
        risk = self.risk_of(prop.predicate)
        new_auth = prop.best_authority
        old_auth = _authority_for_claim(self.session, existing)
        basis: dict[str, Any] = {
            "authority_cmp": f"proposed={new_auth} existing={old_auth}",
            "completeness_cmp": (
                f"proposed_len={len(normalize_value(prop.value))} "
                f"existing_len={len(normalize_value(claim_value_text(existing)))}"
                "（仅排序参考，永不压过①②）"
            ),
        }
        winner: str | None = None
        if new_auth < old_auth:
            winner = "proposed"
            basis["authority_cmp"] += " → proposed 胜（① 高权威直接胜出）"
        elif new_auth > old_auth:
            winner = "existing"
            basis["authority_cmp"] += " → existing 胜（① 低权威新值只进 conflict 记录）"
        else:
            basis["authority_cmp"] += " → 同级，进 ②"
            if (
                prop.effective_from is not None
                and existing.effective_from is not None
                and prop.effective_from != existing.effective_from
            ):
                newer = prop.effective_from > existing.effective_from
                winner = "proposed" if newer else "existing"
                basis["effective_cmp"] = (
                    f"proposed={prop.effective_from} existing={existing.effective_from}"
                    f" → {'proposed' if newer else 'existing'} 胜（② 生效新者胜）"
                )
            else:
                basis["effective_cmp"] = "无法比较（缺可靠 effective_from），进 ④/⑤"

        if winner == "existing":
            item = self._new_item(
                change_set,
                action="conflict",
                claim_id=None,
                proposed={"claim": _prop_dump(prop), "existing_claim_id": existing.id},
                decision="auto_applied",
                basis=basis,
            )
            self._new_conflict(item, existing, prop, basis, status="resolved")
            report.bump("conflict")
            return

        if winner == "proposed":
            claim = _create_claim(self.session, prop, status="candidate")
            item = self._new_item(
                change_set,
                action="supersede",
                claim_id=claim.id,
                proposed={"claim": _prop_dump(prop), "existing_claim_id": existing.id},
                decision="needs_review",
                basis=basis,
            )
            _write_revision(
                self.session, claim, before=None, change_item_id=item.id,
                actor=self.created_by, reason="supersede candidate",
            )
            auto = (
                risk != "high"
                and self.policy.auto_apply_supersede_low_risk
                and self._gate_ok(prop, risk, "supersede")  # pending/异常 fail-closed 见 _gate_ok
            )
            if auto:
                item.decision = "auto_applied"
                self._new_conflict(item, existing, prop, basis, status="resolved")
                publish_claim(
                    self.session, self.scope, claim, change_item_id=item.id,
                    actor=self.created_by,
                    reason="auto supersede（裁决序①/②）", superseding=existing,
                )
            else:
                # 未自动发布的 supersede 进审核：保留**真实 risk**——低风险候选不得被
                # 误标成 high_risk_change（否则污染审核优先级与审计语义，codex #8）。
                conflict = self._new_conflict(item, existing, prop, basis, status="open")
                self._gate(
                    item, prop, risk, report,
                    new_claim_id=claim.id, conflict_id=conflict.id,
                )
            report.bump("supersede")
            return

        # 裁决序①②未分胜负：conflict（冲突未决期间旧 published 不动、新值停 candidate，K3.4）
        claim = _create_claim(self.session, prop, status="candidate")
        item = self._new_item(
            change_set,
            action="conflict",
            claim_id=claim.id,
            proposed={"claim": _prop_dump(prop), "existing_claim_id": existing.id},
            decision="needs_review",
            basis=basis,
        )
        _write_revision(
            self.session, claim, before=None, change_item_id=item.id,
            actor=self.created_by, reason="conflict candidate",
        )
        if risk == "high":
            # 高风险跳过④直接⑤（03 §6.2）
            conflict = self._new_conflict(item, existing, prop, basis, status="open")
            self._gate(
                item, prop, "high", report,
                new_claim_id=claim.id, conflict_id=conflict.id, type_="conflict",
            )
        else:
            conflict = self._new_conflict(item, existing, prop, basis, status="pending_judge")
            self.judge_queue.append(
                ConflictJudgeRequest(
                    conflict_id=conflict.id,
                    product_version_id=prop.product_version_id,
                    predicate=prop.predicate,
                    field_name=prop.field_name,
                    existing={
                        "value": claim_value_text(existing),
                        "value_state": existing.value_state,
                        "evidence": [
                            {"knowledge_id": e.knowledge_id, "page": e.page, "quote": e.quote}
                            for e in _evidence_for_claim(self.session, existing)
                        ],
                    },
                    proposed=_prop_dump(prop),
                )
            )
        report.bump("conflict")

    # -- 内部构件 --------------------------------------------------------------

    def _new_item(
        self,
        change_set: ChangeSet,
        *,
        action: str,
        claim_id: str | None,
        proposed: dict[str, Any],
        decision: str,
        basis: dict[str, Any] | None,
    ) -> ChangeItem:
        item = ChangeItem(
            change_set_id=change_set.id,
            action=action,
            claim_id=claim_id,
            proposed=proposed,
            decision=decision,
            decision_basis=basis,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def _new_conflict(
        self,
        item: ChangeItem,
        existing: Claim,
        prop: ProposedClaim,
        basis: dict[str, Any],
        *,
        status: str,
    ) -> Conflict:
        conflict = Conflict(
            change_item_id=item.id,
            existing_claim_id=existing.id,
            proposed=_prop_dump(prop),
            decision_basis=basis,
            status=status,
        )
        self.session.add(conflict)
        self.session.flush()
        return conflict

    def _gate(
        self,
        item: ChangeItem,
        prop: ProposedClaim,
        risk: str,
        report: MergeReport,
        *,
        new_claim_id: str | None,
        conflict_id: str | None = None,
        type_: str | None = None,
    ) -> None:
        """审核门禁（K4.1）：needs_review 的 ChangeItem 挂稳定 ID ReviewItem。"""
        review_type = type_ or ("high_risk_change" if risk == "high" else "low_confidence")
        key = derive_review_key(
            review_type, prop.product_version_id, prop.predicate, prop.value_hash
        )
        _, created = ensure_review_item(
            self.session,
            scope=self.scope,
            review_key=key,
            type_=review_type,
            subject={
                "change_item_id": item.id,
                "new_claim_id": new_claim_id,
                "conflict_id": conflict_id,
                "predicate": prop.predicate,
            },
            risk_level=risk,
        )
        if key not in report.review_keys:
            report.review_keys.append(key)


def _prop_dump(prop: ProposedClaim) -> dict[str, Any]:
    return prop.model_dump(mode="json")


def _existing_value_hash(claim: Claim) -> str:
    from insurance_harness.knowledge.models import value_hash

    return value_hash(claim.value_state, claim_value_text(claim))


# ------------------------------------------------------------------ 应用与审核动作


def _apply_enrich_append(
    session: Session,
    scope: KnowledgeScope,
    item: ChangeItem,
    *,
    actor: str,
) -> None:
    if item.claim_id is None:
        raise _scope_mismatch()
    claim = _require_scoped_claim(session, scope, item.claim_id)
    before = _snapshot(claim)
    for e in item.proposed.get("evidence", []):
        parsed = ProposedEvidence.model_validate(e)
        session.add(
            ClaimEvidence(
                claim_id=claim.id,
                knowledge_id=parsed.knowledge_id,
                raw_kb_id=parsed.raw_kb_id,
                source_revision=parsed.source_revision,
                file_hash=parsed.file_hash,
                original_digest=parsed.original_digest,
                parser_version=parsed.parser_version,
                chunk_id=parsed.chunk_id,
                chunk_hash=parsed.chunk_hash,
                lineage_status=parsed.lineage_status,
                stale_at=parsed.stale_at,
                quote=parsed.quote,
                page=parsed.page,
                authority_level=parsed.authority_level,
                doc_role=parsed.doc_role,
                extraction_method=parsed.extraction_method,
            )
        )
    claim.confidence = float(item.proposed.get("confidence", claim.confidence))
    _write_revision(
        session, claim, before=before, change_item_id=item.id,
        actor=actor, reason="enrich append evidence",
    )


def apply_change_item(
    session: Session,
    scope: KnowledgeScope,
    item: ChangeItem,
    *,
    actor: str,
    decision: str = "approved",
    reason: str | None = None,
    llm_verdict: str | None = None,
) -> None:
    """采纳一个 needs_review/pending 的 ChangeItem（approve 或 ④ 裁决回写）。"""
    require_current_scope(session, scope)
    item, claim, old, conflicts = _require_scoped_item_aggregate(session, scope, item)
    if item.action == "enrich" and item.proposed.get("mode") == "append_evidence":
        _apply_enrich_append(session, scope, item, actor=actor)
    else:
        if claim is None:
            raise _scope_mismatch()
        publish_claim(
            session,
            scope,
            claim,
            change_item_id=item.id,
            actor=actor,
            reason=reason,
            superseding=old,
        )
    item.decision = decision
    basis = dict(item.decision_basis or {})
    if llm_verdict is not None:
        basis["llm_verdict"] = llm_verdict
    if decision == "approved":
        basis["reviewer"] = actor
    item.decision_basis = basis
    _resolve_conflicts(conflicts, basis)
    session.flush()


def reject_change_item(
    session: Session,
    scope: KnowledgeScope,
    item: ChangeItem,
    *,
    actor: str,
    reason: str | None = None,
    llm_verdict: str | None = None,
) -> None:
    """驳回：候选 Claim → retracted，旧值保持 published（K4.2）。"""
    require_current_scope(session, scope)
    item, claim, _, conflicts = _require_scoped_item_aggregate(session, scope, item)
    if claim is not None and claim.status in ("candidate", "draft"):
        _retract_claim(
            session, claim, change_item_id=item.id, actor=actor, reason=reason or "rejected"
        )
    item.decision = "rejected"
    basis = dict(item.decision_basis or {})
    basis["reviewer"] = actor
    if llm_verdict is not None:
        basis["llm_verdict"] = llm_verdict
    if reason:
        basis["review_reason"] = reason
    item.decision_basis = basis
    _resolve_conflicts(conflicts, basis)
    session.flush()


def _resolve_conflicts(
    conflicts: tuple[Conflict, ...], basis: dict[str, Any]
) -> None:
    for conflict in conflicts:
        conflict.status = "resolved"
        conflict.decision_basis = basis


def resolve_review(
    session: Session,
    scope: KnowledgeScope,
    review_key: str,
    action: str,
    *,
    actor: str,
    reason: str | None = None,
) -> ReviewItem:
    """受限动作集 approve/reject/defer（K4.2）；已决项翻案走 overturn_review。"""
    require_current_scope(session, scope)
    item = session.execute(
        select(ReviewItem).where(
            ReviewItem.space_id == scope.space_id,
            ReviewItem.review_key == review_key,
        )
    ).scalar_one_or_none()
    if item is None:
        raise _scope_mismatch()
    subject = _require_scoped_review_subject(session, scope, item.subject)
    if action not in item.allowed_actions:
        raise ValueError(f"动作 {action!r} 不在受限动作集 {item.allowed_actions} 中")
    if item.status != "open":
        raise ValueError(
            f"review item {review_key} 已决（{item.status}）；翻案请走 overturn_review"
        )
    if action == "defer":
        return item  # 保持 open，不落 resolution
    if not subject.change_item_id:
        raise _scope_mismatch()
    change_item = _require_scoped_change_item(session, scope, subject.change_item_id)
    if action == "approve":
        apply_change_item(
            session,
            scope,
            change_item,
            actor=actor,
            decision="approved",
            reason=reason,
        )
    else:
        reject_change_item(session, scope, change_item, actor=actor, reason=reason)
    item.status = "resolved"
    item.resolution = {
        "action": action,
        "actor": actor,
        "reason": reason,
        "at": utcnow().isoformat(),
    }
    session.flush()
    return item


def overturn_review(
    session: Session,
    scope: KnowledgeScope,
    review_key: str,
    new_action: str,
    *,
    actor: str,
    reason: str,
) -> ChangeSet:
    """翻案 = 新 ChangeSet（K3.5）：原 ChangeSet 与原 decision_basis 不改写。"""
    require_current_scope(session, scope)
    item = session.execute(
        select(ReviewItem).where(
            ReviewItem.space_id == scope.space_id,
            ReviewItem.review_key == review_key,
        )
    ).scalar_one_or_none()
    if item is None:
        raise _scope_mismatch()
    subject = _require_scoped_review_subject(session, scope, item.subject)
    if item.status != "resolved" or item.resolution is None:
        raise ValueError(f"review item {review_key} 不是已决项，不能翻案")
    prev = str(item.resolution["action"])
    if new_action == prev or new_action not in ("approve", "reject"):
        raise ValueError(f"翻案动作 {new_action!r} 无效（原决定 {prev!r}）")
    original, adopted, old, _ = _require_scoped_item_aggregate(
        session,
        scope,
        subject.change_item_id or "",
    )
    if new_action == "reject" and adopted is None:
        raise _scope_mismatch()
    change_set = ChangeSet(
        space_id=scope.space_id,
        source_kind="manual_edit",
        knowledge_ids=None,
        status="applied",
        created_by=actor,
    )
    session.add(change_set)
    session.flush()
    if new_action == "reject":
        # 撤销先前采纳：新 Claim 撤回，被取代的旧 Claim 恢复 published
        assert adopted is not None
        reversal = ChangeItem(
            change_set_id=change_set.id,
            action="retract",
            claim_id=adopted.id,
            proposed={"overturn_of": original.id},
            decision="approved",
            decision_basis={"reviewer": actor, "review_reason": reason},
        )
        session.add(reversal)
        session.flush()
        _retract_claim(
            session, adopted, change_item_id=reversal.id, actor=actor, reason=reason
        )
        if old is not None and old.status == "superseded":
            before = _snapshot(old)
            old.status = "published"
            old.superseded_by = None
            _write_revision(
                session, old, before=before, change_item_id=reversal.id,
                actor=actor, reason=f"翻案恢复：{reason}",
            )
    else:
        # 撤销先前驳回：按原提案重新应用
        reversal = ChangeItem(
            change_set_id=change_set.id,
            action=original.action,
            claim_id=original.claim_id,
            proposed=dict(original.proposed),
            decision="needs_review",
            decision_basis={"overturn_of": original.id},
        )
        session.add(reversal)
        session.flush()
        if adopted is not None:
            if adopted.status == "retracted":
                before = _snapshot(adopted)
                adopted.status = "candidate"
                _write_revision(
                    session, adopted, before=before, change_item_id=reversal.id,
                    actor=actor, reason=f"翻案恢复候选：{reason}",
                )
        apply_change_item(
            session,
            scope,
            reversal,
            actor=actor,
            decision="approved",
            reason=reason,
        )
    item.resolution = {
        "action": new_action,
        "actor": actor,
        "reason": reason,
        "overturned_from": prev,
        "at": utcnow().isoformat(),
    }
    session.flush()
    return change_set


# ------------------------------------------------------------------ ④ claude-session 队列


def write_conflict_judge_queue(path: Path, queue: list[ConflictJudgeRequest]) -> None:
    """judge-queue.jsonl 形态落盘（复用 compiler judge-queue 的行式 JSONL 约定）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(r.model_dump_json() + "\n" for r in queue), encoding="utf-8")


def read_conflict_judgements(path: Path) -> list[ConflictJudgement]:
    return [
        ConflictJudgement.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def apply_conflict_judgements(
    session: Session,
    scope: KnowledgeScope,
    judgements: list[ConflictJudgement],
    *,
    actor: str = "claude-session",
) -> int:
    """④ 裁决回写：按 llm_verdict 裁决并留痕（K3.2）；只处理 pending_judge 的冲突。"""
    require_current_scope(session, scope)
    prepared: list[tuple[ConflictJudgement, Conflict, ChangeItem]] = []
    seen_conflicts: set[str] = set()
    seen_items: set[str] = set()
    publication_targets: set[tuple[str | None, str]] = set()
    for judgement in judgements:
        if judgement.conflict_id in seen_conflicts:
            raise _scope_mismatch()
        seen_conflicts.add(judgement.conflict_id)
        conflict, item, claim, old = _require_scoped_conflict_aggregate(
            session, scope, judgement.conflict_id
        )
        if conflict.status != "pending_judge":
            continue
        if item.id in seen_items:
            raise _scope_mismatch()
        seen_items.add(item.id)
        if judgement.winner == "proposed":
            if claim is None:
                raise _scope_mismatch()
            _require_publish_context(
                session,
                scope,
                claim,
                change_item_id=item.id,
                superseding=old,
            )
            target = (claim.product_version_id, claim.predicate)
            if target in publication_targets:
                raise _scope_mismatch()
            publication_targets.add(target)
        prepared.append((judgement, conflict, item))

    for judgement, _, item in prepared:
        if judgement.winner == "proposed":
            apply_change_item(
                session, scope, item, actor=actor, decision="auto_applied",
                reason="④ LLM 裁决（claude-session 回写）", llm_verdict=judgement.reasoning,
            )
        else:
            reject_change_item(
                session, scope, item, actor=actor,
                reason="④ LLM 裁决（claude-session 回写）", llm_verdict=judgement.reasoning,
            )
    return len(prepared)


# ------------------------------------------------------------------ retract（来源删除）


_LEGACY_RETRACT_EVENT = "legacy-replay"
_SOURCE_REVISION_HEX = re.compile(r"^[0-9a-f]{64}$")


def _prepare_retract_source(
    source: SourceImportIdentity | str,
    scope: KnowledgeScope,
    *,
    legacy_replay: bool,
) -> tuple[str, str, str, bool]:
    """Validate a retract identity before any database access."""
    if isinstance(source, SourceImportIdentity):
        if legacy_replay:
            raise _scope_mismatch()
        try:
            identity = SourceImportIdentity.model_validate(
                source.model_dump(mode="python")
            )
        except (AttributeError, TypeError, ValueError, ValidationError) as exc:
            raise _scope_mismatch() from exc
        if identity.raw_kb_id != scope.raw_kb_id:
            raise _scope_mismatch()
        knowledge_id = identity.knowledge_id
        event_revision = identity.source_revision
        external_record_id = knowledge_id
        source_aware = True
    elif isinstance(source, str) and legacy_replay:
        knowledge_id = source.strip()
        if not knowledge_id:
            raise _scope_mismatch()
        event_revision = _LEGACY_RETRACT_EVENT
        external_record_id = "legacy:" + hashlib.sha256(
            knowledge_id.encode("utf-8")
        ).hexdigest()[:57]
        source_aware = False
    else:
        raise _scope_mismatch()
    return (
        knowledge_id,
        external_record_id,
        derive_retract_event_key(knowledge_id, event_revision),
        source_aware,
    )


def _legacy_retract_has_source_aware_state(
    session: Session,
    scope: KnowledgeScope,
    *,
    knowledge_id: str,
) -> bool:
    evidence_id = session.scalar(
        select(ClaimEvidence.id)
        .join(Claim, Claim.id == ClaimEvidence.claim_id)
        .where(
            Claim.space_id == scope.space_id,
            ClaimEvidence.knowledge_id == knowledge_id,
            ClaimEvidence.lineage_status.is_not(None),
        )
        .limit(1)
    )
    if evidence_id is not None:
        return True
    source_revisions = session.scalars(
        select(ChangeSet.source_revision).where(
            ChangeSet.space_id == scope.space_id,
            ChangeSet.source_kind.in_(("document", "recompile")),
            ChangeSet.external_record_id == knowledge_id,
            ChangeSet.source_revision.is_not(None),
        )
    )
    return any(
        _SOURCE_REVISION_HEX.fullmatch(revision or "") is not None
        for revision in source_revisions
    )


def _retract_replay_report(
    session: Session,
    scope: KnowledgeScope,
    change_set: ChangeSet,
    *,
    knowledge_id: str,
) -> MergeReport:
    item_count = validate_retract_tombstone(
        session,
        scope,
        change_set,
        knowledge_id=knowledge_id,
    )
    return MergeReport(
        change_set_id=change_set.id,
        actions={"retract": item_count} if item_count else {},
    )


def _existing_retract_change_set(
    session: Session,
    scope: KnowledgeScope,
    *,
    external_record_id: str,
    source_revision: str,
) -> ChangeSet | None:
    return session.scalar(
        select(ChangeSet).where(
            ChangeSet.space_id == scope.space_id,
            ChangeSet.source_kind == "document",
            ChangeSet.external_record_id == external_record_id,
            ChangeSet.source_revision == source_revision,
        )
    )


def _insert_retract_change_set(
    session: Session,
    scope: KnowledgeScope,
    *,
    knowledge_id: str,
    external_record_id: str,
    source_revision: str,
    created_by: str,
) -> tuple[ChangeSet, bool]:
    candidate = ChangeSet(
        space_id=scope.space_id,
        source_kind="document",
        knowledge_ids=[knowledge_id],
        external_record_id=external_record_id,
        source_revision=source_revision,
        status="applied",
        created_by=created_by,
    )
    try:
        with session.begin_nested():
            session.add(candidate)
            session.flush()
    except IntegrityError:
        winner = _existing_retract_change_set(
            session,
            scope,
            external_record_id=external_record_id,
            source_revision=source_revision,
        )
        if winner is None:
            raise
        return winner, False
    return candidate, True


def retract_source(
    session: Session,
    scope: KnowledgeScope,
    source: SourceImportIdentity | str,
    *,
    legacy_replay: bool = False,
    created_by: str = "retractor",
) -> MergeReport:
    """Delete one scoped source with an exact-event idempotency record."""
    (
        knowledge_id,
        external_record_id,
        source_revision,
        source_aware,
    ) = _prepare_retract_source(source, scope, legacy_replay=legacy_replay)
    require_current_scope(session, scope)
    with session.begin_nested():
        if not source_aware and _legacy_retract_has_source_aware_state(
            session,
            scope,
            knowledge_id=knowledge_id,
        ):
            raise ScopeViolation("source mode conflict")
        existing = _existing_retract_change_set(
            session,
            scope,
            external_record_id=external_record_id,
            source_revision=source_revision,
        )
        if existing is not None:
            return _retract_replay_report(
                session,
                scope,
                existing,
                knowledge_id=knowledge_id,
            )
        evidence = list(
            session.scalars(
                select(ClaimEvidence)
                .join(Claim, Claim.id == ClaimEvidence.claim_id)
                .where(
                    ClaimEvidence.knowledge_id == knowledge_id,
                    Claim.space_id == scope.space_id,
                    *(
                        ()
                        if source_aware
                        else (ClaimEvidence.lineage_status.is_(None),)
                    ),
                )
            )
        )
        change_set, created = _insert_retract_change_set(
            session,
            scope,
            knowledge_id=knowledge_id,
            external_record_id=external_record_id,
            source_revision=source_revision,
            created_by=created_by,
        )
        if not created:
            return _retract_replay_report(
                session,
                scope,
                change_set,
                knowledge_id=knowledge_id,
            )
        report = MergeReport(change_set_id=change_set.id)
        if not evidence:
            return report
        by_claim: dict[str, list[ClaimEvidence]] = {}
        for row in evidence:
            by_claim.setdefault(row.claim_id, []).append(row)
        for claim_id, rows in by_claim.items():
            claim = _require_scoped_claim(session, scope, claim_id)
            removed_ids = {row.id for row in rows}
            remaining_active = [
                row
                for row in _evidence_for_claim(session, claim)
                if row.id not in removed_ids and row.stale_at is None
            ]
            for row in rows:
                session.delete(row)
            item = ChangeItem(
                change_set_id=change_set.id,
                action="retract",
                claim_id=claim_id,
                proposed={
                    "knowledge_id": knowledge_id,
                    "removed_evidence": len(rows),
                },
                decision="auto_applied",
                decision_basis={
                    "note": f"来源删除；剩余 active 证据 {len(remaining_active)} 条"
                    + (
                        "→ Claim retracted"
                        if not remaining_active
                        else "，Claim 保留"
                    )
                },
            )
            session.add(item)
            session.flush()
            if not remaining_active and claim.status in (
                "published",
                "candidate",
                "draft",
            ):
                _retract_claim(
                    session,
                    claim,
                    change_item_id=item.id,
                    actor=created_by,
                    reason=f"来源 {knowledge_id} 删除后 active 证据清零",
                )
            report.bump("retract")
        session.flush()
        return report
