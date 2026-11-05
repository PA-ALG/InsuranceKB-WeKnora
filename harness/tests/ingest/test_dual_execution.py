"""Failure-window controls beyond the frozen RED; synthetic inputs and processes only."""

# ruff: noqa: F811 -- pytest fixture imports
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.ingest.judge_batch import cli, execution
from insurance_harness.ingest.judge_batch.dual import prepare_second
from insurance_harness.ingest.judge_batch.points import JudgeBatchError
from insurance_harness.ingest.judge_batch.verdicts import ingest
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.ingest.test_dual_review import fake_run, first, second
from tests.ingest.test_judge_batch import prepared, publish, submitted, world  # noqa: F401


def test_exit_written_but_completion_record_lost_recovers_without_sending(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared(world)
    calls = fake_run(monkeypatch, "one")
    save = execution.save

    def lose(root: Path, rows: list[dict[str, Any]]) -> None:
        if rows[-1]["status"] == "complete":
            raise OSError("synthetic crash")
        save(root, rows)

    monkeypatch.setattr(execution, "save", lose)
    with pytest.raises(OSError):
        execution.execute(world["run_root"], "s01")
    monkeypatch.setattr(execution, "save", save)
    row = execution.execute(world["run_root"], "s01")
    assert row["status"] == "complete" and len(calls) == 1
    assert len(execution.ledger(world["run_root"])) == 1


def test_failed_final_commit_is_not_publishable_and_ingest_repairs_it(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = second(world, monkeypatch)
    from insurance_harness.ingest.judge_batch import dual
    from insurance_harness.ingest.judge_batch.manifest import write_json

    write = write_json

    def lose(path: Path, value: object) -> None:
        if path.name == "dual-review.json":
            raise OSError("synthetic interruption")
        write(path, value)

    monkeypatch.setattr(dual, "write_json", lose)
    with pytest.raises(OSError):
        ingest(root)
    with pytest.raises(JudgeBatchError):
        publish(world, live=True)
    assert submitted(world) == []
    monkeypatch.setattr(dual, "write_json", write)
    ingest(root)
    assert publish(world)["stopped"] is None


def test_second_rewritten_with_its_own_manifest_cannot_change_candidate(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = first(world, monkeypatch)
    prepare_second(root)
    child = root / "second"
    request = child / "sessions/s01/requests/001.json"
    data = json.loads(request.read_text())
    question = json.loads("\n".join(data["user_lines"]))
    question["points"][0]["new"]["value"] = "180日"
    from insurance_harness.eval.judge import JudgeRequest

    value = JudgeRequest("\n".join(data["system_lines"]), json.dumps(question))
    data.update(request_sha256=value.sha256, user_lines=value.user.split("\n"))
    request.write_text(json.dumps(data))
    manifest = json.loads((child / "manifest.json").read_text())
    manifest["sessions"]["s01"]["files"]["requests/001.json"] = execution.sha(request)
    (child / "manifest.json").write_text(json.dumps(manifest))
    calls = fake_run(monkeypatch, "two")
    with pytest.raises(JudgeBatchError):
        execution.execute(child, "s01")
    assert not calls


def test_known_invalid_json_requires_explicit_new_attempt(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared(world)
    fake_run(monkeypatch, "invalid")
    run = subprocess.run

    def bad(args: list[str], **kwargs: Any) -> Any:
        result = run(args, **kwargs)
        (Path(args[args.index("-C") + 1]) / "responses/001.json").write_text("{}")
        return result

    monkeypatch.setattr("insurance_harness.ingest.judge_batch.execution.subprocess.run", bad)
    execution.execute(world["run_root"], "s01")
    with pytest.raises(JudgeBatchError, match="ANSWER_INVALID"):
        ingest(world["run_root"])
    with pytest.raises(JudgeBatchError, match="SESSION_RETRY_REQUIRED"):
        execution.execute(world["run_root"], "s01")
    fake_run(monkeypatch, "valid")
    execution.execute(world["run_root"], "s01", retry=True)
    assert ingest(world["run_root"])["products"]["1828"]["approve"] == 2


@pytest.mark.parametrize(
    "name,value", [("sessions", []), ("session_budget", True), ("model", None)]
)
def test_malformed_plan_is_typed_and_zero_send(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch, name: str, value: object
) -> None:
    prepared(world)
    path = world["run_root"] / "plan.json"
    plan = json.loads(path.read_text())
    plan[name] = value
    path.write_text(json.dumps(plan))
    calls = fake_run(monkeypatch, "not-sent")
    with pytest.raises(JudgeBatchError):
        execution.execute(world["run_root"], "s01")
    assert not calls


def test_cli_second_and_second_ingest_need_no_platform_credentials(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = first(world, monkeypatch)
    monkeypatch.delenv("HARNESS_WEKNORA_BASE_URL", raising=False)
    monkeypatch.delenv("HARNESS_WEKNORA_API_KEY", raising=False)
    assert cli.main(["second", "--run-root", str(root)]) == 0
    fake_run(monkeypatch, "second")
    assert cli.main(["execute", "--run-root", str(root / "second"), "--session", "s01"]) == 0
    assert cli.main(["ingest", "--run-root", str(root / "second")]) == 0


def test_completed_execution_record_is_not_rewritten(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = first(world, monkeypatch)
    path = root / "sessions-ledger.json"
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    calls = fake_run(monkeypatch, "not-sent")
    execution.execute(root, "s01")
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before and not calls


def test_lost_ledger_cannot_reset_attempt_budget(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = first(world, monkeypatch)
    (root / "sessions-ledger.json").unlink()
    calls = fake_run(monkeypatch, "no-send")
    with pytest.raises(JudgeBatchError):
        execution.execute(root, "s01")
    assert not calls


def test_second_parent_change_before_send_stops_with_zero_attempts(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = first(world, monkeypatch)
    prepare_second(root)
    original = root / "sessions/s01/requests/001.json"
    original.write_text("{}")
    calls = fake_run(monkeypatch, "no-send")
    with pytest.raises(JudgeBatchError):
        execution.execute(root / "second", "s01")
    assert not calls and not (root / "second/attempts").exists()


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_untrusted_saved_answer_is_refused_without_wait_or_send(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    import os

    root = first(world, monkeypatch)
    path = next((root / "attempts").rglob("responses/001.json"))
    saved = path.read_bytes()
    path.unlink()
    if kind == "symlink":
        target = root / "saved.json"
        target.write_bytes(saved)
        path.symlink_to(target)
    else:
        os.mkfifo(path)
    calls = fake_run(monkeypatch, "no-send")
    with pytest.raises(JudgeBatchError):
        execution.execute(root, "s01")
    assert not calls


def test_failed_process_with_truncated_events_can_use_new_known_attempt(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared(world)
    fake_run(monkeypatch, "discarded")

    def fail(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        kwargs["stdout"].write(b'{"type":"thread.started","thread_id":"bad"}\n{"partial":')
        return subprocess.CompletedProcess(args, 1)

    monkeypatch.setattr("insurance_harness.ingest.judge_batch.execution.subprocess.run", fail)
    with pytest.raises(JudgeBatchError):
        execution.execute(world["run_root"], "s01")
    calls = fake_run(monkeypatch, "fresh-after-failure")
    assert execution.execute(world["run_root"], "s01", retry=True)["status"] == "complete"
    assert len(calls) == 1 and len(execution.ledger(world["run_root"])) == 2


def test_answer_changed_after_receipt_check_is_rejected_before_verdict_writes(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared(world)
    fake_run(monkeypatch, "one")
    execution.execute(world["run_root"], "s01")
    original = execution.proof

    def changed(root: Path) -> dict[str, dict[str, Any]]:
        result = original(root)
        answer = next((root / "attempts").rglob("responses/001.json"))
        data = json.loads(answer.read_text())
        data["points"][0]["reason"] = "changed after check"
        answer.write_text(json.dumps(data))
        return result

    monkeypatch.setattr(execution, "proof", changed)
    with pytest.raises(JudgeBatchError):
        ingest(world["run_root"])
    assert not (world["run_root"] / "verdicts").exists()
