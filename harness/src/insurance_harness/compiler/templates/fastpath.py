"""运行时 fast path（006 T6；spec F3；设计 11 §1.3——模板命中优先，失败回退通用管道）。

族识别命中 published 模板 → 锚点定位 → 确定性抽取（表格列直取/正则捕获）→
**既有校验链**（回验/清洗/三态，extract.run_validation_chain）；校验不过或锚点
未命中 → 该字段降级通用管道（F3.2/F3.3），fast path 绝不产出未验证的值。
"""

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from ...goldenset.pdf import PageText
from ...goldenset.records import Evidence
from ...schemas import FieldSpec
from ..extract import run_validation_chain
from ..models import DataQuality, FieldCandidate
from ..routing_data import group_of_field
from ..sections import DocSection
from .models import ExtractionTemplate, FieldAnchors, TemplateField
from .tables import TableStructureProvider, distinct_single_line_cells

_PAGE_HINT_TOLERANCE = 1  # 页位置提示 ±1 容忍解析分页差（同 eval 证据对齐口径）


def _candidate_pages(
    anchors: FieldAnchors,
    pages: Sequence[PageText],
    sections: Sequence[DocSection] | None,
) -> list[PageText]:
    out = list(pages)
    if anchors.pages:
        lo = min(anchors.pages) - _PAGE_HINT_TOLERANCE
        hi = max(anchors.pages) + _PAGE_HINT_TOLERANCE
        out = [p for p in out if lo <= p.page_no <= hi]
    if anchors.section_title and sections:
        pattern = re.compile(anchors.section_title)
        ranges = [
            (s.page_first, s.page_last) for s in sections if pattern.search(s.title)
        ]
        if ranges:
            out = [p for p in out if any(a <= p.page_no <= b for a, b in ranges)]
    return out


def _extract_table(
    tf: TemplateField,
    pages: Sequence[PageText],
    pdf_path: Path | None,
    provider: TableStructureProvider | None,
) -> tuple[str, Evidence, DataQuality] | None:
    anchor = tf.anchors.table_columns
    if anchor is None or provider is None or pdf_path is None:
        return None
    for page in pages:
        for grid in provider.extract_tables(pdf_path, page.page_no):
            header = grid.header_row(anchor.header_contains)
            if header is None:
                continue
            if anchor.op == "join_headers":
                cells = distinct_single_line_cells(header)
                if len(cells) < 2:
                    continue
                value = anchor.join.join(cells)
                quote = " ".join(cells)
            else:  # cell：数字列定位直取（12 #1）
                assert anchor.row_label is not None and anchor.column is not None
                cell = grid.lookup_cell(anchor.header_contains, anchor.column, anchor.row_label)
                if cell is None:
                    continue
                value = quote = cell
            return value, Evidence(page=page.page_no, quote=quote), "table_parsed"
    return None


def _extract_regex(
    tf: TemplateField, pages: Sequence[PageText]
) -> tuple[str, Evidence, DataQuality] | None:
    if tf.anchors.regex is None:
        return None
    pattern = re.compile(tf.anchors.regex)
    for page in pages:
        m = pattern.search(page.text)
        if m is not None and m.group(1):
            quote = m.group(0).strip()[:200]
            return m.group(1), Evidence(page=page.page_no, quote=quote), "structured_direct"
    return None


def run_fastpath(
    template: ExtractionTemplate,
    fields_by_id: Mapping[str, FieldSpec],
    doc: str,
    pages: Sequence[PageText],
    pdf_path: Path | None = None,
    provider: TableStructureProvider | None = None,
    sections: Sequence[DocSection] | None = None,
) -> list[FieldCandidate]:
    """对单文档执行 fast path：返回**已通过校验链**的候选值（F3.1/F3.2）。

    锚点未命中/校验不过的字段不在返回值中（→ 通用管道照常抽取，F3.3）。
    """
    out: list[FieldCandidate] = []
    for tf in template.fields:
        field = fields_by_id.get(tf.field_id)
        if field is None or not field.extractable:
            continue
        scope = _candidate_pages(tf.anchors, pages, sections)
        hit = _extract_table(tf, scope, pdf_path, provider) or _extract_regex(tf, scope)
        if hit is None:
            continue
        value, evidence, data_quality = hit
        cand = FieldCandidate(
            field_id=tf.field_id,
            field_name=tf.field_name,
            group=group_of_field(tf.field_name),
            doc=doc,
            value=value,
            tri_state="present",
            evidence=[evidence],
            confidence="high",
            origin="fastpath",
            metadata={"data_quality": data_quality, "template_id": template.template_id},
        )
        validated, err = run_validation_chain(cand, field, pages)
        if err is not None or validated.tri_state != "present":
            continue  # 校验链不过 → 丢弃并降级通用管道（宁缺勿假，F3.2）
        out.append(validated)
    return out
