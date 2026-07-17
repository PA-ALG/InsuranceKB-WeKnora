"""产品注册服务（spec P2）：扫描产品目录 → 幂等 upsert 主数据/版本/文档/别名。"""

import hashlib
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.models import (
    InsuranceProduct,
    ProductAlias,
    ProductDocument,
    ProductVersion,
)
from insurance_harness.db.scope import KnowledgeScope, require_current_scope
from insurance_harness.product.aliases import generate_aliases
from insurance_harness.product.classify import DocumentType, detect_product_line
from insurance_harness.product.meta import MetaParseError, ProductMeta, load_product_meta

_FILENAME_DOC_TYPE: tuple[tuple[str, DocumentType], ...] = (
    ("条款", DocumentType.TERMS),
    ("说明书", DocumentType.BROCHURE),
    ("费率", DocumentType.RATE_TABLE),
)


class RegisterReport(BaseModel):
    created: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)  # "目录名: 原因"

    @property
    def summary(self) -> str:
        return (
            f"created={len(self.created)} updated={len(self.updated)} "
            f"unchanged={len(self.unchanged)} skipped={len(self.skipped)}"
        )


def _guess_doc_type(file_name: str) -> DocumentType:
    for keyword, doc_type in _FILENAME_DOC_TYPE:
        if keyword in file_name:
            return doc_type
    return DocumentType.UNKNOWN


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def register_products(
    session: Session, root: Path, *, scope: KnowledgeScope, commit: bool = True
) -> RegisterReport:
    """注册 meta 目录树。``commit=False`` 供调用方管理事务（010 dry-run 编排）。"""
    require_current_scope(session, scope)
    report = RegisterReport()
    for product_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            meta = load_product_meta(product_dir)
        except MetaParseError as exc:
            report.skipped.append(str(exc))
            continue
        _register_one(session, product_dir, meta, report, scope=scope)
    if commit:
        session.commit()
    return report


def _register_one(
    session: Session,
    product_dir: Path,
    meta: ProductMeta,
    report: RegisterReport,
    *,
    scope: KnowledgeScope,
) -> None:
    category = detect_product_line(meta.clause_name) or "unknown"
    raw_meta = meta.model_dump(mode="json", by_alias=True)

    product = session.execute(
        select(InsuranceProduct).where(
            InsuranceProduct.space_id == scope.space_id,
            InsuranceProduct.product_code == meta.plan_code,
        )
    ).scalar_one_or_none()

    created = product is None
    changed = False  # 任一实体层（产品主行/版本/文档/别名）产生副作用即为真
    if product is None:
        product = InsuranceProduct(
            space_id=scope.space_id,
            product_code=meta.plan_code,
            canonical_name=meta.clause_name,
            category=category,
            status=meta.sales_status,
            filing_no=meta.filing_no,
            meta=raw_meta,
        )
        session.add(product)
        session.flush()
    else:
        attrs_changed = False
        for attr, new in (
            ("canonical_name", meta.clause_name),
            ("category", category),
            ("status", meta.sales_status),
            ("filing_no", meta.filing_no),
        ):
            if getattr(product, attr) != new:
                setattr(product, attr, new)
                attrs_changed = True
        if attrs_changed:
            product.meta = raw_meta
            changed = True

    # 版本（UQ product_id+version_label 幂等）
    version = session.execute(
        select(ProductVersion).where(
            ProductVersion.space_id == scope.space_id,
            ProductVersion.product_id == product.id,
            ProductVersion.version_label == meta.version_no,
        )
    ).scalar_one_or_none()
    if version is None:
        version = ProductVersion(
            space_id=scope.space_id,
            product_id=product.id,
            version_label=meta.version_no,
            effective_from=meta.start_date,
            channels=meta.channels or None,
            regions=[meta.region_code] if meta.region_code else None,
        )
        session.add(version)
        session.flush()
        changed = True  # 新增版本是真实副作用（阻断3：不得报 unchanged）

    # 文档登记（UQ product_id+sha256 幂等）
    existing_sha = {
        row.sha256
        for row in session.execute(
            select(ProductDocument).where(
                ProductDocument.space_id == scope.space_id,
                ProductDocument.product_id == product.id,
            )
        ).scalars()
    }
    for pdf in sorted(product_dir.glob("*.pdf")):
        digest = _sha256(pdf)
        if digest in existing_sha:
            continue
        session.add(
            ProductDocument(
                space_id=scope.space_id,
                product_id=product.id,
                version_id=version.id,
                file_name=pdf.name,
                doc_type=_guess_doc_type(pdf.name).value,
                sha256=digest,
                source_path=str(pdf),
            )
        )
        changed = True  # 新增文档是真实副作用（阻断3）

    # 别名（确定性生成 + 注册号；UQ product_id+alias 幂等）
    existing_aliases = {
        row.alias
        for row in session.execute(
            select(ProductAlias).where(ProductAlias.product_id == product.id)
        ).scalars()
    }
    desired: list[tuple[str, str]] = generate_aliases(meta.clause_name)
    if meta.registration_no:
        desired.append((meta.registration_no, "registration_no"))
    for alias, alias_type in desired:
        if alias not in existing_aliases:
            session.add(
                ProductAlias(product_id=product.id, alias=alias, alias_type=alias_type)
            )
            changed = True  # 新增别名是真实副作用（阻断3）

    # 分类以**整体聚合**副作用为准，绝不以产品主行未变代理整个注册未变（阻断3）
    if created:
        report.created.append(meta.plan_code)
    elif changed:
        report.updated.append(meta.plan_code)
    else:
        report.unchanged.append(meta.plan_code)
