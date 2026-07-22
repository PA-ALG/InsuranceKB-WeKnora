"""知识域 ORM（change 007；docs/insurance-kb/03 §2.3~§2.6/§5/§8 的剩余表）。

表结构权威：docs/insurance-kb/03-knowledge-model.md——偏差先修订文档再改此处与迁移。
sqlite 仅测试用，兼容边界沿用 003 声明（db/README.md）：只用跨方言类型；
发布态部分唯一索引的 NULL 维度不去重，由合并引擎应用层兜底（03 §8 claims 行）。
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    DDL,
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
    event,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from insurance_harness.db.base import Base, utcnow
from insurance_harness.db.models import TimestampMixin, _uuid
from insurance_harness.knowledge.release_guard_ddl_018 import (
    register_metadata_guards,
)


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
        UniqueConstraint("space_id", "id", name="uq_change_sets_space_id"),
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
    __table_args__ = (
        UniqueConstraint(
            "change_set_id", "id", name="uq_change_items_change_set_id"
        ),
        Index("ix_items_changeset", "change_set_id"),
    )

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
        CheckConstraint(
            "status IN ('building', 'publishing', 'published', 'failed')",
            name="ck_release_snapshots_status",
        ),
        CheckConstraint(
            "read_model_version IN (0, 1)",
            name="ck_release_snapshots_read_model_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_release_snapshots_space")
    )
    label: Mapped[str] = mapped_column(String(128))
    rendered_pages: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="building", index=True)
    read_model_version: Mapped[int] = mapped_column(Integer, default=1)
    projection_frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[str] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(Text)


class ReleaseManifestRecord(TimestampMixin, Base):
    """Immutable canonical artifact envelope bound to one frozen snapshot."""

    __tablename__ = "release_manifests"
    __table_args__ = (
        UniqueConstraint(
            "space_id", "snapshot_id", name="uq_release_manifests_space_snapshot"
        ),
        UniqueConstraint(
            "space_id", "manifest_hash", name="uq_release_manifests_space_hash"
        ),
        UniqueConstraint(
            "space_id",
            "snapshot_id",
            "manifest_hash",
            name="uq_release_manifests_exact",
        ),
        ForeignKeyConstraint(
            ["space_id", "snapshot_id"],
            ["release_snapshots.space_id", "release_snapshots.id"],
            name="fk_release_manifests_space_snapshot",
        ),
        CheckConstraint(
            "length(manifest_hash) = 64 AND manifest_hash = lower(manifest_hash)",
            name="ck_release_manifests_hash",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_release_manifests_space")
    )
    snapshot_id: Mapped[str] = mapped_column(String(36))
    manifest_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ReleaseApproval(Base):
    """Append-only named-human approval of one exact ReleaseManifest."""

    __tablename__ = "release_approvals"
    __table_args__ = (
        UniqueConstraint(
            "space_id", "manifest_hash", name="uq_release_approvals_space_manifest"
        ),
        UniqueConstraint("space_id", "id", name="uq_release_approvals_space_id"),
        UniqueConstraint(
            "space_id",
            "snapshot_id",
            "manifest_hash",
            "id",
            name="uq_release_approvals_exact_id",
        ),
        ForeignKeyConstraint(
            ["space_id", "snapshot_id", "manifest_hash"],
            [
                "release_manifests.space_id",
                "release_manifests.snapshot_id",
                "release_manifests.manifest_hash",
            ],
            name="fk_release_approvals_exact_manifest",
        ),
        CheckConstraint(
            "actor_type IN ('human', 'principal')",
            name="ck_release_approvals_actor_type",
        ),
        CheckConstraint(
            "role = 'release_approver'",
            name="ck_release_approvals_role",
        ),
        CheckConstraint(
            "length(trim(actor)) > 0 AND length(trim(authorization_receipt)) > 0 "
            "AND length(trim(reason)) > 0",
            name="ck_release_approvals_named_attestation",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_release_approvals_space")
    )
    snapshot_id: Mapped[str] = mapped_column(String(36))
    manifest_hash: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(128))
    actor_type: Mapped[str] = mapped_column(String(16))
    role: Mapped[str] = mapped_column(String(32))
    authorization_receipt: Mapped[str] = mapped_column(String(512))
    reason: Mapped[str] = mapped_column(Text)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReleaseActivationAudit(Base):
    """Append-only audit of one explicit approved pointer transition."""

    __tablename__ = "release_activation_audits"
    __table_args__ = (
        ForeignKeyConstraint(
            ["space_id", "from_snapshot_id"],
            ["release_snapshots.space_id", "release_snapshots.id"],
            name="fk_release_activation_audits_from_snapshot",
        ),
        ForeignKeyConstraint(
            ["space_id", "target_snapshot_id", "manifest_hash"],
            [
                "release_manifests.space_id",
                "release_manifests.snapshot_id",
                "release_manifests.manifest_hash",
            ],
            name="fk_release_activation_audits_exact_manifest",
        ),
        ForeignKeyConstraint(
            ["space_id", "target_snapshot_id", "manifest_hash", "approval_id"],
            [
                "release_approvals.space_id",
                "release_approvals.snapshot_id",
                "release_approvals.manifest_hash",
                "release_approvals.id",
            ],
            name="fk_release_activation_audits_exact_approval",
        ),
        CheckConstraint(
            "kind IN ('promote', 'rollback')",
            name="ck_release_activation_audits_kind",
        ),
        CheckConstraint(
            "length(trim(actor)) > 0 AND length(trim(reason)) > 0",
            name="ck_release_activation_audits_attestation",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_spaces.id", name="fk_release_activation_audits_space"),
    )
    kind: Mapped[str] = mapped_column(String(16))
    from_snapshot_id: Mapped[str | None] = mapped_column(String(36))
    target_snapshot_id: Mapped[str] = mapped_column(String(36))
    manifest_hash: Mapped[str] = mapped_column(String(64))
    approval_id: Mapped[str] = mapped_column(String(36))
    actor: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReleaseAlert(Base):
    """Append-only safe operational alert for release-integrity failures."""

    __tablename__ = "release_alerts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["space_id", "snapshot_id", "manifest_hash"],
            [
                "release_manifests.space_id",
                "release_manifests.snapshot_id",
                "release_manifests.manifest_hash",
            ],
            name="fk_release_alerts_exact_manifest",
        ),
        CheckConstraint(
            "code = 'manifest_tamper'",
            name="ck_release_alerts_code",
        ),
        CheckConstraint(
            "severity = 'critical'",
            name="ck_release_alerts_severity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_release_alerts_space")
    )
    snapshot_id: Mapped[str] = mapped_column(String(36))
    manifest_hash: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(32), default="manifest_tamper")
    severity: Mapped[str] = mapped_column(String(16), default="critical")
    safe_details: Mapped[dict[str, Any]] = mapped_column(JSON)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SnapshotFact(TimestampMixin, Base):
    """不可变发布事实；Reader/页面均不得回查 mutable Claim 内容。"""

    __tablename__ = "snapshot_facts"
    __table_args__ = (
        UniqueConstraint(
            "space_id",
            "snapshot_id",
            "claim_id",
            "revision_no",
            name="uq_snapshot_fact_claim_revision",
        ),
        ForeignKeyConstraint(
            ["space_id", "snapshot_id"],
            ["release_snapshots.space_id", "release_snapshots.id"],
            name="fk_snapshot_facts_space_snapshot",
        ),
        ForeignKeyConstraint(
            ["space_id", "claim_id"],
            ["claims.space_id", "claims.id"],
            name="fk_snapshot_facts_space_claim",
        ),
        ForeignKeyConstraint(
            ["claim_id", "revision_no"],
            ["claim_revisions.claim_id", "claim_revisions.revision_no"],
            name="fk_snapshot_facts_claim_revision",
        ),
        ForeignKeyConstraint(
            ["space_id", "product_id"],
            ["insurance_products.space_id", "insurance_products.id"],
            name="fk_snapshot_facts_space_product",
        ),
        ForeignKeyConstraint(
            ["space_id", "product_version_id"],
            ["product_versions.space_id", "product_versions.id"],
            name="fk_snapshot_facts_space_product_version",
        ),
        CheckConstraint(
            "value_state IN ('present', 'absent_explicitly')",
            name="ck_snapshot_facts_value_state",
        ),
        Index(
            "ix_snapshot_facts_reader",
            "space_id",
            "snapshot_id",
            "product_id",
            "product_version_id",
            "predicate",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_snapshot_facts_space")
    )
    snapshot_id: Mapped[str] = mapped_column(String(36))
    claim_id: Mapped[str] = mapped_column(String(36))
    revision_no: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[str] = mapped_column(String(36))
    product_version_id: Mapped[str] = mapped_column(String(36))
    product_code: Mapped[str] = mapped_column(String(64))
    product_name: Mapped[str] = mapped_column(String(255))
    version_label: Mapped[str] = mapped_column(String(64))
    predicate: Mapped[str] = mapped_column(String(128))
    field_name: Mapped[str] = mapped_column(String(255))
    field_group: Mapped[str] = mapped_column(String(64))
    value_state: Mapped[str] = mapped_column(String(32))
    value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    confidence: Mapped[float] = mapped_column(Float)
    schema_version: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON)


class SnapshotClaim(TimestampMixin, Base):
    __tablename__ = "snapshot_claims"
    __table_args__ = (
        UniqueConstraint("space_id", "snapshot_id", "claim_id", name="uq_snapshot_claim"),
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
    snapshot_id: Mapped[str] = mapped_column(String(36), ForeignKey("release_snapshots.id"))
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


class ReleaseOperation(TimestampMixin, Base):
    """一次 publish/rollback/reconcile saga 的冻结身份与租约。"""

    __tablename__ = "release_operations"
    __table_args__ = (
        UniqueConstraint("space_id", "id", name="uq_release_operations_space_id"),
        ForeignKeyConstraint(
            ["space_id", "base_snapshot_id"],
            ["release_snapshots.space_id", "release_snapshots.id"],
            name="fk_release_operations_space_base_snapshot",
        ),
        ForeignKeyConstraint(
            ["space_id", "target_snapshot_id"],
            ["release_snapshots.space_id", "release_snapshots.id"],
            name="fk_release_operations_space_target_snapshot",
        ),
        ForeignKeyConstraint(
            ["space_id", "parent_operation_id"],
            ["release_operations.space_id", "release_operations.id"],
            name="fk_release_operations_space_parent",
        ),
        ForeignKeyConstraint(
            ["space_id", "previous_operation_id"],
            ["release_operations.space_id", "release_operations.id"],
            name="fk_release_operations_space_previous",
        ),
        CheckConstraint(
            "kind IN ('publish', 'rollback', 'reconcile')",
            name="ck_release_operations_kind",
        ),
        CheckConstraint(
            "status IN ('building', 'running', 'succeeded', 'failed')",
            name="ck_release_operations_status",
        ),
        CheckConstraint("retry_no >= 0", name="ck_release_operations_retry_no"),
        Index("ix_release_operations_lease", "status", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_release_operations_space")
    )
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="building")
    base_snapshot_id: Mapped[str | None] = mapped_column(String(36))
    target_snapshot_id: Mapped[str | None] = mapped_column(String(36))
    parent_operation_id: Mapped[str | None] = mapped_column(String(36))
    previous_operation_id: Mapped[str | None] = mapped_column(String(36))
    publish_plan: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    plan_digest: Mapped[str | None] = mapped_column(String(64))
    plan_frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_no: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(Text)


class PublishAttempt(TimestampMixin, Base):
    """冻结计划中一个外部动作的一次可审计执行。"""

    __tablename__ = "publish_attempts"
    __table_args__ = (
        UniqueConstraint(
            "space_id",
            "operation_id",
            "retry_no",
            "action_no",
            name="uq_publish_attempt_action",
        ),
        ForeignKeyConstraint(
            ["space_id", "operation_id"],
            ["release_operations.space_id", "release_operations.id"],
            name="fk_publish_attempts_space_operation",
        ),
        ForeignKeyConstraint(
            ["space_id", "snapshot_id"],
            ["release_snapshots.space_id", "release_snapshots.id"],
            name="fk_publish_attempts_space_snapshot",
        ),
        CheckConstraint(
            "operation IN ('upsert', 'delete')",
            name="ck_publish_attempts_operation",
        ),
        CheckConstraint(
            "status IN ('started', 'succeeded', 'failed', 'collision')",
            name="ck_publish_attempts_status",
        ),
        CheckConstraint("retry_no >= 0", name="ck_publish_attempts_retry_no"),
        CheckConstraint("action_no >= 0", name="ck_publish_attempts_action_no"),
        Index("ix_publish_attempts_operation", "operation_id", "retry_no"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_publish_attempts_space")
    )
    operation_id: Mapped[str] = mapped_column(String(36))
    retry_no: Mapped[int] = mapped_column(Integer)
    action_no: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="started")
    error: Mapped[str | None] = mapped_column(Text)
    snapshot_id: Mapped[str | None] = mapped_column(String(36))
    slug: Mapped[str] = mapped_column(String(1024))
    created_new: Mapped[bool | None] = mapped_column(Boolean)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReconciliationJob(TimestampMixin, Base):
    """失败 operation 的唯一恢复工单。"""

    __tablename__ = "reconciliation_jobs"
    __table_args__ = (
        UniqueConstraint(
            "space_id",
            "source_operation_id",
            name="uq_reconciliation_jobs_source_operation",
        ),
        ForeignKeyConstraint(
            ["space_id", "source_operation_id"],
            ["release_operations.space_id", "release_operations.id"],
            name="fk_reconciliation_jobs_space_source_operation",
        ),
        ForeignKeyConstraint(
            ["space_id", "reconcile_operation_id"],
            ["release_operations.space_id", "release_operations.id"],
            name="fk_reconciliation_jobs_space_reconcile_operation",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_reconciliation_jobs_status",
        ),
        Index("ix_reconciliation_jobs_status", "space_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_reconciliation_jobs_space")
    )
    source_operation_id: Mapped[str] = mapped_column(String(36))
    source_plan_digest: Mapped[str] = mapped_column(String(64))
    reconcile_operation_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    last_error: Mapped[str | None] = mapped_column(Text)


class SourceHead(TimestampMixin, Base):
    """Durable current lifecycle position for one Space-scoped source (021 L2)."""

    __tablename__ = "source_heads"
    __table_args__ = (
        UniqueConstraint(
            "space_id", "knowledge_id", name="uq_source_heads_space_knowledge"
        ),
        UniqueConstraint(
            "space_id",
            "tenant_id",
            "raw_kb_id",
            "knowledge_id",
            name="uq_source_heads_scoped_source",
        ),
        ForeignKeyConstraint(
            ["space_id", "tenant_id", "raw_kb_id"],
            ["knowledge_spaces.id", "knowledge_spaces.tenant_id", "knowledge_spaces.raw_kb_id"],
            name="fk_source_heads_scope_raw",
        ),
        ForeignKeyConstraint(
            ["space_id", "knowledge_id", "last_event_id"],
            ["source_events.space_id", "source_events.knowledge_id", "source_events.id"],
            name="fk_source_heads_last_event",
            use_alter=True,
        ),
        CheckConstraint(
            "(ordering_kind = 'processed_at' "
            "AND ordering_processed_at IS NOT NULL AND ordering_generation IS NULL) "
            "OR (ordering_kind = 'generation' "
            "AND ordering_processed_at IS NULL AND ordering_generation >= 0)",
            name="ck_source_heads_ordering_shape",
        ),
        CheckConstraint(
            "state IN ('active', 'deleted')", name="ck_source_heads_state"
        ),
        CheckConstraint("version >= 1", name="ck_source_heads_version"),
        Index("ix_source_heads_scope_state", "space_id", "state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(String(36))
    tenant_id: Mapped[str] = mapped_column(String(255))
    raw_kb_id: Mapped[str] = mapped_column(String(255))
    knowledge_id: Mapped[str] = mapped_column(String(255))
    head_revision: Mapped[str] = mapped_column(String(64))
    ordering_kind: Mapped[str] = mapped_column(String(16))
    ordering_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ordering_generation: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, default=1)
    last_event_id: Mapped[str | None] = mapped_column(String(36))
    actor: Mapped[str] = mapped_column(String(128))
    head_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceEvent(Base):
    """Append-only input and decision ledger for one SourceHead (021 L2)."""

    __tablename__ = "source_events"
    __table_args__ = (
        UniqueConstraint(
            "space_id", "knowledge_id", "id", name="uq_source_events_source_id"
        ),
        ForeignKeyConstraint(
            ["space_id", "tenant_id", "raw_kb_id"],
            ["knowledge_spaces.id", "knowledge_spaces.tenant_id", "knowledge_spaces.raw_kb_id"],
            name="fk_source_events_scope_raw",
        ),
        ForeignKeyConstraint(
            ["space_id", "tenant_id", "raw_kb_id", "knowledge_id"],
            [
                "source_heads.space_id",
                "source_heads.tenant_id",
                "source_heads.raw_kb_id",
                "source_heads.knowledge_id",
            ],
            name="fk_source_events_scoped_head",
        ),
        ForeignKeyConstraint(
            ["space_id", "change_set_id"],
            ["change_sets.space_id", "change_sets.id"],
            name="fk_source_events_space_change_set",
        ),
        ForeignKeyConstraint(
            ["change_set_id", "tombstone_change_item_id"],
            ["change_items.change_set_id", "change_items.id"],
            name="fk_source_events_tombstone_item",
        ),
        CheckConstraint(
            "(ordering_kind = 'processed_at' "
            "AND ordering_processed_at IS NOT NULL AND ordering_generation IS NULL) "
            "OR (ordering_kind = 'generation' "
            "AND ordering_processed_at IS NULL AND ordering_generation >= 0)",
            name="ck_source_events_ordering_shape",
        ),
        CheckConstraint(
            "desired_state IN ('active', 'deleted')",
            name="ck_source_events_desired_state",
        ),
        CheckConstraint(
            "decision IN ('accepted_create', 'accepted_advance', "
            "'accepted_delete', 'accepted_reactivate', 'idempotent', "
            "'stale', 'blocked_deleted')",
            name="ck_source_events_decision",
        ),
        CheckConstraint(
            "tombstone_change_item_id IS NULL OR change_set_id IS NOT NULL",
            name="ck_source_events_tombstone_link",
        ),
        Index(
            "ix_source_events_source_time",
            "space_id",
            "knowledge_id",
            "decided_at",
        ),
        Index(
            "ix_source_events_scope_decision", "space_id", "decision", "decided_at"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(String(36))
    tenant_id: Mapped[str] = mapped_column(String(255))
    raw_kb_id: Mapped[str] = mapped_column(String(255))
    knowledge_id: Mapped[str] = mapped_column(String(255))
    input_revision: Mapped[str] = mapped_column(String(64))
    ordering_kind: Mapped[str] = mapped_column(String(16))
    ordering_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ordering_generation: Mapped[int | None] = mapped_column(Integer)
    desired_state: Mapped[str] = mapped_column(String(16))
    decision: Mapped[str] = mapped_column(String(32))
    before_head: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_head: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    causation_id: Mapped[str | None] = mapped_column(String(255))
    actor: Mapped[str] = mapped_column(String(128))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    change_set_id: Mapped[str | None] = mapped_column(String(36))
    tombstone_change_item_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceLifecycleBackfillIssue(TimestampMixin, Base):
    """Durable unresolved ordering ambiguity; migration must never guess a head."""

    __tablename__ = "source_lifecycle_backfill_issues"
    __table_args__ = (
        UniqueConstraint(
            "space_id",
            "knowledge_id",
            name="uq_source_lifecycle_issues_space_knowledge",
        ),
        ForeignKeyConstraint(
            ["space_id", "tenant_id", "raw_kb_id"],
            ["knowledge_spaces.id", "knowledge_spaces.tenant_id", "knowledge_spaces.raw_kb_id"],
            name="fk_source_lifecycle_issues_scope_raw",
        ),
        CheckConstraint(
            "status IN ('open', 'resolved')",
            name="ck_source_lifecycle_issues_status",
        ),
        CheckConstraint(
            "(status = 'open' "
            "AND resolved_revision IS NULL AND resolved_ordering_kind IS NULL "
            "AND resolved_processed_at IS NULL AND resolved_generation IS NULL "
            "AND expected_state IS NULL AND resolved_by IS NULL "
            "AND resolution_reason IS NULL AND resolved_at IS NULL) "
            "OR (status = 'resolved' AND resolved_revision IS NOT NULL "
            "AND expected_state IN ('active', 'deleted') AND resolved_by IS NOT NULL "
            "AND resolution_reason IS NOT NULL AND resolved_at IS NOT NULL "
            "AND ((resolved_ordering_kind = 'processed_at' "
            "AND resolved_processed_at IS NOT NULL AND resolved_generation IS NULL) "
            "OR (resolved_ordering_kind = 'generation' "
            "AND resolved_processed_at IS NULL AND resolved_generation >= 0)))",
            name="ck_source_lifecycle_issues_resolution_shape",
        ),
        Index(
            "ix_source_lifecycle_issues_scope_status", "space_id", "status"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(String(36))
    tenant_id: Mapped[str] = mapped_column(String(255))
    raw_kb_id: Mapped[str] = mapped_column(String(255))
    knowledge_id: Mapped[str] = mapped_column(String(255))
    observed_revisions: Mapped[list[str]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")
    resolved_revision: Mapped[str | None] = mapped_column(String(64))
    resolved_ordering_kind: Mapped[str | None] = mapped_column(String(16))
    resolved_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_generation: Mapped[int | None] = mapped_column(Integer)
    expected_state: Mapped[str | None] = mapped_column(String(16))
    resolved_by: Mapped[str | None] = mapped_column(String(128))
    resolution_reason: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def _register_release_authority_guards() -> None:
    sqlite_guards: dict[Any, tuple[str, ...]] = {
        ReleaseManifestRecord.__table__: (
            """CREATE TRIGGER trg_release_manifests_update_guard_029
            BEFORE UPDATE ON release_manifests FOR EACH ROW
            BEGIN SELECT RAISE(ABORT, 'release manifests are immutable'); END""",
            """CREATE TRIGGER trg_release_manifests_delete_guard_029
            BEFORE DELETE ON release_manifests FOR EACH ROW
            BEGIN SELECT RAISE(ABORT, 'release manifests are immutable'); END""",
        ),
        ReleaseApproval.__table__: (
            """CREATE TRIGGER trg_release_approvals_update_guard_029
            BEFORE UPDATE ON release_approvals FOR EACH ROW
            BEGIN SELECT RAISE(ABORT, 'release approvals are append-only'); END""",
            """CREATE TRIGGER trg_release_approvals_delete_guard_029
            BEFORE DELETE ON release_approvals FOR EACH ROW
            BEGIN SELECT RAISE(ABORT, 'release approvals are append-only'); END""",
        ),
        ReleaseActivationAudit.__table__: (
            """CREATE TRIGGER trg_release_activation_audits_update_guard_029
            BEFORE UPDATE ON release_activation_audits FOR EACH ROW
            BEGIN SELECT RAISE(ABORT, 'release activation audits are append-only'); END""",
            """CREATE TRIGGER trg_release_activation_audits_delete_guard_029
            BEFORE DELETE ON release_activation_audits FOR EACH ROW
            BEGIN SELECT RAISE(ABORT, 'release activation audits are append-only'); END""",
        ),
        ReleaseAlert.__table__: (
            """CREATE TRIGGER trg_release_alerts_update_guard_029
            BEFORE UPDATE ON release_alerts FOR EACH ROW
            BEGIN SELECT RAISE(ABORT, 'release alerts are append-only'); END""",
            """CREATE TRIGGER trg_release_alerts_delete_guard_029
            BEFORE DELETE ON release_alerts FOR EACH ROW
            BEGIN SELECT RAISE(ABORT, 'release alerts are append-only'); END""",
        ),
    }
    for table, statements in sqlite_guards.items():
        for statement in statements:
            event.listen(
                table,
                "after_create",
                DDL(statement).execute_if(dialect="sqlite"),  # type: ignore[no-untyped-call]
            )

    postgres_guards: dict[Any, tuple[str, ...]] = {
        ReleaseManifestRecord.__table__: (
            """CREATE FUNCTION guard_release_manifests_immutable_029() RETURNS trigger
            LANGUAGE plpgsql AS $guard$ BEGIN
            RAISE EXCEPTION 'release manifests are immutable' USING ERRCODE = '23514';
            END; $guard$""",
            """CREATE TRIGGER trg_release_manifests_update_guard_029
            BEFORE UPDATE ON release_manifests FOR EACH ROW
            EXECUTE FUNCTION guard_release_manifests_immutable_029()""",
            """CREATE TRIGGER trg_release_manifests_delete_guard_029
            BEFORE DELETE ON release_manifests FOR EACH ROW
            EXECUTE FUNCTION guard_release_manifests_immutable_029()""",
        ),
        ReleaseApproval.__table__: (
            """CREATE FUNCTION guard_release_approvals_append_only_029() RETURNS trigger
            LANGUAGE plpgsql AS $guard$ BEGIN
            RAISE EXCEPTION 'release approvals are append-only' USING ERRCODE = '23514';
            END; $guard$""",
            """CREATE TRIGGER trg_release_approvals_update_guard_029
            BEFORE UPDATE ON release_approvals FOR EACH ROW
            EXECUTE FUNCTION guard_release_approvals_append_only_029()""",
            """CREATE TRIGGER trg_release_approvals_delete_guard_029
            BEFORE DELETE ON release_approvals FOR EACH ROW
            EXECUTE FUNCTION guard_release_approvals_append_only_029()""",
        ),
        ReleaseActivationAudit.__table__: (
            """CREATE FUNCTION guard_release_activation_audits_append_only_029()
            RETURNS trigger LANGUAGE plpgsql AS $guard$ BEGIN
            RAISE EXCEPTION 'release activation audits are append-only'
            USING ERRCODE = '23514'; END; $guard$""",
            """CREATE TRIGGER trg_release_activation_audits_update_guard_029
            BEFORE UPDATE ON release_activation_audits FOR EACH ROW
            EXECUTE FUNCTION guard_release_activation_audits_append_only_029()""",
            """CREATE TRIGGER trg_release_activation_audits_delete_guard_029
            BEFORE DELETE ON release_activation_audits FOR EACH ROW
            EXECUTE FUNCTION guard_release_activation_audits_append_only_029()""",
        ),
        ReleaseAlert.__table__: (
            """CREATE FUNCTION guard_release_alerts_append_only_029()
            RETURNS trigger LANGUAGE plpgsql AS $guard$ BEGIN
            RAISE EXCEPTION 'release alerts are append-only'
            USING ERRCODE = '23514'; END; $guard$""",
            """CREATE TRIGGER trg_release_alerts_update_guard_029
            BEFORE UPDATE ON release_alerts FOR EACH ROW
            EXECUTE FUNCTION guard_release_alerts_append_only_029()""",
            """CREATE TRIGGER trg_release_alerts_delete_guard_029
            BEFORE DELETE ON release_alerts FOR EACH ROW
            EXECUTE FUNCTION guard_release_alerts_append_only_029()""",
        ),
    }
    for table, statements in postgres_guards.items():
        for statement in statements:
            event.listen(
                table,
                "after_create",
                DDL(statement).execute_if(  # type: ignore[no-untyped-call]
                    dialect="postgresql"
                ),
            )


_register_release_authority_guards()
register_metadata_guards(Base.metadata)
