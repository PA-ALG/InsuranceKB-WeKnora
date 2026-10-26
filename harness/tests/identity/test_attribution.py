"""S5b-1 acceptance (protected, written by Claude): upload attribution decided from data.

Spec docs/design/slices/S5b-1-上传材料归属判定.md §3. The fixture holds the first 300 folded
characters of 39 real materials of 13 products in 7 insurance types, so every rule is checked
across products and structures rather than on one sample.
"""

import json
import random
import re
import unicodedata
from importlib.resources import files
from pathlib import Path

import pytest

from insurance_harness.identity.attribution import (
    Attribution,
    AttributionInputError,
    RegisteredMaterial,
    RegisteredProduct,
    Upload,
    attribute,
    load_attribution_policy,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "attribution_heads.json").read_text(encoding="utf-8")
)
PRODUCTS = {product["product_id"]: product for product in FIXTURE["products"]}
ROLES = {"条款": "terms", "说明书": "brochure", "费率表": "rate_table"}
TRIO = ("1824", "1837", "5003")  # 盛世金越（尊享版26）终身寿险 / …（分红型） / 平安创享…（分红型）


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text) if not c.isspace())


def material(product_id: str, role: str) -> dict[str, str]:
    keyword = next(k for k, r in ROLES.items() if r == role)
    return next(m for m in PRODUCTS[product_id]["materials"] if keyword in m["file_name"])


def upload(product_id: str, role: str, **override: str) -> Upload:
    m = material(product_id, role)
    fields = {
        "knowledge_id": f"k-{product_id}-{role}",
        "file_name": m["file_name"],
        "sha256": m["sha256"],
        "head": m["head"],
    }
    fields.update(override)
    return Upload(**fields)


def registered(
    product_id: str, *roles: str, names: tuple[str, ...] | None = None
) -> RegisteredProduct:
    product = PRODUCTS[product_id]
    return RegisteredProduct(
        product_id=product_id,
        names=names or (product["name"],),
        clause_codes=(product["clause_code"],),
        schema_pack_id=product["schema_pack_id"],
        materials=tuple(
            RegisteredMaterial(
                knowledge_id=f"k-{product_id}-{role}",
                sha256=material(product_id, role)["sha256"],
                role=role,
            )
            for role in roles
        ),
    )


def everything_but(product_id: str) -> list[RegisteredProduct]:
    return [
        registered(other, "terms", "brochure", "rate_table")
        for other in PRODUCTS
        if other != product_id
    ]


def expect(result: Attribution, outcome: str, reason: str, product_id: str | None = None) -> None:
    assert (result.outcome, result.reason) == (outcome, reason), result
    if product_id is not None:
        assert result.product_id == product_id, result


# 1. Policy ------------------------------------------------------------------------------------


def test_the_policy_loads_with_its_version_and_points_at_real_packs() -> None:
    policy = load_attribution_policy()
    assert policy.version == "2026-10-26.3"
    catalog = json.loads(
        files("insurance_harness.catalog").joinpath("schema_packs.json").read_text(encoding="utf-8")
    )
    classes = {
        e["pack"]["schema_pack_id"]: e["pack"]["applicable_classifications"]
        for e in catalog["entries"]
    }
    assert policy.classifications
    for entry in policy.classifications:
        assert entry.classification in classes.get(entry.schema_pack_id, []), entry
    assert attribute(upload("1828", "brochure"), [registered("1828", "terms")]).policy_ref == (
        "attribution-policy@2026-10-26.3"
    )


# 2. Leave one out: every product's terms create it ---------------------------------------------


@pytest.mark.parametrize("product_id", sorted(PRODUCTS))
def test_terms_of_an_unregistered_product_create_it(product_id: str) -> None:
    product = PRODUCTS[product_id]
    result = attribute(upload(product_id, "terms"), everything_but(product_id))
    expect(result, "CREATE", "new_product")
    assert result.role == "terms"
    assert result.display_name == fold(product["name"])
    assert result.clause_code == fold(product["clause_code"])
    assert result.schema_pack_id == product["schema_pack_id"]
    assert re.fullmatch(r"sc-[0-9a-f]{10}", result.product_id or "")


def test_creation_covers_seven_insurance_types() -> None:
    packs = {attribute(upload(p, "terms"), everything_but(p)).schema_pack_id for p in PRODUCTS}
    assert len(packs) >= 7


# 3. Supplements ------------------------------------------------------------------------------


@pytest.mark.parametrize("product_id", sorted(PRODUCTS))
def test_brochure_and_rate_table_supplement_their_product_by_name(product_id: str) -> None:
    registry = [
        registered(product_id, "terms"),
        *[registered(o) for o in PRODUCTS if o != product_id],
    ]
    for role in ("brochure", "rate_table"):
        result = attribute(upload(product_id, role), registry)
        expect(result, "SUPPLEMENT", "matched_by_name", product_id)
        assert result.role == role


def test_terms_supplement_a_product_known_by_its_clause_code() -> None:
    result = attribute(upload("1830", "terms"), [registered("1830", "brochure"), registered("594")])
    expect(result, "SUPPLEMENT", "matched_by_clause_code", "1830")


# 4. Names inside names -----------------------------------------------------------------------


def test_each_of_the_nested_names_keeps_its_own_materials() -> None:
    registry = [registered(p, "terms") for p in TRIO]
    for product_id in TRIO:
        for role in ("brochure", "rate_table"):
            expect(
                attribute(upload(product_id, role), registry),
                "SUPPLEMENT",
                "matched_by_name",
                product_id,
            )


@pytest.mark.parametrize("product_id", ["1837", "5003"])
def test_a_longer_new_name_is_a_new_product_not_a_new_version(product_id: str) -> None:
    result = attribute(upload(product_id, "terms"), [registered("1824", "terms", "brochure")])
    expect(result, "CREATE", "new_product")


# 5–7. Duplicates, same role, versions ----------------------------------------------------------


def test_an_identical_file_is_a_duplicate() -> None:
    result = attribute(
        upload("1818", "brochure", knowledge_id="again"), [registered("1818", "terms", "brochure")]
    )
    expect(result, "DUPLICATE", "duplicate_file", "1818")


def test_a_second_different_material_of_the_same_role_needs_a_person() -> None:
    result = attribute(
        upload("1818", "brochure", sha256="f" * 64), [registered("1818", "terms", "brochure")]
    )
    expect(result, "NEEDS_CONFIRM", "same_role_differs", "1818")
    assert result.candidates == ("1818",)


def test_terms_with_a_new_clause_code_are_a_new_version() -> None:
    head = material("1828", "terms")["head"].replace("174号", "999号", 1)
    result = attribute(
        upload("1828", "terms", sha256="e" * 64, head=head),
        [registered("1828", "terms", "brochure"), registered("1826")],
    )
    expect(result, "NEW_VERSION", "new_clause_code", "1828")
    assert result.replaces == ("k-1828-terms",)
    assert result.clause_code == fold(PRODUCTS["1828"]["clause_code"]).replace("174号", "999号")


def test_a_clause_code_and_a_name_of_different_products_conflict() -> None:
    code = fold(PRODUCTS["1826"]["clause_code"])
    head = code + material("1828", "terms")["head"][len(fold(PRODUCTS["1828"]["clause_code"])) :]
    result = attribute(
        upload("1828", "terms", sha256="d" * 64, head=head),
        [registered("1828", "brochure"), registered("1826", "brochure")],
    )
    expect(result, "QUARANTINE", "anchor_conflict")


# 8. Several products --------------------------------------------------------------------------


def test_a_title_naming_two_registered_products_needs_a_person() -> None:
    head = (
        fold(PRODUCTS["1828"]["name"])
        + "、"
        + fold(PRODUCTS["1814"]["name"])
        + "产品说明书在本说明书中"
    )
    result = attribute(
        upload("1828", "brochure", sha256="c" * 64, head=head),
        [registered("1814", "terms"), registered("1828", "terms")],
    )
    expect(result, "NEEDS_CONFIRM", "multiple_products")
    assert result.candidates == ("1814", "1828")


def test_two_products_sharing_an_alias_need_a_person() -> None:
    alias = PRODUCTS["1818"]["name"]
    registry = [
        registered("1818", "terms"),
        registered("1826", "terms", names=(PRODUCTS["1826"]["name"], alias)),
    ]
    result = attribute(upload("1818", "brochure"), registry)
    expect(result, "NEEDS_CONFIRM", "multiple_products")
    assert result.candidates == ("1818", "1826")


# 9–10. Quarantine and confirmation -------------------------------------------------------------


def test_a_brochure_of_an_unknown_product_waits_in_quarantine() -> None:
    expect(
        attribute(upload("1830", "brochure"), everything_but("1830")),
        "QUARANTINE",
        "no_product_anchor",
    )


def test_a_material_without_text_waits_in_quarantine() -> None:
    expect(
        attribute(upload("1830", "terms", head=" \n "), everything_but("1830")),
        "QUARANTINE",
        "text_unavailable",
    )


def test_an_unrecognised_role_needs_a_person() -> None:
    result = attribute(
        upload("1830", "brochure", file_name="scan-0001.pdf"), [registered("1830", "terms")]
    )
    expect(result, "NEEDS_CONFIRM", "role_unresolved", "1830")


def test_an_unknown_insurance_type_needs_a_person() -> None:
    product = PRODUCTS["1830"]
    head = material("1830", "terms")["head"].replace(fold(product["name"]), "平安安心保障计划", 1)
    result = attribute(upload("1830", "terms", head=head), everything_but("1830"))
    expect(result, "NEEDS_CONFIRM", "pack_unresolved")
    assert result.candidates == ()


# 11. Determinism ------------------------------------------------------------------------------


def test_order_and_repetition_do_not_change_the_result() -> None:
    registry = [registered(p, "terms") for p in PRODUCTS]
    shuffled = list(registry)
    random.Random(7).shuffle(shuffled)
    for product_id in PRODUCTS:
        for role in ("brochure", "rate_table"):
            first = attribute(upload(product_id, role), registry)
            assert attribute(upload(product_id, role), shuffled) == first
            assert attribute(upload(product_id, role), registry) == first


def test_the_created_id_depends_only_on_the_clause_code() -> None:
    first = attribute(upload("1828", "terms"), everything_but("1828"))
    other = attribute(
        upload("1828", "terms", knowledge_id="other", sha256="b" * 64, file_name="1828-条款.pdf"),
        [registered("594")],
    )
    assert first.product_id == other.product_id


# 12. Review R1–R4 counterexamples (2026-10-24) -------------------------------------------------

CODE = fold(PRODUCTS["1828"]["clause_code"])
NAME = fold(PRODUCTS["1828"]["name"])


@pytest.mark.parametrize(
    "title",
    ["平安新宁终身寿险", "", "长" * 61],
    ids=["another-name", "no-title", "too-long"],
)
def test_a_clause_code_alone_never_files_a_material(title: str) -> None:
    head = CODE + title + "阅读指引请扫描以查询验证条款"
    result = attribute(
        upload("1828", "terms", sha256="9" * 64, head=head), [registered("1828", "brochure")]
    )
    expect(result, "QUARANTINE", "anchor_conflict")


def test_an_end_marker_right_after_the_code_leaves_no_title_to_create_from() -> None:
    head = CODE + "阅读指引" + NAME + "条款"
    result = attribute(upload("1828", "terms", head=head), everything_but("1828"))
    expect(result, "QUARANTINE", "no_product_anchor")


@pytest.mark.parametrize("label", ["条款编号:", "条款编号"])
def test_a_label_before_the_code_does_not_make_a_new_version(label: str) -> None:
    head = label + material("1828", "terms")["head"]
    registry = [registered("1828", "terms", "brochure")]
    result = attribute(upload("1828", "terms", sha256="8" * 64, head=head), registry)
    # S5b-5: the start holds only the label and this extraction's reader guide carries the
    # verification line, so no title is read and the cited code stays a conflict.
    expect(result, "QUARANTINE", "anchor_conflict")
    assert result.clause_code == CODE
    created = attribute(upload("1828", "terms", head=head), everything_but("1828"))
    expect(created, "QUARANTINE", "no_product_anchor")


def test_an_unknown_issuer_is_not_a_clause_code() -> None:
    head = "远山人寿〔2025〕终身寿险301号远山恒泰终身寿险阅读指引请扫描以查询验证条款"
    result = attribute(upload("1828", "terms", head=head), [])
    expect(result, "QUARANTINE", "no_product_anchor")
    assert result.clause_code is None


def test_a_brochure_citing_its_clause_code_still_supplements_its_product() -> None:
    code = fold(PRODUCTS["1830"]["clause_code"])
    head = fold(PRODUCTS["1830"]["name"]) + "产品说明书本产品条款编号为" + code + "在本说明书中"
    result = attribute(
        upload("1830", "brochure", sha256="7" * 64, head=head), [registered("1830", "terms")]
    )
    expect(result, "SUPPLEMENT", "matched_by_clause_code", "1830")


def test_a_registry_with_a_repeated_product_id_is_refused_in_any_order() -> None:
    one = RegisteredProduct(
        product_id="same",
        names=("甲保险",),
        clause_codes=(CODE,),
        schema_pack_id="schemapack_whole_life_insurance",
    )
    two = RegisteredProduct(
        product_id="same",
        names=("乙保险",),
        clause_codes=(),
        schema_pack_id="schemapack_whole_life_insurance",
    )
    other = registered("1826")
    head = CODE + "甲保险、乙保险产品说明书"
    for registry in ([one, two, other], [two, one, other], [other, one, one]):
        with pytest.raises(AttributionInputError) as caught:
            attribute(upload("1828", "brochure", sha256="6" * 64, head=head), registry)
        assert caught.value.code == "REGISTRY_DUPLICATE_PRODUCT"


# 13. Review R3 remainder (2026-10-25): only the material's own, leading code creates or versions --

OWN = "平安人寿〔2025〕终身寿险301号"
PLAIN = "远山恒泰终身寿险"


def fictitious(**fields: object) -> RegisteredProduct:
    return RegisteredProduct(
        product_id="P",
        names=(PLAIN,),
        clause_codes=(OWN,),
        schema_pack_id="schemapack_whole_life_insurance",
        materials=(RegisteredMaterial(knowledge_id="old-terms", sha256="c" * 64, role="terms"),),
        **fields,
    )


def terms(head: str) -> Upload:
    return Upload(knowledge_id="new", file_name="材料条款.pdf", sha256="a" * 64, head=head)


@pytest.mark.parametrize("label", ["备案编号:", "编号", "条款编号:"])
def test_a_labelled_code_is_a_citation_that_never_creates_a_product(label: str) -> None:
    head = label + OWN + PLAIN + "阅读指引"
    expect(attribute(terms(head), []), "QUARANTINE", "no_product_anchor")
    expect(attribute(terms(head), [fictitious()]), "QUARANTINE", "anchor_conflict")


def test_a_cited_other_code_is_not_a_new_version() -> None:
    head = PLAIN + "阅读指引请参见其他条款编号平安人寿〔2026〕终身寿险302号"
    result = attribute(terms(head), [fictitious()])
    expect(result, "NEEDS_CONFIRM", "same_role_differs", "P")
    assert result.replaces == ()
    expect(attribute(terms(head), []), "QUARANTINE", "no_product_anchor")


def test_the_leading_code_still_creates_and_versions() -> None:
    created = attribute(terms(OWN + PLAIN + "阅读指引"), [])
    expect(created, "CREATE", "new_product")
    assert created.display_name == PLAIN
    versioned = attribute(
        terms("平安人寿〔2026〕终身寿险302号" + PLAIN + "阅读指引"), [fictitious()]
    )
    expect(versioned, "NEW_VERSION", "new_clause_code", "P")
    assert versioned.replaces == ("old-terms",)
