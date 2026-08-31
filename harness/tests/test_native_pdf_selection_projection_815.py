"""EC-01 one-pass native PDF text and coordinate projection."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from io import BytesIO
from pathlib import Path
from types import TracebackType
from typing import Any, Self, cast

import pdfplumber
import pytest

from insurance_harness.compiler import native_pdfplumber as native

_REVISION_ROOT_VALUE = os.environ.get("WEKNORA_EC01_REVISION_SET_ROOT")
_REVISION_ROOT = Path(_REVISION_ROOT_VALUE) if _REVISION_ROOT_VALUE else None
_SOURCE_BYTES = b"synthetic-native-pdf-selection-815"


class _FakeTable:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.bbox = tuple(payload["bbox"])
        self.rows = [
            type("Row", (), {"cells": tuple(row)})() for row in payload["rows"]
        ]
        self._values = cast(list[list[str]], payload["values"])

    def extract(self) -> list[list[str]]:
        return self._values


class _FakePage:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.width = payload["width"]
        self.height = payload["height"]
        self.bbox = (0, 0, self.width, self.height)
        self._words = cast(list[dict[str, Any]], payload["words"])
        self._tables = [_FakeTable(item) for item in payload["tables"]]

    def extract_words(self, **kwargs: object) -> list[dict[str, Any]]:
        assert kwargs == {
            "use_text_flow": True,
            "keep_blank_chars": False,
            "x_tolerance": 3,
            "y_tolerance": 3,
        }
        return self._words

    def find_tables(self) -> list[_FakeTable]:
        return self._tables


class _FakePdf:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.pages = [_FakePage(payload)]

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


def _payload() -> dict[str, Any]:
    return {
        "width": 612,
        "height": 792,
        "words": [
            {"text": "保障", "x0": 40, "top": 60, "x1": 70, "bottom": 74},
            {
                "text": "一般医疗",
                "x0": 76,
                "top": 60,
                "x1": 136,
                "bottom": 74,
            },
            {"text": "保障", "x0": 40, "top": 90, "x1": 70, "bottom": 104},
            {
                "text": "一般医疗",
                "x0": 76,
                "top": 90,
                "x1": 136,
                "bottom": 104,
            },
        ],
        "tables": [
            {
                "bbox": [40, 130, 300, 220],
                "rows": [
                    [[40, 130, 130, 150], [130, 130, 300, 150]],
                    [[40, 150, 130, 170], [130, 150, 300, 170]],
                    [[40, 190, 130, 210], [130, 190, 300, 210]],
                ],
                "values": [
                    ["年龄", "年度保费（元）"],
                    ["0岁", "3943"],
                    ["注：有社保费率", ""],
                ],
            },
            {
                "bbox": [40, 240, 300, 300],
                "rows": [
                    [[40, 240, 130, 260], [130, 240, 300, 260]],
                    [[40, 260, 130, 280], [130, 260, 300, 280]],
                ],
                "values": [["1", "2"], ["3", "4"]],
            },
        ],
    }


def _extract(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any] | None = None,
) -> tuple[native.NativePdfSelectionProjection815V1, list[bytes]]:
    opened: list[bytes] = []
    exact_payload = copy.deepcopy(payload or _payload())

    def _open(stream: BytesIO) -> _FakePdf:
        opened.append(stream.getvalue())
        return _FakePdf(exact_payload)

    monkeypatch.setattr(pdfplumber, "open", _open)
    projection = native.extract_native_pdf_selection_projection_815(
        _SOURCE_BYTES,
        expected_source_sha256=hashlib.sha256(_SOURCE_BYTES).hexdigest(),
        source_revision_id="terms-revision-1",
        source_role="terms",
    )
    return projection, opened


def test_815_projection_is_one_pass_exact_text_and_coordinates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection, opened = _extract(monkeypatch)
    page = projection.pages[0]

    assert opened == [_SOURCE_BYTES]
    assert projection.coordinate_space == "PDF_POINTS_TOP_LEFT_V1"
    assert projection.parse_manifest_sha256 == projection.recomputed_manifest_sha256()
    assert page.canonical_page_text == "保障 一般医疗\n保障 一般医疗"
    assert all(
        page.canonical_page_text[span.char_start : span.char_end] == span.exact_text
        for span in page.spans
    )
    assert all(
        page.canonical_page_text[word.char_start : word.char_end] == word.text
        for word in page.words
    )
    assert len(page.spans) == 2
    assert page.spans[0].exact_text == page.spans[1].exact_text
    assert page.spans[0].span_id != page.spans[1].span_id
    assert page.spans[0].rects != page.spans[1].rects


def test_815_table_slice_keeps_context_and_rejects_number_only_slice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection, _ = _extract(monkeypatch)
    page = projection.pages[0]

    assert len(page.table_slices) == 1
    assert page.table_slices[0].exact_text_parts == (
        "年龄",
        "年度保费（元）",
        "0岁",
        "3943",
        "注：有社保费率",
    )
    assert page.table_slices[0].ordered_cell_ids == tuple(
        item.cell_id
        for item in page.cells
        if item.table_id == page.table_slices[0].table_id and item.exact_text
    )
    assert page.table_unavailability == ()


def test_815_incomplete_table_coordinates_have_typed_unavailability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload()
    payload["tables"][0]["rows"][1][1] = None

    projection, _ = _extract(monkeypatch, payload)

    assert len(projection.pages[0].cells) == 4
    assert projection.pages[0].table_slices == ()
    assert projection.pages[0].table_unavailability == (
        native.NativeTableUnavailability815V1(
            table_index=0,
            reason="TABLE_CELL_COORDINATE_INCOMPLETE",
        ),
    )


def test_815_source_digest_fails_before_pdfplumber_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def _open(_: BytesIO) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(pdfplumber, "open", _open)
    with pytest.raises(native.NativePdfplumberError, match="source_digest_mismatch"):
        native.extract_native_pdf_selection_projection_815(
            _SOURCE_BYTES,
            expected_source_sha256="0" * 64,
            source_revision_id="terms-revision-1",
            source_role="terms",
        )
    assert calls == 0


def test_815_text_range_and_bbox_identity_domains_are_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline, _ = _extract(monkeypatch)
    changed_text_payload = _payload()
    changed_text_payload["words"][0]["text"] = "完整保障"
    changed_text, _ = _extract(monkeypatch, changed_text_payload)
    changed_bbox_payload = _payload()
    changed_bbox_payload["words"][0]["x0"] = 41
    changed_bbox, _ = _extract(monkeypatch, changed_bbox_payload)

    assert baseline.pages[0].words[0].word_id != changed_text.pages[0].words[0].word_id
    assert baseline.pages[0].words[1].word_id != changed_text.pages[0].words[1].word_id
    assert baseline.pages[0].words[0].word_id == changed_bbox.pages[0].words[0].word_id
    assert baseline.parse_manifest_sha256 != changed_bbox.parse_manifest_sha256


@pytest.mark.parametrize("role", ("terms", "brochure", "rate_table"))
def test_815_frozen_revision_set_native_projection_smoke(role: str) -> None:
    if _REVISION_ROOT is None or not _REVISION_ROOT.is_dir():
        pytest.skip("FROZEN_C1_REVISION_SET_UNAVAILABLE")
    manifest = cast(
        dict[str, Any],
        json.loads((_REVISION_ROOT / f"{role}.manifest.json").read_text()),
    )
    pdf_bytes = (_REVISION_ROOT / cast(str, manifest["material_file"])).read_bytes()

    projection = native.extract_native_pdf_selection_projection_815(
        pdf_bytes,
        expected_source_sha256=cast(str, manifest["file_sha256"]),
        source_revision_id=cast(str, manifest["compiler_source_revision_id"]),
        source_role=cast(Any, role),
    )

    assert len(projection.pages) == manifest["page_count"]
    assert projection.original_file_sha256 == manifest["file_sha256"]
    assert projection.source_revision_id == manifest["compiler_source_revision_id"]
    assert projection.source_role == role
    assert projection.parse_manifest_sha256 == projection.recomputed_manifest_sha256()
    assert all(
        page.canonical_page_text[word.char_start : word.char_end] == word.text
        and word.bbox
        for page in projection.pages
        for word in page.words
    )
    assert all(
        page.canonical_page_text[span.char_start : span.char_end] == span.exact_text
        and span.text_sha256 == hashlib.sha256(span.exact_text.encode()).hexdigest()
        and span.rects
        for page in projection.pages
        for span in page.spans
    )
    assert all(
        cell.text_sha256 == hashlib.sha256(cell.exact_text.encode()).hexdigest()
        and cell.bbox
        for page in projection.pages
        for cell in page.cells
    )
