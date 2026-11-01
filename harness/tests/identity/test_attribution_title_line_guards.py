"""S5b-7 review R1–R2 (protected, written by Claude): what a title line may and may not do.

Spec docs/design/slices/S5b-7-正文中的标题行与旧问题重判.md §2.3. R1: after the bracketed name a
title line carries only listed words, so an explanation or a negation of the product is never its
title. R2: a title line adds role signals to the opening, it never pushes a conflicting one out.
"""

import pytest

from insurance_harness.identity.attribution import (
    Attribution,
    RegisteredProduct,
    Upload,
    attribute,
    load_attribution_policy,
)
from insurance_harness.identity.title_lines import line_titles

MEDICAL = "平安e无忧优享版长期医疗保险（费率可调）"
ENDOWMENT = "平安盈添悦两全保险（分红型）"
REGISTRY = [
    RegisteredProduct(
        product_id="sc-med",
        names=(MEDICAL,),
        clause_codes=("平安人寿〔2025〕医疗保险301号",),
        schema_pack_id="schemapack_medical_insurance",
    ),
    RegisteredProduct(
        product_id="sc-end",
        names=(ENDOWMENT,),
        clause_codes=("平安人寿〔2025〕两全保险302号",),
        schema_pack_id="schemapack_endowment_insurance",
    ),
]
ROWS = "投保年龄 有基本医疗保险或公费医疗 无基本医疗保险或公费医疗\r\n" + "\r\n".join(
    f"{age} {795 - age} {1690 + age}" for age in range(30)
)


def judged(head: str, file_name: str) -> Attribution:
    upload = Upload(knowledge_id="k-1", file_name=file_name, sha256="a" * 64, head=head)
    return attribute(upload, REGISTRY)


@pytest.mark.parametrize(
    "line",
    [
        f"《{MEDICAL}》不适用本费率表",
        f"《{MEDICAL}》并非本产品说明书",
        f"《{MEDICAL}》不属于本产品说明书",
        f"《{MEDICAL}》参照费率表",
        f"《{MEDICAL}》以外的费率表",
        f"《{MEDICAL}》的续保费率表",
    ],
)
def test_a_whole_line_explaining_or_negating_a_product_is_not_its_title(line: str) -> None:
    brochure = "在本说明书中，“您”指投保人。\r\n" + line + "\r\n正文"
    for head, file_name in ((ROWS + "\r\n" + line, "费率表.pdf"), (brochure, "产品说明书.pdf")):
        result = judged(head, file_name)
        assert result.product_id is None and result.outcome == "QUARANTINE", (line, file_name)


@pytest.mark.parametrize(
    "words",
    [
        "年交费率表",
        "费率表",
        "基本保险金额表",
        "基本部分年交费率表",
        "年保障成本表",
        "交清增额费率表",
    ],
)
def test_the_listed_qualifiers_found_on_real_rate_tables_still_make_a_title(words: str) -> None:
    result = judged(ROWS + f"\r\n《{ENDOWMENT}》{words}\r\n单位：人民币元", "费率表.pdf")
    attached = {("SUPPLEMENT", "sc-end"), ("NEEDS_CONFIRM", "sc-end")}  # 成本表: role is asked
    assert (result.outcome, result.product_id) in attached


@pytest.mark.parametrize("words", ["并非本产品说明书", "不适用本费率表"])
def test_a_bracketed_start_that_negates_the_product_is_no_title(words: str) -> None:
    head = f"《{MEDICAL}》{words}\r\n在本说明书中，“您”指投保人。"
    result = judged(head, "产品说明书.pdf")
    assert result.product_id is None and result.outcome == "QUARANTINE"


def test_a_bracketed_start_title_still_names_its_product() -> None:
    result = judged(f"《{MEDICAL}》产品说明书\r\n在本说明书中，“您”指投保人。", "产品说明书.pdf")
    assert (result.outcome, result.product_id) == ("SUPPLEMENT", "sc-med")


def test_an_excluded_word_inside_a_title_line_voids_it() -> None:
    pattern = load_attribution_policy().title_line_pattern
    head = "《甲乙保险》费率表\r\n"
    assert line_titles(head, pattern, (), str.strip) == {"甲乙保险": "《甲乙保险》费率表"}
    assert line_titles(head, pattern, ("甲乙",), str.strip) == {}


def test_a_title_line_never_pushes_a_conflicting_role_out_of_the_opening() -> None:
    """The opening names a brochure and, at about its 190th character, a rate table; the title line
    further down names a registered brochure. The conflict must stay a question about the role."""
    filler = "在本说明书中，“您”指投保人，“我们”指本公司。" * 8
    opening = filler[:186] + "费率表见附件"
    assert 180 < opening.index("费率表") < 200
    head = opening + f"\r\n正文\r\n《{MEDICAL}》产品说明书\r\n其余正文"
    result = judged(head, "产品说明书.pdf")
    assert (result.outcome, result.reason, result.candidates) == (
        "NEEDS_CONFIRM",
        "role_unresolved",
        ("sc-med",),
    )


def test_a_conflict_near_the_start_is_the_same_question() -> None:
    head = "费率表与" + "在本说明书中，“您”指投保人。" * 6 + f"\r\n《{MEDICAL}》产品说明书"
    result = judged(head, "产品说明书.pdf")
    assert (result.outcome, result.reason) == ("NEEDS_CONFIRM", "role_unresolved")
