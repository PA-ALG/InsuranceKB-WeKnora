"""Pure 052-binding receipts and source authority for OpenSpec 058."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final, Literal, Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictStr,
    StringConstraints,
    ValidationError,
    computed_field,
    field_validator,
    model_validator,
)

from insurance_harness.canonical import canonical_hash

NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=512, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
MaterialRole = Literal["terms", "brochure", "rate_table"]
AuthorityRelation = Literal["higher", "equal", "lower"]

FACT_SCOPE_OBJECT_TYPE: Final[str] = "incremental-fact-scope.v1"
MATERIAL_BINDING_OBJECT_TYPE: Final[str] = "incremental-material-binding.v1"
SOURCE_AUTHORITY_OBJECT_TYPE: Final[str] = "incremental-source-authority.v1"
_UTC_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%S.%fZ"
_WILDCARD_CHARACTERS: Final[frozenset[str]] = frozenset("*?[]{}")
_UNRESOLVED_IDENTITY_TOKENS: Final[frozenset[str]] = frozenset({"all", "any", "unknown"})


class _FieldAuthority(Protocol):
    primary_role: MaterialRole
    support_roles: tuple[MaterialRole, ...]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class SourceAuthorityContractError(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _canonical_utc(value: str) -> str:
    try:
        parsed = datetime.strptime(value, _UTC_FORMAT)
    except ValueError:
        raise ValueError("timestamp_must_be_canonical_utc") from None
    if parsed.strftime(_UTC_FORMAT) != value:
        raise ValueError("timestamp_must_be_canonical_utc")
    return value


def _resolved_identity(value: str) -> str:
    if any(character in value for character in _WILDCARD_CHARACTERS):
        raise ValueError("wildcard_identity_forbidden")
    if value.casefold() in _UNRESOLVED_IDENTITY_TOKENS:
        raise ValueError("unresolved_identity_forbidden")
    return value


class FactScopeV1(_FrozenModel):
    space_id: NonBlankStr
    product_version_id: NonBlankStr
    subject_id: NonBlankStr
    field_id: NonBlankStr
    valid_from: NonBlankStr
    valid_through: NonBlankStr | None
    region: NonBlankStr
    channel: NonBlankStr
    population: NonBlankStr
    conditions: tuple[NonBlankStr, ...]

    @field_validator(
        "space_id",
        "product_version_id",
        "subject_id",
        "field_id",
        "region",
        "channel",
        "population",
    )
    @classmethod
    def require_resolved_identity(cls, value: str) -> str:
        return _resolved_identity(value)

    @field_validator("valid_from", "valid_through")
    @classmethod
    def require_canonical_time(cls, value: str | None) -> str | None:
        return None if value is None else _canonical_utc(value)

    @model_validator(mode="after")
    def require_canonical_scope(self) -> Self:
        if (
            len(self.conditions) != len(set(self.conditions))
            or self.conditions != tuple(sorted(self.conditions))
            or (self.valid_through is not None and self.valid_through <= self.valid_from)
        ):
            raise ValueError("invalid_fact_scope")
        for condition in self.conditions:
            _resolved_identity(condition)
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def scope_hash(self) -> str:
        payload = self.model_dump(mode="python", exclude={"scope_hash"})
        return canonical_hash(FACT_SCOPE_OBJECT_TYPE, payload)


class MaterialBindingReceiptV1(_FrozenModel):
    """Task-local registration of one exact 052 binding and source revision."""

    catalog_hash: Sha256Hex
    binding_hash: Sha256Hex
    space_id: NonBlankStr
    product_version_id: NonBlankStr
    source_id: Sha256Hex
    source_revision_id: NonBlankStr
    material_role: MaterialRole

    @field_validator("space_id", "product_version_id", "source_revision_id")
    @classmethod
    def require_resolved_identity(cls, value: str) -> str:
        return _resolved_identity(value)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def registration_hash(self) -> str:
        payload = self.model_dump(mode="python", exclude={"registration_hash"})
        return canonical_hash(MATERIAL_BINDING_OBJECT_TYPE, payload)


class SourceAuthorityV1(_FrozenModel):
    source_id: Sha256Hex
    source_revision_id: NonBlankStr
    material_role: MaterialRole
    binding: MaterialBindingReceiptV1
    reliable_at: NonBlankStr

    @field_validator("source_revision_id")
    @classmethod
    def require_resolved_revision(cls, value: str) -> str:
        return _resolved_identity(value)

    @field_validator("reliable_at")
    @classmethod
    def require_reliable_time(cls, value: str) -> str:
        return _canonical_utc(value)

    @model_validator(mode="after")
    def require_binding_identity(self) -> Self:
        binding = self.binding
        if (
            self.source_id != binding.source_id
            or self.source_revision_id != binding.source_revision_id
            or self.material_role != binding.material_role
        ):
            raise ValueError("authority_binding_mismatch")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def authority_hash(self) -> str:
        payload = self.model_dump(mode="python", exclude={"authority_hash"})
        return canonical_hash(SOURCE_AUTHORITY_OBJECT_TYPE, payload)


def validate_source_authority(
    authority: SourceAuthorityV1,
    *,
    catalog_hash: str,
    registered_binding_hashes: frozenset[str],
    space_id: str,
    product_version_id: str,
    field_authority: _FieldAuthority,
) -> SourceAuthorityV1:
    try:
        canonical = SourceAuthorityV1.model_validate(authority)
    except ValidationError as exc:
        raise SourceAuthorityContractError("authority_binding_mismatch") from exc
    binding = canonical.binding
    if binding.catalog_hash != catalog_hash:
        raise SourceAuthorityContractError("authority_policy_mismatch")
    if (
        binding.binding_hash not in registered_binding_hashes
        or binding.space_id != space_id
        or binding.product_version_id != product_version_id
    ):
        raise SourceAuthorityContractError("authority_binding_mismatch")
    if canonical.material_role not in (
        field_authority.primary_role,
        *field_authority.support_roles,
    ):
        raise SourceAuthorityContractError("authority_policy_mismatch")
    return canonical


def compare_source_authority(
    incoming: SourceAuthorityV1,
    existing: SourceAuthorityV1,
    *,
    field_authority: _FieldAuthority,
) -> AuthorityRelation:
    incoming_rank = 1 if incoming.material_role == field_authority.primary_role else 0
    existing_rank = 1 if existing.material_role == field_authority.primary_role else 0
    if incoming_rank != existing_rank:
        return "higher" if incoming_rank > existing_rank else "lower"
    if incoming.reliable_at == existing.reliable_at:
        return "equal"
    return "higher" if incoming.reliable_at > existing.reliable_at else "lower"


__all__ = [
    "FACT_SCOPE_OBJECT_TYPE",
    "MATERIAL_BINDING_OBJECT_TYPE",
    "SOURCE_AUTHORITY_OBJECT_TYPE",
    "FactScopeV1",
    "MaterialBindingReceiptV1",
    "SourceAuthorityContractError",
    "SourceAuthorityV1",
    "compare_source_authority",
    "validate_source_authority",
]
