"""wiki-worker（039 T5/T6）：真实 PostgreSQL 上的双 worker 单结果与 drain 回收。"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter

import pytest
from sqlalchemy import select, text

from insurance_harness.jobs import (
    ErrorClass,
    JobSnapshot,
    JobState,
    JobStore,
)
from insurance_harness.jobs.tables import WikiJob
from insurance_harness.service_shell.health import Lifecycle
from insurance_harness.service_shell.worker import (
    HandlerRegistry,
    HandlerResult,
    WorkerLoop,
)
from tests.jobs.job_store_postgres.helpers import PostgresRuntime
from tests.service_shell.worker.helpers import _settings


def _postgres_rows(
    runtime: PostgresRuntime,
    *,
    space_id: str,
) -> dict[str, tuple[str, int, int, str, str | None, str | None]]:
    with runtime.factory() as session:
        rows = session.scalars(
            select(WikiJob).where(WikiJob.space_id == space_id).order_by(WikiJob.id)
        ).all()
    return {
        row.id: (
            row.state,
            row.attempt,
            row.lease_generation,
            row.job_type,
            row.error_class,
            row.error_summary,
        )
        for row in rows
    }


async def _wait_for_postgres_states(
    runtime: PostgresRuntime,
    *,
    space_id: str,
    expected_count: int,
    terminal_states: set[str],
    timeout: float = 5.0,
) -> dict[str, tuple[str, int, int, str, str | None, str | None]]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        rows = _postgres_rows(runtime, space_id=space_id)
        if len(rows) == expected_count and all(
            values[0] in terminal_states for values in rows.values()
        ):
            return rows
        await asyncio.sleep(0.01)
    pytest.fail(f"PostgreSQL jobs did not reach {terminal_states}: {rows}")


@pytest.mark.integration_postgres
async def test_t5_postgres_two_workers_single_result_and_unknown_type_budget(
    postgres_039_runtime: PostgresRuntime,
) -> None:
    space_id = f"p3-t5-{uuid.uuid4().hex[:24]}"
    settings = _settings(
        worker_space_ids=(space_id,),
        worker_local_concurrency=2,
        heartbeat_interval_seconds=0.05,
        lease_seconds=1,
        claim_poll_interval_seconds=0.01,
        job_max_attempts=2,
        job_backoff_seconds=(0.0,),
        job_per_space_concurrency_limit=8,
        job_global_concurrency_limit=16,
    )
    stores = (
        JobStore(postgres_039_runtime.factory, settings.job_runtime_config()),
        JobStore(postgres_039_runtime.factory, settings.job_runtime_config()),
    )
    stores[0].enqueue(
        space_id=space_id,
        job_type="unregistered",
        idempotency_key="unknown",
    )
    for index in range(4):
        stores[0].enqueue(
            space_id=space_id,
            job_type="known",
            idempotency_key=f"known-{index}",
            payload={"index": index},
        )

    handler_calls: Counter[str] = Counter()

    async def handler(job: JobSnapshot) -> HandlerResult:
        handler_calls[job.id] += 1
        await asyncio.sleep(0.01)
        return HandlerResult()

    lifecycles = (Lifecycle(), Lifecycle())
    workers: list[WorkerLoop] = []
    for index, lifecycle in enumerate(lifecycles):
        registry = HandlerRegistry()
        registry.register("known", handler)
        lifecycle.mark_serving()
        workers.append(
            WorkerLoop(
                store=stores[index],
                registry=registry,
                settings=settings,
                lifecycle=lifecycle,
                worker_id=f"worker-{index}",
            )
        )
    tasks = [asyncio.create_task(worker.run()) for worker in workers]
    rows = await _wait_for_postgres_states(
        postgres_039_runtime,
        space_id=space_id,
        expected_count=5,
        terminal_states={JobState.SUCCEEDED.value, JobState.DEAD_LETTER.value},
    )
    for lifecycle in lifecycles:
        lifecycle.begin_drain()
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=1)

    known_rows = [values for values in rows.values() if values[3] == "known"]
    unknown_rows = [values for values in rows.values() if values[3] == "unregistered"]
    assert len(known_rows) == 4
    assert all(values[0] == JobState.SUCCEEDED.value for values in known_rows)
    assert len(handler_calls) == 4
    assert set(handler_calls.values()) == {1}
    assert unknown_rows == [
        (
            JobState.DEAD_LETTER.value,
            2,
            2,
            "unregistered",
            ErrorClass.RETRYABLE.value,
            "RetryableJobError: unknown_job_type",
        )
    ]


@pytest.mark.integration_postgres
async def test_t6_postgres_drain_reclaims_with_higher_generation_and_one_result(
    postgres_039_runtime: PostgresRuntime,
) -> None:
    space_id = f"p3-t6-{uuid.uuid4().hex[:24]}"
    settings = _settings(
        worker_space_ids=(space_id,),
        worker_local_concurrency=1,
        heartbeat_interval_seconds=0.01,
        lease_seconds=1,
        claim_poll_interval_seconds=0.01,
        drain_deadline_seconds=0.05,
        total_shutdown_timeout_seconds=0.2,
        job_backoff_seconds=(0.0,),
    )
    first_store = JobStore(
        postgres_039_runtime.factory,
        settings.job_runtime_config(),
    )
    queued = first_store.enqueue(
        space_id=space_id,
        job_type="known",
        idempotency_key="takeover",
    ).job
    first_started = asyncio.Event()
    first_cancelled = asyncio.Event()
    first_registry = HandlerRegistry()

    async def stalled_handler(_job: JobSnapshot) -> HandlerResult:
        first_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            first_cancelled.set()
        raise AssertionError("unreachable")

    first_registry.register("known", stalled_handler)
    first_lifecycle = Lifecycle()
    first_lifecycle.mark_serving()
    first_task = asyncio.create_task(
        WorkerLoop(
            store=first_store,
            registry=first_registry,
            settings=settings,
            lifecycle=first_lifecycle,
            worker_id="worker-first",
        ).run()
    )
    await asyncio.wait_for(first_started.wait(), timeout=1)
    drain_started = asyncio.get_running_loop().time()
    assert first_lifecycle.begin_drain() is True
    await asyncio.wait_for(first_task, timeout=settings.total_shutdown_timeout_seconds)
    assert asyncio.get_running_loop().time() - drain_started < (
        settings.total_shutdown_timeout_seconds
    )
    assert first_cancelled.is_set()
    abandoned = _postgres_rows(postgres_039_runtime, space_id=space_id)[queued.id]
    assert abandoned[:3] == (JobState.RUNNING.value, 1, 1)

    with postgres_039_runtime.factory() as session:
        with session.begin():
            session.execute(
                text(
                    "UPDATE wiki_jobs SET lease_expires_at = "
                    "timestamptz '2000-01-01 00:00:00+00' WHERE id = :job_id"
                ),
                {"job_id": queued.id},
            )

    second_calls: list[int] = []
    second_registry = HandlerRegistry()

    async def succeeding_handler(job: JobSnapshot) -> HandlerResult:
        second_calls.append(job.lease_generation)
        return HandlerResult()

    second_registry.register("known", succeeding_handler)
    second_lifecycle = Lifecycle()
    second_lifecycle.mark_serving()
    second_task = asyncio.create_task(
        WorkerLoop(
            store=JobStore(
                postgres_039_runtime.factory,
                settings.job_runtime_config(),
            ),
            registry=second_registry,
            settings=settings,
            lifecycle=second_lifecycle,
            worker_id="worker-second",
        ).run()
    )
    rows = await _wait_for_postgres_states(
        postgres_039_runtime,
        space_id=space_id,
        expected_count=1,
        terminal_states={JobState.SUCCEEDED.value},
    )
    second_lifecycle.begin_drain()
    await asyncio.wait_for(second_task, timeout=1)

    assert len(second_calls) == 1
    assert second_calls[0] > abandoned[2]
    assert rows[queued.id][:2] == (JobState.SUCCEEDED.value, 2)
    assert rows[queued.id][2] == second_calls[0]
