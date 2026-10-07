"""Semantic scoring boundaries independent of the file exchange workflow."""

from collections.abc import Iterator
from typing import Literal

import pytest
from pydantic import ValidationError

from insurance_harness.eval import semantic
from insurance_harness.eval.evaluator import evaluate, gate
from insurance_harness.eval.golden import (
    GoldenEvidence,
    GoldenItem,
    Prediction,
    State,
    ValueComponent,
)


def gold(
    field: str = "waiting", *, pack: str = "medical", product: str = "one",
    state: State = "present", value: str = "等待期30日",
) -> GoldenItem:
    return GoldenItem(
        pack_id=pack, product_id=product, field_key=field, state=state,
        value=value if state == "present" else None, judged_by="human:test",
        evidence=[] if state == "unknown" else [GoldenEvidence(
            document="terms.pdf", document_sha256="a" * 64, page=1, quote=value,
        )],
    )


def pred(item: GoldenItem, *, state: State = "present", value: str = "生效后30日") -> Prediction:
    return Prediction(
        pack_id=item.pack_id, product_id=item.product_id, field_key=item.field_key,
        state=state, value=value if state == "present" else None,
    )


def verdict(
    item: GoldenItem,
    label: Literal["equivalent", "contradicted", "insufficient"] = "equivalent",
) -> semantic.SemanticVerdict:
    return semantic.SemanticVerdict(
        product_id=item.product_id, field_key=item.field_key, verdict=label, reason="核心事实判断",
    )


def ruling(item: GoldenItem, source: str, target: str) -> semantic.Ruling:
    return semantic.Ruling.model_validate({
        "product_id": item.product_id, "field_key": item.field_key,
        "from": source, "to": target, "reason": "terms.pdf 第1页：原文支持该判断",
        "by": "reviewer", "on": "2026-10-07",
    })


def once[T](items: list[T]) -> Iterator[T]:
    yield from items


def test_questions_use_value_equality_even_when_components_do_not_match() -> None:
    item = gold().model_copy(update={
        "components": [ValueComponent(name="改写要点", accepted=("三十天内",))],
    })
    prediction = pred(item, value="等待期 30日")
    assert evaluate([item], [prediction]).outcomes[0].result == "mismatch"
    assert semantic.semantic_questions(once([item]), once([prediction])) == {}
    report = semantic.evaluate_semantic(once([item]), once([prediction]), once([]))
    assert (report.outcomes[0].result, report.outcomes[0].basis) == ("correct", "L1")


@pytest.mark.parametrize("side", ["golden", "prediction"])
def test_duplicate_identities_are_rejected_with_field_key(side: str) -> None:
    item = gold()
    prediction = pred(item)
    goldens = [item, item] if side == "golden" else [item]
    predictions = [prediction, prediction] if side == "prediction" else [prediction]
    with pytest.raises(ValueError, match="waiting"):
        semantic.semantic_questions(once(goldens), once(predictions))
    with pytest.raises(ValueError, match="waiting"):
        semantic.evaluate_semantic(once(goldens), once(predictions), [verdict(item)])


@pytest.mark.parametrize("side", ["golden", "prediction", "across"])
def test_product_field_must_have_one_pack_across_both_inputs(side: str) -> None:
    item, other = gold(), gold(pack="life")
    goldens = [item, other] if side == "golden" else [item]
    predictions = [pred(item), pred(other)] if side == "prediction" else [pred(item)]
    if side == "across":
        predictions = [pred(other)]
    with pytest.raises(ValueError, match="waiting"):
        semantic.semantic_questions(goldens, predictions)
    with pytest.raises(ValueError, match="waiting"):
        semantic.evaluate_semantic(goldens, predictions, [verdict(item)])


def test_questions_are_sorted_per_product_and_ignore_non_present_pairs() -> None:
    items = [gold("zeta"), gold("alpha"), gold("absent", state="absent_explicitly"),
             gold("unknown", state="unknown"), gold("missed"), gold("same", product="two")]
    predictions = [pred(item) for item in items[:4]]
    predictions += [pred(items[4], state="unknown"), pred(items[5], value=items[5].value or "")]
    questions = semantic.semantic_questions(items, predictions)
    assert list(questions) == ["one"]
    assert [question.field_key for question in questions["one"]] == ["alpha", "zeta"]
    assert all(question.components == [] for question in questions["one"])


@pytest.mark.parametrize("problem", ["missing", "extra", "duplicate", "wrong_product"])
def test_every_l2_decision_is_bound_to_one_requested_field(problem: str) -> None:
    item = gold()
    decisions = [verdict(item)]
    if problem == "missing":
        decisions = []
    elif problem == "extra":
        decisions += [verdict(gold("extraneous"))]
    elif problem == "duplicate":
        decisions += [verdict(item, "contradicted")]
    else:
        decisions = [verdict(gold(product="two"))]
    with pytest.raises(ValueError, match="extraneous" if problem == "extra" else "waiting"):
        semantic.evaluate_semantic([item], [pred(item)], once(decisions))


@pytest.mark.parametrize("key", ["product_id", "field_key", "reason"])
def test_verdict_is_strict_and_rejects_blank_strings(key: str) -> None:
    payload = {"product_id": "one", "field_key": "waiting",
               "verdict": "equivalent", "reason": "支持"}
    for invalid in (" ", 123, b"bytes"):
        with pytest.raises(ValidationError):
            semantic.SemanticVerdict.model_validate({**payload, key: invalid})
    with pytest.raises(ValidationError):
        semantic.SemanticVerdict.model_validate({**payload, "extra": "value"})
    decision = semantic.SemanticVerdict.model_validate(payload)
    with pytest.raises(ValidationError):
        decision.reason = "changed"


@pytest.mark.parametrize("key", ["product_id", "field_key", "reason", "by", "on"])
def test_rulings_require_complete_attribution_and_reject_extra_keys(key: str) -> None:
    original = ruling(gold(), "wrong_value", "correct")
    payload = original.model_dump(by_alias=True)
    assert payload["from"] == "wrong_value" and payload["to"] == "correct"
    with pytest.raises(ValidationError):
        semantic.Ruling.model_validate({**payload, key: " "})
    with pytest.raises(ValidationError):
        semantic.Ruling.model_validate({**payload, "extra": "value"})
    with pytest.raises(ValidationError):
        original.reason = "changed"


def test_ruling_transition_table_is_exact() -> None:
    allowed = {
        "wrong_value": {"correct", "incomplete", "golden_defect"},
        "incomplete": {"golden_defect"},
        "correct": {"incomplete", "wrong_value"},
        "hallucination": {"misfiled", "golden_defect"},
    }
    for source, targets in allowed.items():
        for target in ("correct", "incomplete", "wrong_value", "misfiled", "golden_defect"):
            if target in targets:
                assert ruling(gold(), source, target).to_result == target
            else:
                with pytest.raises(ValidationError, match="waiting"):
                    ruling(gold(), source, target)


def test_rulings_cannot_chain_even_when_the_second_from_matches() -> None:
    item = gold()
    with pytest.raises(ValueError, match="waiting"):
        semantic.evaluate_semantic([item], [pred(item)], [verdict(item, "contradicted")], [
            ruling(item, "wrong_value", "incomplete"),
            ruling(item, "incomplete", "golden_defect"),
        ])


def test_l1_cannot_be_downgraded_and_missing_rulings_fail_with_the_field() -> None:
    item = gold()
    with pytest.raises(ValueError, match="waiting"):
        semantic.evaluate_semantic([item], [pred(item, value="等待期30日")], [], [
            ruling(item, "correct", "wrong_value"),
        ])
    with pytest.raises(ValueError, match="missing"):
        semantic.evaluate_semantic([item], [pred(item)], [verdict(item)], [
            ruling(gold("missing"), "correct", "incomplete"),
        ])
    with pytest.raises(ValueError, match="waiting"):
        semantic.evaluate_semantic([item], [pred(item)], [verdict(item)], [
            ruling(item, "wrong_value", "correct"),
        ])


def test_l3_rebuilds_all_metrics_and_does_not_mutate_inputs() -> None:
    items = [gold("equivalent"), gold("incomplete"), gold("wrong"),
             gold("misfiled", state="unknown"), gold("defect", state="unknown"),
             gold("other", pack="life", product="two")]
    predictions = [pred(item) for item in items]
    decisions = [verdict(items[0]), verdict(items[1], "insufficient"),
                 verdict(items[2], "contradicted"), verdict(items[5])]
    rulings = [ruling(items[0], "correct", "wrong_value"),
               ruling(items[1], "incomplete", "golden_defect"),
               ruling(items[2], "wrong_value", "correct"),
               ruling(items[3], "hallucination", "misfiled"),
               ruling(items[4], "hallucination", "golden_defect")]
    before = [model.model_dump() for model in [*items, *predictions, *decisions, *rulings]]
    report = semantic.evaluate_semantic(
        once(items), once(predictions), once(decisions), once(rulings),
    )
    assert [model.model_dump() for model in [*items, *predictions, *decisions, *rulings]] == before
    assert (report.micro.tp, report.micro.fp, report.micro.fn, report.micro.hallucinations) == (
        2, 2, 1, 0,
    )
    assert (report.per_pack["medical"].tp, report.per_pack["medical"].fp,
            report.per_pack["medical"].fn) == (1, 2, 1)
    assert report.per_pack["life"].precision == 1.0
    assert report.per_field["equivalent"].fn == 1
    assert report.per_field["defect"].precision is None
    assert (report.incomplete, report.wrong_values, report.misfiled, report.golden_defects) == (
        0, 1, 1, 2,
    )
    assert report.hallucinations == 0
    assert all(item.basis == "L3" for item in report.outcomes[:5])
    assert "hallucination" not in gate(report, "medical").reasons


def test_semantic_l2_outcomes_keep_incomplete_and_wrong_value_separate() -> None:
    items = [gold("partial"), gold("wrong"), gold("same")]
    report = semantic.evaluate_semantic(items, [pred(item) for item in items], [
        verdict(items[0], "insufficient"), verdict(items[1], "contradicted"), verdict(items[2]),
    ])
    assert [item.result for item in report.outcomes] == ["incomplete", "wrong_value", "correct"]
    assert (report.incomplete, report.wrong_values, report.micro.tp, report.micro.fp,
            report.micro.fn) == (1, 1, 1, 2, 2)
    assert all(item.basis == "L2" and item.reason == "核心事实判断" for item in report.outcomes)


def test_non_present_and_unscored_behavior_matches_literal_evaluation() -> None:
    items = [
        gold("missed"), gold("missing", state="unknown"),
        gold("hallucination", state="unknown"), gold("contradiction", state="absent_explicitly"),
        gold("matching", state="unknown"), gold("different", state="absent_explicitly"),
    ]
    predictions = [pred(items[2]), pred(items[3]), pred(items[4], state="unknown"),
                   pred(items[5], state="unknown"), pred(gold("outside"))]
    assert semantic.evaluate_semantic(items, predictions, []) == evaluate(items, predictions)


def test_all_excluded_defects_leave_undefined_metrics_and_fail_gate() -> None:
    item = gold(state="unknown")
    report = semantic.evaluate_semantic([item], [pred(item)], [], [
        ruling(item, "hallucination", "golden_defect"),
    ])
    assert report.golden_defects == 1
    assert report.micro.precision is None and report.micro.recall is None
    assert set(gate(report, "medical").reasons) == {"precision_undefined", "recall_undefined"}
