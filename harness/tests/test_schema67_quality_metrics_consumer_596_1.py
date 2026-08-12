from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, cast

import pytest

import insurance_harness.goldenset.schema67_golden_quality_gate_596_1 as golden_gate_module
import insurance_harness.goldenset.schema67_quality_metrics_consumer_596_1 as consumer_module
from insurance_harness.goldenset.schema67_golden_quality_gate_596_1 import (
    HumanBatchDecisionReceiptV1,
    Schema67GoldenEvaluationResultV1,
    SchemaWikiGoldenQualityDossierV2,
)
from insurance_harness.goldenset.schema67_quality_metrics_596_1 import (
    Schema67MetricBBoxV1,
    Schema67MetricEvidenceV1,
    Schema67MetricRowV1,
    Schema67QualityMetricsV1,
    compute_schema67_quality_metrics_596_1,
)
from insurance_harness.goldenset.schema67_quality_metrics_consumer_596_1 import (
    Schema67QualityMetricsConsumerError,
    compute_admitted_schema67_quality_metrics_596_1,
)
from insurance_harness.goldenset.schema67_reviewed_golden_successor_596_1 import (
    Schema67ReviewedGoldenSuccessor5961V1,
)
from tests.test_schema67_golden_dossier_receipt_authority_596_1 import (
    _ATTESTATION_SHA256,
    _GOLDEN_ARTIFACT_SHA256,
    _MAPPING_SHA256,
    _STATUS_VECTOR_SHA256,
    _registered_formal,
)

_CURRENT = (
    Path(__file__).parents[2]
    / "dataset/goldenset-drafts/schema67-reviewed-golden-successor-596-1/golden67-successor.json"
)
_A = "a" * 64
_B = "b" * 64
_C = "c" * 64
_NOT_COVERED_FIELD_IDS = (
    "product_type",
    "marketing_tagline",
    "product_overview",
    "health_declaration_requirements",
    "eligible_occupation_classes",
    "premium_grace_period",
    "guaranteed_renewal_status",
    "premium_adjustment_rules",
    "direct_billing_and_advance_payment_rules",
    "eligible_service_packages",
    "tax_qualified_status",
    "tax_benefit_rules",
    "objection_handling_scripts",
    "product_faq",
    "four_step_sales_script",
    "sales_pitch_script",
)
_NOT_COVERED_REASON = "NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS"


def _current() -> Schema67ReviewedGoldenSuccessor5961V1:
    return Schema67ReviewedGoldenSuccessor5961V1.model_validate(
        json.loads(_CURRENT.read_bytes())
    )


def _formal(monkeypatch: pytest.MonkeyPatch) -> tuple[object, ...]:
    return cast(tuple[object, ...], _registered_formal(monkeypatch))


def _compute_formal(
    values: tuple[object, ...],
    *,
    overrides: dict[str, object] | None = None,
) -> Schema67QualityMetricsV1:
    candidate, evidence, golden, result, evaluation, receipt, _, dossier = values
    assert isinstance(result, Schema67GoldenEvaluationResultV1)
    arguments: dict[str, object] = {
        "admission": result,
        "evaluation": evaluation,
        "dossier": dossier,
        "human_batch_decision_receipt": receipt,
        "candidate": candidate,
        "evidence_authority": evidence,
        "golden": golden,
        "mapping_sha256": _MAPPING_SHA256,
        "golden_artifact_sha256": _GOLDEN_ARTIFACT_SHA256,
        "status_vector_sha256": _STATUS_VECTOR_SHA256,
        "attestation_sha256": _ATTESTATION_SHA256,
        "rows": _rows(result),
    }
    if overrides is not None:
        arguments.update(overrides)
    return compute_admitted_schema67_quality_metrics_596_1(**arguments)  # type: ignore[arg-type]


def _rows(result: Schema67GoldenEvaluationResultV1) -> tuple[Schema67MetricRowV1, ...]:
    bbox = Schema67MetricBBoxV1(x0=100_000, y0=100_000, x1=300_000, y1=300_000)
    rows: list[Schema67MetricRowV1] = []
    for index, decision in enumerate(result.private_dossier.field_decisions):
        expected_state: Literal["present", "absent_explicitly", "unknown"] = (
            decision.golden_state
        )
        observed_state: Literal["present", "absent_explicitly", "unknown"] = (
            decision.candidate_state
        )
        evidence: tuple[Schema67MetricEvidenceV1, ...] = ()
        if index in {0, 1}:
            page = 12 if index == 0 else 27
            target = "terms-page-12" if index == 0 else "brochure-page-27"
            evidence = (
                Schema67MetricEvidenceV1(
                    expected_document_sha256=_A,
                    observed_document_sha256=_A,
                    expected_revision_sha256=_B,
                    observed_revision_sha256=_B,
                    expected_page_number=page,
                    observed_page_number=page,
                    expected_quote_sha256=_C,
                    observed_quote_sha256=_C,
                    expected_bbox=bbox,
                    observed_bbox=bbox,
                    expected_target_id=target,
                    observed_target_id=target,
                ),
            )
        rows.append(
            Schema67MetricRowV1(
                field_id=decision.field_id,
                expected_state=expected_state,
                observed_state=observed_state,
                expected_value_atoms=(f"expected-{decision.field_id}",)
                if expected_state == "present"
                else (),
                observed_value_atoms=(f"expected-{decision.field_id}",)
                if observed_state == "present"
                else (),
                evidence_required=index in {0, 1},
                evidence=evidence,
                high_risk=index == 0,
                conflict=index == 1,
                human_pass=True if index in {0, 1} else None,
            )
        )
    return tuple(rows)


def test_current_complete_67_unverified_successor_blocks_only_for_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator_calls = 0
    kernel_calls = 0

    def forbidden(rows: Sequence[Schema67MetricRowV1]) -> Schema67QualityMetricsV1:
        nonlocal kernel_calls
        kernel_calls += 1
        raise AssertionError(rows)

    def forbidden_validator(*args: object, **kwargs: object) -> object:
        nonlocal evaluator_calls
        evaluator_calls += 1
        raise AssertionError((args, kwargs))

    monkeypatch.setattr(consumer_module, "_compute_metrics", forbidden)
    monkeypatch.setattr(
        consumer_module,
        "validate_registered_schema_wiki_golden_quality_dossier_v2_596_1",
        forbidden_validator,
    )
    current = _current()
    assert current.source_review_status == "COMPLETED"
    assert current.review_metadata.reviewed_by == "linyao"
    assert current.review_metadata.annotator_model_id == "claude-fable-5"
    assert current.review_metadata.reviewed_at is None
    assert current.schema67_mapping_status == "COMPLETE_67"
    assert current.residual_pending_field_ids == ()
    assert tuple(row.field_id for row in current.fields) == current.ordered_field_ids
    assert len(current.fields) == 67
    assert all(row.review_status == "REVIEWED" for row in current.fields)
    assert "RESIDUAL" not in current.golden_admission_status
    assert "RECEIPT_UNVERIFIED" in current.golden_admission_status

    with pytest.raises(Schema67QualityMetricsConsumerError, match="GOLDEN_ADMISSION_BLOCKED"):
        compute_admitted_schema67_quality_metrics_596_1(admission=current, rows=())

    assert evaluator_calls == 0
    assert kernel_calls == 0


def test_exact_16_not_covered_fields_are_normal_unknowns() -> None:
    current = _current()
    by_field_id = {row.field_id: row for row in current.fields}

    assert tuple(
        row.field_id
        for row in current.fields
        if row.model_dump(mode="json").get("unknown_reason") == _NOT_COVERED_REASON
    ) == _NOT_COVERED_FIELD_IDS
    for field_id in _NOT_COVERED_FIELD_IDS:
        row = by_field_id[field_id]
        payload = row.model_dump(mode="json")
        assert row.review_status == "REVIEWED"
        assert row.state == "unknown"
        assert row.value is None
        assert row.evidence == ()
        assert payload.get("unknown_reason") == _NOT_COVERED_REASON
        assert payload.get("residual_reason") is None
        assert "PENDING" not in row.model_dump_json()
        assert "RESIDUAL" not in row.model_dump_json()


def test_registered_pair_without_concrete_human_batch_receipt_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _formal(monkeypatch)
    formal = values[3]
    assert isinstance(formal, Schema67GoldenEvaluationResultV1)
    calls = 0

    def forbidden(exact_rows: Sequence[Schema67MetricRowV1]) -> Schema67QualityMetricsV1:
        nonlocal calls
        calls += 1
        raise AssertionError(exact_rows)

    monkeypatch.setattr(consumer_module, "_compute_metrics", forbidden)
    with pytest.raises(Schema67QualityMetricsConsumerError, match="GOLDEN_ADMISSION_INVALID"):
        _compute_formal(
            values,
            overrides={"human_batch_decision_receipt": None},
        )

    assert calls == 0
    assert formal.provider_calls == formal.draft_calls == formal.review_calls == 0
    assert formal.activation_calls == 0


def test_worktree1_must_supply_registered_pair_human_receipt_validator() -> None:
    validator = getattr(
        golden_gate_module,
        "validate_registered_schema_wiki_golden_quality_dossier_v2_596_1",
        None,
    )

    assert callable(validator), (
        "missing worktree1 authority seam: "
        "validate_registered_schema_wiki_golden_quality_dossier_v2_596_1 must "
        "accept the original registered evaluation, original registered Dossier V2, "
        "and concrete verified HumanBatchDecisionReceiptV1"
    )


def test_caller_shaped_human_receipt_cannot_authorize_registered_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _formal(monkeypatch)
    formal = values[3]
    assert isinstance(formal, Schema67GoldenEvaluationResultV1)
    calls = 0

    def forbidden(rows: Sequence[Schema67MetricRowV1]) -> Schema67QualityMetricsV1:
        nonlocal calls
        calls += 1
        raise AssertionError(rows)

    monkeypatch.setattr(consumer_module, "_compute_metrics", forbidden)
    assert formal.quality_gate_receipt is not None
    caller_shaped_receipt = {
        "version": "1",
        "decision": "approve",
        "principal_id": "linyao",
        "candidate_hash": formal.quality_gate_receipt.candidate_sha256,
    }

    with pytest.raises(Schema67QualityMetricsConsumerError, match="GOLDEN_ADMISSION_INVALID"):
        _compute_formal(
            values,
            overrides={"human_batch_decision_receipt": caller_shaped_receipt},
        )

    assert calls == 0


def test_reparsed_self_consistent_pass_result_is_not_a_registered_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _formal(monkeypatch)
    formal = values[3]
    assert isinstance(formal, Schema67GoldenEvaluationResultV1)
    reparsed = Schema67GoldenEvaluationResultV1.model_validate(formal.model_dump(mode="python"))
    calls = 0

    def forbidden(rows: Sequence[Schema67MetricRowV1]) -> Schema67QualityMetricsV1:
        nonlocal calls
        calls += 1
        raise AssertionError(rows)

    monkeypatch.setattr(consumer_module, "_compute_metrics", forbidden)
    with pytest.raises(Schema67QualityMetricsConsumerError, match="GOLDEN_ADMISSION_INVALID"):
        _compute_formal(values, overrides={"admission": reparsed})
    assert calls == 0


def test_formal_result_without_dossier_is_blocked_before_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _formal(monkeypatch)
    calls = 0

    def forbidden(rows: Sequence[Schema67MetricRowV1]) -> Schema67QualityMetricsV1:
        nonlocal calls
        calls += 1
        raise AssertionError(rows)

    monkeypatch.setattr(consumer_module, "_compute_metrics", forbidden)
    with pytest.raises(Schema67QualityMetricsConsumerError, match="GOLDEN_ADMISSION_INVALID"):
        _compute_formal(values, overrides={"dossier": None})
    assert calls == 0


def test_reparsed_self_consistent_dossier_is_not_a_registered_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _formal(monkeypatch)
    dossier = values[7]
    assert isinstance(dossier, SchemaWikiGoldenQualityDossierV2)
    reparsed = SchemaWikiGoldenQualityDossierV2.model_validate(
        dossier.model_dump(mode="python")
    )
    calls = 0

    def forbidden(rows: Sequence[Schema67MetricRowV1]) -> Schema67QualityMetricsV1:
        nonlocal calls
        calls += 1
        raise AssertionError(rows)

    monkeypatch.setattr(consumer_module, "_compute_metrics", forbidden)
    with pytest.raises(Schema67QualityMetricsConsumerError, match="GOLDEN_ADMISSION_INVALID"):
        _compute_formal(values, overrides={"dossier": reparsed})
    assert calls == 0


def test_self_built_dossier_reusing_nested_objects_is_not_a_registered_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _formal(monkeypatch)
    dossier = values[7]
    assert isinstance(dossier, SchemaWikiGoldenQualityDossierV2)
    self_built = SchemaWikiGoldenQualityDossierV2(
        version=dossier.version,
        preparation_id=dossier.preparation_id,
        evaluation_id=dossier.evaluation_id,
        quality_gate_receipt_sha256=dossier.quality_gate_receipt_sha256,
        private_dossier=dossier.private_dossier,
        review_successor=dossier.review_successor,
        evaluation_bundle_sha256=dossier.evaluation_bundle_sha256,
        serving_effect=dossier.serving_effect,
    )
    calls = 0

    def forbidden(rows: Sequence[Schema67MetricRowV1]) -> Schema67QualityMetricsV1:
        nonlocal calls
        calls += 1
        raise AssertionError(rows)

    monkeypatch.setattr(consumer_module, "_compute_metrics", forbidden)
    with pytest.raises(Schema67QualityMetricsConsumerError, match="GOLDEN_ADMISSION_INVALID"):
        _compute_formal(values, overrides={"dossier": self_built})
    assert calls == 0


def test_registered_dossier_cannot_be_cross_joined_to_another_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _formal(monkeypatch)
    other_values = _formal(monkeypatch)
    other_dossier = other_values[7]
    other_receipt = other_values[5]
    calls = 0

    def forbidden(rows: Sequence[Schema67MetricRowV1]) -> Schema67QualityMetricsV1:
        nonlocal calls
        calls += 1
        raise AssertionError(rows)

    monkeypatch.setattr(consumer_module, "_compute_metrics", forbidden)
    with pytest.raises(Schema67QualityMetricsConsumerError, match="GOLDEN_ADMISSION_INVALID"):
        _compute_formal(
            values,
            overrides={
                "dossier": other_dossier,
                "human_batch_decision_receipt": other_receipt,
            },
        )
    assert calls == 0


def test_exact_registered_pair_calls_metrics_kernel_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _formal(monkeypatch)
    calls = 0

    def measured(rows: Sequence[Schema67MetricRowV1]) -> Schema67QualityMetricsV1:
        nonlocal calls
        calls += 1
        return compute_schema67_quality_metrics_596_1(rows)

    monkeypatch.setattr(consumer_module, "_compute_metrics", measured)
    metrics = _compute_formal(values)

    assert calls == 1
    assert metrics.evaluated_field_count == 67
    formal = values[3]
    assert isinstance(formal, Schema67GoldenEvaluationResultV1)
    assert formal.provider_calls == formal.draft_calls == formal.review_calls == 0
    assert formal.activation_calls == 0


@pytest.mark.parametrize(
    "drift",
    ("receipt_reparse", "foreign_evidence", "mapping", "golden_artifact", "status", "attestation"),
)
def test_registered_pair_authority_drift_is_rejected_before_metrics(
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    values = _formal(monkeypatch)
    overrides: dict[str, object]
    if drift == "receipt_reparse":
        receipt = values[5]
        assert isinstance(receipt, HumanBatchDecisionReceiptV1)
        overrides = {
            "human_batch_decision_receipt": HumanBatchDecisionReceiptV1.model_validate(
                receipt.model_dump(mode="python")
            )
        }
    elif drift == "foreign_evidence":
        overrides = {"evidence_authority": _formal(monkeypatch)[1]}
    elif drift == "mapping":
        overrides = {"mapping_sha256": "d" * 64}
    elif drift == "golden_artifact":
        overrides = {"golden_artifact_sha256": "d" * 64}
    elif drift == "status":
        overrides = {"status_vector_sha256": "d" * 64}
    else:
        overrides = {"attestation_sha256": "d" * 64}
    calls = 0

    def forbidden(rows: Sequence[Schema67MetricRowV1]) -> Schema67QualityMetricsV1:
        nonlocal calls
        calls += 1
        raise AssertionError(rows)

    monkeypatch.setattr(consumer_module, "_compute_metrics", forbidden)
    with pytest.raises(Schema67QualityMetricsConsumerError, match="GOLDEN_ADMISSION_INVALID"):
        _compute_formal(values, overrides=overrides)
    assert calls == 0
