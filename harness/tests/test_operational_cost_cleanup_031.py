from __future__ import annotations

import base64
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.goldenset.admission_budget import (
    BudgetLedger,
    BudgetLedgerError,
    RoleRate,
    derive_role_rate_from_pricing,
)
from insurance_harness.goldenset.admission_infrastructure import (
    PRICING_EVIDENCE_DOMAIN,
    PROVIDER_CAP_DOMAIN,
    PROVISIONING_AUTHORIZATION_DOMAIN,
    AuthorizationVerificationError,
    PricingEvidenceApproval,
    PricingEvidenceApprovalPayload,
    PricingEvidenceContent,
    ProviderCapApproval,
    ProviderCapApprovalPayload,
    ProviderCapEvidenceContent,
    ProvisioningAuthorization,
    ProvisioningAuthorizationPayload,
    _require_verified_pricing_capability_for_testing,
    _require_verified_provider_capability_for_testing,
    authorization_signed_bytes,
    pricing_approval_digest,
    pricing_evidence_digest,
    pricing_evidence_signed_bytes,
    provider_cap_approval_digest,
    provider_cap_evidence_digest,
    provider_cap_signed_bytes,
    verify_pricing_evidence,
    verify_provider_cap_evidence,
)
from insurance_harness.goldenset.admission_models import (
    ModelRolePlan,
    TrustedKeyPolicy,
    canonical_json_bytes,
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
