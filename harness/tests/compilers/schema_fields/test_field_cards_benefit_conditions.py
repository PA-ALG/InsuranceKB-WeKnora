"""S12c-11 acceptance: two field boundaries the cards left open are settled (Spec §2, #473 ruling).

Protected file: written by Claude. A non-payment condition written into one benefit's clause and
applying only to that benefit belongs to the benefit's rule field and also to exclusions; who
issues a disability assessment belongs to the disability criteria, while the document itself stays
a claim document. The wording is generic insurance language, never a product's code, name or
answer.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

from insurance_harness.compilers.schema_fields.cards import all_cards, cards_version
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.prompt import (
    build_selection_request,
    build_value_request,
)
from insurance_harness.evidence.segments import SegmentedSource

BENEFIT = (
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
CONDITION = "只针对本项责任的不给付条件"
DISABILITY = "disability_definition_and_assessment_criteria"
CLAIM = "claim_application_deadline_and_documents"
GOLDEN_MANIFEST = Path(__file__).resolve().parents[4] / "dataset/golden/v2/manifest.json"
_PATH = Path(__file__).with_name("test_field_cards_rate_tables.py")
_SPEC = importlib.util.spec_from_file_location("s4i_rate_tables", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
S4I: Any = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(S4I)


def definition(key: str) -> FieldDefinition:
    return FieldDefinition(
        field_key=key, short_title=key, description=key, ordinal=0, pack_id="schemapack_x"
    )


def test_the_cards_carry_the_s12c11_version() -> None:
    assert cards_version() == "draft-2026-10-31b"


def test_each_benefit_card_keeps_its_own_non_payment_conditions() -> None:
    cards = all_cards()
    for key in BENEFIT:
        includes = cards[key]["includes"]
        assert CONDITION in includes and "不承担本项保险金责任" in includes, key
        assert "同时选入责任免除" in includes, key


def test_only_the_benefit_cards_carry_the_condition() -> None:
    carrying = {key for key, card in all_cards().items() if CONDITION in card["includes"]}
    assert carrying == set(BENEFIT)


def test_no_benefit_card_sends_its_own_conditions_away() -> None:
    cards = all_cards()
    for key in BENEFIT:
        for content, target in cards[key]["excludes"]:
            if "exclusions" in target:
                assert content.startswith("责任免除条款"), (key, content)
        pitfalls = " ".join(
            p for e in cards[key].get("examples", []) for p in e.get("pitfalls", [])
        )
        assert "免责" not in pitfalls, key


def test_exclusions_keep_the_sentences_too() -> None:
    includes = all_cards()["exclusions"]["includes"]
    assert "保险责任条文中夹带" in includes
    assert "同时属于该项责任的给付规则字段" in includes


def test_who_issues_a_disability_assessment_is_a_disability_criterion() -> None:
    cards = all_cards()
    assert "伤残鉴定由谁出具" in cards[DISABILITY]["includes"]
    targets = {content: target for content, target in cards[DISABILITY]["excludes"]}
    assert CLAIM in targets["理赔时须提交的申请材料清单"]
    claim = cards[CLAIM]["includes"]
    assert "出具机构要求同时选入" in claim and DISABILITY in claim
    assert "申请材料" in claim  # the document itself stays a claim document


class Page:
    document, document_sha256, page = "条款.pdf", "a" * 64, 1
    text = "车辆用于营运的，我们不承担本项保险金责任。"


def test_both_steps_see_the_condition() -> None:
    source = SegmentedSource([Page()])
    segments = source.ordered([source.segments[0].id])
    field = definition("accidental_death_benefit_rules")
    selection = build_selection_request("p1", [field], source.listing())
    value = build_value_request("p1", [(field, segments)])
    assert CONDITION in selection.user
    assert CONDITION in json.loads(value.user)["schema_fields"][0]["card"]["includes"]


def test_another_edit_to_a_benefit_card_still_changes_the_digest() -> None:
    cards = copy.deepcopy(all_cards())
    cards["death_benefit_rules"]["includes"] += "、（改）"
    assert S4I.untouched(cards) != S4I.UNTOUCHED_DIGEST


def test_the_new_wording_names_no_product() -> None:
    cards = all_cards()
    texts = [cards[key]["includes"] for key in (*BENEFIT, DISABILITY, CLAIM, "exclusions")]
    texts += [content for key in (*BENEFIT, DISABILITY) for content, _ in cards[key]["excludes"]]
    codes = {e["product_id"] for card in cards.values() for e in card.get("examples", [])}
    codes |= set(json.loads(GOLDEN_MANIFEST.read_text(encoding="utf-8"))["products"])
    alternatives = "|".join(map(re.escape, sorted(codes)))
    pattern = re.compile(rf"(?<![0-9A-Za-z])({alternatives})(?![0-9A-Za-z])")
    for text in texts:
        assert not pattern.search(text), text[:80]
        assert "平安" not in text and not re.search(r"sc-[0-9a-f]{10}", text), text[:80]
