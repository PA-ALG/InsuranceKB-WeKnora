"""S5b-7 acceptance (protected, written by Claude): a product name printed anywhere on page 1.

Spec docs/design/slices/S5b-7-正文中的标题行与旧问题重判.md §2. The heads are synthetic but keep the
structure the content stream gives real on-sale materials (public product names): a rate table's
title line comes after its table, a brochure may open with the insurer above a title split in two,
and a terms may carry blank 险种简称/险种代码 labels before its reader guide.
"""

import json

import pytest

from insurance_harness.identity.attribution import (
    Attribution,
    AttributionPolicy,
    RegisteredProduct,
    Upload,
    attribute,
    load_attribution_policy,
)

MEDICAL = "平安e无忧优享版长期医疗保险（费率可调）"
ENDOWMENT = "平安盈添悦两全保险（分红型）"
NURSING = "平安创智盈倍护（2026）终身护理保险"
ACCIDENT = "平安畅行意外伤害保险"
ACCIDENT_MEDICAL = "平安意外（A款）医疗保险"


def product(product_id: str, name: str, code: str, pack: str) -> RegisteredProduct:
    return RegisteredProduct(
        product_id=product_id, names=(name,), clause_codes=(code,), schema_pack_id=pack
    )


REGISTRY = [
    product("sc-med", MEDICAL, "平安人寿〔2025〕医疗保险301号", "schemapack_medical_insurance"),
    product("sc-end", ENDOWMENT, "平安人寿〔2025〕两全保险302号", "schemapack_endowment_insurance"),
    product(
        "sc-nur", NURSING, "平安人寿〔2025〕护理保险303号", "schemapack_nursing_care_insurance"
    ),
    product(
        "sc-acc", ACCIDENT, "平安人寿〔2025〕意外伤害保险304号", "schemapack_accident_insurance"
    ),
    product(
        "sc-am",
        ACCIDENT_MEDICAL,
        "平安人寿〔2025〕意外伤害保险305号",
        "schemapack_accident_medical_insurance",
    ),
]


def judged(head: str, file_name: str) -> Attribution:
    upload = Upload(knowledge_id="k-1", file_name=file_name, sha256="a" * 64, head=head)
    return attribute(upload, REGISTRY)


def rate_table(*title_lines: str) -> str:
    """Rows first, the title after them, page 2 the same: the order the content stream gives."""
    rows = "\r\n".join(f"{age} {795 - age} {1690 + age}" for age in range(30))
    page = "有基本医疗保险或公费医疗 无基本医疗保险或公费医疗\r\n" + rows + "\r\n"
    return page + "\r\n".join(title_lines) + "\r\n单位：人民币元\n" + page + title_lines[-1]


# 1. A title line anywhere confirms the registered product it names (Spec §2.3) ------------------


@pytest.mark.parametrize(
    ("line", "product_id"),
    [
        (f"《{MEDICAL}》年交费率表", "sc-med"),
        (f"《{ENDOWMENT}》基本保险金额表", "sc-end"),
        (f"《{NURSING}》年交费率表", "sc-nur"),
        (f"《{ACCIDENT}》费率表", "sc-acc"),
    ],
)
def test_a_rate_table_title_after_its_table_attaches_it(line: str, product_id: str) -> None:
    result = judged(rate_table(line), "费率表.pdf")
    assert (result.outcome, result.reason, result.product_id, result.role) == (
        "SUPPLEMENT",
        "matched_by_name",
        product_id,
        "rate_table",
    )
    assert result.policy_ref == "attribution-policy@2026-11-01.7"  # PV-1, PV-3, SK-1 bumped it


def test_a_brochure_under_the_insurer_with_a_title_split_in_two_attaches_it() -> None:
    head = (
        "中国平安人寿保险股份有限公司\r\n《平安 e 无忧优享版长期医疗保险（费率可调）》\r\n"
        "产品说明书\r\n在本说明书中，“您”指投保人，“我们”、“本公司”均指中国平安人寿保险股份有限公司。"
    )
    result = judged(head, "产品说明书.pdf")
    assert (result.outcome, result.product_id, result.role) == ("SUPPLEMENT", "sc-med", "brochure")


def test_a_title_split_in_two_further_down_the_page_is_still_a_title() -> None:
    head = (
        "目录\r\n一、产品特色\r\n二、保险责任\r\n《平安盈添悦两全保险（分红型）》\r\n产品说明书\r\n"
        "在本说明书中，“您”指投保人。"
    )
    result = judged(head, "产品说明书.pdf")
    assert (result.outcome, result.product_id) == ("SUPPLEMENT", "sc-end")


# 2. Only whole title lines, and never a new product (Spec §2.3) ---------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "（2）计算上表所使用的发生率不超过《中国人身保险业经验生命表（2025）》非养老类业务二表男女表的100%；",
        f"投保人可同时投保《{ACCIDENT}》，费率表见下。",
        f"本表适用于《{MEDICAL}》年交费率表的续保情形",
    ],
)
def test_a_name_cited_inside_a_sentence_is_not_a_title(line: str) -> None:
    result = judged(rate_table(line), "费率表.pdf")
    assert (result.outcome, result.reason, result.product_id) == (
        "QUARANTINE",
        "no_product_anchor",
        None,
    )


def test_a_title_line_of_an_unregistered_product_neither_attaches_nor_creates() -> None:
    result = judged(rate_table("《平安福满分（2026）终身寿险》年交费率表"), "费率表.pdf")
    assert (result.outcome, result.reason) == ("QUARANTINE", "no_product_anchor")


def test_title_lines_of_two_registered_products_are_a_question() -> None:
    head = rate_table(f"《{MEDICAL}》年交费率表", f"《{ENDOWMENT}》基本保险金额表")
    result = judged(head, "费率表.pdf")
    assert (result.outcome, result.reason, result.candidates) == (
        "NEEDS_CONFIRM",
        "multiple_products",
        ("sc-end", "sc-med"),
    )


def test_title_lines_of_a_registered_and_an_unregistered_product_conflict() -> None:
    head = rate_table(f"《{MEDICAL}》年交费率表", "《平安福满分（2026）终身寿险》年交费率表")
    result = judged(head, "费率表.pdf")
    assert (result.outcome, result.reason, result.product_id) == (
        "QUARANTINE",
        "anchor_conflict",
        None,
    )


def test_another_products_brochure_filed_in_this_folder_stays_quarantined() -> None:
    head = (
        "平安附加学生门诊急诊医疗保险产品说明书\r\n在本说明书中，“您”指投保人，“我们”、“本公司”均指"
        "中国平安人寿保险股份有限公司。“合同”是指您与我们之间签订的平安附加门诊急诊医疗保险合同。"
    )
    result = judged(head, "产品说明书.pdf")
    assert (result.outcome, result.reason, result.product_id) == (
        "QUARANTINE",
        "no_product_anchor",
        None,
    )


def test_a_terms_is_never_attached_by_a_title_line() -> None:
    """Terms are identified by their own code and their start title or guide (S5b-5)."""
    head = (
        "阅读指引\r\n本条款的保险责任与责任免除请仔细阅读。\r\n"
        + rate_table(f"《{ACCIDENT}》费率表")
        + "\r\n平安人寿〔2025〕意外伤害保险399号\r\n请扫描以查询验证条款"
    )
    result = judged(head, "保险条款.pdf")
    assert (result.outcome, result.role, result.product_id) == ("QUARANTINE", "terms", None)


# 3. Blank labels are labels, so the reader guide names a new terms (Spec §2.2) -----------------


BLANK_LABELS = (
    "险种简称：\r\n险种代码：\r\n阅 读 指 引\r\n"
    "\uf043平安乐交通意外伤害保险产品提供意外伤残和意外身故保障\r\n"  # a font bullet, as extracted
    "例子：张先生（30 周岁）为自己投保了平安乐交通意外伤害保险。\r\n"
    "平安人寿〔2022〕意外伤害保险 039 号\r\n请扫描以查询验证条款\r\n平安乐交通意外伤害保险条款\r\n"
)


def test_a_terms_with_blank_labels_creates_its_product_from_the_guide() -> None:
    result = judged(BLANK_LABELS, "保险条款.pdf")
    assert (result.outcome, result.display_name, result.schema_pack_id, result.clause_code) == (
        "CREATE",
        "平安乐交通意外伤害保险",
        "schemapack_accident_insurance",
        "平安人寿〔2022〕意外伤害保险039号",
    )


def test_filled_labels_are_still_stripped() -> None:
    filled = BLANK_LABELS.replace("险种简称：", "险种简称：乐交通")
    head = filled.replace("险种代码：", "险种代码：1024")
    assert judged(head, "保险条款.pdf").display_name == "平安乐交通意外伤害保险"


# 4. The policy (Spec §2.1) ----------------------------------------------------------------------


def test_the_policy_carries_the_title_line_rule_and_the_insurer() -> None:
    policy = load_attribution_policy()
    assert policy.version == "2026-11-01.7"  # PV-1, PV-3, SK-1 bumped it after S5b-7
    assert policy.issuer_names == ("中国平安人寿保险股份有限公司",)
    for words in ("费率表", "成本表", "金额表", "说明书", "现金价值表"):
        assert words in policy.title_line_pattern
    data = json.loads(policy.model_dump_json())
    with pytest.raises(ValueError):  # every listed title line word has some text
        AttributionPolicy.model_validate_json(json.dumps(data | {"title_line_documents": [" "]}))
