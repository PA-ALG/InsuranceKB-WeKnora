"""S5b-4b acceptance (protected, written by Claude): scores are valid only for the output they
scored (Spec docs/design/slices/S5b-4b-登记表产品的编译发布编排.md §3 step 4–5, §6 item 4; review
R1). Stale scores never reach the publish command, and a product compiled before a stop is scored
on the next run. Reuses the fakes of test_publication.
"""

import json
from pathlib import Path

import pytest

from tests.ingest.test_publication import (
    Active,
    Commands,
    digest,
    option,
    publish_run,
    published,
    record_published,
    two_products,
    values,
    write_output,
)


def record_scored(run: Path, entries: dict[str, str]) -> None:
    run.mkdir(parents=True, exist_ok=True)
    (run / "scored.json").write_text(json.dumps(entries), encoding="utf-8")


def old_scores(run: Path, product: str) -> None:
    (run / "review" / product).mkdir(parents=True, exist_ok=True)
    scores = {"reviewer": "flash@test", "reviewed_at": "2026-10-20T10:00:00Z", "scores": {}}
    (run / "review" / product / "scores.json").write_text(json.dumps(scores), encoding="utf-8")


def test_stale_scores_are_never_passed_for_new_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = two_products()
    run = tmp_path / "run"
    write_output(run / "compile", current, "1818", materials=["k-old:1:" + "0" * 64])
    old_scores(run, "1818")
    record_scored(run, {"1818": digest(run / "compile", "1818")})
    write_output(run / "compile", current, "1828")
    record_published(run, {"1828": digest(run / "compile", "1828")})
    commands = Commands(monkeypatch, current)
    commands.review_stop = "BUDGET_EXCEEDED"
    publish_run(tmp_path, current, Active(set()))
    [first] = commands.named("first")
    assert option(first, "--product") == "1818" and "--scores" not in first
    assert published(run, "scored.json")["1818"] != digest(run / "compile", "1818")


def test_a_product_compiled_before_a_stop_is_scored_on_the_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = two_products()
    run = tmp_path / "run"
    commands = Commands(monkeypatch, current)
    commands.compile_stop, commands.stop_after = "BUDGET_EXCEEDED", 1
    stopped = publish_run(tmp_path, current, Active(set()))
    assert stopped.stopped == "BUDGET_EXCEEDED"
    assert (run / "compile" / "1818" / "output.json").exists()
    commands.compile_stop = None
    commands.calls.clear()
    publish_run(tmp_path, current, Active(set()))
    [compiled] = commands.named("compile")
    assert values(compiled, "--products") == ["1828"]
    [reviewed] = commands.named("review")
    assert values(reviewed, "--products") == ["1818", "1828"]
    assert [option(a, "--product") for a in commands.named("first")] == ["1818", "1828"]
    assert all("--scores" in argv for argv in commands.named("first"))


def test_scores_are_passed_only_when_bound_to_the_current_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = two_products()
    run = tmp_path / "run"
    for product in ("1818", "1828"):
        write_output(run / "compile", current, product)
        old_scores(run, product)
    record_scored(run, {"1818": digest(run / "compile", "1818"), "1828": "e" * 64})
    commands = Commands(monkeypatch, current)
    publish_run(tmp_path, current, Active(set()))
    [reviewed] = commands.named("review")
    assert values(reviewed, "--products") == ["1828"]
    for argv in commands.named("first"):
        product = option(argv, "--product")
        assert option(argv, "--scores") == str(run / "review" / product / "scores.json")
    expected = {p: digest(run / "compile", p) for p in ("1818", "1828")}
    assert published(run, "scored.json") == expected
