"""H1 frozen RED: real adapters over synthetic HTTP; no model or platform calls."""

import json
from pathlib import Path

import httpx
import pytest

from insurance_harness.eval.compile_run import compile_products
from insurance_harness.models import TruncatedCompletion
from tests.eval.test_compile_run import factory
from tests.eval.test_compile_run import repo as prepared_compile_repo  # noqa: F401
from tests.eval.test_review_run import Install, Run
from tests.eval.test_review_run import model as prepared_model  # noqa: F401
from tests.eval.test_review_run import repo as prepared_repo  # noqa: F401
from tests.eval.test_review_run import run as prepared_run  # noqa: F401


@pytest.fixture
def compile_repo(request: pytest.FixtureRequest) -> Path:
    return request.getfixturevalue("prepared_compile_repo")  # type: ignore[no-any-return]


@pytest.fixture
def repo(request: pytest.FixtureRequest) -> Path:
    return request.getfixturevalue("prepared_repo")  # type: ignore[no-any-return]


@pytest.fixture
def model(request: pytest.FixtureRequest) -> Install:
    return request.getfixturevalue("prepared_model")  # type: ignore[no-any-return]


@pytest.fixture
def run(request: pytest.FixtureRequest) -> Run:
    return request.getfixturevalue("prepared_run")  # type: ignore[no-any-return]


def compile_one(repo: Path, root: Path) -> list[httpx.Request]:
    build, sent = factory(["served-v1"] * 20)
    compile_products(repo, ["p1"], completion_factory=build, run_root=root, max_sent=20)
    return sent


def replay(repo: Path, root: Path, destination: Path) -> None:
    compile_products(repo, ["p1"], completion_factory=None, run_root=destination,
                     max_sent=0, replay_from=root)


@pytest.mark.parametrize("damage", ["value", "response_hash", "request_hash", "served", "legacy"])
def test_product_replay_requires_successful_call_binding(
    compile_repo: Path, tmp_path: Path, damage: str,
) -> None:
    root = tmp_path / "source"
    compile_one(compile_repo, root)
    ledger_path = root / "ledger.jsonl"
    records = [json.loads(line) for line in ledger_path.read_text().splitlines()]
    if damage == "value":
        answer = root / "p1/responses/attempt-01/002.txt"
        answer.write_text(answer.read_text().replace("90日", "180日"))
    else:
        key = {"response_hash": "response_sha256", "request_hash": "request_sha256",
               "served": "served_model", "legacy": "response_sha256"}[damage]
        for row in records:
            if damage == "legacy":
                row.pop(key, None)
            else:
                row[key] = "another-model" if damage == "served" else "f" * 64
        ledger_path.write_text("".join(json.dumps(row) + "\n" for row in records))
    with pytest.raises(ValueError):
        replay(compile_repo, root, tmp_path / "out")
    assert not (tmp_path / "out/p1/output.json").exists()


def test_product_replay_uses_served_identity_without_sends(
    compile_repo: Path, tmp_path: Path,
) -> None:
    root = tmp_path / "source"
    assert len(compile_one(compile_repo, root)) == 2
    replay(compile_repo, root, tmp_path / "out")
    output = json.loads((tmp_path / "out/p1/output.json").read_text())
    assert output["model"] == "served-v1"
    assert not (tmp_path / "out/ledger.jsonl").exists()


def test_product_checks_saved_answers_before_another_product_send(
    compile_repo: Path, tmp_path: Path,
) -> None:
    root = tmp_path / "run"
    compile_one(compile_repo, root)
    answer = root / "p1/responses/attempt-01/002.txt"
    answer.write_text(answer.read_text().replace("90日", "180日"))
    build, sent = factory(["served-v1"] * 10)
    with pytest.raises(ValueError):
        compile_products(compile_repo, ["p2"], completion_factory=build, run_root=root, max_sent=20)
    assert sent == [] and not (root / "p2/output.json").exists()


def test_product_keeps_truncation_and_stops(compile_repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "run"
    build, sent = factory(["served-v1"], ["length"])
    with pytest.raises(TruncatedCompletion):
        compile_products(compile_repo, ["p1", "p2"], completion_factory=build,
                         run_root=root, max_sent=20)
    assert len(sent) == 1
    assert json.loads((root / "p1/responses/attempt-01/001.txt").read_text())["fields"]
    assert not (root / "p1/output.json").exists()


@pytest.mark.parametrize("kind", ["link", "git", "fifo"])
def test_product_rejects_unsafe_answer_tree_before_send(
    compile_repo: Path, tmp_path: Path, kind: str,
) -> None:
    import os

    root, outside = tmp_path / "run", tmp_path / "outside"
    outside.mkdir()
    destination = root / "p1/responses"
    destination.parent.mkdir(parents=True)
    if kind == "link":
        destination.symlink_to(outside, target_is_directory=True)
    else:
        destination.mkdir()
        if kind == "git":
            (destination / ".git").write_text("gitdir: nowhere")
        else:
            os.mkfifo(destination / "stray.txt")
    build, sent = factory(["served-v1"] * 10)
    with pytest.raises(ValueError):
        compile_products(compile_repo, ["p1"], completion_factory=build, run_root=root, max_sent=20)
    assert sent == [] and list(outside.iterdir()) == []


@pytest.mark.parametrize("damage", ["value", "legacy", "request", "model"])
def test_review_preflights_answers_before_any_new_send(
    tmp_path: Path, model: Install, run: Run, damage: str,
) -> None:
    model()
    assert run()[0] == 0
    root = tmp_path / "run"
    if damage == "value":
        answer = root / "p1/responses/001.txt"
        answer.write_text(answer.read_text().replace("0.8", "0.2"))
    else:
        path = root / "ledger.jsonl"
        records = [json.loads(line) for line in path.read_text().splitlines()]
        for row in records:
            if damage == "legacy":
                row.pop("response_sha256", None)
            elif damage == "request":
                row["request_sha256"] = "f" * 64
            else:
                row["served_model"] = "other-model"
        path.write_text("".join(json.dumps(row) + "\n" for row in records))
    server = model()
    code, summary, _ = run()
    assert code == 2 and summary["stopped"] == "RUN_ROOT_INVALID"
    assert server.requests == [] and not (root / "p1/scores.json").exists()


@pytest.mark.parametrize("changes", [
    {"temperature": 0.7}, {"max_tokens": 8192},
    {"thinking": "enabled", "reasoning_effort": "high"},
])
def test_review_semantic_config_is_part_of_request_identity(
    tmp_path: Path, model: Install, run: Run, changes: dict[str, object],
) -> None:
    model()
    assert run()[0] == 0
    stages = tmp_path / "stages.json"
    data = json.loads(stages.read_text())
    data["stages"][0].update(changes)
    stages.write_text(json.dumps(data))
    server = model()
    assert run()[0] == 0 and len(server.requests) == 1


def test_review_operational_change_keeps_verified_answer(
    tmp_path: Path, model: Install, run: Run,
) -> None:
    model()
    assert run()[0] == 0
    stages = tmp_path / "stages.json"
    data = json.loads(stages.read_text())
    data["stages"][0].update(timeout_s=30.0, max_attempts=1, api_key_env="NEW_TEST_KEY")
    stages.write_text(json.dumps(data))
    server = model()
    assert run()[0] == 0 and server.requests == []


def test_review_unknown_reservation_does_not_send_again(
    tmp_path: Path, model: Install, run: Run,
) -> None:
    model()
    assert run()[0] == 0
    root = tmp_path / "run"
    with (root / "budget.jsonl").open("a") as stream:
        stream.write('{"reserved":1}\n')
    stages = tmp_path / "stages.json"
    data = json.loads(stages.read_text())
    data["stages"][0]["temperature"] = 0.6
    stages.write_text(json.dumps(data))
    server = model()
    assert run()[0] == 2 and server.requests == []
