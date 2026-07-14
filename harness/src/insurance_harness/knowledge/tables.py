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
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
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
            "space_id",
            "product_version_id",
            "concept_id",
            "predicate",
            "effective_from",
            unique=True,
            sqlite_where=text("status = 'published'"),
            postgresql_where=text("status = 'published'"),
        ),
        Index("ix_claims_subject", "product_version_id", "predicate"),
        Index("ix_claims_version", "product_version_id"),
        UniqueConstraint("space_id", "id", name="uq_claims_space_id"),
        ForeignKeyConstraint(
            ["space_id", "product_version_id"],
            ["product_versions.space_id", "product_versions.id"],
            name="fk_claims_space_product_version",
        ),
        ForeignKeyConstraint(
            ["space_id", "superseded_by"],
            ["claims.space_id", "claims.id"],
            name="fk_claims_space_superseded_by",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_claims_space")
    )
    subject_type: Mapped[str] = mapped_column(String(32), default="product_version")
    product_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("product_versions.id")
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
    __table_args__ = (
        Index("ix_evidence_claim", "claim_id"),
        Index("ix_evidence_knowledge", "knowledge_id"),
        Index("ix_evidence_source_revision", "knowledge_id", "source_revision"),
        Index("ix_evidence_stale", "stale_at", "knowledge_id"),
        CheckConstraint(
            "lineage_status IS NULL OR lineage_status IN ('linked', 'page_only', 'ambiguous')",
            name="ck_evidence_lineage_status",
        ),
        CheckConstraint(
            "(lineage_status IS NULL AND raw_kb_id IS NULL "
            "AND source_revision IS NULL AND file_hash IS NULL "
            "AND original_digest IS NULL AND parser_version IS NULL "
            "AND chunk_hash IS NULL AND stale_at IS NULL) OR "
            "(lineage_status IS NOT NULL AND raw_kb_id IS NOT NULL "
            "AND source_revision IS NOT NULL AND file_hash IS NOT NULL "
            "AND original_digest IS NOT NULL AND parser_version IS NOT NULL)",
            name="ck_evidence_source_audit",
        ),
        CheckConstraint(
            "lineage_status IS NULL OR "
            "(lineage_status = 'linked' AND chunk_id IS NOT NULL AND chunk_hash IS NOT NULL) "
            "OR (lineage_status IN ('page_only', 'ambiguous') "
            "AND chunk_id IS NULL AND chunk_hash IS NULL)",
            name="ck_evidence_chunk_shape",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"))
    knowledge_id: Mapped[str] = mapped_column(String(255))
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
    raw_kb_id: Mapped[str | None] = mapped_column(String(255))
    source_revision: Mapped[str | None] = mapped_column(String(64))
    file_hash: Mapped[str | None] = mapped_column(String(64))
    original_digest: Mapped[str | None] = mapped_column(String(64))
    parser_version: Mapped[str | None] = mapped_column(String(255))
    chunk_hash: Mapped[str | None] = mapped_column(String(64))
    lineage_status: Mapped[str | None] = mapped_column(String(16))
    stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClaimRevision(TimestampMixin, Base):
    """不可变修订链（03 §5.1）：每次 ChangeItem 应用产生一条。"""

    __tablename__ = "claim_revisions"
    __table_args__ = (
        UniqueConstraint("claim_id", "revision_no", name="uq_claim_revision"),
        Index("ix_revisions_claim", "claim_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"))
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
            "space_id",
            "source_kind",
            "external_record_id",
            "source_revision",
            name="uq_changeset_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_change_sets_space")
    )
    # document（含 source import 与 retract:<digest> 事件） /
    # structured_import / manual_edit / recompile / rollback
    source_kind: Mapped[str] = mapped_column(String(32))
    knowledge_ids: Mapped[list[str] | None] = mapped_column(JSON)
    external_record_id: Mapped[str | None] = mapped_column(String(128))
    source_revision: Mapped[str | None] = mapped_column(String(64))
    # pending / partially_applied / applied / rejected / rolled_back
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_by: Mapped[str] = mapped_column(String(128))


class ChangeItem(TimestampMixin, Base):
    __tablename__ = "change_items"
    __table_args__ = (Index("ix_items_changeset", "change_set_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    change_set_id: Mapped[str] = mapped_column(String(36), ForeignKey("change_sets.id"))
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
    __table_args__ = (
        Index("ix_review_status_risk", "status", "risk_level"),
        UniqueConstraint("space_id", "review_key", name="uq_review_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_review_items_space")
    )
    review_key: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(32))
    subject: Mapped[dict[str, Any]] = mapped_column(JSON)
    allowed_actions: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="open")  # open/resolved/dismissed
    resolution: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    risk_level: Mapped[str] = mapped_column(String(16), default="low")


class ReleaseSnapshot(TimestampMixin, Base):
    """库级发布快照（03 §5.2）：冻结 claim 集 + 物化渲染产物。"""

    __tablename__ = "release_snapshots"
    __table_args__ = (
        UniqueConstraint("space_id", "label", name="uq_snapshot_label"),
        UniqueConstraint("space_id", "id", name="uq_release_snapshots_space_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_release_snapshots_space")
    )
    label: Mapped[str] = mapped_column(String(128))
    rendered_pages: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_by: Mapped[str] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(Text)


class SnapshotClaim(TimestampMixin, Base):
    __tablename__ = "snapshot_claims"
    __table_args__ = (
        UniqueConstraint(
            "space_id", "snapshot_id", "claim_id", name="uq_snapshot_claim"
        ),
        ForeignKeyConstraint(
            ["space_id", "snapshot_id"],
            ["release_snapshots.space_id", "release_snapshots.id"],
            name="fk_snapshot_claims_space_snapshot",
        ),
        ForeignKeyConstraint(
            ["space_id", "claim_id"],
            ["claims.space_id", "claims.id"],
            name="fk_snapshot_claims_space_claim",
        ),
        Index("ix_snapshot_claims_snapshot", "snapshot_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_snapshot_claims_space")
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("release_snapshots.id")
    )
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"))
    revision_no: Mapped[int] = mapped_column(Integer)


class CurrentRelease(TimestampMixin, Base):
    """当前快照指针（单行表；生产 Agent 只消费指针指向的快照，03 §5.2）。"""

    __tablename__ = "current_release"
    __table_args__ = (
        UniqueConstraint("space_id", name="uq_current_release_space"),
        ForeignKeyConstraint(
            ["space_id", "snapshot_id"],
            ["release_snapshots.space_id", "release_snapshots.id"],
            name="fk_current_release_space_snapshot",
        ),
    )

    space_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_spaces.id", name="fk_current_release_space"),
        primary_key=True,
    )
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default="current")
    snapshot_id: Mapped[str] = mapped_column(String(36), ForeignKey("release_snapshots.id"))
