"""Local-live provisioning: resource identity, response attestation and KB payloads."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import cast

import pytest
import respx
from pydantic import SecretStr

from insurance_harness.live_env.config import ModelProfile
from tests.service_shell.local_provisioning.helpers import FakeBackend, _plan, _provision_module


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
