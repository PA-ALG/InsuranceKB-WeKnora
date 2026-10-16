"""S4h acceptance: a product never sees examples taken from itself (Spec §2.1–§2.2).

Protected file: written by Claude. Examples come from held-out products (S4d Spec §3.4); once such
a product enters evaluation (1828), its own examples would hand it the answers. Every example
names its product_id, and the selection request for a product drops that product's examples.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from insurance_harness.compilers.schema_fields.cards import all_cards, card_payload
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.prompt import build_selection_request
from insurance_harness.eval.product_sources import declared_pack

PACK = "schemapack_critical_illness_insurance"


def definition(key: str) -> FieldDefinition:
    return FieldDefinition(
        field_key=key, short_title=key, description=key, value_spec="文本", ordinal=0, pack_id=PACK
    )


def examples_of(product: str) -> list[str]:
    """Field keys whose cards hold an example of this pack taken from the product."""
    return [
        key
        for key, card in all_cards().items()
        for example in card.get("examples", [])
        if example["schema_pack_id"] == PACK and example["product_id"] == product
    ]


def test_every_example_names_its_product() -> None:
    for key, card in all_cards().items():
        for example in card.get("examples", []):
            assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", example.get("product_id", "")), key


def test_a_product_does_not_receive_its_own_examples() -> None:
    keys = examples_of("1828")
    assert keys, "the critical illness examples are taken from 1828"
    for key in keys:
        own = card_payload(definition(key), entity_id="1828")
        other = card_payload(definition(key), entity_id="9999")
        assert own is not None and other is not None
        assert own.get("examples", []) == []
        assert other.get("examples"), "another product still learns from them"
        assert all("product_id" not in example for example in other["examples"])


def test_the_selection_request_drops_the_compiled_products_examples() -> None:
    keys = examples_of("1828")
    request = build_selection_request("1828", [definition(k) for k in keys], "D1P1S1 条款")
    fields = json.loads(request.user)["schema_fields"]
    assert all("examples" not in field.get("card", {}) for field in fields)
    other = build_selection_request("9999", [definition(k) for k in keys], "D1P1S1 条款")
    assert any(
        "examples" in field.get("card", {}) for field in json.loads(other.user)["schema_fields"]
    )


def test_the_pack_is_declared_by_golden_v2_first(tmp_path: Path) -> None:
    def manifest(version: str, products: dict[str, object]) -> None:
        path = tmp_path / f"dataset/golden/{version}/manifest.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"products": products}), encoding="utf-8")

    manifest("v1", {"0001": {"pack_id": "pack-from-v1"}})
    with pytest.raises(ValueError):
        declared_pack(tmp_path, "1828")
    manifest("v2", {"1828": {"pack_id": PACK}, "0001": {"pack_id": "pack-from-v2"}})
    assert declared_pack(tmp_path, "1828") == PACK
    assert declared_pack(tmp_path, "0001") == "pack-from-v2"
