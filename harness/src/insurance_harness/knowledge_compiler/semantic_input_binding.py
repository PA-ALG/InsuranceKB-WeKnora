"""Product 596-1 shared MinerU semantic-task composition.

This module is deliberately pure. It freezes the 052-backed 8+2 task blueprint,
binds merged 068 custody to 053/054/057 contracts, and performs no provider or
Golden access.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Annotated, Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.evidence_verifier import (
    FREEFORM_EVIDENCE_BINDING_OBJECT_TYPE,
    CandidateValueV1,
    EvidenceSnapshotV1,
    EvidenceSupportScopeV1,
    FieldCandidateV1,
    FieldRuleV1,
    FreeformEvidenceBindingReceiptV1,
    FreeformFieldOutputV1,
    RepairBudgetV1,
    TargetedRepairPlanV1,
    VerificationBatchV1,
    VerifierContractError,
    bind_054_attempt_receipt,
    bind_freeform_arm_evidence,
    plan_targeted_repair,
    replay_freeform_arm_evidence_binding,
    value_snapshot,
    verify_evidence_batch,
)
from insurance_harness.compiler.extraction_receipts import (
    AttemptRequestV1,
    FieldOutcomeV1,
    ReceiptChainV1,
    build_attempt_receipt,
    build_initial_attempt,
    build_targeted_repair,
)
from insurance_harness.compiler.extraction_tasks import (
    ArtifactRefV1,
    AttemptBudgetV1,
    ExtractionTaskV1,
    ParsedArtifactAdmissionPort,
    build_extraction_task,
    build_extraction_task_profile,
)
from insurance_harness.compiler.material_profiles import (
    MaterialProfileCatalog,
    MaterialProfileResolution,
    material_profile_catalog_hash,
)
from insurance_harness.compiler.parsed_documents import (
    ParsedDocumentV1,
    ParseManifestV1,
    ParseQualityDecisionV1,
)
from insurance_harness.knowledge_compiler.vertical_falsification import (
    APPROVED_596_1_SOURCE_SHA256,
    APPROVED_MATERIAL_PROFILE_CATALOG_SHA256,
    APPROVED_PRODUCT_VERSION_ID,
    APPROVED_RATE_FIELD_IDS,
    APPROVED_SCHEMA60_FIELD_IDS,
    APPROVED_SCHEMA_REGISTRY_SHA256,
    APPROVED_SCHEMA_VERSION,
    AdmittedParseArtifactV1,
    admit_596_1_vertical_falsification,
)

NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=512, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ContentSnapshot = Annotated[StrictStr, StringConstraints(min_length=1)]
MaterialRole = Literal["terms", "brochure", "rate_table"]
TaskKind = Literal["semantic", "deterministic_rate"]

SHARED_BLUEPRINT_CONTRACT: Final[str] = "596-1-shared-semantic-task-blueprint.v1"
SHARED_BLUEPRINT_OBJECT_TYPE: Final[str] = "shared-semantic-task-blueprint-596-1.v1"
TASK_BLUEPRINT_OBJECT_TYPE: Final[str] = "semantic-task-blueprint-596-1.v1"
PROMPT_IDENTITY_OBJECT_TYPE: Final[str] = "semantic-task-prompt-596-1.v1"
EXPECTED_ROLES: Final[tuple[MaterialRole, ...]] = (
    "terms",
    "brochure",
    "rate_table",
)
MINERU_CUSTODY_CONTRACT: Final[str] = "mineru-semantic-content-custody.v2"
SEMANTIC_COMPOSITION_OBJECT_TYPE: Final[str] = "semantic-input-composition-596-1.v1"
SEMANTIC_REPAIR_BUNDLE_OBJECT_TYPE: Final[str] = "semantic-repair-bundle-596-1.v1"
BOUND_SEMANTIC_ATTEMPT_OBJECT_TYPE: Final[str] = "bound-semantic-attempt-596-1.v1"
SEMANTIC_ATTEMPT_SET_OBJECT_TYPE: Final[str] = "semantic-attempt-set-596-1.v1"


class SemanticBindingContractError(ValueError):
    """Stable rejection before provider or Golden access."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class SemanticExecutionIdentityV1(_FrozenModel):
    """Opaque, explicit execution identities; this DTO grants no execution."""

    model_id: NonBlankStr
    model_identity_sha256: Sha256Hex
    prompt_contract_id: NonBlankStr
    prompt_template_sha256: Sha256Hex
    budget_identity_sha256: Sha256Hex
    normalizer_identity_sha256: Sha256Hex
    output_contract_id: Literal["freeform-arm-evidence-binding-receipt.v1"]
    output_contract_identity_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_merged_output_contract(self) -> Self:
        if self.output_contract_id != FREEFORM_EVIDENCE_BINDING_OBJECT_TYPE:
            raise ValueError("output_contract_identity_mismatch")
        return self


class MinerUCaptureAttemptV2(_FrozenModel):
    attempt_number: Literal[2]
    attempt_role: Literal["bounded_upgrade"]
    generation: Literal[0]


class MinerUParserLedgerV2(_FrozenModel):
    engine: Literal["mineru_cloud"]
    implementation: Literal["NewMinerUCloudReader"]
    native_structure_schema: Literal["mineru-native-structure.v1"]
    model: Literal["pipeline"]
    formula: bool
    table: bool
    ocr: bool
    language: NonBlankStr
    config_sha256: Sha256Hex


class MinerUCallLedgerV2(_FrozenModel):
    allocation_post: Literal[1]
    upload_put: Literal[1]
    status_get: Annotated[int, Field(ge=1, le=20)]
    zip_get: Literal[1]


class MinerUSemanticCustodyV2(_FrozenModel):
    """Exact task-local view of the merged 068 same-read custody artifact."""

    contract: Literal["mineru-semantic-content-custody.v2"]
    source_sha256: Sha256Hex
    attempt: MinerUCaptureAttemptV2
    raw_structure_sha256: Sha256Hex
    sanitized_structure_sha256: Sha256Hex
    sanitized_structure: dict[str, object]
    content_snapshot_sha256: Sha256Hex
    content_snapshot: ContentSnapshot
    capture_identity_sha256: Sha256Hex
    parser: MinerUParserLedgerV2
    calls: MinerUCallLedgerV2
    latency_milliseconds: Annotated[int, Field(ge=0)]
    status: Literal["completed"]
    cross_page_facts: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class SemanticSourceInputV1:
    """One exact 068 payload paired with the already-admitted 061/060 custody."""

    custody_json: bytes
    admitted: AdmittedParseArtifactV1


class ComposedSemanticTaskV1(_FrozenModel):
    task_id: NonBlankStr
    task_kind: TaskKind
    material_role: MaterialRole
    field_ids: tuple[NonBlankStr, ...]
    extraction_task: ExtractionTaskV1 | None
    initial_attempt: AttemptRequestV1 | None

    @model_validator(mode="after")
    def require_execution_shape(self) -> Self:
        semantic = self.task_kind == "semantic"
        if semantic != (self.extraction_task is not None):
            raise ValueError("semantic_task_execution_shape_mismatch")
        if semantic != (self.initial_attempt is not None):
            raise ValueError("semantic_task_execution_shape_mismatch")
        if semantic and (
            self.extraction_task is None
            or self.initial_attempt is None
            or self.extraction_task.field_ids != self.field_ids
            or self.initial_attempt.field_ids != self.field_ids
        ):
            raise ValueError("semantic_task_execution_shape_mismatch")
        return self


class SemanticSourceBindingV1(_FrozenModel):
    material_role: MaterialRole
    source_revision_id: NonBlankStr
    parse_attempt_id: NonBlankStr
    source_sha256: Sha256Hex
    document_hash: Sha256Hex
    manifest_hash: Sha256Hex
    quality_decision_hash: Sha256Hex
    capture_identity_sha256: Sha256Hex
    content_snapshot_sha256: Sha256Hex
    content_snapshot: ContentSnapshot = Field(repr=False)

    @model_validator(mode="after")
    def require_content_snapshot_hash(self) -> Self:
        if _sha256_bytes(self.content_snapshot.encode("utf-8")) != self.content_snapshot_sha256:
            raise ValueError("semantic_content_snapshot_hash_mismatch")
        return self


class SemanticInputCompositionV1(_FrozenModel):
    contract: Literal["596-1-semantic-input-composition.v1"]
    product_version_id: Literal["596-1"]
    schema_sha256: Sha256Hex
    material_profile_catalog_hash: Sha256Hex
    admission_receipt_digest_sha256: Sha256Hex
    arm_blueprints: tuple[SharedSemanticTaskPlanV1, SharedSemanticTaskPlanV1]
    sources: tuple[SemanticSourceBindingV1, SemanticSourceBindingV1, SemanticSourceBindingV1]
    tasks: tuple[ComposedSemanticTaskV1, ...]
    composition_hash: Sha256Hex

    @model_validator(mode="after")
    def require_exact_composition(self) -> Self:
        if (
            tuple(item.material_role for item in self.sources) != EXPECTED_ROLES
            or len(self.tasks) != 10
            or tuple(item.field_ids for item in self.tasks)
            != tuple(item.field_ids for item in self.arm_blueprints[0].tasks)
            or tuple(item.field_ids for item in self.tasks)
            != tuple(item.field_ids for item in self.arm_blueprints[1].tasks)
        ):
            raise ValueError("semantic_composition_shape_mismatch")
        payload = {
            "contract": self.contract,
            "product_version_id": self.product_version_id,
            "schema_sha256": self.schema_sha256,
            "material_profile_catalog_hash": self.material_profile_catalog_hash,
            "admission_receipt_digest_sha256": self.admission_receipt_digest_sha256,
            "arm_blueprint_hashes": tuple(item.blueprint_hash for item in self.arm_blueprints),
            "sources": tuple(
                item.model_dump(mode="python", exclude={"content_snapshot"})
                for item in self.sources
            ),
            "task_hashes": tuple(
                item.extraction_task.task_hash if item.extraction_task else item.task_id
                for item in self.tasks
            ),
        }
        if self.composition_hash != canonical_hash(SEMANTIC_COMPOSITION_OBJECT_TYPE, payload):
            raise ValueError("semantic_composition_hash_mismatch")
        return self


class BoundSemanticAttemptV1(_FrozenModel):
    task_id: NonBlankStr
    composition_hash: Sha256Hex
    model_id: NonBlankStr
    model_identity_sha256: Sha256Hex
    arm_blueprint_hash: Sha256Hex
    normalizer_identity_sha256: Sha256Hex
    receipt_chain: ReceiptChainV1 | None
    evidence_receipts: tuple[FreeformEvidenceBindingReceiptV1, ...]
    verification: VerificationBatchV1 | None
    bound_attempt_hash: Sha256Hex

    @model_validator(mode="after")
    def require_bound_attempt_hash(self) -> Self:
        payload = _bound_attempt_payload(
            task_id=self.task_id,
            composition_hash=self.composition_hash,
            model_id=self.model_id,
            model_identity_sha256=self.model_identity_sha256,
            arm_blueprint_hash=self.arm_blueprint_hash,
            normalizer_identity_sha256=self.normalizer_identity_sha256,
            receipt_chain=self.receipt_chain,
            evidence_receipts=self.evidence_receipts,
            verification=self.verification,
        )
        if self.bound_attempt_hash != canonical_hash(
            BOUND_SEMANTIC_ATTEMPT_OBJECT_TYPE, payload
        ):
            raise ValueError("bound semantic attempt hash mismatch")
        return self


def _bound_attempt_payload(
    *,
    task_id: str,
    composition_hash: str,
    model_id: str,
    model_identity_sha256: str,
    arm_blueprint_hash: str,
    normalizer_identity_sha256: str,
    receipt_chain: ReceiptChainV1 | None,
    evidence_receipts: tuple[FreeformEvidenceBindingReceiptV1, ...],
    verification: VerificationBatchV1 | None,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "composition_hash": composition_hash,
        "model_id": model_id,
        "model_identity_sha256": model_identity_sha256,
        "arm_blueprint_hash": arm_blueprint_hash,
        "normalizer_identity_sha256": normalizer_identity_sha256,
        "receipt_chain": (
            None
            if receipt_chain is None
            else {
                "task_hash": receipt_chain.task_hash,
                "receipt_hashes": tuple(
                    item.receipt_hash for item in receipt_chain.receipts
                ),
            }
        ),
        "evidence_receipt_hashes": tuple(
            item.receipt_hash for item in evidence_receipts
        ),
        "verification_hash": (
            None if verification is None else verification.verification_hash
        ),
    }


class SemanticTargetedRepairV1(_FrozenModel):
    task_id: NonBlankStr
    bound_attempt_hash: Sha256Hex
    attempt: AttemptRequestV1
    locator_plan: TargetedRepairPlanV1

    @model_validator(mode="after")
    def require_exact_field_bijection(self) -> Self:
        if self.attempt.field_ids != self.locator_plan.field_ids:
            raise ValueError("repair locator/attempt field mismatch")
        return self


class SemanticRepairBundleV1(_FrozenModel):
    contract: Literal["semantic-repair-bundle-596-1.v1"]
    composition_hash: Sha256Hex
    model_id: NonBlankStr
    model_identity_sha256: Sha256Hex
    arm_blueprint_hash: Sha256Hex
    normalizer_identity_sha256: Sha256Hex
    attempt_set_hash: Sha256Hex
    repairs: tuple[SemanticTargetedRepairV1, ...]
    bundle_hash: Sha256Hex

    @model_validator(mode="after")
    def require_exact_bundle(self) -> Self:
        task_ids = tuple(item.task_id for item in self.repairs)
        if len(self.repairs) > 4 or len(task_ids) != len(set(task_ids)):
            raise ValueError("semantic repair bundle invalid")
        payload = {
            "contract": self.contract,
            "composition_hash": self.composition_hash,
            "model_id": self.model_id,
            "model_identity_sha256": self.model_identity_sha256,
            "arm_blueprint_hash": self.arm_blueprint_hash,
            "normalizer_identity_sha256": self.normalizer_identity_sha256,
            "attempt_set_hash": self.attempt_set_hash,
            "repairs": tuple(
                {
                    "task_id": item.task_id,
                    "bound_attempt_hash": item.bound_attempt_hash,
                    "attempt_hash": item.attempt.attempt_hash,
                    "locator_plan_hash": item.locator_plan.plan_hash,
                }
                for item in self.repairs
            ),
        }
        if self.bundle_hash != canonical_hash(SEMANTIC_REPAIR_BUNDLE_OBJECT_TYPE, payload):
            raise ValueError("semantic repair bundle hash mismatch")
        return self


def _exact_admitted_sources(
    composition: SemanticInputCompositionV1,
    admitted_sources: tuple[AdmittedParseArtifactV1, ...],
) -> tuple[AdmittedParseArtifactV1, ...]:
    if len(admitted_sources) != len(composition.sources):
        raise SemanticBindingContractError("SEMANTIC_EVIDENCE_MISMATCH")
    expected_by_role = {item.material_role: item for item in composition.sources}
    exact_sources: list[AdmittedParseArtifactV1] = []
    for item in admitted_sources:
        try:
            expected = expected_by_role[item.role]
            document = ParsedDocumentV1.model_validate(
                item.document.model_dump(mode="python", exclude={"document_hash"})
            )
            manifest = ParseManifestV1.model_validate(
                item.manifest.model_dump(mode="python", exclude={"manifest_hash"})
            )
            decision = ParseQualityDecisionV1.model_validate(
                item.decision.model_dump(mode="python", exclude={"decision_hash"})
            )
        except (KeyError, ValidationError, AttributeError, TypeError, ValueError):
            raise SemanticBindingContractError("SEMANTIC_EVIDENCE_MISMATCH") from None
        if (
            item.source_sha256 != expected.source_sha256
            or document.subject.product_version_id != composition.product_version_id
            or document.subject.source_revision_id != expected.source_revision_id
            or document.attempt.attempt_id != expected.parse_attempt_id
            or document.document_hash != expected.document_hash
            or manifest.manifest_hash != expected.manifest_hash
            or decision.decision_hash != expected.quality_decision_hash
            or item.artifact_sha256 != document.document_hash
            or item.manifest_sha256 != manifest.manifest_hash
            or item.decision_sha256 != decision.decision_hash
            or manifest.document_hash != document.document_hash
            or decision.manifest_hash != manifest.manifest_hash
            or decision.decision != "ADMIT"
        ):
            raise SemanticBindingContractError("SEMANTIC_EVIDENCE_MISMATCH")
        exact_sources.append(item)
    if tuple(item.role for item in exact_sources) != EXPECTED_ROLES:
        raise SemanticBindingContractError("SEMANTIC_EVIDENCE_MISMATCH")
    return tuple(exact_sources)


def _bound_attempt_matches_task(
    *,
    bound: BoundSemanticAttemptV1,
    task: ComposedSemanticTaskV1,
    product_version_id: str,
    source: AdmittedParseArtifactV1,
) -> bool:
    chain = bound.receipt_chain
    verification = bound.verification
    if (
        chain is None
        or verification is None
        or task.extraction_task is None
        or len(chain.receipts) != 1
        or chain.task_hash != task.extraction_task.task_hash
        or chain.task != task.extraction_task
        or tuple(item.field_id for item in bound.evidence_receipts) != task.field_ids
        or tuple(item.field_id for item in verification.results) != task.field_ids
        or any(
            item.product_version_id != product_version_id
            for item in bound.evidence_receipts
        )
    ):
        return False
    try:
        outputs: list[FreeformFieldOutputV1] = []
        for receipt in bound.evidence_receipts:
            replay_freeform_arm_evidence_binding(
                receipt=receipt,
                documents=() if receipt.state == "unknown" else (source.document,),
                manifests=() if receipt.state == "unknown" else (source.manifest,),
            )
            outputs.append(
                FreeformFieldOutputV1(
                    product_version_id=receipt.product_version_id,
                    field_id=receipt.field_id,
                    state=receipt.state,
                    value_snapshot=receipt.value_snapshot,
                    evidence=receipt.evidence,
                )
            )
        candidate_rules = tuple(_verification_candidate_and_rule(item) for item in outputs)
        replayed_verification = verify_evidence_batch(
            document=source.document,
            manifest=source.manifest,
            candidates=tuple(item[0] for item in candidate_rules),
            rules=tuple(item[1] for item in candidate_rules),
        )
        if replayed_verification != verification:
            return False
        bind_054_attempt_receipt(chain=chain, verification=replayed_verification)
    except VerifierContractError:
        return False
    return True


def build_596_1_targeted_repairs(
    *,
    composition: SemanticInputCompositionV1,
    attempts: tuple[BoundSemanticAttemptV1, ...],
    locator_plans: tuple[TargetedRepairPlanV1, ...],
    admitted_sources: tuple[AdmittedParseArtifactV1, ...],
) -> SemanticRepairBundleV1:
    """Bind at most four exact 054 repairs to merged 057 locator authority."""

    try:
        exact_composition = SemanticInputCompositionV1.model_validate(
            composition.model_dump(mode="python")
        )
        exact_attempts = tuple(
            BoundSemanticAttemptV1.model_validate(
                item.model_dump(exclude_computed_fields=True)
            )
            for item in attempts
        )
        exact_plans = tuple(
            TargetedRepairPlanV1.model_validate(item.model_dump(exclude={"plan_hash"}))
            for item in locator_plans
        )
    except (ValidationError, AttributeError, TypeError, ValueError):
        raise SemanticBindingContractError("SEMANTIC_REPAIR_INVALID") from None
    semantic_tasks = tuple(
        item for item in exact_composition.tasks if item.task_kind == "semantic"
    )
    source_map = {
        item.role: item
        for item in _exact_admitted_sources(exact_composition, admitted_sources)
    }
    task_ids = tuple(item.task_id for item in exact_attempts)
    expected_task_ids = tuple(item.task_id for item in semantic_tasks)
    if (
        task_ids != expected_task_ids
        or any(
            item.composition_hash != exact_composition.composition_hash
            for item in exact_attempts
        )
        or len({item.arm_blueprint_hash for item in exact_attempts}) != 1
        or len({item.model_id for item in exact_attempts}) != 1
        or len({item.model_identity_sha256 for item in exact_attempts}) != 1
        or len({item.normalizer_identity_sha256 for item in exact_attempts}) != 1
        or any(
            not _bound_attempt_matches_task(
                bound=bound,
                task=task,
                product_version_id=exact_composition.product_version_id,
                source=source_map[task.material_role],
            )
            for bound, task in zip(exact_attempts, semantic_tasks, strict=True)
        )
    ):
        raise SemanticBindingContractError("SEMANTIC_REPAIR_INVALID")
    arm = next(
        (
            item
            for item in exact_composition.arm_blueprints
            if item.blueprint_hash == exact_attempts[0].arm_blueprint_hash
            and item.execution_identity.model_id == exact_attempts[0].model_id
            and item.execution_identity.model_identity_sha256
            == exact_attempts[0].model_identity_sha256
            and item.execution_identity.normalizer_identity_sha256
            == exact_attempts[0].normalizer_identity_sha256
        ),
        None,
    )
    if arm is None:
        raise SemanticBindingContractError("SEMANTIC_REPAIR_INVALID")
    unresolved = tuple(
        item
        for item in exact_attempts
        if item.receipt_chain is not None
        and any(
            outcome.status != "candidate"
            for outcome in item.receipt_chain.receipts[-1].field_outcomes
        )
    )
    if len(unresolved) != len(exact_plans):
        raise SemanticBindingContractError("SEMANTIC_REPAIR_INVALID")
    if len(unresolved) > 4:
        raise SemanticBindingContractError("SEMANTIC_REPAIR_BUDGET_EXHAUSTED")
    task_map = {item.task_id: item for item in exact_composition.tasks}
    repairs: list[SemanticTargetedRepairV1] = []
    try:
        for bound, locator_plan in zip(unresolved, exact_plans, strict=True):
            chain = bound.receipt_chain
            task = task_map[bound.task_id]
            verification = bound.verification
            if chain is None or verification is None or task.extraction_task is None:
                raise ValueError
            attempt = build_targeted_repair(task.extraction_task, chain)
            source = source_map[task.material_role]
            locator_ids = {
                *(item.page_id for item in source.document.pages),
                *(item.block_id for item in source.document.blocks),
                *(item.table_id for item in source.document.tables),
                *(item.cell_id for item in source.document.cells),
            }
            if (
                verification.product_version_id != exact_composition.product_version_id
                or verification.source_revision_id
                != source.document.subject.source_revision_id
                or verification.parse_attempt_id != source.document.attempt.attempt_id
                or verification.parsed_document_hash != source.document.document_hash
                or verification.parse_manifest_hash != source.manifest.manifest_hash
                or tuple(
                    item.field_id
                    for item in verification.results
                    if item.status != "PASS"
                )
                != attempt.field_ids
                or any(
                    ref not in locator_ids
                    for item in locator_plan.approved_locators
                    for ref in item.locator_refs
                )
            ):
                raise ValueError
            bind_054_attempt_receipt(chain=chain, verification=verification)
            repair_decision = plan_targeted_repair(
                verification,
                approved_locators=locator_plan.approved_locators,
                budget=RepairBudgetV1(max_targeted_repairs=1),
                repairs_used=0,
            )
            if repair_decision.plan != locator_plan:
                raise ValueError
            repairs.append(
                SemanticTargetedRepairV1(
                    task_id=bound.task_id,
                    bound_attempt_hash=bound.bound_attempt_hash,
                    attempt=attempt,
                    locator_plan=locator_plan,
                )
            )
    except (ValueError, VerifierContractError):
        raise SemanticBindingContractError("SEMANTIC_REPAIR_INVALID") from None
    repair_tuple = tuple(repairs)
    attempt_set_hash = canonical_hash(
        SEMANTIC_ATTEMPT_SET_OBJECT_TYPE,
        {
            "composition_hash": exact_composition.composition_hash,
            "bound_attempt_hashes": tuple(
                item.bound_attempt_hash for item in exact_attempts
            ),
        },
    )
    payload = {
        "contract": "semantic-repair-bundle-596-1.v1",
        "composition_hash": exact_composition.composition_hash,
        "model_id": exact_attempts[0].model_id,
        "model_identity_sha256": exact_attempts[0].model_identity_sha256,
        "arm_blueprint_hash": exact_attempts[0].arm_blueprint_hash,
        "normalizer_identity_sha256": exact_attempts[0].normalizer_identity_sha256,
        "attempt_set_hash": attempt_set_hash,
        "repairs": tuple(
            {
                "task_id": item.task_id,
                "bound_attempt_hash": item.bound_attempt_hash,
                "attempt_hash": item.attempt.attempt_hash,
                "locator_plan_hash": item.locator_plan.plan_hash,
            }
            for item in repair_tuple
        ),
    }
    return SemanticRepairBundleV1(
        contract="semantic-repair-bundle-596-1.v1",
        composition_hash=exact_composition.composition_hash,
        model_id=exact_attempts[0].model_id,
        model_identity_sha256=exact_attempts[0].model_identity_sha256,
        arm_blueprint_hash=exact_attempts[0].arm_blueprint_hash,
        normalizer_identity_sha256=exact_attempts[0].normalizer_identity_sha256,
        attempt_set_hash=attempt_set_hash,
        repairs=repair_tuple,
        bundle_hash=canonical_hash(SEMANTIC_REPAIR_BUNDLE_OBJECT_TYPE, payload),
    )


def _task_payload(
    *,
    task_id: str,
    task_kind: TaskKind,
    material_role: MaterialRole,
    module_id: str,
    risk_partition_id: str,
    field_ids: tuple[str, ...],
    source_sha256: str,
    material_profile_id: str,
    material_profile_binding_hash: str,
    resolved_template_content_hash: str,
    catalog_hash: str,
    schema_sha256: str,
    execution_identity: SemanticExecutionIdentityV1,
    task_prompt_identity_sha256: str,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "task_kind": task_kind,
        "material_role": material_role,
        "module_id": module_id,
        "risk_partition_id": risk_partition_id,
        "field_ids": field_ids,
        "source_sha256": source_sha256,
        "material_profile_id": material_profile_id,
        "material_profile_binding_hash": material_profile_binding_hash,
        "resolved_template_content_hash": resolved_template_content_hash,
        "material_profile_catalog_hash": catalog_hash,
        "schema_sha256": schema_sha256,
        "model_id": execution_identity.model_id,
        "model_identity_sha256": execution_identity.model_identity_sha256,
        "prompt_identity_sha256": task_prompt_identity_sha256,
        "budget_identity_sha256": execution_identity.budget_identity_sha256,
        "normalizer_identity_sha256": execution_identity.normalizer_identity_sha256,
        "output_contract_identity_sha256": (execution_identity.output_contract_identity_sha256),
    }


class SharedSemanticTaskBlueprintV1(_FrozenModel):
    task_id: NonBlankStr
    task_kind: TaskKind
    material_role: MaterialRole
    module_id: NonBlankStr
    risk_partition_id: NonBlankStr
    field_ids: tuple[NonBlankStr, ...]
    source_sha256: Sha256Hex
    material_profile_id: NonBlankStr
    material_profile_binding_hash: Sha256Hex
    resolved_template_content_hash: Sha256Hex
    material_profile_catalog_hash: Sha256Hex
    schema_sha256: Sha256Hex
    model_id: NonBlankStr
    model_identity_sha256: Sha256Hex
    prompt_identity_sha256: Sha256Hex
    budget_identity_sha256: Sha256Hex
    normalizer_identity_sha256: Sha256Hex
    output_contract_identity_sha256: Sha256Hex
    task_hash: Sha256Hex

    @model_validator(mode="after")
    def require_canonical_fields_and_hash(self) -> Self:
        if (
            not self.field_ids
            or self.field_ids != tuple(sorted(self.field_ids))
            or len(self.field_ids) != len(set(self.field_ids))
        ):
            raise ValueError("task_field_partition_invalid")
        payload = self.model_dump(mode="python", exclude={"task_hash"})
        if self.task_hash != canonical_hash(TASK_BLUEPRINT_OBJECT_TYPE, payload):
            raise ValueError("task_blueprint_hash_mismatch")
        return self


def _blueprint_payload(
    *,
    execution_identity: SemanticExecutionIdentityV1,
    resolution_binding_hashes: tuple[str, ...],
    tasks: tuple[SharedSemanticTaskBlueprintV1, ...],
) -> dict[str, object]:
    return {
        "contract": SHARED_BLUEPRINT_CONTRACT,
        "product_version_id": APPROVED_PRODUCT_VERSION_ID,
        "schema_version": APPROVED_SCHEMA_VERSION,
        "schema_sha256": APPROVED_SCHEMA_REGISTRY_SHA256,
        "source_sha256": APPROVED_596_1_SOURCE_SHA256,
        "material_profile_catalog_hash": APPROVED_MATERIAL_PROFILE_CATALOG_SHA256,
        "resolution_binding_hashes": resolution_binding_hashes,
        "execution_identity": execution_identity.model_dump(mode="python"),
        "tasks": tuple(task.model_dump(mode="python") for task in tasks),
    }


class SharedSemanticTaskPlanV1(_FrozenModel):
    contract: Literal["596-1-shared-semantic-task-blueprint.v1"]
    product_version_id: Literal["596-1"]
    schema_version: Literal["v1.1+b31a411c621c"]
    schema_sha256: Sha256Hex
    source_sha256: tuple[Sha256Hex, Sha256Hex, Sha256Hex]
    material_profile_catalog_hash: Sha256Hex
    resolution_binding_hashes: tuple[Sha256Hex, Sha256Hex, Sha256Hex]
    execution_identity: SemanticExecutionIdentityV1
    tasks: tuple[SharedSemanticTaskBlueprintV1, ...]
    blueprint_hash: Sha256Hex

    @model_validator(mode="after")
    def require_exact_plan(self) -> Self:
        all_fields = tuple(field_id for task in self.tasks for field_id in task.field_ids)
        if (
            len(self.tasks) != 10
            or sum(task.task_kind == "semantic" for task in self.tasks) != 8
            or sum(task.task_kind == "deterministic_rate" for task in self.tasks) != 2
            or len(all_fields) != len(set(all_fields))
            or set(all_fields) != set(APPROVED_SCHEMA60_FIELD_IDS)
        ):
            raise ValueError("schema60_task_bijection_mismatch")
        payload = _blueprint_payload(
            execution_identity=self.execution_identity,
            resolution_binding_hashes=self.resolution_binding_hashes,
            tasks=self.tasks,
        )
        if self.blueprint_hash != canonical_hash(SHARED_BLUEPRINT_OBJECT_TYPE, payload):
            raise ValueError("shared_blueprint_hash_mismatch")
        return self


def _balanced_four(fields: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    quotient, remainder = divmod(len(fields), 4)
    result: list[tuple[str, ...]] = []
    cursor = 0
    for index in range(4):
        width = quotient + (1 if index < remainder else 0)
        partition = tuple(sorted(fields[cursor : cursor + width]))
        result.append(partition)
        cursor += width
    if cursor != len(fields) or any(not partition for partition in result):
        raise SemanticBindingContractError("SCHEMA60_TASK_PARTITION_INVALID")
    return tuple(result)


def _validated_authority(
    catalog: MaterialProfileCatalog,
    resolutions: tuple[MaterialProfileResolution, ...],
) -> tuple[MaterialProfileCatalog, tuple[MaterialProfileResolution, ...]]:
    try:
        exact_catalog = MaterialProfileCatalog.model_validate(catalog.model_dump(mode="python"))
        exact_resolutions = tuple(
            MaterialProfileResolution.model_validate(item.model_dump(mode="python"))
            for item in resolutions
        )
    except (ValidationError, AttributeError, TypeError, ValueError):
        raise SemanticBindingContractError("MATERIAL_AUTHORITY_MISMATCH") from None
    if (
        material_profile_catalog_hash(exact_catalog) != APPROVED_MATERIAL_PROFILE_CATALOG_SHA256
        or exact_catalog.product.product_version != APPROVED_PRODUCT_VERSION_ID
        or exact_catalog.schema_binding.schema_version != APPROVED_SCHEMA_VERSION
        or exact_catalog.schema_binding.field_ids != APPROVED_SCHEMA60_FIELD_IDS
        or len(exact_resolutions) != 3
        or tuple(item.profile.material_role for item in exact_resolutions) != EXPECTED_ROLES
        or tuple(item.profile.source.sha256 for item in exact_resolutions)
        != APPROVED_596_1_SOURCE_SHA256
        or any(
            item.catalog_hash != APPROVED_MATERIAL_PROFILE_CATALOG_SHA256
            or item.request.schema_field_ids != APPROVED_SCHEMA60_FIELD_IDS
            or item.request.space_id != exact_resolutions[0].request.space_id
            for item in exact_resolutions
        )
    ):
        raise SemanticBindingContractError("MATERIAL_AUTHORITY_MISMATCH")
    return exact_catalog, exact_resolutions


def _make_task(
    *,
    resolution: MaterialProfileResolution,
    task_kind: TaskKind,
    ordinal: int,
    field_ids: tuple[str, ...],
    execution_identity: SemanticExecutionIdentityV1,
) -> SharedSemanticTaskBlueprintV1:
    role = resolution.profile.material_role
    module_id = (
        f"596-1-{role}-semantic-{ordinal:02d}"
        if task_kind == "semantic"
        else f"596-1-rate-deterministic-{ordinal:02d}"
    )
    risk_partition_id = (
        f"{role}-semantic-{ordinal:02d}"
        if task_kind == "semantic"
        else f"rate-numeric-{ordinal:02d}"
    )
    task_id = f"069:{module_id}"
    task_prompt_identity_sha256 = canonical_hash(
        PROMPT_IDENTITY_OBJECT_TYPE,
        {
            "prompt_contract_id": execution_identity.prompt_contract_id,
            "prompt_template_sha256": execution_identity.prompt_template_sha256,
            "task_id": task_id,
            "task_kind": task_kind,
            "material_role": role,
            "field_ids": field_ids,
        },
    )
    payload = _task_payload(
        task_id=task_id,
        task_kind=task_kind,
        material_role=role,
        module_id=module_id,
        risk_partition_id=risk_partition_id,
        field_ids=field_ids,
        source_sha256=resolution.profile.source.sha256,
        material_profile_id=resolution.profile.profile_id,
        material_profile_binding_hash=resolution.binding_hash,
        resolved_template_content_hash=resolution.resolved_template.content_hash,
        catalog_hash=resolution.catalog_hash,
        schema_sha256=APPROVED_SCHEMA_REGISTRY_SHA256,
        execution_identity=execution_identity,
        task_prompt_identity_sha256=task_prompt_identity_sha256,
    )
    return SharedSemanticTaskBlueprintV1(
        task_id=task_id,
        task_kind=task_kind,
        material_role=role,
        module_id=module_id,
        risk_partition_id=risk_partition_id,
        field_ids=field_ids,
        source_sha256=resolution.profile.source.sha256,
        material_profile_id=resolution.profile.profile_id,
        material_profile_binding_hash=resolution.binding_hash,
        resolved_template_content_hash=resolution.resolved_template.content_hash,
        material_profile_catalog_hash=resolution.catalog_hash,
        schema_sha256=APPROVED_SCHEMA_REGISTRY_SHA256,
        model_id=execution_identity.model_id,
        model_identity_sha256=execution_identity.model_identity_sha256,
        prompt_identity_sha256=task_prompt_identity_sha256,
        budget_identity_sha256=execution_identity.budget_identity_sha256,
        normalizer_identity_sha256=execution_identity.normalizer_identity_sha256,
        output_contract_identity_sha256=(execution_identity.output_contract_identity_sha256),
        task_hash=canonical_hash(TASK_BLUEPRINT_OBJECT_TYPE, payload),
    )


def build_596_1_shared_task_blueprint(
    *,
    catalog: MaterialProfileCatalog,
    resolutions: tuple[MaterialProfileResolution, ...],
    execution_identity: SemanticExecutionIdentityV1,
) -> SharedSemanticTaskPlanV1:
    """Build the model-neutral 8+2 plan without reading 068 or issuing work."""

    exact_catalog, exact_resolutions = _validated_authority(catalog, resolutions)
    try:
        exact_execution = SemanticExecutionIdentityV1.model_validate(
            execution_identity.model_dump(mode="python")
        )
    except (ValidationError, AttributeError, TypeError, ValueError):
        raise SemanticBindingContractError("EXECUTION_IDENTITY_MISMATCH") from None

    authorities = {item.primary_role: item for item in exact_catalog.field_authority_groups}
    if set(authorities) != set(EXPECTED_ROLES):
        raise SemanticBindingContractError("MATERIAL_AUTHORITY_MISMATCH")
    if set().union(*(set(item.field_ids) for item in authorities.values())) != set(
        APPROVED_SCHEMA60_FIELD_IDS
    ):
        raise SemanticBindingContractError("MATERIAL_AUTHORITY_MISMATCH")

    by_role = {item.profile.material_role: item for item in exact_resolutions}
    tasks: list[SharedSemanticTaskBlueprintV1] = []
    for role in ("terms", "brochure"):
        ordered = tuple(
            field_id
            for field_id in APPROVED_SCHEMA60_FIELD_IDS
            if field_id in authorities[role].field_ids
        )
        for ordinal, partition in enumerate(_balanced_four(ordered), start=1):
            tasks.append(
                _make_task(
                    resolution=by_role[role],
                    task_kind="semantic",
                    ordinal=ordinal,
                    field_ids=partition,
                    execution_identity=exact_execution,
                )
            )
    for ordinal, field_id in enumerate(APPROVED_RATE_FIELD_IDS, start=1):
        if field_id not in authorities["rate_table"].field_ids:
            raise SemanticBindingContractError("MATERIAL_AUTHORITY_MISMATCH")
        tasks.append(
            _make_task(
                resolution=by_role["rate_table"],
                task_kind="deterministic_rate",
                ordinal=ordinal,
                field_ids=(field_id,),
                execution_identity=exact_execution,
            )
        )
    task_tuple = tuple(tasks)
    resolution_hashes = (
        exact_resolutions[0].binding_hash,
        exact_resolutions[1].binding_hash,
        exact_resolutions[2].binding_hash,
    )
    payload = _blueprint_payload(
        execution_identity=exact_execution,
        resolution_binding_hashes=resolution_hashes,
        tasks=task_tuple,
    )
    return SharedSemanticTaskPlanV1(
        contract="596-1-shared-semantic-task-blueprint.v1",
        product_version_id="596-1",
        schema_version="v1.1+b31a411c621c",
        schema_sha256=APPROVED_SCHEMA_REGISTRY_SHA256,
        source_sha256=APPROVED_596_1_SOURCE_SHA256,
        material_profile_catalog_hash=APPROVED_MATERIAL_PROFILE_CATALOG_SHA256,
        resolution_binding_hashes=resolution_hashes,
        execution_identity=exact_execution,
        tasks=task_tuple,
        blueprint_hash=canonical_hash(SHARED_BLUEPRINT_OBJECT_TYPE, payload),
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_json_loads(payload: bytes) -> object:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    return json.loads(payload, object_pairs_hook=object_pairs)


def _verification_candidate_and_rule(
    output: FreeformFieldOutputV1,
) -> tuple[FieldCandidateV1, FieldRuleV1]:
    candidate_value = (
        CandidateValueV1(kind="enum", enum_value=output.value_snapshot)
        if output.state == "present"
        else None
    )
    snapshot = value_snapshot(candidate_value)
    evidence = tuple(
        EvidenceSnapshotV1(
            field_id=item.field_id,
            product_version_id=output.product_version_id,
            source_revision_id=item.source_revision_id,
            parse_attempt_id=item.parse_attempt_id,
            parsed_document_hash=item.parsed_document_hash,
            parse_manifest_hash=item.parse_manifest_hash,
            locator=item.locator,
            quote_snapshot=item.quote_snapshot,
            quote_snapshot_sha256=item.quote_snapshot_sha256,
            value_snapshot=snapshot,
            value_snapshot_sha256=_sha256_bytes(snapshot.encode("utf-8")),
            support_scope=EvidenceSupportScopeV1(
                product_version_id=output.product_version_id,
                subject_id=output.field_id,
                condition_ids=(),
            ),
        )
        for item in output.evidence
    )
    markers = tuple(sorted({item.quote_snapshot for item in output.evidence}))
    candidate = FieldCandidateV1(
        field_id=output.field_id,
        product_version_id=output.product_version_id,
        subject_id=output.field_id,
        condition_ids=(),
        tri_state=output.state,
        value=candidate_value,
        evidence=evidence,
    )
    rule = FieldRuleV1(
        field_id=output.field_id,
        value_kind="enum",
        allowed_values=(
            (output.value_snapshot,)
            if output.state == "present" and output.value_snapshot is not None
            else ("not-applicable",)
        ),
        minimum=None,
        maximum=None,
        expected_unit=None,
        absence_markers=markers if output.state == "absent_explicitly" else (),
        allow_absent=output.state == "absent_explicitly",
    )
    return candidate, rule


def _raw_sanitized_structure(payload: bytes) -> bytes:
    """Recover the exact embedded RawMessage bytes emitted by Go 068."""

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise SemanticBindingContractError("MINERU_CUSTODY_INVALID") from None
    marker = '"sanitized_structure":'
    start = text.find(marker)
    if start < 0 or text.find(marker, start + len(marker)) >= 0:
        raise SemanticBindingContractError("MINERU_CUSTODY_INVALID")
    fragment = text[start + len(marker) :]
    try:
        _, end = json.JSONDecoder().raw_decode(fragment)
    except (TypeError, ValueError):
        raise SemanticBindingContractError("MINERU_CUSTODY_INVALID") from None
    return fragment[:end].encode("utf-8")


def _capture_identity_payload(custody: MinerUSemanticCustodyV2) -> bytes:
    payload = {
        "contract": custody.contract,
        "source_sha256": custody.source_sha256,
        "attempt": custody.attempt.model_dump(mode="python"),
        "parser_config_sha256": custody.parser.config_sha256,
        "raw_structure_sha256": custody.raw_structure_sha256,
        "sanitized_structure_sha256": custody.sanitized_structure_sha256,
        "content_snapshot_sha256": custody.content_snapshot_sha256,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _load_custody(payload: bytes) -> tuple[MinerUSemanticCustodyV2, bytes]:
    try:
        custody = MinerUSemanticCustodyV2.model_validate(_strict_json_loads(payload))
    except (ValidationError, TypeError, ValueError, UnicodeError):
        raise SemanticBindingContractError("MINERU_CUSTODY_INVALID") from None
    sanitized = _raw_sanitized_structure(payload)
    if (
        _sha256_bytes(sanitized) != custody.sanitized_structure_sha256
        or _sha256_bytes(custody.content_snapshot.encode("utf-8"))
        != custody.content_snapshot_sha256
        or _sha256_bytes(_capture_identity_payload(custody)) != custody.capture_identity_sha256
    ):
        raise SemanticBindingContractError("MINERU_CUSTODY_HASH_MISMATCH")
    return custody, sanitized


def _source_binding(
    source: SemanticSourceInputV1,
    *,
    expected_role: MaterialRole,
) -> tuple[SemanticSourceBindingV1, MaterialProfileResolution, bytes]:
    custody, sanitized = _load_custody(source.custody_json)
    admitted = source.admitted
    try:
        resolution = MaterialProfileResolution.model_validate(admitted.material_profile_resolution)
        document = ParsedDocumentV1.model_validate(
            admitted.document.model_dump(mode="python", exclude={"document_hash"})
        )
        manifest = ParseManifestV1.model_validate(
            admitted.manifest.model_dump(mode="python", exclude={"manifest_hash"})
        )
        decision = ParseQualityDecisionV1.model_validate(
            admitted.decision.model_dump(mode="python", exclude={"decision_hash"})
        )
    except (ValidationError, AttributeError, TypeError, ValueError):
        raise SemanticBindingContractError("PARSE_ADMISSION_MISMATCH") from None
    if (
        admitted.role != expected_role
        or resolution.profile.material_role != expected_role
        or custody.source_sha256 != resolution.profile.source.sha256
        or custody.source_sha256 != admitted.source_sha256
        or custody.source_sha256 != document.subject.source_sha256
        or admitted.sanitized_structure != sanitized
        or admitted.raw_structure_sha256 != custody.raw_structure_sha256
        or admitted.sanitized_structure_sha256 != custody.sanitized_structure_sha256
        or admitted.artifact_sha256 != document.document_hash
        or admitted.manifest_sha256 != manifest.manifest_hash
        or admitted.decision_sha256 != decision.decision_hash
        or document.subject.raw_artifact_hash != custody.raw_structure_sha256
        or document.parser.parser_id != "mineru-cloud-pipeline"
        or document.parser.parser_config_hash != custody.parser.config_sha256
        or document.attempt.attempt_number != custody.attempt.attempt_number
        or document.attempt.attempt_role != custody.attempt.attempt_role
        or document.attempt.generation != custody.attempt.generation
        or manifest.document_hash != document.document_hash
        or decision.manifest_hash != manifest.manifest_hash
        or decision.decision != "ADMIT"
    ):
        raise SemanticBindingContractError("PARSE_ADMISSION_MISMATCH")
    return (
        SemanticSourceBindingV1(
            material_role=expected_role,
            source_revision_id=document.subject.source_revision_id,
            parse_attempt_id=document.attempt.attempt_id,
            source_sha256=custody.source_sha256,
            document_hash=document.document_hash,
            manifest_hash=manifest.manifest_hash,
            quality_decision_hash=decision.decision_hash,
            capture_identity_sha256=custody.capture_identity_sha256,
            content_snapshot_sha256=custody.content_snapshot_sha256,
            content_snapshot=custody.content_snapshot,
        ),
        resolution,
        sanitized,
    )


def _shared_execution_contract(
    identities: tuple[SemanticExecutionIdentityV1, SemanticExecutionIdentityV1],
) -> tuple[SemanticExecutionIdentityV1, SemanticExecutionIdentityV1]:
    try:
        exact = tuple(
            SemanticExecutionIdentityV1.model_validate(item.model_dump(mode="python"))
            for item in identities
        )
    except (ValidationError, AttributeError, TypeError, ValueError):
        raise SemanticBindingContractError("EXECUTION_IDENTITY_MISMATCH") from None
    if len({item.model_identity_sha256 for item in exact}) != 2 or any(
        (
            item.prompt_contract_id,
            item.prompt_template_sha256,
            item.budget_identity_sha256,
            item.normalizer_identity_sha256,
            item.output_contract_id,
            item.output_contract_identity_sha256,
        )
        != (
            exact[0].prompt_contract_id,
            exact[0].prompt_template_sha256,
            exact[0].budget_identity_sha256,
            exact[0].normalizer_identity_sha256,
            exact[0].output_contract_id,
            exact[0].output_contract_identity_sha256,
        )
        for item in exact
    ):
        raise SemanticBindingContractError("EXECUTION_CONTRACT_MISMATCH")
    return exact  # type: ignore[return-value]


def compose_596_1_semantic_inputs(
    *,
    catalog: MaterialProfileCatalog,
    sources: tuple[SemanticSourceInputV1, SemanticSourceInputV1, SemanticSourceInputV1],
    execution_identities: tuple[SemanticExecutionIdentityV1, SemanticExecutionIdentityV1],
) -> SemanticInputCompositionV1:
    """Compose exact 068/060 custody into shared 054 tasks without execution."""

    identities = _shared_execution_contract(execution_identities)
    admission = admit_596_1_vertical_falsification(
        admitted_parse_artifacts=tuple(item.admitted for item in sources)
    )
    if (
        admission.status != "READY_FOR_QUALITY_FALSIFICATION"
        or admission.receipt_digest_sha256 is None
    ):
        raise SemanticBindingContractError("PARSE_ADMISSION_MISMATCH")
    bound = tuple(
        _source_binding(source, expected_role=role)
        for source, role in zip(sources, EXPECTED_ROLES, strict=True)
    )
    bindings = tuple(item[0] for item in bound)
    resolutions = tuple(item[1] for item in bound)
    exact_catalog, exact_resolutions = _validated_authority(catalog, resolutions)
    arm_blueprints = tuple(
        build_596_1_shared_task_blueprint(
            catalog=exact_catalog,
            resolutions=exact_resolutions,
            execution_identity=identity,
        )
        for identity in identities
    )
    first_plan = arm_blueprints[0]
    if tuple(task.field_ids for task in first_plan.tasks) != tuple(
        task.field_ids for task in arm_blueprints[1].tasks
    ):
        raise SemanticBindingContractError("EXECUTION_CONTRACT_MISMATCH")

    by_role = {item.profile.material_role: item for item in exact_resolutions}
    admitted_by_role = {item.admitted.role: item.admitted for item in sources}
    authorities = {item.primary_role: item for item in exact_catalog.field_authority_groups}
    composed: list[ComposedSemanticTaskV1] = []
    for blueprint in first_plan.tasks:
        if blueprint.task_kind == "deterministic_rate":
            composed.append(
                ComposedSemanticTaskV1(
                    task_id=blueprint.task_id,
                    task_kind=blueprint.task_kind,
                    material_role=blueprint.material_role,
                    field_ids=blueprint.field_ids,
                    extraction_task=None,
                    initial_attempt=None,
                )
            )
            continue
        resolution = by_role[blueprint.material_role]
        admitted = admitted_by_role[blueprint.material_role]
        budget = AttemptBudgetV1(
            max_fields=len(blueprint.field_ids),
            max_total_attempts=2,
            max_targeted_repairs=1,
        )
        profile = build_extraction_task_profile(
            material_profile=resolution.profile,
            material_profile_binding_hash=resolution.binding_hash,
            parse_policy_receipt=resolution.parse_policy_receipt,
            field_authority=authorities[blueprint.material_role],
            attempt_budget=budget,
        )
        refs = ParsedArtifactAdmissionPort().admitted_input_refs(
            task_profile=profile,
            space_id=admitted.document.subject.space_id,
            product_version_id=admitted.document.subject.product_version_id,
            source_revision_id=admitted.document.subject.source_revision_id,
            source_revision=ArtifactRefV1(
                object_type="source-revision.v1",
                artifact_hash=canonical_hash(
                    "source-revision-069.v1",
                    {
                        "source_revision_id": admitted.document.subject.source_revision_id,
                        "source_sha256": admitted.source_sha256,
                    },
                ),
            ),
            resolved_template=ArtifactRefV1(
                object_type="resolved-template.v1",
                artifact_hash=resolution.resolved_template.content_hash,
            ),
            schema_contract=ArtifactRefV1(
                object_type="schema-contract.v1",
                artifact_hash=APPROVED_SCHEMA_REGISTRY_SHA256,
            ),
            document=admitted.document,
            manifest=admitted.manifest,
            quality_decision=admitted.decision,
        )
        task = build_extraction_task(
            space_id=admitted.document.subject.space_id,
            product_version_id="596-1",
            source_revision_id=admitted.document.subject.source_revision_id,
            material_role=blueprint.material_role,
            module_id=blueprint.module_id,
            risk_partition_id=blueprint.risk_partition_id,
            field_ids=blueprint.field_ids,
            input_refs=refs,
            budget=budget,
            task_profile=profile,
        )
        composed.append(
            ComposedSemanticTaskV1(
                task_id=blueprint.task_id,
                task_kind=blueprint.task_kind,
                material_role=blueprint.material_role,
                field_ids=blueprint.field_ids,
                extraction_task=task,
                initial_attempt=build_initial_attempt(task),
            )
        )
    task_tuple = tuple(composed)
    payload = {
        "contract": "596-1-semantic-input-composition.v1",
        "product_version_id": "596-1",
        "schema_sha256": APPROVED_SCHEMA_REGISTRY_SHA256,
        "material_profile_catalog_hash": APPROVED_MATERIAL_PROFILE_CATALOG_SHA256,
        "admission_receipt_digest_sha256": admission.receipt_digest_sha256,
        "arm_blueprint_hashes": tuple(item.blueprint_hash for item in arm_blueprints),
        "sources": tuple(
            item.model_dump(mode="python", exclude={"content_snapshot"}) for item in bindings
        ),
        "task_hashes": tuple(
            item.extraction_task.task_hash if item.extraction_task else item.task_id
            for item in task_tuple
        ),
    }
    return SemanticInputCompositionV1(
        contract="596-1-semantic-input-composition.v1",
        product_version_id="596-1",
        schema_sha256=APPROVED_SCHEMA_REGISTRY_SHA256,
        material_profile_catalog_hash=APPROVED_MATERIAL_PROFILE_CATALOG_SHA256,
        admission_receipt_digest_sha256=admission.receipt_digest_sha256,
        arm_blueprints=arm_blueprints,  # type: ignore[arg-type]
        sources=bindings,  # type: ignore[arg-type]
        tasks=task_tuple,
        composition_hash=canonical_hash(SEMANTIC_COMPOSITION_OBJECT_TYPE, payload),
    )


def bind_596_1_semantic_response(
    *,
    composition: SemanticInputCompositionV1,
    task_id: str,
    response_json: bytes,
    admitted_sources: tuple[AdmittedParseArtifactV1, ...],
) -> BoundSemanticAttemptV1:
    """Bind one strict arm response through merged 064 and 054 contracts."""

    try:
        composition = SemanticInputCompositionV1.model_validate(
            composition.model_dump(mode="python")
        )
        payload = _strict_json_loads(response_json)
        if not isinstance(payload, dict):
            raise ValueError
        if set(payload) != {
            "task_id",
            "attempt_hash",
            "arm_blueprint_hash",
            "model_identity_sha256",
            "fields",
        }:
            raise ValueError
        task_binding = next(item for item in composition.tasks if item.task_id == task_id)
        arm = next(
            item
            for item in composition.arm_blueprints
            if item.blueprint_hash == payload["arm_blueprint_hash"]
            and item.execution_identity.model_identity_sha256
            == payload["model_identity_sha256"]
        )
        arm_task = next(item for item in arm.tasks if item.task_id == task_id)
        if (
            payload["task_id"] != task_id
            or payload["attempt_hash"]
            != (
                task_binding.initial_attempt.attempt_hash
                if task_binding.initial_attempt is not None
                else None
            )
            or not isinstance(payload["fields"], list)
            or arm_task.field_ids != task_binding.field_ids
        ):
            raise ValueError
        outputs = tuple(FreeformFieldOutputV1.model_validate(item) for item in payload["fields"])
    except (StopIteration, ValidationError, TypeError, ValueError, json.JSONDecodeError):
        raise SemanticBindingContractError("SEMANTIC_RESPONSE_INVALID") from None
    if tuple(item.field_id for item in outputs) != task_binding.field_ids:
        raise SemanticBindingContractError("SEMANTIC_RESPONSE_FIELD_BIJECTION_MISMATCH")
    if any(item.product_version_id != composition.product_version_id for item in outputs):
        raise SemanticBindingContractError("SEMANTIC_RESPONSE_PRODUCT_VERSION_MISMATCH")

    if len(admitted_sources) != len(composition.sources):
        raise SemanticBindingContractError("SEMANTIC_EVIDENCE_MISMATCH")
    expected_by_role = {item.material_role: item for item in composition.sources}
    exact_sources: list[AdmittedParseArtifactV1] = []
    for item in admitted_sources:
        try:
            expected = expected_by_role[item.role]
            document = ParsedDocumentV1.model_validate(
                item.document.model_dump(mode="python", exclude={"document_hash"})
            )
            manifest = ParseManifestV1.model_validate(
                item.manifest.model_dump(mode="python", exclude={"manifest_hash"})
            )
            decision = ParseQualityDecisionV1.model_validate(
                item.decision.model_dump(mode="python", exclude={"decision_hash"})
            )
        except (KeyError, ValidationError, AttributeError, TypeError, ValueError):
            raise SemanticBindingContractError("SEMANTIC_EVIDENCE_MISMATCH") from None
        if (
            item.source_sha256 != expected.source_sha256
            or document.subject.product_version_id != composition.product_version_id
            or document.subject.source_revision_id != expected.source_revision_id
            or document.attempt.attempt_id != expected.parse_attempt_id
            or document.document_hash != expected.document_hash
            or manifest.manifest_hash != expected.manifest_hash
            or decision.decision_hash != expected.quality_decision_hash
            or item.artifact_sha256 != document.document_hash
            or item.manifest_sha256 != manifest.manifest_hash
            or item.decision_sha256 != decision.decision_hash
            or manifest.document_hash != document.document_hash
            or decision.manifest_hash != manifest.manifest_hash
            or decision.decision != "ADMIT"
        ):
            raise SemanticBindingContractError("SEMANTIC_EVIDENCE_MISMATCH")
        exact_sources.append(item)
    if tuple(item.role for item in exact_sources) != EXPECTED_ROLES:
        raise SemanticBindingContractError("SEMANTIC_EVIDENCE_MISMATCH")
    sources_by_member = {
        (
            item.document.subject.source_revision_id,
            item.document.attempt.attempt_id,
            item.document.document_hash,
            item.manifest.manifest_hash,
        ): item
        for item in exact_sources
    }
    content_by_sha = {item.source_sha256: item.content_snapshot for item in composition.sources}
    evidence_receipts: list[FreeformEvidenceBindingReceiptV1] = []
    for output in outputs:
        if output.state == "unknown":
            receipt = bind_freeform_arm_evidence(
                field_output=output,
                documents=(),
                manifests=(),
            )
        else:
            if task_binding.task_kind == "deterministic_rate" and any(
                evidence.locator.subject_type != "cell"
                or evidence.block_id is not None
                or evidence.table_id is None
                or evidence.cell_id is None
                or evidence.row_index is None
                or evidence.column_index is None
                or evidence.header_snapshot is None
                or evidence.row_span is None
                or evidence.column_span is None
                for evidence in output.evidence
            ):
                raise SemanticBindingContractError("SEMANTIC_RATE_CELL_EVIDENCE_REQUIRED")
            members = tuple(
                (
                    item.source_revision_id,
                    item.parse_attempt_id,
                    item.parsed_document_hash,
                    item.parse_manifest_hash,
                )
                for item in output.evidence
            )
            unique_members = tuple(dict.fromkeys(members))
            try:
                selected = tuple(sources_by_member[item] for item in unique_members)
            except KeyError:
                raise SemanticBindingContractError("SEMANTIC_EVIDENCE_MISMATCH") from None
            if any(item.role != task_binding.material_role for item in selected):
                raise SemanticBindingContractError("SEMANTIC_EVIDENCE_MISMATCH")
            if any(
                item.locator.content_snapshot not in content_by_sha.get(item.source_sha256, "")
                or item.quote_snapshot not in item.locator.content_snapshot
                for item in output.evidence
            ):
                raise SemanticBindingContractError("SEMANTIC_EVIDENCE_MISMATCH")
            try:
                receipt = bind_freeform_arm_evidence(
                    field_output=output,
                    documents=tuple(item.document for item in selected),
                    manifests=tuple(item.manifest for item in selected),
                )
            except ValueError:
                raise SemanticBindingContractError("SEMANTIC_EVIDENCE_MISMATCH") from None
        evidence_receipts.append(receipt)
    receipt_chain = None
    verification = None
    if task_binding.initial_attempt is not None:
        if task_binding.extraction_task is None:
            raise SemanticBindingContractError("SEMANTIC_RESPONSE_INVALID")
        source = next(item for item in exact_sources if item.role == task_binding.material_role)
        candidate_rules = tuple(_verification_candidate_and_rule(item) for item in outputs)
        try:
            verification = verify_evidence_batch(
                document=source.document,
                manifest=source.manifest,
                candidates=tuple(item[0] for item in candidate_rules),
                rules=tuple(item[1] for item in candidate_rules),
            )
        except VerifierContractError:
            raise SemanticBindingContractError("SEMANTIC_EVIDENCE_MISMATCH") from None
        outcomes = tuple(
            FieldOutcomeV1(
                field_id=item.field_id,
                status="candidate" if item.status == "PASS" else "unknown",
                candidate_ref=(
                    ArtifactRefV1(
                        object_type="verified-field-candidate.v1",
                        artifact_hash=item.candidate_snapshot_hash,
                    )
                    if item.status == "PASS"
                    else None
                ),
                reason_code=None if item.status == "PASS" else item.reason_codes[0],
            )
            for item in verification.results
        )
        all_candidate = all(item.status == "candidate" for item in outcomes)
        attempt_receipt = build_attempt_receipt(
            task_binding.initial_attempt,
            field_outcomes=outcomes,
            outcome="completed" if all_candidate else "insufficient",
            reason_code=None if all_candidate else "evidence_insufficient",
        )
        receipt_chain = ReceiptChainV1(
            task=task_binding.extraction_task,
            task_hash=task_binding.extraction_task.task_hash,
            receipts=(attempt_receipt,),
        )
    bound_evidence = tuple(evidence_receipts)
    bound_payload = _bound_attempt_payload(
        task_id=task_id,
        composition_hash=composition.composition_hash,
        model_id=arm.execution_identity.model_id,
        model_identity_sha256=arm.execution_identity.model_identity_sha256,
        arm_blueprint_hash=arm.blueprint_hash,
        normalizer_identity_sha256=arm.execution_identity.normalizer_identity_sha256,
        receipt_chain=receipt_chain,
        evidence_receipts=bound_evidence,
        verification=verification,
    )
    return BoundSemanticAttemptV1(
        task_id=task_id,
        composition_hash=composition.composition_hash,
        model_id=arm.execution_identity.model_id,
        model_identity_sha256=arm.execution_identity.model_identity_sha256,
        arm_blueprint_hash=arm.blueprint_hash,
        normalizer_identity_sha256=arm.execution_identity.normalizer_identity_sha256,
        receipt_chain=receipt_chain,
        evidence_receipts=bound_evidence,
        verification=verification,
        bound_attempt_hash=canonical_hash(
            BOUND_SEMANTIC_ATTEMPT_OBJECT_TYPE, bound_payload
        ),
    )


__all__ = [
    "SHARED_BLUEPRINT_CONTRACT",
    "SemanticBindingContractError",
    "MinerUSemanticCustodyV2",
    "SemanticSourceInputV1",
    "SemanticInputCompositionV1",
    "BoundSemanticAttemptV1",
    "SemanticRepairBundleV1",
    "SemanticExecutionIdentityV1",
    "SharedSemanticTaskBlueprintV1",
    "SharedSemanticTaskPlanV1",
    "build_596_1_shared_task_blueprint",
    "compose_596_1_semantic_inputs",
    "bind_596_1_semantic_response",
    "build_596_1_targeted_repairs",
]
