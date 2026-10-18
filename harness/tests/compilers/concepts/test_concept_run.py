"""S3e-3 acceptance: the concept run reads the active release, checks, retries once, resumes and
publishes only concept members on the head it read (Spec §4.1).

Protected file: written by Claude. Real calls are faked with a mock transport; nothing leaves the
test.
"""

from __future__ import annotations

import json
from collections.abc import Callable
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
    "cooling_off_period": [{"text": "多数产品为15日，丙产品为20日。", "refs": [A, B, C]}],
    "premium_grace_period": [
        {"text": "甲产品的宽限期为60日。", "refs": ["P1/premium_grace_period"]}
    ],
}
BAD_GRACE = [{"text": "甲产品的宽限期为90日。", "refs": ["P1/premium_grace_period"]}]


class Model:
    def __init__(self, statements: dict[str, list[dict[str, Any]]]) -> None:
        self.statements = statements
        self.requests: list[list[str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        user = json.loads(json.loads(request.content)["messages"][1]["content"])
        keys = [concept["key"] for concept in user["concepts"]]
        self.requests.append(keys)
        concepts = [
            {
                "key": key,
                "definition": "读者定义。",
                "explanation": "通用解释。",
                "statements": self.statements[key],
            }
            for key in keys
        ]
        content = json.dumps({"concepts": concepts}, ensure_ascii=False)
        return httpx.Response(
            200,
            json={
                "model": "example-flash",
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            },
        )


class Platform:
    def __init__(self, release: Release) -> None:
        self.release = release.model_dump(mode="json")
        self.seen: list[tuple[str, str, Any]] = []
        self.members: list[Any] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path.removeprefix("/api/v1/enterprise/spaces/demo/")
        self.seen.append((request.method, path, body))
        if path == "releases/active":
            return ok(self.release)
        if path == "candidates":
            self.members = body["members"] if body else []
            return ok({"id": "cand_1", "status": "created"}, 201)
        if path == "candidates/cand_1/decisions":
            return ok(
                {"id": "dec_1", "candidate_id": "cand_1", "outcome": "approve", "digest": "e" * 64}
            )
        # The activated release, read back by the client, holds what was submitted.
        return ok({"id": "rel-10", "epoch": 16, "candidate_id": "cand_1", "members": self.members})


def ok(data: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"success": True, "data": data})


@pytest.fixture
def setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, release: Release
) -> Callable[[dict[str, list[dict[str, Any]]]], tuple[Model, Platform]]:
    stage = {
        "stage": "concepts", "provider": "example", "base_url": "https://api.example.com",
        "model": "example-flash", "api_key_env": "TEST_CONCEPT_KEY", "max_tokens": 1024,
        "policy_version": "concept-test",
    }  # fmt: skip
    (tmp_path / "stages.json").write_text(json.dumps({"stages": [stage]}), encoding="utf-8")
    monkeypatch.setenv(source_map_module.BASE_URL_ENV, "https://weknora.test")
    monkeypatch.setenv(source_map_module.API_KEY_ENV, "key-123")

    def install(statements: dict[str, list[dict[str, Any]]]) -> tuple[Model, Platform]:
        server, platform = Model(statements), Platform(release)
        real = OpenAICompatibleCompletion

        def completion(
            config: StageModelConfig, *, ledger: CallLedger
        ) -> OpenAICompatibleCompletion:
            return real(
                config, ledger=ledger, environ={config.api_key_env: "k"},
                transport=httpx.MockTransport(server), sleep=lambda seconds: None,
            )  # fmt: skip

        monkeypatch.setattr(concept_run, "OpenAICompatibleCompletion", completion)
        monkeypatch.setattr(
            concept_run,
            "PlatformClient",
            lambda base, key: PlatformClient(base, key, transport=httpx.MockTransport(platform)),
        )
        return server, platform

    return install


def run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], *extra: str
) -> tuple[int, dict[str, Any]]:
    argv = [
        "--space", "demo", "--stage", "concepts", "--stage-config", str(tmp_path / "stages.json"),
        "--run-root", str(tmp_path / "run"), *extra,
    ]  # fmt: skip
    code = concept_run.main(argv)
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and str(tmp_path) not in out[0]
    return code, json.loads(out[0])


def concepts(tmp_path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads((tmp_path / "run" / "concepts.json").read_text(encoding="utf-8"))
    return {item["concept_key"]: item for item in data["concepts"]}


def test_a_run_writes_checked_concepts_and_a_rerun_sends_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], setup: Any
) -> None:
    server, _ = setup(GOOD)
    code, report = run(tmp_path, capsys)
    assert code == 0 and report["sent"] == 1
    assert server.requests == [["cooling_off_period", "premium_grace_period"]]
    written = concepts(tmp_path)
    assert set(written) == {"cooling_off_period", "premium_grace_period"}
    cooling = written["cooling_off_period"]
    assert cooling["origin"] == "MODEL_GENERATED" and cooling["title"] == "犹豫期"
    assert cooling["based_on"] == {A: "a" * 64, B: "b" * 64, C: "c" * 64}
    again, _ = setup(GOOD)
    code, report = run(tmp_path, capsys)
    assert code == 0 and again.requests == []


def test_a_failing_concept_is_retried_once_then_left_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], setup: Any
) -> None:
    server, _ = setup({**GOOD, "premium_grace_period": BAD_GRACE})
    code, report = run(tmp_path, capsys)
    assert code == 0
    assert server.requests == [
        ["cooling_off_period", "premium_grace_period"],
        ["premium_grace_period"],
    ]
    assert set(concepts(tmp_path)) == {"cooling_off_period"}
    failed = json.loads((tmp_path / "run" / "report.json").read_text(encoding="utf-8"))["failed"]
    assert "NUMBER_UNSUPPORTED" in failed["premium_grace_period"]


def test_publish_submits_only_concept_members_on_the_head_it_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], setup: Any
) -> None:
    _, platform = setup(GOOD)
    code, report = run(tmp_path, capsys, "--publish", "--reason", "模型汇总，人工确认发布")
    assert code == 0 and report["release_id"] == "rel-10"
    submitted = next(body for method, path, body in platform.seen if path == "candidates")
    assert submitted["base_release_id"] == "rel-9" and submitted["removals"] == []
    assert {m["kind"] for m in submitted["members"]} == {"concept"}
    assert {m["logical_slug"] for m in submitted["members"]} == {
        "concept/cooling_off_period",
        "concept/premium_grace_period",
    }
    decision = next(body for method, path, body in platform.seen if path.endswith("/decisions"))
    assert decision == {"outcome": "approve", "mode": "human", "reason": "模型汇总，人工确认发布"}


def test_the_budget_stops_the_run_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], setup: Any
) -> None:
    server, _ = setup(GOOD)
    code, report = run(tmp_path, capsys, "--max-sent", "0")
    assert (code, report["stopped"]) == (2, "BUDGET_EXCEEDED")
    assert server.requests == [] and not (tmp_path / "run" / "concepts.json").exists()
