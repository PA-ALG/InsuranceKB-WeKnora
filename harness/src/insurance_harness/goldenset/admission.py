"""Fail-closed derivation of a Golden-set run-admission decision.

The approved plan may carry cached observations or a previously derived state, but
neither is trusted here.  A caller must supply fresh, code-owned checks for every
required admission dimension and this module derives the decision from those checks.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Literal, Protocol, Self

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StrictStr,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from insurance_harness.goldenset.admission_budget import (
    AccountSnapshot,
    BudgetAdmissionProof,
    BudgetAmounts,
    BudgetContract,
    BudgetLedger,
    BudgetLedgerError,
    role_rate_cost,
    role_rate_digest,
    verify_budget_admission_contract,
)
from insurance_harness.goldenset.admission_identity import (
    DeterministicIdentityInspector,
    IdentityInspectionRequest,
    IdentityInspectionResult,
    identity_contract_hash,
)
from insurance_harness.goldenset.admission_models import (
    AdmissionState,
    ApprovalVerificationError,
    BudgetApprovalEnvelope,
    CanaryReviewApprovalEnvelope,
    CanaryReviewArtifactEvidence,
    ModelRolePlan,
    ProvenanceApprovalEnvelope,
    RunAdmissionPlan,
    canonical_json_bytes,
    plan_payload_hash,
    verify_approval_envelope,
)
from insurance_harness.goldenset.admission_probe import (
    ProbeBlocker,
    ProbeRequest,
    ProbeResult,
    SafeProviderProbe,
)

type NonBlankStr = Annotated[
    StrictStr, StringConstraints(strip_whitespace=True, min_length=1)
]
type Sha256Digest = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

_REQUIRED_CHECK_NAMES = frozenset(
    {
        "budget_approval",
        "budget_ledger",
        "identity",
        "provenance_approval",
        "provider_probe:annotator",
        "provider_probe:judge",
        "provider_probe:weak_extractor",
        "runtime_capability",
    }
)
_CHECKER_VERSION = "020.1"
_RUNTIME_CAPABILITY_VERSION = "budget-ledger-v3-canary-v1"
_PROVENANCE_SCOPE = "provenance:wip-gs-v0.1"
_BUDGET_SCOPE = "budget:gs-v0.1"
_CANARY_REVIEW_SCOPE = "canary-review:gs-v0.1"
_EXECUTION_PLAN_HASH_DOMAIN = b"insurancekb.run-admission.execution-plan.v1\0"
_CANARY_CAPABILITY_DOMAIN = (
    b"insurancekb.run-admission.canary-review-capability.v1\0"
)
_FIRST_CANARY_STAGE: Literal["annotation"] = "annotation"
_FIRST_CANARY_PRODUCT_ID = "平安爱满分（2026）两全保险"
_SECOND_CANARY_STAGE: Literal["annotation"] = "annotation"
_SECOND_CANARY_PRODUCT_ID = "平安附加（2026）意外伤害保险"
_CANARY_QUALITY_THRESHOLD_VERSION = "golden-v0.1-thresholds-v1"
_MAX_DISPUTED_RATE_NUMERATOR = 5
_MAX_DISPUTED_RATE_DENOMINATOR = 100
_CHECK_TTL = timedelta(minutes=5)
# Task 6 provides the guarded client, but production stays fail-closed until Task 7
# proves that every real T2/T4 entrypoint can reach models only through that guard.
_PRODUCTION_RUNTIME_CAPABILITY_READY = True


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
        """Validate updates instead of accepting Pydantic's unchecked update path."""

        if update is None:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


class RunAdmissionDocument(_ImmutableModel):
    """One typed file containing the immutable plan and all deterministic inputs."""

    plan: RunAdmissionPlan
    identity_request: IdentityInspectionRequest
    budget_contract: BudgetContract | None = None


class IdentityAuditBlocker(_ImmutableModel):
    code: NonBlankStr
    subject: StrictStr | None = None
    product_id: StrictStr | None = None


class IdentityAuditEvidence(_ImmutableModel):
    evaluated_revision: NonBlankStr
    identity_contract_hash: Sha256Digest
    product_digests: Mapping[NonBlankStr, Sha256Digest]
    shared_input_digest: Sha256Digest
    execution_surface_digest: Sha256Digest
    blocker_codes: tuple[NonBlankStr, ...]
    blockers: tuple[IdentityAuditBlocker, ...]

    @model_validator(mode="after")
    def freeze_digests(self) -> IdentityAuditEvidence:
        object.__setattr__(
            self,
            "product_digests",
            MappingProxyType(dict(self.product_digests)),
        )
        return self

    @field_serializer("product_digests")
    def serialize_product_digests(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)


class ApprovalAuditEvidence(_ImmutableModel):
    domain: Literal["budget", "provenance"]
    verified: StrictBool
    key_id: StrictStr | None = None
    approver_identity: StrictStr | None = None
    expires_at: datetime | None = None
    blocker_code: NonBlankStr | None = None


class AdmissionEvidence(_ImmutableModel):
    identity: IdentityAuditEvidence
    approvals: tuple[ApprovalAuditEvidence, ...]
    probes: tuple[ProbeResult, ...]
    budget: BudgetAdmissionProof | None = None


class IdentityInspector(Protocol):
    def inspect(self, request: IdentityInspectionRequest) -> IdentityInspectionResult: ...


class ProviderProbe(Protocol):
    def run(self, request: ProbeRequest) -> ProbeResult: ...


class AdmissionCheck(_ImmutableModel):
    """One fresh, bounded observation produced by a code-owned checker."""

    name: NonBlankStr
    passed: StrictBool
    blocker_code: NonBlankStr | None = None
    observed_at: datetime
    expires_at: datetime

    @field_validator("observed_at", "expires_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("admission check timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_result_and_window(self) -> AdmissionCheck:
        if self.expires_at < self.observed_at:
            raise ValueError("expires_at must not precede observed_at")
        if self.passed == (self.blocker_code is not None):
            raise ValueError("passed checks must omit blocker_code; failed checks require it")
        return self


class AdmissionBlocker(_ImmutableModel):
    check: NonBlankStr
    code: NonBlankStr


class AdmissionResult(_ImmutableModel):
    """Redacted, deterministic admission artifact safe to persist."""

    state: AdmissionState
    plan_payload_hash: Sha256Digest
    evaluated_revision: NonBlankStr
    evaluated_at: datetime
    checker_version: NonBlankStr
    runtime_capability_version: NonBlankStr
    checks: tuple[AdmissionCheck, ...]
    blockers: tuple[AdmissionBlocker, ...]
    evidence: AdmissionEvidence | None = None

    @field_validator("evaluated_at")
    @classmethod
    def require_aware_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must include a timezone")
        return value

    @model_validator(mode="after")
    def require_consistent_state(self) -> AdmissionResult:
        if self.state == "READY" and self.blockers:
            raise ValueError("READY admission result must not contain blockers")
        if self.state == "BLOCKED" and not self.blockers:
            raise ValueError("BLOCKED admission result must contain a blocker")
        if tuple(sorted(self.checks, key=lambda item: item.name)) != self.checks:
            raise ValueError("checks must be sorted by name")
        if tuple(sorted(self.blockers, key=lambda item: (item.check, item.code))) != (
            self.blockers
        ):
            raise ValueError("blockers must have deterministic ordering")
        return self


@dataclass(frozen=True, slots=True)
class ExecutionTarget:
    """One process-local stage/product capability; never a persisted decision field."""

    stage: Literal["annotation", "baseline"]
    product_id: str

    def __post_init__(self) -> None:
        if self.stage not in {"annotation", "baseline"}:
            raise ValueError("execution target stage is not controlled")
        if not isinstance(self.product_id, str) or not self.product_id.strip():
            raise ValueError("execution target product_id must be a non-blank string")


def _require_process_expiry(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("execution authorization expiry must include a timezone")


def _require_process_window(evaluated_at: datetime, expires_at: datetime) -> None:
    if (
        not isinstance(evaluated_at, datetime)
        or evaluated_at.tzinfo is None
        or evaluated_at.utcoffset() is None
    ):
        raise ValueError("execution authorization evaluation time must include a timezone")
    _require_process_expiry(expires_at)
    if evaluated_at >= expires_at:
        raise ValueError("execution authorization expiry must follow evaluation")


def _require_process_digest(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"execution authorization {label} digest is invalid")


@dataclass(frozen=True, slots=True)
class InitialExecutionAuthorization:
    """Fresh least-privilege authority for only the code-fixed first canary."""

    targets: tuple[ExecutionTarget, ...]
    account_id: str
    account_revision: int
    account_approval_digest: str
    execution_plan_hash: str
    evaluated_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        expected = (
            ExecutionTarget(
                stage=_FIRST_CANARY_STAGE,
                product_id=_FIRST_CANARY_PRODUCT_ID,
            ),
        )
        if self.targets != expected:
            raise ValueError("initial authorization must contain only the first canary")
        _require_process_digest(self.account_id, "account")
        if type(self.account_revision) is not int or self.account_revision < 1:
            raise ValueError("initial authorization account revision is invalid")
        _require_process_digest(self.account_approval_digest, "account approval")
        _require_process_digest(self.execution_plan_hash, "execution plan")
        _require_process_window(self.evaluated_at, self.expires_at)


@dataclass(frozen=True, slots=True)
class ReviewedExecutionAuthorization:
    """Signed, evidence-bound continuation authority for the second annotation."""

    targets: tuple[ExecutionTarget, ...]
    capability_digest: str
    account_id: str
    settlement_snapshot_digest: str
    artifact_evidence: CanaryReviewArtifactEvidence
    execution_plan_hash: str
    evaluated_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        expected = (
            ExecutionTarget(
                stage=_SECOND_CANARY_STAGE,
                product_id=_SECOND_CANARY_PRODUCT_ID,
            ),
        )
        if self.targets != expected:
            raise ValueError("reviewed authorization must contain only the second canary")
        if not isinstance(self.artifact_evidence, CanaryReviewArtifactEvidence):
            raise ValueError("reviewed authorization requires typed artifact evidence")
        _require_process_digest(self.capability_digest, "capability")
        _require_process_digest(self.account_id, "account")
        _require_process_digest(
            self.settlement_snapshot_digest,
            "settlement snapshot",
        )
        _require_process_digest(self.execution_plan_hash, "execution plan")
        _require_process_window(self.evaluated_at, self.expires_at)


type ExecutionAuthorization = (
    InitialExecutionAuthorization | ReviewedExecutionAuthorization
)


class ExecutionAuthorizationValidationError(ValueError):
    """Fresh last-hop authorization validation failed closed."""


@dataclass(frozen=True, slots=True)
class RuntimeAdmissionDecision:
    """Admission evidence plus non-serialised-by-callers process authority."""

    result: AdmissionResult
    authorization: ExecutionAuthorization | None
    account: AccountSnapshot | None

    def __post_init__(self) -> None:
        if self.result.state == "READY" and (
            self.authorization is None or self.account is None
        ):
            raise ValueError("READY requires authorization and a fresh account snapshot")
        if self.result.state == "BLOCKED" and self.authorization is not None:
            raise ValueError("BLOCKED forbids execution authorization")
        if self.authorization is not None and self.account is not None:
            if self.authorization.account_id != self.account.account_id:
                label = (
                    "initial"
                    if isinstance(self.authorization, InitialExecutionAuthorization)
                    else "reviewed"
                )
                raise ValueError(f"{label} authorization account snapshot is mismatched")
            if isinstance(self.authorization, InitialExecutionAuthorization) and (
                self.authorization.account_revision != self.account.revision
                or self.authorization.account_approval_digest
                != self.account.approval_digest
            ):
                raise ValueError("initial authorization account snapshot is mismatched")


class ArtifactEvidenceInspectionError(ValueError):
    """A semantic failure to obtain current content-addressed canary evidence."""


class CanaryReviewSource(Protocol):
    def __call__(self) -> CanaryReviewApprovalEnvelope | None: ...


class ArtifactEvidenceInspector(Protocol):
    def inspect(
        self,
        *,
        execution_plan_hash: str,
        canary_target: ExecutionTarget,
    ) -> CanaryReviewArtifactEvidence: ...


class _UnavailableArtifactEvidenceInspector:
    def inspect(
        self,
        *,
        execution_plan_hash: str,
        canary_target: ExecutionTarget,
    ) -> CanaryReviewArtifactEvidence:
        del execution_plan_hash, canary_target
        raise ArtifactEvidenceInspectionError("artifact evidence inspector is unavailable")


def execution_plan_hash(document: RunAdmissionDocument) -> str:
    """Hash only immutable pre-execution inputs, excluding approvals and outputs."""

    preimage = {
        "budget_contract": document.budget_contract,
        "identity_request": document.identity_request,
        "plan_payload": document.plan.payload,
    }
    return hashlib.sha256(
        _EXECUTION_PLAN_HASH_DOMAIN + canonical_json_bytes(preimage)
    ).hexdigest()


def canary_review_capability_digest(
    envelope: CanaryReviewApprovalEnvelope,
) -> str:
    """Return the domain-separated identity of the complete signed review envelope."""

    return hashlib.sha256(
        _CANARY_CAPABILITY_DOMAIN + canonical_json_bytes(envelope)
    ).hexdigest()


def required_admission_check_names() -> frozenset[str]:
    """Return the exact, code-owned checks required for a READY decision."""

    return _REQUIRED_CHECK_NAMES


def derive_admission_result(
    *,
    plan: RunAdmissionPlan,
    checks: tuple[AdmissionCheck, ...],
    evaluated_revision: str,
    evaluated_at: datetime,
    checker_version: str,
    runtime_capability_version: str,
    additional_blockers: tuple[AdmissionBlocker, ...] = (),
    evidence: AdmissionEvidence | None = None,
) -> AdmissionResult:
    """Derive READY/BLOCKED without trusting state stored in the input plan."""

    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must include a timezone")

    checks_by_name: dict[str, AdmissionCheck] = {}
    duplicate_names: set[str] = set()
    for supplied_check in checks:
        if supplied_check.name in checks_by_name:
            duplicate_names.add(supplied_check.name)
        else:
            checks_by_name[supplied_check.name] = supplied_check

    blockers: list[AdmissionBlocker] = []
    for name in sorted(_REQUIRED_CHECK_NAMES):
        check = checks_by_name.get(name)
        if check is None:
            blockers.append(
                AdmissionBlocker(check=name, code="required_check_missing")
            )
            continue
        if name in duplicate_names:
            blockers.append(AdmissionBlocker(check=name, code="duplicate_check"))
        elif evaluated_at < check.observed_at or evaluated_at >= check.expires_at:
            blockers.append(AdmissionBlocker(check=name, code="observation_expired"))
        elif not check.passed:
            # AdmissionCheck validation guarantees a failed check has a redacted code.
            blockers.append(
                AdmissionBlocker(check=name, code=check.blocker_code or "check_failed")
            )

    for name in sorted(set(checks_by_name) - _REQUIRED_CHECK_NAMES):
        blockers.append(AdmissionBlocker(check=name, code="unexpected_check"))

    blockers.extend(additional_blockers)

    ordered_checks = tuple(sorted(checks, key=lambda item: item.name))
    ordered_blockers = tuple(
        sorted(
            set((blocker.check, blocker.code) for blocker in blockers),
            key=lambda item: item,
        )
    )
    typed_blockers = tuple(
        AdmissionBlocker(check=check, code=code) for check, code in ordered_blockers
    )
    state: Literal["READY", "BLOCKED"] = "BLOCKED" if typed_blockers else "READY"
    return AdmissionResult(
        state=state,
        plan_payload_hash=plan_payload_hash(plan),
        evaluated_revision=evaluated_revision,
        evaluated_at=evaluated_at,
        checker_version=checker_version,
        runtime_capability_version=runtime_capability_version,
        checks=ordered_checks,
        blockers=typed_blockers,
        evidence=evidence,
    )


class ProductionAdmissionEvaluator:
    """Aggregate the code-owned identity, approval, budget, and probe checks."""

    def __init__(
        self,
        *,
        repo_root: Path,
        trusted_public_keys: Mapping[str, Ed25519PublicKey] | None = None,
        allowed_budget_roles: frozenset[str] = frozenset(),
        allowed_provenance_roles: frozenset[str] = frozenset(),
        probe: bool = False,
    ) -> None:
        self._initialize(
            identity_inspector=DeterministicIdentityInspector(repo_root=repo_root),
            provider_probe=SafeProviderProbe(),
            trusted_public_keys=trusted_public_keys or {},
            allowed_budget_roles=allowed_budget_roles,
            allowed_provenance_roles=allowed_provenance_roles,
            allowed_canary_review_roles=frozenset(),
            canary_review_source=None,
            artifact_evidence_inspector=None,
            probe=probe,
            clock=lambda: datetime.now(UTC),
            runtime_capability_ready=_PRODUCTION_RUNTIME_CAPABILITY_READY,
        )

    @classmethod
    def _for_production_canary(
        cls,
        *,
        repo_root: Path,
        trusted_public_keys: Mapping[str, Ed25519PublicKey],
        allowed_budget_roles: frozenset[str],
        allowed_provenance_roles: frozenset[str],
        allowed_canary_review_roles: frozenset[str],
        canary_review_source: CanaryReviewSource,
        artifact_evidence_inspector: ArtifactEvidenceInspector,
        probe: bool = False,
    ) -> ProductionAdmissionEvaluator:
        """Private production seam for Task 9's code-owned deployment loaders."""

        instance = cls.__new__(cls)
        instance._initialize(
            identity_inspector=DeterministicIdentityInspector(repo_root=repo_root),
            provider_probe=SafeProviderProbe(),
            trusted_public_keys=trusted_public_keys,
            allowed_budget_roles=allowed_budget_roles,
            allowed_provenance_roles=allowed_provenance_roles,
            allowed_canary_review_roles=allowed_canary_review_roles,
            canary_review_source=canary_review_source,
            artifact_evidence_inspector=artifact_evidence_inspector,
            probe=probe,
            clock=lambda: datetime.now(UTC),
            runtime_capability_ready=_PRODUCTION_RUNTIME_CAPABILITY_READY,
        )
        return instance

    @classmethod
    def _for_testing(
        cls,
        *,
        identity_inspector: IdentityInspector,
        provider_probe: ProviderProbe,
        trusted_public_keys: Mapping[str, Ed25519PublicKey],
        probe: bool,
        clock: Callable[[], datetime],
        runtime_capability_ready: bool,
        allowed_budget_roles: frozenset[str] = frozenset({"budget_approver"}),
        allowed_provenance_roles: frozenset[str] = frozenset(
            {"provenance_approver"}
        ),
        allowed_canary_review_roles: frozenset[str] = frozenset(),
        canary_review_source: CanaryReviewSource | None = None,
        artifact_evidence_inspector: ArtifactEvidenceInspector | None = None,
    ) -> ProductionAdmissionEvaluator:
        instance = cls.__new__(cls)
        instance._initialize(
            identity_inspector=identity_inspector,
            provider_probe=provider_probe,
            trusted_public_keys=trusted_public_keys,
            allowed_budget_roles=allowed_budget_roles,
            allowed_provenance_roles=allowed_provenance_roles,
            allowed_canary_review_roles=allowed_canary_review_roles,
            canary_review_source=canary_review_source,
            artifact_evidence_inspector=artifact_evidence_inspector,
            probe=probe,
            clock=clock,
            runtime_capability_ready=runtime_capability_ready,
        )
        return instance

    def _initialize(
        self,
        *,
        identity_inspector: IdentityInspector,
        provider_probe: ProviderProbe,
        trusted_public_keys: Mapping[str, Ed25519PublicKey],
        allowed_budget_roles: frozenset[str],
        allowed_provenance_roles: frozenset[str],
        allowed_canary_review_roles: frozenset[str],
        canary_review_source: CanaryReviewSource | None,
        artifact_evidence_inspector: ArtifactEvidenceInspector | None,
        probe: bool,
        clock: Callable[[], datetime],
        runtime_capability_ready: bool,
    ) -> None:
        self._identity_inspector = identity_inspector
        self._provider_probe = provider_probe
        self._trusted_public_keys = MappingProxyType(dict(trusted_public_keys))
        self._allowed_budget_roles = allowed_budget_roles
        self._allowed_provenance_roles = allowed_provenance_roles
        self._allowed_canary_review_roles = allowed_canary_review_roles
        self._canary_review_source = canary_review_source or (lambda: None)
        self._artifact_evidence_inspector = (
            artifact_evidence_inspector or _UnavailableArtifactEvidenceInspector()
        )
        self._probe = probe
        self._clock = clock
        self._runtime_capability_ready = runtime_capability_ready

    @staticmethod
    def _check(
        *,
        name: str,
        passed: bool,
        now: datetime,
        blocker_code: str | None = None,
        expires_at: datetime | None = None,
    ) -> AdmissionCheck:
        return AdmissionCheck(
            name=name,
            passed=passed,
            blocker_code=blocker_code,
            observed_at=now,
            expires_at=expires_at or now + _CHECK_TTL,
        )

    @staticmethod
    def _audit_label(value: str | None) -> str | None:
        if value is None or len(value) > 200:
            return None
        if "/" in value or "\\" in value or any(ord(character) < 32 for character in value):
            return None
        return value

    def __call__(self, document: RunAdmissionDocument) -> AdmissionResult:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("admission evaluator clock must include a timezone")

        identity = self._identity_inspector.inspect(document.identity_request)
        observed_identity_contract_hash = identity_contract_hash(
            document.identity_request
        )
        identity_codes: tuple[str, ...] = tuple(
            sorted(blocker.code for blocker in identity.blockers)
        )
        if (
            document.plan.payload.identity_contract_hash
            != observed_identity_contract_hash
        ):
            identity_codes = tuple(
                sorted((*identity_codes, "identity_contract_mismatch"))
            )
        checks: list[AdmissionCheck] = [
            self._check(
                name="identity",
                passed=not identity_codes,
                blocker_code=identity_codes[0] if identity_codes else None,
                now=now,
            )
        ]
        diagnostics = [
            AdmissionBlocker(check="identity", code=code) for code in identity_codes
        ]

        provenance_check, provenance_evidence, provenance_diagnostics = (
            self._evaluate_provenance(document, now)
        )
        budget_check, ledger_check, budget_evidence, budget_audit, budget_diagnostics = (
            self._evaluate_budget(document, now)
        )
        checks.extend((provenance_check, budget_check, ledger_check))
        diagnostics.extend((*provenance_diagnostics, *budget_diagnostics))

        probe_results: list[ProbeResult] = []
        probe_roles: tuple[
            Literal["annotator", "weak_extractor", "judge"], ...
        ] = ("annotator", "weak_extractor", "judge")
        for role in probe_roles:
            role_plan = document.plan.payload.model_roles[role]
            check_name = f"provider_probe:{role}"
            primary_code: str | None
            if not isinstance(role_plan, ModelRolePlan):
                result = ProbeResult(
                    role=role,
                    verified=False,
                    provider=role_plan.provider,
                    model_id=role_plan.model_id,
                    blockers=(
                        ProbeBlocker(
                            code="model_identity_pending",
                            message="signed immutable model identity is pending",
                        ),
                    ),
                )
                primary_code = "model_identity_pending"
            else:
                result = self._provider_probe.run(
                    ProbeRequest(
                        role=role,
                        role_plan=role_plan,
                        mode="remote" if self._probe else "static",
                        price_observed_at=(
                            document.budget_contract.price_observed_at
                            if document.budget_contract is not None
                            else None
                        ),
                    )
                )
                primary_code = result.blockers[0].code if result.blockers else None
            probe_results.append(result)
            checks.append(
                self._check(
                    name=check_name,
                    passed=result.verified,
                    blocker_code=primary_code,
                    now=now,
                )
            )
            diagnostics.extend(
                AdmissionBlocker(check=check_name, code=blocker.code)
                for blocker in result.blockers
            )

        runtime_passed = self._runtime_capability_ready
        checks.append(
            self._check(
                name="runtime_capability",
                passed=runtime_passed,
                blocker_code=None if runtime_passed else "runtime_capability_unattested",
                now=now,
            )
        )

        decision_time = self._clock()
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            raise ValueError("admission decision clock must include a timezone")
        if decision_time < now:
            raise ValueError("admission decision clock moved backwards")

        evidence = AdmissionEvidence(
            identity=IdentityAuditEvidence(
                evaluated_revision=identity.evaluated_revision,
                identity_contract_hash=observed_identity_contract_hash,
                product_digests=identity.product_digests,
                shared_input_digest=identity.shared_input_digest,
                execution_surface_digest=identity.execution_surface_digest,
                blocker_codes=identity_codes,
                blockers=tuple(
                    IdentityAuditBlocker(
                        code=blocker.code,
                        subject=self._audit_label(blocker.subject),
                        product_id=self._audit_label(blocker.product_id),
                    )
                    for blocker in identity.blockers
                ),
            ),
            approvals=(provenance_evidence, budget_audit),
            probes=tuple(probe_results),
            budget=budget_evidence,
        )
        return derive_admission_result(
            plan=document.plan,
            checks=tuple(checks),
            evaluated_revision=identity.evaluated_revision,
            evaluated_at=decision_time,
            checker_version=_CHECKER_VERSION,
            runtime_capability_version=_RUNTIME_CAPABILITY_VERSION,
            additional_blockers=tuple(diagnostics),
            evidence=evidence,
        )

    def admit_budget_account(
        self,
        document: RunAdmissionDocument,
        ledger: BudgetLedger,
    ) -> tuple[AdmissionResult, AccountSnapshot | None]:
        """Re-evaluate admission and open its signed budget account only when READY."""

        result = self(document)
        if result.state != "READY":
            return result, None
        contract = document.budget_contract
        if contract is None:  # Defensive: READY construction already requires this.
            raise BudgetLedgerError("READY admission is missing its budget contract")
        envelopes = tuple(
            item
            for item in document.plan.approval_envelopes
            if isinstance(item, BudgetApprovalEnvelope)
        )
        if len(envelopes) != 1:  # Defensive: READY construction already requires this.
            raise BudgetLedgerError("READY admission requires one budget approval")
        account = ledger.open_or_expand_account(
            plan=document.plan.payload,
            contract=contract,
            envelope=envelopes[0],
            trusted_public_keys=self._trusted_public_keys,
            expected_scope=_BUDGET_SCOPE,
            authorized_roles=self._allowed_budget_roles,
            now=result.evaluated_at,
        )
        return result, account

    def evaluate_execution(
        self,
        document: RunAdmissionDocument,
        ledger: BudgetLedger,
    ) -> RuntimeAdmissionDecision:
        """Freshly derive process-only authority from admission and detached review."""

        result, account = self.admit_budget_account(document, ledger)
        if result.state != "READY" or account is None:
            return RuntimeAdmissionDecision(
                result=result,
                authorization=None,
                account=None,
            )

        review = self._canary_review_source()
        if review is None:
            if not self._identity_contains(document, _FIRST_CANARY_PRODUCT_ID):
                return self._blocked_execution(
                    result,
                    "initial_canary_identity_missing",
                    account=account,
                )
            final_now = self._final_execution_time(result)
            if not self._base_checks_are_fresh(result, final_now):
                return self._blocked_execution(
                    result,
                    "execution_authorization_expired",
                    account=account,
                )
            return RuntimeAdmissionDecision(
                result=result,
                authorization=InitialExecutionAuthorization(
                    targets=(
                        ExecutionTarget(
                            stage=_FIRST_CANARY_STAGE,
                            product_id=_FIRST_CANARY_PRODUCT_ID,
                        ),
                    ),
                    account_id=account.account_id,
                    account_revision=account.revision,
                    account_approval_digest=account.approval_digest,
                    execution_plan_hash=execution_plan_hash(document),
                    evaluated_at=result.evaluated_at,
                    expires_at=self._base_checks_expiry(result),
                ),
                account=account,
            )

        return self._evaluate_canary_review(
            document=document,
            ledger=ledger,
            result=result,
            account=account,
            review=review,
        )

    def revalidate_initial_authorization(
        self,
        document: RunAdmissionDocument,
        authorization: InitialExecutionAuthorization,
    ) -> None:
        """Recheck an initial authority's time and immutable plan bindings."""

        self._revalidate_authorization_window_and_plan(
            document,
            authorization,
            label="initial",
        )

    def revalidate_review_authorization(
        self,
        document: RunAdmissionDocument,
        authorization: ReviewedExecutionAuthorization,
    ) -> None:
        """Recheck process-only review bindings at the runtime's final hop."""

        self._revalidate_authorization_window_and_plan(
            document,
            authorization,
            label="reviewed",
        )
        try:
            observed = self._artifact_evidence_inspector.inspect(
                execution_plan_hash=authorization.execution_plan_hash,
                canary_target=ExecutionTarget(
                    stage=_FIRST_CANARY_STAGE,
                    product_id=_FIRST_CANARY_PRODUCT_ID,
                ),
            )
        except ArtifactEvidenceInspectionError as exc:
            raise ExecutionAuthorizationValidationError(
                "reviewed execution authorization artifact is unavailable"
            ) from exc
        if observed != authorization.artifact_evidence:
            raise ExecutionAuthorizationValidationError(
                "reviewed execution authorization artifact drifted"
            )

    def _revalidate_authorization_window_and_plan(
        self,
        document: RunAdmissionDocument,
        authorization: ExecutionAuthorization,
        *,
        label: Literal["initial", "reviewed"],
    ) -> None:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("authorization validation clock must include a timezone")
        if now < authorization.evaluated_at:
            raise ExecutionAuthorizationValidationError(
                f"{label} execution authorization clock moved backwards"
            )
        if now >= authorization.expires_at:
            raise ExecutionAuthorizationValidationError(
                f"{label} execution authorization expired"
            )
        if execution_plan_hash(document) != authorization.execution_plan_hash:
            raise ExecutionAuthorizationValidationError(
                f"{label} execution authorization plan drifted"
            )

    @staticmethod
    def _identity_contains(document: RunAdmissionDocument, product_id: str) -> bool:
        return any(
            product.product_id == product_id
            for product in document.identity_request.products
        )

    def _final_execution_time(self, result: AdmissionResult) -> datetime:
        final_now = self._clock()
        if final_now.tzinfo is None or final_now.utcoffset() is None:
            raise ValueError("execution authorization clock must include a timezone")
        if final_now < result.evaluated_at:
            raise ValueError("execution authorization clock moved backwards")
        return final_now

    @staticmethod
    def _base_checks_expiry(result: AdmissionResult) -> datetime:
        if not result.checks:
            raise ValueError("execution authorization requires admission checks")
        return min(check.expires_at for check in result.checks)

    @staticmethod
    def _base_checks_are_fresh(result: AdmissionResult, now: datetime) -> bool:
        return all(
            check.observed_at <= now < check.expires_at for check in result.checks
        )

    @staticmethod
    def _blocked_execution(
        result: AdmissionResult,
        code: str,
        *,
        account: AccountSnapshot | None = None,
    ) -> RuntimeAdmissionDecision:
        blockers = tuple(
            AdmissionBlocker(check=check, code=blocker_code)
            for check, blocker_code in sorted(
                {
                    *((item.check, item.code) for item in result.blockers),
                    ("canary_review", code),
                }
            )
        )
        blocked = result.model_copy(update={"state": "BLOCKED", "blockers": blockers})
        return RuntimeAdmissionDecision(
            result=blocked,
            authorization=None,
            account=account,
        )

    @staticmethod
    def _amounts_fit(value: BudgetAmounts, maximum: BudgetAmounts) -> bool:
        return (
            value.input_tokens <= maximum.input_tokens
            and value.output_tokens <= maximum.output_tokens
            and value.cost_minor_units <= maximum.cost_minor_units
        )

    @classmethod
    def _settlement_is_eligible(
        cls,
        *,
        document: RunAdmissionDocument,
        ledger: BudgetLedger,
        account: AccountSnapshot,
    ) -> tuple[bool, BudgetAmounts | None, str | None]:
        contract = document.budget_contract
        if contract is None or account.overage:
            return False, None, None
        try:
            snapshot = ledger.product_settlement_snapshot(
                account.account_id,
                _FIRST_CANARY_STAGE,
                _FIRST_CANARY_PRODUCT_ID,
            )
        except BudgetLedgerError:
            return False, None, None
        if (
            snapshot.account_id != account.account_id
            or snapshot.budget_revision != account.revision
            or snapshot.approval_digest != account.approval_digest
            or snapshot.stage != _FIRST_CANARY_STAGE
            or snapshot.product_id != _FIRST_CANARY_PRODUCT_ID
            or snapshot.reservation_state != "settled"
            or not snapshot.attempts
        ):
            return False, None, None

        input_tokens = 0
        output_tokens = 0
        cost_minor_units = 0
        for attempt in snapshot.attempts:
            if (
                attempt.role != "annotator"
                or attempt.state != "terminal"
                or not attempt.usage_verified
                or attempt.response_digest is None
                or attempt.no_usage_proof is not None
                or not cls._amounts_fit(attempt.actual, attempt.maximum)
            ):
                return False, None, None
            expected_cost = role_rate_cost(
                contract.role_rates["annotator"],
                input_tokens=attempt.actual.input_tokens,
                output_tokens=attempt.actual.output_tokens,
            )
            if attempt.actual.cost_minor_units != expected_cost:
                return False, None, None
            input_tokens += attempt.actual.input_tokens
            output_tokens += attempt.actual.output_tokens
            cost_minor_units += attempt.actual.cost_minor_units
        total = BudgetAmounts(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_minor_units=cost_minor_units,
        )
        if total != snapshot.reservation_actual:
            return False, None, None
        return True, total, ledger.product_settlement_snapshot_digest(snapshot)

    def _evaluate_canary_review(
        self,
        *,
        document: RunAdmissionDocument,
        ledger: BudgetLedger,
        result: AdmissionResult,
        account: AccountSnapshot,
        review: CanaryReviewApprovalEnvelope,
    ) -> RuntimeAdmissionDecision:
        payload = review.payload

        def blocked(code: str) -> RuntimeAdmissionDecision:
            return self._blocked_execution(result, code, account=account)

        try:
            verify_approval_envelope(
                review,
                expected_domain="canary-review",
                expected_plan_payload_hash=plan_payload_hash(document.plan),
                expected_run_identity=document.plan.payload.run_identity,
                expected_purpose=document.plan.payload.purpose,
                expected_scope=_CANARY_REVIEW_SCOPE,
                trusted_public_keys=self._trusted_public_keys,
                allowed_roles=self._allowed_canary_review_roles,
                now=result.evaluated_at,
            )
        except ApprovalVerificationError:
            return blocked("canary_review_invalid")

        if payload.review_decision != "approved":
            return blocked("canary_review_rejected")

        signed_targets = tuple(
            (target.stage, target.product_id) for target in payload.granted_targets
        )
        required_targets = ((_SECOND_CANARY_STAGE, _SECOND_CANARY_PRODUCT_ID),)
        if signed_targets != required_targets or not self._identity_contains(
            document, _SECOND_CANARY_PRODUCT_ID
        ):
            return blocked("canary_review_grants_invalid")

        if payload.execution_plan_hash != execution_plan_hash(document):
            return blocked("canary_review_execution_plan_mismatch")
        if payload.evaluated_revision != result.evaluated_revision:
            return blocked("canary_review_revision_mismatch")
        if payload.runtime_capability_version != result.runtime_capability_version:
            return blocked("canary_review_runtime_mismatch")
        if (
            payload.budget_account_identity != account.account_id
            or payload.budget_revision != account.revision
            or payload.budget_approval_digest != account.approval_digest
        ):
            return blocked("canary_review_budget_mismatch")

        eligible, actual, settlement_digest = self._settlement_is_eligible(
            document=document,
            ledger=ledger,
            account=account,
        )
        if not eligible or actual is None or settlement_digest is None:
            return blocked("canary_review_settlement_ineligible")
        if payload.settlement_snapshot_digest != settlement_digest:
            return blocked("canary_review_settlement_mismatch")

        try:
            observed_artifacts = self._artifact_evidence_inspector.inspect(
                execution_plan_hash=payload.execution_plan_hash,
                canary_target=ExecutionTarget(
                    stage=_FIRST_CANARY_STAGE,
                    product_id=_FIRST_CANARY_PRODUCT_ID,
                ),
            )
        except ArtifactEvidenceInspectionError:
            return blocked("canary_review_artifact_unavailable")
        if observed_artifacts != payload.artifacts:
            return blocked("canary_review_artifact_mismatch")
        if (
            observed_artifacts.quality_threshold_version
            != _CANARY_QUALITY_THRESHOLD_VERSION
            or observed_artifacts.disputed_count * _MAX_DISPUTED_RATE_DENOMINATOR
            > observed_artifacts.record_count * _MAX_DISPUTED_RATE_NUMERATOR
        ):
            return blocked("canary_review_quality_ineligible")

        contract = document.budget_contract
        assert contract is not None
        usage = payload.provider_usage
        if (
            usage.role != "annotator"
            or usage.input_tokens != actual.input_tokens
            or usage.output_tokens != actual.output_tokens
            or usage.cost_minor_units != actual.cost_minor_units
            or usage.role_rate_digest
            != role_rate_digest(contract.role_rates["annotator"])
        ):
            return blocked("canary_review_usage_mismatch")

        final_now = self._final_execution_time(result)
        if not self._base_checks_are_fresh(result, final_now):
            return blocked("execution_authorization_expired")
        try:
            verify_approval_envelope(
                review,
                expected_domain="canary-review",
                expected_plan_payload_hash=plan_payload_hash(document.plan),
                expected_run_identity=document.plan.payload.run_identity,
                expected_purpose=document.plan.payload.purpose,
                expected_scope=_CANARY_REVIEW_SCOPE,
                trusted_public_keys=self._trusted_public_keys,
                allowed_roles=self._allowed_canary_review_roles,
                now=final_now,
            )
        except ApprovalVerificationError:
            return blocked("canary_review_invalid")

        return RuntimeAdmissionDecision(
            result=result,
            authorization=ReviewedExecutionAuthorization(
                targets=(
                    ExecutionTarget(
                        stage=_SECOND_CANARY_STAGE,
                        product_id=_SECOND_CANARY_PRODUCT_ID,
                    ),
                ),
                capability_digest=canary_review_capability_digest(review),
                account_id=account.account_id,
                settlement_snapshot_digest=payload.settlement_snapshot_digest,
                artifact_evidence=payload.artifacts,
                execution_plan_hash=payload.execution_plan_hash,
                evaluated_at=result.evaluated_at,
                expires_at=min(
                    self._base_checks_expiry(result),
                    payload.expires_at,
                ),
            ),
            account=account,
        )

    def _evaluate_provenance(
        self,
        document: RunAdmissionDocument,
        now: datetime,
    ) -> tuple[AdmissionCheck, ApprovalAuditEvidence, tuple[AdmissionBlocker, ...]]:
        envelopes = tuple(
            item
            for item in document.plan.approval_envelopes
            if isinstance(item, ProvenanceApprovalEnvelope)
        )
        code: str | None = None
        verified = False
        envelope = envelopes[0] if len(envelopes) == 1 else None
        if not envelopes:
            code = "approval_missing"
        elif len(envelopes) != 1:
            code = "approval_ambiguous"
        else:
            assert envelope is not None
            try:
                verify_approval_envelope(
                    envelope,
                    expected_domain="provenance",
                    expected_plan_payload_hash=plan_payload_hash(document.plan),
                    expected_run_identity=document.plan.payload.run_identity,
                    expected_purpose=document.plan.payload.purpose,
                    expected_scope=_PROVENANCE_SCOPE,
                    trusted_public_keys=self._trusted_public_keys,
                    allowed_roles=self._allowed_provenance_roles,
                    now=now,
                )
                if canonical_json_bytes(envelope.payload.product_entries) != (
                    canonical_json_bytes(document.identity_request.historical_provenance)
                ):
                    code = "approval_entries_mismatch"
                else:
                    verified = True
            except ApprovalVerificationError:
                code = "approval_invalid"
        check = self._check(
            name="provenance_approval",
            passed=verified,
            blocker_code=code,
            now=now,
            expires_at=envelope.payload.expires_at if verified and envelope else None,
        )
        evidence = ApprovalAuditEvidence(
            domain="provenance",
            verified=verified,
            key_id=envelope.key_id if verified and envelope else None,
            approver_identity=(
                envelope.payload.approver_identity if verified and envelope else None
            ),
            expires_at=envelope.payload.expires_at if verified and envelope else None,
            blocker_code=code,
        )
        diagnostics = (
            (AdmissionBlocker(check="provenance_approval", code=code),)
            if code is not None
            else ()
        )
        return check, evidence, diagnostics

    def _evaluate_budget(
        self,
        document: RunAdmissionDocument,
        now: datetime,
    ) -> tuple[
        AdmissionCheck,
        AdmissionCheck,
        BudgetAdmissionProof | None,
        ApprovalAuditEvidence,
        tuple[AdmissionBlocker, ...],
    ]:
        envelopes = tuple(
            item
            for item in document.plan.approval_envelopes
            if isinstance(item, BudgetApprovalEnvelope)
        )
        envelope = envelopes[0] if len(envelopes) == 1 else None
        proof: BudgetAdmissionProof | None = None
        if document.budget_contract is None:
            code = "budget_contract_missing"
        elif not envelopes:
            code = "approval_missing"
        elif len(envelopes) != 1:
            code = "approval_ambiguous"
        else:
            assert envelope is not None
            try:
                proof = verify_budget_admission_contract(
                    plan=document.plan.payload,
                    contract=document.budget_contract,
                    envelope=envelope,
                    trusted_public_keys=self._trusted_public_keys,
                    expected_scope=_BUDGET_SCOPE,
                    authorized_roles=self._allowed_budget_roles,
                    now=now,
                )
                code = None
            except BudgetLedgerError:
                code = "budget_approval_invalid"
        verified = proof is not None
        expiry = (
            min(
                proof.price_expires_at,
                proof.provider_attestation_expires_at,
                envelope.payload.expires_at,
            )
            if proof is not None and envelope is not None
            else None
        )
        approval_check = self._check(
            name="budget_approval",
            passed=verified,
            blocker_code=code,
            now=now,
            expires_at=expiry,
        )
        ledger_check = self._check(
            name="budget_ledger",
            passed=verified,
            blocker_code=None if verified else "budget_not_admitted",
            now=now,
            expires_at=expiry,
        )
        audit = ApprovalAuditEvidence(
            domain="budget",
            verified=verified,
            key_id=envelope.key_id if verified and envelope else None,
            approver_identity=(
                envelope.payload.approver_identity if verified and envelope else None
            ),
            expires_at=envelope.payload.expires_at if verified and envelope else None,
            blocker_code=code,
        )
        diagnostics = tuple(
            AdmissionBlocker(check=check, code=blocker_code)
            for check, blocker_code in (
                ("budget_approval", code),
                ("budget_ledger", None if verified else "budget_not_admitted"),
            )
            if blocker_code is not None
        )
        return approval_check, ledger_check, proof, audit, diagnostics


__all__ = [
    "AdmissionBlocker",
    "AdmissionCheck",
    "AdmissionEvidence",
    "AdmissionResult",
    "ArtifactEvidenceInspectionError",
    "ArtifactEvidenceInspector",
    "ApprovalAuditEvidence",
    "CanaryReviewSource",
    "ExecutionAuthorization",
    "ExecutionAuthorizationValidationError",
    "ExecutionTarget",
    "IdentityAuditEvidence",
    "InitialExecutionAuthorization",
    "ProductionAdmissionEvaluator",
    "ReviewedExecutionAuthorization",
    "RunAdmissionDocument",
    "RuntimeAdmissionDecision",
    "canary_review_capability_digest",
    "derive_admission_result",
    "execution_plan_hash",
    "required_admission_check_names",
]
