"""Bounded outbox and keyset repair for platform product ingestion."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from insurance_harness.jobs import JobState, JobStore, OutboxDispatcher
from insurance_harness.jobs.errors import SpaceScopeError
from insurance_harness.jobs.models import ErrorClass, OutboxEventView
from insurance_harness.product_ingestion.models import ProductRunState, ProductScope
from insurance_harness.product_ingestion.progression import ProductProgression
from insurance_harness.product_ingestion.store import (
    ProductIngestionStore,
    needs_confirmation_error,
)
from insurance_harness.service_shell.health import Lifecycle, ProcessState
from insurance_harness.service_shell.worker import HandlerRegistry, HandlerResult

_PRODUCT_EVENTS = frozenset(
    {"product.stage.settled", "product.window.settled", "product.run.finished"}
)
_CONFIRMATION_PREFIX = "needs_confirmation:"
Sleeper = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RuntimeIssue:
    phase: str
    space_id: str
    run_id: str | None
    event_id: str | None
    error_type: str
    message: str


class ProductRuntimePump:
    """Advance product runs from owned events plus a rotating bounded repair scan."""

    def __init__(
        self,
        *,
        store: ProductIngestionStore,
        jobs: JobStore,
        outbox: OutboxDispatcher,
        progression: ProductProgression,
        scopes: Mapping[str, ProductScope],
        page_size: int = 50,
        event_limit: int = 100,
        poll_interval_seconds: float = 1.0,
        sleeper: Sleeper = asyncio.sleep,
    ) -> None:
        if not scopes or page_size < 1 or event_limit < 1 or poll_interval_seconds <= 0:
            raise ValueError("product runtime requires scopes and positive bounds")
        if any(key != scope.space_id for key, scope in scopes.items()):
            raise ValueError("product runtime scope keys must equal their space ids")
        self._store = store
        self._jobs = jobs
        self._outbox = outbox
        self._progression = progression
        self._scopes = dict(scopes)
        self._page_size = page_size
        self._event_limit = event_limit
        self._poll_interval_seconds = poll_interval_seconds
        self._sleep = sleeper
        self._cursors: dict[str, tuple[datetime, str] | None] = {
            space_id: None for space_id in scopes
        }
        self._issues: list[RuntimeIssue] = []

    @property
    def issues(self) -> tuple[RuntimeIssue, ...]:
        return tuple(self._issues)

    def _record(
        self,
        *,
        phase: str,
        space_id: str,
        error: Exception,
        run_id: str | None = None,
        event_id: str | None = None,
    ) -> None:
        self._issues.append(
            RuntimeIssue(
                phase=phase,
                space_id=space_id,
                run_id=run_id,
                event_id=event_id,
                error_type=type(error).__name__,
                message=str(error),
            )
        )
        del self._issues[:-100]

    async def _advance_event(
        self, scope: ProductScope, event: OutboxEventView
    ) -> None:
        run_id = event.payload.get("run_id")
        if type(run_id) is not str or not run_id:
            self._record(
                phase="event",
                space_id=scope.space_id,
                event_id=event.event_id,
                error=ValueError("product event run_id is invalid"),
            )
            return
        try:
            await asyncio.to_thread(self._progression.advance, scope, run_id)
            await asyncio.to_thread(
                self._outbox.mark_dispatched,
                space_id=scope.space_id,
                event_id=event.event_id,
            )
        except Exception as error:
            self._record(
                phase="event",
                space_id=scope.space_id,
                run_id=run_id,
                event_id=event.event_id,
                error=error,
            )

    async def _events(self, scope: ProductScope) -> None:
        try:
            events = await asyncio.to_thread(
                self._outbox.read_pending,
                space_id=scope.space_id,
                limit=self._event_limit,
            )
        except Exception as error:
            self._record(phase="event_read", space_id=scope.space_id, error=error)
            return
        for event in events:
            if event.event_type in _PRODUCT_EVENTS:
                await self._advance_event(scope, event)

    async def _repair(self, scope: ProductScope) -> None:
        cursor = self._cursors[scope.space_id]
        try:
            page = await asyncio.to_thread(
                self._store.scan_runs,
                scope=scope,
                after=cursor,
                limit=self._page_size,
            )
        except Exception as error:
            self._record(phase="scan_read", space_id=scope.space_id, error=error)
            return
        if not page:
            self._cursors[scope.space_id] = None
            return
        for run in page:
            # Advance the durable cursor even when this row is corrupt or blocked.
            self._cursors[scope.space_id] = (run.created_at, run.run_id)
            try:
                await asyncio.to_thread(self._progression.advance, scope, run.run_id)
            except Exception as error:
                self._record(
                    phase="scan",
                    space_id=scope.space_id,
                    run_id=run.run_id,
                    error=error,
                )

    async def tick(self) -> None:
        space_ids = tuple(self._scopes)
        try:
            await asyncio.to_thread(
                self._jobs.reclaim_expired_leases,
                space_ids=space_ids,
            )
        except Exception as error:
            self._record(phase="lease_reclaim", space_id="*", error=error)
        for scope in self._scopes.values():
            await self._events(scope)
            await self._repair(scope)

    async def run(self, lifecycle: Lifecycle) -> None:
        """Run beside WorkerLoop until the shared lifecycle begins draining."""
        while lifecycle.state is ProcessState.SERVING:
            try:
                await self.tick()
            except Exception as error:  # defensive boundary for process liveness
                self._record(phase="tick", space_id="*", error=error)
            if lifecycle.state is ProcessState.SERVING:
                await self._sleep(self._poll_interval_seconds)


def _confirmation_reason(
    *,
    store: ProductIngestionStore,
    jobs: JobStore,
    scope: ProductScope,
    run_id: str,
) -> str:
    for stage in store.list_stages(scope=scope, run_id=run_id):
        job = jobs.get_job(space_id=scope.space_id, job_id=stage.job_id)
        summary = job.error_summary or ""
        if (
            job.state is JobState.BLOCKED
            and job.error_class is ErrorClass.CAPACITY_BLOCKED
            and _CONFIRMATION_PREFIX in summary
        ):
            reason = summary.partition(_CONFIRMATION_PREFIX)[2]
            if reason.strip():
                return reason
    raise ValueError("needs_confirmation has no typed child reason")


def register_finalizer(
    registry: HandlerRegistry,
    *,
    store: ProductIngestionStore,
    jobs: JobStore,
    progression: ProductProgression,
    scopes: Mapping[str, ProductScope],
) -> None:
    """Register the short root barrier; WorkerLoop performs the sole transition."""
    if not scopes or any(key != scope.space_id for key, scope in scopes.items()):
        raise ValueError("product finalizer requires exact configured scopes")

    async def finalize(job) -> HandlerResult:
        scope = scopes.get(job.space_id)
        if scope is None:
            raise SpaceScopeError()
        run_id = job.payload.get("run_id")
        if type(run_id) is not str or not run_id:
            raise ValueError("product finalizer run_id is invalid")
        terminal = await asyncio.to_thread(progression.final_state, scope, run_id)
        if terminal is ProductRunState.NEEDS_CONFIRMATION:
            reason = await asyncio.to_thread(
                _confirmation_reason,
                store=store,
                jobs=jobs,
                scope=scope,
                run_id=run_id,
            )
            raise needs_confirmation_error(reason)
        return await asyncio.to_thread(
            store.prepare_run_finalization,
            scope=scope,
            run_id=run_id,
            job_id=job.id,
            generation=job.lease_generation,
            terminal_state=terminal,
        )

    registry.register("product_ingestion_root", finalize)
