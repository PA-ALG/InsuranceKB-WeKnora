"""S12c-2: an independent judge audited Golden v2 evidence: drops and adds (Spec §3, §4)."""

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.eval.segment_score import load_golden_v2

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "dataset/golden/v2"
MANIFEST = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
METHOD = "judge-golden-audit"
PRODUCTS = {"1814", "1816", "1824", "1826", "1828"}
SESSION = re.compile(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}")


def earlier_pairs(
    manifest: dict[str, Any], method: str, key: str, product: str
) -> set[tuple[str, str]]:
    return {
        tuple(pair)
        for r in manifest["revisions"]
        if r.get("method") == method
        for pair in r["products"].get(product, {}).get(key, [])
    }


def check_audit(manifest: dict[str, Any]) -> None:
    revisions = [r for r in manifest["revisions"] if r.get("method") == METHOD]
    assert len(revisions) == 1
    revision = revisions[0]
    assert revision["basis"] and revision["cards_version"]
    assert set(revision["products"]) == PRODUCTS <= set(manifest["products"])
    for product, entry in revision["products"].items():
        assert entry["judging_method"] == "codex-exec-file-exchange"
        assert entry["model_id"] == "gpt-6-astra" and entry["reasoning_effort"] == "xhigh"
        assert entry["session_ids"] and all(SESSION.fullmatch(s) for s in entry["session_ids"])
        golden = {f.field_key: f for f in load_golden_v2(GOLDEN / f"{product}.json").fields}
        dropped = {tuple(pair) for pair in entry["dropped"]}
        added = {tuple(pair) for pair in entry["added"]}
        assert len(dropped) == len(entry["dropped"]) and len(added) == len(entry["added"])
        assert entry["segments_reviewed"] >= len(dropped)
        assert entry["candidates_considered"] >= len(added)
        assert set(entry["fields"]) == {key for key, _ in dropped | added}
        assert not set(entry["fields"]) & set(entry["held_for_adjudication"])
        assert not dropped & earlier_pairs(
            manifest, "deterministic-remap", "quotes_widened", product
        )
        assert not added & earlier_pairs(manifest, "judge-split-review", "dropped", product)
        for key, segment_id in dropped:
            assert golden[key].evidence, key
            assert segment_id not in {q.segment_id for q in golden[key].evidence}, (key, segment_id)
        for key, segment_id in added:
            assert segment_id in {q.segment_id for q in golden[key].evidence}, (key, segment_id)
            assert golden[key].state != "unknown", key


def test_the_golden_audit_is_recorded_for_every_product() -> None:
    check_audit(MANIFEST)


@pytest.mark.parametrize("product", sorted(PRODUCTS))
def test_a_dropped_segment_still_in_golden_is_caught(product: str) -> None:
    tampered = copy.deepcopy(MANIFEST)
    entry = next(r for r in tampered["revisions"] if r.get("method") == METHOD)["products"][product]
    golden = load_golden_v2(GOLDEN / f"{product}.json")
    field = next(f for f in golden.fields if f.evidence)
    entry["dropped"].append([field.field_key, field.evidence[0].segment_id])
    entry["fields"] = sorted(set(entry["fields"]) | {field.field_key})
    with pytest.raises(AssertionError):
        check_audit(tampered)


def test_an_added_segment_missing_from_golden_is_caught() -> None:
    tampered = copy.deepcopy(MANIFEST)
    revision = next(r for r in tampered["revisions"] if r.get("method") == METHOD)
    product = next(p for p in sorted(PRODUCTS) if revision["products"][p]["fields"])
    entry = revision["products"][product]
    entry["added"].append([entry["fields"][0], "D9P99S99"])
    with pytest.raises(AssertionError):
        check_audit(tampered)


def test_a_widened_pair_cannot_be_recorded_as_dropped() -> None:
    tampered = copy.deepcopy(MANIFEST)
    revision = next(r for r in tampered["revisions"] if r.get("method") == METHOD)
    product, pair = next(
        (p, pair)
        for p in sorted(PRODUCTS)
        for pair in sorted(earlier_pairs(tampered, "deterministic-remap", "quotes_widened", p))
    )
    revision["products"][product]["dropped"].append(list(pair))
    revision["products"][product]["fields"].append(pair[0])
    with pytest.raises(AssertionError):
        check_audit(tampered)


# Owner rulings recorded after review round 1 on #392 (Spec §6).


def evidence(product: str, field_key: str) -> set[str]:
    golden = load_golden_v2(GOLDEN / f"{product}.json")
    field = next(f for f in golden.fields if f.field_key == field_key)
    return {q.segment_id for q in field.evidence if q.segment_id}


def audit_entry(product: str) -> dict[str, Any]:
    revision = next(r for r in MANIFEST["revisions"] if r.get("method") == METHOD)
    entry: dict[str, Any] = revision["products"][product]
    return entry


def test_the_three_owner_rulings_are_recorded() -> None:
    revision = next(r for r in MANIFEST["revisions"] if r.get("method") == METHOD)
    assert len(revision["owner_rulings"]) == 3
    for product in PRODUCTS:
        overrides = audit_entry(product)["owner_overrides"]
        assert set(overrides) == {"reverted_adds", "restored", "held"}
        for key, segment_id in overrides["reverted_adds"]:
            assert segment_id not in evidence(product, key), (product, key, segment_id)
        for key, segment_id in overrides["restored"]:
            assert segment_id in evidence(product, key), (product, key, segment_id)


def test_a_worked_example_is_not_rule_evidence() -> None:
    assert "D1P6S7" not in evidence("1816", "income_loss_care_benefit_payment_rules")
    assert ["income_loss_care_benefit_payment_rules", "D1P6S7"] in audit_entry("1816")[
        "owner_overrides"
    ]["reverted_adds"]


@pytest.mark.parametrize(
    ("product", "referring", "conditions"),
    [
        (
            "1824",
            {"D2P4S7", "D2P4S8"},
            {f"D2P3S{n}" for n in range(10, 14)} | {f"D2P4S{n}" for n in range(1, 7)},
        ),
        (
            "1826",
            {"D1P3S11", "D1P3S12", "D2P4S5", "D2P4S6"},
            {f"D2P3S{n}" for n in range(10, 14)} | {f"D2P4S{n}" for n in range(1, 5)},
        ),
        (
            "1828",
            {"D2P8S3", "D2P8S17", "D2P8S18"},
            {"D2P8S1", "D2P8S2"} | {f"D2P8S{n}" for n in range(8, 17)},
        ),
    ],
)
def test_kept_referents_keep_the_conditions_they_point_to(
    product: str, referring: set[str], conditions: set[str]
) -> None:
    kept = evidence(product, "cash_value_rules")
    assert referring <= kept
    assert conditions <= kept
    assert not conditions & {
        s for k, s in audit_entry(product)["dropped"] if k == "cash_value_rules"
    }


def test_card_excludes_win_over_includes_examples() -> None:
    waiver_list = {"D1P1S4", "D1P5S2", "D2P22S21", "D2P22S22"}
    assert not waiver_list & evidence("1816", "covered_critical_specified_diseases")
    entry = audit_entry("1816")
    assert "covered_critical_specified_diseases" in entry["held_for_adjudication"]
    assert (
        "premium_waiver_critical_illnesses"
        in entry["owner_overrides"]["held"]["covered_critical_specified_diseases"]
    )
    assert waiver_list <= evidence("1816", "premium_waiver_critical_illnesses")
