"""SK-2c Spec §4.2, §6.9 (RED, written by Claude): `methods compile --live` submits a plan once.

Review #526 R1 (r3): a live compile replays only answers its value directory's ledger backs, so
every case here answers through `methods values` on a fake model; R3: the receipt names the Space.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.bundle.client import Candidate, PlatformError, Release
from insurance_harness.compilers.methods import cli
from insurance_harness.contracts.bundle import CandidateBundle
from insurance_harness.contracts.enums import ClaimState, ReviewMode, SourceClass
from insurance_harness.contracts.knowledge import Claim
from insurance_harness.ingest.registry import ProductRegistry, save_registry
from insurance_harness.ingest.source_map import API_KEY_ENV, BASE_URL_ENV
from tests.compilers.methods.helpers import (
    METHOD_A,
    World,
    candidate,
    candidate_file,
    copy_entry,
    full_answer,
    release_from,
    unknown_answer,
)
from tests.compilers.methods.values_helpers import Behaviour, answered


class FakePlatform:
    """Active reads and candidate submissions; `fail` makes the next submission fail."""

    def __init__(self, active: Release | None, check: Any = None) -> None:
        self.active_release = active
        self.submitted: list[CandidateBundle] = []
        self.spaces: list[str] = []
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
        self.spaces.append(space_id)
        return Candidate(id=f"cand-{len(self.submitted)}", status="pending")


class Live:
    """One method run answered by `methods values` on a fake model, compiled with `--live`."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        world: World,
        active: Release | None = None,
        answers: Mapping[str, Behaviour] | None = None,
    ) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.tmp_path, self.monkeypatch, self.world = tmp_path, monkeypatch, world
        self.registry = tmp_path / "registry.json"
        save_registry(world.registry, self.registry)
        self.items = [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))]
        copies = [copy_entry(raw) for raw in world.raws.values()]
        self.candidates = tmp_path / "candidates.json"
        self.candidates.write_text(
            json.dumps(candidate_file(copies, self.items)), encoding="utf-8"
        )
        self.responses = tmp_path / "values"
        answered(monkeypatch, world, self.items, self.responses, answers or {METHOD_A: full_answer})
        self.run_root = tmp_path / "run"
        self.platform = FakePlatform(active, self._order)
        self.order: list[tuple[bool, bool]] = []
        monkeypatch.setattr(cli, "reader_from_env", lambda: world.reader)
        monkeypatch.setattr(cli, "PlatformClient", lambda *_: self.platform)
        monkeypatch.setenv(BASE_URL_ENV, "https://platform.invalid")
        monkeypatch.setenv(API_KEY_ENV, "test-only")

    def answer_again(self, answers: Mapping[str, Behaviour]) -> None:
        """New answers from the model, in a new value directory (a legitimate new plan)."""
        self.responses = self.tmp_path / "values-2"
        answered(self.monkeypatch, self.world, self.items, self.responses, answers)

    def _order(self) -> None:
        """At submission: is the plan's report there, and has the registry been written?"""
        written = json.loads(self.registry.read_text(encoding="utf-8"))
        self.order.append(((self.run_root / "report.json").exists(), bool(written["methods"])))

    def main(self, capsys: pytest.CaptureFixture[str], live: bool = True) -> tuple[int, Any]:
        status = cli.main(
            [
                "compile",
                "--registry", str(self.registry),
                "--candidates", str(self.candidates),
                "--responses", str(self.responses),
                "--run-root", str(self.run_root),
                *(["--live"] if live else []),
            ]
        )
        out = capsys.readouterr().out
        assert METHOD_A not in out
        return status, json.loads(out)

    def receipt(self) -> dict[str, Any]:
        receipt: dict[str, Any] = json.loads(
            (self.run_root / "submitted.json").read_text(encoding="utf-8")
        )
        return receipt

    def plan(self) -> dict[str, Any]:
        report = json.loads((self.run_root / "report.json").read_text(encoding="utf-8"))
        plan: dict[str, Any] = report["plan"]
        return plan


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
    receipt = live.receipt()
    assert set(receipt) == {"space_id", "content_sha256", "candidate_sha256", "candidate_id"}
    assert receipt["space_id"] == live.world.registry.space_id == live.platform.spaces[0]
    assert receipt["candidate_sha256"] == live.plan()["candidate.json"]
    assert receipt["candidate_id"] == "cand-1"


def test_the_same_plan_is_not_submitted_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    live = Live(tmp_path, monkeypatch, World())
    assert live.main(capsys)[0] == 0
    first = live.receipt()
    status, summary = live.main(capsys)  # a new compile time, the same content
    assert status == 0
    assert (summary["submitted"], summary["candidate_id"]) == ("already", "cand-1")
    assert len(live.platform.submitted) == 1
    assert live.receipt() == first


def test_a_changed_plan_is_submitted_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    live = Live(tmp_path, monkeypatch, World())
    assert live.main(capsys)[0] == 0
    first = live.receipt()
    live.answer_again({METHOD_A: unknown_answer})  # the model now answers every card unknown
    status, summary = live.main(capsys)
    assert (status, summary["submitted"], summary["candidate_id"]) == (0, "new", "cand-2")
    assert live.receipt()["content_sha256"] != first["content_sha256"]


def test_the_same_content_for_another_space_is_submitted_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review #526 R3: both Spaces have no Active release, so the content alone is the same."""
    live = Live(tmp_path, monkeypatch, World())
    assert live.main(capsys)[0] == 0
    registry = ProductRegistry.model_validate_json(live.registry.read_bytes())
    save_registry(registry.model_copy(update={"space_id": "space-2"}), live.registry)
    status, summary = live.main(capsys)
    assert (status, summary["submitted"], summary["candidate_id"]) == (0, "new", "cand-2")
    assert live.platform.spaces == [live.world.registry.space_id, "space-2"]
    assert live.receipt()["space_id"] == "space-2"


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
    status, summary = live.main(capsys, live=False)
    assert status == 0 and "submitted" not in summary and "candidate_id" not in summary
    assert live.platform.submitted == []


def unknown_cautions_and_unquoted_phrase(payload: dict[str, Any]) -> dict[str, Any]:
    """One card answered unknown, one whose every item is dropped (not verbatim)."""
    answer = full_answer(payload)
    for row in answer["predicates"]:
        if row["predicate"] == "cautions":
            row["state"] = "unknown"
            row.pop("items")
        if row["predicate"] == "key_phrases":
            row["items"] = [{"text": "原文里没有这一句", "refs": row["items"][0]["refs"]}]
    return answer


def test_submitted_method_claims_meet_the_platform_publication_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """What #523 (SK-3) makes the platform check on both publication paths, whole candidate and
    point by point: a present method Claim is SOURCE_SUPPORTED, holds at least one item, and every
    item (the whole value, for text) has original evidence; without evidence it can only be
    unknown."""
    answers = {METHOD_A: unknown_cautions_and_unquoted_phrase}
    live = Live(tmp_path, monkeypatch, World(), answers=answers)
    assert live.main(capsys)[0] == 0
    (bundle,) = live.platform.submitted
    claims = [Claim.model_validate(m.payload) for m in bundle.members if m.kind == "claim"]
    states = {claim.predicate: claim.state for claim in claims}
    assert states["cautions"] == states["key_phrases"] == ClaimState.UNKNOWN
    assert states["method_steps"] == states["method_summary"] == ClaimState.PRESENT
    for claim in claims:
        if claim.state != ClaimState.PRESENT:
            assert claim.value is None and claim.evidence == []
            continue
        assert claim.origin == SourceClass.SOURCE_SUPPORTED
        assert claim.evidence and all(e.source_ref.startswith("source:v1:") for e in claim.evidence)
        if isinstance(claim.value, list):
            assert claim.value and len(claim.evidence) == len(claim.value)
