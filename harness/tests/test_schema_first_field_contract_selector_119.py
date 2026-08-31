"""OpenSpec119 schema-first contracts and bounded selection front door."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

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
from insurance_harness.knowledge_compiler.schema_first_selector import (
    APPROVED_596_1_TEMPLATE_CONTENT_HASHES,
    ApprovedMaterialProfileV1,
    SchemaCompilationRequestV1,
    approved_material_profile_sha256,
    build_596_1_schema67_material_profile_catalog,
    build_596_1_schema67_template_catalog,
    select_schema_compilation,
)
from insurance_harness.template_packages import (
    EvidencePolicy,
    FieldGroup,
    ProvenanceReceipt,
    TemplateApproval,
    TemplateCatalogEntry,
    TemplatePackageContent,
    TemplateScope,
    TemplateVersion,
    ValidatorRef,
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


def _template_entry(field_ids: Iterable[str]) -> TemplateCatalogEntry:
    scope = TemplateScope(space_id="space-119", level="global")
    content = TemplatePackageContent(
        schema_version=APPROVED_SCHEMA_ID,
        field_groups=(
            FieldGroup(
                group_id="schema67-fields",
                field_ids=tuple(field_ids),
                evidence_roles=("terms",),
            ),
        ),
        role_prompts={"extract": "schema67 evidence extraction"},
        validators=(
            ValidatorRef(
                validator_id="schema67-validator",
                validator_version="v1",
                config_hash=_sha("validator"),
            ),
        ),
        evidence_policy=EvidencePolicy(
            require_quote=True,
            require_locator=True,
            minimum_sources=1,
        ),
        attempt_limits={"extract": 1},
        golden_slice_ref="schema67-approved-schema-only",
        provenance=(
            ProvenanceReceipt(
                migration_id="MIG-119-SCHEMA67",
                source_repository="PA-ALG/InsuranceKB-WeKnora",
                source_branch="main",
                source_commit="2f356368342d2d4578e18315a9fedf739ab73190",
                source_path="frontend/src/lib/product-catalog-modules.ts",
                source_language="typescript",
                rights_status="project-owned",
                accepted_behavior="exact approved hierarchy and field grouping",
                rejected_behavior="fuzzy dispatch and runtime state",
                python_target=(
                    "harness/src/insurance_harness/knowledge_compiler/schema_first_selector.py"
                ),
                translation_method="behavior_port_with_characterization_tests",
                characterization_tests=(
                    "harness/tests/test_schema_first_field_contract_selector_119.py",
                ),
            ),
        ),
    )
    version = TemplateVersion.from_content(
        package_id="schema67-template",
        version_id="v1",
        scope=scope,
        content=content,
    )
    return TemplateCatalogEntry(
        version=version,
        approval=TemplateApproval(
            approval_id="schema67-template-approval",
            package_id=version.package_id,
            version_id=version.version_id,
            scope=scope,
            content_hash=version.content_hash,
            state="approved",
        ),
    )


class _TemplateCatalog:
    def __init__(self, entry: TemplateCatalogEntry) -> None:
        self.entry = entry
        self.calls: list[TemplateScope] = []

    def get_approved(self, scope: TemplateScope) -> TemplateCatalogEntry | None:
        self.calls.append(scope)
        return self.entry if scope.level == "global" else None


class _ProfileCatalog:
    def __init__(self, profiles: tuple[ApprovedMaterialProfileV1, ...]) -> None:
        self.profiles = profiles
        self.calls: list[tuple[str, str]] = []

    def list_approved(
        self, *, product_version_id: str, material_role: str
    ) -> tuple[ApprovedMaterialProfileV1, ...]:
        self.calls.append((product_version_id, material_role))
        return self.profiles


def _single_role_field_ids(
    snapshot: ApprovedSchemaSnapshotV1,
    material_role: Literal["terms", "brochure", "rate_table"],
) -> tuple[str, ...]:
    compiled = compile_schema_contracts(snapshot)
    return tuple(
        item.field_id for item in compiled.contracts if item.source_roles == (material_role,)
    )


def _profile(
    snapshot: ApprovedSchemaSnapshotV1,
    material_role: Literal["terms", "brochure", "rate_table"] = "terms",
) -> ApprovedMaterialProfileV1:
    compiled = compile_schema_contracts(snapshot)
    field_ids = _single_role_field_ids(snapshot, material_role)
    profile_id = f"medical-596-1-{material_role}.v1"
    return ApprovedMaterialProfileV1(
        profile_id=profile_id,
        approval_state="approved",
        product_version_id=APPROVED_PRODUCT_VERSION_ID,
        schema_contract_sha256=compiled.contract_set_sha256,
        material_role=material_role,
        product_line_id="medical",
        document_type_id="insurance-terms",
        product_family_id="pingan-596-1-medical",
        required_field_ids=field_ids,
        profile_sha256=approved_material_profile_sha256(
            profile_id=profile_id,
            approval_state="approved",
            product_version_id=APPROVED_PRODUCT_VERSION_ID,
            schema_contract_sha256=compiled.contract_set_sha256,
            material_role=material_role,
            product_line_id="medical",
            document_type_id="insurance-terms",
            product_family_id="pingan-596-1-medical",
            required_field_ids=field_ids,
        ),
    )


def test_schema_path_selects_exact_profile_and_existing_template_resolver() -> None:
    snapshot = _snapshot()
    profile = _profile(snapshot)
    profiles = _ProfileCatalog((profile,))
    templates = _TemplateCatalog(_template_entry(profile.required_field_ids))

    result = select_schema_compilation(
        request=SchemaCompilationRequestV1(
            space_id="space-119",
            product_version_id=APPROVED_PRODUCT_VERSION_ID,
            material_role="terms",
            schema_snapshot=snapshot,
            generic_fact=None,
        ),
        material_profiles=profiles,
        template_catalog=templates,
    )

    assert result.status == "SCHEMA_BOUND"
    assert result.reason_codes == ()
    assert result.material_profile == profile
    assert result.field_contracts is not None
    assert result.resolved_template is not None
    assert result.material_field_ids == profile.required_field_ids
    assert result.synthesis_field_ids == (
        "product_summary",
        "product_overview",
        "social_insurance_requirement",
        "underwriting_method",
        "coverage_responsibilities",
        "coverage_summary",
    )
    assert result.deferred_unknown_field_ids == (
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
    assert "candidate_status" not in str(result.model_dump(mode="json"))
    assert "candidate_value" not in str(result.model_dump(mode="json"))
    assert set(result.material_field_ids).isdisjoint(result.synthesis_field_ids)
    assert set(result.material_field_ids).isdisjoint(result.deferred_unknown_field_ids)
    assert profiles.calls == [(APPROVED_PRODUCT_VERSION_ID, "terms")]
    assert tuple(scope.level for scope in templates.calls) == (
        "global",
        "product-line",
        "document-type",
        "product-family",
    )


def test_three_material_roles_are_disjoint_and_leave_external_fields_unknown() -> None:
    snapshot = _snapshot()
    material_groups: list[tuple[str, ...]] = []
    first_result = None
    for role in ("terms", "brochure", "rate_table"):
        profile = _profile(snapshot, role)
        result = select_schema_compilation(
            request=SchemaCompilationRequestV1(
                space_id="space-119",
                product_version_id=APPROVED_PRODUCT_VERSION_ID,
                material_role=role,
                schema_snapshot=snapshot,
                generic_fact=None,
            ),
            material_profiles=_ProfileCatalog((profile,)),
            template_catalog=_TemplateCatalog(_template_entry(profile.required_field_ids)),
        )
        assert result.status == "SCHEMA_BOUND"
        material_groups.append(result.material_field_ids)
        first_result = first_result or result

    assert first_result is not None
    assert tuple(len(group) for group in material_groups) == (35, 4, 1)
    flattened = tuple(item for group in material_groups for item in group)
    assert len(flattened) == len(set(flattened))
    assert set(flattened).isdisjoint(first_result.synthesis_field_ids)
    assert set(flattened).isdisjoint(first_result.deferred_unknown_field_ids)
    assert set(flattened) | set(first_result.synthesis_field_ids) | set(
        first_result.deferred_unknown_field_ids
    ) == set(EXPECTED_FIELD_IDS)
    assert len(first_result.synthesis_field_ids) == 6
    assert len(first_result.deferred_unknown_field_ids) == 21


def test_profile_drift_blocks_before_template_lookup() -> None:
    snapshot = _snapshot()
    profile = _profile(snapshot).model_copy(
        update={"schema_contract_sha256": _sha("foreign-schema")}
    )
    profiles = _ProfileCatalog((profile,))
    templates = _TemplateCatalog(_template_entry(_single_role_field_ids(snapshot, "terms")))

    result = select_schema_compilation(
        request=SchemaCompilationRequestV1(
            space_id="space-119",
            product_version_id=APPROVED_PRODUCT_VERSION_ID,
            material_role="terms",
            schema_snapshot=snapshot,
            generic_fact=None,
        ),
        material_profiles=profiles,
        template_catalog=templates,
    )

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("MATERIAL_PROFILE_IDENTITY_MISMATCH",)
    assert templates.calls == []


def test_single_material_profile_cannot_claim_all67_or_deferred_fields() -> None:
    snapshot = _snapshot()
    compiled = compile_schema_contracts(snapshot)
    exact = _profile(snapshot)
    all_fields = tuple(item.field_id for item in compiled.contracts)
    forged = ApprovedMaterialProfileV1(
        profile_id=exact.profile_id,
        approval_state=exact.approval_state,
        product_version_id=exact.product_version_id,
        schema_contract_sha256=exact.schema_contract_sha256,
        material_role=exact.material_role,
        product_line_id=exact.product_line_id,
        document_type_id=exact.document_type_id,
        product_family_id=exact.product_family_id,
        required_field_ids=all_fields,
        profile_sha256=approved_material_profile_sha256(
            profile_id=exact.profile_id,
            approval_state=exact.approval_state,
            product_version_id=exact.product_version_id,
            schema_contract_sha256=exact.schema_contract_sha256,
            material_role=exact.material_role,
            product_line_id=exact.product_line_id,
            document_type_id=exact.document_type_id,
            product_family_id=exact.product_family_id,
            required_field_ids=all_fields,
        ),
    )
    templates = _TemplateCatalog(_template_entry(all_fields))

    result = select_schema_compilation(
        request=SchemaCompilationRequestV1(
            space_id="space-119",
            product_version_id=APPROVED_PRODUCT_VERSION_ID,
            material_role="terms",
            schema_snapshot=snapshot,
            generic_fact=None,
        ),
        material_profiles=_ProfileCatalog((forged,)),
        template_catalog=templates,
    )

    assert result.status == "BLOCKED"
    assert result.reason_codes == ("MATERIAL_PROFILE_IDENTITY_MISMATCH",)
    assert templates.calls == []


def test_only_true_no_schema_can_fallback_and_invalid_schema_cannot() -> None:
    generic = build_generic_fact_envelope(
        product_version_id=APPROVED_PRODUCT_VERSION_ID,
        source_revision_id="source-revision-119",
        fact_key="generic/network-hospital-rule",
        state="unknown",
        value_snapshot=None,
        evidence_receipts=(),
    )
    profiles = _ProfileCatalog(())
    templates = _TemplateCatalog(_template_entry(tuple(row.field_id for row in _fields())))
    fallback = select_schema_compilation(
        request=SchemaCompilationRequestV1(
            space_id="space-119",
            product_version_id=APPROVED_PRODUCT_VERSION_ID,
            material_role="terms",
            schema_snapshot=None,
            generic_fact=generic,
        ),
        material_profiles=profiles,
        template_catalog=templates,
    )
    assert fallback.status == "GENERIC_FACT_FALLBACK"
    assert fallback.generic_fact == generic
    assert profiles.calls == []
    assert templates.calls == []

    malformed = _snapshot().model_copy(update={"workbook_sha256": _sha("foreign-workbook")})
    forged_request = SchemaCompilationRequestV1.model_construct(
        space_id="space-119",
        product_version_id=APPROVED_PRODUCT_VERSION_ID,
        material_role="terms",
        schema_snapshot=malformed,
        generic_fact=generic,
    )
    blocked = select_schema_compilation(
        request=forged_request,
        material_profiles=profiles,
        template_catalog=templates,
    )
    assert blocked.status == "BLOCKED"
    assert blocked.reason_codes == ("SCHEMA_SNAPSHOT_INVALID",)
    assert blocked.generic_fact is None
    assert profiles.calls == []
    assert templates.calls == []


def test_production_catalogs_bind_schema67_roles_and_052_resolutions() -> None:
    from insurance_harness.compiler.material_profiles import (
        MaterialProfileResolutionRequest,
        load_material_profile_catalog,
        resolve_material_profile,
    )

    snapshot = _snapshot()
    contracts = compile_schema_contracts(snapshot)
    profiles = build_596_1_schema67_material_profile_catalog(contracts)
    templates = build_596_1_schema67_template_catalog(
        space_id="space-119",
        field_contracts=contracts,
    )
    by_role: dict[str, tuple[str, ...]] = {}
    template_hashes: list[tuple[str, str]] = []
    for role in ("terms", "brochure", "rate_table"):
        result = select_schema_compilation(
            request=SchemaCompilationRequestV1(
                space_id="space-119",
                product_version_id=APPROVED_PRODUCT_VERSION_ID,
                material_role=role,
                schema_snapshot=snapshot,
                generic_fact=None,
            ),
            material_profiles=profiles,
            template_catalog=templates,
        )
        assert result.status == "SCHEMA_BOUND"
        assert result.material_profile is not None
        assert result.resolved_template is not None
        by_role[role] = result.material_field_ids
        template_hashes.append((role, result.resolved_template.content_hash))

    assert tuple(len(by_role[role]) for role in ("terms", "brochure", "rate_table")) == (
        35,
        4,
        1,
    )
    assert tuple(template_hashes) == APPROVED_596_1_TEMPLATE_CONTENT_HASHES

    fixture = Path(__file__).parent / "fixtures" / "material_profile_596_1_052.json"
    catalog_052 = load_material_profile_catalog(fixture)
    resolutions = []
    for profile in catalog_052.profiles:
        resolutions.append(
            resolve_material_profile(
                catalog_052,
                templates,
                MaterialProfileResolutionRequest(
                    space_id="space-119",
                    product_code=catalog_052.product.product_code,
                    product_version=catalog_052.product.product_version,
                    schema_version=catalog_052.schema_binding.schema_version,
                    schema_field_ids=catalog_052.schema_binding.field_ids,
                    source=profile.source,
                    classified_material_role=profile.material_role,
                ),
            )
        )

    assert tuple(item.profile.profile_id for item in resolutions) == (
        "596-1-terms-v1",
        "596-1-brochure-v1",
        "596-1-rate-table-v1",
    )
    assert all(not item.review_items for item in resolutions)
    assert tuple(item.resolved_template.content_hash for item in resolutions) == tuple(
        digest for _role, digest in APPROVED_596_1_TEMPLATE_CONTENT_HASHES
    )


def test_production_catalogs_reject_mutation_revocation_and_ambiguity() -> None:
    snapshot = _snapshot()
    contracts = compile_schema_contracts(snapshot)
    legacy_contracts = contracts.model_copy(
        update={
            "contract_set_sha256": (
                "e0832ec970d572982a2fdd493ec0cd496282d99f363e2544addb6474f4d013de"
            )
        }
    )
    with pytest.raises(ValueError, match="SCHEMA67_CATALOG_INVALID"):
        build_596_1_schema67_material_profile_catalog(legacy_contracts)
    forged_contracts = contracts.model_copy(
        update={"contract_set_sha256": _sha("foreign-contract-set")}
    )
    with pytest.raises(ValueError, match="SCHEMA67_CATALOG_INVALID"):
        build_596_1_schema67_material_profile_catalog(forged_contracts)
    with pytest.raises(ValueError, match="SCHEMA67_CATALOG_INVALID"):
        build_596_1_schema67_template_catalog(
            space_id="space-119",
            field_contracts=forged_contracts,
        )

    fixed = build_596_1_schema67_material_profile_catalog(contracts)
    profile = fixed.list_approved(
        product_version_id=APPROVED_PRODUCT_VERSION_ID,
        material_role="terms",
    )[0]
    revoked = ApprovedMaterialProfileV1(
        **{
            **profile.model_dump(mode="python"),
            "approval_state": "revoked",
            "profile_sha256": approved_material_profile_sha256(
                profile_id=profile.profile_id,
                approval_state="revoked",
                product_version_id=profile.product_version_id,
                schema_contract_sha256=profile.schema_contract_sha256,
                material_role=profile.material_role,
                product_line_id=profile.product_line_id,
                document_type_id=profile.document_type_id,
                product_family_id=profile.product_family_id,
                required_field_ids=profile.required_field_ids,
            ),
        }
    )
    templates = build_596_1_schema67_template_catalog(
        space_id="space-119",
        field_contracts=contracts,
    )
    request = SchemaCompilationRequestV1(
        space_id="space-119",
        product_version_id=APPROVED_PRODUCT_VERSION_ID,
        material_role="terms",
        schema_snapshot=snapshot,
        generic_fact=None,
    )
    revoked_result = select_schema_compilation(
        request=request,
        material_profiles=_ProfileCatalog((revoked,)),
        template_catalog=templates,
    )
    ambiguous_result = select_schema_compilation(
        request=request,
        material_profiles=_ProfileCatalog((profile, profile)),
        template_catalog=templates,
    )
    assert revoked_result.reason_codes == ("MATERIAL_PROFILE_IDENTITY_MISMATCH",)
    assert ambiguous_result.reason_codes == ("MATERIAL_PROFILE_AMBIGUOUS",)
