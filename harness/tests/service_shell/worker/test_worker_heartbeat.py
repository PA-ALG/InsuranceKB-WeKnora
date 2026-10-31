"""wiki-worker：租约丢失取消处理器、瞬时心跳错误与心跳延迟上报。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from insurance_harness.jobs import (
    ClaimedJob,
    JobSnapshot,
    JobState,
)
from insurance_harness.service_shell.health import Lifecycle
from insurance_harness.service_shell.worker import (
    HandlerRegistry,
    HandlerResult,
    WorkerLoop,
)
from tests.service_shell.worker.helpers import _job, _settings, _store


@pytest.mark.parametrize("cleanup", ["cancel", "return", "raise"])
@pytest.mark.parametrize("loss_kind", ["expired", "generation", "terminal"])
async def test_g3_lost_lease_cancels_handler_and_releases_capacity(
    loss_kind: str, cleanup: str
) -> None:
    from insurance_harness.jobs.errors import (
        IllegalTransitionError,
        LeaseExpiredError,
        StaleGenerationError,
    )

    losses = {
        "expired": LeaseExpiredError(job_id="job-1"),
        "generation": StaleGenerationError(expected=2, actual=1, job_id="job-1"),
        "terminal": IllegalTransitionError(JobState.DEAD_LETTER, JobState.DEAD_LETTER, "job-1"),
    }
    store = _store([ClaimedJob(job=_job(1)), ClaimedJob(job=_job(2))])
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    cancelled, root_started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_heartbeat = store.heartbeat

    def heartbeat(**kwargs: Any) -> JobSnapshot:
        if kwargs["job_id"] == "job-1":
            store.calls.append(("heartbeat", "job-1"))
            raise losses[loss_kind]
        return original_heartbeat(**kwargs)

    store.heartbeat = heartbeat  # type: ignore[method-assign]
    registry = HandlerRegistry()

    async def handler(job: JobSnapshot) -> HandlerResult:
        if job.id == "job-1":
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                if cleanup == "return":
                    return HandlerResult()
                if cleanup == "raise":
                    raise RuntimeError("cancellation cleanup failed") from None
                raise
        else:
            root_started.set()
            lifecycle.begin_drain()
        return HandlerResult()

    registry.register("known", handler)
    worker = WorkerLoop(
        store=store,
        registry=registry,
        settings=_settings(worker_local_concurrency=1),
        lifecycle=lifecycle,
        worker_id="worker-a",
    )
    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(root_started.wait(), timeout=0.5)
        await asyncio.wait_for(task, timeout=0.5)
        assert cancelled.is_set()
        assert ("success", "job-2") in store.calls
        assert not any(
            name in {"success", "failure"} and job == "job-1" for name, job in store.calls
        )
    finally:
        lifecycle.begin_drain()
        release.set()
        if not task.done():
            await asyncio.wait_for(task, timeout=1)


async def test_g3_transient_heartbeat_error_does_not_cancel_handler() -> None:
    store = _store()
    store.jobs["job-1"] = _job(1)
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    original_heartbeat = store.heartbeat
    attempts = 0

    def heartbeat(**kwargs: Any) -> JobSnapshot:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("temporary database outage")
        return original_heartbeat(**kwargs)

    store.heartbeat = heartbeat  # type: ignore[method-assign]
    registry = HandlerRegistry()

    async def handler(_job: JobSnapshot) -> HandlerResult:
        while attempts < 2:
            await asyncio.sleep(0.005)
        return HandlerResult()

    registry.register("known", handler)
    worker = WorkerLoop(
        store=store,
        registry=registry,
        settings=_settings(),
        lifecycle=lifecycle,
        worker_id="worker-a",
    )
    await asyncio.wait_for(worker.process_job(_job(1)), timeout=0.5)
    assert ("success", "job-1") in store.calls
    assert store.failures == []


async def test_heartbeat_reports_loop_queue_and_database_delay_without_payload(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import logging
    import time

    store = _store()
    store.jobs["job-1"] = _job(1)
    registry = HandlerRegistry()
    beats = 0

    def heartbeat(**kwargs: object) -> JobSnapshot:
        nonlocal beats
        time.sleep(0.005)
        beats += 1
        return store.jobs["job-1"]

    monkeypatch.setattr(store, "heartbeat", heartbeat)

    async def handler(job: JobSnapshot) -> HandlerResult:
        while beats < 1:
            await asyncio.sleep(0.002)
        return HandlerResult()

    registry.register("known", handler)
    worker = WorkerLoop(
        store=store,
        registry=registry,
        settings=_settings(),
        lifecycle=Lifecycle(),
        worker_id="worker-a",
    )
    with caplog.at_level(logging.INFO):
        await asyncio.wait_for(worker.process_job(_job(1)), 1)
    records = [r for r in caplog.records if getattr(r, "event", "") == "job_heartbeat"]
    assert records, "lease health lacks timing diagnostics"
    record = records[0]
    assert record.__dict__["job_id"] == "job-1" and record.__dict__["generation"] == 1
    assert (
        record.__dict__["loop_delay_seconds"] >= 0 and record.__dict__["executor_wait_seconds"] >= 0
    )
    assert record.__dict__["database_seconds"] >= 0.005 and record.__dict__["error_type"] is None
    assert "payload" not in record.__dict__
