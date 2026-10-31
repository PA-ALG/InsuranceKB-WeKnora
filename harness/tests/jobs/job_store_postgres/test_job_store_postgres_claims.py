"""JobStore（PostgreSQL）：并发 enqueue / claim、限额、lease 接管与 active fence。"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from insurance_harness.jobs import (
    ClaimedJob,
    JobState,
    LeaseExpiredError,
    NoClaimableJob,
    StaleGenerationError,
)
from insurance_harness.jobs.tables import WikiJob
from tests.jobs.job_store_postgres.helpers import (
    FUTURE_TIMEOUT_S,
    PostgresRuntime,
    _force_expire,
    _outbox_count,
    _space,
    _store,
)


def _job_states(runtime: PostgresRuntime, space_id: str) -> dict[str, str]:
    with runtime.factory() as session:
        rows = session.execute(
            select(WikiJob.id, WikiJob.state).where(WikiJob.space_id == space_id)
        ).all()
    return {job_id: state for job_id, state in rows}


# --- T3：并发幂等 enqueue 与 ≥8 连接并发单领 ---


@pytest.mark.integration_postgres
def test_p1_5_concurrent_duplicate_enqueue_creates_exactly_one_row(
    postgres_runtime: PostgresRuntime,
) -> None:
    store = _store(postgres_runtime)
    space_id = _space("dedup")
    barrier = threading.Barrier(8)

    def race() -> bool:
        barrier.wait(timeout=10)
        return store.enqueue(
            space_id=space_id,
            job_type="compile",
            idempotency_key="revision-1",
        ).deduplicated

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = [
            future.result(timeout=FUTURE_TIMEOUT_S)
            for future in [executor.submit(race) for _ in range(8)]
        ]

    assert outcomes.count(False) == 1
    assert outcomes.count(True) == 7
    with postgres_runtime.factory() as session:
        count = session.scalar(
            select(func.count()).select_from(WikiJob).where(WikiJob.space_id == space_id)
        )
    assert count == 1


@pytest.mark.integration_postgres
def test_p1_2_eight_workers_claim_each_job_exactly_once_until_typed_empty(
    postgres_runtime: PostgresRuntime,
) -> None:
    store = _store(postgres_runtime)
    space_id = _space("claim")
    total_jobs = 24
    for index in range(total_jobs):
        store.enqueue(space_id=space_id, job_type="compile", idempotency_key=f"job-{index}")

    barrier = threading.Barrier(8)

    def drain(worker_index: int) -> list[tuple[str, int]]:
        claims: list[tuple[str, int]] = []
        barrier.wait(timeout=10)
        while True:
            outcome = store.claim(space_ids=(space_id,), worker_id=f"worker-{worker_index}")
            if isinstance(outcome, NoClaimableJob):
                assert outcome.reason == "empty"
                return claims
            claims.append((outcome.job.id, outcome.job.lease_generation))

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(drain, index) for index in range(8)]
        results = [future.result(timeout=FUTURE_TIMEOUT_S) for future in futures]

    claimed = [claim for chunk in results for claim in chunk]
    assert len(claimed) == total_jobs
    assert len({job_id for job_id, _generation in claimed}) == total_jobs
    assert all(generation == 1 for _job_id, generation in claimed)
    assert all(state == "leased" for state in _job_states(postgres_runtime, space_id).values())


@pytest.mark.integration_postgres
def test_p1_2_claim_skips_externally_locked_row_without_blocking(
    postgres_runtime: PostgresRuntime,
) -> None:
    store = _store(postgres_runtime)
    space_id = _space("skip")
    first = store.enqueue(space_id=space_id, job_type="compile", idempotency_key="job-1").job
    second = store.enqueue(space_id=space_id, job_type="compile", idempotency_key="job-2").job

    with postgres_runtime.factory() as blocker:
        locked = blocker.execute(
            select(WikiJob.id).where(WikiJob.id == first.id).with_for_update()
        ).scalar_one()
        assert locked == first.id

        outcome = store.claim(space_ids=(space_id,), worker_id="worker-b")
        assert isinstance(outcome, ClaimedJob)
        assert outcome.job.id == second.id
        assert outcome.job.state is JobState.LEASED
        blocker.rollback()


# --- T4：并发下 per-Space 限额不被突破，饱和 Space 不阻塞其他 Space ---


@pytest.mark.integration_postgres
def test_p1_8_concurrent_claims_never_exceed_per_space_limit(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("limit")
    store = _store(postgres_runtime, per_space_concurrency_limit=2)
    for index in range(6):
        store.enqueue(space_id=space_id, job_type="compile", idempotency_key=f"job-{index}")

    barrier = threading.Barrier(8)

    def race(worker_index: int) -> int:
        barrier.wait(timeout=10)
        outcome = store.claim(space_ids=(space_id,), worker_id=f"worker-{worker_index}")
        return 1 if isinstance(outcome, ClaimedJob) else 0

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(race, index) for index in range(8)]
        wins = sum(future.result(timeout=FUTURE_TIMEOUT_S) for future in futures)

    assert wins == 2
    states = list(_job_states(postgres_runtime, space_id).values())
    assert states.count("leased") == 2
    assert states.count("queued") == 4


@pytest.mark.integration_postgres
def test_p1_8_saturated_space_does_not_block_sibling_space(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_a = _space("sat-a")
    space_b = _space("sat-b")
    store = _store(postgres_runtime, per_space_concurrency_limit=1)
    store.enqueue(space_id=space_a, job_type="compile", idempotency_key="a-0")
    store.enqueue(space_id=space_a, job_type="compile", idempotency_key="a-1")
    store.enqueue(space_id=space_b, job_type="compile", idempotency_key="b-0")

    first = store.claim(space_ids=(space_a, space_b), worker_id="worker-1")
    assert isinstance(first, ClaimedJob)
    assert first.job.space_id == space_a

    second = store.claim(space_ids=(space_a, space_b), worker_id="worker-1")
    assert isinstance(second, ClaimedJob)
    assert second.job.space_id == space_b

    third = store.claim(space_ids=(space_a, space_b), worker_id="worker-1")
    assert isinstance(third, NoClaimableJob)
    assert _job_states(postgres_runtime, space_a)[
        store.enqueue(space_id=space_a, job_type="compile", idempotency_key="a-1").job.id
    ] == "queued"


@pytest.mark.integration_postgres
def test_p1_3_expired_lease_is_reclaimed_and_retaken_with_greater_generation(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("takeover")
    expiring = _store(postgres_runtime)
    healthy = _store(postgres_runtime, lease_seconds=300.0)
    expiring.enqueue(space_id=space_id, job_type="compile", idempotency_key="job-1")

    stale = expiring.claim(space_ids=(space_id,), worker_id="worker-a")
    assert isinstance(stale, ClaimedJob)
    expiring.start(
        space_id=space_id, job_id=stale.job.id, generation=stale.job.lease_generation
    )
    _force_expire(postgres_runtime, stale.job.id)

    takeover = healthy.claim(space_ids=(space_id,), worker_id="worker-b")
    assert isinstance(takeover, ClaimedJob)
    assert takeover.job.id == stale.job.id
    assert takeover.job.lease_generation > stale.job.lease_generation
    assert takeover.job.worker_id == "worker-b"
    assert takeover.job.error_summary == "lease_expired"

    with pytest.raises(StaleGenerationError):
        healthy.heartbeat(
            space_id=space_id, job_id=stale.job.id, generation=stale.job.lease_generation
        )
    with pytest.raises(StaleGenerationError):
        healthy.start(
            space_id=space_id, job_id=stale.job.id, generation=stale.job.lease_generation
        )

    current = healthy.get_job(space_id=space_id, job_id=stale.job.id)
    assert current.state is JobState.LEASED
    assert current.lease_generation == takeover.job.lease_generation
    assert current.worker_id == "worker-b"


@pytest.mark.integration_postgres
def test_p1_13_active_fence_uses_postgres_clock_and_never_mutates_job(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("active-fence")
    store = _store(postgres_runtime)
    store.enqueue(space_id=space_id, job_type="compile", idempotency_key="job-1")
    claimed = store.claim(space_ids=(space_id,), worker_id="worker-a")
    assert isinstance(claimed, ClaimedJob)
    running = store.start(
        space_id=space_id,
        job_id=claimed.job.id,
        generation=claimed.job.lease_generation,
    )
    before = store.get_job(space_id=space_id, job_id=running.id)

    verified = store.verify_active_fence(
        space_id=space_id,
        job_id=running.id,
        generation=running.lease_generation,
        attempt=running.attempt,
    )

    assert verified == before
    assert store.get_job(space_id=space_id, job_id=running.id) == before
    assert _outbox_count(postgres_runtime, space_id) == 0

    _force_expire(postgres_runtime, running.id)
    barrier = threading.Barrier(2)

    def verify_expired_fence() -> type[BaseException] | None:
        barrier.wait(timeout=10)
        try:
            store.verify_active_fence(
                space_id=space_id,
                job_id=running.id,
                generation=running.lease_generation,
                attempt=running.attempt,
            )
        except (LeaseExpiredError, StaleGenerationError) as error:
            return type(error)
        return None

    def reclaim() -> None:
        barrier.wait(timeout=10)
        store.reclaim_expired_leases(space_ids=(space_id,))

    with ThreadPoolExecutor(max_workers=2) as executor:
        verify_future = executor.submit(verify_expired_fence)
        reclaim_future = executor.submit(reclaim)
        assert verify_future.result(timeout=FUTURE_TIMEOUT_S) in {
            LeaseExpiredError,
            StaleGenerationError,
        }
        reclaim_future.result(timeout=FUTURE_TIMEOUT_S)

    # reclaim 使用 SKIP LOCKED；若 verifier 先持有共享锁，本轮回收允许跳过，
    # 下一轮必须在锁释放后收敛。两种线性化顺序都不得让旧 fence 通过。
    store.reclaim_expired_leases(space_ids=(space_id,))
    reclaimed = store.get_job(space_id=space_id, job_id=running.id)
    assert reclaimed.state is JobState.QUEUED
    assert reclaimed.lease_generation == running.lease_generation + 1
    assert _outbox_count(postgres_runtime, space_id) == 0
