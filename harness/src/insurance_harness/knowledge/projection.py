"""知识域只读投影（008 阻断 1 修复；codex R2-P1 批量化 + R2-P2 边界强制）。

`ChangeItem.proposed` 的真实持久化形态由 MergeEngine 决定（K3）：

- add:                      ``{"claim": <ProposedClaim>}``（unknown 占位再加 ``mode``）
- enrich fill_unknown:      ``{"claim": …, "mode": "fill_unknown", "placeholder_claim_id": …}``
- enrich append_evidence:   ``{"mode": "append_evidence", "evidence": […], "confidence": …}``
- supersede / conflict:     ``{"claim": …, "existing_claim_id": …}``
- retract（来源删除）:       ``{"knowledge_id": …, "removed_evidence": n}``
- 翻案 reversal:            额外携带 ``overturn_mode`` / ``overturn_of``

任何页面/导出**不得**自行读取 ``proposed`` 内部形态——一律经本模块投影
（读取合同一处收口；形态演进只改这里）。本模块零写入（W5.1 语义同 workbench 查询）。

成本模型（codex R2-P1）：批量入口 ``load_review_aggregates`` 用一次 ``_Prefetch``
（5 条 IN 查询）投影任意多条 ReviewItem——查询量与条数无关；单条入口复用同一
代码路径（1 条的批）。边界（codex R2-P2）：公共入口对**传入的 ORM 对象本身**
校验归属 scope，不匹配抛 ``ScopeViolation``，绝不返回 foreign DTO。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.models import InsuranceProduct, ProductVersion
from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
    require_current_scope,
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


def _evidence_from_rows(rows: Sequence[ClaimEvidence]) -> tuple[EvidenceView, ...]:
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


# ------------------------------------------------------------------ 批量预取


def _claim_refs_of(proposed: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in (
        "existing_claim_id",
        "placeholder_claim_id",
        "adopted_claim_id",
        "restore_claim_id",
    ):
        value = proposed.get(key)
        if value:
            refs.append(str(value))
    return refs


class _Prefetch:
    """一批投影所需的全部行（固定 5 条 IN 查询，与条数无关——codex R2-P1）。

    所有行都经 space 过滤载入：不在字典里 = 不在本 scope（fail-closed）。
    """

    def __init__(self) -> None:
        self.change_items: dict[str, ChangeItem] = {}
        self.conflicts_by_item: dict[str, Conflict] = {}
        self.claims: dict[str, Claim] = {}
        self.evidence_by_claim: dict[str, list[ClaimEvidence]] = {}
        self.products_by_version: dict[str, tuple[str, str, str]] = {}


def _build_prefetch(
    session: Session,
    scope: KnowledgeScope,
    *,
    review_items: Sequence[ReviewItem] = (),
    change_items: Sequence[ChangeItem] = (),
) -> _Prefetch:
    pf = _Prefetch()
    change_item_ids: set[str] = set()
    version_ids: set[str] = set()
    for item in review_items:
        subject = item.subject or {}
        cid = subject.get("change_item_id")
        if cid:
            change_item_ids.add(str(cid))
        pv = subject.get("product_version_id")
        if pv:
            version_ids.add(str(pv))
    change_item_ids.update(str(ci.id) for ci in change_items)

    if change_item_ids:
        for row in session.execute(
            select(ChangeItem)
            .join(ChangeSet, ChangeSet.id == ChangeItem.change_set_id)
            .where(
                ChangeItem.id.in_(change_item_ids),
                ChangeSet.space_id == scope.space_id,
            )
        ).scalars():
            pf.change_items[row.id] = row
        for conflict in session.execute(
            select(Conflict)
            .join(ChangeItem, ChangeItem.id == Conflict.change_item_id)
            .join(ChangeSet, ChangeSet.id == ChangeItem.change_set_id)
            .where(
                Conflict.change_item_id.in_(change_item_ids),
                ChangeSet.space_id == scope.space_id,
            )
        ).scalars():
            pf.conflicts_by_item.setdefault(conflict.change_item_id, conflict)

    claim_ids: set[str] = set()
    for ci in pf.change_items.values():
        proposed = dict(ci.proposed or {})
        if ci.claim_id:
            claim_ids.add(str(ci.claim_id))
        claim_ids.update(_claim_refs_of(proposed))
        payload = proposed.get("claim")
        if isinstance(payload, dict) and payload.get("product_version_id"):
            version_ids.add(str(payload["product_version_id"]))
    for conflict in pf.conflicts_by_item.values():
        if conflict.existing_claim_id:
            claim_ids.add(str(conflict.existing_claim_id))

    if claim_ids:
        for claim in session.execute(
            select(Claim).where(
                Claim.id.in_(claim_ids), Claim.space_id == scope.space_id
            )
        ).scalars():
            pf.claims[claim.id] = claim
            if claim.product_version_id:
                version_ids.add(str(claim.product_version_id))
        for evidence in session.execute(
            select(ClaimEvidence).where(ClaimEvidence.claim_id.in_(claim_ids))
        ).scalars():
            pf.evidence_by_claim.setdefault(evidence.claim_id, []).append(evidence)

    if version_ids:
        for version, product in session.execute(
            select(ProductVersion, InsuranceProduct)
            .join(InsuranceProduct, ProductVersion.product_id == InsuranceProduct.id)
            .where(
                ProductVersion.id.in_(version_ids),
                ProductVersion.space_id == scope.space_id,
            )
        ).all():
            pf.products_by_version[str(version.id)] = (
                product.product_code,
                product.canonical_name,
                version.version_label,
            )
    return pf


def _claim_side_cached(pf: _Prefetch, claim_id: str | None) -> ClaimSideView | None:
    if not claim_id:
        return None
    claim = pf.claims.get(str(claim_id))
    if claim is None:
        return None
    return ClaimSideView(
        claim_id=claim.id,
        predicate=claim.predicate,
        value=_value_text(claim.value),
        value_state=claim.value_state,
        status=claim.status,
        confidence=claim.confidence,
        evidence=_evidence_from_rows(pf.evidence_by_claim.get(claim.id, [])),
    )


def claim_side(
    session: Session, scope: KnowledgeScope, claim_id: str | None
) -> ClaimSideView | None:
    """公开入口：一条 Claim 的展示侧（值+状态+证据）；跨 space/不存在 → None。"""
    if not claim_id:
        return None
    claim = session.get(Claim, str(claim_id))
    if claim is None or claim.space_id != scope.space_id:
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


def _conflict_view(pf: _Prefetch, conflict: Conflict) -> ConflictView:
    proposed_raw = conflict.proposed or {}
    return ConflictView(
        conflict_id=conflict.id,
        status=conflict.status,
        existing=_claim_side_cached(pf, conflict.existing_claim_id),
        proposed=_proposal_side(proposed_raw) if proposed_raw else None,
        decision_basis=dict(conflict.decision_basis or {}),
    )


def _project_change_item_cached(
    pf: _Prefetch, item: ChangeItem
) -> ChangeItemProjection:
    """按 action/mode 解析一条 ChangeItem（唯一读取合同入口；prefetch 内）。

    解析优先级：``proposed["claim"]``（提案原文）→ 持久化 Claim 行（claim_id /
    existing/placeholder id）→ 顶层扁平键（历史/降级容错）。
    """
    proposed: dict[str, Any] = dict(item.proposed or {})
    mode = proposed.get("mode")
    claim_payload = proposed.get("claim")
    claim_dict = claim_payload if isinstance(claim_payload, dict) else None

    candidate = _claim_side_cached(pf, item.claim_id)
    existing_id = proposed.get("existing_claim_id") or proposed.get(
        "placeholder_claim_id"
    )
    existing = _claim_side_cached(pf, str(existing_id) if existing_id else None)
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
            row = pf.claims.get(str(cid))
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

    conflict_row = pf.conflicts_by_item.get(item.id)
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
            _conflict_view(pf, conflict_row) if conflict_row is not None else None
        ),
        gate=gate_view_from_payload(basis.get("gate")),
        decision_basis=basis,
    )


def project_change_item(
    session: Session,
    scope: KnowledgeScope,
    item: ChangeItem,
    *,
    prefetch: _Prefetch | None = None,
) -> ChangeItemProjection:
    """单条投影入口。**边界（codex R2-P2）**：传入的 ChangeItem 必须经其
    ChangeSet 归属当前 scope，否则 ``ScopeViolation``——绝不产出 foreign DTO。"""
    require_current_scope(session, scope)
    pf = prefetch or _build_prefetch(session, scope, change_items=(item,))
    if item.id not in pf.change_items:
        raise ScopeViolation("scope mismatch")
    return _project_change_item_cached(pf, item)


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


def _aggregate_cached(pf: _Prefetch, item: ReviewItem) -> ReviewAggregate:
    subject = dict(item.subject or {})
    change_item_id = subject.get("change_item_id")
    projection: ChangeItemProjection | None = None
    if change_item_id:
        change_item = pf.change_items.get(str(change_item_id))
        if change_item is not None:
            projection = _project_change_item_cached(pf, change_item)
    predicate = subject.get("predicate") or (
        projection.predicate if projection is not None else None
    )
    product_version_id = subject.get("product_version_id") or (
        projection.product_version_id if projection is not None else None
    )
    product_code: str | None = None
    product_name: str | None = None
    version_label: str | None = None
    if product_version_id:
        product_version_id = str(product_version_id)
        info = pf.products_by_version.get(product_version_id)
        if info is not None:
            product_code, product_name, version_label = info
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
        change_set_id=(projection.change_set_id if projection is not None else None),
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


def load_review_aggregates(
    session: Session, scope: KnowledgeScope, items: Sequence[ReviewItem]
) -> tuple[ReviewAggregate, ...]:
    """批量投影（codex R2-P1）：任意条数 = 固定 5 条 IN 查询的一次预取。

    **边界（R2-P2）**：任一传入 ReviewItem 不属于当前 scope → ``ScopeViolation``。
    """
    require_current_scope(session, scope)
    for item in items:
        if item.space_id != scope.space_id:
            raise ScopeViolation("scope mismatch")
    pf = _build_prefetch(session, scope, review_items=items)
    return tuple(_aggregate_cached(pf, item) for item in items)


def load_review_aggregate(
    session: Session, scope: KnowledgeScope, item: ReviewItem
) -> ReviewAggregate:
    """单条审核项的完整审阅上下文（W1 单条详情的数据源）。

    **边界（R2-P2）**：传入 ReviewItem 不属于当前 scope → ``ScopeViolation``。
    """
    return load_review_aggregates(session, scope, (item,))[0]


def claim_revisions(
    session: Session, scope: KnowledgeScope, claim_id: str
) -> tuple[RevisionView, ...]:
    """一条 Claim 的修订历史投影（下钻/时间线复用）。"""
    require_current_scope(session, scope)
    claim = session.get(Claim, claim_id)
    if claim is None or claim.space_id != scope.space_id:
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
