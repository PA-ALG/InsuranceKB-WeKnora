"""S12c-9 acceptance: the contamination hot spots are fixed in card data (Spec §2).

Protected file: written by Claude. A writing rule says what a value leaves out of a passage it
still uses, and it reaches step two only, so step one keeps selecting the field's own passages
(S12c-5 #425 R2: tightening selection rules on long mixed passages dropped evidence). Where the
leaked sentence sits in its own short passage, the selection rules narrow instead. The wording
is generic insurance language, never a product's code, name or answer.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from insurance_harness.compilers.schema_fields.cards import all_cards, card_payload, cards_version
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.prompt import (
    build_selection_request,
    build_value_request,
)
from insurance_harness.evidence.segments import SegmentedSource

PACK = "schemapack_whole_life_insurance"
WRITING = (
    "coverage_responsibilities",
    "coverage_summary",
    "benefit_interaction_rules",
    "cash_value_rules",
)
GOLDEN_MANIFEST = Path(__file__).resolve().parents[4] / "dataset/golden/v2/manifest.json"


def definition(key: str) -> FieldDefinition:
    return FieldDefinition(field_key=key, short_title=key, description=key, ordinal=0, pack_id=PACK)


def test_the_cards_carry_the_s12c9_version() -> None:
    # S12c-10 bumped the version again; the S12c-9 rules stay pinned by the assertions below.
    assert cards_version() == "draft-2026-10-31a"


def test_a_writing_rule_reaches_step_two_only() -> None:
    for key in WRITING:
        step_one = card_payload(definition(key))
        step_two = card_payload(definition(key), examples=False)
        assert step_one is not None and step_two is not None
        assert "writing_rule" not in step_one, key
        assert step_two["writing_rule"] == all_cards()[key]["writing_rule"], key


class Page:
    document, document_sha256, page = "条款.pdf", "a" * 64, 1
    text = "本合同为分红保险合同。"


def test_the_value_request_carries_the_writing_rule_and_step_one_does_not() -> None:
    source = SegmentedSource([Page()])
    segments = source.ordered([source.segments[0].id])
    field = definition("cash_value_rules")
    value = build_value_request("p1", [(field, segments)])
    selection = build_selection_request("p1", [field], source.listing())
    rule = all_cards()["cash_value_rules"]["writing_rule"]
    assert rule in json.loads(value.user)["schema_fields"][0]["card"]["writing_rule"]
    assert "writing_rule" not in selection.user


def test_exclusion_sentences_stay_out_of_coverage_values_not_out_of_selection() -> None:
    cards = all_cards()
    for key in ("coverage_responsibilities", "coverage_summary"):
        rule = cards[key]["writing_rule"]
        assert "不承担" in rule and "同一段落" in rule and "照常写入" in rule, key
    interaction = cards["benefit_interaction_rules"]["writing_rule"]
    assert "责任免除" in interaction and "同一段落" in interaction
    assert "保险责任条文中夹带" in cards["exclusions"]["includes"]


def test_a_participating_product_lists_dividends_as_one_item() -> None:
    rule = all_cards()["coverage_responsibilities"]["writing_rule"]
    assert "有权参与红利分配" in rule and "dividend_rules" in rule


def test_cash_value_keeps_the_relation_without_ratios_or_formulas() -> None:
    rule = all_cards()["cash_value_rules"]["writing_rule"]
    assert "以现金价值为限" in rule
    assert "贷款比例" in rule and "policy_loan_rules" in rule


def test_product_bundle_names_what_only_mentions_a_main_policy() -> None:
    card = all_cards()["product_bundle_rules"]
    assert "随主险保险费一同支付" in card["includes"]
    assert "一同办理减额交清" in card["includes"]  # scope unchanged: Golden and the example keep it
    targets = " ".join(target for _, target in card["excludes"])
    assert "policyholder_rights" in targets and "insured_eligibility" in targets
    mention = [content for content, target in card["excludes"] if target == "不入本字段"]
    assert any("主险终止则本合同终止" in content for content in mention)
    pitfalls = " ".join(p for e in card["examples"] for p in e.get("pitfalls", []))
    assert "保费随主险支付" not in pitfalls  # Golden revision #443: it belongs here


def test_a_procedural_sum_assured_clause_alone_is_unknown() -> None:
    card = all_cards()["sum_assured_range"]
    assert card["unknown_rule"].startswith("原文只有")
    assert "程序性条文" in card["unknown_rule"]


def test_the_accident_definition_draws_the_line_by_why_an_item_is_excluded() -> None:
    card = all_cards()["accident_definition_and_criteria"]
    assert "猝死" in card["includes"] and "故意自伤" in card["includes"]
    assert "犯罪" not in card["includes"]
    crime = [target for content, target in card["excludes"] if "故意犯罪" in content]
    assert crime and "exclusions" in crime[0]


def test_the_new_wording_names_no_product() -> None:
    cards = all_cards()
    texts = [cards[key]["writing_rule"] for key in WRITING]
    texts += [
        json.dumps(cards[key][rule], ensure_ascii=False)
        for key, rule in (
            ("product_bundle_rules", "includes"),
            ("product_bundle_rules", "excludes"),
            ("product_bundle_rules", "bad"),
            ("sum_assured_range", "unknown_rule"),
            ("accident_definition_and_criteria", "includes"),
            ("accident_definition_and_criteria", "excludes"),
            ("exclusions", "includes"),
        )
    ]
    codes = {e["product_id"] for card in cards.values() for e in card.get("examples", [])}
    codes |= set(json.loads(GOLDEN_MANIFEST.read_text(encoding="utf-8"))["products"])
    alternatives = "|".join(map(re.escape, sorted(codes)))
    pattern = re.compile(rf"(?<![0-9A-Za-z])({alternatives})(?![0-9A-Za-z])")
    for text in texts:
        assert not pattern.search(text), text[:80]
        assert "平安" not in text and not re.search(r"sc-[0-9a-f]{10}", text), text[:80]
