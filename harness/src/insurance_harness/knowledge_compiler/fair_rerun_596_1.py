"""Task-local fair weak/strong rerun boundary for Product 596-1."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from pydantic import ValidationError

from insurance_harness.canonical import canonical_hash
from insurance_harness.knowledge_compiler import vertical_falsification as vf
from insurance_harness.knowledge_compiler import weak_strong_ceiling as ceiling
from insurance_harness.knowledge_compiler.field_contracts_596_1 import (
    FieldContractAuthorityRequestV1,
    FieldContractUserReceiptV1,
    NamedHumanAuthorityV1,
    evaluate_field_contract_authority,
)
from insurance_harness.knowledge_compiler.semantic_input_binding import (
    SemanticInputCompositionV1,
    SharedSemanticTaskBlueprintV1,
)

FAIR_RERUN_CONTRACT: Final[str] = "596-1-fair-weak-strong-rerun.v1"
_APPROVED_PLAN_OBJECT_TYPE: Final[str] = "ceiling-596-1-approved-task-plan.v1"
_PAIR_RECEIPT_OBJECT_TYPE: Final[str] = "fair-rerun-frozen-pair-596-1.v1"

RunStatus = Literal[
    "BLOCKED_ON_FIELD_CONTRACT_AUTHORITY",
    "BLOCKED_ON_FAIR_RERUN_CONTRACT",
    "ARM_EXECUTION_FAILED",
    "OUTPUTS_FROZEN_FOR_049_SCORING",
]
ScoreAuthority = Literal["SCORED", "UNADMITTED_RAW"]


@dataclass(frozen=True, slots=True)
class FairRerunResultV1:
    status: RunStatus
    reason_codes: tuple[str, ...]
    weak_calls: int
    strong_calls: int
    golden_reads: Literal[0] = 0
    authority_subject_sha256: str | None = None
    authority_receipt_sha256: str | None = None
    composition_hash: str | None = None
    weak_output: vf.FrozenArmOutputV1 | None = None
    strong_output: vf.FrozenArmOutputV1 | None = None
    weak_score_authority: ScoreAuthority | None = None
    strong_score_authority: ScoreAuthority | None = None
    pair_receipt_sha256: str | None = None


ArmExecutor = Callable[
    [SemanticInputCompositionV1, vf.ArmInputIdentityV1],
    tuple[vf.ArmFieldOutputV1, ...],
]


def _blocked(
    status: RunStatus,
    reason: str,
    *,
    weak_calls: int = 0,
    strong_calls: int = 0,
    subject: str | None = None,
    receipt: str | None = None,
    composition_hash: str | None = None,
    weak_output: vf.FrozenArmOutputV1 | None = None,
) -> FairRerunResultV1:
    return FairRerunResultV1(
        status=status,
        reason_codes=(reason,),
        weak_calls=weak_calls,
        strong_calls=strong_calls,
        authority_subject_sha256=subject,
        authority_receipt_sha256=receipt,
        composition_hash=composition_hash,
        weak_output=weak_output,
    )


def _task_projection(
    tasks: tuple[SharedSemanticTaskBlueprintV1, ...],
) -> tuple[dict[str, object], ...]:
    names = (
        "task_id",
        "task_kind",
        "material_role",
        "module_id",
        "risk_partition_id",
        "field_ids",
        "source_sha256",
    )
    return tuple({name: getattr(task, name) for name in names} for task in tasks)


def _task_plan_sha256(composition: SemanticInputCompositionV1) -> str:
    first, second = composition.arm_blueprints
    tasks = _task_projection(first.tasks)
    if tasks != _task_projection(second.tasks):
        raise ValueError("SHARED_TASK_PLAN_MISMATCH")
    return canonical_hash(
        _APPROVED_PLAN_OBJECT_TYPE,
        {
            "contract_id": "596-1-approved-shared-task-plan.v1",
            "product_version_id": composition.product_version_id,
            "schema_version": first.schema_version,
            "schema_sha256": composition.schema_sha256,
            "source_sha256": tuple(item.source_sha256 for item in composition.sources),
            "material_profile_catalog_hash": composition.material_profile_catalog_hash,
            "tasks": tasks,
        },
    )


def _exact_composition(value: object) -> SemanticInputCompositionV1:
    if not isinstance(value, SemanticInputCompositionV1):
        raise ValueError("SEMANTIC_COMPOSITION_MALFORMED")
    try:
        composition = SemanticInputCompositionV1.model_validate(
            value.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise ValueError("SEMANTIC_COMPOSITION_MALFORMED") from None
    if (
        composition.product_version_id != vf.APPROVED_PRODUCT_VERSION_ID
        or composition.schema_sha256 != vf.APPROVED_SCHEMA_REGISTRY_SHA256
        or composition.material_profile_catalog_hash
        != vf.APPROVED_MATERIAL_PROFILE_CATALOG_SHA256
        or tuple(item.source_sha256 for item in composition.sources)
        != vf.APPROVED_596_1_SOURCE_SHA256
        or _task_plan_sha256(composition)
        != ceiling.APPROVED_SHARED_TASK_PLAN_SHA256
    ):
        raise ValueError("FAIR_RERUN_SHARED_INPUT_MISMATCH")
    weak, strong = (item.execution_identity for item in composition.arm_blueprints)
    shared_names = (
        "prompt_contract_id",
        "prompt_template_sha256",
        "budget_identity_sha256",
        "normalizer_identity_sha256",
        "output_contract_id",
        "output_contract_identity_sha256",
    )
    shared = all(getattr(weak, name) == getattr(strong, name) for name in shared_names)
    exact = (
        weak.model_id == vf.APPROVED_SEMANTIC_MODEL_ID
        and weak.model_identity_sha256 == vf.APPROVED_SEMANTIC_MODEL_IDENTITY_SHA256
        and strong.model_id == ceiling.STRONG_MODEL_ID
        and strong.model_identity_sha256
        == ceiling.APPROVED_STRONG_MODEL_IDENTITY_SHA256
        and weak.prompt_template_sha256 == vf.APPROVED_PROMPT_IDENTITY_SHA256
        and weak.budget_identity_sha256 == vf.APPROVED_BUDGET_IDENTITY_SHA256
        and weak.normalizer_identity_sha256 == vf.APPROVED_NORMALIZER_IDENTITY_SHA256
    )
    if not shared or not exact:
        raise ValueError("FAIR_RERUN_EXECUTION_IDENTITY_MISMATCH")
    return composition


def _arm_identities(
    composition: SemanticInputCompositionV1,
    weak: object,
    strong: object,
) -> tuple[vf.ArmInputIdentityV1, vf.ArmInputIdentityV1]:
    if type(weak) is not vf.ArmInputIdentityV1 or type(strong) is not vf.ArmInputIdentityV1:
        raise ValueError("FAIR_RERUN_ARM_IDENTITY_MALFORMED")
    weak_identity = weak
    strong_identity = strong
    shared_names = (
        "product_version_id",
        "source_sha256",
        "schema_version",
        "schema_sha256",
        "parser_identity_sha256",
        "prompt_identity_sha256",
        "budget_identity_sha256",
        "normalizer_identity_sha256",
        "comparator_identity_sha256",
        "arm_profile_sha256",
        "parse_artifact_receipt_digest_sha256",
        "parser_id",
        "parser_mode",
        "parser_attempt",
    )
    if any(getattr(weak_identity, name) != getattr(strong_identity, name) for name in shared_names):
        raise ValueError("FAIR_RERUN_ARM_IDENTITY_DRIFT")
    exact_shared = (
        weak_identity.product_version_id == vf.APPROVED_PRODUCT_VERSION_ID
        and weak_identity.source_sha256 == vf.APPROVED_596_1_SOURCE_SHA256
        and weak_identity.schema_version == vf.APPROVED_SCHEMA_VERSION
        and weak_identity.schema_sha256 == vf.APPROVED_SCHEMA_REGISTRY_SHA256
        and weak_identity.prompt_identity_sha256 == vf.APPROVED_PROMPT_IDENTITY_SHA256
        and weak_identity.budget_identity_sha256 == vf.APPROVED_BUDGET_IDENTITY_SHA256
        and weak_identity.normalizer_identity_sha256
        == vf.APPROVED_NORMALIZER_IDENTITY_SHA256
        and weak_identity.comparator_identity_sha256
        == vf.APPROVED_COMPARATOR_IDENTITY_SHA256
        and weak_identity.arm_profile_sha256
        == ceiling.APPROVED_SHARED_TASK_PLAN_SHA256
        and weak_identity.parse_artifact_receipt_digest_sha256
        == composition.admission_receipt_digest_sha256
    )
    exact_models = (
        weak_identity.semantic_model_id == vf.APPROVED_SEMANTIC_MODEL_ID
        and weak_identity.semantic_api_base == vf.APPROVED_SEMANTIC_API_BASE
        and weak_identity.model_identity_sha256
        == vf.APPROVED_SEMANTIC_MODEL_IDENTITY_SHA256
        and strong_identity.semantic_model_id == ceiling.STRONG_MODEL_ID
        and strong_identity.semantic_api_base == ceiling.STRONG_EXECUTION_SURFACE
        and strong_identity.model_identity_sha256
        == ceiling.APPROVED_STRONG_MODEL_IDENTITY_SHA256
    )
    if not exact_shared or not exact_models:
        raise ValueError("FAIR_RERUN_ARM_IDENTITY_MISMATCH")
    return weak_identity, strong_identity


def _freeze_once(
    *,
    label: Literal["WEAK", "STRONG"],
    arm: Literal["baseline", "candidate"],
    execute: ArmExecutor,
    composition: SemanticInputCompositionV1,
    identity: vf.ArmInputIdentityV1,
) -> tuple[vf.FrozenArmOutputV1 | None, str | None, bool]:
    try:
        value = execute(composition, identity)
    except Exception:
        return None, f"{label}_ARM_EXECUTION_FAILED", True
    if type(value) is not tuple or any(type(item) is not vf.ArmFieldOutputV1 for item in value):
        return None, f"{label}_OUTPUT_FIELD_SET_MISMATCH", False
    if tuple(item.field_id for item in value) != vf.APPROVED_SCHEMA60_FIELD_IDS:
        return None, f"{label}_OUTPUT_FIELD_SET_MISMATCH", False
    frozen = vf.freeze_arm_output(arm=arm, identity=identity, fields=value)
    if not vf.verify_arm_output_hash(frozen):
        return None, f"{label}_OUTPUT_HASH_MISMATCH", False
    return frozen, None, False


def run_596_1_fair_rerun(
    *,
    composition: object,
    authority_request: FieldContractAuthorityRequestV1,
    user_receipt: FieldContractUserReceiptV1 | None,
    authority: NamedHumanAuthorityV1,
    now: datetime,
    weak_identity: object,
    strong_identity: object,
    weak_execute: ArmExecutor,
    strong_execute: ArmExecutor,
) -> FairRerunResultV1:
    """Invoke two fixed seams once each and freeze outputs before any Golden read."""

    gate = evaluate_field_contract_authority(
        request=authority_request,
        receipt=user_receipt,
        authority=authority,
        now=now,
    )
    if gate.status != "FIELD_CONTRACT_AUTHORITY_VERIFIED":
        return _blocked(
            "BLOCKED_ON_FIELD_CONTRACT_AUTHORITY",
            gate.reason_codes[0],
            subject=gate.subject_sha256,
        )
    assert gate.subject_sha256 is not None and gate.receipt_sha256 is not None
    try:
        exact_composition = _exact_composition(composition)
        weak_arm, strong_arm = _arm_identities(
            exact_composition, weak_identity, strong_identity
        )
    except ValueError as error:
        return _blocked(
            "BLOCKED_ON_FAIR_RERUN_CONTRACT",
            str(error),
            subject=gate.subject_sha256,
            receipt=gate.receipt_sha256,
        )
    weak_output, reason, execution_failed = _freeze_once(
        label="WEAK",
        arm="baseline",
        execute=weak_execute,
        composition=exact_composition,
        identity=weak_arm,
    )
    if reason is not None:
        return _blocked(
            "ARM_EXECUTION_FAILED" if execution_failed else "BLOCKED_ON_FAIR_RERUN_CONTRACT",
            reason,
            weak_calls=1,
            subject=gate.subject_sha256,
            receipt=gate.receipt_sha256,
            composition_hash=exact_composition.composition_hash,
        )
    assert weak_output is not None
    strong_output, reason, execution_failed = _freeze_once(
        label="STRONG",
        arm="candidate",
        execute=strong_execute,
        composition=exact_composition,
        identity=strong_arm,
    )
    if reason is not None:
        return _blocked(
            "ARM_EXECUTION_FAILED" if execution_failed else "BLOCKED_ON_FAIR_RERUN_CONTRACT",
            reason,
            weak_calls=1,
            strong_calls=1,
            weak_output=weak_output,
            subject=gate.subject_sha256,
            receipt=gate.receipt_sha256,
            composition_hash=exact_composition.composition_hash,
        )
    assert strong_output is not None
    pair_receipt = canonical_hash(
        _PAIR_RECEIPT_OBJECT_TYPE,
        {
            "contract": FAIR_RERUN_CONTRACT,
            "field_contract_subject_sha256": gate.subject_sha256,
            "field_contract_receipt_sha256": gate.receipt_sha256,
            "composition_hash": exact_composition.composition_hash,
            "task_plan_sha256": ceiling.APPROVED_SHARED_TASK_PLAN_SHA256,
            "weak_output_hash": weak_output.output_hash,
            "strong_output_hash": strong_output.output_hash,
            "weak_score_authority": "SCORED",
            "strong_score_authority": "UNADMITTED_RAW",
        },
    )
    return FairRerunResultV1(
        status="OUTPUTS_FROZEN_FOR_049_SCORING",
        reason_codes=(),
        weak_calls=1,
        strong_calls=1,
        authority_subject_sha256=gate.subject_sha256,
        authority_receipt_sha256=gate.receipt_sha256,
        composition_hash=exact_composition.composition_hash,
        weak_output=weak_output,
        strong_output=strong_output,
        weak_score_authority="SCORED",
        strong_score_authority="UNADMITTED_RAW",
        pair_receipt_sha256=pair_receipt,
    )


__all__ = ["FAIR_RERUN_CONTRACT", "FairRerunResultV1", "run_596_1_fair_rerun"]
