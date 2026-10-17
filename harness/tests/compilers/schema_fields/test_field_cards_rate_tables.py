"""S4i acceptance: field cards no longer ask for rate-table segments (Spec §3.3).

Protected file: written by Claude. Rate tables are not evidence (user ruling 2026-10-17), so they
never reach a request. Rules that told the model to select their titles, headers or rows are gone,
and examples labelled when rate tables counted are removed rather than rewritten by hand. Unknown
rules may still name a rate table as material that does not settle a field.
"""

from __future__ import annotations

import re

from insurance_harness.compilers.schema_fields.cards import all_cards, cards_version

RATES = re.compile("费率|金额表")
# Examples each card keeps once those labelled under "rate tables are evidence" are removed.
KEPT_EXAMPLES = {
    "entry_age_range": {"1818", "1803"},  # 1837 and 1806 removed
    "coverage_period": {"1818", "1837", "1806"},  # 1803 removed
    "premium_payment_frequency": set(),  # all four removed
    "premium_payment_term": {"1837"},  # 1818, 1803 and 1806 removed
    "product_bundle_rules": {"1837", "1803", "1806"},  # 1818 removed
}


def test_the_cards_carry_the_s4i_version() -> None:
    assert cards_version() == "draft-2026-10-17a"


def test_no_card_asks_for_rate_table_segments() -> None:
    for key, card in all_cards().items():
        assert "费率表" not in card.get("includes", ""), key
        assert not any("费率表" in content for content, _ in card["excludes"]), key
    assert "费率表" not in all_cards()["premium_payment_term"]["unknown_rule"]


def test_no_example_with_content_rests_on_a_rate_table() -> None:
    for key, card in all_cards().items():
        for example in card.get("examples", []):
            if example["state"] == "unknown":
                continue
            text = (example.get("value") or "") + "".join(example.get("pitfalls") or [])
            assert not RATES.search(text), (key, example["product_id"])


def test_only_the_rate_table_examples_were_removed() -> None:
    cards = all_cards()
    for key, kept in KEPT_EXAMPLES.items():
        assert {example["product_id"] for example in cards[key].get("examples", [])} == kept, key
