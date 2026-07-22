"""Immutable, content-addressed DTOs for OpenSpec 028 template packages."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from typing import Annotated, Any, Literal, Self, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
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
StrictPositiveInt = Annotated[int, Field(strict=True, gt=0)]

_CONTENT_HASH_DOMAIN = b"insurancekb.template-package.content.v1\0"

_ValueT = TypeVar("_ValueT")


class _FrozenMapping(
    tuple[tuple[str, _ValueT], ...],
    Mapping[str, _ValueT],
):
    """Immutable mapping whose complete authority state is inspectable."""

    __slots__ = ()

    def __new__(
        cls,
        items: tuple[tuple[str, _ValueT], ...],
    ) -> Self:
        if type(items) is not tuple:
            raise TypeError("frozen mapping items must use an exact tuple")
        seen: set[str] = set()
        for item in items:
            if type(item) is not tuple or len(item) != 2:
                raise TypeError("frozen mapping entries must use exact pairs")
            key, _value = item
            if type(key) is not str or key in seen:
                raise ValueError("frozen mapping keys must be unique exact strings")
            seen.add(key)
        return tuple.__new__(cls, items)

    def __getitem__(self, key: str) -> _ValueT:  # type: ignore[override]
        for item_key, value in tuple.__iter__(self):
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:  # type: ignore[override]
        return (key for key, _value in tuple.__iter__(self))


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

    def __copy__(self) -> Self:
        """Return a freshly validated immutable value, never raw internal state."""

        return type(self).model_validate(
            self.model_dump(mode="python", round_trip=True)
        )

    def __deepcopy__(self, memo: dict[int, Any] | None = None) -> Self:
        """Deep-copy through validation so immutable mapping views remain safe."""

        del memo
        return type(self).model_validate(
            self.model_dump(mode="python", round_trip=True)
        )


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
    minimum_sources: StrictPositiveInt


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
    attempt_limits: Mapping[NonBlankStr, StrictPositiveInt]
    golden_slice_ref: NonBlankStr
    provenance: tuple[ProvenanceReceipt, ...]

    @field_validator("role_prompts", "attempt_limits", mode="before")
    @classmethod
    def require_unambiguous_mapping(cls, value: object) -> dict[str, object]:
        """Reject coercive pair iterables and mappings that enumerate duplicate keys."""

        if not isinstance(value, Mapping):
            raise ValueError("mapping input must be an exact Mapping")
        try:
            items = tuple(value.items())
        except (AttributeError, TypeError, ValueError):
            raise ValueError("mapping input could not be enumerated") from None
        result: dict[str, object] = {}
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ValueError("mapping items must be exact key/value pairs")
            key, item_value = item
            if type(key) is not str:
                raise ValueError("mapping keys must be exact strings")
            if key in seen:
                raise ValueError("mapping input contains duplicate keys")
            seen.add(key)
            result[key] = item_value
        return result

    @field_validator("role_prompts", mode="after")
    @classmethod
    def freeze_role_prompts(
        cls, value: Mapping[str, str]
    ) -> Mapping[str, str]:
        if any(not prompt.strip() for prompt in value.values()):
            raise ValueError("role prompt bodies must contain non-whitespace text")
        return _FrozenMapping(tuple(value.items()))

    @field_validator("attempt_limits", mode="after")
    @classmethod
    def freeze_attempt_limits(
        cls, value: Mapping[str, int]
    ) -> Mapping[str, int]:
        return _FrozenMapping(tuple(value.items()))

    @field_serializer("role_prompts")
    def serialize_role_prompts(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)

    @field_serializer("attempt_limits")
    def serialize_attempt_limits(self, value: Mapping[str, int]) -> dict[str, int]:
        return dict(value)

    @model_validator(mode="after")
    def require_complete_unique_content(self) -> TemplatePackageContent:
        group_ids = tuple(group.group_id for group in self.field_groups)
        field_ids = tuple(
            field_id
            for group in self.field_groups
            for field_id in group.field_ids
        )
        validator_ids = tuple(validator.validator_id for validator in self.validators)
        if not group_ids or len(set(group_ids)) != len(group_ids):
            raise ValueError("field_groups must be non-empty with unique group_id values")
        if len(set(field_ids)) != len(field_ids):
            raise ValueError("field_ids must be unique across field_groups")
        if not validator_ids or len(set(validator_ids)) != len(validator_ids):
            raise ValueError("validators must be non-empty with unique validator_id values")
        if not self.role_prompts:
            raise ValueError("role_prompts must not be empty")
        if not self.attempt_limits:
            raise ValueError("attempt_limits must not be empty")
        if not self.provenance:
            raise ValueError("provenance must not be empty")
        _require_unicode_scalars(self)
        return self


def canonical_content_hash(content: TemplatePackageContent) -> str:
    """Return the versioned, domain-separated hash of validated canonical content."""

    try:
        if type(content) is not TemplatePackageContent:
            raise TypeError("content must use the exact TemplatePackageContent type")
        raw = _snapshot_content_value(content)
        validated = TemplatePackageContent.model_validate(raw)
        payload = json.dumps(
            validated.model_dump(mode="json", round_trip=True),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except Exception:
        raise ValueError("invalid_template_content") from None
    return hashlib.sha256(_CONTENT_HASH_DOMAIN + payload).hexdigest()


def _snapshot_content_value(value: object) -> object:
    """Recursively copy exact DTO storage before public hash revalidation."""

    if isinstance(value, BaseModel):
        allowed_types = (
            TemplatePackageContent,
            FieldGroup,
            ValidatorRef,
            EvidencePolicy,
            ProvenanceReceipt,
        )
        if type(value) not in allowed_types:
            raise TypeError("content contains a non-canonical DTO type")
        storage = object.__getattribute__(value, "__dict__")
        if type(storage) is not dict:
            raise TypeError("content DTO storage must be an exact dictionary")
        field_names = tuple(type(value).model_fields)
        extra = object.__getattribute__(value, "__pydantic_extra__")
        private = object.__getattribute__(value, "__pydantic_private__")
        fields_set = object.__getattribute__(value, "__pydantic_fields_set__")
        if extra is not None or private is not None:
            raise ValueError("content DTO has hidden extra or private storage")
        if type(fields_set) is not set or len(fields_set) != len(field_names) or any(
            type(field_name) is not str or field_name not in field_names
            for field_name in fields_set
        ):
            raise ValueError("content DTO fields_set is non-canonical")
        items = tuple(storage.items())
        if len(items) != len(field_names):
            raise ValueError("content DTO field set is incomplete or extended")
        for field_name, _ in items:
            if type(field_name) is not str or field_name not in field_names:
                raise ValueError("content DTO field set is non-canonical")
        snapshot = dict(items)
        return {
            field_name: _snapshot_content_value(snapshot[field_name])
            for field_name in field_names
        }
    mapping_items: tuple[tuple[object, object], ...] | None
    if type(value) is dict:
        mapping_items = tuple(value.items())
    elif type(value) is _FrozenMapping:
        mapping_items = tuple(tuple.__iter__(value))
    else:
        mapping_items = None
    if mapping_items is not None:
        result: dict[str, object] = {}
        for item in mapping_items:
            if type(item) is not tuple or len(item) != 2:
                raise ValueError("content mapping items must be exact pairs")
            key, item_value = item
            if type(key) is not str or key in result:
                raise ValueError("content mapping keys must be unique exact strings")
            result[key] = _snapshot_content_value(item_value)
        return result
    if type(value) is tuple:
        return tuple(_snapshot_content_value(item) for item in value)
    if type(value) is list:
        return [_snapshot_content_value(item) for item in value]
    if value is None or type(value) in {str, int, bool}:
        return value
    raise TypeError("content contains a non-canonical value type")


def _require_unicode_scalars(value: object) -> None:
    """Ensure every string is made only from Unicode scalar values."""

    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ValueError("text must contain only Unicode scalar values")
        return
    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            _require_unicode_scalars(getattr(value, field_name))
        return
    if isinstance(value, Mapping):
        for key, item_value in value.items():
            _require_unicode_scalars(key)
            _require_unicode_scalars(item_value)
        return
    if isinstance(value, tuple):
        for item in value:
            _require_unicode_scalars(item)


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


class _TemplateContentMergeError(ValueError):
    def __init__(
        self,
        reason_code: Literal[
            "schema_version_mismatch",
            "field_group_conflict",
            "validator_conflict",
        ],
    ):
        self.reason_code = reason_code
        super().__init__(reason_code)


def _merge_field_groups(
    base: tuple[FieldGroup, ...], overlay: tuple[FieldGroup, ...]
) -> tuple[FieldGroup, ...]:
    result = list(base)
    by_id = {item.group_id: item for item in result}
    field_owners = {
        field_id: item.group_id
        for item in result
        for field_id in item.field_ids
    }
    for item in overlay:
        existing = by_id.get(item.group_id)
        if existing is None:
            if any(field_id in field_owners for field_id in item.field_ids):
                raise _TemplateContentMergeError("field_group_conflict")
            by_id[item.group_id] = item
            result.append(item)
            field_owners.update(
                {field_id: item.group_id for field_id in item.field_ids}
            )
        elif existing != item:
            raise _TemplateContentMergeError("field_group_conflict")
    return tuple(result)


def _merge_validators(
    base: tuple[ValidatorRef, ...], overlay: tuple[ValidatorRef, ...]
) -> tuple[ValidatorRef, ...]:
    """Add validators monotonically; replacement has no provable safe semantics."""

    result = list(base)
    by_id = {item.validator_id: item for item in result}
    for item in overlay:
        existing = by_id.get(item.validator_id)
        if existing is None:
            by_id[item.validator_id] = item
            result.append(item)
        elif existing != item:
            raise _TemplateContentMergeError("validator_conflict")
    return tuple(result)


def _merge_template_contents(
    base: TemplatePackageContent,
    overlay: TemplatePackageContent,
) -> TemplatePackageContent:
    """Apply one code-owned, deterministic and monotonic scope overlay."""

    if overlay.schema_version != base.schema_version:
        raise _TemplateContentMergeError("schema_version_mismatch")
    role_prompts = dict(base.role_prompts)
    role_prompts.update(overlay.role_prompts)
    attempt_limits = dict(base.attempt_limits)
    attempt_limits.update(overlay.attempt_limits)
    return TemplatePackageContent(
        schema_version=base.schema_version,
        field_groups=_merge_field_groups(base.field_groups, overlay.field_groups),
        role_prompts=role_prompts,
        validators=_merge_validators(base.validators, overlay.validators),
        evidence_policy=EvidencePolicy(
            require_quote=(
                base.evidence_policy.require_quote
                or overlay.evidence_policy.require_quote
            ),
            require_locator=(
                base.evidence_policy.require_locator
                or overlay.evidence_policy.require_locator
            ),
            minimum_sources=max(
                base.evidence_policy.minimum_sources,
                overlay.evidence_policy.minimum_sources,
            ),
        ),
        attempt_limits=attempt_limits,
        golden_slice_ref=overlay.golden_slice_ref,
        provenance=base.provenance + overlay.provenance,
    )


class ResolvedTemplateSource(_ImmutableModel):
    scope: TemplateScope
    package_id: NonBlankStr
    version_id: NonBlankStr
    content: TemplatePackageContent
    content_hash: Sha256Hex

    @model_validator(mode="after")
    def require_source_content_hash(self) -> ResolvedTemplateSource:
        if self.content_hash != canonical_content_hash(self.content):
            raise ValueError("content_hash_mismatch")
        return self


class ResolvedTemplate(_ImmutableModel):
    request: ResolutionRequest
    content: TemplatePackageContent
    content_hash: Sha256Hex
    source_chain: tuple[ResolvedTemplateSource, ...]

    @model_validator(mode="after")
    def require_resolved_hash_and_sources(self) -> ResolvedTemplate:
        if not self.source_chain:
            raise ValueError("source_chain must not be empty")
        expected_scopes = {
            "global": TemplateScope(space_id=self.request.space_id, level="global"),
            "product-line": TemplateScope(
                space_id=self.request.space_id,
                level="product-line",
                product_line_id=self.request.product_line_id,
            ),
            "document-type": TemplateScope(
                space_id=self.request.space_id,
                level="document-type",
                product_line_id=self.request.product_line_id,
                document_type_id=self.request.document_type_id,
            ),
            "product-family": TemplateScope(
                space_id=self.request.space_id,
                level="product-family",
                product_line_id=self.request.product_line_id,
                document_type_id=self.request.document_type_id,
                product_family_id=self.request.product_family_id,
            ),
        }
        level_order = {
            "global": 0,
            "product-line": 1,
            "document-type": 2,
            "product-family": 3,
        }
        previous_order = -1
        for source in self.source_chain:
            order = level_order[source.scope.level]
            if order <= previous_order or source.scope != expected_scopes[source.scope.level]:
                raise ValueError("source_chain is unordered, duplicated, or inapplicable")
            previous_order = order

        resolved_content = self.source_chain[0].content
        try:
            for source in self.source_chain[1:]:
                resolved_content = _merge_template_contents(
                    resolved_content,
                    source.content,
                )
        except _TemplateContentMergeError as exc:
            raise ValueError(f"source_chain {exc.reason_code}") from None
        if resolved_content != self.content:
            raise ValueError("resolved_content_mismatch")
        if self.content_hash != canonical_content_hash(self.content):
            raise ValueError("content_hash_mismatch")
        return self
