"""Local-live CLI: compose up/down, provisioning, runtime scrubbing and the local gate."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from stat import S_IMODE
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import SecretStr

from insurance_harness.live_env.compose import (
    read_runtime_environment,
    update_runtime_state,
)
from tests.service_shell.local_live_cli.helpers import _module, _write_local_envs


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
