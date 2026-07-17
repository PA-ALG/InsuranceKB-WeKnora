"""015 F3.1 飞轮报表——分状态计数 / TopN / 新增 / 产品分布。"""

from __future__ import annotations

from insurance_harness.flywheel.gaps import AlignedEntity, KnowledgeGap
from insurance_harness.flywheel.report import build_report


def _gap(key: str, product: str, hits: int, status: str = "open") -> KnowledgeGap:
    return KnowledgeGap(
        gap_key=key,
        entity=AlignedEntity(product_id=product),
        hit_count=hits,
        status=status,  # type: ignore[arg-type]
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
    assert r.top_unanswered == (("k2", 9), ("k3", 5))  # 降序取前 2


def test_f3_1_new_count_relative_to_previous_snapshot() -> None:
    gaps = [_gap("k1", "P001", 3), _gap("k2", "P001", 1)]
    r = build_report(gaps, previous_keys=frozenset({"k1"}))
    assert r.new_count == 1  # 仅 k2 是新增


def test_f3_1_by_product_distribution() -> None:
    gaps = [_gap("k1", "P001", 1), _gap("k2", "P001", 1), _gap("k3", "P002", 1)]
    r = build_report(gaps)
    assert r.by_product == {"P001": 2, "P002": 1}
