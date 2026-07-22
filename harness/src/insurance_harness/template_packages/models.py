"""Immutable, content-addressed DTOs for OpenSpec 028 template packages."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    PositiveInt,
    StrictBool,
    StrictStr,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(
        min_length=1,
        max_length=512,
        pattern=r"^\S(?:[^\r\n]*\S)?$",
    ),
]
Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
SourceCommit = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"),
]
ScopeLevel = Literal["global", "product-line", "document-type", "product-family"]
ApprovalState = Literal["approved", "pending", "revoked"]


class _ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    def copy(
        self,
        *,
        include: object = None,
        exclude: object = None,
        update: dict[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Disable Pydantic's deprecated, unvalidated copy path."""

        raise TypeError("copy() is disabled; use validated model_copy()")

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Revalidate updates so a copied DTO cannot bypass field invariants."""

        values = self.model_dump(mode="python", round_trip=True)
        if update is not None:
            values.update(update)
        return type(self).model_validate(values)


class FieldGroup(_ImmutableModel):
    group_id: NonBlankStr
    field_ids: tuple[NonBlankStr, ...]
    evidence_roles: tuple[NonBlankStr, ...]

    @model_validator(mode="after")
    def require_unique_members(self) -> FieldGroup:
        if not self.field_ids or len(set(self.field_ids)) != len(self.field_ids):
            raise ValueError("field_ids must be non-empty and unique")
        if not self.evidence_roles or len(set(self.evidence_roles)) != len(
            self.evidence_roles
        ):
            raise ValueError("evidence_roles must be non-empty and unique")
        return self


class ValidatorRef(_ImmutableModel):
    validator_id: NonBlankStr
    validator_version: NonBlankStr
    config_hash: Sha256Hex


class EvidencePolicy(_ImmutableModel):
    require_quote: StrictBool
    require_locator: StrictBool
    minimum_sources: PositiveInt


class ProvenanceReceipt(_ImmutableModel):
    """Auditable first-party TypeScript-to-Python behavior migration metadata."""

    migration_id: NonBlankStr
    source_repository: NonBlankStr
    source_branch: NonBlankStr
    source_commit: SourceCommit
    source_path: NonBlankStr
    source_language: Literal["typescript"]
    rights_status: Literal["project-owned"]
    accepted_behavior: NonBlankStr
    rejected_behavior: NonBlankStr
    python_target: NonBlankStr
    translation_method: Literal["behavior_port_with_characterization_tests"]
    characterization_tests: tuple[NonBlankStr, ...]

    @staticmethod
    def _is_canonical_repository_path(value: str) -> bool:
        if "\x00" in value or "\\" in value or value.startswith("/") or "//" in value:
            return False
        parts = value.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            return False
        first = parts[0]
        return not (len(first) >= 2 and first[0].isalpha() and first[1] == ":")

    @model_validator(mode="after")
    def require_relative_language_paths(self) -> ProvenanceReceipt:
        source = self.source_path
        target = self.python_target
        tests = self.characterization_tests
        if not self._is_canonical_repository_path(source):
            raise ValueError("source_path must be repository-relative")
        if not source.endswith((".ts", ".tsx")):
            raise ValueError("source_path must identify TypeScript provenance")
        if not self._is_canonical_repository_path(target) or not target.endswith(".py"):
            raise ValueError("python_target must be a repository-relative Python path")
        if not tests or any(
            not self._is_canonical_repository_path(path) or not path.endswith(".py")
            for path in tests
        ):
            raise ValueError("characterization_tests must be relative Python test paths")
        return self


class TemplatePackageContent(_ImmutableModel):
    """The complete canonical payload covered by a template version hash."""

    schema_version: NonBlankStr
    field_groups: tuple[FieldGroup, ...]
    role_prompts: Mapping[NonBlankStr, StrictStr]
    validators: tuple[ValidatorRef, ...]
    evidence_policy: EvidencePolicy
    attempt_limits: Mapping[NonBlankStr, PositiveInt]
    golden_slice_ref: NonBlankStr
    provenance: tuple[ProvenanceReceipt, ...]

    @field_validator("role_prompts", mode="after")
    @classmethod
    def freeze_role_prompts(
        cls, value: Mapping[str, str]
    ) -> Mapping[str, str]:
        if any(not prompt.strip() for prompt in value.values()):
            raise ValueError("role prompt bodies must contain non-whitespace text")
        return MappingProxyType(dict(value))

    @field_validator("attempt_limits", mode="after")
    @classmethod
    def freeze_attempt_limits(
        cls, value: Mapping[str, int]
    ) -> Mapping[str, int]:
        return MappingProxyType(dict(value))

    @field_serializer("role_prompts")
    def serialize_role_prompts(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)

    @field_serializer("attempt_limits")
    def serialize_attempt_limits(self, value: Mapping[str, int]) -> dict[str, int]:
        return dict(value)

    @model_validator(mode="after")
    def require_complete_unique_content(self) -> TemplatePackageContent:
        group_ids = tuple(group.group_id for group in self.field_groups)
        validator_ids = tuple(validator.validator_id for validator in self.validators)
        if not group_ids or len(set(group_ids)) != len(group_ids):
            raise ValueError("field_groups must be non-empty with unique group_id values")
        if not validator_ids or len(set(validator_ids)) != len(validator_ids):
            raise ValueError("validators must be non-empty with unique validator_id values")
        if not self.role_prompts:
            raise ValueError("role_prompts must not be empty")
        if not self.attempt_limits:
            raise ValueError("attempt_limits must not be empty")
        if not self.provenance:
            raise ValueError("provenance must not be empty")
        return self


def canonical_content_hash(content: TemplatePackageContent) -> str:
    """Return SHA-256 of the complete canonical JSON payload."""

    payload = json.dumps(
        content.model_dump(mode="json", round_trip=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class TemplateScope(_ImmutableModel):
    """One exact node in the Space-scoped applicability hierarchy."""

    space_id: NonBlankStr
    level: ScopeLevel
    product_line_id: NonBlankStr | None = None
    document_type_id: NonBlankStr | None = None
    product_family_id: NonBlankStr | None = None

    @model_validator(mode="after")
    def require_exact_hierarchy_prefix(self) -> TemplateScope:
        present = (
            self.product_line_id is not None,
            self.document_type_id is not None,
            self.product_family_id is not None,
        )
        expected = {
            "global": (False, False, False),
            "product-line": (True, False, False),
            "document-type": (True, True, False),
            "product-family": (True, True, True),
        }[self.level]
        if present != expected:
            raise ValueError(f"{self.level} requires exact hierarchy prefix {expected}")
        return self


class ResolutionRequest(_ImmutableModel):
    """Exact applicability identity; display names and fuzzy keys are excluded."""

    space_id: NonBlankStr
    product_line_id: NonBlankStr
    document_type_id: NonBlankStr
    product_family_id: NonBlankStr


class TemplateVersion(_ImmutableModel):
    package_id: NonBlankStr
    version_id: NonBlankStr
    scope: TemplateScope
    content: TemplatePackageContent
    content_hash: Sha256Hex

    @classmethod
    def from_content(
        cls,
        *,
        package_id: str,
        version_id: str,
        scope: TemplateScope,
        content: TemplatePackageContent,
    ) -> TemplateVersion:
        return cls(
            package_id=package_id,
            version_id=version_id,
            scope=scope,
            content=content,
            content_hash=canonical_content_hash(content),
        )

    @model_validator(mode="after")
    def require_full_content_hash(self) -> TemplateVersion:
        if self.content_hash != canonical_content_hash(self.content):
            raise ValueError("content_hash_mismatch")
        return self


class TemplateApproval(_ImmutableModel):
    approval_id: NonBlankStr
    package_id: NonBlankStr
    version_id: NonBlankStr
    scope: TemplateScope
    content_hash: Sha256Hex
    state: ApprovalState


class TemplateCatalogEntry(_ImmutableModel):
    version: TemplateVersion
    approval: TemplateApproval


class ResolvedTemplateSource(_ImmutableModel):
    scope: TemplateScope
    package_id: NonBlankStr
    version_id: NonBlankStr
    content_hash: Sha256Hex


class ResolvedTemplate(_ImmutableModel):
    request: ResolutionRequest
    content: TemplatePackageContent
    content_hash: Sha256Hex
    source_chain: tuple[ResolvedTemplateSource, ...]

    @model_validator(mode="after")
    def require_resolved_hash_and_sources(self) -> ResolvedTemplate:
        if not self.source_chain:
            raise ValueError("source_chain must not be empty")
        if self.content_hash != canonical_content_hash(self.content):
            raise ValueError("content_hash_mismatch")
        return self
