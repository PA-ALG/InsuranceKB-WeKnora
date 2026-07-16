"""OpenSpec 023 R1.2: remote model role probe contracts."""

import base64
import json
from collections.abc import Mapping
from dataclasses import replace
from importlib.resources import files

import httpx
import pytest
import respx
from pydantic import SecretStr

from insurance_harness.live_env.config import LocalLiveConfig, ModelProfile
from insurance_harness.live_env.model_probe import ModelProbeError, probe_all_models

VLM_CANARY = "INSURANCEKBVLM023CANARY7F3A"
RERANK_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/"
    "rerank/text-rerank/text-rerank"
)
CHAT_PROMPT = "R1.2 chat health check: reply with probe-ok."
EMBEDDING_INPUT = "R1.2 embedding dimension probe"
RERANK_QUERY = "R1.2 life insurance query"
RERANK_DOCUMENTS = ["R1.2 unrelated document", "R1.2 life insurance policy"]
VLM_PROMPT = "Read the visual canary text exactly."
EXTRACTION_SYSTEM = "You are a health check."
EXTRACTION_USER = "Reply with probe-ok."


def _packaged_canary_bytes() -> bytes:
    resource = files("insurance_harness.live_env").joinpath(
        "fixtures", "vlm-canary.png"
    )
    assert resource.is_file(), "R1.2 packaged VLM canary is missing"
    return resource.read_bytes()


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


def _profile(
    base_url: str,
    model: str,
    secret: str,
    *,
    protocol: str = "openai_compatible",
) -> ModelProfile:
    return ModelProfile(
        base_url=base_url,
        api_key=SecretStr(secret),
        model=model,
        provider="aliyun",
        protocol=protocol,
    )


def _config() -> LocalLiveConfig:
    return LocalLiveConfig(
        weknora_chat=_profile(
            "https://chat.example/v1", "chat-model", "chat-secret"
        ),
        weknora_embedding=_profile(
            "https://embedding.example/v1", "embedding-model", "embedding-secret"
        ),
        weknora_rerank=_profile(
            RERANK_URL,
            "rerank-model",
            "rerank-secret",
            protocol="dashscope_native",
        ),
        weknora_vllm=_profile(
            "https://vlm.example/v1", "qwen3.7-plus", "vlm-secret"
        ),
        extraction=_profile(
            "https://bailian.example/v1", "deepseek-v4-flash", "bailian-secret"
        ),
    )


def _healthy_routes() -> dict[str, respx.Route]:
    return {
        "weknora_chat": respx.post(
            "https://chat.example/v1/chat/completions"
        ).respond(
            json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        ),
        "weknora_embedding": respx.post(
            "https://embedding.example/v1/embeddings"
        ).respond(json={"data": [{"embedding": [0.1, 0.2, 0.3]}]}),
        "weknora_rerank": respx.post(RERANK_URL).respond(
            json={
                "output": {
                    "results": [
                        {"index": 1, "relevance_score": 0.9},
                        {"index": 0, "relevance_score": 0.2},
                    ]
                }
            }
        ),
        "weknora_vllm": respx.post(
            "https://vlm.example/v1/chat/completions"
        ).respond(
            json={
                "choices": [
                    {
                        "message": {"content": f"visual text: {VLM_CANARY}"},
                        "finish_reason": "stop",
                    }
                ]
            }
        ),
        "extraction": respx.post(
            "https://bailian.example/v1/chat/completions"
        ).respond(
            json={
                "choices": [
                    {
                        "message": {
                            "content": "probe-ok",
                            "reasoning_content": "private",
                        },
                        "finish_reason": "stop",
                    }
                ]
            }
        ),
    }


def test_r1_2_vlm_canary_is_a_package_resource() -> None:
    canary = _packaged_canary_bytes()

    assert canary.startswith(b"\x89PNG\r\n\x1a\n")


@respx.mock
async def test_r1_2_five_model_roles_use_exact_protocols_and_runtime_dimension() -> None:
    routes = _healthy_routes()

    results = await probe_all_models(_config())

    assert set(results) == {
        "weknora_chat",
        "weknora_embedding",
        "weknora_rerank",
        "weknora_vllm",
        "extraction",
    }
    assert all(result.ok for result in results.values())
    assert results["weknora_embedding"].embedding_dimension == 3
    assert (
        routes["weknora_chat"].calls[0].request.headers["authorization"]
        == "Bearer chat-secret"
    )
    chat_body = json.loads(routes["weknora_chat"].calls[0].request.content)
    assert chat_body["max_tokens"] == 4096
    assert chat_body["messages"] == [{"role": "user", "content": CHAT_PROMPT}]
    assert (
        routes["weknora_embedding"].calls[0].request.headers["authorization"]
        == "Bearer embedding-secret"
    )
    assert json.loads(routes["weknora_embedding"].calls[0].request.content) == {
        "model": "embedding-model",
        "input": [EMBEDDING_INPUT],
    }
    assert (
        routes["weknora_rerank"].calls[0].request.headers["authorization"]
        == "Bearer rerank-secret"
    )
    assert json.loads(routes["weknora_rerank"].calls[0].request.content) == {
        "model": "rerank-model",
        "input": {"query": RERANK_QUERY, "documents": RERANK_DOCUMENTS},
        "parameters": {"top_n": 2},
    }
    assert (
        routes["weknora_vllm"].calls[0].request.headers["authorization"]
        == "Bearer vlm-secret"
    )
    vlm_body = json.loads(routes["weknora_vllm"].calls[0].request.content)
    content = vlm_body["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": VLM_PROMPT}
    image_url = content[1]["image_url"]["url"]
    prefix = "data:image/png;base64,"
    assert image_url.startswith(prefix)
    assert base64.b64decode(image_url.removeprefix(prefix)) == _packaged_canary_bytes()
    extraction_body = json.loads(routes["extraction"].calls[0].request.content)
    assert extraction_body["max_tokens"] == 4096
    assert extraction_body["messages"] == [
        {"role": "system", "content": EXTRACTION_SYSTEM},
        {"role": "user", "content": EXTRACTION_USER},
    ]
    sanitized = repr(results)
    for forbidden in (
        "secret",
        "https://",
        "reasoning_content",
        "private",
        VLM_CANARY,
    ):
        assert forbidden not in sanitized


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


@respx.mock
async def test_r1_2_chat_probe_retries_reasoning_length_once() -> None:
    routes = _healthy_routes()
    routes["weknora_chat"].mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": "", "reasoning_content": "thinking"},
                            "finish_reason": "length",
                        }
                    ]
                },
            ),
            httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "ok"}, "finish_reason": "stop"}
                    ]
                },
            ),
        ]
    )

    await probe_all_models(_config())

    assert routes["weknora_chat"].call_count == 2


@respx.mock
async def test_r1_2_extraction_probe_retries_reasoning_length_once() -> None:
    routes = _healthy_routes()
    routes["extraction"].mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": "", "reasoning_content": "thinking"},
                            "finish_reason": "length",
                        }
                    ]
                },
            ),
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": "probe-ok"},
                            "finish_reason": "stop",
                        }
                    ]
                },
            ),
        ]
    )

    await probe_all_models(_config())

    assert routes["extraction"].call_count == 2
