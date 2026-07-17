"""015 F3.1 飞轮报表——分状态计数 / TopN（含脱敏问题）/ 新增 / 闭环周期 / 产品分布。"""

from __future__ import annotations

from insurance_harness.flywheel.gaps import AlignedEntity, KnowledgeGap
from insurance_harness.flywheel.report import build_report


def _gap(
    key: str,
    product: str,
    hits: int,
    status: str = "open",
    question: str = "",
    first_seen: str | None = None,
    resolved_at: str | None = None,
) -> KnowledgeGap:
    return KnowledgeGap(
        gap_key=key,
        entity=AlignedEntity(product_id=product),
        hit_count=hits,
        status=status,  # type: ignore[arg-type]
        sample_questions=(question,) if question else (),
        first_seen=first_seen,
        resolved_at=resolved_at,
    )


def test_f3_1_report_counts_by_status() -> None:
    gaps = [
        _gap("k1", "P001", 5, "open"),
        _gap("k2", "P001", 2, "reopened"),
        _gap("k3", "P002", 1, "resolved"),
    ]
    r = build_report(gaps)
    assert r.total == 3
    assert r.open_count == 1
    assert r.reopened_count == 1
    assert r.resolved_count == 1


def test_f3_1_top_unanswered_ordered_by_hit_count() -> None:
    gaps = [_gap("k1", "P001", 2), _gap("k2", "P001", 9), _gap("k3", "P002", 5)]
    r = build_report(gaps, top_n=2)
    assert [(t.gap_key, t.hit_count) for t in r.top_unanswered] == [("k2", 9), ("k3", 5)]


def test_f3_1_top_unanswered_carries_redacted_question() -> None:
    """F3.1：TopN 输出脱敏**问题**（人类可读）而非仅内部 key（codex 阻断4 报表侧）。"""
    gaps = [_gap("k1", "P001", 9, question="盛世金越的等待期是多久？")]
    r = build_report(gaps)
    assert r.top_unanswered[0].sample_question == "盛世金越的等待期是多久？"


def test_f3_1_new_count_relative_to_previous_snapshot() -> None:
    gaps = [_gap("k1", "P001", 3), _gap("k2", "P001", 1)]
    r = build_report(gaps, previous_keys=frozenset({"k1"}))
    assert r.new_count == 1  # 仅 k2 是新增


def test_f3_1_by_product_distribution() -> None:
    gaps = [_gap("k1", "P001", 1), _gap("k2", "P001", 1), _gap("k3", "P002", 1)]
    r = build_report(gaps)
    assert r.by_product == {"P001": 2, "P002": 1}


def test_f3_1_avg_closure_days_from_resolved_gaps() -> None:
    """F3.1：闭环平均周期 = resolved 缺口 (resolved_at − first_seen) 均值，可复算。"""
    gaps = [
        _gap("k1", "P001", 1, "resolved",
             first_seen="2026-06-01T00:00:00Z", resolved_at="2026-06-11T00:00:00Z"),  # 10 天
        _gap("k2", "P001", 1, "resolved",
             first_seen="2026-06-01T00:00:00Z", resolved_at="2026-06-21T00:00:00Z"),  # 20 天
        _gap("k3", "P002", 1, "open", first_seen="2026-06-01T00:00:00Z"),  # 未闭环不参与
    ]
    r = build_report(gaps)
    assert r.avg_closure_days == 15.0


def test_f3_1_avg_closure_none_when_no_resolved() -> None:
    """无已闭环缺口 → 显式 None 不虚报（诚实边界）。"""
    r = build_report([_gap("k1", "P001", 1, "open")])
    assert r.avg_closure_days is None
