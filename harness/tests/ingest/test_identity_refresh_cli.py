"""PV-4a: `uploads refresh-identity` runs the metadata publish path (PV-4 Spec §3.3).

A dry run reads Active and prints the plan; a v1 registry is refused with its code; nothing runs
without the platform configuration.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from insurance_harness.ingest.registry import save_registry
from insurance_harness.ingest.uploads import main
from tests.ingest.test_identity_refresh import NEWER, OLDER, base_release, v2
from tests.ingest.upload_helpers import entry, registry


@pytest.fixture
def platform_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARNESS_WEKNORA_BASE_URL", "http://weknora.test")
    monkeypatch.setenv("HARNESS_WEKNORA_API_KEY", "key")


def serving_active() -> httpx.MockTransport:
    body = base_release().model_dump(mode="json")

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/releases/active"):
            return httpx.Response(200, json={"success": True, "data": body})
        return httpx.Response(500)

    return httpx.MockTransport(handle)


def test_a_dry_run_prints_the_plan_and_sends_nothing(
    platform_env: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "registry.json"
    save_registry(v2(p1828=NEWER, p1814=OLDER), path)
    assert main(["refresh-identity", "--registry", str(path)], transport=serving_active()) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["dry_run"] is True
    assert (summary["entities"], summary["claims"], summary["bundles"]) == (2, 3, 1)


def test_a_v1_registry_is_refused_with_its_code(
    platform_env: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "registry.json"
    save_registry(registry(p1828=entry("1828", "terms")), path)
    assert main(["refresh-identity", "--registry", str(path)], transport=serving_active()) == 1
    assert capsys.readouterr().err.strip() == "REGISTRY_NOT_V2"


def test_nothing_runs_without_the_platform_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("HARNESS_WEKNORA_BASE_URL", raising=False)
    assert main(["refresh-identity", "--registry", str(tmp_path / "r.json")]) == 2
    assert capsys.readouterr().err.strip() == "CONFIGURATION_MISSING"
