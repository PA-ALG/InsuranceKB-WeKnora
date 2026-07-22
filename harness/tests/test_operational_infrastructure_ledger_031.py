from __future__ import annotations

import base64
import copy
import inspect
import os
import pickle
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.goldenset import admission_infrastructure
from insurance_harness.goldenset.admission_budget import (
    BudgetAmounts,
    BudgetContract,
    BudgetLedger,
    BudgetLedgerError,
    BudgetRole,
    InfrastructureCreatePermit,
    InfrastructureReserveSnapshot,
    ProductReserve,
    ProviderSpendCapAttestation,
    RequestReserve,
    RoleRate,
    budget_account_identity,
    budget_contract_hash,
    model_role_budget_identity_hash,
    require_verified_infrastructure_provider_capability,
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
    VerifiedPricingCapability,
    VerifiedProviderCapCapability,
    VerifiedReconciledDeploymentReceipt,
    _issue_verified_deployment_transport_identity_for_testing,
    _issue_verified_pricing_capability_for_testing,
    _issue_verified_provider_capability_for_testing,
    _issue_verified_reconciled_receipt_for_testing,
    authorization_signed_bytes,
    credential_ref_for_api_key,
    deployment_receipt_content_digest,
    issue_verified_deployment_transport_identity,
    pricing_approval_digest,
    pricing_evidence_digest,
    pricing_evidence_signed_bytes,
    provider_cap_approval_digest,
    provider_cap_evidence_digest,
    provider_cap_signed_bytes,
    require_verified_deployment_transport_identity,
    require_verified_pricing_capability,
    require_verified_provider_capability,
    require_verified_reconciled_receipt,
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
RUN = "golden-v01-run-031"
PURPOSE = "golden-v0.1 production run"
SCOPE = "goldenset-production"
STRONG = "qwen3.7-plus-2026-05-26-031strng"
WEAK = "deepseek-v4-flash-031weak1"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
_A_V5_SCHEMA_FIXTURE = Path(__file__).parent / "fixtures/031/a_v5_budget_schema.sql"
_PRE_PROVIDER_CAP_SIDECAR_V7_FIXTURE = (
    Path(__file__).parent / "fixtures/031/pre_provider_cap_sidecar_v7_budget_schema.sql"
)
_PRODUCTION_API_KEY = "test-only-production-cap-ledger-key-031"
_PRODUCTION_CREDENTIAL_REF = credential_ref_for_api_key(_PRODUCTION_API_KEY)

_A_V5_AUTHORIZATION_ROW = {
    "authorization_digest": "1" * 64,
    "domain": "insurancekb.run-admission.provisioning.v1",
    "envelope_json": b'{"legacy":"authorization"}',
    "run_identity": RUN,
    "purpose": PURPOSE,
    "operation_id": "op-legacy-a-v5-031",
    "reserve_id": "infra-legacy-a-v5-031",
    "recorded_at": NOW.isoformat(),
}


def _create_real_a_v5_infrastructure_ledger(
    db_path: Path,
) -> tuple[BudgetContract, dict[str, object]]:
    """Create a schema-v5 database without importing or instantiating current ledger code."""

    contract = _contract()
    plan = _plan(contract)
    account_id = budget_account_identity(RUN, PURPOSE)
    approval_digest = "8" * 64
    reserve_row: dict[str, object] = {
        "reserve_id": _A_V5_AUTHORIZATION_ROW["reserve_id"],
        "account_id": account_id,
        "run_identity": RUN,
        "purpose": PURPOSE,
        "operation_id": _A_V5_AUTHORIZATION_ROW["operation_id"],
        "authorization_digest": _A_V5_AUTHORIZATION_ROW["authorization_digest"],
        "pricing_evidence_digest": "2" * 64,
        "pricing_approval_digest": "3" * 64,
        "provider_cap_evidence_digest": "4" * 64,
        "provider_cap_approval_digest": "5" * 64,
        "provider_cap_max_cost": 10_000,
        "provider_cap_expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "provider": "bailian",
        "currency": "CNY",
        "workspace_ref": "workspace-legacy-a-v5-031",
        "project_ref": "sha256:" + "6" * 64,
        "credential_ref": "sha256:" + "7" * 64,
        "region": "cn-beijing",
        "base_model": "qwen3.7-plus-2026-05-26",
        "request_plan": "ptu_v2",
        "receipt_plan": "ptu",
        "input_tpm_quota": 10_000,
        "output_tpm_quota": 1_000,
        "covers_fixed_infrastructure": 1,
        "covers_inference": 1,
        "cleanup_deadline": (NOW + timedelta(hours=8)).isoformat(),
        "max_cost": 6_720,
        "state": "reserved",
        "created_at": NOW.isoformat(),
    }
    with sqlite3.connect(db_path) as connection:
        connection.executescript(_A_V5_SCHEMA_FIXTURE.read_text(encoding="utf-8"))
        connection.execute(
            """INSERT INTO budget_accounts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                account_id,
                RUN,
                PURPOSE,
                contract.currency,
                contract.ceiling.input_tokens,
                contract.ceiling.output_tokens,
                contract.ceiling.cost_minor_units,
                1,
                approval_digest,
                0,
            ),
        )
        connection.execute(
            """INSERT INTO budget_approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                account_id,
                1,
                approval_digest,
                None,
                plan_payload_hash(plan),
                budget_contract_hash(contract),
                contract.model_dump_json().encode("utf-8"),
                contract.ceiling.input_tokens,
                contract.ceiling.output_tokens,
                contract.ceiling.cost_minor_units,
            ),
        )
        connection.execute(
            f"""INSERT INTO infrastructure_authorizations
                ({', '.join(_A_V5_AUTHORIZATION_ROW)})
                VALUES ({', '.join('?' for _ in _A_V5_AUTHORIZATION_ROW)})""",
            tuple(_A_V5_AUTHORIZATION_ROW.values()),
        )
        connection.execute(
            f"""INSERT INTO infrastructure_reserves
                ({', '.join(reserve_row)})
                VALUES ({', '.join('?' for _ in reserve_row)})""",
            tuple(reserve_row.values()),
        )
    return contract, reserve_row


def _create_real_pre_provider_cap_sidecar_v7_ledger(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.executescript(_A_V5_SCHEMA_FIXTURE.read_text(encoding="utf-8"))
        connection.executescript(
            _PRE_PROVIDER_CAP_SIDECAR_V7_FIXTURE.read_text(encoding="utf-8")
        )


def test_o4_real_pre_sidecar_v7_migrates_to_v8_without_fabricating_cap_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "pre-sidecar-v7.sqlite3"
    _create_real_pre_provider_cap_sidecar_v7_ledger(db_path)
    with sqlite3.connect(db_path) as connection:
        before_reserve = connection.execute("SELECT * FROM infrastructure_reserves").fetchone()
        assert connection.execute("PRAGMA user_version").fetchone() == (7,)
        assert connection.execute(
            "SELECT COUNT(*) FROM infrastructure_reserves WHERE state='reserved'"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name='infrastructure_provider_cap_evidence'"
        ).fetchone() is None

    ledger = BudgetLedger(db_path)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (8,)
        assert connection.execute("SELECT * FROM infrastructure_reserves").fetchone() == (
            before_reserve
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM infrastructure_provider_cap_evidence"
        ).fetchone() == (0,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    monkeypatch.setattr(ledger, "_clock", lambda: NOW)
    monkeypatch.setattr(
        "insurance_harness.goldenset.admission_cli._load_deployment_approval_configuration",
        lambda: (
            _infra_policy(Ed25519PrivateKey.generate()),
            frozenset(),
            frozenset(),
            frozenset(),
        ),
    )
    with pytest.raises(BudgetLedgerError, match="provider-cap evidence is unavailable"):
        ledger.require_fresh_infrastructure_provider_capability(
            plan=_plan(_contract()),
            expected_scope=SCOPE,
            reserve_id="infra-pre-sidecar-v7-031",
        )


def test_o4_pre_sidecar_v7_ddl_failure_rolls_back_version_schema_and_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "pre-sidecar-v7-ddl-failure.sqlite3"
    _create_real_pre_provider_cap_sidecar_v7_ledger(db_path)

    def snapshot() -> tuple[object, ...]:
        with sqlite3.connect(db_path) as connection:
            return (
                connection.execute("PRAGMA user_version").fetchone(),
                connection.execute(
                    """SELECT type,name,sql FROM sqlite_master
                       WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"""
                ).fetchall(),
                connection.execute("SELECT * FROM infrastructure_authorizations").fetchall(),
                connection.execute("SELECT * FROM infrastructure_reserves").fetchall(),
                connection.execute("PRAGMA foreign_key_check").fetchall(),
            )

    before = snapshot()
    original_connect = BudgetLedger._connect

    def deny_sidecar_create(self: BudgetLedger) -> sqlite3.Connection:
        connection = original_connect(self)

        def authorize(
            action_code: int,
            arg1: str | None,
            _arg2: str | None,
            _database: str | None,
            _trigger: str | None,
        ) -> int:
            if (
                action_code == sqlite3.SQLITE_CREATE_TABLE
                and arg1 == "infrastructure_provider_cap_evidence"
            ):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        return connection

    monkeypatch.setattr(BudgetLedger, "_connect", deny_sidecar_create)

    with pytest.raises(BudgetLedgerError, match="schema migration failed"):
        BudgetLedger(db_path)

    assert snapshot() == before


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


def _evidence_policy(
    private_key: Ed25519PrivateKey,
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
            scopes=frozenset({SCOPE}),
            roles=frozenset({role}),
            public_key=private_key.public_key(),
        )
    }


def _signed_production_evidence(
    *,
    pricing_key: Ed25519PrivateKey,
    cap_key: Ed25519PrivateKey,
) -> tuple[bytes, PricingEvidenceApproval, bytes, ProviderCapApproval]:
    pricing_content = PricingEvidenceContent(
        version="insurancekb.run-admission.pricing-evidence.v1",
        issuer="aliyun-bailian-price-catalog",
        provider="bailian",
        workspace_ref="workspace-cn-beijing-031",
        project_ref="sha256:" + SHA_A,
        credential_ref=_PRODUCTION_CREDENTIAL_REF,
        region="cn-beijing",
        base_model="qwen3.7-plus-2026-05-26",
        request_plan="ptu_v2",
        receipt_plan="ptu",
        input_tpm_quota=10_000,
        output_tpm_quota=1_000,
        currency="CNY",
        effective_from=NOW - timedelta(days=1),
        effective_until=NOW + timedelta(days=1),
        billing_quantum_seconds=3600,
        round_up_rule="ceiling",
        fixed_cost_per_quantum_minor_units=672,
        input_cost_per_million_minor_units=240,
        output_cost_per_million_minor_units=960,
        tiers_policy="worst_case_included",
        thinking_policy="worst_case_included",
        cache_policy="worst_case_included",
        overflow_policy="block",
    )
    pricing_bytes = canonical_json_bytes(pricing_content)
    pricing_payload = PricingEvidenceApprovalPayload(
        evidence_digest=pricing_evidence_digest(pricing_bytes),
        evidence=pricing_content,
        scope=SCOPE,
        approver_identity="pricing-owner@example.test",
        approver_role="pricing-evidence-approver",
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
    )
    pricing_approval = PricingEvidenceApproval(
        domain=PRICING_EVIDENCE_DOMAIN,
        key_id="pricing-key",
        payload=pricing_payload,
        signature=base64.b64encode(
            pricing_key.sign(pricing_evidence_signed_bytes(pricing_payload))
        ).decode("ascii"),
    )

    cap_content = ProviderCapEvidenceContent(
        version="insurancekb.run-admission.provider-cap-evidence.v1",
        issuer="aliyun-bailian-spend-cap",
        provider="bailian",
        workspace_ref="workspace-cn-beijing-031",
        project_ref="sha256:" + SHA_A,
        credential_ref=_PRODUCTION_CREDENTIAL_REF,
        currency="CNY",
        max_cost_minor_units=20_000,
        coverage=("fixed_infrastructure", "inference"),
        observed_at=NOW - timedelta(minutes=2),
        expires_at=NOW + timedelta(hours=1),
    )
    cap_bytes = canonical_json_bytes(cap_content)
    cap_payload = ProviderCapApprovalPayload(
        evidence_digest=provider_cap_evidence_digest(cap_bytes),
        evidence=cap_content,
        scope=SCOPE,
        approver_identity="cap-attestor@example.test",
        approver_role="provider-cap-attestor",
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
    )
    cap_approval = ProviderCapApproval(
        domain=PROVIDER_CAP_DOMAIN,
        key_id="cap-key",
        payload=cap_payload,
        signature=base64.b64encode(cap_key.sign(provider_cap_signed_bytes(cap_payload))).decode(
            "ascii"
        ),
    )
    return pricing_bytes, pricing_approval, cap_bytes, cap_approval


@dataclass(frozen=True)
class _ProductionReserveFixture:
    ledger: BudgetLedger
    db_path: Path
    payload: ProvisioningAuthorizationPayload
    authorization: ProvisioningAuthorization
    permit: InfrastructureCreatePermit
    plan: RunAdmissionPlanPayload
    pricing_bytes: bytes
    pricing_approval: PricingEvidenceApproval
    cap_bytes: bytes
    cap_approval: ProviderCapApproval


def _production_reserve_with_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> _ProductionReserveFixture:
    pricing_key = Ed25519PrivateKey.generate()
    cap_key = Ed25519PrivateKey.generate()
    provisioning_key = Ed25519PrivateKey.generate()
    pricing_bytes, pricing_approval, cap_bytes, cap_approval = _signed_production_evidence(
        pricing_key=pricing_key,
        cap_key=cap_key,
    )
    payload = _authorization_payload(
        credential_ref=_PRODUCTION_CREDENTIAL_REF,
        pricing_evidence_digest=pricing_approval.payload.evidence_digest,
        pricing_approval_digest=pricing_approval_digest(pricing_approval),
        provider_cap_evidence_digest=cap_approval.payload.evidence_digest,
        provider_cap_approval_digest=provider_cap_approval_digest(cap_approval),
        provider_cap_max_cost_minor_units=20_000,
        provider_cap_expires_at=cap_approval.payload.evidence.expires_at,
        maximum_cost_minor_units=6_048,
    )
    authorization = _sign_authorization(provisioning_key, payload)
    authorities = {
        **_infra_policy(provisioning_key),
        **_evidence_policy(
            pricing_key,
            key_id="pricing-key",
            identity="pricing-owner@example.test",
            domain=PRICING_EVIDENCE_DOMAIN,
            role="pricing-evidence-approver",
        ),
        **_evidence_policy(
            cap_key,
            key_id="cap-key",
            identity="cap-attestor@example.test",
            domain=PROVIDER_CAP_DOMAIN,
            role="provider-cap-attestor",
        ),
    }
    monkeypatch.setattr("insurance_harness.goldenset.admission_budget._utc_now", lambda: NOW)
    monkeypatch.setattr(
        "insurance_harness.goldenset.admission_cli._load_deployment_approval_configuration",
        lambda: (authorities, frozenset(), frozenset(), frozenset()),
    )
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger(db_path)
    permit = ledger.reserve_provisioning_before_post(
        authorization=authorization,
        expected=payload,
        pricing_evidence_bytes=pricing_bytes,
        pricing_approval=pricing_approval,
        provider_cap_evidence_bytes=cap_bytes,
        provider_cap_approval=cap_approval,
    )
    contract = _contract(
        ceiling_cost=20_000,
        provider_cap_cost=20_000,
        provider_evidence_digest=cap_approval.payload.evidence_digest,
        credential_ref=_PRODUCTION_CREDENTIAL_REF,
    )
    return _ProductionReserveFixture(
        ledger=ledger,
        db_path=db_path,
        payload=payload,
        authorization=authorization,
        permit=permit,
        plan=_plan(contract),
        pricing_bytes=pricing_bytes,
        pricing_approval=pricing_approval,
        cap_bytes=cap_bytes,
        cap_approval=cap_approval,
    )


@pytest.mark.parametrize(
    "attack",
    ["copy", "construct", "serialization_restart", "mutate", "fork"],
)
def test_o4_i3_ledger_capability_clone_cannot_cross_transport_authority_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    capability = fixture.ledger.require_fresh_infrastructure_provider_capability(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=fixture.permit.reserve.reserve_id,
    )
    candidate = capability
    if attack == "copy":
        candidate = copy.copy(capability)
    elif attack == "construct":
        candidate = object.__new__(type(capability))
        for name in type(capability).__slots__:
            if name != "__weakref__":
                object.__setattr__(candidate, name, getattr(capability, name))
    elif attack == "serialization_restart":
        candidate = pickle.loads(pickle.dumps(capability))
    elif attack == "mutate":
        object.__setattr__(candidate, "workspace_ref", "attacker-workspace")
    else:
        parent_pid = os.getpid()
        monkeypatch.setattr(os, "getpid", lambda: parent_pid + 1)

    with pytest.raises(AuthorizationVerificationError, match="issuer|snapshot|required"):
        require_verified_infrastructure_provider_capability(candidate)


def test_o4_i2_provisioning_rechecks_expiry_after_begin_immediate_before_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_mutation = BudgetLedger._mutation

    @contextmanager
    def cross_expiry_after_lock(
        ledger: BudgetLedger,
    ) -> Any:
        with original_mutation(ledger) as connection:
            ledger._clock = lambda: NOW + timedelta(hours=2)
            yield connection

    monkeypatch.setattr(BudgetLedger, "_mutation", cross_expiry_after_lock)

    with pytest.raises(BudgetLedgerError, match="expired|stale|evidence"):
        _production_reserve_with_sidecar(tmp_path, monkeypatch)

    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM infrastructure_authorizations"
        ).fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM infrastructure_reserves").fetchone() == (
            0,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM infrastructure_provider_cap_evidence"
        ).fetchone() == (0,)


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


def _verified_receipt(
    *,
    cap_digest: str = SHA_D,
    cap_approval_digest: str = "f" * 64,
    run_identity: str = RUN,
    purpose: str = PURPOSE,
    scope: str = SCOPE,
    observed_at: datetime = NOW,
    expires_at: datetime = NOW + timedelta(minutes=5),
    **updates: Any,
) -> VerifiedReconciledDeploymentReceipt:
    receipt = _receipt(**updates)
    identity = _issue_verified_deployment_transport_identity_for_testing(
        workspace_ref=receipt.content.workspace_ref,
        project_ref=receipt.content.project_ref,
        credential_ref=receipt.content.credential_ref,
        provider_cap_evidence_digest=cap_digest,
        provider_cap_approval_digest=cap_approval_digest,
        expires_at=NOW + timedelta(hours=1),
    )
    return _issue_verified_reconciled_receipt_for_testing(
        receipt=receipt,
        transport_identity=identity,
        run_identity=run_identity,
        purpose=purpose,
        scope=scope,
        remote_manifest_digest=receipt.content.remote_manifest_digest,
        observed_at=observed_at,
        expires_at=expires_at,
    )


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
    receipt = _receipt()
    pricing = _pricing_capability(payload)
    provider_cap = _cap_capability(payload)
    identity = _issue_verified_deployment_transport_identity_for_testing(
        workspace_ref=payload.workspace_ref,
        project_ref=payload.project_ref,
        credential_ref=payload.credential_ref,
        provider_cap_evidence_digest=payload.provider_cap_evidence_digest,
        expires_at=payload.provider_cap_expires_at,
    )
    reconciled = _issue_verified_reconciled_receipt_for_testing(
        receipt=receipt,
        transport_identity=identity,
        run_identity=payload.run_identity,
        purpose=payload.purpose,
        scope=payload.scope,
        remote_manifest_digest=receipt.content.remote_manifest_digest,
        observed_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )

    for require, capability in (
        (require_verified_pricing_capability, pricing),
        (require_verified_provider_capability, provider_cap),
        (require_verified_deployment_transport_identity, identity),
        (require_verified_reconciled_receipt, reconciled),
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


def test_o4_schema_v8_fresh_reserve_is_durable_before_account_or_deployment(
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
        assert connection.execute("PRAGMA user_version").fetchone() == (8,)
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM infrastructure_reserves").fetchone() == (1,)
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


def test_o4_adoption_requires_receipt_verified_against_independent_remote_expected() -> None:
    local = _receipt()
    remote = _receipt(gmt_modified=NOW - timedelta(minutes=1))

    with pytest.raises(AuthorizationVerificationError, match="trusted provider"):
        verify_reconciled_deployment_receipt(local, remote_expected=remote)


def test_o4_cloned_receipts_cannot_self_mint_verified_reconciliation() -> None:
    forged = _receipt()
    caller_clone = DeploymentReceipt.model_validate(
        forged.model_dump(mode="python", round_trip=True)
    )

    with pytest.raises(AuthorizationVerificationError, match="trusted provider"):
        verify_reconciled_deployment_receipt(forged, remote_expected=caller_clone)


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


def test_o4_production_reserve_can_reissue_fresh_provider_cap_without_topology(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pricing_key = Ed25519PrivateKey.generate()
    cap_key = Ed25519PrivateKey.generate()
    provisioning_key = Ed25519PrivateKey.generate()
    pricing_bytes, pricing_approval, cap_bytes, cap_approval = _signed_production_evidence(
        pricing_key=pricing_key,
        cap_key=cap_key,
    )
    payload = _authorization_payload(
        credential_ref=_PRODUCTION_CREDENTIAL_REF,
        pricing_evidence_digest=pricing_approval.payload.evidence_digest,
        pricing_approval_digest=pricing_approval_digest(pricing_approval),
        provider_cap_evidence_digest=cap_approval.payload.evidence_digest,
        provider_cap_approval_digest=provider_cap_approval_digest(cap_approval),
        provider_cap_max_cost_minor_units=20_000,
        provider_cap_expires_at=cap_approval.payload.evidence.expires_at,
        maximum_cost_minor_units=6_048,
    )
    authorities = {
        **_infra_policy(provisioning_key),
        **_evidence_policy(
            pricing_key,
            key_id="pricing-key",
            identity="pricing-owner@example.test",
            domain=PRICING_EVIDENCE_DOMAIN,
            role="pricing-evidence-approver",
        ),
        **_evidence_policy(
            cap_key,
            key_id="cap-key",
            identity="cap-attestor@example.test",
            domain=PROVIDER_CAP_DOMAIN,
            role="provider-cap-attestor",
        ),
    }
    monkeypatch.setattr(
        "insurance_harness.goldenset.admission_budget._utc_now",
        lambda: NOW,
    )
    monkeypatch.setattr(
        "insurance_harness.goldenset.admission_cli._load_deployment_approval_configuration",
        lambda: (authorities, frozenset(), frozenset(), frozenset()),
    )
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger(db_path)

    permit = ledger.reserve_provisioning_before_post(
        authorization=_sign_authorization(provisioning_key, payload),
        expected=payload,
        pricing_evidence_bytes=pricing_bytes,
        pricing_approval=pricing_approval,
        provider_cap_evidence_bytes=cap_bytes,
        provider_cap_approval=cap_approval,
    )
    with sqlite3.connect(db_path) as connection:
        topology_count = connection.execute(
            "SELECT COUNT(*) FROM final_infrastructure_topologies"
        ).fetchone()
        assert topology_count == (0,)

    capability = ledger.require_fresh_infrastructure_provider_capability(
        plan=_plan(
            _contract(
                ceiling_cost=20_000,
                provider_cap_cost=20_000,
                provider_evidence_digest=cap_approval.payload.evidence_digest,
                credential_ref=_PRODUCTION_CREDENTIAL_REF,
            )
        ),
        expected_scope=SCOPE,
        reserve_id=permit.reserve.reserve_id,
    )

    assert capability.reserve_id == permit.reserve.reserve_id
    assert capability.run_identity == RUN
    assert capability.purpose == PURPOSE
    assert capability.scope == SCOPE
    assert capability.operation_id == payload.operation_id
    assert capability.evidence_digest == cap_approval.payload.evidence_digest


def test_o5_generic_caller_verified_cap_cannot_issue_production_transport_identity() -> None:
    cap_key = Ed25519PrivateKey.generate()
    _, _, cap_bytes, cap_approval = _signed_production_evidence(
        pricing_key=Ed25519PrivateKey.generate(),
        cap_key=cap_key,
    )
    caller_verified_cap = verify_provider_cap_evidence(
        cap_bytes,
        envelope=cap_approval,
        trusted_authorities=_evidence_policy(
            cap_key,
            key_id="cap-key",
            identity="cap-attestor@example.test",
            domain=PROVIDER_CAP_DOMAIN,
            role="provider-cap-attestor",
        ),
        expected_scope=SCOPE,
        now=NOW,
    )

    with pytest.raises(AuthorizationVerificationError, match="ledger"):
        issue_verified_deployment_transport_identity(
            api_key=_PRODUCTION_API_KEY,
            provider_capability=caller_verified_cap,
        )


def test_o5_infrastructure_module_exposes_no_caller_bindable_ledger_cap_issuer() -> None:
    cap_key = Ed25519PrivateKey.generate()
    _, _, cap_bytes, cap_approval = _signed_production_evidence(
        pricing_key=Ed25519PrivateKey.generate(),
        cap_key=cap_key,
    )
    caller_verified_cap = verify_provider_cap_evidence(
        cap_bytes,
        envelope=cap_approval,
        trusted_authorities=_evidence_policy(
            cap_key,
            key_id="cap-key",
            identity="cap-attestor@example.test",
            domain=PROVIDER_CAP_DOMAIN,
            role="provider-cap-attestor",
        ),
        expected_scope=SCOPE,
        now=NOW,
    )
    helper = getattr(
        admission_infrastructure,
        "_issue_verified_infrastructure_provider_capability_from_ledger",
        None,
    )
    if helper is not None:
        forged_ledger_cap = helper(
            caller_verified_cap,
            run_identity=RUN,
            purpose=PURPOSE,
            scope=SCOPE,
            operation_id="op-attacker-031",
            reserve_id="infra-attacker-031",
        )
        forged_identity = issue_verified_deployment_transport_identity(
            api_key=_PRODUCTION_API_KEY,
            provider_capability=forged_ledger_cap,
        )
        pytest.fail(
            f"caller-bindable helper forged production transport {forged_identity.identity_digest}"
        )

    assert helper is None


@pytest.mark.parametrize(
    ("column", "replacement"),
    (
        ("evidence_bytes", b"{}"),
        ("approval_envelope_bytes", b"{}"),
        ("evidence_digest", "0" * 64),
        ("approval_digest", "0" * 64),
    ),
)
def test_o4_fresh_infrastructure_cap_rejects_tampered_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    column: str,
    replacement: object,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    with sqlite3.connect(fixture.db_path) as connection:
        connection.execute(
            f"UPDATE infrastructure_provider_cap_evidence SET {column}=? WHERE reserve_id=?",
            (replacement, fixture.permit.reserve.reserve_id),
        )

    with pytest.raises(BudgetLedgerError, match="provider-cap|sidecar"):
        fixture.ledger.require_fresh_infrastructure_provider_capability(
            plan=fixture.plan,
            expected_scope=SCOPE,
            reserve_id=fixture.permit.reserve.reserve_id,
        )


def test_o4_fresh_infrastructure_cap_rejects_missing_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    with sqlite3.connect(fixture.db_path) as connection:
        connection.execute(
            "DELETE FROM infrastructure_provider_cap_evidence WHERE reserve_id=?",
            (fixture.permit.reserve.reserve_id,),
        )

    with pytest.raises(BudgetLedgerError, match="unavailable"):
        fixture.ledger.require_fresh_infrastructure_provider_capability(
            plan=fixture.plan,
            expected_scope=SCOPE,
            reserve_id=fixture.permit.reserve.reserve_id,
        )


@pytest.mark.parametrize(
    ("table_name", "column_name", "replacement"),
    (
        ("infrastructure_authorizations", "authorization_digest", "9" * 64),
        ("infrastructure_authorizations", "domain", "untrusted-domain"),
        ("infrastructure_authorizations", "envelope_json", b"{}"),
        ("infrastructure_authorizations", "run_identity", "run-row-drift"),
        ("infrastructure_authorizations", "purpose", "purpose-row-drift"),
        ("infrastructure_authorizations", "operation_id", "operation-row-drift"),
        ("infrastructure_authorizations", "reserve_id", "reserve-row-drift"),
        ("infrastructure_authorizations", "recorded_at", (NOW - timedelta(minutes=1)).isoformat()),
        ("infrastructure_reserves", "reserve_id", "reserve-primary-row-drift"),
        ("infrastructure_reserves", "account_id", "account-row-drift"),
        ("infrastructure_reserves", "run_identity", "run-reserve-row-drift"),
        ("infrastructure_reserves", "purpose", "purpose-reserve-row-drift"),
        ("infrastructure_reserves", "operation_id", "operation-reserve-row-drift"),
        ("infrastructure_reserves", "authorization_digest", "9" * 64),
        ("infrastructure_reserves", "pricing_evidence_digest", "0" * 64),
        ("infrastructure_reserves", "pricing_approval_digest", "0" * 64),
        ("infrastructure_reserves", "provider_cap_evidence_digest", "0" * 64),
        ("infrastructure_reserves", "provider_cap_approval_digest", "0" * 64),
        ("infrastructure_reserves", "provider_cap_max_cost", 20_001),
        (
            "infrastructure_reserves",
            "provider_cap_expires_at",
            (NOW + timedelta(hours=2)).isoformat(),
        ),
        ("infrastructure_reserves", "provider", "other-provider"),
        ("infrastructure_reserves", "currency", "USD"),
        ("infrastructure_reserves", "workspace_ref", "workspace-row-drift"),
        ("infrastructure_reserves", "project_ref", "sha256:" + "8" * 64),
        ("infrastructure_reserves", "credential_ref", "sha256:" + "9" * 64),
        ("infrastructure_reserves", "region", "region-row-drift"),
        ("infrastructure_reserves", "base_model", "base-row-drift"),
        ("infrastructure_reserves", "request_plan", "request-row-drift"),
        ("infrastructure_reserves", "receipt_plan", "receipt-row-drift"),
        ("infrastructure_reserves", "input_tpm_quota", 20_000),
        ("infrastructure_reserves", "output_tpm_quota", 2_000),
        ("infrastructure_reserves", "covers_fixed_infrastructure", 0),
        ("infrastructure_reserves", "covers_inference", 0),
        ("infrastructure_reserves", "cleanup_deadline", NOW.isoformat()),
        ("infrastructure_reserves", "max_cost", 6_049),
        ("infrastructure_reserves", "state", "bound"),
        ("infrastructure_reserves", "deployed_model", "forged-deployment"),
        ("infrastructure_reserves", "receipt_digest", "8" * 64),
        ("infrastructure_reserves", "remote_manifest_digest", "8" * 64),
        ("infrastructure_reserves", "receipt_json", b"{}"),
        ("infrastructure_reserves", "final_approval_digest", "8" * 64),
        ("infrastructure_reserves", "created_at", (NOW - timedelta(minutes=1)).isoformat()),
        ("infrastructure_reserves", "bound_at", NOW.isoformat()),
        ("infrastructure_provider_cap_evidence", "reserve_id", "sidecar-reserve-drift"),
        ("infrastructure_provider_cap_evidence", "evidence_bytes", b"{}"),
        ("infrastructure_provider_cap_evidence", "approval_envelope_bytes", b"{}"),
        ("infrastructure_provider_cap_evidence", "evidence_digest", "0" * 64),
        ("infrastructure_provider_cap_evidence", "approval_digest", "0" * 64),
        (
            "infrastructure_provider_cap_evidence",
            "recorded_at",
            (NOW + timedelta(minutes=1)).isoformat(),
        ),
    ),
)
def test_o4_fresh_infrastructure_cap_rejects_redundant_row_drift_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    table_name: str,
    column_name: str,
    replacement: object,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    with sqlite3.connect(fixture.db_path) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            f"UPDATE {table_name} SET {column_name}=?",
            (replacement,),
        )
        before = {
            name: connection.execute(f"SELECT * FROM {name}").fetchall()
            for name in (
                "infrastructure_authorizations",
                "infrastructure_reserves",
                "infrastructure_provider_cap_evidence",
            )
        }

    with pytest.raises(BudgetLedgerError, match="unavailable|invalid|non-canonical|drift"):
        fixture.ledger.require_fresh_infrastructure_provider_capability(
            plan=fixture.plan,
            expected_scope=SCOPE,
            reserve_id=fixture.permit.reserve.reserve_id,
        )

    with sqlite3.connect(fixture.db_path) as connection:
        after = {
            name: connection.execute(f"SELECT * FROM {name}").fetchall()
            for name in before
        }
    assert after == before


@pytest.mark.parametrize("drift", ("reserve", "run", "scope"))
def test_o4_fresh_infrastructure_cap_rejects_wrong_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    plan = fixture.plan
    expected_scope = SCOPE
    reserve_id = fixture.permit.reserve.reserve_id
    if drift == "reserve":
        reserve_id = "infra-other-031"
    elif drift == "run":
        plan = _plan(
            _contract(
                ceiling_cost=20_000,
                provider_cap_cost=20_000,
                credential_ref=_PRODUCTION_CREDENTIAL_REF,
            ),
            run_identity="golden-v01-run-031-other",
        )
    else:
        expected_scope = "goldenset-production-other"

    with pytest.raises(BudgetLedgerError, match="unavailable|drift|scope|invalid"):
        fixture.ledger.require_fresh_infrastructure_provider_capability(
            plan=plan,
            expected_scope=expected_scope,
            reserve_id=reserve_id,
        )


def test_o4_fresh_infrastructure_cap_rejects_expiry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    monkeypatch.setattr(fixture.ledger, "_clock", lambda: NOW + timedelta(hours=2))

    with pytest.raises(BudgetLedgerError, match="stale|invalid"):
        fixture.ledger.require_fresh_infrastructure_provider_capability(
            plan=fixture.plan,
            expected_scope=SCOPE,
            reserve_id=fixture.permit.reserve.reserve_id,
        )


def test_o4_testing_reserve_has_no_production_cap_sidecar_or_capability(tmp_path: Path) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    permit = _reserve(ledger, Ed25519PrivateKey.generate())
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM infrastructure_provider_cap_evidence"
        ).fetchone() == (0,)

    with pytest.raises(BudgetLedgerError, match="production ledger"):
        ledger.require_fresh_infrastructure_provider_capability(
            plan=_plan(_contract()),
            expected_scope=SCOPE,
            reserve_id=permit.reserve.reserve_id,
        )


def test_o4_production_sidecar_exact_replay_is_single_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)

    replay = fixture.ledger.reserve_provisioning_before_post(
        authorization=fixture.authorization,
        expected=fixture.payload,
        pricing_evidence_bytes=fixture.pricing_bytes,
        pricing_approval=fixture.pricing_approval,
        provider_cap_evidence_bytes=fixture.cap_bytes,
        provider_cap_approval=fixture.cap_approval,
    )

    assert replay == fixture.permit
    with sqlite3.connect(fixture.db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM infrastructure_provider_cap_evidence"
        ).fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM infrastructure_reserves").fetchone() == (
            1,
        )


def test_o4_production_sidecar_conflict_does_not_partially_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    before = fixture.db_path.read_bytes()

    with pytest.raises(BudgetLedgerError, match="signed|evidence|invalid"):
        fixture.ledger.reserve_provisioning_before_post(
            authorization=fixture.authorization,
            expected=fixture.payload,
            pricing_evidence_bytes=fixture.pricing_bytes,
            pricing_approval=fixture.pricing_approval,
            provider_cap_evidence_bytes=fixture.cap_bytes + b" ",
            provider_cap_approval=fixture.cap_approval,
        )

    assert fixture.db_path.read_bytes() == before


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
        "bind_final_infrastructure_contract",
        "bind_final_infrastructure_topology",
        "require_fresh_final_topology",
    ),
)
def test_o3_o4_o7_production_budget_entrypoints_do_not_accept_caller_freshness_time(
    method_name: str,
) -> None:
    assert "now" not in inspect.signature(getattr(BudgetLedger, method_name)).parameters


def test_o6_public_production_single_final_bind_requires_atomic_topology_without_writes(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    testing_ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    infrastructure_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    permit = _reserve(testing_ledger, infrastructure_key)
    contract = _contract()
    production_ledger = BudgetLedger(db_path)
    with sqlite3.connect(db_path) as connection:
        before_tables = {
            table_name: connection.execute(f"SELECT * FROM {table_name}").fetchall()
            for table_name in (
                "budget_accounts",
                "budget_approvals",
                "infrastructure_reserves",
                "deployment_role_bindings",
            )
        }
    database_before = db_path.read_bytes()

    with pytest.raises(
        BudgetLedgerError,
        match="^atomic production topology binding is required$",
    ):
        production_ledger.bind_final_infrastructure_contract(
            reserve_id=permit.reserve.reserve_id,
            authorization=_sign_authorization(infrastructure_key, _authorization_payload()),
            expected_authorization=_authorization_payload(),
            receipt_capability=_verified_receipt(),
            roles=("annotator", "judge"),
            plan=_plan(contract),
            contract=contract,
            envelope=_budget_envelope(budget_key, contract),
            expected_scope=SCOPE,
        )

    assert db_path.read_bytes() == database_before
    with sqlite3.connect(db_path) as connection:
        after_tables = {
            table_name: connection.execute(f"SELECT * FROM {table_name}").fetchall()
            for table_name in before_tables
        }
    assert after_tables == before_tables
    assert production_ledger.infrastructure_reserve(permit.reserve.reserve_id).state == "reserved"


def test_o4_private_transaction_helpers_require_explicit_test_ledger_before_all_work(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger(db_path)
    infra_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    payload = _authorization_payload()
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
        assert authorization_count == (0,)
        assert connection.execute("SELECT COUNT(*) FROM infrastructure_reserves").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM deployment_role_bindings").fetchone() == (
            0,
        )
        assert connection.execute("SELECT COUNT(*) FROM budget_accounts").fetchone() == (0,)


def test_o4_production_ledger_direct_single_transaction_requires_root_evidence(
    tmp_path: Path,
) -> None:
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")
    contract = _contract()
    key = Ed25519PrivateKey.generate()

    with pytest.raises(BudgetLedgerError, match="production final bind requires"):
        ledger._bind_final_infrastructure_contract_transaction(
            reserve_id="infra-strong-031",
            receipt_capability=_verified_receipt(),
            roles=("annotator", "judge"),
            plan=_plan(contract),
            contract=contract,
            envelope=_budget_envelope(key, contract),
            trusted_public_keys={"finance-key": key.public_key()},
            expected_scope=SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=NOW,
        )


def test_o8_production_ledger_direct_dual_transaction_cannot_use_testing_branch(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    testing_ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    infra_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    strong_payload = _authorization_payload()
    weak_payload = _authorization_payload(
        operation_id="op-weak-031",
        infrastructure_reserve_id="infra-weak-031",
        base_model="deepseek-v4-flash",
        maximum_cost_minor_units=1_000,
    )
    _reserve(testing_ledger, infra_key, payload=strong_payload)
    _reserve(testing_ledger, infra_key, payload=weak_payload)
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
    production_ledger = BudgetLedger(db_path)
    database_before = db_path.read_bytes()

    with pytest.raises(
        BudgetLedgerError, match="production final topology requires signed binding requests"
    ):
        production_ledger._bind_final_infrastructure_topology_transaction(
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

    assert db_path.read_bytes() == database_before


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


def test_o4_o6_final_binding_is_atomic_and_shared_strong_cost_is_counted_once(
    tmp_path: Path,
) -> None:
    ledger = BudgetLedger._for_testing(tmp_path / "budget.sqlite3", clock=lambda: NOW)
    infra_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    permit = _reserve(ledger, infra_key)
    contract = _contract()

    bound = ledger._bind_final_infrastructure_contract_for_testing(
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

    assert bound.state == "bound"
    assert bound.deployed_model == STRONG
    assert bound.roles == ("annotator", "judge")
    account = ledger.account_snapshot(budget_account_identity(RUN, PURPOSE))
    assert account.reserved.cost_minor_units == 6_720
    replay = ledger._bind_final_infrastructure_contract_for_testing(
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
        assert connection.execute("SELECT COUNT(*) FROM deployment_role_bindings").fetchone() == (
            0,
        )


@pytest.mark.parametrize("mismatch_target", ["strong", "weak"])
def test_o4_o6_final_topology_rejects_receipt_cap_approval_drift_before_write(
    tmp_path: Path,
    mismatch_target: str,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    infra_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    reserved_approval = "7" * 64
    strong_payload = _authorization_payload(
        provider_cap_approval_digest=reserved_approval,
    )
    weak_payload = _authorization_payload(
        operation_id="op-weak-031",
        infrastructure_reserve_id="infra-weak-031",
        base_model="deepseek-v4-flash",
        maximum_cost_minor_units=1_000,
        provider_cap_approval_digest=reserved_approval,
    )
    _reserve(ledger, infra_key, payload=strong_payload)
    _reserve(ledger, infra_key, payload=weak_payload)
    mismatched_approval = "f" * 64
    strong_receipt = _verified_receipt(
        cap_approval_digest=(
            mismatched_approval if mismatch_target == "strong" else reserved_approval
        )
    )
    weak_receipt = _verified_receipt(
        cap_approval_digest=(
            mismatched_approval if mismatch_target == "weak" else reserved_approval
        ),
        operation_id="op-weak-031",
        infrastructure_reserve_id="infra-weak-031",
        base_model="deepseek-v4-flash",
        deployed_model=WEAK,
        operation_marker="ikb031-" + "4" * 24,
        deployment_suffix="031-" + "5" * 16,
        remote_manifest_digest="6" * 64,
    )
    contract = _contract()
    database_before = db_path.read_bytes()

    with pytest.raises(BudgetLedgerError, match="authorization or cap"):
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

    assert db_path.read_bytes() == database_before
    assert ledger.infrastructure_reserve("infra-strong-031").state == "reserved"
    assert ledger.infrastructure_reserve("infra-weak-031").state == "reserved"


@pytest.mark.parametrize(
    ("column", "drifted"),
    [
        ("remote_manifest_digest", "9" * 64),
        ("receipt_json", b"{}"),
    ],
)
def test_o6_two_reserve_bound_replay_rejects_durable_receipt_drift(
    tmp_path: Path,
    column: str,
    drifted: str | bytes,
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
    bindings: tuple[
        tuple[str, VerifiedReconciledDeploymentReceipt, tuple[BudgetRole, ...]],
        tuple[str, VerifiedReconciledDeploymentReceipt, tuple[BudgetRole, ...]],
    ] = (
        ("infra-strong-031", strong_receipt, ("annotator", "judge")),
        ("infra-weak-031", weak_receipt, ("weak_extractor",)),
    )
    plan = _plan(contract)
    envelope = _budget_envelope(budget_key, contract)

    def bind() -> tuple[InfrastructureReserveSnapshot, InfrastructureReserveSnapshot]:
        return ledger._bind_final_infrastructure_topology_for_testing(
            bindings=bindings,
            plan=plan,
            contract=contract,
            envelope=envelope,
            trusted_public_keys={"finance-key": budget_key.public_key()},
            expected_scope=SCOPE,
            authorized_roles=frozenset({"budget_approver"}),
            now=NOW,
        )

    bind()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"UPDATE infrastructure_reserves SET {column}=? WHERE reserve_id=?",
            (drifted, "infra-strong-031"),
        )

    with pytest.raises(BudgetLedgerError, match="replay conflict"):
        bind()

    assert ledger.infrastructure_reserve("infra-weak-031").state == "bound"


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
        _contract(workspace_ref="workspace-other-031"),
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
    account = ledger._open_or_expand_account_for_testing(
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


def test_o4_shared_provider_cap_combines_fixed_and_inference_across_accounts(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    budget_key = Ed25519PrivateKey.generate()
    infra_key = Ed25519PrivateKey.generate()
    contract = _contract(
        ceiling_cost=10_000,
        provider_cap_cost=10_000,
        product_max_cost=4_500,
    )
    identities = (
        (RUN, PURPOSE, "op-strong-031", "infra-strong-031", "qwen3.7-plus-2026-05-26"),
        (
            "golden-v01-run-031-second",
            "golden-v0.1 independent replay",
            "op-weak-cross-run-031",
            "infra-weak-cross-run-031",
            "deepseek-v4-flash",
        ),
    )
    accounts: list[str] = []
    for index, (run_identity, purpose, operation_id, reserve_id, base_model) in enumerate(
        identities
    ):
        plan = _plan(contract, run_identity=run_identity, purpose=purpose)
        account = ledger._open_or_expand_account_for_testing(
            plan=plan,
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
        _reserve(
            ledger,
            infra_key,
            payload=_authorization_payload(
                run_identity=run_identity,
                purpose=purpose,
                operation_id=operation_id,
                infrastructure_reserve_id=reserve_id,
                base_model=base_model,
                pricing_evidence_digest=("c" if index == 0 else "1") * 64,
                maximum_cost_minor_units=1_000,
            ),
        )

    maximum = BudgetAmounts(input_tokens=0, output_tokens=0, cost_minor_units=4_500)
    barrier = Barrier(2)

    def reserve_product(account_id: str) -> str | None:
        concurrent_ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
        barrier.wait(timeout=5)
        try:
            concurrent_ledger.reserve_product(account_id, "extraction", "product-01", maximum)
        except BudgetLedgerError as exc:
            assert "provider cap" in str(exc)
            return None
        return account_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(reserve_product, accounts))

    successful_account = next(result for result in results if result is not None)
    assert sum(result is not None for result in results) == 1
    ledger.reserve_product(successful_account, "extraction", "product-01", maximum)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(max_cost), 0) FROM infrastructure_reserves"
        ).fetchone() == (2, 2_000)
        assert connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(max_cost), 0) FROM product_reservations"
        ).fetchone() == (1, 4_500)


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


def test_o4_shared_inference_cap_applies_without_infrastructure_rows(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    budget_key = Ed25519PrivateKey.generate()
    contract = _contract(
        ceiling_cost=10_000,
        provider_cap_cost=10_000,
        product_max_cost=6_000,
    )
    accounts: list[str] = []
    for index in range(2):
        run_identity = f"golden-v01-run-031-inference-{index}"
        purpose = f"golden-v0.1 inference account {index}"
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
    with pytest.raises(BudgetLedgerError, match="provider cap"):
        ledger.reserve_product(accounts[1], "extraction", "product-01", maximum)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(max_cost), 0) FROM product_reservations"
        ).fetchone() == (1, 6_000)


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

    with pytest.raises(BudgetLedgerError, match="deployment"):
        ledger._bind_final_infrastructure_contract_for_testing(
            reserve_id=second.reserve.reserve_id,
            receipt_capability=_verified_receipt(
                operation_id="op-duplicate-031",
                infrastructure_reserve_id="infra-duplicate-031",
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


def test_o4_v8_missing_or_drifted_infrastructure_schema_fails_closed(tmp_path: Path) -> None:
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

    topology_missing_path = tmp_path / "topology-missing.sqlite3"
    BudgetLedger(topology_missing_path)
    with sqlite3.connect(topology_missing_path) as connection:
        connection.execute("DROP TABLE final_infrastructure_topologies")
    with pytest.raises(BudgetLedgerError, match="final topology schema"):
        BudgetLedger(topology_missing_path)

    topology_drifted_path = tmp_path / "topology-drifted.sqlite3"
    BudgetLedger(topology_drifted_path)
    with sqlite3.connect(topology_drifted_path) as connection:
        connection.execute("ALTER TABLE final_infrastructure_topologies ADD COLUMN untrusted TEXT")
    with pytest.raises(BudgetLedgerError, match="drifted"):
        BudgetLedger(topology_drifted_path)

    annex_missing_path = tmp_path / "annex-missing.sqlite3"
    BudgetLedger(annex_missing_path)
    with sqlite3.connect(annex_missing_path) as connection:
        connection.execute("DROP TABLE final_topology_receipt_annexes")
    with pytest.raises(BudgetLedgerError, match="receipt annex schema"):
        BudgetLedger(annex_missing_path)

    annex_drifted_path = tmp_path / "annex-drifted.sqlite3"
    BudgetLedger(annex_drifted_path)
    with sqlite3.connect(annex_drifted_path) as connection:
        connection.execute("ALTER TABLE final_topology_receipt_annexes ADD COLUMN untrusted TEXT")
    with pytest.raises(BudgetLedgerError, match="drifted"):
        BudgetLedger(annex_drifted_path)

    sidecar_missing_path = tmp_path / "provider-cap-sidecar-missing.sqlite3"
    BudgetLedger(sidecar_missing_path)
    with sqlite3.connect(sidecar_missing_path) as connection:
        connection.execute("DROP TABLE infrastructure_provider_cap_evidence")
    with pytest.raises(BudgetLedgerError, match="provider-cap sidecar"):
        BudgetLedger(sidecar_missing_path)

    sidecar_drifted_path = tmp_path / "provider-cap-sidecar-drifted.sqlite3"
    BudgetLedger(sidecar_drifted_path)
    with sqlite3.connect(sidecar_drifted_path) as connection:
        connection.execute(
            "ALTER TABLE infrastructure_provider_cap_evidence ADD COLUMN untrusted TEXT"
        )
    with pytest.raises(BudgetLedgerError, match="drifted"):
        BudgetLedger(sidecar_drifted_path)


def test_o4_real_a_v5_to_v8_migration_preserves_rows_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    contract, legacy_reserve = _create_real_a_v5_infrastructure_ledger(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        assert tuple(connection.execute("PRAGMA user_version").fetchone()) == (5,)
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert tables == {
            "budget_accounts",
            "budget_approvals",
            "product_limits",
            "request_limits",
            "product_reservations",
            "request_attempts",
            "request_pool_limits",
            "canary_capability_claims",
            "infrastructure_authorizations",
            "infrastructure_reserves",
        }
        reserve_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(infrastructure_reserves)")
        }
        assert reserve_columns == set(legacy_reserve)
        assert reserve_columns.isdisjoint(
            {
                "deployed_model",
                "receipt_digest",
                "remote_manifest_digest",
                "receipt_json",
                "final_approval_digest",
                "bound_at",
            }
        )
        assert dict(
            connection.execute("SELECT * FROM infrastructure_authorizations").fetchone()
        ) == _A_V5_AUTHORIZATION_ROW
        assert dict(connection.execute("SELECT * FROM infrastructure_reserves").fetchone()) == (
            legacy_reserve
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    migrated = BudgetLedger(db_path)

    with pytest.raises(BudgetLedgerError, match="topology evidence is unavailable"):
        migrated.require_fresh_final_topology(
            plan=_plan(contract),
            expected_scope=SCOPE,
        )
    monkeypatch.setattr(migrated, "_clock", lambda: NOW)
    monkeypatch.setattr(
        "insurance_harness.goldenset.admission_cli._load_deployment_approval_configuration",
        lambda: (
            _infra_policy(Ed25519PrivateKey.generate()),
            frozenset(),
            frozenset(),
            frozenset(),
        ),
    )
    with pytest.raises(BudgetLedgerError, match="provider-cap evidence is unavailable"):
        migrated.require_fresh_infrastructure_provider_capability(
            plan=_plan(contract),
            expected_scope=SCOPE,
            reserve_id=str(legacy_reserve["reserve_id"]),
        )
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        assert tuple(connection.execute("PRAGMA user_version").fetchone()) == (8,)
        authorization = dict(
            connection.execute("SELECT * FROM infrastructure_authorizations").fetchone()
        )
        reserve = dict(connection.execute("SELECT * FROM infrastructure_reserves").fetchone())
        assert authorization == _A_V5_AUTHORIZATION_ROW
        assert {column: reserve[column] for column in legacy_reserve} == legacy_reserve
        assert {
            column: reserve[column]
            for column in (
                "deployed_model",
                "receipt_digest",
                "remote_manifest_digest",
                "receipt_json",
                "final_approval_digest",
                "bound_at",
            )
        } == {
            "deployed_model": None,
            "receipt_digest": None,
            "remote_manifest_digest": None,
            "receipt_json": None,
            "final_approval_digest": None,
            "bound_at": None,
        }
        for table_name in (
            "deployment_role_bindings",
            "final_infrastructure_topologies",
            "final_topology_receipt_annexes",
            "infrastructure_provider_cap_evidence",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_o6_v6_to_v8_migration_creates_empty_receipt_annex_and_cap_sidecar(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "budget.sqlite3"
    old = BudgetLedger._for_testing(db_path, clock=lambda: NOW)
    infrastructure_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    permit = _reserve(old, infrastructure_key)
    contract = _contract()
    plan = _plan(contract)
    old._bind_final_infrastructure_contract_for_testing(
        reserve_id=permit.reserve.reserve_id,
        receipt_capability=_verified_receipt(),
        roles=("annotator", "judge"),
        plan=plan,
        contract=contract,
        envelope=_budget_envelope(budget_key, contract),
        trusted_public_keys={"finance-key": budget_key.public_key()},
        expected_scope=SCOPE,
        authorized_roles=frozenset({"budget_approver"}),
        now=NOW,
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE IF EXISTS final_topology_receipt_annexes")
        connection.execute("DROP TABLE IF EXISTS infrastructure_provider_cap_evidence")
        connection.execute("PRAGMA user_version = 6")

    migrated = BudgetLedger(db_path)

    with pytest.raises(BudgetLedgerError, match="topology evidence is unavailable"):
        migrated.require_fresh_final_topology(
            plan=plan,
            expected_scope=SCOPE,
        )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (8,)
        assert connection.execute(
            "SELECT COUNT(*) FROM final_topology_receipt_annexes"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM infrastructure_provider_cap_evidence"
        ).fetchone() == (0,)


def test_o4_v4_to_v8_migration_preserves_existing_budget_rows(tmp_path: Path) -> None:
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
        connection.execute("DROP TABLE final_topology_receipt_annexes")
        connection.execute("DROP TABLE final_infrastructure_topologies")
        connection.execute("DROP TABLE infrastructure_provider_cap_evidence")
        connection.execute("DROP TABLE deployment_role_bindings")
        connection.execute("DROP TABLE infrastructure_reserves")
        connection.execute("DROP TABLE infrastructure_authorizations")
        connection.execute("PRAGMA user_version = 4")

    migrated = BudgetLedger(db_path)

    assert migrated.account_snapshot(account.account_id) == account
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (8,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
