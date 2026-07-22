"""OpenSpec 031 O8: the operational admission coordinator fails closed."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from insurance_harness.goldenset.admission import (
    AdmissionBlocker,
    AdmissionCheck,
    AdmissionEvidence,
    AdmissionResult,
    ApprovalAuditEvidence,
    RunAdmissionDocument,
)
from insurance_harness.goldenset.admission_budget import (
    AccountSnapshot,
    BudgetAdmissionProof,
    BudgetAmounts,
    BudgetContract,
    BudgetLedger,
    BudgetLedgerError,
    FinalInfrastructureBindingRequest,
    InfrastructureReserveSnapshot,
)
from insurance_harness.goldenset.admission_coordinator import (
    ExistingOperationalRunRequest,
    ExistingOperationalRunSnapshot,
    NewOperationalRunSnapshot,
    OperationalAdmissionFinalizer,
    OperationalFinalizationRequest,
    OperationalRunCoordinator,
)
from insurance_harness.goldenset.admission_deployment import (
    DeploymentController,
    ProviderDeploymentManifest,
    TopologyReconciliationObservationBatchArtifact,
    TopologyReconciliationObservationBatchV1,
    TopologyReconciliationTargetV1,
    _remote_manifest_digest,
)
from insurance_harness.goldenset.admission_infrastructure import (
    DeploymentReceipt,
    DeploymentReceiptContent,
    _issue_verified_deployment_transport_identity_for_testing,
    _issue_verified_reconciled_receipt_for_testing,
    deployment_receipt_content_digest,
)
from insurance_harness.goldenset.admission_models import (
    BudgetApprovalEnvelope,
    ModelRolePlan,
    RunAdmissionPlan,
    RunAdmissionPlanPayload,
    plan_payload_hash,
)
from insurance_harness.goldenset.admission_probe import ProbeResult

NOW = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)


class _ForbiddenLedger:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"O8 blocker performed a ledger side effect: {name}")


class _ForbiddenController:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"O8 blocker performed a provider side effect: {name}")


class _ForbiddenEvaluator:
    def __call__(self, document: RunAdmissionDocument) -> AdmissionResult:
        raise AssertionError("O8 blocker performed admission/probe evaluation")


@pytest.mark.parametrize(
    ("updates", "phase", "code"),
    [
        ({}, "preauthorization", "provisioning_authorization_missing"),
        (
            {"provisioning_authorization": "expired"},
            "preauthorization",
            "provisioning_authorization_expired",
        ),
        (
            {
                "provisioning_authorization": "verified",
                "signed_pricing": "verified",
            },
            "preauthorization",
            "provider_cap_missing",
        ),
        (
            {
                "provisioning_authorization": "verified",
                "signed_pricing": "verified",
                "signed_provider_cap": "verified",
            },
            "reserve",
            "infrastructure_reserve_missing",
        ),
    ],
)
def test_o8_new_flow_projects_stable_missing_or_expired_transition_blocker(
    updates: dict[str, object],
    phase: str,
    code: str,
) -> None:
    snapshot = NewOperationalRunSnapshot.model_validate(
        {
            "run_identity": "golden-v01-run-031",
            "purpose": "golden-v0.1 production run",
            "scope": "goldenset-production",
            **updates,
        }
    )

    result = OperationalRunCoordinator().project(snapshot)

    assert result.state == "BLOCKED"
    assert result.phase == phase
    assert tuple(item.code for item in result.blockers) == (code,)
    assert result.controller_inference_requests == 0


def test_o8_new_flow_rejects_out_of_order_receipt_without_any_side_effect() -> None:
    result = OperationalRunCoordinator().project(
        NewOperationalRunSnapshot(
            run_identity="golden-v01-run-031",
            purpose="golden-v0.1 production run",
            scope="goldenset-production",
            receipt="verified",
        )
    )

    assert result.phase == "preauthorization"
    assert tuple(item.code for item in result.blockers) == (
        "transition_out_of_order",
    )


def test_o8_existing_verified_prefix_stops_at_final_admission_without_mutation() -> None:
    result = OperationalRunCoordinator().project(
        ExistingOperationalRunSnapshot(
            run_identity="golden-v01-run-031",
            purpose="golden-v0.1 production run",
            scope="goldenset-production",
            candidate_deployed_models=(
                "qwen3.7-plus-2026-05-26-031strng",
                "deepseek-v4-flash-031weak1",
            ),
            receipt="verified",
            adoption_authorization="verified",
            signed_pricing="verified",
            signed_provider_cap="verified",
            reserve="verified",
            final_plan="verified",
            signatures="verified",
        )
    )

    assert result.state == "BLOCKED"
    assert result.phase == "admit"
    assert tuple(item.code for item in result.blockers) == (
        "admission_not_evaluated",
    )
    assert result.cost_exposure == "continuing_unbounded_until_signed_cap"


def test_o8_pure_projection_ignores_caller_supplied_ready_admission() -> None:
    document = _document()
    snapshot = NewOperationalRunSnapshot(
        run_identity="golden-v01-run-031",
        purpose="golden-v0.1 production run",
        scope="goldenset-production",
        provisioning_authorization="verified",
        signed_pricing="verified",
        signed_provider_cap="verified",
        reserve="verified",
        receipt="verified",
        final_plan="verified",
        signatures="verified",
        admission_result=_admission(document),
    )

    result = OperationalRunCoordinator().project(snapshot)

    assert result.state == "BLOCKED"
    assert result.phase == "admit"
    assert tuple(item.code for item in result.blockers) == (
        "admission_not_evaluated",
    )
    assert result.cost_exposure == "continuing_unbounded_until_signed_cap"


def test_o8_existing_missing_approval_blocks_before_all_later_side_effects(
    tmp_path: Path,
) -> None:
    coordinator = OperationalRunCoordinator._for_testing(
        evaluator=_ForbiddenEvaluator(),
        clock=lambda: NOW,
    )
    request = ExistingOperationalRunRequest(
        run_identity="golden-v01-run-031",
        purpose="golden-v0.1 production run",
        scope="goldenset-production",
        strong_candidate_deployed_model="qwen3.7-plus-2026-05-26-031strng",
        weak_candidate_deployed_model="deepseek-v4-flash-031weak1",
        report_root=tmp_path,
    )

    result = coordinator.advance(request)

    assert result.state == "BLOCKED"
    assert result.phase == "receipt"
    assert tuple(blocker.code for blocker in result.blockers) == (
        "verified_receipt_missing",
    )
    assert result.probes == 0
    assert result.verified_probes == 0
    assert result.controller_inference_requests == 0


def test_o8_current_external_ids_only_render_candidate_and_never_imply_adoption(
    tmp_path: Path,
) -> None:
    coordinator = OperationalRunCoordinator._for_testing(
        evaluator=_ForbiddenEvaluator(),
        clock=lambda: NOW,
    )

    result = coordinator.advance(
        ExistingOperationalRunRequest(
            run_identity="golden-v01-run-031",
            purpose="golden-v0.1 production run",
            scope="goldenset-production",
            strong_candidate_deployed_model="qwen3.7-plus-2026-05-26-031strng",
            weak_candidate_deployed_model="deepseek-v4-flash-031weak1",
            report_root=tmp_path,
        )
    )

    assert result.candidate_deployed_models == (
        "qwen3.7-plus-2026-05-26-031strng",
        "deepseek-v4-flash-031weak1",
    )
    assert result.cost_exposure == "continuing_unbounded_until_signed_cap"
    assert result.state == "BLOCKED"


def test_o8_existing_advance_requires_receipt_before_adoption_approval(
    tmp_path: Path,
) -> None:
    request = ExistingOperationalRunRequest(
        run_identity="golden-v01-run-031",
        purpose="golden-v0.1 production run",
        scope="goldenset-production",
        strong_candidate_deployed_model="qwen3.7-plus-2026-05-26-031strng",
        weak_candidate_deployed_model="deepseek-v4-flash-031weak1",
        report_root=tmp_path,
        receipts_verified=True,
    )

    result = OperationalRunCoordinator().advance(request)

    assert result.phase == "adoption_approval"
    assert tuple(item.code for item in result.blockers) == (
        "adoption_authorization_missing",
    )


def _role(model_id: str) -> ModelRolePlan:
    return ModelRolePlan(
        provider="bailian",
        model_id=model_id,
        immutable_deployment_id=model_id,
        protocol="https",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        provider_policy="bailian-deployment-detail-v1",
        credential_env_name="HARNESS_DASHSCOPE_API_KEY",
    )


def _document() -> RunAdmissionDocument:
    payload = RunAdmissionPlanPayload(
        run_identity="golden-v01-run-031",
        purpose="golden-v0.1 production run",
        model_roles={
            "annotator": _role("qwen3.7-plus-2026-05-26-031strng"),
            "judge": _role("qwen3.7-plus-2026-05-26-031strng"),
            "weak_extractor": _role("deepseek-v4-flash-031weak1"),
        },
        budget_contract_hash="a" * 64,
    )
    return cast(
        RunAdmissionDocument,
        SimpleNamespace(plan=RunAdmissionPlan(payload=payload)),
    )


def _receipt(
    *, operation: str, reserve: str, base: str, deployed: str, digit: str
) -> object:
    manifest = ProviderDeploymentManifest(
        deployed_model=deployed,
        base_model=cast(Any, base),
        plan="ptu",
        input_tpm=10_000,
        output_tpm=1_000,
        status="RUNNING",
        gmt_create=NOW,
        gmt_modified=NOW,
        workspace_ref="workspace-cn-beijing-031",
        ownership_nonce=digit * 32,
        operation_marker="ikb031-" + digit * 24,
        deployment_suffix="031-" + digit * 16,
    )
    content = DeploymentReceiptContent(
        operation_id=operation,
        infrastructure_reserve_id=reserve,
        workspace_ref="workspace-cn-beijing-031",
        project_ref="sha256:" + "a" * 64,
        credential_ref="sha256:" + "b" * 64,
        workspace_evidence_digest="c" * 64,
        region="cn-beijing",
        base_model=base,
        deployed_model=deployed,
        request_plan="ptu_v2",
        receipt_plan="ptu",
        input_tpm=10_000,
        output_tpm=1_000,
        gmt_create=NOW,
        gmt_modified=NOW,
        cleanup_state="required",
        operation_marker="ikb031-" + digit * 24,
        deployment_suffix="031-" + digit * 16,
        remote_manifest_digest=_remote_manifest_digest(manifest),
    )
    local = DeploymentReceipt(
        content=content, content_digest=deployment_receipt_content_digest(content)
    )
    identity = _issue_verified_deployment_transport_identity_for_testing(
        workspace_ref=content.workspace_ref,
        project_ref=content.project_ref,
        credential_ref=content.credential_ref,
        provider_cap_evidence_digest="e" * 64,
        expires_at=NOW + timedelta(hours=1),
    )
    return _issue_verified_reconciled_receipt_for_testing(
        receipt=local,
        transport_identity=identity,
        run_identity="golden-v01-run-031",
        purpose="golden-v0.1 production run",
        scope="goldenset-production",
        remote_manifest_digest=content.remote_manifest_digest,
        observed_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )


def _binding(
    *,
    strong: bool,
    digit: str | None = None,
    authorization: object | None = None,
) -> FinalInfrastructureBindingRequest:
    receipt_digit = digit or ("1" if strong else "2")
    return FinalInfrastructureBindingRequest(
        reserve_id="infra-strong-031" if strong else "infra-weak-031",
        authorization=cast(Any, authorization or object()),
        expected_authorization=cast(Any, object()),
        receipt_capability=cast(
            Any,
            _receipt(
                operation="op-strong-031" if strong else "op-weak-031",
                reserve="infra-strong-031" if strong else "infra-weak-031",
                base=(
                    "qwen3.7-plus-2026-05-26"
                    if strong
                    else "deepseek-v4-flash"
                ),
                deployed=(
                    "qwen3.7-plus-2026-05-26-031strng"
                    if strong
                    else "deepseek-v4-flash-031weak1"
                ),
                digit=receipt_digit,
            ),
        ),
        roles=("annotator", "judge") if strong else ("weak_extractor",),
        pricing_evidence_bytes=b"pricing",
        pricing_approval=cast(Any, object()),
        provider_cap_evidence_bytes=b"cap",
        provider_cap_approval=cast(Any, object()),
    )


def _bound(binding: FinalInfrastructureBindingRequest) -> InfrastructureReserveSnapshot:
    receipt = cast(Any, binding.receipt_capability).receipt
    return InfrastructureReserveSnapshot(
        reserve_id=binding.reserve_id,
        account_id="d" * 64,
        run_identity="golden-v01-run-031",
        purpose="golden-v0.1 production run",
        operation_id=receipt.content.operation_id,
        authorization_domain="insurancekb.run-admission.provisioning.v1",
        authorization_digest="e" * 64,
        maximum=BudgetAmounts(
            input_tokens=0, output_tokens=0, cost_minor_units=1
        ),
        state="bound",
        deployed_model=receipt.content.deployed_model,
        receipt_digest=receipt.content_digest,
        final_approval_digest="f" * 64,
        roles=binding.roles,
    )


class _BatchLedger:
    def __init__(self) -> None:
        self.bind_calls = 0
        self.bind_times: list[datetime] = []
        self.topology: SimpleNamespace | None = None

    def bind_final_infrastructure_topology(self, **kwargs: Any) -> object:
        self.bind_calls += 1
        self.bind_times.append(kwargs["now"])
        strong = _bound(kwargs["strong"])
        weak = _bound(kwargs["weak"])
        self.topology = SimpleNamespace(
            topology_digest="9" * 64,
            run_identity=kwargs["plan"].run_identity,
            purpose=kwargs["plan"].purpose,
            scope=kwargs["expected_scope"],
            plan_payload_hash=plan_payload_hash(kwargs["plan"]),
            strong=SimpleNamespace(
                reserve_id=strong.reserve_id,
                roles=strong.roles,
                deployed_model=strong.deployed_model,
                receipt=kwargs["strong"].receipt_capability.receipt,
                expected_remote_manifest=_manifest_from_receipt(
                    kwargs["strong"].receipt_capability.receipt
                ),
            ),
            weak=SimpleNamespace(
                reserve_id=weak.reserve_id,
                roles=weak.roles,
                deployed_model=weak.deployed_model,
                receipt=kwargs["weak"].receipt_capability.receipt,
                expected_remote_manifest=_manifest_from_receipt(
                    kwargs["weak"].receipt_capability.receipt
                ),
            ),
            provider_cap_evidence_digest="e" * 64,
            provider_cap_approval_digest="f" * 64,
            valid_until=NOW + timedelta(minutes=30),
        )
        return self.topology

    def _require_verified_final_topology_for_testing(
        self,
        capability: object,
        *,
        now: datetime,
        expected_plan_payload_hash: str,
        expected_scope: str,
    ) -> object:
        if (
            capability is not self.topology
            or self.topology is None
            or self.topology.plan_payload_hash != expected_plan_payload_hash
            or self.topology.scope != expected_scope
            or now >= self.topology.valid_until
        ):
            raise BudgetLedgerError("test final topology is stale or invalid")
        return capability

    def _require_fresh_final_topology_for_testing(
        self,
        *,
        plan: object,
        expected_scope: str,
        now: datetime,
    ) -> object:
        if (
            self.topology is None
            or self.topology.plan_payload_hash != plan_payload_hash(cast(Any, plan))
            or self.topology.scope != expected_scope
            or now >= self.topology.valid_until
        ):
            raise BudgetLedgerError("test final topology is stale or invalid")
        return self.topology


class _InfrastructureFailureLedger(_BatchLedger):
    def __init__(self, failure: BaseException) -> None:
        super().__init__()
        self.failure = failure
        self.fresh_reads = 0
        self.cap_reads = 0

    def _raise_fresh_failure(self) -> object:
        self.fresh_reads += 1
        raise self.failure

    def _require_fresh_final_topology_for_testing(
        self,
        *,
        plan: object,
        expected_scope: str,
        now: datetime,
    ) -> object:
        return self._raise_fresh_failure()

    def require_fresh_final_topology(
        self,
        *,
        plan: object,
        expected_scope: str,
    ) -> object:
        return self._raise_fresh_failure()

    def require_fresh_provider_capability(
        self,
        *,
        plan: object,
        expected_scope: str,
    ) -> object:
        self.cap_reads += 1
        raise self.failure


class _CapReaderInfrastructureFailureLedger(_BatchLedger):
    def __init__(self, failure: BaseException) -> None:
        super().__init__()
        self.failure = failure
        self.fresh_reads = 0
        self.cap_reads = 0

    def require_fresh_final_topology(
        self,
        *,
        plan: object,
        expected_scope: str,
    ) -> object:
        self.fresh_reads += 1
        assert self.topology is not None
        return self.topology

    def require_fresh_provider_capability(
        self,
        *,
        plan: object,
        expected_scope: str,
    ) -> object:
        self.cap_reads += 1
        raise self.failure


class _SnapshotOnlyLedger(_BatchLedger):
    def bind_final_infrastructure_topology(self, **kwargs: Any) -> object:
        self.bind_calls += 1
        self.bind_times.append(kwargs["now"])
        return (_bound(kwargs["strong"]), _bound(kwargs["weak"]))

    _require_verified_final_topology_for_testing = None  # type: ignore[assignment]
    _require_fresh_final_topology_for_testing = None  # type: ignore[assignment]


class _DriftedTopologyLedger(_BatchLedger):
    def bind_final_infrastructure_topology(self, **kwargs: Any) -> object:
        capability = super().bind_final_infrastructure_topology(**kwargs)
        assert self.topology is not None
        self.topology.plan_payload_hash = "0" * 64
        return capability


class _ExpiredTopologyLedger(_BatchLedger):
    def bind_final_infrastructure_topology(self, **kwargs: Any) -> object:
        capability = super().bind_final_infrastructure_topology(**kwargs)
        assert self.topology is not None
        self.topology.valid_until = kwargs["now"]
        return capability


class _ShortTopologyLedger(_BatchLedger):
    def bind_final_infrastructure_topology(self, **kwargs: Any) -> object:
        capability = super().bind_final_infrastructure_topology(**kwargs)
        assert self.topology is not None
        self.topology.valid_until = kwargs["now"] + timedelta(minutes=3)
        return capability


class _ExpiryAwareLedger(_BatchLedger):
    def bind_final_infrastructure_topology(self, **kwargs: Any) -> object:
        if kwargs["now"] > NOW:
            self.bind_calls += 1
            raise BudgetLedgerError("authorization expired")
        return super().bind_final_infrastructure_topology(**kwargs)


class _InvalidCapLedger(_BatchLedger):
    def bind_final_infrastructure_topology(self, **kwargs: Any) -> object:
        self.bind_calls += 1
        raise BudgetLedgerError("provider cap proof is invalid")


def _manifest_from_receipt(receipt: DeploymentReceipt) -> ProviderDeploymentManifest:
    content = receipt.content
    nonce_digit = content.operation_marker[-1]
    return ProviderDeploymentManifest(
        deployed_model=content.deployed_model,
        base_model=cast(Any, content.base_model),
        plan=content.receipt_plan,
        input_tpm=content.input_tpm,
        output_tpm=content.output_tpm,
        status="RUNNING",
        gmt_create=content.gmt_create,
        gmt_modified=content.gmt_modified,
        workspace_ref=content.workspace_ref,
        ownership_nonce=nonce_digit * 32,
        operation_marker=content.operation_marker,
        deployment_suffix=content.deployment_suffix,
    )


class _ObservationRefresher:
    def __init__(
        self,
        *,
        fail_boundary: str | None = None,
        expiry_delta: timedelta = timedelta(minutes=5),
    ) -> None:
        self.fail_boundary = fail_boundary
        self.expiry_delta = expiry_delta
        self.calls = 0

    def __call__(
        self,
        *,
        topology: object,
        strong: TopologyReconciliationTargetV1,
        weak: TopologyReconciliationTargetV1,
        now: datetime,
    ) -> TopologyReconciliationObservationBatchArtifact:
        self.calls += 1
        if self.fail_boundary is not None:
            raise ValueError(f"{self.fail_boundary} deployment manifest drifted")
        exact_topology = cast(Any, topology)
        batch = TopologyReconciliationObservationBatchV1(
            version=(
                "insurancekb.run-admission."
                "topology-reconciliation-observation-batch.v1"
            ),
            issuer="bailian-deployment-controller-v1",
            run_identity=exact_topology.run_identity,
            purpose=exact_topology.purpose,
            scope=exact_topology.scope,
            topology_digest=exact_topology.topology_digest,
            plan_payload_hash=exact_topology.plan_payload_hash,
            provider_cap_evidence_digest=(
                exact_topology.provider_cap_evidence_digest
            ),
            provider_cap_approval_digest=(
                exact_topology.provider_cap_approval_digest
            ),
            transport_identity_digest="7" * 64,
            strong=strong,
            weak=weak,
            observed_at=now,
            expires_at=now + self.expiry_delta,
        )
        return TopologyReconciliationObservationBatchArtifact(
            batch=batch,
            batch_digest="8" * 64,
            artifact_path=Path("topology-observation-batch.json"),
        )


class _InfrastructureFailureObservationRefresher(_ObservationRefresher):
    def __init__(self, failure: BaseException) -> None:
        super().__init__()
        self.failure = failure

    def __call__(
        self,
        *,
        topology: object,
        strong: TopologyReconciliationTargetV1,
        weak: TopologyReconciliationTargetV1,
        now: datetime,
    ) -> TopologyReconciliationObservationBatchArtifact:
        self.calls += 1
        raise self.failure


def _testing_finalizer(
    *,
    ledger: object,
    evaluator: object,
    clock: Any,
    observation_refresher: _ObservationRefresher | None = None,
) -> OperationalAdmissionFinalizer:
    return OperationalAdmissionFinalizer._for_testing(
        ledger=ledger,
        evaluator=evaluator,
        clock=clock,
        observation_refresher=observation_refresher or _ObservationRefresher(),
    )


def _admission(
    document: RunAdmissionDocument,
    *,
    failed_role: str | None = None,
    forced_state: str | None = None,
    mismatched_role: str | None = None,
    observed_at: datetime = NOW,
    evaluated_at: datetime = NOW,
    expires_at: datetime | None = None,
    include_verified_cap: bool = True,
) -> AdmissionResult:
    check_expiry = expires_at or NOW + timedelta(minutes=10)
    probes = tuple(
        ProbeResult(
            role=role,
            verified=role != failed_role,
            provider="bailian",
            model_id=(
                "wrong-deployment"
                if role == mismatched_role
                else document.plan.payload.model_roles[role].model_id
            ),
            observed_at=observed_at,
            observed_deployment_id=document.plan.payload.model_roles[
                role
            ].immutable_deployment_id,
            blockers=(
                ()
                if role != failed_role
                else cast(
                    Any,
                    (
                        {
                            "code": "deployment_not_running",
                            "message": "not running",
                        },
                    ),
                )
            ),
        )
        for role in ("annotator", "weak_extractor", "judge")
    )
    probe_checks = tuple(
        AdmissionCheck(
            name=f"provider_probe:{role}",
            passed=role != failed_role,
            blocker_code=(
                None if role != failed_role else "deployment_not_running"
            ),
            observed_at=NOW,
            expires_at=check_expiry,
        )
        for role in ("annotator", "judge", "weak_extractor")
    )
    state = forced_state or ("READY" if failed_role is None else "BLOCKED")
    budget_checks = (
        (
            AdmissionCheck(
                name="budget_approval",
                passed=True,
                observed_at=NOW,
                expires_at=check_expiry,
            ),
            AdmissionCheck(
                name="budget_ledger",
                passed=True,
                observed_at=NOW,
                expires_at=check_expiry,
            ),
        )
        if include_verified_cap
        else ()
    )
    checks = tuple(sorted(probe_checks + budget_checks, key=lambda check: check.name))
    evidence = AdmissionEvidence.model_construct(
        identity=cast(Any, None),
        approvals=(
            (
                ApprovalAuditEvidence(
                    domain="budget",
                    verified=True,
                    key_id="budget-key",
                    approver_identity="finance",
                    expires_at=check_expiry,
                ),
            )
            if include_verified_cap
            else ()
        ),
        probes=probes,
        budget=(
            BudgetAdmissionProof(
                contract_hash="a" * 64,
                approval_digest="b" * 64,
                revision=1,
                currency="CNY",
                ceiling=BudgetAmounts(
                    input_tokens=0,
                    output_tokens=0,
                    cost_minor_units=10_000,
                ),
                price_expires_at=check_expiry,
                provider_attestation_expires_at=check_expiry,
            )
            if include_verified_cap
            else None
        ),
    )
    return AdmissionResult.model_construct(
        state=state,
        plan_payload_hash=plan_payload_hash(document.plan),
        evaluated_revision="a" * 40,
        evaluated_at=evaluated_at,
        checker_version="020.1",
        runtime_capability_version="budget-ledger-v3-canary-v1",
        checks=checks,
        blockers=(
            ()
            if state == "READY"
            else (AdmissionBlocker(check="admission", code="blocked"),)
        ),
        evidence=evidence,
    )


def _with_verified_budget_authority_expiry(
    admission: AdmissionResult, *, expires_at: datetime
) -> AdmissionResult:
    assert admission.evidence is not None
    evidence = AdmissionEvidence.model_construct(
        identity=admission.evidence.identity,
        approvals=(
            ApprovalAuditEvidence(
                domain="budget",
                verified=True,
                key_id="budget-key",
                approver_identity="finance",
                expires_at=expires_at,
            ),
        ),
        probes=admission.evidence.probes,
        budget=admission.evidence.budget,
    )
    admission_values = dict(admission.__dict__)
    admission_values["evidence"] = evidence
    return AdmissionResult.model_construct(**admission_values)


class _AdmitOnceEvaluator:
    def __init__(self, result: AdmissionResult) -> None:
        self.result = result
        self.calls = 0

    def admit_budget_account(
        self, document: RunAdmissionDocument, ledger: object
    ) -> tuple[AdmissionResult, AccountSnapshot | None]:
        self.calls += 1
        return self.result, cast(AccountSnapshot, object())


class _SequenceEvaluator:
    def __init__(self, *results: AdmissionResult) -> None:
        self.results = results
        self.calls = 0

    def admit_budget_account(
        self, document: RunAdmissionDocument, ledger: object
    ) -> tuple[AdmissionResult, AccountSnapshot | None]:
        result = self.results[self.calls]
        self.calls += 1
        return result, cast(AccountSnapshot, object())


class _ExplodingEvaluator:
    def admit_budget_account(
        self, document: RunAdmissionDocument, ledger: object
    ) -> tuple[AdmissionResult, AccountSnapshot | None]:
        raise RuntimeError("provider probe transport failed")


class _SequenceClock:
    def __init__(self, *values: datetime) -> None:
        self._values = iter(values)
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        return next(self._values)


def _clock_at_now() -> datetime:
    return NOW


def _finalization_request(document: RunAdmissionDocument) -> OperationalFinalizationRequest:
    return OperationalFinalizationRequest(
        document=document,
        strong=_binding(strong=True),
        weak=_binding(strong=False),
        contract=cast(BudgetContract, object()),
        envelope=cast(BudgetApprovalEnvelope, object()),
        expected_scope="goldenset-production",
    )


def test_o8_finalizer_uses_public_atomic_batch_and_one_admit_evaluator_call() -> None:
    document = _document()
    ledger = _BatchLedger()
    evaluator = _AdmitOnceEvaluator(_admission(document))
    finalizer = _testing_finalizer(
        ledger=ledger, evaluator=evaluator, clock=_clock_at_now
    )

    result = finalizer.finalize(_finalization_request(document))
    replay = finalizer.finalize(_finalization_request(document))

    assert result.state == "READY"
    assert result.probes == result.verified_probes == 3
    assert result.controller_inference_requests == 0
    assert replay == result
    assert ledger.bind_calls == 2
    assert evaluator.calls == 2


def test_o8_finalizer_uses_owned_start_and_verification_clocks() -> None:
    document = _document()
    ledger = _BatchLedger()
    evaluated_at = NOW + timedelta(seconds=1)
    evaluator = _AdmitOnceEvaluator(
        _admission(
            document,
            observed_at=evaluated_at,
            evaluated_at=evaluated_at,
        )
    )
    clock = _SequenceClock(
        NOW,
        NOW + timedelta(seconds=2),
        NOW + timedelta(seconds=2),
    )
    request = _finalization_request(document)
    finalizer = _testing_finalizer(
        ledger=ledger,
        evaluator=evaluator,
        clock=clock,
    )

    result = finalizer.finalize(request)

    assert result.state == "READY"
    assert clock.calls == 3
    assert ledger.bind_calls == 1
    assert ledger.bind_times == [NOW]


def test_o8_same_plan_revalidates_changed_receipt_authorization_and_now() -> None:
    document = _document()
    ledger = _ExpiryAwareLedger()
    evaluator = _AdmitOnceEvaluator(_admission(document))
    finalizer = _testing_finalizer(
        ledger=ledger,
        evaluator=evaluator,
        clock=_SequenceClock(NOW, NOW, NOW, NOW + timedelta(hours=1)),
    )
    first_request = _finalization_request(document)
    changed_strong = _binding(
        strong=True,
        digit="3",
        authorization=object(),
    )

    first = finalizer.finalize(first_request)
    expired = finalizer.finalize(
        replace(
            first_request,
            strong=changed_strong,
        )
    )

    assert first.state == "READY"
    assert expired.state == "BLOCKED"
    assert tuple(item.code for item in expired.blockers) == ("final_topology_invalid",)
    assert ledger.bind_calls == 1
    assert evaluator.calls == 1


def test_o8_two_finalizer_instances_never_reuse_an_old_ready_result() -> None:
    document = _document()
    ledger = _BatchLedger()
    evaluator = _SequenceEvaluator(
        _admission(document),
        _admission(document, forced_state="BLOCKED"),
    )

    first = _testing_finalizer(
        ledger=ledger, evaluator=evaluator, clock=_clock_at_now
    ).finalize(_finalization_request(document))
    second = _testing_finalizer(
        ledger=ledger, evaluator=evaluator, clock=_clock_at_now
    ).finalize(_finalization_request(document))

    assert first.state == "READY"
    assert second.state == "BLOCKED"
    assert ledger.bind_calls == evaluator.calls == 2


def test_o8_probe_failure_blocks_ready_after_single_admission_evaluation() -> None:
    document = _document()
    ledger = _BatchLedger()
    evaluator = _AdmitOnceEvaluator(_admission(document, failed_role="judge"))
    finalizer = _testing_finalizer(
        ledger=ledger, evaluator=evaluator, clock=_clock_at_now
    )

    result = finalizer.finalize(_finalization_request(document))

    assert result.state == "BLOCKED"
    assert result.phase == "admit"
    assert tuple(item.code for item in result.blockers) == ("admission_blocked",)
    assert result.verified_probes == 2
    assert evaluator.calls == 1


def test_o8_blocked_admission_with_three_verified_probes_never_becomes_ready() -> None:
    document = _document()
    ledger = _BatchLedger()
    evaluator = _AdmitOnceEvaluator(
        _admission(document, forced_state="BLOCKED")
    )
    finalizer = _testing_finalizer(
        ledger=ledger, evaluator=evaluator, clock=_clock_at_now
    )

    result = finalizer.finalize(_finalization_request(document))

    assert result.state == "BLOCKED"
    assert result.phase == "admit"
    assert tuple(item.code for item in result.blockers) == ("admission_blocked",)
    assert result.probes == result.verified_probes == 3


def test_o8_invalid_role_topology_is_typed_blocker_before_bind_or_probe() -> None:
    document = _document()
    ledger = _BatchLedger()
    evaluator = _AdmitOnceEvaluator(_admission(document))
    finalizer = _testing_finalizer(
        ledger=ledger, evaluator=evaluator, clock=_clock_at_now
    )
    request = _finalization_request(document)

    result = finalizer.finalize(
        replace(
            request,
            weak=replace(request.weak, roles=("annotator", "judge")),
        )
    )

    assert result.state == "BLOCKED"
    assert result.phase == "final_plan"
    assert tuple(item.code for item in result.blockers) == (
        "final_topology_invalid",
    )
    assert ledger.bind_calls == 0
    assert evaluator.calls == 0


def test_o8_missing_exact_role_key_blocks_before_bind_or_probe() -> None:
    document = _document()
    payload = document.plan.payload
    invalid_payload = RunAdmissionPlanPayload.model_construct(
        run_identity=payload.run_identity,
        purpose=payload.purpose,
        model_roles={
            "annotator": payload.model_roles["annotator"],
            "weak_extractor": payload.model_roles["weak_extractor"],
        },
        identity_contract_hash=payload.identity_contract_hash,
        budget_contract_hash=payload.budget_contract_hash,
    )
    invalid_document = cast(
        RunAdmissionDocument,
        SimpleNamespace(plan=RunAdmissionPlan.model_construct(payload=invalid_payload)),
    )
    ledger = _BatchLedger()
    evaluator = _AdmitOnceEvaluator(_admission(document))

    result = _testing_finalizer(
        ledger=ledger, evaluator=evaluator, clock=_clock_at_now
    ).finalize(_finalization_request(invalid_document))

    assert result.state == "BLOCKED"
    assert tuple(item.code for item in result.blockers) == (
        "final_topology_invalid",
    )
    assert ledger.bind_calls == evaluator.calls == 0


def test_o8_evaluator_exception_becomes_stable_blocker() -> None:
    document = _document()
    ledger = _BatchLedger()

    result = _testing_finalizer(
        ledger=ledger,
        evaluator=_ExplodingEvaluator(),
        clock=_clock_at_now,
    ).finalize(_finalization_request(document))

    assert result.state == "BLOCKED"
    assert tuple(item.code for item in result.blockers) == (
        "admission_evaluation_failed",
    )
    assert ledger.bind_calls == 1


@pytest.mark.parametrize(
    "failure",
    ["final_topology_invalid", "final_bind_blocked", "admission_evaluation_failed"],
)
def test_o8_failed_finalization_never_infers_verified_cap_from_failure_type(
    failure: str,
) -> None:
    document = _document()
    request = _finalization_request(document)
    ledger: _BatchLedger = _BatchLedger()
    evaluator: object = _AdmitOnceEvaluator(_admission(document))
    if failure == "final_topology_invalid":
        request = replace(
            request,
            weak=replace(request.weak, roles=("annotator", "judge")),
        )
    elif failure == "final_bind_blocked":
        ledger = _InvalidCapLedger()
    else:
        evaluator = _ExplodingEvaluator()

    result = _testing_finalizer(
        ledger=ledger,
        evaluator=evaluator,
        clock=_clock_at_now,
    ).finalize(request)

    assert result.state == "BLOCKED"
    assert tuple(item.code for item in result.blockers) == (failure,)
    assert result.cost_exposure == "continuing_unbounded_until_signed_cap"


def test_o7_o8_verified_topology_not_020_budget_dto_establishes_cap() -> None:
    document = _document()
    result = _testing_finalizer(
        ledger=_BatchLedger(),
        evaluator=_AdmitOnceEvaluator(
            _admission(document, include_verified_cap=False)
        ),
        clock=_SequenceClock(NOW, NOW, NOW),
    ).finalize(_finalization_request(document))

    assert result.state == "READY"
    assert result.phase == "ready"
    assert result.cost_exposure == "bounded_by_verified_provider_cap"


def test_o7_o8_020_budget_proof_and_fake_bound_rows_cannot_mint_ready() -> None:
    """A 020 budget DTO is not the independently signed durable 031 cap/topology."""

    document = _document()
    ledger = _SnapshotOnlyLedger()
    evaluator = _AdmitOnceEvaluator(_admission(document, include_verified_cap=True))

    result = _testing_finalizer(
        ledger=ledger,
        evaluator=evaluator,
        clock=_SequenceClock(NOW, NOW),
    ).finalize(_finalization_request(document))

    assert result.state == "BLOCKED"
    assert result.cost_exposure == "continuing_unbounded_until_signed_cap"
    assert result.controller_inference_requests == 0
    assert ledger.bind_calls == 1
    assert evaluator.calls == 0


def test_o7_o8_testing_topology_cannot_enter_production_finalizer() -> None:
    document = _document()
    ledger = _BatchLedger()
    evaluator = _AdmitOnceEvaluator(_admission(document))

    finalizer = OperationalAdmissionFinalizer(
        ledger=cast(BudgetLedger, ledger),
        evaluator=evaluator,
    )
    finalizer._clock = _clock_at_now

    result = finalizer.finalize(_finalization_request(document))

    assert result.state == "BLOCKED"
    assert tuple(item.code for item in result.blockers) == ("final_topology_invalid",)
    assert result.cost_exposure == "continuing_unbounded_until_signed_cap"
    assert evaluator.calls == 0


@pytest.mark.parametrize(
    "ledger_type",
    (_SnapshotOnlyLedger, _DriftedTopologyLedger, _ExpiredTopologyLedger),
)
def test_o7_o8_missing_drifted_or_expired_final_topology_blocks_before_probe(
    ledger_type: type[_BatchLedger],
) -> None:
    document = _document()
    ledger = ledger_type()
    evaluator = _AdmitOnceEvaluator(_admission(document, include_verified_cap=True))

    result = _testing_finalizer(
        ledger=ledger,
        evaluator=evaluator,
        clock=_clock_at_now,
    ).finalize(_finalization_request(document))

    assert result.state == "BLOCKED"
    assert result.phase == "final_plan"
    assert tuple(item.code for item in result.blockers) == ("final_bind_blocked",)
    assert result.cost_exposure == "continuing_unbounded_until_signed_cap"
    assert result.controller_inference_requests == 0
    assert evaluator.calls == 0


def test_o8_expired_probe_checks_cannot_produce_ready() -> None:
    document = _document()
    ledger = _BatchLedger()
    evaluator = _AdmitOnceEvaluator(
        _admission(document, expires_at=NOW + timedelta(minutes=5))
    )
    request = _finalization_request(document)

    result = _testing_finalizer(
        ledger=ledger,
        evaluator=evaluator,
        clock=_SequenceClock(
            NOW,
            NOW + timedelta(minutes=6),
            NOW + timedelta(minutes=6),
        ),
        observation_refresher=_ObservationRefresher(
            expiry_delta=timedelta(minutes=10)
        ),
    ).finalize(request)

    assert result.state == "BLOCKED"
    assert result.phase == "probe"
    assert tuple(item.code for item in result.blockers) == (
        "probe_observation_expired",
    )


def test_o8_ready_result_exposes_earliest_evidence_expiry() -> None:
    document = _document()
    expires_at = NOW + timedelta(minutes=5)
    result = _testing_finalizer(
        ledger=_BatchLedger(),
        evaluator=_AdmitOnceEvaluator(
            _admission(document, evaluated_at=NOW, expires_at=expires_at)
        ),
        clock=_SequenceClock(NOW, NOW, NOW),
    ).finalize(_finalization_request(document))

    assert result.state == "READY"
    assert getattr(result, "evaluated_at", None) == NOW
    assert getattr(result, "valid_until", None) == expires_at


def test_o7_o8_ready_valid_until_includes_independent_topology_cap_expiry() -> None:
    document = _document()
    result = _testing_finalizer(
        ledger=_ShortTopologyLedger(),
        evaluator=_AdmitOnceEvaluator(
            _admission(
                document,
                evaluated_at=NOW,
                expires_at=NOW + timedelta(minutes=10),
            )
        ),
        clock=_SequenceClock(NOW, NOW, NOW),
    ).finalize(_finalization_request(document))

    assert result.state == "READY"
    assert result.valid_until == NOW + timedelta(minutes=3)


def test_o8_ready_result_uses_earlier_verified_authority_expiry() -> None:
    document = _document()
    check_expiry = NOW + timedelta(minutes=10)
    authority_expiry = NOW + timedelta(minutes=4)
    admission = _with_verified_budget_authority_expiry(
        _admission(document, evaluated_at=NOW, expires_at=check_expiry),
        expires_at=authority_expiry,
    )

    result = _testing_finalizer(
        ledger=_BatchLedger(),
        evaluator=_AdmitOnceEvaluator(admission),
        clock=_SequenceClock(NOW, NOW, NOW),
    ).finalize(_finalization_request(document))

    assert result.state == "READY"
    assert result.valid_until == authority_expiry


def test_o8_expired_verified_authority_cannot_produce_ready() -> None:
    document = _document()
    admission = _with_verified_budget_authority_expiry(
        _admission(
            document,
            evaluated_at=NOW,
            expires_at=NOW + timedelta(minutes=10),
        ),
        expires_at=NOW + timedelta(minutes=2),
    )

    result = _testing_finalizer(
        ledger=_BatchLedger(),
        evaluator=_AdmitOnceEvaluator(admission),
        clock=_SequenceClock(
            NOW,
            NOW + timedelta(minutes=3),
            NOW + timedelta(minutes=3),
        ),
    ).finalize(_finalization_request(document))

    assert result.state == "BLOCKED"
    assert result.phase == "probe"
    assert result.valid_until is None


def test_o8_probe_model_identity_mismatch_cannot_produce_ready() -> None:
    document = _document()
    result = _testing_finalizer(
        ledger=_BatchLedger(),
        evaluator=_AdmitOnceEvaluator(
            _admission(document, mismatched_role="weak_extractor")
        ),
        clock=_clock_at_now,
    ).finalize(_finalization_request(document))

    assert result.state == "BLOCKED"
    assert result.phase == "probe"
    assert tuple(item.code for item in result.blockers) == (
        "probe_verification_incomplete",
    )


def _seed_final_topology(ledger: _BatchLedger, document: RunAdmissionDocument) -> None:
    request = _finalization_request(document)
    ledger.bind_final_infrastructure_topology(
        strong=request.strong,
        weak=request.weak,
        plan=request.document.plan.payload,
        contract=request.contract,
        envelope=request.envelope,
        expected_scope=request.expected_scope,
        now=NOW,
    )


class _PostEvaluationLedger(_BatchLedger):
    def __init__(self, *, second_read_failure: BaseException | None = None) -> None:
        super().__init__()
        self.second_read_failure = second_read_failure
        self.fresh_reads = 0

    def _require_fresh_final_topology_for_testing(
        self,
        *,
        plan: object,
        expected_scope: str,
        now: datetime,
    ) -> object:
        self.fresh_reads += 1
        if self.fresh_reads == 2 and self.second_read_failure is not None:
            raise self.second_read_failure
        return super()._require_fresh_final_topology_for_testing(
            plan=plan,
            expected_scope=expected_scope,
            now=now,
        )


@pytest.mark.parametrize(
    "drift_field",
    ("topology_digest", "provider_cap_approval_digest", "valid_until"),
)
def test_o8_t9_18_candidate_evaluator_drift_fails_postcheck(
    drift_field: str,
) -> None:
    document = _document()
    ledger = _PostEvaluationLedger()
    _seed_final_topology(ledger, document)
    finalizer = _testing_finalizer(
        ledger=ledger,
        evaluator=_AdmitOnceEvaluator(_admission(document)),
        clock=_SequenceClock(NOW, NOW),
    )
    evaluator_calls = 0

    def evaluate_candidate() -> object:
        nonlocal evaluator_calls
        evaluator_calls += 1
        assert ledger.topology is not None
        replacement: object = (
            NOW if drift_field == "valid_until" else "0" * 64
        )
        setattr(ledger.topology, drift_field, replacement)
        return object()

    with pytest.raises(BudgetLedgerError, match="post-evaluator"):
        finalizer.evaluate_with_fresh_topology_postcheck(
            document,
            expected_scope="goldenset-production",
            evaluation=evaluate_candidate,
        )

    assert evaluator_calls == 1
    assert ledger.fresh_reads == 2


@pytest.mark.parametrize("failure_type", (sqlite3.OperationalError, OSError))
def test_o8_t9_18_candidate_postcheck_infrastructure_failure_is_typed(
    failure_type: type[BaseException],
) -> None:
    document = _document()
    ledger = _PostEvaluationLedger(
        second_read_failure=failure_type("post-evaluator durable reload failed")
    )
    _seed_final_topology(ledger, document)
    finalizer = _testing_finalizer(
        ledger=ledger,
        evaluator=_AdmitOnceEvaluator(_admission(document)),
        clock=_SequenceClock(NOW, NOW),
    )
    evaluator_calls = 0

    def evaluate_candidate() -> object:
        nonlocal evaluator_calls
        evaluator_calls += 1
        return object()

    with pytest.raises(BudgetLedgerError, match="post-evaluator"):
        finalizer.evaluate_with_fresh_topology_postcheck(
            document,
            expected_scope="goldenset-production",
            evaluation=evaluate_candidate,
        )

    assert evaluator_calls == 1
    assert ledger.fresh_reads == 2


@pytest.mark.parametrize("failure", (KeyboardInterrupt(), SystemExit()))
def test_o8_t9_18_candidate_postcheck_process_control_exception_propagates(
    failure: BaseException,
) -> None:
    document = _document()
    ledger = _PostEvaluationLedger(second_read_failure=failure)
    _seed_final_topology(ledger, document)
    finalizer = _testing_finalizer(
        ledger=ledger,
        evaluator=_AdmitOnceEvaluator(_admission(document)),
        clock=_SequenceClock(NOW, NOW),
    )
    evaluator_calls = 0

    def evaluate_candidate() -> object:
        nonlocal evaluator_calls
        evaluator_calls += 1
        return object()

    with pytest.raises(type(failure)):
        finalizer.evaluate_with_fresh_topology_postcheck(
            document,
            expected_scope="goldenset-production",
            evaluation=evaluate_candidate,
        )

    assert evaluator_calls == 1
    assert ledger.fresh_reads == 2


def test_o8_t9_18_candidate_postcheck_normal_path_evaluates_once() -> None:
    document = _document()
    ledger = _PostEvaluationLedger()
    _seed_final_topology(ledger, document)
    finalizer = _testing_finalizer(
        ledger=ledger,
        evaluator=_AdmitOnceEvaluator(_admission(document)),
        clock=_SequenceClock(NOW, NOW),
    )
    decision = object()
    evaluator_calls = 0

    def evaluate_candidate() -> object:
        nonlocal evaluator_calls
        evaluator_calls += 1
        return decision

    result = finalizer.evaluate_with_fresh_topology_postcheck(
        document,
        expected_scope="goldenset-production",
        evaluation=evaluate_candidate,
    )

    assert result is decision
    assert evaluator_calls == 1
    assert ledger.fresh_reads == 2


def test_o7_o8_missing_static_topology_performs_zero_observation_or_evaluation() -> None:
    document = _document()
    ledger = _BatchLedger()
    refresher = _ObservationRefresher()
    evaluator = _AdmitOnceEvaluator(_admission(document))

    result = _testing_finalizer(
        ledger=ledger,
        evaluator=evaluator,
        clock=_clock_at_now,
        observation_refresher=refresher,
    ).finalize_durable(document, expected_scope="goldenset-production")

    assert result.state == "BLOCKED"
    assert tuple(item.code for item in result.blockers) == (
        "final_topology_unavailable",
    )
    assert refresher.calls == 0
    assert evaluator.calls == 0
    assert ledger.bind_calls == 0


@pytest.mark.parametrize("production", (False, True), ids=("testing", "production"))
@pytest.mark.parametrize(
    "failure_type",
    (sqlite3.DatabaseError, sqlite3.OperationalError, OSError),
    ids=("database-error", "operational-error", "os-error"),
)
def test_o7_o8_static_topology_infrastructure_failure_is_typed_before_evaluation(
    production: bool,
    failure_type: type[BaseException],
) -> None:
    document = _document()
    ledger = _InfrastructureFailureLedger(failure_type("durable topology unavailable"))
    evaluator = _AdmitOnceEvaluator(_admission(document))
    if production:
        finalizer = OperationalAdmissionFinalizer(
            ledger=cast(Any, ledger),
            evaluator=cast(Any, evaluator),
        )
    else:
        finalizer = _testing_finalizer(
            ledger=ledger,
            evaluator=evaluator,
            clock=_clock_at_now,
        )

    result = finalizer.finalize_durable(
        document,
        expected_scope="goldenset-production",
    )

    assert result.state == "BLOCKED"
    assert tuple(item.code for item in result.blockers) == (
        "final_topology_unavailable",
    )
    assert result.cost_exposure == "continuing_unbounded_until_signed_cap"
    assert ledger.fresh_reads == 1
    assert ledger.cap_reads == 0
    assert ledger.bind_calls == 0
    assert evaluator.calls == 0


@pytest.mark.parametrize(
    "failure_type",
    (sqlite3.DatabaseError, sqlite3.OperationalError, OSError),
    ids=("database-error", "operational-error", "os-error"),
)
def test_o7_o8_testing_observation_infrastructure_failure_is_typed_before_evaluation(
    failure_type: type[BaseException],
) -> None:
    document = _document()
    ledger = _BatchLedger()
    _seed_final_topology(ledger, document)
    evaluator = _AdmitOnceEvaluator(_admission(document))
    refresher = _InfrastructureFailureObservationRefresher(
        failure_type("observation store unavailable")
    )

    result = _testing_finalizer(
        ledger=ledger,
        evaluator=evaluator,
        clock=_clock_at_now,
        observation_refresher=refresher,
    ).finalize_durable(document, expected_scope="goldenset-production")

    assert result.state == "BLOCKED"
    assert tuple(item.code for item in result.blockers) == (
        "topology_observation_blocked",
    )
    assert result.cost_exposure == "continuing_unbounded_until_signed_cap"
    assert refresher.calls == 1
    assert evaluator.calls == 0
    assert ledger.bind_calls == 1


@pytest.mark.parametrize(
    "failure_type",
    (sqlite3.DatabaseError, sqlite3.OperationalError, OSError),
    ids=("database-error", "operational-error", "os-error"),
)
def test_o7_o8_production_controller_infrastructure_failure_is_typed_before_provider_io(
    failure_type: type[BaseException],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _document()
    ledger = _CapReaderInfrastructureFailureLedger(
        failure_type("provider cap ledger unavailable")
    )
    _seed_final_topology(ledger, document)
    evaluator = _AdmitOnceEvaluator(_admission(document))
    monkeypatch.setattr(
        "insurance_harness.goldenset.admission_coordinator."
        "require_verified_final_topology",
        lambda capability, **kwargs: capability,
    )
    controller_calls: list[dict[str, object]] = []

    def fail_controller(
        _cls: type[DeploymentController], **kwargs: object
    ) -> DeploymentController:
        controller_calls.append(kwargs)
        raise failure_type("provider topology controller unavailable")

    monkeypatch.setattr(
        DeploymentController,
        "for_production",
        classmethod(fail_controller),
    )

    result = OperationalAdmissionFinalizer(
        ledger=cast(Any, ledger),
        evaluator=cast(Any, evaluator),
    ).finalize_durable(document, expected_scope="goldenset-production")

    assert result.state == "BLOCKED"
    assert tuple(item.code for item in result.blockers) == (
        "topology_observation_blocked",
    )
    assert result.cost_exposure == "continuing_unbounded_until_signed_cap"
    assert ledger.fresh_reads == 1
    assert ledger.cap_reads == 0
    assert controller_calls == [
        {
            "plan": document.plan.payload,
            "expected_scope": "goldenset-production",
        }
    ]
    assert ledger.bind_calls == 1
    assert evaluator.calls == 0


@pytest.mark.parametrize("failure_type", (KeyboardInterrupt, SystemExit))
@pytest.mark.parametrize("boundary", ("topology", "observation"))
def test_o7_o8_process_control_exceptions_are_never_mapped_to_typed_blockers(
    failure_type: type[BaseException],
    boundary: str,
) -> None:
    document = _document()
    ledger: _BatchLedger
    if boundary == "topology":
        ledger = _InfrastructureFailureLedger(failure_type())
        refresher = _ObservationRefresher()
    else:
        ledger = _BatchLedger()
        _seed_final_topology(ledger, document)
        refresher = _InfrastructureFailureObservationRefresher(failure_type())

    with pytest.raises(failure_type):
        _testing_finalizer(
            ledger=ledger,
            evaluator=_AdmitOnceEvaluator(_admission(document)),
            clock=_clock_at_now,
            observation_refresher=refresher,
        ).finalize_durable(document, expected_scope="goldenset-production")


def test_o7_o8_three_fresh_boundaries_do_not_reuse_failed_middle_observation() -> None:
    document = _document()
    ledger = _BatchLedger()
    _seed_final_topology(ledger, document)
    evaluator = _AdmitOnceEvaluator(_admission(document))
    first = _ObservationRefresher()
    middle = _InfrastructureFailureObservationRefresher(
        sqlite3.OperationalError("observation transaction unavailable")
    )
    third = _ObservationRefresher()

    results = tuple(
        _testing_finalizer(
            ledger=ledger,
            evaluator=evaluator,
            clock=_clock_at_now,
            observation_refresher=refresher,
        ).finalize_durable(document, expected_scope="goldenset-production")
        for refresher in (first, middle, third)
    )

    assert tuple(result.state for result in results) == ("READY", "BLOCKED", "READY")
    assert tuple(item.code for item in results[1].blockers) == (
        "topology_observation_blocked",
    )
    assert first.calls == middle.calls == third.calls == 1
    assert evaluator.calls == 2


def test_o7_o8_old_observation_batch_is_never_reused_at_new_boundary() -> None:
    document = _document()
    ledger = _BatchLedger()
    _seed_final_topology(ledger, document)
    evaluator = _AdmitOnceEvaluator(
        _admission(
            document,
            observed_at=NOW + timedelta(minutes=5, seconds=1),
            evaluated_at=NOW + timedelta(minutes=5, seconds=1),
            expires_at=NOW + timedelta(minutes=15),
        )
    )
    unavailable = _ObservationRefresher(fail_boundary="stale")
    boundary_now = NOW + timedelta(minutes=5, seconds=1)

    blocked = _testing_finalizer(
        ledger=ledger,
        evaluator=evaluator,
        clock=lambda: boundary_now,
        observation_refresher=unavailable,
    ).finalize_durable(document, expected_scope="goldenset-production")
    fresh_refresher = _ObservationRefresher()
    ready = _testing_finalizer(
        ledger=ledger,
        evaluator=evaluator,
        clock=lambda: boundary_now,
        observation_refresher=fresh_refresher,
    ).finalize_durable(document, expected_scope="goldenset-production")

    assert blocked.state == "BLOCKED"
    assert tuple(item.code for item in blocked.blockers) == (
        "topology_observation_blocked",
    )
    assert unavailable.calls == 1
    assert ready.state == "READY"
    assert fresh_refresher.calls == 1
    assert evaluator.calls == 1


@pytest.mark.parametrize("boundary", ("strong", "weak"))
def test_o7_o8_topology_observation_drift_blocks_before_evaluator(
    boundary: str,
) -> None:
    document = _document()
    ledger = _BatchLedger()
    _seed_final_topology(ledger, document)
    evaluator = _AdmitOnceEvaluator(_admission(document))
    refresher = _ObservationRefresher(fail_boundary=boundary)

    result = _testing_finalizer(
        ledger=ledger,
        evaluator=evaluator,
        clock=_clock_at_now,
        observation_refresher=refresher,
    ).finalize_durable(document, expected_scope="goldenset-production")

    assert result.state == "BLOCKED"
    assert tuple(item.code for item in result.blockers) == (
        "topology_observation_blocked",
    )
    assert refresher.calls == 1
    assert evaluator.calls == 0
    assert ledger.bind_calls == 1


def test_o8_topology_expiry_during_observation_blocks_before_evaluator() -> None:
    document = _document()
    ledger = _BatchLedger()
    _seed_final_topology(ledger, document)
    evaluator = _AdmitOnceEvaluator(_admission(document))

    result = _testing_finalizer(
        ledger=ledger,
        evaluator=evaluator,
        clock=_SequenceClock(NOW, NOW + timedelta(minutes=31)),
        observation_refresher=_ObservationRefresher(
            expiry_delta=timedelta(hours=1)
        ),
    ).finalize_durable(document, expected_scope="goldenset-production")

    assert result.state == "BLOCKED"
    assert tuple(item.code for item in result.blockers) == (
        "final_topology_stale",
    )
    assert evaluator.calls == 0


def test_o7_o8_ready_valid_until_includes_fresh_observation_batch_expiry() -> None:
    document = _document()
    ledger = _BatchLedger()
    _seed_final_topology(ledger, document)
    observation_expiry = NOW + timedelta(minutes=2)

    result = _testing_finalizer(
        ledger=ledger,
        evaluator=_AdmitOnceEvaluator(
            _admission(document, expires_at=NOW + timedelta(minutes=10))
        ),
        clock=_clock_at_now,
        observation_refresher=_ObservationRefresher(
            expiry_delta=timedelta(minutes=2)
        ),
    ).finalize_durable(document, expected_scope="goldenset-production")

    assert result.state == "READY"
    assert result.valid_until == observation_expiry
