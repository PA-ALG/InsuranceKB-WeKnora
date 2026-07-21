from __future__ import annotations

import base64
import json
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.goldenset.admission_budget import (
    BudgetAmounts,
    InfrastructureCleanupBinding,
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
    DeploymentTransportError,
    deterministic_deployment_suffix,
    deterministic_operation_marker,
)
from insurance_harness.goldenset.admission_infrastructure import (
    PROVISIONING_AUTHORIZATION_DOMAIN,
    ProvisioningAuthorization,
    ProvisioningAuthorizationPayload,
    authorization_signed_bytes,
)
from insurance_harness.goldenset.admission_models import TrustedKeyPolicy

NOW = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
STRONG_BASE = "qwen3.7-plus-2026-05-26"


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
    signature = key.sign(
        authorization_signed_bytes(PROVISIONING_AUTHORIZATION_DOMAIN, payload)
    )
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

    def infrastructure_cleanup_binding(
        self, reserve_id: str
    ) -> InfrastructureCleanupBinding:
        raise RuntimeError(f"cleanup binding unavailable for {reserve_id}")


class _FakeTransport:
    endpoint = BAILIAN_DEPLOYMENT_ENDPOINT

    def __init__(self) -> None:
        self.post_calls = 0
        self.list_calls = 0
        self.detail_calls = 0
        self.items: list[dict[str, object]] = []
        self.create_mode = "ok"
        self.list_body_override: bytes | None = None
        self.detail_override: bytes | None = None

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
        self.detail_calls += 1
        if self.detail_override is not None:
            return self.detail_override
        match = next(
            item for item in self.items if item["deployed_model"] == deployed_model
        )
        return json.dumps(match, separators=(",", ":")).encode()


def _manifest(
    *,
    base_model: str = STRONG_BASE,
    workspace_ref: str = "workspace-cn-beijing-031",
    operation_marker: str | None = None,
    deployment_suffix: str | None = None,
    deployed_model: str | None = None,
    status: str = "RUNNING",
    **extra: object,
) -> dict[str, object]:
    marker = operation_marker or deterministic_operation_marker(
        "golden-v01-run-031", "op-strong-031"
    )
    suffix = deployment_suffix or deterministic_deployment_suffix(
        "golden-v01-run-031", "op-strong-031"
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
        "operation_marker": marker,
        "deployment_suffix": suffix,
    }
    value.update(extra)
    return value


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
    return controller.provision(
        authorization=authorization,
        permit=permit,
        trusted_authorities=_policy(key),
    )


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
        update={
            "reserve": permit.reserve.model_copy(
                update={"authorization_digest": "0" * 64}
            )
        }
    )
    with pytest.raises(DeploymentControlBlocked, match="reserve|permit"):
        _provision(controller, authorization, forged)
    assert transport.list_calls == transport.post_calls == 0


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


def test_o5_marker_collision_or_foreign_manifest_blocks_without_post(tmp_path: Path) -> None:
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
) -> None:
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    transport = BailianDeploymentHTTPTransport(api_key="test-only-not-a-real-key")
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
        transport=httpx.MockTransport(handler),
    )
    payload = _authorization_payload()
    controller, authorization, permit = _controller(tmp_path, transport, payload)

    with pytest.raises(DeploymentControlBlocked) as first:
        _provision(controller, authorization, permit)
    with pytest.raises(DeploymentControlBlocked) as second:
        _provision(controller, authorization, permit)

    assert first.value.code == second.value.code == "provider_outcome_uncertain"
    assert calls.count("POST") == 1
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
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(DeploymentTransportError, match="compressed|size"):
        transport.list_deployments(marker="ikb031-" + "0" * 24, suffix="031-" + "0" * 16)
    transport.close()
