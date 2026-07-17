"""F3.1 飞轮报表（纯逻辑，unblocked）：分状态计数 + TopN（含脱敏问题）+ 闭环周期 + 分布。

TopN 输出**脱敏问题样例**（人类可读）而非仅内部 gap_key；闭环平均周期基于
first_seen/resolved_at（无已闭环缺口 → None 不虚报）。与 011 健康度报告合流
（F3.2）候 PR #12。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .gaps import KnowledgeGap


class TopUnanswered(BaseModel):
    """TopN 行：脱敏问题样例 + 命中数（gap_key 附带，非唯一标识信息）。"""

    model_config = ConfigDict(frozen=True)

    gap_key: str
    hit_count: int
    sample_question: str  # 最近一条非空脱敏问题样例（可为空串=无样例）


class FlywheelReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    open_count: int
    reopened_count: int
    resolved_count: int
    new_count: int  # 相对上一快照的新增缺口数
    top_unanswered: tuple[TopUnanswered, ...]  # 按 hit_count 降序
    avg_closure_days: float | None  # 缺口→闭环平均周期；无已闭环缺口 → None
    by_product: dict[str, int]


def _latest_question(gap: KnowledgeGap) -> str:
    for q in reversed(gap.sample_questions):
        if q:
            return q
    return ""


def _closure_days(gap: KnowledgeGap) -> float | None:
    if gap.status != "resolved" or not gap.first_seen or not gap.resolved_at:
        return None
    try:
        start = datetime.fromisoformat(gap.first_seen.replace("Z", "+00:00"))
        end = datetime.fromisoformat(gap.resolved_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (end - start).total_seconds() / 86400.0


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
    closures = [d for d in (_closure_days(g) for g in gaps) if d is not None]
    return FlywheelReport(
        total=len(gaps),
        open_count=by_status.get("open", 0),
        reopened_count=by_status.get("reopened", 0),
        resolved_count=by_status.get("resolved", 0),
        new_count=new_count,
        top_unanswered=tuple(
            TopUnanswered(
                gap_key=g.gap_key, hit_count=g.hit_count,
                sample_question=_latest_question(g),
            )
            for g in ranked
        ),
        avg_closure_days=(sum(closures) / len(closures)) if closures else None,
        by_product=dict(by_product),
    )
