"""Pure extraction-task identities for OpenSpec 054 Stage 2.

These frozen DTOs bind the merged 052 profile and policy receipts but remain
non-authoritative domain facts. Parsed artifacts stay behind one protocol seam
until the separate OpenSpec 053 interface is committed.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.material_profiles import (
    MATERIAL_PROFILE_BINDING_OBJECT_TYPE,
    FieldAuthority,
    MaterialProfile,
    ParsePolicyReceipt,
)
from insurance_harness.compiler.parsed_documents import (
    PARSE_MANIFEST_OBJECT_TYPE,
    PARSE_QUALITY_DECISION_OBJECT_TYPE,
    PARSED_DOCUMENT_OBJECT_TYPE,
    ParsedDocumentV1,
    ParseManifestV1,
    ParseQualityDecisionV1,
    build_parse_manifest,
)

NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=512, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
MaterialRole = Literal["terms", "brochure", "rate_table"]

EXTRACTION_TASK_OBJECT_TYPE: Final[str] = "extraction-task.v1"
EXTRACTION_TASK_PROFILE_OBJECT_TYPE: Final[str] = "extraction-task-profile.v1"
_FORBIDDEN_BROAD_IDENTITIES: Final[frozenset[str]] = frozenset(
    {"*", "all", "any", "unknown", "whole_product"}
)
_FORBIDDEN_GLOB_CHARACTERS: Final[frozenset[str]] = frozenset("*?[]{}")
_FORBIDDEN_INPUT_MARKERS: Final[tuple[str, ...]] = (
    "golden",
    "provider",
    "prediction",
    "release",
    "approval",
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class ExtractionAdmissionError(ValueError):
    """Typed rejection at the exact 053-to-054 composition boundary."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _identity_is_wildcard(value: str) -> bool:
    folded = value.casefold()
    if folded in _FORBIDDEN_BROAD_IDENTITIES or any(
        character in _FORBIDDEN_GLOB_CHARACTERS for character in folded
    ):
        return True
    for separator in ("-", ".", ":", "/"):
        folded = folded.replace(separator, "_")
    tokens = tuple(token for token in folded.split("_") if token)
    return any(token in {"all", "any", "unknown"} for token in tokens) or (
        "whole" in tokens and "product" in tokens
    )


class ArtifactRefV1(_FrozenModel):
    """Opaque C0 identity; it conveys no admission or execution authority."""

    object_type: NonBlankStr
    artifact_hash: Sha256Hex

    @field_validator("object_type")
    @classmethod
    def reject_forbidden_inputs(cls, value: str) -> str:
        if any(marker in value.casefold() for marker in _FORBIDDEN_INPUT_MARKERS):
            raise ValueError("forbidden_extraction_input")
        return value


class ExtractionInputRefsV1(_FrozenModel):
    """Opaque identities only; no mutable 053 fields are mirrored here."""

    source_revision: ArtifactRefV1
    material_profile: ArtifactRefV1
    resolved_template: ArtifactRefV1
    schema_contract: ArtifactRefV1
    parsed_document: ArtifactRefV1
    parse_manifest: ArtifactRefV1
    parse_quality_decision: ArtifactRefV1


class AttemptBudgetV1(_FrozenModel):
    max_fields: PositiveInt
    max_total_attempts: Literal[1, 2]
    max_targeted_repairs: Literal[0, 1]

    @model_validator(mode="after")
    def require_exact_attempt_budget(self) -> Self:
        if self.max_total_attempts != 1 + self.max_targeted_repairs:
            raise ValueError("invalid_attempt_budget")
        return self


def _task_profile_payload(
    *,
    material_profile: MaterialProfile,
    material_profile_binding_hash: str,
    parse_policy_receipt: ParsePolicyReceipt,
    field_authority: FieldAuthority,
    authority_mode: Literal["primary", "support"],
    attempt_budget: AttemptBudgetV1,
) -> dict[str, object]:
    return {
        "material_profile": material_profile.model_dump(mode="python"),
        "material_profile_binding_hash": material_profile_binding_hash,
        "parse_policy_receipt": parse_policy_receipt.model_dump(mode="python"),
        "field_authority": field_authority.model_dump(mode="python"),
        "authority_mode": authority_mode,
        "attempt_budget": attempt_budget.model_dump(mode="python"),
    }


class ExtractionTaskProfileV1(_FrozenModel):
    """Exact 052-backed task profile; it grants no parse admission authority."""

    material_profile: MaterialProfile
    material_profile_binding_hash: Sha256Hex
    parse_policy_receipt: ParsePolicyReceipt
    field_authority: FieldAuthority
    authority_mode: Literal["primary", "support"]
    attempt_budget: AttemptBudgetV1
    profile_hash: Sha256Hex

    @model_validator(mode="after")
    def require_exact_052_binding(self) -> Self:
        expected_receipt = {
            **self.material_profile.parse_policy.model_dump(mode="python"),
            "required_parse_capabilities": (
                self.material_profile.required_parse_capabilities
            ),
        }
        if self.parse_policy_receipt.model_dump(mode="python") != expected_receipt:
            raise ValueError("parse_policy_receipt_mismatch")
        role = self.material_profile.material_role
        expected_mode: Literal["primary", "support"]
        if role == self.field_authority.primary_role:
            expected_mode = "primary"
        elif role in self.field_authority.support_roles:
            expected_mode = "support"
        else:
            raise ValueError("field_authority_not_applicable")
        if self.authority_mode != expected_mode:
            raise ValueError("field_authority_mode_mismatch")
        if (
            self.attempt_budget.max_total_attempts != 2
            or self.attempt_budget.max_targeted_repairs != 1
        ):
            raise ValueError("targeted_repair_boundary_mismatch")
        payload = _task_profile_payload(
            material_profile=self.material_profile,
            material_profile_binding_hash=self.material_profile_binding_hash,
            parse_policy_receipt=self.parse_policy_receipt,
            field_authority=self.field_authority,
            authority_mode=self.authority_mode,
            attempt_budget=self.attempt_budget,
        )
        if self.profile_hash != canonical_hash(
            EXTRACTION_TASK_PROFILE_OBJECT_TYPE, payload
        ):
            raise ValueError("task_profile_hash_mismatch")
        return self


def build_extraction_task_profile(
    *,
    material_profile: MaterialProfile,
    material_profile_binding_hash: str,
    parse_policy_receipt: ParsePolicyReceipt,
    field_authority: FieldAuthority,
    attempt_budget: AttemptBudgetV1,
) -> ExtractionTaskProfileV1:
    """Freeze safe public 052 facts without importing Golden or 053 DTOs."""

    role = material_profile.material_role
    if role == field_authority.primary_role:
        authority_mode: Literal["primary", "support"] = "primary"
    elif role in field_authority.support_roles:
        authority_mode = "support"
    else:
        authority_mode = "primary"  # rejected by the validated model
    payload = _task_profile_payload(
        material_profile=material_profile,
        material_profile_binding_hash=material_profile_binding_hash,
        parse_policy_receipt=parse_policy_receipt,
        field_authority=field_authority,
        authority_mode=authority_mode,
        attempt_budget=attempt_budget,
    )
    return ExtractionTaskProfileV1.model_validate(
        {
            **payload,
            "profile_hash": canonical_hash(
                EXTRACTION_TASK_PROFILE_OBJECT_TYPE, payload
            ),
        }
    )


class ParsedArtifactAdmissionPort:
    """The single exact adapter from admitted 053 DTOs to opaque task refs."""

    def admitted_input_refs(
        self,
        *,
        task_profile: ExtractionTaskProfileV1,
        space_id: str,
        product_version_id: str,
        source_revision_id: str,
        source_revision: ArtifactRefV1,
        resolved_template: ArtifactRefV1,
        schema_contract: ArtifactRefV1,
        document: ParsedDocumentV1,
        manifest: ParseManifestV1,
        quality_decision: ParseQualityDecisionV1,
    ) -> ExtractionInputRefsV1:
        try:
            document = ParsedDocumentV1.model_validate(document)
            manifest = ParseManifestV1.model_validate(manifest)
            quality_decision = ParseQualityDecisionV1.model_validate(
                quality_decision
            )
            expected_manifest = build_parse_manifest(
                document,
                task_profile.material_profile,
            )
        except ValueError as error:
            raise ExtractionAdmissionError(
                "parse_artifact_admission_mismatch"
            ) from error

        subject = document.subject
        receipt = task_profile.parse_policy_receipt
        measured = quality_decision.measured_facts
        expected_parser_profile = (
            receipt.default_parser_profile_ref
            if document.attempt.attempt_number == 1
            else receipt.bounded_upgrade_profile_ref
        )
        expected_attempts_exhausted = (
            document.attempt.attempt_number >= receipt.max_parser_attempts
        )
        if (
            manifest != expected_manifest
            or expected_parser_profile is None
            or document.parser.parser_profile_ref != expected_parser_profile
            or document.output_facts.privacy_policy_ref
            != receipt.privacy_policy_ref
            or document.output_facts.output_policy_ref != receipt.output_policy_ref
            or manifest.output_facts.privacy_policy_ref != receipt.privacy_policy_ref
            or manifest.output_facts.output_policy_ref != receipt.output_policy_ref
            or not document.snapshot.pagination_complete
            or not manifest.snapshot.pagination_complete
            or quality_decision.decision != "ADMIT"
            or quality_decision.subject != subject
            or quality_decision.manifest_hash != manifest.manifest_hash
            or quality_decision.parse_policy_receipt != receipt
            or quality_decision.admitted_attempt_id != document.attempt.attempt_id
            or measured.required_capabilities != manifest.required_capabilities
            or measured.satisfied_capabilities != manifest.satisfied_capabilities
            or measured.unsatisfied_capabilities != manifest.unsatisfied_capabilities
            or measured.trigger_conditions
            or measured.attempts_exhausted != expected_attempts_exhausted
            or manifest.unsatisfied_capabilities
            or subject.space_id != space_id
            or subject.product_version_id != product_version_id
            or subject.source_revision_id != source_revision_id
            or subject.material_profile_id
            != task_profile.material_profile.profile_id
            or subject.material_profile_binding_hash
            != task_profile.material_profile_binding_hash
            or subject.source_sha256 != task_profile.material_profile.source.sha256
        ):
            raise ExtractionAdmissionError("parse_artifact_admission_mismatch")

        return ExtractionInputRefsV1(
            source_revision=source_revision,
            material_profile=ArtifactRefV1(
                object_type=MATERIAL_PROFILE_BINDING_OBJECT_TYPE,
                artifact_hash=task_profile.material_profile_binding_hash,
            ),
            resolved_template=resolved_template,
            schema_contract=schema_contract,
            parsed_document=ArtifactRefV1(
                object_type=PARSED_DOCUMENT_OBJECT_TYPE,
                artifact_hash=document.document_hash,
            ),
            parse_manifest=ArtifactRefV1(
                object_type=PARSE_MANIFEST_OBJECT_TYPE,
                artifact_hash=manifest.manifest_hash,
            ),
            parse_quality_decision=ArtifactRefV1(
                object_type=PARSE_QUALITY_DECISION_OBJECT_TYPE,
                artifact_hash=quality_decision.decision_hash,
            ),
        )


def _task_payload(
    *,
    space_id: str,
    product_version_id: str,
    source_revision_id: str,
    material_role: MaterialRole,
    module_id: str,
    risk_partition_id: str,
    field_ids: tuple[str, ...],
    input_refs: ExtractionInputRefsV1,
    budget: AttemptBudgetV1,
    task_profile: ExtractionTaskProfileV1,
) -> dict[str, object]:
    return {
        "space_id": space_id,
        "product_version_id": product_version_id,
        "source_revision_id": source_revision_id,
        "material_role": material_role,
        "module_id": module_id,
        "risk_partition_id": risk_partition_id,
        "field_ids": field_ids,
        "input_refs": input_refs.model_dump(mode="python"),
        "budget": budget.model_dump(mode="python"),
        "task_profile": task_profile.model_dump(mode="python"),
    }


class ExtractionTaskV1(_FrozenModel):
    space_id: NonBlankStr
    product_version_id: NonBlankStr
    source_revision_id: NonBlankStr
    material_role: MaterialRole
    module_id: NonBlankStr
    risk_partition_id: NonBlankStr
    field_ids: tuple[NonBlankStr, ...]
    input_refs: ExtractionInputRefsV1
    budget: AttemptBudgetV1
    task_profile: ExtractionTaskProfileV1
    task_hash: Sha256Hex

    @model_validator(mode="after")
    def require_exact_identity_and_hash(self) -> Self:
        identities = (
            self.space_id,
            self.product_version_id,
            self.source_revision_id,
            self.module_id,
            self.risk_partition_id,
        )
        if any(_identity_is_wildcard(value) for value in identities):
            raise ValueError("invalid_task_identity")
        if (
            not self.field_ids
            or len(self.field_ids) != len(set(self.field_ids))
            or self.field_ids != tuple(sorted(self.field_ids))
            or len(self.field_ids) > self.budget.max_fields
        ):
            raise ValueError("invalid_task_field_partition")
        profile = self.task_profile
        if (
            self.material_role != profile.material_profile.material_role
            or self.budget != profile.attempt_budget
            or self.input_refs.material_profile.artifact_hash
            != profile.material_profile_binding_hash
            or self.input_refs.material_profile.object_type
            != MATERIAL_PROFILE_BINDING_OBJECT_TYPE
            or not set(self.field_ids).issubset(profile.field_authority.field_ids)
        ):
            raise ValueError("task_profile_binding_mismatch")
        expected_hash = canonical_hash(
            EXTRACTION_TASK_OBJECT_TYPE,
            _task_payload(
                space_id=self.space_id,
                product_version_id=self.product_version_id,
                source_revision_id=self.source_revision_id,
                material_role=self.material_role,
                module_id=self.module_id,
                risk_partition_id=self.risk_partition_id,
                field_ids=self.field_ids,
                input_refs=self.input_refs,
                budget=self.budget,
                task_profile=self.task_profile,
            ),
        )
        if self.task_hash != expected_hash:
            raise ValueError("task_hash_mismatch")
        return self


def build_extraction_task(
    *,
    space_id: str,
    product_version_id: str,
    source_revision_id: str,
    material_role: MaterialRole,
    module_id: str,
    risk_partition_id: str,
    field_ids: tuple[str, ...],
    input_refs: ExtractionInputRefsV1,
    budget: AttemptBudgetV1,
    task_profile: ExtractionTaskProfileV1,
) -> ExtractionTaskV1:
    """Build one deterministic non-authoritative task identity."""

    payload = _task_payload(
        space_id=space_id,
        product_version_id=product_version_id,
        source_revision_id=source_revision_id,
        material_role=material_role,
        module_id=module_id,
        risk_partition_id=risk_partition_id,
        field_ids=field_ids,
        input_refs=input_refs,
        budget=budget,
        task_profile=task_profile,
    )
    return ExtractionTaskV1.model_validate(
        {**payload, "task_hash": canonical_hash(EXTRACTION_TASK_OBJECT_TYPE, payload)}
    )
