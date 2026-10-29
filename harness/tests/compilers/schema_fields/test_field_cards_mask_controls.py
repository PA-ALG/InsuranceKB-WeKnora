"""S12c-9 (#457 R1): the S4i "nothing else changed" digest neutralises only what S12c-9 changed.

A writing rule on any card other than the four S12c-9 cards, a change to an untouched example, or
an unrelated definition change must still change the digest; a change inside the authorised parts
must not.
"""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from typing import Any

from insurance_harness.compilers.schema_fields.cards import all_cards

_PATH = Path(__file__).with_name("test_field_cards_rate_tables.py")
_SPEC = importlib.util.spec_from_file_location("s4i_rate_tables", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
S4I: Any = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(S4I)


def digest_after(change: Any) -> str:
    cards = copy.deepcopy(all_cards())
    change(cards)
    return str(S4I.untouched(cards))


def test_the_shipped_cards_match_the_digest() -> None:
    assert digest_after(lambda cards: None) == S4I.UNTOUCHED_DIGEST


def test_a_writing_rule_on_another_card_is_caught() -> None:
    def add(cards: dict[str, Any]) -> None:
        cards["waiting_period"]["writing_rule"] = "不写入等待期长度。"

    assert digest_after(add) != S4I.UNTOUCHED_DIGEST


def test_an_untouched_bundle_example_is_still_protected() -> None:
    def edit(cards: dict[str, Any]) -> None:
        for example in cards["product_bundle_rules"]["examples"]:
            if example["product_id"] == "1837":
                example["value"] = "附加险须随主险投保。"

    assert digest_after(edit) != S4I.UNTOUCHED_DIGEST


def test_an_unrelated_definition_is_still_protected() -> None:
    def edit(cards: dict[str, Any]) -> None:
        cards["waiting_period"]["definition"] += "（改）"

    assert digest_after(edit) != S4I.UNTOUCHED_DIGEST


def test_changes_inside_the_authorised_parts_are_neutralised() -> None:
    def edit(cards: dict[str, Any]) -> None:
        cards["cash_value_rules"]["writing_rule"] += "（措辞）"
        cards["sum_assured_range"]["unknown_rule"] += "（措辞）"
        for example in cards["product_bundle_rules"]["examples"]:
            if example["product_id"] == "1806":
                example["pitfalls"] = ["改写"]

    assert digest_after(edit) == S4I.UNTOUCHED_DIGEST
