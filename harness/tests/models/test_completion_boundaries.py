"""Offline transport, metering and confidentiality edge cases."""

import hashlib
import json
import traceback
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest

from insurance_harness.models import (
    CallLedger,
    ModelBudgetExceeded,
    ModelHTTPError,
    ModelUnavailable,
    OpenAICompatibleCompletion,
    StageModelConfig,
    TruncatedCompletion,
)

SECRET = "private-response-and-key"


def config(**changes: object) -> StageModelConfig:
    return StageModelConfig.model_validate({
        "stage": "extract", "provider": "example", "base_url": "https://example.com/v1/",
        "model": "test-model", "api_key_env": "MODEL_KEY", "max_tokens": 2048,
        "policy_version": "test.1", **changes,
    })


def response(**changes: object) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{
        "message": {"content": "{}"}, "finish_reason": "stop", **changes,
    }]})


@pytest.mark.parametrize("header, expected", [
    ("bad", 1), ("-1", 1), ("NaN", 1), ("Infinity", 1), ("0", 0), ("0.5", 0.5),
])
def test_retry_after_invalid_values_use_finite_backoff(header: str, expected: float) -> None:
    responses = iter([httpx.Response(429, headers={"Retry-After": header}), response()])
    waits: list[float] = []
    client = OpenAICompatibleCompletion(
        config(), environ={"MODEL_KEY": SECRET},
        transport=httpx.MockTransport(lambda _: next(responses)), sleep=waits.append,
    )
    assert client.complete(system="rules", user="input") == "{}"
    assert waits == [expected]
    client.close()


def test_transport_failures_exhaust_attempts_without_leaking_exception() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(SECRET, request=request)

    waits: list[float] = []
    client = OpenAICompatibleCompletion(
        config(max_attempts=2), environ={"MODEL_KEY": SECRET},
        transport=httpx.MockTransport(fail), sleep=waits.append,
    )
    with pytest.raises(ModelUnavailable) as caught:
        client.complete(system=SECRET, user=SECRET)
    assert SECRET not in "".join(traceback.format_exception(caught.value))
    assert [r.outcome for r in client.ledger.records] == ["transport_error"] * 2
    assert client.ledger.sent == 2
    assert waits == [1]
    client.close()


@pytest.mark.parametrize("payload", [
    None, [], {"choices": []}, {"choices": [None]},
    {"choices": [{"message": {"content": [SECRET]}, "finish_reason": "stop"}]},
    {"choices": [{"message": SECRET}]},
])
def test_malformed_success_is_metered_once_and_fails_closed(payload: object) -> None:
    waits: list[float] = []
    client = OpenAICompatibleCompletion(
        config(), environ={"MODEL_KEY": SECRET},
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=json.dumps(payload))),
        sleep=waits.append,
    )
    with pytest.raises(ModelHTTPError) as caught:
        client.complete(system=SECRET, user=SECRET)
    assert SECRET not in str(caught.value)
    assert [r.outcome for r in client.ledger.records] == ["http_error"]
    assert client.ledger.sent == 1
    assert not waits
    client.close()


@pytest.mark.parametrize("finish", ["tool_calls", "content_filter", SECRET, None])
def test_non_stop_finish_cannot_be_accepted_or_echoed(finish: str | None) -> None:
    client = OpenAICompatibleCompletion(
        config(), environ={"MODEL_KEY": SECRET},
        transport=httpx.MockTransport(lambda _: response(finish_reason=finish)),
        sleep=lambda _: None,
    )
    with pytest.raises(TruncatedCompletion):
        client.complete(system="rules", user="input")
    (record,) = client.ledger.records
    assert SECRET not in record.model_dump_json()
    assert record.outcome == "truncated"
    client.close()


def test_hash_matches_sent_bytes_usage_is_optional_and_input_boundary_is_inclusive() -> None:
    requests: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response()

    client = OpenAICompatibleCompletion(
        config(max_input_chars=2), environ={"MODEL_KEY": SECRET},
        transport=httpx.MockTransport(serve), sleep=lambda _: None,
    )
    assert client.complete(system="规", user="文") == "{}"
    (record,) = client.ledger.records
    assert record.request_sha256 == hashlib.sha256(requests[0].content).hexdigest()
    assert record.prompt_tokens is record.completion_tokens is record.reasoning_tokens is None
    assert record.latency_ms >= 0
    assert requests[0].url.path == "/v1/chat/completions"
    client.close()


def test_shared_limit_counts_inflight_send_before_another_client_can_start() -> None:
    started, release = Event(), Event()
    ledger = CallLedger(max_sent=1)

    def serve(request: httpx.Request) -> httpx.Response:
        started.set()
        assert release.wait(5)
        return response()

    first = OpenAICompatibleCompletion(
        config(), environ={"MODEL_KEY": SECRET}, ledger=ledger,
        transport=httpx.MockTransport(serve), sleep=lambda _: None,
    )
    second = OpenAICompatibleCompletion(
        config(), environ={"MODEL_KEY": SECRET}, ledger=ledger,
        transport=httpx.MockTransport(lambda _: pytest.fail("must not send")), sleep=lambda _: None,
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(first.complete, system="s", user="u")
        try:
            assert started.wait(5)
            assert ledger.sent == 1
            with pytest.raises(ModelBudgetExceeded):
                second.complete(system="s", user="u")
        finally:
            release.set()
        assert future.result(timeout=5) == "{}"
    assert sorted(r.outcome for r in ledger.records) == ["budget_exceeded", "ok"]
    first.close()
    second.close()


def test_cancellation_accounts_for_sent_attempt_without_retrying() -> None:
    def interrupt(request: httpx.Request) -> httpx.Response:
        raise KeyboardInterrupt

    waits: list[float] = []
    client = OpenAICompatibleCompletion(
        config(), environ={"MODEL_KEY": SECRET},
        transport=httpx.MockTransport(interrupt), sleep=waits.append,
    )
    with pytest.raises(KeyboardInterrupt):
        client.complete(system="s", user="u")
    assert client.ledger.sent == len(client.ledger.records) == 1
    assert client.ledger.records[0].outcome == "transport_error"
    assert waits == []
    client.close()


def test_proxy_environment_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.invalid")
    monkeypatch.setenv("NO_PROXY", "")
    client = OpenAICompatibleCompletion(
        config(), environ={"MODEL_KEY": SECRET},
        transport=httpx.MockTransport(lambda _: response()), sleep=lambda _: None,
    )
    assert client.complete(system="s", user="u") == "{}"
    client.close()


def test_redirect_is_not_followed_and_zero_budget_never_sends() -> None:
    requests: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(307, headers={"Location": "https://redirect.invalid/"})

    transport = httpx.MockTransport(serve)
    refused = OpenAICompatibleCompletion(
        config(), environ={"MODEL_KEY": SECRET}, ledger=CallLedger(max_sent=0),
        transport=transport, sleep=lambda _: None,
    )
    with pytest.raises(ModelBudgetExceeded):
        refused.complete(system="s", user="u")
    assert not requests
    refused.close()
    client = OpenAICompatibleCompletion(
        config(), environ={"MODEL_KEY": SECRET},
        transport=httpx.MockTransport(serve), sleep=lambda _: None,
    )
    with pytest.raises(ModelHTTPError):
        client.complete(system="s", user="u")
    assert len(requests) == client.ledger.sent == 1
    assert client.ledger.records[0].status_code == 307
    client.close()


def test_truncated_response_still_records_usage_but_never_reasoning_text() -> None:
    client = OpenAICompatibleCompletion(
        config(), environ={"MODEL_KEY": SECRET},
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
            "choices": [{"message": {"content": "", "reasoning_content": SECRET},
                         "finish_reason": "length"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2048,
                      "completion_tokens_details": {"reasoning_tokens": 2048}},
        })), sleep=lambda _: None,
    )
    with pytest.raises(TruncatedCompletion):
        client.complete(system="s", user="u")
    (record,) = client.ledger.records
    assert (record.prompt_tokens, record.completion_tokens, record.reasoning_tokens) == (
        10, 2048, 2048,
    )
    assert SECRET not in record.model_dump_json()
    client.close()
