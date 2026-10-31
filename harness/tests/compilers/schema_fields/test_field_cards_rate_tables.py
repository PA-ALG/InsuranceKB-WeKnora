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
# S12c-9 rewrote these selection rules, added a step-two-only writing rule to four cards and
# corrected one product-bundle example's pitfalls (it contradicted the Golden ruling in #443);
# test_field_cards_writing_rules.py checks them. Exactly these parts are neutralised here, so a
# writing rule on any other card, or any other example change, still changes the digest
# (test_field_cards_mask_controls.py proves it).
S12C9_RULES = {
    "product_bundle_rules": ("includes", "excludes", "bad"),
    "sum_assured_range": ("includes", "unknown_rule"),
    "accident_definition_and_criteria": ("includes", "excludes", "bad"),
    "exclusions": ("includes",),
}
S12C9_WRITING_RULES = (
    "coverage_responsibilities",
    "coverage_summary",
    "benefit_interaction_rules",
    "cash_value_rules",
)
S12C9_EXAMPLE_PITFALLS = {"product_bundle_rules": ("1806",)}
# S12c-10 added a step-two-only writing rule to the two universal-account cards
# (test_field_cards_account_scope.py checks them); only these two are neutralised.
S12C10_WRITING_RULES = (
    "universal_account_guaranteed_interest_rate",
    "universal_account_settlement_rules",
)
# S12c-11 (#473 Owner ruling): a non-payment condition that applies only to one benefit belongs to
# that benefit's rule field as well as to exclusions; who issues a disability assessment belongs
# to the disability criteria. Exactly the added or reworded text is reverted here
# (test_field_cards_benefit_conditions.py checks it), so any other edit to these cards still
# changes the digest.
S12C11_BENEFIT_CLAUSE = (
    "；条文中只针对本项责任的不给付条件与限制（如“……的，我们不承担本项保险金责任”）"
    "也属于本字段，同时选入责任免除（exclusions）"
)
S12C11_BENEFIT_CARDS = (
    "accidental_death_benefit_rules",
    "additional_benefit_rules",
    "disability_benefit_rules",
    "death_benefit_rules",
    "maturity_benefit_rules",
    "survival_benefit_rules",
    "premium_waiver_rules",
    "income_loss_benefit_eligibility_conditions",
    "income_loss_care_benefit_conditions",
)
S12C11_SUFFIXES = {
    "disability_definition_and_assessment_criteria": (
        "、伤残鉴定由谁出具（如二级以上医院或鉴定机构出具伤残程度资料或鉴定书），"
        "理赔申请材料条文中写明的出具机构要求也属于本字段"
    ),
    "claim_application_deadline_and_documents": (
        "；伤残鉴定书等材料写明的出具机构要求同时选入伤残定义与认定标准"
        "（disability_definition_and_assessment_criteria）"
    ),
}
S12C11_ADDED_EXCLUDE = (
    "disability_definition_and_assessment_criteria",
    [
        "理赔时须提交的申请材料清单",
        "理赔申请时效与申请材料（claim_application_deadline_and_documents）",
    ],
)
S12C11_REWORDED_EXCLUDES = {
    "death_benefit_rules": (
        "责任免除条款列出的导致身故不赔的情形及退还现金价值",
        "导致身故不赔的情形及退还现金价值",
    ),
    "income_loss_benefit_eligibility_conditions": (
        "责任免除条款列出的不予给付情形",
        "不予给付的免责情形",
    ),
}
S12C11_PITFALL = (
    "income_loss_benefit_eligibility_conditions",
    "1806",
    "抽取错误：混入完整等待期处理和给付金额频率，应只保留给付条件。",
    "抽取错误：混入完整等待期处理、给付金额频率和既往疾病免责，应只保留给付条件。",
)
# draft-2026-10-16b with the parts above neutralised; any other edit changes this digest.
# S12c-5: the S12C5_RULES are neutralised too, which gives the same digest for the cards before
# and after S12c-5 (was 5da2b4857e0bc38be6c503cc4a4633cd61df1af127c91644fcbc45b68b76a1ab).
# S12c-9: the S12C9_RULES, the four writing rules and the 1806 pitfalls are neutralised too; the
# cards before and after S12c-9 give the same digest
# (was f8cff3cd899f75410837024e27701a07f13ddbf0b00082a3cf0702da29c668f3).
# S12c-10: the two universal-account writing rules are neutralised too; the digest is unchanged.
# S12c-11: the added and reworded benefit-condition and assessment text is reverted first; the
# digest is unchanged.
UNTOUCHED_DIGEST = "94ca4701b06a2c792b5171cb4ddbf87e66907d1bad8076b7d5abf91acef04dda"


def _revert_s12c11(data: dict[str, Any]) -> None:
    for key in S12C11_BENEFIT_CARDS:
        data[key]["includes"] = data[key]["includes"].removesuffix(S12C11_BENEFIT_CLAUSE)
    for key, suffix in S12C11_SUFFIXES.items():
        data[key]["includes"] = data[key]["includes"].removesuffix(suffix)
    key, pair = S12C11_ADDED_EXCLUDE
    data[key]["excludes"] = [p for p in data[key]["excludes"] if list(p) != pair]
    for key, (new, old) in S12C11_REWORDED_EXCLUDES.items():
        data[key]["excludes"] = [
            [old if content == new else content, target]
            for content, target in data[key]["excludes"]
        ]
    key, product, new, old = S12C11_PITFALL
    for example in data[key].get("examples", []):
        if example["product_id"] == product:
            example["pitfalls"] = [old if p == new else p for p in example.get("pitfalls", [])]


def untouched(cards: dict[str, Any]) -> str:
    data = copy.deepcopy(cards)
    _revert_s12c11(data)
    for key in INCLUDES:
        data[key]["includes"] = ""
    data["premium_payment_term"]["unknown_rule"] = ""
    for key in RATE_EXCLUDES:
        data[key]["excludes"] = [pair for pair in data[key]["excludes"] if "费率表" not in pair[0]]
    for key, removed in REMOVED_EXAMPLES.items():
        data[key]["examples"] = [
            e for e in data[key].get("examples", []) if e["product_id"] not in removed
        ]
    for key, rules in (*S12C5_RULES.items(), *S12C9_RULES.items()):
        for rule in rules:
            data[key][rule] = [] if rule in ("excludes", "examples") else ""
    for key in (*S12C9_WRITING_RULES, *S12C10_WRITING_RULES):
        data[key].pop("writing_rule", None)
    for key, products in S12C9_EXAMPLE_PITFALLS.items():
        for example in data[key].get("examples", []):
            if example["product_id"] in products:
                example["pitfalls"] = []
    text = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_the_cards_carry_the_s4i_version() -> None:
    # S4j: the payment term may cite rate-table headers; S12c-5: nine field boundaries;
    # S12c-9: contamination hot spots (writing rules and four selection boundaries);
    # S12c-10: universal-account writing rules; S12c-11: benefit conditions and assessment issuer
    assert cards_version() == "draft-2026-10-31b"


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
