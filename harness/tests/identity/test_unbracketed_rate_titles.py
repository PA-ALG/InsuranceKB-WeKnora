"""PB-A2: exact registered names on complete rate-title lines, via public attribution.

All names/text are synthetic. No directory hint or real material is an attribution input.
"""

import json

import pytest

from insurance_harness.identity.attribution import (
    Attribution,
    AttributionPolicy,
    RegisteredMaterial,
    RegisteredProduct,
    Upload,
    attribute,
    load_attribution_policy,
)

MEDICAL = "合成甲附加（2024）医疗保险"
DISEASE = "合成乙附加疾病保险"
REGISTRY = [
    RegisteredProduct(
        product_id="synthetic-medical",
        names=(MEDICAL,),
        clause_codes=("平安人寿〔2024〕医疗保险901号",),
        schema_pack_id="schemapack_medical_insurance",
    ),
    RegisteredProduct(
        product_id="synthetic-disease",
        names=(DISEASE,),
        clause_codes=("平安人寿〔2024〕疾病保险902号",),
        schema_pack_id="schemapack_critical_illness_insurance",
    ),
]
ROWS = "投保年龄 男 女\n0 10 20\n1 11 21"


def judged(
    head: str,
    *,
    name: str = "费率表.pdf",
    registry: list[RegisteredProduct] | None = None,
) -> Attribution:
    return attribute(
        Upload(knowledge_id="synthetic-rate", file_name=name, sha256="a" * 64, head=head),
        REGISTRY if registry is None else registry,
    )


@pytest.mark.parametrize(
    "suffix",
    ["年交费率表", "年保障成本表", "基本保险金额表", "基本部分（基础）年交费率表（年交）"],
)
@pytest.mark.parametrize("product", REGISTRY)
def test_first_line_confirms_each_exact_registered_name(
    product: RegisteredProduct, suffix: str
) -> None:
    result = judged(f"{product.names[0]}{suffix}\r\n{ROWS}")
    assert (result.outcome, result.reason, result.product_id, result.role) == (
        "SUPPLEMENT", "matched_by_name", product.product_id, "rate_table"
    )
    assert result.version_key is None and result.candidates == ()


def test_whitespace_and_width_folding_do_not_drop_the_name_year() -> None:
    title = " \t".join(MEDICAL.replace("2024", "２０２４"))
    result = judged(f"\r\n  {title} 年 交 费 率 表\n{ROWS}")
    assert (result.outcome, result.product_id) == ("SUPPLEMENT", REGISTRY[0].product_id)


def test_full_registered_alias_is_also_an_exact_name() -> None:
    product = REGISTRY[0].model_copy(update={"names": (MEDICAL, "合成已核准别名医疗保险")})
    result = judged(f"{product.names[1]}年交费率表\n{ROWS}", registry=[product])
    assert (result.outcome, result.product_id) == ("SUPPLEMENT", product.product_id)


def test_qualifier_boundary_is_sixteen_characters() -> None:
    result = judged(f"{MEDICAL}{'基础' * 8}费率表\n{ROWS}")
    assert (result.outcome, result.product_id) == ("SUPPLEMENT", REGISTRY[0].product_id)
    too_long = judged(f"{MEDICAL}{'基础' * 8}年费率表\n{ROWS}")
    assert (too_long.outcome, too_long.product_id) == ("QUARANTINE", None)


@pytest.mark.parametrize("punctuation", ["，", "。", "；", "：", "、", "！", "？", "的", "“", "《"])
def test_explanatory_or_sentence_qualifiers_are_not_titles(punctuation: str) -> None:
    result = judged(f"{MEDICAL}年{punctuation}交费率表\n{ROWS}")
    assert (result.outcome, result.product_id) == ("QUARANTINE", None)


@pytest.mark.parametrize(
    "word", ["不适用", "并非", "非本", "不属于", "不包括", "参照", "参见", "详见", "除外"]
)
def test_every_existing_exclusion_still_rejects_the_whole_line(word: str) -> None:
    result = judged(f"{MEDICAL}{word}年交费率表\n{ROWS}")
    assert (result.outcome, result.product_id) == ("QUARANTINE", None)


@pytest.mark.parametrize(
    "title",
    [
        "合成丙附加（2024）医疗保险年交费率表",
        "合成甲附加（24）医疗保险年交费率表",
        "合成甲附加（2025）医疗保险年交费率表",
        "合成甲附加（2024）医疗险年交费率表",
        "本表参照合成甲附加（2024）医疗保险年交费率表",
    ],
)
def test_wrong_near_or_abbreviated_name_is_not_a_match(title: str) -> None:
    result = judged(f"{title}\n{ROWS}")
    assert (result.outcome, result.product_id) == ("QUARANTINE", None)


@pytest.mark.parametrize("suffix", ["年交费率表", "年保障成本表", "基本保险金额表"])
def test_unregistered_name_cannot_create_any_product_or_version(suffix: str) -> None:
    result = judged(f"{MEDICAL}{suffix}\n{ROWS}", registry=[])
    assert (result.outcome, result.product_id, result.version_key) == ("QUARANTINE", None, None)


@pytest.mark.parametrize(
    "head",
    [
        f"{MEDICAL}\n年交费率表\n{ROWS}",
        f"{MEDICAL}\f年交费率表\n{ROWS}",
        f"{MEDICAL[:5]}\n{MEDICAL[5:]}年交费率表\n{ROWS}",
        f"{MEDICAL[:5]}\f{MEDICAL[5:]}年交费率表\n{ROWS}",
        f"参见下表：{MEDICAL}年交费率表\n{ROWS}",
        f"{MEDICAL}年交费率表，应结合说明阅读\n{ROWS}",
    ],
)
def test_only_a_complete_single_line_can_supply_this_anchor(head: str) -> None:
    result = judged(head)
    assert (result.outcome, result.product_id) == ("QUARANTINE", None)


@pytest.mark.parametrize("separator", ["\n", "\r\n", "\f"])
@pytest.mark.parametrize("suffix", ["年交费率表", "年保障成本表", "基本保险金额表"])
def test_a_late_complete_line_adds_role_evidence(separator: str, suffix: str) -> None:
    head = (ROWS + "\n") * 20 + separator + MEDICAL + suffix
    result = judged(head)
    assert (result.outcome, result.product_id, result.role) == (
        "SUPPLEMENT", REGISTRY[0].product_id, "rate_table"
    )


def test_late_title_does_not_erase_conflicting_opening_role() -> None:
    head = "产品说明书\n" + (ROWS + "\n") * 20 + f"{MEDICAL}年交费率表"
    result = judged(head)
    assert (result.outcome, result.product_id) == ("QUARANTINE", None)


@pytest.mark.parametrize("part", ["（2026）", "（分红型）", "(基础)"])
def test_parenthesis_immediately_after_a_short_name_cannot_be_a_qualifier(part: str) -> None:
    result = judged(f"{DISEASE}{part}年交费率表\n{ROWS}")
    assert (result.outcome, result.product_id) == ("QUARANTINE", None)


def test_a_whole_registered_parenthesized_name_is_accepted() -> None:
    product = REGISTRY[1].model_copy(update={"names": (DISEASE + "（2026）",)})
    result = judged(f"{product.names[0]}年交费率表\n{ROWS}", registry=[product])
    assert (result.outcome, result.product_id) == ("SUPPLEMENT", product.product_id)


def test_multiple_registered_prefixes_quarantine_instead_of_choosing_the_longest() -> None:
    short = REGISTRY[1]
    long = short.model_copy(update={
        "product_id": "synthetic-long-name", "names": (DISEASE + "（2026）",)
    })
    for registry in ([short, long], [long, short]):
        result = judged(f"{long.names[0]}年交费率表\n{ROWS}", registry=registry)
        assert (result.outcome, result.reason, result.product_id) == (
            "QUARANTINE", "anchor_conflict", None
        )


def test_two_alias_prefixes_of_one_product_still_quarantine() -> None:
    for names in ((DISEASE, DISEASE + "（2026）"), (DISEASE + "（2026）", DISEASE)):
        product = REGISTRY[1].model_copy(update={"names": names})
        result = judged(f"{DISEASE}（2026）年交费率表\n{ROWS}", registry=[product])
        assert (result.outcome, result.reason, result.product_id) == (
            "QUARANTINE", "anchor_conflict", None
        )


def test_two_distinct_title_lines_remain_a_multiple_product_question() -> None:
    titles = [MEDICAL + "年交费率表", DISEASE + "基本保险金额表"]
    for ordered in (titles, list(reversed(titles))):
        result = judged("\n".join([ROWS * 20, *ordered]))
        assert (result.outcome, result.reason, result.product_id) == (
            "NEEDS_CONFIRM", "multiple_products", None
        )
        assert set(result.candidates) == {p.product_id for p in REGISTRY}


@pytest.mark.parametrize(
    ("file_name", "head"),
    [
        ("产品说明书.pdf", f"{MEDICAL}年交说明书\n在本说明书中"),
        ("保险条款.pdf", f"{MEDICAL}年交条款\n阅读指引"),
        ("产品说明书.pdf", f"{MEDICAL}年交费率表\n说明书"),
        ("保险条款.pdf", f"{MEDICAL}年交费率表\n阅读指引"),
        ("费率表.pdf", f"{MEDICAL}年交费率表\n说明书"),
        ("无角色.pdf", f"{MEDICAL}年交费率表\n{ROWS}"),
    ],
)
def test_other_or_conflicting_roles_do_not_gain_an_anchor(file_name: str, head: str) -> None:
    for registry in ([], REGISTRY):
        result = judged(head, name=file_name, registry=registry)
        assert (result.outcome, result.product_id) == ("QUARANTINE", None)


def test_two_registered_products_with_the_same_name_remain_ambiguous() -> None:
    first = REGISTRY[0]
    other = first.model_copy(update={"product_id": "synthetic-other-version"})
    for registry in ([first, other], [other, first]):
        result = judged(f"{MEDICAL}年交费率表\n{ROWS}", registry=registry)
        assert (result.outcome, result.reason, result.product_id) == (
            "NEEDS_CONFIRM", "multiple_products", None
        )
        assert set(result.candidates) == {first.product_id, other.product_id}


def test_new_name_and_an_unknown_bracketed_title_conflict() -> None:
    result = judged(f"{MEDICAL}年交费率表\n《合成未知医疗保险》费率表\n{ROWS}")
    assert (result.outcome, result.reason, result.product_id) == (
        "QUARANTINE", "anchor_conflict", None
    )


def test_original_bracketed_match_has_priority_over_the_new_fallback() -> None:
    head = f"{MEDICAL}年交费率表\n《{DISEASE}》费率表\n{ROWS}"
    for registry in (REGISTRY, list(reversed(REGISTRY))):
        result = judged(head, registry=registry)
        assert (result.outcome, result.product_id) == ("SUPPLEMENT", REGISTRY[1].product_id)


def test_another_registered_clause_code_still_conflicts() -> None:
    result = judged(f"{MEDICAL}年交费率表\n{REGISTRY[1].clause_codes[0]}\n{ROWS}")
    assert (result.outcome, result.reason, result.product_id) == (
        "QUARANTINE", "anchor_conflict", None
    )


def test_same_role_different_material_still_requires_confirmation() -> None:
    product = REGISTRY[0].model_copy(update={"materials": (
        RegisteredMaterial(knowledge_id="synthetic-old", sha256="b" * 64, role="rate_table"),
    )})
    result = judged(f"{MEDICAL}年交费率表\n{ROWS}", registry=[product])
    assert (result.outcome, result.reason, result.product_id) == (
        "NEEDS_CONFIRM", "same_role_differs", product.product_id
    )


def test_duplicate_bytes_do_not_depend_on_the_new_layout() -> None:
    product = REGISTRY[0].model_copy(update={"materials": (
        RegisteredMaterial(knowledge_id="synthetic-old", sha256="a" * 64, role="rate_table"),
    )})
    result = judged("没有可读标题", registry=[product])
    assert (result.outcome, result.reason, result.product_id) == (
        "DUPLICATE", "duplicate_file", product.product_id
    )


@pytest.mark.parametrize("suffix", ["费率表", "条款", "产品说明书"])
def test_original_exact_opening_title_still_works(suffix: str) -> None:
    file_name = f"{suffix}.pdf"
    head = f"{MEDICAL}{suffix}\n" + ("阅读指引" if suffix == "条款" else ROWS)
    result = judged(head, name=file_name)
    assert (result.outcome, result.product_id) == ("SUPPLEMENT", REGISTRY[0].product_id)


def test_policy_records_this_change_and_only_the_allowed_document_words() -> None:
    policy = load_attribution_policy()
    data = policy.model_dump(mode="json")
    assert policy.policy_ref == "attribution-policy@2026-11-14.1"
    assert "PB-A2" in policy.basis
    assert data["unbracketed_rate_documents"] == ["费率表", "成本表", "金额表"]
    for words in ([], [""], ["任意正文"]):
        with pytest.raises(ValueError):
            AttributionPolicy.model_validate_json(
                json.dumps(data | {"unbracketed_rate_documents": words})
            )
