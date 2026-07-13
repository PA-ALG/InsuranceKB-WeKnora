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

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from insurance_harness.db.base import Base, utcnow


def _uuid() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class InsuranceProduct(TimestampMixin, Base):
    __tablename__ = "insurance_products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    product_code: Mapped[str] = mapped_column(String(64), unique=True)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(32))  # schema 注册表 line_key
    status: Mapped[str] = mapped_column(String(32))  # 在售/停售/归档
    filing_no: Mapped[str | None] = mapped_column(String(128))
    owner: Mapped[str | None] = mapped_column(String(128))
    # meta 原始快照与未建模字段（planPlanType/productLevel/渠道原文等）
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class ProductAlias(TimestampMixin, Base):
    __tablename__ = "product_aliases"
    __table_args__ = (UniqueConstraint("product_id", "alias", name="uq_alias_per_product"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    product_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("insurance_products.id"), index=True
    )
    alias: Mapped[str] = mapped_column(String(255), index=True)
    # no_paren / no_prefix / short / registration_no / manual
    alias_type: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(64), default="auto")


class ProductVersion(TimestampMixin, Base):
    __tablename__ = "product_versions"
    __table_args__ = (
        UniqueConstraint("product_id", "version_label", name="uq_version_per_product"),
        Index("ix_version_effective", "product_id", "effective_from"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    product_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("insurance_products.id"), index=True
    )
    version_label: Mapped[str] = mapped_column(String(64))
    terms_revision: Mapped[str | None] = mapped_column(String(64))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    channels: Mapped[list[str] | None] = mapped_column(JSON)
    regions: Mapped[list[str] | None] = mapped_column(JSON)


class ProductDocument(TimestampMixin, Base):
    __tablename__ = "product_documents"
    __table_args__ = (UniqueConstraint("product_id", "sha256", name="uq_doc_sha_per_product"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    product_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("insurance_products.id"), index=True
    )
    version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("product_versions.id"))
    file_name: Mapped[str] = mapped_column(String(255))
    doc_type: Mapped[str] = mapped_column(String(32))  # DocumentType 值
    sha256: Mapped[str] = mapped_column(String(64))
    source_path: Mapped[str] = mapped_column(String(1024))


class UnassignedItem(TimestampMixin, Base):
    """归属失败的候选（03 §8 unassigned_pool）：fuzzy/同分候选禁止自动路由。"""

    __tablename__ = "unassigned_pool"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    doc_ref: Mapped[str] = mapped_column(String(1024))
    section_ref: Mapped[str | None] = mapped_column(String(255))
    excerpt: Mapped[str] = mapped_column(Text)
    candidates: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
