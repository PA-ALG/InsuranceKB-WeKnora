"""I1 #468 round 2 R2: public CLI rejections before identity never leave an earlier PASS.

With an explicit absolute --evidence-out, an unapproved --context (argparse, exit 2) or a
missing --repo-root must leave the receipt non-success, with zero subprocess/Docker calls.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.service_shell.test_app_image_registry import COMMIT, REFERENCE, registry
from tests.service_shell.test_app_image_registry_lifecycle import (
    assert_not_consumable,
    passed_once,
)

ROOT = Path(__file__).resolve().parents[3]


def arguments(out: Path, *, root: Path = ROOT, context: str = "colima") -> list[str]:
    return [
        "select",
        "--repo-root", str(root),
        "--context", context,
        "--build-source-head", COMMIT,
        "--pull", REFERENCE,
        "--evidence-out", str(out),
    ]  # fmt: skip


@pytest.fixture
def no_subprocess(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []

    def record(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        raise AssertionError("no subprocess may run for an early rejection")

    monkeypatch.setattr(subprocess, "run", record)
    return calls


def test_an_unapproved_context_exits_2_and_overwrites_an_earlier_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = registry()
    out = (tmp_path / "receipt.json").resolve()
    passed_once(module, out)
    calls: list[Any] = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    with pytest.raises(SystemExit) as exited:
        module._main(arguments(out, context="unapproved"))
    assert exited.value.code == 2
    assert calls == []
    assert_not_consumable(out)


def test_a_missing_repo_root_overwrites_an_earlier_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = registry()
    out = (tmp_path / "receipt.json").resolve()
    passed_once(module, out)
    calls: list[Any] = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    with pytest.raises(module.base.ArtifactContractError):
        module._main(arguments(out, root=tmp_path / "does-not-exist"))
    assert calls == []
    assert_not_consumable(out)


def test_the_equals_form_of_the_option_is_also_marked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = registry()
    out = (tmp_path / "receipt.json").resolve()
    passed_once(module, out)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
    argv = arguments(out, context="unapproved")
    argv[-2:] = [f"--evidence-out={out}"]
    with pytest.raises(SystemExit):
        module._main(argv)
    assert_not_consumable(out)
