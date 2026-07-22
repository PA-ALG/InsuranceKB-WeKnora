"""OpenSpec 020 D1.4/D1.5: production evaluator aggregation contracts."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.goldenset.admission import (
    ProductionAdmissionEvaluator,
    RunAdmissionDocument,
)
from insurance_harness.goldenset.admission_budget import (
    BudgetAmounts,
    BudgetContract,
    ProviderSpendCapAttestation,
    RoleRate,
    budget_contract_hash,
    model_role_budget_identity_hash,
)
from insurance_harness.goldenset.admission_identity import (
    IdentityInspectionRequest,
    IdentityInspectionResult,
    identity_contract_hash,
)
from insurance_harness.goldenset.admission_models import (
    BudgetApprovalEntry,
    BudgetApprovalEnvelope,
    BudgetApprovalPayload,
    ModelRolePlan,
    ObservedAnnotationProvenance,
    PendingModelRolePlan,
    ProvenanceApprovalEnvelope,
    ProvenanceApprovalPayload,
    ProvenanceApprovalSelection,
    RunAdmissionPlan,
    RunAdmissionPlanPayload,
    approval_signed_bytes,
    plan_payload_hash,
)
from insurance_harness.goldenset.admission_probe import ProbeRequest, ProbeResult

_NOW = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)


class _PassingIdentityInspector:
    def inspect(self, _request: IdentityInspectionRequest) -> IdentityInspectionResult:
        return IdentityInspectionResult(
            evaluated_revision="f" * 40,
            product_digests={},
            shared_input_digest="a" * 64,
            execution_surface_digest="b" * 64,
            blockers=(),
        )


class _NoNetworkProbe:
    def run(self, _request: ProbeRequest) -> ProbeResult:
        raise AssertionError("pending/static admission must not invoke a provider probe")


class _PassingProbe:
    def run(self, request: ProbeRequest) -> ProbeResult:
        assert request.mode == "remote"
        return ProbeResult(
            role=request.role,
            verified=True,
            provider=request.role_plan.provider,
            model_id=request.role_plan.model_id,
            endpoint_origin="https://dashscope.aliyuncs.com",
            status_class="success",
            latency_ms=1,
            observed_at=_NOW,
            observed_revision=request.role_plan.expected_model_revision,
            observed_deployment_id=request.role_plan.model_id,
        )


def _identity_request(
    provenance: tuple[ProvenanceApprovalSelection, ...] = (),
) -> IdentityInspectionRequest:
    return IdentityInspectionRequest(
        required_dependency_revisions={},
        source_products_root="dataset/shouxian_product",
        golden_products_root="dataset/goldenset/wip-gs-v0.1",
        products=(),
        shared_input_digests={},
        execution_surface_digests={},
        historical_product_ids=tuple(item.product_id for item in provenance),
        historical_provenance=provenance,
    )


def _pending_role(model_id: str) -> PendingModelRolePlan:
    return PendingModelRolePlan(
        identity_status="pending_immutable_identity",
        provider="bailian",
        model_id=model_id,
        protocol="https",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        provider_policy="bailian-deployment-detail-v1",
        credential_env_name="HARNESS_DASHSCOPE_API_KEY",
    )


def test_d1_4_pending_static_document_is_blocked_without_network() -> None:
    document = RunAdmissionDocument(
        plan=RunAdmissionPlan(
            payload=RunAdmissionPlanPayload(
                run_identity="gs-v0.1-run-001",
                purpose="gs-v0.1-baseline",
                model_roles={
                    "annotator": _pending_role("annotator-pending"),
                    "weak_extractor": _pending_role("weak-pending"),
                    "judge": _pending_role("judge-pending"),
                },
                budget_contract_hash=None,
            )
        ),
        identity_request=_identity_request(),
    )
    evaluator = ProductionAdmissionEvaluator._for_testing(
        identity_inspector=_PassingIdentityInspector(),
        provider_probe=_NoNetworkProbe(),
        trusted_public_keys={},
        probe=False,
        clock=lambda: _NOW,
        runtime_capability_ready=False,
    )

    result = evaluator(document)

    assert result.state == "BLOCKED"
    assert result.evidence is not None
    assert {blocker.code for blocker in result.blockers} >= {
        "approval_missing",
        "budget_contract_missing",
        "model_identity_pending",
        "runtime_capability_unattested",
    }


def _roles() -> dict[str, ModelRolePlan]:
    return {
        role: ModelRolePlan(
            provider="bailian",
            model_id=f"{role}-deployment",
            expected_model_revision="2026-07-19T09:00:00Z",
            protocol="https",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            provider_policy="bailian-deployment-detail-v1",
            credential_env_name="HARNESS_DASHSCOPE_API_KEY",
        )
        for role in ("annotator", "weak_extractor", "judge")
    }


def _contract(roles: dict[str, ModelRolePlan]) -> BudgetContract:
    return BudgetContract(
        currency="CNY",
        price_snapshot_id="test-price-snapshot",
        price_observed_at=_NOW - timedelta(minutes=1),
        price_expires_at=_NOW + timedelta(hours=1),
        ceiling=BudgetAmounts(
            input_tokens=10_000,
            output_tokens=5_000,
            cost_minor_units=1_000,
        ),
        role_rates={
            role: RoleRate(
                model_role_identity_hash=model_role_budget_identity_hash(role_plan),
                input_cost_per_million_minor_units=10,
                output_cost_per_million_minor_units=20,
            )
            for role, role_plan in roles.items()
        },
        provider_attestation=ProviderSpendCapAttestation(
            provider="bailian",
            workspace_ref="goldenset-production",
            project_ref="sha256:" + "c" * 64,
            credential_ref="sha256:" + "d" * 64,
            max_cost_minor_units=900,
            observed_at=_NOW - timedelta(minutes=1),
            expires_at=_NOW + timedelta(hours=1),
            evidence_digest="e" * 64,
        ),
        product_reserves=(),
    )


def _signed_document(
    provenance_key: Ed25519PrivateKey,
    budget_key: Ed25519PrivateKey,
    *,
    approval_expires_at: datetime | None = None,
) -> RunAdmissionDocument:
    roles = _roles()
    contract = _contract(roles)
    provenance = ObservedAnnotationProvenance(
        provenance_kind="observed_annotation",
        product_id="product-01",
        annotator_provider="bailian",
        annotator_model_id="historical-annotator",
        annotated_at_start=_NOW - timedelta(days=1),
        annotated_at_end=_NOW - timedelta(hours=23),
        evidence_basis="test provider audit export",
    )
    identity_request = _identity_request((provenance,))
    payload = RunAdmissionPlanPayload(
        run_identity="gs-v0.1-run-001",
        purpose="gs-v0.1-baseline",
        model_roles=roles,
        identity_contract_hash=identity_contract_hash(identity_request),
        budget_contract_hash=budget_contract_hash(contract),
    )
    payload_hash = plan_payload_hash(payload)
    approval_expiry = approval_expires_at or _NOW + timedelta(hours=1)
    provenance_payload = ProvenanceApprovalPayload(
        plan_payload_hash=payload_hash,
        run_identity=payload.run_identity,
        purpose=payload.purpose,
        scope="provenance:wip-gs-v0.1",
        approver_identity="golden-owner@example.com",
        approver_role="provenance_approver",
        issued_at=_NOW - timedelta(minutes=1),
        expires_at=approval_expiry,
        product_entries=(provenance,),
    )
    ceiling = contract.ceiling
    budget_payload = BudgetApprovalPayload(
        plan_payload_hash=payload_hash,
        run_identity=payload.run_identity,
        purpose=payload.purpose,
        scope="budget:gs-v0.1",
        approver_identity="finance-owner@example.com",
        approver_role="budget_approver",
        issued_at=_NOW - timedelta(minutes=1),
        expires_at=approval_expiry,
        budget_entries=(
            BudgetApprovalEntry(
                currency=contract.currency,
                max_input_tokens=ceiling.input_tokens,
                max_output_tokens=ceiling.output_tokens,
                max_cost_minor_units=ceiling.cost_minor_units,
                budget_contract_hash=budget_contract_hash(contract),
            ),
        ),
    )
    provenance_envelope = ProvenanceApprovalEnvelope(
        domain="provenance",
        key_id="provenance-key",
        payload=provenance_payload,
        signature=base64.b64encode(
            provenance_key.sign(
                approval_signed_bytes("provenance", provenance_payload)
            )
        ).decode("ascii"),
    )
    budget_envelope = BudgetApprovalEnvelope(
        domain="budget",
        key_id="budget-key",
        payload=budget_payload,
        signature=base64.b64encode(
            budget_key.sign(approval_signed_bytes("budget", budget_payload))
        ).decode("ascii"),
    )
    return RunAdmissionDocument(
        plan=RunAdmissionPlan(
            payload=payload,
            approval_envelopes=(provenance_envelope, budget_envelope),
        ),
        identity_request=identity_request,
        budget_contract=contract,
    )


def test_d1_4_production_evaluator_ready_requires_all_real_contracts() -> None:
    provenance_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    evaluator = ProductionAdmissionEvaluator._for_testing(
        identity_inspector=_PassingIdentityInspector(),
        provider_probe=_PassingProbe(),
        trusted_public_keys={
            "provenance-key": provenance_key.public_key(),
            "budget-key": budget_key.public_key(),
        },
        probe=True,
        clock=lambda: _NOW,
        runtime_capability_ready=True,
    )

    result = evaluator(_signed_document(provenance_key, budget_key))

    assert result.state == "READY"
    assert not result.blockers
    assert result.evidence is not None
    assert result.evidence.budget is not None
    assert all(approval.verified for approval in result.evidence.approvals)


def test_d1_1b_signed_plan_rejects_replaced_identity_contract() -> None:
    provenance_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    evaluator = ProductionAdmissionEvaluator._for_testing(
        identity_inspector=_PassingIdentityInspector(),
        provider_probe=_PassingProbe(),
        trusted_public_keys={
            "provenance-key": provenance_key.public_key(),
            "budget-key": budget_key.public_key(),
        },
        probe=True,
        clock=lambda: _NOW,
        runtime_capability_ready=True,
    )
    original = _signed_document(provenance_key, budget_key)
    tampered_identity = original.identity_request.model_copy(
        update={"required_dependency_revisions": {"019": "attacker-revision"}}
    )
    tampered = original.model_copy(update={"identity_request": tampered_identity})

    result = evaluator(tampered)

    assert result.state == "BLOCKED"
    assert any(
        blocker.check == "identity" and blocker.code == "identity_contract_mismatch"
        for blocker in result.blockers
    )


def test_d1_1d_final_decision_time_rejects_approval_expiring_mid_check() -> None:
    provenance_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    moments = iter((_NOW, _NOW + timedelta(minutes=20)))
    evaluator = ProductionAdmissionEvaluator._for_testing(
        identity_inspector=_PassingIdentityInspector(),
        provider_probe=_PassingProbe(),
        trusted_public_keys={
            "provenance-key": provenance_key.public_key(),
            "budget-key": budget_key.public_key(),
        },
        probe=True,
        clock=lambda: next(moments),
        runtime_capability_ready=True,
    )
    document = _signed_document(
        provenance_key,
        budget_key,
        approval_expires_at=_NOW + timedelta(minutes=10),
    )

    result = evaluator(document)

    assert result.state == "BLOCKED"
    assert result.evaluated_at == _NOW + timedelta(minutes=20)
    assert any(blocker.code == "observation_expired" for blocker in result.blockers)


def test_d1_3a_budget_check_expiry_includes_signed_envelope_expiry() -> None:
    provenance_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    evaluator = ProductionAdmissionEvaluator._for_testing(
        identity_inspector=_PassingIdentityInspector(),
        provider_probe=_PassingProbe(),
        trusted_public_keys={
            "provenance-key": provenance_key.public_key(),
            "budget-key": budget_key.public_key(),
        },
        probe=True,
        clock=lambda: _NOW,
        runtime_capability_ready=True,
    )
    expiry = _NOW + timedelta(minutes=10)

    result = evaluator(
        _signed_document(
            provenance_key,
            budget_key,
            approval_expires_at=expiry,
        )
    )

    checks = {check.name: check for check in result.checks}
    assert checks["budget_approval"].expires_at == expiry
    assert checks["budget_ledger"].expires_at == expiry
