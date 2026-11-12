"""Claude Code judge sessions keep the dual-v1 fresh-session contract; offline stand-ins only."""

# ruff: noqa: F811 -- pytest fixture imports
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.ingest.judge_batch import execution
from insurance_harness.ingest.judge_batch.dual import prepare_second
from insurance_harness.ingest.judge_batch.points import JudgeBatchError
from insurance_harness.ingest.judge_batch.verdicts import ingest
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.ingest.test_judge_batch import prepared, world  # noqa: F401

MODEL = "claude-test"


def use_claude(root: Path) -> None:
    path = root / "plan.json"
    plan = json.loads(path.read_text())
    plan["model"] = MODEL
    path.write_text(json.dumps(plan))


def claude_run(
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
    *,
    result: dict[str, Any] | None = None,
    extra: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def no_probe(*_: Any) -> None:
        raise AssertionError("the codex sandbox probe must not run for Claude sessions")

    monkeypatch.setattr(execution, "probe", no_probe)

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        directory = Path(kwargs["cwd"])
        calls.append({"args": args, "cwd": directory})
        for path in sorted((directory / "requests").glob("*.json")):
            question = json.loads("\n".join(json.loads(path.read_text())["user_lines"]))
            points = [
                dict(slug=p["slug"], verdict="approve", category="通过", reason="合成依据")
                for p in question["points"]
            ]
            (directory / "responses" / path.name).write_text(json.dumps({"points": points}))
        events = [
            {"type": "system", "subtype": "init", "session_id": session_id, "model": MODEL},
            *(extra or []),
            result or {"type": "result", "subtype": "success", "is_error": False},
        ]
        kwargs["stdout"].write(("\n".join(json.dumps(e) for e in events) + "\n").encode())
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("insurance_harness.ingest.judge_batch.execution.subprocess.run", run)
    return calls


def test_claude_session_runs_bounded_headless_in_its_own_directory(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared(world)
    use_claude(world["run_root"])
    calls = claude_run(monkeypatch, "claude-one")
    row = execution.execute(world["run_root"], "s01")
    assert row["status"] == "complete" and row["proof"]["thread"] == "claude-one"
    assert row["proof"]["model"] == MODEL
    (call,) = calls
    args = call["args"]
    assert args[:3] == ["claude", "-p", execution.plan_of(world["run_root"])["operator_prompt"]]
    assert call["cwd"] == execution.workspace(world["run_root"], row)
    for flag, value in [
        ("--model", MODEL),
        ("--permission-mode", "dontAsk"),
        ("--output-format", "stream-json"),
        ("--setting-sources", ""),
    ]:
        assert args[args.index(flag) + 1] == value
    assert "--no-session-persistence" in args and "--strict-mcp-config" in args
    tools = args[args.index("--tools") + 1 : args.index("--allowedTools")]
    assert sorted(tools) == ["Glob", "Grep", "Read", "Write"]
    allowed = args[args.index("--allowedTools") + 1 :]
    assert "Write(./responses/**)" in allowed and not any("Bash" in a for a in allowed)
    assert ingest(world["run_root"])["products"]["1828"]["approve"] >= 1


@pytest.mark.parametrize(
    "result",
    [
        {"type": "result", "subtype": "error_max_turns", "is_error": True},
        {"type": "result", "subtype": "success", "is_error": True},
        None,
    ],
)
def test_claude_session_without_clean_success_is_failed(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch, result: dict[str, Any] | None
) -> None:
    prepared(world)
    use_claude(world["run_root"])
    extra = [{"type": "result", "subtype": "success", "is_error": False}] if result is None else []
    claude_run(
        monkeypatch,
        "claude-bad",
        result=result or {"type": "result", "subtype": "success", "is_error": False},
        extra=extra,
    )
    with pytest.raises(JudgeBatchError) as error:
        execution.execute(world["run_root"], "s01")
    assert error.value.code == "SESSION_FAILED"
    assert execution.ledger(world["run_root"])[-1]["status"] == "failed"


def test_claude_second_round_reusing_the_first_session_is_not_independent(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared(world)
    use_claude(world["run_root"])
    claude_run(monkeypatch, "claude-same")
    execution.execute(world["run_root"], "s01")
    ingest(world["run_root"])
    prepare_second(world["run_root"])
    second = world["run_root"] / "second"
    assert execution.plan_of(second)["model"] == MODEL
    claude_run(monkeypatch, "claude-same")
    with pytest.raises(JudgeBatchError) as error:
        execution.execute(second, "s01")
    assert error.value.code == "SESSION_NOT_INDEPENDENT"
