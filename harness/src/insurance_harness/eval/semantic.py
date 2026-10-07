"""Three-layer candidate scoring: deterministic, semantic, and attributed review."""

from collections.abc import Iterable
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from insurance_harness.eval.compare import compare_value
from insurance_harness.eval.equivalence import EquivalenceQuestion
from insurance_harness.eval.evaluator import ItemOutcome, Report, evaluate, report_from_outcomes
from insurance_harness.eval.golden import GoldenItem, NonBlank, Prediction
from insurance_harness.eval.normalize import values_equal


class SemanticVerdict(BaseModel):
    """One independent L2 decision, scoped to its product and field."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    product_id: NonBlank
    field_key: NonBlank
    verdict: Literal["equivalent", "contradicted", "insufficient"]
    reason: NonBlank


class Ruling(BaseModel):
    """An attributed L3 correction from the closed set of allowed transitions."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", populate_by_name=True)
    product_id: NonBlank
    field_key: NonBlank
    from_result: Literal["wrong_value", "incomplete", "correct", "hallucination"] = Field(
        alias="from",
    )
    to_result: Literal["correct", "incomplete", "wrong_value", "misfiled", "golden_defect"] = Field(
        alias="to",
    )
    reason: NonBlank
    by: NonBlank
    on: NonBlank

    def __init__(self, **data: object) -> None:
        # Accept both JSON aliases and Python field names through the same validation.
        super().__init__(**data)

    @model_validator(mode="after")
    def validate_transition(self) -> Self:
        allowed = {
            "wrong_value": {"correct", "incomplete", "golden_defect"},
            "incomplete": {"golden_defect"},
            "correct": {"incomplete", "wrong_value"},
            "hallucination": {"misfiled", "golden_defect"},
        }
        if self.to_result not in allowed[self.from_result]:
            raise ValueError(
                f"{self.field_key}: invalid ruling transition {self.from_result}->{self.to_result}",
            )
        return self


type _Key = tuple[str, str]


def _index[T: Prediction](
    items: Iterable[T], kind: str, packs: dict[_Key, str],
) -> dict[_Key, T]:
    indexed = {}
    for item in items:
        key = item.product_id, item.field_key
        if key in packs and packs[key] != item.pack_id:
            raise ValueError(f"{item.field_key}: product/field occurs in multiple packs")
        if key in indexed:
            raise ValueError(f"{item.field_key}: duplicate {kind} identity {item.identity!r}")
        packs[key] = item.pack_id
        indexed[key] = item
    return indexed


def _inputs(
    golden: Iterable[GoldenItem], predictions: Iterable[Prediction],
) -> tuple[dict[_Key, GoldenItem], dict[_Key, Prediction]]:
    # The judge protocol has no pack key: enforce that it identifies exactly one
    # field across both input sides, including predictions outside the Golden.
    packs: dict[_Key, str] = {}
    return _index(golden, "golden", packs), _index(predictions, "prediction", packs)


def _questions(
    goldens: dict[_Key, GoldenItem], predicted: dict[_Key, Prediction],
) -> dict[str, list[EquivalenceQuestion]]:
    questions: dict[str, list[EquivalenceQuestion]] = {}
    for key, item in goldens.items():
        prediction = predicted.get(key)
        if item.state != "present" or prediction is None or prediction.state != "present":
            continue
        if (values_equal(item.value, prediction.value)
                or compare_value(item, prediction.value).correct):
            continue
        assert item.value is not None
        questions.setdefault(item.product_id, []).append(EquivalenceQuestion(
            field_key=item.field_key, reference=item.value, judged=prediction.value, components=[],
        ))
    return {
        product: sorted(fields, key=lambda question: question.field_key)
        for product, fields in questions.items()
    }


def semantic_questions(
    golden: Iterable[GoldenItem], predictions: Iterable[Prediction],
) -> dict[str, list[EquivalenceQuestion]]:
    """Ask L2 only about present pairs that neither deterministic comparison settles."""
    return _questions(*_inputs(golden, predictions))


def _verdicts(
    verdicts: Iterable[SemanticVerdict], questions: dict[str, list[EquivalenceQuestion]],
) -> dict[_Key, SemanticVerdict]:
    expected = {
        (product, question.field_key)
        for product, fields in questions.items() for question in fields
    }
    indexed = {}
    for verdict in verdicts:
        key = verdict.product_id, verdict.field_key
        if key in indexed:
            raise ValueError(f"{verdict.field_key}: duplicate semantic verdict")
        if key not in expected:
            raise ValueError(f"{verdict.field_key}: unrequested semantic verdict")
        indexed[key] = verdict
    missing = expected - indexed.keys()
    if missing:
        raise ValueError(f"missing semantic verdicts: {sorted(missing)!r}")
    return indexed


def _apply_rulings(outcomes: list[ItemOutcome], rulings: Iterable[Ruling]) -> None:
    indexed = {(item.product_id, item.field_key): item for item in outcomes}
    ruled: set[_Key] = set()
    for ruling in rulings:
        key = ruling.product_id, ruling.field_key
        outcome = indexed.get(key)
        if key in ruled:
            raise ValueError(f"{ruling.field_key}: duplicate ruling")
        if outcome is None or outcome.result != ruling.from_result:
            raise ValueError(f"{ruling.field_key}: ruling does not match current result")
        if outcome.result == "correct" and outcome.basis != "L2":
            raise ValueError(f"{ruling.field_key}: only L2 correct results can be ruled")
        outcome.result = ruling.to_result
        outcome.basis, outcome.reason = "L3", ruling.reason
        outcome.tp = int(ruling.to_result == "correct")
        outcome.fp = int(ruling.to_result in {"incomplete", "wrong_value", "misfiled"})
        outcome.fn = int(ruling.to_result in {"incomplete", "wrong_value"})
        ruled.add(key)


def evaluate_semantic(
    golden: Iterable[GoldenItem], predictions: Iterable[Prediction],
    verdicts: Iterable[SemanticVerdict], rulings: Iterable[Ruling] = (),
) -> Report:
    """Score all requested verdicts exactly once, then aggregate final L3 decisions.

    L2 only tests coverage of Golden facts; additional candidate facts require
    independent source verification and are not checked by this comparison.
    """
    goldens, predicted = _inputs(golden, predictions)
    decisions = _verdicts(verdicts, _questions(goldens, predicted))
    outcomes = evaluate(goldens.values(), predicted.values()).outcomes
    for outcome in outcomes:
        if outcome.golden_state != "present" or outcome.predicted_state != "present":
            continue
        decision = decisions.get((outcome.product_id, outcome.field_key))
        outcome.basis = "L2" if decision else "L1"
        outcome.reason = decision.reason if decision else None
        if decision is None or decision.verdict == "equivalent":
            outcome.result, outcome.tp, outcome.fp, outcome.fn = "correct", 1, 0, 0
        else:
            outcome.result = "incomplete" if decision.verdict == "insufficient" else "wrong_value"
            outcome.tp, outcome.fp, outcome.fn = 0, 1, 1
        # Literal misses are not semantic failures; the L2 reason supplies the
        # explanation. Non-present cases retain evaluate's original diagnostics.
        outcome.component_misses, outcome.forbidden_hits = [], []
    _apply_rulings(outcomes, rulings)
    return report_from_outcomes(outcomes)
