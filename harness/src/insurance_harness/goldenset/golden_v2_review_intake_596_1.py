"""Offline fail-closed intake for the exact 596-1 eighteen-field human review."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import string
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Final, Literal, TypeGuard

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import ValidationError

from insurance_harness.canonical import canonical_bytes, canonical_hash

from .records import GoldenRecord

V1_GOLDEN_SHA256: Final[str] = (
    "562c37c7cf262e2e78f0b3ca4b7de4b0dab2f407d3cd7318a8a69b5dca33d8fb"
)
REVIEW_WORKBOOK_SHA256: Final[str] = (
    "ad51172eeee8dac177afff2319a0f8c14f09a82786846eaa227005dc1ac54edf"
)
HIGH_RISK_OCCUPATION_FIELD_ID: Final[str] = "zh_2df7d6256c"
PRODUCT_TIER_FIELD_ID: Final[str] = "zh_b7ceabc3c0"

_RECORD_OBJECT_TYPE: Final[str] = "golden-v2-596-1-record.v1"
_DECISIONS_OBJECT_TYPE: Final[str] = "golden-v2-596-1-review-decisions.v1"
_REQUEST_OBJECT_TYPE: Final[str] = "golden-v2-596-1-review-request.v1"
_SUBJECT_OBJECT_TYPE: Final[str] = "golden-v2-596-1-human-subject.v1"
_RECEIPT_OBJECT_TYPE: Final[str] = "golden-v2-596-1-human-receipt.v1"
_RESULT_OBJECT_TYPE: Final[str] = "golden-v2-596-1-intake-result.v1"
_SUCCESSOR_OBJECT_TYPE: Final[str] = "golden-v2-596-1-successor-receipt.v1"
_SIGNATURE_DOMAIN: Final[bytes] = (
    b"insurance-harness:596-1-golden-v2-human-review-receipt:v1\0"
)
HUMAN_REVIEW_RECEIPT_CONTRACT_ID: Final[str] = (
    "596-1-golden-v2-human-review-receipt.v1"
)

Priority = Literal["P0", "P1"]
ReviewSelection = Literal[
    "accept_recommendation",
    "keep_current",
    "custom",
    "needs_expert",
    "not_applicable",
]
IntakeStatus = Literal[
    "PENDING",
    "BLOCKED",
    "READY_FOR_EXTERNAL_APPROVAL",
    "HUMAN_DECISIONS_VERIFIED",
]
HumanReceiptAction = Literal["approve", "reject"]
MaterializationStatus = Literal["BLOCKED", "MATERIALIZED"]
ArtifactBinding = Literal["FORMAL_596_1_V1", "SYNTHETIC_TEST_ONLY"]


@dataclass(frozen=True, slots=True)
class SourceIdentityV1:
    role: str
    sha256: str


SOURCE_IDENTITIES: Final[tuple[SourceIdentityV1, ...]] = (
    SourceIdentityV1(
        "terms",
        "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
    ),
    SourceIdentityV1(
        "manual",
        "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
    ),
    SourceIdentityV1(
        "rate",
        "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
    ),
)


@dataclass(frozen=True, slots=True)
class ReviewFieldV1:
    field_id: str
    field_name: str
    priority: Priority
    slot: int


REVIEW_FIELDS: Final[tuple[ReviewFieldV1, ...]] = (
    ReviewFieldV1("clause_version", "条款版本标识", "P0", 1),
    ReviewFieldV1("reduced_paid_up", "减额缴清", "P0", 2),
    ReviewFieldV1("reinstatement", "复效条款", "P0", 3),
    ReviewFieldV1("zh_0b3894ed2a", "产品类型", "P0", 4),
    ReviewFieldV1("zh_74aa1b9c93", "保证续保", "P0", 5),
    ReviewFieldV1("zh_d62301d84c", "宽限期", "P0", 6),
    ReviewFieldV1("zh_e1bea0527a", "特殊免责", "P0", 7),
    ReviewFieldV1("claim_filing_requirements", "理赔申请时效与申请材料", "P1", 1),
    ReviewFieldV1("exclusions_official", "责任免除", "P1", 2),
    ReviewFieldV1("external_drug_coverage", "外购药/特药责任", "P1", 3),
    ReviewFieldV1("waiting_period_claim_handling", "等待期内出险处理", "P1", 4),
    ReviewFieldV1("zh_09a5d9e54e", "保什么", "P1", 5),
    ReviewFieldV1("zh_3a3e6520a3", "给付限额", "P1", 6),
    ReviewFieldV1("zh_3d8424595d", "报销比例", "P1", 7),
    ReviewFieldV1("zh_4a789b1d6f", "报销范围", "P1", 8),
    ReviewFieldV1("zh_7d7fe38f09", "癌症医疗", "P1", 9),
    ReviewFieldV1("zh_7fe8603c08", "费用", "P1", 10),
    ReviewFieldV1("zh_f32c510a5e", "医院范围", "P1", 11),
)

_EXCLUDED_REVIEW_FIELDS: Final[frozenset[str]] = frozenset(
    {HIGH_RISK_OCCUPATION_FIELD_ID, PRODUCT_TIER_FIELD_ID}
)
_PLACEHOLDER_DECISION_REASONS: Final[frozenset[str]] = frozenset(
    {"placeholder", "tbd", "todo", "unknown", "待定", "待确认", "未知"}
)
_SURROUNDING_REASON_PUNCTUATION: Final[str] = (
    string.punctuation + "，。！？；：、（）【】《》“”‘’…—·「」『』〔〕〈〉"
)


@dataclass(frozen=True, slots=True)
class DecisionProvenanceV1:
    workbook_sha256: str
    worksheet: str
    row: int
    decision_cell: str


@dataclass(frozen=True, slots=True)
class ConversationProvenanceV1:
    source_thread_id: str
    conversation_id: str
    user_decision_ref: str


@dataclass(frozen=True, slots=True)
class ReviewDecisionV1:
    field_id: str
    priority: Priority
    selection: ReviewSelection
    current_record_sha256: str
    recommended_record: GoldenRecord | None
    recommended_record_sha256: str | None
    custom_record: GoldenRecord | None
    custom_record_sha256: str | None
    reason: str
    provenance: DecisionProvenanceV1


@dataclass(frozen=True, slots=True)
class ReviewIntakeRequestV1:
    v1_golden_sha256: str
    workbook_sha256: str
    sources: tuple[SourceIdentityV1, ...]
    decisions: tuple[ReviewDecisionV1, ...]
    decisions_sha256: str
    provenance: ConversationProvenanceV1


@dataclass(frozen=True, slots=True)
class NamedHumanAuthorityV1:
    principal_id: str
    display_name: str
    signer_key_id: str
    public_key: Ed25519PublicKey


@dataclass(frozen=True, slots=True)
class NamedHumanReviewReceiptV1:
    contract_id: str
    issued_by: str
    actor_type: str
    principal_id: str
    approved_by: str
    action: HumanReceiptAction
    subject_sha256: str
    decisions_sha256: str
    issued_at: datetime
    expires_at: datetime
    provenance: ConversationProvenanceV1
    signer_key_id: str
    signature_b64: str
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class ReviewIntakeResultV1:
    status: IntakeStatus
    reason_codes: tuple[str, ...]
    request_sha256: str | None
    decisions_sha256: str | None
    subject_sha256: str | None
    receipt_sha256: str | None
    p0_decisions: int
    p1_decisions: int
    successor_records: tuple[GoldenRecord, ...] = ()
    result_sha256: str = ""

    def __post_init__(self) -> None:
        payload = {
            "status": self.status,
            "reason_codes": self.reason_codes,
            "request_sha256": self.request_sha256,
            "decisions_sha256": self.decisions_sha256,
            "subject_sha256": self.subject_sha256,
            "receipt_sha256": self.receipt_sha256,
            "p0_decisions": self.p0_decisions,
            "p1_decisions": self.p1_decisions,
            "successor_record_sha256s": tuple(
                golden_record_sha256(record) for record in self.successor_records
            ),
        }
        object.__setattr__(
            self,
            "result_sha256",
            canonical_hash(_RESULT_OBJECT_TYPE, payload),
        )


@dataclass(frozen=True, slots=True)
class SuccessorMaterializationV1:
    status: MaterializationStatus
    reason_codes: tuple[str, ...]
    records: tuple[GoldenRecord, ...]
    changed_field_ids: tuple[str, ...]
    non_review_unchanged_count: int
    artifact_binding: ArtifactBinding | None
    v1_artifact_sha256: str | None
    successor_sha256: str


def _is_sha256(value: object) -> bool:
    if type(value) is not str or len(value) != 64 or value != value.lower():
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _has_placeholder(value: object) -> bool:
    if type(value) is not str or not value.strip():
        return True
    lowered = value.casefold()
    return any(token in lowered for token in ("placeholder", "todo", "tbd", "unknown"))


def _is_placeholder_decision_reason(value: object) -> bool:
    if type(value) is not str or not value.strip():
        return True
    normalized = unicodedata.normalize("NFKC", value)
    normalized = " ".join(normalized.casefold().split())
    normalized = normalized.strip(_SURROUNDING_REASON_PUNCTUATION).strip()
    return normalized in _PLACEHOLDER_DECISION_REASONS


def golden_record_sha256(record: GoldenRecord) -> str:
    """Hash every managed GoldenRecord byte through the shared canonical envelope."""

    return canonical_hash(_RECORD_OBJECT_TYPE, record.model_dump(mode="python"))


def _provenance_payload(value: DecisionProvenanceV1) -> dict[str, object]:
    return {
        "workbook_sha256": value.workbook_sha256,
        "worksheet": value.worksheet,
        "row": value.row,
        "decision_cell": value.decision_cell,
    }


def _conversation_payload(value: ConversationProvenanceV1) -> dict[str, str]:
    return {
        "source_thread_id": value.source_thread_id,
        "conversation_id": value.conversation_id,
        "user_decision_ref": value.user_decision_ref,
    }


def _decision_payload(value: ReviewDecisionV1) -> dict[str, object]:
    return {
        "field_id": value.field_id,
        "priority": value.priority,
        "selection": value.selection,
        "current_record_sha256": value.current_record_sha256,
        "recommended_record_sha256": value.recommended_record_sha256,
        "custom_record_sha256": value.custom_record_sha256,
        "reason": value.reason,
        "provenance": _provenance_payload(value.provenance),
    }


def review_decisions_sha256(decisions: tuple[ReviewDecisionV1, ...]) -> str:
    """Hash caller-supplied decisions without creating or defaulting any choice."""

    return canonical_hash(
        _DECISIONS_OBJECT_TYPE,
        {
            "v1_golden_sha256": V1_GOLDEN_SHA256,
            "workbook_sha256": REVIEW_WORKBOOK_SHA256,
            "sources": tuple(asdict(source) for source in SOURCE_IDENTITIES),
            "decisions": tuple(_decision_payload(decision) for decision in decisions),
        },
    )


def review_request_sha256(request: ReviewIntakeRequestV1) -> str:
    """Bind one validated request, including its exact conversation provenance."""

    return canonical_hash(
        _REQUEST_OBJECT_TYPE,
        {
            "v1_golden_sha256": request.v1_golden_sha256,
            "workbook_sha256": request.workbook_sha256,
            "sources": tuple(asdict(source) for source in request.sources),
            "decisions_sha256": request.decisions_sha256,
            "provenance": _conversation_payload(request.provenance),
        },
    )


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def review_approval_subject_sha256(
    request: ReviewIntakeRequestV1,
    receipt: NamedHumanReviewReceiptV1,
) -> str:
    """Bind identities, choices, named actor, freshness and conversation provenance."""

    return canonical_hash(
        _SUBJECT_OBJECT_TYPE,
        {
            "v1_golden_sha256": request.v1_golden_sha256,
            "workbook_sha256": request.workbook_sha256,
            "sources": tuple(asdict(source) for source in request.sources),
            "decisions_sha256": request.decisions_sha256,
            "request_provenance": _conversation_payload(request.provenance),
            "issued_by": receipt.issued_by,
            "actor_type": receipt.actor_type,
            "principal_id": receipt.principal_id,
            "approved_by": receipt.approved_by,
            "action": receipt.action,
            "issued_at": _timestamp(receipt.issued_at),
            "expires_at": _timestamp(receipt.expires_at),
            "receipt_provenance": _conversation_payload(receipt.provenance),
            "signer_key_id": receipt.signer_key_id,
        },
    )


def _receipt_payload(receipt: NamedHumanReviewReceiptV1) -> dict[str, object]:
    return {
        "contract_id": receipt.contract_id,
        "issued_by": receipt.issued_by,
        "actor_type": receipt.actor_type,
        "principal_id": receipt.principal_id,
        "approved_by": receipt.approved_by,
        "action": receipt.action,
        "subject_sha256": receipt.subject_sha256,
        "decisions_sha256": receipt.decisions_sha256,
        "issued_at": _timestamp(receipt.issued_at),
        "expires_at": _timestamp(receipt.expires_at),
        "provenance": _conversation_payload(receipt.provenance),
        "signer_key_id": receipt.signer_key_id,
    }


def human_review_receipt_signing_bytes(
    receipt: NamedHumanReviewReceiptV1,
) -> bytes:
    """Return external signing bytes; this module deliberately exposes no signer."""

    return _SIGNATURE_DOMAIN + canonical_bytes(_receipt_payload(receipt))


def human_review_receipt_sha256(receipt: NamedHumanReviewReceiptV1) -> str:
    """Hash an externally signed receipt without trusting its declared digest."""

    return canonical_hash(
        _RECEIPT_OBJECT_TYPE,
        {**_receipt_payload(receipt), "signature_b64": receipt.signature_b64},
    )


def _valid_conversation_provenance(value: object) -> bool:
    if type(value) is not ConversationProvenanceV1:
        return False
    return (
        value.source_thread_id.startswith("019")
        and value.conversation_id.startswith("019")
        and value.user_decision_ref.startswith("user-message:")
        and not any(_has_placeholder(item) for item in _conversation_payload(value).values())
    )


def _valid_decision_provenance(
    value: object, expected: ReviewFieldV1
) -> bool:
    return (
        type(value) is DecisionProvenanceV1
        and value.workbook_sha256 == REVIEW_WORKBOOK_SHA256
        and value.worksheet == expected.priority
        and type(value.row) is int
        and value.row > 0
        and not _has_placeholder(value.decision_cell)
    )


def _replayable_record(record: object, field_id: str) -> bool:
    if type(record) is not GoldenRecord or record.field_id != field_id:
        return False
    if not record.product_id.strip() or not record.doc.strip() or not record.field_name.strip():
        return False
    if record.tri_state == "unknown":
        return record.value is None and not record.evidence
    if record.tri_state == "absent_explicitly" and record.value is not None:
        return False
    if record.tri_state == "present" and (
        type(record.value) is not str or not record.value.strip()
    ):
        return False
    return bool(record.evidence) and all(
        evidence.page > 0 and bool(evidence.quote.strip()) for evidence in record.evidence
    )


def _valid_bound_record(
    record: GoldenRecord | None,
    declared_sha256: str | None,
    field_id: str,
) -> bool:
    if record is None or not _is_sha256(declared_sha256):
        return False
    return (
        _replayable_record(record, field_id)
        and golden_record_sha256(record) == declared_sha256
    )


def _result(
    status: IntakeStatus,
    *reasons: str,
    request_sha256: str | None = None,
    decisions_sha256: str | None = None,
    subject_sha256: str | None = None,
    receipt_sha256: str | None = None,
    p0: int = 0,
    p1: int = 0,
) -> ReviewIntakeResultV1:
    return ReviewIntakeResultV1(
        status=status,
        reason_codes=tuple(reasons),
        request_sha256=request_sha256,
        decisions_sha256=decisions_sha256,
        subject_sha256=subject_sha256,
        receipt_sha256=receipt_sha256,
        p0_decisions=p0,
        p1_decisions=p1,
    )


def _valid_time(value: object) -> TypeGuard[datetime]:
    return (
        type(value) is datetime
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _validate_receipt(
    *,
    request: ReviewIntakeRequestV1,
    receipt: object,
    authority: object,
    now: object,
) -> tuple[str | None, str | None, tuple[str, ...]]:
    if type(receipt) is not NamedHumanReviewReceiptV1:
        return None, None, ("HUMAN_RECEIPT_MALFORMED",)
    if type(authority) is not NamedHumanAuthorityV1 or not isinstance(
        authority.public_key, Ed25519PublicKey
    ):
        return None, None, ("HUMAN_AUTHORITY_INVALID",)
    if not _valid_time(now) or not _valid_time(receipt.issued_at) or not _valid_time(
        receipt.expires_at
    ):
        return None, None, ("HUMAN_RECEIPT_TIME_INVALID",)
    scalar_values = (
        receipt.contract_id,
        receipt.issued_by,
        receipt.actor_type,
        receipt.principal_id,
        receipt.approved_by,
        receipt.action,
        receipt.subject_sha256,
        receipt.decisions_sha256,
        receipt.signer_key_id,
        receipt.signature_b64,
        receipt.receipt_sha256,
        authority.principal_id,
        authority.display_name,
        authority.signer_key_id,
    )
    if any(type(value) is not str for value in scalar_values):
        return None, None, ("HUMAN_RECEIPT_MALFORMED",)
    if receipt.contract_id != HUMAN_REVIEW_RECEIPT_CONTRACT_ID:
        return None, None, ("HUMAN_RECEIPT_CONTRACT_MISMATCH",)
    if (
        receipt.issued_by != "external-human-review"
        or receipt.actor_type != "human"
        or not authority.principal_id.startswith("human:")
        or receipt.principal_id != authority.principal_id
        or receipt.approved_by != authority.display_name
        or receipt.signer_key_id != authority.signer_key_id
        or any(
            _has_placeholder(value)
            for value in (
                receipt.principal_id,
                receipt.approved_by,
                receipt.signer_key_id,
            )
        )
        or not _valid_conversation_provenance(receipt.provenance)
    ):
        return None, None, ("HUMAN_RECEIPT_AUTHORITY_INVALID",)
    observed_at = now.astimezone(UTC)
    issued_at = receipt.issued_at.astimezone(UTC)
    expires_at = receipt.expires_at.astimezone(UTC)
    if expires_at <= issued_at or observed_at < issued_at or observed_at >= expires_at:
        return None, None, ("HUMAN_RECEIPT_STALE",)
    if (
        not _is_sha256(receipt.subject_sha256)
        or not _is_sha256(receipt.decisions_sha256)
        or not _is_sha256(receipt.receipt_sha256)
    ):
        return None, None, ("HUMAN_RECEIPT_MALFORMED",)
    try:
        expected_subject = review_approval_subject_sha256(request, receipt)
        expected_receipt_sha256 = human_review_receipt_sha256(receipt)
    except (TypeError, ValueError):
        return None, None, ("HUMAN_RECEIPT_MALFORMED",)
    if (
        receipt.decisions_sha256 != request.decisions_sha256
        or receipt.provenance != request.provenance
        or receipt.subject_sha256 != expected_subject
    ):
        return expected_subject, expected_receipt_sha256, (
            "HUMAN_RECEIPT_BINDING_MISMATCH",
        )
    if receipt.receipt_sha256 != expected_receipt_sha256:
        return expected_subject, expected_receipt_sha256, (
            "HUMAN_RECEIPT_HASH_MISMATCH",
        )
    try:
        signature = base64.b64decode(receipt.signature_b64, validate=True)
    except (ValueError, binascii.Error):
        return expected_subject, expected_receipt_sha256, (
            "HUMAN_RECEIPT_SIGNATURE_INVALID",
        )
    if (
        len(signature) != 64
        or base64.b64encode(signature).decode("ascii") != receipt.signature_b64
    ):
        return expected_subject, expected_receipt_sha256, (
            "HUMAN_RECEIPT_SIGNATURE_INVALID",
        )
    try:
        authority.public_key.verify(
            signature,
            human_review_receipt_signing_bytes(receipt),
        )
    except (InvalidSignature, ValueError, TypeError):
        return expected_subject, expected_receipt_sha256, (
            "HUMAN_RECEIPT_SIGNATURE_INVALID",
        )
    if receipt.action == "reject":
        return expected_subject, expected_receipt_sha256, (
            "HUMAN_DECISION_REJECTED",
        )
    if receipt.action != "approve":
        return expected_subject, expected_receipt_sha256, (
            "HUMAN_RECEIPT_ACTION_INVALID",
        )
    return expected_subject, expected_receipt_sha256, ()


def evaluate_review_intake(
    request: ReviewIntakeRequestV1,
    *,
    receipt: NamedHumanReviewReceiptV1 | None = None,
    authority: NamedHumanAuthorityV1 | None = None,
    now: datetime | None = None,
) -> ReviewIntakeResultV1:
    """Validate the frozen decision envelope; no path materializes or writes a Golden."""

    if type(request) is not ReviewIntakeRequestV1:
        return _result("BLOCKED", "REVIEW_REQUEST_MALFORMED")
    if (
        request.v1_golden_sha256 != V1_GOLDEN_SHA256
        or request.workbook_sha256 != REVIEW_WORKBOOK_SHA256
        or request.sources != SOURCE_IDENTITIES
        or not _valid_conversation_provenance(request.provenance)
        or not _is_sha256(request.decisions_sha256)
    ):
        return _result("BLOCKED", "REVIEW_INPUT_IDENTITY_INVALID")
    if type(request.decisions) is not tuple:
        return _result("BLOCKED", "REVIEW_DECISIONS_MALFORMED")
    supplied_fields = tuple(
        decision.field_id
        for decision in request.decisions
        if type(decision) is ReviewDecisionV1
    )
    if _EXCLUDED_REVIEW_FIELDS.intersection(supplied_fields):
        return _result("BLOCKED", "EXCLUDED_REVIEW_FIELD")
    if len(request.decisions) < len(REVIEW_FIELDS):
        return _result("PENDING", "REVIEW_DECISIONS_INCOMPLETE")
    if len(request.decisions) != len(REVIEW_FIELDS):
        return _result("BLOCKED", "REVIEW_DECISIONS_NOT_BIJECTIVE")

    needs_expert_pending = False
    not_applicable_pending = False
    for decision, expected in zip(request.decisions, REVIEW_FIELDS, strict=True):
        if type(decision) is not ReviewDecisionV1:
            return _result("BLOCKED", "REVIEW_DECISIONS_MALFORMED")
        if _is_placeholder_decision_reason(decision.reason):
            return _result("BLOCKED", "REVIEW_DECISION_REASON_PLACEHOLDER")
        if (
            decision.field_id != expected.field_id
            or decision.priority != expected.priority
            or decision.selection
            not in (
                "accept_recommendation",
                "keep_current",
                "custom",
                "needs_expert",
                "not_applicable",
            )
            or not _is_sha256(decision.current_record_sha256)
            or not _valid_decision_provenance(decision.provenance, expected)
        ):
            return _result("BLOCKED", "REVIEW_DECISIONS_NOT_BIJECTIVE")

        recommendation_supplied = (
            decision.recommended_record is not None
            or decision.recommended_record_sha256 is not None
        )
        if recommendation_supplied and not _valid_bound_record(
            decision.recommended_record,
            decision.recommended_record_sha256,
            decision.field_id,
        ):
            return _result("BLOCKED", "RECOMMENDED_RECORD_BINDING_INVALID")
        custom_supplied = (
            decision.custom_record is not None
            or decision.custom_record_sha256 is not None
        )
        if custom_supplied and not _valid_bound_record(
            decision.custom_record,
            decision.custom_record_sha256,
            decision.field_id,
        ):
            return _result("BLOCKED", "CUSTOM_RECORD_SEMANTICS_INVALID")
        if decision.selection == "accept_recommendation" and not recommendation_supplied:
            return _result("BLOCKED", "RECOMMENDED_RECORD_REQUIRED")
        if decision.selection == "custom" and not custom_supplied:
            return _result("BLOCKED", "CUSTOM_RECORD_REQUIRED")
        if decision.selection == "needs_expert":
            needs_expert_pending = True
        elif decision.selection == "not_applicable":
            not_applicable_pending = True

    try:
        replayed_sha256 = review_decisions_sha256(request.decisions)
    except (TypeError, ValueError):
        return _result("BLOCKED", "REVIEW_DECISIONS_MALFORMED")
    if replayed_sha256 != request.decisions_sha256:
        return _result("BLOCKED", "REVIEW_DECISIONS_HASH_MISMATCH")
    if needs_expert_pending or not_applicable_pending:
        request_sha256 = review_request_sha256(request)
        return _result(
            "PENDING",
            (
                "NOT_APPLICABLE_ALWAYS_PENDING"
                if not_applicable_pending
                else "BUSINESS_DECISION_UNRESOLVED"
            ),
            request_sha256=request_sha256,
            decisions_sha256=replayed_sha256,
            p0=7,
            p1=11,
        )
    request_sha256 = review_request_sha256(request)
    ready = _result(
        "READY_FOR_EXTERNAL_APPROVAL",
        request_sha256=request_sha256,
        decisions_sha256=replayed_sha256,
        p0=7,
        p1=11,
    )
    if receipt is None:
        return ready
    subject_sha256, receipt_sha256, receipt_reasons = _validate_receipt(
        request=request,
        receipt=receipt,
        authority=authority,
        now=now,
    )
    if receipt_reasons:
        return _result(
            "BLOCKED",
            *receipt_reasons,
            request_sha256=request_sha256,
            decisions_sha256=replayed_sha256,
            subject_sha256=subject_sha256,
            receipt_sha256=receipt_sha256,
            p0=7,
            p1=11,
        )
    return _result(
        "HUMAN_DECISIONS_VERIFIED",
        request_sha256=request_sha256,
        decisions_sha256=replayed_sha256,
        subject_sha256=subject_sha256,
        receipt_sha256=receipt_sha256,
        p0=7,
        p1=11,
    )


def _blocked_materialization(*reasons: str) -> SuccessorMaterializationV1:
    return SuccessorMaterializationV1(
        status="BLOCKED",
        reason_codes=tuple(reasons),
        records=(),
        changed_field_ids=(),
        non_review_unchanged_count=0,
        artifact_binding=None,
        v1_artifact_sha256=None,
        successor_sha256="",
    )


def _materialize_bound_records(
    v1_records: tuple[GoldenRecord, ...],
    *,
    request: ReviewIntakeRequestV1,
    receipt: NamedHumanReviewReceiptV1 | None,
    authority: NamedHumanAuthorityV1,
    now: datetime,
    artifact_binding: ArtifactBinding,
    v1_artifact_sha256: str,
) -> SuccessorMaterializationV1:
    verification = evaluate_review_intake(
        request,
        receipt=receipt,
        authority=authority,
        now=now,
    )
    if verification.status != "HUMAN_DECISIONS_VERIFIED":
        if verification.reason_codes:
            return _blocked_materialization(*verification.reason_codes)
        return _blocked_materialization("HUMAN_VERIFICATION_REQUIRED")
    if (
        type(v1_records) is not tuple
        or len(v1_records) != 60
        or any(type(record) is not GoldenRecord for record in v1_records)
    ):
        return _blocked_materialization("V1_RECORD_SET_INVALID")
    field_ids = tuple(record.field_id for record in v1_records)
    if (
        len(set(field_ids)) != 60
        or any(field.field_id not in field_ids for field in REVIEW_FIELDS)
        or HIGH_RISK_OCCUPATION_FIELD_ID not in field_ids
        or PRODUCT_TIER_FIELD_ID not in field_ids
    ):
        return _blocked_materialization("V1_RECORD_SET_INVALID")

    current_by_field = {record.field_id: record for record in v1_records}
    decisions_by_field = {decision.field_id: decision for decision in request.decisions}
    selected_by_field: dict[str, GoldenRecord] = {}
    for field in REVIEW_FIELDS:
        decision = decisions_by_field[field.field_id]
        current = current_by_field[field.field_id]
        if golden_record_sha256(current) != decision.current_record_sha256:
            return _blocked_materialization("CURRENT_RECORD_BINDING_MISMATCH")
        selected_sha256: str | None
        if decision.selection == "keep_current":
            selected_candidate: GoldenRecord | None = current
            selected_sha256 = decision.current_record_sha256
        elif decision.selection == "accept_recommendation":
            selected_candidate = decision.recommended_record
            selected_sha256 = decision.recommended_record_sha256
        elif decision.selection == "custom":
            selected_candidate = decision.custom_record
            selected_sha256 = decision.custom_record_sha256
        else:
            return _blocked_materialization("BUSINESS_DECISION_UNRESOLVED")
        if type(selected_candidate) is not GoldenRecord:
            return _blocked_materialization("SELECTED_RECORD_INVALID")
        selected = selected_candidate
        if (
            not _is_sha256(selected_sha256)
            or golden_record_sha256(selected) != selected_sha256
        ):
            return _blocked_materialization("SELECTED_RECORD_BINDING_MISMATCH")
        if (
            selected.product_id != current.product_id
            or selected.product_name != current.product_name
            or selected.field_id != current.field_id
            or selected.field_name != current.field_name
        ):
            return _blocked_materialization("SELECTED_RECORD_IDENTITY_DRIFT")
        selected_by_field[field.field_id] = selected

    successor = tuple(
        selected_by_field.get(record.field_id, record) for record in v1_records
    )
    review_field_ids = frozenset(field.field_id for field in REVIEW_FIELDS)
    changed_field_ids = tuple(
        before.field_id
        for before, after in zip(v1_records, successor, strict=True)
        if before.field_id in review_field_ids
        and golden_record_sha256(before) != golden_record_sha256(after)
    )
    non_review_unchanged_count = sum(
        1
        for before, after in zip(v1_records, successor, strict=True)
        if before.field_id not in review_field_ids
        and golden_record_sha256(before) == golden_record_sha256(after)
    )
    if non_review_unchanged_count != 42 or len(changed_field_ids) > 18:
        return _blocked_materialization("SUCCESSOR_SCOPE_VIOLATION")
    for excluded in (HIGH_RISK_OCCUPATION_FIELD_ID, PRODUCT_TIER_FIELD_ID):
        index = field_ids.index(excluded)
        if golden_record_sha256(v1_records[index]) != golden_record_sha256(successor[index]):
            return _blocked_materialization("EXCLUDED_FIELD_MUTATION")

    successor_sha256 = canonical_hash(
        _SUCCESSOR_OBJECT_TYPE,
        {
            "v1_golden_sha256": V1_GOLDEN_SHA256,
            "v1_artifact_sha256": v1_artifact_sha256,
            "artifact_binding": artifact_binding,
            "workbook_sha256": REVIEW_WORKBOOK_SHA256,
            "sources": tuple(asdict(source) for source in SOURCE_IDENTITIES),
            "request_sha256": verification.request_sha256,
            "decisions_sha256": verification.decisions_sha256,
            "human_subject_sha256": verification.subject_sha256,
            "human_receipt_sha256": verification.receipt_sha256,
            "ordered_record_sha256s": tuple(
                golden_record_sha256(record) for record in successor
            ),
            "changed_field_ids": changed_field_ids,
        },
    )
    return SuccessorMaterializationV1(
        status="MATERIALIZED",
        reason_codes=(),
        records=successor,
        changed_field_ids=changed_field_ids,
        non_review_unchanged_count=non_review_unchanged_count,
        artifact_binding=artifact_binding,
        v1_artifact_sha256=v1_artifact_sha256,
        successor_sha256=successor_sha256,
    )


def _materialize_synthetic_test_profile(
    v1_records: tuple[GoldenRecord, ...],
    *,
    request: ReviewIntakeRequestV1,
    receipt: NamedHumanReviewReceiptV1 | None,
    authority: NamedHumanAuthorityV1,
    now: datetime,
) -> SuccessorMaterializationV1:
    """Exercise selection mechanics without claiming formal 596-1 v1 identity."""

    synthetic_sha256 = canonical_hash(
        "golden-v2-596-1-synthetic-v1-profile.v1",
        tuple(golden_record_sha256(record) for record in v1_records),
    )
    return _materialize_bound_records(
        v1_records,
        request=request,
        receipt=receipt,
        authority=authority,
        now=now,
        artifact_binding="SYNTHETIC_TEST_ONLY",
        v1_artifact_sha256=synthetic_sha256,
    )


def _parse_formal_v1_jsonl(value: bytes) -> tuple[GoldenRecord, ...] | None:
    try:
        text = value.decode("utf-8")
        lines = text.splitlines()
        if len(lines) != 60 or any(not line.strip() for line in lines):
            return None
        records = tuple(
            GoldenRecord.model_validate(json.loads(line)) for line in lines
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError):
        return None
    return records


def materialize_verified_successor(
    v1_artifact_bytes: bytes,
    *,
    request: ReviewIntakeRequestV1,
    receipt: NamedHumanReviewReceiptV1 | None,
    authority: NamedHumanAuthorityV1,
    now: datetime,
) -> SuccessorMaterializationV1:
    """Materialize only from bytes proven to be the fixed formal 596-1 v1 JSONL."""

    if type(v1_artifact_bytes) is not bytes:
        return _blocked_materialization("V1_ARTIFACT_BYTES_INVALID")
    actual_sha256 = hashlib.sha256(v1_artifact_bytes).hexdigest()
    if actual_sha256 != V1_GOLDEN_SHA256:
        return _blocked_materialization("V1_ARTIFACT_SHA256_MISMATCH")
    records = _parse_formal_v1_jsonl(v1_artifact_bytes)
    if records is None:
        return _blocked_materialization("V1_ARTIFACT_PARSE_INVALID")
    return _materialize_bound_records(
        records,
        request=request,
        receipt=receipt,
        authority=authority,
        now=now,
        artifact_binding="FORMAL_596_1_V1",
        v1_artifact_sha256=actual_sha256,
    )


__all__ = [
    "ConversationProvenanceV1",
    "DecisionProvenanceV1",
    "ArtifactBinding",
    "HIGH_RISK_OCCUPATION_FIELD_ID",
    "HUMAN_REVIEW_RECEIPT_CONTRACT_ID",
    "HumanReceiptAction",
    "MaterializationStatus",
    "NamedHumanAuthorityV1",
    "NamedHumanReviewReceiptV1",
    "PRODUCT_TIER_FIELD_ID",
    "REVIEW_FIELDS",
    "REVIEW_WORKBOOK_SHA256",
    "ReviewDecisionV1",
    "ReviewFieldV1",
    "ReviewIntakeRequestV1",
    "ReviewIntakeResultV1",
    "ReviewSelection",
    "SOURCE_IDENTITIES",
    "SourceIdentityV1",
    "SuccessorMaterializationV1",
    "V1_GOLDEN_SHA256",
    "evaluate_review_intake",
    "golden_record_sha256",
    "human_review_receipt_sha256",
    "human_review_receipt_signing_bytes",
    "materialize_verified_successor",
    "review_approval_subject_sha256",
    "review_decisions_sha256",
    "review_request_sha256",
]
