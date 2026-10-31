"""App build contracts (OpenSpec 127 / BA0-REQ-01..06): shared paths, constants and runners.

The production modules are loaded lazily so pytest still collects every contract and reports a
precise "planned implementation missing" assertion instead of an import/collection error. Git,
Go and Docker are represented by injected runners; repository manifests, Dockerfiles, Makefile
recipes and Compose topology remain real file contracts.

Wished-for public API frozen by these contracts:

``scripts/app_artifact.py``
    ArtifactContractError
    load_manifest(path)
    load_dependency_lock(path)
    resolve_inputs(repo_root, manifest, *, runner)
    canonical_identity(...)
    build_metadata(...)
    select_or_build_app(...)
    _dependency_plan(lock)  # private Dockerfile lock-consumption seam

``scripts/start_exact_image.py``
    ArtifactSmokeError
    run_exact_image_smoke(...)
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

REPO_ROOT = Path(__file__).resolve().parents[4]
APP_ARTIFACT_PATH = REPO_ROOT / "scripts/app_artifact.py"
START_EXACT_IMAGE_PATH = REPO_ROOT / "scripts/start_exact_image.py"
MANIFEST_PATH = REPO_ROOT / "deploy/local-build/app-build-inputs.v1.json"
DEPENDENCY_LOCK_PATH = REPO_ROOT / "deploy/local-build/app-external-dependencies.v1.json"
EXACT_COMPOSE_PATH = REPO_ROOT / "deploy/local-build/docker-compose.app-exact.yml"
DOCKERFILE_PATH = REPO_ROOT / "docker/Dockerfile.app"

CONTEXT = "colima-g1-build"
PLATFORM = "linux/arm64"
BUILD_SOURCE_HEAD = "b" * 40
INTEGRATION_HEAD = "c" * 40
SOURCE_DATE_EPOCH = 1_700_000_000
IMAGE_ID = "sha256:" + "d" * 64
ARTIFACT_IDENTITY = "sha256:" + "a" * 64
MANIFEST_SHA256 = "1" * 64
LOCK_SHA256 = "2" * 64
CANARY_SECRET = "BA0-CANARY-SECRET-9b665589-do-not-disclose"
CANARY_SECRET_B = "BA0-CANARY-SECRET-B-4ce14a48-do-not-disclose"
D3_NONCE = "0123456789abcdef"
D3_PROJECT = f"insurancekb-ba0-d3-{D3_NONCE}"
D3_CONTAINER = f"{D3_PROJECT}-app-smoke-1"

REQUIRED_CRITICAL_INPUTS = {
    "cmd/server/main.go",
    "cmd/server/bootstrap.go",
    "cmd/server/listen.go",
    "cmd/server/signals_unix.go",
    "cmd/download/duckdb/duckdb.go",
    "docs/docs.go",
    "docs/swagger.json",
    "docs/swagger.yaml",
    "docreader/client/auth.go",
    "docreader/client/client.go",
    "docreader/proto/docreader.pb.go",
    "docreader/proto/docreader_grpc.pb.go",
    "deploy/upstream/adoption_target.go",
    "deploy/upstream/weknora-adoption-target.json",
    "deploy/upstream/weknora-plugin-contract.yaml",
    "internal/assets/embed.go",
    "internal/assets/asr_test.wav",
    "internal/config/config.go",
    "internal/container/container.go",
    "internal/logger/logger.go",
    "internal/router/router.go",
    "internal/runtime/server.go",
    "internal/types/interfaces/user.go",
}

REQUIRED_COPY_ROOTS = {
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "config",
    "licenses",
    "scripts",
    "migrations",
    "dataset/samples",
    "third_party/anydoc-go",
}

REQUIRED_LABELS = {
    "io.insurancekb.app.artifact-identity": ARTIFACT_IDENTITY,
    "io.insurancekb.app.build-source-head": BUILD_SOURCE_HEAD,
    "io.insurancekb.app.manifest-sha256": MANIFEST_SHA256,
    "io.insurancekb.app.dependency-lock-sha256": LOCK_SHA256,
    "io.insurancekb.app.target": "runtime",
    "io.insurancekb.app.platform": PLATFORM,
}


class Runner(Protocol):
    def __call__(
        self,
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        capture_output: bool = True,
        text: bool = True,
        env: Mapping[str, str] | None = None,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True)
class RecordedCall:
    arguments: tuple[str, ...]
    cwd: Path
    kwargs: Mapping[str, object]


class FakeRunner:
    """Auditable process boundary used by selector and D3 contract tests."""

    def __init__(
        self,
        responder: Callable[
            [tuple[str, ...], Path, Mapping[str, object], int],
            subprocess.CompletedProcess[str],
        ],
    ) -> None:
        self._responder = responder
        self.calls: list[RecordedCall] = []

    def __call__(
        self,
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        capture_output: bool = True,
        text: bool = True,
        env: Mapping[str, str] | None = None,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        assert isinstance(arguments, tuple), "runner argv must be an immutable tuple"
        call_kwargs: dict[str, object] = {
            "capture_output": capture_output,
            "text": text,
            **kwargs,
        }
        if env is not None:
            call_kwargs["env"] = dict(env)
        self.calls.append(RecordedCall(arguments, Path(cwd), call_kwargs))
        return self._responder(arguments, Path(cwd), call_kwargs, len(self.calls) - 1)


def _completed(
    arguments: tuple[str, ...],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(arguments, returncode, stdout, stderr)


def _load_planned_module(path: Path, name: str) -> ModuleType:
    assert path.is_file(), f"planned BA0 implementation missing: {path.relative_to(REPO_ROOT)}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load planned module: {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _artifact_module() -> ModuleType:
    return _load_planned_module(APP_ARTIFACT_PATH, "app_artifact_830_ba0")


def _smoke_module() -> ModuleType:
    return _load_planned_module(START_EXACT_IMAGE_PATH, "start_exact_image_830_ba0")


def _load_json(path: Path, *, description: str) -> dict[str, Any]:
    assert path.is_file(), f"planned BA0 {description} missing: {path.relative_to(REPO_ROOT)}"
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{description} must be a JSON object"
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_text(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _dockerfile_instructions(source: str) -> list[str]:
    instructions: list[str] = []
    current = ""
    for raw_line in source.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        current = f"{current} {stripped}".strip()
        if current.endswith("\\"):
            current = current[:-1].rstrip()
            continue
        instructions.append(current)
        current = ""
    assert not current, "unterminated Dockerfile instruction"
    return instructions


def _executable_text(source: str) -> str:
    return "\n".join(
        line.split("#", 1)[0].rstrip()
        for line in source.splitlines()
        if line.split("#", 1)[0].strip()
    )
