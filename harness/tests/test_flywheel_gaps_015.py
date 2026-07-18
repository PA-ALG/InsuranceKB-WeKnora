"""015 F2.2/F2.3 知识缺口聚合——红绿（测试名引用条款号）。

纯逻辑（unblocked）：稳定 ID / hit_count 累计 / 样例≤5 / 幂等不重复开单 / reopen。
"""

from __future__ import annotations

from insurance_harness.flywheel.gaps import (
    AlignedEntity,
    GapAggregator,
    KnowledgeGap,
    stable_gap_key,
)


def _e(product_id: str = "P001", field_id: str | None = "等待期") -> AlignedEntity:
    return AlignedEntity(product_id=product_id, field_id=field_id)


# ---------------------------------------------------------------------------
# 稳定 ID（F2.2）
# ---------------------------------------------------------------------------


def test_f2_2_stable_gap_key_deterministic() -> None:
    assert stable_gap_key(_e()) == stable_gap_key(_e())


def test_f2_2_stable_gap_key_distinguishes_granularity() -> None:
    assert stable_gap_key(_e(field_id="等待期")) != stable_gap_key(_e(field_id="犹豫期"))


# ---------------------------------------------------------------------------
# hit_count 累计 + 样例 + 幂等不重复开单（F2.2）
# ---------------------------------------------------------------------------


def test_f2_2_first_trigger_opens_gap() -> None:
    agg = GapAggregator()
    gap = agg.record(_e(), {"no_citation"}, "tr-1")
    assert gap.hit_count == 1
    assert gap.sample_trace_ids == ("tr-1",)
    assert gap.status == "open"
    assert "no_citation" in gap.signal_types


def test_f2_2_same_gap_accumulates_not_duplicates() -> None:
    agg = GapAggregator()
    agg.record(_e(), {"no_citation"}, "tr-1")
    agg.record(_e(), {"low_confidence_refusal"}, "tr-2")
    gaps = agg.gaps()
    assert len(gaps) == 1  # 不重复开单
    g = gaps[0]
    assert g.hit_count == 2
    assert set(g.sample_trace_ids) == {"tr-1", "tr-2"}
    # 信号类型跨触发合并去重
    assert set(g.signal_types) == {"no_citation", "low_confidence_refusal"}


def test_f2_2_distinct_entities_are_distinct_gaps() -> None:
    agg = GapAggregator()
    agg.record(_e(field_id="等待期"), {"no_citation"}, "tr-1")
    agg.record(_e(field_id="犹豫期"), {"no_citation"}, "tr-2")
    assert len(agg.gaps()) == 2


def test_f2_2_samples_are_most_recent_five() -> None:
    """F2.2：样例=最近 ≤5 条（滚动替换最旧），不是冻结最早 5 条（codex 反例3）。"""
    agg = GapAggregator()
    for i in range(7):
        agg.record(_e(), {"no_citation"}, f"tr-{i}", question=f"问题{i}")
    g = agg.gaps()[0]
    assert g.hit_count == 7
    assert g.sample_trace_ids == ("tr-2", "tr-3", "tr-4", "tr-5", "tr-6")  # 最近 5 条
    assert g.sample_questions == ("问题2", "问题3", "问题4", "问题5", "问题6")  # 平行滚动


def test_f2_2_duplicate_trace_id_not_double_counted() -> None:
    """F2.2：同一 trace_id 对同一缺口只计一次 hit_count（codex 反例2）。"""
    agg = GapAggregator()
    agg.record(_e(), {"no_citation"}, "tr-1")
    g = agg.record(_e(), {"no_citation"}, "tr-1")  # 同 trace 重复触发
    assert g.hit_count == 1
    assert g.sample_trace_ids == ("tr-1",)


def test_f2_2_first_and_last_seen_tracked() -> None:
    """F3.1 闭环周期的时间基座：first_seen 固定于首触发，last_seen 随最新触发。"""
    agg = GapAggregator()
    agg.record(_e(), {"no_citation"}, "tr-1", timestamp="2026-07-01T10:00:00Z")
    g = agg.record(_e(), {"no_citation"}, "tr-2", timestamp="2026-07-03T10:00:00Z")
    assert g.first_seen == "2026-07-01T10:00:00Z"
    assert g.last_seen == "2026-07-03T10:00:00Z"


# ---------------------------------------------------------------------------
# reopen（F2.3）：已 resolve 的缺口再触发 → reopened + 累计
# ---------------------------------------------------------------------------


def test_f2_3_resolved_gap_reopens_on_retrigger() -> None:
    key = stable_gap_key(_e())
    seeded = KnowledgeGap(
        gap_key=key, entity=_e(), hit_count=3,
        sample_trace_ids=("old-1",), status="resolved",
    )
    agg = GapAggregator(existing=[seeded])
    gap = agg.record(_e(), {"empty_knowledge"}, "tr-new")
    assert gap.status == "reopened"
    assert gap.hit_count == 4  # 在既有基础上累计


def test_f2_3_reopen_preserves_first_seen_clears_resolved_at() -> None:
    """F2.3：reopen 保留 first_seen（不重置首见），清 resolved_at（不再算已闭环）。"""
    key = stable_gap_key(_e())
    seeded = KnowledgeGap(
        gap_key=key, entity=_e(), hit_count=3, status="resolved",
        first_seen="2026-06-01T00:00:00Z", resolved_at="2026-06-20T00:00:00Z",
    )
    agg = GapAggregator(existing=[seeded])
    gap = agg.record(_e(), {"no_citation"}, "tr-new", timestamp="2026-07-01T00:00:00Z")
    assert gap.status == "reopened"
    assert gap.first_seen == "2026-06-01T00:00:00Z"
    assert gap.resolved_at is None


def test_f2_3_open_gap_stays_open_on_retrigger() -> None:
    agg = GapAggregator()
    agg.record(_e(), {"no_citation"}, "tr-1")
    gap = agg.record(_e(), {"no_citation"}, "tr-2")
    assert gap.status == "open"
