"""模板归纳器（006 T5；spec F2；设计 11 §1.2——模板是金标的副产品，零模型调用）。

输入 = 族内 ≥2 产品的金标（evidence 页码+引文）+ 对应文档分页文本（+ 可选 pdf 供
表格 provider）；确定性挖掘锚点并在**全部**归纳产品上回放验证（锚点命中且抽出值
与该产品金标 values_equal）才入草案；命中率 <1.0 不发布（F2.2/F2.3）。
"""

import re
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ...goldenset.normalize import values_equal
from ...goldenset.pdf import PageText
from ...goldenset.records import GoldenRecord
from ..sections import split_sections
from .loader import parse_template
from .models import (
    ExtractionTemplate,
    FewShot,
    FieldAnchors,
    InducedFrom,
    TableAnchor,
    TemplateField,
)
from .tables import TableGrid, TableStructureProvider, distinct_single_line_cells

_JOIN = "、"
_PREFIX_CHARS = 8  # 正则锚点的前文窗口（字符）
_SEPARATOR_CLASS = r"[\s、，,/；;:：]*"
_DIGIT_RUN_RE = re.compile(r"[0-9０-９]+")


class InductionError(Exception):
    """归纳前置条件不满足（如族内产品 <2）：fail fast（F2.1）。"""


def load_wip_goldens(path: Path, product_name: str) -> list[GoldenRecord]:
    """读 wip 布局金标（wip-gs-v0.1/<产品>/golden.jsonl，行内无产品元信息）。

    行只含 doc/field/value/tri_state/evidence/reasoning——归纳只用这些字段；
    产品元信息以目录名补齐（正式 release 布局请直接用 goldenset.runner.read_jsonl）。
    """
    import json
    from datetime import UTC, datetime

    records: list[GoldenRecord] = []
    created = datetime.now(UTC)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        records.append(
            GoldenRecord(
                product_id=str(row.get("product_id") or product_name),
                product_name=str(row.get("product_name") or product_name),
                doc=str(row["doc"]),
                field_id=str(row["field_id"]),
                field_name=str(row["field_name"]),
                value=row.get("value"),
                tri_state=row["tri_state"],
                evidence=row.get("evidence") or [],
                disputed=bool(row.get("disputed", False)),
                reasoning=row.get("reasoning"),
                annotator_model=str(row.get("annotator_model") or "wip"),
                schema_version=str(row.get("schema_version") or "wip"),
                created_at=created,
            )
        )
    return records


class ProductDocInput(BaseModel):
    """单产品单文档的归纳输入：分页文本 + 该文档的金标记录。"""

    product_name: str
    pages: list[PageText]
    goldens: list[GoldenRecord]
    pdf_path: Path | None = None  # 提供时表格锚点可用（TableStructureProvider）


class InductionFieldReport(BaseModel):
    """归纳报告行（F2.3）：锚点类型与族内命中率。"""

    model_config = ConfigDict(frozen=True)

    field_id: str
    field_name: str
    anchor_type: str | None = None  # table_columns / regex / None
    hit_rate: float = 0.0  # 锚点在归纳产品上的回放验证命中率
    support: int = 0  # 金标 present 的产品数
    published: bool = False
    note: str = ""


class InductionResult(BaseModel):
    template: ExtractionTemplate
    report: list[InductionFieldReport] = Field(default_factory=list)


def tolerant_pattern(text: str) -> str:
    """值/引文 → 容错正则：数字段泛化 ``\\d+``、分隔符归类、字符间容忍空白换行。

    解析分页/排版差异（全半角空格、换行断词）不应破坏锚点匹配（F2.2）。
    """
    parts: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        m = _DIGIT_RUN_RE.match(text, i)
        if m:
            parts.append(r"\d+")
            i = m.end()
            continue
        if ch in " 、，,/；;:：　":
            if not parts or parts[-1] != _SEPARATOR_CLASS:
                parts.append(_SEPARATOR_CLASS)
            i += 1
            continue
        parts.append(re.escape(ch))
        i += 1
    return r"\s*".join(parts)


def _pages_of(inp: ProductDocInput, golden: GoldenRecord) -> list[PageText]:
    hint = {e.page for e in golden.evidence}
    return [p for p in inp.pages if not hint or p.page_no in hint]


# --- 表格列名锚点（12 #1） ---


def _grids(
    inp: ProductDocInput, page_no: int, provider: TableStructureProvider | None
) -> list[TableGrid]:
    if provider is None or inp.pdf_path is None:
        return []
    return provider.extract_tables(inp.pdf_path, page_no)


def _table_anchor_hits(
    anchor: TableAnchor,
    inp: ProductDocInput,
    golden: GoldenRecord,
    provider: TableStructureProvider | None,
) -> bool:
    """回放验证：锚点在该产品文档上抽出的值与其金标 values_equal（F2.3）。"""
    for page in sorted({e.page for e in golden.evidence}) or [1]:
        for grid in _grids(inp, page, provider):
            header = grid.header_row(anchor.header_contains)
            if header is None:
                continue
            value = anchor.join.join(distinct_single_line_cells(header))
            if values_equal(golden.value, value):
                return True
    return False


def _mine_table_anchor(
    entries: Sequence[tuple[ProductDocInput, GoldenRecord]],
    provider: TableStructureProvider | None,
) -> tuple[TableAnchor | None, float]:
    """表头行按 join 规则复原金标值（values_equal 判定）→ 列名枚举直取锚点。"""
    base_inp, base_g = entries[0]
    for page in sorted({e.page for e in base_g.evidence}):
        for grid in _grids(base_inp, page, provider):
            for row in grid.rows:
                cells = distinct_single_line_cells(row)
                if len(cells) < 2 or not values_equal(base_g.value, _JOIN.join(cells)):
                    continue
                anchor = TableAnchor(
                    op="join_headers", header_contains=cells[0], join=_JOIN
                )
                hits = sum(
                    1 for inp, g in entries if _table_anchor_hits(anchor, inp, g, provider)
                )
                return anchor, hits / len(entries)
    return None, 0.0


# --- 引文上下文正则锚点 ---


def _regex_candidates(inp: ProductDocInput, golden: GoldenRecord) -> list[str]:
    """从金标证据挖捕获正则：引文内定位值 → 前文窗口 + 值捕获组（F2.2）。"""
    assert golden.value is not None
    value_pat = tolerant_pattern(golden.value)
    patterns: list[str] = []
    for ev in golden.evidence:
        page = next((p for p in inp.pages if p.page_no == ev.page), None)
        if page is None:
            continue
        qm = re.search(tolerant_pattern(ev.quote), page.text)
        span_start, text = (qm.start(), page.text) if qm else (0, page.text)
        vm = re.search(value_pat, text[span_start:] if qm is None else qm.group(0))
        if vm is None:
            continue
        offset = span_start + vm.start() if qm else vm.start()
        prefix_raw = text[max(span_start, offset - _PREFIX_CHARS) : offset]
        prefix_raw = prefix_raw.split("\n")[-1]
        patterns.append(tolerant_pattern(prefix_raw) + "(" + value_pat + ")")
    # 有前文的模式更稳，排前面；保持确定性顺序
    return sorted(set(patterns), key=lambda p: (p.startswith("("), patterns.index(p)))


def _regex_hits(pattern: str, inp: ProductDocInput, golden: GoldenRecord) -> bool:
    compiled = re.compile(pattern)
    for page in _pages_of(inp, golden) or inp.pages:
        m = compiled.search(page.text)
        if m is not None and values_equal(golden.value, m.group(1)):
            return True
    return False


def _mine_regex_anchor(
    entries: Sequence[tuple[ProductDocInput, GoldenRecord]],
) -> tuple[str | None, float]:
    base_inp, base_g = entries[0]
    if base_g.value is None:
        return None, 0.0
    for pattern in _regex_candidates(base_inp, base_g):
        hits = sum(1 for inp, g in entries if _regex_hits(pattern, inp, g))
        if hits == len(entries):
            return pattern, 1.0
    return None, 0.0


# --- 辅助锚点（章节标题模式 / 页位置提示） ---


def _section_title_pattern(
    entries: Sequence[tuple[ProductDocInput, GoldenRecord]],
) -> str | None:
    patterns: set[str] = set()
    for inp, g in entries:
        sections = split_sections(inp.pages)
        for page in {e.page for e in g.evidence}:
            for sec in sections:
                if sec.page_first <= page <= sec.page_last and not sec.title.startswith(
                    "(前言)"
                ):
                    patterns.add(tolerant_pattern(sec.title))
    return patterns.pop() if len(patterns) == 1 else None


def _pages_hint(entries: Sequence[tuple[ProductDocInput, GoldenRecord]]) -> tuple[int, ...]:
    return tuple(sorted({e.page for _, g in entries for e in g.evidence}))


def _few_shots(entries: Sequence[tuple[ProductDocInput, GoldenRecord]]) -> tuple[FewShot, ...]:
    shots: list[FewShot] = []
    for inp, g in entries:
        if g.evidence and g.value is not None:
            shots.append(
                FewShot(
                    product=inp.product_name,
                    page=g.evidence[0].page,
                    quote=g.evidence[0].quote,
                    value=g.value,
                )
            )
    return tuple(shots)


# --- 归纳主流程 ---


def induce_template(
    doc: str,
    inputs: Sequence[ProductDocInput],
    family_id: str,
    provider: TableStructureProvider | None = None,
    golden_release: str = "wip-gs-v0.1",
    min_products: int = 2,
) -> InductionResult:
    """族内金标 → 模板草案 + 归纳报告（F2）；产出经 parse_template 自产自验（F2.4）。"""
    if len(inputs) < min_products:
        raise InductionError(
            f"模板归纳需要族内 ≥{min_products} 个产品的金标，实得 {len(inputs)}（F2.1）"
        )
    by_field: dict[str, list[tuple[ProductDocInput, GoldenRecord]]] = {}
    names: dict[str, str] = {}
    for inp in inputs:
        for g in inp.goldens:
            if g.doc == doc and not g.disputed and g.tri_state == "present" and g.value:
                by_field.setdefault(g.field_id, []).append((inp, g))
                names[g.field_id] = g.field_name

    fields: list[TemplateField] = []
    report: list[InductionFieldReport] = []
    for field_id, entries in sorted(by_field.items()):
        support = len({inp.product_name for inp, _ in entries})
        if support < min_products:
            report.append(
                InductionFieldReport(
                    field_id=field_id,
                    field_name=names[field_id],
                    support=support,
                    note=f"金标 present 产品数 {support} < {min_products}，不归纳",
                )
            )
            continue
        table_anchor, table_rate = _mine_table_anchor(entries, provider)
        regex_pattern: str | None = None
        regex_rate = 0.0
        if table_anchor is None or table_rate < 1.0:
            regex_pattern, regex_rate = _mine_regex_anchor(entries)

        if table_anchor is not None and table_rate == 1.0:
            anchor_type, rate = "table_columns", table_rate
            anchors = FieldAnchors(
                section_title=_section_title_pattern(entries),
                pages=_pages_hint(entries),
                table_columns=table_anchor,
            )
        elif regex_pattern is not None and regex_rate == 1.0:
            anchor_type, rate = "regex", regex_rate
            anchors = FieldAnchors(
                section_title=_section_title_pattern(entries),
                pages=_pages_hint(entries),
                regex=regex_pattern,
            )
        else:
            report.append(
                InductionFieldReport(
                    field_id=field_id,
                    field_name=names[field_id],
                    anchor_type=None,
                    hit_rate=max(table_rate, regex_rate),
                    support=support,
                    note="not_anchorable：表格/正则锚点均无法在全部归纳产品上复原金标值",
                )
            )
            continue
        fields.append(
            TemplateField(
                field_id=field_id,
                field_name=names[field_id],
                anchors=anchors,
                few_shots=_few_shots(entries),
            )
        )
        report.append(
            InductionFieldReport(
                field_id=field_id,
                field_name=names[field_id],
                anchor_type=anchor_type,
                hit_rate=rate,
                support=support,
                published=True,
            )
        )

    template = ExtractionTemplate(
        template_id=f"tpl-{family_id.removeprefix('fam-')}-{Path(doc).stem}",
        family_id=family_id,
        doc=doc,
        status="draft",
        induced_from=InducedFrom(
            products=tuple(inp.product_name for inp in inputs),
            golden_release=golden_release,
        ),
        fields=tuple(fields),
    )
    # F2.4 自产自验：草案必须能通过注册表加载校验
    parse_template(template.model_dump(mode="json"), "<induced>")
    return InductionResult(template=template, report=report)


def render_induction_report(result: InductionResult, title: str = "模板归纳报告") -> str:
    """归纳报告 markdown（F2.3：逐字段锚点类型与族内命中率）。"""
    t = result.template
    lines = [
        f"### {title}",
        "",
        f"- template_id：`{t.template_id}`（family `{t.family_id}` / doc `{t.doc}` / "
        f"status `{t.status}`）",
        f"- 归纳来源：{'、'.join(t.induced_from.products)}（{t.induced_from.golden_release}）",
        f"- 发布字段 {len(t.fields)} / 候选字段 {len(result.report)}",
        "",
        "| 字段 | 锚点类型 | 族内命中率 | support | 发布 | 备注 |",
        "|---|---|---|---|---|---|",
    ]
    for r in result.report:
        lines.append(
            f"| {r.field_name}({r.field_id}) | {r.anchor_type or '-'} | {r.hit_rate:.2f} "
            f"| {r.support} | {'✅' if r.published else '—'} | {r.note or '-'} |"
        )
    return "\n".join(lines) + "\n"
