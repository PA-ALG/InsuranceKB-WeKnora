"""S4i acceptance: field cards no longer ask for rate-table segments (Spec §3.3).

Protected file: written by Claude, revised after review R6 on #200. Rate tables are not evidence
(user ruling 2026-10-17), so they never reach a request. The rules that told the model to select
their titles, headers or rows are gone, the examples labelled when rate tables counted are removed
rather than rewritten by hand, and nothing else in the cards changed. Historical unknown reasons
that list the materials a field was missing from are labels, not rules, and stay as they were.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from insurance_harness.compilers.schema_fields.cards import all_cards, cards_version

# The four includes, back to their wording before rate tables became evidence (draft-2026-10-15g).
INCLUDES = {
    "entry_age_range": "被保险人首次投保的起止年龄、出生满N日等下限、年龄计算口径（周岁如何计算）、"
    "不同计划/交费期/渠道的年龄差异",
    "premium_payment_term": "全部可选缴费年期（趸交、N年交、交至N岁），按保险期间或计划对应的组合",
    "premium_payment_frequency": "全部可选缴费频率（趸交、年交、半年交、季交、月交），"
    "以及附加险随主险缴纳等缴费方式规定，"
    "以及“交费方式由您与我们约定并在保险单上载明”这类约定方式条款（与具体频率一并列出）",
    "coverage_period": "保险期间的长度或截止方式及全部可选项（如10年、至70周岁、终身），"
    "按计划或投保年龄分组的差异",
}
TERM_UNKNOWN_RULE = (
    "说明书、条款与费率表表头都没有列出缴费年期时为 unknown（原因：材料未提及）。"
    "本字段的信息还可能在产品投保规则PDF中；"
    "本批材料未提及时为 unknown，不得因条款未写而判 absent_explicitly。"
)
RATE_EXCLUDES = {"sum_assured_range", "product_bundle_rules"}
# Examples each card keeps once those labelled under "rate tables are evidence" are removed.
REMOVED_EXAMPLES = {
    "entry_age_range": {"1837", "1806"},
    "coverage_period": {"1803"},
    "premium_payment_frequency": {"1818", "1837", "1803", "1806"},
    "premium_payment_term": {"1818", "1803", "1806"},
    "product_bundle_rules": {"1818"},
}
KEPT_EXAMPLES = {
    "entry_age_range": {"1818", "1803"},
    "coverage_period": {"1818", "1837", "1806"},
    "premium_payment_frequency": set(),
    "premium_payment_term": {"1837"},
    "product_bundle_rules": {"1837", "1803", "1806"},
}
# S12c-5 rewrote these rules of seven cards (and, per the #425 R1 ruling, the examples of the
# customer-profile card); test_field_cards_boundaries.py pins them. The two coverage cards' edits
# were withdrawn (Owner decision on #425 R2), so they are checked here like every other card.
S12C5_RULES = {
    "target_customer_profile": ("includes", "excludes", "bad", "examples"),
    "premium_payment_frequency": ("excludes", "bad"),
    "income_loss_benefit_payment_rules": ("excludes", "bad"),
    "disability_recovery_and_benefit_termination_rules": ("excludes", "bad"),
    "disability_status_verification_and_reassessment_rules": ("includes", "excludes", "bad"),
    "sum_assured_growth_rate": ("includes", "bad"),
    "non_guaranteed_benefit_rules": ("includes", "excludes", "bad"),
}
# draft-2026-10-16b with the parts above neutralised; any other edit changes this digest.
# S12c-5: the S12C5_RULES are neutralised too, which gives the same digest for the cards before
# and after S12c-5 (was 5da2b4857e0bc38be6c503cc4a4633cd61df1af127c91644fcbc45b68b76a1ab).
UNTOUCHED_DIGEST = "f8cff3cd899f75410837024e27701a07f13ddbf0b00082a3cf0702da29c668f3"


def untouched(cards: dict[str, Any]) -> str:
    data = copy.deepcopy(cards)
    for key in INCLUDES:
        data[key]["includes"] = ""
    data["premium_payment_term"]["unknown_rule"] = ""
    for key in RATE_EXCLUDES:
        data[key]["excludes"] = [pair for pair in data[key]["excludes"] if "费率表" not in pair[0]]
    for key, removed in REMOVED_EXAMPLES.items():
        data[key]["examples"] = [
            e for e in data[key].get("examples", []) if e["product_id"] not in removed
        ]
    for key, rules in S12C5_RULES.items():
        for rule in rules:
            data[key][rule] = [] if rule in ("excludes", "examples") else ""
    text = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_the_cards_carry_the_s4i_version() -> None:
    assert (
        cards_version() == "draft-2026-10-28a"
    )  # S4j: the payment term may cite rate-table headers; S12c-5: nine field boundaries


def test_the_changed_rules_read_exactly_as_specified() -> None:
    cards = all_cards()
    for key, text in INCLUDES.items():
        assert cards[key]["includes"] == text, key
    assert cards["premium_payment_term"]["unknown_rule"] == TERM_UNKNOWN_RULE
    for key, card in cards.items():
        assert not any("费率表" in content for content, _ in card["excludes"]), key
        assert "费率表" not in card.get("includes", ""), key


def test_only_the_rate_table_examples_were_removed() -> None:
    cards = all_cards()
    for key, kept in KEPT_EXAMPLES.items():
        assert {example["product_id"] for example in cards[key].get("examples", [])} == kept, key


def test_nothing_else_in_the_cards_changed() -> None:
    assert untouched(all_cards()) == UNTOUCHED_DIGEST
