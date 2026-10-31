"""服务壳（039 T4）：同一 wheel 的两个入口、就绪元数据、应用工厂与探针状态码。"""

from __future__ import annotations

import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from insurance_harness.service_shell.apps import (
    create_api_app,
    create_worker_probe_app,
)
from tests.service_shell.apps.helpers import _health

HARNESS_ROOT = Path(__file__).resolve().parents[3]


def _paths(app: FastAPI) -> set[str]:
    return {path for route in app.routes if (path := getattr(route, "path", None)) is not None}


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
