"""Additional scoring cases across unrelated packs and product identities."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from insurance_harness.eval.compare import compare_value
from insurance_harness.eval.evaluator import evaluate, gate
from insurance_harness.eval.golden import GoldenEvidence, GoldenItem, Prediction, ValueComponent
from insurance_harness.eval.normalize import normalize_text, values_equal


def evidence() -> GoldenEvidence:
    return GoldenEvidence(document="terms.pdf", document_sha256="a" * 64, page=2, quote="原文")


def item(field: str = "term", /, **changes: Any) -> GoldenItem:
    data: dict[str, Any] = {
        "pack_id": "health", "product_id": "alpha", "field_key": field,
        "state": "present", "value": "90日", "evidence": [evidence()],
        "judged_by": "human:reviewer",
    }
    data.update(changes)
    return GoldenItem.model_validate(data)


def prediction(golden: GoldenItem, **changes: Any) -> Prediction:
    data = golden.model_dump(include={"pack_id", "product_id", "field_key", "state", "value"})
    data.update(changes)
    return Prediction.model_validate(data)


@pytest.mark.parametrize("change", [
    {"value": None}, {"value": " \t"}, {"evidence": []}, {"pack_id": " "},
    {"product_id": ""}, {"field_key": ""}, {"state": "other"},
    {"judged_by": "someone"}, {"judged_by": "human: "},
    {"state": "unknown", "value": None},
    {"state": "unknown", "value": "90日", "evidence": []},
    {"state": "absent_explicitly", "value": "不存在"},
    {"state": "absent_explicitly", "value": None, "evidence": []},
    {"forbidden": [" "]},
])
def test_golden_rejects_invalid_input(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        item(**change)


@pytest.mark.parametrize("change", [
    {"document": " "}, {"document_sha256": "g" * 64}, {"document_sha256": "a" * 63},
    {"page": 0}, {"page": 1.5}, {"quote": " \n"},
])
def test_evidence_rejects_invalid_input(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GoldenEvidence.model_validate(evidence().model_dump() | change)


@pytest.mark.parametrize("accepted", [(), ("",), (" \t",), ("90日", " ")])
def test_components_cannot_match_vacuously(accepted: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        ValueComponent(name="duration", accepted=accepted)


@pytest.mark.parametrize("change", [
    {"state": "present", "value": None}, {"state": "present", "value": " "},
    {"state": "unknown", "value": "有"}, {"state": "absent_explicitly", "value": "无"},
    {"state": "other", "value": None},
])
def test_prediction_validates_state_and_value(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        prediction(item(), **change)


@pytest.mark.parametrize(("left", "right"), [
    ("３０ 万元", "300,000人民币"), ("85%", "0.85"),
    ("2026年10月2日", "2026-10-02"), ("２０２６／１０／２", "2026-10-02"),
    ("【A】，“B”。", '[a],"b".'), ("支持", "true"), (None, None),
])
def test_value_equivalence(left: str | None, right: str | None) -> None:
    assert values_equal(left, right)
    if left is not None and right is not None:
        assert compare_value(item(value=left), right).correct


def test_distinct_values_do_not_collapse() -> None:
    assert not values_equal(None, "")
    assert not values_equal("2026-02-30", "2026-03-02")
    assert not values_equal("9007199254740992", "9007199254740993")
    assert not values_equal("30万", "30元")
    assert normalize_text("  Ａ（乙），丙。 ") == "a(乙),丙."


def test_component_comparison_records_missing_atoms_and_forbidden_terms() -> None:
    golden = item(components=[
        ValueComponent(name="duration", accepted=("90日", "90天")),
        ValueComponent(name="exception", accepted=("意外除外", "意外伤害除外")),
    ], forbidden=("等情形",))
    assert compare_value(golden, "等待期９０天；意外伤害除外").correct
    missing = compare_value(golden, "等待期90日")
    assert not missing.correct
    assert missing.component_misses == ["exception"]
    forbidden = compare_value(golden, "90天，意外除外等情形")
    assert not forbidden.correct
    assert forbidden.forbidden_hits == ["等情形"]
    assert compare_value(golden, None).component_misses == ["duration", "exception"]


def test_scoring_matrix_preserves_all_identity_dimensions() -> None:
    good = item()
    bad = item(product_id="beta", value="1年")
    missed = item("missing")
    non_present = item("state", pack_id="life", product_id="beta")
    unknown = item("unknown", state="unknown", value=None, evidence=[])
    absent = item("absent", state="absent_explicitly", value=None)
    same_unknown = item("same_unknown", state="unknown", value=None, evidence=[])
    same_absent = item("same_absent", state="absent_explicitly", value=None)
    wrong_state = item("wrong_state", state="unknown", value=None, evidence=[])
    missing_unknown = item("missing_unknown", state="unknown", value=None, evidence=[])
    other_pack = item(pack_id="life", value="20年")
    goldens = [good, bad, missed, non_present, unknown, absent, same_unknown,
               same_absent, wrong_state, missing_unknown, other_pack]
    predictions = [prediction(good), prediction(bad, value="2年"),
                   prediction(non_present, state="unknown", value=None),
                   prediction(unknown, state="present", value="有"),
                   prediction(absent, state="present", value="有"),
                   prediction(same_unknown), prediction(same_absent),
                   prediction(wrong_state, state="absent_explicitly"),
                   prediction(other_pack), prediction(good, field_key="outside")]
    report = evaluate(goldens, predictions)
    assert (report.micro.tp, report.micro.fp, report.micro.fn) == (2, 3, 3)
    assert report.micro.precision == 2 / 5
    assert report.micro.recall == 2 / 5
    assert (report.per_field["term"].tp, report.per_field["term"].fp) == (2, 1)
    assert report.hallucinations == 1
    assert report.contradictions == 1
    assert report.correct_non_present == 2
    assert report.missing_predictions == 2
    assert report.unscored_predictions == 1
    assert len(report.outcomes) == 12
    state_outcome = next(o for o in report.outcomes if o.field_key == "wrong_state")
    assert state_outcome.result == "state_mismatch"
    assert json.loads(report.model_dump_json())["micro"]["tp"] == 2


def test_duplicate_input_is_rejected_instead_of_overwriting() -> None:
    golden = item()
    pred = prediction(golden)
    with pytest.raises(ValueError, match="duplicate.*golden"):
        evaluate([golden, golden], [pred])
    with pytest.raises(ValueError, match="duplicate.*prediction"):
        evaluate([golden], [pred, pred])
    with pytest.raises(ValueError, match="duplicate.*prediction"):
        evaluate([], [pred, pred])


def test_component_misses_for_shared_product_and_field_remain_auditable() -> None:
    a = item(components=[ValueComponent(name="duration", accepted=("90日",))])
    b = item(pack_id="life", components=[ValueComponent(name="unit", accepted=("年",))])
    report = evaluate([a, b], [prediction(a, value="无"), prediction(b, value="无")])
    assert report.component_misses == {"alpha/term": ["duration", "unit"]}
    assert {o.pack_id: o.component_misses for o in report.outcomes} == {
        "health": ["duration"], "life": ["unit"],
    }


def test_gate_uses_only_the_requested_pack() -> None:
    healthy = item()
    hallucination = item(pack_id="life", state="unknown", value=None, evidence=[])
    report = evaluate([healthy, hallucination], [prediction(healthy),
                      prediction(hallucination, state="present", value="有")])
    assert gate(report, "health").passed
    assert "hallucination" in gate(report, "life").reasons
    assert not gate(report, "missing").passed
    assert set(gate(report, "missing").reasons) >= {
        "precision_undefined", "recall_undefined",
    }


def test_empty_denominators_and_nonpresent_matches_fail_closed() -> None:
    unknown = item(state="unknown", value=None, evidence=[])
    report = evaluate([unknown], [prediction(unknown)])
    assert report.micro.precision is None
    assert report.micro.recall is None
    assert not gate(report, "health").passed
    empty = evaluate([], [])
    assert empty.micro.precision is None
    assert not gate(empty, "health").passed


def test_threshold_defaults_and_exact_boundaries() -> None:
    goldens = [item(str(i)) for i in range(20)]
    preds = [prediction(g) for g in goldens[:18]]
    report = evaluate(goldens, preds)
    assert gate(report, "health").passed  # precision 1, recall exactly 0.90
    assert "recall_below" in gate(report, "health", min_recall=0.91).reasons
    mismatched = evaluate(goldens, [prediction(g) for g in goldens[:19]] +
                          [prediction(goldens[19], value="91日")])
    assert gate(mismatched, "health").passed  # precision exactly 0.95
    assert "precision_below" in gate(mismatched, "health", min_precision=0.96).reasons


@pytest.mark.parametrize("threshold", [-0.01, 1.01, float("nan"), float("inf")])
def test_invalid_thresholds_are_rejected(threshold: float) -> None:
    report = evaluate([item()], [prediction(item())])
    with pytest.raises(ValueError, match="threshold"):
        gate(report, "health", min_precision=threshold)
    with pytest.raises(ValueError, match="threshold"):
        gate(report, "health", min_recall=threshold)


def test_missing_present_prediction_records_all_missing_components() -> None:
    golden = item(components=[ValueComponent(name="duration", accepted=("90日",))])
    report = evaluate([golden], [])
    assert report.component_misses == {"alpha/term": ["duration"]}
    assert report.outcomes[0].component_misses == ["duration"]
    non_present = evaluate([golden], [prediction(golden, state="unknown", value=None)])
    assert non_present.component_misses == {"alpha/term": ["duration"]}


def test_forbidden_term_vetoes_exact_value_equality() -> None:
    golden = item(value="90日等情形", forbidden=("等情形",))
    report = evaluate([golden], [prediction(golden)])
    assert (report.micro.tp, report.micro.fp, report.micro.fn) == (0, 1, 1)
    assert report.outcomes[0].forbidden_hits == ["等情形"]


@pytest.mark.parametrize(("left", "right", "equal"), [
    ("1.0000000000000000000000000001万", "1万", False),
    ("1.0000000000000000000000000001%", "0.01", False),
    ("1.0000000000000000000000000001万", "10000.000000000000000000000001", True),
    ("1.0000000000000000000000000001%", "0.010000000000000000000000000001", True),
])
def test_numeric_scaling_preserves_all_decimal_digits(
    left: str, right: str, equal: bool,
) -> None:
    assert values_equal(left, right) is equal


@pytest.mark.parametrize(("left", "right"), [
    ("1、2", "12"), ("1,2", "12"), ("1元2元", "12"),
    ("1、234", "1234"), ("1、234", "1,234"),
    ("1,23,456", "123456"), ("人民币1人民币2", "12"),
])
def test_malformed_amounts_and_enumerations_are_not_numbers(left: str, right: str) -> None:
    assert not values_equal(left, right)
    golden = item(value=left)
    report = evaluate([golden], [prediction(golden, value=right)])
    assert (report.micro.tp, report.micro.fp, report.micro.fn) == (0, 1, 1)
    assert not gate(report, "health").passed


@pytest.mark.parametrize(("left", "right"), [
    ("人民币1,234.50元", "1234.5"), ("1,234.50", "1234.5"),
    ("１，２３４，５６７元", "1234567"), ("人民币30万元", "300000"),
])
def test_valid_currency_placement_and_grouping_are_equivalent(left: str, right: str) -> None:
    assert values_equal(left, right)
