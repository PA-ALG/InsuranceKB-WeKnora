"""OpenSpec 023 R1.1: remote model role probe contracts."""

from importlib import import_module

import httpx
import pytest
import respx
from pydantic import SecretStr

from insurance_harness.live_env.config import LocalLiveConfig, ModelProfile


def _profile(base_url: str, model: str, secret: str) -> ModelProfile:
    return ModelProfile(base_url=base_url, api_key=SecretStr(secret), model=model)


def _config() -> LocalLiveConfig:
    return LocalLiveConfig(
        weknora_chat=_profile("https://chat.example/v1", "chat-model", "chat-secret"),
        weknora_embedding=_profile(
            "https://embedding.example/v1", "embedding-model", "embedding-secret"
        ),
        weknora_rerank=_profile(
            "https://rerank.example/v1", "rerank-model", "rerank-secret"
        ),
        extraction=_profile(
            "https://bailian.example/v1", "deepseek-v4-flash", "bailian-secret"
        ),
    )


@respx.mock
async def test_r1_1_four_model_roles_are_probed_with_runtime_embedding_dimension() -> None:
    try:
        probe_all_models = import_module(
            "insurance_harness.live_env.model_probe"
        ).probe_all_models
    except ModuleNotFoundError:
        pytest.fail("R1.1 model probes are missing")

    chat = respx.post("https://chat.example/v1/chat/completions").respond(
        json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    )
    embedding = respx.post("https://embedding.example/v1/embeddings").respond(
        json={"data": [{"embedding": [0.1, 0.2, 0.3]}]}
    )
    rerank = respx.post("https://rerank.example/v1/rerank").respond(
        json={"results": [{"index": 1, "relevance_score": 0.9}]}
    )
    extraction = respx.post("https://bailian.example/v1/chat/completions").respond(
        json={
            "choices": [
                {
                    "message": {"content": "probe-ok", "reasoning_content": "private"},
                    "finish_reason": "stop",
                }
            ]
        }
    )

    results = await probe_all_models(_config())

    assert set(results) == {"weknora_chat", "weknora_embedding", "weknora_rerank", "extraction"}
    assert all(result.ok for result in results.values())
    assert results["weknora_embedding"].embedding_dimension == 3
    assert chat.calls[0].request.headers["authorization"] == "Bearer chat-secret"
    assert '"max_tokens":4096' in chat.calls[0].request.content.decode()
    assert embedding.calls[0].request.headers["authorization"] == "Bearer embedding-secret"
    assert rerank.calls[0].request.headers["authorization"] == "Bearer rerank-secret"
    extraction_body = extraction.calls[0].request.content.decode()
    assert '"max_tokens":4096' in extraction_body
    sanitized = repr(results)
    for forbidden in ("secret", "https://", "reasoning_content", "private"):
        assert forbidden not in sanitized


@respx.mock
async def test_r1_1_probe_failure_redacts_url_token_and_response_body() -> None:
    probe_all_models = import_module(
        "insurance_harness.live_env.model_probe"
    ).probe_all_models
    respx.post("https://chat.example/v1/chat/completions").respond(
        status_code=401,
        text="rejected chat-secret at https://private-gateway.example/v1",
    )

    with pytest.raises(Exception, match="weknora_chat probe failed") as failure:
        await probe_all_models(_config())

    message = str(failure.value)
    for forbidden in ("chat-secret", "https://", "private-gateway", "401"):
        assert forbidden not in message


@pytest.mark.parametrize("malformed_role", ["weknora_embedding", "weknora_rerank"])
@respx.mock
async def test_r1_1_probe_rejects_malformed_numeric_provider_shapes(
    malformed_role: str,
) -> None:
    probe_all_models = import_module(
        "insurance_harness.live_env.model_probe"
    ).probe_all_models
    respx.post("https://chat.example/v1/chat/completions").respond(
        json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    )
    embedding_payload: object = [0.1, 0.2]
    if malformed_role == "weknora_embedding":
        embedding_payload = ["not-a-number"]
    respx.post("https://embedding.example/v1/embeddings").respond(
        json={"data": [{"embedding": embedding_payload}]}
    )
    rerank_payload: object = [{"index": 1, "relevance_score": 0.9}]
    if malformed_role == "weknora_rerank":
        rerank_payload = ["index"]
    respx.post("https://rerank.example/v1/rerank").respond(
        json={"results": rerank_payload}
    )

    with pytest.raises(Exception, match=f"{malformed_role} probe failed"):
        await probe_all_models(_config())


def _healthy_non_chat_routes() -> None:
    respx.post("https://embedding.example/v1/embeddings").respond(
        json={"data": [{"embedding": [0.1, 0.2]}]}
    )
    respx.post("https://rerank.example/v1/rerank").respond(
        json={"results": [{"index": 1, "relevance_score": 0.9}]}
    )


@respx.mock
async def test_r1_1_chat_probe_retries_reasoning_length_once() -> None:
    probe_all_models = import_module(
        "insurance_harness.live_env.model_probe"
    ).probe_all_models
    chat = respx.post("https://chat.example/v1/chat/completions").mock(
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
    _healthy_non_chat_routes()
    respx.post("https://bailian.example/v1/chat/completions").respond(
        json={
            "choices": [
                {"message": {"content": "probe-ok"}, "finish_reason": "stop"}
            ]
        }
    )

    await probe_all_models(_config())

    assert chat.call_count == 2


@respx.mock
async def test_r1_1_extraction_probe_retries_reasoning_length_once() -> None:
    probe_all_models = import_module(
        "insurance_harness.live_env.model_probe"
    ).probe_all_models
    respx.post("https://chat.example/v1/chat/completions").respond(
        json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    )
    _healthy_non_chat_routes()
    extraction = respx.post("https://bailian.example/v1/chat/completions").mock(
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
                        {"message": {"content": "probe-ok"}, "finish_reason": "stop"}
                    ]
                },
            ),
        ]
    )

    await probe_all_models(_config())

    assert extraction.call_count == 2
