"""Model probe: invalid provider shapes, role mismatches and redacted failures."""

from collections.abc import Mapping
from dataclasses import replace

import httpx
import pytest
import respx

from insurance_harness.live_env.model_probe import ModelProbeError, probe_all_models
from tests.service_shell.model_probe.helpers import (
    CHAT_PROMPT,
    EMBEDDING_INPUT,
    EXTRACTION_SYSTEM,
    EXTRACTION_USER,
    RERANK_DOCUMENTS,
    RERANK_QUERY,
    RERANK_URL,
    VLM_CANARY,
    VLM_PROMPT,
    _config,
    _healthy_routes,
)


def _exception_payloads(value: object, seen: set[int] | None = None) -> list[object]:
    visited = seen if seen is not None else set()
    if id(value) in visited:
        return []
    visited.add(id(value))
    payloads = [value]
    if isinstance(value, BaseException):
        payloads.extend(_exception_payloads(value.args, visited))
        payloads.extend(_exception_payloads(vars(value), visited))
        if value.__context__ is not None:
            payloads.extend(_exception_payloads(value.__context__, visited))
        if value.__cause__ is not None:
            payloads.extend(_exception_payloads(value.__cause__, visited))
    elif isinstance(value, Mapping):
        for key, item in value.items():
            payloads.extend(_exception_payloads(key, visited))
            payloads.extend(_exception_payloads(item, visited))
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            payloads.extend(_exception_payloads(item, visited))
    return payloads


@pytest.mark.parametrize(
    "results",
    (
        [{"index": 0, "relevance_score": 0.9}],
        [
            {"index": 0, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.8},
        ],
        [
            {"index": 0, "relevance_score": 0.9},
            {"index": 2, "relevance_score": 0.8},
        ],
        [
            {"index": 0, "relevance_score": 0.9},
            {"index": True, "relevance_score": 0.8},
        ],
        [
            {"index": 0, "relevance_score": 0.9},
            {"index": 1, "relevance_score": "RAW_NON_FINITE"},
        ],
    ),
    ids=("too-few", "duplicate-index", "out-of-range", "bool-index", "non-finite"),
)
@respx.mock
async def test_r1_2_native_rerank_rejects_invalid_result_set(
    results: list[dict[str, object]],
) -> None:
    routes = _healthy_routes()
    legacy = respx.post(f"{RERANK_URL}/rerank")
    if any(row["relevance_score"] == "RAW_NON_FINITE" for row in results):
        routes["weknora_rerank"].respond(
            content=(
                b'{"output":{"results":['
                b'{"index":0,"relevance_score":0.9},'
                b'{"index":1,"relevance_score":1e309}]}}'
            ),
            headers={"content-type": "application/json"},
        )
        legacy.respond(
            content=(
                b'{"results":['
                b'{"index":0,"relevance_score":0.9},'
                b'{"index":1,"relevance_score":1e309}]}'
            ),
            headers={"content-type": "application/json"},
        )
    else:
        routes["weknora_rerank"].respond(json={"output": {"results": results}})
        legacy.respond(json={"results": results})

    with pytest.raises(ModelProbeError, match="weknora_rerank probe failed"):
        await probe_all_models(_config())

    assert not legacy.called


@pytest.mark.parametrize(
    ("malformed_role", "payload"),
    (
        ("weknora_embedding", {"data": [{"embedding": ["not-a-number"]}]}),
        (
            "weknora_rerank",
            {
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 1, "relevance_score": 0.8},
                ]
            },
        ),
    ),
)
@respx.mock
async def test_r1_2_probe_rejects_malformed_provider_shapes(
    malformed_role: str,
    payload: dict[str, object],
) -> None:
    routes = _healthy_routes()
    legacy = respx.post(f"{RERANK_URL}/rerank").respond(
        json={
            "results": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.2},
            ]
        }
    )
    routes[malformed_role].respond(json=payload)

    with pytest.raises(ModelProbeError, match=f"{malformed_role} probe failed"):
        await probe_all_models(_config())

    assert not legacy.called


@respx.mock
async def test_r1_2_vllm_requires_visual_canary_in_response() -> None:
    routes = _healthy_routes()
    routes["weknora_vllm"].respond(
        json={
            "choices": [
                {
                    "message": {"content": "non-empty but no visual canary"},
                    "finish_reason": "stop",
                }
            ]
        }
    )

    with pytest.raises(ModelProbeError, match="weknora_vllm probe failed"):
        await probe_all_models(_config())


@pytest.mark.parametrize(
    ("role", "wrong_protocol"),
    (
        ("weknora_chat", "dashscope_native"),
        ("weknora_embedding", "dashscope_native"),
        ("weknora_rerank", "openai_compatible"),
        ("weknora_vllm", "dashscope_native"),
        ("extraction", "dashscope_native"),
    ),
)
@respx.mock
async def test_r1_2_probe_rejects_role_protocol_mismatch_before_http(
    role: str,
    wrong_protocol: str,
) -> None:
    _healthy_routes()
    config = _config()
    invalid = replace(
        config,
        **{role: replace(getattr(config, role), protocol=wrong_protocol)},
    )

    with pytest.raises(ModelProbeError, match=f"{role} probe failed"):
        await probe_all_models(invalid)

    assert not respx.calls


@pytest.mark.parametrize(
    "failed_role",
    (
        "weknora_chat",
        "weknora_embedding",
        "weknora_rerank",
        "weknora_vllm",
        "extraction",
    ),
)
@respx.mock
async def test_r1_2_each_probe_failure_redacts_all_sensitive_channels(
    failed_role: str,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    routes = _healthy_routes()
    routes[failed_role].respond(
        status_code=502,
        text=(
            "provider-response-secret Authorization Bearer leaked-secret "
            "https://provider-private.example request-body-marker parsed-document-marker"
        ),
    )

    with pytest.raises(ModelProbeError, match=f"{failed_role} probe failed") as failure:
        await probe_all_models(_config())

    assert routes[failed_role].called
    assert failure.value.__context__ is None
    assert failure.value.__cause__ is None
    payloads = _exception_payloads(failure.value)
    retained_http_types = (
        httpx.HTTPStatusError,
        httpx.Request,
        httpx.Response,
        httpx.URL,
        httpx.Headers,
    )
    assert not any(isinstance(value, retained_http_types) for value in payloads)
    captured = capsys.readouterr()
    rendered = "\n".join(
        (str(failure.value), caplog.text, captured.out, captured.err)
    )
    for forbidden in (
        "https://chat.example/v1",
        "https://embedding.example/v1",
        RERANK_URL,
        "https://vlm.example/v1",
        "https://bailian.example/v1",
        "chat-secret",
        "embedding-secret",
        "rerank-secret",
        "vlm-secret",
        "bailian-secret",
        "Authorization",
        "Bearer",
        CHAT_PROMPT,
        EMBEDDING_INPUT,
        RERANK_QUERY,
        *RERANK_DOCUMENTS,
        VLM_PROMPT,
        EXTRACTION_SYSTEM,
        EXTRACTION_USER,
        VLM_CANARY,
        "provider-response-secret",
        "request-body-marker",
        "parsed-document-marker",
    ):
        assert forbidden not in rendered
        assert all(
            forbidden not in value
            for value in payloads
            if isinstance(value, str)
        )
        forbidden_bytes = forbidden.encode()
        assert all(
            forbidden_bytes not in value
            for value in payloads
            if isinstance(value, bytes)
        )
