"""App build: the selected Docker context reaches lookup, build, smoke and receipts."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tests.service_shell.app_build.contract_helpers import _identity_record
from tests.service_shell.app_build.docker_helpers import _selector_runner
from tests.service_shell.app_build.exact_image_helpers import D3Runner, _d2_receipt, _d3_call
from tests.service_shell.app_build.helpers import (
    BUILD_SOURCE_HEAD,
    CONTEXT,
    D3_NONCE,
    IMAGE_ID,
    INTEGRATION_HEAD,
    REPO_ROOT,
    REQUIRED_LABELS,
    Runner,
    _artifact_module,
    _smoke_module,
)


# Task5c: execution context is explicit provenance, never artifact identity.
class ContextFixtureRunner:
    """Check real commands before delegating responses to the existing fixtures."""

    def __init__(self, delegate: Runner, context: str) -> None:
        self.delegate = delegate
        self.context = context
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, arguments: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        command = tuple(arguments)
        assert command[:3] == ("docker", "--context", self.context)
        self.commands.append(command)
        return self.delegate(("docker", "--context", CONTEXT, *command[3:]), **kwargs)


@pytest.mark.parametrize("context", (CONTEXT, "colima"))
@pytest.mark.parametrize("reuse", (True, False))
def test_task5c_selector_context_reaches_lookup_build_inspect_and_receipt(
    tmp_path: Path,
    context: str,
    reuse: bool,
) -> None:
    module = _artifact_module()
    identity = _identity_record()
    before = deepcopy(identity)
    runner = ContextFixtureRunner(
        _selector_runner(candidates=IMAGE_ID if reuse else ""),
        context,
    )
    receipt = module.select_or_build_app(
        repo_root=REPO_ROOT,
        identity=identity,
        evidence_out=tmp_path / "selector.json",
        runner=runner,
        real_build_budget_remaining=0 if reuse else 1,
        docker_context=context,
    )
    assert receipt["docker_context"] == context
    assert receipt["build_invocations"] == (0 if reuse else 1)
    assert receipt["labels"] == REQUIRED_LABELS
    assert identity == before
    assert runner.commands[0][3:5] == ("image", "ls")
    assert runner.commands[-1][3:5] == ("image", "inspect")
    assert sum(command[3] == "build" for command in runner.commands) == (0 if reuse else 1)


@pytest.mark.parametrize("context", ("default", "remote", "", "colima;true"))
def test_task5c_selector_rejects_unapproved_context_before_effects(
    tmp_path: Path,
    context: str,
) -> None:
    module = _artifact_module()
    runner = _selector_runner(candidates=IMAGE_ID)
    output = tmp_path / "selector.json"
    with pytest.raises(module.ArtifactContractError, match="context"):
        module.select_or_build_app(
            repo_root=REPO_ROOT,
            identity=_identity_record(),
            evidence_out=output,
            runner=runner,
            real_build_budget_remaining=1,
            docker_context=context,
        )
    assert runner.calls == []
    assert not output.exists()


@pytest.mark.parametrize("context", (CONTEXT, "colima"))
@pytest.mark.parametrize("runtime_failure", (False, True))
def test_task5c_smoke_uses_context_through_cleanup_and_receipt(
    tmp_path: Path,
    context: str,
    runtime_failure: bool,
) -> None:
    module = _smoke_module()
    d2_path, output = tmp_path / "d2.json", tmp_path / "d3.json"
    d2 = _d2_receipt(d2_path)
    d2["docker_context"] = context
    d2_path.write_text(json.dumps(d2))
    delegate = D3Runner(runtime_returncode=int(runtime_failure))
    delegate.evidence_path = output
    runner = ContextFixtureRunner(delegate, context)
    kwargs = dict(
        repo_root=REPO_ROOT,
        d2_receipt_path=d2_path,
        evidence_out=output,
        nonce=D3_NONCE,
        runner=runner,
        docker_context=context,
    )
    if runtime_failure:
        with pytest.raises(module.ArtifactSmokeError, match="runtime inspect"):
            module.run_exact_image_smoke(**kwargs)
    else:
        module.run_exact_image_smoke(**kwargs)
    receipt = json.loads(output.read_text())
    assert receipt["docker_context"] == context
    assert receipt["cleanup"] == "PASS"
    assert receipt["status"] == ("FAIL" if runtime_failure else "PASS")
    assert delegate.events[-1] == "cleanup"
    assert all(command[3] != "build" for command in runner.commands)


@pytest.mark.parametrize(
    ("receipt_context", "selected"),
    ((CONTEXT, "colima"), ("colima", CONTEXT), (None, "colima"), ("remote", CONTEXT)),
)
def test_task5c_smoke_rejects_cross_context_before_docker(
    tmp_path: Path,
    receipt_context: str | None,
    selected: str,
) -> None:
    module = _smoke_module()
    d2_path, output = tmp_path / "d2.json", tmp_path / "d3.json"
    d2 = _d2_receipt(d2_path)
    if receipt_context is not None:
        d2["docker_context"] = receipt_context
    d2_path.write_text(json.dumps(d2))
    runner = D3Runner()
    with pytest.raises(module.ArtifactSmokeError, match="context"):
        module.run_exact_image_smoke(
            repo_root=REPO_ROOT,
            d2_receipt_path=d2_path,
            evidence_out=output,
            nonce=D3_NONCE,
            runner=runner,
            docker_context=selected,
        )
    assert runner.calls == []
    assert not output.exists()


def test_task5c_legacy_receipt_default_stays_on_original_context(tmp_path: Path) -> None:
    receipt = _d3_call(_smoke_module(), tmp_path, D3Runner())
    assert receipt["docker_context"] == CONTEXT


def test_task5c_cli_passes_selected_context_to_both_ports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, smoke = _artifact_module(), _smoke_module()
    calls = []

    def capture(**kwargs: object) -> dict[str, str]:
        calls.append(kwargs)
        return {"status": "FIXTURE_ONLY"}

    from contextlib import nullcontext

    monkeypatch.setattr(
        app,
        "canonical_identity",
        lambda **kwargs: {
            **_identity_record(),
            "canonical_bytes": b'{"inputs": []}',
        },
    )
    monkeypatch.setattr(app, "frozen_source_context", lambda **kwargs: nullcontext(REPO_ROOT))
    monkeypatch.setattr(app, "_checked_output", lambda *args, **kwargs: INTEGRATION_HEAD)
    monkeypatch.setattr(app, "select_or_build_app", capture)
    assert (
        app._main(
            [
                "select-or-build",
                "--repo-root",
                str(REPO_ROOT),
                "--context",
                "colima",
                "--build-source-head",
                BUILD_SOURCE_HEAD,
                "--evidence-out",
                str(tmp_path / "app.json"),
            ]
        )
        == 0
    )
    monkeypatch.setattr(smoke, "run_exact_image_smoke", capture)
    assert (
        smoke._main(
            [
                "--context",
                "colima",
                "--d2-receipt",
                str(tmp_path / "app.json"),
                "--evidence-out",
                str(tmp_path / "smoke.json"),
            ]
        )
        == 0
    )
    assert [call["docker_context"] for call in calls] == ["colima", "colima"]
