"""S4i acceptance: Golden v2 cites rate tables only as the TrustPolicy allows; remaps are recorded.

Protected file: written by Claude (Spec §3.4, revised after review R5 on #200). The remap is
mechanical: it moves evidence onto the S4i segments and empties what only rate tables supported.
Fields whose value or state rested on rate tables stay usable for segment diagnostics only until an
independent judge reviews them under the new rule; golden_items, the entry to semantic scoring and
threshold calibration, refuses them unless they are excluded explicitly and counted.

S4j (user ruling 2026-10-18) lets the payment term cite rate-table headers again: the Golden may
cite a rate table only for a field the TrustPolicy trusts with that role (the header range itself is
checked by test_golden_payment_term.py); S4i's revision stays as history, and a field it emptied
may be present now only when a later recorded revision restored it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.catalog.trust_policy import load_trust_policy
from insurance_harness.eval import golden_items
from insurance_harness.eval.pdf_text import read_pdf
from insurance_harness.eval.product_sources import source_directory
from insurance_harness.eval.segment_score import load_golden_v2
from insurance_harness.identity.material_roles import document_roles, load_material_roles

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "dataset/golden/v2"
MANIFEST = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
S4I_CARDS = "draft-2026-10-17a"
METHOD = "deterministic-remap"
# Frozen when the remap was made: every Golden v2 product, and the fields that cited rate tables
# (1828's rate table lists no coverage period, so its coverage_period never cited it).
S4I_PRODUCTS = {"1814", "1816", "1824", "1826", "1828"}
RATE_FIELDS = {
    "entry_age_range",
    "premium_payment_term",
    "premium_payment_frequency",
    "coverage_period",
}
CITED_RATE_TABLES = {
    **{product: RATE_FIELDS for product in ("1814", "1816", "1824", "1826")},
    "1828": RATE_FIELDS - {"coverage_period"},
}


def non_evidence_documents(product: str) -> dict[str, str]:
    evidence = {role.role: role.evidence for role in load_material_roles().roles}
    names: dict[str, str] = {}
    for path in sorted(source_directory(REPO, product).glob("*.pdf")):
        for document, role in document_roles(read_pdf(path)).items():
            if role is not None and not evidence[role]:
                names[document] = role
    return names


@pytest.mark.parametrize("product", sorted(S4I_PRODUCTS))
def test_golden_cites_rate_tables_only_for_fields_the_trust_policy_trusts(product: str) -> None:
    excluded = non_evidence_documents(product)
    assert excluded  # every product ships a rate table
    policy = load_trust_policy()
    golden = load_golden_v2(GOLDEN / f"{product}.json")
    for field in golden.fields:
        for quote in field.evidence:
            if quote.document in excluded:
                trusted = policy.header_fields(excluded[quote.document])
                assert field.field_key in trusted, (field.field_key, quote.document)


def restored_later(manifest: dict[str, Any], product: str) -> set[str]:
    """Fields a revision recorded after S4i's restored (S4j: trusted rate-table headers)."""
    revisions = manifest.get("revisions", [])
    s4i = next(i for i, r in enumerate(revisions) if r["cards_version"] == S4I_CARDS)
    return {
        key
        for revision in revisions[s4i + 1 :]
        for key in revision.get("products", {}).get(product, {}).get("restored", [])
    }


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
        for key, segment_id in entry["quotes_widened"]:
            assert segment_id in {q.segment_id for q in golden[key].evidence}
        for key in set(entry["to_unknown"]) - restored_later(manifest, product):
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


def test_every_field_rate_tables_supported_awaits_semantic_review() -> None:
    # Except what a trusted rate-table header supports again (S4j): the judge labelled those
    # fields from the very header the Golden now cites.
    trusted = load_trust_policy().header_fields("rate_table")
    pending = MANIFEST["pending_semantic_review"]
    assert set(pending) == S4I_PRODUCTS
    for product in S4I_PRODUCTS:
        assert set(pending[product]) == CITED_RATE_TABLES[product] - trusted, product


def test_golden_items_refuses_pending_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "items.jsonl"
    assert golden_items.main(["--products", "1824", "--out", str(out)]) == 2
    assert json.loads(capsys.readouterr().out.strip()) == {
        "stopped": "GOLDEN_PENDING_REVIEW",
        "product": "1824",
    }
    assert not out.exists()


def test_golden_items_excludes_pending_fields_only_when_asked_and_counts_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "items.jsonl"
    argv = ["--products", "1824", "1828", "--out", str(out), "--exclude-pending"]
    assert golden_items.main(argv) == 0
    summary = json.loads(capsys.readouterr().out.strip())
    pending = MANIFEST["pending_semantic_review"]
    assert summary["excluded_pending"] == {p: len(pending[p]) for p in ("1824", "1828")}
    written = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert not any(item["field_key"] in pending[item["product_id"]] for item in written)
    for product in ("1824", "1828"):
        total = len(load_golden_v2(GOLDEN / f"{product}.json").fields)
        assert summary["products"][product] == total - len(pending[product])
