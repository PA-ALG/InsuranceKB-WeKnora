from __future__ import annotations

from typing import Literal

import pytest

from insurance_harness.goldenset.schema67_quality_metrics_596_1 import (
    Schema67MetricBBoxV1,
    Schema67MetricEvidenceV1,
    Schema67MetricRowV1,
    Schema67MetricValueV1,
    Schema67QualityMetricsError,
    Schema67QualityMetricsV1,
    compute_schema67_quality_metrics_596_1,
)
from insurance_harness.knowledge_compiler.schema_first_contracts import (
    APPROVED_ORDERED_FIELD_IDS,
)

_A = "a" * 64
_B = "b" * 64
_C = "c" * 64
_D = "d" * 64


def _bbox(*, x0: int = 100_000, x1: int = 300_000) -> Schema67MetricBBoxV1:
    return Schema67MetricBBoxV1(x0=x0, y0=100_000, x1=x1, y1=300_000)


def _evidence(
    *,
    page: int,
    target: str,
    observed_page: int | None = None,
    expected_bbox: Schema67MetricBBoxV1 | None = None,
    observed_bbox: Schema67MetricBBoxV1 | None = None,
) -> Schema67MetricEvidenceV1:
    expected_bbox = expected_bbox or _bbox()
    return Schema67MetricEvidenceV1(
        expected_document_sha256=_A,
        observed_document_sha256=_A,
        expected_revision_sha256=_B,
        observed_revision_sha256=_B,
        expected_page_number=page,
        observed_page_number=page if observed_page is None else observed_page,
        expected_quote_sha256=_C,
        observed_quote_sha256=_C,
        expected_bbox=expected_bbox,
        observed_bbox=observed_bbox or expected_bbox,
        expected_target_id=target,
        observed_target_id=target,
    )


def _perfect_rows() -> tuple[Schema67MetricRowV1, ...]:
    rows: list[Schema67MetricRowV1] = []
    for index, field_id in enumerate(APPROVED_ORDERED_FIELD_IDS):
        expected_state: Literal["present", "absent_explicitly", "unknown"] = (
            "absent_explicitly" if index == 2 else "unknown" if index == 3 else "present"
        )
        evidence: tuple[Schema67MetricEvidenceV1, ...] = ()
        evidence_required = index in {0, 1}
        if index == 0:
            evidence = (_evidence(page=12, target="terms-page-12"),)
        elif index == 1:
            evidence = (_evidence(page=27, target="brochure-page-27"),)
        rows.append(
            Schema67MetricRowV1(
                field_id=field_id,
                expected_state=expected_state,
                observed_state=expected_state,
                expected_value_atoms=(f"atom-{index:02d}",)
                if expected_state == "present"
                else (),
                observed_value_atoms=(f"atom-{index:02d}",)
                if expected_state == "present"
                else (),
                evidence_required=evidence_required,
                evidence=evidence,
                high_risk=index == 0,
                conflict=index == 1,
                human_pass=True if index in {0, 1} else None,
            )
        )
    return tuple(rows)


def _metric(result: Schema67QualityMetricsV1, metric_id: str) -> Schema67MetricValueV1:
    return next(item for item in result.metrics if item.metric_id == metric_id)


def test_exact67_perfect_fixture_measures_every_required_dimension_without_authority() -> None:
    result = compute_schema67_quality_metrics_596_1(_perfect_rows())

    assert result.status == "COMPLETE"
    assert result.reason_codes == ()
    assert result.evaluated_field_count == 67
    assert len(result.tri_state_confusion) == 9
    assert sum(item.count for item in result.tri_state_confusion) == 67
    assert all(item.status == "MEASURED" for item in result.metrics)
    assert _metric(result, "state.tri_state_accuracy").value_ppm == 1_000_000
    assert _metric(result, "present_value.field_exact").value_ppm == 1_000_000
    assert _metric(result, "state.absent_to_unknown_confusion").value_ppm == 0
    assert _metric(result, "state.unknown_to_absent_confusion").value_ppm == 0
    assert _metric(result, "value.false_filled_or_hallucinated").value_ppm == 0
    assert result.bbox_iou_mean_ppm == 1_000_000
    assert set(result.model_dump(mode="json")) == {
        "contract",
        "status",
        "reason_codes",
        "evaluated_field_count",
        "tri_state_confusion",
        "metrics",
        "bbox_iou_mean_ppm",
    }
    dumped = repr(result.model_dump(mode="json")).lower()
    assert "receipt" not in dumped
    assert "admission" not in dumped
    assert "review" not in dumped


def test_state_confusion_normalized_atoms_and_false_fill_are_counted_exactly() -> None:
    rows = list(_perfect_rows())
    rows[0] = rows[0].model_copy(
        update={
            "expected_value_atoms": ("alpha", "beta"),
            "observed_value_atoms": ("beta", "gamma"),
        }
    )
    rows[2] = rows[2].model_copy(
        update={
            "expected_state": "absent_explicitly",
            "observed_state": "unknown",
            "expected_value_atoms": (),
            "observed_value_atoms": (),
        }
    )
    rows[3] = rows[3].model_copy(
        update={
            "expected_state": "unknown",
            "observed_state": "absent_explicitly",
            "expected_value_atoms": (),
            "observed_value_atoms": (),
        }
    )
    rows[4] = rows[4].model_copy(
        update={
            "expected_state": "unknown",
            "observed_state": "present",
            "expected_value_atoms": (),
            "observed_value_atoms": ("hallucinated",),
        }
    )

    result = compute_schema67_quality_metrics_596_1(tuple(rows))

    confusion = {
        (item.expected_state, item.observed_state): item.count
        for item in result.tri_state_confusion
    }
    assert confusion[("absent_explicitly", "unknown")] == 1
    assert confusion[("unknown", "absent_explicitly")] == 1
    assert confusion[("unknown", "present")] == 1
    assert _metric(result, "present_value.normalized_precision").value_ppm == 984_615
    assert _metric(result, "present_value.normalized_recall").value_ppm == 984_615
    assert _metric(result, "present_value.normalized_f1").value_ppm == 984_615
    assert _metric(result, "state.absent_to_unknown_confusion").value_ppm == 1_000_000
    assert _metric(result, "state.unknown_to_absent_confusion").value_ppm == 500_000
    assert _metric(result, "value.false_filled_or_hallucinated").value_ppm == 333_333


def test_normalized_atoms_remain_field_bound_when_values_are_cross_swapped() -> None:
    rows = list(_perfect_rows())
    left = rows[4].observed_value_atoms
    right = rows[5].observed_value_atoms
    rows[4] = rows[4].model_copy(update={"observed_value_atoms": right})
    rows[5] = rows[5].model_copy(update={"observed_value_atoms": left})

    result = compute_schema67_quality_metrics_596_1(tuple(rows))

    assert _metric(result, "present_value.field_exact").value_ppm == 969_230
    assert _metric(result, "present_value.normalized_precision").value_ppm == 969_230
    assert _metric(result, "present_value.normalized_recall").value_ppm == 969_230


def test_evidence_dimensions_and_actual_bbox_iou_are_not_collapsed_to_pass_count() -> None:
    rows = list(_perfect_rows())
    rows[0] = rows[0].model_copy(
        update={
            "evidence": (
                _evidence(
                    page=12,
                    target="terms-page-12",
                    observed_bbox=_bbox(x0=200_000, x1=400_000),
                ),
            )
        }
    )
    second = rows[1].evidence[0].model_copy(
        update={
            "observed_document_sha256": _D,
            "observed_revision_sha256": _D,
            "observed_page_number": 26,
            "observed_quote_sha256": _D,
            "observed_target_id": "foreign-page-27",
            "observed_bbox": None,
        }
    )
    rows[1] = rows[1].model_copy(update={"evidence": (second,)})

    result = compute_schema67_quality_metrics_596_1(tuple(rows))

    assert _metric(result, "evidence.field_coverage").value_ppm == 1_000_000
    assert _metric(result, "evidence.document_accuracy").value_ppm == 500_000
    assert _metric(result, "evidence.revision_accuracy").value_ppm == 500_000
    assert _metric(result, "evidence.page_accuracy").value_ppm == 500_000
    assert _metric(result, "evidence.quote_hash_accuracy").value_ppm == 500_000
    assert _metric(result, "evidence.bbox_coverage").value_ppm == 500_000
    assert result.bbox_iou_mean_ppm == 166_666
    assert _metric(result, "evidence.page12_page27_distinct_target_accuracy").value_ppm == 500_000


@pytest.mark.parametrize(
    "attack",
    [
        lambda rows: rows[:-1],
        lambda rows: (rows[1], rows[0], *rows[2:]),
        lambda rows: (*rows[:-1], rows[0]),
    ],
)
def test_missing_reordered_or_duplicate_field_ids_are_typed_invalid(attack: object) -> None:
    with pytest.raises(Schema67QualityMetricsError, match="ORDERED67_INVALID"):
        compute_schema67_quality_metrics_596_1(attack(_perfect_rows()))  # type: ignore[operator]


def test_missing_required_evidence_is_inconclusive_not_a_zero_score() -> None:
    rows = list(_perfect_rows())
    rows[0] = rows[0].model_copy(update={"evidence": ()})

    result = compute_schema67_quality_metrics_596_1(tuple(rows))

    assert result.status == "INCONCLUSIVE"
    assert "REQUIRED_EVIDENCE_INCOMPLETE" in result.reason_codes
    evidence_metrics = [item for item in result.metrics if item.metric_id.startswith("evidence.")]
    assert evidence_metrics
    assert all(item.status == "NOT_EVALUABLE" for item in evidence_metrics)
    assert all(item.value_ppm is None for item in evidence_metrics)


def test_missing_denominators_and_human_decisions_are_inconclusive_not_fake_passes() -> None:
    rows = [
        row.model_copy(
            update={
                "expected_state": "unknown",
                "observed_state": "unknown",
                "expected_value_atoms": (),
                "observed_value_atoms": (),
                "evidence_required": False,
                "evidence": (),
                "human_pass": None,
            }
        )
        for row in _perfect_rows()
    ]
    rows[0] = rows[0].model_copy(update={"high_risk": True})

    result = compute_schema67_quality_metrics_596_1(tuple(rows))

    assert result.status == "INCONCLUSIVE"
    assert {
        "PRESENT_VALUE_DENOMINATOR_MISSING",
        "EVIDENCE_DENOMINATOR_MISSING",
        "DISTINCT_PAGE_TARGET_DENOMINATOR_MISSING",
        "HUMAN_DECISION_INCOMPLETE",
    }.issubset(result.reason_codes)
    assert _metric(result, "present_value.field_exact").value_ppm is None
    assert _metric(result, "evidence.document_accuracy").value_ppm is None
    assert _metric(result, "human.high_risk_pass").value_ppm is None


def test_atoms_must_be_unique_normalized_ordered_values() -> None:
    row = _perfect_rows()[0]
    with pytest.raises(ValueError):
        Schema67MetricRowV1.model_validate(
            row.model_dump()
            | {"expected_value_atoms": ("beta", "alpha")}
        )
    with pytest.raises(ValueError):
        Schema67MetricRowV1.model_validate(
            row.model_dump()
            | {"expected_value_atoms": ("alpha", "alpha")}
        )
