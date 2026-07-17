"""008 T2：只读查询模块（W1.1 队列 / W2.1 变更 / W3.1 完整度）。

只读纪律（W5.1）：本模块零写入——不 add/delete，任何写动作只经
knowledge/ 服务层（merge.resolve_review 等）在动作路由中调用。

数据合同（PR#15 阻断 1 修复）：本模块**不读取** ``ChangeItem.proposed`` 内部形态，
一律消费 ``knowledge/projection.py`` 的 DTO——add/fill_unknown/append_evidence/
supersede/conflict/retract/overturn 的解析一处收口在知识域。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.models import InsuranceProduct, ProductVersion
from insurance_harness.db.scope import KnowledgeScope, require_current_scope
from insurance_harness.knowledge.projection import (
    ChangeItemProjection,
    ClaimSideView,
    ConflictView,
    ReviewAggregate,
    RevisionView,
    claim_revisions,
    claim_side,
    load_review_aggregate,
    project_change_item,
)
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    Conflict,
    ReviewItem,
)
from insurance_harness.schemas.models import SchemaRegistry

_RISK_ORDER = {"high": 0, "medium": 1, "low": 2}

# 缺口态（W3.3：缺口清单导出只含这三类；present/absent_explicitly 是"已收录"非缺口）
GAP_STATES = frozenset({"unknown", "pending_review", "conflict_open"})


class QueuePage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[ReviewAggregate, ...]
    total: int
    limit: int
    offset: int
    status: str
    risk_level: str | None = None
    type_: str | None = None
    product_code: str | None = None


def list_review_queue(
    session: Session,
    scope: KnowledgeScope,
    *,
    status: str = "open",
    risk_level: str | None = None,
    type_: str | None = None,
    product_code: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> QueuePage:
    """W1.1：默认只列 open；**触发计数倒序默认**（spec 原文），次序 risk 序、更新时间倒序；
    按产品/风险/类型筛选；分页返回总数。每条即完整审阅上下文（ReviewAggregate）。"""
    require_current_scope(session, scope)
    stmt = select(ReviewItem).where(
        ReviewItem.space_id == scope.space_id, ReviewItem.status == status
    )
    if risk_level:
        stmt = stmt.where(ReviewItem.risk_level == risk_level)
    if type_:
        stmt = stmt.where(ReviewItem.type == type_)
    rows = list(session.execute(stmt).scalars())
    aggregates = [load_review_aggregate(session, scope, r) for r in rows]
    if product_code:
        aggregates = [a for a in aggregates if a.product_code == product_code]

    def _order(a: ReviewAggregate) -> tuple[int, int, float]:
        try:
            ts = datetime.fromisoformat(a.version_token).timestamp()
        except ValueError:
            ts = 0.0
        return (-a.trigger_count, _RISK_ORDER.get(a.risk_level, 9), -ts)

    aggregates.sort(key=_order)
    total = len(aggregates)
    window = tuple(aggregates[offset : offset + limit])
    return QueuePage(
        items=window,
        total=total,
        limit=limit,
        offset=offset,
        status=status,
        risk_level=risk_level,
        type_=type_,
        product_code=product_code,
    )


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
        select(ChangeItem.change_set_id, ChangeItem.action)
        .where(ChangeItem.change_set_id.in_([s.id for s in sets]))
    ).all()
    counts: dict[str, dict[str, int]] = {}
    for set_id, action in counts_rows:
        bucket = counts.setdefault(str(set_id), {})
        bucket[str(action)] = bucket.get(str(action), 0) + 1
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


class ReviewRef(BaseModel):
    """ChangeItem → 关联审核项（明细页翻案入口用）。"""

    model_config = ConfigDict(frozen=True)

    review_key: str
    status: str
    resolution_action: str | None = None


class ChangeSetDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    change_set_id: str
    source_kind: str
    status: str
    created_by: str
    items: tuple[ChangeItemProjection, ...]
    reviews: dict[str, ReviewRef] = Field(default_factory=dict)  # change_item_id →


def change_set_detail(
    session: Session, scope: KnowledgeScope, change_set_id: str
) -> ChangeSetDetail | None:
    """W2.2：明细全部经投影（真实 MergeEngine 形态可展示）；跨 space 返回 None。"""
    require_current_scope(session, scope)
    cs = session.get(ChangeSet, change_set_id)
    if cs is None or cs.space_id != scope.space_id:
        return None
    items = list(
        session.execute(
            select(ChangeItem)
            .where(ChangeItem.change_set_id == cs.id)
            .order_by(ChangeItem.created_at)
        ).scalars()
    )
    projections = tuple(project_change_item(session, scope, i) for i in items)
    item_ids = {i.id for i in items}
    reviews: dict[str, ReviewRef] = {}
    for review in session.execute(
        select(ReviewItem).where(ReviewItem.space_id == scope.space_id)
    ).scalars():
        cid = (review.subject or {}).get("change_item_id")
        if cid in item_ids:
            reviews[str(cid)] = ReviewRef(
                review_key=review.review_key,
                status=review.status,
                resolution_action=(
                    str((review.resolution or {}).get("action"))
                    if (review.resolution or {}).get("action")
                    else None
                ),
            )
    return ChangeSetDetail(
        change_set_id=str(cs.id),
        source_kind=cs.source_kind,
        status=cs.status,
        created_by=cs.created_by,
        items=projections,
        reviews=reviews,
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


def _value_str(value: object) -> str:
    if isinstance(value, dict) and "text" in value:
        return str(value["text"])
    return "" if value is None else str(value)


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
            before_value=_value_str((rev.before or {}).get("value")),
            after_value=_value_str((rev.after or {}).get("value")),
            reason=rev.reason,
        )
        for rev, claim, product in rows
    )


# ------------------------------------------------------------------ W3 完整度矩阵


class MatrixCell(BaseModel):
    """单格投影：HTML 与 CSV/JSONL 导出复用同一结构（阻断 5：一处 cell projection）。"""

    model_config = ConfigDict(frozen=True)

    state: str  # present / absent_explicitly / unknown / pending_review / conflict_open
    field_name: str | None = None  # schema 中文名（未在 schema 的历史谓词为 None）
    in_schema: bool = True
    review_key: str | None = None
    conflict_id: str | None = None
    ticket_source: str = ""


class MatrixRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    version_id: str
    product_code: str
    product_name: str
    version_label: str
    category: str
    schema_missing: bool = False  # 产品 category 不在注册表：只显示观测数据并显式标注
    cells: dict[str, MatrixCell] = Field(default_factory=dict)


class CompletenessMatrix(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str
    category: str | None = None
    categories: tuple[str, ...] = ()
    rows: tuple[MatrixRow, ...] = ()


def completeness_matrix(
    session: Session,
    scope: KnowledgeScope,
    registry: SchemaRegistry,
    *,
    category: str | None = None,
) -> CompletenessMatrix:
    """W3.1 产品×schema **全字段**热力矩阵（阻断 5 修复）。

    每个产品版本先按其险种（``InsuranceProduct.category`` = 注册表 line_key）铺
    schema 全字段 ``unknown`` 底图（未收录≠不存在），再覆盖 published 三态、
    pending_review、conflict_open；优先级 conflict_open > pending_review > 三态。
    从未出现过的 schema 字段因此**必然**以 unknown 显示，不会消失。
    """
    require_current_scope(session, scope)
    version_rows: list[tuple[ProductVersion, InsuranceProduct]] = [
        (v, p)
        for v, p in session.execute(
            select(ProductVersion, InsuranceProduct)
            .join(InsuranceProduct, ProductVersion.product_id == InsuranceProduct.id)
            .where(ProductVersion.space_id == scope.space_id)
        ).all()
    ]
    categories = tuple(
        sorted({product.category for _v, product in version_rows if product.category})
    )
    if category:
        version_rows = [
            (v, p) for v, p in version_rows if p.category == category
        ]
    cells: dict[str, dict[str, MatrixCell]] = {}
    schema_missing: dict[str, bool] = {}
    field_names: dict[str, dict[str, str]] = {}  # version_id → field_id → 中文名
    for version, product in version_rows:
        vid = str(version.id)
        line = registry.lines.get(product.category)
        if line is None:
            schema_missing[vid] = True
            cells[vid] = {}
            field_names[vid] = {}
            continue
        schema_missing[vid] = False
        field_names[vid] = {f.field_id: f.name for f in line.fields}
        cells[vid] = {
            f.field_id: MatrixCell(
                state="unknown",
                field_name=f.name,
                in_schema=True,
                ticket_source=f"schema:{registry.version}",
            )
            for f in line.fields
        }
    version_ids = set(cells)

    def _put(vid: str, predicate: str, cell: MatrixCell) -> None:
        if vid not in version_ids:
            return
        known_name = field_names.get(vid, {}).get(predicate)
        cells[vid][predicate] = cell.model_copy(
            update={
                "field_name": known_name,
                "in_schema": predicate in field_names.get(vid, {}),
            }
        )

    # published 三态（value_state：present / absent_explicitly / unknown）
    for claim in session.execute(
        select(Claim).where(
            Claim.space_id == scope.space_id, Claim.status == "published"
        )
    ).scalars():
        if claim.product_version_id:
            _put(
                str(claim.product_version_id),
                claim.predicate,
                MatrixCell(state=claim.value_state),
            )
    # 待审（open ReviewItem）——覆盖三态；(version, predicate) 经投影解析真实形态
    for item in session.execute(
        select(ReviewItem).where(
            ReviewItem.space_id == scope.space_id, ReviewItem.status == "open"
        )
    ).scalars():
        aggregate = load_review_aggregate(session, scope, item)
        if aggregate.product_version_id and aggregate.predicate:
            _put(
                aggregate.product_version_id,
                aggregate.predicate,
                MatrixCell(
                    state="pending_review",
                    review_key=aggregate.review_key,
                    ticket_source=f"review:{aggregate.review_key}",
                ),
            )
    # 冲突中（open/pending_judge Conflict）——最高优先；Conflict.proposed 为扁平提案 dump
    for conflict, change_item in session.execute(
        select(Conflict, ChangeItem)
        .join(ChangeItem, Conflict.change_item_id == ChangeItem.id)
        .join(ChangeSet, ChangeItem.change_set_id == ChangeSet.id)
        .where(Conflict.status.in_(("open", "pending_judge")))
        .where(ChangeSet.space_id == scope.space_id)
    ).all():
        proposed = conflict.proposed or {}
        cvid: str | None = proposed.get("product_version_id")
        cpred: str | None = proposed.get("predicate")
        if not (cvid and cpred):
            projection = project_change_item(session, scope, change_item)
            cvid = projection.product_version_id
            cpred = projection.predicate
        if cvid and cpred:
            _put(
                str(cvid),
                str(cpred),
                MatrixCell(
                    state="conflict_open",
                    conflict_id=conflict.id,
                    ticket_source=f"conflict:{conflict.id}",
                ),
            )
    rows = tuple(
        MatrixRow(
            version_id=str(version.id),
            product_code=product.product_code,
            product_name=product.canonical_name,
            version_label=version.version_label,
            category=product.category,
            schema_missing=schema_missing.get(str(version.id), False),
            cells=cells.get(str(version.id), {}),
        )
        for version, product in version_rows
    )
    return CompletenessMatrix(
        schema_version=registry.version,
        category=category,
        categories=categories,
        rows=rows,
    )


def matrix_export_rows(
    session: Session,
    scope: KnowledgeScope,
    registry: SchemaRegistry,
    *,
    category: str | None = None,
) -> tuple[dict[str, str], ...]:
    """W3.3 **缺口清单**导出行：只含 unknown / pending_review / conflict_open
    （present/absent_explicitly 是已收录事实，不是缺口——阻断 5）。

    ``ticket_source``：unknown → ``schema:<版本>``；待审 → ``review:<key>``；
    冲突 → ``conflict:<id>``（011 H1.6 / 015 问答缺口交付后追加外部来源）。
    """
    matrix = completeness_matrix(session, scope, registry, category=category)
    out: list[dict[str, str]] = []
    for row in matrix.rows:
        for field, cell in sorted(row.cells.items()):
            if cell.state not in GAP_STATES:
                continue
            out.append(
                {
                    "product_code": row.product_code,
                    "product_name": row.product_name,
                    "version_label": row.version_label,
                    "category": row.category,
                    "field": field,
                    "field_name": cell.field_name or "",
                    "state": cell.state,
                    "ticket_source": cell.ticket_source,
                }
            )
    return tuple(out)


class DrillView(BaseModel):
    """W3.2 格子下钻：五态各给证据链（阻断 5：pending/conflict 下钻不再 404）。"""

    model_config = ConfigDict(frozen=True)

    predicate: str
    state: str
    field_name: str | None = None
    schema_version: str
    published: ClaimSideView | None = None
    revisions: tuple[RevisionView, ...] = ()
    pending: ReviewAggregate | None = None
    conflict: ConflictView | None = None
    unknown_note: str | None = None
    schema_source: str | None = None


def cell_drill(
    session: Session,
    scope: KnowledgeScope,
    registry: SchemaRegistry,
    version_id: str,
    predicate: str,
) -> DrillView | None:
    """格子下钻：published 展示 Claim/证据/修订链；pending 展示候选/证据/审核历史；
    conflict 展示双方证据+basis；unknown 展示「未收录≠不存在」与 schema 来源。
    版本不在本 space、或谓词既无数据也不在该险种 schema → None（404）。"""
    require_current_scope(session, scope)
    row = session.execute(
        select(ProductVersion, InsuranceProduct)
        .join(InsuranceProduct, ProductVersion.product_id == InsuranceProduct.id)
        .where(
            ProductVersion.id == version_id,
            ProductVersion.space_id == scope.space_id,
        )
    ).first()
    if row is None:
        return None
    _version, product = row
    line = registry.lines.get(product.category)
    field_spec = None
    if line is not None:
        field_spec = next(
            (f for f in line.fields if f.field_id == predicate), None
        )
    published_claim = session.execute(
        select(Claim)
        .where(
            Claim.space_id == scope.space_id,
            Claim.product_version_id == version_id,
            Claim.predicate == predicate,
            Claim.status == "published",
        )
        .limit(1)
    ).scalar_one_or_none()
    published = (
        claim_side(session, scope, published_claim.id)
        if published_claim is not None
        else None
    )
    revisions = (
        claim_revisions(session, scope, published_claim.id)
        if published_claim is not None
        else ()
    )
    pending: ReviewAggregate | None = None
    for item in session.execute(
        select(ReviewItem).where(
            ReviewItem.space_id == scope.space_id, ReviewItem.status == "open"
        )
    ).scalars():
        aggregate = load_review_aggregate(session, scope, item)
        if (
            aggregate.product_version_id == version_id
            and aggregate.predicate == predicate
        ):
            pending = aggregate
            break
    conflict_view: ConflictView | None = None
    if pending is not None and pending.change_item is not None:
        conflict_view = pending.change_item.conflict
    if conflict_view is None:
        for _conflict, change_item in session.execute(
            select(Conflict, ChangeItem)
            .join(ChangeItem, Conflict.change_item_id == ChangeItem.id)
            .join(ChangeSet, ChangeItem.change_set_id == ChangeSet.id)
            .where(Conflict.status.in_(("open", "pending_judge")))
            .where(ChangeSet.space_id == scope.space_id)
        ).all():
            projection = project_change_item(session, scope, change_item)
            if (
                projection.product_version_id == version_id
                and projection.predicate == predicate
                and projection.conflict is not None
            ):
                conflict_view = projection.conflict
                break
    if conflict_view is not None and conflict_view.status in ("open", "pending_judge"):
        state = "conflict_open"
    elif pending is not None:
        state = "pending_review"
    elif published_claim is not None:
        state = published_claim.value_state
    elif field_spec is not None:
        state = "unknown"
    else:
        return None  # 无数据且不在 schema：不存在的格
    return DrillView(
        predicate=predicate,
        state=state,
        field_name=field_spec.name if field_spec is not None else None,
        schema_version=registry.version,
        published=published,
        revisions=revisions,
        pending=pending,
        conflict=conflict_view,
        unknown_note=(
            "未收录 ≠ 不存在：该字段在险种 schema 中定义，但尚无任何文档证据入库"
            if state == "unknown"
            else None
        ),
        schema_source=(
            f"schema {registry.version} · {field_spec.source_sheet or product.category}"
            if field_spec is not None
            else None
        ),
    )
