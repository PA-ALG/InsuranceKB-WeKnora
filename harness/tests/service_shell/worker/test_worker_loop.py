"""wiki-worker（039 T5/T6）：类型化执行面、并发上限、轮询延迟、drain 与重复信号。"""

from __future__ import annotations

import asyncio

from insurance_harness.jobs import (
    ClaimedJob,
    ErrorClass,
    JobFailure,
    JobSnapshot,
    NoClaimableJob,
)
from insurance_harness.service_shell.health import Lifecycle
from insurance_harness.service_shell.worker import (
    HandlerRegistry,
    HandlerResult,
    WorkerLoop,
)
from tests.service_shell.worker.helpers import _job, _settings, _store


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
    assert not [call for call in store.calls if call[0] in {"success", "failure"}]


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
    assert not [call for call in store.calls if call[0] in {"success", "failure"}]
