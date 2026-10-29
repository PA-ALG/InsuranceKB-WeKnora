"""S12c-5 acceptance: nine field cards state their boundaries on content (Spec §2).

Protected file: written by Claude. The boundary says what a value must not carry, while the
segments that hold the field's own facts stay selectable; the wording is generic insurance
language, never a product's code, name or answer.
"""

from __future__ import annotations

import hashlib
import json
import re

from insurance_harness.compilers.schema_fields.cards import all_cards, cards_version

# The rules S12c-5 rewrote, per card; test_field_cards_rate_tables.py leaves exactly these out.
S12C5_RULES = {
    "target_customer_profile": ("includes", "excludes", "bad"),
    "premium_payment_frequency": ("excludes", "bad"),
    "income_loss_benefit_payment_rules": ("excludes", "bad"),
    "disability_recovery_and_benefit_termination_rules": ("excludes", "bad"),
    "disability_status_verification_and_reassessment_rules": ("includes", "excludes", "bad"),
    "coverage_responsibilities": ("includes", "excludes", "bad"),
    "coverage_summary": ("includes", "excludes", "bad"),
    "sum_assured_growth_rate": ("includes", "bad"),
    "non_guaranteed_benefit_rules": ("includes", "excludes", "bad"),
}
# #425 R1: the customer-profile examples were rewritten to the ruling; they are pinned too.
EXAMPLES_REWRITTEN = ("target_customer_profile",)
RULES_DIGEST = "62efd70e07e65836338840777ff4c135eca2ecc5f6e0e58b6a570651b40434b2"
TARGET_KEY = re.compile(r"[a-z][a-z0-9_]+")


def _rules(card: dict[str, object], rules: tuple[str, ...]) -> str:
    return json.dumps({rule: card[rule] for rule in rules}, ensure_ascii=False)


def test_the_cards_carry_the_s12c5_version() -> None:
    assert cards_version() == "draft-2026-10-28a"


def test_the_rewritten_rules_read_exactly_as_specified() -> None:
    cards = all_cards()
    data = {key: {rule: cards[key][rule] for rule in rules} for key, rules in S12C5_RULES.items()}
    for key in EXAMPLES_REWRITTEN:
        data[key]["examples"] = cards[key]["examples"]
    text = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == RULES_DIGEST


def test_every_exclude_goes_nowhere_or_to_an_existing_card() -> None:
    cards = all_cards()
    for key in S12C5_RULES:
        for _content, target in cards[key]["excludes"]:
            if target == "不入本字段":
                continue
            named = TARGET_KEY.findall(target)
            assert named and all(name in cards for name in named), (key, target)


def test_the_wording_names_no_product() -> None:
    cards = all_cards()
    for key, rules in S12C5_RULES.items():
        text = _rules(cards[key], rules)
        assert not re.search(r"\d{4}", text.replace("2026", "")), key
        assert "平安" not in text, key


def test_the_segments_of_the_fields_own_facts_stay_selectable() -> None:
    cards = all_cards()

    def excludes(key: str) -> str:
        return "".join(content for content, _ in cards[key]["excludes"])

    for key in ("coverage_responsibilities", "coverage_summary"):
        assert "同一段落中的给付内容照常选入" in excludes(key), key
    assert "交费频率仍属本字段" in excludes("premium_payment_frequency")
    assert "第一步选入所有说明产品为谁而设的段落" in cards["target_customer_profile"]["includes"]
    assert "适用的增长比例都要写明" in cards["sum_assured_growth_rate"]["includes"]
