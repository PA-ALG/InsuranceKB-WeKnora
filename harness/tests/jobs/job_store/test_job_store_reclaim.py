"""JobStore（SQLite）：start、租约过期、reclaim 代次与有界维护批次。"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import func, select, text

from insurance_harness.jobs import (
    ClaimedJob,
    ErrorClass,
    IllegalTransitionError,
    JobState,
    JobStore,
    LeaseExpiredError,
    OutboxEventDraft,
    StaleGenerationError,
    database_now,
)

# `append_job_event` 已不在公共出口（P1.6 事件追加边界，D-2026-07-27-16）：
# 只能在完成事务内追加。测试直接引内部模块以验证该内部合同。
from insurance_harness.jobs.outbox import append_job_event
from insurance_harness.jobs.tables import WikiOutboxEvent
from tests.jobs.job_store.helpers import SessionFactory, _claimed, force_expire, make_store


def database_now_utc(store: JobStore) -> datetime:
    """按数据库时钟读当前时间（过期断言必须与实现同一时钟）。"""
    with store._session_factory() as session:  # noqa: SLF001 - 测试读同一时钟
        return database_now(session)


def test_p1_1_start_moves_leased_to_running_and_counts_attempt(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="job-1")
    claimed = _claimed(store, "space-a")

    running = store.start(
        space_id="space-a", job_id=claimed.id, generation=claimed.lease_generation
    )

    assert running.state is JobState.RUNNING
    assert running.attempt == 1
    assert running.started_at is not None

    with pytest.raises(StaleGenerationError):
        store.start(space_id="space-a", job_id=claimed.id, generation=0)
    with pytest.raises(IllegalTransitionError):
        store.start(space_id="space-a", job_id=claimed.id, generation=claimed.lease_generation)


def test_p1_1_reclaim_records_lease_expired_retryable_and_requeues_below_limit(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="job-1")
    claimed = _claimed(store, "space-a")
    force_expire(factory, claimed.id)

    report = store.reclaim_expired_leases(space_ids=("space-a",))

    assert report.requeued_job_ids == (claimed.id,)
    assert report.dead_lettered_job_ids == ()
    job = store.get_job(space_id="space-a", job_id=claimed.id)
    assert job.state is JobState.QUEUED
    assert job.error_class is ErrorClass.RETRYABLE
    assert job.error_summary == "lease_expired"
    assert job.worker_id is None
    assert job.lease_expires_at is None
    # C2：回收本身使 generation 单调 +1，立即失效被逐出 worker 的 fencing。
    assert job.lease_generation == claimed.lease_generation + 1

    retaken = _claimed(store, "space-a", worker_id="worker-2")
    assert retaken.lease_generation == claimed.lease_generation + 2


def test_c2_reclaim_generation_bump_fences_evicted_worker_immediately(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="job-1")
    claimed = _claimed(store, "space-a")
    running = store.start(
        space_id="space-a", job_id=claimed.id, generation=claimed.lease_generation
    )
    force_expire(factory, running.id)
    store.reclaim_expired_leases(space_ids=("space-a",))

    # 回收后（尚未有新 claim）：被逐出 worker 的一切写入即刻 stale。
    with pytest.raises(StaleGenerationError):
        store.heartbeat(space_id="space-a", job_id=running.id, generation=running.lease_generation)
    with pytest.raises(StaleGenerationError):
        store.report_success(
            space_id="space-a", job_id=running.id, generation=running.lease_generation
        )
    with factory() as session:
        with session.begin():
            with pytest.raises(StaleGenerationError):
                append_job_event(
                    session,
                    space_id="space-a",
                    job_id=running.id,
                    generation=running.lease_generation,
                    draft=OutboxEventDraft(event_type="job.progress", payload={}),
                )
    with factory() as session:
        outbox_rows = session.scalar(select(func.count()).select_from(WikiOutboxEvent))
    assert outbox_rows == 0
    assert store.get_job(space_id="space-a", job_id=running.id).state is JobState.QUEUED


def test_c2_outbox_append_requires_running_state(factory: SessionFactory) -> None:
    store = make_store(factory)
    queued = store.enqueue(space_id="space-a", job_type="compile", idempotency_key="q").job
    with factory() as session:
        with session.begin():
            with pytest.raises(IllegalTransitionError):
                append_job_event(
                    session,
                    space_id="space-a",
                    job_id=queued.id,
                    generation=queued.lease_generation,
                    draft=OutboxEventDraft(event_type="job.custom", payload={}),
                )

    leased = _claimed(store, "space-a")
    with factory() as session:
        with session.begin():
            with pytest.raises(IllegalTransitionError):
                append_job_event(
                    session,
                    space_id="space-a",
                    job_id=leased.id,
                    generation=leased.lease_generation,
                    draft=OutboxEventDraft(event_type="job.custom", payload={}),
                )

    running = store.start(space_id="space-a", job_id=leased.id, generation=leased.lease_generation)
    store.report_success(space_id="space-a", job_id=running.id, generation=running.lease_generation)
    # 终态行携带仍然匹配的 generation：state guard 必须单独拒绝（B1 probe）。
    with factory() as session:
        with session.begin():
            with pytest.raises(IllegalTransitionError):
                append_job_event(
                    session,
                    space_id="space-a",
                    job_id=running.id,
                    generation=running.lease_generation,
                    draft=OutboxEventDraft(event_type="job.succeeded.phantom", payload={}),
                )
    with factory() as session:
        outbox_rows = session.scalar(select(func.count()).select_from(WikiOutboxEvent))
    assert outbox_rows == 0


def test_c1_expired_lease_outside_scope_does_not_hold_global_limit(
    factory: SessionFactory,
) -> None:
    """C1 的反饥饿意图保留，机制按 D-2026-07-27-16 改为「回收后放行」。

    原实现让过期行退出限额分母以避免饥饿，但同时它们仍保有写权威（P1.3），
    于是限额被停滞 worker 无界抬高。冻结后的合同改为：分母包含全部
    `leased | running`，饱和时先做一次无 Space 过滤的有界回收再重算。因此
    scope 外的过期行**会**被 fenced（generation +1）——这是刻意的契约收紧，
    不再断言"scope 外零变更"；C1 真正要保住的是「不因外域过期行永久饥饿」
    与「调用方拿不到跨 Space 任务内容」，两者在下方断言。
    """
    crasher = make_store(factory, global_concurrency_limit=1)
    crasher.enqueue(space_id="space-dead", job_type="compile", idempotency_key="k")
    dead = _claimed(crasher, "space-dead", worker_id="worker-crash")
    force_expire(factory, dead.id)

    healthy = make_store(factory, lease_seconds=300.0, global_concurrency_limit=1)
    healthy.enqueue(space_id="space-live", job_type="compile", idempotency_key="k")

    outcome = healthy.claim(space_ids=("space-live",), worker_id="worker-live")

    assert isinstance(outcome, ClaimedJob), "外域过期行不得造成永久饥饿"
    assert outcome.job.space_id == "space-live", "调用方不得拿到跨 Space 任务"
    reclaimed = healthy.get_job(space_id="space-dead", job_id=dead.id)
    assert reclaimed.state is JobState.QUEUED
    assert reclaimed.lease_generation == dead.lease_generation + 1
    # 被逐出的 crasher 即刻失去写权威（generation 与 lease 双重失效）。
    with pytest.raises(StaleGenerationError):
        crasher.start(space_id="space-dead", job_id=dead.id, generation=dead.lease_generation)


def test_m14_heartbeat_cannot_revive_expired_lease(factory: SessionFactory) -> None:
    store = make_store(factory)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="k")
    claimed = _claimed(store, "space-a")
    force_expire(factory, claimed.id)

    reviver = make_store(factory, lease_seconds=600.0)
    with pytest.raises(LeaseExpiredError):
        reviver.heartbeat(
            space_id="space-a", job_id=claimed.id, generation=claimed.lease_generation
        )

    unchanged = store.get_job(space_id="space-a", job_id=claimed.id)
    assert unchanged.state is JobState.LEASED
    # 断言 lease 未被续租：仍停在回拨后的过去时刻（不是 claim 时的原值）。
    assert unchanged.lease_expires_at is not None
    assert unchanged.lease_expires_at < database_now_utc(store)


def test_i4_claim_and_reclaim_maintenance_batches_are_bounded_by_config(
    factory: SessionFactory,
) -> None:
    store = make_store(factory, lease_seconds=300.0, maintenance_batch_size=2)
    ids = []
    for index in range(3):
        store.enqueue(space_id="space-a", job_type="compile", idempotency_key=f"k{index}")
        ids.append(_claimed(store, "space-a", worker_id=f"w{index}").id)
    with factory() as session:  # 测试脚手架：把三个 lease 统一回拨为已过期
        with session.begin():
            session.execute(
                text("UPDATE wiki_jobs SET lease_expires_at = '2000-01-01 00:00:00.000000+00:00'")
            )

    first = store.reclaim_expired_leases(space_ids=("space-a",))
    assert len(first.requeued_job_ids) == 2  # 单次回收受 maintenance_batch_size 约束

    second = store.reclaim_expired_leases(space_ids=("space-a",))
    assert len(second.requeued_job_ids) == 1
    states = [store.get_job(space_id="space-a", job_id=job_id).state for job_id in ids]
    assert states == [JobState.QUEUED, JobState.QUEUED, JobState.QUEUED]


def test_p1_10_reclaim_routes_to_dead_letter_at_max_attempts(
    factory: SessionFactory,
) -> None:
    store = make_store(factory, max_attempts=1)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="poison")
    claimed = _claimed(store, "space-a")
    store.start(space_id="space-a", job_id=claimed.id, generation=claimed.lease_generation)
    force_expire(factory, claimed.id)

    report = store.reclaim_expired_leases(space_ids=("space-a",))

    assert report.requeued_job_ids == ()
    assert report.dead_lettered_job_ids == (claimed.id,)
    job = store.get_job(space_id="space-a", job_id=claimed.id)
    assert job.state is JobState.DEAD_LETTER
    assert job.attempt == 1
    assert job.error_class is ErrorClass.RETRYABLE
    assert job.error_summary == "lease_expired"
    assert job.finished_at is not None
    assert job.idempotency_key == "poison"


def test_p1_3_claim_reclaims_expired_lease_and_takes_strictly_newer_generation(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="job-1")
    first = _claimed(store, "space-a", worker_id="worker-a")
    force_expire(factory, first.id)

    second = _claimed(store, "space-a", worker_id="worker-b")

    assert second.id == first.id
    assert second.lease_generation > first.lease_generation
    assert second.worker_id == "worker-b"


def test_p1_3_reclaim_leaves_active_leases_untouched_and_is_space_scoped(
    factory: SessionFactory,
) -> None:
    active_store = make_store(factory, lease_seconds=300.0)
    active_store.enqueue(space_id="space-a", job_type="compile", idempotency_key="alive")
    alive = _claimed(active_store, "space-a")

    expired_store = make_store(factory)
    expired_store.enqueue(space_id="space-b", job_type="compile", idempotency_key="expired")
    expired = _claimed(expired_store, "space-b")
    force_expire(factory, expired.id)

    report = active_store.reclaim_expired_leases(space_ids=("space-a",))

    assert report.requeued_job_ids == ()
    assert report.dead_lettered_job_ids == ()
    assert active_store.get_job(space_id="space-a", job_id=alive.id).state is JobState.LEASED
    assert expired_store.get_job(space_id="space-b", job_id=expired.id).state is JobState.LEASED
