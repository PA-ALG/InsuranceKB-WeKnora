"""JobStore（PostgreSQL）：完成事务与 outbox 原子性、迟到 worker、重试与 Decision。"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from insurance_harness.jobs import (
    ClaimedJob,
    DomainWriteSpec,
    ErrorClass,
    IllegalTransitionError,
    JobFailure,
    JobState,
    NoClaimableJob,
    OutboxDispatcher,
    OutboxEventDraft,
    StaleGenerationError,
)

# `append_job_event` 已不在公共出口（P1.6 事件追加边界，D-2026-07-27-16）：
# 只能在完成事务内追加。测试直接引内部模块以验证该内部合同。
from insurance_harness.jobs.outbox import append_job_event
from insurance_harness.jobs.tables import WikiOutboxEvent
from tests.jobs.job_store_postgres.helpers import (
    FUTURE_TIMEOUT_S,
    PostgresRuntime,
    _config,
    _force_expire,
    _outbox_count,
    _space,
    _start_running,
    _store,
)


@pytest.mark.integration_postgres
def test_p1_6_completion_interrupt_before_commit_leaves_neither_row(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("atomic")
    domain_table = f"domain_{uuid.uuid4().hex[:12]}"
    with postgres_runtime.engine.begin() as connection:
        connection.exec_driver_sql(
            f'CREATE TABLE "{domain_table}" (job_id TEXT PRIMARY KEY)'
        )
    store = _store(postgres_runtime)
    job_id, generation = _start_running(store, space_id, "job-1", "worker-a")

    # 声明式领域写（P1.5，D-2026-07-27-16）：存储层自己执行，调用方无句柄。
    domain_writes = (DomainWriteSpec(table=domain_table, values={"job_id": job_id}),)

    def interrupt(_session: Session) -> None:
        raise RuntimeError("inject-commit-crash-035")

    sqlalchemy_event.listen(postgres_runtime.factory, "before_commit", interrupt)
    try:
        with pytest.raises(RuntimeError, match="inject-commit-crash-035"):
            store.report_success(
                space_id=space_id,
                job_id=job_id,
                generation=generation,
                events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
                domain_writes=domain_writes,
            )
    finally:
        sqlalchemy_event.remove(postgres_runtime.factory, "before_commit", interrupt)

    with postgres_runtime.factory() as session:
        assert session.scalar(text(f'SELECT count(*) FROM "{domain_table}"')) == 0
    assert _outbox_count(postgres_runtime, space_id) == 0
    assert store.get_job(space_id=space_id, job_id=job_id).state is JobState.RUNNING

    # 重放同一完成事务：领域行与 outbox 事件各恰好出现一次。
    replay = store.report_success(
        space_id=space_id,
        job_id=job_id,
        generation=generation,
        events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
        domain_writes=domain_writes,
    )
    assert replay.state is JobState.SUCCEEDED
    with postgres_runtime.factory() as session:
        assert session.scalar(text(f'SELECT count(*) FROM "{domain_table}"')) == 1
    assert _outbox_count(postgres_runtime, space_id) == 1

    with pytest.raises(IllegalTransitionError):
        store.report_success(
            space_id=space_id,
            job_id=job_id,
            generation=generation,
            events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
            domain_writes=domain_writes,
        )
    with postgres_runtime.factory() as session:
        assert session.scalar(text(f'SELECT count(*) FROM "{domain_table}"')) == 1
    assert _outbox_count(postgres_runtime, space_id) == 1


@pytest.mark.integration_postgres
def test_p1_3_late_worker_every_write_path_is_fenced_after_takeover(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("fence")
    expiring = _store(postgres_runtime)
    healthy = _store(postgres_runtime, lease_seconds=300.0)
    job_id, old_generation = _start_running(expiring, space_id, "job-1", "worker-a")
    _force_expire(postgres_runtime, job_id)

    takeover = healthy.claim(space_ids=(space_id,), worker_id="worker-b")
    assert isinstance(takeover, ClaimedJob)
    assert takeover.job.id == job_id
    new_generation = takeover.job.lease_generation
    assert new_generation > old_generation

    with pytest.raises(StaleGenerationError):
        healthy.heartbeat(space_id=space_id, job_id=job_id, generation=old_generation)
    with pytest.raises(StaleGenerationError):
        healthy.start(space_id=space_id, job_id=job_id, generation=old_generation)
    with pytest.raises(StaleGenerationError):
        healthy.report_success(
            space_id=space_id,
            job_id=job_id,
            generation=old_generation,
            events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
        )
    with pytest.raises(StaleGenerationError):
        healthy.report_failure(
            space_id=space_id,
            job_id=job_id,
            generation=old_generation,
            failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="late"),
        )
    with postgres_runtime.factory() as session:
        with session.begin():
            with pytest.raises(StaleGenerationError):
                append_job_event(
                    session,
                    space_id=space_id,
                    job_id=job_id,
                    generation=old_generation,
                    draft=OutboxEventDraft(event_type="job.custom", payload={}),
                )

    assert _outbox_count(postgres_runtime, space_id) == 0
    current = healthy.get_job(space_id=space_id, job_id=job_id)
    assert current.state is JobState.LEASED
    assert current.lease_generation == new_generation
    assert current.worker_id == "worker-b"


# --- T7：retryable → retry_wait → queued 与 max_attempts → dead_letter（配置驱动） ---


@pytest.mark.integration_postgres
def test_p1_4_retry_loop_reaches_dead_letter_only_via_configured_policy(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("retry")
    store = _store(postgres_runtime, backoff_seconds=(0.0,), max_attempts=2)
    job_id, generation = _start_running(store, space_id, "job-1", "worker-a")

    first_failure = store.report_failure(
        space_id=space_id,
        job_id=job_id,
        generation=generation,
        failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="first failure"),
    )
    assert first_failure.state is JobState.RETRY_WAIT

    retaken = store.claim(space_ids=(space_id,), worker_id="worker-b")
    assert isinstance(retaken, ClaimedJob)
    assert retaken.job.id == job_id
    running = store.start(
        space_id=space_id, job_id=job_id, generation=retaken.job.lease_generation
    )
    assert running.attempt == 2

    dead = store.report_failure(
        space_id=space_id,
        job_id=job_id,
        generation=retaken.job.lease_generation,
        failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="final failure"),
    )
    assert dead.state is JobState.DEAD_LETTER
    assert dead.attempt == 2
    assert dead.error_class is ErrorClass.RETRYABLE
    assert dead.error_summary == "final failure"

    slow_space = _space("retry-slow")
    slow_store = _store(postgres_runtime, backoff_seconds=(3600.0,))
    slow_job, slow_generation = _start_running(slow_store, slow_space, "job-1", "worker-a")
    slow_store.report_failure(
        space_id=slow_space,
        job_id=slow_job,
        generation=slow_generation,
        failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="wait"),
    )
    waiting = slow_store.claim(space_ids=(slow_space,), worker_id="worker-b")
    assert isinstance(waiting, NoClaimableJob)
    assert slow_store.get_job(space_id=slow_space, job_id=slow_job).state is JobState.RETRY_WAIT


# --- T8：awaiting_human 释放额度 + 并发重复 Decision 恰好唤醒一次 ---


@pytest.mark.integration_postgres
def test_p1_7_concurrent_duplicate_decisions_requeue_exactly_once(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("decide")
    store = _store(postgres_runtime, per_space_concurrency_limit=1)
    job_id, generation = _start_running(store, space_id, "job-1", "worker-a")
    store.enqueue(space_id=space_id, job_type="compile", idempotency_key="job-next")
    saturated = store.claim(space_ids=(space_id,), worker_id="worker-b")
    assert isinstance(saturated, NoClaimableJob)

    waiting = store.report_failure(
        space_id=space_id,
        job_id=job_id,
        generation=generation,
        failure=JobFailure(error_class=ErrorClass.HUMAN_REQUIRED, summary="needs review"),
    )
    assert waiting.state is JobState.AWAITING_HUMAN

    # awaiting_human 同事务释放 lease：额度立即归还，下一个任务可领取。
    freed = store.claim(space_ids=(space_id,), worker_id="worker-b")
    assert isinstance(freed, ClaimedJob)
    assert freed.job.idempotency_key == "job-next"

    barrier = threading.Barrier(4)

    def decide() -> str:
        barrier.wait(timeout=10)
        return store.resume_after_decision(space_id=space_id, job_id=job_id).status

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(decide) for _ in range(4)]
        statuses = [future.result(timeout=FUTURE_TIMEOUT_S) for future in futures]

    assert statuses.count("resumed") == 1
    assert statuses.count("duplicate") == 3
    assert store.get_job(space_id=space_id, job_id=job_id).state is JobState.QUEUED


# --- T9：dispatcher 扫描基于持久标记；较小 id 晚提交不被永久跳过 ---


@pytest.mark.integration_postgres
def test_p1_6_late_committed_smaller_id_is_still_dispatched(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("outbox")
    store = _store(postgres_runtime)
    dispatcher = OutboxDispatcher(postgres_runtime.factory, _config())
    early_job, early_generation = _start_running(store, space_id, "job-early", "worker-a")
    late_job, late_generation = _start_running(store, space_id, "job-late", "worker-b")

    delivered: list[str] = []
    with postgres_runtime.factory() as slow_session:
        with slow_session.begin():
            # 先分配较小的有序 id，但保持事务未提交（提交晚于较大 id）。
            early_row = append_job_event(
                slow_session,
                space_id=space_id,
                job_id=early_job,
                generation=early_generation,
                draft=OutboxEventDraft(event_type="job.custom", payload={}, event_id="early-035"),
            )
            early_id = early_row.id

            store.report_success(
                space_id=space_id,
                job_id=late_job,
                generation=late_generation,
                events=(
                    OutboxEventDraft(
                        event_type="job.succeeded", payload={}, event_id="late-035"
                    ),
                ),
            )
            first_round = dispatcher.dispatch_pending(
                space_id=space_id, deliver=lambda event: delivered.append(event.event_id)
            )
            # 未提交的较小 id 尚不可见：本轮只投递已提交的较大 id。
            assert first_round.delivered_event_ids == ("late-035",)

    second_round = dispatcher.dispatch_pending(
        space_id=space_id, deliver=lambda event: delivered.append(event.event_id)
    )
    assert second_round.delivered_event_ids == ("early-035",)
    assert delivered == ["late-035", "early-035"]

    with postgres_runtime.factory() as session:
        rows = session.execute(
            select(WikiOutboxEvent.id, WikiOutboxEvent.event_id, WikiOutboxEvent.dispatched_at)
            .where(WikiOutboxEvent.space_id == space_id)
            .order_by(WikiOutboxEvent.id)
        ).all()
    assert [row.event_id for row in rows] == ["early-035", "late-035"]
    assert rows[0].id == early_id
    assert rows[0].id < rows[1].id  # 分配序与提交/投递序解耦（P1.6 caveat）
    assert all(row.dispatched_at is not None for row in rows)
