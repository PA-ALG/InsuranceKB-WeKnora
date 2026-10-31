"""Local-live provisioning: admin bootstrap, login, recorded tenants and documented routes."""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import SecretStr


@respx.mock
async def test_r3_1_admin_client_bootstraps_first_user_then_authenticates() -> None:
    try:
        module = import_module("insurance_harness.adapters.weknora.admin_client")
    except ModuleNotFoundError:
        pytest.fail("R3.1 WeKnora admin adapter is missing")
    register = respx.post("https://weknora.example/api/v1/auth/register").respond(
        status_code=201,
        json={"success": True, "user": {"id": "user-1", "tenant_id": 1}},
    )
    login = respx.post("https://weknora.example/api/v1/auth/login").respond(
        json={
            "success": True,
            "user": {"id": "user-1"},
            "active_tenant": {"id": 1, "name": "admin workspace"},
            "token": "jwt-secret",
            "refresh_token": "refresh-secret",
        }
    )
    client = module.WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        session = await client.bootstrap_admin(
            module.AdminCredentials("admin", "admin@example.com", "password-123")
        )
    finally:
        await client.aclose()

    assert session.user_id == "user-1"
    assert session.tenant_id == 1
    assert register.call_count == login.call_count == 1
    assert "secret" not in repr(session)


@respx.mock
async def test_r3_1_admin_client_authenticates_after_existing_email_bad_request() -> None:
    module = import_module("insurance_harness.adapters.weknora.admin_client")
    register = respx.post("https://weknora.example/api/v1/auth/register").respond(
        status_code=400,
        json={
            "success": False,
            "error": {
                "code": 1000,
                "message": "user with this email already exists",
            },
        },
    )
    login = respx.post("https://weknora.example/api/v1/auth/login").respond(
        json={
            "success": True,
            "user": {"id": "user-1"},
            "active_tenant": {"id": 1, "name": "admin workspace"},
            "token": "jwt-secret",
            "refresh_token": "refresh-secret",
        }
    )
    client = module.WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        session = await client.bootstrap_admin(
            module.AdminCredentials("admin", "admin@example.com", "password-123")
        )
    finally:
        await client.aclose()

    assert session.user_id == "user-1"
    assert session.tenant_id == 1
    assert register.call_count == login.call_count == 1


@respx.mock
async def test_r3_1_registration_bad_request_still_requires_valid_login() -> None:
    module = import_module("insurance_harness.adapters.weknora.admin_client")
    register = respx.post("https://weknora.example/api/v1/auth/register").respond(
        status_code=400,
        json={"success": False, "error": {"message": "invalid registration"}},
    )
    login = respx.post("https://weknora.example/api/v1/auth/login").respond(
        status_code=401,
        json={"success": False, "error": {"message": "invalid credentials"}},
    )
    client = module.WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        with pytest.raises(httpx.HTTPStatusError, match="401 Unauthorized"):
            await client.bootstrap_admin(
                module.AdminCredentials("admin", "admin@example.com", "wrong-password")
            )
    finally:
        await client.aclose()

    assert register.call_count == login.call_count == 1


@respx.mock
async def test_r3_1_admin_client_accepts_wiki_pages_pagination() -> None:
    module = import_module("insurance_harness.adapters.weknora.admin_client")
    route = respx.get(
        "https://weknora.example/api/v1/knowledgebase/kb-wiki/wiki/pages"
    ).respond(
        json={
            "pages": [{"id": "page-1", "slug": "policy"}],
            "total": 1,
            "page": 1,
            "page_size": 100,
            "total_pages": 1,
        }
    )
    client = module.WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        pages = await client.list_wiki_pages(SecretStr("tenant-key"), "kb-wiki")
    finally:
        await client.aclose()

    assert pages == [{"id": "page-1", "slug": "policy"}]
    assert route.call_count == 1


@respx.mock
async def test_r3_1_repeated_provision_restores_recorded_tenant_before_discovery() -> None:
    provision = import_module("insurance_harness.live_env.local_provisioning")
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    client = admin.WeKnoraAdminClient("https://weknora.example/api/v1")
    session = admin.AdminSession(
        user_id="user-1",
        tenant_id=1,
        token=SecretStr("initial-jwt"),
        refresh_token=SecretStr("initial-refresh"),
    )
    switch = respx.post(
        "https://weknora.example/api/v1/auth/switch-tenant"
    ).respond(
        json={
            "success": True,
            "user": {"id": "user-1"},
            "active_tenant": {"id": 7, "name": "insurancekb-local-live"},
            "token": "tenant-jwt",
            "refresh_token": "tenant-refresh",
        }
    )
    try:
        restored = await provision._restore_runtime_tenant(
            client,
            session,
            {"LOCAL_LIVE_TENANT_ID": "7"},
        )
    finally:
        await client.aclose()

    assert restored.tenant_id == 7
    assert json.loads(switch.calls[0].request.content) == {
        "tenant_id": 7,
        "refresh_token": "initial-refresh",
    }


async def test_r3_1_repeated_provision_rejects_invalid_recorded_tenant() -> None:
    provision = import_module("insurance_harness.live_env.local_provisioning")
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    client = admin.WeKnoraAdminClient("https://weknora.example/api/v1")
    session = admin.AdminSession(
        user_id="user-1",
        tenant_id=1,
        token=SecretStr("initial-jwt"),
        refresh_token=SecretStr("initial-refresh"),
    )
    try:
        with pytest.raises(ValueError, match="LOCAL_LIVE_TENANT_ID"):
            await provision._restore_runtime_tenant(
                client,
                session,
                {"LOCAL_LIVE_TENANT_ID": "not-an-integer"},
            )
    finally:
        await client.aclose()


@respx.mock
async def test_r3_1_admin_client_uses_only_documented_resource_routes(
    tmp_path: Path,
) -> None:
    module = import_module("insurance_harness.adapters.weknora.admin_client")
    client = module.WeKnoraAdminClient("https://weknora.example/api/v1")
    session = module.AdminSession(
        user_id="user-1",
        tenant_id=1,
        token=SecretStr("jwt-secret"),
        refresh_token=SecretStr("refresh-secret"),
    )
    api_key = SecretStr("tenant-secret")
    tenant_list = respx.get("https://weknora.example/api/v1/tenants").respond(
        json={"success": True, "data": {"items": [{"id": 7, "name": "local"}]}}
    )
    tenant_create = respx.post("https://weknora.example/api/v1/tenants").respond(
        status_code=201,
        json={"success": True, "data": {"id": 7, "name": "local"}},
    )
    models = respx.get("https://weknora.example/api/v1/models").respond(
        json={"success": True, "data": []}
    )
    model_create = respx.post("https://weknora.example/api/v1/models").respond(
        status_code=201,
        json={"success": True, "data": {"id": "model-1"}},
    )
    kbs = respx.get("https://weknora.example/api/v1/knowledge-bases").respond(
        json={"success": True, "data": []}
    )
    kb_create = respx.post("https://weknora.example/api/v1/knowledge-bases").respond(
        status_code=201,
        json={"success": True, "data": {"id": "kb-raw"}},
    )
    knowledge = respx.get(
        "https://weknora.example/api/v1/knowledge-bases/kb-raw/knowledge"
    ).respond(json={"success": True, "data": []})
    upload = respx.post(
        "https://weknora.example/api/v1/knowledge-bases/kb-raw/knowledge/file"
    ).respond(
        status_code=201,
        json={"success": True, "data": {"id": "knowledge-1", "parse_status": "processing"}},
    )
    chunks = respx.get("https://weknora.example/api/v1/chunks/knowledge-1").respond(
        json={"success": True, "data": [{"id": "chunk-1"}]}
    )
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(b"pdf")
    model_payload = {
        "name": "Qwen3-VL-Embedding-8B",
        "type": "Embedding",
        "source": "remote",
        "description": "insurancekb-local-live-v1:model:embedding",
        "parameters": {"embedding_parameters": {"dimension": 3}},
    }
    try:
        assert await client.list_tenants(session) == [{"id": 7, "name": "local"}]
        assert (await client.create_tenant(session, {"name": "local"}))["id"] == 7
        assert await client.list_models(api_key) == []
        assert (await client.create_model(api_key, model_payload))["id"] == "model-1"
        assert await client.list_knowledge_bases(api_key) == []
        assert (await client.create_knowledge_base(api_key, {"name": "KB-RAW"}))["id"] == (
            "kb-raw"
        )
        assert await client.list_knowledge(api_key, "kb-raw") == []
        assert (
            await client.upload_file(
                api_key,
                "kb-raw",
                pdf,
                metadata={"sha256": "abc", "owner": "insurancekb-local-live-v1"},
            )
        )["id"] == "knowledge-1"
        assert await client.list_chunks(api_key, "knowledge-1") == [{"id": "chunk-1"}]
    finally:
        await client.aclose()

    assert tenant_list.calls[0].request.headers["authorization"] == "Bearer jwt-secret"
    assert tenant_create.calls[0].request.headers["authorization"] == "Bearer jwt-secret"
    for route in (models, model_create, kbs, kb_create, knowledge, upload, chunks):
        assert route.calls[0].request.headers["x-api-key"] == "tenant-secret"
    assert json.loads(model_create.calls[0].request.content) == model_payload
    assert b'name="metadata"' in upload.calls[0].request.content
