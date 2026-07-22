"""Durable, signed run-budget lineage and exactly-once send ownership."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
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
    InfrastructureAuthorization,
    PricingEvidenceApproval,
    ProviderCapApproval,
    ProvisioningAuthorization,
    ProvisioningAuthorizationPayload,
    VerifiedPricingCapability,
    VerifiedProviderCapCapability,
    _require_verified_pricing_capability_for_testing,
    _require_verified_provider_capability_for_testing,
    require_verified_pricing_capability,
    require_verified_provider_capability,
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
_BUSY_TIMEOUT_MS = 30_000
_TESTING_MODE_SENTINEL = object()
_SCHEMA_VERSION = 5
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
        "created_at",
    }
)
_INFRASTRUCTURE_AUTHORIZATION_TABLE_SQL = """CREATE TABLE infrastructure_authorizations (
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
    state TEXT NOT NULL CHECK (state='reserved'),
    created_at TEXT NOT NULL,
    UNIQUE (account_id, operation_id)
)"""
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
    state: Literal["reserved"]


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
        if self.reserve.state != "reserved":
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
                _SCHEMA_VERSION,
            }:
                raise BudgetLedgerError("budget schema migration version is unsupported")
            self._create_base_schema(connection)
            self._migrate_attempt_schema(connection, version)
            self._migrate_pool_schema(connection, version)
            self._migrate_canary_claim_schema(connection, version)
            self._migrate_infrastructure_schema(connection, version)
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
        }
        present = {name for name, columns in actual.items() if columns}
        if not present:
            if version in {
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
        }
        if actual != expected_columns:
            raise BudgetLedgerError("budget infrastructure schema has drifted columns")
        expected_sql = {
            "infrastructure_authorizations": _INFRASTRUCTURE_AUTHORIZATION_TABLE_SQL,
            "infrastructure_reserves": _INFRASTRUCTURE_RESERVE_TABLE_SQL,
        }
        for table_name, sql in expected_sql.items():
            stored = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()
            if stored is None or str(stored["sql"]) != sql:
                raise BudgetLedgerError("budget infrastructure schema definition has drifted")
        if version not in {
            _SCHEMA_VERSION,
        }:
            raise BudgetLedgerError("budget infrastructure schema version does not match tables")

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

        trusted_authorities = self._production_operational_authorities()
        now = self._production_now()

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
        snapshot = self._reserve_infrastructure(
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
        snapshot = self._reserve_infrastructure(
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
    ) -> InfrastructureReserveSnapshot:
        account_id = budget_account_identity(payload.run_identity, payload.purpose)
        envelope_json = canonical_json_bytes(authorization)
        provider_cap_key = self._provider_cap_key(provider_capability)
        with self._mutation() as connection:
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
                total = self._shared_provider_cap_occupied_cost(
                    connection,
                    provider_cap_key,
                    expected_max_cost=provider_capability.max_cost_minor_units,
                    candidate_account_id=account_id,
                )
                if total > provider_capability.max_cost_minor_units:
                    raise BudgetLedgerError("infrastructure reserves exceed provider cap")
                return self._infrastructure_snapshot(connection, existing)

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
            except sqlite3.IntegrityError as exc:
                raise BudgetLedgerError("infrastructure authorization conflict") from exc
            inserted = connection.execute(
                "SELECT * FROM infrastructure_reserves WHERE reserve_id=?",
                (payload.infrastructure_reserve_id,),
            ).fetchone()
            assert inserted is not None
            return self._infrastructure_snapshot(connection, inserted)

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
    def _infrastructure_reserved_cost(
        connection: sqlite3.Connection,
        account_id: str,
    ) -> int:
        row = connection.execute(
            """SELECT COALESCE(SUM(max_cost), 0) FROM infrastructure_reserves
               WHERE account_id=? AND state='reserved'""",
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
                "SELECT * FROM infrastructure_reserves WHERE state='reserved'"
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
            if str(row["domain"]) != PROVISIONING_AUTHORIZATION_DOMAIN:
                raise BudgetLedgerError("stored infrastructure authorization domain is invalid")
            return ProvisioningAuthorization.model_validate_json(bytes(row["envelope_json"]))
        except (TypeError, ValueError) as exc:
            raise BudgetLedgerError("stored infrastructure authorization is invalid") from exc

    @staticmethod
    def _infrastructure_snapshot(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> InfrastructureReserveSnapshot:
        authorization = BudgetLedger._stored_infrastructure_authorization(connection, row)
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
                state=cast(Literal["reserved"], str(row["state"])),
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

    def _require_provider_cap_allows(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        proposed_occupied: BudgetAmounts,
    ) -> None:
        contract = self._current_contract(connection, account_id)
        provider_cap = contract.provider_attestation.max_cost_minor_units
        matching_scope_rows = [
            row
            for row in connection.execute(
                """SELECT * FROM infrastructure_reserves
                   WHERE state='reserved'"""
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
