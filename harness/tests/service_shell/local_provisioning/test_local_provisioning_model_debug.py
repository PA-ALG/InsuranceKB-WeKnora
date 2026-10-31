"""Local-live provisioning: model key refresh, stored model debug attestation and uploads."""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Any, cast

import pytest
import respx
from pydantic import SecretStr


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
