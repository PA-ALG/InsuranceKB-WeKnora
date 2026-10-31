"""Local-live provisioning: probes and attestations precede mutation; in-memory API key."""

from __future__ import annotations

from dataclasses import replace
from importlib import import_module
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import SecretStr

from tests.service_shell.local_provisioning.helpers import FakeBackend, _plan, _provision_module


class AttestingBackend(FakeBackend):
    def __init__(self, *, fail_at: str | None = None) -> None:
        super().__init__()
        self.events: list[str] = []
        self.fail_at = fail_at

    async def list_resources(self, kind: str) -> list[Any]:
        self.events.append(f"ensure:{kind}")
        return await super().list_resources(kind)

    async def create_resource(self, desired: Any) -> Any:
        if desired.kind.startswith("kb:"):
            self.events.append(f"mutate:{desired.kind}")
        return await super().create_resource(desired)

    async def attest_models(
        self,
        models: dict[str, Any],
        embedding_dimension: int,
    ) -> None:
        assert tuple(models) == ("chat", "embedding", "rerank", "vlm")
        assert embedding_dimension == 3
        for role in models:
            event = f"refresh:{role}"
            self.events.append(event)
            if self.fail_at == event:
                raise RuntimeError("sanitized model attestation failure")
        for role in ("chat", "embedding", "rerank"):
            event = f"debug:{role}"
            self.events.append(event)
            if self.fail_at == event:
                raise RuntimeError("sanitized model attestation failure")

    async def upload_pdf(
        self,
        kb_id: str,
        path: Path,
        digest: str,
        marker: str,
    ) -> Any:
        self.events.append("mutate:knowledge")
        return await super().upload_pdf(kb_id, path, digest, marker)


async def test_r3_3_five_probes_precede_four_model_attestations_and_kb_mutation(
    tmp_path: Path,
) -> None:
    local = import_module("insurance_harness.live_env.local_provisioning")
    provision = _provision_module()
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(b"life insurance PDF")
    events: list[str] = []
    backend = AttestingBackend()
    backend.events = events

    async def prober(configuration: object) -> dict[str, object]:
        del configuration
        for role in ("chat", "embedding", "rerank", "vlm", "extraction"):
            events.append(f"probe:{role}")
        return {"weknora_embedding": type("Probe", (), {"embedding_dimension": 3})()}

    class Operation:
        async def provision(
            self,
            configuration: object,
            runtime: Path,
            source_pdf: Path,
            embedding_dimension: int,
        ) -> dict[str, str]:
            del configuration, runtime
            result = await provision.provision_local_live(
                backend,
                replace(
                    _plan(source_pdf),
                    embedding_dimension=embedding_dimension,
                ),
            )
            return {"LOCAL_LIVE_VLLM_MODEL_ID": result.vlm_model_id}

    collaborator = local.ProvisionCollaborator(
        config=cast(Any, object()),
        runtime_path=tmp_path / ".env.local-live.runtime",
        prober=prober,
        operation=Operation(),
    )
    state = await collaborator._provision(pdf)

    assert state == {"LOCAL_LIVE_VLLM_MODEL_ID": "model:vlm-5"}
    assert events[:5] == [
        "probe:chat",
        "probe:embedding",
        "probe:rerank",
        "probe:vlm",
        "probe:extraction",
    ]
    assert events[5:10] == [
        "ensure:tenant",
        "ensure:model:chat",
        "ensure:model:embedding",
        "ensure:model:rerank",
        "ensure:model:vlm",
    ]
    assert events[10:17] == [
        "refresh:chat",
        "refresh:embedding",
        "refresh:rerank",
        "refresh:vlm",
        "debug:chat",
        "debug:embedding",
        "debug:rerank",
    ]
    assert events[17] == "ensure:kb:raw"
    assert events.index("mutate:knowledge") > events.index("debug:rerank")


@pytest.mark.parametrize(
    "failure_event",
    (
        "refresh:chat",
        "refresh:embedding",
        "refresh:rerank",
        "refresh:vlm",
        "debug:chat",
        "debug:embedding",
        "debug:rerank",
    ),
)
async def test_r3_3_model_attestation_failure_prevents_kb_and_knowledge_mutation(
    tmp_path: Path,
    failure_event: str,
) -> None:
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(b"life insurance PDF")
    backend = AttestingBackend(fail_at=failure_event)

    with pytest.raises(RuntimeError, match="sanitized model attestation failure"):
        await _provision_module().provision_local_live(backend, _plan(pdf))

    assert not any(event.startswith("ensure:kb:") for event in backend.events)
    assert not any(event.startswith("mutate:") for event in backend.events)


async def test_r3_3_runtime_api_key_is_resolved_in_memory_by_exact_resource_identity(
    tmp_path: Path,
) -> None:
    local = import_module("insurance_harness.live_env.local_provisioning")
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    calls: list[str] = []
    runtime = {
        "WEKNORA_ADMIN_USERNAME": "admin",
        "WEKNORA_ADMIN_EMAIL": "admin@example.invalid",
        "WEKNORA_ADMIN_PASSWORD": "admin-password-secret",
        "LOCAL_LIVE_TENANT_ID": "7",
        "LOCAL_LIVE_API_KEY_ID": "42",
        "LOCAL_LIVE_RAW_KB_ID": "raw-kb",
        "LOCAL_LIVE_WIKI_KB_ID": "wiki-kb",
    }
    session = admin.AdminSession(
        user_id="user-1",
        tenant_id=1,
        token=SecretStr("admin-jwt"),
        refresh_token=SecretStr("admin-refresh"),
    )
    tenant_session = replace(session, tenant_id=7)

    class Client:
        async def bootstrap_admin(self, credentials: object) -> object:
            calls.append("bootstrap")
            return session

        async def switch_tenant(self, current: object, tenant_id: int) -> object:
            calls.append(f"switch:{tenant_id}")
            return tenant_session

        async def list_tenant_api_keys(
            self,
            current: object,
            *,
            tenant_id: int,
        ) -> list[object]:
            calls.append(f"keys:{tenant_id}")
            return [
                admin.TenantAPIKey(
                    id=42,
                    tenant_id=7,
                    name="insurancekb-live-contributor::owner=insurancekb-local-live-v1",
                    role="contributor",
                    full_access=False,
                    knowledge_base_ids=("raw-kb", "wiki-kb"),
                    capabilities=("retrieve", "ingest"),
                    token=SecretStr("resolved-tenant-secret"),
                )
            ]

        async def aclose(self) -> None:
            calls.append("close")

    resolver = local.RuntimeAPIKeyResolver(
        runtime_path=tmp_path / ".env.local-live.runtime",
        runtime_loader=lambda path: runtime,
        client_factory=lambda url: cast(Any, Client()),
    )

    key = await resolver.resolve()

    assert key.get_secret_value() == "resolved-tenant-secret"
    assert calls == ["bootstrap", "switch:7", "keys:7", "close"]
    assert "resolved-tenant-secret" not in repr(resolver)
