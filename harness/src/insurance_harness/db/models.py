"""产品域 ORM（docs/insurance-kb/03-knowledge-model.md §2.2/§8 的产品子集）。

命名对照（03 §8 为权威）：
- ``product_code``  ← product_meta.json 的 ``planCode``（业务键，唯一）
- ``version_label`` ← ``versionNo``
- ``filing_no``     ← ``reportPreparedFileCode``（备案文号）
- 注册号 ``sccode`` 不单设列，落 ``product_aliases``（alias_type=registration_no），
  作为路由 exact 依据之一。
表结构变更必须先修订文档 03 再改此处与迁移。
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from insurance_harness.db.base import Base, utcnow


def _uuid() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class KnowledgeSpace(TimestampMixin, Base):
    __tablename__ = "knowledge_spaces"
    __table_args__ = (
        CheckConstraint(
            "(binding_status = 'unbound' "
            "AND tenant_id IS NULL AND raw_kb_id IS NULL AND wiki_kb_id IS NULL) "
            "OR (binding_status = 'bound' "
            "AND tenant_id IS NOT NULL AND raw_kb_id IS NOT NULL AND wiki_kb_id IS NOT NULL)",
            name="ck_knowledge_spaces_binding_shape",
        ),
        UniqueConstraint(
            "tenant_id", "raw_kb_id", name="uq_knowledge_spaces_tenant_raw_kb"
        ),
        UniqueConstraint(
            "tenant_id", "wiki_kb_id", name="uq_knowledge_spaces_tenant_wiki_kb"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str | None] = mapped_column(String(255))
    raw_kb_id: Mapped[str | None] = mapped_column(String(255))
    wiki_kb_id: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    binding_status: Mapped[str] = mapped_column(String(16))


class InsuranceProduct(TimestampMixin, Base):
    __tablename__ = "insurance_products"
    __table_args__ = (
        UniqueConstraint("space_id", "product_code", name="uq_product_code"),
        UniqueConstraint("space_id", "id", name="uq_insurance_products_space_id"),
        Index("ix_products_name", "canonical_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_insurance_products_space")
    )
    product_code: Mapped[str] = mapped_column(String(64))
    canonical_name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(32))  # schema 注册表 line_key
    status: Mapped[str] = mapped_column(String(32))  # 在售/停售/归档
    filing_no: Mapped[str | None] = mapped_column(String(128))
    owner: Mapped[str | None] = mapped_column(String(128))
    # meta 原始快照与未建模字段（planPlanType/productLevel/渠道原文等）
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class ProductAlias(TimestampMixin, Base):
    __tablename__ = "product_aliases"
    __table_args__ = (
        UniqueConstraint("product_id", "alias", name="uq_alias_per_product"),
        Index("ix_aliases_alias", "alias"),
        Index("ix_aliases_product", "product_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    product_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("insurance_products.id")
    )
    alias: Mapped[str] = mapped_column(String(255))
    # no_paren / no_prefix / short / registration_no / manual
    alias_type: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(64), default="auto")


class ProductVersion(TimestampMixin, Base):
    __tablename__ = "product_versions"
    __table_args__ = (
        UniqueConstraint(
            "space_id", "product_id", "version_label", name="uq_version_per_product"
        ),
        UniqueConstraint("space_id", "id", name="uq_product_versions_space_id"),
        ForeignKeyConstraint(
            ["space_id", "product_id"],
            ["insurance_products.space_id", "insurance_products.id"],
            name="fk_product_versions_space_product",
        ),
        Index("ix_version_effective", "product_id", "effective_from"),
        Index("ix_versions_product", "product_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_product_versions_space")
    )
    product_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("insurance_products.id")
    )
    version_label: Mapped[str] = mapped_column(String(64))
    terms_revision: Mapped[str | None] = mapped_column(String(64))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    channels: Mapped[list[str] | None] = mapped_column(JSON)
    regions: Mapped[list[str] | None] = mapped_column(JSON)


class ProductDocument(TimestampMixin, Base):
    __tablename__ = "product_documents"
    __table_args__ = (
        UniqueConstraint(
            "space_id", "product_id", "sha256", name="uq_doc_sha_per_product"
        ),
        ForeignKeyConstraint(
            ["space_id", "product_id"],
            ["insurance_products.space_id", "insurance_products.id"],
            name="fk_product_documents_space_product",
        ),
        ForeignKeyConstraint(
            ["space_id", "version_id"],
            ["product_versions.space_id", "product_versions.id"],
            name="fk_product_documents_space_version",
        ),
        Index("ix_documents_product", "product_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_product_documents_space")
    )
    product_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("insurance_products.id")
    )
    version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("product_versions.id"))
    file_name: Mapped[str] = mapped_column(String(255))
    doc_type: Mapped[str] = mapped_column(String(32))  # DocumentType 值
    sha256: Mapped[str] = mapped_column(String(64))
    source_path: Mapped[str] = mapped_column(String(1024))


class UnassignedItem(TimestampMixin, Base):
    """归属失败的候选（03 §8 unassigned_pool）：fuzzy/同分候选禁止自动路由。"""

    __tablename__ = "unassigned_pool"
    __table_args__ = (Index("ix_unassigned_status", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_unassigned_pool_space")
    )
    doc_ref: Mapped[str] = mapped_column(String(1024))
    section_ref: Mapped[str | None] = mapped_column(String(255))
    excerpt: Mapped[str] = mapped_column(Text)
    candidates: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="open")
