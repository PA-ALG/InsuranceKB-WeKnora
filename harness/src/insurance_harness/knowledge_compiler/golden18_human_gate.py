"""Pure external named-human decision gate for the exact 596-1 Golden18 set."""

from __future__ import annotations

import base64
import binascii
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Final, Literal, TypeGuard

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from insurance_harness.canonical import canonical_bytes, canonical_hash

GOLDEN18_AUTHORITY_SHA256: Final[str] = (
    "23816ccdfa9258bb4785ed0d1032c8281c1eda047c7801543b2032649b567dc2"
)
HUMAN_RECEIPT_CONTRACT_ID: Final[str] = "596-1-golden18-named-human-receipt.v1"
_DECISIONS_OBJECT_TYPE: Final[str] = "golden18-596-1-decisions.v1"
_SUBJECT_OBJECT_TYPE: Final[str] = "golden18-596-1-human-subject.v1"
_RECEIPT_OBJECT_TYPE: Final[str] = "golden18-596-1-human-receipt.v1"
_RESULT_OBJECT_TYPE: Final[str] = "golden18-596-1-human-gate-result.v1"
_SIGNATURE_DOMAIN: Final[bytes] = b"insurance-harness:596-1-golden18-human-receipt:v1\0"

HumanChoice = Literal["weak", "strong", "reject_both"]
HumanReceiptAction = Literal["approve", "reject"]
GateStatus = Literal["PENDING", "BLOCKED", "HUMAN_GATE_VERIFIED"]
Priority = Literal["P0", "P1"]


@dataclass(frozen=True, slots=True)
class Golden18FieldV1:
    field_id: str
    field_name: str
    priority: Priority
    slot: int


GOLDEN18_FIELDS: Final[tuple[Golden18FieldV1, ...]] = (
    Golden18FieldV1("clause_version", "条款版本标识", "P0", 1),
    Golden18FieldV1("reduced_paid_up", "减额缴清", "P0", 2),
    Golden18FieldV1("reinstatement", "复效条款", "P0", 3),
    Golden18FieldV1("zh_0b3894ed2a", "产品类型", "P0", 4),
    Golden18FieldV1("zh_74aa1b9c93", "保证续保", "P0", 5),
    Golden18FieldV1("zh_d62301d84c", "宽限期", "P0", 6),
    Golden18FieldV1("zh_e1bea0527a", "特殊免责", "P0", 7),
    Golden18FieldV1("claim_filing_requirements", "理赔申请时效与申请材料", "P1", 1),
    Golden18FieldV1("exclusions_official", "责任免除", "P1", 2),
    Golden18FieldV1("external_drug_coverage", "外购药/特药责任", "P1", 3),
    Golden18FieldV1("waiting_period_claim_handling", "等待期内出险处理", "P1", 4),
    Golden18FieldV1("zh_09a5d9e54e", "保什么", "P1", 5),
    Golden18FieldV1("zh_3a3e6520a3", "给付限额", "P1", 6),
    Golden18FieldV1("zh_3d8424595d", "报销比例", "P1", 7),
    Golden18FieldV1("zh_4a789b1d6f", "报销范围", "P1", 8),
    Golden18FieldV1("zh_7d7fe38f09", "癌症医疗", "P1", 9),
    Golden18FieldV1("zh_7fe8603c08", "费用", "P1", 10),
    Golden18FieldV1("zh_f32c510a5e", "医院范围", "P1", 11),
)


@dataclass(frozen=True, slots=True)
class Golden18FieldDecisionV1:
    field_id: str
    priority: Priority
    choice: HumanChoice
    reason: str


@dataclass(frozen=True, slots=True)
class ConversationProvenanceV1:
    source_thread_id: str
    conversation_id: str
    user_approval_ref: str


@dataclass(frozen=True, slots=True)
class Golden18GateRequestV1:
    authority_sha256: str
    weak_output_sha256: str
    strong_output_sha256: str
    score_report_sha256: str
    decisions: tuple[Golden18FieldDecisionV1, ...]
    decisions_sha256: str
    provenance: ConversationProvenanceV1


@dataclass(frozen=True, slots=True)
class NamedHumanAuthorityV1:
    principal_id: str
    display_name: str
    signer_key_id: str
    public_key: Ed25519PublicKey


@dataclass(frozen=True, slots=True)
class NamedHumanDecisionReceiptV1:
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
class Golden18HumanGateResultV1:
    status: GateStatus
    reason_codes: tuple[str, ...]
    subject_sha256: str | None
    decisions_sha256: str | None
    receipt_sha256: str | None
    p0_decisions: int
    p1_decisions: int
    release_actions: Literal[0] = 0
    weknora_actions: Literal[0] = 0
    result_sha256: str = ""

    def __post_init__(self) -> None:
        payload = {key: value for key, value in asdict(self).items() if key != "result_sha256"}
        object.__setattr__(self, "result_sha256", canonical_hash(_RESULT_OBJECT_TYPE, payload))


def _is_sha256(value: object) -> bool:
    if type(value) is not str or len(value) != 64 or len(set(value)) <= 1:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _has_placeholder(value: str) -> bool:
    lowered = value.casefold()
    return not value.strip() or any(
        token in lowered for token in ("placeholder", "unknown", "todo", "tbd")
    )


def _provenance_payload(value: ConversationProvenanceV1) -> dict[str, str]:
    return {
        "source_thread_id": value.source_thread_id,
        "conversation_id": value.conversation_id,
        "user_approval_ref": value.user_approval_ref,
    }


def _valid_provenance(value: object) -> bool:
    if type(value) is not ConversationProvenanceV1:
        return False
    fields = tuple(_provenance_payload(value).values())
    return (
        all(type(item) is str and not _has_placeholder(item) for item in fields)
        and value.source_thread_id.startswith("019")
        and value.conversation_id.startswith("019")
        and value.user_approval_ref.startswith("user-message:")
    )


def _decision_payload(value: Golden18FieldDecisionV1) -> dict[str, str]:
    return {
        "field_id": value.field_id,
        "priority": value.priority,
        "choice": value.choice,
        "reason": value.reason,
    }


def golden18_decisions_sha256(decisions: tuple[Golden18FieldDecisionV1, ...]) -> str:
    """Hash the exact ordered field decisions; this function never creates a decision."""

    return canonical_hash(
        _DECISIONS_OBJECT_TYPE,
        {
            "authority_sha256": GOLDEN18_AUTHORITY_SHA256,
            "decisions": tuple(_decision_payload(decision) for decision in decisions),
        },
    )


def golden18_subject_sha256(request: Golden18GateRequestV1) -> str:
    """Recompute the exact external-approval subject."""

    return canonical_hash(
        _SUBJECT_OBJECT_TYPE,
        {
            "authority_sha256": request.authority_sha256,
            "weak_output_sha256": request.weak_output_sha256,
            "strong_output_sha256": request.strong_output_sha256,
            "score_report_sha256": request.score_report_sha256,
            "decisions_sha256": request.decisions_sha256,
            "provenance": _provenance_payload(request.provenance),
        },
    )


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _receipt_payload(receipt: NamedHumanDecisionReceiptV1) -> dict[str, object]:
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
        "provenance": _provenance_payload(receipt.provenance),
        "signer_key_id": receipt.signer_key_id,
    }


def human_receipt_signing_bytes(receipt: NamedHumanDecisionReceiptV1) -> bytes:
    """Return canonical external signing bytes; this module deliberately has no signer."""

    return _SIGNATURE_DOMAIN + canonical_bytes(_receipt_payload(receipt))


def human_receipt_sha256(receipt: NamedHumanDecisionReceiptV1) -> str:
    """Content-address one externally signed receipt without trusting its declared hash."""

    return canonical_hash(
        _RECEIPT_OBJECT_TYPE,
        {**_receipt_payload(receipt), "signature_b64": receipt.signature_b64},
    )


def _result(
    status: GateStatus,
    *reasons: str,
    subject: str | None = None,
    decisions: str | None = None,
    receipt: str | None = None,
    p0: int = 0,
    p1: int = 0,
) -> Golden18HumanGateResultV1:
    return Golden18HumanGateResultV1(
        status=status,
        reason_codes=tuple(reasons),
        subject_sha256=subject,
        decisions_sha256=decisions,
        receipt_sha256=receipt,
        p0_decisions=p0,
        p1_decisions=p1,
    )


def _validate_request(
    request: object,
) -> tuple[str | None, int, int, tuple[str, ...]]:
    if type(request) is not Golden18GateRequestV1:
        return None, 0, 0, ("GOLDEN18_REQUEST_MALFORMED",)
    hashes = (
        request.authority_sha256,
        request.weak_output_sha256,
        request.strong_output_sha256,
        request.score_report_sha256,
        request.decisions_sha256,
    )
    if (
        request.authority_sha256 != GOLDEN18_AUTHORITY_SHA256
        or any(not _is_sha256(value) for value in hashes)
        or not _valid_provenance(request.provenance)
    ):
        return None, 0, 0, ("GOLDEN18_INPUT_IDENTITY_INVALID",)
    if type(request.decisions) is not tuple:
        return None, 0, 0, ("GOLDEN18_DECISIONS_MALFORMED",)
    if len(request.decisions) < len(GOLDEN18_FIELDS):
        return None, 0, 0, ("GOLDEN18_DECISIONS_INCOMPLETE",)
    if len(request.decisions) != len(GOLDEN18_FIELDS):
        return None, 0, 0, ("GOLDEN18_DECISIONS_NOT_BIJECTIVE",)
    for decision, expected in zip(request.decisions, GOLDEN18_FIELDS, strict=True):
        if type(decision) is not Golden18FieldDecisionV1:
            return None, 0, 0, ("GOLDEN18_DECISIONS_MALFORMED",)
        values = tuple(_decision_payload(decision).values())
        if (
            any(type(value) is not str for value in values)
            or decision.field_id != expected.field_id
            or decision.priority != expected.priority
            or decision.choice not in ("weak", "strong", "reject_both")
            or _has_placeholder(decision.reason)
        ):
            return None, 0, 0, ("GOLDEN18_DECISIONS_NOT_BIJECTIVE",)
    try:
        replay = golden18_decisions_sha256(request.decisions)
        subject = golden18_subject_sha256(request)
    except (TypeError, ValueError):
        return None, 0, 0, ("GOLDEN18_DECISIONS_MALFORMED",)
    if replay != request.decisions_sha256:
        return None, 0, 0, ("GOLDEN18_DECISIONS_HASH_MISMATCH",)
    return subject, 7, 11, ()


def _valid_time(value: object) -> TypeGuard[datetime]:
    return (
        type(value) is datetime
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _validate_receipt_shape(
    receipt: object,
    authority: object,
    now: object,
) -> tuple[NamedHumanDecisionReceiptV1 | None, tuple[str, ...]]:
    if type(receipt) is not NamedHumanDecisionReceiptV1:
        return None, ("HUMAN_RECEIPT_MALFORMED",)
    if type(authority) is not NamedHumanAuthorityV1 or not isinstance(
        authority.public_key, Ed25519PublicKey
    ):
        return None, ("HUMAN_AUTHORITY_INVALID",)
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
        return None, ("HUMAN_RECEIPT_MALFORMED",)
    if (
        not _valid_time(now)
        or not _valid_time(receipt.issued_at)
        or not _valid_time(receipt.expires_at)
    ):
        return None, ("HUMAN_RECEIPT_TIME_INVALID",)
    if receipt.contract_id != HUMAN_RECEIPT_CONTRACT_ID:
        return None, ("HUMAN_RECEIPT_CONTRACT_MISMATCH",)
    if (
        receipt.issued_by != "total-control"
        or receipt.actor_type != "human"
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
        or not _valid_provenance(receipt.provenance)
    ):
        return None, ("HUMAN_RECEIPT_AUTHORITY_INVALID",)
    observed_at = now.astimezone(UTC)
    issued_at = receipt.issued_at.astimezone(UTC)
    expires_at = receipt.expires_at.astimezone(UTC)
    if expires_at <= issued_at or observed_at < issued_at or observed_at >= expires_at:
        return None, ("HUMAN_RECEIPT_STALE",)
    if (
        not _is_sha256(receipt.subject_sha256)
        or not _is_sha256(receipt.decisions_sha256)
        or not _is_sha256(receipt.receipt_sha256)
    ):
        return None, ("HUMAN_RECEIPT_MALFORMED",)
    return receipt, ()


def evaluate_golden18_human_gate(
    *,
    request: Golden18GateRequestV1,
    receipt: NamedHumanDecisionReceiptV1 | None,
    authority: NamedHumanAuthorityV1,
    now: datetime,
) -> Golden18HumanGateResultV1:
    """Verify the pure gate. No success path performs or authorizes publication I/O."""

    subject, p0, p1, request_reasons = _validate_request(request)
    if request_reasons:
        status: GateStatus = (
            "PENDING"
            if request_reasons == ("GOLDEN18_DECISIONS_INCOMPLETE",)
            else "BLOCKED"
        )
        return _result(status, *request_reasons)
    assert subject is not None
    if receipt is None:
        return _result(
            "PENDING",
            "EXTERNAL_HUMAN_RECEIPT_MISSING",
            subject=subject,
            decisions=request.decisions_sha256,
            p0=p0,
            p1=p1,
        )
    checked, receipt_reasons = _validate_receipt_shape(receipt, authority, now)
    if receipt_reasons:
        return _result(
            "BLOCKED",
            *receipt_reasons,
            subject=subject,
            decisions=request.decisions_sha256,
            p0=p0,
            p1=p1,
        )
    assert checked is not None
    if (
        checked.subject_sha256 != subject
        or checked.decisions_sha256 != request.decisions_sha256
        or checked.provenance != request.provenance
    ):
        return _result(
            "BLOCKED",
            "HUMAN_RECEIPT_BINDING_MISMATCH",
            subject=subject,
            decisions=request.decisions_sha256,
            p0=p0,
            p1=p1,
        )
    try:
        signature = base64.b64decode(checked.signature_b64, validate=True)
        if base64.b64encode(signature).decode("ascii") != checked.signature_b64:
            raise ValueError("noncanonical signature")
        authority.public_key.verify(signature, human_receipt_signing_bytes(checked))
        replayed_receipt_hash = human_receipt_sha256(checked)
    except (binascii.Error, InvalidSignature, TypeError, ValueError):
        return _result(
            "BLOCKED",
            "HUMAN_RECEIPT_SIGNATURE_INVALID",
            subject=subject,
            decisions=request.decisions_sha256,
            p0=p0,
            p1=p1,
        )
    if replayed_receipt_hash != checked.receipt_sha256:
        return _result(
            "BLOCKED",
            "HUMAN_RECEIPT_HASH_MISMATCH",
            subject=subject,
            decisions=request.decisions_sha256,
            p0=p0,
            p1=p1,
        )
    has_rejection = any(decision.choice == "reject_both" for decision in request.decisions)
    has_strong_choice = any(decision.choice == "strong" for decision in request.decisions)
    if checked.action == "reject" or has_rejection:
        return _result(
            "BLOCKED",
            "HUMAN_DECISION_REJECTED",
            subject=subject,
            decisions=request.decisions_sha256,
            receipt=checked.receipt_sha256,
            p0=p0,
            p1=p1,
        )
    if has_strong_choice:
        return _result(
            "BLOCKED",
            "WEAK_ARM_NOT_APPROVED",
            subject=subject,
            decisions=request.decisions_sha256,
            receipt=checked.receipt_sha256,
            p0=p0,
            p1=p1,
        )
    if checked.action != "approve":
        return _result(
            "BLOCKED",
            "HUMAN_DECISION_RECEIPT_MISMATCH",
            subject=subject,
            decisions=request.decisions_sha256,
            receipt=checked.receipt_sha256,
            p0=p0,
            p1=p1,
        )
    return _result(
        "HUMAN_GATE_VERIFIED",
        subject=subject,
        decisions=request.decisions_sha256,
        receipt=checked.receipt_sha256,
        p0=p0,
        p1=p1,
    )


__all__ = [
    "ConversationProvenanceV1",
    "GOLDEN18_AUTHORITY_SHA256",
    "GOLDEN18_FIELDS",
    "Golden18FieldDecisionV1",
    "Golden18FieldV1",
    "Golden18GateRequestV1",
    "Golden18HumanGateResultV1",
    "HUMAN_RECEIPT_CONTRACT_ID",
    "HumanChoice",
    "HumanReceiptAction",
    "NamedHumanAuthorityV1",
    "NamedHumanDecisionReceiptV1",
    "evaluate_golden18_human_gate",
    "golden18_decisions_sha256",
    "golden18_subject_sha256",
    "human_receipt_sha256",
    "human_receipt_signing_bytes",
]
