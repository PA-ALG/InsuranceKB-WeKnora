"""OpenSpec 035 deterministic lane：JobStore 存储层合同（SQLite 单线程）。

真实并发/一致性证据只来自 `integration_postgres` lane（P1.12）；本文件只
验证单线程可判定的存储层行为：幂等、状态机路由、fencing、配置化策略、
Decision 幂等与指标查询。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.orm import Session

from insurance_harness.db.base import Base, make_engine, make_session_factory
from insurance_harness.jobs import (
    ClaimedJob,
    DomainWriteHandle,
    EnqueueResult,
    ErrorClass,
    IllegalTransitionError,
    InvalidJobInputError,
    JobFailure,
    JobRuntimeConfig,
    JobSnapshot,
    JobState,
    JobStore,
    JobTypePolicy,
    LeaseExpiredError,
    NoClaimableJob,
    OutboxEventDraft,
    SpaceScopeError,
    StaleGenerationError,
    append_job_event,
    classify_failure,
    database_now,
    global_job_metrics,
    space_job_metrics,
)
from insurance_harness.jobs.tables import WikiJob, WikiOutboxEvent

SessionFactory = Callable[[], Session]


@pytest.fixture
def job_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = make_engine(f"sqlite:///{tmp_path}/jobs.db")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def factory(job_engine: Engine) -> SessionFactory:
    return make_session_factory(job_engine)


def make_config(**overrides: object) -> JobRuntimeConfig:
    values: dict[str, object] = {
        "lease_seconds": 300.0,
        "heartbeat_interval_seconds": 30.0,
        "max_attempts": 3,
        "backoff_seconds": (0.0,),
        "per_space_concurrency_limit": 8,
        "global_concurrency_limit": 32,
    }
    values.update(overrides)
    return JobRuntimeConfig.model_validate(values)


def make_store(factory: SessionFactory, **overrides: object) -> JobStore:
    return JobStore(factory, make_config(**overrides))


def job_count(factory: SessionFactory) -> int:
    with factory() as session:
        return int(session.scalar(select(func.count()).select_from(WikiJob)) or 0)


def database_now_utc(store: JobStore) -> datetime:
    """按数据库时钟读当前时间（过期断言必须与实现同一时钟）。"""
    with store._session_factory() as session:  # noqa: SLF001 - 测试读同一时钟
        return database_now(session)


def force_expire(factory: SessionFactory, *job_ids: str) -> None:
    """把指定任务的 lease 回拨到过去，模拟 worker 停滞超过 lease 时长。

    D-2026-07-27-16 起 `lease_seconds` 必须严格为正且大于 heartbeat 间隔，
    因此过期场景不再用 `lease_seconds=0`（那会使每个 lease 出生即过期，
    静默作废并发限额）。所有过期脚手架统一走本函数：只回拨 lease，不改
    state/attempt/generation，与真实停滞的可观测状态一致。
    """
    with factory() as session:
        with session.begin():
            for job_id in job_ids:
                session.execute(
                    text(
                        "UPDATE wiki_jobs SET lease_expires_at = "
                        "'2000-01-01 00:00:00.000000+00:00' WHERE id = :job_id"
                    ),
                    {"job_id": job_id},
                )


# --- T3：enqueue 幂等去重与 claim 基本合同 ---


def test_p1_5_enqueue_persists_queued_job_with_persisted_timestamps(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)

    result = store.enqueue(
        space_id="space-a",
        job_type="compile",
        idempotency_key="batch-1:rev-1",
        payload={"revision": "rev-1"},
    )

    assert isinstance(result, EnqueueResult)
    assert result.deduplicated is False
    job = result.job
    assert job.state is JobState.QUEUED
    assert job.attempt == 0
    assert job.lease_generation == 0
    assert job.worker_id is None
    assert job.payload == {"revision": "rev-1"}
    assert job.enqueued_at.tzinfo is not None
    assert job.available_at == job.enqueued_at
    assert job.started_at is None
    assert job.finished_at is None


def test_p1_5_duplicate_enqueue_returns_typed_dedup_and_single_row(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    first = store.enqueue(space_id="space-a", job_type="compile", idempotency_key="batch-1")

    second = store.enqueue(space_id="space-a", job_type="compile", idempotency_key="batch-1")

    assert second.deduplicated is True
    assert second.job.id == first.job.id
    assert job_count(factory) == 1


def test_p1_5_same_key_different_space_or_job_type_creates_new_jobs(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="batch-1")
    other_space = store.enqueue(space_id="space-b", job_type="compile", idempotency_key="batch-1")
    other_type = store.enqueue(space_id="space-a", job_type="extract", idempotency_key="batch-1")

    assert other_space.deduplicated is False
    assert other_type.deduplicated is False
    assert job_count(factory) == 3


def test_p1_5_enqueue_requires_caller_minted_key_and_space(factory: SessionFactory) -> None:
    store = make_store(factory)

    with pytest.raises(ValueError):
        store.enqueue(space_id="space-a", job_type="compile", idempotency_key="")
    with pytest.raises(ValueError):
        store.enqueue(space_id="", job_type="compile", idempotency_key="batch-1")
    with pytest.raises(ValueError):
        store.enqueue(space_id="space-a", job_type="", idempotency_key="batch-1")
    assert job_count(factory) == 0


def test_p1_2_claim_leases_with_generation_one_and_worker_identity(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    enqueued = store.enqueue(space_id="space-a", job_type="compile", idempotency_key="batch-1")

    outcome = store.claim(space_ids=("space-a",), worker_id="worker-1")

    assert isinstance(outcome, ClaimedJob)
    job = outcome.job
    assert job.id == enqueued.job.id
    assert job.state is JobState.LEASED
    assert job.lease_generation == 1
    assert job.worker_id == "worker-1"
    assert job.lease_expires_at is not None
    assert job.attempt == 0


def test_p1_2_claim_without_claimable_jobs_returns_typed_empty(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)

    outcome = store.claim(space_ids=("space-a",), worker_id="worker-1")

    assert isinstance(outcome, NoClaimableJob)
    assert outcome.reason == "empty"
    assert job_count(factory) == 0


def test_p1_8_claim_scope_never_returns_other_space_job(factory: SessionFactory) -> None:
    store = make_store(factory)
    store.enqueue(space_id="space-b", job_type="compile", idempotency_key="batch-1")

    outcome = store.claim(space_ids=("space-a",), worker_id="worker-1")

    assert isinstance(outcome, NoClaimableJob)
    with factory() as session:
        state = session.scalar(select(WikiJob.state))
    assert state == "queued"


def test_p1_8_get_job_is_space_scoped_fail_closed(factory: SessionFactory) -> None:
    store = make_store(factory)
    enqueued = store.enqueue(space_id="space-a", job_type="compile", idempotency_key="batch-1")

    loaded = store.get_job(space_id="space-a", job_id=enqueued.job.id)
    assert loaded.id == enqueued.job.id

    with pytest.raises(SpaceScopeError):
        store.get_job(space_id="space-b", job_id=enqueued.job.id)
    with pytest.raises(SpaceScopeError):
        store.get_job(space_id="space-a", job_id="missing-job")


# --- T4：per-Space/全局限额只由配置决定，超限排队不丢失 ---


def _drain(store: JobStore, space_ids: tuple[str, ...], worker_id: str) -> list[str]:
    claimed: list[str] = []
    while True:
        outcome = store.claim(space_ids=space_ids, worker_id=worker_id)
        if isinstance(outcome, NoClaimableJob):
            return claimed
        claimed.append(outcome.job.id)


def test_p1_8_per_space_limit_values_two_and_four_take_effect(
    factory: SessionFactory,
) -> None:
    for index in range(6):
        make_store(factory).enqueue(
            space_id="space-a", job_type="compile", idempotency_key=f"job-{index}"
        )

    limited_two = make_store(factory, per_space_concurrency_limit=2)
    first_wave = _drain(limited_two, ("space-a",), "worker-1")
    assert len(first_wave) == 2

    saturated = limited_two.claim(space_ids=("space-a",), worker_id="worker-extra")
    assert isinstance(saturated, NoClaimableJob)
    assert saturated.reason == "per_space_concurrency_limit"  # I12：饱和 ≠ 空队列

    limited_four = make_store(factory, per_space_concurrency_limit=4)
    second_wave = _drain(limited_four, ("space-a",), "worker-2")
    assert len(second_wave) == 2  # 已有 2 leased，共 4 = 新上限

    with factory() as session:
        leased = session.scalar(
            select(func.count()).select_from(WikiJob).where(WikiJob.state == "leased")
        )
        queued = session.scalar(
            select(func.count()).select_from(WikiJob).where(WikiJob.state == "queued")
        )
    assert leased == 4
    assert queued == 2  # 超限任务保持排队，不被拒绝或丢弃


def test_p1_8_global_limit_returns_typed_reason_and_keeps_queue(
    factory: SessionFactory,
) -> None:
    store = make_store(factory, global_concurrency_limit=3, per_space_concurrency_limit=8)
    for index in range(3):
        store.enqueue(space_id="space-a", job_type="compile", idempotency_key=f"a-{index}")
        store.enqueue(space_id="space-b", job_type="compile", idempotency_key=f"b-{index}")

    claimed = _drain(store, ("space-a", "space-b"), "worker-1")
    assert len(claimed) == 3

    outcome = store.claim(space_ids=("space-a", "space-b"), worker_id="worker-1")
    assert isinstance(outcome, NoClaimableJob)
    assert outcome.reason == "global_concurrency_limit"
    with factory() as session:
        queued = session.scalar(
            select(func.count()).select_from(WikiJob).where(WikiJob.state == "queued")
        )
    assert queued == 3


def test_p1_8_saturated_space_does_not_block_other_space(factory: SessionFactory) -> None:
    store = make_store(factory, per_space_concurrency_limit=1)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="a-0")
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="a-1")
    store.enqueue(space_id="space-b", job_type="compile", idempotency_key="b-0")

    first = store.claim(space_ids=("space-a", "space-b"), worker_id="worker-1")
    assert isinstance(first, ClaimedJob)
    assert first.job.space_id == "space-a"

    second = store.claim(space_ids=("space-a", "space-b"), worker_id="worker-1")
    assert isinstance(second, ClaimedJob)
    assert second.job.space_id == "space-b"  # 跳过已饱和的 space-a

    third = store.claim(space_ids=("space-a", "space-b"), worker_id="worker-1")
    assert isinstance(third, NoClaimableJob)
    with factory() as session:
        remaining = list(
            session.execute(
                select(WikiJob.space_id, WikiJob.state).where(WikiJob.state == "queued")
            ).tuples()
        )
    assert remaining == [("space-a", "queued")]


# --- T5：heartbeat、数据库时钟过期回收与 fencing ---


def _claimed(store: JobStore, space_id: str, worker_id: str = "worker-1") -> JobSnapshot:
    outcome = store.claim(space_ids=(space_id,), worker_id=worker_id)
    assert isinstance(outcome, ClaimedJob)
    return outcome.job


def test_p1_3_heartbeat_extends_lease_only_by_configured_duration(
    factory: SessionFactory,
) -> None:
    short = make_store(factory, lease_seconds=300.0)
    longer = make_store(factory, lease_seconds=600.0)
    short.enqueue(space_id="space-a", job_type="compile", idempotency_key="job-1")
    claimed = _claimed(short, "space-a")
    assert claimed.lease_expires_at is not None

    extended = longer.heartbeat(
        space_id="space-a", job_id=claimed.id, generation=claimed.lease_generation
    )

    assert extended.lease_expires_at is not None
    assert extended.lease_expires_at > claimed.lease_expires_at
    assert extended.state is JobState.LEASED


def test_p1_3_heartbeat_with_stale_generation_is_rejected_with_zero_changes(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="job-1")
    claimed = _claimed(store, "space-a")

    with pytest.raises(StaleGenerationError):
        store.heartbeat(space_id="space-a", job_id=claimed.id, generation=0)

    unchanged = store.get_job(space_id="space-a", job_id=claimed.id)
    assert unchanged.lease_expires_at == claimed.lease_expires_at
    assert unchanged.state is JobState.LEASED


def test_p1_3_heartbeat_outside_leased_running_or_space_is_rejected(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    queued = store.enqueue(space_id="space-a", job_type="compile", idempotency_key="job-1").job

    with pytest.raises(IllegalTransitionError):
        store.heartbeat(space_id="space-a", job_id=queued.id, generation=0)
    with pytest.raises(SpaceScopeError):
        store.heartbeat(space_id="space-b", job_id=queued.id, generation=0)
    assert store.get_job(space_id="space-a", job_id=queued.id).state is JobState.QUEUED


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
        store.start(
            space_id="space-a", job_id=claimed.id, generation=claimed.lease_generation
        )


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
        store.heartbeat(
            space_id="space-a", job_id=running.id, generation=running.lease_generation
        )
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

    running = store.start(
        space_id="space-a", job_id=leased.id, generation=leased.lease_generation
    )
    store.report_success(
        space_id="space-a", job_id=running.id, generation=running.lease_generation
    )
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
    assert (
        expired_store.get_job(space_id="space-b", job_id=expired.id).state is JobState.LEASED
    )


# --- T6：完成事务 = 领域写 + outbox + 状态转换，原子且至多成功一次 ---


def _running_job(store: JobStore, space_id: str = "space-a", key: str = "job-1") -> JobSnapshot:
    store.enqueue(space_id=space_id, job_type="compile", idempotency_key=key)
    claimed = _claimed(store, space_id)
    return store.start(
        space_id=space_id, job_id=claimed.id, generation=claimed.lease_generation
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
        events=(
            OutboxEventDraft(event_type="job.succeeded", payload={"job_id": running.id}),
        ),
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

    def domain_write(handle: DomainWriteHandle) -> None:
        handle.execute(
            text("INSERT INTO domain_results_035 (job_id) VALUES (:job_id)"),
            {"job_id": running.id},
        )

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
                domain_write=domain_write,
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
        domain_write=domain_write,
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


def test_i8_domain_write_handle_cannot_commit_or_touch_session_lifecycle(
    factory: SessionFactory, job_engine: Engine
) -> None:
    with job_engine.begin() as connection:
        connection.execute(text("CREATE TABLE domain_guard_035 (job_id TEXT PRIMARY KEY)"))
    store = make_store(factory)
    running = _running_job(store)
    observed: dict[str, object] = {}

    def domain_write(handle: DomainWriteHandle) -> None:
        observed["has_commit"] = hasattr(handle, "commit")
        observed["has_rollback"] = hasattr(handle, "rollback")
        observed["has_close"] = hasattr(handle, "close")
        handle.execute(
            text("INSERT INTO domain_guard_035 (job_id) VALUES (:job_id)"),
            {"job_id": running.id},
        )
        raise RuntimeError("crash after domain write")

    with pytest.raises(RuntimeError, match="crash after domain write"):
        store.report_success(
            space_id="space-a",
            job_id=running.id,
            generation=running.lease_generation,
            events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
            domain_write=domain_write,
        )

    assert observed == {"has_commit": False, "has_rollback": False, "has_close": False}
    with factory() as session:
        assert session.scalar(text("SELECT count(*) FROM domain_guard_035")) == 0
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


# --- T7：backoff/max_attempts 只由配置决定；retry_wait 到期由存储层 requeue ---


def _db_now(factory: SessionFactory) -> datetime:
    with factory() as session:
        return database_now(session)


def _fail_retryable(store: JobStore, job: JobSnapshot, summary: str = "boom") -> JobSnapshot:
    return store.report_failure(
        space_id=job.space_id,
        job_id=job.id,
        generation=job.lease_generation,
        failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary=summary),
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
        job_type_policies={
            "fragile": JobTypePolicy(max_attempts=1, backoff_seconds=(0.0,))
        },
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
        running = store.start(
            space_id="space-a", job_id=job.id, generation=job.lease_generation
        )
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
    running2 = store.start(
        space_id="space-a", job_id=second.id, generation=second.lease_generation
    )
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
