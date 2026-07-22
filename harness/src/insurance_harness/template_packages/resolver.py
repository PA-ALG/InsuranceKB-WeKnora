"""Pure, deterministic TemplatePackage overlay resolution."""

from __future__ import annotations

from typing import Literal

from pydantic import ValidationError

from insurance_harness.template_packages.models import (
    FieldGroup,
    ResolutionRequest,
    ResolvedTemplate,
    ResolvedTemplateSource,
    TemplateApproval,
    TemplateCatalogEntry,
    TemplatePackageContent,
    TemplateScope,
    TemplateVersion,
    ValidatorRef,
    canonical_content_hash,
)
from insurance_harness.template_packages.ports import TemplateCatalog

ResolutionReason = Literal[
    "invalid_request",
    "invalid_catalog_entry",
    "content_hash_mismatch",
    "scope_mismatch",
    "unapproved",
    "approval_hash_mismatch",
    "approval_binding_mismatch",
    "schema_version_mismatch",
    "unresolved_scope",
]


class TemplateResolutionError(ValueError):
    """Typed fail-closed result for invalid or inapplicable template data."""

    def __init__(self, reason_code: ResolutionReason) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _canonical_request(request: ResolutionRequest) -> ResolutionRequest:
    """Freeze one exact base DTO before invoking any external catalog code."""

    if type(request) is not ResolutionRequest:
        raise TemplateResolutionError("invalid_request")
    try:
        payload = request.model_dump(mode="python", round_trip=True)
        return ResolutionRequest.model_validate(payload)
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise TemplateResolutionError("invalid_request") from None


def _requested_scopes(request: ResolutionRequest) -> tuple[TemplateScope, ...]:
    return (
        TemplateScope(space_id=request.space_id, level="global"),
        TemplateScope(
            space_id=request.space_id,
            level="product-line",
            product_line_id=request.product_line_id,
        ),
        TemplateScope(
            space_id=request.space_id,
            level="document-type",
            product_line_id=request.product_line_id,
            document_type_id=request.document_type_id,
        ),
        TemplateScope(
            space_id=request.space_id,
            level="product-family",
            product_line_id=request.product_line_id,
            document_type_id=request.document_type_id,
            product_family_id=request.product_family_id,
        ),
    )


def _validated_entry(
    candidate: TemplateCatalogEntry,
    requested_scope: TemplateScope,
) -> TemplateCatalogEntry:
    """Revalidate an adapter result and bind approval to its exact full content."""

    try:
        candidate_hash = canonical_content_hash(candidate.version.content)
    except (AttributeError, TypeError, ValueError):
        raise TemplateResolutionError("invalid_catalog_entry") from None
    if candidate_hash != candidate.version.content_hash:
        raise TemplateResolutionError("content_hash_mismatch")

    try:
        version = TemplateVersion.model_validate(
            candidate.version.model_dump(mode="python", round_trip=True)
        )
        approval = TemplateApproval.model_validate(
            candidate.approval.model_dump(mode="python", round_trip=True)
        )
    except (AttributeError, ValidationError):
        raise TemplateResolutionError("invalid_catalog_entry") from None

    if version.scope != requested_scope:
        raise TemplateResolutionError("scope_mismatch")
    if approval.state != "approved":
        raise TemplateResolutionError("unapproved")
    if approval.content_hash != version.content_hash:
        raise TemplateResolutionError("approval_hash_mismatch")
    if (
        approval.package_id != version.package_id
        or approval.version_id != version.version_id
        or approval.scope != version.scope
    ):
        raise TemplateResolutionError("approval_binding_mismatch")
    return TemplateCatalogEntry(version=version, approval=approval)


def _overlay_field_groups(
    base: tuple[FieldGroup, ...], overlay: tuple[FieldGroup, ...]
) -> tuple[FieldGroup, ...]:
    result = list(base)
    positions = {item.group_id: index for index, item in enumerate(result)}
    for item in overlay:
        position = positions.get(item.group_id)
        if position is None:
            positions[item.group_id] = len(result)
            result.append(item)
        else:
            result[position] = item
    return tuple(result)


def _overlay_validators(
    base: tuple[ValidatorRef, ...], overlay: tuple[ValidatorRef, ...]
) -> tuple[ValidatorRef, ...]:
    result = list(base)
    positions = {item.validator_id: index for index, item in enumerate(result)}
    for item in overlay:
        position = positions.get(item.validator_id)
        if position is None:
            positions[item.validator_id] = len(result)
            result.append(item)
        else:
            result[position] = item
    return tuple(result)


def _overlay_content(
    base: TemplatePackageContent, overlay: TemplatePackageContent
) -> TemplatePackageContent:
    if overlay.schema_version != base.schema_version:
        raise TemplateResolutionError("schema_version_mismatch")
    role_prompts = dict(base.role_prompts)
    role_prompts.update(overlay.role_prompts)
    attempt_limits = dict(base.attempt_limits)
    attempt_limits.update(overlay.attempt_limits)
    return TemplatePackageContent(
        schema_version=base.schema_version,
        field_groups=_overlay_field_groups(base.field_groups, overlay.field_groups),
        role_prompts=role_prompts,
        validators=_overlay_validators(base.validators, overlay.validators),
        evidence_policy=overlay.evidence_policy,
        attempt_limits=attempt_limits,
        golden_slice_ref=overlay.golden_slice_ref,
        provenance=base.provenance + overlay.provenance,
    )


def resolve_template(
    catalog: TemplateCatalog,
    request: ResolutionRequest,
) -> ResolvedTemplate:
    """Resolve approved overlays in the frozen hierarchy, using exact IDs only."""

    canonical_request = _canonical_request(request)
    entries: list[TemplateCatalogEntry] = []
    for requested_scope in _requested_scopes(canonical_request):
        candidate = catalog.get_approved(requested_scope)
        if candidate is not None:
            entries.append(_validated_entry(candidate, requested_scope))
    if not entries:
        raise TemplateResolutionError("unresolved_scope")

    content = entries[0].version.content
    for entry in entries[1:]:
        content = _overlay_content(content, entry.version.content)
    source_chain = tuple(
        ResolvedTemplateSource(
            scope=entry.version.scope,
            package_id=entry.version.package_id,
            version_id=entry.version.version_id,
            content_hash=entry.version.content_hash,
        )
        for entry in entries
    )
    return ResolvedTemplate(
        request=canonical_request,
        content=content,
        content_hash=canonical_content_hash(content),
        source_chain=source_chain,
    )
