"""Model probe: single retries for reasoning-length and empty answers."""

from typing import Any

import httpx
import pytest
import respx

from insurance_harness.live_env.model_probe import ModelProbeError, probe_all_models
from tests.service_shell.model_probe.helpers import _config, _healthy_routes


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


def _reply(text: object) -> httpx.Response:
    choice = {"message": {"content": text}, "finish_reason": "stop"}
    return httpx.Response(200, json={"choices": [choice]})


# S7d-1 (#305 R1): like the retired compiler client, an empty answer counts as a length stop:
# retried once, and a failure the second time.
@respx.mock
@pytest.mark.parametrize("empty", ["", " \n", None])
@pytest.mark.parametrize("recovers", [True, False])
async def test_s7d1_extraction_retries_an_empty_answer_once(empty: object, recovers: bool) -> None:
    routes = _healthy_routes()
    routes["extraction"].mock(side_effect=[_reply(empty), _reply("ok" if recovers else empty)])
    if recovers:
        await probe_all_models(_config())
    else:
        with pytest.raises(ModelProbeError, match="extraction probe failed"):
            await probe_all_models(_config())
    assert routes["extraction"].call_count == 2


# S7d-1 (#305 R2): the extraction role keeps the retired client's 180 s budget; others keep 30 s.
@respx.mock
async def test_s7d1_extraction_keeps_its_request_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    _healthy_routes()
    calls: list[tuple[str, object]] = []  # (host the request went to, its client's timeout)
    client = httpx.AsyncClient

    def recording(**kwargs: Any) -> httpx.AsyncClient:
        real = client(**kwargs)
        send = real.post

        async def post(url: str, **rest: Any) -> httpx.Response:
            calls.append((httpx.URL(url).host, kwargs["timeout"]))
            return await send(url, **rest)

        real.post = post  # type: ignore[method-assign, assignment]
        return real

    monkeypatch.setattr(httpx, "AsyncClient", recording)
    await probe_all_models(_config())
    hosts = ["chat.example", "embedding.example", "dashscope.aliyuncs.com", "vlm.example"]
    expected = [(host, 30.0) for host in hosts] + [("bailian.example", 180.0)]
    assert sorted(calls) == sorted(expected)  # each role exactly once, with its own budget
