"""JobStore（SQLite）：人工 Decision、尝试次数上限与类型化读入口。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from insurance_harness.jobs import (
    ClaimedJob,
    ErrorClass,
    InvalidJobInputError,
    JobFailure,
    JobSnapshot,
    JobState,
    JobStore,
    OutboxDispatcher,
    OutboxEventDraft,
    SpaceScopeError,
    global_job_metrics,
    space_job_metrics,
)
from insurance_harness.jobs.tables import WikiJob
from tests.jobs.job_store.helpers import (
    SessionFactory,
    _claimed,
    _running_job,
    force_expire,
    make_config,
    make_store,
)

# --- T8：人工 Decision 幂等唤醒 awaiting_human ---


def _awaiting_job(store: JobStore, key: str = "job-1") -> JobSnapshot:
    running = _running_job(store, key=key)
    return store.report_failure(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        failure=JobFailure(error_class=ErrorClass.HUMAN_REQUIRED, summary="needs review"),
    )


def test_p1_7_decision_resumes_awaiting_human_exactly_once(factory: SessionFactory) -> None:
    store = make_store(factory)
    waiting = _awaiting_job(store)
    assert waiting.state is JobState.AWAITING_HUMAN

    first = store.resume_after_decision(space_id="space-a", job_id=waiting.id)
    assert first.status == "resumed"
    assert first.job_id == waiting.id
    resumed = store.get_job(space_id="space-a", job_id=waiting.id)
    assert resumed.state is JobState.QUEUED

    second = store.resume_after_decision(space_id="space-a", job_id=waiting.id)
    assert second.status == "duplicate"
    assert store.get_job(space_id="space-a", job_id=waiting.id).state is JobState.QUEUED


def test_p1_7_decision_on_never_awaiting_states_is_typed_not_awaiting(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    running = _running_job(store)

    outcome = store.resume_after_decision(space_id="space-a", job_id=running.id)

    # I11：从未 awaiting 的行不是「重复 Decision」，报 typed not_awaiting。
    assert outcome.status == "not_awaiting"
    unchanged = store.get_job(space_id="space-a", job_id=running.id)
    assert unchanged.state is JobState.RUNNING
    assert unchanged.lease_generation == running.lease_generation

    dead = store.report_failure(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        failure=JobFailure(error_class=ErrorClass.NON_RETRYABLE, summary="fatal"),
    )
    assert dead.state is JobState.DEAD_LETTER
    assert store.resume_after_decision(space_id="space-a", job_id=running.id).status == (
        "not_awaiting"
    )

    with pytest.raises(SpaceScopeError):
        store.resume_after_decision(space_id="space-b", job_id=running.id)


def test_p1_7_resumed_job_continues_same_state_machine(factory: SessionFactory) -> None:
    store = make_store(factory)
    waiting = _awaiting_job(store)
    store.resume_after_decision(space_id="space-a", job_id=waiting.id)

    retaken = store.claim(space_ids=("space-a",), worker_id="worker-2")

    assert isinstance(retaken, ClaimedJob)
    assert retaken.job.id == waiting.id
    assert retaken.job.lease_generation == waiting.lease_generation + 1
    assert retaken.job.attempt == waiting.attempt  # Decision 不清零 attempt

    running = store.start(
        space_id="space-a", job_id=waiting.id, generation=retaken.job.lease_generation
    )
    done = store.report_success(
        space_id="space-a",
        job_id=waiting.id,
        generation=running.lease_generation,
        events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
    )
    assert done.state is JobState.SUCCEEDED


# --- T14/T15/T18：D-2026-07-27-16 边界冻结（写权威、回收 attempt、storage-only） ---


def test_q14_reclaiming_a_leased_row_counts_one_attempt(factory: SessionFactory) -> None:
    """P1.1 第 10 条：回收 `leased` 行（worker 未及 start）先 attempt +1。"""
    store = make_store(factory)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="job-1")
    claimed = _claimed(store, "space-a")
    assert claimed.attempt == 0
    force_expire(factory, claimed.id)

    store.reclaim_expired_leases(space_ids=("space-a",))

    job = store.get_job(space_id="space-a", job_id=claimed.id)
    assert job.state is JobState.QUEUED
    assert job.attempt == 1, "leased 行被回收必须记一次 attempt"


def test_q14_crash_between_claim_and_start_is_bounded_by_max_attempts(
    factory: SessionFactory,
) -> None:
    """P1.1 场景「未 start 即崩溃的重试次数有界」：不得无界重排队。"""
    store = make_store(factory, max_attempts=3)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="poison")
    leases = 0
    for _ in range(12):
        outcome = store.claim(space_ids=("space-a",), worker_id="worker-1")
        if not isinstance(outcome, ClaimedJob):
            break
        leases += 1
        force_expire(factory, outcome.job.id)  # worker 在 start 之前死亡
        store.reclaim_expired_leases(space_ids=("space-a",))

    with factory() as session:
        row = session.execute(select(WikiJob)).scalar_one()
        assert row.state == JobState.DEAD_LETTER.value, f"仍在 {row.state}，租约已发 {leases} 次"
        assert row.attempt == 3
    assert leases == 3


def test_q23_decision_duplicate_label_survives_a_reclaim(factory: SessionFactory) -> None:
    """P1.7 判据不可变：duplicate 判定不得被回收/失败覆写 `error_class` 影响。

    修复前判据是 `error_class == 'human_required'`，而回收无条件写
    `retryable`、`report_failure`/`report_success` 也会覆写它——于是 Decision
    的 at-least-once 重投在任务经历一次租约过期后收到"从未等待人工"。
    """
    store = make_store(factory)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="job-1")
    claimed = _claimed(store, "space-a")
    running = store.start(
        space_id="space-a", job_id=claimed.id, generation=claimed.lease_generation
    )
    store.report_failure(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        failure=JobFailure(error_class=ErrorClass.HUMAN_REQUIRED, summary="needs human"),
    )
    assert store.resume_after_decision(space_id="space-a", job_id=running.id).status == "resumed"

    # 路径一：唤醒后再失败（error_class 被覆写为 retryable）。
    retaken = _claimed(store, "space-a", worker_id="worker-2")
    again = store.start(space_id="space-a", job_id=retaken.id, generation=retaken.lease_generation)
    store.report_failure(
        space_id="space-a",
        job_id=again.id,
        generation=again.lease_generation,
        failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="transient"),
    )
    assert store.resume_after_decision(space_id="space-a", job_id=again.id).status == "duplicate"

    # 路径二：经历一次租约过期回收（回收无条件写 retryable）。
    third = _claimed(store, "space-a", worker_id="worker-3")
    force_expire(factory, third.id)
    store.reclaim_expired_leases(space_ids=("space-a",))
    assert store.resume_after_decision(space_id="space-a", job_id=third.id).status == "duplicate"


def test_q23_never_awaiting_row_is_still_not_awaiting(factory: SessionFactory) -> None:
    """接受侧：真正从未进入 awaiting_human 的行仍返回 not_awaiting。"""
    store = make_store(factory)
    queued = store.enqueue(space_id="space-a", job_type="compile", idempotency_key="never").job

    outcome = store.resume_after_decision(space_id="space-a", job_id=queued.id)

    assert outcome.status == "not_awaiting"
    assert store.get_job(space_id="space-a", job_id=queued.id).state is JobState.QUEUED


def test_q22_metrics_expose_expired_lease_wedge(factory: SessionFactory) -> None:
    """P1.9：全 Space 卡在过期 lease 时必须与"健康"可区分。

    修复前 queue_depth=0、oldest_schedulable_age=None，而 4 行持有已死租约，
    指标上与空闲系统完全一样（零分母给满分）。
    """
    store = make_store(factory)
    ids = []
    for index in range(4):
        store.enqueue(space_id="space-a", job_type="compile", idempotency_key=f"job-{index}")
    for index in range(4):
        claimed = _claimed(store, "space-a", worker_id=f"w-{index}")
        store.start(space_id="space-a", job_id=claimed.id, generation=claimed.lease_generation)
        ids.append(claimed.id)
    force_expire(factory, *ids)

    with factory() as session:
        metrics = space_job_metrics(session, space_id="space-a")
        global_metrics = global_job_metrics(session)

    assert metrics.queue_depth == 0
    assert metrics.oldest_schedulable_age_seconds is None
    assert metrics.expired_lease_count == 4, "卡死形态必须可见"
    assert metrics.oldest_expired_lease_age_seconds is not None
    assert metrics.oldest_expired_lease_age_seconds > 0
    assert global_metrics.expired_lease_count == 4


def test_q22_healthy_distribution_metrics_stay_exact(factory: SessionFactory) -> None:
    """接受侧：健康分布的读数不因新增维度而漂移。"""
    store = make_store(factory)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="q1")
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="q2")
    claimed = _claimed(store, "space-a")
    store.start(space_id="space-a", job_id=claimed.id, generation=claimed.lease_generation)

    with factory() as session:
        metrics = space_job_metrics(session, space_id="space-a")

    assert metrics.queue_depth == 1
    assert metrics.state_counts[JobState.RUNNING] == 1
    assert metrics.oldest_schedulable_age_seconds is not None
    assert metrics.expired_lease_count == 0
    assert metrics.oldest_expired_lease_age_seconds is None


@pytest.mark.parametrize("bad_space_id", ["", "a\x00b", "x" * 64])
def test_q24_read_path_input_contract_is_typed(factory: SessionFactory, bad_space_id: str) -> None:
    """P1.9 读路径输入合同：写路径拒绝的标识符在读路径同样 typed 拒绝。

    修复前：NUL 泄漏原始 `DataError`，超长 space_id 静默返回 queue_depth=0
    （对写路径会拒绝的标识符给出"健康"读数）。
    """
    store = make_store(factory)
    with pytest.raises(InvalidJobInputError):
        store.enqueue(space_id=bad_space_id, job_type="compile", idempotency_key="k")
    with factory() as session, pytest.raises(InvalidJobInputError):
        space_job_metrics(session, space_id=bad_space_id)


@pytest.mark.parametrize("bad_limit", [0, -1])
def test_q24_non_positive_limit_is_typed_on_read_entries(
    factory: SessionFactory, bad_limit: int
) -> None:
    """`limit = 0` 不得产生与"无事可做"不可区分的空结果。"""
    dispatcher = OutboxDispatcher(factory, make_config())

    with pytest.raises(InvalidJobInputError):
        dispatcher.read_pending(space_id="space-a", limit=bad_limit)
    with pytest.raises(InvalidJobInputError):
        dispatcher.read_pending_all_spaces(limit=bad_limit)
    with pytest.raises(InvalidJobInputError):
        dispatcher.read_backed_off(space_id="space-a", limit=bad_limit)
    with pytest.raises(InvalidJobInputError):
        dispatcher.dispatch_pending(
            space_id="space-a", deliver=lambda _event: None, limit=bad_limit
        )


def test_q24_default_limits_still_work(factory: SessionFactory) -> None:
    """接受侧：默认与正常 limit 不被误拒。"""
    dispatcher = OutboxDispatcher(factory, make_config())

    assert dispatcher.read_pending(space_id="space-a") == ()
    assert dispatcher.read_pending_all_spaces(limit=10) == ()
    assert dispatcher.read_backed_off(space_id="space-a", limit=10) == ()
    report = dispatcher.dispatch_pending(space_id="space-a", deliver=lambda _event: None)
    assert report.delivered_event_ids == ()


def test_q20_append_job_event_is_not_a_public_entry() -> None:
    """P1.6 事件追加边界：调用方事务内的公共追加入口必须不存在。

    该入口允许"领域写 + 事件行已提交但任务未完成"，其后的过期回收与重放会
    以**新铸的随机 event_id** 再发布同一逻辑工作，消费端的 event_id 幂等
    去重在原理上无法折叠，并留下两份领域行。
    """
    import insurance_harness.jobs as jobs_package

    assert "append_job_event" not in jobs_package.__all__
    assert not hasattr(jobs_package, "append_job_event")
