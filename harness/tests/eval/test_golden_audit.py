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
