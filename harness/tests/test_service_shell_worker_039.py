from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select, text

from insurance_harness.jobs import (
    ClaimedJob,
    ErrorClass,
    JobFailure,
    JobSnapshot,
    JobState,
    JobStore,
    NoClaimableJob,
)
from insurance_harness.jobs.tables import WikiJob
from insurance_harness.service_shell.config import ShellSettings
from insurance_harness.service_shell.health import Lifecycle
from insurance_harness.service_shell.worker import (
    HandlerRegistry,
    HandlerResult,
    WorkerLoop,
)
from tests.test_job_store_postgres_035 import PostgresRuntime, _fresh_runtime


def _job(number: int, *, job_type: str = "known") -> JobSnapshot:
    now = datetime.now(UTC)
    return JobSnapshot(
        id=f"job-{number}",
        space_id="space-a",
        job_type=job_type,
        idempotency_key=f"key-{number}",
        payload={"number": number},
        state=JobState.LEASED,
        attempt=0,
        lease_generation=1,
        worker_id="worker-a",
        available_at=now,
        lease_expires_at=now,
        enqueued_at=now,
        started_at=None,
        finished_at=None,
        error_class=None,
        error_summary=None,
    )


class RecordingStore:
    def __init__(self, outcomes: list[Any] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.calls: list[tuple[str, str]] = []
        self.failures: list[JobFailure] = []
        self.jobs = {
            outcome.job.id: outcome.job
            for outcome in self.outcomes
            if isinstance(outcome, ClaimedJob)
        }

    def claim(self, *, space_ids: tuple[str, ...], worker_id: str) -> Any:
        self.calls.append(("claim", worker_id))
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        return NoClaimableJob(reason="empty")

    def start(self, *, space_id: str, job_id: str, generation: int) -> JobSnapshot:
        self.calls.append(("start", job_id))
        return self.jobs[job_id]

    def heartbeat(self, *, space_id: str, job_id: str, generation: int) -> JobSnapshot:
        self.calls.append(("heartbeat", job_id))
        return _job(int(job_id.split("-")[1]))

    def report_success(self, **kwargs: Any) -> JobSnapshot:
        job_id = str(kwargs["job_id"])
        self.calls.append(("success", job_id))
        return _job(int(job_id.split("-")[1]))

    def report_failure(
        self,
        *,
        space_id: str,
        job_id: str,
        generation: int,
        failure: JobFailure,
    ) -> JobSnapshot:
        self.calls.append(("failure", job_id))
        self.failures.append(failure)
        return _job(int(job_id.split("-")[1]))


def _store(outcomes: list[Any] | None = None) -> RecordingStore:
    return RecordingStore(outcomes)


def _settings(**overrides: Any) -> ShellSettings:
    values: dict[str, Any] = {
        "postgres_dsn": "postgresql+psycopg://wiki:secret@db/wiki",
        "worker_space_ids": ("space-a",),
        "heartbeat_interval_seconds": 0.01,
        "lease_seconds": 1,
        "claim_poll_interval_seconds": 0.01,
        "transient_backoff_seconds": (0.01, 0.02),
        "drain_deadline_seconds": 0.2,
        "total_shutdown_timeout_seconds": 0.3,
    }
    values.update(overrides)
    return ShellSettings(**values)


@pytest.fixture(scope="module")
def postgres_039_runtime() -> Iterator[PostgresRuntime]:
    """Reuse P1's controlled PostgreSQL 16 database lifecycle for P3 acceptance."""
    yield from _fresh_runtime()


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


async def test_t5_registered_handler_uses_only_p1_typed_execution_surface() -> None:
    store = _store()
    store.jobs["job-1"] = _job(1)
    registry = HandlerRegistry()

    async def handler(job: JobSnapshot) -> HandlerResult:
        await asyncio.sleep(0.03)
        return HandlerResult()

    registry.register("known", handler)
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    worker = WorkerLoop(
        store=store,
        registry=registry,
        settings=_settings(),
        lifecycle=lifecycle,
        worker_id="worker-a",
    )
    await worker.process_job(_job(1))
    names = [name for name, _job_id in store.calls]
    assert names[0] == "start"
    assert "heartbeat" in names
    assert names[-1] == "success"
    assert store.failures == []


async def test_t5_completion_stops_heartbeat_without_waiting_for_its_interval() -> None:
    store = _store()
    store.jobs["job-9"] = _job(9)
    registry = HandlerRegistry()

    async def handler(_job: JobSnapshot) -> HandlerResult:
        await asyncio.sleep(0)
        return HandlerResult()

    registry.register("known", handler)
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    worker = WorkerLoop(
        store=store,
        registry=registry,
        settings=_settings(heartbeat_interval_seconds=0.5, lease_seconds=1),
        lifecycle=lifecycle,
        worker_id="worker-a",
    )
    await asyncio.wait_for(worker.process_job(_job(9)), timeout=0.05)
    assert store.calls[-1] == ("success", "job-9")


async def test_t5_unknown_job_type_is_retryable_and_not_success() -> None:
    store = _store()
    store.jobs["job-2"] = _job(2, job_type="unregistered")
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    worker = WorkerLoop(
        store=store,
        registry=HandlerRegistry(),
        settings=_settings(),
        lifecycle=lifecycle,
        worker_id="worker-a",
    )
    await worker.process_job(_job(2, job_type="unregistered"))
    assert ("success", "job-2") not in store.calls
    assert store.failures == [
        JobFailure(
            error_class=ErrorClass.RETRYABLE,
            summary="RetryableJobError: unknown_job_type",
        )
    ]


async def test_t5_local_concurrency_limits_claims_and_drain_stops_new_claims() -> None:
    jobs = [ClaimedJob(job=_job(number)) for number in range(1, 5)]
    store = _store(jobs)
    registry = HandlerRegistry()
    release = asyncio.Event()
    active = 0
    maximum = 0

    async def handler(job: JobSnapshot) -> HandlerResult:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        try:
            await release.wait()
            return HandlerResult()
        finally:
            active -= 1

    registry.register("known", handler)
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    worker = WorkerLoop(
        store=store,
        registry=registry,
        settings=_settings(worker_local_concurrency=2),
        lifecycle=lifecycle,
        worker_id="worker-a",
    )
    task = asyncio.create_task(worker.run())
    while maximum < 2:
        await asyncio.sleep(0)
    lifecycle.begin_drain()
    release.set()
    await task
    assert maximum == 2
    assert len([call for call in store.calls if call[0] == "claim"]) == 2
    assert len([call for call in store.calls if call[0] == "success"]) == 2


async def test_t5_empty_poll_and_transient_failures_use_configured_delays() -> None:
    store = _store(
        [
            OSError("temporary-1"),
            OSError("temporary-2"),
            NoClaimableJob(reason="empty"),
        ]
    )
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    delays: list[float] = []

    async def sleeper(delay: float) -> None:
        delays.append(delay)
        if len(delays) == 3:
            lifecycle.begin_drain()

    worker = WorkerLoop(
        store=store,
        registry=HandlerRegistry(),
        settings=_settings(claim_poll_interval_seconds=0.07),
        lifecycle=lifecycle,
        worker_id="worker-a",
        sleeper=sleeper,
    )
    await worker.run()
    assert delays == [0.01, 0.02, 0.07]


async def test_t6_drain_timeout_abandons_generation_and_stops_heartbeat() -> None:
    claimed = ClaimedJob(job=_job(7))
    store = _store([claimed])
    registry = HandlerRegistry()
    started = asyncio.Event()

    async def handler(job: JobSnapshot) -> HandlerResult:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    registry.register("known", handler)
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    worker = WorkerLoop(
        store=store,
        registry=registry,
        settings=_settings(
            worker_local_concurrency=1,
            heartbeat_interval_seconds=0.005,
            drain_deadline_seconds=0.02,
            total_shutdown_timeout_seconds=0.08,
        ),
        lifecycle=lifecycle,
        worker_id="worker-a",
    )
    task = asyncio.create_task(worker.run())
    await started.wait()
    lifecycle.begin_drain()
    await asyncio.wait_for(task, timeout=0.08)
    writes = [name for name, _job_id in store.calls if name in {"success", "failure"}]
    assert writes == []
    heartbeat_count = len([call for call in store.calls if call[0] == "heartbeat"])
    await asyncio.sleep(0.02)
    assert len([call for call in store.calls if call[0] == "heartbeat"]) == heartbeat_count


async def test_t6_repeated_signal_requests_immediate_bounded_exit() -> None:
    claimed = ClaimedJob(job=_job(8))
    store = _store([claimed])
    registry = HandlerRegistry()
    started = asyncio.Event()

    async def handler(job: JobSnapshot) -> HandlerResult:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    registry.register("known", handler)
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    worker = WorkerLoop(
        store=store,
        registry=registry,
        settings=_settings(
            claim_poll_interval_seconds=0.005,
            drain_deadline_seconds=5,
            total_shutdown_timeout_seconds=6,
        ),
        lifecycle=lifecycle,
        worker_id="worker-a",
    )
    task = asyncio.create_task(worker.run())
    await started.wait()
    assert lifecycle.begin_drain() is True
    assert lifecycle.begin_drain() is False
    assert lifecycle.immediate_termination_requested is True
    await asyncio.wait_for(task, timeout=0.08)
    assert not [
        call for call in store.calls if call[0] in {"success", "failure"}
    ]


async def test_t6_repeated_signal_wakes_an_active_drain_wait() -> None:
    claimed = ClaimedJob(job=_job(10))
    store = _store([claimed])
    registry = HandlerRegistry()
    started = asyncio.Event()

    async def handler(job: JobSnapshot) -> HandlerResult:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    registry.register("known", handler)
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    worker = WorkerLoop(
        store=store,
        registry=registry,
        settings=_settings(
            claim_poll_interval_seconds=0.005,
            drain_deadline_seconds=10,
            total_shutdown_timeout_seconds=11,
        ),
        lifecycle=lifecycle,
        worker_id="worker-a",
    )
    task = asyncio.create_task(worker.run())
    await started.wait()
    assert lifecycle.begin_drain() is True
    await asyncio.sleep(0.02)
    assert lifecycle.begin_drain() is False
    await asyncio.wait_for(task, timeout=0.08)
    assert not [
        call for call in store.calls if call[0] in {"success", "failure"}
    ]


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
