"""S5b-3c-1 acceptance (protected, written by Claude): what a person may decide about a material the
attribution rules could not settle, and what each choice concludes.

Spec docs/design/slices/S5b-3c-1-人工确认的选项与结论.md §3. Real openings of the S5b-1 fixture,
across endowment (1818, 1826), critical illness (1828), accident (1814) and annuity (1830) products.
"""

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path

import pytest

from insurance_harness.identity.attribution import (
    Attribution,
    AttributionInputError,
    AttributionPolicy,
    RegisteredMaterial,
    RegisteredProduct,
    Upload,
    attribute,
    load_attribution_policy,
)
from insurance_harness.identity.confirmation import Choice, ConfirmationError, choices, conclude

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "attribution_heads.json").read_text(encoding="utf-8")
)
PRODUCTS = {product["product_id"]: product for product in FIXTURE["products"]}
KEYWORDS = {"terms": "条款", "brochure": "说明书", "rate_table": "费率表"}
OPTION_KEY = re.compile(r"^[a-z0-9][a-z0-9:._-]{0,127}$")
POLICY = load_attribution_policy()
PACKS = list(dict.fromkeys(entry.schema_pack_id for entry in POLICY.classifications))
UNNAMED = "平安安心保障计划"  # a title no classification suffix recognises


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text) if not c.isspace())


def material(product_id: str, role: str) -> dict[str, str]:
    return next(m for m in PRODUCTS[product_id]["materials"] if KEYWORDS[role] in m["file_name"])


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
    product_id: str,
    *roles: str,
    names: tuple[str, ...] | None = None,
    extra: tuple[RegisteredMaterial, ...] = (),
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
        )
        + extra,
    )


def product_key(product_id: str) -> str:
    return "product:" + hashlib.sha256(product_id.encode("utf-8")).hexdigest()[:16]


def pending_of(item: Upload, registry: list[RegisteredProduct], reason: str) -> Attribution:
    result = attribute(item, registry)
    assert (result.outcome, result.reason) == ("NEEDS_CONFIRM", reason)
    return result


def concluded(
    pending: Attribution, key: str, item: Upload, registry: list[RegisteredProduct]
) -> Attribution:
    """A conclusion is never the pending question again, and carries the current policy."""
    result = conclude(pending, key, item, registry)
    assert (result.outcome, result.reason) != (pending.outcome, pending.reason)
    assert result.policy_ref == POLICY.policy_ref
    return result


def keys(pending: Attribution, registry: list[RegisteredProduct]) -> list[str]:
    offered = choices(pending, registry)
    found = [choice.key for choice in offered]
    assert all(OPTION_KEY.fullmatch(key) for key in found)
    assert len(set(found)) == len(found) <= 50
    return found


# The four questions -----------------------------------------------------------------------------


def same_role() -> tuple[Attribution, Upload, list[RegisteredProduct]]:
    item = upload("1818", "brochure", knowledge_id="k-new", sha256="f" * 64)
    registry = [registered("1818", "terms", "brochure")]
    return pending_of(item, registry, "same_role_differs"), item, registry


def two_named(*roles_1814: str) -> tuple[Attribution, Upload, list[RegisteredProduct]]:
    head = (
        fold(PRODUCTS["1828"]["name"])
        + "、"
        + fold(PRODUCTS["1814"]["name"])
        + "产品说明书在本说明书中"
    )
    item = upload("1828", "brochure", knowledge_id="k-two", sha256="c" * 64, head=head)
    registry = [registered("1814", "terms", *roles_1814), registered("1828", "terms")]
    return pending_of(item, registry, "multiple_products"), item, registry


def unrecognised_role(product_id: str) -> tuple[Attribution, Upload, list[RegisteredProduct]]:
    item = upload(product_id, "brochure", knowledge_id="k-scan", file_name="scan-0001.pdf")
    registry = [registered(product_id, "terms")]
    return pending_of(item, registry, "role_unresolved"), item, registry


def unrecognised_pack(product_id: str) -> tuple[Attribution, Upload, list[RegisteredProduct]]:
    head = material(product_id, "terms")["head"].replace(
        fold(PRODUCTS[product_id]["name"]), UNNAMED, 1
    )
    item = upload(product_id, "terms", knowledge_id="k-unnamed", sha256="d" * 64, head=head)
    registry = [registered("1818", "terms", "brochure")]
    return pending_of(item, registry, "pack_unresolved"), item, registry


# 1. Choices -------------------------------------------------------------------------------------


def test_each_question_offers_its_choices_in_a_fixed_order() -> None:
    pending, _, registry = same_role()
    assert keys(pending, registry) == ["replace", "supplement", "ignore"]

    pending, _, registry = two_named()
    assert pending.candidates == ("1814", "1828")
    assert keys(pending, registry) == [product_key("1814"), product_key("1828"), "ignore"]
    assert choices(pending, registry)[0] == Choice(
        key=product_key("1814"), kind="product", value="1814"
    )

    pending, _, registry = unrecognised_role("1830")
    assert keys(pending, registry) == ["role:terms", "role:brochure", "role:rate_table", "ignore"]
    assert choices(pending, registry)[1] == Choice(
        key="role:brochure", kind="role", value="brochure"
    )

    pending, _, registry = unrecognised_pack("1830")
    assert keys(pending, registry) == [f"pack:{pack}" for pack in PACKS] + ["ignore"]
    assert choices(pending, registry)[-1] == Choice(key="ignore", kind="ignore")


def test_a_candidate_no_longer_registered_is_not_offered() -> None:
    pending, _, registry = two_named()
    assert keys(pending, registry[1:]) == [product_key("1828"), "ignore"]
    pending, _, _ = same_role()
    assert keys(pending, []) == ["ignore"]
    pending, _, _ = unrecognised_role("1830")
    assert keys(pending, []) == ["ignore"]


@pytest.mark.parametrize(
    "result",
    [
        attribute(
            upload("1818", "brochure", knowledge_id="again"),
            [registered("1818", "terms", "brochure")],
        ),
        attribute(upload("1830", "terms"), [registered("1818", "terms")]),
    ],
    # S11a: a quarantined material now has choices (tests/ingest/test_quarantine_confirmation.py).
    ids=["duplicate", "create"],
)
def test_only_a_question_for_a_person_has_choices(result: Attribution) -> None:
    assert result.outcome != "NEEDS_CONFIRM"
    with pytest.raises(ConfirmationError) as failure:
        choices(result, [registered("1818", "terms", "brochure")])
    assert failure.value.code == "NOT_CONFIRMABLE"


# 2. Replace, supplement, ignore -----------------------------------------------------------------


def test_replace_supplement_and_ignore_settle_a_second_material_of_the_same_role() -> None:
    pending, item, registry = same_role()
    replaced = concluded(pending, "replace", item, registry)
    assert (replaced.outcome, replaced.reason) == ("REPLACE", "confirmed_replace")
    assert (replaced.product_id, replaced.role, replaced.replaces) == (
        "1818",
        "brochure",
        ("k-1818-brochure",),
    )
    supplemented = concluded(pending, "supplement", item, registry)
    assert (supplemented.outcome, supplemented.reason) == ("SUPPLEMENT", "confirmed_supplement")
    assert (supplemented.product_id, supplemented.role, supplemented.replaces) == (
        "1818",
        "brochure",
        (),
    )
    ignored = concluded(pending, "ignore", item, registry)
    assert (ignored.outcome, ignored.reason) == ("IGNORED", "confirmed_ignore")
    assert (ignored.product_id, ignored.role, ignored.candidates) == ("1818", "brochure", ("1818",))


def test_replacing_terms_lists_every_registered_terms_material() -> None:
    extra = (RegisteredMaterial(knowledge_id="k-1826-terms-old", sha256="e" * 64, role="terms"),)
    registry = [registered("1826", "terms", "brochure", extra=extra)]
    item = upload("1826", "terms", knowledge_id="k-new-terms", sha256="a" * 64)
    pending = pending_of(item, registry, "same_role_differs")
    result = concluded(pending, "replace", item, registry)
    assert result.replaces == ("k-1826-terms", "k-1826-terms-old")


# 3. Choosing a product --------------------------------------------------------------------------


def test_choosing_one_of_two_named_products_files_the_material_there() -> None:
    pending, item, registry = two_named()
    for product_id in ("1814", "1828"):
        result = concluded(pending, product_key(product_id), item, registry)
        assert (result.outcome, result.product_id, result.role) == (
            "SUPPLEMENT",
            product_id,
            "brochure",
        )


def test_a_chosen_product_that_already_has_the_role_asks_the_next_question() -> None:
    pending, item, registry = two_named("brochure")
    result = concluded(pending, product_key("1814"), item, registry)
    assert (result.outcome, result.reason, result.product_id) == (
        "NEEDS_CONFIRM",
        "same_role_differs",
        "1814",
    )
    assert keys(result, registry) == ["replace", "supplement", "ignore"]


def test_two_products_sharing_an_alias_are_told_apart_by_the_choice() -> None:
    alias = PRODUCTS["1818"]["name"]
    registry = [
        registered("1818", "terms"),
        registered("1826", "terms", names=(PRODUCTS["1826"]["name"], alias)),
    ]
    item = upload("1818", "brochure", knowledge_id="k-alias")
    pending = pending_of(item, registry, "multiple_products")
    for product_id in ("1818", "1826"):
        result = concluded(pending, product_key(product_id), item, registry)
        assert (result.outcome, result.product_id) == ("SUPPLEMENT", product_id)


def test_a_file_two_products_hold_is_a_duplicate_of_the_chosen_one() -> None:
    copy = RegisteredMaterial(
        knowledge_id="k-1826-copy", sha256=material("1818", "brochure")["sha256"], role="brochure"
    )
    registry = [registered("1818", "terms", "brochure"), registered("1826", "terms", extra=(copy,))]
    item = upload("1818", "brochure", knowledge_id="again")
    pending = pending_of(item, registry, "multiple_products")
    result = concluded(pending, product_key("1826"), item, registry)
    assert (result.outcome, result.product_id) == ("DUPLICATE", "1826")


# 4. Choosing a role -----------------------------------------------------------------------------


@pytest.mark.parametrize("product_id", ["1830", "1828"])
def test_a_confirmed_role_files_the_material_as_that_role(product_id: str) -> None:
    pending, item, registry = unrecognised_role(product_id)
    for role in ("brochure", "rate_table"):
        result = concluded(pending, f"role:{role}", item, registry)
        assert (result.outcome, result.product_id, result.role) == ("SUPPLEMENT", product_id, role)
    terms = concluded(pending, "role:terms", item, registry)
    assert (terms.outcome, terms.reason, terms.product_id, terms.role) == (
        "NEEDS_CONFIRM",
        "same_role_differs",
        product_id,
        "terms",
    )


# 5. Choosing a pack -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "product_id, pack",
    [("1830", "schemapack_annuity_insurance"), ("1828", "schemapack_critical_illness_insurance")],
)
def test_a_chosen_pack_creates_the_product_the_terms_name(product_id: str, pack: str) -> None:
    pending, item, registry = unrecognised_pack(product_id)
    result = concluded(pending, f"pack:{pack}", item, registry)
    code = PRODUCTS[product_id]["clause_code"]
    created = (
        POLICY.created_id_prefix
        + hashlib.sha256(code.encode()).hexdigest()[: POLICY.created_id_hex]
    )
    assert (
        result.outcome,
        result.product_id,
        result.display_name,
        result.schema_pack_id,
        result.role,
    ) == (
        "CREATE",
        created,
        UNNAMED,
        pack,
        "terms",
    )


def test_a_pack_never_overrides_a_suffix_the_rules_recognise() -> None:
    item = upload("1830", "terms")
    result = attribute(item, [registered("1818", "terms")], pack="schemapack_medical_insurance")
    assert (result.outcome, result.schema_pack_id) == ("CREATE", "schemapack_annuity_insurance")


# 6. Refusals ------------------------------------------------------------------------------------


def test_a_key_the_question_does_not_offer_is_unknown() -> None:
    cases = [
        (same_role(), product_key("1818")),
        (two_named(), "replace"),
        (unrecognised_pack("1830"), "pack:schemapack_unknown"),
        (unrecognised_role("1830"), "role:slides"),
        (same_role(), "Replace"),
    ]
    for (pending, item, registry), key in cases:
        with pytest.raises(ConfirmationError) as failure:
            conclude(pending, key, item, registry)
        assert failure.value.code == "CHOICE_UNKNOWN"


def test_only_the_ignore_choice_remains_once_the_product_is_gone() -> None:
    for pending, item, _ in (same_role(), unrecognised_role("1830")):
        assert concluded(pending, "ignore", item, []).outcome == "IGNORED"
        for key in ("replace", "supplement", "role:brochure"):
            with pytest.raises(ConfirmationError) as failure:
                conclude(pending, key, item, [])
            assert failure.value.code == "CHOICE_UNKNOWN"


INVALID_CHOICES: list[Callable[[Upload, list[RegisteredProduct]], Attribution]] = [
    lambda item, registry: attribute(item, registry, product="9999"),
    lambda item, registry: attribute(item, registry, role="slides"),
    lambda item, registry: attribute(item, registry, pack="schemapack_unknown"),
]


@pytest.mark.parametrize("call", INVALID_CHOICES, ids=["product", "role", "pack"])
def test_attribute_refuses_an_invalid_person_choice(
    call: Callable[[Upload, list[RegisteredProduct]], Attribution],
) -> None:
    with pytest.raises(AttributionInputError) as failure:
        call(upload("1818", "brochure"), [registered("1818", "terms")])
    assert failure.value.code == "CHOICE_INVALID"


def stale(pending: Attribution, key: str, item: Upload, registry: list[RegisteredProduct]) -> None:
    with pytest.raises(ConfirmationError) as failure:
        conclude(pending, key, item, registry)
    assert failure.value.code == "CHOICE_STALE"


def test_a_choice_the_registry_has_since_overtaken_is_stale() -> None:
    # The same-role material it would replace is gone.
    pending, item, _ = same_role()
    stale(pending, "replace", item, [registered("1818", "terms")])
    # The file is now the material of another product.
    pending, item, registry = two_named()
    taken = RegisteredMaterial(knowledge_id="k-1814-copy", sha256=item.sha256, role="brochure")
    stale(
        pending,
        product_key("1828"),
        item,
        [registered("1814", "terms", extra=(taken,)), registry[1]],
    )
    # The clause code it cites now belongs to another product.
    cited = item.model_copy(update={"head": item.head + PRODUCTS["1818"]["clause_code"]})
    pending = pending_of(cited, registry, "multiple_products")
    stale(pending, product_key("1828"), cited, [*registry, registered("1818", "terms")])
    # The title now names a registered product.
    pending, item, registry = unrecognised_pack("1830")
    renamed = registered("1828", "terms", names=(UNNAMED,))
    stale(pending, "pack:schemapack_annuity_insurance", item, [*registry, renamed])


# Review R2–R4 ------------------------------------------------------------------------------------


def test_a_chosen_product_must_agree_with_the_code_even_for_a_shared_file() -> None:
    shared = RegisteredMaterial(
        knowledge_id="k-1818-shared", sha256=material("1826", "terms")["sha256"], role="terms"
    )
    registry = [registered("1818", "terms", extra=(shared,)), registered("1826", "terms")]
    item = upload("1826", "terms", knowledge_id="k-again")
    pending = pending_of(item, registry, "multiple_products")
    conflict = attribute(item, registry, product="1818")
    assert (conflict.outcome, conflict.reason) == ("QUARANTINE", "anchor_conflict")
    stale(pending, product_key("1818"), item, registry)
    agreed = concluded(pending, product_key("1826"), item, registry)
    assert (agreed.outcome, agreed.product_id) == ("DUPLICATE", "1826")


@pytest.mark.parametrize("pack", ["UpperPack", "a" * 124], ids=["capitals", "too_long"])
def test_a_pack_that_cannot_be_an_option_key_is_refused(pack: str) -> None:
    pending, _, registry = unrecognised_pack("1830")
    document = POLICY.model_dump(mode="json")
    document["classifications"][0]["schema_pack_id"] = pack
    policy = AttributionPolicy.model_validate_json(json.dumps(document))
    with pytest.raises(ConfirmationError) as failure:
        choices(pending, registry, policy)
    assert failure.value.code == "NOT_CONFIRMABLE"


def test_a_registry_naming_one_product_twice_is_refused_in_any_order() -> None:
    pending, item, _ = same_role()
    one = RegisteredMaterial(knowledge_id="k-old-one", sha256="1" * 64, role="brochure")
    two = RegisteredMaterial(knowledge_id="k-old-two", sha256="2" * 64, role="brochure")
    twins = [registered("1818", "terms", extra=(one,)), registered("1818", "terms", extra=(two,))]
    for ordered in (twins, twins[::-1]):
        with pytest.raises(AttributionInputError) as listed:
            choices(pending, ordered)
        assert listed.value.code == "REGISTRY_DUPLICATE_PRODUCT"
        with pytest.raises(AttributionInputError) as replaced:
            conclude(pending, "replace", item, ordered)
        assert replaced.value.code == "REGISTRY_DUPLICATE_PRODUCT"
