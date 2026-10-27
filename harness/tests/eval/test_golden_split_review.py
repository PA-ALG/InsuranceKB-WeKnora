"""S12b: an independent judge reviewed the Golden pieces the S4i remap split (Spec §3, §4)."""

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
METHOD = "judge-split-review"
REMAP = "deterministic-remap"
PRODUCTS = {"1814", "1816", "1824", "1826", "1828"}


def remap_entries(manifest: dict[str, Any], product: str) -> list[dict[str, Any]]:
    return [
        r["products"][product]
        for r in manifest["revisions"]
        if r.get("method") == REMAP and product in r.get("products", {})
    ]


def check_split_review(manifest: dict[str, Any]) -> None:
    revisions = [r for r in manifest["revisions"] if r.get("method") == METHOD]
    assert len(revisions) == 1
    revision = revisions[0]
    assert revision["basis"] and revision["cards_version"]
    assert set(revision["products"]) == PRODUCTS <= set(manifest["products"])
    for product, entry in revision["products"].items():
        assert entry["judging_method"] == "codex-exec-file-exchange"
        assert entry["model_id"] == "gpt-6-astra" and entry["reasoning_effort"] == "xhigh"
        assert re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", entry["session_id"])
        golden = {f.field_key: f for f in load_golden_v2(GOLDEN / f"{product}.json").fields}
        remaps = remap_entries(manifest, product)
        split = {key for r in remaps for key in r["fields_split"]}
        widened = {tuple(pair) for r in remaps for pair in r["quotes_widened"]}
        dropped = {tuple(pair) for pair in entry["dropped"]}
        assert entry["pieces_reviewed"] >= len(dropped) + len(entry["pinned_widened"])
        assert len(dropped) == len(entry["dropped"])
        assert set(entry["fields"]) == {key for key, _ in dropped} <= split
        assert set(entry["held_for_adjudication"]) <= split
        assert not set(entry["fields"]) & set(entry["held_for_adjudication"])
        assert not dropped & widened
        assert {tuple(pair) for pair in entry["pinned_widened"]} <= widened
        for key, segment_id in dropped:
            field = golden[key]
            assert field.evidence, key
            assert segment_id not in {q.segment_id for q in field.evidence}, (key, segment_id)


def test_the_split_review_is_recorded_for_every_product() -> None:
    check_split_review(MANIFEST)


@pytest.mark.parametrize("product", sorted(PRODUCTS))
def test_a_dropped_piece_still_in_golden_is_caught(product: str) -> None:
    tampered = copy.deepcopy(MANIFEST)
    entry = next(r for r in tampered["revisions"] if r.get("method") == METHOD)["products"][product]
    golden = load_golden_v2(GOLDEN / f"{product}.json")
    field = next(f for f in golden.fields if f.field_key in entry["fields"])
    entry["dropped"].append([field.field_key, field.evidence[0].segment_id])
    with pytest.raises(AssertionError):
        check_split_review(tampered)


def test_a_widened_pair_cannot_be_recorded_as_dropped() -> None:
    tampered = copy.deepcopy(MANIFEST)
    revision = next(r for r in tampered["revisions"] if r.get("method") == METHOD)
    product, pair = next(
        (p, pair)
        for p in sorted(PRODUCTS)
        for r in remap_entries(tampered, p)
        for pair in r["quotes_widened"]
    )
    revision["products"][product]["dropped"].append(list(pair))
    revision["products"][product]["fields"].append(pair[0])
    with pytest.raises(AssertionError):
        check_split_review(tampered)
