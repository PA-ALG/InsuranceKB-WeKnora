"""SK-2c Spec §4.2, §6.9 (RED, written by Claude): `methods compile --live` submits a plan once."""

import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.bundle.client import Candidate, PlatformError, Release
from insurance_harness.compilers.methods import cli
from insurance_harness.compilers.methods.compile import compile_methods
from insurance_harness.contracts.bundle import CandidateBundle
from insurance_harness.contracts.enums import ReviewMode
from insurance_harness.ingest.registry import ProductRegistry, save_registry
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


class FakePlatform:
    """Active reads and candidate submissions; `fail` makes the next submission fail."""

    def __init__(self, active: Release | None, check: Any = None) -> None:
        self.active_release = active
        self.submitted: list[CandidateBundle] = []
        self.fail: str | None = None
        self.check = check

    def active(self, space_id: str) -> Release | None:
        return self.active_release

    def submit(self, space_id: str, bundle: CandidateBundle) -> Candidate:
        if self.check is not None:
            self.check()
        if self.fail is not None:
            code, self.fail = self.fail, None
            raise PlatformError(code)
        self.submitted.append(bundle)
        return Candidate(id=f"cand-{len(self.submitted)}", status="pending")


class Live:
    """One offline-answered method run, compiled with `--live`."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        world: World,
        active: Release | None = None,
    ) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.world = world
        self.registry = tmp_path / "registry.json"
        save_registry(world.registry, self.registry)
        items = [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))]
        copies = [copy_entry(raw) for raw in world.raws.values()]
        self.candidates = tmp_path / "candidates.json"
        self.candidates.write_text(json.dumps(candidate_file(copies, items)), encoding="utf-8")
        model = FakeModel({METHOD_A: full_answer})
        compile_methods(
            world.registry, candidates_of(world, items), pages=world.reader, port=model,
            active=active,
        )
        self.responses = tmp_path / "responses"
        self.responses.mkdir(exist_ok=True)
        for digest, _, raw in model.sent:
            (self.responses / f"{digest}.txt").write_text(raw, encoding="utf-8")
        self.run_root = tmp_path / "run"
        self.platform = FakePlatform(active, self._order)
        self.order: list[tuple[bool, bool]] = []
        monkeypatch.setattr(cli, "reader_from_env", lambda: world.reader)
        monkeypatch.setattr(cli, "PlatformClient", lambda *_: self.platform)
        monkeypatch.setenv(BASE_URL_ENV, "https://platform.invalid")
        monkeypatch.setenv(API_KEY_ENV, "test-only")

    def _order(self) -> None:
        """At submission: is the plan's report there, and has the registry been written?"""
        written = json.loads(self.registry.read_text(encoding="utf-8"))
        self.order.append(((self.run_root / "report.json").exists(), bool(written["methods"])))

    def main(self, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
        status = cli.main(
            [
                "compile",
                "--registry", str(self.registry),
                "--candidates", str(self.candidates),
                "--responses", str(self.responses),
                "--run-root", str(self.run_root),
                "--model", "fake-model",
                "--live",
            ]
        )
        out = capsys.readouterr().out
        assert METHOD_A not in out
        return status, json.loads(out)

    def receipt(self) -> dict[str, Any]:
        return json.loads((self.run_root / "submitted.json").read_text(encoding="utf-8"))

    def plan(self) -> dict[str, Any]:
        report = json.loads((self.run_root / "report.json").read_text(encoding="utf-8"))
        return report["plan"]


def test_live_submits_the_plan_after_writing_it_and_the_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    live = Live(tmp_path, monkeypatch, World())
    status, summary = live.main(capsys)
    assert status == 0
    assert (summary["submitted"], summary["candidate_id"]) == ("new", "cand-1")
    assert live.order == [(True, True)]
    (bundle,) = live.platform.submitted
    planned = CandidateBundle.model_validate_json(
        (live.run_root / "candidate.json").read_text(encoding="utf-8")
    )
    assert bundle == planned
    assert [plan.mode for plan in bundle.review_plan] == [ReviewMode.HUMAN]
    assert live.receipt() == {
        "candidate_sha256": live.plan()["candidate.json"], "candidate_id": "cand-1",
    }


def test_the_same_plan_is_not_submitted_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    live = Live(tmp_path, monkeypatch, World())
    assert live.main(capsys)[0] == 0
    status, summary = live.main(capsys)
    assert status == 0
    assert (summary["submitted"], summary["candidate_id"]) == ("already", "cand-1")
    assert len(live.platform.submitted) == 1


def test_nothing_is_submitted_without_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World()
    first = Live(tmp_path / "one", monkeypatch, world)
    assert first.main(capsys)[0] == 0
    world.registry = ProductRegistry.model_validate_json(first.registry.read_bytes())
    active = release_from(first.platform.submitted[0])
    again = Live(tmp_path / "two", monkeypatch, world, active)
    status, summary = again.main(capsys)
    assert status == 0 and summary["no_changes"] is True
    assert (summary["submitted"], summary["candidate_id"]) == ("nothing", None)
    assert again.platform.submitted == []
    assert not (again.run_root / "submitted.json").exists()


def test_a_failed_submission_writes_no_receipt_and_a_rerun_submits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    live = Live(tmp_path, monkeypatch, World())
    live.platform.fail = "CANDIDATE_INVALID"
    status, summary = live.main(capsys)
    assert (status, summary) == (2, {"stopped": "CANDIDATE_INVALID"})
    assert (live.run_root / "report.json").exists()
    assert json.loads(live.registry.read_text(encoding="utf-8"))["methods"]
    assert not (live.run_root / "submitted.json").exists()
    status, summary = live.main(capsys)
    assert (status, summary["submitted"], summary["candidate_id"]) == (0, "new", "cand-1")
    assert live.receipt()["candidate_sha256"] == live.plan()["candidate.json"]


def test_without_live_nothing_is_submitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    live = Live(tmp_path, monkeypatch, World())
    status = cli.main(
        [
            "compile",
            "--registry", str(live.registry),
            "--candidates", str(live.candidates),
            "--responses", str(live.responses),
            "--run-root", str(live.run_root),
            "--model", "fake-model",
        ]
    )
    summary = json.loads(capsys.readouterr().out)
    assert status == 0 and "submitted" not in summary and "candidate_id" not in summary
    assert live.platform.submitted == []
