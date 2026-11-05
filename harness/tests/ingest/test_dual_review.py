"""S12c-12c frozen RED: actual two-stage flow, offline process stand-ins only."""

# ruff: noqa: F811 -- imported pytest fixtures are consumed by parameter name

import importlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.ingest.judge_batch.points import JudgeBatchError
from insurance_harness.ingest.judge_batch.verdicts import ingest
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.ingest.test_judge_batch import (
    approve_all,
    prepared,
    publish,
    submitted,
    world,  # noqa: F401
)


def module(name: str) -> Any:
    spec = importlib.util.find_spec("insurance_harness.ingest.judge_batch." + name)
    assert spec is not None, f"{name}: required dual-review production boundary missing"
    return importlib.import_module(spec.name)


def fake_run(
    monkeypatch: pytest.MonkeyPatch, thread: str, rejects: set[str] | None = None
) -> list[str]:
    execution = module("execution")
    calls: list[str] = []
    monkeypatch.setattr(execution, "probe", lambda *_: None)

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert args[:2] == ["codex", "exec"] and "--json" in args
        assert "resume" not in args and "--fork" not in args
        directory = Path(args[args.index("-C") + 1])
        calls.append(str(directory))
        for path in sorted((directory / "requests").glob("*.json")):
            question = json.loads("\n".join(json.loads(path.read_text())["user_lines"]))
            points = [
                dict(
                    slug=p["slug"],
                    verdict="reject" if p["slug"] in (rejects or set()) else "approve",
                    category="遗漏关键内容" if p["slug"] in (rejects or set()) else "通过",
                    reason="合成依据",
                )
                for p in question["points"]
            ]
            (directory / "responses" / path.name).write_text(json.dumps({"points": points}))
        events = [
            {"type": "thread.started", "thread_id": thread},
            {"type": "turn.completed", "usage": {}},
        ]
        kwargs["stdout"].write(("\n".join(json.dumps(e) for e in events) + "\n").encode())
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(execution.subprocess, "run", run)
    return calls


def first(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Path:
    prepared(case)
    fake_run(monkeypatch, "thread-first")
    module("execution").execute(case["run_root"], "s01")
    ingest(case["run_root"])
    return case["run_root"]


def second(
    case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    *,
    same: bool = False,
    rejects: set[str] | None = None,
) -> Path:
    root = first(case, monkeypatch)
    module("dual").prepare_second(root)
    fake_run(monkeypatch, "thread-first" if same else "thread-second", rejects)
    module("execution").execute(root / "second", "s01")
    return root / "second"


def test_legacy_single_judge_cannot_publish(world: dict[str, Any]) -> None:  # noqa: F811
    prepared(world)
    approve_all(world)
    try:
        ingest(world["run_root"])
        result = publish(world, live=True)
        assert result["stopped"], "single review must not publish"
    except JudgeBatchError:
        pass
    assert submitted(world) == []


def test_second_is_only_approved_candidate_fields_and_fulltext(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: F811
    prepared(world)
    fake_run(monkeypatch, "first", {world["keys"][1]})
    module("execution").execute(world["run_root"], "s01")
    ingest(world["run_root"])
    plan = module("dual").prepare_second(world["run_root"])
    assert plan["round"] == 2
    session = world["run_root"] / "second/sessions/s01"
    stored = json.loads((session / "requests/001.json").read_text())
    payload = json.loads("\n".join(stored["user_lines"]))
    assert [p["slug"] for p in payload["points"]] == [world["keys"][0]]
    assert all(not ({"live", "change", "verdict", "reason"} & set(p)) for p in payload["points"])
    assert payload["points"][0]["new"]["value"] == "90日"
    assert (session / "sources").is_dir()
    original = json.loads((world["run_root"] / "sessions/s01/requests/001.json").read_text())
    assert stored["system_lines"] == original["system_lines"], "standards must not be rewritten"
    assert module("dual").prepare_second(world["run_root"]) == plan


def test_two_independent_approvals_publish_and_resume_without_new_judge(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: F811
    root = second(world, monkeypatch)
    ingest(root)
    result = publish(world, live=True)
    assert result["stopped"] is None and result["products"]["1828"]["claims"] == 2
    calls = fake_run(monkeypatch, "must-not-send")
    module("execution").execute(root, "s01")
    assert not calls
    assert publish(world, live=True)["products"]["1828"]["status"] == "already_published"


def test_second_rejection_is_machine_improvement_not_publish(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: F811
    root = second(world, monkeypatch, rejects={world["keys"][0]})
    ingest(root)
    result = publish(world)
    assert result["products"]["1828"]["claims"] == 1
    record = json.loads((world["run_root"] / "dual-review.json").read_text())
    assert record["improvements"][0]["slug"] == world["keys"][0]
    assert record["improvements"][0]["round"] == 2


def test_same_thread_cannot_be_second_judge(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: F811
    with pytest.raises(JudgeBatchError):
        root = second(world, monkeypatch, same=True)
        ingest(root)
        publish(world, live=True)
    assert submitted(world) == []


@pytest.mark.parametrize("damage", ["response", "session", "plan", "receipt"])
def test_tampering_after_dual_ingest_blocks_even_publish_resume(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:  # noqa: F811
    root = second(world, monkeypatch)
    ingest(root)
    publish(world, live=True)
    before = len(submitted(world))
    if damage == "response":
        file = next((root / "attempts").rglob("responses/001.json"))
    elif damage == "session":
        file = root / "sessions/s01/requests/001.json"
    elif damage == "plan":
        file = world["run_root"] / "plan.json"
    else:
        file = world["run_root"] / "dual-review.json"
    file.write_text("{}")
    with pytest.raises(JudgeBatchError):
        publish(world, live=True)
    assert len(submitted(world)) == before


def test_missing_second_never_sends(world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    root = first(world, monkeypatch)
    module("dual").prepare_second(root)
    with pytest.raises(JudgeBatchError):
        publish(world, live=True)
    assert submitted(world) == []


def test_known_failure_retry_gets_new_directory_and_consumes_budget(
    world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    prepared(world)
    execution = module("execution")
    calls = fake_run(monkeypatch, "failed-thread")
    successful = execution.subprocess.run

    def fail(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        successful(args, **kwargs)
        return subprocess.CompletedProcess(args, 1)

    monkeypatch.setattr(execution.subprocess, "run", fail)
    with pytest.raises(JudgeBatchError):
        execution.execute(world["run_root"], "s01")
    old = calls[0]
    calls = fake_run(monkeypatch, "retry-thread")
    execution.execute(world["run_root"], "s01", retry=True)
    assert len(calls) == 1 and calls[0] != old and Path(old).exists()
    ingest(world["run_root"])
    module("dual").prepare_second(world["run_root"])
    before = len(calls)
    with pytest.raises(JudgeBatchError) as error:
        execution.execute(world["run_root"] / "second", "s01")
    assert error.value.code == "SESSION_BUDGET_EXHAUSTED" and len(calls) == before


def test_unknown_attempt_is_not_blindly_retried(
    world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    prepared(world)
    execution = module("execution")
    calls = fake_run(monkeypatch, "unused")

    def interrupt(*args: Any, **kwargs: Any) -> Any:
        raise KeyboardInterrupt()

    monkeypatch.setattr(execution.subprocess, "run", interrupt)
    with pytest.raises(KeyboardInterrupt):
        execution.execute(world["run_root"], "s01")
    with pytest.raises(JudgeBatchError) as error:
        execution.execute(world["run_root"], "s01", retry=True)
    assert error.value.code == "SESSION_RESULT_UNKNOWN" and not calls


def test_second_parent_binding_cannot_be_reused_after_first_result_changes(
    world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    root = first(world, monkeypatch)
    module("dual").prepare_second(root)
    (root / "verdicts/1828.json").write_text("[]")
    with pytest.raises(JudgeBatchError):
        module("dual").prepare_second(root)


def test_unaltered_first_round_question_still_contains_live_comparison(
    world: dict[str, Any],  # noqa: F811
) -> None:
    prepared(world)
    request = json.loads((world["run_root"] / "sessions/s01/requests/001.json").read_text())
    question = json.loads("\n".join(request["user_lines"]))
    assert any(p["live"] is not None for p in question["points"])
