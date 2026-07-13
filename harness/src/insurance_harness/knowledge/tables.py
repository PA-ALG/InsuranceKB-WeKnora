"""知识域 ORM（change 007；docs/insurance-kb/03 §2.3~§2.6/§5/§8 的剩余表）。

表结构权威：docs/insurance-kb/03-knowledge-model.md——偏差先修订文档再改此处与迁移。
sqlite 仅测试用，兼容边界沿用 003 声明（db/README.md）：只用跨方言类型；
发布态部分唯一索引的 NULL 维度不去重，由合并引擎应用层兜底（03 §8 claims 行）。
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from insurance_harness.db.base import Base, utcnow
from insurance_harness.db.models import TimestampMixin, _uuid


class Claim(TimestampMixin, Base):
    """一条可独立验证/审核/版本化的最小事实（03 §2.3）。"""

    __tablename__ = "claims"
    __table_args__ = (
        Index(
            "uq_claims_published",
            "product_version_id",
            "concept_id",
            "predicate",
            "effective_from",
            unique=True,
            sqlite_where=text("status = 'published'"),
            postgresql_where=text("status = 'published'"),
        ),
        Index("ix_claims_subject", "product_version_id", "predicate"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subject_type: Mapped[str] = mapped_column(String(32), default="product_version")
    product_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("product_versions.id"), index=True
    )
    concept_id: Mapped[str | None] = mapped_column(String(36))
    predicate: Mapped[str] = mapped_column(String(128))
    value_state: Mapped[str] = mapped_column(String(32))  # present/absent_explicitly/unknown
    value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    # draft/candidate/published/superseded/retracted（03 §2.3.2）
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    extraction_method: Mapped[str] = mapped_column(String(32), default="llm")
    schema_version: Mapped[str] = mapped_column(String(64), default="", index=True)
    current_revision: Mapped[int] = mapped_column(Integer, default=0)
    superseded_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("claims.id"))
    pending_judge: Mapped[bool] = mapped_column(Boolean, default=False)


class ClaimEvidence(TimestampMixin, Base):
    """Claim 的溯源证据（03 §2.4）；无 Evidence 的 Claim 不得 published。"""

    __tablename__ = "claim_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    knowledge_id: Mapped[str] = mapped_column(String(255), index=True)
    chunk_id: Mapped[str | None] = mapped_column(String(64))
    quote: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(255))
    table_ref: Mapped[str | None] = mapped_column(String(255))
    timestamp_ms: Mapped[int | None] = mapped_column(Integer)
    authority_level: Mapped[int] = mapped_column(Integer)  # 03 §6.1，数值越小越权威
    doc_role: Mapped[str] = mapped_column(String(32))
    extraction_method: Mapped[str] = mapped_column(String(32), default="llm")
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClaimRevision(TimestampMixin, Base):
    """不可变修订链（03 §5.1）：每次 ChangeItem 应用产生一条。"""

    __tablename__ = "claim_revisions"
    __table_args__ = (UniqueConstraint("claim_id", "revision_no", name="uq_claim_revision"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after: Mapped[dict[str, Any]] = mapped_column(JSON)
    change_item_id: Mapped[str | None] = mapped_column(String(36))
    actor: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(String(255))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChangeSet(TimestampMixin, Base):
    """一批导入产生一个不可变 ChangeSet（03 §2.5）：source_batch 字段只写一次。"""

    __tablename__ = "change_sets"
    __table_args__ = (
        UniqueConstraint(
            "source_kind", "external_record_id", "source_revision", name="uq_changeset_source"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # document / structured_import / manual_edit / recompile / rollback
    source_kind: Mapped[str] = mapped_column(String(32))
    knowledge_ids: Mapped[list[str] | None] = mapped_column(JSON)
    external_record_id: Mapped[str | None] = mapped_column(String(128))
    source_revision: Mapped[str | None] = mapped_column(String(64))
    # pending / partially_applied / applied / rejected / rolled_back
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_by: Mapped[str] = mapped_column(String(128))


class ChangeItem(TimestampMixin, Base):
    __tablename__ = "change_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    change_set_id: Mapped[str] = mapped_column(String(36), ForeignKey("change_sets.id"), index=True)
    action: Mapped[str] = mapped_column(String(32))  # add/enrich/supersede/conflict/retract
    claim_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("claims.id"))
    proposed: Mapped[dict[str, Any]] = mapped_column(JSON)
    # auto_applied / needs_review / approved / rejected
    decision: Mapped[str] = mapped_column(String(32), default="needs_review")
    decision_basis: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class Conflict(TimestampMixin, Base):
    __tablename__ = "conflicts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    change_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("change_items.id"))
    existing_claim_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("claims.id"))
    proposed: Mapped[dict[str, Any]] = mapped_column(JSON)
    decision_basis: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # open / pending_judge / resolved
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)


class ReviewItem(TimestampMixin, Base):
    """内容派生稳定 ID + 受限动作集（03 §2.6）。"""

    __tablename__ = "review_items"
    __table_args__ = (Index("ix_review_status_risk", "status", "risk_level"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    review_key: Mapped[str] = mapped_column(String(64), unique=True)
    type: Mapped[str] = mapped_column(String(32))
    subject: Mapped[dict[str, Any]] = mapped_column(JSON)
    allowed_actions: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="open")  # open/resolved/dismissed
    resolution: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    risk_level: Mapped[str] = mapped_column(String(16), default="low")


class ReleaseSnapshot(TimestampMixin, Base):
    """库级发布快照（03 §5.2）：冻结 claim 集 + 物化渲染产物。"""

    __tablename__ = "release_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    label: Mapped[str] = mapped_column(String(128), unique=True)
    rendered_pages: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_by: Mapped[str] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(Text)


class SnapshotClaim(TimestampMixin, Base):
    __tablename__ = "snapshot_claims"
    __table_args__ = (UniqueConstraint("snapshot_id", "claim_id", name="uq_snapshot_claim"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("release_snapshots.id"), index=True
    )
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"))
    revision_no: Mapped[int] = mapped_column(Integer)


class CurrentRelease(TimestampMixin, Base):
    """当前快照指针（单行表；生产 Agent 只消费指针指向的快照，03 §5.2）。"""

    __tablename__ = "current_release"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default="current")
    snapshot_id: Mapped[str] = mapped_column(String(36), ForeignKey("release_snapshots.id"))
