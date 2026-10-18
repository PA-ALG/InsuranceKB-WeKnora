"""Concept run recovery and refusals beyond the acceptance cases (S3e-3 Spec §4.1).

A refused answer stays for diagnosis but is sent again on rerun; a retry is sent only while budget
remains; an altered accepted answer is corrupt run-root state; a cancelled send stays counted and
ends with a fixed code (review R2 on PR #220); and malformed arguments or a missing platform
configuration stop with fixed codes before anything is sent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from insurance_harness.bundle.client import PlatformClient, Release
from insurance_harness.compilers.concepts import run as concept_run
from insurance_harness.ingest import source_map as source_map_module
from insurance_harness.models import CallLedger, OpenAICompatibleCompletion, StageModelConfig

A, B, C = "P1/cooling_off_period", "P2/cooling_off_period", "P3/cooling_off_period"
GOOD = {
    "cooling_off_period": [{"text": "多数产品为十五日。", "refs": [A, B]}],
    "premium_grace_period": [{"text": "甲产品为60日。", "refs": ["P1/premium_grace_period"]}],
}


class Model:
    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        user = json.loads(json.loads(request.content)["messages"][1]["content"])
        self.requests.append(user)
        if isinstance(self.answer, BaseException):
            raise self.answer
        if isinstance(self.answer, str):
            content = self.answer
        else:
            concepts = [
                {"key": item["key"], "definition": "定义。", "explanation": "解释。",
                 "statements": self.answer[item["key"]]}
                for item in user["concepts"]
            ]  # fmt: skip
            content = json.dumps({"concepts": concepts}, ensure_ascii=False)
        return httpx.Response(
            200,
            json={
                "model": "example-flash",
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            },
        )


@pytest.fixture
def run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    release: Release,
) -> Any:
    stage = {
        "stage": "concepts", "provider": "example", "base_url": "https://api.example.com",
        "model": "example-flash", "api_key_env": "TEST_CONCEPT_KEY", "max_tokens": 1024,
        "policy_version": "concept-test",
    }  # fmt: skip
    (tmp_path / "stages.json").write_text(json.dumps({"stages": [stage]}), encoding="utf-8")
    monkeypatch.setenv(source_map_module.BASE_URL_ENV, "https://weknora.test")
    monkeypatch.setenv(source_map_module.API_KEY_ENV, "key-123")
    active = release.model_dump(mode="json")

    def platform(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "data": active})

    monkeypatch.setattr(
        concept_run,
        "PlatformClient",
        lambda base, key: PlatformClient(base, key, transport=httpx.MockTransport(platform)),
    )

    def invoke(answer: Any, *extra: str) -> tuple[int, dict[str, Any], Model]:
        server, real = Model(answer), OpenAICompatibleCompletion

        def completion(
            config: StageModelConfig, *, ledger: CallLedger
        ) -> OpenAICompatibleCompletion:
            return real(
                config, ledger=ledger, environ={config.api_key_env: "k"},
                transport=httpx.MockTransport(server), sleep=lambda seconds: None,
            )  # fmt: skip

        monkeypatch.setattr(concept_run, "OpenAICompatibleCompletion", completion)
        code = concept_run.main(
            [
                "--space", "demo", "--stage", "concepts",
                "--stage-config", str(tmp_path / "stages.json"),
                "--run-root", str(tmp_path / "run"), *extra,
            ]
        )  # fmt: skip
        out = capsys.readouterr().out
        assert str(tmp_path) not in out
        return code, json.loads(out), server

    return invoke


def report(tmp_path: Path) -> dict[str, Any]:
    return dict(json.loads((tmp_path / "run" / "report.json").read_text(encoding="utf-8")))


def test_chinese_numerals_are_checked_against_the_values(tmp_path: Path, run: Any) -> None:
    code, summary, _ = run(GOOD)
    assert (code, summary["written"], summary["failed"]) == (0, 2, [])


def test_a_refused_answer_is_kept_and_sent_again_on_rerun(tmp_path: Path, run: Any) -> None:
    code, summary, server = run("不是 JSON")
    assert code == 0 and summary["failed"] == ["cooling_off_period", "premium_grace_period"]
    assert [list(user) for user in server.requests[1:]] == [["concepts", "previous_problems"]] * 2
    assert report(tmp_path)["concepts"]["cooling_off_period"] == {
        "attempts": [["CONCEPT_OUTPUT_INVALID"], ["CONCEPT_OUTPUT_INVALID"]],
        "sent": 2,
    }
    responses = tmp_path / "run" / "responses"
    assert len(list(responses.glob("*.txt"))) == 3 and not list(responses.glob("*.sha256"))
    code, summary, again = run(GOOD)
    assert (code, summary["written"], len(again.requests)) == (0, 2, 1)


def test_a_retry_waits_for_budget_and_the_concept_is_left_out(tmp_path: Path, run: Any) -> None:
    bad = {
        **GOOD,
        "premium_grace_period": [{"text": "为90日。", "refs": ["P1/premium_grace_period"]}],
    }
    code, summary, server = run(bad, "--max-sent", "1")
    assert (code, summary["written"], len(server.requests)) == (0, 1, 1)
    assert report(tmp_path)["failed"] == {"premium_grace_period": ["RETRY_BUDGET_EXCEEDED"]}
    code, summary, again = run(GOOD, "--max-sent", "2")
    assert (code, summary["written"], summary["sent"], len(again.requests)) == (0, 2, 1, 1)


def test_an_altered_accepted_answer_is_corrupt_state(tmp_path: Path, run: Any) -> None:
    assert run(GOOD)[0] == 0
    (tmp_path / "run" / "responses" / "001.txt").write_text("{}", encoding="utf-8")
    code, summary, server = run(GOOD)
    assert (code, summary, server.requests) == (2, {"stopped": "RUN_ROOT_INVALID"}, [])
    assert not (tmp_path / "run" / "concepts.json").exists()


@pytest.mark.parametrize(
    "extra",
    [("--publish",), ("--reason", "x"), ("--per-call", "0"), ("--max-sent", "-1")],
    ids=["publish without reason", "reason without publish", "zero batch", "negative budget"],
)
def test_malformed_arguments_stop_before_anything_is_sent(run: Any, extra: tuple[str, ...]) -> None:
    code, summary, server = run(GOOD, *extra)
    assert (code, summary, server.requests) == (2, {"stopped": "INVALID_ARGUMENTS"}, [])


def test_an_overlong_statement_fails_its_concept_not_the_run(tmp_path: Path, run: Any) -> None:
    overlong = {**GOOD, "cooling_off_period": [{"text": "万" * 1500 + "元", "refs": [A]}]}
    code, summary, _ = run(overlong)
    assert (code, summary["written"], summary["failed"]) == (0, 1, ["cooling_off_period"])
    assert "STATEMENT_LENGTH" in report(tmp_path)["failed"]["cooling_off_period"]


def test_a_cancelled_send_stays_counted_and_the_rerun_resumes(tmp_path: Path, run: Any) -> None:
    code, summary, server = run(KeyboardInterrupt())
    assert (code, summary, len(server.requests)) == (2, {"stopped": "INTERRUPTED"}, 1)
    assert not (tmp_path / "run" / "concepts.json").exists()
    code, summary, again = run(GOOD, "--max-sent", "2")  # the lock was released
    assert (code, summary["sent"], summary["sent_total"], summary["written"]) == (0, 1, 2, 2)


def test_a_missing_platform_configuration_stops_first(
    run: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(source_map_module.API_KEY_ENV)
    code, summary, server = run(GOOD)
    assert (code, summary, server.requests) == (2, {"stopped": "PLATFORM_UNCONFIGURED"}, [])
