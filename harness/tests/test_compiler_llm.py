"""compiler/llm.py：OpenAI 兼容客户端（推理型模型约定）与调用统计。"""

import httpx
import pytest
import respx

from insurance_harness.compiler.llm import (
    CallStats,
    MeteredClient,
    OpenAICompatClient,
    TruncatedOutputError,
    openai_compat_request_bytes,
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
async def test_nonempty_content_finish_length_raises_truncated() -> None:
    respx.post(f"{BASE}/chat/completions").respond(
        json=_payload('{"partial":true}', "length", reasoning="truncated")
    )
    with pytest.raises(TruncatedOutputError, match="finish_reason=length"):
        await _client().complete("sys", "user")


@respx.mock
async def test_http_error_propagates_for_retry_layer() -> None:
    respx.post(f"{BASE}/chat/completions").respond(status_code=503)
    with pytest.raises(httpx.HTTPStatusError):
        await _client().complete("sys", "user")


@respx.mock
async def test_explicit_thinking_mode_is_serialized_in_exact_http_body() -> None:
    route = respx.post(f"{BASE}/chat/completions").respond(
        json=_payload('{"ok":true}', "stop")
    )
    client = OpenAICompatClient(
        base_url=BASE,
        api_key="sk-test",
        model="deepseek-v4-flash",
        temperature=0.0,
        max_tokens=8192,
        thinking="disabled",
    )

    assert await client.complete("sys", "user") == '{"ok":true}'
    expected = openai_compat_request_bytes(
        model="deepseek-v4-flash",
        temperature=0.0,
        max_tokens=8192,
        system="sys",
        user="user",
        thinking="disabled",
    )
    assert route.calls[0].request.content == expected
    assert b'"thinking":{"type":"disabled"}' in expected
    await client.aclose()


def test_default_request_remains_compatible_without_thinking_field() -> None:
    body = openai_compat_request_bytes(
        model="legacy-compatible-model",
        temperature=0.1,
        max_tokens=4096,
        system="sys",
        user="user",
    )
    assert b'"thinking"' not in body
    assert b'"response_format"' not in body
    assert body == (
        b'{"model":"legacy-compatible-model","temperature":0.1,'
        b'"max_tokens":4096,"messages":[{"role":"system","content":"sys"},'
        b'{"role":"user","content":"user"}]}'
    )


@respx.mock
async def test_json_object_response_format_is_exact_http_body() -> None:
    route = respx.post(f"{BASE}/chat/completions").respond(
        json=_payload('{"ok":true}', "stop")
    )
    client = OpenAICompatClient(
        base_url=BASE,
        api_key="sk-test",
        model="deepseek-v4-flash",
        temperature=0.0,
        max_tokens=8192,
        thinking="disabled",
        response_format="json_object",
    )

    assert await client.complete("sys", "user") == '{"ok":true}'
    expected = openai_compat_request_bytes(
        model="deepseek-v4-flash",
        temperature=0.0,
        max_tokens=8192,
        system="sys",
        user="user",
        thinking="disabled",
        response_format="json_object",
    )
    assert route.calls[0].request.content == expected
    assert expected == (
        b'{"model":"deepseek-v4-flash","temperature":0.0,"max_tokens":8192,'
        b'"thinking":{"type":"disabled"},'
        b'"response_format":{"type":"json_object"},'
        b'"messages":[{"role":"system","content":"sys"},'
        b'{"role":"user","content":"user"}]}'
    )
    await client.aclose()


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
