"""漏抽归因工具（005 spec V5）：纯确定性、零模型调用。

对金标 present / 预测 unknown（或缺行）的字段逐条定位失分环节：
- ``routing_miss``：金标证据页不在该字段所属组的路由章节内（路由问题）；
- ``extract_empty``：证据页在路由内但抽取仍为空（prompt/模型问题）;
- ``cleaning_kill``：预测 ``unknown_reason=placeholder``（清洗误杀）；
- ``no_evidence_page``：金标该条无证据页，无法做路由判定（单列不强行归因）。

路由结果获取（V5.2）：run manifest 只有 routed_pairs 计数、无逐章节记录，
故基于 ``sections.split_sections + route_groups`` 对原 PDF 确定性重算；
核心函数接受注入的路由查询（RoutingLookup），无 PDF 也可单测。
"""

import re
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from ..goldenset.records import GoldenRecord
from .routing_data import group_of_field
from .sections import DocSection, route_groups, split_sections

MissCategory = str  # routing_miss / extract_empty / cleaning_kill / no_evidence_page

ROUTING_MISS = "routing_miss"
EXTRACT_EMPTY = "extract_empty"
CLEANING_KILL = "cleaning_kill"
NO_EVIDENCE_PAGE = "no_evidence_page"

#: (product_name, doc) -> (sections, by_group)；None = 该文档不可用（调用方决定失败策略）
RoutingLookup = Callable[
    [str, str], tuple[Sequence[DocSection], dict[str, tuple[str, ...]]] | None
]


class MissAttribution(BaseModel):
    """单条漏抽的归因结果（V5.3 逐条清单行）。"""

    product_id: str
    product_name: str
    field_id: str
    field_name: str
    group: str
    doc: str
    evidence_pages: list[int] = Field(default_factory=list)
    category: MissCategory
    unknown_reason: str | None = None


class AttributionReport(BaseModel):
    items: list[MissAttribution] = Field(default_factory=list)

    @property
    def stats(self) -> dict[str, int]:
        return dict(Counter(i.category for i in self.items))


def dataset_routing_lookup(
    dataset_root: Path,
    keywords: dict[str, re.Pattern[str] | None] | None = None,
) -> RoutingLookup:
    """基于原始 PDF 的确定性路由重算（带缓存）；``keywords`` 可注入 004 基线复算修复前。"""
    from ..goldenset.pdf import extract_pages

    cache: dict[tuple[str, str], tuple[Sequence[DocSection], dict[str, tuple[str, ...]]]] = {}

    def lookup(
        product_name: str, doc: str
    ) -> tuple[Sequence[DocSection], dict[str, tuple[str, ...]]] | None:
        key = (product_name, doc)
        if key not in cache:
            pdf = dataset_root / product_name / doc
            if not pdf.exists():
                return None
            sections = split_sections(extract_pages(pdf))
            routing = route_groups(sections, keywords=keywords)
            cache[key] = (sections, dict(routing.by_group))
        return cache[key]

    return lookup


def _pages_routed(
    sections: Sequence[DocSection], routed_ids: tuple[str, ...], pages: set[int]
) -> bool:
    routed = set(routed_ids)
    return any(
        s.section_id in routed and any(s.page_first <= pg <= s.page_last for pg in pages)
        for s in sections
    )


def attribute_misses(
    golden: Sequence[GoldenRecord],
    pred: Sequence[GoldenRecord],
    lookup: RoutingLookup,
) -> AttributionReport:
    """对 金标 present / 预测 unknown（或缺行）逐条归因（V5.1；disputed 金标除外）。"""
    p_map = {(p.product_id, p.field_id): p for p in pred}
    items: list[MissAttribution] = []
    for g in golden:
        if g.disputed or g.tri_state != "present":
            continue
        p = p_map.get((g.product_id, g.field_id))
        if p is not None and p.tri_state != "unknown":
            continue
        unknown_reason = getattr(p, "unknown_reason", None) if p is not None else None
        group = group_of_field(g.field_name)
        pages = {e.page for e in g.evidence}
        if unknown_reason == "placeholder":
            category = CLEANING_KILL
        elif not pages:
            category = NO_EVIDENCE_PAGE  # V5.4
        else:
            routed = lookup(g.product_name, g.doc)
            if routed is None:
                raise FileNotFoundError(
                    f"路由重算缺原文档：{g.product_name}/{g.doc}（V5.2 需要 dataset PDF）"
                )
            sections, by_group = routed
            covered = _pages_routed(sections, by_group.get(group, ()), pages)
            category = EXTRACT_EMPTY if covered else ROUTING_MISS
        items.append(
            MissAttribution(
                product_id=g.product_id,
                product_name=g.product_name,
                field_id=g.field_id,
                field_name=g.field_name,
                group=group,
                doc=g.doc,
                evidence_pages=sorted(pages),
                category=category,
                unknown_reason=str(unknown_reason) if unknown_reason else None,
            )
        )
    return AttributionReport(items=items)


def render_attribution(report: AttributionReport, title: str = "漏抽归因") -> str:
    """归因统计 + 逐条清单的 markdown 渲染（V5.3）。"""
    lines = [f"### {title}", "", "| 归因 | 条数 |", "|---|---|"]
    for cat in (ROUTING_MISS, EXTRACT_EMPTY, CLEANING_KILL, NO_EVIDENCE_PAGE):
        n = report.stats.get(cat, 0)
        if n or cat != NO_EVIDENCE_PAGE:
            lines.append(f"| {cat} | {n} |")
    lines += ["", "| 产品 | 字段 | 组 | 文档 | 证据页 | 归因 | unknown_reason |",
              "|---|---|---|---|---|---|---|"]
    for i in report.items:
        pages = ",".join(str(p) for p in i.evidence_pages) or "-"
        lines.append(
            f"| {i.product_name[:16]} | {i.field_name}({i.field_id}) | {i.group} "
            f"| {i.doc} | {pages} | {i.category} | {i.unknown_reason or '-'} |"
        )
    return "\n".join(lines) + "\n"
