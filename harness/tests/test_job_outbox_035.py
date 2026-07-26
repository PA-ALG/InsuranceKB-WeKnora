"""OpenSpec 035 deterministic lane：Outbox dispatcher at-least-once 合同。

扫描只基于持久 `dispatched_at` 标记；投递成功未标记即崩溃 ⇒ 重投，
消费端以 `event_id` 幂等去重收敛。跨事务可见性（分配序 caveat）的真实
证据在 PG lane（P1.12）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from insurance_harness.db.base import Base, make_engine, make_session_factory
from insurance_harness.jobs import (
    ClaimedJob,
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
    dispatcher = OutboxDispatcher(factory)

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
    dispatcher = OutboxDispatcher(factory)
    delivered: list[str] = []

    report = dispatcher.dispatch_pending(
        space_id="space-a", deliver=lambda event: delivered.append(event.event_id)
    )

    assert report.failed_event_id is None
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
    dispatcher = OutboxDispatcher(factory)

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
    assert first_round.failed_event_id is not None
    # 投递成功但未标记：行必须仍在未投递集合中等待重投。
    pending = dispatcher.read_pending(space_id="space-a")
    assert [event.event_id for event in pending] == [first_round.failed_event_id]

    second_round = dispatcher.dispatch_pending(space_id="space-a", deliver=consumer)
    assert second_round.failed_event_id is None
    assert second_round.delivered_event_ids == (first_round.failed_event_id,)
    assert observed_effects == {first_round.failed_event_id: 1}
    assert dispatcher.read_pending(space_id="space-a") == ()


def test_p1_6_scan_is_marker_based_not_high_watermark(factory: SessionFactory) -> None:
    store = _store(factory)
    _complete_with_event(store, "space-a", "job-1", "job.succeeded", event_id="event-early")
    _complete_with_event(store, "space-a", "job-2", "job.succeeded", event_id="event-late")
    dispatcher = OutboxDispatcher(factory)

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
    dispatcher = OutboxDispatcher(factory)
    delivered: list[str] = []

    dispatcher.dispatch_pending(
        space_id="space-a", deliver=lambda event: delivered.append(event.space_id)
    )

    assert delivered == ["space-a"]
    remaining = dispatcher.read_pending(space_id="space-b")
    assert [event.space_id for event in remaining] == ["space-b"]