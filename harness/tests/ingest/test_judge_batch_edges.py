"""RV7 implementer tests: answer, manifest, recovery, close and CLI edges beyond the RED."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from insurance_harness.eval.judge_files import stored_requests
from insurance_harness.ingest.judge_batch import JudgeBatchError, close_points, ingest, prepare
from insurance_harness.ingest.judge_batch import cli as command
from insurance_harness.ingest.judge_batch.sessions import prompt
from tests.changes.test_claim_changes_publish import active
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.ingest.test_judge_batch import (  # noqa: F401
    POLICY,
    REVIEWER,
    answer,
    leftover,
    prepared,
    publish,
    submitted,
    world,
)
from tests.ingest.test_judge_batch_recovery import ledger, record  # noqa: F401


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


def test_a_missing_manifest_or_an_added_request_is_refused(
    world: dict[str, Any],  # noqa: F811
) -> None:
    prepared(world)
    answer(world, {key: ("approve", "通过") for key in world["keys"]})
    requests = world["run_root"] / "sessions" / "s01" / "requests"
    (requests / "002.json").write_bytes((requests / "001.json").read_bytes())
    with pytest.raises(JudgeBatchError) as added:
        ingest(world["run_root"])
    assert added.value.code == "REQUEST_CHANGED"
    (requests / "002.json").unlink()
    (world["run_root"] / "manifest.json").unlink()
    with pytest.raises(JudgeBatchError) as missing:
        ingest(world["run_root"])
    assert missing.value.code == "MANIFEST_MISSING"


def test_a_lost_activation_is_settled_by_reading_active_first(
    ledger: dict[str, Any],  # noqa: F811
) -> None:
    ledger["server"].lose = {"activate"}
    publish(ledger, live=True)
    dry = publish(ledger)["products"]["1828"]
    assert dry["status"] == "in_progress" and dry["pending"] == "activate"
    publish(ledger, live=True)
    sent = [path for method, path, _ in ledger["server"].seen if method == "POST"]
    assert sum(path.endswith("/activations") for path in sent) == 1
    assert record(ledger)["reconciled"] == ["activate"]


def test_supersede_needs_this_batchs_completed_attempt(
    world: dict[str, Any],  # noqa: F811
) -> None:
    prepared(world)
    answer(world, {key: ("approve", "通过") for key in world["keys"]})
    ingest(world["run_root"])
    world["server"].active = active(world["claims"])  # live, but not published by this batch
    path = leftover(world, world["claims"])
    result = close_points(
        world["run_root"],
        client=world["client"],
        product="1828",
        candidate="cand_old",
        candidate_bundle=path,
        issue=384,
    )
    assert result["supersede"] == [] and set(result["skipped"].values()) == {"not_live"}


def test_a_live_value_the_judge_did_not_see_stops_publishing(
    world: dict[str, Any],  # noqa: F811
) -> None:
    prepared(world)
    answer(world, {key: ("approve", "通过") for key in world["keys"]})
    ingest(world["run_root"])
    first = world["claims"][0]
    digest = hashlib.sha256("60日".encode()).hexdigest()
    quote = first.evidence[0].model_copy(update={"quote": "60日", "quote_sha256": digest})
    changed = first.model_copy(update={"value": "60日", "evidence": [quote]})
    world["server"].active = active([changed])  # still an upgrade, but from 60日, not 旧值
    result = publish(world, live=True)
    assert result["stopped"] == {"product": "1828", "code": "CONTENT_CHANGED"}
    assert submitted(world) == []


def test_a_read_back_that_does_not_match_stops_and_the_rerun_reads_again(
    ledger: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = ledger["server"]
    real = server.handle
    garbled: list[str] = []

    def handle(method: str, path: str, body: Any) -> tuple[str, httpx.Response]:
        step, response = real(method, path, body)
        if step == "read_back" and not garbled:
            garbled.append(path)
            data = json.loads(response.content)["data"]
            short = {**data, "members": data["members"][:-1]}
            return step, httpx.Response(200, json={"success": True, "data": short})
        return step, response

    monkeypatch.setattr(server, "handle", handle)
    first = publish(ledger, live=True)
    assert first["stopped"] == {"product": "1828", "code": "RELEASE_MISMATCH"}
    assert record(ledger)["stage"] == "activated"
    assert publish(ledger, live=True)["products"]["1828"]["status"] == "published"


def _published_with_leftover(case: dict[str, Any]) -> Path:
    prepared(case)
    answer(case, {key: ("approve", "通过") for key in case["keys"]})
    ingest(case["run_root"])
    publish(case, live=True)
    return leftover(case, case["claims"])


def _close(case: dict[str, Any], path: Path) -> None:
    close_points(
        case["run_root"],
        client=case["client"],
        product="1828",
        candidate="cand_old",
        candidate_bundle=path,
        issue=384,
        live=True,
    )


def test_a_bundle_file_whose_slugs_group_differently_is_refused(
    world: dict[str, Any],  # noqa: F811
) -> None:
    path = _published_with_leftover(world)
    first = world["keys"][0]
    live = next(m for m in world["server"].active["members"] if m["logical_slug"] == first)
    on_platform = json.loads(path.read_text(encoding="utf-8"))
    on_platform["members"] = [
        live if m["logical_slug"] == first else m for m in on_platform["members"]
    ]
    world["server"].leftovers["cand_old"] = on_platform  # same sizes and base, one digest differs
    with pytest.raises(JudgeBatchError) as refused:
        _close(world, path)
    assert refused.value.code == "CANDIDATE_BUNDLE_MISMATCH"
    assert world["server"].rejections == []


def test_a_bundle_file_with_other_removals_is_refused(
    world: dict[str, Any],  # noqa: F811
) -> None:
    path = _published_with_leftover(world)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["removals"] = ["1828/gone"]  # not in Head, so only the sizes can tell
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(JudgeBatchError) as refused:
        _close(world, path)
    assert refused.value.code == "CANDIDATE_BUNDLE_MISMATCH"
    assert world["server"].rejections == []
