from __future__ import annotations

import base64
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.knowledge_compiler import golden18_human_gate as gate


def _sha(char: str) -> str:
    return hashlib.sha256(char.encode("ascii")).hexdigest()


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
PROVENANCE = gate.ConversationProvenanceV1(
    source_thread_id="019fa5ea-2507-73a2-acb8-d49030bad2f0",
    conversation_id="019fa5ea-2507-73a2-acb8-d49030bad2f0",
    user_approval_ref="user-message:golden18-explicit-decision",
)
PRIVATE_KEY = Ed25519PrivateKey.generate()
AUTHORITY = gate.NamedHumanAuthorityV1(
    principal_id="human:reviewer-596-1",
    display_name="596-1 named reviewer",
    signer_key_id="human-reviewer-key-2026-08",
    public_key=PRIVATE_KEY.public_key(),
)


def _decisions(
    *, choice: gate.HumanChoice = "weak", count: int = 18
) -> tuple[gate.Golden18FieldDecisionV1, ...]:
    return tuple(
        gate.Golden18FieldDecisionV1(
            field_id=field.field_id,
            priority=field.priority,
            choice=choice,
            reason="named human checked the frozen weak/strong evidence",
        )
        for field in gate.GOLDEN18_FIELDS[:count]
    )


def _request(
    decisions: tuple[gate.Golden18FieldDecisionV1, ...] | None = None,
) -> gate.Golden18GateRequestV1:
    rows = _decisions() if decisions is None else decisions
    return gate.Golden18GateRequestV1(
        authority_sha256=gate.GOLDEN18_AUTHORITY_SHA256,
        weak_output_sha256=_sha("1"),
        strong_output_sha256=_sha("2"),
        score_report_sha256=_sha("3"),
        decisions=rows,
        decisions_sha256=gate.golden18_decisions_sha256(rows),
        provenance=PROVENANCE,
    )


def _receipt(
    request: gate.Golden18GateRequestV1,
    *,
    action: gate.HumanReceiptAction = "approve",
    actor_type: str = "human",
    authority: gate.NamedHumanAuthorityV1 = AUTHORITY,
    private_key: Ed25519PrivateKey = PRIVATE_KEY,
) -> gate.NamedHumanDecisionReceiptV1:
    unsigned = gate.NamedHumanDecisionReceiptV1(
        contract_id=gate.HUMAN_RECEIPT_CONTRACT_ID,
        issued_by="total-control",
        actor_type=actor_type,
        principal_id=authority.principal_id,
        approved_by=authority.display_name,
        action=action,
        subject_sha256=gate.golden18_subject_sha256(request),
        decisions_sha256=request.decisions_sha256,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        provenance=request.provenance,
        signer_key_id=authority.signer_key_id,
        signature_b64="",
        receipt_sha256="",
    )
    signature = base64.b64encode(
        private_key.sign(gate.human_receipt_signing_bytes(unsigned))
    ).decode("ascii")
    signed = replace(unsigned, signature_b64=signature)
    return replace(signed, receipt_sha256=gate.human_receipt_sha256(signed))


def test_exact_authority_tuple_is_frozen() -> None:
    actual = [
        (field.field_id, field.field_name, field.priority, field.slot)
        for field in gate.GOLDEN18_FIELDS
    ]
    assert actual == [
        ("clause_version", "条款版本标识", "P0", 1),
        ("reduced_paid_up", "减额缴清", "P0", 2),
        ("reinstatement", "复效条款", "P0", 3),
        ("zh_0b3894ed2a", "产品类型", "P0", 4),
        ("zh_74aa1b9c93", "保证续保", "P0", 5),
        ("zh_d62301d84c", "宽限期", "P0", 6),
        ("zh_e1bea0527a", "特殊免责", "P0", 7),
        ("claim_filing_requirements", "理赔申请时效与申请材料", "P1", 1),
        ("exclusions_official", "责任免除", "P1", 2),
        ("external_drug_coverage", "外购药/特药责任", "P1", 3),
        ("waiting_period_claim_handling", "等待期内出险处理", "P1", 4),
        ("zh_09a5d9e54e", "保什么", "P1", 5),
        ("zh_3a3e6520a3", "给付限额", "P1", 6),
        ("zh_3d8424595d", "报销比例", "P1", 7),
        ("zh_4a789b1d6f", "报销范围", "P1", 8),
        ("zh_7d7fe38f09", "癌症医疗", "P1", 9),
        ("zh_7fe8603c08", "费用", "P1", 10),
        ("zh_f32c510a5e", "医院范围", "P1", 11),
    ]
    assert gate.GOLDEN18_AUTHORITY_SHA256 == (
        "23816ccdfa9258bb4785ed0d1032c8281c1eda047c7801543b2032649b567dc2"
    )


def test_missing_decisions_and_receipt_are_typed_pending() -> None:
    complete = _request()
    missing_rows = complete.decisions[:-1]
    incomplete = replace(
        complete,
        decisions=missing_rows,
        decisions_sha256=gate.golden18_decisions_sha256(missing_rows),
    )

    decision_result = gate.evaluate_golden18_human_gate(
        request=incomplete,
        receipt=None,
        authority=AUTHORITY,
        now=NOW,
    )
    receipt_result = gate.evaluate_golden18_human_gate(
        request=complete,
        receipt=None,
        authority=AUTHORITY,
        now=NOW,
    )

    assert decision_result.status == "PENDING"
    assert decision_result.reason_codes == ("GOLDEN18_DECISIONS_INCOMPLETE",)
    assert receipt_result.status == "PENDING"
    assert receipt_result.reason_codes == ("EXTERNAL_HUMAN_RECEIPT_MISSING",)
    assert decision_result.release_actions == receipt_result.release_actions == 0
    assert decision_result.weknora_actions == receipt_result.weknora_actions == 0


def test_exact_decisions_and_named_human_receipt_verify() -> None:
    request = _request()
    receipt = _receipt(request)

    result = gate.evaluate_golden18_human_gate(
        request=request,
        receipt=receipt,
        authority=AUTHORITY,
        now=NOW,
    )

    assert result.status == "HUMAN_GATE_VERIFIED"
    assert result.reason_codes == ()
    assert result.p0_decisions == 7
    assert result.p1_decisions == 11
    assert result.subject_sha256 == gate.golden18_subject_sha256(request)
    assert result.receipt_sha256 == receipt.receipt_sha256
    assert result.release_actions == result.weknora_actions == 0


def test_decision_bijection_priority_and_hash_drift_block() -> None:
    request = _request()
    cases = (
        replace(request, decisions=request.decisions + (request.decisions[0],)),
        replace(
            request,
            decisions=(replace(request.decisions[0], priority="P1"),)
            + request.decisions[1:],
        ),
        replace(
            request,
            decisions=(replace(request.decisions[0], choice="strong"),)
            + request.decisions[1:],
        ),
        replace(request, decisions_sha256=_sha("4")),
    )

    for candidate in cases:
        result = gate.evaluate_golden18_human_gate(
            request=candidate,
            receipt=None,
            authority=AUTHORITY,
            now=NOW,
        )
        assert result.status == "BLOCKED"
        assert result.release_actions == result.weknora_actions == 0


def test_service_placeholder_stale_foreign_and_tamper_block() -> None:
    request = _request()
    valid = _receipt(request)
    foreign_private = Ed25519PrivateKey.generate()
    foreign_authority = replace(AUTHORITY, public_key=foreign_private.public_key())
    cases = (
        (_receipt(request, actor_type="service"), AUTHORITY, NOW),
        (replace(valid, approved_by="placeholder"), AUTHORITY, NOW),
        (valid, AUTHORITY, valid.expires_at),
        (valid, foreign_authority, NOW),
        (replace(valid, subject_sha256=_sha("5")), AUTHORITY, NOW),
        (replace(valid, signature_b64="A" * 88), AUTHORITY, NOW),
    )

    for receipt, authority, observed_at in cases:
        result = gate.evaluate_golden18_human_gate(
            request=request,
            receipt=receipt,
            authority=authority,
            now=observed_at,
        )
        assert result.status == "BLOCKED"
        assert result.release_actions == result.weknora_actions == 0


def test_conversation_subject_and_explicit_rejection_are_bound() -> None:
    request = _request()
    approved = _receipt(request)
    changed_provenance = replace(
        request,
        provenance=replace(PROVENANCE, conversation_id="01900000000000000000000000000000"),
    )
    rejected_request = _request(_decisions(choice="reject_both"))
    rejected_receipt = _receipt(rejected_request, action="reject")

    drift = gate.evaluate_golden18_human_gate(
        request=changed_provenance,
        receipt=approved,
        authority=AUTHORITY,
        now=NOW,
    )
    rejected = gate.evaluate_golden18_human_gate(
        request=rejected_request,
        receipt=rejected_receipt,
        authority=AUTHORITY,
        now=NOW,
    )

    assert drift.status == "BLOCKED"
    assert "HUMAN_RECEIPT_BINDING_MISMATCH" in drift.reason_codes
    assert rejected.status == "BLOCKED"
    assert rejected.reason_codes == ("HUMAN_DECISION_REJECTED",)
    assert rejected.receipt_sha256 == rejected_receipt.receipt_sha256


def test_strong_choice_never_becomes_release_authority() -> None:
    all_strong = _request(_decisions(choice="strong"))
    single_strong_decisions = (
        replace(_decisions()[0], choice="strong"),
    ) + _decisions()[1:]
    single_strong = _request(single_strong_decisions)

    for request in (all_strong, single_strong):
        result = gate.evaluate_golden18_human_gate(
            request=request,
            receipt=_receipt(request),
            authority=AUTHORITY,
            now=NOW,
        )

        assert result.status == "BLOCKED"
        assert result.reason_codes == ("WEAK_ARM_NOT_APPROVED",)
        assert result.release_actions == result.weknora_actions == 0


def test_exact_authority_and_hash_inputs_fail_closed() -> None:
    request = _request()
    candidates = (
        replace(request, authority_sha256="0" * 64),
        replace(request, weak_output_sha256="0" * 64),
        replace(request, strong_output_sha256="0" * 64),
        replace(request, score_report_sha256="0" * 64),
    )
    for candidate in candidates:
        result = gate.evaluate_golden18_human_gate(
            request=candidate,
            receipt=None,
            authority=AUTHORITY,
            now=NOW,
        )
        assert result.status == "BLOCKED"
        assert result.release_actions == result.weknora_actions == 0


def test_module_has_no_release_weknora_or_approval_mint_surface() -> None:
    forbidden = {
        "approve",
        "create_receipt",
        "mint_receipt",
        "publish",
        "release",
        "weknora",
    }
    public = {name.casefold() for name in gate.__all__}
    assert forbidden.isdisjoint(public)
