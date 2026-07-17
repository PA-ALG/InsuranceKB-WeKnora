"""F2.2/F2.3 知识缺口聚合（纯逻辑，unblocked）：信号 → 去重、计数、优先级、reopen。

稳定 ID 由对齐粒度派生：同一缺口多次触发只累计 hit_count 与**最近**样例（≤5，滚动
替换最旧——spec F2.2），**不重复开单**（hit_count 即优先级信号）。同一 trace_id 对
同一缺口不重复累计（实例内 seen 守卫；跨轮由 F1.1a 游标保证——codex PR#18 阻断2）。
已 resolve 的缺口再触发 → reopened（保留 first_seen、清 resolved_at）。first_seen/
last_seen/resolved_at 支撑 F3.1 闭环周期。此模块只做聚合，不落 ReviewItem
（投影=F2.4 gated 段）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from .models import SignalType

GapStatus = Literal["open", "resolved", "reopened"]

_MAX_SAMPLES = 5


class AlignedEntity(BaseModel):
    """F2.1 对齐输出粒度（product 级 unblocked；concept 级候 009）。"""

    model_config = ConfigDict(frozen=True)

    product_id: str | None = None
    field_id: str | None = None
    concept_id: str | None = None


class KnowledgeGap(BaseModel):
    model_config = ConfigDict(frozen=True)

    gap_key: str
    entity: AlignedEntity
    signal_types: tuple[SignalType, ...] = ()
    hit_count: int = 0
    sample_trace_ids: tuple[str, ...] = ()  # 最近 ≤5（与 sample_questions 平行）
    sample_questions: tuple[str, ...] = ()  # 脱敏问题样例（TopN 报表用，F3.1）
    status: GapStatus = "open"
    first_seen: str | None = None  # 首触发 trace 时间戳（reopen 不重置）
    last_seen: str | None = None  # 最近触发 trace 时间戳
    resolved_at: str | None = None  # 闭环时间（reopen 时清空）


def stable_gap_key(entity: AlignedEntity) -> str:
    """确定性稳定 ID：对齐粒度派生（product|field|concept），同粒度必同 key。"""
    return f"{entity.product_id or ''}|{entity.field_id or ''}|{entity.concept_id or ''}"


class GapAggregator:
    """维护 gap_key → KnowledgeGap；seed 既有缺口（含 resolved）以支持 reopen。"""

    def __init__(self, existing: list[KnowledgeGap] | None = None) -> None:
        self._gaps: dict[str, KnowledgeGap] = {g.gap_key: g for g in existing or []}
        self._counted: set[tuple[str, str]] = set()  # (gap_key, trace_id) 实例内去重

    def record(
        self,
        entity: AlignedEntity,
        signal_types: set[SignalType],
        trace_id: str,
        *,
        question: str = "",
        timestamp: str | None = None,
    ) -> KnowledgeGap:
        """记录一次缺口触发；返回更新后的缺口（幂等不重复开单，同 gap_key 累计）。

        同一 (gap_key, trace_id) 只计一次（批内守卫；跨轮由游标保证）。
        """
        key = stable_gap_key(entity)
        if (key, trace_id) in self._counted:
            return self._gaps[key]  # 重复 trace 不增计数（codex 反例2）
        self._counted.add((key, trace_id))
        existing = self._gaps.get(key)
        if existing is None:
            gap = KnowledgeGap(
                gap_key=key,
                entity=entity,
                signal_types=tuple(sorted(signal_types)),
                hit_count=1,
                sample_trace_ids=(trace_id,),
                sample_questions=(question,),
                status="open",
                first_seen=timestamp,
                last_seen=timestamp,
            )
        else:
            # 最近样例滚动替换最旧（spec F2.2「最近 ≤5」，codex 反例3）
            samples = (*existing.sample_trace_ids, trace_id)[-_MAX_SAMPLES:]
            questions = (*existing.sample_questions, question)[-_MAX_SAMPLES:]
            reopening = existing.status == "resolved"
            gap = existing.model_copy(
                update={
                    "signal_types": tuple(
                        sorted(set(existing.signal_types) | signal_types)
                    ),
                    "hit_count": existing.hit_count + 1,
                    "sample_trace_ids": samples,
                    "sample_questions": questions,
                    # resolve 后再触发 → reopened（知识补了还答不好=新问题，F2.3）
                    "status": "reopened" if reopening else existing.status,
                    # reopen 保留 first_seen（首见不重置）、清 resolved_at（不再算已闭环）
                    "first_seen": existing.first_seen or timestamp,
                    "last_seen": timestamp or existing.last_seen,
                    "resolved_at": None if reopening else existing.resolved_at,
                }
            )
        self._gaps[key] = gap
        return gap

    def gaps(self) -> list[KnowledgeGap]:
        return list(self._gaps.values())
