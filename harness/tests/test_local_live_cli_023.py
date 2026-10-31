"""OpenSpec 023 local-live CLI: the explicit retry-vlm path (knowledge id, marker, attempts).

This module keeps its path: the digest-pinned plugin contract
(deploy/upstream/weknora-plugin-contract.yaml, node compatibility.harness_retry_scope) and the
trusted local-live image workflow name one of its tests. The other CLI contracts live in
service_shell/local_live_cli/.
"""

from __future__ import annotations

import json
from hashlib import sha256
from io import StringIO
from pathlib import Path
from stat import S_IMODE

import pytest
from pydantic import SecretStr

from tests.service_shell.local_live_cli.helpers import PhaseRequestLike, ResolvedLocks, _module


def test_r3_3_knowledge_id_is_required_only_for_explicit_retry() -> None:
    module = _module()
    calls: list[PhaseRequestLike] = []

    class Adapter:
        def run(self, request: PhaseRequestLike) -> object:
            calls.append(request)
            return {"status": "failed", "knowledge_id": request.knowledge_id}

    missing = StringIO()
    assert module.main(
        ["retry-vlm"],
        adapter=Adapter(),
        lock_verifier=ResolvedLocks(),
        output=StringIO(),
        error=missing,
    ) == 2
    assert calls == []
    assert "--knowledge-id is required" in missing.getvalue()

    invalid = StringIO()
    assert module.main(
        ["smoke-vlm", "--knowledge-id", "vlm-knowledge-1"],
        adapter=Adapter(),
        lock_verifier=ResolvedLocks(),
        output=StringIO(),
        error=invalid,
    ) == 2
    assert calls == []
    assert "valid only for retry-vlm" in invalid.getvalue()


def test_r3_3_retry_vlm_consumes_marker_after_identity_before_single_reparse(
    tmp_path: Path,
) -> None:
    module = _module()
    runtime = tmp_path / ".env.local-live.runtime"
    runtime.write_text("opaque runtime\n")
    runtime.chmod(0o600)
    fixture = tmp_path / "vlm-canary.png"
    fixture.write_bytes(b"safe visual fixture")
    process_config = {
        "enable_multimodel": True,
        "vlm_config": {"enabled": True, "model_id": "vlm-model"},
    }
    config_digest = sha256(
        json.dumps(process_config, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    calls: list[str] = []
    resolver_calls: list[str] = []
    attempt_calls = 0

    class Client:
        async def get_knowledge(self, key: object, knowledge_id: str) -> dict[str, object]:
            del key
            calls.append(f"get:{knowledge_id}")
            return {
                "id": knowledge_id,
                "knowledge_base_id": "raw-kb",
                "parse_status": "failed",
                "metadata": {
                    "owner": "insurancekb-local-live-v1",
                    "sha256": sha256(fixture.read_bytes()).hexdigest(),
                    "purpose": "vlm-smoke",
                    "vlm_model_id": "vlm-model",
                    "process_config_sha256": config_digest,
                    "process_overrides": process_config,
                },
                "error": "provider-secret raw provider response",
            }

        async def get_knowledge_parse_attempt(
            self, key: object, knowledge_id: str
        ) -> int:
            nonlocal attempt_calls
            del key
            attempt_calls += 1
            calls.append(f"attempt:{knowledge_id}:{attempt_calls}")
            return attempt_calls

        async def reparse_knowledge(
            self,
            key: object,
            knowledge_id: str,
            config: object,
        ) -> dict[str, object]:
            del key, config
            calls.append(f"reparse:{knowledge_id}")
            return {"id": knowledge_id}

        async def aclose(self) -> None:
            calls.append("close")

    class Resolver:
        async def resolve(self, values: object = None) -> SecretStr:
            resolver_calls.append("resolve")
            return SecretStr("tenant-key")

    collaborator = module.VLMSmokeCollaborator(
        runtime_path=runtime,
        fixture_path=fixture,
        runtime_loader=lambda path: {
            "LOCAL_LIVE_RAW_KB_ID": "raw-kb",
            "LOCAL_LIVE_VLLM_MODEL_ID": "vlm-model",
        },
        client_factory=lambda url: Client(),
        api_key_resolver=Resolver(),
        poll_interval=0,
    )
    request = module.PhaseRequest("retry-vlm", False, None, "vlm-knowledge-1")

    result = collaborator.run(request)
    assert result["knowledge_id"] == "vlm-knowledge-1"
    assert result["attempt"] == 2
    assert result["error_class"] == "knowledge_parse_failed"
    assert "provider-secret" not in repr(result)

    assert sum(call.startswith("reparse:") for call in calls) == 1
    assert resolver_calls == ["resolve"]
    assert attempt_calls == 2
    api_calls = tuple(calls)
    marker = next(tmp_path.glob(".env.local-live.runtime.retry-vlm-*"))
    assert S_IMODE(marker.stat().st_mode) == 0o600
    with pytest.raises(RuntimeError, match="retry"):
        collaborator.run(request)
    assert tuple(calls) == api_calls
    assert resolver_calls == ["resolve"]
    assert attempt_calls == 2


@pytest.mark.parametrize(
    ("attempts", "expected_reparse_count"),
    (([None], 0), ([2, 2], 1), ([2, 4], 1)),
)
def test_r3_3_retry_uses_real_span_attempt_and_rejects_missing_or_nonincremented_attempt(
    tmp_path: Path,
    attempts: list[int | None],
    expected_reparse_count: int,
) -> None:
    module = _module()
    runtime = tmp_path / ".env.local-live.runtime"
    runtime.write_text("opaque runtime\n")
    runtime.chmod(0o600)
    fixture = tmp_path / "vlm-canary.png"
    fixture.write_bytes(b"safe visual fixture")
    process_config = {
        "enable_multimodel": True,
        "vlm_config": {"enabled": True, "model_id": "vlm-model"},
    }
    config_digest = sha256(
        json.dumps(process_config, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    calls: list[str] = []
    remaining_attempts = list(attempts)

    class Client:
        async def get_knowledge(self, key: object, knowledge_id: str) -> dict[str, object]:
            del key
            calls.append(f"get:{knowledge_id}")
            return {
                "id": knowledge_id,
                "knowledge_base_id": "raw-kb",
                "parse_status": "failed",
                "metadata": {
                    "owner": "insurancekb-local-live-v1",
                    "sha256": sha256(fixture.read_bytes()).hexdigest(),
                    "purpose": "vlm-smoke",
                    "vlm_model_id": "vlm-model",
                    "process_config_sha256": config_digest,
                    "process_overrides": process_config,
                },
            }

        async def get_knowledge_parse_attempt(
            self, key: object, knowledge_id: str
        ) -> object:
            del key
            calls.append(f"attempt:{knowledge_id}")
            return remaining_attempts.pop(0)

        async def reparse_knowledge(
            self, key: object, knowledge_id: str, config: object
        ) -> dict[str, object]:
            del key, config
            calls.append(f"reparse:{knowledge_id}")
            return {"id": knowledge_id}

        async def aclose(self) -> None:
            calls.append("close")

    class Resolver:
        async def resolve(self, values: object = None) -> SecretStr:
            return SecretStr("tenant-key")

    collaborator = module.VLMSmokeCollaborator(
        runtime_path=runtime,
        fixture_path=fixture,
        runtime_loader=lambda path: {
            "LOCAL_LIVE_RAW_KB_ID": "raw-kb",
            "LOCAL_LIVE_VLLM_MODEL_ID": "vlm-model",
        },
        client_factory=lambda url: Client(),
        api_key_resolver=Resolver(),
        poll_interval=0,
    )

    with pytest.raises(RuntimeError, match="retry"):
        collaborator.run(
            module.PhaseRequest("retry-vlm", False, None, "vlm-knowledge-1")
        )

    assert sum(call.startswith("reparse:") for call in calls) == expected_reparse_count
    markers = tuple(tmp_path.glob(".env.local-live.runtime.retry-vlm-*"))
    assert bool(markers) is bool(expected_reparse_count)


@pytest.mark.parametrize(
    "mutation",
    (
        "kb",
        "owner",
        "sha",
        "purpose",
        "vlm_model",
        "process_config",
        "completed",
        "pending",
        "processing",
    ),
)
def test_r3_3_retry_rejects_arbitrary_knowledge_before_marker_and_reparse(
    tmp_path: Path,
    mutation: str,
) -> None:
    module = _module()
    runtime = tmp_path / ".env.local-live.runtime"
    runtime.write_text("opaque runtime\n")
    runtime.chmod(0o600)
    fixture = tmp_path / "vlm-canary.png"
    fixture.write_bytes(b"safe visual fixture")
    fixture_digest = sha256(fixture.read_bytes()).hexdigest()
    process_config = {
        "enable_multimodel": True,
        "vlm_config": {"enabled": True, "model_id": "vlm-model"},
    }
    config_digest = sha256(
        json.dumps(process_config, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    metadata: dict[str, object] = {
        "owner": "insurancekb-local-live-v1",
        "sha256": fixture_digest,
        "purpose": "vlm-smoke",
        "vlm_model_id": "vlm-model",
        "process_config_sha256": config_digest,
    }
    record: dict[str, object] = {
        "id": "vlm-knowledge-1",
        "knowledge_base_id": "raw-kb",
        "parse_status": "failed",
        "metadata": metadata,
    }
    metadata["process_overrides"] = process_config
    if mutation == "kb":
        record["knowledge_base_id"] = "other-kb"
    elif mutation in {"owner", "purpose"}:
        metadata[mutation] = "wrong"
    elif mutation == "sha":
        metadata["sha256"] = "0" * 64
    elif mutation == "vlm_model":
        metadata["vlm_model_id"] = "other-vlm"
    elif mutation == "process_config":
        metadata["process_overrides"] = {
            **process_config,
            "vlm_config": {"enabled": True, "model_id": "other-vlm"},
        }
    elif mutation in {"completed", "pending", "processing"}:
        record["parse_status"] = mutation
    calls: list[str] = []

    class Client:
        async def get_knowledge(self, key: object, knowledge_id: str) -> dict[str, object]:
            del key
            calls.append(f"get:{knowledge_id}")
            return record

        async def reparse_knowledge(self, *args: object, **kwargs: object) -> object:
            calls.append("reparse")
            raise AssertionError("arbitrary knowledge must not be reparsed")

        async def upload_file(self, *args: object, **kwargs: object) -> object:
            calls.append("upload")
            raise AssertionError("retry must not upload")

        async def get_knowledge_parse_attempt(
            self, key: object, knowledge_id: str
        ) -> int:
            del key, knowledge_id
            calls.append("attempt")
            raise AssertionError("non-retryable status must fail before attempt lookup")

        async def aclose(self) -> None:
            calls.append("close")

    class Resolver:
        async def resolve(self, values: object = None) -> SecretStr:
            return SecretStr("tenant-key")

    collaborator = module.VLMSmokeCollaborator(
        runtime_path=runtime,
        fixture_path=fixture,
        runtime_loader=lambda path: {
            "LOCAL_LIVE_RAW_KB_ID": "raw-kb",
            "LOCAL_LIVE_VLLM_MODEL_ID": "vlm-model",
        },
        client_factory=lambda url: Client(),
        api_key_resolver=Resolver(),
        poll_interval=0,
    )
    request = module.PhaseRequest("retry-vlm", False, None, "vlm-knowledge-1")

    with pytest.raises(RuntimeError, match="retry"):
        collaborator.run(request)

    assert calls == ["get:vlm-knowledge-1", "close"]
    assert not tuple(tmp_path.glob(".env.local-live.runtime.retry-vlm-*"))
