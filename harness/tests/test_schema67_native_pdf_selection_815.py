"""EC-01 native-PDF Schema67 execution and selection contracts."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
from collections.abc import Callable
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
from typing import Final, cast

import pytest

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler import evidence_verifier
from insurance_harness.compiler import native_pdfplumber as native
from insurance_harness.compiler.extraction_receipts import build_initial_attempt
from insurance_harness.compiler.extraction_tasks import MaterialRole, build_extraction_task
from insurance_harness.compiler.parsed_documents import (
    BlockLocatorV1,
    CapabilityEvidenceV1,
    CellLocatorV1,
    ParseBlockV1,
    ParseCellV1,
    ParsedDocumentV1,
    ParseElementCountsV1,
    ParseManifestV1,
    ParseQualityDecisionV1,
    ParseTableV1,
    TableLocatorV1,
)
from insurance_harness.knowledge_compiler import (
    deepseek_locator_extractor_596_1 as deepseek,
)
from insurance_harness.knowledge_compiler import (
    schema67_native_pdf_selection_815 as native_selection,
)
from insurance_harness.knowledge_compiler.deepseek_locator_extractor_596_1 import (
    DeepSeekCompilerError,
    Schema67ExecutionPlanV1,
    Schema67TaskSliceV1,
    build_schema67_native_pdf_execution_projection_815,
    prepare_schema67_deepseek_tasks,
)
from insurance_harness.knowledge_compiler.schema67_native_pdf_selection_815 import (
    CoordinateEvidenceCompanion815V1,
    NativePdfSelectionError815,
    Schema67SelectionCatalog815V1,
    build_field_selection_catalogs_815,
    hydrate_model_selection_response_815,
    make_coordinate_evidence_companion_815,
    require_model_selection_response_815,
)
from insurance_harness.knowledge_compiler.schema_first_contracts import (
    APPROVED_ORDERED_FIELD_IDS,
)
from insurance_harness.knowledge_compiler.vertical_falsification import (
    AdmittedParseArtifactV1,
)
from tests import test_deepseek_locator_extractor_119 as fixtures

_FROZEN_TERMS_PDF_SHA256_815: Final[str] = (
    "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"
)
_FROZEN_TERMS_SOURCE_REVISION_ID_815: Final[str] = (
    "ea7160149d2fd99ea4a4960c50bfa6ca3641e4532956671b9956f4f8b57ad681"
)


def _rehash_plan(plan: Schema67ExecutionPlanV1) -> Schema67ExecutionPlanV1:
    payload = {
        "contract_set_sha256": plan.contract_set_sha256,
        "task_slices": tuple(item.model_dump(mode="python") for item in plan.task_slices),
        "deferred_unknown_field_ids": plan.deferred_unknown_field_ids,
        "batch_budget": plan.batch_budget.model_dump(mode="python"),
    }
    return plan.model_copy(
        update={
            "execution_plan_sha256": canonical_hash(
                "schema67-deepseek-execution-plan.v2", payload
            )
        }
    )


def _rehash_slice(task_slice: Schema67TaskSliceV1) -> Schema67TaskSliceV1:
    payload = task_slice.model_dump(mode="python", exclude={"task_slice_sha256"})
    return task_slice.model_copy(
        update={
            "task_slice_sha256": canonical_hash(
                "schema67-deepseek-task-slice.v1", payload
            )
        }
    )


def test_815_source_extract_plan_is_exact_schema_intersection() -> None:
    contracts = fixtures._schema67_contract_set()
    base_plan = fixtures._execution_plan(contracts)

    projection = build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=base_plan,
        available_source_roles=("terms", "brochure", "rate_table"),
    )

    by_id = {item.field_id: item for item in contracts.contracts}
    assert projection.provider_visible_field_count == 25
    assert projection.code_deferred_field_count == 42
    assert projection.dispositioned_field_count == 67
    assert len(projection.execution_plan.task_slices) == 8
    assert all(item.field_ids for item in projection.execution_plan.task_slices)
    assert projection.execution_plan.task_slices[-1].material_roles == (
        "terms",
        "brochure",
    )
    assert set(projection.provider_visible_field_ids).isdisjoint(
        projection.code_deferred_field_ids
    )
    assert set(projection.provider_visible_field_ids) | set(
        projection.code_deferred_field_ids
    ) == set(APPROVED_ORDERED_FIELD_IDS)
    assert all(
        by_id[field_id].formation_modes == ("source_extract",)
        for field_id in projection.provider_visible_field_ids
    )
    assert tuple(item.field_id for item in projection.code_deferred) == tuple(
        field_id
        for field_id in APPROVED_ORDERED_FIELD_IDS
        if field_id not in projection.provider_visible_field_ids
    )
    assert all(
        item.reason
        == (
            "FORMATION_MODE_DEFERRED"
            if by_id[item.field_id].formation_modes != ("source_extract",)
            else "SOURCE_NOT_AVAILABLE"
        )
        for item in projection.code_deferred
    )
    assert projection.projection_sha256 == projection.recomputed_projection_sha256()


@pytest.mark.parametrize(
    "formation_modes",
    [
        ("rule_derive",),
        ("llm_generate",),
        ("external_map",),
        ("source_extract", "rule_derive"),
        ("source_extract", "llm_generate"),
        ("source_extract", "external_map"),
    ],
)
def test_815_non_pure_source_fields_are_code_deferred(
    formation_modes: tuple[str, ...],
) -> None:
    contract = fixtures._schema67_contract_set().contracts[0]
    policy_probe = contract.model_copy(update={"formation_modes": formation_modes})

    assert deepseek._native_pdf_field_disposition_815(
        policy_probe,
        available_source_roles=frozenset({"terms", "brochure", "rate_table"}),
    ) == "FORMATION_MODE_DEFERRED"


def test_815_pure_source_field_without_available_source_is_deferred() -> None:
    contract = next(
        item
        for item in fixtures._schema67_contract_set().contracts
        if item.formation_modes == ("source_extract",)
        and "terms" in item.source_roles
    )

    assert deepseek._native_pdf_field_disposition_815(
        contract,
        available_source_roles=frozenset(),
    ) == "SOURCE_NOT_AVAILABLE"


def test_815_prepare_accepts_only_exact_native_pdf_projected_plan() -> None:
    contracts = fixtures._schema67_contract_set()
    base = fixtures._execution_plan(contracts)
    projection = build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=base,
        available_source_roles=("terms", "brochure", "rate_table"),
    )

    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=projection.execution_plan,
        role_inputs=fixtures._schema67_role_inputs(
            contracts, projection.execution_plan
        ),
    )
    assert tuple(field.field_id for task in prepared for field in task.field_prompts) == tuple(
        field_id
        for task in projection.execution_plan.task_slices
        for field_id in task.field_ids
    )

    first_visible = projection.execution_plan.task_slices[0].field_ids[0]
    moved = projection.execution_plan.model_copy(
        update={
            "task_slices": (
                _rehash_slice(
                    projection.execution_plan.task_slices[0].model_copy(
                    update={
                        "field_ids": projection.execution_plan.task_slices[0].field_ids[1:]
                    }
                    )
                ),
                *projection.execution_plan.task_slices[1:],
            ),
            "deferred_unknown_field_ids": (
                first_visible,
                *projection.execution_plan.deferred_unknown_field_ids,
            ),
        }
    )
    moved = _rehash_plan(moved)
    with pytest.raises(DeepSeekCompilerError) as caught:
        prepare_schema67_deepseek_tasks(
            field_contracts=contracts,
            execution_plan=moved,
            role_inputs=fixtures._schema67_role_inputs(contracts, moved),
        )
    assert caught.value.reason_code == "SCHEMA67_FIELD_PARTITION_INVALID"


def _source_projection(
    *,
    role: MaterialRole,
    lines: tuple[str, ...] = (),
    bbox_shift: int = 0,
    line_bboxes: tuple[native.NativeBBox, ...] | None = None,
    line_page_numbers: tuple[int, ...] | None = None,
    canonical_gap_after_line: tuple[int, str] | None = None,
    table_parts: tuple[str, ...] = (),
    table_bbox_top: int = 200,
    parent_block_ids: tuple[str, ...] | None = None,
    source_revision_id: str | None = None,
    original_file_sha256: str | None = None,
) -> native.NativePdfSelectionProjection815V1:
    if line_bboxes is not None:
        assert len(line_bboxes) == len(lines)
    if line_page_numbers is not None:
        assert len(line_page_numbers) == len(lines)
    if canonical_gap_after_line is not None:
        assert 0 <= canonical_gap_after_line[0] < len(lines)
    page_numbers = line_page_numbers or (1,) * len(lines)
    page_order = tuple(dict.fromkeys(page_numbers)) or (1,)

    cells: tuple[native.NativeTableCell815V1, ...] = ()
    table_slices: tuple[native.NativeTableSlice815V1, ...] = ()
    if table_parts:
        cells = tuple(
            native.NativeTableCell815V1(
                cell_id=f"cell-{role}-{index}",
                table_id=f"table-{role}",
                page_number=1,
                row_index=index // 2,
                column_index=index % 2,
                exact_text=text,
                text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                bbox=(
                    str(40 + (index % 2) * 120),
                    str(table_bbox_top + (index // 2) * 20),
                    "300",
                    str(table_bbox_top + 60),
                ),
            )
            for index, text in enumerate(table_parts)
        )
        slice_payload = {
            "table_id": f"table-{role}",
            "page_numbers": (1,),
            "ordered_cell_ids": tuple(item.cell_id for item in cells),
            "exact_text_parts": table_parts,
        }
        table_slices = (
            native.NativeTableSlice815V1(
                table_slice_id=f"table-slice-{role}",
                table_id=f"table-{role}",
                page_numbers=(1,),
                ordered_cell_ids=tuple(item.cell_id for item in cells),
                exact_text_parts=table_parts,
                slice_sha256=hashlib.sha256(repr(slice_payload).encode()).hexdigest(),
            ),
        )

    pages: list[native.NativePdfPageProjection815V1] = []
    for page_number in page_order:
        indexes = tuple(
            index for index, value in enumerate(page_numbers) if value == page_number
        )
        canonical_parts: list[str] = []
        for index in indexes:
            canonical_parts.append(lines[index])
            if canonical_gap_after_line is not None and index == canonical_gap_after_line[0]:
                canonical_parts.append(canonical_gap_after_line[1])
        canonical_text = "\n".join(canonical_parts)
        words: list[native.NativeTextWord815V1] = []
        spans: list[native.NativeTextSpan815V1] = []
        cursor = 0
        for line_order, index in enumerate(indexes):
            if line_order:
                cursor += 1
            text = lines[index]
            start = cursor
            cursor += len(text)
            bbox = (
                line_bboxes[index]
                if line_bboxes is not None
                else (
                    str(40 + bbox_shift),
                    str(60 + index * 20),
                    "300",
                    str(74 + index * 20),
                )
            )
            digest = hashlib.sha256(text.encode()).hexdigest()
            words.append(
                native.NativeTextWord815V1(
                    word_id=f"word-{role}-{index}",
                    text=text,
                    char_start=start,
                    char_end=cursor,
                    bbox=bbox,
                )
            )
            spans.append(
                native.NativeTextSpan815V1(
                    span_id=f"span-{role}-{index}",
                    parent_block_id=(
                        parent_block_ids[index]
                        if parent_block_ids is not None
                        else f"block-{role}-{index}"
                    ),
                    page_number=page_number,
                    char_start=start,
                    char_end=cursor,
                    rects=(bbox,),
                    exact_text=text,
                    text_sha256=digest,
                )
            )
            if (
                canonical_gap_after_line is not None
                and index == canonical_gap_after_line[0]
                and line_order < len(indexes) - 1
            ):
                cursor += len(canonical_gap_after_line[1]) + 1
        pages.append(
            native.NativePdfPageProjection815V1(
                page_number=page_number,
                page_width_points="612",
                page_height_points="792",
                canonical_page_text=canonical_text,
                page_text_sha256=hashlib.sha256(canonical_text.encode()).hexdigest(),
                words=tuple(words),
                spans=tuple(spans),
                cells=cells if page_number == 1 else (),
                table_slices=table_slices if page_number == 1 else (),
                table_unavailability=(),
            )
        )
    provisional = native.NativePdfSelectionProjection815V1(
        adapter_version="pdfplumber-0.11.10/native-text-position.815.v1",
        coordinate_space="PDF_POINTS_TOP_LEFT_V1",
        source_revision_id=source_revision_id or f"{role}-revision",
        source_role=role,
        original_file_sha256=(
            original_file_sha256
            or hashlib.sha256(f"{role}-pdf".encode()).hexdigest()
        ),
        pages=tuple(pages),
        parse_manifest_sha256="",
    )
    return replace(
        provisional,
        parse_manifest_sha256=provisional.recomputed_manifest_sha256(),
    )


def _selection_catalog(
    *,
    terms: native.NativePdfSelectionProjection815V1 | None = None,
    brochure: native.NativePdfSelectionProjection815V1 | None = None,
    rate_table: native.NativePdfSelectionProjection815V1 | None = None,
) -> tuple[
    deepseek.Schema67NativePdfExecutionProjection815V1,
    Schema67SelectionCatalog815V1,
]:
    contracts = fixtures._schema67_contract_set()
    source_projections = tuple(
        projection
        for projection in (terms, brochure, rate_table)
        if projection is not None
    )
    roles = cast(
        tuple[MaterialRole, ...],
        tuple(item.source_role for item in source_projections),
    )
    execution = build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=fixtures._execution_plan(contracts),
        available_source_roles=roles,
    )
    return execution, build_field_selection_catalogs_815(
        field_contracts=contracts,
        provider_visible_field_ids=execution.provider_visible_field_ids,
        available_source_roles=roles,
        source_projections=source_projections,
    )


def test_815_schema_intent_catalog_recalls_frozen_business_target_dimensions() -> None:
    terms = _source_projection(
        role="terms",
        lines=(
            "1.3 投保范围",
            "本合同接受的被保险人投保年龄为0周岁至70周岁。",
            "家庭成员仅指投保人本人、投保时具有合法婚姻关系的配偶、父母及子女。",
            "1.4 健康告知",
            "1.5.1 等待期",
            "本合同生效后30日为等待期，意外伤害无等待期。",
            "1.5.2 保险责任",
            "5.2 保险事故通知",
            "投保人、被保险人或受益人应当在知道保险事故后10日内通知我们。",
            "5.3 保险金申请",
            "申请一般医疗保险金时应提交保险金申请书、医疗费用原始凭证、结算清单及基本医疗保险补偿证明。",
            "5.4 保险金给付",
            "5.5 医疗机构定义",
            "医院指二级以上基本医疗保险定点医院普通部，不包括特需部、国际部、昂贵医院、疗养院和康复医院。",
            "5.6 免赔额计算",
            "免赔额定义一。",
            "免赔额定义二。",
            "免赔额定义三。",
            "免赔额定义四。",
            "免赔额定义五。",
            "免赔额定义六。",
            "免赔额定义七。",
            "免赔额定义八。",
            "免赔额定义九。",
            "免赔额定义十。",
            "免赔额定义十一。",
            "免赔额定义十二。",
            "附录2计划表：计划一年度免赔额10000元，计划二年度免赔额0元。",
            "5.7 赔付比例",
            "附录2计划表：有基本医疗保险并使用时给付比例100%，未使用时给付比例60%。",
            "6.1 犹豫期",
            "自签收本合同之日起15日内可以解除合同并退还全部保险费。",
            "6.2 合同效力恢复",
        ),
    )
    _, catalog = _selection_catalog(
        terms=terms,
        brochure=_source_projection(role="brochure", lines=("保障期间",)),
        rate_table=_source_projection(role="rate_table", lines=("可投保职业",)),
    )

    required_fragments = {
        "insured_eligibility": ("家庭成员仅指", "合法婚姻关系"),
        "deductible_rules": ("计划一年度免赔额10000元", "计划二年度免赔额0元"),
        "reimbursement_rate_rules": ("给付比例100%", "给付比例60%"),
        "eligible_hospital_scope": ("二级以上基本医疗保险定点医院普通部", "不包括特需部"),
        "claim_application_deadline_and_documents": (
            "知道保险事故后10日内通知",
            "医疗费用原始凭证、结算清单",
        ),
    }
    spans_by_id = {span.span_id: span for page in terms.pages for span in page.spans}
    missing_by_field: dict[str, tuple[str, ...]] = {}
    for field_id, fragments in required_fragments.items():
        field = catalog.require_field(field_id)
        selected_text = "\n".join(
            part for selection in field.selections for part in selection.exact_text_parts
        )
        missing = tuple(fragment for fragment in fragments if fragment not in selected_text)
        if missing:
            missing_by_field[field_id] = missing
        assert field.allowed_source_roles == ("terms",)
        assert all(
            spans_by_id[subject_id].exact_text == exact_text
            for selection in field.selections
            if selection.selection_type == "TEXT_SPAN"
            for subject_id, exact_text in zip(
                selection.subject_ids,
                selection.exact_text_parts,
                strict=True,
            )
        )
    assert missing_by_field == {}

    assert "0周岁至70周岁" in "\n".join(
        part
        for selection in catalog.require_field("entry_age_range").selections
        for part in selection.exact_text_parts
    )
    assert "签收本合同之日起15日" in "\n".join(
        part
        for selection in catalog.require_field("cooling_off_period").selections
        for part in selection.exact_text_parts
    )
    assert "30日为等待期" in "\n".join(
        part
        for selection in catalog.require_field("waiting_period").selections
        for part in selection.exact_text_parts
    )


def test_815_real_terms_pdf_has_complete_surrender_clause_when_configured() -> None:
    configured_path = os.environ.get("WEKNORA_EC01_TERMS_PDF")
    if not configured_path:
        pytest.skip("WEKNORA_EC01_TERMS_PDF_UNAVAILABLE")

    pdf_bytes = Path(configured_path).read_bytes()
    source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    assert source_sha256 == _FROZEN_TERMS_PDF_SHA256_815
    terms = native.extract_native_pdf_selection_projection_815(
        pdf_bytes,
        expected_source_sha256=_FROZEN_TERMS_PDF_SHA256_815,
        source_revision_id=f"terms-{_FROZEN_TERMS_PDF_SHA256_815}",
        source_role="terms",
    )
    _, catalog = _selection_catalog(
        terms=terms,
        brochure=_source_projection(role="brochure", lines=()),
        rate_table=_source_projection(role="rate_table", lines=()),
    )

    field = catalog.require_field("surrender_and_cancellation_terms")
    clause = next(
        selection
        for selection in field.selections
        if selection.selection_type == "TEXT_SPAN"
        and selection.page_numbers == (26,)
        and len(selection.subject_ids) > 1
        and selection.exact_text_parts[0].startswith("6.1 犹豫期 ")
    )
    expected_parts = (
        "6.1 犹豫期 自您签收本合同之日起，有15日的犹豫期。在此期间请您认真审视本合同，",
        "如果您认为本合同与您的需求不相符，您可以在此期间提出解除本合同，我",
        "们将退还您所支付的全部保险费。",
        "解除本合同时，您需要填写解除合同通知书，并提供您的保险合同及有效身",
        "份证件。自我们收到您解除合同的通知书时，本合同即被解除，合同解除前",
        "发生的保险事故我们不承担保险责任。",
    )
    assert clause.exact_text_parts == expected_parts
    clause_text = "".join(clause.exact_text_parts)
    assert "6.2" not in clause_text

    page = terms.pages[25]
    spans_by_id = {span.span_id: span for span in page.spans}
    selected_spans = tuple(spans_by_id[subject_id] for subject_id in clause.subject_ids)
    assert clause.exact_text_parts == tuple(span.exact_text for span in selected_spans)
    assert all(
        page.canonical_page_text[span.char_start : span.char_end] == span.exact_text
        for span in selected_spans
    )
    assert all("6.2" not in span.exact_text for span in selected_spans)
    assert page.canonical_page_text.find("6.2", selected_spans[-1].char_end) != -1

    selected_words = tuple(
        word
        for word in page.words
        if any(
            span.char_start <= word.char_start and word.char_end <= span.char_end
            for span in selected_spans
        )
    )
    assert selected_words
    assert all(
        page.canonical_page_text[word.char_start : word.char_end] == word.text
        for word in selected_words
    )
    rects = tuple(rect for span in selected_spans for rect in span.rects)
    assert len(rects) > 1
    union = native_selection._union_native_bbox_815(rects)
    assert union == native_selection._union_native_bbox_815(
        tuple(word.bbox for word in selected_words)
    )
    assert all(
        Decimal(union[0]) <= Decimal(rect[0]) <= Decimal(rect[2]) <= Decimal(union[2])
        and Decimal(union[1]) <= Decimal(rect[1]) <= Decimal(rect[3]) <= Decimal(union[3])
        for rect in rects
    )


def test_815_real_terms_pdf_preserves_complete_eligibility_paragraph_when_configured() -> None:
    configured_path = os.environ.get("WEKNORA_EC01_TERMS_PDF")
    if not configured_path:
        pytest.skip("WEKNORA_EC01_TERMS_PDF_UNAVAILABLE")

    pdf_bytes = Path(configured_path).read_bytes()
    assert hashlib.sha256(pdf_bytes).hexdigest() == _FROZEN_TERMS_PDF_SHA256_815
    terms = native.extract_native_pdf_selection_projection_815(
        pdf_bytes,
        expected_source_sha256=_FROZEN_TERMS_PDF_SHA256_815,
        source_revision_id=f"terms-{_FROZEN_TERMS_PDF_SHA256_815}",
        source_role="terms",
    )
    _, catalog = _selection_catalog(
        terms=terms,
        brochure=_source_projection(role="brochure", lines=()),
        rate_table=_source_projection(role="rate_table", lines=()),
    )

    expected_parts = (
        "您可以同时为符合我们承保条件的家庭成员投保本产品，家庭成员仅指投保",
        "人本人、投保时与投保人具有合法婚姻关系的配偶、投保人的父母以及投保",
        "人的子女。",
    )
    field = catalog.require_field("insured_eligibility")
    paragraph = next(
        selection
        for selection in field.selections
        if selection.selection_type == "TEXT_SPAN"
        and selection.page_numbers == (2,)
        and selection.exact_text_parts == expected_parts
    )
    assert field.allowed_source_roles == ("terms",)

    page = terms.pages[1]
    spans_by_id = {span.span_id: span for span in page.spans}
    selected_spans = tuple(spans_by_id[subject_id] for subject_id in paragraph.subject_ids)
    assert paragraph.exact_text_parts == tuple(span.exact_text for span in selected_spans)
    assert all(
        page.canonical_page_text[span.char_start : span.char_end] == span.exact_text
        for span in selected_spans
    )
    assert all(
        following.char_start == previous.char_end + 1
        for previous, following in zip(
            selected_spans[:-1], selected_spans[1:], strict=True
        )
    )
    assert all(span.rects for span in selected_spans)
    selected_words = tuple(
        word
        for word in page.words
        if any(
            span.char_start <= word.char_start and word.char_end <= span.char_end
            for span in selected_spans
        )
    )
    assert selected_words
    assert all(
        page.canonical_page_text[word.char_start : word.char_end] == word.text
        for word in selected_words
    )
    assert native_selection._union_native_bbox_815(
        tuple(rect for span in selected_spans for rect in span.rects)
    ) == native_selection._union_native_bbox_815(
        tuple(word.bbox for word in selected_words)
    )


def test_815_real_terms_pdf_groups_bounded_integer_list_runs_when_configured() -> None:
    configured_path = os.environ.get("WEKNORA_EC01_TERMS_PDF")
    if not configured_path:
        pytest.skip("WEKNORA_EC01_TERMS_PDF_UNAVAILABLE")

    pdf_bytes = Path(configured_path).read_bytes()
    assert hashlib.sha256(pdf_bytes).hexdigest() == _FROZEN_TERMS_PDF_SHA256_815
    terms = native.extract_native_pdf_selection_projection_815(
        pdf_bytes,
        expected_source_sha256=_FROZEN_TERMS_PDF_SHA256_815,
        source_revision_id=_FROZEN_TERMS_SOURCE_REVISION_ID_815,
        source_role="terms",
    )
    page = terms.pages[23]
    expected_item_subject_ids = {
        4: (
            "span-0fb5fcc331d237f3c77e1a2f56db3560305ab0cd8c052a848711984debf7176a",
            "span-bd6d91d12f847f3b8e0843769821533b94b05dfa7f07368f2be6db9f93dd5390",
        ),
        5: (
            "span-0324a615e67a32bdf8cd6afbca4acfa6fb826ceb4b98037f8c12320363414ca8",
            "span-6dd122dd6de42ee2420f3920f152cb828e127adb81243108fb9b402df17b3f8d",
            "span-ca648c593b9b3932a3adc808e0a186ca03af45438ac8c8d5fe3776836c864033",
            "span-3a2d535227092df39b1eeec0700667114017976e2015e62f86148e59806c241e",
        ),
        6: (
            "span-4e587ca7ceaea4d9b63e75cd2d55b939d16bcf3a5c73da7c37f281c88acd4b87",
            "span-3321373c0effd707a7c4c3d098c96b73bad559b13aea032af282cc51fd9ed42c",
        ),
        7: (
            "span-4e4eec410ee4f8e7a5940a1de8c13e7394a083324db55938d4a7ade502a5e001",
        ),
    }
    expected_item_ranges = {4: (727, 775), 5: (776, 885), 6: (886, 932), 7: (933, 966)}
    page_groups = native_selection._complete_clause_groups_815(page)
    matched_groups = {}
    for item_number, subject_ids in expected_item_subject_ids.items():
        matches = tuple(
            group
            for group in page_groups
            if tuple(span.span_id for span in group.spans) == subject_ids
        )
        assert len(matches) == 1
        matched_groups[item_number] = matches[0]
        assert (
            matches[0].spans[0].char_start,
            matches[0].spans[-1].char_end,
        ) == expected_item_ranges[item_number]
    assert not any(
        set(left.spans).intersection(right.spans)
        for left_number, left in matched_groups.items()
        for right_number, right in matched_groups.items()
        if left_number < right_number
    )

    item5 = matched_groups[5]
    item5_quote = "".join(span.exact_text for span in item5.spans)
    assert hashlib.sha256(item5_quote.encode()).hexdigest() == (
        "716977cfb5f69128af8b826d5aedc7a7d41c522b1ee5fe2afce937d8968d60ea"
    )
    contract = next(
        item
        for item in fixtures._schema67_contract_set().contracts
        if item.field_id == "claim_application_deadline_and_documents"
    )
    item5_selection = native_selection._selection(
        selection_type="TEXT_SPAN",
        field_id=contract.field_id,
        source=terms,
        subject_ids=tuple(span.span_id for span in item5.spans),
        page_numbers=(page.page_number,),
        exact_text_parts=tuple(span.exact_text for span in item5.spans),
        value_part_groups=native_selection._text_value_part_groups_815(item5.spans),
    )
    assert item5_selection.selection_id == (
        "selection-680b62dae34cec5398b4bbe921b8e190cb1b5d7a8ac775f42c8f7a47f73e7eca"
    )

    existing_group_anchors = (
        (1, "span-cec4938cac7fbd863aa2104a6113a6a5bbc4706e718e4b124c69dd0890926891"),
        (3, "span-4c46573dfd926f3a1945b82b054bca9381227c8b5430654691a8175f89f3fa9b"),
        (8, "span-2ba59f1aff99e6ad4de46e22abafbcca92ecc9227935dc19c31956862230daf8"),
        (10, "span-7c12d49976dfe579bcfb1ad34198410dbe5e70fe9d2c3e3f420e6b21f6be0fd9"),
        (12, "span-311c197607cda5f56821a3d306a89d4fa937855bedea8fd08e337be25655cc6f"),
        (12, "span-b4aa22610716eb1a626e0f88fb692b1c34e6ae55fd66840fbd2f8a72b258bba1"),
        (14, "span-87b2d77485cb5c1e6569adc1dc5cf3898e7b2a224bd7faad6d6ef38af74b2577"),
        (21, "span-570816ed21cb8b583d4bcc4dd549dc87cf9fbb22a38896ba28b3afd1222ab9e7"),
        (28, "span-0b788a7a309fc605ba8fdb1588deba94c1a3fb746252aaeb5423ef55b018e1f0"),
        (28, "span-2f6cc2e719ca5fc2119714193c40823eaa07abae540175729a04d8b10e90bbee"),
    )
    existing_group_records = []
    for page_number, anchor_id in existing_group_anchors:
        matches = tuple(
            group
            for group in native_selection._complete_clause_groups_815(
                terms.pages[page_number - 1]
            )
            if group.spans[0].span_id == anchor_id
        )
        assert len(matches) == 1
        group = matches[0]
        existing_group_records.append(
            (
                page_number,
                anchor_id,
                group.ranking_context,
                tuple(span.span_id for span in group.spans),
                tuple(span.exact_text for span in group.spans),
            )
        )
    assert canonical_hash(
        "schema67-existing-integer-group-snapshot.815.v1",
        tuple(existing_group_records),
    ) == "b2ad2286d8c6d2bb60274ac80b0962628d0d8e69ba5cc2f17cab1322e18d0344"

    integer_start = re.compile(r"^\s*[1-9]\d?\.\s+\S")
    existing_anchor_set = set(existing_group_anchors)
    new_group_counts: dict[int, int] = {}
    for source_page in terms.pages:
        new_groups = tuple(
            group
            for group in native_selection._complete_clause_groups_815(source_page)
            if integer_start.match(group.spans[0].exact_text)
            and (source_page.page_number, group.spans[0].span_id)
            not in existing_anchor_set
        )
        if new_groups:
            new_group_counts[source_page.page_number] = len(new_groups)
        assert all(
            all(span.page_number == source_page.page_number for span in group.spans)
            for group in new_groups
        )
    assert new_group_counts == {13: 5, 23: 6, 24: 9, 25: 9, 26: 2}

    _, catalog = _selection_catalog(
        terms=terms,
        brochure=_source_projection(role="brochure", lines=()),
        rate_table=_source_projection(role="rate_table", lines=()),
    )
    assert {
        field_id: catalog.require_field(field_id).catalog_sha256
        for field_id in (
            "entry_age_range",
            "insured_eligibility",
            "cooling_off_period",
            "waiting_period",
        )
    } == {
        "entry_age_range": "282e119671ab385648ba8a4ed009bc99f323289d541be7493014d9da2058b383",
        "insured_eligibility": "834dfcfe63efe75fe303481b778546c5a2fbc8a5156be4e6fc1beb935e4e3aa7",
        "cooling_off_period": "b4e0e4a95951e9ee813d268e1455af4710cbcb79c71f9c2a3beb6a582ff5b53c",
        "waiting_period": "83693bf09ddf0588b7093c57391cebda2d13da609fc7c09adcf1d42794db845e",
    }


def test_815_integer_list_ranking_preserves_complete_field_clauses_when_configured() -> None:
    configured_path = os.environ.get("WEKNORA_EC01_TERMS_PDF")
    if not configured_path:
        pytest.skip("WEKNORA_EC01_TERMS_PDF_UNAVAILABLE")

    revision_root = Path(configured_path).parent
    authorities: tuple[tuple[MaterialRole, str, str], ...] = (
        (
            "terms",
            _FROZEN_TERMS_SOURCE_REVISION_ID_815,
            _FROZEN_TERMS_PDF_SHA256_815,
        ),
        (
            "brochure",
            "89944ff7ecbfdcb0d00b7ceacfbdac4407389af078514317e2a3affe1973de50",
            "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
        ),
        (
            "rate_table",
            "1c29dfab5f72de0a8490cd91e0eaeba901967f83f4a8d1aed0065c20db564a4e",
            "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
        ),
    )
    projections = {}
    for role, source_revision_id, source_sha256 in authorities:
        pdf_bytes = (revision_root / f"{role}.pdf").read_bytes()
        assert hashlib.sha256(pdf_bytes).hexdigest() == source_sha256
        projections[role] = native.extract_native_pdf_selection_projection_815(
            pdf_bytes,
            expected_source_sha256=source_sha256,
            source_revision_id=source_revision_id,
            source_role=role,
        )

    _, catalog = _selection_catalog(
        terms=projections["terms"],
        brochure=projections["brochure"],
        rate_table=projections["rate_table"],
    )

    drug_clause_id = (
        "selection-f00836847d645027d76ca9d313684a22bb1f45953f694f04eb93b0c383eb1775"
    )
    assert drug_clause_id in {
        selection.selection_id
        for selection in catalog.require_field(
            "out_of_hospital_special_drug_coverage"
        ).selections
    }

    rotations = {
        "coverage_period": (
            "dd658f979a88bdeed0b4efb538371c9c3c63d763cc43c8956ebcea6b93b8fba6",
            (),
            (),
        ),
        "post_discontinuation_renewal_arrangement": (
            "dff9e6d090efa1dde26f2649004c58d689cae4f2d56e19f46b25acba481579a7",
            (
                "selection-47fc0098452af2e880622685489bcb43d9633322963022cf8e010c51cdca5e14",
            ),
            (
                "selection-ba37033e1d1bd72815d61f88634932266b3dc0b07f04f1512d743652469b401d",
            ),
        ),
        "exclusions": (
            "276654290a1f2ac1b2e2d49a74c71f13006467148b2a0a5fcf95678f9393b4e3",
            (
                "selection-6afd4b0f8e574dbf69e65c7f9cd587feb4db3488e4f0f65de5a06178a96b3da6",
            ),
            (
                "selection-20b8cd3357226e62566bd6bb9ca6b44fb410e985a736f977aa5b576fc35a3d2c",
            ),
        ),
        "out_of_hospital_special_drug_coverage": (
            "61526d19737f035abb67846b121ec27822a76a83b1f1cba98dedce0f1da53d8e",
            (
                "selection-4723ebcbd4554b4b821d7f78d64c54392720139f1ce631160c20d14e66bc0c74",
            ),
            (drug_clause_id,),
        ),
        "indemnity_principle": (
            "d84010b1e5431e5778b45548c49167254f4a28c4781c397bf001ecc5844c7bad",
            (
                "selection-ce1d0ce7557fa27ebc876c0289c47bd343ef211956ddeb975ccdee650d4687aa",
            ),
            (
                "selection-ac2b528b21468d315ae5bffbb45cd724f6b013831184ce86d135380690d50140",
            ),
        ),
        "outpatient_inpatient_scope": (
            "de42d6eef083df34ca8d7907f7359eff8f449a128a8f8c4fee16c5986bade7c1",
            (
                "selection-928b522dcb1b5b85700f23b0117a3f55431bbafe9208166cfbd218b3cb13759c",
            ),
            (
                "selection-78e2887d2456e62828a25d3f671a3225d81cd69abb042adcef4adf9580862295",
            ),
        ),
        "eligible_hospital_scope": (
            "4500c4584c10c18e02e713c15e9f2be27a184b9849f635d7bf263e8b6e391ad5",
            (
                "selection-91958d66b853a336c4c46d6cbc365d8133a79c47b7d3458afb36194564a4c6a9",
                "selection-50d12440c3876cc99f014bef20ae6f8fa12da763078a250f5286b8f6cf496ae0",
                "selection-5d68f27ee162a8a697f735cdc2f294edfba73356c9138fbbf0c22f22223266d8",
                "selection-556be4458004e9fdc8c0ad5e22502141319aad6dcde865d74c5d07ef62f1991a",
                "selection-81f35121b12120a602f317243e448df68330cddaa26a36d6584cd37fa37b38e0",
            ),
            (
                "selection-82d86985fdc9dfeabd9517b8d4453fc6581c8e2658a7a6b1ee917aa6609ae5ef",
                "selection-6e8f1caeeac63cd5c96c4ade0025ebbc1a03d6296d690ba10f8a25e3543ece78",
                "selection-ab4a23acd86642a765f2bf48ddc7341cbfbb8a6a029bc210abab632bff43f760",
                "selection-07295e80588bf56571ec365938d3e6fe130e4afea9308240ef4922ec1e1200f2",
                "selection-c58ef1e0d5eefc8f104f6af674996b1cad3ab44f51c0e69243dcd2f0f9e4c34a",
            ),
        ),
        "claim_application_deadline_and_documents": (
            "243e3948d3b5a45afc30efc5d0f6885b3ee87dd1c9e714ded9dcbf097cc40929",
            (
                "selection-a599f8caf14d7f02a73702420f2d95909881654db9653b30ff82999aa74ff9c2",
            ),
            (
                "selection-64d163e2ed55323625c7ac863e83b1e87b646e5caedfe4c96f8a00a24a40038f",
            ),
        ),
    }
    for field_id, (expected_sha256, removed, restored) in rotations.items():
        field = catalog.require_field(field_id)
        selection_ids = tuple(selection.selection_id for selection in field.selections)
        assert field.catalog_sha256 == expected_sha256
        assert set(removed).isdisjoint(selection_ids)
        assert set(restored) <= set(selection_ids)

    unaffected = tuple(
        (field.field_id, field.catalog_sha256)
        for field in catalog.fields
        if field.field_id not in rotations
    )
    assert canonical_hash(
        "schema67-integer-group-ranking-unaffected-catalogs.815.v1",
        unaffected,
    ) == "48efdaad643332db04b3d0836f545f1356f2cc3a29a531abe48f014302a9e14f"


def test_815_integer_groups_are_parse_only_for_all_source_extract_fields() -> None:
    configured_path = os.environ.get("WEKNORA_EC01_TERMS_PDF")
    if not configured_path:
        pytest.skip("WEKNORA_EC01_TERMS_PDF_UNAVAILABLE")

    revision_root = Path(configured_path).parent
    authorities: tuple[tuple[MaterialRole, str, str], ...] = (
        (
            "terms",
            _FROZEN_TERMS_SOURCE_REVISION_ID_815,
            _FROZEN_TERMS_PDF_SHA256_815,
        ),
        (
            "brochure",
            "89944ff7ecbfdcb0d00b7ceacfbdac4407389af078514317e2a3affe1973de50",
            "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
        ),
        (
            "rate_table",
            "1c29dfab5f72de0a8490cd91e0eaeba901967f83f4a8d1aed0065c20db564a4e",
            "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
        ),
    )
    projections = {}
    for role, source_revision_id, source_sha256 in authorities:
        pdf_bytes = (revision_root / f"{role}.pdf").read_bytes()
        assert hashlib.sha256(pdf_bytes).hexdigest() == source_sha256
        projections[role] = native.extract_native_pdf_selection_projection_815(
            pdf_bytes,
            expected_source_sha256=source_sha256,
            source_revision_id=source_revision_id,
            source_role=role,
        )

    _, catalog = _selection_catalog(
        terms=projections["terms"],
        brochure=projections["brochure"],
        rate_table=projections["rate_table"],
    )
    integer_group_records = tuple(
        (
            projection.source_role,
            page.page_number,
            group.ranking_context,
            tuple(asdict(span) for span in group.spans),
        )
        for projection in projections.values()
        for page in projection.pages
        for group in native_selection._complete_clause_groups_815(page)
        if group.content_priority == 1
    )
    assert len(integer_group_records) == 56
    assert canonical_hash(
        "schema67-integer-list-parse-groups.815.v1",
        integer_group_records,
    ) == "8454d4036f5c7bec4d9942ae4b934ec498502a48cea9bdb62d7861845ed6b2a5"
    integer_group_subjects = frozenset(
        (projection.source_role, tuple(span.span_id for span in group.spans))
        for projection in projections.values()
        for page in projection.pages
        for group in native_selection._complete_clause_groups_815(page)
        if group.content_priority == 1
    )
    assert integer_group_subjects

    integer_admissions = tuple(
        (field.field_id, selection.selection_id)
        for field in catalog.fields
        for selection in field.selections
        if (selection.source_role, selection.subject_ids) in integer_group_subjects
    )
    assert integer_admissions == ()
    assert len(catalog.fields) == 25
    assert canonical_hash(
        "schema67-source-extract-ordered-selections-baseline.815.v1",
        tuple(
            (
                field.field_id,
                tuple(selection.selection_id for selection in field.selections),
            )
            for field in catalog.fields
        ),
    ) == "91b39ec666dd2206368207f9c9d22cdbdb9b5c002d2a294c9d7ae68cd06409cd"
    assert catalog.catalog_sha256 == (
        "c038e8a56a155d3f0334b21f291d486e1b0b77c0ae5ab2b7e564753691de2176"
    )


def test_815_integer_list_run_does_not_cross_section_boundary() -> None:
    terms = _source_projection(
        role="terms",
        lines=("4. 前一列表项", "◆ 独立章节", "5. 后一列表项"),
    )

    groups = native_selection._complete_clause_groups_815(terms.pages[0])

    assert not any(
        group.spans[0].exact_text in {"4. 前一列表项", "5. 后一列表项"}
        for group in groups
    )


def test_815_real_terms_pdf_rejects_nonfrozen_bytes_when_configured() -> None:
    configured_path = os.environ.get("WEKNORA_EC01_TERMS_PDF")
    if not configured_path:
        pytest.skip("WEKNORA_EC01_TERMS_PDF_UNAVAILABLE")

    pdf_bytes = Path(configured_path).read_bytes()
    assert hashlib.sha256(pdf_bytes).hexdigest() == _FROZEN_TERMS_PDF_SHA256_815
    with pytest.raises(native.NativePdfplumberError, match="source_digest_mismatch"):
        native.extract_native_pdf_selection_projection_815(
            pdf_bytes + b"\nsource-drift",
            expected_source_sha256=_FROZEN_TERMS_PDF_SHA256_815,
            source_revision_id=f"terms-{_FROZEN_TERMS_PDF_SHA256_815}",
            source_role="terms",
        )


def test_815_selection_catalog_is_field_local_bounded_and_self_hashed() -> None:
    execution, catalog = _selection_catalog(
        terms=_source_projection(
            role="terms",
            lines=("责任免除 战争责任", "责任免除 战争责任", "免赔额为一万元"),
        ),
        brochure=_source_projection(role="brochure", lines=("保障期间为一年",)),
        rate_table=_source_projection(
            role="rate_table",
            table_parts=("可投保职业", "类别", "1", "医疗", "注：按职业分类"),
        ),
    )

    assert len(catalog.fields) == execution.provider_visible_field_count == 25
    exclusions = catalog.require_field("exclusions")
    deductible = catalog.require_field("deductible_rules")
    assert exclusions.allowed_source_roles == ("terms",)
    assert len(exclusions.selections) == 2
    assert len({item.selection_id for item in exclusions.selections}) == 2
    assert all(item.source_role == "terms" for item in exclusions.selections)
    assert len(exclusions.selections) <= 12
    assert set(item.selection_id for item in exclusions.selections).isdisjoint(
        item.selection_id for item in deductible.selections
    )
    assert catalog.catalog_sha256 == catalog.recomputed_catalog_sha256()


def test_815_schema_guidance_is_not_emitted_as_candidate_source_text() -> None:
    contracts = fixtures._schema67_contract_set()
    _, catalog = _selection_catalog(
        terms=_source_projection(role="terms", lines=("责任免除 战争责任",)),
        brochure=_source_projection(role="brochure", lines=("保障期间为一年",)),
        rate_table=_source_projection(role="rate_table", lines=("可投保职业为一至三类",)),
    )
    source_texts = {
        "责任免除 战争责任",
        "保障期间为一年",
        "可投保职业为一至三类",
    }

    assert all(
        part in source_texts
        for field in catalog.fields
        for selection in field.selections
        for part in selection.exact_text_parts
    )
    exclusions_contract = next(
        item for item in contracts.contracts if item.field_id == "exclusions"
    )
    assert exclusions_contract.description not in source_texts


def test_815_synthetic_exact_eight_complete_group_requests_stay_bounded() -> None:
    contracts = fixtures._schema67_contract_set()
    execution = build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=fixtures._execution_plan(contracts),
        available_source_roles=("terms", "brochure", "rate_table"),
    )
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=execution.execution_plan,
        role_inputs=fixtures._schema67_role_inputs(contracts, execution.execution_plan),
    )
    _, catalog = _selection_catalog(
        terms=_source_projection(
            role="terms",
            lines=(
                "1.3 投保范围",
                "首次投保年龄为出生满30日至70周岁。",
                "71至100周岁须同时满足以下条件：",
                "（1）既往已经投保；（2）经保险人审核同意。",
                "投保人可为本人、配偶、父母及子女投保。",
                "1.4 健康告知",
                "投保人应如实告知健康状况。",
                "6.1 犹豫期及合同解除（退保）",
                "犹豫期内投保人可书面申请解除合同。",
                "犹豫期后退还现金价值，并可能产生损失。",
                "6.2 合同效力恢复",
                "责任免除包括战争责任。",
                "免赔额为一万元。",
            ),
        ),
        brochure=_source_projection(role="brochure", lines=("保障期间为一年。",)),
        rate_table=_source_projection(
            role="rate_table",
            table_parts=("可投保职业", "类别", "1", "医疗"),
        ),
    )
    request_sizes: list[int] = []
    for task in prepared:
        task_catalogs = tuple(
            deepseek._task_native_selection_catalog_815(
                prompt=item,
                catalog=catalog.require_field(item.field_id),
            )
            for item in task.field_prompts
        )
        request = deepseek._PreparedExtractorRequest(
            contracts=task.field_prompts,
            locators=(),
            contract_payload=tuple(
                deepseek._request_field_contract_payload(item)
                for item in task.field_prompts
            ),
            slot_authority=cast(deepseek._LocatorSlotAuthorityV1, object()),
            locator_authority_sha256="a" * 64,
            locator_selection_sha256="b" * 64,
            payload={
                "task_id": task.provider_task_sha256,
                "attempt_hash": task.provider_attempt_sha256,
            },
            system="",
            user="",
            request_sha256="",
        )
        system, user, _request_sha256 = deepseek._prepare_native_selection_request_815(
            prepared_request=request,
            task_key=task.task_key,
            field_catalogs=task_catalogs,
        )
        request_sizes.append(
            len(deepseek._deepseek_request_bytes(system=system, user=user))
        )

    assert len(request_sizes) == 8
    assert max(request_sizes) <= deepseek.DEEPSEEK_MAX_REQUEST_BYTES


def test_815_mixed_formation_field_has_no_selection_catalog() -> None:
    _, catalog = _selection_catalog(
        terms=_source_projection(role="terms", lines=("产品特色", "责任免除")),
        brochure=_source_projection(role="brochure", lines=("产品特色",)),
        rate_table=_source_projection(role="rate_table", lines=("可投保职业",)),
    )

    with pytest.raises(
        NativePdfSelectionError815,
        match="FIELD_SELECTION_CATALOG_NOT_FOUND",
    ):
        catalog.require_field("official_product_features")


def test_815_table_slice_requires_header_unit_or_condition_context() -> None:
    _, catalog = _selection_catalog(
        terms=_source_projection(role="terms", lines=("责任免除",)),
        brochure=_source_projection(role="brochure", lines=("保障期间",)),
        rate_table=_source_projection(
            role="rate_table",
            table_parts=("可投保职业", "1"),
        ),
    )

    assert catalog.require_field("eligible_occupation_classes").selections == ()


def test_815_bbox_only_change_rotates_selection_and_catalog_identity() -> None:
    baseline_source = _source_projection(role="terms", lines=("责任免除 战争责任",))
    changed_source = _source_projection(
        role="terms",
        lines=("责任免除 战争责任",),
        bbox_shift=1,
    )
    assert baseline_source.pages[0].spans[0].span_id == changed_source.pages[0].spans[0].span_id
    assert baseline_source.parse_manifest_sha256 != changed_source.parse_manifest_sha256

    _, baseline = _selection_catalog(
        terms=baseline_source,
        brochure=_source_projection(role="brochure", lines=("保障期间",)),
        rate_table=_source_projection(role="rate_table", lines=("可投保职业",)),
    )
    _, changed = _selection_catalog(
        terms=changed_source,
        brochure=_source_projection(role="brochure", lines=("保障期间",)),
        rate_table=_source_projection(role="rate_table", lines=("可投保职业",)),
    )

    baseline_selection = baseline.require_field("exclusions").selections[0]
    changed_selection = changed.require_field("exclusions").selections[0]
    assert baseline_selection.selection_id != changed_selection.selection_id
    assert baseline.catalog_sha256 != changed.catalog_sha256


def test_815_catalog_prefers_complete_clause_over_toc_heading_and_summary() -> None:
    lines = (
        "您有退保的权利........................6.2",
        "如何退保",
        "这部分讲的是您可随时申请退保以及可能承担的损失。",
        "6.1 犹豫期 自您签收本合同之日起，有15日的犹豫期。",
        "在此期间请您认真审视本合同，如果您认为本合同与您的需求不相符，",
        "您可以在此期间提出解除本合同，我们将退还您所支付的全部保险费。",
        "解除本合同时，您需要填写解除合同通知书，并提供您的保险合同及有效身份证件。",
        "自我们收到您解除合同的通知书时，本合同即被解除。",
        "6.2 犹豫期后解除合同的手续及风险 本合同成立后，您可以解除本合同。",
    )
    _, catalog = _selection_catalog(
        terms=_source_projection(
            role="terms",
            lines=lines,
            table_parts=("退保", "办理条件", "犹豫期", "合同解除"),
            table_bbox_top=400,
        ),
        brochure=_source_projection(role="brochure", lines=("保障期间",)),
        rate_table=_source_projection(role="rate_table", lines=("可投保职业",)),
    )

    contract = next(
        item
        for item in fixtures._schema67_contract_set().contracts
        if item.field_id == "surrender_and_cancellation_terms"
    )
    assert {"犹豫期", "合同解除", "退保"} <= set(
        intent.term
        for intent in native_selection._retrieval_intents_815(
            contract=contract,
            corpus_pages=(),
        )
    )
    field = catalog.require_field("surrender_and_cancellation_terms")
    clause = next(
        item
        for item in field.selections
        if item.subject_ids
        == (
            "span-terms-3",
            "span-terms-4",
            "span-terms-5",
            "span-terms-6",
            "span-terms-7",
        )
    )
    assert clause.exact_text_parts == lines[3:8]
    assert "如何退保" not in clause.exact_text_parts

    table_index = next(
        index
        for index, item in enumerate(field.selections)
        if item.selection_type == "TABLE_SLICE"
    )
    clause_index = field.selections.index(clause)
    summary_index = next(
        index
        for index, item in enumerate(field.selections)
        if item.subject_ids == ("span-terms-2",)
    )
    title_index = next(
        index
        for index, item in enumerate(field.selections)
        if item.subject_ids == ("span-terms-1",)
    )
    toc_index = next(
        index
        for index, item in enumerate(field.selections)
        if item.subject_ids == ("span-terms-0",)
    )
    assert clause_index < table_index < summary_index < title_index < toc_index


def test_815_catalog_scores_complete_clause_with_uniconed_section_context() -> None:
    lines = (
        "如何退保",
        "本节概要。",
        "6.1 说明 本节规则如下。",
        "适用本节的人员应遵守约定。",
        "6.2 后续规则 另行说明。",
    )
    _, catalog = _selection_catalog(
        terms=_source_projection(role="terms", lines=lines),
        brochure=_source_projection(role="brochure", lines=("保障期间",)),
        rate_table=_source_projection(role="rate_table", lines=("可投保职业",)),
    )

    field = catalog.require_field("surrender_and_cancellation_terms")
    clause = next(
        item
        for item in field.selections
        if item.subject_ids == ("span-terms-2", "span-terms-3")
    )
    assert field.selections[0] == clause
    assert clause.exact_text_parts == lines[2:4]
    assert "如何退保" not in clause.exact_text_parts


def test_815_catalog_does_not_reuse_prior_clause_span_as_section_context() -> None:
    _, catalog = _selection_catalog(
        terms=_source_projection(
            role="terms",
            lines=(
                "6.1 前一规则 本条内容。",
                "退保",
                "6.2 后一规则 完全无关。",
            ),
        ),
        brochure=_source_projection(role="brochure", lines=("保障期间",)),
        rate_table=_source_projection(role="rate_table", lines=("可投保职业",)),
    )

    field = catalog.require_field("surrender_and_cancellation_terms")
    assert any(
        item.subject_ids == ("span-terms-0", "span-terms-1")
        for item in field.selections
    )
    assert all(item.subject_ids != ("span-terms-2",) for item in field.selections)


def test_815_catalog_does_not_cross_large_geometry_gap_for_section_context() -> None:
    lines = (
        "① 退保",
        "6.1 说明 本节规则如下。",
        "适用本节的人员应遵守约定。",
        "6.2 后续规则 另行说明。",
    )
    _, catalog = _selection_catalog(
        terms=_source_projection(
            role="terms",
            lines=lines,
            line_bboxes=(
                ("40", "60", "300", "74"),
                ("40", "160", "300", "174"),
                ("40", "180", "300", "194"),
                ("40", "200", "300", "214"),
            ),
        ),
        brochure=_source_projection(role="brochure", lines=("保障期间",)),
        rate_table=_source_projection(role="rate_table", lines=("可投保职业",)),
    )

    field = catalog.require_field("surrender_and_cancellation_terms")
    assert all(item.subject_ids != ("span-terms-1", "span-terms-2") for item in field.selections)


def test_815_catalog_does_not_cross_canonical_gap_for_section_context() -> None:
    lines = (
        "① 退保",
        "6.1 说明 本节规则如下。",
        "适用本节的人员应遵守约定。",
        "6.2 后续规则 另行说明。",
    )
    _, catalog = _selection_catalog(
        terms=_source_projection(
            role="terms",
            lines=lines,
            canonical_gap_after_line=(0, "未选择的间隔文本"),
        ),
        brochure=_source_projection(role="brochure", lines=("保障期间",)),
        rate_table=_source_projection(role="rate_table", lines=("可投保职业",)),
    )

    field = catalog.require_field("surrender_and_cancellation_terms")
    assert all(item.subject_ids != ("span-terms-1", "span-terms-2") for item in field.selections)


def test_815_catalog_reuses_clause_groups_once_per_source_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = fixtures._schema67_contract_set()
    sources = (
        _source_projection(
            role="terms",
            lines=("6.1 犹豫期 退保规则。", "本节内容。"),
        ),
        _source_projection(role="brochure", lines=("保障期间",)),
        _source_projection(role="rate_table", lines=("可投保职业",)),
    )
    execution = build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=fixtures._execution_plan(contracts),
        available_source_roles=("terms", "brochure", "rate_table"),
    )
    original = native_selection._contiguous_clause_groups_815
    calls = 0

    def counting_groups(
        page: native.NativePdfPageProjection815V1,
    ) -> tuple[tuple[native.NativeTextSpan815V1, ...], ...]:
        nonlocal calls
        calls += 1
        return original(page)

    monkeypatch.setattr(native_selection, "_contiguous_clause_groups_815", counting_groups)
    build_field_selection_catalogs_815(
        field_contracts=contracts,
        provider_visible_field_ids=execution.provider_visible_field_ids,
        available_source_roles=("terms", "brochure", "rate_table"),
        source_projections=sources,
    )

    assert calls == sum(len(source.pages) for source in sources)


@pytest.mark.parametrize(
    ("boundary", "line_bboxes", "line_page_numbers", "table_parts", "table_bbox_top"),
    [
        (
            "下一页正文仍然提及退保。",
            None,
            (1, 1, 2),
            (),
            200,
        ),
        ("6.2 解除合同 您可以在犹豫期后退保。", None, None, (), 200),
        ("① 退保手续", None, None, (), 200),
        ("退保说明........................6.2", None, None, (), 200),
        (
            "26",
            (("40", "60", "300", "74"), ("40", "80", "300", "94"), ("40", "700", "300", "714")),
            None,
            (),
            200,
        ),
        (
            "退保表格重叠行",
            (("40", "60", "300", "74"), ("40", "80", "300", "94"), ("40", "205", "300", "219")),
            None,
            ("退保", "办理条件", "犹豫期", "合同解除"),
            200,
        ),
        (
            "退保间隔过大的正文。",
            (("40", "60", "300", "74"), ("40", "80", "300", "94"), ("40", "160", "300", "174")),
            None,
            (),
            200,
        ),
        (
            "退保阅读顺序回跳正文。",
            (("40", "60", "300", "74"), ("40", "80", "300", "94"), ("40", "70", "300", "84")),
            None,
            (),
            200,
        ),
    ],
    ids=(
        "next-page",
        "new-clause",
        "section-icon",
        "toc",
        "bottom-page-number",
        "table-overlap",
        "large-gap",
        "geometry-rewind",
    ),
)
def test_815_clause_group_stops_at_hard_boundaries(
    boundary: str,
    line_bboxes: tuple[native.NativeBBox, ...] | None,
    line_page_numbers: tuple[int, ...] | None,
    table_parts: tuple[str, ...],
    table_bbox_top: int,
) -> None:
    _, catalog = _selection_catalog(
        terms=_source_projection(
            role="terms",
            lines=(
                "6.1 犹豫期 您可以在犹豫期内申请退保。",
                "解除本合同后我们将退还保险费。",
                boundary,
            ),
            line_bboxes=line_bboxes,
            line_page_numbers=line_page_numbers,
            table_parts=table_parts,
            table_bbox_top=table_bbox_top,
        ),
        brochure=_source_projection(role="brochure", lines=("保障期间",)),
        rate_table=_source_projection(role="rate_table", lines=("可投保职业",)),
    )

    field = catalog.require_field("surrender_and_cancellation_terms")
    clause = next(
        item
        for item in field.selections
        if item.subject_ids == ("span-terms-0", "span-terms-1")
    )
    assert clause.exact_text_parts == (
        "6.1 犹豫期 您可以在犹豫期内申请退保。",
        "解除本合同后我们将退还保险费。",
    )


def test_815_ordinary_text_without_clause_start_remains_atomic() -> None:
    _, catalog = _selection_catalog(
        terms=_source_projection(role="terms", lines=("您可以申请退保并解除本合同。",)),
        brochure=_source_projection(role="brochure", lines=("保障期间",)),
        rate_table=_source_projection(role="rate_table", lines=("可投保职业",)),
    )

    field = catalog.require_field("surrender_and_cancellation_terms")
    assert field.selections[0].subject_ids == ("span-terms-0",)
    assert field.selections[0].exact_text_parts == ("您可以申请退保并解除本合同。",)


def test_815_clause_group_keeps_uniconed_context_inside_preceding_clause() -> None:
    lines = (
        "6.1 犹豫期 您可以在犹豫期内申请退保。",
        "解除本合同后我们将退还保险费。",
        "请注意",
        "您仍可按本合同约定办理退保。",
        "如何退保",
        "6.2 解除合同 您可以在犹豫期后退保。",
    )
    _, catalog = _selection_catalog(
        terms=_source_projection(
            role="terms",
            lines=lines,
            line_bboxes=(
                ("40", "60", "300", "74"),
                ("60", "80", "300", "94"),
                ("60", "100", "300", "114"),
                ("60", "120", "300", "134"),
                ("40", "140", "300", "170"),
                ("40", "180", "300", "194"),
            ),
        ),
        brochure=_source_projection(role="brochure", lines=("保障期间",)),
        rate_table=_source_projection(role="rate_table", lines=("可投保职业",)),
    )

    field = catalog.require_field("surrender_and_cancellation_terms")
    clause = next(
        item
        for item in field.selections
        if item.subject_ids
        == (
            "span-terms-0",
            "span-terms-1",
            "span-terms-2",
            "span-terms-3",
            "span-terms-4",
        )
    )
    assert clause.exact_text_parts == lines[:5]
    assert "如何退保" in clause.exact_text_parts


def test_815_same_left_uniconed_context_does_not_split_preceding_clause() -> None:
    lines = (
        "6.1 犹豫期 您可以在犹豫期内申请退保。",
        "解除本合同后我们将退还保险费。",
        "如何退保",
        "6.2 解除合同 您可以在犹豫期后退保。",
    )
    _, catalog = _selection_catalog(
        terms=_source_projection(
            role="terms",
            lines=lines,
            line_bboxes=(
                ("40", "60", "300", "74"),
                ("40", "80", "300", "94"),
                ("40", "100", "300", "130"),
                ("40", "140", "300", "154"),
            ),
        ),
        brochure=_source_projection(role="brochure", lines=("保障期间",)),
        rate_table=_source_projection(role="rate_table", lines=("可投保职业",)),
    )

    field = catalog.require_field("surrender_and_cancellation_terms")
    clause = next(
        item
        for item in field.selections
        if item.subject_ids == ("span-terms-0", "span-terms-1", "span-terms-2")
    )
    assert clause.exact_text_parts == lines[:3]


def test_815_same_left_short_body_before_ordinary_text_continues_clause() -> None:
    lines = (
        "6.1 犹豫期 您可以在犹豫期内申请退保。",
        "解除本合同后我们将退还保险费。",
        "请注意",
        "您仍可按本合同约定办理退保。",
        "6.2 解除合同 您可以在犹豫期后退保。",
    )
    _, catalog = _selection_catalog(
        terms=_source_projection(
            role="terms",
            lines=lines,
            line_bboxes=(
                ("40", "60", "300", "74"),
                ("40", "80", "300", "94"),
                ("40", "100", "300", "114"),
                ("40", "120", "300", "134"),
                ("40", "140", "300", "154"),
            ),
        ),
        brochure=_source_projection(role="brochure", lines=("保障期间",)),
        rate_table=_source_projection(role="rate_table", lines=("可投保职业",)),
    )

    field = catalog.require_field("surrender_and_cancellation_terms")
    clause = next(
        item
        for item in field.selections
        if item.subject_ids
        == ("span-terms-0", "span-terms-1", "span-terms-2", "span-terms-3")
    )
    assert clause.exact_text_parts == lines[:4]


def test_815_same_left_unpunctuated_body_before_clause_remains_complete() -> None:
    lines = (
        "6.1 犹豫期 您可以在犹豫期内申请退保。",
        "解除本合同后我们将退还保险费。",
        "保险费退还",
        "6.2 解除合同 您可以在犹豫期后退保。",
    )
    _, catalog = _selection_catalog(
        terms=_source_projection(
            role="terms",
            lines=lines,
            line_bboxes=(
                ("40", "60", "300", "74"),
                ("40", "80", "300", "94"),
                ("40", "100", "300", "114"),
                ("40", "120", "300", "134"),
            ),
        ),
        brochure=_source_projection(role="brochure", lines=("保障期间",)),
        rate_table=_source_projection(role="rate_table", lines=("可投保职业",)),
    )

    field = catalog.require_field("surrender_and_cancellation_terms")
    clause = next(
        item
        for item in field.selections
        if item.subject_ids == ("span-terms-0", "span-terms-1", "span-terms-2")
    )
    assert clause.exact_text_parts == lines[:3]


def test_815_clause_group_keeps_large_type_subheading_inside_numbered_clause() -> None:
    lines = (
        "6.1 犹豫期 您可以在犹豫期内申请退保。",
        "解除本合同后我们将退还保险费。",
        "特别约定",
        "后续条件以本合同约定为准。",
        "6.2 解除合同 您可以在犹豫期后退保。",
    )
    _, catalog = _selection_catalog(
        terms=_source_projection(
            role="terms",
            lines=lines,
            line_bboxes=(
                ("40", "60", "300", "74"),
                ("40", "80", "300", "94"),
                ("40", "100", "300", "130"),
                ("40", "140", "300", "154"),
                ("40", "160", "300", "174"),
            ),
        ),
        brochure=_source_projection(role="brochure", lines=("保障期间",)),
        rate_table=_source_projection(role="rate_table", lines=("可投保职业",)),
    )

    field = catalog.require_field("surrender_and_cancellation_terms")
    clause = next(
        item
        for item in field.selections
        if item.subject_ids
        == ("span-terms-0", "span-terms-1", "span-terms-2", "span-terms-3")
    )
    assert clause.exact_text_parts == lines[:4]


def _rebind_admitted_source(
    admitted: AdmittedParseArtifactV1,
    projection: native.NativePdfSelectionProjection815V1,
) -> AdmittedParseArtifactV1:
    page = projection.pages[0]
    text_by_block = {item.parent_block_id: item.exact_text for item in page.spans}
    blocks = tuple(
        ParseBlockV1(
            block_id=item.block_id,
            order_index=item.order_index,
            locator=BlockLocatorV1.model_validate(item.locator.model_dump(mode="python")),
            content_hash=hashlib.sha256(text_by_block[item.block_id].encode()).hexdigest()
            if item.block_id in text_by_block
            else item.content_hash,
            structure_hash=item.structure_hash,
        )
        for item in admitted.document.blocks
    )
    known_block_ids = {item.block_id for item in blocks}
    if projection.pages and blocks:
        template = blocks[0]
        additional = tuple(
            ParseBlockV1(
                block_id=span.parent_block_id,
                order_index=len(blocks) + index,
                locator=BlockLocatorV1(
                    page_number=span.page_number,
                    bbox=template.locator.bbox,
                    block_index=len(blocks) + index,
                ),
                content_hash=hashlib.sha256(span.exact_text.encode()).hexdigest(),
                structure_hash=template.structure_hash,
            )
            for index, span in enumerate(
                span
                for page in projection.pages
                for span in page.spans
                if span.parent_block_id not in known_block_ids
            )
        )
        blocks = (*blocks, *additional)
    cells = tuple(
        ParseCellV1(
            cell_id=item.cell_id,
            order_index=index,
            table_id=item.table_id,
            locator=CellLocatorV1(
                page_number=item.page_number,
                bbox=(
                    Decimal(item.bbox[0]),
                    Decimal(item.bbox[1]),
                    Decimal(item.bbox[2]),
                    Decimal(item.bbox[3]),
                ),
                table_id=item.table_id,
                row_index=item.row_index,
                column_index=item.column_index,
                row_span=1,
                column_span=1,
            ),
            content_hash=item.text_sha256,
            structure_hash=hashlib.sha256(f"structure-{item.cell_id}".encode()).hexdigest(),
        )
        for index, item in enumerate(page.cells)
    )
    tables: tuple[ParseTableV1, ...] = ()
    if cells:
        left = min(item.locator.bbox[0] for item in cells)
        top = min(item.locator.bbox[1] for item in cells)
        right = max(item.locator.bbox[2] for item in cells)
        bottom = max(item.locator.bbox[3] for item in cells)
        table_id = cells[0].table_id
        tables = (
            ParseTableV1(
                table_id=table_id,
                order_index=0,
                locator=TableLocatorV1(
                    page_number=1,
                    table_index=0,
                    bbox=(left, top, right, bottom),
                ),
                content_hash=hashlib.sha256(
                    "\n".join(item.exact_text for item in page.cells).encode()
                ).hexdigest(),
                structure_hash=hashlib.sha256(f"structure-{table_id}".encode()).hexdigest(),
                row_count=max(item.locator.row_index for item in cells) + 1,
                column_count=max(item.locator.column_index for item in cells) + 1,
                header_cell_ids=tuple(
                    item.cell_id for item in cells if item.locator.row_index == 0
                ),
                continuation_table_ids=(),
            ),
        )
    capabilities = admitted.document.capability_evidence
    if tables:
        capabilities = (
            *capabilities,
            CapabilityEvidenceV1(
                capability="table_grid",
                subject_refs=(tables[0].table_id, *(item.cell_id for item in cells)),
            ),
        )
    document_payload = admitted.document.model_dump(
        mode="python", exclude={"document_hash"}
    )
    document_payload.update(
        {
            "pages": admitted.document.pages,
            "blocks": blocks,
            "tables": tables,
            "cells": cells,
            "capability_evidence": capabilities,
        }
    )
    document = ParsedDocumentV1.model_validate(document_payload)
    manifest = ParseManifestV1(
        contract="parse-manifest.v1",
        subject=document.subject,
        parser=document.parser,
        attempt=document.attempt,
        snapshot=document.snapshot,
        output_facts=document.output_facts,
        document_hash=document.document_hash,
        ordered_page_ids=tuple(item.page_id for item in document.pages),
        ordered_block_ids=tuple(item.block_id for item in document.blocks),
        ordered_table_ids=tuple(item.table_id for item in document.tables),
        ordered_cell_ids=tuple(item.cell_id for item in document.cells),
        element_counts=ParseElementCountsV1(
            pages=len(document.pages),
            blocks=len(document.blocks),
            tables=len(document.tables),
            cells=len(document.cells),
        ),
        required_capabilities=admitted.manifest.required_capabilities,
        satisfied_capabilities=admitted.manifest.satisfied_capabilities,
        unsatisfied_capabilities=admitted.manifest.unsatisfied_capabilities,
        capability_evidence=capabilities,
        warnings=document.warnings,
        unsupported=document.unsupported,
    )
    decision_payload = admitted.decision.model_dump(
        mode="python", exclude={"decision_hash"}
    )
    decision_payload["manifest_hash"] = manifest.manifest_hash
    decision = ParseQualityDecisionV1.model_validate(decision_payload)
    return replace(
        admitted,
        source_sha256=document.subject.source_sha256,
        artifact_sha256=document.document_hash,
        document=document,
        manifest=manifest,
        decision=decision,
        manifest_sha256=manifest.manifest_hash,
        decision_sha256=decision.decision_hash,
    )


def _span_hydration_fixture() -> tuple[
    Schema67SelectionCatalog815V1,
    tuple[native.NativePdfSelectionProjection815V1, ...],
    AdmittedParseArtifactV1,
]:
    contracts = fixtures._schema67_contract_set()
    execution = build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=fixtures._execution_plan(contracts),
        available_source_roles=("terms", "brochure", "rate_table"),
    )
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=execution.execution_plan,
        role_inputs=fixtures._schema67_role_inputs(contracts, execution.execution_plan),
    )
    terms_task = next(item for item in prepared if item.task_key == "terms-03")
    _prepared, admitted, _locators = fixtures._admitted_source_for_prepared(terms_task)
    parent_ids = tuple(item.block_id for item in admitted.document.blocks)
    terms = _source_projection(
        role="terms",
        lines=(
            "责任免除 战争责任",
            "责任免除 既往症定义与处理",
            "责任免除 外购药特药责任",
            "补偿原则",
        ),
        parent_block_ids=parent_ids,
        source_revision_id=admitted.document.subject.source_revision_id,
        original_file_sha256=admitted.document.subject.source_sha256,
    )
    admitted = _rebind_admitted_source(admitted, terms)
    sources = (
        terms,
        _source_projection(role="brochure", lines=("保障期间",)),
        _source_projection(role="rate_table", lines=("可投保职业",)),
    )
    catalog = build_field_selection_catalogs_815(
        field_contracts=contracts,
        provider_visible_field_ids=execution.provider_visible_field_ids,
        available_source_roles=("terms", "brochure", "rate_table"),
        source_projections=sources,
    )
    return catalog, sources, admitted


def _complete_eligibility_hydration_fixture() -> tuple[
    Schema67SelectionCatalog815V1,
    tuple[native.NativePdfSelectionProjection815V1, ...],
    AdmittedParseArtifactV1,
]:
    contracts = fixtures._schema67_contract_set()
    execution = build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=fixtures._execution_plan(contracts),
        available_source_roles=("terms", "brochure", "rate_table"),
    )
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=execution.execution_plan,
        role_inputs=fixtures._schema67_role_inputs(contracts, execution.execution_plan),
    )
    source_task = next(item for item in prepared if item.task_key == "terms-02")
    _prepared, admitted, _locators = fixtures._admitted_source_for_prepared(source_task)
    parent_ids = tuple(item.block_id for item in admitted.document.blocks)
    terms = _source_projection(
        role="terms",
        lines=(
            "1.3 投保范围",
            "首次投保年龄为出生满30日至70周岁。",
            "71至100周岁须同时满足以下条件：",
            "（1）既往已经投保；（2）经保险人审核同意。",
            "投保人可为本人、配偶、父母及子女投保。",
            "1.4 健康告知要求。",
        ),
        parent_block_ids=parent_ids,
        source_revision_id=admitted.document.subject.source_revision_id,
        original_file_sha256=admitted.document.subject.source_sha256,
    )
    admitted = _rebind_admitted_source(admitted, terms)
    sources = (
        terms,
        _source_projection(role="brochure", lines=("保障期间",)),
        _source_projection(role="rate_table", lines=("可投保职业",)),
    )
    catalog = build_field_selection_catalogs_815(
        field_contracts=contracts,
        provider_visible_field_ids=execution.provider_visible_field_ids,
        available_source_roles=("terms", "brochure", "rate_table"),
        source_projections=sources,
    )
    return catalog, sources, admitted


def _five_span_clause_hydration_fixture() -> tuple[
    Schema67SelectionCatalog815V1,
    tuple[native.NativePdfSelectionProjection815V1, ...],
    AdmittedParseArtifactV1,
]:
    catalog, sources, admitted = _span_hydration_fixture()
    clause_parts = (
        "6.1 犹豫期 您可以在犹豫期内申请退保。",
        "解除本合同后我们将退还保险费。",
        "退保申请应当按照合同约定提交。",
        "退保金额以保险合同约定为准。",
        "本条款适用于您解除本合同的情形。",
        "6.2 责任免除 战争责任不予赔付。",
    )
    terms = _source_projection(
        role="terms",
        lines=clause_parts,
        parent_block_ids=tuple(f"block-terms-clause-{index}" for index in range(6)),
        source_revision_id=admitted.document.subject.source_revision_id,
        original_file_sha256=admitted.document.subject.source_sha256,
    )
    rebound = _rebind_admitted_source(admitted, terms)
    rebound_sources = (terms, *sources[1:])
    contracts = fixtures._schema67_contract_set()
    execution = build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=fixtures._execution_plan(contracts),
        available_source_roles=("terms", "brochure", "rate_table"),
    )
    return (
        build_field_selection_catalogs_815(
            field_contracts=contracts,
            provider_visible_field_ids=execution.provider_visible_field_ids,
            available_source_roles=("terms", "brochure", "rate_table"),
            source_projections=rebound_sources,
        ),
        rebound_sources,
        rebound,
    )


def _complete_clause_binding_phase_fixture_815(
    span_count: int,
) -> tuple[
    native_selection.ModelTaskSelectionResponse815V1,
    tuple[native_selection.FieldSelectionCatalog815V1, ...],
    tuple[native.NativePdfSelectionProjection815V1, ...],
    AdmittedParseArtifactV1,
    deepseek._Schema67EvidenceBindingPort,
]:
    contracts = fixtures._schema67_contract_set()
    execution = build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=fixtures._execution_plan(contracts),
        available_source_roles=("terms", "brochure", "rate_table"),
    )
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=execution.execution_plan,
        role_inputs=fixtures._schema67_role_inputs(contracts, execution.execution_plan),
    )
    task = next(
        item
        for item in prepared
        if any(
            prompt.field_id == "surrender_and_cancellation_terms"
            for prompt in item.field_prompts
        )
    )
    task, admitted, _locators = fixtures._admitted_source_for_prepared(task)
    lines = (
        "6.1 犹豫期 您可以在犹豫期内申请退保。",
        *(f"退保申请材料与合同解除条件第{index}项。" for index in range(1, span_count)),
        "6.2 责任免除 战争责任不予赔付。",
    )
    parent_block_ids = tuple(
        f"block-terms-phase-{index}" for index in range(len(lines))
    )
    terms = _source_projection(
        role="terms",
        lines=lines,
        parent_block_ids=parent_block_ids,
        source_revision_id=admitted.document.subject.source_revision_id,
        original_file_sha256=admitted.document.subject.source_sha256,
    )
    admitted = _rebind_admitted_source(admitted, terms)
    task = replace(
        task,
        field_prompts=tuple(
            item.model_copy(
                update={"source_locator_refs": (("terms", parent_block_ids[:-1]),)}
            )
            if item.field_id == "surrender_and_cancellation_terms"
            else item
            for item in task.field_prompts
        ),
    )
    sources = (
        terms,
        _source_projection(role="brochure", lines=("保障期间",)),
        _source_projection(role="rate_table", lines=("可投保职业",)),
    )
    catalog = build_field_selection_catalogs_815(
        field_contracts=contracts,
        provider_visible_field_ids=execution.provider_visible_field_ids,
        available_source_roles=("terms", "brochure", "rate_table"),
        source_projections=sources,
    )
    field_catalogs = tuple(
        catalog.require_field(item.field_id) for item in task.field_prompts
    )
    target = catalog.require_field("surrender_and_cancellation_terms")
    selection = next(
        item for item in target.selections if len(item.subject_ids) == span_count
    )
    response = require_model_selection_response_815(
        {
            "task_key": task.task_key,
            "fields": [
                {
                    "field_id": item.field_id,
                    "state": "present"
                    if item.field_id == target.field_id
                    else "unknown",
                    "selection_ids": [selection.selection_id]
                    if item.field_id == target.field_id
                    else [],
                    "typed_reason": None
                    if item.field_id == target.field_id
                    else "ANSWER_NOT_FOUND",
                }
                for item in task.field_prompts
            ],
        },
        task_key=task.task_key,
        field_catalogs=field_catalogs,
    )
    source_task = task.source_tasks[0]
    rebound_task = build_extraction_task(
        space_id=source_task.space_id,
        product_version_id=source_task.product_version_id,
        source_revision_id=source_task.source_revision_id,
        material_role=source_task.material_role,
        module_id=source_task.module_id,
        risk_partition_id=source_task.risk_partition_id,
        field_ids=source_task.field_ids,
        input_refs=source_task.input_refs.model_copy(
            update={
                "parsed_document": source_task.input_refs.parsed_document.model_copy(
                    update={"artifact_hash": admitted.artifact_sha256}
                ),
                "parse_manifest": source_task.input_refs.parse_manifest.model_copy(
                    update={"artifact_hash": admitted.manifest_sha256}
                ),
                "parse_quality_decision": (
                    source_task.input_refs.parse_quality_decision.model_copy(
                        update={"artifact_hash": admitted.decision_sha256}
                    )
                ),
            }
        ),
        budget=source_task.budget,
        task_profile=source_task.task_profile,
    )
    initial_attempt = build_initial_attempt(rebound_task)
    provider_task_sha256 = canonical_hash(
        "schema67-deepseek-provider-task.v1",
        {
            "execution_plan_sha256": task.execution_plan_sha256,
            "task_slice_sha256": task.task_slice_sha256,
            "source_task_hashes": (rebound_task.task_hash,),
            "locator_selection_policy_sha256": deepseek.LOCATOR_SELECTION_POLICY_SHA256,
            "field_prompt_authorities": tuple(
                item.model_dump(mode="python") for item in task.field_prompts
            ),
        },
    )
    task = replace(
        task,
        source_tasks=(rebound_task,),
        initial_attempts=(initial_attempt,),
        provider_task_sha256=provider_task_sha256,
        provider_attempt_sha256=canonical_hash(
            "schema67-deepseek-provider-attempt.v1",
            {
                "provider_task_sha256": provider_task_sha256,
                "source_attempt_hashes": (initial_attempt.attempt_hash,),
            },
        ),
    )
    return (
        response,
        field_catalogs,
        sources,
        admitted,
        deepseek._Schema67EvidenceBindingPort(
            prepared=task,
            admitted_sources=(admitted,),
        ),
    )


def test_815_fresh_phases_bound_all_parsed_identity_hash_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixtures_by_span_count = {
        span_count: _complete_clause_binding_phase_fixture_815(span_count)
        for span_count in (2, 20)
    }
    identity_properties = (
        ("document", ParsedDocumentV1, "document_hash"),
        ("manifest", ParseManifestV1, "manifest_hash"),
        ("decision", ParseQualityDecisionV1, "decision_hash"),
    )
    active_counts: dict[str, dict[int, int]] = {
        name: {} for name, _model, _attribute in identity_properties
    }
    for name, model, attribute in identity_properties:
        descriptor = model.__dict__[attribute]
        assert isinstance(descriptor, property)
        original_getter = cast(Callable[[object], str], descriptor.fget)

        def counted_hash(
            value: object,
            *,
            identity_name: str = name,
            getter: Callable[[object], str] = original_getter,
        ) -> str:
            counts = active_counts[identity_name]
            counts[id(value)] = counts.get(id(value), 0) + 1
            return getter(value)

        monkeypatch.setattr(model, attribute, property(counted_hash))

    totals: dict[tuple[int, str, str], int] = {}
    per_instance_maxima: dict[tuple[int, str, str], int] = {}
    for span_count, fixture in fixtures_by_span_count.items():
        response, field_catalogs, sources, admitted, port = fixture
        for counts in active_counts.values():
            counts.clear()
        outputs, _coordinates, reasons = hydrate_model_selection_response_815(
            response=response,
            field_catalogs=field_catalogs,
            source_projections=sources,
            admitted_sources=(admitted,),
        )
        for name, counts in active_counts.items():
            totals[(span_count, "hydrate", name)] = sum(counts.values())
            per_instance_maxima[(span_count, "hydrate", name)] = max(
                counts.values(), default=0
            )
            counts.clear()
        bound = port.bind_native_selection_outputs(outputs, field_catalogs)
        assert "surrender_and_cancellation_terms" not in {
            field_id for field_id, _reason in reasons
        }
        assert all(reason == "ANSWER_NOT_FOUND" for _field_id, reason in reasons)
        assert all(
            item.status == "PASS"
            for batch in bound.verification_batches
            for item in batch.results
        )
        for name, counts in active_counts.items():
            totals[(span_count, "bind", name)] = sum(counts.values())
            per_instance_maxima[(span_count, "bind", name)] = max(
                counts.values(), default=0
            )

    phase_limits = {
        ("hydrate", "document"): 1,
        ("hydrate", "manifest"): 1,
        ("hydrate", "decision"): 1,
        ("bind", "document"): 3,
        ("bind", "manifest"): 3,
        ("bind", "decision"): 1,
    }
    for phase in ("hydrate", "bind"):
        for name, _model, _attribute in identity_properties:
            assert totals[(20, phase, name)] <= totals[(2, phase, name)], (
                totals,
                per_instance_maxima,
            )
            assert totals[(20, phase, name)] <= phase_limits[(phase, name)], (
                totals,
                phase_limits,
            )
    assert max(per_instance_maxima.values(), default=0) <= 1, (
        totals,
        per_instance_maxima,
    )


def test_815_stale_identity_projection_cannot_mask_a_fresh_rebuilt_document() -> None:
    assert "_expected_source_identities" not in inspect.signature(
        hydrate_model_selection_response_815
    ).parameters
    response, field_catalogs, sources, admitted, _port = (
        _complete_clause_binding_phase_fixture_815(2)
    )
    baseline, _coordinates, reasons = hydrate_model_selection_response_815(
        response=response,
        field_catalogs=field_catalogs,
        source_projections=sources,
        admitted_sources=(admitted,),
    )
    assert "surrender_and_cancellation_terms" not in {
        field_id for field_id, _reason in reasons
    }
    source = admitted
    mutated_document = ParsedDocumentV1.model_validate(
        {
            **source.document.model_dump(mode="python", exclude={"document_hash"}),
            "blocks": (
                source.document.blocks[0].model_copy(update={"structure_hash": "0" * 64}),
                *source.document.blocks[1:],
            ),
        }
    )
    stale_wrapped = replace(source, document=mutated_document)
    with pytest.raises(NativePdfSelectionError815, match="SELECTION_AUTHORITY_INVALID"):
        hydrate_model_selection_response_815(
            response=response,
            field_catalogs=field_catalogs,
            source_projections=sources,
            admitted_sources=(stale_wrapped,),
        )

    mutated_manifest = ParseManifestV1.model_validate(
        {
            **source.manifest.model_dump(mode="python", exclude={"manifest_hash"}),
            "document_hash": mutated_document.document_hash,
        }
    )
    mutated_decision = ParseQualityDecisionV1.model_validate(
        {
            **source.decision.model_dump(mode="python", exclude={"decision_hash"}),
            "manifest_hash": mutated_manifest.manifest_hash,
        }
    )
    rebuilt = replace(
        source,
        artifact_sha256=mutated_document.document_hash,
        document=mutated_document,
        manifest=mutated_manifest,
        manifest_sha256=mutated_manifest.manifest_hash,
        decision=mutated_decision,
        decision_sha256=mutated_decision.decision_hash,
    )

    replayed, _coordinates, replay_reasons = hydrate_model_selection_response_815(
        response=response,
        field_catalogs=field_catalogs,
        source_projections=sources,
        admitted_sources=(rebuilt,),
    )
    assert replay_reasons == reasons
    baseline_target = next(
        item for item in baseline if item.field_id == "surrender_and_cancellation_terms"
    )
    replayed_target = next(
        item for item in replayed if item.field_id == "surrender_and_cancellation_terms"
    )
    assert replayed_target.state == baseline_target.state
    assert replayed_target.value_snapshot == baseline_target.value_snapshot
    assert tuple(item.quote_snapshot for item in replayed_target.evidence) == tuple(
        item.quote_snapshot for item in baseline_target.evidence
    )
    assert {
        (item.parsed_document_hash, item.parse_manifest_hash)
        for item in replayed_target.evidence
    } == {
        (
            rebuilt.artifact_sha256,
            rebuilt.manifest_sha256,
        )
    }


def test_815_concrete_exactification_rejects_identity_model_subclass_extras() -> None:
    class ParsedDocumentWithReviewerExtra(ParsedDocumentV1):
        reviewer_extra: str

    class ParseManifestWithReviewerExtra(ParseManifestV1):
        reviewer_extra: str

    class ParseDecisionWithReviewerExtra(ParseQualityDecisionV1):
        reviewer_extra: str

    response, field_catalogs, sources, admitted, _port = (
        _complete_clause_binding_phase_fixture_815(2)
    )
    extended_document = ParsedDocumentWithReviewerExtra.model_validate(
        {
            **admitted.document.model_dump(mode="python", exclude={"document_hash"}),
            "reviewer_extra": "must-not-enter-authority",
        }
    )
    document_manifest = ParseManifestV1.model_validate(
        {
            **admitted.manifest.model_dump(mode="python", exclude={"manifest_hash"}),
            "document_hash": extended_document.document_hash,
        }
    )
    document_decision = ParseQualityDecisionV1.model_validate(
        {
            **admitted.decision.model_dump(mode="python", exclude={"decision_hash"}),
            "manifest_hash": document_manifest.manifest_hash,
        }
    )
    extended_manifest = ParseManifestWithReviewerExtra.model_validate(
        {
            **admitted.manifest.model_dump(mode="python", exclude={"manifest_hash"}),
            "reviewer_extra": "must-not-enter-authority",
        }
    )
    manifest_decision = ParseQualityDecisionV1.model_validate(
        {
            **admitted.decision.model_dump(mode="python", exclude={"decision_hash"}),
            "manifest_hash": extended_manifest.manifest_hash,
        }
    )
    extended_decision = ParseDecisionWithReviewerExtra.model_validate(
        {
            **admitted.decision.model_dump(mode="python", exclude={"decision_hash"}),
            "reviewer_extra": "must-not-enter-authority",
        }
    )
    subtype_sources = (
        replace(
            admitted,
            artifact_sha256=extended_document.document_hash,
            document=extended_document,
            manifest=document_manifest,
            manifest_sha256=document_manifest.manifest_hash,
            decision=document_decision,
            decision_sha256=document_decision.decision_hash,
        ),
        replace(
            admitted,
            manifest=extended_manifest,
            manifest_sha256=extended_manifest.manifest_hash,
            decision=manifest_decision,
            decision_sha256=manifest_decision.decision_hash,
        ),
        replace(
            admitted,
            decision=extended_decision,
            decision_sha256=extended_decision.decision_hash,
        ),
    )

    for subtype_source in subtype_sources:
        with pytest.raises(
            NativePdfSelectionError815, match="SELECTION_AUTHORITY_INVALID"
        ):
            hydrate_model_selection_response_815(
                response=response,
                field_catalogs=field_catalogs,
                source_projections=sources,
                admitted_sources=(subtype_source,),
            )


def test_815_native_binding_port_exactifies_its_own_admitted_phase() -> None:
    class ParseDecisionWithReviewerExtra(ParseQualityDecisionV1):
        reviewer_extra: str

    response, field_catalogs, sources, admitted, port = (
        _complete_clause_binding_phase_fixture_815(2)
    )
    outputs, _coordinates, _reasons = hydrate_model_selection_response_815(
        response=response,
        field_catalogs=field_catalogs,
        source_projections=sources,
        admitted_sources=(admitted,),
    )
    extended_decision = ParseDecisionWithReviewerExtra.model_validate(
        {
            **admitted.decision.model_dump(mode="python", exclude={"decision_hash"}),
            "reviewer_extra": "must-not-enter-binding-phase",
        }
    )
    unsealed_port = replace(
        port,
        admitted_sources=(
            replace(
                admitted,
                decision=extended_decision,
                decision_sha256=extended_decision.decision_hash,
            ),
        ),
    )

    with pytest.raises(deepseek.DeepSeekCompilerError, match="EVIDENCE_BINDING_FAILED"):
        unsealed_port.bind_native_selection_outputs(outputs, field_catalogs)


def _rehash_selection_815(
    selection: native_selection.NativePdfSelection815V1,
    **updates: object,
) -> native_selection.NativePdfSelection815V1:
    subject_ids = cast(
        tuple[str, ...],
        updates.get("subject_ids", selection.subject_ids),
    )
    exact_text_parts = cast(
        tuple[str, ...],
        updates.get("exact_text_parts", selection.exact_text_parts),
    )
    updates = {
        **updates,
        "value_parts": (
            native_selection._value_part(
                subject_ids=subject_ids,
                exact_text_parts=exact_text_parts,
            ),
        ),
    }
    provisional = replace(
        selection,
        selection_id="pending",
        selection_sha256="pending",
        **updates,  # type: ignore[arg-type]
    )
    digest = provisional.recomputed_selection_sha256()
    return replace(
        provisional,
        selection_id=f"selection-{digest}",
        selection_sha256=digest,
    )


def _rehash_field_catalog_815(
    field: native_selection.FieldSelectionCatalog815V1,
    selections: tuple[native_selection.NativePdfSelection815V1, ...],
) -> native_selection.FieldSelectionCatalog815V1:
    provisional = replace(field, selections=selections, catalog_sha256="pending")
    return replace(provisional, catalog_sha256=provisional.recomputed_catalog_sha256())


def _rehash_projection_815(
    projection: native.NativePdfSelectionProjection815V1,
    *,
    pages: tuple[native.NativePdfPageProjection815V1, ...],
) -> native.NativePdfSelectionProjection815V1:
    provisional = replace(projection, pages=pages, parse_manifest_sha256="")
    return replace(
        provisional,
        parse_manifest_sha256=provisional.recomputed_manifest_sha256(),
    )


class _SelectionResponseTransport815:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        payload = json.loads(user)
        assert "locator_slot_catalog" not in payload
        response_contract = payload["response_contract"]
        assert "value_snapshot" not in response_contract["field_keys"]
        assert response_contract["field_keys"] == [
            "field_id",
            "state",
            "selection_ids",
            "value_part_ids",
            "typed_reason",
        ]
        assert response_contract["fields_container"] == {
            "json_type": "array",
            "ordering": "field_order",
            "object_or_map": "forbidden",
        }
        assert response_contract["state_enum"] == [
            "present",
            "absent_explicitly",
            "unknown",
        ]
        assert response_contract["state_rules"] == {
            "present": {
                "selection_ids": "nonempty_code_issued",
                "value_part_ids": "policy_scoped_code_issued_or_empty",
                "typed_reason": None,
            },
            "absent_explicitly": {
                "selection_ids": "nonempty_code_issued",
                "value_part_ids": "policy_scoped_code_issued_or_empty",
                "typed_reason": None,
            },
            "unknown": {
                "selection_ids": [],
                "value_part_ids": [],
                "typed_reason": "ANSWER_NOT_FOUND",
            },
        }
        assert response_contract["display_policy_rules"] == {
            "EXACT_SHORT": (
                "empty_only_for_single_atomic_group_otherwise_"
                "ordered_group_owned_value_part_ids"
            ),
            "EXTRACTIVE_LONG": (
                "ordered_group_owned_value_part_ids_or_empty_full_group_value"
            ),
        }
        assert "fields as an ordered JSON array, never an object or map" in system
        assert "state must be exactly present, absent_explicitly, or unknown; never known" in system
        assert "typed_reason null" in system
        assert "EXACT_SHORT permits value_part_ids [] only for one atomic part" in system
        assert "multi-part EXACT_SHORT groups require ordered code-issued value_part_ids" in system
        assert "EXTRACTIVE_LONG" in system
        for field_catalog in payload["field_selection_catalogs"]:
            for selection in field_catalog["selections"]:
                assert selection["display_policy"] in {
                    "EXACT_SHORT",
                    "EXTRACTIVE_LONG",
                }
                assert selection["value_parts"]
                assert all(
                    set(part)
                    == {
                        "value_part_id",
                        "exact_text_parts",
                        "value_part_sha256",
                    }
                    for part in selection["value_parts"]
                )
        fields = []
        for item in payload["field_selection_catalogs"]:
            if item["field_id"] == "exclusions":
                fields.append(
                    {
                        "field_id": item["field_id"],
                        "state": "present",
                        "selection_ids": [item["selections"][0]["selection_id"]],
                        "value_part_ids": [],
                        "typed_reason": None,
                    }
                )
            else:
                fields.append(
                    {
                        "field_id": item["field_id"],
                        "state": "unknown",
                        "selection_ids": [],
                        "value_part_ids": [],
                        "typed_reason": "ANSWER_NOT_FOUND",
                    }
                )
        return json.dumps(
            {"task_key": payload["task_key"], "fields": fields},
            ensure_ascii=False,
            separators=(",", ":"),
        )


@pytest.mark.asyncio
async def test_815_selection_response_runs_inside_the_existing_task_loop() -> None:
    catalog, sources, admitted = _span_hydration_fixture()
    contracts = fixtures._schema67_contract_set()
    execution = build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=fixtures._execution_plan(contracts),
        available_source_roles=("terms", "brochure", "rate_table"),
    )
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=execution.execution_plan,
        role_inputs=fixtures._schema67_role_inputs(contracts, execution.execution_plan),
    )
    task = next(item for item in prepared if item.task_key == "terms-03")
    task, _fixture_admitted, locators = fixtures._admitted_source_for_prepared(task)
    terms_projection = next(item for item in sources if item.source_role == "terms")
    text_by_block = {
        item.parent_block_id: item.exact_text
        for page in terms_projection.pages
        for item in page.spans
    }
    locators = tuple(
        item.model_copy(
            update={
                "content_snapshot": text_by_block[item.locator_ref],
                "content_snapshot_sha256": hashlib.sha256(
                    text_by_block[item.locator_ref].encode()
                ).hexdigest(),
            }
        )
        for item in locators
    )
    source_task = task.source_tasks[0]
    source_task = build_extraction_task(
        space_id=source_task.space_id,
        product_version_id=source_task.product_version_id,
        source_revision_id=source_task.source_revision_id,
        material_role=source_task.material_role,
        module_id=source_task.module_id,
        risk_partition_id=source_task.risk_partition_id,
        field_ids=source_task.field_ids,
        input_refs=source_task.input_refs.model_copy(
            update={
                "parsed_document": source_task.input_refs.parsed_document.model_copy(
                    update={"artifact_hash": admitted.document.document_hash}
                ),
                "parse_manifest": source_task.input_refs.parse_manifest.model_copy(
                    update={"artifact_hash": admitted.manifest.manifest_hash}
                ),
                "parse_quality_decision": (
                    source_task.input_refs.parse_quality_decision.model_copy(
                        update={"artifact_hash": admitted.decision.decision_hash}
                    )
                ),
            }
        ),
        budget=source_task.budget,
        task_profile=source_task.task_profile,
    )
    initial_attempt = build_initial_attempt(source_task)
    provider_task_sha256 = canonical_hash(
        "schema67-deepseek-provider-task.v1",
        {
            "execution_plan_sha256": task.execution_plan_sha256,
            "task_slice_sha256": task.task_slice_sha256,
            "source_task_hashes": (source_task.task_hash,),
            "locator_selection_policy_sha256": deepseek.LOCATOR_SELECTION_POLICY_SHA256,
            "field_prompt_authorities": tuple(
                item.model_dump(mode="python") for item in task.field_prompts
            ),
        },
    )
    task = replace(
        task,
        source_tasks=(source_task,),
        initial_attempts=(initial_attempt,),
        provider_task_sha256=provider_task_sha256,
        provider_attempt_sha256=canonical_hash(
            "schema67-deepseek-provider-attempt.v1",
            {
                "provider_task_sha256": provider_task_sha256,
                "source_attempt_hashes": (initial_attempt.attempt_hash,),
            },
        ),
    )
    port = deepseek._Schema67EvidenceBindingPort(
        prepared=task,
        admitted_sources=(admitted,),
    )
    task_catalogs = tuple(catalog.require_field(item.field_id) for item in task.field_prompts)
    transport = _SelectionResponseTransport815()

    result = await deepseek._run_deepseek_task(
        profile=fixtures._profile(),
        policy=fixtures._policy(),
        transport=transport,
        port=port,
        field_contracts=task.field_prompts,
        locators=locators,
        execution_plan_sha256=execution.execution_plan.execution_plan_sha256,
        task_slice_sha256=task.task_slice_sha256,
        task_key=task.task_key,
        _single_pass_mvp=True,
        _selection_authority=(task_catalogs, sources),
    )

    assert result.final_outputs[0].field_id == task.field_prompts[0].field_id
    exclusions = next(item for item in result.final_outputs if item.field_id == "exclusions")
    assert exclusions.state == "present"
    assert exclusions.evidence
    assert result.receipt.extractor_calls == result.receipt.total_calls == 1
    assert result.receipt.response_contract_repairs == 0
    assert result.receipt.evidence_repairs == 0
    assert result.receipt.transport_retries == 0
    assert len(transport.calls) == 1


def test_815_selection_response_rejects_model_supplied_source_content() -> None:
    catalog, _sources, _admitted = _span_hydration_fixture()
    field = catalog.require_field("exclusions")
    base = {
        "field_id": "exclusions",
        "state": "present",
        "selection_ids": [field.selections[0].selection_id],
        "typed_reason": None,
    }

    for forbidden in (
        "value_snapshot",
        "quote_snapshot",
        "bbox",
        "page_text_char_start",
    ):
        with pytest.raises(
            NativePdfSelectionError815,
            match="SELECTION_RESPONSE_SHAPE_INVALID",
        ):
            require_model_selection_response_815(
                {"task_key": "terms-03", "fields": [{**base, forbidden: "invalid"}]},
                task_key="terms-03",
                field_catalogs=(field,),
            )


def test_815_selection_response_state_rules_and_field_set_are_closed() -> None:
    catalog, _sources, _admitted = _span_hydration_fixture()
    exclusions = catalog.require_field("exclusions")
    other = catalog.require_field("pre_existing_condition_rules")

    invalid_fields: tuple[list[dict[str, object]], ...] = (
        [
            {
                "field_id": "exclusions",
                "state": "present",
                "selection_ids": [],
                "typed_reason": None,
            }
        ],
        [
            {
                "field_id": "exclusions",
                "state": "unknown",
                "selection_ids": [exclusions.selections[0].selection_id],
                "typed_reason": "ANSWER_NOT_FOUND",
            }
        ],
        [
            {
                "field_id": "exclusions",
                "state": "unknown",
                "selection_ids": [],
                "typed_reason": "UNRECOGNIZED",
            }
        ],
        [
            {
                "field_id": "exclusions",
                "state": "unknown",
                "selection_ids": [],
                "typed_reason": "ANSWER_NOT_FOUND",
            },
            {
                "field_id": "exclusions",
                "state": "unknown",
                "selection_ids": [],
                "typed_reason": "ANSWER_NOT_FOUND",
            },
        ],
    )
    for fields in invalid_fields:
        with pytest.raises(
            NativePdfSelectionError815,
            match="SELECTION_RESPONSE_SHAPE_INVALID",
        ):
            require_model_selection_response_815(
                {"task_key": "terms-03", "fields": fields},
                task_key="terms-03",
                field_catalogs=(exclusions, other),
            )

    response = require_model_selection_response_815(
        {
            "task_key": "terms-03",
            "fields": [
                {
                    "field_id": "exclusions",
                    "state": "unknown",
                    "selection_ids": [],
                    "typed_reason": "ANSWER_NOT_FOUND",
                }
            ],
        },
        task_key="terms-03",
        field_catalogs=(exclusions,),
    )
    assert response.fields[0].typed_reason == "ANSWER_NOT_FOUND"

    absent = require_model_selection_response_815(
        {
            "task_key": "terms-03",
            "fields": [
                {
                    "field_id": "exclusions",
                    "state": "absent_explicitly",
                    "selection_ids": [exclusions.selections[0].selection_id],
                    "typed_reason": None,
                }
            ],
        },
        task_key="terms-03",
        field_catalogs=(exclusions,),
    )
    assert absent.fields[0].state == "absent_explicitly"
    assert absent.fields[0].typed_reason is None


@pytest.mark.parametrize(
    "fields",
    (
        {
            "exclusions": {
                "state": "present",
                "selection_ids": ["sanitized-selection-id"],
                "typed_reason": None,
            }
        },
        [
            {
                "field_id": "exclusions",
                "state": "known",
                "selection_ids": ["sanitized-selection-id"],
                "typed_reason": "ANSWER_FOUND",
            }
        ],
    ),
)
def test_815_selection_response_rejects_sanitized_real_failure_shapes(
    fields: object,
) -> None:
    catalog, _sources, _admitted = _span_hydration_fixture()
    exclusions = catalog.require_field("exclusions")

    with pytest.raises(
        NativePdfSelectionError815,
        match="SELECTION_RESPONSE_SHAPE_INVALID",
    ):
        require_model_selection_response_815(
            {"task_key": "terms-03", "fields": fields},
            task_key="terms-03",
            field_catalogs=(exclusions,),
        )


def test_815_selection_hydration_joins_spans_in_document_order() -> None:
    catalog, sources, admitted = _span_hydration_fixture()
    field = catalog.require_field("exclusions")
    selected_ids = tuple(item.selection_id for item in reversed(field.selections[:3]))
    response = require_model_selection_response_815(
        {
            "task_key": "terms-03",
            "fields": [
                {
                    "field_id": "exclusions",
                    "state": "present",
                    "selection_ids": selected_ids,
                    "typed_reason": None,
                }
            ],
        },
        task_key="terms-03",
        field_catalogs=(field,),
    )

    outputs, coordinates, reasons = hydrate_model_selection_response_815(
        response=response,
        field_catalogs=(field,),
        source_projections=sources,
        admitted_sources=(admitted,),
    )

    assert outputs[0].value_snapshot == "\N{LINE SEPARATOR}".join(
        item.exact_text_parts[0] for item in field.selections[:3]
    )
    assert len(outputs[0].evidence) == 3
    assert len(coordinates) == 3
    assert reasons == ()

    companion = make_coordinate_evidence_companion_815(
        candidate_sha256="a" * 64,
        selection_catalog=catalog,
        source_projections=sources,
        coordinate_rows=coordinates,
    )
    assert companion.candidate_sha256 == "a" * 64
    assert companion.companion_sha256 == companion.recomputed_companion_sha256()
    with pytest.raises(ValueError, match="coordinate Evidence companion invalid"):
        CoordinateEvidenceCompanion815V1.model_validate(
            {
                **companion.model_dump(mode="python"),
                "candidate_sha256": "b" * 64,
            }
        )


def test_815_selected_value_parts_narrow_value_evidence_and_coordinates() -> None:
    catalog, sources, admitted = _complete_eligibility_hydration_fixture()
    eligibility = catalog.require_field("insured_eligibility")
    group = eligibility.selections[0]
    assert group.display_policy == "EXTRACTIVE_LONG"
    selected_parts = (group.value_parts[0], group.value_parts[-1])
    response = require_model_selection_response_815(
        {
            "task_key": "terms-02",
            "fields": [
                {
                    "field_id": eligibility.field_id,
                    "state": "present",
                    "selection_ids": [group.selection_id],
                    "value_part_ids": [item.value_part_id for item in selected_parts],
                    "typed_reason": None,
                }
            ],
        },
        task_key="terms-02",
        field_catalogs=(eligibility,),
    )

    outputs, coordinates, reasons = hydrate_model_selection_response_815(
        response=response,
        field_catalogs=(eligibility,),
        source_projections=sources,
        admitted_sources=(admitted,),
    )

    selected_exact_text = tuple(
        text for part in selected_parts for text in part.exact_text_parts
    )
    assert outputs[0].value_snapshot == "\N{LINE SEPARATOR}".join(selected_exact_text)
    assert {item.quote_snapshot for item in outputs[0].evidence} == set(
        selected_exact_text
    )
    assert len(outputs[0].evidence) == len(selected_exact_text)
    assert tuple(item.quote for item in coordinates) == selected_exact_text
    assert set(selected_exact_text) < set(group.exact_text_parts)
    assert reasons == ()


def test_815_code_issued_wrapped_paragraph_hydrates_from_complete_group() -> None:
    contracts = fixtures._schema67_contract_set()
    execution = build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=fixtures._execution_plan(contracts),
        available_source_roles=("terms", "brochure", "rate_table"),
    )
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=execution.execution_plan,
        role_inputs=fixtures._schema67_role_inputs(contracts, execution.execution_plan),
    )
    terms_task = next(item for item in prepared if item.task_key == "terms-01")
    _prepared, admitted, _locators = fixtures._admitted_source_for_prepared(terms_task)
    expected_parts = (
        "您可以同时为符合我们承保条件的家庭成员投保本产品，家庭成员仅指投保",
        "人本人、投保时与投保人具有合法婚姻关系的配偶、投保人的父母以及投保",
        "人的子女。",
    )
    terms = _source_projection(
        role="terms",
        lines=(
            "1.3 投保范围 本合同接受的被保险人投保年龄为0周岁至70周岁，且须",
            "符合投保当时我们的规定。",
            *expected_parts,
            "1.4 健康告知要求。",
        ),
        line_bboxes=(
            ("40", "60", "560", "74"),
            ("40", "80", "560", "94"),
            ("40", "130", "560", "144"),
            ("40", "150", "560", "164"),
            ("40", "170", "300", "184"),
            ("40", "210", "300", "224"),
        ),
        parent_block_ids=tuple(f"block-terms-wrapped-{index}" for index in range(6)),
        source_revision_id=admitted.document.subject.source_revision_id,
        original_file_sha256=admitted.document.subject.source_sha256,
    )
    admitted = _rebind_admitted_source(admitted, terms)
    sources = (
        terms,
        _source_projection(role="brochure", lines=("保障期间",)),
        _source_projection(role="rate_table", lines=("可投保职业",)),
    )
    catalog = build_field_selection_catalogs_815(
        field_contracts=contracts,
        provider_visible_field_ids=execution.provider_visible_field_ids,
        available_source_roles=("terms", "brochure", "rate_table"),
        source_projections=sources,
    )
    eligibility = catalog.require_field("insured_eligibility")
    paragraph = next(
        item for item in eligibility.selections if item.exact_text_parts == expected_parts
    )
    page = terms.pages[0]
    assert any(
        tuple(span.span_id for span in group.spans) == paragraph.subject_ids
        for group in native_selection._complete_clause_groups_815(page)
    )
    assert not any(
        tuple(span.span_id for span in group) == paragraph.subject_ids
        for group in native_selection._contiguous_clause_groups_815(page)
    )
    response = require_model_selection_response_815(
        {
            "task_key": terms_task.task_key,
            "fields": [
                {
                    "field_id": eligibility.field_id,
                    "state": "present",
                    "selection_ids": [paragraph.selection_id],
                    "value_part_ids": [paragraph.value_parts[0].value_part_id],
                    "typed_reason": None,
                }
            ],
        },
        task_key=terms_task.task_key,
        field_catalogs=(eligibility,),
    )

    outputs, coordinates, reasons = hydrate_model_selection_response_815(
        response=response,
        field_catalogs=(eligibility,),
        source_projections=sources,
        admitted_sources=(admitted,),
    )

    assert outputs[0].state == "present"
    assert outputs[0].value_snapshot == native_selection._VALUE_PART_SEPARATOR_815.join(
        expected_parts
    )
    assert tuple(item.quote_snapshot for item in outputs[0].evidence) == expected_parts
    assert tuple(item.quote for item in coordinates) == expected_parts
    assert reasons == ()


def test_815_indemnity_part_keeps_only_its_exact_1_7_evidence_coordinates() -> None:
    contracts = fixtures._schema67_contract_set()
    execution = build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=fixtures._execution_plan(contracts),
        available_source_roles=("terms", "brochure", "rate_table"),
    )
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=execution.execution_plan,
        role_inputs=fixtures._schema67_role_inputs(contracts, execution.execution_plan),
    )
    terms_task = next(item for item in prepared if item.task_key == "terms-03")
    _prepared, admitted, _locators = fixtures._admitted_source_for_prepared(terms_task)
    parent_ids = tuple(item.block_id for item in admitted.document.blocks)
    terms = _source_projection(
        role="terms",
        lines=(
            "1.7 补偿原则。",
            "已从其他途径获得补偿的，仅赔付剩余部分。",
            "1.8 免赔额。",
            "本合同约定免赔额为一万元。",
        ),
        parent_block_ids=parent_ids,
        source_revision_id=admitted.document.subject.source_revision_id,
        original_file_sha256=admitted.document.subject.source_sha256,
    )
    admitted = _rebind_admitted_source(admitted, terms)
    sources = (
        terms,
        _source_projection(role="brochure", lines=("保障期间",)),
        _source_projection(role="rate_table", lines=("可投保职业",)),
    )
    catalog = build_field_selection_catalogs_815(
        field_contracts=contracts,
        provider_visible_field_ids=execution.provider_visible_field_ids,
        available_source_roles=("terms", "brochure", "rate_table"),
        source_projections=sources,
    )
    indemnity = catalog.require_field("indemnity_principle")
    group = next(
        item for item in indemnity.selections if item.exact_text_parts[0] == "1.7 补偿原则。"
    )
    selected_part = group.value_parts[-1]
    response = require_model_selection_response_815(
        {
            "task_key": terms_task.task_key,
            "fields": [
                {
                    "field_id": indemnity.field_id,
                    "state": "present",
                    "selection_ids": [group.selection_id],
                    "value_part_ids": [selected_part.value_part_id],
                    "typed_reason": None,
                }
            ],
        },
        task_key=terms_task.task_key,
        field_catalogs=(indemnity,),
    )

    outputs, coordinates, reasons = hydrate_model_selection_response_815(
        response=response,
        field_catalogs=(indemnity,),
        source_projections=sources,
        admitted_sources=(admitted,),
    )

    assert selected_part.exact_text_parts == (
        "已从其他途径获得补偿的，仅赔付剩余部分。",
    )
    assert outputs[0].value_snapshot == selected_part.exact_text_parts[0]
    assert tuple(item.quote_snapshot for item in outputs[0].evidence) == (
        selected_part.exact_text_parts
    )
    assert tuple(item.quote for item in coordinates) == selected_part.exact_text_parts
    assert "1.7 补偿原则。" not in tuple(item.quote for item in coordinates)
    assert reasons == ()


def test_815_exact_short_multi_part_group_requires_explicit_field_local_parts() -> None:
    contracts = fixtures._schema67_contract_set()
    execution = build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=fixtures._execution_plan(contracts),
        available_source_roles=("terms", "brochure", "rate_table"),
    )
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=execution.execution_plan,
        role_inputs=fixtures._schema67_role_inputs(contracts, execution.execution_plan),
    )
    terms_task = next(
        item
        for item in prepared
        if "waiting_period" in tuple(field.field_id for field in item.field_prompts)
    )
    _prepared, admitted, _locators = fixtures._admitted_source_for_prepared(terms_task)
    parent_ids = tuple(item.block_id for item in admitted.document.blocks)
    terms = _source_projection(
        role="terms",
        lines=(
            "1.5.1 等待期 自合同生效之日起30日。",
            "以下情形无等待期。",
            "1.5.2 一般医疗保险金。",
        ),
        parent_block_ids=parent_ids[:3],
        source_revision_id=admitted.document.subject.source_revision_id,
        original_file_sha256=admitted.document.subject.source_sha256,
    )
    admitted = _rebind_admitted_source(admitted, terms)
    sources = (
        terms,
        _source_projection(role="brochure", lines=("保障期间",)),
        _source_projection(role="rate_table", lines=("可投保职业",)),
    )
    catalog = build_field_selection_catalogs_815(
        field_contracts=contracts,
        provider_visible_field_ids=execution.provider_visible_field_ids,
        available_source_roles=("terms", "brochure", "rate_table"),
        source_projections=sources,
    )
    waiting_period = catalog.require_field("waiting_period")
    group = waiting_period.selections[0]
    assert group.display_policy == "EXACT_SHORT"
    assert len(group.value_parts) == 2

    empty_parts = require_model_selection_response_815(
        {
            "task_key": terms_task.task_key,
            "fields": [
                {
                    "field_id": waiting_period.field_id,
                    "state": "present",
                    "selection_ids": [group.selection_id],
                    "value_part_ids": [],
                    "typed_reason": None,
                }
            ],
        },
        task_key=terms_task.task_key,
        field_catalogs=(waiting_period,),
    )
    empty_outputs, empty_coordinates, empty_reasons = (
        hydrate_model_selection_response_815(
            response=empty_parts,
            field_catalogs=(waiting_period,),
            source_projections=sources,
            admitted_sources=(admitted,),
        )
    )
    assert empty_outputs[0].state == "unknown"
    assert empty_outputs[0].value_snapshot is None
    assert empty_outputs[0].evidence == ()
    assert empty_coordinates == ()
    assert empty_reasons == (("waiting_period", "SOURCE_LOCATION_UNRESOLVED"),)

    selected_part = group.value_parts[0]
    explicit_part = require_model_selection_response_815(
        {
            "task_key": terms_task.task_key,
            "fields": [
                {
                    "field_id": waiting_period.field_id,
                    "state": "present",
                    "selection_ids": [group.selection_id],
                    "value_part_ids": [selected_part.value_part_id],
                    "typed_reason": None,
                }
            ],
        },
        task_key=terms_task.task_key,
        field_catalogs=(waiting_period,),
    )
    outputs, coordinates, reasons = hydrate_model_selection_response_815(
        response=explicit_part,
        field_catalogs=(waiting_period,),
        source_projections=sources,
        admitted_sources=(admitted,),
    )
    assert outputs[0].state == "present"
    assert outputs[0].value_snapshot == "\N{LINE SEPARATOR}".join(
        selected_part.exact_text_parts
    )
    assert tuple(item.quote_snapshot for item in outputs[0].evidence) == (
        selected_part.exact_text_parts
    )
    assert tuple(item.quote for item in coordinates) == selected_part.exact_text_parts
    assert reasons == ()


def test_815_cross_field_value_part_demotes_only_its_field() -> None:
    catalog, sources, admitted = _complete_eligibility_hydration_fixture()
    eligibility = catalog.require_field("insured_eligibility")
    health = catalog.require_field("health_declaration_requirements")
    eligibility_group = eligibility.selections[0]
    health_group = health.selections[0]
    response = require_model_selection_response_815(
        {
            "task_key": "terms-02",
            "fields": [
                {
                    "field_id": eligibility.field_id,
                    "state": "present",
                    "selection_ids": [eligibility_group.selection_id],
                    "value_part_ids": [health_group.value_parts[0].value_part_id],
                    "typed_reason": None,
                },
                {
                    "field_id": health.field_id,
                    "state": "present",
                    "selection_ids": [health_group.selection_id],
                    "value_part_ids": [],
                    "typed_reason": None,
                },
            ],
        },
        task_key="terms-02",
        field_catalogs=(eligibility, health),
    )

    outputs, coordinates, reasons = hydrate_model_selection_response_815(
        response=response,
        field_catalogs=(eligibility, health),
        source_projections=sources,
        admitted_sources=(admitted,),
    )

    assert outputs[0].state == "unknown"
    assert outputs[0].value_snapshot is None
    assert outputs[0].evidence == ()
    assert outputs[1].state == "present"
    assert all(item.field_id == outputs[1].field_id for item in coordinates)
    assert reasons == ((eligibility.field_id, "SOURCE_LOCATION_UNRESOLVED"),)


def test_815_multi_span_clause_hydrates_ordered_exact_evidence() -> None:
    catalog, sources, admitted = _five_span_clause_hydration_fixture()
    field = catalog.require_field("surrender_and_cancellation_terms")
    parent = next(item for item in field.selections if len(item.subject_ids) == 5)
    response = require_model_selection_response_815(
        {
            "task_key": "terms-03",
            "fields": [
                {
                    "field_id": field.field_id,
                    "state": "present",
                    "selection_ids": [parent.selection_id],
                    "typed_reason": None,
                }
            ],
        },
        task_key="terms-03",
        field_catalogs=(field,),
    )

    outputs, coordinates, reasons = hydrate_model_selection_response_815(
        response=response,
        field_catalogs=(field,),
        source_projections=sources,
        admitted_sources=(admitted,),
    )

    assert outputs[0].state == "present"
    assert outputs[0].value_snapshot == native_selection._VALUE_PART_SEPARATOR_815.join(
        parent.exact_text_parts
    )
    assert "\n" not in outputs[0].value_snapshot
    assert tuple(sorted(outputs[0].evidence, key=evidence_verifier._freeform_evidence_key)) == (
        outputs[0].evidence
    )
    assert {item.quote_snapshot for item in outputs[0].evidence} == set(
        parent.exact_text_parts
    )
    assert len(coordinates) == len(parent.subject_ids) == 5
    assert len({item.selection_id for item in coordinates}) == 5
    spans_by_id = {
        span.span_id: span for page in sources[0].pages for span in page.spans
    }
    assert tuple(item.selection_id for item in coordinates) == tuple(
        "selection-"
        + canonical_hash(
            "schema67-coordinate-child-selection.815.v1",
            {
                "parent_selection_id": parent.selection_id,
                "field_id": parent.field_id,
                "ordinal": ordinal,
                "span_id": spans_by_id[span_id].span_id,
                "page_number": spans_by_id[span_id].page_number,
                "char_start": spans_by_id[span_id].char_start,
                "char_end": spans_by_id[span_id].char_end,
                "quote_sha256": spans_by_id[span_id].text_sha256,
            },
        )
        for ordinal, span_id in enumerate(parent.subject_ids)
    )
    assert reasons == ()


@pytest.mark.parametrize(
    "failure",
    (
        "middle_span_deleted",
        "duplicate_subject",
        "order_swap",
        "page_drift",
        "char_range_drift",
        "quote_drift",
        "rect_word_drift",
        "rect_drift",
        "foreign_subject",
        "new_clause",
        "section_icon",
        "toc",
        "bottom_page_number",
        "table_overlap",
        "geometry_rewind",
        "visual_gap",
    ),
)
def test_815_multi_span_hydration_fails_closed_only_for_mutated_field(
    failure: str,
) -> None:
    catalog, sources, admitted = _five_span_clause_hydration_fixture()
    original_terms = sources[0]
    target = catalog.require_field("surrender_and_cancellation_terms")
    neighbor = catalog.require_field("exclusions")
    parent = next(item for item in target.selections if len(item.subject_ids) == 5)
    neighbor_selection = neighbor.selections[0]
    terms = original_terms
    source_rebound = False

    if failure == "middle_span_deleted":
        page = original_terms.pages[0]
        terms = _rehash_projection_815(
            original_terms,
            pages=(replace(page, spans=(*page.spans[:2], *page.spans[3:])),),
        )
        source_rebound = True
    elif failure == "char_range_drift":
        page = original_terms.pages[0]
        drifted = replace(page.spans[2], char_start=page.spans[2].char_start + 1)
        terms = _rehash_projection_815(
            original_terms,
            pages=(replace(page, spans=(*page.spans[:2], drifted, *page.spans[3:])),),
        )
        source_rebound = True
    elif failure == "quote_drift":
        page = original_terms.pages[0]
        quote = "退保申请应当按照合同约定递交。"
        drifted = replace(
            page.spans[2],
            exact_text=quote,
            text_sha256=hashlib.sha256(quote.encode()).hexdigest(),
        )
        terms = _rehash_projection_815(
            original_terms,
            pages=(replace(page, spans=(*page.spans[:2], drifted, *page.spans[3:])),),
        )
        source_rebound = True
    elif failure == "rect_drift":
        page = original_terms.pages[0]
        drifted = replace(page.spans[2], rects=(("40", "160", "300", "174"),))
        terms = _rehash_projection_815(
            original_terms,
            pages=(replace(page, spans=(*page.spans[:2], drifted, *page.spans[3:])),),
        )
        source_rebound = True
    elif failure == "rect_word_drift":
        page = original_terms.pages[0]
        drifted = replace(page.spans[2], rects=(("41", "100", "300", "114"),))
        terms = _rehash_projection_815(
            original_terms,
            pages=(replace(page, spans=(*page.spans[:2], drifted, *page.spans[3:])),),
        )
        source_rebound = True
    elif failure in {
        "new_clause",
        "section_icon",
        "toc",
        "bottom_page_number",
        "table_overlap",
        "geometry_rewind",
        "visual_gap",
    }:
        lines = list(item.exact_text for item in original_terms.pages[0].spans)
        bboxes: tuple[native.NativeBBox, ...] | None = None
        table_parts: tuple[str, ...] = ()
        if failure == "new_clause":
            lines[2] = "6.2 解除合同 您可以在犹豫期后退保。"
        elif failure == "section_icon":
            lines[2] = "① 退保手续"
        elif failure == "toc":
            lines[2] = "退保说明........................6.2"
        elif failure == "bottom_page_number":
            lines[2] = "26"
            bboxes = (
                ("40", "60", "300", "74"),
                ("40", "80", "300", "94"),
                ("40", "700", "300", "714"),
                ("40", "120", "300", "134"),
                ("40", "140", "300", "154"),
                ("40", "180", "300", "194"),
            )
        elif failure == "table_overlap":
            lines[2] = "退保表格重叠行"
            bboxes = (
                ("40", "60", "300", "74"),
                ("40", "80", "300", "94"),
                ("40", "205", "300", "219"),
                ("40", "120", "300", "134"),
                ("40", "140", "300", "154"),
                ("40", "180", "300", "194"),
            )
            table_parts = ("退保", "办理条件", "犹豫期", "合同解除")
        elif failure == "geometry_rewind":
            bboxes = (
                ("40", "60", "300", "74"),
                ("40", "80", "300", "94"),
                ("40", "70", "300", "84"),
                ("40", "120", "300", "134"),
                ("40", "140", "300", "154"),
                ("40", "180", "300", "194"),
            )
        elif failure == "visual_gap":
            bboxes = (
                ("40", "60", "300", "74"),
                ("40", "80", "300", "94"),
                ("40", "160", "300", "174"),
                ("40", "180", "300", "194"),
                ("40", "200", "300", "214"),
                ("40", "240", "300", "254"),
            )
        terms = _source_projection(
            role="terms",
            lines=tuple(lines),
            line_bboxes=bboxes,
            table_parts=table_parts,
            parent_block_ids=tuple(
                item.parent_block_id for item in original_terms.pages[0].spans
            ),
            source_revision_id=original_terms.source_revision_id,
            original_file_sha256=original_terms.original_file_sha256,
        )
        source_rebound = True

    active_sources = (terms, *sources[1:])
    active_admitted = _rebind_admitted_source(admitted, terms) if source_rebound else admitted
    live_spans = {item.span_id: item for item in terms.pages[0].spans}
    parent_subject_ids = parent.subject_ids
    if failure == "duplicate_subject":
        parent_subject_ids = (
            *parent.subject_ids[:2],
            parent.subject_ids[1],
            *parent.subject_ids[2:],
        )
    elif failure == "order_swap":
        parent_subject_ids = (parent.subject_ids[1], parent.subject_ids[0], *parent.subject_ids[2:])
    elif failure == "foreign_subject":
        parent_subject_ids = (*parent.subject_ids[:4], "span-brochure-0")
    parent_parts = tuple(
        live_spans[item].exact_text if item in live_spans else "保障期间"
        for item in parent_subject_ids
    )
    parent_pages = (2,) if failure == "page_drift" else (1,)
    target_selection = _rehash_selection_815(
        parent,
        subject_ids=parent_subject_ids,
        page_numbers=parent_pages,
        exact_text_parts=parent_parts,
        parse_manifest_sha256=terms.parse_manifest_sha256,
    )
    neighbor_rebound = _rehash_selection_815(
        neighbor_selection,
        parse_manifest_sha256=terms.parse_manifest_sha256,
    )
    target_catalog = _rehash_field_catalog_815(target, (target_selection,))
    neighbor_catalog = _rehash_field_catalog_815(neighbor, (neighbor_rebound,))
    response = require_model_selection_response_815(
        {
            "task_key": "terms-03",
            "fields": [
                {
                    "field_id": target.field_id,
                    "state": "present",
                    "selection_ids": [target_selection.selection_id],
                    "typed_reason": None,
                },
                {
                    "field_id": neighbor.field_id,
                    "state": "present",
                    "selection_ids": [neighbor_rebound.selection_id],
                    "typed_reason": None,
                },
            ],
        },
        task_key="terms-03",
        field_catalogs=(target_catalog, neighbor_catalog),
    )

    outputs, coordinates, reasons = hydrate_model_selection_response_815(
        response=response,
        field_catalogs=(target_catalog, neighbor_catalog),
        source_projections=active_sources,
        admitted_sources=(active_admitted,),
    )

    assert outputs[0].state == "unknown"
    assert outputs[0].value_snapshot is None
    assert outputs[0].evidence == ()
    assert outputs[1].state == "present"
    assert outputs[1].evidence
    assert tuple(item.field_id for item in coordinates) == (neighbor.field_id,)
    assert reasons == ((target.field_id, "SOURCE_LOCATION_UNRESOLVED"),)


def test_815_field_local_invalid_selection_demotes_only_that_field() -> None:
    catalog, sources, admitted = _span_hydration_fixture()
    exclusions = catalog.require_field("exclusions")
    other = catalog.require_field("pre_existing_condition_rules")
    response = require_model_selection_response_815(
        {
            "task_key": "terms-03",
            "fields": [
                {
                    "field_id": "exclusions",
                    "state": "present",
                    "selection_ids": [other.selections[0].selection_id],
                    "typed_reason": None,
                },
                {
                    "field_id": "pre_existing_condition_rules",
                    "state": "present",
                    "selection_ids": [other.selections[0].selection_id],
                    "typed_reason": None,
                },
            ],
        },
        task_key="terms-03",
        field_catalogs=(exclusions, other),
    )

    outputs, coordinates, reasons = hydrate_model_selection_response_815(
        response=response,
        field_catalogs=(exclusions, other),
        source_projections=sources,
        admitted_sources=(admitted,),
    )

    assert outputs[0].state == "unknown"
    assert outputs[0].value_snapshot is None
    assert outputs[0].evidence == ()
    assert outputs[1].state == "present"
    assert all(item.field_id == outputs[1].field_id for item in coordinates)
    assert reasons == (("exclusions", "SOURCE_LOCATION_UNRESOLVED"),)


def test_815_selected_table_slice_expands_to_ordered_cell_evidence() -> None:
    contracts = fixtures._schema67_contract_set()
    execution = build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=fixtures._execution_plan(contracts),
        available_source_roles=("terms", "brochure", "rate_table"),
    )
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=execution.execution_plan,
        role_inputs=fixtures._schema67_role_inputs(contracts, execution.execution_plan),
    )
    rate_task = next(item for item in prepared if item.task_key == "rate_table-01")
    _prepared, admitted, _locators = fixtures._admitted_source_for_prepared(rate_task)
    rate = _source_projection(
        role="rate_table",
        table_parts=("可投保职业", "类别", "1", "医疗"),
        source_revision_id=admitted.document.subject.source_revision_id,
        original_file_sha256=admitted.document.subject.source_sha256,
    )
    admitted = _rebind_admitted_source(admitted, rate)
    sources = (
        _source_projection(role="terms", lines=("责任免除",)),
        _source_projection(role="brochure", lines=("保障期间",)),
        rate,
    )
    catalog = build_field_selection_catalogs_815(
        field_contracts=contracts,
        provider_visible_field_ids=execution.provider_visible_field_ids,
        available_source_roles=("terms", "brochure", "rate_table"),
        source_projections=sources,
    )
    field = catalog.require_field("eligible_occupation_classes")
    response = require_model_selection_response_815(
        {
            "task_key": "rate_table-01",
            "fields": [
                {
                    "field_id": field.field_id,
                    "state": "present",
                    "selection_ids": [field.selections[0].selection_id],
                    "typed_reason": None,
                }
            ],
        },
        task_key="rate_table-01",
        field_catalogs=(field,),
    )

    outputs, coordinates, reasons = hydrate_model_selection_response_815(
        response=response,
        field_catalogs=(field,),
        source_projections=sources,
        admitted_sources=(admitted,),
    )

    assert tuple(item.quote_snapshot for item in outputs[0].evidence) == (
        "可投保职业",
        "类别",
        "1",
        "医疗",
    )
    assert outputs[0].value_snapshot == "\N{LINE SEPARATOR}".join(
        field.selections[0].exact_text_parts
    )
    assert coordinates[0].cell_ids == tuple(item.cell_id for item in rate.pages[0].cells)
    assert reasons == ()

    explicit_atomic_part_selection = require_model_selection_response_815(
        {
            "task_key": "rate_table-01",
            "fields": [
                {
                    "field_id": field.field_id,
                    "state": "present",
                    "selection_ids": [field.selections[0].selection_id],
                    "value_part_ids": [field.selections[0].value_parts[0].value_part_id],
                    "typed_reason": None,
                }
            ],
        },
        task_key="rate_table-01",
        field_catalogs=(field,),
    )
    explicit_outputs, explicit_coordinates, explicit_reasons = (
        hydrate_model_selection_response_815(
            response=explicit_atomic_part_selection,
            field_catalogs=(field,),
            source_projections=sources,
            admitted_sources=(admitted,),
        )
    )
    assert explicit_outputs[0] == outputs[0]
    assert explicit_coordinates == coordinates
    assert explicit_reasons == ()


def test_815_overlapping_table_selections_stably_deduplicate_shared_evidence() -> None:
    contracts = fixtures._schema67_contract_set()
    execution = build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=fixtures._execution_plan(contracts),
        available_source_roles=("terms", "brochure", "rate_table"),
    )
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=execution.execution_plan,
        role_inputs=fixtures._schema67_role_inputs(contracts, execution.execution_plan),
    )
    terms_task = next(item for item in prepared if item.task_key == "terms-04")
    _prepared, admitted, _locators = fixtures._admitted_source_for_prepared(terms_task)
    terms = _source_projection(
        role="terms",
        lines=("免赔额为一万元",),
        table_parts=("报销比例", "适用条件", "有医保", "100%", "无医保", "60%"),
        parent_block_ids=(admitted.document.blocks[0].block_id,),
        source_revision_id=admitted.document.subject.source_revision_id,
        original_file_sha256=admitted.document.subject.source_sha256,
    )
    page = terms.pages[0]
    slices = (
        native.NativeTableSlice815V1(
            table_slice_id="table-slice-terms-insured",
            table_id="table-terms",
            page_numbers=(1,),
            ordered_cell_ids=tuple(item.cell_id for item in page.cells[:4]),
            exact_text_parts=tuple(item.exact_text for item in page.cells[:4]),
            slice_sha256=hashlib.sha256(b"table-slice-terms-insured").hexdigest(),
        ),
        native.NativeTableSlice815V1(
            table_slice_id="table-slice-terms-uninsured",
            table_id="table-terms",
            page_numbers=(1,),
            ordered_cell_ids=tuple(
                item.cell_id for item in (*page.cells[:2], *page.cells[4:])
            ),
            exact_text_parts=tuple(
                item.exact_text for item in (*page.cells[:2], *page.cells[4:])
            ),
            slice_sha256=hashlib.sha256(b"table-slice-terms-uninsured").hexdigest(),
        ),
    )
    terms = replace(
        terms,
        pages=(replace(page, table_slices=slices),),
        parse_manifest_sha256="",
    )
    terms = replace(
        terms,
        parse_manifest_sha256=terms.recomputed_manifest_sha256(),
    )
    admitted = _rebind_admitted_source(admitted, terms)
    sources = (
        terms,
        _source_projection(role="brochure", lines=("保障期间",)),
        _source_projection(role="rate_table", lines=("可投保职业",)),
    )
    catalog = build_field_selection_catalogs_815(
        field_contracts=contracts,
        provider_visible_field_ids=execution.provider_visible_field_ids,
        available_source_roles=("terms", "brochure", "rate_table"),
        source_projections=sources,
    )
    deductible = catalog.require_field("deductible_rules")
    outpatient = catalog.require_field("outpatient_inpatient_scope")
    reimbursable = catalog.require_field("reimbursable_expense_scope")
    reimbursement = catalog.require_field("reimbursement_rate_rules")
    hospital = catalog.require_field("eligible_hospital_scope")
    overlapping = tuple(
        item for item in reimbursement.selections if item.selection_type == "TABLE_SLICE"
    )
    assert len(overlapping) == 2
    assert set(overlapping[0].subject_ids) & set(overlapping[1].subject_ids)

    response = require_model_selection_response_815(
        {
            "task_key": "terms-04",
            "fields": [
                {
                    "field_id": deductible.field_id,
                    "state": "present",
                    "selection_ids": [deductible.selections[0].selection_id],
                    "typed_reason": None,
                },
                {
                    "field_id": outpatient.field_id,
                    "state": "unknown",
                    "selection_ids": [],
                    "typed_reason": "ANSWER_NOT_FOUND",
                },
                {
                    "field_id": reimbursable.field_id,
                    "state": "unknown",
                    "selection_ids": [],
                    "typed_reason": "ANSWER_NOT_FOUND",
                },
                {
                    "field_id": reimbursement.field_id,
                    "state": "present",
                    "selection_ids": [item.selection_id for item in overlapping],
                    "typed_reason": None,
                },
                {
                    "field_id": hospital.field_id,
                    "state": "present",
                    "selection_ids": [overlapping[0].selection_id],
                    "typed_reason": None,
                },
            ],
        },
        task_key="terms-04",
        field_catalogs=(deductible, outpatient, reimbursable, reimbursement, hospital),
    )

    outputs, coordinates, reasons = hydrate_model_selection_response_815(
        response=response,
        field_catalogs=(deductible, outpatient, reimbursable, reimbursement, hospital),
        source_projections=sources,
        admitted_sources=(admitted,),
    )

    assert tuple(item.field_id for item in outputs) == (
        "deductible_rules",
        "outpatient_inpatient_scope",
        "reimbursable_expense_scope",
        "reimbursement_rate_rules",
        "eligible_hospital_scope",
    )
    assert outputs[0].state == "present"
    assert outputs[0].value_snapshot == "免赔额为一万元"
    assert outputs[0].evidence
    assert outputs[3].state == "present"
    assert outputs[3].value_snapshot == "\N{LINE SEPARATOR}".join(
        "\N{LINE SEPARATOR}".join(item.exact_text_parts) for item in overlapping
    )
    assert tuple(item.cell_id for item in outputs[3].evidence) == tuple(
        item.cell_id for item in page.cells
    )
    assert outputs[4].state == "unknown"
    assert outputs[4].value_snapshot is None
    assert outputs[4].evidence == ()
    assert tuple(item.field_id for item in coordinates) == (
        "deductible_rules",
        "reimbursement_rate_rules",
        "reimbursement_rate_rules",
    )
    assert tuple(item.selection_id for item in coordinates[1:]) == tuple(
        item.selection_id for item in overlapping
    )
    assert tuple(item.cell_ids for item in coordinates[1:]) == tuple(
        item.subject_ids for item in overlapping
    )
    assert reasons == (
        ("outpatient_inpatient_scope", "ANSWER_NOT_FOUND"),
        ("reimbursable_expense_scope", "ANSWER_NOT_FOUND"),
        ("eligible_hospital_scope", "SOURCE_LOCATION_UNRESOLVED"),
    )

    with pytest.raises(
        NativePdfSelectionError815,
        match="SELECTION_RESPONSE_SHAPE_INVALID",
    ):
        require_model_selection_response_815(
            {
                "task_key": "terms-04",
                "fields": [
                    {
                        "field_id": reimbursement.field_id,
                        "state": "present",
                        "selection_ids": [
                            overlapping[0].selection_id,
                            overlapping[0].selection_id,
                        ],
                        "typed_reason": None,
                    }
                ],
            },
            task_key="terms-04",
            field_catalogs=(reimbursement,),
        )

    nonoverlapping = require_model_selection_response_815(
        {
            "task_key": "terms-04",
            "fields": [
                {
                    "field_id": reimbursement.field_id,
                    "state": "present",
                    "selection_ids": [overlapping[0].selection_id],
                    "typed_reason": None,
                }
            ],
        },
        task_key="terms-04",
        field_catalogs=(reimbursement,),
    )
    valid_outputs, valid_coordinates, valid_reasons = hydrate_model_selection_response_815(
        response=nonoverlapping,
        field_catalogs=(reimbursement,),
        source_projections=sources,
        admitted_sources=(admitted,),
    )
    assert valid_outputs[0].state == "present"
    assert valid_outputs[0].evidence
    assert len(valid_coordinates) == 1
    assert valid_reasons == ()

    drifted_selection_seed = replace(
        overlapping[0],
        selection_id="pending",
        subject_ids=("cell-not-in-projection",),
        exact_text_parts=(overlapping[0].exact_text_parts[0],),
        value_parts=(
            native_selection._value_part(
                subject_ids=("cell-not-in-projection",),
                exact_text_parts=(overlapping[0].exact_text_parts[0],),
            ),
        ),
        selection_sha256="pending",
    )
    drifted_selection_sha256 = drifted_selection_seed.recomputed_selection_sha256()
    drifted_selection = replace(
        drifted_selection_seed,
        selection_id=f"selection-{drifted_selection_sha256}",
        selection_sha256=drifted_selection_sha256,
    )
    drifted_catalog_seed = replace(
        reimbursement,
        selections=(drifted_selection,),
        catalog_sha256="pending",
    )
    drifted_catalog = replace(
        drifted_catalog_seed,
        catalog_sha256=drifted_catalog_seed.recomputed_catalog_sha256(),
    )
    drifted_response = require_model_selection_response_815(
        {
            "task_key": "terms-04",
            "fields": [
                {
                    "field_id": deductible.field_id,
                    "state": "present",
                    "selection_ids": [deductible.selections[0].selection_id],
                    "typed_reason": None,
                },
                {
                    "field_id": drifted_catalog.field_id,
                    "state": "present",
                    "selection_ids": [drifted_selection.selection_id],
                    "typed_reason": None,
                },
            ],
        },
        task_key="terms-04",
        field_catalogs=(deductible, drifted_catalog),
    )
    drifted_outputs, drifted_coordinates, drifted_reasons = (
        hydrate_model_selection_response_815(
            response=drifted_response,
            field_catalogs=(deductible, drifted_catalog),
            source_projections=sources,
            admitted_sources=(admitted,),
        )
    )
    assert drifted_outputs[0] == outputs[0]
    assert drifted_outputs[1].state == "unknown"
    assert drifted_outputs[1].value_snapshot is None
    assert drifted_outputs[1].evidence == ()
    assert tuple(item.field_id for item in drifted_coordinates) == (
        "deductible_rules",
    )
    assert drifted_reasons == (
        ("reimbursement_rate_rules", "SOURCE_LOCATION_UNRESOLVED"),
    )
