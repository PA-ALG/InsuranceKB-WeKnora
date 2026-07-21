"""Domain-separated deployment authorization and normalized receipt contracts.

The models in this module are pure.  They do not access the provider or the budget
database; callers must verify exact code-owned expectations before either boundary.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Self

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from insurance_harness.goldenset.admission_models import (
    TrustedAuthority,
    TrustedKeyPolicy,
    canonical_json_bytes,
)

PROVISIONING_AUTHORIZATION_DOMAIN: Literal[
    "insurancekb.run-admission.provisioning.v1"
] = "insurancekb.run-admission.provisioning.v1"
ADOPTION_AUTHORIZATION_DOMAIN: Literal[
    "insurancekb.run-admission.deployment-adoption.v1"
] = "insurancekb.run-admission.deployment-adoption.v1"
PRICING_EVIDENCE_DOMAIN: Literal[
    "insurancekb.run-admission.pricing.v1"
] = "insurancekb.run-admission.pricing.v1"
PROVIDER_CAP_DOMAIN: Literal[
    "insurancekb.run-admission.provider-cap.v1"
] = "insurancekb.run-admission.provider-cap.v1"
CLEANUP_AUTHORIZATION_DOMAIN: Literal[
    "insurancekb.run-admission.deployment-cleanup.v1"
] = "insurancekb.run-admission.deployment-cleanup.v1"

_PROVISIONING_SIGNING_PREFIX = b"insurancekb.run-admission.provisioning.v1\0"
_ADOPTION_SIGNING_PREFIX = b"insurancekb.run-admission.deployment-adoption.v1\0"
_PRICING_SIGNING_PREFIX = b"insurancekb.run-admission.pricing.v1\0"
_PROVIDER_CAP_SIGNING_PREFIX = b"insurancekb.run-admission.provider-cap.v1\0"
_CLEANUP_SIGNING_PREFIX = b"insurancekb.run-admission.deployment-cleanup.v1\0"
_AUTHORIZATION_DIGEST_DOMAIN = b"insurancekb.run-admission.infrastructure-authorization.v1\0"
_RECEIPT_DIGEST_DOMAIN = b"insurancekb.run-admission.deployment-receipt.v1\0"
_PRICING_EVIDENCE_DIGEST_DOMAIN = b"insurancekb.run-admission.pricing-evidence.v1\0"
_PRICING_APPROVAL_DIGEST_DOMAIN = b"insurancekb.run-admission.pricing-approval.v1\0"
_CAP_EVIDENCE_DIGEST_DOMAIN = b"insurancekb.run-admission.provider-cap-evidence.v1\0"
_CAP_APPROVAL_DIGEST_DOMAIN = b"insurancekb.run-admission.provider-cap-approval.v1\0"
_CLEANUP_AUTHORIZATION_DIGEST_DOMAIN = (
    b"insurancekb.run-admission.deployment-cleanup-authorization.v1\0"
)
_MAX_AUTHORITY_EVIDENCE_BYTES = 64 * 1024

type AuthorizationDomain = Literal[
    "insurancekb.run-admission.provisioning.v1",
    "insurancekb.run-admission.deployment-adoption.v1",
]
type NonBlankStr = Annotated[
    StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)
]
type Sha256Digest = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
type DigestRef = Annotated[StrictStr, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
type PositiveCost = Annotated[StrictInt, Field(ge=1, le=2**63 - 1)]
type NonNegativeCost = Annotated[StrictInt, Field(ge=0, le=2**63 - 1)]


class AuthorizationVerificationError(ValueError):
    """A deployment authorization or receipt cannot be trusted exactly."""


class _ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def copy(
        self,
        *,
        include: object = None,
        exclude: object = None,
        update: dict[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        raise TypeError("copy() is disabled; use validated model_copy()")

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        if update is None:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


def _require_aware_active_window(start: datetime, end: datetime, label: str) -> None:
    for timestamp in (start, end):
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError(f"{label} timestamps must include a timezone")
    if end <= start:
        raise ValueError(f"{label} expiry must follow its start")


class PricingEvidenceContent(_ImmutableModel):
    """Canonical provider pricing facts; authority is established separately."""

    version: Literal["insurancekb.run-admission.pricing-evidence.v1"]
    issuer: NonBlankStr
    provider: Literal["bailian"]
    workspace_ref: NonBlankStr
    project_ref: DigestRef
    credential_ref: DigestRef
    region: Literal["cn-beijing"]
    base_model: Literal["qwen3.7-plus-2026-05-26", "deepseek-v4-flash"]
    request_plan: Literal["ptu_v2"]
    receipt_plan: Literal["ptu"]
    input_tpm_quota: Literal[10_000]
    output_tpm_quota: Literal[1_000]
    currency: Literal["CNY"]
    effective_from: datetime
    effective_until: datetime
    billing_quantum_seconds: Annotated[StrictInt, Field(ge=1, le=31_536_000)]
    round_up_rule: Literal["ceiling"]
    fixed_cost_per_quantum_minor_units: PositiveCost
    input_cost_per_million_minor_units: PositiveCost
    output_cost_per_million_minor_units: PositiveCost
    tiers_policy: Literal["worst_case_included"]
    thinking_policy: Literal["worst_case_included"]
    cache_policy: Literal["worst_case_included"]
    overflow_policy: Literal["block"]

    @model_validator(mode="after")
    def require_effective_window(self) -> Self:
        for name, timestamp in (
            ("effective_from", self.effective_from),
            ("effective_until", self.effective_until),
        ):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError(f"{name} must include a timezone")
        if self.effective_until <= self.effective_from:
            raise ValueError("pricing effective window is invalid")
        return self


class PricingEvidenceApprovalPayload(_ImmutableModel):
    evidence_digest: Sha256Digest
    evidence: PricingEvidenceContent
    scope: NonBlankStr
    approver_identity: NonBlankStr
    approver_role: Literal["pricing-evidence-approver"]
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def require_approval_window(self) -> Self:
        _require_aware_active_window(self.issued_at, self.expires_at, "pricing approval")
        return self


class PricingEvidenceApproval(_ImmutableModel):
    domain: Literal["insurancekb.run-admission.pricing.v1"]
    key_id: NonBlankStr
    payload: PricingEvidenceApprovalPayload
    signature: NonBlankStr


class ProviderCapEvidenceContent(_ImmutableModel):
    version: Literal["insurancekb.run-admission.provider-cap-evidence.v1"]
    issuer: NonBlankStr
    provider: Literal["bailian"]
    workspace_ref: NonBlankStr
    project_ref: DigestRef
    credential_ref: DigestRef
    currency: Literal["CNY"]
    max_cost_minor_units: PositiveCost
    coverage: tuple[Literal["fixed_infrastructure"], Literal["inference"]]
    observed_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def require_cap_window(self) -> Self:
        _require_aware_active_window(self.observed_at, self.expires_at, "provider cap")
        return self


class ProviderCapApprovalPayload(_ImmutableModel):
    evidence_digest: Sha256Digest
    evidence: ProviderCapEvidenceContent
    scope: NonBlankStr
    approver_identity: NonBlankStr
    approver_role: Literal["provider-cap-attestor"]
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def require_approval_window(self) -> Self:
        _require_aware_active_window(self.issued_at, self.expires_at, "cap approval")
        return self


class ProviderCapApproval(_ImmutableModel):
    domain: Literal["insurancekb.run-admission.provider-cap.v1"]
    key_id: NonBlankStr
    payload: ProviderCapApprovalPayload
    signature: NonBlankStr


class DeploymentCleanupAuthorizationPayload(_ImmutableModel):
    run_identity: NonBlankStr
    purpose: NonBlankStr
    scope: NonBlankStr
    operation_id: NonBlankStr
    reserve_id: NonBlankStr
    receipt_digest: Sha256Digest
    deployed_model: NonBlankStr
    workspace_ref: NonBlankStr
    project_ref: DigestRef
    credential_ref: DigestRef
    expected_remote_manifest_digest: Sha256Digest
    cleanup_reason: NonBlankStr
    cleanup_deadline: datetime
    approver_identity: NonBlankStr
    approver_role: Literal["deployment-cleanup-operator"]
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def require_cleanup_window(self) -> Self:
        _require_aware_active_window(self.issued_at, self.expires_at, "cleanup approval")
        if (
            self.cleanup_deadline.tzinfo is None
            or self.cleanup_deadline.utcoffset() is None
            or self.cleanup_deadline <= self.issued_at
        ):
            raise ValueError("cleanup deadline must follow issue time")
        return self


class DeploymentCleanupAuthorization(_ImmutableModel):
    domain: Literal["insurancekb.run-admission.deployment-cleanup.v1"]
    key_id: NonBlankStr
    payload: DeploymentCleanupAuthorizationPayload
    signature: NonBlankStr


class _CommonInfrastructureAuthorizationPayload(_ImmutableModel):
    provider: Literal["bailian"]
    run_identity: NonBlankStr
    purpose: NonBlankStr
    scope: NonBlankStr
    operation_id: NonBlankStr
    infrastructure_reserve_id: NonBlankStr
    workspace_ref: NonBlankStr
    project_ref: DigestRef
    credential_ref: DigestRef
    region: NonBlankStr
    base_model: NonBlankStr
    request_plan: Literal["ptu_v2"]
    receipt_plan: Literal["ptu"]
    input_tpm_quota: Literal[10_000]
    output_tpm_quota: Literal[1_000]
    pricing_evidence_digest: Sha256Digest
    provider_cap_evidence_digest: Sha256Digest
    pricing_approval_digest: Sha256Digest
    provider_cap_approval_digest: Sha256Digest
    currency: Literal["CNY"]
    provider_cap_max_cost_minor_units: PositiveCost
    provider_cap_coverage: tuple[
        Literal["fixed_infrastructure"], Literal["inference"]
    ]
    provider_cap_expires_at: datetime
    maximum_cost_minor_units: PositiveCost
    cleanup_deadline: datetime
    approver_identity: NonBlankStr
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def require_aware_ordered_window(self) -> Self:
        for field_name, timestamp in (
            ("issued_at", self.issued_at),
            ("expires_at", self.expires_at),
            ("cleanup_deadline", self.cleanup_deadline),
            ("provider_cap_expires_at", self.provider_cap_expires_at),
        ):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError(f"{field_name} must include a timezone")
        if self.expires_at <= self.issued_at:
            raise ValueError("authorization expiry must follow issue time")
        if self.cleanup_deadline <= self.issued_at:
            raise ValueError("cleanup deadline must follow issue time")
        if self.provider_cap_expires_at <= self.issued_at:
            raise ValueError("provider cap expiry must follow issue time")
        if self.maximum_cost_minor_units > self.provider_cap_max_cost_minor_units:
            raise ValueError("maximum infrastructure cost exceeds provider cap")
        return self


class ProvisioningAuthorizationPayload(_CommonInfrastructureAuthorizationPayload):
    transition: Literal["create"]
    approver_role: Literal["deployment-provisioner"]


class ExistingDeploymentAdoptionAuthorizationPayload(
    _CommonInfrastructureAuthorizationPayload
):
    transition: Literal["adopt_existing"]
    approver_role: Literal["budget-approver"]
    deployed_model: NonBlankStr
    receipt_digest: Sha256Digest
    gmt_create: datetime
    preexisting: Literal[True]
    limitation: Literal["not_preauthorized_by_031"]
    incurred_cost_minor_units: NonNegativeCost
    future_max_cost_minor_units: PositiveCost

    @model_validator(mode="after")
    def require_conservative_preexisting_cost(self) -> Self:
        if self.gmt_create.tzinfo is None or self.gmt_create.utcoffset() is None:
            raise ValueError("gmt_create must include a timezone")
        if self.gmt_create >= self.issued_at:
            raise ValueError("preexisting deployment must predate adoption authorization")
        if (
            self.incurred_cost_minor_units + self.future_max_cost_minor_units
            != self.maximum_cost_minor_units
        ):
            raise ValueError("adoption maximum must equal incurred plus future maximum cost")
        return self


class ProvisioningAuthorization(_ImmutableModel):
    domain: Literal["insurancekb.run-admission.provisioning.v1"]
    key_id: NonBlankStr
    payload: ProvisioningAuthorizationPayload
    signature: NonBlankStr


class ExistingDeploymentAdoptionAuthorization(_ImmutableModel):
    domain: Literal["insurancekb.run-admission.deployment-adoption.v1"]
    key_id: NonBlankStr
    payload: ExistingDeploymentAdoptionAuthorizationPayload
    signature: NonBlankStr


type InfrastructureAuthorization = (
    ProvisioningAuthorization | ExistingDeploymentAdoptionAuthorization
)
type InfrastructureAuthorizationPayload = (
    ProvisioningAuthorizationPayload | ExistingDeploymentAdoptionAuthorizationPayload
)


class DeploymentReceiptContent(_ImmutableModel):
    """Allowlisted provider receipt content; raw provider responses never enter it."""

    operation_id: NonBlankStr
    infrastructure_reserve_id: NonBlankStr
    workspace_ref: NonBlankStr
    project_ref: DigestRef
    credential_ref: DigestRef
    workspace_evidence_digest: Sha256Digest
    region: NonBlankStr
    base_model: NonBlankStr
    deployed_model: NonBlankStr
    request_plan: Literal["ptu_v2"]
    receipt_plan: Literal["ptu"]
    input_tpm: Literal[10_000]
    output_tpm: Literal[1_000]
    gmt_create: datetime
    gmt_modified: datetime
    cleanup_state: Literal["required"]
    operation_marker: Annotated[
        StrictStr, StringConstraints(pattern=r"^ikb031-[0-9a-f]{24}$")
    ]
    deployment_suffix: Annotated[
        StrictStr, StringConstraints(pattern=r"^031-[0-9a-f]{16}$")
    ]
    remote_manifest_digest: Sha256Digest

    @model_validator(mode="after")
    def require_gmt_times(self) -> Self:
        for field_name, timestamp in (
            ("gmt_create", self.gmt_create),
            ("gmt_modified", self.gmt_modified),
        ):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError(f"{field_name} must include a timezone")
            if timestamp.utcoffset() != timedelta(0):
                raise ValueError(f"{field_name} must be normalized to GMT")
        if self.gmt_modified < self.gmt_create:
            raise ValueError("gmt_modified must not precede gmt_create")
        return self


class DeploymentReceipt(_ImmutableModel):
    content: DeploymentReceiptContent
    content_digest: Sha256Digest

    @model_validator(mode="after")
    def require_matching_content_digest(self) -> Self:
        if self.content_digest != deployment_receipt_content_digest(self.content):
            raise ValueError("deployment receipt content digest mismatch")
        return self


type ProviderCapCoverage = Literal["fixed_infrastructure", "inference"]

_CAPABILITY_SEAL = object()


@dataclass(frozen=True, slots=True, init=False)
class VerifiedPricingCapability:
    """Opaque result of trusted pricing-evidence verification.

    The production issuer is intentionally deferred to O7/T6.  Task 4 accepts only
    this sealed result and exposes a private deterministic issuer solely for tests.
    """

    evidence_digest: str
    approval_digest: str
    provider: str
    currency: str
    workspace_ref: str
    project_ref: str
    credential_ref: str
    region: str
    base_model: str
    request_plan: str
    receipt_plan: str
    input_tpm_quota: int
    output_tpm_quota: int
    fixed_cost_minor_units: int
    fixed_segment_costs_minor_units: tuple[int, ...]
    input_cost_per_million_minor_units: int
    output_cost_per_million_minor_units: int
    effective_from: datetime
    effective_until: datetime
    _seal: object


@dataclass(frozen=True, slots=True, init=False)
class VerifiedProviderCapCapability:
    """Opaque result of trusted provider-cap attestation verification."""

    evidence_digest: str
    approval_digest: str
    provider: str
    currency: str
    workspace_ref: str
    project_ref: str
    credential_ref: str
    coverage: frozenset[ProviderCapCoverage]
    max_cost_minor_units: int
    expires_at: datetime
    _seal: object


@dataclass(frozen=True, slots=True, init=False)
class VerifiedReconciledDeploymentReceipt:
    """Opaque receipt proven equal to an independently observed remote manifest."""

    receipt: DeploymentReceipt
    reconciliation_digest: str
    _seal: object


class _PricingCapabilityFacts(_ImmutableModel):
    evidence_digest: Sha256Digest
    approval_digest: Sha256Digest
    provider: Literal["bailian"]
    currency: Literal["CNY"]
    workspace_ref: NonBlankStr
    project_ref: DigestRef
    credential_ref: DigestRef
    region: NonBlankStr
    base_model: NonBlankStr
    request_plan: Literal["ptu_v2"]
    receipt_plan: Literal["ptu"]
    input_tpm_quota: Literal[10_000]
    output_tpm_quota: Literal[1_000]
    fixed_cost_minor_units: PositiveCost
    fixed_segment_costs_minor_units: tuple[PositiveCost, ...] = ()
    input_cost_per_million_minor_units: NonNegativeCost = 0
    output_cost_per_million_minor_units: NonNegativeCost = 0
    effective_from: datetime = datetime(1970, 1, 1, tzinfo=UTC)
    effective_until: datetime = datetime(9999, 12, 31, tzinfo=UTC)


class _ProviderCapCapabilityFacts(_ImmutableModel):
    evidence_digest: Sha256Digest
    approval_digest: Sha256Digest
    provider: Literal["bailian"]
    currency: Literal["CNY"]
    workspace_ref: NonBlankStr
    project_ref: DigestRef
    credential_ref: DigestRef
    coverage: frozenset[ProviderCapCoverage]
    max_cost_minor_units: PositiveCost
    expires_at: datetime

    @model_validator(mode="after")
    def require_complete_coverage_and_expiry(self) -> Self:
        if self.coverage != frozenset({"fixed_infrastructure", "inference"}):
            raise ValueError("provider cap must cover fixed infrastructure and inference")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("provider cap expiry must include a timezone")
        return self


def _issue_verified_pricing_capability_for_testing(
    **values: object,
) -> VerifiedPricingCapability:
    """Private test seam until O7 installs the trusted signed-evidence verifier."""

    facts = _PricingCapabilityFacts.model_validate(values)
    capability = object.__new__(VerifiedPricingCapability)
    for name, value in facts.model_dump(mode="python").items():
        object.__setattr__(capability, name, value)
    object.__setattr__(capability, "_seal", _CAPABILITY_SEAL)
    return capability


def _issue_verified_provider_capability_for_testing(
    **values: object,
) -> VerifiedProviderCapCapability:
    """Private test seam until O7 installs the trusted signed-cap verifier."""

    facts = _ProviderCapCapabilityFacts.model_validate(values)
    capability = object.__new__(VerifiedProviderCapCapability)
    for name, value in facts.model_dump(mode="python").items():
        object.__setattr__(capability, name, value)
    object.__setattr__(capability, "_seal", _CAPABILITY_SEAL)
    return capability


def require_verified_pricing_capability(
    capability: object,
) -> VerifiedPricingCapability:
    if (
        not isinstance(capability, VerifiedPricingCapability)
        or capability._seal is not _CAPABILITY_SEAL
    ):
        raise AuthorizationVerificationError("verified pricing capability is required")
    return capability


def require_verified_provider_capability(
    capability: object,
) -> VerifiedProviderCapCapability:
    if (
        not isinstance(capability, VerifiedProviderCapCapability)
        or capability._seal is not _CAPABILITY_SEAL
    ):
        raise AuthorizationVerificationError("verified provider cap capability is required")
    return capability


def require_verified_reconciled_receipt(
    capability: object,
) -> VerifiedReconciledDeploymentReceipt:
    if (
        not isinstance(capability, VerifiedReconciledDeploymentReceipt)
        or capability._seal is not _CAPABILITY_SEAL
    ):
        raise AuthorizationVerificationError("verified reconciled receipt is required")
    return capability


def verify_reconciled_deployment_receipt(
    receipt: DeploymentReceipt,
    *,
    remote_expected: DeploymentReceipt,
) -> VerifiedReconciledDeploymentReceipt:
    """Compare local receipt to a separately materialized remote observation."""

    if receipt is remote_expected:
        raise AuthorizationVerificationError(
            "remote expected receipt must be an independent observation"
        )
    verify_deployment_receipt(receipt, expected=remote_expected)
    capability = object.__new__(VerifiedReconciledDeploymentReceipt)
    object.__setattr__(capability, "receipt", receipt)
    object.__setattr__(
        capability,
        "reconciliation_digest",
        hashlib.sha256(
            b"insurancekb.run-admission.receipt-reconciliation.v1\0"
            + canonical_json_bytes(remote_expected)
        ).hexdigest(),
    )
    object.__setattr__(capability, "_seal", _CAPABILITY_SEAL)
    return capability


def authorization_signed_bytes(
    domain: AuthorizationDomain,
    payload: InfrastructureAuthorizationPayload,
) -> bytes:
    """Return the canonical bytes for exactly one versioned authorization domain."""

    if domain == PROVISIONING_AUTHORIZATION_DOMAIN:
        if not isinstance(payload, ProvisioningAuthorizationPayload):
            raise TypeError("provisioning domain requires a provisioning payload")
        prefix = _PROVISIONING_SIGNING_PREFIX
    elif domain == ADOPTION_AUTHORIZATION_DOMAIN:
        if not isinstance(payload, ExistingDeploymentAdoptionAuthorizationPayload):
            raise TypeError("adoption domain requires an adoption payload")
        prefix = _ADOPTION_SIGNING_PREFIX
    else:  # pragma: no cover - static typing plus runtime fail-closed guard
        raise ValueError("unknown infrastructure authorization domain")
    return prefix + canonical_json_bytes(payload)


def infrastructure_authorization_digest(
    envelope: InfrastructureAuthorization,
) -> str:
    return hashlib.sha256(
        _AUTHORIZATION_DIGEST_DOMAIN + canonical_json_bytes(envelope)
    ).hexdigest()


def deployment_receipt_content_digest(content: DeploymentReceiptContent) -> str:
    return hashlib.sha256(_RECEIPT_DIGEST_DOMAIN + canonical_json_bytes(content)).hexdigest()


def _verify_authorization(
    envelope: InfrastructureAuthorization,
    *,
    expected: InfrastructureAuthorizationPayload,
    expected_domain: AuthorizationDomain,
    expected_role: str,
    trusted_authorities: Mapping[str, TrustedAuthority],
    now: datetime,
) -> str:
    try:
        if isinstance(envelope, ProvisioningAuthorization):
            validated: InfrastructureAuthorization = ProvisioningAuthorization.model_validate(
                envelope.model_dump(mode="python", round_trip=True)
            )
        elif isinstance(envelope, ExistingDeploymentAdoptionAuthorization):
            validated = ExistingDeploymentAdoptionAuthorization.model_validate(
                envelope.model_dump(mode="python", round_trip=True)
            )
        else:
            raise AuthorizationVerificationError("authorization type is invalid")
    except (TypeError, ValueError) as exc:
        raise AuthorizationVerificationError("authorization structure is invalid") from exc

    if validated.domain != expected_domain:
        raise AuthorizationVerificationError("authorization domain mismatch")
    if type(validated.payload) is not type(expected) or canonical_json_bytes(
        validated.payload
    ) != canonical_json_bytes(expected):
        raise AuthorizationVerificationError("authorization does not match exact expected values")
    payload = validated.payload
    if payload.approver_role != expected_role:
        raise AuthorizationVerificationError("authorization role mismatch")
    for field_name, timestamp in (
        ("issued_at", payload.issued_at),
        ("expires_at", payload.expires_at),
        ("now", now),
    ):
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise AuthorizationVerificationError(f"{field_name} must include a timezone")
    if now < payload.issued_at or now >= payload.expires_at:
        raise AuthorizationVerificationError("authorization is outside its validity window")
    if now >= payload.cleanup_deadline:
        raise AuthorizationVerificationError("authorization cleanup deadline has elapsed")
    if now >= payload.provider_cap_expires_at:
        raise AuthorizationVerificationError("authorization provider cap has expired")

    authority = trusted_authorities.get(validated.key_id)
    if not isinstance(authority, TrustedKeyPolicy):
        raise AuthorizationVerificationError("authorization requires a trusted key policy")
    if (
        authority.key_id != validated.key_id
        or authority.approver_identity != payload.approver_identity
        or expected_domain not in authority.domains
        or payload.scope not in authority.scopes
        or expected_role not in authority.roles
    ):
        raise AuthorizationVerificationError("authorization violates trusted key policy")
    public_key = authority.public_key
    if not isinstance(public_key, Ed25519PublicKey):
        raise AuthorizationVerificationError("authorization policy key type is invalid")
    try:
        signature = base64.b64decode(validated.signature, validate=True)
        if base64.b64encode(signature).decode("ascii") != validated.signature:
            raise AuthorizationVerificationError("authorization signature is noncanonical")
        public_key.verify(
            signature,
            authorization_signed_bytes(expected_domain, payload),
        )
    except AuthorizationVerificationError:
        raise
    except (binascii.Error, InvalidSignature, TypeError, ValueError) as exc:
        raise AuthorizationVerificationError("authorization signature is invalid") from exc
    return infrastructure_authorization_digest(validated)


def verify_provisioning_authorization(
    envelope: ProvisioningAuthorization,
    *,
    expected: ProvisioningAuthorizationPayload,
    trusted_authorities: Mapping[str, TrustedAuthority],
    now: datetime,
) -> str:
    return _verify_authorization(
        envelope,
        expected=expected,
        expected_domain=PROVISIONING_AUTHORIZATION_DOMAIN,
        expected_role="deployment-provisioner",
        trusted_authorities=trusted_authorities,
        now=now,
    )


def verify_adoption_authorization(
    envelope: ExistingDeploymentAdoptionAuthorization,
    *,
    expected: ExistingDeploymentAdoptionAuthorizationPayload,
    trusted_authorities: Mapping[str, TrustedAuthority],
    now: datetime,
) -> str:
    return _verify_authorization(
        envelope,
        expected=expected,
        expected_domain=ADOPTION_AUTHORIZATION_DOMAIN,
        expected_role="budget-approver",
        trusted_authorities=trusted_authorities,
        now=now,
    )


def verify_deployment_receipt(
    receipt: DeploymentReceipt,
    *,
    expected: DeploymentReceipt,
) -> str:
    """Revalidate construction and compare every normalized receipt byte exactly."""

    try:
        validated = DeploymentReceipt.model_validate(
            receipt.model_dump(mode="python", round_trip=True)
        )
        validated_expected = DeploymentReceipt.model_validate(
            expected.model_dump(mode="python", round_trip=True)
        )
    except (TypeError, ValueError) as exc:
        raise AuthorizationVerificationError(
            "deployment receipt content digest is invalid"
        ) from exc
    if validated.content_digest != deployment_receipt_content_digest(validated.content):
        raise AuthorizationVerificationError("deployment receipt content digest is invalid")
    if canonical_json_bytes(validated) != canonical_json_bytes(validated_expected):
        raise AuthorizationVerificationError(
            "deployment receipt does not match exact expected values"
        )
    return validated.content_digest


def pricing_evidence_digest(evidence_bytes: bytes) -> str:
    if (
        not isinstance(evidence_bytes, bytes)
        or not evidence_bytes
        or len(evidence_bytes) > _MAX_AUTHORITY_EVIDENCE_BYTES
    ):
        raise AuthorizationVerificationError("pricing evidence size is invalid")
    return hashlib.sha256(
        _PRICING_EVIDENCE_DIGEST_DOMAIN + evidence_bytes
    ).hexdigest()


def provider_cap_evidence_digest(evidence_bytes: bytes) -> str:
    if (
        not isinstance(evidence_bytes, bytes)
        or not evidence_bytes
        or len(evidence_bytes) > _MAX_AUTHORITY_EVIDENCE_BYTES
    ):
        raise AuthorizationVerificationError("provider cap evidence size is invalid")
    return hashlib.sha256(_CAP_EVIDENCE_DIGEST_DOMAIN + evidence_bytes).hexdigest()


def pricing_evidence_signed_bytes(payload: PricingEvidenceApprovalPayload) -> bytes:
    return _PRICING_SIGNING_PREFIX + canonical_json_bytes(payload)


def provider_cap_signed_bytes(payload: ProviderCapApprovalPayload) -> bytes:
    return _PROVIDER_CAP_SIGNING_PREFIX + canonical_json_bytes(payload)


def pricing_approval_digest(envelope: PricingEvidenceApproval) -> str:
    return hashlib.sha256(
        _PRICING_APPROVAL_DIGEST_DOMAIN + canonical_json_bytes(envelope)
    ).hexdigest()


def provider_cap_approval_digest(envelope: ProviderCapApproval) -> str:
    return hashlib.sha256(
        _CAP_APPROVAL_DIGEST_DOMAIN + canonical_json_bytes(envelope)
    ).hexdigest()


def cleanup_authorization_signed_bytes(
    payload: DeploymentCleanupAuthorizationPayload,
) -> bytes:
    return _CLEANUP_SIGNING_PREFIX + canonical_json_bytes(payload)


def cleanup_authorization_digest(
    envelope: DeploymentCleanupAuthorization,
) -> str:
    return hashlib.sha256(
        _CLEANUP_AUTHORIZATION_DIGEST_DOMAIN + canonical_json_bytes(envelope)
    ).hexdigest()


def verify_cleanup_authorization(
    envelope: DeploymentCleanupAuthorization,
    *,
    trusted_authorities: Mapping[str, TrustedAuthority],
    now: datetime,
) -> str:
    """Verify the independent cleanup authority; resource binding is checked by controller."""

    try:
        validated = DeploymentCleanupAuthorization.model_validate(
            envelope.model_dump(mode="python", round_trip=True)
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise AuthorizationVerificationError("cleanup authorization is invalid") from exc
    if validated.domain != CLEANUP_AUTHORIZATION_DOMAIN:
        raise AuthorizationVerificationError("cleanup authorization domain mismatch")
    _require_now_in_window(
        now=now,
        issued_at=validated.payload.issued_at,
        expires_at=validated.payload.expires_at,
        label="cleanup authorization",
    )
    if now >= validated.payload.cleanup_deadline:
        raise AuthorizationVerificationError("cleanup deadline has elapsed")
    _verify_evidence_policy(
        key_id=validated.key_id,
        identity=validated.payload.approver_identity,
        domain=validated.domain,
        scope=validated.payload.scope,
        role=validated.payload.approver_role,
        signature=validated.signature,
        signed_bytes=cleanup_authorization_signed_bytes(validated.payload),
        trusted_authorities=trusted_authorities,
    )
    return cleanup_authorization_digest(validated)


def _parse_canonical_evidence(
    evidence_bytes: bytes,
    *,
    model_type: type[PricingEvidenceContent] | type[ProviderCapEvidenceContent],
) -> PricingEvidenceContent | ProviderCapEvidenceContent:
    if not isinstance(evidence_bytes, bytes) or not evidence_bytes:
        raise AuthorizationVerificationError("authoritative evidence bytes are required")
    if len(evidence_bytes) > _MAX_AUTHORITY_EVIDENCE_BYTES:
        raise AuthorizationVerificationError("authoritative evidence is oversized")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    try:
        raw = json.loads(
            evidence_bytes.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
        )
        parsed = model_type.model_validate(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise AuthorizationVerificationError(
            "authoritative evidence structure is invalid"
        ) from exc
    if canonical_json_bytes(parsed) != evidence_bytes:
        raise AuthorizationVerificationError("authoritative evidence is not canonical")
    return parsed


def _verify_evidence_policy(
    *,
    key_id: str,
    identity: str,
    domain: str,
    scope: str,
    role: str,
    signature: str,
    signed_bytes: bytes,
    trusted_authorities: Mapping[str, TrustedAuthority],
) -> None:
    authority = trusted_authorities.get(key_id)
    if not isinstance(authority, TrustedKeyPolicy):
        raise AuthorizationVerificationError("evidence requires a trusted key policy")
    if (
        authority.key_id != key_id
        or authority.approver_identity != identity
        or domain not in authority.domains
        or scope not in authority.scopes
        or role not in authority.roles
    ):
        raise AuthorizationVerificationError("evidence violates trusted key policy")
    try:
        signature_bytes = base64.b64decode(signature, validate=True)
        if base64.b64encode(signature_bytes).decode("ascii") != signature:
            raise AuthorizationVerificationError("evidence signature is noncanonical")
        authority.public_key.verify(signature_bytes, signed_bytes)
    except AuthorizationVerificationError:
        raise
    except (binascii.Error, InvalidSignature, TypeError, ValueError) as exc:
        raise AuthorizationVerificationError("evidence signature is invalid") from exc


def _require_now_in_window(
    *, now: datetime, issued_at: datetime, expires_at: datetime, label: str
) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise AuthorizationVerificationError("verification time must include a timezone")
    if now < issued_at or now >= expires_at:
        raise AuthorizationVerificationError(f"{label} is outside its validity window")


def _checked_pricing_product(left: int, right: int) -> int:
    if left <= 0 or right <= 0 or left > (2**63 - 1) // right:
        raise ValueError("pricing multiplication exceeds signed ledger range")
    return left * right


def _checked_pricing_sum(values: tuple[int, ...]) -> int:
    total = 0
    for value in values:
        if value <= 0 or total > (2**63 - 1) - value:
            raise ValueError("pricing sum exceeds signed ledger range")
        total += value
    return total


def verify_pricing_evidence(
    evidence_bytes: bytes,
    *,
    envelope: PricingEvidenceApproval,
    trusted_authorities: Mapping[str, TrustedAuthority],
    expected_scope: str,
    now: datetime,
    fixed_duration_seconds: int,
    cost_window_start: datetime | None = None,
    fixed_duration_segments_seconds: tuple[int, ...] | None = None,
) -> VerifiedPricingCapability:
    """Verify signed canonical pricing and derive conservative fixed/inference rates."""

    try:
        validated = PricingEvidenceApproval.model_validate(
            envelope.model_dump(mode="python", round_trip=True)
        )
    except (TypeError, ValueError) as exc:
        raise AuthorizationVerificationError("pricing approval is invalid") from exc
    if type(fixed_duration_seconds) is not int or fixed_duration_seconds <= 0:
        raise AuthorizationVerificationError("fixed pricing duration is invalid")
    segments = fixed_duration_segments_seconds or (fixed_duration_seconds,)
    if (
        not segments
        or any(type(item) is not int or item <= 0 for item in segments)
        or sum(segments) != fixed_duration_seconds
    ):
        raise AuthorizationVerificationError("fixed pricing segments are invalid")
    if validated.domain != PRICING_EVIDENCE_DOMAIN:
        raise AuthorizationVerificationError("pricing domain mismatch")
    if validated.payload.scope != expected_scope:
        raise AuthorizationVerificationError("pricing scope mismatch")
    _require_now_in_window(
        now=now,
        issued_at=validated.payload.issued_at,
        expires_at=validated.payload.expires_at,
        label="pricing approval",
    )
    _verify_evidence_policy(
        key_id=validated.key_id,
        identity=validated.payload.approver_identity,
        domain=validated.domain,
        scope=validated.payload.scope,
        role=validated.payload.approver_role,
        signature=validated.signature,
        signed_bytes=pricing_evidence_signed_bytes(validated.payload),
        trusted_authorities=trusted_authorities,
    )
    parsed = _parse_canonical_evidence(
        evidence_bytes, model_type=PricingEvidenceContent
    )
    if not isinstance(parsed, PricingEvidenceContent):  # pragma: no cover
        raise AuthorizationVerificationError("pricing evidence type mismatch")
    digest = pricing_evidence_digest(evidence_bytes)
    if (
        validated.payload.evidence_digest != digest
        or canonical_json_bytes(validated.payload.evidence) != evidence_bytes
        or parsed.issuer != "aliyun-bailian-price-catalog"
    ):
        raise AuthorizationVerificationError("pricing evidence does not match approval")
    start = now if cost_window_start is None else cost_window_start
    if start.tzinfo is None or start.utcoffset() is None:
        raise AuthorizationVerificationError("pricing cost-window start must be aware")
    try:
        quantum_us = parsed.billing_quantum_seconds * 1_000_000
        segment_costs = tuple(
            _checked_pricing_product(
                (duration * 1_000_000 + quantum_us - 1) // quantum_us,
                parsed.fixed_cost_per_quantum_minor_units,
            )
            for duration in segments
        )
        fixed_cost = _checked_pricing_sum(segment_costs)
        cost_end = start + timedelta(seconds=fixed_duration_seconds)
    except (OverflowError, ValueError) as exc:
        raise AuthorizationVerificationError("pricing arithmetic overflow") from exc
    if parsed.effective_from > start or parsed.effective_until < cost_end:
        raise AuthorizationVerificationError("pricing evidence does not cover cost window")
    facts = _PricingCapabilityFacts(
        evidence_digest=digest,
        approval_digest=pricing_approval_digest(validated),
        provider=parsed.provider,
        currency=parsed.currency,
        workspace_ref=parsed.workspace_ref,
        project_ref=parsed.project_ref,
        credential_ref=parsed.credential_ref,
        region=parsed.region,
        base_model=parsed.base_model,
        request_plan=parsed.request_plan,
        receipt_plan=parsed.receipt_plan,
        input_tpm_quota=parsed.input_tpm_quota,
        output_tpm_quota=parsed.output_tpm_quota,
        fixed_cost_minor_units=fixed_cost,
        fixed_segment_costs_minor_units=segment_costs,
        input_cost_per_million_minor_units=parsed.input_cost_per_million_minor_units,
        output_cost_per_million_minor_units=parsed.output_cost_per_million_minor_units,
        effective_from=parsed.effective_from,
        effective_until=parsed.effective_until,
    )
    capability = object.__new__(VerifiedPricingCapability)
    for name, value in facts.model_dump(mode="python").items():
        object.__setattr__(capability, name, value)
    object.__setattr__(capability, "_seal", _CAPABILITY_SEAL)
    return capability


def verify_provider_cap_evidence(
    evidence_bytes: bytes,
    *,
    envelope: ProviderCapApproval,
    trusted_authorities: Mapping[str, TrustedAuthority],
    expected_scope: str,
    now: datetime,
) -> VerifiedProviderCapCapability:
    """Verify a signed provider hard cap covering fixed and inference spend."""

    try:
        validated = ProviderCapApproval.model_validate(
            envelope.model_dump(mode="python", round_trip=True)
        )
    except (TypeError, ValueError) as exc:
        raise AuthorizationVerificationError("provider cap approval is invalid") from exc
    if validated.domain != PROVIDER_CAP_DOMAIN:
        raise AuthorizationVerificationError("provider cap domain mismatch")
    if validated.payload.scope != expected_scope:
        raise AuthorizationVerificationError("provider cap scope mismatch")
    _require_now_in_window(
        now=now,
        issued_at=validated.payload.issued_at,
        expires_at=validated.payload.expires_at,
        label="provider cap approval",
    )
    _verify_evidence_policy(
        key_id=validated.key_id,
        identity=validated.payload.approver_identity,
        domain=validated.domain,
        scope=validated.payload.scope,
        role=validated.payload.approver_role,
        signature=validated.signature,
        signed_bytes=provider_cap_signed_bytes(validated.payload),
        trusted_authorities=trusted_authorities,
    )
    parsed = _parse_canonical_evidence(
        evidence_bytes, model_type=ProviderCapEvidenceContent
    )
    if not isinstance(parsed, ProviderCapEvidenceContent):  # pragma: no cover
        raise AuthorizationVerificationError("provider cap evidence type mismatch")
    digest = provider_cap_evidence_digest(evidence_bytes)
    if (
        validated.payload.evidence_digest != digest
        or canonical_json_bytes(validated.payload.evidence) != evidence_bytes
        or parsed.issuer != "aliyun-bailian-spend-cap"
    ):
        raise AuthorizationVerificationError("provider cap evidence does not match approval")
    if now < parsed.observed_at or now >= parsed.expires_at:
        raise AuthorizationVerificationError("provider cap evidence is stale")
    facts = _ProviderCapCapabilityFacts(
        evidence_digest=digest,
        approval_digest=provider_cap_approval_digest(validated),
        provider=parsed.provider,
        currency=parsed.currency,
        workspace_ref=parsed.workspace_ref,
        project_ref=parsed.project_ref,
        credential_ref=parsed.credential_ref,
        coverage=frozenset(parsed.coverage),
        max_cost_minor_units=parsed.max_cost_minor_units,
        expires_at=parsed.expires_at,
    )
    capability = object.__new__(VerifiedProviderCapCapability)
    for name, value in facts.model_dump(mode="python").items():
        object.__setattr__(capability, name, value)
    object.__setattr__(capability, "_seal", _CAPABILITY_SEAL)
    return capability


__all__ = [
    "ADOPTION_AUTHORIZATION_DOMAIN",
    "PROVISIONING_AUTHORIZATION_DOMAIN",
    "PRICING_EVIDENCE_DOMAIN",
    "PROVIDER_CAP_DOMAIN",
    "CLEANUP_AUTHORIZATION_DOMAIN",
    "AuthorizationDomain",
    "AuthorizationVerificationError",
    "DeploymentReceipt",
    "DeploymentReceiptContent",
    "DeploymentCleanupAuthorization",
    "DeploymentCleanupAuthorizationPayload",
    "ExistingDeploymentAdoptionAuthorization",
    "ExistingDeploymentAdoptionAuthorizationPayload",
    "InfrastructureAuthorization",
    "InfrastructureAuthorizationPayload",
    "ProvisioningAuthorization",
    "ProvisioningAuthorizationPayload",
    "PricingEvidenceApproval",
    "PricingEvidenceApprovalPayload",
    "PricingEvidenceContent",
    "ProviderCapApproval",
    "ProviderCapApprovalPayload",
    "ProviderCapEvidenceContent",
    "ProviderCapCoverage",
    "VerifiedPricingCapability",
    "VerifiedProviderCapCapability",
    "VerifiedReconciledDeploymentReceipt",
    "authorization_signed_bytes",
    "deployment_receipt_content_digest",
    "infrastructure_authorization_digest",
    "cleanup_authorization_digest",
    "cleanup_authorization_signed_bytes",
    "pricing_approval_digest",
    "pricing_evidence_digest",
    "pricing_evidence_signed_bytes",
    "provider_cap_approval_digest",
    "provider_cap_evidence_digest",
    "provider_cap_signed_bytes",
    "require_verified_pricing_capability",
    "require_verified_provider_capability",
    "require_verified_reconciled_receipt",
    "verify_adoption_authorization",
    "verify_deployment_receipt",
    "verify_provisioning_authorization",
    "verify_pricing_evidence",
    "verify_provider_cap_evidence",
    "verify_reconciled_deployment_receipt",
    "verify_cleanup_authorization",
]
