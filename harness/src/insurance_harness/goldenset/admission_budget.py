"""Durable, signed run-budget lineage and exactly-once send ownership."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_serializer,
    model_validator,
)

from insurance_harness.goldenset.admission_infrastructure import (
    PROVISIONING_AUTHORIZATION_DOMAIN,
    AuthorizationDomain,
    AuthorizationVerificationError,
    DeploymentReceipt,
    InfrastructureAuthorization,
    PricingEvidenceApproval,
    ProviderCapApproval,
    ProvisioningAuthorization,
    ProvisioningAuthorizationPayload,
    VerifiedPricingCapability,
    VerifiedProviderCapCapability,
    VerifiedReconciledDeploymentReceipt,
    _IssuerSnapshotRegistry,
    _require_verified_pricing_capability_for_testing,
    _require_verified_provider_capability_for_testing,
    _require_verified_reconciled_receipt_for_testing,
    infrastructure_authorization_digest,
    require_verified_pricing_capability,
    require_verified_provider_capability,
    require_verified_reconciled_receipt,
    verify_pricing_evidence,
    verify_provider_cap_evidence,
    verify_provisioning_authorization,
)
from insurance_harness.goldenset.admission_models import (
    ApprovalVerificationError,
    BudgetApprovalEnvelope,
    ModelRolePlan,
    RunAdmissionPlanPayload,
    TrustedAuthority,
    canonical_json_bytes,
    plan_payload_hash,
    verify_approval_envelope,
)

SQLITE_SAFE_INTEGER_MAX = 2**63 - 1

type NonNegativeInt = Annotated[StrictInt, Field(ge=0, le=SQLITE_SAFE_INTEGER_MAX)]
type NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
type Sha256Digest = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
type DigestRef = Annotated[StrictStr, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
type AttemptState = Literal["prepared", "sent", "terminal", "uncertain", "no_usage"]
type BudgetRole = Literal["annotator", "weak_extractor", "judge"]

_REQUIRED_ROLES = frozenset({"annotator", "weak_extractor", "judge"})
_ACCOUNT_DOMAIN = b"insurancekb.run-admission.budget-account.v1\0"
_CONTRACT_DOMAIN = b"insurancekb.run-admission.budget-contract.v1\0"
_APPROVAL_DIGEST_DOMAIN = b"insurancekb.run-admission.budget-approval-digest.v1\0"
_OWNER_TOKEN_DOMAIN = b"insurancekb.run-admission.attempt-owner.v1\0"
_MODEL_ROLE_DOMAIN = b"insurancekb.run-admission.budget-model-role.v1\0"
_ROLE_RATE_DOMAIN = b"insurancekb.run-admission.budget-role-rate.v1\0"
_SETTLEMENT_SNAPSHOT_DOMAIN = b"insurancekb.run-admission.product-settlement-snapshot.v1\0"
_FINAL_TOPOLOGY_DOMAIN = b"insurancekb.run-admission.final-topology.v1\0"
_RECEIPT_JSON_DOMAIN = b"insurancekb.run-admission.receipt-json.v1\0"
_RECEIPT_ANNEX_DOMAIN = b"insurancekb.run-admission.receipt-annex.v1\0"
_TRANSPORT_IDENTITY_DIGEST_DOMAIN = b"insurancekb.run-admission.transport-identity.v1\0"
_BAILIAN_DEPLOYMENT_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/deployments"
_TRUSTED_RECONCILIATION_ISSUER = "bailian-deployment-controller-v1"
_FINAL_TOPOLOGY_SEAL = object()
_INFRASTRUCTURE_PROVIDER_CAPABILITY_SEAL = object()
_TOPOLOGY_PROVIDER_CAPABILITY_SEAL = object()
_LEDGER_CAPABILITY_SNAPSHOT_REGISTRY = _IssuerSnapshotRegistry()
_INFRASTRUCTURE_CAP_SNAPSHOT_DOMAIN = b"insurancekb.infrastructure-capability-snapshot.v1\0"
_TOPOLOGY_CAP_SNAPSHOT_DOMAIN = b"insurancekb.topology-capability-snapshot.v1\0"
_FINAL_TOPOLOGY_SNAPSHOT_DOMAIN = b"insurancekb.final-topology-snapshot.v1\0"
_PRODUCTION_DEPLOYMENT_OPERATION_ROOT = Path("/var/lib/insurancekb/run-admission/deployments")
_BUSY_TIMEOUT_MS = 30_000
_TESTING_MODE_SENTINEL = object()
_SCHEMA_VERSION = 8
_PRE_PROVIDER_CAP_SIDECAR_SCHEMA_VERSION = 7
_PRE_RECEIPT_ANNEX_SCHEMA_VERSION = 6
_PRE_FINAL_TOPOLOGY_SCHEMA_VERSION = 5
_PRE_INFRASTRUCTURE_SCHEMA_VERSION = 4
_PRE_CANARY_SCHEMA_VERSION = 3
_PRE_USAGE_SCHEMA_VERSION = 2
_PRE_POOL_SCHEMA_VERSION = 1


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _ceil_timedelta_seconds(value: Any) -> int:
    """Return positive whole seconds without floating-point conversion."""

    if (
        not hasattr(value, "days")
        or not hasattr(value, "seconds")
        or not hasattr(value, "microseconds")
    ):
        raise BudgetLedgerError("pricing duration is invalid")
    total_microseconds = (
        int(value.days) * 86_400_000_000 + int(value.seconds) * 1_000_000 + int(value.microseconds)
    )
    if total_microseconds <= 0:
        raise BudgetLedgerError("pricing duration must be positive")
    return (total_microseconds + 999_999) // 1_000_000


def _transport_identity_digest_for_provider_cap(
    capability: VerifiedProviderCapCapability,
) -> str:
    """Mechanically bind transport identity to signed cap resource facts."""

    values: dict[str, object] = {
        "provider": capability.provider,
        "endpoint": _BAILIAN_DEPLOYMENT_ENDPOINT,
        "workspace_ref": capability.workspace_ref,
        "project_ref": capability.project_ref,
        "credential_ref": capability.credential_ref,
        "currency": capability.currency,
        "provider_cap_evidence_digest": capability.evidence_digest,
        "provider_cap_approval_digest": capability.approval_digest,
        "topology_digest": None,
        "coverage": tuple(sorted(capability.coverage)),
        "credential_fingerprint": capability.credential_ref.removeprefix("sha256:"),
        "expires_at": capability.expires_at,
    }
    return hashlib.sha256(
        _TRANSPORT_IDENTITY_DIGEST_DOMAIN + canonical_json_bytes(values)
    ).hexdigest()


_PRE_POOL_ATTEMPT_COLUMNS = frozenset(
    {
        "account_id",
        "stage",
        "product_id",
        "request_unit",
        "attempt_no",
        "owner_token_digest",
        "state",
        "max_input",
        "max_output",
        "max_cost",
        "actual_input",
        "actual_output",
        "actual_cost",
        "charged_input",
        "charged_output",
        "charged_cost",
        "response_digest",
        "provider_proof_digest",
        "provider_request_id",
        "provider_verifier_policy",
        "provider_proof_observed_at",
    }
)
_PRE_USAGE_ATTEMPT_COLUMNS = _PRE_POOL_ATTEMPT_COLUMNS | {"role", "limit_kind"}
_CURRENT_ATTEMPT_COLUMNS = _PRE_USAGE_ATTEMPT_COLUMNS | {"usage_verified"}
_PRE_BINDING_POOL_COLUMNS = frozenset(
    {
        "account_id",
        "stage",
        "product_id",
        "role",
        "max_attempts",
        "max_input",
        "max_output",
        "max_cost",
    }
)
_CURRENT_POOL_COLUMNS = _PRE_BINDING_POOL_COLUMNS | {
    "model_role_identity_hash",
    "role_rate_digest",
}
_CANARY_CLAIM_COLUMNS = frozenset(
    {
        "account_id",
        "capability_digest",
        "canary_stage",
        "canary_product_id",
        "settlement_digest",
        "budget_revision",
        "approval_digest",
        "target_stage",
        "target_product_id",
        "target_max_input",
        "target_max_output",
        "target_max_cost",
    }
)
_CANARY_CLAIM_TABLE_SQL = """CREATE TABLE canary_capability_claims (
    account_id TEXT NOT NULL REFERENCES budget_accounts(account_id),
    capability_digest TEXT NOT NULL,
    canary_stage TEXT NOT NULL,
    canary_product_id TEXT NOT NULL,
    settlement_digest TEXT NOT NULL,
    budget_revision INTEGER NOT NULL CHECK (budget_revision >= 1),
    approval_digest TEXT NOT NULL,
    target_stage TEXT NOT NULL,
    target_product_id TEXT NOT NULL,
    target_max_input INTEGER NOT NULL CHECK (target_max_input >= 0),
    target_max_output INTEGER NOT NULL CHECK (target_max_output >= 0),
    target_max_cost INTEGER NOT NULL CHECK (target_max_cost >= 0),
    PRIMARY KEY (
        account_id, capability_digest, target_stage, target_product_id
    ),
    FOREIGN KEY (account_id, canary_stage, canary_product_id)
        REFERENCES product_limits(account_id, stage, product_id),
    FOREIGN KEY (account_id, target_stage, target_product_id)
        REFERENCES product_limits(account_id, stage, product_id)
)"""
_INFRASTRUCTURE_AUTHORIZATION_COLUMNS = frozenset(
    {
        "authorization_digest",
        "domain",
        "envelope_json",
        "run_identity",
        "purpose",
        "operation_id",
        "reserve_id",
        "recorded_at",
    }
)
_INFRASTRUCTURE_RESERVE_COLUMNS = frozenset(
    {
        "reserve_id",
        "account_id",
        "run_identity",
        "purpose",
        "operation_id",
        "authorization_digest",
        "pricing_evidence_digest",
        "pricing_approval_digest",
        "provider_cap_evidence_digest",
        "provider_cap_approval_digest",
        "provider_cap_max_cost",
        "provider_cap_expires_at",
        "provider",
        "currency",
        "workspace_ref",
        "project_ref",
        "credential_ref",
        "region",
        "base_model",
        "request_plan",
        "receipt_plan",
        "input_tpm_quota",
        "output_tpm_quota",
        "covers_fixed_infrastructure",
        "covers_inference",
        "cleanup_deadline",
        "max_cost",
        "state",
        "deployed_model",
        "receipt_digest",
        "remote_manifest_digest",
        "receipt_json",
        "final_approval_digest",
        "created_at",
        "bound_at",
    }
)
_DEPLOYMENT_ROLE_BINDING_COLUMNS = frozenset(
    {
        "account_id",
        "role",
        "reserve_id",
    }
)
_A_V5_INFRASTRUCTURE_RESERVE_COLUMNS = _INFRASTRUCTURE_RESERVE_COLUMNS - {
    "deployed_model",
    "receipt_digest",
    "remote_manifest_digest",
    "receipt_json",
    "final_approval_digest",
    "bound_at",
}
_A_V5_INFRASTRUCTURE_AUTHORIZATION_TABLE_SQL = """CREATE TABLE infrastructure_authorizations (
    authorization_digest TEXT PRIMARY KEY,
    domain TEXT NOT NULL CHECK (domain='insurancekb.run-admission.provisioning.v1'),
    envelope_json BLOB NOT NULL UNIQUE,
    run_identity TEXT NOT NULL,
    purpose TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    reserve_id TEXT NOT NULL UNIQUE,
    recorded_at TEXT NOT NULL,
    UNIQUE (run_identity, purpose, operation_id)
)"""
_A_V5_INFRASTRUCTURE_RESERVE_TABLE_SQL = """CREATE TABLE infrastructure_reserves (
    reserve_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    run_identity TEXT NOT NULL,
    purpose TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    authorization_digest TEXT NOT NULL UNIQUE
        REFERENCES infrastructure_authorizations(authorization_digest),
    pricing_evidence_digest TEXT NOT NULL,
    pricing_approval_digest TEXT NOT NULL,
    provider_cap_evidence_digest TEXT NOT NULL,
    provider_cap_approval_digest TEXT NOT NULL,
    provider_cap_max_cost INTEGER NOT NULL CHECK (provider_cap_max_cost > 0),
    provider_cap_expires_at TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider='bailian'),
    currency TEXT NOT NULL CHECK (currency='CNY'),
    workspace_ref TEXT NOT NULL,
    project_ref TEXT NOT NULL,
    credential_ref TEXT NOT NULL,
    region TEXT NOT NULL,
    base_model TEXT NOT NULL,
    request_plan TEXT NOT NULL CHECK (request_plan='ptu_v2'),
    receipt_plan TEXT NOT NULL CHECK (receipt_plan='ptu'),
    input_tpm_quota INTEGER NOT NULL CHECK (input_tpm_quota=10000),
    output_tpm_quota INTEGER NOT NULL CHECK (output_tpm_quota=1000),
    covers_fixed_infrastructure INTEGER NOT NULL CHECK (covers_fixed_infrastructure=1),
    covers_inference INTEGER NOT NULL CHECK (covers_inference=1),
    cleanup_deadline TEXT NOT NULL,
    max_cost INTEGER NOT NULL CHECK (max_cost > 0),
    state TEXT NOT NULL CHECK (state='reserved'),
    created_at TEXT NOT NULL,
    UNIQUE (account_id, operation_id)
)"""
_INFRASTRUCTURE_AUTHORIZATION_TABLE_SQL = """CREATE TABLE infrastructure_authorizations (
    authorization_digest TEXT PRIMARY KEY,
    domain TEXT NOT NULL CHECK (domain =
        'insurancekb.run-admission.provisioning.v1'
    ),
    envelope_json BLOB NOT NULL UNIQUE,
    run_identity TEXT NOT NULL,
    purpose TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    reserve_id TEXT NOT NULL UNIQUE,
    recorded_at TEXT NOT NULL,
    UNIQUE (run_identity, purpose, operation_id)
)"""
_INFRASTRUCTURE_RESERVE_TABLE_SQL = """CREATE TABLE infrastructure_reserves (
    reserve_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    run_identity TEXT NOT NULL,
    purpose TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    authorization_digest TEXT NOT NULL UNIQUE
        REFERENCES infrastructure_authorizations(authorization_digest),
    pricing_evidence_digest TEXT NOT NULL,
    pricing_approval_digest TEXT NOT NULL,
    provider_cap_evidence_digest TEXT NOT NULL,
    provider_cap_approval_digest TEXT NOT NULL,
    provider_cap_max_cost INTEGER NOT NULL CHECK (provider_cap_max_cost > 0),
    provider_cap_expires_at TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider='bailian'),
    currency TEXT NOT NULL CHECK (currency='CNY'),
    workspace_ref TEXT NOT NULL,
    project_ref TEXT NOT NULL,
    credential_ref TEXT NOT NULL,
    region TEXT NOT NULL,
    base_model TEXT NOT NULL,
    request_plan TEXT NOT NULL CHECK (request_plan='ptu_v2'),
    receipt_plan TEXT NOT NULL CHECK (receipt_plan='ptu'),
    input_tpm_quota INTEGER NOT NULL CHECK (input_tpm_quota=10000),
    output_tpm_quota INTEGER NOT NULL CHECK (output_tpm_quota=1000),
    covers_fixed_infrastructure INTEGER NOT NULL CHECK (covers_fixed_infrastructure=1),
    covers_inference INTEGER NOT NULL CHECK (covers_inference=1),
    cleanup_deadline TEXT NOT NULL,
    max_cost INTEGER NOT NULL CHECK (max_cost > 0),
    state TEXT NOT NULL CHECK (state IN ('reserved','bound')),
    deployed_model TEXT UNIQUE,
    receipt_digest TEXT UNIQUE,
    remote_manifest_digest TEXT UNIQUE,
    receipt_json BLOB,
    final_approval_digest TEXT,
    created_at TEXT NOT NULL,
    bound_at TEXT,
    UNIQUE (account_id, operation_id),
    CHECK ((state='reserved' AND deployed_model IS NULL AND receipt_digest IS NULL
            AND remote_manifest_digest IS NULL
            AND receipt_json IS NULL AND final_approval_digest IS NULL AND bound_at IS NULL)
        OR (state='bound' AND deployed_model IS NOT NULL AND receipt_digest IS NOT NULL
            AND remote_manifest_digest IS NOT NULL
            AND receipt_json IS NOT NULL AND final_approval_digest IS NOT NULL
            AND bound_at IS NOT NULL))
)"""
_DEPLOYMENT_ROLE_BINDING_TABLE_SQL = """CREATE TABLE deployment_role_bindings (
    account_id TEXT NOT NULL REFERENCES budget_accounts(account_id),
    role TEXT NOT NULL CHECK (role IN ('annotator','weak_extractor','judge')),
    reserve_id TEXT NOT NULL REFERENCES infrastructure_reserves(reserve_id),
    PRIMARY KEY (account_id, role)
)"""
_FINAL_TOPOLOGY_COLUMNS = frozenset(
    {
        "account_id",
        "strong_reserve_id",
        "weak_reserve_id",
        "topology_json",
        "topology_digest",
        "recorded_at",
    }
)
_FINAL_TOPOLOGY_TABLE_SQL = """CREATE TABLE final_infrastructure_topologies (
    account_id TEXT PRIMARY KEY REFERENCES budget_accounts(account_id),
    strong_reserve_id TEXT NOT NULL UNIQUE REFERENCES infrastructure_reserves(reserve_id),
    weak_reserve_id TEXT NOT NULL UNIQUE REFERENCES infrastructure_reserves(reserve_id),
    topology_json BLOB NOT NULL UNIQUE,
    topology_digest TEXT NOT NULL UNIQUE,
    recorded_at TEXT NOT NULL,
    CHECK (strong_reserve_id != weak_reserve_id)
)"""
_RECEIPT_ANNEX_COLUMNS = frozenset(
    {
        "annex_digest",
        "reserve_id",
        "receipt_digest",
        "artifact_json",
        "recorded_at",
    }
)
_RECEIPT_ANNEX_TABLE_SQL = """CREATE TABLE final_topology_receipt_annexes (
    annex_digest TEXT PRIMARY KEY,
    reserve_id TEXT NOT NULL UNIQUE REFERENCES infrastructure_reserves(reserve_id),
    receipt_digest TEXT NOT NULL UNIQUE,
    artifact_json BLOB NOT NULL UNIQUE,
    recorded_at TEXT NOT NULL
)"""
_INFRASTRUCTURE_PROVIDER_CAP_EVIDENCE_COLUMNS = frozenset(
    {
        "reserve_id",
        "evidence_bytes",
        "approval_envelope_bytes",
        "evidence_digest",
        "approval_digest",
        "recorded_at",
    }
)
_INFRASTRUCTURE_PROVIDER_CAP_EVIDENCE_TABLE_SQL = (
    """CREATE TABLE infrastructure_provider_cap_evidence (
    reserve_id TEXT PRIMARY KEY REFERENCES infrastructure_reserves(reserve_id),
    evidence_bytes BLOB NOT NULL,
    approval_envelope_bytes BLOB NOT NULL,
    evidence_digest TEXT NOT NULL,
    approval_digest TEXT NOT NULL,
    recorded_at TEXT NOT NULL
)"""
)
type _ProviderCapKey = tuple[
    str,
    str,
    str,
    str,
    str,
    tuple[str, ...],
]


class BudgetLedgerError(RuntimeError):
    """A fail-closed admission or ledger transition failure."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

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
        if update is None:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


class BudgetAmounts(_FrozenModel):
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    cost_minor_units: NonNegativeInt


class RoleRate(_FrozenModel):
    model_role_identity_hash: Sha256Digest
    input_cost_per_million_minor_units: NonNegativeInt
    output_cost_per_million_minor_units: NonNegativeInt


class ProviderSpendCapAttestation(_FrozenModel):
    provider: NonBlankStr
    workspace_ref: NonBlankStr
    project_ref: DigestRef
    credential_ref: DigestRef
    max_cost_minor_units: NonNegativeInt
    observed_at: datetime
    expires_at: datetime
    evidence_digest: Sha256Digest

    @model_validator(mode="after")
    def require_trusted_time(self) -> ProviderSpendCapAttestation:
        for timestamp in (self.observed_at, self.expires_at):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("provider spend-cap times must include timezone")
        if self.expires_at <= self.observed_at:
            raise ValueError("provider spend-cap expiry must follow observation")
        return self


class RequestReserve(_FrozenModel):
    request_unit: NonBlankStr
    role: BudgetRole
    maximum: BudgetAmounts

    @model_validator(mode="after")
    def require_nonzero_bound(self) -> RequestReserve:
        if _is_zero(self.maximum):
            raise ValueError("request reserve must have a non-zero bound")
        return self


class RequestPoolReserve(_FrozenModel):
    """Signed dynamic-request pool for code-owned prompts not enumerable in advance."""

    role: BudgetRole
    max_attempts: Annotated[StrictInt, Field(ge=1)]
    per_attempt_maximum: BudgetAmounts

    @model_validator(mode="after")
    def require_nonzero_bound(self) -> RequestPoolReserve:
        if _is_zero(self.per_attempt_maximum):
            raise ValueError("request pool must have a non-zero per-attempt bound")
        return self


class ProductReserve(_FrozenModel):
    stage: NonBlankStr
    product_id: NonBlankStr
    maximum: BudgetAmounts
    request_reserves: tuple[RequestReserve, ...]
    request_pools: tuple[RequestPoolReserve, ...] = ()

    @model_validator(mode="after")
    def require_nonzero_bound(self) -> ProductReserve:
        if _is_zero(self.maximum):
            raise ValueError("product reserve must have a non-zero bound")
        identities = [item.request_unit for item in self.request_reserves]
        if len(identities) != len(set(identities)):
            raise ValueError("request reserve identities must be unique")
        pool_roles = [item.role for item in self.request_pools]
        if len(pool_roles) != len(set(pool_roles)):
            raise ValueError("request pool roles must be unique")
        if not identities and not pool_roles:
            raise ValueError("a product requires an exact request or request pool")
        worst_case = _sum_amounts(
            (
                *(item.maximum for item in self.request_reserves),
                *(
                    _multiply_amounts(item.per_attempt_maximum, item.max_attempts)
                    for item in self.request_pools
                ),
            )
        )
        if not _fits(worst_case, self.maximum):
            raise ValueError("request worst-case exceeds the product maximum")
        return self


class BudgetContract(_FrozenModel):
    currency: Annotated[StrictStr, StringConstraints(pattern=r"^[A-Z]{3}$")]
    price_snapshot_id: NonBlankStr
    price_observed_at: datetime
    price_expires_at: datetime
    ceiling: BudgetAmounts
    role_rates: Mapping[StrictStr, RoleRate]
    provider_attestation: ProviderSpendCapAttestation
    product_reserves: tuple[ProductReserve, ...]

    @model_validator(mode="after")
    def validate_and_freeze(self) -> BudgetContract:
        for timestamp in (self.price_observed_at, self.price_expires_at):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("price snapshot times must include timezone")
        if self.price_expires_at <= self.price_observed_at:
            raise ValueError("price expiry must follow observation")
        if frozenset(self.role_rates) != _REQUIRED_ROLES:
            raise ValueError("role rates must contain exactly the three model roles")
        if self.provider_attestation.max_cost_minor_units > self.ceiling.cost_minor_units:
            raise ValueError("provider spend cap exceeds approved cost ceiling")
        identities = [(item.stage, item.product_id) for item in self.product_reserves]
        if len(identities) != len(set(identities)):
            raise ValueError("product reserve identities must be unique")
        total = _sum_amounts(item.maximum for item in self.product_reserves)
        if not _fits(total, self.ceiling):
            raise ValueError("product worst-case reserves exceed the total ceiling")
        if total.cost_minor_units > self.provider_attestation.max_cost_minor_units:
            raise ValueError("product worst-case cost exceeds the provider spend cap")
        for product in self.product_reserves:
            for request in product.request_reserves:
                rate = self.role_rates[request.role]
                minimum_cost = role_rate_cost(
                    rate,
                    input_tokens=request.maximum.input_tokens,
                    output_tokens=request.maximum.output_tokens,
                )
                if request.maximum.cost_minor_units < minimum_cost:
                    raise ValueError("request cost reserve is below the signed role rate")
            for pool in product.request_pools:
                rate = self.role_rates[pool.role]
                maximum = pool.per_attempt_maximum
                minimum_cost = role_rate_cost(
                    rate,
                    input_tokens=maximum.input_tokens,
                    output_tokens=maximum.output_tokens,
                )
                if maximum.cost_minor_units < minimum_cost:
                    raise ValueError("request pool cost reserve is below the signed role rate")
        object.__setattr__(self, "role_rates", MappingProxyType(dict(self.role_rates)))
        return self

    @field_serializer("role_rates")
    def serialize_role_rates(self, value: Mapping[str, RoleRate]) -> dict[str, RoleRate]:
        return dict(value)


class AttemptKey(_FrozenModel):
    account_id: Sha256Digest
    stage: NonBlankStr
    product_id: NonBlankStr
    request_unit: NonBlankStr
    attempt_no: Annotated[StrictInt, Field(ge=1)]


class SendPermit(_FrozenModel):
    key: AttemptKey
    owner_token: NonBlankStr
    role: BudgetRole
    maximum: BudgetAmounts


class AttemptSnapshot(_FrozenModel):
    key: AttemptKey
    state: AttemptState
    maximum: BudgetAmounts
    actual: BudgetAmounts
    charged: BudgetAmounts
    response_digest: Sha256Digest | None = None
    usage_verified: StrictBool


class SettlementNoUsageProof(_FrozenModel):
    evidence_digest: Sha256Digest
    provider_request_id: NonBlankStr
    verifier_policy: NonBlankStr
    observed_at: datetime


class ProductSettlementAttempt(_FrozenModel):
    request_unit: NonBlankStr
    attempt_no: Annotated[StrictInt, Field(ge=1)]
    role: BudgetRole
    limit_kind: Literal["exact", "pool"]
    state: AttemptState
    maximum: BudgetAmounts
    actual: BudgetAmounts
    usage_verified: StrictBool
    response_digest: Sha256Digest | None = None
    no_usage_proof: SettlementNoUsageProof | None = None


class ProductSettlementSnapshot(_FrozenModel):
    account_id: Sha256Digest
    budget_revision: Annotated[StrictInt, Field(ge=1)]
    approval_digest: Sha256Digest
    stage: NonBlankStr
    product_id: NonBlankStr
    reservation_state: Literal["reserved", "settled", "released"]
    reservation_maximum: BudgetAmounts
    reservation_actual: BudgetAmounts
    attempts: tuple[ProductSettlementAttempt, ...]


class AccountSnapshot(_FrozenModel):
    account_id: Sha256Digest
    revision: Annotated[StrictInt, Field(ge=1)]
    approval_digest: Sha256Digest
    ceiling: BudgetAmounts
    reserved: BudgetAmounts
    settled: BudgetAmounts
    uncertain: BudgetAmounts
    attempt_count: NonNegativeInt
    overage: bool


class BudgetAdmissionProof(_FrozenModel):
    """Redacted proof that one signed contract matches one immutable plan."""

    contract_hash: Sha256Digest
    approval_digest: Sha256Digest
    revision: Annotated[StrictInt, Field(ge=1)]
    currency: Annotated[StrictStr, StringConstraints(pattern=r"^[A-Z]{3}$")]
    ceiling: BudgetAmounts
    price_expires_at: datetime
    provider_attestation_expires_at: datetime


class InfrastructureReserveSnapshot(_FrozenModel):
    """Redacted durable state for one fixed-cost deployment reserve."""

    reserve_id: NonBlankStr
    account_id: Sha256Digest
    run_identity: NonBlankStr
    purpose: NonBlankStr
    operation_id: NonBlankStr
    authorization_domain: AuthorizationDomain
    authorization_digest: Sha256Digest
    maximum: BudgetAmounts
    state: Literal["reserved", "bound"]
    deployed_model: NonBlankStr | None = None
    receipt_digest: Sha256Digest | None = None
    final_approval_digest: Sha256Digest | None = None
    roles: tuple[BudgetRole, ...] = ()


class InfrastructureCreatePermit(_FrozenModel):
    """Proof that a create transition already owns its durable fixed-cost reserve."""

    operation_id: NonBlankStr
    reserve: InfrastructureReserveSnapshot
    authorization_expires_at: datetime
    provider_cap_expires_at: datetime
    cleanup_deadline: datetime

    @model_validator(mode="after")
    def require_pre_post_reserve(self) -> InfrastructureCreatePermit:
        if self.operation_id != self.reserve.operation_id:
            raise ValueError("infrastructure create permit operation mismatch")
        if self.reserve.authorization_domain != PROVISIONING_AUTHORIZATION_DOMAIN:
            raise ValueError("only provisioning can yield a create permit")
        if self.reserve.state != "reserved" or self.reserve.deployed_model is not None:
            raise ValueError("create permit requires an unbound durable reserve")
        for field_name, timestamp in (
            ("authorization_expires_at", self.authorization_expires_at),
            ("provider_cap_expires_at", self.provider_cap_expires_at),
            ("cleanup_deadline", self.cleanup_deadline),
        ):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError(f"{field_name} must include a timezone")
        return self

    def require_fresh(self, now: datetime) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise BudgetLedgerError("permit freshness time must include a timezone")
        if now >= self.authorization_expires_at:
            raise BudgetLedgerError("create permit authorization has expired")
        if now >= self.provider_cap_expires_at:
            raise BudgetLedgerError("create permit provider cap has expired")
        if now >= self.cleanup_deadline:
            raise BudgetLedgerError("create permit cleanup deadline has elapsed")


class FinalTopologyDeployment(_FrozenModel):
    """Exact durable deployment facts carried by the sealed final topology."""

    reserve_id: NonBlankStr
    operation_id: NonBlankStr
    authorization_digest: Sha256Digest
    pricing_evidence_digest: Sha256Digest
    pricing_approval_digest: Sha256Digest
    maximum_cost_minor_units: NonNegativeInt
    deployed_model: NonBlankStr
    receipt_json_digest: Sha256Digest
    receipt_digest: Sha256Digest
    remote_manifest_digest: Sha256Digest
    receipt: DeploymentReceipt
    roles: tuple[BudgetRole, ...]
    cleanup_deadline: datetime
    reconciliation_digest: Sha256Digest
    transport_identity_digest: Sha256Digest


class _DurableFinalDeploymentEvidence(_FrozenModel):
    reserve_id: NonBlankStr
    roles: tuple[BudgetRole, ...]
    pricing_evidence_json: NonBlankStr
    pricing_approval: PricingEvidenceApproval
    receipt_annex_digest: Sha256Digest
    reconciliation_digest: Sha256Digest


class _DurableFinalTopologyRecord(_FrozenModel):
    version: Literal["insurancekb.run-admission.final-topology.v1"]
    plan: RunAdmissionPlanPayload
    contract: BudgetContract
    budget_envelope: BudgetApprovalEnvelope
    expected_scope: NonBlankStr
    provider_cap_evidence_json: NonBlankStr
    provider_cap_approval: ProviderCapApproval
    strong: _DurableFinalDeploymentEvidence
    weak: _DurableFinalDeploymentEvidence


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class VerifiedInfrastructureProviderCapCapability:
    """Opaque provider cap issued only from a fresh production ledger transaction."""

    run_identity: str
    purpose: str
    scope: str
    operation_id: str
    reserve_id: str
    evidence_digest: str
    approval_digest: str
    provider: str
    currency: str
    workspace_ref: str
    project_ref: str
    credential_ref: str
    coverage: frozenset[str]
    max_cost_minor_units: int
    expires_at: datetime
    _seal: object


def _infrastructure_capability_snapshot(
    capability: VerifiedInfrastructureProviderCapCapability,
) -> bytes:
    return canonical_json_bytes(
        {
            name: (
                tuple(sorted(value)) if isinstance(value, frozenset) else value
            )
            for name, value in (
                ("approval_digest", capability.approval_digest),
                ("coverage", capability.coverage),
                ("credential_ref", capability.credential_ref),
                ("currency", capability.currency),
                ("evidence_digest", capability.evidence_digest),
                ("expires_at", capability.expires_at),
                ("max_cost_minor_units", capability.max_cost_minor_units),
                ("operation_id", capability.operation_id),
                ("project_ref", capability.project_ref),
                ("provider", capability.provider),
                ("purpose", capability.purpose),
                ("reserve_id", capability.reserve_id),
                ("run_identity", capability.run_identity),
                ("scope", capability.scope),
                ("workspace_ref", capability.workspace_ref),
            )
        }
    )


def require_verified_infrastructure_provider_capability(
    capability: object,
) -> VerifiedInfrastructureProviderCapCapability:
    if (
        not isinstance(capability, VerifiedInfrastructureProviderCapCapability)
        or capability._seal is not _INFRASTRUCTURE_PROVIDER_CAPABILITY_SEAL
    ):
        raise AuthorizationVerificationError(
            "ledger-admitted infrastructure provider cap capability is required"
        )
    _LEDGER_CAPABILITY_SNAPSHOT_REGISTRY.require(
        capability,
        domain=_INFRASTRUCTURE_CAP_SNAPSHOT_DOMAIN,
        snapshot=_infrastructure_capability_snapshot(capability),
    )
    return capability


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class VerifiedTopologyProviderCapCapability:
    """Provider cap issued only after a fresh bound final-topology reload."""

    topology_digest: str
    run_identity: str
    purpose: str
    scope: str
    operation_id: str
    reserve_id: str
    evidence_digest: str
    approval_digest: str
    provider: str
    currency: str
    workspace_ref: str
    project_ref: str
    credential_ref: str
    coverage: frozenset[str]
    max_cost_minor_units: int
    expires_at: datetime
    _seal: object


def _topology_capability_snapshot(
    capability: VerifiedTopologyProviderCapCapability,
) -> bytes:
    return canonical_json_bytes(
        {
            "approval_digest": capability.approval_digest,
            "coverage": tuple(sorted(capability.coverage)),
            "credential_ref": capability.credential_ref,
            "currency": capability.currency,
            "evidence_digest": capability.evidence_digest,
            "expires_at": capability.expires_at,
            "max_cost_minor_units": capability.max_cost_minor_units,
            "operation_id": capability.operation_id,
            "project_ref": capability.project_ref,
            "provider": capability.provider,
            "purpose": capability.purpose,
            "reserve_id": capability.reserve_id,
            "run_identity": capability.run_identity,
            "scope": capability.scope,
            "topology_digest": capability.topology_digest,
            "workspace_ref": capability.workspace_ref,
        }
    )


def require_verified_topology_provider_capability(
    capability: object,
) -> VerifiedTopologyProviderCapCapability:
    if (
        not isinstance(capability, VerifiedTopologyProviderCapCapability)
        or capability._seal is not _TOPOLOGY_PROVIDER_CAPABILITY_SEAL
    ):
        raise AuthorizationVerificationError(
            "ledger-admitted topology-bound provider cap capability is required"
        )
    _LEDGER_CAPABILITY_SNAPSHOT_REGISTRY.require(
        capability,
        domain=_TOPOLOGY_CAP_SNAPSHOT_DOMAIN,
        snapshot=_topology_capability_snapshot(capability),
    )
    return capability


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class VerifiedFinalTopology:
    """Opaque capability issued only from production durable ledger state."""

    topology_digest: str
    account_id: str
    run_identity: str
    purpose: str
    scope: str
    plan_payload_hash: str
    budget_contract_hash: str
    budget_approval_digest: str
    budget_revision: int
    budget_approval_expires_at: datetime
    strong: FinalTopologyDeployment
    weak: FinalTopologyDeployment
    provider: str
    currency: str
    workspace_ref: str
    project_ref: str
    credential_ref: str
    provider_cap_evidence_digest: str
    provider_cap_approval_digest: str
    provider_cap_coverage: frozenset[str]
    provider_cap_max_cost_minor_units: int
    provider_cap_expires_at: datetime
    provider_cap_approval_expires_at: datetime
    issued_at: datetime
    valid_until: datetime
    _seal: object


def _final_topology_capability_snapshot(capability: VerifiedFinalTopology) -> bytes:
    return canonical_json_bytes(
        {
            name: (tuple(sorted(value)) if isinstance(value, frozenset) else value)
            for name in type(capability).__slots__
            if name not in {"__weakref__", "_seal"}
            for value in (getattr(capability, name),)
        }
    )


def _final_topology_durable_snapshot(capability: VerifiedFinalTopology) -> bytes:
    """Canonical stable facts; excludes per-load issuance metadata."""

    return canonical_json_bytes(
        {
            name: (tuple(sorted(value)) if isinstance(value, frozenset) else value)
            for name in type(capability).__slots__
            if name not in {"__weakref__", "_seal", "issued_at"}
            for value in (getattr(capability, name),)
        }
    )


def require_verified_final_topology(
    capability: object,
    *,
    now: datetime,
    expected_plan_payload_hash: str,
    expected_scope: str,
) -> VerifiedFinalTopology:
    """Reject caller-created, testing-ledger, or stale topology DTOs."""

    if (
        not isinstance(capability, VerifiedFinalTopology)
        or capability._seal is not _FINAL_TOPOLOGY_SEAL
    ):
        raise BudgetLedgerError("verified production final topology is required")
    try:
        _LEDGER_CAPABILITY_SNAPSHOT_REGISTRY.require(
            capability,
            domain=_FINAL_TOPOLOGY_SNAPSHOT_DOMAIN,
            snapshot=_final_topology_capability_snapshot(capability),
        )
    except AuthorizationVerificationError as exc:
        raise BudgetLedgerError("verified final topology issuer snapshot is unavailable") from exc
    if now.tzinfo is None or now.utcoffset() is None:
        raise BudgetLedgerError("final topology freshness time must include a timezone")
    if now >= capability.valid_until:
        raise BudgetLedgerError("verified production final topology is stale")
    if capability.plan_payload_hash != expected_plan_payload_hash:
        raise BudgetLedgerError("verified production final topology plan has drifted")
    if capability.scope != expected_scope:
        raise BudgetLedgerError("verified production final topology scope has drifted")
    return capability


@dataclass(frozen=True, slots=True)
class FinalInfrastructureBindingRequest:
    """All public evidence required to bind one deployment in the final topology."""

    reserve_id: str
    authorization: InfrastructureAuthorization
    expected_authorization: ProvisioningAuthorizationPayload
    receipt_capability: VerifiedReconciledDeploymentReceipt
    roles: tuple[BudgetRole, ...]
    pricing_evidence_bytes: bytes
    pricing_approval: PricingEvidenceApproval
    provider_cap_evidence_bytes: bytes
    provider_cap_approval: ProviderCapApproval


@dataclass(frozen=True, slots=True)
class _FinalTopologyBindResult:
    snapshots: tuple[InfrastructureReserveSnapshot, InfrastructureReserveSnapshot]


def _is_zero(value: BudgetAmounts) -> bool:
    return value.input_tokens == 0 and value.output_tokens == 0 and value.cost_minor_units == 0


def _sum_amounts(values: Iterator[BudgetAmounts] | tuple[BudgetAmounts, ...]) -> BudgetAmounts:
    input_tokens = 0
    output_tokens = 0
    cost_minor_units = 0
    for value in values:
        input_tokens += value.input_tokens
        output_tokens += value.output_tokens
        cost_minor_units += value.cost_minor_units
    return BudgetAmounts(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_minor_units=cost_minor_units,
    )


def _add(left: BudgetAmounts, right: BudgetAmounts) -> BudgetAmounts:
    return BudgetAmounts(
        input_tokens=left.input_tokens + right.input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
        cost_minor_units=left.cost_minor_units + right.cost_minor_units,
    )


def _multiply_amounts(value: BudgetAmounts, multiplier: int) -> BudgetAmounts:
    return BudgetAmounts(
        input_tokens=value.input_tokens * multiplier,
        output_tokens=value.output_tokens * multiplier,
        cost_minor_units=value.cost_minor_units * multiplier,
    )


def _fits(value: BudgetAmounts, ceiling: BudgetAmounts) -> bool:
    return (
        value.input_tokens <= ceiling.input_tokens
        and value.output_tokens <= ceiling.output_tokens
        and value.cost_minor_units <= ceiling.cost_minor_units
    )


def budget_contract_hash(contract: BudgetContract) -> str:
    return hashlib.sha256(_CONTRACT_DOMAIN + canonical_json_bytes(contract)).hexdigest()


def model_role_budget_identity_hash(role_plan: ModelRolePlan) -> str:
    return hashlib.sha256(_MODEL_ROLE_DOMAIN + canonical_json_bytes(role_plan)).hexdigest()


def derive_role_rate_from_pricing(
    pricing_capability: VerifiedPricingCapability,
    *,
    role_plan: ModelRolePlan,
    expected_provider: str,
    expected_currency: str,
    candidate: RoleRate | None = None,
) -> RoleRate:
    """Derive or revalidate the sole RoleRate allowed by sealed signed pricing."""

    try:
        pricing = require_verified_pricing_capability(pricing_capability)
    except AuthorizationVerificationError as exc:
        raise BudgetLedgerError("verified pricing is required for role rate") from exc
    if (
        role_plan.provider != pricing.provider
        or expected_provider != pricing.provider
        or expected_currency != pricing.currency
    ):
        raise BudgetLedgerError("role rate resource does not match signed pricing")
    expected = RoleRate(
        model_role_identity_hash=model_role_budget_identity_hash(role_plan),
        input_cost_per_million_minor_units=pricing.input_cost_per_million_minor_units,
        output_cost_per_million_minor_units=pricing.output_cost_per_million_minor_units,
    )
    if candidate is not None and canonical_json_bytes(candidate) != canonical_json_bytes(expected):
        raise BudgetLedgerError("role rate differs from signed pricing or model identity")
    return expected


def role_rate_digest(rate: RoleRate) -> str:
    return hashlib.sha256(_ROLE_RATE_DOMAIN + canonical_json_bytes(rate)).hexdigest()


def role_rate_cost(rate: RoleRate, *, input_tokens: int, output_tokens: int) -> int:
    """Price input and output independently with integer ceiling arithmetic."""

    input_cost = (input_tokens * rate.input_cost_per_million_minor_units + 999_999) // 1_000_000
    output_cost = (output_tokens * rate.output_cost_per_million_minor_units + 999_999) // 1_000_000
    return input_cost + output_cost


def budget_account_identity(run_identity: str, purpose: str) -> str:
    payload = canonical_json_bytes({"purpose": purpose, "run_identity": run_identity})
    return hashlib.sha256(_ACCOUNT_DOMAIN + payload).hexdigest()


def _approval_digest(envelope: BudgetApprovalEnvelope) -> str:
    return hashlib.sha256(_APPROVAL_DIGEST_DOMAIN + canonical_json_bytes(envelope)).hexdigest()


def _owner_token_digest(owner_token: str) -> str:
    return hashlib.sha256(_OWNER_TOKEN_DOMAIN + owner_token.encode("utf-8")).hexdigest()


def verify_budget_admission_contract(
    *,
    plan: RunAdmissionPlanPayload,
    contract: BudgetContract,
    envelope: BudgetApprovalEnvelope,
    trusted_public_keys: Mapping[str, TrustedAuthority],
    expected_scope: str,
    authorized_roles: frozenset[str],
    now: datetime,
) -> BudgetAdmissionProof:
    """Verify signatures, freshness, rates, attestation, and exact ceilings."""

    try:
        verify_approval_envelope(
            envelope,
            expected_domain="budget",
            expected_plan_payload_hash=plan_payload_hash(plan),
            expected_run_identity=plan.run_identity,
            expected_purpose=plan.purpose,
            expected_scope=expected_scope,
            trusted_public_keys=trusted_public_keys,
            allowed_roles=authorized_roles,
            now=now,
        )
    except ApprovalVerificationError as exc:
        raise BudgetLedgerError("budget approval rejected") from exc

    if len(envelope.payload.budget_entries) != 1:
        raise BudgetLedgerError("budget approval must contain exactly one contract")
    entry = envelope.payload.budget_entries[0]
    contract_digest = budget_contract_hash(contract)
    if now >= contract.price_expires_at or now >= contract.provider_attestation.expires_at:
        raise BudgetLedgerError("budget price or provider attestation is expired")
    if plan.budget_contract_hash != contract_digest:
        raise BudgetLedgerError("plan does not bind the supplied budget contract")
    if frozenset(plan.model_roles) != _REQUIRED_ROLES:
        raise BudgetLedgerError("budget role rates do not match the admitted models")
    for role in _REQUIRED_ROLES:
        role_plan = plan.model_roles[role]
        if not isinstance(role_plan, ModelRolePlan) or contract.role_rates[
            role
        ].model_role_identity_hash != model_role_budget_identity_hash(role_plan):
            raise BudgetLedgerError("budget role rates do not match the admitted models")
    ceiling = contract.ceiling
    if (
        entry.budget_contract_hash != contract_digest
        or entry.currency != contract.currency
        or entry.max_input_tokens != ceiling.input_tokens
        or entry.max_output_tokens != ceiling.output_tokens
        or entry.max_cost_minor_units != ceiling.cost_minor_units
    ):
        raise BudgetLedgerError("budget contract does not match signed approval")
    return BudgetAdmissionProof(
        contract_hash=contract_digest,
        approval_digest=_approval_digest(envelope),
        revision=envelope.payload.revision,
        currency=contract.currency,
        ceiling=ceiling,
        price_expires_at=contract.price_expires_at,
        provider_attestation_expires_at=contract.provider_attestation.expires_at,
    )


def _amounts_from_row(
    row: sqlite3.Row,
    input_name: str,
    output_name: str,
    cost_name: str,
) -> BudgetAmounts:
    return BudgetAmounts(
        input_tokens=int(row[input_name]),
        output_tokens=int(row[output_name]),
        cost_minor_units=int(row[cost_name]),
    )


class BudgetLedger:
    """SQLite budget state machine; every mutation holds a BEGIN IMMEDIATE lock."""

    def __init__(self, db_path: Path) -> None:
        self._initialize(db_path, clock=_utc_now, testing_sentinel=None)

    @classmethod
    def _for_testing(
        cls,
        db_path: Path,
        *,
        clock: Callable[[], datetime],
    ) -> Self:
        instance = cls.__new__(cls)
        instance._initialize(
            db_path,
            clock=clock,
            testing_sentinel=_TESTING_MODE_SENTINEL,
        )
        return instance

    def _initialize(
        self,
        db_path: Path,
        *,
        clock: Callable[[], datetime],
        testing_sentinel: object | None,
    ) -> None:
        self._db_path = Path(db_path)
        self._clock = clock
        self._testing_sentinel = testing_sentinel
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._db_path,
            timeout=_BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        return connection

    @staticmethod
    def _production_operational_configuration() -> tuple[
        Mapping[str, TrustedAuthority],
        frozenset[str],
        frozenset[str],
        frozenset[str],
    ]:
        """Load the code-fixed, root-owned production trust configuration.

        Production mutation APIs deliberately expose no caller-controlled trust
        argument.  The dynamic import avoids an import cycle with the CLI module,
        which owns the protected filesystem loader.
        """

        from insurance_harness.goldenset.admission_cli import (
            _load_deployment_approval_configuration,
        )

        configuration = _load_deployment_approval_configuration()
        authorities = configuration[0]
        if not authorities:
            raise BudgetLedgerError("root-owned operational trust configuration is unavailable")
        return configuration

    @classmethod
    def _production_operational_authorities(cls) -> Mapping[str, TrustedAuthority]:
        return cls._production_operational_configuration()[0]

    def _initialize_schema(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("BEGIN IMMEDIATE")
            version_row = connection.execute("PRAGMA user_version").fetchone()
            assert version_row is not None
            version = int(version_row[0])
            if version not in {
                0,
                _PRE_POOL_SCHEMA_VERSION,
                _PRE_USAGE_SCHEMA_VERSION,
                _PRE_CANARY_SCHEMA_VERSION,
                _PRE_INFRASTRUCTURE_SCHEMA_VERSION,
                _PRE_FINAL_TOPOLOGY_SCHEMA_VERSION,
                _PRE_RECEIPT_ANNEX_SCHEMA_VERSION,
                _PRE_PROVIDER_CAP_SIDECAR_SCHEMA_VERSION,
                _SCHEMA_VERSION,
            }:
                raise BudgetLedgerError("budget schema migration version is unsupported")
            self._create_base_schema(connection)
            self._migrate_attempt_schema(connection, version)
            self._migrate_pool_schema(connection, version)
            self._migrate_canary_claim_schema(connection, version)
            self._migrate_infrastructure_schema(connection, version)
            self._migrate_infrastructure_provider_cap_evidence_schema(connection, version)
            self._migrate_final_topology_schema(connection, version)
            self._migrate_receipt_annex_schema(connection, version)
            if version != _SCHEMA_VERSION:
                self._reconcile_legacy_settled_reservations(connection)
            connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise BudgetLedgerError("budget schema migration foreign-key check failed")
            connection.commit()
        except BaseException as exc:
            connection.rollback()
            if isinstance(exc, BudgetLedgerError):
                raise
            raise BudgetLedgerError("budget schema migration failed") from exc
        finally:
            connection.close()

    @staticmethod
    def _create_base_schema(connection: sqlite3.Connection) -> None:
        statements = (
            """
                CREATE TABLE IF NOT EXISTS budget_accounts (
                    account_id TEXT PRIMARY KEY,
                    run_identity TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    ceiling_input INTEGER NOT NULL CHECK (ceiling_input >= 0),
                    ceiling_output INTEGER NOT NULL CHECK (ceiling_output >= 0),
                    ceiling_cost INTEGER NOT NULL CHECK (ceiling_cost >= 0),
                    current_revision INTEGER NOT NULL CHECK (current_revision >= 1),
                    approval_digest TEXT NOT NULL UNIQUE,
                    overage INTEGER NOT NULL DEFAULT 0 CHECK (overage IN (0, 1)),
                    UNIQUE (run_identity, purpose)
                )
                """,
            """
                CREATE TABLE IF NOT EXISTS budget_approvals (
                    account_id TEXT NOT NULL REFERENCES budget_accounts(account_id),
                    revision INTEGER NOT NULL,
                    approval_digest TEXT NOT NULL UNIQUE,
                    previous_digest TEXT,
                    plan_payload_hash TEXT NOT NULL,
                    contract_hash TEXT NOT NULL,
                    contract_json BLOB NOT NULL,
                    ceiling_input INTEGER NOT NULL,
                    ceiling_output INTEGER NOT NULL,
                    ceiling_cost INTEGER NOT NULL,
                    PRIMARY KEY (account_id, revision)
                )
                """,
            """
                CREATE TABLE IF NOT EXISTS product_limits (
                    account_id TEXT NOT NULL REFERENCES budget_accounts(account_id),
                    stage TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    max_input INTEGER NOT NULL,
                    max_output INTEGER NOT NULL,
                    max_cost INTEGER NOT NULL,
                    PRIMARY KEY (account_id, stage, product_id)
                )
                """,
            """
                CREATE TABLE IF NOT EXISTS request_limits (
                    account_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    request_unit TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('annotator','weak_extractor','judge')),
                    max_input INTEGER NOT NULL,
                    max_output INTEGER NOT NULL,
                    max_cost INTEGER NOT NULL,
                    PRIMARY KEY (account_id, stage, product_id, request_unit),
                    FOREIGN KEY (account_id, stage, product_id)
                        REFERENCES product_limits(account_id, stage, product_id)
                )
                """,
            """
                CREATE TABLE IF NOT EXISTS product_reservations (
                    account_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('reserved','settled','released')),
                    max_input INTEGER NOT NULL,
                    max_output INTEGER NOT NULL,
                    max_cost INTEGER NOT NULL,
                    actual_input INTEGER NOT NULL DEFAULT 0,
                    actual_output INTEGER NOT NULL DEFAULT 0,
                    actual_cost INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (account_id, stage, product_id),
                    FOREIGN KEY (account_id, stage, product_id)
                        REFERENCES product_limits(account_id, stage, product_id)
                )
                """,
        )
        for statement in statements:
            connection.execute(statement)

    @staticmethod
    def _create_attempt_table(connection: sqlite3.Connection, *, table_name: str) -> None:
        if table_name not in {"request_attempts", "request_attempts_v3"}:
            raise BudgetLedgerError("budget schema migration table name is invalid")
        connection.execute(
            f"""CREATE TABLE {table_name} (
                account_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                product_id TEXT NOT NULL,
                request_unit TEXT NOT NULL,
                attempt_no INTEGER NOT NULL CHECK (attempt_no >= 1),
                owner_token_digest TEXT NOT NULL,
                role TEXT NOT NULL CHECK (
                    role IN ('annotator','weak_extractor','judge')
                ),
                limit_kind TEXT NOT NULL CHECK (limit_kind IN ('exact','pool')),
                state TEXT NOT NULL CHECK (
                    state IN ('prepared','sent','terminal','uncertain','no_usage')
                ),
                max_input INTEGER NOT NULL,
                max_output INTEGER NOT NULL,
                max_cost INTEGER NOT NULL,
                actual_input INTEGER NOT NULL DEFAULT 0,
                actual_output INTEGER NOT NULL DEFAULT 0,
                actual_cost INTEGER NOT NULL DEFAULT 0,
                charged_input INTEGER NOT NULL DEFAULT 0,
                charged_output INTEGER NOT NULL DEFAULT 0,
                charged_cost INTEGER NOT NULL DEFAULT 0,
                response_digest TEXT,
                usage_verified INTEGER NOT NULL DEFAULT 0 CHECK (
                    usage_verified IN (0, 1)
                ),
                provider_proof_digest TEXT,
                provider_request_id TEXT,
                provider_verifier_policy TEXT,
                provider_proof_observed_at TEXT,
                PRIMARY KEY (
                    account_id, stage, product_id, request_unit, attempt_no
                ),
                FOREIGN KEY (account_id, stage, product_id)
                    REFERENCES product_reservations(account_id, stage, product_id)
            )"""
        )

    @staticmethod
    def _create_pool_table(connection: sqlite3.Connection, *, table_name: str) -> None:
        if table_name not in {"request_pool_limits", "request_pool_limits_v2"}:
            raise BudgetLedgerError("budget schema migration table name is invalid")
        connection.execute(
            f"""CREATE TABLE {table_name} (
                account_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                product_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (
                    role IN ('annotator','weak_extractor','judge')
                ),
                max_attempts INTEGER NOT NULL CHECK (max_attempts >= 1),
                max_input INTEGER NOT NULL,
                max_output INTEGER NOT NULL,
                max_cost INTEGER NOT NULL,
                model_role_identity_hash TEXT NOT NULL,
                role_rate_digest TEXT NOT NULL,
                PRIMARY KEY (account_id, stage, product_id, role),
                FOREIGN KEY (account_id, stage, product_id)
                    REFERENCES product_limits(account_id, stage, product_id)
            )"""
        )

    @staticmethod
    def _create_canary_claim_table(connection: sqlite3.Connection) -> None:
        connection.execute(_CANARY_CLAIM_TABLE_SQL)

    @staticmethod
    def _table_columns(connection: sqlite3.Connection, table_name: str) -> frozenset[str]:
        if table_name not in {
            "canary_capability_claims",
            "deployment_role_bindings",
            "final_infrastructure_topologies",
            "final_topology_receipt_annexes",
            "infrastructure_provider_cap_evidence",
            "infrastructure_authorizations",
            "infrastructure_reserves",
            "request_attempts",
            "request_attempts_v3",
            "request_pool_limits",
            "request_pool_limits_v2",
        }:
            raise BudgetLedgerError("budget schema migration table name is invalid")
        return frozenset(
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        )

    def _migrate_attempt_schema(self, connection: sqlite3.Connection, version: int) -> None:
        columns = self._table_columns(connection, "request_attempts")
        if not columns:
            if version in {_PRE_POOL_SCHEMA_VERSION, _PRE_USAGE_SCHEMA_VERSION}:
                raise BudgetLedgerError("budget schema migration lost the old attempt table")
            self._create_attempt_table(connection, table_name="request_attempts")
            return
        if columns == _CURRENT_ATTEMPT_COLUMNS:
            if version in {_PRE_POOL_SCHEMA_VERSION, _PRE_USAGE_SCHEMA_VERSION}:
                raise BudgetLedgerError("budget schema migration version does not match table")
            return
        if columns not in {_PRE_POOL_ATTEMPT_COLUMNS, _PRE_USAGE_ATTEMPT_COLUMNS}:
            raise BudgetLedgerError("budget schema migration found unknown attempt columns")
        if (
            version
            in {
                _PRE_CANARY_SCHEMA_VERSION,
                _PRE_INFRASTRUCTURE_SCHEMA_VERSION,
                _PRE_FINAL_TOPOLOGY_SCHEMA_VERSION,
                _PRE_RECEIPT_ANNEX_SCHEMA_VERSION,
                _PRE_PROVIDER_CAP_SIDECAR_SCHEMA_VERSION,
                _SCHEMA_VERSION,
            }
            or (version == _PRE_USAGE_SCHEMA_VERSION and columns != _PRE_USAGE_ATTEMPT_COLUMNS)
            or (version == _PRE_POOL_SCHEMA_VERSION and columns != _PRE_POOL_ATTEMPT_COLUMNS)
        ):
            raise BudgetLedgerError("budget schema migration version does not match table")

        old_rows = connection.execute(
            """SELECT account_id,stage,product_id,request_unit,attempt_no,
                      owner_token_digest,state,max_input,max_output,max_cost,
                      actual_input,actual_output,actual_cost,
                      charged_input,charged_output,charged_cost,response_digest,
                      provider_proof_digest,provider_request_id,
                      provider_verifier_policy,provider_proof_observed_at
               FROM request_attempts
               ORDER BY account_id,stage,product_id,request_unit,attempt_no"""
        ).fetchall()
        self._create_attempt_table(connection, table_name="request_attempts_v3")
        if columns == _PRE_POOL_ATTEMPT_COLUMNS:
            connection.execute(
                """INSERT INTO request_attempts_v3 (
                   account_id,stage,product_id,request_unit,attempt_no,
                   owner_token_digest,role,limit_kind,state,
                   max_input,max_output,max_cost,
                   actual_input,actual_output,actual_cost,
                   charged_input,charged_output,charged_cost,response_digest,usage_verified,
                   provider_proof_digest,provider_request_id,
                   provider_verifier_policy,provider_proof_observed_at
               )
               SELECT a.account_id,a.stage,a.product_id,a.request_unit,a.attempt_no,
                      a.owner_token_digest,l.role,'exact',a.state,
                      a.max_input,a.max_output,a.max_cost,
                      a.actual_input,a.actual_output,a.actual_cost,
                      a.charged_input,a.charged_output,a.charged_cost,
                      a.response_digest,0,a.provider_proof_digest,
                      a.provider_request_id,a.provider_verifier_policy,
                      a.provider_proof_observed_at
               FROM request_attempts AS a
               JOIN request_limits AS l
                 ON l.account_id=a.account_id AND l.stage=a.stage
                AND l.product_id=a.product_id AND l.request_unit=a.request_unit"""
            )
        else:
            connection.execute(
                """INSERT INTO request_attempts_v3 (
                       account_id,stage,product_id,request_unit,attempt_no,
                       owner_token_digest,role,limit_kind,state,
                       max_input,max_output,max_cost,
                       actual_input,actual_output,actual_cost,
                       charged_input,charged_output,charged_cost,response_digest,
                       usage_verified,provider_proof_digest,provider_request_id,
                       provider_verifier_policy,provider_proof_observed_at
                   )
                   SELECT account_id,stage,product_id,request_unit,attempt_no,
                          owner_token_digest,role,limit_kind,state,
                          max_input,max_output,max_cost,
                          actual_input,actual_output,actual_cost,
                          charged_input,charged_output,charged_cost,response_digest,
                          0,provider_proof_digest,provider_request_id,
                          provider_verifier_policy,provider_proof_observed_at
                   FROM request_attempts"""
            )
        new_rows = connection.execute(
            """SELECT account_id,stage,product_id,request_unit,attempt_no,
                      owner_token_digest,state,max_input,max_output,max_cost,
                      actual_input,actual_output,actual_cost,
                      charged_input,charged_output,charged_cost,response_digest,
                      provider_proof_digest,provider_request_id,
                      provider_verifier_policy,provider_proof_observed_at
               FROM request_attempts_v3
               ORDER BY account_id,stage,product_id,request_unit,attempt_no"""
        ).fetchall()
        if [tuple(row) for row in new_rows] != [tuple(row) for row in old_rows]:
            raise BudgetLedgerError("budget schema migration did not preserve attempt rows")
        if connection.execute("PRAGMA foreign_key_check(request_attempts_v3)").fetchall():
            raise BudgetLedgerError("budget schema migration attempt integrity failed")
        usage_rows = connection.execute("SELECT usage_verified FROM request_attempts_v3").fetchall()
        if any(int(row[0]) != 0 for row in usage_rows):
            raise BudgetLedgerError("budget schema migration usage provenance failed")
        connection.execute("DROP TABLE request_attempts")
        connection.execute("ALTER TABLE request_attempts_v3 RENAME TO request_attempts")

    def _migrate_pool_schema(self, connection: sqlite3.Connection, version: int) -> None:
        columns = self._table_columns(connection, "request_pool_limits")
        if not columns:
            self._create_pool_table(connection, table_name="request_pool_limits")
            return
        if columns == _CURRENT_POOL_COLUMNS:
            if version == _PRE_POOL_SCHEMA_VERSION:
                raise BudgetLedgerError("budget schema migration version does not match table")
            return
        if columns != _PRE_BINDING_POOL_COLUMNS or version in {
            _PRE_USAGE_SCHEMA_VERSION,
            _PRE_CANARY_SCHEMA_VERSION,
            _PRE_INFRASTRUCTURE_SCHEMA_VERSION,
            _PRE_FINAL_TOPOLOGY_SCHEMA_VERSION,
            _PRE_RECEIPT_ANNEX_SCHEMA_VERSION,
            _PRE_PROVIDER_CAP_SIDECAR_SCHEMA_VERSION,
            _SCHEMA_VERSION,
        }:
            raise BudgetLedgerError("budget schema migration found unknown pool columns")

        old_rows = connection.execute(
            """SELECT account_id,stage,product_id,role,max_attempts,
                      max_input,max_output,max_cost
               FROM request_pool_limits
               ORDER BY account_id,stage,product_id,role"""
        ).fetchall()
        self._create_pool_table(connection, table_name="request_pool_limits_v2")
        for row in old_rows:
            approvals = connection.execute(
                """SELECT contract_json FROM budget_approvals
                   WHERE account_id=? ORDER BY revision""",
                (str(row["account_id"]),),
            ).fetchall()
            maximum = _amounts_from_row(row, "max_input", "max_output", "max_cost")
            role = cast(BudgetRole, str(row["role"]))
            original_rate: RoleRate | None = None
            for approval in approvals:
                try:
                    contract = BudgetContract.model_validate_json(bytes(approval[0]))
                except (TypeError, ValueError) as exc:
                    raise BudgetLedgerError(
                        "budget schema migration cannot validate an approval contract"
                    ) from exc
                historical_pool = next(
                    (
                        pool
                        for product in contract.product_reserves
                        if product.stage == str(row["stage"])
                        and product.product_id == str(row["product_id"])
                        for pool in product.request_pools
                        if pool.role == role
                    ),
                    None,
                )
                if historical_pool is None:
                    if original_rate is not None:
                        raise BudgetLedgerError(
                            "budget schema migration request pool history changed"
                        )
                    continue
                if (
                    historical_pool.max_attempts != int(row["max_attempts"])
                    or historical_pool.per_attempt_maximum != maximum
                ):
                    raise BudgetLedgerError("budget schema migration request pool history changed")
                candidate_rate = contract.role_rates[role]
                if original_rate is None:
                    original_rate = candidate_rate
                elif candidate_rate != original_rate:
                    raise BudgetLedgerError("budget schema migration request pool binding changed")
            if original_rate is None:
                raise BudgetLedgerError("budget schema migration cannot bind a request pool")
            connection.execute(
                """INSERT INTO request_pool_limits_v2 VALUES (
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                   )""",
                (
                    str(row["account_id"]),
                    str(row["stage"]),
                    str(row["product_id"]),
                    role,
                    int(row["max_attempts"]),
                    maximum.input_tokens,
                    maximum.output_tokens,
                    maximum.cost_minor_units,
                    original_rate.model_role_identity_hash,
                    role_rate_digest(original_rate),
                ),
            )
        new_rows = connection.execute(
            """SELECT account_id,stage,product_id,role,max_attempts,
                      max_input,max_output,max_cost
               FROM request_pool_limits_v2
               ORDER BY account_id,stage,product_id,role"""
        ).fetchall()
        if [tuple(row) for row in new_rows] != [tuple(row) for row in old_rows]:
            raise BudgetLedgerError("budget schema migration did not preserve pool rows")
        if connection.execute("PRAGMA foreign_key_check(request_pool_limits_v2)").fetchall():
            raise BudgetLedgerError("budget schema migration pool integrity failed")
        connection.execute("DROP TABLE request_pool_limits")
        connection.execute("ALTER TABLE request_pool_limits_v2 RENAME TO request_pool_limits")

    def _migrate_canary_claim_schema(self, connection: sqlite3.Connection, version: int) -> None:
        columns = self._table_columns(connection, "canary_capability_claims")
        if not columns:
            if version in {
                _PRE_INFRASTRUCTURE_SCHEMA_VERSION,
                _PRE_FINAL_TOPOLOGY_SCHEMA_VERSION,
                _PRE_RECEIPT_ANNEX_SCHEMA_VERSION,
                _PRE_PROVIDER_CAP_SIDECAR_SCHEMA_VERSION,
                _SCHEMA_VERSION,
            }:
                raise BudgetLedgerError("budget canary claim table is missing")
            self._create_canary_claim_table(connection)
            return
        if columns != _CANARY_CLAIM_COLUMNS or not self._canary_claim_schema_is_current(connection):
            raise BudgetLedgerError("budget canary claim schema is invalid")

    @staticmethod
    def _create_infrastructure_schema(connection: sqlite3.Connection) -> None:
        connection.execute(_INFRASTRUCTURE_AUTHORIZATION_TABLE_SQL)
        connection.execute(_INFRASTRUCTURE_RESERVE_TABLE_SQL)
        connection.execute(_DEPLOYMENT_ROLE_BINDING_TABLE_SQL)

    def _migrate_infrastructure_schema(
        self,
        connection: sqlite3.Connection,
        version: int,
    ) -> None:
        actual = {
            "infrastructure_authorizations": self._table_columns(
                connection, "infrastructure_authorizations"
            ),
            "infrastructure_reserves": self._table_columns(connection, "infrastructure_reserves"),
            "deployment_role_bindings": self._table_columns(connection, "deployment_role_bindings"),
        }
        present = {name for name, columns in actual.items() if columns}
        if version == _PRE_FINAL_TOPOLOGY_SCHEMA_VERSION and present == {
            "infrastructure_authorizations",
            "infrastructure_reserves",
        }:
            self._migrate_a_v5_infrastructure_schema(connection, actual)
            return
        if not present:
            if version in {
                _PRE_FINAL_TOPOLOGY_SCHEMA_VERSION,
                _PRE_RECEIPT_ANNEX_SCHEMA_VERSION,
                _PRE_PROVIDER_CAP_SIDECAR_SCHEMA_VERSION,
                _SCHEMA_VERSION,
            }:
                raise BudgetLedgerError("budget infrastructure schema is missing")
            self._create_infrastructure_schema(connection)
            return
        if present != frozenset(actual):
            raise BudgetLedgerError("budget infrastructure schema is incomplete")
        expected_columns = {
            "infrastructure_authorizations": _INFRASTRUCTURE_AUTHORIZATION_COLUMNS,
            "infrastructure_reserves": _INFRASTRUCTURE_RESERVE_COLUMNS,
            "deployment_role_bindings": _DEPLOYMENT_ROLE_BINDING_COLUMNS,
        }
        if actual != expected_columns:
            raise BudgetLedgerError("budget infrastructure schema has drifted columns")
        expected_sql = {
            "infrastructure_authorizations": _INFRASTRUCTURE_AUTHORIZATION_TABLE_SQL,
            "infrastructure_reserves": _INFRASTRUCTURE_RESERVE_TABLE_SQL,
            "deployment_role_bindings": _DEPLOYMENT_ROLE_BINDING_TABLE_SQL,
        }
        for table_name, sql in expected_sql.items():
            stored = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()
            if stored is None or str(stored["sql"]) != sql:
                raise BudgetLedgerError("budget infrastructure schema definition has drifted")
        if version not in {
            _PRE_FINAL_TOPOLOGY_SCHEMA_VERSION,
            _PRE_RECEIPT_ANNEX_SCHEMA_VERSION,
            _PRE_PROVIDER_CAP_SIDECAR_SCHEMA_VERSION,
            _SCHEMA_VERSION,
        }:
            raise BudgetLedgerError("budget infrastructure schema version does not match tables")

    @staticmethod
    def _migrate_a_v5_infrastructure_schema(
        connection: sqlite3.Connection,
        actual: Mapping[str, frozenset[str]],
    ) -> None:
        expected_columns = {
            "infrastructure_authorizations": _INFRASTRUCTURE_AUTHORIZATION_COLUMNS,
            "infrastructure_reserves": _A_V5_INFRASTRUCTURE_RESERVE_COLUMNS,
            "deployment_role_bindings": frozenset(),
        }
        if actual != expected_columns:
            raise BudgetLedgerError("budget infrastructure schema has drifted columns")
        for table_name, expected_sql in (
            (
                "infrastructure_authorizations",
                _A_V5_INFRASTRUCTURE_AUTHORIZATION_TABLE_SQL,
            ),
            ("infrastructure_reserves", _A_V5_INFRASTRUCTURE_RESERVE_TABLE_SQL),
        ):
            stored = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()
            if stored is None or str(stored["sql"]) != expected_sql:
                raise BudgetLedgerError("budget infrastructure schema definition has drifted")

        connection.execute(
            "ALTER TABLE infrastructure_authorizations RENAME TO infrastructure_authorizations_v5"
        )
        connection.execute(
            "ALTER TABLE infrastructure_reserves RENAME TO infrastructure_reserves_v5"
        )
        connection.execute(_INFRASTRUCTURE_AUTHORIZATION_TABLE_SQL)
        connection.execute(_INFRASTRUCTURE_RESERVE_TABLE_SQL)
        connection.execute(
            """INSERT INTO infrastructure_authorizations
               SELECT * FROM infrastructure_authorizations_v5"""
        )
        connection.execute(
            """INSERT INTO infrastructure_reserves (
                   reserve_id,account_id,run_identity,purpose,operation_id,
                   authorization_digest,pricing_evidence_digest,pricing_approval_digest,
                   provider_cap_evidence_digest,provider_cap_approval_digest,
                   provider_cap_max_cost,provider_cap_expires_at,provider,currency,
                   workspace_ref,project_ref,credential_ref,region,base_model,
                   request_plan,receipt_plan,input_tpm_quota,output_tpm_quota,
                   covers_fixed_infrastructure,covers_inference,cleanup_deadline,
                   max_cost,state,created_at
               )
               SELECT reserve_id,account_id,run_identity,purpose,operation_id,
                      authorization_digest,pricing_evidence_digest,pricing_approval_digest,
                      provider_cap_evidence_digest,provider_cap_approval_digest,
                      provider_cap_max_cost,provider_cap_expires_at,provider,currency,
                      workspace_ref,project_ref,credential_ref,region,base_model,
                      request_plan,receipt_plan,input_tpm_quota,output_tpm_quota,
                      covers_fixed_infrastructure,covers_inference,cleanup_deadline,
                      max_cost,state,created_at
               FROM infrastructure_reserves_v5"""
        )
        connection.execute(_DEPLOYMENT_ROLE_BINDING_TABLE_SQL)
        connection.execute("DROP TABLE infrastructure_reserves_v5")
        connection.execute("DROP TABLE infrastructure_authorizations_v5")

    def _migrate_infrastructure_provider_cap_evidence_schema(
        self,
        connection: sqlite3.Connection,
        version: int,
    ) -> None:
        columns = self._table_columns(connection, "infrastructure_provider_cap_evidence")
        if not columns:
            if version == _SCHEMA_VERSION:
                raise BudgetLedgerError("budget infrastructure provider-cap sidecar is missing")
            connection.execute(_INFRASTRUCTURE_PROVIDER_CAP_EVIDENCE_TABLE_SQL)
            return
        if columns != _INFRASTRUCTURE_PROVIDER_CAP_EVIDENCE_COLUMNS:
            raise BudgetLedgerError(
                "budget infrastructure provider-cap sidecar has drifted columns"
            )
        stored = connection.execute(
            """SELECT sql FROM sqlite_master
               WHERE type='table' AND name='infrastructure_provider_cap_evidence'"""
        ).fetchone()
        if stored is None or str(stored["sql"]) != _INFRASTRUCTURE_PROVIDER_CAP_EVIDENCE_TABLE_SQL:
            raise BudgetLedgerError("budget infrastructure provider-cap sidecar definition drifted")
        if version != _SCHEMA_VERSION:
            raise BudgetLedgerError("budget infrastructure provider-cap sidecar version mismatch")

    @staticmethod
    def _create_final_topology_schema(connection: sqlite3.Connection) -> None:
        connection.execute(_FINAL_TOPOLOGY_TABLE_SQL)

    def _migrate_final_topology_schema(
        self,
        connection: sqlite3.Connection,
        version: int,
    ) -> None:
        columns = self._table_columns(connection, "final_infrastructure_topologies")
        if not columns:
            if version in {_PRE_PROVIDER_CAP_SIDECAR_SCHEMA_VERSION, _SCHEMA_VERSION}:
                raise BudgetLedgerError("budget final topology schema is missing")
            self._create_final_topology_schema(connection)
            return
        if columns != _FINAL_TOPOLOGY_COLUMNS:
            raise BudgetLedgerError("budget final topology schema has drifted columns")
        stored = connection.execute(
            """SELECT sql FROM sqlite_master
               WHERE type='table' AND name='final_infrastructure_topologies'"""
        ).fetchone()
        if stored is None or str(stored["sql"]) != _FINAL_TOPOLOGY_TABLE_SQL:
            raise BudgetLedgerError("budget final topology schema definition has drifted")
        if version not in {
            _PRE_RECEIPT_ANNEX_SCHEMA_VERSION,
            _PRE_PROVIDER_CAP_SIDECAR_SCHEMA_VERSION,
            _SCHEMA_VERSION,
        }:
            raise BudgetLedgerError("budget final topology schema version does not match tables")

    @staticmethod
    def _create_receipt_annex_schema(connection: sqlite3.Connection) -> None:
        connection.execute(_RECEIPT_ANNEX_TABLE_SQL)

    def _migrate_receipt_annex_schema(
        self,
        connection: sqlite3.Connection,
        version: int,
    ) -> None:
        columns = self._table_columns(connection, "final_topology_receipt_annexes")
        if not columns:
            if version in {_PRE_PROVIDER_CAP_SIDECAR_SCHEMA_VERSION, _SCHEMA_VERSION}:
                raise BudgetLedgerError("budget receipt annex schema is missing")
            self._create_receipt_annex_schema(connection)
            return
        if columns != _RECEIPT_ANNEX_COLUMNS:
            raise BudgetLedgerError("budget receipt annex schema has drifted columns")
        stored = connection.execute(
            """SELECT sql FROM sqlite_master
               WHERE type='table' AND name='final_topology_receipt_annexes'"""
        ).fetchone()
        if stored is None or str(stored["sql"]) != _RECEIPT_ANNEX_TABLE_SQL:
            raise BudgetLedgerError("budget receipt annex schema definition has drifted")
        if version not in {_PRE_PROVIDER_CAP_SIDECAR_SCHEMA_VERSION, _SCHEMA_VERSION}:
            raise BudgetLedgerError("budget receipt annex schema version does not match tables")

    @staticmethod
    def _canary_claim_schema_is_current(connection: sqlite3.Connection) -> bool:
        stored_schema = connection.execute(
            """SELECT sql FROM sqlite_master
               WHERE type='table' AND name='canary_capability_claims'"""
        ).fetchone()
        if stored_schema is None or str(stored_schema["sql"]) != _CANARY_CLAIM_TABLE_SQL:
            return False
        table_info = connection.execute("PRAGMA table_info(canary_capability_claims)").fetchall()
        primary_key = tuple(
            str(row["name"])
            for row in sorted(table_info, key=lambda row: int(row["pk"]))
            if int(row["pk"]) > 0
        )
        if primary_key != (
            "account_id",
            "capability_digest",
            "target_stage",
            "target_product_id",
        ):
            return False

        foreign_key_groups: dict[int, list[sqlite3.Row]] = {}
        for row in connection.execute(
            "PRAGMA foreign_key_list(canary_capability_claims)"
        ).fetchall():
            foreign_key_groups.setdefault(int(row["id"]), []).append(row)
        actual_foreign_keys = frozenset(
            (
                str(rows[0]["table"]),
                tuple(
                    (str(row["from"]), str(row["to"]))
                    for row in sorted(rows, key=lambda row: int(row["seq"]))
                ),
            )
            for rows in foreign_key_groups.values()
        )
        expected_foreign_keys = frozenset(
            {
                ("budget_accounts", (("account_id", "account_id"),)),
                (
                    "product_limits",
                    (
                        ("account_id", "account_id"),
                        ("canary_stage", "stage"),
                        ("canary_product_id", "product_id"),
                    ),
                ),
                (
                    "product_limits",
                    (
                        ("account_id", "account_id"),
                        ("target_stage", "stage"),
                        ("target_product_id", "product_id"),
                    ),
                ),
            }
        )
        return actual_foreign_keys == expected_foreign_keys

    @staticmethod
    def _reconcile_legacy_settled_reservations(
        connection: sqlite3.Connection,
        account_id: str | None = None,
    ) -> None:
        """Conservatively materialize settled debits during migration or recovery."""

        if account_id is None:
            settled = connection.execute(
                """SELECT * FROM product_reservations
                   WHERE state='settled'
                   ORDER BY account_id,stage,product_id"""
            ).fetchall()
        else:
            settled = connection.execute(
                """SELECT * FROM product_reservations
                   WHERE account_id=? AND state='settled'
                   ORDER BY stage,product_id""",
                (account_id,),
            ).fetchall()
        overage_accounts: set[str] = set()
        for reservation in settled:
            reservation_account_id = str(reservation["account_id"])
            stage = str(reservation["stage"])
            product_id = str(reservation["product_id"])
            actual = BudgetLedger._attempt_charges(
                connection,
                reservation_account_id,
                stage,
                product_id,
            )
            maximum = _amounts_from_row(reservation, "max_input", "max_output", "max_cost")
            if not _fits(actual, maximum):
                overage_accounts.add(reservation_account_id)
            connection.execute(
                """UPDATE product_reservations
                   SET actual_input=?,actual_output=?,actual_cost=?
                   WHERE account_id=? AND stage=? AND product_id=?""",
                (
                    actual.input_tokens,
                    actual.output_tokens,
                    actual.cost_minor_units,
                    reservation_account_id,
                    stage,
                    product_id,
                ),
            )
        if account_id is None:
            accounts = connection.execute(
                "SELECT * FROM budget_accounts ORDER BY account_id"
            ).fetchall()
        else:
            accounts = [BudgetLedger._require_account(connection, account_id)]
        for account in accounts:
            current_account_id = str(account["account_id"])
            ceiling = _amounts_from_row(account, "ceiling_input", "ceiling_output", "ceiling_cost")
            if not _fits(BudgetLedger._occupied(connection, current_account_id), ceiling):
                overage_accounts.add(current_account_id)
        for overage_account_id in overage_accounts:
            connection.execute(
                "UPDATE budget_accounts SET overage=1 WHERE account_id=?",
                (overage_account_id,),
            )

    @contextmanager
    def _mutation(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _require_testing_mode(self) -> None:
        if self._testing_sentinel is not _TESTING_MODE_SENTINEL:
            raise BudgetLedgerError("private infrastructure helper requires testing mode")

    def _is_testing_mode(self) -> bool:
        return self._testing_sentinel is _TESTING_MODE_SENTINEL

    def _require_production_mode(self) -> None:
        if self._testing_sentinel is _TESTING_MODE_SENTINEL:
            raise BudgetLedgerError("verified final topology requires a production ledger")

    def _production_now(self) -> datetime:
        """Return the ledger-owned freshness boundary for production decisions."""

        self._require_production_mode()
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise BudgetLedgerError("production ledger clock must include a timezone")
        return now

    def _validate_infrastructure_capabilities(
        self,
        payload: ProvisioningAuthorizationPayload,
        *,
        pricing_capability: VerifiedPricingCapability,
        provider_capability: VerifiedProviderCapCapability,
        now: datetime,
    ) -> tuple[VerifiedPricingCapability, VerifiedProviderCapCapability]:
        try:
            if self._is_testing_mode():
                pricing = _require_verified_pricing_capability_for_testing(pricing_capability)
                provider_cap = _require_verified_provider_capability_for_testing(
                    provider_capability
                )
            else:
                pricing = require_verified_pricing_capability(pricing_capability)
                provider_cap = require_verified_provider_capability(provider_capability)
        except AuthorizationVerificationError as exc:
            raise BudgetLedgerError("verified infrastructure capabilities are required") from exc
        pricing_expected = (
            payload.provider,
            payload.currency,
            payload.workspace_ref,
            payload.project_ref,
            payload.credential_ref,
            payload.region,
            payload.base_model,
            payload.request_plan,
            payload.receipt_plan,
            payload.input_tpm_quota,
            payload.output_tpm_quota,
        )
        pricing_resource = (
            pricing.provider,
            pricing.currency,
            pricing.workspace_ref,
            pricing.project_ref,
            pricing.credential_ref,
            pricing.region,
            pricing.base_model,
            pricing.request_plan,
            pricing.receipt_plan,
            pricing.input_tpm_quota,
            pricing.output_tpm_quota,
        )
        cap_expected = (
            payload.provider,
            payload.currency,
            payload.workspace_ref,
            payload.project_ref,
            payload.credential_ref,
        )
        cap_resource = (
            provider_cap.provider,
            provider_cap.currency,
            provider_cap.workspace_ref,
            provider_cap.project_ref,
            provider_cap.credential_ref,
        )
        if pricing_resource != pricing_expected or cap_resource != cap_expected:
            raise BudgetLedgerError("infrastructure capability resource mismatch")
        if (
            pricing.evidence_digest != payload.pricing_evidence_digest
            or pricing.approval_digest != payload.pricing_approval_digest
            or pricing.fixed_cost_minor_units != payload.maximum_cost_minor_units
            or provider_cap.evidence_digest != payload.provider_cap_evidence_digest
            or provider_cap.approval_digest != payload.provider_cap_approval_digest
            or provider_cap.max_cost_minor_units != payload.provider_cap_max_cost_minor_units
            or provider_cap.expires_at != payload.provider_cap_expires_at
            or provider_cap.coverage != frozenset(payload.provider_cap_coverage)
        ):
            raise BudgetLedgerError("infrastructure price or cap capability mismatch")
        if now >= provider_cap.expires_at:
            raise BudgetLedgerError("verified provider cap capability is expired")
        if payload.maximum_cost_minor_units > provider_cap.max_cost_minor_units:
            raise BudgetLedgerError("infrastructure reserve exceeds provider cap")
        return pricing, provider_cap

    def reserve_provisioning_before_post(
        self,
        *,
        authorization: ProvisioningAuthorization,
        expected: ProvisioningAuthorizationPayload,
        pricing_evidence_bytes: bytes | None = None,
        pricing_approval: PricingEvidenceApproval | None = None,
        provider_cap_evidence_bytes: bytes | None = None,
        provider_cap_approval: ProviderCapApproval | None = None,
        **unsupported: object,
    ) -> InfrastructureCreatePermit:
        """Reverify signed price/cap evidence and occupy cost before provider POST."""

        if (
            unsupported
            or not isinstance(pricing_evidence_bytes, bytes)
            or not isinstance(pricing_approval, PricingEvidenceApproval)
            or not isinstance(provider_cap_evidence_bytes, bytes)
            or not isinstance(provider_cap_approval, ProviderCapApproval)
        ):
            raise BudgetLedgerError(
                "production provisioning requires signed pricing and provider-cap evidence"
            )

        def verify_fresh_boundary() -> tuple[
            str,
            VerifiedPricingCapability,
            VerifiedProviderCapCapability,
            datetime,
        ]:
            trusted_authorities = self._production_operational_authorities()
            now = self._production_now()
            try:
                pricing = verify_pricing_evidence(
                    pricing_evidence_bytes,
                    envelope=pricing_approval,
                    trusted_authorities=trusted_authorities,
                    expected_scope=expected.scope,
                    now=now,
                    fixed_duration_seconds=_ceil_timedelta_seconds(
                        expected.cleanup_deadline - expected.issued_at
                    ),
                    cost_window_start=expected.issued_at,
                )
                provider_cap = verify_provider_cap_evidence(
                    provider_cap_evidence_bytes,
                    envelope=provider_cap_approval,
                    trusted_authorities=trusted_authorities,
                    expected_scope=expected.scope,
                    now=now,
                )
                authorization_digest = verify_provisioning_authorization(
                    authorization,
                    expected=expected,
                    trusted_authorities=trusted_authorities,
                    now=now,
                )
            except AuthorizationVerificationError as exc:
                raise BudgetLedgerError(
                    f"signed provisioning price/cap evidence rejected: {exc}"
                ) from exc
            if pricing.fixed_cost_minor_units != expected.maximum_cost_minor_units:
                raise BudgetLedgerError(
                    "caller cost differs from mechanically derived pricing evidence"
                )
            pricing, provider_cap = self._validate_infrastructure_capabilities(
                expected,
                pricing_capability=pricing,
                provider_capability=provider_cap,
                now=now,
            )
            return authorization_digest, pricing, provider_cap, now

        authorization_digest, pricing, provider_cap, now = verify_fresh_boundary()
        snapshot, now, provider_cap = self._reserve_infrastructure(
            authorization=authorization,
            authorization_digest=authorization_digest,
            payload=expected,
            pricing_capability=pricing,
            provider_capability=provider_cap,
            recorded_at=now,
            provider_cap_evidence_bytes=provider_cap_evidence_bytes,
            provider_cap_approval_bytes=canonical_json_bytes(provider_cap_approval),
            freshness_revalidator=verify_fresh_boundary,
        )
        permit = InfrastructureCreatePermit(
            operation_id=expected.operation_id,
            reserve=snapshot,
            authorization_expires_at=expected.expires_at,
            provider_cap_expires_at=provider_cap.expires_at,
            cleanup_deadline=expected.cleanup_deadline,
        )
        permit.require_fresh(now)
        return permit

    def _reserve_provisioning_before_post_for_testing(
        self,
        *,
        authorization: ProvisioningAuthorization,
        expected: ProvisioningAuthorizationPayload,
        trusted_authorities: Mapping[str, TrustedAuthority],
        pricing_capability: VerifiedPricingCapability,
        provider_capability: VerifiedProviderCapCapability,
        now: datetime,
    ) -> InfrastructureCreatePermit:
        """Verify and occupy fixed cost before any future provider POST."""

        self._require_testing_mode()

        try:
            authorization_digest = verify_provisioning_authorization(
                authorization,
                expected=expected,
                trusted_authorities=trusted_authorities,
                now=now,
            )
        except AuthorizationVerificationError as exc:
            raise BudgetLedgerError(f"provisioning authorization rejected: {exc}") from exc
        pricing, provider_cap = self._validate_infrastructure_capabilities(
            expected,
            pricing_capability=pricing_capability,
            provider_capability=provider_capability,
            now=now,
        )
        snapshot, now, provider_cap = self._reserve_infrastructure(
            authorization=authorization,
            authorization_digest=authorization_digest,
            payload=expected,
            pricing_capability=pricing,
            provider_capability=provider_cap,
            recorded_at=now,
        )
        permit = InfrastructureCreatePermit(
            operation_id=expected.operation_id,
            reserve=snapshot,
            authorization_expires_at=expected.expires_at,
            provider_cap_expires_at=provider_cap.expires_at,
            cleanup_deadline=expected.cleanup_deadline,
        )
        permit.require_fresh(now)
        return permit

    def _reserve_infrastructure(
        self,
        *,
        authorization: InfrastructureAuthorization,
        authorization_digest: str,
        payload: ProvisioningAuthorizationPayload,
        pricing_capability: VerifiedPricingCapability,
        provider_capability: VerifiedProviderCapCapability,
        recorded_at: datetime,
        provider_cap_evidence_bytes: bytes | None = None,
        provider_cap_approval_bytes: bytes | None = None,
        freshness_revalidator: (
            Callable[
                [],
                tuple[
                    str,
                    VerifiedPricingCapability,
                    VerifiedProviderCapCapability,
                    datetime,
                ],
            ]
            | None
        ) = None,
    ) -> tuple[
        InfrastructureReserveSnapshot,
        datetime,
        VerifiedProviderCapCapability,
    ]:
        if (provider_cap_evidence_bytes is None) != (provider_cap_approval_bytes is None):
            raise BudgetLedgerError("infrastructure provider-cap sidecar is incomplete")
        with self._mutation() as connection:
            if freshness_revalidator is not None:
                (
                    authorization_digest,
                    pricing_capability,
                    provider_capability,
                    recorded_at,
                ) = freshness_revalidator()
            account_id = budget_account_identity(payload.run_identity, payload.purpose)
            envelope_json = canonical_json_bytes(authorization)
            provider_cap_key = self._provider_cap_key(provider_capability)
            existing = connection.execute(
                "SELECT * FROM infrastructure_reserves WHERE reserve_id=?",
                (payload.infrastructure_reserve_id,),
            ).fetchone()
            if existing is not None:
                stored_authorization = connection.execute(
                    """SELECT * FROM infrastructure_authorizations
                       WHERE authorization_digest=?""",
                    (str(existing["authorization_digest"]),),
                ).fetchone()
                if (
                    str(existing["authorization_digest"]) != authorization_digest
                    or str(existing["account_id"]) != account_id
                    or str(existing["operation_id"]) != payload.operation_id
                    or int(existing["max_cost"]) != payload.maximum_cost_minor_units
                    or stored_authorization is None
                    or bytes(stored_authorization["envelope_json"]) != envelope_json
                    or not self._stored_capabilities_match(
                        existing, pricing_capability, provider_capability
                    )
                ):
                    raise BudgetLedgerError("infrastructure reserve conflict")
                if provider_cap_evidence_bytes is not None:
                    sidecar = connection.execute(
                        """SELECT * FROM infrastructure_provider_cap_evidence
                           WHERE reserve_id=?""",
                        (payload.infrastructure_reserve_id,),
                    ).fetchone()
                    if (
                        sidecar is None
                        or bytes(sidecar["evidence_bytes"]) != provider_cap_evidence_bytes
                        or bytes(sidecar["approval_envelope_bytes"])
                        != provider_cap_approval_bytes
                        or str(sidecar["evidence_digest"]) != provider_capability.evidence_digest
                        or str(sidecar["approval_digest"]) != provider_capability.approval_digest
                    ):
                        raise BudgetLedgerError("infrastructure provider-cap sidecar conflict")
                total = self._shared_provider_cap_occupied_cost(
                    connection,
                    provider_cap_key,
                    expected_max_cost=provider_capability.max_cost_minor_units,
                    candidate_account_id=account_id,
                )
                if total > provider_capability.max_cost_minor_units:
                    raise BudgetLedgerError("infrastructure reserves exceed provider cap")
                return (
                    self._infrastructure_snapshot(connection, existing),
                    recorded_at,
                    provider_capability,
                )

            total = self._shared_provider_cap_occupied_cost(
                connection,
                provider_cap_key,
                expected_max_cost=provider_capability.max_cost_minor_units,
                candidate_account_id=account_id,
            )
            if total + payload.maximum_cost_minor_units > provider_capability.max_cost_minor_units:
                raise BudgetLedgerError("infrastructure reserves exceed provider cap")
            try:
                connection.execute(
                    """INSERT INTO infrastructure_authorizations VALUES (
                           ?, ?, ?, ?, ?, ?, ?, ?
                       )""",
                    (
                        authorization_digest,
                        authorization.domain,
                        envelope_json,
                        payload.run_identity,
                        payload.purpose,
                        payload.operation_id,
                        payload.infrastructure_reserve_id,
                        recorded_at.isoformat(),
                    ),
                )
                connection.execute(
                    """INSERT INTO infrastructure_reserves (
                           reserve_id,account_id,run_identity,purpose,operation_id,
                           authorization_digest,pricing_evidence_digest,
                           pricing_approval_digest,provider_cap_evidence_digest,
                           provider_cap_approval_digest,provider_cap_max_cost,
                           provider_cap_expires_at,provider,currency,workspace_ref,project_ref,
                           credential_ref,region,base_model,request_plan,receipt_plan,
                           input_tpm_quota,output_tpm_quota,covers_fixed_infrastructure,
                           covers_inference,cleanup_deadline,max_cost,state,created_at
                       ) VALUES (
                           ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?, ?, 'reserved', ?
                       )""",
                    (
                        payload.infrastructure_reserve_id,
                        account_id,
                        payload.run_identity,
                        payload.purpose,
                        payload.operation_id,
                        authorization_digest,
                        pricing_capability.evidence_digest,
                        pricing_capability.approval_digest,
                        provider_capability.evidence_digest,
                        provider_capability.approval_digest,
                        provider_capability.max_cost_minor_units,
                        provider_capability.expires_at.isoformat(),
                        provider_capability.provider,
                        provider_capability.currency,
                        provider_capability.workspace_ref,
                        provider_capability.project_ref,
                        provider_capability.credential_ref,
                        pricing_capability.region,
                        pricing_capability.base_model,
                        pricing_capability.request_plan,
                        pricing_capability.receipt_plan,
                        pricing_capability.input_tpm_quota,
                        pricing_capability.output_tpm_quota,
                        1,
                        1,
                        payload.cleanup_deadline.isoformat(),
                        payload.maximum_cost_minor_units,
                        recorded_at.isoformat(),
                    ),
                )
                if provider_cap_evidence_bytes is not None:
                    connection.execute(
                        """INSERT INTO infrastructure_provider_cap_evidence VALUES (
                               ?, ?, ?, ?, ?, ?
                           )""",
                        (
                            payload.infrastructure_reserve_id,
                            provider_cap_evidence_bytes,
                            provider_cap_approval_bytes,
                            provider_capability.evidence_digest,
                            provider_capability.approval_digest,
                            recorded_at.isoformat(),
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                raise BudgetLedgerError("infrastructure authorization conflict") from exc
            inserted = connection.execute(
                "SELECT * FROM infrastructure_reserves WHERE reserve_id=?",
                (payload.infrastructure_reserve_id,),
            ).fetchone()
            assert inserted is not None
            return (
                self._infrastructure_snapshot(connection, inserted),
                recorded_at,
                provider_capability,
            )

    def bind_final_infrastructure_contract(
        self,
        *,
        reserve_id: str,
        authorization: InfrastructureAuthorization,
        expected_authorization: ProvisioningAuthorizationPayload,
        receipt_capability: VerifiedReconciledDeploymentReceipt,
        roles: tuple[BudgetRole, ...],
        plan: RunAdmissionPlanPayload,
        contract: BudgetContract,
        envelope: BudgetApprovalEnvelope,
        expected_scope: str,
        pricing_evidence_bytes: bytes | None = None,
        pricing_approval: PricingEvidenceApproval | None = None,
        provider_cap_evidence_bytes: bytes | None = None,
        provider_cap_approval: ProviderCapApproval | None = None,
        **unsupported: object,
    ) -> InfrastructureReserveSnapshot:
        """Reject the non-atomic production single-reserve finalization path."""

        raise BudgetLedgerError("atomic production topology binding is required")

    def _bind_final_infrastructure_contract_for_testing(
        self,
        *,
        reserve_id: str,
        receipt_capability: VerifiedReconciledDeploymentReceipt,
        roles: tuple[BudgetRole, ...],
        plan: RunAdmissionPlanPayload,
        contract: BudgetContract,
        envelope: BudgetApprovalEnvelope,
        trusted_public_keys: Mapping[str, TrustedAuthority],
        expected_scope: str,
        authorized_roles: frozenset[str],
        now: datetime,
    ) -> InfrastructureReserveSnapshot:
        """Atomically bind final approval, receipt, deployment, and role references."""

        self._require_testing_mode()

        return self._bind_final_infrastructure_contract_transaction(
            reserve_id=reserve_id,
            receipt_capability=receipt_capability,
            roles=roles,
            plan=plan,
            contract=contract,
            envelope=envelope,
            trusted_public_keys=trusted_public_keys,
            expected_scope=expected_scope,
            authorized_roles=authorized_roles,
            now=now,
        )

    def bind_final_infrastructure_topology(
        self,
        *,
        strong: FinalInfrastructureBindingRequest,
        weak: FinalInfrastructureBindingRequest,
        plan: RunAdmissionPlanPayload,
        contract: BudgetContract,
        envelope: BudgetApprovalEnvelope,
        expected_scope: str,
        **unsupported: object,
    ) -> VerifiedFinalTopology:
        """Reverify both deployments, then bind their exact topology atomically."""

        if unsupported:
            raise BudgetLedgerError(
                "production final topology does not accept caller policy or time"
            )
        self._bind_final_infrastructure_topology_transaction(
            bindings=(
                (strong.reserve_id, strong.receipt_capability, strong.roles),
                (weak.reserve_id, weak.receipt_capability, weak.roles),
            ),
            plan=plan,
            contract=contract,
            envelope=envelope,
            expected_scope=expected_scope,
            production_requests=(strong, weak),
        )
        return self.require_fresh_final_topology(
            plan=plan,
            expected_scope=expected_scope,
        )

    @staticmethod
    def _production_receipt_annex(
        receipt: DeploymentReceipt,
        *,
        reconciliation_digest: str,
    ) -> tuple[str, bytes, Any]:
        """Read immutable ownership and reconciliation artifacts from the fixed store."""

        from insurance_harness.goldenset.admission_deployment import (
            DeploymentControlBlocked,
            DeploymentReceiptArtifact,
            DeploymentReconciliationEvidenceV1,
            _OperationStore,
        )

        store: _OperationStore | None = None
        try:
            store = _OperationStore(_PRODUCTION_DEPLOYMENT_OPERATION_ROOT)
            receipt_artifact_bytes = store.read(f"{receipt.content_digest}.receipt.json")
            reconciliation_artifact_bytes = store.read(
                f"{reconciliation_digest}.receipt-reconciliation.json"
            )
        except DeploymentControlBlocked as exc:
            raise BudgetLedgerError("production receipt artifact is unavailable") from exc
        finally:
            if store is not None:
                store.close()
        if receipt_artifact_bytes is None or reconciliation_artifact_bytes is None:
            raise BudgetLedgerError("production receipt reconciliation artifact is unavailable")
        try:
            receipt_artifact = DeploymentReceiptArtifact.model_validate_json(receipt_artifact_bytes)
            reconciliation_artifact = DeploymentReconciliationEvidenceV1.model_validate_json(
                reconciliation_artifact_bytes
            )
        except ValueError as exc:
            raise BudgetLedgerError(
                "production receipt reconciliation artifact is invalid"
            ) from exc
        if (
            canonical_json_bytes(receipt_artifact) != receipt_artifact_bytes
            or canonical_json_bytes(reconciliation_artifact) != reconciliation_artifact_bytes
            or receipt_artifact.receipt != receipt
            or receipt_artifact.receipt.content_digest != receipt.content_digest
            or receipt_artifact.remote_manifest_digest != receipt.content.remote_manifest_digest
            or reconciliation_artifact.receipt != receipt
            or reconciliation_artifact.remote_manifest != receipt_artifact.remote_manifest
            or reconciliation_artifact.reconciliation_digest != reconciliation_digest
        ):
            raise BudgetLedgerError("production receipt reconciliation artifact has drifted")
        annex_bytes = canonical_json_bytes(
            {
                "version": "insurancekb.run-admission.receipt-annex.v1",
                "receipt_artifact": receipt_artifact.model_dump(mode="json"),
                "reconciliation_artifact": reconciliation_artifact.model_dump(mode="json"),
            }
        )
        return (
            hashlib.sha256(_RECEIPT_ANNEX_DOMAIN + annex_bytes).hexdigest(),
            annex_bytes,
            reconciliation_artifact,
        )

    @staticmethod
    def _durable_final_deployment_evidence(
        request: FinalInfrastructureBindingRequest,
        *,
        receipt_annex_digest: str,
    ) -> _DurableFinalDeploymentEvidence:
        receipt = require_verified_reconciled_receipt(request.receipt_capability)
        return _DurableFinalDeploymentEvidence(
            reserve_id=request.reserve_id,
            roles=request.roles,
            pricing_evidence_json=request.pricing_evidence_bytes.decode("utf-8"),
            pricing_approval=request.pricing_approval,
            receipt_annex_digest=receipt_annex_digest,
            reconciliation_digest=receipt.reconciliation_digest,
        )

    @staticmethod
    def _final_topology_capability_values(
        *,
        requests: tuple[
            FinalInfrastructureBindingRequest,
            FinalInfrastructureBindingRequest,
        ],
        verified: tuple[
            tuple[str, VerifiedPricingCapability, VerifiedProviderCapCapability],
            tuple[str, VerifiedPricingCapability, VerifiedProviderCapCapability],
        ],
        proof: BudgetAdmissionProof,
        plan: RunAdmissionPlanPayload,
        contract: BudgetContract,
        envelope: BudgetApprovalEnvelope,
        expected_scope: str,
        now: datetime,
    ) -> Mapping[str, object]:
        deployments: list[FinalTopologyDeployment] = []
        expiries = [
            contract.price_expires_at,
            envelope.payload.expires_at,
            requests[0].provider_cap_approval.payload.expires_at,
            verified[0][2].expires_at,
        ]
        for request, (authorization_digest, pricing, _cap) in zip(requests, verified, strict=True):
            receipt_capability = require_verified_reconciled_receipt(
                request.receipt_capability, now=now
            )
            receipt = receipt_capability.receipt
            receipt_json = canonical_json_bytes(receipt)
            expiries.extend(
                (
                    request.expected_authorization.cleanup_deadline,
                    pricing.effective_until,
                    request.pricing_approval.payload.expires_at,
                    receipt_capability.expires_at,
                )
            )
            deployments.append(
                FinalTopologyDeployment(
                    reserve_id=request.reserve_id,
                    operation_id=request.expected_authorization.operation_id,
                    authorization_digest=authorization_digest,
                    pricing_evidence_digest=pricing.evidence_digest,
                    pricing_approval_digest=pricing.approval_digest,
                    maximum_cost_minor_units=(
                        request.expected_authorization.maximum_cost_minor_units
                    ),
                    deployed_model=receipt.content.deployed_model,
                    receipt_json_digest=hashlib.sha256(
                        _RECEIPT_JSON_DOMAIN + receipt_json
                    ).hexdigest(),
                    receipt_digest=receipt.content_digest,
                    remote_manifest_digest=receipt.content.remote_manifest_digest,
                    receipt=receipt,
                    roles=request.roles,
                    cleanup_deadline=(request.expected_authorization.cleanup_deadline),
                    reconciliation_digest=(receipt_capability.reconciliation_digest),
                    transport_identity_digest=(receipt_capability.transport_identity_digest),
                )
            )
        valid_until = min(expiries)
        if now >= valid_until:
            raise BudgetLedgerError("final topology durable evidence is stale")
        provider_cap = verified[0][2]
        strong, weak = deployments
        digest_values: dict[str, object] = {
            "account_id": budget_account_identity(plan.run_identity, plan.purpose),
            "run_identity": plan.run_identity,
            "purpose": plan.purpose,
            "scope": expected_scope,
            "plan_payload_hash": plan_payload_hash(plan),
            "budget_contract_hash": proof.contract_hash,
            "budget_approval_digest": proof.approval_digest,
            "budget_revision": proof.revision,
            "budget_approval_expires_at": envelope.payload.expires_at.isoformat(),
            "strong": strong.model_dump(mode="json"),
            "weak": weak.model_dump(mode="json"),
            "provider": provider_cap.provider,
            "currency": provider_cap.currency,
            "workspace_ref": provider_cap.workspace_ref,
            "project_ref": provider_cap.project_ref,
            "credential_ref": provider_cap.credential_ref,
            "provider_cap_evidence_digest": provider_cap.evidence_digest,
            "provider_cap_approval_digest": provider_cap.approval_digest,
            "provider_cap_coverage": sorted(provider_cap.coverage),
            "provider_cap_max_cost_minor_units": provider_cap.max_cost_minor_units,
            "provider_cap_expires_at": provider_cap.expires_at.isoformat(),
            "provider_cap_approval_expires_at": (
                requests[0].provider_cap_approval.payload.expires_at.isoformat()
            ),
            "valid_until": valid_until.isoformat(),
        }
        return MappingProxyType(
            {
                **digest_values,
                "topology_digest": hashlib.sha256(
                    _FINAL_TOPOLOGY_DOMAIN + canonical_json_bytes(digest_values)
                ).hexdigest(),
                "strong": strong,
                "weak": weak,
                "provider_cap_coverage": provider_cap.coverage,
                "provider_cap_expires_at": provider_cap.expires_at,
                "provider_cap_approval_expires_at": (
                    requests[0].provider_cap_approval.payload.expires_at
                ),
                "budget_approval_expires_at": envelope.payload.expires_at,
                "issued_at": now,
                "valid_until": valid_until,
            }
        )

    @staticmethod
    def _seal_final_topology(values: Mapping[str, object]) -> VerifiedFinalTopology:
        del values
        raise BudgetLedgerError(
            "in-memory final topology sealing is disabled; fresh durable reload is required"
        )

    def _verify_final_binding_request(
        self,
        request: FinalInfrastructureBindingRequest,
        *,
        plan: RunAdmissionPlanPayload,
        contract: BudgetContract,
        trusted_authorities: Mapping[str, TrustedAuthority],
        expected_scope: str,
        now: datetime,
    ) -> tuple[str, VerifiedPricingCapability, VerifiedProviderCapCapability]:
        expected = request.expected_authorization
        try:
            if not isinstance(request.authorization, ProvisioningAuthorization):
                raise AuthorizationVerificationError("provisioning authorization type mismatch")
            duration = _ceil_timedelta_seconds(expected.cleanup_deadline - expected.issued_at)
            segments: tuple[int, ...] | None = None
            cost_window_start = expected.issued_at
            authorization_digest = verify_provisioning_authorization(
                request.authorization,
                expected=expected,
                trusted_authorities=trusted_authorities,
                now=now,
            )
            pricing = verify_pricing_evidence(
                request.pricing_evidence_bytes,
                envelope=request.pricing_approval,
                trusted_authorities=trusted_authorities,
                expected_scope=expected_scope,
                now=now,
                fixed_duration_seconds=duration,
                cost_window_start=cost_window_start,
                fixed_duration_segments_seconds=segments,
            )
            provider_cap = verify_provider_cap_evidence(
                request.provider_cap_evidence_bytes,
                envelope=request.provider_cap_approval,
                trusted_authorities=trusted_authorities,
                expected_scope=expected_scope,
                now=now,
            )
            receipt = self._require_verified_receipt_for_authorization(
                request.receipt_capability, expected, now=now
            )
        except AuthorizationVerificationError as exc:
            raise BudgetLedgerError("final infrastructure signed evidence rejected") from exc
        if pricing.fixed_cost_minor_units != expected.maximum_cost_minor_units:
            raise BudgetLedgerError("final infrastructure cost differs from signed pricing")
        pricing, provider_cap = self._validate_infrastructure_capabilities(
            expected,
            pricing_capability=pricing,
            provider_capability=provider_cap,
            now=now,
        )
        self._require_receipt_matches_authorization(receipt, expected)
        for role in request.roles:
            role_plan = plan.model_roles.get(role)
            if not isinstance(role_plan, ModelRolePlan):
                raise BudgetLedgerError("deployment role topology is invalid")
            derive_role_rate_from_pricing(
                pricing,
                role_plan=role_plan,
                expected_provider=expected.provider,
                expected_currency=expected.currency,
                candidate=contract.role_rates.get(role),
            )
        return authorization_digest, pricing, provider_cap

    def _bind_final_infrastructure_contract_transaction(
        self,
        *,
        reserve_id: str,
        receipt_capability: VerifiedReconciledDeploymentReceipt,
        roles: tuple[BudgetRole, ...],
        plan: RunAdmissionPlanPayload,
        contract: BudgetContract,
        envelope: BudgetApprovalEnvelope,
        trusted_public_keys: Mapping[str, TrustedAuthority],
        expected_scope: str,
        authorized_roles: frozenset[str],
        now: datetime,
        expected_authorization_digest: str | None = None,
        pricing_capability: VerifiedPricingCapability | None = None,
        provider_capability: VerifiedProviderCapCapability | None = None,
        provider_cap_observed_at: datetime | None = None,
    ) -> InfrastructureReserveSnapshot:
        """Shared transaction; production must supply freshly verified capabilities."""

        if self._is_testing_mode():
            if any(
                value is not None
                for value in (
                    expected_authorization_digest,
                    pricing_capability,
                    provider_capability,
                    provider_cap_observed_at,
                )
            ):
                raise BudgetLedgerError("testing final bind cannot consume production evidence")
        else:
            if (
                not isinstance(expected_authorization_digest, str)
                or not expected_authorization_digest
                or pricing_capability is None
                or provider_capability is None
                or provider_cap_observed_at is None
            ):
                raise BudgetLedgerError(
                    "production final bind requires complete root-verified evidence"
                )
            (
                trusted_public_keys,
                authorized_roles,
                _provenance_roles,
                _canary_roles,
            ) = self._production_operational_configuration()
            now = self._production_now()

        try:
            receipt = (
                _require_verified_reconciled_receipt_for_testing(receipt_capability, now=now)
                if self._is_testing_mode()
                else require_verified_reconciled_receipt(receipt_capability, now=now)
            ).receipt
        except AuthorizationVerificationError as exc:
            raise BudgetLedgerError("verified reconciled receipt is required") from exc
        proof = verify_budget_admission_contract(
            plan=plan,
            contract=contract,
            envelope=envelope,
            trusted_public_keys=trusted_public_keys,
            expected_scope=expected_scope,
            authorized_roles=authorized_roles,
            now=now,
        )
        role_set = frozenset(roles)
        if role_set not in {
            frozenset({"annotator", "judge"}),
            frozenset({"weak_extractor"}),
        } or len(roles) != len(role_set):
            raise BudgetLedgerError("deployment role topology is invalid")
        account_id = budget_account_identity(plan.run_identity, plan.purpose)
        receipt_json = canonical_json_bytes(receipt)
        with self._mutation() as connection:
            reserve = connection.execute(
                "SELECT * FROM infrastructure_reserves WHERE reserve_id=?",
                (reserve_id,),
            ).fetchone()
            if reserve is None:
                raise BudgetLedgerError("infrastructure reserve not found")
            if (
                str(reserve["account_id"]) != account_id
                or str(reserve["run_identity"]) != plan.run_identity
                or str(reserve["purpose"]) != plan.purpose
            ):
                raise BudgetLedgerError("infrastructure reserve run identity conflict")
            authorization = self._stored_infrastructure_authorization(connection, reserve)
            payload = authorization.payload
            receipt = self._require_verified_receipt_for_authorization(
                receipt_capability,
                payload,
                now=now,
                testing=self._is_testing_mode(),
            )
            if expected_authorization_digest is not None and (
                str(reserve["authorization_digest"]) != expected_authorization_digest
                or infrastructure_authorization_digest(authorization)
                != expected_authorization_digest
                or pricing_capability is None
                or provider_capability is None
                or provider_cap_observed_at is None
                or not self._stored_capabilities_match(
                    reserve, pricing_capability, provider_capability
                )
            ):
                raise BudgetLedgerError(
                    "final signed infrastructure evidence conflicts with reserve"
                )
            if now >= payload.cleanup_deadline:
                raise BudgetLedgerError("infrastructure cleanup deadline has elapsed")
            if now >= payload.provider_cap_expires_at:
                raise BudgetLedgerError("infrastructure provider cap has expired")
            self._require_contract_matches_reserved_provider_cap(
                contract,
                reserve,
                observed_at=provider_cap_observed_at,
            )
            if (
                str(reserve["workspace_ref"]) != payload.workspace_ref
                or str(reserve["pricing_evidence_digest"]) != payload.pricing_evidence_digest
                or str(reserve["pricing_approval_digest"]) != payload.pricing_approval_digest
                or str(reserve["provider_cap_evidence_digest"])
                != payload.provider_cap_evidence_digest
                or str(reserve["provider_cap_approval_digest"])
                != payload.provider_cap_approval_digest
                or int(reserve["provider_cap_max_cost"])
                != payload.provider_cap_max_cost_minor_units
                or str(reserve["currency"]) != payload.currency
                or str(reserve["provider"]) != payload.provider
                or str(reserve["project_ref"]) != payload.project_ref
                or str(reserve["credential_ref"]) != payload.credential_ref
            ):
                raise BudgetLedgerError("final provider attestation resource mismatch")
            self._require_receipt_matches_authorization(receipt, authorization.payload)
            for role in roles:
                role_plan = plan.model_roles[role]
                if (
                    not isinstance(role_plan, ModelRolePlan)
                    or role_plan.provider != payload.provider
                    or role_plan.model_id != receipt.content.deployed_model
                    or role_plan.immutable_deployment_id != receipt.content.deployed_model
                ):
                    raise BudgetLedgerError(
                        "model_id, immutable_deployment_id and deployed_model must match"
                    )
            if str(reserve["state"]) == "bound":
                stored_roles = tuple(
                    str(row["role"])
                    for row in connection.execute(
                        """SELECT role FROM deployment_role_bindings
                           WHERE reserve_id=? ORDER BY role""",
                        (reserve_id,),
                    ).fetchall()
                )
                if (
                    str(reserve["deployed_model"]) != receipt.content.deployed_model
                    or str(reserve["receipt_digest"]) != receipt.content_digest
                    or str(reserve["remote_manifest_digest"])
                    != receipt.content.remote_manifest_digest
                    or bytes(reserve["receipt_json"]) != receipt_json
                    or str(reserve["final_approval_digest"]) != proof.approval_digest
                    or stored_roles != tuple(sorted(roles))
                ):
                    raise BudgetLedgerError("bound infrastructure replay conflict")
                return self._infrastructure_snapshot(connection, reserve)

            account = connection.execute(
                "SELECT * FROM budget_accounts WHERE account_id=?", (account_id,)
            ).fetchone()
            if account is None:
                self._insert_account(
                    connection,
                    account_id,
                    plan.run_identity,
                    plan.purpose,
                    contract,
                    envelope,
                    proof.approval_digest,
                    proof.contract_hash,
                )
            else:
                self._expand_account(
                    connection,
                    account,
                    contract,
                    envelope,
                    proof.approval_digest,
                    proof.contract_hash,
                )
            current_account = self._require_account(connection, account_id)
            product_max_row = connection.execute(
                "SELECT COALESCE(SUM(max_cost), 0) FROM product_limits WHERE account_id=?",
                (account_id,),
            ).fetchone()
            assert product_max_row is not None
            provider_cap_key = self._provider_cap_key_from_row(reserve)
            shared_occupied = self._shared_provider_cap_occupied_cost(
                connection,
                provider_cap_key,
                expected_max_cost=contract.provider_attestation.max_cost_minor_units,
                candidate_account_id=account_id,
            )
            current_product_occupied = self._product_occupied_cost(
                connection, frozenset({account_id})
            )
            all_fixed_and_product_maxima = (
                shared_occupied - current_product_occupied + int(product_max_row[0])
            )
            if all_fixed_and_product_maxima > contract.provider_attestation.max_cost_minor_units:
                raise BudgetLedgerError(
                    "infrastructure plus product maxima exceed final provider cap"
                )
            ceiling = _amounts_from_row(
                current_account, "ceiling_input", "ceiling_output", "ceiling_cost"
            )
            occupied = self._occupied(connection, account_id)
            if not _fits(occupied, ceiling):
                raise BudgetLedgerError("infrastructure reserve exceeds final budget ceiling")
            if occupied.cost_minor_units > contract.provider_attestation.max_cost_minor_units:
                raise BudgetLedgerError("infrastructure reserve exceeds final provider cap")
            try:
                connection.execute(
                    """UPDATE infrastructure_reserves
                       SET state='bound',deployed_model=?,receipt_digest=?,
                           remote_manifest_digest=?,receipt_json=?,
                           final_approval_digest=?,bound_at=?
                       WHERE reserve_id=? AND state='reserved'""",
                    (
                        receipt.content.deployed_model,
                        receipt.content_digest,
                        receipt.content.remote_manifest_digest,
                        receipt_json,
                        proof.approval_digest,
                        now.isoformat(),
                        reserve_id,
                    ),
                )
                for role in sorted(roles):
                    connection.execute(
                        "INSERT INTO deployment_role_bindings VALUES (?, ?, ?)",
                        (
                            account_id,
                            role,
                            reserve_id,
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                raise BudgetLedgerError("deployment or role reserve conflict") from exc
            bound = connection.execute(
                "SELECT * FROM infrastructure_reserves WHERE reserve_id=?", (reserve_id,)
            ).fetchone()
            assert bound is not None
            return self._infrastructure_snapshot(connection, bound)

    def _bind_final_infrastructure_topology_for_testing(
        self,
        *,
        bindings: tuple[
            tuple[
                str,
                VerifiedReconciledDeploymentReceipt,
                tuple[BudgetRole, ...],
            ],
            tuple[
                str,
                VerifiedReconciledDeploymentReceipt,
                tuple[BudgetRole, ...],
            ],
        ],
        plan: RunAdmissionPlanPayload,
        contract: BudgetContract,
        envelope: BudgetApprovalEnvelope,
        trusted_public_keys: Mapping[str, TrustedAuthority],
        expected_scope: str,
        authorized_roles: frozenset[str],
        now: datetime,
    ) -> tuple[InfrastructureReserveSnapshot, InfrastructureReserveSnapshot]:
        """Test seam for O8's all-or-nothing two-deployment final topology."""

        self._require_testing_mode()
        return self._bind_final_infrastructure_topology_transaction(
            bindings=bindings,
            plan=plan,
            contract=contract,
            envelope=envelope,
            trusted_public_keys=trusted_public_keys,
            expected_scope=expected_scope,
            authorized_roles=authorized_roles,
            now=now,
        ).snapshots

    def _bind_final_infrastructure_topology_transaction(
        self,
        *,
        bindings: tuple[
            tuple[
                str,
                VerifiedReconciledDeploymentReceipt,
                tuple[BudgetRole, ...],
            ],
            tuple[
                str,
                VerifiedReconciledDeploymentReceipt,
                tuple[BudgetRole, ...],
            ],
        ],
        plan: RunAdmissionPlanPayload,
        contract: BudgetContract,
        envelope: BudgetApprovalEnvelope,
        expected_scope: str,
        trusted_public_keys: Mapping[str, TrustedAuthority] | None = None,
        authorized_roles: frozenset[str] | None = None,
        now: datetime | None = None,
        verified_by_reserve: Mapping[
            str,
            tuple[str, VerifiedPricingCapability, VerifiedProviderCapCapability],
        ]
        | None = None,
        durable_record: _DurableFinalTopologyRecord | None = None,
        production_requests: tuple[
            FinalInfrastructureBindingRequest,
            FinalInfrastructureBindingRequest,
        ]
        | None = None,
    ) -> _FinalTopologyBindResult:
        """Bind strong+weak reserves under one SQLite transaction."""

        if self._is_testing_mode():
            if (
                production_requests is not None
                or verified_by_reserve is not None
                or durable_record is not None
            ):
                raise BudgetLedgerError("testing final topology cannot consume production evidence")
        else:
            if production_requests is None:
                raise BudgetLedgerError(
                    "production final topology requires signed binding requests"
                )
            if (
                trusted_public_keys is not None
                or authorized_roles is not None
                or now is not None
                or verified_by_reserve is not None
                or durable_record is not None
            ):
                raise BudgetLedgerError(
                    "production final topology rejects caller policy, time, or evidence"
                )
            strong_request, weak_request = production_requests
            bindings = (
                (
                    strong_request.reserve_id,
                    strong_request.receipt_capability,
                    strong_request.roles,
                ),
                (
                    weak_request.reserve_id,
                    weak_request.receipt_capability,
                    weak_request.roles,
                ),
            )

        account_id = budget_account_identity(plan.run_identity, plan.purpose)
        production_receipt_annexes: dict[str, tuple[str, str, bytes]] | None = None
        try:
            with self._mutation() as connection:
                if production_requests is not None:
                    self._require_production_mode()
                    (
                        trusted_public_keys,
                        authorized_roles,
                        _provenance_roles,
                        _canary_roles,
                    ) = self._production_operational_configuration()
                    now = self._production_now()
                    production_verified = tuple(
                        self._verify_final_binding_request(
                            request,
                            plan=plan,
                            contract=contract,
                            trusted_authorities=trusted_public_keys,
                            expected_scope=expected_scope,
                            now=now,
                        )
                        for request in production_requests
                    )
                    if (
                        production_verified[0][2].evidence_digest
                        != production_verified[1][2].evidence_digest
                        or production_verified[0][2].approval_digest
                        != production_verified[1][2].approval_digest
                    ):
                        raise BudgetLedgerError(
                            "strong and weak deployments require the same signed provider cap"
                        )
                    verified_by_reserve = {
                        request.reserve_id: request_verified
                        for request, request_verified in zip(
                            production_requests, production_verified, strict=True
                        )
                    }
                    if len(verified_by_reserve) != 2:
                        raise BudgetLedgerError("final infrastructure topology is invalid")
                    production_receipt_annexes = {}
                    for request in production_requests:
                        try:
                            verified_receipt = require_verified_reconciled_receipt(
                                request.receipt_capability,
                                now=now,
                            )
                        except AuthorizationVerificationError as exc:
                            raise BudgetLedgerError(
                                "verified reconciled receipt is required"
                            ) from exc
                        annex_digest, artifact_bytes, reconciliation_artifact = (
                            self._production_receipt_annex(
                                verified_receipt.receipt,
                                reconciliation_digest=(verified_receipt.reconciliation_digest),
                            )
                        )
                        if (
                            reconciliation_artifact.issuer != verified_receipt.issuer
                            or reconciliation_artifact.transport_identity_digest
                            != verified_receipt.transport_identity_digest
                            or reconciliation_artifact.run_identity != verified_receipt.run_identity
                            or reconciliation_artifact.purpose != verified_receipt.purpose
                            or reconciliation_artifact.scope != verified_receipt.scope
                            or reconciliation_artifact.observed_at != verified_receipt.observed_at
                            or reconciliation_artifact.expires_at != verified_receipt.expires_at
                            or reconciliation_artifact.provider_cap_evidence_digest
                            != verified_receipt.provider_cap_evidence_digest
                            or reconciliation_artifact.provider_cap_approval_digest
                            != verified_receipt.provider_cap_approval_digest
                        ):
                            raise BudgetLedgerError(
                                "production receipt reconciliation artifact has drifted"
                            )
                        production_receipt_annexes[request.reserve_id] = (
                            annex_digest,
                            verified_receipt.receipt.content_digest,
                            artifact_bytes,
                        )
                    try:
                        durable_record = _DurableFinalTopologyRecord(
                            version="insurancekb.run-admission.final-topology.v1",
                            plan=plan,
                            contract=contract,
                            budget_envelope=envelope,
                            expected_scope=expected_scope,
                            provider_cap_evidence_json=production_requests[
                                0
                            ].provider_cap_evidence_bytes.decode("utf-8"),
                            provider_cap_approval=production_requests[0].provider_cap_approval,
                            strong=self._durable_final_deployment_evidence(
                                production_requests[0],
                                receipt_annex_digest=production_receipt_annexes[
                                    production_requests[0].reserve_id
                                ][0],
                            ),
                            weak=self._durable_final_deployment_evidence(
                                production_requests[1],
                                receipt_annex_digest=production_receipt_annexes[
                                    production_requests[1].reserve_id
                                ][0],
                            ),
                        )
                    except (
                        AuthorizationVerificationError,
                        UnicodeDecodeError,
                        ValueError,
                    ) as exc:
                        raise BudgetLedgerError(
                            "final infrastructure topology evidence is not canonical"
                        ) from exc
                if trusted_public_keys is None or authorized_roles is None or now is None:
                    raise BudgetLedgerError("final topology verification policy is unavailable")
                normalized: list[tuple[str, DeploymentReceipt, tuple[BudgetRole, ...]]] = []
                capability_by_reserve = {
                    reserve_id: capability for reserve_id, capability, _roles in bindings
                }
                try:
                    for reserve_id, capability, roles in bindings:
                        verified_receipt = (
                            require_verified_reconciled_receipt(capability, now=now)
                            if production_requests is not None
                            else _require_verified_reconciled_receipt_for_testing(
                                capability, now=now
                            )
                        )
                        normalized.append(
                            (
                                reserve_id,
                                verified_receipt.receipt,
                                roles,
                            )
                        )
                except AuthorizationVerificationError as exc:
                    raise BudgetLedgerError("verified reconciled receipt is required") from exc
                if (
                    frozenset(normalized[0][2]) != frozenset({"annotator", "judge"})
                    or len(normalized[0][2]) != 2
                    or normalized[1][2] != ("weak_extractor",)
                    or normalized[0][0] == normalized[1][0]
                    or normalized[0][1].content.deployed_model
                    == normalized[1][1].content.deployed_model
                ):
                    raise BudgetLedgerError("final infrastructure topology is invalid")
                proof = verify_budget_admission_contract(
                    plan=plan,
                    contract=contract,
                    envelope=envelope,
                    trusted_public_keys=trusted_public_keys,
                    expected_scope=expected_scope,
                    authorized_roles=authorized_roles,
                    now=now,
                )
                rows: list[sqlite3.Row] = []
                for reserve_id, receipt, roles in normalized:
                    reserve = connection.execute(
                        "SELECT * FROM infrastructure_reserves WHERE reserve_id=?",
                        (reserve_id,),
                    ).fetchone()
                    if reserve is None:
                        raise BudgetLedgerError("infrastructure reserve not found")
                    authorization = self._stored_infrastructure_authorization(connection, reserve)
                    payload = authorization.payload
                    receipt = self._require_verified_receipt_for_authorization(
                        capability_by_reserve[reserve_id],
                        payload,
                        now=now,
                        testing=production_requests is None,
                    )
                    normalized[len(rows)] = (reserve_id, receipt, roles)
                    verified = (
                        None if verified_by_reserve is None else verified_by_reserve.get(reserve_id)
                    )
                    if verified_by_reserve is not None and (
                        verified is None
                        or str(reserve["authorization_digest"]) != verified[0]
                        or infrastructure_authorization_digest(authorization) != verified[0]
                        or not self._stored_capabilities_match(reserve, verified[1], verified[2])
                    ):
                        raise BudgetLedgerError(
                            "final signed infrastructure evidence conflicts with reserve"
                        )
                    if (
                        str(reserve["account_id"]) != account_id
                        or str(reserve["run_identity"]) != plan.run_identity
                        or str(reserve["purpose"]) != plan.purpose
                        or now >= payload.cleanup_deadline
                        or now >= payload.provider_cap_expires_at
                    ):
                        raise BudgetLedgerError("infrastructure reserve run or freshness conflict")
                    self._require_contract_matches_reserved_provider_cap(
                        contract,
                        reserve,
                        observed_at=(
                            None
                            if durable_record is None
                            else durable_record.provider_cap_approval.payload.evidence.observed_at
                        ),
                    )
                    self._require_receipt_matches_authorization(receipt, payload)
                    for role in roles:
                        role_plan = plan.model_roles[role]
                        if (
                            not isinstance(role_plan, ModelRolePlan)
                            or role_plan.provider != payload.provider
                            or role_plan.model_id != receipt.content.deployed_model
                            or role_plan.immutable_deployment_id != receipt.content.deployed_model
                        ):
                            raise BudgetLedgerError(
                                "model_id, immutable_deployment_id and deployed_model must match"
                            )
                    rows.append(reserve)

                account = connection.execute(
                    "SELECT * FROM budget_accounts WHERE account_id=?", (account_id,)
                ).fetchone()
                if account is None:
                    self._insert_account(
                        connection,
                        account_id,
                        plan.run_identity,
                        plan.purpose,
                        contract,
                        envelope,
                        proof.approval_digest,
                        proof.contract_hash,
                    )
                else:
                    self._expand_account(
                        connection,
                        account,
                        contract,
                        envelope,
                        proof.approval_digest,
                        proof.contract_hash,
                    )
                occupied = self._occupied(connection, account_id)
                current = self._require_account(connection, account_id)
                ceiling = _amounts_from_row(
                    current, "ceiling_input", "ceiling_output", "ceiling_cost"
                )
                if not _fits(occupied, ceiling):
                    raise BudgetLedgerError("infrastructure reserve exceeds final budget ceiling")
                if occupied.cost_minor_units > contract.provider_attestation.max_cost_minor_units:
                    raise BudgetLedgerError("infrastructure reserve exceeds final provider cap")
                provider_cap_keys = {self._provider_cap_key_from_row(row) for row in rows}
                if len(provider_cap_keys) != 1:
                    raise BudgetLedgerError("final infrastructure provider cap scope is ambiguous")
                provider_cap_key = next(iter(provider_cap_keys))
                shared_occupied = self._shared_provider_cap_occupied_cost(
                    connection,
                    provider_cap_key,
                    expected_max_cost=contract.provider_attestation.max_cost_minor_units,
                    candidate_account_id=account_id,
                )
                product_max_row = connection.execute(
                    "SELECT COALESCE(SUM(max_cost), 0) FROM product_limits WHERE account_id=?",
                    (account_id,),
                ).fetchone()
                assert product_max_row is not None
                current_product_occupied = self._product_occupied_cost(
                    connection, frozenset({account_id})
                )
                if (
                    shared_occupied - current_product_occupied + int(product_max_row[0])
                    > contract.provider_attestation.max_cost_minor_units
                ):
                    raise BudgetLedgerError(
                        "infrastructure plus product maxima exceed final provider cap"
                    )

                results: list[InfrastructureReserveSnapshot] = []
                for reserve, (_, receipt, roles) in zip(rows, normalized, strict=True):
                    receipt_json = canonical_json_bytes(receipt)
                    if str(reserve["state"]) == "bound":
                        stored_roles = tuple(
                            str(row["role"])
                            for row in connection.execute(
                                """SELECT role FROM deployment_role_bindings
                                   WHERE reserve_id=? ORDER BY role""",
                                (str(reserve["reserve_id"]),),
                            ).fetchall()
                        )
                        if (
                            str(reserve["deployed_model"]) != receipt.content.deployed_model
                            or str(reserve["receipt_digest"]) != receipt.content_digest
                            or str(reserve["remote_manifest_digest"])
                            != receipt.content.remote_manifest_digest
                            or bytes(reserve["receipt_json"]) != receipt_json
                            or str(reserve["final_approval_digest"]) != proof.approval_digest
                            or stored_roles != tuple(sorted(roles))
                        ):
                            raise BudgetLedgerError("bound infrastructure replay conflict")
                    else:
                        connection.execute(
                            """UPDATE infrastructure_reserves
                               SET state='bound',deployed_model=?,receipt_digest=?,
                                   remote_manifest_digest=?,receipt_json=?,
                                   final_approval_digest=?,bound_at=?
                               WHERE reserve_id=? AND state='reserved'""",
                            (
                                receipt.content.deployed_model,
                                receipt.content_digest,
                                receipt.content.remote_manifest_digest,
                                receipt_json,
                                proof.approval_digest,
                                now.isoformat(),
                                str(reserve["reserve_id"]),
                            ),
                        )
                        for role in sorted(roles):
                            connection.execute(
                                "INSERT INTO deployment_role_bindings VALUES (?, ?, ?)",
                                (account_id, role, str(reserve["reserve_id"])),
                            )
                    bound = connection.execute(
                        "SELECT * FROM infrastructure_reserves WHERE reserve_id=?",
                        (str(reserve["reserve_id"]),),
                    ).fetchone()
                    assert bound is not None
                    results.append(self._infrastructure_snapshot(connection, bound))
                if durable_record is not None:
                    if production_receipt_annexes is None:
                        raise BudgetLedgerError("production receipt annexes are unavailable")
                    for reserve_id, _receipt, _roles in normalized:
                        annex_digest, receipt_digest, artifact_bytes = production_receipt_annexes[
                            reserve_id
                        ]
                        existing_annex = connection.execute(
                            """SELECT * FROM final_topology_receipt_annexes
                               WHERE reserve_id=?""",
                            (reserve_id,),
                        ).fetchone()
                        annex_values = (
                            annex_digest,
                            reserve_id,
                            receipt_digest,
                            artifact_bytes,
                        )
                        if existing_annex is None:
                            connection.execute(
                                """INSERT INTO final_topology_receipt_annexes
                                   VALUES (?, ?, ?, ?, ?)""",
                                (*annex_values, now.isoformat()),
                            )
                        elif (
                            str(existing_annex["annex_digest"]),
                            str(existing_annex["reserve_id"]),
                            str(existing_annex["receipt_digest"]),
                            bytes(existing_annex["artifact_json"]),
                        ) != annex_values:
                            raise BudgetLedgerError("durable receipt annex replay conflict")
                    topology_json = canonical_json_bytes(durable_record)
                    topology_digest = hashlib.sha256(
                        _FINAL_TOPOLOGY_DOMAIN + topology_json
                    ).hexdigest()
                    existing_topology = connection.execute(
                        """SELECT * FROM final_infrastructure_topologies
                           WHERE account_id=?""",
                        (account_id,),
                    ).fetchone()
                    topology_values = (
                        normalized[0][0],
                        normalized[1][0],
                        topology_json,
                        topology_digest,
                    )
                    if existing_topology is None:
                        connection.execute(
                            """INSERT INTO final_infrastructure_topologies
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (
                                account_id,
                                *topology_values,
                                now.isoformat(),
                            ),
                        )
                    elif (
                        str(existing_topology["strong_reserve_id"]),
                        str(existing_topology["weak_reserve_id"]),
                        bytes(existing_topology["topology_json"]),
                        str(existing_topology["topology_digest"]),
                    ) != topology_values:
                        raise BudgetLedgerError(
                            "durable final infrastructure topology replay conflict"
                        )
                return _FinalTopologyBindResult(
                    snapshots=cast(
                        tuple[
                            InfrastructureReserveSnapshot,
                            InfrastructureReserveSnapshot,
                        ],
                        tuple(results),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise BudgetLedgerError("final infrastructure topology bind failed") from exc

    def require_fresh_final_topology(
        self,
        *,
        plan: RunAdmissionPlanPayload,
        expected_scope: str,
    ) -> VerifiedFinalTopology:
        """Rebuild a sealed capability from exact production ledger state."""

        self._require_production_mode()
        account_id = budget_account_identity(plan.run_identity, plan.purpose)
        expected_plan_digest = plan_payload_hash(plan)
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            account = connection.execute(
                "SELECT * FROM budget_accounts WHERE account_id=?",
                (account_id,),
            ).fetchone()
            if (
                account is None
                or str(account["run_identity"]) != plan.run_identity
                or str(account["purpose"]) != plan.purpose
                or bool(account["overage"])
            ):
                raise BudgetLedgerError("final topology budget account is unavailable")
            approval = connection.execute(
                """SELECT plan_payload_hash,contract_hash,contract_json,approval_digest
                   FROM budget_approvals WHERE account_id=? AND revision=?""",
                (account_id, int(account["current_revision"])),
            ).fetchone()
            if (
                approval is None
                or str(approval["approval_digest"]) != str(account["approval_digest"])
                or str(approval["plan_payload_hash"]) != expected_plan_digest
                or str(approval["contract_hash"]) != plan.budget_contract_hash
            ):
                raise BudgetLedgerError("final topology budget approval has drifted")
            try:
                contract = BudgetContract.model_validate_json(bytes(approval["contract_json"]))
            except (TypeError, ValueError) as exc:
                raise BudgetLedgerError("final topology budget contract is invalid") from exc
            if budget_contract_hash(contract) != str(approval["contract_hash"]):
                raise BudgetLedgerError("final topology budget contract has drifted")

            topology_row = connection.execute(
                """SELECT * FROM final_infrastructure_topologies
                   WHERE account_id=?""",
                (account_id,),
            ).fetchone()
            if topology_row is None:
                raise BudgetLedgerError("signed durable final topology evidence is unavailable")
            topology_json = bytes(topology_row["topology_json"])
            topology_digest = hashlib.sha256(_FINAL_TOPOLOGY_DOMAIN + topology_json).hexdigest()
            if topology_digest != str(topology_row["topology_digest"]):
                raise BudgetLedgerError("durable final topology digest has drifted")
            try:
                durable_record = _DurableFinalTopologyRecord.model_validate_json(topology_json)
            except (TypeError, ValueError) as exc:
                raise BudgetLedgerError("durable final topology record is invalid") from exc
            if (
                canonical_json_bytes(durable_record) != topology_json
                or durable_record.plan != plan
                or durable_record.contract != contract
                or durable_record.expected_scope != expected_scope
                or durable_record.strong.reserve_id != str(topology_row["strong_reserve_id"])
                or durable_record.weak.reserve_id != str(topology_row["weak_reserve_id"])
            ):
                raise BudgetLedgerError("durable final topology record has drifted")
            now = self._production_now()
            (
                trusted_authorities,
                budget_roles,
                _provenance_roles,
                _canary_roles,
            ) = self._production_operational_configuration()
            try:
                fresh_budget_proof = verify_budget_admission_contract(
                    plan=plan,
                    contract=contract,
                    envelope=durable_record.budget_envelope,
                    trusted_public_keys=trusted_authorities,
                    expected_scope=expected_scope,
                    authorized_roles=budget_roles,
                    now=now,
                )
                fresh_provider_cap = verify_provider_cap_evidence(
                    durable_record.provider_cap_evidence_json.encode("utf-8"),
                    envelope=durable_record.provider_cap_approval,
                    trusted_authorities=trusted_authorities,
                    expected_scope=expected_scope,
                    now=now,
                )
            except (ApprovalVerificationError, AuthorizationVerificationError) as exc:
                raise BudgetLedgerError(
                    "signed durable final topology evidence is stale or invalid"
                ) from exc
            if fresh_budget_proof.approval_digest != str(
                account["approval_digest"]
            ) or fresh_budget_proof.contract_hash != str(approval["contract_hash"]):
                raise BudgetLedgerError("durable final budget proof has drifted")
            expected_transport_identity_digest = _transport_identity_digest_for_provider_cap(
                fresh_provider_cap
            )

            role_rows = connection.execute(
                """SELECT role,reserve_id FROM deployment_role_bindings
                   WHERE account_id=? ORDER BY role""",
                (account_id,),
            ).fetchall()
            role_map = {str(row["role"]): str(row["reserve_id"]) for row in role_rows}
            if (
                set(role_map) != _REQUIRED_ROLES
                or len(role_rows) != 3
                or role_map["annotator"] != role_map["judge"]
                or role_map["annotator"] == role_map["weak_extractor"]
            ):
                raise BudgetLedgerError("final topology role binding is invalid")
            reserve_roles: tuple[tuple[str, tuple[BudgetRole, ...]], ...] = (
                (role_map["annotator"], ("annotator", "judge")),
                (role_map["weak_extractor"], ("weak_extractor",)),
            )
            deployments: list[FinalTopologyDeployment] = []
            reserve_rows: list[sqlite3.Row] = []
            cleanup_deadlines: list[datetime] = []
            pricing_expiries: list[datetime] = []
            authorization_expiries: list[datetime] = []
            authorization_rechecks: list[
                tuple[ProvisioningAuthorization, ProvisioningAuthorizationPayload, str]
            ] = []
            pricing_rechecks: list[
                tuple[str, PricingEvidenceApproval, int, datetime, str, str]
            ] = []
            durable_deployments = (
                durable_record.strong,
                durable_record.weak,
            )
            for (reserve_id, roles), durable_deployment in zip(
                reserve_roles,
                durable_deployments,
                strict=True,
            ):
                reserve = connection.execute(
                    "SELECT * FROM infrastructure_reserves WHERE reserve_id=?",
                    (reserve_id,),
                ).fetchone()
                if (
                    reserve is None
                    or str(reserve["state"]) != "bound"
                    or str(reserve["account_id"]) != account_id
                    or str(reserve["run_identity"]) != plan.run_identity
                    or str(reserve["purpose"]) != plan.purpose
                    or str(reserve["final_approval_digest"]) != str(account["approval_digest"])
                ):
                    raise BudgetLedgerError("final topology reserve is not durably bound")
                authorization = self._stored_infrastructure_authorization(connection, reserve)
                payload = authorization.payload
                if not isinstance(payload, ProvisioningAuthorizationPayload):
                    raise BudgetLedgerError("stored infrastructure authorization domain is invalid")
                pricing_duration = _ceil_timedelta_seconds(
                    payload.cleanup_deadline - payload.issued_at
                )
                pricing_segments: tuple[int, ...] | None = None
                pricing_start = payload.issued_at
                try:
                    fresh_pricing = verify_pricing_evidence(
                        durable_deployment.pricing_evidence_json.encode("utf-8"),
                        envelope=durable_deployment.pricing_approval,
                        trusted_authorities=trusted_authorities,
                        expected_scope=expected_scope,
                        now=now,
                        fixed_duration_seconds=pricing_duration,
                        cost_window_start=pricing_start,
                        fixed_duration_segments_seconds=pricing_segments,
                    )
                except AuthorizationVerificationError as exc:
                    raise BudgetLedgerError(
                        "signed durable deployment pricing is stale or invalid"
                    ) from exc
                if (
                    infrastructure_authorization_digest(authorization)
                    != str(reserve["authorization_digest"])
                    or payload.run_identity != plan.run_identity
                    or payload.purpose != plan.purpose
                    or payload.scope != expected_scope
                    or payload.operation_id != str(reserve["operation_id"])
                    or payload.infrastructure_reserve_id != reserve_id
                    or payload.workspace_ref != str(reserve["workspace_ref"])
                    or payload.project_ref != str(reserve["project_ref"])
                    or payload.credential_ref != str(reserve["credential_ref"])
                    or durable_deployment.reserve_id != reserve_id
                    or durable_deployment.roles != roles
                    or fresh_pricing.evidence_digest != str(reserve["pricing_evidence_digest"])
                    or fresh_pricing.approval_digest != str(reserve["pricing_approval_digest"])
                ):
                    raise BudgetLedgerError("final topology authorization has drifted")
                authorization_rechecks.append(
                    (
                        authorization,
                        payload,
                        str(reserve["authorization_digest"]),
                    )
                )
                authorization_expiries.append(payload.expires_at)
                pricing_rechecks.append(
                    (
                        durable_deployment.pricing_evidence_json,
                        durable_deployment.pricing_approval,
                        pricing_duration,
                        pricing_start,
                        fresh_pricing.evidence_digest,
                        fresh_pricing.approval_digest,
                    )
                )
                try:
                    receipt_json = bytes(reserve["receipt_json"])
                    receipt = DeploymentReceipt.model_validate_json(receipt_json)
                except (TypeError, ValueError) as exc:
                    raise BudgetLedgerError("final topology receipt is invalid") from exc
                annex = connection.execute(
                    """SELECT * FROM final_topology_receipt_annexes
                       WHERE annex_digest=?""",
                    (durable_deployment.receipt_annex_digest,),
                ).fetchone()
                if annex is None:
                    raise BudgetLedgerError("final topology receipt annex is unavailable")
                annex_bytes = bytes(annex["artifact_json"])
                (
                    artifact_digest,
                    production_artifact_bytes,
                    reconciliation_artifact,
                ) = self._production_receipt_annex(
                    receipt,
                    reconciliation_digest=durable_deployment.reconciliation_digest,
                )
                if (
                    str(annex["reserve_id"]) != reserve_id
                    or str(annex["receipt_digest"]) != receipt.content_digest
                    or str(annex["annex_digest"]) != durable_deployment.receipt_annex_digest
                    or hashlib.sha256(_RECEIPT_ANNEX_DOMAIN + annex_bytes).hexdigest()
                    != durable_deployment.receipt_annex_digest
                    or artifact_digest != durable_deployment.receipt_annex_digest
                    or production_artifact_bytes != annex_bytes
                ):
                    raise BudgetLedgerError("final topology receipt annex has drifted")
                if (
                    reconciliation_artifact.issuer != _TRUSTED_RECONCILIATION_ISSUER
                    or reconciliation_artifact.transport_identity_digest
                    != expected_transport_identity_digest
                    or reconciliation_artifact.reconciliation_digest
                    != durable_deployment.reconciliation_digest
                    or reconciliation_artifact.run_identity != plan.run_identity
                    or reconciliation_artifact.purpose != plan.purpose
                    or reconciliation_artifact.scope != expected_scope
                    or reconciliation_artifact.receipt != receipt
                    or reconciliation_artifact.receipt_digest != receipt.content_digest
                    or reconciliation_artifact.operation_id != receipt.content.operation_id
                    or reconciliation_artifact.reserve_id != reserve_id
                    or reconciliation_artifact.workspace_ref != receipt.content.workspace_ref
                    or reconciliation_artifact.project_ref != receipt.content.project_ref
                    or reconciliation_artifact.credential_ref != receipt.content.credential_ref
                    or reconciliation_artifact.provider_cap_evidence_digest
                    != fresh_provider_cap.evidence_digest
                    or reconciliation_artifact.provider_cap_approval_digest
                    != fresh_provider_cap.approval_digest
                    or reconciliation_artifact.remote_manifest_digest
                    != receipt.content.remote_manifest_digest
                    or reconciliation_artifact.observed_at.tzinfo is None
                    or reconciliation_artifact.observed_at.utcoffset() is None
                    or reconciliation_artifact.expires_at.tzinfo is None
                    or reconciliation_artifact.expires_at.utcoffset() is None
                    or reconciliation_artifact.observed_at >= reconciliation_artifact.expires_at
                    or now < reconciliation_artifact.observed_at
                    or reconciliation_artifact.expires_at > fresh_provider_cap.expires_at
                ):
                    raise BudgetLedgerError("final topology reconciliation provenance is invalid")
                if (
                    canonical_json_bytes(receipt) != receipt_json
                    or receipt.content_digest != str(reserve["receipt_digest"])
                    or receipt.content.deployed_model != str(reserve["deployed_model"])
                    or receipt.content.remote_manifest_digest
                    != str(reserve["remote_manifest_digest"])
                ):
                    raise BudgetLedgerError("final topology receipt has drifted")
                self._require_receipt_matches_authorization(receipt, payload)
                stored_roles = tuple(
                    cast(BudgetRole, str(row["role"]))
                    for row in connection.execute(
                        """SELECT role FROM deployment_role_bindings
                           WHERE account_id=? AND reserve_id=? ORDER BY role""",
                        (account_id, reserve_id),
                    ).fetchall()
                )
                if stored_roles != roles:
                    raise BudgetLedgerError("final topology reserve roles have drifted")
                for role in roles:
                    role_plan = plan.model_roles[role]
                    if (
                        role_plan.provider != str(reserve["provider"])
                        or role_plan.model_id != receipt.content.deployed_model
                        or role_plan.immutable_deployment_id != receipt.content.deployed_model
                    ):
                        raise BudgetLedgerError("final topology deployment role has drifted")
                cleanup_deadline = datetime.fromisoformat(str(reserve["cleanup_deadline"]))
                cleanup_deadlines.append(cleanup_deadline)
                pricing_expiries.extend(
                    (
                        fresh_pricing.effective_until,
                        durable_deployment.pricing_approval.payload.expires_at,
                    )
                )
                reserve_rows.append(reserve)
                receipt_json_digest = hashlib.sha256(
                    _RECEIPT_JSON_DOMAIN + receipt_json
                ).hexdigest()
                deployments.append(
                    FinalTopologyDeployment(
                        reserve_id=reserve_id,
                        operation_id=str(reserve["operation_id"]),
                        authorization_digest=str(reserve["authorization_digest"]),
                        pricing_evidence_digest=fresh_pricing.evidence_digest,
                        pricing_approval_digest=fresh_pricing.approval_digest,
                        maximum_cost_minor_units=int(reserve["max_cost"]),
                        deployed_model=receipt.content.deployed_model,
                        receipt_json_digest=receipt_json_digest,
                        receipt_digest=receipt.content_digest,
                        remote_manifest_digest=receipt.content.remote_manifest_digest,
                        receipt=receipt,
                        roles=roles,
                        cleanup_deadline=cleanup_deadline,
                        reconciliation_digest=(reconciliation_artifact.reconciliation_digest),
                        transport_identity_digest=(
                            reconciliation_artifact.transport_identity_digest
                        ),
                    )
                )

            cap_keys = {self._provider_cap_key_from_row(reserve) for reserve in reserve_rows}
            cap_evidence = {
                str(reserve["provider_cap_evidence_digest"]) for reserve in reserve_rows
            }
            cap_approvals = {
                str(reserve["provider_cap_approval_digest"]) for reserve in reserve_rows
            }
            cap_maxima = {int(reserve["provider_cap_max_cost"]) for reserve in reserve_rows}
            cap_expiries = {
                datetime.fromisoformat(str(reserve["provider_cap_expires_at"]))
                for reserve in reserve_rows
            }
            if not (
                len(cap_keys)
                == len(cap_evidence)
                == len(cap_approvals)
                == len(cap_maxima)
                == len(cap_expiries)
                == 1
            ):
                raise BudgetLedgerError("final topology provider cap has drifted")
            cap_key = next(iter(cap_keys))
            provider, currency, workspace, project, credential, coverage_tuple = cap_key
            coverage = frozenset(coverage_tuple)
            cap_digest = next(iter(cap_evidence))
            cap_approval_digest = next(iter(cap_approvals))
            cap_maximum = next(iter(cap_maxima))
            cap_expiry = next(iter(cap_expiries))
            for reserve in reserve_rows:
                self._require_contract_matches_reserved_provider_cap(
                    contract,
                    reserve,
                    observed_at=(durable_record.provider_cap_approval.payload.evidence.observed_at),
                )
            if (
                coverage != frozenset({"fixed_infrastructure", "inference"})
                or fresh_provider_cap.provider != provider
                or fresh_provider_cap.currency != currency
                or fresh_provider_cap.workspace_ref != workspace
                or fresh_provider_cap.project_ref != project
                or fresh_provider_cap.credential_ref != credential
                or fresh_provider_cap.coverage != coverage
                or fresh_provider_cap.evidence_digest != cap_digest
                or fresh_provider_cap.approval_digest != cap_approval_digest
                or fresh_provider_cap.max_cost_minor_units != cap_maximum
                or fresh_provider_cap.expires_at != cap_expiry
            ):
                raise BudgetLedgerError("final topology provider cap resource has drifted")
            shared_occupied = self._shared_provider_cap_occupied_cost(
                connection,
                cap_key,
                expected_max_cost=cap_maximum,
                candidate_account_id=account_id,
            )
            if shared_occupied > cap_maximum:
                raise BudgetLedgerError("final topology provider cap is exceeded")
            valid_until = min(
                cap_expiry,
                durable_record.provider_cap_approval.payload.expires_at,
                durable_record.budget_envelope.payload.expires_at,
                contract.price_expires_at,
                *cleanup_deadlines,
                *pricing_expiries,
                *authorization_expiries,
            )
            (
                final_authorities,
                final_budget_roles,
                _final_provenance_roles,
                _final_canary_roles,
            ) = self._production_operational_configuration()
            final_now = self._production_now()
            try:
                final_budget_proof = verify_budget_admission_contract(
                    plan=plan,
                    contract=contract,
                    envelope=durable_record.budget_envelope,
                    trusted_public_keys=final_authorities,
                    expected_scope=expected_scope,
                    authorized_roles=final_budget_roles,
                    now=final_now,
                )
                final_provider_cap = verify_provider_cap_evidence(
                    durable_record.provider_cap_evidence_json.encode("utf-8"),
                    envelope=durable_record.provider_cap_approval,
                    trusted_authorities=final_authorities,
                    expected_scope=expected_scope,
                    now=final_now,
                )
                for authorization, payload, expected_digest in authorization_rechecks:
                    if (
                        verify_provisioning_authorization(
                            authorization,
                            expected=payload,
                            trusted_authorities=final_authorities,
                            now=final_now,
                        )
                        != expected_digest
                    ):
                        raise AuthorizationVerificationError(
                            "durable infrastructure authorization digest drifted"
                        )
                for (
                    evidence_json,
                    pricing_approval,
                    duration,
                    pricing_start,
                    expected_evidence_digest,
                    expected_approval_digest,
                ) in pricing_rechecks:
                    pricing = verify_pricing_evidence(
                        evidence_json.encode("utf-8"),
                        envelope=pricing_approval,
                        trusted_authorities=final_authorities,
                        expected_scope=expected_scope,
                        now=final_now,
                        fixed_duration_seconds=duration,
                        cost_window_start=pricing_start,
                        fixed_duration_segments_seconds=None,
                    )
                    if (
                        pricing.evidence_digest != expected_evidence_digest
                        or pricing.approval_digest != expected_approval_digest
                    ):
                        raise AuthorizationVerificationError(
                            "durable deployment pricing digest drifted"
                        )
            except (ApprovalVerificationError, AuthorizationVerificationError) as exc:
                raise BudgetLedgerError(
                    "signed durable final topology evidence is stale or invalid"
                ) from exc
            if (
                final_budget_proof.approval_digest != fresh_budget_proof.approval_digest
                or final_budget_proof.contract_hash != fresh_budget_proof.contract_hash
                or final_provider_cap != fresh_provider_cap
            ):
                raise BudgetLedgerError("durable final topology authority has drifted")
            now = final_now
            if now >= valid_until:
                raise BudgetLedgerError("final topology durable evidence is stale")

            strong, weak = deployments
            digest_values: dict[str, object] = {
                "account_id": account_id,
                "run_identity": plan.run_identity,
                "purpose": plan.purpose,
                "scope": expected_scope,
                "plan_payload_hash": expected_plan_digest,
                "budget_contract_hash": str(approval["contract_hash"]),
                "budget_approval_digest": str(account["approval_digest"]),
                "budget_revision": int(account["current_revision"]),
                "budget_approval_expires_at": (
                    durable_record.budget_envelope.payload.expires_at.isoformat()
                ),
                "strong": strong.model_dump(mode="json"),
                "weak": weak.model_dump(mode="json"),
                "provider": provider,
                "currency": currency,
                "workspace_ref": workspace,
                "project_ref": project,
                "credential_ref": credential,
                "provider_cap_evidence_digest": cap_digest,
                "provider_cap_approval_digest": cap_approval_digest,
                "provider_cap_coverage": sorted(coverage),
                "provider_cap_max_cost_minor_units": cap_maximum,
                "provider_cap_expires_at": cap_expiry.isoformat(),
                "provider_cap_approval_expires_at": (
                    durable_record.provider_cap_approval.payload.expires_at.isoformat()
                ),
                "valid_until": valid_until.isoformat(),
            }
            capability = object.__new__(VerifiedFinalTopology)
            values: dict[str, object] = {
                **digest_values,
                "topology_digest": hashlib.sha256(
                    _FINAL_TOPOLOGY_DOMAIN + canonical_json_bytes(digest_values)
                ).hexdigest(),
                "strong": strong,
                "weak": weak,
                "provider_cap_coverage": coverage,
                "provider_cap_expires_at": cap_expiry,
                "provider_cap_approval_expires_at": (
                    durable_record.provider_cap_approval.payload.expires_at
                ),
                "budget_approval_expires_at": durable_record.budget_envelope.payload.expires_at,
                "issued_at": now,
                "valid_until": valid_until,
            }
            for name, value in values.items():
                object.__setattr__(capability, name, value)
            object.__setattr__(capability, "_seal", _FINAL_TOPOLOGY_SEAL)
            connection.commit()
            (
                post_commit_authorities,
                post_commit_budget_roles,
                _post_commit_provenance_roles,
                _post_commit_canary_roles,
            ) = self._production_operational_configuration()
            return_now = self._production_now()
            try:
                post_commit_budget_proof = verify_budget_admission_contract(
                    plan=plan,
                    contract=contract,
                    envelope=durable_record.budget_envelope,
                    trusted_public_keys=post_commit_authorities,
                    expected_scope=expected_scope,
                    authorized_roles=post_commit_budget_roles,
                    now=return_now,
                )
                post_commit_provider_cap = verify_provider_cap_evidence(
                    durable_record.provider_cap_evidence_json.encode("utf-8"),
                    envelope=durable_record.provider_cap_approval,
                    trusted_authorities=post_commit_authorities,
                    expected_scope=expected_scope,
                    now=return_now,
                )
                for authorization, payload, expected_digest in authorization_rechecks:
                    if (
                        verify_provisioning_authorization(
                            authorization,
                            expected=payload,
                            trusted_authorities=post_commit_authorities,
                            now=return_now,
                        )
                        != expected_digest
                    ):
                        raise AuthorizationVerificationError(
                            "durable infrastructure authorization digest drifted"
                        )
                for (
                    evidence_json,
                    pricing_approval,
                    duration,
                    pricing_start,
                    expected_evidence_digest,
                    expected_approval_digest,
                ) in pricing_rechecks:
                    pricing = verify_pricing_evidence(
                        evidence_json.encode("utf-8"),
                        envelope=pricing_approval,
                        trusted_authorities=post_commit_authorities,
                        expected_scope=expected_scope,
                        now=return_now,
                        fixed_duration_seconds=duration,
                        cost_window_start=pricing_start,
                        fixed_duration_segments_seconds=None,
                    )
                    if (
                        pricing.evidence_digest != expected_evidence_digest
                        or pricing.approval_digest != expected_approval_digest
                    ):
                        raise AuthorizationVerificationError(
                            "durable deployment pricing digest drifted"
                        )
            except (ApprovalVerificationError, AuthorizationVerificationError) as exc:
                raise BudgetLedgerError(
                    "signed durable final topology evidence is stale or invalid"
                ) from exc
            if (
                post_commit_budget_proof.approval_digest
                != final_budget_proof.approval_digest
                or post_commit_budget_proof.contract_hash != final_budget_proof.contract_hash
                or post_commit_provider_cap != final_provider_cap
            ):
                raise BudgetLedgerError("durable final topology authority has drifted")
            if return_now >= valid_until:
                raise BudgetLedgerError("final topology durable evidence is stale")
            _LEDGER_CAPABILITY_SNAPSHOT_REGISTRY.register(
                capability,
                domain=_FINAL_TOPOLOGY_SNAPSHOT_DOMAIN,
                snapshot=_final_topology_capability_snapshot(capability),
            )
            return require_verified_final_topology(
                capability,
                now=return_now,
                expected_plan_payload_hash=expected_plan_digest,
                expected_scope=expected_scope,
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def require_fresh_infrastructure_provider_capability(
        self,
        *,
        plan: RunAdmissionPlanPayload,
        expected_scope: str,
        reserve_id: str,
        **unsupported: object,
    ) -> VerifiedInfrastructureProviderCapCapability:
        """Freshly admit one reserved production cap without requiring final topology."""

        if unsupported:
            raise BudgetLedgerError(
                "fresh infrastructure provider cap rejects caller-controlled inputs"
            )
        self._require_production_mode()
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            reserve = connection.execute(
                "SELECT * FROM infrastructure_reserves WHERE reserve_id=?",
                (reserve_id,),
            ).fetchone()
            authorization_row = connection.execute(
                """SELECT a.* FROM infrastructure_authorizations AS a
                   JOIN infrastructure_reserves AS r
                     ON r.authorization_digest=a.authorization_digest
                   WHERE r.reserve_id=?""",
                (reserve_id,),
            ).fetchone()
            sidecar = connection.execute(
                """SELECT * FROM infrastructure_provider_cap_evidence
                   WHERE reserve_id=?""",
                (reserve_id,),
            ).fetchone()
            if reserve is None or authorization_row is None or sidecar is None:
                raise BudgetLedgerError(
                    "durable infrastructure provider-cap evidence is unavailable"
                )
            authorization_bytes = bytes(authorization_row["envelope_json"])
            approval_bytes = bytes(sidecar["approval_envelope_bytes"])
            evidence_bytes = bytes(sidecar["evidence_bytes"])
            try:
                authorization = ProvisioningAuthorization.model_validate_json(authorization_bytes)
                approval = ProviderCapApproval.model_validate_json(approval_bytes)
            except (TypeError, ValueError) as exc:
                raise BudgetLedgerError(
                    "durable infrastructure provider-cap evidence is invalid"
                ) from exc
            if (
                canonical_json_bytes(authorization) != authorization_bytes
                or canonical_json_bytes(approval) != approval_bytes
            ):
                raise BudgetLedgerError(
                    "durable infrastructure provider-cap bytes are non-canonical"
                )
            payload = authorization.payload
            trusted_authorities = self._production_operational_authorities()
            now = self._production_now()
            try:
                authorization_digest = verify_provisioning_authorization(
                    authorization,
                    expected=payload,
                    trusted_authorities=trusted_authorities,
                    now=now,
                )
                provider_cap = verify_provider_cap_evidence(
                    evidence_bytes,
                    envelope=approval,
                    trusted_authorities=trusted_authorities,
                    expected_scope=expected_scope,
                    now=now,
                )
            except AuthorizationVerificationError as exc:
                raise BudgetLedgerError(
                    "durable infrastructure provider-cap evidence is stale or invalid"
                ) from exc
            expected_coverage = frozenset(payload.provider_cap_coverage)
            expected_account_id = budget_account_identity(plan.run_identity, plan.purpose)
            recorded_at = str(reserve["created_at"])
            if (
                str(reserve["state"]) != "reserved"
                or reserve["deployed_model"] is not None
                or reserve["receipt_digest"] is not None
                or reserve["remote_manifest_digest"] is not None
                or reserve["receipt_json"] is not None
                or reserve["final_approval_digest"] is not None
                or reserve["bound_at"] is not None
                or str(authorization_row["recorded_at"]) != recorded_at
                or str(sidecar["recorded_at"]) != recorded_at
                or plan.run_identity != payload.run_identity
                or payload.run_identity != str(reserve["run_identity"])
                or plan.purpose != payload.purpose
                or payload.purpose != str(reserve["purpose"])
                or str(authorization_row["domain"]) != authorization.domain
                or str(authorization_row["run_identity"]) != payload.run_identity
                or str(authorization_row["purpose"]) != payload.purpose
                or str(authorization_row["operation_id"]) != payload.operation_id
                or payload.scope != expected_scope
                or payload.operation_id != str(reserve["operation_id"])
                or payload.infrastructure_reserve_id != reserve_id
                or str(authorization_row["reserve_id"]) != reserve_id
                or str(authorization_row["authorization_digest"]) != authorization_digest
                or str(reserve["authorization_digest"]) != authorization_digest
                or str(reserve["account_id"]) != expected_account_id
                or str(reserve["pricing_evidence_digest"])
                != payload.pricing_evidence_digest
                or str(reserve["pricing_approval_digest"])
                != payload.pricing_approval_digest
                or str(reserve["region"]) != payload.region
                or str(reserve["base_model"]) != payload.base_model
                or str(reserve["request_plan"]) != payload.request_plan
                or str(reserve["receipt_plan"]) != payload.receipt_plan
                or int(reserve["input_tpm_quota"]) != payload.input_tpm_quota
                or int(reserve["output_tpm_quota"]) != payload.output_tpm_quota
                or str(reserve["cleanup_deadline"]) != payload.cleanup_deadline.isoformat()
                or int(reserve["max_cost"]) != payload.maximum_cost_minor_units
                or provider_cap.provider != str(reserve["provider"])
                or provider_cap.provider != payload.provider
                or provider_cap.currency != str(reserve["currency"])
                or provider_cap.currency != payload.currency
                or provider_cap.workspace_ref != str(reserve["workspace_ref"])
                or provider_cap.workspace_ref != payload.workspace_ref
                or provider_cap.project_ref != str(reserve["project_ref"])
                or provider_cap.project_ref != payload.project_ref
                or provider_cap.credential_ref != str(reserve["credential_ref"])
                or provider_cap.credential_ref != payload.credential_ref
                or provider_cap.evidence_digest != str(reserve["provider_cap_evidence_digest"])
                or provider_cap.approval_digest != str(reserve["provider_cap_approval_digest"])
                or provider_cap.evidence_digest != str(sidecar["evidence_digest"])
                or provider_cap.approval_digest != str(sidecar["approval_digest"])
                or provider_cap.evidence_digest != payload.provider_cap_evidence_digest
                or provider_cap.approval_digest != payload.provider_cap_approval_digest
                or provider_cap.coverage != expected_coverage
                or provider_cap.max_cost_minor_units != int(reserve["provider_cap_max_cost"])
                or provider_cap.max_cost_minor_units
                != payload.provider_cap_max_cost_minor_units
                or provider_cap.expires_at.isoformat()
                != str(reserve["provider_cap_expires_at"])
                or provider_cap.expires_at != payload.provider_cap_expires_at
                or int(reserve["covers_fixed_infrastructure"]) != 1
                or int(reserve["covers_inference"]) != 1
            ):
                raise BudgetLedgerError("durable infrastructure provider-cap join has drifted")
            final_authorities = self._production_operational_authorities()
            final_now = self._production_now()
            try:
                final_authorization_digest = verify_provisioning_authorization(
                    authorization,
                    expected=payload,
                    trusted_authorities=final_authorities,
                    now=final_now,
                )
                final_provider_cap = verify_provider_cap_evidence(
                    evidence_bytes,
                    envelope=approval,
                    trusted_authorities=final_authorities,
                    expected_scope=expected_scope,
                    now=final_now,
                )
            except AuthorizationVerificationError as exc:
                raise BudgetLedgerError(
                    "durable infrastructure provider-cap evidence is stale or invalid"
                ) from exc
            if (
                final_authorization_digest != authorization_digest
                or final_provider_cap != provider_cap
            ):
                raise BudgetLedgerError(
                    "durable infrastructure provider-cap authority has drifted"
                )
            capability = object.__new__(VerifiedInfrastructureProviderCapCapability)
            values: dict[str, object] = {
                "run_identity": payload.run_identity,
                "purpose": payload.purpose,
                "scope": payload.scope,
                "operation_id": payload.operation_id,
                "reserve_id": reserve_id,
                "evidence_digest": provider_cap.evidence_digest,
                "approval_digest": provider_cap.approval_digest,
                "provider": provider_cap.provider,
                "currency": provider_cap.currency,
                "workspace_ref": provider_cap.workspace_ref,
                "project_ref": provider_cap.project_ref,
                "credential_ref": provider_cap.credential_ref,
                "coverage": provider_cap.coverage,
                "max_cost_minor_units": provider_cap.max_cost_minor_units,
                "expires_at": provider_cap.expires_at,
            }
            for name, value in values.items():
                object.__setattr__(capability, name, value)
            object.__setattr__(
                capability,
                "_seal",
                _INFRASTRUCTURE_PROVIDER_CAPABILITY_SEAL,
            )
            connection.commit()
            post_commit_authorities = self._production_operational_authorities()
            return_now = self._production_now()
            try:
                post_commit_authorization_digest = verify_provisioning_authorization(
                    authorization,
                    expected=payload,
                    trusted_authorities=post_commit_authorities,
                    now=return_now,
                )
                post_commit_provider_cap = verify_provider_cap_evidence(
                    evidence_bytes,
                    envelope=approval,
                    trusted_authorities=post_commit_authorities,
                    expected_scope=expected_scope,
                    now=return_now,
                )
            except AuthorizationVerificationError as exc:
                raise BudgetLedgerError(
                    "durable infrastructure provider-cap evidence is stale or invalid"
                ) from exc
            if (
                post_commit_authorization_digest != final_authorization_digest
                or post_commit_provider_cap != final_provider_cap
            ):
                raise BudgetLedgerError(
                    "durable infrastructure provider-cap authority has drifted"
                )
            if return_now >= min(payload.expires_at, provider_cap.expires_at):
                raise BudgetLedgerError(
                    "durable infrastructure provider-cap evidence is stale or invalid"
                )
            _LEDGER_CAPABILITY_SNAPSHOT_REGISTRY.register(
                capability,
                domain=_INFRASTRUCTURE_CAP_SNAPSHOT_DOMAIN,
                snapshot=_infrastructure_capability_snapshot(capability),
            )
            return require_verified_infrastructure_provider_capability(capability)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def require_fresh_topology_provider_capability(
        self,
        *,
        plan: RunAdmissionPlanPayload,
        expected_scope: str,
        reserve_id: str,
        **unsupported: object,
    ) -> VerifiedTopologyProviderCapCapability:
        """Issue a cap only from one exact deployment in a fresh final topology."""

        if unsupported:
            raise BudgetLedgerError(
                "fresh topology provider cap rejects caller-controlled inputs"
            )
        topology = self.require_fresh_final_topology(
            plan=plan,
            expected_scope=expected_scope,
        )
        deployments = tuple(
            deployment
            for deployment in (topology.strong, topology.weak)
            if deployment.reserve_id == reserve_id
        )
        if len(deployments) != 1:
            raise BudgetLedgerError("reserve is not uniquely bound by the fresh final topology")
        deployment = deployments[0]
        capability = object.__new__(VerifiedTopologyProviderCapCapability)
        values: dict[str, object] = {
            "topology_digest": topology.topology_digest,
            "run_identity": topology.run_identity,
            "purpose": topology.purpose,
            "scope": topology.scope,
            "operation_id": deployment.operation_id,
            "reserve_id": deployment.reserve_id,
            "evidence_digest": topology.provider_cap_evidence_digest,
            "approval_digest": topology.provider_cap_approval_digest,
            "provider": topology.provider,
            "currency": topology.currency,
            "workspace_ref": topology.workspace_ref,
            "project_ref": topology.project_ref,
            "credential_ref": topology.credential_ref,
            "coverage": topology.provider_cap_coverage,
            "max_cost_minor_units": topology.provider_cap_max_cost_minor_units,
            "expires_at": topology.provider_cap_expires_at,
        }
        for name, value in values.items():
            object.__setattr__(capability, name, value)
        object.__setattr__(capability, "_seal", _TOPOLOGY_PROVIDER_CAPABILITY_SEAL)
        _LEDGER_CAPABILITY_SNAPSHOT_REGISTRY.register(
            capability,
            domain=_TOPOLOGY_CAP_SNAPSHOT_DOMAIN,
            snapshot=_topology_capability_snapshot(capability),
        )
        return require_verified_topology_provider_capability(capability)

    def require_fresh_provider_capability(
        self,
        *,
        plan: RunAdmissionPlanPayload,
        expected_scope: str,
        **unsupported: object,
    ) -> VerifiedProviderCapCapability:
        """Reissue the exact signed provider cap bound to a fresh topology.

        The public boundary deliberately accepts neither caller-owned trust nor
        caller-owned time.  A production topology is revalidated first; then the
        durable signed cap sidecar is loaded again under the fixed root trust
        configuration and compared byte-for-fact with that topology.
        """

        if unsupported:
            raise BudgetLedgerError(
                "fresh provider cap rejects caller-controlled verification inputs"
            )
        topology = self.require_fresh_final_topology(
            plan=plan,
            expected_scope=expected_scope,
        )
        account_id = budget_account_identity(plan.run_identity, plan.purpose)
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            topology_row = connection.execute(
                """SELECT topology_json,topology_digest
                   FROM final_infrastructure_topologies WHERE account_id=?""",
                (account_id,),
            ).fetchone()
            if topology_row is None:
                raise BudgetLedgerError("signed durable final topology evidence is unavailable")
            topology_json = bytes(topology_row["topology_json"])
            if hashlib.sha256(_FINAL_TOPOLOGY_DOMAIN + topology_json).hexdigest() != str(
                topology_row["topology_digest"]
            ):
                raise BudgetLedgerError("durable final topology digest has drifted")
            try:
                durable_record = _DurableFinalTopologyRecord.model_validate_json(topology_json)
            except (TypeError, ValueError) as exc:
                raise BudgetLedgerError("durable final topology record is invalid") from exc
            if (
                canonical_json_bytes(durable_record) != topology_json
                or durable_record.plan != plan
                or durable_record.expected_scope != expected_scope
            ):
                raise BudgetLedgerError("durable final topology record has drifted")

            trusted_authorities = self._production_operational_authorities()
            now = self._production_now()
            require_verified_final_topology(
                topology,
                now=now,
                expected_plan_payload_hash=plan_payload_hash(plan),
                expected_scope=expected_scope,
            )
            try:
                provider_cap = verify_provider_cap_evidence(
                    durable_record.provider_cap_evidence_json.encode("utf-8"),
                    envelope=durable_record.provider_cap_approval,
                    trusted_authorities=trusted_authorities,
                    expected_scope=expected_scope,
                    now=now,
                )
            except AuthorizationVerificationError as exc:
                raise BudgetLedgerError("signed durable provider cap is stale or invalid") from exc
            if (
                provider_cap.provider != topology.provider
                or provider_cap.currency != topology.currency
                or provider_cap.workspace_ref != topology.workspace_ref
                or provider_cap.project_ref != topology.project_ref
                or provider_cap.credential_ref != topology.credential_ref
                or provider_cap.evidence_digest != topology.provider_cap_evidence_digest
                or provider_cap.approval_digest != topology.provider_cap_approval_digest
                or provider_cap.coverage != topology.provider_cap_coverage
                or provider_cap.max_cost_minor_units != topology.provider_cap_max_cost_minor_units
                or provider_cap.expires_at != topology.provider_cap_expires_at
                or durable_record.provider_cap_approval.payload.expires_at
                != topology.provider_cap_approval_expires_at
            ):
                raise BudgetLedgerError("durable provider cap has drifted from final topology")
            connection.commit()

            final_topology = self.require_fresh_final_topology(
                plan=plan,
                expected_scope=expected_scope,
            )
            if _final_topology_durable_snapshot(final_topology) != (
                _final_topology_durable_snapshot(topology)
            ):
                raise BudgetLedgerError("durable final topology changed during provider-cap load")
            final_authorities = self._production_operational_authorities()
            final_now = self._production_now()
            try:
                final_provider_cap = verify_provider_cap_evidence(
                    durable_record.provider_cap_evidence_json.encode("utf-8"),
                    envelope=durable_record.provider_cap_approval,
                    trusted_authorities=final_authorities,
                    expected_scope=expected_scope,
                    now=final_now,
                )
            except AuthorizationVerificationError as exc:
                raise BudgetLedgerError(
                    "signed durable provider cap is stale or invalid"
                ) from exc
            if final_provider_cap != provider_cap:
                raise BudgetLedgerError("durable provider-cap authority changed during load")
            return require_verified_provider_capability(final_provider_cap)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def infrastructure_reserve(self, reserve_id: str) -> InfrastructureReserveSnapshot:
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT * FROM infrastructure_reserves WHERE reserve_id=?", (reserve_id,)
            ).fetchone()
            if row is None:
                raise BudgetLedgerError("infrastructure reserve not found")
            snapshot = self._infrastructure_snapshot(connection, row)
            connection.commit()
            return snapshot
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _require_receipt_matches_authorization(
        receipt: DeploymentReceipt,
        payload: ProvisioningAuthorizationPayload,
    ) -> None:
        content = receipt.content
        if (
            content.operation_id != payload.operation_id
            or content.infrastructure_reserve_id != payload.infrastructure_reserve_id
            or content.workspace_ref != payload.workspace_ref
            or content.project_ref != payload.project_ref
            or content.credential_ref != payload.credential_ref
            or content.region != payload.region
            or content.base_model != payload.base_model
            or content.request_plan != payload.request_plan
            or content.receipt_plan != payload.receipt_plan
            or content.input_tpm != payload.input_tpm_quota
            or content.output_tpm != payload.output_tpm_quota
        ):
            raise BudgetLedgerError("deployment receipt does not match authorization")

    @staticmethod
    def _require_verified_receipt_for_authorization(
        capability: VerifiedReconciledDeploymentReceipt,
        payload: ProvisioningAuthorizationPayload,
        *,
        now: datetime,
        testing: bool = False,
    ) -> DeploymentReceipt:
        try:
            verified = (
                _require_verified_reconciled_receipt_for_testing(capability, now=now)
                if testing
                else require_verified_reconciled_receipt(capability, now=now)
            )
        except AuthorizationVerificationError as exc:
            raise BudgetLedgerError("verified reconciled receipt is stale or invalid") from exc
        if (
            verified.run_identity != payload.run_identity
            or verified.purpose != payload.purpose
            or verified.scope != payload.scope
            or verified.operation_id != payload.operation_id
            or verified.reserve_id != payload.infrastructure_reserve_id
            or verified.workspace_ref != payload.workspace_ref
            or verified.project_ref != payload.project_ref
            or verified.credential_ref != payload.credential_ref
            or verified.provider_cap_evidence_digest != payload.provider_cap_evidence_digest
            or verified.provider_cap_approval_digest != payload.provider_cap_approval_digest
            or verified.remote_manifest_digest != verified.receipt.content.remote_manifest_digest
        ):
            raise BudgetLedgerError(
                "verified receipt reconciliation does not match authorization or cap"
            )
        BudgetLedger._require_receipt_matches_authorization(verified.receipt, payload)
        return verified.receipt

    @staticmethod
    def _infrastructure_reserved_cost(
        connection: sqlite3.Connection,
        account_id: str,
    ) -> int:
        row = connection.execute(
            """SELECT COALESCE(SUM(max_cost), 0) FROM infrastructure_reserves
               WHERE account_id=? AND state IN ('reserved','bound')""",
            (account_id,),
        ).fetchone()
        assert row is not None
        return int(row[0])

    @staticmethod
    def _provider_cap_key(
        provider_cap: VerifiedProviderCapCapability,
    ) -> _ProviderCapKey:
        return (
            provider_cap.provider,
            provider_cap.currency,
            provider_cap.workspace_ref,
            provider_cap.project_ref,
            provider_cap.credential_ref,
            tuple(sorted(provider_cap.coverage)),
        )

    @staticmethod
    def _provider_cap_key_from_row(row: sqlite3.Row) -> _ProviderCapKey:
        coverage = tuple(
            sorted(
                name
                for name, column in (
                    ("fixed_infrastructure", "covers_fixed_infrastructure"),
                    ("inference", "covers_inference"),
                )
                if bool(row[column])
            )
        )
        return (
            str(row["provider"]),
            str(row["currency"]),
            str(row["workspace_ref"]),
            str(row["project_ref"]),
            str(row["credential_ref"]),
            coverage,
        )

    @staticmethod
    def _require_contract_matches_reserved_provider_cap(
        contract: BudgetContract,
        row: sqlite3.Row,
        *,
        observed_at: datetime | None = None,
    ) -> None:
        """Exact join between the signed inference contract and fixed-cost cap row."""

        attestation = contract.provider_attestation
        if (
            attestation.provider != str(row["provider"])
            or contract.currency != str(row["currency"])
            or attestation.workspace_ref != str(row["workspace_ref"])
            or attestation.project_ref != str(row["project_ref"])
            or attestation.credential_ref != str(row["credential_ref"])
            or attestation.evidence_digest != str(row["provider_cap_evidence_digest"])
            or attestation.max_cost_minor_units != int(row["provider_cap_max_cost"])
            or attestation.expires_at.isoformat() != str(row["provider_cap_expires_at"])
            or (observed_at is not None and attestation.observed_at != observed_at)
            or not bool(row["covers_fixed_infrastructure"])
            or not bool(row["covers_inference"])
        ):
            raise BudgetLedgerError("final provider attestation resource mismatch")

    @staticmethod
    def _product_occupied_cost(
        connection: sqlite3.Connection,
        account_ids: frozenset[str],
    ) -> int:
        total = 0
        for account_id in sorted(account_ids):
            rows = connection.execute(
                "SELECT * FROM product_reservations WHERE account_id=? AND state!='released'",
                (account_id,),
            ).fetchall()
            total += sum(
                int(row["max_cost"]) if str(row["state"]) == "reserved" else int(row["actual_cost"])
                for row in rows
            )
        return total

    @staticmethod
    def _contract_matches_provider_cap_key(
        contract: BudgetContract,
        key: _ProviderCapKey,
    ) -> bool:
        provider, currency, workspace, project, credential, coverage = key
        attestation = contract.provider_attestation
        return (
            attestation.provider == provider
            and contract.currency == currency
            and attestation.workspace_ref == workspace
            and attestation.project_ref == project
            and attestation.credential_ref == credential
            and coverage == ("fixed_infrastructure", "inference")
        )

    @staticmethod
    def _contracts_share_inference_cap_resource(
        first: BudgetContract,
        second: BudgetContract,
    ) -> bool:
        first_cap = first.provider_attestation
        second_cap = second.provider_attestation
        return (
            first_cap.provider == second_cap.provider
            and first.currency == second.currency
            and first_cap.workspace_ref == second_cap.workspace_ref
            and first_cap.project_ref == second_cap.project_ref
            and first_cap.credential_ref == second_cap.credential_ref
        )

    @staticmethod
    def _shared_inference_cap_occupied_cost(
        connection: sqlite3.Connection,
        contract: BudgetContract,
    ) -> int:
        account_ids: set[str] = set()
        expected_max = contract.provider_attestation.max_cost_minor_units
        for account in connection.execute("SELECT account_id FROM budget_accounts").fetchall():
            account_id = str(account["account_id"])
            candidate = BudgetLedger._current_contract(connection, account_id)
            if BudgetLedger._contracts_share_inference_cap_resource(contract, candidate):
                if candidate.provider_attestation.max_cost_minor_units != expected_max:
                    raise BudgetLedgerError("shared provider cap resource has conflicting maxima")
                account_ids.add(account_id)
        return BudgetLedger._product_occupied_cost(connection, frozenset(account_ids))

    @staticmethod
    def _shared_provider_cap_occupied_cost(
        connection: sqlite3.Connection,
        key: _ProviderCapKey,
        *,
        expected_max_cost: int,
        candidate_account_id: str | None = None,
    ) -> int:
        matching = [
            row
            for row in connection.execute(
                "SELECT * FROM infrastructure_reserves WHERE state IN ('reserved','bound')"
            ).fetchall()
            if BudgetLedger._provider_cap_key_from_row(row) == key
        ]
        if any(int(row["provider_cap_max_cost"]) != expected_max_cost for row in matching):
            raise BudgetLedgerError("shared provider cap evidence has conflicting maxima")
        account_ids = {str(row["account_id"]) for row in matching}
        for account in connection.execute("SELECT account_id FROM budget_accounts").fetchall():
            account_id = str(account["account_id"])
            contract = BudgetLedger._current_contract(connection, account_id)
            if BudgetLedger._contract_matches_provider_cap_key(contract, key):
                if contract.provider_attestation.max_cost_minor_units != expected_max_cost:
                    raise BudgetLedgerError("shared provider cap evidence has conflicting maxima")
                account_ids.add(account_id)
        if candidate_account_id is not None and candidate_account_id not in account_ids:
            account = connection.execute(
                "SELECT 1 FROM budget_accounts WHERE account_id=?",
                (candidate_account_id,),
            ).fetchone()
            if account is not None:
                raise BudgetLedgerError(
                    "candidate account does not match shared provider cap scope"
                )
        fixed_cost = sum(int(row["max_cost"]) for row in matching)
        inference_cost = BudgetLedger._product_occupied_cost(connection, frozenset(account_ids))
        return fixed_cost + inference_cost

    @staticmethod
    def _stored_capabilities_match(
        row: sqlite3.Row,
        pricing: VerifiedPricingCapability,
        provider_cap: VerifiedProviderCapCapability,
    ) -> bool:
        return (
            str(row["pricing_evidence_digest"]) == pricing.evidence_digest
            and str(row["pricing_approval_digest"]) == pricing.approval_digest
            and str(row["provider_cap_evidence_digest"]) == provider_cap.evidence_digest
            and str(row["provider_cap_approval_digest"]) == provider_cap.approval_digest
            and int(row["provider_cap_max_cost"]) == provider_cap.max_cost_minor_units
            and str(row["provider_cap_expires_at"]) == provider_cap.expires_at.isoformat()
            and str(row["provider"]) == provider_cap.provider == pricing.provider
            and str(row["currency"]) == provider_cap.currency == pricing.currency
            and str(row["workspace_ref"]) == provider_cap.workspace_ref == pricing.workspace_ref
            and str(row["project_ref"]) == provider_cap.project_ref == pricing.project_ref
            and str(row["credential_ref"]) == provider_cap.credential_ref == pricing.credential_ref
            and str(row["region"]) == pricing.region
            and str(row["base_model"]) == pricing.base_model
            and str(row["request_plan"]) == pricing.request_plan
            and str(row["receipt_plan"]) == pricing.receipt_plan
            and int(row["input_tpm_quota"]) == pricing.input_tpm_quota
            and int(row["output_tpm_quota"]) == pricing.output_tpm_quota
            and bool(row["covers_fixed_infrastructure"])
            and bool(row["covers_inference"])
        )

    @staticmethod
    def _stored_infrastructure_authorization(
        connection: sqlite3.Connection,
        reserve: sqlite3.Row,
    ) -> InfrastructureAuthorization:
        row = connection.execute(
            """SELECT domain,envelope_json FROM infrastructure_authorizations
               WHERE authorization_digest=?""",
            (str(reserve["authorization_digest"]),),
        ).fetchone()
        if row is None:
            raise BudgetLedgerError("infrastructure authorization is unavailable")
        try:
            if str(row["domain"]) == PROVISIONING_AUTHORIZATION_DOMAIN:
                return ProvisioningAuthorization.model_validate_json(bytes(row["envelope_json"]))
        except (TypeError, ValueError) as exc:
            raise BudgetLedgerError("stored infrastructure authorization is invalid") from exc
        raise BudgetLedgerError("stored infrastructure authorization domain is invalid")

    @staticmethod
    def _infrastructure_snapshot(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> InfrastructureReserveSnapshot:
        authorization = BudgetLedger._stored_infrastructure_authorization(connection, row)
        roles = tuple(
            cast(BudgetRole, str(binding["role"]))
            for binding in connection.execute(
                """SELECT role FROM deployment_role_bindings
                   WHERE reserve_id=? ORDER BY role""",
                (str(row["reserve_id"]),),
            ).fetchall()
        )
        try:
            return InfrastructureReserveSnapshot(
                reserve_id=str(row["reserve_id"]),
                account_id=str(row["account_id"]),
                run_identity=str(row["run_identity"]),
                purpose=str(row["purpose"]),
                operation_id=str(row["operation_id"]),
                authorization_domain=authorization.domain,
                authorization_digest=str(row["authorization_digest"]),
                maximum=BudgetAmounts(
                    input_tokens=0,
                    output_tokens=0,
                    cost_minor_units=int(row["max_cost"]),
                ),
                state=cast(Literal["reserved", "bound"], str(row["state"])),
                deployed_model=(
                    None if row["deployed_model"] is None else str(row["deployed_model"])
                ),
                receipt_digest=(
                    None if row["receipt_digest"] is None else str(row["receipt_digest"])
                ),
                final_approval_digest=(
                    None
                    if row["final_approval_digest"] is None
                    else str(row["final_approval_digest"])
                ),
                roles=roles,
            )
        except ValueError as exc:
            raise BudgetLedgerError("infrastructure reserve row is invalid") from exc

    def open_or_expand_account(
        self,
        *,
        plan: RunAdmissionPlanPayload,
        contract: BudgetContract,
        envelope: BudgetApprovalEnvelope,
        expected_scope: str,
        **unsupported: object,
    ) -> AccountSnapshot:
        if unsupported:
            raise BudgetLedgerError(
                "production account open does not accept caller trust policy or time"
            )
        (
            trusted_public_keys,
            authorized_roles,
            _provenance_roles,
            _canary_roles,
        ) = self._production_operational_configuration()
        return self._open_or_expand_account(
            plan=plan,
            contract=contract,
            envelope=envelope,
            trusted_public_keys=trusted_public_keys,
            expected_scope=expected_scope,
            authorized_roles=authorized_roles,
            now=self._production_now(),
        )

    def _open_or_expand_account_for_testing(
        self,
        *,
        plan: RunAdmissionPlanPayload,
        contract: BudgetContract,
        envelope: BudgetApprovalEnvelope,
        trusted_public_keys: Mapping[str, TrustedAuthority],
        expected_scope: str,
        authorized_roles: frozenset[str],
        now: datetime,
    ) -> AccountSnapshot:
        self._require_testing_mode()
        return self._open_or_expand_account(
            plan=plan,
            contract=contract,
            envelope=envelope,
            trusted_public_keys=trusted_public_keys,
            expected_scope=expected_scope,
            authorized_roles=authorized_roles,
            now=now,
        )

    def _open_or_expand_account(
        self,
        *,
        plan: RunAdmissionPlanPayload,
        contract: BudgetContract,
        envelope: BudgetApprovalEnvelope,
        trusted_public_keys: Mapping[str, TrustedAuthority],
        expected_scope: str,
        authorized_roles: frozenset[str],
        now: datetime,
    ) -> AccountSnapshot:
        proof = verify_budget_admission_contract(
            plan=plan,
            contract=contract,
            envelope=envelope,
            trusted_public_keys=trusted_public_keys,
            expected_scope=expected_scope,
            authorized_roles=authorized_roles,
            now=now,
        )

        account_id = budget_account_identity(plan.run_identity, plan.purpose)
        approval_digest = proof.approval_digest
        contract_digest = proof.contract_hash
        with self._mutation() as connection:
            reserved_provider_cap_rows = connection.execute(
                """SELECT * FROM infrastructure_reserves
                   WHERE account_id=? AND state='reserved'""",
                (account_id,),
            ).fetchall()
            for reserved_provider_cap in reserved_provider_cap_rows:
                self._require_contract_matches_reserved_provider_cap(
                    contract,
                    reserved_provider_cap,
                )
            row = connection.execute(
                "SELECT * FROM budget_accounts WHERE account_id = ?", (account_id,)
            ).fetchone()
            if row is None:
                self._insert_account(
                    connection,
                    account_id,
                    plan.run_identity,
                    plan.purpose,
                    contract,
                    envelope,
                    approval_digest,
                    contract_digest,
                )
            else:
                self._expand_account(
                    connection,
                    row,
                    contract,
                    envelope,
                    approval_digest,
                    contract_digest,
                )
        return self.account_snapshot(account_id)

    def _insert_account(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        run_identity: str,
        purpose: str,
        contract: BudgetContract,
        envelope: BudgetApprovalEnvelope,
        approval_digest: str,
        contract_digest: str,
    ) -> None:
        payload = envelope.payload
        if payload.revision != 1 or payload.previous_approval_digest is not None:
            raise BudgetLedgerError("first budget approval must be revision 1")
        ceiling = contract.ceiling
        connection.execute(
            """INSERT INTO budget_accounts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                account_id,
                run_identity,
                purpose,
                contract.currency,
                ceiling.input_tokens,
                ceiling.output_tokens,
                ceiling.cost_minor_units,
                1,
                approval_digest,
            ),
        )
        self._insert_approval(
            connection, account_id, contract, envelope, approval_digest, contract_digest
        )
        self._merge_product_limits(connection, account_id, contract)

    def _expand_account(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        contract: BudgetContract,
        envelope: BudgetApprovalEnvelope,
        approval_digest: str,
        contract_digest: str,
    ) -> None:
        current_revision = int(row["current_revision"])
        current_digest = str(row["approval_digest"])
        payload = envelope.payload
        ceiling = contract.ceiling
        current_ceiling = _amounts_from_row(row, "ceiling_input", "ceiling_output", "ceiling_cost")
        if str(row["currency"]) != contract.currency:
            raise BudgetLedgerError("budget account currency cannot change")
        if payload.revision == current_revision and approval_digest == current_digest:
            if ceiling != current_ceiling:
                raise BudgetLedgerError("idempotent approval ceiling mismatch")
            return
        if (
            payload.revision != current_revision + 1
            or payload.previous_approval_digest != current_digest
        ):
            raise BudgetLedgerError("budget approval chain mismatch")
        original_approval = connection.execute(
            """SELECT contract_json FROM budget_approvals
               WHERE account_id=? AND revision=1""",
            (str(row["account_id"]),),
        ).fetchone()
        if original_approval is None:
            raise BudgetLedgerError("budget account original role rates are unavailable")
        try:
            original_contract = BudgetContract.model_validate_json(
                bytes(original_approval["contract_json"])
            )
        except (TypeError, ValueError) as exc:
            raise BudgetLedgerError("budget account original contract is invalid") from exc
        original_without_ceiling = original_contract.model_dump(mode="python")
        proposed_without_ceiling = contract.model_dump(mode="python")
        original_without_ceiling.pop("ceiling")
        proposed_without_ceiling.pop("ceiling")
        if canonical_json_bytes(original_without_ceiling) != canonical_json_bytes(
            proposed_without_ceiling
        ):
            raise BudgetLedgerError("budget revision may change only the account ceiling")
        if not _fits(current_ceiling, ceiling) or ceiling == current_ceiling:
            raise BudgetLedgerError("new ceiling must monotonically increase")
        self._insert_approval(
            connection,
            str(row["account_id"]),
            contract,
            envelope,
            approval_digest,
            contract_digest,
        )
        connection.execute(
            """UPDATE budget_accounts SET ceiling_input=?, ceiling_output=?,
               ceiling_cost=?, current_revision=?, approval_digest=? WHERE account_id=?""",
            (
                ceiling.input_tokens,
                ceiling.output_tokens,
                ceiling.cost_minor_units,
                payload.revision,
                approval_digest,
                str(row["account_id"]),
            ),
        )

    @staticmethod
    def _insert_approval(
        connection: sqlite3.Connection,
        account_id: str,
        contract: BudgetContract,
        envelope: BudgetApprovalEnvelope,
        approval_digest: str,
        contract_digest: str,
    ) -> None:
        ceiling = contract.ceiling
        connection.execute(
            """INSERT INTO budget_approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                account_id,
                envelope.payload.revision,
                approval_digest,
                envelope.payload.previous_approval_digest,
                envelope.payload.plan_payload_hash,
                contract_digest,
                canonical_json_bytes(contract),
                ceiling.input_tokens,
                ceiling.output_tokens,
                ceiling.cost_minor_units,
            ),
        )

    @staticmethod
    def _merge_product_limits(
        connection: sqlite3.Connection, account_id: str, contract: BudgetContract
    ) -> None:
        contract_products = {(item.stage, item.product_id) for item in contract.product_reserves}
        stored_products = {
            (str(row["stage"]), str(row["product_id"]))
            for row in connection.execute(
                "SELECT stage,product_id FROM product_limits WHERE account_id=?",
                (account_id,),
            ).fetchall()
        }
        if not stored_products.issubset(contract_products):
            raise BudgetLedgerError("budget expansion cannot remove signed product limits")
        for limit in contract.product_reserves:
            contract_requests = {item.request_unit for item in limit.request_reserves}
            stored_requests = {
                str(row["request_unit"])
                for row in connection.execute(
                    """SELECT request_unit FROM request_limits WHERE account_id=?
                       AND stage=? AND product_id=?""",
                    (account_id, limit.stage, limit.product_id),
                ).fetchall()
            }
            if not stored_requests.issubset(contract_requests):
                raise BudgetLedgerError("budget expansion cannot remove signed request limits")
            contract_pool_roles = {item.role for item in limit.request_pools}
            stored_pool_roles = {
                str(row["role"])
                for row in connection.execute(
                    """SELECT role FROM request_pool_limits WHERE account_id=?
                       AND stage=? AND product_id=?""",
                    (account_id, limit.stage, limit.product_id),
                ).fetchall()
            }
            if not stored_pool_roles.issubset(contract_pool_roles):
                raise BudgetLedgerError("budget expansion cannot remove signed request pool limits")
            existing = connection.execute(
                """SELECT max_input, max_output, max_cost FROM product_limits
                   WHERE account_id=? AND stage=? AND product_id=?""",
                (account_id, limit.stage, limit.product_id),
            ).fetchone()
            maximum = limit.maximum
            if existing is not None:
                old = _amounts_from_row(existing, "max_input", "max_output", "max_cost")
                if old != maximum:
                    raise BudgetLedgerError(
                        "existing signed product reserve cannot change during expansion"
                    )
            else:
                connection.execute(
                    "INSERT INTO product_limits VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        account_id,
                        limit.stage,
                        limit.product_id,
                        maximum.input_tokens,
                        maximum.output_tokens,
                        maximum.cost_minor_units,
                    ),
                )
            for request_limit in limit.request_reserves:
                request_existing = connection.execute(
                    """SELECT role,max_input,max_output,max_cost FROM request_limits
                       WHERE account_id=? AND stage=? AND product_id=?
                       AND request_unit=?""",
                    (
                        account_id,
                        limit.stage,
                        limit.product_id,
                        request_limit.request_unit,
                    ),
                ).fetchone()
                if request_existing is not None:
                    old_request = _amounts_from_row(
                        request_existing, "max_input", "max_output", "max_cost"
                    )
                    if (
                        old_request != request_limit.maximum
                        or str(request_existing["role"]) != request_limit.role
                    ):
                        raise BudgetLedgerError(
                            "existing signed request reserve cannot change during expansion"
                        )
                    continue
                connection.execute(
                    "INSERT INTO request_limits VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        account_id,
                        limit.stage,
                        limit.product_id,
                        request_limit.request_unit,
                        request_limit.role,
                        request_limit.maximum.input_tokens,
                        request_limit.maximum.output_tokens,
                        request_limit.maximum.cost_minor_units,
                    ),
                )
            for pool_limit in limit.request_pools:
                pool_existing = connection.execute(
                    """SELECT max_attempts,max_input,max_output,max_cost,
                              model_role_identity_hash,role_rate_digest
                       FROM request_pool_limits WHERE account_id=? AND stage=?
                       AND product_id=? AND role=?""",
                    (
                        account_id,
                        limit.stage,
                        limit.product_id,
                        pool_limit.role,
                    ),
                ).fetchone()
                if pool_existing is not None:
                    role_rate = contract.role_rates[pool_limit.role]
                    old_pool = _amounts_from_row(
                        pool_existing, "max_input", "max_output", "max_cost"
                    )
                    if (
                        int(pool_existing["max_attempts"]) != pool_limit.max_attempts
                        or old_pool != pool_limit.per_attempt_maximum
                        or str(pool_existing["model_role_identity_hash"])
                        != role_rate.model_role_identity_hash
                        or str(pool_existing["role_rate_digest"]) != role_rate_digest(role_rate)
                    ):
                        raise BudgetLedgerError(
                            "existing signed request pool cannot change during expansion"
                        )
                    continue
                maximum = pool_limit.per_attempt_maximum
                role_rate = contract.role_rates[pool_limit.role]
                connection.execute(
                    """INSERT INTO request_pool_limits
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        account_id,
                        limit.stage,
                        limit.product_id,
                        pool_limit.role,
                        pool_limit.max_attempts,
                        maximum.input_tokens,
                        maximum.output_tokens,
                        maximum.cost_minor_units,
                        role_rate.model_role_identity_hash,
                        role_rate_digest(role_rate),
                    ),
                )

    def reserve_product(
        self,
        account_id: str,
        stage: str,
        product_id: str,
        maximum: BudgetAmounts,
    ) -> None:
        with self._mutation() as connection:
            account = self._require_account(connection, account_id)
            if bool(account["overage"]):
                raise BudgetLedgerError("account has an unresolved actual-usage overage")
            self._require_cost_authority_fresh(connection, account_id)
            limit = connection.execute(
                """SELECT * FROM product_limits
                   WHERE account_id=? AND stage=? AND product_id=?""",
                (account_id, stage, product_id),
            ).fetchone()
            if (
                limit is None
                or _amounts_from_row(limit, "max_input", "max_output", "max_cost") != maximum
            ):
                raise BudgetLedgerError("product reserve does not match signed contract")
            existing = connection.execute(
                """SELECT * FROM product_reservations
                   WHERE account_id=? AND stage=? AND product_id=?""",
                (account_id, stage, product_id),
            ).fetchone()
            if existing is not None:
                old = _amounts_from_row(existing, "max_input", "max_output", "max_cost")
                if str(existing["state"]) in {"reserved", "settled"} and old == maximum:
                    return
                raise BudgetLedgerError("product reservation is terminal or mismatched")
            occupied = self._occupied(connection, account_id)
            ceiling = _amounts_from_row(account, "ceiling_input", "ceiling_output", "ceiling_cost")
            if not _fits(_add(occupied, maximum), ceiling):
                raise BudgetLedgerError("insufficient budget before product boundary")
            self._require_provider_cap_allows(connection, account_id, _add(occupied, maximum))
            connection.execute(
                """INSERT INTO product_reservations
                   (account_id,stage,product_id,state,max_input,max_output,max_cost)
                   VALUES (?, ?, ?, 'reserved', ?, ?, ?)""",
                (
                    account_id,
                    stage,
                    product_id,
                    maximum.input_tokens,
                    maximum.output_tokens,
                    maximum.cost_minor_units,
                ),
            )

    def reserve_product_for_authorized_snapshot(
        self,
        *,
        account_id: str,
        expected_account_revision: int,
        expected_approval_digest: str,
        authorization_evaluated_at: datetime,
        authorization_expires_at: datetime,
        stage: str,
        product_id: str,
        maximum: BudgetAmounts,
    ) -> None:
        """Atomically validate a fresh account-bound authority and reserve its target."""

        if type(expected_account_revision) is not int or expected_account_revision < 1:
            raise BudgetLedgerError("authorized account revision is invalid")
        self._require_digest(expected_approval_digest, "authorized account approval")
        with self._mutation() as connection:
            self._require_authorization_window(
                evaluated_at=authorization_evaluated_at,
                expires_at=authorization_expires_at,
            )
            account = self._require_account(connection, account_id)
            if (
                int(account["current_revision"]) != expected_account_revision
                or str(account["approval_digest"]) != expected_approval_digest
            ):
                raise BudgetLedgerError("authorized account snapshot drifted")
            if bool(account["overage"]):
                raise BudgetLedgerError("account has an unresolved actual-usage overage")
            self._require_cost_authority_fresh(connection, account_id)
            limit = connection.execute(
                """SELECT * FROM product_limits
                   WHERE account_id=? AND stage=? AND product_id=?""",
                (account_id, stage, product_id),
            ).fetchone()
            if (
                limit is None
                or _amounts_from_row(limit, "max_input", "max_output", "max_cost") != maximum
            ):
                raise BudgetLedgerError("authorized product reserve is not signed")
            existing = connection.execute(
                """SELECT * FROM product_reservations
                   WHERE account_id=? AND stage=? AND product_id=?""",
                (account_id, stage, product_id),
            ).fetchone()
            if existing is not None:
                old = _amounts_from_row(existing, "max_input", "max_output", "max_cost")
                if str(existing["state"]) in {"reserved", "settled"} and old == maximum:
                    return
                raise BudgetLedgerError("product reservation is terminal or mismatched")
            occupied = self._occupied(connection, account_id)
            ceiling = _amounts_from_row(
                account,
                "ceiling_input",
                "ceiling_output",
                "ceiling_cost",
            )
            if not _fits(_add(occupied, maximum), ceiling):
                raise BudgetLedgerError("insufficient budget before product boundary")
            self._require_provider_cap_allows(connection, account_id, _add(occupied, maximum))
            connection.execute(
                """INSERT INTO product_reservations
                   (account_id,stage,product_id,state,max_input,max_output,max_cost)
                   VALUES (?, ?, ?, 'reserved', ?, ?, ?)""",
                (
                    account_id,
                    stage,
                    product_id,
                    maximum.input_tokens,
                    maximum.output_tokens,
                    maximum.cost_minor_units,
                ),
            )

    def claim_canary_capability_and_reserve(
        self,
        *,
        account_id: str,
        capability_digest: str,
        canary_stage: str,
        canary_product_id: str,
        expected_settlement_digest: str,
        authorization_evaluated_at: datetime,
        authorization_expires_at: datetime,
        target_stage: str,
        target_product_id: str,
        target_maximum: BudgetAmounts,
        granted_targets: tuple[tuple[str, str], ...],
    ) -> None:
        """Atomically consume one verified capability and reserve its exact target."""

        self._require_digest(capability_digest, "canary capability")
        self._require_digest(expected_settlement_digest, "settlement snapshot")
        if (
            not canary_stage.strip()
            or not canary_product_id.strip()
            or not target_stage.strip()
            or not target_product_id.strip()
            or _is_zero(target_maximum)
        ):
            raise BudgetLedgerError("canary and target identities are required")
        if (
            not granted_targets
            or any(
                len(target) != 2
                or not isinstance(target[0], str)
                or not isinstance(target[1], str)
                or not target[0].strip()
                or not target[1].strip()
                for target in granted_targets
            )
            or len(granted_targets) != len(set(granted_targets))
        ):
            raise BudgetLedgerError("canary capability grants are invalid")
        target_identity = (target_stage, target_product_id)
        granted_target_set = frozenset(granted_targets)
        if target_identity not in granted_target_set:
            raise BudgetLedgerError("capability target is outside verified grants")
        with self._mutation() as connection:
            self._require_authorization_window(
                evaluated_at=authorization_evaluated_at,
                expires_at=authorization_expires_at,
            )
            if target_identity not in granted_target_set:
                raise BudgetLedgerError("capability target is outside verified grants")
            account = self._require_account(connection, account_id)
            if bool(account["overage"]):
                raise BudgetLedgerError("account has an unresolved actual-usage overage")
            self._require_cost_authority_fresh(connection, account_id)
            snapshot = self._product_settlement_snapshot(
                connection, account_id, canary_stage, canary_product_id
            )
            current_digest = self.product_settlement_snapshot_digest(snapshot)
            if current_digest != expected_settlement_digest:
                raise BudgetLedgerError("canary settlement snapshot drifted")
            self._require_eligible_canary_settlement(connection, snapshot)

            limit = connection.execute(
                """SELECT * FROM product_limits
                   WHERE account_id=? AND stage=? AND product_id=?""",
                (account_id, target_stage, target_product_id),
            ).fetchone()
            if (
                limit is None
                or _amounts_from_row(limit, "max_input", "max_output", "max_cost") != target_maximum
            ):
                raise BudgetLedgerError("capability target reserve is not signed")

            existing_claim = connection.execute(
                """SELECT * FROM canary_capability_claims
                   WHERE account_id=? AND capability_digest=?
                   AND target_stage=? AND target_product_id=?""",
                (
                    account_id,
                    capability_digest,
                    target_stage,
                    target_product_id,
                ),
            ).fetchone()
            if existing_claim is not None:
                existing_maximum = _amounts_from_row(
                    existing_claim,
                    "target_max_input",
                    "target_max_output",
                    "target_max_cost",
                )
                if (
                    str(existing_claim["canary_stage"]) != canary_stage
                    or str(existing_claim["canary_product_id"]) != canary_product_id
                    or str(existing_claim["settlement_digest"]) != current_digest
                    or int(existing_claim["budget_revision"]) != snapshot.budget_revision
                    or str(existing_claim["approval_digest"]) != snapshot.approval_digest
                    or str(existing_claim["target_stage"]) != target_stage
                    or str(existing_claim["target_product_id"]) != target_product_id
                    or existing_maximum != target_maximum
                ):
                    raise BudgetLedgerError(
                        "canary capability replay selected a different target or evidence"
                    )
                reservation = connection.execute(
                    """SELECT * FROM product_reservations
                       WHERE account_id=? AND stage=? AND product_id=?""",
                    (account_id, target_stage, target_product_id),
                ).fetchone()
                if (
                    reservation is None
                    or str(reservation["state"]) not in {"reserved", "settled"}
                    or _amounts_from_row(reservation, "max_input", "max_output", "max_cost")
                    != target_maximum
                ):
                    raise BudgetLedgerError("canary capability claim lost its target reservation")
                return

            target_reservation = connection.execute(
                """SELECT 1 FROM product_reservations
                   WHERE account_id=? AND stage=? AND product_id=?""",
                (account_id, target_stage, target_product_id),
            ).fetchone()
            if target_reservation is not None:
                raise BudgetLedgerError(
                    "canary capability cannot adopt an existing target reservation"
                )
            occupied = self._occupied(connection, account_id)
            ceiling = _amounts_from_row(account, "ceiling_input", "ceiling_output", "ceiling_cost")
            if not _fits(_add(occupied, target_maximum), ceiling):
                raise BudgetLedgerError("insufficient budget before capability target")
            self._require_provider_cap_allows(
                connection, account_id, _add(occupied, target_maximum)
            )
            connection.execute(
                """INSERT INTO canary_capability_claims VALUES (
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                   )""",
                (
                    account_id,
                    capability_digest,
                    canary_stage,
                    canary_product_id,
                    current_digest,
                    snapshot.budget_revision,
                    snapshot.approval_digest,
                    target_stage,
                    target_product_id,
                    target_maximum.input_tokens,
                    target_maximum.output_tokens,
                    target_maximum.cost_minor_units,
                ),
            )
            connection.execute(
                """INSERT INTO product_reservations
                   (account_id,stage,product_id,state,max_input,max_output,max_cost)
                   VALUES (?, ?, ?, 'reserved', ?, ?, ?)""",
                (
                    account_id,
                    target_stage,
                    target_product_id,
                    target_maximum.input_tokens,
                    target_maximum.output_tokens,
                    target_maximum.cost_minor_units,
                ),
            )

    @staticmethod
    def _require_eligible_canary_settlement(
        connection: sqlite3.Connection,
        snapshot: ProductSettlementSnapshot,
    ) -> None:
        if snapshot.reservation_state != "settled" or not snapshot.attempts:
            raise BudgetLedgerError("canary is not completely settled")
        contract = BudgetLedger._current_contract(connection, snapshot.account_id)
        actuals: list[BudgetAmounts] = []
        for attempt in snapshot.attempts:
            if (
                attempt.state != "terminal"
                or not attempt.usage_verified
                or attempt.response_digest is None
                or attempt.no_usage_proof is not None
            ):
                raise BudgetLedgerError(
                    "canary attempts must be terminal with verified provider usage"
                )
            if not _fits(attempt.actual, attempt.maximum):
                raise BudgetLedgerError("canary actual usage exceeds its attempt bound")
            expected_cost = role_rate_cost(
                contract.role_rates[attempt.role],
                input_tokens=attempt.actual.input_tokens,
                output_tokens=attempt.actual.output_tokens,
            )
            if attempt.actual.cost_minor_units != expected_cost:
                raise BudgetLedgerError("canary actual cost does not match the signed role rate")
            actuals.append(attempt.actual)
        if _sum_amounts(tuple(actuals)) != snapshot.reservation_actual:
            raise BudgetLedgerError("canary reservation actual does not match terminal attempts")

    def claim_attempt(
        self,
        account_id: str,
        stage: str,
        product_id: str,
        request_unit: str,
        attempt_no: int,
        owner_token: str,
        maximum: BudgetAmounts,
    ) -> SendPermit | None:
        key = AttemptKey(
            account_id=account_id,
            stage=stage,
            product_id=product_id,
            request_unit=request_unit,
            attempt_no=attempt_no,
        )
        if not owner_token.strip() or _is_zero(maximum):
            raise BudgetLedgerError("attempt owner and maximum bound are required")
        with self._mutation() as connection:
            account = self._require_account(connection, account_id)
            if bool(account["overage"]):
                raise BudgetLedgerError("account has an unresolved actual-usage overage")
            reservation = connection.execute(
                """SELECT * FROM product_reservations
                   WHERE account_id=? AND stage=? AND product_id=?""",
                (account_id, stage, product_id),
            ).fetchone()
            if reservation is None or str(reservation["state"]) != "reserved":
                return None
            existing = connection.execute(
                """SELECT 1 FROM request_attempts WHERE account_id=? AND stage=?
                   AND product_id=? AND request_unit=? AND attempt_no=?""",
                (account_id, stage, product_id, request_unit, attempt_no),
            ).fetchone()
            if existing is not None:
                return None
            request_limit = connection.execute(
                """SELECT * FROM request_limits WHERE account_id=? AND stage=?
                   AND product_id=? AND request_unit=?""",
                (account_id, stage, product_id, request_unit),
            ).fetchone()
            if (
                request_limit is None
                or _amounts_from_row(request_limit, "max_input", "max_output", "max_cost")
                != maximum
            ):
                raise BudgetLedgerError("request bound does not match signed contract")
            latest = connection.execute(
                """SELECT COALESCE(MAX(attempt_no), 0) FROM request_attempts
                   WHERE account_id=? AND stage=? AND product_id=? AND request_unit=?""",
                (account_id, stage, product_id, request_unit),
            ).fetchone()
            assert latest is not None
            if attempt_no != int(latest[0]) + 1:
                raise BudgetLedgerError("attempt number must be sequential")
            reserved_max = _amounts_from_row(reservation, "max_input", "max_output", "max_cost")
            charged = self._attempt_charges(connection, account_id, stage, product_id)
            if not _fits(_add(charged, maximum), reserved_max):
                raise BudgetLedgerError("request bound exceeds product reservation")
            connection.execute(
                """INSERT INTO request_attempts
                   (account_id,stage,product_id,request_unit,attempt_no,
                    owner_token_digest,role,limit_kind,state,
                    max_input,max_output,max_cost)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'exact', 'prepared', ?, ?, ?)""",
                (
                    account_id,
                    stage,
                    product_id,
                    request_unit,
                    attempt_no,
                    _owner_token_digest(owner_token),
                    str(request_limit["role"]),
                    maximum.input_tokens,
                    maximum.output_tokens,
                    maximum.cost_minor_units,
                ),
            )
        return SendPermit(
            key=key,
            owner_token=owner_token,
            role=str(request_limit["role"]),  # type: ignore[arg-type]
            maximum=maximum,
        )

    def claim_pool_attempt(
        self,
        *,
        account_id: str,
        stage: str,
        product_id: str,
        request_unit: str,
        attempt_no: int,
        owner_token: str,
        role: BudgetRole,
        maximum: BudgetAmounts,
    ) -> SendPermit | None:
        """Claim one exact fingerprint from a signed per-role dynamic request pool."""

        self._require_digest(request_unit, "request fingerprint")
        key = AttemptKey(
            account_id=account_id,
            stage=stage,
            product_id=product_id,
            request_unit=request_unit,
            attempt_no=attempt_no,
        )
        if not owner_token.strip() or _is_zero(maximum):
            raise BudgetLedgerError("attempt owner and maximum bound are required")
        with self._mutation() as connection:
            account = self._require_account(connection, account_id)
            if bool(account["overage"]):
                raise BudgetLedgerError("account has an unresolved actual-usage overage")
            reservation = connection.execute(
                """SELECT * FROM product_reservations
                   WHERE account_id=? AND stage=? AND product_id=?""",
                (account_id, stage, product_id),
            ).fetchone()
            if reservation is None or str(reservation["state"]) != "reserved":
                return None
            existing = connection.execute(
                """SELECT 1 FROM request_attempts WHERE account_id=? AND stage=?
                   AND product_id=? AND request_unit=? AND attempt_no=?""",
                (account_id, stage, product_id, request_unit, attempt_no),
            ).fetchone()
            if existing is not None:
                return None
            exact = connection.execute(
                """SELECT 1 FROM request_limits WHERE account_id=? AND stage=?
                   AND product_id=? AND request_unit=?""",
                (account_id, stage, product_id, request_unit),
            ).fetchone()
            if exact is not None:
                raise BudgetLedgerError("dynamic request fingerprint is reserved by an exact limit")
            pool_limit = connection.execute(
                """SELECT * FROM request_pool_limits WHERE account_id=? AND stage=?
                   AND product_id=? AND role=?""",
                (account_id, stage, product_id, role),
            ).fetchone()
            if pool_limit is None:
                raise BudgetLedgerError("signed request pool is not available")
            if _amounts_from_row(pool_limit, "max_input", "max_output", "max_cost") != maximum:
                raise BudgetLedgerError("request bound does not match signed pool")
            attempt_count = connection.execute(
                """SELECT COUNT(*) FROM request_attempts WHERE account_id=?
                   AND stage=? AND product_id=? AND role=? AND limit_kind='pool'""",
                (account_id, stage, product_id, role),
            ).fetchone()
            assert attempt_count is not None
            if int(attempt_count[0]) >= int(pool_limit["max_attempts"]):
                raise BudgetLedgerError("request pool attempt limit is exhausted")
            latest = connection.execute(
                """SELECT COALESCE(MAX(attempt_no), 0) FROM request_attempts
                   WHERE account_id=? AND stage=? AND product_id=? AND request_unit=?""",
                (account_id, stage, product_id, request_unit),
            ).fetchone()
            assert latest is not None
            if attempt_no != int(latest[0]) + 1:
                raise BudgetLedgerError("attempt number must be sequential")
            reserved_max = _amounts_from_row(reservation, "max_input", "max_output", "max_cost")
            charged = self._attempt_charges(connection, account_id, stage, product_id)
            if not _fits(_add(charged, maximum), reserved_max):
                raise BudgetLedgerError("request bound exceeds product reservation")
            connection.execute(
                """INSERT INTO request_attempts
                   (account_id,stage,product_id,request_unit,attempt_no,
                    owner_token_digest,role,limit_kind,state,
                    max_input,max_output,max_cost)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pool', 'prepared', ?, ?, ?)""",
                (
                    account_id,
                    stage,
                    product_id,
                    request_unit,
                    attempt_no,
                    _owner_token_digest(owner_token),
                    role,
                    maximum.input_tokens,
                    maximum.output_tokens,
                    maximum.cost_minor_units,
                ),
            )
        return SendPermit(
            key=key,
            owner_token=owner_token,
            role=role,
            maximum=maximum,
        )

    def mark_sent(self, permit: SendPermit) -> None:
        with self._mutation() as connection:
            changed = connection.execute(
                """UPDATE request_attempts SET state='sent'
                   WHERE account_id=? AND stage=? AND product_id=? AND request_unit=?
                   AND attempt_no=? AND owner_token_digest=? AND state='prepared'""",
                self._permit_params(permit),
            ).rowcount
            if changed != 1:
                raise BudgetLedgerError("send permit is not the current prepared owner")

    def mark_uncertain(self, permit: SendPermit) -> None:
        """Conservatively charge one owner-held ambiguous attempt at its full bound."""

        with self._mutation() as connection:
            changed = connection.execute(
                """UPDATE request_attempts SET state='uncertain',
                   charged_input=max_input,charged_output=max_output,charged_cost=max_cost
                   WHERE account_id=? AND stage=? AND product_id=? AND request_unit=?
                   AND attempt_no=? AND owner_token_digest=?
                   AND state IN ('prepared','sent')""",
                self._permit_params(permit),
            ).rowcount
            if changed != 1:
                raise BudgetLedgerError("permit is not the current attempt owner")

    def record_terminal(
        self,
        permit: SendPermit,
        *,
        actual: BudgetAmounts,
        response_digest: str,
        usage_verified: bool,
        force_overage: bool = False,
    ) -> None:
        self._require_digest(response_digest, "response")
        if type(usage_verified) is not bool or type(force_overage) is not bool:
            raise BudgetLedgerError("usage verification markers must be boolean")
        if force_overage and usage_verified:
            raise BudgetLedgerError("verified usage cannot force an unknown overage")
        with self._mutation() as connection:
            owned_attempt = connection.execute(
                """SELECT role,max_input,max_output,max_cost FROM request_attempts
                   WHERE account_id=? AND stage=? AND product_id=? AND request_unit=?
                   AND attempt_no=? AND owner_token_digest=?
                   AND state IN ('prepared','sent')""",
                self._permit_params(permit),
            ).fetchone()
            if owned_attempt is None:
                raise BudgetLedgerError("terminal response is not owned or already resolved")
            stored_maximum = _amounts_from_row(owned_attempt, "max_input", "max_output", "max_cost")
            stored_actual = stored_maximum
            if usage_verified:
                if any(
                    value > SQLITE_SAFE_INTEGER_MAX
                    for value in (
                        actual.input_tokens,
                        actual.output_tokens,
                        actual.cost_minor_units,
                    )
                ):
                    raise BudgetLedgerError("verified usage exceeds SQLite's durable integer range")
                contract = self._current_contract(connection, permit.key.account_id)
                role = cast(BudgetRole, str(owned_attempt["role"]))
                expected_cost = role_rate_cost(
                    contract.role_rates[role],
                    input_tokens=actual.input_tokens,
                    output_tokens=actual.output_tokens,
                )
                if actual.cost_minor_units != expected_cost:
                    raise BudgetLedgerError(
                        "verified actual cost does not match the signed role rate"
                    )
                stored_actual = actual
            changed = connection.execute(
                """UPDATE request_attempts SET state='terminal',
                   actual_input=?,actual_output=?,actual_cost=?,
                   charged_input=?,charged_output=?,charged_cost=?,response_digest=?,
                   usage_verified=?
                   WHERE account_id=? AND stage=? AND product_id=? AND request_unit=?
                   AND attempt_no=? AND owner_token_digest=?
                   AND state IN ('prepared','sent')""",
                (
                    stored_actual.input_tokens,
                    stored_actual.output_tokens,
                    stored_actual.cost_minor_units,
                    stored_actual.input_tokens,
                    stored_actual.output_tokens,
                    stored_actual.cost_minor_units,
                    response_digest,
                    int(usage_verified),
                    *self._permit_params(permit),
                ),
            ).rowcount
            if changed != 1:
                raise BudgetLedgerError("terminal response is not owned or already resolved")
            if force_overage or not _fits(stored_actual, stored_maximum):
                connection.execute(
                    "UPDATE budget_accounts SET overage=1 WHERE account_id=?",
                    (permit.key.account_id,),
                )

    def recover_incomplete(self, account_id: str) -> int:
        with self._mutation() as connection:
            self._require_account(connection, account_id)
            affected_reservations = connection.execute(
                """SELECT DISTINCT reservations.state
                   FROM request_attempts AS attempts
                   JOIN product_reservations AS reservations
                     ON reservations.account_id=attempts.account_id
                    AND reservations.stage=attempts.stage
                    AND reservations.product_id=attempts.product_id
                   WHERE attempts.account_id=? AND attempts.state='no_usage'""",
                (account_id,),
            ).fetchall()
            changed = connection.execute(
                """UPDATE request_attempts SET state='uncertain',
                   charged_input=max_input,charged_output=max_output,charged_cost=max_cost,
                   provider_proof_digest=NULL,provider_request_id=NULL,
                   provider_verifier_policy=NULL,provider_proof_observed_at=NULL
                   WHERE account_id=? AND state IN ('prepared','sent','no_usage')""",
                (account_id,),
            ).rowcount
            affected_states = {str(row["state"]) for row in affected_reservations}
            if "settled" in affected_states:
                self._reconcile_legacy_settled_reservations(
                    connection,
                    account_id=account_id,
                )
            if "released" in affected_states:
                connection.execute(
                    "UPDATE budget_accounts SET overage=1 WHERE account_id=?",
                    (account_id,),
                )
        return int(changed)

    def release_product(self, account_id: str, stage: str, product_id: str) -> bool:
        with self._mutation() as connection:
            reservation = connection.execute(
                """SELECT state FROM product_reservations
                   WHERE account_id=? AND stage=? AND product_id=?""",
                (account_id, stage, product_id),
            ).fetchone()
            if reservation is None or str(reservation["state"]) != "reserved":
                return False
            unresolved = connection.execute(
                """SELECT COUNT(*) FROM request_attempts WHERE account_id=? AND stage=?
                   AND product_id=?""",
                (account_id, stage, product_id),
            ).fetchone()
            assert unresolved is not None
            if int(unresolved[0]) != 0:
                return False
            connection.execute(
                """UPDATE product_reservations SET state='released'
                   WHERE account_id=? AND stage=? AND product_id=?""",
                (account_id, stage, product_id),
            )
            return True

    def settle_product(self, account_id: str, stage: str, product_id: str) -> None:
        with self._mutation() as connection:
            reservation = connection.execute(
                """SELECT * FROM product_reservations
                   WHERE account_id=? AND stage=? AND product_id=?""",
                (account_id, stage, product_id),
            ).fetchone()
            if reservation is None or str(reservation["state"]) != "reserved":
                raise BudgetLedgerError("product is not reserved")
            unresolved = connection.execute(
                """SELECT COUNT(*) FROM request_attempts WHERE account_id=? AND stage=?
                   AND product_id=? AND state NOT IN ('terminal','uncertain')""",
                (account_id, stage, product_id),
            ).fetchone()
            assert unresolved is not None
            if int(unresolved[0]) != 0:
                raise BudgetLedgerError("product has an unresolved request attempt")
            signed_units = {
                str(row["request_unit"])
                for row in connection.execute(
                    """SELECT request_unit FROM request_limits WHERE account_id=?
                       AND stage=? AND product_id=?""",
                    (account_id, stage, product_id),
                ).fetchall()
            }
            resolved_units = {
                str(row["request_unit"])
                for row in connection.execute(
                    """SELECT DISTINCT request_unit FROM request_attempts
                       WHERE account_id=? AND stage=? AND product_id=?
                       AND limit_kind='exact'
                       AND state IN ('terminal','uncertain')""",
                    (account_id, stage, product_id),
                ).fetchall()
            }
            if resolved_units != signed_units:
                raise BudgetLedgerError(
                    "every signed request unit requires terminal or uncertain charge"
                )
            actual = self._attempt_charges(connection, account_id, stage, product_id)
            reserved = _amounts_from_row(reservation, "max_input", "max_output", "max_cost")
            connection.execute(
                """UPDATE product_reservations SET state='settled',
                   actual_input=?,actual_output=?,actual_cost=?
                   WHERE account_id=? AND stage=? AND product_id=?""",
                (
                    actual.input_tokens,
                    actual.output_tokens,
                    actual.cost_minor_units,
                    account_id,
                    stage,
                    product_id,
                ),
            )
            account = self._require_account(connection, account_id)
            ceiling = _amounts_from_row(account, "ceiling_input", "ceiling_output", "ceiling_cost")
            if not _fits(actual, reserved) or not _fits(
                self._occupied(connection, account_id), ceiling
            ):
                connection.execute(
                    "UPDATE budget_accounts SET overage=1 WHERE account_id=?",
                    (account_id,),
                )

    def attempt_snapshot(self, key: AttemptKey) -> AttemptSnapshot:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM request_attempts WHERE account_id=? AND stage=?
                   AND product_id=? AND request_unit=? AND attempt_no=?""",
                (
                    key.account_id,
                    key.stage,
                    key.product_id,
                    key.request_unit,
                    key.attempt_no,
                ),
            ).fetchone()
        if row is None:
            raise BudgetLedgerError("request attempt not found")
        return AttemptSnapshot(
            key=key,
            state=str(row["state"]),  # type: ignore[arg-type]
            maximum=_amounts_from_row(row, "max_input", "max_output", "max_cost"),
            actual=_amounts_from_row(row, "actual_input", "actual_output", "actual_cost"),
            charged=_amounts_from_row(row, "charged_input", "charged_output", "charged_cost"),
            response_digest=(
                None if row["response_digest"] is None else str(row["response_digest"])
            ),
            usage_verified=bool(row["usage_verified"]),
        )

    def product_settlement_snapshot(
        self, account_id: str, stage: str, product_id: str
    ) -> ProductSettlementSnapshot:
        """Return the canonical, complete settlement preimage for one product."""

        connection = self._connect()
        try:
            connection.execute("BEGIN")
            snapshot = self._product_settlement_snapshot(connection, account_id, stage, product_id)
            connection.commit()
            return snapshot
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def locked_product_settlement_snapshot(
        self, account_id: str, stage: str, product_id: str
    ) -> Iterator[ProductSettlementSnapshot]:
        """Yield a frozen settlement snapshot while ledger mutations are excluded."""

        with self._mutation() as connection:
            yield self._product_settlement_snapshot(
                connection,
                account_id,
                stage,
                product_id,
            )

    @staticmethod
    def product_settlement_snapshot_digest(
        snapshot: ProductSettlementSnapshot,
    ) -> str:
        return hashlib.sha256(
            _SETTLEMENT_SNAPSHOT_DOMAIN + canonical_json_bytes(snapshot)
        ).hexdigest()

    @staticmethod
    def _product_settlement_snapshot(
        connection: sqlite3.Connection,
        account_id: str,
        stage: str,
        product_id: str,
    ) -> ProductSettlementSnapshot:
        account = BudgetLedger._require_account(connection, account_id)
        reservation = connection.execute(
            """SELECT * FROM product_reservations
               WHERE account_id=? AND stage=? AND product_id=?""",
            (account_id, stage, product_id),
        ).fetchone()
        if reservation is None:
            raise BudgetLedgerError("product reservation not found")
        rows = connection.execute(
            """SELECT * FROM request_attempts
               WHERE account_id=? AND stage=? AND product_id=?
               ORDER BY request_unit,attempt_no""",
            (account_id, stage, product_id),
        ).fetchall()
        attempts: list[ProductSettlementAttempt] = []
        for row in rows:
            proof_values = (
                row["provider_proof_digest"],
                row["provider_request_id"],
                row["provider_verifier_policy"],
                row["provider_proof_observed_at"],
            )
            if any(value is not None for value in proof_values) and not all(
                value is not None for value in proof_values
            ):
                raise BudgetLedgerError("attempt no-usage proof is incomplete")
            proof = None
            if all(value is not None for value in proof_values):
                try:
                    proof = SettlementNoUsageProof(
                        evidence_digest=str(proof_values[0]),
                        provider_request_id=str(proof_values[1]),
                        verifier_policy=str(proof_values[2]),
                        observed_at=datetime.fromisoformat(str(proof_values[3])),
                    )
                except ValueError as exc:
                    raise BudgetLedgerError("attempt no-usage proof is invalid") from exc
            try:
                attempts.append(
                    ProductSettlementAttempt(
                        request_unit=str(row["request_unit"]),
                        attempt_no=int(row["attempt_no"]),
                        role=str(row["role"]),  # type: ignore[arg-type]
                        limit_kind=str(row["limit_kind"]),  # type: ignore[arg-type]
                        state=str(row["state"]),  # type: ignore[arg-type]
                        maximum=_amounts_from_row(row, "max_input", "max_output", "max_cost"),
                        actual=_amounts_from_row(
                            row, "actual_input", "actual_output", "actual_cost"
                        ),
                        usage_verified=bool(row["usage_verified"]),
                        response_digest=(
                            None if row["response_digest"] is None else str(row["response_digest"])
                        ),
                        no_usage_proof=proof,
                    )
                )
            except ValueError as exc:
                raise BudgetLedgerError("attempt settlement row is invalid") from exc
        try:
            return ProductSettlementSnapshot(
                account_id=account_id,
                budget_revision=int(account["current_revision"]),
                approval_digest=str(account["approval_digest"]),
                stage=stage,
                product_id=product_id,
                reservation_state=str(reservation["state"]),  # type: ignore[arg-type]
                reservation_maximum=_amounts_from_row(
                    reservation, "max_input", "max_output", "max_cost"
                ),
                reservation_actual=_amounts_from_row(
                    reservation, "actual_input", "actual_output", "actual_cost"
                ),
                attempts=tuple(attempts),
            )
        except ValueError as exc:
            raise BudgetLedgerError("product settlement row is invalid") from exc

    def account_snapshot(self, account_id: str) -> AccountSnapshot:
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            account = self._require_account(connection, account_id)
            rows = connection.execute(
                "SELECT * FROM product_reservations WHERE account_id=?", (account_id,)
            ).fetchall()
            attempt_count_row = connection.execute(
                "SELECT COUNT(*) FROM request_attempts WHERE account_id=?", (account_id,)
            ).fetchone()
            uncertain_rows = connection.execute(
                "SELECT * FROM request_attempts WHERE account_id=? AND state='uncertain'",
                (account_id,),
            ).fetchall()
            infrastructure_cost = self._infrastructure_reserved_cost(connection, account_id)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        reserved = _sum_amounts(
            tuple(
                _amounts_from_row(row, "max_input", "max_output", "max_cost")
                for row in rows
                if str(row["state"]) == "reserved"
            )
        )
        infrastructure_reserved = BudgetAmounts(
            input_tokens=0,
            output_tokens=0,
            cost_minor_units=infrastructure_cost,
        )
        reserved = _add(reserved, infrastructure_reserved)
        settled = _sum_amounts(
            tuple(
                _amounts_from_row(row, "actual_input", "actual_output", "actual_cost")
                for row in rows
                if str(row["state"]) == "settled"
            )
        )
        uncertain = _sum_amounts(
            tuple(
                _amounts_from_row(row, "charged_input", "charged_output", "charged_cost")
                for row in uncertain_rows
            )
        )
        assert attempt_count_row is not None
        return AccountSnapshot(
            account_id=account_id,
            revision=int(account["current_revision"]),
            approval_digest=str(account["approval_digest"]),
            ceiling=_amounts_from_row(account, "ceiling_input", "ceiling_output", "ceiling_cost"),
            reserved=reserved,
            settled=settled,
            uncertain=uncertain,
            attempt_count=int(attempt_count_row[0]),
            overage=bool(account["overage"]),
        )

    @staticmethod
    def _require_account(connection: sqlite3.Connection, account_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM budget_accounts WHERE account_id=?", (account_id,)
        ).fetchone()
        if row is None:
            raise BudgetLedgerError("budget account not found")
        return cast(sqlite3.Row, row)

    @staticmethod
    def _occupied(connection: sqlite3.Connection, account_id: str) -> BudgetAmounts:
        rows = connection.execute(
            "SELECT * FROM product_reservations WHERE account_id=?", (account_id,)
        ).fetchall()
        product_occupied = _sum_amounts(
            tuple(
                _amounts_from_row(
                    row,
                    "max_input" if str(row["state"]) == "reserved" else "actual_input",
                    "max_output" if str(row["state"]) == "reserved" else "actual_output",
                    "max_cost" if str(row["state"]) == "reserved" else "actual_cost",
                )
                for row in rows
                if str(row["state"]) != "released"
            )
        )
        return _add(
            product_occupied,
            BudgetAmounts(
                input_tokens=0,
                output_tokens=0,
                cost_minor_units=BudgetLedger._infrastructure_reserved_cost(connection, account_id),
            ),
        )

    @staticmethod
    def _attempt_charges(
        connection: sqlite3.Connection,
        account_id: str,
        stage: str,
        product_id: str,
    ) -> BudgetAmounts:
        rows = connection.execute(
            """SELECT * FROM request_attempts
               WHERE account_id=? AND stage=? AND product_id=?""",
            (account_id, stage, product_id),
        ).fetchall()
        values: list[BudgetAmounts] = []
        for row in rows:
            state = str(row["state"])
            if state in {"prepared", "sent", "no_usage"} or (
                state == "terminal" and not bool(row["usage_verified"])
            ):
                values.append(_amounts_from_row(row, "max_input", "max_output", "max_cost"))
            else:
                values.append(
                    _amounts_from_row(row, "charged_input", "charged_output", "charged_cost")
                )
        return _sum_amounts(tuple(values))

    @staticmethod
    def _permit_params(permit: SendPermit) -> tuple[object, ...]:
        return (
            permit.key.account_id,
            permit.key.stage,
            permit.key.product_id,
            permit.key.request_unit,
            permit.key.attempt_no,
            _owner_token_digest(permit.owner_token),
        )

    def _require_authorization_window(
        self,
        *,
        evaluated_at: datetime,
        expires_at: datetime,
    ) -> None:
        for label, timestamp in (
            ("evaluation", evaluated_at),
            ("expiry", expires_at),
        ):
            if (
                not isinstance(timestamp, datetime)
                or timestamp.tzinfo is None
                or timestamp.utcoffset() is None
            ):
                raise BudgetLedgerError(f"authorization {label} time must include a timezone")
        if evaluated_at >= expires_at:
            raise BudgetLedgerError("authorization expiry must follow evaluation")
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise BudgetLedgerError("authorization ledger clock must include a timezone")
        if now < evaluated_at:
            raise BudgetLedgerError("authorization ledger clock moved backwards")
        if now >= expires_at:
            raise BudgetLedgerError("authorization expired before ledger mutation")

    @staticmethod
    def _require_digest(value: str, label: str) -> None:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise BudgetLedgerError(f"{label} digest is invalid")

    def _require_cost_authority_fresh(
        self,
        connection: sqlite3.Connection,
        account_id: str,
    ) -> None:
        contract = self._current_contract(connection, account_id)
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise BudgetLedgerError("budget ledger clock must include a timezone")
        if now >= contract.price_expires_at or now >= contract.provider_attestation.expires_at:
            raise BudgetLedgerError("pricing or provider cap expired before cost mutation")

    @staticmethod
    def _require_provider_cap_allows(
        connection: sqlite3.Connection,
        account_id: str,
        proposed_occupied: BudgetAmounts,
    ) -> None:
        contract = BudgetLedger._current_contract(connection, account_id)
        provider_cap = contract.provider_attestation.max_cost_minor_units
        matching_scope_rows = [
            row
            for row in connection.execute(
                """SELECT * FROM infrastructure_reserves
                   WHERE state IN ('reserved','bound')"""
            ).fetchall()
            if BudgetLedger._contract_matches_provider_cap_key(
                contract, BudgetLedger._provider_cap_key_from_row(row)
            )
        ]
        provider_cap_keys = {
            BudgetLedger._provider_cap_key_from_row(row) for row in matching_scope_rows
        }
        if len(provider_cap_keys) > 1:
            raise BudgetLedgerError("durable provider cap scope is ambiguous")
        if not provider_cap_keys:
            current_occupied = BudgetLedger._occupied(connection, account_id)
            additional_cost = proposed_occupied.cost_minor_units - current_occupied.cost_minor_units
            if additional_cost < 0:
                raise BudgetLedgerError("proposed provider-cap occupancy regressed")
            shared_inference = BudgetLedger._shared_inference_cap_occupied_cost(
                connection, contract
            )
            if shared_inference + additional_cost > provider_cap:
                raise BudgetLedgerError("durable provider cap exceeded before product reserve")
            return
        if any(int(row["provider_cap_max_cost"]) != provider_cap for row in matching_scope_rows):
            raise BudgetLedgerError("shared provider cap evidence has conflicting maxima")
        current_occupied = BudgetLedger._occupied(connection, account_id)
        additional_cost = proposed_occupied.cost_minor_units - current_occupied.cost_minor_units
        if additional_cost < 0:
            raise BudgetLedgerError("proposed provider-cap occupancy regressed")
        shared_occupied = BudgetLedger._shared_provider_cap_occupied_cost(
            connection,
            next(iter(provider_cap_keys)),
            expected_max_cost=provider_cap,
            candidate_account_id=account_id,
        )
        if shared_occupied + additional_cost > provider_cap:
            raise BudgetLedgerError("durable provider cap exceeded before product reserve")

    @staticmethod
    def _current_contract(connection: sqlite3.Connection, account_id: str) -> BudgetContract:
        approval = connection.execute(
            """SELECT a.contract_json FROM budget_approvals AS a
               JOIN budget_accounts AS b
                 ON b.account_id=a.account_id AND b.current_revision=a.revision
               WHERE b.account_id=?""",
            (account_id,),
        ).fetchone()
        if approval is None:
            raise BudgetLedgerError("current budget approval is unavailable")
        try:
            return BudgetContract.model_validate_json(bytes(approval["contract_json"]))
        except (TypeError, ValueError) as exc:
            raise BudgetLedgerError("current budget approval is invalid") from exc


__all__ = [
    "AccountSnapshot",
    "AttemptKey",
    "AttemptSnapshot",
    "BudgetAdmissionProof",
    "BudgetAmounts",
    "BudgetContract",
    "BudgetLedger",
    "BudgetLedgerError",
    "InfrastructureCreatePermit",
    "InfrastructureReserveSnapshot",
    "ProductReserve",
    "ProductSettlementAttempt",
    "ProductSettlementSnapshot",
    "ProviderSpendCapAttestation",
    "RequestPoolReserve",
    "RequestReserve",
    "RoleRate",
    "SQLITE_SAFE_INTEGER_MAX",
    "SettlementNoUsageProof",
    "SendPermit",
    "VerifiedInfrastructureProviderCapCapability",
    "VerifiedTopologyProviderCapCapability",
    "budget_account_identity",
    "budget_contract_hash",
    "derive_role_rate_from_pricing",
    "model_role_budget_identity_hash",
    "role_rate_digest",
    "role_rate_cost",
    "require_verified_infrastructure_provider_capability",
    "require_verified_topology_provider_capability",
    "verify_budget_admission_contract",
]
