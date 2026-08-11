from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, cast

import pytest

import insurance_harness.goldenset.schema67_quality_metrics_consumer_596_1 as consumer_module
from insurance_harness.goldenset.schema67_golden_quality_gate_596_1 import (
    Schema67GoldenEvaluationResultV1,
)
from insurance_harness.goldenset.schema67_quality_metrics_596_1 import (
    Schema67MetricBBoxV1,
    Schema67MetricEvidenceV1,
    Schema67MetricRowV1,
    Schema67QualityMetricsV1,
)
from insurance_harness.goldenset.schema67_quality_metrics_consumer_596_1 import (
    Schema67QualityMetricsConsumerError,
    compute_admitted_schema67_quality_metrics_596_1,
)
from insurance_harness.goldenset.schema67_reviewed_golden_successor_596_1 import (
    Schema67ReviewedGoldenSuccessor5961V1,
)
from tests.test_schema67_golden_quality_gate_596_1 import (
    _evaluate,
    _golden,
    _non_fixture_candidate_and_authority,
)

_CURRENT = (
    Path(__file__).parents[2]
    / "dataset/goldenset-drafts/schema67-reviewed-golden-successor-596-1/golden67-successor.json"
)
_A = "a" * 64
_B = "b" * 64
_C = "c" * 64


def _current() -> Schema67ReviewedGoldenSuccessor5961V1:
    return Schema67ReviewedGoldenSuccessor5961V1.model_validate(
        json.loads(_CURRENT.read_bytes())
    )


def _formal() -> Schema67GoldenEvaluationResultV1:
    candidate, authority = _non_fixture_candidate_and_authority()
    return cast(
        Schema67GoldenEvaluationResultV1,
        _evaluate(
            candidate=candidate,
            authority=authority,
            golden=_golden(candidate, authority),
        ),
    )


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


def test_current_51_16_unverified_successor_blocks_before_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def forbidden(rows: Sequence[Schema67MetricRowV1]) -> Schema67QualityMetricsV1:
        nonlocal calls
        calls += 1
        raise AssertionError(rows)

    monkeypatch.setattr(consumer_module, "_compute_metrics", forbidden)
    current = _current()
    assert current.schema67_mapping_status == "PARTIAL_51_CLOSED_16_RESIDUAL"
    assert current.golden_admission_status == "BLOCKED_RESIDUALS_AND_RECEIPT_UNVERIFIED"

    with pytest.raises(Schema67QualityMetricsConsumerError, match="GOLDEN_ADMISSION_BLOCKED"):
        compute_admitted_schema67_quality_metrics_596_1(admission=current, rows=())

    assert calls == 0


def test_registered_formal_pass_calls_pure_metrics_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    formal = _formal()
    rows = _rows(formal)
    original = consumer_module._compute_metrics
    calls = 0

    def counted(
        exact_rows: Sequence[Schema67MetricRowV1],
    ) -> Schema67QualityMetricsV1:
        nonlocal calls
        calls += 1
        return original(exact_rows)

    monkeypatch.setattr(consumer_module, "_compute_metrics", counted)
    result = compute_admitted_schema67_quality_metrics_596_1(admission=formal, rows=rows)

    assert calls == 1
    assert result.evaluated_field_count == 67
    assert formal.provider_calls == formal.draft_calls == formal.review_calls == 0
    assert formal.activation_calls == 0


def test_reparsed_self_consistent_pass_result_is_not_a_registered_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    formal = _formal()
    reparsed = Schema67GoldenEvaluationResultV1.model_validate(formal.model_dump(mode="python"))
    calls = 0

    def forbidden(rows: Sequence[Schema67MetricRowV1]) -> Schema67QualityMetricsV1:
        nonlocal calls
        calls += 1
        raise AssertionError(rows)

    monkeypatch.setattr(consumer_module, "_compute_metrics", forbidden)
    with pytest.raises(Schema67QualityMetricsConsumerError, match="GOLDEN_ADMISSION_INVALID"):
        compute_admitted_schema67_quality_metrics_596_1(admission=reparsed, rows=_rows(formal))
    assert calls == 0
