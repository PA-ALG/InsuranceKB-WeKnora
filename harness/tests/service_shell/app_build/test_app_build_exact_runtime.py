"""Exact-image smoke: preflight, collisions, cleanup and the runtime receipt."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.service_shell.app_build.docker_helpers import _image_inspect, _is_docker_build
from tests.service_shell.app_build.exact_image_helpers import (
    D3Runner,
    _d2_receipt,
    _d3_call,
    _d3_mutation_calls,
    _valid_rendered_compose,
)
from tests.service_shell.app_build.helpers import (
    CANARY_SECRET,
    D3_NONCE,
    IMAGE_ID,
    REPO_ROOT,
    REQUIRED_LABELS,
    _smoke_module,
)


def test_d3_existing_evidence_path_is_rejected_before_runner_or_mutation(
    tmp_path: Path,
) -> None:
    module = _smoke_module()
    d2_receipt_path = tmp_path / "d2.json"
    evidence_path = tmp_path / "stale-d3.json"
    _d2_receipt(d2_receipt_path)
    evidence_path.write_text('{"status":"PASS","stale":true}\n', encoding="utf-8")
    runner = D3Runner()

    with pytest.raises(module.ArtifactSmokeError, match="evidence|exist|output"):
        module.run_exact_image_smoke(
            repo_root=REPO_ROOT,
            d2_receipt_path=d2_receipt_path,
            evidence_out=evidence_path,
            nonce=D3_NONCE,
            runner=runner,
        )

    assert runner.calls == []
    assert _d3_mutation_calls(runner) == []


@pytest.mark.parametrize(
    ("case", "inspect", "message"),
    (
        ("image", _image_inspect(image_id="sha256:" + "e" * 64), "image|identity"),
        (
            "label",
            _image_inspect(
                labels={
                    **REQUIRED_LABELS,
                    "io.insurancekb.app.build-source-head": "f" * 40,
                }
            ),
            "label|build.source",
        ),
        ("platform", _image_inspect(architecture="amd64"), "arm64|arch|platform"),
    ),
    ids=("image-id", "label", "platform"),
)
def test_d3_exact_image_preflight_failure_has_zero_mutations(
    tmp_path: Path,
    case: str,
    inspect: str,
    message: str,
) -> None:
    del case
    module = _smoke_module()
    runner = D3Runner(source_inspect=inspect)

    with pytest.raises(module.ArtifactSmokeError, match=message):
        _d3_call(module, tmp_path, runner)

    assert runner.events == ["image-inspect"]
    assert _d3_mutation_calls(runner) == []


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("ports", "port|topology|standalone"),
        ("privileged", "privileged|unknown|topology|standalone"),
        ("secret-environment", "environment|unknown|topology|standalone"),
        ("entrypoint-no-fail-fast", "fail.fast|set -e|entrypoint|command"),
        ("healthcheck-missing-path", "config|path|health|command"),
        ("commented-required-path", "comment|config|path|command"),
        ("no-op-required-path", "entrypoint|health|command|contract"),
        ("trailing-decoy", "argv|operand|entrypoint|smoke|command"),
        ("masking-healthcheck", "health|fail.fast|mask|command"),
    ),
)
def test_d3_exact_image_static_topology_or_argv_failure_precedes_collision_with_zero_mutations(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    module = _smoke_module()
    rendered = _valid_rendered_compose()
    service = rendered["services"]["app-smoke"]
    if mutation == "ports":
        service["ports"] = ["8081:8080"]
    elif mutation == "privileged":
        service["privileged"] = True
        service["pid"] = "host"
        service["devices"] = ["/dev/null:/dev/ba0"]
    elif mutation == "secret-environment":
        service["environment"]["OPENAI_API_KEY"] = CANARY_SECRET
    elif mutation == "entrypoint-no-fail-fast":
        assert isinstance(service["entrypoint"], list)
        service["entrypoint"][2] = service["entrypoint"][2].replace("set -eu\n", "true\n", 1)
    elif mutation == "healthcheck-missing-path":
        assert isinstance(service["healthcheck"]["test"], list)
        service["healthcheck"]["test"][1] = service["healthcheck"]["test"][1].replace(
            "test -d /app/config;", "", 1
        )
    elif mutation == "commented-required-path":
        assert isinstance(service["entrypoint"], list)
        service["entrypoint"][2] = service["entrypoint"][2].replace(
            "test -d /app/config", "# test -d /app/config", 1
        )
        assert isinstance(service["healthcheck"]["test"], list)
        service["healthcheck"]["test"][1] = service["healthcheck"]["test"][1].replace(
            "test -d /app/config", "# test -d /app/config", 1
        )
    elif mutation == "no-op-required-path":
        assert isinstance(service["entrypoint"], list)
        service["entrypoint"][2] = service["entrypoint"][2].replace(
            "test -d /app/config", ": test -d /app/config", 1
        )
        assert isinstance(service["healthcheck"]["test"], list)
        service["healthcheck"]["test"][1] = service["healthcheck"]["test"][1].replace(
            "test -d /app/config", ": test -d /app/config", 1
        )
    elif mutation == "trailing-decoy":
        assert isinstance(service["entrypoint"], list)
        service["entrypoint"] = [
            *service["entrypoint"],
            "test -x /app/WeKnora && ldd /app/WeKnora",
        ]
    else:
        healthcheck = service["healthcheck"]["test"]
        assert isinstance(healthcheck, list) and len(healthcheck) == 2
        original = healthcheck[1]
        healthcheck[1] = re.sub(
            r"(\btest\s+-x\s+['\"]?/app/WeKnora\b)",
            r"\1 || echo ignored",
            original,
            count=1,
        )
        assert healthcheck[1] != original
    runner = D3Runner(rendered_compose=rendered)

    with pytest.raises(module.ArtifactSmokeError, match=message):
        _d3_call(module, tmp_path, runner)

    assert runner.events == ["image-inspect", "compose-config"]
    assert _d3_mutation_calls(runner) == []


def test_d3_exact_image_project_collision_fails_before_up_with_zero_mutations(
    tmp_path: Path,
) -> None:
    module = _smoke_module()
    runner = D3Runner(collision=True)

    with pytest.raises(module.ArtifactSmokeError, match="collision|project"):
        _d3_call(module, tmp_path, runner)

    assert runner.events == ["image-inspect", "compose-config", "project-collision"]
    assert _d3_mutation_calls(runner) == []


def test_d3_exact_image_runtime_failure_still_cleans_up_before_failure_receipt(
    tmp_path: Path,
) -> None:
    module = _smoke_module()
    d2_receipt_path = tmp_path / "d2.json"
    evidence_path = tmp_path / "d3-failure.json"
    _d2_receipt(d2_receipt_path)
    runner = D3Runner(runtime_returncode=1)
    runner.evidence_path = evidence_path

    with pytest.raises(module.ArtifactSmokeError, match="runtime|inspect|health"):
        module.run_exact_image_smoke(
            repo_root=REPO_ROOT,
            d2_receipt_path=d2_receipt_path,
            evidence_out=evidence_path,
            nonce="0123456789abcdef",
            runner=runner,
        )

    assert runner.events[-2:] == ["runtime-inspect", "cleanup"]
    assert evidence_path.is_file()
    failure = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert failure["status"] == "FAIL"
    assert failure["cleanup"] == "PASS"
    assert runner.receipt_existed_at_cleanup is False


def test_d3_exact_image_receipt_proves_exact_runtime_and_all_forbidden_effects_zero(
    tmp_path: Path,
) -> None:
    module = _smoke_module()
    runner = D3Runner()

    receipt = _d3_call(module, tmp_path, runner)

    assert receipt["image_id"] == IMAGE_ID
    assert receipt["runtime_image_id"] == IMAGE_ID
    assert receipt["build_invocations"] == 0
    assert receipt["pull_invocations"] == 0
    assert receipt["cleanup"] == "PASS"
    assert receipt["effects"] == {
        "networks": 0,
        "published_ports": 0,
        "volumes": 0,
        "dependencies": 0,
        "provider_model": 0,
        "business_db": 0,
        "production_8081": 0,
        "production_active": 0,
        "g2": 0,
    }
    assert all(not _is_docker_build(call.arguments) for call in runner.calls)
