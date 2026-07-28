"""P1-backed Worker loop skeleton with an intentionally empty handler registry."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from insurance_harness.jobs import (
    ClaimedJob,
    DomainWriteSpec,
    JobFailure,
    JobSnapshot,
    NoClaimableJob,
    OutboxEventDraft,
    RetryableJobError,
    classify_failure,
)
from insurance_harness.service_shell.config import ShellSettings
from insurance_harness.service_shell.health import Lifecycle, ProcessState


@dataclass(frozen=True, slots=True)
class HandlerResult:
    """Declarative P1 completion payload returned by a registered handler."""

    events: tuple[OutboxEventDraft, ...] = ()
    domain_writes: tuple[DomainWriteSpec, ...] = ()


Handler = Callable[[JobSnapshot], Awaitable[HandlerResult]]
Sleeper = Callable[[float], Awaitable[None]]


class JobStoreSurface(Protocol):
    """Only the merged P1 public methods that a Worker role may invoke."""

    def claim(self, *, space_ids: tuple[str, ...], worker_id: str) -> Any: ...

    def start(self, *, space_id: str, job_id: str, generation: int) -> JobSnapshot: ...

    def heartbeat(self, *, space_id: str, job_id: str, generation: int) -> JobSnapshot: ...

    def report_success(
        self,
        *,
        space_id: str,
        job_id: str,
        generation: int,
        events: tuple[OutboxEventDraft, ...],
        domain_writes: tuple[DomainWriteSpec, ...],
    ) -> JobSnapshot: ...

    def report_failure(
        self,
        *,
        space_id: str,
        job_id: str,
        generation: int,
        failure: JobFailure,
    ) -> JobSnapshot: ...


class HandlerRegistry:
    """Explicit extension point; production P3 registers no business handler."""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    @property
    def handlers(self) -> Mapping[str, Handler]:
        return dict(self._handlers)

    def register(self, job_type: str, handler: Handler) -> None:
        if not job_type or "\x00" in job_type:
            raise ValueError("job_type must be non-empty and contain no NUL")
        if job_type in self._handlers:
            raise ValueError(f"handler already registered for {job_type!r}")
        self._handlers[job_type] = handler

    def get(self, job_type: str) -> Handler | None:
        return self._handlers.get(job_type)


class WorkerLoop:
    """Claim only with free local capacity and leave all durable semantics to P1."""

    def __init__(
        self,
        *,
        store: JobStoreSurface,
        registry: HandlerRegistry,
        settings: ShellSettings,
        lifecycle: Lifecycle,
        worker_id: str,
        sleeper: Sleeper = asyncio.sleep,
    ) -> None:
        self._store = store
        self._registry = registry
        self._settings = settings
        self._lifecycle = lifecycle
        self._worker_id = worker_id
        self._sleep = sleeper
        self._tasks: set[asyncio.Task[None]] = set()
        self.last_transient_error: str | None = None

    async def _store_call(self, operation: Callable[..., Any], **kwargs: Any) -> Any:
        return await asyncio.to_thread(operation, **kwargs)

    async def _heartbeat(self, job: JobSnapshot, stop: asyncio.Event) -> None:
        backoff_index = 0
        while not stop.is_set():
            await self._sleep(self._settings.heartbeat_interval_seconds)
            if stop.is_set():
                return
            try:
                await self._store_call(
                    self._store.heartbeat,
                    space_id=job.space_id,
                    job_id=job.id,
                    generation=job.lease_generation,
                )
                backoff_index = 0
            except Exception as error:
                self.last_transient_error = type(error).__name__
                delays = self._settings.transient_backoff_seconds
                delay = delays[min(backoff_index, len(delays) - 1)]
                backoff_index += 1
                await self._sleep(delay)

    @staticmethod
    async def _stop_heartbeat(
        task: asyncio.Task[None] | None,
        stop: asyncio.Event,
    ) -> None:
        stop.set()
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def process_job(self, claimed: JobSnapshot) -> None:
        """Execute one claimed generation; cancellation deliberately performs no write."""
        started = False
        heartbeat_stop = asyncio.Event()
        heartbeat_task: asyncio.Task[None] | None = None
        try:
            job = await self._store_call(
                self._store.start,
                space_id=claimed.space_id,
                job_id=claimed.id,
                generation=claimed.lease_generation,
            )
            started = True
            heartbeat_task = asyncio.create_task(self._heartbeat(job, heartbeat_stop))
            handler = self._registry.get(job.job_type)
            if handler is None:
                raise RetryableJobError("unknown_job_type")
            result = await handler(job)
            if not isinstance(result, HandlerResult):
                raise TypeError("handler must return HandlerResult")
            await self._stop_heartbeat(heartbeat_task, heartbeat_stop)
            await self._store_call(
                self._store.report_success,
                space_id=job.space_id,
                job_id=job.id,
                generation=job.lease_generation,
                events=result.events,
                domain_writes=result.domain_writes,
            )
        except asyncio.CancelledError:
            await self._stop_heartbeat(heartbeat_task, heartbeat_stop)
            # Drain timeout abandons this generation. P1 lease expiry is the only
            # recovery path; reporting cancellation would create a second transition.
            raise
        except Exception as error:
            await self._stop_heartbeat(heartbeat_task, heartbeat_stop)
            if started:
                await self._store_call(
                    self._store.report_failure,
                    space_id=claimed.space_id,
                    job_id=claimed.id,
                    generation=claimed.lease_generation,
                    failure=classify_failure(error),
                )
            else:
                self.last_transient_error = type(error).__name__

    def _discard_done(self) -> None:
        done = {task for task in self._tasks if task.done()}
        self._tasks.difference_update(done)
        for task in done:
            # Consume task exceptions so a single bad handler cannot kill the main loop.
            if not task.cancelled():
                task.exception()

    async def _wait_for_capacity(self) -> None:
        while (
            len(self._tasks) >= self._settings.worker_local_concurrency
            and self._lifecycle.state is ProcessState.SERVING
        ):
            await asyncio.wait(
                self._tasks,
                timeout=self._settings.claim_poll_interval_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            self._discard_done()

    async def _drain(self) -> None:
        self._discard_done()
        if not self._tasks:
            return
        loop = asyncio.get_running_loop()
        immediate = asyncio.Event()

        def wake_immediate() -> None:
            if not loop.is_closed():
                loop.call_soon_threadsafe(immediate.set)

        unsubscribe = self._lifecycle.subscribe_immediate_termination(wake_immediate)
        timeout = (
            0.0
            if self._lifecycle.immediate_termination_requested
            else self._settings.drain_deadline_seconds
        )
        pending = set(self._tasks)
        immediate_task = asyncio.create_task(immediate.wait())
        deadline = loop.time() + timeout
        try:
            while pending and not immediate.is_set():
                remaining = max(0.0, deadline - loop.time())
                if remaining == 0:
                    break
                done, _waiting = await asyncio.wait(
                    pending | {immediate_task},
                    timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done or immediate_task in done:
                    break
                pending.difference_update(done)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            self._discard_done()
        finally:
            unsubscribe()
            if not immediate_task.done():
                immediate_task.cancel()
                try:
                    await immediate_task
                except asyncio.CancelledError:
                    pass

    async def run(self) -> None:
        """Run until drain, retrying transient claim errors with configured backoff."""
        backoff_index = 0
        try:
            while self._lifecycle.state is ProcessState.SERVING:
                self._discard_done()
                await self._wait_for_capacity()
                if self._lifecycle.state is not ProcessState.SERVING:
                    break
                if not self._settings.worker_space_ids:
                    await self._sleep(self._settings.claim_poll_interval_seconds)
                    continue
                try:
                    outcome = await self._store_call(
                        self._store.claim,
                        space_ids=self._settings.worker_space_ids,
                        worker_id=self._worker_id,
                    )
                except Exception as error:
                    self.last_transient_error = type(error).__name__
                    delays = self._settings.transient_backoff_seconds
                    delay = delays[min(backoff_index, len(delays) - 1)]
                    backoff_index += 1
                    await self._sleep(delay)
                    continue
                backoff_index = 0
                if isinstance(outcome, NoClaimableJob):
                    await self._sleep(self._settings.claim_poll_interval_seconds)
                    continue
                if not isinstance(outcome, ClaimedJob):
                    self.last_transient_error = "invalid_claim_outcome"
                    await self._sleep(self._settings.claim_poll_interval_seconds)
                    continue
                self._tasks.add(asyncio.create_task(self.process_job(outcome.job)))
        finally:
            await self._drain()
            self._lifecycle.mark_terminated()
