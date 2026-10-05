"""All nine locator kinds share the public keyword constructor (Spec §8.2)."""

from typing import Any

import pytest
from pydantic import ValidationError

from insurance_harness.contracts import Locator

CASES: list[dict[str, Any]] = [
    {"kind": "PDF_TEXT_SPAN", "page": 1, "start": 0, "end": 2},
    {"kind": "OCR_REGION", "page": 1, "bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}},
    {"kind": "DOCX_BLOCK", "block_index": 0},
    {"kind": "DOCX_TABLE_CELL", "table_index": 0, "row": 0, "column": 0},
    {"kind": "PPTX_SHAPE", "slide": 1, "shape_id": "title"},
    {"kind": "XLSX_CELL_RANGE", "sheet": "Sheet1", "cell_range": "A1:B3"},
    {"kind": "CHUNK_SPAN", "chunk_id": "chunk-a", "start": 0, "end": 2},
    {"kind": "STRUCTURED_PATH", "path": ["items", "0", "name"]},
    {"kind": "EXPERT_REVISION", "revision_record_id": "revision-a"},
]


@pytest.mark.parametrize("fields", CASES)
def test_locator_round_trip(fields: dict[str, Any]) -> None:
    locator = Locator(**fields)
    assert locator.model_dump(mode="json", exclude_none=True) == fields
    assert Locator.model_validate_json(locator.model_dump_json()) == locator


@pytest.mark.parametrize("fields", CASES)
def test_every_kind_specific_field_is_required(fields: dict[str, Any]) -> None:
    for name in fields.keys() - {"kind"}:
        with pytest.raises(ValidationError):
            Locator(**{key: value for key, value in fields.items() if key != name})


@pytest.mark.parametrize("fields", [
    {"kind": "PDF_TEXT_SPAN", "page": 0, "start": 0, "end": 2},
    {"kind": "PDF_TEXT_SPAN", "page": 1, "start": -1, "end": 2},
    {"kind": "PDF_TEXT_SPAN", "page": 1, "start": 3, "end": 2},
    {"kind": "PDF_TEXT_SPAN", "page": True, "start": 0, "end": 2},
    {"kind": "OCR_REGION", "page": 1, "bbox": {"x": -0.1, "y": 0.2, "w": 0.3, "h": 0.4}},
    {"kind": "OCR_REGION", "page": 1, "bbox": {"x": 0.1, "y": 0.2, "w": 1.1, "h": 0.4}},
    {"kind": "OCR_REGION", "page": 1, "bbox": {"x": 0.1, "y": 0.2, "w": 0.3}},
    {"kind": "DOCX_BLOCK", "block_index": -1},
    {"kind": "DOCX_TABLE_CELL", "table_index": 0, "row": -1, "column": 0},
    {"kind": "PPTX_SHAPE", "slide": 0, "shape_id": "title"},
    {"kind": "PPTX_SHAPE", "slide": 1, "shape_id": " "},
    {"kind": "XLSX_CELL_RANGE", "sheet": "Sheet1", "cell_range": "A0"},
    {"kind": "CHUNK_SPAN", "chunk_id": " ", "start": 0, "end": 2},
    {"kind": "STRUCTURED_PATH", "path": []},
    {"kind": "STRUCTURED_PATH", "path": [""]},
    {"kind": "EXPERT_REVISION", "revision_record_id": ""},
    {"kind": "UNDECLARED"},
])
def test_invalid_locator_fails_closed(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Locator(**fields)
