"""App build contracts: fake `go list` streams and the identity runner."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tests.service_shell.app_build.helpers import BUILD_SOURCE_HEAD, FakeRunner, _completed


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

    packages: list[dict[str, Any]] = [
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
        packages.append(local_package("internal/newtopsentinel", ["sentinel.go"], ["context"]))
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
        assert arguments and arguments[0] != "docker", "identity/preflight must not invoke Docker"
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
