"""S4i acceptance: Golden v2 cites no rate table, and the remap is recorded per product.

Protected file: written by Claude (Spec §3.4). The remap is deterministic: rate-table evidence is
removed, the rest is mapped by page position onto the S4i segments (test_golden_data.py checks the
ids hold the quotes), and a field left without evidence becomes unknown. Values are not edited.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.eval.pdf_text import read_pdf
from insurance_harness.eval.product_sources import source_directory
from insurance_harness.eval.segment_score import load_golden_v2
from insurance_harness.identity.material_roles import document_roles, load_material_roles

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "dataset/golden/v2"
MANIFEST = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
S4I_CARDS = "draft-2026-10-17a"
METHOD = "deterministic-remap"
# Frozen when the remap was made: every Golden v2 product at that time.
S4I_PRODUCTS = {"1814", "1816", "1824", "1826", "1828"}


def non_evidence_documents(product: str) -> set[str]:
    evidence = {role.role: role.evidence for role in load_material_roles().roles}
    names: set[str] = set()
    for path in sorted(source_directory(REPO, product).glob("*.pdf")):
        for document, role in document_roles(read_pdf(path)).items():
            if role is not None and not evidence[role]:
                names.add(document)
    return names


@pytest.mark.parametrize("product", sorted(S4I_PRODUCTS))
def test_golden_cites_no_rate_table(product: str) -> None:
    excluded = non_evidence_documents(product)
    assert excluded  # every product ships a rate table
    golden = load_golden_v2(GOLDEN / f"{product}.json")
    cited = {quote.document for field in golden.fields for quote in field.evidence}
    assert not cited & excluded


def check_s4i_revision(manifest: dict[str, Any]) -> None:
    revisions = [
        r
        for r in manifest.get("revisions", [])
        if r["cards_version"] == S4I_CARDS and r.get("method") == METHOD
    ]
    assert len(revisions) == 1
    revision = revisions[0]
    assert len(revision["baseline"]) == 40  # the commit whose segmentation the old ids follow
    assert set(revision["products"]) == S4I_PRODUCTS <= set(manifest["products"])
    for product, entry in revision["products"].items():
        golden = {f.field_key: f for f in load_golden_v2(GOLDEN / f"{product}.json").fields}
        assert entry["fields"] and set(entry["fields"]) <= set(golden)
        assert set(entry["to_unknown"]) <= set(entry["fields"])
        assert entry["rate_table_quotes_removed"] > 0
        assert entry["quotes_split"] >= 0
        for key in entry["to_unknown"]:
            field = golden[key]
            assert field.state == "unknown" and field.value is None and not field.evidence
            assert "费率表" in field.reason


def test_the_s4i_remap_is_recorded_for_every_product() -> None:
    check_s4i_revision(MANIFEST)


def test_dropping_a_product_from_the_s4i_remap_is_caught() -> None:
    for product in S4I_PRODUCTS:
        tampered = copy.deepcopy(MANIFEST)
        revision = next(r for r in tampered["revisions"] if r.get("method") == METHOD)
        del revision["products"][product]
        with pytest.raises(AssertionError):
            check_s4i_revision(tampered)
