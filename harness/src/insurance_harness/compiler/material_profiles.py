"""Exact MaterialProfile bindings for the approved OpenSpec 052 product slice.

This module is deliberately a thin, pure-domain seam over the existing
TemplatePackage resolver. It binds approved identities and emits receipts; it does
not inspect source contents or grant publication authority.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Annotated, Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from insurance_harness.canonical import canonical_hash
from insurance_harness.template_packages import (
    ResolutionRequest,
    ResolvedTemplate,
    TemplateCatalog,
    TemplateResolutionError,
    TemplateScope,
    resolve_template,
)

NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=512, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PositiveSize = Annotated[StrictInt, Field(gt=0)]
MaterialRole = Literal["terms", "brochure", "rate_table"]
AuthorityClass = Literal["contract_fact", "brochure_fact", "rate_numeric"]
ScopeLevel = Literal["global", "product-line", "document-type", "product-family"]
ResolutionReason = Literal[
    "product_identity_mismatch",
    "schema_identity_mismatch",
    "source_not_registered",
    "source_identity_mismatch",
    "material_role_conflict",
    "template_resolution_failed",
]
CatalogReason = Literal[
    "invalid_catalog",
    "invalid_field_authority",
    "invalid_field_bijection",
]

MATERIAL_PROFILE_CATALOG_OBJECT_TYPE: Final[str] = "material-profile-catalog.v1"
MATERIAL_PROFILE_BINDING_OBJECT_TYPE: Final[str] = (
    "material-profile-template-binding.v1"
)
_REQUESTED_LEVELS: Final[tuple[ScopeLevel, ...]] = (
    "global",
    "product-line",
    "document-type",
    "product-family",
)
_EXPECTED_GOLDEN: Final[dict[str, str]] = {
    "status": "S0_Q_FROZEN_FULL_GOLDEN_AVAILABLE",
    "release_hash": "fca06f988bf0310d12a0f6f8d0703a9476c54a5405676fb1a9b3476f91ec21d0",
    "artifact_hash": "83032da028ef227071fddac0ed422cbb9d1c2cc31e195972f9878a67d95b44ca",
    "approval_subject": "6feb2acf4be1ab5ce075b662bc9c9a40024038ca2324b893d3f31b1384f7674b",
}
_EXPECTED_SOURCES: Final[dict[MaterialRole, tuple[str, str, int, str]]] = {
    "terms": (
        "保险条款.pdf",
        "dataset/shouxian_product/平安e生保（尊享版）医疗保险/保险条款.pdf",
        1_047_811,
        "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
    ),
    "brochure": (
        "产品说明书.pdf",
        "dataset/shouxian_product/平安e生保（尊享版）医疗保险/产品说明书.pdf",
        492_101,
        "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
    ),
    "rate_table": (
        "费率表.pdf",
        "dataset/shouxian_product/平安e生保（尊享版）医疗保险/费率表.pdf",
        51_961,
        "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
    ),
}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class ProductBinding(_FrozenModel):
    product_code: NonBlankStr
    product_version: NonBlankStr


class SchemaBinding(_FrozenModel):
    line_key: NonBlankStr
    schema_version: NonBlankStr
    field_ids: tuple[NonBlankStr, ...]

    @model_validator(mode="after")
    def require_unique_fields(self) -> Self:
        if not self.field_ids or len(self.field_ids) != len(set(self.field_ids)):
            raise ValueError("invalid_field_bijection")
        return self


class ProductFamilyMapping(_FrozenModel):
    mapping_source: Literal["approved_product_version_mapping"]
    product_code: NonBlankStr
    product_version: NonBlankStr
    product_family_id: NonBlankStr


class GoldenIdentity(_FrozenModel):
    status: Literal["S0_Q_FROZEN_FULL_GOLDEN_AVAILABLE"]
    release_hash: Sha256Hex
    artifact_hash: Sha256Hex
    approval_subject: Sha256Hex


class SourceDocumentIdentity(_FrozenModel):
    name: NonBlankStr
    path: NonBlankStr
    size: PositiveSize
    sha256: Sha256Hex

    @field_validator("path")
    @classmethod
    def require_repository_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or "\\" in value
            or "//" in value
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("source path must be canonical and repository-relative")
        return value


class MaterialProfile(_FrozenModel):
    profile_id: NonBlankStr
    material_role: MaterialRole
    source: SourceDocumentIdentity
    document_type_id: NonBlankStr
    required_parse_capabilities: tuple[NonBlankStr, ...]

    @model_validator(mode="after")
    def require_unique_capabilities(self) -> Self:
        capabilities = self.required_parse_capabilities
        if not capabilities or len(capabilities) != len(set(capabilities)):
            raise ValueError("required capabilities must be non-empty and unique")
        return self


class FieldAuthority(_FrozenModel):
    authority_class: AuthorityClass
    primary_role: MaterialRole
    support_roles: tuple[MaterialRole, ...]
    field_ids: tuple[NonBlankStr, ...]

    @model_validator(mode="after")
    def require_safe_authority(self) -> Self:
        expected_primary: dict[AuthorityClass, MaterialRole] = {
            "contract_fact": "terms",
            "brochure_fact": "brochure",
            "rate_numeric": "rate_table",
        }
        if (
            self.primary_role != expected_primary[self.authority_class]
            or self.primary_role in self.support_roles
            or len(self.support_roles) != len(set(self.support_roles))
            or not self.field_ids
            or len(self.field_ids) != len(set(self.field_ids))
        ):
            raise ValueError("invalid_field_authority")
        return self


class MaterialProfileCatalog(_FrozenModel):
    contract: Literal["material-profile-catalog.v1"]
    catalog_version: NonBlankStr
    product: ProductBinding
    schema_binding: SchemaBinding
    product_family_mapping: ProductFamilyMapping
    golden_identity: GoldenIdentity
    profiles: tuple[MaterialProfile, ...]
    field_authority_groups: tuple[FieldAuthority, ...]

    @model_validator(mode="after")
    def require_exact_596_1_slice(self) -> Self:  # noqa: C901
        if (self.product.product_code, self.product.product_version) != (
            "596",
            "596-1",
        ):
            raise ValueError("invalid_catalog")
        if (
            self.schema_binding.line_key,
            self.schema_binding.schema_version,
            len(self.schema_binding.field_ids),
        ) != ("medical", "v1.1+b31a411c621c", 60):
            raise ValueError("invalid_field_bijection")
        mapping = self.product_family_mapping
        if (
            mapping.product_code,
            mapping.product_version,
            mapping.product_family_id,
        ) != ("596", "596-1", "pingan-eshengbao-zunxiang-medical"):
            raise ValueError("invalid_catalog")
        if self.golden_identity.model_dump(mode="python") != _EXPECTED_GOLDEN:
            raise ValueError("invalid_catalog")
        if len(self.profiles) != 3 or len(
            {profile.profile_id for profile in self.profiles}
        ) != 3:
            raise ValueError("invalid_catalog")
        profiles_by_role = {profile.material_role: profile for profile in self.profiles}
        if set(profiles_by_role) != set(_EXPECTED_SOURCES):
            raise ValueError("invalid_catalog")
        for role, expected in _EXPECTED_SOURCES.items():
            source = profiles_by_role[role].source
            if (source.name, source.path, source.size, source.sha256) != expected:
                raise ValueError("invalid_catalog")
        authority_fields = tuple(
            field_id
            for group in self.field_authority_groups
            for field_id in group.field_ids
        )
        if (
            len(authority_fields) != 60
            or len(authority_fields) != len(set(authority_fields))
            or set(authority_fields) != set(self.schema_binding.field_ids)
        ):
            raise ValueError("invalid_field_bijection")
        if {group.authority_class for group in self.field_authority_groups} != {
            "contract_fact",
            "brochure_fact",
            "rate_numeric",
        }:
            raise ValueError("invalid_field_authority")
        return self

    def authority_for(self, field_id: str) -> FieldAuthority:
        for group in self.field_authority_groups:
            if field_id in group.field_ids:
                return group
        raise KeyError(field_id)


class MaterialProfileResolutionRequest(_FrozenModel):
    space_id: NonBlankStr
    product_code: NonBlankStr
    product_version: NonBlankStr
    schema_version: NonBlankStr
    schema_field_ids: tuple[NonBlankStr, ...]
    source: SourceDocumentIdentity
    classified_material_role: MaterialRole | None = None

    @model_validator(mode="after")
    def require_unique_schema_fields(self) -> Self:
        if not self.schema_field_ids or len(self.schema_field_ids) != len(
            set(self.schema_field_ids)
        ):
            raise ValueError("schema_field_ids must be non-empty and unique")
        return self


class TemplateSourceReceipt(_FrozenModel):
    scope: TemplateScope
    package_id: NonBlankStr
    version_id: NonBlankStr
    content_hash: Sha256Hex


class TemplateFallbackReceipt(_FrozenModel):
    requested_levels: tuple[ScopeLevel, ...]
    resolved_levels: tuple[ScopeLevel, ...]
    missing_levels: tuple[ScopeLevel, ...]
    source_chain: tuple[TemplateSourceReceipt, ...]
    resolved_content_hash: Sha256Hex

    @model_validator(mode="after")
    def require_exact_chain_partition(self) -> Self:
        if self.requested_levels != _REQUESTED_LEVELS:
            raise ValueError("requested TemplatePackage levels changed")
        if self.resolved_levels != tuple(item.scope.level for item in self.source_chain):
            raise ValueError("resolved levels do not match source chain")
        if self.missing_levels != tuple(
            level for level in self.requested_levels if level not in self.resolved_levels
        ):
            raise ValueError("missing levels do not match source chain")
        return self


class MaterialProfileReviewItem(_FrozenModel):
    review_type: Literal["material_profile_binding"] = "material_profile_binding"
    reason_code: ResolutionReason
    product_version: NonBlankStr
    source_path: NonBlankStr
    expected: NonBlankStr
    observed: NonBlankStr


class MaterialProfileResolution(_FrozenModel):
    catalog_hash: Sha256Hex
    request: MaterialProfileResolutionRequest
    profile: MaterialProfile
    product_family_id: NonBlankStr
    golden_identity: GoldenIdentity
    resolved_template: ResolvedTemplate
    template_receipt: TemplateFallbackReceipt
    review_items: tuple[MaterialProfileReviewItem, ...]
    binding_hash: Sha256Hex

    @model_validator(mode="after")
    def require_binding_hash(self) -> Self:
        if self.binding_hash != _binding_hash(
            catalog_hash=self.catalog_hash,
            request=self.request,
            profile=self.profile,
            product_family_id=self.product_family_id,
            golden_identity=self.golden_identity,
            template_receipt=self.template_receipt,
        ):
            raise ValueError("binding_hash_mismatch")
        if self.review_items:
            raise ValueError("successful resolution cannot contain ReviewItems")
        return self


class MaterialProfileCatalogError(ValueError):
    def __init__(self, reason_code: CatalogReason) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class MaterialProfileResolutionError(ValueError):
    def __init__(self, review_item: MaterialProfileReviewItem) -> None:
        self.reason_code = review_item.reason_code
        self.review_item = review_item
        super().__init__(review_item.reason_code)


def _catalog_error_reason(exc: ValidationError) -> CatalogReason:
    text = str(exc)
    if "invalid_field_authority" in text:
        return "invalid_field_authority"
    if "invalid_field_bijection" in text:
        return "invalid_field_bijection"
    return "invalid_catalog"


def load_material_profile_catalog_data(value: object) -> MaterialProfileCatalog:
    """Validate the one approved catalog without accepting partial coercive input."""

    try:
        return MaterialProfileCatalog.model_validate(value)
    except ValidationError as exc:
        raise MaterialProfileCatalogError(_catalog_error_reason(exc)) from None


def load_material_profile_catalog(path: Path) -> MaterialProfileCatalog:
    """Load a catalog artifact; resolution itself performs no filesystem access."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise MaterialProfileCatalogError("invalid_catalog") from None
    return load_material_profile_catalog_data(payload)


def material_profile_catalog_hash(catalog: MaterialProfileCatalog) -> str:
    """Return the C0 identity of the complete validated catalog."""

    return canonical_hash(
        MATERIAL_PROFILE_CATALOG_OBJECT_TYPE,
        catalog.model_dump(mode="python"),
    )


def _review_error(
    reason_code: ResolutionReason,
    request: MaterialProfileResolutionRequest,
    *,
    expected: str,
    observed: str,
) -> MaterialProfileResolutionError:
    return MaterialProfileResolutionError(
        MaterialProfileReviewItem(
            reason_code=reason_code,
            product_version=request.product_version,
            source_path=request.source.path,
            expected=expected,
            observed=observed,
        )
    )


def _template_receipt(template: ResolvedTemplate) -> TemplateFallbackReceipt:
    source_chain = tuple(
        TemplateSourceReceipt(
            scope=source.scope,
            package_id=source.package_id,
            version_id=source.version_id,
            content_hash=source.content_hash,
        )
        for source in template.source_chain
    )
    resolved_levels = tuple(source.scope.level for source in source_chain)
    return TemplateFallbackReceipt(
        requested_levels=_REQUESTED_LEVELS,
        resolved_levels=resolved_levels,
        missing_levels=tuple(
            level for level in _REQUESTED_LEVELS if level not in resolved_levels
        ),
        source_chain=source_chain,
        resolved_content_hash=template.content_hash,
    )


def _binding_hash(
    *,
    catalog_hash: str,
    request: MaterialProfileResolutionRequest,
    profile: MaterialProfile,
    product_family_id: str,
    golden_identity: GoldenIdentity,
    template_receipt: TemplateFallbackReceipt,
) -> str:
    return canonical_hash(
        MATERIAL_PROFILE_BINDING_OBJECT_TYPE,
        {
            "catalog_hash": catalog_hash,
            "request": request.model_dump(mode="python"),
            "profile": profile.model_dump(mode="python"),
            "product_family_id": product_family_id,
            "golden_identity": golden_identity.model_dump(mode="python"),
            "template_receipt": template_receipt.model_dump(mode="python"),
        },
    )


def resolve_material_profile(
    catalog: MaterialProfileCatalog,
    template_catalog: TemplateCatalog,
    request: MaterialProfileResolutionRequest,
) -> MaterialProfileResolution:
    """Bind one exact registered source to the existing approved template chain."""

    canonical_request = MaterialProfileResolutionRequest.model_validate(
        request.model_dump(mode="python")
    )
    expected_product = (
        catalog.product.product_code,
        catalog.product.product_version,
    )
    observed_product = (
        canonical_request.product_code,
        canonical_request.product_version,
    )
    if observed_product != expected_product:
        raise _review_error(
            "product_identity_mismatch",
            canonical_request,
            expected="/".join(expected_product),
            observed="/".join(observed_product),
        )
    expected_schema = catalog.schema_binding
    if (
        canonical_request.schema_version != expected_schema.schema_version
        or canonical_request.schema_field_ids != expected_schema.field_ids
    ):
        raise _review_error(
            "schema_identity_mismatch",
            canonical_request,
            expected=f"{expected_schema.schema_version}:60",
            observed=(
                f"{canonical_request.schema_version}:"
                f"{len(canonical_request.schema_field_ids)}"
            ),
        )
    profile = next(
        (
            item
            for item in catalog.profiles
            if item.source.path == canonical_request.source.path
        ),
        None,
    )
    if profile is None:
        raise _review_error(
            "source_not_registered",
            canonical_request,
            expected="one of three approved source paths",
            observed=canonical_request.source.path,
        )
    if profile.source != canonical_request.source:
        raise _review_error(
            "source_identity_mismatch",
            canonical_request,
            expected=f"{profile.source.size}:{profile.source.sha256}",
            observed=(
                f"{canonical_request.source.size}:"
                f"{canonical_request.source.sha256}"
            ),
        )
    classified_role = canonical_request.classified_material_role
    if classified_role is not None and classified_role != profile.material_role:
        raise _review_error(
            "material_role_conflict",
            canonical_request,
            expected=profile.material_role,
            observed=classified_role,
        )
    mapping = catalog.product_family_mapping
    template_request = ResolutionRequest(
        space_id=canonical_request.space_id,
        product_line_id=expected_schema.line_key,
        document_type_id=profile.document_type_id,
        product_family_id=mapping.product_family_id,
    )
    try:
        resolved_template = resolve_template(template_catalog, template_request)
    except TemplateResolutionError as exc:
        raise _review_error(
            "template_resolution_failed",
            canonical_request,
            expected="approved explicit TemplatePackage chain",
            observed=exc.reason_code,
        ) from None
    receipt = _template_receipt(resolved_template)
    catalog_hash = material_profile_catalog_hash(catalog)
    binding_hash = _binding_hash(
        catalog_hash=catalog_hash,
        request=canonical_request,
        profile=profile,
        product_family_id=mapping.product_family_id,
        golden_identity=catalog.golden_identity,
        template_receipt=receipt,
    )
    return MaterialProfileResolution(
        catalog_hash=catalog_hash,
        request=canonical_request,
        profile=profile,
        product_family_id=mapping.product_family_id,
        golden_identity=catalog.golden_identity,
        resolved_template=resolved_template,
        template_receipt=receipt,
        review_items=(),
        binding_hash=binding_hash,
    )


__all__ = [
    "MATERIAL_PROFILE_BINDING_OBJECT_TYPE",
    "MATERIAL_PROFILE_CATALOG_OBJECT_TYPE",
    "FieldAuthority",
    "GoldenIdentity",
    "MaterialProfile",
    "MaterialProfileCatalog",
    "MaterialProfileCatalogError",
    "MaterialProfileResolution",
    "MaterialProfileResolutionError",
    "MaterialProfileResolutionRequest",
    "MaterialProfileReviewItem",
    "ProductBinding",
    "ProductFamilyMapping",
    "SchemaBinding",
    "SourceDocumentIdentity",
    "TemplateFallbackReceipt",
    "TemplateSourceReceipt",
    "load_material_profile_catalog",
    "load_material_profile_catalog_data",
    "material_profile_catalog_hash",
    "resolve_material_profile",
]
