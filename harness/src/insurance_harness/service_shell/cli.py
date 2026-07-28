"""Explicit console entry points; the invoked script fixes the process role."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from math import ceil
from types import FrameType

import uvicorn
from fastapi import FastAPI
from sqlalchemy.orm import Session

from insurance_harness.db.base import make_engine, make_session_factory
from insurance_harness.jobs import (
    GlobalJobMetrics,
    JobStore,
    SpaceJobMetrics,
    global_job_metrics,
    space_job_metrics,
)
from insurance_harness.service_shell.apps import (
    ObservationQueries,
    create_worker_probe_app,
)
from insurance_harness.service_shell.apps import (
    create_api_app as create_api_surface,
)
from insurance_harness.service_shell.config import ShellConfigError, ShellSettings, load_settings
from insurance_harness.service_shell.health import (
    Lifecycle,
    ProcessState,
    ReadinessChecker,
    database_readiness_probe,
)
from insurance_harness.service_shell.principal import StaticPrincipalProvider
from insurance_harness.service_shell.worker import HandlerRegistry, WorkerLoop

SessionFactory = Callable[[], Session]


class LifecycleServer(uvicorn.Server):
    """Bind Uvicorn's real signal path to the shared fail-closed lifecycle."""

    def __init__(self, config: uvicorn.Config, *, lifecycle: Lifecycle) -> None:
        super().__init__(config)
        self._lifecycle = lifecycle

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        self._lifecycle.begin_drain()
        super().handle_exit(sig, frame)


def _load_or_exit() -> ShellSettings:
    try:
        return load_settings()
    except ShellConfigError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error


def _runtime_dependencies(
    settings: ShellSettings,
) -> tuple[Lifecycle, ReadinessChecker, SessionFactory]:
    engine = make_engine(settings.postgres_dsn.get_secret_value())
    factory = make_session_factory(engine)
    lifecycle = Lifecycle()
    checker = ReadinessChecker(
        lifecycle=lifecycle,
        probe=database_readiness_probe(factory),
        timeout_seconds=settings.readiness_timeout_seconds,
        freshness_seconds=settings.readiness_freshness_seconds,
    )
    return lifecycle, checker, factory


def build_api_app(
    *,
    settings: ShellSettings,
    lifecycle: Lifecycle,
    readiness: ReadinessChecker,
    session_factory: SessionFactory,
) -> FastAPI:
    """Compose the production API from current principal bindings and P1.9 reads."""

    def read_space(space_id: str) -> SpaceJobMetrics:
        with session_factory() as session:
            return space_job_metrics(session, space_id=space_id)

    def read_global() -> GlobalJobMetrics:
        with session_factory() as session:
            return global_job_metrics(session)

    return create_api_surface(
        lifecycle=lifecycle,
        readiness=readiness,
        principal_provider=StaticPrincipalProvider(settings.principal_records()),
        observations=ObservationQueries(
            read_space=read_space,
            read_global=read_global,
        ),
    )


def build_worker_loop(
    *,
    settings: ShellSettings,
    lifecycle: Lifecycle,
    session_factory: SessionFactory,
) -> WorkerLoop:
    """Compose the production Worker with P1 as its only durable write surface."""
    missing = tuple(
        key
        for key, missing_value in (
            ("worker_id", settings.worker_id is None),
            ("worker_space_ids", not settings.worker_space_ids),
        )
        if missing_value
    )
    if missing:
        raise ShellConfigError(missing)
    assert settings.worker_id is not None
    store = JobStore(session_factory, settings.job_runtime_config())
    return WorkerLoop(
        store=store,
        registry=HandlerRegistry(),
        settings=settings,
        lifecycle=lifecycle,
        worker_id=settings.worker_id,
    )


def _server(
    app: FastAPI,
    *,
    lifecycle: Lifecycle,
    host: str,
    port: int,
    shutdown_timeout: float,
) -> LifecycleServer:
    return LifecycleServer(
        uvicorn.Config(
            app,
            host=host,
            port=port,
            timeout_graceful_shutdown=max(1, ceil(shutdown_timeout)),
        ),
        lifecycle=lifecycle,
    )


def api_main() -> None:
    """Run only the API role selected by the `wiki-api` script."""
    settings = _load_or_exit()
    lifecycle, readiness, factory = _runtime_dependencies(settings)
    app = build_api_app(
        settings=settings,
        lifecycle=lifecycle,
        readiness=readiness,
        session_factory=factory,
    )
    server = _server(
        app,
        lifecycle=lifecycle,
        host=settings.api_host,
        port=settings.api_port,
        shutdown_timeout=settings.drain_deadline_seconds,
    )
    lifecycle.mark_serving()
    try:
        server.run()
    finally:
        if lifecycle.state is not ProcessState.TERMINATED:
            lifecycle.mark_terminated()


async def _serve_worker(
    *,
    settings: ShellSettings,
    lifecycle: Lifecycle,
    readiness: ReadinessChecker,
    session_factory: SessionFactory,
) -> None:
    worker = build_worker_loop(
        settings=settings,
        lifecycle=lifecycle,
        session_factory=session_factory,
    )
    server = _server(
        create_worker_probe_app(lifecycle=lifecycle, readiness=readiness),
        lifecycle=lifecycle,
        host=settings.worker_probe_host,
        port=settings.worker_probe_port,
        shutdown_timeout=settings.total_shutdown_timeout_seconds,
    )
    lifecycle.mark_serving()
    worker_task = asyncio.create_task(worker.run())
    server_task = asyncio.create_task(server.serve())
    done, _pending = await asyncio.wait(
        {worker_task, server_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if server_task in done and lifecycle.state is ProcessState.SERVING:
        lifecycle.begin_drain()
    if worker_task in done:
        server.should_exit = True
    await asyncio.gather(worker_task, server_task)


def worker_main() -> None:
    """Run only the Worker role selected by the `wiki-worker` script."""
    settings = _load_or_exit()
    lifecycle, readiness, factory = _runtime_dependencies(settings)
    try:
        asyncio.run(
            _serve_worker(
                settings=settings,
                lifecycle=lifecycle,
                readiness=readiness,
                session_factory=factory,
            )
        )
    except ShellConfigError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error
