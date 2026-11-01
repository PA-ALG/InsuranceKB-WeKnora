"""SK-2c Spec §3.3, §4.1, §6.1, §6.7–§6.8 (RED, written by Claude): `methods values`, then
`methods compile` taking the model from the value directory."""

import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.bundle.client import Release
from insurance_harness.compilers.methods import cli
from insurance_harness.contracts.bundle import CandidateBundle
from insurance_harness.ingest.registry import save_registry
from insurance_harness.ingest.source_map import API_KEY_ENV, BASE_URL_ENV
from tests.compilers.methods.helpers import (
    METHOD_A,
    World,
    candidate,
    candidate_file,
    claims_of,
    copy_entry,
    full_answer,
)
from tests.compilers.methods.values_helpers import SERVED, FakeProvider, install, stage_config


class FakePlatform:
    def active(self, space_id: str) -> Release | None:
        return None


class Files:
    """The files of one value run and the compile after it."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, world: World) -> None:
        self.registry = tmp_path / "registry.json"
        save_registry(world.registry, self.registry)
        self.candidates = tmp_path / "candidates.json"
        copies = [copy_entry(raw) for raw in world.raws.values()]
        items = [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))]
        self.candidates.write_text(json.dumps(candidate_file(copies, items)), encoding="utf-8")
        self.stages = tmp_path / "stages.json"
        stage = stage_config().model_dump(mode="json")
        self.stages.write_text(json.dumps({"stages": [stage]}), encoding="utf-8")
        self.responses = tmp_path / "values"
        self.run_root = tmp_path / "run"
        monkeypatch.setattr(cli, "reader_from_env", lambda: world.reader)
        monkeypatch.setattr(cli, "PlatformClient", lambda *_: FakePlatform())
        monkeypatch.setenv(BASE_URL_ENV, "https://platform.invalid")
        monkeypatch.setenv(API_KEY_ENV, "test-only")

    def values(self, capsys: pytest.CaptureFixture[str], *extra: str) -> tuple[int, Any]:
        argv = [
            "values",
            "--registry", str(self.registry),
            "--candidates", str(self.candidates),
            "--responses", str(self.responses),
            "--stage-config", str(self.stages),
            *extra,
        ]
        if "--max-sent" not in extra:
            argv += ["--max-sent", "5"]
        return _main(capsys, argv)

    def compile(self, capsys: pytest.CaptureFixture[str], *extra: str) -> tuple[int, Any]:
        argv = [
            "compile",
            "--registry", str(self.registry),
            "--candidates", str(self.candidates),
            "--responses", str(self.responses),
            "--run-root", str(self.run_root),
            *extra,
        ]
        return _main(capsys, argv)


def _main(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, Any]:
    status = cli.main(argv)
    out = capsys.readouterr().out
    assert METHOD_A not in out and "家庭" not in out  # codes and counts only
    return status, json.loads(out)


def test_values_then_compile_without_a_model_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World()
    files = Files(tmp_path, monkeypatch, world)
    install(monkeypatch, FakeProvider({METHOD_A: full_answer}))
    before = files.registry.read_bytes()
    status, summary = files.values(capsys)
    assert status == 0
    assert summary["codes"] == {"answered": 1} and summary["model"] == SERVED
    assert (summary["methods"], summary["sent"], summary["sent_total"]) == (1, 1, 1)
    assert files.registry.read_bytes() == before  # the value stage only reads the registry

    status, summary = files.compile(capsys)
    assert status == 0 and summary["members"] == 6
    bundle = CandidateBundle.model_validate_json(
        (files.run_root / "candidate.json").read_text(encoding="utf-8")
    )
    claims = claims_of(bundle)
    assert len(claims) == 5
    assert {claim.provenance.model for claim in claims.values()} == {SERVED}


def test_a_model_name_other_than_the_directory_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World()
    files = Files(tmp_path, monkeypatch, world)
    install(monkeypatch, FakeProvider({METHOD_A: full_answer}))
    assert files.values(capsys)[0] == 0
    before = files.registry.read_bytes()
    assert files.compile(capsys, "--model", "another-model") == (2, {"stopped": "MODEL_MISMATCH"})
    assert files.registry.read_bytes() == before
    status, _ = files.compile(capsys, "--model", SERVED)
    assert status == 0


def test_a_directory_without_a_ledger_needs_a_model_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World()
    files = Files(tmp_path, monkeypatch, world)
    files.responses.mkdir()
    assert files.compile(capsys) == (2, {"stopped": "MODEL_UNKNOWN"})


def test_a_corrupt_ledger_is_refused_by_the_compile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World()
    files = Files(tmp_path, monkeypatch, world)
    files.responses.mkdir()
    (files.responses / "ledger.jsonl").write_text("{not a record}\n", encoding="utf-8")
    assert files.compile(capsys, "--model", SERVED) == (2, {"stopped": "RUN_ROOT_INVALID"})


def test_a_stopped_value_run_reports_its_code_and_sends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World()
    files = Files(tmp_path, monkeypatch, world)
    install(monkeypatch, FakeProvider({METHOD_A: full_answer}))
    status, summary = files.values(capsys, "--max-sent", "0")
    assert (status, summary) == (2, {"stopped": "BUDGET_EXCEEDED", "sent": 0, "sent_total": 0})


def test_a_negative_budget_is_an_invalid_argument(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World()
    files = Files(tmp_path, monkeypatch, world)
    install(monkeypatch, None)
    assert files.values(capsys, "--max-sent", "-1") == (2, {"stopped": "INVALID_ARGUMENTS"})


def test_an_unknown_stage_is_a_configuration_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World()
    files = Files(tmp_path, monkeypatch, world)
    install(monkeypatch, None)
    status, summary = files.values(capsys, "--stage", "schema_fields")
    assert (status, summary) == (2, {"stopped": "MODEL_CONFIG_INVALID"})
