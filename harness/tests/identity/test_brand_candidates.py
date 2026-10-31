"""S11c acceptance: a sales or Office material that names only a brand is offered to a person
with candidate products, never attributed automatically (Spec §2.5, §2.6).

Protected file: written by Claude. Sales decks and training documents print a brand ("星河安康"),
not the filed name. A registered product whose brand core (its name without the company prefix,
the bracketed qualifiers and the product type suffix) starts with what the material's file name or
opening carries is a candidate; a year the material carries keeps only the products of that year
when any match. Candidates always go to a person, even one alone; without any the material stays
quarantined. PDF terms, brochures and rate tables are judged exactly as before. The product names
below are invented.
"""

from __future__ import annotations

import hashlib

import pytest

from insurance_harness.identity.attribution import (
    Attribution,
    RegisteredMaterial,
    RegisteredProduct,
    Upload,
    attribute,
    load_attribution_policy,
)
from insurance_harness.identity.confirmation import choices, conclude
from insurance_harness.ingest.confirmations import load_wording, question_of
from insurance_harness.ingest.registry import (
    MaterialEntry,
    PendingEntry,
    ProductEntry,
    ProductRegistry,
)

PACK = "schemapack_whole_life_insurance"
NAMES = {
    "p-a": "平安星河安康（2026）终身寿险",
    "p-b": "平安星河安康（尊享版25）终身寿险",
    "p-c": "平安星河安康养老年金保险（分红型）",
    "p-d": "平安云帆守护（2026）两全保险",
    "p-e": "平安附加（2026）意外伤害保险",  # no brand: nothing is left after prefix and type
    "p-f": "平安e星安康（2026）医疗保险",
}
FAMILY = ("p-a", "p-b", "p-c")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def product(product_id: str, *materials: RegisteredMaterial) -> RegisteredProduct:
    return RegisteredProduct(
        product_id=product_id,
        names=(NAMES[product_id],),
        clause_codes=(),
        schema_pack_id=PACK,
        materials=materials,
    )


REGISTRY = [product(p) for p in NAMES]


def upload(file_name: str, head: str, knowledge_id: str = "k-new") -> Upload:
    return Upload(knowledge_id=knowledge_id, file_name=file_name, sha256=sha(file_name), head=head)


def judged(file_name: str, head: str, registry: list[RegisteredProduct] = REGISTRY) -> Attribution:
    return attribute(upload(file_name, head), registry)


# 1. Candidates ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("file_name", "head", "candidates"),
    [
        ("星河安康2026产品培训.pptx", "星河安康 2026 产品培训\n\n开场话术", ("p-a",)),
        ("星河安康2025产品培训.pptx", "星河安康 2025 产品培训\n\n开场话术", ("p-b",)),
        ("星河安康话术.pptx", "星河安康话术\n\n开场", FAMILY),  # no year: the whole family
        ("星河安康2024培训.pptx", "星河安康 2024 培训", FAMILY),  # no product of that year
        ("云帆守护培训.pptx", "产品培训\n\n开场", ("p-d",)),  # the brand only in the file name
        ("E星安康培训.pptx", "E星安康培训", ("p-f",)),  # case and width are folded
    ],
)
def test_a_sales_material_gets_its_brand_candidates(
    file_name: str, head: str, candidates: tuple[str, ...]
) -> None:
    result = judged(file_name, head)
    assert (result.outcome, result.reason) == ("NEEDS_CONFIRM", "brand_candidates")
    assert result.candidates == candidates
    assert result.product_id is None, "never attributed automatically, even to one candidate"
    assert result.role == "sales_training"
    assert result.policy_ref == f"attribution-policy@{load_attribution_policy().version}"


def test_an_office_file_of_unknown_role_gets_candidates_too() -> None:
    result = judged("星河安康.pptx", "星河安康\n\n保障全面")
    assert (result.outcome, result.reason, result.role) == (
        "NEEDS_CONFIRM",
        "brand_candidates",
        None,
    )
    assert result.candidates == FAMILY


@pytest.mark.parametrize(
    ("file_name", "head"),
    [
        ("星河安康.pdf", "星河安康\n\n保障全面"),  # a PDF of unknown role: as before
        ("星河安康说明书.pdf", "星河安康产品说明书\n本产品保障终身。"),  # a brochure: as before
        ("云海培训.pptx", "云海产品培训"),  # no registered brand
        ("意外伤害培训.pptx", "意外伤害培训"),  # a product without a brand is never a candidate
        ("星河培训.pptx", "星河产品培训"),  # two characters are not a brand
    ],
)
def test_otherwise_the_material_stays_quarantined(file_name: str, head: str) -> None:
    result = judged(file_name, head)
    assert (result.outcome, result.reason) == ("QUARANTINE", "no_product_anchor")
    assert result.candidates == ()


def test_too_many_candidates_stay_quarantined() -> None:
    crowded = [
        RegisteredProduct(
            product_id=f"q-{n:02d}",
            names=(f"平安星河安康{n}号（2026）终身寿险",),
            clause_codes=(),
            schema_pack_id=PACK,
        )
        for n in range(load_attribution_policy().brand_max_candidates + 1)
    ]
    result = judged("星河安康培训.pptx", "星河安康培训", crowded)
    assert (result.outcome, result.reason) == ("QUARANTINE", "no_product_anchor")


def test_a_whole_registered_title_still_attributes_as_before() -> None:
    result = judged("云帆守护培训.pptx", "《平安云帆守护（2026）两全保险》产品培训\n\n开场")
    assert (result.outcome, result.reason, result.product_id, result.role) == (
        "SUPPLEMENT",
        "matched_by_name",
        "p-d",
        "sales_training",
    )


# 2. What a person may choose ----------------------------------------------------------------------


def product_key(product_id: str) -> str:
    return "product:" + hashlib.sha256(product_id.encode("utf-8")).hexdigest()[:16]


def test_the_candidates_are_offered_in_order_then_ignore() -> None:
    pending = judged("星河安康话术.pptx", "星河安康话术\n\n开场")
    offered = choices(pending, REGISTRY)
    assert [(c.key, c.kind, c.value) for c in offered] == [
        *((product_key(p), "product", p) for p in FAMILY),
        ("ignore", "ignore", None),
    ]


def test_choosing_a_candidate_supplements_it_with_the_sales_material() -> None:
    item = upload("星河安康话术.pptx", "星河安康话术\n\n开场")
    pending = attribute(item, REGISTRY)
    result = conclude(pending, product_key("p-b"), item, REGISTRY)
    assert (result.outcome, result.reason, result.product_id, result.role) == (
        "SUPPLEMENT",
        "confirmed_by_person",
        "p-b",
        "sales_training",
    )


def test_an_office_file_of_unknown_role_is_then_asked_its_role() -> None:
    item = upload("星河安康.pptx", "星河安康\n\n保障全面")
    pending = attribute(item, REGISTRY)
    asked = conclude(pending, product_key("p-a"), item, REGISTRY)
    assert (asked.outcome, asked.reason, asked.product_id) == (
        "NEEDS_CONFIRM",
        "role_unresolved",
        "p-a",
    )
    assert "role:sales_training" in [c.key for c in choices(asked, REGISTRY)]
    result = conclude(asked, "role:sales_training", item, REGISTRY)
    assert (result.outcome, result.product_id, result.role) == (
        "SUPPLEMENT",
        "p-a",
        "sales_training",
    )


def test_a_second_sales_material_asks_whether_to_replace_or_keep_both() -> None:
    held = RegisteredMaterial(knowledge_id="k-old", sha256="f" * 64, role="sales_training")
    registry = [product(p, held) if p == "p-a" else product(p) for p in NAMES]
    item = upload("星河安康2026产品培训.pptx", "星河安康 2026 产品培训")
    pending = attribute(item, registry)
    asked = conclude(pending, product_key("p-a"), item, registry)
    assert (asked.outcome, asked.reason) == ("NEEDS_CONFIRM", "same_role_differs")
    assert [c.key for c in choices(asked, registry)] == ["replace", "supplement", "ignore"]


def test_ignoring_settles_it() -> None:
    item = upload("星河安康话术.pptx", "星河安康话术")
    result = conclude(attribute(item, REGISTRY), "ignore", item, REGISTRY)
    assert (result.outcome, result.reason) == ("IGNORED", "confirmed_ignore")


# 3. The question a person reads ------------------------------------------------------------------


def test_the_question_names_the_candidates_and_the_wording_version_is_unchanged() -> None:
    item = upload("星河安康话术.pptx", "星河安康话术\n\n开场")
    entry = PendingEntry(
        knowledge_id=item.knowledge_id,
        parse_attempt=1,
        sha256=item.sha256,
        file_name=item.file_name,
        attribution=attribute(item, REGISTRY),
    )
    registry = ProductRegistry(
        contract="product-registry.v1",
        space_id="space-1",
        raw_kb_id="raw-1",
        products={
            p: ProductEntry(
                names=[NAMES[p]], clause_codes=[], schema_pack_id=PACK, origin="seeded",
                materials=[],
            )
            for p in NAMES
        },
        pending=[entry],
        decisions=[],
    )
    question = question_of(entry, registry, head=item.head)
    assert all(NAMES[p] in question.detail for p in FAMILY)
    assert NAMES["p-d"] not in question.detail
    assert [o.label for o in question.options] == [
        *(f"归入「{NAMES[p]}」" for p in FAMILY),
        "忽略这份文件",
    ]
    wording = load_wording()
    assert wording.version == "2026-10-26.1"
    assert wording.roles["sales_training"].strip()


def test_a_registry_may_hold_sales_materials() -> None:
    entry = ProductEntry(
        names=[NAMES["p-a"]], clause_codes=[], schema_pack_id=PACK, origin="seeded",
        materials=[
            MaterialEntry(
                knowledge_id="k-deck", parse_attempt=1, sha256="d" * 64, role="sales_training",
                file_name="星河安康培训.pptx",
            )
        ],
    )
    registry = ProductRegistry(
        contract="product-registry.v1", space_id="space-1", raw_kb_id="raw-1",
        products={"p-a": entry}, pending=[], decisions=[],
    )
    assert registry.registered()[0].materials[0].role == "sales_training"
