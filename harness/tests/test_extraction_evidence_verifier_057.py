"""OpenSpec 057: deterministic Evidence verification and one targeted repair."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Literal

import pytest

import insurance_harness.compiler.evidence_verifier as evidence_verifier
from insurance_harness.compiler.evidence_verifier import (
    ApprovedLocatorSetV1,
    CandidateValueV1,
    EvidenceLocatorSnapshotV1,
    EvidenceSnapshotV1,
    EvidenceSupportScopeV1,
    FieldCandidateV1,
    FieldRuleV1,
    FreeformEvidenceBindingReceiptV1,
    FreeformEvidenceV1,
    FreeformFieldOutputV1,
    RepairBudgetV1,
    TargetedRepairPlanV1,
    VerificationBatchV1,
    VerifierContractError,
    apply_targeted_repair,
    bind_freeform_arm_evidence,
    plan_targeted_repair,
    replay_freeform_arm_evidence_binding,
    value_snapshot,
    verify_evidence_batch,
)
from insurance_harness.compiler.extraction_receipts import (
    FieldOutcomeV1,
    ReceiptChainV1,
    build_attempt_receipt,
    build_initial_attempt,
)
from insurance_harness.compiler.extraction_tasks import (
    ArtifactRefV1,
    AttemptBudgetV1,
    ExtractionInputRefsV1,
    ExtractionTaskV1,
    build_extraction_task,
    build_extraction_task_profile,
)
from insurance_harness.compiler.material_profiles import (
    MATERIAL_PROFILE_BINDING_OBJECT_TYPE,
    ApprovedParsePolicy,
    FieldAuthority,
    MaterialProfile,
    ParsePolicyReceipt,
    SourceDocumentIdentity,
)
from insurance_harness.compiler.parsed_documents import (
    BlockLocatorV1,
    CellLocatorV1,
    PageLocatorV1,
    ParseAttemptV1,
    ParseBlockV1,
    ParseCellV1,
    ParsedDocumentV1,
    ParseManifestV1,
    ParseOutputFactsV1,
    ParsePageV1,
    ParserIdentityV1,
    ParseSnapshotV1,
    ParseSubjectV1,
    ParseTableV1,
    TableLocatorV1,
    build_parse_manifest,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _value(kind: str, **updates: object) -> CandidateValueV1:
    return CandidateValueV1.model_validate({"kind": kind, **updates})


def _document(
    *,
    document_index: int = 1,
    source_name: str = "terms",
    source_revision_id: str = "revision-057",
    source_sha256: str = "a" * 64,
    material_role: Literal["terms", "brochure", "rate_table"] = "terms",
    profile_id: str = "profile-terms-596-1",
    header_text: str | None = None,
    cell_text: str = (
        "10000CNY 12.5 90day 90month 门诊+住院 2026-02-29 2024-02-290 "
        "1..100 10..1 -10 -10CNY -1..10 10+20=30 10+20=31 不设年度免赔额"
    ),
) -> tuple[ParsedDocumentV1, ParseManifestV1, dict[str, str]]:
    page_id = f"page-{document_index}"
    block_id = f"block-{document_index}"
    table_id = f"table-{document_index}"
    cell_id = f"cell-{document_index}"
    header_cell_id = f"header-cell-{document_index}"
    page_text = "本产品596-1在标准条件下，住院医疗年度免赔额为10000元。"
    block_text = "标准条件适用于596-1。"
    table_text = "年度免赔额"
    document = ParsedDocumentV1(
        contract="parsed-document.v1",
        subject=ParseSubjectV1(
            space_id="space-057",
            source_id=f"source-{source_name}",
            source_revision_id=source_revision_id,
            product_version_id="596-1",
            material_profile_id=profile_id,
            material_profile_binding_hash="b" * 64,
            source_sha256=source_sha256,
            raw_artifact_hash="c" * 64,
            canonical_envelope_hash="d" * 64,
        ),
        parser=ParserIdentityV1(
            parser_id="parser-neutral-fixture",
            parser_profile_ref="approved-parser-profile:parser-neutral-default.v1",
            parser_build_id="build-v1",
            parser_config_hash="e" * 64,
        ),
        attempt=ParseAttemptV1(
            attempt_id="parse-attempt-1",
            attempt_number=1,
            attempt_role="default",
            generation=1,
        ),
        snapshot=ParseSnapshotV1(
            snapshot_id="snapshot-057",
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
                page_id=page_id,
                order_index=0,
                locator=PageLocatorV1(page_number=1),
                content_hash=_sha(page_text),
                structure_hash="1" * 64,
            ),
        ),
        blocks=(
            ParseBlockV1(
                block_id=block_id,
                order_index=0,
                locator=BlockLocatorV1(
                    page_number=1,
                    block_index=0,
                    bbox=(Decimal(0), Decimal(0), Decimal(10), Decimal(10)),
                ),
                content_hash=_sha(block_text),
                structure_hash="2" * 64,
            ),
        ),
        tables=(
            ParseTableV1(
                table_id=table_id,
                order_index=0,
                locator=TableLocatorV1(
                    page_number=1,
                    table_index=0,
                    bbox=(Decimal(0), Decimal(10), Decimal(30), Decimal(30)),
                ),
                content_hash=_sha(table_text),
                structure_hash="3" * 64,
                row_count=2 if header_text is not None else 1,
                column_count=1,
                header_cell_ids=(header_cell_id,) if header_text is not None else (),
                continuation_table_ids=(),
            ),
        ),
        cells=(
            *(
                (
                    ParseCellV1(
                        cell_id=header_cell_id,
                        order_index=0,
                        table_id=table_id,
                        locator=CellLocatorV1(
                            page_number=1,
                            table_id=table_id,
                            row_index=0,
                            column_index=0,
                            row_span=1,
                            column_span=1,
                            bbox=(Decimal(0), Decimal(10), Decimal(10), Decimal(20)),
                        ),
                        content_hash=_sha(header_text),
                        structure_hash="5" * 64,
                    ),
                )
                if header_text is not None
                else ()
            ),
            ParseCellV1(
                cell_id=cell_id,
                order_index=1 if header_text is not None else 0,
                table_id=table_id,
                locator=CellLocatorV1(
                    page_number=1,
                    table_id=table_id,
                    row_index=1 if header_text is not None else 0,
                    column_index=0,
                    row_span=1,
                    column_span=1,
                    bbox=(Decimal(0), Decimal(10), Decimal(10), Decimal(20)),
                ),
                content_hash=_sha(cell_text),
                structure_hash="4" * 64,
            ),
        ),
        capability_evidence=(),
        warnings=(),
        unsupported=(),
    )
    profile = MaterialProfile(
        profile_id=profile_id,
        material_role=material_role,
        source=SourceDocumentIdentity(
            name=f"{source_name}.pdf",
            path=f"dataset/{source_name}.pdf",
            size=1,
            sha256=source_sha256,
        ),
        document_type_id="insurance-terms",
        required_parse_capabilities=("ordered_pages",),
        parse_policy=ApprovedParsePolicy(
            policy_id="policy-057",
            policy_version="v1",
            material_profile_id=profile_id,
            default_parser_profile_ref="approved-parser-profile:parser-neutral-default.v1",
            bounded_upgrade_profile_ref=None,
            upgrade_trigger_conditions=(),
            max_parser_attempts=1,
            privacy_policy_ref="privacy-policy:internal.v1",
            output_policy_ref="output-policy:internal.v1",
        ),
    )
    # 057 verifies identity and structure, not 053 quality admission. The profile
    # capability is intentionally unsatisfied so no caller can infer ADMIT here.
    manifest = build_parse_manifest(document, profile)
    return (
        document,
        manifest,
        {
            page_id: page_text,
            block_id: block_text,
            table_id: table_text,
            cell_id: cell_text,
            **({header_cell_id: header_text} if header_text is not None else {}),
        },
    )


def _locator(
    *,
    ref: str = "cell-1",
    kind: str = "cell",
    parents: tuple[str, ...] = ("page-1", "table-1"),
    content: str = (
        "10000CNY 12.5 90day 90month 门诊+住院 2026-02-29 2024-02-290 "
        "1..100 10..1 -10 -10CNY -1..10 10+20=30 10+20=31 不设年度免赔额"
    ),
) -> EvidenceLocatorSnapshotV1:
    return EvidenceLocatorSnapshotV1.model_validate(
        {
            "subject_type": kind,
            "subject_ref": ref,
            "page_number": 1,
            "parent_refs": parents,
            "content_snapshot": content,
            "content_snapshot_sha256": _sha(content),
        }
    )


def _candidate(
    *,
    field_id: str = "annual_deductible",
    value: CandidateValueV1 | None = None,
    tri_state: str = "present",
    locator: EvidenceLocatorSnapshotV1 | None = None,
    quote: str | None = None,
    product_version_id: str = "596-1",
    supported_product_version_id: str = "596-1",
    subject_id: str = "annual_deductible",
    supported_subject_id: str = "annual_deductible",
    condition_ids: tuple[str, ...] = ("standard",),
    supported_condition_ids: tuple[str, ...] = ("standard",),
) -> FieldCandidateV1:
    document, manifest, _ = _document()
    actual_value = value or _value("number_unit", number="10000", unit="CNY")
    if quote is None:
        if actual_value.kind == "number":
            quote = str(actual_value.number)
        elif actual_value.kind == "number_unit":
            quote = f"{actual_value.number}{actual_value.unit}"
        elif actual_value.kind == "enum":
            quote = actual_value.enum_value
        elif actual_value.kind == "date":
            quote = actual_value.date_value
        elif actual_value.kind == "range":
            quote = f"{actual_value.lower}..{actual_value.upper}"
        else:
            operator = "+" if actual_value.operator == "sum" else "-"
            quote = (
                operator.join(str(item) for item in actual_value.operands)
                + f"={actual_value.result}"
            )
        assert quote is not None
    snapshot = value_snapshot(actual_value if tri_state == "present" else None)
    evidence: tuple[EvidenceSnapshotV1, ...] = ()
    if tri_state != "unknown":
        evidence = (
            EvidenceSnapshotV1(
                field_id=field_id,
                product_version_id=product_version_id,
                source_revision_id=document.subject.source_revision_id,
                parse_attempt_id=document.attempt.attempt_id,
                parsed_document_hash=document.document_hash,
                parse_manifest_hash=manifest.manifest_hash,
                locator=locator or _locator(),
                quote_snapshot=quote,
                quote_snapshot_sha256=_sha(quote),
                value_snapshot=snapshot,
                value_snapshot_sha256=_sha(snapshot),
                support_scope=EvidenceSupportScopeV1(
                    product_version_id=supported_product_version_id,
                    subject_id=supported_subject_id,
                    condition_ids=supported_condition_ids,
                ),
            ),
        )
    return FieldCandidateV1.model_validate(
        {
            "field_id": field_id,
            "product_version_id": product_version_id,
            "subject_id": subject_id,
            "condition_ids": condition_ids,
            "tri_state": tri_state,
            "value": actual_value if tri_state == "present" else None,
            "evidence": evidence,
        }
    )


def _verify(candidate: FieldCandidateV1, rule: FieldRuleV1) -> VerificationBatchV1:
    document, manifest, _ = _document()
    return verify_evidence_batch(
        document=document,
        manifest=manifest,
        candidates=(candidate,),
        rules=(rule,),
    )


def test_exact_cell_evidence_binds_document_and_parent_chain() -> None:
    candidate = _candidate()
    rule = FieldRuleV1(
        field_id=candidate.field_id,
        value_kind="number_unit",
        expected_unit="CNY",
        minimum=Decimal("0"),
        maximum=Decimal("100000"),
        allow_absent=False,
    )

    verified = _verify(candidate, rule)
    assert verified.results[0].status == "PASS"
    assert verified.results[0].reason_codes == ()

    wrong_kind = _candidate(locator=_locator(kind="page"))
    assert _verify(wrong_kind, rule).results[0].reason_codes == ("locator_kind_mismatch",)

    wrong_parent = _candidate(locator=_locator(parents=("page-1", "table-x")))
    assert _verify(wrong_parent, rule).results[0].reason_codes == ("locator_parent_mismatch",)


@pytest.mark.parametrize(
    (
        "supported_product_version_id",
        "supported_subject_id",
        "supported_condition_ids",
        "reason",
    ),
    [
        ("596-2", "annual_deductible", ("standard",), "semantic_version_mismatch"),
        ("596-1", "waiting_period", ("standard",), "semantic_subject_mismatch"),
        ("596-1", "annual_deductible", ("special",), "semantic_condition_mismatch"),
    ],
)
def test_quote_hit_does_not_override_semantic_scope(
    supported_product_version_id: str,
    supported_subject_id: str,
    supported_condition_ids: tuple[str, ...],
    reason: str,
) -> None:
    candidate = _candidate(
        supported_product_version_id=supported_product_version_id,
        supported_subject_id=supported_subject_id,
        supported_condition_ids=supported_condition_ids,
    )
    result = _verify(
        candidate,
        FieldRuleV1(
            field_id=candidate.field_id,
            value_kind="number_unit",
            expected_unit="CNY",
            allow_absent=False,
        ),
    ).results[0]

    assert result.reason_codes == (reason,)


def test_exact_source_attempt_document_and_manifest_identity_cannot_drift() -> None:
    candidate = _candidate()
    evidence = candidate.evidence[0]
    rule = FieldRuleV1(
        field_id=candidate.field_id,
        value_kind="number_unit",
        expected_unit="CNY",
        allow_absent=False,
    )
    for update in (
        {"source_revision_id": "revision-other"},
        {"parse_attempt_id": "attempt-other"},
        {"parsed_document_hash": "0" * 64},
        {"parse_manifest_hash": "1" * 64},
    ):
        drifted = candidate.model_copy(update={"evidence": (evidence.model_copy(update=update),)})
        assert _verify(drifted, rule).results[0].reason_codes == ("evidence_identity_mismatch",)


def test_matching_quote_must_contain_the_candidate_value_snapshot() -> None:
    candidate = _candidate(quote="90day")
    result = _verify(
        candidate,
        FieldRuleV1(
            field_id=candidate.field_id,
            value_kind="number_unit",
            expected_unit="CNY",
            allow_absent=False,
        ),
    ).results[0]

    assert result.reason_codes == ("value_not_supported_by_quote",)
    assert result.reason_codes == ("value_not_supported_by_quote",)


@pytest.mark.parametrize(
    ("value", "rule", "passes"),
    [
        (_value("number", number="12.5"), {"value_kind": "number"}, True),
        (
            _value("number_unit", number="90", unit="day"),
            {"value_kind": "number_unit", "expected_unit": "day"},
            True,
        ),
        (
            _value("number_unit", number="90", unit="month"),
            {"value_kind": "number_unit", "expected_unit": "day"},
            False,
        ),
        (
            _value("enum", enum_value="门诊+住院"),
            {"value_kind": "enum", "allowed_values": ("门诊+住院",)},
            True,
        ),
        (
            _value("date", date_value="2026-02-29"),
            {"value_kind": "date"},
            False,
        ),
        (
            _value("range", lower="10", upper="1"),
            {"value_kind": "range"},
            False,
        ),
        (
            _value(
                "arithmetic",
                operator="sum",
                operands=("10", "20"),
                result="30",
            ),
            {"value_kind": "arithmetic"},
            True,
        ),
        (
            _value(
                "arithmetic",
                operator="sum",
                operands=("10", "20"),
                result="31",
            ),
            {"value_kind": "arithmetic"},
            False,
        ),
    ],
)
def test_fixed_value_rule_families_are_deterministic(
    value: CandidateValueV1, rule: dict[str, object], passes: bool
) -> None:
    candidate = _candidate(value=value)
    result = _verify(
        candidate,
        FieldRuleV1.model_validate({"field_id": candidate.field_id, "allow_absent": False, **rule}),
    ).results[0]
    assert (result.status == "PASS") is passes


def test_numeric_value_support_is_atomic_not_a_substring() -> None:
    substring_number = _candidate(
        value=_value("number", number="10"),
        quote="10000CNY",
    )
    number_result = _verify(
        substring_number,
        FieldRuleV1(
            field_id=substring_number.field_id,
            value_kind="number",
            allow_absent=False,
        ),
    ).results[0]
    assert number_result.reason_codes == ("value_not_supported_by_quote",)


@pytest.mark.parametrize(
    ("value", "quote", "rule"),
    [
        (
            _value("number_unit", number="10", unit="CNY"),
            "10000CNY",
            {"value_kind": "number_unit", "expected_unit": "CNY"},
        ),
        (
            _value("enum", enum_value="住院"),
            "门诊+住院",
            {"value_kind": "enum", "allowed_values": ("住院",)},
        ),
        (
            _value("date", date_value="2024-02-29"),
            "2024-02-290",
            {"value_kind": "date"},
        ),
        (
            _value("range", lower="1", upper="10"),
            "1..100",
            {"value_kind": "range"},
        ),
    ],
)
def test_fixed_value_atoms_reject_larger_tokens(
    value: CandidateValueV1,
    quote: str,
    rule: dict[str, object],
) -> None:
    candidate = _candidate(value=value, quote=quote)
    result = _verify(
        candidate,
        FieldRuleV1.model_validate(
            {"field_id": candidate.field_id, "allow_absent": False, **rule}
        ),
    ).results[0]
    assert result.status == "FAIL"


@pytest.mark.parametrize(
    ("value", "quote", "rule"),
    [
        (_value("number", number="10"), "-10", {"value_kind": "number"}),
        (
            _value("number_unit", number="10", unit="CNY"),
            "-10CNY",
            {"value_kind": "number_unit", "expected_unit": "CNY"},
        ),
        (
            _value("range", lower="1", upper="10"),
            "-1..10",
            {"value_kind": "range"},
        ),
    ],
)
def test_positive_atoms_do_not_match_negative_quotes(
    value: CandidateValueV1,
    quote: str,
    rule: dict[str, object],
) -> None:
    candidate = _candidate(value=value, quote=quote)
    result = _verify(
        candidate,
        FieldRuleV1.model_validate(
            {"field_id": candidate.field_id, "allow_absent": False, **rule}
        ),
    ).results[0]
    assert result.reason_codes == ("value_not_supported_by_quote",)


@pytest.mark.parametrize(
    ("value", "quote", "rule"),
    [
        (_value("number", number="-10"), "-10", {"value_kind": "number"}),
        (
            _value("number_unit", number="-10", unit="CNY"),
            "-10CNY",
            {"value_kind": "number_unit", "expected_unit": "CNY"},
        ),
        (
            _value("range", lower="-1", upper="10"),
            "-1..10",
            {"value_kind": "range"},
        ),
    ],
)
def test_negative_atoms_still_match_their_exact_signed_quotes(
    value: CandidateValueV1,
    quote: str,
    rule: dict[str, object],
) -> None:
    candidate = _candidate(value=value, quote=quote)
    result = _verify(
        candidate,
        FieldRuleV1.model_validate(
            {"field_id": candidate.field_id, "allow_absent": False, **rule}
        ),
    ).results[0]
    assert result.status == "PASS"


def test_range_rule_enforces_both_bounds() -> None:
    outside_range = _candidate(
        value=_value("range", lower="1", upper="100"),
        quote="1..100",
    )
    range_result = _verify(
        outside_range,
        FieldRuleV1(
            field_id=outside_range.field_id,
            value_kind="range",
            minimum=Decimal("10"),
            maximum=Decimal("20"),
            allow_absent=False,
        ),
    ).results[0]
    assert range_result.reason_codes == ("range_out_of_bounds",)


def test_unknown_is_gap_and_absent_requires_exact_evidence() -> None:
    rule = FieldRuleV1(
        field_id="annual_deductible",
        value_kind="number_unit",
        expected_unit="CNY",
        absence_markers=("不设年度免赔额",),
        allow_absent=True,
    )
    unknown = _candidate(tri_state="unknown")
    unknown_result = _verify(unknown, rule).results[0]
    assert (unknown_result.status, unknown_result.reason_codes) == (
        "GAP",
        ("unknown_value",),
    )

    absent = _candidate(tri_state="absent_explicitly", quote="不设置年度免赔额")
    # The quote is not present in the bound cell snapshot; explicit absence is
    # therefore not silently accepted.
    absent_result = _verify(absent, rule).results[0]
    assert absent_result.status == "FAIL"
    assert absent_result.reason_codes == ("quote_not_found",)

    without_evidence = absent.model_copy(update={"evidence": ()})
    missing = _verify(without_evidence, rule).results[0]
    assert (missing.status, missing.reason_codes) == (
        "FAIL",
        ("absence_evidence_missing",),
    )

    positive_quote = _candidate(tri_state="absent_explicitly", quote="10000CNY")
    unsupported_absence = _verify(positive_quote, rule).results[0]
    assert unsupported_absence.reason_codes == ("absence_semantics_missing",)

    explicit_absence = _candidate(
        tri_state="absent_explicitly",
        quote="不设年度免赔额",
    )
    assert _verify(explicit_absence, rule).results[0].status == "PASS"


def test_targeted_repair_is_failed_fields_only_and_exhausts_once() -> None:
    passed = _candidate(field_id="annual_deductible")
    failed = _candidate(
        field_id="waiting_period",
        subject_id="waiting_period",
        supported_subject_id="other_subject",
    )
    rules = (
        FieldRuleV1(
            field_id="annual_deductible",
            value_kind="number_unit",
            expected_unit="CNY",
            allow_absent=False,
        ),
        FieldRuleV1(
            field_id="waiting_period",
            value_kind="number_unit",
            expected_unit="CNY",
            allow_absent=False,
        ),
    )
    document, manifest, _ = _document()
    initial = verify_evidence_batch(
        document=document,
        manifest=manifest,
        candidates=(passed, failed),
        rules=rules,
    )
    decision = plan_targeted_repair(
        initial,
        approved_locators=(
            ApprovedLocatorSetV1(field_id="waiting_period", locator_refs=("cell-1",)),
        ),
        budget=RepairBudgetV1(max_targeted_repairs=1),
        repairs_used=0,
    )

    assert decision.outcome == "REPAIR"
    assert decision.plan is not None
    assert decision.plan.field_ids == ("waiting_period",)

    with pytest.raises(VerifierContractError, match="repair_field_scope_mismatch"):
        apply_targeted_repair(
            document=document,
            manifest=manifest,
            initial=initial,
            plan=decision.plan,
            repaired_candidates=(passed,),
            rules=rules,
        )

    repaired = _candidate(
        field_id="waiting_period",
        subject_id="waiting_period",
        supported_subject_id="waiting_period",
    )
    resolution = apply_targeted_repair(
        document=document,
        manifest=manifest,
        initial=initial,
        plan=decision.plan,
        repaired_candidates=(repaired,),
        rules=rules,
    )
    assert tuple((item.field_id, item.status) for item in resolution.results) == (
        ("annual_deductible", "PASS"),
        ("waiting_period", "PASS"),
    )
    assert resolution.gaps == ()
    assert resolution.review_items == ()

    exhausted = plan_targeted_repair(
        initial,
        approved_locators=(
            ApprovedLocatorSetV1(field_id="waiting_period", locator_refs=("cell-1",)),
        ),
        budget=RepairBudgetV1(max_targeted_repairs=1),
        repairs_used=1,
    )
    assert exhausted.outcome == "EXHAUSTED"
    assert exhausted.plan is None
    assert exhausted.gaps[0].field_id == "waiting_period"
    assert exhausted.review_items[0].reason_code == "repair_budget_exhausted"


def test_targeted_repair_rejects_input_custody_drift_before_merging() -> None:
    passed = _candidate(field_id="annual_deductible")
    failed = _candidate(
        field_id="waiting_period",
        subject_id="waiting_period",
        supported_subject_id="other_subject",
    )
    rules = tuple(
        FieldRuleV1(
            field_id=field_id,
            value_kind="number_unit",
            expected_unit="CNY",
            allow_absent=False,
        )
        for field_id in ("annual_deductible", "waiting_period")
    )
    document, manifest, _ = _document()
    initial = verify_evidence_batch(
        document=document,
        manifest=manifest,
        candidates=(passed, failed),
        rules=rules,
    )
    decision = plan_targeted_repair(
        initial,
        approved_locators=(
            ApprovedLocatorSetV1(field_id="waiting_period", locator_refs=("cell-1",)),
        ),
        budget=RepairBudgetV1(max_targeted_repairs=1),
        repairs_used=0,
    )
    assert decision.plan is not None
    repaired = _candidate(
        field_id="waiting_period",
        subject_id="waiting_period",
        supported_subject_id="waiting_period",
    )
    drifted_document = document.model_copy(
        update={
            "subject": document.subject.model_copy(
                update={"product_version_id": "596-2"}
            )
        }
    )
    drifted_manifest = manifest.model_copy(
        update={
            "subject": manifest.subject.model_copy(
                update={"product_version_id": "596-2"}
            ),
            "document_hash": drifted_document.document_hash,
        }
    )

    before = initial.results
    with pytest.raises(VerifierContractError, match="repair_input_custody_mismatch"):
        apply_targeted_repair(
            document=drifted_document,
            manifest=drifted_manifest,
            initial=initial,
            plan=decision.plan,
            repaired_candidates=(repaired,),
            rules=rules,
        )
    assert initial.results == before


def test_manual_repair_plan_must_cover_every_failure_and_real_locators() -> None:
    first = _candidate(
        field_id="waiting_period",
        subject_id="waiting_period",
        supported_subject_id="other_subject",
    )
    second = _candidate(
        field_id="coverage_scope",
        subject_id="coverage_scope",
        supported_subject_id="other_subject",
    )
    rules = tuple(
        FieldRuleV1(
            field_id=field_id,
            value_kind="number_unit",
            expected_unit="CNY",
            allow_absent=False,
        )
        for field_id in ("coverage_scope", "waiting_period")
    )
    document, manifest, _ = _document()
    initial = verify_evidence_batch(
        document=document,
        manifest=manifest,
        candidates=(second, first),
        rules=rules,
    )
    incomplete = TargetedRepairPlanV1(
        contract="targeted-repair-plan.v1",
        parent_verification_hash=initial.verification_hash,
        repair_number=1,
        field_ids=("waiting_period",),
        approved_locators=(
            ApprovedLocatorSetV1(field_id="waiting_period", locator_refs=("cell-1",)),
        ),
    )
    repaired = _candidate(
        field_id="waiting_period",
        subject_id="waiting_period",
        supported_subject_id="waiting_period",
    )
    with pytest.raises(VerifierContractError, match="repair_plan_incomplete"):
        apply_targeted_repair(
            document=document,
            manifest=manifest,
            initial=initial,
            plan=incomplete,
            repaired_candidates=(repaired,),
            rules=rules,
        )

    invalid_locator_plan = TargetedRepairPlanV1(
        contract="targeted-repair-plan.v1",
        parent_verification_hash=initial.verification_hash,
        repair_number=1,
        field_ids=("coverage_scope", "waiting_period"),
        approved_locators=(
            ApprovedLocatorSetV1(
                field_id="coverage_scope", locator_refs=("cell-missing",)
            ),
            ApprovedLocatorSetV1(field_id="waiting_period", locator_refs=("cell-1",)),
        ),
    )
    repaired_second = _candidate(
        field_id="coverage_scope",
        subject_id="coverage_scope",
        supported_subject_id="coverage_scope",
        tri_state="unknown",
    )
    with pytest.raises(VerifierContractError, match="repair_plan_locator_invalid"):
        apply_targeted_repair(
            document=document,
            manifest=manifest,
            initial=initial,
            plan=invalid_locator_plan,
            repaired_candidates=(repaired_second, repaired),
            rules=rules,
        )


def _task_for_verification(
    verification: VerificationBatchV1,
) -> ExtractionTaskV1:
    field_ids = tuple(item.field_id for item in verification.results)
    budget = AttemptBudgetV1(
        max_fields=len(field_ids),
        max_total_attempts=2,
        max_targeted_repairs=1,
    )
    material_profile = MaterialProfile(
        profile_id="profile-terms-596-1",
        material_role="terms",
        source=SourceDocumentIdentity(
            name="terms.pdf",
            path="dataset/terms.pdf",
            size=1,
            sha256="a" * 64,
        ),
        document_type_id="insurance-terms",
        required_parse_capabilities=("ordered_pages",),
        parse_policy=ApprovedParsePolicy(
            policy_id="policy-057",
            policy_version="v1",
            material_profile_id="profile-terms-596-1",
            default_parser_profile_ref=(
                "approved-parser-profile:parser-neutral-default.v1"
            ),
            bounded_upgrade_profile_ref=None,
            upgrade_trigger_conditions=(),
            max_parser_attempts=1,
            privacy_policy_ref="privacy-policy:internal.v1",
            output_policy_ref="output-policy:internal.v1",
        ),
    )
    parse_policy_receipt = ParsePolicyReceipt.model_validate(
        {
            **material_profile.parse_policy.model_dump(mode="python"),
            "required_parse_capabilities": material_profile.required_parse_capabilities,
        }
    )
    profile = build_extraction_task_profile(
        material_profile=material_profile,
        material_profile_binding_hash="b" * 64,
        parse_policy_receipt=parse_policy_receipt,
        field_authority=FieldAuthority(
            authority_class="contract_fact",
            primary_role="terms",
            support_roles=(),
            field_ids=field_ids,
        ),
        attempt_budget=budget,
    )
    inputs = ExtractionInputRefsV1(
        source_revision=ArtifactRefV1(
            object_type="source-revision.v1", artifact_hash="a" * 64
        ),
        material_profile=ArtifactRefV1(
            object_type=MATERIAL_PROFILE_BINDING_OBJECT_TYPE,
            artifact_hash="b" * 64,
        ),
        resolved_template=ArtifactRefV1(
            object_type="resolved-template.v1", artifact_hash="c" * 64
        ),
        schema_contract=ArtifactRefV1(
            object_type="schema-contract.v1", artifact_hash="d" * 64
        ),
        parsed_document=ArtifactRefV1(
            object_type="parsed-document.v1",
            artifact_hash=verification.parsed_document_hash,
        ),
        parse_manifest=ArtifactRefV1(
            object_type="parse-manifest.v1",
            artifact_hash=verification.parse_manifest_hash,
        ),
        parse_quality_decision=ArtifactRefV1(
            object_type="parse-quality-decision.v1", artifact_hash="1" * 64
        ),
    )
    return build_extraction_task(
        space_id="space-057",
        product_version_id=verification.product_version_id,
        source_revision_id=verification.source_revision_id,
        material_role="terms",
        module_id="evidence-verifier",
        risk_partition_id="contract-facts",
        field_ids=field_ids,
        input_refs=inputs,
        budget=budget,
        task_profile=profile,
    )


def test_054_exact_receipt_adapter_binds_real_dtos_without_copying_hashes() -> None:
    passed = _candidate(field_id="annual_deductible")
    failed = _candidate(
        field_id="waiting_period",
        subject_id="waiting_period",
        supported_subject_id="other_subject",
    )
    rules = tuple(
        FieldRuleV1(
            field_id=field_id,
            value_kind="number_unit",
            expected_unit="CNY",
            allow_absent=False,
        )
        for field_id in ("annual_deductible", "waiting_period")
    )
    document, manifest, _ = _document()
    verification = verify_evidence_batch(
        document=document,
        manifest=manifest,
        candidates=(passed, failed),
        rules=rules,
    )
    task = _task_for_verification(verification)
    attempt = build_initial_attempt(task)
    outcomes = tuple(
        FieldOutcomeV1(
            field_id=result.field_id,
            status="candidate" if result.status == "PASS" else "unknown",
            candidate_ref=(
                ArtifactRefV1(
                    object_type="verified-field-candidate.v1",
                    artifact_hash=result.candidate_snapshot_hash,
                )
                if result.status == "PASS"
                else None
            ),
            reason_code=None if result.status == "PASS" else result.reason_codes[0],
        )
        for result in verification.results
    )
    receipt = build_attempt_receipt(
        attempt,
        field_outcomes=outcomes,
        outcome="insufficient",
        reason_code="verification_fields_unresolved",
    )
    chain = ReceiptChainV1(
        task=task,
        task_hash=task.task_hash,
        receipts=(receipt,),
    )

    bound = evidence_verifier.bind_054_attempt_receipt(
        chain=chain,
        verification=verification,
    )
    assert type(bound) is type(receipt)
    assert bound == receipt
    assert bound.receipt_hash == receipt.receipt_hash
    with pytest.raises(VerifierContractError, match="verification_receipt_binding_mismatch"):
        evidence_verifier.bind_054_attempt_receipt(
            chain=chain,
            verification=verification.model_copy(
                update={"parsed_document_hash": "0" * 64}
            ),
        )


def test_value_snapshot_is_canonical_and_binary_float_is_rejected() -> None:
    left = _value("range", lower="1.00", upper="2.00")
    right = _value("range", lower="1.00", upper="2.00")
    assert value_snapshot(left) == value_snapshot(right)
    assert json.loads(value_snapshot(left))["kind"] == "range"

    with pytest.raises(ValueError, match="binary float"):
        CandidateValueV1.model_validate({"kind": "number", "number": 1.5})


def _freeform_evidence(
    *,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    contents: dict[str, str],
    field_id: str = "claim_filing_requirements",
    ref: str | None = None,
    quote: str | None = None,
) -> FreeformEvidenceV1:
    cell = document.cells[-1]
    subject_ref = ref or cell.cell_id
    content = contents[subject_ref]
    exact_quote = quote or content.split(" ", maxsplit=1)[0]
    return FreeformEvidenceV1(
        field_id=field_id,
        source_sha256=document.subject.source_sha256,
        source_revision_id=document.subject.source_revision_id,
        parse_attempt_id=document.attempt.attempt_id,
        parsed_document_hash=document.document_hash,
        parse_manifest_hash=manifest.manifest_hash,
        page_number=cell.locator.page_number,
        block_id=None,
        table_id=cell.table_id,
        cell_id=cell.cell_id,
        row_index=cell.locator.row_index,
        column_index=cell.locator.column_index,
        header_snapshot=None,
        row_span=cell.locator.row_span,
        column_span=cell.locator.column_span,
        locator=EvidenceLocatorSnapshotV1(
            subject_type="cell",
            subject_ref=subject_ref,
            page_number=cell.locator.page_number,
            parent_refs=(document.pages[0].page_id, cell.table_id),
            content_snapshot=content,
            content_snapshot_sha256=_sha(content),
        ),
        quote_snapshot=exact_quote,
        quote_snapshot_sha256=_sha(exact_quote),
    )


def _freeform_fixture() -> tuple[
    FreeformFieldOutputV1,
    tuple[ParsedDocumentV1, ...],
    tuple[ParseManifestV1, ...],
]:
    terms, terms_manifest, terms_contents = _document()
    brochure, brochure_manifest, brochure_contents = _document(
        document_index=2,
        source_name="brochure",
        source_revision_id="revision-064-brochure",
        source_sha256="9" * 64,
        material_role="brochure",
        profile_id="profile-brochure-596-1",
        cell_text="理赔时应提交完整申请材料，并可按要求补充证明。",
    )
    evidence = (
        _freeform_evidence(
            document=terms,
            manifest=terms_manifest,
            contents=terms_contents,
        ),
        _freeform_evidence(
            document=brochure,
            manifest=brochure_manifest,
            contents=brochure_contents,
        ),
    )
    output = FreeformFieldOutputV1(
        product_version_id="596-1",
        field_id="claim_filing_requirements",
        state="present",
        value_snapshot="申请人应提交理赔材料；具体清单由后续语义评分判断。",
        evidence=evidence,
    )
    return output, (terms, brochure), (terms_manifest, brochure_manifest)


def test_freeform_multi_source_receipt_is_replayable_without_semantic_judgment() -> None:
    output, documents, manifests = _freeform_fixture()

    receipt = bind_freeform_arm_evidence(
        field_output=output,
        documents=documents,
        manifests=manifests,
    )

    assert receipt.field_id == output.field_id
    assert receipt.value_snapshot == output.value_snapshot
    assert tuple(item.parsed_document_hash for item in receipt.documents) == tuple(
        item.document_hash for item in documents
    )
    assert replay_freeform_arm_evidence_binding(
        receipt=receipt,
        documents=documents,
        manifests=manifests,
    ) == receipt
    assert bind_freeform_arm_evidence(
        field_output=output,
        documents=documents,
        manifests=manifests,
    ).receipt_hash == receipt.receipt_hash


@pytest.mark.parametrize(
    ("ref", "kind", "parents"),
    [
        ("page-1", "page", ()),
        ("block-1", "block", ("page-1",)),
        ("table-1", "table", ("page-1",)),
        ("cell-1", "cell", ("page-1", "table-1")),
    ],
)
def test_freeform_page_block_table_and_cell_locators_bind(
    ref: str,
    kind: Literal["page", "block", "table", "cell"],
    parents: tuple[str, ...],
) -> None:
    document, manifest, contents = _document()
    content = contents[ref]
    evidence = _freeform_evidence(
        document=document,
        manifest=manifest,
        contents=contents,
    ).model_copy(
        update={
            "block_id": ref if kind == "block" else None,
            "table_id": (
                parents[-1] if kind == "cell" else ref if kind == "table" else None
            ),
            "cell_id": ref if kind == "cell" else None,
            "row_index": 0 if kind == "cell" else None,
            "column_index": 0 if kind == "cell" else None,
            "row_span": 1 if kind == "cell" else None,
            "column_span": 1 if kind == "cell" else None,
            "locator": EvidenceLocatorSnapshotV1(
                subject_type=kind,
                subject_ref=ref,
                page_number=1,
                parent_refs=parents,
                content_snapshot=content,
                content_snapshot_sha256=_sha(content),
            ),
            "quote_snapshot": content,
            "quote_snapshot_sha256": _sha(content),
        }
    )
    output = FreeformFieldOutputV1(
        product_version_id="596-1",
        field_id=evidence.field_id,
        state="present",
        value_snapshot="自由文本语义值不需要逐字出现在 quote 中。",
        evidence=(evidence,),
    )

    assert bind_freeform_arm_evidence(
        field_output=output,
        documents=(document,),
        manifests=(manifest,),
    ).evidence == (evidence,)


def test_freeform_rate_locator_replays_all_arm_structure_and_header() -> None:
    document, manifest, contents = _document(
        document_index=3,
        source_name="rate",
        source_revision_id="revision-064-rate",
        source_sha256="8" * 64,
        material_role="rate_table",
        profile_id="profile-rate-596-1",
        header_text="年龄",
        cell_text="30岁对应费率为0.12。",
    )
    evidence = _freeform_evidence(
        document=document,
        manifest=manifest,
        contents=contents,
        field_id="zh_7fe8603c08",
        quote="0.12",
    ).model_copy(
        update={
            "block_id": document.blocks[0].block_id,
            "header_snapshot": "年龄",
        }
    )
    output = FreeformFieldOutputV1(
        product_version_id="596-1",
        field_id=evidence.field_id,
        state="present",
        value_snapshot="0.12",
        evidence=(evidence,),
    )
    receipt = bind_freeform_arm_evidence(
        field_output=output,
        documents=(document,),
        manifests=(manifest,),
    )

    assert receipt.evidence == (evidence,)
    assert replay_freeform_arm_evidence_binding(
        receipt=receipt,
        documents=(document,),
        manifests=(manifest,),
    ) == receipt


@pytest.mark.parametrize(
    "update",
    [
        {"source_sha256": "0" * 64},
        {"page_number": 2},
        {"block_id": "block-x"},
        {"table_id": "table-x"},
        {"cell_id": "cell-x"},
        {"row_index": 0},
        {"column_index": 1},
        {"header_snapshot": "保额"},
        {"row_span": 2},
        {"column_span": 2},
    ],
)
def test_freeform_arm_locator_mutation_cannot_bind_or_replay(
    update: dict[str, object],
) -> None:
    document, manifest, contents = _document(
        document_index=3,
        source_name="rate",
        source_revision_id="revision-064-rate",
        source_sha256="8" * 64,
        material_role="rate_table",
        profile_id="profile-rate-596-1",
        header_text="年龄",
        cell_text="30岁对应费率为0.12。",
    )
    evidence = _freeform_evidence(
        document=document,
        manifest=manifest,
        contents=contents,
        field_id="zh_7fe8603c08",
        quote="0.12",
    ).model_copy(
        update={
            "block_id": document.blocks[0].block_id,
            "header_snapshot": "年龄",
        }
    )
    output = FreeformFieldOutputV1(
        product_version_id="596-1",
        field_id=evidence.field_id,
        state="present",
        value_snapshot="0.12",
        evidence=(evidence,),
    )
    receipt = bind_freeform_arm_evidence(
        field_output=output,
        documents=(document,),
        manifests=(manifest,),
    )
    mutated_evidence = evidence.model_copy(update=update)

    with pytest.raises(VerifierContractError):
        bind_freeform_arm_evidence(
            field_output=output.model_copy(update={"evidence": (mutated_evidence,)}),
            documents=(document,),
            manifests=(manifest,),
        )
    with pytest.raises(VerifierContractError, match="freeform_receipt_hash_mismatch"):
        replay_freeform_arm_evidence_binding(
            receipt=receipt.model_copy(update={"evidence": (mutated_evidence,)}),
            documents=(document,),
            manifests=(manifest,),
        )


@pytest.mark.parametrize(
    "update",
    [
        {"source_revision_id": "foreign-revision"},
        {"parse_attempt_id": "foreign-attempt"},
        {"parsed_document_hash": "0" * 64},
        {"parse_manifest_hash": "1" * 64},
    ],
)
def test_freeform_identity_drift_fails_closed(update: dict[str, str]) -> None:
    output, documents, manifests = _freeform_fixture()
    drifted = output.model_copy(
        update={"evidence": (output.evidence[0].model_copy(update=update), *output.evidence[1:])}
    )

    with pytest.raises(VerifierContractError, match="freeform_document_membership_mismatch"):
        bind_freeform_arm_evidence(
            field_output=drifted,
            documents=documents,
            manifests=manifests,
        )


@pytest.mark.parametrize(
    ("locator_update", "evidence_update", "reason"),
    [
        ({"subject_ref": "missing-cell"}, {}, "freeform_locator_not_found"),
        ({"subject_type": "page"}, {}, "freeform_locator_kind_mismatch"),
        ({"page_number": 2}, {}, "freeform_locator_page_mismatch"),
        ({"parent_refs": ("page-1", "table-x")}, {}, "freeform_locator_parent_mismatch"),
        (
            {
                "content_snapshot": "different content",
                "content_snapshot_sha256": _sha("different content"),
            },
            {},
            "freeform_content_snapshot_mismatch",
        ),
        (
            {},
            {
                "quote_snapshot": "not in content",
                "quote_snapshot_sha256": _sha("not in content"),
            },
            "freeform_quote_not_found",
        ),
    ],
)
def test_freeform_locator_content_and_quote_fail_closed(
    locator_update: dict[str, object],
    evidence_update: dict[str, object],
    reason: str,
) -> None:
    output, documents, manifests = _freeform_fixture()
    evidence = output.evidence[0]
    locator = evidence.locator.model_copy(update=locator_update)
    drifted_evidence = evidence.model_copy(
        update={"locator": locator, **evidence_update}
    )
    drifted = output.model_copy(
        update={"evidence": (drifted_evidence, *output.evidence[1:])}
    )

    with pytest.raises(VerifierContractError, match=reason):
        bind_freeform_arm_evidence(
            field_output=drifted,
            documents=documents,
            manifests=manifests,
        )


def test_freeform_membership_shape_and_order_fail_closed() -> None:
    output, documents, manifests = _freeform_fixture()
    cases = (
        output.model_copy(update={"evidence": ()}),
        output.model_copy(update={"evidence": (output.evidence[0], output.evidence[0])}),
        output.model_copy(update={"evidence": tuple(reversed(output.evidence))}),
        output.model_copy(update={"evidence": (output.evidence[0],)}),
        output.model_copy(update={"state": "unknown", "value_snapshot": None}),
    )
    for malformed in cases:
        with pytest.raises(VerifierContractError):
            bind_freeform_arm_evidence(
                field_output=malformed,
                documents=documents,
                manifests=manifests,
            )

    with pytest.raises(VerifierContractError, match="freeform_document_order_invalid"):
        bind_freeform_arm_evidence(
            field_output=output,
            documents=tuple(reversed(documents)),
            manifests=tuple(reversed(manifests)),
        )
    with pytest.raises(VerifierContractError, match="freeform_document_manifest_mismatch"):
        bind_freeform_arm_evidence(
            field_output=output,
            documents=documents,
            manifests=tuple(reversed(manifests)),
        )


def test_freeform_unknown_has_no_evidence_or_document_custody() -> None:
    output = FreeformFieldOutputV1(
        product_version_id="596-1",
        field_id="claim_filing_requirements",
        state="unknown",
        value_snapshot=None,
        evidence=(),
    )

    receipt = bind_freeform_arm_evidence(
        field_output=output,
        documents=(),
        manifests=(),
    )

    assert receipt.evidence == ()
    assert receipt.documents == ()
    assert replay_freeform_arm_evidence_binding(
        receipt=receipt,
        documents=(),
        manifests=(),
    ) == receipt


def test_freeform_receipt_hash_binds_value_evidence_and_document_closure() -> None:
    output, documents, manifests = _freeform_fixture()
    receipt = bind_freeform_arm_evidence(
        field_output=output,
        documents=documents,
        manifests=manifests,
    )
    changed_value = bind_freeform_arm_evidence(
        field_output=output.model_copy(update={"value_snapshot": "不同的自由文本值"}),
        documents=documents,
        manifests=manifests,
    )
    assert changed_value.receipt_hash != receipt.receipt_hash

    evidence = output.evidence[0]
    changed_quote = "12.5"
    changed_evidence = evidence.model_copy(
        update={
            "quote_snapshot": changed_quote,
            "quote_snapshot_sha256": _sha(changed_quote),
        }
    )
    changed_output = output.model_copy(
        update={"evidence": (changed_evidence, *output.evidence[1:])}
    )
    changed_receipt = bind_freeform_arm_evidence(
        field_output=changed_output,
        documents=documents,
        manifests=manifests,
    )
    assert changed_receipt.receipt_hash != receipt.receipt_hash

    forged = receipt.model_copy(update={"value_snapshot": "mutated"})
    assert isinstance(forged, FreeformEvidenceBindingReceiptV1)
    with pytest.raises(VerifierContractError, match="freeform_receipt_hash_mismatch"):
        replay_freeform_arm_evidence_binding(
            receipt=forged,
            documents=documents,
            manifests=manifests,
        )


def test_freeform_extension_does_not_import_061_or_semantic_judge() -> None:
    source = evidence_verifier.__loader__.get_source(evidence_verifier.__name__)  # type: ignore[union-attr]
    assert source is not None
    assert "vertical_falsification" not in source
    assert "semantic_judge" not in source
