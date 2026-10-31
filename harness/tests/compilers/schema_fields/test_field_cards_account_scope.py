"""S12c-10 acceptance: the universal-account fields write universal accounts only (Spec §3).

Protected file: written by Claude. A supplementary-pension product's investment-portfolio account
is not a universal account; the two cards say so in a step-two writing rule, and when the given
passages only describe such an account the value is unknown. The wording is generic insurance
language, never a product's code, name or answer.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

from insurance_harness.compilers.schema_fields.cards import all_cards, card_payload, cards_version
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.prompt import (
    build_selection_request,
    build_value_request,
)
from insurance_harness.evidence.segments import SegmentedSource

PACK = "schemapack_supplementary_pension_insurance"
ACCOUNT = (
    "universal_account_guaranteed_interest_rate",
    "universal_account_settlement_rules",
)
GOLDEN_MANIFEST = Path(__file__).resolve().parents[4] / "dataset/golden/v2/manifest.json"
_PATH = Path(__file__).with_name("test_field_cards_rate_tables.py")
_SPEC = importlib.util.spec_from_file_location("s4i_rate_tables", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
S4I: Any = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(S4I)


def definition(key: str) -> FieldDefinition:
    return FieldDefinition(field_key=key, short_title=key, description=key, ordinal=0, pack_id=PACK)


def test_the_cards_carry_the_s12c10_version() -> None:
    assert cards_version() == "draft-2026-10-31a"


def test_the_account_writing_rule_reaches_step_two_only() -> None:
    for key in ACCOUNT:
        step_one = card_payload(definition(key))
        step_two = card_payload(definition(key), examples=False)
        assert step_one is not None and step_two is not None
        assert "writing_rule" not in step_one, key
        assert step_two["writing_rule"] == all_cards()[key]["writing_rule"], key


class Page:
    document, document_sha256, page = "条款.pdf", "a" * 64, 1
    text = "投资组合账户的保证利率为年利率1.5%。"


def test_the_value_request_carries_the_rule_and_the_selection_request_does_not() -> None:
    source = SegmentedSource([Page()])
    segments = source.ordered([source.segments[0].id])
    for key in ACCOUNT:
        field = definition(key)
        value = build_value_request("p1", [(field, segments)])
        selection = build_selection_request("p1", [field], source.listing())
        rule = all_cards()[key]["writing_rule"]
        assert json.loads(value.user)["schema_fields"][0]["card"]["writing_rule"] == rule, key
        assert "writing_rule" not in selection.user, key


def test_a_pension_portfolio_account_is_not_a_universal_account() -> None:
    for key in ACCOUNT:
        rule = all_cards()[key]["writing_rule"]
        assert "只写万能账户" in rule, key
        assert "专属商业养老保险" in rule and "投资组合账户" in rule, key
        assert "投资连结账户" in rule, key
        assert "unknown" in rule and "absent_explicitly" not in rule, key


def test_only_the_two_account_cards_gain_a_writing_rule() -> None:
    with_rule = {key for key, card in all_cards().items() if "writing_rule" in card}
    assert with_rule == {*S4I.S12C9_WRITING_RULES, *ACCOUNT}


def test_a_writing_rule_on_another_account_card_still_changes_the_digest() -> None:
    cards = copy.deepcopy(all_cards())
    cards["initial_charge_rules"]["writing_rule"] = "本字段只写万能账户。"
    assert S4I.untouched(cards) != S4I.UNTOUCHED_DIGEST


def test_the_new_wording_names_no_product() -> None:
    cards = all_cards()
    codes = {e["product_id"] for card in cards.values() for e in card.get("examples", [])}
    codes |= set(json.loads(GOLDEN_MANIFEST.read_text(encoding="utf-8"))["products"])
    alternatives = "|".join(map(re.escape, sorted(codes)))
    pattern = re.compile(rf"(?<![0-9A-Za-z])({alternatives})(?![0-9A-Za-z])")
    for key in ACCOUNT:
        text = cards[key]["writing_rule"]
        assert not pattern.search(text), key
        assert "平安" not in text and not re.search(r"sc-[0-9a-f]{10}", text), key
