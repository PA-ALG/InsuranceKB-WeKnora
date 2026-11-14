"""PB-R1: synthetic filed titles, tested through attribution rather than a private router."""

import hashlib

import pytest

from insurance_harness.identity.attribution import (
    RegisteredProduct,
    Upload,
    attribute,
    load_attribution_policy,
)
from insurance_harness.identity.brands import brand_core

NEW_POLICY = "attribution-policy@2026-11-14.1"
CODE = "平安人寿〔2099〕医疗保险901号"


def terms(name: str, *, code: str = CODE, body: str = "保险责任") -> Upload:
    head = f"{code}{name}条款\n阅读指引\n{body}"
    return Upload(
        knowledge_id="synthetic-rider",
        file_name="保险条款.pdf",
        sha256=hashlib.sha256(head.encode()).hexdigest(),
        head=head,
    )


@pytest.mark.parametrize(
    ("name", "family"),
    [
        ("平安附加合成甲意外伤害医疗保险", "accident_medical"),
        ("平安合成乙意外伤害（Ａ款）医疗保险", "accident_medical"),
        ("平安附加合成甲疾病保险", "critical_illness"),
        ("平安合成乙特定疾病保险（普通型）", "critical_illness"),
    ],
)
def test_filed_new_suffix_selects_the_existing_pack(name: str, family: str) -> None:
    result = attribute(terms(name), [])
    assert (result.outcome, result.reason, result.role) == ("CREATE", "new_product", "terms")
    assert result.schema_pack_id == f"schemapack_{family}_insurance"
    assert result.clause_code == CODE
    assert result.policy_ref == NEW_POLICY


@pytest.mark.parametrize(
    ("suffix", "family"),
    [
        ("医疗保险", "medical"),
        ("意外医疗保险", "accident_medical"),
        ("意外伤害保险", "accident"),
        ("重大疾病保险", "critical_illness"),
        ("定期寿险", "term_life"),
        ("终身寿险", "whole_life"),
        ("两全保险", "endowment"),
        ("年金保险", "annuity"),
        ("护理保险", "nursing_care"),
        ("补充养老保险", "supplementary_pension"),
        ("失能收入损失保险", "disability_income"),
    ],
)
def test_main_product_routes_remain_unchanged(suffix: str, family: str) -> None:
    result = attribute(terms(f"平安合成主险{suffix}"), [])
    assert result.outcome == "CREATE"
    assert result.schema_pack_id == f"schemapack_{family}_insurance"


def test_longest_suffix_still_wins_independent_of_policy_order() -> None:
    policy = load_attribution_policy()
    reordered = policy.model_copy(
        update={"classifications": tuple(reversed(policy.classifications))}
    )
    for name in (
        "平安附加合成甲意外伤害医疗保险",
        "平安合成乙意外（Ｂ款）医疗保险",
    ):
        result = attribute(terms(name), [], reordered)
        assert result.schema_pack_id == "schemapack_accident_medical_insurance"


@pytest.mark.parametrize("suffix", ["医疗保险", "保障服务保险"])
def test_body_keywords_do_not_override_the_filed_type(suffix: str) -> None:
    result = attribute(
        terms(f"平安合成甲{suffix}", body="参见意外伤害医疗保险、疾病保险。"), []
    )
    if suffix == "医疗保险":
        assert (result.outcome, result.schema_pack_id) == ("CREATE", "schemapack_medical_insurance")
    else:
        assert result.outcome == "NEEDS_CONFIRM"
        assert result.schema_pack_id is None


def test_a_brochure_with_the_new_suffix_still_cannot_create_a_product() -> None:
    upload = terms("平安合成乙疾病保险").model_copy(
        update={"file_name": "产品说明书.pdf", "head": "平安合成乙疾病保险产品说明书"}
    )
    result = attribute(upload, [])
    assert (result.outcome, result.reason) == ("QUARANTINE", "no_product_anchor")


def test_new_route_does_not_reclassify_an_existing_registered_identity() -> None:
    name = "平安附加合成甲意外伤害医疗保险"
    product = RegisteredProduct(
        product_id="synthetic-registered",
        names=(name,),
        clause_codes=(CODE,),
        schema_pack_id="schemapack_medical_insurance",
        materials=(),
    )
    before = product.model_dump_json()
    result = attribute(terms(name), [product])
    assert result.outcome == "SUPPLEMENT"
    assert result.product_id == product.product_id
    assert product.model_dump_json() == before
    assert result.schema_pack_id != "schemapack_accident_medical_insurance"


def test_conflicting_code_and_title_still_quarantine() -> None:
    product = RegisteredProduct(
        product_id="synthetic-other",
        names=("平安合成乙疾病保险",),
        clause_codes=(CODE,),
        schema_pack_id="schemapack_critical_illness_insurance",
        materials=(),
    )
    result = attribute(terms("平安附加合成甲意外伤害医疗保险"), [product])
    assert (result.outcome, result.reason) == ("QUARANTINE", "anchor_conflict")


@pytest.mark.parametrize(
    "suffix", ["意外伤害医疗保险", "疾病保险", "重大疾病保险", "意外医疗保险"]
)
def test_brand_core_removes_the_full_longest_suffix(suffix: str) -> None:
    assert brand_core(f"平安附加合成甲{suffix}", load_attribution_policy()) == "合成甲"
