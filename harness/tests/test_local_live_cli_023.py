"""OpenSpec 023 executable local-live CLI skeleton contracts."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from hashlib import sha256
from io import StringIO
from pathlib import Path
from stat import S_IMODE
from types import ModuleType, SimpleNamespace
from typing import Protocol, cast

import pytest
from pydantic import SecretStr

from insurance_harness.live_env.compose import (
    read_runtime_environment,
    update_runtime_state,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = REPO_ROOT / "harness/scripts/local_live.py"
PHASES = (
    "check",
    "probe-models",
    "up",
    "provision",
    "verify",
    "smoke-vlm",
    "retry-vlm",
    "run-local",
    "down",
)


class PhaseRequestLike(Protocol):
    phase: str
    delete_volumes: bool
    knowledge_id: str | None


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
        "LOCAL_LIVE_WEKNORA_CHAT_PROVIDER=aliyun\n"
        "LOCAL_LIVE_WEKNORA_CHAT_PROTOCOL=openai_compatible\n"
        "LOCAL_LIVE_WEKNORA_EMBEDDING_BASE_URL=https://embedding.example/v1\n"
        "LOCAL_LIVE_WEKNORA_EMBEDDING_API_KEY=embedding-key\n"
        "LOCAL_LIVE_WEKNORA_EMBEDDING_MODEL=embedding-model\n"
        "LOCAL_LIVE_WEKNORA_EMBEDDING_PROVIDER=aliyun\n"
        "LOCAL_LIVE_WEKNORA_EMBEDDING_PROTOCOL=openai_compatible\n"
        "LOCAL_LIVE_WEKNORA_RERANK_BASE_URL=https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank\n"
        "LOCAL_LIVE_WEKNORA_RERANK_API_KEY=rerank-key\n"
        "LOCAL_LIVE_WEKNORA_RERANK_MODEL=rerank-model\n"
        "LOCAL_LIVE_WEKNORA_RERANK_PROVIDER=aliyun\n"
        "LOCAL_LIVE_WEKNORA_RERANK_PROTOCOL=dashscope_native\n"
        "LOCAL_LIVE_WEKNORA_VLLM_BASE_URL=https://vlm.example/v1\n"
        "LOCAL_LIVE_WEKNORA_VLLM_API_KEY=vlm-key\n"
        "LOCAL_LIVE_WEKNORA_VLLM_MODEL=vlm-model\n"
        "LOCAL_LIVE_WEKNORA_VLLM_PROVIDER=aliyun\n"
        "LOCAL_LIVE_WEKNORA_VLLM_PROTOCOL=openai_compatible\n"
        "HARNESS_LLM_BASE_URL=https://bailian.example/v1\n"
        "HARNESS_LLM_API_KEY=private-api-key\n"
        "HARNESS_LLM_MODEL_WEAK=deepseek-v4-flash\n"
        "HARNESS_LLM_PROVIDER=aliyun\n"
        "HARNESS_LLM_PROTOCOL=openai_compatible\n"
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
    arguments = [phase]
    if phase == "retry-vlm":
        arguments.extend(("--knowledge-id", "vlm-knowledge-1"))
    assert (
        module.main(
            arguments, adapter=Adapter(), lock_verifier=ResolvedLocks(), output=output
        )
        == 0
    )
    assert len(requests) == 1
    assert requests[0].phase == phase
    assert requests[0].delete_volumes is False
    assert requests[0].knowledge_id == (
        "vlm-knowledge-1" if phase == "retry-vlm" else None
    )
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


def test_r3_3_knowledge_id_is_required_only_for_explicit_retry() -> None:
    module = _module()
    calls: list[PhaseRequestLike] = []

    class Adapter:
        def run(self, request: PhaseRequestLike) -> object:
            calls.append(request)
            return {"status": "failed", "knowledge_id": request.knowledge_id}

    missing = StringIO()
    assert module.main(
        ["retry-vlm"],
        adapter=Adapter(),
        lock_verifier=ResolvedLocks(),
        output=StringIO(),
        error=missing,
    ) == 2
    assert calls == []
    assert "--knowledge-id is required" in missing.getvalue()

    invalid = StringIO()
    assert module.main(
        ["smoke-vlm", "--knowledge-id", "vlm-knowledge-1"],
        adapter=Adapter(),
        lock_verifier=ResolvedLocks(),
        output=StringIO(),
        error=invalid,
    ) == 2
    assert calls == []
    assert "valid only for retry-vlm" in invalid.getvalue()


def test_r3_3_retry_vlm_consumes_marker_after_identity_before_single_reparse(
    tmp_path: Path,
) -> None:
    module = _module()
    runtime = tmp_path / ".env.local-live.runtime"
    runtime.write_text("opaque runtime\n")
    runtime.chmod(0o600)
    fixture = tmp_path / "vlm-canary.png"
    fixture.write_bytes(b"safe visual fixture")
    process_config = {
        "enable_multimodel": True,
        "vlm_config": {"enabled": True, "model_id": "vlm-model"},
    }
    config_digest = sha256(
        json.dumps(process_config, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    calls: list[str] = []
    resolver_calls: list[str] = []
    attempt_calls = 0

    class Client:
        async def get_knowledge(self, key: object, knowledge_id: str) -> dict[str, object]:
            del key
            calls.append(f"get:{knowledge_id}")
            return {
                "id": knowledge_id,
                "knowledge_base_id": "raw-kb",
                "parse_status": "failed",
                "metadata": {
                    "owner": "insurancekb-local-live-v1",
                    "sha256": sha256(fixture.read_bytes()).hexdigest(),
                    "purpose": "vlm-smoke",
                    "vlm_model_id": "vlm-model",
                    "process_config_sha256": config_digest,
                    "process_overrides": process_config,
                },
                "error": "provider-secret raw provider response",
            }

        async def get_knowledge_parse_attempt(
            self, key: object, knowledge_id: str
        ) -> int:
            nonlocal attempt_calls
            del key
            attempt_calls += 1
            calls.append(f"attempt:{knowledge_id}:{attempt_calls}")
            return attempt_calls

        async def reparse_knowledge(
            self,
            key: object,
            knowledge_id: str,
            config: object,
        ) -> dict[str, object]:
            del key, config
            calls.append(f"reparse:{knowledge_id}")
            return {"id": knowledge_id}

        async def aclose(self) -> None:
            calls.append("close")

    class Resolver:
        async def resolve(self, values: object = None) -> SecretStr:
            resolver_calls.append("resolve")
            return SecretStr("tenant-key")

    collaborator = module.VLMSmokeCollaborator(
        runtime_path=runtime,
        fixture_path=fixture,
        runtime_loader=lambda path: {
            "LOCAL_LIVE_RAW_KB_ID": "raw-kb",
            "LOCAL_LIVE_VLLM_MODEL_ID": "vlm-model",
        },
        client_factory=lambda url: Client(),
        api_key_resolver=Resolver(),
        poll_interval=0,
    )
    request = module.PhaseRequest("retry-vlm", False, None, "vlm-knowledge-1")

    result = collaborator.run(request)
    assert result["knowledge_id"] == "vlm-knowledge-1"
    assert result["attempt"] == 2
    assert result["error_class"] == "knowledge_parse_failed"
    assert "provider-secret" not in repr(result)

    assert sum(call.startswith("reparse:") for call in calls) == 1
    assert resolver_calls == ["resolve"]
    assert attempt_calls == 2
    api_calls = tuple(calls)
    marker = next(tmp_path.glob(".env.local-live.runtime.retry-vlm-*"))
    assert S_IMODE(marker.stat().st_mode) == 0o600
    with pytest.raises(RuntimeError, match="retry"):
        collaborator.run(request)
    assert tuple(calls) == api_calls
    assert resolver_calls == ["resolve"]
    assert attempt_calls == 2


@pytest.mark.parametrize(
    ("attempts", "expected_reparse_count"),
    (([None], 0), ([2, 2], 1), ([2, 4], 1)),
)
def test_r3_3_retry_uses_real_span_attempt_and_rejects_missing_or_nonincremented_attempt(
    tmp_path: Path,
    attempts: list[int | None],
    expected_reparse_count: int,
) -> None:
    module = _module()
    runtime = tmp_path / ".env.local-live.runtime"
    runtime.write_text("opaque runtime\n")
    runtime.chmod(0o600)
    fixture = tmp_path / "vlm-canary.png"
    fixture.write_bytes(b"safe visual fixture")
    process_config = {
        "enable_multimodel": True,
        "vlm_config": {"enabled": True, "model_id": "vlm-model"},
    }
    config_digest = sha256(
        json.dumps(process_config, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    calls: list[str] = []
    remaining_attempts = list(attempts)

    class Client:
        async def get_knowledge(self, key: object, knowledge_id: str) -> dict[str, object]:
            del key
            calls.append(f"get:{knowledge_id}")
            return {
                "id": knowledge_id,
                "knowledge_base_id": "raw-kb",
                "parse_status": "failed",
                "metadata": {
                    "owner": "insurancekb-local-live-v1",
                    "sha256": sha256(fixture.read_bytes()).hexdigest(),
                    "purpose": "vlm-smoke",
                    "vlm_model_id": "vlm-model",
                    "process_config_sha256": config_digest,
                    "process_overrides": process_config,
                },
            }

        async def get_knowledge_parse_attempt(
            self, key: object, knowledge_id: str
        ) -> object:
            del key
            calls.append(f"attempt:{knowledge_id}")
            return remaining_attempts.pop(0)

        async def reparse_knowledge(
            self, key: object, knowledge_id: str, config: object
        ) -> dict[str, object]:
            del key, config
            calls.append(f"reparse:{knowledge_id}")
            return {"id": knowledge_id}

        async def aclose(self) -> None:
            calls.append("close")

    class Resolver:
        async def resolve(self, values: object = None) -> SecretStr:
            return SecretStr("tenant-key")

    collaborator = module.VLMSmokeCollaborator(
        runtime_path=runtime,
        fixture_path=fixture,
        runtime_loader=lambda path: {
            "LOCAL_LIVE_RAW_KB_ID": "raw-kb",
            "LOCAL_LIVE_VLLM_MODEL_ID": "vlm-model",
        },
        client_factory=lambda url: Client(),
        api_key_resolver=Resolver(),
        poll_interval=0,
    )

    with pytest.raises(RuntimeError, match="retry"):
        collaborator.run(
            module.PhaseRequest("retry-vlm", False, None, "vlm-knowledge-1")
        )

    assert sum(call.startswith("reparse:") for call in calls) == expected_reparse_count
    markers = tuple(tmp_path.glob(".env.local-live.runtime.retry-vlm-*"))
    assert bool(markers) is bool(expected_reparse_count)


@pytest.mark.parametrize(
    "mutation",
    ("kb", "owner", "sha", "purpose", "vlm_model", "process_config", "completed"),
)
def test_r3_3_retry_rejects_arbitrary_knowledge_before_marker_and_reparse(
    tmp_path: Path,
    mutation: str,
) -> None:
    module = _module()
    runtime = tmp_path / ".env.local-live.runtime"
    runtime.write_text("opaque runtime\n")
    runtime.chmod(0o600)
    fixture = tmp_path / "vlm-canary.png"
    fixture.write_bytes(b"safe visual fixture")
    fixture_digest = sha256(fixture.read_bytes()).hexdigest()
    process_config = {
        "enable_multimodel": True,
        "vlm_config": {"enabled": True, "model_id": "vlm-model"},
    }
    config_digest = sha256(
        json.dumps(process_config, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    metadata: dict[str, object] = {
        "owner": "insurancekb-local-live-v1",
        "sha256": fixture_digest,
        "purpose": "vlm-smoke",
        "vlm_model_id": "vlm-model",
        "process_config_sha256": config_digest,
    }
    record: dict[str, object] = {
        "id": "vlm-knowledge-1",
        "knowledge_base_id": "raw-kb",
        "parse_status": "failed",
        "metadata": metadata,
    }
    metadata["process_overrides"] = process_config
    if mutation == "kb":
        record["knowledge_base_id"] = "other-kb"
    elif mutation in {"owner", "purpose"}:
        metadata[mutation] = "wrong"
    elif mutation == "sha":
        metadata["sha256"] = "0" * 64
    elif mutation == "vlm_model":
        metadata["vlm_model_id"] = "other-vlm"
    elif mutation == "process_config":
        metadata["process_overrides"] = {
            **process_config,
            "vlm_config": {"enabled": True, "model_id": "other-vlm"},
        }
    else:
        record["parse_status"] = "completed"
    calls: list[str] = []

    class Client:
        async def get_knowledge(self, key: object, knowledge_id: str) -> dict[str, object]:
            del key
            calls.append(f"get:{knowledge_id}")
            return record

        async def reparse_knowledge(self, *args: object, **kwargs: object) -> object:
            calls.append("reparse")
            raise AssertionError("arbitrary knowledge must not be reparsed")

        async def upload_file(self, *args: object, **kwargs: object) -> object:
            calls.append("upload")
            raise AssertionError("retry must not upload")

        async def aclose(self) -> None:
            calls.append("close")

    class Resolver:
        async def resolve(self, values: object = None) -> SecretStr:
            return SecretStr("tenant-key")

    collaborator = module.VLMSmokeCollaborator(
        runtime_path=runtime,
        fixture_path=fixture,
        runtime_loader=lambda path: {
            "LOCAL_LIVE_RAW_KB_ID": "raw-kb",
            "LOCAL_LIVE_VLLM_MODEL_ID": "vlm-model",
        },
        client_factory=lambda url: Client(),
        api_key_resolver=Resolver(),
        poll_interval=0,
    )
    request = module.PhaseRequest("retry-vlm", False, None, "vlm-knowledge-1")

    with pytest.raises(RuntimeError, match="retry"):
        collaborator.run(request)

    assert calls == ["get:vlm-knowledge-1", "close"]
    assert not tuple(tmp_path.glob(".env.local-live.runtime.retry-vlm-*"))


def test_r3_3_dirty_implementation_evidence_hashes_tracked_and_untracked_content(
    tmp_path: Path,
) -> None:
    module = _module()
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    subprocess.run(
        ("git", "config", "user.email", "local@example.invalid"),
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(("git", "config", "user.name", "Local Test"), cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("base\n")
    subprocess.run(("git", "add", "tracked.txt"), cwd=tmp_path, check=True)
    subprocess.run(("git", "commit", "-qm", "base"), cwd=tmp_path, check=True)
    tracked.write_text("changed\n")
    untracked = tmp_path / "untracked.txt"
    untracked.write_text("first\n")

    first = module._implementation_evidence(tmp_path)
    untracked.write_text("second\n")
    second = module._implementation_evidence(tmp_path)

    assert first["head"] == second["head"]
    assert first["dirty"] is True
    assert first["evidence"] == "provisional"
    assert first["diff_digest"] != second["diff_digest"]
    tracked.write_text("base\n")
    untracked.unlink()
    clean = module._implementation_evidence(tmp_path)
    assert clean == {
        "implementation_sha": first["head"],
        "dirty": False,
        "evidence": "exact",
    }


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


def test_r3_1_compose_up_verifies_both_rendered_configs_before_mutation(
    tmp_path: Path,
) -> None:
    module = _module()
    runtime = tmp_path / ".env.local-live.runtime"
    runtime.write_text("runtime=opaque\n")
    image_lock = tmp_path / "images.lock"
    image_lock.write_text(json.dumps({"_status": "RESOLVED", "app": "locked"}))
    events: list[str] = []

    class Runner:
        def __call__(
            self,
            arguments: tuple[str, ...],
            *,
            cwd: Path,
            capture_output: bool,
        ) -> subprocess.CompletedProcess[str]:
            assert cwd == tmp_path
            assert arguments[:4] == ("docker", "compose", "--env-file", str(runtime))
            group = "harness" if "docker-compose.harness.yml" in arguments else "weknora"
            project_index = arguments.index("--project-name")
            assert arguments[project_index + 1] == (
                "insurancekb-harness-live"
                if group == "harness"
                else "insurancekb-local-live"
            )
            if "config" in arguments:
                action = "config"
            elif "port" in arguments:
                action = "port"
            else:
                action = "up"
                assert "--wait" in arguments
            events.append(f"command:{group}:{action}")
            return subprocess.CompletedProcess(
                arguments,
                0,
                stdout=(
                    '{"services": {}}'
                    if action == "config"
                    else "127.0.0.1:8080\n"
                    if action == "port"
                    else ""
                ),
                stderr="",
            )

    def verify_weknora(document: object, lock: object) -> None:
        events.append("verify:weknora")

    def verify_harness(document: object, lock: object) -> None:
        events.append("verify:harness")

    collaborator = module.ComposeCollaborator(
        repo_root=tmp_path,
        runtime_path=runtime,
        image_lock_path=image_lock,
        runner=Runner(),
        weknora_verifier=verify_weknora,
        harness_verifier=verify_harness,
    )

    result = collaborator.run(module.PhaseRequest("up", False))

    assert result == {"status": "started", "services": 6}
    assert events == [
        "command:weknora:config",
        "verify:weknora",
        "command:harness:config",
        "verify:harness",
        "command:weknora:up",
        "command:harness:up",
        "command:weknora:port",
        "command:weknora:port",
        "command:harness:port",
    ]

def test_r3_1_compose_down_deletes_volumes_only_after_explicit_request(
    tmp_path: Path,
) -> None:
    module = _module()
    commands: list[tuple[str, ...]] = []

    class Runner:
        def __call__(
            self,
            arguments: tuple[str, ...],
            *,
            cwd: Path,
            capture_output: bool,
        ) -> subprocess.CompletedProcess[str]:
            commands.append(arguments)
            return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    collaborator = module.ComposeCollaborator(
        repo_root=tmp_path,
        runtime_path=tmp_path / ".env.local-live.runtime",
        image_lock_path=tmp_path / "images.lock",
        runner=Runner(),
    )

    collaborator.run(module.PhaseRequest("down", False))
    assert all("--volumes" not in command for command in commands)
    commands.clear()
    collaborator.run(module.PhaseRequest("down", True))
    assert len(commands) == 2
    assert all("--volumes" in command for command in commands)


def test_r3_1_provision_collaborator_probes_before_operation_and_persists_state(
    tmp_path: Path,
) -> None:
    module = _module()
    config_path, runtime_path = _write_local_envs(tmp_path)
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(b"%PDF-1.4 local-live fixture")
    config = module.load_local_live_config(config_path)
    events: list[str] = []
    state = {
        "LOCAL_LIVE_TENANT_ID": "tenant-1",
        "LOCAL_LIVE_CHAT_MODEL_ID": "chat-1",
        "LOCAL_LIVE_EMBEDDING_MODEL_ID": "embedding-1",
        "LOCAL_LIVE_RERANK_MODEL_ID": "rerank-1",
        "LOCAL_LIVE_VLLM_MODEL_ID": "vlm-1",
        "LOCAL_LIVE_CHAT_ENDPOINT_FINGERPRINT": "a" * 64,
        "LOCAL_LIVE_EMBEDDING_ENDPOINT_FINGERPRINT": "b" * 64,
        "LOCAL_LIVE_RERANK_ENDPOINT_FINGERPRINT": "c" * 64,
        "LOCAL_LIVE_VLLM_ENDPOINT_FINGERPRINT": "d" * 64,
        "LOCAL_LIVE_RAW_KB_ID": "raw-1",
        "LOCAL_LIVE_WIKI_KB_ID": "wiki-1",
        "LOCAL_LIVE_API_KEY_ID": "key-1",
        "LOCAL_LIVE_SPACE_ID": "space-1",
        "LOCAL_LIVE_KNOWLEDGE_ID": "knowledge-1",
        "LOCAL_LIVE_PARSER_FINGERPRINT": "weknora-v0.6.3",
    }

    async def prober(configuration: object) -> object:
        assert configuration is config
        events.append("probe")
        return {
            "weknora_embedding": SimpleNamespace(embedding_dimension=1024),
        }

    class Operation:
        async def provision(
            self,
            configuration: object,
            runtime: Path,
            source_pdf: Path,
            embedding_dimension: int,
        ) -> dict[str, str]:
            assert configuration is config
            assert runtime == runtime_path
            assert source_pdf == pdf
            assert embedding_dimension == 1024
            events.append("provision")
            return state

    collaborator = module.ProvisionCollaborator(
        config=config,
        runtime_path=runtime_path,
        prober=prober,
        operation=Operation(),
    )

    result = collaborator.run(module.PhaseRequest("provision", False, pdf))

    assert events == ["probe", "provision"]
    assert result == {"status": "provisioned", "resources": 11}
    persisted = read_runtime_environment(runtime_path)
    assert {name: persisted[name] for name in state} == state


def test_r3_3_real_pre_task4_runtime_is_atomically_scrubbed_and_requires_reprovision(
    tmp_path: Path,
) -> None:
    module = _module()
    config_path, runtime_path = _write_local_envs(tmp_path)
    base = read_runtime_environment(runtime_path)
    old_state = {
        "LOCAL_LIVE_TENANT_ID": "tenant-1",
        "LOCAL_LIVE_CHAT_MODEL_ID": "chat-1",
        "LOCAL_LIVE_EMBEDDING_MODEL_ID": "embedding-1",
        "LOCAL_LIVE_RERANK_MODEL_ID": "rerank-1",
        "LOCAL_LIVE_RAW_KB_ID": "raw-1",
        "LOCAL_LIVE_WIKI_KB_ID": "wiki-1",
        "LOCAL_LIVE_API_KEY_ID": "key-1",
        "LOCAL_LIVE_API_KEY": "pre-task4-tenant-secret",
        "LOCAL_LIVE_SPACE_ID": "space-1",
        "LOCAL_LIVE_KNOWLEDGE_ID": "knowledge-1",
        "LOCAL_LIVE_PARSER_FINGERPRINT": "weknora-v0.6.3",
    }
    runtime_path.write_text(
        "".join(
            f"{name}={value}\n"
            for name, value in {**base, **old_state}.items()
        )
    )
    runtime_path.chmod(0o600)

    assert module.ensure_runtime_environment(runtime_path).created is False

    rewritten = read_runtime_environment(runtime_path)
    assert rewritten == base
    assert not any(name.startswith("LOCAL_LIVE_") for name in rewritten)
    assert b"pre-task4-tenant-secret" not in runtime_path.read_bytes()
    assert S_IMODE(runtime_path.stat().st_mode) == 0o600

    class Operation:
        async def provision(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("verify must fail before provisioning")

    collaborator = module.ProvisionCollaborator(
        config=module.load_local_live_config(config_path),
        runtime_path=runtime_path,
        operation=Operation(),
    )
    with pytest.raises(RuntimeError, match="not provisioned"):
        collaborator.run(module.PhaseRequest("verify", False))


def test_r3_3_local_gate_resolves_api_key_in_memory_for_exact_seven_live_values(
    tmp_path: Path,
) -> None:
    module = _module()
    _, runtime_path = _write_local_envs(tmp_path)
    module.ensure_runtime_environment(runtime_path)
    update_runtime_state(
        runtime_path,
        {
            "LOCAL_LIVE_TENANT_ID": "tenant-1",
            "LOCAL_LIVE_CHAT_MODEL_ID": "chat-1",
            "LOCAL_LIVE_EMBEDDING_MODEL_ID": "embedding-1",
            "LOCAL_LIVE_RERANK_MODEL_ID": "rerank-1",
            "LOCAL_LIVE_VLLM_MODEL_ID": "vlm-1",
            "LOCAL_LIVE_CHAT_ENDPOINT_FINGERPRINT": "a" * 64,
            "LOCAL_LIVE_EMBEDDING_ENDPOINT_FINGERPRINT": "b" * 64,
            "LOCAL_LIVE_RERANK_ENDPOINT_FINGERPRINT": "c" * 64,
            "LOCAL_LIVE_VLLM_ENDPOINT_FINGERPRINT": "d" * 64,
            "LOCAL_LIVE_RAW_KB_ID": "raw-1",
            "LOCAL_LIVE_WIKI_KB_ID": "wiki-1",
            "LOCAL_LIVE_API_KEY_ID": "key-1",
            "LOCAL_LIVE_SPACE_ID": "space-1",
            "LOCAL_LIVE_KNOWLEDGE_ID": "knowledge-1",
            "LOCAL_LIVE_PARSER_FINGERPRINT": "weknora-v0.6.3",
        },
    )
    captured: dict[str, str] = {}

    class Resolver:
        async def resolve(self, runtime: object) -> SecretStr:
            assert "LOCAL_LIVE_API_KEY" not in cast(dict[str, str], runtime)
            return SecretStr("tenant-secret")

    class Runner:
        def __call__(
            self,
            arguments: tuple[str, ...],
            *,
            cwd: Path,
            environment: dict[str, str],
        ) -> subprocess.CompletedProcess[str]:
            assert cwd == tmp_path / "harness"
            assert arguments[1:] == (
                "scripts/run_live_gate.py",
                "--manifest",
                "live-nodes.txt",
                "--report",
                "reports/local-live.xml",
            )
            captured.update(
                {
                    name: value
                    for name, value in environment.items()
                    if name.startswith("HARNESS_LIVE_")
                }
            )
            assert "WEKNORA_ADMIN_PASSWORD" not in environment
            assert "HARNESS_LLM_API_KEY" not in environment
            return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    collaborator = module.LocalGateCollaborator(
        harness_root=tmp_path / "harness",
        runtime_path=runtime_path,
        api_key_resolver=Resolver(),
        runner=Runner(),
    )

    assert collaborator.run(module.PhaseRequest("run-local", False)) == {
        "status": "passed",
        "tests": 5,
    }
    assert captured == {
        "HARNESS_LIVE_API_KEY": "tenant-secret",
        "HARNESS_LIVE_DB_URL": (
            "postgresql+psycopg://harness:"
            + "h" * 32
            + "@127.0.0.1:5442/insurance_kb"
        ),
        "HARNESS_LIVE_BASE_URL": "http://127.0.0.1:8080",
        "HARNESS_LIVE_SPACE_ID": "space-1",
        "HARNESS_LIVE_KNOWLEDGE_ID": "knowledge-1",
        "HARNESS_LIVE_PARSER_FINGERPRINT": "weknora-v0.6.3",
        "HARNESS_LIVE_KB_ID": "wiki-1",
    }
