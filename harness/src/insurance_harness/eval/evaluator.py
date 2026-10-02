"""Pack-scoped deterministic scoring and fail-closed quality admission."""

import math
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from insurance_harness.eval.compare import compare_value
from insurance_harness.eval.golden import GoldenItem, Prediction, State


class Metrics(BaseModel):
    tp: int = 0
    fp: int = 0
    fn: int = 0
    hallucinations: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def precision(self) -> float | None:
        denominator = self.tp + self.fp
        return self.tp / denominator if denominator else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recall(self) -> float | None:
        denominator = self.tp + self.fn
        return self.tp / denominator if denominator else None


class ItemOutcome(BaseModel):
    """One keyed decision; missing predictions and non-present mismatches differ."""

    pack_id: str
    product_id: str
    field_key: str
    golden_state: State | None
    predicted_state: State | None
    golden_value: str | None
    predicted_value: str | None
    result: Literal[
        "correct", "mismatch", "missed", "hallucination", "contradiction",
        "correct_non_present", "state_mismatch", "missing", "unscored",
    ]
    tp: int = 0
    fp: int = 0
    fn: int = 0
    component_misses: list[str] = Field(default_factory=list)
    forbidden_hits: list[str] = Field(default_factory=list)


class Report(BaseModel):
    per_field: dict[str, Metrics] = Field(default_factory=dict)
    per_pack: dict[str, Metrics] = Field(default_factory=dict)
    micro: Metrics = Field(default_factory=Metrics)
    hallucinations: int = 0
    contradictions: int = 0
    correct_non_present: int = 0
    missing_predictions: int = 0
    unscored_predictions: int = 0
    component_misses: dict[str, list[str]] = Field(default_factory=dict)
    outcomes: list[ItemOutcome] = Field(default_factory=list)


class GateVerdict(BaseModel):
    passed: bool
    reasons: list[str]


def _index[T: Prediction](items: Iterable[T], kind: str) -> dict[tuple[str, str, str], T]:
    indexed: dict[tuple[str, str, str], T] = {}
    for item in items:
        if item.identity in indexed:
            raise ValueError(f"duplicate {kind} identity: {item.identity!r}")
        indexed[item.identity] = item
    return indexed


def _outcome(golden: GoldenItem | None, prediction: Prediction | None) -> ItemOutcome:
    item = golden if golden is not None else prediction
    assert item is not None
    outcome = ItemOutcome(
        pack_id=item.pack_id, product_id=item.product_id, field_key=item.field_key,
        golden_state=golden.state if golden else None,
        predicted_state=prediction.state if prediction else None,
        golden_value=golden.value if golden else None,
        predicted_value=prediction.value if prediction else None,
        result="unscored",
    )
    if golden is None:
        return outcome
    if golden.state == "present":
        if prediction is None or prediction.state != "present":
            outcome.result, outcome.fn = "missed", 1
            outcome.component_misses = compare_value(golden, None).component_misses
        else:
            comparison = compare_value(golden, prediction.value)
            outcome.component_misses = comparison.component_misses
            outcome.forbidden_hits = comparison.forbidden_hits
            if comparison.correct:
                outcome.result, outcome.tp = "correct", 1
            else:
                outcome.result, outcome.fp, outcome.fn = "mismatch", 1, 1
    elif prediction is None:
        outcome.result = "missing"
    elif prediction.state == "present":
        outcome.result = "hallucination" if golden.state == "unknown" else "contradiction"
        outcome.fp = 1
    elif prediction.state == golden.state:
        outcome.result = "correct_non_present"
    else:
        # The spec excludes non-present disagreements from P/R denominators.
        outcome.result = "state_mismatch"
    return outcome


def evaluate(golden: Iterable[GoldenItem], predictions: Iterable[Prediction]) -> Report:
    """Score unique (pack, product, field) identities without silently overwriting."""
    goldens = _index(golden, "golden")
    predicted = _index(predictions, "prediction")
    report = Report()
    for identity, item in goldens.items():
        prediction = predicted.get(identity)
        outcome = _outcome(item, prediction)
        report.outcomes.append(outcome)
        report.missing_predictions += prediction is None
        report.hallucinations += outcome.result == "hallucination"
        report.contradictions += outcome.result == "contradiction"
        report.correct_non_present += outcome.result == "correct_non_present"
        for metrics in (
            report.per_field.setdefault(item.field_key, Metrics()),
            report.per_pack.setdefault(item.pack_id, Metrics()),
            report.micro,
        ):
            metrics.tp += outcome.tp
            metrics.fp += outcome.fp
            metrics.fn += outcome.fn
            metrics.hallucinations += outcome.result == "hallucination"
        if outcome.component_misses:
            # The spec's display key lacks pack_id. Preserve all missing names;
            # outcomes above retain each pack's separate, auditable result.
            misses = report.component_misses.setdefault(f"{item.product_id}/{item.field_key}", [])
            misses.extend(name for name in outcome.component_misses if name not in misses)
    for identity, prediction in predicted.items():
        if identity not in goldens:
            report.outcomes.append(_outcome(None, prediction))
            report.unscored_predictions += 1
    return report


def gate(
    report: Report,
    pack_id: str,
    min_precision: float = 0.95,
    min_recall: float = 0.90,
) -> GateVerdict:
    """Admit only the requested pack when all required measures pass."""
    for threshold in (min_precision, min_recall):
        if not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError("quality threshold must be finite and between 0 and 1")
    metrics = report.per_pack.get(pack_id, Metrics())
    reasons = []
    for name, value, threshold in (
        ("precision", metrics.precision, min_precision),
        ("recall", metrics.recall, min_recall),
    ):
        if value is None:
            reasons.append(f"{name}_undefined")
        elif value < threshold:
            reasons.append(f"{name}_below")
    if metrics.hallucinations:
        reasons.append("hallucination")
    return GateVerdict(passed=not reasons, reasons=reasons)
