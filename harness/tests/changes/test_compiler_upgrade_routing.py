"""S12c-1b acceptance (protected, written by Claude, #397 R1): an upgrade to unknown goes to people.

Spec docs/design/slices/S12c-1b-编译器升级的变更判定.md §3. Replacing a published fact with unknown
removes it; the independent reviewer only judges present/absent values against quotes, so such
an upgrade routes the publish to people whatever the scores say, and upgrade claims always count
as reviewed. Other unknowns keep RV2a: not scored, not blocking.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.compilers.schema_fields import publish_changes as command
from insurance_harness.compilers.schema_fields.claims import claims_from
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.contracts.enums import ClaimState, ReviewMode
from insurance_harness.contracts.knowledge import Claim, Maintenance
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.review.routing import Route, Scores, labelled, route
from tests.changes.test_claim_changes_publish import active, setup  # noqa: F401
from tests.changes.test_compiler_upgrade import NEW, claim, proof
from tests.compilers.schema_fields.test_publish_cli import SOURCE
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401

POLICY = "policy@test"


def upgraded(value: str | None, predicate: str) -> Claim:
    evidence = [proof("terms", f"{predicate}为{value}")] if value is not None else []
    return claim(value, *evidence, identity=NEW, predicate=predicate).model_copy(
        update={"maintenance": Maintenance(revision_no=1, reason="upgrade")}
    )


def scored(**by_key: float) -> Scores:
    return Scores(reviewer="r", reviewed_at="2026-10-28T00:00:00Z", by_key=by_key)


def test_an_upgrade_to_unknown_routes_to_people_even_with_a_passing_score() -> None:
    present, removed = upgraded("90日", "waiting_period"), upgraded(None, "grace_period")
    decided = route(
        [present, removed],
        admitted=True,
        threshold=lambda _: 0.9,
        scores=scored(**{present.logical_key: 0.99, removed.logical_key: 0.99}),
        policy_ref=POLICY,
    )
    assert decided.mode == ReviewMode.HUMAN
    assert "UPGRADE_TO_UNKNOWN" in decided.reasons


def test_a_present_upgrade_needs_its_own_score_and_plain_unknowns_stay_unscored() -> None:
    present = upgraded("90日", "waiting_period")
    plain_unknown = claim(None, identity=NEW, predicate="grace_period")
    assert plain_unknown.state == ClaimState.UNKNOWN
    missing = route(
        [present, plain_unknown],
        admitted=True,
        threshold=lambda _: 0.9,
        scores=scored(),
        policy_ref=POLICY,
    )
    assert missing.mode == ReviewMode.HUMAN and "SCORE_MISSING" in missing.reasons
    passing = route(
        [present, plain_unknown],
        admitted=True,
        threshold=lambda _: 0.9,
        scores=scored(**{present.logical_key: 0.99}),
        policy_ref=POLICY,
    )
    assert passing.mode == ReviewMode.MACHINE, "an ordinary unknown neither is scored nor blocks"


def test_machine_labelling_requires_a_score_for_every_upgrade_claim() -> None:
    removed = upgraded(None, "grace_period")
    machine = Route(mode=ReviewMode.MACHINE, policy_ref=POLICY, reasons=())
    with pytest.raises(ValueError):
        labelled([removed], machine, scored())


def test_the_publish_command_never_auto_releases_an_upgrade_to_unknown(
    setup: Any,  # noqa: F811
    tmp_path: Path,
    capsys: Any,
) -> None:
    """Codex's #397 repro through the real entry: admitted pack, the present upgrade scores 0.99."""
    argv, server, _ = setup
    path = tmp_path / "1828/output.json"
    raw = json.loads(path.read_text())
    before = claims_from(
        CompileOutput.model_validate(raw), SOURCE, {"保险条款.pdf": SourceRevision("k-1", 2)}
    )
    # Active: the old compiler's claims; the first one held a different value.
    first = before[0]
    quote = first.evidence[0].model_copy(
        update={"quote": "旧值", "quote_sha256": hashlib.sha256("旧值".encode()).hexdigest()}
    )
    server.active = active(
        [first.model_copy(update={"value": "旧值", "evidence": [quote]}), before[1]]
    )
    # The upgraded compiler keeps the first field's value and answers unknown for the second.
    raw["value_protocol"] = "2026-10-27.1"
    raw["fields"][1] = {"field_key": raw["fields"][1]["field_key"], "state": "unknown"}
    path.write_text(json.dumps(raw))
    for filename, data in {
        "policy.json": {
            "version": "test",
            "admitted_packs": ["pack"],
            "thresholds": {"pack": {"default": 0.9}},
        },
        "scores.json": {
            "reviewer": "r",
            "reviewed_at": "2026-10-28T00:00:00Z",
            "scores": {before[0].logical_key: 0.99, before[1].logical_key: 0.99},
        },
        "spot.json": {"version": "test", "default": {"rate": 0.0, "minimum": 0, "target": 0.99}},
    }.items():
        (tmp_path / filename).write_text(json.dumps(data))
    assert (
        command.main(
            [
                *argv,
                "--route",
                "--review-policy",
                str(tmp_path / "policy.json"),
                "--scores",
                str(tmp_path / "scores.json"),
                "--spot-check-policy",
                str(tmp_path / "spot.json"),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["upgrade"] == 2
    assert result["review"] == "human"
    assert "UPGRADE_TO_UNKNOWN" in result["reasons"]
    assert result["decision_id"] is None and result["release_id"] is None
    assert not [path for _, path, _ in server.seen if path.endswith(("/decisions", "/activations"))]
