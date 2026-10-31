"""App build contracts: Docker inspect / build fakes and the image selector runner."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

from tests.service_shell.app_build.contract_helpers import _identity_record
from tests.service_shell.app_build.helpers import (
    CONTEXT,
    IMAGE_ID,
    REPO_ROOT,
    REQUIRED_LABELS,
    FakeRunner,
    RecordedCall,
    Runner,
    _completed,
    _dockerfile_instructions,
)


def _image_inspect(
    *,
    image_id: str = IMAGE_ID,
    os_name: str = "linux",
    architecture: str = "arm64",
    labels: Mapping[str, str] | None = None,
) -> str:
    return json.dumps(
        {
            "Id": image_id,
            "Os": os_name,
            "Architecture": architecture,
            "Config": {"Labels": dict(REQUIRED_LABELS if labels is None else labels)},
        }
    )


def _is_docker_build(arguments: tuple[str, ...]) -> bool:
    if not arguments or arguments[0] != "docker":
        return False
    tail = arguments[arguments.index(CONTEXT) + 1 :] if CONTEXT in arguments else arguments[1:]
    return bool(tail and (tail[0] == "build" or tail[:2] == ("buildx", "build")))


def _docker_build_args(call: RecordedCall) -> dict[str, str]:
    assert _is_docker_build(call.arguments)
    values: dict[str, str] = {}
    index = 0
    while index < len(call.arguments):
        argument = call.arguments[index]
        if argument == "--build-arg":
            index += 1
            assert index < len(call.arguments), "--build-arg lacks KEY=VALUE"
            item = call.arguments[index]
        elif argument.startswith("--build-arg="):
            item = argument.removeprefix("--build-arg=")
        else:
            index += 1
            continue
        assert "=" in item, f"build arg must freeze a value: {item!r}"
        name, value = item.split("=", 1)
        assert name and name not in values
        values[name] = value
        index += 1
    return values


def _docker_option_values(
    arguments: tuple[str, ...], option: str, *, short: str | None = None
) -> list[str]:
    values: list[str] = []
    for index, argument in enumerate(arguments):
        if argument == option or (short is not None and argument == short):
            assert index + 1 < len(arguments), f"{argument} lacks a value"
            values.append(arguments[index + 1])
        elif argument.startswith(option + "="):
            values.append(argument.removeprefix(option + "="))
    return values


def _effective_build_labels(arguments: tuple[str, ...], cwd: Path) -> dict[str, str]:
    labels: dict[str, str] = {}
    file_options = _docker_option_values(arguments, "--file", short="-f")
    assert len(file_options) <= 1
    if file_options:
        dockerfile = Path(file_options[0])
        if not dockerfile.is_absolute():
            dockerfile = cwd / dockerfile
    else:
        context = Path(arguments[-1])
        dockerfile = (context if context.is_absolute() else cwd / context) / "Dockerfile"

    variables = _docker_build_args(RecordedCall(arguments, cwd, {}))

    def expand(value: str) -> str:
        return re.sub(
            r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))",
            lambda match: variables.get(match.group(1) or match.group(2), match.group(0)),
            value,
        )

    if dockerfile.is_file():
        for instruction in _dockerfile_instructions(dockerfile.read_text(encoding="utf-8")):
            keyword, _, operands = instruction.partition(" ")
            if keyword == "FROM":
                labels = {}
            elif keyword == "ARG":
                for item in shlex.split(operands):
                    if "=" in item:
                        name, value = item.split("=", 1)
                        variables.setdefault(name, expand(value))
            elif keyword == "ENV":
                for item in shlex.split(operands):
                    if "=" in item:
                        name, value = item.split("=", 1)
                        variables[name] = expand(value)
            elif keyword == "LABEL":
                for item in shlex.split(operands):
                    assert "=" in item, "LABEL must carry an explicit key=value"
                    name, value = item.split("=", 1)
                    labels[name] = expand(value)

    for item in _docker_option_values(arguments, "--label"):
        assert "=" in item, "--label must carry an explicit key=value"
        name, value = item.split("=", 1)
        labels[name] = value
    return labels


def _selector_runner(
    *,
    candidates: str,
    inspect_stdout: str | None = None,
    inspect_returncode: int = 0,
    query_returncode: int = 0,
) -> FakeRunner:
    built_inspect: str | None = None

    def respond(
        arguments: tuple[str, ...],
        cwd: Path,
        kwargs: Mapping[str, object],
        index: int,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal built_inspect
        del kwargs, index
        assert arguments[:3] == ("docker", "--context", CONTEXT)
        if "image" in arguments and "ls" in arguments:
            return _completed(
                arguments,
                returncode=query_returncode,
                stdout=candidates,
                stderr="query failed" if query_returncode else "",
            )
        if _is_docker_build(arguments):
            if "--iidfile" in arguments:
                iidfile = Path(arguments[arguments.index("--iidfile") + 1])
                iidfile.write_text(IMAGE_ID + "\n", encoding="utf-8")
                built_image_id = iidfile.read_text(encoding="utf-8").strip()
                platforms = _docker_option_values(arguments, "--platform")
                if len(platforms) == 1 and re.fullmatch(r"[^/]+/[^/]+", platforms[0]):
                    built_os, built_arch = platforms[0].split("/", 1)
                else:
                    built_os, built_arch = "", ""
                built_inspect = _image_inspect(
                    image_id=built_image_id,
                    os_name=built_os,
                    architecture=built_arch,
                    labels=_effective_build_labels(arguments, cwd),
                )
            return _completed(arguments, stdout=f"built {IMAGE_ID}\n")
        if "inspect" in arguments:
            inspect = (
                inspect_stdout if inspect_stdout is not None else built_inspect or _image_inspect()
            )
            return _completed(
                arguments,
                returncode=inspect_returncode,
                stdout=inspect,
                stderr="inspect failed" if inspect_returncode else "",
            )
        raise AssertionError(f"unexpected selector command: {arguments!r}")

    return FakeRunner(respond)


def _selector_call(
    module: ModuleType,
    tmp_path: Path,
    runner: Runner,
    *,
    repo_root: Path = REPO_ROOT,
    secrets: Mapping[str, str] | None = None,
    budget: int = 1,
) -> dict[str, Any]:
    evidence = tmp_path / "selector-receipt.json"
    result = module.select_or_build_app(
        repo_root=repo_root,
        identity=_identity_record(),
        evidence_out=evidence,
        runner=runner,
        secret_values=dict(secrets or {}),
        real_build_budget_remaining=budget,
    )
    assert isinstance(result, dict)
    assert evidence.is_file(), "selector must write the requested receipt"
    assert json.loads(evidence.read_text(encoding="utf-8")) == result
    return result
