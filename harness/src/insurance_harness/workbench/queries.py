"""008 T2：只读查询模块（W1.1 队列 / W2.1 变更 / W3.1 完整度）。

只读纪律（W5.1）：本模块零写入——不 add/delete/update，任何写动作只经
knowledge/ 服务层（merge.resolve_review 等）在动作路由中调用。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from insurance_harness.db.models import InsuranceProduct, ProductVersion
from insurance_harness.db.scope import KnowledgeScope, require_current_scope
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    Conflict,
    ReviewItem,
)

_RISK_ORDER = {"high": 0, "medium": 1, "low": 2}


class QueueItemView(BaseModel):
    model_config = ConfigDict(frozen=True)

    review_key: str
    type: str
    risk_level: str
    status: str
    predicate: str | None
    subject: dict[str, Any]


class QueuePage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[QueueItemView, ...]
    total: int
    limit: int
    offset: int


def list_review_queue(
    session: Session,
    scope: KnowledgeScope,
    *,
    status: str = "open",
    risk_level: str | None = None,
    type_: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> QueuePage:
    """W1.1：默认只列 open；高风险排前（裁决记录：主链无"触发计数"字段，
    以 risk 序 + 更新时间倒序替代该排序语义）；分页返回总数。"""
    require_current_scope(session, scope)
    stmt = select(ReviewItem).where(
        ReviewItem.space_id == scope.space_id, ReviewItem.status == status
    )
    if risk_level:
        stmt = stmt.where(ReviewItem.risk_level == risk_level)
    if type_:
        stmt = stmt.where(ReviewItem.type == type_)
    rows = list(session.execute(stmt).scalars())
    rows.sort(
        key=lambda r: (_RISK_ORDER.get(r.risk_level, 9), -(r.updated_at.timestamp()))
    )
    total = len(rows)
    window = rows[offset : offset + limit]
    items = tuple(
        QueueItemView(
            review_key=r.review_key,
            type=r.type,
            risk_level=r.risk_level,
            status=r.status,
            predicate=(r.subject or {}).get("predicate"),
            subject=dict(r.subject or {}),
        )
        for r in window
    )
    return QueuePage(items=items, total=total, limit=limit, offset=offset)


class ChangeSetView(BaseModel):
    model_config = ConfigDict(frozen=True)

    change_set_id: str
    source_kind: str
    status: str
    created_by: str
    created_at: str
    action_counts: dict[str, int] = Field(default_factory=dict)


def list_change_sets(
    session: Session,
    scope: KnowledgeScope,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[ChangeSetView, ...]:
    """W2.1：时间倒序 + 每批五类 ChangeItem 动作计数（分色数据源）。"""
    require_current_scope(session, scope)
    sets = list(
        session.execute(
            select(ChangeSet)
            .where(ChangeSet.space_id == scope.space_id)
            .order_by(ChangeSet.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).scalars()
    )
    if not sets:
        return ()
    counts_rows = session.execute(
        select(ChangeItem.change_set_id, ChangeItem.action, func.count())
        .where(ChangeItem.change_set_id.in_([s.id for s in sets]))
        .group_by(ChangeItem.change_set_id, ChangeItem.action)
    ).all()
    counts: dict[str, dict[str, int]] = {}
    for set_id, action, n in counts_rows:
        counts.setdefault(str(set_id), {})[str(action)] = int(n)
    return tuple(
        ChangeSetView(
            change_set_id=str(s.id),
            source_kind=s.source_kind,
            status=s.status,
            created_by=s.created_by,
            created_at=s.created_at.isoformat(),
            action_counts=counts.get(str(s.id), {}),
        )
        for s in sets
    )


class MatrixRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    version_id: str
    product_code: str
    product_name: str
    version_label: str
    cells: dict[str, str] = Field(default_factory=dict)


class CompletenessMatrix(BaseModel):
    model_config = ConfigDict(frozen=True)

    rows: tuple[MatrixRow, ...]


def completeness_matrix(session: Session, scope: KnowledgeScope) -> CompletenessMatrix:
    """W3.1 五态格：conflict_open > pending_review > published 三态。

    数据源=主链聚合（claims/conflicts/review_items），零写入。
    """
    require_current_scope(session, scope)
    versions = session.execute(
        select(ProductVersion, InsuranceProduct)
        .join(InsuranceProduct, ProductVersion.product_id == InsuranceProduct.id)
        .where(ProductVersion.space_id == scope.space_id)
    ).all()
    # published 三态
    cells: dict[str, dict[str, str]] = {}
    for claim in session.execute(
        select(Claim).where(
            Claim.space_id == scope.space_id, Claim.status == "published"
        )
    ).scalars():
        if claim.product_version_id:
            cells.setdefault(claim.product_version_id, {})[claim.predicate] = (
                claim.value_state
            )
    # 待审（open ReviewItem）——覆盖三态
    for item in session.execute(
        select(ReviewItem).where(
            ReviewItem.space_id == scope.space_id, ReviewItem.status == "open"
        )
    ).scalars():
        subject = item.subject or {}
        predicate = subject.get("predicate")
        vid = _version_of_review(session, subject)
        if vid and predicate:
            cells.setdefault(vid, {})[str(predicate)] = "pending_review"
    # 冲突中（open Conflict）——最高优先
    for _conflict, change_item in session.execute(
        select(Conflict, ChangeItem)
        .join(ChangeItem, Conflict.change_item_id == ChangeItem.id)
        .join(ChangeSet, ChangeItem.change_set_id == ChangeSet.id)
        .where(Conflict.status.in_(("open", "pending_judge")))
        .where(ChangeSet.space_id == scope.space_id)
    ).all():
        proposed = change_item.proposed or {}
        vid = proposed.get("product_version_id")
        predicate = proposed.get("predicate")
        if vid and predicate:
            cells.setdefault(str(vid), {})[str(predicate)] = "conflict_open"
    rows = tuple(
        MatrixRow(
            version_id=str(version.id),
            product_code=product.product_code,
            product_name=product.canonical_name,
            version_label=version.version_label,
            cells=cells.get(str(version.id), {}),
        )
        for version, product in versions
    )
    return CompletenessMatrix(rows=rows)


class ConflictView(BaseModel):
    model_config = ConfigDict(frozen=True)

    existing_value: str
    proposed_value: str
    decision_basis: dict[str, Any] = Field(default_factory=dict)
    status: str


class ChangeItemDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    change_item_id: str
    action: str
    decision: str
    predicate: str | None
    proposed_value: str | None
    conflict: ConflictView | None = None


class ChangeSetDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    change_set_id: str
    source_kind: str
    status: str
    created_by: str
    items: tuple[ChangeItemDetail, ...]


def _value_text(value: Any) -> str:
    if isinstance(value, dict) and "text" in value:
        return str(value["text"])
    return "" if value is None else str(value)


def change_set_detail(
    session: Session, scope: KnowledgeScope, change_set_id: str
) -> ChangeSetDetail | None:
    """W2.2：明细 + conflict 双方值与自动裁决依据；跨 space 返回 None（不泄露）。"""
    require_current_scope(session, scope)
    cs = session.get(ChangeSet, change_set_id)
    if cs is None or cs.space_id != scope.space_id:
        return None
    items = list(
        session.execute(
            select(ChangeItem).where(ChangeItem.change_set_id == cs.id)
        ).scalars()
    )
    conflicts = {
        c.change_item_id: c
        for c in session.execute(
            select(Conflict).where(
                Conflict.change_item_id.in_([i.id for i in items] or [""])
            )
        ).scalars()
    }
    detail_items: list[ChangeItemDetail] = []
    for item in items:
        proposed = item.proposed or {}
        conflict_view: ConflictView | None = None
        conflict = conflicts.get(item.id)
        if conflict is not None:
            existing_text = ""
            if conflict.existing_claim_id:
                existing = session.get(Claim, conflict.existing_claim_id)
                if existing is not None and existing.space_id == scope.space_id:
                    existing_text = _value_text(existing.value)
            conflict_view = ConflictView(
                existing_value=existing_text,
                proposed_value=_value_text((conflict.proposed or {}).get("value")),
                decision_basis=dict(conflict.decision_basis or {}),
                status=conflict.status,
            )
        detail_items.append(
            ChangeItemDetail(
                change_item_id=str(item.id),
                action=item.action,
                decision=item.decision,
                predicate=proposed.get("predicate"),
                proposed_value=_value_text(proposed.get("value")) or None,
                conflict=conflict_view,
            )
        )
    return ChangeSetDetail(
        change_set_id=str(cs.id),
        source_kind=cs.source_kind,
        status=cs.status,
        created_by=cs.created_by,
        items=tuple(detail_items),
    )


class TimelineRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    at: str
    actor: str
    product_code: str
    product_name: str
    predicate: str
    before_value: str
    after_value: str
    reason: str | None


def product_timeline(
    session: Session, scope: KnowledgeScope, *, limit: int = 100
) -> tuple[TimelineRow, ...]:
    """W2.4/G8：人类可读变更流——谁/何时/什么字段/旧值→新值/原因（时间倒序）。

    数据源 = ClaimRevision 不可变修订链（每次 ChangeItem 应用一条）。
    """
    require_current_scope(session, scope)
    from insurance_harness.knowledge.tables import ClaimRevision

    rows = session.execute(
        select(ClaimRevision, Claim, InsuranceProduct)
        .join(Claim, ClaimRevision.claim_id == Claim.id)
        .join(ProductVersion, Claim.product_version_id == ProductVersion.id)
        .join(InsuranceProduct, ProductVersion.product_id == InsuranceProduct.id)
        .where(Claim.space_id == scope.space_id)
        .order_by(ClaimRevision.at.desc())
        .limit(limit)
    ).all()
    return tuple(
        TimelineRow(
            at=rev.at.isoformat(),
            actor=rev.actor,
            product_code=product.product_code,
            product_name=product.canonical_name,
            predicate=claim.predicate,
            before_value=_value_text((rev.before or {}).get("value")),
            after_value=_value_text((rev.after or {}).get("value")),
            reason=rev.reason,
        )
        for rev, claim, product in rows
    )


class EvidenceLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    knowledge_id: str
    page: int | None
    quote: str


class RevisionLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    at: str
    actor: str
    after_value: str
    reason: str | None


class ClaimDrill(BaseModel):
    model_config = ConfigDict(frozen=True)

    predicate: str
    value: str
    value_state: str
    status: str
    evidence: tuple[EvidenceLine, ...]
    revisions: tuple[RevisionLine, ...]


def claim_drill(
    session: Session, scope: KnowledgeScope, version_id: str, predicate: str
) -> ClaimDrill | None:
    """W3.2 下钻：published Claim + 证据 + 修订历史；跨 space 返回 None。"""
    require_current_scope(session, scope)
    from insurance_harness.knowledge.tables import ClaimEvidence, ClaimRevision

    claim = session.execute(
        select(Claim)
        .where(
            Claim.space_id == scope.space_id,
            Claim.product_version_id == version_id,
            Claim.predicate == predicate,
            Claim.status == "published",
        )
        .limit(1)
    ).scalar_one_or_none()
    if claim is None:
        return None
    evidence = tuple(
        EvidenceLine(knowledge_id=e.knowledge_id, page=e.page, quote=e.quote)
        for e in session.execute(
            select(ClaimEvidence).where(ClaimEvidence.claim_id == claim.id)
        ).scalars()
    )
    revisions = tuple(
        RevisionLine(
            at=r.at.isoformat(),
            actor=r.actor,
            after_value=_value_text((r.after or {}).get("value")),
            reason=r.reason,
        )
        for r in session.execute(
            select(ClaimRevision)
            .where(ClaimRevision.claim_id == claim.id)
            .order_by(ClaimRevision.revision_no.desc())
        ).scalars()
    )
    return ClaimDrill(
        predicate=claim.predicate,
        value=_value_text(claim.value),
        value_state=claim.value_state,
        status=claim.status,
        evidence=evidence,
        revisions=revisions,
    )


def matrix_export_rows(
    session: Session, scope: KnowledgeScope
) -> tuple[dict[str, str], ...]:
    """W3.3 导出行：product/field/state + 工单来源标注列（011/015 前为空）。"""
    matrix = completeness_matrix(session, scope)
    out: list[dict[str, str]] = []
    for row in matrix.rows:
        for field, state in sorted(row.cells.items()):
            out.append(
                {
                    "product_code": row.product_code,
                    "product_name": row.product_name,
                    "version_label": row.version_label,
                    "field": field,
                    "state": state,
                    "ticket_source": "",  # 011 H1.6 / 015 问答缺口交付后回填
                }
            )
    return tuple(out)


def _version_of_review(session: Session, subject: dict[str, Any]) -> str | None:
    change_item_id = subject.get("change_item_id")
    if not change_item_id:
        return None
    item = session.get(ChangeItem, str(change_item_id))
    if item is None:
        return None
    vid = (item.proposed or {}).get("product_version_id")
    return str(vid) if vid else None
