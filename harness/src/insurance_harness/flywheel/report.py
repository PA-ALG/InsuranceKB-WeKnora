"""F3.1 飞轮报表（纯逻辑，unblocked）：缺口按状态计数 + TopN 答不上 + 产品分布。

"缺口→闭环平均周期"需 first_seen/resolved_at 时间字段（KnowledgeGap 扩展）——本
版先给可从缺口聚合直接算出的部分；时序指标随时间字段补齐（诚实边界）。与 011
健康度报告合流（F3.2）候 PR #12。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from .gaps import KnowledgeGap


class FlywheelReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    open_count: int
    reopened_count: int
    resolved_count: int
    new_count: int  # 相对上一快照的新增缺口数
    top_unanswered: tuple[tuple[str, int], ...]  # (gap_key, hit_count) 降序
    by_product: dict[str, int]


def build_report(
    gaps: Sequence[KnowledgeGap],
    *,
    previous_keys: frozenset[str] = frozenset(),
    top_n: int = 10,
) -> FlywheelReport:
    """从缺口聚合产出周期报表。new_count 用上一快照的 gap_key 集合确定。"""
    by_status = Counter(g.status for g in gaps)
    by_product: Counter[str] = Counter(
        (g.entity.product_id or "(未对齐)") for g in gaps
    )
    ranked = sorted(gaps, key=lambda g: (-g.hit_count, g.gap_key))[:top_n]
    new_count = sum(1 for g in gaps if g.gap_key not in previous_keys)
    return FlywheelReport(
        total=len(gaps),
        open_count=by_status.get("open", 0),
        reopened_count=by_status.get("reopened", 0),
        resolved_count=by_status.get("resolved", 0),
        new_count=new_count,
        top_unanswered=tuple((g.gap_key, g.hit_count) for g in ranked),
        by_product=dict(by_product),
    )
