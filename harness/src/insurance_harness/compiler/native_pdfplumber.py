"""Task-local native pdfplumber facts for OpenSpec 056 Stage 0.

This module deliberately does not define ParsedDocument, ParseManifest, quality
decisions, or canonical approval hashes. It records only facts returned by
pdfplumber and bridges them through the sole OpenSpec 053 contracts.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any, Final, Literal, cast

from insurance_harness.compiler.material_profiles import MaterialProfileResolution
from insurance_harness.compiler.parsed_documents import (
    CapabilityEvidenceV1,
    CellLocatorV1,
    PageLocatorV1,
    ParseAttemptV1,
    ParseCellV1,
    ParsedDocumentV1,
    ParseManifestV1,
    ParseOutputFactsV1,
    ParsePageV1,
    ParseQualityDecisionV1,
    ParserIdentityV1,
    ParseSnapshotV1,
    ParseSubjectV1,
    ParseTableV1,
    ParseWarningV1,
    TableLocatorV1,
    UnsupportedParseFactV1,
    build_parse_manifest,
    evaluate_parse_quality,
)

NativeBBox = tuple[str, str, str, str]

_NATIVE_SELECTION_ADAPTER_VERSION_815: Final[str] = (
    "pdfplumber-0.11.10/native-text-position.815.v1"
)

_FIXED_UNSUPPORTED: Final[tuple[str, ...]] = (
    "block_locators",
    "header_hierarchy",
    "merged_cells",
    "cross_page_sections",
    "cross_page_tables",
)


class NativePdfplumberError(ValueError):
    """Typed rejection of malformed or identity-drifted native parser facts."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class NativeWordFact:
    word_id: str
    word_index: int
    bbox: NativeBBox
    content_sha256: str
    text_length: int


@dataclass(frozen=True, slots=True)
class NativeCellFact:
    cell_id: str
    row_index: int
    column_index: int
    bbox: NativeBBox
    content_sha256: str
    text_length: int


@dataclass(frozen=True, slots=True)
class NativeTableFact:
    table_id: str
    table_index: int
    bbox: NativeBBox
    row_count: int
    column_count: int
    cells: tuple[NativeCellFact, ...]
    missing_cell_positions: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class NativePageFact:
    page_id: str
    page_number: int
    bbox: NativeBBox
    words: tuple[NativeWordFact, ...]
    tables: tuple[NativeTableFact, ...]


@dataclass(frozen=True, slots=True)
class NativeCapabilityEvidence:
    capability: str
    subject_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NativePdfplumberFacts:
    parser_engine: str
    parser_build_id: str
    parser_config_hash: str
    source_sha256: str
    pages: tuple[NativePageFact, ...]
    capability_evidence: tuple[NativeCapabilityEvidence, ...]
    supported_capabilities: tuple[str, ...]
    unsupported_capabilities: tuple[str, ...]

    @property
    def diagnostic_sha256(self) -> str:
        """Diagnostic digest only; never an approval or 053/C0 authority."""

        payload = json.dumps(
            asdict(self),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class NativeTextWord815V1:
    word_id: str
    text: str
    char_start: int
    char_end: int
    bbox: NativeBBox


@dataclass(frozen=True, slots=True)
class NativeTextSpan815V1:
    span_id: str
    parent_block_id: str
    page_number: int
    char_start: int
    char_end: int
    rects: tuple[NativeBBox, ...]
    exact_text: str
    text_sha256: str


@dataclass(frozen=True, slots=True)
class NativeTableCell815V1:
    cell_id: str
    table_id: str
    page_number: int
    row_index: int
    column_index: int
    exact_text: str
    text_sha256: str
    bbox: NativeBBox


@dataclass(frozen=True, slots=True)
class NativeTableSlice815V1:
    table_slice_id: str
    table_id: str
    page_numbers: tuple[int, ...]
    ordered_cell_ids: tuple[str, ...]
    exact_text_parts: tuple[str, ...]
    slice_sha256: str


NativeTableUnavailabilityReason815 = Literal[
    "TABLE_SHAPE_INCOMPLETE",
    "TABLE_CELL_COORDINATE_INCOMPLETE",
]


@dataclass(frozen=True, slots=True)
class NativeTableUnavailability815V1:
    table_index: int
    reason: NativeTableUnavailabilityReason815


@dataclass(frozen=True, slots=True)
class NativePdfPageProjection815V1:
    page_number: int
    page_width_points: str
    page_height_points: str
    canonical_page_text: str
    page_text_sha256: str
    words: tuple[NativeTextWord815V1, ...]
    spans: tuple[NativeTextSpan815V1, ...]
    cells: tuple[NativeTableCell815V1, ...]
    table_slices: tuple[NativeTableSlice815V1, ...]
    table_unavailability: tuple[NativeTableUnavailability815V1, ...]


@dataclass(frozen=True, slots=True)
class NativePdfSelectionProjection815V1:
    adapter_version: str
    coordinate_space: Literal["PDF_POINTS_TOP_LEFT_V1"]
    source_revision_id: str
    source_role: Literal["terms", "brochure", "rate_table"]
    original_file_sha256: str
    pages: tuple[NativePdfPageProjection815V1, ...]
    parse_manifest_sha256: str

    def recomputed_manifest_sha256(self) -> str:
        payload = asdict(self)
        payload.pop("parse_manifest_sha256")
        return _native_815_hash("parse-manifest", payload)


def _content_sha256(value: object) -> tuple[str, int]:
    text = "" if value is None else str(value)
    return hashlib.sha256(text.encode()).hexdigest(), len(text)


def _native_structure_hash(label: str, payload: object) -> str:
    """Hash task-local native structure without creating a second C0 authority."""

    encoded = json.dumps(
        {"domain": f"native-pdfplumber-056:{label}", "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _native_815_hash(label: str, payload: object) -> str:
    encoded = json.dumps(
        {"domain": f"native-pdf-selection.815:{label}", "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _native_subject_id_815(
    *,
    prefix: str,
    source_revision_id: str,
    file_sha256: str,
    page_number: int,
    subject_type: str,
    subject_range: tuple[int, ...],
    exact_text_sha256: str,
) -> str:
    digest = _native_815_hash(
        "subject-id",
        {
            "adapter_version": _NATIVE_SELECTION_ADAPTER_VERSION_815,
            "source_revision_id": source_revision_id,
            "file_sha256": file_sha256,
            "page_number": page_number,
            "subject_type": subject_type,
            "subject_range": subject_range,
            "exact_text_sha256": exact_text_sha256,
        },
    )
    return f"{prefix}-{digest}"


def _canonical_number(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise NativePdfplumberError("invalid_native_bbox")
    if isinstance(value, float) and not math.isfinite(value):
        raise NativePdfplumberError("invalid_native_bbox")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise NativePdfplumberError("invalid_native_bbox") from exc
    if not number.is_finite():
        raise NativePdfplumberError("invalid_native_bbox")
    normalized = number.normalize()
    return format(normalized, "f")


def _bbox(raw: object) -> NativeBBox:
    if not isinstance(raw, (tuple, list)) or len(raw) != 4:
        raise NativePdfplumberError("invalid_native_bbox")
    left, top, right, bottom = tuple(_canonical_number(item) for item in raw)
    if Decimal(right) <= Decimal(left) or Decimal(bottom) <= Decimal(top):
        raise NativePdfplumberError("invalid_native_bbox")
    return left, top, right, bottom


def _word_fact(raw: object, *, page_number: int, word_index: int) -> NativeWordFact:
    if not isinstance(raw, dict):
        raise NativePdfplumberError("invalid_native_word")
    required = {"text", "x0", "top", "x1", "bottom"}
    if not required.issubset(raw):
        raise NativePdfplumberError("invalid_native_word")
    content_sha256, text_length = _content_sha256(raw["text"])
    return NativeWordFact(
        word_id=f"page-{page_number:04d}-word-{word_index:06d}",
        word_index=word_index,
        bbox=_bbox((raw["x0"], raw["top"], raw["x1"], raw["bottom"])),
        content_sha256=content_sha256,
        text_length=text_length,
    )


def _table_fact(raw: Any, *, page_number: int, table_index: int) -> NativeTableFact:
    rows = tuple(tuple(row.cells) for row in raw.rows)
    values = tuple(tuple(row) for row in raw.extract())
    if not rows or len(rows) != len(values):
        raise NativePdfplumberError("native_table_shape_mismatch")
    column_count = len(rows[0])
    if column_count == 0 or any(len(row) != column_count for row in rows + values):
        raise NativePdfplumberError("native_table_shape_mismatch")

    table_id = f"page-{page_number:04d}-table-{table_index:04d}"
    cells: list[NativeCellFact] = []
    missing: list[tuple[int, int]] = []
    for row_index, (row_cells, row_values) in enumerate(zip(rows, values, strict=True)):
        for column_index, (cell_bbox, value) in enumerate(
            zip(row_cells, row_values, strict=True)
        ):
            if cell_bbox is None:
                missing.append((row_index, column_index))
                continue
            content_sha256, text_length = _content_sha256(value)
            cells.append(
                NativeCellFact(
                    cell_id=f"{table_id}-cell-{row_index:04d}-{column_index:04d}",
                    row_index=row_index,
                    column_index=column_index,
                    bbox=_bbox(cell_bbox),
                    content_sha256=content_sha256,
                    text_length=text_length,
                )
            )
    return NativeTableFact(
        table_id=table_id,
        table_index=table_index,
        bbox=_bbox(raw.bbox),
        row_count=len(rows),
        column_count=column_count,
        cells=tuple(cells),
        missing_cell_positions=tuple(missing),
    )


def extract_native_pdfplumber_facts(
    pdf_bytes: bytes,
    *,
    expected_source_sha256: str,
    parser_build_id: str,
    parser_config_hash: str,
) -> NativePdfplumberFacts:
    """Extract native facts from exact bytes without retaining source text."""

    actual_source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    if actual_source_sha256 != expected_source_sha256:
        raise NativePdfplumberError("source_digest_mismatch")
    if not parser_build_id.strip():
        raise NativePdfplumberError("parser_identity_missing")
    if len(parser_config_hash) != 64 or any(
        character not in "0123456789abcdef" for character in parser_config_hash
    ):
        raise NativePdfplumberError("parser_identity_missing")

    import pdfplumber

    pages: list[NativePageFact] = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            words = tuple(
                _word_fact(raw, page_number=page_number, word_index=index)
                for index, raw in enumerate(page.extract_words())
            )
            tables = tuple(
                _table_fact(raw, page_number=page_number, table_index=index)
                for index, raw in enumerate(page.find_tables())
            )
            pages.append(
                NativePageFact(
                    page_id=f"page-{page_number:04d}",
                    page_number=page_number,
                    bbox=_bbox(page.bbox),
                    words=words,
                    tables=tables,
                )
            )
    if not pages:
        raise NativePdfplumberError("native_document_empty")

    all_tables = tuple(table for page in pages for table in page.tables)
    all_cells_located = bool(all_tables) and all(
        not table.missing_cell_positions for table in all_tables
    )
    page_ids = tuple(page.page_id for page in pages)
    word_ids = tuple(word.word_id for page in pages for word in page.words)
    table_ids = tuple(table.table_id for table in all_tables)
    cell_ids = tuple(cell.cell_id for table in all_tables for cell in table.cells)
    evidence = [NativeCapabilityEvidence("ordered_pages", page_ids)]
    supported = ["ordered_pages"]
    if word_ids:
        evidence.append(NativeCapabilityEvidence("word_locators", word_ids))
        supported.append("word_locators")
    if all_tables:
        evidence.append(NativeCapabilityEvidence("table_grid", table_ids))
        supported.append("table_grid")
    if all_cells_located:
        evidence.extend(
            (
                NativeCapabilityEvidence("cell_locators", cell_ids),
                NativeCapabilityEvidence("row_column_indices", cell_ids),
            )
        )
        supported.extend(("cell_locators", "row_column_indices"))

    unsupported = list(_FIXED_UNSUPPORTED)
    if not word_ids:
        unsupported.append("word_locators")
    if not all_tables:
        unsupported.append("table_grid")
    if not all_cells_located:
        unsupported.extend(("cell_locators", "row_column_indices"))
    ordered_unsupported = tuple(
        capability
        for capability in (
            "word_locators",
            "block_locators",
            "cell_locators",
            "header_hierarchy",
            "merged_cells",
            "row_column_indices",
            "table_grid",
            "cross_page_sections",
            "cross_page_tables",
        )
        if capability in unsupported
    )
    return NativePdfplumberFacts(
        parser_engine="pdfplumber",
        parser_build_id=parser_build_id,
        parser_config_hash=parser_config_hash,
        source_sha256=actual_source_sha256,
        pages=tuple(pages),
        capability_evidence=tuple(evidence),
        supported_capabilities=tuple(supported),
        unsupported_capabilities=ordered_unsupported,
    )


def _union_bbox_815(values: tuple[NativeBBox, ...]) -> NativeBBox:
    if not values:
        raise NativePdfplumberError("native_selection_span_empty")
    decimals = tuple(_decimal_bbox(item) for item in values)
    return (
        _canonical_number(min(item[0] for item in decimals)),
        _canonical_number(min(item[1] for item in decimals)),
        _canonical_number(max(item[2] for item in decimals)),
        _canonical_number(max(item[3] for item in decimals)),
    )


def _native_text_projection_815(
    raw_words: object,
    *,
    source_revision_id: str,
    file_sha256: str,
    page_number: int,
) -> tuple[str, tuple[NativeTextWord815V1, ...], tuple[NativeTextSpan815V1, ...]]:
    if not isinstance(raw_words, list):
        raise NativePdfplumberError("invalid_native_word")
    parsed: list[tuple[str, NativeBBox, Decimal]] = []
    for raw in raw_words:
        if not isinstance(raw, dict) or not {"text", "x0", "top", "x1", "bottom"}.issubset(
            raw
        ):
            raise NativePdfplumberError("invalid_native_word")
        text = raw["text"]
        if not isinstance(text, str) or not text:
            raise NativePdfplumberError("invalid_native_word")
        parsed.append(
            (
                text,
                _bbox((raw["x0"], raw["top"], raw["x1"], raw["bottom"])),
                Decimal(_canonical_number(raw["top"])),
            )
        )

    lines: list[list[tuple[str, NativeBBox, Decimal]]] = []
    for item in parsed:
        if not lines or abs(item[2] - lines[-1][-1][2]) > Decimal("2"):
            lines.append([item])
        else:
            lines[-1].append(item)

    page_parts: list[str] = []
    words: list[NativeTextWord815V1] = []
    spans: list[NativeTextSpan815V1] = []
    cursor = 0
    for line_index, line in enumerate(lines):
        if line_index:
            page_parts.append("\n")
            cursor += 1
        line_start = cursor
        line_word_boxes: list[NativeBBox] = []
        for word_index, (text, bbox, _top) in enumerate(line):
            if word_index:
                page_parts.append(" ")
                cursor += 1
            start = cursor
            page_parts.append(text)
            cursor += len(text)
            text_sha256 = hashlib.sha256(text.encode()).hexdigest()
            words.append(
                NativeTextWord815V1(
                    word_id=_native_subject_id_815(
                        prefix="word",
                        source_revision_id=source_revision_id,
                        file_sha256=file_sha256,
                        page_number=page_number,
                        subject_type="TEXT_WORD",
                        subject_range=(start, cursor),
                        exact_text_sha256=text_sha256,
                    ),
                    text=text,
                    char_start=start,
                    char_end=cursor,
                    bbox=bbox,
                )
            )
            line_word_boxes.append(bbox)
        line_end = cursor
        exact_text = " ".join(item[0] for item in line)
        text_sha256 = hashlib.sha256(exact_text.encode()).hexdigest()
        spans.append(
            NativeTextSpan815V1(
                span_id=_native_subject_id_815(
                    prefix="span",
                    source_revision_id=source_revision_id,
                    file_sha256=file_sha256,
                    page_number=page_number,
                    subject_type="TEXT_SPAN",
                    subject_range=(line_start, line_end),
                    exact_text_sha256=text_sha256,
                ),
                parent_block_id=_native_subject_id_815(
                    prefix="block",
                    source_revision_id=source_revision_id,
                    file_sha256=file_sha256,
                    page_number=page_number,
                    subject_type="TEXT_BLOCK",
                    subject_range=(line_start, line_end),
                    exact_text_sha256=text_sha256,
                ),
                page_number=page_number,
                char_start=line_start,
                char_end=line_end,
                rects=(_union_bbox_815(tuple(line_word_boxes)),),
                exact_text=exact_text,
                text_sha256=text_sha256,
            )
        )
    return "".join(page_parts), tuple(words), tuple(spans)


def _has_table_context_815(parts: tuple[str, ...]) -> bool:
    return any(character.isalpha() for part in parts for character in part)


def _native_table_projection_815(
    raw_tables: object,
    *,
    source_revision_id: str,
    file_sha256: str,
    page_number: int,
) -> tuple[
    tuple[NativeTableCell815V1, ...],
    tuple[NativeTableSlice815V1, ...],
    tuple[NativeTableUnavailability815V1, ...],
]:
    if not isinstance(raw_tables, list):
        raise NativePdfplumberError("native_table_shape_mismatch")
    all_cells: list[NativeTableCell815V1] = []
    all_slices: list[NativeTableSlice815V1] = []
    unavailability: list[NativeTableUnavailability815V1] = []
    for table_index, raw in enumerate(raw_tables):
        try:
            rows = tuple(tuple(row.cells) for row in raw.rows)
            values = tuple(tuple(row) for row in raw.extract())
        except (AttributeError, TypeError, ValueError, NativePdfplumberError):
            unavailability.append(
                NativeTableUnavailability815V1(
                    table_index=table_index,
                    reason="TABLE_SHAPE_INCOMPLETE",
                )
            )
            continue
        if (
            not rows
            or len(rows) != len(values)
            or not rows[0]
            or any(len(row) != len(rows[0]) for row in rows + values)
        ):
            unavailability.append(
                NativeTableUnavailability815V1(
                    table_index=table_index,
                    reason="TABLE_SHAPE_INCOMPLETE",
                )
            )
            continue
        if any(cell_bbox is None for row in rows for cell_bbox in row):
            unavailability.append(
                NativeTableUnavailability815V1(
                    table_index=table_index,
                    reason="TABLE_CELL_COORDINATE_INCOMPLETE",
                )
            )
            continue
        normalized_values = tuple(
            tuple("" if value is None else str(value) for value in row)
            for row in values
        )
        table_text_sha256 = hashlib.sha256(
            "\n".join("\t".join(row) for row in normalized_values).encode()
        ).hexdigest()
        table_id = _native_subject_id_815(
            prefix="table",
            source_revision_id=source_revision_id,
            file_sha256=file_sha256,
            page_number=page_number,
            subject_type="TABLE",
            subject_range=(table_index,),
            exact_text_sha256=table_text_sha256,
        )
        cells_by_position: dict[tuple[int, int], NativeTableCell815V1] = {}
        table_cells: list[NativeTableCell815V1] = []
        try:
            for row_index, (row_boxes, row_values) in enumerate(
                zip(rows, normalized_values, strict=True)
            ):
                for column_index, (cell_bbox, exact_text) in enumerate(
                    zip(row_boxes, row_values, strict=True)
                ):
                    text_sha256 = hashlib.sha256(exact_text.encode()).hexdigest()
                    cell = NativeTableCell815V1(
                        cell_id=_native_subject_id_815(
                            prefix="cell",
                            source_revision_id=source_revision_id,
                            file_sha256=file_sha256,
                            page_number=page_number,
                            subject_type="TABLE_CELL",
                            subject_range=(table_index, row_index, column_index),
                            exact_text_sha256=text_sha256,
                        ),
                        table_id=table_id,
                        page_number=page_number,
                        row_index=row_index,
                        column_index=column_index,
                        exact_text=exact_text,
                        text_sha256=text_sha256,
                        bbox=_bbox(cell_bbox),
                    )
                    cells_by_position[(row_index, column_index)] = cell
                    table_cells.append(cell)
        except (TypeError, ValueError, NativePdfplumberError):
            unavailability.append(
                NativeTableUnavailability815V1(
                    table_index=table_index,
                    reason="TABLE_CELL_COORDINATE_INCOMPLETE",
                )
            )
            continue
        all_cells.extend(table_cells)

        nonempty_positions = tuple(
            tuple(
                (row_index, column_index)
                for column_index, value in enumerate(row_values)
                if value
            )
            for row_index, row_values in enumerate(normalized_values)
        )
        header_positions = nonempty_positions[0]
        footnote_rows = tuple(
            row_index
            for row_index in range(1, len(normalized_values))
            if (positions := nonempty_positions[row_index])
            and normalized_values[positions[0][0]][positions[0][1]].startswith(
                ("注", "说明", "备注")
            )
        )
        footnote_positions = tuple(
            position
            for row_index in footnote_rows
            for position in nonempty_positions[row_index]
        )
        for row_index in range(1, len(normalized_values)):
            if row_index in footnote_rows:
                continue
            row_positions = nonempty_positions[row_index]
            ordered_positions = (
                *header_positions,
                *row_positions,
                *footnote_positions,
            )
            if len(header_positions) < 2 or len(row_positions) < 2:
                continue
            parts = tuple(
                normalized_values[row][column] for row, column in ordered_positions
            )
            if not _has_table_context_815(parts):
                continue
            ordered_cells = tuple(cells_by_position[position] for position in ordered_positions)
            slice_payload = {
                "table_id": table_id,
                "page_numbers": (page_number,),
                "ordered_cell_ids": tuple(item.cell_id for item in ordered_cells),
                "exact_text_parts": parts,
            }
            slice_sha256 = _native_815_hash("table-slice", slice_payload)
            all_slices.append(
                NativeTableSlice815V1(
                    table_slice_id=_native_subject_id_815(
                        prefix="table-slice",
                        source_revision_id=source_revision_id,
                        file_sha256=file_sha256,
                        page_number=page_number,
                        subject_type="TABLE_SLICE",
                        subject_range=(table_index, row_index),
                        exact_text_sha256=hashlib.sha256(
                            "\n".join(parts).encode()
                        ).hexdigest(),
                    ),
                    table_id=table_id,
                    page_numbers=(page_number,),
                    ordered_cell_ids=tuple(item.cell_id for item in ordered_cells),
                    exact_text_parts=parts,
                    slice_sha256=slice_sha256,
                )
            )
    return tuple(all_cells), tuple(all_slices), tuple(unavailability)


def extract_native_pdf_selection_projection_815(
    pdf_bytes: bytes,
    *,
    expected_source_sha256: str,
    source_revision_id: str,
    source_role: Literal["terms", "brochure", "rate_table"],
) -> NativePdfSelectionProjection815V1:
    """Project exact native text and positions from one read of the source PDF."""

    actual_source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    if actual_source_sha256 != expected_source_sha256:
        raise NativePdfplumberError("source_digest_mismatch")
    if not source_revision_id.strip() or source_role not in {
        "terms",
        "brochure",
        "rate_table",
    }:
        raise NativePdfplumberError("native_selection_identity_invalid")

    import pdfplumber

    pages: list[NativePdfPageProjection815V1] = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            canonical_text, words, spans = _native_text_projection_815(
                page.extract_words(
                    use_text_flow=True,
                    keep_blank_chars=False,
                    x_tolerance=3,
                    y_tolerance=3,
                ),
                source_revision_id=source_revision_id,
                file_sha256=actual_source_sha256,
                page_number=page_number,
            )
            cells, table_slices, table_unavailability = _native_table_projection_815(
                page.find_tables(),
                source_revision_id=source_revision_id,
                file_sha256=actual_source_sha256,
                page_number=page_number,
            )
            pages.append(
                NativePdfPageProjection815V1(
                    page_number=page_number,
                    page_width_points=_canonical_number(page.width),
                    page_height_points=_canonical_number(page.height),
                    canonical_page_text=canonical_text,
                    page_text_sha256=hashlib.sha256(canonical_text.encode()).hexdigest(),
                    words=words,
                    spans=spans,
                    cells=cells,
                    table_slices=table_slices,
                    table_unavailability=table_unavailability,
                )
            )
    if not pages:
        raise NativePdfplumberError("native_document_empty")
    provisional = NativePdfSelectionProjection815V1(
        adapter_version=_NATIVE_SELECTION_ADAPTER_VERSION_815,
        coordinate_space="PDF_POINTS_TOP_LEFT_V1",
        source_revision_id=source_revision_id,
        source_role=source_role,
        original_file_sha256=actual_source_sha256,
        pages=tuple(pages),
        parse_manifest_sha256="",
    )
    return NativePdfSelectionProjection815V1(
        adapter_version=provisional.adapter_version,
        coordinate_space=provisional.coordinate_space,
        source_revision_id=provisional.source_revision_id,
        source_role=provisional.source_role,
        original_file_sha256=provisional.original_file_sha256,
        pages=provisional.pages,
        parse_manifest_sha256=provisional.recomputed_manifest_sha256(),
    )


def _decimal_bbox(value: NativeBBox) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    return cast(
        tuple[Decimal, Decimal, Decimal, Decimal],
        tuple(Decimal(item) for item in value),
    )


def _bridge_identity_is_exact(
    facts: NativePdfplumberFacts,
    *,
    subject: ParseSubjectV1,
    parser: ParserIdentityV1,
    resolution: MaterialProfileResolution,
) -> bool:
    return (
        facts.source_sha256 == subject.source_sha256
        and subject.source_sha256 == resolution.profile.source.sha256
        and subject.space_id == resolution.request.space_id
        and subject.product_version_id == resolution.request.product_version
        and subject.material_profile_id == resolution.profile.profile_id
        and subject.material_profile_binding_hash == resolution.binding_hash
        and parser.parser_id == facts.parser_engine
        and parser.parser_build_id == facts.parser_build_id
        and parser.parser_config_hash == facts.parser_config_hash
    )


def build_parsed_document_v1(  # noqa: C901
    facts: NativePdfplumberFacts,
    *,
    subject: ParseSubjectV1,
    parser: ParserIdentityV1,
    attempt: ParseAttemptV1,
    snapshot: ParseSnapshotV1,
    output_facts: ParseOutputFactsV1,
    material_profile_resolution: MaterialProfileResolution,
) -> tuple[ParsedDocumentV1, ParseManifestV1, ParseQualityDecisionV1]:
    """Bridge proven native facts into the sole OpenSpec 053 contract and gate."""

    if not _bridge_identity_is_exact(
        facts,
        subject=subject,
        parser=parser,
        resolution=material_profile_resolution,
    ):
        raise NativePdfplumberError("bridge_identity_mismatch")

    pages = tuple(
        ParsePageV1(
            page_id=page.page_id,
            order_index=index,
            locator=PageLocatorV1(page_number=page.page_number),
            content_hash=_native_structure_hash(
                "page-content",
                {
                    "word_hashes": tuple(word.content_sha256 for word in page.words),
                    "table_ids": tuple(table.table_id for table in page.tables),
                },
            ),
            structure_hash=_native_structure_hash(
                "page-structure",
                {
                    "bbox": page.bbox,
                    "word_ids": tuple(word.word_id for word in page.words),
                    "table_ids": tuple(table.table_id for table in page.tables),
                },
            ),
        )
        for index, page in enumerate(facts.pages)
    )

    native_tables = tuple(
        (page.page_number, table)
        for page in facts.pages
        for table in page.tables
    )
    has_ambiguous_table = any(
        table.missing_cell_positions for _, table in native_tables
    )
    tables = tuple(
        ParseTableV1(
            table_id=table.table_id,
            order_index=index,
            locator=TableLocatorV1(
                page_number=page_number,
                table_index=table.table_index,
                bbox=_decimal_bbox(table.bbox),
            ),
            content_hash=_native_structure_hash(
                "table-content",
                tuple(cell.content_sha256 for cell in table.cells),
            ),
            structure_hash=_native_structure_hash(
                "table-structure",
                {
                    "bbox": table.bbox,
                    "row_count": table.row_count,
                    "column_count": table.column_count,
                    "cell_ids": tuple(cell.cell_id for cell in table.cells),
                    "missing_cell_positions": table.missing_cell_positions,
                },
            ),
            row_count=table.row_count,
            column_count=table.column_count,
            header_cell_ids=(),
            continuation_table_ids=(),
        )
        for index, (page_number, table) in enumerate(native_tables)
    )

    native_cells = tuple(
        (page_number, table.table_id, cell)
        for page_number, table in native_tables
        if not table.missing_cell_positions
        for cell in table.cells
    )
    cells = tuple(
        ParseCellV1(
            cell_id=cell.cell_id,
            order_index=index,
            table_id=table_id,
            locator=CellLocatorV1(
                page_number=page_number,
                table_id=table_id,
                row_index=cell.row_index,
                column_index=cell.column_index,
                row_span=1,
                column_span=1,
                bbox=_decimal_bbox(cell.bbox),
            ),
            content_hash=cell.content_sha256,
            structure_hash=_native_structure_hash(
                "cell-structure",
                {
                    "bbox": cell.bbox,
                    "row_index": cell.row_index,
                    "column_index": cell.column_index,
                },
            ),
        )
        for index, (page_number, table_id, cell) in enumerate(native_cells)
    )

    page_ids = tuple(page.page_id for page in pages)
    table_ids = tuple(table.table_id for table in tables)
    cell_ids = tuple(cell.cell_id for cell in cells)
    evidence: list[CapabilityEvidenceV1] = []
    if "ordered_pages" in facts.supported_capabilities:
        evidence.append(
            CapabilityEvidenceV1(
                capability="ordered_pages",
                subject_refs=page_ids,
            )
        )
    if (
        "table_grid" in facts.supported_capabilities
        and not has_ambiguous_table
        and table_ids
        and cell_ids
    ):
        evidence.append(
            CapabilityEvidenceV1(
                capability="table_grid",
                subject_refs=table_ids + cell_ids,
            )
        )
    for capability in ("cell_locators", "row_column_indices"):
        if capability in facts.supported_capabilities and cell_ids:
            evidence.append(
                CapabilityEvidenceV1(
                    capability=capability,
                    subject_refs=cell_ids,
                )
            )

    evidenced_capabilities = {item.capability for item in evidence}
    unsupported: list[UnsupportedParseFactV1] = []
    if has_ambiguous_table:
        unsupported.append(
            UnsupportedParseFactV1(
                capability="table_grid",
                reason_code="native_table_grid_or_span_ambiguous",
                subject_refs=tuple(
                    table.table_id
                    for _, table in native_tables
                    if table.missing_cell_positions
                ),
            )
        )
    for capability in facts.unsupported_capabilities:
        if capability not in evidenced_capabilities:
            unsupported.append(
                UnsupportedParseFactV1(
                    capability=capability,
                    reason_code="native_pdfplumber_capability_not_proven",
                    subject_refs=page_ids,
                )
            )
    if "word_locators" in facts.supported_capabilities:
        unsupported.append(
            UnsupportedParseFactV1(
                capability="word_locators",
                reason_code="parsed_document_v1_has_no_word_element",
                subject_refs=page_ids,
            )
        )

    document = ParsedDocumentV1(
        contract="parsed-document.v1",
        subject=subject,
        parser=parser,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output_facts,
        pages=pages,
        blocks=(),
        tables=tables,
        cells=cells,
        capability_evidence=tuple(evidence),
        warnings=(
            ParseWarningV1(
                warning_code="native_words_bound_by_page_digest_only",
                subject_refs=page_ids,
            ),
        )
        if "word_locators" in facts.supported_capabilities
        else (),
        unsupported=tuple(unsupported),
    )
    manifest = build_parse_manifest(document, material_profile_resolution.profile)
    decision = evaluate_parse_quality(
        document=document,
        manifest=manifest,
        material_profile_resolution=material_profile_resolution,
    )
    return document, manifest, decision
