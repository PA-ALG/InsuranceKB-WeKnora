"""S4f acceptance: the rate-table revision of Golden v2 is recorded per product (Spec §2.2).

Protected file: written by Claude. Coverage period is re-annotated under draft-2026-10-16a,
where rate-table titles and headers are evidence for the options they list; product bundle rules
stay clause-only (user ruling 2026-10-16). File hashes and segment-id consistency stay covered by
test_golden_data.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from insurance_harness.eval.segment_score import load_golden_v2

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "dataset/golden/v2"
MANIFEST = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
RATE_TABLE_CARDS = "draft-2026-10-16a"
REVISED = {"coverage_period"}


def test_the_rate_table_revision_covers_every_product() -> None:
    revisions = [r for r in MANIFEST.get("revisions", []) if r["cards_version"] == RATE_TABLE_CARDS]
    assert len(revisions) == 1
    revision = revisions[0]
    assert set(revision["products"]) == set(MANIFEST["products"])
    for product, entry in revision["products"].items():
        keys = {field.field_key for field in load_golden_v2(GOLDEN / f"{product}.json").fields}
        assert set(entry["fields"]) == REVISED & keys
        assert entry["model_id"] and entry["reasoning_effort"] and entry["session_id"]
