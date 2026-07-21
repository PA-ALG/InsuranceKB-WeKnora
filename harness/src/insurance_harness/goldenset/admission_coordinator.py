"""Pure O8 operational-admission state projection.

Provider mutations, signatures, and durable budget writes deliberately remain in
their owning modules.  This module only decides which transition is permitted and
summarises the already-verified 020 admission result.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, StrictStr, StringConstraints

from insurance_harness.goldenset.admission import AdmissionResult, RunAdmissionDocument
from insurance_harness.goldenset.admission_budget import (
    AccountSnapshot,
    BudgetContract,
    BudgetLedger,
    BudgetLedgerError,
    FinalInfrastructureBindingRequest,
    InfrastructureReserveSnapshot,
)
from insurance_harness.goldenset.admission_infrastructure import (
    AuthorizationVerificationError,
    require_verified_reconciled_receipt,
)
from insurance_harness.goldenset.admission_models import (
    BudgetApprovalEnvelope,
    ModelRolePlan,
    TrustedAuthority,
    plan_payload_hash,
)

type NonBlankStr = Annotated[
    StrictStr, StringConstraints(strip_whitespace=True, min_length=1)
]
type OperationalPhase = Literal[
    "receipt",
    "adoption_approval",
    "preauthorization",
    "reserve",
    "create_or_reconcile",
    "final_plan",
    "sign",
    "admit",
    "probe",
    "ready",
]
type EvidenceStatus = Literal["missing", "verified", "expired", "invalid"]


class AdmissionEvaluator(Protocol):
    def __call__(self, document: RunAdmissionDocument) -> AdmissionResult: ...


class FinalAdmissionEvaluator(Protocol):
    def admit_budget_account(
        self, document: RunAdmissionDocument, ledger: BudgetLedger
    ) -> tuple[AdmissionResult, AccountSnapshot | None]: ...


class _ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class OperationalBlocker(_ImmutableModel):
    phase: OperationalPhase
    code: NonBlankStr


class OperationalRunResult(_ImmutableModel):
    state: Literal["BLOCKED", "READY"]
    phase: OperationalPhase
    blockers: tuple[OperationalBlocker, ...]
    probes: int = Field(ge=0)
    verified_probes: int = Field(ge=0)
    controller_inference_requests: Literal[0] = 0
    candidate_deployed_models: tuple[NonBlankStr, ...] = ()
    cost_exposure: Literal[
        "bounded_by_verified_provider_cap",
        "continuing_unbounded_until_signed_cap",
    ]


class ExistingOperationalRunRequest(_ImmutableModel):
    """Read-only evidence snapshot for the preexisting-resource path."""

    flow: Literal["existing"] = "existing"
    run_identity: NonBlankStr
    purpose: NonBlankStr
    scope: NonBlankStr
    strong_candidate_deployed_model: NonBlankStr
    weak_candidate_deployed_model: NonBlankStr
    report_root: Path
    strong_adoption_authorization_present: bool = False
    weak_adoption_authorization_present: bool = False
    signed_pricing_present: bool = False
    signed_provider_cap_present: bool = False
    receipts_verified: bool = False
    reserves_verified: bool = False
    final_document: RunAdmissionDocument | None = None


class NewOperationalRunSnapshot(_ImmutableModel):
    """Read-only projection inputs for the future-create path."""

    flow: Literal["new"] = "new"
    run_identity: NonBlankStr
    purpose: NonBlankStr
    scope: NonBlankStr
    provisioning_authorization: EvidenceStatus = "missing"
    signed_pricing: EvidenceStatus = "missing"
    signed_provider_cap: EvidenceStatus = "missing"
    reserve: EvidenceStatus = "missing"
    receipt: EvidenceStatus = "missing"
    final_plan: EvidenceStatus = "missing"
    signatures: EvidenceStatus = "missing"
    admission_result: AdmissionResult | None = None


class ExistingOperationalRunSnapshot(_ImmutableModel):
    """Read-only projection inputs for the preexisting-adoption path."""

    flow: Literal["existing"] = "existing"
    run_identity: NonBlankStr
    purpose: NonBlankStr
    scope: NonBlankStr
    candidate_deployed_models: tuple[NonBlankStr, NonBlankStr]
    receipt: EvidenceStatus = "missing"
    adoption_authorization: EvidenceStatus = "missing"
    signed_pricing: EvidenceStatus = "missing"
    signed_provider_cap: EvidenceStatus = "missing"
    reserve: EvidenceStatus = "missing"
    final_plan: EvidenceStatus = "missing"
    signatures: EvidenceStatus = "missing"
    admission_result: AdmissionResult | None = None


@dataclass(frozen=True, slots=True)
class OperationalFinalizationRequest:
    document: RunAdmissionDocument
    strong: FinalInfrastructureBindingRequest
    weak: FinalInfrastructureBindingRequest
    contract: BudgetContract
    envelope: BudgetApprovalEnvelope
    trusted_authorities: Mapping[str, TrustedAuthority]
    expected_scope: str
    authorized_roles: frozenset[str]
    now: datetime


class OperationalRunCoordinator:
    """Project the next O8 transition without performing external mutations."""

    def __init__(self) -> None:
        self._evaluator: AdmissionEvaluator | None = None
        self._clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    @classmethod
    def _for_testing(
        cls,
        *,
        evaluator: AdmissionEvaluator,
        clock: Callable[[], datetime],
    ) -> OperationalRunCoordinator:
        instance = cls()
        instance._evaluator = evaluator
        instance._clock = clock
        return instance

    def advance(self, request: ExistingOperationalRunRequest) -> OperationalRunResult:
        """Return the next permitted transition; never write or call a provider."""

        candidates = (
            request.strong_candidate_deployed_model,
            request.weak_candidate_deployed_model,
        )
        if not request.receipts_verified:
            return self._blocked(
                phase="receipt",
                code="verified_receipt_missing",
                candidates=candidates,
                cap_verified=request.signed_provider_cap_present,
            )
        if not (
            request.strong_adoption_authorization_present
            and request.weak_adoption_authorization_present
        ):
            return self._blocked(
                phase="adoption_approval",
                code="adoption_authorization_missing",
                candidates=candidates,
                cap_verified=False,
            )
        if not request.signed_pricing_present:
            return self._blocked(
                phase="adoption_approval",
                code="signed_pricing_missing",
                candidates=candidates,
                cap_verified=False,
            )
        if not request.signed_provider_cap_present:
            return self._blocked(
                phase="adoption_approval",
                code="provider_cap_missing",
                candidates=candidates,
                cap_verified=False,
            )
        if not request.reserves_verified:
            return self._blocked(
                phase="reserve",
                code="infrastructure_reserve_missing",
                candidates=candidates,
                cap_verified=True,
            )
        if request.final_document is None:
            return self._blocked(
                phase="final_plan",
                code="final_plan_missing",
                candidates=candidates,
                cap_verified=True,
            )
        return self._blocked(
            phase="admit",
            code="admission_not_evaluated",
            candidates=candidates,
            cap_verified=True,
        )

    def project(
        self, snapshot: NewOperationalRunSnapshot | ExistingOperationalRunSnapshot
    ) -> OperationalRunResult:
        """Purely project the next transition from immutable evidence statuses."""

        if isinstance(snapshot, NewOperationalRunSnapshot):
            candidates: tuple[str, ...] = ()
            phases: tuple[
                tuple[OperationalPhase, tuple[tuple[str, EvidenceStatus], ...]], ...
            ] = (
                (
                    "preauthorization",
                    (
                        ("provisioning_authorization", snapshot.provisioning_authorization),
                        ("signed_pricing", snapshot.signed_pricing),
                        ("provider_cap", snapshot.signed_provider_cap),
                    ),
                ),
                ("reserve", (("infrastructure_reserve", snapshot.reserve),)),
                (
                    "create_or_reconcile",
                    (("deployment_receipt", snapshot.receipt),),
                ),
                ("final_plan", (("final_plan", snapshot.final_plan),)),
                ("sign", (("final_signatures", snapshot.signatures),)),
            )
        else:
            candidates = snapshot.candidate_deployed_models
            phases = (
                ("receipt", (("verified_receipt", snapshot.receipt),)),
                (
                    "adoption_approval",
                    (
                        ("adoption_authorization", snapshot.adoption_authorization),
                        ("signed_pricing", snapshot.signed_pricing),
                        ("provider_cap", snapshot.signed_provider_cap),
                    ),
                ),
                ("reserve", (("infrastructure_reserve", snapshot.reserve),)),
                ("final_plan", (("final_plan", snapshot.final_plan),)),
                ("sign", (("final_signatures", snapshot.signatures),)),
            )
        flattened = tuple(item for _, items in phases for item in items)
        for phase, items in phases:
            for name, status in items:
                if status == "verified":
                    continue
                index = flattened.index((name, status))
                later_present = any(
                    later_status != "missing"
                    for _, later_status in flattened[index + 1 :]
                )
                code = (
                    "transition_out_of_order"
                    if later_present
                    else self._status_blocker(name, status)
                )
                return self._blocked_many(
                    phase=phase,
                    code=code,
                    candidates=candidates,
                    cap_verified=snapshot.signed_provider_cap == "verified",
                )
        # Caller-supplied admission artifacts are untrusted on this pure path.
        # READY is derived only after the finalizer performs a fresh evaluation.
        return self._blocked_many(
            phase="admit",
            code="admission_not_evaluated",
            candidates=candidates,
            cap_verified=True,
        )

    @staticmethod
    def _status_blocker(name: str, status: EvidenceStatus) -> str:
        if status == "missing":
            return f"{name}_missing"
        return f"{name}_{status}"

    @staticmethod
    def _blocked_many(
        *,
        phase: OperationalPhase,
        code: str,
        candidates: tuple[str, ...],
        cap_verified: bool,
    ) -> OperationalRunResult:
        return OperationalRunResult(
            state="BLOCKED",
            phase=phase,
            blockers=(OperationalBlocker(phase=phase, code=code),),
            probes=0,
            verified_probes=0,
            candidate_deployed_models=candidates,
            cost_exposure=(
                "bounded_by_verified_provider_cap"
                if cap_verified
                else "continuing_unbounded_until_signed_cap"
            ),
        )

    @staticmethod
    def _blocked(
        *,
        phase: OperationalPhase,
        code: str,
        candidates: tuple[str, ...],
        cap_verified: bool,
    ) -> OperationalRunResult:
        return OperationalRunResult(
            state="BLOCKED",
            phase=phase,
            blockers=(OperationalBlocker(phase=phase, code=code),),
            probes=0,
            verified_probes=0,
            candidate_deployed_models=candidates,
            cost_exposure=(
                "bounded_by_verified_provider_cap"
                if cap_verified
                else "continuing_unbounded_until_signed_cap"
            ),
        )

    @staticmethod
    def _from_admission(
        result: AdmissionResult,
        *,
        candidates: tuple[str, ...],
        now: datetime,
        expected_roles: Mapping[str, ModelRolePlan] | None = None,
    ) -> OperationalRunResult:
        evidence = result.evidence
        probes = () if evidence is None else evidence.probes
        verified = sum(probe.verified for probe in probes)
        if result.state != "READY":
            return OperationalRunResult(
                state="BLOCKED",
                phase="admit",
                blockers=(
                    OperationalBlocker(phase="admit", code="admission_blocked"),
                ),
                probes=len(probes),
                verified_probes=verified,
                candidate_deployed_models=candidates,
                cost_exposure="bounded_by_verified_provider_cap",
            )
        probe_roles = tuple(probe.role for probe in probes)
        expected_role_names = ("annotator", "weak_extractor", "judge")
        exact_probes = probe_roles == expected_role_names
        if expected_roles is not None and exact_probes:
            exact_probes = all(
                probe.provider == expected_roles[probe.role].provider
                and probe.model_id == expected_roles[probe.role].model_id
                and probe.observed_deployment_id
                == expected_roles[probe.role].immutable_deployment_id
                for probe in probes
            )
        provider_checks = {
            check.name: check
            for check in result.checks
            if check.name.startswith("provider_probe:")
        }
        expected_check_names = {
            f"provider_probe:{role}" for role in expected_role_names
        }
        expired = any(now >= check.expires_at for check in result.checks)
        observations_current = (
            bool(result.checks)
            and result.evaluated_at <= now
            and all(check.observed_at <= now < check.expires_at for check in result.checks)
            and all(check.passed for check in result.checks)
            and set(provider_checks) == expected_check_names
            and all(provider_checks[name].passed for name in expected_check_names)
            and all(
                probe.observed_at is not None
                and provider_checks[f"provider_probe:{probe.role}"].observed_at
                <= probe.observed_at
                <= result.evaluated_at
                for probe in probes
            )
        )
        if not observations_current:
            return OperationalRunResult(
                state="BLOCKED",
                phase="probe",
                blockers=(
                    OperationalBlocker(
                        phase="probe",
                        code=(
                            "probe_observation_expired"
                            if expired
                            else "probe_evidence_invalid"
                        ),
                    ),
                ),
                probes=len(probes),
                verified_probes=verified,
                candidate_deployed_models=candidates,
                cost_exposure="bounded_by_verified_provider_cap",
            )
        if len(probes) != 3 or verified != 3 or not exact_probes:
            return OperationalRunResult(
                state="BLOCKED",
                phase="probe",
                blockers=(
                    OperationalBlocker(
                        phase="probe", code="probe_verification_incomplete"
                    ),
                ),
                probes=len(probes),
                verified_probes=verified,
                candidate_deployed_models=candidates,
                cost_exposure="bounded_by_verified_provider_cap",
            )
        return OperationalRunResult(
            state="READY",
            phase="ready",
            blockers=(),
            probes=3,
            verified_probes=3,
            candidate_deployed_models=candidates,
            cost_exposure="bounded_by_verified_provider_cap",
        )


class OperationalAdmissionFinalizer:
    """Explicit ledger/admission command handler; the coordinator stays pure."""

    def __init__(self, *, ledger: BudgetLedger, evaluator: FinalAdmissionEvaluator) -> None:
        self._ledger = ledger
        self._evaluator = evaluator
        self._clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    @classmethod
    def _for_testing(
        cls,
        *,
        ledger: object,
        evaluator: object,
        clock: Callable[[], datetime],
    ) -> OperationalAdmissionFinalizer:
        instance = cls(
            ledger=cast(BudgetLedger, ledger),
            evaluator=cast(FinalAdmissionEvaluator, evaluator),
        )
        instance._clock = clock
        return instance

    def finalize(self, request: OperationalFinalizationRequest) -> OperationalRunResult:
        candidates: tuple[str, ...] = ()
        try:
            start_now = self._read_clock()
            payload_hash = plan_payload_hash(request.document.plan)
            role_plans = request.document.plan.payload.model_roles
            if frozenset(role_plans) != {
                "annotator",
                "weak_extractor",
                "judge",
            }:
                raise ValueError("final plan must contain exactly three role keys")
            candidates = tuple(
                model_id
                for role in ("annotator", "weak_extractor")
                if isinstance((model_id := role_plans[role].model_id), str)
                and model_id.strip()
            )
            self._require_topology(request)
        except (AuthorizationVerificationError, KeyError, ValueError):
            return OperationalRunCoordinator._blocked_many(
                phase="final_plan",
                code="final_topology_invalid",
                candidates=candidates,
                cap_verified=True,
            )
        try:
            bound = self._ledger.bind_final_infrastructure_topology(
                strong=request.strong,
                weak=request.weak,
                plan=request.document.plan.payload,
                contract=request.contract,
                envelope=request.envelope,
                trusted_authorities=request.trusted_authorities,
                expected_scope=request.expected_scope,
                authorized_roles=request.authorized_roles,
                now=start_now,
            )
            self._require_bound_topology(request, bound)
        except (BudgetLedgerError, KeyError, ValueError):
            return OperationalRunCoordinator._blocked_many(
                phase="final_plan",
                code="final_bind_blocked",
                candidates=candidates,
                cap_verified=True,
            )
        try:
            admission, account = self._evaluator.admit_budget_account(
                request.document, self._ledger
            )
            verification_now = self._read_clock()
        except Exception:
            return OperationalRunCoordinator._blocked_many(
                phase="admit",
                code="admission_evaluation_failed",
                candidates=candidates,
                cap_verified=True,
            )
        if account is None and admission.state == "READY":
            result = OperationalRunCoordinator._blocked_many(
                phase="admit",
                code="budget_account_missing",
                candidates=candidates,
                cap_verified=True,
            )
        elif admission.plan_payload_hash != payload_hash:
            result = OperationalRunCoordinator._blocked_many(
                phase="admit",
                code="admission_plan_mismatch",
                candidates=candidates,
                cap_verified=True,
            )
        else:
            exact_role_plans = {
                role: cast(ModelRolePlan, plan)
                for role, plan in request.document.plan.payload.model_roles.items()
            }
            result = OperationalRunCoordinator._from_admission(
                admission,
                candidates=candidates,
                now=verification_now,
                expected_roles=exact_role_plans,
            )
        return result

    def _read_clock(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("finalizer clock must include a timezone")
        return now

    @staticmethod
    def _require_topology(request: OperationalFinalizationRequest) -> None:
        try:
            strong_receipt = require_verified_reconciled_receipt(
                request.strong.receipt_capability
            ).receipt
            weak_receipt = require_verified_reconciled_receipt(
                request.weak.receipt_capability
            ).receipt
        except AuthorizationVerificationError as exc:
            raise ValueError("verified final topology receipts are required") from exc
        roles = request.document.plan.payload.model_roles
        if (
            frozenset(roles) != {"annotator", "weak_extractor", "judge"}
            or request.strong.roles != ("annotator", "judge")
            or request.weak.roles != ("weak_extractor",)
            or request.strong.reserve_id == request.weak.reserve_id
            or strong_receipt.content.deployed_model
            == weak_receipt.content.deployed_model
            or not isinstance(roles["annotator"], ModelRolePlan)
            or not isinstance(roles["judge"], ModelRolePlan)
            or not isinstance(roles["weak_extractor"], ModelRolePlan)
            or roles["annotator"].model_id != strong_receipt.content.deployed_model
            or roles["judge"].model_id != strong_receipt.content.deployed_model
            or roles["weak_extractor"].model_id
            != weak_receipt.content.deployed_model
        ):
            raise ValueError("final infrastructure topology is invalid")

    @staticmethod
    def _require_bound_topology(
        request: OperationalFinalizationRequest,
        bound: tuple[InfrastructureReserveSnapshot, InfrastructureReserveSnapshot],
    ) -> None:
        expected = (
            (
                request.strong.reserve_id,
                request.strong.roles,
                request.strong.receipt_capability.receipt.content.deployed_model,
            ),
            (
                request.weak.reserve_id,
                request.weak.roles,
                request.weak.receipt_capability.receipt.content.deployed_model,
            ),
        )
        observed = tuple(
            (item.reserve_id, item.roles, item.deployed_model) for item in bound
        )
        if observed != expected or any(item.state != "bound" for item in bound):
            raise ValueError("bound infrastructure topology is invalid")
