"""文档可喂性评分（006 T7；spec F4；来源 12-dayu-borrowings #4，并入 11 §2 质量检测）。

解析产物进抽取管道前的**确定性**打分（零模型）：乱码/空页/超大页/截断尾部/表格
列名合法性。本 change 只打分与报告（split_route 记入 manifest，不拦截）；隔离区
目录机制简单实现（``write_quarantine``，审计痕迹可救回，12 #5）。
"""

import json
import re
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..goldenset.pdf import PageText
from .templates.tables import TableGrid

DEFAULT_THRESHOLD = 0.75

_GARBLED_MAX_RATIO = 0.005  # � 与 (cid:N) 字符占比上限
_EMPTY_PAGE_MIN_CHARS = 10
_EMPTY_PAGE_MAX_RATIO = 0.5
_OVERSIZED_PAGE_CHARS = 15_000  # 单页文本超此值多为解析把版面糊成一团
_TRUNCATED_TAIL_RE = re.compile(r"[，、,：:；;（(]\s*$")
_CID_RE = re.compile(r"\(cid:\d+\)")


class FeedabilityCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    ok: bool
    detail: str = ""


class FeedabilityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    doc: str
    score: float  # ∈ [0,1]：通过检查项占比
    threshold: float = DEFAULT_THRESHOLD
    checks: tuple[FeedabilityCheck, ...] = ()

    @property
    def feedable(self) -> bool:
        return self.score >= self.threshold

    @property
    def quarantine_suggested(self) -> bool:
        return not self.feedable


def _check_garbled(pages: Sequence[PageText]) -> FeedabilityCheck:
    total = sum(len(p.text) for p in pages) or 1
    bad = sum(p.text.count("�") for p in pages) + sum(
        len(m.group(0)) for p in pages for m in _CID_RE.finditer(p.text)
    )
    ratio = bad / total
    return FeedabilityCheck(
        name="garbled",
        ok=ratio <= _GARBLED_MAX_RATIO,
        detail=f"乱码占比 {ratio:.4f}（上限 {_GARBLED_MAX_RATIO}）",
    )


def _check_empty_pages(pages: Sequence[PageText]) -> FeedabilityCheck:
    total = len(pages) or 1
    empty = sum(1 for p in pages if len(p.text.strip()) < _EMPTY_PAGE_MIN_CHARS)
    ratio = empty / total
    return FeedabilityCheck(
        name="empty_pages",
        ok=ratio <= _EMPTY_PAGE_MAX_RATIO,
        detail=f"空页比例 {ratio:.2f}（{empty}/{total}，上限 {_EMPTY_PAGE_MAX_RATIO}）",
    )


def _check_oversized_page(pages: Sequence[PageText]) -> FeedabilityCheck:
    worst = max((len(p.text) for p in pages), default=0)
    return FeedabilityCheck(
        name="oversized_page",
        ok=worst <= _OVERSIZED_PAGE_CHARS,
        detail=f"最大单页 {worst} 字（上限 {_OVERSIZED_PAGE_CHARS}）",
    )


def _check_truncated_tail(pages: Sequence[PageText]) -> FeedabilityCheck:
    tail = ""
    for p in reversed(pages):
        if p.text.strip():
            tail = p.text.strip()
            break
    truncated = bool(_TRUNCATED_TAIL_RE.search(tail[-8:])) if tail else True
    return FeedabilityCheck(
        name="truncated_tail",
        ok=not truncated,
        detail=f"文档尾部 {tail[-20:]!r}" if tail else "无任何文本",
    )


def _check_table_headers(tables: Sequence[TableGrid]) -> FeedabilityCheck:
    illegal = 0
    for grid in tables:
        if not grid.rows or all(not c for c in grid.rows[0]):
            illegal += 1
    return FeedabilityCheck(
        name="table_headers",
        ok=illegal == 0,
        detail=f"表头非法表格数 {illegal}/{len(tables)}",
    )


def score_feedability(
    doc: str,
    pages: Sequence[PageText],
    tables: Sequence[TableGrid] | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> FeedabilityReport:
    """确定性可喂性打分（F4.1）：总分 = 通过检查项占比，逐项 ok/detail 可见。"""
    checks = [
        _check_garbled(pages),
        _check_empty_pages(pages),
        _check_oversized_page(pages),
        _check_truncated_tail(pages),
    ]
    if tables is not None:
        checks.append(_check_table_headers(tables))
    score = sum(1 for c in checks if c.ok) / len(checks)
    return FeedabilityReport(doc=doc, score=score, threshold=threshold, checks=tuple(checks))


class QuarantineRecord(BaseModel):
    """隔离区审计记录（12 #5：留痕可救回）。"""

    product: str
    doc: str
    report: FeedabilityReport
    note: str = "可喂性评分不达标：走解析升级链（11 §2）后重评，或人工救回"

    model_config = ConfigDict(frozen=True)


def write_quarantine(
    quarantine_dir: Path, product: str, doc: str, report: FeedabilityReport
) -> Path:
    """落隔离文件 `<dir>/<product>/<doc>.rejection.json`（F4.3）。"""
    record = QuarantineRecord(product=product, doc=doc, report=report)
    path = quarantine_dir / product / f"{doc}.rejection.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def render_feedability(reports: Sequence[FeedabilityReport]) -> str:
    """逐文档评分的 markdown/终端渲染（F4.2 报告）。"""
    lines = ["| 文档 | 评分 | 达标 | 未过检查项 |", "|---|---|---|---|"]
    for r in reports:
        failed = "，".join(f"{c.name}({c.detail})" for c in r.checks if not c.ok) or "-"
        lines.append(
            f"| {r.doc} | {r.score:.2f} | {'✅' if r.feedable else '❌ 建议隔离'} | {failed} |"
        )
    return "\n".join(lines) + "\n"
