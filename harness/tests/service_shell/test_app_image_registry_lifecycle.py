"""I1 #468 review R2: an early rejection never leaves an earlier PASS receipt in place.

A previous successful selection wrote PASS to the receipt path; the next call is rejected
before any Docker call (bad reference) or before the identity exists (CLI). The file must
no longer be a PASS receipt and `start_exact_image` must refuse it.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tests.service_shell.test_app_image_registry import (
    COMMIT,
    REFERENCE,
    REPOSITORY,
    FakeDocker,
    pulled_record,
    registry,
    select,
)

ROOT = Path(__file__).resolve().parents[3]


def smoke() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "i1_lifecycle_start_exact_image", ROOT / "scripts/start_exact_image.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def passed_once(module: ModuleType, out: Path) -> dict[str, Any]:
    receipt: dict[str, Any] = select(module, FakeDocker(pulled_record(module)), out)
    assert receipt["status"] == "PASS"
    return receipt


def assert_not_consumable(out: Path) -> None:
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["status"] != "PASS"
    checker = smoke()
    with pytest.raises(checker.ArtifactSmokeError):
        checker._required_labels(document)


@pytest.mark.parametrize(
    "reference",
    [
        f"{REPOSITORY}:main",
        f"ghcr.io/someone-else/weknora-app@sha256:{'d' * 64}",
        REFERENCE + "\n",
    ],
    ids=["tag", "foreign-repository", "trailing-newline"],
)
def test_a_rejected_reference_overwrites_an_earlier_pass_without_calling_docker(
    reference: str, tmp_path: Path
) -> None:
    module = registry()
    out = tmp_path / "receipt.json"
    passed_once(module, out)
    runner = FakeDocker(pulled_record(module))
    with pytest.raises(module.base.ArtifactContractError):
        select(module, runner, out, reference)
    assert runner.calls == []
    assert_not_consumable(out)


def test_an_identity_failure_in_the_cli_overwrites_an_earlier_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = registry()
    out = tmp_path / "receipt.json"
    passed_once(module, out)

    def broken(*_: object) -> dict[str, Any]:
        raise module.base.ArtifactContractError("identity cannot be computed")

    monkeypatch.setattr(module, "_identity", broken)
    with pytest.raises(module.base.ArtifactContractError):
        module._main(
            [
                "select",
                "--repo-root",
                str(ROOT),
                "--build-source-head",
                COMMIT,
                "--pull",
                REFERENCE,
                "--evidence-out",
                str(out),
            ]
        )
    assert_not_consumable(out)
