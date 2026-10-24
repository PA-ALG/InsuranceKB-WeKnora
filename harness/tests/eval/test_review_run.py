"""RV2a acceptance: the review run command (Spec §3.3, §4).

Protected file: written by Claude. Over a fake transport (nothing leaves the process), the command
writes per product a scores file the RV1 publish command accepts; a rerun does not send what was
already answered; the run-root budget and the served-model guard stop sending; every failure
prints one fixed code without paths, keys or material text.
"""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.compilers.schema_fields import publish
from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.eval import review_run
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.models import (
    CallLedger,
    OpenAICompatibleCompletion,
    StageModelConfig,
    load_stage_config,
)

SECRET = "SECRET-条款原文"
PACK = "pack-r"
CATALOG = SCHEMA_PACK_CATALOG
STAGES = Path(__file__).resolve().parents[2] / "src/insurance_harness/models/stages.json"


class Page:
    document, document_sha256, page = "条款.pdf", "ab" * 32, 1
    text = "第一条 甲为三十日。\n第二条 本合同不设乙。\n第三条 丙按年度计算。\n"


SOURCE = SegmentedSource([Page()])
# Each quote is 10-11 characters: with this limit every field is its own batch.
ONE_PER_BATCH = "11"
FIELDS = [
    FieldResult(
        field_key="term_a",
        state="present",
        value="三十日",
        evidence=SOURCE.evidence(["D1P1S1"]),
        segment_ids=["D1P1S1"],
    ),
    FieldResult(
        field_key="term_b",
        state="absent_explicitly",
        evidence=SOURCE.evidence(["D1P1S2"]),
        segment_ids=["D1P1S2"],
    ),
    FieldResult(
        field_key="term_c",
        state="present",
        value="按年度",
        evidence=SOURCE.evidence(["D1P1S3"]),
        segment_ids=["D1P1S3"],
    ),
    FieldResult(field_key="term_d", state="unknown"),
]
KEYS = ["p1/term_a", "p1/term_b", "p1/term_c"]


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def write_output(root: Path, product: str, fields: list[FieldResult]) -> None:
    output = CompileOutput(pack_id=PACK, entity_id=product, model="m", fields=fields)
    path = root / product / "output.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(output.model_dump_json(), encoding="utf-8")


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("review run tests require a mock transport")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A catalog pack with every field, a stage file, and p1's output in the second root."""
    root = tmp_path / "repo"
    fields = [
        {
            "field_key": key,
            "short_title": f"字段{key}",
            "description": f"{key}的定义",
            "formation_method": "原文抽取",
        }
        for key in ("term_a", "term_b", "term_d")
    ]
    # Reviewed whatever its formation method: the review covers every field the output has.
    fields.append(
        {
            "field_key": "term_c",
            "short_title": "字段丙",
            "description": "丙的定义",
            "formation_method": "人工维护",
        }
    )
    write_json(root / CATALOG, {"entries": [{"pack": {"schema_pack_id": PACK, "fields": fields}}]})
    (tmp_path / "compile-a").mkdir()
    write_output(tmp_path / "compile-b", "p1", FIELDS)
    write_json(
        tmp_path / "stages.json",
        {
            "stages": [
                {
                    "stage": "review",
                    "provider": "example",
                    "base_url": "https://api.example.com",
                    "model": "example-flash",
                    "api_key_env": "TEST_REVIEW_KEY",
                    "max_tokens": 4096,
                    "response_format": "json_object",
                    "policy_version": "review-test.1",
                }
            ]
        },
    )
    return root


class Model:
    """Scores every requested key 0.8, serving one queued model name per request."""

    def __init__(self, served: list[str], content: str | None = None) -> None:
        self.served, self.content = served, content
        self.requests: list[dict[str, Any]] = []

    def keys(self) -> list[list[str]]:
        users = [json.loads(body["messages"][1]["content"]) for body in self.requests]
        return [[item["key"] for item in user["items"]] for user in users]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        user = json.loads(body["messages"][1]["content"])
        content = self.content or json.dumps(
            {"scores": [{"key": item["key"], "score": 0.8} for item in user["items"]]}
        )
        served = self.served.pop(0) if len(self.served) > 1 else self.served[0]
        return httpx.Response(
            200,
            json={
                "model": served,
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            },
        )


Install = Callable[..., Model]


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> Install:
    """Route the command's completion client to a fake model; each call replaces the last."""
    real = OpenAICompatibleCompletion

    def install(*served: str, content: str | None = None) -> Model:
        server = Model(list(served or ("example-flash-0917",)), content)

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


Result = tuple[int, dict[str, Any], str]
Run = Callable[..., Result]


@pytest.fixture
def run(repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Run:
    def invoke(*extra: str, products: tuple[str, ...] = ("p1",)) -> Result:
        code = review_run.main(
            [
                "--repo",
                str(repo),
                "--products",
                *products,
                "--compile-root",
                str(tmp_path / "compile-a"),
                "--compile-root",
                str(tmp_path / "compile-b"),
                "--stage",
                "review",
                "--stage-config",
                str(tmp_path / "stages.json"),
                "--run-root",
                str(tmp_path / "run"),
                *extra,
            ]
        )
        out = capsys.readouterr().out
        lines = out.strip().splitlines()
        assert len(lines) == 1, "the command prints exactly one JSON line"
        return code, json.loads(lines[0]), out

    return invoke


def scores_path(tmp_path: Path, product: str = "p1") -> Path:
    return tmp_path / "run" / product / "scores.json"


def test_writes_a_scores_file_the_publish_command_accepts(
    tmp_path: Path, model: Install, run: Run
) -> None:
    server = model("example-flash-0917")
    code, _, _ = run()
    assert code == 0
    document = publish._ScoresFile.model_validate_json(scores_path(tmp_path).read_text())
    assert document.reviewer == "example-flash-0917@review-test.1"
    # Unknown fields are not scored (user ruling 2026-10-17).
    assert document.scores == dict.fromkeys(KEYS, 0.8)
    assert server.keys() == [KEYS]  # one batch under the default limit
    assert server.requests[0]["response_format"] == {"type": "json_object"}
    responses = tmp_path / "run" / "p1" / "responses"
    assert json.loads((responses / "001.txt").read_text())["scores"][0]["key"] == "p1/term_a"
    assert len((responses / "001.request.sha256").read_text().strip()) == 64


def test_a_rerun_sends_nothing_already_answered(tmp_path: Path, model: Install, run: Run) -> None:
    first = model()
    assert run("--max-chars", ONE_PER_BATCH)[0] == 0
    assert first.keys() == [[key] for key in KEYS]
    saved = scores_path(tmp_path).read_bytes()
    again = model()
    assert run("--max-chars", ONE_PER_BATCH)[0] == 0
    assert again.requests == []
    assert scores_path(tmp_path).read_bytes() == saved


def test_the_budget_counts_across_runs_and_stops_before_sending(
    tmp_path: Path, model: Install, run: Run
) -> None:
    first = model()
    code, report, _ = run("--max-sent", "1", "--max-chars", ONE_PER_BATCH)
    assert (code, report["stopped"]) == (2, "BUDGET_EXCEEDED")
    assert first.keys() == [["p1/term_a"]]
    assert not scores_path(tmp_path).exists()
    # The answered batch is reused; only the remaining two are sent within the new total.
    second = model()
    assert run("--max-sent", "3", "--max-chars", ONE_PER_BATCH)[0] == 0
    assert second.keys() == [["p1/term_b"], ["p1/term_c"]]
    document = publish._ScoresFile.model_validate_json(scores_path(tmp_path).read_text())
    assert set(document.scores) == set(KEYS)


def test_a_served_model_change_stops_the_run_and_the_root(
    tmp_path: Path, model: Install, run: Run
) -> None:
    first = model("example-flash-0917", "example-flash-1001")
    code, report, _ = run("--max-chars", ONE_PER_BATCH)
    assert (code, report["stopped"]) == (2, "SERVED_MODEL_CHANGED")
    assert len(first.requests) == 2  # the third batch is never sent
    assert not scores_path(tmp_path).exists()
    second = model("example-flash-1001")
    code, report, _ = run("--max-chars", ONE_PER_BATCH)
    assert (code, report["stopped"]) == (2, "SERVED_MODEL_CHANGED")
    assert second.requests == []


def test_the_first_compile_root_with_the_output_is_used(
    tmp_path: Path, model: Install, run: Run
) -> None:
    write_output(tmp_path / "compile-a", "p1", FIELDS[:1])
    server = model()
    assert run()[0] == 0
    assert server.keys() == [["p1/term_a"]]


def test_a_product_without_content_gets_an_empty_scores_file_without_sending(
    tmp_path: Path, model: Install, run: Run
) -> None:
    write_output(tmp_path / "compile-a", "p2", [FieldResult(field_key="term_d", state="unknown")])
    server = model()
    assert run(products=("p2",))[0] == 0
    assert server.requests == []
    document = publish._ScoresFile.model_validate_json(scores_path(tmp_path, "p2").read_text())
    assert document.scores == {}


def assert_safe(out: str, tmp_path: Path) -> None:
    assert str(tmp_path) not in out and str(tmp_path.resolve()) not in out
    assert SECRET not in out and "TEST_REVIEW_KEY" not in out


def test_a_missing_output_stops_without_paths(tmp_path: Path, model: Install, run: Run) -> None:
    server = model()
    code, report, out = run(products=("p1", "p9"))
    assert (code, report["stopped"]) == (2, "OUTPUT_MISSING")
    assert_safe(out, tmp_path)
    # Products before the failure keep their scores.
    assert scores_path(tmp_path).exists() and len(server.requests) == 1


def test_a_field_outside_the_pack_stops_before_sending(
    tmp_path: Path, model: Install, run: Run
) -> None:
    stray = FieldResult(
        field_key=SECRET,
        state="present",
        value="三十日",
        evidence=SOURCE.evidence(["D1P1S1"]),
        segment_ids=["D1P1S1"],
    )
    write_output(tmp_path / "compile-a", "p3", [stray])
    server = model()
    code, report, out = run(products=("p3",))
    assert (code, report["stopped"]) == (2, "DEFINITION_MISSING")
    assert_safe(out, tmp_path)
    assert server.requests == []


def test_an_invalid_answer_stops_without_echoing_it(
    tmp_path: Path, model: Install, run: Run
) -> None:
    model(content=f"评分：{SECRET}")
    code, report, out = run()
    assert (code, report["stopped"]) == (2, "REVIEW_OUTPUT_INVALID")
    assert_safe(out, tmp_path)
    assert not scores_path(tmp_path).exists()
    # The raw answer stays in the private run root for diagnosis.
    assert SECRET in (tmp_path / "run" / "p1" / "responses" / "001.txt").read_text()


def test_a_busy_run_root_stops_before_sending(tmp_path: Path, model: Install, run: Run) -> None:
    root = tmp_path / "run"
    root.mkdir()
    descriptor = os.open(root / ".lock", os.O_CREAT | os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    try:
        server = model()
        code, report, out = run()
        assert (code, report["stopped"]) == (2, "RUN_ROOT_BUSY")
        assert_safe(out, tmp_path)
        assert server.requests == []
    finally:
        os.close(descriptor)


def test_a_missing_key_stops_before_sending(
    tmp_path: Path, run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TEST_REVIEW_KEY", raising=False)
    code, report, out = run()
    assert (code, report["stopped"]) == (2, "MODEL_ERROR")
    assert_safe(out, tmp_path)
    assert not scores_path(tmp_path).exists()


def test_the_review_stage_reuses_the_compile_model_and_key_with_its_own_policy() -> None:
    review = load_stage_config(STAGES, "review")
    compile_stage = load_stage_config(STAGES, "schema_fields")
    assert (review.provider, review.base_url, review.model, review.api_key_env) == (
        compile_stage.provider,
        compile_stage.base_url,
        compile_stage.model,
        compile_stage.api_key_env,
    )
    assert review.response_format == "json_object"
    assert review.policy_version != compile_stage.policy_version
