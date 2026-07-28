from __future__ import annotations

import asyncio
import signal
import subprocess
import sys
import tomllib
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from insurance_harness.jobs import GlobalJobMetrics, JobState, SpaceJobMetrics
from insurance_harness.service_shell import cli as shell_cli
from insurance_harness.service_shell.apps import (
    ObservationQueries,
    create_api_app,
    create_worker_probe_app,
)
from insurance_harness.service_shell.config import ShellConfigError, ShellSettings
from insurance_harness.service_shell.health import Lifecycle, ReadinessChecker
from insurance_harness.service_shell.principal import StaticPrincipalProvider
from insurance_harness.service_shell.worker import HandlerRegistry

HARNESS_ROOT = Path(__file__).resolve().parents[1]


def _health() -> tuple[Lifecycle, ReadinessChecker]:
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    checker = ReadinessChecker(
        lifecycle=lifecycle,
        probe=lambda: None,
        timeout_seconds=0.1,
        freshness_seconds=1,
    )
    return lifecycle, checker


def _paths(app: FastAPI) -> set[str]:
    return {
        path
        for route in app.routes
        if (path := getattr(route, "path", None)) is not None
    }


def test_t4_same_wheel_registers_exact_api_and_worker_scripts() -> None:
    data = tomllib.loads((HARNESS_ROOT / "pyproject.toml").read_text())
    assert data["project"]["scripts"] == {
        "wiki-api": "insurance_harness.service_shell.cli:api_main",
        "wiki-worker": "insurance_harness.service_shell.cli:worker_main",
    }


def test_t4_installed_wheel_carries_readiness_metadata_for_both_roles(
    tmp_path: Path,
) -> None:
    dist_dir = tmp_path / "dist"
    subprocess.run(
        [
            "uv",
            "build",
            "--wheel",
            "--out-dir",
            str(dist_dir),
            "--cache-dir",
            str(tmp_path / "uv-cache"),
        ],
        cwd=HARNESS_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel_path = next(dist_dir.glob("insurance_harness-*.whl"))
    installed = tmp_path / "installed"
    with zipfile.ZipFile(wheel_path) as wheel:
        wheel.extractall(installed)
    smoke = f"""
import sys
from importlib.metadata import distributions
from pathlib import Path

sys.path.insert(0, {str(installed)!r})
import insurance_harness
from insurance_harness.service_shell.cli import (
    _runtime_dependencies,
    build_api_app,
    build_worker_loop,
)
from insurance_harness.service_shell.config import ShellSettings
from insurance_harness.service_shell.health import packaged_alembic_head

package_path = Path(insurance_harness.__file__).resolve()
assert package_path.is_relative_to(Path({str(installed)!r}).resolve())
distribution = next(
    item
    for item in distributions(path=[{str(installed)!r}])
    if item.metadata["Name"] == "insurance-harness"
)
scripts = {{item.name: item.value for item in distribution.entry_points}}
assert scripts["wiki-api"] == "insurance_harness.service_shell.cli:api_main"
assert scripts["wiki-worker"] == "insurance_harness.service_shell.cli:worker_main"
assert packaged_alembic_head()
settings = ShellSettings(
    postgres_dsn="postgresql+psycopg://wiki:secret@db/wiki",
    principal_records_json="{{}}",
    worker_id="worker-a",
    worker_space_ids=("space-a",),
)
lifecycle, readiness, factory = _runtime_dependencies(settings)
build_api_app(
    settings=settings,
    lifecycle=lifecycle,
    readiness=readiness,
    session_factory=factory,
)
build_worker_loop(
    settings=settings,
    lifecycle=lifecycle,
    session_factory=factory,
)
"""
    subprocess.run(
        [sys.executable, "-c", smoke],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )


def test_t4_app_factories_are_repeatable_and_roles_are_mutually_exclusive() -> None:
    api_lifecycle, api_readiness = _health()
    worker_lifecycle, worker_readiness = _health()
    first_api = create_api_app(
        lifecycle=api_lifecycle,
        readiness=api_readiness,
    )
    second_api = create_api_app(
        lifecycle=api_lifecycle,
        readiness=api_readiness,
    )
    worker = create_worker_probe_app(
        lifecycle=worker_lifecycle,
        readiness=worker_readiness,
    )

    assert first_api is not second_api
    assert first_api.state.role == "api"
    assert second_api.state.role == "api"
    assert worker.state.role == "worker"
    assert not hasattr(first_api.state, "worker_loop")
    assert _paths(worker) == {"/livez", "/readyz"}
    assert {"/livez", "/readyz"} <= _paths(first_api)


def test_t4_probe_http_statuses_track_truthful_health() -> None:
    lifecycle, readiness = _health()
    api = create_api_app(lifecycle=lifecycle, readiness=readiness)
    client = TestClient(api)
    assert client.get("/livez").status_code == 200
    assert client.get("/readyz").status_code == 200

    lifecycle.begin_drain()
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["reason"] == "draining"


def _provider() -> StaticPrincipalProvider:
    return StaticPrincipalProvider(
        {
            "admin": {
                "kind": "human",
                "subject_id": "admin-user",
                "bindings": {"space-a": ["space_admin"]},
            },
            "other-admin": {
                "kind": "human",
                "subject_id": "other-user",
                "bindings": {"space-b": ["space_admin"]},
            },
            "viewer": {
                "kind": "human",
                "subject_id": "viewer-user",
                "bindings": {"space-a": ["viewer"]},
            },
            "super": {
                "kind": "human",
                "subject_id": "super-user",
                "bindings": {"*": ["super_admin"]},
            },
            "service": {
                "kind": "service",
                "service": "source_reader",
                "space_ids": ["space-a"],
                "capabilities": ["read_raw_knowledge"],
            },
        }
    )


def _state_counts(**overrides: int) -> dict[JobState, int]:
    counts = {state: 0 for state in JobState}
    for name, value in overrides.items():
        counts[JobState(name)] = value
    return counts


def _observed_app() -> tuple[FastAPI, list[str]]:
    lifecycle, readiness = _health()
    calls: list[str] = []

    def read_space(space_id: str) -> SpaceJobMetrics:
        calls.append(f"space:{space_id}")
        return SpaceJobMetrics(
            space_id=space_id,
            state_counts=_state_counts(queued=3, retry_wait=1, dead_letter=2),
            queue_depth=3,
            retry_wait_count=1,
            dead_letter_count=2,
            attempt_total=7,
            oldest_schedulable_age_seconds=12.5,
            expired_lease_count=1,
            oldest_expired_lease_age_seconds=4.5,
        )

    def read_global() -> GlobalJobMetrics:
        calls.append("global")
        return GlobalJobMetrics(
            state_counts=_state_counts(queued=4, retry_wait=1, dead_letter=2),
            queue_depth=4,
            retry_wait_count=1,
            dead_letter_count=2,
            attempt_total=8,
            oldest_schedulable_age_seconds=15.0,
            expired_lease_count=1,
            oldest_expired_lease_age_seconds=5.0,
        )

    return (
        create_api_app(
            lifecycle=lifecycle,
            readiness=readiness,
            principal_provider=_provider(),
            observations=ObservationQueries(
                read_space=read_space,
                read_global=read_global,
            ),
        ),
        calls,
    )


def test_t7_space_observation_requires_admin_binding_and_maps_p1_metrics() -> None:
    app, calls = _observed_app()
    client = TestClient(app)
    response = client.get(
        "/observations/spaces/space-a/jobs",
        headers={"Authorization": "Bearer admin"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "space_id": "space-a",
        "state_counts": {
            "queued": 3,
            "leased": 0,
            "running": 0,
            "succeeded": 0,
            "retry_wait": 1,
            "awaiting_human": 0,
            "blocked": 0,
            "dead_letter": 2,
        },
        "queue_depth": 3,
        "retry_wait_count": 1,
        "dead_letter_count": 2,
        "attempt_total": 7,
        "oldest_schedulable_age_seconds": 12.5,
        "expired_lease_count": 1,
        "oldest_expired_lease_age_seconds": 4.5,
    }
    assert calls == ["space:space-a"]
    assert "payload" not in response.text
    assert "secret" not in response.text


def test_t7_space_observation_authorization_matrix_fails_before_query() -> None:
    app, calls = _observed_app()
    client = TestClient(app)
    attempts = [
        ({}, 401),
        ({"Authorization": "Bearer viewer"}, 403),
        ({"Authorization": "Bearer service"}, 403),
        ({"Authorization": "Bearer other-admin"}, 403),
        ({"Authorization": "Bearer unknown"}, 401),
    ]
    for headers, expected_status in attempts:
        response = client.get("/observations/spaces/space-a/jobs", headers=headers)
        assert response.status_code == expected_status
        assert set(response.json()) == {"error"}
    assert calls == []


def test_t7_global_observation_is_an_explicit_super_admin_only_route() -> None:
    app, calls = _observed_app()
    client = TestClient(app)
    for credential in ("admin", "viewer", "service"):
        response = client.get(
            "/observations/jobs",
            headers={"Authorization": f"Bearer {credential}"},
        )
        assert response.status_code == 403
        assert set(response.json()) == {"error"}
    assert calls == []

    response = client.get(
        "/observations/jobs",
        headers={"Authorization": "Bearer super"},
    )
    assert response.status_code == 200
    assert response.json()["queue_depth"] == 4
    assert "space_id" not in response.json()
    assert calls == ["global"]


def test_t7_draining_refuses_new_observation_before_handler() -> None:
    app, calls = _observed_app()
    app.state.lifecycle.begin_drain()
    response = TestClient(app).get(
        "/observations/spaces/space-a/jobs",
        headers={"Authorization": "Bearer admin"},
    )
    assert response.status_code == 503
    assert response.json() == {"error": "draining"}
    assert calls == []


def _settings(**overrides: Any) -> ShellSettings:
    values: dict[str, Any] = {
        "postgres_dsn": "postgresql+psycopg://wiki:secret@db/wiki",
        "principal_records_json": (
            '{"admin":{"kind":"human","subject_id":"admin-user",'
            '"bindings":{"space-a":["space_admin"]}}}'
        ),
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
        lambda actual, *, space_id: SpaceJobMetrics(
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
        else pytest.fail("wrong session"),
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
