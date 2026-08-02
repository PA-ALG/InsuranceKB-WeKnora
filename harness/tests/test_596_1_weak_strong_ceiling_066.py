from __future__ import annotations

import json
from dataclasses import asdict, replace
from typing import Literal, cast

import pytest

from insurance_harness.canonical import canonical_hash
from insurance_harness.knowledge_compiler import vertical_falsification as vf
from insurance_harness.knowledge_compiler import weak_strong_ceiling as ceiling

_GOLDEN_BYTES = b"exact-approved-golden-placeholder"
_ADMISSION_DIGEST = "a" * 64


def _shared_identity_payload(identity: vf.ArmInputIdentityV1) -> dict[str, object]:
    return {
        "product_version_id": identity.product_version_id,
        "source_sha256": identity.source_sha256,
        "schema_version": identity.schema_version,
        "schema_sha256": identity.schema_sha256,
        "parser_identity_sha256": identity.parser_identity_sha256,
        "prompt_identity_sha256": identity.prompt_identity_sha256,
        "budget_identity_sha256": identity.budget_identity_sha256,
        "normalizer_identity_sha256": identity.normalizer_identity_sha256,
        "comparator_identity_sha256": identity.comparator_identity_sha256,
        "arm_profile_sha256": identity.arm_profile_sha256,
        "parse_artifact_receipt_digest_sha256": (
            identity.parse_artifact_receipt_digest_sha256
        ),
        "parser_id": identity.parser_id,
        "parser_mode": identity.parser_mode,
        "parser_attempt": identity.parser_attempt,
    }


def _identity(
    *,
    role: Literal["weak", "strong"],
) -> vf.ArmInputIdentityV1:
    return vf.ArmInputIdentityV1(
        product_version_id=vf.APPROVED_PRODUCT_VERSION_ID,
        source_sha256=vf.APPROVED_596_1_SOURCE_SHA256,
        schema_version=vf.APPROVED_SCHEMA_VERSION,
        schema_sha256=vf.APPROVED_SCHEMA_REGISTRY_SHA256,
        parser_identity_sha256=vf.APPROVED_CANDIDATE_PARSER_IDENTITY_SHA256,
        model_identity_sha256=(
            vf.APPROVED_SEMANTIC_MODEL_IDENTITY_SHA256
            if role == "weak"
            else ceiling.APPROVED_STRONG_MODEL_IDENTITY_SHA256
        ),
        semantic_model_id=(
            vf.APPROVED_SEMANTIC_MODEL_ID
            if role == "weak"
            else ceiling.STRONG_MODEL_ID
        ),
        semantic_api_base=(
            vf.APPROVED_SEMANTIC_API_BASE
            if role == "weak"
            else ceiling.STRONG_EXECUTION_SURFACE
        ),
        prompt_identity_sha256=vf.APPROVED_PROMPT_IDENTITY_SHA256,
        budget_identity_sha256=vf.APPROVED_BUDGET_IDENTITY_SHA256,
        normalizer_identity_sha256=vf.APPROVED_NORMALIZER_IDENTITY_SHA256,
        comparator_identity_sha256=vf.APPROVED_COMPARATOR_IDENTITY_SHA256,
        arm_profile_sha256=ceiling.APPROVED_SHARED_TASK_PLAN_SHA256,
        parse_artifact_receipt_digest_sha256=_ADMISSION_DIGEST,
        parser_id="mineru-cloud-pipeline",
        parser_mode="bounded_upgrade",
        parser_attempt=2,
    )


def _evidence() -> tuple[vf.EvidenceLocatorV1, ...]:
    return (
        vf.EvidenceLocatorV1(
            source_sha256=vf.APPROVED_596_1_SOURCE_SHA256[0],
            quote_snapshot="synthetic quote",
            page_number=1,
            block_id="block-1",
        ),
    )


def _fields() -> tuple[vf.ArmFieldOutputV1, ...]:
    return tuple(
        vf.ArmFieldOutputV1(
            field_id=field_id,
            state="present",
            value_snapshot=f"synthetic-{index}",
            evidence=_evidence(),
        )
        for index, field_id in enumerate(vf.APPROVED_SCHEMA60_FIELD_IDS)
    )


def _output(role: Literal["weak", "strong"]) -> vf.FrozenArmOutputV1:
    return vf.freeze_arm_output(
        arm="candidate",
        identity=_identity(role=role),
        fields=_fields(),
    )


def _strong_receipt(
    strong_output: vf.FrozenArmOutputV1,
    *,
    weak_output: vf.FrozenArmOutputV1 | None = None,
    execution_surface: str = ceiling.STRONG_EXECUTION_SURFACE,
    run_identity_sha256: str | None = None,
    receipt_hash: str | None = None,
) -> ceiling.StrongExecutionReceiptV1:
    weak = weak_output or _output("weak")
    payload = {
        "contract_id": ceiling.STRONG_EXECUTION_RECEIPT_CONTRACT,
        "execution_surface": execution_surface,
        "model_id": ceiling.STRONG_MODEL_ID,
        "run_identity_sha256": run_identity_sha256
        or canonical_hash("test-066-strong-run.v1", {"run": "strong-1"}),
        "input_identity_sha256": canonical_hash(
            "ceiling-596-1-shared-input.v1",
            _shared_identity_payload(weak.identity),
        ),
        "task_plan_sha256": ceiling.APPROVED_SHARED_TASK_PLAN_SHA256,
        "model_identity_sha256": strong_output.identity.model_identity_sha256,
        "prompt_identity_sha256": strong_output.identity.prompt_identity_sha256,
        "budget_identity_sha256": strong_output.identity.budget_identity_sha256,
        "frozen_output_hash": strong_output.output_hash,
    }
    return ceiling.StrongExecutionReceiptV1(
        **payload,
        receipt_hash=receipt_hash
        or canonical_hash(ceiling.STRONG_EXECUTION_RECEIPT_OBJECT_TYPE, payload),
    )


def _metrics(*, strong: bool) -> vf.ArmQualityMetricsV1:
    exact = 59 if strong else 57
    return vf.ArmQualityMetricsV1(
        denominator=60,
        critical_denominator=18,
        tri_state_correct=exact,
        normalized_value_denominator=42,
        normalized_value_correct=41 if strong else 39,
        abstentions=1,
        misses=0,
        hallucinations=0,
        wrong_values=1 if strong else 3,
        exact_field_correct=exact,
        known_denominator=42,
        known_with_evidence=42,
        critical_known_denominator=18,
        critical_known_with_evidence=18,
        critical_silent_errors=0,
        critical_semantic_errors=0 if strong else 1,
        tri_state_correct_basis_points=9833 if strong else 9500,
        normalized_value_correct_basis_points=9761 if strong else 9285,
        abstention_basis_points=166,
        known_evidence_basis_points=10000,
    )


def _score(
    *,
    role: Literal["weak", "strong"],
    status: Literal["SCORED", "GOLDEN_INVALID"] = "SCORED",
) -> vf.AdmittedFrozenArmScoreV1:
    output = _output(role)
    strong = role == "strong"
    correctness = tuple(
        vf.ArmFieldCorrectnessV1(
            field_id=field_id,
            critical_priority=None,
            rate_field=False,
            tri_state_correct=strong or index != 0,
            exact_field_correct=strong or index != 0,
            known_evidence_present=True,
            rate_locator_complete=None,
        )
        for index, field_id in enumerate(vf.APPROVED_SCHEMA60_FIELD_IDS)
    )
    return vf.AdmittedFrozenArmScoreV1(
        status=status,
        reason_codes=(() if status == "SCORED" else ("GOLDEN_596_BYTES_INVALID",)),
        metrics=_metrics(strong=strong),
        field_correctness=(correctness if status == "SCORED" else ()),
        output_hash=output.output_hash,
        arm_identity=output.identity,
        admission_receipt_digest_sha256=_ADMISSION_DIGEST,
        golden_content_digest_sha256=("b" * 64 if status == "SCORED" else None),
    )


def _install_scorer(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status: Literal["SCORED", "GOLDEN_INVALID"] = "SCORED",
) -> list[tuple[object, object]]:
    calls: list[tuple[object, object]] = []

    def _fake(**kwargs: object) -> vf.AdmittedFrozenArmScoreV1:
        output = kwargs["arm_output"]
        calls.append((output, kwargs["golden_596_jsonl_bytes"]))
        assert isinstance(output, vf.FrozenArmOutputV1)
        role: Literal["weak", "strong"] = (
            "weak"
            if output.identity.semantic_model_id == vf.APPROVED_SEMANTIC_MODEL_ID
            else "strong"
        )
        return _score(role=role, status=status)

    monkeypatch.setattr(vf, "score_admitted_frozen_arm", _fake)
    return calls


def test_blocks_both_scorers_when_either_output_hash_is_not_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_scorer(monkeypatch)
    strong = replace(_output("strong"), output_hash="f" * 64)

    result = ceiling.compare_596_1_weak_strong_ceiling(
        weak_output=_output("weak"),
        strong_output=strong,
        strong_execution_receipt=_strong_receipt(strong),
        golden_596_jsonl_bytes=_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert result.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert result.reason_codes == ("STRONG_OUTPUT_HASH_MISMATCH",)
    assert calls == []
    assert result.field_deltas == ()


@pytest.mark.parametrize(
    "mutation",
    ("prompt", "budget", "parser", "schema", "artifact", "field_order"),
)
def test_shared_non_model_drift_blocks_before_scorer(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    calls = _install_scorer(monkeypatch)
    strong = _output("strong")
    if mutation == "field_order":
        strong = vf.freeze_arm_output(
            arm="candidate",
            identity=strong.identity,
            fields=tuple(reversed(strong.fields)),
        )
    else:
        identity = strong.identity
        if mutation == "prompt":
            identity = replace(identity, prompt_identity_sha256="1" * 64)
        elif mutation == "budget":
            identity = replace(identity, budget_identity_sha256="2" * 64)
        elif mutation == "parser":
            identity = replace(identity, parser_identity_sha256="3" * 64)
        elif mutation == "schema":
            identity = replace(identity, schema_sha256="4" * 64)
        else:
            identity = replace(
                identity,
                parse_artifact_receipt_digest_sha256="5" * 64,
            )
        strong = vf.freeze_arm_output(
            arm="candidate",
            identity=identity,
            fields=strong.fields,
        )

    result = ceiling.compare_596_1_weak_strong_ceiling(
        weak_output=_output("weak"),
        strong_output=strong,
        strong_execution_receipt=_strong_receipt(strong),
        golden_596_jsonl_bytes=_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert result.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert "SHARED_INPUT_IDENTITY_MISMATCH" in result.reason_codes
    assert calls == []


def test_requires_exact_weak_and_strong_model_roles_before_scorer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_scorer(monkeypatch)
    strong = _output("strong")
    strong = vf.freeze_arm_output(
        arm="candidate",
        identity=replace(strong.identity, semantic_model_id="GPT-5.6-sol"),
        fields=strong.fields,
    )

    result = ceiling.compare_596_1_weak_strong_ceiling(
        weak_output=_output("weak"),
        strong_output=strong,
        strong_execution_receipt=_strong_receipt(strong),
        golden_596_jsonl_bytes=_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert result.reason_codes == ("STRONG_MODEL_IDENTITY_MISMATCH",)
    assert calls == []


def test_missing_external_strong_execution_receipt_blocks_before_scorer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_scorer(monkeypatch)

    result = ceiling.compare_596_1_weak_strong_ceiling(
        weak_output=_output("weak"),
        strong_output=_output("strong"),
        strong_execution_receipt=None,
        golden_596_jsonl_bytes=_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert result.reason_codes == ("STRONG_EXECUTION_RECEIPT_MISSING",)
    assert calls == []


def test_non_string_receipt_hash_field_is_typed_malformed_before_scorer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_scorer(monkeypatch)
    weak = _output("weak")
    strong = _output("strong")
    receipt = _strong_receipt(strong, weak_output=weak)
    object.__setattr__(receipt, "run_identity_sha256", cast(str, object()))

    result = ceiling.compare_596_1_weak_strong_ceiling(
        weak_output=weak,
        strong_output=strong,
        strong_execution_receipt=receipt,
        golden_596_jsonl_bytes=_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert result.reason_codes == ("STRONG_EXECUTION_RECEIPT_MALFORMED",)
    assert calls == []


@pytest.mark.parametrize(
    "mutation", ("surface", "receipt_hash", "model_hash", "run_placeholder")
)
def test_foreign_or_forged_strong_execution_receipt_blocks_before_scorer(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    calls = _install_scorer(monkeypatch)
    weak = _output("weak")
    strong = _output("strong")
    if mutation == "model_hash":
        strong = vf.freeze_arm_output(
            arm="candidate",
            identity=replace(
                strong.identity,
                model_identity_sha256=canonical_hash(
                    "foreign-strong-model.v1", {"model": "gpt-5.6-sol"}
                ),
            ),
            fields=strong.fields,
        )
    receipt = _strong_receipt(
        strong,
        weak_output=weak,
        execution_surface=(
            "deepseek-online" if mutation == "surface" else ceiling.STRONG_EXECUTION_SURFACE
        ),
        run_identity_sha256=("0" * 64 if mutation == "run_placeholder" else None),
        receipt_hash=("f" * 64 if mutation == "receipt_hash" else None),
    )

    result = ceiling.compare_596_1_weak_strong_ceiling(
        weak_output=weak,
        strong_output=strong,
        strong_execution_receipt=receipt,
        golden_596_jsonl_bytes=_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert result.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert calls == []


def test_both_arms_using_same_foreign_task_plan_blocks_before_scorer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_scorer(monkeypatch)
    foreign_plan = canonical_hash(
        "foreign-shared-task-plan.v1", {"tasks": "same-but-unapproved"}
    )
    weak_source = _output("weak")
    strong_source = _output("strong")
    weak = vf.freeze_arm_output(
        arm="candidate",
        identity=replace(weak_source.identity, arm_profile_sha256=foreign_plan),
        fields=weak_source.fields,
    )
    strong = vf.freeze_arm_output(
        arm="candidate",
        identity=replace(strong_source.identity, arm_profile_sha256=foreign_plan),
        fields=strong_source.fields,
    )

    result = ceiling.compare_596_1_weak_strong_ceiling(
        weak_output=weak,
        strong_output=strong,
        strong_execution_receipt=_strong_receipt(strong, weak_output=weak),
        golden_596_jsonl_bytes=_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert result.reason_codes == ("SHARED_TASK_PLAN_IDENTITY_MISMATCH",)
    assert calls == []


@pytest.mark.parametrize("mutation", ("api_base", "identity_hash"))
def test_weak_model_requires_exact_approved_identity_before_scorer(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    calls = _install_scorer(monkeypatch)
    weak = _output("weak")
    identity = (
        replace(weak.identity, semantic_api_base="https://foreign.invalid/v1")
        if mutation == "api_base"
        else replace(weak.identity, model_identity_sha256="7" * 64)
    )
    weak = vf.freeze_arm_output(
        arm="candidate",
        identity=identity,
        fields=weak.fields,
    )

    strong = _output("strong")
    result = ceiling.compare_596_1_weak_strong_ceiling(
        weak_output=weak,
        strong_output=strong,
        strong_execution_receipt=_strong_receipt(strong, weak_output=weak),
        golden_596_jsonl_bytes=_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert result.reason_codes == ("WEAK_MODEL_IDENTITY_MISMATCH",)
    assert calls == []


def test_scores_both_only_after_hash_freeze_and_emits_answer_safe_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_scorer(monkeypatch)

    weak = _output("weak")
    strong = _output("strong")
    result = ceiling.compare_596_1_weak_strong_ceiling(
        weak_output=weak,
        strong_output=strong,
        strong_execution_receipt=_strong_receipt(strong, weak_output=weak),
        golden_596_jsonl_bytes=_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert result.status == "COMPARED"
    assert len(calls) == 2
    assert calls[0][1] is calls[1][1] is _GOLDEN_BYTES
    assert len(result.field_deltas) == 60
    assert result.field_deltas[0].comparison == "STRONG_BETTER"
    assert result.aggregate_delta.exact_field_correct == 2
    assert result.aggregate_delta.critical_semantic_errors == -1
    serialized = json.dumps(asdict(result), sort_keys=True)
    for forbidden in (
        "expected_value",
        "expected_state",
        "value_snapshot",
        "quote_snapshot",
        "synthetic-0",
        "reasoning",
    ):
        assert forbidden not in serialized
    assert len(result.comparison_receipt_hash) == 64


def test_golden_invalid_from_public_scorers_produces_no_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_scorer(monkeypatch, status="GOLDEN_INVALID")

    weak = _output("weak")
    strong = _output("strong")
    result = ceiling.compare_596_1_weak_strong_ceiling(
        weak_output=weak,
        strong_output=strong,
        strong_execution_receipt=_strong_receipt(strong, weak_output=weak),
        golden_596_jsonl_bytes=_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert len(calls) == 2
    assert result.status == "GOLDEN_INVALID"
    assert result.field_deltas == ()


def test_public_scores_must_replay_the_prevalidated_output_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake(**kwargs: object) -> vf.AdmittedFrozenArmScoreV1:
        output = kwargs["arm_output"]
        assert isinstance(output, vf.FrozenArmOutputV1)
        role: Literal["weak", "strong"] = (
            "weak"
            if output.identity.semantic_model_id == vf.APPROVED_SEMANTIC_MODEL_ID
            else "strong"
        )
        score = _score(role=role)
        return replace(score, output_hash="e" * 64) if role == "strong" else score

    monkeypatch.setattr(vf, "score_admitted_frozen_arm", _fake)

    weak = _output("weak")
    strong = _output("strong")
    result = ceiling.compare_596_1_weak_strong_ceiling(
        weak_output=weak,
        strong_output=strong,
        strong_execution_receipt=_strong_receipt(strong, weak_output=weak),
        golden_596_jsonl_bytes=_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert result.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert result.reason_codes == ("PUBLIC_SCORE_OUTPUT_BINDING_MISMATCH",)
    assert result.field_deltas == ()


def test_score_only_comparison_builder_is_not_a_public_authority() -> None:
    assert not hasattr(ceiling, "build_ceiling_comparison_from_scores")


def test_public_score_custody_must_match_between_arms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake(**kwargs: object) -> vf.AdmittedFrozenArmScoreV1:
        output = kwargs["arm_output"]
        assert isinstance(output, vf.FrozenArmOutputV1)
        role: Literal["weak", "strong"] = (
            "weak"
            if output.identity.semantic_model_id == vf.APPROVED_SEMANTIC_MODEL_ID
            else "strong"
        )
        score = _score(role=role)
        return (
            replace(score, golden_content_digest_sha256="c" * 64)
            if role == "strong"
            else score
        )

    monkeypatch.setattr(vf, "score_admitted_frozen_arm", _fake)

    weak = _output("weak")
    strong = _output("strong")
    result = ceiling.compare_596_1_weak_strong_ceiling(
        weak_output=weak,
        strong_output=strong,
        strong_execution_receipt=_strong_receipt(strong, weak_output=weak),
        golden_596_jsonl_bytes=_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert result.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert result.reason_codes == ("PUBLIC_SCORE_CUSTODY_MISMATCH",)
    assert result.field_deltas == ()


def test_model_identity_changes_comparison_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake(**kwargs: object) -> vf.AdmittedFrozenArmScoreV1:
        output = kwargs["arm_output"]
        assert isinstance(output, vf.FrozenArmOutputV1)
        role: Literal["weak", "strong"] = (
            "weak"
            if output.identity.semantic_model_id == vf.APPROVED_SEMANTIC_MODEL_ID
            else "strong"
        )
        return replace(
            _score(role=role),
            output_hash=output.output_hash,
            arm_identity=output.identity,
        )

    monkeypatch.setattr(vf, "score_admitted_frozen_arm", _fake)
    weak = _output("weak")
    strong = _output("strong")
    first = ceiling.compare_596_1_weak_strong_ceiling(
        weak_output=weak,
        strong_output=strong,
        strong_execution_receipt=_strong_receipt(strong, weak_output=weak),
        golden_596_jsonl_bytes=_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )
    second = ceiling.compare_596_1_weak_strong_ceiling(
        weak_output=weak,
        strong_output=strong,
        strong_execution_receipt=_strong_receipt(
            strong,
            weak_output=weak,
            run_identity_sha256=canonical_hash(
                "test-066-strong-run.v1", {"run": "strong-2"}
            ),
        ),
        golden_596_jsonl_bytes=_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert first.field_deltas == second.field_deltas
    assert first.comparison_receipt_hash != second.comparison_receipt_hash
