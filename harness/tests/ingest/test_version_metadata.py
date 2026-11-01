"""PV-4a acceptance: an entity's version identity from the registry (PV-4 Spec §3.1, §3.2).

Protected file: written by Claude. A registry entry without a version record (v1, or not yet
migrated) keeps today's entity exactly; a v2 entry publishes its real plan code, version key,
single clause code, sale period with its basis, and family. The compile publish path builds the
same entity, so a later compile never writes the entity back to its old shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.compilers.schema_fields.page import product_page
from insurance_harness.contracts.knowledge import ProductFamily as PublishedFamily
from insurance_harness.contracts.knowledge import ProductLifecycle
from insurance_harness.ingest.product_versions import MetadataBasis, ProductFamily, ProductVersion
from insurance_harness.ingest.registry import ProductEntry, RegistryError, save_registry
from insurance_harness.ingest.version_metadata import entity_metadata, registry_metadata
from tests.ingest.upload_helpers import entry, registry

REPO = Path(__file__).resolve().parents[3]
COMMIT = "d" * 40
BASIS = MetadataBasis(
    repository="PA-ALG/pingan-life-product-documents",
    commit=COMMIT,
    catalog_sha256="e" * 64,
    synced_at="2026-11-01T08:00:00Z",
)


def versioned(product: ProductEntry, **fields: object) -> ProductEntry:
    defaults: dict[str, object] = {
        "version_key": "2635-1",
        "plan_code": "2635",
        "version_no": 1,
        "sale_start": "2024-04-23",
        "sale_end": "2024-09-01",
        "source_status": "discontinued",
        "family": ProductFamily(key="智盈倍护", display_name="智盈倍护"),
    }
    defaults.update(fields)
    return product.model_copy(update={"version": ProductVersion(**defaults)})  # type: ignore[arg-type]


def test_an_entry_without_a_version_keeps_todays_identity() -> None:
    meta = entity_metadata("1828", entry("1828", "terms"), None)
    assert meta.identifiers == {"product_code": "1828"}
    assert meta.lifecycle is None
    assert meta.family is None


def test_a_versioned_entry_publishes_its_filed_identity() -> None:
    product = versioned(entry("1828", "terms"))
    meta = entity_metadata("sc-abc", product, BASIS)
    assert meta.identifiers == {
        "product_code": "2635",
        "version_key": "2635-1",
        "filing_no": product.clause_codes[0],
    }
    assert meta.lifecycle == ProductLifecycle(
        sale_start="2024-04-23",
        sale_end="2024-09-01",
        source_status="discontinued",
        basis_commit=COMMIT,
        basis_date="2026-11-01",
    )
    assert meta.family == PublishedFamily(key="智盈倍护", display_name="智盈倍护")


def test_unknown_parts_are_omitted_never_guessed() -> None:
    product = versioned(entry("1828", "terms"), version_key=None, plan_code=None, version_no=None,
                        sale_start=None, sale_end=None, source_status=None, family=None)
    product = product.model_copy(update={"clause_codes": ["码一", "码二"]})
    meta = entity_metadata("sc-abc", product, BASIS)
    assert meta.identifiers == {}
    assert meta.lifecycle is None
    assert meta.family is None


def test_a_lifecycle_without_a_basis_has_no_basis_fields() -> None:
    meta = entity_metadata("2635", versioned(entry("1828", "terms")), None)
    assert meta.lifecycle is not None
    assert (meta.lifecycle.basis_commit, meta.lifecycle.basis_date) == (None, None)


def test_the_product_page_carries_the_metadata() -> None:
    meta = entity_metadata("sc-abc", versioned(entry("1828", "terms")), BASIS)
    pack = entry("1828", "terms").schema_pack_id
    page = product_page(
        REPO / SCHEMA_PACK_CATALOG, pack, entity_id="sc-abc", name="演示", metadata=meta
    )
    assert page.entity.identifiers == meta.identifiers
    assert page.entity.lifecycle == meta.lifecycle
    assert page.entity.product_family == meta.family
    legacy = product_page(REPO / SCHEMA_PACK_CATALOG, pack, entity_id="sc-abc", name="演示")
    assert legacy.entity.identifiers == {"product_code": "sc-abc"}
    assert legacy.entity.lifecycle is None and legacy.entity.product_family is None


def test_registry_metadata_reads_one_product(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    save_registry(registry(p1828=entry("1828", "terms")), path)
    assert registry_metadata(path, "1828").identifiers == {"product_code": "1828"}
    with pytest.raises(RegistryError):
        registry_metadata(path, "9999")
