"""Thin consumer from the existing formal Golden evaluator to pure Schema67 metrics."""

from __future__ import annotations

from collections.abc import Sequence

from insurance_harness.goldenset.schema67_golden_quality_gate_596_1 import (
    HumanBatchDecisionReceiptV1,
    Schema67GoldenEvaluationResultV1,
    Schema67GoldenEvaluationReviewBundleV1,
    Schema67GoldenQualityGateError,
    Schema67GoldenSet5961V1,
    SchemaWikiGoldenQualityDossierV2,
    validate_registered_schema_wiki_golden_quality_dossier_v2_596_1,
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
    evaluation: Schema67GoldenEvaluationReviewBundleV1 | None = None,
    dossier: SchemaWikiGoldenQualityDossierV2 | None = None,
    human_batch_decision_receipt: HumanBatchDecisionReceiptV1 | None = None,
    candidate: object | None = None,
    evidence_authority: object | None = None,
    golden: Schema67GoldenSet5961V1 | None = None,
    mapping_sha256: str | None = None,
    golden_artifact_sha256: str | None = None,
    status_vector_sha256: str | None = None,
    attestation_sha256: str | None = None,
    rows: Sequence[Schema67MetricRowV1],
) -> Schema67QualityMetricsV1:
    """Measure only after the existing evaluator has produced a registered PASS receipt."""

    if type(admission) is Schema67ReviewedGoldenSuccessor5961V1:
        try:
            exact_status = Schema67ReviewedGoldenSuccessor5961V1.model_validate(
                admission.model_dump(mode="python")
            )
        except ValueError:
            raise Schema67QualityMetricsConsumerError("GOLDEN_ADMISSION_INVALID") from None
        if exact_status == admission and (
            exact_status.source_review_status == "COMPLETED"
            and exact_status.schema67_mapping_status == "COMPLETE_67"
            and exact_status.golden_admission_status == "BLOCKED_RECEIPT_UNVERIFIED"
            and not exact_status.residual_pending_field_ids
            and exact_status.review_metadata.reviewed_at is None
            and exact_status.ready_to_sign.approval_receipt_sha256 is None
        ):
            raise Schema67QualityMetricsConsumerError("GOLDEN_ADMISSION_BLOCKED")
        raise Schema67QualityMetricsConsumerError("GOLDEN_ADMISSION_INVALID")

    if type(admission) is not Schema67GoldenEvaluationResultV1:
        raise Schema67QualityMetricsConsumerError("GOLDEN_ADMISSION_INVALID")
    if (
        type(evaluation) is not Schema67GoldenEvaluationReviewBundleV1
        or type(dossier) is not SchemaWikiGoldenQualityDossierV2
        or type(human_batch_decision_receipt) is not HumanBatchDecisionReceiptV1
        or candidate is None
        or evidence_authority is None
        or type(golden) is not Schema67GoldenSet5961V1
        or type(mapping_sha256) is not str
        or type(golden_artifact_sha256) is not str
        or type(status_vector_sha256) is not str
        or type(attestation_sha256) is not str
    ):
        raise Schema67QualityMetricsConsumerError("GOLDEN_ADMISSION_INVALID")
    try:
        validated_dossier = validate_registered_schema_wiki_golden_quality_dossier_v2_596_1(
            dossier,
            result=admission,
            evaluation=evaluation,
            human_decision_receipt=human_batch_decision_receipt,
            candidate=candidate,
            evidence_authority=evidence_authority,
            golden=golden,
            mapping_sha256=mapping_sha256,
            golden_artifact_sha256=golden_artifact_sha256,
            status_vector_sha256=status_vector_sha256,
            attestation_sha256=attestation_sha256,
        )
    except (Schema67GoldenQualityGateError, TypeError, ValueError):
        raise Schema67QualityMetricsConsumerError("GOLDEN_ADMISSION_INVALID") from None
    if validated_dossier is not dossier:
        raise Schema67QualityMetricsConsumerError("GOLDEN_ADMISSION_INVALID")

    exact_rows = tuple(rows)
    decisions = evaluation.private_dossier.field_decisions
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
