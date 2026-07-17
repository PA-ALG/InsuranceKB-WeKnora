"""F3.3 编排（纯逻辑，unblocked）：traces → F1 信号 → F2 对齐/聚合 → F3 报表。

一趟 pull 的确定性核心，与 I/O（Langfuse/文件/DB）解耦以便单测：
1. F1.1 游标增量：只处理游标之后的新 trace。
2. F2.1 对齐：question → AlignedEntity（置信不足/歧义 → None）。
3. F1.2 信号：对齐结果回填 `aligned_entity` 后识别四类信号（空知识据此查 claim）。
4. F2.2/2.3 聚合：有信号且已对齐 → 记入缺口；有信号但未对齐 → 观察队列（不开单）。
5. F3.1 报表：产出分状态计数 / TopN / 产品分布。

单据落地（ReviewItem 投影）不在此——那是 F2 gated 段（候 PR#9 + 域协调）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from ..product.routing import MatchIndex
from .align import align_question
from .cursor import new_traces, next_cursor
from .gaps import GapAggregator, KnowledgeGap, stable_gap_key
from .models import SignalConfig, Trace
from .report import FlywheelReport, build_report
from .signals import DEFAULT_CONFIG, ClaimLookup, detect_signals


class PullResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    report: FlywheelReport
    next_cursor: str | None
    processed: int  # 本轮游标过滤后的新 trace 数
    unaligned_signals: int  # 有信号但未对齐（进观察队列，未开单）
    # 空知识信号是否被评估（需 claim_lookup）；否则未评估，报表须自陈覆盖面。
    empty_knowledge_active: bool


def run_pull(
    traces: Sequence[Trace],
    index: MatchIndex,
    *,
    config: SignalConfig = DEFAULT_CONFIG,
    field_names: Mapping[str, str] | None = None,
    claim_lookup: ClaimLookup | None = None,
    cursor: str | None = None,
    existing_gaps: list[KnowledgeGap] | None = None,
) -> PullResult:
    """跑一趟 F1→F2→F3；确定性、零模型。"""
    fresh = new_traces(traces, cursor)  # F1.1 增量：只处理游标之后的新 trace
    aggregator = GapAggregator(existing_gaps)
    unaligned_signals = 0
    for trace in fresh:
        entity = align_question(index, trace.question, field_names=field_names)  # F2.1
        # run_pull 对 aligned_entity 有权威：对齐→gap_key；未对齐→清空（忽略入站陈旧键，
        # 否则客户端伪造的对齐键可借道触发 empty_knowledge）。
        stamped = trace.model_copy(
            update={"aligned_entity": stable_gap_key(entity) if entity is not None else None}
        )
        signals = detect_signals(stamped, config, claim_lookup=claim_lookup)  # F1.2
        if not signals:
            continue
        if entity is None:
            unaligned_signals += 1  # 有信号但对齐不足 → 观察队列，不开单（F2.1 fail-safe）
            continue
        aggregator.record(entity, signals, trace.trace_id)  # F2.2/2.3
    previous_keys = frozenset(g.gap_key for g in (existing_gaps or []))
    report = build_report(aggregator.gaps(), previous_keys=previous_keys)  # F3.1
    return PullResult(
        report=report,
        next_cursor=next_cursor(fresh, cursor),
        processed=len(fresh),
        unaligned_signals=unaligned_signals,
        empty_knowledge_active=claim_lookup is not None,
    )
