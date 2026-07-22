"""Pure O8 operational-admission state projection.

Provider mutations, signatures, and durable budget writes deliberately remain in
their owning modules.  This module only decides which transition is permitted and
summarises the already-verified 020 admission result.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    StringConstraints,
    model_validator,
)

from insurance_harness.goldenset.admission import AdmissionResult, RunAdmissionDocument
from insurance_harness.goldenset.admission_budget import (
    AccountSnapshot,
    BudgetContract,
    BudgetLedger,
    BudgetLedgerError,
    FinalInfrastructureBindingRequest,
    VerifiedFinalTopology,
    require_verified_final_topology,
)
from insurance_harness.goldenset.admission_deployment import (
    DeploymentControlBlocked,
    DeploymentController,
    ProviderDeploymentManifest,
    TopologyReconciliationObservationBatchArtifact,
    TopologyReconciliationObservationBatchV1,
    TopologyReconciliationTargetV1,
)
from insurance_harness.goldenset.admission_infrastructure import (
    AuthorizationVerificationError,
    _require_verified_reconciled_receipt_for_testing,
    require_verified_reconciled_receipt,
)
from insurance_harness.goldenset.admission_models import (
    BudgetApprovalEnvelope,
    ModelRolePlan,
    canonical_json_bytes,
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


class _TopologyObservationRefresher(Protocol):
    def __call__(
        self,
        *,
        topology: object,
        strong: TopologyReconciliationTargetV1,
        weak: TopologyReconciliationTargetV1,
        now: datetime,
    ) -> TopologyReconciliationObservationBatchArtifact: ...


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
    evaluated_at: datetime | None = None
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def require_ready_authority_window(self) -> OperationalRunResult:
        if self.state == "READY":
            if (
                self.phase != "ready"
                or self.blockers
                or self.cost_exposure != "bounded_by_verified_provider_cap"
                or self.evaluated_at is None
                or self.valid_until is None
                or self.evaluated_at >= self.valid_until
            ):
                raise ValueError(
                    "READY requires a current bounded provider-cap authority window"
                )
        return self


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
    expected_scope: str


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
                cap_verified=False,
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
                cap_verified=False,
            )
        if request.final_document is None:
            return self._blocked(
                phase="final_plan",
                code="final_plan_missing",
                candidates=candidates,
                cap_verified=False,
            )
        return self._blocked(
            phase="admit",
            code="admission_not_evaluated",
            candidates=candidates,
            cap_verified=False,
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
                    cap_verified=False,
                )
        # Caller-supplied admission artifacts are untrusted on this pure path.
        # READY is derived only after the finalizer performs a fresh evaluation.
        return self._blocked_many(
            phase="admit",
            code="admission_not_evaluated",
            candidates=candidates,
            cap_verified=False,
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
        topology_valid_until: datetime,
        observation_valid_until: datetime,
        expected_roles: Mapping[str, ModelRolePlan] | None = None,
    ) -> OperationalRunResult:
        evidence = result.evidence
        probes = () if evidence is None else evidence.probes
        verified = sum(probe.verified for probe in probes)
        cap_verified = now < topology_valid_until
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
                cost_exposure=(
                    "bounded_by_verified_provider_cap"
                    if cap_verified
                    else "continuing_unbounded_until_signed_cap"
                ),
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
        valid_until = min(
            OperationalRunCoordinator._ready_valid_until(result),
            topology_valid_until,
            observation_valid_until,
        )
        expired = now >= valid_until
        observations_current = (
            bool(result.checks)
            and result.evaluated_at <= now
            and now < valid_until
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
                cost_exposure=(
                    "bounded_by_verified_provider_cap"
                    if cap_verified
                    else "continuing_unbounded_until_signed_cap"
                ),
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
                cost_exposure=(
                    "bounded_by_verified_provider_cap"
                    if cap_verified
                    else "continuing_unbounded_until_signed_cap"
                ),
            )
        if not cap_verified:
            return OperationalRunResult(
                state="BLOCKED",
                phase="admit",
                blockers=(
                    OperationalBlocker(
                        phase="admit", code="provider_cap_unverified"
                    ),
                ),
                probes=len(probes),
                verified_probes=verified,
                candidate_deployed_models=candidates,
                cost_exposure="continuing_unbounded_until_signed_cap",
            )
        return OperationalRunResult(
            state="READY",
            phase="ready",
            blockers=(),
            probes=3,
            verified_probes=3,
            candidate_deployed_models=candidates,
            cost_exposure="bounded_by_verified_provider_cap",
            evaluated_at=result.evaluated_at,
            valid_until=valid_until,
        )

    @staticmethod
    def _ready_valid_until(result: AdmissionResult) -> datetime:
        expiries = [check.expires_at for check in result.checks]
        evidence = result.evidence
        if evidence is not None:
            expiries.extend(
                approval.expires_at
                for approval in evidence.approvals
                if approval.verified and approval.expires_at is not None
            )
            if evidence.budget is not None:
                expiries.extend(
                    (
                        evidence.budget.price_expires_at,
                        evidence.budget.provider_attestation_expires_at,
                    )
                )
        if not expiries:
            raise ValueError("READY admission requires expiring evidence")
        return min(expiries)

class OperationalAdmissionFinalizer:
    """Issue only reports derived from a fresh sealed durable final topology."""

    def __init__(self, *, ledger: BudgetLedger, evaluator: FinalAdmissionEvaluator) -> None:
        self._ledger = ledger
        self._evaluator = evaluator
        self._clock: Callable[[], datetime] = lambda: datetime.now(UTC)
        self._testing = False
        self._testing_observation_refresher: _TopologyObservationRefresher | None = None

    @classmethod
    def _for_testing(
        cls,
        *,
        ledger: object,
        evaluator: object,
        clock: Callable[[], datetime],
        observation_refresher: _TopologyObservationRefresher,
    ) -> OperationalAdmissionFinalizer:
        instance = cls(
            ledger=cast(BudgetLedger, ledger),
            evaluator=cast(FinalAdmissionEvaluator, evaluator),
        )
        instance._clock = clock
        instance._testing = True
        instance._testing_observation_refresher = observation_refresher
        return instance

    def finalize(self, request: OperationalFinalizationRequest) -> OperationalRunResult:
        candidates: tuple[str, ...] = ()
        try:
            start_now = self._read_clock()
            payload_hash = plan_payload_hash(request.document.plan)
            candidates = self._candidate_models(request.document)
            self._require_topology(request, now=start_now)
        except (AuthorizationVerificationError, KeyError, ValueError):
            return OperationalRunCoordinator._blocked_many(
                phase="final_plan",
                code="final_topology_invalid",
                candidates=candidates,
                cap_verified=False,
            )
        try:
            if self._testing:
                capability = self._ledger.bind_final_infrastructure_topology(
                    strong=request.strong,
                    weak=request.weak,
                    plan=request.document.plan.payload,
                    contract=request.contract,
                    envelope=request.envelope,
                    expected_scope=request.expected_scope,
                    now=start_now,
                )
            else:
                capability = self._ledger.bind_final_infrastructure_topology(
                    strong=request.strong,
                    weak=request.weak,
                    plan=request.document.plan.payload,
                    contract=request.contract,
                    envelope=request.envelope,
                    expected_scope=request.expected_scope,
                )
            topology = self._verify_topology_capability(
                capability,
                now=start_now,
                expected_plan_payload_hash=payload_hash,
                expected_scope=request.expected_scope,
            )
            self._require_bound_topology(request, topology)
        except (
            sqlite3.Error,
            BudgetLedgerError,
            KeyError,
            OSError,
            TypeError,
            ValueError,
        ):
            return OperationalRunCoordinator._blocked_many(
                phase="final_plan",
                code="final_bind_blocked",
                candidates=candidates,
                cap_verified=False,
            )
        observation = self._refresh_topology_observation(
            document=request.document,
            expected_scope=request.expected_scope,
            topology=topology,
            now=start_now,
        )
        if observation is None:
            return OperationalRunCoordinator._blocked_many(
                phase="final_plan",
                code="topology_observation_blocked",
                candidates=candidates,
                cap_verified=False,
            )
        return self._evaluate_fresh_admission(
            document=request.document,
            expected_scope=request.expected_scope,
            topology=topology,
            observation=observation,
            candidates=candidates,
        )

    def finalize_durable(
        self,
        document: RunAdmissionDocument,
        *,
        expected_scope: str,
    ) -> OperationalRunResult:
        """Re-read durable topology before one production execution boundary."""

        candidates: tuple[str, ...] = ()
        try:
            now = self._read_clock()
            candidates = self._candidate_models(document)
            topology = self._fresh_topology(
                document=document,
                expected_scope=expected_scope,
                now=now,
            )
        except (
            sqlite3.Error,
            BudgetLedgerError,
            KeyError,
            OSError,
            TypeError,
            ValueError,
        ):
            return OperationalRunCoordinator._blocked_many(
                phase="final_plan",
                code="final_topology_unavailable",
                candidates=candidates,
                cap_verified=False,
            )
        observation = self._refresh_topology_observation(
            document=document,
            expected_scope=expected_scope,
            topology=topology,
            now=now,
        )
        if observation is None:
            return OperationalRunCoordinator._blocked_many(
                phase="final_plan",
                code="topology_observation_blocked",
                candidates=candidates,
                cap_verified=False,
            )
        return self._evaluate_fresh_admission(
            document=document,
            expected_scope=expected_scope,
            topology=topology,
            observation=observation,
            candidates=candidates,
        )

    def evaluate_with_fresh_topology_postcheck[EvaluationResultT](
        self,
        document: RunAdmissionDocument,
        *,
        expected_scope: str,
        evaluation: Callable[[], EvaluationResultT],
    ) -> EvaluationResultT:
        """Run one evaluator between two independent durable topology reloads."""

        try:
            before = self._fresh_topology(
                document=document,
                expected_scope=expected_scope,
                now=self._read_clock(),
            )
            expected_identity = self._postcheck_identity(before)
        except (
            sqlite3.Error,
            AttributeError,
            AuthorizationVerificationError,
            BudgetLedgerError,
            KeyError,
            OSError,
            TypeError,
            ValueError,
        ):
            raise BudgetLedgerError(
                "candidate pre-evaluator durable topology is unavailable"
            ) from None

        result = evaluation()

        try:
            after = self._fresh_topology(
                document=document,
                expected_scope=expected_scope,
                now=self._read_clock(),
            )
            if self._postcheck_identity(after) != expected_identity:
                raise BudgetLedgerError(
                    "candidate post-evaluator durable topology has drifted"
                )
        except (
            sqlite3.Error,
            AttributeError,
            AuthorizationVerificationError,
            BudgetLedgerError,
            KeyError,
            OSError,
            TypeError,
            ValueError,
        ):
            raise BudgetLedgerError(
                "candidate post-evaluator durable topology is unavailable or drifted"
            ) from None
        return result

    @staticmethod
    def _postcheck_identity(topology: VerifiedFinalTopology) -> tuple[object, ...]:
        """Freeze stable authority facts before the evaluator can mutate shared state."""

        return (
            topology.topology_digest,
            topology.run_identity,
            topology.purpose,
            topology.scope,
            topology.plan_payload_hash,
            topology.provider_cap_evidence_digest,
            topology.provider_cap_approval_digest,
            topology.valid_until,
        )

    def _evaluate_fresh_admission(
        self,
        *,
        document: RunAdmissionDocument,
        expected_scope: str,
        topology: VerifiedFinalTopology,
        observation: TopologyReconciliationObservationBatchV1,
        candidates: tuple[str, ...],
    ) -> OperationalRunResult:
        payload_hash = plan_payload_hash(document.plan)
        try:
            pre_evaluation_now = self._read_clock()
            refreshed = self._fresh_topology(
                document=document,
                expected_scope=expected_scope,
                now=pre_evaluation_now,
            )
            if refreshed.topology_digest != topology.topology_digest:
                raise BudgetLedgerError("final topology changed before admission")
            self._require_observation_binding(
                observation,
                topology=refreshed,
                now=pre_evaluation_now,
            )
        except (
            sqlite3.Error,
            BudgetLedgerError,
            KeyError,
            OSError,
            TypeError,
            ValueError,
        ):
            return OperationalRunCoordinator._blocked_many(
                phase="final_plan",
                code="final_topology_stale",
                candidates=candidates,
                cap_verified=False,
            )
        try:
            admission, account = self._evaluator.admit_budget_account(
                document, self._ledger
            )
            verification_now = self._read_clock()
        except Exception:
            return OperationalRunCoordinator._blocked_many(
                phase="admit",
                code="admission_evaluation_failed",
                candidates=candidates,
                cap_verified=False,
            )
        try:
            refreshed = self._fresh_topology(
                document=document,
                expected_scope=expected_scope,
                now=verification_now,
            )
            if refreshed.topology_digest != topology.topology_digest:
                raise BudgetLedgerError("final topology changed during admission")
            self._require_observation_binding(
                observation,
                topology=refreshed,
                now=verification_now,
            )
        except (
            sqlite3.Error,
            BudgetLedgerError,
            KeyError,
            OSError,
            TypeError,
            ValueError,
        ):
            return OperationalRunCoordinator._blocked_many(
                phase="final_plan",
                code="final_topology_stale",
                candidates=candidates,
                cap_verified=False,
            )
        if account is None and admission.state == "READY":
            return OperationalRunCoordinator._blocked_many(
                phase="admit",
                code="budget_account_missing",
                candidates=candidates,
                cap_verified=True,
            )
        if admission.plan_payload_hash != payload_hash:
            return OperationalRunCoordinator._blocked_many(
                phase="admit",
                code="admission_plan_mismatch",
                candidates=candidates,
                cap_verified=True,
            )
        exact_role_plans = {
            role: cast(ModelRolePlan, plan)
            for role, plan in document.plan.payload.model_roles.items()
        }
        return OperationalRunCoordinator._from_admission(
            admission,
            candidates=candidates,
            now=verification_now,
            topology_valid_until=refreshed.valid_until,
            observation_valid_until=observation.expires_at,
            expected_roles=exact_role_plans,
        )

    def _refresh_topology_observation(
        self,
        *,
        document: RunAdmissionDocument,
        expected_scope: str,
        topology: VerifiedFinalTopology,
        now: datetime,
    ) -> TopologyReconciliationObservationBatchV1 | None:
        try:
            if self._testing:
                strong = self._observation_target(topology.strong, boundary="strong")
                weak = self._observation_target(topology.weak, boundary="weak")
                refresher = self._testing_observation_refresher
                if refresher is None:
                    raise ValueError("test topology observation refresher is unavailable")
                artifact = refresher(
                    topology=topology,
                    strong=strong,
                    weak=weak,
                    now=now,
                )
            else:
                controller = DeploymentController.for_production(
                    plan=document.plan.payload,
                    expected_scope=expected_scope,
                )
                try:
                    artifact = controller.refresh_topology_reconciliation_batch()
                finally:
                    controller.close()
            exact_artifact = TopologyReconciliationObservationBatchArtifact.model_validate(
                artifact.model_dump(mode="python", round_trip=True)
            )
            self._require_observation_binding(
                exact_artifact.batch,
                topology=topology,
                now=now,
                expected_strong=(strong if self._testing else None),
                expected_weak=(weak if self._testing else None),
                allow_observed_after_now=True,
            )
            return exact_artifact.batch
        except (
            sqlite3.Error,
            AttributeError,
            AuthorizationVerificationError,
            BudgetLedgerError,
            DeploymentControlBlocked,
            KeyError,
            OSError,
            TypeError,
            ValueError,
        ):
            return None

    @staticmethod
    def _observation_target(
        deployment: object,
        *,
        boundary: Literal["strong", "weak"],
    ) -> TopologyReconciliationTargetV1:
        exact = cast(Any, deployment)
        receipt = exact.receipt
        manifest = ProviderDeploymentManifest.model_validate(
            exact.expected_remote_manifest
        )
        return TopologyReconciliationTargetV1(
            boundary=boundary,
            receipt=receipt,
            expected_remote_manifest=manifest,
            roles=("annotator", "judge") if boundary == "strong" else ("extractor",),
        )

    @staticmethod
    def _require_observation_binding(
        batch: TopologyReconciliationObservationBatchV1,
        *,
        topology: VerifiedFinalTopology,
        now: datetime,
        expected_strong: TopologyReconciliationTargetV1 | None = None,
        expected_weak: TopologyReconciliationTargetV1 | None = None,
        allow_observed_after_now: bool = False,
    ) -> None:
        if (
            batch.issuer != "bailian-deployment-controller-v1"
            or batch.run_identity != topology.run_identity
            or batch.purpose != topology.purpose
            or batch.scope != topology.scope
            or batch.topology_digest != topology.topology_digest
            or batch.plan_payload_hash != topology.plan_payload_hash
            or batch.provider_cap_evidence_digest
            != topology.provider_cap_evidence_digest
            or batch.provider_cap_approval_digest
            != topology.provider_cap_approval_digest
            or now >= batch.expires_at
            or (not allow_observed_after_now and batch.observed_at > now)
            or (
                expected_strong is not None
                and canonical_json_bytes(batch.strong)
                != canonical_json_bytes(expected_strong)
            )
            or (
                expected_weak is not None
                and canonical_json_bytes(batch.weak)
                != canonical_json_bytes(expected_weak)
            )
        ):
            raise BudgetLedgerError("topology observation batch is stale or drifted")

    def _fresh_topology(
        self,
        *,
        document: RunAdmissionDocument,
        expected_scope: str,
        now: datetime,
    ) -> VerifiedFinalTopology:
        if self._testing:
            reader = getattr(
                self._ledger,
                "_require_fresh_final_topology_for_testing",
                None,
            )
        else:
            reader = self._ledger.require_fresh_final_topology
        if not callable(reader):
            raise BudgetLedgerError("fresh final topology reader is unavailable")
        if self._testing:
            capability = reader(
                plan=document.plan.payload,
                expected_scope=expected_scope,
                now=now,
            )
        else:
            capability = reader(
                plan=document.plan.payload,
                expected_scope=expected_scope,
            )
        return self._verify_topology_capability(
            capability,
            now=now,
            expected_plan_payload_hash=plan_payload_hash(document.plan),
            expected_scope=expected_scope,
        )

    def _verify_topology_capability(
        self,
        capability: object,
        *,
        now: datetime,
        expected_plan_payload_hash: str,
        expected_scope: str,
    ) -> VerifiedFinalTopology:
        if not self._testing:
            return require_verified_final_topology(
                capability,
                now=now,
                expected_plan_payload_hash=expected_plan_payload_hash,
                expected_scope=expected_scope,
            )
        verifier = getattr(
            self._ledger,
            "_require_verified_final_topology_for_testing",
            None,
        )
        if not callable(verifier):
            raise BudgetLedgerError("verified test final topology is unavailable")
        return cast(
            VerifiedFinalTopology,
            verifier(
                capability,
                now=now,
                expected_plan_payload_hash=expected_plan_payload_hash,
                expected_scope=expected_scope,
            ),
        )

    def _read_clock(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("finalizer clock must include a timezone")
        return now

    @staticmethod
    def _candidate_models(document: RunAdmissionDocument) -> tuple[str, ...]:
        role_plans = document.plan.payload.model_roles
        if frozenset(role_plans) != {"annotator", "weak_extractor", "judge"}:
            raise ValueError("final plan must contain exactly three role keys")
        return tuple(
            model_id
            for role in ("annotator", "weak_extractor")
            if isinstance((model_id := role_plans[role].model_id), str)
            and model_id.strip()
        )

    def _require_topology(
        self,
        request: OperationalFinalizationRequest,
        *,
        now: datetime,
    ) -> None:
        try:
            receipt_verifier = (
                _require_verified_reconciled_receipt_for_testing
                if self._testing
                else require_verified_reconciled_receipt
            )
            strong_receipt = receipt_verifier(
                request.strong.receipt_capability,
                now=now,
            ).receipt
            weak_receipt = receipt_verifier(
                request.weak.receipt_capability,
                now=now,
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
        topology: VerifiedFinalTopology,
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
        observed = (
            (
                topology.strong.reserve_id,
                topology.strong.roles,
                topology.strong.deployed_model,
            ),
            (
                topology.weak.reserve_id,
                topology.weak.roles,
                topology.weak.deployed_model,
            ),
        )
        if (
            observed != expected
            or topology.run_identity != request.document.plan.payload.run_identity
            or topology.purpose != request.document.plan.payload.purpose
            or topology.scope != request.expected_scope
        ):
            raise ValueError("bound infrastructure topology is invalid")
