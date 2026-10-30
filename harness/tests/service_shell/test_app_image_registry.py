"""I1 acceptance (protected, written by Claude): CI app image plan and digest pull.

Spec docs/design/slices/I1-CI构建镜像.md §3.2 and §3.7. The CI build reuses the BA0 identity so a
pulled image carries the same labels as a local build, and a local deploy can select a CI image
by digest instead of building in the VM. Docker is an injected runner; nothing is pulled.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
REPOSITORY = "ghcr.io/pa-alg/insurancekb-weknora-app"
DIGEST = "sha256:" + "d" * 64
REFERENCE = f"{REPOSITORY}@{DIGEST}"
IMAGE_ID = "sha256:" + "e" * 64
COMMIT = "c" * 40


def _load(name: str, relative: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader, f"{relative} must exist"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registry() -> ModuleType:
    return _load("i1_app_image_registry", "scripts/app_image_registry.py")


def identity() -> dict[str, Any]:
    return {
        "artifact": "weknora-app",
        "artifact_identity": "sha256:" + "a" * 64,
        "canonical_bytes": b"{}",
        "manifest_sha256": "b" * 64,
        "dependency_lock_sha256": "f" * 64,
        "build_source_head": COMMIT,
        "integration_head": COMMIT,
        "target": "runtime",
        "platform": "linux/arm64",
        "version": "0.9.0",
        "commit_id": COMMIT,
        "source_date_epoch": 0,
        "build_time": "1970-01-01 00:00:00 UTC",
    }


def expected_labels(module: ModuleType) -> dict[str, str]:
    return dict(module.base._required_labels(identity()))


class FakeDocker:
    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, arguments: Sequence[str], **_: object) -> subprocess.CompletedProcess[str]:
        command = tuple(arguments)
        self.calls.append(command)
        if "pull" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[3:5] == ("image", "inspect"):
            return subprocess.CompletedProcess(command, 0, json.dumps(self.record), "")
        return subprocess.CompletedProcess(command, 1, "", "unexpected docker call")


def pulled_record(module: ModuleType, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "Id": IMAGE_ID,
        "RepoDigests": [REFERENCE],
        "Os": "linux",
        "Architecture": "arm64",
        "Config": {"Labels": expected_labels(module)},
    }
    record.update(overrides)
    return record


def select(module: ModuleType, runner: FakeDocker, out: Path, reference: str = REFERENCE) -> Any:
    return module.select_pulled_app(
        repo_root=ROOT,
        identity=identity(),
        reference=reference,
        evidence_out=out,
        runner=runner,
        docker_context="colima",
    )


@pytest.mark.parametrize(
    "reference",
    [
        f"{REPOSITORY}:main",
        f"{REPOSITORY}:sha-{'c' * 12}",
        f"ghcr.io/someone-else/weknora-app@{DIGEST}",
        f"{REPOSITORY}@sha256:{'d' * 63}",
        f"{REPOSITORY}:main@{DIGEST}",
    ],
)
def test_only_an_exact_digest_of_our_app_repository_can_be_pulled(
    reference: str, tmp_path: Path
) -> None:
    module = registry()
    runner = FakeDocker(pulled_record(module))
    with pytest.raises(module.base.ArtifactContractError):
        select(module, runner, tmp_path / "receipt.json", reference)
    assert runner.calls == [], "a rejected reference must not reach Docker"


def test_a_pulled_image_with_the_identity_labels_gets_a_receipt_start_exact_image_accepts(
    tmp_path: Path,
) -> None:
    module = registry()
    runner = FakeDocker(pulled_record(module))
    out = tmp_path / "receipt.json"
    receipt = select(module, runner, out)

    assert receipt["contract"] == "ba0-app-build-receipt.v1"
    assert receipt["status"] == "PASS"
    assert receipt["selector"] == "PULL"
    assert receipt["image_id"] == IMAGE_ID
    assert receipt["pulled_reference"] == REFERENCE
    assert receipt["build_invocations"] == 0
    assert receipt["labels"] == expected_labels(module)
    assert json.loads(out.read_text(encoding="utf-8")) == receipt
    assert any("pull" in call and REFERENCE in call for call in runner.calls)

    smoke = _load("i1_start_exact_image", "scripts/start_exact_image.py")
    assert smoke._required_labels(receipt) == expected_labels(module)


@pytest.mark.parametrize(
    "overrides",
    [
        {"Architecture": "amd64"},
        {"RepoDigests": [f"{REPOSITORY}@sha256:{'0' * 64}"]},
        {"Config": {"Labels": {}}},
    ],
)
def test_a_pulled_image_that_does_not_prove_the_identity_is_refused(
    overrides: dict[str, Any], tmp_path: Path
) -> None:
    module = registry()
    record = pulled_record(module, **overrides)
    out = tmp_path / "receipt.json"
    with pytest.raises(module.base.ArtifactContractError):
        select(module, FakeDocker(record), out)
    assert json.loads(out.read_text(encoding="utf-8"))["status"] == "INCOMPLETE"


def test_a_label_for_another_identity_is_refused(tmp_path: Path) -> None:
    module = registry()
    labels = expected_labels(module)
    labels["io.insurancekb.app.artifact-identity"] = "sha256:" + "9" * 64
    record = pulled_record(module, Config={"Labels": labels})
    with pytest.raises(module.base.ArtifactContractError):
        select(module, FakeDocker(record), tmp_path / "receipt.json")


def test_the_ci_plan_carries_the_local_identity_labels_and_build_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = registry()
    frozen = tmp_path / "frozen"
    (frozen / "docker").mkdir(parents=True)
    (frozen / "docker" / "Dockerfile.app").write_text("FROM scratch\n", encoding="utf-8")
    build_args = {"BUILDER_IMAGE": "golang@sha256:" + "1" * 64, "VERSION_ARG": "0.9.0"}

    monkeypatch.setattr(module.base, "canonical_identity", lambda **_: identity())
    monkeypatch.setattr(module, "_verified_context", lambda **_: _context(frozen))
    monkeypatch.setattr(module.base, "_selector_build_args", lambda *_: dict(build_args))

    context_out = tmp_path / "context"
    plan = module.ci_plan(repo_root=ROOT, build_source_head=COMMIT, context_out=context_out)

    assert plan["contract"] == "i1-app-ci-plan.v1"
    assert plan["artifact_identity"] == identity()["artifact_identity"]
    assert plan["platform"] == "linux/arm64"
    assert plan["target"] == "runtime"
    assert plan["dockerfile"] == "docker/Dockerfile.app"
    assert plan["labels"] == expected_labels(module)
    assert plan["build_args"] == build_args
    assert (context_out / "docker" / "Dockerfile.app").read_text(encoding="utf-8")

    with pytest.raises(module.base.ArtifactContractError):
        module.ci_plan(repo_root=ROOT, build_source_head=COMMIT, context_out=context_out)


class _context:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, *_: object) -> None:
        return None
