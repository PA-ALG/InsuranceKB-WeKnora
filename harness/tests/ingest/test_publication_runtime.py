"""Offline command contracts, score snapshots and per-round publication accounting."""

import json
from pathlib import Path

import httpx
import pytest

from insurance_harness.bundle.client import PlatformClient
from insurance_harness.eval import compile_run, review_run
from insurance_harness.ingest.publication import run_publication
from tests.ingest.test_publication import (
    Active,
    Commands,
    digest,
    option,
    publish_run,
    published,
    record_published,
    spend,
    stored,
    two_products,
    values,
    write_output,
)
from tests.ingest.test_publication_scores import old_scores, record_scored


def test_round_counts_come_from_durable_reservations_not_command_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, run = two_products(), tmp_path / "run"
    spend(run / "compile", 8)
    spend(run / "review", 5)
    commands = Commands(monkeypatch, current)
    active = Active({"1818", "1828"})
    report = publish_run(tmp_path, current, active, compile_max_sent=7, review_max_sent=4)
    assert (report.compile_sent, report.review_sent) == (6, 2)
    assert option(commands.named("compile")[0], "--max-sent") == "15"
    assert option(commands.named("review")[0], "--max-sent") == "9"
    assert report.reviewed == ["1818", "1828"]
    assert len(active.requests) == 1
    assert all("--scores" not in argv for argv in commands.named("changes") if "--dry-run" in argv)


def test_compile_stop_preserves_real_stop_text_and_counts_spent_sends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, run = two_products(), tmp_path / "run"
    commands = Commands(monkeypatch, current)
    active = Active(set())

    def partial_compile(argv: list[str]) -> int:
        commands.calls.append(("compile", argv))
        spend(run / "compile", 2)
        write_output(run / "compile", current, "1818")
        # compile_run uses its exception class and safe reason, not review_run's code spelling.
        print(json.dumps({"stopped": "ModelBudgetExceeded: budget_exceeded", "products": []}))
        return 2

    monkeypatch.setattr(compile_run, "main", partial_compile)
    report = publish_run(tmp_path, current, active)
    assert report.stopped == "ModelBudgetExceeded: budget_exceeded"
    assert (report.compile_sent, report.review_sent, active.requests) == (2, 0, [])
    assert [name for name, _ in commands.calls] == ["compile"]
    assert published(run) == published(run, "scored.json") == {}


def test_compile_partial_restart_and_review_config_failure_cannot_reuse_old_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, run = two_products(), tmp_path / "run"
    write_output(run / "compile", current, "1818", materials=["old:1:" + "a" * 64])
    old_scores(run, "1818")
    record_scored(run, {"1818": digest(run / "compile", "1818")})
    old_binding = (run / "scored.json").read_bytes()
    commands = Commands(monkeypatch, current)
    commands.compile_stop, commands.stop_after = "ModelBudgetExceeded: budget_exceeded", 1
    assert publish_run(tmp_path, current, Active(set())).stopped is not None
    commands.compile_stop = None
    commands.calls.clear()

    def early_config_failure(argv: list[str]) -> int:
        commands.calls.append(("review", argv))
        # Faithful to review_run: load_stage_config fails before _withdraw_scores.
        assert (run / "review/1818/scores.json").exists()
        print(json.dumps({"stopped": "MODEL_ERROR", "error": "ModelConfigError"}))
        return 2

    monkeypatch.setattr(review_run, "main", early_config_failure)
    report = publish_run(tmp_path, current, Active(set()))
    assert values(commands.named("compile")[0], "--products") == ["1828"]
    assert values(commands.named("review")[0], "--products") == ["1818", "1828"]
    assert report.review_stopped == "MODEL_ERROR" and report.reviewed == []
    assert all("--scores" not in args for args in commands.named("first"))
    assert (run / "scored.json").read_bytes() == old_binding


@pytest.mark.parametrize("mutate_output", [False, True])
def test_scores_bind_only_reported_products_to_the_bytes_seen_before_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutate_output: bool,
) -> None:
    current, run = two_products(), tmp_path / "run"
    for product in ("1818", "1828"):
        write_output(run / "compile", current, product)
    before = digest(run / "compile", "1818")
    commands = Commands(monkeypatch, current)

    def subset_review(argv: list[str]) -> int:
        commands.calls.append(("review", argv))
        # A file alone cannot certify completion: only the command's real object summary can.
        for product in ("1818", "1828"):
            old_scores(run, product)
        if mutate_output:
            path = run / "compile/1818/output.json"
            path.write_bytes(path.read_bytes() + b"\n")
        print(json.dumps({"products": [{"product": "1818", "scored": 0, "reused": False}]}))
        return 0

    monkeypatch.setattr(review_run, "main", subset_review)
    report = publish_run(tmp_path, current, Active(set()))
    assert report.reviewed == ["1818"]
    assert published(run, "scored.json") == {"1818": before}
    first, second = commands.named("first")
    assert ("--scores" in first) is not mutate_output
    assert "--scores" not in second


def test_failed_review_with_partial_score_files_never_updates_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, run = two_products(), tmp_path / "run"
    commands = Commands(monkeypatch, current)
    record_scored(run, {"unselected": "c" * 64})
    before = (run / "scored.json").read_bytes()

    def failed_review(argv: list[str]) -> int:
        commands.calls.append(("review", argv))
        spend(run / "review", 2)
        old_scores(run, "1818")
        print(json.dumps({"stopped": "BUDGET_EXCEEDED", "product": "1828"}))
        return 2

    monkeypatch.setattr(review_run, "main", failed_review)
    report = publish_run(tmp_path, current, Active(set()))
    assert report.review_stopped == "BUDGET_EXCEEDED" and report.review_sent == 2
    assert report.reviewed == [] and (run / "scored.json").read_bytes() == before
    assert all("--scores" not in argv for argv in commands.named("first"))


@pytest.mark.parametrize("score_file", [False, True])
def test_current_binding_skips_review_but_needs_a_file_to_pass_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, score_file: bool,
) -> None:
    current, run = two_products(), tmp_path / "run"
    write_output(run / "compile", current, "1818")
    record_scored(run, {"1818": digest(run / "compile", "1818")})
    if score_file:
        old_scores(run, "1818")
    commands = Commands(monkeypatch, current)
    report = publish_run(tmp_path, current, Active(set()), products=["1818"])
    assert not commands.named("review") and report.review_sent == 0
    assert ("--scores" in commands.named("first")[0]) is score_file


def test_failed_change_probe_skips_that_product_and_reviews_only_remaining_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, run = two_products(), tmp_path / "run"
    commands = Commands(monkeypatch, current)
    commands.publish_failures = {"1818": "SOURCE_UNAVAILABLE"}
    report = publish_run(tmp_path, current, Active({"1818"}))
    assert report.failed == {"1818": "SOURCE_UNAVAILABLE"}
    assert values(commands.named("review")[0], "--products") == ["1828"]
    assert list(published(run)) == ["1828"]
    assert len(commands.named("changes")) == 1


def test_active_failure_sends_no_review_or_publish_and_is_reported_for_each_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = two_products()
    commands = Commands(monkeypatch, current)
    requests: list[httpx.Request] = []

    def unavailable(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503, json={"success": False, "code": "SERVICE_UNAVAILABLE"})

    client = PlatformClient("http://weknora.test", "fake",
                            transport=httpx.MockTransport(unavailable))
    report = run_publication(stored(tmp_path, current), tmp_path / "run", client=client,
                             stage_config=tmp_path / "unused.json")
    assert report.failed == {p: "SERVICE_UNAVAILABLE" for p in ("1818", "1828")}
    assert [name for name, _ in commands.calls] == ["compile"] and len(requests) == 1


def test_nothing_pending_calls_neither_commands_nor_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, run = two_products(), tmp_path / "run"
    for product in current.products:
        write_output(run / "compile", current, product)
    record_published(run, {p: digest(run / "compile", p) for p in current.products})
    commands, active = Commands(monkeypatch, current), Active(set())
    report = publish_run(tmp_path, current, active)
    assert commands.calls == [] and active.requests == []
    assert report.planned_compile == report.planned_publish == []


def test_only_claims_with_matching_string_subjects_select_change_publishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = two_products()
    commands = Commands(monkeypatch, current)

    def active(request: httpx.Request) -> httpx.Response:
        members = [
            {"kind": kind, "logical_slug": str(index), "member_digest": "a" * 64,
             "payload": {"subject_ref": subject}}
            for index, (kind, subject) in enumerate([
                ("entity", "1818"), ("claim", ["1818"]), ("claim", {"id": "1828"}),
            ])
        ]
        return httpx.Response(200, json={"success": True, "data": {
            "id": "release", "epoch": 1, "members": members,
        }})

    client = PlatformClient("http://weknora.test", "fake", transport=httpx.MockTransport(active))
    report = run_publication(stored(tmp_path, current), tmp_path / "run", client=client,
                             stage_config=tmp_path / "unused.json")
    assert report.failed == {} and not commands.named("changes")
    assert [option(argv, "--product") for argv in commands.named("first")] == ["1818", "1828"]
