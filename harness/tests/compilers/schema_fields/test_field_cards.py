"""S4d acceptance: field cards are versioned data that reach the request (Spec §3.4).

Protected file: written by Claude. Cards define each field's boundary and three-state rule;
examples come only from held-out products and only the current insurance type's examples are sent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.compilers.schema_fields.cards import all_cards, card_payload, cards_version
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition, pack_definitions
from insurance_harness.compilers.schema_fields.engine import SchemaFieldsCompiler

REPO_ROOT = Path(__file__).resolve().parents[4]
CATALOG = REPO_ROOT / SCHEMA_PACK_CATALOG
EVAL_PACKS = (
    "schemapack_accident_insurance",
    "schemapack_disability_income_insurance",
    "schemapack_whole_life_insurance",
    "schemapack_endowment_insurance",
)
EVAL_PRODUCTS = ("1814", "1816", "1824", "1826")
RULE_KEYS = {
    "title",
    "sources",
    "source_scope",
    "definition",
    "includes",
    "excludes",
    "absent_rule",
    "unknown_rule",
    "bad",
}


@pytest.mark.parametrize("pack_id", EVAL_PACKS)
def test_every_field_of_the_evaluation_packs_has_a_card(pack_id: str) -> None:
    missing = [
        f.field_key for f in pack_definitions(CATALOG, pack_id) if f.field_key not in all_cards()
    ]
    assert missing == []


def test_cards_carry_rules_and_a_version() -> None:
    assert cards_version()
    for key, card in all_cards().items():
        assert RULE_KEYS <= set(card), key
        assert card["source_scope"] in {"条款与说明书", "含其他材料"}, key
        assert all(len(pair) == 2 for pair in card["excludes"]), key


def test_examples_come_only_from_held_out_products() -> None:
    for key, card in all_cards().items():
        for example in card.get("examples", []):
            assert not example["product"].startswith(EVAL_PRODUCTS), (key, example["product"])
            assert example["state"] in {"present", "absent_explicitly", "unknown"}


def definition(field_key: str, pack_id: str) -> FieldDefinition:
    return FieldDefinition(
        field_key=field_key, short_title="宽限期", description="宽限期", ordinal=0, pack_id=pack_id
    )


def test_payload_sends_only_examples_of_the_same_insurance_type() -> None:
    card = all_cards()["premium_grace_period"]
    packs = {e["schema_pack_id"] for e in card.get("examples", [])}
    assert "schemapack_endowment_insurance" in packs
    same = card_payload(definition("premium_grace_period", "schemapack_endowment_insurance"))
    other = card_payload(definition("premium_grace_period", "schemapack_accident_insurance"))
    assert same is not None and other is not None
    assert {e["schema_pack_id"] for e in same.get("examples", [])} == {
        "schemapack_endowment_insurance"
    }
    # S4e: accident insurance now has its own held-out examples, so only the type is checked.
    assert {e["schema_pack_id"] for e in other.get("examples", [])} <= {
        "schemapack_accident_insurance"
    }
    assert same["absent_rule"] == card["absent_rule"]


def test_a_field_without_a_card_has_no_payload() -> None:
    assert card_payload(definition("no_such_field", "schemapack_endowment_insurance")) is None


def test_the_selection_request_carries_the_card() -> None:
    class Page:
        document, document_sha256, page, text = (
            "保险条款.pdf",
            "c" * 64,
            1,
            "3.2 宽限期 自约定支付日次日零时起60日为宽限期。",
        )

    class Unused:
        model = "offline"

        def complete(self, *, system: str, user: str) -> str:
            raise AssertionError("building requests must not call the model")

    request = SchemaFieldsCompiler(Unused()).build_requests(
        "1818", [definition("premium_grace_period", "schemapack_endowment_insurance")], [Page()]
    )[0]
    assert all_cards()["premium_grace_period"]["absent_rule"] in request.user
