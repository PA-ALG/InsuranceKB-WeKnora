"""JobStore（SQLite）：重试退避策略与 Space / 全局指标。"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from insurance_harness.jobs import (
    ClaimedJob,
    ErrorClass,
    JobFailure,
    JobSnapshot,
    JobState,
    JobTypePolicy,
    NoClaimableJob,
    classify_failure,
    global_job_metrics,
    space_job_metrics,
)
from insurance_harness.jobs.tables import WikiJob
from tests.jobs.job_store.helpers import (
    SessionFactory,
    _claimed,
    _db_now,
    _fail_retryable,
    _running_job,
    make_store,
)


def test_p1_4_backoff_available_at_follows_each_configuration(
    factory: SessionFactory,
) -> None:
    slow = make_store(factory, backoff_seconds=(60.0,))
    slower = make_store(factory, backoff_seconds=(7200.0,))

    for store, key, delay in ((slow, "job-slow", 60.0), (slower, "job-slower", 7200.0)):
        running = _running_job(store, key=key)
        before = _db_now(factory)
        failed = _fail_retryable(store, running)
        after = _db_now(factory)
        assert failed.state is JobState.RETRY_WAIT
        lower = before + timedelta(seconds=delay)
        upper = after + timedelta(seconds=delay)
        assert lower <= failed.available_at <= upper, key


def test_p1_1_due_retry_wait_is_requeued_by_storage_layer_via_claim(
    factory: SessionFactory,
) -> None:
    store = make_store(factory, backoff_seconds=(0.0,))
    running = _running_job(store)
    failed = _fail_retryable(store, running)
    assert failed.state is JobState.RETRY_WAIT

    retaken = store.claim(space_ids=("space-a",), worker_id="worker-2")

    assert isinstance(retaken, ClaimedJob)
    assert retaken.job.id == running.id
    assert retaken.job.lease_generation == running.lease_generation + 1
    assert retaken.job.attempt == 1  # attempt 只在 leased → running 时 +1


def test_p1_4_pending_backoff_keeps_job_unclaimable(factory: SessionFactory) -> None:
    store = make_store(factory, backoff_seconds=(3600.0,))
    running = _running_job(store)
    _fail_retryable(store, running)

    outcome = store.claim(space_ids=("space-a",), worker_id="worker-2")

    assert isinstance(outcome, NoClaimableJob)
    assert store.get_job(space_id="space-a", job_id=running.id).state is JobState.RETRY_WAIT


def test_p1_4_job_type_policy_override_takes_precedence(factory: SessionFactory) -> None:
    store = make_store(
        factory,
        backoff_seconds=(0.0,),
        max_attempts=3,
        job_type_policies={"fragile": JobTypePolicy(max_attempts=1, backoff_seconds=(0.0,))},
    )
    store.enqueue(space_id="space-a", job_type="fragile", idempotency_key="f-1")
    claimed = _claimed(store, "space-a")
    fragile_running = store.start(
        space_id="space-a", job_id=claimed.id, generation=claimed.lease_generation
    )

    failed = _fail_retryable(store, fragile_running)

    assert failed.state is JobState.DEAD_LETTER  # override max_attempts=1 直接进 dead_letter
    assert failed.attempt == 1


def test_p1_4_retryable_at_max_attempts_dead_letters_with_forensics(
    factory: SessionFactory,
) -> None:
    store = make_store(factory, backoff_seconds=(0.0,), max_attempts=2)
    running = _running_job(store)
    _fail_retryable(store, running, summary="first failure")

    second = store.claim(space_ids=("space-a",), worker_id="worker-2")
    assert isinstance(second, ClaimedJob)
    running_again = store.start(
        space_id="space-a", job_id=second.job.id, generation=second.job.lease_generation
    )
    assert running_again.attempt == 2

    dead = _fail_retryable(store, running_again, summary="final failure")

    assert dead.state is JobState.DEAD_LETTER
    assert dead.attempt == 2
    assert dead.error_class is ErrorClass.RETRYABLE
    assert dead.error_summary == "final failure"
    assert dead.finished_at is not None
    assert dead.space_id == "space-a"
    assert dead.idempotency_key == "job-1"


def test_p1_4_unclassified_exception_is_recorded_not_swallowed(
    factory: SessionFactory,
) -> None:
    store = make_store(factory, backoff_seconds=(0.0,))
    running = _running_job(store)

    failed = store.report_failure(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        failure=classify_failure(ValueError("kaboom-035")),
    )

    assert failed.state is JobState.RETRY_WAIT
    assert failed.error_class is ErrorClass.RETRYABLE
    assert failed.error_summary is not None
    assert "kaboom-035" in failed.error_summary
    assert "ValueError" in failed.error_summary


# --- T11：只读指标查询与预置分布精确一致 ---


def _seed_known_distribution(factory: SessionFactory) -> JobSnapshot:
    """Space A：3 queued / 1 running / 1 retry_wait / 2 dead_letter；B：1 queued。

    最老可调度行是最先入队、停在 retry_wait 的任务（P1.9 场景）。
    """
    store = make_store(factory, backoff_seconds=(3600.0,))
    oldest = _running_job(store, key="retrying")
    retry_row = _fail_retryable(store, oldest)

    for key in ("dead-1", "dead-2"):
        running = _running_job(store, key=key)
        store.report_failure(
            space_id="space-a",
            job_id=running.id,
            generation=running.lease_generation,
            failure=JobFailure(error_class=ErrorClass.NON_RETRYABLE, summary="fatal"),
        )
    _running_job(store, key="running-1")
    for key in ("queued-1", "queued-2", "queued-3"):
        store.enqueue(space_id="space-a", job_type="compile", idempotency_key=key)
    store.enqueue(space_id="space-b", job_type="compile", idempotency_key="b-queued")
    return retry_row


def test_p1_9_space_metrics_match_seeded_distribution_exactly(
    factory: SessionFactory,
) -> None:
    retry_row = _seed_known_distribution(factory)

    before = _db_now(factory)
    with factory() as session:
        metrics = space_job_metrics(session, space_id="space-a")
    after = _db_now(factory)

    assert metrics.space_id == "space-a"
    assert metrics.state_counts == {
        JobState.QUEUED: 3,
        JobState.LEASED: 0,
        JobState.RUNNING: 1,
        JobState.SUCCEEDED: 0,
        JobState.RETRY_WAIT: 1,
        JobState.AWAITING_HUMAN: 0,
        JobState.BLOCKED: 0,
        JobState.DEAD_LETTER: 2,
    }
    assert metrics.queue_depth == 3
    assert metrics.retry_wait_count == 1
    assert metrics.dead_letter_count == 2
    assert metrics.attempt_total == 4  # retrying + dead-1 + dead-2 + running-1 各 1 次

    # 最老可调度年龄覆盖 retry_wait：由最先入队且停在 retry_wait 的行决定。
    assert metrics.oldest_schedulable_age_seconds is not None
    lower = (before - retry_row.enqueued_at).total_seconds()
    upper = (after - retry_row.enqueued_at).total_seconds()
    assert lower <= metrics.oldest_schedulable_age_seconds <= upper


def test_p1_9_global_metrics_is_an_explicitly_named_separate_entry(
    factory: SessionFactory,
) -> None:
    _seed_known_distribution(factory)

    with factory() as session:
        space_a = space_job_metrics(session, space_id="space-a")
        space_b = space_job_metrics(session, space_id="space-b")
        overall = global_job_metrics(session)

    assert space_b.state_counts[JobState.QUEUED] == 1
    assert space_b.dead_letter_count == 0
    assert space_b.attempt_total == 0
    assert overall.queue_depth == space_a.queue_depth + space_b.queue_depth == 4
    assert overall.state_counts[JobState.DEAD_LETTER] == 2
    assert overall.attempt_total == 4
    assert overall.oldest_schedulable_age_seconds is not None
    assert space_a.oldest_schedulable_age_seconds is not None
    assert (
        overall.oldest_schedulable_age_seconds >= space_b.oldest_schedulable_age_seconds >= 0
        if space_b.oldest_schedulable_age_seconds is not None
        else False
    )


def test_p1_9_metrics_empty_space_returns_zeroes_not_errors(
    factory: SessionFactory,
) -> None:
    with factory() as session:
        metrics = space_job_metrics(session, space_id="space-empty")

    assert all(count == 0 for count in metrics.state_counts.values())
    assert metrics.queue_depth == 0
    assert metrics.oldest_schedulable_age_seconds is None


def test_p1_9_timestamps_are_persisted_for_duration_metrics(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    running = _running_job(store)
    done = store.report_success(
        space_id="space-a", job_id=running.id, generation=running.lease_generation
    )

    with factory() as session:
        row = session.execute(
            select(WikiJob.enqueued_at, WikiJob.started_at, WikiJob.finished_at).where(
                WikiJob.id == done.id
            )
        ).one()
    assert row.enqueued_at is not None
    assert row.started_at is not None
    assert row.finished_at is not None
