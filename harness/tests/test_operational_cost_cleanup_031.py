from __future__ import annotations

import base64
import os
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.goldenset.admission_budget import (
    BudgetAmounts,
    BudgetContract,
    BudgetLedger,
    BudgetLedgerError,
    FinalInfrastructureBindingRequest,
    InfrastructureCleanupBinding,
    InfrastructureReserveSnapshot,
    ProviderSpendCapAttestation,
    RoleRate,
    budget_contract_hash,
    derive_role_rate_from_pricing,
    model_role_budget_identity_hash,
)
from insurance_harness.goldenset.admission_deployment import (
    BAILIAN_DEPLOYMENT_ENDPOINT,
    CleanupControlResult,
    DeploymentControlBlocked,
    DeploymentController,
    DeploymentNotFound,
    DeploymentReceiptArtifact,
    ProviderDeploymentManifest,
    deterministic_deployment_suffix,
    deterministic_operation_marker,
    provider_manifest_digest,
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
    authorization_signed_bytes,
    cleanup_authorization_signed_bytes,
    deployment_receipt_content_digest,
    pricing_approval_digest,
    pricing_evidence_digest,
    pricing_evidence_signed_bytes,
    provider_cap_approval_digest,
    provider_cap_evidence_digest,
    provider_cap_signed_bytes,
    verify_pricing_evidence,
    verify_provider_cap_evidence,
    verify_reconciled_deployment_receipt,
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
SHA_B = "b" * 64


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
        signature=base64.b64encode(
            key.sign(pricing_evidence_signed_bytes(payload))
        ).decode("ascii"),
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
        signature=base64.b64encode(key.sign(provider_cap_signed_bytes(payload))).decode(
            "ascii"
        ),
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
            key.sign(
                authorization_signed_bytes(PROVISIONING_AUTHORIZATION_DOMAIN, payload)
            )
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
        operation_id="op-strong-031",
        infrastructure_reserve_id="infra-strong-031",
        workspace_ref="workspace-cn-beijing-031",
        project_ref="sha256:" + SHA_A,
        credential_ref="sha256:" + SHA_B,
        region="cn-beijing",
        base_model="qwen3.7-plus-2026-05-26",
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
        maximum_cost_minor_units=(
            incurred_cost_minor_units + future_max_cost_minor_units
        ),
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
    envelope = ExistingDeploymentAdoptionAuthorization(
        domain=ADOPTION_AUTHORIZATION_DOMAIN,
        key_id="adoption-key",
        payload=payload,
        signature=base64.b64encode(
            key.sign(authorization_signed_bytes(ADOPTION_AUTHORIZATION_DOMAIN, payload))
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
        "operation_marker": deterministic_operation_marker(
            "golden-v01-run-031", "op-strong-031"
        ),
        "deployment_suffix": deterministic_deployment_suffix(
            "golden-v01-run-031", "op-strong-031"
        ),
    }
    values.update(updates)
    return ProviderDeploymentManifest.model_validate(values)


def _receipt(
    manifest: ProviderDeploymentManifest | None = None,
    **updates: Any,
) -> DeploymentReceipt:
    bound_manifest = _manifest() if manifest is None else manifest
    values: dict[str, object] = {
        "operation_id": "op-strong-031",
        "infrastructure_reserve_id": "infra-strong-031",
        "workspace_ref": "workspace-cn-beijing-031",
        "project_ref": "sha256:" + SHA_A,
        "credential_ref": "sha256:" + SHA_B,
        "workspace_evidence_digest": "c" * 64,
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


def _cleanup_binding(receipt: DeploymentReceipt) -> InfrastructureCleanupBinding:
    return InfrastructureCleanupBinding(
        reserve_id="infra-strong-031",
        run_identity="golden-v01-run-031",
        purpose="golden-v0.1 production run",
        scope="goldenset-production",
        operation_id="op-strong-031",
        workspace_ref="workspace-cn-beijing-031",
        project_ref="sha256:" + SHA_A,
        credential_ref="sha256:" + SHA_B,
        receipt_digest=receipt.content_digest,
        deployed_model=receipt.content.deployed_model,
        cleanup_deadline=NOW + timedelta(hours=8),
        remote_manifest_digest=receipt.content.remote_manifest_digest,
    )


def _cleanup_authorization(
    key: Ed25519PrivateKey,
    receipt: DeploymentReceipt,
    manifest: ProviderDeploymentManifest,
    **updates: Any,
) -> DeploymentCleanupAuthorization:
    binding_values = _cleanup_binding(receipt).model_dump(mode="python")
    binding_values.pop("remote_manifest_digest")
    values: dict[str, object] = {
        **binding_values,
        "expected_remote_manifest_digest": provider_manifest_digest(manifest),
        "cleanup_reason": "golden run completed",
        "approver_identity": "cleanup-operator@example.test",
        "approver_role": "deployment-cleanup-operator",
        "issued_at": NOW - timedelta(minutes=5),
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


class _CleanupReader:
    def __init__(self, binding: InfrastructureCleanupBinding) -> None:
        self.binding = binding

    def infrastructure_cleanup_binding(
        self, reserve_id: str
    ) -> InfrastructureCleanupBinding:
        if reserve_id != self.binding.reserve_id:
            raise BudgetLedgerError("cleanup binding not found")
        return self.binding

    def infrastructure_reserve(self, reserve_id: str) -> InfrastructureReserveSnapshot:
        if reserve_id != self.binding.reserve_id:
            raise BudgetLedgerError("reserve not found")
        return InfrastructureReserveSnapshot(
            reserve_id=reserve_id,
            account_id="9" * 64,
            run_identity=self.binding.run_identity,
            purpose=self.binding.purpose,
            operation_id=self.binding.operation_id,
            authorization_domain=PROVISIONING_AUTHORIZATION_DOMAIN,
            authorization_digest="8" * 64,
            maximum=BudgetAmounts(
                input_tokens=0, output_tokens=0, cost_minor_units=5_376
            ),
            state="bound",
            deployed_model=self.binding.deployed_model,
            receipt_digest=self.binding.receipt_digest,
            final_approval_digest="7" * 64,
            roles=("annotator", "judge"),
        )


class _CleanupTransport:
    endpoint = BAILIAN_DEPLOYMENT_ENDPOINT

    def __init__(self, manifest: ProviderDeploymentManifest) -> None:
        self.manifest: ProviderDeploymentManifest | None = manifest
        self.detail_calls = 0
        self.delete_calls = 0
        self.mode = "ok"
        self.drift_endpoint_after_detail = False

    def deployment_detail(self, *, deployed_model: str) -> bytes:
        self.detail_calls += 1
        if self.drift_endpoint_after_detail:
            self.endpoint = "https://attacker.invalid/deployments"
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


def _cleanup_controller(
    tmp_path: Path,
    receipt: DeploymentReceipt,
    manifest: ProviderDeploymentManifest,
    transport: _CleanupTransport,
    clock: Any = None,
) -> DeploymentController:
    root = tmp_path / "deployment-control"
    root.mkdir(mode=0o700)
    artifact = DeploymentReceiptArtifact(
        receipt=receipt,
        remote_manifest=manifest,
        remote_manifest_digest=provider_manifest_digest(manifest),
    )
    receipt_path = root / f"{receipt.content_digest}.receipt.json"
    receipt_path.write_bytes(canonical_json_bytes(artifact))
    os.chmod(receipt_path, 0o600)
    return DeploymentController._for_testing(
        run_root=root,
        reserve_reader=_CleanupReader(_cleanup_binding(receipt)),
        transport=transport,
        clock=(lambda: NOW) if clock is None else clock,
    )


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
) -> None:
    pricing_key = Ed25519PrivateKey.generate()
    cap_key = Ed25519PrivateKey.generate()
    provision_key = Ed25519PrivateKey.generate()
    pricing_content = _pricing_content()
    cap_content = _cap_content()
    pricing = _pricing_approval(pricing_key, pricing_content)
    cap = _cap_approval(cap_key, cap_content)
    expected, authorization = _provisioning_authorization(
        provision_key, pricing, cap
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
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")

    permit = ledger.reserve_provisioning_before_post(
        authorization=authorization,
        expected=expected,
        trusted_authorities=authorities,
        pricing_evidence_bytes=canonical_json_bytes(pricing_content),
        pricing_approval=pricing,
        provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
        provider_cap_approval=cap,
        now=NOW,
    )

    assert permit.reserve.maximum.cost_minor_units == 5_376
    assert permit.reserve == ledger.infrastructure_reserve("infra-strong-031")


def test_o8_public_topology_bind_reverifies_both_evidence_sets_before_atomic_bind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pricing_key = Ed25519PrivateKey.generate()
    cap_key = Ed25519PrivateKey.generate()
    provision_key = Ed25519PrivateKey.generate()
    finance_key = Ed25519PrivateKey.generate()
    pricing_content = _pricing_content()
    cap_content = _cap_content()
    pricing = _pricing_approval(pricing_key, pricing_content)
    cap = _cap_approval(cap_key, cap_content)
    expected, authorization = _provisioning_authorization(
        provision_key, pricing, cap
    )
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
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")
    ledger.reserve_provisioning_before_post(
        authorization=authorization,
        expected=expected,
        trusted_authorities=authorities,
        pricing_evidence_bytes=canonical_json_bytes(pricing_content),
        pricing_approval=pricing,
        provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
        provider_cap_approval=cap,
        now=NOW,
    )
    ledger.reserve_provisioning_before_post(
        authorization=weak_authorization,
        expected=weak_expected,
        trusted_authorities=authorities,
        pricing_evidence_bytes=canonical_json_bytes(weak_pricing_content),
        pricing_approval=weak_pricing,
        provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
        provider_cap_approval=cap,
        now=NOW,
    )
    receipt = _receipt()
    receipt_capability = verify_reconciled_deployment_receipt(
        receipt,
        remote_expected=DeploymentReceipt.model_validate(
            receipt.model_dump(mode="python", round_trip=True)
        ),
    )
    weak_receipt = _receipt(
        operation_id="op-weak-031",
        infrastructure_reserve_id="infra-weak-031",
        base_model="deepseek-v4-flash",
        deployed_model="deepseek-v4-flash-031weak1",
        operation_marker="ikb031-" + "4" * 24,
        deployment_suffix="031-" + "5" * 16,
        remote_manifest_digest="6" * 64,
    )
    weak_receipt_capability = verify_reconciled_deployment_receipt(
        weak_receipt,
        remote_expected=DeploymentReceipt.model_validate(
            weak_receipt.model_dump(mode="python", round_trip=True)
        ),
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
            "model_id": "deepseek-v4-flash-031weak1",
            "immutable_deployment_id": "deepseek-v4-flash-031weak1",
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
        ceiling=BudgetAmounts(
            input_tokens=0, output_tokens=0, cost_minor_units=20_000
        ),
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
    malicious_rate = strong_rate.model_copy(
        update={"input_cost_per_million_minor_units": 1}
    )
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
                    update={
                        "budget_contract_hash": budget_contract_hash(
                            malicious_contract
                        )
                    }
                ),
            ),
        }
    )
    malicious_budget_envelope = BudgetApprovalEnvelope(
        domain="budget",
        key_id="finance-key",
        payload=malicious_budget_payload,
        signature=base64.b64encode(
            finance_key.sign(
                approval_signed_bytes("budget", malicious_budget_payload)
            )
        ).decode("ascii"),
    )
    monkeypatch.setattr(
        ledger,
        "_bind_final_infrastructure_contract_for_testing",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("production bind used private testing seam")
        ),
    )

    with pytest.raises(BudgetLedgerError, match="role rate differs"):
        ledger.bind_final_infrastructure_contract(
            reserve_id=expected.infrastructure_reserve_id,
            authorization=authorization,
            expected_authorization=expected,
            receipt_capability=receipt_capability,
            roles=("annotator", "judge"),
            plan=malicious_plan,
            contract=malicious_contract,
            envelope=malicious_budget_envelope,
            trusted_authorities=authorities,
            expected_scope="goldenset-production",
            authorized_roles=frozenset({"budget_approver"}),
            pricing_evidence_bytes=canonical_json_bytes(pricing_content),
            pricing_approval=pricing,
            provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
            provider_cap_approval=cap,
            now=NOW,
        )
    assert ledger.infrastructure_reserve(expected.infrastructure_reserve_id).state == (
        "reserved"
    )

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
    with pytest.raises(BudgetLedgerError, match="signed evidence rejected"):
        ledger.bind_final_infrastructure_topology(
            strong=strong_binding,
            weak=replace(weak_binding, pricing_evidence_bytes=b"{}"),
            plan=plan,
            contract=contract,
            envelope=budget_envelope,
            trusted_authorities=authorities,
            expected_scope="goldenset-production",
            authorized_roles=frozenset({"budget_approver"}),
            now=NOW,
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
            trusted_authorities=authorities,
            expected_scope="goldenset-production",
            authorized_roles=frozenset({"budget_approver"}),
            now=NOW,
        )
    assert ledger.infrastructure_reserve("infra-strong-031").state == "reserved"
    assert ledger.infrastructure_reserve("infra-weak-031").state == "reserved"
    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (
            0,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM deployment_role_bindings"
        ).fetchone() == (0,)
        connection.execute("DROP TRIGGER fail_public_weak_bind")

    bound = ledger.bind_final_infrastructure_topology(
        strong=strong_binding,
        weak=weak_binding,
        plan=plan,
        contract=contract,
        envelope=budget_envelope,
        trusted_authorities=authorities,
        expected_scope="goldenset-production",
        authorized_roles=frozenset({"budget_approver"}),
        now=NOW,
    )

    assert tuple(item.state for item in bound) == ("bound", "bound")
    assert bound[0].roles == ("annotator", "judge")
    assert bound[1].roles == ("weak_extractor",)


def test_o7_budget_ledger_rejects_caller_cost_before_any_reserve(tmp_path: Any) -> None:
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
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")

    with pytest.raises(BudgetLedgerError, match="mechanical|price|cost"):
        ledger.reserve_provisioning_before_post(
            authorization=authorization,
            expected=expected,
            trusted_authorities=authorities,
            pricing_evidence_bytes=canonical_json_bytes(pricing_content),
            pricing_approval=pricing,
            provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
            provider_cap_approval=cap,
            now=NOW,
        )

    with pytest.raises(BudgetLedgerError, match="not found"):
        ledger.infrastructure_reserve("infra-strong-031")


@pytest.mark.parametrize(
    ("incurred", "future", "expect_success"),
    [(672, 5_376, True), (1, 5_376, False), (672, 1, False)],
)
def test_o7_production_adoption_mechanically_prices_both_time_segments_before_reserve(
    tmp_path: Path,
    incurred: int,
    future: int,
    expect_success: bool,
) -> None:
    pricing_key = Ed25519PrivateKey.generate()
    cap_key = Ed25519PrivateKey.generate()
    adoption_key = Ed25519PrivateKey.generate()
    pricing_content = _pricing_content()
    cap_content = _cap_content()
    pricing = _pricing_approval(pricing_key, pricing_content)
    cap = _cap_approval(cap_key, cap_content)
    receipt = _receipt()
    expected, authorization = _adoption_authorization(
        adoption_key,
        pricing,
        cap,
        receipt,
        incurred_cost_minor_units=incurred,
        future_max_cost_minor_units=future,
    )
    independent = DeploymentReceipt.model_validate(
        receipt.model_dump(mode="python", round_trip=True)
    )
    receipt_capability = verify_reconciled_deployment_receipt(
        receipt, remote_expected=independent
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
            adoption_key,
            key_id="adoption-key",
            identity="budget-owner@example.test",
            domain=ADOPTION_AUTHORIZATION_DOMAIN,
            role="budget-approver",
        ),
    }
    ledger = BudgetLedger(tmp_path / f"adopt-{incurred}-{future}.sqlite3")
    def call() -> InfrastructureReserveSnapshot:
        return ledger.reserve_existing_adoption(
            authorization=authorization,
            expected=expected,
            trusted_authorities=authorities,
            receipt_capability=receipt_capability,
            pricing_evidence_bytes=canonical_json_bytes(pricing_content),
            pricing_approval=pricing,
            provider_cap_evidence_bytes=canonical_json_bytes(cap_content),
            provider_cap_approval=cap,
            now=NOW,
        )

    if expect_success:
        snapshot = call()
        assert snapshot.maximum.cost_minor_units == 6_048
        assert ledger.infrastructure_reserve(snapshot.reserve_id) == snapshot
    else:
        with pytest.raises(BudgetLedgerError, match="mechanical|price|cost"):
            call()
        with pytest.raises(BudgetLedgerError, match="not found"):
            ledger.infrastructure_reserve("infra-strong-031")


def test_o7_cleanup_requires_independent_signed_authority_before_delete(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    manifest = _manifest()
    transport = _CleanupTransport(manifest)
    controller = _cleanup_controller(tmp_path, receipt, manifest, transport)

    with pytest.raises(DeploymentControlBlocked) as blocked:
        controller.cleanup(
            authorization=cast(DeploymentCleanupAuthorization, None),
            trusted_authorities={},
            receipt_digest=receipt.content_digest,
        )

    assert blocked.value.code == "cleanup_authorization_invalid"
    assert transport.delete_calls == 0


@pytest.mark.parametrize("drift_after_detail", [False, True])
def test_o7_cleanup_endpoint_drift_is_blocked_at_entry_and_immediately_before_delete(
    tmp_path: Path,
    drift_after_detail: bool,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    authorization = _cleanup_authorization(key, receipt, manifest)
    transport = _CleanupTransport(manifest)
    if drift_after_detail:
        transport.drift_endpoint_after_detail = True
    else:
        transport.endpoint = "https://attacker.invalid/deployments"
    controller = _cleanup_controller(tmp_path, receipt, manifest, transport)

    with pytest.raises(DeploymentControlBlocked, match="endpoint"):
        controller.cleanup(
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

    assert transport.delete_calls == 0


def test_o7_cleanup_rechecks_expiry_after_waiting_for_run_lock_before_delete(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    manifest = _manifest()
    receipt = _receipt(manifest)
    authorization = _cleanup_authorization(
        key, receipt, manifest, expires_at=NOW + timedelta(seconds=1)
    )
    transport = _CleanupTransport(manifest)
    clock_values = iter((NOW, NOW + timedelta(seconds=2)))
    controller = _cleanup_controller(
        tmp_path,
        receipt,
        manifest,
        transport,
        clock=lambda: next(clock_values),
    )

    with pytest.raises(DeploymentControlBlocked) as blocked:
        controller.cleanup(
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

    assert blocked.value.code == "cleanup_authorization_invalid"
    assert transport.delete_calls == 0


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("run_identity", "other-run"),
        ("purpose", "other-purpose"),
        ("scope", "other-scope"),
        ("operation_id", "other-operation"),
        ("reserve_id", "other-reserve"),
        ("receipt_digest", "1" * 64),
        ("deployed_model", "foreign-deployment"),
        ("workspace_ref", "other-workspace"),
        ("project_ref", "sha256:" + "2" * 64),
        ("credential_ref", "sha256:" + "3" * 64),
        ("expected_remote_manifest_digest", "4" * 64),
        ("cleanup_deadline", NOW + timedelta(hours=7)),
    ],
)
def test_o7_cleanup_cross_resource_replay_is_blocked_before_delete(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    key = Ed25519PrivateKey.generate()
    receipt = _receipt()
    manifest = _manifest()
    authorization = _cleanup_authorization(
        key, receipt, manifest, **{field: replacement}
    )
    transport = _CleanupTransport(manifest)
    controller = _cleanup_controller(tmp_path, receipt, manifest, transport)

    with pytest.raises(DeploymentControlBlocked) as blocked:
        controller.cleanup(
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

    assert blocked.value.code == "cleanup_authorization_invalid"
    assert transport.delete_calls == 0


def test_o7_verified_running_ptu_direct_delete_reconciles_terminal_404(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    receipt = _receipt()
    manifest = _manifest()
    authorization = _cleanup_authorization(key, receipt, manifest)
    transport = _CleanupTransport(manifest)
    controller = _cleanup_controller(tmp_path, receipt, manifest, transport)

    result = controller.cleanup(
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
    replay = controller.cleanup(
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

    assert isinstance(result, CleanupControlResult)
    assert result == replay
    assert result.receipt.billing_stop_verified is True
    assert result.receipt.terminal_state == "absent_404"
    assert result.receipt_path.name.endswith(".cleanup-receipt.json")
    assert transport.delete_calls == 1
    assert b"secret" not in result.receipt_path.read_bytes()


@pytest.mark.parametrize("mode", ["timeout_after_accept", "timeout_without_accept"])
def test_o7_ambiguous_delete_only_claims_stop_after_terminal_reconcile(
    tmp_path: Path,
    mode: str,
) -> None:
    key = Ed25519PrivateKey.generate()
    receipt = _receipt()
    manifest = _manifest()
    authorization = _cleanup_authorization(key, receipt, manifest)
    transport = _CleanupTransport(manifest)
    transport.mode = mode
    controller = _cleanup_controller(tmp_path, receipt, manifest, transport)
    authorities = _policy(
        key,
        key_id="cleanup-key",
        identity="cleanup-operator@example.test",
        domain=CLEANUP_AUTHORIZATION_DOMAIN,
        role="deployment-cleanup-operator",
    )

    if mode == "timeout_after_accept":
        result = controller.cleanup(
            authorization=authorization,
            trusted_authorities=authorities,
            receipt_digest=receipt.content_digest,
        )
        assert result.receipt.billing_stop_verified is True
    else:
        with pytest.raises(DeploymentControlBlocked) as blocked:
            controller.cleanup(
                authorization=authorization,
                trusted_authorities=authorities,
                receipt_digest=receipt.content_digest,
            )
        assert blocked.value.code == "billing_stop_unverified"
    assert transport.delete_calls == 1


def test_o7_changed_manifest_and_404_before_send_never_delete(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    receipt = _receipt()
    manifest = _manifest()
    authorization = _cleanup_authorization(key, receipt, manifest)
    authorities = _policy(
        key,
        key_id="cleanup-key",
        identity="cleanup-operator@example.test",
        domain=CLEANUP_AUTHORIZATION_DOMAIN,
        role="deployment-cleanup-operator",
    )

    changed = _manifest(gmt_modified=NOW)
    changed_transport = _CleanupTransport(changed)
    changed_controller = _cleanup_controller(
        tmp_path, receipt, manifest, changed_transport
    )
    with pytest.raises(DeploymentControlBlocked, match="manifest"):
        changed_controller.cleanup(
            authorization=authorization,
            trusted_authorities=authorities,
            receipt_digest=receipt.content_digest,
        )
    assert changed_transport.delete_calls == 0

    absent_root = tmp_path / "absent"
    absent_root.mkdir()
    absent_transport = _CleanupTransport(manifest)
    absent_transport.manifest = None
    absent_controller = _cleanup_controller(
        absent_root, receipt, manifest, absent_transport
    )
    result = absent_controller.cleanup(
        authorization=authorization,
        trusted_authorities=authorities,
        receipt_digest=receipt.content_digest,
    )
    assert result.receipt.terminal_state == "already_absent_404"
    assert absent_transport.delete_calls == 0


def test_o7_replaced_artifact_and_fresh_cleanup_signature_cannot_override_ledger_ownership(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    original = _manifest()
    receipt = _receipt(original)
    changed = _manifest(gmt_modified=NOW)
    transport = _CleanupTransport(changed)
    controller = _cleanup_controller(tmp_path, receipt, original, transport)
    receipt_path = (
        tmp_path / "deployment-control" / f"{receipt.content_digest}.receipt.json"
    )
    receipt_path.write_bytes(
        canonical_json_bytes(
            {
                "receipt": receipt,
                "remote_manifest": changed,
                "remote_manifest_digest": provider_manifest_digest(changed),
            }
        )
    )
    authorization = _cleanup_authorization(key, receipt, changed)

    with pytest.raises(DeploymentControlBlocked, match="receipt|manifest|ownership"):
        controller.cleanup(
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

    assert transport.delete_calls == 0
