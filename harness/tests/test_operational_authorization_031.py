from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from insurance_harness.goldenset.admission_infrastructure import (
    ADOPTION_AUTHORIZATION_DOMAIN,
    PROVISIONING_AUTHORIZATION_DOMAIN,
    AuthorizationVerificationError,
    DeploymentReceipt,
    DeploymentReceiptContent,
    ExistingDeploymentAdoptionAuthorization,
    ExistingDeploymentAdoptionAuthorizationPayload,
    ProvisioningAuthorization,
    ProvisioningAuthorizationPayload,
    authorization_signed_bytes,
    deployment_receipt_content_digest,
    verify_adoption_authorization,
    verify_deployment_receipt,
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


def _receipt_content(**updates: Any) -> DeploymentReceiptContent:
    values: dict[str, object] = {
        "operation_id": "op-strong-031",
        "infrastructure_reserve_id": "infra-strong-031",
        "workspace_ref": "workspace-cn-beijing-031",
        "project_ref": "sha256:" + SHA_A,
        "credential_ref": "sha256:" + SHA_B,
        "workspace_evidence_digest": SHA_A,
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
        "operation_marker": "ikb031-" + "1" * 24,
        "deployment_suffix": "031-" + "2" * 16,
        "remote_manifest_digest": "3" * 64,
    }
    values.update(updates)
    return DeploymentReceiptContent.model_validate(values)


def _receipt(**updates: Any) -> DeploymentReceipt:
    content = _receipt_content(**updates)
    return DeploymentReceipt(
        content=content,
        content_digest=deployment_receipt_content_digest(content),
    )


def _adoption_payload(**updates: Any) -> ExistingDeploymentAdoptionAuthorizationPayload:
    receipt = _receipt()
    values: dict[str, object] = {
        **_provisioning_payload().model_dump(mode="python"),
        "transition": "adopt_existing",
        "deployed_model": receipt.content.deployed_model,
        "receipt_digest": receipt.content_digest,
        "gmt_create": receipt.content.gmt_create,
        "preexisting": True,
        "limitation": "not_preauthorized_by_031",
        "incurred_cost_minor_units": 3_360,
        "future_max_cost_minor_units": 3_360,
        "approver_identity": "budget-owner@example.test",
        "approver_role": "budget-approver",
    }
    values.update(updates)
    return ExistingDeploymentAdoptionAuthorizationPayload.model_validate(values)


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


def _sign_adoption(
    private_key: Ed25519PrivateKey,
    payload: ExistingDeploymentAdoptionAuthorizationPayload,
) -> ExistingDeploymentAdoptionAuthorization:
    signature = private_key.sign(
        authorization_signed_bytes(ADOPTION_AUTHORIZATION_DOMAIN, payload)
    )
    return ExistingDeploymentAdoptionAuthorization(
        domain=ADOPTION_AUTHORIZATION_DOMAIN,
        key_id="adoption-key",
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
        domain=ADOPTION_AUTHORIZATION_DOMAIN,
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


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("deployed_model", "other-deployment"),
        ("receipt_digest", "1" * 64),
        ("gmt_create", NOW - timedelta(hours=2)),
        ("preexisting", False),
        ("limitation", "retroactively_preauthorized"),
        ("incurred_cost_minor_units", 3_359),
        ("future_max_cost_minor_units", 3_361),
    ],
)
def test_o4_adoption_authorization_binds_preexisting_cost_and_receipt_facts(
    field: str,
    replacement: object,
) -> None:
    expected = _adoption_payload()
    values = expected.model_dump(mode="python")
    values[field] = replacement
    if field in {"incurred_cost_minor_units", "future_max_cost_minor_units"}:
        values["maximum_cost_minor_units"] = int(values["incurred_cost_minor_units"]) + int(
            values["future_max_cost_minor_units"]
        )
    if field in {"preexisting", "limitation"}:
        with pytest.raises(ValidationError):
            ExistingDeploymentAdoptionAuthorizationPayload.model_validate(values)
        return
    private_key = Ed25519PrivateKey.generate()
    mutated = ExistingDeploymentAdoptionAuthorizationPayload.model_validate(values)
    policy = _policy(
        key_id="adoption-key",
        identity="budget-owner@example.test",
        domain=ADOPTION_AUTHORIZATION_DOMAIN,
        role="budget-approver",
        private_key=private_key,
    )
    with pytest.raises(AuthorizationVerificationError, match="expected values"):
        verify_adoption_authorization(
            _sign_adoption(private_key, mutated),
            expected=expected,
            trusted_authorities={"adoption-key": policy},
            now=NOW,
        )


def test_o4_adoption_authorization_cannot_select_create_transition() -> None:
    values = _adoption_payload().model_dump(mode="python")
    values["transition"] = "create"

    with pytest.raises(ValidationError):
        ExistingDeploymentAdoptionAuthorizationPayload.model_validate(values)


def test_o4_adoption_signature_cannot_be_replayed_as_provisioning() -> None:
    private_key = Ed25519PrivateKey.generate()
    payload = _adoption_payload()
    envelope = _sign_adoption(private_key, payload)
    adoption_policy = _policy(
        key_id="adoption-key",
        identity="budget-owner@example.test",
        domain=ADOPTION_AUTHORIZATION_DOMAIN,
        role="budget-approver",
        private_key=private_key,
    )
    verify_adoption_authorization(
        envelope,
        expected=payload,
        trusted_authorities={"adoption-key": adoption_policy},
        now=NOW,
    )

    forged = ProvisioningAuthorization.model_construct(
        domain=PROVISIONING_AUTHORIZATION_DOMAIN,
        key_id=envelope.key_id,
        payload=_provisioning_payload(),
        signature=envelope.signature,
    )
    with pytest.raises(AuthorizationVerificationError, match="policy|signature"):
        verify_provisioning_authorization(
            forged,
            expected=_provisioning_payload(),
            trusted_authorities={"adoption-key": adoption_policy},
            now=NOW,
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("operation_id", "other-operation"),
        ("infrastructure_reserve_id", "other-reserve"),
        ("request_plan", "ptu"),
        ("receipt_plan", "ptu_v2"),
        ("base_model", "deepseek-v4-flash"),
        ("deployed_model", "other-deployment"),
        ("input_tpm", 20_000),
        ("output_tpm", 2_000),
        ("gmt_create", NOW - timedelta(hours=2)),
        ("gmt_modified", NOW - timedelta(minutes=3)),
        ("workspace_evidence_digest", "1" * 64),
        ("cleanup_state", "complete"),
    ],
)
def test_o6_receipt_exact_verification_rejects_normalized_metadata_mutation(
    field: str,
    replacement: object,
) -> None:
    expected = _receipt()
    values = expected.content.model_dump(mode="python")
    values[field] = replacement
    with pytest.raises((ValidationError, AuthorizationVerificationError)):
        mutated_content = DeploymentReceiptContent.model_validate(values)
        mutated = DeploymentReceipt(
            content=mutated_content,
            content_digest=deployment_receipt_content_digest(mutated_content),
        )
        verify_deployment_receipt(mutated, expected=expected)


def test_o6_receipt_rejects_content_digest_mutation() -> None:
    expected = _receipt()
    mutated = DeploymentReceipt.model_construct(
        content=expected.content,
        content_digest="1" * 64,
    )

    with pytest.raises(AuthorizationVerificationError, match="content digest"):
        verify_deployment_receipt(mutated, expected=expected)


def test_o6_receipt_accepts_only_ptu_v2_to_ptu_and_fixed_quota() -> None:
    receipt = _receipt()
    assert verify_deployment_receipt(receipt, expected=receipt) == receipt.content_digest

    for field, value in (
        ("request_plan", "ptu"),
        ("receipt_plan", "ptu_v2"),
        ("input_tpm", 9_999),
        ("output_tpm", 999),
    ):
        values = receipt.content.model_dump(mode="python")
        values[field] = value
        with pytest.raises(ValidationError):
            DeploymentReceiptContent.model_validate(values)
