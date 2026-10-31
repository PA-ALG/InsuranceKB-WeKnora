"""App build: locked facts flow into the instructions that consume them."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path

import pytest

from tests.service_shell.app_build.contract_helpers import (
    _synthetic_dependency_lock,
    _write_synthetic_contract,
)
from tests.service_shell.app_build.docker_helpers import (
    _docker_build_args,
    _is_docker_build,
    _selector_call,
    _selector_runner,
)
from tests.service_shell.app_build.helpers import (
    DEPENDENCY_LOCK_PATH,
    DOCKERFILE_PATH,
    REPO_ROOT,
    _artifact_module,
    _load_json,
    _sha256_bytes,
)
from tests.service_shell.app_build.lock_helpers import (
    LockUse,
    _assert_build_arg_lock_dataflow,
    _assert_dependency_lock_dataflow,
    _assert_no_floating_or_ignored_installs,
    _build_args_cover_lock_uses,
    _dependency_lock_uses,
)


def test_python_tool_local_wheels_have_valid_matching_filenames() -> None:
    from packaging.utils import parse_wheel_filename

    lock = json.loads(DEPENDENCY_LOCK_PATH.read_text())
    dockerfile = DOCKERFILE_PATH.read_text()
    for name, tool in lock["python_tools"].items():
        variable = f"$BA0_PYTHON_TOOLS_{name.upper()}_VERSION"
        paths = re.findall(r'"(/tmp/[^"\n]+\.whl)"', dockerfile)
        paths = [path.replace(variable, tool["version"]) for path in paths if variable in path]
        assert paths, f"missing wheel consumption for {name}"
        for path in paths:
            distribution, version, _, tags = parse_wheel_filename(Path(path).name)
            assert distribution == name
            assert str(version) == tool["version"]
            assert tags
            assert Path(path).name == tool["origin"].rsplit("/", 1)[-1]


def test_dockerfile_build_path_wires_locked_facts_into_consuming_instructions(
    tmp_path: Path,
) -> None:
    module = _artifact_module()
    repo_root = tmp_path / "repository"
    _, lock_path = _write_synthetic_contract(repo_root)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    runner = _selector_runner(candidates="")

    _selector_call(module, tmp_path, runner, repo_root=repo_root)

    build_calls = [call for call in runner.calls if _is_docker_build(call.arguments)]
    assert len(build_calls) == 1
    build_args = _docker_build_args(build_calls[0])
    dockerfile_source = DOCKERFILE_PATH.read_text(encoding="utf-8")
    uses = _dependency_lock_uses(lock)
    dependency_uses = tuple(use for use in uses if not use.consumer.startswith("from-"))
    dependency_plan: Mapping[str, object] | None = None
    if not _build_args_cover_lock_uses(dependency_uses, build_args):
        plan_builder = getattr(module, "_dependency_plan", None)
        assert callable(plan_builder), (
            "copied-lock builds require the private _dependency_plan(lock) seam"
        )
        planned = plan_builder(lock)
        assert isinstance(planned, Mapping)
        assert plan_builder(lock) == planned, "dependency plan must be deterministic"
        rendered_plan = tmp_path / "rendered-dependency-plan.env"
        cli = subprocess.run(
            (
                sys.executable,
                "scripts/app_artifact.py",
                "dependency-plan",
                "--lock",
                str(lock_path),
                "--output",
                str(rendered_plan),
            ),
            cwd=REPO_ROOT,
            capture_output=True,
            text=False,
            check=False,
        )
        assert cli.returncode == 0, cli.stderr.decode(errors="replace")
        assert cli.stdout == b""
        assert cli.stderr == b""
        assert isinstance(planned.get("output_bytes"), bytes)
        assert rendered_plan.read_bytes() == planned["output_bytes"]
        dependency_plan = planned

    _assert_dependency_lock_dataflow(
        lock,
        build_args,
        dockerfile_source,
        dependency_plan,
    )


@pytest.mark.parametrize(
    "malicious_fixture",
    (
        "preassignment",
        "ignored-failure",
        "quoted-python-c",
        "empty-output",
        "wrong-value",
        "floating-install",
    ),
)
def test_lock_dataflow_guard_rejects_ineffective_consumers(
    malicious_fixture: str,
) -> None:
    if malicious_fixture == "floating-install":
        with pytest.raises(AssertionError, match="upgrade|pin"):
            _assert_no_floating_or_ignored_installs(["RUN pip install --upgrade pip"])
        return

    if malicious_fixture in {"preassignment", "ignored-failure"}:
        use = LockUse(
            paths=("debian.packages.git",),
            values=("1.2.3-locked",),
            consumer="apt",
            operation=r"\bapt-get\s+install\b",
            description="locked git package",
        )
        instruction = (
            'RUN PIN=$LOCKED apt-get install "git=$PIN"'
            if malicious_fixture == "preassignment"
            else 'RUN apt-get install "git=$LOCKED" || :'
        )
        with pytest.raises(AssertionError, match="real operation operands"):
            _assert_build_arg_lock_dataflow((use,), {"LOCKED": "1.2.3-locked"}, [instruction])
        return

    lock = _synthetic_dependency_lock()
    uses = _dependency_lock_uses(lock)
    dependency_uses = tuple(use for use in uses if not use.consumer.startswith("from-"))
    facts = sorted(
        (path, use.consumer, value)
        for use in dependency_uses
        for path, value in zip(use.paths, use.values, strict=True)
    )
    bindings = [
        {
            "name": f"LOCK_OUTPUT_{index:03d}",
            "consumer": consumer,
            "fact_path": path,
            "value": value,
        }
        for index, (path, consumer, value) in enumerate(facts)
    ]
    plan = {
        "lock_sha256": _sha256_bytes(
            json.dumps(lock, sort_keys=True, separators=(",", ":")).encode()
        ),
        "output_path": "/tmp/ba0-dependency-plan.env",
        "bindings": bindings,
        "output_bytes": "".join(
            f"{binding['name']}={json.dumps(binding['value'])}\n" for binding in bindings
        ).encode(),
    }
    expected_message = "exact dependency-plan parser argv"
    if malicious_fixture == "empty-output":
        plan["output_bytes"] = b""
        expected_message = "output_bytes"
    elif malicious_fixture == "wrong-value":
        bindings[0]["value"] = "tampered-lock-value"
        expected_message = "wrong lock value"
    lock_path = "deploy/local-build/app-external-dependencies.v1.json"
    parser = (
        "python3 -c 'pass' scripts/app_artifact.py dependency-plan"
        if malicious_fixture == "quoted-python-c"
        else "python3 scripts/app_artifact.py dependency-plan"
    )
    dockerfile = "\n".join(
        (
            "FROM $BUILDER AS builder",
            "FROM $BROWSERSKILL AS browserskill",
            "FROM $RUST AS rust",
            "FROM $RUNTIME AS runtime",
            f"COPY {lock_path} {lock_path}",
            (f"RUN {parser} --lock {lock_path} --output /tmp/ba0-dependency-plan.env"),
            "RUN sh /tmp/uv-installer",
        )
    )
    with pytest.raises(AssertionError, match=expected_message):
        _assert_dependency_lock_dataflow(
            lock,
            {
                "BUILDER": lock["base_images"]["builder"]["reference"],
                "BROWSERSKILL": lock["base_images"]["browserskill"]["reference"],
                "RUST": lock["base_images"]["rust"]["reference"],
                "RUNTIME": lock["base_images"]["runtime"]["reference"],
            },
            dockerfile,
            plan,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("unknown", "unknown|schema|field"),
        ("floating", "digest|mutable|pinned|sha"),
        ("missing", "duckdb|extension|missing"),
    ),
    ids=("unknown", "floating", "missing-duckdb-extension"),
)
def test_manifest_lock_loader_rejects_unknown_floating_or_missing_facts(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    module = _artifact_module()
    document = _load_json(DEPENDENCY_LOCK_PATH, description="external dependency lock")
    module.load_dependency_lock(DEPENDENCY_LOCK_PATH)
    mutated = deepcopy(document)
    if mutation == "unknown":
        mutated["unbounded_fallback"] = True
    elif mutation == "floating":
        mutated["base_images"]["builder"]["reference"] = "golang:1.26-bookworm"
    else:
        del mutated["downloads"]["duckdb"]["extensions"]["excel"]
    path = tmp_path / f"{mutation}.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")

    with pytest.raises(module.ArtifactContractError, match=message):
        module.load_dependency_lock(path)


def test_dependency_lock_rejects_shell_active_tokens(tmp_path: Path) -> None:
    module = _artifact_module()
    document = _load_json(DEPENDENCY_LOCK_PATH, description="external dependency lock")
    document["debian"]["packages"]["git"] = "$(touch${IFS}/tmp/ba0-injection)"
    path = tmp_path / "shell-active-lock.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(module.ArtifactContractError, match="shell|token|unsafe"):
        module.load_dependency_lock(path)
