"""S4e acceptance: Golden v2 files match the manifest, and their segment ids still hold the quotes.

Protected file: written by Claude. Scoring takes Golden evidence by its recorded segment id
(Spec §3.2). This check fails when the segmentation rules or the product sources change, which is
the signal to re-map Golden instead of letting ids silently point at other text. Revisions are
recorded per field.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from pathlib import Path

import pytest

from insurance_harness.eval.product_sources import source_directory, source_pages
from insurance_harness.eval.segment_score import load_golden_v2
from insurance_harness.evidence.segments import SegmentedSource

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "dataset/golden/v2"
MANIFEST = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
S4E_CARDS = "draft-2026-10-15j"


def squeeze(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text) if not c.isspace())


@pytest.mark.parametrize("product", sorted(MANIFEST["products"]))
def test_golden_file_matches_the_manifest_and_the_current_segments(product: str) -> None:
    path = GOLDEN / f"{product}.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == MANIFEST["files"][f"{product}.json"]
    golden = load_golden_v2(path)
    entry = MANIFEST["products"][product]
    assert golden.product_id == product and len(golden.fields) == entry["fields"]
    assert dict(Counter(field.state for field in golden.fields)) == entry["states"]

    source = SegmentedSource(source_pages(source_directory(REPO, product)))
    fingerprints = {page.document: page.document_sha256 for page in source.pages}
    assert fingerprints == entry["source_sha256"]
    segments = {segment.id: segment for segment in source.segments}
    for field in golden.fields:
        for quote in field.evidence:
            segment = segments.get(quote.segment_id or "")
            where = (field.field_key, quote.segment_id)
            assert segment is not None, where
            assert (segment.document, segment.page) == (quote.document, quote.page), where
            assert squeeze(segment.text) == squeeze(quote.quote), where
            assert quote.document_sha256 == fingerprints[quote.document], where


def test_the_s4e_revision_is_recorded_for_every_product() -> None:
    revisions = [r for r in MANIFEST.get("revisions", []) if r["cards_version"] == S4E_CARDS]
    assert len(revisions) == 1
    revision = revisions[0]
    assert set(revision["products"]) <= set(MANIFEST["products"])
    for product in set(MANIFEST["products"]) - set(revision["products"]):
        # Added after the revision (S4h: 1828), annotated directly under newer cards.
        later = load_golden_v2(GOLDEN / f"{product}.json").cards_version
        assert later > S4E_CARDS, product
    for product, entry in revision["products"].items():
        keys = {field.field_key for field in load_golden_v2(GOLDEN / f"{product}.json").fields}
        assert entry["fields"] and set(entry["fields"]) <= keys
        assert entry["model_id"] and entry["reasoning_effort"] and entry["session_id"]
