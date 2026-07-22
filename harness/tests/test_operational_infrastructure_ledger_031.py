from __future__ import annotations

import base64
import inspect
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.goldenset.admission_budget import (
    BudgetAmounts,
    BudgetContract,
    BudgetLedger,
    BudgetLedgerError,
    InfrastructureCreatePermit,
    ProductReserve,
    ProviderSpendCapAttestation,
    RequestReserve,
    RoleRate,
    budget_contract_hash,
    model_role_budget_identity_hash,
)
from insurance_harness.goldenset.admission_infrastructure import (
    PROVISIONING_AUTHORIZATION_DOMAIN,
    AuthorizationVerificationError,
    ProvisioningAuthorization,
    ProvisioningAuthorizationPayload,
    VerifiedPricingCapability,
    VerifiedProviderCapCapability,
    _issue_verified_pricing_capability_for_testing,
    _issue_verified_provider_capability_for_testing,
    authorization_signed_bytes,
    require_verified_pricing_capability,
    require_verified_provider_capability,
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
            private_key.sign(authorization_signed_bytes(PROVISIONING_AUTHORIZATION_DOMAIN, payload))
        ).decode("ascii"),
    )


def _infra_policy(
    private_key: Ed25519PrivateKey,
) -> dict[str, TrustedKeyPolicy]:
    key_id = "provisioning-key"
    return {
        key_id: TrustedKeyPolicy(
            key_id=key_id,
            approver_identity="deployment-operator@example.test",
            domains=frozenset({PROVISIONING_AUTHORIZATION_DOMAIN}),
            scopes=frozenset({SCOPE}),
            roles=frozenset({"deployment-provisioner"}),
            public_key=private_key.public_key(),
        )
    }


def _pricing_capability(
    payload: ProvisioningAuthorizationPayload,
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
    payload: ProvisioningAuthorizationPayload,
    *,
    maximum: int | None = None,
) -> VerifiedProviderCapCapability:
    return _issue_verified_provider_capability_for_testing(
        evidence_digest=payload.provider_cap_evidence_digest,
        approval_digest=payload.provider_cap_approval_digest,
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


def test_o7_private_test_issuers_cannot_mint_production_capabilities() -> None:
    payload = _authorization_payload()
    pricing = _pricing_capability(payload)
    provider_cap = _cap_capability(payload)

    for require, capability in (
        (require_verified_pricing_capability, pricing),
        (require_verified_provider_capability, provider_cap),
    ):
        with pytest.raises(AuthorizationVerificationError, match="production"):
            require(capability)


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
    workspace_ref: str = "workspace-cn-beijing-031",
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
            workspace_ref=workspace_ref,
            project_ref=project_ref,
            credential_ref=credential_ref,
            max_cost_minor_units=(ceiling_cost if provider_cap_cost is None else provider_cap_cost),
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


def _plan(
    contract: BudgetContract,
    *,
    run_identity: str = RUN,
    purpose: str = PURPOSE,
) -> RunAdmissionPlanPayload:
    return RunAdmissionPlanPayload(
        run_identity=run_identity,
        purpose=purpose,
        model_roles=_roles(),
        budget_contract_hash=budget_contract_hash(contract),
    )


def _budget_envelope(
    private_key: Ed25519PrivateKey,
    contract: BudgetContract,
    *,
    run_identity: str = RUN,
    purpose: str = PURPOSE,
) -> BudgetApprovalEnvelope:
    plan = _plan(contract, run_identity=run_identity, purpose=purpose)
    payload = BudgetApprovalPayload(
        plan_payload_hash=plan_payload_hash(plan),
        run_identity=run_identity,
        purpose=purpose,
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
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (5,)
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM infrastructure_reserves").fetchone() == (1,)
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(infrastructure_reserves)")
        }
        assert columns.isdisjoint(
            {
                "deployed_model",
                "receipt_digest",
                "remote_manifest_digest",
                "receipt_json",
                "final_approval_digest",
                "bound_at",
            }
        )
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='deployment_role_bindings'"
            ).fetchone()
            is None
        )
        authorization_sql = connection.execute(
            """SELECT sql FROM sqlite_master
               WHERE type='table' AND name='infrastructure_authorizations'"""
        ).fetchone()
        assert authorization_sql is not None
        assert "deployment-adoption" not in str(authorization_sql[0])


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
        assert connection.execute("SELECT COUNT(*) FROM infrastructure_reserves").fetchone() == (1,)


def test_o4_shared_provider_cap_blocks_cross_run_and_purpose_overflow(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    key = Ed25519PrivateKey.generate()
    first = _authorization_payload(
        maximum_cost_minor_units=6_000,
        provider_cap_max_cost_minor_units=10_000,
    )
    second = _authorization_payload(
        run_identity="golden-v01-run-031-second",
        purpose="golden-v0.1 independent replay",
        operation_id="op-weak-cross-run-031",
        infrastructure_reserve_id="infra-weak-cross-run-031",
        base_model="deepseek-v4-flash",
        pricing_evidence_digest="1" * 64,
        provider_cap_approval_digest="2" * 64,
        maximum_cost_minor_units=6_000,
        provider_cap_max_cost_minor_units=10_000,
    )

    _reserve(ledger, key, payload=first)
    with pytest.raises(BudgetLedgerError, match="provider cap"):
        _reserve(ledger, key, payload=second)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(max_cost), 0) FROM infrastructure_reserves"
        ).fetchone() == (1, 6_000)
        assert connection.execute(
            "SELECT COUNT(*) FROM infrastructure_authorizations"
        ).fetchone() == (1,)


def test_o4_rotated_cap_evidence_cannot_reset_shared_provider_hard_cap(
    tmp_path: Path,
) -> None:
    ledger = BudgetLedger._for_testing(tmp_path / "budget.sqlite3", clock=lambda: NOW)
    key = Ed25519PrivateKey.generate()
    _reserve(
        ledger,
        key,
        payload=_authorization_payload(maximum_cost_minor_units=6_000),
    )
    rotated = _authorization_payload(
        run_identity="golden-v01-run-031-rotated-cap",
        purpose="golden-v0.1 rotated cap observation",
        operation_id="op-rotated-cap-031",
        infrastructure_reserve_id="infra-rotated-cap-031",
        pricing_evidence_digest="1" * 64,
        provider_cap_evidence_digest="9" * 64,
        provider_cap_approval_digest="8" * 64,
        maximum_cost_minor_units=6_000,
    )

    with pytest.raises(BudgetLedgerError, match="provider cap"):
        _reserve(ledger, key, payload=rotated)

    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(max_cost), 0) FROM infrastructure_reserves"
        ).fetchone() == (1, 6_000)


def test_o4_shared_provider_cap_serializes_concurrent_cross_account_reserves(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    key = Ed25519PrivateKey.generate()
    barrier = Barrier(2)
    payloads = (
        _authorization_payload(
            maximum_cost_minor_units=6_000,
            provider_cap_max_cost_minor_units=10_000,
        ),
        _authorization_payload(
            run_identity="golden-v01-run-031-second",
            purpose="golden-v0.1 independent replay",
            operation_id="op-weak-cross-run-031",
            infrastructure_reserve_id="infra-weak-cross-run-031",
            base_model="deepseek-v4-flash",
            pricing_evidence_digest="1" * 64,
            maximum_cost_minor_units=6_000,
            provider_cap_max_cost_minor_units=10_000,
        ),
    )

    def reserve(payload: ProvisioningAuthorizationPayload) -> bool:
        ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
        barrier.wait(timeout=5)
        try:
            _reserve(ledger, key, payload=payload)
        except BudgetLedgerError as exc:
            assert "provider cap" in str(exc)
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(reserve, payloads))

    assert sorted(results) == [False, True]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(max_cost), 0) FROM infrastructure_reserves"
        ).fetchone() == (1, 6_000)


def test_o4_shared_provider_cap_exact_replay_does_not_double_debit(tmp_path: Path) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    key = Ed25519PrivateKey.generate()
    first_payload = _authorization_payload(maximum_cost_minor_units=4_000)
    second_payload = _authorization_payload(
        run_identity="golden-v01-run-031-second",
        purpose="golden-v0.1 independent replay",
        operation_id="op-weak-cross-run-031",
        infrastructure_reserve_id="infra-weak-cross-run-031",
        base_model="deepseek-v4-flash",
        pricing_evidence_digest="1" * 64,
        maximum_cost_minor_units=6_000,
    )

    first = _reserve(ledger, key, payload=first_payload)
    _reserve(ledger, key, payload=second_payload)

    assert _reserve(ledger, key, payload=first_payload) == first
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(max_cost), 0) FROM infrastructure_reserves"
        ).fetchone() == (2, 10_000)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("workspace_ref", "workspace-cn-shanghai-031"),
        ("project_ref", "sha256:" + "1" * 64),
        ("credential_ref", "sha256:" + "2" * 64),
        ("evidence_digest", "3" * 64),
        ("max_cost_minor_units", 9_999),
        ("expires_at", NOW + timedelta(hours=2)),
    ),
)
def test_o4_account_open_after_infrastructure_reserve_rejects_cap_resource_mismatch_before_write(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    infrastructure_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    _reserve(
        ledger,
        infrastructure_key,
        payload=_authorization_payload(
            maximum_cost_minor_units=6_000,
            provider_cap_max_cost_minor_units=10_000,
        ),
    )
    contract = _contract(ceiling_cost=20_000, provider_cap_cost=10_000)
    provider_attestation = contract.provider_attestation.model_copy(update={field: replacement})
    mismatched_contract = contract.model_copy(update={"provider_attestation": provider_attestation})
    plan = _plan(mismatched_contract)

    with sqlite3.connect(db_path) as connection:
        before_reserves = connection.execute("SELECT * FROM infrastructure_reserves").fetchall()
    with pytest.raises(BudgetLedgerError, match="provider attestation resource mismatch"):
        ledger._open_or_expand_account_for_testing(
            plan=plan,
            contract=mismatched_contract,
            envelope=_budget_envelope(budget_key, mismatched_contract),
            trusted_public_keys={"finance-key": budget_key.public_key()},
            expected_scope=SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=NOW,
        )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM budget_approvals").fetchone() == (0,)
        assert (
            connection.execute("SELECT * FROM infrastructure_reserves").fetchall()
            == before_reserves
        )


def test_o4_canary_claim_rechecks_expired_provider_cap_before_evidence_or_write(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    current = [NOW]
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: current[0])
    budget_key = Ed25519PrivateKey.generate()
    contract = _contract(
        ceiling_cost=10_000,
        provider_cap_cost=10_000,
        product_max_cost=1_000,
    )
    account = ledger._open_or_expand_account_for_testing(
        plan=_plan(contract),
        contract=contract,
        envelope=_budget_envelope(budget_key, contract),
        trusted_public_keys={"finance-key": budget_key.public_key()},
        expected_scope=SCOPE,
        authorized_roles=frozenset({"budget_approver"}),
        now=NOW,
    )
    current[0] = NOW + timedelta(hours=2)

    with pytest.raises(BudgetLedgerError, match="pricing or provider cap expired"):
        ledger.claim_canary_capability_and_reserve(
            account_id=account.account_id,
            capability_digest="4" * 64,
            canary_stage="annotation",
            canary_product_id="missing-canary",
            expected_settlement_digest="5" * 64,
            authorization_evaluated_at=NOW,
            authorization_expires_at=NOW + timedelta(hours=3),
            target_stage="extraction",
            target_product_id="product-01",
            target_maximum=BudgetAmounts(
                input_tokens=0,
                output_tokens=0,
                cost_minor_units=1_000,
            ),
            granted_targets=(("extraction", "product-01"),),
        )

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM canary_capability_claims").fetchone() == (
            0,
        )
        assert connection.execute("SELECT COUNT(*) FROM product_reservations").fetchone() == (0,)


def test_o4_distinct_provider_cap_workspace_isolated_across_accounts(tmp_path: Path) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    key = Ed25519PrivateKey.generate()
    first = _authorization_payload(maximum_cost_minor_units=6_000)
    second = _authorization_payload(
        run_identity="golden-v01-run-031-second",
        purpose="golden-v0.1 independent replay",
        operation_id="op-weak-cross-run-031",
        infrastructure_reserve_id="infra-weak-cross-run-031",
        workspace_ref="workspace-cn-beijing-isolated-031",
        base_model="deepseek-v4-flash",
        pricing_evidence_digest="1" * 64,
        maximum_cost_minor_units=6_000,
    )

    _reserve(ledger, key, payload=first)
    _reserve(ledger, key, payload=second)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(max_cost), 0) FROM infrastructure_reserves"
        ).fetchone() == (2, 12_000)


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger(db_path)
    key = Ed25519PrivateKey.generate()
    payload = _authorization_payload()
    forged_pricing = _pricing_capability(payload)
    forged_cap = _cap_capability(payload)
    object.__setattr__(forged_pricing, "_seal", object())
    object.__setattr__(forged_cap, "_seal", object())
    authorities = _infra_policy(key)
    monkeypatch.setattr(
        "insurance_harness.goldenset.admission_cli._load_deployment_approval_configuration",
        lambda: (authorities, frozenset(), frozenset(), frozenset()),
    )

    with pytest.raises(BudgetLedgerError, match="signed pricing and provider-cap"):
        ledger.reserve_provisioning_before_post(
            authorization=_sign_authorization(key, payload),
            expected=payload,
            pricing_capability=forged_pricing,
            provider_capability=forged_cap,
            now=NOW,
        )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM infrastructure_reserves").fetchone() == (0,)


def test_o3_production_account_open_rejects_caller_self_enrolled_budget_key_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "self-enrolled-budget.sqlite3"
    ledger = BudgetLedger(db_path)
    root_key = Ed25519PrivateKey.generate()
    attacker_key = Ed25519PrivateKey.generate()
    root_authorities = {
        "finance-key": TrustedKeyPolicy(
            key_id="finance-key",
            approver_identity="finance-owner@example.test",
            domains=frozenset({"budget"}),
            scopes=frozenset({SCOPE}),
            roles=frozenset({"budget_approver"}),
            public_key=root_key.public_key(),
        )
    }
    monkeypatch.setattr(
        "insurance_harness.goldenset.admission_cli._load_deployment_approval_configuration",
        lambda: (
            root_authorities,
            frozenset({"budget_approver"}),
            frozenset(),
            frozenset(),
        ),
    )
    contract = _contract()
    plan = _plan(contract)

    with pytest.raises(BudgetLedgerError, match="approval|trust|signature|key"):
        ledger.open_or_expand_account(
            plan=plan,
            contract=contract,
            envelope=_budget_envelope(attacker_key, contract),
            trusted_public_keys={"finance-key": attacker_key.public_key()},
            expected_scope=SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=NOW,
        )

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM budget_approvals").fetchone() == (0,)


def test_o3_production_account_open_uses_internal_clock_for_expired_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "expired-budget.sqlite3"
    ledger = BudgetLedger(db_path)
    finance_key = Ed25519PrivateKey.generate()
    authorities = {
        "finance-key": TrustedKeyPolicy(
            key_id="finance-key",
            approver_identity="finance-owner@example.test",
            domains=frozenset({"budget"}),
            scopes=frozenset({SCOPE}),
            roles=frozenset({"budget_approver"}),
            public_key=finance_key.public_key(),
        )
    }
    monkeypatch.setattr(
        "insurance_harness.goldenset.admission_cli._load_deployment_approval_configuration",
        lambda: (
            authorities,
            frozenset({"budget_approver"}),
            frozenset(),
            frozenset(),
        ),
    )
    monkeypatch.setattr(ledger, "_clock", lambda: NOW + timedelta(hours=2))
    contract = _contract()

    with pytest.raises(BudgetLedgerError, match="approval|expired|attestation|price"):
        ledger.open_or_expand_account(
            plan=_plan(contract),
            contract=contract,
            envelope=_budget_envelope(finance_key, contract),
            expected_scope=SCOPE,
        )

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM budget_approvals").fetchone() == (0,)


@pytest.mark.parametrize(
    "method_name",
    (
        "open_or_expand_account",
        "reserve_provisioning_before_post",
    ),
)
def test_o3_o4_o7_production_budget_entrypoints_do_not_accept_caller_freshness_time(
    method_name: str,
) -> None:
    assert "now" not in inspect.signature(getattr(BudgetLedger, method_name)).parameters


def test_o4_private_transaction_helpers_require_explicit_test_ledger_before_all_work(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger(db_path)
    infra_key = Ed25519PrivateKey.generate()
    payload = _authorization_payload()

    with pytest.raises(BudgetLedgerError, match="testing mode"):
        ledger._reserve_provisioning_before_post_for_testing(
            authorization=_sign_authorization(infra_key, payload),
            expected=payload,
            trusted_authorities=_infra_policy(infra_key),
            pricing_capability=_pricing_capability(payload),
            provider_capability=_cap_capability(payload),
            now=NOW,
        )
    with sqlite3.connect(db_path) as connection:
        authorization_count = connection.execute(
            "SELECT COUNT(*) FROM infrastructure_authorizations"
        ).fetchone()
        assert authorization_count == (0,)
        assert connection.execute("SELECT COUNT(*) FROM infrastructure_reserves").fetchone() == (0,)
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
    assert (
        dict(row).items()
        >= {
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
    )


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


def test_o4_shared_provider_cap_includes_matching_inference_only_account(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    budget_key = Ed25519PrivateKey.generate()
    infra_key = Ed25519PrivateKey.generate()
    contract = _contract(
        ceiling_cost=10_000,
        provider_cap_cost=10_000,
        product_max_cost=5_000,
    )
    inference_run = "golden-v01-run-031-inference-only"
    inference_purpose = "golden-v0.1 inference-only account"
    inference_plan = _plan(
        contract,
        run_identity=inference_run,
        purpose=inference_purpose,
    )
    inference_account = ledger._open_or_expand_account_for_testing(
        plan=inference_plan,
        contract=contract,
        envelope=_budget_envelope(
            budget_key,
            contract,
            run_identity=inference_run,
            purpose=inference_purpose,
        ),
        trusted_public_keys={"finance-key": budget_key.public_key()},
        expected_scope=SCOPE,
        authorized_roles=frozenset({"budget_approver"}),
        now=NOW,
    )
    _reserve(
        ledger,
        infra_key,
        payload=_authorization_payload(maximum_cost_minor_units=6_000),
    )

    with pytest.raises(BudgetLedgerError, match="provider cap"):
        ledger.reserve_product(
            inference_account.account_id,
            "extraction",
            "product-01",
            BudgetAmounts(input_tokens=0, output_tokens=0, cost_minor_units=5_000),
        )

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM product_reservations").fetchone() == (0,)


def test_o4_distinct_workspaces_do_not_share_inference_cap_occupancy(
    tmp_path: Path,
) -> None:
    ledger = BudgetLedger._for_testing(tmp_path / "budget.sqlite3", clock=lambda: NOW)
    budget_key = Ed25519PrivateKey.generate()
    accounts: list[str] = []
    for index, workspace_ref in enumerate(("workspace-a-031", "workspace-b-031")):
        run_identity = f"golden-v01-run-031-workspace-{index}"
        purpose = f"golden-v0.1 workspace account {index}"
        contract = _contract(
            provider_cap_cost=10_000,
            product_max_cost=6_000,
            workspace_ref=workspace_ref,
        )
        account = ledger._open_or_expand_account_for_testing(
            plan=_plan(contract, run_identity=run_identity, purpose=purpose),
            contract=contract,
            envelope=_budget_envelope(
                budget_key,
                contract,
                run_identity=run_identity,
                purpose=purpose,
            ),
            trusted_public_keys={"finance-key": budget_key.public_key()},
            expected_scope=SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=NOW,
        )
        accounts.append(account.account_id)

    maximum = BudgetAmounts(input_tokens=0, output_tokens=0, cost_minor_units=6_000)
    ledger.reserve_product(accounts[0], "extraction", "product-01", maximum)
    ledger.reserve_product(accounts[1], "extraction", "product-01", maximum)

    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(max_cost), 0) FROM product_reservations"
        ).fetchone() == (2, 12_000)


def test_o4_v4_to_v5_migration_preserves_existing_budget_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "budget.sqlite3"
    old = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    budget_key = Ed25519PrivateKey.generate()
    contract = _contract()
    account = old._open_or_expand_account_for_testing(
        plan=_plan(contract),
        contract=contract,
        envelope=_budget_envelope(budget_key, contract),
        trusted_public_keys={"finance-key": budget_key.public_key()},
        expected_scope=SCOPE,
        authorized_roles=frozenset({"budget_approver"}),
        now=NOW,
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE infrastructure_reserves")
        connection.execute("DROP TABLE infrastructure_authorizations")
        connection.execute("PRAGMA user_version = 4")

    migrated = BudgetLedger(db_path)

    assert migrated.account_snapshot(account.account_id) == account
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (5,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
