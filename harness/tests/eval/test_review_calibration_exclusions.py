"""RV2b acceptance correction: missed on an explicit-absence claim is wrong; a defective Golden
or a field outside Golden is excluded and counted, never guessed (Spec §3.2).

Protected file: written by Claude. Found while implementing: the evaluator reports `missed` when
the compiler says absent_explicitly and Golden says present, so a reviewed claim can carry it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from insurance_harness.eval.evaluator import ItemOutcome, report_from_outcomes
from insurance_harness.eval.review_calibration import main


def outcome(field: str, result: str, predicted: str, golden: str) -> ItemOutcome:
    return ItemOutcome.model_validate(
        {
            "pack_id": "pack_one",
            "product_id": "alpha",
            "field_key": field,
            "golden_state": golden,
            "predicted_state": predicted,
            "golden_value": "v" if golden == "present" else None,
            "predicted_value": "v" if predicted == "present" else None,
            "result": result,
        }
    )


def calibrate(
    tmp_path: Path, outcomes: list[ItemOutcome], scores: dict[str, float]
) -> dict[str, Any]:
    report = tmp_path / "report.json"
    data = {"report": report_from_outcomes(outcomes).model_dump(), "provenance": {"judge": "x"}}
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    directory = tmp_path / "scores" / "alpha"
    directory.mkdir(parents=True)
    document = {"reviewer": "r", "reviewed_at": "2026-10-17T09:00:00+08:00", "scores": scores}
    (directory / "scores.json").write_text(json.dumps(document), encoding="utf-8")
    out = tmp_path / "out"
    assert (
        main(["--report", str(report), "--scores", str(tmp_path / "scores"), "--out", str(out)])
        == 0
    )
    result: dict[str, Any] = json.loads((out / "calibration.json").read_text(encoding="utf-8"))
    return result


def test_missed_on_an_explicit_absence_claim_is_wrong(tmp_path: Path) -> None:
    data = calibrate(
        tmp_path,
        [
            outcome("f_ok", "correct", "present", "present"),
            outcome("f_missed", "missed", "absent_explicitly", "present"),
        ],
        {"alpha/f_ok": 0.9, "alpha/f_missed": 0.8},
    )
    labels = {row["field_key"]: row["label"] for row in data["claims"]}
    assert labels == {"f_ok": "correct", "f_missed": "wrong"}


def test_a_defective_golden_or_a_field_outside_golden_is_excluded_and_counted(
    tmp_path: Path,
) -> None:
    data = calibrate(
        tmp_path,
        [
            outcome("f_ok", "correct", "present", "present"),
            outcome("f_defect", "golden_defect", "present", "present"),
            outcome("f_outside", "unscored", "present", "unknown"),
        ],
        {"alpha/f_ok": 0.9},
    )
    assert [row["field_key"] for row in data["claims"]] == ["f_ok"]
    assert data["excluded"] == {"golden_defect": 1, "unscored": 1}
    assert data["all"]["claims"] == 1
