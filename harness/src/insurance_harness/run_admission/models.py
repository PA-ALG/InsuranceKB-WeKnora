"""Frozen DTOs for the independent OpenSpec 030 run-admission domain."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    TypeAdapter,
    field_serializer,
    field_validator,
    model_validator,
)

from insurance_harness.model_policy import ModelIdentity

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
CleanIntegrationSha = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"),
]
NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]
StrictPositiveInt = Annotated[StrictInt, Field(gt=0)]
SignatureB64 = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=88, max_length=88),
]

_RESOURCE_CAPS_DOMAIN = b"insurancekb.run-admission.resource-caps.v1\0"
_STRUCTURED_DISPATCH_DOMAIN = b"insurancekb.run-admission.structured-dispatch.v1\0"
_DEPLOYMENT_ROLES_DOMAIN = b"insurancekb.run-admission.deployment-roles.v1\0"
_CONTENT_SET_DOMAIN = b"insurancekb.run-admission.content-set.v1\0"
_MODEL_PLAN_DOMAIN = b"insurancekb.run-admission.model-plan.v1\0"
_AWARE_DATETIME_ADAPTER = TypeAdapter(AwareDatetime)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_digest(domain: bytes, value: object) -> str:
    return hashlib.sha256(domain + _canonical_json(value)).hexdigest()


def _normalize_utc(value: datetime) -> datetime:
    try:
        return value.astimezone(UTC)
    except (OSError, OverflowError, ValueError):
        raise ValueError("aware datetime cannot be represented canonically in UTC") from None


def _canonical_rfc3339(value: datetime) -> str:
    serialized = _AWARE_DATETIME_ADAPTER.dump_python(_normalize_utc(value), mode="json")
    if type(serialized) is not str:
        raise ValueError("invalid aware datetime serialization")
    return serialized


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    def copy(
        self,
        *,
        include: object = None,
        exclude: object = None,
        update: dict[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        raise TypeError("copy() is disabled; use validated model_copy()")

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        values = self.model_dump(mode="python", round_trip=True, warnings=False)
        if update is not None:
            values.update(dict(update))
        return type(self).model_validate(values)


def _revalidate[ModelT: _FrozenModel](
    model_type: type[ModelT],
    value: object,
) -> ModelT:
    if type(value) is not model_type:
        raise ValueError("invalid run-admission DTO")
    try:
        _assert_canonical_model_tree(value)
        fields = value.model_dump(mode="python", round_trip=True, warnings=False)
        return model_type.model_validate(fields)
    except Exception:
        raise ValueError("invalid run-admission DTO") from None


def _assert_canonical_model_tree(value: object) -> None:
    if isinstance(value, BaseModel):
        fields = set(type(value).model_fields)
        if (
            set(value.__dict__) != fields
            or value.__pydantic_fields_set__ != fields
            or value.__pydantic_extra__ not in (None, {})
            or value.__pydantic_private__ not in (None, {})
        ):
            raise ValueError("non-canonical model state")
        for item in value.__dict__.values():
            _assert_canonical_model_tree(item)
        return
    if isinstance(value, tuple):
        if type(value) is not tuple:
            raise ValueError("non-canonical tuple state")
        for item in value:
            _assert_canonical_model_tree(item)
        return
    if isinstance(value, (list, dict, set)):
        raise ValueError("mutable container in canonical model state")


class ContentArtifactLock(_FrozenModel):
    path: NonBlankStr
    sha256: Sha256Hex

    @field_validator("path")
    @classmethod
    def validate_content_path(cls, value: str) -> str:
        parts = value.split("/")
        if value.startswith("/") or not parts or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("content path must be repository-relative")
        if "\\" in value:
            raise ValueError("content path must use canonical POSIX separators")
        return value


class ContentSetLock(_FrozenModel):
    artifacts: tuple[ContentArtifactLock, ...]

    @model_validator(mode="after")
    def normalize_unique_artifacts(self) -> ContentSetLock:
        artifacts = tuple(sorted(self.artifacts, key=lambda item: item.path))
        if not artifacts or len({item.path for item in artifacts}) != len(artifacts):
            raise ValueError("content artifacts must be non-empty and unique")
        object.__setattr__(self, "artifacts", artifacts)
        return self

    @property
    def digest(self) -> str:
        return _canonical_digest(
            _CONTENT_SET_DOMAIN,
            self.model_dump(mode="json", round_trip=True),
        )


class RegistrationEntryLock(ContentArtifactLock):
    @field_validator("path")
    @classmethod
    def validate_registration_path(cls, value: str) -> str:
        if not value.endswith("/product_meta.json"):
            raise ValueError("registration path must identify product_meta.json")
        return value


class ResourceCaps(_FrozenModel):
    worker_limit: StrictPositiveInt
    attempt_limit: StrictPositiveInt
    time_limit_seconds: StrictPositiveInt
    token_limit: StrictPositiveInt

    @property
    def digest(self) -> str:
        return _canonical_digest(
            _RESOURCE_CAPS_DOMAIN,
            self.model_dump(mode="json", round_trip=True),
        )


class StructuredDispatchLock(_FrozenModel):
    registration_entries: tuple[RegistrationEntryLock, ...]
    source_registry_identity: NonBlankStr
    source_authority_hash: Sha256Hex
    record_schema_refs: tuple[NonBlankStr, ...]
    adapter_version: NonBlankStr
    canonicalizer_version: NonBlankStr
    source_profile_fingerprints: tuple[Sha256Hex, ...]
    mapping_manifest_hashes: tuple[Sha256Hex, ...]
    effective_mapping_versions: tuple[NonBlankStr, ...]

    @model_validator(mode="after")
    def normalize_and_require_exact_dispatch_lock(self) -> StructuredDispatchLock:
        entries = tuple(sorted(self.registration_entries, key=lambda entry: entry.path))
        if len(entries) != 5 or len({entry.path for entry in entries}) != 5:
            raise ValueError("structured dispatch must bind five unique meta entries")
        for field_name in (
            "record_schema_refs",
            "source_profile_fingerprints",
            "mapping_manifest_hashes",
            "effective_mapping_versions",
        ):
            values = tuple(getattr(self, field_name))
            if not values or len(values) != len(set(values)):
                raise ValueError(f"{field_name} must be non-empty and unique")
            object.__setattr__(self, field_name, tuple(sorted(values)))
        object.__setattr__(self, "registration_entries", entries)
        return self

    @property
    def digest(self) -> str:
        return _canonical_digest(
            _STRUCTURED_DISPATCH_DOMAIN,
            self.model_dump(mode="json", round_trip=True),
        )


def canonical_model_identities_hash(
    identities: tuple[ModelIdentity, ...],
) -> str:
    try:
        normalized = tuple(
            sorted(
                (
                    ModelIdentity.model_validate(
                        identity.model_dump(mode="python", round_trip=True, warnings=False)
                    )
                    for identity in tuple(identities)
                ),
                key=lambda identity: identity.identity_key,
            )
        )
    except Exception:
        raise ValueError("invalid deployment role identities") from None
    if not normalized or len({item.role for item in normalized}) != len(normalized):
        raise ValueError("deployment roles must be non-empty and unique")
    return _canonical_digest(
        _DEPLOYMENT_ROLES_DOMAIN,
        [item.model_dump(mode="json", round_trip=True) for item in normalized],
    )


def canonical_model_plan_hash(
    identities: tuple[ModelIdentity, ...],
) -> str:
    try:
        normalized = tuple(
            sorted(
                (
                    ModelIdentity.model_validate(
                        identity.model_dump(mode="python", round_trip=True, warnings=False)
                    )
                    for identity in tuple(identities)
                ),
                key=lambda identity: identity.identity_key,
            )
        )
    except Exception:
        raise ValueError("invalid model plan identities") from None
    if not normalized or len({item.role for item in normalized}) != len(normalized):
        raise ValueError("model plan identities must be non-empty and unique")
    return _canonical_digest(
        _MODEL_PLAN_DOMAIN,
        [item.model_dump(mode="json", round_trip=True) for item in normalized],
    )


class MvpAdmissionPlan(_FrozenModel):
    purpose: NonBlankStr
    run_schema_version: NonBlankStr
    run_id: NonBlankStr
    run_revision: NonBlankStr
    space_id: NonBlankStr
    entry_count: Literal[23]
    manifest_hash: Sha256Hex
    eligibility_hash: Sha256Hex
    golden_slice_hash: Sha256Hex
    routing_policy_identity: NonBlankStr
    routing_policy_hash: Sha256Hex
    schema_lock: ContentSetLock
    schema_hash: Sha256Hex
    template_lock: ContentSetLock
    template_lock_hash: Sha256Hex
    structured_dispatch: StructuredDispatchLock
    structured_dispatch_hash: Sha256Hex
    model_plan_hash: Sha256Hex
    approved_identities: tuple[ModelIdentity, ...]
    deployment_roles_hash: Sha256Hex
    approved_template_hashes: tuple[Sha256Hex, ...]
    resource_caps: ResourceCaps
    resource_caps_hash: Sha256Hex
    rights_hash: Sha256Hex
    provenance_hash: Sha256Hex
    clean_integration_sha: CleanIntegrationSha
    expires_at: AwareDatetime

    @field_validator("entry_count", mode="before")
    @classmethod
    def require_exact_entry_count_type(cls, value: object) -> object:
        if type(value) is not int or value != 23:
            raise ValueError("entry_count must be the exact integer 23")
        return value

    @field_serializer("expires_at")
    def serialize_expires_at(self, value: datetime) -> str:
        return _canonical_rfc3339(value)

    @model_validator(mode="after")
    def require_all_nested_locks_and_hashes(self) -> MvpAdmissionPlan:
        try:
            identities = tuple(
                sorted(
                    (
                        ModelIdentity.model_validate(
                            item.model_dump(mode="python", round_trip=True, warnings=False)
                        )
                        for item in self.approved_identities
                    ),
                    key=lambda item: item.identity_key,
                )
            )
        except Exception:
            raise ValueError("approved model identities are invalid") from None
        if self.structured_dispatch_hash != self.structured_dispatch.digest:
            raise ValueError("structured dispatch hash mismatch")
        if self.resource_caps_hash != self.resource_caps.digest:
            raise ValueError("resource caps hash mismatch")
        if self.schema_hash != self.schema_lock.digest:
            raise ValueError("schema hash mismatch")
        if self.template_lock_hash != self.template_lock.digest:
            raise ValueError("template lock hash mismatch")
        if self.model_plan_hash != canonical_model_plan_hash(identities):
            raise ValueError("model plan hash mismatch")
        if self.deployment_roles_hash != canonical_model_identities_hash(identities):
            raise ValueError("deployment roles hash mismatch")
        templates = tuple(sorted(self.approved_template_hashes))
        if not templates or len(templates) != len(set(templates)):
            raise ValueError("approved template hashes must be non-empty and unique")
        if templates != tuple(sorted(artifact.sha256 for artifact in self.template_lock.artifacts)):
            raise ValueError("approved template hashes do not match template lock")
        object.__setattr__(self, "approved_identities", identities)
        object.__setattr__(self, "approved_template_hashes", templates)
        object.__setattr__(self, "expires_at", _normalize_utc(self.expires_at))
        return self


def _validate_exact_raw_mvp_plan(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != set(MvpAdmissionPlan.model_fields):
        raise ValueError("invalid raw MVP admission plan schema")
    raw = value
    caps = raw.get("resource_caps")
    if type(caps) is not dict or set(caps) != set(ResourceCaps.model_fields):
        raise ValueError("invalid raw resource caps schema")
    if any(type(caps[name]) is not int or caps[name] <= 0 for name in ResourceCaps.model_fields):
        raise ValueError("resource caps must be exact positive integers")
    if type(raw.get("entry_count")) is not int or raw["entry_count"] != 23:
        raise ValueError("entry_count must be the exact integer 23")
    expires_at = raw.get("expires_at")
    if type(expires_at) is not str:
        raise ValueError("expires_at must be a canonical RFC3339 string")
    try:
        parsed_expiry = _AWARE_DATETIME_ADAPTER.validate_python(expires_at)
        canonical_expiry = _canonical_rfc3339(parsed_expiry)
    except (OSError, OverflowError, ValueError):
        raise ValueError("expires_at must be a canonical RFC3339 string") from None
    if canonical_expiry != expires_at:
        raise ValueError("expires_at must use the canonical RFC3339 representation")
    return raw


class ApprovalEnvelope(_FrozenModel):
    schema_version: Literal["insurancekb.run-admission-approval-envelope.v1"]
    signature_domain: NonBlankStr
    key_id: NonBlankStr
    public_key_fingerprint: Sha256Hex
    human_identity: NonBlankStr
    approver_role: NonBlankStr
    payload: MvpAdmissionPlan
    signature_b64: SignatureB64

    @field_validator("signature_b64")
    @classmethod
    def validate_signature_bytes(cls, value: str) -> str:
        try:
            decoded = base64.b64decode(value, validate=True)
        except Exception:
            raise ValueError("signature must be canonical base64") from None
        if len(decoded) != 64 or base64.b64encode(decoded).decode("ascii") != value:
            raise ValueError("signature must encode exactly 64 bytes")
        return value


def approval_signed_bytes(envelope: ApprovalEnvelope) -> bytes:
    canonical = _revalidate(ApprovalEnvelope, envelope)
    value = canonical.model_dump(mode="json", round_trip=True)
    value.pop("signature_b64")
    return canonical.signature_domain.encode("utf-8") + b"\0" + _canonical_json(value)


class AdmissionDecision(_FrozenModel):
    state: Literal["READY", "BLOCKED"]
    reason_code: NonBlankStr
    verified_binding_digest: Sha256Hex | None = None

    @model_validator(mode="after")
    def keep_authority_out_of_serializable_decision(self) -> AdmissionDecision:
        if (self.state == "READY") != (self.verified_binding_digest is not None):
            raise ValueError("READY decision requires verified binding digest")
        return self


__all__ = [
    "AdmissionDecision",
    "ApprovalEnvelope",
    "ContentArtifactLock",
    "ContentSetLock",
    "MvpAdmissionPlan",
    "RegistrationEntryLock",
    "ResourceCaps",
    "StructuredDispatchLock",
    "approval_signed_bytes",
    "canonical_model_identities_hash",
    "canonical_model_plan_hash",
]
