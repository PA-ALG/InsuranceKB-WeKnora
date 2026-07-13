"""compiler/llm.py：OpenAI 兼容客户端（推理型模型约定）与调用统计。"""

import httpx
import pytest
import respx

from insurance_harness.compiler.llm import (
    CallStats,
    MeteredClient,
    OpenAICompatClient,
    TruncatedOutputError,
)

BASE = "https://gateway.test/compatible-mode/v1"


def _client() -> OpenAICompatClient:
    return OpenAICompatClient(
        base_url=BASE, api_key="sk-test", model="deepseek-v4-flash", max_tokens=4096
    )


def _payload(content: str | None, finish: str, reasoning: str = "") -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {"content": content, "reasoning_content": reasoning},
                "finish_reason": finish,
            }
        ]
    }


@respx.mock
async def test_reasoning_content_is_ignored_only_content_returned() -> None:
    route = respx.post(f"{BASE}/chat/completions").respond(
        json=_payload('[{"field_id": "x"}]', "stop", reasoning="长篇推理过程……")
    )
    out = await _client().complete("sys", "user")
    assert out == '[{"field_id": "x"}]'
    import json

    body = json.loads(route.calls[0].request.content.decode())
    assert body["max_tokens"] == 4096  # 推理型模型必须给足 max_tokens
    assert route.calls[0].request.headers["authorization"] == "Bearer sk-test"


@respx.mock
async def test_empty_content_finish_length_raises_truncated() -> None:
    respx.post(f"{BASE}/chat/completions").respond(
        json=_payload("", "length", reasoning="推理耗尽了全部 token")
    )
    with pytest.raises(TruncatedOutputError, match="finish_reason=length"):
        await _client().complete("sys", "user")


@respx.mock
async def test_http_error_propagates_for_retry_layer() -> None:
    respx.post(f"{BASE}/chat/completions").respond(status_code=503)
    with pytest.raises(httpx.HTTPStatusError):
        await _client().complete("sys", "user")


async def test_metered_client_records_stats() -> None:
    class Echo:
        async def complete(self, system: str, user: str) -> str:
            return "回答内容"

    stats = CallStats()
    client = MeteredClient(Echo(), stats)
    await client.complete("系统", "用户输入")
    await client.complete("系统", "另一个输入")
    assert stats.calls == 2
    assert stats.prompt_chars == len("系统用户输入") + len("系统另一个输入")
    assert stats.completion_chars == 2 * len("回答内容")
    assert stats.est_tokens > 0
