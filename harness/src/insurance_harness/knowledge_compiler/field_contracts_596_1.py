"""Task-local exact8 field contracts and external authority gate for 596-1."""

from __future__ import annotations

import base64
import binascii
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Final, Literal, TypeGuard

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from insurance_harness.canonical import canonical_bytes, canonical_hash
from insurance_harness.knowledge_compiler.golden18_human_gate import (
    ConversationProvenanceV1,
    NamedHumanAuthorityV1,
)

DECISION_PACKAGE_SHA256: Final[str] = (
    "43af184fc27295467b5130b1b88953c073049fd02309b78c53ac59d6f1937e26"
)
FIELD_CONTRACT_USER_RECEIPT_ID: Final[str] = (
    "596-1-exact8-field-contract-user-receipt.v1"
)
_CONTRACTS_OBJECT_TYPE: Final[str] = "exact8-596-1-field-contracts.v1"
_SUBJECT_OBJECT_TYPE: Final[str] = "exact8-596-1-field-contract-subject.v1"
_RECEIPT_OBJECT_TYPE: Final[str] = "exact8-596-1-field-contract-receipt.v1"
_RESULT_OBJECT_TYPE: Final[str] = "exact8-596-1-field-contract-result.v1"
_SIGNATURE_DOMAIN: Final[bytes] = (
    b"insurance-harness:596-1-exact8-field-contract-user-receipt:v1\0"
)

ContractStatus = Literal[
    "FROZEN_NO_USER_DECISION_REQUIRED", "NONE_PENDING_USER_CONFIRMATION"
]
AuthorityStatus = Literal[
    "BLOCKED_ON_FIELD_CONTRACT_AUTHORITY", "FIELD_CONTRACT_AUTHORITY_VERIFIED"
]
ReceiptAction = Literal["approve"]


@dataclass(frozen=True, slots=True)
class Exact8FieldContractV1:
    field_id: str
    field_name: str
    authority_class: str
    primary_role: str
    support_roles: tuple[str, ...]
    status: ContractStatus
    decision_package_sha256: str | None


EXACT8_FIELD_CONTRACTS: Final[tuple[Exact8FieldContractV1, ...]] = (
    Exact8FieldContractV1(
        "clause_version",
        "条款版本标识",
        "contract_fact",
        "terms",
        ("brochure",),
        "FROZEN_NO_USER_DECISION_REQUIRED",
        None,
    ),
    Exact8FieldContractV1(
        "zh_1ec5e3f2cc",
        "犹豫期及合同解除（退保）",
        "contract_fact",
        "terms",
        ("brochure",),
        "FROZEN_NO_USER_DECISION_REQUIRED",
        None,
    ),
    Exact8FieldContractV1(
        "zh_3d8424595d",
        "报销比例",
        "contract_fact",
        "terms",
        ("brochure",),
        "FROZEN_NO_USER_DECISION_REQUIRED",
        None,
    ),
    Exact8FieldContractV1(
        "zh_f32c510a5e",
        "医院范围",
        "contract_fact",
        "terms",
        ("brochure",),
        "FROZEN_NO_USER_DECISION_REQUIRED",
        None,
    ),
    Exact8FieldContractV1(
        "zh_2df7d6256c",
        "高危职业",
        "contract_fact",
        "terms",
        ("brochure",),
        "NONE_PENDING_USER_CONFIRMATION",
        DECISION_PACKAGE_SHA256,
    ),
    Exact8FieldContractV1(
        "zh_7fe8603c08",
        "费用",
        "rate_numeric",
        "rate_table",
        ("terms", "brochure"),
        "NONE_PENDING_USER_CONFIRMATION",
        DECISION_PACKAGE_SHA256,
    ),
    Exact8FieldContractV1(
        "zh_b7ceabc3c0",
        "产品档次",
        "brochure_fact",
        "brochure",
        ("terms",),
        "NONE_PENDING_USER_CONFIRMATION",
        DECISION_PACKAGE_SHA256,
    ),
    Exact8FieldContractV1(
        "zh_e1bea0527a",
        "特殊免责",
        "contract_fact",
        "terms",
        ("brochure",),
        "NONE_PENDING_USER_CONFIRMATION",
        DECISION_PACKAGE_SHA256,
    ),
)


def _field_contract_payload(value: Exact8FieldContractV1) -> dict[str, object]:
    return {
        "field_id": value.field_id,
        "field_name": value.field_name,
        "authority_class": value.authority_class,
        "primary_role": value.primary_role,
        "support_roles": value.support_roles,
        "status": value.status,
        "decision_package_sha256": value.decision_package_sha256,
    }


EXACT8_FIELD_CONTRACTS_SHA256: Final[str] = canonical_hash(
    _CONTRACTS_OBJECT_TYPE,
    {"contracts": tuple(_field_contract_payload(row) for row in EXACT8_FIELD_CONTRACTS)},
)


@dataclass(frozen=True, slots=True)
class FieldContractAuthorityRequestV1:
    field_contracts_sha256: str
    decision_package_sha256: str
    pending_resolution_sha256: str
    provenance: ConversationProvenanceV1


@dataclass(frozen=True, slots=True)
class FieldContractUserReceiptV1:
    contract_id: str
    issued_by: str
    actor_type: str
    principal_id: str
    approved_by: str
    action: ReceiptAction
    subject_sha256: str
    field_contracts_sha256: str
    decision_package_sha256: str
    pending_resolution_sha256: str
    issued_at: datetime
    expires_at: datetime
    provenance: ConversationProvenanceV1
    signer_key_id: str
    signature_b64: str
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class FieldContractAuthorityResultV1:
    status: AuthorityStatus
    reason_codes: tuple[str, ...]
    subject_sha256: str | None
    receipt_sha256: str | None
    provider_calls: Literal[0] = 0
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


def field_contract_authority_subject_sha256(
    request: FieldContractAuthorityRequestV1,
) -> str:
    """Recompute the exact subject an external user receipt must approve."""

    return canonical_hash(
        _SUBJECT_OBJECT_TYPE,
        {
            "field_contracts_sha256": request.field_contracts_sha256,
            "decision_package_sha256": request.decision_package_sha256,
            "pending_resolution_sha256": request.pending_resolution_sha256,
            "provenance": _provenance_payload(request.provenance),
        },
    )


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _receipt_payload(receipt: FieldContractUserReceiptV1) -> dict[str, object]:
    return {
        "contract_id": receipt.contract_id,
        "issued_by": receipt.issued_by,
        "actor_type": receipt.actor_type,
        "principal_id": receipt.principal_id,
        "approved_by": receipt.approved_by,
        "action": receipt.action,
        "subject_sha256": receipt.subject_sha256,
        "field_contracts_sha256": receipt.field_contracts_sha256,
        "decision_package_sha256": receipt.decision_package_sha256,
        "pending_resolution_sha256": receipt.pending_resolution_sha256,
        "issued_at": _timestamp(receipt.issued_at),
        "expires_at": _timestamp(receipt.expires_at),
        "provenance": _provenance_payload(receipt.provenance),
        "signer_key_id": receipt.signer_key_id,
    }


def field_contract_receipt_signing_bytes(receipt: FieldContractUserReceiptV1) -> bytes:
    """Return canonical signing bytes; this module intentionally has no signer."""

    return _SIGNATURE_DOMAIN + canonical_bytes(_receipt_payload(receipt))


def field_contract_receipt_sha256(receipt: FieldContractUserReceiptV1) -> str:
    """Content-address an external receipt without trusting its declared hash."""

    return canonical_hash(
        _RECEIPT_OBJECT_TYPE,
        {**_receipt_payload(receipt), "signature_b64": receipt.signature_b64},
    )


def _result(
    status: AuthorityStatus,
    *reasons: str,
    subject: str | None = None,
    receipt: str | None = None,
) -> FieldContractAuthorityResultV1:
    return FieldContractAuthorityResultV1(
        status=status,
        reason_codes=tuple(reasons),
        subject_sha256=subject,
        receipt_sha256=receipt,
    )


def _validate_request(
    request: object,
) -> tuple[str | None, tuple[str, ...]]:
    if type(request) is not FieldContractAuthorityRequestV1:
        return None, ("FIELD_CONTRACT_AUTHORITY_REQUEST_MALFORMED",)
    scalar_values = (
        request.field_contracts_sha256,
        request.decision_package_sha256,
        request.pending_resolution_sha256,
    )
    if any(type(value) is not str for value in scalar_values):
        return None, ("FIELD_CONTRACT_AUTHORITY_REQUEST_MALFORMED",)
    if (
        request.field_contracts_sha256 != EXACT8_FIELD_CONTRACTS_SHA256
        or request.decision_package_sha256 != DECISION_PACKAGE_SHA256
        or not _is_sha256(request.pending_resolution_sha256)
        or not _valid_provenance(request.provenance)
    ):
        return None, ("FIELD_CONTRACT_AUTHORITY_IDENTITY_MISMATCH",)
    try:
        return field_contract_authority_subject_sha256(request), ()
    except (TypeError, ValueError):
        return None, ("FIELD_CONTRACT_AUTHORITY_REQUEST_MALFORMED",)


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
) -> tuple[FieldContractUserReceiptV1 | None, tuple[str, ...]]:
    if type(receipt) is not FieldContractUserReceiptV1:
        return None, ("FIELD_CONTRACT_USER_RECEIPT_MALFORMED",)
    if type(authority) is not NamedHumanAuthorityV1 or not isinstance(
        authority.public_key, Ed25519PublicKey
    ):
        return None, ("FIELD_CONTRACT_HUMAN_AUTHORITY_INVALID",)
    scalar_values = (
        receipt.contract_id,
        receipt.issued_by,
        receipt.actor_type,
        receipt.principal_id,
        receipt.approved_by,
        receipt.action,
        receipt.subject_sha256,
        receipt.field_contracts_sha256,
        receipt.decision_package_sha256,
        receipt.pending_resolution_sha256,
        receipt.signer_key_id,
        receipt.signature_b64,
        receipt.receipt_sha256,
        authority.principal_id,
        authority.display_name,
        authority.signer_key_id,
    )
    if any(type(value) is not str for value in scalar_values):
        return None, ("FIELD_CONTRACT_USER_RECEIPT_MALFORMED",)
    if (
        not _valid_time(now)
        or not _valid_time(receipt.issued_at)
        or not _valid_time(receipt.expires_at)
    ):
        return None, ("FIELD_CONTRACT_USER_RECEIPT_TIME_INVALID",)
    if receipt.contract_id != FIELD_CONTRACT_USER_RECEIPT_ID:
        return None, ("FIELD_CONTRACT_USER_RECEIPT_CONTRACT_MISMATCH",)
    if (
        receipt.issued_by != "total-control"
        or receipt.actor_type != "human"
        or receipt.action != "approve"
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
        return None, ("FIELD_CONTRACT_USER_RECEIPT_AUTHORITY_INVALID",)
    observed_at = now.astimezone(UTC)
    issued_at = receipt.issued_at.astimezone(UTC)
    expires_at = receipt.expires_at.astimezone(UTC)
    if expires_at <= issued_at or observed_at < issued_at or observed_at >= expires_at:
        return None, ("FIELD_CONTRACT_USER_RECEIPT_STALE",)
    hashes = (
        receipt.subject_sha256,
        receipt.field_contracts_sha256,
        receipt.decision_package_sha256,
        receipt.pending_resolution_sha256,
        receipt.receipt_sha256,
    )
    if any(not _is_sha256(value) for value in hashes):
        return None, ("FIELD_CONTRACT_USER_RECEIPT_MALFORMED",)
    return receipt, ()


def evaluate_field_contract_authority(
    *,
    request: FieldContractAuthorityRequestV1,
    receipt: FieldContractUserReceiptV1 | None,
    authority: NamedHumanAuthorityV1,
    now: datetime,
) -> FieldContractAuthorityResultV1:
    """Verify the exact external authority gate without any provider side effect."""

    subject, request_reasons = _validate_request(request)
    if request_reasons:
        return _result("BLOCKED_ON_FIELD_CONTRACT_AUTHORITY", *request_reasons)
    assert subject is not None
    if receipt is None:
        return _result(
            "BLOCKED_ON_FIELD_CONTRACT_AUTHORITY",
            "EXACT_USER_RECEIPT_MISSING",
            subject=subject,
        )
    checked, receipt_reasons = _validate_receipt_shape(receipt, authority, now)
    if receipt_reasons:
        return _result(
            "BLOCKED_ON_FIELD_CONTRACT_AUTHORITY",
            *receipt_reasons,
            subject=subject,
        )
    assert checked is not None
    if (
        checked.subject_sha256 != subject
        or checked.field_contracts_sha256 != request.field_contracts_sha256
        or checked.decision_package_sha256 != request.decision_package_sha256
        or checked.pending_resolution_sha256 != request.pending_resolution_sha256
        or checked.provenance != request.provenance
    ):
        return _result(
            "BLOCKED_ON_FIELD_CONTRACT_AUTHORITY",
            "FIELD_CONTRACT_USER_RECEIPT_BINDING_MISMATCH",
            subject=subject,
        )
    try:
        signature = base64.b64decode(checked.signature_b64, validate=True)
        if base64.b64encode(signature).decode("ascii") != checked.signature_b64:
            raise ValueError("noncanonical signature")
        authority.public_key.verify(
            signature, field_contract_receipt_signing_bytes(checked)
        )
        replayed_receipt_hash = field_contract_receipt_sha256(checked)
    except (binascii.Error, InvalidSignature, TypeError, ValueError):
        return _result(
            "BLOCKED_ON_FIELD_CONTRACT_AUTHORITY",
            "FIELD_CONTRACT_USER_RECEIPT_SIGNATURE_INVALID",
            subject=subject,
        )
    if replayed_receipt_hash != checked.receipt_sha256:
        return _result(
            "BLOCKED_ON_FIELD_CONTRACT_AUTHORITY",
            "FIELD_CONTRACT_USER_RECEIPT_HASH_MISMATCH",
            subject=subject,
        )
    return _result(
        "FIELD_CONTRACT_AUTHORITY_VERIFIED",
        subject=subject,
        receipt=checked.receipt_sha256,
    )


__all__ = [
    "DECISION_PACKAGE_SHA256",
    "EXACT8_FIELD_CONTRACTS",
    "EXACT8_FIELD_CONTRACTS_SHA256",
    "FIELD_CONTRACT_USER_RECEIPT_ID",
    "ConversationProvenanceV1",
    "Exact8FieldContractV1",
    "FieldContractAuthorityRequestV1",
    "FieldContractAuthorityResultV1",
    "FieldContractUserReceiptV1",
    "NamedHumanAuthorityV1",
    "evaluate_field_contract_authority",
    "field_contract_authority_subject_sha256",
    "field_contract_receipt_sha256",
    "field_contract_receipt_signing_bytes",
]
