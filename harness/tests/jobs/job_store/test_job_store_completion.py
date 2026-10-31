"""JobStore（SQLite）：完成、失败路由、awaiting_human 与输入校验。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.orm import Session

from insurance_harness.jobs import (
    ClaimedJob,
    DomainWriteSpec,
    ErrorClass,
    IllegalTransitionError,
    InvalidJobInputError,
    JobFailure,
    JobState,
    NoClaimableJob,
    OutboxEventDraft,
    SpaceScopeError,
    StaleGenerationError,
    space_job_metrics,
)

# `append_job_event` 已不在公共出口（P1.6 事件追加边界，D-2026-07-27-16）：
# 只能在完成事务内追加。测试直接引内部模块以验证该内部合同。
from insurance_harness.jobs.outbox import append_job_event
from insurance_harness.jobs.tables import WikiOutboxEvent
from tests.jobs.job_store.helpers import (
    SessionFactory,
    _claimed,
    _db_now,
    _fail_retryable,
    _running_job,
    job_count,
    make_store,
)


def _outbox_rows(factory: SessionFactory) -> list[tuple[str, str, str]]:
    with factory() as session:
        rows = session.execute(
            select(
                WikiOutboxEvent.space_id, WikiOutboxEvent.event_type, WikiOutboxEvent.event_id
            ).order_by(WikiOutboxEvent.id)
        ).all()
    return [(space, event_type, event_id) for space, event_type, event_id in rows]


def test_p1_6_report_success_commits_state_and_outbox_in_one_transaction(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    running = _running_job(store)

    done = store.report_success(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        events=(OutboxEventDraft(event_type="job.succeeded", payload={"job_id": running.id}),),
    )

    assert done.state is JobState.SUCCEEDED
    assert done.finished_at is not None
    assert done.worker_id is None
    assert done.lease_expires_at is None
    rows = _outbox_rows(factory)
    assert len(rows) == 1
    assert rows[0][0] == "space-a"
    assert rows[0][1] == "job.succeeded"


def test_p1_5_duplicate_completion_is_rejected_with_zero_second_result(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    running = _running_job(store)
    store.report_success(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
    )

    with pytest.raises(IllegalTransitionError):
        store.report_success(
            space_id="space-a",
            job_id=running.id,
            generation=running.lease_generation,
            events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
        )

    assert len(_outbox_rows(factory)) == 1
    assert store.get_job(space_id="space-a", job_id=running.id).state is JobState.SUCCEEDED


def test_p1_3_stale_generation_completion_and_outbox_append_are_rejected(
    factory: SessionFactory, job_engine: Engine
) -> None:
    store = make_store(factory)
    running = _running_job(store)

    with pytest.raises(StaleGenerationError):
        store.report_success(
            space_id="space-a",
            job_id=running.id,
            generation=running.lease_generation - 1,
            events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
        )
    with pytest.raises(StaleGenerationError):
        store.report_failure(
            space_id="space-a",
            job_id=running.id,
            generation=running.lease_generation - 1,
            failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="late"),
        )
    with factory() as session:
        with session.begin():
            with pytest.raises(StaleGenerationError):
                append_job_event(
                    session,
                    space_id="space-a",
                    job_id=running.id,
                    generation=running.lease_generation - 1,
                    draft=OutboxEventDraft(event_type="job.custom", payload={}),
                )

    assert _outbox_rows(factory) == []
    unchanged = store.get_job(space_id="space-a", job_id=running.id)
    assert unchanged.state is JobState.RUNNING
    assert unchanged.error_class is None


def test_p1_6_injected_interrupt_before_commit_leaves_no_half_writes(
    factory: SessionFactory, job_engine: Engine
) -> None:
    with job_engine.begin() as connection:
        connection.execute(text("CREATE TABLE domain_results_035 (job_id TEXT PRIMARY KEY)"))
    store = make_store(factory)
    running = _running_job(store)

    # 声明式领域写（P1.5，D-2026-07-27-16）：存储层自己执行，调用方无句柄。
    domain_writes = (DomainWriteSpec(table="domain_results_035", values={"job_id": running.id}),)

    def interrupt(_session: Session) -> None:
        raise RuntimeError("inject-commit-crash-035")

    sqlalchemy_event.listen(factory, "before_commit", interrupt)
    try:
        with pytest.raises(RuntimeError, match="inject-commit-crash-035"):
            store.report_success(
                space_id="space-a",
                job_id=running.id,
                generation=running.lease_generation,
                events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
                domain_writes=domain_writes,
            )
    finally:
        sqlalchemy_event.remove(factory, "before_commit", interrupt)

    with factory() as session:
        domain_count = session.scalar(text("SELECT count(*) FROM domain_results_035"))
    assert domain_count == 0
    assert _outbox_rows(factory) == []
    assert store.get_job(space_id="space-a", job_id=running.id).state is JobState.RUNNING

    replay = store.report_success(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
        domain_writes=domain_writes,
    )
    assert replay.state is JobState.SUCCEEDED
    with factory() as session:
        domain_count = session.scalar(text("SELECT count(*) FROM domain_results_035"))
    assert domain_count == 1
    assert len(_outbox_rows(factory)) == 1


def test_p1_4_report_failure_routes_each_error_class_deterministically(
    factory: SessionFactory,
) -> None:
    store = make_store(factory, backoff_seconds=(60.0,))
    cases: list[tuple[ErrorClass, JobState]] = [
        (ErrorClass.RETRYABLE, JobState.RETRY_WAIT),
        (ErrorClass.NON_RETRYABLE, JobState.DEAD_LETTER),
        (ErrorClass.CAPACITY_BLOCKED, JobState.BLOCKED),
        (ErrorClass.HUMAN_REQUIRED, JobState.AWAITING_HUMAN),
    ]
    for index, (error_class, expected_state) in enumerate(cases):
        running = _running_job(store, key=f"job-{index}")
        failed = store.report_failure(
            space_id="space-a",
            job_id=running.id,
            generation=running.lease_generation,
            failure=JobFailure(error_class=error_class, summary=f"case-{error_class.value}"),
        )
        assert failed.state is expected_state, error_class
        assert failed.error_class is error_class
        assert failed.error_summary == f"case-{error_class.value}"
        assert failed.worker_id is None
        assert failed.lease_expires_at is None
        if expected_state in (JobState.DEAD_LETTER, JobState.BLOCKED):
            assert failed.finished_at is not None
        if expected_state is JobState.RETRY_WAIT:
            assert failed.available_at > running.available_at


def test_p1_7_awaiting_human_releases_concurrency_slot_in_same_transaction(
    factory: SessionFactory,
) -> None:
    store = make_store(factory, per_space_concurrency_limit=1)
    running = _running_job(store, key="job-0")
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="job-next")
    saturated = store.claim(space_ids=("space-a",), worker_id="worker-2")
    assert isinstance(saturated, NoClaimableJob)

    store.report_failure(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        failure=JobFailure(error_class=ErrorClass.HUMAN_REQUIRED, summary="needs review"),
    )

    freed = store.claim(space_ids=("space-a",), worker_id="worker-2")
    assert isinstance(freed, ClaimedJob)
    assert freed.job.idempotency_key == "job-next"


def test_m15_report_success_clears_error_residue_from_earlier_attempts(
    factory: SessionFactory,
) -> None:
    store = make_store(factory, backoff_seconds=(0.0,))
    running = _running_job(store)
    _fail_retryable(store, running, summary="transient blip")
    retaken = store.claim(space_ids=("space-a",), worker_id="worker-2")
    assert isinstance(retaken, ClaimedJob)
    running_again = store.start(
        space_id="space-a", job_id=retaken.job.id, generation=retaken.job.lease_generation
    )

    done = store.report_success(
        space_id="space-a",
        job_id=running_again.id,
        generation=running_again.lease_generation,
    )

    assert done.state is JobState.SUCCEEDED
    assert done.error_class is None
    assert done.error_summary is None


def test_i8_domain_write_cannot_leave_partial_rows_on_failure(
    factory: SessionFactory, job_engine: Engine
) -> None:
    """I8 的场景保留，被测对象随边界替换而变（D-2026-07-27-16）。

    原节点断言 `DomainWriteHandle` 不暴露 `commit/rollback/close`。该句柄已
    删除——第二轮评审证明属性面封锁挡不住任何一层可达的 DB 句柄，通道改为
    声明式（完成事务收数据不收代码，接口层面无句柄可泄漏；见
    `test_q19a_completion_entry_takes_data_not_code`）。I8 真正要保住的性质
    是"领域写失败时不留半写"，在此保留并断言：完成事务中途失败后，声明式
    领域写落下的行必须随整个事务回滚，任务留在 `running` 可重放。
    """
    with job_engine.begin() as connection:
        connection.execute(text("CREATE TABLE domain_guard_035 (job_id TEXT PRIMARY KEY)"))
    store = make_store(factory)
    running = _running_job(store)

    def interrupt(_session: Session) -> None:
        raise RuntimeError("crash after domain write")

    sqlalchemy_event.listen(factory, "before_commit", interrupt)
    try:
        with pytest.raises(RuntimeError, match="crash after domain write"):
            store.report_success(
                space_id="space-a",
                job_id=running.id,
                generation=running.lease_generation,
                events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
                domain_writes=(
                    DomainWriteSpec(table="domain_guard_035", values={"job_id": running.id}),
                ),
            )
    finally:
        sqlalchemy_event.remove(factory, "before_commit", interrupt)

    with factory() as session:
        assert session.scalar(text("SELECT count(*) FROM domain_guard_035")) == 0
    assert _outbox_rows(factory) == []
    assert store.get_job(space_id="space-a", job_id=running.id).state is JobState.RUNNING


def test_i6_input_validation_is_typed_and_dialect_independent(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)

    with pytest.raises(InvalidJobInputError):
        store.enqueue(space_id="s" * 37, job_type="compile", idempotency_key="k")
    with pytest.raises(InvalidJobInputError):
        store.enqueue(space_id="space-a", job_type="t" * 65, idempotency_key="k")
    with pytest.raises(InvalidJobInputError):
        store.enqueue(space_id="space-a", job_type="compile", idempotency_key="z" * 256)
    with pytest.raises(InvalidJobInputError):
        store.enqueue(space_id="space-a", job_type="compile", idempotency_key="a\x00b")
    with pytest.raises(InvalidJobInputError):
        store.enqueue(
            space_id="space-a",
            job_type="compile",
            idempotency_key="obj",
            payload={"x": object()},
        )
    with pytest.raises(InvalidJobInputError):
        store.claim(space_ids=("space-a",), worker_id="w" * 129)
    assert isinstance(InvalidJobInputError("x"), ValueError)  # 兼容旧 ValueError 合同
    assert InvalidJobInputError("x").code == "invalid_input"
    assert job_count(factory) == 0


def test_m16_claim_scope_members_and_worker_are_validated_typed(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="k")

    with pytest.raises(InvalidJobInputError):
        store.claim(space_ids=("space-a", ""), worker_id="worker-1")
    with pytest.raises(InvalidJobInputError):
        store.claim(space_ids=("space-a",), worker_id="")
    with pytest.raises(InvalidJobInputError):
        store.claim(space_ids=("space-a", "s\x00b"), worker_id="worker-1")
    assert store.claim(space_ids=("space-a",), worker_id="worker-1") is not None


def test_m17_dedup_result_exposes_terminal_flag(factory: SessionFactory) -> None:
    store = make_store(factory, max_attempts=1, backoff_seconds=(0.0,))
    fresh = store.enqueue(space_id="space-a", job_type="compile", idempotency_key="k")
    assert fresh.terminal is False

    claimed = _claimed(store, "space-a")
    running = store.start(
        space_id="space-a", job_id=claimed.id, generation=claimed.lease_generation
    )
    store.report_failure(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        failure=JobFailure(error_class=ErrorClass.NON_RETRYABLE, summary="fatal"),
    )

    again = store.enqueue(space_id="space-a", job_type="compile", idempotency_key="k")
    assert again.deduplicated is True
    assert again.terminal is True  # M17：消费方可据此铸新批次键，而非等待旧行
    assert again.job.state is JobState.DEAD_LETTER


def test_p1_9_backdated_row_yields_exact_oldest_schedulable_age(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    seeded = store.enqueue(space_id="space-a", job_type="compile", idempotency_key="old")
    backdated = seeded.job.enqueued_at - timedelta(hours=1)
    with factory() as session:  # 测试脚手架：回拨 enqueued_at 制造已知年龄
        with session.begin():
            session.execute(
                text("UPDATE wiki_jobs SET enqueued_at = :backdated WHERE id = :id"),
                {"backdated": backdated.isoformat(sep=" "), "id": seeded.job.id},
            )

    before = _db_now(factory)
    with factory() as session:
        metrics = space_job_metrics(session, space_id="space-a")
    after = _db_now(factory)

    assert metrics.oldest_schedulable_age_seconds is not None
    lower = (before - backdated).total_seconds()
    upper = (after - backdated).total_seconds()
    assert lower <= metrics.oldest_schedulable_age_seconds <= upper
    assert metrics.oldest_schedulable_age_seconds >= 3600.0


def test_p1_4_report_failure_requires_running_and_matching_space(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="job-1")
    claimed = _claimed(store, "space-a")

    with pytest.raises(IllegalTransitionError):
        store.report_failure(
            space_id="space-a",
            job_id=claimed.id,
            generation=claimed.lease_generation,
            failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="early"),
        )
    with pytest.raises(SpaceScopeError):
        store.report_failure(
            space_id="space-b",
            job_id=claimed.id,
            generation=claimed.lease_generation,
            failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="cross"),
        )
    assert store.get_job(space_id="space-a", job_id=claimed.id).state is JobState.LEASED
