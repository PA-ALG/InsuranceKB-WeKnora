"""F2.2/F2.3 知识缺口聚合（纯逻辑，unblocked）：信号 → 去重、计数、优先级、reopen。

稳定 ID 由对齐粒度派生：同一缺口多次触发只累计 hit_count 与最近样例（≤5），**不重复
开单**（hit_count 即优先级信号）。已 resolve 的缺口再触发 → reopened（知识补了还答
不好=新问题）。此模块只做聚合，不落 ReviewItem（投影到 knowledge 域=F2 gated 段）。

record() 假设输入已由 F1.1 游标去重（每 trace 只处理一次）——故每次调用即一次有效
触发，直接累计；同 gap 的去重由 gap_key 保证。
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
    sample_trace_ids: tuple[str, ...] = ()
    status: GapStatus = "open"


def stable_gap_key(entity: AlignedEntity) -> str:
    """确定性稳定 ID：对齐粒度派生（product|field|concept），同粒度必同 key。"""
    return f"{entity.product_id or ''}|{entity.field_id or ''}|{entity.concept_id or ''}"


class GapAggregator:
    """维护 gap_key → KnowledgeGap；seed 既有缺口（含 resolved）以支持 reopen。"""

    def __init__(self, existing: list[KnowledgeGap] | None = None) -> None:
        self._gaps: dict[str, KnowledgeGap] = {g.gap_key: g for g in existing or []}

    def record(
        self, entity: AlignedEntity, signal_types: set[SignalType], trace_id: str
    ) -> KnowledgeGap:
        """记录一次缺口触发；返回更新后的缺口（幂等不重复开单，同 gap_key 累计）。"""
        key = stable_gap_key(entity)
        existing = self._gaps.get(key)
        if existing is None:
            gap = KnowledgeGap(
                gap_key=key,
                entity=entity,
                signal_types=tuple(sorted(signal_types)),
                hit_count=1,
                sample_trace_ids=(trace_id,),
                status="open",
            )
        else:
            samples = existing.sample_trace_ids
            if trace_id not in samples and len(samples) < _MAX_SAMPLES:
                samples = (*samples, trace_id)
            gap = existing.model_copy(
                update={
                    "signal_types": tuple(
                        sorted(set(existing.signal_types) | signal_types)
                    ),
                    "hit_count": existing.hit_count + 1,
                    "sample_trace_ids": samples,
                    # resolve 后再触发 → reopened（知识补了还答不好=新问题，F2.3）
                    "status": "reopened" if existing.status == "resolved" else existing.status,
                }
            )
        self._gaps[key] = gap
        return gap

    def gaps(self) -> list[KnowledgeGap]:
        return list(self._gaps.values())
