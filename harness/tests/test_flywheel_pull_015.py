"""015 F3.3 编排（run_pull）——F1 游标+信号 → F2 对齐+聚合 → F3 报表 一趟贯通。

覆盖：对齐命中累计同一缺口、有信号但未对齐进观察队列（不开单）、无信号跳过、
游标增量只处理新 trace、claim_lookup 驱动空知识信号。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from insurance_harness.db.models import InsuranceProduct, ProductAlias
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.flywheel.gaps import AlignedEntity, stable_gap_key
from insurance_harness.flywheel.models import SignalConfig, Trace
from insurance_harness.flywheel.pull import run_pull
from insurance_harness.product.aliases import generate_aliases
from insurance_harness.product.routing import MatchIndex

HARNESS_ROOT = Path(__file__).resolve().parents[1]

PRODUCT_A = ("1824", "平安盛世金越尊享版终身寿险", "平保寿发〔2025〕366号")
PRODUCT_B = ("1820", "平安福满分养老年金保险", "平保寿发〔2026〕88号")


@pytest.fixture()
def session(tmp_path: Path) -> Session:
    url = f"sqlite:///{tmp_path}/pull.db"
    cfg = Config(str(HARNESS_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(HARNESS_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return Session(create_engine(url))


@pytest.fixture()
def scope(bound_scope: Callable[..., KnowledgeScope]) -> KnowledgeScope:
    return bound_scope(
        tenant_id="tenant-flywheel-pull",
        raw_kb_id="raw-flywheel-pull",
        wiki_kb_id="wiki-flywheel-pull",
    )


@pytest.fixture()
def prod_ids(session: Session, scope: KnowledgeScope) -> dict[str, str]:
    ids: dict[str, str] = {}
    for key, (code, name, filing) in {"A": PRODUCT_A, "B": PRODUCT_B}.items():
        product = InsuranceProduct(
            space_id=scope.space_id,
            product_code=code,
            canonical_name=name,
            category="whole-life",
            status="在售",
            filing_no=filing,
        )
        session.add(product)
        session.flush()
        ids[key] = product.id
        for alias, alias_type in generate_aliases(name):
            session.add(ProductAlias(product_id=product.id, alias=alias, alias_type=alias_type))
    session.commit()
    return ids


@pytest.fixture()
def index(session: Session, scope: KnowledgeScope, prod_ids: dict[str, str]) -> MatchIndex:
    return MatchIndex.from_session(session, scope)


def _trace(tid: str, ts: str, q: str, a: str, **kw: object) -> Trace:
    return Trace(trace_id=tid, timestamp=ts, question=q, answer=a, **kw)  # type: ignore[arg-type]


def test_f3_3_pull_aligns_signals_into_gaps(index: MatchIndex, prod_ids: dict[str, str]) -> None:
    traces = [
        _trace("t1", "2026-07-01T10:00:00", f"{PRODUCT_A[1]} 的等待期是多久？", "抱歉，无法确定。"),
        _trace(
            "t2", "2026-07-01T11:00:00", f"{PRODUCT_A[1]} 的犹豫期几天？", "犹豫期通常为十五天。"
        ),  # 实质回答零引用 → no_citation
        _trace("t3", "2026-07-01T12:00:00", "这类保险怎么退保？", "抱歉，无法回答。"),  # 未对齐
        _trace(
            "t4",
            "2026-07-01T13:00:00",
            f"{PRODUCT_B[1]} 的保额？",
            "基本保额为五十万元。",
            source_refs=("chunk-1",),
            score=0.9,
        ),  # 有引用高分 → 无信号
    ]
    res = run_pull(traces, index)

    assert res.processed == 4
    assert res.report.total == 1  # 仅产品 A 一个缺口
    key_a = stable_gap_key(AlignedEntity(product_id=prod_ids["A"]))
    top = res.report.top_unanswered
    assert [(t.gap_key, t.hit_count) for t in top] == [(key_a, 2)]  # t1+t2 累计到同缺口
    assert top[0].sample_question  # TopN 携带脱敏问题（F3.1）
    assert res.report.by_product == {prod_ids["A"]: 1}
    assert res.unaligned_signals == 1  # t3 有信号但未对齐 → 观察队列
    # 游标推进过全部新 trace（naive 时间戳按 UTC 归一化编码）
    assert res.next_cursor == "2026-07-01T13:00:00Z|t4"


def test_f3_3_pull_respects_incoming_cursor(index: MatchIndex) -> None:
    traces = [
        _trace("t1", "2026-07-01T10:00:00", f"{PRODUCT_A[1]} 等待期？", "抱歉，无法确定。"),
        _trace("t2", "2026-07-01T11:00:00", "无关问题", "抱歉，无法回答。"),
    ]
    cursor = "2026-07-01T10:00:00Z|t1"  # 已处理到 t1（UTC 归一化编码）
    res = run_pull(traces, index, cursor=cursor)

    assert res.processed == 1  # 仅 t2 是新的
    assert res.report.total == 0  # t2 未对齐 → 无缺口
    assert res.unaligned_signals == 1


def test_f3_3_pull_empty_knowledge_via_claim_lookup(
    index: MatchIndex, prod_ids: dict[str, str]
) -> None:
    # 已对齐 + 该实体无 published claim → 空知识信号（即便回答体面有引用）。
    traces = [
        _trace(
            "t1",
            "2026-07-01T10:00:00",
            f"{PRODUCT_A[1]} 的等待期？",
            "等待期为九十天，详见条款。",
            source_refs=("chunk-9",),
            score=0.95,
        ),
    ]
    res = run_pull(traces, index, claim_lookup=lambda _key: False)
    assert res.report.total == 1  # 空知识使其成缺口

    res_has_claim = run_pull(traces, index, claim_lookup=lambda _key: True)
    assert res_has_claim.report.total == 0  # 有 claim → 非空知识 → 无其他信号 → 无缺口


def test_f3_3_pull_ignores_stale_client_aligned_entity(index: MatchIndex) -> None:
    # 红队悬疑：run_pull 对 aligned_entity 有权威——入站 trace 自带的对齐键不可借道触发空知识。
    traces = [
        Trace(
            trace_id="t1",
            timestamp="2026-07-01T10:00:00",
            question="一个无法对齐到任何产品的问题",
            answer="这是一段体面的、有引用来源的正常回答。",
            source_refs=("chunk-1",),
            score=0.95,
            aligned_entity="P999||",  # 客户端伪造的陈旧对齐键
        ),
    ]
    res = run_pull(traces, index, claim_lookup=lambda _key: False)
    assert res.unaligned_signals == 0  # 未对齐 → 清空陈旧键 → 不误触 empty_knowledge
    assert res.report.total == 0


def test_f3_3_pull_declares_empty_knowledge_coverage(index: MatchIndex) -> None:
    # 红队#3：报表须自陈覆盖面——未接 claim_lookup 时空知识不评估。
    traces = [_trace("t1", "2026-07-01T10:00:00", "问题", "答案")]
    assert run_pull(traces, index).empty_knowledge_active is False
    assert run_pull(traces, index, claim_lookup=lambda _k: True).empty_knowledge_active is True


def test_f3_3_pull_empty_knowledge_inactive_when_disabled(index: MatchIndex) -> None:
    """codex High-2：识别器配置关闭时即使接了 lookup 也不得宣称已评估。"""
    traces = [_trace("t1", "2026-07-01T10:00:00", "问题", "答案")]
    res = run_pull(
        traces, index,
        config=SignalConfig(empty_knowledge=False),
        claim_lookup=lambda _k: True,
    )
    assert res.empty_knowledge_active is False


def test_f3_3_pull_duplicate_trace_counted_once(
    index: MatchIndex, prod_ids: dict[str, str]
) -> None:
    """codex 反例2：同批同 trace_id 只计一次 hit_count。"""
    t = _trace("t1", "2026-07-01T10:00:00", f"{PRODUCT_A[1]} 的等待期？", "抱歉，无法确定。")
    res = run_pull([t, t], index)
    assert res.processed == 1  # 批内去重
    assert res.report.top_unanswered[0].hit_count == 1


def test_f2_1_pull_observations_carry_consumable_details(index: MatchIndex) -> None:
    """F2.1：观察队列保留 trace_id/脱敏问题/信号/原因明细，不是只有计数（codex 阻断4）。"""
    traces = [
        _trace("t-un", "2026-07-01T10:00:00", "这类保险怎么退保？", "抱歉，无法回答。"),
    ]
    res = run_pull(traces, index)
    assert res.unaligned_signals == 1
    assert len(res.observations) == 1
    obs = res.observations[0]
    assert obs.trace_id == "t-un"
    assert "退保" in obs.question
    assert "low_confidence_refusal" in obs.signal_types
    assert obs.reason == "no_actionable_match"
