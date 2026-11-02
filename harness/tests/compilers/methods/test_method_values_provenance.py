"""SK-2c Spec r3 §3.1–§3.2, §4.1, §6.2–§6.6, §6.11 (RED, written by Claude, review #526 R1, R2, R4,
R5): a saved answer counts only with the ledger record of the call that returned it, for exactly
this request (source revisions included) and these request settings; every answer received is
kept raw, truncated ones too, never through a link out of the value directory."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.compilers.methods.compile import compile_methods
from insurance_harness.compilers.methods.responses import LedgerAnswers, ResponsesError
from insurance_harness.compilers.methods.values import ValuesStopped, method_values
from insurance_harness.models import StageModelConfig
from tests.compilers.methods.helpers import (
    DECK_A,
    METHOD_A,
    METHOD_C,
    World,
    candidate,
    candidates_of,
    claims_of,
    full_answer,
    method_use,
    unknown_answer,
)
from tests.compilers.methods.values_helpers import (
    SERVED,
    TRUNCATED,
    TRUNCATED_TEXT,
    Behaviour,
    FakeProvider,
    answered,
    install,
    stage_config,
)
from tests.ingest.method_helpers import deck_pages, source

SHA_D = "d" * 64


def deck_a(world: World) -> list[dict[str, Any]]:
    return [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))]


def both(world: World) -> list[dict[str, Any]]:
    return [*deck_a(world), candidate(METHOD_C, world.raw_c, world.hits("k-deck-c"))]


def again(
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    items: Sequence[Mapping[str, Any]],
    root: Path,
    answers: Mapping[str, Behaviour],
    config: StageModelConfig | None = None,
    **provider: Any,
) -> tuple[FakeProvider, dict[str, Any] | ValuesStopped]:
    """Another value run on the same directory: its provider and its summary, or its stop."""
    model = FakeProvider(answers, **provider)
    install(monkeypatch, model)
    try:
        return model, method_values(
            world.registry, candidates_of(world, items), pages=world.reader, root=root,
            config=config or stage_config(), max_sent=10,
        )
    except ValuesStopped as stop:
        return model, stop


def code_of(result: dict[str, Any] | ValuesStopped) -> str:
    assert isinstance(result, ValuesStopped), result
    return result.code


def answer_file(root: Path) -> Path:
    (path,) = root.glob("*.txt")
    return path


def rewrite_ledger(root: Path, **change: Any) -> None:
    lines = (root / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    for record in records:
        if record["outcome"] == "ok":
            record.update(change)
    (root / "ledger.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


def revise_deck_a(world: World, sha256: str) -> None:
    """Deck A as a new source revision (next parse attempt, other bytes) with the same text."""
    old = world.raws["k-deck-a"]
    raw = source("k-deck-a", old.file_name, sha256, attempt=old.parse_attempt + 1)
    pages = list(deck_pages(old.file_name, sha256, DECK_A))
    world.decks["k-deck-a"] = pages
    world.reader.decks["k-deck-a"] = pages
    world.raws["k-deck-a"] = world.raw_a = raw
    world.registry.method_uses = [
        method_use(raw, pages) if use.knowledge_id == "k-deck-a" else use
        for use in world.registry.method_uses
    ]


# --- R1: a saved answer is bound to its call ----------------------------------------------


def test_the_ledger_records_what_each_saved_answer_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    answered(monkeypatch, world, deck_a(world), tmp_path, {METHOD_A: full_answer})
    text = answer_file(tmp_path).read_bytes()
    (record,) = [
        json.loads(line)
        for line in (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert record["outcome"] == "ok" and record["served_model"] == SERVED
    assert record["response_sha256"] == hashlib.sha256(text).hexdigest()
    stage = json.loads((tmp_path / "stage.json").read_text(encoding="utf-8"))
    assert StageModelConfig.model_validate(stage) == stage_config()


def test_another_valid_answer_in_place_of_the_saved_one_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    answered(monkeypatch, world, deck_a(world), tmp_path, {METHOD_A: full_answer})
    saved = answer_file(tmp_path)
    answer = json.loads(saved.read_text(encoding="utf-8"))
    for row in answer["predicates"]:  # still a well-formed answer, but not the one received
        row["state"] = "unknown"
        row.pop("items", None)
    saved.write_text(json.dumps(answer, ensure_ascii=False), encoding="utf-8")
    model, result = again(monkeypatch, world, both(world), tmp_path, {METHOD_C: unknown_answer})
    assert code_of(result) == "RUN_ROOT_INVALID" and model.calls == []
    with pytest.raises(ResponsesError) as raised:
        compile_methods(
            world.registry, candidates_of(world, deck_a(world)), pages=world.reader,
            port=LedgerAnswers(tmp_path), active=None,
        )
    assert raised.value.code == "RUN_ROOT_INVALID"


def test_a_ledger_record_for_another_request_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    answered(monkeypatch, world, deck_a(world), tmp_path, {METHOD_A: full_answer})
    rewrite_ledger(tmp_path, request_sha256="0" * 64)
    model, result = again(monkeypatch, world, deck_a(world), tmp_path, {METHOD_A: full_answer})
    assert code_of(result) == "RUN_ROOT_INVALID" and model.calls == []
    with pytest.raises(ResponsesError):
        compile_methods(
            world.registry, candidates_of(world, deck_a(world)), pages=world.reader,
            port=LedgerAnswers(tmp_path), active=None,
        )


def test_answers_without_the_directory_stage_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    answered(monkeypatch, world, deck_a(world), tmp_path, {METHOD_A: full_answer})
    (tmp_path / "stage.json").unlink()
    model, result = again(monkeypatch, world, deck_a(world), tmp_path, {METHOD_A: full_answer})
    assert code_of(result) == "RUN_ROOT_INVALID" and model.calls == []
    with pytest.raises(ResponsesError):
        LedgerAnswers(tmp_path)


def test_the_compile_port_replays_verified_answers_with_their_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    answered(monkeypatch, world, deck_a(world), tmp_path, {METHOD_A: full_answer})
    port = LedgerAnswers(tmp_path)
    assert port.model == SERVED
    run = compile_methods(
        world.registry, candidates_of(world, deck_a(world)), pages=world.reader, port=port,
        active=None,
    )
    claims = claims_of(run.bundle)
    assert len(claims) == 5 and {c.provenance.model for c in claims.values()} == {SERVED}
    with pytest.raises(ResponsesError) as raised:
        LedgerAnswers(tmp_path, model="another-model")
    assert raised.value.code == "MODEL_MISMATCH"


# --- R2: source revisions and request settings ---------------------------------------------


def test_a_new_source_revision_with_the_same_text_is_asked_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    answered(monkeypatch, world, deck_a(world), tmp_path, {METHOD_A: full_answer})
    revise_deck_a(world, SHA_D)
    replayed = compile_methods(
        world.registry, candidates_of(world, deck_a(world)), pages=world.reader,
        port=LedgerAnswers(tmp_path), active=None,
    )
    assert [m["code"] for m in replayed.report["methods"]] == ["RESPONSE_MISSING"]
    model, result = again(monkeypatch, world, deck_a(world), tmp_path, {METHOD_A: full_answer})
    assert isinstance(result, dict) and result["codes"] == {"answered": 1}
    assert model.calls == [METHOD_A]
    payload = json.loads(json.loads(model.bodies[0])["messages"][1]["content"])
    assert payload["materials"] == [{"ref": "M1", "revision": f"k-deck-a/2/{SHA_D}"}]


@pytest.mark.parametrize(
    "change", [{"temperature": 1.0}, {"max_tokens": 2000}, {"thinking": "enabled"}]
)
def test_other_request_settings_refuse_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]
) -> None:
    world = World()
    answered(monkeypatch, world, deck_a(world), tmp_path, {METHOD_A: full_answer})
    model, result = again(
        monkeypatch, world, deck_a(world), tmp_path, {METHOD_A: full_answer},
        config=stage_config(**change),
    )
    assert code_of(result) == "RUN_ROOT_MODEL_CHANGED" and model.calls == []


def test_operational_settings_keep_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    answered(monkeypatch, world, deck_a(world), tmp_path, {METHOD_A: full_answer})
    config = stage_config(max_attempts=2, timeout_s=30.0)
    model, result = again(
        monkeypatch, world, deck_a(world), tmp_path, {METHOD_A: full_answer}, config=config
    )
    assert isinstance(result, dict) and result["codes"] == {"saved": 1}
    assert model.calls == []


# --- R4: every answer received is kept, and a changed version stops the run ------------------


def test_a_truncated_answer_is_kept_raw_without_an_answer_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    summary = answered(monkeypatch, world, deck_a(world), tmp_path, {METHOD_A: TRUNCATED})
    assert summary["codes"] == {"VALUE_TRUNCATED": 1}
    assert (tmp_path / "raw" / "001.txt").read_text(encoding="utf-8") == TRUNCATED_TEXT
    assert list(tmp_path.glob("*.txt")) == []


def test_a_truncated_answer_from_another_served_version_stops_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    answered(monkeypatch, world, deck_a(world), tmp_path, {METHOD_A: full_answer})
    _, result = again(
        monkeypatch, world, both(world), tmp_path, {METHOD_C: TRUNCATED}, served="served-model-2"
    )
    assert code_of(result) == "SERVED_MODEL_CHANGED"
    assert sorted(p.name for p in (tmp_path / "raw").iterdir()) == ["001.txt"]


# --- R5: nothing is written through a link -------------------------------------------------


def test_a_raw_directory_linked_into_a_repository_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "repo" / "kept"
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    target.mkdir()
    root = tmp_path / "values"
    root.mkdir()
    (root / "raw").symlink_to(target, target_is_directory=True)
    world = World()
    model, result = again(monkeypatch, world, deck_a(world), root, {METHOD_A: full_answer})
    assert code_of(result) == "RUN_ROOT_INVALID" and model.calls == []
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("name", ["ledger.jsonl", "budget.jsonl", "stage.json", ".lock"])
def test_a_run_file_linked_out_of_the_directory_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    root = tmp_path / "values"
    root.mkdir()
    (root / name).symlink_to(tmp_path / "elsewhere")
    world = World()
    model, result = again(monkeypatch, world, deck_a(world), root, {METHOD_A: full_answer})
    assert code_of(result) == "RUN_ROOT_INVALID" and model.calls == []
    assert not (tmp_path / "elsewhere").exists()
