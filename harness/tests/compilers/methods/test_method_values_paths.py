"""SK-2c Spec r4 §3.1, §6.14 (RED, written by Claude, review #526 round 2 R5a, R5b): one check of
the value directory before a value run sends or writes and before a compile reads: neither the
directory nor raw/ lies in a git work tree, no entry of either is a link, and a saved answer is
never read through a link."""

import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.compilers.methods import cli
from insurance_harness.compilers.methods.compile import compile_methods
from insurance_harness.compilers.methods.responses import (
    LedgerAnswers,
    ResponsesError,
    SavedResponses,
)
from insurance_harness.compilers.methods.values import ValuesStopped, method_values
from insurance_harness.ingest.registry import save_registry
from insurance_harness.ingest.source_map import API_KEY_ENV, BASE_URL_ENV
from tests.compilers.methods.helpers import (
    METHOD_A,
    METHOD_C,
    FakeModel,
    World,
    candidate,
    candidate_file,
    candidates_of,
    copy_entry,
    full_answer,
    unknown_answer,
)
from tests.compilers.methods.values_helpers import FakeProvider, answered, install, stage_config


def deck_a(world: World) -> list[dict[str, Any]]:
    return [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))]


def both(world: World) -> list[dict[str, Any]]:
    return [*deck_a(world), candidate(METHOD_C, world.raw_c, world.hits("k-deck-c"))]


def values_stop(
    monkeypatch: pytest.MonkeyPatch, world: World, items: list[dict[str, Any]], root: Path
) -> tuple[FakeProvider, str]:
    model = FakeProvider({METHOD_A: full_answer, METHOD_C: unknown_answer})
    install(monkeypatch, model)
    with pytest.raises(ValuesStopped) as raised:
        method_values(
            world.registry, candidates_of(world, items), pages=world.reader, root=root,
            config=stage_config(), max_sent=10,
        )
    return model, raised.value.code


def compile_with(world: World, port: Any) -> None:
    compile_methods(
        world.registry, candidates_of(world, deck_a(world)), pages=world.reader, port=port,
        active=None,
    )


# --- R5a: raw/ itself, not only the directory's ancestors ------------------------------------


def test_a_raw_directory_that_is_a_repository_is_refused_before_any_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "values"
    (root / "raw" / ".git").mkdir(parents=True)
    world = World()
    model, code = values_stop(monkeypatch, world, deck_a(world), root)
    assert code == "RUN_ROOT_INVALID" and model.calls == []
    assert sorted(p.name for p in (root / "raw").iterdir()) == [".git"]
    assert sorted(p.name for p in root.iterdir()) == ["raw"]  # nothing else was written


def test_the_compile_refuses_a_value_directory_whose_raw_is_a_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    answered(monkeypatch, world, deck_a(world), tmp_path, {METHOD_A: full_answer})
    (tmp_path / "raw" / ".git").mkdir()
    with pytest.raises(ResponsesError) as raised:
        LedgerAnswers(tmp_path)
    assert raised.value.code == "RUN_ROOT_INVALID"


# --- R5b: saved answers are never read through a link ----------------------------------------


def moved_behind_a_link(root: Path, elsewhere: Path) -> None:
    """The saved answer moved out of the directory, a link left in its place: same bytes."""
    (saved,) = root.glob("*.txt")
    elsewhere.mkdir()
    target = elsewhere / saved.name
    saved.rename(target)
    saved.symlink_to(target)


def test_a_saved_answer_behind_a_link_is_refused_before_any_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    root = tmp_path / "values"
    answered(monkeypatch, world, deck_a(world), root, {METHOD_A: full_answer})
    moved_behind_a_link(root, tmp_path / "elsewhere")
    model, code = values_stop(monkeypatch, world, both(world), root)
    assert code == "RUN_ROOT_INVALID" and model.calls == []
    with pytest.raises(ResponsesError):
        compile_with(world, LedgerAnswers(root))


def test_any_link_in_the_directory_or_raw_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    root = tmp_path / "values"
    answered(monkeypatch, world, deck_a(world), root, {METHOD_A: full_answer})
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    (root / "raw" / "002.txt").symlink_to(tmp_path / "note.txt")
    model, code = values_stop(monkeypatch, world, both(world), root)
    assert code == "RUN_ROOT_INVALID" and model.calls == []
    (root / "raw" / "002.txt").unlink()
    (root / "notes").symlink_to(tmp_path / "note.txt")
    model, code = values_stop(monkeypatch, world, both(world), root)
    assert code == "RUN_ROOT_INVALID" and model.calls == []


def test_an_offline_answer_behind_a_link_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The hand-prepared directory of SK-2a's offline interface reads without following links."""
    world = World()
    memory = FakeModel({METHOD_A: full_answer})
    compile_with(world, memory)
    root = tmp_path / "hand"
    root.mkdir()
    (digest, _, answer) = memory.sent[0]
    (tmp_path / "kept.txt").write_text(answer, encoding="utf-8")
    (root / f"{digest}.txt").symlink_to(tmp_path / "kept.txt")
    with pytest.raises(ResponsesError) as raised:
        compile_with(world, SavedResponses(root, "hand-model"))
    assert raised.value.code == "RUN_ROOT_INVALID"

    registry = tmp_path / "registry.json"
    save_registry(world.registry, registry)
    candidates = tmp_path / "candidates.json"
    copies = [copy_entry(raw) for raw in world.raws.values()]
    candidates.write_text(json.dumps(candidate_file(copies, deck_a(world))), encoding="utf-8")
    monkeypatch.setattr(cli, "reader_from_env", lambda: world.reader)
    monkeypatch.setattr(cli, "PlatformClient", lambda *_: _NoActive())
    monkeypatch.setenv(BASE_URL_ENV, "https://platform.invalid")
    monkeypatch.setenv(API_KEY_ENV, "test-only")
    before = registry.read_bytes()
    status = cli.main([
        "compile", "--registry", str(registry), "--candidates", str(candidates),
        "--responses", str(root), "--run-root", str(tmp_path / "run"), "--model", "hand-model",
    ])
    assert (status, json.loads(capsys.readouterr().out)) == (2, {"stopped": "RUN_ROOT_INVALID"})
    assert registry.read_bytes() == before


class _NoActive:
    def active(self, space_id: str) -> None:
        return None


def test_regular_saved_answers_are_still_reused_without_a_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    answered(monkeypatch, world, deck_a(world), tmp_path, {METHOD_A: full_answer})
    created = install(monkeypatch, None)
    summary = method_values(
        world.registry, candidates_of(world, deck_a(world)), pages=world.reader, root=tmp_path,
        config=stage_config(), max_sent=10,
    )
    assert summary["codes"] == {"saved": 1} and created == []
    compile_with(world, LedgerAnswers(tmp_path))


# --- R5c (round 3): a non-regular answer is refused at once, never opened blocking ------------

_CHILD = """
import json, os, sys
from pathlib import Path
from insurance_harness.compilers.methods.responses import (
    LedgerAnswers, ResponsesError, SavedResponses,
)
root, request, mode = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()), sys.argv[3]
(answer,) = root.glob("*.txt")
port = LedgerAnswers(root) if mode == "ledger" else SavedResponses(root, "hand-model")
answer.unlink()
os.mkfifo(answer)  # no writer: a blocking open would never return
try:
    port.complete(system=request["system"], user=request["user"])
    print("READ")
except ResponsesError as error:
    print(error.code)
"""


@pytest.mark.parametrize("mode", ["ledger", "offline"])
def test_a_saved_answer_replaced_by_a_fifo_is_refused_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """Replaced after the port checked the directory: the read itself must not block. Run in a
    child process with a timeout, so a blocking open fails this test instead of hanging it."""
    import subprocess
    import sys

    world = World()
    model = FakeProvider({METHOD_A: full_answer})
    install(monkeypatch, model)
    root = tmp_path / "values"
    method_values(
        world.registry, candidates_of(world, deck_a(world)), pages=world.reader, root=root,
        config=stage_config(), max_sent=10,
    )
    messages = json.loads(model.bodies[0])["messages"]
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({"system": messages[0]["content"], "user": messages[1]["content"]}),
        encoding="utf-8",
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", _CHILD, str(root), str(request), mode],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert done.stdout.strip() == "RUN_ROOT_INVALID", done.stderr[-500:]


@pytest.mark.parametrize("where", ["root", "raw"])
def test_a_non_regular_entry_in_the_directory_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """Every entry is a regular file (or the raw/ directory): a FIFO named like a run file or an
    answer is refused by the directory check, which never opens anything."""
    import os

    from insurance_harness.compilers.methods.responses import check_value_directory

    world = World()
    answered(monkeypatch, world, deck_a(world), tmp_path, {METHOD_A: full_answer})
    os.mkfifo(tmp_path / ("stage.json.fifo" if where == "root" else "raw/002.txt"))
    with pytest.raises(ResponsesError) as raised:
        check_value_directory(tmp_path)
    assert raised.value.code == "RUN_ROOT_INVALID"
