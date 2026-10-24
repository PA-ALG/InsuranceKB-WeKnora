"""Regression (PR #195 review R1–R3): reruns never trust saved state they cannot check.

R1: once a product's run starts its earlier scores file is set aside where publishing never
reads it, and scores.json comes back only after every batch passed for the current input.
Changing a value, a rule, the model or the policy re-reviews within the budget; any failure,
before or after a send, leaves nothing to publish, so routing cannot reach machine review. An
unchanged review sends nothing and restores the earlier file as it was.
R2: corrupt accepted-answer markers, and accepted answers that no longer pass the scorer for
their batch, stop the product before any send (RUN_ROOT_INVALID); leftover files never make a
new answer collide with an old name.
R3: malformed answers reach the command as one JSON stop line.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.compilers.schema_fields import publish
from insurance_harness.compilers.schema_fields.claims import claims_from
from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.contracts.enums import ReviewMode
from insurance_harness.eval import review_run
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.models import CallLedger, OpenAICompatibleCompletion, StageModelConfig
from insurance_harness.review.routing import Route, Scores, route

CATALOG = SCHEMA_PACK_CATALOG
SERVED = "example-flash-0917"


class Page:
    document, document_sha256, page = "条款.pdf", "ef" * 32, 1
    text = "第一条 甲为三十日。\n第二条 乙为按年度。\n"


SOURCE = SegmentedSource([Page()])
# Every quote is 10 characters: with this limit each field is its own batch.
ONE_PER_BATCH = ("--max-chars", "10")


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def write_output(tmp_path: Path, first_value: str = "三十日") -> None:
    fields = [
        FieldResult(
            field_key=key,
            state="present",
            value=value,
            evidence=SOURCE.evidence([segment]),
            segment_ids=[segment],
        )
        for key, value, segment in (("f1", first_value, "D1P1S1"), ("f2", "按年度", "D1P1S2"))
    ]
    output = CompileOutput(
        pack_id="pk", entity_id="p1", model="m", fields=fields, cards_version="cards-test"
    )
    path = tmp_path / "compiled" / "p1" / "output.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(output.model_dump_json(), encoding="utf-8")


def write_catalog(tmp_path: Path, second_description: str = "f2") -> None:
    fields = [
        {"field_key": "f1", "short_title": "f1", "description": "f1"},
        {"field_key": "f2", "short_title": "f2", "description": second_description},
    ]
    document = {"entries": [{"pack": {"schema_pack_id": "pk", "fields": fields}}]}
    write_json(tmp_path / "repo" / CATALOG, document)


def write_stages(tmp_path: Path, policy: str = "review-a", model: str = "example-flash") -> None:
    stage = {
        "stage": "review",
        "provider": "example",
        "base_url": "https://api.example.com",
        "model": model,
        "api_key_env": "TEST_REVIEW_KEY",
        "max_tokens": 1024,
        "policy_version": policy,
    }
    write_json(tmp_path / "stages.json", {"stages": [stage]})


@pytest.fixture(autouse=True)
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("review run tests require a mock transport")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    write_catalog(tmp_path)
    write_output(tmp_path)
    write_stages(tmp_path)


class Model:
    def __init__(self, score: float, served: str, content: str | None) -> None:
        self.score, self.served, self.content = score, served, content
        self.keys: list[list[str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        user = json.loads(json.loads(request.content)["messages"][1]["content"])
        self.keys.append([item["key"] for item in user["items"]])
        content = self.content or json.dumps(
            {"scores": [{"key": item["key"], "score": self.score} for item in user["items"]]}
        )
        choice = {"message": {"content": content}, "finish_reason": "stop"}
        return httpx.Response(200, json={"model": self.served, "choices": [choice]})


Install = Callable[..., Model]


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> Install:
    real = OpenAICompatibleCompletion

    def install(score: float = 0.7, served: str = SERVED, content: str | None = None) -> Model:
        server = Model(score, served, content)

        def client(config: StageModelConfig, *, ledger: CallLedger) -> OpenAICompatibleCompletion:
            return real(
                config,
                ledger=ledger,
                environ={config.api_key_env: "k"},
                transport=httpx.MockTransport(server),
                sleep=lambda seconds: None,
            )

        monkeypatch.setattr(review_run, "OpenAICompatibleCompletion", client)
        return server

    return install


Run = Callable[..., tuple[int, dict[str, Any]]]


@pytest.fixture
def run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Run:
    def invoke(*extra: str) -> tuple[int, dict[str, Any]]:
        code = review_run.main(
            [
                "--repo", str(tmp_path / "repo"), "--products", "p1",
                "--compile-root", str(tmp_path / "compiled"), "--stage", "review",
                "--stage-config", str(tmp_path / "stages.json"),
                "--run-root", str(tmp_path / "run"), *extra,
            ]
        )  # fmt: skip
        lines = capsys.readouterr().out.strip().splitlines()
        assert len(lines) == 1, "the command prints exactly one JSON line"
        return code, json.loads(lines[0])

    return invoke


def scores_file(tmp_path: Path) -> Path:
    return tmp_path / "run" / "p1" / "scores.json"


def scores(tmp_path: Path) -> dict[str, Any]:
    return dict(json.loads(scores_file(tmp_path).read_text(encoding="utf-8")))


def complete(model: Install, run: Run) -> None:
    model()
    assert run(*ONE_PER_BATCH)[0] == 0


def publish_route(tmp_path: Path) -> Route:
    """What publishing p1 with --route decides now: admitted pack, every threshold 0.5."""
    path = tmp_path / "compiled" / "p1" / "output.json"
    output = CompileOutput.model_validate_json(path.read_text(encoding="utf-8"))
    claims = claims_from(output, SOURCE, {"条款.pdf": SourceRevision("k-1", 2)})
    loaded = None
    if scores_file(tmp_path).exists():
        document = publish._ScoresFile.model_validate_json(scores_file(tmp_path).read_text())
        loaded = Scores(document.reviewer, document.reviewed_at, dict(document.scores))
    return route(
        claims, admitted=True, threshold=lambda key: 0.5, scores=loaded, policy_ref="policy@t"
    )


NOTHING_TO_PUBLISH = Route(mode=ReviewMode.HUMAN, policy_ref=None, reasons=("SCORES_MISSING",))


# --- R1: a scores file is bound to the review that produced it ------------------------------

CHANGES: dict[str, tuple[Callable[[Path], None], list[list[str]], str]] = {
    "value": (lambda path: write_output(path, "四十日"), [["p1/f1"]], "review-a"),
    "rule": (lambda path: write_catalog(path, "f2 的新规则"), [["p1/f2"]], "review-a"),
    "policy": (lambda path: write_stages(path, "review-b"), [["p1/f1"], ["p1/f2"]], "review-b"),
    # A renamed alias that serves the same version: requests carry the configured model.
    "model": (
        lambda path: write_stages(path, model="example-flash-alias"),
        [["p1/f1"], ["p1/f2"]],
        "review-a",
    ),
}


@pytest.mark.parametrize(("change", "resent", "policy"), CHANGES.values(), ids=CHANGES.keys())
def test_a_change_after_completion_is_reviewed_again(
    tmp_path: Path,
    model: Install,
    run: Run,
    change: Callable[[Path], None],
    resent: list[list[str]],
    policy: str,
) -> None:
    complete(model, run)
    change(tmp_path)
    again = model(score=0.6)
    code, report = run(*ONE_PER_BATCH)
    assert code == 0 and report["products"][0]["reused"] is False
    assert again.keys == resent
    fresh = {key for batch in resent for key in batch}
    assert scores(tmp_path)["scores"] == {
        key: 0.6 if key in fresh else 0.7 for key in ("p1/f1", "p1/f2")
    }
    assert scores(tmp_path)["reviewer"] == f"{SERVED}@{policy}"


def test_a_stopped_re_review_leaves_no_stale_scores(
    tmp_path: Path, model: Install, run: Run
) -> None:
    complete(model, run)
    write_output(tmp_path, "四十日")
    model()
    code, report = run(*ONE_PER_BATCH, "--max-sent", "2")  # both earlier sends count
    assert (code, report["stopped"]) == (2, "BUDGET_EXCEEDED")
    # Publishing now finds no scores and queues the product for people.
    assert not scores_file(tmp_path).exists()


def test_a_model_serving_another_version_stops_without_stale_scores(
    tmp_path: Path, model: Install, run: Run
) -> None:
    complete(model, run)
    write_stages(tmp_path, model="example-pro")
    again = model(served="example-pro-1001")
    code, report = run(*ONE_PER_BATCH)
    assert (code, report["stopped"]) == (2, "SERVED_MODEL_CHANGED")
    assert len(again.keys) == 1 and not scores_file(tmp_path).exists()


def test_an_altered_but_well_formed_scores_file_is_rebuilt_without_sending(
    tmp_path: Path, model: Install, run: Run
) -> None:
    complete(model, run)
    altered = {**scores(tmp_path), "scores": {"p1/f1": 0.1, "p1/f2": 0.7}}
    scores_file(tmp_path).write_text(json.dumps(altered), encoding="utf-8")
    again = model()
    code, report = run(*ONE_PER_BATCH)
    assert code == 0 and report["products"][0]["reused"] is False
    assert again.keys == []
    assert scores(tmp_path)["scores"] == {"p1/f1": 0.7, "p1/f2": 0.7}


MALFORMED = {
    "not json": "{",
    "missing fields": '{"reviewer": "r"}',
    "score above one": json.dumps(
        {"reviewer": "r", "reviewed_at": "2026-10-17T12:00:00+00:00", "scores": {"p1/f1": 1.5}}
    ),
}


@pytest.mark.parametrize("text", MALFORMED.values(), ids=MALFORMED.keys())
def test_a_malformed_earlier_scores_file_is_never_consumed_and_is_rebuilt(
    tmp_path: Path, model: Install, run: Run, text: str
) -> None:
    complete(model, run)
    scores_file(tmp_path).write_text(text, encoding="utf-8")
    again = model()
    code, report = run(*ONE_PER_BATCH)
    assert code == 0 and report["products"][0]["reused"] is False
    assert again.keys == []
    assert scores(tmp_path)["scores"] == {"p1/f1": 0.7, "p1/f2": 0.7}
    assert not (tmp_path / "run" / "p1" / "scores.json.previous").exists()


# --- R2: accepted-answer markers are checked before any send -----------------------------


def interrupted(model: Install, run: Run) -> None:
    """The first batch answered and accepted, the second refused by the budget."""
    model()
    code, report = run(*ONE_PER_BATCH, "--max-sent", "1")
    assert (code, report["stopped"]) == (2, "BUDGET_EXCEEDED")


def responses(tmp_path: Path) -> Path:
    return tmp_path / "run" / "p1" / "responses"


def not_hex(folder: Path) -> None:
    (folder / "001.request.sha256").write_text("not-a-sha\n", encoding="utf-8")


def upper_case(folder: Path) -> None:
    marker = folder / "001.request.sha256"
    marker.write_text(marker.read_text(encoding="utf-8").upper(), encoding="utf-8")


def answer_missing(folder: Path) -> None:
    (folder / "001.txt").unlink()


def not_numbered(folder: Path) -> None:
    (folder / "001.request.sha256").rename(folder / "first.request.sha256")
    (folder / "001.txt").rename(folder / "first.txt")


CORRUPT: dict[str, Callable[[Path], None]] = {
    "digest not hex": not_hex,
    "digest upper case": upper_case,
    "accepted answer missing": answer_missing,
    "marker not numbered": not_numbered,
}


@pytest.mark.parametrize("corrupt", CORRUPT.values(), ids=CORRUPT.keys())
def test_a_corrupt_accepted_answer_marker_stops_before_sending(
    tmp_path: Path, model: Install, run: Run, corrupt: Callable[[Path], None]
) -> None:
    interrupted(model, run)
    corrupt(responses(tmp_path))
    again = model()
    code, report = run(*ONE_PER_BATCH, "--max-sent", "5")
    assert (code, report["stopped"]) == (2, "RUN_ROOT_INVALID")
    assert again.keys == []


def test_leftover_files_never_make_a_new_answer_collide(
    tmp_path: Path, model: Install, run: Run
) -> None:
    interrupted(model, run)
    (responses(tmp_path) / ".002.txt.tmp").write_text("partial", encoding="utf-8")
    again = model()
    assert run(*ONE_PER_BATCH, "--max-sent", "5")[0] == 0
    assert again.keys == [["p1/f2"]]
    assert (responses(tmp_path) / "003.request.sha256").exists()


# --- R3: malformed answers reach the command as one stop line ------------------------------

ANSWERS = {
    "repeated member": '{"scores": [{"key": "p1/f1", "score": 0.1, "score": 1}, '
    '{"key": "p1/f2", "score": 0.5}]}',
    "401-digit integer": '{"scores": [{"key": "p1/f1", "score": '
    + "9" * 401
    + '}, {"key": "p1/f2", "score": 0.5}]}',
}


@pytest.mark.parametrize("content", ANSWERS.values(), ids=ANSWERS.keys())
def test_a_malformed_answer_stops_the_command_with_one_line(
    tmp_path: Path, model: Install, run: Run, content: str
) -> None:
    model(content=content)
    code, report = run()  # run() itself asserts exactly one JSON line
    assert (code, report) == (2, {"stopped": "REVIEW_OUTPUT_INVALID", "product": "p1"})
    assert not scores_file(tmp_path).exists()


# --- R1/R2 (continued): failures before any send leave nothing to publish -----------------


@pytest.mark.parametrize("corrupt", CORRUPT.values(), ids=CORRUPT.keys())
def test_a_corrupt_marker_after_an_input_change_leaves_nothing_to_publish(
    tmp_path: Path, model: Install, run: Run, corrupt: Callable[[Path], None]
) -> None:
    complete(model, run)
    assert publish_route(tmp_path).mode == ReviewMode.MACHINE  # what is at stake
    write_output(tmp_path, "四十日")
    corrupt(responses(tmp_path))
    again = model()
    code, report = run(*ONE_PER_BATCH, "--max-sent", "5")
    assert (code, report["stopped"]) == (2, "RUN_ROOT_INVALID")
    assert again.keys == [] and not scores_file(tmp_path).exists()
    assert publish_route(tmp_path) == NOTHING_TO_PUBLISH


SHARED: dict[str, Callable[[Path], object]] = {
    "budget emptied": lambda root: (root / "budget.jsonl").write_text("", encoding="utf-8"),
    "ledger cut short": lambda root: (root / "ledger.jsonl").write_text('{"sent', encoding="utf-8"),
}


@pytest.mark.parametrize("corrupt", SHARED.values(), ids=SHARED.keys())
def test_a_corrupt_shared_budget_after_an_input_change_leaves_nothing_to_publish(
    tmp_path: Path, model: Install, run: Run, corrupt: Callable[[Path], object]
) -> None:
    """Review R1 on PR #195: the shared budget and ledger are read before any product."""
    complete(model, run)
    assert publish_route(tmp_path).mode == ReviewMode.MACHINE  # what is at stake
    write_output(tmp_path, "四十日")
    corrupt(tmp_path / "run")
    again = model()
    code, report = run(*ONE_PER_BATCH, "--max-sent", "5")
    assert (code, report["stopped"]) == (2, "RUN_ROOT_INVALID")
    assert again.keys == [] and not scores_file(tmp_path).exists()
    assert publish_route(tmp_path) == NOTHING_TO_PUBLISH


CACHED = {
    "not json": "{",
    "another batch's key": '{"scores": [{"key": "p1/f1", "score": 0.7}]}',
    "score out of range": '{"scores": [{"key": "p1/f2", "score": 2}]}',
    "key twice": '{"scores": [{"key": "p1/f2", "score": 0.7}, {"key": "p1/f2", "score": 0.7}]}',
}


@pytest.mark.parametrize("text", CACHED.values(), ids=CACHED.keys())
def test_a_corrupt_cached_answer_stops_before_the_changed_batch_is_sent(
    tmp_path: Path, model: Install, run: Run, text: str
) -> None:
    complete(model, run)
    write_output(tmp_path, "四十日")  # the first batch must be sent again
    (responses(tmp_path) / "002.txt").write_text(text, encoding="utf-8")  # the second's answer
    again = model()
    code, report = run(*ONE_PER_BATCH, "--max-sent", "5")
    assert (code, report["stopped"]) == (2, "RUN_ROOT_INVALID")
    assert again.keys == [] and not scores_file(tmp_path).exists()
    assert publish_route(tmp_path) == NOTHING_TO_PUBLISH


def test_an_invalid_new_answer_after_an_input_change_leaves_nothing_to_publish(
    tmp_path: Path, model: Install, run: Run
) -> None:
    complete(model, run)
    write_output(tmp_path, "四十日")
    model(content="{")
    code, report = run(*ONE_PER_BATCH)
    assert (code, report["stopped"]) == (2, "REVIEW_OUTPUT_INVALID")
    assert not scores_file(tmp_path).exists()
    assert publish_route(tmp_path) == NOTHING_TO_PUBLISH


def test_an_unchanged_review_restores_the_same_scores_file_without_sending(
    tmp_path: Path, model: Install, run: Run
) -> None:
    complete(model, run)
    before = scores_file(tmp_path).read_bytes()
    again = model()
    code, report = run(*ONE_PER_BATCH)
    assert code == 0 and report["products"][0]["reused"] is True
    assert again.keys == [] and scores_file(tmp_path).read_bytes() == before
    assert not (tmp_path / "run" / "p1" / "scores.json.previous").exists()
    assert publish_route(tmp_path).mode == ReviewMode.MACHINE
