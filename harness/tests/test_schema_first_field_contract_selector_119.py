"""OpenSpec119 schema-first contracts and bounded selection front door."""

from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from insurance_harness.knowledge_compiler.schema_first_contracts import (
    APPROVED_BY,
    APPROVED_PRODUCT_VERSION_ID,
    APPROVED_REVIEW_PACKAGE_ID,
    APPROVED_SCHEMA_ID,
    APPROVED_SCHEMA_ROWS_SHA256,
    APPROVED_WORKBOOK_SHA256,
    EXACT_APPROVAL_AUTHORITY_REF,
    ApprovedFieldRowV1,
    ApprovedSchemaSnapshotV1,
    GenericEvidenceReceiptRefV1,
    GenericFactEnvelopeV1,
    SchemaFirstContractError,
    TriState,
    approved_schema_rows,
    approved_schema_snapshot_sha256,
    build_generic_fact_envelope,
    compile_schema_contracts,
    schema_rows_sha256,
)

EXPECTED_FIELD_IDS = (
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


EXPECTED_FIELD_IDS_SHA256 = "8ffe2a043dfae6e65d84f213d42818de3c6c1c39c1fcb0c9eccd14367a30db24"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fields() -> tuple[ApprovedFieldRowV1, ...]:
    rows = approved_schema_rows()
    assert tuple(row.field_id for row in rows) == EXPECTED_FIELD_IDS
    assert schema_rows_sha256(rows) == APPROVED_SCHEMA_ROWS_SHA256
    return rows


def _snapshot(
    fields: tuple[ApprovedFieldRowV1, ...] | None = None,
    *,
    authority_ref: str = EXACT_APPROVAL_AUTHORITY_REF,
) -> ApprovedSchemaSnapshotV1:
    exact_fields = fields or _fields()
    schema_hash = schema_rows_sha256(exact_fields)
    snapshot_hash = approved_schema_snapshot_sha256(
        product_version_id=APPROVED_PRODUCT_VERSION_ID,
        review_package_id=APPROVED_REVIEW_PACKAGE_ID,
        schema_id=APPROVED_SCHEMA_ID,
        workbook_sha256=APPROVED_WORKBOOK_SHA256,
        approval_status="EXPERT_APPROVED_NO_CHANGES",
        approved_by=APPROVED_BY,
        authority_ref=authority_ref,
        schema_rows_sha256_value=schema_hash,
        ordered_field_ids_sha256_value=EXPECTED_FIELD_IDS_SHA256,
    )
    return ApprovedSchemaSnapshotV1.model_validate(
        {
            "product_version_id": APPROVED_PRODUCT_VERSION_ID,
            "review_package_id": APPROVED_REVIEW_PACKAGE_ID,
            "schema_id": APPROVED_SCHEMA_ID,
            "workbook_sha256": APPROVED_WORKBOOK_SHA256,
            "approval_status": "EXPERT_APPROVED_NO_CHANGES",
            "approved_by": APPROVED_BY,
            "authority_ref": authority_ref,
            "fields": exact_fields,
            "schema_rows_sha256": schema_hash,
            "ordered_field_ids_sha256": EXPECTED_FIELD_IDS_SHA256,
            "snapshot_sha256": snapshot_hash,
        }
    )


def test_exact_schema67_compiles_one_contract_per_field_without_values() -> None:
    first = compile_schema_contracts(_snapshot())
    second = compile_schema_contracts(_snapshot())

    assert first == second
    assert len(first.contracts) == 67
    assert first.product_version_id == "596-1"
    assert first.review_package_id == "596-2-golden-human-review"
    assert tuple(item.field_id for item in first.contracts) == EXPECTED_FIELD_IDS
    assert first.ordered_field_ids_sha256 == EXPECTED_FIELD_IDS_SHA256
    assert tuple(item.ordinal for item in first.contracts) == tuple(range(1, 68))
    assert len({item.field_id for item in first.contracts}) == 67
    assert first.contract_set_sha256 == second.contract_set_sha256
    assert first.contract_set_sha256 == (
        "c51d4a01ee90177397b8a5f14c35a0a3ee8cad5bd175c5f94826639792d92f0c"
    )
    assert _fields()[0].description == (
        "产品在公司产品主数据中的唯一标识代码，用于关联产品元数据、条款、计划表及其他业务材料；"
        "优先从产品主数据获取，必要时可从条款首页核验。"
    )
    assert _fields()[22].source_authority_raw == ("产品保全、核保规则PDF及其他业务材料")
    assert _fields()[39].value_shape_raw == ("一般医疗保险金200万、恶性肿瘤医疗保险金200万等")
    assert _fields()[39].formation_raw == "原文抽取；LLM生成"
    serialized = str(first.model_dump(mode="json"))
    assert "value-1" not in serialized
    assert "candidate_status" not in serialized
    assert "candidate_value" not in serialized
    assert "candidate_evidence" not in serialized
    assert "allowed_states" not in serialized


def test_approved_raw_guidance_survives_field_contract_projection() -> None:
    rows = _fields()
    contracts = compile_schema_contracts(_snapshot()).contracts

    assert len(rows) == len(contracts) == 67
    for row, contract in zip(rows, contracts, strict=True):
        assert contract.field_name == row.field_name
        assert contract.category == row.category
        assert contract.description == row.description
        assert contract.value_shape_raw == row.value_shape_raw
        assert contract.source_authority_raw == row.source_authority_raw
        assert contract.formation_raw == row.formation_raw
        assert contract.source_roles == row.source_roles


def test_schema67_duplicate_reorder_and_declared_hash_drift_fail_closed() -> None:
    rows = _fields()
    with pytest.raises(ValidationError):
        _snapshot(rows[:-1] + (rows[-2],))
    with pytest.raises(ValidationError):
        _snapshot((rows[1], rows[0], *rows[2:]))

    forged = _snapshot().model_copy(update={"schema_rows_sha256": _sha("forged")})
    with pytest.raises(SchemaFirstContractError, match="SCHEMA_SNAPSHOT_INVALID"):
        compile_schema_contracts(forged)

    foreign = rows[0].model_copy(update={"field_id": "foreign_field"})
    with pytest.raises(ValidationError):
        _snapshot((foreign, *rows[1:]))


def test_rehashed_schema_row_mutations_cannot_replace_approved_xlsx_authority() -> None:
    rows = _fields()
    mutations = (
        rows[0].model_copy(update={"description": "attacker description"}),
        rows[0].model_copy(update={"source_authority_raw": "伪造来源"}),
        rows[0].model_copy(update={"formation_raw": "LLM生成"}),
        rows[0].model_copy(update={"value_shape_raw": "伪造取值形态"}),
    )

    for mutated in mutations:
        with pytest.raises(ValidationError):
            _snapshot((mutated, *rows[1:]))

    synthetic = tuple(
        ApprovedFieldRowV1(
            ordinal=index,
            category="synthetic category",
            field_name=f"synthetic-{index}",
            field_id=field_id,
            description="synthetic description",
            value_shape_raw=None,
            source_authority_raw="产品条款",
            formation_raw="原文抽取",
        )
        for index, field_id in enumerate(EXPECTED_FIELD_IDS, start=1)
    )
    with pytest.raises(ValidationError):
        _snapshot(synthetic)


def test_approval_actor_is_exact_linyao_and_part_of_snapshot_custody() -> None:
    approved = _snapshot()
    assert approved.approved_by == "linyao"
    assert compile_schema_contracts(approved).approved_by == "linyao"

    forged = approved.model_copy(update={"approved_by": "someone-else"})
    with pytest.raises(SchemaFirstContractError, match="SCHEMA_SNAPSHOT_INVALID"):
        compile_schema_contracts(forged)


def test_approval_authority_ref_is_exact_and_cannot_be_rehashed() -> None:
    assert _snapshot().authority_ref == EXACT_APPROVAL_AUTHORITY_REF
    assert compile_schema_contracts(_snapshot()).authority_ref == EXACT_APPROVAL_AUTHORITY_REF
    with pytest.raises(ValidationError):
        _snapshot(authority_ref="user-message:attacker")


def test_current_material_routing_defers_21_without_answer_oracle() -> None:
    compiled = compile_schema_contracts(_snapshot())
    by_id = {item.field_id: item for item in compiled.contracts}

    deferred = tuple(
        item.field_id for item in compiled.contracts if item.source_roles == ("deferred",)
    )
    assert len(deferred) == 21
    assert "sales_start_date" in deferred
    assert "marketing_tagline" in deferred
    assert "eligible_service_packages" in deferred
    assert by_id["guaranteed_renewal_period"].source_roles == ("terms",)
    assert all(not hasattr(row, "candidate_status") for row in _snapshot().fields)
    assert all(not hasattr(item, "allowed_states") for item in compiled.contracts)


def test_schema_rows_cannot_carry_candidate_or_answer_custody() -> None:
    row = _fields()[33]
    with pytest.raises(ValidationError):
        ApprovedFieldRowV1.model_validate(
            {
                **row.model_dump(mode="python"),
                "candidate_status": "source_explicit_absence",
            }
        )


def test_hardness_is_closed_deterministic_and_answer_independent() -> None:
    first = compile_schema_contracts(_snapshot())
    second = compile_schema_contracts(_snapshot())
    by_id = {item.field_id: item for item in first.contracts}

    assert by_id["cooling_off_period"].hardness.band == "H0_EXACT"
    assert by_id["entry_age_range"].hardness.band == "H1_BOUNDED"
    assert by_id["product_summary"].hardness.band == "H2_SEMANTIC"
    assert by_id["product_code"].hardness.band == "H3_EXTERNAL_AUTHORITY"
    assert by_id["product_summary"].hardness.cross_source is True
    assert tuple(item.hardness for item in first.contracts) == tuple(
        item.hardness for item in second.contracts
    )


def _generic_evidence(fact_key: str, state: TriState) -> GenericEvidenceReceiptRefV1:
    return GenericEvidenceReceiptRefV1(
        contract="freeform-arm-evidence-binding-receipt.v1",
        fact_key=fact_key,
        state=state,
        receipt_sha256=_sha(f"{fact_key}:{state}"),
    )


def test_generic_fact_state_and_release_boundaries() -> None:
    unknown = build_generic_fact_envelope(
        product_version_id=APPROVED_PRODUCT_VERSION_ID,
        source_revision_id="source-revision-119",
        fact_key="generic/network-hospital-rule",
        state="unknown",
        value_snapshot=None,
        evidence_receipts=(),
    )
    present = build_generic_fact_envelope(
        product_version_id=APPROVED_PRODUCT_VERSION_ID,
        source_revision_id="source-revision-119",
        fact_key="generic/network-hospital-rule",
        state="present",
        value_snapshot="candidate snapshot",
        evidence_receipts=(_generic_evidence("generic/network-hospital-rule", "present"),),
    )
    absent = build_generic_fact_envelope(
        product_version_id=APPROVED_PRODUCT_VERSION_ID,
        source_revision_id="source-revision-119",
        fact_key="generic/network-hospital-rule",
        state="absent_explicitly",
        value_snapshot=None,
        evidence_receipts=(
            _generic_evidence("generic/network-hospital-rule", "absent_explicitly"),
        ),
    )

    assert unknown.release_eligible is False
    assert present.release_eligible is False
    assert absent.release_eligible is False
    with pytest.raises(ValidationError):
        GenericFactEnvelopeV1.model_validate(
            {
                **present.model_dump(mode="python"),
                "formal_field_id": "schema67_field_01",
            }
        )
    with pytest.raises(SchemaFirstContractError, match="GENERIC_FACT_STATE_INVALID"):
        build_generic_fact_envelope(
            product_version_id=APPROVED_PRODUCT_VERSION_ID,
            source_revision_id="source-revision-119",
            fact_key="generic/network-hospital-rule",
            state="absent_explicitly",
            value_snapshot=None,
            evidence_receipts=(),
        )
