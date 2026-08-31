"""Deterministic C5 authority and coordinate-folding contracts."""

from __future__ import annotations

import hashlib
from typing import cast

import pytest

from insurance_harness.knowledge_compiler import schema_wiki_c5_preview_815 as c5


def _source_row(
    *,
    quote: str,
    start: int | None,
    end: int | None,
    selection_type: str = "TEXT_SPAN",
) -> dict[str, object]:
    return {
        "selection_id": "selection-01",
        "field_id": "field-01",
        "source_role": "terms",
        "source_revision_id": "a" * 64,
        "original_file_sha256": "b" * 64,
        "parse_manifest_sha256": "c" * 64,
        "page_number": 1,
        "coordinate_space": "PDF_POINTS_TOP_LEFT_V1",
        "page_width_points": "595",
        "page_height_points": "842",
        "bbox": ["10", "20", "30", "40"],
        "rects": [["10", "20", "30", "40"]],
        "block_id": "block-01" if selection_type == "TEXT_SPAN" else None,
        "span_id": "span-01" if selection_type == "TEXT_SPAN" else None,
        "table_id": "table-01" if selection_type == "TABLE_SLICE" else None,
        "table_slice_id": "slice-01" if selection_type == "TABLE_SLICE" else None,
        "cell_ids": ["cell-01"] if selection_type == "TABLE_SLICE" else [],
        "quote": quote,
        "quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
        "page_text_char_start": start,
        "page_text_char_end": end,
        "selection_type": selection_type,
    }


def test_c5_folds_adjacent_unicode_text_without_changing_source_identity() -> None:
    first = _source_row(quote="甲乙", start=10, end=12)
    second = _source_row(quote="丙丁", start=13, end=15)
    second["bbox"] = ["31", "41", "50", "60"]
    second["rects"] = [["31", "41", "50", "60"]]

    folded = c5._fold_source_rows([first, second])

    assert len(folded) == 1
    source = folded[0]
    assert source["selection_id"] == "selection-01"
    assert source["page_text_char_start"] == 10
    assert source["page_text_char_end"] == 15
    assert source["quote"] == "甲乙\N{LINE SEPARATOR}丙丁"
    assert source["bbox"] == ["10", "20", "50", "60"]
    assert len(cast(list[object], source["rects"])) == 2


def test_c5_rejects_overlap_and_document_identity_drift() -> None:
    first = _source_row(quote="alpha", start=0, end=5)
    overlap = _source_row(quote="beta", start=4, end=8)
    with pytest.raises(ValueError, match="C5_SOURCE_SELECTION_UNREPLAYABLE"):
        c5._fold_source_rows([first, overlap])

    drift = _source_row(quote="beta", start=6, end=10)
    drift["source_revision_id"] = "d" * 64
    with pytest.raises(ValueError, match="C5_SOURCE_SELECTION_IDENTITY_MISMATCH"):
        c5._fold_source_rows([first, drift])


def test_c5_folds_table_cells_without_inventing_text_offsets() -> None:
    first = _source_row(
        quote="cell one",
        start=None,
        end=None,
        selection_type="TABLE_SLICE",
    )
    second = _source_row(
        quote="cell two",
        start=None,
        end=None,
        selection_type="TABLE_SLICE",
    )
    second["cell_ids"] = ["cell-02"]

    folded = c5._fold_source_rows([first, second])

    assert len(folded) == 1
    assert folded[0]["cell_ids"] == ["cell-01", "cell-02"]
    assert folded[0]["page_text_char_start"] is None
    assert folded[0]["page_text_char_end"] is None
