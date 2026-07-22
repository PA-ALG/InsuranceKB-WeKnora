"""Pure, deterministic TemplatePackage overlay resolution."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from insurance_harness.template_packages.models import (
    ResolutionRequest,
    ResolvedTemplate,
    ResolvedTemplateSource,
    TemplateApproval,
    TemplateCatalogEntry,
    TemplatePackageContent,
    TemplateScope,
    TemplateVersion,
    _merge_template_contents,
    _snapshot_content_value,
    _TemplateContentMergeError,
    canonical_content_hash,
)
from insurance_harness.template_packages.ports import TemplateCatalog

ResolutionReason = Literal[
    "invalid_request",
    "invalid_catalog_entry",
    "catalog_lookup_failed",
    "content_hash_mismatch",
    "catalog_scope_mutation",
    "scope_mismatch",
    "unapproved",
    "approval_hash_mismatch",
    "approval_binding_mismatch",
    "schema_version_mismatch",
    "field_group_conflict",
    "validator_conflict",
    "unresolved_scope",
]

_ScopeIdentity = tuple[str, str, str | None, str | None, str | None]


class TemplateResolutionError(ValueError):
    """Typed fail-closed result for invalid or inapplicable template data."""

    def __init__(self, reason_code: ResolutionReason) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _snapshot_exact_fields(
    value: object,
    model_type: type[BaseModel],
) -> dict[str, object]:
    """Copy one exact Pydantic DTO without invoking caller-shadowable methods."""

    if type(value) is not model_type:
        raise TypeError("DTO must use its exact domain type")
    storage = object.__getattribute__(value, "__dict__")
    if type(storage) is not dict:
        raise TypeError("DTO storage must be an exact dictionary")
    field_names = tuple(model_type.model_fields)
    extra = object.__getattribute__(value, "__pydantic_extra__")
    private = object.__getattribute__(value, "__pydantic_private__")
    fields_set = object.__getattribute__(value, "__pydantic_fields_set__")
    if extra is not None or private is not None:
        raise ValueError("DTO has hidden extra or private storage")
    if type(fields_set) is not set or any(
        type(field_name) is not str or field_name not in field_names
        for field_name in fields_set
    ):
        raise ValueError("DTO fields_set is non-canonical")
    items = tuple(storage.items())
    if len(items) != len(field_names):
        raise ValueError("DTO field set is incomplete or extended")
    for field_name, _ in items:
        if type(field_name) is not str or field_name not in field_names:
            raise ValueError("DTO field set is non-canonical")
    snapshot = dict(items)
    if model_type is TemplateScope:
        required_scope_fields = {"space_id", "level"}
        required_scope_fields.update(
            field_name
            for field_name in (
                "product_line_id",
                "document_type_id",
                "product_family_id",
            )
            if snapshot[field_name] is not None
        )
        if not required_scope_fields.issubset(fields_set):
            raise ValueError("TemplateScope fields_set omits identity fields")
    elif len(fields_set) != len(field_names):
        raise ValueError("DTO fields_set is incomplete")
    return {field_name: snapshot[field_name] for field_name in field_names}


def _canonical_request(request: ResolutionRequest) -> ResolutionRequest:
    """Freeze one exact base DTO before invoking any external catalog code."""

    try:
        payload = _snapshot_exact_fields(request, ResolutionRequest)
        if any(type(value) is not str for value in payload.values()):
            raise TypeError("request identity must use exact string primitives")
        return ResolutionRequest.model_validate(payload)
    except Exception:
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


def _scope_identity(scope: TemplateScope) -> _ScopeIdentity:
    return (
        scope.space_id,
        scope.level,
        scope.product_line_id,
        scope.document_type_id,
        scope.product_family_id,
    )


def _scope_from_identity(identity: _ScopeIdentity) -> TemplateScope:
    space_id, level, product_line_id, document_type_id, product_family_id = identity
    return TemplateScope.model_validate(
        {
            "space_id": space_id,
            "level": level,
            "product_line_id": product_line_id,
            "document_type_id": document_type_id,
            "product_family_id": product_family_id,
        }
    )


def _validated_entry(
    candidate: TemplateCatalogEntry,
    expected_scope: _ScopeIdentity,
) -> TemplateCatalogEntry:
    """Revalidate an adapter result and bind approval to its exact full content."""

    try:
        candidate_values = _snapshot_exact_fields(candidate, TemplateCatalogEntry)
        candidate_version = candidate_values["version"]
        candidate_approval = candidate_values["approval"]
        version_values = _snapshot_exact_fields(candidate_version, TemplateVersion)
        approval_values = _snapshot_exact_fields(candidate_approval, TemplateApproval)
        candidate_content = version_values["content"]
        content_values = _snapshot_content_value(candidate_content)
        version_scope_values = _snapshot_exact_fields(
            version_values["scope"],
            TemplateScope,
        )
        approval_scope_values = _snapshot_exact_fields(
            approval_values["scope"],
            TemplateScope,
        )
        content = TemplatePackageContent.model_validate(content_values)
        version_scope = TemplateScope.model_validate(version_scope_values)
        approval_scope = TemplateScope.model_validate(approval_scope_values)
        candidate_hash = canonical_content_hash(content)
        stated_hash = version_values["content_hash"]
        if (
            type(stated_hash) is not str
            or len(stated_hash) != 64
            or any(character not in "0123456789abcdef" for character in stated_hash)
        ):
            raise ValueError("content_hash must be canonical SHA-256 hex")
        version = TemplateVersion.model_validate(
            {
                **version_values,
                "content": content,
                "content_hash": candidate_hash,
                "scope": version_scope,
            }
        )
        approval = TemplateApproval.model_validate(
            {**approval_values, "scope": approval_scope}
        )
        snapshot = TemplateCatalogEntry(
            version=version,
            approval=approval,
        )
    except Exception:
        raise TemplateResolutionError("invalid_catalog_entry") from None

    if candidate_hash != stated_hash:
        raise TemplateResolutionError("content_hash_mismatch")
    if _scope_identity(snapshot.version.scope) != expected_scope:
        raise TemplateResolutionError("scope_mismatch")
    if snapshot.approval.state != "approved":
        raise TemplateResolutionError("unapproved")
    if snapshot.approval.content_hash != snapshot.version.content_hash:
        raise TemplateResolutionError("approval_hash_mismatch")
    if (
        snapshot.approval.package_id != snapshot.version.package_id
        or snapshot.approval.version_id != snapshot.version.version_id
        or snapshot.approval.scope != snapshot.version.scope
    ):
        raise TemplateResolutionError("approval_binding_mismatch")
    return snapshot


def _overlay_content(
    base: TemplatePackageContent, overlay: TemplatePackageContent
) -> TemplatePackageContent:
    try:
        return _merge_template_contents(base, overlay)
    except _TemplateContentMergeError as exc:
        raise TemplateResolutionError(exc.reason_code) from None


def resolve_template(
    catalog: TemplateCatalog,
    request: ResolutionRequest,
) -> ResolvedTemplate:
    """Resolve approved overlays in the frozen hierarchy, using exact IDs only."""

    canonical_request = _canonical_request(request)
    entries: list[TemplateCatalogEntry] = []
    for requested_scope in _requested_scopes(canonical_request):
        expected_scope = _scope_identity(requested_scope)
        query_scope = _scope_from_identity(expected_scope)
        try:
            candidate = catalog.get_approved(query_scope)
        except Exception:
            raise TemplateResolutionError("catalog_lookup_failed") from None
        try:
            query_values = _snapshot_exact_fields(query_scope, TemplateScope)
            if any(
                value is not None and type(value) is not str
                for value in query_values.values()
            ):
                raise TypeError("query scope must use exact primitive values")
            query_snapshot = TemplateScope.model_validate(query_values)
            if _scope_identity(query_snapshot) != expected_scope:
                raise ValueError("query scope changed during catalog lookup")
        except Exception:
            raise TemplateResolutionError("catalog_scope_mutation") from None
        if candidate is not None:
            entries.append(_validated_entry(candidate, expected_scope))
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
            content=entry.version.content,
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
