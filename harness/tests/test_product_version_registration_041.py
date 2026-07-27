"""OpenSpec 041: create-only ProductVersion authority anchor registration."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.models import InsuranceProduct, ProductVersion
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.product.register import register_products


def _scope(bound_scope: Callable[..., KnowledgeScope]) -> KnowledgeScope:
    return bound_scope(
        tenant_id="tenant-version-registration",
        raw_kb_id="raw-version-registration",
        wiki_kb_id="wiki-version-registration",
    )


def _write_product(
    root: Path,
    *,
    directory: str,
    plan_code: str,
    version_no: str,
    filing_no: str | None,
    registration_no: str | None,
) -> Path:
    product_dir = root / directory
    product_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, object] = {
        "planCode": plan_code,
        "versionNo": version_no,
        "clauseName": f"平安版本登记测试医疗保险{plan_code}",
        "planSalesStatus": "在售",
    }
    if filing_no is not None:
        meta["reportPreparedFileCode"] = filing_no
    if registration_no is not None:
        meta["sccode"] = registration_no
    product_dir.joinpath("product_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False),
        encoding="utf-8",
    )
    product_dir.joinpath("保险条款.pdf").write_bytes(
        f"%PDF-041-{plan_code}".encode()
    )
    return product_dir


def _load_version(
    session: Session,
    scope: KnowledgeScope,
    *,
    product_code: str,
) -> ProductVersion:
    version = session.scalar(
        select(ProductVersion)
        .join(InsuranceProduct, ProductVersion.product_id == InsuranceProduct.id)
        .where(
            ProductVersion.space_id == scope.space_id,
            InsuranceProduct.product_code == product_code,
        )
    )
    assert version is not None
    return version


def test_new_version_prefers_filing_number_over_registration_number(
    tmp_path: Path,
    session: Session,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = _scope(bound_scope)
    root = tmp_path / "products"
    _write_product(
        root,
        directory="filing-priority",
        plan_code="REG-041-A",
        version_no="REG-041-A-1",
        filing_no="备案-REG-041-A-1",
        registration_no="注册-REG-041-A-1",
    )

    register_products(session, root, scope=scope)

    assert (
        _load_version(session, scope, product_code="REG-041-A").terms_revision
        == "备案-REG-041-A-1"
    )


def test_new_version_uses_registration_number_when_filing_is_missing(
    tmp_path: Path,
    session: Session,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = _scope(bound_scope)
    root = tmp_path / "products"
    _write_product(
        root,
        directory="registration-fallback",
        plan_code="REG-041-B",
        version_no="REG-041-B-1",
        filing_no=None,
        registration_no="注册-REG-041-B-1",
    )

    register_products(session, root, scope=scope)

    assert (
        _load_version(session, scope, product_code="REG-041-B").terms_revision
        == "注册-REG-041-B-1"
    )


def test_existing_version_anchor_is_never_rewritten_or_backfilled(
    tmp_path: Path,
    session: Session,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = _scope(bound_scope)
    root = tmp_path / "products"
    filled_dir = _write_product(
        root,
        directory="filled",
        plan_code="REG-041-C",
        version_no="REG-041-C-1",
        filing_no="备案-REG-041-C-1",
        registration_no=None,
    )
    empty_dir = _write_product(
        root,
        directory="empty",
        plan_code="REG-041-D",
        version_no="REG-041-D-1",
        filing_no=None,
        registration_no=None,
    )
    register_products(session, root, scope=scope)

    filled = _load_version(session, scope, product_code="REG-041-C")
    empty = _load_version(session, scope, product_code="REG-041-D")
    assert filled.terms_revision == "备案-REG-041-C-1"
    assert empty.terms_revision is None

    for product_dir, new_filing in (
        (filled_dir, "备案-REG-041-C-CHANGED"),
        (empty_dir, "备案-REG-041-D-LATE"),
    ):
        meta_path = product_dir / "product_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["reportPreparedFileCode"] = new_filing
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    register_products(session, root, scope=scope)
    session.refresh(filled)
    session.refresh(empty)
    assert filled.terms_revision == "备案-REG-041-C-1"
    assert empty.terms_revision is None
