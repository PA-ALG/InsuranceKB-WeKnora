"""Immutable public models for the production model boundary."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC
from typing import Annotated, Any, Literal, Protocol, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    PositiveInt,
    StrictBytes,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

ModelFamily = Literal["minimax", "qwen", "qwen-vl"]
ModelRole = Literal["classify", "extract", "gap", "verify", "consensus"]
IdentityKey = tuple[str, str, ModelRole, str]
_MODEL_ROLES = frozenset({"classify", "extract", "gap", "verify", "consensus"})
PolicyReasonCode = Literal[
    "policy_allowed",
    "purpose_mismatch",
    "run_schema_version_mismatch",
    "space_id_mismatch",
    "run_id_mismatch",
    "run_revision_mismatch",
    "admission_artifact_digest_mismatch",
    "verified_binding_digest_mismatch",
    "model_plan_hash_mismatch",
    "admission_expired",
    "template_not_approved",
    "strong_model",
    "family_not_approved",
    "invalid_identity",
    "rolling_identity",
    "identity_not_approved",
    "identity_not_admission_approved",
]

NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]
Sha256Hex = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
CleanIntegrationSha = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"),
]


def _normalize_identity_keys(keys: Iterable[IdentityKey]) -> frozenset[IdentityKey]:
    """Reject caller-controlled equality/hash behavior and freeze canonical keys."""

    try:
        candidates = tuple(keys)
    except Exception:
        raise ValueError("invalid approved identity keys") from None

    normalized: set[IdentityKey] = set()
    for key in candidates:
        if type(key) is not tuple or len(key) != 4:
            raise ValueError("invalid approved identity keys")
        if any(type(part) is not str for part in key):
            raise ValueError("invalid approved identity keys")
        provider, deployment_id, role, policy_version = key
        stable_parts = (provider, deployment_id, policy_version)
        if any(
            not value or value != value.strip() or len(value) > 256
            for value in stable_parts
        ):
            raise ValueError("invalid approved identity keys")
        if role not in _MODEL_ROLES:
            raise ValueError("invalid approved identity keys")
        canonical: IdentityKey = (
            provider,
            deployment_id,
            role,
            policy_version,
        )
        if canonical in normalized:
            raise ValueError("invalid approved identity keys")
        normalized.add(canonical)
    return frozenset(normalized)


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
        """Revalidate every update instead of trusting Pydantic's unchecked copy."""

        values = self.model_dump(mode="python", round_trip=True)
        if update is not None:
            values.update(update)
        return type(self).model_validate(values)


class ModelIdentity(_ImmutableModel):
    provider: NonBlankStr
    deployment_id: NonBlankStr
    family: ModelFamily
    role: ModelRole
    policy_version: NonBlankStr

    @property
    def identity_key(self) -> IdentityKey:
        """Return the exact, stable identity used by the injected approval set."""

        return (self.provider, self.deployment_id, self.role, self.policy_version)


class ModelPermitView(_ImmutableModel):
    """Serializable permit receipt; possession never grants model-call authority."""

    identity: ModelIdentity
    purpose: NonBlankStr
    run_schema_version: NonBlankStr
    space_id: NonBlankStr
    run_id: NonBlankStr
    run_revision: NonBlankStr
    admission_hash: Sha256Hex
    verified_binding_digest: Sha256Hex
    template_hash: Sha256Hex
    model_plan_hash: Sha256Hex
    policy_snapshot_digest: Sha256Hex
    call_scope_hash: Sha256Hex
    expires_at: AwareDatetime

    @field_validator("expires_at", mode="after")
    @classmethod
    def normalize_expiry_to_utc(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(UTC)


_PERMIT_VIEW_DIGEST_DOMAIN = b"insurancekb.model-policy.permit-view.v1\0"


def _model_permit_view_digest(view: ModelPermitView) -> str:
    encoded = json.dumps(
        view.model_dump(mode="json", round_trip=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(_PERMIT_VIEW_DIGEST_DOMAIN + encoded).hexdigest()


class ModelCallContext(_ImmutableModel):
    """Secret-free, exact scope for one proposed production model call."""

    identity: ModelIdentity
    purpose: NonBlankStr
    run_schema_version: NonBlankStr
    space_id: NonBlankStr
    run_id: NonBlankStr
    run_revision: NonBlankStr
    admission_hash: Sha256Hex
    verified_binding_digest: Sha256Hex
    template_hash: Sha256Hex
    model_plan_hash: Sha256Hex
    call_scope_hash: Sha256Hex


class ModelCallFacts(_ImmutableModel):
    """Caller facts for one call; all authority is recomputed by the gateway."""

    job_id: NonBlankStr
    stage: NonBlankStr
    attempt: PositiveInt
    input_digest: Sha256Hex
    content_digest: Sha256Hex
    rendered_prompt_digest: Sha256Hex
    purpose: NonBlankStr
    run_schema_version: NonBlankStr
    space_id: NonBlankStr
    run_id: NonBlankStr
    run_revision: NonBlankStr
    admission_artifact_digest: Sha256Hex
    template_hash: Sha256Hex
    model_plan_hash: Sha256Hex
    identity: ModelIdentity
    role: ModelRole


class ModelCallRequest(_ImmutableModel):
    """Frozen transport input; raw values are never copied into audit records."""

    content: StrictBytes
    rendered_prompt: StrictBytes

    @model_validator(mode="after")
    def require_nonempty_transport_input(self) -> ModelCallRequest:
        if not self.content or not self.rendered_prompt:
            raise ValueError("model call request values must not be empty")
        try:
            self.content.decode("utf-8", errors="strict")
            self.rendered_prompt.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise ValueError("model call request values must be valid UTF-8") from None
        return self


class PolicyReceipt(_ImmutableModel):
    """Serializable audit data; it never grants transport authority."""

    decision: Literal["ALLOW", "DENY"]
    reason_code: PolicyReasonCode
    identity_key: IdentityKey
    purpose: NonBlankStr
    run_schema_version: NonBlankStr
    space_id: NonBlankStr
    run_id: NonBlankStr
    run_revision: NonBlankStr
    admission_hash: Sha256Hex
    request_digest: Sha256Hex
    binding_digest: Sha256Hex
    verified_binding_digest: Sha256Hex
    template_hash: Sha256Hex
    model_plan_hash: Sha256Hex
    call_scope_hash: Sha256Hex
    attempted_context_digest: Sha256Hex
    policy_snapshot_digest: Sha256Hex
    permit_digest: Sha256Hex | None = None
    permit_view: ModelPermitView | None = None
    evaluated_at: AwareDatetime

    @field_validator("evaluated_at", mode="after")
    @classmethod
    def normalize_evaluated_at_to_utc(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_coherent_decision_shape(self) -> PolicyReceipt:
        if self.decision == "DENY":
            if (
                self.reason_code == "policy_allowed"
                or self.permit_view is not None
                or self.permit_digest is not None
            ):
                raise ValueError("DENY receipt cannot carry permit authority data")
            return self
        view = self.permit_view
        if (
            self.reason_code != "policy_allowed"
            or view is None
            or self.permit_digest is None
        ):
            raise ValueError("ALLOW receipt requires coherent permit view and digest")
        if (
            self.permit_digest != _model_permit_view_digest(view)
            or self.identity_key != view.identity.identity_key
            or self.purpose != view.purpose
            or self.run_schema_version != view.run_schema_version
            or self.space_id != view.space_id
            or self.run_id != view.run_id
            or self.run_revision != view.run_revision
            or self.admission_hash != view.admission_hash
            or self.verified_binding_digest != view.verified_binding_digest
            or self.template_hash != view.template_hash
            or self.model_plan_hash != view.model_plan_hash
            or self.policy_snapshot_digest != view.policy_snapshot_digest
            or self.call_scope_hash != view.call_scope_hash
            or self.evaluated_at >= view.expires_at
        ):
            raise ValueError("ALLOW receipt scope does not match permit view")
        return self


class ReceiptSink(Protocol):
    """Port used by the guarded client to persist allow and deny receipts."""

    def record(self, receipt: PolicyReceipt, /) -> None: ...
