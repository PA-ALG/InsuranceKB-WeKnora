"""S4f acceptance: the rate-table revision of Golden v2 is recorded per product (Spec §2.2).

Protected file: written by Claude. Coverage period is re-annotated under draft-2026-10-16a,
where rate-table titles and headers are evidence for the options they list; product bundle rules
stay clause-only (user ruling 2026-10-16). File hashes and segment-id consistency stay covered by
test_golden_data.py.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.eval.segment_score import load_golden_v2

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "dataset/golden/v2"
MANIFEST = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
RATE_TABLE_CARDS = "draft-2026-10-16a"
REVISED = {"coverage_period"}


# Frozen when the revision was made; products added later (S4h: 1828) are not part of it.
RATE_TABLE_PRODUCTS = {"1814", "1816", "1824", "1826"}


def check_rate_table_revision(manifest: dict[str, Any]) -> None:
    revisions = [r for r in manifest.get("revisions", []) if r["cards_version"] == RATE_TABLE_CARDS]
    assert len(revisions) == 1
    revision = revisions[0]
    assert set(revision["products"]) == RATE_TABLE_PRODUCTS
    assert RATE_TABLE_PRODUCTS <= set(manifest["products"])
    for product, entry in revision["products"].items():
        keys = {field.field_key for field in load_golden_v2(GOLDEN / f"{product}.json").fields}
        assert set(entry["fields"]) == REVISED & keys
        assert entry["model_id"] and entry["reasoning_effort"] and entry["session_id"]


def test_the_rate_table_revision_covers_every_product() -> None:
    check_rate_table_revision(MANIFEST)


def test_dropping_a_product_from_the_rate_table_revision_is_caught() -> None:
    for product in RATE_TABLE_PRODUCTS:
        tampered = copy.deepcopy(MANIFEST)
        revision = next(r for r in tampered["revisions"] if r["cards_version"] == RATE_TABLE_CARDS)
        del revision["products"][product]
        with pytest.raises(AssertionError):
            check_rate_table_revision(tampered)
