"""S4i acceptance: golden_items checks the pending-review list before it trusts it (Spec §3.4).

Protected file: written by Claude after review R3 on #203. Fields the manifest lists as pending
semantic review may not reach semantic scoring or calibration. A list that names no real field of
the product (a rename, another Golden version, a typo) must not read as "nothing pending": in both
modes it stops the run before anything is written. Synthetic fixtures only (RV2b's alpha and beta).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from insurance_harness.eval.golden_items import main

FIXTURE = Path(__file__).parent / "fixtures" / "golden_items"
MANIFEST = Path("dataset/golden/v2/manifest.json")


def repo_with(tmp_path: Path, pending: object) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    manifest = json.loads((repo / MANIFEST).read_text(encoding="utf-8"))
    manifest["pending_semantic_review"] = pending
    (repo / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return repo


def run(repo: Path, out: Path, *extra: str) -> int:
    return main(["--repo", str(repo), "--products", "alpha", "beta", "--out", str(out), *extra])


def last_line(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    line: dict[str, object] = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    return line


def test_a_valid_list_stops_by_default(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "items.jsonl"
    assert run(repo_with(tmp_path, {"alpha": ["field_a"]}), out) == 2
    assert last_line(capsys) == {"stopped": "GOLDEN_PENDING_REVIEW", "product": "alpha"}
    assert not out.exists()


def test_a_valid_list_is_excluded_only_when_asked_and_counted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "items.jsonl"
    assert run(repo_with(tmp_path, {"alpha": ["field_a"]}), out, "--exclude-pending") == 0
    summary = last_line(capsys)
    assert summary["excluded_pending"] == {"alpha": 1, "beta": 0}
    assert summary["products"] == {"alpha": 2, "beta": 2}
    written = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert ("alpha", "field_a") not in {(r["product_id"], r["field_key"]) for r in written}


@pytest.mark.parametrize(
    "listed",
    [
        ["field_c_typo"],  # names no field of this Golden
        ["field_a", " "],  # blank
        ["field_a", "field_a"],  # repeated
        [],  # an entry with nothing pending is not a record of anything
        "field_a",  # not a list
        [1],  # not a string
    ],
    ids=["missing", "blank", "duplicate", "empty", "not_list", "not_string"],
)
@pytest.mark.parametrize("extra", [(), ("--exclude-pending",)], ids=["default", "exclude"])
def test_a_list_that_does_not_match_the_golden_stops_in_both_modes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], listed: object, extra: tuple[str, ...]
) -> None:
    out = tmp_path / "items.jsonl"
    assert run(repo_with(tmp_path, {"alpha": listed}), out, *extra) == 2
    assert last_line(capsys) == {"stopped": "MANIFEST_PENDING_INVALID", "product": "alpha"}
    assert not out.exists()
