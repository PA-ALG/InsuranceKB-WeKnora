"""spec F6：族指纹修复——无标题文档 fallback（004 疑点 fam-e3b0c44298fc）。"""

from pathlib import Path

import pytest

from insurance_harness.compiler.sections import family_fingerprint, split_sections
from insurance_harness.goldenset.pdf import PageText, extract_pages

DATASET = Path(__file__).resolve().parents[2] / "dataset/shouxian_product"

EMPTY_SHA_FAMILY = "fam-e3b0c44298fc"  # 空串 sha256 前 12 位（F6.1 缺陷指纹）

RATE_PAGES = [
    PageText(
        page_no=1,
        text="《某某终身寿险》年交费率表\n（每万元基本保险金额）\n男性\n"
        "交费期间\n趸交 3年 6年 10年\n投保年龄\n0 100 50 30 20",
    ),
    PageText(page_no=2, text="女性\n交费期间\n趸交 3年 6年 10年\n投保年龄\n0 99 49 29 19"),
]
BROCHURE_PAGES = [
    PageText(
        page_no=i,
        text=("某某终身寿险产品说明书\n" if i == 1 else "") + "在本说明书中提供保障介绍。",
    )
    for i in range(1, 8)
]


def test_f6_2_headless_doc_no_longer_empty_sha() -> None:
    fp = family_fingerprint(split_sections(RATE_PAGES))
    assert fp.startswith("fam-") and fp != EMPTY_SHA_FAMILY
    assert family_fingerprint([]) != EMPTY_SHA_FAMILY  # 空文档也不得撞空串指纹


def test_f6_2_headless_docs_separate_by_doc_type() -> None:
    rate = family_fingerprint(split_sections(RATE_PAGES))
    brochure = family_fingerprint(split_sections(BROCHURE_PAGES))
    assert rate != brochure  # 费率表 ≠ 说明书（旧算法两者同为空串指纹）


def test_f6_2_same_layout_different_product_same_family() -> None:
    # 同版式不同产品名/数字：《》内容与数字不影响 fallback 指纹
    variant = [
        PageText(page_no=p.page_no, text=p.text.replace("某某", "另一产品").replace("100", "200"))
        for p in RATE_PAGES
    ]
    assert family_fingerprint(split_sections(RATE_PAGES)) == family_fingerprint(
        split_sections(variant)
    )


def test_f6_2_headed_docs_fingerprint_unchanged_from_004() -> None:
    """标题序列非空 → 算法与 004 完全一致（既有族 id 不漂移）。"""
    pages = [
        PageText(
            page_no=1,
            text="第一条 投保范围\n投保年龄为出生满30日至65周岁。\n第二条 犹豫期\n20日。",
        )
    ]
    import hashlib
    import re

    sections = split_sections(pages, target_chars=200, min_chars=0)
    titles = [h for s in sections for h in s.headings]
    assert titles  # 前置：有标题
    normalized = "\x00".join(re.sub(r"[\s0-9０-９]+", "", t) for t in titles)
    legacy = "fam-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    assert family_fingerprint(sections) == legacy


def test_f6_3_shengshijinyue_rate_tables_share_family_on_real_pdfs() -> None:
    products = [
        "平安盛世金越（尊享版26）终身寿险",
        "平安盛世金越（尊享版26）终身寿险（分红型）",
        "平安创享盛世金越（尊享版26）终身寿险（分红型）",
    ]
    if not all((DATASET / p / "费率表.pdf").exists() for p in products):
        pytest.skip(f"样本缺失：{DATASET}")
    rate_fams = {
        p: family_fingerprint(split_sections(extract_pages(DATASET / p / "费率表.pdf")))
        for p in products
    }
    assert len(set(rate_fams.values())) == 1, f"盛世金越 3 份费率表应同族：{rate_fams}"
    assert set(rate_fams.values()) != {EMPTY_SHA_FAMILY}
    # 说明书不得与费率表同族（F6.3）
    brochure = family_fingerprint(
        split_sections(extract_pages(DATASET / products[0] / "产品说明书.pdf"))
    )
    assert brochure not in set(rate_fams.values())


def test_f6_3_headed_terms_fingerprints_match_004_manifest() -> None:
    """有标题文档（条款）指纹与 004 run manifest 记录一致（回归锚点）。"""
    expected = {
        "平安盛世金越（尊享版26）终身寿险": "fam-e460ade8ea5a",
        "平安守护百分百（2026）两全保险": "fam-7e3de45515c1",
    }
    for product, fam in expected.items():
        pdf = DATASET / product / "保险条款.pdf"
        if not pdf.exists():
            pytest.skip(f"样本缺失：{pdf}")
        assert family_fingerprint(split_sections(extract_pages(pdf))) == fam
