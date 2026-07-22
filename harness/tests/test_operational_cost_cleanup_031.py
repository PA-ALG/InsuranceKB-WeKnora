from __future__ import annotations

import base64
import copy
import fcntl
import hashlib
import inspect
import json
import os
import pickle
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.goldenset import admission_cli, admission_deployment
from insurance_harness.goldenset.admission_budget import (
    BudgetAmounts,
    BudgetContract,
    BudgetLedger,
    BudgetLedgerError,
    FinalInfrastructureBindingRequest,
    InfrastructureCleanupBinding,
    InfrastructureCreatePermit,
    InfrastructureReserveSnapshot,
    ProviderSpendCapAttestation,
    RoleRate,
    _approval_digest,
    budget_contract_hash,
    derive_role_rate_from_pricing,
    model_role_budget_identity_hash,
    require_verified_final_topology,
    require_verified_topology_provider_capability,
)
from insurance_harness.goldenset.admission_deployment import (
    BAILIAN_DEPLOYMENT_ENDPOINT,
    BailianDeploymentHTTPTransport,
    CleanupDeleteIntent,
    CleanupDeleteIntentSlot,
    CleanupReceipt,
    CleanupTerminalJournal,
    DeploymentControlBlocked,
    DeploymentController,
    DeploymentNotFound,
    DeploymentReceiptArtifact,
    DeploymentReconciliationEvidenceV1,
    DurableDeleteAttemptEvidence,
    ProviderDeploymentManifest,
    deterministic_deployment_suffix,
    deterministic_operation_marker,
    provider_manifest_digest,
    transport_workspace_evidence_digest,
)
from insurance_harness.goldenset.admission_infrastructure import (
    ADOPTION_AUTHORIZATION_DOMAIN,
    CLEANUP_AUTHORIZATION_DOMAIN,
    PRICING_EVIDENCE_DOMAIN,
    PROVIDER_CAP_DOMAIN,
    PROVISIONING_AUTHORIZATION_DOMAIN,
    AuthorizationVerificationError,
    DeploymentCleanupAuthorization,
    DeploymentCleanupAuthorizationPayload,
    DeploymentReceipt,
    DeploymentReceiptContent,
    ExistingDeploymentAdoptionAuthorization,
    ExistingDeploymentAdoptionAuthorizationPayload,
    PricingEvidenceApproval,
    PricingEvidenceApprovalPayload,
    PricingEvidenceContent,
    ProviderCapApproval,
    ProviderCapApprovalPayload,
    ProviderCapEvidenceContent,
    ProvisioningAuthorization,
    ProvisioningAuthorizationPayload,
    VerifiedReconciledDeploymentReceipt,
    _issue_verified_deployment_transport_identity_for_testing,
    _issue_verified_reconciled_receipt_for_testing,
    _require_verified_pricing_capability_for_testing,
    _require_verified_provider_capability_for_testing,
    authorization_signed_bytes,
    cleanup_authorization_digest,
    cleanup_authorization_signed_bytes,
    credential_ref_for_api_key,
    deployment_receipt_content_digest,
    infrastructure_authorization_digest,
    pricing_approval_digest,
    pricing_evidence_digest,
    pricing_evidence_signed_bytes,
    provider_cap_approval_digest,
    provider_cap_evidence_digest,
    provider_cap_signed_bytes,
    require_verified_provider_capability,
    verify_pricing_evidence,
    verify_provider_cap_evidence,
)
from insurance_harness.goldenset.admission_models import (
    BudgetApprovalEntry,
    BudgetApprovalEnvelope,
    BudgetApprovalPayload,
    ModelRolePlan,
    RunAdmissionPlanPayload,
    TrustedKeyPolicy,
    approval_signed_bytes,
    canonical_json_bytes,
    plan_payload_hash,
)
from tests.test_operational_deployment_031 import _production_adoption_case

NOW = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)
SHA_A = "a" * 64
TEST_API_KEY = "test-only-bailian-credential-031"
SHA_B = credential_ref_for_api_key(TEST_API_KEY).removeprefix("sha256:")
OWNERSHIP_NONCE = "e" * 32


def _pricing_content(**updates: Any) -> PricingEvidenceContent:
    values: dict[str, object] = {
        "version": "insurancekb.run-admission.pricing-evidence.v1",
        "issuer": "aliyun-bailian-price-catalog",
        "provider": "bailian",
        "workspace_ref": "workspace-cn-beijing-031",
        "project_ref": "sha256:" + SHA_A,
        "credential_ref": "sha256:" + SHA_B,
        "region": "cn-beijing",
        "base_model": "qwen3.7-plus-2026-05-26",
        "request_plan": "ptu_v2",
        "receipt_plan": "ptu",
        "input_tpm_quota": 10_000,
        "output_tpm_quota": 1_000,
        "currency": "CNY",
        "effective_from": NOW - timedelta(days=1),
        "effective_until": NOW + timedelta(days=1),
        "billing_quantum_seconds": 3600,
        "round_up_rule": "ceiling",
        "fixed_cost_per_quantum_minor_units": 672,
        "input_cost_per_million_minor_units": 240,
        "output_cost_per_million_minor_units": 960,
        "tiers_policy": "worst_case_included",
        "thinking_policy": "worst_case_included",
        "cache_policy": "worst_case_included",
        "overflow_policy": "block",
    }
    values.update(updates)
    return PricingEvidenceContent.model_validate(values)


def _pricing_approval(
    key: Ed25519PrivateKey,
    content: PricingEvidenceContent,
    **updates: Any,
) -> PricingEvidenceApproval:
    evidence = canonical_json_bytes(content)
    values: dict[str, object] = {
        "evidence_digest": pricing_evidence_digest(evidence),
        "evidence": content,
        "scope": "goldenset-production",
        "approver_identity": "pricing-owner@example.test",
        "approver_role": "pricing-evidence-approver",
        "issued_at": NOW - timedelta(minutes=5),
        "expires_at": NOW + timedelta(hours=1),
    }
    values.update(updates)
    payload = PricingEvidenceApprovalPayload.model_validate(values)
    return PricingEvidenceApproval(
        domain=PRICING_EVIDENCE_DOMAIN,
        key_id="pricing-key",
        payload=payload,
        signature=base64.b64encode(key.sign(pricing_evidence_signed_bytes(payload))).decode(
            "ascii"
        ),
    )


def _cap_content(**updates: Any) -> ProviderCapEvidenceContent:
    values: dict[str, object] = {
        "version": "insurancekb.run-admission.provider-cap-evidence.v1",
        "issuer": "aliyun-bailian-spend-cap",
        "provider": "bailian",
        "workspace_ref": "workspace-cn-beijing-031",
        "project_ref": "sha256:" + SHA_A,
        "credential_ref": "sha256:" + SHA_B,
        "currency": "CNY",
        "max_cost_minor_units": 20_000,
        "coverage": ("fixed_infrastructure", "inference"),
        "observed_at": NOW - timedelta(minutes=2),
        "expires_at": NOW + timedelta(hours=1),
    }
    values.update(updates)
    return ProviderCapEvidenceContent.model_validate(values)


def _cap_approval(
    key: Ed25519PrivateKey,
    content: ProviderCapEvidenceContent,
    **updates: Any,
) -> ProviderCapApproval:
    evidence = canonical_json_bytes(content)
    values: dict[str, object] = {
        "evidence_digest": provider_cap_evidence_digest(evidence),
        "evidence": content,
        "scope": "goldenset-production",
        "approver_identity": "cap-attestor@example.test",
        "approver_role": "provider-cap-attestor",
        "issued_at": NOW - timedelta(minutes=5),
        "expires_at": NOW + timedelta(hours=1),
    }
    values.update(updates)
    payload = ProviderCapApprovalPayload.model_validate(values)
    return ProviderCapApproval(
        domain=PROVIDER_CAP_DOMAIN,
        key_id="cap-key",
        payload=payload,
        signature=base64.b64encode(key.sign(provider_cap_signed_bytes(payload))).decode("ascii"),
    )


def _policy(
    key: Ed25519PrivateKey,
    *,
    key_id: str,
    identity: str,
    domain: str,
    role: str,
) -> dict[str, TrustedKeyPolicy]:
    return {
        key_id: TrustedKeyPolicy(
            key_id=key_id,
            approver_identity=identity,
            domains=frozenset({domain}),
            scopes=frozenset({"goldenset-production"}),
            roles=frozenset({role}),
            public_key=key.public_key(),
        )
    }


def _install_production_authorities(
    monkeypatch: pytest.MonkeyPatch,
    authorities: dict[str, TrustedKeyPolicy],
) -> None:
    monkeypatch.setattr(
        "insurance_harness.goldenset.admission_budget._utc_now",
        lambda: NOW,
    )
    monkeypatch.setattr(
        "insurance_harness.goldenset.admission_cli._load_deployment_approval_configuration",
        lambda: (
            authorities,
            frozenset({"budget_approver"}),
            frozenset(),
            frozenset(),
        ),
    )


def _provisioning_authorization(
    key: Ed25519PrivateKey,
    pricing: PricingEvidenceApproval,
    cap: ProviderCapApproval,
    *,
    maximum_cost_minor_units: int = 5_376,
    operation_id: str = "op-strong-031",
    reserve_id: str = "infra-strong-031",
    base_model: str = "qwen3.7-plus-2026-05-26",
) -> tuple[ProvisioningAuthorizationPayload, ProvisioningAuthorization]:
    payload = ProvisioningAuthorizationPayload(
        transition="create",
        provider="bailian",
        run_identity="golden-v01-run-031",
        purpose="golden-v0.1 production run",
        scope="goldenset-production",
        operation_id=operation_id,
        infrastructure_reserve_id=reserve_id,
        workspace_ref="workspace-cn-beijing-031",
        project_ref="sha256:" + SHA_A,
        credential_ref="sha256:" + SHA_B,
        region="cn-beijing",
        base_model=base_model,
        request_plan="ptu_v2",
        receipt_plan="ptu",
        input_tpm_quota=10_000,
        output_tpm_quota=1_000,
        pricing_evidence_digest=pricing.payload.evidence_digest,
        provider_cap_evidence_digest=cap.payload.evidence_digest,
        pricing_approval_digest=pricing_approval_digest(pricing),
        provider_cap_approval_digest=provider_cap_approval_digest(cap),
        currency="CNY",
        provider_cap_max_cost_minor_units=20_000,
        provider_cap_coverage=("fixed_infrastructure", "inference"),
        provider_cap_expires_at=cap.payload.evidence.expires_at,
        maximum_cost_minor_units=maximum_cost_minor_units,
        cleanup_deadline=NOW + timedelta(hours=8),
        approver_identity="deployment-operator@example.test",
        approver_role="deployment-provisioner",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )
    envelope = ProvisioningAuthorization(
        domain=PROVISIONING_AUTHORIZATION_DOMAIN,
        key_id="provisioning-key",
        payload=payload,
        signature=base64.b64encode(
            key.sign(authorization_signed_bytes(PROVISIONING_AUTHORIZATION_DOMAIN, payload))
        ).decode("ascii"),
    )
    return payload, envelope


def _adoption_authorization(
    key: Ed25519PrivateKey,
    pricing: PricingEvidenceApproval,
    cap: ProviderCapApproval,
    receipt: DeploymentReceipt,
    *,
    incurred_cost_minor_units: int = 672,
    future_max_cost_minor_units: int = 5_376,
) -> tuple[
    ExistingDeploymentAdoptionAuthorizationPayload,
    ExistingDeploymentAdoptionAuthorization,
]:
    payload = ExistingDeploymentAdoptionAuthorizationPayload(
        transition="adopt_existing",
        provider="bailian",
        run_identity="golden-v01-run-031",
        purpose="golden-v0.1 production run",
        scope="goldenset-production",
        operation_id=receipt.content.operation_id,
        infrastructure_reserve_id=receipt.content.infrastructure_reserve_id,
        workspace_ref=receipt.content.workspace_ref,
        project_ref=receipt.content.project_ref,
        credential_ref=receipt.content.credential_ref,
        region=receipt.content.region,
        base_model=receipt.content.base_model,
        request_plan=receipt.content.request_plan,
        receipt_plan=receipt.content.receipt_plan,
        input_tpm_quota=receipt.content.input_tpm,
        output_tpm_quota=receipt.content.output_tpm,
        pricing_evidence_digest=pricing.payload.evidence_digest,
        provider_cap_evidence_digest=cap.payload.evidence_digest,
        pricing_approval_digest=pricing_approval_digest(pricing),
        provider_cap_approval_digest=provider_cap_approval_digest(cap),
        currency="CNY",
        provider_cap_max_cost_minor_units=cap.payload.evidence.max_cost_minor_units,
        provider_cap_coverage=cap.payload.evidence.coverage,
        provider_cap_expires_at=cap.payload.evidence.expires_at,
        maximum_cost_minor_units=(incurred_cost_minor_units + future_max_cost_minor_units),
        cleanup_deadline=NOW + timedelta(hours=8),
        approver_identity="budget-owner@example.test",
        approver_role="budget-approver",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
        deployed_model=receipt.content.deployed_model,
        receipt_digest=receipt.content_digest,
        gmt_create=receipt.content.gmt_create,
        preexisting=True,
        limitation="not_preauthorized_by_031",
        incurred_cost_minor_units=incurred_cost_minor_units,
        future_max_cost_minor_units=future_max_cost_minor_units,
    )
    return payload, ExistingDeploymentAdoptionAuthorization(
        domain=ADOPTION_AUTHORIZATION_DOMAIN,
        key_id="adoption-key",
        payload=payload,
        signature=base64.b64encode(
            key.sign(authorization_signed_bytes(ADOPTION_AUTHORIZATION_DOMAIN, payload))
        ).decode("ascii"),
    )


def _manifest(**updates: Any) -> ProviderDeploymentManifest:
    values: dict[str, object] = {
        "deployed_model": "qwen3.7-plus-2026-05-26-031strng",
        "base_model": "qwen3.7-plus-2026-05-26",
        "plan": "ptu",
        "input_tpm": 10_000,
        "output_tpm": 1_000,
        "status": "RUNNING",
        "gmt_create": NOW - timedelta(hours=1),
        "gmt_modified": NOW - timedelta(minutes=2),
        "workspace_ref": "workspace-cn-beijing-031",
        "ownership_nonce": OWNERSHIP_NONCE,
        "operation_marker": deterministic_operation_marker(
            "golden-v01-run-031", "op-strong-031", OWNERSHIP_NONCE
        ),
        "deployment_suffix": deterministic_deployment_suffix(
            "golden-v01-run-031", "op-strong-031", OWNERSHIP_NONCE
        ),
    }
    values.update(updates)
    return ProviderDeploymentManifest.model_validate(values)


def _receipt(
    manifest: ProviderDeploymentManifest | None = None,
    **updates: Any,
) -> DeploymentReceipt:
    bound_manifest = _manifest() if manifest is None else manifest
    transport_identity = _issue_verified_deployment_transport_identity_for_testing(
        workspace_ref="workspace-cn-beijing-031",
        project_ref="sha256:" + SHA_A,
        credential_ref="sha256:" + SHA_B,
        provider_cap_evidence_digest="d" * 64,
        expires_at=NOW + timedelta(hours=24),
    )
    values: dict[str, object] = {
        "operation_id": "op-strong-031",
        "infrastructure_reserve_id": "infra-strong-031",
        "workspace_ref": "workspace-cn-beijing-031",
        "project_ref": "sha256:" + SHA_A,
        "credential_ref": "sha256:" + SHA_B,
        "workspace_evidence_digest": transport_workspace_evidence_digest(transport_identity),
        "region": "cn-beijing",
        "base_model": "qwen3.7-plus-2026-05-26",
        "deployed_model": "qwen3.7-plus-2026-05-26-031strng",
        "request_plan": "ptu_v2",
        "receipt_plan": "ptu",
        "input_tpm": 10_000,
        "output_tpm": 1_000,
        "gmt_create": NOW - timedelta(hours=1),
        "gmt_modified": NOW - timedelta(minutes=2),
        "cleanup_state": "required",
        "operation_marker": bound_manifest.operation_marker,
        "deployment_suffix": bound_manifest.deployment_suffix,
        "remote_manifest_digest": provider_manifest_digest(bound_manifest),
    }
    values.update(updates)
    content = DeploymentReceiptContent.model_validate(values)
    return DeploymentReceipt(
        content=content,
        content_digest=deployment_receipt_content_digest(content),
    )


def _testing_receipt_capability(
    receipt: DeploymentReceipt,
    *,
    cap_digest: str = "d" * 64,
) -> VerifiedReconciledDeploymentReceipt:
    identity = _issue_verified_deployment_transport_identity_for_testing(
        workspace_ref=receipt.content.workspace_ref,
        project_ref=receipt.content.project_ref,
        credential_ref=receipt.content.credential_ref,
        provider_cap_evidence_digest=cap_digest,
        expires_at=NOW + timedelta(hours=1),
    )
    return _issue_verified_reconciled_receipt_for_testing(
        receipt=receipt,
        transport_identity=identity,
        run_identity="golden-v01-run-031",
        purpose="golden-v0.1 production run",
        scope="goldenset-production",
        remote_manifest_digest=receipt.content.remote_manifest_digest,
        observed_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )


def _controller_issued_production_receipt(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ledger_path: Path,
    operation_root: Path,
    plan: RunAdmissionPlanPayload,
    authorization: ProvisioningAuthorization,
    permit: Any,
    manifest: ProviderDeploymentManifest,
) -> tuple[DeploymentReceipt, VerifiedReconciledDeploymentReceipt]:
    operation_root.mkdir(mode=0o700, exist_ok=True)
    monkeypatch.setattr(secrets, "token_hex", lambda size: OWNERSHIP_NONCE)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", TEST_API_KEY)
    monkeypatch.setattr(
        admission_deployment,
        "_PRODUCTION_BUDGET_LEDGER_PATH",
        ledger_path,
    )
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", operation_root)
    controller = DeploymentController.for_production(
        plan=plan,
        expected_scope=authorization.payload.scope,
        reserve_id=permit.reserve.reserve_id,
    )
    controller._clock = lambda: NOW
    transport = controller._transport
    assert type(transport) is BailianDeploymentHTTPTransport

    def list_deployments(*, marker: str, suffix: str) -> bytes:
        assert marker == manifest.operation_marker
        assert suffix == manifest.deployment_suffix
        return canonical_json_bytes({"items": ()})

    def deployment_detail(*, deployed_model: str) -> bytes:
        assert deployed_model == manifest.deployed_model
        return canonical_json_bytes(manifest)

    def create_deployment(*, request_body: bytes, idempotency_key: str) -> bytes:
        request = json.loads(request_body)
        assert request["operation_marker"] == manifest.operation_marker
        assert request["deployment_suffix"] == manifest.deployment_suffix
        assert idempotency_key
        return canonical_json_bytes(manifest)

    monkeypatch.setattr(transport, "list_deployments", list_deployments)
    monkeypatch.setattr(transport, "deployment_detail", deployment_detail)
    monkeypatch.setattr(transport, "create_deployment", create_deployment)
    try:
        result = controller.provision(authorization=authorization, permit=permit)
    finally:
        controller.close()
    monkeypatch.setattr(
        "insurance_harness.goldenset.admission_budget._PRODUCTION_DEPLOYMENT_OPERATION_ROOT",
        operation_root,
        raising=False,
    )
    return result.receipt, result.receipt_capability


def test_o7_t9_19_c4_production_cleanup_exposes_canonical_factory_and_api() -> None:
    factory = getattr(DeploymentController, "for_production_cleanup", None)
    cleanup = getattr(DeploymentController, "cleanup", None)

    assert callable(factory)
    assert callable(cleanup)


def test_o7_t9_19_c4_production_cleanup_factory_owns_ledger_transport_and_clock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _receipt()
    binding = InfrastructureCleanupBinding(
        reserve_id=receipt.content.infrastructure_reserve_id,
        run_identity="golden-v01-run-031",
        purpose="golden-v0.1 production run",
        scope="goldenset-production",
        operation_id=receipt.content.operation_id,
        workspace_ref=receipt.content.workspace_ref,
        project_ref=receipt.content.project_ref,
        credential_ref=receipt.content.credential_ref,
        receipt_digest=receipt.content_digest,
        deployed_model=receipt.content.deployed_model,
        remote_manifest_digest=receipt.content.remote_manifest_digest,
        reconciliation_digest="1" * 64,
        transport_identity_digest="2" * 64,
        cleanup_deadline=NOW + timedelta(hours=8),
    )
    root = tmp_path / "deployment-control"
    root.mkdir(mode=0o700)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", TEST_API_KEY)
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", root)
    monkeypatch.setattr(
        admission_deployment,
        "_PRODUCTION_BUDGET_LEDGER_PATH",
        tmp_path / "budget.sqlite3",
    )
    monkeypatch.setattr(
        BudgetLedger,
        "infrastructure_cleanup_binding",
        lambda _ledger, reserve_id: binding
        if reserve_id == binding.reserve_id
        else (_ for _ in ()).throw(BudgetLedgerError("not found")),
    )

    controller = DeploymentController.for_production_cleanup(
        reserve_id=binding.reserve_id
    )
    try:
        assert controller._cleanup_reserve_reader.infrastructure_cleanup_binding(
            binding.reserve_id
        ) == binding
        assert controller._transport.endpoint == admission_deployment.BAILIAN_DEPLOYMENT_ENDPOINT
        assert set(inspect.signature(controller.cleanup).parameters) == {
            "authorization",
            "receipt_digest",
        }
    finally:
        controller.close()


def _c4_cleanup_binding(
    receipt: DeploymentReceipt,
    capability: VerifiedReconciledDeploymentReceipt,
) -> InfrastructureCleanupBinding:
    return InfrastructureCleanupBinding(
        reserve_id=receipt.content.infrastructure_reserve_id,
        run_identity=capability.run_identity,
        purpose=capability.purpose,
        scope=capability.scope,
        operation_id=receipt.content.operation_id,
        workspace_ref=receipt.content.workspace_ref,
        project_ref=receipt.content.project_ref,
        credential_ref=receipt.content.credential_ref,
        receipt_digest=receipt.content_digest,
        deployed_model=receipt.content.deployed_model,
        remote_manifest_digest=receipt.content.remote_manifest_digest,
        reconciliation_digest=capability.reconciliation_digest,
        transport_identity_digest=capability.transport_identity_digest,
        cleanup_deadline=NOW + timedelta(hours=8),
    )


def _c4_cleanup_authorization(
    key: Ed25519PrivateKey,
    binding: InfrastructureCleanupBinding,
    **updates: object,
) -> DeploymentCleanupAuthorization:
    values: dict[str, object] = {
        "run_identity": binding.run_identity,
        "purpose": binding.purpose,
        "scope": binding.scope,
        "operation_id": binding.operation_id,
        "reserve_id": binding.reserve_id,
        "receipt_digest": binding.receipt_digest,
        "deployed_model": binding.deployed_model,
        "workspace_ref": binding.workspace_ref,
        "project_ref": binding.project_ref,
        "credential_ref": binding.credential_ref,
        "expected_remote_manifest_digest": binding.remote_manifest_digest,
        "cleanup_reason": "T9.19 controlled cleanup",
        "cleanup_deadline": binding.cleanup_deadline,
        "approver_identity": "cleanup-operator@example.test",
        "approver_role": "deployment-cleanup-operator",
        "issued_at": NOW - timedelta(minutes=1),
        "expires_at": NOW + timedelta(minutes=30),
    }
    values.update(updates)
    payload = DeploymentCleanupAuthorizationPayload.model_validate(values)
    return DeploymentCleanupAuthorization(
        domain=CLEANUP_AUTHORIZATION_DOMAIN,
        key_id="cleanup-key",
        payload=payload,
        signature=base64.b64encode(
            key.sign(cleanup_authorization_signed_bytes(payload))
        ).decode("ascii"),
    )


def _c4_cleanup_resource_prefix(binding: InfrastructureCleanupBinding) -> str:
    return hashlib.sha256(
        b"insurancekb.run-admission.cleanup-resource.v1\0"
        + canonical_json_bytes(binding)
    ).hexdigest()


class _C4CleanupReader:
    def __init__(self, binding: InfrastructureCleanupBinding) -> None:
        self.binding = binding

    def infrastructure_cleanup_binding(
        self,
        reserve_id: str,
    ) -> InfrastructureCleanupBinding:
        if reserve_id != self.binding.reserve_id:
            raise BudgetLedgerError("cleanup binding not found")
        return self.binding

    def infrastructure_reserve(self, reserve_id: str) -> InfrastructureReserveSnapshot:
        raise AssertionError("cleanup must not read mutable reserve state")


class _C4CleanupTransport:
    endpoint = BAILIAN_DEPLOYMENT_ENDPOINT

    def __init__(self, manifest: ProviderDeploymentManifest) -> None:
        self.manifest: ProviderDeploymentManifest | None = manifest
        self.identity = _issue_verified_deployment_transport_identity_for_testing(
            workspace_ref=manifest.workspace_ref,
            project_ref="sha256:" + SHA_A,
            credential_ref="sha256:" + SHA_B,
            provider_cap_evidence_digest="d" * 64,
            provider_cap_approval_digest="f" * 64,
            expires_at=NOW + timedelta(hours=24),
        )
        self.detail_calls = 0
        self.delete_calls = 0
        self.mode = "ok"

    def deployment_detail(self, *, deployed_model: str) -> bytes:
        self.detail_calls += 1
        if self.manifest is None:
            raise DeploymentNotFound("absent")
        return canonical_json_bytes(self.manifest)

    def delete_deployment(self, *, deployed_model: str) -> bytes:
        self.delete_calls += 1
        if self.mode == "timeout_without_accept":
            raise TimeoutError("ambiguous")
        self.manifest = None
        if self.mode == "timeout_after_accept":
            raise TimeoutError("response lost")
        return b"{}"

    def list_deployments(self, *, marker: str, suffix: str) -> bytes:
        raise AssertionError("cleanup must not list")

    def create_deployment(self, *, request_body: bytes, idempotency_key: str) -> bytes:
        raise AssertionError("cleanup must not create")


def _c4_cleanup_controller(
    tmp_path: Path,
    receipt: DeploymentReceipt,
    manifest: ProviderDeploymentManifest,
    transport: _C4CleanupTransport,
    *,
    clock: Any = None,
) -> tuple[DeploymentController, InfrastructureCleanupBinding]:
    root = tmp_path / "deployment-control"
    root.mkdir(mode=0o700)
    capability = _testing_receipt_capability(receipt)
    binding = _c4_cleanup_binding(receipt, capability)
    receipt_artifact = DeploymentReceiptArtifact(
        receipt=receipt,
        remote_manifest=manifest,
        remote_manifest_digest=provider_manifest_digest(manifest),
    )
    reconciliation = DeploymentReconciliationEvidenceV1(
        version="insurancekb.run-admission.deployment-reconciliation-evidence.v1",
        issuer="bailian-deployment-controller-v1",
        transport_identity_digest=capability.transport_identity_digest,
        run_identity=capability.run_identity,
        purpose=capability.purpose,
        scope=capability.scope,
        receipt=receipt,
        remote_manifest=manifest,
        receipt_digest=receipt.content_digest,
        operation_id=receipt.content.operation_id,
        reserve_id=receipt.content.infrastructure_reserve_id,
        workspace_ref=receipt.content.workspace_ref,
        project_ref=receipt.content.project_ref,
        credential_ref=receipt.content.credential_ref,
        provider_cap_evidence_digest=capability.provider_cap_evidence_digest,
        provider_cap_approval_digest=capability.provider_cap_approval_digest,
        remote_manifest_digest=receipt.content.remote_manifest_digest,
        observed_at=capability.observed_at,
        expires_at=capability.expires_at,
        reconciliation_digest=capability.reconciliation_digest,
    )
    receipt_path = root / f"{receipt.content_digest}.receipt.json"
    receipt_path.write_bytes(canonical_json_bytes(receipt_artifact))
    receipt_path.chmod(0o600)
    reconciliation_path = root / (
        f"{capability.reconciliation_digest}.receipt-reconciliation.json"
    )
    reconciliation_path.write_bytes(canonical_json_bytes(reconciliation))
    reconciliation_path.chmod(0o600)
    controller = DeploymentController._for_testing(
        run_root=root,
        reserve_reader=_C4CleanupReader(binding),
        transport=transport,
        clock=(lambda: NOW) if clock is None else clock,
    )
    return controller, binding


def test_o7_t9_19_c4_verified_running_ptu_uses_direct_delete_and_terminal_404(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
    )
    authorization = _c4_cleanup_authorization(key, binding)

    try:
        result = controller._cleanup_for_testing(
            authorization=authorization,
            trusted_authorities=_policy(
                key,
                key_id="cleanup-key",
                identity="cleanup-operator@example.test",
                domain=CLEANUP_AUTHORIZATION_DOMAIN,
                role="deployment-cleanup-operator",
            ),
            receipt_digest=receipt.content_digest,
        )
    finally:
        controller.close()

    assert result.receipt.billing_stop_verified is True
    assert result.receipt.terminal_state == "absent_404"
    assert result.receipt.causal_delete_attempt_digest is not None
    assert (transport.detail_calls, transport.delete_calls) == (2, 1)


@pytest.mark.parametrize("attempt_drift", ["missing", "replaced", "symlink"])
def test_o7_t9_19_c4_second_get_reloads_paired_attempt_before_causal_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attempt_drift: str,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
    )
    original_detail = transport.deployment_detail

    def drift_attempt_before_second_404(*, deployed_model: str) -> bytes:
        if transport.detail_calls == 1 and transport.manifest is None:
            attempt = next(
                controller._store.root.glob("*.cleanup-delete-attempt.slot")
            )
            attempt.unlink()
            if attempt_drift == "replaced":
                attempt.write_bytes(b"{}")
                attempt.chmod(0o600)
            elif attempt_drift == "symlink":
                attempt.symlink_to(
                    controller._store.root
                    / f"{binding.receipt_digest}.receipt.json"
                )
        return original_detail(deployed_model=deployed_model)

    monkeypatch.setattr(
        transport,
        "deployment_detail",
        drift_attempt_before_second_404,
    )
    try:
        with pytest.raises(DeploymentControlBlocked) as blocked:
            controller._cleanup_for_testing(
                authorization=_c4_cleanup_authorization(key, binding),
                trusted_authorities=_policy(
                    key,
                    key_id="cleanup-key",
                    identity="cleanup-operator@example.test",
                    domain=CLEANUP_AUTHORIZATION_DOMAIN,
                    role="deployment-cleanup-operator",
                ),
                receipt_digest=binding.receipt_digest,
            )
    finally:
        controller.close()

    assert blocked.value.code in {
        "cleanup_attempt_invalid",
        "operation_artifact_unsafe",
    }
    assert transport.delete_calls == 1
    root = tmp_path / "deployment-control"
    assert not tuple(root.glob("*.cleanup-terminal-journal.json"))
    assert not tuple(root.glob("*.cleanup-receipt.json"))


def test_o7_t9_19_c4_terminal_journal_succeeds_as_durable_attempt_successor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
    )
    authorization = _c4_cleanup_authorization(key, binding)
    authorities = _policy(
        key,
        key_id="cleanup-key",
        identity="cleanup-operator@example.test",
        domain=CLEANUP_AUTHORIZATION_DOMAIN,
        role="deployment-cleanup-operator",
    )
    original_publish = controller._publish_cleanup_terminal

    def remove_slots_after_fresh_reload(**kwargs: Any) -> Any:
        assert kwargs["verified_attempt"] is not None
        for pattern in (
            "*.cleanup-delete-intent.slot",
            "*.cleanup-delete-attempt.slot",
        ):
            for path in controller._store.root.glob(pattern):
                path.unlink()
        return original_publish(**kwargs)

    monkeypatch.setattr(
        controller,
        "_publish_cleanup_terminal",
        remove_slots_after_fresh_reload,
    )
    first = controller._cleanup_for_testing(
        authorization=authorization,
        trusted_authorities=authorities,
        receipt_digest=binding.receipt_digest,
    )
    root = controller._store.root
    controller.close()

    assert first.receipt.terminal_state == "absent_404"
    assert first.receipt.causal_delete_attempt_digest is not None
    assert not tuple(root.glob("*.cleanup-delete-intent.slot"))
    assert not tuple(root.glob("*.cleanup-delete-attempt.slot"))
    assert first.journal_path is not None
    journal = CleanupTerminalJournal.model_validate_json(
        first.journal_path.read_bytes()
    )
    assert journal.causal_intent_snapshot is not None
    assert journal.causal_attempt_snapshot is not None

    replay_transport = _C4CleanupTransport(manifest)
    replay_transport.manifest = None
    restarted = DeploymentController._for_testing(
        run_root=root,
        reserve_reader=_C4CleanupReader(binding),
        transport=replay_transport,
        clock=lambda: NOW,
    )
    try:
        replay = restarted._cleanup_for_testing(
            authorization=authorization,
            trusted_authorities=authorities,
            receipt_digest=binding.receipt_digest,
        )
    finally:
        restarted.close()

    assert replay == first
    assert (replay_transport.detail_calls, replay_transport.delete_calls) == (0, 0)


@pytest.mark.parametrize(
    "forgery",
    ["intent_copy", "attempt_copy", "construct", "raw_tamper"],
)
def test_o7_t9_19_c4_embedded_terminal_successor_forgery_fails_closed(
    tmp_path: Path,
    forgery: str,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
    )
    authorization = _c4_cleanup_authorization(key, binding)
    authorities = _policy(
        key,
        key_id="cleanup-key",
        identity="cleanup-operator@example.test",
        domain=CLEANUP_AUTHORIZATION_DOMAIN,
        role="deployment-cleanup-operator",
    )
    first = controller._cleanup_for_testing(
        authorization=authorization,
        trusted_authorities=authorities,
        receipt_digest=binding.receipt_digest,
    )
    assert first.journal_path is not None
    journal = CleanupTerminalJournal.model_validate_json(
        first.journal_path.read_bytes()
    )
    assert journal.causal_intent_snapshot is not None
    assert journal.causal_attempt_snapshot is not None
    if forgery == "intent_copy":
        forged_intent = journal.causal_intent_snapshot.model_copy(deep=True)
        object.__setattr__(forged_intent, "intent_digest", "0" * 64)
        forged = journal.model_copy(deep=True)
        object.__setattr__(forged, "causal_intent_snapshot", forged_intent)
        forged_bytes = canonical_json_bytes(forged)
    elif forgery == "attempt_copy":
        forged_attempt = journal.causal_attempt_snapshot.model_copy(deep=True)
        object.__setattr__(forged_attempt, "attempt_proof", "0" * 64)
        forged = journal.model_copy(deep=True)
        object.__setattr__(forged, "causal_attempt_snapshot", forged_attempt)
        forged_bytes = canonical_json_bytes(forged)
    elif forgery == "construct":
        forged = CleanupTerminalJournal.model_construct(
            version=journal.version,
            binding=journal.binding,
            receipt=journal.receipt,
            receipt_digest=journal.receipt_digest,
            causal_intent_snapshot=None,
            causal_attempt_snapshot=None,
        )
        forged_bytes = canonical_json_bytes(forged)
    else:
        raw_values = json.loads(first.journal_path.read_bytes())
        raw_values["causal_attempt_snapshot"]["attempted_at"] = (
            NOW + timedelta(seconds=1)
        ).isoformat()
        forged_bytes = json.dumps(
            raw_values,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    first.journal_path.write_bytes(forged_bytes)
    for pattern in (
        "*.cleanup-delete-intent.slot",
        "*.cleanup-delete-attempt.slot",
    ):
        for path in controller._store.root.glob(pattern):
            path.unlink()
    root = controller._store.root
    controller.close()

    replay_transport = _C4CleanupTransport(manifest)
    replay_transport.manifest = None
    restarted = DeploymentController._for_testing(
        run_root=root,
        reserve_reader=_C4CleanupReader(binding),
        transport=replay_transport,
        clock=lambda: NOW,
    )
    try:
        with pytest.raises(DeploymentControlBlocked) as blocked:
            restarted._cleanup_for_testing(
                authorization=authorization,
                trusted_authorities=authorities,
                receipt_digest=binding.receipt_digest,
            )
    finally:
        restarted.close()

    assert blocked.value.code == "cleanup_receipt_invalid"
    assert (replay_transport.detail_calls, replay_transport.delete_calls) == (0, 0)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("run_identity", "foreign-run"),
        ("purpose", "foreign-purpose"),
        ("scope", "foreign-scope"),
        ("operation_id", "foreign-operation"),
        ("reserve_id", "foreign-reserve"),
        ("receipt_digest", "1" * 64),
        ("deployed_model", "foreign-deployment"),
        ("credential_ref", "sha256:" + "2" * 64),
        ("expected_remote_manifest_digest", "3" * 64),
    ],
)
def test_o7_t9_19_c4_cross_resource_cleanup_replay_has_zero_provider_io(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
    )
    authorization = _c4_cleanup_authorization(
        key,
        binding,
        **{field: replacement},
    )

    try:
        with pytest.raises(DeploymentControlBlocked) as blocked:
            controller._cleanup_for_testing(
                authorization=authorization,
                trusted_authorities=_policy(
                    key,
                    key_id="cleanup-key",
                    identity="cleanup-operator@example.test",
                    domain=CLEANUP_AUTHORIZATION_DOMAIN,
                    role="deployment-cleanup-operator",
                ),
                receipt_digest=receipt.content_digest,
            )
    finally:
        controller.close()

    assert blocked.value.code == "cleanup_authorization_invalid"
    assert (transport.detail_calls, transport.delete_calls) == (0, 0)


def test_o7_t9_19_c4_actual_os_lock_queue_expiry_has_zero_provider_io(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    expired = threading.Event()
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
        clock=lambda: NOW + timedelta(minutes=2) if expired.is_set() else NOW,
    )
    authorization = _c4_cleanup_authorization(
        key,
        binding,
        issued_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=1),
    )
    lock_path = controller._store.path(
        controller._store.lock_name(binding.run_identity)
    )
    descriptor = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
    )
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    failures: list[BaseException] = []

    def cleanup() -> None:
        try:
            controller._cleanup_for_testing(
                authorization=authorization,
                trusted_authorities=_policy(
                    key,
                    key_id="cleanup-key",
                    identity="cleanup-operator@example.test",
                    domain=CLEANUP_AUTHORIZATION_DOMAIN,
                    role="deployment-cleanup-operator",
                ),
                receipt_digest=receipt.content_digest,
            )
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=cleanup)
    thread.start()
    time.sleep(0.1)
    assert thread.is_alive()
    expired.set()
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)
    thread.join(timeout=5)
    controller.close()

    assert len(failures) == 1
    assert isinstance(failures[0], DeploymentControlBlocked)
    assert failures[0].code == "cleanup_authorization_invalid"
    assert (transport.detail_calls, transport.delete_calls) == (0, 0)


def test_o7_t9_19_c4_missing_reconciliation_artifact_blocks_before_provider_io(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
    )
    reconciliation_path = controller._store.path(
        f"{binding.reconciliation_digest}.receipt-reconciliation.json"
    )
    reconciliation_path.unlink()
    authorization = _c4_cleanup_authorization(key, binding)

    try:
        with pytest.raises(DeploymentControlBlocked) as blocked:
            controller._cleanup_for_testing(
                authorization=authorization,
                trusted_authorities=_policy(
                    key,
                    key_id="cleanup-key",
                    identity="cleanup-operator@example.test",
                    domain=CLEANUP_AUTHORIZATION_DOMAIN,
                    role="deployment-cleanup-operator",
                ),
                receipt_digest=receipt.content_digest,
            )
    finally:
        controller.close()

    assert blocked.value.code == "cleanup_authorization_invalid"
    assert (transport.detail_calls, transport.delete_calls) == (0, 0)


@pytest.mark.parametrize("same_resource", [False, True])
def test_o7_t9_19_c4_intent_limit_is_scoped_to_exact_cleanup_resource(
    tmp_path: Path,
    same_resource: bool,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
    )
    counted_binding = (
        binding
        if same_resource
        else binding.model_copy(update={"reserve_id": "foreign-reserve"})
    )
    if same_resource:
        occupied_authorization = _c4_cleanup_authorization(
            key,
            binding,
            issued_at=NOW - timedelta(minutes=2),
            expires_at=NOW + timedelta(minutes=20),
        )
        occupied_intent = CleanupDeleteIntent(
            binding=binding,
            authorization=occupied_authorization,
            authorization_digest=cleanup_authorization_digest(
                occupied_authorization
            ),
            authorization_issued_at=occupied_authorization.payload.issued_at,
        )
        occupied_digest = hashlib.sha256(
            b"insurancekb.run-admission.cleanup-delete-intent.v1\0"
            + canonical_json_bytes(occupied_intent)
        ).hexdigest()
        occupied_bytes = canonical_json_bytes(
            CleanupDeleteIntentSlot(
                intent=occupied_intent,
                intent_digest=occupied_digest,
            )
        )
    else:
        occupied_bytes = b"{}"
    prefix = _c4_cleanup_resource_prefix(counted_binding)
    for ordinal in range(64):
        path = controller._store.path(
            f"{prefix}.{ordinal:02d}.cleanup-delete-intent.slot"
        )
        path.write_bytes(occupied_bytes)
        path.chmod(0o600)
    authorization = _c4_cleanup_authorization(key, binding)
    authorities = _policy(
        key,
        key_id="cleanup-key",
        identity="cleanup-operator@example.test",
        domain=CLEANUP_AUTHORIZATION_DOMAIN,
        role="deployment-cleanup-operator",
    )
    try:
        if same_resource:
            with pytest.raises(DeploymentControlBlocked) as blocked:
                controller._cleanup_for_testing(
                    authorization=authorization,
                    trusted_authorities=authorities,
                    receipt_digest=binding.receipt_digest,
                )
            assert blocked.value.code == "cleanup_journal_limit_exceeded"
            assert (transport.detail_calls, transport.delete_calls) == (0, 0)
        else:
            result = controller._cleanup_for_testing(
                authorization=authorization,
                trusted_authorities=authorities,
                receipt_digest=binding.receipt_digest,
            )
            assert result.receipt.billing_stop_verified is True
            assert (transport.detail_calls, transport.delete_calls) == (2, 1)
    finally:
        controller.close()


def test_o7_t9_19_c4_cleanup_reads_only_fixed_resource_slots_with_many_foreign_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
    )
    root = controller._store.root
    for ordinal in range(1_000):
        foreign = root / f"foreign-{ordinal:04d}.artifact"
        foreign.write_bytes(b"foreign")
        foreign.chmod(0o600)
    slot_reads = 0
    original_read = controller._store.read

    def count_slot_reads(name: str) -> bytes | None:
        nonlocal slot_reads
        if name.endswith(".cleanup-delete-intent.slot"):
            slot_reads += 1
        return original_read(name)

    def forbid_directory_scan(*args: Any, **kwargs: Any) -> tuple[str, ...]:
        raise AssertionError("cleanup must not enumerate the operation-store directory")

    reads_before_first_get: list[int] = []
    original_detail = transport.deployment_detail

    def detail(*, deployed_model: str) -> bytes:
        reads_before_first_get.append(slot_reads)
        return original_detail(deployed_model=deployed_model)

    monkeypatch.setattr(controller._store, "read", count_slot_reads)
    monkeypatch.setattr(controller._store, "names_with_suffix", forbid_directory_scan)
    monkeypatch.setattr(
        controller._store,
        "names_with_prefix_and_suffix",
        forbid_directory_scan,
    )
    monkeypatch.setattr(transport, "deployment_detail", detail)
    try:
        result = controller._cleanup_for_testing(
            authorization=_c4_cleanup_authorization(key, binding),
            trusted_authorities=_policy(
                key,
                key_id="cleanup-key",
                identity="cleanup-operator@example.test",
                domain=CLEANUP_AUTHORIZATION_DOMAIN,
                role="deployment-cleanup-operator",
            ),
            receipt_digest=binding.receipt_digest,
        )
    finally:
        controller.close()

    assert result.receipt.billing_stop_verified is True
    assert reads_before_first_get[0] == 64
    assert (transport.detail_calls, transport.delete_calls) == (2, 1)


@pytest.mark.parametrize(
    "timeout_mode",
    ["timeout_without_accept", "timeout_after_accept"],
)
def test_o7_t9_19_c4_delete_timeout_remains_noncausal_after_external_absence(
    tmp_path: Path,
    timeout_mode: str,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    now = {"value": NOW}
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
        clock=lambda: now["value"],
    )
    authorities = _policy(
        key,
        key_id="cleanup-key",
        identity="cleanup-operator@example.test",
        domain=CLEANUP_AUTHORIZATION_DOMAIN,
        role="deployment-cleanup-operator",
    )
    first = _c4_cleanup_authorization(
        key,
        binding,
        issued_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=1),
    )
    transport.mode = timeout_mode

    first_result: Any = None
    try:
        first_result = controller._cleanup_for_testing(
            authorization=first,
            trusted_authorities=authorities,
            receipt_digest=receipt.content_digest,
        )
    except DeploymentControlBlocked as ambiguous:
        assert timeout_mode == "timeout_without_accept"
        assert ambiguous.code == "billing_stop_unverified"
    assert transport.delete_calls == 1
    if timeout_mode == "timeout_after_accept":
        controller.close()
        assert first_result.receipt.terminal_state == "already_absent_404"
        assert first_result.receipt.causal_delete_attempt_digest is None
        return

    now["value"] = NOW + timedelta(minutes=2)
    transport.manifest = None
    transport.mode = "ok"
    replacement = _c4_cleanup_authorization(
        key,
        binding,
        issued_at=now["value"] - timedelta(seconds=1),
        expires_at=now["value"] + timedelta(minutes=30),
    )
    try:
        result = controller._cleanup_for_testing(
            authorization=replacement,
            trusted_authorities=authorities,
            receipt_digest=receipt.content_digest,
        )
    finally:
        controller.close()

    assert result.receipt.terminal_state == "already_absent_404"
    assert result.receipt.causal_delete_attempt_digest is None
    assert transport.delete_calls == 1


def test_o7_t9_19_c4_pre_send_intent_never_proves_causal_delete_after_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
    )
    authorities = _policy(
        key,
        key_id="cleanup-key",
        identity="cleanup-operator@example.test",
        domain=CLEANUP_AUTHORIZATION_DOMAIN,
        role="deployment-cleanup-operator",
    )
    first = _c4_cleanup_authorization(key, binding)
    original_gate = controller._verify_cleanup_gate
    gate_calls = 0

    def crash_after_intent_before_delete(**kwargs: Any) -> Any:
        nonlocal gate_calls
        gate_calls += 1
        if gate_calls == 5:
            raise SystemExit("simulated crash after intent before DELETE invocation")
        return original_gate(**kwargs)

    monkeypatch.setattr(
        controller,
        "_verify_cleanup_gate",
        crash_after_intent_before_delete,
    )
    with pytest.raises(SystemExit):
        controller._cleanup_for_testing(
            authorization=first,
            trusted_authorities=authorities,
            receipt_digest=binding.receipt_digest,
        )
    root = controller._store.root
    controller.close()
    assert transport.delete_calls == 0
    assert len(tuple(root.glob("*.cleanup-delete-intent.slot"))) == 1

    transport.manifest = None
    restarted = DeploymentController._for_testing(
        run_root=root,
        reserve_reader=_C4CleanupReader(binding),
        transport=transport,
        clock=lambda: NOW + timedelta(minutes=2),
    )
    replacement = _c4_cleanup_authorization(
        key,
        binding,
        issued_at=NOW + timedelta(minutes=2) - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=32),
    )
    try:
        recovered = restarted._cleanup_for_testing(
            authorization=replacement,
            trusted_authorities=authorities,
            receipt_digest=binding.receipt_digest,
        )
    finally:
        restarted.close()

    assert recovered.receipt.terminal_state == "already_absent_404"
    assert recovered.receipt.causal_delete_attempt_digest is None
    assert transport.delete_calls == 0


def test_o7_t9_19_c4_first_observation_404_is_noncausal_and_never_deletes(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    transport.manifest = None
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
    )
    authorization = _c4_cleanup_authorization(key, binding)
    try:
        result = controller._cleanup_for_testing(
            authorization=authorization,
            trusted_authorities=_policy(
                key,
                key_id="cleanup-key",
                identity="cleanup-operator@example.test",
                domain=CLEANUP_AUTHORIZATION_DOMAIN,
                role="deployment-cleanup-operator",
            ),
            receipt_digest=receipt.content_digest,
        )
    finally:
        controller.close()

    assert result.receipt.terminal_state == "already_absent_404"
    assert result.receipt.causal_delete_attempt_digest is None
    assert (transport.detail_calls, transport.delete_calls) == (1, 0)


def test_o7_t9_19_c4_same_ambiguous_authority_never_retries_but_new_authority_can_delete(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    now = {"value": NOW}
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
        clock=lambda: now["value"],
    )
    authorities = _policy(
        key,
        key_id="cleanup-key",
        identity="cleanup-operator@example.test",
        domain=CLEANUP_AUTHORIZATION_DOMAIN,
        role="deployment-cleanup-operator",
    )
    first = _c4_cleanup_authorization(
        key,
        binding,
        issued_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=1),
    )
    transport.mode = "timeout_without_accept"
    with pytest.raises(DeploymentControlBlocked):
        controller._cleanup_for_testing(
            authorization=first,
            trusted_authorities=authorities,
            receipt_digest=receipt.content_digest,
        )
    with pytest.raises(DeploymentControlBlocked):
        controller._cleanup_for_testing(
            authorization=first,
            trusted_authorities=authorities,
            receipt_digest=receipt.content_digest,
        )
    assert transport.delete_calls == 1

    now["value"] = NOW + timedelta(minutes=2)
    transport.mode = "ok"
    replacement = _c4_cleanup_authorization(
        key,
        binding,
        issued_at=now["value"] - timedelta(seconds=1),
        expires_at=now["value"] + timedelta(minutes=30),
    )
    try:
        result = controller._cleanup_for_testing(
            authorization=replacement,
            trusted_authorities=authorities,
            receipt_digest=receipt.content_digest,
        )
    finally:
        controller.close()
    assert result.receipt.terminal_state == "absent_404"
    assert result.receipt.causal_delete_attempt_digest is not None
    assert transport.delete_calls == 2


def test_o7_t9_19_c4_exact_replay_is_zero_io_and_foreign_terminal_receipt_fails_closed(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
    )
    authorities = _policy(
        key,
        key_id="cleanup-key",
        identity="cleanup-operator@example.test",
        domain=CLEANUP_AUTHORIZATION_DOMAIN,
        role="deployment-cleanup-operator",
    )
    authorization = _c4_cleanup_authorization(key, binding)
    first = controller._cleanup_for_testing(
        authorization=authorization,
        trusted_authorities=authorities,
        receipt_digest=receipt.content_digest,
    )
    calls = (transport.detail_calls, transport.delete_calls)
    replay = controller._cleanup_for_testing(
        authorization=authorization,
        trusted_authorities=authorities,
        receipt_digest=receipt.content_digest,
    )
    assert replay == first
    assert (transport.detail_calls, transport.delete_calls) == calls

    assert first.journal_path is not None
    original_journal = first.journal_path.read_bytes()
    copied_receipt = first.receipt.model_copy(
        update={"observed_at": first.receipt.observed_at + timedelta(seconds=1)}
    )
    copied_receipt_bytes = canonical_json_bytes(copied_receipt)
    forged_journal = CleanupTerminalJournal.model_construct(
        binding=binding,
        receipt=copied_receipt,
        receipt_digest=hashlib.sha256(
            b"insurancekb.run-admission.cleanup-receipt.v1\0"
            + copied_receipt_bytes
        ).hexdigest(),
    )
    first.journal_path.write_bytes(canonical_json_bytes(forged_journal))
    with pytest.raises(DeploymentControlBlocked) as copied:
        controller._cleanup_for_testing(
            authorization=authorization,
            trusted_authorities=authorities,
            receipt_digest=receipt.content_digest,
        )
    assert copied.value.code == "cleanup_receipt_invalid"
    assert (transport.detail_calls, transport.delete_calls) == calls
    first.journal_path.write_bytes(original_journal)

    first.receipt_path.write_bytes(b"{}\n")
    with pytest.raises(DeploymentControlBlocked) as blocked:
        controller._cleanup_for_testing(
            authorization=authorization,
            trusted_authorities=authorities,
            receipt_digest=receipt.content_digest,
        )
    controller.close()
    assert blocked.value.code == "cleanup_receipt_invalid"
    assert (transport.detail_calls, transport.delete_calls) == calls


def test_o7_t9_19_c4_forged_terminal_journal_cannot_assert_billing_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    seed_transport = _C4CleanupTransport(manifest)
    seed_controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        seed_transport,
    )
    authorization = _c4_cleanup_authorization(key, binding)
    forged_receipt_values: dict[str, object] = {
        "binding": binding,
        "cleanup_authorization_digest": cleanup_authorization_digest(authorization),
        "causal_delete_attempt_digest": None,
        "terminal_state": "already_absent_404",
        "observed_at": NOW,
    }
    if "observation_proof" in CleanupReceipt.model_fields:
        forged_receipt_values["cleanup_transport_identity_digest"] = "0" * 64
        forged_receipt_values["observation_proof"] = "0" * 64
    forged_receipt = CleanupReceipt.model_validate(forged_receipt_values)
    forged_receipt_bytes = canonical_json_bytes(forged_receipt)
    forged_digest = hashlib.sha256(
        b"insurancekb.run-admission.cleanup-receipt.v1\0" + forged_receipt_bytes
    ).hexdigest()
    forged_journal = CleanupTerminalJournal(
        binding=binding,
        receipt=forged_receipt,
        receipt_digest=forged_digest,
    )
    journal_path = seed_controller._store.path(
        seed_controller._store.cleanup_terminal_journal_name(binding)
    )
    journal_path.write_bytes(canonical_json_bytes(forged_journal))
    journal_path.chmod(0o600)
    seed_controller.close()

    database_path = tmp_path / "budget.sqlite3"
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", TEST_API_KEY)
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", journal_path.parent)
    monkeypatch.setattr(
        admission_deployment,
        "_PRODUCTION_BUDGET_LEDGER_PATH",
        database_path,
    )
    monkeypatch.setattr(
        BudgetLedger,
        "infrastructure_cleanup_binding",
        lambda _ledger, reserve_id: binding
        if reserve_id == binding.reserve_id
        else (_ for _ in ()).throw(BudgetLedgerError("not found")),
    )
    _install_production_authorities(
        monkeypatch,
        _policy(
            key,
            key_id="cleanup-key",
            identity="cleanup-operator@example.test",
            domain=CLEANUP_AUTHORIZATION_DOMAIN,
            role="deployment-cleanup-operator",
        ),
    )
    controller = DeploymentController.for_production_cleanup(
        reserve_id=binding.reserve_id
    )
    controller._clock = lambda: NOW
    provider_calls: list[str] = []

    def detail(*, deployed_model: str) -> bytes:
        provider_calls.append("GET")
        return canonical_json_bytes(manifest)

    def delete(*, deployed_model: str) -> bytes:
        provider_calls.append("DELETE")
        return b"{}"

    monkeypatch.setattr(controller._transport, "deployment_detail", detail)
    monkeypatch.setattr(controller._transport, "delete_deployment", delete)
    try:
        with pytest.raises(DeploymentControlBlocked) as blocked:
            controller.cleanup(
                authorization=authorization,
                receipt_digest=binding.receipt_digest,
            )
    finally:
        controller.close()

    assert blocked.value.code == "cleanup_receipt_invalid"
    assert provider_calls == []


def test_o7_t9_19_c4_terminal_proof_survives_same_key_restart_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    seed_controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        _C4CleanupTransport(manifest),
    )
    root = seed_controller._store.root
    seed_controller.close()
    authorization = _c4_cleanup_authorization(key, binding)
    authorities = _policy(
        key,
        key_id="cleanup-key",
        identity="cleanup-operator@example.test",
        domain=CLEANUP_AUTHORIZATION_DOMAIN,
        role="deployment-cleanup-operator",
    )
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", TEST_API_KEY)
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", root)
    monkeypatch.setattr(
        admission_deployment,
        "_PRODUCTION_BUDGET_LEDGER_PATH",
        tmp_path / "budget.sqlite3",
    )
    monkeypatch.setattr(
        BudgetLedger,
        "infrastructure_cleanup_binding",
        lambda _ledger, reserve_id: binding
        if reserve_id == binding.reserve_id
        else (_ for _ in ()).throw(BudgetLedgerError("not found")),
    )
    _install_production_authorities(monkeypatch, authorities)
    remote: dict[str, ProviderDeploymentManifest | None] = {"manifest": manifest}
    provider_calls: list[str] = []

    def detail(*, deployed_model: str) -> bytes:
        provider_calls.append("GET")
        current = remote["manifest"]
        if current is None:
            raise DeploymentNotFound("absent")
        return canonical_json_bytes(current)

    def delete(*, deployed_model: str) -> bytes:
        provider_calls.append("DELETE")
        remote["manifest"] = None
        return b"{}"

    first_controller = DeploymentController.for_production_cleanup(
        reserve_id=binding.reserve_id
    )
    first_controller._clock = lambda: NOW
    monkeypatch.setattr(first_controller._transport, "deployment_detail", detail)
    monkeypatch.setattr(first_controller._transport, "delete_deployment", delete)
    try:
        first = first_controller.cleanup(
            authorization=authorization,
            receipt_digest=binding.receipt_digest,
        )
        authenticator_repr = repr(first_controller._cleanup_observation_authenticator)
    finally:
        first_controller.close()
    assert provider_calls == ["GET", "DELETE", "GET"]

    restart = DeploymentController.for_production_cleanup(reserve_id=binding.reserve_id)
    restart._clock = lambda: NOW
    monkeypatch.setattr(restart._transport, "deployment_detail", detail)
    monkeypatch.setattr(restart._transport, "delete_deployment", delete)
    try:
        replay = restart.cleanup(
            authorization=authorization,
            receipt_digest=binding.receipt_digest,
        )
    finally:
        restart.close()
    assert replay == first
    assert provider_calls == ["GET", "DELETE", "GET"]
    assert TEST_API_KEY not in authenticator_repr
    assert TEST_API_KEY.encode() not in first.receipt_path.read_bytes()
    assert first.journal_path is not None
    assert TEST_API_KEY.encode() not in first.journal_path.read_bytes()

    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", "wrong-cleanup-key")
    with pytest.raises(DeploymentControlBlocked) as wrong_key:
        DeploymentController.for_production_cleanup(reserve_id=binding.reserve_id)
    assert wrong_key.value.code == "production_cleanup_controller_unavailable"
    assert provider_calls == ["GET", "DELETE", "GET"]


@pytest.mark.parametrize("attack", ["copy", "deepcopy", "pickle", "construct"])
def test_o7_t9_19_c4_cleanup_authenticator_cannot_be_copied_or_serialized(
    attack: str,
) -> None:
    authenticator = admission_deployment._CleanupObservationAuthenticator.for_production(
        TEST_API_KEY
    )
    if attack == "construct":
        forged = object.__new__(type(authenticator))
        with pytest.raises(DeploymentControlBlocked):
            forged.proof(b"observation")
    else:
        operation: Callable[[], object] = {
            "copy": lambda: copy.copy(authenticator),
            "deepcopy": lambda: copy.deepcopy(authenticator),
            "pickle": lambda: pickle.dumps(authenticator),
        }[attack]
        with pytest.raises(TypeError):
            operation()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX fork")
def test_o7_t9_19_c4_cleanup_authenticator_is_invalid_after_fork() -> None:
    authenticator = admission_deployment._CleanupObservationAuthenticator.for_production(
        TEST_API_KEY
    )
    observation = b"fork-bound-cleanup-observation"
    authenticator.proof(observation)
    read_descriptor, write_descriptor = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_descriptor)
        try:
            authenticator.proof(observation)
        except BaseException:
            outcome = b"blocked"
        else:
            outcome = b"vulnerable"
        os.write(write_descriptor, outcome)
        os.close(write_descriptor)
        os._exit(0)
    os.close(write_descriptor)
    try:
        outcome = os.read(read_descriptor, 32)
    finally:
        os.close(read_descriptor)
        os.waitpid(pid, 0)
    assert outcome == b"blocked"


@pytest.mark.parametrize("version", [1, 2])
def test_o7_t9_19_c4_unsigned_legacy_journal_cannot_be_promoted_to_causal_cleanup(
    tmp_path: Path,
    version: int,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
    )
    legacy_path = controller._store.path(
        controller._store.cleanup_legacy_journal_name(binding, version)
    )
    legacy_path.write_bytes(
        canonical_json_bytes(
            {
                "version": version,
                "run_identity": binding.run_identity,
                "operation_id": binding.operation_id,
                "reserve_id": binding.reserve_id,
                "receipt_digest": binding.receipt_digest,
                "delete_started": True,
                "cleanup_authorization_digest": "4" * 64,
            }
        )
    )
    legacy_path.chmod(0o600)
    authorization = _c4_cleanup_authorization(key, binding)
    try:
        with pytest.raises(DeploymentControlBlocked) as blocked:
            controller._cleanup_for_testing(
                authorization=authorization,
                trusted_authorities=_policy(
                    key,
                    key_id="cleanup-key",
                    identity="cleanup-operator@example.test",
                    domain=CLEANUP_AUTHORIZATION_DOMAIN,
                    role="deployment-cleanup-operator",
                ),
                receipt_digest=receipt.content_digest,
            )
    finally:
        controller.close()
    assert blocked.value.code == "cleanup_journal_legacy_untrusted"
    assert (transport.detail_calls, transport.delete_calls) == (0, 0)


@pytest.mark.parametrize(
    "failure_point",
    ["intent", "terminal_journal", "terminal_receipt"],
)
def test_o7_t9_19_c4_atomic_publication_failure_is_recoverable_without_blind_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
    )
    authorities = _policy(
        key,
        key_id="cleanup-key",
        identity="cleanup-operator@example.test",
        domain=CLEANUP_AUTHORIZATION_DOMAIN,
        role="deployment-cleanup-operator",
    )
    authorization = _c4_cleanup_authorization(key, binding)
    original = controller._store.atomic_write_absent_on_failure
    failed = False

    def fail_once(name: str, content: bytes) -> tuple[int, int] | None:
        nonlocal failed
        target = (
            (failure_point == "intent" and name.endswith(".cleanup-delete-intent.slot"))
            or (
                failure_point == "terminal_journal"
                and name.endswith(".cleanup-terminal-journal.json")
            )
            or (
                failure_point == "terminal_receipt"
                and name.endswith(".cleanup-receipt.json")
            )
        )
        if target and not failed:
            failed = True
            raise DeploymentControlBlocked(
                "operation_artifact_unsafe",
                "simulated no-replace publication failure",
            )
        return original(name, content)

    monkeypatch.setattr(controller._store, "atomic_write_absent_on_failure", fail_once)
    with pytest.raises(DeploymentControlBlocked):
        controller._cleanup_for_testing(
            authorization=authorization,
            trusted_authorities=authorities,
            receipt_digest=receipt.content_digest,
        )
    calls_after_failure = transport.delete_calls
    monkeypatch.setattr(controller._store, "atomic_write_absent_on_failure", original)
    recovered = controller._cleanup_for_testing(
        authorization=authorization,
        trusted_authorities=authorities,
        receipt_digest=receipt.content_digest,
    )
    replay = controller._cleanup_for_testing(
        authorization=authorization,
        trusted_authorities=authorities,
        receipt_digest=receipt.content_digest,
    )
    controller.close()

    assert recovered == replay
    assert recovered.receipt.billing_stop_verified is True
    assert transport.delete_calls == (1 if failure_point == "intent" else calls_after_failure)
    assert len(tuple((tmp_path / "deployment-control").glob("*.cleanup-receipt.json"))) == 1
    assert len(
        tuple((tmp_path / "deployment-control").glob("*.cleanup-terminal-journal.json"))
    ) == 1


@pytest.mark.parametrize(
    "failure_phase",
    ["create", "link", "file_fsync", "dir_fsync", "readback"],
)
def test_o7_t9_19_c4_completed_attempt_publication_failure_is_noncausal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_phase: str,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    now = {"value": NOW}
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
        clock=lambda: now["value"],
    )
    authorities = _policy(
        key,
        key_id="cleanup-key",
        identity="cleanup-operator@example.test",
        domain=CLEANUP_AUTHORIZATION_DOMAIN,
        role="deployment-cleanup-operator",
    )
    original_write = controller._store.atomic_write_absent_on_failure

    def fail_attempt(name: str, content: bytes) -> tuple[int, int] | None:
        if name.endswith(".cleanup-delete-attempt.slot"):
            raise DeploymentControlBlocked(
                "operation_artifact_unsafe",
                f"simulated attempt {failure_phase} failure",
            )
        return original_write(name, content)

    monkeypatch.setattr(
        controller._store,
        "atomic_write_absent_on_failure",
        fail_attempt,
    )
    first = _c4_cleanup_authorization(
        key,
        binding,
        issued_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(DeploymentControlBlocked):
        controller._cleanup_for_testing(
            authorization=first,
            trusted_authorities=authorities,
            receipt_digest=binding.receipt_digest,
        )
    assert transport.delete_calls == 1
    root = controller._store.root
    assert not tuple(root.glob("*.cleanup-delete-attempt.slot"))
    assert not tuple(root.glob("*.cleanup-receipt.json"))
    assert not tuple(root.glob("*.cleanup-terminal-journal.json"))

    monkeypatch.setattr(
        controller._store,
        "atomic_write_absent_on_failure",
        original_write,
    )
    now["value"] = NOW + timedelta(minutes=2)
    replacement = _c4_cleanup_authorization(
        key,
        binding,
        issued_at=now["value"] - timedelta(seconds=1),
        expires_at=now["value"] + timedelta(minutes=30),
    )
    try:
        recovered = controller._cleanup_for_testing(
            authorization=replacement,
            trusted_authorities=authorities,
            receipt_digest=binding.receipt_digest,
        )
    finally:
        controller.close()
    assert recovered.receipt.terminal_state == "already_absent_404"
    assert recovered.receipt.causal_delete_attempt_digest is None
    assert transport.delete_calls == 1


def test_o7_t9_19_c4_forged_completed_attempt_blocks_before_provider_io(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
    )
    attempt = controller._store.path(
        f"{_c4_cleanup_resource_prefix(binding)}.00.cleanup-delete-attempt.slot"
    )
    attempt.write_bytes(b"{}")
    attempt.chmod(0o600)
    try:
        with pytest.raises(DeploymentControlBlocked) as blocked:
            controller._cleanup_for_testing(
                authorization=_c4_cleanup_authorization(key, binding),
                trusted_authorities=_policy(
                    key,
                    key_id="cleanup-key",
                    identity="cleanup-operator@example.test",
                    domain=CLEANUP_AUTHORIZATION_DOMAIN,
                    role="deployment-cleanup-operator",
                ),
                receipt_digest=binding.receipt_digest,
            )
    finally:
        controller.close()
    assert blocked.value.code == "cleanup_attempt_invalid"
    assert (transport.detail_calls, transport.delete_calls) == (0, 0)


@pytest.mark.parametrize(
    "forgery",
    [
        "run",
        "resource",
        "authorization",
        "transport",
        "receipt",
        "model_copy",
        "model_construct",
        "pickle_copy",
    ],
)
def test_o7_t9_19_c4_completed_attempt_identity_or_copy_forgery_fails_closed(
    tmp_path: Path,
    forgery: str,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
    )
    authorities = _policy(
        key,
        key_id="cleanup-key",
        identity="cleanup-operator@example.test",
        domain=CLEANUP_AUTHORIZATION_DOMAIN,
        role="deployment-cleanup-operator",
    )
    authorization = _c4_cleanup_authorization(key, binding)
    result = controller._cleanup_for_testing(
        authorization=authorization,
        trusted_authorities=authorities,
        receipt_digest=binding.receipt_digest,
    )
    attempt_path = next(controller._store.root.glob("*.cleanup-delete-attempt.slot"))
    attempt = DurableDeleteAttemptEvidence.model_validate_json(
        attempt_path.read_bytes()
    )
    assert result.journal_path is not None
    result.journal_path.unlink()
    result.receipt_path.unlink()
    changed_binding = binding
    if forgery == "run":
        changed_binding = binding.model_copy(update={"run_identity": "foreign-run"})
    elif forgery == "resource":
        changed_binding = binding.model_copy(update={"reserve_id": "foreign-reserve"})
    elif forgery == "receipt":
        changed_binding = binding.model_copy(update={"receipt_digest": "0" * 64})
    if forgery in {"run", "resource", "receipt"}:
        forged = attempt.model_copy(update={"binding": changed_binding})
    elif forgery == "authorization":
        forged = attempt.model_copy(
            update={"cleanup_authorization_digest": "0" * 64}
        )
    elif forgery == "transport":
        forged = attempt.model_copy(
            update={"cleanup_transport_identity_digest": "0" * 64}
        )
    elif forgery == "model_copy":
        forged = attempt.model_copy(
            update={"attempted_at": attempt.attempted_at + timedelta(seconds=1)}
        )
    elif forgery == "model_construct":
        forged = DurableDeleteAttemptEvidence.model_construct(
            version=attempt.version,
            binding=attempt.binding,
            intent_digest=attempt.intent_digest,
            cleanup_authorization_digest=attempt.cleanup_authorization_digest,
            cleanup_transport_identity_digest=(
                attempt.cleanup_transport_identity_digest
            ),
            attempted_at=attempt.attempted_at + timedelta(seconds=1),
            outcome_class=attempt.outcome_class,
            attempt_proof=attempt.attempt_proof,
        )
    else:
        forged = pickle.loads(pickle.dumps(attempt))
        object.__setattr__(
            forged,
            "attempted_at",
            attempt.attempted_at + timedelta(seconds=1),
        )
    attempt_path.write_bytes(canonical_json_bytes(forged))
    transport.manifest = manifest
    transport.detail_calls = 0
    transport.delete_calls = 0
    try:
        with pytest.raises(DeploymentControlBlocked) as blocked:
            controller._cleanup_for_testing(
                authorization=authorization,
                trusted_authorities=authorities,
                receipt_digest=binding.receipt_digest,
            )
    finally:
        controller.close()
    assert blocked.value.code == "cleanup_attempt_invalid"
    assert (transport.detail_calls, transport.delete_calls) == (0, 0)


@pytest.mark.parametrize("failure", [KeyboardInterrupt, SystemExit])
def test_o7_t9_19_c4_process_control_during_delete_never_creates_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: type[BaseException],
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
    )

    def interrupt(*, deployed_model: str) -> bytes:
        transport.delete_calls += 1
        raise failure("process control")

    monkeypatch.setattr(transport, "delete_deployment", interrupt)
    try:
        with pytest.raises(failure):
            controller._cleanup_for_testing(
                authorization=_c4_cleanup_authorization(key, binding),
                trusted_authorities=_policy(
                    key,
                    key_id="cleanup-key",
                    identity="cleanup-operator@example.test",
                    domain=CLEANUP_AUTHORIZATION_DOMAIN,
                    role="deployment-cleanup-operator",
                ),
                receipt_digest=binding.receipt_digest,
            )
    finally:
        controller.close()
    root = tmp_path / "deployment-control"
    assert not tuple(root.glob("*.cleanup-delete-attempt.slot"))
    assert not tuple(root.glob("*.cleanup-receipt.json"))
    assert not tuple(root.glob("*.cleanup-terminal-journal.json"))


def test_o7_t9_19_c4_terminal_get_expiry_blocks_before_receipt_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    expired = threading.Event()
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
        clock=lambda: NOW + timedelta(minutes=2) if expired.is_set() else NOW,
    )
    authorization = _c4_cleanup_authorization(
        key,
        binding,
        issued_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=1),
    )
    original_detail = transport.deployment_detail

    def expire_after_terminal_get(*, deployed_model: str) -> bytes:
        try:
            return original_detail(deployed_model=deployed_model)
        finally:
            if transport.detail_calls == 2:
                expired.set()

    monkeypatch.setattr(transport, "deployment_detail", expire_after_terminal_get)
    try:
        with pytest.raises(DeploymentControlBlocked) as blocked:
            controller._cleanup_for_testing(
                authorization=authorization,
                trusted_authorities=_policy(
                    key,
                    key_id="cleanup-key",
                    identity="cleanup-operator@example.test",
                    domain=CLEANUP_AUTHORIZATION_DOMAIN,
                    role="deployment-cleanup-operator",
                ),
                receipt_digest=receipt.content_digest,
            )
    finally:
        controller.close()

    assert blocked.value.code == "cleanup_authorization_invalid"
    assert transport.delete_calls == 1
    root = tmp_path / "deployment-control"
    assert tuple(root.glob("*.cleanup-terminal-journal.json")) == ()
    assert tuple(root.glob("*.cleanup-receipt.json")) == ()


def test_o7_t9_19_c4_first_get_rechecks_freshness_after_journal_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    expired = False
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
        clock=lambda: NOW + timedelta(minutes=2) if expired else NOW,
    )
    authorization = _c4_cleanup_authorization(
        key,
        binding,
        issued_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=1),
    )
    original_scan = controller._load_cleanup_delete_intents

    def expire_after_scan(**kwargs: Any) -> Any:
        nonlocal expired
        result = original_scan(**kwargs)
        expired = True
        return result

    monkeypatch.setattr(controller, "_load_cleanup_delete_intents", expire_after_scan)
    root = controller._store.root
    before = frozenset(root.iterdir())
    try:
        with pytest.raises(DeploymentControlBlocked) as blocked:
            controller._cleanup_for_testing(
                authorization=authorization,
                trusted_authorities=_policy(
                    key,
                    key_id="cleanup-key",
                    identity="cleanup-operator@example.test",
                    domain=CLEANUP_AUTHORIZATION_DOMAIN,
                    role="deployment-cleanup-operator",
                ),
                receipt_digest=binding.receipt_digest,
            )
    finally:
        controller.close()

    assert blocked.value.code == "cleanup_authorization_invalid"
    assert (transport.detail_calls, transport.delete_calls) == (0, 0)
    assert not tuple(root.glob("*.cleanup-delete-intent*"))
    assert not tuple(root.glob("*.cleanup-terminal-journal.json"))
    assert not tuple(root.glob("*.cleanup-receipt.json"))
    assert before <= frozenset(root.iterdir())


def test_o7_t9_19_c4_restore_rechecks_freshness_after_receipt_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    transport = _C4CleanupTransport(manifest)
    now = {"value": NOW}
    controller, binding = _c4_cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
        clock=lambda: now["value"],
    )
    authorities = _policy(
        key,
        key_id="cleanup-key",
        identity="cleanup-operator@example.test",
        domain=CLEANUP_AUTHORIZATION_DOMAIN,
        role="deployment-cleanup-operator",
    )
    first = _c4_cleanup_authorization(
        key,
        binding,
        issued_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=1),
    )
    original_write = controller._store.atomic_write_absent_on_failure
    failed_terminal_receipt = False

    def fail_first_terminal_receipt(
        name: str,
        content: bytes,
    ) -> tuple[int, int] | None:
        nonlocal failed_terminal_receipt
        if name.endswith(".cleanup-receipt.json") and not failed_terminal_receipt:
            failed_terminal_receipt = True
            raise DeploymentControlBlocked(
                "operation_artifact_unsafe",
                "simulated terminal receipt interruption",
            )
        return original_write(name, content)

    monkeypatch.setattr(
        controller._store,
        "atomic_write_absent_on_failure",
        fail_first_terminal_receipt,
    )
    with pytest.raises(DeploymentControlBlocked):
        controller._cleanup_for_testing(
            authorization=first,
            trusted_authorities=authorities,
            receipt_digest=binding.receipt_digest,
        )
    assert transport.delete_calls == 1
    monkeypatch.setattr(
        controller._store,
        "atomic_write_absent_on_failure",
        original_write,
    )
    expired_after_receipt_readback = False

    def expire_after_receipt_readback(
        name: str,
        content: bytes,
    ) -> tuple[int, int] | None:
        nonlocal expired_after_receipt_readback
        outcome = original_write(name, content)
        if name.endswith(".cleanup-receipt.json"):
            expired_after_receipt_readback = True
            now["value"] = NOW + timedelta(minutes=1)
        return outcome

    monkeypatch.setattr(
        controller._store,
        "atomic_write_absent_on_failure",
        expire_after_receipt_readback,
    )
    with pytest.raises(DeploymentControlBlocked) as expired:
        controller._cleanup_for_testing(
            authorization=first,
            trusted_authorities=authorities,
            receipt_digest=binding.receipt_digest,
        )
    assert expired.value.code == "cleanup_authorization_invalid"
    assert expired_after_receipt_readback is True
    assert transport.delete_calls == 1

    now["value"] = NOW + timedelta(minutes=2)
    replacement = _c4_cleanup_authorization(
        key,
        binding,
        issued_at=now["value"] - timedelta(seconds=1),
        expires_at=now["value"] + timedelta(minutes=30),
    )
    monkeypatch.setattr(
        controller._store,
        "atomic_write_absent_on_failure",
        original_write,
    )
    try:
        recovered = controller._cleanup_for_testing(
            authorization=replacement,
            trusted_authorities=authorities,
            receipt_digest=binding.receipt_digest,
        )
    finally:
        controller.close()

    assert recovered.receipt.billing_stop_verified is True
    assert transport.delete_calls == 1


def test_o7_production_adoption_uses_controller_receipt_and_reserves_segments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pricing_key = Ed25519PrivateKey.generate()
    cap_key = Ed25519PrivateKey.generate()
    provision_key = Ed25519PrivateKey.generate()
    adoption_key = Ed25519PrivateKey.generate()
    pricing_content = _pricing_content()
    cap_content = _cap_content()
    pricing = _pricing_approval(pricing_key, pricing_content)
    cap = _cap_approval(cap_key, cap_content)
    provisioning_payload, provisioning = _provisioning_authorization(
        provision_key,
        pricing,
        cap,
    )
    authorities = {
        **_policy(
            pricing_key,
            key_id="pricing-key",
            identity="pricing-owner@example.test",
            domain=PRICING_EVIDENCE_DOMAIN,
            role="pricing-evidence-approver",
        ),
        **_policy(
            cap_key,
            key_id="cap-key",
            identity="cap-attestor@example.test",
            domain=PROVIDER_CAP_DOMAIN,
            role="provider-cap-attestor",
        ),
        **_policy(
            provision_key,
            key_id="provisioning-key",
            identity="deployment-operator@example.test",
            domain=PROVISIONING_AUTHORIZATION_DOMAIN,
            role="deployment-provisioner",
        ),
        **_policy(
            adoption_key,
            key_id="adoption-key",
            identity="budget-owner@example.test",
            domain=ADOPTION_AUTHORIZATION_DOMAIN,
            role="budget-approver",
        ),
    }
    _install_production_authorities(monkeypatch, authorities)
    provisioning_path = tmp_path / "provisioning.sqlite3"
    provisioning_ledger = BudgetLedger(provisioning_path)
    permit = provisioning_ledger.reserve_provisioning_before_post(
        authorization=provisioning,
        expected=provisioning_payload,
        pricing_evidence_bytes=canonical_json_bytes(pricing_content),
        pricing_approval=pricing,
        provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
        provider_cap_approval=cap,
    )
    assert type(permit) is InfrastructureCreatePermit
    deployment_suffix = deterministic_deployment_suffix(
        provisioning_payload.run_identity,
        provisioning_payload.operation_id,
        OWNERSHIP_NONCE,
    )
    manifest = _manifest(
        deployed_model=f"{provisioning_payload.base_model}-{deployment_suffix}"
    )
    role_plan = ModelRolePlan(
        provider="bailian",
        model_id=manifest.deployed_model,
        immutable_deployment_id=manifest.deployed_model,
        protocol="https",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        provider_policy="bailian-deployment-detail-v1",
        credential_env_name="HARNESS_DASHSCOPE_API_KEY",
    )
    plan = RunAdmissionPlanPayload(
        run_identity=provisioning_payload.run_identity,
        purpose=provisioning_payload.purpose,
        model_roles={
            "annotator": role_plan,
            "judge": role_plan,
            "weak_extractor": role_plan,
        },
        budget_contract_hash="9" * 64,
    )
    receipt, receipt_capability = _controller_issued_production_receipt(
        monkeypatch,
        ledger_path=provisioning_path,
        operation_root=tmp_path / "controller-store",
        plan=plan,
        authorization=provisioning,
        permit=permit,
        manifest=manifest,
    )
    expected, adoption = _adoption_authorization(
        adoption_key,
        pricing,
        cap,
        receipt,
    )
    adoption_ledger = BudgetLedger(tmp_path / "adoption.sqlite3")

    with pytest.raises(BudgetLedgerError, match="production|receipt|verified|signed"):
        adoption_ledger.reserve_existing_adoption(
            authorization=adoption,
            expected=expected,
            receipt_capability=copy.copy(receipt_capability),
            pricing_evidence_bytes=canonical_json_bytes(pricing_content),
            pricing_approval=pricing,
            provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
            provider_cap_approval=cap,
        )
    with sqlite3.connect(tmp_path / "adoption.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM infrastructure_reserves"
        ).fetchone() == (0,)

    snapshot = adoption_ledger.reserve_existing_adoption(
        authorization=adoption,
        expected=expected,
        receipt_capability=receipt_capability,
        pricing_evidence_bytes=canonical_json_bytes(pricing_content),
        pricing_approval=pricing,
        provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
        provider_cap_approval=cap,
    )

    assert type(snapshot) is InfrastructureReserveSnapshot
    assert snapshot.authorization_domain == ADOPTION_AUTHORIZATION_DOMAIN
    assert snapshot.maximum.cost_minor_units == 6_048
    with sqlite3.connect(tmp_path / "adoption.sqlite3") as connection:
        sidecar = connection.execute(
            """SELECT evidence_bytes,approval_envelope_bytes
               FROM infrastructure_provider_cap_evidence"""
        ).fetchone()
        assert sidecar == (
            canonical_json_bytes(cap_content),
            canonical_json_bytes(cap),
        )

    for label, incurred, future in (
        ("incurred", 1, 5_376),
        ("future", 672, 1),
    ):
        invalid_expected, invalid_adoption = _adoption_authorization(
            adoption_key,
            pricing,
            cap,
            receipt,
            incurred_cost_minor_units=incurred,
            future_max_cost_minor_units=future,
        )
        invalid_path = tmp_path / f"adoption-invalid-{label}.sqlite3"
        invalid_ledger = BudgetLedger(invalid_path)
        with pytest.raises(BudgetLedgerError, match="cost|pricing|mechanical"):
            invalid_ledger.reserve_existing_adoption(
                authorization=invalid_adoption,
                expected=invalid_expected,
                receipt_capability=receipt_capability,
                pricing_evidence_bytes=canonical_json_bytes(pricing_content),
                pricing_approval=pricing,
                provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
                provider_cap_approval=cap,
            )
        with sqlite3.connect(invalid_path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM infrastructure_reserves"
            ).fetchone() == (0,)


def test_o7_signed_pricing_mechanically_rounds_fixed_and_inference_rates() -> None:
    key = Ed25519PrivateKey.generate()
    content = _pricing_content()
    evidence = canonical_json_bytes(content)
    approval = _pricing_approval(key, content)

    verified = verify_pricing_evidence(
        evidence,
        envelope=approval,
        trusted_authorities=_policy(
            key,
            key_id="pricing-key",
            identity="pricing-owner@example.test",
            domain=PRICING_EVIDENCE_DOMAIN,
            role="pricing-evidence-approver",
        ),
        expected_scope="goldenset-production",
        now=NOW,
        fixed_duration_seconds=3601,
    )

    assert verified.evidence_digest == pricing_evidence_digest(evidence)
    assert verified.approval_digest == pricing_approval_digest(approval)
    assert verified.fixed_cost_minor_units == 1_344
    assert verified.input_cost_per_million_minor_units == 240
    assert verified.output_cost_per_million_minor_units == 960


def test_o7_sealed_pricing_is_the_only_source_of_exact_model_role_rate() -> None:
    key = Ed25519PrivateKey.generate()
    content = _pricing_content()
    verified = verify_pricing_evidence(
        canonical_json_bytes(content),
        envelope=_pricing_approval(key, content),
        trusted_authorities=_policy(
            key,
            key_id="pricing-key",
            identity="pricing-owner@example.test",
            domain=PRICING_EVIDENCE_DOMAIN,
            role="pricing-evidence-approver",
        ),
        expected_scope="goldenset-production",
        now=NOW,
        fixed_duration_seconds=3600,
    )
    role_plan = ModelRolePlan(
        provider="bailian",
        model_id="qwen3.7-plus-2026-05-26-031strng",
        immutable_deployment_id="qwen3.7-plus-2026-05-26-031strng",
        protocol="openai-compatible",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        provider_policy="bailian-deployment-detail-v1",
        credential_env_name="BAILIAN_API_KEY",
    )

    derived = derive_role_rate_from_pricing(
        verified,
        role_plan=role_plan,
        expected_provider="bailian",
        expected_currency="CNY",
    )
    assert derived.input_cost_per_million_minor_units == 240
    assert derived.output_cost_per_million_minor_units == 960

    for forged in (
        derived.model_copy(update={"input_cost_per_million_minor_units": 1}),
        RoleRate(
            model_role_identity_hash="0" * 64,
            input_cost_per_million_minor_units=240,
            output_cost_per_million_minor_units=960,
        ),
    ):
        with pytest.raises(BudgetLedgerError, match="role rate"):
            derive_role_rate_from_pricing(
                verified,
                role_plan=role_plan,
                expected_provider="bailian",
                expected_currency="CNY",
                candidate=forged,
            )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("issuer", "operator-authored"),
        ("currency", "USD"),
        ("provider", "other"),
        ("region", "cn-shanghai"),
        ("base_model", "mutable-alias"),
        ("request_plan", "ptu"),
        ("receipt_plan", "ptu_v2"),
        ("input_tpm_quota", 20_000),
        ("output_tpm_quota", 2_000),
        ("billing_quantum_seconds", 60),
        ("round_up_rule", "floor"),
        ("tiers_policy", "unknown"),
        ("thinking_policy", "unknown"),
        ("cache_policy", "unknown"),
        ("overflow_policy", "zero"),
    ],
)
def test_o7_pricing_evidence_mutation_or_unknown_cost_is_rejected(
    field: str,
    replacement: object,
) -> None:
    key = Ed25519PrivateKey.generate()
    content = _pricing_content()
    approval = _pricing_approval(key, content)
    mutated = content.model_dump(mode="python")
    mutated[field] = replacement
    evidence = canonical_json_bytes(mutated)

    with pytest.raises(AuthorizationVerificationError):
        verify_pricing_evidence(
            evidence,
            envelope=approval,
            trusted_authorities=_policy(
                key,
                key_id="pricing-key",
                identity="pricing-owner@example.test",
                domain=PRICING_EVIDENCE_DOMAIN,
                role="pricing-evidence-approver",
            ),
            expected_scope="goldenset-production",
            now=NOW,
            fixed_duration_seconds=3600,
        )


def test_o7_unsigned_expired_or_wrong_role_pricing_is_rejected() -> None:
    key = Ed25519PrivateKey.generate()
    content = _pricing_content()
    evidence = canonical_json_bytes(content)
    approval = _pricing_approval(key, content)

    cases = (
        approval.model_copy(update={"signature": base64.b64encode(b"x" * 64).decode()}),
        _pricing_approval(key, content, expires_at=NOW),
    )
    for candidate in cases:
        with pytest.raises(AuthorizationVerificationError):
            verify_pricing_evidence(
                evidence,
                envelope=candidate,
                trusted_authorities=_policy(
                    key,
                    key_id="pricing-key",
                    identity="pricing-owner@example.test",
                    domain=PRICING_EVIDENCE_DOMAIN,
                    role="pricing-evidence-approver",
                ),
                expected_scope="goldenset-production",
                now=NOW,
                fixed_duration_seconds=3600,
            )

    with pytest.raises(AuthorizationVerificationError):
        verify_pricing_evidence(
            evidence,
            envelope=approval,
            trusted_authorities=_policy(
                key,
                key_id="pricing-key",
                identity="pricing-owner@example.test",
                domain=PRICING_EVIDENCE_DOMAIN,
                role="budget-approver",
            ),
            expected_scope="goldenset-production",
            now=NOW,
            fixed_duration_seconds=3600,
        )


@pytest.mark.parametrize("segments", [None, (1, 1)])
def test_o7_pricing_multiplication_and_addition_overflow_are_typed(
    segments: tuple[int, ...] | None,
) -> None:
    key = Ed25519PrivateKey.generate()
    content = _pricing_content(
        billing_quantum_seconds=1,
        fixed_cost_per_quantum_minor_units=2**63 - 1,
    )
    with pytest.raises(AuthorizationVerificationError, match="overflow"):
        verify_pricing_evidence(
            canonical_json_bytes(content),
            envelope=_pricing_approval(key, content),
            trusted_authorities=_policy(
                key,
                key_id="pricing-key",
                identity="pricing-owner@example.test",
                domain=PRICING_EVIDENCE_DOMAIN,
                role="pricing-evidence-approver",
            ),
            expected_scope="goldenset-production",
            now=NOW,
            fixed_duration_seconds=2,
            fixed_duration_segments_seconds=segments,
        )


def test_o7_provider_cap_requires_signed_exact_resource_and_both_coverages() -> None:
    key = Ed25519PrivateKey.generate()
    content = _cap_content()
    evidence = canonical_json_bytes(content)
    approval = _cap_approval(key, content)

    verified = verify_provider_cap_evidence(
        evidence,
        envelope=approval,
        trusted_authorities=_policy(
            key,
            key_id="cap-key",
            identity="cap-attestor@example.test",
            domain=PROVIDER_CAP_DOMAIN,
            role="provider-cap-attestor",
        ),
        expected_scope="goldenset-production",
        now=NOW,
    )

    assert verified.evidence_digest == provider_cap_evidence_digest(evidence)
    assert verified.approval_digest == provider_cap_approval_digest(approval)
    assert verified.coverage == frozenset({"fixed_infrastructure", "inference"})
    assert verified.max_cost_minor_units == 20_000


def test_o7_private_test_verifiers_reject_production_issued_capabilities() -> None:
    pricing_key = Ed25519PrivateKey.generate()
    cap_key = Ed25519PrivateKey.generate()
    pricing_content = _pricing_content()
    cap_content = _cap_content()
    pricing = verify_pricing_evidence(
        canonical_json_bytes(pricing_content),
        envelope=_pricing_approval(pricing_key, pricing_content),
        trusted_authorities=_policy(
            pricing_key,
            key_id="pricing-key",
            identity="pricing-owner@example.test",
            domain=PRICING_EVIDENCE_DOMAIN,
            role="pricing-evidence-approver",
        ),
        expected_scope="goldenset-production",
        now=NOW,
        fixed_duration_seconds=3600,
    )
    cap = verify_provider_cap_evidence(
        canonical_json_bytes(cap_content),
        envelope=_cap_approval(cap_key, cap_content),
        trusted_authorities=_policy(
            cap_key,
            key_id="cap-key",
            identity="cap-attestor@example.test",
            domain=PROVIDER_CAP_DOMAIN,
            role="provider-cap-attestor",
        ),
        expected_scope="goldenset-production",
        now=NOW,
    )
    for require, capability in (
        (_require_verified_pricing_capability_for_testing, pricing),
        (_require_verified_provider_capability_for_testing, cap),
    ):
        with pytest.raises(AuthorizationVerificationError, match="test"):
            require(capability)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("issuer", "operator-authored"),
        ("workspace_ref", "other-workspace"),
        ("project_ref", "sha256:" + "1" * 64),
        ("credential_ref", "sha256:" + "2" * 64),
        ("currency", "USD"),
        ("max_cost_minor_units", 19_999),
        ("coverage", ("fixed_infrastructure",)),
        ("observed_at", NOW - timedelta(days=1)),
        ("expires_at", NOW),
    ],
)
def test_o7_provider_cap_mutation_cross_resource_or_incomplete_coverage_is_rejected(
    field: str,
    replacement: object,
) -> None:
    key = Ed25519PrivateKey.generate()
    content = _cap_content()
    approval = _cap_approval(key, content)
    mutated = content.model_dump(mode="python")
    mutated[field] = replacement

    with pytest.raises(AuthorizationVerificationError):
        verify_provider_cap_evidence(
            canonical_json_bytes(mutated),
            envelope=approval,
            trusted_authorities=_policy(
                key,
                key_id="cap-key",
                identity="cap-attestor@example.test",
                domain=PROVIDER_CAP_DOMAIN,
                role="provider-cap-attestor",
            ),
            expected_scope="goldenset-production",
            now=NOW,
        )


def test_o7_budget_ledger_production_entry_reverifies_signed_evidence_before_reserve(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pricing_key = Ed25519PrivateKey.generate()
    cap_key = Ed25519PrivateKey.generate()
    provision_key = Ed25519PrivateKey.generate()
    pricing_content = _pricing_content()
    cap_content = _cap_content()
    pricing = _pricing_approval(pricing_key, pricing_content)
    cap = _cap_approval(cap_key, cap_content)
    expected, authorization = _provisioning_authorization(provision_key, pricing, cap)
    authorities = {
        **_policy(
            pricing_key,
            key_id="pricing-key",
            identity="pricing-owner@example.test",
            domain=PRICING_EVIDENCE_DOMAIN,
            role="pricing-evidence-approver",
        ),
        **_policy(
            cap_key,
            key_id="cap-key",
            identity="cap-attestor@example.test",
            domain=PROVIDER_CAP_DOMAIN,
            role="provider-cap-attestor",
        ),
        **_policy(
            provision_key,
            key_id="provisioning-key",
            identity="deployment-operator@example.test",
            domain=PROVISIONING_AUTHORIZATION_DOMAIN,
            role="deployment-provisioner",
        ),
    }
    _install_production_authorities(monkeypatch, authorities)
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")

    permit = ledger.reserve_provisioning_before_post(
        authorization=authorization,
        expected=expected,
        pricing_evidence_bytes=canonical_json_bytes(pricing_content),
        pricing_approval=pricing,
        provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
        provider_cap_approval=cap,
    )

    assert permit.reserve.maximum.cost_minor_units == 5_376
    assert permit.reserve == ledger.infrastructure_reserve("infra-strong-031")
    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        before = connection.execute("SELECT * FROM infrastructure_reserves").fetchall()
    monkeypatch.setattr(ledger, "_clock", lambda: NOW + timedelta(hours=2))
    with pytest.raises(BudgetLedgerError, match="expired|stale|signed"):
        ledger.reserve_provisioning_before_post(
            authorization=authorization,
            expected=expected,
            pricing_evidence_bytes=canonical_json_bytes(pricing_content),
            pricing_approval=pricing,
            provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
            provider_cap_approval=cap,
        )
    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        assert connection.execute("SELECT * FROM infrastructure_reserves").fetchall() == before


def test_o3_o7_production_ledger_rejects_caller_self_enrolled_authorities_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pricing_key = Ed25519PrivateKey.generate()
    cap_key = Ed25519PrivateKey.generate()
    provision_key = Ed25519PrivateKey.generate()
    root_key = Ed25519PrivateKey.generate()
    pricing_content = _pricing_content()
    cap_content = _cap_content()
    pricing = _pricing_approval(pricing_key, pricing_content)
    cap = _cap_approval(cap_key, cap_content)
    expected, authorization = _provisioning_authorization(provision_key, pricing, cap)
    caller_authorities = {
        **_policy(
            pricing_key,
            key_id="pricing-key",
            identity="pricing-owner@example.test",
            domain=PRICING_EVIDENCE_DOMAIN,
            role="pricing-evidence-approver",
        ),
        **_policy(
            cap_key,
            key_id="cap-key",
            identity="cap-attestor@example.test",
            domain=PROVIDER_CAP_DOMAIN,
            role="provider-cap-attestor",
        ),
        **_policy(
            provision_key,
            key_id="provisioning-key",
            identity="deployment-operator@example.test",
            domain=PROVISIONING_AUTHORIZATION_DOMAIN,
            role="deployment-provisioner",
        ),
    }
    root_authorities = _policy(
        root_key,
        key_id="root-pricing-key",
        identity="root-pricing-owner@example.test",
        domain=PRICING_EVIDENCE_DOMAIN,
        role="pricing-evidence-approver",
    )
    monkeypatch.setattr(
        "insurance_harness.goldenset.admission_cli._load_deployment_approval_configuration",
        lambda: (root_authorities, frozenset(), frozenset(), frozenset()),
    )
    db_path = tmp_path / "self-enroll.sqlite3"
    ledger = BudgetLedger(db_path)

    with pytest.raises(BudgetLedgerError, match="signed|trusted|authority|key"):
        ledger.reserve_provisioning_before_post(
            authorization=authorization,
            expected=expected,
            trusted_authorities=caller_authorities,
            pricing_evidence_bytes=canonical_json_bytes(pricing_content),
            pricing_approval=pricing,
            provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
            provider_cap_approval=cap,
        )

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM infrastructure_reserves").fetchone() == (0,)


@pytest.mark.parametrize("deployment_key", ["strong", "weak"])
@pytest.mark.parametrize(
    "forgery",
    [
        "issuer",
        "transport_identity_digest",
        "invalid_window",
        "future_window",
        "self_consistent_window",
        "cleanup_binding_topology",
    ],
)
def test_o4_o8_public_topology_rejects_workspace_join_and_reconciliation_forgery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    deployment_key: str,
    forgery: str,
) -> None:
    pricing_key = Ed25519PrivateKey.generate()
    cap_key = Ed25519PrivateKey.generate()
    provision_key = Ed25519PrivateKey.generate()
    finance_key = Ed25519PrivateKey.generate()
    cleanup_key = Ed25519PrivateKey.generate()
    pricing_content = _pricing_content()
    cap_content = _cap_content(expires_at=NOW + timedelta(minutes=20))
    pricing = _pricing_approval(pricing_key, pricing_content)
    cap = _cap_approval(cap_key, cap_content)
    expected, authorization = _provisioning_authorization(provision_key, pricing, cap)
    weak_pricing_content = _pricing_content(
        base_model="deepseek-v4-flash",
        fixed_cost_per_quantum_minor_units=432,
    )
    weak_pricing = _pricing_approval(pricing_key, weak_pricing_content)
    weak_expected, weak_authorization = _provisioning_authorization(
        provision_key,
        weak_pricing,
        cap,
        maximum_cost_minor_units=3_456,
        operation_id="op-weak-031",
        reserve_id="infra-weak-031",
        base_model="deepseek-v4-flash",
    )
    authorities = {
        **_policy(
            pricing_key,
            key_id="pricing-key",
            identity="pricing-owner@example.test",
            domain=PRICING_EVIDENCE_DOMAIN,
            role="pricing-evidence-approver",
        ),
        **_policy(
            cap_key,
            key_id="cap-key",
            identity="cap-attestor@example.test",
            domain=PROVIDER_CAP_DOMAIN,
            role="provider-cap-attestor",
        ),
        **_policy(
            provision_key,
            key_id="provisioning-key",
            identity="deployment-operator@example.test",
            domain=PROVISIONING_AUTHORIZATION_DOMAIN,
            role="deployment-provisioner",
        ),
        **_policy(
            finance_key,
            key_id="finance-key",
            identity="finance-owner@example.test",
            domain="budget",
            role="budget_approver",
        ),
        **_policy(
            cleanup_key,
            key_id="cleanup-key",
            identity="cleanup-operator@example.test",
            domain=CLEANUP_AUTHORIZATION_DOMAIN,
            role="deployment-cleanup-operator",
        ),
    }
    _install_production_authorities(monkeypatch, authorities)
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")
    monkeypatch.setattr(ledger, "_clock", lambda: NOW)
    strong_permit = ledger.reserve_provisioning_before_post(
        authorization=authorization,
        expected=expected,
        pricing_evidence_bytes=canonical_json_bytes(pricing_content),
        pricing_approval=pricing,
        provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
        provider_cap_approval=cap,
    )
    weak_permit = ledger.reserve_provisioning_before_post(
        authorization=weak_authorization,
        expected=weak_expected,
        pricing_evidence_bytes=canonical_json_bytes(weak_pricing_content),
        pricing_approval=weak_pricing,
        provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
        provider_cap_approval=cap,
    )
    strong_suffix = deterministic_deployment_suffix(
        expected.run_identity,
        expected.operation_id,
        OWNERSHIP_NONCE,
    )
    strong_manifest = _manifest(
        deployed_model=f"{expected.base_model}-{strong_suffix}",
    )
    receipt = _receipt(
        strong_manifest,
        deployed_model=strong_manifest.deployed_model,
    )
    weak_suffix = deterministic_deployment_suffix(
        expected.run_identity,
        weak_expected.operation_id,
        OWNERSHIP_NONCE,
    )
    weak_manifest = _manifest(
        deployed_model=f"deepseek-v4-flash-{weak_suffix}",
        base_model="deepseek-v4-flash",
        operation_marker=deterministic_operation_marker(
            expected.run_identity,
            weak_expected.operation_id,
            OWNERSHIP_NONCE,
        ),
        deployment_suffix=weak_suffix,
    )
    weak_receipt = _receipt(
        weak_manifest,
        operation_id="op-weak-031",
        infrastructure_reserve_id="infra-weak-031",
        base_model="deepseek-v4-flash",
        deployed_model=weak_manifest.deployed_model,
        operation_marker=weak_manifest.operation_marker,
        deployment_suffix=weak_manifest.deployment_suffix,
    )
    strong_plan = ModelRolePlan(
        provider="bailian",
        model_id=receipt.content.deployed_model,
        immutable_deployment_id=receipt.content.deployed_model,
        protocol="https",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        provider_policy="bailian-deployment-detail-v1",
        credential_env_name="HARNESS_DASHSCOPE_API_KEY",
    )
    weak_plan = strong_plan.model_copy(
        update={
            "model_id": weak_receipt.content.deployed_model,
            "immutable_deployment_id": weak_receipt.content.deployed_model,
        }
    )
    pricing_capability = verify_pricing_evidence(
        canonical_json_bytes(pricing_content),
        envelope=pricing,
        trusted_authorities=authorities,
        expected_scope="goldenset-production",
        now=NOW,
        fixed_duration_seconds=8 * 3600,
        cost_window_start=NOW,
    )
    strong_rate = derive_role_rate_from_pricing(
        pricing_capability,
        role_plan=strong_plan,
        expected_provider="bailian",
        expected_currency="CNY",
    )
    weak_rate = RoleRate(
        model_role_identity_hash=model_role_budget_identity_hash(weak_plan),
        input_cost_per_million_minor_units=240,
        output_cost_per_million_minor_units=960,
    )
    cap_attestation = ProviderSpendCapAttestation(
        provider="bailian",
        workspace_ref=cap_content.workspace_ref,
        project_ref="sha256:" + SHA_A,
        credential_ref="sha256:" + SHA_B,
        evidence_digest=cap.payload.evidence_digest,
        max_cost_minor_units=20_000,
        observed_at=cap_content.observed_at,
        expires_at=cap_content.expires_at,
    )
    contract = BudgetContract(
        currency="CNY",
        price_snapshot_id=pricing.payload.evidence_digest,
        price_observed_at=NOW,
        price_expires_at=pricing_content.effective_until,
        ceiling=BudgetAmounts(input_tokens=0, output_tokens=0, cost_minor_units=20_000),
        role_rates={
            "annotator": strong_rate,
            "judge": strong_rate,
            "weak_extractor": weak_rate,
        },
        provider_attestation=cap_attestation,
        product_reserves=(),
    )
    plan = RunAdmissionPlanPayload(
        run_identity=expected.run_identity,
        purpose=expected.purpose,
        model_roles={
            "annotator": strong_plan,
            "judge": strong_plan,
            "weak_extractor": weak_plan,
        },
        budget_contract_hash=budget_contract_hash(contract),
    )
    expected_strong_receipt = receipt
    expected_weak_receipt = weak_receipt
    operation_root = tmp_path / "operation-store"
    receipt, receipt_capability = _controller_issued_production_receipt(
        monkeypatch,
        ledger_path=tmp_path / "budget.sqlite3",
        operation_root=operation_root,
        plan=plan,
        authorization=authorization,
        permit=strong_permit,
        manifest=strong_manifest,
    )
    weak_receipt, weak_receipt_capability = _controller_issued_production_receipt(
        monkeypatch,
        ledger_path=tmp_path / "budget.sqlite3",
        operation_root=operation_root,
        plan=plan,
        authorization=weak_authorization,
        permit=weak_permit,
        manifest=weak_manifest,
    )
    assert receipt == expected_strong_receipt
    assert weak_receipt == expected_weak_receipt
    monkeypatch.setattr(
        "insurance_harness.goldenset.admission_budget._PRODUCTION_DEPLOYMENT_OPERATION_ROOT",
        tmp_path / "missing-operation-store",
        raising=False,
    )
    budget_payload = BudgetApprovalPayload(
        plan_payload_hash=plan_payload_hash(plan),
        run_identity=plan.run_identity,
        purpose=plan.purpose,
        scope="goldenset-production",
        approver_identity="finance-owner@example.test",
        approver_role="budget_approver",
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=30),
        budget_entries=(
            BudgetApprovalEntry(
                currency="CNY",
                max_input_tokens=0,
                max_output_tokens=0,
                max_cost_minor_units=20_000,
                budget_contract_hash=budget_contract_hash(contract),
            ),
        ),
    )
    budget_envelope = BudgetApprovalEnvelope(
        domain="budget",
        key_id="finance-key",
        payload=budget_payload,
        signature=base64.b64encode(
            finance_key.sign(approval_signed_bytes("budget", budget_payload))
        ).decode("ascii"),
    )
    malicious_rate = strong_rate.model_copy(update={"input_cost_per_million_minor_units": 1})
    malicious_contract = contract.model_copy(
        update={
            "role_rates": {
                "annotator": malicious_rate,
                "judge": malicious_rate,
                "weak_extractor": weak_rate,
            }
        }
    )
    malicious_plan = plan.model_copy(
        update={"budget_contract_hash": budget_contract_hash(malicious_contract)}
    )
    malicious_budget_payload = budget_payload.model_copy(
        update={
            "plan_payload_hash": plan_payload_hash(malicious_plan),
            "budget_entries": (
                budget_payload.budget_entries[0].model_copy(
                    update={"budget_contract_hash": budget_contract_hash(malicious_contract)}
                ),
            ),
        }
    )
    malicious_budget_envelope = BudgetApprovalEnvelope(
        domain="budget",
        key_id="finance-key",
        payload=malicious_budget_payload,
        signature=base64.b64encode(
            finance_key.sign(approval_signed_bytes("budget", malicious_budget_payload))
        ).decode("ascii"),
    )
    monkeypatch.setattr(
        ledger,
        "_bind_final_infrastructure_contract_for_testing",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("production bind used private testing seam")
        ),
    )

    with pytest.raises(
        BudgetLedgerError,
        match="^atomic production topology binding is required$",
    ):
        ledger.bind_final_infrastructure_contract(
            reserve_id=expected.infrastructure_reserve_id,
            authorization=authorization,
            expected_authorization=expected,
            receipt_capability=receipt_capability,
            roles=("annotator", "judge"),
            plan=malicious_plan,
            contract=malicious_contract,
            envelope=malicious_budget_envelope,
            expected_scope="goldenset-production",
            pricing_evidence_bytes=canonical_json_bytes(pricing_content),
            pricing_approval=pricing,
            provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
            provider_cap_approval=cap,
        )
    assert ledger.infrastructure_reserve(expected.infrastructure_reserve_id).state == ("reserved")

    strong_binding = FinalInfrastructureBindingRequest(
        reserve_id=expected.infrastructure_reserve_id,
        authorization=authorization,
        expected_authorization=expected,
        receipt_capability=receipt_capability,
        roles=("annotator", "judge"),
        pricing_evidence_bytes=canonical_json_bytes(pricing_content),
        pricing_approval=pricing,
        provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
        provider_cap_approval=cap,
    )
    weak_binding = FinalInfrastructureBindingRequest(
        reserve_id=weak_expected.infrastructure_reserve_id,
        authorization=weak_authorization,
        expected_authorization=weak_expected,
        receipt_capability=weak_receipt_capability,
        roles=("weak_extractor",),
        pricing_evidence_bytes=canonical_json_bytes(weak_pricing_content),
        pricing_approval=weak_pricing,
        provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
        provider_cap_approval=cap,
    )
    with pytest.raises(BudgetLedgerError, match="receipt artifact"):
        ledger.bind_final_infrastructure_topology(
            strong=strong_binding,
            weak=weak_binding,
            plan=plan,
            contract=contract,
            envelope=budget_envelope,
            expected_scope="goldenset-production",
        )
    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        assert connection.execute(
            "SELECT state FROM infrastructure_reserves ORDER BY reserve_id"
        ).fetchall() == [("reserved",), ("reserved",)]
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM deployment_role_bindings").fetchone() == (
            0,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM final_infrastructure_topologies"
        ).fetchone() == (0,)

    monkeypatch.setattr(
        "insurance_harness.goldenset.admission_budget._PRODUCTION_DEPLOYMENT_OPERATION_ROOT",
        operation_root,
        raising=False,
    )
    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        connection.execute(
            """CREATE TRIGGER fail_weak_receipt_annex
               BEFORE INSERT ON final_topology_receipt_annexes
               WHEN NEW.reserve_id='infra-weak-031'
               BEGIN SELECT RAISE(FAIL, 'forced weak annex failure'); END"""
        )
    with pytest.raises(BudgetLedgerError, match="topology bind failed"):
        ledger.bind_final_infrastructure_topology(
            strong=strong_binding,
            weak=weak_binding,
            plan=plan,
            contract=contract,
            envelope=budget_envelope,
            expected_scope="goldenset-production",
        )
    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        assert connection.execute(
            "SELECT state FROM infrastructure_reserves ORDER BY reserve_id"
        ).fetchall() == [("reserved",), ("reserved",)]
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM deployment_role_bindings").fetchone() == (
            0,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM final_topology_receipt_annexes"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM final_infrastructure_topologies"
        ).fetchone() == (0,)
        connection.execute("DROP TRIGGER fail_weak_receipt_annex")
    with pytest.raises(BudgetLedgerError, match="signed evidence rejected"):
        ledger.bind_final_infrastructure_topology(
            strong=strong_binding,
            weak=replace(weak_binding, pricing_evidence_bytes=b"{}"),
            plan=plan,
            contract=contract,
            envelope=budget_envelope,
            expected_scope="goldenset-production",
        )
    assert ledger.infrastructure_reserve("infra-strong-031").state == "reserved"
    assert ledger.infrastructure_reserve("infra-weak-031").state == "reserved"

    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        connection.execute(
            """CREATE TRIGGER fail_public_weak_bind
               BEFORE UPDATE ON infrastructure_reserves
               WHEN NEW.reserve_id='infra-weak-031' AND NEW.state='bound'
               BEGIN SELECT RAISE(ABORT, 'simulated public weak bind crash'); END"""
        )
    with pytest.raises(BudgetLedgerError, match="topology bind failed"):
        ledger.bind_final_infrastructure_topology(
            strong=strong_binding,
            weak=weak_binding,
            plan=plan,
            contract=contract,
            envelope=budget_envelope,
            expected_scope="goldenset-production",
        )
    assert ledger.infrastructure_reserve("infra-strong-031").state == "reserved"
    assert ledger.infrastructure_reserve("infra-weak-031").state == "reserved"
    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM deployment_role_bindings").fetchone() == (
            0,
        )
        connection.execute("DROP TRIGGER fail_public_weak_bind")

    monkeypatch.setattr(
        "insurance_harness.goldenset.admission_cli._load_deployment_approval_configuration",
        lambda: (authorities, frozenset(), frozenset(), frozenset()),
    )
    with pytest.raises(BudgetLedgerError, match="signed|role|approval"):
        ledger.bind_final_infrastructure_topology(
            strong=strong_binding,
            weak=weak_binding,
            plan=plan,
            contract=contract,
            envelope=budget_envelope,
            expected_scope="goldenset-production",
        )
    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        assert connection.execute(
            "SELECT state FROM infrastructure_reserves ORDER BY reserve_id"
        ).fetchall() == [("reserved",), ("reserved",)]
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM deployment_role_bindings").fetchone() == (
            0,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM final_infrastructure_topologies"
        ).fetchone() == (0,)

    _install_production_authorities(monkeypatch, authorities)
    mutable_now = {"value": NOW}
    monkeypatch.setattr(ledger, "_clock", lambda: mutable_now["value"])
    original_mutation = ledger._mutation

    @contextmanager
    def expire_after_lock() -> Any:
        with original_mutation() as connection:
            mutable_now["value"] = NOW + timedelta(hours=2)
            yield connection

    monkeypatch.setattr(ledger, "_mutation", expire_after_lock)
    with pytest.raises(BudgetLedgerError, match="expired|stale|fresh|signed"):
        ledger.bind_final_infrastructure_topology(
            strong=strong_binding,
            weak=weak_binding,
            plan=plan,
            contract=contract,
            envelope=budget_envelope,
            expected_scope="goldenset-production",
        )
    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        assert connection.execute(
            "SELECT state FROM infrastructure_reserves ORDER BY reserve_id"
        ).fetchall() == [("reserved",), ("reserved",)]
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM deployment_role_bindings").fetchone() == (
            0,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM final_infrastructure_topologies"
        ).fetchone() == (0,)

    monkeypatch.setattr(ledger, "_mutation", original_mutation)
    monkeypatch.setattr(ledger, "_clock", lambda: NOW)

    workspace_b_contract = contract.model_copy(
        update={
            "provider_attestation": contract.provider_attestation.model_copy(
                update={"workspace_ref": "workspace-other-031"}
            )
        }
    )
    workspace_b_plan = plan.model_copy(
        update={"budget_contract_hash": budget_contract_hash(workspace_b_contract)}
    )
    workspace_b_payload = budget_payload.model_copy(
        update={
            "plan_payload_hash": plan_payload_hash(workspace_b_plan),
            "budget_entries": (
                budget_payload.budget_entries[0].model_copy(
                    update={"budget_contract_hash": budget_contract_hash(workspace_b_contract)}
                ),
            ),
        }
    )
    workspace_b_envelope = BudgetApprovalEnvelope(
        domain="budget",
        key_id="finance-key",
        payload=workspace_b_payload,
        signature=base64.b64encode(
            finance_key.sign(approval_signed_bytes("budget", workspace_b_payload))
        ).decode("ascii"),
    )
    db_before_workspace_mismatch = (tmp_path / "budget.sqlite3").read_bytes()
    with pytest.raises(BudgetLedgerError, match="provider.*resource"):
        ledger.bind_final_infrastructure_topology(
            strong=strong_binding,
            weak=weak_binding,
            plan=workspace_b_plan,
            contract=workspace_b_contract,
            envelope=workspace_b_envelope,
            expected_scope="goldenset-production",
        )
    assert (tmp_path / "budget.sqlite3").read_bytes() == db_before_workspace_mismatch

    fresh_reload_observations: list[tuple[int, int]] = []
    original_fresh_reload = ledger.require_fresh_final_topology

    def fresh_reload_after_commit(**kwargs: Any) -> Any:
        with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
            fresh_reload_observations.append(
                (
                    int(
                        connection.execute(
                            "SELECT COUNT(*) FROM final_topology_receipt_annexes"
                        ).fetchone()[0]
                    ),
                    int(
                        connection.execute(
                            "SELECT COUNT(*) FROM final_infrastructure_topologies"
                        ).fetchone()[0]
                    ),
                )
            )
        return original_fresh_reload(**kwargs)

    monkeypatch.setattr(ledger, "require_fresh_final_topology", fresh_reload_after_commit)
    bound = ledger.bind_final_infrastructure_topology(
        strong=strong_binding,
        weak=weak_binding,
        plan=plan,
        contract=contract,
        envelope=budget_envelope,
        expected_scope="goldenset-production",
    )
    cleanup_binding = ledger.infrastructure_cleanup_binding("infra-strong-031")
    assert type(cleanup_binding) is InfrastructureCleanupBinding
    assert cleanup_binding.receipt_digest == receipt.content_digest
    assert cleanup_binding.remote_manifest_digest == provider_manifest_digest(strong_manifest)
    assert cleanup_binding.reconciliation_digest == receipt_capability.reconciliation_digest
    assert (
        cleanup_binding.transport_identity_digest
        == receipt_capability.transport_identity_digest
    )
    assert cleanup_binding.scope == expected.scope

    if forgery == "issuer":
        selected_receipt = receipt if deployment_key == "strong" else weak_receipt
        selected_manifest = (
            strong_manifest if deployment_key == "strong" else weak_manifest
        )
        selected_binding = ledger.infrastructure_cleanup_binding(
            selected_receipt.content.infrastructure_reserve_id
        )
        remote: dict[str, ProviderDeploymentManifest | None] = {
            "manifest": selected_manifest
        }
        provider_methods: list[str] = []

        def cleanup_detail(
            _transport: BailianDeploymentHTTPTransport,
            *,
            deployed_model: str,
        ) -> bytes:
            provider_methods.append("GET")
            assert deployed_model == selected_binding.deployed_model
            current = remote["manifest"]
            if current is None:
                raise DeploymentNotFound("absent")
            return canonical_json_bytes(current)

        def cleanup_delete(
            _transport: BailianDeploymentHTTPTransport,
            *,
            deployed_model: str,
        ) -> bytes:
            provider_methods.append("DELETE")
            assert deployed_model == selected_binding.deployed_model
            remote["manifest"] = None
            return b"{}"

        monkeypatch.setattr(
            BailianDeploymentHTTPTransport,
            "deployment_detail",
            cleanup_detail,
        )
        monkeypatch.setattr(
            BailianDeploymentHTTPTransport,
            "delete_deployment",
            cleanup_delete,
        )
        database_before_cleanup = (tmp_path / "budget.sqlite3").read_bytes()
        cleanup_controller = DeploymentController.for_production_cleanup(
            reserve_id=selected_binding.reserve_id
        )
        cleanup_controller._clock = lambda: NOW
        try:
            cleanup_result = cleanup_controller.cleanup(
                authorization=_c4_cleanup_authorization(
                    cleanup_key,
                    selected_binding,
                ),
                receipt_digest=selected_binding.receipt_digest,
            )
        finally:
            cleanup_controller.close()
        assert cleanup_result.receipt.terminal_state == "absent_404"
        assert provider_methods == ["GET", "DELETE", "GET"]
        assert (tmp_path / "budget.sqlite3").read_bytes() == database_before_cleanup

    if forgery == "cleanup_binding_topology":
        topology_tables = (
            "infrastructure_reserves",
            "infrastructure_authorizations",
            "deployment_role_bindings",
            "final_topology_receipt_annexes",
            "final_infrastructure_topologies",
        )

        def topology_state() -> dict[str, list[tuple[Any, ...]]]:
            with sqlite3.connect(tmp_path / "budget.sqlite3") as state_connection:
                return {
                    table: state_connection.execute(
                        f"SELECT * FROM {table} ORDER BY rowid"
                    ).fetchall()
                    for table in topology_tables
                }

        with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
            original_row = connection.execute(
                """SELECT account_id,strong_reserve_id,weak_reserve_id,
                          topology_json,topology_digest
                   FROM final_infrastructure_topologies"""
            ).fetchone()
        assert original_row is not None
        account_id, strong_reserve_id, weak_reserve_id, topology_json, topology_digest = (
            original_row
        )
        original_payload = json.loads(bytes(topology_json))
        with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
            authorization_digest, authorization_envelope = connection.execute(
                """SELECT a.authorization_digest,a.envelope_json
                   FROM infrastructure_authorizations AS a
                   JOIN infrastructure_reserves AS r
                     ON r.authorization_digest=a.authorization_digest
                   WHERE r.reserve_id='infra-strong-031'"""
            ).fetchone()

        for mutation in (
            "authorization_envelope_noncanonical",
            "authorization_digest",
            "authorization_payload",
            "topology_digest",
            "row_reserve_ids",
            "noncanonical_topology_json",
            "plan_run_identity",
            "plan_purpose",
            "expected_scope",
            "pricing_evidence_digest",
            "pricing_approval_digest",
            "provider_cap_evidence_digest",
            "provider_cap_approval_digest",
            "roles",
            "receipt_annex_digest",
            "reconciliation_digest",
        ):
            with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
                connection.execute(
                    """UPDATE final_infrastructure_topologies
                       SET strong_reserve_id=?,weak_reserve_id=?,topology_json=?,topology_digest=?
                       WHERE account_id=?""",
                    (
                        strong_reserve_id,
                        weak_reserve_id,
                        topology_json,
                        topology_digest,
                        account_id,
                    ),
                )
                connection.execute(
                    """UPDATE infrastructure_authorizations
                       SET authorization_digest=?,envelope_json=?
                       WHERE reserve_id='infra-strong-031'""",
                    (authorization_digest, authorization_envelope),
                )
                connection.execute(
                    """UPDATE infrastructure_reserves SET authorization_digest=?
                       WHERE reserve_id='infra-strong-031'""",
                    (authorization_digest,),
                )
                if mutation == "authorization_envelope_noncanonical":
                    connection.execute(
                        """UPDATE infrastructure_authorizations SET envelope_json=?
                           WHERE authorization_digest=?""",
                        (
                            json.dumps(
                                json.loads(bytes(authorization_envelope)),
                                indent=2,
                                sort_keys=True,
                            ).encode("utf-8"),
                            authorization_digest,
                        ),
                    )
                elif mutation == "authorization_digest":
                    mutated_authorization = json.loads(bytes(authorization_envelope))
                    mutated_authorization["signature"] += "A"
                    connection.execute(
                        """UPDATE infrastructure_authorizations SET envelope_json=?
                           WHERE authorization_digest=?""",
                        (canonical_json_bytes(mutated_authorization), authorization_digest),
                    )
                elif mutation == "authorization_payload":
                    mutated_authorization = json.loads(bytes(authorization_envelope))
                    mutated_authorization["payload"]["cleanup_deadline"] = (
                        NOW + timedelta(hours=7)
                    ).isoformat()
                    mutated_payload = ProvisioningAuthorizationPayload.model_validate(
                        mutated_authorization["payload"]
                    )
                    changed_authorization = ProvisioningAuthorization(
                        domain=PROVISIONING_AUTHORIZATION_DOMAIN,
                        key_id=str(mutated_authorization["key_id"]),
                        payload=mutated_payload,
                        signature=base64.b64encode(
                            provision_key.sign(
                                authorization_signed_bytes(
                                    PROVISIONING_AUTHORIZATION_DOMAIN,
                                    mutated_payload,
                                )
                            )
                        ).decode("ascii"),
                    )
                    changed_digest = infrastructure_authorization_digest(
                        changed_authorization
                    )
                    connection.execute(
                        """UPDATE infrastructure_authorizations
                           SET authorization_digest=?,envelope_json=?
                           WHERE reserve_id='infra-strong-031'""",
                        (
                            changed_digest,
                            canonical_json_bytes(changed_authorization),
                        ),
                    )
                    connection.execute(
                        """UPDATE infrastructure_reserves SET authorization_digest=?
                           WHERE reserve_id='infra-strong-031'""",
                        (changed_digest,),
                    )
                elif mutation == "topology_digest":
                    connection.execute(
                        "UPDATE final_infrastructure_topologies SET topology_digest=?",
                        ("0" * 64,),
                    )
                elif mutation == "row_reserve_ids":
                    connection.execute(
                        """UPDATE final_infrastructure_topologies
                           SET strong_reserve_id=?,weak_reserve_id=?""",
                        (weak_reserve_id, strong_reserve_id),
                    )
                else:
                    mutated_payload = copy.deepcopy(original_payload)
                    if mutation == "noncanonical_topology_json":
                        mutated_json = json.dumps(
                            mutated_payload,
                            indent=2,
                            sort_keys=True,
                        ).encode("utf-8")
                    else:
                        if mutation == "plan_run_identity":
                            mutated_payload["plan"]["run_identity"] = "other-run-031"
                        elif mutation == "plan_purpose":
                            mutated_payload["plan"]["purpose"] = "other purpose"
                        elif mutation == "expected_scope":
                            mutated_payload["expected_scope"] = "other-scope"
                        elif mutation == "pricing_evidence_digest":
                            mutated_payload["strong"]["pricing_evidence_json"] = (
                                mutated_payload["weak"]["pricing_evidence_json"]
                            )
                        elif mutation == "pricing_approval_digest":
                            mutated_payload["strong"]["pricing_approval"]["signature"] += "A"
                        elif mutation == "provider_cap_evidence_digest":
                            mutated_payload["provider_cap_evidence_json"] = json.dumps(
                                json.loads(mutated_payload["provider_cap_evidence_json"]),
                                indent=2,
                                sort_keys=True,
                            )
                        elif mutation == "provider_cap_approval_digest":
                            mutated_payload["provider_cap_approval"]["signature"] += "A"
                        elif mutation == "roles":
                            mutated_payload["strong"]["roles"] = ["annotator"]
                        elif mutation == "receipt_annex_digest":
                            mutated_payload["strong"]["receipt_annex_digest"] = "0" * 64
                        else:
                            mutated_payload["strong"]["reconciliation_digest"] = "0" * 64
                        mutated_json = canonical_json_bytes(mutated_payload)
                    mutated_digest = hashlib.sha256(
                        b"insurancekb.run-admission.final-topology.v1\0" + mutated_json
                    ).hexdigest()
                    connection.execute(
                        """UPDATE final_infrastructure_topologies
                           SET topology_json=?,topology_digest=?""",
                        (mutated_json, mutated_digest),
                    )
            before_rejected_binding = topology_state()
            with pytest.raises(BudgetLedgerError, match="topology|cleanup|drift|bound"):
                ledger.infrastructure_cleanup_binding("infra-strong-031")
            assert topology_state() == before_rejected_binding

        with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
            connection.execute(
                """UPDATE final_infrastructure_topologies
                   SET strong_reserve_id=?,weak_reserve_id=?,topology_json=?,topology_digest=?
                   WHERE account_id=?""",
                (
                    strong_reserve_id,
                    weak_reserve_id,
                    topology_json,
                    topology_digest,
                    account_id,
                ),
            )
        assert ledger.infrastructure_cleanup_binding("infra-strong-031") == cleanup_binding
        return

    assert type(bound).__name__ == "VerifiedFinalTopology"
    assert fresh_reload_observations == [(2, 1)]
    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        annex_rows_before_replay = connection.execute(
            """SELECT annex_digest,reserve_id,receipt_digest,artifact_json
               FROM final_topology_receipt_annexes ORDER BY reserve_id"""
        ).fetchall()
        durable_topology = json.loads(
            bytes(
                connection.execute(
                    "SELECT topology_json FROM final_infrastructure_topologies"
                ).fetchone()[0]
            )
        )
    assert {
        durable_topology["strong"]["receipt_annex_digest"],
        durable_topology["weak"]["receipt_annex_digest"],
    } == {str(row[0]) for row in annex_rows_before_replay}
    assert "receipt" not in durable_topology["strong"]
    assert "receipt" not in durable_topology["weak"]

    if deployment_key == "strong" and forgery == "issuer":
        original_connect = ledger._connect
        current = [NOW]

        class _CrossExpiryConnection:
            def __init__(self, connection: sqlite3.Connection) -> None:
                self._connection = connection
                self._advanced = False

            def execute(self, sql: str, parameters: Any = ()) -> Any:
                if not self._advanced and sql.lstrip().upper().startswith("SELECT"):
                    current[0] = bound.valid_until
                    self._advanced = True
                return self._connection.execute(sql, parameters)

            def __getattr__(self, name: str) -> Any:
                return getattr(self._connection, name)

        with monkeypatch.context() as blocked_select:
            blocked_select.setattr(ledger, "_clock", lambda: current[0])
            blocked_select.setattr(
                ledger,
                "_connect",
                lambda: _CrossExpiryConnection(original_connect()),
            )
            with pytest.raises(BudgetLedgerError, match="expired|stale|invalid"):
                ledger.require_fresh_final_topology(
                    plan=plan,
                    expected_scope="goldenset-production",
                )

        trusted_configuration = admission_cli._load_deployment_approval_configuration()
        root_available = [True]

        class _RootRotatingConnection:
            def __init__(self, connection: sqlite3.Connection) -> None:
                self._connection = connection

            def execute(self, sql: str, parameters: Any = ()) -> Any:
                return self._connection.execute(sql, parameters)

            def commit(self) -> None:
                self._connection.commit()
                root_available[0] = False

            def __getattr__(self, name: str) -> Any:
                return getattr(self._connection, name)

        with monkeypatch.context() as rotated_root:
            rotated_root.setattr(
                admission_cli,
                "_load_deployment_approval_configuration",
                lambda: trusted_configuration
                if root_available[0]
                else ({}, frozenset(), frozenset(), frozenset()),
            )
            rotated_root.setattr(
                ledger,
                "_connect",
                lambda: _RootRotatingConnection(original_connect()),
            )
            with pytest.raises(BudgetLedgerError, match="trust|authority|configuration|invalid"):
                ledger.require_fresh_final_topology(
                    plan=plan,
                    expected_scope="goldenset-production",
                )

    replayed_topology = ledger.require_fresh_final_topology(
        plan=plan,
        expected_scope="goldenset-production",
    )
    assert replayed_topology.topology_digest == bound.topology_digest
    monkeypatch.setattr(ledger, "_clock", lambda: NOW + timedelta(seconds=1))
    delayed_replay = ledger.bind_final_infrastructure_topology(
        strong=strong_binding,
        weak=weak_binding,
        plan=plan,
        contract=contract,
        envelope=budget_envelope,
        expected_scope="goldenset-production",
    )
    assert delayed_replay.topology_digest == bound.topology_digest
    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        assert (
            connection.execute(
                """SELECT annex_digest,reserve_id,receipt_digest,artifact_json
               FROM final_topology_receipt_annexes ORDER BY reserve_id"""
            ).fetchall()
            == annex_rows_before_replay
        )

    after_initial_reconciliation_ttl = NOW + timedelta(minutes=5, seconds=1)
    monkeypatch.setattr(ledger, "_clock", lambda: after_initial_reconciliation_ttl)
    static_topology = ledger.require_fresh_final_topology(
        plan=plan,
        expected_scope="goldenset-production",
    )
    assert static_topology.topology_digest == bound.topology_digest
    assert static_topology.valid_until > after_initial_reconciliation_ttl
    with pytest.raises(BudgetLedgerError, match="issuer snapshot"):
        require_verified_final_topology(
            copy.copy(static_topology),
            now=after_initial_reconciliation_ttl,
            expected_plan_payload_hash=plan_payload_hash(plan),
            expected_scope="goldenset-production",
        )
    topology_capability = ledger.require_fresh_topology_provider_capability(
        plan=plan,
        expected_scope="goldenset-production",
        reserve_id=static_topology.strong.reserve_id,
    )
    with pytest.raises(AuthorizationVerificationError, match="issuer|snapshot"):
        require_verified_topology_provider_capability(copy.copy(topology_capability))
    fresh_provider_cap = ledger.require_fresh_provider_capability(
        plan=plan,
        expected_scope="goldenset-production",
    )
    verified_fresh_cap = require_verified_provider_capability(fresh_provider_cap)
    assert verified_fresh_cap.evidence_digest == static_topology.provider_cap_evidence_digest
    assert verified_fresh_cap.approval_digest == static_topology.provider_cap_approval_digest
    assert verified_fresh_cap.workspace_ref == static_topology.workspace_ref
    assert verified_fresh_cap.project_ref == static_topology.project_ref
    assert verified_fresh_cap.credential_ref == static_topology.credential_ref
    assert verified_fresh_cap.currency == static_topology.currency
    assert verified_fresh_cap.coverage == static_topology.provider_cap_coverage
    assert (
        verified_fresh_cap.max_cost_minor_units == static_topology.provider_cap_max_cost_minor_units
    )
    assert verified_fresh_cap.expires_at == static_topology.provider_cap_expires_at

    provider_loader_failures: list[str] = []
    original_connect = ledger._connect
    with monkeypatch.context() as blocked_select:
        current = [after_initial_reconciliation_ttl]

        class _ProviderCapCrossExpiryConnection:
            def __init__(self, connection: sqlite3.Connection) -> None:
                self._connection = connection
                self._advanced = False

            def execute(self, sql: str, parameters: Any = ()) -> Any:
                result = self._connection.execute(sql, parameters)
                if (
                    not self._advanced
                    and "FROM final_infrastructure_topologies" in sql
                ):
                    current[0] = static_topology.provider_cap_expires_at
                    self._advanced = True
                return result

            def __getattr__(self, name: str) -> Any:
                return getattr(self._connection, name)

        blocked_select.setattr(
            ledger,
            "require_fresh_final_topology",
            lambda **_kwargs: static_topology,
        )
        blocked_select.setattr(ledger, "_clock", lambda: current[0])
        blocked_select.setattr(
            ledger,
            "_connect",
            lambda: _ProviderCapCrossExpiryConnection(original_connect()),
        )
        try:
            ledger.require_fresh_provider_capability(
                plan=plan,
                expected_scope="goldenset-production",
            )
        except BudgetLedgerError:
            pass
        else:
            provider_loader_failures.append("blocked_select_crossed_expiry")

    trusted_configuration = admission_cli._load_deployment_approval_configuration()
    with monkeypatch.context() as rotated_provider_root:
        root_available = [True]

        class _ProviderCapRootRotatingConnection:
            def __init__(self, connection: sqlite3.Connection) -> None:
                self._connection = connection

            def commit(self) -> None:
                self._connection.commit()
                root_available[0] = False

            def __getattr__(self, name: str) -> Any:
                return getattr(self._connection, name)

        rotated_provider_root.setattr(
            ledger,
            "require_fresh_final_topology",
            lambda **_kwargs: static_topology,
        )
        rotated_provider_root.setattr(ledger, "_clock", lambda: NOW)
        rotated_provider_root.setattr(
            admission_cli,
            "_load_deployment_approval_configuration",
            lambda: trusted_configuration
            if root_available[0]
            else ({}, frozenset(), frozenset(), frozenset()),
        )
        rotated_provider_root.setattr(
            ledger,
            "_connect",
            lambda: _ProviderCapRootRotatingConnection(original_connect()),
        )
        try:
            ledger.require_fresh_provider_capability(
                plan=plan,
                expected_scope="goldenset-production",
            )
        except BudgetLedgerError:
            pass
        else:
            provider_loader_failures.append("commit_rotated_root")

    with monkeypatch.context() as authority_load_expiry:
        current = [
            static_topology.provider_cap_expires_at - timedelta(microseconds=1)
        ]
        authority_loads = 0

        def cross_expiry_during_final_authority_load() -> Any:
            nonlocal authority_loads
            authority_loads += 1
            if authority_loads == 2:
                current[0] = static_topology.provider_cap_expires_at
            return trusted_configuration

        authority_load_expiry.setattr(
            ledger,
            "require_fresh_final_topology",
            lambda **_kwargs: static_topology,
        )
        authority_load_expiry.setattr(ledger, "_clock", lambda: current[0])
        authority_load_expiry.setattr(
            admission_cli,
            "_load_deployment_approval_configuration",
            cross_expiry_during_final_authority_load,
        )
        try:
            ledger.require_fresh_provider_capability(
                plan=plan,
                expected_scope="goldenset-production",
            )
        except BudgetLedgerError:
            pass
        else:
            provider_loader_failures.append("authority_load_crossed_expiry")

    assert provider_loader_failures == []

    with monkeypatch.context() as advancing_provider_clock:
        current = [after_initial_reconciliation_ttl]

        def advance_between_fresh_loads() -> datetime:
            value = current[0]
            current[0] = value + timedelta(microseconds=1)
            return value

        advancing_provider_clock.setattr(ledger, "_clock", advance_between_fresh_loads)
        advancing_capability = ledger.require_fresh_provider_capability(
            plan=plan,
            expected_scope="goldenset-production",
        )
        assert (
            require_verified_provider_capability(advancing_capability).evidence_digest
            == static_topology.provider_cap_evidence_digest
        )

    monkeypatch.setattr(ledger, "_clock", lambda: NOW + timedelta(minutes=20, seconds=1))
    with pytest.raises(BudgetLedgerError, match="stale|expired"):
        ledger.require_fresh_provider_capability(
            plan=plan,
            expected_scope="goldenset-production",
        )
    monkeypatch.setattr(ledger, "_clock", lambda: NOW)

    testing_reader = BudgetLedger._for_testing(
        tmp_path / "budget.sqlite3",
        clock=lambda: NOW,
    )
    with pytest.raises(BudgetLedgerError, match="production ledger"):
        testing_reader.require_fresh_final_topology(
            plan=plan,
            expected_scope="goldenset-production",
        )
    with pytest.raises(BudgetLedgerError, match="production ledger"):
        testing_reader.require_fresh_provider_capability(
            plan=plan,
            expected_scope="goldenset-production",
        )
    with pytest.raises(BudgetLedgerError, match="caller-controlled"):
        ledger.require_fresh_provider_capability(
            plan=plan,
            expected_scope="goldenset-production",
            now=NOW,
        )

    db_path = tmp_path / "budget.sqlite3"
    workspace_b_approval_digest = _approval_digest(workspace_b_envelope)
    workspace_b_contract_digest = budget_contract_hash(workspace_b_contract)
    with sqlite3.connect(db_path) as connection:
        account_id = str(connection.execute("SELECT account_id FROM budget_accounts").fetchone()[0])
        original_account_approval_digest = str(
            connection.execute(
                "SELECT approval_digest FROM budget_accounts WHERE account_id=?",
                (account_id,),
            ).fetchone()[0]
        )
        original_approval_row = connection.execute(
            """SELECT approval_digest,plan_payload_hash,contract_hash,contract_json
               FROM budget_approvals WHERE account_id=? AND revision=1""",
            (account_id,),
        ).fetchone()
        assert original_approval_row is not None
        original_reserve_approvals = connection.execute(
            """SELECT reserve_id,final_approval_digest FROM infrastructure_reserves
               WHERE account_id=? ORDER BY reserve_id""",
            (account_id,),
        ).fetchall()
        original_topology_json, original_topology_digest = connection.execute(
            """SELECT topology_json,topology_digest
               FROM final_infrastructure_topologies"""
        ).fetchone()
        tampered_topology = json.loads(bytes(original_topology_json))
        tampered_topology["plan"] = workspace_b_plan.model_dump(mode="json")
        tampered_topology["contract"] = workspace_b_contract.model_dump(mode="json")
        tampered_topology["budget_envelope"] = workspace_b_envelope.model_dump(mode="json")
        tampered_topology_json = canonical_json_bytes(tampered_topology)
        tampered_topology_digest = hashlib.sha256(
            b"insurancekb.run-admission.final-topology.v1\0" + tampered_topology_json
        ).hexdigest()
        connection.execute(
            "UPDATE budget_accounts SET approval_digest=? WHERE account_id=?",
            (workspace_b_approval_digest, account_id),
        )
        connection.execute(
            """UPDATE budget_approvals
               SET approval_digest=?,plan_payload_hash=?,contract_hash=?,contract_json=?
               WHERE account_id=? AND revision=1""",
            (
                workspace_b_approval_digest,
                plan_payload_hash(workspace_b_plan),
                workspace_b_contract_digest,
                canonical_json_bytes(workspace_b_contract),
                account_id,
            ),
        )
        connection.execute(
            """UPDATE infrastructure_reserves SET final_approval_digest=?
               WHERE account_id=?""",
            (workspace_b_approval_digest, account_id),
        )
        connection.execute(
            """UPDATE final_infrastructure_topologies
               SET topology_json=?,topology_digest=? WHERE account_id=?""",
            (tampered_topology_json, tampered_topology_digest, account_id),
        )
    before_workspace_tamper_reload = db_path.read_bytes()
    with pytest.raises(BudgetLedgerError, match="provider.*resource"):
        ledger.require_fresh_final_topology(
            plan=workspace_b_plan,
            expected_scope="goldenset-production",
        )
    assert db_path.read_bytes() == before_workspace_tamper_reload
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE budget_accounts SET approval_digest=? WHERE account_id=?",
            (original_account_approval_digest, account_id),
        )
        connection.execute(
            """UPDATE budget_approvals
               SET approval_digest=?,plan_payload_hash=?,contract_hash=?,contract_json=?
               WHERE account_id=? AND revision=1""",
            (*original_approval_row, account_id),
        )
        connection.executemany(
            """UPDATE infrastructure_reserves SET final_approval_digest=?
               WHERE reserve_id=?""",
            (
                (str(final_approval_digest), str(reserve_id))
                for reserve_id, final_approval_digest in original_reserve_approvals
            ),
        )
        connection.execute(
            """UPDATE final_infrastructure_topologies
               SET topology_json=?,topology_digest=? WHERE account_id=?""",
            (original_topology_json, original_topology_digest, account_id),
        )
    with sqlite3.connect(db_path) as connection:
        original_topology_json, original_topology_digest = connection.execute(
            """SELECT topology_json,topology_digest
               FROM final_infrastructure_topologies"""
        ).fetchone()
        tampered = json.loads(bytes(original_topology_json))
        deployment = tampered[deployment_key]
        annex_row = connection.execute(
            """SELECT artifact_json FROM final_topology_receipt_annexes
               WHERE annex_digest=?""",
            (deployment["receipt_annex_digest"],),
        ).fetchone()
        assert annex_row is not None
        annex_payload = json.loads(bytes(annex_row[0]))
        receipt = annex_payload["receipt_artifact"]["receipt"]
        reconciliation_artifact = annex_payload["reconciliation_artifact"]
        content = receipt["content"]
        reconciliation_issuer = reconciliation_artifact["issuer"]
        transport_identity_digest = reconciliation_artifact["transport_identity_digest"]
        reconciliation_observed_at = reconciliation_artifact["observed_at"]
        reconciliation_expires_at = reconciliation_artifact["expires_at"]
        if forgery == "issuer":
            reconciliation_issuer = "caller-forged-controller-v1"
        elif forgery == "transport_identity_digest":
            transport_identity_digest = "f" * 64
        elif forgery == "invalid_window":
            reconciliation_expires_at = reconciliation_observed_at
        elif forgery == "future_window":
            reconciliation_observed_at = (
                (NOW + timedelta(seconds=2)).isoformat().replace("+00:00", "Z")
            )
            reconciliation_expires_at = (
                (NOW + timedelta(seconds=3)).isoformat().replace("+00:00", "Z")
            )
        else:
            reconciliation_observed_at = (
                (NOW - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
            )
            reconciliation_expires_at = (
                (NOW + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
            )
        reconciliation_facts = {
            "issuer": reconciliation_issuer,
            "transport_identity_digest": transport_identity_digest,
            "run_identity": plan.run_identity,
            "purpose": plan.purpose,
            "scope": "goldenset-production",
            "receipt_digest": receipt["content_digest"],
            "operation_id": content["operation_id"],
            "reserve_id": content["infrastructure_reserve_id"],
            "workspace_ref": content["workspace_ref"],
            "project_ref": content["project_ref"],
            "credential_ref": content["credential_ref"],
            "provider_cap_evidence_digest": cap.payload.evidence_digest,
            "provider_cap_approval_digest": provider_cap_approval_digest(cap),
            "remote_manifest_digest": content["remote_manifest_digest"],
            "observed_at": datetime.fromisoformat(
                reconciliation_observed_at.replace("Z", "+00:00")
            ),
            "expires_at": datetime.fromisoformat(reconciliation_expires_at.replace("Z", "+00:00")),
        }
        deployment["reconciliation_digest"] = hashlib.sha256(
            b"insurancekb.run-admission.receipt-reconciliation.v2\0"
            + canonical_json_bytes(reconciliation_facts)
        ).hexdigest()
        forged_topology_json = canonical_json_bytes(tampered)
        forged_topology_digest = hashlib.sha256(
            b"insurancekb.run-admission.final-topology.v1\0" + forged_topology_json
        ).hexdigest()
        connection.execute(
            """UPDATE final_infrastructure_topologies
               SET topology_json=?,topology_digest=?""",
            (forged_topology_json, forged_topology_digest),
        )
    before_rejected_read = db_path.read_bytes()
    with pytest.raises(
        BudgetLedgerError,
        match="reconciliation (?:artifact|provenance)",
    ):
        ledger.require_fresh_final_topology(
            plan=plan,
            expected_scope="goldenset-production",
        )
    assert db_path.read_bytes() == before_rejected_read

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """UPDATE final_infrastructure_topologies
               SET topology_json=?,topology_digest=?""",
            (original_topology_json, original_topology_digest),
        )

    if deployment_key == "strong" and forgery == "self_consistent_window":
        original_record = json.loads(bytes(original_topology_json))
        reconciliation_path = (
            tmp_path
            / "operation-store"
            / (f"{original_record['strong']['reconciliation_digest']}.receipt-reconciliation.json")
        )
        original_reconciliation_bytes = reconciliation_path.read_bytes()
        before_fixed_artifact_rejection = db_path.read_bytes()

        reconciliation_path.write_bytes(b"{}")
        reconciliation_path.chmod(0o600)
        with pytest.raises(BudgetLedgerError, match="reconciliation artifact"):
            ledger.require_fresh_final_topology(
                plan=plan,
                expected_scope="goldenset-production",
            )
        assert db_path.read_bytes() == before_fixed_artifact_rejection

        reconciliation_path.write_bytes(original_reconciliation_bytes)
        reconciliation_path.chmod(0o600)
        reconciliation_path.unlink()
        with pytest.raises(BudgetLedgerError, match="reconciliation artifact"):
            ledger.require_fresh_final_topology(
                plan=plan,
                expected_scope="goldenset-production",
            )
        assert db_path.read_bytes() == before_fixed_artifact_rejection
        reconciliation_path.write_bytes(original_reconciliation_bytes)
        reconciliation_path.chmod(0o600)

    with sqlite3.connect(db_path) as connection:
        original_annex = connection.execute(
            """SELECT annex_digest,artifact_json FROM final_topology_receipt_annexes
               WHERE reserve_id='infra-strong-031'"""
        ).fetchone()
        assert original_annex is not None
        tampered_artifact = b" " + bytes(original_annex[1])
        tampered_annex_digest = hashlib.sha256(
            b"insurancekb.run-admission.receipt-annex.v1\0" + tampered_artifact
        ).hexdigest()
        tampered_topology = json.loads(bytes(original_topology_json))
        tampered_topology["strong"]["receipt_annex_digest"] = tampered_annex_digest
        tampered_topology_json = canonical_json_bytes(tampered_topology)
        tampered_topology_digest = hashlib.sha256(
            b"insurancekb.run-admission.final-topology.v1\0" + tampered_topology_json
        ).hexdigest()
        connection.execute(
            """UPDATE final_topology_receipt_annexes
               SET annex_digest=?,artifact_json=?
               WHERE reserve_id='infra-strong-031'""",
            (tampered_annex_digest, tampered_artifact),
        )
        connection.execute(
            """UPDATE final_infrastructure_topologies
               SET topology_json=?,topology_digest=?""",
            (tampered_topology_json, tampered_topology_digest),
        )
    before_annex_rejected_read = db_path.read_bytes()
    with pytest.raises(BudgetLedgerError, match="receipt annex.*drifted"):
        ledger.require_fresh_final_topology(
            plan=plan,
            expected_scope="goldenset-production",
        )
    assert db_path.read_bytes() == before_annex_rejected_read
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """UPDATE final_topology_receipt_annexes
               SET annex_digest=?,artifact_json=?
               WHERE reserve_id='infra-strong-031'""",
            (str(original_annex[0]), bytes(original_annex[1])),
        )
        connection.execute(
            """UPDATE final_infrastructure_topologies
               SET topology_json=?,topology_digest=?""",
            (original_topology_json, original_topology_digest),
        )

    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        topology_json = bytes(
            connection.execute(
                "SELECT topology_json FROM final_infrastructure_topologies"
            ).fetchone()[0]
        )
        tampered = json.loads(topology_json)
        tampered["provider_cap_approval"]["signature"] = base64.b64encode(b"\0" * 64).decode(
            "ascii"
        )
        tampered_json = canonical_json_bytes(tampered)
        tampered_digest = hashlib.sha256(
            b"insurancekb.run-admission.final-topology.v1\0" + tampered_json
        ).hexdigest()
        connection.execute(
            """UPDATE final_infrastructure_topologies
               SET topology_json=?,topology_digest=?""",
            (tampered_json, tampered_digest),
        )
        before = tuple(
            connection.execute(
                "SELECT * FROM infrastructure_reserves ORDER BY reserve_id"
            ).fetchall()
        )
    with pytest.raises(BudgetLedgerError, match="signed durable"):
        ledger.require_fresh_final_topology(
            plan=plan,
            expected_scope="goldenset-production",
        )
    with pytest.raises(BudgetLedgerError, match="signed durable"):
        ledger.require_fresh_provider_capability(
            plan=plan,
            expected_scope="goldenset-production",
        )
    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        after = tuple(
            connection.execute(
                "SELECT * FROM infrastructure_reserves ORDER BY reserve_id"
            ).fetchall()
        )
    assert after == before


def test_o7_budget_ledger_rejects_caller_cost_before_any_reserve(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pricing_key = Ed25519PrivateKey.generate()
    cap_key = Ed25519PrivateKey.generate()
    provision_key = Ed25519PrivateKey.generate()
    pricing_content = _pricing_content()
    cap_content = _cap_content()
    pricing = _pricing_approval(pricing_key, pricing_content)
    cap = _cap_approval(cap_key, cap_content)
    expected, authorization = _provisioning_authorization(
        provision_key, pricing, cap, maximum_cost_minor_units=1
    )
    authorities = {
        **_policy(
            pricing_key,
            key_id="pricing-key",
            identity="pricing-owner@example.test",
            domain=PRICING_EVIDENCE_DOMAIN,
            role="pricing-evidence-approver",
        ),
        **_policy(
            cap_key,
            key_id="cap-key",
            identity="cap-attestor@example.test",
            domain=PROVIDER_CAP_DOMAIN,
            role="provider-cap-attestor",
        ),
        **_policy(
            provision_key,
            key_id="provisioning-key",
            identity="deployment-operator@example.test",
            domain=PROVISIONING_AUTHORIZATION_DOMAIN,
            role="deployment-provisioner",
        ),
    }
    _install_production_authorities(monkeypatch, authorities)
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")

    with pytest.raises(BudgetLedgerError, match="mechanical|price|cost"):
        ledger.reserve_provisioning_before_post(
            authorization=authorization,
            expected=expected,
            pricing_evidence_bytes=canonical_json_bytes(pricing_content),
            pricing_approval=pricing,
            provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
            provider_cap_approval=cap,
        )

    with pytest.raises(BudgetLedgerError, match="not found"):
        ledger.infrastructure_reserve("infra-strong-031")


def test_o7_production_budget_receipt_gate_rejects_private_test_issuer(
    tmp_path: Path,
) -> None:
    pricing_key = Ed25519PrivateKey.generate()
    cap_key = Ed25519PrivateKey.generate()
    provision_key = Ed25519PrivateKey.generate()
    pricing_content = _pricing_content()
    cap_content = _cap_content()
    pricing = _pricing_approval(pricing_key, pricing_content)
    cap = _cap_approval(cap_key, cap_content)
    receipt = _receipt()
    expected, _authorization = _provisioning_authorization(provision_key, pricing, cap)
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")
    before = (tmp_path / "budget.sqlite3").read_bytes()

    with pytest.raises(BudgetLedgerError, match="stale|invalid|production"):
        ledger._require_verified_receipt_for_authorization(
            _testing_receipt_capability(
                receipt,
                cap_digest=cap.payload.evidence_digest,
            ),
            expected,
            now=NOW,
        )
    assert (tmp_path / "budget.sqlite3").read_bytes() == before


def test_o7_t9_19_c4_real_c3_adoption_dual_bind_to_production_cleanup_e2e(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def ledger_rows(db_path: Path) -> tuple[tuple[str, tuple[tuple[object, ...], ...]], ...]:
        with sqlite3.connect(db_path) as connection:
            tables = tuple(
                str(row[0])
                for row in connection.execute(
                    """SELECT name FROM sqlite_master
                       WHERE type='table' AND name NOT LIKE 'sqlite_%'
                       ORDER BY name"""
                ).fetchall()
            )
            return tuple(
                (
                    table,
                    tuple(
                        tuple(row)
                        for row in connection.execute(
                            f'SELECT * FROM "{table}" ORDER BY rowid'
                        ).fetchall()
                    ),
                )
                for table in tables
            )

    case = _production_adoption_case(tmp_path, monkeypatch)
    strong_manifest = case.manifest
    strong_receipt = case.receipt
    weak_operation = "op-adopt-weak-031"
    weak_reserve = "infra-adopt-weak-031"
    weak_nonce = "6" * 32
    weak_suffix = deterministic_deployment_suffix(
        case.payload.run_identity,
        weak_operation,
        weak_nonce,
    )
    weak_manifest = strong_manifest.model_copy(
        update={
            "deployed_model": f"{strong_manifest.base_model}-{weak_suffix}",
            "ownership_nonce": weak_nonce,
            "operation_marker": deterministic_operation_marker(
                case.payload.run_identity,
                weak_operation,
                weak_nonce,
            ),
            "deployment_suffix": weak_suffix,
        }
    )
    weak_content = strong_receipt.content.model_copy(
        update={
            "operation_id": weak_operation,
            "infrastructure_reserve_id": weak_reserve,
            "deployed_model": weak_manifest.deployed_model,
            "operation_marker": weak_manifest.operation_marker,
            "deployment_suffix": weak_manifest.deployment_suffix,
            "remote_manifest_digest": provider_manifest_digest(weak_manifest),
        }
    )
    weak_receipt = DeploymentReceipt(
        content=weak_content,
        content_digest=deployment_receipt_content_digest(weak_content),
    )
    weak_payload = case.payload.model_copy(
        update={
            "operation_id": weak_operation,
            "infrastructure_reserve_id": weak_reserve,
            "deployed_model": weak_receipt.content.deployed_model,
            "receipt_digest": weak_receipt.content_digest,
            "gmt_create": weak_receipt.content.gmt_create,
        }
    )
    weak_authorization = ExistingDeploymentAdoptionAuthorization(
        domain=ADOPTION_AUTHORIZATION_DOMAIN,
        key_id="adoption-key",
        payload=weak_payload,
        signature=base64.b64encode(
            case.adoption_key.sign(
                authorization_signed_bytes(ADOPTION_AUTHORIZATION_DOMAIN, weak_payload)
            )
        ).decode("ascii"),
    )
    remotes: dict[str, ProviderDeploymentManifest | None] = {
        strong_manifest.deployed_model: strong_manifest,
        weak_manifest.deployed_model: weak_manifest,
    }
    provider_methods: list[tuple[str, str]] = []

    def detail(
        _transport: BailianDeploymentHTTPTransport,
        *,
        deployed_model: str,
    ) -> bytes:
        provider_methods.append(("GET", deployed_model))
        manifest = remotes[deployed_model]
        if manifest is None:
            raise DeploymentNotFound("absent")
        return canonical_json_bytes(manifest)

    def delete(
        _transport: BailianDeploymentHTTPTransport,
        *,
        deployed_model: str,
    ) -> bytes:
        provider_methods.append(("DELETE", deployed_model))
        remotes[deployed_model] = None
        return b"{}"

    monkeypatch.setattr(BailianDeploymentHTTPTransport, "deployment_detail", detail)
    monkeypatch.setattr(BailianDeploymentHTTPTransport, "delete_deployment", delete)
    strong_adopted = case.controller.reconcile_existing_adoption(
        authorization=case.authorization
    )
    weak_adopted = case.controller.reconcile_existing_adoption(
        authorization=weak_authorization
    )
    assert strong_adopted.receipt == strong_receipt
    assert weak_adopted.receipt == weak_receipt
    ledger = case.fixture.ledger
    strong_reserved = ledger.reserve_existing_adoption(
        authorization=case.authorization,
        expected=case.payload,
        receipt_capability=strong_adopted.receipt_capability,
        pricing_evidence_bytes=case.fixture.pricing_bytes,
        pricing_approval=case.fixture.pricing_approval,
        provider_cap_evidence_bytes=case.fixture.cap_bytes,
        provider_cap_approval=case.fixture.cap_approval,
    )
    weak_reserved = ledger.reserve_existing_adoption(
        authorization=weak_authorization,
        expected=weak_payload,
        receipt_capability=weak_adopted.receipt_capability,
        pricing_evidence_bytes=case.fixture.pricing_bytes,
        pricing_approval=case.fixture.pricing_approval,
        provider_cap_evidence_bytes=case.fixture.cap_bytes,
        provider_cap_approval=case.fixture.cap_approval,
    )
    strong_plan = ModelRolePlan(
        provider="bailian",
        model_id=strong_receipt.content.deployed_model,
        immutable_deployment_id=strong_receipt.content.deployed_model,
        protocol="https",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        provider_policy="bailian-deployment-detail-v1",
        credential_env_name="HARNESS_DASHSCOPE_API_KEY",
    )
    weak_plan = strong_plan.model_copy(
        update={
            "model_id": weak_receipt.content.deployed_model,
            "immutable_deployment_id": weak_receipt.content.deployed_model,
        }
    )
    verified_pricing = verify_pricing_evidence(
        case.fixture.pricing_bytes,
        envelope=case.fixture.pricing_approval,
        trusted_authorities=case.authorities,
        expected_scope=case.payload.scope,
        now=NOW,
        fixed_duration_seconds=9 * 3600,
        cost_window_start=strong_receipt.content.gmt_create,
        fixed_duration_segments_seconds=(3600, 8 * 3600),
    )
    strong_rate = derive_role_rate_from_pricing(
        verified_pricing,
        role_plan=strong_plan,
        expected_provider="bailian",
        expected_currency="CNY",
    )
    weak_rate = derive_role_rate_from_pricing(
        verified_pricing,
        role_plan=weak_plan,
        expected_provider="bailian",
        expected_currency="CNY",
    )
    cap_evidence = case.fixture.cap_approval.payload.evidence
    contract = BudgetContract(
        currency="CNY",
        price_snapshot_id=case.fixture.pricing_approval.payload.evidence_digest,
        price_observed_at=NOW,
        price_expires_at=case.fixture.pricing_approval.payload.evidence.effective_until,
        ceiling=BudgetAmounts(input_tokens=0, output_tokens=0, cost_minor_units=20_000),
        role_rates={
            "annotator": strong_rate,
            "judge": strong_rate,
            "weak_extractor": weak_rate,
        },
        provider_attestation=ProviderSpendCapAttestation(
            provider="bailian",
            workspace_ref=cap_evidence.workspace_ref,
            project_ref=cap_evidence.project_ref,
            credential_ref=cap_evidence.credential_ref,
            evidence_digest=case.fixture.cap_approval.payload.evidence_digest,
            max_cost_minor_units=cap_evidence.max_cost_minor_units,
            observed_at=cap_evidence.observed_at,
            expires_at=cap_evidence.expires_at,
        ),
        product_reserves=(),
    )
    plan = RunAdmissionPlanPayload(
        run_identity=case.payload.run_identity,
        purpose=case.payload.purpose,
        model_roles={
            "annotator": strong_plan,
            "judge": strong_plan,
            "weak_extractor": weak_plan,
        },
        budget_contract_hash=budget_contract_hash(contract),
    )
    finance_key = Ed25519PrivateKey.generate()
    cleanup_key = Ed25519PrivateKey.generate()
    authorities = {
        **case.authorities,
        **_policy(
            finance_key,
            key_id="finance-key",
            identity="finance-owner@example.test",
            domain="budget",
            role="budget_approver",
        ),
        **_policy(
            cleanup_key,
            key_id="cleanup-key",
            identity="cleanup-operator@example.test",
            domain=CLEANUP_AUTHORIZATION_DOMAIN,
            role="deployment-cleanup-operator",
        ),
    }
    _install_production_authorities(monkeypatch, authorities)
    budget_payload = BudgetApprovalPayload(
        plan_payload_hash=plan_payload_hash(plan),
        run_identity=plan.run_identity,
        purpose=plan.purpose,
        scope=case.payload.scope,
        approver_identity="finance-owner@example.test",
        approver_role="budget_approver",
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=30),
        budget_entries=(
            BudgetApprovalEntry(
                currency="CNY",
                max_input_tokens=0,
                max_output_tokens=0,
                max_cost_minor_units=20_000,
                budget_contract_hash=budget_contract_hash(contract),
            ),
        ),
    )
    budget_approval = BudgetApprovalEnvelope(
        domain="budget",
        key_id="finance-key",
        payload=budget_payload,
        signature=base64.b64encode(
            finance_key.sign(approval_signed_bytes("budget", budget_payload))
        ).decode("ascii"),
    )
    monkeypatch.setattr(
        "insurance_harness.goldenset.admission_budget._PRODUCTION_DEPLOYMENT_OPERATION_ROOT",
        case.run_root,
        raising=False,
    )
    ledger.bind_final_infrastructure_topology(
        strong=FinalInfrastructureBindingRequest(
            reserve_id=strong_reserved.reserve_id,
            authorization=case.authorization,
            expected_authorization=case.payload,
            receipt_capability=strong_adopted.receipt_capability,
            roles=("annotator", "judge"),
            pricing_evidence_bytes=case.fixture.pricing_bytes,
            pricing_approval=case.fixture.pricing_approval,
            provider_cap_evidence_bytes=case.fixture.cap_bytes,
            provider_cap_approval=case.fixture.cap_approval,
        ),
        weak=FinalInfrastructureBindingRequest(
            reserve_id=weak_reserved.reserve_id,
            authorization=weak_authorization,
            expected_authorization=weak_payload,
            receipt_capability=weak_adopted.receipt_capability,
            roles=("weak_extractor",),
            pricing_evidence_bytes=case.fixture.pricing_bytes,
            pricing_approval=case.fixture.pricing_approval,
            provider_cap_evidence_bytes=case.fixture.cap_bytes,
            provider_cap_approval=case.fixture.cap_approval,
        ),
        plan=plan,
        contract=contract,
        envelope=budget_approval,
        expected_scope=case.payload.scope,
    )
    case.controller.close()
    ledger_rows_before_cleanup = ledger_rows(case.fixture.db_path)
    methods_before_cleanup = len(provider_methods)
    for reserve_id in (strong_reserved.reserve_id, weak_reserved.reserve_id):
        cleanup_controller = DeploymentController.for_production_cleanup(
            reserve_id=reserve_id
        )
        cleanup_controller._clock = lambda: NOW
        binding = ledger.infrastructure_cleanup_binding(reserve_id)
        try:
            result = cleanup_controller.cleanup(
                authorization=_c4_cleanup_authorization(cleanup_key, binding),
                receipt_digest=binding.receipt_digest,
            )
        finally:
            cleanup_controller.close()
        assert result.receipt.terminal_state == "absent_404"
    assert provider_methods[methods_before_cleanup:] == [
        ("GET", strong_receipt.content.deployed_model),
        ("DELETE", strong_receipt.content.deployed_model),
        ("GET", strong_receipt.content.deployed_model),
        ("GET", weak_receipt.content.deployed_model),
        ("DELETE", weak_receipt.content.deployed_model),
        ("GET", weak_receipt.content.deployed_model),
    ]
    assert ledger_rows(case.fixture.db_path) == ledger_rows_before_cleanup
