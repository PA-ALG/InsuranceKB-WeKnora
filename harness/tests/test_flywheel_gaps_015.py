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


def test_f2_2_samples_capped_at_five_but_count_unbounded() -> None:
    agg = GapAggregator()
    for i in range(7):
        agg.record(_e(), {"no_citation"}, f"tr-{i}")
    g = agg.gaps()[0]
    assert g.hit_count == 7
    assert len(g.sample_trace_ids) == 5  # 样例上限 5


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


def test_f2_3_open_gap_stays_open_on_retrigger() -> None:
    agg = GapAggregator()
    agg.record(_e(), {"no_citation"}, "tr-1")
    gap = agg.record(_e(), {"no_citation"}, "tr-2")
    assert gap.status == "open"
