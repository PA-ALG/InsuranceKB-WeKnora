"""Thin consumer from the existing formal Golden evaluator to pure Schema67 metrics."""

from __future__ import annotations

from collections.abc import Sequence

from insurance_harness.goldenset.schema67_golden_quality_gate_596_1 import (
    Schema67GoldenEvaluationResultV1,
    Schema67GoldenQualityGateError,
    make_schema67_golden_evaluation_review_bundle_596_1,
)
from insurance_harness.goldenset.schema67_quality_metrics_596_1 import (
    Schema67MetricRowV1,
    Schema67QualityMetricsError,
    Schema67QualityMetricsV1,
    compute_schema67_quality_metrics_596_1,
)
from insurance_harness.goldenset.schema67_reviewed_golden_successor_596_1 import (
    Schema67ReviewedGoldenSuccessor5961V1,
)
from insurance_harness.knowledge_compiler.schema_first_contracts import (
    APPROVED_ORDERED_FIELD_IDS,
)


class Schema67QualityMetricsConsumerError(ValueError):
    """Stable consumer error; never a Golden or quality verdict."""


def _compute_metrics(
    rows: Sequence[Schema67MetricRowV1],
) -> Schema67QualityMetricsV1:
    return compute_schema67_quality_metrics_596_1(rows)


def compute_admitted_schema67_quality_metrics_596_1(
    *,
    admission: Schema67ReviewedGoldenSuccessor5961V1 | Schema67GoldenEvaluationResultV1,
    rows: Sequence[Schema67MetricRowV1],
) -> Schema67QualityMetricsV1:
    """Measure only after the existing evaluator has produced a registered PASS receipt."""

    if type(admission) is Schema67ReviewedGoldenSuccessor5961V1:
        if (
            admission.source_review_status == "COMPLETED"
            and admission.schema67_mapping_status == "PARTIAL_51_CLOSED_16_RESIDUAL"
            and admission.golden_admission_status
            == "BLOCKED_RESIDUALS_AND_RECEIPT_UNVERIFIED"
            and len(admission.residual_pending_field_ids) == 16
            and admission.review_metadata.reviewed_at is None
            and admission.ready_to_sign.approval_receipt_sha256 is None
        ):
            raise Schema67QualityMetricsConsumerError("GOLDEN_ADMISSION_BLOCKED")
        raise Schema67QualityMetricsConsumerError("GOLDEN_ADMISSION_INVALID")

    if type(admission) is not Schema67GoldenEvaluationResultV1:
        raise Schema67QualityMetricsConsumerError("GOLDEN_ADMISSION_INVALID")
    try:
        bundle = make_schema67_golden_evaluation_review_bundle_596_1(admission)
    except Schema67GoldenQualityGateError:
        raise Schema67QualityMetricsConsumerError("GOLDEN_ADMISSION_INVALID") from None

    exact_rows = tuple(rows)
    decisions = bundle.private_dossier.field_decisions
    if (
        len(exact_rows) != 67
        or tuple(row.field_id for row in exact_rows) != APPROVED_ORDERED_FIELD_IDS
        or tuple(row.field_id for row in decisions) != APPROVED_ORDERED_FIELD_IDS
        or any(
            type(row) is not Schema67MetricRowV1
            or row.field_id != decision.field_id
            or row.expected_state != decision.golden_state
            or row.observed_state != decision.candidate_state
            for row, decision in zip(exact_rows, decisions, strict=True)
        )
    ):
        raise Schema67QualityMetricsConsumerError("METRICS_INPUT_INVALID")
    try:
        return _compute_metrics(exact_rows)
    except Schema67QualityMetricsError:
        raise Schema67QualityMetricsConsumerError("METRICS_INPUT_INVALID") from None


__all__ = [
    "Schema67QualityMetricsConsumerError",
    "compute_admitted_schema67_quality_metrics_596_1",
]
