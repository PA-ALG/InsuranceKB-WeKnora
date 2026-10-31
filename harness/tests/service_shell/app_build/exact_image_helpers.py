"""Exact-image smoke contracts: receipts, rendered compose and the D3 runner."""

from __future__ import annotations

import json
import re
import stat
import subprocess
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from tests.service_shell.app_build.docker_helpers import _image_inspect, _is_docker_build
from tests.service_shell.app_build.helpers import (
    ARTIFACT_IDENTITY,
    BUILD_SOURCE_HEAD,
    CONTEXT,
    D3_CONTAINER,
    D3_NONCE,
    D3_PROJECT,
    EXACT_COMPOSE_PATH,
    IMAGE_ID,
    INTEGRATION_HEAD,
    LOCK_SHA256,
    MANIFEST_SHA256,
    PLATFORM,
    REPO_ROOT,
    REQUIRED_LABELS,
    FakeRunner,
    RecordedCall,
    Runner,
    _completed,
    _json_text,
)


def _d2_receipt(path: Path) -> dict[str, Any]:
    receipt = {
        "contract": "ba0-app-build-receipt.v1",
        "status": "PASS",
        "selector": "REUSE",
        "artifact_identity": ARTIFACT_IDENTITY,
        "image_id": IMAGE_ID,
        "build_source_head": BUILD_SOURCE_HEAD,
        "integration_head": INTEGRATION_HEAD,
        "manifest_sha256": MANIFEST_SHA256,
        "dependency_lock_sha256": LOCK_SHA256,
        "platform": PLATFORM,
        "target": "runtime",
        "labels": dict(REQUIRED_LABELS),
        "build_invocations": 0,
    }
    path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def _valid_rendered_compose() -> dict[str, Any]:
    assert EXACT_COMPOSE_PATH.is_file(), "planned BA0 standalone Compose missing"
    document = yaml.safe_load(EXACT_COMPOSE_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, dict)

    def substitute(value: object) -> object:
        if isinstance(value, str):
            return re.sub(
                r"\$\{BA0_APP_IMAGE(?::[-+?][^}]*)?\}|\$BA0_APP_IMAGE\b",
                IMAGE_ID,
                value,
            )
        if isinstance(value, list):
            return [substitute(item) for item in value]
        if isinstance(value, dict):
            return {key: substitute(item) for key, item in value.items()}
        return value

    rendered = substitute(document)
    assert isinstance(rendered, dict)
    assert "BA0_APP_IMAGE" not in _json_text(rendered)
    return rendered


class D3Runner(FakeRunner):
    def __init__(
        self,
        *,
        source_inspect: str | None = None,
        rendered_compose: Mapping[str, object] | None = None,
        collision: bool = False,
        runtime_returncode: int = 0,
    ) -> None:
        self.events: list[str] = []
        self._source_inspect = source_inspect or _image_inspect()
        self._rendered_compose = dict(rendered_compose or _valid_rendered_compose())
        self._collision = collision
        self._runtime_returncode = runtime_returncode
        self.env_files: list[tuple[Path, int, str]] = []
        self.env_path: Path | None = None
        self.evidence_path: Path | None = None
        self.receipt_existed_at_cleanup: bool | None = None
        super().__init__(self._respond)

    @staticmethod
    def _compose_arguments(env_path: Path, action: str) -> tuple[str, ...]:
        prefix = (
            "docker",
            "--context",
            CONTEXT,
            "compose",
            "--project-name",
            D3_PROJECT,
            "--env-file",
            str(env_path),
            "-f",
            "deploy/local-build/docker-compose.app-exact.yml",
        )
        suffixes = {
            "config": ("config", "--format", "json"),
            "up": (
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                "30",
                "--no-build",
                "--pull",
                "never",
                "app-smoke",
            ),
            "down": ("down", "--remove-orphans"),
        }
        return (*prefix, *suffixes[action])

    def _respond(
        self,
        arguments: tuple[str, ...],
        cwd: Path,
        kwargs: Mapping[str, object],
        index: int,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, kwargs, index
        assert arguments[:3] == ("docker", "--context", CONTEXT)
        assert not _is_docker_build(arguments), "D3 must never invoke docker build"

        if arguments[3:5] == ("image", "inspect"):
            expected = (
                "docker",
                "--context",
                CONTEXT,
                "image",
                "inspect",
                IMAGE_ID,
                "--format",
                "{{json .}}",
            )
            assert arguments == expected
            self.events.append("image-inspect")
            return _completed(arguments, stdout=self._source_inspect)

        collision_probe = (
            "docker",
            "--context",
            CONTEXT,
            "ps",
            "--all",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={D3_PROJECT}",
        )
        if arguments[3:4] == ("ps",):
            assert arguments == collision_probe
            self.events.append("project-collision")
            return _completed(arguments, stdout="occupied\n" if self._collision else "")

        runtime_inspect = (
            "docker",
            "--context",
            CONTEXT,
            "inspect",
            D3_CONTAINER,
            "--format",
            "{{json .}}",
        )
        if arguments[3:4] == ("inspect",):
            assert arguments == runtime_inspect
            self.events.append("runtime-inspect")
            return _completed(
                arguments,
                returncode=self._runtime_returncode,
                stdout=(
                    json.dumps(
                        {
                            "Id": "sha256:" + "7" * 64,
                            "Name": "/" + D3_CONTAINER,
                            "Image": IMAGE_ID,
                            "State": {
                                "Status": "running",
                                "Health": {"Status": "healthy"},
                            },
                        }
                    )
                    if self._runtime_returncode == 0
                    else ""
                ),
                stderr="runtime inspect failed" if self._runtime_returncode else "",
            )

        if arguments[3:4] == ("compose",):
            assert "--env-file" in arguments
            env_path = Path(arguments[arguments.index("--env-file") + 1])
            if self.env_path is None:
                self.env_path = env_path
            assert env_path == self.env_path
            self.env_files.append(
                (
                    env_path,
                    stat.S_IMODE(env_path.stat().st_mode),
                    env_path.read_text(encoding="utf-8"),
                )
            )
            if arguments == self._compose_arguments(env_path, "config"):
                self.events.append("compose-config")
                return _completed(arguments, stdout=json.dumps(self._rendered_compose))
            if arguments == self._compose_arguments(env_path, "up"):
                self.events.append("compose-up")
                return _completed(arguments)
            if arguments == self._compose_arguments(env_path, "down"):
                assert self.evidence_path is not None
                self.receipt_existed_at_cleanup = self.evidence_path.exists()
                self.events.append("cleanup")
                return _completed(arguments)

        raise AssertionError(f"unexpected D3 Docker command: {arguments!r}")


def _d3_call(
    module: ModuleType,
    tmp_path: Path,
    runner: Runner,
    *,
    nonce: str = D3_NONCE,
) -> dict[str, Any]:
    d2_receipt_path = tmp_path / "d2.json"
    evidence_path = tmp_path / "d3.json"
    _d2_receipt(d2_receipt_path)
    if isinstance(runner, D3Runner):
        runner.evidence_path = evidence_path
    result = module.run_exact_image_smoke(
        repo_root=REPO_ROOT,
        d2_receipt_path=d2_receipt_path,
        evidence_out=evidence_path,
        nonce=nonce,
        runner=runner,
    )
    assert isinstance(result, dict)
    assert evidence_path.is_file(), "D3 must write its receipt after cleanup"
    assert json.loads(evidence_path.read_text(encoding="utf-8")) == result
    return result


def _is_docker_pull(arguments: tuple[str, ...]) -> bool:
    tail = arguments[3:]
    if tail[:1] == ("pull",) or tail[:2] == ("image", "pull"):
        return True
    if tail[:1] == ("compose",):
        return "pull" in tail and "--pull" not in tail
    return False


def _d3_mutation_calls(runner: D3Runner) -> list[RecordedCall]:
    mutations: list[RecordedCall] = []
    for call in runner.calls:
        tail = call.arguments[3:]
        if _is_docker_build(call.arguments) or _is_docker_pull(call.arguments):
            mutations.append(call)
        elif tail[:1] in (("network",), ("volume",)):
            mutations.append(call)
        elif tail[:1] == ("compose",) and ("up" in tail or "down" in tail):
            mutations.append(call)
    return mutations
