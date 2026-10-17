"""A repeated JSON member name in any RV2b input stops the run; last-one-wins never applies.

Review R1 on PR #197: a duplicate can silently flip a label, a score or a product's pack and still
yield a threshold. Every input is decoded raw with duplicates rejected at any depth, before shape
validation, and the run stops with the input's existing unreadable/invalid code, writing nothing.
The texts are written by hand because json.dumps cannot produce duplicate members.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from insurance_harness.eval import golden_items, review_calibration

FIXTURE = Path(__file__).parent / "fixtures" / "golden_items"
GOLDEN = Path("dataset/golden/v2")
REVIEWED_AT = "2026-10-17T09:00:00+08:00"


def stop_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> str:
    captured = capsys.readouterr()
    lines = captured.out.strip().splitlines()
    assert len(lines) == 1
    assert str(tmp_path) not in captured.out + captured.err
    code: str = json.loads(lines[0])["stopped"]
    return code


def outcome(field: str, result: str = '"result": "correct"') -> str:
    return (
        f'{{"pack_id": "pack_one", "product_id": "alpha", "field_key": "{field}", '
        f'"golden_state": "present", "predicted_state": "present", {result}}}'
    )


def report_text(outcomes: list[str]) -> str:
    return '{"report": {"outcomes": [' + ", ".join(outcomes) + "]}}"


TEN = [outcome(f"f{index}") for index in range(10)]
FLIPPED = outcome("f9", '"result": "wrong_value", "result": "correct"')
SCORES = {f"alpha/f{index}": 0.9 for index in range(10)}


def calibrate(tmp_path: Path, report: str, scores: str | None = None) -> tuple[int, Path]:
    (tmp_path / "report.json").write_text(report, encoding="utf-8")
    directory = tmp_path / "scores" / "alpha"
    directory.mkdir(parents=True)
    if scores is None:
        document = {"reviewer": "model:x", "reviewed_at": REVIEWED_AT, "scores": SCORES}
        scores = json.dumps(document)
    (directory / "scores.json").write_text(scores, encoding="utf-8")
    out = tmp_path / "out"
    argv = ["--report", str(tmp_path / "report.json"), "--scores", str(directory.parent)]
    return review_calibration.main([*argv, "--out", str(out)]), out


def test_the_hand_written_report_is_valid_without_duplicates(tmp_path: Path) -> None:
    code, out = calibrate(tmp_path, report_text(TEN))
    assert code == 0
    data = json.loads((out / "calibration.json").read_text(encoding="utf-8"))
    assert data["packs"]["pack_one"]["selected"]["threshold"] == 0.9


@pytest.mark.parametrize(
    "report",
    [
        # One of ten claims at 0.9 is wrong; last-one-wins would report 10/10 and select 0.9.
        report_text([*TEN[:9], FLIPPED]),
        # A second outcomes array would hide the first one's unmapped label.
        '{"report": {"outcomes": [' + outcome("f0", '"result": "bogus"') + "], "
        '"outcomes": [' + ", ".join(TEN) + "]}}",
        report_text(TEN)[:-1] + ', "report": {"outcomes": []}}',
        report_text([outcome("f0", '"result": "correct", "pack_id": "pack_two"'), *TEN[1:]]),
    ],
    ids=["result", "outcomes", "report", "pack_id"],
)
def test_a_duplicate_member_in_the_report_stops(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], report: str
) -> None:
    code, out = calibrate(tmp_path, report)
    assert code == 2
    assert stop_code(tmp_path, capsys) == "REPORT_UNREADABLE"
    assert not out.exists()


PAIRS = ", ".join(f'"{key}": {value}' for key, value in SCORES.items())


@pytest.mark.parametrize(
    "scores",
    [
        f'{{"reviewer": "model:x", "reviewed_at": "{REVIEWED_AT}", '
        f'"scores": {{{PAIRS}, "alpha/f0": 0.1}}}}',
        f'{{"reviewer": "model:x", "reviewer": "model:y", "reviewed_at": "{REVIEWED_AT}", '
        f'"scores": {{{PAIRS}}}}}',
    ],
    ids=["score_key", "reviewer"],
)
def test_a_duplicate_member_in_a_scores_file_stops(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], scores: str
) -> None:
    code, out = calibrate(tmp_path, report_text(TEN), scores)
    assert code == 2
    assert stop_code(tmp_path, capsys) == "SCORES_UNREADABLE"
    assert not out.exists()


def convert(tmp_path: Path, path: str, old: str, new: str) -> int:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    target = repo / GOLDEN / path
    text = target.read_text(encoding="utf-8")
    assert text.count(old) == 1
    target.write_text(text.replace(old, new), encoding="utf-8")
    out = tmp_path / "golden.jsonl"
    code = golden_items.main(
        ["--repo", str(repo), "--products", "alpha", "beta", "--out", str(out)]
    )
    assert not out.exists()
    return code


def test_a_product_named_twice_in_the_manifest_stops(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = '"alpha": {"pack_id": "pack_one", "model_id": "judge-one", "product_id": "alpha"},'
    second = '"alpha": {"pack_id": "pack_two", "model_id": "judge-two", "product_id": "alpha"},'
    assert convert(tmp_path, "manifest.json", first, f"{first}\n  {second}") == 2
    assert stop_code(tmp_path, capsys) == "MANIFEST_UNREADABLE"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('"value": "合成取值丙",', '"value": "合成取值丙", "value": "合成取值戊",'),
        ('"state": "absent_explicitly",', '"state": "absent_explicitly", "state": "unknown",'),
        ('"page": 2,', '"page": 2, "page": 3,'),  # nested inside an evidence entry
        (
            '"cards_version": "synthetic-1",',
            '"cards_version": "x", "cards_version": "synthetic-1",',
        ),
    ],
    ids=["value", "state", "evidence_page", "top_level"],
)
def test_a_duplicate_member_in_a_golden_file_stops(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], old: str, new: str
) -> None:
    assert convert(tmp_path, "alpha.json", old, new) == 2
    assert stop_code(tmp_path, capsys) == "GOLDEN_INVALID"
