"""Typed, immutable contracts for Golden-set run admission.

Approval signatures deliberately cover only an immutable approval payload. Runtime
observations and derived admission state live outside that payload, so they cannot
silently change the identity of the plan that a human approved.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

type ApprovalDomain = Literal["budget", "provenance", "canary-review"]
type AdmissionState = Literal["READY", "BLOCKED"]

_REQUIRED_MODEL_ROLES = frozenset({"annotator", "weak_extractor", "judge"})
_SIGNATURE_PREFIX = "insurancekb.run-admission."
_DRIFTING_IDENTITY_PLACEHOLDERS = frozenset(
    {"best", "claude-session", "latest", "manual", "placeholder", "tbd", "unknown"}
)
_FIRST_CANARY_TARGET = ("annotation", "平安爱满分（2026）两全保险")
_CONTROLLED_CANARY_REVIEW_TARGETS = frozenset(
    {
        ("annotation", "平安爱满分（2026）两全保险"),
        ("annotation", "平安附加（2026）意外伤害保险"),
        ("baseline", "平安e生保（尊享版）医疗保险"),
        ("baseline", "平安e生保（悦享版）医疗保险"),
        ("baseline", "平安e生保（惠享版）长期医疗保险（费率可调）"),
        ("baseline", "平安创享盛世金越（尊享版26）终身寿险（分红型）"),
        ("baseline", "平安守护百分百（2026）两全保险"),
        ("baseline", "平安爱满分（2026）两全保险"),
        ("baseline", "平安盛世金越养老年金保险（分红型）"),
        ("baseline", "平安盛世金越（尊享版26）终身寿险"),
        ("baseline", "平安盛世金越（尊享版26）终身寿险（分红型）"),
        ("baseline", "平安盛世金越（至尊版26）年金保险（分红型）"),
        ("baseline", "平安福满分（2026）养老年金保险"),
        ("baseline", "平安附加（2026）失能收入损失保险"),
        ("baseline", "平安附加（2026）意外伤害保险"),
    }
)

type NonBlankStr = Annotated[
    StrictStr, StringConstraints(strip_whitespace=True, min_length=1)
]
type NonNegativeStrictInt = Annotated[StrictInt, Field(ge=0)]
type PositiveStrictInt = Annotated[StrictInt, Field(ge=1)]
type Sha256Digest = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
type GitObjectId = Annotated[
    StrictStr, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
]
type RunIdentityStr = Annotated[
    StrictStr,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
type PurposeStr = Annotated[
    StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]


class ApprovalVerificationError(ValueError):
    """Raised when a detached run-admission approval is not trustworthy."""


@dataclass(frozen=True, slots=True)
class TrustedKeyPolicy:
    """One trust-root key bound to its exact human and approval capabilities."""

    key_id: str
    approver_identity: str
    domains: frozenset[str]
    scopes: frozenset[str]
    roles: frozenset[str]
    public_key: Ed25519PublicKey

    def __post_init__(self) -> None:
        if not self.key_id.strip() or not self.approver_identity.strip():
            raise ValueError("trusted key identity fields must be non-blank")
        if not self.domains or not self.scopes or not self.roles:
            raise ValueError("trusted key policy capabilities must be non-empty")
        if any(
            not value.strip()
            for values in (self.domains, self.scopes, self.roles)
            for value in values
        ):
            raise ValueError("trusted key policy values must be non-blank")
        if not isinstance(self.public_key, Ed25519PublicKey):
            raise TypeError("trusted key policy requires an Ed25519 public key")


type TrustedAuthority = Ed25519PublicKey | TrustedKeyPolicy


class _ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def copy(
        self,
        *,
        include: object = None,
        exclude: object = None,
        update: dict[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Disable Pydantic's deprecated unvalidated copy path."""

        raise TypeError("copy() is disabled; use validated model_copy()")

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy safely: updates must pass the same validation and freeze steps as input."""

        if update is None:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


class ModelRolePlan(_ImmutableModel):
    identity_status: Literal["pinned"] = "pinned"
    provider: NonBlankStr
    model_id: NonBlankStr
    expected_model_revision: NonBlankStr | None = None
    immutable_deployment_id: NonBlankStr | None = None
    protocol: NonBlankStr
    base_url: NonBlankStr
    provider_policy: NonBlankStr
    credential_env_name: NonBlankStr

    @field_validator("model_id", "expected_model_revision", "immutable_deployment_id")
    @classmethod
    def reject_drifting_identity_placeholders(cls, value: str | None) -> str | None:
        if value is not None and value.casefold() in _DRIFTING_IDENTITY_PLACEHOLDERS:
            raise ValueError("model identity must not be a drifting placeholder")
        return value

    @model_validator(mode="after")
    def require_one_immutable_identity(self) -> ModelRolePlan:
        identities = (self.expected_model_revision, self.immutable_deployment_id)
        if sum(identity is not None and bool(identity.strip()) for identity in identities) != 1:
            raise ValueError(
                "exactly one signed expected_model_revision or immutable_deployment_id "
                "is required"
            )
        return self


class PendingModelRolePlan(_ImmutableModel):
    """Explicitly incomplete role selection for an honest BLOCKED plan.

    A pending role preserves the intended provider/model and safe connection policy,
    but cannot carry a revision or deployment that has not actually been proved.
    Runtime admission must reject this type before constructing a provider probe.
    """

    identity_status: Literal["pending_immutable_identity"]
    provider: NonBlankStr
    model_id: NonBlankStr | None = None
    expected_model_revision: None = None
    immutable_deployment_id: None = None
    protocol: NonBlankStr
    base_url: NonBlankStr
    provider_policy: NonBlankStr
    credential_env_name: NonBlankStr


type ModelRoleSelection = ModelRolePlan | PendingModelRolePlan


class RunAdmissionPlanPayload(_ImmutableModel):
    run_identity: RunIdentityStr
    purpose: PurposeStr
    model_roles: Mapping[StrictStr, ModelRoleSelection]
    identity_contract_hash: Sha256Digest | None = None
    budget_contract_hash: Sha256Digest | None

    @model_validator(mode="after")
    def require_exact_model_roles(self) -> RunAdmissionPlanPayload:
        if frozenset(self.model_roles) != _REQUIRED_MODEL_ROLES:
            raise ValueError(
                "model_roles must contain exactly annotator, weak_extractor, and judge"
            )
        object.__setattr__(self, "model_roles", MappingProxyType(dict(self.model_roles)))
        return self

    @field_serializer("model_roles")
    def serialize_model_roles(
        self, value: Mapping[str, ModelRoleSelection]
    ) -> dict[str, ModelRoleSelection]:
        return dict(value)


class BudgetApprovalEntry(_ImmutableModel):
    currency: StrictStr
    max_input_tokens: NonNegativeStrictInt
    max_output_tokens: NonNegativeStrictInt
    max_cost_minor_units: NonNegativeStrictInt
    budget_contract_hash: Sha256Digest


class ProvenanceApprovalEntry(_ImmutableModel):
    product_id: NonBlankStr
    annotator_provider: NonBlankStr
    annotator_model_id: NonBlankStr
    annotated_at_start: datetime
    annotated_at_end: datetime
    evidence_basis: NonBlankStr

    @model_validator(mode="after")
    def validate_annotation_window(self) -> ProvenanceApprovalEntry:
        for field_name, timestamp in (
            ("annotated_at_start", self.annotated_at_start),
            ("annotated_at_end", self.annotated_at_end),
        ):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError(f"{field_name} must include a timezone")
        if self.annotated_at_start > self.annotated_at_end:
            raise ValueError("annotated_at_start must be at or before annotated_at_end")
        return self


class ObservedAnnotationProvenance(ProvenanceApprovalEntry):
    """Annotation provenance backed by an observed provider/model time window."""

    provenance_kind: Literal["observed_annotation"]


class LegacyFrozenProvenance(_ImmutableModel):
    """Repository-frozen legacy evidence without a synthetic annotation window."""

    provenance_kind: Literal["legacy_frozen"]
    product_id: NonBlankStr
    product_digest: Sha256Digest
    wip_digest: Sha256Digest
    frozen_commit: GitObjectId
    evidence_path: NonBlankStr
    evidence_blob_id: GitObjectId
    evidence_digest: Sha256Digest
    recorded_agent_id: NonBlankStr
    evidence_frozen_at: datetime
    limitation: Literal["original_annotation_time_unavailable"]

    @model_validator(mode="after")
    def require_aware_freeze_time(self) -> LegacyFrozenProvenance:
        if (
            self.evidence_frozen_at.tzinfo is None
            or self.evidence_frozen_at.utcoffset() is None
        ):
            raise ValueError("evidence_frozen_at must include a timezone")
        return self


type ProvenanceApprovalSelection = Annotated[
    ObservedAnnotationProvenance | LegacyFrozenProvenance,
    Field(discriminator="provenance_kind"),
]


class ProductInputPlan(_ImmutableModel):
    """Immutable identity of all source inputs consumed for one product."""

    product_id: NonBlankStr
    line_key: NonBlankStr
    pdf_digests: Mapping[NonBlankStr, NonBlankStr]
    product_meta_path: Literal["product_meta.json"] = "product_meta.json"
    product_meta_digest: NonBlankStr
    fields_digest: NonBlankStr
    consumed_input_digests: Mapping[NonBlankStr, NonBlankStr]

    @model_validator(mode="after")
    def validate_and_freeze_input_digests(self) -> ProductInputPlan:
        reserved_source_names = {self.product_meta_path, "fields.json"}
        for path in (*self.pdf_digests, *self.consumed_input_digests):
            candidate = Path(path)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise ValueError("consumed input paths must be repository-relative")
        for path in self.pdf_digests:
            if len(Path(path).parts) != 1:
                raise ValueError("PDF paths must not cross product roots")
            if not path.casefold().endswith(".pdf"):
                raise ValueError("pdf_digests keys must name PDF files")
            if path in reserved_source_names:
                raise ValueError("PDF path collides with a reserved product input")
        product_meta_path = Path(self.product_meta_path)
        if (
            product_meta_path.is_absolute()
            or ".." in product_meta_path.parts
            or len(product_meta_path.parts) != 1
        ):
            raise ValueError("product_meta_path must be a filename within the product root")
        if set(self.consumed_input_digests) & {"fields.json"}:
            raise ValueError("consumed input path collides with reserved fields.json")
        object.__setattr__(
            self,
            "pdf_digests",
            MappingProxyType(dict(self.pdf_digests)),
        )
        object.__setattr__(
            self,
            "consumed_input_digests",
            MappingProxyType(dict(self.consumed_input_digests)),
        )
        return self

    @field_serializer("pdf_digests", "consumed_input_digests")
    def serialize_digest_mapping(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)


class PendingProductInputPlan(_ImmutableModel):
    """Product identity with an explicitly absent required meta/fields input."""

    input_status: Literal["pending_required_input"]
    product_id: NonBlankStr
    line_key: NonBlankStr
    pdf_digests: Mapping[NonBlankStr, NonBlankStr]
    product_meta_path: Literal["product_meta.json"] = "product_meta.json"
    product_meta_digest: NonBlankStr | None
    fields_digest: NonBlankStr | None
    consumed_input_digests: Mapping[NonBlankStr, NonBlankStr]

    @model_validator(mode="after")
    def validate_pending_and_freeze(self) -> PendingProductInputPlan:
        if self.product_meta_digest is not None and self.fields_digest is not None:
            raise ValueError("pending input requires an explicitly missing digest")
        for path in (*self.pdf_digests, *self.consumed_input_digests):
            candidate = Path(path)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise ValueError("consumed input paths must be repository-relative")
        for path in self.pdf_digests:
            if len(Path(path).parts) != 1 or not path.casefold().endswith(".pdf"):
                raise ValueError("pdf_digests keys must name PDF files")
        if set(self.consumed_input_digests) & {"fields.json"}:
            raise ValueError("consumed input path collides with reserved fields.json")
        object.__setattr__(
            self,
            "pdf_digests",
            MappingProxyType(dict(self.pdf_digests)),
        )
        object.__setattr__(
            self,
            "consumed_input_digests",
            MappingProxyType(dict(self.consumed_input_digests)),
        )
        return self

    @field_serializer("pdf_digests", "consumed_input_digests")
    def serialize_digest_mapping(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)


type ProductInputSelection = ProductInputPlan | PendingProductInputPlan


class BudgetPlan(BudgetApprovalEntry):
    """Immutable top-level input/output token and cost ceiling."""


class _ApprovalPayload(_ImmutableModel):
    plan_payload_hash: StrictStr
    run_identity: StrictStr
    purpose: StrictStr
    scope: StrictStr
    approver_identity: StrictStr
    approver_role: StrictStr
    issued_at: datetime
    expires_at: datetime


class BudgetApprovalPayload(_ApprovalPayload):
    revision: PositiveStrictInt = 1
    previous_approval_digest: Sha256Digest | None = None
    budget_entries: tuple[BudgetApprovalEntry, ...]

    @model_validator(mode="after")
    def require_explicit_approval_chain(self) -> BudgetApprovalPayload:
        if (self.revision == 1) != (self.previous_approval_digest is None):
            raise ValueError(
                "revision 1 must not have a previous digest; later revisions require one"
            )
        return self


class ProvenanceApprovalPayload(_ApprovalPayload):
    product_entries: tuple[ProvenanceApprovalSelection, ...]


class BudgetApprovalEnvelope(_ImmutableModel):
    domain: Literal["budget"]
    key_id: StrictStr
    payload: BudgetApprovalPayload
    signature: StrictStr


class ProvenanceApprovalEnvelope(_ImmutableModel):
    domain: Literal["provenance"]
    key_id: StrictStr
    payload: ProvenanceApprovalPayload
    signature: StrictStr


type ApprovalEnvelope = BudgetApprovalEnvelope | ProvenanceApprovalEnvelope


class CanaryReviewTarget(_ImmutableModel):
    """One code-controlled stage/product capability target."""

    stage: StrictStr
    product_id: NonBlankStr

    @model_validator(mode="after")
    def require_controlled_target(self) -> CanaryReviewTarget:
        if (self.stage, self.product_id) not in _CONTROLLED_CANARY_REVIEW_TARGETS:
            raise ValueError("canary review target is not code-controlled")
        return self


class CanaryReviewArtifactEvidence(_ImmutableModel):
    """Content-addressed canary outputs reviewed by the approver."""

    checkpoint_digest: Sha256Digest
    manifest_digest: Sha256Digest
    golden_digest: Sha256Digest
    quote_verification_digest: Sha256Digest
    disputed_quality_digest: Sha256Digest
    disputed_count: NonNegativeStrictInt
    record_count: PositiveStrictInt
    quality_threshold_version: NonBlankStr

    @model_validator(mode="after")
    def require_possible_disputed_count(self) -> Self:
        if self.disputed_count > self.record_count:
            raise ValueError("disputed_count must not exceed record_count")
        return self


class CanaryReviewUsageEvidence(_ImmutableModel):
    """Provider-reported usage and the exact signed rate used for its cost."""

    role: Literal["annotator"]
    input_tokens: NonNegativeStrictInt
    output_tokens: NonNegativeStrictInt
    cost_minor_units: NonNegativeStrictInt
    role_rate_digest: Sha256Digest


class CanaryReviewApprovalPayload(_ApprovalPayload):
    """Post-run evidence signed to grant a bounded continuation capability."""

    plan_payload_hash: Sha256Digest
    run_identity: RunIdentityStr
    purpose: PurposeStr
    scope: NonBlankStr
    approver_identity: NonBlankStr
    approver_role: NonBlankStr
    review_decision: Literal["approved", "rejected"]
    granted_targets: tuple[CanaryReviewTarget, ...]
    execution_plan_hash: Sha256Digest
    evaluated_revision: Annotated[
        StrictStr, StringConstraints(pattern=r"^[0-9a-f]{40,64}$")
    ]
    runtime_capability_version: NonBlankStr
    canary_target: CanaryReviewTarget
    budget_account_identity: Sha256Digest
    budget_revision: PositiveStrictInt
    budget_approval_digest: Sha256Digest
    settlement_snapshot_digest: Sha256Digest
    artifacts: CanaryReviewArtifactEvidence
    provider_usage: CanaryReviewUsageEvidence

    @field_validator("issued_at", "expires_at")
    @classmethod
    def require_aware_review_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canary review timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def require_fixed_canary_and_unique_grants(self) -> CanaryReviewApprovalPayload:
        canary = (self.canary_target.stage, self.canary_target.product_id)
        if canary != _FIRST_CANARY_TARGET:
            raise ValueError("canary target must be the code-fixed first canary")
        targets = tuple((item.stage, item.product_id) for item in self.granted_targets)
        if len(targets) != len(set(targets)):
            raise ValueError("granted_targets must be unique while preserving order")
        return self


class CanaryReviewApprovalEnvelope(_ImmutableModel):
    """Detached deployment-owned canary review; never a plan approval member."""

    domain: Literal["canary-review"]
    key_id: NonBlankStr
    payload: CanaryReviewApprovalPayload
    signature: NonBlankStr


type VerifiableApprovalEnvelope = ApprovalEnvelope | CanaryReviewApprovalEnvelope


class AdmissionObservation(_ImmutableModel):
    name: StrictStr
    observed_at: datetime
    value: StrictStr


class AdmissionDerivedState(_ImmutableModel):
    state: AdmissionState
    blockers: tuple[StrictStr, ...] = ()


class RunAdmissionPlan(_ImmutableModel):
    payload: RunAdmissionPlanPayload
    approval_envelopes: tuple[ApprovalEnvelope, ...] = ()
    observations: tuple[AdmissionObservation, ...] = ()
    derived_state: AdmissionDerivedState | None = None


def _canonical_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return _canonical_value(value.model_dump(mode="json", by_alias=True))
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise TypeError("float values are forbidden in canonical approval JSON")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        canonical: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            canonical[key] = _canonical_value(item)
        return canonical
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_bytes(value: object) -> bytes:
    """Return deterministic compact UTF-8 JSON, rejecting ambiguous numeric input."""

    canonical = _canonical_value(value)
    return json.dumps(
        canonical,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def plan_payload_hash(plan: RunAdmissionPlanPayload | RunAdmissionPlan) -> str:
    """Hash only the immutable plan payload, never observations or derived state."""

    payload = plan.payload if isinstance(plan, RunAdmissionPlan) else plan
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def approval_signed_bytes(domain: ApprovalDomain, payload: object) -> bytes:
    """Build the versioned, domain-separated bytes covered by an approval signature."""

    label = f"{_SIGNATURE_PREFIX}{domain}.v1\0".encode()
    return label + canonical_json_bytes(payload)


def _require_aware(timestamp: datetime, field_name: str) -> None:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ApprovalVerificationError(f"{field_name} must include a timezone")


def verify_approval_envelope(
    envelope: VerifiableApprovalEnvelope,
    *,
    expected_domain: ApprovalDomain,
    expected_plan_payload_hash: str,
    expected_run_identity: str,
    expected_purpose: str,
    expected_scope: str,
    trusted_public_keys: Mapping[str, TrustedAuthority],
    allowed_roles: frozenset[str],
    now: datetime,
) -> None:
    """Verify signature, authority, freshness, and anti-replay bindings."""

    if envelope.domain != expected_domain:
        raise ApprovalVerificationError("approval domain mismatch")

    payload = envelope.payload
    if payload.plan_payload_hash != expected_plan_payload_hash:
        raise ApprovalVerificationError("approval plan payload hash mismatch")
    if payload.run_identity != expected_run_identity:
        raise ApprovalVerificationError("approval run identity mismatch")
    if payload.purpose != expected_purpose:
        raise ApprovalVerificationError("approval purpose mismatch")
    if payload.scope != expected_scope:
        raise ApprovalVerificationError("approval scope mismatch")
    if payload.approver_role not in allowed_roles:
        raise ApprovalVerificationError("approver role is not authorized for this scope")

    _require_aware(payload.issued_at, "issued_at")
    _require_aware(payload.expires_at, "expires_at")
    _require_aware(now, "now")
    if payload.expires_at <= payload.issued_at:
        raise ApprovalVerificationError("approval expiry must follow issue time")
    if now < payload.issued_at:
        raise ApprovalVerificationError("approval is not yet valid")
    if now >= payload.expires_at:
        raise ApprovalVerificationError("approval is expired")

    trusted_authority = trusted_public_keys.get(envelope.key_id)
    if trusted_authority is None:
        raise ApprovalVerificationError("unknown key id")
    public_key = trusted_authority
    if isinstance(trusted_authority, TrustedKeyPolicy):
        if trusted_authority.key_id != envelope.key_id:
            raise ApprovalVerificationError("trusted key policy key id mismatch")
        if payload.approver_identity != trusted_authority.approver_identity:
            raise ApprovalVerificationError("approval identity violates trusted key policy")
        if envelope.domain not in trusted_authority.domains:
            raise ApprovalVerificationError("approval domain violates trusted key policy")
        if payload.scope not in trusted_authority.scopes:
            raise ApprovalVerificationError("approval scope violates trusted key policy")
        if payload.approver_role not in trusted_authority.roles:
            raise ApprovalVerificationError("approval role violates trusted key policy")
        public_key = trusted_authority.public_key
    if not isinstance(public_key, Ed25519PublicKey):
        raise ApprovalVerificationError("trusted key is not an Ed25519 public key")

    try:
        signature = base64.b64decode(envelope.signature, validate=True)
        if base64.b64encode(signature).decode("ascii") != envelope.signature:
            raise ApprovalVerificationError("approval signature encoding is noncanonical")
        public_key.verify(signature, approval_signed_bytes(envelope.domain, payload))
    except ApprovalVerificationError:
        raise
    except (binascii.Error, InvalidSignature, ValueError) as exc:
        raise ApprovalVerificationError("invalid approval signature") from exc


__all__ = [
    "AdmissionDerivedState",
    "AdmissionObservation",
    "ApprovalDomain",
    "ApprovalVerificationError",
    "BudgetPlan",
    "BudgetApprovalEntry",
    "BudgetApprovalEnvelope",
    "BudgetApprovalPayload",
    "CanaryReviewApprovalEnvelope",
    "CanaryReviewApprovalPayload",
    "CanaryReviewArtifactEvidence",
    "CanaryReviewTarget",
    "CanaryReviewUsageEvidence",
    "GitObjectId",
    "LegacyFrozenProvenance",
    "ModelRolePlan",
    "ModelRoleSelection",
    "PendingModelRolePlan",
    "PendingProductInputPlan",
    "ProductInputSelection",
    "ProductInputPlan",
    "ObservedAnnotationProvenance",
    "ProvenanceApprovalEntry",
    "ProvenanceApprovalEnvelope",
    "ProvenanceApprovalPayload",
    "ProvenanceApprovalSelection",
    "RunAdmissionPlan",
    "RunAdmissionPlanPayload",
    "TrustedAuthority",
    "TrustedKeyPolicy",
    "approval_signed_bytes",
    "canonical_json_bytes",
    "plan_payload_hash",
    "verify_approval_envelope",
]
