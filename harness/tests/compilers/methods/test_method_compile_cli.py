"""SK-2 Spec §6–§8, §10.6 (RED, written by Claude): the offline compile command and write order."""

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.bundle import assemble as assemble_module
from insurance_harness.bundle.client import Release
from insurance_harness.compilers.methods import cli
from insurance_harness.compilers.methods.compile import compile_methods
from insurance_harness.contracts.bundle import CandidateBundle
from insurance_harness.ingest.registry import ProductRegistry, save_registry
from insurance_harness.ingest.registry_lock import RegistryLock
from insurance_harness.ingest.source_map import API_KEY_ENV, BASE_URL_ENV
from tests.compilers.methods.helpers import (
    METHOD_A,
    FakeModel,
    World,
    candidate,
    candidate_file,
    candidates_of,
    copy_entry,
    full_answer,
    release_from,
)
from tests.ingest.method_helpers import v1


class FakePlatform:
    def __init__(self, active: Release | None) -> None:
        self.active_release = active
        self.reads: list[str] = []

    def active(self, space_id: str) -> Release | None:
        self.reads.append(space_id)
        return self.active_release


class Setup:
    """Files of one offline run: registry, candidates, saved responses and an empty run root."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        world: World,
        items: Sequence[Mapping[str, Any]],
        answers: Mapping[str, Callable[[dict[str, Any]], dict[str, Any]]],
        active: Release | None = None,
        registry: ProductRegistry | None = None,
    ) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.registry = tmp_path / "registry.json"
        save_registry(registry or world.registry, self.registry)
        self.candidates = tmp_path / "candidates.json"
        copies = [copy_entry(raw) for raw in world.raws.values()]
        self.candidates.write_text(json.dumps(candidate_file(copies, items)), encoding="utf-8")
        # The requests the command will make, answered once in memory and saved by digest.
        model = FakeModel(answers)
        compile_methods(
            world.registry, candidates_of(world, items), pages=world.reader, port=model,
            active=active,
        )
        self.responses = tmp_path / "responses"
        self.responses.mkdir(exist_ok=True)
        for digest, _, raw in model.sent:
            (self.responses / f"{digest}.txt").write_text(raw, encoding="utf-8")
        self.run_root = tmp_path / "run"
        self.platform = FakePlatform(active)
        monkeypatch.setattr(cli, "reader_from_env", lambda: world.reader)
        monkeypatch.setattr(cli, "PlatformClient", lambda *_: self.platform)
        monkeypatch.setenv(BASE_URL_ENV, "https://platform.invalid")
        monkeypatch.setenv(API_KEY_ENV, "test-only")

    def main(self, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
        status = cli.main(
            [
                "compile",
                "--registry", str(self.registry),
                "--candidates", str(self.candidates),
                "--responses", str(self.responses),
                "--run-root", str(self.run_root),
                "--model", "fake-model",
            ]
        )
        out = capsys.readouterr().out
        assert METHOD_A not in out  # codes and counts only, never material text
        return status, json.loads(out)


def deck_a(world: World) -> list[dict[str, Any]]:
    return [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))]


def test_the_command_writes_the_plan_and_report_before_the_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World()
    setup = Setup(tmp_path, monkeypatch, world, deck_a(world), {METHOD_A: full_answer})
    real = save_registry
    seen: list[bool] = []

    def checked(registry: ProductRegistry, path: Path) -> None:
        seen.append((setup.run_root / "candidate.json").exists())
        seen.append((setup.run_root / "report.json").exists())
        real(registry, path)

    monkeypatch.setattr(cli, "save_registry", checked)
    status, summary = setup.main(capsys)
    assert status == 0 and seen == [True, True]
    bundle = CandidateBundle.model_validate_json((setup.run_root / "candidate.json").read_text())
    # SK-3 RED (Claude): five claims, the entity and the method profile
    assert len(bundle.members) == 7
    report = (setup.run_root / "report.json").read_text(encoding="utf-8")
    assert METHOD_A not in report and json.loads(report)["methods"][0]["status"] == "compiled"
    written = json.loads(setup.registry.read_text(encoding="utf-8"))
    assert len(written["methods"]) == 1
    assert setup.platform.reads == [world.registry.space_id]
    assert summary["members"] == 7


def test_a_failed_bundle_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World()
    setup = Setup(tmp_path, monkeypatch, world, deck_a(world), {METHOD_A: full_answer})
    before = setup.registry.read_bytes()
    monkeypatch.setattr(assemble_module, "MAX_BUNDLE_BYTES", 100)
    status, summary = setup.main(capsys)
    assert status == 2 and summary == {"stopped": "BUNDLE_INVALID", "reason": "SIZE_LIMIT"}
    assert setup.registry.read_bytes() == before
    assert not (setup.run_root / "candidate.json").exists()
    assert not (setup.run_root / "report.json").exists()


def test_running_again_leaves_the_registry_bytes_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World()
    setup = Setup(tmp_path / "one", monkeypatch, world, deck_a(world), {METHOD_A: full_answer})
    assert setup.main(capsys)[0] == 0
    first = setup.registry.read_bytes()
    bundle = CandidateBundle.model_validate_json((setup.run_root / "candidate.json").read_text())
    active = release_from(bundle)
    world.registry = ProductRegistry.model_validate_json(first)
    again = Setup(
        tmp_path / "two", monkeypatch, world, deck_a(world), {METHOD_A: full_answer}, active
    )
    status, summary = again.main(capsys)
    assert status == 0 and summary["no_changes"] is True
    assert again.registry.read_bytes() == first
    assert not (again.run_root / "candidate.json").exists()


def test_a_missing_saved_response_skips_the_method_without_a_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World()
    setup = Setup(tmp_path, monkeypatch, world, deck_a(world), {METHOD_A: full_answer})
    for saved in setup.responses.iterdir():
        saved.unlink()
    status, _ = setup.main(capsys)
    assert status == 0
    report = json.loads((setup.run_root / "report.json").read_text(encoding="utf-8"))
    assert report["methods"][0]["code"] == "RESPONSE_MISSING"
    assert not (setup.run_root / "candidate.json").exists()


def test_a_v1_registry_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World()
    setup = Setup(tmp_path, monkeypatch, world, [], {}, registry=v1())
    before = setup.registry.read_bytes()
    status, summary = setup.main(capsys)
    assert (status, summary) == (2, {"stopped": "REGISTRY_NOT_V2"})
    assert setup.registry.read_bytes() == before


def test_a_busy_registry_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World()
    setup = Setup(tmp_path, monkeypatch, world, deck_a(world), {METHOD_A: full_answer})
    with RegistryLock(setup.registry):
        status, summary = setup.main(capsys)
    assert (status, summary) == (3, {"stopped": "REGISTRY_BUSY"})


def test_missing_configuration_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World()
    setup = Setup(tmp_path, monkeypatch, world, deck_a(world), {METHOD_A: full_answer})
    monkeypatch.delenv(API_KEY_ENV)
    status, summary = setup.main(capsys)
    assert (status, summary) == (2, {"stopped": "CONFIGURATION_MISSING"})
