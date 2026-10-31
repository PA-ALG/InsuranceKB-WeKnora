"""Exact-image smoke: compose topology, runner order and receipt validation."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from tests.service_shell.app_build.docker_helpers import _is_docker_build
from tests.service_shell.app_build.exact_image_helpers import (
    D3Runner,
    _d2_receipt,
    _d3_call,
    _d3_mutation_calls,
    _is_docker_pull,
)
from tests.service_shell.app_build.helpers import (
    D3_NONCE,
    EXACT_COMPOSE_PATH,
    IMAGE_ID,
    REPO_ROOT,
    RecordedCall,
    _json_text,
    _smoke_module,
)
from tests.service_shell.app_build.lock_helpers import _has_ignored_failure

# BA0-REQ-05/06: standalone exact-image artifact smoke and zero effects.


def _compose_script_operand(value: object, *, healthcheck: bool) -> str:
    assert isinstance(value, list), "smoke command must use executable argv form"
    if healthcheck:
        assert len(value) == 2 and value[0] == "CMD-SHELL", (
            "healthcheck must have exactly one CMD-SHELL script operand"
        )
        script = value[1]
    else:
        assert len(value) == 3 and value[:2] in (["/bin/sh", "-ec"], ["/bin/sh", "-ce"]), (
            "entrypoint must have exactly one /bin/sh -ec script operand"
        )
        script = value[2]
    assert isinstance(script, str) and script.strip()
    return script


def _assert_fail_fast_healthcheck(script: str) -> None:
    assert re.match(r"^\s*set\s+-[a-z]*e[a-z]*(?:\s+-[a-z]+)*\s*(?:;|\n)", script), (
        "healthcheck script must begin with set -e fail-fast semantics"
    )
    assert "||" not in script, "healthcheck checks must not ignore failure with ||"
    assert not re.search(r"(?:;|&&|\|\|)\s*(?:true|:|exit\s+0)\s*$", script.strip()), (
        "healthcheck must not mask checks with unconditional trailing success"
    )


def test_d3_exact_image_compose_is_single_service_read_only_and_standalone() -> None:
    document = yaml.safe_load(
        EXACT_COMPOSE_PATH.read_text(encoding="utf-8")
        if EXACT_COMPOSE_PATH.is_file()
        else pytest.fail(
            "planned BA0 standalone Compose missing: "
            "deploy/local-build/docker-compose.app-exact.yml"
        )
    )
    assert isinstance(document, dict)
    assert set(document) <= {"services"}
    assert set(document["services"]) == {"app-smoke"}
    service = document["services"]["app-smoke"]

    assert service["pull_policy"] == "never"
    assert "BA0_APP_IMAGE" in service["image"]
    assert service["network_mode"] == "none"
    assert service["read_only"] is True
    assert "/tmp" in service["tmpfs"]
    assert str(service["environment"]["AUTO_MIGRATE"]).lower() == "false"
    for forbidden in (
        "build",
        "ports",
        "volumes",
        "container_name",
        "env_file",
        "depends_on",
        "networks",
        "links",
    ):
        assert forbidden not in service

    entrypoint = _compose_script_operand(service["entrypoint"], healthcheck=False)
    healthcheck = _compose_script_operand(service["healthcheck"]["test"], healthcheck=True)
    _assert_fail_fast_healthcheck(healthcheck)
    for command in (entrypoint, healthcheck):
        assert re.search(r"\btest\s+-x\s+['\"]?/app/WeKnora\b", command)
        assert re.search(r"\bldd\s+['\"]?/app/WeKnora\b", command)
        assert re.search(
            r"\btest\s+-x\s+['\"]?/opt/weknora/browserskill/bsk\b", command
        )
        assert re.search(r"\bldd\s+['\"]?/opt/weknora/browserskill/bsk\b", command)
        assert "not found" in command.lower() and re.search(r"\bgrep\b", command)
        assert "!" in command or re.search(r"\bexit\s+1\b", command)
        assert not _has_ignored_failure(command)

    combined_commands = f"{entrypoint}\n{healthcheck}"
    for required_path in (
        "/app/WeKnora",
        "/app/config",
        "/app/scripts",
        "/app/migrations",
        "/app/dataset/samples",
        "/home/appuser/.duckdb",
        "/app/LICENSE",
        "/app/THIRD_PARTY_NOTICES.md",
        "/app/licenses",
        "/opt/weknora/browserskill/bsk",
        "/opt/weknora/browserskill/browser-skill-weknora-0.3.1.zip",
        "/opt/weknora/browserskill/BrowserSkill-LICENSE",
    ):
        assert re.search(
            rf"\btest\s+-[derx]\s+['\"]?{re.escape(required_path)}\b",
            combined_commands,
        )
    assert re.search(
        r"\bsleep\s+infinity\b|\btail\s+-f\s+/dev/null\b|"
        r"\bwhile\s+(?::|true)\s*;?\s*do\b.*\bsleep\b.*\bdone\b",
        entrypoint,
        re.S,
    ), "entrypoint must keep the verified container alive"

    public = _json_text(document).lower()
    assert "http" not in public
    for forbidden in (
        "postgres",
        "redis",
        "docreader",
        "provider",
        "8081",
    ):
        assert forbidden not in public


def _assert_compose_argv(call: RecordedCall, *, action: str) -> Path:
    arguments = call.arguments
    env_path = Path(arguments[arguments.index("--env-file") + 1])
    assert arguments == D3Runner._compose_arguments(env_path, action)
    return env_path


def test_d3_exact_image_runner_order_and_exact_no_build_no_pull_argv(
    tmp_path: Path,
) -> None:
    module = _smoke_module()
    runner = D3Runner()

    receipt = _d3_call(module, tmp_path, runner)

    assert runner.events == [
        "image-inspect",
        "compose-config",
        "project-collision",
        "compose-up",
        "runtime-inspect",
        "cleanup",
    ]
    config_call = next(call for call in runner.calls if "config" in call.arguments)
    up_call = next(call for call in runner.calls if "up" in call.arguments)
    down_call = next(call for call in runner.calls if "down" in call.arguments)
    config_env = _assert_compose_argv(config_call, action="config")
    up_env = _assert_compose_argv(up_call, action="up")
    down_env = _assert_compose_argv(down_call, action="down")
    assert config_env == up_env == down_env
    assert runner.env_files
    assert all(mode == 0o600 for _, mode, _ in runner.env_files)
    assert all(content == f"BA0_APP_IMAGE={IMAGE_ID}\n" for _, _, content in runner.env_files)
    assert receipt["status"] == "PASS"
    assert receipt["scope"] == "CONTAINER_ARTIFACT_SMOKE"
    assert runner.receipt_existed_at_cleanup is False
    assert sum(_is_docker_build(call.arguments) for call in runner.calls) == 0
    assert sum(_is_docker_pull(call.arguments) for call in runner.calls) == 0


def test_d3_exact_image_invalid_receipt_is_rejected_before_runner_or_mutation(
    tmp_path: Path,
) -> None:
    module = _smoke_module()
    receipt_path = tmp_path / "invalid-d2.json"
    receipt_path.write_text(
        json.dumps({"status": "PASS", "image_id": "wechatopenai/weknora-app:latest"}),
        encoding="utf-8",
    )
    runner = D3Runner()

    with pytest.raises(module.ArtifactSmokeError, match="receipt|image|sha256"):
        module.run_exact_image_smoke(
            repo_root=REPO_ROOT,
            d2_receipt_path=receipt_path,
            evidence_out=tmp_path / "d3.json",
            nonce="0123456789abcdef",
            runner=runner,
        )

    assert runner.calls == []
    assert _d3_mutation_calls(runner) == []


@pytest.mark.parametrize(
    ("field", "value", "label"),
    (
        ("integration_head", "CANARY-SECRET-PROVENANCE", None),
        (
            "artifact_identity",
            "sha256:CANARY-SECRET-PROVENANCE",
            "io.insurancekb.app.artifact-identity",
        ),
        (
            "manifest_sha256",
            "CANARY-SECRET-PROVENANCE",
            "io.insurancekb.app.manifest-sha256",
        ),
        (
            "dependency_lock_sha256",
            "CANARY-SECRET-PROVENANCE",
            "io.insurancekb.app.dependency-lock-sha256",
        ),
    ),
    ids=("integration-head", "artifact-identity", "manifest", "dependency-lock"),
)
def test_d3_malformed_provenance_is_rejected_before_runner_or_copy(
    tmp_path: Path,
    field: str,
    value: str,
    label: str | None,
) -> None:
    module = _smoke_module()
    d2_receipt_path = tmp_path / "d2-malformed-provenance.json"
    d2_receipt = _d2_receipt(d2_receipt_path)
    d2_receipt[field] = value
    if label is not None:
        d2_receipt["labels"][label] = value
    d2_receipt_path.write_text(json.dumps(d2_receipt, sort_keys=True) + "\n", encoding="utf-8")
    evidence_path = tmp_path / "d3.json"
    runner = D3Runner()

    with pytest.raises(
        module.ArtifactSmokeError,
        match="provenance|commit|identity|sha256|hash",
    ):
        module.run_exact_image_smoke(
            repo_root=REPO_ROOT,
            d2_receipt_path=d2_receipt_path,
            evidence_out=evidence_path,
            nonce=D3_NONCE,
            runner=runner,
        )

    assert runner.calls == []
    assert _d3_mutation_calls(runner) == []
    assert not evidence_path.exists()
