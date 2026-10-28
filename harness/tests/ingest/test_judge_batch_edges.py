"""RV7 implementer tests: answer and CLI edges beyond the RED (test_judge_batch)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.eval.judge_files import stored_requests
from insurance_harness.ingest.judge_batch import JudgeBatchError, ingest, prepare
from insurance_harness.ingest.judge_batch import cli as command
from insurance_harness.ingest.judge_batch.sessions import prompt
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.ingest.test_judge_batch import (  # noqa: F401
    POLICY,
    REVIEWER,
    answer,
    prepared,
    publish,
    submitted,
    world,
)


def test_an_approval_under_a_reject_category_is_refused(
    world: dict[str, Any],  # noqa: F811
) -> None:
    prepared(world)
    first, second = world["keys"]
    answer(world, {first: ("approve", "遗漏关键内容"), second: ("approve", "通过")})
    with pytest.raises(JudgeBatchError) as refused:
        ingest(world["run_root"])
    assert refused.value.code == "ANSWER_INVALID"


def test_requests_are_split_by_size_and_every_point_is_asked_once(
    world: dict[str, Any],  # noqa: F811
) -> None:
    prepare(
        world["run_root"],
        registry=world["registry"],
        compile_root=world["compile_root"],
        products=["1828"],
        reader=world["reader"],
        client=world["client"],
        policy_ref=POLICY,
        reviewer=REVIEWER,
        model="judge-test",
        points_per_request=1,
        repo=world["repo"],
    )
    requests = stored_requests(world["run_root"] / "sessions" / "s01")
    asked = [json.loads(request.user)["points"][0]["slug"] for request in requests]
    assert sorted(asked) == sorted(world["keys"]) and len(requests) == 2


def test_nothing_approved_submits_nothing(
    world: dict[str, Any],  # noqa: F811
) -> None:
    prepared(world)
    answer(world, {key: ("reject", "值有误") for key in world["keys"]})
    ingest(world["run_root"])
    result = publish(world, live=True)
    assert result["products"]["1828"]["status"] == "nothing_approved"
    assert submitted(world) == []


def test_the_prompt_data_is_consistent() -> None:
    rules = prompt()
    assert rules["version"] and rules["system"] and rules["rules"] and rules["operator_prompt"]
    assert rules["approve_category"] not in rules["reject_categories"]


def test_the_cli_ingests_and_reports_codes_only(
    world: dict[str, Any],  # noqa: F811
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared(world)
    answer(world, {key: ("approve", "通过") for key in world["keys"]})
    assert command.main(["ingest", "--run-root", str(world["run_root"])]) == 0
    assert json.loads(capsys.readouterr().out)["products"]["1828"]["approve"] == 2
    monkeypatch.delenv("HARNESS_WEKNORA_BASE_URL", raising=False)
    argv = [
        "publish",
        "--registry",
        str(world["registry"]),
        "--compile-root",
        str(world["compile_root"]),
        "--run-root",
        str(world["run_root"]),
        "--issue",
        "1",
    ]
    assert command.main(argv) == 2
    assert capsys.readouterr().err.strip() == "CONFIGURATION_MISSING"
    missing = world["run_root"].parent / "elsewhere"
    assert command.main(["ingest", "--run-root", str(missing)]) == 1
    error = capsys.readouterr().err.strip()
    assert error == "PLAN_MISSING" and str(Path(missing)) not in error
