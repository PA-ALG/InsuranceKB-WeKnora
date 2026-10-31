"""JobStore（SQLite）：enqueue 幂等、claim 的 Space 范围与单 Space / 全局并发上限。"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from insurance_harness.jobs import (
    ClaimedJob,
    EnqueueResult,
    JobState,
    JobStore,
    NoClaimableJob,
    SpaceScopeError,
)
from insurance_harness.jobs.tables import WikiJob
from tests.jobs.job_store.helpers import SessionFactory, job_count, make_store

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
