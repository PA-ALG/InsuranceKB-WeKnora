"""Task-local Schema67 expert/Evidence admission gate for Mission 119.

This module is pure and offline.  It composes the public OpenSpec 057 Evidence
binder; it does not parse the review workbook, mint human authority, score a
Golden, or write any artifact.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Final, Literal, Protocol, TypeGuard, runtime_checkable

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, ValidationError

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.evidence_verifier import (
    FreeformEvidenceBindingReceiptV1,
    FreeformFieldOutputV1,
    VerifierContractError,
    bind_freeform_arm_evidence,
)
from insurance_harness.compiler.extraction_tasks import MaterialRole
from insurance_harness.compiler.parsed_documents import ParsedDocumentV1, ParseManifestV1
from insurance_harness.knowledge_compiler.deepseek_locator_extractor_596_1 import (
    DEEPSEEK_EXECUTION_IDENTITY_SHA256,
    DeepSeekCompilerError,
    DeepSeekExecutionReceiptV1,
    DeepSeekTaskExecutionV1,
    EvidenceRepairTraceV2,
    ResponseContractRepairResolutionV2,
    Schema67BatchBudgetV1,
    Schema67BatchExecutionReceiptV1,
    Schema67BatchExecutionV1,
    Schema67BoundAttemptV1,
    Schema67ExecutionPlanV1,
    Schema67PreparedTaskV1,
    Schema67RoleTaskInputV1,
    _require_schema67_execution_plan_mode_815,
    build_schema67_batch_receipt,
    prepare_schema67_deepseek_tasks,
)
from insurance_harness.knowledge_compiler.schema_first_contracts import (
    FieldContractSetV1,
)

WORKBOOK_SHA256: Final[str] = "808473db9c4d0093bc4ddbe9e11dae6ef6f6c6927aefc6ce6fe65d1a9f56bb29"
SCHEMA_SHA256: Final[str] = "1b07dea05d220d83da6391d5761c63836925db06774e0125d85c906c2f76b504"
ORDERED_FIELD_IDS_SHA256: Final[str] = (
    "8ffe2a043dfae6e65d84f213d42818de3c6c1c39c1fcb0c9eccd14367a30db24"
)
CANDIDATE_SHA256: Final[str] = "3a3d81a78ca8121249aa98fa13d6aa099ea770dfbbde789df347a9894b07560f"
REFERENCE_EVIDENCE_FRAGMENT_COUNT: Final[int] = 111
EXPLICIT_ABSENCE_FIELD_ID: Final[str] = "guaranteed_renewal_period"
EXPERT_DISPLAY_NAME: Final[str] = "linyao"
EXPERT_PRINCIPAL_ID: Final[str] = "human:linyao"
EXPERT_RECEIPT_CONTRACT_ID: Final[str] = "schema67-596-2-expert-approval-receipt.v1"
APPROVED_EXPERT_RECEIPT_ISSUED_AT: Final[datetime] = datetime(2026, 8, 7, 11, 59, tzinfo=UTC)
APPROVED_EXPERT_RECEIPT_EXPIRES_AT: Final[datetime] = datetime(2027, 8, 7, 12, 0, tzinfo=UTC)
APPROVED_EXPERT_RECEIPT_SHA256: Final[str] = (
    "2cc6d0045b8d0c8c0b16eba4b91a403bd3f12371c8d207f6ebc5e888be30260c"
)
_EXPERT_SUBJECT_OBJECT_TYPE: Final[str] = "schema67-596-2-expert-approval-subject.v1"
_EXPERT_RECEIPT_OBJECT_TYPE: Final[str] = "schema67-596-2-expert-approval-receipt.v1"
_REFERENCE_BUNDLE_SNAPSHOT_OBJECT_TYPE: Final[str] = "schema67-596-2-reference-bundle-snapshot.v1"
_CANDIDATE_BUNDLE_OBJECT_TYPE: Final[str] = "schema67-596-1-candidate-evidence-bundle.v1"
_TOTAL_CONTROL_AUTHORITY_SNAPSHOT_OBJECT_TYPE: Final[str] = (
    "schema67-596-2-total-control-authority-snapshot.v1"
)
_SEMANTIC_COMPARATOR_AUTHORITY_OBJECT_TYPE: Final[str] = "schema67-semantic-comparator-authority.v1"
_SEMANTIC_COMPARISON_OBJECT_TYPE: Final[str] = "schema67-semantic-authority-comparison.v1"
_SEMANTIC_FIELD_EVALUATION_OBJECT_TYPE: Final[str] = "schema67-semantic-field-evaluation.v1"
_SEMANTIC_EVALUATION_RECEIPT_OBJECT_TYPE: Final[str] = "schema67-semantic-evaluation-receipt.v1"
_LANE_C_REPORT_GATE_OBJECT_TYPE: Final[str] = "schema67-lane-c-report-gate.v1"
_SCHEMA67_CANDIDATE_OBJECT_TYPE: Final[str] = "schema67-candidate.v2"
_SCHEMA67_CANDIDATE_FACTORY_TOKEN: Final[object] = object()
_REPORT_COMPILER_DEPENDENCY_TREE_SHA1: Final[str] = "bf38d51bef0b6d1ae119bb0535e8ff0dc9463c53"
_SCHEMA67_SOURCE_ROLE_AUTHORITY: Final[tuple[tuple[str, str], ...]] = (
    (
        "terms",
        "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
    ),
    (
        "brochure",
        "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
    ),
    (
        "rate_table",
        "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
    ),
)
_SEMANTIC_COMPARATOR_AUTHORITY_ID: Final[str] = "total-control:linyao-schema67-semantic-comparator"
_SEMANTIC_COMPARATOR_VERSION: Final[str] = "schema67-explicit-authority.v1"
_APPROVED_A_SCHEMA_SNAPSHOT_SHA256: Final[str] = (
    "fb5f74fb870b187fdba08a18a09450f171f9b01483c8e24386ac964c28181374"
)
_APPROVED_A_SCHEMA_ROWS_SHA256: Final[str] = (
    "cb49f9e27356316a72c258b2b9030257bf434d47a988f61dc820b826c222a57c"
)
_TOTAL_CONTROL_AUTHORITY_FACTORY_SEAL: Final[object] = object()
_APPROVED_EXPLICIT_ABSENCE_QUOTE_SHA256S: Final[frozenset[str]] = frozenset(
    {
        "b19354d8b254979387b4578c4c91434c88d656506d83205abcf71ffe05b6627e",
        "c7f94b0dd880461f481daf1d55b485047779e3374d8c09013d2e1f42894dfaa2",
    }
)

ORDERED_FIELD_IDS: Final[tuple[str, ...]] = (
    "product_code",
    "product_short_name",
    "product_name",
    "sales_start_date",
    "sales_end_date",
    "product_type",
    "insurance_category",
    "sales_channels",
    "external_publication_status",
    "sales_status",
    "policy_role",
    "product_summary",
    "official_product_features",
    "target_customer_profile",
    "marketing_tagline",
    "product_overview",
    "entry_age_range",
    "insured_eligibility",
    "health_declaration_requirements",
    "geographic_eligibility_requirements",
    "social_insurance_requirement",
    "eligible_occupation_classes",
    "underwriting_method",
    "premium_payment_term",
    "premium_payment_frequency",
    "cooling_off_period",
    "waiting_period",
    "premium_grace_period",
    "coverage_period",
    "coverage_term_category",
    "surrender_and_cancellation_terms",
    "coverage_and_renewal_terms",
    "guaranteed_renewal_status",
    "guaranteed_renewal_period",
    "product_conversion_rules",
    "premium_adjustment_rules",
    "post_discontinuation_renewal_arrangement",
    "covered_risk_categories",
    "coverage_responsibilities",
    "coverage_summary",
    "cancer_medical_coverage",
    "age_segment_tags",
    "coverage_limit_category",
    "special_coverage_and_exclusion_tags",
    "exclusions",
    "pre_existing_condition_rules",
    "out_of_hospital_special_drug_coverage",
    "indemnity_principle",
    "zero_deductible_flag",
    "deductible_rules",
    "outpatient_inpatient_scope",
    "reimbursable_expense_scope",
    "reimbursement_rate_rules",
    "eligible_hospital_scope",
    "premium_medical_facility_coverage",
    "direct_billing_and_advance_payment_rules",
    "claim_application_deadline_and_documents",
    "policyholder_rights",
    "eligible_service_packages",
    "medical_service_benefits",
    "tax_qualified_status",
    "tax_benefit_rules",
    "product_bundle_rules",
    "objection_handling_scripts",
    "product_faq",
    "four_step_sales_script",
    "sales_pitch_script",
)

FIXED_UNKNOWN_FIELD_IDS: Final[tuple[str, ...]] = (
    "sales_start_date",
    "sales_end_date",
    "product_type",
    "insurance_category",
    "sales_channels",
    "external_publication_status",
    "sales_status",
    "policy_role",
    "marketing_tagline",
    "geographic_eligibility_requirements",
    "premium_grace_period",
    "product_conversion_rules",
    "premium_adjustment_rules",
    "eligible_service_packages",
    "tax_qualified_status",
    "tax_benefit_rules",
    "product_bundle_rules",
    "objection_handling_scripts",
    "product_faq",
    "four_step_sales_script",
    "sales_pitch_script",
)
FIXED_UNKNOWN_FIELD_IDS_SHA256: Final[str] = (
    "419b8dc4b37db18dccdfca95aace39ce17046c8f6809cdc87f1bd7f8e598e9b5"
)

_EXPECTED_KNOWN_FIELD_IDS: Final[tuple[str, ...]] = tuple(
    field_id for field_id in ORDERED_FIELD_IDS if field_id not in FIXED_UNKNOWN_FIELD_IDS
)

if hashlib.sha256(("\n".join(ORDERED_FIELD_IDS) + "\n").encode()).hexdigest() != (
    ORDERED_FIELD_IDS_SHA256
):
    raise RuntimeError("Schema67 ordered field authority drift")
if (
    hashlib.sha256(("\n".join(FIXED_UNKNOWN_FIELD_IDS) + "\n").encode()).hexdigest()
    != FIXED_UNKNOWN_FIELD_IDS_SHA256
):
    raise RuntimeError("Schema67 fixed unknown field authority drift")
if (
    len(FIXED_UNKNOWN_FIELD_IDS) != 21
    or len(set(FIXED_UNKNOWN_FIELD_IDS)) != 21
    or EXPLICIT_ABSENCE_FIELD_ID in FIXED_UNKNOWN_FIELD_IDS
):
    raise RuntimeError("Schema67 field partition invalid")

REFERENCE_BUNDLE_SNAPSHOT_SHA256: Final[str] = canonical_hash(
    _REFERENCE_BUNDLE_SNAPSHOT_OBJECT_TYPE,
    {
        "product_version_id": "596-1",
        "review_package_id": "596-2-golden-human-review",
        "workbook_sha256": WORKBOOK_SHA256,
        "schema_sha256": SCHEMA_SHA256,
        "ordered_field_ids_sha256": ORDERED_FIELD_IDS_SHA256,
        "approved_candidate_sha256": CANDIDATE_SHA256,
        "reference_evidence_fragments": REFERENCE_EVIDENCE_FRAGMENT_COUNT,
    },
)


TriState = Literal["present", "absent_explicitly", "unknown"]
AdmissionStatus = Literal[
    "PENDING_EXPERT_RECEIPT",
    "REFERENCE_APPROVED_CANDIDATE_EVIDENCE_BLOCKED",
    "READY_FOR_OFFLINE_GOLDEN_EVAL",
    "BLOCKED",
]
ExpertContentState = Literal["PENDING_RECEIPT", "VERIFIED", "BLOCKED"]
EvidenceReplayState = Literal["PASS", "BLOCKED"]
SemanticAxisVerdict = Literal["PASS", "FAIL", "PENDING"]
SemanticComparisonOutcome = Literal["EQUIVALENT", "DIFFERENT", "PENDING"]
SemanticEvaluationStatus = Literal[
    "SEMANTIC_EVALUATION_BLOCKED",
    "SEMANTIC_REVIEW_REQUIRED",
    "SEMANTIC_DOUBLE_PASS",
]
ReportGateStatus = Literal["READY", "PENDING", "BLOCKED"]


@dataclass(frozen=True, slots=True)
class ExpertApprovalProvenanceV1:
    source_thread_id: str
    conversation_id: str
    user_approval_ref: str


EXPERT_APPROVAL_PROVENANCE: Final[ExpertApprovalProvenanceV1] = ExpertApprovalProvenanceV1(
    source_thread_id="019fda9b-f72b-7661-b88f-f2ae1bb02634",
    conversation_id="019fda9b-f72b-7661-b88f-f2ae1bb02634",
    user_approval_ref="596-2-package-result-approved-without-edits",
)


@dataclass(frozen=True, slots=True)
class NamedExpertApprovalReceiptV1:
    contract_id: str
    issued_by: str
    actor_type: str
    principal_id: str
    approved_by: str
    action: str
    workbook_sha256: str
    schema_sha256: str
    ordered_field_ids_sha256: str
    candidate_sha256: str
    reference_bundle_sha256: str
    subject_sha256: str
    issued_at: datetime
    expires_at: datetime
    provenance: ExpertApprovalProvenanceV1
    receipt_sha256: str


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class Schema67AuthoritySnapshotError(ValueError):
    """Typed fail-closed error for the exact Lane A to Lane C authority bridge."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@runtime_checkable
class Schema67AuthoritySnapshotPort(Protocol):
    @property
    def workbook_sha256(self) -> str: ...

    @property
    def schema_sha256(self) -> str: ...

    @property
    def ordered_field_ids(self) -> tuple[str, ...]: ...

    @property
    def ordered_field_ids_sha256(self) -> str: ...

    @property
    def candidate_sha256(self) -> str: ...


@dataclass(frozen=True, slots=True)
class TotalControlSchema67AuthoritySnapshotV1:
    contract_id: Literal["schema67-596-2-total-control-authority-snapshot.v1"]
    product_version_id: Literal["596-1"]
    review_package_id: Literal["596-2-golden-human-review"]
    approved_by: Literal["linyao"]
    approved_schema_snapshot_sha256: str
    approved_schema_rows_sha256: str
    workbook_sha256: str
    schema_sha256: str
    ordered_field_ids: tuple[str, ...]
    ordered_field_ids_sha256: str
    candidate_sha256: str
    reference_bundle_sha256: str
    authority_snapshot_sha256: str
    _factory_seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        payload = {
            "contract_id": self.contract_id,
            "product_version_id": self.product_version_id,
            "review_package_id": self.review_package_id,
            "approved_by": self.approved_by,
            "approved_schema_snapshot_sha256": self.approved_schema_snapshot_sha256,
            "approved_schema_rows_sha256": self.approved_schema_rows_sha256,
            "workbook_sha256": self.workbook_sha256,
            "schema_sha256": self.schema_sha256,
            "ordered_field_ids": self.ordered_field_ids,
            "ordered_field_ids_sha256": self.ordered_field_ids_sha256,
            "candidate_sha256": self.candidate_sha256,
            "reference_bundle_sha256": self.reference_bundle_sha256,
        }
        if (
            self._factory_seal is not _TOTAL_CONTROL_AUTHORITY_FACTORY_SEAL
            or self.approved_schema_snapshot_sha256 != _APPROVED_A_SCHEMA_SNAPSHOT_SHA256
            or self.approved_schema_rows_sha256 != _APPROVED_A_SCHEMA_ROWS_SHA256
            or self.workbook_sha256 != WORKBOOK_SHA256
            or self.schema_sha256 != SCHEMA_SHA256
            or self.ordered_field_ids != ORDERED_FIELD_IDS
            or self.ordered_field_ids_sha256 != ORDERED_FIELD_IDS_SHA256
            or self.candidate_sha256 != CANDIDATE_SHA256
            or self.reference_bundle_sha256 != REFERENCE_BUNDLE_SNAPSHOT_SHA256
            or self.authority_snapshot_sha256
            != canonical_hash(_TOTAL_CONTROL_AUTHORITY_SNAPSHOT_OBJECT_TYPE, payload)
        ):
            raise ValueError("total-control Schema67 authority mismatch")


def make_total_control_schema67_authority_snapshot(
    *,
    approved_schema_snapshot: object,
) -> TotalControlSchema67AuthoritySnapshotV1:
    """Bridge one exact Lane A snapshot to the fixed linyao reference authority."""

    from insurance_harness.knowledge_compiler.schema_first_contracts import (
        ApprovedSchemaSnapshotV1,
    )

    try:
        if type(approved_schema_snapshot) is not ApprovedSchemaSnapshotV1:
            raise TypeError
        exact = ApprovedSchemaSnapshotV1.model_validate(
            approved_schema_snapshot.model_dump(mode="python", round_trip=True)
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise Schema67AuthoritySnapshotError("SCHEMA67_A_AUTHORITY_INVALID") from None
    ordered_field_ids = tuple(item.field_id for item in exact.fields)
    if (
        exact != approved_schema_snapshot
        or exact.snapshot_sha256 != _APPROVED_A_SCHEMA_SNAPSHOT_SHA256
        or exact.workbook_sha256 != WORKBOOK_SHA256
        or exact.schema_rows_sha256 != _APPROVED_A_SCHEMA_ROWS_SHA256
        or ordered_field_ids != ORDERED_FIELD_IDS
        or exact.ordered_field_ids_sha256 != ORDERED_FIELD_IDS_SHA256
    ):
        raise Schema67AuthoritySnapshotError("SCHEMA67_A_AUTHORITY_INVALID")
    values: dict[str, object] = {
        "contract_id": "schema67-596-2-total-control-authority-snapshot.v1",
        "product_version_id": "596-1",
        "review_package_id": "596-2-golden-human-review",
        "approved_by": EXPERT_DISPLAY_NAME,
        "approved_schema_snapshot_sha256": exact.snapshot_sha256,
        "approved_schema_rows_sha256": exact.schema_rows_sha256,
        "workbook_sha256": exact.workbook_sha256,
        "schema_sha256": SCHEMA_SHA256,
        "ordered_field_ids": ordered_field_ids,
        "ordered_field_ids_sha256": exact.ordered_field_ids_sha256,
        "candidate_sha256": CANDIDATE_SHA256,
        "reference_bundle_sha256": REFERENCE_BUNDLE_SNAPSHOT_SHA256,
    }
    try:
        return TotalControlSchema67AuthoritySnapshotV1(
            contract_id="schema67-596-2-total-control-authority-snapshot.v1",
            product_version_id="596-1",
            review_package_id="596-2-golden-human-review",
            approved_by="linyao",
            approved_schema_snapshot_sha256=exact.snapshot_sha256,
            approved_schema_rows_sha256=exact.schema_rows_sha256,
            workbook_sha256=exact.workbook_sha256,
            schema_sha256=SCHEMA_SHA256,
            ordered_field_ids=ordered_field_ids,
            ordered_field_ids_sha256=exact.ordered_field_ids_sha256,
            candidate_sha256=CANDIDATE_SHA256,
            reference_bundle_sha256=REFERENCE_BUNDLE_SNAPSHOT_SHA256,
            authority_snapshot_sha256=canonical_hash(
                _TOTAL_CONTROL_AUTHORITY_SNAPSHOT_OBJECT_TYPE, values
            ),
            _factory_seal=_TOTAL_CONTROL_AUTHORITY_FACTORY_SEAL,
        )
    except (TypeError, ValueError, ValidationError):
        raise Schema67AuthoritySnapshotError("SCHEMA67_A_AUTHORITY_INVALID") from None


def _provenance_payload(value: ExpertApprovalProvenanceV1) -> dict[str, str]:
    return {
        "source_thread_id": value.source_thread_id,
        "conversation_id": value.conversation_id,
        "user_approval_ref": value.user_approval_ref,
    }


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _receipt_payload(receipt: NamedExpertApprovalReceiptV1) -> dict[str, object]:
    return {
        "contract_id": receipt.contract_id,
        "issued_by": receipt.issued_by,
        "actor_type": receipt.actor_type,
        "principal_id": receipt.principal_id,
        "approved_by": receipt.approved_by,
        "action": receipt.action,
        "workbook_sha256": receipt.workbook_sha256,
        "schema_sha256": receipt.schema_sha256,
        "ordered_field_ids_sha256": receipt.ordered_field_ids_sha256,
        "candidate_sha256": receipt.candidate_sha256,
        "reference_bundle_sha256": receipt.reference_bundle_sha256,
        "subject_sha256": receipt.subject_sha256,
        "issued_at": _timestamp(receipt.issued_at),
        "expires_at": _timestamp(receipt.expires_at),
        "provenance": _provenance_payload(receipt.provenance),
    }


def expert_approval_subject_sha256(receipt: NamedExpertApprovalReceiptV1) -> str:
    """Recompute the one approved package subject; no generic approval scope exists."""

    return canonical_hash(
        _EXPERT_SUBJECT_OBJECT_TYPE,
        {
            "product_version_id": "596-1",
            "review_package_id": "596-2-golden-human-review",
            "workbook_sha256": receipt.workbook_sha256,
            "schema_sha256": receipt.schema_sha256,
            "ordered_field_ids_sha256": receipt.ordered_field_ids_sha256,
            "candidate_sha256": receipt.candidate_sha256,
            "reference_bundle_sha256": receipt.reference_bundle_sha256,
            "principal_id": receipt.principal_id,
            "approved_by": receipt.approved_by,
            "action": receipt.action,
            "provenance": _provenance_payload(receipt.provenance),
        },
    )


def expert_approval_receipt_sha256(
    receipt: NamedExpertApprovalReceiptV1,
) -> str:
    return canonical_hash(
        _EXPERT_RECEIPT_OBJECT_TYPE,
        _receipt_payload(receipt),
    )


class EvidenceReplayCaseV1(_FrozenModel):
    case_id: StrictStr
    field_output: FreeformFieldOutputV1
    documents: tuple[ParsedDocumentV1, ...]
    manifests: tuple[ParseManifestV1, ...]


class _EvidenceBundleContractError(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class _DerivedCandidateBundleV1:
    candidate_fields: tuple[FreeformFieldOutputV1, ...]
    canonical_cases: tuple[EvidenceReplayCaseV1, ...]
    bundle_sha256: str
    evidence_fragments_total: int


def _evidence_snapshot_sha256(value: object) -> str:
    return canonical_hash(
        "schema67-596-1-candidate-evidence-snapshot.v1",
        value,
    )


def _candidate_field_payload(output: FreeformFieldOutputV1) -> dict[str, object]:
    return {
        "product_version_id": output.product_version_id,
        "field_id": output.field_id,
        "state": output.state,
        "value_snapshot_sha256": (
            None
            if output.value_snapshot is None
            else hashlib.sha256(output.value_snapshot.encode("utf-8")).hexdigest()
        ),
        "evidence_sha256": _evidence_snapshot_sha256(
            tuple(item.model_dump(mode="python") for item in output.evidence)
        ),
    }


def _evidence_case_payload(case: EvidenceReplayCaseV1) -> dict[str, object]:
    output = case.field_output
    value_sha256 = (
        None
        if output.value_snapshot is None
        else hashlib.sha256(output.value_snapshot.encode("utf-8")).hexdigest()
    )
    evidence_sha256 = _evidence_snapshot_sha256(
        tuple(item.model_dump(mode="python") for item in output.evidence)
    )
    return {
        "case_id": case.case_id,
        "product_version_id": output.product_version_id,
        "field_id": output.field_id,
        "state": output.state,
        "value_snapshot_sha256": value_sha256,
        "evidence_sha256": evidence_sha256,
        "parsed_document_hashes": tuple(document.document_hash for document in case.documents),
        "parse_manifest_hashes": tuple(manifest.manifest_hash for manifest in case.manifests),
    }


def _derive_candidate_bundle(
    candidate_fields: object,
    evidence_cases: object,
) -> _DerivedCandidateBundleV1:
    if (
        type(candidate_fields) is not tuple
        or len(candidate_fields) != len(ORDERED_FIELD_IDS)
        or any(type(output) is not FreeformFieldOutputV1 for output in candidate_fields)
    ):
        raise _EvidenceBundleContractError("CANDIDATE_FIELD_MEMBERSHIP_INVALID")
    checked_fields = candidate_fields
    if tuple(output.field_id for output in checked_fields) != ORDERED_FIELD_IDS:
        raise _EvidenceBundleContractError("CANDIDATE_FIELD_MEMBERSHIP_INVALID")

    known_outputs: dict[str, FreeformFieldOutputV1] = {}
    for output in checked_fields:
        if output.product_version_id != "596-1":
            raise _EvidenceBundleContractError("CANDIDATE_PRODUCT_IDENTITY_INVALID")
        if output.field_id in FIXED_UNKNOWN_FIELD_IDS:
            if output.state != "unknown" or output.value_snapshot is not None or output.evidence:
                raise _EvidenceBundleContractError("CANDIDATE_DEFERRED_FIELD_INVALID")
            continue
        if output.field_id == EXPLICIT_ABSENCE_FIELD_ID:
            if output.state == "unknown":
                if output.value_snapshot is not None or output.evidence:
                    raise _EvidenceBundleContractError("CANDIDATE_UNKNOWN_FIELD_INVALID")
                continue
            if output.state != "absent_explicitly":
                raise _EvidenceBundleContractError("CANDIDATE_ABSENCE_STATE_INVALID")
            if not (
                {item.quote_snapshot_sha256 for item in output.evidence}
                & _APPROVED_EXPLICIT_ABSENCE_QUOTE_SHA256S
            ):
                raise _EvidenceBundleContractError("CANDIDATE_EXPLICIT_ABSENCE_NOT_PROVEN")
        elif output.state not in ("present", "unknown"):
            raise _EvidenceBundleContractError("CANDIDATE_FIELD_STATE_INVALID")
        if output.state == "unknown":
            if output.value_snapshot is not None or output.evidence:
                raise _EvidenceBundleContractError("CANDIDATE_UNKNOWN_FIELD_INVALID")
            continue
        if type(output.value_snapshot) is not str or not output.evidence:
            raise _EvidenceBundleContractError("CANDIDATE_KNOWN_FIELD_INVALID")
        known_outputs[output.field_id] = output

    if type(evidence_cases) is not tuple:
        raise _EvidenceBundleContractError("EVIDENCE_REPLAY_MEMBERSHIP_INVALID")
    if any(type(case) is not EvidenceReplayCaseV1 for case in evidence_cases):
        raise _EvidenceBundleContractError("EVIDENCE_REPLAY_MEMBERSHIP_INVALID")
    checked_cases = evidence_cases
    case_ids = tuple(case.case_id for case in checked_cases)
    if any(type(case_id) is not str or not case_id for case_id in case_ids) or len(
        set(case_ids)
    ) != len(case_ids):
        raise _EvidenceBundleContractError("EVIDENCE_REPLAY_MEMBERSHIP_INVALID")
    canonical_cases = tuple(sorted(checked_cases, key=lambda case: case.case_id))
    evidence_by_field: dict[str, list[str]] = {}
    for case in canonical_cases:
        output = case.field_output
        if output.product_version_id != "596-1":
            raise _EvidenceBundleContractError("EVIDENCE_PRODUCT_IDENTITY_INVALID")
        candidate_output = known_outputs.get(output.field_id)
        if candidate_output is None:
            raise _EvidenceBundleContractError("EVIDENCE_FIELD_MEMBERSHIP_INVALID")
        if (
            output.state != candidate_output.state
            or output.value_snapshot != candidate_output.value_snapshot
            or not output.evidence
        ):
            raise _EvidenceBundleContractError("EVIDENCE_CASE_BINDING_INVALID")
        evidence_by_field.setdefault(output.field_id, []).extend(
            _evidence_snapshot_sha256(item.model_dump(mode="python")) for item in output.evidence
        )
    if set(evidence_by_field) != set(known_outputs):
        raise _EvidenceBundleContractError("EVIDENCE_FIELD_MEMBERSHIP_INVALID")
    for field_id, candidate_output in known_outputs.items():
        candidate_evidence = sorted(
            _evidence_snapshot_sha256(item.model_dump(mode="python"))
            for item in candidate_output.evidence
        )
        case_evidence = sorted(evidence_by_field[field_id])
        if candidate_evidence != case_evidence or len(case_evidence) != len(set(case_evidence)):
            raise _EvidenceBundleContractError("EVIDENCE_CASE_BINDING_INVALID")
    try:
        bundle_hash = canonical_hash(
            _CANDIDATE_BUNDLE_OBJECT_TYPE,
            {
                "candidate_fields": tuple(
                    _candidate_field_payload(output) for output in checked_fields
                ),
                "evidence_cases": tuple(_evidence_case_payload(case) for case in canonical_cases),
            },
        )
    except (AttributeError, TypeError, ValueError):
        raise _EvidenceBundleContractError("EVIDENCE_BUNDLE_ENCODING_INVALID") from None
    return _DerivedCandidateBundleV1(
        candidate_fields=checked_fields,
        canonical_cases=canonical_cases,
        bundle_sha256=bundle_hash,
        evidence_fragments_total=sum(len(case.field_output.evidence) for case in canonical_cases),
    )


def candidate_evidence_bundle_sha256(
    candidate_fields: tuple[FreeformFieldOutputV1, ...],
    evidence_cases: tuple[EvidenceReplayCaseV1, ...],
) -> str:
    """Bind one frozen Lane B candidate independently from reference authority."""

    return _derive_candidate_bundle(
        candidate_fields,
        evidence_cases,
    ).bundle_sha256


class EvidenceReplayReviewItemV1(_FrozenModel):
    field_id: StrictStr
    case_id: StrictStr
    reason_code: StrictStr


class ExpertGoldenAdmissionResultV1(_FrozenModel):
    status: AdmissionStatus
    reason_codes: tuple[StrictStr, ...]
    reference_content_authority: ExpertContentState
    evidence_replay: EvidenceReplayState
    evidence_fragments_total: int
    evidence_fragments_passed: int
    evidence_fragments_failed: int
    evidence_receipt_hashes: tuple[StrictStr, ...]
    review_items: tuple[EvidenceReplayReviewItemV1, ...]
    publishable_field_ids: tuple[StrictStr, ...]
    effective_unknown_field_ids: tuple[StrictStr, ...]
    candidate_bundle_sha256: StrictStr | None
    reference_bundle_sha256: StrictStr | None
    reference_subject_sha256: StrictStr | None
    reference_receipt_sha256: StrictStr | None
    semantic_eval_allowed: StrictBool
    wiki_admission_allowed: StrictBool


class SemanticComparatorAuthorityV1(_FrozenModel):
    contract_id: Literal["schema67-semantic-comparator-authority.v1"]
    authority_id: Literal["total-control:linyao-schema67-semantic-comparator"]
    comparator_version: Literal["schema67-explicit-authority.v1"]
    workbook_sha256: StrictStr
    schema_sha256: StrictStr
    ordered_field_ids_sha256: StrictStr
    approved_candidate_sha256: StrictStr
    reference_bundle_sha256: StrictStr
    reference_fields_authority_sha256: StrictStr
    expert_subject_sha256: StrictStr
    expert_receipt_sha256: StrictStr
    authority_sha256: StrictStr


class SemanticAuthorityComparisonV1(_FrozenModel):
    contract_id: Literal["schema67-semantic-authority-comparison.v1"]
    field_id: StrictStr
    candidate_bundle_sha256: StrictStr
    candidate_state: TriState
    candidate_value_sha256: StrictStr | None
    reference_state: TriState
    reference_value_sha256: StrictStr | None
    required_evidence_source_sha256s: tuple[StrictStr, ...]
    semantic_outcome: SemanticComparisonOutcome
    comparator_authority_sha256: StrictStr
    comparison_sha256: StrictStr


@runtime_checkable
class SemanticAuthorityComparatorPort(Protocol):
    @property
    def authority(self) -> SemanticComparatorAuthorityV1: ...

    def compare(
        self,
        *,
        field_id: str,
        candidate_state: TriState,
        candidate_value_sha256: str | None,
        candidate_bundle_sha256: str,
    ) -> SemanticAuthorityComparisonV1: ...


class SemanticFieldEvaluationV1(_FrozenModel):
    field_id: StrictStr
    correctness: SemanticAxisVerdict
    completeness: SemanticAxisVerdict
    state_consistent: StrictBool | None
    required_evidence_source_sha256s: tuple[StrictStr, ...]
    covered_evidence_source_sha256s: tuple[StrictStr, ...]
    review_reason_codes: tuple[StrictStr, ...]
    comparison_receipt_sha256: StrictStr | None
    field_evaluation_sha256: StrictStr


class SemanticEvaluationReviewItemV1(_FrozenModel):
    field_id: StrictStr
    reason_code: StrictStr


class Schema67SemanticEvaluationResultV1(_FrozenModel):
    status: SemanticEvaluationStatus
    reason_codes: tuple[StrictStr, ...]
    base_admission_status: AdmissionStatus
    field_evaluations: tuple[SemanticFieldEvaluationV1, ...]
    review_items: tuple[SemanticEvaluationReviewItemV1, ...]
    evidence_receipt_hashes: tuple[StrictStr, ...]
    candidate_bundle_sha256: StrictStr | None
    reference_bundle_sha256: StrictStr | None
    reference_subject_sha256: StrictStr | None
    reference_receipt_sha256: StrictStr | None
    comparator_authority_sha256: StrictStr | None
    semantic_eval_allowed: StrictBool
    wiki_admission_allowed: StrictBool
    publishable_field_ids: tuple[StrictStr, ...]
    evaluation_receipt_sha256: StrictStr


class LaneCReportGateError(ValueError):
    """Typed fail-closed error for Candidate v2 to Lane C gate composition."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _ReportGateSeal(tuple[str]):
    __slots__ = ()

    def __new__(
        cls,
        token: object,
        receipt_sha256: str,
    ) -> _ReportGateSeal:
        if token is not _LANE_C_REPORT_GATE_FACTORY_TOKEN:
            raise ValueError("LANE_C_REPORT_GATE_SEAL_INVALID")
        return tuple.__new__(cls, (receipt_sha256,))

    @property
    def receipt_sha256(self) -> str:
        return self[0]


_LANE_C_REPORT_GATE_FACTORY_TOKEN: Final[object] = object()


@dataclass(frozen=True, slots=True)
class Schema67ReportGateRowV1:
    field_id: str
    state: TriState
    evidence_057_status: Literal["PASS", "BLOCKED", "NOT_REQUIRED"]
    correctness: SemanticAxisVerdict
    completeness: SemanticAxisVerdict
    state_consistent: bool | None
    review_reason_codes: tuple[str, ...]
    candidate_evidence_receipt_sha256: str | None
    semantic_decision_receipt_sha256: str | None


@dataclass(frozen=True, slots=True)
class Schema67ReportGateV1:
    contract_id: Literal["schema67-lane-c-report-gate.v1"]
    status: ReportGateStatus
    candidate_v2_sha256: str
    candidate_bundle_sha256: str
    accepted_batch_receipt_sha256: str
    task_receipt_hashes: tuple[str, ...]
    candidate_evidence_receipt_hashes: tuple[str, ...]
    live_evidence_receipt_hashes: tuple[str, ...]
    reference_bundle_sha256: str
    reference_subject_sha256: str
    reference_receipt_sha256: str
    comparator_authority_sha256: str
    semantic_decision_receipt_hashes: tuple[str, ...]
    semantic_evaluation_receipt_sha256: str
    rows: tuple[Schema67ReportGateRowV1, ...]
    semantic_eval_allowed: bool
    wiki_admission_allowed: bool
    publishable_field_ids: tuple[str, ...]
    gate_receipt_sha256: str
    _factory_seal: _ReportGateSeal = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _validate_schema67_report_gate(self)


def semantic_comparator_authority_sha256(
    authority: SemanticComparatorAuthorityV1,
) -> str:
    return canonical_hash(
        _SEMANTIC_COMPARATOR_AUTHORITY_OBJECT_TYPE,
        {
            "contract_id": authority.contract_id,
            "authority_id": authority.authority_id,
            "comparator_version": authority.comparator_version,
            "workbook_sha256": authority.workbook_sha256,
            "schema_sha256": authority.schema_sha256,
            "ordered_field_ids_sha256": authority.ordered_field_ids_sha256,
            "approved_candidate_sha256": authority.approved_candidate_sha256,
            "reference_bundle_sha256": authority.reference_bundle_sha256,
            "reference_fields_authority_sha256": (authority.reference_fields_authority_sha256),
            "expert_subject_sha256": authority.expert_subject_sha256,
            "expert_receipt_sha256": authority.expert_receipt_sha256,
        },
    )


def semantic_authority_comparison_sha256(
    comparison: SemanticAuthorityComparisonV1,
) -> str:
    return canonical_hash(
        _SEMANTIC_COMPARISON_OBJECT_TYPE,
        {
            "contract_id": comparison.contract_id,
            "field_id": comparison.field_id,
            "candidate_bundle_sha256": comparison.candidate_bundle_sha256,
            "candidate_state": comparison.candidate_state,
            "candidate_value_sha256": comparison.candidate_value_sha256,
            "reference_state": comparison.reference_state,
            "reference_value_sha256": comparison.reference_value_sha256,
            "required_evidence_source_sha256s": (comparison.required_evidence_source_sha256s),
            "semantic_outcome": comparison.semantic_outcome,
            "comparator_authority_sha256": comparison.comparator_authority_sha256,
        },
    )


def _result(
    *,
    status: AdmissionStatus,
    reasons: tuple[str, ...],
    reference: ExpertContentState,
    evidence: EvidenceReplayState,
    total: int = 0,
    passed: int = 0,
    receipts: tuple[str, ...] = (),
    review_items: tuple[EvidenceReplayReviewItemV1, ...] = (),
    publishable: tuple[str, ...] = (),
    unknown: tuple[str, ...] = (),
    candidate_bundle_sha256: str | None = None,
    reference_bundle_sha256: str | None = None,
    reference_subject_sha256: str | None = None,
    reference_receipt_sha256: str | None = None,
    semantic_eval_allowed: bool = False,
    wiki_admission_allowed: bool = False,
) -> ExpertGoldenAdmissionResultV1:
    return ExpertGoldenAdmissionResultV1(
        status=status,
        reason_codes=reasons,
        reference_content_authority=reference,
        evidence_replay=evidence,
        evidence_fragments_total=total,
        evidence_fragments_passed=passed,
        evidence_fragments_failed=total - passed,
        evidence_receipt_hashes=receipts,
        review_items=review_items,
        publishable_field_ids=publishable,
        effective_unknown_field_ids=unknown,
        candidate_bundle_sha256=candidate_bundle_sha256,
        reference_bundle_sha256=reference_bundle_sha256,
        reference_subject_sha256=reference_subject_sha256,
        reference_receipt_sha256=reference_receipt_sha256,
        semantic_eval_allowed=semantic_eval_allowed,
        wiki_admission_allowed=wiki_admission_allowed,
    )


def _snapshot_is_exact(snapshot: object) -> bool:
    try:
        if type(snapshot) is not TotalControlSchema67AuthoritySnapshotV1:
            return False
        exact = replace(snapshot)
        return (
            exact == snapshot
            and isinstance(exact, Schema67AuthoritySnapshotPort)
            and type(exact.workbook_sha256) is str
            and snapshot.workbook_sha256 == WORKBOOK_SHA256
            and type(exact.schema_sha256) is str
            and snapshot.schema_sha256 == SCHEMA_SHA256
            and type(exact.ordered_field_ids) is tuple
            and snapshot.ordered_field_ids == ORDERED_FIELD_IDS
            and type(exact.ordered_field_ids_sha256) is str
            and snapshot.ordered_field_ids_sha256 == ORDERED_FIELD_IDS_SHA256
            and type(exact.candidate_sha256) is str
            and snapshot.candidate_sha256 == CANDIDATE_SHA256
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        return False


def _valid_time(value: object) -> TypeGuard[datetime]:
    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


def _is_sha256(value: object) -> TypeGuard[str]:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def make_total_control_named_expert_approval_receipt() -> NamedExpertApprovalReceiptV1:
    """Return the one pre-approved linyao receipt; callers choose no authority."""

    unsigned = NamedExpertApprovalReceiptV1(
        contract_id=EXPERT_RECEIPT_CONTRACT_ID,
        issued_by="total-control",
        actor_type="human",
        principal_id=EXPERT_PRINCIPAL_ID,
        approved_by=EXPERT_DISPLAY_NAME,
        action="accept_package_result_without_edits",
        workbook_sha256=WORKBOOK_SHA256,
        schema_sha256=SCHEMA_SHA256,
        ordered_field_ids_sha256=ORDERED_FIELD_IDS_SHA256,
        candidate_sha256=CANDIDATE_SHA256,
        reference_bundle_sha256=REFERENCE_BUNDLE_SNAPSHOT_SHA256,
        subject_sha256="",
        issued_at=APPROVED_EXPERT_RECEIPT_ISSUED_AT,
        expires_at=APPROVED_EXPERT_RECEIPT_EXPIRES_AT,
        provenance=EXPERT_APPROVAL_PROVENANCE,
        receipt_sha256="",
    )
    bound = replace(
        unsigned,
        subject_sha256=expert_approval_subject_sha256(unsigned),
    )
    receipt = replace(
        bound,
        receipt_sha256=expert_approval_receipt_sha256(bound),
    )
    if receipt.receipt_sha256 != APPROVED_EXPERT_RECEIPT_SHA256:
        raise ValueError("EXPERT_RECEIPT_IDENTITY_MISMATCH")
    return receipt


def _verify_expert_receipt(
    *,
    receipt: object,
    observed_at: object,
) -> str | None:
    if type(receipt) is not NamedExpertApprovalReceiptV1:
        return "EXPERT_RECEIPT_MALFORMED"
    scalar_values = (
        receipt.contract_id,
        receipt.issued_by,
        receipt.actor_type,
        receipt.principal_id,
        receipt.approved_by,
        receipt.action,
        receipt.workbook_sha256,
        receipt.schema_sha256,
        receipt.ordered_field_ids_sha256,
        receipt.candidate_sha256,
        receipt.reference_bundle_sha256,
        receipt.subject_sha256,
        receipt.receipt_sha256,
    )
    if any(type(value) is not str for value in scalar_values):
        return "EXPERT_RECEIPT_MALFORMED"
    if (
        type(receipt.provenance) is not ExpertApprovalProvenanceV1
        or any(
            type(value) is not str
            for value in (
                receipt.provenance.source_thread_id,
                receipt.provenance.conversation_id,
                receipt.provenance.user_approval_ref,
            )
        )
        or not _valid_time(observed_at)
        or not _valid_time(receipt.issued_at)
        or not _valid_time(receipt.expires_at)
    ):
        return "EXPERT_RECEIPT_MALFORMED"
    if (
        receipt.issued_by != "total-control"
        or receipt.actor_type != "human"
        or receipt.principal_id != EXPERT_PRINCIPAL_ID
        or receipt.approved_by != EXPERT_DISPLAY_NAME
        or receipt.action != "accept_package_result_without_edits"
        or receipt.provenance != EXPERT_APPROVAL_PROVENANCE
    ):
        return "EXPERT_RECEIPT_AUTHORITY_INVALID"
    if (
        receipt.contract_id != EXPERT_RECEIPT_CONTRACT_ID
        or receipt.workbook_sha256 != WORKBOOK_SHA256
        or receipt.schema_sha256 != SCHEMA_SHA256
        or receipt.ordered_field_ids_sha256 != ORDERED_FIELD_IDS_SHA256
        or receipt.candidate_sha256 != CANDIDATE_SHA256
        or receipt.reference_bundle_sha256 != REFERENCE_BUNDLE_SNAPSHOT_SHA256
    ):
        return "EXPERT_RECEIPT_BINDING_MISMATCH"
    if not all(
        _is_sha256(value)
        for value in (
            receipt.workbook_sha256,
            receipt.schema_sha256,
            receipt.ordered_field_ids_sha256,
            receipt.candidate_sha256,
            receipt.reference_bundle_sha256,
            receipt.subject_sha256,
            receipt.receipt_sha256,
        )
    ):
        return "EXPERT_RECEIPT_MALFORMED"
    if (
        receipt.expires_at.astimezone(UTC) <= receipt.issued_at.astimezone(UTC)
        or observed_at.astimezone(UTC) < receipt.issued_at.astimezone(UTC)
        or observed_at.astimezone(UTC) >= receipt.expires_at.astimezone(UTC)
    ):
        return "EXPERT_RECEIPT_STALE"
    try:
        expected_subject = expert_approval_subject_sha256(receipt)
        expected_receipt = expert_approval_receipt_sha256(receipt)
    except (TypeError, ValueError):
        return "EXPERT_RECEIPT_MALFORMED"
    if receipt.subject_sha256 != expected_subject:
        return "EXPERT_RECEIPT_BINDING_MISMATCH"
    if receipt.receipt_sha256 != expected_receipt:
        return "EXPERT_RECEIPT_HASH_MISMATCH"
    if (
        receipt.issued_at != APPROVED_EXPERT_RECEIPT_ISSUED_AT
        or receipt.expires_at != APPROVED_EXPERT_RECEIPT_EXPIRES_AT
        or receipt.receipt_sha256 != APPROVED_EXPERT_RECEIPT_SHA256
    ):
        return "EXPERT_RECEIPT_IDENTITY_MISMATCH"
    return None


def validate_total_control_named_expert_approval_receipt(
    *,
    receipt: object,
    observed_at: object,
) -> NamedExpertApprovalReceiptV1:
    """Replay the exact linyao package receipt for downstream Lane C gates."""

    reason = _verify_expert_receipt(receipt=receipt, observed_at=observed_at)
    if reason is not None:
        raise Schema67AuthoritySnapshotError(reason)
    assert type(receipt) is NamedExpertApprovalReceiptV1
    return receipt


def _semantic_authority_is_exact(
    comparator: object,
) -> TypeGuard[SemanticAuthorityComparatorPort]:
    try:
        from insurance_harness.goldenset.schema67_semantic_comparator_596_2 import (
            validate_total_control_schema67_semantic_comparator,
        )

        if validate_total_control_schema67_semantic_comparator(comparator) is not comparator:
            return False
        if not isinstance(comparator, SemanticAuthorityComparatorPort):
            return False
        authority = comparator.authority
        if type(authority) is not SemanticComparatorAuthorityV1:
            return False
        exact = SemanticComparatorAuthorityV1.model_validate(
            authority.model_dump(mode="python", round_trip=True)
        )
        return (
            exact == authority
            and authority.contract_id == _SEMANTIC_COMPARATOR_AUTHORITY_OBJECT_TYPE
            and authority.authority_id == _SEMANTIC_COMPARATOR_AUTHORITY_ID
            and authority.comparator_version == _SEMANTIC_COMPARATOR_VERSION
            and authority.workbook_sha256 == WORKBOOK_SHA256
            and authority.schema_sha256 == SCHEMA_SHA256
            and authority.ordered_field_ids_sha256 == ORDERED_FIELD_IDS_SHA256
            and authority.approved_candidate_sha256 == CANDIDATE_SHA256
            and authority.reference_bundle_sha256 == REFERENCE_BUNDLE_SNAPSHOT_SHA256
            and all(
                _is_sha256(value)
                for value in (
                    authority.workbook_sha256,
                    authority.schema_sha256,
                    authority.ordered_field_ids_sha256,
                    authority.approved_candidate_sha256,
                    authority.reference_bundle_sha256,
                    authority.reference_fields_authority_sha256,
                    authority.expert_subject_sha256,
                    authority.expert_receipt_sha256,
                    authority.authority_sha256,
                )
            )
            and authority.authority_sha256 == semantic_comparator_authority_sha256(authority)
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        return False


def _semantic_comparison_is_exact(
    comparison: object,
    *,
    field_output: FreeformFieldOutputV1,
    candidate_bundle_sha256: str,
    authority_sha256: str,
) -> TypeGuard[SemanticAuthorityComparisonV1]:
    try:
        if type(comparison) is not SemanticAuthorityComparisonV1:
            return False
        exact = SemanticAuthorityComparisonV1.model_validate(
            comparison.model_dump(mode="python", round_trip=True)
        )
        candidate_value_sha256 = (
            None
            if field_output.value_snapshot is None
            else hashlib.sha256(field_output.value_snapshot.encode("utf-8")).hexdigest()
        )
        required_sources = comparison.required_evidence_source_sha256s
        return (
            exact == comparison
            and comparison.contract_id == _SEMANTIC_COMPARISON_OBJECT_TYPE
            and comparison.field_id == field_output.field_id
            and comparison.candidate_bundle_sha256 == candidate_bundle_sha256
            and comparison.candidate_state == field_output.state
            and comparison.candidate_value_sha256 == candidate_value_sha256
            and comparison.comparator_authority_sha256 == authority_sha256
            and type(required_sources) is tuple
            and required_sources == tuple(sorted(set(required_sources)))
            and all(_is_sha256(value) for value in required_sources)
            and (
                (comparison.reference_state == "unknown")
                == (comparison.reference_value_sha256 is None)
            )
            and (
                comparison.reference_value_sha256 is None
                or _is_sha256(comparison.reference_value_sha256)
            )
            and _is_sha256(comparison.comparison_sha256)
            and comparison.comparison_sha256 == semantic_authority_comparison_sha256(comparison)
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        return False


def _field_evaluation(
    *,
    field_id: str,
    correctness: SemanticAxisVerdict,
    completeness: SemanticAxisVerdict,
    state_consistent: bool | None,
    required_sources: tuple[str, ...] = (),
    covered_sources: tuple[str, ...] = (),
    reasons: tuple[str, ...] = (),
    comparison_receipt_sha256: str | None = None,
) -> SemanticFieldEvaluationV1:
    payload: dict[str, object] = {
        "field_id": field_id,
        "correctness": correctness,
        "completeness": completeness,
        "state_consistent": state_consistent,
        "required_evidence_source_sha256s": required_sources,
        "covered_evidence_source_sha256s": covered_sources,
        "review_reason_codes": reasons,
        "comparison_receipt_sha256": comparison_receipt_sha256,
    }
    return SemanticFieldEvaluationV1(
        field_id=field_id,
        correctness=correctness,
        completeness=completeness,
        state_consistent=state_consistent,
        required_evidence_source_sha256s=required_sources,
        covered_evidence_source_sha256s=covered_sources,
        review_reason_codes=reasons,
        comparison_receipt_sha256=comparison_receipt_sha256,
        field_evaluation_sha256=canonical_hash(_SEMANTIC_FIELD_EVALUATION_OBJECT_TYPE, payload),
    )


def _semantic_result(
    *,
    status: SemanticEvaluationStatus,
    reasons: tuple[str, ...],
    base: ExpertGoldenAdmissionResultV1,
    evaluations: tuple[SemanticFieldEvaluationV1, ...] = (),
    comparator_authority_sha256: str | None = None,
    semantic_eval_allowed: bool = False,
    wiki_admission_allowed: bool = False,
    publishable: tuple[str, ...] = (),
) -> Schema67SemanticEvaluationResultV1:
    review_items = tuple(
        SemanticEvaluationReviewItemV1(
            field_id=evaluation.field_id,
            reason_code=reason,
        )
        for evaluation in evaluations
        for reason in evaluation.review_reason_codes
    )
    receipt_payload: dict[str, object] = {
        "status": status,
        "reason_codes": reasons,
        "base_admission_status": base.status,
        "candidate_bundle_sha256": base.candidate_bundle_sha256,
        "reference_bundle_sha256": base.reference_bundle_sha256,
        "reference_subject_sha256": base.reference_subject_sha256,
        "reference_receipt_sha256": base.reference_receipt_sha256,
        "evidence_receipt_hashes": base.evidence_receipt_hashes,
        "comparator_authority_sha256": comparator_authority_sha256,
        "field_evaluation_sha256s": tuple(
            evaluation.field_evaluation_sha256 for evaluation in evaluations
        ),
        "semantic_eval_allowed": semantic_eval_allowed,
        "wiki_admission_allowed": wiki_admission_allowed,
        "publishable_field_ids": publishable,
    }
    return Schema67SemanticEvaluationResultV1(
        status=status,
        reason_codes=reasons,
        base_admission_status=base.status,
        field_evaluations=evaluations,
        review_items=review_items,
        evidence_receipt_hashes=base.evidence_receipt_hashes,
        candidate_bundle_sha256=base.candidate_bundle_sha256,
        reference_bundle_sha256=base.reference_bundle_sha256,
        reference_subject_sha256=base.reference_subject_sha256,
        reference_receipt_sha256=base.reference_receipt_sha256,
        comparator_authority_sha256=comparator_authority_sha256,
        semantic_eval_allowed=semantic_eval_allowed,
        wiki_admission_allowed=wiki_admission_allowed,
        publishable_field_ids=publishable,
        evaluation_receipt_sha256=canonical_hash(
            _SEMANTIC_EVALUATION_RECEIPT_OBJECT_TYPE, receipt_payload
        ),
    )


@dataclass(frozen=True, slots=True)
class _CandidateV2Custody:
    candidate_sha256: str
    fields: tuple[FreeformFieldOutputV1, ...]
    evidence_receipts: tuple[FreeformEvidenceBindingReceiptV1, ...]
    batch_receipt: Schema67BatchExecutionReceiptV1
    demoted_field_ids: tuple[str, ...]


class _CandidateV2Seal(tuple[str]):
    __slots__ = ()

    def __new__(cls, token: object, candidate_sha256: str) -> _CandidateV2Seal:
        if token is not _SCHEMA67_CANDIDATE_FACTORY_TOKEN:
            raise LaneCReportGateError("CANDIDATE_V2_SEAL_INVALID")
        return tuple.__new__(cls, (candidate_sha256,))

    @property
    def candidate_sha256(self) -> str:
        return self[0]


def _prepared_task_payload(task: Schema67PreparedTaskV1) -> dict[str, object]:
    return {
        "task_key": task.task_key,
        "task_kind": task.task_kind,
        "source_tasks": tuple(
            item.model_dump(mode="python", round_trip=True) for item in task.source_tasks
        ),
        "initial_attempts": tuple(
            item.model_dump(mode="python", round_trip=True) for item in task.initial_attempts
        ),
        "field_prompts": tuple(
            item.model_dump(mode="python", round_trip=True) for item in task.field_prompts
        ),
        "provider_task_sha256": task.provider_task_sha256,
        "provider_attempt_sha256": task.provider_attempt_sha256,
        "execution_plan_sha256": task.execution_plan_sha256,
        "task_slice_sha256": task.task_slice_sha256,
    }


def _task_execution_payload(execution: DeepSeekTaskExecutionV1) -> dict[str, object]:
    if type(execution.initial) is not Schema67BoundAttemptV1:
        raise LaneCReportGateError("CANDIDATE_TASK_CUSTODY_INVALID")
    response_repair = execution.response_contract_repair
    evidence_repair = execution.evidence_repair
    if (
        response_repair is not None
        and type(response_repair) is not ResponseContractRepairResolutionV2
    ) or (evidence_repair is not None and type(evidence_repair) is not EvidenceRepairTraceV2):
        raise LaneCReportGateError("CANDIDATE_TASK_CUSTODY_INVALID")
    return {
        "initial": execution.initial.model_dump(mode="python", round_trip=True),
        "initial_outputs": tuple(
            item.model_dump(mode="python", round_trip=True) for item in execution.initial_outputs
        ),
        "final_outputs": tuple(
            item.model_dump(mode="python", round_trip=True) for item in execution.final_outputs
        ),
        "evidence_receipts": tuple(
            item.model_dump(mode="python", round_trip=True) for item in execution.evidence_receipts
        ),
        "response_contract_repair": (
            None
            if response_repair is None
            else response_repair.model_dump(mode="python", round_trip=True)
        ),
        "evidence_repair": (
            None
            if evidence_repair is None
            else evidence_repair.model_dump(mode="python", round_trip=True)
        ),
        "receipt": execution.receipt.model_dump(mode="python", round_trip=True),
    }


def _batch_execution_payload(batch: Schema67BatchExecutionV1) -> dict[str, object]:
    return {
        "executions": tuple(_task_execution_payload(item) for item in batch.executions),
        "receipt": batch.receipt.model_dump(mode="python", round_trip=True),
    }


def _candidate_fields(
    batch: Schema67BatchExecutionV1,
    execution_plan: Schema67ExecutionPlanV1,
) -> tuple[FreeformFieldOutputV1, ...]:
    provider_outputs = {
        output.field_id: output
        for execution in batch.executions
        for output in execution.final_outputs
    }
    deferred = set(execution_plan.deferred_unknown_field_ids)
    return tuple(
        (
            FreeformFieldOutputV1(
                product_version_id="596-1",
                field_id=field_id,
                state="unknown",
                value_snapshot=None,
                evidence=(),
            )
            if field_id in deferred
            else provider_outputs[field_id]
        )
        for field_id in ORDERED_FIELD_IDS
    )


def _candidate_evidence_receipts(
    batch: Schema67BatchExecutionV1,
    execution_plan: Schema67ExecutionPlanV1,
) -> tuple[FreeformEvidenceBindingReceiptV1, ...]:
    provider_receipts = {
        receipt.field_id: receipt
        for execution in batch.executions
        for receipt in execution.evidence_receipts
    }
    deferred = set(execution_plan.deferred_unknown_field_ids)
    return tuple(
        (
            bind_freeform_arm_evidence(
                field_output=FreeformFieldOutputV1(
                    product_version_id="596-1",
                    field_id=field_id,
                    state="unknown",
                    value_snapshot=None,
                    evidence=(),
                ),
                documents=(),
                manifests=(),
            )
            if field_id in deferred
            else provider_receipts[field_id]
        )
        for field_id in ORDERED_FIELD_IDS
    )


def _schema67_candidate_v2_payload(
    *,
    candidate_tree_sha1: str,
    field_contract_set_sha256: str,
    execution_plan: Schema67ExecutionPlanV1,
    prepared_tasks: tuple[Schema67PreparedTaskV1, ...],
    batch_execution: Schema67BatchExecutionV1,
) -> dict[str, object]:
    fields = _candidate_fields(batch_execution, execution_plan)
    receipts = _candidate_evidence_receipts(batch_execution, execution_plan)
    return {
        "contract": _SCHEMA67_CANDIDATE_OBJECT_TYPE,
        "product_version_id": "596-1",
        "ordered_field_ids": ORDERED_FIELD_IDS,
        "candidate_tree_sha1": candidate_tree_sha1,
        "model_identity_sha256": DEEPSEEK_EXECUTION_IDENTITY_SHA256,
        "source_roles": tuple(
            {"role": role, "source_sha256": source_sha256}
            for role, source_sha256 in _SCHEMA67_SOURCE_ROLE_AUTHORITY
        ),
        "field_contract_set_sha256": field_contract_set_sha256,
        "execution_plan": execution_plan.model_dump(mode="python", round_trip=True),
        "prepared_tasks": tuple(_prepared_task_payload(item) for item in prepared_tasks),
        "batch_execution": _batch_execution_payload(batch_execution),
        "fields": tuple(item.model_dump(mode="python", round_trip=True) for item in fields),
        "evidence_receipts": tuple(
            item.model_dump(mode="python", round_trip=True) for item in receipts
        ),
        "batch_receipt": batch_execution.receipt.model_dump(mode="python", round_trip=True),
    }


@dataclass(frozen=True, slots=True)
class Schema67CandidateV2:
    """Factory-sealed Candidate v2 with the complete 119 execution preimage."""

    contract: Literal["schema67-candidate.v2"]
    product_version_id: Literal["596-1"]
    ordered_field_ids: tuple[str, ...]
    candidate_tree_sha1: str
    model_identity_sha256: str
    field_contract_set_sha256: str
    execution_plan: Schema67ExecutionPlanV1 = field(repr=False)
    prepared_tasks: tuple[Schema67PreparedTaskV1, ...] = field(repr=False)
    batch_execution: Schema67BatchExecutionV1 = field(repr=False)
    candidate_sha256: str
    _factory_seal: _CandidateV2Seal = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _validated_candidate_v2(self)

    @property
    def source_roles(self) -> tuple[dict[str, str], ...]:
        return tuple(
            {"role": role, "source_sha256": source_sha256}
            for role, source_sha256 in _SCHEMA67_SOURCE_ROLE_AUTHORITY
        )

    @property
    def fields(self) -> tuple[FreeformFieldOutputV1, ...]:
        return _candidate_fields(self.batch_execution, self.execution_plan)

    @property
    def evidence_receipts(self) -> tuple[FreeformEvidenceBindingReceiptV1, ...]:
        return _candidate_evidence_receipts(self.batch_execution, self.execution_plan)

    @property
    def batch_receipt(self) -> Schema67BatchExecutionReceiptV1:
        return self.batch_execution.receipt

    def model_dump(
        self,
        *,
        mode: str = "python",
        exclude: set[str] | None = None,
        round_trip: bool = False,
    ) -> dict[str, object]:
        del mode, round_trip
        payload = _schema67_candidate_v2_payload(
            candidate_tree_sha1=self.candidate_tree_sha1,
            field_contract_set_sha256=self.field_contract_set_sha256,
            execution_plan=self.execution_plan,
            prepared_tasks=self.prepared_tasks,
            batch_execution=self.batch_execution,
        )
        payload["candidate_sha256"] = self.candidate_sha256
        for key in exclude or set():
            payload.pop(key, None)
        return payload


def _replay_batch_receipt(
    *,
    execution_plan: Schema67ExecutionPlanV1,
    prepared_tasks: tuple[Schema67PreparedTaskV1, ...],
    batch_execution: Schema67BatchExecutionV1,
) -> Schema67BatchExecutionReceiptV1:
    receipt = batch_execution.receipt
    budget = Schema67BatchBudgetV1(
        task_count=receipt.task_count,
        locator_calls=receipt.locator_calls,
        extractor_calls=receipt.extractor_calls,
        transport_retries=receipt.transport_retries,
        response_contract_repairs=receipt.response_contract_repairs,
        evidence_repairs=receipt.evidence_repairs,
        repair_calls=receipt.repair_calls,
    )
    return build_schema67_batch_receipt(
        execution_plan=execution_plan,
        prepared_tasks=prepared_tasks,
        budget=budget,
        executions=batch_execution.executions,
    )


def _validate_candidate_task_custody(
    *,
    candidate: Schema67CandidateV2,
    fields: tuple[FreeformFieldOutputV1, ...],
    receipts: tuple[FreeformEvidenceBindingReceiptV1, ...],
    batch: Schema67BatchExecutionReceiptV1,
) -> None:
    try:
        plan = Schema67ExecutionPlanV1.model_validate(
            candidate.execution_plan.model_dump(mode="python", round_trip=True)
        )
        tasks = candidate.prepared_tasks
        executions = candidate.batch_execution.executions
        if type(executions) is not tuple or len(executions) != 8:
            raise TypeError
        if (
            type(tasks) is not tuple
            or len(tasks) != 8
            or plan != candidate.execution_plan
            or candidate.field_contract_set_sha256 != plan.contract_set_sha256
            or candidate.batch_execution.receipt != batch
        ):
            raise TypeError
        checked_executions: list[DeepSeekTaskExecutionV1] = []
        for task, execution in zip(tasks, executions, strict=True):
            if (
                type(task) is not Schema67PreparedTaskV1
                or type(execution) is not DeepSeekTaskExecutionV1
                or type(execution.initial) is not Schema67BoundAttemptV1
            ):
                raise TypeError
            checked_initial = Schema67BoundAttemptV1.model_validate(
                execution.initial.model_dump(mode="python", round_trip=True)
            )
            checked_receipt = DeepSeekExecutionReceiptV1.model_validate(
                execution.receipt.model_dump(mode="python", round_trip=True)
            )
            checked_execution = DeepSeekTaskExecutionV1(
                initial=checked_initial,
                initial_outputs=execution.initial_outputs,
                final_outputs=execution.final_outputs,
                evidence_receipts=execution.evidence_receipts,
                response_contract_repair=execution.response_contract_repair,
                evidence_repair=execution.evidence_repair,
                evidence_demotion=checked_receipt.evidence_demotion,
                receipt=checked_receipt,
            )
            prompt_field_ids = tuple(item.field_id for item in task.field_prompts)
            if (
                checked_initial != execution.initial
                or checked_receipt != execution.receipt
                or checked_execution != execution
                or checked_initial.task_id != task.provider_task_sha256
                or checked_initial.attempt_hash != task.provider_attempt_sha256
                or checked_initial.execution_plan_sha256 != plan.execution_plan_sha256
                or checked_initial.task_slice_sha256 != task.task_slice_sha256
                or checked_initial.outputs != execution.initial_outputs
                or checked_receipt.initial_bound_attempt_hash != checked_initial.bound_attempt_hash
                or checked_receipt.task_id != task.provider_task_sha256
                or checked_receipt.attempt_hash != task.provider_attempt_sha256
                or checked_receipt.execution_plan_sha256 != plan.execution_plan_sha256
                or checked_receipt.task_slice_sha256 != task.task_slice_sha256
                or tuple(item.field_id for item in execution.final_outputs) != prompt_field_ids
                or tuple(item.field_id for item in execution.evidence_receipts) != prompt_field_ids
            ):
                raise ValueError
            checked_executions.append(checked_execution)
        exact_executions = tuple(checked_executions)
        execution_receipts = tuple(execution.receipt for execution in exact_executions)
        final_outputs = tuple(
            output for execution in exact_executions for output in execution.final_outputs
        )
        final_evidence_receipts = tuple(
            receipt for execution in exact_executions for receipt in execution.evidence_receipts
        )
        executable_field_ids = tuple(
            field_id for item in plan.task_slices for field_id in item.field_ids
        )
        deferred_field_ids = plan.deferred_unknown_field_ids
        if (
            batch.task_count != 8
            or batch.task_receipt_hashes
            != tuple(receipt.receipt_hash for receipt in execution_receipts)
            or any(
                receipt.execution_plan_sha256 != batch.execution_plan_sha256
                or receipt.task_slice_sha256 is None
                for receipt in execution_receipts
            )
            or len({receipt.task_id for receipt in execution_receipts}) != 8
            or len({receipt.task_slice_sha256 for receipt in execution_receipts}) != 8
            or (
                any(receipt.evidence_demotion is not None for receipt in execution_receipts)
                and (
                    batch.prior_provider_calls,
                    batch.cumulative_provider_calls,
                )
                != (2, 10)
            )
            or tuple(output.field_id for output in final_outputs) != executable_field_ids
            or tuple(receipt.field_id for receipt in final_evidence_receipts)
            != executable_field_ids
            or len(executable_field_ids) != len(set(executable_field_ids))
            or len(deferred_field_ids) != len(set(deferred_field_ids))
            or set(executable_field_ids).intersection(deferred_field_ids)
            or set(executable_field_ids).union(deferred_field_ids) != set(ORDERED_FIELD_IDS)
            or tuple(item for item in ORDERED_FIELD_IDS if item in deferred_field_ids)
            != deferred_field_ids
            or fields != _candidate_fields(candidate.batch_execution, plan)
            or receipts != _candidate_evidence_receipts(candidate.batch_execution, plan)
            or _replay_batch_receipt(
                execution_plan=plan,
                prepared_tasks=tasks,
                batch_execution=candidate.batch_execution,
            )
            != batch
        ):
            raise ValueError
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise LaneCReportGateError("CANDIDATE_TASK_CUSTODY_INVALID") from None


def _validated_candidate_v2(candidate: object) -> _CandidateV2Custody:
    try:
        if type(candidate) is not Schema67CandidateV2:
            raise TypeError
        candidate_dump = candidate.model_dump(mode="python", round_trip=True)
        if set(candidate_dump) != {
            "contract",
            "product_version_id",
            "ordered_field_ids",
            "candidate_tree_sha1",
            "model_identity_sha256",
            "source_roles",
            "field_contract_set_sha256",
            "execution_plan",
            "prepared_tasks",
            "batch_execution",
            "fields",
            "evidence_receipts",
            "batch_receipt",
            "candidate_sha256",
        }:
            raise TypeError
        fields = candidate.fields
        receipts = candidate.evidence_receipts
        batch = candidate.batch_receipt
        if (
            candidate.contract != _SCHEMA67_CANDIDATE_OBJECT_TYPE
            or candidate.product_version_id != "596-1"
            or candidate.ordered_field_ids != ORDERED_FIELD_IDS
            or candidate.candidate_tree_sha1 != _REPORT_COMPILER_DEPENDENCY_TREE_SHA1
            or candidate.model_identity_sha256 != DEEPSEEK_EXECUTION_IDENTITY_SHA256
            or type(fields) is not tuple
            or tuple(item.field_id for item in fields) != ORDERED_FIELD_IDS
            or any(type(item) is not FreeformFieldOutputV1 for item in fields)
            or type(receipts) is not tuple
            or tuple(item.field_id for item in receipts) != ORDERED_FIELD_IDS
            or any(type(item) is not FreeformEvidenceBindingReceiptV1 for item in receipts)
            or type(batch) is not Schema67BatchExecutionReceiptV1
            or batch.task_count != 8
            or len(batch.task_receipt_hashes) != 8
            or not _is_sha256(candidate.candidate_sha256)
            or candidate._factory_seal.candidate_sha256 != candidate.candidate_sha256
        ):
            raise TypeError
        source_roles = candidate_dump["source_roles"]
        if type(source_roles) is not tuple:
            raise TypeError
        source_authority_rows: list[tuple[str, str]] = []
        for source_role in source_roles:
            if (
                type(source_role) is not dict
                or set(source_role) != {"role", "source_sha256"}
                or type(source_role["role"]) is not str
                or type(source_role["source_sha256"]) is not str
            ):
                raise TypeError
            source_authority_rows.append((source_role["role"], source_role["source_sha256"]))
        source_authority = tuple(source_authority_rows)
        if source_authority != _SCHEMA67_SOURCE_ROLE_AUTHORITY:
            raise ValueError
        source_sha256s = {source_sha256 for _, source_sha256 in source_authority}
        checked_fields = tuple(
            FreeformFieldOutputV1.model_validate(item.model_dump(mode="python", round_trip=True))
            for item in fields
        )
        checked_receipts = tuple(
            FreeformEvidenceBindingReceiptV1.model_validate(
                item.model_dump(mode="python", round_trip=True)
            )
            for item in receipts
        )
        checked_batch = Schema67BatchExecutionReceiptV1.model_validate(
            batch.model_dump(mode="python", round_trip=True)
        )
        if (
            checked_fields != fields
            or checked_receipts != receipts
            or checked_batch != batch
            or any(
                field_output.product_version_id != "596-1"
                or receipt.product_version_id != "596-1"
                or receipt.field_id != field_output.field_id
                or receipt.state != field_output.state
                or receipt.value_snapshot != field_output.value_snapshot
                or receipt.evidence != field_output.evidence
                or any(
                    evidence.source_sha256 not in source_sha256s
                    for evidence in field_output.evidence
                )
                for field_output, receipt in zip(checked_fields, checked_receipts, strict=True)
            )
        ):
            raise ValueError
        candidate_payload = _schema67_candidate_v2_payload(
            candidate_tree_sha1=candidate.candidate_tree_sha1,
            field_contract_set_sha256=candidate.field_contract_set_sha256,
            execution_plan=candidate.execution_plan,
            prepared_tasks=candidate.prepared_tasks,
            batch_execution=candidate.batch_execution,
        )
        if candidate_dump != {
            **candidate_payload,
            "candidate_sha256": candidate.candidate_sha256,
        } or candidate.candidate_sha256 != canonical_hash(
            _SCHEMA67_CANDIDATE_OBJECT_TYPE, candidate_payload
        ):
            raise ValueError
        _validate_candidate_task_custody(
            candidate=candidate,
            fields=checked_fields,
            receipts=checked_receipts,
            batch=checked_batch,
        )
        demoted_field_ids_raw = tuple(
            field_id
            for execution in candidate.batch_execution.executions
            if execution.receipt.evidence_demotion is not None
            for field_id in execution.receipt.evidence_demotion.demoted_field_ids
        )
        demoted_field_id_set = set(demoted_field_ids_raw)
        demoted_field_ids = tuple(
            field_id for field_id in ORDERED_FIELD_IDS if field_id in demoted_field_id_set
        )
        if (
            len(demoted_field_ids_raw) != len(demoted_field_id_set)
            or set(demoted_field_ids) != demoted_field_id_set
            or any(
                checked_fields[ORDERED_FIELD_IDS.index(field_id)].state != "unknown"
                for field_id in demoted_field_ids
            )
        ):
            raise ValueError
        return _CandidateV2Custody(
            candidate_sha256=candidate.candidate_sha256,
            fields=checked_fields,
            evidence_receipts=checked_receipts,
            batch_receipt=checked_batch,
            demoted_field_ids=demoted_field_ids,
        )
    except LaneCReportGateError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, ValidationError):
        raise LaneCReportGateError("CANDIDATE_V2_CUSTODY_INVALID") from None


def validate_schema67_candidate_v2(candidate: object) -> Schema67CandidateV2:
    """Freshly replay one concrete, factory-sealed Candidate v2 custody object."""

    _validated_candidate_v2(candidate)
    assert type(candidate) is Schema67CandidateV2
    return candidate


def _load_schema67_task_execution(payload: object) -> DeepSeekTaskExecutionV1:
    if type(payload) is not dict or set(payload) != {
        "initial",
        "initial_outputs",
        "final_outputs",
        "evidence_receipts",
        "response_contract_repair",
        "evidence_repair",
        "receipt",
    }:
        raise TypeError
    initial_outputs = payload["initial_outputs"]
    final_outputs = payload["final_outputs"]
    evidence_receipts = payload["evidence_receipts"]
    if any(
        type(value) is not list for value in (initial_outputs, final_outputs, evidence_receipts)
    ):
        raise TypeError
    response_repair_wire = payload["response_contract_repair"]
    evidence_repair_wire = payload["evidence_repair"]
    if response_repair_wire is not None and type(response_repair_wire) is not dict:
        raise TypeError
    if evidence_repair_wire is not None and type(evidence_repair_wire) is not dict:
        raise TypeError
    receipt = DeepSeekExecutionReceiptV1.model_validate(payload["receipt"])
    return DeepSeekTaskExecutionV1(
        initial=Schema67BoundAttemptV1.model_validate(payload["initial"]),
        initial_outputs=tuple(
            FreeformFieldOutputV1.model_validate(item) for item in initial_outputs
        ),
        final_outputs=tuple(FreeformFieldOutputV1.model_validate(item) for item in final_outputs),
        evidence_receipts=tuple(
            FreeformEvidenceBindingReceiptV1.model_validate(item) for item in evidence_receipts
        ),
        response_contract_repair=(
            None
            if response_repair_wire is None
            else ResponseContractRepairResolutionV2.model_validate(response_repair_wire)
        ),
        evidence_repair=(
            None
            if evidence_repair_wire is None
            else EvidenceRepairTraceV2.model_validate(evidence_repair_wire)
        ),
        evidence_demotion=receipt.evidence_demotion,
        receipt=receipt,
    )


def _load_schema67_batch_execution(payload: object) -> Schema67BatchExecutionV1:
    if type(payload) is not dict or set(payload) != {"executions", "receipt"}:
        raise TypeError
    executions = payload["executions"]
    if type(executions) is not list:
        raise TypeError
    return Schema67BatchExecutionV1(
        executions=tuple(_load_schema67_task_execution(item) for item in executions),
        receipt=Schema67BatchExecutionReceiptV1.model_validate(payload["receipt"]),
    )


def load_schema67_candidate_v2(
    payload: object,
    *,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
    role_inputs: Sequence[Schema67RoleTaskInputV1],
) -> Schema67CandidateV2:
    """Load canonical wire only through externally verified preparation authority."""

    try:
        if type(payload) is not dict or set(payload) != {
            "contract",
            "product_version_id",
            "ordered_field_ids",
            "candidate_tree_sha1",
            "model_identity_sha256",
            "source_roles",
            "field_contract_set_sha256",
            "execution_plan",
            "prepared_tasks",
            "batch_execution",
            "fields",
            "evidence_receipts",
            "batch_receipt",
            "candidate_sha256",
        }:
            raise TypeError
        ordered_field_ids = payload["ordered_field_ids"]
        prepared_tasks = payload["prepared_tasks"]
        if type(ordered_field_ids) is not list or type(prepared_tasks) is not list:
            raise TypeError
        if type(payload["candidate_sha256"]) is not str:
            raise TypeError
        candidate_tree_sha1 = payload["candidate_tree_sha1"]
        if type(candidate_tree_sha1) is not str:
            raise TypeError
        candidate = make_total_control_schema67_candidate_v2(
            field_contracts=field_contracts,
            execution_plan=execution_plan,
            role_inputs=role_inputs,
            batch_execution=_load_schema67_batch_execution(payload["batch_execution"]),
            candidate_tree_sha1=candidate_tree_sha1,
        )
        expected_json = json.loads(
            json.dumps(
                candidate.model_dump(mode="python", round_trip=True),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        if payload != expected_json:
            raise ValueError
        return validate_schema67_candidate_v2(candidate)
    except LaneCReportGateError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, ValidationError):
        raise LaneCReportGateError("CANDIDATE_V2_CUSTODY_INVALID") from None


def make_total_control_schema67_candidate_v2(
    *,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
    role_inputs: Sequence[Schema67RoleTaskInputV1],
    batch_execution: Schema67BatchExecutionV1,
    candidate_tree_sha1: str,
) -> Schema67CandidateV2:
    """Seal one actual 119 batch; no caller-provided PASS or detached executions."""

    try:
        contracts = FieldContractSetV1.model_validate(
            field_contracts.model_dump(mode="python", round_trip=True)
        )
        plan = Schema67ExecutionPlanV1.model_validate(
            execution_plan.model_dump(mode="python", round_trip=True)
        )
        inputs = tuple(role_inputs)
        available_source_roles: tuple[MaterialRole, ...] = tuple(
            role
            for role in ("terms", "brochure", "rate_table")
            if any(item.material_role == role for item in inputs)
        )
        _require_schema67_execution_plan_mode_815(
            field_contracts=contracts,
            execution_plan=plan,
            available_source_roles=available_source_roles,
        )
        if (
            type(field_contracts) is not FieldContractSetV1
            or contracts != field_contracts
            or type(execution_plan) is not Schema67ExecutionPlanV1
            or plan != execution_plan
            or contracts.workbook_sha256 != WORKBOOK_SHA256
            or tuple(item.field_id for item in contracts.contracts) != ORDERED_FIELD_IDS
            or type(role_inputs) is not tuple
            or any(type(item) is not Schema67RoleTaskInputV1 for item in inputs)
            or type(batch_execution) is not Schema67BatchExecutionV1
            or candidate_tree_sha1 != _REPORT_COMPILER_DEPENDENCY_TREE_SHA1
        ):
            raise TypeError
        prepared = prepare_schema67_deepseek_tasks(
            field_contracts=contracts,
            execution_plan=plan,
            role_inputs=inputs,
        )
        payload = _schema67_candidate_v2_payload(
            candidate_tree_sha1=candidate_tree_sha1,
            field_contract_set_sha256=contracts.contract_set_sha256,
            execution_plan=plan,
            prepared_tasks=prepared,
            batch_execution=batch_execution,
        )
        candidate_sha256 = canonical_hash(_SCHEMA67_CANDIDATE_OBJECT_TYPE, payload)
        return Schema67CandidateV2(
            contract="schema67-candidate.v2",
            product_version_id="596-1",
            ordered_field_ids=ORDERED_FIELD_IDS,
            candidate_tree_sha1=candidate_tree_sha1,
            model_identity_sha256=DEEPSEEK_EXECUTION_IDENTITY_SHA256,
            field_contract_set_sha256=contracts.contract_set_sha256,
            execution_plan=plan,
            prepared_tasks=prepared,
            batch_execution=batch_execution,
            candidate_sha256=candidate_sha256,
            _factory_seal=_CandidateV2Seal(_SCHEMA67_CANDIDATE_FACTORY_TOKEN, candidate_sha256),
        )
    except LaneCReportGateError:
        raise
    except (AttributeError, DeepSeekCompilerError, TypeError, ValueError, ValidationError):
        raise LaneCReportGateError("CANDIDATE_V2_CUSTODY_INVALID") from None


def _schema67_report_gate_row_payload(
    row: Schema67ReportGateRowV1,
) -> dict[str, object]:
    return {
        "field_id": row.field_id,
        "state": row.state,
        "evidence_057_status": row.evidence_057_status,
        "correctness": row.correctness,
        "completeness": row.completeness,
        "state_consistent": row.state_consistent,
        "review_reason_codes": row.review_reason_codes,
        "candidate_evidence_receipt_sha256": (row.candidate_evidence_receipt_sha256),
        "semantic_decision_receipt_sha256": (row.semantic_decision_receipt_sha256),
    }


def _schema67_report_gate_payload(
    gate: Schema67ReportGateV1,
) -> dict[str, object]:
    return {
        "contract_id": gate.contract_id,
        "status": gate.status,
        "candidate_v2_sha256": gate.candidate_v2_sha256,
        "candidate_bundle_sha256": gate.candidate_bundle_sha256,
        "accepted_batch_receipt_sha256": gate.accepted_batch_receipt_sha256,
        "task_receipt_hashes": gate.task_receipt_hashes,
        "candidate_evidence_receipt_hashes": (gate.candidate_evidence_receipt_hashes),
        "live_evidence_receipt_hashes": gate.live_evidence_receipt_hashes,
        "reference_bundle_sha256": gate.reference_bundle_sha256,
        "reference_subject_sha256": gate.reference_subject_sha256,
        "reference_receipt_sha256": gate.reference_receipt_sha256,
        "comparator_authority_sha256": gate.comparator_authority_sha256,
        "semantic_decision_receipt_hashes": (gate.semantic_decision_receipt_hashes),
        "semantic_evaluation_receipt_sha256": (gate.semantic_evaluation_receipt_sha256),
        "rows": tuple(_schema67_report_gate_row_payload(row) for row in gate.rows),
        "semantic_eval_allowed": gate.semantic_eval_allowed,
        "wiki_admission_allowed": gate.wiki_admission_allowed,
        "publishable_field_ids": gate.publishable_field_ids,
    }


def _validate_schema67_report_gate(gate: object) -> Schema67ReportGateV1:
    if type(gate) is not Schema67ReportGateV1:
        raise ValueError("LANE_C_REPORT_GATE_SEAL_INVALID")
    rows = gate.rows
    if (
        type(gate._factory_seal) is not _ReportGateSeal
        or gate._factory_seal.receipt_sha256 != gate.gate_receipt_sha256
        or gate.contract_id != _LANE_C_REPORT_GATE_OBJECT_TYPE
        or tuple(row.field_id for row in rows) != ORDERED_FIELD_IDS
        or not all(
            _is_sha256(value)
            for value in (
                gate.candidate_v2_sha256,
                gate.candidate_bundle_sha256,
                gate.accepted_batch_receipt_sha256,
                gate.reference_bundle_sha256,
                gate.reference_subject_sha256,
                gate.reference_receipt_sha256,
                gate.comparator_authority_sha256,
                gate.semantic_evaluation_receipt_sha256,
                gate.gate_receipt_sha256,
                *gate.task_receipt_hashes,
                *gate.candidate_evidence_receipt_hashes,
                *gate.live_evidence_receipt_hashes,
                *gate.semantic_decision_receipt_hashes,
            )
        )
        or len(gate.task_receipt_hashes) != 8
        or len(set(gate.task_receipt_hashes)) != 8
        or len(set(gate.candidate_evidence_receipt_hashes))
        != len(gate.candidate_evidence_receipt_hashes)
        or len(set(gate.live_evidence_receipt_hashes)) != len(gate.live_evidence_receipt_hashes)
        or len(set(gate.semantic_decision_receipt_hashes))
        != len(gate.semantic_decision_receipt_hashes)
    ):
        raise ValueError("LANE_C_REPORT_GATE_SEAL_INVALID")
    for row in rows:
        if row.state == "unknown":
            valid = (
                row.evidence_057_status == "NOT_REQUIRED"
                and row.correctness == "PENDING"
                and row.completeness == "PENDING"
                and row.state_consistent is None
                and row.review_reason_codes
                in (
                    ("SEMANTIC_UNKNOWN_PENDING",),
                    ("EVIDENCE_NONPASS_DEMOTED",),
                )
                and row.candidate_evidence_receipt_sha256 is None
                and row.semantic_decision_receipt_sha256 is None
            )
        else:
            valid = (
                row.evidence_057_status in ("PASS", "BLOCKED")
                and row.candidate_evidence_receipt_sha256 is not None
                and _is_sha256(row.candidate_evidence_receipt_sha256)
                and (
                    row.semantic_decision_receipt_sha256 is None
                    or _is_sha256(row.semantic_decision_receipt_sha256)
                )
                and len(set(row.review_reason_codes)) == len(row.review_reason_codes)
            )
        if not valid:
            raise ValueError("LANE_C_REPORT_GATE_SEAL_INVALID")
    expected_status: ReportGateStatus
    if any(
        row.evidence_057_status == "BLOCKED"
        or row.correctness == "FAIL"
        or row.completeness == "FAIL"
        for row in rows
    ):
        expected_status = "BLOCKED"
    elif any(row.correctness == "PENDING" or row.completeness == "PENDING" for row in rows):
        expected_status = "PENDING"
    else:
        expected_status = "READY"
    expected_publishable = ORDERED_FIELD_IDS if expected_status == "READY" else ()
    if (
        gate.status != expected_status
        or gate.wiki_admission_allowed != (expected_status == "READY")
        or gate.publishable_field_ids != expected_publishable
        or gate.gate_receipt_sha256
        != canonical_hash(
            _LANE_C_REPORT_GATE_OBJECT_TYPE,
            _schema67_report_gate_payload(gate),
        )
        or gate.candidate_evidence_receipt_hashes
        != tuple(
            row.candidate_evidence_receipt_sha256
            for row in rows
            if row.candidate_evidence_receipt_sha256 is not None
        )
        or gate.semantic_decision_receipt_hashes
        != tuple(
            row.semantic_decision_receipt_sha256
            for row in rows
            if row.semantic_decision_receipt_sha256 is not None
        )
    ):
        raise ValueError("LANE_C_REPORT_GATE_SEAL_INVALID")
    return gate


def validate_schema67_report_gate(
    gate: object,
) -> Schema67ReportGateV1:
    """Revalidate code-owned seal and every report-gate binding at consumption."""

    return _validate_schema67_report_gate(gate)


def evaluate_expert_golden_admission(
    *,
    snapshot: Schema67AuthoritySnapshotPort,
    candidate_fields: tuple[FreeformFieldOutputV1, ...],
    evidence_cases: tuple[EvidenceReplayCaseV1, ...],
    receipt: object | None,
    observed_at: object | None,
) -> ExpertGoldenAdmissionResultV1:
    """Derive Schema67 state from Lane B outputs, then replay 057 Evidence."""

    if not _snapshot_is_exact(snapshot):
        return _result(
            status="BLOCKED",
            reasons=("SCHEMA67_SNAPSHOT_IDENTITY_INVALID",),
            reference="BLOCKED",
            evidence="BLOCKED",
        )
    receipt_reason = (
        None
        if receipt is None
        else _verify_expert_receipt(
            receipt=receipt,
            observed_at=observed_at,
        )
    )
    reference_state: ExpertContentState = (
        "PENDING_RECEIPT"
        if receipt is None
        else "BLOCKED"
        if receipt_reason is not None
        else "VERIFIED"
    )
    try:
        bundle = _derive_candidate_bundle(candidate_fields, evidence_cases)
    except _EvidenceBundleContractError as exc:
        verified_receipt = (
            receipt
            if reference_state == "VERIFIED" and type(receipt) is NamedExpertApprovalReceiptV1
            else None
        )
        return _result(
            status="BLOCKED",
            reasons=(exc.reason_code,),
            reference=reference_state,
            evidence="BLOCKED",
            reference_bundle_sha256=REFERENCE_BUNDLE_SNAPSHOT_SHA256,
            reference_subject_sha256=(
                None if verified_receipt is None else verified_receipt.subject_sha256
            ),
            reference_receipt_sha256=(
                None if verified_receipt is None else verified_receipt.receipt_sha256
            ),
        )

    receipts: list[str] = []
    review_items: list[EvidenceReplayReviewItemV1] = []
    failed_fields: set[str] = set()
    passed_fragments = 0
    for case in bundle.canonical_cases:
        try:
            bound: FreeformEvidenceBindingReceiptV1 = bind_freeform_arm_evidence(
                field_output=case.field_output,
                documents=case.documents,
                manifests=case.manifests,
            )
        except VerifierContractError as exc:
            failed_fields.add(case.field_output.field_id)
            review_items.append(
                EvidenceReplayReviewItemV1(
                    field_id=case.field_output.field_id,
                    case_id=case.case_id,
                    reason_code=exc.reason_code,
                )
            )
        else:
            receipts.append(bound.receipt_hash)
            passed_fragments += len(case.field_output.evidence)

    evidence_state: EvidenceReplayState = "PASS" if not review_items else "BLOCKED"
    effective_unknown = tuple(
        field_id
        for field_id in ORDERED_FIELD_IDS
        if candidate_fields[ORDERED_FIELD_IDS.index(field_id)].state == "unknown"
        or field_id in failed_fields
    )
    if receipt is None:
        return _result(
            status="PENDING_EXPERT_RECEIPT",
            reasons=("EXPERT_RECEIPT_MISSING",),
            reference="PENDING_RECEIPT",
            evidence=evidence_state,
            total=bundle.evidence_fragments_total,
            passed=passed_fragments,
            receipts=tuple(receipts),
            review_items=tuple(review_items),
            publishable=(),
            unknown=effective_unknown,
            candidate_bundle_sha256=bundle.bundle_sha256,
            reference_bundle_sha256=REFERENCE_BUNDLE_SNAPSHOT_SHA256,
        )
    assert receipt is not None
    if receipt_reason is not None:
        return _result(
            status="BLOCKED",
            reasons=(receipt_reason,),
            reference="BLOCKED",
            evidence=evidence_state,
            total=bundle.evidence_fragments_total,
            passed=passed_fragments,
            receipts=tuple(receipts),
            review_items=tuple(review_items),
            publishable=(),
            unknown=effective_unknown,
            candidate_bundle_sha256=bundle.bundle_sha256,
            reference_bundle_sha256=REFERENCE_BUNDLE_SNAPSHOT_SHA256,
        )
    if evidence_state == "BLOCKED":
        assert type(receipt) is NamedExpertApprovalReceiptV1
        return _result(
            status="REFERENCE_APPROVED_CANDIDATE_EVIDENCE_BLOCKED",
            reasons=("EVIDENCE_REPLAY_FAILED",),
            reference="VERIFIED",
            evidence="BLOCKED",
            total=bundle.evidence_fragments_total,
            passed=passed_fragments,
            receipts=tuple(receipts),
            review_items=tuple(review_items),
            publishable=(),
            unknown=effective_unknown,
            candidate_bundle_sha256=bundle.bundle_sha256,
            reference_bundle_sha256=receipt.reference_bundle_sha256,
            reference_subject_sha256=receipt.subject_sha256,
            reference_receipt_sha256=receipt.receipt_sha256,
            semantic_eval_allowed=True,
        )
    assert type(receipt) is NamedExpertApprovalReceiptV1
    return _result(
        status="READY_FOR_OFFLINE_GOLDEN_EVAL",
        reasons=(),
        reference="VERIFIED",
        evidence="PASS",
        total=bundle.evidence_fragments_total,
        passed=passed_fragments,
        receipts=tuple(receipts),
        review_items=tuple(review_items),
        publishable=(),
        unknown=effective_unknown,
        candidate_bundle_sha256=bundle.bundle_sha256,
        reference_bundle_sha256=receipt.reference_bundle_sha256,
        reference_subject_sha256=receipt.subject_sha256,
        reference_receipt_sha256=receipt.receipt_sha256,
        semantic_eval_allowed=True,
    )


def evaluate_schema67_semantic_gate(
    *,
    snapshot: Schema67AuthoritySnapshotPort,
    candidate_fields: tuple[FreeformFieldOutputV1, ...],
    evidence_cases: tuple[EvidenceReplayCaseV1, ...],
    receipt: object | None,
    observed_at: object | None,
    frozen_candidate_bundle_sha256: object,
    comparator: object,
) -> Schema67SemanticEvaluationResultV1:
    """Run the deterministic double-axis gate after reference and 057 Evidence."""

    try:
        derived_bundle = _derive_candidate_bundle(candidate_fields, evidence_cases)
    except _EvidenceBundleContractError:
        derived_bundle = None
    if derived_bundle is not None and (
        not _is_sha256(frozen_candidate_bundle_sha256)
        or frozen_candidate_bundle_sha256 != derived_bundle.bundle_sha256
    ):
        frozen_base = _result(
            status="BLOCKED",
            reasons=("CANDIDATE_FREEZE_IDENTITY_MISMATCH",),
            reference="BLOCKED",
            evidence="BLOCKED",
            candidate_bundle_sha256=derived_bundle.bundle_sha256,
            reference_bundle_sha256=REFERENCE_BUNDLE_SNAPSHOT_SHA256,
        )
        return _semantic_result(
            status="SEMANTIC_EVALUATION_BLOCKED",
            reasons=("CANDIDATE_FREEZE_IDENTITY_MISMATCH",),
            base=frozen_base,
        )
    base = evaluate_expert_golden_admission(
        snapshot=snapshot,
        candidate_fields=candidate_fields,
        evidence_cases=evidence_cases,
        receipt=receipt,
        observed_at=observed_at,
    )
    if base.status != "READY_FOR_OFFLINE_GOLDEN_EVAL":
        evaluations: tuple[SemanticFieldEvaluationV1, ...] = ()
        if (
            base.candidate_bundle_sha256 is not None
            and len(candidate_fields) == len(ORDERED_FIELD_IDS)
            and tuple(output.field_id for output in candidate_fields) == ORDERED_FIELD_IDS
        ):
            failed_fields = {item.field_id for item in base.review_items}
            evaluations = tuple(
                _field_evaluation(
                    field_id=output.field_id,
                    correctness=("FAIL" if output.field_id in failed_fields else "PENDING"),
                    completeness=("FAIL" if output.field_id in failed_fields else "PENDING"),
                    state_consistent=None,
                    reasons=(
                        ("EVIDENCE_REPLAY_FAILED",)
                        if output.field_id in failed_fields
                        else ("SEMANTIC_GATE_PREREQUISITE_BLOCKED",)
                    ),
                )
                for output in candidate_fields
            )
        return _semantic_result(
            status="SEMANTIC_EVALUATION_BLOCKED",
            reasons=("SEMANTIC_GATE_PREREQUISITE_BLOCKED",),
            base=base,
            evaluations=evaluations,
        )

    if not _semantic_authority_is_exact(comparator):
        return _semantic_result(
            status="SEMANTIC_EVALUATION_BLOCKED",
            reasons=("SEMANTIC_COMPARATOR_AUTHORITY_INVALID",),
            base=base,
        )
    authority = comparator.authority
    if (
        authority.reference_bundle_sha256 != base.reference_bundle_sha256
        or authority.expert_subject_sha256 != base.reference_subject_sha256
        or authority.expert_receipt_sha256 != base.reference_receipt_sha256
    ):
        return _semantic_result(
            status="SEMANTIC_EVALUATION_BLOCKED",
            reasons=("SEMANTIC_COMPARATOR_AUTHORITY_INVALID",),
            base=base,
            comparator_authority_sha256=authority.authority_sha256,
        )
    assert base.candidate_bundle_sha256 is not None

    evaluations_list: list[SemanticFieldEvaluationV1] = []
    for output in candidate_fields:
        covered_sources = tuple(sorted({evidence.source_sha256 for evidence in output.evidence}))
        if output.state == "unknown":
            evaluations_list.append(
                _field_evaluation(
                    field_id=output.field_id,
                    correctness="PENDING",
                    completeness="PENDING",
                    state_consistent=None,
                    covered_sources=covered_sources,
                    reasons=("SEMANTIC_UNKNOWN_PENDING",),
                )
            )
            continue
        candidate_value_sha256 = (
            None
            if output.value_snapshot is None
            else hashlib.sha256(output.value_snapshot.encode("utf-8")).hexdigest()
        )
        try:
            comparison = comparator.compare(
                field_id=output.field_id,
                candidate_state=output.state,
                candidate_value_sha256=candidate_value_sha256,
                candidate_bundle_sha256=base.candidate_bundle_sha256,
            )
        except Exception:
            return _semantic_result(
                status="SEMANTIC_EVALUATION_BLOCKED",
                reasons=("SEMANTIC_COMPARISON_INVALID",),
                base=base,
                comparator_authority_sha256=authority.authority_sha256,
            )
        if not _semantic_comparison_is_exact(
            comparison,
            field_output=output,
            candidate_bundle_sha256=base.candidate_bundle_sha256,
            authority_sha256=authority.authority_sha256,
        ):
            return _semantic_result(
                status="SEMANTIC_EVALUATION_BLOCKED",
                reasons=("SEMANTIC_COMPARISON_INVALID",),
                base=base,
                comparator_authority_sha256=authority.authority_sha256,
            )

        reasons: list[str] = []
        state_consistent = comparison.reference_state == output.state
        if not state_consistent:
            correctness: SemanticAxisVerdict = "FAIL"
            reasons.append("SEMANTIC_STATE_MISMATCH")
        elif comparison.semantic_outcome == "EQUIVALENT":
            correctness = "PASS"
        elif comparison.semantic_outcome == "DIFFERENT":
            correctness = "FAIL"
            reasons.append("SEMANTIC_VALUE_MISMATCH")
        else:
            correctness = "PENDING"
            reasons.append("SEMANTIC_AUTHORITY_PENDING")

        required_sources = comparison.required_evidence_source_sha256s
        if required_sources and set(required_sources).issubset(covered_sources):
            completeness: SemanticAxisVerdict = "PASS"
        else:
            completeness = "FAIL"
            reasons.append("SEMANTIC_EVIDENCE_BRANCH_INCOMPLETE")
        evaluations_list.append(
            _field_evaluation(
                field_id=output.field_id,
                correctness=correctness,
                completeness=completeness,
                state_consistent=state_consistent,
                required_sources=required_sources,
                covered_sources=covered_sources,
                reasons=tuple(reasons),
                comparison_receipt_sha256=comparison.comparison_sha256,
            )
        )

    evaluations = tuple(evaluations_list)
    double_pass = len(evaluations) == len(ORDERED_FIELD_IDS) and all(
        evaluation.correctness == "PASS" and evaluation.completeness == "PASS"
        for evaluation in evaluations
    )
    return _semantic_result(
        status="SEMANTIC_DOUBLE_PASS" if double_pass else "SEMANTIC_REVIEW_REQUIRED",
        reasons=() if double_pass else ("SEMANTIC_REVIEW_ITEMS_PRESENT",),
        base=base,
        evaluations=evaluations,
        comparator_authority_sha256=authority.authority_sha256,
        semantic_eval_allowed=True,
        wiki_admission_allowed=double_pass,
        publishable=ORDERED_FIELD_IDS if double_pass else (),
    )


def make_total_control_schema67_report_gate(
    *,
    snapshot: Schema67AuthoritySnapshotPort,
    candidate: object,
    evidence_cases: tuple[EvidenceReplayCaseV1, ...],
    frozen_candidate_bundle_sha256: object,
    receipt: object,
    observed_at: object,
    comparator: object,
) -> Schema67ReportGateV1:
    """Build the sole code-owned Lane C result accepted by report composition."""

    custody = _validated_candidate_v2(candidate)
    if not _semantic_authority_is_exact(comparator):
        raise LaneCReportGateError("SEMANTIC_COMPARATOR_AUTHORITY_INVALID")
    comparator_authority_sha256 = comparator.authority.authority_sha256
    semantic = evaluate_schema67_semantic_gate(
        snapshot=snapshot,
        candidate_fields=custody.fields,
        evidence_cases=evidence_cases,
        receipt=receipt,
        observed_at=observed_at,
        frozen_candidate_bundle_sha256=frozen_candidate_bundle_sha256,
        comparator=comparator,
    )
    if (
        semantic.candidate_bundle_sha256 is None
        or semantic.reference_bundle_sha256 is None
        or semantic.reference_subject_sha256 is None
        or semantic.reference_receipt_sha256 is None
        or len(semantic.field_evaluations) != len(ORDERED_FIELD_IDS)
    ):
        raise LaneCReportGateError("SEMANTIC_GATE_PRECONDITION_INVALID")

    evaluations = {evaluation.field_id: evaluation for evaluation in semantic.field_evaluations}
    candidate_receipts = {receipt.field_id: receipt for receipt in custody.evidence_receipts}
    demoted_field_ids = set(custody.demoted_field_ids)
    rows = tuple(
        Schema67ReportGateRowV1(
            field_id=field_output.field_id,
            state=field_output.state,
            evidence_057_status=(
                "NOT_REQUIRED"
                if field_output.state == "unknown"
                else "BLOCKED"
                if "EVIDENCE_REPLAY_FAILED"
                in evaluations[field_output.field_id].review_reason_codes
                else "PASS"
            ),
            correctness=evaluations[field_output.field_id].correctness,
            completeness=(
                "PENDING"
                if field_output.state == "unknown"
                else evaluations[field_output.field_id].completeness
            ),
            state_consistent=(
                None
                if field_output.state == "unknown"
                else evaluations[field_output.field_id].state_consistent
            ),
            review_reason_codes=(
                (
                    "EVIDENCE_NONPASS_DEMOTED"
                    if field_output.field_id in demoted_field_ids
                    else "SEMANTIC_UNKNOWN_PENDING",
                )
                if field_output.state == "unknown"
                else evaluations[field_output.field_id].review_reason_codes
            ),
            candidate_evidence_receipt_sha256=(
                None
                if field_output.state == "unknown"
                else candidate_receipts[field_output.field_id].receipt_hash
            ),
            semantic_decision_receipt_sha256=(
                evaluations[field_output.field_id].comparison_receipt_sha256
            ),
        )
        for field_output in custody.fields
    )
    if semantic.status == "SEMANTIC_EVALUATION_BLOCKED" or any(
        row.evidence_057_status == "BLOCKED"
        or row.correctness == "FAIL"
        or row.completeness == "FAIL"
        for row in rows
    ):
        status: ReportGateStatus = "BLOCKED"
    elif semantic.status == "SEMANTIC_DOUBLE_PASS":
        status = "READY"
    else:
        status = "PENDING"
    candidate_evidence_receipt_hashes = tuple(
        candidate_receipts[field_output.field_id].receipt_hash
        for field_output in custody.fields
        if field_output.state != "unknown"
    )
    semantic_decision_receipt_hashes = tuple(
        row.semantic_decision_receipt_sha256
        for row in rows
        if row.semantic_decision_receipt_sha256 is not None
    )
    values: dict[str, object] = {
        "contract_id": _LANE_C_REPORT_GATE_OBJECT_TYPE,
        "status": status,
        "candidate_v2_sha256": custody.candidate_sha256,
        "candidate_bundle_sha256": semantic.candidate_bundle_sha256,
        "accepted_batch_receipt_sha256": (custody.batch_receipt.batch_receipt_sha256),
        "task_receipt_hashes": custody.batch_receipt.task_receipt_hashes,
        "candidate_evidence_receipt_hashes": candidate_evidence_receipt_hashes,
        "live_evidence_receipt_hashes": semantic.evidence_receipt_hashes,
        "reference_bundle_sha256": semantic.reference_bundle_sha256,
        "reference_subject_sha256": semantic.reference_subject_sha256,
        "reference_receipt_sha256": semantic.reference_receipt_sha256,
        "comparator_authority_sha256": comparator_authority_sha256,
        "semantic_decision_receipt_hashes": semantic_decision_receipt_hashes,
        "semantic_evaluation_receipt_sha256": (semantic.evaluation_receipt_sha256),
        "rows": tuple(_schema67_report_gate_row_payload(row) for row in rows),
        "semantic_eval_allowed": semantic.semantic_eval_allowed,
        "wiki_admission_allowed": semantic.wiki_admission_allowed,
        "publishable_field_ids": semantic.publishable_field_ids,
    }
    gate_receipt_sha256 = canonical_hash(_LANE_C_REPORT_GATE_OBJECT_TYPE, values)
    return Schema67ReportGateV1(
        contract_id="schema67-lane-c-report-gate.v1",
        status=status,
        candidate_v2_sha256=custody.candidate_sha256,
        candidate_bundle_sha256=semantic.candidate_bundle_sha256,
        accepted_batch_receipt_sha256=(custody.batch_receipt.batch_receipt_sha256),
        task_receipt_hashes=custody.batch_receipt.task_receipt_hashes,
        candidate_evidence_receipt_hashes=candidate_evidence_receipt_hashes,
        live_evidence_receipt_hashes=semantic.evidence_receipt_hashes,
        reference_bundle_sha256=semantic.reference_bundle_sha256,
        reference_subject_sha256=semantic.reference_subject_sha256,
        reference_receipt_sha256=semantic.reference_receipt_sha256,
        comparator_authority_sha256=comparator_authority_sha256,
        semantic_decision_receipt_hashes=semantic_decision_receipt_hashes,
        semantic_evaluation_receipt_sha256=semantic.evaluation_receipt_sha256,
        rows=rows,
        semantic_eval_allowed=semantic.semantic_eval_allowed,
        wiki_admission_allowed=semantic.wiki_admission_allowed,
        publishable_field_ids=semantic.publishable_field_ids,
        gate_receipt_sha256=gate_receipt_sha256,
        _factory_seal=_ReportGateSeal(_LANE_C_REPORT_GATE_FACTORY_TOKEN, gate_receipt_sha256),
    )


__all__ = [
    "APPROVED_EXPERT_RECEIPT_EXPIRES_AT",
    "APPROVED_EXPERT_RECEIPT_ISSUED_AT",
    "APPROVED_EXPERT_RECEIPT_SHA256",
    "CANDIDATE_SHA256",
    "EXPERT_APPROVAL_PROVENANCE",
    "EXPERT_DISPLAY_NAME",
    "EXPERT_PRINCIPAL_ID",
    "EXPLICIT_ABSENCE_FIELD_ID",
    "FIXED_UNKNOWN_FIELD_IDS",
    "FIXED_UNKNOWN_FIELD_IDS_SHA256",
    "ORDERED_FIELD_IDS",
    "ORDERED_FIELD_IDS_SHA256",
    "REFERENCE_BUNDLE_SNAPSHOT_SHA256",
    "REFERENCE_EVIDENCE_FRAGMENT_COUNT",
    "SCHEMA_SHA256",
    "WORKBOOK_SHA256",
    "EvidenceReplayCaseV1",
    "ExpertApprovalProvenanceV1",
    "ExpertGoldenAdmissionResultV1",
    "NamedExpertApprovalReceiptV1",
    "LaneCReportGateError",
    "Schema67ReportGateRowV1",
    "Schema67ReportGateV1",
    "Schema67CandidateV2",
    "Schema67AuthoritySnapshotError",
    "Schema67AuthoritySnapshotPort",
    "TotalControlSchema67AuthoritySnapshotV1",
    "SemanticAuthorityComparatorPort",
    "SemanticAuthorityComparisonV1",
    "SemanticComparatorAuthorityV1",
    "SemanticEvaluationReviewItemV1",
    "SemanticFieldEvaluationV1",
    "candidate_evidence_bundle_sha256",
    "evaluate_expert_golden_admission",
    "expert_approval_receipt_sha256",
    "expert_approval_subject_sha256",
    "make_total_control_schema67_authority_snapshot",
    "make_total_control_schema67_candidate_v2",
    "make_total_control_named_expert_approval_receipt",
    "make_total_control_schema67_report_gate",
    "semantic_authority_comparison_sha256",
    "semantic_comparator_authority_sha256",
    "load_schema67_candidate_v2",
    "validate_schema67_candidate_v2",
    "validate_schema67_report_gate",
    "validate_total_control_named_expert_approval_receipt",
]
