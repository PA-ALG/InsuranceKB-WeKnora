"""Annuity payout fields get cards; a right with its own field is only named (#563 annuity hold).

The annuity recovery sample (59 points) held the pack on four placement errors: payout start,
period and amount values carried each other's facts, and policyholder rights repeated the details
of rights that have dedicated fields. Every payout field had no card. The rules below are generic
insurance language; none names a product or an answer.
"""

from __future__ import annotations

import copy
from pathlib import Path

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.catalog.additions import effective_catalog
from insurance_harness.compilers.schema_fields.cards import all_cards, card_payload
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition

PACK = "schemapack_annuity_insurance"
PAYOUT = (
    "annuity_start_time",
    "annuity_start_age",
    "annuity_payment_frequency",
    "annuity_payment_period",
    "annuity_payment_amount_rules",
    "guaranteed_payment_rules",
    "guaranteed_payment_period",
    "unpaid_guaranteed_benefit_rules",
    "annuity_transfer_to_universal_account_rules",
)
REPO = Path(__file__).resolve().parents[4]


def annuity_fields() -> set[str]:
    entries = effective_catalog(REPO / SCHEMA_PACK_CATALOG)["entries"]
    (pack,) = [e["pack"] for e in entries if e["pack"]["schema_pack_id"] == PACK]
    return {f["field_key"] for f in pack["fields"]}


def definition(key: str) -> FieldDefinition:
    return FieldDefinition(field_key=key, short_title=key, description=key, ordinal=0, pack_id=PACK)


def targets(key: str) -> str:
    return " ".join(target for _, target in all_cards()[key]["excludes"])


def test_every_annuity_payout_field_has_a_card_pointing_at_real_siblings() -> None:
    fields = annuity_fields()
    cards = all_cards()
    for key in PAYOUT:
        assert key in fields, key
        card = cards[key]
        for rule in ("title", "definition", "includes", "excludes", "absent_rule", "unknown_rule"):
            assert card.get(rule), (key, rule)
        for _, target in card["excludes"]:
            named = [part.split("（")[-1].rstrip("）") for part in target.split("/")]
            assert target == "不入本字段" or any(n in fields for n in named), (key, target)


def test_start_period_and_amount_keep_to_their_own_facts() -> None:
    assert "annuity_payment_amount_rules" in targets("annuity_start_time")
    assert "annuity_payment_period" in targets("annuity_start_time")
    assert "annuity_payment_period" in targets("annuity_payment_amount_rules")
    period = all_cards()["annuity_payment_period"]
    assert "coverage_period" in targets("annuity_payment_period")
    assert "annuity_payment_frequency" in targets("annuity_payment_period")
    assert "自首次领取日起" in period["writing_rule"]


def test_no_guarantee_without_a_clause_is_unknown_not_absent() -> None:
    for key in (
        "guaranteed_payment_rules",
        "guaranteed_payment_period",
        "unpaid_guaranteed_benefit_rules",
    ):
        assert "unknown" in all_cards()[key]["unknown_rule"], key


def test_rights_with_a_dedicated_field_are_only_named_in_the_value() -> None:
    card = all_cards()["policyholder_rights"]
    assert "同一条款可同时被对应的具体规则字段引用" not in card["includes"]
    rule = card["writing_rule"]
    for key in (
        "cash_value_rules",
        "policy_loan_rules",
        "surrender_and_cancellation_terms",
        "dividend_rules",
        "sum_assured_reduction_rules",
    ):
        assert key in rule, key
    assert "只写权益名称" in rule and "null" in rule
    # Selection keeps finding the passages; only the value step narrows (S12c-9 pattern).
    assert "writing_rule" not in (card_payload(definition("policyholder_rights")) or {})
    assert (card_payload(definition("policyholder_rights"), examples=False) or {})[
        "writing_rule"
    ] == rule


def test_an_unapproved_annuity_card_edit_still_changes_the_s4i_digest() -> None:
    from tests.compilers.schema_fields.test_field_cards_rate_tables import (
        UNTOUCHED_DIGEST,
        untouched,
    )

    cards = copy.deepcopy(all_cards())
    assert untouched(cards) == UNTOUCHED_DIGEST
    cards["annuity_payment_period"]["includes"] += "（改写）"
    assert untouched(cards) != UNTOUCHED_DIGEST
    cards = copy.deepcopy(all_cards())
    cards["policyholder_rights"]["writing_rule"] += "（改写）"
    assert untouched(cards) != UNTOUCHED_DIGEST
    cards = copy.deepcopy(all_cards())
    cards["annuity_extra_field"] = {"title": "多出的卡"}
    assert untouched(cards) != UNTOUCHED_DIGEST
