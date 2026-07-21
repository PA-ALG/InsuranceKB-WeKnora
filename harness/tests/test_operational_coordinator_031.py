"""OpenSpec 031 O8: the operational admission coordinator fails closed."""

from __future__ import annotations

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
    RunAdmissionDocument,
)
from insurance_harness.goldenset.admission_budget import (
    AccountSnapshot,
    BudgetAmounts,
    BudgetContract,
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
from insurance_harness.goldenset.admission_infrastructure import (
    DeploymentReceipt,
    DeploymentReceiptContent,
    deployment_receipt_content_digest,
    verify_reconciled_deployment_receipt,
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
        remote_manifest_digest=digit * 64,
    )
    local = DeploymentReceipt(
        content=content, content_digest=deployment_receipt_content_digest(content)
    )
    remote = DeploymentReceipt.model_validate(
        local.model_dump(mode="python", round_trip=True)
    )
    return verify_reconciled_deployment_receipt(local, remote_expected=remote)


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

    def bind_final_infrastructure_topology(self, **kwargs: Any) -> object:
        self.bind_calls += 1
        self.bind_times.append(kwargs["now"])
        return (_bound(kwargs["strong"]), _bound(kwargs["weak"]))


class _ExpiryAwareLedger(_BatchLedger):
    def bind_final_infrastructure_topology(self, **kwargs: Any) -> object:
        if kwargs["now"] > NOW:
            self.bind_calls += 1
            raise BudgetLedgerError("authorization expired")
        return super().bind_final_infrastructure_topology(**kwargs)


def _admission(
    document: RunAdmissionDocument,
    *,
    failed_role: str | None = None,
    forced_state: str | None = None,
    mismatched_role: str | None = None,
    observed_at: datetime = NOW,
    evaluated_at: datetime = NOW,
    expires_at: datetime | None = None,
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
    checks = tuple(
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
    evidence = AdmissionEvidence.model_construct(
        identity=cast(Any, None), approvals=(), probes=probes, budget=None
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
        trusted_authorities={},
        expected_scope="goldenset-production",
        authorized_roles=frozenset({"budget_approver"}),
        now=NOW,
    )


def test_o8_finalizer_uses_public_atomic_batch_and_one_admit_evaluator_call() -> None:
    document = _document()
    ledger = _BatchLedger()
    evaluator = _AdmitOnceEvaluator(_admission(document))
    finalizer = OperationalAdmissionFinalizer._for_testing(
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
    clock = _SequenceClock(NOW, NOW + timedelta(seconds=2))
    request = replace(
        _finalization_request(document),
        now=NOW + timedelta(days=365),
    )
    finalizer = OperationalAdmissionFinalizer._for_testing(
        ledger=ledger,
        evaluator=evaluator,
        clock=clock,
    )

    result = finalizer.finalize(request)

    assert result.state == "READY"
    assert clock.calls == 2
    assert ledger.bind_calls == 1
    assert ledger.bind_times == [NOW]


def test_o8_same_plan_revalidates_changed_receipt_authorization_and_now() -> None:
    document = _document()
    ledger = _ExpiryAwareLedger()
    evaluator = _AdmitOnceEvaluator(_admission(document))
    finalizer = OperationalAdmissionFinalizer._for_testing(
        ledger=ledger,
        evaluator=evaluator,
        clock=_SequenceClock(NOW, NOW, NOW + timedelta(hours=1)),
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
            now=NOW + timedelta(hours=1),
        )
    )

    assert first.state == "READY"
    assert expired.state == "BLOCKED"
    assert tuple(item.code for item in expired.blockers) == ("final_bind_blocked",)
    assert ledger.bind_calls == 2
    assert evaluator.calls == 1


def test_o8_two_finalizer_instances_never_reuse_an_old_ready_result() -> None:
    document = _document()
    ledger = _BatchLedger()
    evaluator = _SequenceEvaluator(
        _admission(document),
        _admission(document, forced_state="BLOCKED"),
    )

    first = OperationalAdmissionFinalizer._for_testing(
        ledger=ledger, evaluator=evaluator, clock=_clock_at_now
    ).finalize(_finalization_request(document))
    second = OperationalAdmissionFinalizer._for_testing(
        ledger=ledger, evaluator=evaluator, clock=_clock_at_now
    ).finalize(_finalization_request(document))

    assert first.state == "READY"
    assert second.state == "BLOCKED"
    assert ledger.bind_calls == evaluator.calls == 2


def test_o8_probe_failure_blocks_ready_after_single_admission_evaluation() -> None:
    document = _document()
    ledger = _BatchLedger()
    evaluator = _AdmitOnceEvaluator(_admission(document, failed_role="judge"))
    finalizer = OperationalAdmissionFinalizer._for_testing(
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
    finalizer = OperationalAdmissionFinalizer._for_testing(
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
    finalizer = OperationalAdmissionFinalizer._for_testing(
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

    result = OperationalAdmissionFinalizer._for_testing(
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

    result = OperationalAdmissionFinalizer._for_testing(
        ledger=ledger,
        evaluator=_ExplodingEvaluator(),
        clock=_clock_at_now,
    ).finalize(_finalization_request(document))

    assert result.state == "BLOCKED"
    assert tuple(item.code for item in result.blockers) == (
        "admission_evaluation_failed",
    )
    assert ledger.bind_calls == 1


def test_o8_expired_probe_checks_cannot_produce_ready() -> None:
    document = _document()
    ledger = _BatchLedger()
    evaluator = _AdmitOnceEvaluator(
        _admission(document, expires_at=NOW + timedelta(minutes=5))
    )
    request = _finalization_request(document)

    result = OperationalAdmissionFinalizer._for_testing(
        ledger=ledger,
        evaluator=evaluator,
        clock=_SequenceClock(NOW, NOW + timedelta(minutes=6)),
    ).finalize(request)

    assert result.state == "BLOCKED"
    assert result.phase == "probe"
    assert tuple(item.code for item in result.blockers) == (
        "probe_observation_expired",
    )


def test_o8_probe_model_identity_mismatch_cannot_produce_ready() -> None:
    document = _document()
    result = OperationalAdmissionFinalizer._for_testing(
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
