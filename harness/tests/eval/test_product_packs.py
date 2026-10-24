"""S5a acceptance: every dataset product declares its pack, from Golden or versioned data (§2.2).

Protected file: written by Claude. Products outside Golden had no pack, so they could not be
compiled. The declarations are data, ruled by the filed product type (养老年金 is an annuity, user
2026-10-18); each names a pack in the catalog, and a product declared two ways must agree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.eval.product_sources import declared_pack

REPO = Path(__file__).resolve().parents[3]
CATALOG = REPO / SCHEMA_PACK_CATALOG
NEW = {
    "1818": "schemapack_endowment_insurance",
    "1837": "schemapack_whole_life_insurance",
    "5003": "schemapack_whole_life_insurance",
    "1830": "schemapack_annuity_insurance",
    "1847H": "schemapack_annuity_insurance",
    "2650": "schemapack_medical_insurance",
    "594": "schemapack_medical_insurance",
}


def plan_codes() -> list[str]:
    codes = []
    for meta in sorted((REPO / "dataset" / "shouxian_product").glob("*/product_meta.json")):
        code = json.loads(meta.read_text(encoding="utf-8")).get("planCode")
        if isinstance(code, str) and code:
            codes.append(code)
    return codes


def test_every_dataset_product_resolves_to_a_catalog_pack() -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    packs = {entry["pack"]["schema_pack_id"] for entry in catalog["entries"]}
    codes = plan_codes()
    assert len(codes) >= 13
    for code in codes:
        assert declared_pack(REPO, code) in packs, code


def test_the_new_declarations_follow_the_filed_product_type() -> None:
    assert {code: declared_pack(REPO, code) for code in NEW} == NEW
    data = json.loads((REPO / "dataset" / "product_packs.json").read_text(encoding="utf-8"))
    assert data["version"] and data["packs"] == NEW


def write(repo: Path, relative: str, content: object) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    text = content if isinstance(content, str) else json.dumps(content)
    path.write_text(text, encoding="utf-8")


def test_a_product_declared_two_ways_must_agree(tmp_path: Path) -> None:
    write(tmp_path, "dataset/golden/v2/manifest.json", {"products": {"A": {"pack_id": "pack_a"}}})
    write(tmp_path, "dataset/product_packs.json", {"version": "v", "packs": {"A": "pack_b"}})
    with pytest.raises(ValueError):
        declared_pack(tmp_path, "A")
    write(tmp_path, "dataset/product_packs.json", {"version": "v", "packs": {"A": "pack_a"}})
    assert declared_pack(tmp_path, "A") == "pack_a"


def test_a_product_only_in_the_data_file_gets_its_pack(tmp_path: Path) -> None:
    write(tmp_path, "dataset/product_packs.json", {"version": "v", "packs": {"B": "pack_b"}})
    assert declared_pack(tmp_path, "B") == "pack_b"
    with pytest.raises(ValueError):
        declared_pack(tmp_path, "C")
    assert declared_pack(tmp_path, "C", "explicit") == "explicit"


@pytest.mark.parametrize(
    "content",
    [
        "{",
        {"packs": {"B": "pack_b"}},
        {"version": "v", "packs": {"B": 3}},
        {"version": "v", "packs": []},
    ],
    ids=["not json", "no version", "pack not a string", "packs not an object"],
)
def test_a_malformed_data_file_is_refused(tmp_path: Path, content: object) -> None:
    write(tmp_path, "dataset/product_packs.json", content)
    with pytest.raises(ValueError):
        declared_pack(tmp_path, "B")
