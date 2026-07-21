"""015 F2.1 实体对齐（复用 003 路由器）——question → AlignedEntity。

护栏成对（doc-21）：既测**对齐侧**（exact/alias 唯一命中 → 开单粒度），也测
**拒绝侧**（fuzzy/无命中/多产品歧义 → None，观察队列不开单，fail-safe 不误挂）。
只测拒绝侧或只测对齐侧都是半个护栏。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from insurance_harness.db.models import InsuranceProduct, ProductAlias
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.flywheel.align import align_question
from insurance_harness.product.aliases import generate_aliases
from insurance_harness.product.routing import MatchIndex

HARNESS_ROOT = Path(__file__).resolve().parents[1]

# 两个互不为子串的产品全名，便于构造 exact 命中与"两产品歧义"用例。
PRODUCT_A = ("1824", "平安盛世金越尊享版终身寿险", "平保寿发〔2025〕366号")
PRODUCT_B = ("1820", "平安福满分养老年金保险", "平保寿发〔2026〕88号")
ALIAS_A = "金越尊享"  # A 独有别名（非全名子串命中路径）
ALIAS_B = "福满分优选"  # B 独有别名（构造 A 全名 + B 别名 的跨层歧义用例）


@pytest.fixture()
def session(tmp_path: Path) -> Session:
    url = f"sqlite:///{tmp_path}/align.db"
    cfg = Config(str(HARNESS_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(HARNESS_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return Session(create_engine(url))


@pytest.fixture()
def scope(bound_scope: Callable[..., KnowledgeScope]) -> KnowledgeScope:
    return bound_scope(
        tenant_id="tenant-flywheel-align",
        raw_kb_id="raw-flywheel-align",
        wiki_kb_id="wiki-flywheel-align",
    )


@pytest.fixture()
def prod_ids(session: Session, scope: KnowledgeScope) -> dict[str, str]:
    ids: dict[str, str] = {}
    for key, (code, name, filing) in {"A": PRODUCT_A, "B": PRODUCT_B}.items():
        product = InsuranceProduct(
            space_id=scope.space_id,
            product_code=code,
            canonical_name=name,
            category="whole-life",
            status="在售",
            filing_no=filing,
        )
        session.add(product)
        session.flush()
        ids[key] = product.id
        for alias, alias_type in generate_aliases(name):
            session.add(ProductAlias(product_id=product.id, alias=alias, alias_type=alias_type))
    session.add(ProductAlias(product_id=ids["A"], alias=ALIAS_A, alias_type="short_name"))
    session.add(ProductAlias(product_id=ids["B"], alias=ALIAS_B, alias_type="short_name"))
    session.commit()
    return ids


@pytest.fixture()
def index(session: Session, scope: KnowledgeScope, prod_ids: dict[str, str]) -> MatchIndex:
    return MatchIndex.from_session(session, scope)


# --- 对齐侧 ---


def test_f2_1_exact_name_aligns_to_product(index: MatchIndex, prod_ids: dict[str, str]) -> None:
    entity = align_question(index, f"{PRODUCT_A[1]} 的等待期是多久？")
    assert entity is not None
    assert entity.product_id == prod_ids["A"]
    assert entity.field_id is None  # 未提供 field_names → 产品级缺口


def test_f2_1_unique_alias_aligns_to_product(index: MatchIndex, prod_ids: dict[str, str]) -> None:
    entity = align_question(index, f"{ALIAS_A} 这款保证续保吗？")
    assert entity is not None
    assert entity.product_id == prod_ids["A"]


def test_f2_1_field_name_attached_when_vocab_provided(
    index: MatchIndex, prod_ids: dict[str, str]
) -> None:
    entity = align_question(
        index,
        f"{PRODUCT_A[1]} 的等待期多少天？",
        field_names={"等待期": "waiting_period", "现金价值": "cash_value"},
    )
    assert entity is not None
    assert entity.product_id == prod_ids["A"]
    assert entity.field_id == "waiting_period"


def test_f2_1_field_name_longest_match_wins(
    index: MatchIndex, prod_ids: dict[str, str]
) -> None:
    # "基本保额" 与 "保额" 都在词表——最长优先，避免子串误配。
    entity = align_question(
        index,
        f"{PRODUCT_A[1]} 的基本保额是多少？",
        field_names={"保额": "sum_assured", "基本保额": "basic_sum_assured"},
    )
    assert entity is not None
    assert entity.field_id == "basic_sum_assured"


# --- 拒绝侧（fail-safe，观察队列不开单）---


def test_f2_1_two_products_is_ambiguous_returns_none(index: MatchIndex) -> None:
    # 同一问题命中两个产品全名 → 歧义，宁可不开单也不误挂到某一个。
    entity = align_question(index, f"{PRODUCT_A[1]} 和 {PRODUCT_B[1]} 哪个更划算？")
    assert entity is None


def test_f2_1_no_product_mention_returns_none(index: MatchIndex) -> None:
    # 无任何产品信号（fuzzy 也进 unassigned，不进 candidates）→ 观察队列不开单。
    entity = align_question(index, "这类保险的犹豫期一般是几天？")
    assert entity is None


def test_f2_1_mixed_exact_and_alias_two_products_returns_none(index: MatchIndex) -> None:
    # 红队#2：A 全名(exact) + B 唯一别名(alias) 同现 = 两产品歧义。
    # 不得因表面形式不同（一个用全名一个用别名）就绕过 fail-safe 误挂到 A。
    entity = align_question(index, f"{PRODUCT_A[1]} 和 {ALIAS_B} 哪个更划算？")
    assert entity is None


def test_f2_1_field_not_attached_from_product_name_substring(
    index: MatchIndex, prod_ids: dict[str, str]
) -> None:
    # 红队#1：字段名"养老"是产品全名"平安福满分养老年金保险"的子串——问题问的是续保，
    # 绝不能因产品名里含"养老"就误挂 field=养老。产品名表面串须先剔除再匹配字段。
    entity = align_question(
        index,
        f"{PRODUCT_B[1]} 的续保条件是什么？",
        field_names={"养老": "F_pension", "等待期": "F_wait"},
    )
    assert entity is not None
    assert entity.product_id == prod_ids["B"]
    assert entity.field_id is None


def test_f2_1_genuine_field_survives_product_name_scrub(
    index: MatchIndex, prod_ids: dict[str, str]
) -> None:
    # 剔除产品名不得误伤真实字段：问题正文里的"等待期"仍应命中。
    entity = align_question(
        index,
        f"{PRODUCT_B[1]} 的等待期是多少天？",
        field_names={"养老": "F_pension", "等待期": "F_wait"},
    )
    assert entity is not None
    assert entity.field_id == "F_wait"


def test_f2_1_field_survives_when_mentioned_outside_product_name(
    index: MatchIndex, prod_ids: dict[str, str]
) -> None:
    # 剔除只针对产品名整体 span——正文里独立出现的"养老金"仍应命中字段（不因产品名含"养老"而误删）。
    entity = align_question(
        index,
        f"{PRODUCT_B[1]} 的养老金什么时候能领？",
        field_names={"养老": "F_pension"},
    )
    assert entity is not None
    assert entity.field_id == "F_pension"
