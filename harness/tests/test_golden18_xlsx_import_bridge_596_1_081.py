from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import UTC, datetime
from xml.sax.saxutils import escape

from insurance_harness.goldenset import golden_v2_review_intake_596_1 as intake
from insurance_harness.goldenset.golden18_xlsx_import_bridge_596_1 import (
    ReviewRecordAuthorityV1,
    import_golden18_review_workbook,
)
from insurance_harness.goldenset.records import Evidence, GoldenRecord

HEADERS = (
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


def _column_name(index: int) -> str:
    value = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        value = chr(65 + remainder) + value
    return value


def _cell(
    row: int,
    column: int,
    value: str | int | None = None,
    *,
    formula: str | None = None,
) -> str:
    coordinate = f"{_column_name(column)}{row}"
    if formula is not None:
        return f'<c r="{coordinate}" t="str"><f>{escape(formula)}</f><v/></c>'
    if value is None:
        return f'<c r="{coordinate}" t="inlineStr"><is><t></t></is></c>'
    if type(value) is int:
        return f'<c r="{coordinate}" t="n"><v>{value}</v></c>'
    assert isinstance(value, str)
    return f'<c r="{coordinate}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'


def _instruction_sheet() -> str:
    rows = {
        1: _cell(1, 1, "Golden 596-1｜P0/P1 人工复核包（仅供决策，不生成 v2）"),
        4: (
            _cell(4, 1, "authoritative main")
            + _cell(4, 5, formula="COUNTIF('P0业务决策'!$O$5:$O$11,\"待决策\")")
        ),
        5: (
            _cell(5, 1, "只读工作树 HEAD")
            + _cell(5, 5, formula="COUNTIF('P1证据复核'!$O$5:$O$15,\"待决策\")")
        ),
        6: (
            _cell(6, 1, "049 v1 / 596.jsonl SHA-256")
            + _cell(6, 2, intake.V1_GOLDEN_SHA256)
            + _cell(6, 5, formula="E4+E5")
        ),
        7: _cell(7, 1, "产品/版本") + _cell(7, 2, "平安e生保（尊享版）医疗保险 / 单一冻结版本"),
        18: _cell(18, 2, intake.SOURCE_IDENTITIES[0].sha256),
        19: _cell(19, 2, intake.SOURCE_IDENTITIES[1].sha256),
        20: _cell(20, 2, intake.SOURCE_IDENTITIES[2].sha256),
        21: _cell(21, 2, "base.yaml + medical.yaml + extensions-v1.1.yaml"),
    }
    body = "".join(f'<row r="{row}">{cells}</row>' for row, cells in rows.items())
    return _worksheet(body, table_rel=None, validations="")


def _review_sheet(
    fields: tuple[intake.ReviewFieldV1, ...],
    decisions: dict[str, tuple[str | None, str | None, str | None]],
    *,
    table_rel: str,
) -> str:
    header = "".join(_cell(4, index, value) for index, value in enumerate(HEADERS, 1))
    rows = [f'<row r="4">{header}</row>']
    for offset, field in enumerate(fields, 5):
        selection, custom_tri_state, custom_value = decisions.get(
            field.field_id, (None, None, None)
        )
        values: tuple[str | int | None, ...] = (
            field.priority,
            field.field_id,
            field.field_name,
            "present",
            f"current:{field.field_id}",
            "present",
            f"recommended:{field.field_id}",
            "synthetic-primary.pdf",
            1,
            f"evidence:{field.field_id}",
            None,
            selection,
            custom_tri_state,
            custom_value,
        )
        cells = "".join(_cell(offset, index, value) for index, value in enumerate(values, 1))
        cells += _cell(offset, 15, formula=f'IF(L{offset}="","待决策","已填写")')
        rows.append(f'<row r="{offset}">{cells}</row>')
    last_row = 4 + len(fields)
    validations = (
        '<dataValidations count="2">'
        f'<dataValidation type="list" sqref="L5:L{last_row}"><formula1>'
        '"接受推荐,保留当前,自定义,需业务专家,不适用"'
        "</formula1></dataValidation>"
        f'<dataValidation type="list" sqref="M5:M{last_row}"><formula1>'
        '"present,unknown,absent_explicitly,不改 tri-state"'
        "</formula1></dataValidation></dataValidations>"
    )
    return _worksheet("".join(rows), table_rel=table_rel, validations=validations)


def _worksheet(body: str, *, table_rel: str | None, validations: str) -> str:
    table = (
        ""
        if table_rel is None
        else f'<tableParts count="1"><tablePart r:id="{table_rel}"/></tableParts>'
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheetData>{body}</sheetData>{validations}{table}</worksheet>"
    )


def _table_xml(name: str, ref: str) -> str:
    columns = "".join(
        f'<tableColumn id="{index}" name="{escape(value)}"/>'
        for index, value in enumerate(HEADERS, 1)
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<table xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'id="1" name="{name}" displayName="{name}" ref="{ref}" '
        'headerRowCount="1" totalsRowCount="0" totalsRowShown="0">'
        f'<autoFilter ref="{ref}"/><tableColumns count="15">{columns}</tableColumns>'
        "</table>"
    )


def _xlsx_bytes(
    decisions: dict[str, tuple[str | None, str | None, str | None]] | None = None,
) -> bytes:
    choices = {} if decisions is None else decisions
    p0 = tuple(field for field in intake.REVIEW_FIELDS if field.priority == "P0")
    p1 = tuple(field for field in intake.REVIEW_FIELDS if field.priority == "P1")
    members = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="'
            'application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="'
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="审阅说明" sheetId="1" r:id="rId1"/>'
            '<sheet name="P0业务决策" sheetId="2" r:id="rId2"/>'
            '<sheet name="P1证据复核" sheetId="3" r:id="rId3"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet2.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet3.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": _instruction_sheet(),
        "xl/worksheets/sheet2.xml": _review_sheet(p0, choices, table_rel="rId1"),
        "xl/worksheets/sheet3.xml": _review_sheet(p1, choices, table_rel="rId1"),
        "xl/worksheets/_rels/sheet2.xml.rels": (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/table" '
            'Target="../tables/table1.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/_rels/sheet3.xml.rels": (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/table" '
            'Target="../tables/table2.xml"/>'
            "</Relationships>"
        ),
        "xl/tables/table1.xml": _table_xml("P0ReviewTable", "A4:O11"),
        "xl/tables/table2.xml": _table_xml("P1ReviewTable", "A4:O15"),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, text in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 8, 5, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, text.encode("utf-8"))
    return output.getvalue()


def _record(
    field: intake.ReviewFieldV1,
    *,
    value_prefix: str,
    document: str = "synthetic-primary.pdf",
) -> GoldenRecord:
    value = f"{value_prefix}:{field.field_id}"
    return GoldenRecord(
        product_id="596-1",
        product_name="synthetic-596-1",
        doc=document,
        field_id=field.field_id,
        field_name=field.field_name,
        value=value,
        tri_state="present",
        evidence=[Evidence(page=1, quote=f"evidence:{field.field_id}")],
        disputed=False,
        disputed_reason=None,
        reasoning="synthetic 081 authority",
        annotator_model="synthetic-human-review",
        schema_version="596-1.synthetic.v1",
        created_at=datetime(2026, 8, 5, tzinfo=UTC),
    )


def _authority(*, custom_field_id: str | None = None) -> ReviewRecordAuthorityV1:
    current = tuple(_record(field, value_prefix="current") for field in intake.REVIEW_FIELDS)
    recommended = tuple(
        _record(field, value_prefix="recommended") for field in intake.REVIEW_FIELDS
    )
    custom = tuple(
        (_record(field, value_prefix="custom") if field.field_id == custom_field_id else None)
        for field in intake.REVIEW_FIELDS
    )
    return ReviewRecordAuthorityV1(current, recommended, custom)


PROVENANCE = intake.ConversationProvenanceV1(
    source_thread_id="019fa5ea-2507-73a2-acb8-d49030bad2f0",
    conversation_id="019fa5ea-2507-73a2-acb8-d49030bad2f0",
    user_decision_ref="user-message:081-synthetic-complete",
)


def _complete_decisions() -> dict[str, tuple[str | None, str | None, str | None]]:
    result: dict[str, tuple[str | None, str | None, str | None]] = {
        field.field_id: ("保留当前", None, None) for field in intake.REVIEW_FIELDS
    }
    result[intake.REVIEW_FIELDS[0].field_id] = ("接受推荐", None, None)
    custom_field = intake.REVIEW_FIELDS[1]
    result[custom_field.field_id] = (
        "自定义",
        "present",
        f"custom:{custom_field.field_id}",
    )
    return result


def _mutate_member(workbook: bytes, member: str, old: str, new: str) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(workbook))
    members = {name: source.read(name) for name in source.namelist()}
    source.close()
    text = members[member].decode("utf-8")
    assert old in text
    members[member] = text.replace(old, new, 1).encode("utf-8")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 8, 5, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    return output.getvalue()


def test_blank_exact_eighteen_returns_awaiting_without_075_request() -> None:
    workbook = _xlsx_bytes()
    result = import_golden18_review_workbook(
        workbook,
        expected_workbook_sha256=hashlib.sha256(workbook).hexdigest(),
        authority=_authority(),
    )

    assert result.status == "AWAITING_18_HUMAN_DECISIONS"
    assert result.pending_field_ids == tuple(field.field_id for field in intake.REVIEW_FIELDS)
    assert (result.p0_pending, result.p1_pending, result.total_pending) == (7, 11, 18)
    assert result.approved_blank_workbook_sha256 == intake.REVIEW_WORKBOOK_SHA256
    assert result.input_workbook_sha256 != result.approved_blank_workbook_sha256
    assert result.review_request is None


def test_complete_synthetic_workbook_converts_to_public_075_request() -> None:
    decisions = _complete_decisions()
    workbook = _xlsx_bytes(decisions)
    result = import_golden18_review_workbook(
        workbook,
        expected_workbook_sha256=hashlib.sha256(workbook).hexdigest(),
        authority=_authority(custom_field_id=intake.REVIEW_FIELDS[1].field_id),
        provenance=PROVENANCE,
    )

    assert result.status == "READY_FOR_075_REVIEW_INTAKE"
    assert result.intake_status == "READY_FOR_EXTERNAL_APPROVAL"
    assert result.pending_field_ids == ()
    assert result.review_request is not None
    assert result.review_request.workbook_sha256 == intake.REVIEW_WORKBOOK_SHA256
    completed_sha = hashlib.sha256(workbook).hexdigest()
    assert result.input_workbook_sha256 == completed_sha
    assert all(
        f"completed_workbook_sha256={completed_sha}" in decision.reason
        for decision in result.review_request.decisions
    )
    replay = intake.evaluate_review_intake(result.review_request)
    assert replay.status == "READY_FOR_EXTERNAL_APPROVAL"


def test_partial_workbook_never_emits_partial_075_request() -> None:
    decisions: dict[str, tuple[str | None, str | None, str | None]] = {
        intake.REVIEW_FIELDS[0].field_id: ("保留当前", None, None),
    }
    workbook = _xlsx_bytes(decisions)
    result = import_golden18_review_workbook(
        workbook,
        expected_workbook_sha256=hashlib.sha256(workbook).hexdigest(),
        authority=_authority(),
    )

    assert result.status == "AWAITING_18_HUMAN_DECISIONS"
    assert result.total_pending == 17
    assert intake.REVIEW_FIELDS[0].field_id not in result.pending_field_ids
    assert result.review_request is None


def test_hash_drift_fails_before_parsing() -> None:
    workbook = _xlsx_bytes()
    result = import_golden18_review_workbook(
        workbook,
        expected_workbook_sha256="0" * 64,
    )

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("WORKBOOK_SHA256_MISMATCH",)
    assert result.review_request is None


def test_complete_workbook_requires_explicit_record_authority() -> None:
    workbook = _xlsx_bytes(_complete_decisions())
    result = import_golden18_review_workbook(
        workbook,
        expected_workbook_sha256=hashlib.sha256(workbook).hexdigest(),
    )

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("REVIEW_RECORD_AUTHORITY_REQUIRED",)
    assert result.review_request is None


def test_non_template_partial_workbook_requires_record_authority() -> None:
    workbook = _xlsx_bytes()
    result = import_golden18_review_workbook(
        workbook,
        expected_workbook_sha256=hashlib.sha256(workbook).hexdigest(),
    )

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("PARTIAL_WORKBOOK_AUTHORITY_REQUIRED",)
    assert result.review_request is None


def test_record_display_drift_blocks_zero_075_output() -> None:
    workbook = _xlsx_bytes(_complete_decisions())
    authority = _authority(custom_field_id=intake.REVIEW_FIELDS[1].field_id)
    changed = authority.current_records[0].model_copy(update={"value": "foreign"})
    drifted = ReviewRecordAuthorityV1(
        (changed, *authority.current_records[1:]),
        authority.recommended_records,
        authority.custom_records,
    )
    result = import_golden18_review_workbook(
        workbook,
        expected_workbook_sha256=hashlib.sha256(workbook).hexdigest(),
        authority=drifted,
        provenance=PROVENANCE,
    )

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("REVIEW_RECORD_BINDING_INVALID",)
    assert result.review_request is None


def test_foreign_product_or_field_identity_cannot_enter_075() -> None:
    workbook = _xlsx_bytes(_complete_decisions())
    authority = _authority(custom_field_id=intake.REVIEW_FIELDS[1].field_id)
    foreign = authority.recommended_records[0]
    assert foreign is not None
    foreign = foreign.model_copy(update={"product_id": "foreign", "product_name": "foreign"})
    drifted = ReviewRecordAuthorityV1(
        authority.current_records,
        (foreign, *authority.recommended_records[1:]),
        authority.custom_records,
    )
    result = import_golden18_review_workbook(
        workbook,
        expected_workbook_sha256=hashlib.sha256(workbook).hexdigest(),
        authority=drifted,
        provenance=PROVENANCE,
    )

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("REVIEW_RECORD_BINDING_INVALID",)
    assert result.review_request is None


def test_workbook_relationship_and_product_identity_drift_fail_closed() -> None:
    workbook = _xlsx_bytes(_complete_decisions())
    mutations = (
        (
            "xl/_rels/workbook.xml.rels",
            'Target="worksheets/sheet2.xml"',
            'Target="worksheets/sheet3.xml"',
        ),
        (
            "xl/worksheets/sheet1.xml",
            "平安e生保（尊享版）医疗保险 / 单一冻结版本",
            "foreign-product",
        ),
        (
            "xl/worksheets/sheet1.xml",
            intake.SOURCE_IDENTITIES[0].sha256,
            "f" * 64,
        ),
        (
            "xl/worksheets/_rels/sheet2.xml.rels",
            'Target="../tables/table1.xml"',
            'Target="../tables/table2.xml"',
        ),
    )
    for member, old, new in mutations:
        mutated = _mutate_member(workbook, member, old, new)
        result = import_golden18_review_workbook(
            mutated,
            expected_workbook_sha256=hashlib.sha256(mutated).hexdigest(),
            authority=_authority(custom_field_id=intake.REVIEW_FIELDS[1].field_id),
            provenance=PROVENANCE,
        )
        assert result.status == "BLOCKED"
        assert result.review_request is None


def test_duplicate_workbook_relationship_id_fails_closed() -> None:
    workbook = _xlsx_bytes(_complete_decisions())
    marker = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    duplicate = (
        marker + '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/foreign.xml"/>'
    )
    mutated = _mutate_member(
        workbook,
        "xl/_rels/workbook.xml.rels",
        marker,
        duplicate,
    )
    result = import_golden18_review_workbook(
        mutated,
        expected_workbook_sha256=hashlib.sha256(mutated).hexdigest(),
        authority=_authority(custom_field_id=intake.REVIEW_FIELDS[1].field_id),
        provenance=PROVENANCE,
    )

    assert result.status == "BLOCKED"
    assert result.review_request is None


def test_instruction_metadata_only_extra_row_or_column_fails_closed() -> None:
    workbook = _xlsx_bytes(_complete_decisions())
    mutations = (
        ("</sheetData>", '<row r="999"/></sheetData>'),
        ("<sheetData>", '<cols><col min="16" max="16"/></cols><sheetData>'),
    )
    for old, new in mutations:
        mutated = _mutate_member(
            workbook,
            "xl/worksheets/sheet1.xml",
            old,
            new,
        )
        result = import_golden18_review_workbook(
            mutated,
            expected_workbook_sha256=hashlib.sha256(mutated).hexdigest(),
            authority=_authority(custom_field_id=intake.REVIEW_FIELDS[1].field_id),
            provenance=PROVENANCE,
        )
        assert result.status == "BLOCKED"
        assert result.review_request is None


def test_malformed_nested_record_is_typed_blocked_without_exception_leak() -> None:
    workbook = _xlsx_bytes(_complete_decisions())
    authority = _authority(custom_field_id=intake.REVIEW_FIELDS[1].field_id)
    payload = authority.current_records[0].model_dump(mode="python")
    malformed = GoldenRecord.model_construct(**{**payload, "evidence": [object()]})
    drifted = ReviewRecordAuthorityV1(
        (malformed, *authority.current_records[1:]),
        authority.recommended_records,
        authority.custom_records,
    )
    result = import_golden18_review_workbook(
        workbook,
        expected_workbook_sha256=hashlib.sha256(workbook).hexdigest(),
        authority=drifted,
        provenance=PROVENANCE,
    )

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("REVIEW_RECORD_BINDING_INVALID",)
    assert result.review_request is None


def test_illegal_decision_vocabulary_fails_closed() -> None:
    decisions = _complete_decisions()
    decisions[intake.REVIEW_FIELDS[0].field_id] = ("自动批准", None, None)
    workbook = _xlsx_bytes(decisions)
    result = import_golden18_review_workbook(
        workbook,
        expected_workbook_sha256=hashlib.sha256(workbook).hexdigest(),
    )

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("WORKBOOK_CONTRACT_INVALID",)
    assert result.review_request is None


def test_formula_in_human_input_cell_fails_closed() -> None:
    workbook = _xlsx_bytes()
    mutated = _mutate_member(
        workbook,
        "xl/worksheets/sheet2.xml",
        '<c r="L5" t="inlineStr"><is><t></t></is></c>',
        '<c r="L5" t="str"><f>CONCAT("secret")</f><v/></c>',
    )
    result = import_golden18_review_workbook(
        mutated,
        expected_workbook_sha256=hashlib.sha256(mutated).hexdigest(),
    )

    assert result.status == "BLOCKED"
    assert result.review_request is None


def test_excel_error_in_human_input_cell_fails_closed() -> None:
    workbook = _xlsx_bytes()
    mutated = _mutate_member(
        workbook,
        "xl/worksheets/sheet2.xml",
        '<c r="L5" t="inlineStr"><is><t></t></is></c>',
        '<c r="L5" t="e"><v>#VALUE!</v></c>',
    )
    result = import_golden18_review_workbook(
        mutated,
        expected_workbook_sha256=hashlib.sha256(mutated).hexdigest(),
    )

    assert result.status == "BLOCKED"
    assert result.review_request is None


def test_hidden_sheet_row_or_column_fails_closed() -> None:
    workbook = _xlsx_bytes()
    mutations = (
        (
            "xl/workbook.xml",
            '<sheet name="P0业务决策" sheetId="2"',
            '<sheet name="P0业务决策" state="hidden" sheetId="2"',
        ),
        (
            "xl/worksheets/sheet2.xml",
            '<row r="5">',
            '<row r="5" hidden="1">',
        ),
        (
            "xl/worksheets/sheet2.xml",
            "<sheetData>",
            '<cols><col min="12" max="12" hidden="1"/></cols><sheetData>',
        ),
    )
    for member, old, new in mutations:
        mutated = _mutate_member(workbook, member, old, new)
        result = import_golden18_review_workbook(
            mutated,
            expected_workbook_sha256=hashlib.sha256(mutated).hexdigest(),
        )
        assert result.status == "BLOCKED"
        assert result.review_request is None


def test_extra_row_column_and_header_drift_fail_closed() -> None:
    workbook = _xlsx_bytes()
    mutations = (
        (
            "xl/worksheets/sheet2.xml",
            "</sheetData>",
            '<row r="12"><c r="A12" t="inlineStr"><is><t>extra</t></is></c></row></sheetData>',
        ),
        (
            "xl/worksheets/sheet2.xml",
            '<row r="5">',
            '<row r="5"><c r="P5" t="inlineStr"><is><t>extra</t></is></c>',
        ),
        (
            "xl/tables/table1.xml",
            'name="用户决策"',
            'name="自动决策"',
        ),
        (
            "xl/worksheets/sheet2.xml",
            "</sheetData>",
            '<row r="12"/></sheetData>',
        ),
        (
            "xl/worksheets/sheet2.xml",
            "<sheetData>",
            '<cols><col min="16" max="16" width="10"/></cols><sheetData>',
        ),
    )
    for member, old, new in mutations:
        mutated = _mutate_member(workbook, member, old, new)
        result = import_golden18_review_workbook(
            mutated,
            expected_workbook_sha256=hashlib.sha256(mutated).hexdigest(),
        )
        assert result.status == "BLOCKED"
        assert result.review_request is None


def test_field_reorder_and_duplicate_fail_closed() -> None:
    workbook = _xlsx_bytes()
    first = intake.REVIEW_FIELDS[0].field_id
    second = intake.REVIEW_FIELDS[1].field_id
    reordered = _mutate_member(
        workbook,
        "xl/worksheets/sheet2.xml",
        f"<t>{first}</t>",
        f"<t>{second}</t>",
    )
    result = import_golden18_review_workbook(
        reordered,
        expected_workbook_sha256=hashlib.sha256(reordered).hexdigest(),
    )

    assert result.status == "BLOCKED"
    assert result.review_request is None


def test_malformed_workbook_never_exposes_free_text() -> None:
    secret = "must-not-survive"
    workbook = f"not-a-workbook:{secret}".encode()
    result = import_golden18_review_workbook(
        workbook,
        expected_workbook_sha256=hashlib.sha256(workbook).hexdigest(),
    )

    assert result.status == "BLOCKED"
    assert secret not in repr(result)
    assert result.review_request is None
