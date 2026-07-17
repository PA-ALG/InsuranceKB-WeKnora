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
from insurance_harness.flywheel.cursor import _encode
from insurance_harness.flywheel.gaps import AlignedEntity, stable_gap_key
from insurance_harness.flywheel.models import Trace
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
    assert res.report.top_unanswered == ((key_a, 2),)  # t1+t2 累计到同缺口
    assert res.report.by_product == {prod_ids["A"]: 1}
    assert res.unaligned_signals == 1  # t3 有信号但未对齐 → 观察队列
    assert res.next_cursor == _encode(("2026-07-01T13:00:00", "t4"))  # 游标推进过全部新 trace


def test_f3_3_pull_respects_incoming_cursor(index: MatchIndex) -> None:
    traces = [
        _trace("t1", "2026-07-01T10:00:00", f"{PRODUCT_A[1]} 等待期？", "抱歉，无法确定。"),
        _trace("t2", "2026-07-01T11:00:00", "无关问题", "抱歉，无法回答。"),
    ]
    cursor = _encode(("2026-07-01T10:00:00", "t1"))  # 已处理到 t1
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
