"""Local-live provisioning: scoped tenant keys and exact reuse of owned embeddings."""

from __future__ import annotations

import json
from importlib import import_module

import httpx
import pytest
import respx
from pydantic import SecretStr

from tests.service_shell.local_provisioning.helpers import _provision_module


@respx.mock
async def test_r3_1_created_tenant_switch_mints_scoped_contributor_key() -> None:
    module = import_module("insurance_harness.adapters.weknora.admin_client")
    client = module.WeKnoraAdminClient("https://weknora.example/api/v1")
    session = module.AdminSession(
        user_id="user-1",
        tenant_id=1,
        token=SecretStr("old-jwt"),
        refresh_token=SecretStr("refresh-secret"),
    )
    switched_route = respx.post(
        "https://weknora.example/api/v1/auth/switch-tenant"
    ).respond(
        json={
            "success": True,
            "user": {"id": "user-1"},
            "active_tenant": {"id": 7, "name": "local", "role": "owner"},
            "memberships": [{"tenant_id": 7, "role": "owner", "status": "active"}],
            "token": "tenant-jwt",
            "refresh_token": "tenant-refresh",
        }
    )
    key_route = respx.post(
        "https://weknora.example/api/v1/tenants/7/api-keys"
    ).respond(
        status_code=201,
        json={
            "success": True,
            "data": {
                "id": 42,
                "name": "insurancekb-live-contributor",
                "api_key": "sk-encrypted-display",
                "full_access": False,
                "knowledge_base_ids": ["kb-raw", "kb-wiki"],
                "capabilities": ["retrieve", "ingest"],
                "token": "sk-live-token",
                "created_at": "2026-07-15T00:00:00Z",
            },
        },
    )
    list_route = respx.get(
        "https://weknora.example/api/v1/tenants/7/api-keys"
    ).respond(
        json={
            "success": True,
            "data": [
                {
                    "id": 42,
                    "name": "insurancekb-live-contributor",
                    "api_key": "sk-live-token",
                    "full_access": False,
                    "knowledge_base_ids": ["kb-raw", "kb-wiki"],
                    "capabilities": ["retrieve", "ingest"],
                }
            ],
        }
    )
    try:
        switched = await client.switch_tenant(session, 7)
        key = await client.create_tenant_api_key(
            switched,
            tenant_id=7,
            name="insurancekb-live-contributor",
            knowledge_base_ids=("kb-raw", "kb-wiki"),
        )
        listed = await client.list_tenant_api_keys(switched, tenant_id=7)
    finally:
        await client.aclose()

    assert switched.tenant_id == 7
    assert switched.token.get_secret_value() == "tenant-jwt"
    assert key.id == 42
    assert key.role == "contributor"
    assert key.capabilities == ("retrieve", "ingest")
    assert key.knowledge_base_ids == ("kb-raw", "kb-wiki")
    assert key.token.get_secret_value() == "sk-live-token"
    assert "sk-live-token" not in repr(key)
    assert listed == [key]
    assert json.loads(switched_route.calls[0].request.content) == {
        "tenant_id": 7,
        "refresh_token": "refresh-secret",
    }
    assert key_route.calls[0].request.headers["authorization"] == "Bearer tenant-jwt"
    assert list_route.calls[0].request.headers["authorization"] == "Bearer tenant-jwt"
    assert json.loads(key_route.calls[0].request.content) == {
        "name": "insurancekb-live-contributor",
        "full_access": False,
        "knowledge_base_ids": ["kb-raw", "kb-wiki"],
        "capabilities": ["retrieve", "ingest"],
    }


@respx.mock
async def test_r3_1_scoped_api_key_404_fails_closed_without_legacy_fallback() -> None:
    module = import_module("insurance_harness.adapters.weknora.admin_client")
    client = module.WeKnoraAdminClient("https://weknora.example/api/v1")
    session = module.AdminSession(
        user_id="user-1",
        tenant_id=7,
        token=SecretStr("tenant-jwt"),
        refresh_token=SecretStr("tenant-refresh"),
    )
    scoped_route = respx.get(
        "https://weknora.example/api/v1/tenants/7/api-keys"
    ).respond(status_code=404, json={"success": False})
    try:
        with pytest.raises(httpx.HTTPStatusError) as failure:
            await client.list_tenant_api_keys(session, tenant_id=7)
    finally:
        await client.aclose()

    assert failure.value.response.status_code == 404
    assert scoped_route.call_count == 1
    assert len(respx.calls) == 1


@respx.mock
async def test_r5_2_admin_client_revokes_scoped_tenant_key() -> None:
    module = import_module("insurance_harness.adapters.weknora.admin_client")
    client = module.WeKnoraAdminClient("https://weknora.example/api/v1")
    session = module.AdminSession(
        user_id="user-1",
        tenant_id=7,
        token=SecretStr("tenant-jwt"),
        refresh_token=SecretStr("tenant-refresh"),
    )
    route = respx.delete(
        "https://weknora.example/api/v1/tenants/7/api-keys/42"
    ).respond(json={"success": True})
    try:
        await client.delete_tenant_api_key(session, tenant_id=7, key_id=42)
    finally:
        await client.aclose()

    assert route.calls[0].request.headers["authorization"] == "Bearer tenant-jwt"


@respx.mock
async def test_r3_1_real_backend_maps_confirmed_tenant_ownership_description() -> None:
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    client = admin.WeKnoraAdminClient("https://weknora.example/api/v1")
    session = admin.AdminSession(
        user_id="user-1",
        tenant_id=1,
        token=SecretStr("jwt"),
        refresh_token=SecretStr("refresh"),
    )
    respx.get("https://weknora.example/api/v1/tenants").respond(
        json={
            "success": True,
            "data": {
                "items": [
                    {
                        "id": 7,
                        "name": "insurancekb-local-live",
                        "description": (
                            '{"dimension":null,"marker":"insurancekb-local-live-v1",'
                            '"role":"tenant"}'
                        ),
                    }
                ]
            },
        }
    )
    backend = admin.WeKnoraProvisioningBackend(
        client,
        session,
        model_payloads={},
        knowledge_base_payloads={},
    )
    try:
        resources = await backend.list_resources("tenant")
    finally:
        await client.aclose()

    assert resources == [
        _provision_module().OwnedResource(
            id="7",
            kind="tenant",
            name="insurancekb-local-live",
            tenant_id="",
            marker="insurancekb-local-live-v1",
            role="tenant",
        )
    ]


@respx.mock
async def test_r3_1_real_backend_selects_exact_reused_embedding_and_key() -> None:
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    provision = _provision_module()
    client = admin.WeKnoraAdminClient("https://weknora.example/api/v1")
    session = admin.AdminSession(
        user_id="user-1",
        tenant_id=7,
        token=SecretStr("jwt"),
        refresh_token=SecretStr("refresh"),
    )
    ownership = (
        '{"dimension":3,"marker":"insurancekb-local-live-v1",'
        '"role":"embedding"}'
    )
    respx.get("https://weknora.example/api/v1/models").respond(
        json={
            "success": True,
            "data": [
                {
                    "id": "builtin-local",
                    "name": "local-builtin-embedding",
                    "tenant_id": 7,
                    "description": ownership.replace(
                        "insurancekb-local-live-v1", "another-environment"
                    ),
                },
                {
                    "id": "invalid-remote",
                    "name": "other-remote-embedding",
                    "tenant_id": 7,
                    "type": "Embedding",
                    "parameters": {
                        "base_url": "https://models.example/v1/../private",
                        "provider": "aliyun",
                    },
                    "description": ownership.replace(
                        "insurancekb-local-live-v1", "another-environment"
                    ),
                },
                {
                    "id": "embedding-owned",
                    "name": "Qwen3-VL-Embedding-8B",
                    "tenant_id": 7,
                    "type": "Embedding",
                    "parameters": {
                        "base_url": "https://models.example/v1",
                        "provider": "aliyun",
                        "supports_vision": False,
                    },
                    "description": ownership,
                },
            ],
        }
    )
    kb_create = respx.post(
        "https://weknora.example/api/v1/knowledge-bases"
    ).respond(
        status_code=201,
        json={
            "success": True,
            "data": {
                "id": "kb-raw",
                "name": "KB-RAW",
                "tenant_id": 7,
                "embedding_model_id": "embedding-owned",
                "vlm_config": {"enabled": False, "model_id": ""},
                "description": (
                    '{"dimension":3,"marker":"insurancekb-local-live-v1",'
                    '"role":"raw"}'
                ),
            },
        },
    )
    respx.get("https://weknora.example/api/v1/tenants/7/api-keys").respond(
        json={
            "success": True,
            "data": [
                {
                    "id": 1,
                    "name": "other::owner=another-environment",
                    "api_key": "wrong-key",
                    "full_access": False,
                    "knowledge_base_ids": ["other-kb"],
                    "capabilities": ["retrieve", "ingest"],
                },
                {
                    "id": 2,
                    "name": (
                        "insurancekb-live-contributor::owner="
                        "insurancekb-local-live-v1"
                    ),
                    "api_key": "owned-key",
                    "full_access": False,
                    "knowledge_base_ids": ["kb-raw", "kb-wiki"],
                    "capabilities": ["retrieve", "ingest"],
                },
            ],
        }
    )
    wiki_pages = respx.get(
        "https://weknora.example/api/v1/knowledgebase/kb-wiki/wiki/pages"
    ).respond(json={"success": True, "data": {"items": []}})
    backend = admin.WeKnoraProvisioningBackend(
        client,
        session,
        model_payloads={},
        knowledge_base_payloads={"raw": {"type": "document"}},
    )
    try:
        embeddings = await backend.list_resources("model:embedding")
        incomplete = [item for item in embeddings if item.id != "embedding-owned"]
        assert len(incomplete) == 2
        assert all(item.model_type is None for item in incomplete)
        assert all(item.endpoint_fingerprint is None for item in incomplete)
        embedding = next(item for item in embeddings if item.id == "embedding-owned")
        await backend.select_resource(embedding)
        await backend.create_resource(
            provision.DesiredResource(
                kind="kb:raw",
                name="KB-RAW",
                tenant_id="7",
                marker="insurancekb-local-live-v1",
                role="raw",
                dimension=3,
                embedding_model_id="embedding-owned",
                vlm_enabled=False,
                vlm_model_id="",
            )
        )
        keys = await backend.list_resources("api-key")
        key = next(item for item in keys if item.id == "2")
        await backend.select_resource(key)
        assert backend.live_api_key().get_secret_value() == "owned-key"
        assert await backend.list_wiki_pages("kb-wiki") == []
    finally:
        await client.aclose()

    assert json.loads(kb_create.calls[0].request.content)["embedding_model_id"] == (
        "embedding-owned"
    )
    assert wiki_pages.calls[0].request.headers["x-api-key"] == "owned-key"
