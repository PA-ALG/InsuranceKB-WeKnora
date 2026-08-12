"""Non-authoritative human annotation kit for medical Schema67 product 596-1."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.knowledge_compiler.medical_schema_pack_596_1 import (
    MEDICAL_SECTION_FIELD_COUNTS,
    MEDICAL_SECTION_IDS,
    make_medical_schema_pack_596_1,
)

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonBlankStr = Annotated[str, StringConstraints(min_length=1, max_length=512)]
MappingAction = Literal["reuse", "rename", "split", "merge", "new", "N-A"]
SourceRisk = Literal["low", "medium", "high"]
TriState = Literal["present", "absent_explicitly", "unknown"]

_CONTRACT: Final[str] = "schema67-human-annotation-kit-596-1.v1"
_SUMMARY_CONTRACT: Final[Literal["schema67-human-annotation-kit-summary-596-1.v1"]] = (
    "schema67-human-annotation-kit-summary-596-1.v1"
)
_OLD60_SHA256: Final[str] = "562c37c7cf262e2e78f0b3ca4b7de4b0dab2f407d3cd7318a8a69b5dca33d8fb"
_DRAFT71_SHA256: Final[str] = "25c62051d04c8bd56f3770e77d071ae18945daee5dce6b8fb584937555260be4"


class Schema67HumanAnnotationKitError(ValueError):
    """Stable fail-closed error for the non-authoritative annotation kit."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _ClosedModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class RelatedDigestV1(_ClosedModel):
    name: NonBlankStr
    sha256: Sha256Hex


class AnnotationInputIdentityV1(_ClosedModel):
    dataset_id: NonBlankStr
    sha256: Sha256Hex
    row_count: int = Field(ge=1)
    authority_level: Literal["HUMAN_APPROVED_S0_Q_MIGRATION_INPUT", "MODEL_SUGGESTION"]
    admission_status: Literal["PROPOSED_MIGRATION", "MODEL_SUGGESTION"]
    human_review_status: Literal["PENDING"] = "PENDING"
    scope: NonBlankStr
    related_digests: tuple[RelatedDigestV1, ...] = ()


class AnnotationSchemaPackIdentityV1(_ClosedModel):
    schema_pack_id: Literal["medical-schema67.v1"]
    schema_pack_sha256: Sha256Hex
    ordered_field_ids: tuple[NonBlankStr, ...]
    ordered_section_ids: tuple[NonBlankStr, ...]
    section_field_counts: tuple[int, ...]


class AnnotationMappingDecisionV1(_ClosedModel):
    mapping_id: NonBlankStr
    source_dataset: Literal["old60", "draft71"]
    source_field_id: NonBlankStr | None
    source_display_name: NonBlankStr | None
    target_field_ids: tuple[NonBlankStr, ...]
    action: MappingAction
    source_authority_level: Literal["HUMAN_APPROVED_S0_Q_MIGRATION_INPUT", "MODEL_SUGGESTION"]
    admission_status: Literal["PROPOSED_MIGRATION", "MODEL_SUGGESTION"]
    human_review_status: Literal["PENDING"] = "PENDING"
    source_state_suggestion: TriState | None
    source_risk_level: SourceRisk | None
    mandatory_human_review: bool
    tri_state_conflict: bool

    @model_validator(mode="after")
    def _validate_action_shape(self) -> AnnotationMappingDecisionV1:
        source_count = int(self.source_field_id is not None)
        target_count = len(self.target_field_ids)
        valid = {
            "reuse": source_count == 1
            and target_count == 1
            and self.source_field_id == self.target_field_ids[0],
            "rename": source_count == 1
            and target_count == 1
            and self.source_field_id != self.target_field_ids[0],
            "split": source_count == 1 and target_count >= 2,
            "merge": source_count == 1 and target_count == 1,
            "new": source_count == 0 and target_count == 1,
            "N-A": source_count == 1 and target_count == 0,
        }[self.action]
        if not valid or (self.source_field_id is None) != (self.source_display_name is None):
            raise ValueError("ANNOTATION_MAPPING_SHAPE_INVALID")
        return self


class AnnotationSourceRevisionV1(_ClosedModel):
    role: Literal["terms", "brochure", "rate"]
    knowledge_id: NonBlankStr
    parse_attempt: int = Field(ge=1)
    file_sha256: Sha256Hex
    chunk_manifest_sha256: Sha256Hex
    chunk_count: int = Field(ge=1)
    page_count: int = Field(ge=1)
    parse_status: Literal["completed"] = "completed"
    revision_authority_status: Literal["PREFLIGHT_CURRENT_REVISION_ONLY"]
    evidence_admission_status: Literal["PENDING_ATTEMPT_BOUND_SEAL"]


class PendingSchema67AnnotationV1(_ClosedModel):
    field_id: NonBlankStr
    annotation_status: Literal["PENDING"] = "PENDING"
    state: None = None
    value: None = None
    value_schema: None = None
    allowed_values: tuple[str, ...] = ()
    normalization_rule_id: None = None
    evidence: tuple[object, ...] = ()
    page: None = None
    locator: None = None
    quote: None = None
    quote_sha256: None = None
    content_sha256: None = None
    bbox: None = None
    coordinate_space: None = None
    bbox_status: Literal["PENDING_CAPTURE"] = "PENDING_CAPTURE"
    risk_level: None = None
    conflict_status: Literal["PENDING"] = "PENDING"
    reviewer_decisions: tuple[object, ...] = ()

    @model_validator(mode="after")
    def _require_blank_pending_template(self) -> PendingSchema67AnnotationV1:
        if self.allowed_values or self.evidence or self.reviewer_decisions:
            raise ValueError("ANNOTATION_TEMPLATE_NOT_BLANK")
        return self


class SpecialPageWorkItemV1(_ClosedModel):
    role: Literal["terms", "brochure", "rate"]
    page: Literal[12, 27]
    page_exists: bool
    prior_approved_quote_count: int = Field(ge=0)
    action: Literal[
        "PENDING_RECAPTURE",
        "PENDING_HUMAN_SELECTION",
        "PROHIBITED_PAGE_OUT_OF_RANGE",
    ]
    bbox_status: Literal["PENDING_CAPTURE"] = "PENDING_CAPTURE"
    coordinate_space: None = None


class ReviewerRoleSlotV1(_ClosedModel):
    slot_id: NonBlankStr
    required_role: NonBlankStr
    named_human_id: Literal["PENDING_NAMED_HUMAN_ID"]
    decision_status: Literal["PENDING"]


class WholeBatchReceiptTemplateV1(_ClosedModel):
    contract: Literal["schema67-golden-whole-batch-receipt-template-596-1.v1"]
    status: Literal["PENDING"]
    required_reviewer_slot_ids: tuple[NonBlankStr, ...]
    golden_set_sha256: None = None
    receipt_sha256: None = None
    signature: None = None


class Schema67HumanAnnotationKit5961V1(_ClosedModel):
    contract: Literal["schema67-human-annotation-kit-596-1.v1"]
    kit_status: Literal["NON_AUTHORITATIVE_DRAFT"]
    product_version_id: Literal["596-1"]
    generation_policy: Literal["NO_MODEL_NO_MATERIAL_WIKI_NO_GOLDEN"]
    schema_pack: AnnotationSchemaPackIdentityV1
    old60_input: AnnotationInputIdentityV1
    draft71_input: AnnotationInputIdentityV1
    old60_mappings: tuple[AnnotationMappingDecisionV1, ...]
    draft71_mappings: tuple[AnnotationMappingDecisionV1, ...]
    source_revisions: tuple[AnnotationSourceRevisionV1, ...]
    annotations: tuple[PendingSchema67AnnotationV1, ...]
    special_pages: tuple[SpecialPageWorkItemV1, ...]
    reviewer_slots: tuple[ReviewerRoleSlotV1, ...]
    whole_batch_receipt: WholeBatchReceiptTemplateV1
    kit_sha256: Sha256Hex

    @model_validator(mode="after")
    def _validate_complete_pending_kit(self) -> Schema67HumanAnnotationKit5961V1:
        ordered = tuple(self.schema_pack.ordered_field_ids)
        if (
            tuple(row.field_id for row in self.annotations) != ordered
            or len(ordered) != 67
            or len(set(ordered)) != 67
            or tuple(item.role for item in self.source_revisions) != ("terms", "brochure", "rate")
            or tuple((item.role, item.page) for item in self.special_pages)
            != (
                ("terms", 12),
                ("terms", 27),
                ("brochure", 12),
                ("brochure", 27),
                ("rate", 12),
                ("rate", 27),
            )
            or self.whole_batch_receipt.required_reviewer_slot_ids
            != tuple(slot.slot_id for slot in self.reviewer_slots)
        ):
            raise ValueError("ANNOTATION_KIT_TOPOLOGY_INVALID")
        _validate_mapping_topology(self.old60_mappings, ordered)
        _validate_mapping_topology(self.draft71_mappings, ordered)
        if self.kit_sha256 != schema67_human_annotation_kit_sha256(self):
            raise ValueError("ANNOTATION_KIT_HASH_INVALID")
        return self


class Schema67HumanAnnotationKitSummary5961V1(_ClosedModel):
    contract: Literal["schema67-human-annotation-kit-summary-596-1.v1"]
    kit_status: Literal["NON_AUTHORITATIVE_DRAFT"]
    field_count: int
    pending_field_count: int
    old60_source_count: int
    draft71_source_count: int
    model_high_risk_count: int
    mandatory_human_review_count: int
    tri_state_conflict_count: int
    bbox_pending_count: int
    reviewer_slot_count: int
    assigned_reviewer_count: Literal[0]
    approved_field_count: Literal[0]
    can_emit_approved_golden: Literal[False]


_OLD60_MAPPING: Final[dict[str, tuple[MappingAction, tuple[str, ...]]]] = {
    "claim_filing_requirements": ("rename", ("claim_application_deadline_and_documents",)),
    "clause_effective_date": ("N-A", ()),
    "clause_version": ("N-A", ()),
    "discontinuation_renewal": ("rename", ("post_discontinuation_renewal_arrangement",)),
    "exclusions_official": ("rename", ("exclusions",)),
    "external_drug_coverage": ("rename", ("out_of_hospital_special_drug_coverage",)),
    "pre_existing_conditions": ("rename", ("pre_existing_condition_rules",)),
    "reduced_paid_up": ("N-A", ()),
    "regulatory_filing_no": ("N-A", ()),
    "reinstatement": ("N-A", ()),
    "waiting_period_claim_handling": ("N-A", ()),
    "zh_0612362268": ("rename", ("deductible_rules",)),
    "zh_09a5d9e54e": ("rename", ("coverage_summary",)),
    "zh_0b3894ed2a": ("rename", ("product_type",)),
    "zh_0c5a8e59e2": ("rename", ("product_bundle_rules",)),
    "zh_14b93ce275": ("rename", ("premium_payment_term",)),
    "zh_17a83223e4": ("rename", ("premium_payment_frequency",)),
    "zh_17e15e0c5a": ("N-A", ()),
    "zh_1a3227c6ce": ("rename", ("product_name",)),
    "zh_1a5675a37a": ("rename", ("coverage_term_category",)),
    "zh_1ec5e3f2cc": ("rename", ("surrender_and_cancellation_terms",)),
    "zh_23a2625781": ("N-A", ()),
    "zh_2df7d6256c": ("merge", ("eligible_occupation_classes",)),
    "zh_313cabffd8": ("rename", ("cooling_off_period",)),
    "zh_346f0dac8c": ("rename", ("external_publication_status",)),
    "zh_3a3e6520a3": ("rename", ("coverage_responsibilities",)),
    "zh_3d8424595d": ("rename", ("reimbursement_rate_rules",)),
    "zh_4a789b1d6f": ("rename", ("reimbursable_expense_scope",)),
    "zh_5162df17d8": ("rename", ("sales_status",)),
    "zh_52548821b9": ("rename", ("premium_adjustment_rules",)),
    "zh_540e1969e3": ("rename", ("covered_risk_categories",)),
    "zh_58d313ee26": ("rename", ("target_customer_profile",)),
    "zh_67ee7025ef": ("rename", ("policy_role",)),
    "zh_6a3bd6cdbf": ("rename", ("official_product_features",)),
    "zh_74aa1b9c93": ("rename", ("guaranteed_renewal_status",)),
    "zh_74fd5a9469": ("N-A", ()),
    "zh_7598a3116c": ("rename", ("coverage_period",)),
    "zh_789479e2d4": ("rename", ("sales_channels",)),
    "zh_7bf05bc576": ("rename", ("coverage_and_renewal_terms",)),
    "zh_7d7fe38f09": ("rename", ("cancer_medical_coverage",)),
    "zh_7fe8603c08": ("N-A", ()),
    "zh_89e518b987": ("rename", ("product_summary",)),
    "zh_8bd90889d3": ("rename", ("sales_start_date",)),
    "zh_a17bd1c3f3": ("N-A", ()),
    "zh_a271d96039": ("rename", ("policyholder_rights",)),
    "zh_ad4a95859a": ("rename", ("insurance_category",)),
    "zh_b4b770e114": ("rename", ("insured_eligibility",)),
    "zh_b7ceabc3c0": ("N-A", ()),
    "zh_c4f4b0d48a": ("rename", ("entry_age_range",)),
    "zh_c5187f228e": ("rename", ("outpatient_inpatient_scope",)),
    "zh_c588207763": ("merge", ("eligible_occupation_classes",)),
    "zh_ca6e0226c2": ("rename", ("guaranteed_renewal_period",)),
    "zh_d62301d84c": ("rename", ("premium_grace_period",)),
    "zh_dcae594f8b": ("N-A", ()),
    "zh_e1bea0527a": ("rename", ("special_coverage_and_exclusion_tags",)),
    "zh_f1de0de938": ("rename", ("sales_end_date",)),
    "zh_f32c510a5e": ("rename", ("eligible_hospital_scope",)),
    "zh_f558f0a88f": ("rename", ("waiting_period",)),
    "zh_f8cc996739": (
        "split",
        ("eligible_service_packages", "medical_service_benefits"),
    ),
    "zh_fd9a0b9fa3": ("rename", ("product_short_name",)),
}

_DRAFT71_MAPPING: Final[dict[str, tuple[MappingAction, tuple[str, ...]]]] = {
    "product_code": ("reuse", ("product_code",)),
    "product_short_name": ("reuse", ("product_short_name",)),
    "product_name": ("reuse", ("product_name",)),
    "sales_start_date": ("reuse", ("sales_start_date",)),
    "sales_end_date": ("reuse", ("sales_end_date",)),
    "product_line": ("rename", ("insurance_category",)),
    "product_design_type": ("rename", ("product_type",)),
    "sales_channels": ("reuse", ("sales_channels",)),
    "published_external": ("rename", ("external_publication_status",)),
    "sales_status": ("reuse", ("sales_status",)),
    "primary_or_rider": ("rename", ("policy_role",)),
    "product_summary": ("reuse", ("product_summary",)),
    "product_highlights": ("rename", ("official_product_features",)),
    "target_customer_group": ("rename", ("target_customer_profile",)),
    "policyholder_rights": ("reuse", ("policyholder_rights",)),
    "eligible_services": ("rename", ("eligible_service_packages",)),
    "premium_payment_term": ("reuse", ("premium_payment_term",)),
    "premium_payment_mode": ("rename", ("premium_payment_frequency",)),
    "hesitation_period": ("rename", ("cooling_off_period",)),
    "waiting_period": ("reuse", ("waiting_period",)),
    "grace_period": ("rename", ("premium_grace_period",)),
    "covered_risks": ("rename", ("covered_risk_categories",)),
    "product_bundling_rules": ("rename", ("product_bundle_rules",)),
    "coverage_period": ("reuse", ("coverage_period",)),
    "coverage_period_class": ("rename", ("coverage_term_category",)),
    "entry_age_range": ("reuse", ("entry_age_range",)),
    "fees": ("N-A", ()),
    "product_tier": ("N-A", ()),
    "policy_count": ("N-A", ()),
    "surrender_rate": ("N-A", ()),
    "claim_count": ("N-A", ()),
    "claim_paid_amount": ("N-A", ()),
    "insurance_period_and_renewal": ("rename", ("coverage_and_renewal_terms",)),
    "hesitation_and_surrender_terms": ("rename", ("surrender_and_cancellation_terms",)),
    "eligibility_scope": ("rename", ("insured_eligibility",)),
    "zero_deductible": ("rename", ("zero_deductible_flag",)),
    "cancer_medical_benefit": ("rename", ("cancer_medical_coverage",)),
    "coverage_summary": ("reuse", ("coverage_summary",)),
    "covered_age_groups": ("rename", ("age_segment_tags",)),
    "guaranteed_renewal": ("rename", ("guaranteed_renewal_status",)),
    "guaranteed_renewal_period": ("reuse", ("guaranteed_renewal_period",)),
    "social_security_unrestricted": ("rename", ("social_insurance_requirement",)),
    "high_risk_occupation_insurable": ("merge", ("eligible_occupation_classes",)),
    "insurable_occupation_classes": ("merge", ("eligible_occupation_classes",)),
    "coverage_scale_type": ("rename", ("coverage_limit_category",)),
    "deductible": ("rename", ("deductible_rules",)),
    "outpatient_inpatient_scope": ("reuse", ("outpatient_inpatient_scope",)),
    "value_added_services": ("rename", ("medical_service_benefits",)),
    "underwriting_mode": ("rename", ("underwriting_method",)),
    "allowance_benefits": ("N-A", ()),
    "benefit_limit": ("rename", ("coverage_responsibilities",)),
    "reimbursement_scope": ("rename", ("reimbursable_expense_scope",)),
    "reimbursement_ratio": ("rename", ("reimbursement_rate_rules",)),
    "hospital_scope": ("rename", ("eligible_hospital_scope",)),
    "indemnity_principle": ("reuse", ("indemnity_principle",)),
    "special_exclusion_relaxations": (
        "rename",
        ("special_coverage_and_exclusion_tags",),
    ),
    "high_end_medical_access": ("rename", ("premium_medical_facility_coverage",)),
    "product_conversion": ("rename", ("product_conversion_rules",)),
    "rate_adjustable": ("rename", ("premium_adjustment_rules",)),
    "regulatory_filing_no": ("N-A", ()),
    "clause_version": ("N-A", ()),
    "clause_effective_date": ("N-A", ()),
    "exclusions_official": ("rename", ("exclusions",)),
    "waiting_period_claim_handling": ("N-A", ()),
    "reinstatement": ("N-A", ()),
    "claim_filing_requirements": ("rename", ("claim_application_deadline_and_documents",)),
    "sales_region_limit": ("rename", ("geographic_eligibility_requirements",)),
    "reduced_paid_up": ("N-A", ()),
    "pre_existing_conditions": ("rename", ("pre_existing_condition_rules",)),
    "external_drug_coverage": ("rename", ("out_of_hospital_special_drug_coverage",)),
    "discontinuation_renewal": ("rename", ("post_discontinuation_renewal_arrangement",)),
}


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError("ANNOTATION_CANONICAL_VALUE_INVALID")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def schema67_human_annotation_kit_sha256(value: BaseModel | Mapping[str, object]) -> str:
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json", exclude={"kit_sha256"})
    else:
        payload = {key: item for key, item in value.items() if key != "kit_sha256"}
    return hashlib.sha256(
        _CONTRACT.encode("utf-8") + b"\0" + _canonical_json_bytes(payload)
    ).hexdigest()


def canonical_schema67_human_annotation_kit_bytes(
    kit: Schema67HumanAnnotationKit5961V1,
) -> bytes:
    return _canonical_json_bytes(kit.model_dump(mode="json")) + b"\n"


def _parse_exact_jsonl(
    payload: bytes, *, expected_sha256: str, expected_count: int
) -> tuple[dict[str, Any], ...]:
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise Schema67HumanAnnotationKitError("ANNOTATION_INPUT_IDENTITY_INVALID")
    try:
        rows = tuple(json.loads(line) for line in payload.splitlines() if line)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        raise Schema67HumanAnnotationKitError("ANNOTATION_INPUT_INVALID") from None
    if (
        len(rows) != expected_count
        or any(not isinstance(row, dict) for row in rows)
        or len({row.get("field_id") for row in rows}) != expected_count
    ):
        raise Schema67HumanAnnotationKitError("ANNOTATION_INPUT_INVALID")
    return rows


def _mapping_rows(
    *,
    source_dataset: Literal["old60", "draft71"],
    rows: Sequence[Mapping[str, Any]],
    mapping: Mapping[str, tuple[MappingAction, tuple[str, ...]]],
    ordered67: tuple[str, ...],
) -> tuple[AnnotationMappingDecisionV1, ...]:
    decisions: list[AnnotationMappingDecisionV1] = []
    for row in rows:
        source_field_id = row.get("field_id")
        if not isinstance(source_field_id, str) or source_field_id not in mapping:
            raise Schema67HumanAnnotationKitError("ANNOTATION_MAPPING_SOURCE_INVALID")
        action, targets = mapping[source_field_id]
        flags = set(row.get("flags", ()))
        old60 = source_dataset == "old60"
        decisions.append(
            AnnotationMappingDecisionV1(
                mapping_id=f"{source_dataset}:{len(decisions) + 1:03d}",
                source_dataset=source_dataset,
                source_field_id=source_field_id,
                source_display_name=row.get("field_name") if old60 else row.get("display_name"),
                target_field_ids=targets,
                action=action,
                source_authority_level=(
                    "HUMAN_APPROVED_S0_Q_MIGRATION_INPUT" if old60 else "MODEL_SUGGESTION"
                ),
                admission_status="PROPOSED_MIGRATION" if old60 else "MODEL_SUGGESTION",
                source_state_suggestion=row.get("tri_state"),
                source_risk_level=None if old60 else row.get("risk_level"),
                mandatory_human_review=(False if old60 else "mandatory_human_review" in flags),
                tri_state_conflict=(
                    False
                    if old60
                    else bool({"old_seed_disagreement", "old_seed_semantic_conflict"} & flags)
                ),
            )
        )
    covered = {target for item in decisions for target in item.target_field_ids}
    for target in ordered67:
        if target not in covered:
            decisions.append(
                AnnotationMappingDecisionV1(
                    mapping_id=f"{source_dataset}:{len(decisions) + 1:03d}",
                    source_dataset=source_dataset,
                    source_field_id=None,
                    source_display_name=None,
                    target_field_ids=(target,),
                    action="new",
                    source_authority_level=(
                        "HUMAN_APPROVED_S0_Q_MIGRATION_INPUT" if old60 else "MODEL_SUGGESTION"
                    ),
                    admission_status=("PROPOSED_MIGRATION" if old60 else "MODEL_SUGGESTION"),
                    source_state_suggestion=None,
                    source_risk_level=None,
                    mandatory_human_review=False,
                    tri_state_conflict=False,
                )
            )
    return tuple(decisions)


def _validate_mapping_topology(
    mappings: Sequence[AnnotationMappingDecisionV1],
    ordered67: tuple[str, ...],
) -> None:
    source_ids = [item.source_field_id for item in mappings if item.source_field_id]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("ANNOTATION_MAPPING_SOURCE_DUPLICATE")
    target_rows: dict[str, list[AnnotationMappingDecisionV1]] = {}
    for item in mappings:
        for target in item.target_field_ids:
            target_rows.setdefault(target, []).append(item)
    if set(target_rows) != set(ordered67):
        raise ValueError("ANNOTATION_MAPPING_TARGET_CLOSURE_INVALID")
    for rows in target_rows.values():
        if len(rows) > 1 and any(item.action != "merge" for item in rows):
            raise ValueError("ANNOTATION_MAPPING_TARGET_DUPLICATE")
        if len(rows) == 1 and rows[0].action == "merge":
            raise ValueError("ANNOTATION_MAPPING_MERGE_INCOMPLETE")


def _schema_pack_identity() -> AnnotationSchemaPackIdentityV1:
    pack = make_medical_schema_pack_596_1()
    return AnnotationSchemaPackIdentityV1(
        schema_pack_id="medical-schema67.v1",
        schema_pack_sha256=pack.schema_pack_sha256,
        ordered_field_ids=pack.ordered_field_ids,
        ordered_section_ids=MEDICAL_SECTION_IDS,
        section_field_counts=MEDICAL_SECTION_FIELD_COUNTS,
    )


def _source_revisions() -> tuple[AnnotationSourceRevisionV1, ...]:
    return (
        AnnotationSourceRevisionV1(
            role="terms",
            knowledge_id="f987fc16-222a-4246-8ca0-22c1a81dd6d9",
            parse_attempt=2,
            file_sha256="88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
            chunk_manifest_sha256="f2190b125469819ea0d97603c71f4fb19e4a92fa09117582b4d581947a0de414",
            chunk_count=162,
            page_count=39,
            revision_authority_status="PREFLIGHT_CURRENT_REVISION_ONLY",
            evidence_admission_status="PENDING_ATTEMPT_BOUND_SEAL",
        ),
        AnnotationSourceRevisionV1(
            role="brochure",
            knowledge_id="1265a343-c408-4620-8eed-c4f6a2adadc2",
            parse_attempt=1,
            file_sha256="5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
            chunk_manifest_sha256="9995d0f3f2962ec8a879e77ae3850bba0d34e5984d82356ae440cce695bb27ee",
            chunk_count=79,
            page_count=27,
            revision_authority_status="PREFLIGHT_CURRENT_REVISION_ONLY",
            evidence_admission_status="PENDING_ATTEMPT_BOUND_SEAL",
        ),
        AnnotationSourceRevisionV1(
            role="rate",
            knowledge_id="32402c40-6131-4049-8080-cc5b68188cd3",
            parse_attempt=1,
            file_sha256="7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
            chunk_manifest_sha256="26e6469fabf20d19ea53049573fb652cd0dce9a40df6e1b7ceebba12669e96ce",
            chunk_count=4,
            page_count=2,
            revision_authority_status="PREFLIGHT_CURRENT_REVISION_ONLY",
            evidence_admission_status="PENDING_ATTEMPT_BOUND_SEAL",
        ),
    )


def _reviewer_slots() -> tuple[ReviewerRoleSlotV1, ...]:
    roles = (
        ("annotator-primary", "schema-product-owner"),
        ("annotator-secondary", "medical-product-claims-sme"),
        ("actuarial-rate", "actuarial-rate-reviewer"),
        ("legal-compliance", "legal-compliance-reviewer"),
        ("data-custody-release", "data-custody-release-reviewer"),
        ("conflict-adjudicator", "named-human-adjudicator"),
    )
    return tuple(
        ReviewerRoleSlotV1(
            slot_id=slot_id,
            required_role=role,
            named_human_id="PENDING_NAMED_HUMAN_ID",
            decision_status="PENDING",
        )
        for slot_id, role in roles
    )


def build_schema67_human_annotation_kit_596_1(
    *, old60_bytes: bytes, draft71_bytes: bytes
) -> Schema67HumanAnnotationKit5961V1:
    old60 = _parse_exact_jsonl(old60_bytes, expected_sha256=_OLD60_SHA256, expected_count=60)
    draft71 = _parse_exact_jsonl(draft71_bytes, expected_sha256=_DRAFT71_SHA256, expected_count=71)
    schema_pack = _schema_pack_identity()
    old60_mappings = _mapping_rows(
        source_dataset="old60",
        rows=old60,
        mapping=_OLD60_MAPPING,
        ordered67=schema_pack.ordered_field_ids,
    )
    draft71_mappings = _mapping_rows(
        source_dataset="draft71",
        rows=draft71,
        mapping=_DRAFT71_MAPPING,
        ordered67=schema_pack.ordered_field_ids,
    )
    reviewer_slots = _reviewer_slots()
    payload: dict[str, object] = {
        "contract": _CONTRACT,
        "kit_status": "NON_AUTHORITATIVE_DRAFT",
        "product_version_id": "596-1",
        "generation_policy": "NO_MODEL_NO_MATERIAL_WIKI_NO_GOLDEN",
        "schema_pack": schema_pack,
        "old60_input": AnnotationInputIdentityV1(
            dataset_id="dataset/goldenset/gs-s0q-596-v1",
            sha256=_OLD60_SHA256,
            row_count=60,
            authority_level="HUMAN_APPROVED_S0_Q_MIGRATION_INPUT",
            admission_status="PROPOSED_MIGRATION",
            scope="S0-Q only; not production or machine_auto",
            related_digests=(
                RelatedDigestV1(
                    name="disputed.jsonl",
                    sha256="01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b",
                ),
                RelatedDigestV1(
                    name="review-and-approval.json",
                    sha256="484fdb78bdc73109bccd4d771e41089574b26f28c1992b67b2114524a515c868",
                ),
                RelatedDigestV1(
                    name="manifest.json",
                    sha256="d926cc3da4af4c531dffd05c12e5b8214fb8b79e50652ca5c30bd5db35f377c1",
                ),
            ),
        ),
        "draft71_input": AnnotationInputIdentityV1(
            dataset_id="dataset/goldenset-drafts/esheng-zunxiang-v0",
            sha256=_DRAFT71_SHA256,
            row_count=71,
            authority_level="MODEL_SUGGESTION",
            admission_status="MODEL_SUGGESTION",
            scope="non-authoritative draft; human review required",
        ),
        "old60_mappings": old60_mappings,
        "draft71_mappings": draft71_mappings,
        "source_revisions": _source_revisions(),
        "annotations": tuple(
            PendingSchema67AnnotationV1(field_id=field_id)
            for field_id in schema_pack.ordered_field_ids
        ),
        "special_pages": (
            SpecialPageWorkItemV1(
                role="terms",
                page=12,
                page_exists=True,
                prior_approved_quote_count=5,
                action="PENDING_RECAPTURE",
            ),
            SpecialPageWorkItemV1(
                role="terms",
                page=27,
                page_exists=True,
                prior_approved_quote_count=0,
                action="PENDING_HUMAN_SELECTION",
            ),
            SpecialPageWorkItemV1(
                role="brochure",
                page=12,
                page_exists=True,
                prior_approved_quote_count=0,
                action="PENDING_HUMAN_SELECTION",
            ),
            SpecialPageWorkItemV1(
                role="brochure",
                page=27,
                page_exists=True,
                prior_approved_quote_count=0,
                action="PENDING_HUMAN_SELECTION",
            ),
            SpecialPageWorkItemV1(
                role="rate",
                page=12,
                page_exists=False,
                prior_approved_quote_count=0,
                action="PROHIBITED_PAGE_OUT_OF_RANGE",
            ),
            SpecialPageWorkItemV1(
                role="rate",
                page=27,
                page_exists=False,
                prior_approved_quote_count=0,
                action="PROHIBITED_PAGE_OUT_OF_RANGE",
            ),
        ),
        "reviewer_slots": reviewer_slots,
        "whole_batch_receipt": WholeBatchReceiptTemplateV1(
            contract="schema67-golden-whole-batch-receipt-template-596-1.v1",
            status="PENDING",
            required_reviewer_slot_ids=tuple(slot.slot_id for slot in reviewer_slots),
        ),
    }
    payload["kit_sha256"] = schema67_human_annotation_kit_sha256(payload)
    try:
        return Schema67HumanAnnotationKit5961V1.model_validate(payload)
    except (ValidationError, TypeError, ValueError):
        raise Schema67HumanAnnotationKitError("ANNOTATION_KIT_INVALID") from None


def validate_schema67_human_annotation_kit_596_1(
    kit: Schema67HumanAnnotationKit5961V1,
    *,
    old60_bytes: bytes,
    draft71_bytes: bytes,
) -> Schema67HumanAnnotationKit5961V1:
    try:
        fresh = Schema67HumanAnnotationKit5961V1.model_validate(kit.model_dump(mode="python"))
    except (AttributeError, ValidationError, TypeError, ValueError):
        raise Schema67HumanAnnotationKitError("ANNOTATION_KIT_INVALID") from None
    expected = build_schema67_human_annotation_kit_596_1(
        old60_bytes=old60_bytes,
        draft71_bytes=draft71_bytes,
    )
    if fresh != kit or fresh != expected:
        raise Schema67HumanAnnotationKitError("ANNOTATION_KIT_AUTHORITY_INVALID")
    return kit


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("duplicate JSON key")
        values[key] = value
    return values


def load_schema67_human_annotation_kit_596_1(
    payload: bytes,
    *,
    old60_bytes: bytes,
    draft71_bytes: bytes,
) -> Schema67HumanAnnotationKit5961V1:
    try:
        decoded = json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
        if not isinstance(decoded, dict):
            raise ValueError("kit root must be an object")
        kit = Schema67HumanAnnotationKit5961V1.model_validate(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError, ValueError):
        raise Schema67HumanAnnotationKitError("ANNOTATION_KIT_WIRE_INVALID") from None
    if payload != canonical_schema67_human_annotation_kit_bytes(kit):
        raise Schema67HumanAnnotationKitError("ANNOTATION_KIT_WIRE_INVALID")
    return validate_schema67_human_annotation_kit_596_1(
        kit,
        old60_bytes=old60_bytes,
        draft71_bytes=draft71_bytes,
    )


def schema67_human_annotation_kit_safe_summary(
    kit: Schema67HumanAnnotationKit5961V1,
) -> Schema67HumanAnnotationKitSummary5961V1:
    return Schema67HumanAnnotationKitSummary5961V1(
        contract=_SUMMARY_CONTRACT,
        kit_status="NON_AUTHORITATIVE_DRAFT",
        field_count=len(kit.annotations),
        pending_field_count=sum(row.annotation_status == "PENDING" for row in kit.annotations),
        old60_source_count=sum(item.source_field_id is not None for item in kit.old60_mappings),
        draft71_source_count=sum(item.source_field_id is not None for item in kit.draft71_mappings),
        model_high_risk_count=sum(
            item.source_risk_level == "high" for item in kit.draft71_mappings
        ),
        mandatory_human_review_count=sum(
            item.mandatory_human_review for item in kit.draft71_mappings
        ),
        tri_state_conflict_count=sum(item.tri_state_conflict for item in kit.draft71_mappings),
        bbox_pending_count=sum(row.bbox_status == "PENDING_CAPTURE" for row in kit.annotations),
        reviewer_slot_count=len(kit.reviewer_slots),
        assigned_reviewer_count=0,
        approved_field_count=0,
        can_emit_approved_golden=False,
    )


__all__ = [
    "AnnotationMappingDecisionV1",
    "AnnotationSourceRevisionV1",
    "PendingSchema67AnnotationV1",
    "ReviewerRoleSlotV1",
    "Schema67HumanAnnotationKit5961V1",
    "Schema67HumanAnnotationKitError",
    "Schema67HumanAnnotationKitSummary5961V1",
    "SpecialPageWorkItemV1",
    "WholeBatchReceiptTemplateV1",
    "build_schema67_human_annotation_kit_596_1",
    "canonical_schema67_human_annotation_kit_bytes",
    "load_schema67_human_annotation_kit_596_1",
    "schema67_human_annotation_kit_safe_summary",
    "schema67_human_annotation_kit_sha256",
    "validate_schema67_human_annotation_kit_596_1",
]
