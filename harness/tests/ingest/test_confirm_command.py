"""S5b-3c-2 acceptance (protected, written by Claude): the `uploads confirm` command.

Spec docs/design/slices/S5b-3c-2-待确认材料的推送与应用.md §3.4, §4 item 12: one run per registry,
the same configuration and exit codes as `run`, a report without material text, and what was
applied kept when the platform fails.
"""

import json
from pathlib import Path

import httpx
import pytest

from insurance_harness.ingest.registry import load_registry, save_registry
from insurance_harness.ingest.uploads import main
from tests.ingest.confirmation_scenarios import (
    UPLOADS,
    asked,
    only_item,
    platform_for_command,
    products,
)


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARNESS_WEKNORA_BASE_URL", "http://weknora.test")
    monkeypatch.setenv("HARNESS_WEKNORA_API_KEY", "key")


def stored(tmp_path: Path, *ids: str) -> Path:
    path = tmp_path / "registry.json"
    save_registry(asked(products(), *ids), path)
    return path


def test_the_command_pushes_then_applies_and_reports_without_material_text(
    tmp_path: Path, environment: None, capsys: pytest.CaptureFixture[str]
) -> None:
    path, platform = stored(tmp_path, "k-new"), platform_for_command()
    assert main(["confirm", "--registry", str(path)], transport=platform.transport()) == 0
    assert json.loads(capsys.readouterr().out)["pushed"] == ["k-new"]
    platform.answer(only_item(platform, "k-new"), "replace")
    assert main(["confirm", "--registry", str(path)], transport=platform.transport()) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["applied"] == ["k-new"]
    assert load_registry(path).decisions[-1].attribution.outcome == "REPLACE"
    assert UPLOADS["k-new"][1][:20] not in output


def test_a_dry_run_writes_nothing(tmp_path: Path, environment: None) -> None:
    path, platform = stored(tmp_path, "k-new"), platform_for_command()
    before = path.read_bytes()
    assert (
        main(["confirm", "--registry", str(path), "--dry-run"], transport=platform.transport()) == 0
    )
    assert (path.read_bytes(), platform.writes, platform.items) == (before, [], {})


def test_missing_configuration_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("HARNESS_WEKNORA_BASE_URL", raising=False)
    monkeypatch.delenv("HARNESS_WEKNORA_API_KEY", raising=False)
    path, platform = stored(tmp_path, "k-new"), platform_for_command()
    assert main(["confirm", "--registry", str(path)], transport=platform.transport()) == 2
    assert "CONFIGURATION_MISSING" in capsys.readouterr().err
    assert platform.writes == []


def test_a_busy_registry_is_refused(
    tmp_path: Path, environment: None, capsys: pytest.CaptureFixture[str]
) -> None:
    path, platform = stored(tmp_path, "k-new"), platform_for_command()
    before = path.read_bytes()
    path.with_name(path.name + ".lock").write_text("")
    assert main(["confirm", "--registry", str(path)], transport=platform.transport()) == 3
    assert "REGISTRY_BUSY" in capsys.readouterr().err
    assert (path.read_bytes(), platform.writes) == (before, [])


def test_a_platform_failure_keeps_what_was_applied(
    tmp_path: Path, environment: None, capsys: pytest.CaptureFixture[str]
) -> None:
    path, platform = stored(tmp_path, "k-new", "k-scan"), platform_for_command()
    assert main(["confirm", "--registry", str(path)], transport=platform.transport()) == 0
    platform.answer(only_item(platform, "k-new"), "supplement")
    platform.answer(only_item(platform, "k-scan"), "role:brochure")
    platform.fail_closures_after = 1
    capsys.readouterr()
    assert main(["confirm", "--registry", str(path)], transport=platform.transport()) == 1
    assert "SERVICE_UNAVAILABLE" in capsys.readouterr().err
    kept = load_registry(path)
    assert [d.knowledge_id for d in kept.decisions if d.confirmation] == ["k-new"]
    assert not path.with_name(path.name + ".lock").exists()


def test_a_short_submission_response_ends_the_command_with_a_code(
    tmp_path: Path, environment: None, capsys: pytest.CaptureFixture[str]
) -> None:
    path, platform = stored(tmp_path, "k-new", "k-scan"), platform_for_command()
    before = path.read_bytes()

    def drop_last(request: httpx.Request) -> httpx.Response:
        response = platform.handle(request)
        if request.method == "POST" and response.status_code < 300 and "items" in response.text:
            body = json.loads(response.content)
            body["data"]["items"] = body["data"]["items"][:-1]
            return httpx.Response(response.status_code, json=body)
        return response

    assert main(["confirm", "--registry", str(path)], transport=httpx.MockTransport(drop_last)) == 1
    assert "INVALID_RESPONSE" in capsys.readouterr().err
    assert path.read_bytes() == before
