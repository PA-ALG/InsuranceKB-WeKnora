from __future__ import annotations

import copy
import hashlib
import inspect
import json
import pickle
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest

import insurance_harness.goldenset.expert_golden_admission_596_2 as admission_119
import insurance_harness.goldenset.schema67_semantic_comparator_596_2 as comparator_119
import insurance_harness.knowledge_compiler.deepseek_locator_extractor_596_1 as deepseek_119
from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.evidence_verifier import (
    ApprovedLocatorSetV1,
    EvidenceLocatorSnapshotV1,
    FieldVerificationV1,
    FreeformEvidenceBindingReceiptV1,
    FreeformEvidenceV1,
    FreeformFieldOutputV1,
    RepairResolutionV1,
    TargetedRepairPlanV1,
    VerificationBatchV1,
    bind_freeform_arm_evidence,
)
from insurance_harness.compiler.material_profiles import (
    ApprovedParsePolicy,
    MaterialProfile,
    SourceDocumentIdentity,
)
from insurance_harness.compiler.parsed_documents import (
    BlockLocatorV1,
    PageLocatorV1,
    ParseAttemptV1,
    ParseBlockV1,
    ParsedDocumentV1,
    ParseManifestV1,
    ParseOutputFactsV1,
    ParsePageV1,
    ParserIdentityV1,
    ParseSnapshotV1,
    ParseSubjectV1,
    build_parse_manifest,
)
from insurance_harness.goldenset.expert_golden_admission_596_2 import (
    CANDIDATE_SHA256,
    EXPERT_APPROVAL_PROVENANCE,
    EXPERT_DISPLAY_NAME,
    EXPLICIT_ABSENCE_FIELD_ID,
    FIXED_UNKNOWN_FIELD_IDS,
    FIXED_UNKNOWN_FIELD_IDS_SHA256,
    ORDERED_FIELD_IDS,
    ORDERED_FIELD_IDS_SHA256,
    REFERENCE_BUNDLE_SNAPSHOT_SHA256,
    REFERENCE_EVIDENCE_FRAGMENT_COUNT,
    SCHEMA_SHA256,
    WORKBOOK_SHA256,
    EvidenceReplayCaseV1,
    NamedExpertApprovalReceiptV1,
    candidate_evidence_bundle_sha256,
    evaluate_expert_golden_admission,
    expert_approval_receipt_sha256,
    expert_approval_subject_sha256,
    make_total_control_named_expert_approval_receipt,
)
from insurance_harness.knowledge_compiler.deepseek_locator_extractor_596_1 import (
    DEEPSEEK_EXECUTION_IDENTITY_SHA256,
    DEEPSEEK_MODEL_IDENTITY,
    LOCATOR_SELECTION_POLICY_SHA256,
    DeepSeekExecutionReceiptV1,
    DeepSeekTaskExecutionV1,
    Schema67BatchBudgetV1,
    Schema67BatchExecutionReceiptV1,
    Schema67BatchExecutionV1,
    Schema67BoundAttemptV1,
    Schema67ExecutionPlanV1,
    Schema67PreparedTaskV1,
    Schema67RoleTaskInputV1,
    build_schema67_batch_receipt,
    build_schema67_execution_plan,
    prepare_schema67_deepseek_tasks,
)
from insurance_harness.knowledge_compiler.schema_first_contracts import (
    APPROVED_BY,
    APPROVED_PRODUCT_VERSION_ID,
    APPROVED_REVIEW_PACKAGE_ID,
    APPROVED_SCHEMA_ID,
    APPROVED_WORKBOOK_SHA256,
    ApprovedSchemaSnapshotV1,
    FieldContractSetV1,
    approved_schema_rows,
    approved_schema_snapshot_sha256,
    compile_schema_contracts,
    schema_rows_sha256,
)
from tests.test_deepseek_locator_extractor_119 import (
    _schema67_role_inputs as _real_schema67_role_inputs,
)
from tests.test_fixture_candidate_human_batch_059 import (
    _receipt_chain as _verification_receipt_chain,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _ForgedSnapshot:
    workbook_sha256: str = WORKBOOK_SHA256
    schema_sha256: str = SCHEMA_SHA256
    ordered_field_ids: tuple[str, ...] = ORDERED_FIELD_IDS
    ordered_field_ids_sha256: str = ORDERED_FIELD_IDS_SHA256
    candidate_sha256: str = CANDIDATE_SHA256


def _approved_a_snapshot() -> ApprovedSchemaSnapshotV1:
    fields = approved_schema_rows()
    schema_sha256 = schema_rows_sha256(fields)
    snapshot_sha256 = approved_schema_snapshot_sha256(
        product_version_id=APPROVED_PRODUCT_VERSION_ID,
        review_package_id=APPROVED_REVIEW_PACKAGE_ID,
        schema_id=APPROVED_SCHEMA_ID,
        workbook_sha256=APPROVED_WORKBOOK_SHA256,
        approval_status="EXPERT_APPROVED_NO_CHANGES",
        approved_by=APPROVED_BY,
        authority_ref="user-message:019fda9b-schema67-approved-no-changes",
        schema_rows_sha256_value=schema_sha256,
        ordered_field_ids_sha256_value=ORDERED_FIELD_IDS_SHA256,
    )
    return ApprovedSchemaSnapshotV1(
        product_version_id=APPROVED_PRODUCT_VERSION_ID,
        review_package_id=APPROVED_REVIEW_PACKAGE_ID,
        schema_id=APPROVED_SCHEMA_ID,
        workbook_sha256=APPROVED_WORKBOOK_SHA256,
        approval_status="EXPERT_APPROVED_NO_CHANGES",
        approved_by=APPROVED_BY,
        authority_ref="user-message:019fda9b-schema67-approved-no-changes",
        fields=fields,
        schema_rows_sha256=schema_sha256,
        ordered_field_ids_sha256=ORDERED_FIELD_IDS_SHA256,
        snapshot_sha256=snapshot_sha256,
    )


def _authority_snapshot() -> admission_119.TotalControlSchema67AuthoritySnapshotV1:
    return admission_119.make_total_control_schema67_authority_snapshot(
        approved_schema_snapshot=_approved_a_snapshot()
    )


def test_total_control_factory_maps_exact_a_snapshot_without_candidate_reinjection() -> None:
    approved = _approved_a_snapshot()

    result = admission_119.make_total_control_schema67_authority_snapshot(
        approved_schema_snapshot=approved
    )

    assert type(result) is admission_119.TotalControlSchema67AuthoritySnapshotV1
    assert result.workbook_sha256 == WORKBOOK_SHA256
    assert result.schema_sha256 == SCHEMA_SHA256
    assert result.ordered_field_ids == ORDERED_FIELD_IDS
    assert result.ordered_field_ids_sha256 == ORDERED_FIELD_IDS_SHA256
    assert result.candidate_sha256 == CANDIDATE_SHA256
    assert result.approved_schema_snapshot_sha256 == approved.snapshot_sha256
    assert result.approved_schema_rows_sha256 == approved.schema_rows_sha256
    assert len(result.authority_snapshot_sha256) == 64
    assert not hasattr(approved, "candidate_sha256")


def test_total_control_factory_rejects_exact_a_authority_drift() -> None:
    approved = _approved_a_snapshot()
    drifted = (
        approved.model_copy(update={"workbook_sha256": "0" * 64}),
        approved.model_copy(update={"schema_rows_sha256": "1" * 64}),
        approved.model_copy(update={"fields": tuple(reversed(approved.fields))}),
        approved.model_copy(update={"authority_ref": "user-message:foreign-authority"}),
    )

    for item in drifted:
        with pytest.raises(admission_119.Schema67AuthoritySnapshotError) as caught:
            admission_119.make_total_control_schema67_authority_snapshot(
                approved_schema_snapshot=item
            )
        assert caught.value.reason_code == "SCHEMA67_A_AUTHORITY_INVALID"


def test_total_control_factory_rejects_structural_protocol_substitute() -> None:
    with pytest.raises(admission_119.Schema67AuthoritySnapshotError) as caught:
        admission_119.make_total_control_schema67_authority_snapshot(
            approved_schema_snapshot=_ForgedSnapshot()
        )

    assert caught.value.reason_code == "SCHEMA67_A_AUTHORITY_INVALID"


def _document() -> tuple[ParsedDocumentV1, ParseManifestV1, tuple[str, ...]]:
    block_texts = ("本合同为不保证续保合同。", "已核验片段二", "已核验片段三")
    source_sha256 = "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"
    profile_id = "profile-schema67-terms"
    document = ParsedDocumentV1(
        contract="parsed-document.v1",
        subject=ParseSubjectV1(
            space_id="space-119",
            source_id="source-terms",
            source_revision_id="revision-119",
            product_version_id="596-1",
            material_profile_id=profile_id,
            material_profile_binding_hash="b" * 64,
            source_sha256=source_sha256,
            raw_artifact_hash="c" * 64,
            canonical_envelope_hash="d" * 64,
        ),
        parser=ParserIdentityV1(
            parser_id="mineru-canonical",
            parser_profile_ref="approved-parser-profile:parser-neutral-mineru.v1",
            parser_build_id="build-119",
            parser_config_hash="e" * 64,
        ),
        attempt=ParseAttemptV1(
            attempt_id="attempt-119",
            attempt_number=1,
            attempt_role="default",
            generation=1,
        ),
        snapshot=ParseSnapshotV1(
            snapshot_id="snapshot-119",
            snapshot_generation=1,
            pagination_complete=True,
            concurrent_mutation_fence_hash="f" * 64,
        ),
        output_facts=ParseOutputFactsV1(
            privacy_policy_ref="privacy-policy:internal.v1",
            output_policy_ref="output-policy:internal.v1",
            body_text_included=False,
            secrets_included=False,
            absolute_paths_included=False,
            unknown_vendor_fields_included=False,
        ),
        pages=(
            ParsePageV1(
                page_id="page-1",
                order_index=0,
                locator=PageLocatorV1(page_number=1),
                content_hash=_sha("page"),
                structure_hash="1" * 64,
            ),
        ),
        blocks=tuple(
            ParseBlockV1(
                block_id=f"block-{index}",
                order_index=index - 1,
                locator=BlockLocatorV1(
                    page_number=1,
                    block_index=index - 1,
                    bbox=(
                        Decimal(index - 1),
                        Decimal(0),
                        Decimal(index),
                        Decimal(1),
                    ),
                ),
                content_hash=_sha(text),
                structure_hash=str(index + 1) * 64,
            )
            for index, text in enumerate(block_texts, start=1)
        ),
        tables=(),
        cells=(),
        capability_evidence=(),
        warnings=(),
        unsupported=(),
    )
    profile = MaterialProfile(
        profile_id=profile_id,
        material_role="terms",
        source=SourceDocumentIdentity(
            name="terms.pdf",
            path="dataset/terms.pdf",
            size=1,
            sha256=source_sha256,
        ),
        document_type_id="insurance-terms",
        required_parse_capabilities=("ordered_pages",),
        parse_policy=ApprovedParsePolicy(
            policy_id="policy-119",
            policy_version="v1",
            material_profile_id=profile_id,
            default_parser_profile_ref=("approved-parser-profile:parser-neutral-mineru.v1"),
            bounded_upgrade_profile_ref=None,
            upgrade_trigger_conditions=(),
            max_parser_attempts=1,
            privacy_policy_ref="privacy-policy:internal.v1",
            output_policy_ref="output-policy:internal.v1",
        ),
    )
    return document, build_parse_manifest(document, profile), block_texts


def _approved_cases() -> tuple[EvidenceReplayCaseV1, ...]:
    document, manifest, block_texts = _document()
    known_fields = tuple(
        field for field in ORDERED_FIELD_IDS if field not in FIXED_UNKNOWN_FIELD_IDS
    )
    case_counts = {field_id: 3 if index < 19 else 2 for index, field_id in enumerate(known_fields)}
    assert sum(case_counts.values()) == REFERENCE_EVIDENCE_FRAGMENT_COUNT

    cases: list[EvidenceReplayCaseV1] = []
    for field_id in known_fields:
        value_snapshot = f"approved-value:{field_id}"
        for case_index in range(case_counts[field_id]):
            block_index = case_index + 1
            quote = block_texts[case_index]
            case_id = f"{field_id}:{case_index + 1:03d}"
            evidence = FreeformEvidenceV1(
                field_id=field_id,
                source_sha256=document.subject.source_sha256,
                source_revision_id=document.subject.source_revision_id,
                parse_attempt_id=document.attempt.attempt_id,
                parsed_document_hash=document.document_hash,
                parse_manifest_hash=manifest.manifest_hash,
                page_number=1,
                block_id=f"block-{block_index}",
                locator=EvidenceLocatorSnapshotV1(
                    subject_type="block",
                    subject_ref=f"block-{block_index}",
                    page_number=1,
                    parent_refs=("page-1",),
                    content_snapshot=quote,
                    content_snapshot_sha256=_sha(quote),
                ),
                quote_snapshot=quote,
                quote_snapshot_sha256=_sha(quote),
            )
            cases.append(
                EvidenceReplayCaseV1(
                    case_id=case_id,
                    field_output=FreeformFieldOutputV1(
                        product_version_id="596-1",
                        field_id=field_id,
                        state=(
                            "absent_explicitly"
                            if field_id == EXPLICIT_ABSENCE_FIELD_ID
                            else "present"
                        ),
                        value_snapshot=value_snapshot,
                        evidence=(evidence,),
                    ),
                    documents=(document,),
                    manifests=(manifest,),
                )
            )
    return tuple(sorted(cases, key=lambda item: item.case_id))


def _candidate_fields(
    cases: tuple[EvidenceReplayCaseV1, ...],
) -> tuple[FreeformFieldOutputV1, ...]:
    fields: list[FreeformFieldOutputV1] = []
    for field_id in ORDERED_FIELD_IDS:
        matching = tuple(
            case.field_output for case in cases if case.field_output.field_id == field_id
        )
        if not matching:
            fields.append(
                FreeformFieldOutputV1(
                    product_version_id="596-1",
                    field_id=field_id,
                    state="unknown",
                    value_snapshot=None,
                    evidence=(),
                )
            )
            continue
        fields.append(
            matching[0].model_copy(
                update={
                    "evidence": tuple(
                        evidence for output in matching for evidence in output.evidence
                    )
                }
            )
        )
    return tuple(fields)


NOW = datetime(2026, 8, 7, 12, tzinfo=UTC)


def _rehash_receipt(
    receipt: NamedExpertApprovalReceiptV1,
) -> NamedExpertApprovalReceiptV1:
    unbound = replace(receipt, subject_sha256="", receipt_sha256="")
    bound = replace(
        unbound,
        subject_sha256=expert_approval_subject_sha256(unbound),
    )
    return replace(bound, receipt_sha256=expert_approval_receipt_sha256(bound))


def _receipt(
    *,
    approved_by: str = EXPERT_DISPLAY_NAME,
) -> NamedExpertApprovalReceiptV1:
    receipt = make_total_control_named_expert_approval_receipt()
    if approved_by == EXPERT_DISPLAY_NAME:
        return receipt
    return _rehash_receipt(replace(receipt, approved_by=approved_by))


def test_only_one_preapproved_linyao_receipt_window_is_valid() -> None:
    approved = make_total_control_named_expert_approval_receipt()
    alternate = _rehash_receipt(
        replace(
            approved,
            issued_at=approved.issued_at + timedelta(minutes=1),
            expires_at=approved.expires_at + timedelta(minutes=1),
        )
    )

    assert (
        admission_119.validate_total_control_named_expert_approval_receipt(
            receipt=approved,
            observed_at=NOW,
        )
        is approved
    )
    with pytest.raises(
        admission_119.Schema67AuthoritySnapshotError,
        match="EXPERT_RECEIPT_IDENTITY_MISMATCH",
    ):
        admission_119.validate_total_control_named_expert_approval_receipt(
            receipt=alternate,
            observed_at=NOW,
        )


def test_semantic_comparator_receipt_must_join_exact_base_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = _approved_cases()
    fields = _candidate_fields(cases)
    receipt_a = _receipt()
    receipt_b = _rehash_receipt(
        replace(
            receipt_a,
            issued_at=receipt_a.issued_at + timedelta(minutes=1),
            expires_at=receipt_a.expires_at + timedelta(minutes=1),
        )
    )
    base = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=fields,
        evidence_cases=cases,
        receipt=receipt_a,
        observed_at=NOW,
    )
    mismatched_base = base.model_copy(update={"reference_receipt_sha256": receipt_b.receipt_sha256})
    monkeypatch.setattr(
        admission_119,
        "evaluate_expert_golden_admission",
        lambda **_kwargs: mismatched_base,
    )

    result = admission_119.evaluate_schema67_semantic_gate(
        snapshot=_authority_snapshot(),
        candidate_fields=fields,
        evidence_cases=cases,
        receipt=receipt_a,
        observed_at=NOW,
        frozen_candidate_bundle_sha256=candidate_evidence_bundle_sha256(fields, cases),
        comparator=_approved_comparator(),
    )

    assert result.reason_codes == ("SEMANTIC_COMPARATOR_AUTHORITY_INVALID",)
    assert result.field_evaluations == ()
    assert result.wiki_admission_allowed is False
    assert result.publishable_field_ids == ()


def test_evidence_pass_does_not_override_missing_expert_receipt() -> None:
    cases = _approved_cases()

    result = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=_candidate_fields(cases),
        evidence_cases=cases,
        receipt=None,
        observed_at=None,
    )

    assert result.status == "PENDING_EXPERT_RECEIPT"
    assert result.reference_content_authority == "PENDING_RECEIPT"
    assert result.evidence_replay == "PASS"
    assert result.evidence_fragments_total == 111
    assert result.evidence_fragments_passed == 111
    assert result.evidence_fragments_failed == 0
    assert result.semantic_eval_allowed is False
    assert result.wiki_admission_allowed is False
    assert result.publishable_field_ids == ()


def test_exact_linyao_receipt_and_live_evidence_replay_allow_offline_eval() -> None:
    cases = _approved_cases()
    receipt = _receipt()

    result = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=_candidate_fields(cases),
        evidence_cases=cases,
        receipt=receipt,
        observed_at=NOW,
    )

    assert result.status == "READY_FOR_OFFLINE_GOLDEN_EVAL"
    assert result.reference_content_authority == "VERIFIED"
    assert result.evidence_replay == "PASS"
    assert result.semantic_eval_allowed is True
    assert result.wiki_admission_allowed is False
    assert result.reference_subject_sha256 == receipt.subject_sha256
    assert result.reference_receipt_sha256 == receipt.receipt_sha256
    assert result.reference_bundle_sha256 == REFERENCE_BUNDLE_SNAPSHOT_SHA256
    assert result.candidate_bundle_sha256 == candidate_evidence_bundle_sha256(
        _candidate_fields(cases), cases
    )
    assert result.publishable_field_ids == ()
    assert result.effective_unknown_field_ids == tuple(
        field_id for field_id in ORDERED_FIELD_IDS if field_id in FIXED_UNKNOWN_FIELD_IDS
    )


def test_foreign_approver_cannot_reuse_linyao_authority() -> None:
    cases = _approved_cases()
    receipt = _receipt(approved_by="someone-else")

    result = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=_candidate_fields(cases),
        evidence_cases=cases,
        receipt=receipt,
        observed_at=NOW,
    )

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("EXPERT_RECEIPT_AUTHORITY_INVALID",)
    assert result.semantic_eval_allowed is False
    assert result.wiki_admission_allowed is False
    assert result.publishable_field_ids == ()


def test_stale_or_tampered_receipt_never_opens_golden_gate() -> None:
    cases = _approved_cases()
    receipt = _receipt()

    stale = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=_candidate_fields(cases),
        evidence_cases=cases,
        receipt=receipt,
        observed_at=receipt.expires_at,
    )
    tampered = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=_candidate_fields(cases),
        evidence_cases=cases,
        receipt=replace(receipt, candidate_sha256="9" * 64),
        observed_at=NOW,
    )
    hash_tampered = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=_candidate_fields(cases),
        evidence_cases=cases,
        receipt=replace(receipt, receipt_sha256="8" * 64),
        observed_at=NOW,
    )
    provenance_tampered = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=_candidate_fields(cases),
        evidence_cases=cases,
        receipt=_rehash_receipt(
            replace(
                receipt,
                provenance=replace(
                    EXPERT_APPROVAL_PROVENANCE,
                    user_approval_ref="foreign-user-approval",
                ),
            )
        ),
        observed_at=NOW,
    )

    assert stale.reason_codes == ("EXPERT_RECEIPT_STALE",)
    assert tampered.reason_codes == ("EXPERT_RECEIPT_BINDING_MISMATCH",)
    assert hash_tampered.reason_codes == ("EXPERT_RECEIPT_HASH_MISMATCH",)
    assert provenance_tampered.reason_codes == ("EXPERT_RECEIPT_AUTHORITY_INVALID",)
    assert stale.semantic_eval_allowed is False
    assert stale.wiki_admission_allowed is False
    assert tampered.semantic_eval_allowed is False
    assert tampered.wiki_admission_allowed is False
    assert hash_tampered.semantic_eval_allowed is False
    assert hash_tampered.wiki_admission_allowed is False
    assert provenance_tampered.semantic_eval_allowed is False
    assert provenance_tampered.wiki_admission_allowed is False


def test_failed_live_evidence_is_downgraded_to_unknown_review_item() -> None:
    cases = _approved_cases()
    original = cases[0]
    evidence = original.field_output.evidence[0]
    rejected_quote = "不属于已绑定解析快照"
    locator = evidence.locator.model_copy(
        update={
            "content_snapshot": rejected_quote,
            "content_snapshot_sha256": _sha(rejected_quote),
        }
    )
    rejected_evidence = evidence.model_copy(
        update={
            "locator": locator,
            "quote_snapshot": rejected_quote,
            "quote_snapshot_sha256": _sha(rejected_quote),
        }
    )
    rejected_output = original.field_output.model_copy(update={"evidence": (rejected_evidence,)})
    rejected_case = original.model_copy(update={"field_output": rejected_output})
    replay_cases = (rejected_case, *cases[1:])
    receipt = _receipt()

    result = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=_candidate_fields(replay_cases),
        evidence_cases=replay_cases,
        receipt=receipt,
        observed_at=NOW,
    )

    assert result.status == "REFERENCE_APPROVED_CANDIDATE_EVIDENCE_BLOCKED"
    assert result.reference_content_authority == "VERIFIED"
    assert result.evidence_replay == "BLOCKED"
    assert result.evidence_fragments_passed == 110
    assert result.evidence_fragments_failed == 1
    assert original.field_output.field_id in result.effective_unknown_field_ids
    assert original.field_output.field_id not in result.publishable_field_ids
    assert result.review_items[0].case_id == original.case_id
    assert result.semantic_eval_allowed is True
    assert result.wiki_admission_allowed is False


def test_fixed_unknown_field_cannot_carry_value_or_evidence_case() -> None:
    cases = _approved_cases()
    original = cases[0]
    unknown_field = FIXED_UNKNOWN_FIELD_IDS[0]
    injected_output = original.field_output.model_copy(update={"field_id": unknown_field})
    injected = original.model_copy(update={"field_output": injected_output})
    invalid_cases = (injected, *cases[1:])
    result = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=_candidate_fields(invalid_cases),
        evidence_cases=invalid_cases,
        receipt=None,
        observed_at=None,
    )

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("CANDIDATE_DEFERRED_FIELD_INVALID",)
    assert result.evidence_fragments_total == 0


def test_caller_supplied_all_true_checklist_seam_no_longer_exists() -> None:
    cases = _approved_cases()
    assert not hasattr(admission_119, "SemanticChecklistItemV1")
    assert not hasattr(admission_119, "SemanticChecklistV1")
    snapshot_drift = evaluate_expert_golden_admission(
        snapshot=_ForgedSnapshot(),
        candidate_fields=_candidate_fields(cases),
        evidence_cases=cases,
        receipt=None,
        observed_at=None,
    )

    assert snapshot_drift.reason_codes == ("SCHEMA67_SNAPSHOT_IDENTITY_INVALID",)
    assert snapshot_drift.evidence_fragments_total == 0


def test_workbook_frozen_unknown_partition_is_exact_and_independent() -> None:
    assert len(FIXED_UNKNOWN_FIELD_IDS) == 21
    assert len(set(FIXED_UNKNOWN_FIELD_IDS)) == 21
    assert FIXED_UNKNOWN_FIELD_IDS_SHA256 == (
        "419b8dc4b37db18dccdfca95aace39ce17046c8f6809cdc87f1bd7f8e598e9b5"
    )
    assert _sha("\n".join(FIXED_UNKNOWN_FIELD_IDS) + "\n") == (FIXED_UNKNOWN_FIELD_IDS_SHA256)
    assert EXPLICIT_ABSENCE_FIELD_ID not in FIXED_UNKNOWN_FIELD_IDS


def test_only_guaranteed_renewal_period_may_be_explicitly_absent() -> None:
    cases = _approved_cases()
    present_index = next(
        index for index, case in enumerate(cases) if case.field_output.state == "present"
    )
    original = cases[present_index]
    invalid_output = original.field_output.model_copy(update={"state": "absent_explicitly"})
    invalid_cases = list(cases)
    invalid_cases[present_index] = original.model_copy(update={"field_output": invalid_output})

    result = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=_candidate_fields(tuple(invalid_cases)),
        evidence_cases=tuple(invalid_cases),
        receipt=None,
        observed_at=None,
    )

    assert result.reason_codes == ("CANDIDATE_FIELD_STATE_INVALID",)
    assert result.evidence_fragments_total == 0


def test_explicit_absence_requires_the_approved_negative_evidence_quote() -> None:
    cases = _approved_cases()
    absent_indexes = tuple(
        index
        for index, case in enumerate(cases)
        if case.field_output.field_id == EXPLICIT_ABSENCE_FIELD_ID
    )
    assert absent_indexes
    invalid_cases = list(cases)
    for index in absent_indexes:
        original = cases[index]
        evidence = original.field_output.evidence[0]
        replacement_quote = "已核验片段二"
        locator = evidence.locator.model_copy(
            update={
                "subject_ref": "block-2",
                "content_snapshot": replacement_quote,
                "content_snapshot_sha256": _sha(replacement_quote),
            }
        )
        replacement = evidence.model_copy(
            update={
                "block_id": "block-2",
                "locator": locator,
                "quote_snapshot": replacement_quote,
                "quote_snapshot_sha256": _sha(replacement_quote),
            }
        )
        invalid_cases[index] = original.model_copy(
            update={
                "field_output": original.field_output.model_copy(
                    update={"evidence": (replacement,)}
                )
            }
        )

    result = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=_candidate_fields(tuple(invalid_cases)),
        evidence_cases=tuple(invalid_cases),
        receipt=None,
        observed_at=None,
    )

    assert result.reason_codes == ("CANDIDATE_EXPLICIT_ABSENCE_NOT_PROVEN",)
    assert result.evidence_fragments_total == 0


def test_same_field_state_and_value_must_be_identical_across_cases() -> None:
    cases = _approved_cases()
    original = cases[1]
    assert original.field_output.field_id == cases[0].field_output.field_id
    drifted_output = original.field_output.model_copy(
        update={"value_snapshot": "drifted-approved-value"}
    )
    drifted_cases = list(cases)
    drifted_cases[1] = original.model_copy(update={"field_output": drifted_output})

    result = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=_candidate_fields(tuple(drifted_cases)),
        evidence_cases=tuple(drifted_cases),
        receipt=None,
        observed_at=None,
    )

    assert result.reason_codes == ("EVIDENCE_CASE_BINDING_INVALID",)
    assert result.evidence_fragments_total == 0


def test_candidate_fragment_count_may_vary_but_case_ids_remain_unique() -> None:
    cases = _approved_cases()
    reduced = tuple(
        next(case for case in cases if case.field_output.field_id == field_id)
        for field_id in ORDERED_FIELD_IDS
        if field_id not in FIXED_UNKNOWN_FIELD_IDS
    )
    partial = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=_candidate_fields(reduced),
        evidence_cases=reduced,
        receipt=_receipt(),
        observed_at=NOW,
    )
    duplicate_id = list(cases)
    duplicate_id[-1] = duplicate_id[-1].model_copy(update={"case_id": cases[0].case_id})
    duplicate = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=_candidate_fields(tuple(duplicate_id)),
        evidence_cases=tuple(duplicate_id),
        receipt=None,
        observed_at=None,
    )

    assert partial.status == "READY_FOR_OFFLINE_GOLDEN_EVAL"
    assert partial.evidence_fragments_total == 46
    assert partial.evidence_fragments_passed == 46
    assert duplicate.reason_codes == ("EVIDENCE_REPLAY_MEMBERSHIP_INVALID",)
    assert duplicate.evidence_fragments_total == 0


def test_candidate_field_snapshot_must_remain_exact67_and_ordered() -> None:
    cases = _approved_cases()
    candidate_fields = _candidate_fields(cases)

    result = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=candidate_fields[1:],
        evidence_cases=cases,
        receipt=None,
        observed_at=None,
    )

    assert result.reason_codes == ("CANDIDATE_FIELD_MEMBERSHIP_INVALID",)
    assert result.evidence_fragments_total == 0


def test_arbitrary_model_evidence_cannot_mint_linyao_reference_receipt() -> None:
    parameters = inspect.signature(make_total_control_named_expert_approval_receipt).parameters

    assert "evidence_cases" not in parameters
    assert "candidate_fields" not in parameters


def test_model_value_change_does_not_rebind_reference_approval_to_candidate() -> None:
    cases = _approved_cases()
    receipt = _receipt()
    changed_field_id = cases[0].field_output.field_id
    changed_cases = tuple(
        case.model_copy(
            update={
                "field_output": case.field_output.model_copy(
                    update={"value_snapshot": "new-model-value"}
                )
            }
        )
        if case.field_output.field_id == changed_field_id
        else case
        for case in cases
    )

    result = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=_candidate_fields(changed_cases),
        evidence_cases=changed_cases,
        receipt=receipt,
        observed_at=NOW,
    )

    assert result.reference_content_authority == "VERIFIED"
    assert result.semantic_eval_allowed is True
    assert "EXPERT_CONTENT_APPROVED" not in result.status
    assert not hasattr(result, "expert_content_authority")
    assert result.reference_bundle_sha256 == receipt.reference_bundle_sha256
    assert result.candidate_bundle_sha256 != result.reference_bundle_sha256


def test_non_reference_candidate_field_may_remain_unknown_without_evidence() -> None:
    cases = _approved_cases()
    deferred_field = next(
        field_id
        for field_id in ORDERED_FIELD_IDS
        if field_id not in FIXED_UNKNOWN_FIELD_IDS and field_id != EXPLICIT_ABSENCE_FIELD_ID
    )
    reduced = tuple(case for case in cases if case.field_output.field_id != deferred_field)

    result = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=_candidate_fields(reduced),
        evidence_cases=reduced,
        receipt=_receipt(),
        observed_at=NOW,
    )

    assert result.status == "READY_FOR_OFFLINE_GOLDEN_EVAL"
    assert result.semantic_eval_allowed is True
    assert result.wiki_admission_allowed is False
    assert deferred_field in result.effective_unknown_field_ids
    assert deferred_field not in result.publishable_field_ids


def test_explicit_absence_field_may_safely_abstain_as_unknown() -> None:
    cases = _approved_cases()
    reduced = tuple(
        case for case in cases if case.field_output.field_id != EXPLICIT_ABSENCE_FIELD_ID
    )

    result = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=_candidate_fields(reduced),
        evidence_cases=reduced,
        receipt=_receipt(),
        observed_at=NOW,
    )

    assert result.status == "READY_FOR_OFFLINE_GOLDEN_EVAL"
    assert result.semantic_eval_allowed is True
    assert result.wiki_admission_allowed is False
    assert EXPLICIT_ABSENCE_FIELD_ID in result.effective_unknown_field_ids
    assert EXPLICIT_ABSENCE_FIELD_ID not in result.publishable_field_ids


def test_invalid_candidate_does_not_invalidate_reference_receipt_authority() -> None:
    cases = _approved_cases()

    result = evaluate_expert_golden_admission(
        snapshot=_authority_snapshot(),
        candidate_fields=_candidate_fields(cases)[1:],
        evidence_cases=cases,
        receipt=_receipt(),
        observed_at=NOW,
    )

    assert result.reason_codes == ("CANDIDATE_FIELD_MEMBERSHIP_INVALID",)
    assert result.reference_content_authority == "VERIFIED"
    assert result.semantic_eval_allowed is False
    assert result.wiki_admission_allowed is False


def test_schema67_semantic_double_axis_gate_is_public() -> None:
    assert hasattr(admission_119, "SemanticComparatorAuthorityV1")
    assert hasattr(admission_119, "SemanticAuthorityComparisonV1")
    assert hasattr(admission_119, "Schema67SemanticEvaluationResultV1")
    assert hasattr(admission_119, "evaluate_schema67_semantic_gate")


def _semantic_authority(
    *, authority_sha256: str | None = None
) -> admission_119.SemanticComparatorAuthorityV1:
    unsigned = admission_119.SemanticComparatorAuthorityV1(
        contract_id="schema67-semantic-comparator-authority.v1",
        authority_id="total-control:linyao-schema67-semantic-comparator",
        comparator_version="schema67-explicit-authority.v1",
        workbook_sha256=WORKBOOK_SHA256,
        schema_sha256=SCHEMA_SHA256,
        ordered_field_ids_sha256=ORDERED_FIELD_IDS_SHA256,
        approved_candidate_sha256=CANDIDATE_SHA256,
        reference_bundle_sha256=REFERENCE_BUNDLE_SNAPSHOT_SHA256,
        reference_fields_authority_sha256="f" * 64,
        expert_subject_sha256=_receipt().subject_sha256,
        expert_receipt_sha256=_receipt().receipt_sha256,
        authority_sha256="0" * 64,
    )
    return unsigned.model_copy(
        update={
            "authority_sha256": (
                authority_sha256
                if authority_sha256 is not None
                else admission_119.semantic_comparator_authority_sha256(unsigned)
            )
        }
    )


class _AuthorityComparator:
    def __init__(
        self,
        *,
        authority: admission_119.SemanticComparatorAuthorityV1 | None = None,
        outcomes: dict[str, admission_119.SemanticComparisonOutcome] | None = None,
        reference_states: dict[str, admission_119.TriState] | None = None,
        required_sources: dict[str, tuple[str, ...]] | None = None,
        corrupt_field: str | None = None,
    ) -> None:
        self.authority = authority or _semantic_authority()
        self.outcomes = outcomes or {}
        self.reference_states = reference_states or {}
        self.required_sources = required_sources or {}
        self.corrupt_field = corrupt_field
        self.calls: list[tuple[str, str, str | None, str]] = []

    def compare(
        self,
        *,
        field_id: str,
        candidate_state: admission_119.TriState,
        candidate_value_sha256: str | None,
        candidate_bundle_sha256: str,
    ) -> admission_119.SemanticAuthorityComparisonV1:
        self.calls.append(
            (
                field_id,
                candidate_state,
                candidate_value_sha256,
                candidate_bundle_sha256,
            )
        )
        reference_state = self.reference_states.get(field_id, candidate_state)
        unsigned = admission_119.SemanticAuthorityComparisonV1(
            contract_id="schema67-semantic-authority-comparison.v1",
            field_id=field_id,
            candidate_bundle_sha256=candidate_bundle_sha256,
            candidate_state=candidate_state,
            candidate_value_sha256=candidate_value_sha256,
            reference_state=reference_state,
            reference_value_sha256=(
                None if reference_state == "unknown" else _sha(f"approved-reference:{field_id}")
            ),
            required_evidence_source_sha256s=self.required_sources.get(
                field_id,
                ("88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",),
            ),
            semantic_outcome=self.outcomes.get(field_id, "EQUIVALENT"),
            comparator_authority_sha256=self.authority.authority_sha256,
            comparison_sha256="0" * 64,
        )
        return unsigned.model_copy(
            update={
                "comparison_sha256": (
                    "f" * 64
                    if field_id == self.corrupt_field
                    else admission_119.semantic_authority_comparison_sha256(unsigned)
                )
            }
        )


def _approved_comparator() -> comparator_119.DeterministicSchema67SemanticComparator:
    reference = comparator_119.load_total_control_approved_schema67_reference(
        receipt=_receipt(),
        observed_at=NOW,
    )
    return comparator_119.make_deterministic_schema67_semantic_comparator(reference=reference)


def _evaluate_semantic(
    comparator: object,
    *,
    cases: tuple[EvidenceReplayCaseV1, ...] | None = None,
    frozen_candidate_bundle_sha256: str | None = None,
) -> admission_119.Schema67SemanticEvaluationResultV1:
    exact_cases = _approved_cases() if cases is None else cases
    candidate_fields = _candidate_fields(exact_cases)
    return admission_119.evaluate_schema67_semantic_gate(
        snapshot=_authority_snapshot(),
        candidate_fields=candidate_fields,
        evidence_cases=exact_cases,
        receipt=_receipt(),
        observed_at=NOW,
        frozen_candidate_bundle_sha256=(
            candidate_evidence_bundle_sha256(candidate_fields, exact_cases)
            if frozen_candidate_bundle_sha256 is None
            else frozen_candidate_bundle_sha256
        ),
        comparator=comparator,
    )


@dataclass(frozen=True, slots=True)
class _CandidateV2Fixture:
    contract: str
    product_version_id: str
    ordered_field_ids: tuple[str, ...]
    candidate_tree_sha1: str
    model_identity_sha256: str
    source_roles: tuple[dict[str, str], ...]
    fields: tuple[FreeformFieldOutputV1, ...]
    evidence_receipts: tuple[FreeformEvidenceBindingReceiptV1, ...]
    batch_receipt: Schema67BatchExecutionReceiptV1
    accepted_task_executions: tuple[DeepSeekTaskExecutionV1, ...]
    candidate_sha256: str

    def model_dump(
        self,
        *,
        mode: str = "python",
        exclude: set[str] | None = None,
        round_trip: bool = False,
    ) -> dict[str, object]:
        del mode, round_trip
        payload: dict[str, object] = {
            "contract": self.contract,
            "product_version_id": self.product_version_id,
            "ordered_field_ids": self.ordered_field_ids,
            "candidate_tree_sha1": self.candidate_tree_sha1,
            "model_identity_sha256": self.model_identity_sha256,
            "source_roles": self.source_roles,
            "fields": tuple(item.model_dump(mode="python") for item in self.fields),
            "evidence_receipts": tuple(
                item.model_dump(mode="python") for item in self.evidence_receipts
            ),
            "batch_receipt": self.batch_receipt.model_dump(mode="python"),
            "candidate_sha256": self.candidate_sha256,
        }
        for key in exclude or set():
            payload.pop(key, None)
        return payload


def _outputs_sha256(outputs: tuple[FreeformFieldOutputV1, ...]) -> str:
    return canonical_hash(
        "schema67-deepseek-field-outputs.v1",
        tuple(item.model_dump(mode="python") for item in outputs),
    )


def _accepted_task_executions(
    fields: tuple[FreeformFieldOutputV1, ...],
    receipts: tuple[FreeformEvidenceBindingReceiptV1, ...],
    *,
    execution_plan: Schema67ExecutionPlanV1,
    prepared_tasks: tuple[Schema67PreparedTaskV1, ...],
) -> Schema67BatchExecutionV1:
    fields_by_id = {item.field_id: item for item in fields}
    receipts_by_id = {item.field_id: item for item in receipts}
    executions: list[DeepSeekTaskExecutionV1] = []
    for index, task in enumerate(prepared_tasks):
        field_ids = tuple(item.field_id for item in task.field_prompts)
        outputs = tuple(fields_by_id[item] for item in field_ids)
        task_receipts = tuple(receipts_by_id[item] for item in field_ids)
        verification = VerificationBatchV1(
            contract="evidence-verification-batch.v1",
            product_version_id="596-1",
            source_revision_id=f"source-revision-loader:{index}",
            parse_attempt_id=f"parse-attempt-loader:{index}",
            parsed_document_hash=_sha(f"loader-document:{index}"),
            parse_manifest_hash=_sha(f"loader-manifest:{index}"),
            results=tuple(
                FieldVerificationV1(
                    field_id=item.field_id,
                    status="PASS",
                    reason_codes=(),
                    candidate_snapshot_hash=_sha(f"loader-candidate:{index}:{item.field_id}"),
                )
                for item in sorted(outputs, key=lambda output: output.field_id)
            ),
        )
        receipt_chain = _verification_receipt_chain(verification)
        initial_payload = {
            "task_id": task.provider_task_sha256,
            "attempt_hash": task.provider_attempt_sha256,
            "execution_plan_sha256": execution_plan.execution_plan_sha256,
            "task_slice_sha256": task.task_slice_sha256,
            "output_hashes": tuple(
                canonical_hash(
                    "schema67-deepseek-field-output.v1",
                    item.model_dump(mode="python"),
                )
                for item in outputs
            ),
            "evidence_receipt_hashes": tuple(item.receipt_hash for item in task_receipts),
            "verification_hashes": (verification.verification_hash,),
            "receipt_chain_hashes": (tuple(item.receipt_hash for item in receipt_chain.receipts),),
        }
        initial = Schema67BoundAttemptV1(
            task_id=task.provider_task_sha256,
            attempt_hash=task.provider_attempt_sha256,
            execution_plan_sha256=execution_plan.execution_plan_sha256,
            task_slice_sha256=task.task_slice_sha256,
            outputs=outputs,
            evidence_receipts=task_receipts,
            verification_batches=(verification,),
            receipt_chains=(receipt_chain,),
            bound_attempt_hash=canonical_hash(
                "schema67-deepseek-bound-attempt.v1", initial_payload
            ),
        )
        receipt_values: dict[str, object] = {
            "contract": "deepseek-task-execution-receipt.v2",
            "model_identity": DEEPSEEK_MODEL_IDENTITY.model_dump(mode="python"),
            "execution_identity_sha256": DEEPSEEK_EXECUTION_IDENTITY_SHA256,
            "batch_budget_identity_sha256": (execution_plan.batch_budget.budget_identity_sha256),
            "execution_plan_sha256": execution_plan.execution_plan_sha256,
            "task_slice_sha256": task.task_slice_sha256,
            "schema_workbook_sha256": WORKBOOK_SHA256,
            "approved_by": "linyao",
            "task_id": task.provider_task_sha256,
            "attempt_hash": task.provider_attempt_sha256,
            "field_ids": field_ids,
            "field_contracts_sha256": _sha(f"field-contracts:{index}"),
            "locator_selection_policy_sha256": LOCATOR_SELECTION_POLICY_SHA256,
            "locator_authority_sha256": _sha(f"locator-authority:{index}"),
            "locator_selection_sha256": _sha(f"locator-selection:{index}"),
            "locator_slot_policy_sha256": deepseek_119.LOCATOR_SLOT_POLICY_SHA256,
            "locator_slot_authority_sha256": _sha(f"locator-slot-authority:{index}"),
            "response_contract_repair_policy_sha256": (
                deepseek_119._RESPONSE_CONTRACT_REPAIR_POLICY_SHA256
            ),
            "extractor_request_sha256": _sha(f"extractor-request:{index}"),
            "response_contract_repair": None,
            "evidence_repair_summary": None,
            "evidence_demotion": None,
            "initial_bound_attempt_hash": initial.bound_attempt_hash,
            "initial_outputs_sha256": _outputs_sha256(outputs),
            "final_outputs_sha256": _outputs_sha256(outputs),
            "evidence_receipt_hashes": tuple(item.receipt_hash for item in task_receipts),
            "locator_calls": 0,
            "extractor_calls": 1,
            "repair_calls": 0,
            "transport_retries": 0,
            "response_contract_repairs": 0,
            "evidence_repairs": 0,
            "total_calls": 1,
        }
        receipt = DeepSeekExecutionReceiptV1.model_validate(
            {
                **receipt_values,
                "receipt_hash": canonical_hash(
                    "deepseek-evidence-compiler-596-1.v2", receipt_values
                ),
            }
        )
        executions.append(
            DeepSeekTaskExecutionV1(
                initial=initial,
                initial_outputs=outputs,
                final_outputs=outputs,
                evidence_receipts=task_receipts,
                response_contract_repair=None,
                evidence_repair=None,
                evidence_demotion=None,
                receipt=receipt,
            )
        )
    budget = Schema67BatchBudgetV1(task_count=8, extractor_calls=8)
    batch_receipt = build_schema67_batch_receipt(
        execution_plan=execution_plan,
        prepared_tasks=prepared_tasks,
        budget=budget,
        executions=tuple(executions),
    )
    return Schema67BatchExecutionV1(executions=tuple(executions), receipt=batch_receipt)


def _accepted_task_executions_with_dual_repair(
    fields: tuple[FreeformFieldOutputV1, ...],
    receipts: tuple[FreeformEvidenceBindingReceiptV1, ...],
    *,
    execution_plan: Schema67ExecutionPlanV1,
    prepared_tasks: tuple[Schema67PreparedTaskV1, ...],
) -> Schema67BatchExecutionV1:
    base = _accepted_task_executions(
        fields,
        receipts,
        execution_plan=execution_plan,
        prepared_tasks=prepared_tasks,
    )
    task_index = next(
        index
        for index, task in enumerate(prepared_tasks)
        if len(task.field_prompts) >= 2
        and any(prompt.allowed_locator_refs for prompt in task.field_prompts)
    )
    task = prepared_tasks[task_index]
    execution = base.executions[task_index]
    target_prompt = next(prompt for prompt in task.field_prompts if prompt.allowed_locator_refs)
    target_field_id = target_prompt.field_id
    target_ref = target_prompt.allowed_locator_refs[0]
    quote = "loader dual repair evidence"
    document_seed, manifest_seed, _texts = _document()
    target_block = document_seed.blocks[0].model_copy(
        update={
            "block_id": target_ref,
            "content_hash": _sha(quote),
        }
    )
    document = ParsedDocumentV1.model_validate(
        {
            **document_seed.model_dump(mode="python", exclude={"document_hash"}),
            "blocks": (
                target_block.model_dump(mode="python"),
                *(item.model_dump(mode="python") for item in document_seed.blocks[1:]),
            ),
        }
    )
    manifest = ParseManifestV1.model_validate(
        {
            **manifest_seed.model_dump(mode="python", exclude={"manifest_hash"}),
            "document_hash": document.document_hash,
            "ordered_block_ids": tuple(item.block_id for item in document.blocks),
        }
    )
    target_evidence = FreeformEvidenceV1(
        field_id=target_field_id,
        source_sha256=document.subject.source_sha256,
        source_revision_id=document.subject.source_revision_id,
        parse_attempt_id=document.attempt.attempt_id,
        parsed_document_hash=document.document_hash,
        parse_manifest_hash=manifest.manifest_hash,
        page_number=1,
        block_id=target_ref,
        locator=EvidenceLocatorSnapshotV1(
            subject_type="block",
            subject_ref=target_ref,
            page_number=1,
            parent_refs=(document.pages[0].page_id,),
            content_snapshot=quote,
            content_snapshot_sha256=_sha(quote),
        ),
        quote_snapshot=quote,
        quote_snapshot_sha256=_sha(quote),
    )
    target_final = FreeformFieldOutputV1(
        product_version_id="596-1",
        field_id=target_field_id,
        state="present",
        value_snapshot="loader-dual-value",
        evidence=(target_evidence,),
    )
    target_final_receipt = bind_freeform_arm_evidence(
        field_output=target_final,
        documents=(document,),
        manifests=(manifest,),
    )
    final_outputs = tuple(
        target_final if item.field_id == target_field_id else item
        for item in execution.final_outputs
    )
    final_receipts = tuple(
        target_final_receipt if item.field_id == target_field_id else item
        for item in execution.evidence_receipts
    )
    # Evidence repair starts from a parsed known field whose verification failed;
    # an explicit UNKNOWN is already a valid terminal state and is not repairable.
    initial_outputs = final_outputs
    initial_receipts = final_receipts
    ordered_verification_ids = tuple(sorted(item.field_id for item in execution.final_outputs))
    verification = VerificationBatchV1(
        contract="evidence-verification-batch.v1",
        product_version_id="596-1",
        source_revision_id="source-revision-loader-dual",
        parse_attempt_id="parse-attempt-loader-dual",
        parsed_document_hash=_sha("loader-dual-document"),
        parse_manifest_hash=_sha("loader-dual-manifest"),
        results=tuple(
            FieldVerificationV1(
                field_id=field_id,
                status="FAIL" if field_id == target_field_id else "PASS",
                reason_codes=("EVIDENCE_INSUFFICIENT",) if field_id == target_field_id else (),
                candidate_snapshot_hash=_sha(f"initial-candidate:{field_id}"),
            )
            for field_id in ordered_verification_ids
        ),
    )
    initial_payload = {
        "task_id": task.provider_task_sha256,
        "attempt_hash": task.provider_attempt_sha256,
        "execution_plan_sha256": execution_plan.execution_plan_sha256,
        "task_slice_sha256": task.task_slice_sha256,
        "output_hashes": tuple(
            canonical_hash("schema67-deepseek-field-output.v1", item.model_dump(mode="python"))
            for item in initial_outputs
        ),
        "evidence_receipt_hashes": tuple(item.receipt_hash for item in initial_receipts),
        "verification_hashes": (verification.verification_hash,),
        "receipt_chain_hashes": (),
    }
    initial = Schema67BoundAttemptV1(
        task_id=task.provider_task_sha256,
        attempt_hash=task.provider_attempt_sha256,
        execution_plan_sha256=execution_plan.execution_plan_sha256,
        task_slice_sha256=task.task_slice_sha256,
        outputs=initial_outputs,
        evidence_receipts=initial_receipts,
        verification_batches=(verification,),
        receipt_chains=(),
        bound_attempt_hash=canonical_hash("schema67-deepseek-bound-attempt.v1", initial_payload),
    )
    repair_plan = TargetedRepairPlanV1(
        contract="targeted-repair-plan.v1",
        parent_verification_hash=verification.verification_hash,
        repair_number=1,
        field_ids=(target_field_id,),
        approved_locators=(
            ApprovedLocatorSetV1(
                field_id=target_field_id,
                locator_refs=target_prompt.allowed_locator_refs,
            ),
        ),
    )
    repaired_results = tuple(
        (
            FieldVerificationV1(
                field_id=item.field_id,
                status="PASS",
                reason_codes=(),
                candidate_snapshot_hash=_sha(f"final-candidate:{item.field_id}"),
            )
            if item.field_id == target_field_id
            else item
        )
        for item in verification.results
    )
    resolution = RepairResolutionV1(
        contract="targeted-repair-resolution.v1",
        parent_verification_hash=verification.verification_hash,
        repair_plan_hash=repair_plan.plan_hash,
        results=repaired_results,
        gaps=(),
        review_items=(),
    )
    trace_values = {
        "contract": "schema67-evidence-repair-trace.v2",
        "kind": "evidence_repair",
        "repair_request_sha256": _sha("loader-dual-evidence-request"),
        "accepted_response_sha256": _sha("loader-dual-evidence-response"),
        "repair_plan_sha256": repair_plan.plan_hash,
        "parent_bound_attempt_hash": initial.bound_attempt_hash,
        "repair_plan": repair_plan.model_dump(mode="python", exclude={"plan_hash"}),
        "verifier_resolution": resolution.model_dump(mode="python", exclude={"resolution_hash"}),
    }
    evidence_trace = deepseek_119.EvidenceRepairTraceV2.model_validate(
        {
            **trace_values,
            "trace_hash": canonical_hash("schema67-evidence-repair-trace.v2", trace_values),
        }
    )
    response_values = {
        "contract": "schema67-response-contract-repair-resolution.v2",
        "kind": "response_contract_repair",
        "failure_code": "FIELD_ITEM_SHAPE",
        "response_contract_repair_policy_sha256": (
            deepseek_119._RESPONSE_CONTRACT_REPAIR_POLICY_SHA256
        ),
        "field_ids": tuple(item.field_id for item in task.field_prompts),
        "failed_field_ids": (),
        "parent_extractor_request_sha256": execution.receipt.extractor_request_sha256,
        "invalid_response_sha256": _sha("loader-dual-invalid-response"),
        "repair_request_sha256": _sha("loader-dual-contract-request"),
        "accepted_response_sha256": _sha("loader-dual-contract-response"),
    }
    response_repair = deepseek_119.ResponseContractRepairResolutionV2.model_validate(
        {
            **response_values,
            "resolution_hash": canonical_hash(
                "schema67-response-contract-repair-resolution.v2", response_values
            ),
        }
    )
    receipt_values = execution.receipt.model_dump(mode="python", exclude={"receipt_hash"})
    receipt_values.update(
        {
            "response_contract_repair": response_repair.model_dump(mode="python"),
            "evidence_repair_summary": deepseek_119._evidence_repair_summary(
                evidence_trace
            ).model_dump(mode="python"),
            "initial_bound_attempt_hash": initial.bound_attempt_hash,
            "initial_outputs_sha256": _outputs_sha256(initial_outputs),
            "final_outputs_sha256": _outputs_sha256(final_outputs),
            "evidence_receipt_hashes": tuple(item.receipt_hash for item in final_receipts),
            "extractor_calls": 1,
            "repair_calls": 2,
            "transport_retries": 0,
            "response_contract_repairs": 1,
            "evidence_repairs": 1,
            "total_calls": 3,
        }
    )
    repaired_receipt = DeepSeekExecutionReceiptV1.model_validate(
        {
            **receipt_values,
            "receipt_hash": canonical_hash("deepseek-evidence-compiler-596-1.v2", receipt_values),
        }
    )
    repaired_execution = DeepSeekTaskExecutionV1(
        initial=initial,
        initial_outputs=initial_outputs,
        final_outputs=final_outputs,
        evidence_receipts=final_receipts,
        response_contract_repair=response_repair,
        evidence_repair=evidence_trace,
        evidence_demotion=None,
        receipt=repaired_receipt,
    )
    executions = tuple(
        repaired_execution if index == task_index else item
        for index, item in enumerate(base.executions)
    )
    budget = Schema67BatchBudgetV1(
        task_count=8,
        extractor_calls=8,
        repair_calls=2,
        response_contract_repairs=1,
        evidence_repairs=1,
    )
    return Schema67BatchExecutionV1(
        executions=executions,
        receipt=build_schema67_batch_receipt(
            execution_plan=execution_plan,
            prepared_tasks=prepared_tasks,
            budget=budget,
            executions=executions,
        ),
    )


def _accepted_task_executions_with_demotion(
    fields: tuple[FreeformFieldOutputV1, ...],
    receipts: tuple[FreeformEvidenceBindingReceiptV1, ...],
    *,
    execution_plan: Schema67ExecutionPlanV1,
    prepared_tasks: tuple[Schema67PreparedTaskV1, ...],
) -> Schema67BatchExecutionV1:
    base = _accepted_task_executions(
        fields,
        receipts,
        execution_plan=execution_plan,
        prepared_tasks=prepared_tasks,
    )
    task_index, target_field_ids = next(
        (index, tuple(item.field_id for item in known[-2:]))
        for index, execution in enumerate(base.executions)
        if len(
            known := tuple(
                output for output in execution.initial_outputs if output.state != "unknown"
            )
        )
        >= 2
    )
    task = prepared_tasks[task_index]
    execution = base.executions[task_index]
    verification = VerificationBatchV1(
        contract="evidence-verification-batch.v1",
        product_version_id="596-1",
        source_revision_id="source-revision-loader-demotion",
        parse_attempt_id="parse-attempt-loader-demotion",
        parsed_document_hash=_sha("loader-demotion-document"),
        parse_manifest_hash=_sha("loader-demotion-manifest"),
        results=tuple(
            FieldVerificationV1(
                field_id=item.field_id,
                status="FAIL" if item.field_id in target_field_ids else "PASS",
                reason_codes=("EVIDENCE_INSUFFICIENT",)
                if item.field_id in target_field_ids
                else (),
                candidate_snapshot_hash=_sha(f"loader-demotion-candidate:{item.field_id}"),
            )
            for item in sorted(execution.initial_outputs, key=lambda output: output.field_id)
        ),
    )
    receipt_chain = _verification_receipt_chain(verification)
    initial_payload = {
        "task_id": task.provider_task_sha256,
        "attempt_hash": task.provider_attempt_sha256,
        "execution_plan_sha256": execution_plan.execution_plan_sha256,
        "task_slice_sha256": task.task_slice_sha256,
        "output_hashes": tuple(
            canonical_hash("schema67-deepseek-field-output.v1", item.model_dump(mode="python"))
            for item in execution.initial_outputs
        ),
        "evidence_receipt_hashes": tuple(
            item.receipt_hash for item in execution.initial.evidence_receipts
        ),
        "verification_hashes": (verification.verification_hash,),
        "receipt_chain_hashes": (tuple(item.receipt_hash for item in receipt_chain.receipts),),
    }
    initial = Schema67BoundAttemptV1(
        task_id=task.provider_task_sha256,
        attempt_hash=task.provider_attempt_sha256,
        execution_plan_sha256=execution_plan.execution_plan_sha256,
        task_slice_sha256=task.task_slice_sha256,
        outputs=execution.initial_outputs,
        evidence_receipts=execution.initial.evidence_receipts,
        verification_batches=(verification,),
        receipt_chains=(receipt_chain,),
        bound_attempt_hash=canonical_hash("schema67-deepseek-bound-attempt.v1", initial_payload),
    )
    final_outputs, final_receipts, demotion = deepseek_119._demote_initial_nonpass(
        initial, execution.initial_outputs
    )
    assert demotion is not None
    receipt_values = execution.receipt.model_dump(mode="python", exclude={"receipt_hash"})
    receipt_values.update(
        {
            "evidence_demotion": demotion.model_dump(mode="python"),
            "initial_bound_attempt_hash": initial.bound_attempt_hash,
            "final_outputs_sha256": _outputs_sha256(final_outputs),
            "evidence_receipt_hashes": tuple(item.receipt_hash for item in final_receipts),
        }
    )
    demoted_receipt = DeepSeekExecutionReceiptV1.model_validate(
        {
            **receipt_values,
            "receipt_hash": canonical_hash("deepseek-evidence-compiler-596-1.v2", receipt_values),
        }
    )
    demoted_execution = DeepSeekTaskExecutionV1(
        initial=initial,
        initial_outputs=execution.initial_outputs,
        final_outputs=final_outputs,
        evidence_receipts=final_receipts,
        response_contract_repair=None,
        evidence_repair=None,
        evidence_demotion=demotion,
        receipt=demoted_receipt,
    )
    executions = tuple(
        demoted_execution if index == task_index else item
        for index, item in enumerate(base.executions)
    )
    budget = Schema67BatchBudgetV1(task_count=8, extractor_calls=8)
    return Schema67BatchExecutionV1(
        executions=executions,
        receipt=build_schema67_batch_receipt(
            execution_plan=execution_plan,
            prepared_tasks=prepared_tasks,
            budget=budget,
            executions=executions,
            _single_pass_mvp=True,
        ),
    )


def _candidate_v2(
    cases: tuple[EvidenceReplayCaseV1, ...],
    *,
    dual_repair: bool = False,
    single_pass_demotion: bool = False,
) -> admission_119.Schema67CandidateV2:
    assert not (dual_repair and single_pass_demotion)
    fields = _candidate_fields(cases)
    receipts: list[FreeformEvidenceBindingReceiptV1] = []
    for output in fields:
        matching = tuple(case for case in cases if case.field_output.field_id == output.field_id)
        receipt = bind_freeform_arm_evidence(
            field_output=output,
            documents=() if output.state == "unknown" else matching[0].documents,
            manifests=() if output.state == "unknown" else matching[0].manifests,
        )
        receipts.append(receipt)
    contracts = compile_schema_contracts(_approved_a_snapshot())
    execution_plan = build_schema67_execution_plan(contracts)
    role_inputs = _real_schema67_role_inputs(contracts, execution_plan)
    prepared_tasks = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=execution_plan,
        role_inputs=role_inputs,
    )
    batch_factory = (
        _accepted_task_executions_with_dual_repair
        if dual_repair
        else _accepted_task_executions_with_demotion
        if single_pass_demotion
        else _accepted_task_executions
    )
    batch_execution = batch_factory(
        fields,
        tuple(receipts),
        execution_plan=execution_plan,
        prepared_tasks=prepared_tasks,
    )
    return admission_119.make_total_control_schema67_candidate_v2(
        field_contracts=contracts,
        execution_plan=execution_plan,
        role_inputs=role_inputs,
        batch_execution=batch_execution,
        candidate_tree_sha1="bf38d51bef0b6d1ae119bb0535e8ff0dc9463c53",
    )


def _duck_candidate_v2(
    candidate: admission_119.Schema67CandidateV2,
) -> _CandidateV2Fixture:
    return _CandidateV2Fixture(
        contract=candidate.contract,
        product_version_id=candidate.product_version_id,
        ordered_field_ids=candidate.ordered_field_ids,
        candidate_tree_sha1=candidate.candidate_tree_sha1,
        model_identity_sha256=candidate.model_identity_sha256,
        source_roles=candidate.source_roles,
        fields=candidate.fields,
        evidence_receipts=candidate.evidence_receipts,
        batch_receipt=candidate.batch_receipt,
        accepted_task_executions=candidate.batch_execution.executions,
        candidate_sha256=candidate.candidate_sha256,
    )


def _make_report_gate(
    *,
    cases: tuple[EvidenceReplayCaseV1, ...] | None = None,
    comparator: object | None = None,
) -> admission_119.Schema67ReportGateV1:
    exact_cases = _approved_cases() if cases is None else cases
    candidate = _candidate_v2(exact_cases)
    return admission_119.make_total_control_schema67_report_gate(
        snapshot=_authority_snapshot(),
        candidate=candidate,
        evidence_cases=exact_cases,
        frozen_candidate_bundle_sha256=candidate_evidence_bundle_sha256(
            candidate.fields, exact_cases
        ),
        receipt=_receipt(),
        observed_at=NOW,
        comparator=comparator or _approved_comparator(),
    )


def test_report_gate_factory_binds_candidate_batch_evidence_and_authorities() -> None:
    cases = _approved_cases()
    candidate = _candidate_v2(cases)
    comparator = _approved_comparator()

    gate = admission_119.make_total_control_schema67_report_gate(
        snapshot=_authority_snapshot(),
        candidate=candidate,
        evidence_cases=cases,
        frozen_candidate_bundle_sha256=candidate_evidence_bundle_sha256(candidate.fields, cases),
        receipt=_receipt(),
        observed_at=NOW,
        comparator=comparator,
    )

    assert admission_119.validate_schema67_report_gate(gate) is gate
    assert gate.candidate_v2_sha256 == candidate.candidate_sha256
    assert gate.accepted_batch_receipt_sha256 == (candidate.batch_receipt.batch_receipt_sha256)
    assert gate.task_receipt_hashes == candidate.batch_receipt.task_receipt_hashes
    assert len(gate.task_receipt_hashes) == 8
    assert gate.candidate_evidence_receipt_hashes == tuple(
        receipt.receipt_hash
        for field, receipt in zip(candidate.fields, candidate.evidence_receipts, strict=True)
        if field.state != "unknown"
    )
    assert len(gate.live_evidence_receipt_hashes) == 111
    assert gate.reference_receipt_sha256 == _receipt().receipt_sha256
    assert gate.comparator_authority_sha256 == comparator.authority.authority_sha256
    assert len(gate.semantic_decision_receipt_hashes) == 46
    with pytest.raises(AttributeError):
        object.__setattr__(candidate._factory_seal, "candidate_sha256", "f" * 64)
    with pytest.raises(TypeError):
        pickle.loads(pickle.dumps(candidate._factory_seal))


def test_runtime_duck_candidate_with_self_hashed_synthetic_tasks_is_rejected() -> None:
    cases = _approved_cases()
    sealed = _candidate_v2(cases)
    candidate = _duck_candidate_v2(sealed)

    with pytest.raises(
        admission_119.LaneCReportGateError,
        match="CANDIDATE_V2_CUSTODY_INVALID",
    ):
        admission_119.make_total_control_schema67_report_gate(
            snapshot=_authority_snapshot(),
            candidate=candidate,
            evidence_cases=cases,
            frozen_candidate_bundle_sha256=candidate_evidence_bundle_sha256(
                candidate.fields, cases
            ),
            receipt=_receipt(),
            observed_at=NOW,
            comparator=_AuthorityComparator(),
        )


def test_public_candidate_v2_validator_replays_concrete_custody_only() -> None:
    candidate = _candidate_v2(_approved_cases())

    assert admission_119.validate_schema67_candidate_v2(candidate) is candidate
    with pytest.raises(
        admission_119.LaneCReportGateError,
        match="CANDIDATE_V2_CUSTODY_INVALID",
    ):
        admission_119.validate_schema67_candidate_v2(_duck_candidate_v2(candidate))
    with pytest.raises(
        admission_119.LaneCReportGateError,
        match="CANDIDATE_V2_CUSTODY_INVALID",
    ):
        admission_119.validate_schema67_candidate_v2(replace(candidate, candidate_sha256="f" * 64))


def _candidate_v2_wire() -> dict[str, object]:
    candidate = _candidate_v2(_approved_cases())
    wire = json.loads(
        json.dumps(
            candidate.model_dump(mode="python", round_trip=True),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    assert type(wire) is dict
    return cast(dict[str, object], wire)


def _trusted_candidate_v2_preparation() -> tuple[
    FieldContractSetV1,
    Schema67ExecutionPlanV1,
    tuple[Schema67RoleTaskInputV1, ...],
]:
    contracts = compile_schema_contracts(_approved_a_snapshot())
    execution_plan = build_schema67_execution_plan(contracts)
    return (
        contracts,
        execution_plan,
        _real_schema67_role_inputs(contracts, execution_plan),
    )


def _load_candidate_v2(payload: object) -> admission_119.Schema67CandidateV2:
    contracts, execution_plan, role_inputs = _trusted_candidate_v2_preparation()
    return admission_119.load_schema67_candidate_v2(
        payload,
        field_contracts=contracts,
        execution_plan=execution_plan,
        role_inputs=role_inputs,
    )


def _self_rehash_candidate_v2_wire(payload: dict[str, object]) -> None:
    payload["candidate_sha256"] = canonical_hash(
        "schema67-candidate.v2",
        {key: value for key, value in payload.items() if key != "candidate_sha256"},
    )


def _rehash_candidate_task_wire(payload: dict[str, object], execution_index: int) -> None:
    batch_execution = cast(dict[str, object], payload["batch_execution"])
    executions = cast(list[dict[str, object]], batch_execution["executions"])
    execution = executions[execution_index]
    receipt = cast(dict[str, object], execution["receipt"])
    receipt["receipt_hash"] = canonical_hash(
        "deepseek-evidence-compiler-596-1.v2",
        {key: value for key, value in receipt.items() if key != "receipt_hash"},
    )
    batch_receipt = cast(dict[str, object], batch_execution["receipt"])
    task_hashes = cast(list[str], batch_receipt["task_receipt_hashes"])
    task_hashes[execution_index] = cast(str, receipt["receipt_hash"])
    batch_values = {
        key: value for key, value in batch_receipt.items() if key != "batch_receipt_sha256"
    }
    batch_receipt["batch_receipt_sha256"] = deepseek_119._batch_receipt_sha256(batch_values)
    payload["batch_receipt"] = copy.deepcopy(batch_receipt)
    _self_rehash_candidate_v2_wire(payload)


def test_public_candidate_v2_loader_round_trips_exact_canonical_json() -> None:
    candidate = _candidate_v2(_approved_cases())
    payload = _candidate_v2_wire()

    loaded = _load_candidate_v2(payload)

    assert admission_119.validate_schema67_candidate_v2(loaded) is loaded
    assert loaded.candidate_sha256 == candidate.candidate_sha256
    assert loaded.model_dump(mode="python", round_trip=True) == candidate.model_dump(
        mode="python",
        round_trip=True,
    )
    signature = inspect.signature(admission_119.load_schema67_candidate_v2)
    for parameter_name in ("field_contracts", "execution_plan", "role_inputs"):
        assert signature.parameters[parameter_name].default is inspect.Parameter.empty


def test_public_candidate_v2_loader_round_trips_nested_single_pass_demotion() -> None:
    candidate = _candidate_v2(_approved_cases(), single_pass_demotion=True)
    payload = json.loads(
        json.dumps(
            candidate.model_dump(mode="python", round_trip=True),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    demoted_execution = next(
        item
        for item in payload["batch_execution"]["executions"]
        if item["receipt"]["evidence_demotion"] is not None
    )

    assert "evidence_demotion" not in demoted_execution
    exact_receipt_keys = (
        "policy_sha256",
        "parent_bound_attempt_sha256",
        "verification_batch_hashes",
        "demoted_field_ids",
        "initial_output_sha256",
        "final_output_sha256",
        "final_evidence_receipt_hashes",
        "pass_preservation_sha256",
        "receipt_hash",
    )
    assert tuple(deepseek_119.EvidenceDemotionReceiptV1.model_fields) == (exact_receipt_keys)
    assert set(demoted_execution["receipt"]["evidence_demotion"]) == set(exact_receipt_keys)

    loaded = _load_candidate_v2(payload)

    assert loaded.model_dump(mode="python", round_trip=True) == candidate.model_dump(
        mode="python", round_trip=True
    )
    assert loaded.batch_receipt.prior_provider_calls == 2
    assert loaded.batch_receipt.cumulative_provider_calls == 10


def test_public_candidate_v2_loader_rejects_rehashed_demotion_receipt_omission() -> None:
    payload = json.loads(
        json.dumps(
            _candidate_v2(_approved_cases(), single_pass_demotion=True).model_dump(
                mode="python", round_trip=True
            ),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    executions = payload["batch_execution"]["executions"]
    execution_index = next(
        index
        for index, item in enumerate(executions)
        if item["receipt"]["evidence_demotion"] is not None
    )
    execution = executions[execution_index]
    execution["final_outputs"] = copy.deepcopy(execution["initial_outputs"])
    execution["evidence_receipts"] = copy.deepcopy(execution["initial"]["evidence_receipts"])
    receipt = execution["receipt"]
    receipt["evidence_demotion"] = None
    receipt["final_outputs_sha256"] = canonical_hash(
        "schema67-deepseek-field-outputs.v1", tuple(execution["final_outputs"])
    )
    receipt["evidence_receipt_hashes"] = [
        item["receipt_hash"] for item in execution["evidence_receipts"]
    ]
    _rehash_candidate_task_wire(payload, execution_index)

    with pytest.raises(
        admission_119.LaneCReportGateError,
        match="CANDIDATE_V2_CUSTODY_INVALID",
    ):
        _load_candidate_v2(payload)


@pytest.mark.parametrize(
    "mutation",
    (
        "keys",
        "scope",
        "order",
        "hash",
        "parent",
        "verification",
        "pass_output",
        "pass_receipt",
        "demoted_output",
        "retry",
        "response_repair",
        "evidence_repair",
        "budget",
    ),
)
def test_public_candidate_v2_loader_rejects_rehashed_demotion_drift(
    mutation: str,
) -> None:
    payload = json.loads(
        json.dumps(
            _candidate_v2(_approved_cases(), single_pass_demotion=True).model_dump(
                mode="python", round_trip=True
            ),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    batch_execution = payload["batch_execution"]
    executions = batch_execution["executions"]
    execution_index = next(
        index
        for index, item in enumerate(executions)
        if item["receipt"]["evidence_demotion"] is not None
    )
    execution = executions[execution_index]
    receipt = execution["receipt"]
    demotion = receipt["evidence_demotion"]
    if mutation == "keys":
        demotion["caller_attestation"] = "forbidden"
    elif mutation == "scope":
        demoted = set(demotion["demoted_field_ids"])
        demotion["demoted_field_ids"] = [
            next(
                item["field_id"]
                for item in execution["initial_outputs"]
                if item["field_id"] not in demoted and item["state"] != "unknown"
            )
        ]
    elif mutation == "order":
        assert len(demotion["demoted_field_ids"]) == 2
        demotion["demoted_field_ids"] = list(reversed(demotion["demoted_field_ids"]))
    elif mutation == "hash":
        demotion["receipt_hash"] = "f" * 64
    elif mutation == "parent":
        demotion["parent_bound_attempt_sha256"] = "f" * 64
    elif mutation == "verification":
        demotion["verification_batch_hashes"] = ["f" * 64]
    elif mutation == "pass_output":
        demoted = set(demotion["demoted_field_ids"])
        output = next(
            item
            for item in execution["final_outputs"]
            if item["field_id"] not in demoted and item["state"] == "present"
        )
        output["value_snapshot"] = "caller-mutated-pass-value"
        receipt["final_outputs_sha256"] = canonical_hash(
            "schema67-deepseek-field-outputs.v1",
            tuple(execution["final_outputs"]),
        )
        demotion["final_output_sha256"] = receipt["final_outputs_sha256"]
    elif mutation == "pass_receipt":
        demoted = set(demotion["demoted_field_ids"])
        evidence_receipt = next(
            item for item in execution["evidence_receipts"] if item["field_id"] not in demoted
        )
        evidence_receipt["receipt_hash"] = "f" * 64
        receipt["evidence_receipt_hashes"] = [
            item["receipt_hash"] for item in execution["evidence_receipts"]
        ]
        demotion["final_evidence_receipt_hashes"] = receipt["evidence_receipt_hashes"]
    elif mutation == "demoted_output":
        output = next(
            item
            for item in execution["final_outputs"]
            if item["field_id"] in set(demotion["demoted_field_ids"])
        )
        output["state"] = "present"
        output["value_snapshot"] = "restored-by-caller"
        receipt["final_outputs_sha256"] = canonical_hash(
            "schema67-deepseek-field-outputs.v1",
            tuple(execution["final_outputs"]),
        )
        demotion["final_output_sha256"] = receipt["final_outputs_sha256"]
    elif mutation == "retry":
        receipt["extractor_calls"] = 2
        receipt["transport_retries"] = 1
        receipt["total_calls"] = 2
    elif mutation == "response_repair":
        receipt["repair_calls"] = 1
        receipt["response_contract_repairs"] = 1
        receipt["total_calls"] = 2
    elif mutation == "evidence_repair":
        receipt["repair_calls"] = 1
        receipt["evidence_repairs"] = 1
        receipt["total_calls"] = 2
    else:
        batch_receipt = batch_execution["receipt"]
        batch_receipt["prior_provider_calls"] = None
        batch_receipt["cumulative_provider_calls"] = None
    if mutation not in {"hash", "budget"}:
        demotion["receipt_hash"] = canonical_hash(
            "schema67-evidence-demotion-receipt.v1",
            {key: value for key, value in demotion.items() if key != "receipt_hash"},
        )
    _rehash_candidate_task_wire(payload, execution_index)

    with pytest.raises(admission_119.LaneCReportGateError):
        _load_candidate_v2(payload)


def test_public_candidate_v2_loader_rejects_all_pass_fake_demotion_receipt() -> None:
    all_pass = _candidate_v2(_approved_cases())
    demoted = _candidate_v2(_approved_cases(), single_pass_demotion=True)
    assert all(
        item.receipt.evidence_demotion is None for item in all_pass.batch_execution.executions
    )
    payload = json.loads(
        json.dumps(
            all_pass.model_dump(mode="python", round_trip=True),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    fake_receipt = next(
        item.receipt.evidence_demotion
        for item in demoted.batch_execution.executions
        if item.receipt.evidence_demotion is not None
    )
    execution = payload["batch_execution"]["executions"][0]
    execution["receipt"]["evidence_demotion"] = fake_receipt.model_dump(mode="json")
    _rehash_candidate_task_wire(payload, 0)

    with pytest.raises(admission_119.LaneCReportGateError):
        _load_candidate_v2(payload)


def test_public_candidate_v2_loader_rejects_caller_top_level_demotion_summary() -> None:
    payload = json.loads(
        json.dumps(
            _candidate_v2(_approved_cases(), single_pass_demotion=True).model_dump(
                mode="python", round_trip=True
            ),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    execution = next(
        item
        for item in payload["batch_execution"]["executions"]
        if item["receipt"]["evidence_demotion"] is not None
    )
    execution["evidence_demotion"] = copy.deepcopy(execution["receipt"]["evidence_demotion"])
    _self_rehash_candidate_v2_wire(payload)

    with pytest.raises(admission_119.LaneCReportGateError):
        _load_candidate_v2(payload)


def test_public_candidate_v2_loader_rejects_all_pass_budget_downgrade() -> None:
    payload = json.loads(
        json.dumps(
            _candidate_v2(_approved_cases()).model_dump(mode="python", round_trip=True),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    batch_receipt = payload["batch_execution"]["receipt"]
    assert (
        batch_receipt["prior_provider_calls"],
        batch_receipt["cumulative_provider_calls"],
    ) == (2, 10)
    batch_receipt["prior_provider_calls"] = None
    batch_receipt["cumulative_provider_calls"] = None
    batch_values = {
        key: value for key, value in batch_receipt.items() if key != "batch_receipt_sha256"
    }
    batch_receipt["batch_receipt_sha256"] = canonical_hash(
        deepseek_119._BATCH_RECEIPT_OBJECT_TYPE,
        batch_values,
    )
    payload["batch_receipt"] = copy.deepcopy(batch_receipt)
    _self_rehash_candidate_v2_wire(payload)

    with pytest.raises(admission_119.LaneCReportGateError):
        _load_candidate_v2(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("task_count", 7),
        ("provider_calls", 9),
        ("extractor_calls", 9),
        ("locator_calls", 1),
        ("transport_retries", 1),
        ("response_contract_repairs", 1),
        ("evidence_repairs", 1),
        ("repair_calls", 1),
        ("prior_provider_calls", None),
        ("cumulative_provider_calls", None),
    ),
)
def test_public_candidate_v2_loader_rejects_each_single_batch_budget_drift(
    field: str,
    value: int | None,
) -> None:
    payload = json.loads(
        json.dumps(
            _candidate_v2(_approved_cases(), single_pass_demotion=True).model_dump(
                mode="python", round_trip=True
            ),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    batch_receipt = payload["batch_execution"]["receipt"]
    batch_receipt[field] = value
    batch_values = {
        key: item for key, item in batch_receipt.items() if key != "batch_receipt_sha256"
    }
    batch_receipt["batch_receipt_sha256"] = deepseek_119._batch_receipt_sha256(batch_values)
    payload["batch_receipt"] = copy.deepcopy(batch_receipt)
    _self_rehash_candidate_v2_wire(payload)

    with pytest.raises(admission_119.LaneCReportGateError):
        _load_candidate_v2(payload)


def _demoted_candidate_evidence_cases(
    candidate: admission_119.Schema67CandidateV2,
) -> tuple[EvidenceReplayCaseV1, ...]:
    fields_by_id = {item.field_id: item for item in candidate.fields}
    return tuple(
        case
        for case in _approved_cases()
        if fields_by_id[case.field_output.field_id].state != "unknown"
    )


def test_lane_c_derives_demotion_review_items_and_skips_only_unknown_fields() -> None:
    candidate = _candidate_v2(_approved_cases(), single_pass_demotion=True)
    cases = _demoted_candidate_evidence_cases(candidate)
    comparator = _approved_comparator()

    gate = admission_119.make_total_control_schema67_report_gate(
        snapshot=_authority_snapshot(),
        candidate=candidate,
        evidence_cases=cases,
        frozen_candidate_bundle_sha256=candidate_evidence_bundle_sha256(candidate.fields, cases),
        receipt=_receipt(),
        observed_at=NOW,
        comparator=comparator,
    )

    demoted_field_ids = tuple(
        field_id
        for execution in candidate.batch_execution.executions
        if execution.receipt.evidence_demotion is not None
        for field_id in execution.receipt.evidence_demotion.demoted_field_ids
    )
    rows_by_id = {item.field_id: item for item in gate.rows}
    assert demoted_field_ids
    assert all(
        rows_by_id[field_id].evidence_057_status == "NOT_REQUIRED"
        and rows_by_id[field_id].correctness == "PENDING"
        and rows_by_id[field_id].completeness == "PENDING"
        and rows_by_id[field_id].review_reason_codes == ("EVIDENCE_NONPASS_DEMOTED",)
        for field_id in demoted_field_ids
    )
    assert tuple(
        item.field_id for item in gate.rows if item.semantic_decision_receipt_sha256 is not None
    ) == tuple(item.field_id for item in candidate.fields if item.state != "unknown")
    assert gate.status in {"PENDING", "BLOCKED"}
    assert gate.wiki_admission_allowed is False
    assert gate.publishable_field_ids == ()


def test_public_candidate_v2_loader_round_trips_dual_repair_and_rejects_drift() -> None:
    candidate = _candidate_v2(_approved_cases(), dual_repair=True)
    payload = json.loads(
        json.dumps(
            candidate.model_dump(mode="python", round_trip=True),
            sort_keys=True,
            separators=(",", ":"),
        )
    )

    loaded = _load_candidate_v2(payload)

    assert loaded.candidate_sha256 == candidate.candidate_sha256
    assert loaded.batch_receipt.provider_calls == 10
    dual_execution = next(
        item
        for item in loaded.batch_execution.executions
        if item.response_contract_repair is not None and item.evidence_repair is not None
    )
    assert dual_execution.receipt.response_contract_repairs == 1
    assert dual_execution.receipt.evidence_repairs == 1

    for drift in ("trace", "plan", "summary", "nonrepair_receipt"):
        forged = json.loads(json.dumps(payload))
        executions = forged["batch_execution"]["executions"]
        dual_index = next(
            index
            for index, item in enumerate(executions)
            if item["response_contract_repair"] is not None and item["evidence_repair"] is not None
        )
        if drift == "trace":
            executions[dual_index]["evidence_repair"]["trace_hash"] = "f" * 64
        elif drift == "plan":
            executions[dual_index]["evidence_repair"]["repair_plan"]["parent_verification_hash"] = (
                "f" * 64
            )
        elif drift == "summary":
            executions[dual_index]["receipt"]["evidence_repair_summary"]["summary_hash"] = "f" * 64
        else:
            executions[(dual_index + 1) % 8]["receipt"]["receipt_hash"] = "f" * 64
        _self_rehash_candidate_v2_wire(forged)
        with pytest.raises(
            admission_119.LaneCReportGateError,
            match="CANDIDATE_V2_CUSTODY_INVALID",
        ):
            _load_candidate_v2(forged)


def test_candidate_rejects_fully_rehashed_dual_repair_missing_prior_pass_field() -> None:
    candidate = _candidate_v2(_approved_cases(), dual_repair=True)
    dual_index = next(
        index
        for index, item in enumerate(candidate.batch_execution.executions)
        if item.response_contract_repair is not None and item.evidence_repair is not None
    )
    execution = candidate.batch_execution.executions[dual_index]
    assert isinstance(execution.initial, Schema67BoundAttemptV1)
    assert execution.evidence_repair is not None
    verification = next(
        item
        for item in execution.initial.verification_batches
        if item.verification_hash == execution.evidence_repair.repair_plan.parent_verification_hash
    )
    removed = next(item for item in verification.results if item.status == "PASS")
    drifted_plan = execution.evidence_repair.repair_plan
    drifted_resolution = RepairResolutionV1(
        contract="targeted-repair-resolution.v1",
        parent_verification_hash=verification.verification_hash,
        repair_plan_hash=drifted_plan.plan_hash,
        results=tuple(
            item
            for item in execution.evidence_repair.verifier_resolution.results
            if item.field_id != removed.field_id
        ),
        gaps=(),
        review_items=(),
    )
    trace_values = {
        "contract": "schema67-evidence-repair-trace.v2",
        "kind": "evidence_repair",
        "repair_request_sha256": execution.evidence_repair.repair_request_sha256,
        "accepted_response_sha256": execution.evidence_repair.accepted_response_sha256,
        "repair_plan_sha256": drifted_plan.plan_hash,
        "parent_bound_attempt_hash": execution.initial.bound_attempt_hash,
        "repair_plan": drifted_plan.model_dump(mode="python", exclude={"plan_hash"}),
        "verifier_resolution": drifted_resolution.model_dump(
            mode="python", exclude={"resolution_hash"}
        ),
    }
    drifted_trace = deepseek_119.EvidenceRepairTraceV2.model_validate(
        {
            **trace_values,
            "trace_hash": canonical_hash("schema67-evidence-repair-trace.v2", trace_values),
        }
    )
    receipt_values = execution.receipt.model_dump(mode="python", exclude={"receipt_hash"})
    receipt_values.update(
        {
            "initial_bound_attempt_hash": execution.initial.bound_attempt_hash,
            "evidence_repair_summary": deepseek_119._evidence_repair_summary(
                drifted_trace
            ).model_dump(mode="python"),
        }
    )
    drifted_receipt = DeepSeekExecutionReceiptV1.model_validate(
        {
            **receipt_values,
            "receipt_hash": canonical_hash("deepseek-evidence-compiler-596-1.v2", receipt_values),
        }
    )
    with pytest.raises(
        ValueError,
        match="deepseek_evidence_repair_custody_mismatch",
    ):
        DeepSeekTaskExecutionV1(
            initial=execution.initial,
            initial_outputs=execution.initial_outputs,
            final_outputs=execution.final_outputs,
            evidence_receipts=execution.evidence_receipts,
            response_contract_repair=execution.response_contract_repair,
            evidence_repair=drifted_trace,
            evidence_demotion=None,
            receipt=drifted_receipt,
        )


def test_public_candidate_v2_loader_rejects_self_rehashed_task_key_drift() -> None:
    payload = _candidate_v2_wire()
    prepared_tasks = payload["prepared_tasks"]
    assert isinstance(prepared_tasks, list)
    first_task = prepared_tasks[0]
    assert isinstance(first_task, dict)
    first_task["task_key"] = "attacker-task-key"
    _self_rehash_candidate_v2_wire(payload)

    with pytest.raises(
        admission_119.LaneCReportGateError,
        match="CANDIDATE_V2_CUSTODY_INVALID",
    ):
        _load_candidate_v2(payload)


def test_public_candidate_v2_loader_rejects_self_rehashed_locator_authority_drift() -> None:
    payload = _candidate_v2_wire()
    prepared_tasks = payload["prepared_tasks"]
    assert isinstance(prepared_tasks, list)
    first_task = prepared_tasks[0]
    assert isinstance(first_task, dict)
    field_prompts = first_task["field_prompts"]
    assert isinstance(field_prompts, list)
    first_prompt = field_prompts[0]
    assert isinstance(first_prompt, dict)
    source_locator_refs = first_prompt["source_locator_refs"]
    assert isinstance(source_locator_refs, list)
    first_source = source_locator_refs[0]
    assert isinstance(first_source, list)
    source_refs = first_source[1]
    assert isinstance(source_refs, list)
    source_refs.append("attacker-locator-ref")
    source_refs.sort()
    first_prompt["allowed_locator_refs"] = sorted(
        {locator_ref for source_row in source_locator_refs for locator_ref in source_row[1]}
    )
    first_prompt["requires_unknown_review"] = any(
        not source_row[1] for source_row in source_locator_refs
    )
    _self_rehash_candidate_v2_wire(payload)

    with pytest.raises(
        admission_119.LaneCReportGateError,
        match="CANDIDATE_V2_CUSTODY_INVALID",
    ):
        _load_candidate_v2(payload)


@pytest.mark.parametrize(
    ("path", "replacement"),
    (
        (("ordered_field_ids", 0), "foreign-field"),
        (("prepared_tasks", 0, "provider_task_sha256"), "f" * 64),
        (("batch_execution", "receipt", "batch_receipt_sha256"), "f" * 64),
        (("fields", 0, "state"), "unknown"),
        (("evidence_receipts", 0, "receipt_hash"), "f" * 64),
        (("candidate_sha256",), "f" * 64),
    ),
)
def test_public_candidate_v2_loader_rejects_custody_drift(
    path: tuple[str | int, ...],
    replacement: object,
) -> None:
    payload = _candidate_v2_wire()
    target: object = payload
    for part in path[:-1]:
        if isinstance(target, dict):
            assert isinstance(part, str)
            target = target[part]
        else:
            assert isinstance(target, list)
            assert isinstance(part, int)
            target = target[part]
    final_part = path[-1]
    if isinstance(target, dict):
        assert isinstance(final_part, str)
        target[final_part] = replacement
    else:
        assert isinstance(target, list)
        assert isinstance(final_part, int)
        target[final_part] = replacement

    with pytest.raises(
        admission_119.LaneCReportGateError,
        match="CANDIDATE_V2_CUSTODY_INVALID",
    ):
        _load_candidate_v2(payload)


def test_public_candidate_v2_loader_rejects_shape_self_signing_and_sensitive_input() -> None:
    candidate = _candidate_v2(_approved_cases())
    payload = _candidate_v2_wire()
    payload["api_key"] = "must-not-survive"
    with pytest.raises(admission_119.LaneCReportGateError) as extra_error:
        _load_candidate_v2(payload)
    assert "must-not-survive" not in repr(extra_error.value)
    assert extra_error.value.__cause__ is None

    missing = _candidate_v2_wire()
    missing.pop("batch_receipt")
    with pytest.raises(admission_119.LaneCReportGateError):
        _load_candidate_v2(missing)

    forged = _candidate_v2_wire()
    forged_fields = forged["fields"]
    assert isinstance(forged_fields, list)
    first_field = forged_fields[0]
    assert isinstance(first_field, dict)
    first_field["value_snapshot"] = "attacker-selected-value"
    forged["candidate_sha256"] = canonical_hash(
        "schema67-candidate.v2",
        {key: value for key, value in forged.items() if key != "candidate_sha256"},
    )
    with pytest.raises(admission_119.LaneCReportGateError):
        _load_candidate_v2(forged)

    with pytest.raises(admission_119.LaneCReportGateError):
        _load_candidate_v2(candidate)


def test_sixty_five_unknown_fields_never_make_report_gate_ready() -> None:
    cases = _approved_cases()
    present_field_id = next(
        field_id
        for field_id in ORDERED_FIELD_IDS
        if field_id not in FIXED_UNKNOWN_FIELD_IDS and field_id != EXPLICIT_ABSENCE_FIELD_ID
    )
    reduced = tuple(
        case
        for case in cases
        if case.field_output.field_id in (present_field_id, EXPLICIT_ABSENCE_FIELD_ID)
    )

    gate = _make_report_gate(cases=reduced)

    pending = tuple(row for row in gate.rows if row.state == "unknown")
    assert len(pending) == 65
    assert gate.status == "BLOCKED"
    assert gate.wiki_admission_allowed is False
    assert gate.publishable_field_ids == ()
    assert all(row.correctness == "PENDING" for row in pending)
    assert all(row.completeness == "PENDING" for row in pending)
    assert all(row.review_reason_codes == ("SEMANTIC_UNKNOWN_PENDING",) for row in pending)


def test_report_gate_cannot_be_replaced_with_public_self_hashed_pass_rows() -> None:
    gate = _make_report_gate()
    with pytest.raises(AttributeError):
        object.__setattr__(gate._factory_seal, "receipt_sha256", "b" * 64)
    with pytest.raises(TypeError):
        pickle.loads(pickle.dumps(gate._factory_seal))
    forged_rows = tuple(
        replace(
            row,
            correctness="PASS",
            completeness="PASS",
            review_reason_codes=(),
        )
        for row in gate.rows
    )
    forged_payload = {
        **admission_119._schema67_report_gate_payload(gate),
        "status": "READY",
        "rows": tuple(admission_119._schema67_report_gate_row_payload(row) for row in forged_rows),
        "wiki_admission_allowed": True,
        "publishable_field_ids": ORDERED_FIELD_IDS,
    }
    forged_hash = canonical_hash("schema67-lane-c-report-gate.v1", forged_payload)

    with pytest.raises(ValueError, match="LANE_C_REPORT_GATE_SEAL_INVALID"):
        replace(
            gate,
            status="READY",
            rows=forged_rows,
            wiki_admission_allowed=True,
            publishable_field_ids=ORDERED_FIELD_IDS,
            gate_receipt_sha256=forged_hash,
        )


def test_candidate_self_hash_cannot_replace_accepted_task_outputs() -> None:
    cases = _approved_cases()
    candidate = _candidate_v2(cases)
    field_id = next(item for item in ORDERED_FIELD_IDS if item not in FIXED_UNKNOWN_FIELD_IDS)
    original = next(item for item in candidate.fields if item.field_id == field_id)
    forged_output = original.model_copy(update={"value_snapshot": "forged value"})
    matching_case = next(case for case in cases if case.field_output.field_id == field_id)
    forged_receipt = bind_freeform_arm_evidence(
        field_output=forged_output,
        documents=matching_case.documents,
        manifests=matching_case.manifests,
    )
    target_execution = next(
        item
        for item in candidate.batch_execution.executions
        if field_id in tuple(output.field_id for output in item.final_outputs)
    )
    forged_outputs = tuple(
        forged_output if item.field_id == field_id else item
        for item in target_execution.final_outputs
    )
    forged_task_receipts = tuple(
        forged_receipt if item.field_id == field_id else item
        for item in target_execution.evidence_receipts
    )
    object.__setattr__(target_execution, "final_outputs", forged_outputs)
    object.__setattr__(target_execution, "evidence_receipts", forged_task_receipts)
    forged_payload = admission_119._schema67_candidate_v2_payload(
        candidate_tree_sha1=candidate.candidate_tree_sha1,
        field_contract_set_sha256=candidate.field_contract_set_sha256,
        execution_plan=candidate.execution_plan,
        prepared_tasks=candidate.prepared_tasks,
        batch_execution=candidate.batch_execution,
    )
    object.__setattr__(
        candidate,
        "candidate_sha256",
        canonical_hash("schema67-candidate.v2", forged_payload),
    )
    forged_cases = tuple(
        case.model_copy(
            update={
                "field_output": case.field_output.model_copy(
                    update={"value_snapshot": "forged value"}
                )
            }
        )
        if case.field_output.field_id == field_id
        else case
        for case in cases
    )

    with pytest.raises(
        admission_119.LaneCReportGateError,
        match="CANDIDATE_V2_CUSTODY_INVALID",
    ):
        admission_119.make_total_control_schema67_report_gate(
            snapshot=_authority_snapshot(),
            candidate=candidate,
            evidence_cases=forged_cases,
            frozen_candidate_bundle_sha256=candidate_evidence_bundle_sha256(
                candidate.fields, forged_cases
            ),
            receipt=_receipt(),
            observed_at=NOW,
            comparator=_AuthorityComparator(),
        )


def test_report_gate_seals_evidence_failure_without_calling_comparator() -> None:
    cases = _approved_cases()
    original = cases[0]
    replay_cases = (
        original.model_copy(update={"documents": (), "manifests": ()}),
        *cases[1:],
    )
    candidate = _candidate_v2(cases)
    comparator = _approved_comparator()

    gate = admission_119.make_total_control_schema67_report_gate(
        snapshot=_authority_snapshot(),
        candidate=candidate,
        evidence_cases=replay_cases,
        frozen_candidate_bundle_sha256=candidate_evidence_bundle_sha256(
            candidate.fields, replay_cases
        ),
        receipt=_receipt(),
        observed_at=NOW,
        comparator=comparator,
    )

    failed = next(row for row in gate.rows if row.field_id == original.field_output.field_id)
    assert gate.status == "BLOCKED"
    assert gate.semantic_eval_allowed is False
    assert gate.wiki_admission_allowed is False
    assert gate.publishable_field_ids == ()
    assert failed.evidence_057_status == "BLOCKED"
    assert failed.correctness == "FAIL"
    assert failed.completeness == "FAIL"


def test_semantic_gate_rejects_synthetic_known_values_and_keeps_unknowns_pending() -> None:
    comparator = _approved_comparator()

    first = _evaluate_semantic(comparator)
    second = _evaluate_semantic(_approved_comparator())

    evaluations = {item.field_id: item for item in first.field_evaluations}
    assert first.status == "SEMANTIC_REVIEW_REQUIRED"
    assert first.semantic_eval_allowed is True
    assert first.wiki_admission_allowed is False
    assert first.publishable_field_ids == ()
    assert len(first.field_evaluations) == 67
    assert all(
        evaluations[field_id].correctness == "PENDING"
        and evaluations[field_id].completeness == "PENDING"
        and evaluations[field_id].state_consistent is None
        and evaluations[field_id].review_reason_codes == ("SEMANTIC_UNKNOWN_PENDING",)
        for field_id in FIXED_UNKNOWN_FIELD_IDS
    )
    assert all(
        evaluations[field_id].correctness == "FAIL"
        and evaluations[field_id].state_consistent is True
        for field_id in ORDERED_FIELD_IDS
        if field_id not in FIXED_UNKNOWN_FIELD_IDS
    )
    absent = evaluations[EXPLICIT_ABSENCE_FIELD_ID]
    assert absent.correctness == "FAIL"
    assert first.evaluation_receipt_sha256 == second.evaluation_receipt_sha256
    assert first == second


def test_semantic_gate_blocks_before_comparator_when_known_evidence_fails() -> None:
    cases = _approved_cases()
    original = cases[0]
    evidence = original.field_output.evidence[0]
    foreign = "same-format but not bound to the parsed document"
    rejected = evidence.model_copy(
        update={
            "quote_snapshot": foreign,
            "quote_snapshot_sha256": _sha(foreign),
        }
    )
    rejected_case = original.model_copy(
        update={"field_output": original.field_output.model_copy(update={"evidence": (rejected,)})}
    )
    replay_cases = (rejected_case, *cases[1:])
    comparator = _approved_comparator()

    result = _evaluate_semantic(comparator, cases=replay_cases)

    failed = next(
        item for item in result.field_evaluations if item.field_id == original.field_output.field_id
    )
    assert result.status == "SEMANTIC_EVALUATION_BLOCKED"
    assert result.semantic_eval_allowed is False
    assert result.wiki_admission_allowed is False
    assert result.publishable_field_ids == ()
    assert failed.correctness == "FAIL"
    assert failed.completeness == "FAIL"
    assert failed.review_reason_codes == ("EVIDENCE_REPLAY_FAILED",)


def test_semantic_gate_rejects_caller_controlled_outcomes_and_reference_states() -> None:
    known = tuple(
        field_id
        for field_id in ORDERED_FIELD_IDS
        if field_id not in FIXED_UNKNOWN_FIELD_IDS and field_id != EXPLICIT_ABSENCE_FIELD_ID
    )
    value_drift, state_drift, evidence_gap = known[:3]
    comparator = _AuthorityComparator(
        outcomes={value_drift: "DIFFERENT"},
        reference_states={state_drift: "absent_explicitly"},
        required_sources={evidence_gap: ("b" * 64,)},
    )

    result = _evaluate_semantic(comparator)

    assert result.status == "SEMANTIC_EVALUATION_BLOCKED"
    assert result.reason_codes == ("SEMANTIC_COMPARATOR_AUTHORITY_INVALID",)
    assert result.field_evaluations == ()
    assert result.wiki_admission_allowed is False
    assert result.publishable_field_ids == ()


def test_semantic_gate_rejects_authority_or_comparison_hash_drift() -> None:
    authority_drift = _AuthorityComparator(authority=_semantic_authority(authority_sha256="f" * 64))
    comparison_drift = _AuthorityComparator(
        corrupt_field=next(
            field_id for field_id in ORDERED_FIELD_IDS if field_id not in FIXED_UNKNOWN_FIELD_IDS
        )
    )

    bad_authority = _evaluate_semantic(authority_drift)
    bad_comparison = _evaluate_semantic(comparison_drift)

    assert bad_authority.status == "SEMANTIC_EVALUATION_BLOCKED"
    assert bad_authority.reason_codes == ("SEMANTIC_COMPARATOR_AUTHORITY_INVALID",)
    assert authority_drift.calls == []
    assert bad_comparison.status == "SEMANTIC_EVALUATION_BLOCKED"
    assert bad_comparison.reason_codes == ("SEMANTIC_COMPARATOR_AUTHORITY_INVALID",)
    assert comparison_drift.calls == []
    assert bad_authority.wiki_admission_allowed is False
    assert bad_comparison.wiki_admission_allowed is False
    assert bad_authority.publishable_field_ids == ()
    assert bad_comparison.publishable_field_ids == ()


def test_semantic_gate_rejects_candidate_freeze_drift_before_comparator() -> None:
    comparator = _approved_comparator()

    result = _evaluate_semantic(
        comparator,
        frozen_candidate_bundle_sha256="0" * 64,
    )

    assert result.status == "SEMANTIC_EVALUATION_BLOCKED"
    assert result.reason_codes == ("CANDIDATE_FREEZE_IDENTITY_MISMATCH",)
    assert result.wiki_admission_allowed is False
    assert result.publishable_field_ids == ()
