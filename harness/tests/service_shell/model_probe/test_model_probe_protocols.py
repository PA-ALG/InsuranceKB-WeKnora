"""Model probe: proxy isolation, packaged VLM canary and the five role protocols."""

import base64
import json
from importlib.resources import files

import httpx
import pytest
import respx

import insurance_harness.live_env.model_probe as model_probe
from insurance_harness.live_env.model_probe import probe_all_models
from tests.service_shell.model_probe.helpers import (
    CHAT_PROMPT,
    EMBEDDING_INPUT,
    EXTRACTION_SYSTEM,
    EXTRACTION_USER,
    RERANK_DOCUMENTS,
    RERANK_QUERY,
    VLM_CANARY,
    VLM_PROMPT,
    _config,
    _healthy_routes,
    _profile,
)


def _packaged_canary_bytes() -> bytes:
    resource = files("insurance_harness.live_env").joinpath(
        "fixtures", "vlm-canary.png"
    )
    assert resource.is_file(), "R1.2 packaged VLM canary is missing"
    return resource.read_bytes()


async def test_r1_2_model_probe_http_client_ignores_shell_proxy_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructor: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"ok": True}

    class Client:
        def __init__(self, **kwargs: object) -> None:
            constructor.update(kwargs)

        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *args: object) -> None:
            del args

        async def post(
            self, url: str, *, json: dict[str, object]
        ) -> Response:
            del url, json
            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", Client)

    document = await model_probe._post(
        _profile("https://chat.example/v1", "chat-model", "chat-secret"),
        "https://chat.example/v1/chat/completions",
        {"model": "chat-model"},
    )

    assert document == {"ok": True}
    assert constructor["trust_env"] is False


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
