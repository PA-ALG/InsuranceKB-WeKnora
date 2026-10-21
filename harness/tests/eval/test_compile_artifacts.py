"""Candidate and product-name mapping remain readable across interrupted refreshes."""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.eval.compile_run import ProductRun, write_candidate
from insurance_harness.eval.convert import predictions_from_candidate
from tests.eval.test_compile_materials import compile_at
from tests.eval.test_compile_materials import repo as repo


def artifacts(root: Path) -> tuple[dict[str, Any], dict[str, str]]:
    return (
        json.loads((root / "candidate.json").read_text()),
        json.loads((root / "product-map.json").read_text()),
    )


def prepare(repo: Path, root: Path) -> list[ProductRun]:
    compile_at(repo, root, [])
    write_candidate(root, [ProductRun("p", "旧名称", "pack", False, 1, 1)])
    assert len(predictions_from_candidate(*artifacts(root))) == 1
    return [ProductRun("p", "新名称", "pack", True, 0, 1)]


@pytest.mark.parametrize("failure", [1, 2, 3])
def test_refresh_failure_preserves_readable_pair_and_retry_converges(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: int,
) -> None:
    root = tmp_path / "run"
    runs = prepare(repo, root)
    real_replace = os.replace
    replaced: list[str] = []

    def interrupted(source: str, target: Path) -> None:
        assert len(predictions_from_candidate(*artifacts(root))) == 1
        replaced.append(target.name)
        if len(replaced) == failure:
            raise OSError("interrupted artifact refresh")
        real_replace(source, target)
        assert len(predictions_from_candidate(*artifacts(root))) == 1

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", interrupted)
        with pytest.raises(OSError, match="interrupted artifact refresh"):
            write_candidate(root, runs, replace=True)
    candidate, mapping = artifacts(root)
    assert len(predictions_from_candidate(candidate, mapping)) == 1
    assert replaced == ["product-map.json", "candidate.json", "product-map.json"][:failure]
    assert mapping == ({"旧名称": "p"} if failure == 1 else {"旧名称": "p", "新名称": "p"})
    name = candidate["request"]["entity_bindings"][0]["display_name"]
    assert name == ("新名称" if failure == 3 else "旧名称")
    write_candidate(root, runs, replace=True)
    assert artifacts(root)[1] == {"新名称": "p"}
    assert len(predictions_from_candidate(*artifacts(root))) == 1
    assert sorted(path.name for path in root.iterdir()) == [
        ".lock", "budget.jsonl", "candidate.json", "ledger.jsonl", "p", "product-map.json",
    ]


@pytest.mark.parametrize("name", ["旧名称", " 旧 名称 "])
def test_conflicting_old_registration_stops_before_writing_either_artifact(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str,
) -> None:
    root = tmp_path / "run"
    prepare(repo, root)
    output = CompileOutput.model_validate_json((root / "p/output.json").read_text())
    other = root / "p2/output.json"
    other.parent.mkdir()
    other.write_text(output.model_copy(update={"entity_id": "p2"}).model_dump_json())
    old = [(root / filename).read_bytes() for filename in ("candidate.json", "product-map.json")]
    replaced: list[object] = []
    monkeypatch.setattr(os, "replace", lambda *args: replaced.append(args))
    with pytest.raises(ValueError):
        write_candidate(root, [ProductRun("p2", name, "pack", False, 1, 1)], replace=True)
    assert replaced == []
    assert old == [(root / filename).read_bytes()
                   for filename in ("candidate.json", "product-map.json")]


@pytest.mark.parametrize("broken", [
    '[]', '{}', '{"旧名称": 3}', '{"": "p"}', '"SOURCE-SECRET"', '{broken',
])
def test_invalid_old_mapping_stops_before_any_artifact_write(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, broken: str,
) -> None:
    root = tmp_path / "run"
    runs = prepare(repo, root)
    (root / "product-map.json").write_text(broken)
    old = (root / "candidate.json").read_bytes()
    replaced: list[object] = []
    monkeypatch.setattr(os, "replace", lambda *args: replaced.append(args))
    with pytest.raises(ValueError):
        write_candidate(root, runs, replace=True)
    assert replaced == [] and (root / "candidate.json").read_bytes() == old
    assert (root / "product-map.json").read_text() == broken


def test_missing_old_mapping_refuses_refresh_before_writing_candidate(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "run"
    runs = prepare(repo, root)
    (root / "product-map.json").unlink()
    old = (root / "candidate.json").read_bytes()
    replaced: list[object] = []
    monkeypatch.setattr(os, "replace", lambda *args: replaced.append(args))
    with pytest.raises(FileNotFoundError):
        write_candidate(root, runs, replace=True)
    assert replaced == [] and (root / "candidate.json").read_bytes() == old
