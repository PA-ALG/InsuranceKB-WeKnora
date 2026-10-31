"""服务壳（039 T1/T4–T6）：生产组装、身份与范围校验、信号与关停时限。"""

from __future__ import annotations

import asyncio
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from insurance_harness.jobs import SpaceJobMetrics
from insurance_harness.service_shell import cli as shell_cli
from insurance_harness.service_shell.apps import (
    create_worker_probe_app,
)
from insurance_harness.service_shell.config import ShellConfigError, ShellSettings
from insurance_harness.service_shell.health import Lifecycle
from insurance_harness.service_shell.principal import (
    AuthenticationError,
)
from insurance_harness.service_shell.worker import HandlerRegistry
from tests.service_shell.apps.helpers import _health, _state_counts


def _settings(**overrides: Any) -> ShellSettings:
    values: dict[str, Any] = {
        "postgres_dsn": "postgresql+psycopg://wiki:secret@db/wiki",
        "principal_records_json": (
            '{"admin":{"kind":"human","subject_id":"admin-user",'
            '"bindings":{"space-a":["space_admin"]}}}'
        ),
        "principal_space_ids": ("space-a",),
        "worker_id": "worker-a",
        "worker_space_ids": ("space-a",),
    }
    values.update(overrides)
    return ShellSettings(**values)


def test_t4_production_api_composition_wires_auth_and_p1_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle, readiness = _health()
    session = object()

    class SessionContext:
        def __enter__(self) -> object:
            return session

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(
        shell_cli,
        "space_job_metrics",
        lambda actual, *, space_id: (
            SpaceJobMetrics(
                space_id=space_id,
                state_counts=_state_counts(queued=2),
                queue_depth=2,
                retry_wait_count=0,
                dead_letter_count=0,
                attempt_total=3,
                oldest_schedulable_age_seconds=1.0,
                expired_lease_count=0,
                oldest_expired_lease_age_seconds=None,
            )
            if actual is session
            else pytest.fail("wrong session")
        ),
    )
    monkeypatch.setattr(
        shell_cli,
        "global_job_metrics",
        lambda actual: pytest.fail("unexpected global read"),
    )

    app = shell_cli.build_api_app(
        settings=_settings(),
        lifecycle=lifecycle,
        readiness=readiness,
        session_factory=cast(Callable[[], Session], SessionContext),
    )
    response = TestClient(app).get(
        "/observations/spaces/space-a/jobs",
        headers={"Authorization": "Bearer admin"},
    )
    assert response.status_code == 200
    assert response.json()["queue_depth"] == 2


@pytest.mark.parametrize(
    ("credential", "principal_records_json"),
    [
        (
            "admin",
            '{"admin":{"kind":"human","subject_id":"admin-user",'
            '"bindings":{"space-unknown":["space_admin"]}}}',
        ),
        (
            "service",
            '{"service":{"kind":"service","service":"source_reader",'
            '"space_ids":["space-unknown"],'
            '"capabilities":["read_raw_knowledge"]}}',
        ),
    ],
)
def test_t1_production_api_rejects_principal_bound_to_unknown_space(
    credential: str,
    principal_records_json: str,
) -> None:
    lifecycle, readiness = _health()
    app = shell_cli.build_api_app(
        settings=_settings(
            principal_records_json=principal_records_json,
        ),
        lifecycle=lifecycle,
        readiness=readiness,
        session_factory=cast(Callable[[], Session], object()),
    )

    with pytest.raises(AuthenticationError, match="invalid_principal_binding"):
        app.state.principal_provider.authenticate(credential)


def test_t5_production_worker_composition_uses_p1_store_and_empty_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, object] = {}
    store = object()

    def fake_store(session_factory: object, config: object) -> object:
        created["session_factory"] = session_factory
        created["config"] = config
        return store

    class FakeLoop:
        def __init__(self, **kwargs: object) -> None:
            created.update(kwargs)

    monkeypatch.setattr(shell_cli, "JobStore", fake_store)
    monkeypatch.setattr(shell_cli, "WorkerLoop", FakeLoop)
    factory = cast(Callable[[], Session], object())
    lifecycle = Lifecycle()
    result = shell_cli.build_worker_loop(
        settings=_settings(),
        lifecycle=lifecycle,
        session_factory=factory,
    )
    assert isinstance(result, FakeLoop)
    assert created["store"] is store
    assert created["session_factory"] is factory
    assert created["worker_id"] == "worker-a"
    registry = created["registry"]
    assert isinstance(registry, HandlerRegistry)
    assert registry.handlers == {}


def test_t5_worker_composition_requires_explicit_identity_and_scope() -> None:
    with pytest.raises(ShellConfigError) as caught:
        shell_cli.build_worker_loop(
            settings=_settings(worker_id=None, worker_space_ids=()),
            lifecycle=Lifecycle(),
            session_factory=cast(Callable[[], Session], object()),
        )
    assert caught.value.keys == ("worker_id", "worker_space_ids")


def test_t6_uvicorn_signal_enters_shared_drain_and_repeated_signal_escalates() -> None:
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    app_lifecycle, readiness = _health()
    server = shell_cli.LifecycleServer(
        uvicorn.Config(
            create_worker_probe_app(
                lifecycle=app_lifecycle,
                readiness=readiness,
            )
        ),
        lifecycle=lifecycle,
    )
    server.handle_exit(signal.SIGTERM, None)
    assert lifecycle.state.value == "draining"
    assert lifecycle.immediate_termination_requested is False
    server.handle_exit(signal.SIGTERM, None)
    assert lifecycle.immediate_termination_requested is True


async def test_t6_server_completion_does_not_double_count_the_first_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CountingLifecycle(Lifecycle):
        def __init__(self) -> None:
            super().__init__()
            self.drain_calls = 0

        def begin_drain(self) -> bool:
            self.drain_calls += 1
            return super().begin_drain()

    lifecycle = CountingLifecycle()
    _probe_lifecycle, readiness = _health()

    class FakeWorker:
        async def run(self) -> None:
            while lifecycle.state.value == "serving":
                await asyncio.sleep(0)
            await asyncio.sleep(0.01)

    class FakeServer:
        should_exit = False

        async def serve(self) -> None:
            assert lifecycle.begin_drain() is True

    monkeypatch.setattr(shell_cli, "build_worker_loop", lambda **_kwargs: FakeWorker())
    monkeypatch.setattr(shell_cli, "_server", lambda *_args, **_kwargs: FakeServer())
    await shell_cli._serve_worker(
        settings=_settings(),
        lifecycle=lifecycle,
        readiness=readiness,
        session_factory=cast(Callable[[], Session], object()),
    )
    assert lifecycle.drain_calls == 1
    assert lifecycle.immediate_termination_requested is False


async def test_t6_worker_total_shutdown_timeout_caps_composed_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = Lifecycle()
    _probe_lifecycle, readiness = _health()

    class FakeWorker:
        async def run(self) -> None:
            await asyncio.Event().wait()

    class FakeServer:
        should_exit = False

        async def serve(self) -> None:
            lifecycle.begin_drain()
            await asyncio.Event().wait()

    monkeypatch.setattr(shell_cli, "build_worker_loop", lambda **_kwargs: FakeWorker())
    monkeypatch.setattr(shell_cli, "_server", lambda *_args, **_kwargs: FakeServer())

    await asyncio.wait_for(
        shell_cli._serve_worker(
            settings=_settings(
                drain_deadline_seconds=0.01,
                total_shutdown_timeout_seconds=0.02,
            ),
            lifecycle=lifecycle,
            readiness=readiness,
            session_factory=cast(Callable[[], Session], object()),
        ),
        timeout=0.08,
    )
    assert lifecycle.state.value == "terminated"


def test_worker_entrypoint_emits_success_heartbeat_without_test_log_override(
    tmp_path: Path,
) -> None:
    code = """
import logging
import uvicorn
from fastapi import FastAPI
from insurance_harness.service_shell import cli
cli._load_or_exit = lambda: object()
cli._runtime_dependencies = lambda settings: (None, None, None)
async def serve(**kwargs):
    uvicorn.Config(FastAPI())
    logging.getLogger("insurance_harness.service_shell.worker").info("heartbeat-startup-visible")
cli._serve_worker = serve
cli.worker_main()
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=15, check=True
    )
    assert "heartbeat-startup-visible" in result.stderr
