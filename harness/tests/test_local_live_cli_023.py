"""OpenSpec 023 executable local-live CLI skeleton contracts."""

from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path
from types import ModuleType
from typing import Protocol

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = REPO_ROOT / "harness/scripts/local_live.py"
PHASES = ("check", "probe-models", "up", "provision", "verify", "run-local", "down")


class PhaseRequestLike(Protocol):
    phase: str
    delete_volumes: bool


class ProfileLike(Protocol):
    model: str


class LocalConfigLike(Protocol):
    weknora_chat: ProfileLike
    extraction: ProfileLike


def _module() -> ModuleType:
    assert CLI_PATH.is_file(), "local-live CLI is missing"
    spec = importlib.util.spec_from_file_location("local_live_cli_023", CLI_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ResolvedLocks:
    def require_resolved(self) -> None:
        return None


def _write_local_envs(tmp_path: Path) -> tuple[Path, Path]:
    config = tmp_path / ".env.local-live"
    config.write_text(
        "LOCAL_LIVE_WEKNORA_CHAT_BASE_URL=https://chat.example/v1\n"
        "LOCAL_LIVE_WEKNORA_CHAT_API_KEY=chat-key\n"
        "LOCAL_LIVE_WEKNORA_CHAT_MODEL=chat-model\n"
        "LOCAL_LIVE_WEKNORA_EMBEDDING_BASE_URL=https://embedding.example/v1\n"
        "LOCAL_LIVE_WEKNORA_EMBEDDING_API_KEY=embedding-key\n"
        "LOCAL_LIVE_WEKNORA_EMBEDDING_MODEL=embedding-model\n"
        "LOCAL_LIVE_WEKNORA_RERANK_BASE_URL=https://rerank.example/v1\n"
        "LOCAL_LIVE_WEKNORA_RERANK_API_KEY=rerank-key\n"
        "LOCAL_LIVE_WEKNORA_RERANK_MODEL=rerank-model\n"
        "HARNESS_LLM_BASE_URL=https://bailian.example/v1\n"
        "HARNESS_LLM_API_KEY=private-api-key\n"
        "HARNESS_LLM_MODEL_WEAK=deepseek-v4-flash\n"
    )
    runtime = tmp_path / ".env.local-live.runtime"
    runtime.write_text(
        "DB_USER=weknora\n"
        "DB_NAME=weknora\n"
        f"DB_PASSWORD={'d' * 32}\n"
        f"REDIS_PASSWORD={'r' * 32}\n"
        f"JWT_SECRET={'j' * 32}\n"
        f"SYSTEM_AES_KEY={'a' * 32}\n"
        f"HARNESS_POSTGRES_PASSWORD={'h' * 32}\n"
        "WEKNORA_VERSION=v0.6.3\n"
    )
    config.chmod(0o600)
    runtime.chmod(0o600)
    return config, runtime


@pytest.mark.parametrize("phase", PHASES)
def test_r5_1_cli_dispatches_each_frozen_phase_through_injected_adapter(
    phase: str,
) -> None:
    module = _module()
    requests: list[PhaseRequestLike] = []

    class Adapter:
        def run(self, request: PhaseRequestLike) -> object:
            requests.append(request)
            return {"status": "ok", "phase": request.phase}

    output = StringIO()
    assert (
        module.main(
            [phase], adapter=Adapter(), lock_verifier=ResolvedLocks(), output=output
        )
        == 0
    )
    assert len(requests) == 1
    assert requests[0].phase == phase
    assert requests[0].delete_volumes is False
    assert '"status": "ok"' in output.getvalue()


def test_r5_2_down_is_non_destructive_without_explicit_volume_confirmation() -> None:
    module = _module()
    requests: list[PhaseRequestLike] = []

    class Adapter:
        def run(self, request: PhaseRequestLike) -> object:
            requests.append(request)
            return {"status": "stopped"}

    assert module.main(
        ["down"], adapter=Adapter(), lock_verifier=ResolvedLocks(), output=StringIO()
    ) == 0
    assert requests[0].delete_volumes is False

    error = StringIO()
    assert module.main(
        ["down", "--delete-volumes"],
        adapter=Adapter(),
        lock_verifier=ResolvedLocks(),
        output=StringIO(),
        error=error,
    ) == 2
    assert len(requests) == 1
    assert "explicit confirmation required" in error.getvalue()

    assert module.main(
        ["down", "--delete-volumes", "--confirm-delete-volumes"],
        adapter=Adapter(),
        lock_verifier=ResolvedLocks(),
        output=StringIO(),
    ) == 0
    assert requests[-1].delete_volumes is True


def test_r5_1_unresolved_runtime_lock_fails_closed_before_adapter(tmp_path: Path) -> None:
    module = _module()
    lock = tmp_path / "runner.lock"
    lock.write_text("version=UNRESOLVED\narch=UNRESOLVED\n")
    called = False

    class Adapter:
        def run(self, request: object) -> object:
            nonlocal called
            called = True
            return {"status": "must-not-run"}

    error = StringIO()
    assert module.main(
        ["check"],
        adapter=Adapter(),
        lock_verifier=module.FileLockVerifier((lock,)),
        output=StringIO(),
        error=error,
    ) == 2
    assert called is False
    assert error.getvalue() == "local-live: runtime locks are unresolved\n"


def test_r5_1_cli_redacts_adapter_output_and_errors() -> None:
    module = _module()
    secrets = {
        "api_key": "raw-api-key",
        "db_url": "postgresql://user:password@db/harness",
        "registration_token": "raw-registration-token",
        "base_url": "https://private.example/v1",
    }

    class Adapter:
        def run(self, request: object) -> object:
            return {"status": "ok", **secrets}

    output = StringIO()
    assert module.main(
        ["verify"], adapter=Adapter(), lock_verifier=ResolvedLocks(), output=output
    ) == 0
    rendered = output.getvalue()
    assert "<redacted>" in rendered
    assert all(secret not in rendered for secret in secrets.values())
    assert "password" not in rendered

    class FailingAdapter:
        def run(self, request: object) -> object:
            raise RuntimeError("probe failed at https://private.example with token raw-token")

    error = StringIO()
    assert module.main(
        ["probe-models"],
        adapter=FailingAdapter(),
        lock_verifier=ResolvedLocks(),
        output=StringIO(),
        error=error,
    ) == 1
    assert "private.example" not in error.getvalue()
    assert "raw-token" not in error.getvalue()


def test_r5_1_cli_default_path_uses_local_adapter_and_fails_closed(
    tmp_path: Path,
) -> None:
    module = _module()
    images_lock = tmp_path / "images.lock"
    runner_lock = tmp_path / "runner.lock"
    images_lock.write_text("resolved=true\n")
    runner_lock.write_text("resolved=true\n")
    module.__dict__["DEFAULT_LOCK_PATHS"] = (images_lock, runner_lock)
    module.__dict__["DEFAULT_LOCAL_PATHS"] = module.LocalLivePaths(
        tmp_path / "missing-config",
        tmp_path / "missing-runtime",
    )
    error = StringIO()

    assert module.main(["check"], output=StringIO(), error=error) == 2
    assert error.getvalue() == "local-live: model configuration is invalid\n"


def test_r5_1_default_lock_gate_requires_images_and_runner_locks() -> None:
    module = _module()

    assert tuple(path.name for path in module.DEFAULT_LOCK_PATHS) == (
        "images.lock",
        "runner.lock",
    )


def test_r5_1_local_check_validates_private_config_runtime_and_both_locks(
    tmp_path: Path,
) -> None:
    module = _module()
    config, runtime = _write_local_envs(tmp_path)
    images_lock = tmp_path / "images.lock"
    runner_lock = tmp_path / "runner.lock"
    images_lock.write_text("image=example@sha256:" + "a" * 64 + "\n")
    runner_lock.write_text("version=2.999.0\nsha256=" + "b" * 64 + "\n")
    adapter = module.LocalLiveAdapter(module.LocalLivePaths(config, runtime))
    output = StringIO()

    assert module.main(
        ["check"],
        adapter=adapter,
        lock_verifier=module.FileLockVerifier((images_lock, runner_lock)),
        output=output,
    ) == 0
    assert output.getvalue() == (
        '{"config": "valid", "runtime": "valid", "status": "ok"}\n'
    )
    assert "private-api-key" not in output.getvalue()

    runtime.chmod(0o644)
    error = StringIO()
    assert module.main(
        ["check"],
        adapter=adapter,
        lock_verifier=module.FileLockVerifier((images_lock, runner_lock)),
        output=StringIO(),
        error=error,
    ) == 2
    assert error.getvalue() == "local-live: runtime configuration is invalid\n"


def test_r1_1_local_check_reuses_four_role_model_config_loader(tmp_path: Path) -> None:
    module = _module()
    config, runtime = _write_local_envs(tmp_path)
    config.write_text(
        "HARNESS_LLM_BASE_URL=https://bailian.example/v1\n"
        "HARNESS_LLM_API_KEY=private-api-key\n"
        "HARNESS_LLM_MODEL_WEAK=deepseek-v4-flash\n"
    )
    config.chmod(0o600)
    error = StringIO()

    assert module.main(
        ["check"],
        adapter=module.LocalLiveAdapter(module.LocalLivePaths(config, runtime)),
        lock_verifier=ResolvedLocks(),
        output=StringIO(),
        error=error,
    ) == 2
    assert error.getvalue() == "local-live: model configuration is invalid\n"


def test_r1_1_probe_models_defaults_to_async_probe_all_models(tmp_path: Path) -> None:
    module = _module()
    config, runtime = _write_local_envs(tmp_path)
    seen: list[LocalConfigLike] = []

    async def fake_probe_all_models(configuration: LocalConfigLike) -> object:
        seen.append(configuration)
        return {"status": "probed", "api_key": "private-api-key"}

    module.__dict__["probe_all_models"] = fake_probe_all_models
    adapter = module.LocalLiveAdapter(module.LocalLivePaths(config, runtime))
    output = StringIO()
    assert module.main(
        ["probe-models"],
        adapter=adapter,
        lock_verifier=ResolvedLocks(),
        output=output,
    ) == 0
    assert len(seen) == 1
    assert seen[0].weknora_chat.model == "chat-model"
    assert seen[0].extraction.model == "deepseek-v4-flash"
    assert "private-api-key" not in output.getvalue()
    assert '"status": "probed"' in output.getvalue()


def test_r5_1_check_idempotently_ensures_runtime_environment(tmp_path: Path) -> None:
    module = _module()
    config, runtime = _write_local_envs(tmp_path)
    runtime.unlink()
    adapter = module.LocalLiveAdapter(module.LocalLivePaths(config, runtime))

    first = StringIO()
    second = StringIO()
    assert module.main(
        ["check"], adapter=adapter, lock_verifier=ResolvedLocks(), output=first
    ) == 0
    assert runtime.stat().st_mode & 0o777 == 0o600
    assert module.main(
        ["check"], adapter=adapter, lock_verifier=ResolvedLocks(), output=second
    ) == 0
    assert first.getvalue() == second.getvalue()


@pytest.mark.parametrize("phase", ["up", "provision", "verify", "run-local", "down"])
def test_r5_1_local_phase_without_collaborator_fails_closed(
    tmp_path: Path,
    phase: str,
) -> None:
    module = _module()
    config, runtime = _write_local_envs(tmp_path)
    error = StringIO()

    assert module.main(
        [phase],
        adapter=module.LocalLiveAdapter(module.LocalLivePaths(config, runtime)),
        lock_verifier=ResolvedLocks(),
        output=StringIO(),
        error=error,
    ) == 2
    assert error.getvalue() == f"local-live: collaborator unavailable for {phase}\n"


@pytest.mark.parametrize(
    ("phase", "collaborator_name"),
    [("up", "subprocess"), ("provision", "provision"), ("verify", "provision")],
)
def test_r5_1_local_phase_routes_only_to_injected_collaborator(
    tmp_path: Path,
    phase: str,
    collaborator_name: str,
) -> None:
    module = _module()
    config, runtime = _write_local_envs(tmp_path)
    calls: list[str] = []

    class Collaborator:
        def run(self, request: PhaseRequestLike) -> object:
            calls.append(request.phase)
            return {"status": "planned"}

    kwargs = {f"{collaborator_name}_collaborator": Collaborator()}
    adapter = module.LocalLiveAdapter(module.LocalLivePaths(config, runtime), **kwargs)

    assert module.main(
        [phase], adapter=adapter, lock_verifier=ResolvedLocks(), output=StringIO()
    ) == 0
    assert calls == [phase]
