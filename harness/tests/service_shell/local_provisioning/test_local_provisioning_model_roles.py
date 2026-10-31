"""Local-live provisioning: vision capability, four-role credentials and runtime state."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from typing import Any, cast

import pytest
from pydantic import SecretStr

from insurance_harness.live_env.config import ModelProfile
from tests.service_shell.local_provisioning.helpers import _provision_module


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
