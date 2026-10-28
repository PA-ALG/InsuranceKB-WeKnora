"""S12c-2a: the held 1816 critical-illness list field is ruled present.

Spec: docs/design/slices/S12c-2a-1816重疾清单裁定.md.

The card's own 1806 examples (same product family, a 120-disease list applying only to the
premium waiver) record the list as present in both the critical-illness list field and the
waiver list field; the waiver clause cites the contract's own list, so the exclusion of lists
"defined separately by the waiver clause" does not apply.
"""

import json
from pathlib import Path
from typing import Any

from insurance_harness.eval.segment_score import load_golden_v2

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "dataset" / "golden" / "v2"
CARDS = REPO / "harness/src/insurance_harness/compilers/schema_fields/field_cards.json"
FIELD = "covered_critical_specified_diseases"
WAIVER = "premium_waiver_critical_illnesses"


def manifest() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
    return data


def fields_1816() -> dict[str, Any]:
    return {f.field_key: f for f in load_golden_v2(GOLDEN / "1816.json").fields}


def test_the_1816_list_field_is_present_and_matches_the_waiver_list() -> None:
    fields = fields_1816()
    field, waiver = fields[FIELD], fields[WAIVER]
    assert field.state == "present"
    assert field.value == waiver.value
    evidence = {quote.segment_id for quote in field.evidence}
    assert {"D2P4S39", "D2P3S10"} <= evidence  # list lead-in; waiver clause citing the list
    assert "D2P22S22" not in evidence  # common diagnosis criterion: disease definitions


def test_one_owner_ruling_records_the_decision_and_releases_the_hold() -> None:
    rulings = [r for r in manifest()["revisions"] if r.get("method") == "owner-ruling"]
    assert len(rulings) == 1
    ruling = rulings[0]
    assert ruling["basis"] and ruling["cards_version"]
    entry = ruling["products"]["1816"]
    assert entry["fields"] == [FIELD]
    decision = entry["decisions"][FIELD]
    assert decision["state"] == "present"
    assert decision["evidence_changed"] is False
    assert decision["releases_hold_of"] == "judge-golden-audit"
    assert "1806" in decision["basis"]


def test_the_card_examples_the_ruling_rests_on_still_hold() -> None:
    raw = json.loads(CARDS.read_text(encoding="utf-8"))
    cards = raw.get("cards", raw)

    def example(field: str) -> dict[str, Any]:
        found = [e for e in cards[field]["examples"] if e.get("product_id") == "1806"]
        assert len(found) == 1, field
        return dict(found[0])

    listed, waived = example(FIELD), example(WAIVER)
    assert listed["state"] == waived["state"] == "present"
    assert listed["value"] == waived["value"]
