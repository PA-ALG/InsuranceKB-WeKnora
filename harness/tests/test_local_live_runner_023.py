"""OpenSpec 023 R5.1/R5.2 isolated runner-controller contracts."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Protocol

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "harness/src/insurance_harness/live_env/github_live.py"
RUNNER_ROOT = REPO_ROOT / "deploy/local-live/runner"

LIVE_VALUES = {
    "HARNESS_LIVE_API_KEY": "api-key",
    "HARNESS_LIVE_DB_URL": "postgresql://run-role:password@db/harness",
    "HARNESS_LIVE_BASE_URL": "http://weknora:8080",
    "HARNESS_LIVE_SPACE_ID": "space",
    "HARNESS_LIVE_KNOWLEDGE_ID": "knowledge",
    "HARNESS_LIVE_PARSER_FINGERPRINT": "parser",
    "HARNESS_LIVE_KB_ID": "kb",
}


class CleanupActionLike(Protocol):
    kind: str


def _module() -> ModuleType:
    assert MODULE_PATH.is_file(), "R5 controller module is missing"
    spec = importlib.util.spec_from_file_location("github_live_023", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_r5_1_nonce_creates_unique_runner_name_and_label() -> None:
    module = _module()

    first = module.RunnerIdentity.from_nonce("0123456789abcdef")
    second = module.RunnerIdentity.from_nonce("fedcba9876543210")

    assert first.name == first.label == "insurancekb-live-0123456789abcdef"
    assert second.name == second.label == "insurancekb-live-fedcba9876543210"
    assert first != second
    for invalid in ("0" * 15, "0" * 17, "ABCDEF0123456789", "g" * 16):
        with pytest.raises(ValueError, match="nonce"):
            module.RunnerIdentity.from_nonce(invalid)


@pytest.mark.parametrize("arch", ["arm64", "x64"])
def test_r5_1_runner_lock_matches_explicit_architecture_and_unresolved_fails_closed(
    tmp_path: Path,
    arch: str,
) -> None:
    module = _module()
    repository_lock = module.RunnerPackageLock.load(RUNNER_ROOT / "runner.lock")
    repository_lock.require_verified()
    assert repository_lock == module.RunnerPackageLock(
        version="2.335.1",
        arch="arm64",
        archive="actions-runner-linux-arm64-2.335.1.tar.gz",
        sha256="6d1e85bfd1a506a8b17c1f1b9b57dba458ffed90898799aaa9f599520b0d9207",
    )

    verified_path = tmp_path / "runner.lock"
    verified_path.write_text(
        "version=2.999.0\n"
        f"arch={arch}\n"
        f"archive=actions-runner-linux-{arch}-2.999.0.tar.gz\n"
        f"sha256={'a' * 64}\n"
    )
    verified = module.RunnerPackageLock.load(verified_path)
    verified.require_verified()
    assert verified.download_url == (
        "https://github.com/actions/runner/releases/download/v2.999.0/"
        f"actions-runner-linux-{arch}-2.999.0.tar.gz"
    )

    mismatch_path = tmp_path / "mismatch.lock"
    mismatch_path.write_text(
        "version=2.999.0\n"
        "arch=arm64\n"
        "archive=actions-runner-linux-x64-2.999.0.tar.gz\n"
        f"sha256={'a' * 64}\n"
    )
    with pytest.raises(ValueError, match="invalid"):
        module.RunnerPackageLock.load(mismatch_path).require_verified()


def test_r5_1_runner_image_is_non_root_ephemeral_and_one_job() -> None:
    dockerfile = (RUNNER_ROOT / "Dockerfile").read_text()
    entrypoint = (RUNNER_ROOT / "entrypoint.sh").read_text()

    assert (
        "ARG RUNNER_BASE_IMAGE=debian:bookworm-slim@sha256:"
        "7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818"
        in dockerfile
    )
    assert "USER runner" in dockerfile
    assert "sha256sum -c" in dockerfile
    assert "github.com/actions/runner/releases/download" in dockerfile
    assert "ARG RUNNER_ARCH" in dockerfile
    assert "--ephemeral" in entrypoint
    assert "--disableupdate" in entrypoint
    assert "run.sh --once" in entrypoint
    assert entrypoint.index("unset RUNNER_REGISTRATION_TOKEN") < entrypoint.index(
        "exec ./run.sh --once"
    )
    assert "set -x" not in entrypoint


def test_r5_1_plan_has_no_mounts_two_attached_networks_https_and_seven_values(
    tmp_path: Path,
) -> None:
    module = _module()
    lock_path = tmp_path / "runner.lock"
    lock_path.write_text(
        "version=2.999.0\n"
        "arch=arm64\n"
        "archive=actions-runner-linux-arm64-2.999.0.tar.gz\n"
        f"sha256={'b' * 64}\n"
    )

    plan = module.build_runner_plan(
        nonce="0123456789abcdef",
        live_values=LIVE_VALUES,
        lock=module.RunnerPackageLock.load(lock_path),
    )

    assert plan.mounts == ()
    assert plan.published_ports == ()
    assert plan.attached_networks == ("local-live-weknora", "local-live-harness-db")
    assert plan.outbound_https is True
    assert plan.max_jobs == 1
    assert set(plan.live_values.reveal()) == set(LIVE_VALUES)
    with pytest.raises(ValueError, match="seven"):
        module.build_runner_plan(
            nonce="0123456789abcdef",
            live_values={**LIVE_VALUES, "HARNESS_LLM_API_KEY": "forbidden"},
            lock=module.RunnerPackageLock.load(lock_path),
        )


def test_r5_1_runner_plan_repr_redacts_both_secrets() -> None:
    module = _module()
    lock = module.RunnerPackageLock(
        version="2.999.0",
        arch="arm64",
        archive="actions-runner-linux-arm64-2.999.0.tar.gz",
        sha256="c" * 64,
    )

    plan = module.build_runner_plan(
        nonce="0123456789abcdef",
        live_values=LIVE_VALUES,
        lock=lock,
    )

    rendered = repr(plan)
    assert LIVE_VALUES["HARNESS_LIVE_API_KEY"] not in rendered
    assert LIVE_VALUES["HARNESS_LIVE_DB_URL"] not in rendered
    assert "password" not in rendered
    assert plan.live_values.reveal() == LIVE_VALUES


def test_r5_1_injected_gateway_requires_open_same_repo_exact_sha() -> None:
    module = _module()

    class Gateway:
        def __init__(self, pull: object) -> None:
            self.pull = pull

        def get_pull(self, repository: str, number: int) -> object:
            assert repository == "PA-ALG/InsuranceKB-WeKnora"
            assert number == 9
            return self.pull

    sha = "a" * 40
    approved = module.PullRequest(
        number=9,
        state="open",
        base_repository="PA-ALG/InsuranceKB-WeKnora",
        head_repository="PA-ALG/InsuranceKB-WeKnora",
        head_sha=sha,
    )
    assert module.approve_pull_request(
        Gateway(approved),
        repository="PA-ALG/InsuranceKB-WeKnora",
        pr_number=9,
        head_sha=sha,
    ) == approved

    for changed in (
        module.PullRequest(9, "closed", approved.base_repository, approved.head_repository, sha),
        module.PullRequest(9, "open", approved.base_repository, "fork/repo", sha),
        module.PullRequest(9, "open", approved.base_repository, approved.head_repository, "b" * 40),
    ):
        with pytest.raises(ValueError, match="open same-repository exact-SHA"):
            module.approve_pull_request(
                Gateway(changed),
                repository="PA-ALG/InsuranceKB-WeKnora",
                pr_number=9,
                head_sha=sha,
            )


def test_r5_2_cleanup_plan_covers_all_ephemeral_resources() -> None:
    module = _module()
    actions = module.cleanup_plan(module.EphemeralResources.for_nonce("0123456789abcdef"))

    assert [action.kind for action in actions] == [
        "delete_secret",
        "delete_secret",
        "delete_variable",
        "delete_variable",
        "delete_variable",
        "delete_variable",
        "delete_variable",
        "revoke_tenant_key",
        "drop_db_role",
        "remove_runner_registration",
        "remove_container",
        "remove_volume",
        "remove_workspace",
        "remove_logs",
    ]


@pytest.mark.parametrize("primary", [RuntimeError("live failed"), KeyboardInterrupt()])
def test_r5_2_cleanup_attempts_every_action_without_masking_primary(
    primary: BaseException,
) -> None:
    module = _module()
    resources = module.EphemeralResources.for_nonce("0123456789abcdef")
    attempted: list[str] = []

    class Executor:
        def execute(self, action: CleanupActionLike) -> None:
            attempted.append(action.kind)
            if action.kind == "drop_db_role":
                raise RuntimeError("secret detail must be sanitized")

    def operation() -> None:
        raise primary

    with pytest.raises(type(primary)) as caught:
        module.execute_with_cleanup(operation, Executor(), resources)

    assert caught.value is primary
    assert attempted == [action.kind for action in module.cleanup_plan(resources)]
    notes = getattr(caught.value, "__notes__", [])
    assert notes == ["cleanup failures: drop_db_role"]
    assert "secret detail" not in str(notes)


def test_r5_2_cleanup_failure_after_success_is_sanitized() -> None:
    module = _module()
    resources = module.EphemeralResources.for_nonce("0123456789abcdef")

    class Executor:
        def execute(self, action: CleanupActionLike) -> None:
            if action.kind == "remove_logs":
                raise RuntimeError("local path")

    with pytest.raises(module.CleanupFailure, match="remove_logs") as caught:
        module.execute_with_cleanup(lambda: "ok", Executor(), resources)

    assert "local path" not in str(caught.value)
