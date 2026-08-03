from __future__ import annotations

import base64
import hashlib
import inspect
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.goldenset import golden_v2_review_intake_596_1 as intake
from insurance_harness.goldenset.records import Evidence, GoldenRecord


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


NOW = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)
PROVENANCE = intake.ConversationProvenanceV1(
    source_thread_id="019fa5ea-2507-73a2-acb8-d49030bad2f0",
    conversation_id="019fa5ea-2507-73a2-acb8-d49030bad2f0",
    user_decision_ref="user-message:596-1-workbook-decisions",
)
PRIVATE_KEY = Ed25519PrivateKey.generate()
AUTHORITY = intake.NamedHumanAuthorityV1(
    principal_id="human:596-1-business-reviewer",
    display_name="596-1 named business reviewer",
    signer_key_id="human-review-596-1-2026-08",
    public_key=PRIVATE_KEY.public_key(),
)


def _record(field_id: str, *, value: str | None = None) -> GoldenRecord:
    resolved_value = f"v1:{field_id}" if value is None else value
    return GoldenRecord(
        product_id="596-1",
        product_name="synthetic-596-1",
        doc="synthetic-primary.pdf",
        field_id=field_id,
        field_name=f"field:{field_id}",
        value=resolved_value,
        tri_state="present",
        evidence=[Evidence(page=1, quote=f"evidence:{field_id}:{resolved_value}")],
        disputed=False,
        disputed_reason=None,
        reasoning="synthetic 075 fixture",
        annotator_model="human-review-fixture",
        schema_version="596-1.synthetic.v1",
        created_at=NOW,
    )


def _v1_records() -> tuple[GoldenRecord, ...]:
    authority_fields = [field.field_id for field in intake.REVIEW_FIELDS]
    other_fields = [
        intake.HIGH_RISK_OCCUPATION_FIELD_ID,
        intake.PRODUCT_TIER_FIELD_ID,
        *(f"synthetic_non_review_{index:02d}" for index in range(40)),
    ]
    return tuple(_record(field_id) for field_id in authority_fields + other_fields)


def _synthetic_jsonl_bytes(records: tuple[GoldenRecord, ...]) -> bytes:
    return (
        "\n".join(
            json.dumps(
                record.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            for record in records
        )
        + "\n"
    ).encode("utf-8")


def _decisions(
    records: tuple[GoldenRecord, ...] | None = None,
) -> tuple[intake.ReviewDecisionV1, ...]:
    source = _v1_records() if records is None else records
    by_field = {record.field_id: record for record in source}
    return tuple(
        intake.ReviewDecisionV1(
            field_id=field.field_id,
            priority=field.priority,
            selection="keep_current",
            current_record_sha256=intake.golden_record_sha256(by_field[field.field_id]),
            recommended_record=None,
            recommended_record_sha256=None,
            custom_record=None,
            custom_record_sha256=None,
            reason="named reviewer must make this explicit choice",
            provenance=intake.DecisionProvenanceV1(
                workbook_sha256=intake.REVIEW_WORKBOOK_SHA256,
                worksheet=field.priority,
                row=field.slot + 1,
                decision_cell=f"H{field.slot + 1}",
            ),
        )
        for field in intake.REVIEW_FIELDS
    )


def _request(
    decisions: tuple[intake.ReviewDecisionV1, ...] | None = None,
) -> intake.ReviewIntakeRequestV1:
    rows = _decisions() if decisions is None else decisions
    return intake.ReviewIntakeRequestV1(
        v1_golden_sha256=intake.V1_GOLDEN_SHA256,
        workbook_sha256=intake.REVIEW_WORKBOOK_SHA256,
        sources=intake.SOURCE_IDENTITIES,
        decisions=rows,
        decisions_sha256=intake.review_decisions_sha256(rows),
        provenance=PROVENANCE,
    )


def _receipt(
    request: intake.ReviewIntakeRequestV1,
    *,
    authority: intake.NamedHumanAuthorityV1 = AUTHORITY,
    private_key: Ed25519PrivateKey = PRIVATE_KEY,
    actor_type: str = "human",
    issued_by: str = "external-human-review",
    action: intake.HumanReceiptAction = "approve",
) -> intake.NamedHumanReviewReceiptV1:
    unsigned = intake.NamedHumanReviewReceiptV1(
        contract_id=intake.HUMAN_REVIEW_RECEIPT_CONTRACT_ID,
        issued_by=issued_by,
        actor_type=actor_type,
        principal_id=authority.principal_id,
        approved_by=authority.display_name,
        action=action,
        subject_sha256="",
        decisions_sha256=request.decisions_sha256,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        provenance=request.provenance,
        signer_key_id=authority.signer_key_id,
        signature_b64="",
        receipt_sha256="",
    )
    bound = replace(
        unsigned,
        subject_sha256=intake.review_approval_subject_sha256(request, unsigned),
    )
    signature = base64.b64encode(
        private_key.sign(intake.human_review_receipt_signing_bytes(bound))
    ).decode("ascii")
    signed = replace(bound, signature_b64=signature)
    return replace(
        signed,
        receipt_sha256=intake.human_review_receipt_sha256(signed),
    )


def _materialization_decisions(
    records: tuple[GoldenRecord, ...],
) -> tuple[intake.ReviewDecisionV1, ...]:
    current_by_field = {record.field_id: record for record in records}
    decisions: list[intake.ReviewDecisionV1] = []
    for index, field in enumerate(intake.REVIEW_FIELDS):
        current = current_by_field[field.field_id]
        recommendation = (
            current.model_copy(
                update={
                    "value": f"recommended:{field.field_id}",
                    "evidence": [
                        Evidence(
                            page=2,
                            quote=f"recommended evidence:{field.field_id}",
                        )
                    ],
                }
            )
            if index != 0
            else None
        )
        custom = (
            current.model_copy(
                update={
                    "value": f"custom:{field.field_id}",
                    "evidence": [
                        Evidence(page=3, quote=f"custom evidence:{field.field_id}")
                    ],
                }
            )
            if index == 2
            else None
        )
        selection: intake.ReviewSelection
        if index == 0:
            selection = "keep_current"
        elif index == 2:
            selection = "custom"
        else:
            selection = "accept_recommendation"
        decisions.append(
            intake.ReviewDecisionV1(
                field_id=field.field_id,
                priority=field.priority,
                selection=selection,
                current_record_sha256=intake.golden_record_sha256(current),
                recommended_record=recommendation,
                recommended_record_sha256=(
                    intake.golden_record_sha256(recommendation)
                    if recommendation is not None
                    else None
                ),
                custom_record=custom,
                custom_record_sha256=(
                    intake.golden_record_sha256(custom) if custom is not None else None
                ),
                reason="explicit synthetic human decision for materialization",
                provenance=intake.DecisionProvenanceV1(
                    workbook_sha256=intake.REVIEW_WORKBOOK_SHA256,
                    worksheet=field.priority,
                    row=field.slot + 1,
                    decision_cell=f"H{field.slot + 1}",
                ),
            )
        )
    return tuple(decisions)


def _verified_materialization_input() -> tuple[
    tuple[GoldenRecord, ...],
    intake.ReviewIntakeRequestV1,
    intake.NamedHumanReviewReceiptV1,
]:
    records = _v1_records()
    request = _request(_materialization_decisions(records))
    receipt = _receipt(request)
    verification = intake.evaluate_review_intake(
        request,
        receipt=receipt,
        authority=AUTHORITY,
        now=NOW,
    )
    assert verification.status == "HUMAN_DECISIONS_VERIFIED"
    return records, request, receipt


def test_exact_identities_and_original_ordered_eighteen_are_frozen() -> None:
    assert intake.V1_GOLDEN_SHA256 == (
        "562c37c7cf262e2e78f0b3ca4b7de4b0dab2f407d3cd7318a8a69b5dca33d8fb"
    )
    assert intake.REVIEW_WORKBOOK_SHA256 == (
        "ad51172eeee8dac177afff2319a0f8c14f09a82786846eaa227005dc1ac54edf"
    )
    assert [(source.role, source.sha256) for source in intake.SOURCE_IDENTITIES] == [
        ("terms", "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"),
        ("manual", "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279"),
        ("rate", "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb"),
    ]
    assert [
        (field.field_id, field.field_name, field.priority, field.slot)
        for field in intake.REVIEW_FIELDS
    ] == [
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
    assert len(intake.REVIEW_FIELDS) == 18
    assert {
        intake.HIGH_RISK_OCCUPATION_FIELD_ID,
        intake.PRODUCT_TIER_FIELD_ID,
    }.isdisjoint(field.field_id for field in intake.REVIEW_FIELDS)


def test_exact_complete_decisions_are_ready_for_external_approval() -> None:
    result = intake.evaluate_review_intake(_request())

    assert result.status == "READY_FOR_EXTERNAL_APPROVAL"
    assert result.reason_codes == ()
    assert result.p0_decisions == 7
    assert result.p1_decisions == 11
    assert result.successor_records == ()


def test_v1_workbook_or_source_identity_drift_blocks() -> None:
    request = _request()
    candidates = (
        replace(request, v1_golden_sha256=_sha("foreign-v1")),
        replace(request, workbook_sha256=_sha("foreign-workbook")),
        replace(request, sources=tuple(reversed(intake.SOURCE_IDENTITIES))),
    )

    for candidate in candidates:
        result = intake.evaluate_review_intake(candidate)
        assert result.status == "BLOCKED"
        assert result.reason_codes == ("REVIEW_INPUT_IDENTITY_INVALID",)
        assert result.successor_records == ()


def test_missing_decision_is_typed_pending_with_zero_successor() -> None:
    request = _request()
    missing = request.decisions[:-1]
    candidate = replace(
        request,
        decisions=missing,
        decisions_sha256=intake.review_decisions_sha256(missing),
    )

    result = intake.evaluate_review_intake(candidate)

    assert result.status == "PENDING"
    assert result.reason_codes == ("REVIEW_DECISIONS_INCOMPLETE",)
    assert result.successor_records == ()


@pytest.mark.parametrize("case", ["duplicate", "extra", "reordered", "priority", "hash"])
def test_non_bijective_or_drifted_decisions_block(case: str) -> None:
    request = _request()
    decisions = request.decisions
    if case == "duplicate":
        changed = decisions + (decisions[0],)
    elif case == "extra":
        changed = decisions + (
            replace(decisions[0], field_id="synthetic_non_review_00"),
        )
    elif case == "reordered":
        changed = (decisions[1], decisions[0], *decisions[2:])
    elif case == "priority":
        changed = (replace(decisions[0], priority="P1"), *decisions[1:])
    else:
        result = intake.evaluate_review_intake(
            replace(request, decisions_sha256=_sha("drift"))
        )
        assert result.status == "BLOCKED"
        assert result.successor_records == ()
        return
    candidate = replace(
        request,
        decisions=changed,
        decisions_sha256=intake.review_decisions_sha256(changed),
    )

    result = intake.evaluate_review_intake(candidate)

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("REVIEW_DECISIONS_NOT_BIJECTIVE",)
    assert result.successor_records == ()


@pytest.mark.parametrize(
    "field_id",
    [intake.HIGH_RISK_OCCUPATION_FIELD_ID, intake.PRODUCT_TIER_FIELD_ID],
)
def test_high_risk_occupation_and_product_tier_cannot_enter_review(
    field_id: str,
) -> None:
    request = _request()
    changed = request.decisions + (replace(request.decisions[0], field_id=field_id),)
    candidate = replace(
        request,
        decisions=changed,
        decisions_sha256=intake.review_decisions_sha256(changed),
    )

    result = intake.evaluate_review_intake(candidate)

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("EXCLUDED_REVIEW_FIELD",)
    assert result.successor_records == ()


@pytest.mark.parametrize(
    ("selection", "expected_reason"),
    [
        ("needs_expert", "BUSINESS_DECISION_UNRESOLVED"),
        ("not_applicable", "NOT_APPLICABLE_ALWAYS_PENDING"),
    ],
)
def test_unmapped_business_choices_stay_pending(
    selection: intake.ReviewSelection,
    expected_reason: str,
) -> None:
    request = _request()
    changed = (
        replace(request.decisions[0], selection=selection),
        *request.decisions[1:],
    )
    candidate = replace(
        request,
        decisions=changed,
        decisions_sha256=intake.review_decisions_sha256(changed),
    )

    result = intake.evaluate_review_intake(candidate)

    assert result.status == "PENDING"
    assert result.reason_codes == (expected_reason,)
    assert result.successor_records == ()


def test_custom_requires_complete_replayable_golden_record_semantics() -> None:
    request = _request()
    current = _v1_records()[0]
    bad_unknown = current.model_copy(
        update={"tri_state": "unknown", "value": "guessed", "evidence": []}
    )
    changed = (
        replace(
            request.decisions[0],
            selection="custom",
            custom_record=bad_unknown,
            custom_record_sha256=intake.golden_record_sha256(bad_unknown),
        ),
        *request.decisions[1:],
    )
    candidate = replace(
        request,
        decisions=changed,
        decisions_sha256=intake.review_decisions_sha256(changed),
    )

    result = intake.evaluate_review_intake(candidate)

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("CUSTOM_RECORD_SEMANTICS_INVALID",)
    assert result.successor_records == ()


@pytest.mark.parametrize("tri_state", ["present", "absent_explicitly"])
def test_custom_present_or_absent_requires_replayable_evidence(
    tri_state: str,
) -> None:
    request = _request()
    current = _v1_records()[0]
    invalid = current.model_copy(
        update={
            "tri_state": tri_state,
            "value": "custom" if tri_state == "present" else None,
            "evidence": [],
        }
    )
    changed = (
        replace(
            request.decisions[0],
            selection="custom",
            custom_record=invalid,
            custom_record_sha256=intake.golden_record_sha256(invalid),
        ),
        *request.decisions[1:],
    )
    candidate = replace(
        request,
        decisions=changed,
        decisions_sha256=intake.review_decisions_sha256(changed),
    )

    result = intake.evaluate_review_intake(candidate)

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("CUSTOM_RECORD_SEMANTICS_INVALID",)


def test_accept_recommendation_requires_exact_complete_record_binding() -> None:
    request = _request()
    missing = (
        replace(request.decisions[0], selection="accept_recommendation"),
        *request.decisions[1:],
    )
    current = _v1_records()[0]
    recommendation = current.model_copy(update={"value": "recommended"})
    drifted = (
        replace(
            request.decisions[0],
            selection="accept_recommendation",
            recommended_record=recommendation,
            recommended_record_sha256=_sha("wrong-recommendation"),
        ),
        *request.decisions[1:],
    )

    for decisions, reason in (
        (missing, "RECOMMENDED_RECORD_REQUIRED"),
        (drifted, "RECOMMENDED_RECORD_BINDING_INVALID"),
    ):
        candidate = replace(
            request,
            decisions=decisions,
            decisions_sha256=intake.review_decisions_sha256(decisions),
        )
        result = intake.evaluate_review_intake(candidate)
        assert result.status == "BLOCKED"
        assert result.reason_codes == (reason,)


def test_unknown_explanation_is_not_treated_as_a_defaulted_decision() -> None:
    request = _request()
    changed = (
        replace(
            request.decisions[0],
            reason="原文未覆盖，人工明确选择保留当前 unknown 结论",
        ),
        *request.decisions[1:],
    )
    candidate = replace(
        request,
        decisions=changed,
        decisions_sha256=intake.review_decisions_sha256(changed),
    )

    result = intake.evaluate_review_intake(candidate)

    assert result.status == "READY_FOR_EXTERNAL_APPROVAL"
    assert result.reason_codes == ()


@pytest.mark.parametrize(
    "reason",
    [
        "TODO",
        "tbd",
        "placeholder",
        "unknown",
        "待定",
        "待确认",
        "未知",
        "TODO!",
        "TBD???",
        "待定。",
        "未知！",
    ],
)
def test_placeholder_decision_reasons_block(reason: str) -> None:
    request = _request()
    changed = (
        replace(request.decisions[0], reason=reason),
        *request.decisions[1:],
    )
    candidate = replace(
        request,
        decisions=changed,
        decisions_sha256=intake.review_decisions_sha256(changed),
    )

    result = intake.evaluate_review_intake(candidate)

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("REVIEW_DECISION_REASON_PLACEHOLDER",)


def test_substantive_reason_containing_placeholder_words_remains_valid() -> None:
    request = _request()
    changed = (
        replace(
            request.decisions[0],
            reason="业务复核确认原文未覆盖，因此保留 unknown；这不是 TODO。",
        ),
        *request.decisions[1:],
    )
    candidate = replace(
        request,
        decisions=changed,
        decisions_sha256=intake.review_decisions_sha256(changed),
    )

    result = intake.evaluate_review_intake(candidate)

    assert result.status == "READY_FOR_EXTERNAL_APPROVAL"
    assert result.reason_codes == ()


def test_exact_external_named_human_receipt_verifies() -> None:
    request = _request()
    receipt = _receipt(request)

    result = intake.evaluate_review_intake(
        request,
        receipt=receipt,
        authority=AUTHORITY,
        now=NOW,
    )

    assert result.status == "HUMAN_DECISIONS_VERIFIED"
    assert result.reason_codes == ()
    assert result.subject_sha256 == receipt.subject_sha256
    assert result.receipt_sha256 == receipt.receipt_sha256
    assert result.successor_records == ()


def test_receipt_binds_decisions_actor_expiry_and_conversation() -> None:
    request = _request()
    receipt = _receipt(request)
    changed_decisions = (
        replace(request.decisions[0], reason="a changed explicit human reason"),
        *request.decisions[1:],
    )
    changed_request = replace(
        request,
        decisions=changed_decisions,
        decisions_sha256=intake.review_decisions_sha256(changed_decisions),
    )
    changed_provenance = replace(
        request,
        provenance=replace(
            request.provenance,
            user_decision_ref="user-message:different-review",
        ),
    )

    for candidate in (changed_request, changed_provenance):
        result = intake.evaluate_review_intake(
            candidate,
            receipt=receipt,
            authority=AUTHORITY,
            now=NOW,
        )
        assert result.status == "BLOCKED"
        assert result.reason_codes == ("HUMAN_RECEIPT_BINDING_MISMATCH",)
        assert result.successor_records == ()


def test_service_self_placeholder_foreign_stale_and_workbook_drift_block() -> None:
    request = _request()
    valid = _receipt(request)
    foreign_private = Ed25519PrivateKey.generate()
    foreign_authority = replace(
        AUTHORITY,
        public_key=foreign_private.public_key(),
    )
    placeholder_authority = replace(AUTHORITY, display_name="placeholder")
    cases = (
        (_receipt(request, actor_type="service"), AUTHORITY, NOW),
        (_receipt(request, issued_by="insurance-harness"), AUTHORITY, NOW),
        (_receipt(request, authority=placeholder_authority), placeholder_authority, NOW),
        (valid, foreign_authority, NOW),
        (valid, AUTHORITY, valid.expires_at),
    )

    for receipt, authority, observed_at in cases:
        result = intake.evaluate_review_intake(
            request,
            receipt=receipt,
            authority=authority,
            now=observed_at,
        )
        assert result.status == "BLOCKED"
        assert result.successor_records == ()

    workbook_drift = intake.evaluate_review_intake(
        replace(request, workbook_sha256=_sha("changed-workbook")),
        receipt=valid,
        authority=AUTHORITY,
        now=NOW,
    )
    assert workbook_drift.status == "BLOCKED"
    assert workbook_drift.reason_codes == ("REVIEW_INPUT_IDENTITY_INVALID",)


def test_rejected_or_missing_external_receipt_cannot_verify() -> None:
    request = _request()
    ready = intake.evaluate_review_intake(
        request,
        receipt=None,
        authority=AUTHORITY,
        now=NOW,
    )
    rejected = intake.evaluate_review_intake(
        request,
        receipt=_receipt(request, action="reject"),
        authority=AUTHORITY,
        now=NOW,
    )

    assert ready.status == "READY_FOR_EXTERNAL_APPROVAL"
    assert rejected.status == "BLOCKED"
    assert rejected.reason_codes == ("HUMAN_DECISION_REJECTED",)
    assert ready.successor_records == rejected.successor_records == ()


def test_module_exposes_verification_but_no_signer_or_approval_mint() -> None:
    forbidden = {
        "approve",
        "create_receipt",
        "mint_receipt",
        "sign",
        "sign_receipt",
    }
    assert forbidden.isdisjoint(name.casefold() for name in intake.__all__)


def test_verified_materialization_is_pure_ordered_and_authority_bounded() -> None:
    records, request, receipt = _verified_materialization_input()

    result = intake._materialize_synthetic_test_profile(
        records,
        request=request,
        receipt=receipt,
        authority=AUTHORITY,
        now=NOW,
    )

    assert result.status == "MATERIALIZED"
    assert result.reason_codes == ()
    assert len(result.records) == 60
    assert [record.field_id for record in result.records] == [
        record.field_id for record in records
    ]
    assert result.records[0] == records[0]
    assert result.records[1] == request.decisions[1].recommended_record
    assert result.records[2] == request.decisions[2].custom_record
    assert result.changed_field_ids == tuple(
        field.field_id for field in intake.REVIEW_FIELDS[1:]
    )
    assert result.non_review_unchanged_count == 42
    assert result.artifact_binding == "SYNTHETIC_TEST_ONLY"
    assert intake.golden_record_sha256(
        result.records[18]
    ) == intake.golden_record_sha256(records[18])
    assert intake.golden_record_sha256(
        result.records[19]
    ) == intake.golden_record_sha256(records[19])
    assert len(result.successor_sha256) == 64


def test_materialization_is_deterministic_and_content_addressed() -> None:
    records, request, receipt = _verified_materialization_input()

    first = intake._materialize_synthetic_test_profile(
        records,
        request=request,
        receipt=receipt,
        authority=AUTHORITY,
        now=NOW,
    )
    second = intake._materialize_synthetic_test_profile(
        records,
        request=request,
        receipt=receipt,
        authority=AUTHORITY,
        now=NOW,
    )
    mutated_non_review = list(records)
    mutated_non_review[-1] = mutated_non_review[-1].model_copy(
        update={"value": "changed managed byte"}
    )
    changed = intake._materialize_synthetic_test_profile(
        tuple(mutated_non_review),
        request=request,
        receipt=receipt,
        authority=AUTHORITY,
        now=NOW,
    )

    assert first == second
    assert changed.status == "MATERIALIZED"
    assert changed.successor_sha256 != first.successor_sha256


def test_current_review_record_drift_blocks_materialization() -> None:
    records, request, receipt = _verified_materialization_input()
    mutated = list(records)
    mutated[0] = mutated[0].model_copy(update={"value": "drifted current value"})

    result = intake._materialize_synthetic_test_profile(
        tuple(mutated),
        request=request,
        receipt=receipt,
        authority=AUTHORITY,
        now=NOW,
    )

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("CURRENT_RECORD_BINDING_MISMATCH",)
    assert result.records == ()
    assert result.successor_sha256 == ""


def test_selected_record_mutation_after_receipt_blocks_materialization() -> None:
    records, request, receipt = _verified_materialization_input()
    recommendation = request.decisions[1].recommended_record
    assert recommendation is not None
    recommendation.value = "mutated after named-human receipt"

    result = intake._materialize_synthetic_test_profile(
        records,
        request=request,
        receipt=receipt,
        authority=AUTHORITY,
        now=NOW,
    )

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("RECOMMENDED_RECORD_BINDING_INVALID",)
    assert result.records == ()


def test_publicly_constructed_verified_result_is_not_materialization_authority() -> None:
    records = _v1_records()
    request = _request(_materialization_decisions(records))
    forged = intake.ReviewIntakeResultV1(
        status="HUMAN_DECISIONS_VERIFIED",
        reason_codes=(),
        request_sha256=intake.review_request_sha256(request),
        decisions_sha256=request.decisions_sha256,
        subject_sha256=_sha("forged-subject"),
        receipt_sha256=_sha("forged-receipt"),
        p0_decisions=7,
        p1_decisions=11,
    )

    assert forged.status == "HUMAN_DECISIONS_VERIFIED"
    assert "verification" not in inspect.signature(
        intake.materialize_verified_successor
    ).parameters
    result = intake._materialize_synthetic_test_profile(
        records,
        request=request,
        receipt=None,
        authority=AUTHORITY,
        now=NOW,
    )

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("HUMAN_VERIFICATION_REQUIRED",)
    assert result.records == ()


def test_formal_materialization_rejects_arbitrary_synthetic_v1_bytes() -> None:
    records, request, receipt = _verified_materialization_input()

    result = intake.materialize_verified_successor(
        _synthetic_jsonl_bytes(records),
        request=request,
        receipt=receipt,
        authority=AUTHORITY,
        now=NOW,
    )

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("V1_ARTIFACT_SHA256_MISMATCH",)
    assert result.records == ()
    assert result.artifact_binding is None


def test_post_signature_decision_replacement_with_retained_hash_blocks() -> None:
    records, request, receipt = _verified_materialization_input()
    current = records[0]
    injected = current.model_copy(
        update={
            "value": "unsigned post-receipt replacement",
            "evidence": [Evidence(page=9, quote="not covered by the signed decision hash")],
        }
    )
    replaced = (
        replace(
            request.decisions[0],
            selection="accept_recommendation",
            recommended_record=injected,
            recommended_record_sha256=intake.golden_record_sha256(injected),
        ),
        *request.decisions[1:],
    )
    tampered_request = replace(request, decisions=replaced)

    result = intake._materialize_synthetic_test_profile(
        records,
        request=tampered_request,
        receipt=receipt,
        authority=AUTHORITY,
        now=NOW,
    )

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("REVIEW_DECISIONS_HASH_MISMATCH",)
    assert result.records == ()


def test_unverified_changed_or_non_sixty_input_cannot_materialize() -> None:
    records, request, receipt = _verified_materialization_input()
    changed_decisions = (
        replace(request.decisions[0], reason="changed after receipt"),
        *request.decisions[1:],
    )
    changed_request = replace(
        request,
        decisions=changed_decisions,
        decisions_sha256=intake.review_decisions_sha256(changed_decisions),
    )
    cases = (
        (records, request, None, "HUMAN_VERIFICATION_REQUIRED"),
        (
            records,
            changed_request,
            receipt,
            "HUMAN_RECEIPT_BINDING_MISMATCH",
        ),
        (records[:-1], request, receipt, "V1_RECORD_SET_INVALID"),
    )

    for candidate_records, candidate_request, candidate_receipt, reason in cases:
        result = intake._materialize_synthetic_test_profile(
            candidate_records,
            request=candidate_request,
            receipt=candidate_receipt,
            authority=AUTHORITY,
            now=NOW,
        )
        assert result.status == "BLOCKED"
        assert result.reason_codes == (reason,)
        assert result.records == ()
