"""OpenSpec 023 R5.1/R5.2 isolated runner-controller contracts."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from importlib import import_module
from io import StringIO
from pathlib import Path
from types import ModuleType
from typing import Protocol

import pytest
from pydantic import SecretStr

from insurance_harness.live_env.compose import (
    ensure_runtime_environment,
    update_runtime_state,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "harness/src/insurance_harness/live_env/github_live.py"
RUNNER_ROOT = REPO_ROOT / "deploy/local-live/runner"
GITHUB_CLI = REPO_ROOT / "harness/scripts/github_live.py"

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


class EphemeralResourcesLike(Protocol):
    db_role: str


def _module() -> ModuleType:
    assert MODULE_PATH.is_file(), "R5 controller module is missing"
    spec = importlib.util.spec_from_file_location("github_live_023", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _github_cli_module() -> ModuleType:
    assert GITHUB_CLI.is_file(), "R5 GitHub live CLI is missing"
    spec = importlib.util.spec_from_file_location("github_live_cli_023", GITHUB_CLI)
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
    assert (
        "ARG RUNNER_RELEASE_BASE=https://github.com/actions/runner/releases/download"
        in dockerfile
    )
    assert "ARG RUNNER_RELEASE_PROTO=https" in dockerfile
    assert '--proto "=${RUNNER_RELEASE_PROTO}"' in dockerfile
    assert "ARG RUNNER_DEBIAN_MIRROR=http://deb.debian.org/debian" in dockerfile
    assert (
        "ARG RUNNER_DEBIAN_SECURITY_MIRROR=http://deb.debian.org/debian-security"
        in dockerfile
    )
    assert 'URIs: ${RUNNER_DEBIAN_MIRROR}' in dockerfile
    assert 'URIs: ${RUNNER_DEBIAN_SECURITY_MIRROR}' in dockerfile
    assert (
        'grep --fixed-strings --line-regexp --quiet "URIs: ${RUNNER_DEBIAN_MIRROR}"'
        in dockerfile
    )
    assert (
        'grep --fixed-strings --line-regexp --quiet '
        '"URIs: ${RUNNER_DEBIAN_SECURITY_MIRROR}"' in dockerfile
    )
    assert (
        '"${RUNNER_RELEASE_BASE}/v${RUNNER_VERSION}/${RUNNER_ARCHIVE}"'
        in dockerfile
    )
    assert "ARG RUNNER_ARCH" in dockerfile
    assert "--ephemeral" in entrypoint
    assert "--disableupdate" in entrypoint
    assert "run.sh --once" in entrypoint
    assert "mkfifo" in entrypoint
    assert 'RUNNER_REGISTRATION_TOKEN="$(cat "$token_pipe")"' in entrypoint
    assert "rm -f \"$token_pipe\"" in entrypoint
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
        "remove_workspace",
        "remove_logs",
        "remove_container",
        "remove_volume",
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


def test_r5_1_controller_runs_exact_sha_with_ephemeral_credentials_and_cleanup() -> None:
    module = _module()
    sha = "a" * 40
    request = module.LiveRunRequest(
        repository="PA-ALG/InsuranceKB-WeKnora",
        pr_number=9,
        head_sha=sha,
        nonce="0123456789abcdef",
    )
    lock = module.RunnerPackageLock(
        version="2.999.0",
        arch="arm64",
        archive="actions-runner-linux-arm64-2.999.0.tar.gz",
        sha256="c" * 64,
    )
    state = module.PersistentLiveState(
        base_url="http://app:8080",
        space_id="space-1",
        knowledge_id="knowledge-1",
        parser_fingerprint="weknora-v0.6.3",
        kb_id="wiki-1",
    )
    events: list[str] = []
    set_values: dict[str, tuple[str, bool]] = {}

    class Backend:
        def approve(self, live_request: object) -> object:
            events.append("approve")
            return module.PullRequest(
                number=9,
                state="open",
                base_repository="PA-ALG/InsuranceKB-WeKnora",
                head_repository="PA-ALG/InsuranceKB-WeKnora",
                head_sha=sha,
            )

        def mint_credentials(self, resources: EphemeralResourcesLike) -> object:
            events.append("mint")
            return module.TemporaryCredentials(
                tenant_key_id="key-99",
                tenant_token=SecretStr("tenant-token"),
                db_role=resources.db_role,
                db_url=SecretStr("postgresql://run-role:password@db/harness"),
            )

        def set_live_value(self, name: str, value: str, *, secret: bool) -> None:
            events.append(f"set:{name}")
            set_values[name] = (value, secret)

        def build_runner(self, plan: object) -> None:
            events.append("build-runner")

        def registration_token(self, repository: str) -> SecretStr:
            events.append("registration-token")
            return SecretStr("short-lived-registration-token")

        def start_runner(self, plan: object, token: SecretStr) -> None:
            assert token.get_secret_value() == "short-lived-registration-token"
            events.append("start-runner")

        def dispatch(self, live_request: object) -> None:
            events.append("dispatch")

        def wait(self, live_request: object) -> object:
            events.append("wait")
            return module.LiveRunResult(
                url="https://github.example/runs/1",
                conclusion="success",
            )

        def execute(self, action: CleanupActionLike) -> None:
            events.append(f"cleanup:{action.kind}")

    result = module.run_github_live(
        Backend(),
        request=request,
        state=state,
        lock=lock,
    )

    assert result.conclusion == "success"
    assert events[:6] == [
        "approve",
        "mint",
        "set:HARNESS_LIVE_API_KEY",
        "set:HARNESS_LIVE_DB_URL",
        "set:HARNESS_LIVE_BASE_URL",
        "set:HARNESS_LIVE_SPACE_ID",
    ]
    assert events.count("approve") == 2
    assert events.index("registration-token") < events.index("start-runner")
    assert events.index("start-runner") < events.index("dispatch")
    assert events.index("dispatch") < events.index("wait")
    assert events[-14:] == [
        f"cleanup:{action.kind}"
        for action in module.cleanup_plan(
            module.EphemeralResources.for_nonce(request.nonce)
        )
    ]
    assert set(set_values) == module.LIVE_VALUE_NAMES
    assert {name for name, (_, secret) in set_values.items() if secret} == set(
        module.LIVE_SECRET_NAMES
    )
    rendered = repr((request, state, result))
    assert "tenant-token" not in rendered
    assert "password" not in rendered


def test_r5_1_concrete_backend_keeps_secrets_out_of_argv_and_host_mounts(
    tmp_path: Path,
) -> None:
    try:
        backend_module = import_module(
            "insurance_harness.live_env.github_backend"
        )
    except ModuleNotFoundError:
        pytest.fail("R5 concrete GitHub/Docker backend is missing")
    domain = _module()
    calls: list[tuple[tuple[str, ...], str | None, dict[str, str] | None]] = []
    sha = "a" * 40

    class Runner:
        def __call__(
            self,
            arguments: tuple[str, ...],
            *,
            cwd: Path,
            input_text: str | None,
            environment: dict[str, str] | None,
        ) -> subprocess.CompletedProcess[str]:
            calls.append((arguments, input_text, environment))
            if arguments[:2] == ("gh", "api") and "pulls/9" in arguments[2]:
                output = json.dumps(
                    {
                        "number": 9,
                        "state": "open",
                        "base": {"repo": {"full_name": "PA-ALG/InsuranceKB-WeKnora"}},
                        "head": {
                            "repo": {"full_name": "PA-ALG/InsuranceKB-WeKnora"},
                            "sha": sha,
                        },
                    }
                )
            elif "registration-token" in " ".join(arguments):
                output = "short-registration-token\n"
            elif arguments[:2] == ("docker", "create"):
                output = "container-id\n"
            elif arguments[:2] == ("docker", "inspect"):
                output = "anonymous-volume-id\n"
            else:
                output = ""
            return subprocess.CompletedProcess(
                arguments,
                0,
                stdout=output,
                stderr="",
            )

    backend = backend_module.ConcreteLiveBackend(
        repo_root=REPO_ROOT,
        runtime_path=tmp_path / ".env.local-live.runtime",
        runner=Runner(),
        sleeper=lambda _: None,
    )
    request = domain.LiveRunRequest(
        repository="PA-ALG/InsuranceKB-WeKnora",
        pr_number=9,
        head_sha=sha,
        nonce="0123456789abcdef",
    )
    assert backend.approve(request).head_sha == sha
    backend.set_live_value(
        "HARNESS_LIVE_API_KEY",
        "tenant-live-secret",
        secret=True,
    )
    plan = domain.build_runner_plan(
        nonce=request.nonce,
        live_values=LIVE_VALUES,
        lock=domain.RunnerPackageLock.load(RUNNER_ROOT / "runner.lock"),
    )
    backend.build_runner(plan)
    token = backend.registration_token(request.repository)
    backend.start_runner(plan, token)
    backend.dispatch(request)

    assert all(
        "tenant-live-secret" not in argument
        and "short-registration-token" not in argument
        for arguments, _, _ in calls
        for argument in arguments
    )
    secret_call = next(call for call in calls if call[0][:3] == ("gh", "secret", "set"))
    assert secret_call[1] == "tenant-live-secret"
    assert "--body" not in secret_call[0]
    create_call = next(call for call in calls if call[0][:2] == ("docker", "create"))
    create_arguments, _, create_environment = create_call
    assert create_environment is not None
    assert "RUNNER_REGISTRATION_TOKEN" not in create_environment
    assert "--tmpfs" in create_arguments
    token_call = next(
        call
        for call in calls
        if call[0][:3] == ("docker", "exec", "--interactive")
        and call[0][-1] == "cat > /run/insurancekb/registration-token"
    )
    assert token_call[1] == "short-registration-token"
    assert "--network" in create_arguments
    assert "local-live-weknora" in create_arguments
    assert "-v" not in create_arguments
    assert "--volume" not in create_arguments
    assert all("docker.sock" not in argument for argument in create_arguments)
    mount_specs = [
        create_arguments[index + 1]
        for index, argument in enumerate(create_arguments[:-1])
        if argument == "--mount"
    ]
    assert mount_specs == [
        "type=volume,volume-nocopy,"
        "destination=/home/runner/actions-runner/_work"
    ]
    assert all("type=bind" not in mount for mount in mount_specs)
    assert any(
        arguments[:4]
        == ("docker", "network", "connect", "local-live-harness-db")
        for arguments, _, _ in calls
    )


def test_r5_1_concrete_backend_rejects_non_object_run_entries(
    tmp_path: Path,
) -> None:
    backend_module = import_module("insurance_harness.live_env.github_backend")
    domain = _module()

    class Runner:
        def __call__(
            self,
            arguments: tuple[str, ...],
            *,
            cwd: Path,
            input_text: str | None,
            environment: dict[str, str] | None,
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                arguments,
                0,
                stdout=json.dumps([None]),
                stderr="",
            )

    backend = backend_module.ConcreteLiveBackend(
        repo_root=REPO_ROOT,
        runtime_path=tmp_path / ".env.local-live.runtime",
        runner=Runner(),
        sleeper=lambda _: None,
        poll_attempts=1,
    )
    request = domain.LiveRunRequest(
        repository="PA-ALG/InsuranceKB-WeKnora",
        pr_number=9,
        head_sha="a" * 40,
        nonce="0123456789abcdef",
    )

    with pytest.raises(ValueError, match="invalid GitHub run list response"):
        backend.wait(request)


def test_r5_2_concrete_backend_mints_and_revokes_both_ephemeral_credentials(
    tmp_path: Path,
) -> None:
    backend_module = import_module("insurance_harness.live_env.github_backend")
    domain = _module()
    runtime = tmp_path / ".env.local-live.runtime"
    ensure_runtime_environment(runtime)
    update_runtime_state(
        runtime,
        {
            "LOCAL_LIVE_TENANT_ID": "7",
            "LOCAL_LIVE_CHAT_MODEL_ID": "chat-1",
            "LOCAL_LIVE_EMBEDDING_MODEL_ID": "embedding-1",
            "LOCAL_LIVE_RERANK_MODEL_ID": "rerank-1",
            "LOCAL_LIVE_RAW_KB_ID": "raw-1",
            "LOCAL_LIVE_WIKI_KB_ID": "wiki-1",
            "LOCAL_LIVE_API_KEY_ID": "key-1",
            "LOCAL_LIVE_API_KEY": "persistent-key",
            "LOCAL_LIVE_SPACE_ID": "space-1",
            "LOCAL_LIVE_KNOWLEDGE_ID": "knowledge-1",
            "LOCAL_LIVE_PARSER_FINGERPRINT": "weknora-v0.6.3",
        },
    )
    events: list[str] = []

    def tenant_minter(values: object, resources: object) -> tuple[str, SecretStr]:
        events.append("mint-tenant")
        return "42", SecretStr("per-run-tenant-token")

    def database_minter(
        values: object,
        resources: EphemeralResourcesLike,
    ) -> tuple[str, SecretStr]:
        events.append("mint-db")
        return resources.db_role, SecretStr(
            "postgresql+psycopg://role:per-run-db-secret@db/harness"
        )

    def tenant_revoker(values: object, key_id: str) -> None:
        assert key_id == "42"
        events.append("revoke-tenant")

    def database_dropper(values: object, role: str) -> None:
        assert role == domain.EphemeralResources.for_nonce(
            "0123456789abcdef"
        ).db_role
        events.append("drop-db")

    backend = backend_module.ConcreteLiveBackend(
        repo_root=REPO_ROOT,
        runtime_path=runtime,
        tenant_minter=tenant_minter,
        database_minter=database_minter,
        tenant_revoker=tenant_revoker,
        database_dropper=database_dropper,
    )
    resources = domain.EphemeralResources.for_nonce("0123456789abcdef")

    credentials = backend.mint_credentials(resources)
    backend.execute(domain.CleanupAction("revoke_tenant_key", resources.tenant_key))
    backend.execute(domain.CleanupAction("drop_db_role", resources.db_role))

    assert events == ["mint-tenant", "mint-db", "revoke-tenant", "drop-db"]
    assert credentials.db_role == resources.db_role
    assert credentials.tenant_key_id == "42"
    assert "per-run-tenant-token" not in repr(credentials)
    assert "per-run-db-secret" not in repr(credentials)


def test_r5_1_github_cli_requires_explicit_dispatch_confirmation() -> None:
    module = _github_cli_module()
    calls: list[object] = []

    class Adapter:
        def run(self, request: object) -> object:
            calls.append(request)
            return {"status": "passed", "url": "https://github.example/runs/1"}

    arguments = [
        "--pr-number",
        "9",
        "--head-sha",
        "a" * 40,
        "--runner-nonce",
        "0123456789abcdef",
    ]
    error = StringIO()
    assert module.main(arguments, adapter=Adapter(), error=error) == 2
    assert calls == []
    assert "explicit confirmation" in error.getvalue()

    output = StringIO()
    assert module.main(
        [*arguments, "--confirm-dispatch"],
        adapter=Adapter(),
        output=output,
    ) == 0
    assert len(calls) == 1
    assert "github.example" in output.getvalue()


def test_r5_1_database_role_grants_only_live_test_database_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_module = import_module("insurance_harness.live_env.github_backend")
    domain = _module()
    statements: list[str] = []

    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, statement: object, parameters: object = None) -> None:
            statements.append(str(statement))

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def cursor(self) -> Cursor:
            return Cursor()

    monkeypatch.setattr(
        backend_module.psycopg,
        "connect",
        lambda *args, **kwargs: Connection(),
    )
    values = {"HARNESS_POSTGRES_PASSWORD": "h" * 32}
    resources = domain.EphemeralResources.for_nonce("0123456789abcdef")

    role, url = backend_module.ConcreteLiveBackend._mint_database_role(
        values,
        resources,
    )

    rendered = "\n".join(statements)
    assert role == resources.db_role
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT" in rendered
    assert "GRANT CONNECT, CREATE ON DATABASE" in rendered
    assert "GRANT USAGE ON SCHEMA" in rendered
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES" in rendered
    assert "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES" in rendered
    assert "h" * 32 not in repr(url)
