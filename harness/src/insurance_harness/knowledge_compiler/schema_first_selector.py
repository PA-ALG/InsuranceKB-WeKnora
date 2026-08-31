"""Exact schema-first MaterialProfile and TemplatePackage selection for 119."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Final, Literal, Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.canonical import canonical_hash
from insurance_harness.knowledge_compiler.schema_first_contracts import (
    ApprovedSchemaSnapshotV1,
    FieldContractSetV1,
    GenericFactEnvelopeV1,
    SchemaFirstContractError,
    compile_schema_contracts,
)
from insurance_harness.template_packages import (
    EvidencePolicy,
    FieldGroup,
    ProvenanceReceipt,
    ResolutionRequest,
    ResolvedTemplate,
    TemplateApproval,
    TemplateCatalog,
    TemplateCatalogEntry,
    TemplatePackageContent,
    TemplateResolutionError,
    TemplateScope,
    TemplateVersion,
    ValidatorRef,
    resolve_template,
)

NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=512, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
MaterialRole = Literal["terms", "brochure", "rate_table"]
ApprovalState = Literal["approved", "pending", "revoked"]
SelectionStatus = Literal["SCHEMA_BOUND", "GENERIC_FACT_FALLBACK", "BLOCKED"]
_EXECUTABLE_MATERIAL_ROLES = frozenset({"terms", "brochure", "rate_table"})

_PROFILE_OBJECT_TYPE = "schema67-approved-material-profile.v1"
_SELECTION_OBJECT_TYPE = "schema67-compilation-selection.v1"
_APPROVED_CONTRACT_SET_SHA256: Final[str] = (
    "c51d4a01ee90177397b8a5f14c35a0a3ee8cad5bd175c5f94826639792d92f0c"
)
_APPROVED_PRODUCT_LINE_ID: Final[str] = "medical"
_APPROVED_PRODUCT_FAMILY_ID: Final[str] = "pingan-eshengbao-zunxiang-medical"
_APPROVED_PROFILE_BINDINGS: Final[tuple[tuple[MaterialRole, str, str], ...]] = (
    ("terms", "596-1-terms-v1", "insurance-terms"),
    ("brochure", "596-1-brochure-v1", "product-brochure"),
    ("rate_table", "596-1-rate-table-v1", "rate-table"),
)
APPROVED_596_1_TEMPLATE_CONTENT_HASHES: Final[tuple[tuple[MaterialRole, str], ...]] = (
    ("terms", "8d9c3b2897007200c700203bb0ff0824481281ea36b323d7432647214bc039b1"),
    ("brochure", "c33dd5d20d577c3c3d79419b35a2d9843ea13aa91cea130e334c93d846e170a7"),
    ("rate_table", "26c37ab91ce4f885087eafc6c70b2d56c10a9b76416cecf7042bfdd6076fbf9c"),
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


def approved_material_profile_sha256(
    *,
    profile_id: str,
    approval_state: ApprovalState,
    product_version_id: str,
    schema_contract_sha256: str,
    material_role: MaterialRole,
    product_line_id: str,
    document_type_id: str,
    product_family_id: str,
    required_field_ids: tuple[str, ...],
) -> str:
    return canonical_hash(
        _PROFILE_OBJECT_TYPE,
        {
            "profile_id": profile_id,
            "approval_state": approval_state,
            "product_version_id": product_version_id,
            "schema_contract_sha256": schema_contract_sha256,
            "material_role": material_role,
            "product_line_id": product_line_id,
            "document_type_id": document_type_id,
            "product_family_id": product_family_id,
            "required_field_ids": required_field_ids,
        },
    )


class ApprovedMaterialProfileV1(_FrozenModel):
    profile_id: NonBlankStr
    approval_state: ApprovalState
    product_version_id: NonBlankStr
    schema_contract_sha256: Sha256Hex
    material_role: MaterialRole
    product_line_id: NonBlankStr
    document_type_id: NonBlankStr
    product_family_id: NonBlankStr
    required_field_ids: tuple[NonBlankStr, ...]
    profile_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_exact_profile_hash(self) -> Self:
        if not self.required_field_ids or len(self.required_field_ids) != len(
            set(self.required_field_ids)
        ):
            raise ValueError("profile field IDs must be non-empty and unique")
        expected = approved_material_profile_sha256(
            profile_id=self.profile_id,
            approval_state=self.approval_state,
            product_version_id=self.product_version_id,
            schema_contract_sha256=self.schema_contract_sha256,
            material_role=self.material_role,
            product_line_id=self.product_line_id,
            document_type_id=self.document_type_id,
            product_family_id=self.product_family_id,
            required_field_ids=self.required_field_ids,
        )
        if self.profile_sha256 != expected:
            raise ValueError("material profile hash mismatch")
        return self


class MaterialProfileCatalogPort(Protocol):
    """Return approved candidates for one exact product/material identity."""

    def list_approved(
        self, *, product_version_id: str, material_role: str
    ) -> tuple[ApprovedMaterialProfileV1, ...]: ...


@dataclass(frozen=True, slots=True)
class _Fixed5961Schema67MaterialProfileCatalog:
    profiles: tuple[ApprovedMaterialProfileV1, ...]

    def list_approved(
        self, *, product_version_id: str, material_role: str
    ) -> tuple[ApprovedMaterialProfileV1, ...]:
        if type(product_version_id) is not str or type(material_role) is not str:
            return ()
        return tuple(
            profile
            for profile in self.profiles
            if profile.product_version_id == product_version_id
            and profile.material_role == material_role
            and profile.approval_state == "approved"
        )


@dataclass(frozen=True, slots=True)
class _Fixed5961Schema67TemplateCatalog:
    entries: tuple[TemplateCatalogEntry, ...]

    def get_approved(self, scope: TemplateScope) -> TemplateCatalogEntry | None:
        if type(scope) is not TemplateScope:
            return None
        matches = tuple(entry for entry in self.entries if entry.version.scope == scope)
        return matches[0] if len(matches) == 1 else None


class SchemaCompilationRequestV1(_FrozenModel):
    space_id: NonBlankStr
    product_version_id: NonBlankStr
    material_role: MaterialRole
    schema_snapshot: ApprovedSchemaSnapshotV1 | None
    generic_fact: GenericFactEnvelopeV1 | None


class SchemaCompilationSelectionV1(_FrozenModel):
    status: SelectionStatus
    reason_codes: tuple[NonBlankStr, ...]
    field_contracts: FieldContractSetV1 | None
    material_profile: ApprovedMaterialProfileV1 | None
    resolved_template: ResolvedTemplate | None
    generic_fact: GenericFactEnvelopeV1 | None
    material_field_ids: tuple[NonBlankStr, ...]
    synthesis_field_ids: tuple[NonBlankStr, ...]
    deferred_unknown_field_ids: tuple[NonBlankStr, ...]
    selection_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_result_shape_and_hash(self) -> Self:
        if self.status == "SCHEMA_BOUND":
            valid_shape = (
                not self.reason_codes
                and self.field_contracts is not None
                and self.material_profile is not None
                and self.resolved_template is not None
                and self.generic_fact is None
                and bool(self.material_field_ids)
            )
        elif self.status == "GENERIC_FACT_FALLBACK":
            valid_shape = (
                not self.reason_codes
                and self.field_contracts is None
                and self.material_profile is None
                and self.resolved_template is None
                and self.generic_fact is not None
                and not self.material_field_ids
                and not self.synthesis_field_ids
                and not self.deferred_unknown_field_ids
            )
        else:
            valid_shape = (
                bool(self.reason_codes)
                and self.field_contracts is None
                and self.material_profile is None
                and self.resolved_template is None
                and self.generic_fact is None
                and not self.material_field_ids
                and not self.synthesis_field_ids
                and not self.deferred_unknown_field_ids
            )
        if not valid_shape:
            raise ValueError("schema selection result shape mismatch")
        if self.status == "SCHEMA_BOUND":
            assert self.field_contracts is not None
            ordered = tuple(item.field_id for item in self.field_contracts.contracts)
            groups = (
                self.material_field_ids,
                self.synthesis_field_ids,
                self.deferred_unknown_field_ids,
            )
            if (
                any(len(group) != len(set(group)) for group in groups)
                or any(
                    group != tuple(item for item in ordered if item in group) for group in groups
                )
                or sum(len(group) for group in groups)
                != len(set().union(*(set(group) for group in groups)))
                or not set().union(*(set(group) for group in groups)) <= set(ordered)
            ):
                raise ValueError("schema task field partition mismatch")
        if self.selection_sha256 != canonical_hash(
            _SELECTION_OBJECT_TYPE, _selection_payload(self)
        ):
            raise ValueError("schema selection result hash mismatch")
        return self


def _selection_payload(value: SchemaCompilationSelectionV1) -> dict[str, object]:
    resolved = value.resolved_template
    return {
        "status": value.status,
        "reason_codes": value.reason_codes,
        "field_contract_set_sha256": (
            value.field_contracts.contract_set_sha256 if value.field_contracts is not None else None
        ),
        "material_profile_sha256": (
            value.material_profile.profile_sha256 if value.material_profile is not None else None
        ),
        "resolved_template": (
            {
                "content_hash": resolved.content_hash,
                "source_chain": tuple(
                    {
                        "scope": source.scope.model_dump(mode="python"),
                        "package_id": source.package_id,
                        "version_id": source.version_id,
                        "content_hash": source.content_hash,
                    }
                    for source in resolved.source_chain
                ),
            }
            if resolved is not None
            else None
        ),
        "generic_fact_sha256": (
            value.generic_fact.envelope_sha256 if value.generic_fact is not None else None
        ),
        "material_field_ids": value.material_field_ids,
        "synthesis_field_ids": value.synthesis_field_ids,
        "deferred_unknown_field_ids": value.deferred_unknown_field_ids,
    }


def _result(
    status: SelectionStatus,
    *,
    reasons: tuple[str, ...] = (),
    field_contracts: FieldContractSetV1 | None = None,
    material_profile: ApprovedMaterialProfileV1 | None = None,
    resolved_template: ResolvedTemplate | None = None,
    generic_fact: GenericFactEnvelopeV1 | None = None,
    material_field_ids: tuple[str, ...] = (),
    synthesis_field_ids: tuple[str, ...] = (),
    deferred_unknown_field_ids: tuple[str, ...] = (),
) -> SchemaCompilationSelectionV1:
    draft = SchemaCompilationSelectionV1.model_construct(
        status=status,
        reason_codes=reasons,
        field_contracts=field_contracts,
        material_profile=material_profile,
        resolved_template=resolved_template,
        generic_fact=generic_fact,
        material_field_ids=material_field_ids,
        synthesis_field_ids=synthesis_field_ids,
        deferred_unknown_field_ids=deferred_unknown_field_ids,
        selection_sha256="0" * 64,
    )
    return SchemaCompilationSelectionV1(
        status=status,
        reason_codes=reasons,
        field_contracts=field_contracts,
        material_profile=material_profile,
        resolved_template=resolved_template,
        generic_fact=generic_fact,
        material_field_ids=material_field_ids,
        synthesis_field_ids=synthesis_field_ids,
        deferred_unknown_field_ids=deferred_unknown_field_ids,
        selection_sha256=canonical_hash(_SELECTION_OBJECT_TYPE, _selection_payload(draft)),
    )


def _canonical_request(value: object) -> SchemaCompilationRequestV1 | None:
    try:
        if type(value) is not SchemaCompilationRequestV1:
            return None
        return SchemaCompilationRequestV1.model_validate(
            value.model_dump(mode="python", round_trip=True)
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        return None


def _canonical_profile(value: object) -> ApprovedMaterialProfileV1 | None:
    try:
        if type(value) is not ApprovedMaterialProfileV1:
            return None
        return ApprovedMaterialProfileV1.model_validate(
            value.model_dump(mode="python", round_trip=True)
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        return None


def _field_task_partition(
    contracts: FieldContractSetV1, material_role: MaterialRole
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    material: list[str] = []
    synthesis: list[str] = []
    deferred: list[str] = []
    for contract in contracts.contracts:
        roles = frozenset(contract.source_roles)
        if roles == {material_role}:
            material.append(contract.field_id)
        elif len(roles) > 1 and roles <= _EXECUTABLE_MATERIAL_ROLES:
            synthesis.append(contract.field_id)
        elif roles <= _EXECUTABLE_MATERIAL_ROLES:
            continue
        else:
            deferred.append(contract.field_id)
    return tuple(material), tuple(synthesis), tuple(deferred)


def _exact_596_1_contract_set(value: object) -> FieldContractSetV1:
    try:
        if type(value) is not FieldContractSetV1:
            raise TypeError("exact FieldContractSetV1 required")
        checked = FieldContractSetV1.model_validate(
            value.model_dump(mode="python", round_trip=True)
        )
        role_counts = tuple(
            len(_field_task_partition(checked, role)[0])
            for role, _profile_id, _document_type_id in _APPROVED_PROFILE_BINDINGS
        )
        if checked.contract_set_sha256 != _APPROVED_CONTRACT_SET_SHA256 or role_counts != (
            35,
            4,
            1,
        ):
            raise ValueError("contract authority mismatch")
        return checked
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise ValueError("SCHEMA67_CATALOG_INVALID") from None


def _build_approved_profile(
    contracts: FieldContractSetV1,
    *,
    role: MaterialRole,
    profile_id: str,
    document_type_id: str,
) -> ApprovedMaterialProfileV1:
    field_ids = _field_task_partition(contracts, role)[0]
    profile_hash = approved_material_profile_sha256(
        profile_id=profile_id,
        approval_state="approved",
        product_version_id=contracts.product_version_id,
        schema_contract_sha256=contracts.contract_set_sha256,
        material_role=role,
        product_line_id=_APPROVED_PRODUCT_LINE_ID,
        document_type_id=document_type_id,
        product_family_id=_APPROVED_PRODUCT_FAMILY_ID,
        required_field_ids=field_ids,
    )
    return ApprovedMaterialProfileV1(
        profile_id=profile_id,
        approval_state="approved",
        product_version_id=contracts.product_version_id,
        schema_contract_sha256=contracts.contract_set_sha256,
        material_role=role,
        product_line_id=_APPROVED_PRODUCT_LINE_ID,
        document_type_id=document_type_id,
        product_family_id=_APPROVED_PRODUCT_FAMILY_ID,
        required_field_ids=field_ids,
        profile_sha256=profile_hash,
    )


def build_596_1_schema67_material_profile_catalog(
    field_contracts: FieldContractSetV1,
) -> MaterialProfileCatalogPort:
    """Return the closed three-role catalog for the approved 596-1 Schema67 slice."""

    contracts = _exact_596_1_contract_set(field_contracts)
    return _Fixed5961Schema67MaterialProfileCatalog(
        profiles=tuple(
            _build_approved_profile(
                contracts,
                role=role,
                profile_id=profile_id,
                document_type_id=document_type_id,
            )
            for role, profile_id, document_type_id in _APPROVED_PROFILE_BINDINGS
        )
    )


def _build_approved_template_content(
    *, role: MaterialRole, field_ids: tuple[str, ...]
) -> TemplatePackageContent:
    return TemplatePackageContent(
        schema_version="medical-schema67.v1",
        field_groups=(
            FieldGroup(
                group_id=f"schema67-{role}-fields",
                field_ids=field_ids,
                evidence_roles=(role,),
            ),
        ),
        role_prompts={
            "extract": (
                f"Extract only approved 596-1 Schema67 {role} fields with replayable Evidence."
            )
        },
        validators=(
            ValidatorRef(
                validator_id="schema67-evidence-validator",
                validator_version="119.v1",
                config_hash=_APPROVED_CONTRACT_SET_SHA256,
            ),
        ),
        evidence_policy=EvidencePolicy(
            require_quote=True,
            require_locator=True,
            minimum_sources=1,
        ),
        attempt_limits={"extract": 1},
        golden_slice_ref="schema67-approved-contracts-no-runtime-answers",
        provenance=(
            ProvenanceReceipt(
                migration_id=f"MIG-119-SCHEMA67-{role.upper()}",
                source_repository="PA-ALG/InsuranceKB-WeKnora",
                source_branch="main",
                source_commit="2f356368342d2d4578e18315a9fedf739ab73190",
                source_path="frontend/src/lib/product-catalog-modules.ts",
                source_language="typescript",
                rights_status="project-owned",
                accepted_behavior="exact approved 596-1 material role and field subset routing",
                rejected_behavior=(
                    "fuzzy dispatch, runtime answer custody, and cross-role field duplication"
                ),
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


def build_596_1_schema67_template_catalog(
    *,
    space_id: str,
    field_contracts: FieldContractSetV1,
) -> TemplateCatalog:
    """Return approved document-type templates shared by A and 052 resolution."""

    contracts = _exact_596_1_contract_set(field_contracts)
    expected_hashes = dict(APPROVED_596_1_TEMPLATE_CONTENT_HASHES)
    entries: list[TemplateCatalogEntry] = []
    try:
        for role, _profile_id, document_type_id in _APPROVED_PROFILE_BINDINGS:
            content = _build_approved_template_content(
                role=role,
                field_ids=_field_task_partition(contracts, role)[0],
            )
            scope = TemplateScope(
                space_id=space_id,
                level="document-type",
                product_line_id=_APPROVED_PRODUCT_LINE_ID,
                document_type_id=document_type_id,
            )
            version = TemplateVersion.from_content(
                package_id=f"schema67-596-1-{role}",
                version_id=f"119-schema67-{role}.v1",
                scope=scope,
                content=content,
            )
            if version.content_hash != expected_hashes[role]:
                raise ValueError("approved template content hash mismatch")
            entries.append(
                TemplateCatalogEntry(
                    version=version,
                    approval=TemplateApproval(
                        approval_id=f"119-schema67-{role}-approved",
                        package_id=version.package_id,
                        version_id=version.version_id,
                        scope=scope,
                        content_hash=expected_hashes[role],
                        state="approved",
                    ),
                )
            )
    except (KeyError, TypeError, ValueError, ValidationError):
        raise ValueError("SCHEMA67_CATALOG_INVALID") from None
    return _Fixed5961Schema67TemplateCatalog(entries=tuple(entries))


def select_schema_compilation(
    *,
    request: SchemaCompilationRequestV1,
    material_profiles: MaterialProfileCatalogPort,
    template_catalog: TemplateCatalog,
) -> SchemaCompilationSelectionV1:
    """Select a schema path or a strictly non-authoritative no-schema fallback."""

    checked = _canonical_request(request)
    if checked is None:
        return _result("BLOCKED", reasons=("SCHEMA_SNAPSHOT_INVALID",))
    if checked.schema_snapshot is None:
        if (
            checked.generic_fact is None
            or checked.generic_fact.product_version_id != checked.product_version_id
        ):
            return _result("BLOCKED", reasons=("GENERIC_FACT_REQUIRED",))
        return _result("GENERIC_FACT_FALLBACK", generic_fact=checked.generic_fact)
    if checked.generic_fact is not None:
        return _result("BLOCKED", reasons=("GENERIC_FACT_NOT_ALLOWED_WITH_SCHEMA",))
    try:
        contracts = compile_schema_contracts(checked.schema_snapshot)
    except SchemaFirstContractError:
        return _result("BLOCKED", reasons=("SCHEMA_SNAPSHOT_INVALID",))
    if checked.product_version_id != contracts.product_version_id:
        return _result("BLOCKED", reasons=("SCHEMA_PRODUCT_MISMATCH",))
    material_fields, synthesis_fields, deferred_fields = _field_task_partition(
        contracts, checked.material_role
    )
    if not material_fields:
        return _result("BLOCKED", reasons=("MATERIAL_ROLE_FIELDS_MISSING",))
    try:
        candidates = material_profiles.list_approved(
            product_version_id=checked.product_version_id,
            material_role=checked.material_role,
        )
    except Exception:
        return _result("BLOCKED", reasons=("MATERIAL_PROFILE_LOOKUP_FAILED",))
    if type(candidates) is not tuple:
        return _result("BLOCKED", reasons=("MATERIAL_PROFILE_LOOKUP_FAILED",))
    if not candidates:
        return _result("BLOCKED", reasons=("MATERIAL_PROFILE_MISSING",))
    if len(candidates) != 1:
        return _result("BLOCKED", reasons=("MATERIAL_PROFILE_AMBIGUOUS",))
    profile = _canonical_profile(candidates[0])
    expected_fields = material_fields
    if (
        profile is None
        or profile.approval_state != "approved"
        or profile.product_version_id != checked.product_version_id
        or profile.schema_contract_sha256 != contracts.contract_set_sha256
        or profile.material_role != checked.material_role
        or profile.required_field_ids != expected_fields
    ):
        return _result("BLOCKED", reasons=("MATERIAL_PROFILE_IDENTITY_MISMATCH",))
    try:
        resolved = resolve_template(
            template_catalog,
            ResolutionRequest(
                space_id=checked.space_id,
                product_line_id=profile.product_line_id,
                document_type_id=profile.document_type_id,
                product_family_id=profile.product_family_id,
            ),
        )
        template_fields = tuple(
            field_id for group in resolved.content.field_groups for field_id in group.field_ids
        )
        if (
            resolved.content.schema_version != contracts.schema_id
            or template_fields != expected_fields
            or len(template_fields) != len(set(template_fields))
        ):
            raise ValueError("template identity mismatch")
    except (AttributeError, TypeError, ValueError, ValidationError, TemplateResolutionError):
        return _result("BLOCKED", reasons=("TEMPLATE_RESOLUTION_FAILED",))
    return _result(
        "SCHEMA_BOUND",
        field_contracts=contracts,
        material_profile=profile,
        resolved_template=resolved,
        material_field_ids=material_fields,
        synthesis_field_ids=synthesis_fields,
        deferred_unknown_field_ids=deferred_fields,
    )


__all__ = [
    "APPROVED_596_1_TEMPLATE_CONTENT_HASHES",
    "ApprovedMaterialProfileV1",
    "MaterialProfileCatalogPort",
    "SchemaCompilationRequestV1",
    "SchemaCompilationSelectionV1",
    "approved_material_profile_sha256",
    "build_596_1_schema67_material_profile_catalog",
    "build_596_1_schema67_template_catalog",
    "select_schema_compilation",
]
