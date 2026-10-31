"""App build: canonical identity, drift scope and the secret canary."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from tests.service_shell.app_build.contract_helpers import _write_synthetic_contract
from tests.service_shell.app_build.helpers import (
    BUILD_SOURCE_HEAD,
    CANARY_SECRET,
    CANARY_SECRET_B,
    DEPENDENCY_LOCK_PATH,
    INTEGRATION_HEAD,
    MANIFEST_PATH,
    REPO_ROOT,
    _artifact_module,
    _completed,
    _json_text,
    _sha256_bytes,
)
from tests.service_shell.app_build.resolver_helpers import _go_list_stream, _identity_runner


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


def test_identity_drift_scope_ignores_ba0_receipts_but_catches_new_go_source(
    tmp_path: Path,
) -> None:
    module = _artifact_module()
    repo_root = tmp_path / "repository"
    manifest_path, lock_path = _write_synthetic_contract(repo_root)
    subprocess.run(("git", "init", "-q"), cwd=repo_root, check=True)
    subprocess.run(("git", "add", "."), cwd=repo_root, check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=BA0 Test",
            "-c",
            "user.email=ba0-test@example.invalid",
            "commit",
            "-q",
            "-m",
            "fixture",
        ),
        cwd=repo_root,
        check=True,
    )
    source_head = subprocess.check_output(
        ("git", "rev-parse", "HEAD"), cwd=repo_root, text=True
    ).strip()

    def runner(
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        if arguments[:2] == ("go", "list"):
            return _completed(arguments, stdout=_go_list_stream(repo_root))
        return subprocess.run(
            arguments,
            cwd=cwd,
            capture_output=capture_output,
            text=text,
            env=env,
            check=False,
        )

    arguments = {
        "repo_root": repo_root,
        "manifest_path": manifest_path,
        "dependency_lock_path": lock_path,
        "build_source_head": source_head,
        "integration_head": source_head,
        "runner": runner,
        "effective_build_args": {
            "CGO_ENABLED": "1",
            "GOOS": "linux",
            "GOARCH": "arm64",
        },
        "environment": {},
    }
    before = module.canonical_identity(**arguments)
    receipt = repo_root / "docs/build-receipts/d2/initialization-build.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"status":"PASS"}\n', encoding="utf-8")

    after_receipt = module.canonical_identity(**arguments)
    assert after_receipt["artifact_identity"] == before["artifact_identity"]

    (repo_root / "docs/untracked.go").write_text("package docs\n", encoding="utf-8")
    with pytest.raises(module.ArtifactContractError, match="untracked|drift"):
        module.canonical_identity(**arguments)


@pytest.mark.parametrize(
    ("embed_pattern", "asset_paths", "deleted_path"),
    (
        ("*.asset", ("keep.asset", "deleted.asset"), "deleted.asset"),
        (
            "assets/*",
            (
                "assets/keep.asset",
                "assets/sub/keep.asset",
                "assets/sub/deleted.asset",
            ),
            "assets/sub/deleted.asset",
        ),
    ),
    ids=("flat-glob", "wildcard-directory-descendant"),
)
def test_identity_drift_scope_catches_deleted_file_from_go_embed_pattern(
    tmp_path: Path,
    embed_pattern: str,
    asset_paths: tuple[str, ...],
    deleted_path: str,
) -> None:
    module = _artifact_module()
    repo_root = tmp_path / "repository"
    manifest_path, lock_path = _write_synthetic_contract(repo_root)
    (repo_root / "docs/docs.go").write_text(
        f'package docs\n\nimport "embed"\n\n//go:embed {embed_pattern}\nvar Assets embed.FS\n',
        encoding="utf-8",
    )
    for relative in asset_paths:
        asset = repo_root / "docs" / relative
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_text(f"{relative}\n", encoding="utf-8")
    deleted = repo_root / "docs" / deleted_path
    subprocess.run(("git", "init", "-q"), cwd=repo_root, check=True)
    subprocess.run(("git", "add", "."), cwd=repo_root, check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=BA0 Test",
            "-c",
            "user.email=ba0-test@example.invalid",
            "commit",
            "-q",
            "-m",
            "fixture",
        ),
        cwd=repo_root,
        check=True,
    )
    source_head = subprocess.check_output(
        ("git", "rev-parse", "HEAD"), cwd=repo_root, text=True
    ).strip()

    def go_list_stream() -> str:
        records = [json.loads(line) for line in _go_list_stream(repo_root).splitlines() if line]
        docs = next(record for record in records if record.get("ImportPath", "").endswith("/docs"))
        docs["EmbedPatterns"] = [embed_pattern]
        docs["EmbedFiles"] = sorted(
            relative for relative in asset_paths if (repo_root / "docs" / relative).is_file()
        )
        return "".join(json.dumps(record) + "\n" for record in records)

    def runner(
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        if arguments[:2] == ("go", "list"):
            return _completed(arguments, stdout=go_list_stream())
        return subprocess.run(
            arguments,
            cwd=cwd,
            capture_output=capture_output,
            text=text,
            env=env,
            check=False,
        )

    arguments = {
        "repo_root": repo_root,
        "manifest_path": manifest_path,
        "dependency_lock_path": lock_path,
        "build_source_head": source_head,
        "integration_head": source_head,
        "runner": runner,
        "effective_build_args": {
            "CGO_ENABLED": "1",
            "GOOS": "linux",
            "GOARCH": "arm64",
        },
        "environment": {},
    }
    module.canonical_identity(**arguments)
    deleted.unlink()

    with pytest.raises(module.ArtifactContractError, match="manifest|input|drift"):
        module.canonical_identity(**arguments)


@pytest.mark.parametrize(
    "changed", ("app_input", "dependency_lock"), ids=("app-input", "lock-input")
)
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
    environments: tuple[dict[str, str], ...] = (
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
            "trace": [call.__dict__ for runner in runners for call in runner.calls],
            "stdout": captured.out,
            "stderr": captured.err,
        }
    )

    for canary in (CANARY_SECRET, CANARY_SECRET_B):
        assert canary not in surfaces
        assert _sha256_bytes(canary.encode()) not in surfaces
    assert all(call.arguments[0] != "docker" for runner in runners for call in runner.calls)
