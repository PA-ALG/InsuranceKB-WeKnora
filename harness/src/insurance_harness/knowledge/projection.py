"""知识域只读投影（008 阻断 1 修复）：工作台/导出消费的唯一 DTO 入口。

`ChangeItem.proposed` 的真实持久化形态由 MergeEngine 决定（K3）：

- add:                      ``{"claim": <ProposedClaim>}``（unknown 占位再加 ``mode``）
- enrich fill_unknown:      ``{"claim": …, "mode": "fill_unknown", "placeholder_claim_id": …}``
- enrich append_evidence:   ``{"mode": "append_evidence", "evidence": […], "confidence": …}``
- supersede / conflict:     ``{"claim": …, "existing_claim_id": …}``
- retract（来源删除）:       ``{"knowledge_id": …, "removed_evidence": n}``
- 翻案 reversal:            额外携带 ``overturn_mode`` / ``overturn_of``

任何页面/导出**不得**自行读取 ``proposed`` 内部形态——一律经本模块投影
（读取合同一处收口；形态演进只改这里）。本模块零写入（W5.1 语义同 workbench 查询）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.models import InsuranceProduct, ProductVersion
from insurance_harness.db.scope import KnowledgeScope, require_current_scope
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    ClaimEvidence,
    ClaimRevision,
    Conflict,
    ReviewItem,
)


class EvidenceView(BaseModel):
    """证据对照行（W1：引文+页码+来源文档+权威等级）。"""

    model_config = ConfigDict(frozen=True)

    knowledge_id: str
    quote: str
    page: int | None = None
    doc_role: str = ""
    authority_level: int | None = None


class RevisionView(BaseModel):
    model_config = ConfigDict(frozen=True)

    at: str
    actor: str
    after_value: str
    reason: str | None = None


class ClaimSideView(BaseModel):
    """冲突/对照的一侧：值 + 状态 + 证据。"""

    model_config = ConfigDict(frozen=True)

    claim_id: str | None = None
    predicate: str | None = None
    value: str | None = None
    value_state: str | None = None
    status: str | None = None
    confidence: float | None = None
    evidence: tuple[EvidenceView, ...] = ()


class GateView(BaseModel):
    """W7：QualityGate 拒绝原因 + 画像/基线标识文本。"""

    model_config = ConfigDict(frozen=True)

    reason: str
    field_id: str | None = None
    action: str | None = None
    profile_version: str | None = None
    profile_content_sha256: str | None = None
    artifact_sha256: str | None = None
    baseline_id: str | None = None
    approval_sha256: str | None = None


class ConflictView(BaseModel):
    model_config = ConfigDict(frozen=True)

    conflict_id: str
    status: str
    existing: ClaimSideView | None = None
    proposed: ClaimSideView | None = None
    decision_basis: dict[str, Any] = Field(default_factory=dict)


class ChangeItemProjection(BaseModel):
    """一条 ChangeItem 的展示投影：predicate/值/证据/冲突/gate 全解析。"""

    model_config = ConfigDict(frozen=True)

    change_item_id: str
    change_set_id: str
    action: str
    mode: str | None = None
    overturn_mode: str | None = None
    overturn_of: str | None = None
    decision: str
    predicate: str | None = None
    product_version_id: str | None = None
    proposed_value: str | None = None
    value_state: str | None = None
    candidate: ClaimSideView | None = None
    existing: ClaimSideView | None = None
    appended_evidence: tuple[EvidenceView, ...] = ()
    confidence: float | None = None
    conflict: ConflictView | None = None
    gate: GateView | None = None
    decision_basis: dict[str, Any] = Field(default_factory=dict)


class ReviewHistoryEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: str
    actor: str
    at: str
    reason: str | None = None
    request_id: str | None = None


class ReviewAggregate(BaseModel):
    """一条审核项的完整审阅上下文（W1 单条详情）。"""

    model_config = ConfigDict(frozen=True)

    review_key: str
    type: str
    risk_level: str
    status: str
    version_token: str  # 乐观并发版本（updated_at isoformat）
    trigger_count: int = 0
    last_triggered_at: str | None = None
    predicate: str | None = None
    product_version_id: str | None = None
    product_code: str | None = None
    product_name: str | None = None
    version_label: str | None = None
    change_set_id: str | None = None
    change_item: ChangeItemProjection | None = None
    gate: GateView | None = None
    allowed_actions: tuple[str, ...] = ()
    resolution_action: str | None = None
    history: tuple[ReviewHistoryEvent, ...] = ()
    overturn_of_review: str | None = None
    prev_action: str | None = None
    requested_action: str | None = None
    overturn_reason: str | None = None


def _value_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        text = value.get("text")
        return None if text is None else str(text)
    return str(value)


def _evidence_from_rows(rows: list[ClaimEvidence]) -> tuple[EvidenceView, ...]:
    return tuple(
        EvidenceView(
            knowledge_id=e.knowledge_id,
            quote=e.quote,
            page=e.page,
            doc_role=e.doc_role,
            authority_level=e.authority_level,
        )
        for e in rows
    )


def _evidence_from_dicts(rows: Any) -> tuple[EvidenceView, ...]:
    if not isinstance(rows, list):
        return ()
    out: list[EvidenceView] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            EvidenceView(
                knowledge_id=str(row.get("knowledge_id") or ""),
                quote=str(row.get("quote") or ""),
                page=row.get("page"),
                doc_role=str(row.get("doc_role") or ""),
                authority_level=row.get("authority_level"),
            )
        )
    return tuple(out)


def _claim_rows(session: Session, scope: KnowledgeScope, claim_id: str) -> Claim | None:
    claim = session.get(Claim, claim_id)
    if claim is None or claim.space_id != scope.space_id:
        return None
    return claim


def _claim_side(
    session: Session, scope: KnowledgeScope, claim_id: str | None
) -> ClaimSideView | None:
    if not claim_id:
        return None
    claim = _claim_rows(session, scope, str(claim_id))
    if claim is None:
        return None
    evidence = list(
        session.execute(
            select(ClaimEvidence).where(ClaimEvidence.claim_id == claim.id)
        ).scalars()
    )
    return ClaimSideView(
        claim_id=claim.id,
        predicate=claim.predicate,
        value=_value_text(claim.value),
        value_state=claim.value_state,
        status=claim.status,
        confidence=claim.confidence,
        evidence=_evidence_from_rows(evidence),
    )


def claim_side(
    session: Session, scope: KnowledgeScope, claim_id: str | None
) -> ClaimSideView | None:
    """公开入口：一条 Claim 的展示侧（值+状态+证据）；跨 space/不存在 → None。"""
    return _claim_side(session, scope, claim_id)


def _proposal_side(proposed: dict[str, Any]) -> ClaimSideView:
    """扁平 ProposedClaim dump（Conflict.proposed / proposed["claim"]）→ 展示侧。"""
    return ClaimSideView(
        predicate=(
            str(proposed["predicate"]) if proposed.get("predicate") is not None else None
        ),
        value=_value_text(proposed.get("value")),
        value_state=(
            str(proposed["value_state"])
            if proposed.get("value_state") is not None
            else None
        ),
        confidence=proposed.get("confidence"),
        evidence=_evidence_from_dicts(proposed.get("evidence")),
    )


def gate_view_from_payload(payload: Any) -> GateView | None:
    if not isinstance(payload, dict) or not payload.get("reason"):
        return None
    return GateView(
        reason=str(payload["reason"]),
        field_id=payload.get("field_id"),
        action=payload.get("action"),
        profile_version=payload.get("profile_version"),
        profile_content_sha256=payload.get("profile_content_sha256"),
        artifact_sha256=payload.get("artifact_sha256"),
        baseline_id=payload.get("baseline_id"),
        approval_sha256=payload.get("approval_sha256"),
    )


def _conflict_view(
    session: Session, scope: KnowledgeScope, conflict: Conflict
) -> ConflictView:
    existing = _claim_side(session, scope, conflict.existing_claim_id)
    proposed_raw = conflict.proposed or {}
    return ConflictView(
        conflict_id=conflict.id,
        status=conflict.status,
        existing=existing,
        proposed=_proposal_side(proposed_raw) if proposed_raw else None,
        decision_basis=dict(conflict.decision_basis or {}),
    )


def project_change_item(
    session: Session, scope: KnowledgeScope, item: ChangeItem
) -> ChangeItemProjection:
    """按 action/mode 解析一条 ChangeItem（唯一读取合同入口）。

    解析优先级：``proposed["claim"]``（提案原文）→ 持久化 Claim 行（claim_id /
    existing/placeholder id）→ 顶层扁平键（历史/降级容错）。
    """
    proposed: dict[str, Any] = dict(item.proposed or {})
    mode = proposed.get("mode")
    claim_payload = proposed.get("claim")
    claim_dict = claim_payload if isinstance(claim_payload, dict) else None

    candidate = _claim_side(session, scope, item.claim_id)
    existing_id = proposed.get("existing_claim_id") or proposed.get(
        "placeholder_claim_id"
    )
    existing = _claim_side(
        session, scope, str(existing_id) if existing_id else None
    )
    if mode == "append_evidence":
        # 目标 = 既有 Claim（claim_id 指向它），追加证据在 proposed["evidence"]
        existing = existing or candidate
        candidate = None

    predicate: str | None = None
    product_version_id: str | None = None
    proposed_value: str | None = None
    value_state: str | None = None
    if claim_dict is not None:
        predicate = (
            str(claim_dict["predicate"])
            if claim_dict.get("predicate") is not None
            else None
        )
        pv = claim_dict.get("product_version_id")
        product_version_id = str(pv) if pv else None
        proposed_value = _value_text(claim_dict.get("value"))
        vs = claim_dict.get("value_state")
        value_state = str(vs) if vs is not None else None
    for side in (candidate, existing):
        if side is None:
            continue
        predicate = predicate or side.predicate
        proposed_value = proposed_value if proposed_value is not None else side.value
        value_state = value_state or side.value_state
    if product_version_id is None:
        for cid in (item.claim_id, existing_id):
            if not cid:
                continue
            row = _claim_rows(session, scope, str(cid))
            if row is not None and row.product_version_id:
                product_version_id = row.product_version_id
                break
    # 顶层扁平键降级容错（旧数据/外部写入），绝不作为主形态
    if predicate is None and proposed.get("predicate") is not None:
        predicate = str(proposed["predicate"])
    if product_version_id is None and proposed.get("product_version_id"):
        product_version_id = str(proposed["product_version_id"])
    if proposed_value is None and "value" in proposed and claim_dict is None:
        proposed_value = _value_text(proposed.get("value"))

    conflict_row = session.execute(
        select(Conflict)
        .join(ChangeItem, ChangeItem.id == Conflict.change_item_id)
        .join(ChangeSet, ChangeSet.id == ChangeItem.change_set_id)
        .where(
            Conflict.change_item_id == item.id,
            ChangeSet.space_id == scope.space_id,
        )
    ).scalars().first()

    basis = dict(item.decision_basis or {})
    return ChangeItemProjection(
        change_item_id=item.id,
        change_set_id=item.change_set_id,
        action=item.action,
        mode=str(mode) if mode is not None else None,
        overturn_mode=(
            str(proposed["overturn_mode"])
            if proposed.get("overturn_mode") is not None
            else None
        ),
        overturn_of=(
            str(proposed["overturn_of"])
            if proposed.get("overturn_of") is not None
            else None
        ),
        decision=item.decision,
        predicate=predicate,
        product_version_id=product_version_id,
        proposed_value=proposed_value,
        value_state=value_state,
        candidate=candidate,
        existing=existing,
        appended_evidence=(
            _evidence_from_dicts(proposed.get("evidence"))
            if mode == "append_evidence"
            else ()
        ),
        confidence=(
            float(proposed["confidence"])
            if isinstance(proposed.get("confidence"), int | float)
            else None
        ),
        conflict=(
            _conflict_view(session, scope, conflict_row)
            if conflict_row is not None
            else None
        ),
        gate=gate_view_from_payload(basis.get("gate")),
        decision_basis=basis,
    )


def _history_events(resolution: dict[str, Any] | None) -> tuple[ReviewHistoryEvent, ...]:
    if not resolution:
        return ()
    events = resolution.get("events")
    rows: list[dict[str, Any]]
    if isinstance(events, list) and events:
        rows = [e for e in events if isinstance(e, dict)]
    elif resolution.get("action"):
        rows = [resolution]  # 旧格式（单记录）兼容
    else:
        return ()
    return tuple(
        ReviewHistoryEvent(
            action=str(e.get("action") or ""),
            actor=str(e.get("actor") or ""),
            at=str(e.get("at") or ""),
            reason=e.get("reason"),
            request_id=e.get("request_id"),
        )
        for e in rows
    )


def load_review_aggregate(
    session: Session, scope: KnowledgeScope, item: ReviewItem
) -> ReviewAggregate:
    """一条 ReviewItem 的完整审阅上下文（W1 单条详情的数据源）。"""
    require_current_scope(session, scope)
    subject = dict(item.subject or {})
    change_item_id = subject.get("change_item_id")
    projection: ChangeItemProjection | None = None
    if change_item_id:
        change_item = session.execute(
            select(ChangeItem)
            .join(ChangeSet, ChangeSet.id == ChangeItem.change_set_id)
            .where(
                ChangeItem.id == str(change_item_id),
                ChangeSet.space_id == scope.space_id,
            )
        ).scalar_one_or_none()
        if change_item is not None:
            projection = project_change_item(session, scope, change_item)
    predicate = subject.get("predicate") or (
        projection.predicate if projection is not None else None
    )
    product_version_id = (
        projection.product_version_id if projection is not None else None
    )
    product_code: str | None = None
    product_name: str | None = None
    version_label: str | None = None
    if product_version_id:
        row = session.execute(
            select(ProductVersion, InsuranceProduct)
            .join(InsuranceProduct, ProductVersion.product_id == InsuranceProduct.id)
            .where(
                ProductVersion.id == product_version_id,
                ProductVersion.space_id == scope.space_id,
            )
        ).first()
        if row is not None:
            version, product = row
            product_code = product.product_code
            product_name = product.canonical_name
            version_label = version.version_label
    trigger = subject.get("trigger") or {}
    resolution = dict(item.resolution or {})
    return ReviewAggregate(
        review_key=item.review_key,
        type=item.type,
        risk_level=item.risk_level,
        status=item.status,
        version_token=item.updated_at.isoformat(),
        trigger_count=int(trigger.get("count") or 0),
        last_triggered_at=trigger.get("last_at"),
        predicate=str(predicate) if predicate is not None else None,
        product_version_id=product_version_id,
        product_code=product_code,
        product_name=product_name,
        version_label=version_label,
        change_set_id=(
            projection.change_set_id if projection is not None else None
        ),
        change_item=projection,
        gate=gate_view_from_payload(subject.get("gate")),
        allowed_actions=tuple(item.allowed_actions or ()),
        resolution_action=(
            str(resolution["action"]) if resolution.get("action") else None
        ),
        history=_history_events(resolution),
        overturn_of_review=subject.get("overturn_of_review"),
        prev_action=subject.get("prev_action"),
        requested_action=subject.get("requested_action"),
        overturn_reason=subject.get("overturn_reason"),
    )


def claim_revisions(
    session: Session, scope: KnowledgeScope, claim_id: str
) -> tuple[RevisionView, ...]:
    """一条 Claim 的修订历史投影（下钻/时间线复用）。"""
    require_current_scope(session, scope)
    claim = _claim_rows(session, scope, claim_id)
    if claim is None:
        return ()
    return tuple(
        RevisionView(
            at=r.at.isoformat(),
            actor=r.actor,
            after_value=_value_text((r.after or {}).get("value")) or "",
            reason=r.reason,
        )
        for r in session.execute(
            select(ClaimRevision)
            .where(ClaimRevision.claim_id == claim.id)
            .order_by(ClaimRevision.revision_no.desc())
        ).scalars()
    )
