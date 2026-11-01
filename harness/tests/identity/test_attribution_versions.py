"""PV-1 acceptance (written by Claude): version-aware attribution and new versions beside old ones.

Spec docs/design/slices/PV-1-登记表v2与版本迁移.md §3; PV-0 appendix A §1.3 (the ordered table);
PV-0 §4.2 (a new version no longer replaces the old one).
"""

import hashlib

import pytest

from insurance_harness.identity.attribution import (
    Attribution,
    RegisteredProduct,
    attribute,
    load_attribution_policy,
)
from insurance_harness.identity.confirmation import choices, conclude
from insurance_harness.ingest.registry import record
from insurance_harness.ingest.registry_migration import plan_migration
from insurance_harness.ingest.uploads import attribute_uploads
from tests.identity.test_attribution import PRODUCTS, fold, registered, upload
from tests.ingest.upload_helpers import Pages, entry, raw, registry
from tests.ingest.version_helpers import catalog, of, version

CODE = PRODUCTS["1828"]["clause_code"]
NEW_CODE = CODE.replace("174号", "999号")
NAME = PRODUCTS["1828"]["name"]


def keyed(
    product_id: str, key: str | None, *roles: str, codes: tuple[str, ...] = ()
) -> RegisteredProduct:
    product = registered(product_id, *roles)
    return product.model_copy(
        update={"version_key": key, "clause_codes": codes or product.clause_codes}
    )


def expect(result: Attribution, outcome: str, reason: str, product_id: str | None = None) -> None:
    assert (result.outcome, result.reason) == (outcome, reason), result
    if product_id is not None:
        assert result.product_id == product_id, result


def new_id(code: str) -> str:
    policy = load_attribution_policy()
    digest = hashlib.sha256(fold(code).encode()).hexdigest()[: policy.created_id_hex]
    return policy.created_id_prefix + digest


TERMS = upload("1828", "terms", sha256="e" * 64)  # the 1828 terms, not a registered file
NEW_TERMS = upload("1828", "terms", sha256="e" * 64, head=TERMS.head.replace("174号", "999号", 1))


# 1. The ordered table --------------------------------------------------------------------------


def test_row_1_the_version_key_names_the_entry_even_without_its_code() -> None:
    old = "平安人寿〔2024〕疾病保险001号"
    result = attribute(TERMS, [keyed("1828", "1828-1", codes=(old,))], catalog=catalog(of("1828")))
    expect(result, "SUPPLEMENT", "matched_by_version_key", "1828")  # not a new version


def test_row_2_the_version_key_and_the_code_naming_another_entry_conflict() -> None:
    other = keyed("1826", None, codes=(CODE,))
    result = attribute(TERMS, [keyed("1828", "1828-1"), other], catalog=catalog(of("1828")))
    expect(result, "QUARANTINE", "anchor_conflict")


@pytest.mark.parametrize("registered_too", [False, True])
def test_row_3_a_shared_code_is_quarantined_and_never_creates(registered_too: bool) -> None:
    shared = catalog(of("1828", key="1828-1"), of("1828", key="1828-2"))
    products = [keyed("1828", None)] if registered_too else []
    result = attribute(TERMS, products, catalog=shared)
    expect(result, "QUARANTINE", "shared_clause_code")
    assert result.product_id is None


def test_row_4_a_code_two_entries_hold_conflicts() -> None:
    both = [keyed("1828", None), keyed("1826", None, codes=(CODE,))]
    expect(attribute(TERMS, both, catalog=catalog(of("1828"))), "QUARANTINE", "anchor_conflict")


def test_row_5_the_one_entry_holding_the_code_is_it_unless_its_key_differs() -> None:
    result = attribute(TERMS, [keyed("1828", None, "brochure")], catalog=catalog(of("1828")))
    expect(result, "SUPPLEMENT", "matched_by_clause_code", "1828")
    other_key = attribute(TERMS, [keyed("1828", "1828-7")], catalog=catalog(of("1828")))
    expect(other_key, "QUARANTINE", "anchor_conflict")


def test_row_6_a_new_product_carries_its_version_key_when_the_catalog_knows_it() -> None:
    created = attribute(TERMS, [], catalog=catalog(of("1828", key="1828-3")))
    expect(created, "CREATE", "new_product", new_id(CODE))
    assert created.version_key == "1828-3"
    unknown = attribute(TERMS, [], catalog=catalog(of("1814")))
    expect(unknown, "CREATE", "new_product", new_id(CODE))
    assert unknown.version_key is None


def test_without_a_catalog_the_rules_are_unchanged() -> None:
    expect(attribute(TERMS, []), "CREATE", "new_product", new_id(CODE))


# 2. A new version is a new entry beside the old one ----------------------------------------------


def test_new_terms_of_a_registered_name_are_a_new_entry_beside_it() -> None:
    old = registered("1828", "terms", "brochure", "rate_table")
    result = attribute(
        NEW_TERMS, [old], catalog=catalog(of("1828"), version("1828-2", NAME, NEW_CODE))
    )
    expect(result, "NEW_VERSION", "new_clause_code", new_id(NEW_CODE))
    assert result.candidates == ("1828",)
    assert result.replaces == ()
    assert (result.display_name, result.schema_pack_id) == (
        NAME,
        PRODUCTS["1828"]["schema_pack_id"],
    )
    assert (result.clause_code, result.version_key) == (fold(NEW_CODE), "1828-2")


def test_a_new_version_whose_id_is_taken_conflicts() -> None:
    taken = RegisteredProduct(
        product_id=new_id(NEW_CODE), names=("其他产品",), clause_codes=(), schema_pack_id="x"
    )
    result = attribute(NEW_TERMS, [registered("1828", "terms"), taken])
    expect(result, "QUARANTINE", "anchor_conflict")


def test_the_old_entry_keeps_its_materials_and_the_new_one_is_linked() -> None:
    value = registry(p1828=entry("1828", "terms", "brochure", "rate_table"))
    chained = catalog(
        of("1828", end="2026-01-01", status="discontinued"),
        version("1828-2", NAME, NEW_CODE, start="2026-01-01"),
    )
    v2, _ = plan_migration(value, chained)
    source = raw("1828", "terms", knowledge_id="k-1828-terms2", sha256="e" * 64)
    run = attribute_uploads(
        v2,
        [source],
        Pages(heads={"k-1828-terms2": NEW_TERMS.head}, sources=[source]),
        catalog=chained,
    )
    old, new = run.registry.products["1828"], run.registry.products[new_id(NEW_CODE)]
    assert old == v2.products["1828"]  # materials, codes and version untouched; nothing retired
    assert [m.knowledge_id for m in new.materials] == ["k-1828-terms2"]
    assert (new.names, new.origin) == ([NAME], "created")
    assert new.version is not None
    assert (new.version.version_key, new.version.predecessor) == ("1828-2", "1828")


def test_a_v1_registry_gets_the_new_entry_without_version_fields() -> None:
    value = registry(p1828=entry("1828", "terms", "brochure"))
    source = raw("1828", "terms", knowledge_id="k-1828-terms2", sha256="e" * 64)
    run = attribute_uploads(
        value, [source], Pages(heads={"k-1828-terms2": NEW_TERMS.head}, sources=[source])
    )
    assert run.registry.products["1828"] == value.products["1828"]
    created = run.registry.products[new_id(NEW_CODE)]
    assert created.version is None and created.retired == []


# 3. A person naming the old product for new terms concludes the new entry -------------------------


def test_a_person_choosing_the_registered_product_concludes_a_new_entry() -> None:
    bare = upload("1828", "terms", sha256="e" * 64, head=fold(NEW_CODE) + "正文内容说明文字")
    products = [registered("1828", "terms", "brochure", "rate_table")]
    pending = attribute(bare, products)
    expect(pending, "QUARANTINE", "no_product_anchor")
    key = next(c.key for c in choices(pending, products) if c.value == "1828")
    result = conclude(pending, key, bare, products)
    expect(result, "NEW_VERSION", "new_clause_code", new_id(NEW_CODE))
    assert result.candidates == ("1828",)
    value = registry(p1828=entry("1828", "terms", "brochure", "rate_table"))
    source = raw("1828", "terms", knowledge_id="k-bare", sha256="e" * 64)
    assert record(value, source, result) is True
    assert new_id(NEW_CODE) in value.products
    assert (
        value.products["1828"].materials
        == entry("1828", "terms", "brochure", "rate_table").materials
    )
