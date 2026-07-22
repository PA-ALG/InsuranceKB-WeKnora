from __future__ import annotations

import base64
import copy
import inspect
import json
import os
import pickle
import secrets
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from insurance_harness.goldenset import (
    admission_cli,
    admission_deployment,
    admission_infrastructure,
)
from insurance_harness.goldenset.admission_budget import (
    BudgetAmounts,
    BudgetLedger,
    BudgetLedgerError,
    InfrastructureCreatePermit,
    InfrastructureReserveSnapshot,
)
from insurance_harness.goldenset.admission_deployment import (
    BAILIAN_DEPLOYMENT_ENDPOINT,
    BailianDeploymentHTTPTransport,
    DeploymentControlBlocked,
    DeploymentController,
    DeploymentControlResult,
    DeploymentControlTransport,
    DeploymentProviderConflict,
    DeploymentReceiptArtifact,
    DeploymentReconciliationEvidenceV1,
    DeploymentTransportError,
    ProviderDeploymentManifest,
    deployment_reconciliation_digest,
    deterministic_deployment_suffix,
    deterministic_operation_marker,
    provider_manifest_digest,
    transport_workspace_evidence_digest,
)
from insurance_harness.goldenset.admission_infrastructure import (
    PROVIDER_CAP_DOMAIN,
    PROVISIONING_AUTHORIZATION_DOMAIN,
    AuthorizationVerificationError,
    DeploymentReceipt,
    DeploymentReceiptContent,
    ProviderCapApproval,
    ProviderCapApprovalPayload,
    ProviderCapEvidenceContent,
    ProvisioningAuthorization,
    ProvisioningAuthorizationPayload,
    VerifiedDeploymentTransportIdentity,
    VerifiedProviderCapCapability,
    VerifiedReconciledDeploymentReceipt,
    _issue_verified_deployment_transport_identity_for_testing,
    _require_verified_reconciled_receipt_for_testing,
    authorization_signed_bytes,
    credential_ref_for_api_key,
    deployment_receipt_content_digest,
    issue_verified_deployment_transport_identity,
    provider_cap_evidence_digest,
    provider_cap_signed_bytes,
    require_verified_deployment_transport_identity,
    verify_deployment_receipt,
    verify_provider_cap_evidence,
)
from insurance_harness.goldenset.admission_models import (
    ModelRolePlan,
    RunAdmissionPlanPayload,
    TrustedKeyPolicy,
    canonical_json_bytes,
)
from tests.test_operational_infrastructure_ledger_031 import (
    _PRODUCTION_API_KEY,
    _production_reserve_with_sidecar,
)

NOW = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
OWNERSHIP_NONCE = "e" * 32
STRONG_BASE = "qwen3.7-plus-2026-05-26"


def _testing_receipt_issuer() -> Callable[..., VerifiedReconciledDeploymentReceipt]:
    return cast(
        Callable[..., VerifiedReconciledDeploymentReceipt],
        vars(admission_deployment)["_issue_verified_reconciled_receipt_for_testing"],
    )


def _clone_infrastructure_cap(
    capability: Any,
    *,
    reserve_id: str,
    operation_id: str,
) -> Any:
    clone = object.__new__(type(capability))
    for name in (
        "run_identity",
        "purpose",
        "scope",
        "evidence_digest",
        "approval_digest",
        "provider",
        "currency",
        "workspace_ref",
        "project_ref",
        "credential_ref",
        "coverage",
        "max_cost_minor_units",
        "expires_at",
        "_seal",
    ):
        object.__setattr__(clone, name, getattr(capability, name))
    object.__setattr__(clone, "reserve_id", reserve_id)
    object.__setattr__(clone, "operation_id", operation_id)
    return clone


def _mock_final_topology_from_cap(capability: Any) -> tuple[Any, Any, Any]:
    weak = _clone_infrastructure_cap(
        capability,
        reserve_id="infra-weak-031",
        operation_id="op-weak-031",
    )
    topology = SimpleNamespace(
        topology_digest="9" * 64,
        run_identity=capability.run_identity,
        purpose=capability.purpose,
        scope=capability.scope,
        provider=capability.provider,
        currency=capability.currency,
        workspace_ref=capability.workspace_ref,
        project_ref=capability.project_ref,
        credential_ref=capability.credential_ref,
        provider_cap_evidence_digest=capability.evidence_digest,
        provider_cap_approval_digest=capability.approval_digest,
        provider_cap_coverage=capability.coverage,
        provider_cap_max_cost_minor_units=capability.max_cost_minor_units,
        provider_cap_expires_at=capability.expires_at,
        strong=SimpleNamespace(
            reserve_id=capability.reserve_id,
            operation_id=capability.operation_id,
        ),
        weak=SimpleNamespace(
            reserve_id=weak.reserve_id,
            operation_id=weak.operation_id,
        ),
    )
    return topology, capability, weak


def _production_plan() -> RunAdmissionPlanPayload:
    strong = ModelRolePlan(
        provider="bailian",
        model_id="deployment-strong-031",
        immutable_deployment_id="deployment-strong-031",
        protocol="https",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        provider_policy="bailian-deployment-detail-v1",
        credential_env_name="HARNESS_DASHSCOPE_API_KEY",
    )
    weak = ModelRolePlan(
        provider="bailian",
        model_id="deployment-weak-031",
        immutable_deployment_id="deployment-weak-031",
        protocol="https",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        provider_policy="bailian-deployment-detail-v1",
        credential_env_name="HARNESS_DASHSCOPE_API_KEY",
    )
    return RunAdmissionPlanPayload(
        run_identity="goldenset-s0-20260721-deployment-factory",
        purpose="goldenset-production",
        model_roles={"annotator": strong, "judge": strong, "weak_extractor": weak},
        budget_contract_hash=SHA_A,
    )


def test_o3_o4_o7_production_controller_api_exposes_no_trust_override() -> None:
    for operation in (DeploymentController.provision,):
        assert "trusted_authorities" not in inspect.signature(operation).parameters


def test_o5_c2_production_topology_refresh_exposes_no_caller_selected_evidence() -> None:
    assert tuple(
        inspect.signature(DeploymentController.refresh_topology_reconciliation_batch).parameters
    ) == ("self",)


def test_o5_o6_free_provider_observation_issuer_cannot_mint_production_receipt_capability() -> None:
    """Only the controller's verified artifact path may mint a production receipt seal."""

    assert not hasattr(
        admission_infrastructure,
        "_issue_verified_reconciled_receipt_from_provider_observation",
    )


def test_o5_o6_raw_controller_receipt_inputs_cannot_bypass_fresh_provider_detail() -> None:
    """A caller-provided receipt/manifest pair is not a provider observation proof."""

    assert not hasattr(DeploymentController, "_issue_reconciled_receipt")
    assert tuple(
        inspect.signature(DeploymentController._publish_reconciled_receipt).parameters
    ) == ("self", "observation")
    with pytest.raises(TypeError, match="cannot be caller-constructed"):
        admission_deployment._ControllerRemoteReceiptObservation()


@pytest.mark.parametrize("attack", ["clone", "mutate", "topology_digest"])
def test_o5_i3_transport_capability_requires_issuer_private_canonical_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    cap = fixture.ledger.require_fresh_infrastructure_provider_capability(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=fixture.permit.reserve.reserve_id,
    )
    identity = issue_verified_deployment_transport_identity(
        api_key=_PRODUCTION_API_KEY,
        provider_capability=cap,
    )
    if attack == "clone":
        candidate = object.__new__(type(identity))
        for name in (
            "provider",
            "endpoint",
            "workspace_ref",
            "project_ref",
            "credential_ref",
            "currency",
            "provider_cap_evidence_digest",
            "provider_cap_approval_digest",
            "topology_digest",
            "coverage",
            "credential_fingerprint",
            "expires_at",
            "identity_digest",
            "_seal",
        ):
            object.__setattr__(candidate, name, getattr(identity, name))
    elif attack == "mutate":
        candidate = identity
        object.__setattr__(candidate, "workspace_ref", "attacker-workspace")
    else:
        candidate = identity
        object.__setattr__(candidate, "topology_digest", "7" * 64)

    with pytest.raises(AuthorizationVerificationError, match="issuer|snapshot"):
        require_verified_deployment_transport_identity(candidate)


@pytest.mark.parametrize(
    "attack",
    ["copy", "construct", "serialization_restart", "mutate", "fork"],
)
def test_o5_i3_receipt_capability_is_process_local_issuer_view(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    payload = _authorization_payload()
    transport = _FakeTransport()
    controller, authorization, permit = _controller(tmp_path, transport, payload)
    capability = _provision(controller, authorization, permit).receipt_capability

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
        _require_verified_reconciled_receipt_for_testing(candidate)


def test_o5_production_controller_constructor_rejects_dependency_injection_before_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _InjectedReader:
        calls = 0

        def infrastructure_reserve(self, reserve_id: str) -> InfrastructureReserveSnapshot:
            del reserve_id
            self.calls += 1
            raise AssertionError("injected reserve reader must not be called")

    reserve_reader = _InjectedReader()
    transport = _FakeTransport()
    run_root = tmp_path / "production-deployment-control"
    run_root.mkdir(mode=0o700)
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", run_root)

    with pytest.raises(TypeError, match="reserve_reader|transport"):
        cast(Any, DeploymentController)(
            reserve_reader=cast(BudgetLedger, reserve_reader),
            transport=cast(BailianDeploymentHTTPTransport, transport),
        )

    assert reserve_reader.calls == 0
    assert transport.list_calls == transport.post_calls == transport.detail_calls == 0
    assert tuple(run_root.iterdir()) == ()


def _transport_identity_for_key(api_key: str) -> VerifiedDeploymentTransportIdentity:
    return _issue_verified_deployment_transport_identity_for_testing(
        workspace_ref="workspace-cn-beijing-031",
        project_ref="sha256:" + SHA_A,
        credential_ref=credential_ref_for_api_key(api_key),
        provider_cap_evidence_digest=SHA_D,
        expires_at=NOW + timedelta(hours=1),
    )


def _production_provider_cap_for_key(api_key: str) -> VerifiedProviderCapCapability:
    key = Ed25519PrivateKey.generate()
    content = ProviderCapEvidenceContent(
        version="insurancekb.run-admission.provider-cap-evidence.v1",
        issuer="aliyun-bailian-spend-cap",
        provider="bailian",
        workspace_ref="workspace-cn-beijing-031",
        project_ref="sha256:" + SHA_A,
        credential_ref=credential_ref_for_api_key(api_key),
        currency="CNY",
        max_cost_minor_units=10_000,
        coverage=("fixed_infrastructure", "inference"),
        observed_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
    )
    evidence = canonical_json_bytes(content)
    payload = ProviderCapApprovalPayload(
        evidence_digest=provider_cap_evidence_digest(evidence),
        evidence=content,
        scope="goldenset-production",
        approver_identity="cap-attestor@example.test",
        approver_role="provider-cap-attestor",
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
    )
    approval = ProviderCapApproval(
        domain=PROVIDER_CAP_DOMAIN,
        key_id="cap-key",
        payload=payload,
        signature=base64.b64encode(key.sign(provider_cap_signed_bytes(payload))).decode("ascii"),
    )
    policy = {
        "cap-key": TrustedKeyPolicy(
            key_id="cap-key",
            approver_identity="cap-attestor@example.test",
            domains=frozenset({PROVIDER_CAP_DOMAIN}),
            scopes=frozenset({"goldenset-production"}),
            roles=frozenset({"provider-cap-attestor"}),
            public_key=key.public_key(),
        )
    }
    return verify_provider_cap_evidence(
        evidence,
        envelope=approval,
        trusted_authorities=policy,
        expected_scope="goldenset-production",
        now=NOW,
    )


def test_o4_caller_self_enrolled_cap_cannot_construct_production_controller_or_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = "caller-controlled-production-key"
    caller_cap = _production_provider_cap_for_key(api_key)
    side_effects = {"http_client": 0, "operation_store": 0}

    class _NoIOClient:
        def __init__(self, **_kwargs: object) -> None:
            side_effects["http_client"] += 1

        def close(self) -> None:
            pass

    class _NoIOStore:
        def __init__(self, _root: Path) -> None:
            side_effects["operation_store"] += 1

        def close(self) -> None:
            pass

    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", api_key)
    monkeypatch.setattr(httpx, "Client", _NoIOClient)
    monkeypatch.setattr(admission_deployment, "_OperationStore", _NoIOStore)
    monkeypatch.setattr(
        admission_deployment,
        "_PRODUCTION_BUDGET_LEDGER_PATH",
        tmp_path / "budget.sqlite3",
    )
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", tmp_path)

    with pytest.raises(TypeError):
        cast(Any, DeploymentController.for_production)(provider_capability=caller_cap)
    with pytest.raises(TypeError):
        cast(Any, BailianDeploymentHTTPTransport)(
            api_key=api_key,
            provider_capability=caller_cap,
        )

    assert side_effects == {"http_client": 0, "operation_store": 0}


def test_o4_production_factory_reads_cap_from_fixed_ledger_before_transport_or_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    side_effects = {"ledger": 0, "http_client": 0, "operation_store": 0}

    def _expired_root_topology(
        _ledger: BudgetLedger,
        *,
        plan: RunAdmissionPlanPayload,
        expected_scope: str,
        **_unsupported: object,
    ) -> Any:
        del plan, expected_scope, _unsupported
        side_effects["ledger"] += 1
        raise BudgetLedgerError("root provider-cap approval is expired")

    class _NoIOClient:
        def __init__(self, **_kwargs: object) -> None:
            side_effects["http_client"] += 1

    class _NoIOStore:
        def __init__(self, _root: Path) -> None:
            side_effects["operation_store"] += 1

    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", "fixed-ledger-key")
    monkeypatch.setattr(
        BudgetLedger,
        "require_fresh_final_topology",
        _expired_root_topology,
    )
    monkeypatch.setattr(httpx, "Client", _NoIOClient)
    monkeypatch.setattr(admission_deployment, "_OperationStore", _NoIOStore)
    monkeypatch.setattr(
        admission_deployment,
        "_PRODUCTION_BUDGET_LEDGER_PATH",
        tmp_path / "budget.sqlite3",
    )
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", tmp_path)

    with pytest.raises(DeploymentControlBlocked) as blocked:
        DeploymentController.for_production(
            plan=_production_plan(),
            expected_scope="goldenset-production",
        )

    assert blocked.value.code == "production_controller_unavailable"
    assert side_effects == {"ledger": 1, "http_client": 0, "operation_store": 0}


def test_o4_o5_factory_with_durable_provisioning_reserve_does_not_require_final_topology(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O4/O5: provisioning must be constructible before the final topology exists."""

    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    run_root = tmp_path / "deployments"
    run_root.mkdir(mode=0o700)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _PRODUCTION_API_KEY)
    monkeypatch.setattr(
        admission_deployment,
        "_PRODUCTION_BUDGET_LEDGER_PATH",
        fixture.db_path,
    )
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", run_root)

    controller = DeploymentController.for_production(
        plan=fixture.plan,
        expected_scope="goldenset-production",
        reserve_id=fixture.permit.reserve.reserve_id,
    )

    assert type(controller._reserve_reader) is BudgetLedger
    assert tuple(run_root.iterdir()) == ()
    cast(BailianDeploymentHTTPTransport, controller._transport).close()


def test_o5_provisioning_factory_reserve_must_match_signed_permit_before_provider_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    authorities, _budget_roles, _provenance_roles, _review_roles = (
        admission_cli._load_deployment_approval_configuration()
    )
    other_key = Ed25519PrivateKey.generate()
    other_payload = fixture.payload.model_copy(
        update={
            "operation_id": "op-other-031",
            "infrastructure_reserve_id": "infra-other-031",
        }
    )
    other_authorization = ProvisioningAuthorization(
        domain=PROVISIONING_AUTHORIZATION_DOMAIN,
        key_id="provisioning-key-other",
        payload=other_payload,
        signature=base64.b64encode(
            other_key.sign(
                authorization_signed_bytes(
                    PROVISIONING_AUTHORIZATION_DOMAIN,
                    other_payload,
                )
            )
        ).decode("ascii"),
    )
    combined_authorities = {
        **authorities,
        "provisioning-key-other": TrustedKeyPolicy(
            key_id="provisioning-key-other",
            approver_identity=other_payload.approver_identity,
            domains=frozenset({PROVISIONING_AUTHORIZATION_DOMAIN}),
            scopes=frozenset({other_payload.scope}),
            roles=frozenset({other_payload.approver_role}),
            public_key=other_key.public_key(),
        ),
    }
    monkeypatch.setattr(
        admission_cli,
        "_load_deployment_approval_configuration",
        lambda: (combined_authorities, frozenset(), frozenset(), frozenset()),
    )
    other_permit = fixture.ledger.reserve_provisioning_before_post(
        authorization=other_authorization,
        expected=other_payload,
        pricing_evidence_bytes=fixture.pricing_bytes,
        pricing_approval=fixture.pricing_approval,
        provider_cap_evidence_bytes=fixture.cap_bytes,
        provider_cap_approval=fixture.cap_approval,
    )
    run_root = tmp_path / "deployments"
    run_root.mkdir(mode=0o700)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _PRODUCTION_API_KEY)
    monkeypatch.setattr(
        admission_deployment,
        "_PRODUCTION_BUDGET_LEDGER_PATH",
        fixture.db_path,
    )
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", run_root)
    controller = DeploymentController.for_production(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=fixture.permit.reserve.reserve_id,
    )
    controller._clock = lambda: NOW
    provider_calls = 0

    def reject_provider_list(
        _transport: BailianDeploymentHTTPTransport,
        *,
        marker: str,
        suffix: str,
    ) -> bytes:
        nonlocal provider_calls
        del marker, suffix
        provider_calls += 1
        raise DeploymentTransportError("provider I/O must not be reached")

    monkeypatch.setattr(
        BailianDeploymentHTTPTransport,
        "list_deployments",
        reject_provider_list,
    )

    with pytest.raises(DeploymentControlBlocked) as blocked:
        controller.provision(
            authorization=other_authorization,
            permit=other_permit,
        )

    assert blocked.value.code == "production_reserve_binding_mismatch"
    assert provider_calls == 0
    assert list(run_root.glob("*.journal.json")) == []
    controller.close()


def test_o5_cap_expiring_after_os_run_lock_blocks_provider_io_and_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    run_root = tmp_path / "deployments"
    run_root.mkdir(mode=0o700)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _PRODUCTION_API_KEY)
    monkeypatch.setattr(
        admission_deployment,
        "_PRODUCTION_BUDGET_LEDGER_PATH",
        fixture.db_path,
    )
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", run_root)
    controller = DeploymentController.for_production(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=fixture.permit.reserve.reserve_id,
    )
    controller._clock = lambda: NOW
    original_run_lock = controller._store.run_lock

    @contextmanager
    def expire_after_os_lock(run_identity: str) -> Any:
        with original_run_lock(run_identity):
            cast(BudgetLedger, controller._reserve_reader)._clock = (
                lambda: NOW + timedelta(hours=2)
            )
            yield

    monkeypatch.setattr(controller._store, "run_lock", expire_after_os_lock)
    provider_calls = 0

    def reject_provider_list(
        _transport: BailianDeploymentHTTPTransport,
        *,
        marker: str,
        suffix: str,
    ) -> bytes:
        nonlocal provider_calls
        del marker, suffix
        provider_calls += 1
        raise DeploymentTransportError("provider I/O must not be reached")

    monkeypatch.setattr(
        BailianDeploymentHTTPTransport,
        "list_deployments",
        reject_provider_list,
    )

    with pytest.raises(DeploymentControlBlocked) as blocked:
        controller.provision(
            authorization=fixture.authorization,
            permit=fixture.permit,
        )

    assert blocked.value.code == "production_provider_cap_invalid"
    assert provider_calls == 0
    assert list(run_root.glob("*.journal.json")) == []
    controller.close()


def test_o5_cap_expiring_after_list_blocks_immediate_provider_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    run_root = tmp_path / "deployments"
    run_root.mkdir(mode=0o700)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _PRODUCTION_API_KEY)
    monkeypatch.setattr(
        admission_deployment,
        "_PRODUCTION_BUDGET_LEDGER_PATH",
        fixture.db_path,
    )
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", run_root)
    controller = DeploymentController.for_production(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=fixture.permit.reserve.reserve_id,
    )
    controller._clock = lambda: NOW
    list_calls = 0
    post_calls = 0

    def expire_during_list(
        _transport: BailianDeploymentHTTPTransport,
        *,
        marker: str,
        suffix: str,
    ) -> bytes:
        nonlocal list_calls
        del marker, suffix
        list_calls += 1
        cast(BudgetLedger, controller._reserve_reader)._clock = (
            lambda: NOW + timedelta(hours=2)
        )
        return canonical_json_bytes({"items": []})

    def reject_post(
        _transport: BailianDeploymentHTTPTransport,
        *,
        request_body: bytes,
        idempotency_key: str,
    ) -> bytes:
        nonlocal post_calls
        del request_body, idempotency_key
        post_calls += 1
        raise DeploymentTransportError("provider POST must not be reached")

    monkeypatch.setattr(BailianDeploymentHTTPTransport, "list_deployments", expire_during_list)
    monkeypatch.setattr(BailianDeploymentHTTPTransport, "create_deployment", reject_post)

    with pytest.raises(DeploymentControlBlocked) as blocked:
        controller.provision(
            authorization=fixture.authorization,
            permit=fixture.permit,
        )

    assert blocked.value.code == "production_provider_cap_invalid"
    assert list_calls == 1
    assert post_calls == 0
    controller.close()


def test_o5_cap_expiring_during_post_blocks_receipt_observation_and_mint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider mutation cannot authorize later GETs or a stale receipt mint."""

    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    run_root = tmp_path / "deployments"
    run_root.mkdir(mode=0o700)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _PRODUCTION_API_KEY)
    monkeypatch.setattr(
        admission_deployment,
        "_PRODUCTION_BUDGET_LEDGER_PATH",
        fixture.db_path,
    )
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", run_root)
    controller = DeploymentController.for_production(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=fixture.permit.reserve.reserve_id,
    )
    controller._clock = lambda: NOW
    list_calls = 0
    post_calls = 0
    detail_calls = 0
    created_manifest: dict[str, object] | None = None

    def empty_provider_list(
        _transport: BailianDeploymentHTTPTransport,
        *,
        marker: str,
        suffix: str,
    ) -> bytes:
        nonlocal list_calls
        del marker, suffix
        list_calls += 1
        return canonical_json_bytes({"items": []})

    def expire_during_post(
        _transport: BailianDeploymentHTTPTransport,
        *,
        request_body: bytes,
        idempotency_key: str,
    ) -> bytes:
        nonlocal post_calls, created_manifest
        del idempotency_key
        post_calls += 1
        request = json.loads(request_body)
        created_manifest = _manifest(
            base_model=request["base_model"],
            workspace_ref=request["workspace_ref"],
            operation_marker=request["operation_marker"],
            deployment_suffix=request["deployment_suffix"],
        )
        cast(BudgetLedger, controller._reserve_reader)._clock = lambda: NOW + timedelta(hours=2)
        return canonical_json_bytes(created_manifest)

    def reject_stale_detail(
        _transport: BailianDeploymentHTTPTransport,
        *,
        deployed_model: str,
    ) -> bytes:
        nonlocal detail_calls
        detail_calls += 1
        assert created_manifest is not None
        assert deployed_model == created_manifest["deployed_model"]
        return canonical_json_bytes(created_manifest)

    monkeypatch.setattr(
        BailianDeploymentHTTPTransport,
        "list_deployments",
        empty_provider_list,
    )
    monkeypatch.setattr(
        BailianDeploymentHTTPTransport,
        "create_deployment",
        expire_during_post,
    )
    monkeypatch.setattr(
        BailianDeploymentHTTPTransport,
        "deployment_detail",
        reject_stale_detail,
    )

    with pytest.raises(DeploymentControlBlocked) as blocked:
        controller.provision(
            authorization=fixture.authorization,
            permit=fixture.permit,
        )

    assert blocked.value.code == "production_provider_cap_invalid"
    assert (list_calls, post_calls, detail_calls) == (1, 1, 0)
    assert list(run_root.glob("*.receipt.json")) == []
    assert list(run_root.glob("*.receipt-reconciliation.json")) == []
    controller.close()


def test_o5_i2_authority_rotation_during_post_blocks_every_followup_get(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    run_root = tmp_path / "deployments"
    run_root.mkdir(mode=0o700)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _PRODUCTION_API_KEY)
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_BUDGET_LEDGER_PATH", fixture.db_path)
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", run_root)
    controller = DeploymentController.for_production(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=fixture.permit.reserve.reserve_id,
    )
    controller._clock = lambda: NOW
    created_manifest: dict[str, object] | None = None
    detail_calls = 0

    monkeypatch.setattr(
        BailianDeploymentHTTPTransport,
        "list_deployments",
        lambda *_args, **_kwargs: canonical_json_bytes({"items": []}),
    )

    def rotate_authority_during_post(
        _transport: BailianDeploymentHTTPTransport,
        *,
        request_body: bytes,
        idempotency_key: str,
    ) -> bytes:
        nonlocal created_manifest
        del idempotency_key
        request = json.loads(request_body)
        created_manifest = _manifest(
            base_model=request["base_model"],
            workspace_ref=request["workspace_ref"],
            ownership_nonce=request["ownership_nonce"],
            operation_marker=request["operation_marker"],
            deployment_suffix=request["deployment_suffix"],
        )
        monkeypatch.setattr(
            admission_cli,
            "_load_deployment_approval_configuration",
            lambda: ({}, frozenset(), frozenset(), frozenset()),
        )
        return canonical_json_bytes(created_manifest)

    def observe_detail(
        _transport: BailianDeploymentHTTPTransport,
        *,
        deployed_model: str,
    ) -> bytes:
        nonlocal detail_calls
        detail_calls += 1
        assert created_manifest is not None
        assert deployed_model == created_manifest["deployed_model"]
        return canonical_json_bytes(created_manifest)

    monkeypatch.setattr(
        BailianDeploymentHTTPTransport,
        "create_deployment",
        rotate_authority_during_post,
    )
    monkeypatch.setattr(BailianDeploymentHTTPTransport, "deployment_detail", observe_detail)

    with pytest.raises(DeploymentControlBlocked) as blocked:
        controller.provision(
            authorization=fixture.authorization,
            permit=fixture.permit,
        )

    # The durable cap reload owns the root-authority ceremony; root rotation is
    # therefore conservatively surfaced through the production-cap boundary.
    assert blocked.value.code == "production_provider_cap_invalid"
    assert detail_calls == 0
    assert list(run_root.glob("*.receipt.json")) == []
    assert list(run_root.glob("*.receipt-reconciliation.json")) == []
    controller.close()


def test_o5_provisioning_mode_rejects_topology_refresh_before_provider_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    run_root = tmp_path / "deployments"
    run_root.mkdir(mode=0o700)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _PRODUCTION_API_KEY)
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_BUDGET_LEDGER_PATH", fixture.db_path)
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", run_root)
    controller = DeploymentController.for_production(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=fixture.permit.reserve.reserve_id,
    )
    detail_calls = 0

    def reject_detail(
        _transport: BailianDeploymentHTTPTransport,
        *,
        deployed_model: str,
    ) -> bytes:
        nonlocal detail_calls
        del deployed_model
        detail_calls += 1
        raise DeploymentTransportError("provider GET must not be reached")

    monkeypatch.setattr(BailianDeploymentHTTPTransport, "deployment_detail", reject_detail)

    with pytest.raises(DeploymentControlBlocked) as blocked:
        controller.refresh_topology_reconciliation_batch()

    assert blocked.value.code == "production_mode_mismatch"
    assert detail_calls == 0
    assert list(run_root.glob("*.journal.json")) == []
    controller.close()


def test_o5_factory_store_initialization_failure_closes_created_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _PRODUCTION_API_KEY)
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_BUDGET_LEDGER_PATH", fixture.db_path)
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", tmp_path / "missing-root")
    close_calls = 0
    original_close = BailianDeploymentHTTPTransport.close

    def counted_close(transport: BailianDeploymentHTTPTransport) -> None:
        nonlocal close_calls
        close_calls += 1
        original_close(transport)

    monkeypatch.setattr(BailianDeploymentHTTPTransport, "close", counted_close)

    with pytest.raises(DeploymentControlBlocked) as blocked:
        DeploymentController.for_production(
            plan=fixture.plan,
            expected_scope=fixture.payload.scope,
            reserve_id=fixture.permit.reserve.reserve_id,
        )

    assert blocked.value.code == "operation_store_unsafe"
    assert close_calls == 1


def test_o5_topology_factory_rejects_weak_sidecar_binding_drift_before_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    strong_cap = fixture.ledger.require_fresh_infrastructure_provider_capability(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=fixture.permit.reserve.reserve_id,
    )
    topology, _strong, _weak = _mock_final_topology_from_cap(strong_cap)
    client_calls = 0

    def fixed_topology(_ledger: BudgetLedger, **_kwargs: object) -> Any:
        return topology

    class _NoIOClient:
        def __init__(self, **_kwargs: object) -> None:
            nonlocal client_calls
            client_calls += 1

    monkeypatch.setattr(BudgetLedger, "require_fresh_final_topology", fixed_topology)
    topology_cap = fixture.ledger.require_fresh_topology_provider_capability(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=topology.strong.reserve_id,
    )

    def drifted_caps(_ledger: BudgetLedger, **_kwargs: object) -> Any:
        return topology_cap

    monkeypatch.setattr(
        BudgetLedger,
        "require_fresh_topology_provider_capability",
        drifted_caps,
    )
    monkeypatch.setattr(httpx, "Client", _NoIOClient)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _PRODUCTION_API_KEY)
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_BUDGET_LEDGER_PATH", fixture.db_path)
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", tmp_path)

    with pytest.raises(DeploymentControlBlocked) as blocked:
        DeploymentController.for_production(
            plan=fixture.plan,
            expected_scope=fixture.payload.scope,
        )

    assert blocked.value.code == "production_controller_unavailable"
    assert client_calls == 0


def test_o5_i3_topology_factory_rejects_caps_from_different_topology_digests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    strong_cap = fixture.ledger.require_fresh_infrastructure_provider_capability(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=fixture.permit.reserve.reserve_id,
    )
    topology, _strong, _weak = _mock_final_topology_from_cap(strong_cap)
    drifted_topology = SimpleNamespace(
        **{
            **vars(topology),
            "topology_digest": "8" * 64,
        }
    )

    monkeypatch.setattr(
        BudgetLedger,
        "require_fresh_final_topology",
        lambda _ledger, **_kwargs: drifted_topology,
    )
    drifted_strong_cap = fixture.ledger.require_fresh_topology_provider_capability(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=drifted_topology.strong.reserve_id,
    )
    drifted_weak_cap = fixture.ledger.require_fresh_topology_provider_capability(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=drifted_topology.weak.reserve_id,
    )
    client_calls = 0

    def load_expected_topology(_ledger: BudgetLedger, **_kwargs: object) -> Any:
        return topology

    def load_drifted_cap(_ledger: BudgetLedger, **kwargs: object) -> Any:
        return (
            drifted_strong_cap
            if kwargs["reserve_id"] == topology.strong.reserve_id
            else drifted_weak_cap
        )

    class _NoIOClient:
        def __init__(self, **_kwargs: object) -> None:
            nonlocal client_calls
            client_calls += 1

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        BudgetLedger,
        "require_fresh_final_topology",
        load_expected_topology,
    )
    monkeypatch.setattr(
        BudgetLedger,
        "require_fresh_topology_provider_capability",
        load_drifted_cap,
    )
    monkeypatch.setattr(httpx, "Client", _NoIOClient)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _PRODUCTION_API_KEY)
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_BUDGET_LEDGER_PATH", fixture.db_path)
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", tmp_path)

    with pytest.raises(DeploymentControlBlocked) as blocked:
        DeploymentController.for_production(
            plan=fixture.plan,
            expected_scope=fixture.payload.scope,
        )

    assert blocked.value.code == "production_controller_unavailable"
    assert client_calls == 0


def test_o5_i1_bound_topology_cap_uses_distinct_loader_from_reserved_provisioning_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    reserved_capability = fixture.ledger.require_fresh_infrastructure_provider_capability(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=fixture.permit.reserve.reserve_id,
    )

    assert reserved_capability.reserve_id == fixture.permit.reserve.reserve_id
    with pytest.raises(BudgetLedgerError, match="final topology|bound"):
        fixture.ledger.require_fresh_topology_provider_capability(
            plan=fixture.plan,
            expected_scope=fixture.payload.scope,
            reserve_id=fixture.permit.reserve.reserve_id,
        )


def test_o5_topology_refresh_reloads_caps_between_strong_and_weak_get(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    strong_cap = fixture.ledger.require_fresh_infrastructure_provider_capability(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=fixture.permit.reserve.reserve_id,
    )
    topology, strong_cap, _weak_cap = _mock_final_topology_from_cap(strong_cap)
    topology.topology_digest = "1" * 64
    topology.plan_payload_hash = "2" * 64
    cap_expired = False

    def fixed_topology(_ledger: BudgetLedger, **_kwargs: object) -> Any:
        if cap_expired:
            raise BudgetLedgerError("provider cap expired after strong GET")
        return topology

    run_root = tmp_path / "deployments"
    run_root.mkdir(mode=0o700)
    monkeypatch.setattr(BudgetLedger, "require_fresh_final_topology", fixed_topology)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _PRODUCTION_API_KEY)
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_BUDGET_LEDGER_PATH", fixture.db_path)
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", run_root)
    controller = DeploymentController.for_production(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
    )
    controller._clock = lambda: NOW
    target_transport = _FakeTransport()
    target_transport.identity = controller._transport.identity
    strong_target = _topology_target(
        target_transport,
        boundary="strong",
        operation_id="op-strong-topology-031",
        reserve_id="infra-strong-topology-031",
        base_model=STRONG_BASE,
        roles=("annotator", "judge"),
    )
    weak_target = _topology_target(
        target_transport,
        boundary="weak",
        operation_id="op-weak-topology-031",
        reserve_id="infra-weak-topology-031",
        base_model="deepseek-v4-flash",
        roles=("extractor",),
    )
    topology.strong.receipt = strong_target.receipt
    topology.strong.roles = ("annotator", "judge")
    topology.strong.remote_manifest_digest = (
        strong_target.receipt.content.remote_manifest_digest
    )
    topology.strong.reconciliation_digest = _write_bound_topology_artifacts(
        controller,
        strong_target,
    )
    topology.weak.receipt = weak_target.receipt
    topology.weak.roles = ("weak_extractor",)
    topology.weak.remote_manifest_digest = weak_target.receipt.content.remote_manifest_digest
    topology.weak.reconciliation_digest = _write_bound_topology_artifacts(
        controller,
        weak_target,
    )
    detail_calls = 0

    def expire_after_strong_get(
        _transport: BailianDeploymentHTTPTransport,
        *,
        deployed_model: str,
    ) -> bytes:
        nonlocal cap_expired, detail_calls
        detail_calls += 1
        if detail_calls > 1:
            raise AssertionError("weak GET must not be reached")
        assert deployed_model == strong_target.receipt.content.deployed_model
        cap_expired = True
        return canonical_json_bytes(strong_target.expected_remote_manifest)

    monkeypatch.setattr(
        BailianDeploymentHTTPTransport,
        "deployment_detail",
        expire_after_strong_get,
    )

    with pytest.raises(DeploymentControlBlocked) as blocked:
        controller.refresh_topology_reconciliation_batch()

    assert blocked.value.code == "production_provider_cap_invalid"
    assert detail_calls == 1
    controller.close()


@pytest.mark.parametrize(
    "drift_stage",
    ["before_publication", "after_readback", "after_readback_replay"],
)
def test_o5_topology_refresh_rechecks_topology_expiry_before_batch_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift_stage: str,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    strong_cap = fixture.ledger.require_fresh_infrastructure_provider_capability(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=fixture.permit.reserve.reserve_id,
    )
    topology, _strong_cap, _weak_cap = _mock_final_topology_from_cap(strong_cap)
    topology.topology_digest = "1" * 64
    topology.plan_payload_hash = "2" * 64
    topology.valid_until = NOW + timedelta(minutes=1)

    monkeypatch.setattr(
        BudgetLedger,
        "require_fresh_final_topology",
        lambda _ledger, **_kwargs: topology,
    )
    run_root = tmp_path / "deployments"
    run_root.mkdir(mode=0o700)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _PRODUCTION_API_KEY)
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_BUDGET_LEDGER_PATH", fixture.db_path)
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", run_root)
    controller = DeploymentController.for_production(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
    )
    if drift_stage == "before_publication":
        observed = iter((NOW, topology.valid_until))
        controller._clock = lambda: next(observed)
    elif drift_stage == "after_readback":
        controller._clock = lambda: NOW
        original_freshness = controller._require_fresh_production_topology_refresh
        freshness_calls = 0

        def expire_after_readback(*, expected_fingerprint: str) -> Any:
            nonlocal freshness_calls
            freshness_calls += 1
            if freshness_calls == 6:
                raise DeploymentControlBlocked(
                    "production_topology_drift",
                    "topology expired after batch readback",
                )
            return original_freshness(expected_fingerprint=expected_fingerprint)

        monkeypatch.setattr(
            controller,
            "_require_fresh_production_topology_refresh",
            expire_after_readback,
        )
    else:
        controller._clock = lambda: NOW
    target_transport = _FakeTransport()
    target_transport.identity = controller._transport.identity
    strong_target = _topology_target(
        target_transport,
        boundary="strong",
        operation_id="op-strong-topology-031",
        reserve_id="infra-strong-topology-031",
        base_model=STRONG_BASE,
        roles=("annotator", "judge"),
    )
    weak_target = _topology_target(
        target_transport,
        boundary="weak",
        operation_id="op-weak-topology-031",
        reserve_id="infra-weak-topology-031",
        base_model="deepseek-v4-flash",
        roles=("extractor",),
    )
    topology.strong.receipt = strong_target.receipt
    topology.strong.roles = ("annotator", "judge")
    topology.strong.remote_manifest_digest = strong_target.receipt.content.remote_manifest_digest
    topology.strong.reconciliation_digest = _write_bound_topology_artifacts(
        controller,
        strong_target,
    )
    topology.weak.receipt = weak_target.receipt
    topology.weak.roles = ("weak_extractor",)
    topology.weak.remote_manifest_digest = weak_target.receipt.content.remote_manifest_digest
    topology.weak.reconciliation_digest = _write_bound_topology_artifacts(
        controller,
        weak_target,
    )

    def exact_detail(
        _transport: BailianDeploymentHTTPTransport,
        *,
        deployed_model: str,
    ) -> bytes:
        target = (
            strong_target
            if deployed_model == strong_target.receipt.content.deployed_model
            else weak_target
        )
        return canonical_json_bytes(target.expected_remote_manifest)

    monkeypatch.setattr(BailianDeploymentHTTPTransport, "deployment_detail", exact_detail)

    replay_path: Path | None = None
    replay_bytes: bytes | None = None
    if drift_stage == "after_readback_replay":
        first = controller.refresh_topology_reconciliation_batch()
        replay_path = first.artifact_path
        replay_bytes = replay_path.read_bytes()
        original_freshness = controller._require_fresh_production_topology_refresh
        freshness_calls = 0

        def expire_replay_after_readback(*, expected_fingerprint: str) -> Any:
            nonlocal freshness_calls
            freshness_calls += 1
            if freshness_calls == 6:
                raise DeploymentControlBlocked(
                    "production_topology_drift",
                    "topology expired after replay readback",
                )
            return original_freshness(expected_fingerprint=expected_fingerprint)

        monkeypatch.setattr(
            controller,
            "_require_fresh_production_topology_refresh",
            expire_replay_after_readback,
        )

    with pytest.raises(DeploymentControlBlocked) as blocked:
        controller.refresh_topology_reconciliation_batch()

    assert blocked.value.code in {
        "production_provider_cap_invalid",
        "production_topology_drift",
    }
    if replay_path is None:
        assert list(run_root.glob("*.topology-observation-batch.json")) == []
    else:
        assert replay_path.read_bytes() == replay_bytes
        assert list(run_root.glob("*.topology-observation-batch.json")) == [replay_path]
    controller.close()


def test_o5_canonical_production_factory_owns_ledger_root_and_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    run_root = tmp_path / "deployments"
    run_root.mkdir(mode=0o700)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _PRODUCTION_API_KEY)
    monkeypatch.setattr(
        admission_deployment,
        "_PRODUCTION_BUDGET_LEDGER_PATH",
        fixture.db_path,
    )
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", run_root)

    controller = DeploymentController.for_production(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=fixture.permit.reserve.reserve_id,
    )

    assert "reserve_reader" not in inspect.signature(DeploymentController.for_production).parameters
    assert "transport" not in inspect.signature(DeploymentController.for_production).parameters
    assert type(controller._reserve_reader) is BudgetLedger
    assert controller._reserve_reader._db_path == fixture.db_path
    assert type(controller._transport) is BailianDeploymentHTTPTransport
    assert controller._store.root == run_root
    assert tuple(run_root.iterdir()) == ()
    with controller as entered:
        assert entered is controller
    controller.close()
    controller.close()
    assert controller._store._root_fd == -1
    assert controller._transport._client.is_closed


def _production_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    run_root: Path,
) -> DeploymentController:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _PRODUCTION_API_KEY)
    monkeypatch.setattr(
        admission_deployment,
        "_PRODUCTION_BUDGET_LEDGER_PATH",
        fixture.db_path,
    )
    monkeypatch.setattr(admission_deployment, "_PRODUCTION_RUN_ROOT", run_root)
    return DeploymentController.for_production(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=fixture.permit.reserve.reserve_id,
    )


@pytest.mark.parametrize("dependency", ["reserve_reader", "transport"])
def test_o5_production_controller_rejects_dependency_replacement_before_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dependency: str,
) -> None:
    class _InjectedReader:
        calls = 0

        def infrastructure_reserve(self, reserve_id: str) -> InfrastructureReserveSnapshot:
            del reserve_id
            self.calls += 1
            raise AssertionError("injected reserve reader must not be called")

    run_root = tmp_path / "production-deployments"
    run_root.mkdir(mode=0o700)
    controller = _production_controller(
        tmp_path,
        monkeypatch,
        run_root=run_root,
    )
    owned_transport = cast(BailianDeploymentHTTPTransport, controller._transport)
    injected_reader = _InjectedReader()
    injected_transport = _FakeTransport()
    if dependency == "reserve_reader":
        controller._reserve_reader = injected_reader
    else:
        controller._transport = injected_transport

    with pytest.raises(DeploymentControlBlocked) as blocked:
        cast(Any, controller.provision)(authorization=object(), permit=object())

    assert blocked.value.code == "production_dependency_invalid"
    assert injected_reader.calls == 0
    assert (
        injected_transport.list_calls
        == injected_transport.post_calls
        == injected_transport.detail_calls
        == 0
    )
    assert tuple(run_root.iterdir()) == ()
    owned_transport.close()


def _authorization_payload(**updates: Any) -> ProvisioningAuthorizationPayload:
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
        "base_model": STRONG_BASE,
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


def _signed_authorization(
    key: Ed25519PrivateKey,
    payload: ProvisioningAuthorizationPayload,
) -> ProvisioningAuthorization:
    signature = key.sign(authorization_signed_bytes(PROVISIONING_AUTHORIZATION_DOMAIN, payload))
    return ProvisioningAuthorization(
        domain=PROVISIONING_AUTHORIZATION_DOMAIN,
        key_id="provisioning-key",
        payload=payload,
        signature=base64.b64encode(signature).decode("ascii"),
    )


def _policy(key: Ed25519PrivateKey) -> dict[str, TrustedKeyPolicy]:
    return {
        "provisioning-key": TrustedKeyPolicy(
            key_id="provisioning-key",
            approver_identity="deployment-operator@example.test",
            domains=frozenset({PROVISIONING_AUTHORIZATION_DOMAIN}),
            scopes=frozenset({"goldenset-production"}),
            roles=frozenset({"deployment-provisioner"}),
            public_key=key.public_key(),
        )
    }


def _permit(payload: ProvisioningAuthorizationPayload) -> InfrastructureCreatePermit:
    from insurance_harness.goldenset.admission_infrastructure import (
        infrastructure_authorization_digest,
    )

    key = getattr(payload, "_test_signing_key", None)
    assert isinstance(key, Ed25519PrivateKey)
    authorization = _signed_authorization(key, payload)
    reserve = InfrastructureReserveSnapshot(
        reserve_id=payload.infrastructure_reserve_id,
        account_id="9" * 64,
        run_identity=payload.run_identity,
        purpose=payload.purpose,
        operation_id=payload.operation_id,
        authorization_domain=PROVISIONING_AUTHORIZATION_DOMAIN,
        authorization_digest=infrastructure_authorization_digest(authorization),
        maximum=BudgetAmounts(
            input_tokens=0,
            output_tokens=0,
            cost_minor_units=payload.maximum_cost_minor_units,
        ),
        state="reserved",
    )
    return InfrastructureCreatePermit(
        operation_id=payload.operation_id,
        reserve=reserve,
        authorization_expires_at=payload.expires_at,
        provider_cap_expires_at=payload.provider_cap_expires_at,
        cleanup_deadline=payload.cleanup_deadline,
    )


class _ReserveReader:
    def __init__(self, reserve: InfrastructureReserveSnapshot) -> None:
        self.reserve = reserve

    def infrastructure_reserve(self, reserve_id: str) -> InfrastructureReserveSnapshot:
        if reserve_id != self.reserve.reserve_id:
            raise RuntimeError("reserve not found")
        return self.reserve


class _FakeTransport:
    endpoint = BAILIAN_DEPLOYMENT_ENDPOINT

    def __init__(self) -> None:
        self.provider = "bailian"
        self.workspace_ref = "workspace-cn-beijing-031"
        self.project_ref = "sha256:" + SHA_A
        self.credential_ref = "sha256:" + SHA_B
        self.identity = _issue_verified_deployment_transport_identity_for_testing(
            workspace_ref=self.workspace_ref,
            project_ref=self.project_ref,
            credential_ref=self.credential_ref,
            provider_cap_evidence_digest=SHA_D,
            expires_at=NOW + timedelta(hours=1),
        )
        self.post_calls = 0
        self.list_calls = 0
        self.detail_calls = 0
        self.items: list[dict[str, object]] = []
        self.create_mode = "ok"
        self.list_body_override: bytes | None = None
        self.detail_override: bytes | None = None
        self.detail_overrides: dict[str, bytes] = {}
        self.detail_delay_seconds = 0.0
        self.active_detail_calls = 0
        self.max_active_detail_calls = 0
        self._detail_counter_lock = threading.Lock()

    def list_deployments(self, *, marker: str, suffix: str) -> bytes:
        self.list_calls += 1
        if self.list_body_override is not None:
            return self.list_body_override
        return json.dumps({"items": self.items}, separators=(",", ":")).encode()

    def create_deployment(self, *, request_body: bytes, idempotency_key: str) -> bytes:
        self.post_calls += 1
        request = json.loads(request_body)
        manifest = _manifest(
            base_model=request["base_model"],
            workspace_ref=request["workspace_ref"],
            ownership_nonce=request["ownership_nonce"],
            operation_marker=request["operation_marker"],
            deployment_suffix=request["deployment_suffix"],
        )
        self.items.append(manifest)
        if self.create_mode == "timeout_after_accept":
            raise TimeoutError("response lost")
        if self.create_mode == "conflict_after_accept":
            raise DeploymentProviderConflict("already exists")
        if self.create_mode == "malformed_after_accept":
            return b"not-json"
        return json.dumps(manifest, separators=(",", ":")).encode()

    def deployment_detail(self, *, deployed_model: str) -> bytes:
        with self._detail_counter_lock:
            self.detail_calls += 1
            self.active_detail_calls += 1
            self.max_active_detail_calls = max(
                self.max_active_detail_calls, self.active_detail_calls
            )
        try:
            if self.detail_delay_seconds:
                time.sleep(self.detail_delay_seconds)
            if deployed_model in self.detail_overrides:
                return self.detail_overrides[deployed_model]
            if self.detail_override is not None:
                return self.detail_override
            match = next(item for item in self.items if item["deployed_model"] == deployed_model)
            return json.dumps(match, separators=(",", ":")).encode()
        finally:
            with self._detail_counter_lock:
                self.active_detail_calls -= 1


def _manifest(
    *,
    base_model: str = STRONG_BASE,
    workspace_ref: str = "workspace-cn-beijing-031",
    ownership_nonce: str = OWNERSHIP_NONCE,
    operation_marker: str | None = None,
    deployment_suffix: str | None = None,
    deployed_model: str | None = None,
    status: str = "RUNNING",
    **extra: object,
) -> dict[str, object]:
    marker = operation_marker or deterministic_operation_marker(
        "golden-v01-run-031", "op-strong-031", ownership_nonce
    )
    suffix = deployment_suffix or deterministic_deployment_suffix(
        "golden-v01-run-031", "op-strong-031", ownership_nonce
    )
    value: dict[str, object] = {
        "deployed_model": deployed_model or f"{base_model}-{suffix}",
        "base_model": base_model,
        "plan": "ptu",
        "input_tpm": 10_000,
        "output_tpm": 1_000,
        "status": status,
        "gmt_create": "2026-07-21T07:58:00Z",
        "gmt_modified": "2026-07-21T07:59:00Z",
        "workspace_ref": workspace_ref,
        "ownership_nonce": ownership_nonce,
        "operation_marker": marker,
        "deployment_suffix": suffix,
    }
    value.update(extra)
    return value


def _standalone_receipt(**updates: Any) -> DeploymentReceipt:
    values: dict[str, object] = {
        "operation_id": "op-strong-031",
        "infrastructure_reserve_id": "infra-strong-031",
        "workspace_ref": "workspace-cn-beijing-031",
        "project_ref": "sha256:" + SHA_A,
        "credential_ref": "sha256:" + SHA_B,
        "workspace_evidence_digest": SHA_A,
        "region": "cn-beijing",
        "base_model": STRONG_BASE,
        "deployed_model": f"{STRONG_BASE}-031strng",
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
    expected = _standalone_receipt()
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
    expected = _standalone_receipt()
    mutated = DeploymentReceipt.model_construct(
        content=expected.content,
        content_digest="1" * 64,
    )

    with pytest.raises(AuthorizationVerificationError, match="content digest"):
        verify_deployment_receipt(mutated, expected=expected)


def test_o6_receipt_accepts_only_ptu_v2_to_ptu_and_fixed_quota() -> None:
    receipt = _standalone_receipt()
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


def _topology_target(
    transport: _FakeTransport,
    *,
    boundary: Literal["strong", "weak"],
    operation_id: str,
    reserve_id: str,
    base_model: str,
    roles: tuple[Literal["annotator", "extractor", "judge"], ...],
) -> Any:
    manifest_raw = _manifest(
        base_model=base_model,
        operation_marker=deterministic_operation_marker(
            "golden-v01-run-031", operation_id, OWNERSHIP_NONCE
        ),
        deployment_suffix=deterministic_deployment_suffix(
            "golden-v01-run-031", operation_id, OWNERSHIP_NONCE
        ),
    )
    transport.items.append(manifest_raw)
    manifest = ProviderDeploymentManifest.model_validate(manifest_raw)
    content = DeploymentReceiptContent(
        operation_id=operation_id,
        infrastructure_reserve_id=reserve_id,
        workspace_ref=transport.identity.workspace_ref,
        project_ref=transport.identity.project_ref,
        credential_ref=transport.identity.credential_ref,
        workspace_evidence_digest=transport_workspace_evidence_digest(transport.identity),
        region="cn-beijing",
        base_model=manifest.base_model,
        deployed_model=manifest.deployed_model,
        request_plan="ptu_v2",
        receipt_plan=manifest.plan,
        input_tpm=manifest.input_tpm,
        output_tpm=manifest.output_tpm,
        gmt_create=manifest.gmt_create,
        gmt_modified=manifest.gmt_modified,
        cleanup_state="required",
        operation_marker=manifest.operation_marker,
        deployment_suffix=manifest.deployment_suffix,
        remote_manifest_digest=provider_manifest_digest(manifest),
    )
    receipt = DeploymentReceipt(
        content=content,
        content_digest=deployment_receipt_content_digest(content),
    )
    return admission_deployment.TopologyReconciliationTargetV1(
        boundary=boundary,
        receipt=receipt,
        expected_remote_manifest=manifest,
        roles=roles,
    )


def _topology_refresh_case(
    tmp_path: Path,
    *,
    clock: Callable[[], datetime],
) -> tuple[DeploymentController, _FakeTransport, Any, Any, Path]:
    transport = _FakeTransport()
    transport.identity = _issue_verified_deployment_transport_identity_for_testing(
        workspace_ref=transport.workspace_ref,
        project_ref=transport.project_ref,
        credential_ref=transport.credential_ref,
        provider_cap_evidence_digest=SHA_D,
        topology_digest="1" * 64,
        expires_at=NOW + timedelta(hours=1),
    )
    strong = _topology_target(
        transport,
        boundary="strong",
        operation_id="op-strong-031",
        reserve_id="infra-strong-031",
        base_model=STRONG_BASE,
        roles=("annotator", "judge"),
    )
    weak = _topology_target(
        transport,
        boundary="weak",
        operation_id="op-weak-031",
        reserve_id="infra-weak-031",
        base_model="deepseek-v4-flash",
        roles=("extractor",),
    )
    payload = _authorization_payload()
    controller, _authorization, _permit_value = _controller(
        tmp_path,
        transport,
        payload,
        clock=clock,
    )
    return controller, transport, strong, weak, controller._store.root


def _write_bound_topology_artifacts(
    controller: DeploymentController,
    target: Any,
) -> str:
    identity = controller._transport.identity
    artifact = DeploymentReceiptArtifact(
        receipt=target.receipt,
        remote_manifest=target.expected_remote_manifest,
        remote_manifest_digest=target.receipt.content.remote_manifest_digest,
    )
    observed_at = NOW - timedelta(minutes=1)
    expires_at = NOW + timedelta(minutes=30)
    digest = deployment_reconciliation_digest(
        issuer="bailian-deployment-controller-v1",
        transport_identity_digest=identity.identity_digest,
        run_identity="golden-v01-run-031",
        purpose="golden-v0.1 production run",
        scope="goldenset-production",
        receipt_digest=target.receipt.content_digest,
        operation_id=target.receipt.content.operation_id,
        reserve_id=target.receipt.content.infrastructure_reserve_id,
        workspace_ref=target.receipt.content.workspace_ref,
        project_ref=target.receipt.content.project_ref,
        credential_ref=target.receipt.content.credential_ref,
        provider_cap_evidence_digest=identity.provider_cap_evidence_digest,
        provider_cap_approval_digest=identity.provider_cap_approval_digest,
        remote_manifest_digest=target.receipt.content.remote_manifest_digest,
        observed_at=observed_at,
        expires_at=expires_at,
    )
    evidence = DeploymentReconciliationEvidenceV1(
        version="insurancekb.run-admission.deployment-reconciliation-evidence.v1",
        issuer="bailian-deployment-controller-v1",
        transport_identity_digest=identity.identity_digest,
        run_identity="golden-v01-run-031",
        purpose="golden-v0.1 production run",
        scope="goldenset-production",
        receipt=target.receipt,
        remote_manifest=target.expected_remote_manifest,
        receipt_digest=target.receipt.content_digest,
        operation_id=target.receipt.content.operation_id,
        reserve_id=target.receipt.content.infrastructure_reserve_id,
        workspace_ref=target.receipt.content.workspace_ref,
        project_ref=target.receipt.content.project_ref,
        credential_ref=target.receipt.content.credential_ref,
        provider_cap_evidence_digest=identity.provider_cap_evidence_digest,
        provider_cap_approval_digest=identity.provider_cap_approval_digest,
        remote_manifest_digest=target.receipt.content.remote_manifest_digest,
        observed_at=observed_at,
        expires_at=expires_at,
        reconciliation_digest=digest,
    )
    controller._store.atomic_write(
        f"{target.receipt.content_digest}.receipt.json",
        canonical_json_bytes(artifact),
    )
    controller._store.atomic_write(
        f"{digest}.receipt-reconciliation.json",
        canonical_json_bytes(evidence),
    )
    return digest


def _refresh_topology_batch(
    controller: DeploymentController,
    *,
    strong: Any,
    weak: Any,
) -> Any:
    return controller._refresh_topology_reconciliation_batch_for_testing(
        run_identity="golden-v01-run-031",
        purpose="golden-v0.1 production run",
        scope="goldenset-production",
        topology_digest="1" * 64,
        plan_payload_hash="2" * 64,
        provider_cap_evidence_digest=SHA_D,
        provider_cap_approval_digest="f" * 64,
        strong=strong,
        weak=weak,
    )


def test_o6_old_topology_observation_batch_cannot_replace_boundary_refresh_at_t_plus_5_01(
    tmp_path: Path,
) -> None:
    current = [NOW]
    controller, transport, strong, weak, _root = _topology_refresh_case(
        tmp_path,
        clock=lambda: current[0],
    )

    first = _refresh_topology_batch(controller, strong=strong, weak=weak)
    current[0] = NOW + timedelta(minutes=5, seconds=1)
    second = _refresh_topology_batch(controller, strong=strong, weak=weak)

    assert type(first.batch).__name__ == "TopologyReconciliationObservationBatchV1"
    assert first.batch.provider_cap_approval_digest == "f" * 64
    assert first.batch.expires_at == NOW + timedelta(minutes=5)
    assert second.batch.observed_at == current[0]
    assert second.batch_digest != first.batch_digest
    assert second.artifact_path != first.artifact_path
    assert transport.detail_calls == 4


@pytest.mark.parametrize(("boundary", "expected_gets"), [("strong", 1), ("weak", 2)])
def test_o6_topology_observation_batch_rejects_either_manifest_drift_without_artifact(
    tmp_path: Path,
    boundary: str,
    expected_gets: int,
) -> None:
    controller, transport, strong, weak, root = _topology_refresh_case(
        tmp_path,
        clock=lambda: NOW,
    )
    target = strong if boundary == "strong" else weak
    drifted = target.expected_remote_manifest.model_copy(
        update={"gmt_modified": NOW + timedelta(minutes=1)}
    )
    transport.detail_overrides[target.receipt.content.deployed_model] = canonical_json_bytes(
        drifted
    )

    with pytest.raises(DeploymentControlBlocked) as blocked:
        _refresh_topology_batch(controller, strong=strong, weak=weak)

    assert blocked.value.code == "topology_observation_drift"
    assert transport.detail_calls == expected_gets
    assert list(root.glob("*.topology-observation-batch.json")) == []


def test_o6_topology_observation_rejects_cap_approval_drift_before_get_or_artifact(
    tmp_path: Path,
) -> None:
    controller, transport, strong, weak, root = _topology_refresh_case(
        tmp_path,
        clock=lambda: NOW,
    )

    with pytest.raises(DeploymentControlBlocked) as blocked:
        controller._refresh_topology_reconciliation_batch_for_testing(
            run_identity="golden-v01-run-031",
            purpose="golden-v0.1 production run",
            scope="goldenset-production",
            topology_digest="1" * 64,
            plan_payload_hash="2" * 64,
            provider_cap_evidence_digest=SHA_D,
            provider_cap_approval_digest="e" * 64,
            strong=strong,
            weak=weak,
        )

    assert blocked.value.code == "topology_transport_identity_invalid"
    assert transport.detail_calls == 0
    assert list(root.glob("*.topology-observation-batch.json")) == []


@pytest.mark.parametrize("failure_point", ["replace", "file_fsync", "directory_fsync"])
def test_o6_topology_observation_batch_atomic_failure_leaves_no_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    controller, _transport, strong, weak, root = _topology_refresh_case(
        tmp_path,
        clock=lambda: NOW,
    )
    original_fsync = os.fsync
    fsync_calls = 0

    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated batch publication failure")

    def fail_fsync(descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if failure_point == "file_fsync" and fsync_calls == 1:
            raise OSError("simulated batch file fsync failure")
        if failure_point == "directory_fsync" and fsync_calls == 2:
            raise OSError("simulated batch directory fsync failure")
        original_fsync(descriptor)

    if failure_point == "replace":
        monkeypatch.setattr(os, "replace", fail_replace)
    else:
        monkeypatch.setattr(os, "fsync", fail_fsync)

    with pytest.raises(DeploymentControlBlocked, match="artifact write"):
        _refresh_topology_batch(controller, strong=strong, weak=weak)

    assert list(root.glob("*.topology-observation-batch.json")) == []
    assert list(root.glob(".*.tmp")) == []


def test_o6_topology_observation_batch_concurrent_exact_replay_is_serial_and_idempotent(
    tmp_path: Path,
) -> None:
    controller, transport, strong, weak, root = _topology_refresh_case(
        tmp_path,
        clock=lambda: NOW,
    )
    transport.detail_delay_seconds = 0.01
    results: list[Any] = []
    failures: list[BaseException] = []

    def refresh() -> None:
        try:
            results.append(_refresh_topology_batch(controller, strong=strong, weak=weak))
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    threads = [threading.Thread(target=refresh) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert failures == []
    assert len(results) == 4
    assert len({result.batch_digest for result in results}) == 1
    assert len({result.artifact_path for result in results}) == 1
    assert transport.detail_calls == 8
    assert transport.max_active_detail_calls == 1
    assert len(list(root.glob("*.topology-observation-batch.json"))) == 1
    assert list(root.glob(".*.tmp")) == []


def _controller(
    tmp_path: Path,
    transport: DeploymentControlTransport,
    payload: ProvisioningAuthorizationPayload,
    *,
    clock: Callable[[], datetime] = lambda: NOW,
) -> tuple[DeploymentController, ProvisioningAuthorization, InfrastructureCreatePermit]:
    key = Ed25519PrivateKey.generate()
    object.__setattr__(payload, "_test_signing_key", key)
    authorization = _signed_authorization(key, payload)
    permit = _permit(payload)
    root = tmp_path / "deployment-control"
    root.mkdir(mode=0o700)
    controller = DeploymentController._for_testing(
        run_root=root,
        reserve_reader=_ReserveReader(permit.reserve),
        transport=transport,
        clock=clock,
    )
    return controller, authorization, permit


def _provision(
    controller: DeploymentController,
    authorization: ProvisioningAuthorization,
    permit: InfrastructureCreatePermit,
) -> DeploymentControlResult:
    key = cast(
        Ed25519PrivateKey,
        authorization.payload.__dict__["_test_signing_key"],
    )
    assert isinstance(key, Ed25519PrivateKey)
    return controller._provision_for_testing(
        authorization=authorization,
        permit=permit,
        trusted_authorities=_policy(key),
    )


def test_o4_provider_cap_approval_digest_drift_blocks_before_network_or_artifact(
    tmp_path: Path,
) -> None:
    payload = _authorization_payload(provider_cap_approval_digest="f" * 64)
    transport = _FakeTransport()
    transport.identity = _issue_verified_deployment_transport_identity_for_testing(
        workspace_ref=payload.workspace_ref,
        project_ref=payload.project_ref,
        credential_ref=payload.credential_ref,
        provider_cap_evidence_digest=payload.provider_cap_evidence_digest,
        provider_cap_approval_digest="e" * 64,
        expires_at=payload.provider_cap_expires_at,
    )
    controller, authorization, permit = _controller(tmp_path, transport, payload)

    with pytest.raises(DeploymentControlBlocked) as blocked:
        _provision(controller, authorization, permit)

    assert blocked.value.code == "transport_identity_mismatch"
    assert transport.list_calls == transport.post_calls == transport.detail_calls == 0
    assert tuple((tmp_path / "deployment-control").iterdir()) == ()


def test_o5_fixed_request_journal_and_redacted_content_addressed_receipt(
    tmp_path: Path,
) -> None:
    payload = _authorization_payload()
    transport = _FakeTransport()
    controller, authorization, permit = _controller(tmp_path, transport, payload)

    result = _provision(controller, authorization, permit)

    assert transport.post_calls == 1
    assert result.receipt.content.base_model == STRONG_BASE
    assert result.receipt.content.request_plan == "ptu_v2"
    assert result.receipt.content.receipt_plan == "ptu"
    assert result.receipt.content.input_tpm == 10_000
    assert result.receipt.content.output_tpm == 1_000
    assert result.receipt_path.name == f"{result.receipt.content_digest}.receipt.json"
    assert result.receipt_path.stat().st_mode & 0o777 == 0o600
    stored = result.receipt_path.read_bytes()
    assert b"secret" not in stored
    assert b"/Users/" not in stored
    journal = json.loads(result.journal_path.read_bytes())
    assert journal["history"] == [
        "authorized",
        "reserved",
        "prepared",
        "created",
        "receipted",
    ]


def test_o6_controller_publishes_immutable_reconciliation_evidence_and_replays(
    tmp_path: Path,
) -> None:
    payload = _authorization_payload()
    transport = _FakeTransport()
    controller, authorization, permit = _controller(tmp_path, transport, payload)

    first = _provision(controller, authorization, permit)
    root = tmp_path / "deployment-control"
    evidence_path = root / (
        f"{first.receipt_capability.reconciliation_digest}.receipt-reconciliation.json"
    )
    first_bytes = evidence_path.read_bytes()
    evidence = DeploymentReconciliationEvidenceV1.model_validate_json(first_bytes)

    assert canonical_json_bytes(evidence) == first_bytes
    assert evidence.receipt == first.receipt
    assert evidence.reconciliation_digest == (first.receipt_capability.reconciliation_digest)
    assert evidence.provider_cap_evidence_digest == (payload.provider_cap_evidence_digest)
    assert evidence.provider_cap_approval_digest == (payload.provider_cap_approval_digest)

    replay = _provision(controller, authorization, permit)

    assert replay.receipt == first.receipt
    assert evidence_path.read_bytes() == first_bytes
    assert len(list(root.glob("*.receipt-reconciliation.json"))) == 1


def test_o6_reconciliation_artifact_failure_cannot_publish_receipt_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _authorization_payload()
    transport = _FakeTransport()
    controller, authorization, permit = _controller(tmp_path, transport, payload)
    original_publish = controller._store.atomic_write_absent_on_failure

    def fail_reconciliation_artifact(name: str, content: bytes) -> None:
        if name.endswith(".receipt-reconciliation.json"):
            raise DeploymentControlBlocked(
                "operation_artifact_unsafe",
                "simulated reconciliation artifact publication failure",
            )
        original_publish(name, content)

    monkeypatch.setattr(
        controller._store,
        "atomic_write_absent_on_failure",
        fail_reconciliation_artifact,
    )

    with pytest.raises(DeploymentControlBlocked, match="simulated reconciliation"):
        _provision(controller, authorization, permit)

    root = tmp_path / "deployment-control"
    assert len(list(root.glob("*.receipt.json"))) == 1
    assert list(root.glob("*.receipt-reconciliation.json")) == []
    assert list(root.glob(".*.tmp")) == []
    journal_path = next(root.glob("*.journal.json"))
    # The terminal receipt pointer is durable before reconciliation capability
    # mint, so restart can safely revalidate and resume without another POST.
    assert json.loads(journal_path.read_bytes())["state"] == "receipted"

    monkeypatch.setattr(
        controller._store,
        "atomic_write_absent_on_failure",
        original_publish,
    )
    recovered = _provision(controller, authorization, permit)

    assert recovered.receipt_path.exists()
    assert len(list(root.glob("*.receipt-reconciliation.json"))) == 1


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_o6_absent_on_failure_removes_named_artifact_when_directory_fsync_is_interrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: type[BaseException],
) -> None:
    payload = _authorization_payload()
    transport = _FakeTransport()
    controller, _authorization, _permit_value = _controller(tmp_path, transport, payload)
    original_fsync = os.fsync
    fsync_calls = 0

    def interrupt_directory_fsync(descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 2:
            raise interruption("simulated process-control interruption")
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", interrupt_directory_fsync)
    name = f"{'7' * 64}.receipt-reconciliation.json"

    with pytest.raises(interruption):
        controller._store.atomic_write_absent_on_failure(name, b"{}")

    root = controller._store.root
    assert not (root / name).exists()
    assert list(root.glob(".*.tmp")) == []
    controller.close()


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_o6_absent_on_failure_cleans_successful_rename_interrupted_before_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: type[BaseException],
) -> None:
    payload = _authorization_payload()
    controller, _authorization, _permit_value = _controller(
        tmp_path,
        _FakeTransport(),
        payload,
    )
    original_replace = os.replace

    def replace_then_interrupt(
        source: Any,
        destination: Any,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        original_replace(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )
        raise interruption("rename completed before process-control interruption")

    monkeypatch.setattr(os, "replace", replace_then_interrupt)
    name = f"{'6' * 64}.receipt-reconciliation.json"

    with pytest.raises(interruption):
        controller._store.atomic_write_absent_on_failure(name, b"{}")

    assert not (controller._store.root / name).exists()
    assert list(controller._store.root.glob(".*.tmp")) == []
    controller.close()


def test_o6_absent_on_failure_does_not_delete_foreign_inode_after_rename_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _authorization_payload()
    controller, _authorization, _permit_value = _controller(
        tmp_path,
        _FakeTransport(),
        payload,
    )
    original_replace = os.replace
    foreign = b"foreign-owner"

    def replace_then_foreign_takeover(
        source: Any,
        destination: Any,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        original_replace(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )
        name = cast(str, destination)
        assert dst_dir_fd is not None
        root_fd = dst_dir_fd
        os.unlink(name, dir_fd=root_fd)
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=root_fd,
        )
        try:
            os.write(descriptor, foreign)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        raise KeyboardInterrupt("foreign inode replaced completed rename")

    monkeypatch.setattr(os, "replace", replace_then_foreign_takeover)
    name = f"{'5' * 64}.receipt-reconciliation.json"

    with pytest.raises(KeyboardInterrupt):
        controller._store.atomic_write_absent_on_failure(name, b"{}")

    assert (controller._store.root / name).read_bytes() == foreign
    assert list(controller._store.root.glob(".*.tmp")) == []
    controller.close()


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_o6_atomic_publication_readback_interrupt_removes_only_own_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: type[BaseException],
) -> None:
    payload = _authorization_payload()
    controller, _authorization, _permit_value = _controller(
        tmp_path,
        _FakeTransport(),
        payload,
    )
    original_read = controller._store.read
    reads = 0

    def interrupt_final_readback(name: str) -> bytes | None:
        nonlocal reads
        reads += 1
        if reads == 2:
            raise interruption("publication readback interrupted")
        return original_read(name)

    monkeypatch.setattr(controller._store, "read", interrupt_final_readback)
    name = f"{'4' * 64}.receipt-reconciliation.json"

    with pytest.raises(interruption):
        controller._store.atomic_write_absent_on_failure(name, b"{}")

    assert not (controller._store.root / name).exists()
    assert list(controller._store.root.glob(".*.tmp")) == []
    controller.close()


def test_o6_atomic_publication_readback_foreign_takeover_is_not_deleted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _authorization_payload()
    controller, _authorization, _permit_value = _controller(
        tmp_path,
        _FakeTransport(),
        payload,
    )
    original_read = controller._store.read
    foreign = b"foreign-owner"
    reads = 0
    name = f"{'3' * 64}.receipt-reconciliation.json"

    def replace_before_final_readback(candidate: str) -> bytes | None:
        nonlocal reads
        reads += 1
        if reads == 2:
            path = controller._store.root / candidate
            path.unlink()
            path.write_bytes(foreign)
            path.chmod(0o600)
        return original_read(candidate)

    monkeypatch.setattr(controller._store, "read", replace_before_final_readback)

    with pytest.raises(DeploymentControlBlocked, match="readback"):
        controller._store.atomic_write_absent_on_failure(name, b"{}")

    assert (controller._store.root / name).read_bytes() == foreign
    assert list(controller._store.root.glob(".*.tmp")) == []
    controller.close()


def test_o6_atomic_publication_distinguishes_created_from_exact_replay(
    tmp_path: Path,
) -> None:
    payload = _authorization_payload()
    controller, _authorization, _permit_value = _controller(
        tmp_path,
        _FakeTransport(),
        payload,
    )
    name = f"{'2' * 64}.receipt-reconciliation.json"

    publication = controller._store.atomic_write_absent_on_failure(name, b"{}")
    replay = controller._store.atomic_write_absent_on_failure(name, b"{}")

    assert publication is not None
    assert replay is None
    assert (controller._store.root / name).read_bytes() == b"{}"
    controller.close()


def test_o6_owned_cleanup_quarantines_before_foreign_takeover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _authorization_payload()
    controller, _authorization, _permit_value = _controller(
        tmp_path,
        _FakeTransport(),
        payload,
    )
    name = f"{'1' * 64}.receipt-reconciliation.json"
    publication = controller._store.atomic_write_absent_on_failure(name, b"{}")
    assert publication is not None
    original_rename = os.rename
    foreign = b"foreign-owner-after-cleanup-start"
    takeover_calls = 0

    def takeover_before_quarantine(
        source: Any,
        destination: Any,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        nonlocal takeover_calls
        if source == name:
            takeover_calls += 1
            path = controller._store.root / name
            path.unlink()
            path.write_bytes(foreign)
            path.chmod(0o600)
        original_rename(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(os, "rename", takeover_before_quarantine)

    removed = controller._store.remove_if_owned(name, publication)

    assert takeover_calls == 1
    assert removed is False
    assert (controller._store.root / name).read_bytes() == foreign
    assert list(controller._store.root.glob(".cleanup-*.tmp")) == []
    controller.close()


def test_o6_owned_cleanup_restores_foreign_symlink_without_following(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _authorization_payload()
    controller, _authorization, _permit_value = _controller(
        tmp_path,
        _FakeTransport(),
        payload,
    )
    name = f"{'0' * 64}.receipt-reconciliation.json"
    publication = controller._store.atomic_write_absent_on_failure(name, b"{}")
    assert publication is not None
    original_rename = os.rename
    foreign_target = "foreign-owner-target"

    def symlink_takeover_before_quarantine(
        source: Any,
        destination: Any,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        if source == name:
            path = controller._store.root / name
            path.unlink()
            path.symlink_to(foreign_target)
        original_rename(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(os, "rename", symlink_takeover_before_quarantine)

    removed = controller._store.remove_if_owned(name, publication)

    path = controller._store.root / name
    assert removed is False
    assert path.is_symlink()
    assert path.readlink() == Path(foreign_target)
    assert list(controller._store.root.glob(".cleanup-*.tmp")) == []
    controller.close()


def test_o6_owned_cleanup_restores_original_name_when_quarantine_open_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _authorization_payload()
    controller, _authorization, _permit_value = _controller(
        tmp_path,
        _FakeTransport(),
        payload,
    )
    name = f"{'9' * 64}.receipt-reconciliation.json"
    publication = controller._store.atomic_write_absent_on_failure(name, b"{}")
    assert publication is not None
    original_open = os.open

    def fail_quarantine_open(path: Any, *args: Any, **kwargs: Any) -> int:
        if isinstance(path, str) and path.startswith(".cleanup-"):
            raise OSError(24, "simulated descriptor exhaustion")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", fail_quarantine_open)

    removed = controller._store.remove_if_owned(name, publication)

    assert removed is False
    assert (controller._store.root / name).read_bytes() == b"{}"
    assert list(controller._store.root.glob(".cleanup-*.tmp")) == []
    controller.close()


def test_o6_owned_cleanup_surfaces_and_preserves_double_takeover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _authorization_payload()
    controller, _authorization, _permit_value = _controller(
        tmp_path,
        _FakeTransport(),
        payload,
    )
    name = f"{'f' * 64}.receipt-reconciliation.json"
    publication = controller._store.atomic_write_absent_on_failure(name, b"{}")
    assert publication is not None
    original_rename = os.rename
    foreign_a = b"foreign-owner-a"
    foreign_b = b"foreign-owner-b"

    def double_takeover_before_quarantine(
        source: Any,
        destination: Any,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        if source == name:
            path = controller._store.root / name
            path.unlink()
            path.write_bytes(foreign_a)
            path.chmod(0o600)
            original_rename(
                source,
                destination,
                src_dir_fd=src_dir_fd,
                dst_dir_fd=dst_dir_fd,
            )
            path.write_bytes(foreign_b)
            path.chmod(0o600)
            return
        original_rename(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(os, "rename", double_takeover_before_quarantine)

    with pytest.raises(DeploymentControlBlocked, match="cleanup conflict"):
        controller._store.remove_if_owned(name, publication)

    assert (controller._store.root / name).read_bytes() == foreign_b
    preserved = list(controller._store.root.glob(".foreign-preserved-*.artifact"))
    assert len(preserved) == 1
    assert preserved[0].read_bytes() == foreign_a
    assert list(controller._store.root.glob(".cleanup-*.tmp")) == []
    controller.close()


def test_o6_owned_cleanup_explicitly_preserves_non_linkable_foreign_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _authorization_payload()
    controller, _authorization, _permit_value = _controller(
        tmp_path,
        _FakeTransport(),
        payload,
    )
    name = f"{'e' * 64}.receipt-reconciliation.json"
    publication = controller._store.atomic_write_absent_on_failure(name, b"{}")
    assert publication is not None
    original_rename = os.rename

    def directory_takeover_before_quarantine(
        source: Any,
        destination: Any,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        if source == name:
            path = controller._store.root / name
            path.unlink()
            path.mkdir(mode=0o700)
        original_rename(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(os, "rename", directory_takeover_before_quarantine)

    with pytest.raises(DeploymentControlBlocked, match="cleanup conflict"):
        controller._store.remove_if_owned(name, publication)

    preserved = list(controller._store.root.glob(".foreign-preserved-*.artifact"))
    assert len(preserved) == 1
    assert preserved[0].is_dir()
    assert list(controller._store.root.glob(".cleanup-*.tmp")) == []
    controller.close()


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_o6_owned_cleanup_resolves_completed_quarantine_rename_before_rethrow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: type[BaseException],
) -> None:
    payload = _authorization_payload()
    controller, _authorization, _permit_value = _controller(
        tmp_path,
        _FakeTransport(),
        payload,
    )
    name = f"{'d' * 64}.receipt-reconciliation.json"
    publication = controller._store.atomic_write_absent_on_failure(name, b"{}")
    assert publication is not None
    original_rename = os.rename

    def rename_then_interrupt(
        source: Any,
        destination: Any,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        original_rename(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )
        raise interruption("quarantine rename completed before interruption")

    monkeypatch.setattr(os, "rename", rename_then_interrupt)

    with pytest.raises(interruption):
        controller._store.remove_if_owned(name, publication)

    assert not (controller._store.root / name).exists()
    assert list(controller._store.root.glob(".cleanup-*.tmp")) == []
    controller.close()


@pytest.mark.parametrize("readback", [None, b"{}\n"])
def test_o5_o6_receipt_artifact_readback_must_be_exact_before_capability_mint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    readback: bytes | None,
) -> None:
    payload = _authorization_payload()
    transport = _FakeTransport()
    controller, authorization, permit = _controller(tmp_path, transport, payload)
    original_read = controller._store.read
    original_issuer = _testing_receipt_issuer()
    mint_calls = 0
    receipt_reads = 0

    def observe_mint(**values: object) -> Any:
        nonlocal mint_calls
        mint_calls += 1
        return original_issuer(**values)

    def hostile_readback(name: str) -> bytes | None:
        nonlocal receipt_reads
        value = original_read(name)
        if name.endswith(".receipt.json") and value is not None:
            receipt_reads += 1
            # The first read is atomic_write()'s own durability check.  Corrupt
            # only the controller's subsequent trust-boundary readback.
            if receipt_reads >= 2:
                return readback
        return value

    monkeypatch.setattr(
        admission_deployment,
        "_issue_verified_reconciled_receipt_for_testing",
        observe_mint,
    )
    monkeypatch.setattr(controller._store, "read", hostile_readback)

    with pytest.raises(DeploymentControlBlocked) as blocked:
        _provision(controller, authorization, permit)

    assert mint_calls == 0
    assert blocked.value.code in {
        "operation_artifact_unsafe",
        "receipt_conflict",
        "receipt_invalid",
    }


@pytest.mark.parametrize("readback", [None, b"{}\n"])
def test_o5_o6_reconciliation_readback_must_be_exact_before_capability_mint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    readback: bytes | None,
) -> None:
    payload = _authorization_payload()
    transport = _FakeTransport()
    controller, authorization, permit = _controller(tmp_path, transport, payload)
    original_read = controller._store.read
    original_issuer = _testing_receipt_issuer()
    mint_calls = 0
    evidence_reads = 0

    def observe_mint(**values: object) -> Any:
        nonlocal mint_calls
        mint_calls += 1
        return original_issuer(**values)

    def hostile_readback(name: str) -> bytes | None:
        nonlocal evidence_reads
        value = original_read(name)
        if name.endswith(".receipt-reconciliation.json") and value is not None:
            evidence_reads += 1
            if evidence_reads >= 2:
                return readback
        return value

    monkeypatch.setattr(
        admission_deployment,
        "_issue_verified_reconciled_receipt_for_testing",
        observe_mint,
    )
    monkeypatch.setattr(controller._store, "read", hostile_readback)

    with pytest.raises(DeploymentControlBlocked) as blocked:
        _provision(controller, authorization, permit)

    assert mint_calls == 0
    assert blocked.value.code in {
        "operation_artifact_unsafe",
        "receipt_reconciliation_invalid",
    }


@pytest.mark.parametrize(
    ("artifact_suffix", "expected_code"),
    [
        (".receipt.json", "receipt_publication_proof_invalid"),
        (".receipt-reconciliation.json", "receipt_publication_proof_invalid"),
    ],
)
def test_o5_i3_authority_sink_rereads_fixed_store_before_capability_mint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_suffix: str,
    expected_code: str,
) -> None:
    payload = _authorization_payload()
    transport = _FakeTransport()
    controller, authorization, permit = _controller(tmp_path, transport, payload)
    original_read = controller._store.read
    original_mint = controller._mint_reconciled_receipt_from_publication
    original_issuer = _testing_receipt_issuer()
    mint_calls = 0
    in_authority_sink = False

    def observe_mint(**values: object) -> Any:
        nonlocal mint_calls
        mint_calls += 1
        return original_issuer(**values)

    def corrupt_only_at_authority_sink(name: str) -> bytes | None:
        value = original_read(name)
        if in_authority_sink and name.endswith(artifact_suffix) and value is not None:
            return b"{}\n"
        return value

    def enter_authority_sink(proof: Any) -> VerifiedReconciledDeploymentReceipt:
        nonlocal in_authority_sink
        in_authority_sink = True
        try:
            return original_mint(proof)
        finally:
            in_authority_sink = False

    monkeypatch.setattr(
        admission_deployment,
        "_issue_verified_reconciled_receipt_for_testing",
        observe_mint,
    )
    monkeypatch.setattr(controller._store, "read", corrupt_only_at_authority_sink)
    monkeypatch.setattr(
        controller,
        "_mint_reconciled_receipt_from_publication",
        enter_authority_sink,
    )

    with pytest.raises(DeploymentControlBlocked) as blocked:
        _provision(controller, authorization, permit)

    assert blocked.value.code == expected_code
    assert mint_calls == 0


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("provider", "other"),
        ("region", "cn-shanghai"),
        ("base_model", "qwen3.7-plus-latest"),
        ("request_plan", "ptu"),
        ("receipt_plan", "ptu_v2"),
        ("input_tpm_quota", 20_000),
        ("output_tpm_quota", 2_000),
    ],
)
def test_o5_configuration_drift_is_blocked_before_network(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    original = _authorization_payload()
    values = original.model_dump(mode="python")
    values[field] = replacement
    payload = ProvisioningAuthorizationPayload.model_construct(**values)
    transport = _FakeTransport()
    controller, authorization, permit = _controller(tmp_path, transport, payload)

    with pytest.raises(DeploymentControlBlocked):
        _provision(controller, authorization, permit)

    assert transport.list_calls == 0
    assert transport.post_calls == 0
    assert transport.detail_calls == 0


def test_o5_endpoint_or_durable_reserve_drift_is_blocked_before_network(
    tmp_path: Path,
) -> None:
    payload = _authorization_payload()
    transport = _FakeTransport()
    transport.endpoint = "https://example.invalid/deployments"
    controller, authorization, permit = _controller(tmp_path, transport, payload)

    with pytest.raises(DeploymentControlBlocked, match="endpoint"):
        _provision(controller, authorization, permit)
    assert transport.list_calls == transport.post_calls == 0

    transport.endpoint = BAILIAN_DEPLOYMENT_ENDPOINT
    forged = permit.model_copy(
        update={"reserve": permit.reserve.model_copy(update={"authorization_digest": "0" * 64})}
    )
    with pytest.raises(DeploymentControlBlocked, match="reserve|permit"):
        _provision(controller, authorization, forged)
    assert transport.list_calls == transport.post_calls == 0


def test_o5_transport_credential_identity_mismatch_blocks_before_network(
    tmp_path: Path,
) -> None:
    payload = _authorization_payload()
    transport = _FakeTransport()
    transport.credential_ref = "sha256:" + "8" * 64
    transport.identity = _issue_verified_deployment_transport_identity_for_testing(
        workspace_ref=transport.workspace_ref,
        project_ref=transport.project_ref,
        credential_ref=transport.credential_ref,
        provider_cap_evidence_digest=SHA_D,
        expires_at=NOW + timedelta(hours=1),
    )
    controller, authorization, permit = _controller(tmp_path, transport, payload)

    blocked: DeploymentControlBlocked | None = None
    try:
        _provision(controller, authorization, permit)
    except DeploymentControlBlocked as exc:
        blocked = exc

    assert (
        blocked is not None and "transport identity" in str(blocked),
        transport.list_calls,
        transport.post_calls,
        transport.detail_calls,
    ) == (True, 0, 0, 0)


def test_o3_production_controller_rejects_caller_self_enrolled_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual_now = datetime.now(UTC)
    payload = _authorization_payload(
        issued_at=actual_now - timedelta(minutes=5),
        expires_at=actual_now + timedelta(minutes=30),
        provider_cap_expires_at=actual_now + timedelta(hours=1),
        cleanup_deadline=actual_now + timedelta(hours=8),
    )
    transport = _FakeTransport()
    transport.identity = _issue_verified_deployment_transport_identity_for_testing(
        workspace_ref=transport.workspace_ref,
        project_ref=transport.project_ref,
        credential_ref=transport.credential_ref,
        provider_cap_evidence_digest=SHA_D,
        expires_at=actual_now + timedelta(hours=1),
    )
    testing_controller, authorization, permit = _controller(tmp_path, transport, payload)
    del testing_controller
    root = tmp_path / "production-deployment-control"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(
        admission_cli,
        "_load_deployment_approval_configuration",
        lambda: ({}, frozenset(), frozenset(), frozenset()),
    )
    key = cast(
        Ed25519PrivateKey,
        authorization.payload.__dict__["_test_signing_key"],
    )
    controller = _production_controller(
        tmp_path,
        monkeypatch,
        run_root=root,
    )
    monkeypatch.setattr(
        admission_cli,
        "_load_deployment_approval_configuration",
        lambda: ({}, frozenset(), frozenset(), frozenset()),
    )

    with pytest.raises(TypeError, match="trusted_authorities"):
        cast(Any, controller.provision)(
            authorization=authorization,
            permit=permit,
            trusted_authorities=_policy(key),
        )
    with pytest.raises(DeploymentControlBlocked) as forbidden_seam:
        controller._provision_for_testing(
            authorization=authorization,
            permit=permit,
            trusted_authorities=_policy(key),
        )

    with pytest.raises(DeploymentControlBlocked) as blocked:
        controller.provision(authorization=authorization, permit=permit)

    assert forbidden_seam.value.code == "testing_seam_forbidden"
    assert blocked.value.code == "production_provider_cap_invalid"
    assert transport.list_calls == transport.post_calls == transport.detail_calls == 0
    assert tuple(root.iterdir()) == ()
    cast(BailianDeploymentHTTPTransport, controller._transport).close()


def test_o5_testing_controller_cannot_issue_production_receipt_with_production_transport_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    provider_cap = fixture.ledger.require_fresh_infrastructure_provider_capability(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=fixture.permit.reserve.reserve_id,
    )
    transport = _FakeTransport()
    transport.identity = issue_verified_deployment_transport_identity(
        api_key=_PRODUCTION_API_KEY,
        provider_capability=provider_cap,
    )
    payload = _authorization_payload(
        credential_ref=provider_cap.credential_ref,
        provider_cap_evidence_digest=provider_cap.evidence_digest,
        provider_cap_approval_digest=provider_cap.approval_digest,
        provider_cap_expires_at=provider_cap.expires_at,
    )
    controller, authorization, permit = _controller(tmp_path, transport, payload)
    with pytest.raises(DeploymentControlBlocked) as blocked:
        _provision(controller, authorization, permit)

    assert blocked.value.code == "transport_identity_invalid"
    assert transport.list_calls == transport.post_calls == transport.detail_calls == 0


@pytest.mark.parametrize("mode", ["timeout_after_accept", "conflict_after_accept"])
def test_o5_ambiguous_post_reconciles_without_duplicate_create(
    tmp_path: Path,
    mode: str,
) -> None:
    payload = _authorization_payload()
    transport = _FakeTransport()
    transport.create_mode = mode
    controller, authorization, permit = _controller(tmp_path, transport, payload)

    first = _provision(controller, authorization, permit)
    second = _provision(controller, authorization, permit)

    assert first.receipt == second.receipt
    assert transport.post_calls == 1
    assert json.loads(first.journal_path.read_bytes())["history"] == [
        "authorized",
        "reserved",
        "prepared",
        "reconciled",
        "receipted",
    ]


@pytest.mark.parametrize("foreign_nonce", [None, "0" * 32])
def test_o5_c1_foreign_actor_race_cannot_claim_ownership_without_exact_journal_nonce(
    tmp_path: Path,
    foreign_nonce: str | None,
) -> None:
    class _ForeignRaceTransport(_FakeTransport):
        def create_deployment(self, *, request_body: bytes, idempotency_key: str) -> bytes:
            del idempotency_key
            self.post_calls += 1
            request = json.loads(request_body)
            foreign = _manifest(
                base_model=request["base_model"],
                workspace_ref=request["workspace_ref"],
                operation_marker=request["operation_marker"],
                deployment_suffix=request["deployment_suffix"],
            )
            if foreign_nonce is None:
                foreign.pop("ownership_nonce")
            else:
                foreign["ownership_nonce"] = foreign_nonce
            self.items.append(foreign)
            raise DeploymentProviderConflict("foreign actor won the provider race")

    payload = _authorization_payload()
    transport = _ForeignRaceTransport()
    controller, authorization, permit = _controller(tmp_path, transport, payload)

    with pytest.raises(DeploymentControlBlocked) as blocked:
        _provision(controller, authorization, permit)

    assert blocked.value.code == "provider_outcome_uncertain"
    assert transport.list_calls == 2
    assert transport.post_calls == 1
    assert transport.detail_calls == 0
    assert not tuple(controller._store.root.glob("*.receipt.json"))
    assert not tuple(controller._store.root.glob("*.receipt-reconciliation.json"))


def test_o5_two_operators_share_run_lock_and_create_at_most_once(tmp_path: Path) -> None:
    payload = _authorization_payload()
    transport = _FakeTransport()
    controller, authorization, permit = _controller(tmp_path, transport, payload)
    results: list[DeploymentControlResult] = []

    def run() -> None:
        results.append(_provision(controller, authorization, permit))

    threads = [threading.Thread(target=run), threading.Thread(target=run)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(results) == 2
    assert transport.post_calls == 1
    assert results[0].receipt == results[1].receipt


def test_o5_marker_collision_or_foreign_manifest_blocks_without_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(secrets, "token_hex", lambda size: OWNERSHIP_NONCE)
    payload = _authorization_payload()
    transport = _FakeTransport()
    collision = _manifest()
    transport.items = [collision, dict(collision)]
    controller, authorization, permit = _controller(tmp_path, transport, payload)

    with pytest.raises(DeploymentControlBlocked, match="multiple"):
        _provision(controller, authorization, permit)
    assert transport.post_calls == 0

    transport.items = [_manifest(base_model="deepseek-v4-flash")]
    with pytest.raises(DeploymentControlBlocked, match="manifest|foreign"):
        _provision(controller, authorization, permit)
    assert transport.post_calls == 0


def test_o5_first_observation_of_exact_remote_match_requires_adoption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(secrets, "token_hex", lambda size: OWNERSHIP_NONCE)
    payload = _authorization_payload()
    transport = _FakeTransport()
    transport.items = [_manifest()]
    controller, authorization, permit = _controller(tmp_path, transport, payload)

    with pytest.raises(DeploymentControlBlocked) as blocked:
        _provision(controller, authorization, permit)

    assert blocked.value.code == "preexisting_collision"
    assert transport.list_calls == 1
    assert transport.post_calls == 0
    assert transport.detail_calls == 0


def test_o5_lock_queue_crossing_expiry_rechecks_clock_next_to_post(
    tmp_path: Path,
) -> None:
    payload = _authorization_payload()
    observed = iter((NOW, payload.expires_at))
    transport = _FakeTransport()
    controller, authorization, permit = _controller(
        tmp_path,
        transport,
        payload,
        clock=lambda: next(observed),
    )

    with pytest.raises(DeploymentControlBlocked) as blocked:
        _provision(controller, authorization, permit)

    assert blocked.value.code == "provisioning_gate_rejected"
    assert transport.post_calls == 0


def test_o5_i2_prepared_journal_rechecks_expiry_before_initial_list(
    tmp_path: Path,
) -> None:
    payload = _authorization_payload()
    observed = iter((NOW, NOW, payload.expires_at))
    transport = _FakeTransport()
    controller, authorization, permit = _controller(
        tmp_path,
        transport,
        payload,
        clock=lambda: next(observed),
    )

    with pytest.raises(DeploymentControlBlocked) as blocked:
        _provision(controller, authorization, permit)

    assert blocked.value.code == "provisioning_gate_rejected"
    assert transport.list_calls == transport.post_calls == transport.detail_calls == 0


def test_o5_i2_prepared_journal_fsync_rechecks_expiry_immediately_before_post(
    tmp_path: Path,
) -> None:
    payload = _authorization_payload()
    observed = iter((NOW, NOW, NOW, NOW, payload.expires_at))
    transport = _FakeTransport()
    controller, authorization, permit = _controller(
        tmp_path,
        transport,
        payload,
        clock=lambda: next(observed),
    )

    with pytest.raises(DeploymentControlBlocked) as blocked:
        _provision(controller, authorization, permit)

    assert blocked.value.code == "provisioning_gate_rejected"
    assert transport.list_calls == 1
    assert transport.post_calls == transport.detail_calls == 0


def test_o5_i2_ambiguous_post_rechecks_expiry_before_reconciliation_list(
    tmp_path: Path,
) -> None:
    payload = _authorization_payload()
    observed = iter((NOW, NOW, NOW, NOW, NOW, payload.expires_at))
    transport = _FakeTransport()
    transport.create_mode = "timeout_without_accept"

    def timeout_without_accept(*, request_body: bytes, idempotency_key: str) -> bytes:
        del request_body, idempotency_key
        transport.post_calls += 1
        raise TimeoutError("provider result is ambiguous")

    transport.create_deployment = timeout_without_accept  # type: ignore[method-assign]
    controller, authorization, permit = _controller(
        tmp_path,
        transport,
        payload,
        clock=lambda: next(observed),
    )

    with pytest.raises(DeploymentControlBlocked) as blocked:
        _provision(controller, authorization, permit)

    assert blocked.value.code == "provisioning_gate_rejected"
    assert transport.list_calls == 1
    assert transport.post_calls == 1
    assert transport.detail_calls == 0


@pytest.mark.parametrize(
    ("expiry_after", "expected_detail_calls", "expected_journal_state"),
    [
        ("post", 0, "prepared"),
        ("first_detail", 1, "prepared"),
        ("second_detail", 2, "created"),
    ],
)
def test_o5_i1_provisioning_rechecks_full_freshness_after_every_provider_response(
    tmp_path: Path,
    expiry_after: str,
    expected_detail_calls: int,
    expected_journal_state: str,
) -> None:
    payload = _authorization_payload()
    current = [NOW]

    class _ExpiryAdvancingTransport(_FakeTransport):
        def create_deployment(self, *, request_body: bytes, idempotency_key: str) -> bytes:
            response = super().create_deployment(
                request_body=request_body,
                idempotency_key=idempotency_key,
            )
            if expiry_after == "post":
                current[0] = payload.expires_at
            return response

        def deployment_detail(self, *, deployed_model: str) -> bytes:
            response = super().deployment_detail(deployed_model=deployed_model)
            if expiry_after == "first_detail" and self.detail_calls == 1:
                current[0] = payload.expires_at
            if expiry_after == "second_detail" and self.detail_calls == 2:
                current[0] = payload.expires_at
            return response

    transport = _ExpiryAdvancingTransport()
    controller, authorization, permit = _controller(
        tmp_path,
        transport,
        payload,
        clock=lambda: current[0],
    )

    with pytest.raises(DeploymentControlBlocked) as blocked:
        _provision(controller, authorization, permit)

    assert blocked.value.code == "provisioning_gate_rejected"
    assert transport.list_calls == 1
    assert transport.post_calls == 1
    assert transport.detail_calls == expected_detail_calls
    root = controller._store.root
    assert list(root.glob("*.receipt.json")) == []
    assert list(root.glob("*.receipt-reconciliation.json")) == []
    journal = json.loads(next(root.glob("*.journal.json")).read_bytes())
    assert journal["state"] == expected_journal_state
    assert journal["send_started"] is True
    controller.close()


@pytest.mark.parametrize("terminal_drift", ["clock", "reserve"])
def test_o5_i1_terminal_journal_drift_blocks_before_receipt_capability_mint_and_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal_drift: str,
) -> None:
    payload = _authorization_payload()
    current = [NOW]
    transport = _FakeTransport()
    controller, authorization, permit = _controller(
        tmp_path,
        transport,
        payload,
        clock=lambda: current[0],
    )
    original_write = controller._write_journal
    original_issuer = _testing_receipt_issuer()
    mint_calls = 0
    drift_once = True

    def observe_mint(**values: object) -> Any:
        nonlocal mint_calls
        mint_calls += 1
        return original_issuer(**values)

    def drift_after_terminal_write(name: str, journal: Any) -> None:
        nonlocal drift_once
        original_write(name, journal)
        if journal.state != "receipted" or not drift_once:
            return
        drift_once = False
        if terminal_drift == "clock":
            current[0] = payload.expires_at
        else:
            reader = cast(Any, controller._reserve_reader)
            reader.reserve = permit.reserve.model_copy(update={"purpose": "drifted-purpose"})

    monkeypatch.setattr(
        admission_deployment,
        "_issue_verified_reconciled_receipt_for_testing",
        observe_mint,
    )
    monkeypatch.setattr(controller, "_write_journal", drift_after_terminal_write)

    with pytest.raises(DeploymentControlBlocked) as blocked:
        _provision(controller, authorization, permit)

    assert blocked.value.code in {"provisioning_gate_rejected", "durable_reserve_mismatch"}
    assert mint_calls == 0
    journal = json.loads(next(controller._store.root.glob("*.journal.json")).read_bytes())
    assert journal["state"] == "receipted"
    assert transport.post_calls == 1

    current[0] = NOW
    cast(Any, controller._reserve_reader).reserve = permit.reserve
    recovered = _provision(controller, authorization, permit)

    assert recovered.receipt_capability.receipt == recovered.receipt
    assert mint_calls == 1
    assert transport.post_calls == 1
    controller.close()


def test_o5_tampered_created_journal_without_send_started_never_posts(
    tmp_path: Path,
) -> None:
    payload = _authorization_payload()
    transport = _FakeTransport()
    controller, authorization, permit = _controller(tmp_path, transport, payload)
    first = _provision(controller, authorization, permit)
    journal = json.loads(first.journal_path.read_bytes())
    journal.update(
        {
            "state": "created",
            "history": ["authorized", "reserved", "prepared", "created"],
            "send_started": False,
            "receipt_digest": None,
        }
    )
    first.journal_path.write_bytes(
        json.dumps(journal, sort_keys=True, separators=(",", ":")).encode()
    )
    transport.items.clear()

    with pytest.raises(DeploymentControlBlocked) as blocked:
        _provision(controller, authorization, permit)

    assert blocked.value.code == "operation_journal_invalid"
    assert transport.post_calls == 1


def test_o5_remote_detail_mismatch_never_installs_receipt(tmp_path: Path) -> None:
    payload = _authorization_payload()
    transport = _FakeTransport()
    transport.detail_override = json.dumps(
        _manifest(workspace_ref="foreign-workspace"), separators=(",", ":")
    ).encode()
    controller, authorization, permit = _controller(tmp_path, transport, payload)

    with pytest.raises(DeploymentControlBlocked, match="manifest"):
        _provision(controller, authorization, permit)

    assert transport.post_calls == 1
    assert list((tmp_path / "deployment-control").glob("*.receipt.json")) == []


@pytest.mark.parametrize(
    "detail",
    [
        b"not-json",
        json.dumps(
            _manifest(workspace_ref="foreign-workspace"),
            separators=(",", ":"),
        ).encode(),
    ],
)
def test_o5_o6_provider_detail_failure_or_drift_mints_no_receipt_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    detail: bytes,
) -> None:
    payload = _authorization_payload()
    transport = _FakeTransport()
    transport.detail_override = detail
    controller, authorization, permit = _controller(tmp_path, transport, payload)
    original_issuer = _testing_receipt_issuer()
    mint_calls = 0

    def observe_mint(**values: object) -> Any:
        nonlocal mint_calls
        mint_calls += 1
        return original_issuer(**values)

    monkeypatch.setattr(
        admission_deployment,
        "_issue_verified_reconciled_receipt_for_testing",
        observe_mint,
    )

    with pytest.raises(DeploymentControlBlocked):
        _provision(controller, authorization, permit)

    root = tmp_path / "deployment-control"
    assert mint_calls == 0
    assert list(root.glob("*.receipt.json")) == []
    assert list(root.glob("*.receipt-reconciliation.json")) == []


@pytest.mark.parametrize(
    "body",
    [b"not-json", b"{" + b"x" * (1024 * 1024) + b"}"],
)
def test_o5_malformed_or_oversized_list_fails_closed_before_post(
    tmp_path: Path,
    body: bytes,
) -> None:
    payload = _authorization_payload()
    transport = _FakeTransport()
    transport.list_body_override = body
    controller, authorization, permit = _controller(tmp_path, transport, payload)

    with pytest.raises(DeploymentControlBlocked, match="response"):
        _provision(controller, authorization, permit)

    assert transport.post_calls == 0


def test_o5_production_http_transport_ignores_hostile_proxy_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _production_reserve_with_sidecar(tmp_path, monkeypatch)
    provider_cap = fixture.ledger.require_fresh_infrastructure_provider_capability(
        plan=fixture.plan,
        expected_scope=fixture.payload.scope,
        reserve_id=fixture.permit.reserve.reserve_id,
    )
    captured: dict[str, object] = {}

    class _Client:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def close(self) -> None:
            pass

    monkeypatch.setenv("HTTP_PROXY", "http://attacker.invalid:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://attacker.invalid:8080")
    monkeypatch.setenv("ALL_PROXY", "socks5://attacker.invalid:1080")
    monkeypatch.setattr(httpx, "Client", _Client)

    transport = BailianDeploymentHTTPTransport._for_production(
        api_key=_PRODUCTION_API_KEY,
        provider_capability=provider_cap,
    )
    transport.close()

    assert captured["trust_env"] is False
    assert captured["base_url"] == BAILIAN_DEPLOYMENT_ENDPOINT
    assert os.environ["ALL_PROXY"].startswith("socks5://")


def test_o5_real_httpx_timeout_then_zero_reconcile_never_posts_twice(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, stream=httpx.ByteStream(b'{"items":[]}'))
        raise httpx.ReadTimeout("lost", request=request)

    transport = BailianDeploymentHTTPTransport._for_testing(
        api_key="x",
        identity=_transport_identity_for_key("x"),
        transport=httpx.MockTransport(handler),
    )
    payload = _authorization_payload(credential_ref=credential_ref_for_api_key("x"))
    controller, authorization, permit = _controller(tmp_path, transport, payload)

    with pytest.raises(DeploymentControlBlocked) as first:
        _provision(controller, authorization, permit)
    with pytest.raises(DeploymentControlBlocked) as second:
        _provision(controller, authorization, permit)

    assert first.value.code == second.value.code == "provider_outcome_uncertain"
    assert calls.count("POST") == 1
    transport.close()


def test_o5_i4_b_transport_rejects_delete_before_network() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, stream=httpx.ByteStream(b"{}"))

    transport = BailianDeploymentHTTPTransport._for_testing(
        api_key="x",
        identity=_transport_identity_for_key("x"),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(DeploymentTransportError, match="method|DELETE"):
        transport._request_bounded(
            cast(Any, "DELETE"),
            BAILIAN_DEPLOYMENT_ENDPOINT,
            accepted_statuses=frozenset({200}),
        )

    assert calls == []
    transport.close()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            stream=httpx.ByteStream(b"not-gzip"),
        ),
        httpx.Response(
            200,
            stream=httpx.ByteStream(b"x" * (256 * 1024 + 1)),
        ),
    ],
)
def test_o5_real_httpx_stream_rejects_compressed_or_oversized_body(
    response: httpx.Response,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return response

    transport = BailianDeploymentHTTPTransport._for_testing(
        api_key="x",
        identity=_transport_identity_for_key("x"),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(DeploymentTransportError, match="compressed|size"):
        transport.list_deployments(marker="ikb031-" + "0" * 24, suffix="031-" + "0" * 16)
    transport.close()
