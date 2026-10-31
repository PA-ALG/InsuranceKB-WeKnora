"""App build: the closed input manifest and the Go / embed input resolver."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tests.service_shell.app_build.contract_helpers import _write_synthetic_contract
from tests.service_shell.app_build.helpers import (
    MANIFEST_PATH,
    PLATFORM,
    REPO_ROOT,
    REQUIRED_COPY_ROOTS,
    REQUIRED_CRITICAL_INPUTS,
    _artifact_module,
    _json_text,
    _load_json,
)
from tests.service_shell.app_build.resolver_helpers import _identity_runner


def _record_value(record: object, name: str) -> Any:
    if isinstance(record, Mapping):
        return record[name]
    return getattr(record, name)


def _resolved_paths(records: object) -> set[str]:
    assert not isinstance(records, (str, bytes, Mapping))
    assert isinstance(records, Iterable)
    paths: set[str] = set()
    for record in records:
        value = record if isinstance(record, str) else _record_value(record, "path")
        paths.add(Path(str(value)).as_posix().removeprefix("./"))
    return paths


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
        "go_build_tags": ["anydoc"],
        "components": ["anydoc", "browserskill"],
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
    go_list_calls = [call for call in runner.calls if call.arguments[0:2] == ("go", "list")]
    assert len(go_list_calls) == 1
    assert go_list_calls[0].arguments[:6] == (
        "go",
        "list",
        "-tags",
        "anydoc",
        "-deps",
        "-json",
    )
    assert set(go_list_calls[0].arguments[6:]) == {
        "./cmd/server",
        "./cmd/download/duckdb",
    }
    assert go_list_calls[0].cwd == REPO_ROOT
    go_list_env = go_list_calls[0].kwargs.get("env")
    assert isinstance(go_list_env, Mapping)
    assert {name: go_list_env.get(name) for name in ("GOOS", "GOARCH", "CGO_ENABLED")} == {
        "GOOS": "linux",
        "GOARCH": "arm64",
        "CGO_ENABLED": "1",
    }
    assert all(call.arguments[0] != "docker" for call in runner.calls)


def test_manifest_resolver_excludes_generated_anydoc_outputs(tmp_path: Path) -> None:
    module = _artifact_module()
    repo_root = tmp_path / "repository"
    manifest_path, _ = _write_synthetic_contract(repo_root)
    generated = {
        "third_party/anydoc-go/target/release/libanydoc_go.a",
        "third_party/anydoc-go/lib/linux_arm64_gnu/libanydoc_go.a",
        "third_party/anydoc-go/patched-anydoc/src/lib.rs",
    }
    for relative in generated:
        path = repo_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("generated\n", encoding="utf-8")

    resolved = module.resolve_inputs(
        repo_root,
        module.load_manifest(manifest_path),
        runner=_identity_runner(repo_root),
    )

    assert generated.isdisjoint(_resolved_paths(resolved))


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
    unknown_path.write_text(json.dumps({**document, "silent_extra_input": True}), encoding="utf-8")
    with pytest.raises(module.ArtifactContractError, match="unknown|schema|field"):
        module.load_manifest(unknown_path)

    escaped = deepcopy(document)
    escaped["required_paths"] = [*escaped["required_paths"], "../outside"]
    escaped_path = tmp_path / "escaped.json"
    escaped_path.write_text(json.dumps(escaped), encoding="utf-8")
    with pytest.raises(module.ArtifactContractError, match="repository|escape|outside"):
        module.load_manifest(escaped_path)
