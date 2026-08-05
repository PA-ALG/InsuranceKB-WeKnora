"""Fixed-format, offline XLSX bridge for the 596-1 Golden18 review package."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from typing import Final, Literal
from xml.etree import ElementTree

from pydantic import ValidationError

from . import golden_v2_review_intake_596_1 as intake
from .records import GoldenRecord

_MAIN_NS: Final[str] = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS: Final[str] = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS: Final[str] = "http://schemas.openxmlformats.org/package/2006/relationships"
_WORKSHEET_REL_TYPE: Final[str] = f"{_REL_NS}/worksheet"
_TABLE_REL_TYPE: Final[str] = f"{_REL_NS}/table"
_NS: Final[dict[str, str]] = {"m": _MAIN_NS}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHEET_NAMES: Final[tuple[str, ...]] = ("审阅说明", "P0业务决策", "P1证据复核")
_HEADERS: Final[tuple[str, ...]] = (
    "优先级",
    "field_id",
    "字段名",
    "当前 tri-state",
    "当前值",
    "推荐 tri-state",
    "推荐修订",
    "主权威 PDF",
    "页码",
    "逐字 Evidence",
    "冲突/不适用说明",
    "用户决策",
    "自定义 tri-state",
    "用户只需确认/自定义说明",
    "审阅状态",
)
_SELECTIONS: Final[dict[str, intake.ReviewSelection]] = {
    "接受推荐": "accept_recommendation",
    "保留当前": "keep_current",
    "自定义": "custom",
    "需业务专家": "needs_expert",
    "不适用": "not_applicable",
}
_CUSTOM_TRI_STATES: Final[frozenset[str]] = frozenset(
    {"present", "unknown", "absent_explicitly", "不改 tri-state"}
)
_DECISION_VALIDATION: Final[str] = '"接受推荐,保留当前,自定义,需业务专家,不适用"'
_CUSTOM_VALIDATION: Final[str] = '"present,unknown,absent_explicitly,不改 tri-state"'

BridgeStatus = Literal[
    "AWAITING_18_HUMAN_DECISIONS",
    "PENDING_075_BUSINESS_RESOLUTION",
    "READY_FOR_075_REVIEW_INTAKE",
    "BLOCKED",
]


@dataclass(frozen=True, slots=True)
class ReviewRecordAuthorityV1:
    """Caller-owned replayable records; the bridge never invents record authority."""

    current_records: tuple[GoldenRecord, ...]
    recommended_records: tuple[GoldenRecord | None, ...]
    custom_records: tuple[GoldenRecord | None, ...]


@dataclass(frozen=True, slots=True)
class Golden18XlsxImportResultV1:
    status: BridgeStatus
    reason_codes: tuple[str, ...]
    approved_blank_workbook_sha256: str
    input_workbook_sha256: str | None
    pending_field_ids: tuple[str, ...]
    p0_pending: int
    p1_pending: int
    total_pending: int
    review_request: intake.ReviewIntakeRequestV1 | None = None
    review_request_sha256: str | None = None
    decisions_sha256: str | None = None
    intake_status: intake.IntakeStatus | None = None


@dataclass(frozen=True, slots=True)
class _Cell:
    value: str | None
    formula: str | None
    cell_type: str | None


def _result(
    status: BridgeStatus,
    *reasons: str,
    completed_sha256: str | None = None,
    pending: tuple[str, ...] = (),
    request: intake.ReviewIntakeRequestV1 | None = None,
    intake_status: intake.IntakeStatus | None = None,
) -> Golden18XlsxImportResultV1:
    p0_ids = {field.field_id for field in intake.REVIEW_FIELDS if field.priority == "P0"}
    p0 = sum(field_id in p0_ids for field_id in pending)
    request_sha = intake.review_request_sha256(request) if request is not None else None
    return Golden18XlsxImportResultV1(
        status=status,
        reason_codes=tuple(reasons),
        approved_blank_workbook_sha256=intake.REVIEW_WORKBOOK_SHA256,
        input_workbook_sha256=completed_sha256,
        pending_field_ids=pending,
        p0_pending=p0,
        p1_pending=len(pending) - p0,
        total_pending=len(pending),
        review_request=request,
        review_request_sha256=request_sha,
        decisions_sha256=(request.decisions_sha256 if request is not None else None),
        intake_status=intake_status,
    )


def _column_number(reference: str) -> int:
    letters = "".join(character for character in reference if character.isalpha())
    value = 0
    for character in letters:
        value = value * 26 + ord(character.upper()) - 64
    return value


def _shared_strings(archive: zipfile.ZipFile) -> tuple[str, ...]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return ()
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return tuple(
        "".join(text.text or "" for text in item.findall(".//m:t", _NS))
        for item in root.findall("m:si", _NS)
    )


def _cells(root: ElementTree.Element, shared: tuple[str, ...]) -> dict[str, _Cell]:
    cells: dict[str, _Cell] = {}
    for cell in root.findall(".//m:sheetData/m:row/m:c", _NS):
        reference = cell.attrib.get("r", "")
        if not reference or reference in cells:
            raise ValueError("duplicate cell")
        cell_type = cell.attrib.get("t")
        formula_node = cell.find("m:f", _NS)
        formula = formula_node.text or "" if formula_node is not None else None
        value: str | None
        if cell_type == "inlineStr":
            value = "".join(text.text or "" for text in cell.findall(".//m:is/m:t", _NS))
        else:
            raw = cell.findtext("m:v", default=None, namespaces=_NS)
            if cell_type == "s" and raw is not None:
                index = int(raw)
                if index < 0 or index >= len(shared):
                    raise ValueError("shared string index")
                value = shared[index]
            else:
                value = raw
        cells[reference] = _Cell(value=value, formula=formula, cell_type=cell_type)
    return cells


def _assert_no_hidden(root: ElementTree.Element) -> None:
    for row in root.findall(".//m:sheetData/m:row", _NS):
        if row.attrib.get("hidden") in {"1", "true"}:
            raise ValueError("hidden row")
    for column in root.findall(".//m:cols/m:col", _NS):
        if column.attrib.get("hidden") in {"1", "true"}:
            raise ValueError("hidden column")


def _assert_review_extent(root: ElementTree.Element, *, last_row: int) -> None:
    for row in root.findall(".//m:sheetData/m:row", _NS):
        row_number = int(row.attrib.get("r", "0"))
        if row_number < 1 or row_number > last_row:
            raise ValueError("extra row")
    for column in root.findall(".//m:cols/m:col", _NS):
        minimum = int(column.attrib.get("min", "0"))
        maximum = int(column.attrib.get("max", "0"))
        if minimum < 1 or maximum < minimum or maximum > 15:
            raise ValueError("extra column")


def _assert_instruction_extent(root: ElementTree.Element) -> None:
    for row in root.findall(".//m:sheetData/m:row", _NS):
        row_number = int(row.attrib.get("r", "0"))
        if row_number < 1 or row_number > 27:
            raise ValueError("extra instruction row")
    for column in root.findall(".//m:cols/m:col", _NS):
        minimum = int(column.attrib.get("min", "0"))
        maximum = int(column.attrib.get("max", "0"))
        if minimum < 1 or maximum < minimum or maximum > 8:
            raise ValueError("extra instruction column")
    for cell in root.findall(".//m:sheetData/m:row/m:c", _NS):
        if _column_number(cell.attrib.get("r", "")) > 8:
            raise ValueError("extra instruction cell")


def _assert_formulas(cells: dict[str, _Cell], expected: dict[str, str]) -> None:
    actual = {
        reference: cell.formula for reference, cell in cells.items() if cell.formula is not None
    }
    if actual != expected:
        raise ValueError("formula drift")
    if any(cell.cell_type == "e" for cell in cells.values()):
        raise ValueError("excel error")


def _validation_rows(
    root: ElementTree.Element,
) -> tuple[tuple[str | None, str | None, str | None], ...]:
    values: list[tuple[str | None, str | None, str | None]] = []
    for item in root.findall(".//m:dataValidations/m:dataValidation", _NS):
        values.append(
            (
                item.attrib.get("type"),
                item.attrib.get("sqref"),
                item.findtext("m:formula1", default=None, namespaces=_NS),
            )
        )
    return tuple(values)


def _assert_table(
    archive: zipfile.ZipFile,
    *,
    path: str,
    name: str,
    reference: str,
) -> None:
    root = ElementTree.fromstring(archive.read(path))
    columns = tuple(
        column.attrib.get("name") for column in root.findall(".//m:tableColumns/m:tableColumn", _NS)
    )
    if (
        root.attrib.get("name") != name
        or root.attrib.get("displayName") != name
        or root.attrib.get("ref") != reference
        or columns != _HEADERS
    ):
        raise ValueError("table drift")


def _assert_table_link(
    archive: zipfile.ZipFile,
    root: ElementTree.Element,
    *,
    rels_path: str,
    target: str,
) -> None:
    table_parts = root.findall(".//m:tableParts/m:tablePart", _NS)
    if len(table_parts) != 1:
        raise ValueError("table link drift")
    relationship_id = table_parts[0].attrib.get(f"{{{_REL_NS}}}id")
    if not relationship_id:
        raise ValueError("table link drift")
    relationships = ElementTree.fromstring(archive.read(rels_path))
    matches = [
        item
        for item in relationships.findall(f"{{{_PKG_REL_NS}}}Relationship")
        if item.attrib.get("Id") == relationship_id
    ]
    actual_target = matches[0].attrib.get("Target", "") if matches else ""
    normalized_target = actual_target.removeprefix("/xl/").removeprefix("../")
    if (
        len(matches) != 1
        or matches[0].attrib.get("Type") != _TABLE_REL_TYPE
        or matches[0].attrib.get("TargetMode") is not None
        or normalized_target != target.removeprefix("../")
    ):
        raise ValueError("table relationship drift")


def _assert_workbook_links(
    archive: zipfile.ZipFile,
    sheets: list[ElementTree.Element],
) -> None:
    expected_targets = (
        "worksheets/sheet1.xml",
        "worksheets/sheet2.xml",
        "worksheets/sheet3.xml",
    )
    actual_ids = tuple(sheet.attrib.get(f"{{{_REL_NS}}}id") for sheet in sheets)
    if any(not relationship_id for relationship_id in actual_ids) or len(set(actual_ids)) != len(
        actual_ids
    ):
        raise ValueError("worksheet relationship id drift")
    relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relationship_items = relationships.findall(f"{{{_PKG_REL_NS}}}Relationship")
    relationship_ids = tuple(item.attrib.get("Id") for item in relationship_items)
    if any(not value for value in relationship_ids) or len(set(relationship_ids)) != len(
        relationship_ids
    ):
        raise ValueError("duplicate workbook relationship")
    by_id = {item.attrib.get("Id"): item for item in relationship_items}
    for relationship_id, target in zip(actual_ids, expected_targets, strict=True):
        item = by_id.get(relationship_id)
        if (
            item is None
            or item.attrib.get("Type") != _WORKSHEET_REL_TYPE
            or item.attrib.get("Target", "").removeprefix("/xl/") != target
            or item.attrib.get("TargetMode") is not None
        ):
            raise ValueError("worksheet relationship drift")


def _review_rows(
    archive: zipfile.ZipFile,
    *,
    sheet_path: str,
    table_path: str,
    table_rels_path: str,
    table_target: str,
    table_name: str,
    fields: tuple[intake.ReviewFieldV1, ...],
    shared: tuple[str, ...],
) -> tuple[tuple[str | None, str | None, str | None], ...]:
    root = ElementTree.fromstring(archive.read(sheet_path))
    _assert_no_hidden(root)
    _assert_table_link(
        archive,
        root,
        rels_path=table_rels_path,
        target=table_target,
    )
    last_row = 4 + len(fields)
    _assert_review_extent(root, last_row=last_row)
    cells = _cells(root, shared)
    for reference in cells:
        row = int("".join(character for character in reference if character.isdigit()))
        if row > last_row or _column_number(reference) > 15:
            raise ValueError("extra row or column")
    _assert_formulas(
        cells,
        {f"O{row}": f'IF(L{row}="","待决策","已填写")' for row in range(5, last_row + 1)},
    )
    headers = tuple(cells[f"{chr(64 + column)}4"].value for column in range(1, 16))
    if headers != _HEADERS:
        raise ValueError("header drift")
    expected_validations = (
        ("list", f"L5:L{last_row}", _DECISION_VALIDATION),
        ("list", f"M5:M{last_row}", _CUSTOM_VALIDATION),
    )
    if _validation_rows(root) != expected_validations:
        raise ValueError("validation drift")
    reference = f"A4:O{last_row}"
    _assert_table(archive, path=table_path, name=table_name, reference=reference)

    decisions: list[tuple[str | None, str | None, str | None]] = []
    for row, expected in enumerate(fields, 5):
        if (
            cells[f"A{row}"].value != expected.priority
            or cells[f"B{row}"].value != expected.field_id
            or cells[f"C{row}"].value != expected.field_name
        ):
            raise ValueError("field order drift")
        for column in ("L", "M", "N"):
            cell = cells.get(f"{column}{row}", _Cell(None, None, None))
            if cell.formula is not None or cell.cell_type == "e":
                raise ValueError("input formula or error")
        selection = cells.get(f"L{row}", _Cell(None, None, None)).value or None
        custom_tri_state = cells.get(f"M{row}", _Cell(None, None, None)).value or None
        custom_value = cells.get(f"N{row}", _Cell(None, None, None)).value or None
        if selection is not None and selection not in _SELECTIONS:
            raise ValueError("decision vocabulary")
        if custom_tri_state is not None and custom_tri_state not in _CUSTOM_TRI_STATES:
            raise ValueError("custom tri-state vocabulary")
        if selection is None and custom_tri_state is not None:
            raise ValueError("orphan custom input")
        decisions.append((selection, custom_tri_state, custom_value))
    return tuple(decisions)


def _parse_workbook(
    workbook_bytes: bytes,
) -> tuple[tuple[tuple[str | None, str | None, str | None], ...], ...]:
    with zipfile.ZipFile(io.BytesIO(workbook_bytes)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any(
            "vba" in name.lower() or name.startswith("xl/externalLinks/") for name in names
        ):
            raise ValueError("unsafe package")
        required = {
            "xl/workbook.xml",
            "xl/_rels/workbook.xml.rels",
            "xl/worksheets/sheet1.xml",
            "xl/worksheets/sheet2.xml",
            "xl/worksheets/sheet3.xml",
            "xl/tables/table1.xml",
            "xl/tables/table2.xml",
        }
        if not required.issubset(names):
            raise ValueError("missing package member")
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        sheets = workbook.findall(".//m:sheets/m:sheet", _NS)
        if tuple(sheet.attrib.get("name") for sheet in sheets) != _SHEET_NAMES or any(
            sheet.attrib.get("state", "visible") != "visible" for sheet in sheets
        ):
            raise ValueError("sheet drift")
        _assert_workbook_links(archive, sheets)
        shared = _shared_strings(archive)
        instructions = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        _assert_no_hidden(instructions)
        _assert_instruction_extent(instructions)
        instruction_cells = _cells(instructions, shared)
        _assert_formulas(
            instruction_cells,
            {
                "E4": "COUNTIF('P0业务决策'!$O$5:$O$11,\"待决策\")",
                "E5": "COUNTIF('P1证据复核'!$O$5:$O$15,\"待决策\")",
                "E6": "E4+E5",
            },
        )
        instruction_expectations = {
            "A1": "Golden 596-1｜P0/P1 人工复核包（仅供决策，不生成 v2）",
            "B6": intake.V1_GOLDEN_SHA256,
            "B7": "平安e生保（尊享版）医疗保险 / 单一冻结版本",
            "B18": intake.SOURCE_IDENTITIES[0].sha256,
            "B19": intake.SOURCE_IDENTITIES[1].sha256,
            "B20": intake.SOURCE_IDENTITIES[2].sha256,
            "B21": "base.yaml + medical.yaml + extensions-v1.1.yaml",
        }
        if any(
            instruction_cells.get(reference, _Cell(None, None, None)).value != value
            for reference, value in instruction_expectations.items()
        ):
            raise ValueError("golden identity drift")
        fields = intake.REVIEW_FIELDS
        p0 = tuple(field for field in fields if field.priority == "P0")
        p1 = tuple(field for field in fields if field.priority == "P1")
        return (
            _review_rows(
                archive,
                sheet_path="xl/worksheets/sheet2.xml",
                table_path="xl/tables/table1.xml",
                table_rels_path="xl/worksheets/_rels/sheet2.xml.rels",
                table_target="../tables/table1.xml",
                table_name="P0ReviewTable",
                fields=p0,
                shared=shared,
            ),
            _review_rows(
                archive,
                sheet_path="xl/worksheets/sheet3.xml",
                table_path="xl/tables/table2.xml",
                table_rels_path="xl/worksheets/_rels/sheet3.xml.rels",
                table_target="../tables/table2.xml",
                table_name="P1ReviewTable",
                fields=p1,
                shared=shared,
            ),
        )


def _cell_text(cells: dict[str, _Cell], reference: str) -> str | None:
    value = cells.get(reference, _Cell(None, None, None)).value
    return value if value not in {None, ""} else None


def _assert_record_identity(
    record: object,
    field: intake.ReviewFieldV1,
    *,
    current: GoldenRecord | None = None,
) -> GoldenRecord:
    if type(record) is not GoldenRecord:
        raise ValueError("record type")
    try:
        payload = {name: getattr(record, name) for name in GoldenRecord.model_fields}
        validated = GoldenRecord.model_validate(payload, strict=True)
    except (AttributeError, TypeError, ValidationError):
        raise ValueError("record validation") from None
    if (
        validated.product_id != "596-1"
        or not validated.product_name.strip()
        or validated.field_id != field.field_id
        or validated.field_name != field.field_name
        or not validated.doc.strip()
        or not validated.schema_version.strip()
    ):
        raise ValueError("record identity")
    if current is not None and (
        validated.product_name != current.product_name
        or validated.schema_version != current.schema_version
    ):
        raise ValueError("record scope drift")
    if validated.tri_state == "unknown":
        if validated.value is not None or validated.evidence:
            raise ValueError("unknown record semantics")
    elif validated.tri_state == "present":
        if (
            type(validated.value) is not str
            or not validated.value.strip()
            or not validated.evidence
        ):
            raise ValueError("present record semantics")
    elif validated.value is not None or not validated.evidence:
        raise ValueError("absent record semantics")
    if any(evidence.page <= 0 or not evidence.quote.strip() for evidence in validated.evidence):
        raise ValueError("record evidence")
    return validated


def _authority_decisions(
    workbook_bytes: bytes,
    *,
    workbook_sha256: str,
    authority: ReviewRecordAuthorityV1,
    provenance: intake.ConversationProvenanceV1 | None,
    allow_incomplete: bool = False,
) -> tuple[intake.ReviewDecisionV1, ...]:
    if type(authority) is not ReviewRecordAuthorityV1:
        raise ValueError("authority type")
    if not all(
        type(values) is tuple and len(values) == len(intake.REVIEW_FIELDS)
        for values in (
            authority.current_records,
            authority.recommended_records,
            authority.custom_records,
        )
    ):
        raise ValueError("authority cardinality")
    with zipfile.ZipFile(io.BytesIO(workbook_bytes)) as archive:
        shared = _shared_strings(archive)
        roots = {
            "P0": _cells(ElementTree.fromstring(archive.read("xl/worksheets/sheet2.xml")), shared),
            "P1": _cells(ElementTree.fromstring(archive.read("xl/worksheets/sheet3.xml")), shared),
        }
    rows: list[intake.ReviewDecisionV1] = []
    for index, field in enumerate(intake.REVIEW_FIELDS):
        row = field.slot + 4
        cells = roots[field.priority]
        current = _assert_record_identity(authority.current_records[index], field)
        recommended = authority.recommended_records[index]
        custom = authority.custom_records[index]
        if current.tri_state != _cell_text(cells, f"D{row}") or current.value != _cell_text(
            cells, f"E{row}"
        ):
            raise ValueError("current display drift")
        displayed_recommended_tri = _cell_text(cells, f"F{row}")
        displayed_recommended_value = _cell_text(cells, f"G{row}")
        displayed_doc = _cell_text(cells, f"H{row}")
        displayed_page = _cell_text(cells, f"I{row}")
        displayed_quote = _cell_text(cells, f"J{row}")
        if recommended is None:
            if any(
                value is not None
                for value in (
                    displayed_recommended_tri,
                    displayed_recommended_value,
                    displayed_doc,
                    displayed_page,
                    displayed_quote,
                )
            ):
                raise ValueError("recommendation authority missing")
        else:
            recommended = _assert_record_identity(recommended, field, current=current)
            evidence = recommended.evidence
            if (
                recommended.tri_state != displayed_recommended_tri
                or recommended.value != displayed_recommended_value
                or recommended.doc != displayed_doc
                or len(evidence) != 1
                or str(evidence[0].page) != displayed_page
                or evidence[0].quote != displayed_quote
            ):
                raise ValueError("recommendation display drift")
        selection_text = _cell_text(cells, f"L{row}")
        if selection_text is None:
            if allow_incomplete:
                if custom is not None:
                    raise ValueError("orphan custom authority")
                continue
            raise ValueError("decision missing")
        selection = _SELECTIONS[selection_text]
        custom_tri_state = _cell_text(cells, f"M{row}")
        custom_value = _cell_text(cells, f"N{row}")
        if selection == "custom":
            custom = _assert_record_identity(custom, field, current=current)
            if custom_tri_state == "不改 tri-state":
                custom_tri_state = current.tri_state
            custom_value_matches = (
                custom.value == custom_value
                if custom.tri_state == "present"
                else custom.value is None
            )
            if custom.tri_state != custom_tri_state or not custom_value_matches:
                raise ValueError("custom display drift")
        elif custom is not None or custom_tri_state not in {None, "不改 tri-state"}:
            raise ValueError("unexpected custom authority")
        note_sha = hashlib.sha256((custom_value or "").encode("utf-8")).hexdigest()
        reason = (
            "Imported explicit decision from exact completed workbook; "
            f"completed_workbook_sha256={workbook_sha256}; note_sha256={note_sha}"
        )
        rows.append(
            intake.ReviewDecisionV1(
                field_id=field.field_id,
                priority=field.priority,
                selection=selection,
                current_record_sha256=intake.golden_record_sha256(current),
                recommended_record=recommended,
                recommended_record_sha256=(
                    intake.golden_record_sha256(recommended) if recommended is not None else None
                ),
                custom_record=custom,
                custom_record_sha256=(
                    intake.golden_record_sha256(custom) if custom is not None else None
                ),
                reason=reason,
                provenance=intake.DecisionProvenanceV1(
                    workbook_sha256=intake.REVIEW_WORKBOOK_SHA256,
                    worksheet=field.priority,
                    row=row,
                    decision_cell=f"L{row}",
                ),
            )
        )
    if not allow_incomplete and type(provenance) is not intake.ConversationProvenanceV1:
        raise ValueError("conversation provenance")
    return tuple(rows)


def import_golden18_review_workbook(
    workbook_bytes: bytes,
    *,
    expected_workbook_sha256: str,
    authority: ReviewRecordAuthorityV1 | None = None,
    provenance: intake.ConversationProvenanceV1 | None = None,
) -> Golden18XlsxImportResultV1:
    """Import one exact fixed-layout workbook without logging or external effects."""

    if type(workbook_bytes) is not bytes or type(expected_workbook_sha256) is not str:
        return _result("BLOCKED", "WORKBOOK_INPUT_MALFORMED")
    actual_sha256 = hashlib.sha256(workbook_bytes).hexdigest()
    if (
        _SHA256.fullmatch(expected_workbook_sha256) is None
        or actual_sha256 != expected_workbook_sha256
    ):
        return _result("BLOCKED", "WORKBOOK_SHA256_MISMATCH", completed_sha256=actual_sha256)
    try:
        p0, p1 = _parse_workbook(workbook_bytes)
    except (KeyError, OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError):
        return _result("BLOCKED", "WORKBOOK_CONTRACT_INVALID", completed_sha256=actual_sha256)
    selections = p0 + p1
    pending = tuple(
        field.field_id
        for field, (selection, _, _) in zip(intake.REVIEW_FIELDS, selections, strict=True)
        if selection is None
    )
    if pending:
        if actual_sha256 != intake.REVIEW_WORKBOOK_SHA256:
            if authority is None:
                return _result(
                    "BLOCKED",
                    "PARTIAL_WORKBOOK_AUTHORITY_REQUIRED",
                    completed_sha256=actual_sha256,
                )
            try:
                _authority_decisions(
                    workbook_bytes,
                    workbook_sha256=actual_sha256,
                    authority=authority,
                    provenance=None,
                    allow_incomplete=True,
                )
            except (TypeError, ValueError):
                return _result(
                    "BLOCKED",
                    "REVIEW_RECORD_BINDING_INVALID",
                    completed_sha256=actual_sha256,
                )
        return _result(
            "AWAITING_18_HUMAN_DECISIONS",
            completed_sha256=actual_sha256,
            pending=pending,
        )
    if authority is None or provenance is None:
        return _result(
            "BLOCKED", "REVIEW_RECORD_AUTHORITY_REQUIRED", completed_sha256=actual_sha256
        )
    try:
        decisions = _authority_decisions(
            workbook_bytes,
            workbook_sha256=actual_sha256,
            authority=authority,
            provenance=provenance,
        )
        request = intake.ReviewIntakeRequestV1(
            v1_golden_sha256=intake.V1_GOLDEN_SHA256,
            workbook_sha256=intake.REVIEW_WORKBOOK_SHA256,
            sources=intake.SOURCE_IDENTITIES,
            decisions=decisions,
            decisions_sha256=intake.review_decisions_sha256(decisions),
            provenance=provenance,
        )
        replay = intake.evaluate_review_intake(request)
    except (TypeError, ValueError):
        return _result("BLOCKED", "REVIEW_RECORD_BINDING_INVALID", completed_sha256=actual_sha256)
    if replay.status == "BLOCKED":
        return _result("BLOCKED", *replay.reason_codes, completed_sha256=actual_sha256)
    bridge_status: BridgeStatus = (
        "PENDING_075_BUSINESS_RESOLUTION"
        if replay.status == "PENDING"
        else "READY_FOR_075_REVIEW_INTAKE"
    )
    return _result(
        bridge_status,
        completed_sha256=actual_sha256,
        request=request,
        intake_status=replay.status,
    )


__all__ = [
    "Golden18XlsxImportResultV1",
    "ReviewRecordAuthorityV1",
    "import_golden18_review_workbook",
]
