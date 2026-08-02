"""Provider-free 596-1 weak/strong quality-ceiling comparison."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final, Literal

from insurance_harness.canonical import canonical_hash
from insurance_harness.knowledge_compiler import vertical_falsification as vf

WEAK_MODEL_ID: Final[str] = "DeepSeek V4 Flash"
STRONG_MODEL_ID: Final[str] = "gpt-5.6-sol"
STRONG_EXECUTION_SURFACE: Final[str] = "offline-codex-strong-ceiling"
STRONG_EXECUTION_RECEIPT_CONTRACT: Final[str] = (
    "596-1-offline-codex-strong-execution.v1"
)
STRONG_EXECUTION_RECEIPT_OBJECT_TYPE: Final[str] = (
    "strong-execution-receipt-596-1.v1"
)
APPROVED_SHARED_TASK_PLAN_SHA256: Final[str] = (
    "08c7d9e4e6c11e68d8ad54f25a2bb3e92fb3040ce24f30dc69e579634bb994fc"
)
APPROVED_STRONG_MODEL_IDENTITY_SHA256: Final[str] = canonical_hash(
    "ceiling-596-1-strong-model-identity.v1",
    {
        "execution_surface": STRONG_EXECUTION_SURFACE,
        "model_id": STRONG_MODEL_ID,
    },
)
_COMPARISON_OBJECT_TYPE: Final[str] = "ceiling-596-1-comparison.v1"

_APPROVED_TASK_PARTITIONS: Final = (
    (
        "069:596-1-terms-semantic-01",
        "semantic",
        "terms",
        "596-1-terms-semantic-01",
        "terms-semantic-01",
        (
            "clause_version",
            "regulatory_filing_no",
            "zh_0c5a8e59e2",
            "zh_1ec5e3f2cc",
            "zh_313cabffd8",
            "zh_a271d96039",
            "zh_b4b770e114",
            "zh_d62301d84c",
            "zh_f558f0a88f",
            "zh_fd9a0b9fa3",
        ),
        vf.APPROVED_596_1_SOURCE_SHA256[0],
    ),
    (
        "069:596-1-terms-semantic-02",
        "semantic",
        "terms",
        "596-1-terms-semantic-02",
        "terms-semantic-02",
        (
            "claim_filing_requirements",
            "clause_effective_date",
            "exclusions_official",
            "reduced_paid_up",
            "reinstatement",
            "waiting_period_claim_handling",
            "zh_09a5d9e54e",
            "zh_14b93ce275",
            "zh_17a83223e4",
            "zh_7d7fe38f09",
        ),
        vf.APPROVED_596_1_SOURCE_SHA256[0],
    ),
    (
        "069:596-1-terms-semantic-03",
        "semantic",
        "terms",
        "596-1-terms-semantic-03",
        "terms-semantic-03",
        (
            "zh_0612362268",
            "zh_2df7d6256c",
            "zh_3a3e6520a3",
            "zh_4a789b1d6f",
            "zh_74aa1b9c93",
            "zh_74fd5a9469",
            "zh_c5187f228e",
            "zh_ca6e0226c2",
        ),
        vf.APPROVED_596_1_SOURCE_SHA256[0],
    ),
    (
        "069:596-1-terms-semantic-04",
        "semantic",
        "terms",
        "596-1-terms-semantic-04",
        "terms-semantic-04",
        (
            "discontinuation_renewal",
            "external_drug_coverage",
            "pre_existing_conditions",
            "zh_3d8424595d",
            "zh_52548821b9",
            "zh_e1bea0527a",
            "zh_f32c510a5e",
            "zh_f8cc996739",
        ),
        vf.APPROVED_596_1_SOURCE_SHA256[0],
    ),
    (
        "069:596-1-brochure-semantic-01",
        "semantic",
        "brochure",
        "596-1-brochure-semantic-01",
        "brochure-semantic-01",
        (
            "zh_0b3894ed2a",
            "zh_1a3227c6ce",
            "zh_789479e2d4",
            "zh_8bd90889d3",
            "zh_ad4a95859a",
            "zh_f1de0de938",
        ),
        vf.APPROVED_596_1_SOURCE_SHA256[1],
    ),
    (
        "069:596-1-brochure-semantic-02",
        "semantic",
        "brochure",
        "596-1-brochure-semantic-02",
        "brochure-semantic-02",
        (
            "zh_346f0dac8c",
            "zh_5162df17d8",
            "zh_67ee7025ef",
            "zh_6a3bd6cdbf",
            "zh_89e518b987",
        ),
        vf.APPROVED_596_1_SOURCE_SHA256[1],
    ),
    (
        "069:596-1-brochure-semantic-03",
        "semantic",
        "brochure",
        "596-1-brochure-semantic-03",
        "brochure-semantic-03",
        (
            "zh_1a5675a37a",
            "zh_540e1969e3",
            "zh_7598a3116c",
            "zh_b7ceabc3c0",
            "zh_c4f4b0d48a",
        ),
        vf.APPROVED_596_1_SOURCE_SHA256[1],
    ),
    (
        "069:596-1-brochure-semantic-04",
        "semantic",
        "brochure",
        "596-1-brochure-semantic-04",
        "brochure-semantic-04",
        (
            "zh_17e15e0c5a",
            "zh_23a2625781",
            "zh_58d313ee26",
            "zh_7bf05bc576",
            "zh_a17bd1c3f3",
            "zh_dcae594f8b",
        ),
        vf.APPROVED_596_1_SOURCE_SHA256[1],
    ),
    (
        "069:596-1-rate-deterministic-01",
        "deterministic_rate",
        "rate_table",
        "596-1-rate-deterministic-01",
        "rate-numeric-01",
        ("zh_7fe8603c08",),
        vf.APPROVED_596_1_SOURCE_SHA256[2],
    ),
    (
        "069:596-1-rate-deterministic-02",
        "deterministic_rate",
        "rate_table",
        "596-1-rate-deterministic-02",
        "rate-numeric-02",
        ("zh_c588207763",),
        vf.APPROVED_596_1_SOURCE_SHA256[2],
    ),
)


def _approved_task_plan_payload() -> dict[str, object]:
    tasks = tuple(
        {
            "task_id": task_id,
            "task_kind": task_kind,
            "material_role": material_role,
            "module_id": module_id,
            "risk_partition_id": risk_partition_id,
            "field_ids": field_ids,
            "source_sha256": source_sha256,
        }
        for (
            task_id,
            task_kind,
            material_role,
            module_id,
            risk_partition_id,
            field_ids,
            source_sha256,
        ) in _APPROVED_TASK_PARTITIONS
    )
    return {
        "contract_id": "596-1-approved-shared-task-plan.v1",
        "product_version_id": vf.APPROVED_PRODUCT_VERSION_ID,
        "schema_version": vf.APPROVED_SCHEMA_VERSION,
        "schema_sha256": vf.APPROVED_SCHEMA_REGISTRY_SHA256,
        "source_sha256": vf.APPROVED_596_1_SOURCE_SHA256,
        "material_profile_catalog_hash": (
            "32651266dcef2c6597b35911906b3d64408bc9c0cabe2db52472f836d519d019"
        ),
        "tasks": tasks,
    }


if canonical_hash(
    "ceiling-596-1-approved-task-plan.v1", _approved_task_plan_payload()
) != APPROVED_SHARED_TASK_PLAN_SHA256:
    raise RuntimeError("APPROVED_SHARED_TASK_PLAN_PREIMAGE_DRIFT")


@dataclass(frozen=True, slots=True)
class CeilingModelIdentityV1:
    model_id: str
    api_base: str
    identity_sha256: str


@dataclass(frozen=True, slots=True)
class StrongExecutionReceiptV1:
    """Externally issued receipt for one frozen offline strong-model execution."""

    contract_id: str
    execution_surface: str
    model_id: str
    run_identity_sha256: str
    input_identity_sha256: str
    task_plan_sha256: str
    model_identity_sha256: str
    prompt_identity_sha256: str
    budget_identity_sha256: str
    frozen_output_hash: str
    receipt_hash: str


@dataclass(frozen=True, slots=True)
class CeilingFieldDeltaV1:
    field_id: str
    critical_priority: Literal["P0", "P1"] | None
    rate_field: bool
    weak_tri_state_correct: bool
    strong_tri_state_correct: bool
    weak_exact_field_correct: bool
    strong_exact_field_correct: bool
    weak_known_evidence_present: bool
    strong_known_evidence_present: bool
    weak_rate_locator_complete: bool | None
    strong_rate_locator_complete: bool | None
    comparison: Literal[
        "STRONG_BETTER",
        "WEAK_BETTER",
        "TIED_CORRECT",
        "TIED_INCORRECT",
    ]


@dataclass(frozen=True, slots=True)
class CeilingAggregateDeltaV1:
    tri_state_correct: int = 0
    normalized_value_correct: int = 0
    exact_field_correct: int = 0
    abstentions: int = 0
    misses: int = 0
    hallucinations: int = 0
    wrong_values: int = 0
    known_with_evidence: int = 0
    critical_known_with_evidence: int = 0
    critical_silent_errors: int = 0
    critical_semantic_errors: int = 0
    tri_state_correct_basis_points: int = 0
    normalized_value_correct_basis_points: int = 0
    abstention_basis_points: int = 0
    known_evidence_basis_points: int = 0


@dataclass(frozen=True, slots=True)
class WeakStrongCeilingComparisonV1:
    status: Literal["COMPARED", "BLOCKED_ON_REQUIRED_CONTRACTS", "GOLDEN_INVALID"]
    reason_codes: tuple[str, ...]
    weak_output_hash: str | None
    strong_output_hash: str | None
    weak_model: CeilingModelIdentityV1 | None
    strong_model: CeilingModelIdentityV1 | None
    shared_input_identity_sha256: str | None
    strong_execution_receipt_hash: str | None
    strong_run_identity_sha256: str | None
    weak_score_receipt_hash: str | None
    strong_score_receipt_hash: str | None
    admission_receipt_digest_sha256: str | None
    golden_content_digest_sha256: str | None
    evaluator_identity_sha256: str
    field_deltas: tuple[CeilingFieldDeltaV1, ...]
    aggregate_delta: CeilingAggregateDeltaV1
    comparison_receipt_hash: str = ""

    def __post_init__(self) -> None:
        payload = {
            key: value
            for key, value in asdict(self).items()
            if key != "comparison_receipt_hash"
        }
        object.__setattr__(
            self,
            "comparison_receipt_hash",
            canonical_hash(_COMPARISON_OBJECT_TYPE, payload),
        )


def _model_identity(identity: vf.ArmInputIdentityV1) -> CeilingModelIdentityV1:
    return CeilingModelIdentityV1(
        model_id=identity.semantic_model_id,
        api_base=identity.semantic_api_base,
        identity_sha256=identity.model_identity_sha256,
    )


def _is_sha256(value: object) -> bool:
    if type(value) is not str or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _is_placeholder_sha256(value: str) -> bool:
    return len(set(value)) <= 1


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


def _strong_execution_receipt_payload(
    receipt: StrongExecutionReceiptV1,
) -> dict[str, object]:
    return {
        "contract_id": receipt.contract_id,
        "execution_surface": receipt.execution_surface,
        "model_id": receipt.model_id,
        "run_identity_sha256": receipt.run_identity_sha256,
        "input_identity_sha256": receipt.input_identity_sha256,
        "task_plan_sha256": receipt.task_plan_sha256,
        "model_identity_sha256": receipt.model_identity_sha256,
        "prompt_identity_sha256": receipt.prompt_identity_sha256,
        "budget_identity_sha256": receipt.budget_identity_sha256,
        "frozen_output_hash": receipt.frozen_output_hash,
    }


def _validate_strong_execution_receipt(
    *,
    value: object,
    weak: vf.FrozenArmOutputV1,
    strong: vf.FrozenArmOutputV1,
) -> tuple[StrongExecutionReceiptV1 | None, tuple[str, ...]]:
    if value is None:
        return None, ("STRONG_EXECUTION_RECEIPT_MISSING",)
    if type(value) is not StrongExecutionReceiptV1:
        return None, ("STRONG_EXECUTION_RECEIPT_MALFORMED",)
    receipt = value
    scalar_values = tuple(_strong_execution_receipt_payload(receipt).values()) + (
        receipt.receipt_hash,
    )
    if any(type(item) is not str for item in scalar_values):
        return None, ("STRONG_EXECUTION_RECEIPT_MALFORMED",)
    hashes = (
        receipt.run_identity_sha256,
        receipt.input_identity_sha256,
        receipt.task_plan_sha256,
        receipt.model_identity_sha256,
        receipt.prompt_identity_sha256,
        receipt.budget_identity_sha256,
        receipt.frozen_output_hash,
        receipt.receipt_hash,
    )
    expected_input_hash = canonical_hash(
        "ceiling-596-1-shared-input.v1",
        _shared_identity_payload(weak.identity),
    )
    expected_receipt_hash = canonical_hash(
        STRONG_EXECUTION_RECEIPT_OBJECT_TYPE,
        _strong_execution_receipt_payload(receipt),
    )
    if (
        any(not _is_sha256(value) for value in hashes)
        or _is_placeholder_sha256(receipt.run_identity_sha256)
        or receipt.contract_id != STRONG_EXECUTION_RECEIPT_CONTRACT
        or receipt.execution_surface != STRONG_EXECUTION_SURFACE
        or receipt.model_id != STRONG_MODEL_ID
        or receipt.input_identity_sha256 != expected_input_hash
        or receipt.task_plan_sha256 != APPROVED_SHARED_TASK_PLAN_SHA256
        or receipt.model_identity_sha256
        != APPROVED_STRONG_MODEL_IDENTITY_SHA256
        or receipt.model_identity_sha256 != strong.identity.model_identity_sha256
        or receipt.prompt_identity_sha256
        != strong.identity.prompt_identity_sha256
        or receipt.budget_identity_sha256
        != strong.identity.budget_identity_sha256
        or receipt.frozen_output_hash != strong.output_hash
        or receipt.receipt_hash != expected_receipt_hash
    ):
        return None, ("STRONG_EXECUTION_RECEIPT_BINDING_MISMATCH",)
    return receipt, ()


def _blocked(
    *,
    status: Literal["BLOCKED_ON_REQUIRED_CONTRACTS", "GOLDEN_INVALID"],
    reason_codes: tuple[str, ...],
) -> WeakStrongCeilingComparisonV1:
    return WeakStrongCeilingComparisonV1(
        status=status,
        reason_codes=reason_codes,
        weak_output_hash=None,
        strong_output_hash=None,
        weak_model=None,
        strong_model=None,
        shared_input_identity_sha256=None,
        strong_execution_receipt_hash=None,
        strong_run_identity_sha256=None,
        weak_score_receipt_hash=None,
        strong_score_receipt_hash=None,
        admission_receipt_digest_sha256=None,
        golden_content_digest_sha256=None,
        evaluator_identity_sha256=vf.APPROVED_EVALUATOR_IDENTITY_SHA256,
        field_deltas=(),
        aggregate_delta=CeilingAggregateDeltaV1(),
    )


def _validated_output(
    value: object,
    *,
    role: Literal["WEAK", "STRONG"],
) -> tuple[vf.FrozenArmOutputV1 | None, tuple[str, ...]]:
    if type(value) is not vf.FrozenArmOutputV1:
        return None, (f"{role}_OUTPUT_MALFORMED",)
    output = value
    try:
        if not vf.verify_arm_output_hash(output):
            return None, (f"{role}_OUTPUT_HASH_MISMATCH",)
        if output.arm != "candidate":
            return None, (f"{role}_ARM_ROLE_MISMATCH",)
        if tuple(field.field_id for field in output.fields) != (
            vf.APPROVED_SCHEMA60_FIELD_IDS
        ):
            return None, ("SHARED_INPUT_IDENTITY_MISMATCH",)
    except Exception:
        return None, (f"{role}_OUTPUT_MALFORMED",)
    return output, ()


def _pre_golden_outputs(
    *,
    weak_output: object,
    strong_output: object,
    strong_execution_receipt: object,
) -> tuple[
    vf.FrozenArmOutputV1 | None,
    vf.FrozenArmOutputV1 | None,
    StrongExecutionReceiptV1 | None,
    tuple[str, ...],
]:
    weak, weak_reasons = _validated_output(weak_output, role="WEAK")
    strong, strong_reasons = _validated_output(strong_output, role="STRONG")
    reasons = [*weak_reasons, *strong_reasons]
    if weak is None or strong is None:
        return weak, strong, None, tuple(dict.fromkeys(reasons))
    if _shared_identity_payload(weak.identity) != _shared_identity_payload(
        strong.identity
    ) or tuple(field.field_id for field in weak.fields) != tuple(
        field.field_id for field in strong.fields
    ):
        reasons.append("SHARED_INPUT_IDENTITY_MISMATCH")
    if (
        weak.identity.semantic_model_id != WEAK_MODEL_ID
        or weak.identity.semantic_api_base != vf.APPROVED_SEMANTIC_API_BASE
        or weak.identity.model_identity_sha256
        != vf.APPROVED_SEMANTIC_MODEL_IDENTITY_SHA256
    ):
        reasons.append("WEAK_MODEL_IDENTITY_MISMATCH")
    if (
        strong.identity.semantic_model_id != STRONG_MODEL_ID
        or strong.identity.semantic_api_base != STRONG_EXECUTION_SURFACE
        or strong.identity.model_identity_sha256
        != APPROVED_STRONG_MODEL_IDENTITY_SHA256
    ):
        reasons.append("STRONG_MODEL_IDENTITY_MISMATCH")
    if (
        weak.identity.arm_profile_sha256 != APPROVED_SHARED_TASK_PLAN_SHA256
        or strong.identity.arm_profile_sha256 != APPROVED_SHARED_TASK_PLAN_SHA256
    ):
        reasons.append("SHARED_TASK_PLAN_IDENTITY_MISMATCH")
    if (
        weak.identity.model_identity_sha256
        == strong.identity.model_identity_sha256
    ):
        reasons.append("MODEL_IDENTITY_NOT_DISTINCT")
    receipt, receipt_reasons = _validate_strong_execution_receipt(
        value=strong_execution_receipt,
        weak=weak,
        strong=strong,
    )
    reasons.extend(receipt_reasons)
    return weak, strong, receipt, tuple(dict.fromkeys(reasons))


def _field_comparison(
    *,
    weak: vf.ArmFieldCorrectnessV1,
    strong: vf.ArmFieldCorrectnessV1,
) -> CeilingFieldDeltaV1:
    comparison: Literal[
        "STRONG_BETTER",
        "WEAK_BETTER",
        "TIED_CORRECT",
        "TIED_INCORRECT",
    ]
    if strong.exact_field_correct and not weak.exact_field_correct:
        comparison = "STRONG_BETTER"
    elif weak.exact_field_correct and not strong.exact_field_correct:
        comparison = "WEAK_BETTER"
    elif weak.exact_field_correct:
        comparison = "TIED_CORRECT"
    else:
        comparison = "TIED_INCORRECT"
    return CeilingFieldDeltaV1(
        field_id=weak.field_id,
        critical_priority=weak.critical_priority,
        rate_field=weak.rate_field,
        weak_tri_state_correct=weak.tri_state_correct,
        strong_tri_state_correct=strong.tri_state_correct,
        weak_exact_field_correct=weak.exact_field_correct,
        strong_exact_field_correct=strong.exact_field_correct,
        weak_known_evidence_present=weak.known_evidence_present,
        strong_known_evidence_present=strong.known_evidence_present,
        weak_rate_locator_complete=weak.rate_locator_complete,
        strong_rate_locator_complete=strong.rate_locator_complete,
        comparison=comparison,
    )


def _aggregate_delta(
    *,
    weak: vf.ArmQualityMetricsV1,
    strong: vf.ArmQualityMetricsV1,
) -> CeilingAggregateDeltaV1:
    return CeilingAggregateDeltaV1(
        tri_state_correct=strong.tri_state_correct - weak.tri_state_correct,
        normalized_value_correct=(
            strong.normalized_value_correct - weak.normalized_value_correct
        ),
        exact_field_correct=strong.exact_field_correct - weak.exact_field_correct,
        abstentions=strong.abstentions - weak.abstentions,
        misses=strong.misses - weak.misses,
        hallucinations=strong.hallucinations - weak.hallucinations,
        wrong_values=strong.wrong_values - weak.wrong_values,
        known_with_evidence=(strong.known_with_evidence - weak.known_with_evidence),
        critical_known_with_evidence=(
            strong.critical_known_with_evidence - weak.critical_known_with_evidence
        ),
        critical_silent_errors=(
            strong.critical_silent_errors - weak.critical_silent_errors
        ),
        critical_semantic_errors=(
            strong.critical_semantic_errors - weak.critical_semantic_errors
        ),
        tri_state_correct_basis_points=(
            strong.tri_state_correct_basis_points
            - weak.tri_state_correct_basis_points
        ),
        normalized_value_correct_basis_points=(
            strong.normalized_value_correct_basis_points
            - weak.normalized_value_correct_basis_points
        ),
        abstention_basis_points=(
            strong.abstention_basis_points - weak.abstention_basis_points
        ),
        known_evidence_basis_points=(
            strong.known_evidence_basis_points - weak.known_evidence_basis_points
        ),
    )


def _build_ceiling_comparison_from_scores(
    *,
    weak_score: vf.AdmittedFrozenArmScoreV1,
    strong_score: vf.AdmittedFrozenArmScoreV1,
    strong_execution_receipt: StrongExecutionReceiptV1,
) -> WeakStrongCeilingComparisonV1:
    if weak_score.status == "GOLDEN_INVALID" or strong_score.status == "GOLDEN_INVALID":
        return _blocked(
            status="GOLDEN_INVALID",
            reason_codes=("GOLDEN_596_BYTES_INVALID",),
        )
    if weak_score.status != "SCORED" or strong_score.status != "UNADMITTED_RAW":
        return _blocked(
            status="BLOCKED_ON_REQUIRED_CONTRACTS",
            reason_codes=("PUBLIC_SINGLE_ARM_SCORE_BLOCKED",),
        )
    weak_identity = weak_score.arm_identity
    strong_identity = strong_score.arm_identity
    if weak_identity is None or strong_identity is None:
        return _blocked(
            status="BLOCKED_ON_REQUIRED_CONTRACTS",
            reason_codes=("PUBLIC_SINGLE_ARM_SCORE_IDENTITY_MISSING",),
        )
    if (
        weak_identity.semantic_model_id != WEAK_MODEL_ID
        or strong_identity.semantic_model_id != STRONG_MODEL_ID
        or _shared_identity_payload(weak_identity)
        != _shared_identity_payload(strong_identity)
        or tuple(item.field_id for item in weak_score.field_correctness)
        != vf.APPROVED_SCHEMA60_FIELD_IDS
        or tuple(item.field_id for item in strong_score.field_correctness)
        != vf.APPROVED_SCHEMA60_FIELD_IDS
    ):
        return _blocked(
            status="BLOCKED_ON_REQUIRED_CONTRACTS",
            reason_codes=("PUBLIC_SINGLE_ARM_SCORE_BINDING_MISMATCH",),
        )
    field_deltas: list[CeilingFieldDeltaV1] = []
    for weak, strong in zip(
        weak_score.field_correctness,
        strong_score.field_correctness,
        strict=True,
    ):
        if (
            weak.field_id != strong.field_id
            or weak.critical_priority != strong.critical_priority
            or weak.rate_field != strong.rate_field
        ):
            return _blocked(
                status="BLOCKED_ON_REQUIRED_CONTRACTS",
                reason_codes=("PUBLIC_SINGLE_ARM_SCORE_BINDING_MISMATCH",),
            )
        field_deltas.append(_field_comparison(weak=weak, strong=strong))
    shared_payload = _shared_identity_payload(weak_identity)
    return WeakStrongCeilingComparisonV1(
        status="COMPARED",
        reason_codes=tuple(
            dict.fromkeys((*weak_score.reason_codes, *strong_score.reason_codes))
        ),
        weak_output_hash=weak_score.output_hash,
        strong_output_hash=strong_score.output_hash,
        weak_model=_model_identity(weak_identity),
        strong_model=_model_identity(strong_identity),
        shared_input_identity_sha256=canonical_hash(
            "ceiling-596-1-shared-input.v1", shared_payload
        ),
        strong_execution_receipt_hash=strong_execution_receipt.receipt_hash,
        strong_run_identity_sha256=strong_execution_receipt.run_identity_sha256,
        weak_score_receipt_hash=weak_score.score_receipt_hash,
        strong_score_receipt_hash=strong_score.score_receipt_hash,
        admission_receipt_digest_sha256=(
            weak_score.admission_receipt_digest_sha256
        ),
        golden_content_digest_sha256=weak_score.golden_content_digest_sha256,
        evaluator_identity_sha256=weak_score.evaluator_identity_sha256,
        field_deltas=tuple(field_deltas),
        aggregate_delta=_aggregate_delta(
            weak=weak_score.metrics,
            strong=strong_score.metrics,
        ),
    )


def compare_596_1_weak_strong_ceiling(
    *,
    weak_output: object,
    strong_output: object,
    strong_execution_receipt: object,
    golden_596_jsonl_bytes: object,
    admitted_parse_artifacts: tuple[vf.AdmittedParseArtifactV1, ...],
) -> WeakStrongCeilingComparisonV1:
    """Compare two already-frozen outputs without running either model."""

    weak, strong, receipt, reasons = _pre_golden_outputs(
        weak_output=weak_output,
        strong_output=strong_output,
        strong_execution_receipt=strong_execution_receipt,
    )
    if weak is None or strong is None or receipt is None or reasons:
        return _blocked(
            status="BLOCKED_ON_REQUIRED_CONTRACTS",
            reason_codes=reasons or ("ARM_OUTPUT_MALFORMED",),
        )
    weak_score = vf.score_admitted_frozen_arm(
        arm_output=weak,
        golden_596_jsonl_bytes=golden_596_jsonl_bytes,
        admitted_parse_artifacts=admitted_parse_artifacts,
    )
    strong_score = vf.score_admitted_frozen_arm(
        arm_output=strong,
        golden_596_jsonl_bytes=golden_596_jsonl_bytes,
        admitted_parse_artifacts=admitted_parse_artifacts,
    )
    if (
        weak_score.output_hash != weak.output_hash
        or strong_score.output_hash != strong.output_hash
        or weak_score.arm_identity != weak.identity
        or strong_score.arm_identity != strong.identity
    ):
        return _blocked(
            status="BLOCKED_ON_REQUIRED_CONTRACTS",
            reason_codes=("PUBLIC_SCORE_OUTPUT_BINDING_MISMATCH",),
        )
    weak_custody = (
        weak_score.admission_receipt_digest_sha256,
        weak_score.golden_release_hash,
        weak_score.golden_artifact_hash,
        weak_score.golden_approval_subject_hash,
        weak_score.golden_596_jsonl_sha256,
        weak_score.golden_content_digest_sha256,
        weak_score.evaluator_identity_sha256,
    )
    strong_custody = (
        strong_score.admission_receipt_digest_sha256,
        strong_score.golden_release_hash,
        strong_score.golden_artifact_hash,
        strong_score.golden_approval_subject_hash,
        strong_score.golden_596_jsonl_sha256,
        strong_score.golden_content_digest_sha256,
        strong_score.evaluator_identity_sha256,
    )
    if weak_custody != strong_custody:
        return _blocked(
            status="BLOCKED_ON_REQUIRED_CONTRACTS",
            reason_codes=("PUBLIC_SCORE_CUSTODY_MISMATCH",),
        )
    return _build_ceiling_comparison_from_scores(
        weak_score=weak_score,
        strong_score=strong_score,
        strong_execution_receipt=receipt,
    )


__all__ = [
    "CeilingAggregateDeltaV1",
    "CeilingFieldDeltaV1",
    "CeilingModelIdentityV1",
    "APPROVED_SHARED_TASK_PLAN_SHA256",
    "APPROVED_STRONG_MODEL_IDENTITY_SHA256",
    "STRONG_MODEL_ID",
    "STRONG_EXECUTION_RECEIPT_CONTRACT",
    "STRONG_EXECUTION_RECEIPT_OBJECT_TYPE",
    "STRONG_EXECUTION_SURFACE",
    "StrongExecutionReceiptV1",
    "WEAK_MODEL_ID",
    "WeakStrongCeilingComparisonV1",
    "compare_596_1_weak_strong_ceiling",
]
