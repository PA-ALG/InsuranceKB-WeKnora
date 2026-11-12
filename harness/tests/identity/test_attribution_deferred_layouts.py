"""PB-A1 (written by Claude): layouts that left on-sale materials without a product anchor.

Issue #563 batch 5 deferred 10 main products whose terms or rate tables carry their product in a
place the rules did not read. The heads below are synthetic (invented product names) but keep the
structure the content stream gives those PDFs:

- terms whose opening is a reader guide without a usable name, and whose own code line is followed
  by the terms title (《name》 is absent; the title ends with 条款);
- terms whose verification code prints ASCII brackets ([2021] instead of 〔2021〕);
- a reader guide naming the product as 对“<name>合同” under emphasis marks, which extraction turns
  into full-width dots inside the name;
- rate tables titled 附件3：《<name>》基本保险金额表, or 《<name>》<a short plan part>费率表.
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

ACCIDENT = "平安示例安行意外伤害保险"
MEDICAL = "平安示例康宁（2021）医疗保险"
WHOLE_LIFE = "平安示例盈享（D款）终身寿险（分红型）"
POLICY_REF = "attribution-policy@2026-11-12.2"

GUIDE_WITHOUT_NAME = (
    "阅 读 指 引\r\n为了帮助您更好地了解产品，我们先介绍几个保险条款中常用的术语\r\n"
    " 被保险人就是受保险合同保障的人。\r\n 投保人就是购买保险并交纳保险费的人。\r\n"
    " 您拥有的重要权益\r\n 被保险人可以享受本合同提供的保障………………………………2.2\r\n"
    " 您有退保的权利………………………………………………………………5.1\r\n"
)


def judged(head: str, file_name: str, registry: list[RegisteredProduct] | None = None) -> Attribution:
    upload = Upload(knowledge_id="k-1", file_name=file_name, sha256="a" * 64, head=head)
    return attribute(upload, registry or [])


def registered(product_id: str, name: str, code: str, pack: str) -> RegisteredProduct:
    return RegisteredProduct(
        product_id=product_id, names=(name,), clause_codes=(code,), schema_pack_id=pack
    )


def terms(code_line: str, after: str) -> str:
    return GUIDE_WITHOUT_NAME + "1.1 合同构成\r\n" + code_line + "\r\n请扫描以查询验证条款\r\n" + after


# 1. The title printed right after the terms' own code line ---------------------------------------


def test_a_terms_title_after_its_own_code_line_creates_the_product() -> None:
    head = terms("平安人寿〔2024〕意外伤害保险050号", f"{ACCIDENT}条款\r\n在本条款中，“您”指投保人")
    result = judged(head, "保险条款.pdf")
    assert (result.outcome, result.reason, result.display_name, result.schema_pack_id) == (
        "CREATE",
        "new_product",
        ACCIDENT,
        "schemapack_accident_insurance",
    )
    assert (result.clause_code, result.policy_ref) == ("平安人寿〔2024〕意外伤害保险050号", POLICY_REF)


def test_a_qualified_title_after_the_code_line_keeps_its_qualifier() -> None:
    head = terms("平安人寿〔2021〕医疗保险151号", f"{MEDICAL}条款\r\n在本条款中")
    result = judged(head, "保险条款.pdf")
    assert (result.outcome, result.display_name, result.schema_pack_id) == (
        "CREATE",
        "平安示例康宁(2021)医疗保险",
        "schemapack_medical_insurance",
    )


def test_text_after_the_code_line_that_is_no_typed_name_is_no_title() -> None:
    """A table of contents after the code line ends nowhere near a type suffix: fail closed."""
    head = terms("平安人寿〔2023〕意外伤害保险010号", "7.9 非处方药\r\n7.10 猝死\r\n7.11 潜水条款")
    result = judged(head, "保险条款.pdf")
    assert (result.outcome, result.reason) == ("QUARANTINE", "no_product_anchor")


def test_the_code_line_title_names_a_registered_product_by_its_code_and_name() -> None:
    code = "平安人寿〔2024〕意外伤害保险050号"
    known = registered("sc-acc", ACCIDENT, code, "schemapack_accident_insurance")
    result = judged(terms(code, f"{ACCIDENT}条款\r\n"), "保险条款.pdf", [known])
    assert (result.outcome, result.product_id, result.reason) == (
        "SUPPLEMENT",
        "sc-acc",
        "matched_by_clause_code",
    )


def test_a_code_line_title_of_another_registered_product_conflicts() -> None:
    code = "平安人寿〔2024〕意外伤害保险050号"
    known = registered("sc-acc", ACCIDENT, code, "schemapack_accident_insurance")
    head = terms(code, "平安示例别的意外伤害保险条款\r\n")
    assert judged(head, "保险条款.pdf", [known]).reason == "anchor_conflict"


# 2. A verification code printed with ASCII brackets ---------------------------------------------


def test_an_ascii_bracketed_own_code_is_the_terms_own_code_in_the_compared_form() -> None:
    head = terms("平安人寿[2021]医疗保险018号", f"{MEDICAL}条款\r\n")
    result = judged(head, "保险条款.pdf")
    assert (result.outcome, result.clause_code, result.display_name) == (
        "CREATE",
        "平安人寿〔2021〕医疗保险018号",
        "平安示例康宁(2021)医疗保险",
    )
    same = judged(terms("平安人寿〔2021〕医疗保险018号", f"{MEDICAL}条款\r\n"), "保险条款.pdf")
    assert same.product_id == result.product_id  # one code, one created id


# 3. A reader guide naming the product under emphasis marks ---------------------------------------


EMPHASISED_GUIDE = (
    "阅 读 指 引 \r\n本阅读指引有助于您理解条款 ．．．．．．．．．．．．．，对．“．平安示例安行"
    "（ ．．．．．．E\r\n．）意外伤害保险 ．．．．．．．合同” ．．．内容的解释以条款为准 ．．．．．．。\r\n"
    " 您拥有的重要权益 \r\n 被保险人可以享受本主险合同提供的保障……………………2.3\r\n"
)


def test_an_emphasised_guide_name_creates_the_terms_product() -> None:
    head = EMPHASISED_GUIDE + "平安人寿〔2023〕意外伤害保险010号\r\n请扫描以查询验证条款\r\n7.9 非处方药\r\n"
    result = judged(head, "保险条款.pdf")
    assert (result.outcome, result.display_name, result.schema_pack_id) == (
        "CREATE",
        "平安示例安行(E)意外伤害保险",
        "schemapack_accident_insurance",
    )


def test_two_guides_naming_different_products_are_still_no_title() -> None:
    other = EMPHASISED_GUIDE.replace("安行", "别行", 1)
    head = (
        EMPHASISED_GUIDE
        + other
        + "平安人寿〔2023〕意外伤害保险010号\r\n请扫描以查询验证条款\r\n7.9 非处方药\r\n"
    )
    assert judged(head, "保险条款.pdf").reason == "no_product_anchor"


# 4. Rate table titles: an attachment label, a short plan part -----------------------------------


WHOLE_LIFE_ENTRY = registered(
    "sc-wl", WHOLE_LIFE, "平安人寿〔2025〕终身寿险301号", "schemapack_whole_life_insurance"
)
ACCIDENT_ENTRY = registered(
    "sc-acc", ACCIDENT, "平安人寿〔2024〕意外伤害保险050号", "schemapack_accident_insurance"
)
MEDICAL_ENTRY = registered(
    "sc-med", MEDICAL, "平安人寿〔2021〕医疗保险151号", "schemapack_medical_insurance"
)
ROWS = "\r\n".join(f"{age} {927 + age} {2745 + age}" for age in range(20))


def test_a_rate_table_opening_with_an_attachment_label_attaches_it() -> None:
    head = f"附件3： 《{WHOLE_LIFE}》基本保险金额表\r\n（每份）\r\n单位：人民币元\r\n{ROWS}"
    result = judged(head, "费率表.pdf", [WHOLE_LIFE_ENTRY])
    assert (result.outcome, result.product_id, result.role) == ("SUPPLEMENT", "sc-wl", "rate_table")


@pytest.mark.parametrize(
    ("line", "entry"),
    [
        (f"《{ACCIDENT}》客运列车意外基本部分费率表", ACCIDENT_ENTRY),
        (f"《{ACCIDENT}》航空意外可选部分费率表", ACCIDENT_ENTRY),
        (f"《{MEDICAL}》基本部分（基础）年交费率表", MEDICAL_ENTRY),
        (f"《{MEDICAL}》费率表（年交）", MEDICAL_ENTRY),  # the payment mode after the document word
    ],
)
def test_a_rate_table_title_line_with_a_plan_part_attaches_it(
    line: str, entry: RegisteredProduct
) -> None:
    head = f"保险期间 费率\r\n{ROWS}\r\n{line}\r\n(每万元基本保险金额）\r\n单位：人民币元"
    result = judged(head, "费率表.pdf", [entry])
    assert (result.outcome, result.product_id, result.role) == (
        "SUPPLEMENT",
        entry.product_id,
        "rate_table",
    )


@pytest.mark.parametrize(
    "line",
    [
        f"《{ACCIDENT}》的保险金额按本合同约定的方式确定并适用于费率表",  # a sentence, too long
        f"《{ACCIDENT}》，详见费率表",  # punctuation and a reference
        f"《{ACCIDENT}》不适用本费率表",  # a negation
        f"《{ACCIDENT}》费率表（详见附表）的说明",  # text after the bracketed part
    ],
)
def test_a_long_or_punctuated_tail_is_still_no_title_line(line: str) -> None:
    head = f"保险期间 费率\r\n{ROWS}\r\n{line}\r\n"
    result = judged(head, "费率表.pdf", [ACCIDENT_ENTRY])
    assert (result.outcome, result.reason) == ("QUARANTINE", "no_product_anchor")


# 5. The policy ----------------------------------------------------------------------------------


def test_the_policy_version_and_rule_data() -> None:
    policy = load_attribution_policy()
    assert policy.policy_ref == POLICY_REF
    assert "PB-A1" in policy.basis
    assert 8 <= policy.title_line_qualifier_chars <= 20
    data = json.loads(policy.model_dump_json())
    with pytest.raises(ValueError):
        AttributionPolicy.model_validate_json(json.dumps(data | {"title_line_qualifier_chars": 0}))
    with pytest.raises(ValueError):  # every guide pattern names the product in one group
        AttributionPolicy.model_validate_json(
            json.dumps(data | {"guide_title_patterns": ["阅读指引(.*)(产品)提供"]})
        )
