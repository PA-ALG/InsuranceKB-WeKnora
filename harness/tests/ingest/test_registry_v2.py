"""PV-1 acceptance (written by Claude): the v2 registry format and its read-only entry.

Spec docs/design/slices/PV-1-登记表v2与版本迁移.md §2.3, §5; PV-0 appendix A §4 (read-only entry).
"""

import json
from pathlib import Path

import pytest

from insurance_harness.changes.options import registry_inputs
from insurance_harness.ingest.registry import (
    ProductRegistry,
    RegistryError,
    load_registry,
    save_registry,
)
from insurance_harness.ingest.registry_migration import plan_migration
from insurance_harness.ingest.uploads import attribute_uploads
from insurance_harness.ingest.version_catalog import (
    CatalogError,
    load_catalog,
    save_catalog,
)
from tests.ingest.upload_helpers import Pages, entry, raw, registry
from tests.ingest.version_helpers import catalog, of

ROLES = ("terms", "brochure", "rate_table")


def migrated() -> ProductRegistry:
    value = registry(p1828=entry("1828", *ROLES), p1814=entry("1814", *ROLES))
    planned, _ = plan_migration(value, catalog(of("1828"), of("1814")))
    return planned


def document(value: ProductRegistry) -> dict[str, object]:
    loaded: dict[str, object] = json.loads(value.model_dump_json())
    return loaded


def write(tmp_path: Path, data: dict[str, object]) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


# 1. Format -------------------------------------------------------------------------------------


def test_a_migrated_registry_is_v2_with_its_basis_and_versions() -> None:
    value = migrated()
    assert value.contract == "product-registry.v2"
    assert value.metadata_basis is not None and value.metadata_basis.commit == "c" * 40
    version = value.products["1828"].version
    assert version is not None
    assert (version.version_key, version.plan_code, version.version_no) == ("1828-1", "1828", 1)
    assert version.sale_start == "2025-10-01" and version.sale_end is None
    assert version.family is not None and version.family.key


@pytest.mark.parametrize(
    "breakage",
    ["v1-with-version", "v1-with-basis", "v2-without-basis", "duplicate-key", "dates", "dangling"],
)
def test_an_inconsistent_v2_registry_is_refused(tmp_path: Path, breakage: str) -> None:
    v1 = document(registry(p1828=entry("1828", *ROLES), p1814=entry("1814", *ROLES)))
    v2 = document(migrated())
    products = v2["products"]
    assert isinstance(products, dict)
    if breakage == "v1-with-version":
        data = v1 | {"products": products}
    elif breakage == "v1-with-basis":
        data = v1 | {"metadata_basis": v2["metadata_basis"]}
    elif breakage == "v2-without-basis":
        data = v2 | {"metadata_basis": None}
    elif breakage == "duplicate-key":
        products["1814"]["version"]["version_key"] = "1828-1"
        data = v2
    elif breakage == "dates":
        products["1828"]["version"]["sale_end"] = "2025-09-30"
        data = v2
    else:
        products["1828"]["version"]["predecessor"] = "9999"
        data = v2
    with pytest.raises(RegistryError) as caught:
        load_registry(write(tmp_path, data))
    assert caught.value.code == "REGISTRY_INVALID"


def test_a_v2_registry_saves_and_loads_back_unchanged(tmp_path: Path) -> None:
    path, value = tmp_path / "registry.json", migrated()
    save_registry(value, path)
    assert load_registry(path) == value


# 2. The read-only entry ------------------------------------------------------------------------


@pytest.mark.parametrize("contract", ["v1", "v2"])
def test_reading_never_writes_or_creates_files(tmp_path: Path, contract: str) -> None:
    value = registry(p1828=entry("1828", *ROLES)) if contract == "v1" else migrated()
    path = tmp_path / "registry.json"
    save_registry(value, path)
    before = (path.read_bytes(), path.stat().st_mtime_ns, sorted(tmp_path.iterdir()))
    load_registry(path)
    registry_inputs(path, ["1828"])  # the dry-run publish path reads facts and a source map
    assert (path.read_bytes(), path.stat().st_mtime_ns, sorted(tmp_path.iterdir())) == before


def test_a_v1_registry_stays_v1_after_a_run() -> None:
    value = registry(p1828=entry("1828", "terms"))
    brochure = raw("1828", "brochure")
    run = attribute_uploads(value, [brochure], Pages(sources=[brochure]))
    assert run.registry.contract == "product-registry.v1"
    assert all(p.version is None for p in run.registry.products.values())
    assert run.registry.metadata_basis is None


# 3. The catalog file a v2 registry names ---------------------------------------------------------


def test_the_catalog_file_loads_back_and_a_changed_one_is_refused(tmp_path: Path) -> None:
    value = catalog(of("1828"), of("1814"))
    path = tmp_path / "registry.json"
    name, digest = save_catalog(value, path)
    assert name == f"registry.json.catalog-{digest[:12]}.json"
    assert load_catalog(path, digest) == value
    assert save_catalog(value, path) == (name, digest)  # content-addressed: written once
    stored = tmp_path / name
    stored.write_text(stored.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(CatalogError) as caught:
        load_catalog(path, digest)
    assert caught.value.code == "CATALOG_INVALID"
    with pytest.raises(CatalogError) as missing:
        load_catalog(path, "0" * 64)
    assert missing.value.code == "CATALOG_INVALID"
