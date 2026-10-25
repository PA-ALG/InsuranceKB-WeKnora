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
    assert policy.version == "2026-10-24.1"
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
        "attribution-policy@2026-10-24.1"
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
