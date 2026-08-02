from __future__ import annotations

import base64
import hashlib
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.knowledge_compiler import field_contracts_596_1 as contracts

NOW = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)
PRIVATE_KEY = Ed25519PrivateKey.generate()
PROVENANCE = contracts.ConversationProvenanceV1(
    source_thread_id="019fa5ea-2507-73a2-acb8-d49030bad2f0",
    conversation_id="019fa5ea-2507-73a2-acb8-d49030bad2f0",
    user_approval_ref="user-message:596-1-exact8-field-contracts",
)
AUTHORITY = contracts.NamedHumanAuthorityV1(
    principal_id="human:596-1-field-contract-owner",
    display_name="596-1 field contract owner",
    signer_key_id="human-field-contract-key-2026-08",
    public_key=PRIVATE_KEY.public_key(),
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _request() -> contracts.FieldContractAuthorityRequestV1:
    return contracts.FieldContractAuthorityRequestV1(
        field_contracts_sha256=contracts.EXACT8_FIELD_CONTRACTS_SHA256,
        decision_package_sha256=contracts.DECISION_PACKAGE_SHA256,
        pending_resolution_sha256=_sha("external-user-resolution-bundle"),
        provenance=PROVENANCE,
    )


def _receipt(
    request: contracts.FieldContractAuthorityRequestV1,
    *,
    actor_type: str = "human",
    authority: contracts.NamedHumanAuthorityV1 = AUTHORITY,
    private_key: Ed25519PrivateKey = PRIVATE_KEY,
) -> contracts.FieldContractUserReceiptV1:
    unsigned = contracts.FieldContractUserReceiptV1(
        contract_id=contracts.FIELD_CONTRACT_USER_RECEIPT_ID,
        issued_by="total-control",
        actor_type=actor_type,
        principal_id=authority.principal_id,
        approved_by=authority.display_name,
        action="approve",
        subject_sha256=contracts.field_contract_authority_subject_sha256(request),
        field_contracts_sha256=request.field_contracts_sha256,
        decision_package_sha256=request.decision_package_sha256,
        pending_resolution_sha256=request.pending_resolution_sha256,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        provenance=request.provenance,
        signer_key_id=authority.signer_key_id,
        signature_b64="",
        receipt_sha256="",
    )
    signature = base64.b64encode(
        private_key.sign(contracts.field_contract_receipt_signing_bytes(unsigned))
    ).decode("ascii")
    signed = replace(unsigned, signature_b64=signature)
    return replace(
        signed,
        receipt_sha256=contracts.field_contract_receipt_sha256(signed),
    )


def test_exact8_identity_status_and_source_authority_are_frozen() -> None:
    actual = tuple(
        (
            row.field_id,
            row.field_name,
            row.authority_class,
            row.primary_role,
            row.support_roles,
            row.status,
            row.decision_package_sha256,
        )
        for row in contracts.EXACT8_FIELD_CONTRACTS
    )
    assert actual == (
        (
            "clause_version",
            "条款版本标识",
            "contract_fact",
            "terms",
            ("brochure",),
            "FROZEN_NO_USER_DECISION_REQUIRED",
            None,
        ),
        (
            "zh_1ec5e3f2cc",
            "犹豫期及合同解除（退保）",
            "contract_fact",
            "terms",
            ("brochure",),
            "FROZEN_NO_USER_DECISION_REQUIRED",
            None,
        ),
        (
            "zh_3d8424595d",
            "报销比例",
            "contract_fact",
            "terms",
            ("brochure",),
            "FROZEN_NO_USER_DECISION_REQUIRED",
            None,
        ),
        (
            "zh_f32c510a5e",
            "医院范围",
            "contract_fact",
            "terms",
            ("brochure",),
            "FROZEN_NO_USER_DECISION_REQUIRED",
            None,
        ),
        (
            "zh_2df7d6256c",
            "高危职业",
            "contract_fact",
            "terms",
            ("brochure",),
            "NONE_PENDING_USER_CONFIRMATION",
            contracts.DECISION_PACKAGE_SHA256,
        ),
        (
            "zh_7fe8603c08",
            "费用",
            "rate_numeric",
            "rate_table",
            ("terms", "brochure"),
            "NONE_PENDING_USER_CONFIRMATION",
            contracts.DECISION_PACKAGE_SHA256,
        ),
        (
            "zh_b7ceabc3c0",
            "产品档次",
            "brochure_fact",
            "brochure",
            ("terms",),
            "NONE_PENDING_USER_CONFIRMATION",
            contracts.DECISION_PACKAGE_SHA256,
        ),
        (
            "zh_e1bea0527a",
            "特殊免责",
            "contract_fact",
            "terms",
            ("brochure",),
            "NONE_PENDING_USER_CONFIRMATION",
            contracts.DECISION_PACKAGE_SHA256,
        ),
    )

    pending = [asdict(row) for row in contracts.EXACT8_FIELD_CONTRACTS[4:]]
    assert all(
        not any(token in key for token in ("choice", "option", "selected", "default"))
        for row in pending
        for key in row
    )


def test_missing_exact_user_receipt_blocks_before_provider() -> None:
    result = contracts.evaluate_field_contract_authority(
        request=_request(),
        receipt=None,
        authority=AUTHORITY,
        now=NOW,
    )

    assert result.status == "BLOCKED_ON_FIELD_CONTRACT_AUTHORITY"
    assert result.reason_codes == ("EXACT_USER_RECEIPT_MISSING",)
    assert result.provider_calls == 0
    assert result.release_actions == result.weknora_actions == 0


def test_exact_external_named_human_receipt_verifies_without_resolving_rows() -> None:
    request = _request()
    receipt = _receipt(request)

    result = contracts.evaluate_field_contract_authority(
        request=request,
        receipt=receipt,
        authority=AUTHORITY,
        now=NOW,
    )

    assert result.status == "FIELD_CONTRACT_AUTHORITY_VERIFIED"
    assert result.reason_codes == ()
    assert result.subject_sha256 == receipt.subject_sha256
    assert result.receipt_sha256 == receipt.receipt_sha256
    assert result.provider_calls == 0
    assert all(
        row.status == "NONE_PENDING_USER_CONFIRMATION"
        for row in contracts.EXACT8_FIELD_CONTRACTS[4:]
    )


def test_package_subject_resolution_and_content_hash_drift_block() -> None:
    request = _request()
    valid = _receipt(request)
    cases = (
        (replace(request, decision_package_sha256=_sha("foreign-package")), valid),
        (replace(request, field_contracts_sha256=_sha("foreign-contracts")), valid),
        (replace(request, pending_resolution_sha256=_sha("foreign-resolution")), valid),
        (request, replace(valid, subject_sha256=_sha("foreign-subject"))),
        (request, replace(valid, receipt_sha256=_sha("foreign-receipt"))),
    )

    for candidate_request, candidate_receipt in cases:
        result = contracts.evaluate_field_contract_authority(
            request=candidate_request,
            receipt=candidate_receipt,
            authority=AUTHORITY,
            now=NOW,
        )
        assert result.status == "BLOCKED_ON_FIELD_CONTRACT_AUTHORITY"
        assert result.provider_calls == 0


def test_service_placeholder_stale_foreign_and_signature_tamper_block() -> None:
    request = _request()
    valid = _receipt(request)
    foreign_private = Ed25519PrivateKey.generate()
    foreign_authority = replace(AUTHORITY, public_key=foreign_private.public_key())
    cases = (
        (_receipt(request, actor_type="service"), AUTHORITY, NOW),
        (replace(valid, approved_by="placeholder"), AUTHORITY, NOW),
        (valid, AUTHORITY, valid.expires_at),
        (valid, foreign_authority, NOW),
        (replace(valid, signature_b64="A" * 88), AUTHORITY, NOW),
    )

    for receipt, authority, observed_at in cases:
        result = contracts.evaluate_field_contract_authority(
            request=request,
            receipt=receipt,
            authority=authority,
            now=observed_at,
        )
        assert result.status == "BLOCKED_ON_FIELD_CONTRACT_AUTHORITY"
        assert result.provider_calls == 0
