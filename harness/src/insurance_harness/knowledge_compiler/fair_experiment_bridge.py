"""Executable, Golden-blind bridge from the 074 fair rerun to 066 scoring."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Final, Literal, Protocol, TypeGuard, cast

from pydantic import SecretStr

from insurance_harness.canonical import CanonicalEncodingError, canonical_hash
from insurance_harness.knowledge_compiler import fair_rerun_596_1 as fair
from insurance_harness.knowledge_compiler import vertical_falsification as vf
from insurance_harness.knowledge_compiler import weak_strong_ceiling as ceiling
from insurance_harness.knowledge_compiler.field_contracts_596_1 import (
    FieldContractAuthorityRequestV1,
    FieldContractUserReceiptV1,
    NamedHumanAuthorityV1,
)
from insurance_harness.knowledge_compiler.semantic_input_binding import (
    SemanticInputCompositionV1,
)

_TRANSPORT_CONTRACT: Final[str] = "fair-experiment-arm-execution.v1"
_TRANSPORT_OBJECT_TYPE: Final[str] = "fair-experiment-arm-execution-receipt.v1"
_SUBMISSION_OBJECT_TYPE: Final[str] = "fair-experiment-arm-submission.v1"
_SEAL_CONTRACT: Final[str] = "fair-experiment-executable-bridge.v1"
_SEAL_OBJECT_TYPE: Final[str] = "sealed-fair-experiment-596-1.v1"

Role = Literal["weak", "strong"]


@dataclass(frozen=True, slots=True)
class ArmExecutionSubmissionV1:
    role: Role
    composition_hash: str
    composition: SemanticInputCompositionV1
    input_identity_sha256: str
    identity: vf.ArmInputIdentityV1
    submission_hash: str


@dataclass(frozen=True, slots=True)
class ArmExecutionTransportReceiptV1:
    contract_id: str
    role: Role
    composition_hash: str
    submission_hash: str
    input_identity_sha256: str
    task_plan_sha256: str
    model_id: str
    model_identity_sha256: str
    execution_surface: str
    prompt_identity_sha256: str
    budget_identity_sha256: str
    frozen_output_hash: str
    run_identity_sha256: str
    receipt_hash: str


@dataclass(frozen=True, slots=True)
class ArmExecutionTransportResultV1:
    fields: tuple[vf.ArmFieldOutputV1, ...]
    receipt: ArmExecutionTransportReceiptV1
    strong_execution_receipt: ceiling.StrongExecutionReceiptV1 | None = None


class ArmTransportPort(Protocol):
    def submit(
        self,
        submission: ArmExecutionSubmissionV1,
        *,
        authorization: SecretStr,
    ) -> ArmExecutionTransportResultV1: ...


class GoldenBytesPort(Protocol):
    def load(self) -> bytes: ...


@dataclass(frozen=True, slots=True)
class SealedFairExperimentV1:
    contract_id: str
    composition: SemanticInputCompositionV1
    authority_request: FieldContractAuthorityRequestV1
    user_receipt: FieldContractUserReceiptV1
    authority: NamedHumanAuthorityV1
    now: datetime
    weak_identity: vf.ArmInputIdentityV1
    strong_identity: vf.ArmInputIdentityV1
    fair_rerun_result: fair.FairRerunResultV1
    composition_hash: str
    field_contract_subject_sha256: str
    field_contract_receipt_sha256: str
    pair_receipt_sha256: str
    weak_074_output_hash: str
    strong_074_output_hash: str
    weak_output: vf.FrozenArmOutputV1
    strong_output: vf.FrozenArmOutputV1
    weak_transport_receipt: ArmExecutionTransportReceiptV1
    strong_transport_receipt: ArmExecutionTransportReceiptV1
    strong_execution_receipt: ceiling.StrongExecutionReceiptV1
    weak_authority: Literal["SCORED"]
    strong_authority: Literal["UNADMITTED_RAW"]
    seal_sha256: str


ExecutionStatus = Literal[
    "BLOCKED_ON_AUTHORIZATION",
    "BLOCKED_ON_FAIR_RERUN_CONTRACT",
    "BLOCKED_ON_TRANSPORT_RECEIPT",
    "ARM_EXECUTION_FAILED",
    "OUTPUTS_SEALED_FOR_066_SCORING",
]


@dataclass(frozen=True, slots=True)
class FairExperimentExecutionResultV1:
    status: ExecutionStatus
    reason_codes: tuple[str, ...]
    transport_calls: int
    golden_reads: Literal[0] = 0
    sealed_experiment: SealedFairExperimentV1 | None = None


ScoreStatus = Literal[
    "COMPARED",
    "BLOCKED_ON_FROZEN_EXPERIMENT",
    "BLOCKED_ON_REQUIRED_CONTRACTS",
    "GOLDEN_INVALID",
    "GOLDEN_LOAD_FAILED",
]


@dataclass(frozen=True, slots=True)
class FairExperimentScoreResultV1:
    status: ScoreStatus
    reason_codes: tuple[str, ...]
    golden_reads: Literal[0, 1]
    comparison: ceiling.WeakStrongCeilingComparisonV1 | None = None


def _hash_payload(
    value: ArmExecutionTransportReceiptV1, *, exclude: str
) -> dict[str, object]:
    payload = cast(dict[str, object], asdict(value))
    payload.pop(exclude)
    return payload


def transport_execution_receipt_sha256(
    receipt: ArmExecutionTransportReceiptV1,
) -> str:
    return canonical_hash(
        _TRANSPORT_OBJECT_TYPE,
        _hash_payload(receipt, exclude="receipt_hash"),
    )


def _shared_payload(identity: vf.ArmInputIdentityV1) -> dict[str, object]:
    payload = asdict(identity)
    for name in ("model_identity_sha256", "semantic_model_id", "semantic_api_base"):
        payload.pop(name)
    return payload


def _input_hash(identity: vf.ArmInputIdentityV1) -> str:
    return canonical_hash("fair-experiment-shared-input.v1", _shared_payload(identity))


def _submission(
    role: Role,
    composition: SemanticInputCompositionV1,
    identity: vf.ArmInputIdentityV1,
) -> ArmExecutionSubmissionV1:
    input_hash = _input_hash(identity)
    payload = {
        "role": role,
        "composition": composition.model_dump(mode="python"),
        "input_identity_sha256": input_hash,
        "task_plan_sha256": ceiling.APPROVED_SHARED_TASK_PLAN_SHA256,
        "model_id": identity.semantic_model_id,
        "model_identity_sha256": identity.model_identity_sha256,
        "execution_surface": identity.semantic_api_base,
        "prompt_identity_sha256": identity.prompt_identity_sha256,
        "budget_identity_sha256": identity.budget_identity_sha256,
        "frozen_arm": "candidate",
    }
    return ArmExecutionSubmissionV1(
        role=role,
        composition_hash=composition.composition_hash,
        composition=composition,
        input_identity_sha256=input_hash,
        identity=identity,
        submission_hash=canonical_hash(_SUBMISSION_OBJECT_TYPE, payload),
    )


def _is_sha(value: object) -> bool:
    if type(value) is not str or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _identities_exact(
    weak: object,
    strong: object,
) -> bool:
    if type(weak) is not vf.ArmInputIdentityV1 or type(strong) is not vf.ArmInputIdentityV1:
        return False
    if _shared_payload(weak) != _shared_payload(strong):
        return False
    return (
        weak.product_version_id == vf.APPROVED_PRODUCT_VERSION_ID
        and weak.source_sha256 == vf.APPROVED_596_1_SOURCE_SHA256
        and weak.schema_version == vf.APPROVED_SCHEMA_VERSION
        and weak.schema_sha256 == vf.APPROVED_SCHEMA_REGISTRY_SHA256
        and weak.parser_identity_sha256 == vf.APPROVED_CANDIDATE_PARSER_IDENTITY_SHA256
        and (weak.parser_id, weak.parser_mode, weak.parser_attempt)
        == ("mineru-cloud-pipeline", "bounded_upgrade", 2)
        and weak.prompt_identity_sha256 == vf.APPROVED_PROMPT_IDENTITY_SHA256
        and weak.budget_identity_sha256 == vf.APPROVED_BUDGET_IDENTITY_SHA256
        and weak.normalizer_identity_sha256 == vf.APPROVED_NORMALIZER_IDENTITY_SHA256
        and weak.comparator_identity_sha256 == vf.APPROVED_COMPARATOR_IDENTITY_SHA256
        and weak.arm_profile_sha256 == ceiling.APPROVED_SHARED_TASK_PLAN_SHA256
        and weak.semantic_model_id == vf.APPROVED_SEMANTIC_MODEL_ID
        and weak.semantic_api_base == vf.APPROVED_SEMANTIC_API_BASE
        and weak.model_identity_sha256 == vf.APPROVED_SEMANTIC_MODEL_IDENTITY_SHA256
        and strong.semantic_model_id == ceiling.STRONG_MODEL_ID
        and strong.semantic_api_base == ceiling.STRONG_EXECUTION_SURFACE
        and strong.model_identity_sha256 == ceiling.APPROVED_STRONG_MODEL_IDENTITY_SHA256
    )


def _receipt_exact(
    value: object,
    submission: ArmExecutionSubmissionV1,
    fields: tuple[vf.ArmFieldOutputV1, ...],
) -> bool:
    if type(value) is not ArmExecutionTransportReceiptV1:
        return False
    receipt = value
    try:
        output = vf.freeze_arm_output(
            arm="candidate", identity=submission.identity, fields=fields
        )
        return (
            receipt.contract_id == _TRANSPORT_CONTRACT
            and receipt.role == submission.role
            and receipt.composition_hash == submission.composition_hash
            and receipt.submission_hash == submission.submission_hash
            and receipt.input_identity_sha256 == submission.input_identity_sha256
            and receipt.task_plan_sha256 == ceiling.APPROVED_SHARED_TASK_PLAN_SHA256
            and receipt.model_id == submission.identity.semantic_model_id
            and receipt.model_identity_sha256 == submission.identity.model_identity_sha256
            and receipt.execution_surface == submission.identity.semantic_api_base
            and receipt.prompt_identity_sha256
            == submission.identity.prompt_identity_sha256
            and receipt.budget_identity_sha256
            == submission.identity.budget_identity_sha256
            and receipt.frozen_output_hash == output.output_hash
            and _is_sha(receipt.run_identity_sha256)
            and len(set(receipt.run_identity_sha256)) > 1
            and _is_sha(receipt.receipt_hash)
            and receipt.receipt_hash == transport_execution_receipt_sha256(receipt)
        )
    except Exception:
        return False


def _strong_receipt_scalars_well_formed(
    receipt: ceiling.StrongExecutionReceiptV1,
) -> bool:
    names = (
        "contract_id",
        "execution_surface",
        "model_id",
        "run_identity_sha256",
        "input_identity_sha256",
        "task_plan_sha256",
        "model_identity_sha256",
        "prompt_identity_sha256",
        "budget_identity_sha256",
        "frozen_output_hash",
        "receipt_hash",
    )
    return all(type(getattr(receipt, name)) is str for name in names)


def _seal_payload(sealed: SealedFairExperimentV1) -> dict[str, object]:
    return {
        "contract_id": sealed.contract_id,
        "composition": sealed.composition.model_dump(mode="python"),
        "authority_request": asdict(sealed.authority_request),
        "user_receipt": asdict(sealed.user_receipt),
        "authority": {
            "principal_id": sealed.authority.principal_id,
            "display_name": sealed.authority.display_name,
            "signer_key_id": sealed.authority.signer_key_id,
            "public_key_hex": sealed.authority.public_key.public_bytes_raw().hex(),
        },
        "now": sealed.now,
        "weak_identity": asdict(sealed.weak_identity),
        "strong_identity": asdict(sealed.strong_identity),
        "fair_rerun_result": asdict(sealed.fair_rerun_result),
        "composition_hash": sealed.composition_hash,
        "field_contract_subject_sha256": sealed.field_contract_subject_sha256,
        "field_contract_receipt_sha256": sealed.field_contract_receipt_sha256,
        "pair_receipt_sha256": sealed.pair_receipt_sha256,
        "weak_074_output_hash": sealed.weak_074_output_hash,
        "strong_074_output_hash": sealed.strong_074_output_hash,
        "weak_output": asdict(sealed.weak_output),
        "strong_output": asdict(sealed.strong_output),
        "weak_transport_receipt": asdict(sealed.weak_transport_receipt),
        "strong_transport_receipt": asdict(sealed.strong_transport_receipt),
        "strong_execution_receipt": asdict(sealed.strong_execution_receipt),
        "weak_authority": sealed.weak_authority,
        "strong_authority": sealed.strong_authority,
    }


def _seal_hash(sealed: SealedFairExperimentV1) -> str:
    return canonical_hash(_SEAL_OBJECT_TYPE, _seal_payload(sealed))


def _blocked_execution(
    status: ExecutionStatus,
    reason: str,
    calls: int = 0,
) -> FairExperimentExecutionResultV1:
    return FairExperimentExecutionResultV1(
        status=status,
        reason_codes=(reason,),
        transport_calls=calls,
    )


def execute_and_freeze(
    *,
    composition: object,
    authority_request: FieldContractAuthorityRequestV1,
    user_receipt: FieldContractUserReceiptV1 | None,
    authority: NamedHumanAuthorityV1,
    now: datetime,
    weak_identity: object,
    strong_identity: object,
    transport: ArmTransportPort,
    authorization: SecretStr | None,
) -> FairExperimentExecutionResultV1:
    """Execute the exact 074 pair through an authorized production transport port."""

    if authorization is None:
        return _blocked_execution("BLOCKED_ON_AUTHORIZATION", "OPAQUE_AUTHORIZATION_MISSING")
    if not _identities_exact(weak_identity, strong_identity):
        return _blocked_execution(
            "BLOCKED_ON_FAIR_RERUN_CONTRACT", "FAIR_RERUN_EXECUTION_IDENTITY_MISMATCH"
        )
    receipts: dict[Role, ArmExecutionTransportReceiptV1] = {}
    strong_execution_receipts: list[ceiling.StrongExecutionReceiptV1] = []
    drift: list[str] = []

    def invoke(
        role: Role,
        actual: SemanticInputCompositionV1,
        identity: vf.ArmInputIdentityV1,
    ) -> tuple[vf.ArmFieldOutputV1, ...]:
        submission = _submission(role, actual, identity)
        result = transport.submit(submission, authorization=authorization)
        if type(result) is not ArmExecutionTransportResultV1 or type(result.fields) is not tuple:
            drift.append(f"{role.upper()}_TRANSPORT_RECEIPT_DRIFT")
            raise ValueError("transport receipt rejected")
        if not _receipt_exact(result.receipt, submission, result.fields):
            drift.append(f"{role.upper()}_TRANSPORT_RECEIPT_DRIFT")
            raise ValueError("transport receipt rejected")
        if role == "weak" and result.strong_execution_receipt is not None:
            drift.append("WEAK_FOREIGN_STRONG_EXECUTION_RECEIPT")
            raise ValueError("foreign strong receipt rejected")
        if role == "strong":
            if type(result.strong_execution_receipt) is not ceiling.StrongExecutionReceiptV1:
                drift.append("STRONG_EXECUTION_RECEIPT_MISSING")
                raise ValueError("strong receipt missing")
            strong_execution_receipts.append(result.strong_execution_receipt)
        receipts[role] = result.receipt
        return result.fields

    rerun = fair.run_596_1_fair_rerun(
        composition=composition,
        authority_request=authority_request,
        user_receipt=user_receipt,
        authority=authority,
        now=now,
        weak_identity=weak_identity,
        strong_identity=strong_identity,
        weak_execute=lambda actual, identity: invoke("weak", actual, identity),
        strong_execute=lambda actual, identity: invoke("strong", actual, identity),
    )
    calls = rerun.weak_calls + rerun.strong_calls
    if drift:
        return _blocked_execution("BLOCKED_ON_TRANSPORT_RECEIPT", drift[0], calls)
    if rerun.status != "OUTPUTS_FROZEN_FOR_049_SCORING":
        status: ExecutionStatus = (
            "ARM_EXECUTION_FAILED"
            if rerun.status == "ARM_EXECUTION_FAILED"
            else "BLOCKED_ON_FAIR_RERUN_CONTRACT"
        )
        return FairExperimentExecutionResultV1(status, rerun.reason_codes, calls)
    if (
        rerun.weak_output is None
        or rerun.strong_output is None
        or rerun.pair_receipt_sha256 is None
        or rerun.authority_subject_sha256 is None
        or rerun.authority_receipt_sha256 is None
        or rerun.composition_hash is None
        or "weak" not in receipts
        or "strong" not in receipts
        or len(strong_execution_receipts) != 1
        or type(composition) is not SemanticInputCompositionV1
        or user_receipt is None
    ):
        return _blocked_execution("BLOCKED_ON_FAIR_RERUN_CONTRACT", "FROZEN_PAIR_INCOMPLETE", calls)
    weak_output = vf.freeze_arm_output(
        arm="candidate",
        identity=rerun.weak_output.identity,
        fields=rerun.weak_output.fields,
    )
    strong_output = rerun.strong_output
    strong_execution_receipt = strong_execution_receipts[0]
    if not _strong_receipt_scalars_well_formed(strong_execution_receipt):
        return _blocked_execution(
            "BLOCKED_ON_TRANSPORT_RECEIPT",
            "STRONG_EXECUTION_RECEIPT_MALFORMED",
            calls,
        )
    draft = SealedFairExperimentV1(
        contract_id=_SEAL_CONTRACT,
        composition=composition,
        authority_request=authority_request,
        user_receipt=user_receipt,
        authority=authority,
        now=now,
        weak_identity=rerun.weak_output.identity,
        strong_identity=rerun.strong_output.identity,
        fair_rerun_result=rerun,
        composition_hash=rerun.composition_hash,
        field_contract_subject_sha256=rerun.authority_subject_sha256,
        field_contract_receipt_sha256=rerun.authority_receipt_sha256,
        pair_receipt_sha256=rerun.pair_receipt_sha256,
        weak_074_output_hash=rerun.weak_output.output_hash,
        strong_074_output_hash=strong_output.output_hash,
        weak_output=weak_output,
        strong_output=strong_output,
        weak_transport_receipt=receipts["weak"],
        strong_transport_receipt=receipts["strong"],
        strong_execution_receipt=strong_execution_receipt,
        weak_authority="SCORED",
        strong_authority="UNADMITTED_RAW",
        seal_sha256="",
    )
    try:
        sealed = replace(draft, seal_sha256=_seal_hash(draft))
    except CanonicalEncodingError:
        return _blocked_execution(
            "BLOCKED_ON_TRANSPORT_RECEIPT",
            "STRONG_EXECUTION_RECEIPT_MALFORMED",
            calls,
        )
    if not _sealed_exact(sealed):
        return _blocked_execution(
            "BLOCKED_ON_FAIR_RERUN_CONTRACT", "SEALED_PAIR_REPLAY_FAILED", calls
        )
    return FairExperimentExecutionResultV1(
        status="OUTPUTS_SEALED_FOR_066_SCORING",
        reason_codes=(),
        transport_calls=calls,
        sealed_experiment=sealed,
    )


def _replay_074(sealed: SealedFairExperimentV1) -> fair.FairRerunResultV1:
    rerun = sealed.fair_rerun_result
    if rerun.weak_output is None or rerun.strong_output is None:
        raise ValueError("stored fair rerun is incomplete")
    weak_fields = rerun.weak_output.fields
    strong_fields = rerun.strong_output.fields

    def weak_execute(
        actual: SemanticInputCompositionV1,
        identity: vf.ArmInputIdentityV1,
    ) -> tuple[vf.ArmFieldOutputV1, ...]:
        if actual != sealed.composition or identity != sealed.weak_identity:
            raise ValueError("weak replay input drift")
        return weak_fields

    def strong_execute(
        actual: SemanticInputCompositionV1,
        identity: vf.ArmInputIdentityV1,
    ) -> tuple[vf.ArmFieldOutputV1, ...]:
        if actual != sealed.composition or identity != sealed.strong_identity:
            raise ValueError("strong replay input drift")
        return strong_fields

    return fair.run_596_1_fair_rerun(
        composition=sealed.composition,
        authority_request=sealed.authority_request,
        user_receipt=sealed.user_receipt,
        authority=sealed.authority,
        now=sealed.now,
        weak_identity=sealed.weak_identity,
        strong_identity=sealed.strong_identity,
        weak_execute=weak_execute,
        strong_execute=strong_execute,
    )


def _sealed_exact(value: object) -> TypeGuard[SealedFairExperimentV1]:
    if type(value) is not SealedFairExperimentV1:
        return False
    sealed = value
    try:
        replayed = _replay_074(sealed)
        weak_submission = _submission("weak", sealed.composition, sealed.weak_identity)
        strong_submission = _submission("strong", sealed.composition, sealed.strong_identity)
        rerun = sealed.fair_rerun_result
        return (
            sealed.contract_id == _SEAL_CONTRACT
            and replayed == rerun
            and rerun.status == "OUTPUTS_FROZEN_FOR_049_SCORING"
            and rerun.weak_output is not None
            and rerun.strong_output is not None
            and rerun.pair_receipt_sha256 == sealed.pair_receipt_sha256
            and rerun.composition_hash == sealed.composition_hash
            and sealed.composition.composition_hash == sealed.composition_hash
            and sealed.weak_identity == rerun.weak_output.identity
            and sealed.strong_identity == rerun.strong_output.identity
            and _identities_exact(sealed.weak_identity, sealed.strong_identity)
            and sealed.weak_output.arm == sealed.strong_output.arm == "candidate"
            and vf.verify_arm_output_hash(sealed.weak_output)
            and vf.verify_arm_output_hash(sealed.strong_output)
            and sealed.weak_output
            == vf.freeze_arm_output(
                arm="candidate",
                identity=rerun.weak_output.identity,
                fields=rerun.weak_output.fields,
            )
            and sealed.strong_output == rerun.strong_output
            and rerun.weak_output.output_hash == sealed.weak_074_output_hash
            and rerun.strong_output.output_hash == sealed.strong_074_output_hash
            and tuple(item.field_id for item in sealed.weak_output.fields)
            == vf.APPROVED_SCHEMA60_FIELD_IDS
            and tuple(item.field_id for item in sealed.strong_output.fields)
            == vf.APPROVED_SCHEMA60_FIELD_IDS
            and _receipt_exact(
                sealed.weak_transport_receipt, weak_submission, sealed.weak_output.fields
            )
            and _receipt_exact(
                sealed.strong_transport_receipt, strong_submission, sealed.strong_output.fields
            )
            and sealed.weak_authority == "SCORED"
            and sealed.strong_authority == "UNADMITTED_RAW"
            and _is_sha(sealed.seal_sha256)
            and sealed.seal_sha256 == _seal_hash(sealed)
        )
    except Exception:
        return False


def score_frozen_experiment(
    *,
    sealed_experiment: object,
    golden_loader: GoldenBytesPort,
    admitted_parse_artifacts: tuple[vf.AdmittedParseArtifactV1, ...],
) -> FairExperimentScoreResultV1:
    """Replay the complete seal before loading Golden bytes and entering 066."""

    if not _sealed_exact(sealed_experiment):
        return FairExperimentScoreResultV1(
            status="BLOCKED_ON_FROZEN_EXPERIMENT",
            reason_codes=("SEALED_EXPERIMENT_REPLAY_FAILED",),
            golden_reads=0,
        )
    sealed = sealed_experiment
    try:
        preflight = ceiling.compare_596_1_weak_strong_ceiling(
            weak_output=sealed.weak_output,
            strong_output=sealed.strong_output,
            strong_execution_receipt=sealed.strong_execution_receipt,
            golden_596_jsonl_bytes=b"",
            admitted_parse_artifacts=admitted_parse_artifacts,
        )
    except Exception:
        return FairExperimentScoreResultV1(
            status="BLOCKED_ON_FROZEN_EXPERIMENT",
            reason_codes=("PUBLIC_066_PREFLIGHT_FAILED",),
            golden_reads=0,
        )
    if not (
        preflight.status == "GOLDEN_INVALID"
        and preflight.reason_codes == ("GOLDEN_596_BYTES_INVALID",)
    ):
        return FairExperimentScoreResultV1(
            status="BLOCKED_ON_FROZEN_EXPERIMENT",
            reason_codes=("PUBLIC_066_PREFLIGHT_FAILED",),
            golden_reads=0,
        )
    try:
        golden_bytes = golden_loader.load()
    except Exception:
        return FairExperimentScoreResultV1(
            status="GOLDEN_LOAD_FAILED",
            reason_codes=("GOLDEN_LOAD_FAILED",),
            golden_reads=1,
        )
    comparison = ceiling.compare_596_1_weak_strong_ceiling(
        weak_output=sealed.weak_output,
        strong_output=sealed.strong_output,
        strong_execution_receipt=sealed.strong_execution_receipt,
        golden_596_jsonl_bytes=golden_bytes,
        admitted_parse_artifacts=admitted_parse_artifacts,
    )
    return FairExperimentScoreResultV1(
        status=comparison.status,
        reason_codes=comparison.reason_codes,
        golden_reads=1,
        comparison=comparison,
    )


__all__ = [
    "ArmExecutionSubmissionV1",
    "ArmExecutionTransportReceiptV1",
    "ArmExecutionTransportResultV1",
    "FairExperimentExecutionResultV1",
    "FairExperimentScoreResultV1",
    "ArmTransportPort",
    "GoldenBytesPort",
    "SealedFairExperimentV1",
    "execute_and_freeze",
    "score_frozen_experiment",
    "transport_execution_receipt_sha256",
]
