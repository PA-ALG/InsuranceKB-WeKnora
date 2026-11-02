"""App build contracts: synthetic repository contracts, identity records and lock files."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tests.service_shell.app_build.helpers import (
    ARTIFACT_IDENTITY,
    BUILD_SOURCE_HEAD,
    INTEGRATION_HEAD,
    LOCK_SHA256,
    MANIFEST_SHA256,
    PLATFORM,
    REQUIRED_COPY_ROOTS,
    REQUIRED_CRITICAL_INPUTS,
    REQUIRED_LABELS,
    SOURCE_DATE_EPOCH,
)


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
        "external_dependency_lock": ("deploy/local-build/app-external-dependencies.v1.json"),
        "build_contract": {
            "target": "runtime",
            "platform": PLATFORM,
            "goos": "linux",
            "goarch": "arm64",
            "cgo_enabled": True,
            "go_build_tags": ["anydoc"],
            "components": ["anydoc", "browserskill"],
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
        "LICENSE": "fixture license\n",
        "THIRD_PARTY_NOTICES.md": "fixture notices\n",
        "licenses/sources/modules.tsv": "fixture/module v1.0.0 " + "a" * 64 + "\n",
        "config/app.yml": "mode: test\n",
        "contracts/candidate_bundle.schema.json": "{}\n",
        "scripts/docker-entrypoint.sh": "#!/bin/sh\n",
        "migrations/000001.sql": "select 1;\n",
        "dataset/samples/sample.txt": "sample\n",
        "cmd/server/main.go": (
            'package main\n\nimport _ "github.com/Tencent/WeKnora/internal/newtopsentinel"\n'
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
            'package assets\n\nimport _ "embed"\n\n//go:embed asr_test.wav\nvar ASR []byte\n'
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
        "third_party/anydoc-go/Cargo.lock": "# fixture lock\n",
        "third_party/anydoc-go/Cargo.toml": "[package]\nname='anydoc-go'\nversion='0.1.9'\n",
        "third_party/anydoc-go/go.mod": "module github.com/firecrawl/anydoc/go\n",
        "third_party/anydoc-go/anydoc.go": "package anydoc\n",
        "third_party/anydoc-go/src/lib.rs": "pub fn fixture() {}\n",
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
            "browserskill": {
                "reference": "node:24-bookworm-slim@sha256:" + "c" * 64,
            },
            "rust": {
                "reference": "rust:1.90.0-bookworm@sha256:" + "d" * 64,
            },
            "runtime": {
                "reference": "debian:12.12-slim@sha256:" + "4" * 64,
            },
        },
        "toolchains": {"rust": "1.90.0"},
        "debian": {
            "repositories": {
                "debian": {
                    "snapshot": ("https://snapshot.debian.org/archive/debian/20260801T000000Z/"),
                    "release_sha256": "5" * 64,
                },
                "debian-security": {
                    "snapshot": (
                        "https://snapshot.debian.org/archive/debian-security/20260801T000000Z/"
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
                        "cmake",
                        "pkg-config",
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
            "anydoc": {
                "version": "0.1.9",
                "platform": "source",
                "origin": "https://crates.io/api/v1/crates/anydoc/0.1.9/download",
                "sha256": "c" * 64,
            },
            "browserskill": {
                "version": "0.3.1",
                "source_commit": "d" * 40,
                "platform": "source",
                "origin": "https://codeload.github.com/Tencent/BrowserSkill/tar.gz/" + "d" * 40,
                "sha256": "d" * 64,
            },
            "pnpm": {
                "version": "10.17.0",
                "platform": "source",
                "origin": "https://registry.npmjs.org/pnpm/-/pnpm-10.17.0.tgz",
                "sha256": "e" * 64,
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
        "version": "v1.2.3",
        "commit_id": BUILD_SOURCE_HEAD,
        "source_date_epoch": SOURCE_DATE_EPOCH,
        "build_time": datetime.fromtimestamp(SOURCE_DATE_EPOCH, tz=UTC).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        ),
        "target": "runtime",
        "platform": PLATFORM,
        "labels": dict(REQUIRED_LABELS),
    }
