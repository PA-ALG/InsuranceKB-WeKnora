"""#563 annuity hold: only the exact approved annuity-card units are neutralised.

The nine payout cards are new; policyholder_rights drops one includes clause and gains a
writing rule. The actual values are captured first. Only the exact approved after snapshot is
turned back into the before cards, so the S4i digest is unchanged; a partial change, an
unapproved value or any other card still changes it.
"""

from typing import Any

from tests.compilers.schema_fields.rule_alignment_scope import digest

NEW_CARDS = (
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
WRITING_RULES = frozenset(
    {
        "policyholder_rights",
        "annuity_start_time",
        "annuity_payment_period",
        "annuity_payment_amount_rules",
    }
)
ANCHOR = "包括附加险合同）。"
REMOVED = "同一条款可同时被对应的具体规则字段引用；"
BEFORE = "b709dfffcea3209f960c55cd5380c5772bf7a52732d76c6047d6fca8ae6c4e2a"
AFTER = "a64cf23f60dd8cadc88a2d7609d625485ee6f6af1582c9a066f4198c76946c31"


def normalize_annuity_cards(data: dict[str, Any]) -> None:
    selected: dict[str, Any] = {key: data.pop(key, None) for key in NEW_CARDS}
    card = data["policyholder_rights"]
    selected["policyholder_rights/includes"] = card.get("includes")
    selected["policyholder_rights/writing_rule"] = card.pop("writing_rule", None)
    fingerprint = digest(selected)
    if fingerprint == AFTER:
        card["includes"] = card["includes"].replace(ANCHOR, ANCHOR + REMOVED, 1)
    elif fingerprint != BEFORE:
        data["annuity-563 units"] = fingerprint
