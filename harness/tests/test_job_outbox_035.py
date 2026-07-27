"""OpenSpec 035 deterministic lane：Outbox dispatcher at-least-once 合同。

扫描只基于持久 `dispatched_at` 标记；投递成功未标记即崩溃 ⇒ 重投，
消费端以 `event_id` 幂等去重收敛。跨事务可见性（分配序 caveat）的真实
证据在 PG lane（P1.12）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from insurance_harness.db.base import Base, make_engine, make_session_factory
from insurance_harness.jobs import (
    ClaimedJob,
    DuplicateEventError,
    JobRuntimeConfig,
    JobStore,
    OutboxDispatcher,
    OutboxEventDraft,
    OutboxEventView,
    SpaceScopeError,
)
from insurance_harness.jobs.tables import WikiOutboxEvent

SessionFactory = Callable[[], Session]


@pytest.fixture
def job_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = make_engine(f"sqlite:///{tmp_path}/outbox.db")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def factory(job_engine: Engine) -> SessionFactory:
    return make_session_factory(job_engine)


def _runtime_config(**overrides: object) -> JobRuntimeConfig:
    values: dict[str, object] = {
        "lease_seconds": 300.0,
        "heartbeat_interval_seconds": 30.0,
        "max_attempts": 3,
        "backoff_seconds": (0.0,),
        "per_space_concurrency_limit": 8,
        "global_concurrency_limit": 32,
        "dispatch_backoff_seconds": (0.0,),
    }
    values.update(overrides)
    return JobRuntimeConfig.model_validate(values)


def _dispatcher(factory: SessionFactory, **overrides: object) -> OutboxDispatcher:
    return OutboxDispatcher(factory, _runtime_config(**overrides))


def _store(factory: SessionFactory) -> JobStore:
    return JobStore(
        factory,
        JobRuntimeConfig(
            lease_seconds=300.0,
            heartbeat_interval_seconds=30.0,
            max_attempts=3,
            backoff_seconds=(0.0,),
            per_space_concurrency_limit=8,
            global_concurrency_limit=32,
        ),
    )


def _complete_with_event(
    store: JobStore, space_id: str, key: str, event_type: str, event_id: str | None = None
) -> str:
    store.enqueue(space_id=space_id, job_type="compile", idempotency_key=key)
    outcome = store.claim(space_ids=(space_id,), worker_id="worker-1")
    assert isinstance(outcome, ClaimedJob)
    running = store.start(
        space_id=space_id, job_id=outcome.job.id, generation=outcome.job.lease_generation
    )
    done = store.report_success(
        space_id=space_id,
        job_id=running.id,
        generation=running.lease_generation,
        events=(
            OutboxEventDraft(event_type=event_type, payload={"key": key}, event_id=event_id),
        ),
    )
    return done.id


def test_p1_6_read_pending_is_id_ordered_and_space_scoped(factory: SessionFactory) -> None:
    store = _store(factory)
    _complete_with_event(store, "space-a", "job-1", "job.succeeded")
    _complete_with_event(store, "space-a", "job-2", "job.succeeded")
    _complete_with_event(store, "space-b", "job-3", "job.succeeded")
    dispatcher = _dispatcher(factory)

    scoped = dispatcher.read_pending(space_id="space-a")
    assert [event.space_id for event in scoped] == ["space-a", "space-a"]
    assert [event.id for event in scoped] == sorted(event.id for event in scoped)

    everything = dispatcher.read_pending_all_spaces()
    assert len(everything) == 3
    assert [event.id for event in everything] == sorted(event.id for event in everything)

    with pytest.raises(SpaceScopeError):
        dispatcher.mark_dispatched(space_id="space-b", event_id=scoped[0].event_id)


def test_p1_6_dispatch_marks_each_row_persistently(factory: SessionFactory) -> None:
    store = _store(factory)
    _complete_with_event(store, "space-a", "job-1", "job.succeeded")
    _complete_with_event(store, "space-a", "job-2", "job.succeeded")
    dispatcher = _dispatcher(factory)
    delivered: list[str] = []

    report = dispatcher.dispatch_pending(
        space_id="space-a", deliver=lambda event: delivered.append(event.event_id)
    )

    assert report.failed_event_ids == ()
    assert report.delivered_event_ids == tuple(delivered)
    assert len(delivered) == 2
    assert dispatcher.read_pending(space_id="space-a") == ()
    with factory() as session:
        marks = session.execute(select(WikiOutboxEvent.dispatched_at)).scalars().all()
    assert all(mark is not None for mark in marks)


def test_p1_6_delivered_but_unmarked_crash_converges_via_event_id_dedup(
    factory: SessionFactory,
) -> None:
    store = _store(factory)
    _complete_with_event(store, "space-a", "job-1", "job.succeeded")
    dispatcher = _dispatcher(factory)

    observed_effects: dict[str, int] = {}
    crashed = False

    def consumer(event: OutboxEventView) -> None:
        nonlocal crashed
        # 消费端以 event_id 幂等：重复投递不产生第二次可观测效果。
        if event.event_id not in observed_effects:
            observed_effects[event.event_id] = 1
        if not crashed:
            crashed = True
            raise RuntimeError("crash after delivery before mark")

    first_round = dispatcher.dispatch_pending(space_id="space-a", deliver=consumer)
    assert first_round.delivered_event_ids == ()
    assert len(first_round.failed_event_ids) == 1
    crashed_event_id = first_round.failed_event_ids[0]
    # 投递成功但未标记：行必须仍在未投递集合中等待重投。
    pending = dispatcher.read_pending(space_id="space-a")
    assert [event.event_id for event in pending] == [crashed_event_id]

    second_round = dispatcher.dispatch_pending(space_id="space-a", deliver=consumer)
    assert second_round.failed_event_ids == ()
    assert second_round.delivered_event_ids == (crashed_event_id,)
    assert observed_effects == {crashed_event_id: 1}
    assert dispatcher.read_pending(space_id="space-a") == ()


def test_p1_6_scan_is_marker_based_not_high_watermark(factory: SessionFactory) -> None:
    store = _store(factory)
    _complete_with_event(store, "space-a", "job-1", "job.succeeded", event_id="event-early")
    _complete_with_event(store, "space-a", "job-2", "job.succeeded", event_id="event-late")
    dispatcher = _dispatcher(factory)

    dispatcher.mark_dispatched(space_id="space-a", event_id="event-late")

    pending = dispatcher.read_pending(space_id="space-a")
    assert [event.event_id for event in pending] == ["event-early"]

    marked_again = dispatcher.mark_dispatched(space_id="space-a", event_id="event-late")
    later = dispatcher.mark_dispatched(space_id="space-a", event_id="event-late")
    assert marked_again.dispatched_at == later.dispatched_at  # 重复标记幂等


def test_p1_6_dispatch_scope_never_leaks_other_space_rows(factory: SessionFactory) -> None:
    store = _store(factory)
    _complete_with_event(store, "space-a", "job-1", "job.succeeded")
    _complete_with_event(store, "space-b", "job-2", "job.succeeded")
    dispatcher = _dispatcher(factory)
    delivered: list[str] = []

    dispatcher.dispatch_pending(
        space_id="space-a", deliver=lambda event: delivered.append(event.space_id)
    )

    assert delivered == ["space-a"]
    remaining = dispatcher.read_pending(space_id="space-b")
    assert [event.space_id for event in remaining] == ["space-b"]


# --- I10：毒性事件不阻塞后续事件，达配置上限后 park 出扫描窗口 ---


def test_i10_poison_event_yields_via_backoff_without_blocking_later_events(
    factory: SessionFactory,
) -> None:
    """I10 的队头阻塞修复保留；让位机制按 D-2026-07-27-16 改为持久退避。

    原实现用"失败 N 次即永久移出扫描窗口"实现让位，等于把"瞬时消费端不可用"
    误判为"永久毒性"并静默丢弃已提交行（违反 P1.6）。现在失败只推迟
    `next_dispatch_at`，行始终留在扫描集合内。
    """
    store = _store(factory)
    for index in range(4):
        _complete_with_event(
            store, "space-a", f"job-{index}", "job.succeeded", event_id=f"evt-{index}"
        )
    dispatcher = _dispatcher(factory, dispatch_backoff_seconds=(0.0, 3600.0))

    def deliver(event: OutboxEventView) -> None:
        if event.event_id == "evt-0":
            raise RuntimeError("poison event")

    first = dispatcher.dispatch_pending(space_id="space-a", deliver=deliver)
    assert first.delivered_event_ids == ("evt-1", "evt-2", "evt-3")  # 不再队头阻塞
    assert first.failed_event_ids == ("evt-0",)

    # 第一档退避为 0：立刻仍可重试（只让位，不出局）。
    second = dispatcher.dispatch_pending(space_id="space-a", deliver=deliver)
    assert second.delivered_event_ids == ()
    assert second.failed_event_ids == ("evt-0",)

    # 第二档退避 1 小时：本轮不到期，因此不被扫到——但**仍在集合内**。
    third = dispatcher.dispatch_pending(space_id="space-a", deliver=deliver)
    assert third.delivered_event_ids == ()
    assert third.failed_event_ids == ()
    assert dispatcher.read_pending(space_id="space-a") == ()  # 退避未到期

    backed_off = dispatcher.read_backed_off(space_id="space-a")
    assert [event.event_id for event in backed_off] == ["evt-0"]
    assert backed_off[0].dispatch_attempts == 2
    assert backed_off[0].dispatched_at is None  # 退避 ≠ 假装投递成功
    with factory() as session:
        undispatched = session.scalar(
            select(func.count())
            .select_from(WikiOutboxEvent)
            .where(WikiOutboxEvent.dispatched_at.is_(None))
        )
    assert undispatched == 1  # 行仍在库内待投，不是被丢弃


def test_q21_transient_consumer_outage_recovers_at_least_once(
    factory: SessionFactory,
) -> None:
    """P1.6：连续失败超过任何退避档位后恢复，健康事件仍必须被投递。"""
    store = _store(factory)
    for index in range(3):
        _complete_with_event(
            store, "space-a", f"job-{index}", "job.succeeded", event_id=f"evt-{index}"
        )
    dispatcher = _dispatcher(factory, dispatch_backoff_seconds=(0.0,))
    broker_up = False

    def deliver(event: OutboxEventView) -> None:
        if not broker_up:
            raise RuntimeError("broker down")

    for _round in range(4):  # 远超原硬上限 5 之外的失败次数也不出局
        report = dispatcher.dispatch_pending(space_id="space-a", deliver=deliver)
        assert report.delivered_event_ids == ()
        assert len(report.failed_event_ids) == 3

    broker_up = True
    recovered = dispatcher.dispatch_pending(space_id="space-a", deliver=deliver)

    assert set(recovered.delivered_event_ids) == {"evt-0", "evt-1", "evt-2"}
    assert dispatcher.read_pending(space_id="space-a") == ()
    with factory() as session:
        undispatched = session.scalar(
            select(func.count())
            .select_from(WikiOutboxEvent)
            .where(WikiOutboxEvent.dispatched_at.is_(None))
        )
    assert undispatched == 0


def test_q21_dispatch_backoff_delay_comes_from_configuration() -> None:
    """接受侧 + 配置驱动：退避档位只来自 `JobRuntimeConfig`。"""
    config = _runtime_config(dispatch_backoff_seconds=(1.0, 10.0, 60.0))
    assert config.dispatch_backoff_delay(attempts=1) == 1.0
    assert config.dispatch_backoff_delay(attempts=2) == 10.0
    assert config.dispatch_backoff_delay(attempts=3) == 60.0
    assert config.dispatch_backoff_delay(attempts=99) == 60.0  # 超出取最后一档
    with pytest.raises(ValueError):
        config.dispatch_backoff_delay(attempts=0)


def test_i7_event_id_is_unique_per_space_and_duplicate_is_typed(
    factory: SessionFactory,
) -> None:
    store = _store(factory)
    _complete_with_event(store, "space-a", "job-1", "job.succeeded", event_id="shared-id")
    # 跨 Space 允许同一 event_id：事件流按 Space 隔离（P1.8）。
    _complete_with_event(store, "space-b", "job-1", "job.succeeded", event_id="shared-id")

    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="job-2")
    outcome = store.claim(space_ids=("space-a",), worker_id="worker-1")
    assert isinstance(outcome, ClaimedJob)
    running = store.start(
        space_id="space-a", job_id=outcome.job.id, generation=outcome.job.lease_generation
    )

    with pytest.raises(DuplicateEventError):
        store.report_success(
            space_id="space-a",
            job_id=running.id,
            generation=running.lease_generation,
            events=(
                OutboxEventDraft(
                    event_type="job.succeeded", payload={}, event_id="shared-id"
                ),
            ),
        )

    # typed 拒绝且完成事务整体回滚：任务仍 running，零第二行。
    assert store.get_job(space_id="space-a", job_id=running.id).state.value == "running"
    with factory() as session:
        count = session.scalar(
            select(func.count())
            .select_from(WikiOutboxEvent)
            .where(WikiOutboxEvent.event_id == "shared-id")
        )
    assert count == 2