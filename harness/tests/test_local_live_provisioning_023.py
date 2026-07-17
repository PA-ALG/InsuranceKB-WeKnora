"""OpenSpec 023 R3.1/R3.2: ownership-safe local-live provisioning."""

from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import respx
from pydantic import SecretStr
from sqlalchemy import Table, create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.live_env.config import ModelProfile


def _provision_module() -> Any:
    try:
        return import_module("insurance_harness.live_env.provision")
    except ModuleNotFoundError:
        pytest.fail("R3.1/R3.2 provisioner is missing")


class FakeBackend:
    def __init__(self) -> None:
        self.resources: list[Any] = []
        self.knowledge: list[Any] = []
        self.pages: list[Any] = []
        self.created: list[str] = []
        self.uploaded_to: list[str] = []

    async def list_resources(self, kind: str) -> list[Any]:
        return [resource for resource in self.resources if resource.kind == kind]

    async def create_resource(self, desired: Any) -> Any:
        module = _provision_module()
        record = module.OwnedResource(
            id=f"{desired.kind}-{len(self.resources) + 1}",
            kind=desired.kind,
            name=desired.name,
            tenant_id=desired.tenant_id,
            marker=desired.marker,
            role=desired.role,
            dimension=desired.dimension,
            model_type=desired.model_type,
            provider=desired.provider,
            model_name=desired.model_name,
            endpoint_fingerprint=desired.endpoint_fingerprint,
            supports_vision=desired.supports_vision,
            embedding_model_id=desired.embedding_model_id,
            vlm_enabled=desired.vlm_enabled,
            vlm_model_id=desired.vlm_model_id,
            capabilities=desired.capabilities,
            knowledge_base_ids=desired.knowledge_base_ids,
        )
        self.resources.append(record)
        self.created.append(desired.kind)
        return record

    async def list_knowledge(self, kb_id: str) -> list[Any]:
        return [item for item in self.knowledge if item.kb_id == kb_id]

    async def upload_pdf(self, kb_id: str, path: Path, digest: str, marker: str) -> Any:
        module = _provision_module()
        self.uploaded_to.append(kb_id)
        record = module.KnowledgeRecord(
            id=f"knowledge-{len(self.knowledge) + 1}",
            kb_id=kb_id,
            sha256=digest,
            status="processing",
            chunk_count=0,
            marker=marker,
        )
        self.knowledge.append(record)
        return record

    async def wait_completed(self, knowledge_id: str) -> Any:
        module = _provision_module()
        current = next(item for item in self.knowledge if item.id == knowledge_id)
        completed = module.KnowledgeRecord(
            id=current.id,
            kb_id=current.kb_id,
            sha256=current.sha256,
            status="completed",
            chunk_count=2,
            marker=current.marker,
        )
        self.knowledge[self.knowledge.index(current)] = completed
        return completed

    async def list_wiki_pages(self, kb_id: str) -> list[Any]:
        return [page for page in self.pages if page.kb_id == kb_id]


def _plan(pdf: Path) -> Any:
    module = _provision_module()
    return module.ProvisionPlan(
        marker="insurancekb-local-live-v1",
        tenant_name="insurancekb-local-live",
        chat_model="MiniMax-M2.5",
        embedding_model="Qwen3-VL-Embedding-8B",
        rerank_model="Qwen3-VL-Reranker-8B",
        vlm_model="qwen3.7-plus",
        embedding_dimension=3,
        raw_kb_name="KB-RAW",
        wiki_kb_name="KB-WIKI",
        api_key_name="insurancekb-live-contributor",
        space_name="insurancekb-live-space",
        pdf_path=pdf,
    )


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


@respx.mock
async def test_r3_3_admin_client_refreshes_model_api_key_with_admin_session() -> None:
    module = import_module("insurance_harness.adapters.weknora.admin_client")
    client = module.WeKnoraAdminClient("https://weknora.example/api/v1")
    session = module.AdminSession(
        user_id="user-1",
        tenant_id=7,
        token=SecretStr("tenant-jwt"),
        refresh_token=SecretStr("tenant-refresh"),
    )
    route = respx.put(
        "https://weknora.example/api/v1/models/chat-1/credentials"
    ).respond(
        json={
            "success": True,
            "data": {
                "fields": {
                    "api_key": {"configured": True},
                    "app_secret": {"configured": False},
                }
            },
        }
    )
    try:
        await client.refresh_model_api_key(
            session,
            "chat-1",
            SecretStr("provider-key-secret"),
        )
    finally:
        await client.aclose()

    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer tenant-jwt"
    assert json.loads(request.content) == {"api_key": "provider-key-secret"}


@respx.mock
async def test_r3_3_model_credential_failure_redacts_key_and_response(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = import_module("insurance_harness.adapters.weknora.admin_client")
    client = module.WeKnoraAdminClient("https://weknora.example/api/v1")
    session = module.AdminSession(
        user_id="user-1",
        tenant_id=7,
        token=SecretStr("tenant-jwt"),
        refresh_token=SecretStr("tenant-refresh"),
    )
    respx.put("https://weknora.example/api/v1/models/chat-1/credentials").respond(
        json={
            "success": False,
            "message": "provider-key-secret raw-credential-response",
            "data": {"fields": {"api_key": {"configured": True}}},
        },
    )
    try:
        with pytest.raises(RuntimeError, match="model credential refresh failed") as failure:
            await client.refresh_model_api_key(
                session,
                "chat-1",
                SecretStr("provider-key-secret"),
            )
    finally:
        await client.aclose()

    rendered = str(failure.value)
    captured = capsys.readouterr()
    assert failure.value.__cause__ is None
    assert failure.value.__context__ is None
    for channel in (rendered, caplog.text, captured.out, captured.err):
        assert "tenant-jwt" not in channel
        assert "provider-key-secret" not in channel
        assert "raw-credential-response" not in channel


@pytest.mark.parametrize(
    ("role", "raw_response", "expected_dimension", "expected_count"),
    (
        ("chat", {"content": "stored chat ok"}, None, None),
        ("embedding", [0.1, 0.2, 0.3], 3, None),
        (
            "rerank",
            [
                {"index": 1, "relevance_score": 0.9},
            ],
            None,
            1,
        ),
    ),
)
@respx.mock
async def test_r3_3_admin_client_strictly_attests_stored_model_debug(
    role: str,
    raw_response: object,
    expected_dimension: int | None,
    expected_count: int | None,
) -> None:
    module = import_module("insurance_harness.adapters.weknora.admin_client")
    client = module.WeKnoraAdminClient("https://weknora.example/api/v1")
    session = module.AdminSession(
        user_id="user-1",
        tenant_id=7,
        token=SecretStr("tenant-jwt"),
        refresh_token=SecretStr("tenant-refresh"),
    )
    route = respx.post(
        f"https://weknora.example/api/v1/models/{role}-1/debug"
    ).respond(
        json={
            "success": True,
            "data": {
                "ok": True,
                "error": "must-not-return",
                "raw_response": raw_response,
            },
        }
    )
    documents = ("unrelated", "life insurance") if role == "rerank" else ()
    options = {"temperature": 0.1, "thinking": False} if role == "chat" else None
    try:
        result = await client.debug_model(
            session,
            f"{role}-1",
            role=role,
            input_text="stored model probe",
            documents=documents,
            options=options,
            expected_dimension=expected_dimension,
            minimum_results=1 if role == "rerank" else None,
            expected_result_count=expected_count,
        )
    finally:
        await client.aclose()

    assert result.role == role
    assert result.ok is True
    assert result.embedding_dimension == expected_dimension
    assert result.result_count == expected_count
    assert "must-not-return" not in repr(result)
    assert "stored chat ok" not in repr(result)
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer tenant-jwt"
    assert request.headers["content-type"].startswith("multipart/form-data;")
    assert b'name="input"' in request.content
    assert b"stored model probe" in request.content
    if role == "rerank":
        assert b'name="documents"' in request.content
        assert json.dumps(list(documents)).encode() in request.content
    else:
        assert b'name="documents"' not in request.content
    if options is None:
        assert b'name="options"' not in request.content
    else:
        assert b'name="options"' in request.content
        assert json.dumps(options, separators=(",", ":"), sort_keys=True).encode() in (
            request.content
        )


@pytest.mark.parametrize(
    ("outer_success", "role", "data", "expected_dimension"),
    (
        (
            True,
            "chat",
            {"ok": True, "raw_response": {"content": "   "}},
            None,
        ),
        (
            True,
            "embedding",
            {"ok": True, "raw_response": [0.1, "bad", 0.3]},
            3,
        ),
        (
            True,
            "embedding",
            {"ok": True, "raw_response": [0.1, 0.2]},
            3,
        ),
        (
            True,
            "rerank",
            {
                "ok": True,
                "raw_response": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.8},
                ],
            },
            None,
        ),
        (
            False,
            "chat",
            {"ok": True, "raw_response": {"content": "outer failure leak"}},
            None,
        ),
        (
            True,
            "rerank",
            {
                "ok": False,
                "error": "raw-debug-error",
                "raw_response": "raw-debug-response",
            },
            None,
        ),
    ),
)
@respx.mock
async def test_r3_3_admin_client_rejects_invalid_stored_model_debug_without_leak(
    outer_success: bool,
    role: str,
    data: dict[str, object],
    expected_dimension: int | None,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = import_module("insurance_harness.adapters.weknora.admin_client")
    client = module.WeKnoraAdminClient("https://weknora.example/api/v1")
    session = module.AdminSession(
        user_id="user-1",
        tenant_id=7,
        token=SecretStr("tenant-jwt"),
        refresh_token=SecretStr("tenant-refresh"),
    )
    respx.post(f"https://weknora.example/api/v1/models/{role}-1/debug").respond(
        json={"success": outer_success, "data": data}
    )
    documents = ("unrelated", "life insurance") if role == "rerank" else ()
    try:
        with pytest.raises(RuntimeError, match=f"{role} stored-model debug failed") as failure:
            await client.debug_model(
                session,
                f"{role}-1",
                role=role,
                input_text="stored model probe",
                documents=documents,
                expected_dimension=expected_dimension,
                minimum_results=2 if role == "rerank" else None,
                expected_result_count=2 if role == "rerank" else None,
            )
    finally:
        await client.aclose()

    rendered = str(failure.value)
    captured = capsys.readouterr()
    assert failure.value.__cause__ is None
    assert failure.value.__context__ is None
    for channel in (rendered, caplog.text, captured.out, captured.err):
        assert "tenant-jwt" not in channel
        assert "stored model probe" not in channel
        assert "raw-debug-error" not in channel
        assert "raw-debug-response" not in channel
        assert "outer failure leak" not in channel


@respx.mock
async def test_r3_3_upload_file_optional_process_config_preserves_plain_multipart(
    tmp_path: Path,
) -> None:
    module = import_module("insurance_harness.adapters.weknora.admin_client")
    client = module.WeKnoraAdminClient("https://weknora.example/api/v1")
    api_key = SecretStr("tenant-key")
    fixture = tmp_path / "visual-canary.png"
    fixture.write_bytes(b"canary-png-bytes")
    plain = respx.post(
        "https://weknora.example/api/v1/knowledge-bases/kb-raw/knowledge/file"
    ).respond(json={"success": True, "data": {"id": "plain"}})
    selected = respx.post(
        "https://weknora.example/api/v1/knowledge-bases/kb-vlm/knowledge/file"
    ).respond(json={"success": True, "data": {"id": "selected"}})
    vlm_config = module.VLMProcessConfig(enabled=True, model_id="vlm-1")
    process_config = module.KnowledgeProcessConfig(
        enable_multimodel=True,
        vlm_config=vlm_config,
    )
    try:
        with pytest.raises(ValueError, match="model_id"):
            module.VLMProcessConfig(enabled=True, model_id="   ")
        with pytest.raises(ValueError, match="multimodel"):
            module.KnowledgeProcessConfig(
                enable_multimodel=False,
                vlm_config=vlm_config,
            )
        await client.upload_file(
            api_key,
            "kb-raw",
            fixture,
            metadata={"owner": "local", "sha256": "abc"},
        )
        with pytest.raises(TypeError, match="KnowledgeProcessConfig"):
            await client.upload_file(
                api_key,
                "kb-vlm",
                fixture,
                metadata={"owner": "local", "sha256": "abc"},
                media_type="image/png",
                process_config=cast(Any, {"enable_multimodel": True}),
            )
        await client.upload_file(
            api_key,
            "kb-vlm",
            fixture,
            metadata={"owner": "local", "sha256": "abc"},
            media_type="image/png",
            process_config=process_config,
        )
    finally:
        await client.aclose()

    plain_body = plain.calls[0].request.content
    assert b'name="file"; filename="visual-canary.png"' in plain_body
    assert b"Content-Type: application/pdf" in plain_body
    assert b'name="metadata"' in plain_body
    assert b'enable_multimodel' not in plain_body
    assert b'process_config' not in plain_body
    selected_body = selected.calls[0].request.content
    assert b'name="file"; filename="visual-canary.png"' in selected_body
    assert b"Content-Type: image/png" in selected_body
    assert b'name="enable_multimodel"' in selected_body
    assert b"true" in selected_body
    assert b'name="process_config"' in selected_body
    assert json.dumps(
        {
            "enable_multimodel": True,
            "vlm_config": {"enabled": True, "model_id": "vlm-1"},
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode() in selected_body
    assert len(selected.calls) == 1


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


async def test_r3_1_repeat_provision_reuses_exact_owned_resource_graph(tmp_path: Path) -> None:
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(b"same life insurance PDF")
    backend = FakeBackend()
    module = _provision_module()

    first = await module.provision_local_live(backend, _plan(pdf))
    created_once = list(backend.created)
    second = await module.provision_local_live(backend, _plan(pdf))

    assert second == first
    assert backend.created == created_once
    assert {resource.kind for resource in backend.resources} == {
        "tenant",
        "model:chat",
        "model:embedding",
        "model:rerank",
        "model:vlm",
        "kb:raw",
        "kb:wiki",
        "api-key",
        "space",
    }
    assert {
        resource.role: resource.supports_vision
        for resource in backend.resources
        if resource.kind.startswith("model:")
    } == {
        "chat": False,
        "embedding": False,
        "rerank": False,
        "vlm": True,
    }
    api_key = next(resource for resource in backend.resources if resource.kind == "api-key")
    assert api_key.role == "contributor"
    assert api_key.name == (
        "insurancekb-live-contributor::owner=insurancekb-local-live-v1"
    )
    assert api_key.capabilities == ("retrieve", "ingest")
    assert api_key.knowledge_base_ids == (first.raw_kb_id, first.wiki_kb_id)


async def test_r3_1_stable_name_with_wrong_ownership_fails_closed(tmp_path: Path) -> None:
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(b"life insurance PDF")
    backend = FakeBackend()
    module = _provision_module()
    backend.resources.append(
        module.OwnedResource(
            id="tenant-other",
            kind="tenant",
            name="insurancekb-local-live",
            tenant_id="other",
            marker="someone-else",
            role="tenant",
        )
    )

    with pytest.raises(module.OwnershipMismatch, match="tenant"):
        await module.provision_local_live(backend, _plan(pdf))

    assert backend.created == []


async def test_r3_1_embedding_dimension_mismatch_fails_closed(tmp_path: Path) -> None:
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(b"life insurance PDF")
    backend = FakeBackend()
    module = _provision_module()
    plan = _plan(pdf)
    await module.provision_local_live(backend, plan)

    with pytest.raises(module.OwnershipMismatch, match="model:embedding"):
        await module.provision_local_live(
            backend,
            replace(plan, embedding_dimension=plan.embedding_dimension + 1),
        )


async def test_r3_1_space_backend_is_injected_not_weknora_rest(tmp_path: Path) -> None:
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(b"life insurance PDF")
    weknora = FakeBackend()
    spaces = FakeBackend()
    module = _provision_module()

    result = await module.provision_local_live(weknora, _plan(pdf), space_backend=spaces)

    assert result.space_id.startswith("space-")
    assert "space" not in weknora.created
    assert spaces.created == ["space"]


async def test_r3_1_harness_space_backend_persists_owned_binding(
    tmp_path: Path,
) -> None:
    try:
        space_module = import_module("insurance_harness.live_env.space")
    except ModuleNotFoundError:
        pytest.fail("R3.1 Harness KnowledgeSpace backend is missing")
    engine = create_engine(f"sqlite:///{tmp_path / 'space.db'}")
    cast(Table, KnowledgeSpace.__table__).create(engine)
    factory: sessionmaker[Session] = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )
    plan = _plan(tmp_path / "policy.pdf")
    plan.pdf_path.write_bytes(b"life insurance PDF")
    weknora = FakeBackend()
    spaces = space_module.HarnessSpaceBackend(factory, marker=plan.marker)

    first = await _provision_module().provision_local_live(
        weknora,
        plan,
        space_backend=spaces,
    )
    second = await _provision_module().provision_local_live(
        weknora,
        plan,
        space_backend=spaces,
    )

    assert first.space_id == second.space_id
    with factory() as session:
        row = session.get(KnowledgeSpace, first.space_id)
        assert row is not None
        assert row.name == plan.space_name
        assert row.binding_status == "bound"
        assert row.tenant_id == first.tenant_id
        assert row.raw_kb_id == first.raw_kb_id
        assert row.wiki_kb_id == first.wiki_kb_id
        assert session.scalar(select(func.count()).select_from(KnowledgeSpace)) == 1
    engine.dispose()


async def test_r3_1_harness_space_backend_rejects_foreign_same_name(
    tmp_path: Path,
) -> None:
    space_module = import_module("insurance_harness.live_env.space")
    module = _provision_module()
    engine = create_engine(f"sqlite:///{tmp_path / 'space.db'}")
    cast(Table, KnowledgeSpace.__table__).create(engine)
    factory: sessionmaker[Session] = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )
    plan = _plan(tmp_path / "policy.pdf")
    plan.pdf_path.write_bytes(b"life insurance PDF")
    with factory() as session:
        session.add(
            KnowledgeSpace(
                id="foreign-space-id",
                name=plan.space_name,
                binding_status="bound",
                tenant_id="foreign-tenant",
                raw_kb_id="foreign-raw",
                wiki_kb_id="foreign-wiki",
            )
        )
        session.commit()

    with pytest.raises(module.OwnershipMismatch, match="space"):
        await module.provision_local_live(
            FakeBackend(),
            plan,
            space_backend=space_module.HarnessSpaceBackend(
                factory,
                marker=plan.marker,
            ),
        )

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(KnowledgeSpace)) == 1
    engine.dispose()


async def test_r3_2_pdf_sha_reuse_upload_once_and_wiki_unknown_fail_closed(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(b"life insurance PDF")
    backend = FakeBackend()
    module = _provision_module()
    first = await module.provision_local_live(backend, _plan(pdf))
    assert backend.uploaded_to == [first.raw_kb_id]
    assert first.knowledge.chunk_count > 0

    second = await module.provision_local_live(backend, _plan(pdf))
    assert second.knowledge.id == first.knowledge.id
    assert backend.uploaded_to == [first.raw_kb_id]
    assert first.wiki_kb_id not in backend.uploaded_to

    changed_pdf = tmp_path / "changed.pdf"
    changed_pdf.write_bytes(b"a different life insurance PDF")
    changed = await module.provision_local_live(backend, replace(_plan(pdf), pdf_path=changed_pdf))
    assert changed.knowledge.id != first.knowledge.id
    assert backend.uploaded_to == [first.raw_kb_id, first.raw_kb_id]

    backend.pages.append(
        module.WikiPageRecord(id="unknown", kb_id=first.wiki_kb_id, marker="foreign")
    )
    with pytest.raises(module.OwnershipMismatch, match="wiki"):
        await module.provision_local_live(backend, _plan(pdf))


@pytest.mark.parametrize(
    ("url", "canonical"),
    (
        ("HTTPS://Models.Example:443", "https://models.example/"),
        (
            "https://Models.Example:443/compatible-mode/%7e/",
            "https://models.example/compatible-mode/%7E",
        ),
        ("http://Models.Example:80/v1/", "http://models.example/v1"),
    ),
)
def test_r3_3_canonical_endpoint_fingerprint_normalizes_safe_urls(
    url: str,
    canonical: str,
) -> None:
    module = _provision_module()

    assert module.canonical_endpoint_fingerprint(url) == sha256(
        canonical.encode()
    ).hexdigest()


@pytest.mark.parametrize(
    "url",
    (
        "https://user:password@models.example/v1",
        "https://models.example/v1?api_key=secret",
        "https://models.example/v1#fragment",
        "https://models.example?",
        "https://models.example#",
        "https://models.example/v1/../private",
        "https://models.example/v1//embeddings",
        "https://models.example/v1/%2e%2e/private",
        "https://models.example/v1/%not-hex",
    ),
)
def test_r3_3_canonical_endpoint_fingerprint_rejects_ambiguous_urls(url: str) -> None:
    with pytest.raises(ValueError, match="endpoint URL"):
        _provision_module().canonical_endpoint_fingerprint(url)


def test_r3_3_resource_identity_includes_model_endpoint_and_kb_binding() -> None:
    module = _provision_module()
    fingerprint = module.canonical_endpoint_fingerprint(
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    desired_model = module.DesiredResource(
        kind="model:chat",
        name="deepseek-v4-flash",
        tenant_id="7",
        marker="local-v1",
        role="chat",
        model_type="KnowledgeQA",
        provider="aliyun",
        model_name="deepseek-v4-flash",
        endpoint_fingerprint=fingerprint,
    )
    owned_model = module.OwnedResource(
        id="chat-1",
        kind="model:chat",
        name="deepseek-v4-flash",
        tenant_id="7",
        marker="local-v1",
        role="chat",
        model_type="KnowledgeQA",
        provider="aliyun",
        model_name="deepseek-v4-flash",
        endpoint_fingerprint=fingerprint,
    )
    desired_kb = module.DesiredResource(
        kind="kb:raw",
        name="KB-RAW",
        tenant_id="7",
        marker="local-v1",
        role="raw",
        embedding_model_id="embedding-1",
        vlm_enabled=False,
        vlm_model_id="",
    )
    owned_kb = module.OwnedResource(
        id="kb-raw",
        kind="kb:raw",
        name="KB-RAW",
        tenant_id="7",
        marker="local-v1",
        role="raw",
        embedding_model_id="embedding-1",
        vlm_enabled=False,
        vlm_model_id="",
    )

    assert module._same_resource(owned_model, desired_model)
    assert not module._same_resource(
        replace(owned_model, provider="siliconflow"), desired_model
    )
    assert not module._same_resource(
        replace(owned_model, endpoint_fingerprint="0" * 64), desired_model
    )
    assert not module._same_resource(
        replace(
            owned_model,
            model_type=None,
            provider=None,
            model_name=None,
            endpoint_fingerprint=None,
        ),
        desired_model,
    )
    assert module._same_resource(owned_kb, desired_kb)
    assert not module._same_resource(
        replace(owned_kb, embedding_model_id="embedding-foreign"), desired_kb
    )
    assert not module._same_resource(
        replace(
            owned_kb,
            embedding_model_id=None,
            vlm_enabled=None,
            vlm_model_id=None,
        ),
        desired_kb,
    )
    rendered = repr((owned_model, owned_kb))
    ownership = import_module(
        "insurance_harness.adapters.weknora.admin_client"
    )._ownership("local-v1", "chat", None)
    for forbidden in (
        "https://dashscope.aliyuncs.com",
        "provider-key-secret",
        sha256(b"provider-key-secret").hexdigest(),
    ):
        assert forbidden not in rendered
        assert forbidden not in ownership


@respx.mock
async def test_r3_3_backend_recomputes_model_and_kb_response_identity() -> None:
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    provision = _provision_module()
    client = admin.WeKnoraAdminClient("https://weknora.example/api/v1")
    session = admin.AdminSession(
        user_id="user-1",
        tenant_id=7,
        token=SecretStr("tenant-jwt"),
        refresh_token=SecretStr("tenant-refresh"),
    )
    description = (
        '{"dimension":null,"marker":"insurancekb-local-live-v1",'
        '"role":"chat"}'
    )
    endpoint = "https://DashScope.AliyunCS.com:443/compatible-mode/v1/"
    respx.get("https://weknora.example/api/v1/models").respond(
        json={
            "success": True,
            "data": [
                {
                    "id": "chat-1",
                    "tenant_id": 7,
                    "name": "deepseek-v4-flash",
                    "type": "KnowledgeQA",
                    "source": "remote",
                    "description": description,
                    "parameters": {
                        "base_url": endpoint,
                        "provider": "aliyun",
                        "supports_vision": False,
                    },
                }
            ],
        }
    )
    kb_description = description.replace('"chat"', '"raw"')
    respx.get("https://weknora.example/api/v1/knowledge-bases").respond(
        json={
            "success": True,
            "data": [
                {
                    "id": "kb-legacy",
                    "tenant_id": 7,
                    "name": "OLD-KB",
                    "description": kb_description.replace(
                        "insurancekb-local-live-v1", "another-environment"
                    ),
                },
                {
                    "id": "kb-raw",
                    "tenant_id": 7,
                    "name": "KB-RAW",
                    "description": kb_description,
                    "embedding_model_id": "embedding-1",
                    "vlm_config": {"enabled": False, "model_id": ""},
                }
            ],
        }
    )
    backend = admin.WeKnoraProvisioningBackend(
        client,
        session,
        model_payloads={
            "chat": {
                "type": "KnowledgeQA",
                "parameters": {"base_url": endpoint, "provider": "aliyun"},
            }
        },
        knowledge_base_payloads={},
    )
    desired_chat = provision.DesiredResource(
        kind="model:chat",
        name="deepseek-v4-flash",
        tenant_id="7",
        marker="insurancekb-local-live-v1",
        role="chat",
    )
    try:
        models = await backend.list_resources("model:chat")
        kbs = await backend.list_resources("kb:raw")
        selected = await provision._ensure_resource(backend, desired_chat)
        with pytest.raises(provision.OwnershipMismatch, match="model:chat"):
            await provision._ensure_resource(
                backend,
                replace(desired_chat, provider="siliconflow"),
            )
    finally:
        await client.aclose()

    assert models == [
        provision.OwnedResource(
            id="chat-1",
            kind="model:chat",
            name="deepseek-v4-flash",
            tenant_id="7",
            marker="insurancekb-local-live-v1",
            role="chat",
            model_type="KnowledgeQA",
            provider="aliyun",
            model_name="deepseek-v4-flash",
            endpoint_fingerprint=provision.canonical_endpoint_fingerprint(endpoint),
            supports_vision=False,
        )
    ]
    assert kbs == [
        provision.OwnedResource(
            id="kb-legacy",
            kind="kb:raw",
            name="OLD-KB",
            tenant_id="7",
            marker="another-environment",
            role="raw",
        ),
        provision.OwnedResource(
            id="kb-raw",
            kind="kb:raw",
            name="KB-RAW",
            tenant_id="7",
            marker="insurancekb-local-live-v1",
            role="raw",
            embedding_model_id="embedding-1",
            vlm_enabled=False,
            vlm_model_id="",
        )
    ]
    assert selected == models[0]


async def test_r3_3_plain_pdf_waits_for_exact_raw_kb_binding(tmp_path: Path) -> None:
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(b"life insurance PDF")
    backend = FakeBackend()
    module = _provision_module()
    plan = _plan(pdf)
    first = await module.provision_local_live(backend, plan)
    raw = next(resource for resource in backend.resources if resource.kind == "kb:raw")
    backend.resources[backend.resources.index(raw)] = replace(
        raw,
        embedding_model_id="foreign-embedding",
    )
    changed_pdf = tmp_path / "changed.pdf"
    changed_pdf.write_bytes(b"different life insurance PDF")

    with pytest.raises(module.OwnershipMismatch, match="kb:raw"):
        await module.provision_local_live(
            backend,
            replace(plan, pdf_path=changed_pdf),
        )

    assert backend.uploaded_to == [first.raw_kb_id]


@pytest.mark.parametrize(
    ("role", "model_type", "supports_vision"),
    (
        ("chat", "KnowledgeQA", False),
        ("embedding", "Embedding", False),
        ("rerank", "Rerank", False),
        ("vlm", "VLLM", True),
    ),
)
def test_r3_3_model_payloads_are_provider_aware_remote_resources(
    role: str,
    model_type: str,
    supports_vision: bool,
) -> None:
    local = import_module("insurance_harness.live_env.local_provisioning")
    profile = ModelProfile(
        base_url=f"https://{role}.example/v1",
        api_key=SecretStr(f"{role}-secret"),
        model=f"{role}-model",
        provider="aliyun",
        protocol=("dashscope_native" if role == "rerank" else "openai_compatible"),
    )

    payload = local._model_payload(
        profile,
        model_type=model_type,
        dimension=1024 if role == "embedding" else None,
        supports_vision=supports_vision,
    )

    assert payload["source"] == "remote"
    assert payload["type"] == model_type
    assert "supports_vision" not in payload
    parameters = cast(dict[str, object], payload["parameters"])
    assert parameters["supports_vision"] is supports_vision
    assert parameters["provider"] == "aliyun"
    assert "siliconflow" not in repr(payload)


def test_r3_1_wiki_kb_payload_explicitly_enables_wiki_indexing() -> None:
    local = import_module("insurance_harness.live_env.local_provisioning")

    payloads = local._knowledge_base_payloads()

    assert payloads["raw"] == {"type": "document"}
    assert payloads["wiki"] == {
        "type": "wiki",
        "indexing_strategy": {
            "vector_enabled": True,
            "keyword_enabled": True,
            "wiki_enabled": True,
            "graph_enabled": False,
        },
        "wiki_config": {},
    }


@pytest.mark.parametrize(("role", "supports_vision"), (("chat", False), ("vlm", True)))
async def test_r3_3_model_create_and_response_attest_nested_vision_capability(
    role: str,
    supports_vision: bool,
) -> None:
    local = import_module("insurance_harness.live_env.local_provisioning")
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    provision = _provision_module()
    profile = ModelProfile(
        base_url=f"https://{role}.example/v1",
        api_key=SecretStr(f"{role}-secret"),
        model=f"{role}-model",
        provider="aliyun",
        protocol="openai_compatible",
    )
    model_type = "VLLM" if role == "vlm" else "KnowledgeQA"
    model_payload = local._model_payload(
        profile,
        model_type=model_type,
        supports_vision=supports_vision,
    )
    captured: list[dict[str, object]] = []

    class Client:
        async def create_model(
            self, session: object, payload: dict[str, object]
        ) -> dict[str, object]:
            del session
            captured.append(payload)
            return {
                "id": f"{role}-1",
                "name": payload["name"],
                "description": payload["description"],
                "type": payload["type"],
                "parameters": dict(cast(dict[str, object], payload["parameters"])),
            }

    session = admin.AdminSession(
        user_id="user-1",
        tenant_id=7,
        token=SecretStr("tenant-jwt"),
        refresh_token=SecretStr("tenant-refresh"),
    )
    backend = admin.WeKnoraProvisioningBackend(
        cast(Any, Client()),
        session,
        model_payloads={role: model_payload},
        knowledge_base_payloads={},
    )
    desired = backend.resolve_desired_resource(
        provision.DesiredResource(
            kind=f"model:{role}",
            name=f"{role}-model",
            tenant_id="7",
            marker="insurancekb-local-live-v1",
            role=role,
        )
    )

    created = await backend.create_resource(desired)

    create_payload = captured[0]
    create_parameters = cast(dict[str, object], create_payload["parameters"])
    assert "supports_vision" not in create_payload
    assert create_parameters["supports_vision"] is supports_vision
    assert desired.supports_vision is supports_vision
    assert created.supports_vision is supports_vision
    assert provision._same_resource(created, desired)
    assert not provision._same_resource(
        replace(created, supports_vision=not supports_vision), desired
    )


async def test_r3_3_backend_refreshes_four_role_credentials_then_debugs_three() -> None:
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    provision = _provision_module()
    calls: list[tuple[str, object]] = []

    class Client:
        async def refresh_model_api_key(
            self,
            session: object,
            model_id: str,
            api_key: SecretStr,
        ) -> None:
            del session
            calls.append((f"refresh:{model_id}", api_key.get_secret_value()))

        async def debug_model(self, session: object, model_id: str, **kwargs: object) -> None:
            del session
            calls.append((f"debug:{model_id}", kwargs))

    payloads = {
        role: {
            "type": model_type,
            "source": "remote",
            "parameters": {
                "api_key": f"{role}-secret",
                "base_url": f"https://{role}.example/v1",
                "provider": "aliyun",
            },
        }
        for role, model_type in (
            ("chat", "KnowledgeQA"),
            ("embedding", "Embedding"),
            ("rerank", "Rerank"),
            ("vlm", "VLLM"),
        )
    }
    backend = admin.WeKnoraProvisioningBackend(
        cast(Any, Client()),
        admin.AdminSession(
            user_id="user-1",
            tenant_id=7,
            token=SecretStr("tenant-jwt"),
            refresh_token=SecretStr("tenant-refresh"),
        ),
        model_payloads=payloads,
        knowledge_base_payloads={},
    )
    models = {
        role: provision.OwnedResource(
            id=f"{role}-id",
            kind=f"model:{role}",
            name=f"{role}-model",
            tenant_id="7",
            marker="local-v1",
            role=role,
        )
        for role in payloads
    }

    await backend.attest_models(models, 3)

    assert calls[:4] == [
        ("refresh:chat-id", "chat-secret"),
        ("refresh:embedding-id", "embedding-secret"),
        ("refresh:rerank-id", "rerank-secret"),
        ("refresh:vlm-id", "vlm-secret"),
    ]
    assert [name for name, _ in calls[4:]] == [
        "debug:chat-id",
        "debug:embedding-id",
        "debug:rerank-id",
    ]
    embedding = cast(dict[str, object], calls[5][1])
    assert embedding["expected_dimension"] == 3
    rerank = cast(dict[str, object], calls[6][1])
    assert rerank["minimum_results"] == 2
    assert rerank["expected_result_count"] == 2
    assert len(cast(tuple[str, ...], rerank["documents"])) == 2


def test_r3_3_runtime_state_keeps_vlm_id_and_only_endpoint_fingerprints() -> None:
    local = import_module("insurance_harness.live_env.local_provisioning")
    profiles = {
        role: ModelProfile(
            base_url=f"https://{role}.example/v1",
            api_key=SecretStr(f"{role}-secret"),
            model=f"{role}-model",
            provider="aliyun",
            protocol=(
                "dashscope_native" if role == "rerank" else "openai_compatible"
            ),
        )
        for role in ("chat", "embedding", "rerank", "vlm")
    }
    configuration = type(
        "Configuration",
        (),
        {
            "weknora_chat": profiles["chat"],
            "weknora_embedding": profiles["embedding"],
            "weknora_rerank": profiles["rerank"],
            "weknora_vllm": profiles["vlm"],
        },
    )()
    result = type(
        "Result",
        (),
        {
            "chat_model_id": "chat-id",
            "embedding_model_id": "embedding-id",
            "rerank_model_id": "rerank-id",
            "vlm_model_id": "vlm-id",
        },
    )()

    state = local._runtime_model_state(configuration, result)

    assert state["LOCAL_LIVE_VLLM_MODEL_ID"] == "vlm-id"
    assert set(state) == {
        "LOCAL_LIVE_CHAT_MODEL_ID",
        "LOCAL_LIVE_EMBEDDING_MODEL_ID",
        "LOCAL_LIVE_RERANK_MODEL_ID",
        "LOCAL_LIVE_VLLM_MODEL_ID",
        "LOCAL_LIVE_CHAT_ENDPOINT_FINGERPRINT",
        "LOCAL_LIVE_EMBEDDING_ENDPOINT_FINGERPRINT",
        "LOCAL_LIVE_RERANK_ENDPOINT_FINGERPRINT",
        "LOCAL_LIVE_VLLM_ENDPOINT_FINGERPRINT",
    }
    rendered = repr(state)
    for role in profiles:
        assert f"https://{role}.example/v1" not in rendered
        assert f"{role}-secret" not in rendered
        assert sha256(f"{role}-secret".encode()).hexdigest() not in rendered


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


@respx.mock
async def test_r3_3_find_knowledge_by_sha256_paginates_beyond_first_page() -> None:
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    base = "https://weknora.example/api/v1/knowledge-bases/raw-kb/knowledge"
    digest = "a" * 64
    first_page = respx.get(
        base,
        params={"page": 1, "page_size": 100},
    ).respond(
        json={
            "success": True,
            "data": [
                {"id": f"other-{index}", "metadata": {"sha256": "b" * 64}}
                for index in range(100)
            ],
            "total": 101,
            "page": 1,
            "page_size": 100,
        }
    )
    second_page = respx.get(
        base,
        params={"page": 2, "page_size": 100},
    ).respond(
        json={
            "success": True,
            "data": [{"id": "matching-101", "metadata": {"sha256": digest}}],
            "total": 101,
            "page": 2,
            "page_size": 100,
        }
    )
    client = admin.WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        matches = await client.find_knowledge_by_sha256(
            SecretStr("tenant-key"),
            "raw-kb",
            digest,
        )
    finally:
        await client.aclose()

    assert [item["id"] for item in matches] == ["matching-101"]
    assert first_page.called and second_page.called


@respx.mock
async def test_r3_3_parse_attempt_reads_strict_span_envelope() -> None:
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    route = respx.get(
        "https://weknora.example/api/v1/knowledge/knowledge-1/spans"
    ).respond(
        json={
            "success": True,
            "data": {"knowledge_id": "knowledge-1", "current_attempt": 3},
        }
    )
    client = admin.WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        attempt = await client.get_knowledge_parse_attempt(
            SecretStr("tenant-key"), "knowledge-1"
        )
    finally:
        await client.aclose()

    assert attempt == 3
    assert route.called


@pytest.mark.parametrize(
    "data",
    (
        {"knowledge_id": "other", "current_attempt": 3},
        {"knowledge_id": "knowledge-1", "current_attempt": 0},
        {"knowledge_id": "knowledge-1", "current_attempt": True},
        {"knowledge_id": "knowledge-1"},
    ),
)
@respx.mock
async def test_r3_3_parse_attempt_rejects_mismatched_identity_and_invalid_attempt(
    data: dict[str, object],
) -> None:
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    respx.get(
        "https://weknora.example/api/v1/knowledge/knowledge-1/spans"
    ).respond(json={"success": True, "data": data})
    client = admin.WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        with pytest.raises(ValueError, match="span"):
            await client.get_knowledge_parse_attempt(
                SecretStr("tenant-key"), "knowledge-1"
            )
    finally:
        await client.aclose()


@respx.mock
async def test_r3_3_typed_chunks_preserve_outer_pagination_and_plain_defaults_text() -> None:
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    base = "https://weknora.example/api/v1/chunks/knowledge-1"
    plain = respx.get(base, params={"page": 1, "page_size": 100}).respond(
        json={"success": True, "data": [{"id": "text-1"}]}
    )
    ocr_1 = respx.get(
        base,
        params={"page": 1, "page_size": 1, "chunk_type": "image_ocr"},
    ).respond(
        json={
            "success": True,
            "data": [{"id": "ocr-1"}],
            "total": 2,
            "page": 1,
            "page_size": 1,
        }
    )
    ocr_2 = respx.get(
        base,
        params={"page": 2, "page_size": 1, "chunk_type": "image_ocr"},
    ).respond(
        json={
            "success": True,
            "data": [{"id": "ocr-2"}],
            "total": 2,
            "page": 2,
            "page_size": 1,
        }
    )
    caption = respx.get(
        base,
        params={"page": 1, "page_size": 1, "chunk_type": "image_caption"},
    ).respond(
        json={
            "success": True,
            "data": [{"id": "caption-1"}],
            "total": 1,
            "page": 1,
            "page_size": 1,
        }
    )
    reparse = respx.post(
        "https://weknora.example/api/v1/knowledge/knowledge-1/reparse"
    ).respond(json={"success": True, "data": {"id": "knowledge-1"}})
    client = admin.WeKnoraAdminClient("https://weknora.example/api/v1")
    key = SecretStr("tenant-key")
    config = admin.KnowledgeProcessConfig(
        enable_multimodel=True,
        vlm_config=admin.VLMProcessConfig(enabled=True, model_id="vlm-1"),
    )
    try:
        assert await client.list_chunks(key, "knowledge-1") == [{"id": "text-1"}]
        ocr = await client.list_typed_chunks(
            key, "knowledge-1", chunk_type="image_ocr", page_size=1
        )
        captions = await client.list_typed_chunks(
            key, "knowledge-1", chunk_type="image_caption", page_size=1
        )
        assert await client.reparse_knowledge(key, "knowledge-1", config) == {
            "id": "knowledge-1"
        }
    finally:
        await client.aclose()

    assert [item["id"] for item in ocr.items] == ["ocr-1", "ocr-2"]
    assert (ocr.total, ocr.page, ocr.page_size) == (2, 2, 1)
    assert [item["id"] for item in captions.items] == ["caption-1"]
    assert plain.called and ocr_1.called and ocr_2.called and caption.called
    assert "chunk_type" not in plain.calls[0].request.url.params
    assert json.loads(reparse.calls[0].request.content) == {
        "process_config": config.as_payload()
    }


async def test_r3_3_vlm_smoke_uploads_only_unmatched_fixture_and_attests_children(
    tmp_path: Path,
) -> None:
    local = import_module("insurance_harness.live_env.local_provisioning")
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    fixture = tmp_path / "vlm-canary.png"
    fixture.write_bytes(b"safe visual fixture")
    calls: list[tuple[str, object]] = []

    class Client:
        async def find_knowledge_by_sha256(
            self, key: SecretStr, kb_id: str, digest: str
        ) -> list[dict[str, object]]:
            del key, digest
            calls.append(("find", kb_id))
            return []

        async def upload_file(
            self,
            key: SecretStr,
            kb_id: str,
            path: Path,
            **kwargs: object,
        ) -> dict[str, object]:
            del key
            calls.append(("upload", (kb_id, path, kwargs)))
            return {"id": "vlm-knowledge-1", "parse_status": "processing"}

        async def get_knowledge(self, key: SecretStr, knowledge_id: str) -> dict[str, object]:
            del key
            calls.append(("get", knowledge_id))
            return {
                "id": knowledge_id,
                "knowledge_base_id": "raw-kb",
                "parse_status": "completed",
            }

        async def get_knowledge_parse_attempt(
            self, key: SecretStr, knowledge_id: str
        ) -> int:
            del key, knowledge_id
            calls.append(("attempt", 1))
            return 1

        async def list_typed_chunks(
            self,
            key: SecretStr,
            knowledge_id: str,
            *,
            chunk_type: str,
            page_size: int = 100,
        ) -> object:
            del key, knowledge_id, page_size
            calls.append(("chunks", chunk_type))
            items = (
                ({
                    "id": "ocr-1",
                    "parent_chunk_id": "parent-1",
                    "content": "INSURANCEKBVLM023CANARY7F3A",
                },)
                if chunk_type == "image_ocr"
                else ({"id": "caption-1", "parent_chunk_id": "parent-1"},)
            )
            return admin.TypedChunkListing(
                items=items,
                total=len(items),
                page=1,
                page_size=100,
            )

        async def aclose(self) -> None:
            calls.append(("close", True))

    class Resolver:
        async def resolve(self, runtime: object = None) -> SecretStr:
            return SecretStr("tenant-key")

    collaborator = local.VLMSmokeCollaborator(
        runtime_path=tmp_path / ".env.local-live.runtime",
        fixture_path=fixture,
        runtime_loader=lambda path: {
            "LOCAL_LIVE_RAW_KB_ID": "raw-kb",
            "LOCAL_LIVE_VLLM_MODEL_ID": "vlm-model",
        },
        client_factory=lambda url: cast(Any, Client()),
        api_key_resolver=Resolver(),
        poll_interval=0,
    )

    result = await collaborator._smoke()

    upload = cast(tuple[object, ...], calls[1][1])
    assert upload[0] == "raw-kb"
    options = cast(dict[str, object], upload[2])
    assert options["media_type"] == "image/png"
    config = cast(Any, options["process_config"])
    assert config.as_payload() == {
        "enable_multimodel": True,
        "vlm_config": {"enabled": True, "model_id": "vlm-model"},
    }
    expected_config_digest = sha256(
        json.dumps(
            config.as_payload(),
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    assert options["metadata"] == {
        "owner": "insurancekb-local-live-v1",
        "sha256": sha256(fixture.read_bytes()).hexdigest(),
        "purpose": "vlm-smoke",
        "vlm_model_id": "vlm-model",
        "process_config_sha256": expected_config_digest,
    }
    assert result["status"] == "completed"
    assert result["image_ocr_chunks"] == 1
    assert result["image_caption_chunks"] == 1
    rendered = repr(result)
    assert "INSURANCEKBVLM023CANARY7F3A" not in rendered
    assert "content" not in rendered


def test_r3_3_vlm_smoke_accepts_server_normalized_process_overrides() -> None:
    local = import_module("insurance_harness.live_env.local_provisioning")
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    config = admin.KnowledgeProcessConfig(
        enable_multimodel=True,
        vlm_config=admin.VLMProcessConfig(enabled=True, model_id="vlm-model"),
    )
    metadata: dict[str, object] = dict(
        local.VLMSmokeCollaborator._smoke_metadata(
            fixture_digest="f" * 64,
            vlm_model_id="vlm-model",
            process_config=config,
        )
    )
    metadata["process_overrides"] = {
        "enable_multimodel": True,
        "vlm_config": {
            "enabled": True,
            "model_id": "vlm-model",
            "api_key": "***",
            "base_url": "",
            "interface_type": "",
            "model_name": "",
        },
    }

    assert local.VLMSmokeCollaborator._validate_smoke_identity(
        {
            "id": "existing-1",
            "knowledge_base_id": "raw-kb",
            "parse_status": "completed",
            "metadata": metadata,
        },
        knowledge_id=None,
        kb_id="raw-kb",
        fixture_digest="f" * 64,
        vlm_model_id="vlm-model",
        process_config=config,
        retry=False,
    ) == ("existing-1", "completed")


@pytest.mark.parametrize(
    "observed",
    (
        {
            "enable_multimodel": False,
            "vlm_config": {"enabled": True, "model_id": "vlm-model"},
        },
        {
            "enable_multimodel": True,
            "vlm_config": {"enabled": False, "model_id": "vlm-model"},
        },
        {
            "enable_multimodel": True,
            "vlm_config": {"enabled": True, "model_id": "foreign-model"},
        },
    ),
)
def test_r3_3_vlm_smoke_rejects_normalized_security_key_mismatch(
    observed: dict[str, object],
) -> None:
    local = import_module("insurance_harness.live_env.local_provisioning")
    admin = import_module("insurance_harness.adapters.weknora.admin_client")
    expected = admin.KnowledgeProcessConfig(
        enable_multimodel=True,
        vlm_config=admin.VLMProcessConfig(enabled=True, model_id="vlm-model"),
    )

    assert not local.VLMSmokeCollaborator._process_config_matches(
        observed,
        expected,
    )


@pytest.mark.parametrize("status", ("failed", "cancelled", "processing"))
async def test_r3_3_vlm_smoke_preserves_noncompleted_match_without_mutation(
    tmp_path: Path,
    status: str,
) -> None:
    local = import_module("insurance_harness.live_env.local_provisioning")
    fixture = tmp_path / "vlm-canary.png"
    fixture.write_bytes(b"safe visual fixture")
    digest = sha256(fixture.read_bytes()).hexdigest()
    calls: list[str] = []

    class Client:
        async def find_knowledge_by_sha256(
            self, key: SecretStr, kb_id: str, fixture_digest: str
        ) -> list[dict[str, object]]:
            del key, kb_id, fixture_digest
            calls.append("find")
            return [{
                "id": "existing-1",
                "knowledge_base_id": "raw-kb",
                "parse_status": status,
                "metadata": {
                    "sha256": digest,
                    "owner": "insurancekb-local-live-v1",
                    "purpose": "vlm-smoke",
                    "vlm_model_id": "vlm-model",
                    "process_config_sha256": sha256(
                        json.dumps(
                            {
                                "enable_multimodel": True,
                                "vlm_config": {
                                    "enabled": True,
                                    "model_id": "vlm-model",
                                },
                            },
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode()
                    ).hexdigest(),
                    "process_overrides": {
                        "enable_multimodel": True,
                        "vlm_config": {
                            "enabled": True,
                            "model_id": "vlm-model",
                        },
                    },
                },
            }]

        async def upload_file(self, *args: object, **kwargs: object) -> object:
            calls.append("upload")
            raise AssertionError("must not upload a matching fixture")

        async def get_knowledge_parse_attempt(
            self, key: SecretStr, knowledge_id: str
        ) -> int:
            del key, knowledge_id
            calls.append("attempt")
            return 1

        async def reparse_knowledge(self, *args: object, **kwargs: object) -> object:
            calls.append("reparse")
            raise AssertionError("smoke must not retry")

        async def aclose(self) -> None:
            calls.append("close")

    class Resolver:
        async def resolve(self, runtime: object = None) -> SecretStr:
            return SecretStr("tenant-key")

    collaborator = local.VLMSmokeCollaborator(
        runtime_path=tmp_path / ".env.local-live.runtime",
        fixture_path=fixture,
        runtime_loader=lambda path: {
            "LOCAL_LIVE_RAW_KB_ID": "raw-kb",
            "LOCAL_LIVE_VLLM_MODEL_ID": "vlm-model",
        },
        client_factory=lambda url: cast(Any, Client()),
        api_key_resolver=Resolver(),
    )

    result = await collaborator._smoke()

    assert result["knowledge_id"] == "existing-1"
    assert result["status"] == status
    assert calls == ["find", "attempt", "close"]
