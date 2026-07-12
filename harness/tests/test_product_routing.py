"""P4：产品路由——exact/alias/fuzzy 分级、歧义与 fuzzy 不自动归属、一对多章节路由（T6）。"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from insurance_harness.db.models import InsuranceProduct, ProductAlias, UnassignedItem
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.product.aliases import generate_aliases
from insurance_harness.product.routing import (
    MatchIndex,
    ProductCandidate,
    Section,
    persist_unassigned,
    route_document,
    route_sections,
)

HARNESS_ROOT = Path(__file__).resolve().parents[1]

# 镜像真实数据集里的包含歧义：非分红名是分红名的前缀；两产品共享短别名"盛世金越（尊享版26）"
PRODUCT_A = (
    "1824",
    "平安盛世金越（尊享版26）终身寿险",
    "平保寿发〔2025〕366号",
    "平安人寿〔2025〕终身寿险150号",
)
PRODUCT_B = ("1825", "平安盛世金越（尊享版26）终身寿险（分红型）", "平保寿发〔2025〕401号", None)
PRODUCT_C = ("1820", "平安福满分（2026）养老年金保险", "平保寿发〔2026〕88号", None)


@pytest.fixture()
def session(tmp_path: Path) -> Session:
    url = f"sqlite:///{tmp_path}/routing.db"
    cfg = Config(str(HARNESS_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(HARNESS_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    s = Session(create_engine(url))
    for code, name, filing, sccode in (PRODUCT_A, PRODUCT_B, PRODUCT_C):
        product = InsuranceProduct(
            product_code=code, canonical_name=name, category="whole-life", status="在售",
            filing_no=filing,
        )
        s.add(product)
        s.flush()
        for alias, alias_type in generate_aliases(name):
            s.add(ProductAlias(product_id=product.id, alias=alias, alias_type=alias_type))
        if sccode:
            s.add(ProductAlias(product_id=product.id, alias=sccode, alias_type="registration_no"))
    s.commit()
    return s


@pytest.fixture()
def index(session: Session) -> MatchIndex:
    return MatchIndex.from_session(session)


def _pages(*texts: str) -> list[PageText]:
    return [PageText(page_no=i, text=t) for i, t in enumerate(texts, start=1)]


def _by_code(result_candidates: tuple[ProductCandidate, ...], code: str) -> ProductCandidate:
    return next(c for c in result_candidates if c.product_code == code)


# --- P4.1/P4.2 exact ---


def test_exact_by_filing_no(index: MatchIndex) -> None:
    result = route_document(index, "doc", _pages("备案编号：平保寿发〔2025〕366号 特此说明"))
    assert [c.product_code for c in result.candidates] == ["1824"]
    c = result.candidates[0]
    assert c.confidence == "exact" and "备案文号" in c.basis
    assert not result.unassigned


def test_exact_by_registration_no(index: MatchIndex) -> None:
    result = route_document(index, "doc", _pages("注册号 平安人寿〔2025〕终身寿险150号"))
    assert [c.product_code for c in result.candidates] == ["1824"]
    assert result.candidates[0].confidence == "exact"


def test_exact_by_product_code_word_boundary(index: MatchIndex) -> None:
    result = route_document(index, "doc", _pages("产品代码：1824。"))
    assert [c.product_code for c in result.candidates] == ["1824"]
    # 词边界：18240 不得命中 1824
    result2 = route_document(index, "doc", _pages("工号 18240 与产品无关，无其他线索"))
    assert not any(c.product_code == "1824" for c in result2.candidates)


def test_exact_full_name_longest_first(index: MatchIndex) -> None:
    """B 的全名以 A 的全名为前缀：出现 B 全名时只归 B，不得同时错挂 A。"""
    result = route_document(
        index, "doc", _pages("平安盛世金越（尊享版26）终身寿险（分红型）条款目录……")
    )
    exact_codes = {c.product_code for c in result.candidates if c.confidence == "exact"}
    assert "1825" in exact_codes
    assert "1824" not in exact_codes


# --- P4.2 alias / 歧义 / fuzzy ---


def test_alias_unique_hit(index: MatchIndex) -> None:
    result = route_document(index, "doc", _pages("推荐产品：福满分（2026）养老年金保险，收益稳健"))
    c = _by_code(result.candidates, "1820")
    assert c.confidence == "alias" and "别名命中" in c.basis


def test_ambiguous_alias_goes_unassigned_not_auto(index: MatchIndex) -> None:
    """短别名"盛世金越（尊享版26）"映射 A/B 两产品 → 不自动归属，带候选进 unassigned。"""
    result = route_document(index, "doc", _pages("盛世金越（尊享版26）值得购买吗？"))
    assert result.candidates == ()
    assert len(result.unassigned) == 1
    draft = result.unassigned[0]
    assert "别名歧义" in draft.reason
    assert {c.product_code for c in draft.candidates} == {"1824", "1825"}
    assert all(c.confidence == "alias" for c in draft.candidates)


def test_fuzzy_never_auto_assigned(index: MatchIndex) -> None:
    result = route_document(index, "doc", _pages("这是一段与既有产品只有微弱相似度的营销文案。"))
    assert result.candidates == ()  # fuzzy 一律不产出正式归属
    assert len(result.unassigned) == 1
    draft = result.unassigned[0]
    assert draft.reason == "无 exact/alias 命中"
    assert all(c.confidence == "fuzzy" for c in draft.candidates)


# --- P4.3 一对多（含 T6 拼接多产品文档） ---


def test_multi_product_document_one_to_many(index: MatchIndex) -> None:
    result = route_document(
        index,
        "doc",
        _pages(
            "第一部分 平安盛世金越（尊享版26）终身寿险 条款",
            "第二部分 平安福满分（2026）养老年金保险 条款",
        ),
    )
    codes = {c.product_code: c for c in result.candidates}
    assert set(codes) == {"1824", "1820"}
    assert codes["1824"].page_first == 1 and codes["1820"].page_first == 2


def test_t6_concatenated_sections_route_and_unassigned(index: MatchIndex) -> None:
    """T6：拼接文档分章节路由——各章节归对，混淆章节进 unassigned 而非错挂。"""
    sections = [
        Section(
            section_ref="s1-终身寿险条款",
            pages=(
                PageText(
                    page_no=1,
                    text="平安盛世金越（尊享版26）终身寿险\n备案：平保寿发〔2025〕366号",
                ),
            ),
        ),
        Section(
            section_ref="s2-年金条款",
            pages=(PageText(page_no=5, text="平安福满分（2026）养老年金保险 保险条款"),),
        ),
        Section(
            section_ref="s3-混淆章节",
            pages=(PageText(page_no=9, text="盛世金越（尊享版26）产品对比与购买建议"),),
        ),
    ]
    result = route_sections(index, "concat.pdf", sections)

    by_section = {c.section_ref: c for c in result.candidates}
    assert by_section["s1-终身寿险条款"].product_code == "1824"
    assert by_section["s1-终身寿险条款"].confidence == "exact"
    assert by_section["s2-年金条款"].product_code == "1820"
    # 混淆章节：不出现在正式归属里，进 unassigned 并带双候选
    assert "s3-混淆章节" not in by_section
    assert len(result.unassigned) == 1
    draft = result.unassigned[0]
    assert draft.section_ref == "s3-混淆章节"
    assert {c.product_code for c in draft.candidates} == {"1824", "1825"}


# --- P4.4 unassigned 池表 ---


def test_p4_4_persist_unassigned_pool(session: Session, index: MatchIndex) -> None:
    result = route_document(index, "doc.pdf", _pages("盛世金越（尊享版26）怎么样"))
    n = persist_unassigned(session, result.unassigned)
    session.commit()
    assert n == 1
    row = session.execute(select(UnassignedItem)).scalar_one()
    assert row.doc_ref == "doc.pdf" and row.status == "open"
    assert row.candidates and {c["product_code"] for c in row.candidates} == {"1824", "1825"}
    assert session.scalar(select(func.count()).select_from(UnassignedItem)) == 1
