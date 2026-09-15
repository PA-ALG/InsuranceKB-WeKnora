"""A field keeps all exact source locations, including later pages of one chunk."""

from __future__ import annotations

# ruff: noqa: F811
import copy
import hashlib
import importlib
import json

import pytest

from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import Evidence
from tests.product_ingestion.test_platform import snapshot  # noqa: F401
from tests.product_ingestion.test_source_geometry import native_snapshot


def project(evidence, decoded):
    module = importlib.import_module("insurance_harness.product_ingestion.source_geometry")
    helper = getattr(module, "project_evidence_locations", None)
    # The old publication input passes whole source-block evidence through.
    if helper is None:
        return (evidence,), {"parts": [], "gaps": []}
    return helper(evidence, decoded)


def evidence_for(decoded, start=0, end=None):
    b = decoded.blocks[0]
    end = len(b.text) if end is None else end
    return Evidence(
        **b.model_dump(exclude={"text"}),
        start=start,
        end=end,
        quote=b.text[start:end],
        quote_hash=hashlib.sha256(b.text[start:end].encode()).hexdigest(),
        offset_unit="UNICODE_CODE_POINT",
    )


def test_cross_page_evidence_retains_every_location_and_original(snapshot):
    decoded = native_snapshot(snapshot)
    evidence = evidence_for(decoded)
    before = evidence.model_dump_json()
    source_before = copy.deepcopy(decoded.snapshot)
    parts, audit = project(evidence, decoded)
    assert len(parts) == 2, "cross-page evidence must become two existing single-page citations"
    assert "".join(p.quote for p in parts) == evidence.quote
    assert {p.page_number for p in parts} == {evidence.page_number}
    assert [p["actual_page_number"] for p in audit["parts"]] == [1, 2]
    assert evidence.model_dump_json() == before and decoded.snapshot == source_before


def test_quote_wholly_on_later_page_is_not_rejected_or_rewritten(snapshot):
    decoded = native_snapshot(snapshot)
    cut = decoded.snapshot["chunk_page_mappings"][0]["page_spans"][0]["block_codepoint_end"]
    evidence = evidence_for(decoded, cut)
    parts, audit = project(evidence, decoded)
    assert parts == (evidence,)
    assert audit["parts"][0]["actual_page_number"] == 2


def test_single_page_evidence_is_byte_identical(snapshot):
    decoded = native_snapshot(snapshot)
    evidence = evidence_for(decoded, 0, 4)
    parts, audit = project(evidence, decoded)
    assert parts == (evidence,)


def test_non_whitespace_without_box_cannot_be_verified(snapshot):
    decoded = native_snapshot(snapshot)
    native = json.loads(decoded.native_bytes)
    native["pages"][0]["bboxes"] = native["pages"][0]["bboxes"][1:]
    from dataclasses import replace

    decoded = replace(decoded, native_bytes=json.dumps(native).encode())
    with pytest.raises(ValueError, match="EVIDENCE_CHARACTER_LOCATION_MISSING"):
        project(evidence_for(decoded, 0, 4), decoded)


def with_page_gap(decoded, gap_size):
    from dataclasses import replace

    body = copy.deepcopy(decoded.snapshot)
    native = json.loads(decoded.native_bytes)
    cut = native["pages"][0]["global_codepoint_end"]
    end = cut - gap_size
    native["pages"][0]["global_codepoint_end"] = end
    native["pages"][0]["page_text_sha256"] = hashlib.sha256(
        body["markdown"][:end].encode()
    ).hexdigest()
    native["pages"][0]["bboxes"] = [
        b for b in native["pages"][0]["bboxes"] if b["global_codepoint_end"] <= end
    ]
    span = body["chunk_page_mappings"][0]["page_spans"][0]
    span["global_codepoint_end"] = end
    span["block_codepoint_end"] = end - body["chunk_page_mappings"][0]["block_global_start"]
    return replace(decoded, snapshot=body, native_bytes=json.dumps(native).encode())


def test_page_separator_is_preserved_in_explicit_mapping_audit(snapshot):
    decoded = with_page_gap(native_snapshot(snapshot), 1)
    original = evidence_for(decoded)
    parts, audit = project(original, decoded)
    assert len(parts) == 2 and audit["gaps"][0]["text"] == "\n"
    spans = [(v["global_start"], v["global_end"]) for v in audit["parts"] + audit["gaps"]]
    assert "".join(decoded.snapshot["markdown"][a:b] for a, b in sorted(spans)) == original.quote
    assert parts[0].quote + audit["gaps"][0]["text"] + parts[1].quote == original.quote


def test_non_whitespace_gap_is_not_silently_dropped(snapshot):
    decoded = with_page_gap(native_snapshot(snapshot), 2)
    with pytest.raises(ValueError, match="EVIDENCE_UNLOCATED_CONTENT"):
        project(evidence_for(decoded), decoded)


def test_multiple_existing_quotes_keep_order_and_each_location(snapshot):
    decoded = native_snapshot(snapshot)
    originals = (evidence_for(decoded, 0, 4), evidence_for(decoded))
    projected = [project(e, decoded)[0] for e in originals]
    assert len(projected[0]) == 1 and len(projected[1]) == 2
    assert projected[0][0] == originals[0]
