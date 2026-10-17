"""Regression (PR #191 review R1, R2): malformed review inputs stop before anything is sent.

A JSON boolean is neither a score nor a threshold, and the review time is an ISO 8601 date-time
with an offset. Valid integer scores and offset times still pass the argument stage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.catalog.review_policy import load_review_policy
from insurance_harness.compilers.schema_fields import publish as command

GOOD_POLICY = {"version": "t", "admitted_packs": ["pack"], "thresholds": {"pack": {"default": 0.9}}}


def scores_file(
    reviewed_at: str = "2026-10-17T12:00:00Z", scores: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"reviewer": "r", "reviewed_at": reviewed_at, "scores": scores or {"1828/a": 0.95}}


def run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, policy: Any, scores: Any
) -> dict[str, Any]:
    def no_client(*_: Any) -> None:
        raise AssertionError("no request may be sent")

    monkeypatch.setattr(command, "PlatformClient", no_client)
    (tmp_path / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
    (tmp_path / "scores.json").write_text(json.dumps(scores), encoding="utf-8")
    argv = [
        "--run-root",
        str(tmp_path),
        "--product",
        "1828",
        "--source-map",
        str(tmp_path / "map.json"),
    ]
    argv += ["--route", "--review-policy", str(tmp_path / "policy.json")]
    argv += ["--scores", str(tmp_path / "scores.json")]
    assert command.main(argv) == 2
    return {}


@pytest.mark.parametrize(
    ("policy", "scores"),
    [
        (GOOD_POLICY, scores_file(scores={"1828/a": True})),
        (GOOD_POLICY, scores_file(scores={"1828/a": "0.95"})),
        ({**GOOD_POLICY, "thresholds": {"pack": {"default": False}}}, scores_file()),
        ({**GOOD_POLICY, "thresholds": {"pack": {"fields": {"a": True}}}}, scores_file()),
        (GOOD_POLICY, scores_file("not-a-date")),
        (GOOD_POLICY, scores_file("2026-10-17")),
        (GOOD_POLICY, scores_file("2026-10-17T12:00:00")),
    ],
    ids=[
        "bool score",
        "string score",
        "bool default",
        "bool field",
        "no date",
        "date only",
        "no offset",
    ],
)
def test_malformed_review_inputs_are_invalid_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    policy: Any,
    scores: Any,
) -> None:
    run(tmp_path, monkeypatch, policy, scores)
    assert json.loads(capsys.readouterr().out) == {"stopped": "INVALID_ARGUMENTS"}


def test_integer_scores_and_offset_times_pass_the_argument_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # No compile output exists here, so the command stops at the next stage instead.
    run(
        tmp_path,
        monkeypatch,
        GOOD_POLICY,
        scores_file("2026-10-17T12:00:00+08:00", {"1828/a": 1}),
    )
    assert json.loads(capsys.readouterr().out) == {"stopped": "OUTPUT_UNREADABLE"}


def test_policy_thresholds_accept_integers_but_not_booleans(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps({**GOOD_POLICY, "thresholds": {"pack": {"default": 1}}}), encoding="utf-8"
    )
    assert load_review_policy(path).threshold("pack", "a") == 1.0
    path.write_text(
        json.dumps({**GOOD_POLICY, "thresholds": {"pack": {"default": True}}}), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load_review_policy(path)
