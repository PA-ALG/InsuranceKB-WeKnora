"""Change 016: product registration requires an explicit scope."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from insurance_harness.db.models import (
    InsuranceProduct,
    ProductDocument,
    ProductVersion,
)
from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
)
from insurance_harness.product.register import register_products


def _make_scope(
    factory: Callable[..., KnowledgeScope], suffix: str
) -> KnowledgeScope:
    return factory(
        tenant_id=f"tenant-{suffix}",
        raw_kb_id=f"raw-{suffix}",
        wiki_kb_id=f"wiki-{suffix}",
    )


@pytest.fixture
def product_root(tmp_path: Path) -> Path:
    root = tmp_path / "products"
    product = root / "跨空间同码产品"
    product.mkdir(parents=True)
    product.joinpath("product_meta.json").write_text(
        json.dumps(
            {
                "planCode": "SAME-001",
                "versionNo": "v1",
                "clauseName": "平安跨空间同码年金保险",
                "planSalesStatus": "在售",
                "reportPreparedFileCode": "备案-SAME-001",
                "sccode": "注册-SAME-001",
            },
            ensure_ascii=False,
        )
    )
    product.joinpath("保险条款.pdf").write_bytes(b"%PDF-scoped")
    return root


def test_register_same_product_code_is_idempotent_per_scope(
    session: Session,
    bound_scope: Callable[..., KnowledgeScope],
    product_root: Path,
) -> None:
    scope_a = _make_scope(bound_scope, "a")
    scope_b = _make_scope(bound_scope, "b")

    report_a = register_products(session, product_root, scope=scope_a)
    report_b = register_products(session, product_root, scope=scope_b)
    report_a_again = register_products(session, product_root, scope=scope_a)

    assert report_a.created == ["SAME-001"]
    assert report_b.created == ["SAME-001"]
    assert report_a_again.created == []
    assert report_a_again.unchanged == ["SAME-001"]

    products_a = session.scalars(
        select(InsuranceProduct).where(InsuranceProduct.space_id == scope_a.space_id)
    ).all()
    products_b = session.scalars(
        select(InsuranceProduct).where(InsuranceProduct.space_id == scope_b.space_id)
    ).all()
    assert [row.product_code for row in products_a] == ["SAME-001"]
    assert [row.product_code for row in products_b] == ["SAME-001"]
    assert products_a[0].id != products_b[0].id

    assert session.scalars(
        select(ProductVersion).where(ProductVersion.space_id == scope_a.space_id)
    ).one().space_id == scope_a.space_id
    assert session.scalars(
        select(ProductVersion).where(ProductVersion.space_id == scope_b.space_id)
    ).one().space_id == scope_b.space_id
    assert session.scalars(
        select(ProductDocument).where(ProductDocument.space_id == scope_a.space_id)
    ).one().space_id == scope_a.space_id
    assert session.scalars(
        select(ProductDocument).where(ProductDocument.space_id == scope_b.space_id)
    ).one().space_id == scope_b.space_id


def test_product_mutation_rejects_forged_matching_bound_scope_before_write(
    session: Session,
    bound_scope: Callable[..., KnowledgeScope],
    product_root: Path,
) -> None:
    loaded = _make_scope(bound_scope, "forged-product")
    forged = KnowledgeScope(**loaded.model_dump())
    before = session.scalar(select(func.count()).select_from(InsuranceProduct))

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        register_products(session, product_root, scope=forged)

    assert session.scalar(select(func.count()).select_from(InsuranceProduct)) == before
    assert session.is_active
