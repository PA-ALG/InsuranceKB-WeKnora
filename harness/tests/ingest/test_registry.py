"""S5b-2 acceptance (protected, written by Claude): the product registry (Spec §2.1, §2.4)."""

import json
import os
from pathlib import Path

import pytest

from insurance_harness.ingest.registry import (
    ProductRegistry,
    RegistryError,
    SeedProduct,
    load_registry,
    save_registry,
    seed_registry,
)
from insurance_harness.ingest.source_map import SourceEntry, SourceMap
from tests.ingest.upload_helpers import (
    PRODUCTS,
    RAW_KB,
    SPACE,
    Pages,
    entry,
    knowledge_id,
    raw,
    registry,
)

ROLES = ("terms", "brochure", "rate_table")


def written(tmp_path: Path, value: ProductRegistry) -> Path:
    path = tmp_path / "registry.json"
    save_registry(value, path)
    return path


# 1. Format ------------------------------------------------------------------------------------


def test_a_saved_registry_loads_back_unchanged(tmp_path: Path) -> None:
    value = registry(p1828=entry("1828", *ROLES), p1814=entry("1814", "terms"))
    assert load_registry(written(tmp_path, value)) == value


@pytest.mark.parametrize(
    "breakage",
    ["unknown-field", "repeated-knowledge", "empty-names", "unknown-role", "wrong-contract"],
)
def test_an_invalid_registry_is_refused(tmp_path: Path, breakage: str) -> None:
    document = json.loads(
        registry(p1828=entry("1828", *ROLES), p1814=entry("1814", "terms")).model_dump_json()
    )
    if breakage == "unknown-field":
        document["extra"] = 1
    elif breakage == "repeated-knowledge":
        document["products"]["1814"]["materials"].append(
            document["products"]["1828"]["materials"][0]
        )
    elif breakage == "empty-names":
        document["products"]["1828"]["names"] = []
    elif breakage == "unknown-role":
        document["products"]["1828"]["materials"][0]["role"] = "poster"
    else:
        document["contract"] = "product-registry.v0"
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RegistryError) as caught:
        load_registry(path)
    assert caught.value.code == "REGISTRY_INVALID"


def test_a_failed_save_leaves_the_old_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = written(tmp_path, registry(p1828=entry("1828", "terms")))
    before = path.read_bytes()

    def broken(source: object, target: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError):
        save_registry(registry(p1828=entry("1828", *ROLES)), path)
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["registry.json"]


def test_the_source_map_is_the_existing_format_in_a_fixed_order() -> None:
    value = registry(p1828=entry("1828", "rate_table", "terms"), p1814=entry("1814", "brochure"))
    source_map = value.source_map()
    assert isinstance(source_map, SourceMap)
    assert source_map.space_id == SPACE
    assert list(source_map.products) == ["1814", "1828"]
    assert source_map.products["1828"] == [
        SourceEntry(knowledge_id=knowledge_id("1828", "rate_table"), parse_attempt=1),
        SourceEntry(knowledge_id=knowledge_id("1828", "terms"), parse_attempt=1),
    ]
    SourceMap.model_validate(json.loads(source_map.model_dump_json()))


def test_facts_give_the_name_and_pack_compiling_needs() -> None:
    facts = registry(p1828=entry("1828", "terms")).facts("1828")
    assert (facts.name, facts.schema_pack_id) == (
        PRODUCTS["1828"]["name"],
        PRODUCTS["1828"]["schema_pack_id"],
    )
    with pytest.raises(RegistryError):
        registry(p1828=entry("1828", "terms")).facts("9999")


def test_registered_products_feed_the_attribution_core() -> None:
    registered = registry(p1828=entry("1828", "terms", "brochure")).registered()
    assert [p.product_id for p in registered] == ["1828"]
    assert {m.role for m in registered[0].materials} == {"terms", "brochure"}
    assert registered[0].clause_codes == (PRODUCTS["1828"]["clause_code"],)


# 11. Seeding ----------------------------------------------------------------------------------


def seed_inputs(*product_ids: str) -> tuple[list[SourceMap], dict[str, SeedProduct]]:
    maps = [
        SourceMap(
            space_id=SPACE,
            products={
                pid: [
                    SourceEntry(knowledge_id=knowledge_id(pid, role), parse_attempt=1)
                    for role in ROLES
                ]
            },
        )
        for pid in product_ids
    ]
    facts = {
        pid: SeedProduct(
            name=PRODUCTS[pid]["name"],
            clause_code=PRODUCTS[pid]["clause_code"],
            schema_pack_id=PRODUCTS[pid]["schema_pack_id"],
        )
        for pid in product_ids
    }
    return maps, facts


def test_seeding_reproduces_the_hand_written_source_maps() -> None:
    maps, facts = seed_inputs("1828", "1814", "594")
    sources = [raw(pid, role) for pid in ("1828", "1814", "594") for role in ROLES]
    seeded = seed_registry(SPACE, RAW_KB, maps, sources, Pages(), facts)
    merged = {pid: entries for source_map in maps for pid, entries in source_map.products.items()}
    exported = seeded.source_map().products
    assert set(exported) == set(merged)
    for pid, entries in merged.items():
        assert sorted(exported[pid], key=lambda e: e.knowledge_id) == sorted(
            entries, key=lambda e: e.knowledge_id
        )
    assert {m.role for m in seeded.products["1828"].materials} == set(ROLES)
    assert seeded.products["594"].origin == "seeded"
    assert seeded.pending == [] and seeded.decisions == []


def test_seeding_fails_when_a_role_cannot_be_recognised() -> None:
    maps, facts = seed_inputs("1828")
    sources = [raw("1828", role) for role in ROLES]
    sources[1] = raw("1828", "brochure", file_name="scan-0001.pdf")
    with pytest.raises(RegistryError) as caught:
        seed_registry(SPACE, RAW_KB, maps, sources, Pages(), facts)
    assert caught.value.code == "SEED_INVALID"


def test_seeding_fails_when_a_mapped_material_is_not_in_the_listing() -> None:
    maps, facts = seed_inputs("1828")
    sources = [raw("1828", "terms"), raw("1828", "brochure")]
    with pytest.raises(RegistryError) as caught:
        seed_registry(SPACE, RAW_KB, maps, sources, Pages(), facts)
    assert caught.value.code == "SEED_INVALID"
