"""spec E2.1/E2.2：章节切分保页码映射、组路由压缩比、文档族指纹（11 §1.1）。"""

from pathlib import Path

import pytest

from insurance_harness.compiler.sections import (
    family_fingerprint,
    route_groups,
    split_sections,
)
from insurance_harness.goldenset.pdf import PageText, extract_pages

DATASET = Path(__file__).resolve().parents[2] / "dataset/shouxian_product"

PAGES = [
    PageText(
        page_no=1,
        text="平安测试终身寿险\n第一条 投保范围\n投保年龄为出生满30日至65周岁，保险期间为终身。\n"
        "第二条 犹豫期\n自签收本合同之日起20日内为犹豫期，犹豫期内投保人可解除合同。",
    ),
    PageText(
        page_no=2,
        text="第三条 保险责任\n被保险人身故，按基本保险金额给付身故保险金。\n"
        "第四条 责任免除\n因下列情形之一身故的，我们不承担给付保险金责任。",
    ),
]


def test_e2_1_sections_keep_page_mapping() -> None:
    sections = split_sections(PAGES, target_chars=200, min_chars=0)
    assert len(sections) >= 4
    # 每个片段带原始页码；跨页章节的页码映射不丢
    for sec in sections:
        for frag in sec.fragments:
            assert frag.page_no in (1, 2)
    by_title = {s.title[:8]: s for s in sections}
    assert any("犹豫期" in s.title for s in sections)
    hesitation = next(s for s in sections if "犹豫期" in s.title)
    assert hesitation.page_first == 1 and hesitation.page_last == 1
    exclusion = next(s for s in sections if "责任免除" in s.title)
    assert exclusion.page_first == 2
    assert by_title  # 章节标题保留（族指纹的输入）


def test_e2_1_oversized_block_split_keeps_pages() -> None:
    long_pages = [PageText(page_no=7, text="第一条 总则\n" + "很长的内容。" * 500)]
    sections = split_sections(long_pages, target_chars=800, min_chars=0)
    assert len(sections) > 1  # 超长块被硬切
    assert all(f.page_no == 7 for s in sections for f in s.fragments)
    assert sum(s.char_count for s in sections) == len(long_pages[0].text)


def test_family_fingerprint_same_structure_same_family() -> None:
    fp1 = family_fingerprint(split_sections(PAGES, target_chars=200, min_chars=0))
    # 同版式、不同数字（条款序号/年份变化）→ 同族
    pages_variant = [
        PageText(page_no=p.page_no, text=p.text.replace("2026", "2027")) for p in PAGES
    ]
    fp2 = family_fingerprint(split_sections(pages_variant, target_chars=200, min_chars=0))
    assert fp1 == fp2 and fp1.startswith("fam-")
    # 结构不同 → 不同族
    other = [PageText(page_no=1, text="第一章 释义\n恶性肿瘤指……\n第二章 理赔\n申请材料……")]
    fp3 = family_fingerprint(split_sections(other, target_chars=200, min_chars=0))
    assert fp3 != fp1


@pytest.mark.parametrize(
    "product",
    [
        "平安盛世金越（尊享版26）终身寿险",
        "平安附加（2026）失能收入损失保险",
        "平安e生保（尊享版）医疗保险",
    ],
)
def test_e2_2_routing_compression_le_40_percent_on_sample_terms(product: str) -> None:
    """样本条款文档：路由后 (组×章节) 数 ≤ 全量组合的 40%（实际值记入 validation-report）。"""
    pdf = DATASET / product / "保险条款.pdf"
    if not pdf.exists():
        pytest.skip(f"样本缺失：{pdf}")
    sections = split_sections(extract_pages(pdf))
    routing = route_groups(sections)
    assert routing.total_pairs == 7 * len(sections)
    assert routing.compression_ratio <= 0.40, (
        f"{product} 压缩比 {routing.compression_ratio:.3f} 超过 40%"
    )
    # coverage 扫描全部章节
    assert len(routing.by_group["coverage"]) == len(sections)


def test_e2_2_irrelevant_sections_not_routed() -> None:
    """无关章节不得进入该组调用：疾病释义关键词密集段不应进 contract_admin。"""
    disease = PageText(
        page_no=1,
        text="第一章 疾病释义\n恶性肿瘤指恶性细胞不受控制的进行性增长。重大器官移植术指……\n"
        "急性心肌梗死指……脑中风后遗症指……严重恶性肿瘤的释义与定义以此为准。轻症疾病定义……",
    )
    sections = split_sections([disease], target_chars=2000, min_chars=0)
    routing = route_groups(sections)
    assert routing.by_group["disease_definition"]  # 正确归组
    assert not routing.by_group["contract_admin"]  # 无关组不路由
