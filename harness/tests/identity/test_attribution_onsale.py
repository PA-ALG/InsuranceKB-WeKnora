"""S5b-5 acceptance (protected, written by Claude): products are recognised from real terms.

Spec docs/design/slices/S5b-5-按真实条款格式识别产品.md §2, §4. The fixture holds the first two
pages (folded, trimmed around the clause code) of 21 public materials of 7 on-sale products in 7
insurance types; the 13 registered products come from the S5b-1 fixture.
"""

import hashlib
import json
from pathlib import Path

import pytest

from insurance_harness.identity.attribution import (
    Attribution,
    RegisteredMaterial,
    RegisteredProduct,
    Upload,
    attribute,
)
from tests.identity.test_attribution import PRODUCTS, registered

ONSALE = json.loads(
    (Path(__file__).parent / "fixtures" / "attribution_heads_onsale.json").read_text(
        encoding="utf-8"
    )
)
NEW = {product["plan_code"]: product for product in ONSALE["products"]}
TERMS, BROCHURE, RATES = "保险条款.pdf", "产品说明书.pdf", "费率表.pdf"
EXPECTED = {
    "1836": ("平安安佑福重大疾病保险", "schemapack_critical_illness_insurance"),
    "2613": ("平安畅行意外伤害保险", "schemapack_accident_insurance"),
    "L3223": ("平安意外(A款)医疗保险", "schemapack_accident_medical_insurance"),
    "1815": ("平安附加(2026)定期寿险", "schemapack_term_life_insurance"),
    "2648": ("平安智盈倍护(2026)终身护理保险", "schemapack_nursing_care_insurance"),
    "1806": ("平安附加失能收入损失保险", "schemapack_disability_income_insurance"),
    "2647": ("平安智盈金生专属商业养老保险", "schemapack_supplementary_pension_insurance"),
}
EXCEPTIONS = {
    ("2613", RATES): ("QUARANTINE", "no_product_anchor"),  # a rate table without any title
    ("L3223", BROCHURE): ("QUARANTINE", "no_product_anchor"),  # another product's brochure
    ("2647", RATES): ("NEEDS_CONFIRM", "role_unresolved"),  # a conversion table, not a rate table
}


def material(plan: str, file_name: str) -> dict[str, str]:
    return next(m for m in NEW[plan]["materials"] if m["file_name"] == file_name)


def onsale(plan: str, file_name: str, head: str | None = None) -> Upload:
    m = material(plan, file_name)
    return Upload(
        knowledge_id=f"k-{plan}-{file_name}",
        file_name=file_name,
        sha256=m["sha256"],
        head=m["head"] if head is None else head,
    )


def current() -> list[RegisteredProduct]:
    return [registered(product, "terms", "brochure", "rate_table") for product in PRODUCTS]


def created_id(code: str) -> str:
    return "sc-" + hashlib.sha256(code.encode()).hexdigest()[:10]


def own_code(plan: str) -> str:
    code = material(plan, TERMS)["own_code"]
    assert code, plan
    return code


def with_terms(plan: str) -> list[RegisteredProduct]:
    name, pack = EXPECTED[plan]
    created = RegisteredProduct(
        product_id=created_id(own_code(plan)),
        names=(name,),
        clause_codes=(own_code(plan),),
        schema_pack_id=pack,
        materials=(
            RegisteredMaterial(
                knowledge_id=f"k-{plan}-{TERMS}",
                sha256=material(plan, TERMS)["sha256"],
                role="terms",
            ),
        ),
    )
    return [*current(), created]


def outcome(attribution: Attribution) -> tuple[str, str]:
    return attribution.outcome, attribution.reason


@pytest.mark.parametrize("plan", sorted(EXPECTED))
def test_onsale_terms_create_their_product_from_their_own_code(plan: str) -> None:
    attribution = attribute(onsale(plan, TERMS), current())
    name, pack = EXPECTED[plan]
    assert outcome(attribution) == ("CREATE", "new_product")
    assert attribution.product_id == created_id(own_code(plan))
    assert attribution.clause_code == own_code(plan)
    assert attribution.display_name == name
    assert attribution.schema_pack_id == pack
    assert attribution.role == "terms"


@pytest.mark.parametrize(
    ("plan", "file_name"),
    [
        (plan, file_name)
        for plan in sorted(EXPECTED)
        for file_name in (BROCHURE, RATES)
        if (plan, file_name) not in EXCEPTIONS
    ],
)
def test_brochures_and_rate_tables_join_the_created_product_by_name(
    plan: str, file_name: str
) -> None:
    attribution = attribute(onsale(plan, file_name), with_terms(plan))
    assert outcome(attribution) == ("SUPPLEMENT", "matched_by_name")
    assert attribution.product_id == created_id(own_code(plan))


@pytest.mark.parametrize(("plan", "file_name"), sorted(EXCEPTIONS))
def test_materials_without_a_reliable_anchor_wait_for_a_person_or_quarantine(
    plan: str, file_name: str
) -> None:
    attribution = attribute(onsale(plan, file_name), with_terms(plan))
    assert outcome(attribution) == EXCEPTIONS[(plan, file_name)]
    assert attribution.outcome != "SUPPLEMENT"


def test_the_start_title_wins_and_the_reader_guide_only_stands_in() -> None:
    # Extraction may garble the reader guide (S5b-5 Spec §2.2): it never overrides the start.
    head = material("1836", TERMS)["head"]
    guide = "平安安佑福重大疾病保险产品提供"  # the extracted guide also holds a font bullet
    assert head.count(guide) == 1
    changed = head.replace(guide, "平安安康福重大疾病保险产品提供")
    attribution = attribute(onsale("1836", TERMS, head=changed), current())
    assert outcome(attribution) == ("CREATE", "new_product")
    assert attribution.display_name == EXPECTED["1836"][0]
    # 2613 opens with labels and no title, so its name comes from the reader guide.
    assert attribute(onsale("2613", TERMS), current()).display_name == EXPECTED["2613"][0]


def test_two_different_own_codes_are_a_conflict() -> None:
    head = material("2648", TERMS)["head"] + "平安人寿〔2025〕护理保险999号请扫描以查询验证条款"
    attribution = attribute(onsale("2648", TERMS, head=head), current())
    assert outcome(attribution) == ("QUARANTINE", "anchor_conflict")


def test_a_code_without_its_verification_marker_creates_nothing() -> None:
    head = material("1815", TERMS)["head"].replace("请扫描以查询验证条款", "")
    assert own_code("1815") in head
    attribution = attribute(onsale("1815", TERMS, head=head), current())
    assert attribution.outcome != "CREATE"
    assert outcome(attribution) == ("QUARANTINE", "no_product_anchor")


def test_the_same_terms_twice_are_a_duplicate_not_a_second_product() -> None:
    upload = onsale("2613", TERMS)
    attribution = attribute(upload, with_terms("2613"))
    assert outcome(attribution) == ("DUPLICATE", "duplicate_file")
    assert attribution.product_id == created_id(own_code("2613"))
