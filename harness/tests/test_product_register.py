"""P2：产品注册幂等/更新/跳过。"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from insurance_harness.db.models import InsuranceProduct, ProductAlias, ProductDocument
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.product.register import register_products

HARNESS_ROOT = Path(__file__).resolve().parents[1]


def _meta(plan_code: str, name: str, status: str = "在售") -> dict[str, str]:
    return {
        "planCode": plan_code,
        "versionNo": f"{plan_code}-1",
        "clauseName": name,
        "planSalesStatus": status,
        "planSalesChannel": "个人代理、电话销售",
        "startDate": "2026-04-08",
        "reportPreparedFileCode": f"平保寿发〔2026〕{plan_code}号",
        "sccode": f"平安人寿〔2026〕年金保险{plan_code}号",
    }


@pytest.fixture()
def dataset(tmp_path: Path) -> Path:
    root = tmp_path / "products"
    p1 = root / "平安盛世金越养老年金保险（分红型）"
    p1.mkdir(parents=True)
    (p1 / "product_meta.json").write_text(
        json.dumps(_meta("1847H", "平安盛世金越养老年金保险（分红型）"), ensure_ascii=False)
    )
    (p1 / "保险条款.pdf").write_bytes(b"%PDF-terms")
    (p1 / "费率表.pdf").write_bytes(b"%PDF-rate")
    # .txt 变体（P2.1 兼容）
    p2 = root / "平安福满分（2026）养老年金保险"
    p2.mkdir()
    (p2 / "product_meta.txt").write_text(
        json.dumps(_meta("1820", "平安福满分（2026）养老年金保险"), ensure_ascii=False)
    )
    # 损坏 meta（P2.2 跳过）
    p3 = root / "坏产品"
    p3.mkdir()
    (p3 / "product_meta.json").write_text("{broken")
    return root


@pytest.fixture()
def session(tmp_path: Path) -> Session:
    url = f"sqlite:///{tmp_path}/reg.db"
    cfg = Config(str(HARNESS_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(HARNESS_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return Session(create_engine(url))


@pytest.fixture
def scope(bound_scope: Callable[..., KnowledgeScope]) -> KnowledgeScope:
    return bound_scope(
        tenant_id="tenant-product-register",
        raw_kb_id="raw-product-register",
        wiki_kb_id="wiki-product-register",
    )


def test_p2_register_idempotent_and_skip(
    dataset: Path, session: Session, scope: KnowledgeScope
) -> None:
    report1 = register_products(session, dataset, scope=scope)
    assert sorted(report1.created) == ["1820", "1847H"]
    assert len(report1.skipped) == 1 and "坏产品" in report1.skipped[0]

    n_products = session.scalar(
        select(func.count())
        .select_from(InsuranceProduct)
        .where(InsuranceProduct.space_id == scope.space_id)
    )
    n_docs = session.scalar(
        select(func.count())
        .select_from(ProductDocument)
        .where(ProductDocument.space_id == scope.space_id)
    )
    assert n_products == 2 and n_docs == 2

    # 幂等重跑：零新增
    report2 = register_products(session, dataset, scope=scope)
    assert report2.created == [] and report2.updated == []
    assert sorted(report2.unchanged) == ["1820", "1847H"]
    assert session.scalar(
        select(func.count())
        .select_from(InsuranceProduct)
        .where(InsuranceProduct.space_id == scope.space_id)
    ) == 2
    assert session.scalar(
        select(func.count())
        .select_from(ProductDocument)
        .where(ProductDocument.space_id == scope.space_id)
    ) == 2


def test_p2_update_changed_fields(
    dataset: Path, session: Session, scope: KnowledgeScope
) -> None:
    register_products(session, dataset, scope=scope)
    meta_path = dataset / "平安福满分（2026）养老年金保险" / "product_meta.txt"
    meta = _meta("1820", "平安福满分（2026）养老年金保险", status="停售")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False))

    report = register_products(session, dataset, scope=scope)
    assert report.updated == ["1820"]
    product = session.execute(
        select(InsuranceProduct).where(
            InsuranceProduct.space_id == scope.space_id,
            InsuranceProduct.product_code == "1820",
        )
    ).scalar_one()
    assert product.status == "停售"


def test_p2_3_aliases_include_registration_no(
    dataset: Path, session: Session, scope: KnowledgeScope
) -> None:
    register_products(session, dataset, scope=scope)
    aliases = {
        row.alias: row.alias_type
        for row in session.execute(
            select(ProductAlias)
            .join(InsuranceProduct)
            .where(InsuranceProduct.space_id == scope.space_id)
        ).scalars()
    }
    assert aliases.get("平安人寿〔2026〕年金保险1847H号") == "registration_no"
    assert "盛世金越养老年金保险" in aliases
