"""Provider-free Schema67 metric arithmetic after upstream formal admission.

This module deliberately owns no Golden, review, receipt, admission, Candidate, or
release authority.  It accepts already-admitted, typed expected/observed rows and
returns measurement DTOs only.  Callers must not use its output as a quality gate.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Annotated, Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from insurance_harness.knowledge_compiler.schema_first_contracts import (
    APPROVED_ORDERED_FIELD_IDS,
)

TriState = Literal["present", "absent_explicitly", "unknown"]
MetricStatus = Literal["MEASURED", "NOT_EVALUABLE"]
ResultStatus = Literal["COMPLETE", "INCONCLUSIVE"]
Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=512, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
Ppm = Annotated[StrictInt, Field(ge=0, le=1_000_000)]

_TRI_STATES: Final[tuple[TriState, ...]] = (
    "present",
    "absent_explicitly",
    "unknown",
)
_EVIDENCE_METRIC_IDS: Final[tuple[str, ...]] = (
    "evidence.field_coverage",
    "evidence.document_accuracy",
    "evidence.revision_accuracy",
    "evidence.page_accuracy",
    "evidence.quote_hash_accuracy",
    "evidence.bbox_coverage",
    "evidence.page12_page27_distinct_target_accuracy",
)


class Schema67QualityMetricsError(ValueError):
    """Typed invalid input; this is not a quality verdict."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Schema67MetricBBoxV1(_FrozenModel):
    """A normalized top-left bbox; coordinates are exact integer millionths."""

    coordinate_space: Literal["normalized_top_left_0_1e6.v1"] = (
        "normalized_top_left_0_1e6.v1"
    )
    x0: Annotated[StrictInt, Field(ge=0, lt=1_000_000)]
    y0: Annotated[StrictInt, Field(ge=0, lt=1_000_000)]
    x1: Annotated[StrictInt, Field(gt=0, le=1_000_000)]
    y1: Annotated[StrictInt, Field(gt=0, le=1_000_000)]

    @model_validator(mode="after")
    def require_non_degenerate_box(self) -> Self:
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("BBOX_INVALID")
        return self


class Schema67MetricEvidenceV1(_FrozenModel):
    """One expected fragment paired with the observed fragment, if any."""

    expected_document_sha256: Sha256Hex
    observed_document_sha256: Sha256Hex | None
    expected_revision_sha256: Sha256Hex
    observed_revision_sha256: Sha256Hex | None
    expected_page_number: Annotated[StrictInt, Field(gt=0)]
    observed_page_number: Annotated[StrictInt, Field(gt=0)] | None
    expected_quote_sha256: Sha256Hex
    observed_quote_sha256: Sha256Hex | None
    expected_bbox: Schema67MetricBBoxV1
    observed_bbox: Schema67MetricBBoxV1 | None
    expected_target_id: NonBlankStr
    observed_target_id: NonBlankStr | None


class Schema67MetricRowV1(_FrozenModel):
    """An admitted field comparison expressed only as measurement atoms."""

    field_id: NonBlankStr
    expected_state: TriState
    observed_state: TriState
    expected_value_atoms: tuple[NonBlankStr, ...] = ()
    observed_value_atoms: tuple[NonBlankStr, ...] = ()
    evidence_required: StrictBool = False
    evidence: tuple[Schema67MetricEvidenceV1, ...] = ()
    high_risk: StrictBool = False
    conflict: StrictBool = False
    human_pass: StrictBool | None = None

    @field_validator("expected_value_atoms", "observed_value_atoms")
    @classmethod
    def require_canonical_atoms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(value))) != value:
            raise ValueError("VALUE_ATOMS_NONCANONICAL")
        return value

    @model_validator(mode="after")
    def require_state_value_consistency(self) -> Self:
        if (self.expected_state == "present") != bool(self.expected_value_atoms):
            raise ValueError("EXPECTED_STATE_VALUE_INVALID")
        if (self.observed_state == "present") != bool(self.observed_value_atoms):
            raise ValueError("OBSERVED_STATE_VALUE_INVALID")
        if self.human_pass is not None and not (self.high_risk or self.conflict):
            raise ValueError("HUMAN_PASS_OUT_OF_SCOPE")
        return self


class Schema67MetricValueV1(_FrozenModel):
    metric_id: NonBlankStr
    status: MetricStatus
    numerator: StrictInt | None
    denominator: StrictInt | None
    value_ppm: Ppm | None

    @model_validator(mode="after")
    def require_metric_shape(self) -> Self:
        values = (self.numerator, self.denominator, self.value_ppm)
        if self.status == "NOT_EVALUABLE":
            if values != (None, None, None):
                raise ValueError("NOT_EVALUABLE_METRIC_HAS_VALUE")
            return self
        if (
            self.numerator is None
            or self.denominator is None
            or self.value_ppm is None
            or self.denominator <= 0
            or self.numerator < 0
            or self.numerator > self.denominator
        ):
            raise ValueError("MEASURED_METRIC_INVALID")
        return self


class Schema67TriStateConfusionCellV1(_FrozenModel):
    expected_state: TriState
    observed_state: TriState
    count: Annotated[StrictInt, Field(ge=0)]


class Schema67QualityMetricsV1(_FrozenModel):
    """Pure measurements.  No field in this DTO carries authority or a verdict."""

    contract: Literal["schema67-quality-metrics.v1"] = "schema67-quality-metrics.v1"
    status: ResultStatus
    reason_codes: tuple[NonBlankStr, ...]
    evaluated_field_count: Literal[67]
    tri_state_confusion: tuple[Schema67TriStateConfusionCellV1, ...]
    metrics: tuple[Schema67MetricValueV1, ...]
    bbox_iou_mean_ppm: Ppm | None

    @model_validator(mode="after")
    def require_closed_output(self) -> Self:
        if len(self.tri_state_confusion) != 9:
            raise ValueError("TRI_STATE_CONFUSION_NOT_CLOSED")
        if len({item.metric_id for item in self.metrics}) != len(self.metrics):
            raise ValueError("DUPLICATE_METRIC_ID")
        if self.status == "COMPLETE" and (
            self.reason_codes
            or any(item.status != "MEASURED" for item in self.metrics)
            or self.bbox_iou_mean_ppm is None
        ):
            raise ValueError("COMPLETE_METRICS_INVALID")
        if self.status == "INCONCLUSIVE" and not self.reason_codes:
            raise ValueError("INCONCLUSIVE_REASON_MISSING")
        return self


def _ratio(metric_id: str, numerator: int, denominator: int) -> Schema67MetricValueV1:
    if denominator <= 0:
        return _not_evaluable(metric_id)
    return Schema67MetricValueV1(
        metric_id=metric_id,
        status="MEASURED",
        numerator=numerator,
        denominator=denominator,
        value_ppm=numerator * 1_000_000 // denominator,
    )


def _not_evaluable(metric_id: str) -> Schema67MetricValueV1:
    return Schema67MetricValueV1(
        metric_id=metric_id,
        status="NOT_EVALUABLE",
        numerator=None,
        denominator=None,
        value_ppm=None,
    )


def _bbox_iou_ppm(expected: Schema67MetricBBoxV1, observed: Schema67MetricBBoxV1) -> int:
    left = max(expected.x0, observed.x0)
    top = max(expected.y0, observed.y0)
    right = min(expected.x1, observed.x1)
    bottom = min(expected.y1, observed.y1)
    intersection = max(0, right - left) * max(0, bottom - top)
    expected_area = (expected.x1 - expected.x0) * (expected.y1 - expected.y0)
    observed_area = (observed.x1 - observed.x0) * (observed.y1 - observed.y0)
    union = expected_area + observed_area - intersection
    return intersection * 1_000_000 // union


def _require_exact67(rows: Sequence[Schema67MetricRowV1]) -> tuple[Schema67MetricRowV1, ...]:
    exact = tuple(rows)
    if (
        len(exact) != len(APPROVED_ORDERED_FIELD_IDS)
        or any(type(row) is not Schema67MetricRowV1 for row in exact)
        or tuple(row.field_id for row in exact) != APPROVED_ORDERED_FIELD_IDS
    ):
        raise Schema67QualityMetricsError("ORDERED67_INVALID")
    return exact


def compute_schema67_quality_metrics_596_1(
    rows: Sequence[Schema67MetricRowV1],
) -> Schema67QualityMetricsV1:
    """Compute deterministic metrics without making any quality/admission decision."""

    exact = _require_exact67(rows)
    reasons: set[str] = set()
    confusion = Counter((row.expected_state, row.observed_state) for row in exact)
    confusion_cells = tuple(
        Schema67TriStateConfusionCellV1(
            expected_state=expected,
            observed_state=observed,
            count=confusion[(expected, observed)],
        )
        for expected in _TRI_STATES
        for observed in _TRI_STATES
    )
    metrics: list[Schema67MetricValueV1] = [
        _ratio(
            "state.tri_state_accuracy",
            sum(row.expected_state == row.observed_state for row in exact),
            len(exact),
        )
    ]

    expected_present = tuple(row for row in exact if row.expected_state == "present")
    if not expected_present:
        reasons.add("PRESENT_VALUE_DENOMINATOR_MISSING")
        metrics.extend(
            _not_evaluable(metric_id)
            for metric_id in (
                "present_value.field_exact",
                "present_value.normalized_precision",
                "present_value.normalized_recall",
                "present_value.normalized_f1",
            )
        )
    else:
        metrics.append(
            _ratio(
                "present_value.field_exact",
                sum(
                    row.observed_state == "present"
                    and row.expected_value_atoms == row.observed_value_atoms
                    for row in expected_present
                ),
                len(expected_present),
            )
        )
        expected_atoms = Counter(
            (row.field_id, atom)
            for row in expected_present
            for atom in row.expected_value_atoms
        )
        observed_atoms = Counter(
            (row.field_id, atom)
            for row in expected_present
            for atom in row.observed_value_atoms
        )
        atom_tp = sum((expected_atoms & observed_atoms).values())
        atom_fp = sum((observed_atoms - expected_atoms).values())
        atom_fn = sum((expected_atoms - observed_atoms).values())
        metrics.extend(
            (
                _ratio("present_value.normalized_precision", atom_tp, atom_tp + atom_fp),
                _ratio("present_value.normalized_recall", atom_tp, atom_tp + atom_fn),
                _ratio("present_value.normalized_f1", 2 * atom_tp, 2 * atom_tp + atom_fp + atom_fn),
            )
        )

    expected_absent = tuple(
        row for row in exact if row.expected_state == "absent_explicitly"
    )
    expected_unknown = tuple(row for row in exact if row.expected_state == "unknown")
    if not expected_absent or not expected_unknown:
        reasons.add("STATE_DENOMINATOR_MISSING")
    metrics.extend(
        (
            _ratio(
                "state.absent_to_unknown_confusion",
                sum(row.observed_state == "unknown" for row in expected_absent),
                len(expected_absent),
            ),
            _ratio(
                "state.unknown_to_absent_confusion",
                sum(row.observed_state == "absent_explicitly" for row in expected_unknown),
                len(expected_unknown),
            ),
            _ratio(
                "value.false_filled_or_hallucinated",
                sum(
                    row.observed_state == "present"
                    for row in (*expected_absent, *expected_unknown)
                ),
                len(expected_absent) + len(expected_unknown),
            ),
        )
    )

    required_rows = tuple(row for row in exact if row.evidence_required)
    evidence_incomplete = any(not row.evidence for row in required_rows)
    evidence_fragments = tuple(fragment for row in exact for fragment in row.evidence)
    if evidence_incomplete:
        reasons.add("REQUIRED_EVIDENCE_INCOMPLETE")
        metrics.extend(_not_evaluable(metric_id) for metric_id in _EVIDENCE_METRIC_IDS)
        bbox_iou_mean_ppm: int | None = None
    elif not required_rows or not evidence_fragments:
        reasons.add("EVIDENCE_DENOMINATOR_MISSING")
        reasons.add("DISTINCT_PAGE_TARGET_DENOMINATOR_MISSING")
        metrics.extend(_not_evaluable(metric_id) for metric_id in _EVIDENCE_METRIC_IDS)
        bbox_iou_mean_ppm = None
    else:
        metrics.append(
            _ratio(
                "evidence.field_coverage",
                sum(bool(row.evidence) for row in required_rows),
                len(required_rows),
            )
        )
        fragment_count = len(evidence_fragments)
        metrics.extend(
            (
                _ratio(
                    "evidence.document_accuracy",
                    sum(
                        item.observed_document_sha256 == item.expected_document_sha256
                        for item in evidence_fragments
                    ),
                    fragment_count,
                ),
                _ratio(
                    "evidence.revision_accuracy",
                    sum(
                        item.observed_revision_sha256 == item.expected_revision_sha256
                        for item in evidence_fragments
                    ),
                    fragment_count,
                ),
                _ratio(
                    "evidence.page_accuracy",
                    sum(
                        item.observed_page_number == item.expected_page_number
                        for item in evidence_fragments
                    ),
                    fragment_count,
                ),
                _ratio(
                    "evidence.quote_hash_accuracy",
                    sum(
                        item.observed_quote_sha256 == item.expected_quote_sha256
                        for item in evidence_fragments
                    ),
                    fragment_count,
                ),
                _ratio(
                    "evidence.bbox_coverage",
                    sum(item.observed_bbox is not None for item in evidence_fragments),
                    fragment_count,
                ),
            )
        )
        bbox_iou_values = tuple(
            0
            if item.observed_bbox is None
            else _bbox_iou_ppm(item.expected_bbox, item.observed_bbox)
            for item in evidence_fragments
        )
        bbox_iou_mean_ppm = sum(bbox_iou_values) // fragment_count
        page_targets = tuple(
            item for item in evidence_fragments if item.expected_page_number in {12, 27}
        )
        pages = {item.expected_page_number for item in page_targets}
        targets_by_page = {
            page: {
                item.expected_target_id
                for item in page_targets
                if item.expected_page_number == page
            }
            for page in pages
        }
        distinct_targets = (
            pages == {12, 27}
            and targets_by_page[12]
            and targets_by_page[27]
            and targets_by_page[12].isdisjoint(targets_by_page[27])
        )
        if not distinct_targets:
            reasons.add("DISTINCT_PAGE_TARGET_DENOMINATOR_MISSING")
            metrics.append(
                _not_evaluable("evidence.page12_page27_distinct_target_accuracy")
            )
        else:
            metrics.append(
                _ratio(
                    "evidence.page12_page27_distinct_target_accuracy",
                    sum(
                        item.observed_page_number == item.expected_page_number
                        and item.observed_target_id == item.expected_target_id
                        for item in page_targets
                    ),
                    len(page_targets),
                )
            )

    for label, selected in (
        ("human.high_risk_pass", tuple(row for row in exact if row.high_risk)),
        ("human.conflict_pass", tuple(row for row in exact if row.conflict)),
    ):
        if not selected or any(row.human_pass is None for row in selected):
            reasons.add("HUMAN_DECISION_INCOMPLETE")
            metrics.append(_not_evaluable(label))
        else:
            metrics.append(
                _ratio(label, sum(row.human_pass is True for row in selected), len(selected))
            )

    ordered_reasons = tuple(sorted(reasons))
    return Schema67QualityMetricsV1(
        status="INCONCLUSIVE" if ordered_reasons else "COMPLETE",
        reason_codes=ordered_reasons,
        evaluated_field_count=67,
        tri_state_confusion=confusion_cells,
        metrics=tuple(metrics),
        bbox_iou_mean_ppm=bbox_iou_mean_ppm,
    )


__all__ = [
    "Schema67MetricBBoxV1",
    "Schema67MetricEvidenceV1",
    "Schema67MetricRowV1",
    "Schema67MetricValueV1",
    "Schema67QualityMetricsError",
    "Schema67QualityMetricsV1",
    "Schema67TriStateConfusionCellV1",
    "compute_schema67_quality_metrics_596_1",
]
