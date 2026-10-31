"""JobStore（SQLite）：租约配置、全局 reclaim、饱和、状态迁移与原子准入。"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from insurance_harness.jobs import (
    ClaimedJob,
    DomainWriteSpec,
    DomainWriteViolationError,
    ErrorClass,
    IllegalTransitionError,
    InvalidJobInputError,
    JobFailure,
    JobRuntimeConfig,
    JobState,
    LeaseExpiredError,
    NoClaimableJob,
    OutboxEventDraft,
)

# `append_job_event` 已不在公共出口（P1.6 事件追加边界，D-2026-07-27-16）：
# 只能在完成事务内追加。测试直接引内部模块以验证该内部合同。
from insurance_harness.jobs.outbox import append_job_event
from insurance_harness.jobs.tables import WikiJob, WikiOutboxEvent
from tests.jobs.job_store.helpers import (
    SessionFactory,
    _claimed,
    force_expire,
    job_count,
    make_config,
    make_store,
)


def _active_rows(factory: SessionFactory) -> int:
    with factory() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(WikiJob)
                .where(WikiJob.state.in_((JobState.LEASED.value, JobState.RUNNING.value)))
            )
            or 0
        )


@pytest.mark.parametrize(
    ("lease_seconds", "heartbeat"),
    [(0.0, 30.0), (-1.0, 30.0), (30.0, 30.0), (10.0, 30.0)],
)
def test_q11_zero_or_sub_heartbeat_lease_is_rejected_by_config(
    lease_seconds: float, heartbeat: float
) -> None:
    """P1.3：`lease_seconds` 必须严格为正且大于 heartbeat 间隔。

    `lease_seconds = 0` 曾是合法配置，其后果是每个 lease 出生即过期——静默
    作废并发限额与 heartbeat（运维若把 0 读作"不限期"会得到相反语义）。
    """
    with pytest.raises(ValueError):
        JobRuntimeConfig.model_validate(
            {
                "lease_seconds": lease_seconds,
                "heartbeat_interval_seconds": heartbeat,
                "max_attempts": 3,
                "backoff_seconds": (0.0,),
                "per_space_concurrency_limit": 8,
                "global_concurrency_limit": 32,
            }
        )


def test_q11_positive_lease_above_heartbeat_is_still_accepted() -> None:
    """接受侧：正常正值配置不被误拒。"""
    config = make_config(lease_seconds=45.0, heartbeat_interval_seconds=15.0)
    assert config.lease_seconds == 45.0


def test_q17_unenumerated_space_converges_via_explicit_global_entry(
    factory: SessionFactory,
) -> None:
    """P1.10 回收可达性：无人枚举的 Space 必须能经显式全局入口收敛。"""
    store = make_store(factory, max_attempts=1)
    store.enqueue(space_id="space-orphan", job_type="compile", idempotency_key="job")
    orphan = _claimed(store, "space-orphan", worker_id="worker-gone")
    force_expire(factory, orphan.id)

    report = store.reclaim_expired_leases_all_spaces()

    assert report.dead_lettered_job_ids == (orphan.id,)
    job = store.get_job(space_id="space-orphan", job_id=orphan.id)
    assert job.state is JobState.DEAD_LETTER
    assert job.error_summary == "lease_expired"


def test_q17_global_reclaim_leaves_unexpired_rows_untouched(factory: SessionFactory) -> None:
    """接受侧：全局回收不得误杀未过期 lease。"""
    store = make_store(factory)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="live")
    live = _claimed(store, "space-a")

    report = store.reclaim_expired_leases_all_spaces()

    assert report.requeued_job_ids == ()
    assert report.dead_lettered_job_ids == ()
    unchanged = store.get_job(space_id="space-a", job_id=live.id)
    assert unchanged.state is JobState.LEASED
    assert unchanged.lease_generation == live.lease_generation


def test_q16_stalled_expired_leases_never_exceed_configured_limits(
    factory: SessionFactory,
) -> None:
    """P1.8 限额会计：停滞的过期 lease 不得抬高 `leased | running` 行数上限。

    每个 worker 只声明自己的 Space（P1.8 鼓励的分片部署），过期行属于别的
    Space、无人回收——C1 的窄计数在此裂开：分母缩小而执行体一个没少。
    """
    store = make_store(factory, per_space_concurrency_limit=1, global_concurrency_limit=2)
    for index in range(6):
        store.enqueue(space_id=f"space-{index}", job_type="compile", idempotency_key="job")

    for index in range(6):
        outcome = store.claim(space_ids=(f"space-{index}",), worker_id=f"worker-{index}")
        if isinstance(outcome, ClaimedJob):
            force_expire(factory, outcome.job.id)  # worker 存活但停滞
        assert _active_rows(factory) <= 2, f"第 {index + 1} 次 claim 后越限"


def test_q16_single_space_saturation_is_not_bypassed_by_expired_rows(
    factory: SessionFactory,
) -> None:
    """同一 Space、`maintenance_batch_size=1` 也不得越过 per-Space 上限。"""
    store = make_store(
        factory,
        per_space_concurrency_limit=2,
        global_concurrency_limit=2,
        maintenance_batch_size=1,
    )
    for index in range(8):
        store.enqueue(space_id="space-a", job_type="compile", idempotency_key=f"job-{index}")

    for _ in range(6):
        outcome = store.claim(space_ids=("space-a",), worker_id="worker-x")
        if isinstance(outcome, ClaimedJob):
            force_expire(factory, outcome.job.id)
        assert _active_rows(factory) <= 2


def test_q16_saturation_triggers_scope_free_bounded_reclaim(factory: SessionFactory) -> None:
    """C1 反饥饿语义保留：饱和集合中属未声明 Space 的过期行被回收后放行，
    且不向调用方返回跨 Space 任务内容。"""
    store = make_store(factory, per_space_concurrency_limit=4, global_concurrency_limit=1)
    store.enqueue(space_id="space-foreign", job_type="compile", idempotency_key="foreign")
    store.enqueue(space_id="space-mine", job_type="compile", idempotency_key="mine")
    foreign = store.claim(space_ids=("space-foreign",), worker_id="worker-foreign")
    assert isinstance(foreign, ClaimedJob)
    force_expire(factory, foreign.job.id)

    outcome = store.claim(space_ids=("space-mine",), worker_id="worker-mine")

    assert isinstance(outcome, ClaimedJob), "过期外域行必须被回收让路，不得永久饥饿"
    assert outcome.job.space_id == "space-mine"
    reclaimed = store.get_job(space_id="space-foreign", job_id=foreign.job.id)
    assert reclaimed.state is JobState.QUEUED
    assert reclaimed.lease_generation == foreign.job.lease_generation + 1
    assert _active_rows(factory) == 1


def test_q16_unexpired_leases_still_consume_the_limit(factory: SessionFactory) -> None:
    """接受侧：未过期 lease 仍精确占额，达限返回 typed 拒绝而非放行。"""
    store = make_store(factory, per_space_concurrency_limit=8, global_concurrency_limit=2)
    for index in range(4):
        store.enqueue(space_id="space-a", job_type="compile", idempotency_key=f"job-{index}")

    granted = [store.claim(space_ids=("space-a",), worker_id=f"w-{i}") for i in range(4)]

    assert sum(isinstance(item, ClaimedJob) for item in granted) == 2
    refusals = [item for item in granted if isinstance(item, NoClaimableJob)]
    assert [item.reason for item in refusals] == ["global_concurrency_limit"] * 2
    assert _active_rows(factory) == 2


def test_q18_storage_only_transitions_have_no_caller_entry(factory: SessionFactory) -> None:
    """P1.1 storage-only 执法：持有有效 lease、attempt=0 的 leased 行不得经
    任何调用方入口进入终态/等待态；四类错误分类逐一验证不对称已消除。"""
    store = make_store(factory)
    for error_class in ErrorClass:
        store.enqueue(space_id="space-a", job_type="compile", idempotency_key=error_class.value)

    for error_class in ErrorClass:
        leased = _claimed(store, "space-a", worker_id=f"w-{error_class.value}")
        assert leased.attempt == 0
        with pytest.raises(IllegalTransitionError):
            store.report_failure(
                space_id="space-a",
                job_id=leased.id,
                generation=leased.lease_generation,
                failure=JobFailure(error_class=error_class, summary="pre-start fatal"),
            )
        frozen = store.get_job(space_id="space-a", job_id=leased.id)
        assert (frozen.state, frozen.attempt, frozen.lease_generation) == (
            JobState.LEASED,
            0,
            leased.lease_generation,
        ), f"{error_class.value} 改变了 leased 行"
        assert frozen.error_class is None and frozen.error_summary is None


def test_q18_ensure_transition_refuses_storage_only_pairs_for_callers() -> None:
    """storage-only 常量必须是可执行护栏，而非仅文档/测试断言。"""
    from insurance_harness.jobs.models import STORAGE_ONLY_TRANSITIONS, ensure_transition

    for source, target in sorted(STORAGE_ONLY_TRANSITIONS):
        with pytest.raises(IllegalTransitionError):
            ensure_transition(source, target, "job-x")
        # 存储层自身仍可执行同一对转换。
        ensure_transition(source, target, "job-x", storage_layer=True)


def test_q18_running_to_dead_letter_still_works(factory: SessionFactory) -> None:
    """接受侧：合法的 `running → dead_letter`（P1.1 #9）不被误杀。"""
    store = make_store(factory, max_attempts=3)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="job-1")
    claimed = _claimed(store, "space-a")
    running = store.start(
        space_id="space-a", job_id=claimed.id, generation=claimed.lease_generation
    )

    dead = store.report_failure(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        failure=JobFailure(error_class=ErrorClass.NON_RETRYABLE, summary="fatal"),
    )

    assert dead.state is JobState.DEAD_LETTER
    assert dead.attempt == 1
    assert dead.error_class is ErrorClass.NON_RETRYABLE


def test_q15_expired_lease_holder_has_no_write_authority_on_any_path(
    factory: SessionFactory,
) -> None:
    """P1.3 写权威合同：过期未回收的持有者四条写路径全部 typed 拒绝、零变更。"""
    store = make_store(factory)
    for key in ("start", "success", "failure", "event"):
        store.enqueue(space_id="space-a", job_type="compile", idempotency_key=key)

    # 路径一：start
    claimed = _claimed(store, "space-a")
    force_expire(factory, claimed.id)
    with pytest.raises(LeaseExpiredError):
        store.start(space_id="space-a", job_id=claimed.id, generation=claimed.lease_generation)
    frozen = store.get_job(space_id="space-a", job_id=claimed.id)
    assert (frozen.state, frozen.attempt, frozen.lease_generation) == (
        JobState.LEASED,
        0,
        claimed.lease_generation,
    )

    # 路径二/三/四：running 行的结果提交、失败上报、outbox 追加
    for path in ("success", "failure", "event"):
        job = _claimed(store, "space-a", worker_id=f"worker-{path}")
        running = store.start(space_id="space-a", job_id=job.id, generation=job.lease_generation)
        force_expire(factory, running.id)
        gen = running.lease_generation
        if path == "success":
            with pytest.raises(LeaseExpiredError):
                store.report_success(
                    space_id="space-a",
                    job_id=running.id,
                    generation=gen,
                    events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
                )
        elif path == "failure":
            with pytest.raises(LeaseExpiredError):
                store.report_failure(
                    space_id="space-a",
                    job_id=running.id,
                    generation=gen,
                    failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="boom"),
                )
        else:
            with pytest.raises(LeaseExpiredError), factory() as session:
                with session.begin():
                    append_job_event(
                        session,
                        space_id="space-a",
                        job_id=running.id,
                        generation=gen,
                        draft=OutboxEventDraft(event_type="job.progress", payload={}),
                    )
        after = store.get_job(space_id="space-a", job_id=running.id)
        assert after.state is JobState.RUNNING, f"{path} 路径不应改变状态"
        assert after.lease_generation == gen

    with factory() as session:
        assert int(session.scalar(select(func.count()).select_from(WikiOutboxEvent)) or 0) == 0


def test_q15_unexpired_lease_still_writes_on_every_path(factory: SessionFactory) -> None:
    """接受侧：未过期 lease 的四条写路径一条都不能被误杀。"""
    store = make_store(factory)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="ok-1")
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="ok-2")

    first = _claimed(store, "space-a")
    running = store.start(space_id="space-a", job_id=first.id, generation=first.lease_generation)
    with factory() as session:
        with session.begin():
            append_job_event(
                session,
                space_id="space-a",
                job_id=running.id,
                generation=running.lease_generation,
                draft=OutboxEventDraft(event_type="job.progress", payload={"n": 1}),
            )
    done = store.report_success(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
    )
    assert done.state is JobState.SUCCEEDED

    second = _claimed(store, "space-a", worker_id="worker-2")
    running2 = store.start(space_id="space-a", job_id=second.id, generation=second.lease_generation)
    failed = store.report_failure(
        space_id="space-a",
        job_id=running2.id,
        generation=running2.lease_generation,
        failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="transient"),
    )
    assert failed.state is JobState.RETRY_WAIT


def test_q14_crash_after_start_keeps_its_existing_bound(factory: SessionFactory) -> None:
    """接受侧：start 之后崩溃的界与 attempt 计数不因 T14 改变。"""
    store = make_store(factory, max_attempts=3)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="poison")
    leases = 0
    for _ in range(12):
        outcome = store.claim(space_ids=("space-a",), worker_id="worker-1")
        if not isinstance(outcome, ClaimedJob):
            break
        leases += 1
        started = store.start(
            space_id="space-a", job_id=outcome.job.id, generation=outcome.job.lease_generation
        )
        force_expire(factory, started.id)
        store.reclaim_expired_leases(space_ids=("space-a",))

    with factory() as session:
        row = session.execute(select(WikiJob)).scalar_one()
        assert row.state == JobState.DEAD_LETTER.value
        assert row.attempt == 3
    assert leases == 3


def test_atomic_admission_rolls_back_job_when_domain_write_is_rejected(
    factory: SessionFactory,
) -> None:
    from uuid import uuid4

    store = make_store(factory)
    with pytest.raises(DomainWriteViolationError):
        store.enqueue(
            space_id="space-a",
            job_type="fixture",
            idempotency_key="atomic-reject",
            job_id=str(uuid4()),
            domain_writes=(DomainWriteSpec(table="wiki_jobs", values={"id": "forbidden"}),),
        )
    assert job_count(factory) == 0


def test_atomic_admission_dedup_rejects_changed_explicit_identity(factory: SessionFactory) -> None:
    from uuid import uuid4

    store = make_store(factory)
    job_id = str(uuid4())
    first = store.enqueue(
        space_id="space-a",
        job_type="fixture",
        idempotency_key="atomic",
        job_id=job_id,
        payload={"run_id": "one"},
    )
    same = store.enqueue(
        space_id="space-a",
        job_type="fixture",
        idempotency_key="atomic",
        job_id=job_id,
        payload={"run_id": "one"},
    )
    assert same.deduplicated and first.job.id == same.job.id
    with pytest.raises(InvalidJobInputError):
        store.enqueue(
            space_id="space-a",
            job_type="fixture",
            idempotency_key="atomic",
            job_id=job_id,
            payload={"run_id": "changed"},
        )
    assert job_count(factory) == 1
