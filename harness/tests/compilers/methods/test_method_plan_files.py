"""#516 review R2 (written by Claude): a run's plan files are one set, or visibly incomplete.

`report.json` is put in place last and names the digests of the other plan files: a run root
without it, or whose digests differ, holds no complete plan. A failure while the files are being
prepared leaves the previous set exactly as it was.
"""

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.ingest.registry import ProductRegistry
from tests.compilers.methods.helpers import METHOD_A, World, full_answer, unknown_answer
from tests.compilers.methods.test_method_compile_cli import Setup, deck_a

REAL_REPLACE = os.replace
REAL_WRITE_TEXT = Path.write_text


def files(run_root: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(run_root.iterdir())}


def second_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> tuple[Setup, Setup]:
    """A successful run, then a second one with other answers into the same run root."""
    world = World()
    one = Setup(tmp_path / "one", monkeypatch, world, deck_a(world), {METHOD_A: full_answer})
    assert one.main(capsys)[0] == 0
    world.registry = ProductRegistry.model_validate_json(one.registry.read_bytes())
    two = Setup(tmp_path / "two", monkeypatch, world, deck_a(world), {METHOD_A: unknown_answer})
    two.run_root = one.run_root
    return one, two


def failing(when: Callable[[str], bool]) -> Callable[..., Any]:
    def write_text(self: Path, *args: Any, **kwargs: Any) -> int:
        if when(self.name):
            raise OSError("disk full")
        return REAL_WRITE_TEXT(self, *args, **kwargs)

    return write_text


def test_a_failure_while_preparing_keeps_the_previous_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, two = second_run(tmp_path, monkeypatch, capsys)
    before, registry = files(two.run_root), two.registry.read_bytes()
    monkeypatch.setattr(Path, "write_text", failing(lambda name: "review_items" in name))
    status, summary = two.main(capsys)
    assert (status, summary) == (2, {"stopped": "LOCAL_IO_FAILED"})
    assert files(two.run_root) == before  # nothing new, nothing left behind
    assert two.registry.read_bytes() == registry


def test_a_failure_while_putting_files_in_place_leaves_no_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, two = second_run(tmp_path, monkeypatch, capsys)
    registry = two.registry.read_bytes()

    def replace(source: Any, target: Any) -> None:
        if Path(target).name == "review_items.json":
            raise OSError("disk full")
        REAL_REPLACE(source, target)

    monkeypatch.setattr(os, "replace", replace)
    assert two.main(capsys) == (2, {"stopped": "LOCAL_IO_FAILED"})
    assert not (two.run_root / "report.json").exists()  # the set is visibly incomplete
    assert two.registry.read_bytes() == registry

    monkeypatch.setattr(os, "replace", REAL_REPLACE)  # recovery: the same run again
    assert two.main(capsys)[0] == 0
    assert_complete(two.run_root)


def assert_complete(run_root: Path) -> None:
    report = json.loads((run_root / "report.json").read_text(encoding="utf-8"))
    for name, expected in report["plan"].items():
        path = run_root / name
        if expected is None:
            assert not path.exists()
        else:
            assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    assert not [path for path in run_root.iterdir() if path.name.startswith(".")]


def test_the_report_names_the_plan_it_belongs_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    one, two = second_run(tmp_path, monkeypatch, capsys)
    assert_complete(one.run_root)
    report = json.loads((one.run_root / "report.json").read_text(encoding="utf-8"))
    assert set(report["plan"]) == {"candidate.json", "review_items.json"}
    assert report["plan"]["candidate.json"] is not None
