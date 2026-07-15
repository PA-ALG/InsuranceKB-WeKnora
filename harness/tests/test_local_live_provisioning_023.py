"""OpenSpec 023 R3.1/R3.2: ownership-safe local-live provisioning."""

from __future__ import annotations

import json
from dataclasses import replace
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
import respx
from pydantic import SecretStr


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
            "tenant": {"id": 1, "name": "admin workspace"},
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
                    "id": "embedding-foreign",
                    "name": "other-embedding",
                    "tenant_id": 7,
                    "description": ownership.replace(
                        "insurancekb-local-live-v1", "another-environment"
                    ),
                },
                {
                    "id": "embedding-owned",
                    "name": "Qwen3-VL-Embedding-8B",
                    "tenant_id": 7,
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
            )
        )
        keys = await backend.list_resources("api-key")
        key = next(item for item in keys if item.id == "2")
        await backend.select_resource(key)
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
        "kb:raw",
        "kb:wiki",
        "api-key",
        "space",
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
