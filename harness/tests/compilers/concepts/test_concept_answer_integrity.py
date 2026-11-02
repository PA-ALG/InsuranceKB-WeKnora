"""H1 frozen RED: concept cache authenticity, semantic identity and safe retention."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.compilers.concepts.test_concept_run_recovery import GOOD
from tests.compilers.concepts.test_concept_run_recovery import run as prepared_run  # noqa: F401


@pytest.fixture
def run(request: pytest.FixtureRequest) -> Any:
    return request.getfixturevalue("prepared_run")


@pytest.mark.parametrize("damage", ["value", "legacy", "request", "model"])
def test_concept_answer_needs_successful_ledger_binding(
    tmp_path: Path, run: Any, damage: str,
) -> None:
    assert run(GOOD)[0] == 0
    root = tmp_path / "run"
    if damage == "value":
        answer = root / "responses/001.txt"
        answer.write_text(answer.read_text().replace("定义。", "另一个定义。"))
    else:
        path = root / "ledger.jsonl"
        records = [json.loads(line) for line in path.read_text().splitlines()]
        for row in records:
            if damage == "legacy":
                row.pop("response_sha256", None)
            elif damage == "request":
                row["request_sha256"] = "e" * 64
            else:
                row["served_model"] = "another-model"
        path.write_text("".join(json.dumps(row) + "\n" for row in records))
    code, report, server = run(GOOD)
    assert code == 2 and report["stopped"] == "RUN_ROOT_INVALID"
    assert server.requests == [] and not (root / "concepts.json").exists()


@pytest.mark.parametrize("changes", [
    {"temperature": 0.7}, {"max_tokens": 2048},
    {"thinking": "enabled", "reasoning_effort": "high"},
])
def test_concept_semantic_settings_do_not_reuse_old_answers(
    tmp_path: Path, run: Any, changes: dict[str, object],
) -> None:
    assert run(GOOD)[0] == 0
    stages = tmp_path / "stages.json"
    data = json.loads(stages.read_text())
    data["stages"][0].update(changes)
    stages.write_text(json.dumps(data))
    code, _, server = run(GOOD)
    assert code == 0 and len(server.requests) == 1


def test_concept_truncated_text_is_kept_before_run_stops(
    tmp_path: Path, run: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = httpx.MockTransport.handle_request

    def truncate(self: httpx.MockTransport, request: httpx.Request) -> httpx.Response:
        response = original(self, request)
        data = response.json()
        if "choices" in data:
            data["choices"][0]["finish_reason"] = "length"
            return httpx.Response(200, json=data)
        return response

    monkeypatch.setattr(httpx.MockTransport, "handle_request", truncate)
    code, report, server = run(GOOD)
    assert code == 2 and report["stopped"] == "MODEL_ERROR"
    assert len(server.requests) == 1
    assert json.loads((tmp_path / "run/responses/001.txt").read_text())["concepts"]
    assert not (tmp_path / "run/concepts.json").exists()


def test_concept_answer_directory_may_not_be_a_link(tmp_path: Path, run: Any) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "run"
    root.mkdir()
    (root / "responses").symlink_to(outside, target_is_directory=True)
    code, report, server = run(GOOD)
    assert code == 2 and report["stopped"] == "RUN_ROOT_INVALID"
    assert server.requests == [] and list(outside.iterdir()) == []
