from __future__ import annotations

import base64
import copy
import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.goldenset import admission_deployment
from insurance_harness.goldenset.admission_budget import (
    BudgetAmounts,
    BudgetContract,
    BudgetLedger,
    BudgetLedgerError,
    FinalInfrastructureBindingRequest,
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
    BailianDeploymentHTTPTransport,
    DeploymentController,
    ProviderDeploymentManifest,
    deterministic_deployment_suffix,
    deterministic_operation_marker,
    provider_manifest_digest,
    transport_workspace_evidence_digest,
)
from insurance_harness.goldenset.admission_infrastructure import (
    PRICING_EVIDENCE_DOMAIN,
    PROVIDER_CAP_DOMAIN,
    PROVISIONING_AUTHORIZATION_DOMAIN,
    AuthorizationVerificationError,
    DeploymentReceipt,
    DeploymentReceiptContent,
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
    credential_ref_for_api_key,
    deployment_receipt_content_digest,
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
