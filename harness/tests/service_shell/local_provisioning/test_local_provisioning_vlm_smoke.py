"""Local-live provisioning: the VLM smoke upload, overrides and non-completed matches."""

from __future__ import annotations

import json
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import SecretStr


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
