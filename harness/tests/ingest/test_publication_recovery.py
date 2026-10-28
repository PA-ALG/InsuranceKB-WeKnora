"""Atomic publication checkpoints, interrupted retries and uploads command boundaries."""

import json
import os
from pathlib import Path

import httpx
import pytest

from insurance_harness.eval import compile_run
from insurance_harness.ingest.uploads import main
from tests.ingest.test_publication import (
    Active,
    Commands,
    command,
    digest,
    environment,  # noqa: F401
    publish_run,
    published,
    stored,
    two_products,
    write_output,
)
from tests.ingest.test_publication_scores import old_scores, record_scored


def test_scored_write_failure_keeps_old_binding_and_publishes_without_stale_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, run = two_products(), tmp_path / "run"
    commands = Commands(monkeypatch, current)
    record_scored(run, {"1818": "d" * 64})
    old = (run / "scored.json").read_bytes()
    replace = os.replace

    def fail_score(source: str, target: Path) -> None:
        if Path(target).name == "scored.json":
            raise OSError("secret file location")
        replace(source, target)

    monkeypatch.setattr(os, "replace", fail_score)
    report = publish_run(tmp_path, current, Active(set()))
    assert report.review_stopped == "PUBLICATION_IO_ERROR"
    assert (run / "scored.json").read_bytes() == old
    assert all("--scores" not in argv for argv in commands.named("first"))
    assert not list(run.glob(".scored.json.*"))
    assert "secret" not in report.model_dump_json()


@pytest.mark.parametrize("active_after", [False, True])
def test_interruption_after_publish_retries_human_candidate_or_checks_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, active_after: bool,
) -> None:
    current, run = two_products(), tmp_path / "run"
    write_output(run / "compile", current, "1818")
    record_scored(run, {"1818": digest(run / "compile", "1818")})
    old_scores(run, "1818")
    commands = Commands(monkeypatch, current)
    replace = os.replace

    def interrupt_receipt(source: str, target: Path) -> None:
        if Path(target).name == "published.json":
            raise KeyboardInterrupt
        replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", interrupt_receipt)
        with pytest.raises(KeyboardInterrupt):
            publish_run(tmp_path, current, Active(set()), products=["1818"])
    assert published(run) == {} and len(commands.named("first")) == 1
    assert not list(run.glob(".published.json.*"))
    commands.calls.clear()
    if active_after:
        commands.unchanged = {"1818"}
    report = publish_run(tmp_path, current, Active({"1818"} if active_after else set()),
                         products=["1818"])
    assert report.routes == {"1818": "unchanged" if active_after else "human"}
    assert [name for name, _ in commands.calls] == ["changes" if active_after else "first"]
    assert not commands.named("review") and list(published(run)) == ["1818"]


def test_one_receipt_failure_does_not_mark_failed_product_when_next_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, run = two_products(), tmp_path / "run"
    Commands(monkeypatch, current)
    replace = os.replace
    failed = False

    def fail_first_receipt(source: str, target: Path) -> None:
        nonlocal failed
        if Path(target).name == "published.json" and not failed:
            failed = True
            raise OSError("private path")
        replace(source, target)

    monkeypatch.setattr(os, "replace", fail_first_receipt)
    report = publish_run(tmp_path, current, Active(set()))
    assert report.failed == {"1818": "PUBLICATION_IO_ERROR"}
    assert report.routes == {"1828": "human"} and list(published(run)) == ["1828"]


@pytest.mark.usefixtures("environment")
def test_uploads_dry_run_sends_no_commands_reads_active_once_and_releases_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    current = two_products()
    registry = stored(tmp_path, current)
    seed = tmp_path / "seed"
    write_output(seed, current, "1818")
    commands, active = Commands(monkeypatch, current), Active(set())
    assert main(command(tmp_path, "--dry-run", "--seed-from", str(seed)),
                transport=httpx.MockTransport(active.handle)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["planned_compile"] == ["1828"]
    assert commands.calls == [] and not (tmp_path / "run").exists()
    assert len(active.requests) == 1  # one read: is the seed current on carry? (S12c-4)
    assert not registry.with_name("registry.json.lock").exists()


@pytest.mark.usefixtures("environment")
def test_uploads_holds_registry_lock_during_every_stage_and_returns_review_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    current = two_products()
    stored(tmp_path, current)
    commands = Commands(monkeypatch, current)
    commands.review_stop = "MODEL_ERROR"
    compile_main = compile_run.main

    def locked_compile(argv: list[str]) -> int:
        assert (tmp_path / "registry.json.lock").exists()
        return compile_main(argv)

    monkeypatch.setattr(compile_run, "main", locked_compile)
    active = Active(set())
    assert main(command(tmp_path), transport=httpx.MockTransport(active.handle)) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["review_stopped"] == "MODEL_ERROR" and len(report["routes"]) == 2
    assert not (tmp_path / "registry.json.lock").exists()
    assert all("--scores" not in argv for argv in commands.named("first"))


@pytest.mark.parametrize("raw", ["private content", "[]", '{}\n{}', '{"products":["1818"]}'])
@pytest.mark.usefixtures("environment")
def test_invalid_command_output_is_a_code_and_never_leaks_to_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], raw: str,
) -> None:
    stored(tmp_path, two_products())
    Commands(monkeypatch, two_products())

    def malformed(argv: list[str]) -> int:
        print(raw)
        return 0

    monkeypatch.setattr(compile_run, "main", malformed)
    active = Active(set())
    assert main(command(tmp_path), transport=httpx.MockTransport(active.handle)) == 1
    captured = capsys.readouterr()
    assert "COMMAND_OUTPUT_INVALID" in captured.out + captured.err
    assert "private content" not in captured.out + captured.err and not active.requests
    assert not (tmp_path / "registry.json.lock").exists()
