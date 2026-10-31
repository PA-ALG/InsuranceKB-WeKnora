"""JobStore（PostgreSQL）：强杀接管、毒性任务、指标、租约与跨 Space 写入。"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from insurance_harness.jobs import (
    ClaimedJob,
    DomainWriteSpec,
    ErrorClass,
    JobFailure,
    JobState,
    JobStore,
    NoClaimableJob,
    OutboxDispatcher,
    OutboxEventDraft,
    SpaceScopeError,
    StaleGenerationError,
    database_now,
    global_job_metrics,
    space_job_metrics,
)
from tests.jobs.job_store_postgres.helpers import (
    CONNECT_ARGS,
    FUTURE_TIMEOUT_S,
    PostgresRuntime,
    _config,
    _force_expire,
    _outbox_count,
    _space,
    _start_running,
    _store,
)

# --- T10：崩溃接管端到端恰好一份领域结果；毒性任务循环有界 ---


@pytest.mark.integration_postgres
def test_p1_10_forced_kill_takeover_yields_exactly_one_domain_result(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("crash")
    domain_table = f"domain_{uuid.uuid4().hex[:12]}"
    application_name = f"worker_a_{uuid.uuid4().hex[:8]}"
    with postgres_runtime.engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE TABLE "{domain_table}" (job_id TEXT PRIMARY KEY)')

    # worker A 使用独立连接池，便于用 pg_terminate_backend 强制终止。
    crash_engine = create_engine(
        postgres_runtime.engine.url,
        future=True,
        connect_args={**CONNECT_ARGS, "application_name": application_name},
    )
    crash_factory: sessionmaker[Session] = sessionmaker(
        bind=crash_engine, expire_on_commit=False, future=True
    )
    try:
        worker_a = JobStore(crash_factory, _config())
        job_id, generation_a = _start_running(worker_a, space_id, "job-1", "worker-a")
        _force_expire(postgres_runtime, job_id)

        # 强制终止 A 的全部后端连接：不执行任何清理（P1.10）。
        with postgres_runtime.factory() as session:
            session.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE application_name = :application_name AND pid <> pg_backend_pid()"
                ),
                {"application_name": application_name},
            )
            session.commit()

        worker_b = _store(postgres_runtime, lease_seconds=300.0)
        takeover = worker_b.claim(space_ids=(space_id,), worker_id="worker-b")
        assert isinstance(takeover, ClaimedJob)
        assert takeover.job.id == job_id
        generation_b = takeover.job.lease_generation
        assert generation_b > generation_a
        worker_b.start(space_id=space_id, job_id=job_id, generation=generation_b)

        domain_writes = (DomainWriteSpec(table=domain_table, values={"job_id": job_id}),)

        done = worker_b.report_success(
            space_id=space_id,
            job_id=job_id,
            generation=generation_b,
            events=(OutboxEventDraft(event_type="job.succeeded", payload={"job": job_id}),),
            domain_writes=domain_writes,
        )
        assert done.state is JobState.SUCCEEDED

        # A「苏醒」（新连接的同进程重放）：旧 generation 提交被 fencing 拒绝。
        revived_a = _store(postgres_runtime)
        with pytest.raises(StaleGenerationError):
            revived_a.report_success(
                space_id=space_id,
                job_id=job_id,
                generation=generation_a,
                events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
                domain_writes=domain_writes,
            )

        with postgres_runtime.factory() as session:
            assert session.scalar(text(f'SELECT count(*) FROM "{domain_table}"')) == 1
        assert _outbox_count(postgres_runtime, space_id) == 1
    finally:
        crash_engine.dispose()


@pytest.mark.integration_postgres
def test_p1_10_poison_task_crash_loop_is_bounded_by_max_attempts(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("poison")
    store = _store(postgres_runtime, max_attempts=3)
    store.enqueue(space_id=space_id, job_type="compile", idempotency_key="poison")

    generations: list[int] = []
    for _round in range(3):
        outcome = store.claim(space_ids=(space_id,), worker_id="worker-a")
        assert isinstance(outcome, ClaimedJob)
        generations.append(outcome.job.lease_generation)
        running = store.start(
            space_id=space_id,
            job_id=outcome.job.id,
            generation=outcome.job.lease_generation,
        )
        assert running.attempt == _round + 1
        # worker 随即「崩溃」：不 heartbeat、不提交任何结果，lease 自然过期。
        _force_expire(postgres_runtime, outcome.job.id)

    final = store.claim(space_ids=(space_id,), worker_id="worker-b")
    assert isinstance(final, NoClaimableJob)  # 回收路由进 dead_letter，不再 requeue

    job_id = generations and store.enqueue(
        space_id=space_id, job_type="compile", idempotency_key="poison"
    ).job.id
    assert isinstance(job_id, str)
    dead = store.get_job(space_id=space_id, job_id=job_id)
    assert dead.state is JobState.DEAD_LETTER
    assert dead.attempt == 3
    assert dead.error_class is ErrorClass.RETRYABLE
    assert dead.error_summary == "lease_expired"
    # C2 修复后每次回收也 +1：三次「回收+领取」共 6 个 generation，仍有界。
    assert dead.lease_generation == 6
    assert generations == [1, 3, 5]


# --- T11：指标查询与预置分布精确一致（per-Space 精确 + 全局按增量精确） ---


@pytest.mark.integration_postgres
def test_p1_9_metrics_match_seeded_distribution_on_postgres(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_a = _space("metrics-a")
    space_b = _space("metrics-b")
    with postgres_runtime.factory() as session:
        global_before = global_job_metrics(session)

    store = _store(postgres_runtime, backoff_seconds=(3600.0,))
    oldest_id, oldest_generation = _start_running(store, space_a, "retrying", "worker-a")
    retry_row = store.report_failure(
        space_id=space_a,
        job_id=oldest_id,
        generation=oldest_generation,
        failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="wait"),
    )
    for key in ("dead-1", "dead-2"):
        job_id, generation = _start_running(store, space_a, key, "worker-a")
        store.report_failure(
            space_id=space_a,
            job_id=job_id,
            generation=generation,
            failure=JobFailure(error_class=ErrorClass.NON_RETRYABLE, summary="fatal"),
        )
    _start_running(store, space_a, "running-1", "worker-a")
    for key in ("queued-1", "queued-2", "queued-3"):
        store.enqueue(space_id=space_a, job_type="compile", idempotency_key=key)
    store.enqueue(space_id=space_b, job_type="compile", idempotency_key="b-queued")
    # 回拨最老可调度行（retry_wait）的 enqueued_at，锁定精确年龄下界。
    backdated = retry_row.enqueued_at - timedelta(hours=1)
    with postgres_runtime.factory() as session:
        session.execute(
            text("UPDATE wiki_jobs SET enqueued_at = :backdated WHERE id = :id"),
            {"backdated": backdated, "id": oldest_id},
        )
        session.commit()

    with postgres_runtime.factory() as session:
        before = database_now(session)
        metrics_a = space_job_metrics(session, space_id=space_a)
        metrics_b = space_job_metrics(session, space_id=space_b)
        global_after = global_job_metrics(session)
        after = database_now(session)

    assert metrics_a.state_counts == {
        JobState.QUEUED: 3,
        JobState.LEASED: 0,
        JobState.RUNNING: 1,
        JobState.SUCCEEDED: 0,
        JobState.RETRY_WAIT: 1,
        JobState.AWAITING_HUMAN: 0,
        JobState.BLOCKED: 0,
        JobState.DEAD_LETTER: 2,
    }
    assert metrics_a.queue_depth == 3
    assert metrics_a.retry_wait_count == 1
    assert metrics_a.dead_letter_count == 2
    assert metrics_a.attempt_total == 4
    # 最老可调度年龄由回拨的 retry_wait 行精确决定（覆盖 retry_wait，非仅 queued）。
    assert metrics_a.oldest_schedulable_age_seconds is not None
    lower = (before - backdated).total_seconds()
    upper = (after - backdated).total_seconds()
    assert lower <= metrics_a.oldest_schedulable_age_seconds <= upper
    assert metrics_a.oldest_schedulable_age_seconds >= 3600.0
    assert metrics_b.state_counts[JobState.QUEUED] == 1
    assert metrics_b.attempt_total == 0

    # 全局入口按增量精确：共享库中其余 Space 的行保持不变。
    delta = {
        state: global_after.state_counts[state] - global_before.state_counts[state]
        for state in JobState
    }
    assert delta == {
        JobState.QUEUED: 4,
        JobState.LEASED: 0,
        JobState.RUNNING: 1,
        JobState.SUCCEEDED: 0,
        JobState.RETRY_WAIT: 1,
        JobState.AWAITING_HUMAN: 0,
        JobState.BLOCKED: 0,
        JobState.DEAD_LETTER: 2,
    }
    assert global_after.attempt_total - global_before.attempt_total == 4
    assert retry_row.state is JobState.RETRY_WAIT


# --- C1：scope 外过期 lease 不得永久占用全局限额（独立数据库） ---


@pytest.mark.integration_postgres
def test_c1_expired_foreign_lease_does_not_consume_global_limit(
    isolated_postgres_runtime: PostgresRuntime,
) -> None:
    runtime = isolated_postgres_runtime
    space_dead = _space("dead")
    space_live = _space("live")
    crasher = _store(runtime, global_concurrency_limit=1)
    crasher.enqueue(space_id=space_dead, job_type="compile", idempotency_key="k")
    dead = crasher.claim(space_ids=(space_dead,), worker_id="worker-crash")
    assert isinstance(dead, ClaimedJob)
    _force_expire(runtime, dead.job.id)

    healthy = _store(runtime, lease_seconds=300.0, global_concurrency_limit=1)
    healthy.enqueue(space_id=space_live, job_type="compile", idempotency_key="k")

    outcome = healthy.claim(space_ids=(space_live,), worker_id="worker-live")

    # C1 的反饥饿意图保留；机制按 D-2026-07-27-16 改为「饱和时先做无 Space
    # 过滤的有界回收再重算」——因此 scope 外过期行会被 fenced（generation +1），
    # 不再断言"scope 外零变更"。保住的是：不永久饥饿 + 调用方拿不到跨 Space
    # 任务内容 + 过期持有者即刻失去写权威。
    assert isinstance(outcome, ClaimedJob)  # 修复前：永远 global_concurrency_limit
    assert outcome.job.space_id == space_live
    reclaimed = healthy.get_job(space_id=space_dead, job_id=dead.job.id)
    assert reclaimed.state is JobState.QUEUED
    assert reclaimed.lease_generation == dead.job.lease_generation + 1
    with pytest.raises(StaleGenerationError):
        crasher.start(
            space_id=space_dead,
            job_id=dead.job.id,
            generation=dead.job.lease_generation,
        )
    # 有效（未过期）lease 已达全局限额：下一个 claim 被全局限额挡住。
    healthy.enqueue(space_id=space_live, job_type="compile", idempotency_key="k2")
    blocked = healthy.claim(space_ids=(space_live,), worker_id="worker-live")
    assert isinstance(blocked, NoClaimableJob)
    assert blocked.reason == "global_concurrency_limit"


# --- I3：advisory 锁等待不吞噬 lease 时长（clock_timestamp 语义） ---


@pytest.mark.integration_postgres
def test_i3_lease_duration_survives_advisory_lock_wait(
    postgres_runtime: PostgresRuntime,
) -> None:
    from insurance_harness.jobs.store import _CLAIM_LOCK_KEY

    space_id = _space("clockwait")
    # lease 必须大于 heartbeat 间隔（D-2026-07-27-16），短 lease 场景同步调小。
    store = _store(postgres_runtime, lease_seconds=5.0, heartbeat_interval_seconds=1.0)
    store.enqueue(space_id=space_id, job_type="compile", idempotency_key="k")
    lock_held = threading.Event()

    def hold_claim_lock() -> None:
        with postgres_runtime.factory() as session:
            with session.begin():
                session.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"), {"key": _CLAIM_LOCK_KEY}
                )
                lock_held.set()
                time.sleep(1.5)

    thread = threading.Thread(target=hold_claim_lock)
    thread.start()
    assert lock_held.wait(timeout=10)
    outcome = store.claim(space_ids=(space_id,), worker_id="worker-a")
    thread.join(timeout=FUTURE_TIMEOUT_S)
    assert isinstance(outcome, ClaimedJob)

    with postgres_runtime.factory() as session:
        remaining = session.execute(
            text(
                "SELECT extract(epoch FROM (lease_expires_at - clock_timestamp())) "
                "FROM wiki_jobs WHERE id = :id"
            ),
            {"id": outcome.job.id},
        ).scalar_one()
    # 修复前：lease 锚定事务开始时刻，等待 1.5s 后仅剩 ~3.5s 甚至立即过期。
    assert float(remaining) > 3.5

    thief = _store(postgres_runtime, lease_seconds=5.0, heartbeat_interval_seconds=1.0)
    stolen = thief.claim(space_ids=(space_id,), worker_id="thief")
    assert isinstance(stolen, NoClaimableJob)  # 新 lease 未过期，不可被立即接管
    current = store.get_job(space_id=space_id, job_id=outcome.job.id)
    assert current.worker_id == "worker-a"
    assert current.lease_generation == outcome.job.lease_generation


# --- P1.8：跨 Space 写入与 outbox 读取在 PG 全部 fail closed ---


@pytest.mark.integration_postgres
def test_p1_8_cross_space_writes_and_outbox_reads_fail_closed_on_postgres(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_a = _space("iso-a")
    space_b = _space("iso-b")
    store = _store(postgres_runtime)
    job_id, generation = _start_running(store, space_a, "job-1", "worker-a")

    with pytest.raises(SpaceScopeError):
        store.heartbeat(space_id=space_b, job_id=job_id, generation=generation)
    with pytest.raises(SpaceScopeError):
        store.start(space_id=space_b, job_id=job_id, generation=generation)
    with pytest.raises(SpaceScopeError):
        store.report_success(space_id=space_b, job_id=job_id, generation=generation)
    with pytest.raises(SpaceScopeError):
        store.report_failure(
            space_id=space_b,
            job_id=job_id,
            generation=generation,
            failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="cross"),
        )
    with pytest.raises(SpaceScopeError):
        store.resume_after_decision(space_id=space_b, job_id=job_id)
    with pytest.raises(SpaceScopeError):
        store.get_job(space_id=space_b, job_id=job_id)

    done = store.report_success(
        space_id=space_a,
        job_id=job_id,
        generation=generation,
        events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
    )
    assert done.state is JobState.SUCCEEDED
    dispatcher = OutboxDispatcher(postgres_runtime.factory, _config())
    event_id = dispatcher.read_pending(space_id=space_a)[0].event_id
    assert dispatcher.read_pending(space_id=space_b) == ()  # 零行返回
    with pytest.raises(SpaceScopeError):
        dispatcher.mark_dispatched(space_id=space_b, event_id=event_id)
    current = store.get_job(space_id=space_a, job_id=job_id)
    assert current.state is JobState.SUCCEEDED  # 目标行零变更
