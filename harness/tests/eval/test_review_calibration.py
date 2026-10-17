"""Judge labels meet review scores; per pack, the lowest threshold with 95% precision (RV2b §3.2).

Reports are built with the real evaluator models so their shape matches `semantic_run score`;
scores files follow RV1's format, one per product. All values are synthetic and must never reach
the outputs or the stop line.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.catalog.review_policy import ReviewPolicy
from insurance_harness.eval.evaluator import ItemOutcome, report_from_outcomes
from insurance_harness.eval.golden import GoldenItem, Prediction
from insurance_harness.eval.review_calibration import main, wilson_lower_bound
from insurance_harness.eval.semantic import Ruling, SemanticVerdict, evaluate_semantic

MATERIAL = "合成取值"
REVIEWED_AT = "2026-10-17T09:00:00+08:00"
OUTPUTS = ("calibration.json", "calibration.md", "thresholds.json")
# The Golden state each final result implies when the prediction is present or explicit.
GOLDEN_STATE = {
    "hallucination": "unknown",
    "misfiled": "unknown",
    "state_mismatch": "unknown",
    "contradiction": "absent_explicitly",
    "correct_non_present": "absent_explicitly",
}


def outcome(
    product: str,
    field: str,
    result: str,
    *,
    pack: str = "pack_one",
    predicted: str | None = "present",
    golden: str | None = None,
) -> ItemOutcome:
    golden = golden or GOLDEN_STATE.get(result, "present")
    return ItemOutcome.model_validate(
        {
            "pack_id": pack,
            "product_id": product,
            "field_key": field,
            "golden_state": golden,
            "predicted_state": predicted,
            "golden_value": MATERIAL if golden == "present" else None,
            "predicted_value": MATERIAL if predicted == "present" else None,
            "result": result,
        }
    )


def block(
    product: str, pack: str, *runs: tuple[float, str, int]
) -> tuple[list[ItemOutcome], dict[str, float]]:
    """`count` outcomes per (score, result, count), keyed f000, f001, ... with their scores."""
    outcomes, scores = [], {}
    rows = [(score, result) for score, result, count in runs for _ in range(count)]
    for index, (score, result) in enumerate(rows):
        field = f"f{index:03d}"
        outcomes.append(outcome(product, field, result, pack=pack))
        scores[f"{product}/{field}"] = score
    return outcomes, scores


def write_report(path: Path, outcomes: list[ItemOutcome]) -> Path:
    data = {"report": report_from_outcomes(outcomes).model_dump(), "provenance": {"judge": "x"}}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_scores(root: Path, scores: dict[str, float], products: tuple[str, ...] = ()) -> Path:
    grouped: dict[str, dict[str, float]] = {product: {} for product in products}
    for key, value in scores.items():
        grouped.setdefault(key.split("/", 1)[0], {})[key] = value
    for product, rows in grouped.items():
        directory = root / product
        directory.mkdir(parents=True)
        document = {"reviewer": "model:synthetic", "reviewed_at": REVIEWED_AT, "scores": rows}
        (directory / "scores.json").write_text(json.dumps(document), encoding="utf-8")
    return root


def calibrate(report: Path, scores: Path, out: Path, *extra: str) -> int:
    return main(["--report", str(report), "--scores", str(scores), "--out", str(out), *extra])


def run(
    tmp_path: Path,
    outcomes: list[ItemOutcome],
    scores: dict[str, float],
    *extra: str,
    products: tuple[str, ...] = (),
) -> tuple[int, Path]:
    report = write_report(tmp_path / "report.json", outcomes)
    root = write_scores(tmp_path / "scores", scores, products)
    out = tmp_path / "out"
    return calibrate(report, root, out, *extra), out


def load(out: Path, name: str = "calibration.json") -> dict[str, Any]:
    data: dict[str, Any] = json.loads((out / name).read_text(encoding="utf-8"))
    return data


def stop_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> str:
    captured = capsys.readouterr()
    lines = captured.out.strip().splitlines()
    assert len(lines) == 1
    for secret in (str(tmp_path), MATERIAL):
        assert secret not in captured.out + captured.err
    code: str = json.loads(lines[0])["stopped"]
    return code


A, AB, C = f"{MATERIAL}甲", f"{MATERIAL}甲乙", f"{MATERIAL}丙"
Case = tuple[str, str | None, str | None, str | None, tuple[str, str] | None]
# field: Golden state and value, predicted state and value, expected (result, label) if reviewed.
CASES: dict[str, Case] = {
    "f_correct": ("present", A, "present", A, ("correct", "correct")),
    "f_incomplete": ("present", AB, "present", A, ("incomplete", "correct")),
    "f_non_present": (
        "absent_explicitly",
        None,
        "absent_explicitly",
        None,
        ("correct_non_present", "correct"),
    ),
    "f_wrong": ("present", A, "present", C, ("wrong_value", "wrong")),
    "f_hallucination": ("unknown", None, "present", A, ("hallucination", "wrong")),
    "f_misfiled": ("unknown", None, "present", A, ("misfiled", "wrong")),
    "f_contradiction": ("absent_explicitly", None, "present", A, ("contradiction", "wrong")),
    "f_state": ("unknown", None, "absent_explicitly", None, ("state_mismatch", "wrong")),
    "f_missed": ("present", A, "unknown", None, None),
    "f_both_unknown": ("unknown", None, "unknown", None, None),
    "f_not_predicted": ("absent_explicitly", None, None, None, None),
}


def test_labels_follow_the_spec_mapping_on_a_real_semantic_report(tmp_path: Path) -> None:
    quote = {"document": "d.pdf", "document_sha256": "c" * 64, "page": 1, "quote": "合成引文"}
    ids = {"pack_id": "pack_one", "product_id": "alpha"}
    golden = [
        GoldenItem.model_validate(
            {**ids, "field_key": field, "state": state, "value": value, "judged_by": "model:x"}
            | {"evidence": [quote] if state != "unknown" else []}
        )
        for field, (state, value, _, _, _) in CASES.items()
    ]
    predicted = [
        Prediction.model_validate({**ids, "field_key": field, "state": state, "value": value})
        for field, (_, _, state, value, _) in CASES.items()
        if state is not None
    ]
    verdicts = [
        SemanticVerdict.model_validate(
            {"product_id": "alpha", "field_key": field, "verdict": verdict, "reason": "合成"}
        )
        for field, verdict in (("f_incomplete", "insufficient"), ("f_wrong", "contradicted"))
    ]
    ruling = Ruling(
        product_id="alpha",
        field_key="f_misfiled",
        from_result="hallucination",
        to_result="misfiled",
        reason="放错字段",
        by="human:x",
        on="2026-10-17",
    )
    report = evaluate_semantic(golden, predicted, verdicts, [ruling])
    expected = {field: case[4] for field, case in CASES.items() if case[4] is not None}
    code, out = run(tmp_path, report.outcomes, {f"alpha/{field}": 0.5 for field in expected})
    assert code == 0
    claims = {row["field_key"]: row for row in load(out)["claims"]}
    # Unknown and missing predictions are not reviewed claims.
    assert {field: (row["result"], row["label"]) for field, row in claims.items()} == expected
    assert claims["f_state"] == {
        "pack_id": "pack_one",
        "product_id": "alpha",
        "field_key": "f_state",
        "state": "absent_explicitly",
        "score": 0.5,
        "label": "wrong",
        "result": "state_mismatch",
    }


def test_unknown_predictions_take_no_part_and_need_no_score(tmp_path: Path) -> None:
    outcomes = [
        outcome("alpha", "f_present", "correct"),
        outcome("alpha", "f_missed", "missed", predicted="unknown"),
        outcome("alpha", "f_quiet", "correct_non_present", predicted="unknown", golden="unknown"),
        outcome("alpha", "f_none", "missing", predicted=None, golden="unknown"),
        outcome("beta", "f_missed", "missed", pack="pack_two", predicted="unknown"),
    ]
    # Scores for an unknown claim and for a field the report lacks are ignored and counted.
    scores = {"alpha/f_present": 0.9, "alpha/f_missed": 0.2, "alpha/f_elsewhere": 0.7}
    code, out = run(tmp_path, outcomes, scores, products=("beta",))
    assert code == 0
    data = load(out)
    assert [row["field_key"] for row in data["claims"]] == ["f_present"]
    assert data["unused_scores"] == 2
    assert data["packs"]["pack_one"]["claims"] == 1
    assert data["packs"]["pack_two"]["claims"] == 0
    assert data["all"]["claims"] == 1


@pytest.mark.parametrize("result", ["golden_defect", "mismatch", "unscored", "bogus"])
def test_an_unmapped_result_on_a_reviewed_claim_stops(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], result: str
) -> None:
    outcomes = [outcome("alpha", "f_ok", "correct"), outcome("alpha", "f_odd", "correct")]
    report = write_report(tmp_path / "report.json", outcomes)
    data = json.loads(report.read_text(encoding="utf-8"))
    data["report"]["outcomes"][1]["result"] = result
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    root = write_scores(tmp_path / "scores", {"alpha/f_ok": 0.9, "alpha/f_odd": 0.9})
    out = tmp_path / "out"
    assert calibrate(report, root, out) == 2
    assert stop_code(tmp_path, capsys) == "LABEL_UNKNOWN"
    assert not out.exists()


def test_a_reviewed_claim_without_a_score_stops(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outcomes = [outcome("alpha", "f_scored", "correct"), outcome("alpha", "f_bare", "wrong_value")]
    code, out = run(tmp_path, outcomes, {"alpha/f_scored": 0.9})
    assert code == 2
    assert stop_code(tmp_path, capsys) == "SCORE_MISSING"
    assert not out.exists()


ONE = ((0.9, "correct", 12), (0.8, "wrong_value", 1), (0.6, "incomplete", 10))


def three_packs() -> tuple[list[ItemOutcome], dict[str, float]]:
    one = block("alpha", "pack_one", *ONE, (0.3, "hallucination", 1))
    two = block("beta", "pack_two", (0.95, "correct", 5))
    three = block(
        "gamma",
        "pack_three",
        (0.99, "correct", 5),
        (0.9, "contradiction", 1),
        (0.4, "correct", 10),
        (0.3, "wrong_value", 2),
    )
    return one[0] + two[0] + three[0], {**one[1], **two[1], **three[1]}


def candidate(threshold: float, n: int, correct: int) -> dict[str, Any]:
    return {
        "threshold": threshold,
        "n": n,
        "correct": correct,
        "precision": pytest.approx(correct / n, abs=1e-12),
        "wilson_lower": pytest.approx(wilson_lower_bound(correct, n), abs=1e-12),
    }


def decision(group: dict[str, Any]) -> tuple[str, str | None, float | None]:
    selected = group["selected"]
    return group["status"], group["reason"], selected["threshold"] if selected else None


def test_thresholds_pick_the_lowest_passing_score_or_say_why_not(tmp_path: Path) -> None:
    outcomes, scores = three_packs()
    code, out = run(tmp_path, outcomes, scores)
    assert code == 0
    data = load(out)
    one = data["packs"]["pack_one"]
    # Precision dips below 95% at 0.8 and recovers at 0.6: the lowest passing score wins.
    assert one["candidates"] == [
        candidate(0.9, 12, 12),
        candidate(0.8, 13, 12),
        candidate(0.6, 23, 22),
        candidate(0.3, 24, 22),
    ]
    assert (one["claims"], one["correct"], decision(one)) == (24, 22, ("selected", None, 0.6))
    assert one["selected"] == candidate(0.6, 23, 22)
    assert one["selected"]["wilson_lower"] == pytest.approx(0.7900841350594088, abs=1e-9)

    two = data["packs"]["pack_two"]  # five claims, all correct: too few to set a threshold
    assert decision(two) == ("insufficient", "insufficient_support", None)
    assert two["candidates"] == [candidate(0.95, 5, 5)]

    # Enough claims, but no threshold with at least ten of them reaches 95%.
    three = data["packs"]["pack_three"]
    assert decision(three) == ("insufficient", "precision_not_reached", None)
    assert [row["threshold"] for row in three["candidates"]] == [0.99, 0.9, 0.4, 0.3]

    pooled = data["all"]
    assert pooled["candidates"] == [
        candidate(0.99, 5, 5),
        candidate(0.95, 10, 10),
        candidate(0.9, 23, 22),
        candidate(0.8, 24, 22),
        candidate(0.6, 34, 32),
        candidate(0.4, 44, 42),
        candidate(0.3, 47, 42),
    ]
    assert decision(pooled) == ("selected", None, 0.4)
    assert pooled["selected"] == candidate(0.4, 44, 42)
    assert list(data["packs"]) == ["pack_one", "pack_three", "pack_two"]


def test_precision_and_support_options_move_the_threshold(tmp_path: Path) -> None:
    outcomes, scores = block("alpha", "pack_one", *ONE, (0.3, "wrong_value", 1))
    cases = [
        ((), ("selected", None, 0.6)),
        (("--precision", "0.99"), ("selected", None, 0.9)),
        (("--min-support", "13"), ("selected", None, 0.6)),
        (("--min-support", "24"), ("insufficient", "precision_not_reached", None)),
        (("--min-support", "25"), ("insufficient", "insufficient_support", None)),
    ]
    for index, (extra, expected) in enumerate(cases):
        root = tmp_path / str(index)
        root.mkdir()
        code, out = run(root, outcomes, scores, *extra)
        assert code == 0
        assert decision(load(out)["packs"]["pack_one"]) == expected


def test_precision_exactly_at_the_target_passes(tmp_path: Path) -> None:
    outcomes, scores = block("alpha", "pack_one", (0.7, "correct", 19), (0.5, "wrong_value", 1))
    code, out = run(tmp_path, outcomes, scores)
    assert code == 0
    assert load(out)["packs"]["pack_one"]["selected"] == candidate(0.5, 20, 19)


@pytest.mark.parametrize(
    ("successes", "trials", "expected"),
    [
        (10, 10, 0.7224598312333834),
        (19, 20, 0.7638641064874331),
        (95, 100, 0.8882480347279117),  # the textbook Wilson 95% interval is [0.888, 0.978]
        (1, 2, 0.09452865480086611),
        (0, 5, 0.0),
    ],
)
def test_wilson_lower_bound_uses_z_196(successes: int, trials: int, expected: float) -> None:
    value = wilson_lower_bound(successes, trials)
    assert value == pytest.approx(expected, abs=1e-12)
    assert 0.0 <= value <= 1.0


def test_outputs_carry_their_sources_and_no_material(tmp_path: Path) -> None:
    outcomes, scores = three_packs()
    code, out = run(tmp_path, outcomes, scores)
    assert code == 0
    assert sorted(path.name for path in out.iterdir()) == sorted(OUTPUTS)

    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    sources = {
        "report_sha256": sha(tmp_path / "report.json"),
        "scores_sha256": {
            product: sha(tmp_path / "scores" / product / "scores.json")
            for product in ("alpha", "beta", "gamma")
        },
    }
    parameters = {"precision": 0.95, "min_support": 10, "z": 1.96}
    thresholds = load(out, "thresholds.json")
    assert thresholds == {
        "thresholds": {"pack_one": {"default": 0.6}},
        "parameters": parameters,
        "sources": sources,
    }
    # RV3 copies the thresholds into the review policy as they are.
    policy = ReviewPolicy(version="calibrated", thresholds=thresholds["thresholds"])
    assert policy.threshold("pack_one", "any_field") == 0.6
    data = load(out)
    assert [data[key] for key in ("parameters", "sources", "unused_scores")] == [
        parameters,
        sources,
        0,
    ]
    keys = [(row["pack_id"], row["product_id"], row["field_key"]) for row in data["claims"]]
    assert keys == sorted(keys)
    assert len(keys) == 47
    summary = (out / "calibration.md").read_text(encoding="utf-8")
    for pack in ("pack_one", "pack_two", "pack_three"):
        assert pack in summary
    assert "不足" in summary
    for name in OUTPUTS:
        text = (out / name).read_text(encoding="utf-8")
        assert MATERIAL not in text
        assert str(tmp_path) not in text


def test_outputs_are_byte_identical_for_the_same_inputs(tmp_path: Path) -> None:
    outcomes, scores = three_packs()
    report = write_report(tmp_path / "report.json", list(reversed(outcomes)))
    root = write_scores(tmp_path / "scores", scores)
    assert calibrate(report, root, tmp_path / "first") == 0
    assert calibrate(report, root, tmp_path / "second") == 0
    for name in OUTPUTS:
        assert (tmp_path / "first" / name).read_bytes() == (tmp_path / "second" / name).read_bytes()
    keys = [
        (row["pack_id"], row["product_id"], row["field_key"])
        for row in load(tmp_path / "first")["claims"]
    ]
    assert keys == sorted(keys)


@pytest.mark.parametrize(
    ("score_products", "note"),
    [
        (("alpha",), "a reported product has no scores"),
        (("alpha", "beta", "gamma"), "scores name a product the report lacks"),
    ],
)
def test_report_and_scores_must_cover_the_same_products(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], score_products: tuple[str, ...], note: str
) -> None:
    outcomes = [outcome("alpha", "f1", "correct"), outcome("beta", "f1", "wrong_value")]
    scores = {f"{product}/f1": 0.9 for product in score_products}
    code, out = run(tmp_path, outcomes, scores)
    assert code == 2, note
    assert stop_code(tmp_path, capsys) == "PRODUCT_MISMATCH"
    assert not out.exists()


GOOD_SCORES = {"reviewer": "model:x", "reviewed_at": REVIEWED_AT, "scores": {"alpha/f1": 0.5}}


@pytest.mark.parametrize(
    "change",
    [
        {"scores": {"alpha/f1": 1.5}},
        {"scores": {"alpha/f1": True}},  # a JSON boolean is not a score
        {"reviewed_at": "2026-10-17"},  # RV1: a date-time with its offset
        {"reviewer": None},
        None,
    ],
)
def test_a_malformed_scores_file_stops(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], change: dict[str, Any] | None
) -> None:
    report = write_report(tmp_path / "report.json", [outcome("alpha", "f1", "correct")])
    (tmp_path / "scores" / "alpha").mkdir(parents=True)
    document = "not json" if change is None else json.dumps({**GOOD_SCORES, **change})
    (tmp_path / "scores" / "alpha" / "scores.json").write_text(document, encoding="utf-8")
    assert calibrate(report, tmp_path / "scores", tmp_path / "out") == 2
    assert stop_code(tmp_path, capsys) == "SCORES_UNREADABLE"
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("text", ["not json", "[]", json.dumps({"report": {}})])
def test_an_unreadable_report_stops(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    (tmp_path / "report.json").write_text(text, encoding="utf-8")
    root = write_scores(tmp_path / "scores", {"alpha/f1": 0.5})
    assert calibrate(tmp_path / "report.json", root, tmp_path / "out") == 2
    assert stop_code(tmp_path, capsys) == "REPORT_UNREADABLE"


@pytest.mark.parametrize(
    "extra",
    [("--precision", "0"), ("--precision", "1.2"), ("--precision", "nan"), ("--min-support", "0")],
)
def test_bad_options_stop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: tuple[str, ...]
) -> None:
    code, out = run(tmp_path, [outcome("alpha", "f1", "correct")], {"alpha/f1": 0.5}, *extra)
    assert code == 2
    assert stop_code(tmp_path, capsys) == "INVALID_ARGUMENTS"
    assert not out.exists()


def test_existing_outputs_are_never_replaced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "thresholds.json").write_text("earlier", encoding="utf-8")
    code, _ = run(tmp_path, [outcome("alpha", "f1", "correct")], {"alpha/f1": 0.5})
    assert code == 2
    assert stop_code(tmp_path, capsys) == "OUTPUT_EXISTS"
    assert (out / "thresholds.json").read_text(encoding="utf-8") == "earlier"
    assert sorted(path.name for path in out.iterdir()) == ["thresholds.json"]
