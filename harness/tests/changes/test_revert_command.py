"""The revert command: dry run, nothing to revert, a person's decision, activation check, errors."""

import json
from typing import Any

import pytest

from insurance_harness.bundle.client import (
    Candidate,
    Decision,
    DecisionInput,
    PlatformError,
    Release,
    ReleaseMember,
)
from insurance_harness.changes import revert as command
from insurance_harness.contracts.bundle import CandidateBundle

SHA = "b" * 64


def claim(slug: str, value: str, digest: str) -> ReleaseMember:
    subject, predicate = slug.split("/")
    return ReleaseMember(
        kind="claim",
        logical_slug=slug,
        member_digest=digest,
        payload={"subject_ref": subject, "predicate": predicate, "value": value},
        access_scope="space",
    )


OLD = Release(id="rel-1", epoch=1, members=[claim("A/f1", "v1", "1" * 64)])
ACTIVE = Release(
    id="rel-2",
    epoch=2,
    members=[
        claim("A/f1", "v2", "2" * 64),
        claim("A/f2", "new", "3" * 64),
        ReleaseMember(
            kind="concept",
            logical_slug="concept/x",
            member_digest="4" * 64,
            payload={"based_on": {"A/f1": "2" * 64}},
            access_scope="space",
        ),
    ],
)


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, base_url: str, api_key: str) -> None:
        self.submitted: list[CandidateBundle] = []
        self.decisions: list[DecisionInput] = []
        self.activated = False
        self.fail_release: str | None = None
        self.releases = {"rel-1": OLD, "rel-2": ACTIVE}
        FakeClient.instances.append(self)

    def active(self, space_id: str) -> Release | None:
        return self.releases.get("rel-3") or ACTIVE

    def release(self, space_id: str, release_id: str) -> Release:
        if release_id not in self.releases:
            raise PlatformError("RELEASE_NOT_FOUND")
        return self.releases[release_id]

    def submit(self, space_id: str, bundle: CandidateBundle) -> Candidate:
        self.submitted.append(bundle)
        return Candidate(id="cand-1", status="created")

    def decide(self, space_id: str, candidate_id: str, decision: DecisionInput) -> Decision:
        self.decisions.append(decision)
        return Decision(id="dec-1", candidate_id=candidate_id, outcome="approve", digest="d")

    def activate(self, space_id: str, candidate_id: str, decision_id: str) -> Release:
        bundle = self.submitted[-1]
        kept = [m for m in ACTIVE.members if m.logical_slug not in bundle.removals]
        replaced = {m.logical_slug for m in bundle.members}
        members = [m for m in kept if m.logical_slug not in replaced] + [
            ReleaseMember(**m.model_dump()) for m in bundle.members
        ]
        self.releases["rel-3"] = Release(id="rel-3", epoch=3, members=members)
        self.activated = True
        return self.releases["rel-3"]


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Any:
    FakeClient.instances.clear()
    monkeypatch.setattr(command, "PlatformClient", FakeClient)
    monkeypatch.setenv("HARNESS_WEKNORA_BASE_URL", "http://platform.test")
    monkeypatch.setenv("HARNESS_WEKNORA_API_KEY", "test-key")

    def invoke(*extra: str, to_release: str = "rel-1") -> tuple[int, dict[str, Any]]:
        argv = ["--space", "s", "--entity", "A", "--to-release", to_release, "--reason", "回退测试"]
        code = command.main([*argv, *extra])
        return code, json.loads(capsys.readouterr().out)

    return invoke


def test_a_dry_run_reports_the_delta_and_submits_nothing(run: Any) -> None:
    code, report = run("--dry-run")
    assert code == 0
    assert report["members"] == ["A/f1"] and report["removals"] == ["A/f2"]
    assert report["stale_concepts"] == ["concept/x"]
    assert not FakeClient.instances[-1].submitted


def test_a_revert_is_a_persons_decision_and_is_checked_after_activation(run: Any) -> None:
    code, report = run("--activate")
    client = FakeClient.instances[-1]
    assert code == 0 and report["release_id"] == "rel-3"
    assert [d.mode for d in client.decisions] == ["human"]
    assert client.decisions[0].reason == "回退测试"
    assert client.submitted[0].origin == "revert"
    assert "value" not in json.dumps(report), "the report never carries member content"


def test_without_activate_the_candidate_is_decided_but_not_released(run: Any) -> None:
    code, report = run()
    assert code == 0 and report["decision_id"] == "dec-1"
    assert "release_id" not in report
    assert not FakeClient.instances[-1].activated


def test_nothing_to_revert_submits_nothing(run: Any) -> None:
    code, report = run(to_release="rel-2")
    assert code == 0 and report["no_changes"] is True
    assert not FakeClient.instances[-1].submitted


def test_platform_errors_are_reported_as_codes(run: Any) -> None:
    code, report = run(to_release="rel-missing")
    assert code == 2 and report["stopped"] == "RELEASE_NOT_FOUND"


def test_a_blank_reason_is_refused(run: Any, capsys: pytest.CaptureFixture[str]) -> None:
    code = command.main(["--space", "s", "--entity", "A", "--to-release", "rel-1", "--reason", " "])
    assert code == 2
    assert json.loads(capsys.readouterr().out) == {"stopped": "INVALID_ARGUMENTS"}
