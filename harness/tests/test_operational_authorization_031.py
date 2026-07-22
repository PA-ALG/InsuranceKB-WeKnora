from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from insurance_harness.goldenset.admission_infrastructure import (
    PROVISIONING_AUTHORIZATION_DOMAIN,
    AuthorizationVerificationError,
    ProvisioningAuthorization,
    ProvisioningAuthorizationPayload,
    authorization_signed_bytes,
    verify_provisioning_authorization,
)
from insurance_harness.goldenset.admission_models import TrustedKeyPolicy

NOW = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _provisioning_payload(**updates: Any) -> ProvisioningAuthorizationPayload:
    values: dict[str, object] = {
        "transition": "create",
        "provider": "bailian",
        "run_identity": "golden-v01-run-031",
        "purpose": "golden-v0.1 production run",
        "scope": "goldenset-production",
        "operation_id": "op-strong-031",
        "infrastructure_reserve_id": "infra-strong-031",
        "workspace_ref": "workspace-cn-beijing-031",
        "project_ref": "sha256:" + SHA_A,
        "credential_ref": "sha256:" + SHA_B,
        "region": "cn-beijing",
        "base_model": "qwen3.7-plus-2026-05-26",
        "request_plan": "ptu_v2",
        "receipt_plan": "ptu",
        "input_tpm_quota": 10_000,
        "output_tpm_quota": 1_000,
        "pricing_evidence_digest": SHA_C,
        "provider_cap_evidence_digest": SHA_D,
        "pricing_approval_digest": "e" * 64,
        "provider_cap_approval_digest": "f" * 64,
        "currency": "CNY",
        "provider_cap_max_cost_minor_units": 10_000,
        "provider_cap_coverage": ("fixed_infrastructure", "inference"),
        "provider_cap_expires_at": NOW + timedelta(hours=1),
        "maximum_cost_minor_units": 6_720,
        "cleanup_deadline": NOW + timedelta(hours=8),
        "approver_identity": "deployment-operator@example.test",
        "approver_role": "deployment-provisioner",
        "issued_at": NOW - timedelta(minutes=5),
        "expires_at": NOW + timedelta(minutes=30),
    }
    values.update(updates)
    return ProvisioningAuthorizationPayload.model_validate(values)


def _sign_provisioning(
    private_key: Ed25519PrivateKey,
    payload: ProvisioningAuthorizationPayload,
) -> ProvisioningAuthorization:
    signature = private_key.sign(
        authorization_signed_bytes(PROVISIONING_AUTHORIZATION_DOMAIN, payload)
    )
    return ProvisioningAuthorization(
        domain=PROVISIONING_AUTHORIZATION_DOMAIN,
        key_id="provisioning-key",
        payload=payload,
        signature=base64.b64encode(signature).decode("ascii"),
    )


def _policy(
    *,
    key_id: str,
    identity: str,
    domain: str,
    role: str,
    private_key: Ed25519PrivateKey,
) -> TrustedKeyPolicy:
    return TrustedKeyPolicy(
        key_id=key_id,
        approver_identity=identity,
        domains=frozenset({domain}),
        scopes=frozenset({"goldenset-production"}),
        roles=frozenset({role}),
        public_key=private_key.public_key(),
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("run_identity", "other-run"),
        ("provider", "other-provider"),
        ("purpose", "other purpose"),
        ("scope", "other-scope"),
        ("operation_id", "other-operation"),
        ("infrastructure_reserve_id", "other-reserve"),
        ("workspace_ref", "other-workspace"),
        ("project_ref", "sha256:" + "1" * 64),
        ("credential_ref", "sha256:" + "2" * 64),
        ("region", "cn-shanghai"),
        ("base_model", "deepseek-v4-flash"),
        ("request_plan", "ptu"),
        ("receipt_plan", "ptu_v2"),
        ("input_tpm_quota", 20_000),
        ("output_tpm_quota", 2_000),
        ("pricing_evidence_digest", "1" * 64),
        ("provider_cap_evidence_digest", "2" * 64),
        ("pricing_approval_digest", "3" * 64),
        ("provider_cap_approval_digest", "4" * 64),
        ("currency", "USD"),
        ("provider_cap_max_cost_minor_units", 9_999),
        ("provider_cap_coverage", ("inference", "fixed_infrastructure")),
        ("provider_cap_expires_at", NOW + timedelta(hours=2)),
        ("maximum_cost_minor_units", 6_721),
        ("cleanup_deadline", NOW + timedelta(hours=9)),
    ],
)
def test_o4_provisioning_authorization_rejects_resigned_expected_value_mutation(
    field: str,
    replacement: object,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    expected = _provisioning_payload()
    policy = _policy(
        key_id="provisioning-key",
        identity="deployment-operator@example.test",
        domain=PROVISIONING_AUTHORIZATION_DOMAIN,
        role="deployment-provisioner",
        private_key=private_key,
    )
    with pytest.raises((ValidationError, AuthorizationVerificationError)):
        mutated = _provisioning_payload(**{field: replacement})
        envelope = _sign_provisioning(private_key, mutated)
        verify_provisioning_authorization(
            envelope,
            expected=expected,
            trusted_authorities={"provisioning-key": policy},
            now=NOW,
        )


def test_o4_provisioning_authorization_is_domain_and_role_separated() -> None:
    private_key = Ed25519PrivateKey.generate()
    payload = _provisioning_payload()
    envelope = _sign_provisioning(private_key, payload)
    wrong_policy = _policy(
        key_id="provisioning-key",
        identity="deployment-operator@example.test",
        domain="budget",
        role="budget-approver",
        private_key=private_key,
    )

    with pytest.raises(AuthorizationVerificationError, match="policy"):
        verify_provisioning_authorization(
            envelope,
            expected=payload,
            trusted_authorities={"provisioning-key": wrong_policy},
            now=NOW,
        )
