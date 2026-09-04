"""Focused RED contracts for OpenSpec 127 / BA0-REQ-01..06.

The production modules intentionally do not exist at the Task 2 baseline.  Tests
load them lazily so pytest still collects every contract and reports a precise
"planned implementation missing" assertion instead of an import/collection
error.  Git, Go, and Docker are represented by injected runners; repository
manifests, Dockerfiles, Makefile recipes, and Compose topology remain real file
contracts.

Wished-for public API frozen here:

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
import re
import shlex
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ARTIFACT_PATH = REPO_ROOT / "scripts/app_artifact.py"
START_EXACT_IMAGE_PATH = REPO_ROOT / "scripts/start_exact_image.py"
MANIFEST_PATH = REPO_ROOT / "deploy/local-build/app-build-inputs.v1.json"
DEPENDENCY_LOCK_PATH = (
    REPO_ROOT / "deploy/local-build/app-external-dependencies.v1.json"
)
EXACT_COMPOSE_PATH = REPO_ROOT / "deploy/local-build/docker-compose.app-exact.yml"
DOCKERFILE_PATH = REPO_ROOT / "docker/Dockerfile.app"
MAKEFILE_PATH = REPO_ROOT / "Makefile"
BUILD_IMAGES_PATH = REPO_ROOT / "scripts/build_images.sh"
GET_VERSION_PATH = REPO_ROOT / "scripts/get_version.sh"

CONTEXT = "colima-g1-build"
PLATFORM = "linux/arm64"
APP_REPOSITORY = "wechatopenai/weknora-app"
BUILD_SOURCE_HEAD = "b" * 40
INTEGRATION_HEAD = "c" * 40
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
    "config",
    "scripts",
    "migrations",
    "dataset/samples",
    "skills/preloaded",
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


def _duckdb_version_from_go_mod(repo_root: Path) -> str:
    source = (repo_root / "go.mod").read_text(encoding="utf-8")
    match = re.search(
        r"github\.com/duckdb/duckdb-go/v2\s+v2\.([0-9])([0-9]{2})([0-9]{2})\.[0-9]+",
        source,
    )
    assert match is not None, "go.mod must pin the DuckDB binding version"
    major, minor, patch = (int(value) for value in match.groups())
    return f"v{major}.{minor}.{patch}"


def _json_text(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _record_value(record: object, name: str) -> Any:
    if isinstance(record, Mapping):
        return record[name]
    return getattr(record, name)


def _resolved_paths(records: object) -> set[str]:
    assert not isinstance(records, (str, bytes, Mapping))
    paths: set[str] = set()
    for record in records:  # type: ignore[union-attr]
        value = record if isinstance(record, str) else _record_value(record, "path")
        paths.add(Path(str(value)).as_posix().removeprefix("./"))
    return paths


def _go_list_stream(repo_root: Path, *, incomplete: bool = False) -> str:
    module_path = "github.com/Tencent/WeKnora"

    def local_package(
        directory: str,
        go_files: list[str],
        imports: list[str],
        *,
        embed_files: list[str] | None = None,
        ignored_go_files: list[str] | None = None,
    ) -> dict[str, Any]:
        package = {
            "Dir": str(repo_root / directory),
            "ImportPath": f"{module_path}/{directory}",
            "Name": "main" if directory.startswith("cmd/") else Path(directory).name,
            "Root": str(repo_root),
            "Module": {"Path": module_path, "Dir": str(repo_root), "Main": True},
            "GoFiles": go_files,
            "Imports": imports,
            "Deps": [],
        }
        if embed_files:
            package["EmbedFiles"] = embed_files
        if ignored_go_files:
            package["IgnoredGoFiles"] = ignored_go_files
        return package

    packages = [
        {
            "Dir": "/usr/local/go/src/context",
            "ImportPath": "context",
            "Name": "context",
            "Standard": True,
            "Goroot": True,
            "GoFiles": ["context.go"],
        },
        {
            "Dir": "/go/pkg/mod/github.com/gin-gonic/gin@v1.10.0",
            "ImportPath": "github.com/gin-gonic/gin",
            "Name": "gin",
            "Module": {
                "Path": "github.com/gin-gonic/gin",
                "Dir": "/go/pkg/mod/github.com/gin-gonic/gin@v1.10.0",
            },
            "GoFiles": ["gin.go"],
        },
        local_package(
            "internal/config",
            ["config.go"],
            ["context"],
        ),
        local_package(
            "internal/logger",
            ["logger.go"],
            ["context"],
        ),
        local_package(
            "internal/runtime",
            ["server.go"],
            ["context", f"{module_path}/internal/logger"],
        ),
        local_package(
            "internal/types/interfaces",
            ["user.go"],
            ["context"],
        ),
        local_package(
            "docs",
            ["docs.go"],
            ["github.com/swaggo/swag"],
        ),
        local_package(
            "docreader/proto",
            ["docreader.pb.go", "docreader_grpc.pb.go"],
            ["google.golang.org/grpc"],
        ),
        local_package(
            "docreader/client",
            ["auth.go", "client.go"],
            [f"{module_path}/docreader/proto", "google.golang.org/grpc"],
        ),
        local_package(
            "deploy/upstream",
            ["adoption_target.go"],
            ["embed", "encoding/json"],
            embed_files=["weknora-adoption-target.json"],
        ),
        local_package(
            "internal/assets",
            ["embed.go"],
            ["embed"],
            embed_files=["asr_test.wav"],
        ),
        local_package(
            "internal/router",
            ["router.go"],
            [
                f"{module_path}/deploy/upstream",
                f"{module_path}/docreader/client",
                f"{module_path}/docs",
                f"{module_path}/internal/assets",
            ],
        ),
        local_package(
            "internal/container",
            ["container.go"],
            [f"{module_path}/internal/router"],
        ),
        local_package(
            "cmd/download/duckdb",
            ["duckdb.go"],
            ["context", "github.com/duckdb/duckdb-go/v2"],
        ),
    ]
    sentinel = repo_root / "internal/newtopsentinel/sentinel.go"
    server_imports = [
        "context",
        "github.com/gin-gonic/gin",
        f"{module_path}/internal/config",
        f"{module_path}/internal/container",
        f"{module_path}/internal/logger",
        f"{module_path}/internal/runtime",
        f"{module_path}/internal/types/interfaces",
    ]
    if sentinel.is_file():
        server_imports.append(f"{module_path}/internal/newtopsentinel")
        packages.append(
            local_package("internal/newtopsentinel", ["sentinel.go"], ["context"])
        )
    packages.append(
        local_package(
            "cmd/server",
            ["main.go", "bootstrap.go", "listen.go", "signals_unix.go"],
            server_imports,
            ignored_go_files=["signals_windows.go"],
        )
    )
    if incomplete:
        packages[-1]["Incomplete"] = True
        packages[-1]["DepsErrors"] = [
            {
                "ImportStack": [f"{module_path}/cmd/server"],
                "Pos": "cmd/server/main.go:1:1",
                "Err": f"no required module provides {module_path}/internal/unresolved",
            }
        ]
    return "".join(json.dumps(package) + "\n" for package in packages)


def _identity_runner(
    repo_root: Path,
    *,
    drift: bool = False,
    go_list_failure: str | None = None,
    source_head: str = BUILD_SOURCE_HEAD,
    source_epoch: int = 1_700_000_000,
) -> FakeRunner:
    def respond(
        arguments: tuple[str, ...],
        cwd: Path,
        kwargs: Mapping[str, object],
        index: int,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, kwargs, index
        assert arguments and arguments[0] != "docker", (
            "identity/preflight must not invoke Docker"
        )
        if arguments[0] == "go" and "list" in arguments:
            if go_list_failure == "command":
                return _completed(
                    arguments,
                    returncode=1,
                    stderr="unresolved import github.com/Tencent/WeKnora/internal/unresolved",
                )
            return _completed(
                arguments,
                stdout=_go_list_stream(
                    repo_root,
                    incomplete=go_list_failure == "deps-error",
                ),
            )
        if arguments[0] == "git":
            if "diff" in arguments:
                return _completed(
                    arguments,
                    returncode=1 if drift else 0,
                    stderr="manifest input drift" if drift else "",
                )
            if any("%ct" in argument for argument in arguments):
                return _completed(arguments, stdout=f"{source_epoch}\n")
            if any("VERSION" in argument for argument in arguments):
                return _completed(arguments, stdout="v1.2.3\n")
            if "rev-parse" in arguments:
                return _completed(arguments, stdout=source_head + "\n")
            return _completed(arguments)
        return _completed(arguments)

    return FakeRunner(respond)


def _write_synthetic_contract(repo_root: Path) -> tuple[Path, Path]:
    manifest_path = repo_root / "deploy/local-build/app-build-inputs.v1.json"
    lock_path = repo_root / "deploy/local-build/app-external-dependencies.v1.json"
    manifest_path.parent.mkdir(parents=True)

    manifest = {
        "schema_version": 1,
        "artifact": "weknora-app",
        "context": ".",
        "dockerfile": "docker/Dockerfile.app",
        "dockerignore": ".dockerignore",
        "go_packages": ["./cmd/server", "./cmd/download/duckdb"],
        "required_paths": sorted(
            {
                "VERSION",
                "Makefile",
                "scripts/build_images.sh",
                "scripts/get_version.sh",
                *REQUIRED_COPY_ROOTS,
                *REQUIRED_CRITICAL_INPUTS,
            }
        ),
        "external_dependency_lock": (
            "deploy/local-build/app-external-dependencies.v1.json"
        ),
        "build_contract": {
            "target": "runtime",
            "platform": PLATFORM,
            "goos": "linux",
            "goarch": "arm64",
            "cgo_enabled": True,
        },
    }
    lock = _synthetic_dependency_lock()
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    lock_path.write_text(json.dumps(lock, sort_keys=True) + "\n", encoding="utf-8")

    files = {
        "VERSION": "v1.2.3\n",
        "go.mod": (
            "module github.com/Tencent/WeKnora\n\n"
            "go 1.26.0\n\n"
            "require github.com/duckdb/duckdb-go/v2 v2.10502.0\n"
        ),
        "go.sum": "github.com/duckdb/duckdb-go/v2 v2.10502.0 h1:fixture=\n",
        "Makefile": "build-prod:\n\tgo build ./cmd/server\n",
        ".dockerignore": ".git/\n",
        "docker/Dockerfile.app": "FROM scratch AS runtime\n",
        "scripts/build_images.sh": "#!/bin/sh\n",
        "scripts/get_version.sh": "#!/bin/sh\n",
        "config/app.yml": "mode: test\n",
        "scripts/docker-entrypoint.sh": "#!/bin/sh\n",
        "migrations/000001.sql": "select 1;\n",
        "dataset/samples/sample.txt": "sample\n",
        "skills/preloaded/sample/SKILL.md": "sample\n",
        "cmd/server/main.go": (
            "package main\n\n"
            'import _ "github.com/Tencent/WeKnora/internal/newtopsentinel"\n'
        ),
        "cmd/server/bootstrap.go": "package main\n",
        "cmd/server/listen.go": "package main\n",
        "cmd/server/signals_unix.go": "//go:build !windows\n\npackage main\n",
        "cmd/server/signals_windows.go": "//go:build windows\n\npackage main\n",
        "cmd/download/duckdb/duckdb.go": "package main\n",
        "internal/newtopsentinel/sentinel.go": "package newtopsentinel\n",
        "internal/config/config.go": "package config\n",
        "internal/container/container.go": "package container\n",
        "internal/logger/logger.go": "package logger\n",
        "internal/router/router.go": "package router\n",
        "internal/runtime/server.go": "package runtime\n",
        "internal/types/interfaces/user.go": "package interfaces\n",
        "internal/assets/embed.go": (
            "package assets\n\nimport _ \"embed\"\n\n"
            "//go:embed asr_test.wav\nvar ASR []byte\n"
        ),
        "internal/assets/asr_test.wav": "fixture\n",
        "docs/docs.go": "package docs\n",
        "docs/swagger.json": "{}\n",
        "docs/swagger.yaml": "swagger: '2.0'\n",
        "docreader/client/auth.go": "package client\n",
        "docreader/client/client.go": "package client\n",
        "docreader/proto/docreader.pb.go": "package proto\n",
        "docreader/proto/docreader_grpc.pb.go": "package proto\n",
        "deploy/upstream/adoption_target.go": "package upstream\n",
        "deploy/upstream/weknora-adoption-target.json": "{}\n",
        "deploy/upstream/weknora-plugin-contract.yaml": "version: 1\n",
    }
    for relative, content in files.items():
        path = repo_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return manifest_path, lock_path


def _synthetic_dependency_lock() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "platform": {
            "os": "linux",
            "arch": "arm64",
            "duckdb": "fixture-duckdb-platform",
        },
        "base_images": {
            "builder": {
                "reference": "golang:1.26-bookworm@sha256:" + "3" * 64,
            },
            "runtime": {
                "reference": "debian:12.12-slim@sha256:" + "4" * 64,
            },
        },
        "debian": {
            "repositories": {
                "debian": {
                    "snapshot": (
                        "https://snapshot.debian.org/archive/debian/20260801T000000Z/"
                    ),
                    "release_sha256": "5" * 64,
                },
                "debian-security": {
                    "snapshot": (
                        "https://snapshot.debian.org/archive/debian-security/"
                        "20260801T000000Z/"
                    ),
                    "release_sha256": "6" * 64,
                },
            },
            "packages": {
                package: f"1.0.0-ba0-{index}"
                for index, package in enumerate(
                    (
                        "git",
                        "build-essential",
                        "libsqlite3-dev",
                        "ca-certificates",
                        "postgresql-client",
                        "default-mysql-client",
                        "tzdata",
                        "sed",
                        "curl",
                        "bash",
                        "vim",
                        "wget",
                        "libsqlite3-0",
                        "python3",
                        "python3-pip",
                        "python3-dev",
                        "libffi-dev",
                        "libssl-dev",
                        "nodejs",
                        "npm",
                        "gosu",
                        "ffmpeg",
                    ),
                    start=1,
                )
            },
        },
        "python_tools": {
            name: {
                "version": version,
                "origin": f"https://files.pythonhosted.org/packages/{name}-{version}.whl",
                "sha256": digit * 64,
            }
            for name, version, digit in (
                ("pip", "25.2", "6"),
                ("setuptools", "80.9.0", "7"),
                ("wheel", "0.45.1", "8"),
            )
        },
        "downloads": {
            "go_tools": {
                "migrate": {
                    "module": "github.com/golang-migrate/migrate/v4/cmd/migrate",
                    "version": "v4.19.1",
                    "go_sum": "h1:" + "M" * 43 + "=",
                }
            },
            "uv": {
                "version": "0.9.26",
                "platform": "fixture-linux-arm64",
                "origin": "https://dependencies.invalid/uv/0.9.26/install.sh",
                "sha256": "9" * 64,
            },
            "duckdb": {
                "version": "v1.5.2",
                "extensions": {
                    name: {
                        "platform": "fixture-duckdb-platform",
                        "origin": (
                            "https://dependencies.invalid/duckdb/v1.5.2/"
                            f"fixture-duckdb-platform/{name}.duckdb_extension.gz"
                        ),
                        "sha256": digit * 64,
                    }
                    for name, digit in (("spatial", "a"), ("excel", "b"))
                },
            },
        },
    }


def _identity_record() -> dict[str, Any]:
    return {
        "artifact": "weknora-app",
        "artifact_identity": ARTIFACT_IDENTITY,
        "manifest_sha256": MANIFEST_SHA256,
        "dependency_lock_sha256": LOCK_SHA256,
        "build_source_head": BUILD_SOURCE_HEAD,
        "integration_head": INTEGRATION_HEAD,
        "target": "runtime",
        "platform": PLATFORM,
        "labels": dict(REQUIRED_LABELS),
    }


def _image_inspect(
    *,
    image_id: str = IMAGE_ID,
    os_name: str = "linux",
    architecture: str = "arm64",
    labels: Mapping[str, str] | None = None,
) -> str:
    return json.dumps(
        {
            "Id": image_id,
            "Os": os_name,
            "Architecture": architecture,
            "Config": {
                "Labels": dict(REQUIRED_LABELS if labels is None else labels)
            },
        }
    )


def _invalid_image_inspections() -> tuple[tuple[str, str, int, str], ...]:
    drift_values = {
        "io.insurancekb.app.artifact-identity": "sha256:" + "f" * 64,
        "io.insurancekb.app.build-source-head": "e" * 40,
        "io.insurancekb.app.manifest-sha256": "3" * 64,
        "io.insurancekb.app.dependency-lock-sha256": "4" * 64,
        "io.insurancekb.app.target": "builder",
        "io.insurancekb.app.platform": "linux/amd64",
    }
    cases: list[tuple[str, str, int, str]] = []
    for label, drift in drift_values.items():
        slug = label.removeprefix("io.insurancekb.app.").replace("-", "_")
        missing = {name: value for name, value in REQUIRED_LABELS.items() if name != label}
        changed = {**REQUIRED_LABELS, label: drift}
        cases.extend(
            (
                (
                    f"missing-{slug}",
                    _image_inspect(labels=missing),
                    0,
                    "label|missing",
                ),
                (
                    f"drift-{slug}",
                    _image_inspect(labels=changed),
                    0,
                    "label|drift|mismatch",
                ),
            )
        )
    cases.extend(
        (
            ("os", _image_inspect(os_name="darwin"), 0, "linux|os|platform"),
            ("arch", _image_inspect(architecture="amd64"), 0, "arm64|arch|platform"),
            ("inspect-error", "", 1, "inspect"),
            (
                "image-id",
                _image_inspect(image_id="sha256:" + "9" * 64),
                0,
                "image|candidate|inspect",
            ),
        )
    )
    return tuple(cases)


def _is_docker_build(arguments: tuple[str, ...]) -> bool:
    if not arguments or arguments[0] != "docker":
        return False
    tail = arguments[arguments.index(CONTEXT) + 1 :] if CONTEXT in arguments else arguments[1:]
    return bool(tail and (tail[0] == "build" or tail[:2] == ("buildx", "build")))


def _assert_exact_lookup_query(call: RecordedCall) -> None:
    arguments = call.arguments
    assert arguments[:5] == ("docker", "--context", CONTEXT, "image", "ls")
    assert "--quiet" in arguments
    assert "--no-trunc" in arguments
    filters = [
        arguments[index + 1]
        for index, value in enumerate(arguments[:-1])
        if value == "--filter"
    ]
    assert f"label=io.insurancekb.app.artifact-identity={ARTIFACT_IDENTITY}" in filters
    reference_filters = [value for value in filters if value.startswith("reference=")]
    assert reference_filters == [f"reference={APP_REPOSITORY}:*"]


def _assert_exact_candidate_inspect(call: RecordedCall, candidate: str) -> None:
    assert call.arguments == (
        "docker",
        "--context",
        CONTEXT,
        "image",
        "inspect",
        candidate,
        "--format",
        "{{json .}}",
    )


def _docker_build_args(call: RecordedCall) -> dict[str, str]:
    assert _is_docker_build(call.arguments)
    values: dict[str, str] = {}
    index = 0
    while index < len(call.arguments):
        argument = call.arguments[index]
        if argument == "--build-arg":
            index += 1
            assert index < len(call.arguments), "--build-arg lacks KEY=VALUE"
            item = call.arguments[index]
        elif argument.startswith("--build-arg="):
            item = argument.removeprefix("--build-arg=")
        else:
            index += 1
            continue
        assert "=" in item, f"build arg must freeze a value: {item!r}"
        name, value = item.split("=", 1)
        assert name and name not in values
        values[name] = value
        index += 1
    return values


def _docker_option_values(
    arguments: tuple[str, ...], option: str, *, short: str | None = None
) -> list[str]:
    values: list[str] = []
    for index, argument in enumerate(arguments):
        if argument == option or (short is not None and argument == short):
            assert index + 1 < len(arguments), f"{argument} lacks a value"
            values.append(arguments[index + 1])
        elif argument.startswith(option + "="):
            values.append(argument.removeprefix(option + "="))
    return values


def _effective_build_labels(arguments: tuple[str, ...], cwd: Path) -> dict[str, str]:
    labels: dict[str, str] = {}
    file_options = _docker_option_values(arguments, "--file", short="-f")
    assert len(file_options) <= 1
    if file_options:
        dockerfile = Path(file_options[0])
        if not dockerfile.is_absolute():
            dockerfile = cwd / dockerfile
    else:
        context = Path(arguments[-1])
        dockerfile = (context if context.is_absolute() else cwd / context) / "Dockerfile"

    variables = _docker_build_args(RecordedCall(arguments, cwd, {}))

    def expand(value: str) -> str:
        return re.sub(
            r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))",
            lambda match: variables.get(
                match.group(1) or match.group(2), match.group(0)
            ),
            value,
        )

    if dockerfile.is_file():
        for instruction in _dockerfile_instructions(
            dockerfile.read_text(encoding="utf-8")
        ):
            keyword, _, operands = instruction.partition(" ")
            if keyword == "FROM":
                labels = {}
            elif keyword == "ARG":
                for item in shlex.split(operands):
                    if "=" in item:
                        name, value = item.split("=", 1)
                        variables.setdefault(name, expand(value))
            elif keyword == "ENV":
                for item in shlex.split(operands):
                    if "=" in item:
                        name, value = item.split("=", 1)
                        variables[name] = expand(value)
            elif keyword == "LABEL":
                for item in shlex.split(operands):
                    assert "=" in item, "LABEL must carry an explicit key=value"
                    name, value = item.split("=", 1)
                    labels[name] = expand(value)

    for item in _docker_option_values(arguments, "--label"):
        assert "=" in item, "--label must carry an explicit key=value"
        name, value = item.split("=", 1)
        labels[name] = value
    return labels


@dataclass(frozen=True)
class LockUse:
    paths: tuple[str, ...]
    values: tuple[str, ...]
    consumer: str
    operation: str
    description: str


def _dependency_lock_uses(lock: Mapping[str, Any]) -> tuple[LockUse, ...]:
    repositories = lock["debian"]["repositories"]
    packages = lock["debian"]["packages"]
    python_tools = lock["python_tools"]
    downloads = lock["downloads"]
    migrate = downloads["go_tools"]["migrate"]
    duckdb = downloads["duckdb"]

    def use(
        items: list[tuple[str, object]],
        consumer: str,
        operation: str,
        description: str,
    ) -> LockUse:
        return LockUse(
            paths=tuple(path for path, _ in items),
            values=tuple(str(value) for _, value in items),
            consumer=consumer,
            operation=operation,
            description=description,
        )

    return (
        use(
            [
                ("schema_version", lock["schema_version"]),
                ("platform.os", lock["platform"]["os"]),
                ("platform.arch", lock["platform"]["arch"]),
            ],
            "validate",
            r"\btest\b",
            "lock schema and target platform",
        ),
        use(
            [("base_images.builder.reference", lock["base_images"]["builder"]["reference"])],
            "from-builder",
            r"^FROM\b",
            "builder base image",
        ),
        use(
            [("base_images.runtime.reference", lock["base_images"]["runtime"]["reference"])],
            "from-runtime",
            r"^FROM\b",
            "runtime base image",
        ),
        use(
            [
                (f"debian.repositories.{name}.snapshot", repository["snapshot"])
                for name, repository in repositories.items()
            ],
            "apt-source",
            r"\b(?:printf|echo|sed|tee)\b",
            "Debian snapshots",
        ),
        use(
            [
                (
                    f"debian.repositories.{name}.release_sha256",
                    repository["release_sha256"],
                )
                for name, repository in repositories.items()
            ],
            "sha256",
            r"\b(?:printf|echo)\b(?=[^;&]*\|\s*sha256sum\s+-c\b)",
            "Debian Release SHA256",
        ),
        use(
            [(f"debian.packages.{name}", value) for name, value in packages.items()],
            "apt",
            r"\bapt-get\s+install\b",
            "Debian package versions",
        ),
        use(
            [
                (f"python_tools.{name}.version", tool["version"])
                for name, tool in python_tools.items()
            ],
            "pip",
            r"\bpip3?\s+install\b",
            "Python tool versions",
        ),
        use(
            [
                (f"python_tools.{name}.origin", tool["origin"])
                for name, tool in python_tools.items()
            ],
            "download",
            r"\b(?:curl|wget|pip3?\s+download)\b",
            "Python tool origins",
        ),
        use(
            [
                (f"python_tools.{name}.sha256", tool["sha256"])
                for name, tool in python_tools.items()
            ],
            "sha256",
            r"\b(?:printf|echo)\b(?=[^;&]*\|\s*sha256sum\s+-c\b)",
            "Python tool SHA256 values",
        ),
        use(
            [
                (f"downloads.uv.{name}", downloads["uv"][name])
                for name in ("version", "platform", "origin")
            ],
            "download",
            r"\b(?:curl|wget)\b",
            "uv download coordinates",
        ),
        use(
            [("downloads.uv.sha256", downloads["uv"]["sha256"])],
            "sha256",
            r"\b(?:printf|echo)\b(?=[^;&]*\|\s*sha256sum\s+-c\b)",
            "uv SHA256",
        ),
        use(
            [
                (f"downloads.go_tools.migrate.{name}", migrate[name])
                for name in ("module", "version")
            ],
            "go-install",
            r"\bgo\s+install\b",
            "migrate module and version",
        ),
        use(
            [("downloads.go_tools.migrate.go_sum", migrate["go_sum"])],
            "go-sum",
            r"\bgrep\b",
            "migrate go_sum",
        ),
        use(
            [
                ("platform.duckdb", lock["platform"]["duckdb"]),
                ("downloads.duckdb.version", duckdb["version"]),
            ]
            + [
                (f"downloads.duckdb.extensions.{extension}.{name}", item[name])
                for extension, item in duckdb["extensions"].items()
                for name in ("platform", "origin", "sha256")
            ],
            "duckdb-download",
            r"\bgo\s+run\s+cmd/download/duckdb/duckdb\.go\b",
            "DuckDB locked download plan",
        ),
    )


def _has_ignored_failure(command: str) -> bool:
    return re.search(r"\|\|\s*(?::(?:\s|$)|true\b)", command) is not None


def _variable_is_operation_operand(command: str, operation: str, name: str) -> bool:
    operation_match = re.search(operation, command, re.I)
    if operation_match is None or _has_ignored_failure(command):
        return False
    variable_match = re.search(
        rf"\$(?:\{{{re.escape(name)}\}}|{re.escape(name)})(?![A-Za-z0-9_])",
        command,
    )
    return variable_match is not None and variable_match.start() >= operation_match.end()


def _lock_shell_segments(instructions: list[str]) -> list[str]:
    return [
        segment.strip()
        for instruction in instructions
        for segment in re.split(r"\s*(?:&&|;)\s*", instruction)
        if segment.strip()
    ]


def _assert_no_floating_or_ignored_installs(instructions: list[str]) -> None:
    for segment in _lock_shell_segments(instructions):
        operation = re.search(
            r"\b(?:apt-get\s+install|pip3?\s+install|go\s+install)\b",
            segment,
            re.I,
        )
        if operation is None:
            continue
        assert not _has_ignored_failure(segment), "locked install failure cannot be ignored"
        operands = segment[operation.end() :]
        assert "latest" not in operands.lower()
        if re.match(r"\bapt-get\s+install\b", operation.group(), re.I):
            assert "$" in operands or "=" in operands, "apt install must consume a pin"
        elif re.match(r"\bpip", operation.group(), re.I):
            assert "--upgrade" not in operands
            assert "$" in operands or "==" in operands or ".whl" in operands
        else:
            assert "$" in operands or re.search(r"@v?\d", operands)


def _build_args_cover_lock_uses(
    uses: tuple[LockUse, ...], build_args: Mapping[str, str]
) -> bool:
    return all(
        any(value in argument for argument in build_args.values())
        for use in uses
        for value in use.values
    )


def _assert_build_arg_lock_dataflow(
    uses: tuple[LockUse, ...],
    build_args: Mapping[str, str],
    instructions: list[str],
) -> None:
    segments = _lock_shell_segments(instructions)
    for use in uses:
        for value in use.values:
            names = {
                name for name, argument in build_args.items() if value in argument
            }
            assert names, f"{use.description} was not mapped to a build arg"
            assert all(
                any(
                    _variable_is_operation_operand(segment, use.operation, name)
                    for segment in segments
                )
                for name in names
            ), f"{use.description} build args are not real operation operands"


def _assert_copied_lock_dataflow(
    lock: Mapping[str, Any],
    uses: tuple[LockUse, ...],
    dependency_plan: Mapping[str, object],
    instructions: list[str],
) -> None:
    lock_relative = "deploy/local-build/app-external-dependencies.v1.json"
    copies = [
        (index, instruction)
        for index, instruction in enumerate(instructions)
        if instruction.startswith("COPY ") and lock_relative in instruction
    ]
    assert len(copies) == 1, "Dockerfile must COPY the exact versioned lock"
    copy_index, copy_instruction = copies[0]
    lock_destination = copy_instruction.split()[-1]

    output_path = dependency_plan.get("output_path")
    bindings = dependency_plan.get("bindings")
    assert isinstance(output_path, str) and output_path
    assert isinstance(bindings, list) and bindings
    canonical_lock = json.dumps(lock, sort_keys=True, separators=(",", ":")).encode()
    assert dependency_plan.get("lock_sha256") == _sha256_bytes(canonical_lock)

    expected_facts = {
        path: (use.consumer, value)
        for use in uses
        if not use.consumer.startswith("from-")
        for path, value in zip(use.paths, use.values, strict=True)
    }
    bound_paths: set[str] = set()
    bound_names: set[str] = set()
    normalized_bindings: list[tuple[str, str, str, str]] = []
    for raw_binding in bindings:
        assert isinstance(raw_binding, Mapping)
        name = raw_binding.get("name")
        consumer = raw_binding.get("consumer")
        fact_path = raw_binding.get("fact_path")
        value = raw_binding.get("value")
        assert isinstance(name, str) and re.fullmatch(r"[A-Z][A-Z0-9_]*", name)
        assert isinstance(consumer, str)
        assert isinstance(fact_path, str) and fact_path in expected_facts
        assert isinstance(value, str)
        expected_consumer, expected_value = expected_facts[fact_path]
        assert consumer == expected_consumer
        assert value == expected_value, f"wrong lock value for {fact_path}"
        assert fact_path not in bound_paths, "plan fact bound twice"
        assert name not in bound_names, "plan output name reused"
        bound_paths.add(fact_path)
        bound_names.add(name)
        normalized_bindings.append((name, consumer, fact_path, value))
    assert bound_paths == set(expected_facts), "plan must cover every lock fact"
    assert [binding[2] for binding in normalized_bindings] == sorted(expected_facts), (
        "dependency plan bindings must be deterministically ordered by fact path"
    )
    expected_output = "".join(
        f"{name}={json.dumps(value, ensure_ascii=False)}\n"
        for name, _, _, value in normalized_bindings
    ).encode()
    assert dependency_plan.get("output_bytes") == expected_output, (
        "dependency plan output_bytes do not match its bindings"
    )

    expected_parser_argv = [
        "python3",
        "scripts/app_artifact.py",
        "dependency-plan",
        "--lock",
        lock_destination,
        "--output",
        output_path,
    ]
    parser_indexes: list[int] = []
    for index, instruction in enumerate(instructions):
        if index <= copy_index or not instruction.startswith("RUN "):
            continue
        try:
            argv = shlex.split(instruction.removeprefix("RUN ").strip())
        except ValueError:
            continue
        if argv == expected_parser_argv:
            parser_indexes.append(index)
    assert parser_indexes, "exact dependency-plan parser argv required; -c is forbidden"
    parser_index = parser_indexes[0]
    operation_by_consumer = {use.consumer: use.operation for use in uses}
    for name, consumer, _, _ in normalized_bindings:
        operation = operation_by_consumer[consumer]
        assert any(
            index > parser_index
            and re.search(
                rf"(?:\bsource|\.)\s+['\"]?{re.escape(output_path)}['\"]?",
                instruction,
            )
            and any(
                _variable_is_operation_operand(segment, operation, name)
                for segment in _lock_shell_segments([instruction])
            )
            for index, instruction in enumerate(instructions)
        ), f"plan output {name} is not consumed by {consumer}"


def _assert_dependency_lock_dataflow(
    lock: Mapping[str, Any],
    build_args: Mapping[str, str],
    dockerfile_source: str,
    dependency_plan: Mapping[str, object] | None = None,
) -> None:
    instructions = [
        _executable_text(item)
        for item in _dockerfile_instructions(dockerfile_source)
    ]
    uses = _dependency_lock_uses(lock)
    _assert_no_floating_or_ignored_installs(instructions)
    assert any(
        re.search(r"\buv\b", instruction, re.I)
        and re.search(r"\b(?:sh|bash)\b", instruction)
        and not _has_ignored_failure(instruction)
        for instruction in instructions
    ), "the verified uv payload must actually be installed"
    base_uses = tuple(use for use in uses if use.consumer.startswith("from-"))
    _assert_build_arg_lock_dataflow(base_uses, build_args, instructions)
    dependency_uses = tuple(
        use for use in uses if not use.consumer.startswith("from-")
    )
    if _build_args_cover_lock_uses(dependency_uses, build_args):
        _assert_build_arg_lock_dataflow(dependency_uses, build_args, instructions)
    else:
        assert dependency_plan is not None, "copied-lock path requires a dependency plan"
        _assert_copied_lock_dataflow(
            lock, uses, dependency_plan, instructions
        )


def _selector_runner(
    *,
    candidates: str,
    inspect_stdout: str | None = None,
    inspect_returncode: int = 0,
    query_returncode: int = 0,
) -> FakeRunner:
    built_inspect: str | None = None

    def respond(
        arguments: tuple[str, ...],
        cwd: Path,
        kwargs: Mapping[str, object],
        index: int,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal built_inspect
        del kwargs, index
        assert arguments[:3] == ("docker", "--context", CONTEXT)
        if "image" in arguments and "ls" in arguments:
            return _completed(
                arguments,
                returncode=query_returncode,
                stdout=candidates,
                stderr="query failed" if query_returncode else "",
            )
        if _is_docker_build(arguments):
            if "--iidfile" in arguments:
                iidfile = Path(arguments[arguments.index("--iidfile") + 1])
                iidfile.write_text(
                    IMAGE_ID + "\n", encoding="utf-8"
                )
                built_image_id = iidfile.read_text(encoding="utf-8").strip()
                platforms = _docker_option_values(arguments, "--platform")
                if len(platforms) == 1 and re.fullmatch(r"[^/]+/[^/]+", platforms[0]):
                    built_os, built_arch = platforms[0].split("/", 1)
                else:
                    built_os, built_arch = "", ""
                built_inspect = _image_inspect(
                    image_id=built_image_id,
                    os_name=built_os,
                    architecture=built_arch,
                    labels=_effective_build_labels(arguments, cwd),
                )
            return _completed(arguments, stdout=f"built {IMAGE_ID}\n")
        if "inspect" in arguments:
            inspect = (
                inspect_stdout
                if inspect_stdout is not None
                else built_inspect or _image_inspect()
            )
            return _completed(
                arguments,
                returncode=inspect_returncode,
                stdout=inspect,
                stderr="inspect failed" if inspect_returncode else "",
            )
        raise AssertionError(f"unexpected selector command: {arguments!r}")

    return FakeRunner(respond)


def _selector_call(
    module: ModuleType,
    tmp_path: Path,
    runner: Runner,
    *,
    repo_root: Path = REPO_ROOT,
    secrets: Mapping[str, str] | None = None,
    budget: int = 1,
) -> dict[str, Any]:
    evidence = tmp_path / "selector-receipt.json"
    result = module.select_or_build_app(
        repo_root=repo_root,
        identity=_identity_record(),
        evidence_out=evidence,
        runner=runner,
        secret_values=dict(secrets or {}),
        real_build_budget_remaining=budget,
    )
    assert isinstance(result, dict)
    assert evidence.is_file(), "selector must write the requested receipt"
    assert json.loads(evidence.read_text(encoding="utf-8")) == result
    return result


def _d2_receipt(path: Path) -> dict[str, Any]:
    receipt = {
        "contract": "ba0-app-build-receipt.v1",
        "status": "PASS",
        "selector": "REUSE",
        "artifact_identity": ARTIFACT_IDENTITY,
        "image_id": IMAGE_ID,
        "build_source_head": BUILD_SOURCE_HEAD,
        "integration_head": INTEGRATION_HEAD,
        "manifest_sha256": MANIFEST_SHA256,
        "dependency_lock_sha256": LOCK_SHA256,
        "platform": PLATFORM,
        "target": "runtime",
        "labels": dict(REQUIRED_LABELS),
        "build_invocations": 0,
    }
    path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def _valid_rendered_compose() -> dict[str, Any]:
    assert EXACT_COMPOSE_PATH.is_file(), "planned BA0 standalone Compose missing"
    document = yaml.safe_load(EXACT_COMPOSE_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, dict)

    def substitute(value: object) -> object:
        if isinstance(value, str):
            return re.sub(
                r"\$\{BA0_APP_IMAGE(?::[-+?][^}]*)?\}|\$BA0_APP_IMAGE\b",
                IMAGE_ID,
                value,
            )
        if isinstance(value, list):
            return [substitute(item) for item in value]
        if isinstance(value, dict):
            return {key: substitute(item) for key, item in value.items()}
        return value

    rendered = substitute(document)
    assert isinstance(rendered, dict)
    assert "BA0_APP_IMAGE" not in _json_text(rendered)
    return rendered


class D3Runner(FakeRunner):
    def __init__(
        self,
        *,
        source_inspect: str | None = None,
        rendered_compose: Mapping[str, object] | None = None,
        collision: bool = False,
        runtime_returncode: int = 0,
    ) -> None:
        self.events: list[str] = []
        self._source_inspect = source_inspect or _image_inspect()
        self._rendered_compose = dict(rendered_compose or _valid_rendered_compose())
        self._collision = collision
        self._runtime_returncode = runtime_returncode
        self.env_files: list[tuple[Path, int, str]] = []
        self.env_path: Path | None = None
        self.evidence_path: Path | None = None
        self.receipt_existed_at_cleanup: bool | None = None
        super().__init__(self._respond)

    @staticmethod
    def _compose_arguments(env_path: Path, action: str) -> tuple[str, ...]:
        prefix = (
            "docker",
            "--context",
            CONTEXT,
            "compose",
            "--project-name",
            D3_PROJECT,
            "--env-file",
            str(env_path),
            "-f",
            "deploy/local-build/docker-compose.app-exact.yml",
        )
        suffixes = {
            "config": ("config", "--format", "json"),
            "up": (
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                "30",
                "--no-build",
                "--pull",
                "never",
                "app-smoke",
            ),
            "down": ("down", "--remove-orphans"),
        }
        return (*prefix, *suffixes[action])

    def _respond(
        self,
        arguments: tuple[str, ...],
        cwd: Path,
        kwargs: Mapping[str, object],
        index: int,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, kwargs, index
        assert arguments[:3] == ("docker", "--context", CONTEXT)
        assert not _is_docker_build(arguments), "D3 must never invoke docker build"

        if arguments[3:5] == ("image", "inspect"):
            expected = (
                "docker",
                "--context",
                CONTEXT,
                "image",
                "inspect",
                IMAGE_ID,
                "--format",
                "{{json .}}",
            )
            assert arguments == expected
            self.events.append("image-inspect")
            return _completed(arguments, stdout=self._source_inspect)

        collision_probe = (
            "docker",
            "--context",
            CONTEXT,
            "ps",
            "--all",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={D3_PROJECT}",
        )
        if arguments[3:4] == ("ps",):
            assert arguments == collision_probe
            self.events.append("project-collision")
            return _completed(arguments, stdout="occupied\n" if self._collision else "")

        runtime_inspect = (
            "docker",
            "--context",
            CONTEXT,
            "inspect",
            D3_CONTAINER,
            "--format",
            "{{json .}}",
        )
        if arguments[3:4] == ("inspect",):
            assert arguments == runtime_inspect
            self.events.append("runtime-inspect")
            return _completed(
                arguments,
                returncode=self._runtime_returncode,
                stdout=(
                    json.dumps(
                        {
                            "Id": "sha256:" + "7" * 64,
                            "Name": "/" + D3_CONTAINER,
                            "Image": IMAGE_ID,
                            "State": {
                                "Status": "running",
                                "Health": {"Status": "healthy"},
                            },
                        }
                    )
                    if self._runtime_returncode == 0
                    else ""
                ),
                stderr="runtime inspect failed" if self._runtime_returncode else "",
            )

        if arguments[3:4] == ("compose",):
            assert "--env-file" in arguments
            env_path = Path(arguments[arguments.index("--env-file") + 1])
            if self.env_path is None:
                self.env_path = env_path
            assert env_path == self.env_path
            self.env_files.append(
                (
                    env_path,
                    stat.S_IMODE(env_path.stat().st_mode),
                    env_path.read_text(encoding="utf-8"),
                )
            )
            if arguments == self._compose_arguments(env_path, "config"):
                self.events.append("compose-config")
                return _completed(arguments, stdout=json.dumps(self._rendered_compose))
            if arguments == self._compose_arguments(env_path, "up"):
                self.events.append("compose-up")
                return _completed(arguments)
            if arguments == self._compose_arguments(env_path, "down"):
                assert self.evidence_path is not None
                self.receipt_existed_at_cleanup = self.evidence_path.exists()
                self.events.append("cleanup")
                return _completed(arguments)

        raise AssertionError(f"unexpected D3 Docker command: {arguments!r}")


def _d3_call(
    module: ModuleType,
    tmp_path: Path,
    runner: Runner,
    *,
    nonce: str = D3_NONCE,
) -> dict[str, Any]:
    d2_receipt_path = tmp_path / "d2.json"
    evidence_path = tmp_path / "d3.json"
    _d2_receipt(d2_receipt_path)
    if isinstance(runner, D3Runner):
        runner.evidence_path = evidence_path
    result = module.run_exact_image_smoke(
        repo_root=REPO_ROOT,
        d2_receipt_path=d2_receipt_path,
        evidence_out=evidence_path,
        nonce=nonce,
        runner=runner,
    )
    assert isinstance(result, dict)
    assert evidence_path.is_file(), "D3 must write its receipt after cleanup"
    assert json.loads(evidence_path.read_text(encoding="utf-8")) == result
    return result


# BA0-REQ-01: complete, reproducible, input-sensitive identity.


def test_manifest_is_closed_versioned_and_names_real_app_inputs() -> None:
    module = _artifact_module()
    document = _load_json(MANIFEST_PATH, description="app build-input manifest")

    assert document["schema_version"] == 1
    assert document["artifact"] == "weknora-app"
    assert document["context"] == "."
    assert document["dockerfile"] == "docker/Dockerfile.app"
    assert document["dockerignore"] == ".dockerignore"
    assert document["go_packages"] == ["./cmd/server", "./cmd/download/duckdb"]
    assert document["external_dependency_lock"] == (
        "deploy/local-build/app-external-dependencies.v1.json"
    )
    build_contract = document["build_contract"]
    assert build_contract == {
        "target": "runtime",
        "platform": PLATFORM,
        "goos": "linux",
        "goarch": "arm64",
        "cgo_enabled": True,
    }
    manifest_text = _json_text(document)
    for required in REQUIRED_COPY_ROOTS | REQUIRED_CRITICAL_INPUTS:
        assert required in manifest_text

    loaded = module.load_manifest(MANIFEST_PATH)
    assert loaded is not None


def test_manifest_resolver_includes_known_real_go_and_embed_closure() -> None:
    module = _artifact_module()
    manifest = module.load_manifest(MANIFEST_PATH)
    runner = _identity_runner(REPO_ROOT)

    resolved = module.resolve_inputs(REPO_ROOT, manifest, runner=runner)
    paths = _resolved_paths(resolved)

    assert REQUIRED_CRITICAL_INPUTS <= paths
    for required_root in REQUIRED_COPY_ROOTS:
        assert any(path == required_root or path.startswith(required_root + "/") for path in paths)
    assert "go.mod" in paths
    assert "go.sum" in paths
    assert "internal/router/router.go" in paths
    assert "docker/Dockerfile.app" in paths
    assert ".dockerignore" in paths
    assert "Makefile" in paths
    assert "VERSION" in paths
    go_list_calls = [
        call for call in runner.calls if call.arguments[0:2] == ("go", "list")
    ]
    assert len(go_list_calls) == 1
    assert go_list_calls[0].arguments[:4] == ("go", "list", "-deps", "-json")
    assert set(go_list_calls[0].arguments[4:]) == {
        "./cmd/server",
        "./cmd/download/duckdb",
    }
    assert go_list_calls[0].cwd == REPO_ROOT
    go_list_env = go_list_calls[0].kwargs.get("env")
    assert isinstance(go_list_env, Mapping)
    assert {
        name: go_list_env.get(name)
        for name in ("GOOS", "GOARCH", "CGO_ENABLED")
    } == {"GOOS": "linux", "GOARCH": "arm64", "CGO_ENABLED": "1"}
    assert all(call.arguments[0] != "docker" for call in runner.calls)


def test_manifest_resolver_follows_new_top_level_import_and_embed_sentinel(
    tmp_path: Path,
) -> None:
    module = _artifact_module()
    repo_root = tmp_path / "repository"
    manifest_path, _ = _write_synthetic_contract(repo_root)
    runner = _identity_runner(repo_root)

    resolved = module.resolve_inputs(
        repo_root,
        module.load_manifest(manifest_path),
        runner=runner,
    )

    paths = _resolved_paths(resolved)
    assert "internal/newtopsentinel/sentinel.go" in paths
    assert "internal/assets/asr_test.wav" in paths
    assert "cmd/server/bootstrap.go" in paths
    assert "cmd/server/listen.go" in paths
    assert "cmd/server/signals_unix.go" in paths
    assert "cmd/server/signals_windows.go" not in paths


@pytest.mark.parametrize("failure", ("command", "deps-error"))
def test_manifest_resolver_rejects_unresolved_go_dependency(
    tmp_path: Path,
    failure: str,
) -> None:
    module = _artifact_module()
    repo_root = tmp_path / "repository"
    manifest_path, _ = _write_synthetic_contract(repo_root)
    runner = _identity_runner(repo_root, go_list_failure=failure)

    with pytest.raises(module.ArtifactContractError, match="go list|dependency|unresolved"):
        module.resolve_inputs(
            repo_root,
            module.load_manifest(manifest_path),
            runner=runner,
        )

    assert all(call.arguments[0] != "docker" for call in runner.calls)


def test_manifest_loader_rejects_unknown_fields_and_repository_escape(
    tmp_path: Path,
) -> None:
    module = _artifact_module()
    document = _load_json(MANIFEST_PATH, description="app build-input manifest")

    unknown_path = tmp_path / "unknown.json"
    unknown_path.write_text(
        json.dumps({**document, "silent_extra_input": True}), encoding="utf-8"
    )
    with pytest.raises(module.ArtifactContractError, match="unknown|schema|field"):
        module.load_manifest(unknown_path)

    escaped = deepcopy(document)
    escaped["required_paths"] = [*escaped["required_paths"], "../outside"]
    escaped_path = tmp_path / "escaped.json"
    escaped_path.write_text(json.dumps(escaped), encoding="utf-8")
    with pytest.raises(module.ArtifactContractError, match="repository|escape|outside"):
        module.load_manifest(escaped_path)


def test_identity_is_stable_across_docs_only_integration_heads() -> None:
    module = _artifact_module()
    runner = _identity_runner(REPO_ROOT)
    common = {
        "repo_root": REPO_ROOT,
        "manifest_path": MANIFEST_PATH,
        "dependency_lock_path": DEPENDENCY_LOCK_PATH,
        "build_source_head": BUILD_SOURCE_HEAD,
        "runner": runner,
        "effective_build_args": {"CGO_ENABLED": "1"},
        "environment": {"GOPROXY": "https://proxy-one.example"},
    }

    first = module.canonical_identity(integration_head=INTEGRATION_HEAD, **common)
    second = module.canonical_identity(integration_head="e" * 40, **common)

    assert first["artifact_identity"] == second["artifact_identity"]
    assert first["canonical_bytes"] == second["canonical_bytes"]
    assert first["build_source_head"] == second["build_source_head"] == BUILD_SOURCE_HEAD
    assert first["integration_head"] == INTEGRATION_HEAD
    assert second["integration_head"] == "e" * 40
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", first["artifact_identity"])
    assert _sha256_bytes(first["canonical_bytes"]) == first["artifact_identity"].removeprefix(
        "sha256:"
    )


@pytest.mark.parametrize("changed", ("app_input", "dependency_lock"))
def test_identity_changes_when_one_effective_input_changes(
    tmp_path: Path,
    changed: str,
) -> None:
    module = _artifact_module()
    repo_root = tmp_path / "repository"
    manifest_path, lock_path = _write_synthetic_contract(repo_root)
    runner = _identity_runner(repo_root)
    arguments = {
        "repo_root": repo_root,
        "manifest_path": manifest_path,
        "dependency_lock_path": lock_path,
        "build_source_head": BUILD_SOURCE_HEAD,
        "integration_head": INTEGRATION_HEAD,
        "runner": runner,
        "effective_build_args": {"CGO_ENABLED": "1"},
        "environment": {},
    }
    before = module.canonical_identity(**arguments)

    if changed == "app_input":
        (repo_root / "config/app.yml").write_text("mode: changed\n", encoding="utf-8")
    else:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["downloads"]["uv"]["sha256"] = "c" * 64
        lock_path.write_text(json.dumps(lock, sort_keys=True) + "\n", encoding="utf-8")
    after = module.canonical_identity(**arguments)

    assert before["artifact_identity"] != after["artifact_identity"]
    assert before["canonical_bytes"] != after["canonical_bytes"]


def test_identity_input_drift_fails_before_any_docker_invocation() -> None:
    module = _artifact_module()
    runner = _identity_runner(REPO_ROOT, drift=True)

    with pytest.raises(module.ArtifactContractError, match="drift|build.source|manifest"):
        module.canonical_identity(
            repo_root=REPO_ROOT,
            manifest_path=MANIFEST_PATH,
            dependency_lock_path=DEPENDENCY_LOCK_PATH,
            build_source_head=BUILD_SOURCE_HEAD,
            integration_head=INTEGRATION_HEAD,
            runner=runner,
            effective_build_args={"CGO_ENABLED": "1"},
            environment={},
        )

    assert all(call.arguments[0] != "docker" for call in runner.calls)


def test_canonical_identity_secret_canary_is_absent_from_bytes_trace_and_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _artifact_module()
    repo_root = tmp_path / "repository"
    manifest_path, lock_path = _write_synthetic_contract(repo_root)
    environments = (
        {},
        {"GOPRIVATE": CANARY_SECRET, "REPOSITORY_TOKEN": CANARY_SECRET},
        {"GOPRIVATE": CANARY_SECRET_B, "REPOSITORY_TOKEN": CANARY_SECRET_B},
    )
    runners = [_identity_runner(repo_root) for _ in environments]
    results = [
        module.canonical_identity(
            repo_root=repo_root,
            manifest_path=manifest_path,
            dependency_lock_path=lock_path,
            build_source_head=BUILD_SOURCE_HEAD,
            integration_head=INTEGRATION_HEAD,
            runner=runner,
            effective_build_args={"CGO_ENABLED": "1"},
            environment=environment,
        )
        for environment, runner in zip(environments, runners, strict=True)
    ]
    captured = capsys.readouterr()
    assert len({result["canonical_bytes"] for result in results}) == 1
    assert len({result["artifact_identity"] for result in results}) == 1
    surfaces = _json_text(
        {
            "results": results,
            "canonical_bytes": [result["canonical_bytes"] for result in results],
            "trace": [
                call.__dict__ for runner in runners for call in runner.calls
            ],
            "stdout": captured.out,
            "stderr": captured.err,
        }
    )

    for canary in (CANARY_SECRET, CANARY_SECRET_B):
        assert canary not in surfaces
        assert _sha256_bytes(canary.encode()) not in surfaces
    assert all(
        call.arguments[0] != "docker" for runner in runners for call in runner.calls
    )


# BA0-REQ-03/04: stable metadata, builder facts, persistent caches, locked inputs.


def test_metadata_comes_from_build_source_epoch_and_is_wall_clock_stable() -> None:
    module = _artifact_module()
    first_runner = _identity_runner(REPO_ROOT, source_epoch=1_700_000_000)
    second_runner = _identity_runner(REPO_ROOT, source_epoch=1_700_000_000)

    first = module.build_metadata(
        repo_root=REPO_ROOT,
        build_source_head=BUILD_SOURCE_HEAD,
        runner=first_runner,
    )
    second = module.build_metadata(
        repo_root=REPO_ROOT,
        build_source_head=BUILD_SOURCE_HEAD,
        runner=second_runner,
    )

    assert first == second
    assert set(first) == {"version", "commit_id", "source_date_epoch", "build_time"}
    assert first["version"] == "v1.2.3"
    assert first["commit_id"] == BUILD_SOURCE_HEAD
    assert first["source_date_epoch"] == 1_700_000_000
    assert first["build_time"] == datetime.fromtimestamp(
        1_700_000_000, tz=UTC
    ).strftime("%Y-%m-%d %H:%M:%S UTC")
    assert "go_version" not in first, "host Go version must not enter metadata"

    script = GET_VERSION_PATH.read_text(encoding="utf-8")
    assert "BUILD_SOURCE_HEAD" in script
    assert "SOURCE_DATE_EPOCH" in script
    assert "%ct" in script
    build_time_lines = [
        line
        for line in script.splitlines()
        if "BUILD_TIME=" in line and "date" in line
    ]
    assert all("SOURCE_DATE_EPOCH" in line for line in build_time_lines)
    assert "go version" not in script


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


def _cache_mounts(instruction: str) -> dict[str, str]:
    mounts: dict[str, str] = {}
    for mount in re.findall(r"--mount=([^ ]+)", instruction):
        fields = dict(
            part.split("=", 1) for part in mount.split(",") if "=" in part
        )
        if fields.get("type") == "cache" and "target" in fields:
            assert fields.get("sharing") == "locked"
            assert fields.get("id"), f"cache mount lacks a stable id: {mount}"
            mounts[fields["target"]] = fields["id"]
    return mounts


def _shell_assignments(command: str) -> dict[str, str]:
    assignments: dict[str, str] = {}
    pattern = re.compile(
        r"(?:^|[ ;])([A-Za-z_][A-Za-z0-9_]*)=(?:\"([^\"]+)\"|'([^']+)'|([^\s;&]+))"
    )
    for match in pattern.finditer(command):
        assignments[match.group(1)] = next(value for value in match.groups()[1:] if value)
    return assignments


def _resolve_shell_path(token: str, assignments: Mapping[str, str]) -> str:
    value = token.strip("\"'")
    variable = re.fullmatch(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))", value)
    if variable is not None:
        return assignments.get(variable.group(1) or variable.group(2), "")
    return value


def test_dockerfile_gets_go_version_inside_builder_and_uses_stable_metadata() -> None:
    source = DOCKERFILE_PATH.read_text(encoding="utf-8")
    instructions = _dockerfile_instructions(source)
    build = next(item for item in instructions if "make build-prod" in item)

    assert "go version" in build
    assert "GO_VERSION" in build
    assert "SOURCE_DATE_EPOCH" in source
    assert "GO_VERSION_ARG" not in source
    for instruction in instructions:
        if "BUILD_TIME" in instruction and "date" in instruction:
            assert "SOURCE_DATE_EPOCH" in instruction


def test_dockerfile_go_runs_share_locked_module_build_cache_ids_and_probe() -> None:
    source = DOCKERFILE_PATH.read_text(encoding="utf-8")
    instructions = _dockerfile_instructions(source)
    duckdb_run = next(
        item for item in instructions if "go run cmd/download/duckdb/duckdb.go" in item
    )
    build_run = next(item for item in instructions if "make build-prod" in item)

    first_mounts = _cache_mounts(duckdb_run)
    second_mounts = _cache_mounts(build_run)
    assert set(first_mounts) == {"/go/pkg/mod", "/root/.cache/go-build"}
    assert first_mounts == second_mounts
    assert all(
        "SOURCE" not in cache_id and "COMMIT" not in cache_id
        for cache_id in first_mounts.values()
    )
    first_command = _executable_text(duckdb_run)
    second_command = _executable_text(build_run)
    first_assignments = _shell_assignments(first_command)
    second_assignments = _shell_assignments(second_command)
    writes = [
        (
            _resolve_shell_path(
                match.group("path") or match.group("tee"), first_assignments
            ),
            match.start(),
        )
        for match in re.finditer(
            r"\b(?:printf|echo)\b[^;&|]*?>\s*(?P<path>[^\s;&]+)|\btee\s+(?P<tee>[^\s;&]+)",
            first_command,
        )
    ]
    first_checks = [
        (_resolve_shell_path(match.group("path"), first_assignments), match.start())
        for match in re.finditer(
            r"(?:\btest|\[)\s+-s\s+(?P<path>[^\s;&\]]+)", first_command
        )
    ]
    second_checks = [
        (_resolve_shell_path(match.group("path"), second_assignments), match.start())
        for match in re.finditer(
            r"(?:\btest|\[)\s+-s\s+(?P<path>[^\s;&\]]+)", second_command
        )
    ]
    download_position = first_command.index("go run cmd/download/duckdb/duckdb.go")
    compile_position = second_command.index("make build-prod")
    for cache_path in first_mounts:
        cache_writes = [
            (path, position)
            for path, position in writes
            if path == cache_path or path.startswith(cache_path + "/")
        ]
        assert cache_writes, f"the first Go RUN must write a probe in {cache_path}"
        written_probe, write_position = cache_writes[0]
        assert written_probe
        assert not re.search(
            r"secret|token|password|credential", written_probe, re.I
        )
        assert write_position > download_position
        assert any(
            path == written_probe and position > write_position
            for path, position in first_checks
        ), f"the first Go RUN must verify non-empty evidence in {cache_path}"
        assert any(
            path == written_probe and position < compile_position
            for path, position in second_checks
        ), f"the build RUN must verify the same {cache_path} evidence before compiling"


def test_dependency_lock_covers_all_versioned_external_facts_without_proxy() -> None:
    module = _artifact_module()
    document = _load_json(DEPENDENCY_LOCK_PATH, description="external dependency lock")
    module.load_dependency_lock(DEPENDENCY_LOCK_PATH)

    assert document["schema_version"] == 1
    assert document["platform"]["os"] == "linux"
    assert document["platform"]["arch"] == "arm64"
    for stage in ("builder", "runtime"):
        reference = document["base_images"][stage]["reference"]
        assert re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", reference)

    debian = document["debian"]
    assert set(debian["repositories"]) == {"debian", "debian-security"}
    for repository in debian["repositories"].values():
        assert re.fullmatch(
            r"\S+/\d{8}T\d{6}Z/",
            repository["snapshot"],
        )
        assert re.fullmatch(r"[0-9a-f]{64}", repository["release_sha256"])
    required_packages = {
        "git",
        "build-essential",
        "libsqlite3-dev",
        "ca-certificates",
        "postgresql-client",
        "default-mysql-client",
        "tzdata",
        "sed",
        "curl",
        "bash",
        "vim",
        "wget",
        "libsqlite3-0",
        "python3",
        "python3-pip",
        "python3-dev",
        "libffi-dev",
        "libssl-dev",
        "nodejs",
        "npm",
        "gosu",
        "ffmpeg",
    }
    assert required_packages <= set(debian["packages"])
    assert all(value and "latest" not in value for value in debian["packages"].values())

    for name in ("pip", "setuptools", "wheel"):
        tool = document["python_tools"][name]
        assert tool["version"]
        assert tool["version"] in tool["origin"]
        assert re.fullmatch(r"[0-9a-f]{64}", tool["sha256"])

    downloads = document["downloads"]
    migrate = downloads["go_tools"]["migrate"]
    assert migrate["module"] == "github.com/golang-migrate/migrate/v4/cmd/migrate"
    assert migrate["version"] == "v4.19.1"
    assert migrate["go_sum"].startswith("h1:")
    for item in (downloads["uv"], *downloads["duckdb"]["extensions"].values()):
        assert item["platform"]
        assert item["origin"] and not re.search(r"\s", item["origin"])
        assert re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
    assert set(downloads["duckdb"]["extensions"]) == {"spatial", "excel"}
    assert downloads["duckdb"]["version"] == _duckdb_version_from_go_mod(REPO_ROOT)
    assert all(
        item["platform"] == document["platform"]["duckdb"]
        for item in downloads["duckdb"]["extensions"].values()
    )

    public = _json_text(document).lower()
    for forbidden in ("mirror", "proxy", "credential", "password", "secret", "token"):
        assert forbidden not in public
    assert "latest" not in public


def test_docker_build_path_wires_versioned_lock_facts_into_consuming_instructions(
    tmp_path: Path,
) -> None:
    module = _artifact_module()
    repo_root = tmp_path / "repository"
    _, lock_path = _write_synthetic_contract(repo_root)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    runner = _selector_runner(candidates="")

    _selector_call(module, tmp_path, runner, repo_root=repo_root)

    build_calls = [call for call in runner.calls if _is_docker_build(call.arguments)]
    assert len(build_calls) == 1
    build_args = _docker_build_args(build_calls[0])
    dockerfile_source = DOCKERFILE_PATH.read_text(encoding="utf-8")
    uses = _dependency_lock_uses(lock)
    dependency_uses = tuple(
        use for use in uses if not use.consumer.startswith("from-")
    )
    dependency_plan: Mapping[str, object] | None = None
    if not _build_args_cover_lock_uses(dependency_uses, build_args):
        plan_builder = getattr(module, "_dependency_plan", None)
        assert callable(plan_builder), (
            "copied-lock builds require the private _dependency_plan(lock) seam"
        )
        planned = plan_builder(lock)
        assert isinstance(planned, Mapping)
        assert plan_builder(lock) == planned, "dependency plan must be deterministic"
        rendered_plan = tmp_path / "rendered-dependency-plan.env"
        cli = subprocess.run(
            (
                sys.executable,
                "scripts/app_artifact.py",
                "dependency-plan",
                "--lock",
                str(lock_path),
                "--output",
                str(rendered_plan),
            ),
            cwd=REPO_ROOT,
            capture_output=True,
            text=False,
            check=False,
        )
        assert cli.returncode == 0, cli.stderr.decode(errors="replace")
        assert cli.stdout == b""
        assert cli.stderr == b""
        assert isinstance(planned.get("output_bytes"), bytes)
        assert rendered_plan.read_bytes() == planned["output_bytes"]
        dependency_plan = planned

    _assert_dependency_lock_dataflow(
        lock,
        build_args,
        dockerfile_source,
        dependency_plan,
    )


@pytest.mark.parametrize(
    "malicious_fixture",
    (
        "preassignment",
        "ignored-failure",
        "quoted-python-c",
        "empty-output",
        "wrong-value",
        "floating-install",
    ),
)
def test_dependency_lock_dataflow_rejects_ineffective_consumers(
    malicious_fixture: str,
) -> None:
    if malicious_fixture == "floating-install":
        with pytest.raises(AssertionError, match="upgrade|pin"):
            _assert_no_floating_or_ignored_installs(
                ["RUN pip install --upgrade pip"]
            )
        return

    if malicious_fixture in {"preassignment", "ignored-failure"}:
        use = LockUse(
            paths=("debian.packages.git",),
            values=("1.2.3-locked",),
            consumer="apt",
            operation=r"\bapt-get\s+install\b",
            description="locked git package",
        )
        instruction = (
            'RUN PIN=$LOCKED apt-get install "git=$PIN"'
            if malicious_fixture == "preassignment"
            else 'RUN apt-get install "git=$LOCKED" || :'
        )
        with pytest.raises(AssertionError, match="real operation operands"):
            _assert_build_arg_lock_dataflow(
                (use,), {"LOCKED": "1.2.3-locked"}, [instruction]
            )
        return

    lock = _synthetic_dependency_lock()
    uses = _dependency_lock_uses(lock)
    dependency_uses = tuple(
        use for use in uses if not use.consumer.startswith("from-")
    )
    facts = sorted(
        (path, use.consumer, value)
        for use in dependency_uses
        for path, value in zip(use.paths, use.values, strict=True)
    )
    bindings = [
        {
            "name": f"LOCK_OUTPUT_{index:03d}",
            "consumer": consumer,
            "fact_path": path,
            "value": value,
        }
        for index, (path, consumer, value) in enumerate(facts)
    ]
    plan = {
        "lock_sha256": _sha256_bytes(
            json.dumps(lock, sort_keys=True, separators=(",", ":")).encode()
        ),
        "output_path": "/tmp/ba0-dependency-plan.env",
        "bindings": bindings,
        "output_bytes": "".join(
            f"{binding['name']}={json.dumps(binding['value'])}\n"
            for binding in bindings
        ).encode(),
    }
    expected_message = "exact dependency-plan parser argv"
    if malicious_fixture == "empty-output":
        plan["output_bytes"] = b""
        expected_message = "output_bytes"
    elif malicious_fixture == "wrong-value":
        bindings[0]["value"] = "tampered-lock-value"
        expected_message = "wrong lock value"
    lock_path = "deploy/local-build/app-external-dependencies.v1.json"
    parser = (
        "python3 -c 'pass' scripts/app_artifact.py dependency-plan"
        if malicious_fixture == "quoted-python-c"
        else "python3 scripts/app_artifact.py dependency-plan"
    )
    dockerfile = "\n".join(
        (
            "FROM $BUILDER AS builder",
            "FROM $RUNTIME AS runtime",
            f"COPY {lock_path} {lock_path}",
            (
                f"RUN {parser} --lock {lock_path} "
                "--output /tmp/ba0-dependency-plan.env"
            ),
            "RUN sh /tmp/uv-installer",
        )
    )
    with pytest.raises(AssertionError, match=expected_message):
        _assert_dependency_lock_dataflow(
            lock,
            {
                "BUILDER": lock["base_images"]["builder"]["reference"],
                "RUNTIME": lock["base_images"]["runtime"]["reference"],
            },
            dockerfile,
            plan,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("unknown", "unknown|schema|field"),
        ("floating", "digest|mutable|pinned|sha"),
        ("missing", "duckdb|extension|missing"),
    ),
    ids=("unknown", "floating", "missing-duckdb-extension"),
)
def test_dependency_lock_loader_rejects_unknown_floating_or_missing_facts(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    module = _artifact_module()
    document = _load_json(DEPENDENCY_LOCK_PATH, description="external dependency lock")
    mutated = deepcopy(document)
    if mutation == "unknown":
        mutated["unbounded_fallback"] = True
    elif mutation == "floating":
        mutated["base_images"]["builder"]["reference"] = "golang:1.26-bookworm"
    else:
        del mutated["downloads"]["duckdb"]["extensions"]["excel"]
    path = tmp_path / f"{mutation}.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")

    with pytest.raises(module.ArtifactContractError, match=message):
        module.load_dependency_lock(path)


# BA0-REQ-02/06: deterministic lookup, fail-closed reuse, secrecy, build budget.


def test_lookup_normalizes_candidate_set_and_unique_valid_hit_builds_zero(
    tmp_path: Path,
) -> None:
    module = _artifact_module()
    runner = _selector_runner(candidates=f"{IMAGE_ID}\n{IMAGE_ID}\n")

    receipt = _selector_call(module, tmp_path, runner)

    assert receipt["selector"] == "REUSE"
    assert receipt["build_invocations"] == 0
    assert receipt["candidate_image_ids"] == [IMAGE_ID]
    assert receipt["image_id"] == IMAGE_ID
    assert receipt["artifact_identity"] == ARTIFACT_IDENTITY
    assert receipt["build_source_head"] == BUILD_SOURCE_HEAD
    assert receipt["integration_head"] == INTEGRATION_HEAD
    assert sum(_is_docker_build(call.arguments) for call in runner.calls) == 0
    query_calls = [call for call in runner.calls if "ls" in call.arguments]
    inspect_calls = [call for call in runner.calls if "inspect" in call.arguments]
    assert len(query_calls) == len(inspect_calls) == 1
    _assert_exact_lookup_query(query_calls[0])
    _assert_exact_candidate_inspect(inspect_calls[0], IMAGE_ID)
    assert all(call.arguments[:3] == ("docker", "--context", CONTEXT) for call in runner.calls)


def test_lookup_zero_candidates_is_only_miss_and_builds_once(tmp_path: Path) -> None:
    module = _artifact_module()
    runner = _selector_runner(candidates="")

    receipt = _selector_call(module, tmp_path, runner)

    assert receipt["selector"] == "BUILD_AFFECTED"
    assert receipt["build_invocations"] == 1
    assert receipt["candidate_image_ids"] == []
    assert receipt["image_id"] == IMAGE_ID
    build_calls = [call for call in runner.calls if _is_docker_build(call.arguments)]
    assert len(build_calls) == 1
    built_labels = _effective_build_labels(
        build_calls[0].arguments, build_calls[0].cwd
    )
    assert REQUIRED_LABELS.items() <= built_labels.items()
    tags = _docker_option_values(build_calls[0].arguments, "--tag", short="-t")
    assert len(tags) == 1
    repository, separator, tag = tags[0].rpartition(":")
    assert separator and repository == APP_REPOSITORY
    assert tag and tag.lower() not in {"latest", "main", "dev", "runtime"}
    assert ARTIFACT_IDENTITY.removeprefix("sha256:") in tag
    assert _docker_option_values(build_calls[0].arguments, "--platform") == [PLATFORM]
    assert _docker_option_values(build_calls[0].arguments, "--target") == ["runtime"]
    assert build_calls[0].arguments.count("--iidfile") == 1
    iidfile_index = build_calls[0].arguments.index("--iidfile")
    assert iidfile_index + 1 < len(build_calls[0].arguments)
    assert Path(build_calls[0].arguments[iidfile_index + 1]).is_absolute()
    query_calls = [call for call in runner.calls if "ls" in call.arguments]
    assert len(query_calls) == 1
    _assert_exact_lookup_query(query_calls[0])
    post_build_inspects = [call for call in runner.calls if "inspect" in call.arguments]
    assert len(post_build_inspects) == 1
    _assert_exact_candidate_inspect(post_build_inspects[0], IMAGE_ID)
    assert runner.calls.index(query_calls[0]) < runner.calls.index(build_calls[0])
    assert runner.calls.index(build_calls[0]) < runner.calls.index(post_build_inspects[0])
    assert receipt["labels"] == REQUIRED_LABELS
    assert receipt["platform"] == PLATFORM


@pytest.mark.parametrize(
    ("inspect_stdout", "inspect_returncode", "message"),
    tuple(
        pytest.param(inspect_stdout, returncode, message, id=case)
        for case, inspect_stdout, returncode, message in _invalid_image_inspections()
    ),
)
def test_lookup_miss_post_build_invalid_inspect_fails_closed_after_one_build(
    tmp_path: Path,
    inspect_stdout: str,
    inspect_returncode: int,
    message: str,
) -> None:
    module = _artifact_module()
    runner = _selector_runner(
        candidates="",
        inspect_stdout=inspect_stdout,
        inspect_returncode=inspect_returncode,
    )
    evidence = tmp_path / "selector-receipt.json"

    with pytest.raises(module.ArtifactContractError, match=message):
        module.select_or_build_app(
            repo_root=REPO_ROOT,
            identity=_identity_record(),
            evidence_out=evidence,
            runner=runner,
            secret_values={},
            real_build_budget_remaining=1,
        )

    query_calls = [call for call in runner.calls if "ls" in call.arguments]
    build_calls = [call for call in runner.calls if _is_docker_build(call.arguments)]
    inspect_calls = [call for call in runner.calls if "inspect" in call.arguments]
    assert len(query_calls) == len(build_calls) == len(inspect_calls) == 1
    _assert_exact_lookup_query(query_calls[0])
    _assert_exact_candidate_inspect(inspect_calls[0], IMAGE_ID)
    assert runner.calls.index(query_calls[0]) < runner.calls.index(build_calls[0])
    assert runner.calls.index(build_calls[0]) < runner.calls.index(inspect_calls[0])
    if evidence.exists():
        failure_receipt = json.loads(evidence.read_text(encoding="utf-8"))
        assert failure_receipt.get("status") != "PASS"


@pytest.mark.parametrize(
    ("case", "candidates", "inspect_stdout", "inspect_returncode", "message"),
    (
        *tuple(
            pytest.param(
                case,
                IMAGE_ID + "\n",
                inspect_stdout,
                returncode,
                message,
                id=case,
            )
            for case, inspect_stdout, returncode, message in _invalid_image_inspections()
        ),
        pytest.param(
            "conflict",
            f"sha256:{'e' * 64}\n{IMAGE_ID}\n{IMAGE_ID}\n",
            _image_inspect(),
            0,
            "conflict|multiple|candidate",
            id="conflict",
        ),
    ),
)
def test_lookup_nonempty_invalid_conflict_or_inspect_error_fails_closed_build_zero(
    tmp_path: Path,
    case: str,
    candidates: str,
    inspect_stdout: str,
    inspect_returncode: int,
    message: str,
) -> None:
    module = _artifact_module()
    runner = _selector_runner(
        candidates=candidates,
        inspect_stdout=inspect_stdout,
        inspect_returncode=inspect_returncode,
    )

    with pytest.raises(module.ArtifactContractError, match=message):
        _selector_call(module, tmp_path, runner)

    assert sum(_is_docker_build(call.arguments) for call in runner.calls) == 0
    query_calls = [call for call in runner.calls if "ls" in call.arguments]
    assert len(query_calls) == 1
    _assert_exact_lookup_query(query_calls[0])
    inspect_calls = [call for call in runner.calls if "inspect" in call.arguments]
    if case == "conflict":
        assert inspect_calls == []
    else:
        assert len(inspect_calls) == 1
        _assert_exact_candidate_inspect(inspect_calls[0], IMAGE_ID)


def test_lookup_query_error_is_not_miss_and_builds_zero(tmp_path: Path) -> None:
    module = _artifact_module()
    runner = _selector_runner(candidates="", query_returncode=1)

    with pytest.raises(module.ArtifactContractError, match="query|lookup"):
        _selector_call(module, tmp_path, runner)

    assert sum(_is_docker_build(call.arguments) for call in runner.calls) == 0
    assert len(runner.calls) == 1
    _assert_exact_lookup_query(runner.calls[0])


def test_lookup_secret_canary_never_enters_argv_trace_labels_receipt_or_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _artifact_module()
    secret_variants = (
        {},
        {"GOPRIVATE": CANARY_SECRET, "repository_token": CANARY_SECRET},
        {"GOPRIVATE": CANARY_SECRET_B, "repository_token": CANARY_SECRET_B},
    )
    runners: list[FakeRunner] = []
    receipts: list[dict[str, Any]] = []
    receipt_files: list[str] = []
    for index, secrets in enumerate(secret_variants):
        case_path = tmp_path / f"secret-variant-{index}"
        case_path.mkdir()
        runner = _selector_runner(candidates="")
        runners.append(runner)
        receipts.append(_selector_call(module, case_path, runner, secrets=secrets))
        receipt_files.append(
            (case_path / "selector-receipt.json").read_text(encoding="utf-8")
        )
    captured = capsys.readouterr()

    invariant_keys = (
        "selector",
        "build_invocations",
        "artifact_identity",
        "image_id",
        "build_source_head",
        "integration_head",
        "manifest_sha256",
        "dependency_lock_sha256",
        "target",
        "platform",
        "labels",
    )
    projections = [
        {key: receipt[key] for key in invariant_keys} for receipt in receipts
    ]
    assert projections[0] == projections[1] == projections[2]
    surfaces = _json_text(
        {
            "calls": [
                {
                    "arguments": call.arguments,
                    "cwd": str(call.cwd),
                    "kwargs": call.kwargs,
                }
                for runner in runners
                for call in runner.calls
            ],
            "receipts": receipts,
            "receipt_files": receipt_files,
            "labels": [receipt["labels"] for receipt in receipts],
            "identity": [receipt["artifact_identity"] for receipt in receipts],
            "stdout": captured.out,
            "stderr": captured.err,
        }
    )
    for canary in (CANARY_SECRET, CANARY_SECRET_B):
        assert canary not in surfaces
        assert _sha256_bytes(canary.encode()) not in surfaces
    assert all(receipt["build_invocations"] == 1 for receipt in receipts)


def test_lookup_miss_with_exhausted_budget_stops_before_mutation(
    tmp_path: Path,
) -> None:
    module = _artifact_module()
    runner = _selector_runner(candidates="")

    with pytest.raises(module.ArtifactContractError, match="STOP|budget|RETURN_TO_USER"):
        _selector_call(module, tmp_path, runner, budget=0)

    assert sum(_is_docker_build(call.arguments) for call in runner.calls) == 0


def _executable_text(source: str) -> str:
    return "\n".join(
        line.split("#", 1)[0].rstrip()
        for line in source.splitlines()
        if line.split("#", 1)[0].strip()
    )


def _shell_function_body(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(name)}\(\)\s*\{{\s*\n(?P<body>.*?)^\}}",
        source,
    )
    assert match is not None, f"missing shell function {name}"
    return _executable_text(match.group("body"))


def _shell_command_tokens(
    source: str, *, preserve_wrappers: bool = False
) -> list[list[str]]:
    cleaned = "\n".join(
        line.lstrip().lstrip("@+-").strip()
        for line in _executable_text(source).replace("\\\n", " ").splitlines()
    )
    lexer = shlex.shlex(
        cleaned.replace("\n", " ; "), posix=True, punctuation_chars=";&|"
    )
    lexer.whitespace_split = True
    lexer.commenters = ""
    commands: list[list[str]] = []
    current: list[str] = []
    for token in lexer:
        if token and set(token) <= {";", "&", "|"}:
            if current:
                commands.append(current)
                current = []
        else:
            current.append(token)
    if current:
        commands.append(current)

    normalized: list[list[str]] = []
    for command in commands:
        if not preserve_wrappers:
            if command[:1] == ["env"]:
                command = command[1:]
            while command and re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*=.*", command[0]
            ):
                command = command[1:]
        if command:
            normalized.append(command)
    return normalized


def _tokens_are_docker_build(tokens: list[str]) -> bool:
    if not tokens or Path(tokens[0]).name != "docker":
        return False
    index = 1
    while index < len(tokens) and tokens[index].startswith("-"):
        if tokens[index] in {"--context", "-c", "--host", "-H", "--config"}:
            index += 2
        else:
            index += 1
    return tokens[index : index + 1] == ["build"] or tokens[
        index : index + 2
    ] == ["buildx", "build"]


def _assert_no_docker_build_commands(source: str) -> None:
    executable = _executable_text(source)
    hidden = re.compile(
        r"(?:`[^`]*|\$\$?\([^)]*)\bdocker\b[^;|&`)\n]*"
        r"\b(?:buildx\s+build|build)\b",
        re.S,
    )
    assert hidden.search(executable) is None, (
        "docker build cannot be hidden in command or make-shell substitution"
    )
    assert all(
        not _tokens_are_docker_build(tokens)
        for tokens in _shell_command_tokens(executable)
    ), "direct docker build/buildx build is forbidden"


def _assert_no_docker_authority(source: str) -> None:
    executable = _executable_text(source)
    hidden = re.compile(
        r"(?:`[^`]*\bdocker\b[^`]*`|\$\$?\([^)]*\bdocker\b[^)]*\))",
        re.S,
    )
    assert hidden.search(executable) is None, (
        "docker authority cannot be hidden in command or make-shell substitution"
    )
    for tokens in _shell_command_tokens(executable, preserve_wrappers=True):
        while tokens:
            if tokens[0] in {"if", "then", "elif", "while", "until", "do", "!"}:
                tokens = tokens[1:]
                continue
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0]):
                tokens = tokens[1:]
                continue
            wrapper = Path(tokens[0]).name
            if wrapper == "env":
                tokens = tokens[1:]
                while tokens:
                    option = tokens[0]
                    if option == "--":
                        tokens = tokens[1:]
                        break
                    if option in {"-S", "--split-string"} or option.startswith(
                        "--split-string="
                    ):
                        raise AssertionError(
                            "Docker authority guard forbids env split-string"
                        )
                    if option in {"-i", "--ignore-environment"}:
                        tokens = tokens[1:]
                    elif option in {"-u", "--unset", "-C", "--chdir"}:
                        assert len(tokens) >= 2, f"env {option} lacks a value"
                        tokens = tokens[2:]
                    elif option.startswith(("--unset=", "--chdir=")):
                        tokens = tokens[1:]
                    elif re.fullmatch(
                        r"[A-Za-z_][A-Za-z0-9_]*=.*", option
                    ):
                        tokens = tokens[1:]
                    elif option.startswith("-"):
                        raise AssertionError(
                            f"Docker authority guard rejects unsupported env option {option}"
                        )
                    else:
                        break
                continue
            if wrapper not in {"command", "exec"}:
                break
            tokens = tokens[1:]
            while tokens:
                if tokens[0] == "--":
                    tokens = tokens[1:]
                    break
                takes_value = (
                    wrapper == "env"
                    and tokens[0] in {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}
                ) or (wrapper == "exec" and tokens[0] == "-a")
                if takes_value:
                    tokens = tokens[2:]
                elif tokens[0].startswith("-") or re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0]
                ):
                    tokens = tokens[1:]
                else:
                    break
        if tokens and Path(tokens[0]).name in {"sh", "bash", "zsh"}:
            assert not any(
                re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", option)
                for option in tokens[1:]
            ), "Docker authority guard forbids secondary shell -c"
        assert not tokens or Path(tokens[0]).name not in {"docker", "sudo"}, (
            "public app build entry must not hold direct Docker authority"
        )


def test_shell_guard_rejects_hidden_docker_build_bypasses() -> None:
    for bypass in (
        "`docker build .`",
        "$(docker --context shadow-context buildx build .)",
        "$$(docker build .)",
        "$(shell docker buildx build .)",
    ):
        with pytest.raises(AssertionError, match="substitution"):
            _assert_no_docker_build_commands(bypass)
    for bypass in (
        "command docker image inspect sha256:deadbeef",
        'printf "$$(docker image inspect sha256:deadbeef)"',
        "docker --log-level debug --context shadow-context buildx build .",
        "env -- docker image inspect sha256:deadbeef",
        "env -i docker image inspect sha256:deadbeef",
        "env -u NAME docker image inspect sha256:deadbeef",
        "env -S 'docker image inspect sha256:deadbeef'",
        "sh -c 'docker image inspect sha256:deadbeef'",
    ):
        with pytest.raises(AssertionError, match="Docker authority|substitution"):
            _assert_no_docker_authority(bypass)


def test_public_app_build_entry_has_one_authority_and_makefile_has_no_naked_build() -> None:
    script = BUILD_IMAGES_PATH.read_text(encoding="utf-8")
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")
    app_body = _shell_function_body(script, "build_app_image")

    assert "--build-source-head" in app_body
    assert "--evidence-out" in app_body
    assert "scripts/app_artifact.py" in app_body
    assert CONTEXT in app_body
    _assert_no_docker_build_commands(app_body)
    _assert_no_docker_authority(app_body)

    executable_script = _executable_text(script)
    app_branch = re.search(
        r'(?ms)if \[ "\$BUILD_APP" = true \]; then(?P<body>.*?)^fi$',
        executable_script,
    )
    assert app_branch is not None
    branch_body = app_branch.group("body")
    _assert_no_docker_build_commands(branch_body)
    _assert_no_docker_authority(branch_body)
    branch_commands = _shell_command_tokens(branch_body)
    branch_delegates = [tokens for tokens in branch_commands if tokens == ["build_app_image"]]
    assert len(branch_delegates) == 1
    harmless_setup = {
        "set",
        "export",
        "test",
        "[",
        ":",
        "cd",
        "umask",
        "printf",
        "echo",
    }
    assert all(
        tokens in branch_delegates or tokens[0] in harmless_setup
        for tokens in branch_commands
    ), "BUILD_APP branch may only delegate once plus harmless shell setup"

    app_target = re.search(
        r"(?ms)^docker-build-app:\n(?P<body>(?:\t.*\n)+)", makefile
    )
    assert app_target is not None
    target_body = _executable_text(app_target.group("body")).replace("\\\n", " ")
    _assert_no_docker_build_commands(target_body)
    _assert_no_docker_authority(target_body)
    recipe_commands = _shell_command_tokens(target_body)
    delegates = [
        tokens
        for tokens in recipe_commands
        if tokens[0] == "./scripts/build_images.sh"
    ]
    assert len(delegates) == 1 and "--app" in delegates[0]
    assert all(
        tokens in delegates or tokens[0] in harmless_setup for tokens in recipe_commands
    ), "docker-build-app may only delegate once plus harmless shell setup"


# BA0-REQ-05/06: standalone exact-image artifact smoke and zero effects.


def _compose_script_operand(value: object, *, healthcheck: bool) -> str:
    assert isinstance(value, list), "smoke command must use executable argv form"
    if healthcheck:
        assert len(value) == 2 and value[0] == "CMD-SHELL", (
            "healthcheck must have exactly one CMD-SHELL script operand"
        )
        script = value[1]
    else:
        assert len(value) == 3 and value[:2] in (["/bin/sh", "-ec"], ["/bin/sh", "-ce"]), (
            "entrypoint must have exactly one /bin/sh -ec script operand"
        )
        script = value[2]
    assert isinstance(script, str) and script.strip()
    return script


def _assert_fail_fast_healthcheck(script: str) -> None:
    assert re.match(
        r"^\s*set\s+-[a-z]*e[a-z]*(?:\s+-[a-z]+)*\s*(?:;|\n)", script
    ), "healthcheck script must begin with set -e fail-fast semantics"
    assert "||" not in script, "healthcheck checks must not ignore failure with ||"
    assert not re.search(
        r"(?:;|&&|\|\|)\s*(?:true|:|exit\s+0)\s*$", script.strip()
    ), "healthcheck must not mask checks with unconditional trailing success"


def test_d3_exact_image_compose_is_single_service_read_only_and_standalone() -> None:
    document = yaml.safe_load(
        EXACT_COMPOSE_PATH.read_text(encoding="utf-8")
        if EXACT_COMPOSE_PATH.is_file()
        else pytest.fail(
            "planned BA0 standalone Compose missing: "
            "deploy/local-build/docker-compose.app-exact.yml"
        )
    )
    assert isinstance(document, dict)
    assert set(document) <= {"services"}
    assert set(document["services"]) == {"app-smoke"}
    service = document["services"]["app-smoke"]

    assert service["pull_policy"] == "never"
    assert "BA0_APP_IMAGE" in service["image"]
    assert service["network_mode"] == "none"
    assert service["read_only"] is True
    assert "/tmp" in service["tmpfs"]
    assert str(service["environment"]["AUTO_MIGRATE"]).lower() == "false"
    for forbidden in (
        "build",
        "ports",
        "volumes",
        "container_name",
        "env_file",
        "depends_on",
        "networks",
        "links",
    ):
        assert forbidden not in service

    entrypoint = _compose_script_operand(service["entrypoint"], healthcheck=False)
    healthcheck = _compose_script_operand(
        service["healthcheck"]["test"], healthcheck=True
    )
    _assert_fail_fast_healthcheck(healthcheck)
    for command in (entrypoint, healthcheck):
        assert re.search(r"\btest\s+-x\s+['\"]?/app/WeKnora\b", command)
        assert re.search(r"\bldd\s+['\"]?/app/WeKnora\b", command)
        assert "not found" in command.lower() and re.search(r"\bgrep\b", command)
        assert "!" in command or re.search(r"\bexit\s+1\b", command)
        assert not _has_ignored_failure(command)

    combined_commands = f"{entrypoint}\n{healthcheck}"
    for required_path in (
        "/app/WeKnora",
        "/app/config",
        "/app/scripts",
        "/app/migrations",
        "/app/dataset/samples",
        "/app/skills/preloaded",
        "/home/appuser/.duckdb",
    ):
        assert re.search(
            rf"\btest\s+-[derx]\s+['\"]?{re.escape(required_path)}\b",
            combined_commands,
        )
    assert re.search(
        r"\bsleep\s+infinity\b|\btail\s+-f\s+/dev/null\b|"
        r"\bwhile\s+(?::|true)\s*;?\s*do\b.*\bsleep\b.*\bdone\b",
        entrypoint,
        re.S,
    ), "entrypoint must keep the verified container alive"

    public = _json_text(document).lower()
    assert "http" not in public
    for forbidden in (
        "postgres",
        "redis",
        "docreader",
        "provider",
        "8081",
    ):
        assert forbidden not in public


def _assert_compose_argv(call: RecordedCall, *, action: str) -> Path:
    arguments = call.arguments
    env_path = Path(arguments[arguments.index("--env-file") + 1])
    assert arguments == D3Runner._compose_arguments(env_path, action)
    return env_path


def _is_docker_pull(arguments: tuple[str, ...]) -> bool:
    tail = arguments[3:]
    if tail[:1] == ("pull",) or tail[:2] == ("image", "pull"):
        return True
    if tail[:1] == ("compose",):
        return "pull" in tail and "--pull" not in tail
    return False


def _d3_mutation_calls(runner: D3Runner) -> list[RecordedCall]:
    mutations: list[RecordedCall] = []
    for call in runner.calls:
        tail = call.arguments[3:]
        if _is_docker_build(call.arguments) or _is_docker_pull(call.arguments):
            mutations.append(call)
        elif tail[:1] in (("network",), ("volume",)):
            mutations.append(call)
        elif tail[:1] == ("compose",) and ("up" in tail or "down" in tail):
            mutations.append(call)
    return mutations


def test_d3_exact_image_runner_order_and_exact_no_build_no_pull_argv(
    tmp_path: Path,
) -> None:
    module = _smoke_module()
    runner = D3Runner()

    receipt = _d3_call(module, tmp_path, runner)

    assert runner.events == [
        "image-inspect",
        "compose-config",
        "project-collision",
        "compose-up",
        "runtime-inspect",
        "cleanup",
    ]
    config_call = next(call for call in runner.calls if "config" in call.arguments)
    up_call = next(call for call in runner.calls if "up" in call.arguments)
    down_call = next(call for call in runner.calls if "down" in call.arguments)
    config_env = _assert_compose_argv(config_call, action="config")
    up_env = _assert_compose_argv(up_call, action="up")
    down_env = _assert_compose_argv(down_call, action="down")
    assert config_env == up_env == down_env
    assert runner.env_files
    assert all(mode == 0o600 for _, mode, _ in runner.env_files)
    assert all(
        content == f"BA0_APP_IMAGE={IMAGE_ID}\n"
        for _, _, content in runner.env_files
    )
    assert receipt["status"] == "PASS"
    assert receipt["scope"] == "CONTAINER_ARTIFACT_SMOKE"
    assert runner.receipt_existed_at_cleanup is False
    assert sum(_is_docker_build(call.arguments) for call in runner.calls) == 0
    assert sum(_is_docker_pull(call.arguments) for call in runner.calls) == 0


def test_d3_invalid_receipt_is_rejected_before_runner_or_mutation(tmp_path: Path) -> None:
    module = _smoke_module()
    receipt_path = tmp_path / "invalid-d2.json"
    receipt_path.write_text(
        json.dumps({"status": "PASS", "image_id": "wechatopenai/weknora-app:latest"}),
        encoding="utf-8",
    )
    runner = D3Runner()

    with pytest.raises(module.ArtifactSmokeError, match="receipt|image|sha256"):
        module.run_exact_image_smoke(
            repo_root=REPO_ROOT,
            d2_receipt_path=receipt_path,
            evidence_out=tmp_path / "d3.json",
            nonce="0123456789abcdef",
            runner=runner,
        )

    assert runner.calls == []
    assert _d3_mutation_calls(runner) == []


@pytest.mark.parametrize(
    ("case", "inspect", "message"),
    (
        ("image", _image_inspect(image_id="sha256:" + "e" * 64), "image|identity"),
        (
            "label",
            _image_inspect(
                labels={
                    **REQUIRED_LABELS,
                    "io.insurancekb.app.build-source-head": "f" * 40,
                }
            ),
            "label|build.source",
        ),
        ("platform", _image_inspect(architecture="amd64"), "arm64|arch|platform"),
    ),
    ids=("image-id", "label", "platform"),
)
def test_d3_image_preflight_failure_has_zero_mutations(
    tmp_path: Path,
    case: str,
    inspect: str,
    message: str,
) -> None:
    del case
    module = _smoke_module()
    runner = D3Runner(source_inspect=inspect)

    with pytest.raises(module.ArtifactSmokeError, match=message):
        _d3_call(module, tmp_path, runner)

    assert runner.events == ["image-inspect"]
    assert _d3_mutation_calls(runner) == []


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("ports", "port|topology|standalone"),
        ("trailing-decoy", "argv|operand|entrypoint|smoke|command"),
        ("masking-healthcheck", "health|fail.fast|mask|command"),
    ),
)
def test_d3_static_topology_or_argv_failure_precedes_collision_with_zero_mutations(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    module = _smoke_module()
    rendered = _valid_rendered_compose()
    service = rendered["services"]["app-smoke"]
    if mutation == "ports":
        service["ports"] = ["8081:8080"]
    elif mutation == "trailing-decoy":
        assert isinstance(service["entrypoint"], list)
        service["entrypoint"] = [
            *service["entrypoint"],
            "test -x /app/WeKnora && ldd /app/WeKnora",
        ]
    else:
        healthcheck = service["healthcheck"]["test"]
        assert isinstance(healthcheck, list) and len(healthcheck) == 2
        original = healthcheck[1]
        healthcheck[1] = re.sub(
            r"(\btest\s+-x\s+['\"]?/app/WeKnora\b)",
            r"\1 || echo ignored",
            original,
            count=1,
        )
        assert healthcheck[1] != original
    runner = D3Runner(rendered_compose=rendered)

    with pytest.raises(module.ArtifactSmokeError, match=message):
        _d3_call(module, tmp_path, runner)

    assert runner.events == ["image-inspect", "compose-config"]
    assert _d3_mutation_calls(runner) == []


def test_d3_project_collision_fails_before_up_with_zero_mutations(tmp_path: Path) -> None:
    module = _smoke_module()
    runner = D3Runner(collision=True)

    with pytest.raises(module.ArtifactSmokeError, match="collision|project"):
        _d3_call(module, tmp_path, runner)

    assert runner.events == ["image-inspect", "compose-config", "project-collision"]
    assert _d3_mutation_calls(runner) == []


def test_d3_runtime_failure_still_cleans_up_before_failure_receipt(tmp_path: Path) -> None:
    module = _smoke_module()
    d2_receipt_path = tmp_path / "d2.json"
    evidence_path = tmp_path / "d3-failure.json"
    _d2_receipt(d2_receipt_path)
    runner = D3Runner(runtime_returncode=1)
    runner.evidence_path = evidence_path

    with pytest.raises(module.ArtifactSmokeError, match="runtime|inspect|health"):
        module.run_exact_image_smoke(
            repo_root=REPO_ROOT,
            d2_receipt_path=d2_receipt_path,
            evidence_out=evidence_path,
            nonce="0123456789abcdef",
            runner=runner,
        )

    assert runner.events[-2:] == ["runtime-inspect", "cleanup"]
    assert evidence_path.is_file()
    failure = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert failure["status"] == "FAIL"
    assert failure["cleanup"] == "PASS"
    assert runner.receipt_existed_at_cleanup is False


def test_d3_receipt_proves_exact_runtime_and_all_forbidden_effects_zero(
    tmp_path: Path,
) -> None:
    module = _smoke_module()
    runner = D3Runner()

    receipt = _d3_call(module, tmp_path, runner)

    assert receipt["image_id"] == IMAGE_ID
    assert receipt["runtime_image_id"] == IMAGE_ID
    assert receipt["build_invocations"] == 0
    assert receipt["pull_invocations"] == 0
    assert receipt["cleanup"] == "PASS"
    assert receipt["effects"] == {
        "networks": 0,
        "published_ports": 0,
        "volumes": 0,
        "dependencies": 0,
        "provider_model": 0,
        "business_db": 0,
        "production_8081": 0,
        "production_active": 0,
        "g2": 0,
    }
    assert all(not _is_docker_build(call.arguments) for call in runner.calls)
