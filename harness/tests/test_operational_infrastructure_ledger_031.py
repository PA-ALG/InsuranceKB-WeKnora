from __future__ import annotations

import base64
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.goldenset.admission_budget import (
    BudgetAmounts,
    BudgetContract,
    BudgetLedger,
    BudgetLedgerError,
    InfrastructureCreatePermit,
    InfrastructureReserveSnapshot,
    ProductReserve,
    ProviderSpendCapAttestation,
    RequestReserve,
    RoleRate,
    budget_account_identity,
    budget_contract_hash,
    model_role_budget_identity_hash,
)
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
    VerifiedPricingCapability,
    VerifiedProviderCapCapability,
    VerifiedReconciledDeploymentReceipt,
    _issue_verified_pricing_capability_for_testing,
    _issue_verified_provider_capability_for_testing,
    authorization_signed_bytes,
    deployment_receipt_content_digest,
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
    plan_payload_hash,
)

NOW = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)
RUN = "golden-v01-run-031"
PURPOSE = "golden-v0.1 production run"
SCOPE = "goldenset-production"
STRONG = "qwen3.7-plus-2026-05-26-031strng"
WEAK = "deepseek-v4-flash-031weak1"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _authorization_payload(**updates: Any) -> ProvisioningAuthorizationPayload:
    values: dict[str, object] = {
        "transition": "create",
        "provider": "bailian",
        "run_identity": RUN,
        "purpose": PURPOSE,
        "scope": SCOPE,
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


def _sign_authorization(
    private_key: Ed25519PrivateKey,
    payload: ProvisioningAuthorizationPayload,
) -> ProvisioningAuthorization:
    return ProvisioningAuthorization(
        domain=PROVISIONING_AUTHORIZATION_DOMAIN,
        key_id="provisioning-key",
        payload=payload,
        signature=base64.b64encode(
            private_key.sign(
                authorization_signed_bytes(PROVISIONING_AUTHORIZATION_DOMAIN, payload)
            )
        ).decode("ascii"),
    )


def _adoption_payload(receipt: DeploymentReceipt) -> ExistingDeploymentAdoptionAuthorizationPayload:
    values = _authorization_payload().model_dump(mode="python")
    values.update(
        {
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
    )
    return ExistingDeploymentAdoptionAuthorizationPayload.model_validate(values)


def _sign_adoption(
    private_key: Ed25519PrivateKey,
    payload: ExistingDeploymentAdoptionAuthorizationPayload,
) -> ExistingDeploymentAdoptionAuthorization:
    return ExistingDeploymentAdoptionAuthorization(
        domain=ADOPTION_AUTHORIZATION_DOMAIN,
        key_id="adoption-key",
        payload=payload,
        signature=base64.b64encode(
            private_key.sign(
                authorization_signed_bytes(ADOPTION_AUTHORIZATION_DOMAIN, payload)
            )
        ).decode("ascii"),
    )


def _infra_policy(
    private_key: Ed25519PrivateKey,
    *,
    adoption: bool = False,
) -> dict[str, TrustedKeyPolicy]:
    key_id = "adoption-key" if adoption else "provisioning-key"
    return {
        key_id: TrustedKeyPolicy(
            key_id=key_id,
            approver_identity=(
                "budget-owner@example.test"
                if adoption
                else "deployment-operator@example.test"
            ),
            domains=frozenset(
                {
                    ADOPTION_AUTHORIZATION_DOMAIN
                    if adoption
                    else PROVISIONING_AUTHORIZATION_DOMAIN
                }
            ),
            scopes=frozenset({SCOPE}),
            roles=frozenset(
                {"budget-approver" if adoption else "deployment-provisioner"}
            ),
            public_key=private_key.public_key(),
        )
    }


def _receipt(**updates: Any) -> DeploymentReceipt:
    values: dict[str, object] = {
        "operation_id": "op-strong-031",
        "infrastructure_reserve_id": "infra-strong-031",
        "workspace_ref": "workspace-cn-beijing-031",
        "project_ref": "sha256:" + SHA_A,
        "credential_ref": "sha256:" + SHA_B,
        "workspace_evidence_digest": SHA_A,
        "region": "cn-beijing",
        "base_model": "qwen3.7-plus-2026-05-26",
        "deployed_model": STRONG,
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
    content = DeploymentReceiptContent.model_validate(values)
    return DeploymentReceipt(
        content=content,
        content_digest=deployment_receipt_content_digest(content),
    )


def _verified_receipt(**updates: Any) -> VerifiedReconciledDeploymentReceipt:
    return verify_reconciled_deployment_receipt(
        _receipt(**updates), remote_expected=_receipt(**updates)
    )


def _pricing_capability(
    payload: ProvisioningAuthorizationPayload
    | ExistingDeploymentAdoptionAuthorizationPayload,
) -> VerifiedPricingCapability:
    return _issue_verified_pricing_capability_for_testing(
        evidence_digest=payload.pricing_evidence_digest,
        approval_digest="e" * 64,
        provider=payload.provider,
        currency=payload.currency,
        workspace_ref=payload.workspace_ref,
        project_ref=payload.project_ref,
        credential_ref=payload.credential_ref,
        region=payload.region,
        base_model=payload.base_model,
        request_plan=payload.request_plan,
        receipt_plan=payload.receipt_plan,
        input_tpm_quota=payload.input_tpm_quota,
        output_tpm_quota=payload.output_tpm_quota,
        fixed_cost_minor_units=payload.maximum_cost_minor_units,
    )


def _cap_capability(
    payload: ProvisioningAuthorizationPayload
    | ExistingDeploymentAdoptionAuthorizationPayload,
    *,
    maximum: int | None = None,
) -> VerifiedProviderCapCapability:
    return _issue_verified_provider_capability_for_testing(
        evidence_digest=payload.provider_cap_evidence_digest,
        approval_digest="f" * 64,
        provider=payload.provider,
        currency=payload.currency,
        workspace_ref=payload.workspace_ref,
        project_ref=payload.project_ref,
        credential_ref=payload.credential_ref,
        coverage=frozenset({"fixed_infrastructure", "inference"}),
        max_cost_minor_units=(
            payload.provider_cap_max_cost_minor_units if maximum is None else maximum
        ),
        expires_at=payload.provider_cap_expires_at,
    )


def _roles() -> dict[str, ModelRolePlan]:
    return {
        "annotator": ModelRolePlan(
            provider="bailian",
            model_id=STRONG,
            immutable_deployment_id=STRONG,
            protocol="https",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            provider_policy="bailian-deployment-detail-v1",
            credential_env_name="HARNESS_DASHSCOPE_API_KEY",
        ),
        "judge": ModelRolePlan(
            provider="bailian",
            model_id=STRONG,
            immutable_deployment_id=STRONG,
            protocol="https",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            provider_policy="bailian-deployment-detail-v1",
            credential_env_name="HARNESS_DASHSCOPE_API_KEY",
        ),
        "weak_extractor": ModelRolePlan(
            provider="bailian",
            model_id=WEAK,
            immutable_deployment_id=WEAK,
            protocol="https",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            provider_policy="bailian-deployment-detail-v1",
            credential_env_name="HARNESS_DASHSCOPE_API_KEY",
        ),
    }


def _contract(
    *,
    ceiling_cost: int = 10_000,
    provider_cap_cost: int | None = None,
    provider_evidence_digest: str = SHA_D,
    project_ref: str = "sha256:" + SHA_A,
    credential_ref: str = "sha256:" + SHA_B,
    provider: str = "bailian",
    product_max_cost: int | None = None,
) -> BudgetContract:
    roles = _roles()
    return BudgetContract(
        currency="CNY",
        price_snapshot_id="pricing-031",
        price_observed_at=NOW - timedelta(minutes=10),
        price_expires_at=NOW + timedelta(hours=1),
        ceiling=BudgetAmounts(
            input_tokens=0,
            output_tokens=0,
            cost_minor_units=ceiling_cost,
        ),
        role_rates={
            role: RoleRate(
                model_role_identity_hash=model_role_budget_identity_hash(plan),
                input_cost_per_million_minor_units=0,
                output_cost_per_million_minor_units=0,
            )
            for role, plan in roles.items()
        },
        provider_attestation=ProviderSpendCapAttestation(
            provider=provider,
            project_ref=project_ref,
            credential_ref=credential_ref,
            max_cost_minor_units=(
                ceiling_cost if provider_cap_cost is None else provider_cap_cost
            ),
            observed_at=NOW - timedelta(minutes=10),
            expires_at=NOW + timedelta(hours=1),
            evidence_digest=provider_evidence_digest,
        ),
        product_reserves=(
            ()
            if product_max_cost is None
            else (
                ProductReserve(
                    stage="extraction",
                    product_id="product-01",
                    maximum=BudgetAmounts(
                        input_tokens=0,
                        output_tokens=0,
                        cost_minor_units=product_max_cost,
                    ),
                    request_reserves=(
                        RequestReserve(
                            request_unit="request-01",
                            role="weak_extractor",
                            maximum=BudgetAmounts(
                                input_tokens=0,
                                output_tokens=0,
                                cost_minor_units=product_max_cost,
                            ),
                        ),
                    ),
                ),
            )
        ),
    )


def _plan(contract: BudgetContract) -> RunAdmissionPlanPayload:
    return RunAdmissionPlanPayload(
        run_identity=RUN,
        purpose=PURPOSE,
        model_roles=_roles(),
        budget_contract_hash=budget_contract_hash(contract),
    )


def _budget_envelope(
    private_key: Ed25519PrivateKey,
    contract: BudgetContract,
) -> BudgetApprovalEnvelope:
    plan = _plan(contract)
    payload = BudgetApprovalPayload(
        plan_payload_hash=plan_payload_hash(plan),
        run_identity=RUN,
        purpose=PURPOSE,
        scope=SCOPE,
        approver_identity="finance-owner@example.test",
        approver_role="budget_approver",
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=30),
        budget_entries=(
            BudgetApprovalEntry(
                currency="CNY",
                max_input_tokens=0,
                max_output_tokens=0,
                max_cost_minor_units=contract.ceiling.cost_minor_units,
                budget_contract_hash=budget_contract_hash(contract),
            ),
        ),
    )
    return BudgetApprovalEnvelope(
        domain="budget",
        key_id="finance-key",
        payload=payload,
        signature=base64.b64encode(
            private_key.sign(approval_signed_bytes("budget", payload))
        ).decode("ascii"),
    )


def _reserve(
    ledger: BudgetLedger,
    private_key: Ed25519PrivateKey,
    *,
    payload: ProvisioningAuthorizationPayload | None = None,
) -> InfrastructureCreatePermit:
    expected = payload or _authorization_payload()
    return ledger._reserve_provisioning_before_post_for_testing(
        authorization=_sign_authorization(private_key, expected),
        expected=expected,
        trusted_authorities=_infra_policy(private_key),
        pricing_capability=_pricing_capability(expected),
        provider_capability=_cap_capability(expected),
        now=NOW,
    )


def test_o4_schema_v5_fresh_reserve_is_durable_before_account_or_deployment(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    key = Ed25519PrivateKey.generate()

    permit = _reserve(ledger, key)

    assert permit.reserve.state == "reserved"
    assert permit.reserve.maximum == BudgetAmounts(
        input_tokens=0,
        output_tokens=0,
        cost_minor_units=6_720,
    )
    assert permit.reserve.deployed_model is None
    assert permit.reserve.roles == ()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (5,)
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM infrastructure_reserves").fetchone() == (
            1,
        )
        assert connection.execute("SELECT COUNT(*) FROM deployment_role_bindings").fetchone() == (
            0,
        )


def test_o4_byte_identical_reservation_replay_is_exactly_once(tmp_path: Path) -> None:
    ledger = BudgetLedger._for_testing(tmp_path / "budget.sqlite3", clock=lambda: NOW)
    key = Ed25519PrivateKey.generate()

    first = _reserve(ledger, key)
    replay = _reserve(ledger, key)

    assert replay == first


def test_o4_conflicting_reserve_or_cap_overflow_rolls_back(tmp_path: Path) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    key = Ed25519PrivateKey.generate()
    _reserve(ledger, key)

    conflict = _authorization_payload(maximum_cost_minor_units=6_721)
    with pytest.raises(BudgetLedgerError, match="conflict"):
        _reserve(ledger, key, payload=conflict)
    second = _authorization_payload(
        operation_id="op-weak-031",
        infrastructure_reserve_id="infra-weak-031",
        base_model="deepseek-v4-flash",
        maximum_cost_minor_units=4_320,
    )
    with pytest.raises(BudgetLedgerError, match="cap"):
        _reserve(ledger, key, payload=second)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM infrastructure_reserves").fetchone() == (
            1,
        )


def test_o4_adoption_occupies_cost_without_returning_a_create_permit(tmp_path: Path) -> None:
    ledger = BudgetLedger._for_testing(tmp_path / "budget.sqlite3", clock=lambda: NOW)
    key = Ed25519PrivateKey.generate()
    receipt = _receipt()
    payload = _adoption_payload(receipt)

    snapshot = ledger._reserve_existing_adoption_for_testing(
        authorization=_sign_adoption(key, payload),
        expected=payload,
        trusted_authorities=_infra_policy(key, adoption=True),
        receipt_capability=verify_reconciled_deployment_receipt(
            receipt, remote_expected=_receipt()
        ),
        pricing_capability=_pricing_capability(payload),
        provider_capability=_cap_capability(payload),
        now=NOW,
    )

    assert type(snapshot) is InfrastructureReserveSnapshot
    assert snapshot.authorization_domain == ADOPTION_AUTHORIZATION_DOMAIN
    assert snapshot.maximum.cost_minor_units == 6_720


def test_o4_adoption_requires_receipt_verified_against_independent_remote_expected() -> None:
    local = _receipt()
    remote = _receipt(gmt_modified=NOW - timedelta(minutes=1))

    with pytest.raises(AuthorizationVerificationError, match="expected values"):
        verify_reconciled_deployment_receipt(local, remote_expected=remote)


def test_o4_raw_price_or_cap_values_cannot_produce_create_permit(tmp_path: Path) -> None:
    ledger = BudgetLedger._for_testing(tmp_path / "budget.sqlite3", clock=lambda: NOW)
    key = Ed25519PrivateKey.generate()
    payload = _authorization_payload()

    with pytest.raises(BudgetLedgerError, match="verified.*capabilit"):
        ledger._reserve_provisioning_before_post_for_testing(
            authorization=_sign_authorization(key, payload),
            expected=payload,
            trusted_authorities=_infra_policy(key),
            pricing_capability={"evidence_digest": SHA_C},  # type: ignore[arg-type]
            provider_capability={"evidence_digest": SHA_D},  # type: ignore[arg-type]
            now=NOW,
        )


def test_o7_production_ledger_rejects_private_test_capabilities_without_signed_evidence(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger(db_path)
    key = Ed25519PrivateKey.generate()
    payload = _authorization_payload()
    forged_pricing = _pricing_capability(payload)
    forged_cap = _cap_capability(payload)
    object.__setattr__(forged_pricing, "_seal", object())
    object.__setattr__(forged_cap, "_seal", object())

    with pytest.raises(BudgetLedgerError, match="signed pricing and provider-cap"):
        ledger.reserve_provisioning_before_post(
            authorization=_sign_authorization(key, payload),
            expected=payload,
            trusted_authorities=_infra_policy(key),
            pricing_capability=forged_pricing,
            provider_capability=forged_cap,
            now=NOW,
        )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM infrastructure_reserves").fetchone() == (
            0,
        )


def test_o7_public_adoption_rejects_cloned_capabilities_without_signed_evidence(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    infra_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    receipt = _receipt()
    adoption = _adoption_payload(receipt)
    cloned_receipt = _verified_receipt()
    object.__setattr__(cloned_receipt, "_seal", object())

    with pytest.raises(BudgetLedgerError, match="signed pricing and provider-cap"):
        ledger.reserve_existing_adoption(
            authorization=_sign_adoption(infra_key, adoption),
            expected=adoption,
            trusted_authorities=_infra_policy(infra_key, adoption=True),
            receipt_capability=cloned_receipt,
            pricing_capability=_pricing_capability(adoption),
            provider_capability=_cap_capability(adoption),
            now=NOW,
        )
    permit = _reserve(ledger, infra_key)
    contract = _contract()
    with pytest.raises(BudgetLedgerError, match="signed pricing and provider-cap"):
        ledger.bind_final_infrastructure_contract(
            reserve_id=permit.reserve.reserve_id,
            authorization=_sign_authorization(infra_key, _authorization_payload()),
            expected_authorization=_authorization_payload(),
            receipt_capability=cloned_receipt,
            roles=("annotator", "judge"),
            plan=_plan(contract),
            contract=contract,
            envelope=_budget_envelope(budget_key, contract),
            trusted_authorities={
                **_infra_policy(infra_key),
                "finance-key": budget_key.public_key(),
            },
            expected_scope=SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=NOW,
        )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)
        assert connection.execute("SELECT state FROM infrastructure_reserves").fetchone() == (
            "reserved",
        )


def test_o4_private_transaction_helpers_require_explicit_test_ledger_before_all_work(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger(db_path)
    infra_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    payload = _authorization_payload()
    receipt = _receipt()
    adoption = _adoption_payload(receipt)
    contract = _contract()

    with pytest.raises(BudgetLedgerError, match="testing mode"):
        ledger._reserve_provisioning_before_post_for_testing(
            authorization=_sign_authorization(infra_key, payload),
            expected=payload,
            trusted_authorities=_infra_policy(infra_key),
            pricing_capability=_pricing_capability(payload),
            provider_capability=_cap_capability(payload),
            now=NOW,
        )
    with pytest.raises(BudgetLedgerError, match="testing mode"):
        ledger._reserve_existing_adoption_for_testing(
            authorization=_sign_adoption(infra_key, adoption),
            expected=adoption,
            trusted_authorities=_infra_policy(infra_key, adoption=True),
            receipt_capability=_verified_receipt(),
            pricing_capability=_pricing_capability(adoption),
            provider_capability=_cap_capability(adoption),
            now=NOW,
        )
    with pytest.raises(BudgetLedgerError, match="testing mode"):
        ledger._bind_final_infrastructure_contract_for_testing(
            reserve_id="infra-strong-031",
            receipt_capability=_verified_receipt(),
            roles=("annotator", "judge"),
            plan=_plan(contract),
            contract=contract,
            envelope=_budget_envelope(budget_key, contract),
            trusted_public_keys={"finance-key": budget_key.public_key()},
            expected_scope=SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=NOW,
        )
    with sqlite3.connect(db_path) as connection:
        authorization_count = connection.execute(
            "SELECT COUNT(*) FROM infrastructure_authorizations"
        ).fetchone()
        assert authorization_count == (
            0,
        )
        assert connection.execute("SELECT COUNT(*) FROM infrastructure_reserves").fetchone() == (
            0,
        )
        assert connection.execute("SELECT COUNT(*) FROM deployment_role_bindings").fetchone() == (
            0,
        )
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)


def test_o4_reserve_persists_exact_verified_evidence_resource_bindings(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    key = Ed25519PrivateKey.generate()
    permit = _reserve(ledger, key)

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM infrastructure_reserves WHERE reserve_id=?",
            (permit.reserve.reserve_id,),
        ).fetchone()
    assert row is not None
    assert dict(row).items() >= {
        "pricing_evidence_digest": SHA_C,
        "pricing_approval_digest": "e" * 64,
        "provider_cap_evidence_digest": SHA_D,
        "provider_cap_approval_digest": "f" * 64,
        "provider_cap_max_cost": 10_000,
        "currency": "CNY",
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
        "covers_fixed_infrastructure": 1,
        "covers_inference": 1,
    }.items()


def test_o4_reserve_and_create_permit_expire_at_cleanup_deadline(tmp_path: Path) -> None:
    ledger = BudgetLedger._for_testing(tmp_path / "budget.sqlite3", clock=lambda: NOW)
    key = Ed25519PrivateKey.generate()
    expired = _authorization_payload(cleanup_deadline=NOW)

    with pytest.raises(BudgetLedgerError, match="cleanup deadline"):
        _reserve(ledger, key, payload=expired)

    fresh_until_cleanup = _authorization_payload(
        expires_at=NOW + timedelta(hours=10),
        provider_cap_expires_at=NOW + timedelta(hours=10),
    )
    permit = _reserve(ledger, key, payload=fresh_until_cleanup)
    with pytest.raises(BudgetLedgerError, match="cleanup deadline"):
        permit.require_fresh(NOW + timedelta(hours=8))


def test_o4_o6_final_binding_is_atomic_and_shared_strong_cost_is_counted_once(
    tmp_path: Path,
) -> None:
    ledger = BudgetLedger._for_testing(tmp_path / "budget.sqlite3", clock=lambda: NOW)
    infra_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    permit = _reserve(ledger, infra_key)
    receipt = _receipt()
    contract = _contract()

    bound = ledger._bind_final_infrastructure_contract_for_testing(
        reserve_id=permit.reserve.reserve_id,
        receipt_capability=verify_reconciled_deployment_receipt(
            receipt, remote_expected=_receipt()
        ),
        roles=("annotator", "judge"),
        plan=_plan(contract),
        contract=contract,
        envelope=_budget_envelope(budget_key, contract),
        trusted_public_keys={"finance-key": budget_key.public_key()},
        expected_scope=SCOPE,
        authorized_roles=frozenset({"budget_approver"}),
        now=NOW,
    )

    assert bound.state == "bound"
    assert bound.deployed_model == STRONG
    assert bound.roles == ("annotator", "judge")
    account = ledger.account_snapshot(budget_account_identity(RUN, PURPOSE))
    assert account.reserved.cost_minor_units == 6_720
    replay = ledger._bind_final_infrastructure_contract_for_testing(
        reserve_id=permit.reserve.reserve_id,
        receipt_capability=verify_reconciled_deployment_receipt(
            receipt, remote_expected=_receipt()
        ),
        roles=("annotator", "judge"),
        plan=_plan(contract),
        contract=contract,
        envelope=_budget_envelope(budget_key, contract),
        trusted_public_keys={"finance-key": budget_key.public_key()},
        expected_scope=SCOPE,
        authorized_roles=frozenset({"budget_approver"}),
        now=NOW,
    )
    assert replay == bound
    assert ledger.account_snapshot(account.account_id).reserved.cost_minor_units == 6_720


def test_o8_two_reserve_final_topology_rolls_back_as_one_transaction(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    infra_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    strong_payload = _authorization_payload()
    weak_payload = _authorization_payload(
        operation_id="op-weak-031",
        infrastructure_reserve_id="infra-weak-031",
        base_model="deepseek-v4-flash",
        maximum_cost_minor_units=1_000,
    )
    _reserve(ledger, infra_key, payload=strong_payload)
    _reserve(ledger, infra_key, payload=weak_payload)
    strong_receipt = _verified_receipt()
    weak_receipt = _verified_receipt(
        operation_id="op-weak-031",
        infrastructure_reserve_id="infra-weak-031",
        base_model="deepseek-v4-flash",
        deployed_model=WEAK,
        operation_marker="ikb031-" + "4" * 24,
        deployment_suffix="031-" + "5" * 16,
        remote_manifest_digest="6" * 64,
    )
    contract = _contract()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """CREATE TRIGGER fail_weak_bind BEFORE UPDATE ON infrastructure_reserves
               WHEN NEW.reserve_id='infra-weak-031' AND NEW.state='bound'
               BEGIN SELECT RAISE(ABORT, 'simulated weak bind crash'); END"""
        )

    with pytest.raises(BudgetLedgerError, match="topology bind failed"):
        ledger._bind_final_infrastructure_topology_for_testing(
            bindings=(
                ("infra-strong-031", strong_receipt, ("annotator", "judge")),
                ("infra-weak-031", weak_receipt, ("weak_extractor",)),
            ),
            plan=_plan(contract),
            contract=contract,
            envelope=_budget_envelope(budget_key, contract),
            trusted_public_keys={"finance-key": budget_key.public_key()},
            expected_scope=SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=NOW,
        )

    assert ledger.infrastructure_reserve("infra-strong-031").state == "reserved"
    assert ledger.infrastructure_reserve("infra-weak-031").state == "reserved"
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM deployment_role_bindings"
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    "roles",
    [
        ("annotator",),
        ("judge",),
        ("annotator", "weak_extractor"),
        ("annotator", "judge", "weak_extractor"),
    ],
)
def test_o6_single_reserve_rejects_incomplete_or_mixed_strength_role_topology(
    tmp_path: Path,
    roles: tuple[str, ...],
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    infra_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    permit = _reserve(ledger, infra_key)
    contract = _contract()

    with pytest.raises(BudgetLedgerError, match="topology"):
        ledger._bind_final_infrastructure_contract_for_testing(
            reserve_id=permit.reserve.reserve_id,
            receipt_capability=_verified_receipt(),
            roles=roles,  # type: ignore[arg-type]
            plan=_plan(contract),
            contract=contract,
            envelope=_budget_envelope(budget_key, contract),
            trusted_public_keys={"finance-key": budget_key.public_key()},
            expected_scope=SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=NOW,
        )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)


@pytest.mark.parametrize(
    "contract",
    [
        _contract(provider_evidence_digest="9" * 64),
        _contract(project_ref="sha256:" + "8" * 64),
        _contract(credential_ref="sha256:" + "7" * 64),
    ],
)
def test_o4_final_provider_attestation_must_exactly_match_reserved_capability(
    tmp_path: Path,
    contract: BudgetContract,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    infra_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    permit = _reserve(ledger, infra_key)

    with pytest.raises(BudgetLedgerError, match="provider attestation resource"):
        ledger._bind_final_infrastructure_contract_for_testing(
            reserve_id=permit.reserve.reserve_id,
            receipt_capability=_verified_receipt(),
            roles=("annotator", "judge"),
            plan=_plan(contract),
            contract=contract,
            envelope=_budget_envelope(budget_key, contract),
            trusted_public_keys={"finance-key": budget_key.public_key()},
            expected_scope=SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=NOW,
        )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)


def test_o4_final_bind_counts_all_signed_product_maxima_against_provider_cap(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    infra_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    permit = _reserve(ledger, infra_key)
    contract = _contract(product_max_cost=4_000)

    with pytest.raises(BudgetLedgerError, match="product maxima.*provider cap"):
        ledger._bind_final_infrastructure_contract_for_testing(
            reserve_id=permit.reserve.reserve_id,
            receipt_capability=_verified_receipt(),
            roles=("annotator", "judge"),
            plan=_plan(contract),
            contract=contract,
            envelope=_budget_envelope(budget_key, contract),
            trusted_public_keys={"finance-key": budget_key.public_key()},
            expected_scope=SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=NOW,
        )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)


def test_o4_product_reserve_enforces_durable_provider_cap_after_finalization(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    budget_key = Ed25519PrivateKey.generate()
    infra_key = Ed25519PrivateKey.generate()
    contract = _contract(
        ceiling_cost=20_000,
        provider_cap_cost=10_000,
        product_max_cost=6_000,
    )
    plan = _plan(contract)
    account = ledger.open_or_expand_account(
        plan=plan,
        contract=contract,
        envelope=_budget_envelope(budget_key, contract),
        trusted_public_keys={"finance-key": budget_key.public_key()},
        expected_scope=SCOPE,
        authorized_roles=frozenset({"budget_approver"}),
        now=NOW,
    )
    _reserve(ledger, infra_key)

    maximum = BudgetAmounts(input_tokens=0, output_tokens=0, cost_minor_units=6_000)
    with pytest.raises(BudgetLedgerError, match="durable provider cap"):
        ledger.reserve_product(account.account_id, "extraction", "product-01", maximum)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM product_reservations").fetchone() == (0,)


def test_o4_cross_provider_final_binding_rolls_back_before_account(tmp_path: Path) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    infra_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    permit = _reserve(ledger, infra_key)
    contract = _contract(provider="other-provider")

    with pytest.raises(BudgetLedgerError, match="provider"):
        ledger._bind_final_infrastructure_contract_for_testing(
            reserve_id=permit.reserve.reserve_id,
            receipt_capability=_verified_receipt(),
            roles=("annotator", "judge"),
            plan=_plan(contract),
            contract=contract,
            envelope=_budget_envelope(budget_key, contract),
            trusted_public_keys={"finance-key": budget_key.public_key()},
            expected_scope=SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=NOW,
        )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)


def test_o4_final_lower_cap_rolls_back_account_receipt_and_roles(tmp_path: Path) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    infra_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    permit = _reserve(ledger, infra_key)
    contract = _contract(ceiling_cost=6_719)

    with pytest.raises(BudgetLedgerError, match="provider attestation resource"):
        ledger._bind_final_infrastructure_contract_for_testing(
            reserve_id=permit.reserve.reserve_id,
            receipt_capability=_verified_receipt(),
            roles=("annotator", "judge"),
            plan=_plan(contract),
            contract=contract,
            envelope=_budget_envelope(budget_key, contract),
            trusted_public_keys={"finance-key": budget_key.public_key()},
            expected_scope=SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=NOW,
        )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)
        assert connection.execute("SELECT state FROM infrastructure_reserves").fetchone() == (
            "reserved",
        )
        assert connection.execute("SELECT COUNT(*) FROM deployment_role_bindings").fetchone() == (
            0,
        )


def test_o4_final_provider_cap_must_cover_fixed_reserve(tmp_path: Path) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    infra_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    permit = _reserve(ledger, infra_key)
    contract = _contract(provider_cap_cost=6_719)

    with pytest.raises(BudgetLedgerError, match="provider attestation resource"):
        ledger._bind_final_infrastructure_contract_for_testing(
            reserve_id=permit.reserve.reserve_id,
            receipt_capability=_verified_receipt(),
            roles=("annotator", "judge"),
            plan=_plan(contract),
            contract=contract,
            envelope=_budget_envelope(budget_key, contract),
            trusted_public_keys={"finance-key": budget_key.public_key()},
            expected_scope=SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=NOW,
        )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)


def test_o6_same_deployed_model_cannot_bind_a_second_reserve(tmp_path: Path) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    infra_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    shared_cap_payload = _authorization_payload(provider_cap_max_cost_minor_units=20_000)
    first = _reserve(ledger, infra_key, payload=shared_cap_payload)
    contract = _contract(ceiling_cost=20_000)
    plan = _plan(contract)
    envelope = _budget_envelope(budget_key, contract)
    ledger._bind_final_infrastructure_contract_for_testing(
        reserve_id=first.reserve.reserve_id,
        receipt_capability=_verified_receipt(),
        roles=("annotator", "judge"),
        plan=plan,
        contract=contract,
        envelope=envelope,
        trusted_public_keys={"finance-key": budget_key.public_key()},
        expected_scope=SCOPE,
        authorized_roles=frozenset({"budget_approver"}),
        now=NOW,
    )
    second_payload = _authorization_payload(
        operation_id="op-duplicate-031",
        infrastructure_reserve_id="infra-duplicate-031",
        provider_cap_max_cost_minor_units=20_000,
    )
    second = _reserve(ledger, infra_key, payload=second_payload)
    duplicate_receipt = _receipt(
        operation_id="op-duplicate-031",
        infrastructure_reserve_id="infra-duplicate-031",
    )

    with pytest.raises(BudgetLedgerError, match="deployment"):
        ledger._bind_final_infrastructure_contract_for_testing(
            reserve_id=second.reserve.reserve_id,
            receipt_capability=verify_reconciled_deployment_receipt(
                duplicate_receipt,
                remote_expected=_receipt(
                    operation_id="op-duplicate-031",
                    infrastructure_reserve_id="infra-duplicate-031",
                ),
            ),
            roles=("weak_extractor",),
            plan=plan,
            contract=contract,
            envelope=envelope,
            trusted_public_keys={"finance-key": budget_key.public_key()},
            expected_scope=SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=NOW,
        )
    assert ledger.infrastructure_reserve(second.reserve.reserve_id).state == "reserved"


def test_o6_role_identity_mismatch_rolls_back_final_binding(tmp_path: Path) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    infra_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    permit = _reserve(ledger, infra_key)
    contract = _contract()
    plan = _plan(contract)

    with pytest.raises(BudgetLedgerError, match="model_id"):
        ledger._bind_final_infrastructure_contract_for_testing(
            reserve_id=permit.reserve.reserve_id,
            receipt_capability=_verified_receipt(),
            roles=("weak_extractor",),
            plan=plan,
            contract=contract,
            envelope=_budget_envelope(budget_key, contract),
            trusted_public_keys={"finance-key": budget_key.public_key()},
            expected_scope=SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=NOW,
        )
    assert ledger.infrastructure_reserve(permit.reserve.reserve_id).state == "reserved"
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)


def test_o4_v5_missing_or_drifted_infrastructure_schema_fails_closed(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.sqlite3"
    BudgetLedger(missing_path)
    with sqlite3.connect(missing_path) as connection:
        connection.execute("DROP TABLE deployment_role_bindings")
    with pytest.raises(BudgetLedgerError, match="infrastructure schema"):
        BudgetLedger(missing_path)

    drifted_path = tmp_path / "drifted.sqlite3"
    BudgetLedger(drifted_path)
    with sqlite3.connect(drifted_path) as connection:
        connection.execute("ALTER TABLE infrastructure_reserves ADD COLUMN untrusted TEXT")
    with pytest.raises(BudgetLedgerError, match="drifted"):
        BudgetLedger(drifted_path)


def test_o4_v4_to_v5_migration_preserves_existing_budget_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "budget.sqlite3"
    old = BudgetLedger(db_path)
    budget_key = Ed25519PrivateKey.generate()
    contract = _contract()
    account = old.open_or_expand_account(
        plan=_plan(contract),
        contract=contract,
        envelope=_budget_envelope(budget_key, contract),
        trusted_public_keys={"finance-key": budget_key.public_key()},
        expected_scope=SCOPE,
        authorized_roles=frozenset({"budget_approver"}),
        now=NOW,
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE deployment_role_bindings")
        connection.execute("DROP TABLE infrastructure_reserves")
        connection.execute("DROP TABLE infrastructure_authorizations")
        connection.execute("PRAGMA user_version = 4")

    migrated = BudgetLedger(db_path)

    assert migrated.account_snapshot(account.account_id) == account
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (5,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
