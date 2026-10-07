"""S4b acceptance: stage-configured OpenAI-compatible completion (blueprint §7.6).

Protected file: written by Claude. Pins §3.2 of the S4b spec.

The completion port is the single retry owner for a model call chain. It
counts every attempt, refuses oversize or over-budget sends before they leave
the process, treats truncation as a configuration error rather than a retry,
and never lets the key, the prompt or the model output into errors or records.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import insurance_harness.models as models_package
from insurance_harness.compilers.schema_fields.engine import SchemaFieldsCompiler
from insurance_harness.models import (
    CallLedger,
    InputTooLarge,
    ModelBudgetExceeded,
    ModelCallError,
    ModelConfigError,
    ModelHTTPError,
    ModelUnavailable,
    OpenAICompatibleCompletion,
    StageModelConfig,
    TruncatedCompletion,
    load_stage_config,
)

KEY = "sk-test-SECRET-123"
PROMPT = "条款原文：等待期90日"
ANSWER = '{"fields": []}'


def config(**overrides: object) -> StageModelConfig:
    data: dict[str, object] = {
        "stage": "schema_fields", "provider": "example", "base_url": "https://api.example.com",
        "model": "example-model", "api_key_env": "TEST_MODEL_KEY", "max_tokens": 8192,
        "policy_version": "test.1",
    }
    return StageModelConfig.model_validate({**data, **overrides})


def ok(content: str = ANSWER, *, finish: str = "stop") -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{
            "message": {"role": "assistant", "content": content, "reasoning_content": "推理过程"},
            "finish_reason": finish,
        }],
        "usage": {
            "prompt_tokens": 1200, "completion_tokens": 300,
            "completion_tokens_details": {"reasoning_tokens": 200},
        },
    })


class Server:
    """Serves queued responses; the string "timeout" raises a read timeout."""

    def __init__(self, *responses: httpx.Response | str) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if item == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        assert isinstance(item, httpx.Response)
        return item


def make(
    server: Server, *, ledger: CallLedger | None = None, sleeps: list[float] | None = None,
    **overrides: object,
) -> OpenAICompatibleCompletion:
    waits = sleeps if sleeps is not None else []
    return OpenAICompatibleCompletion(
        config(**overrides), environ={"TEST_MODEL_KEY": KEY}, ledger=ledger,
        transport=httpx.MockTransport(server), sleep=waits.append,
    )


def outcomes(completion: OpenAICompatibleCompletion) -> list[str]:
    return [record.outcome for record in completion.ledger.records]


# --- configuration -----------------------------------------------------------


@pytest.mark.parametrize("override", [
    {"base_url": "http://api.example.com"},
    {"api_key_env": "sk-live-abc"},
    {"max_tokens": 0},
    {"max_attempts": 6},
    {"temperature": 2.5},
    {"max_input_chars": 0},
    {"thinking": "maybe"},
    {"api_key": KEY},
])
def test_config_rejects_invalid_or_secret_bearing_values(override: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        config(**override)


def test_load_stage_config_selects_one_stage_and_fails_closed(tmp_path: Path) -> None:
    base = config().model_dump()
    path = tmp_path / "stages.json"
    path.write_text(json.dumps({"stages": [base, {**base, "stage": "review"}]}))
    assert load_stage_config(path, "review").stage == "review"
    with pytest.raises(ModelConfigError):
        load_stage_config(path, "missing")
    path.write_text(json.dumps({"stages": [base, base]}))
    with pytest.raises(ModelConfigError):
        load_stage_config(path, "schema_fields")
    path.write_text(json.dumps({"stages": [{**base, "max_tokens": -1}]}))
    with pytest.raises(ModelConfigError):
        load_stage_config(path, "schema_fields")


def test_repository_stage_config_names_deepseek_without_a_key() -> None:
    path = Path(models_package.__file__).parent / "stages.json"
    stage = load_stage_config(path, "schema_fields")
    assert (stage.provider, stage.base_url) == ("deepseek", "https://api.deepseek.com")
    assert stage.api_key_env == "HARNESS_SCHEMA_FIELDS_API_KEY"
    assert "sk-" not in path.read_text(encoding="utf-8")


def test_model_code_has_no_family_branches() -> None:
    sources = Path(models_package.__file__).parent.rglob("*.py")
    assert not any("deepseek" in path.read_text(encoding="utf-8").lower() for path in sources)


def test_missing_key_fails_before_any_request() -> None:
    server = Server()
    with pytest.raises(ModelConfigError):
        OpenAICompatibleCompletion(
            config(), environ={"TEST_MODEL_KEY": "  "}, transport=httpx.MockTransport(server),
        )
    assert server.requests == []


# --- request and response ----------------------------------------------------


def test_sends_the_configured_openai_payload_and_returns_content_only() -> None:
    server = Server(ok(), ok())
    completion = make(
        server, temperature=0.2, thinking="enabled", response_format="json_object",
    )
    assert completion.model == "example-model"
    assert completion.complete(system="规则", user=PROMPT) == ANSWER
    request = server.requests[0]
    assert (request.method, request.url.path) == ("POST", "/chat/completions")
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert body["model"] == "example-model"
    assert body["messages"] == [
        {"role": "system", "content": "规则"}, {"role": "user", "content": PROMPT},
    ]
    assert (body["max_tokens"], body["temperature"]) == (8192, 0.2)
    assert body["thinking"] == {"type": "enabled"}
    assert body["response_format"] == {"type": "json_object"}
    completion.complete(system="规则", user=PROMPT)
    first, second = completion.ledger.records
    assert first.request_sha256 == second.request_sha256
    assert server.requests[0].content == server.requests[1].content


def test_optional_fields_are_omitted_when_not_configured() -> None:
    server = Server(ok())
    make(server).complete(system="规则", user=PROMPT)
    body = json.loads(server.requests[0].content)
    assert "thinking" not in body and "response_format" not in body


def test_success_records_usage_including_reasoning_tokens() -> None:
    completion = make(Server(ok()))
    completion.complete(system="规则", user=PROMPT)
    (record,) = completion.ledger.records
    assert (record.outcome, record.attempt, record.status_code) == ("ok", 1, 200)
    assert (record.prompt_tokens, record.completion_tokens, record.reasoning_tokens) == (
        1200, 300, 200,
    )
    assert (record.stage, record.model, record.policy_version) == (
        "schema_fields", "example-model", "test.1",
    )
    assert record.finish_reason == "stop"
    assert completion.ledger.sent == 1


@pytest.mark.parametrize("response", [ok(finish="length"), ok(content="  ")])
def test_truncated_or_empty_output_is_not_retried(response: httpx.Response) -> None:
    server = Server(response, ok())
    completion = make(server)
    with pytest.raises(TruncatedCompletion):
        completion.complete(system="规则", user=PROMPT)
    assert len(server.requests) == 1
    assert outcomes(completion) == ["truncated"]


# --- retry ownership ---------------------------------------------------------


def test_rate_limit_waits_for_retry_after_then_succeeds() -> None:
    sleeps: list[float] = []
    server = Server(httpx.Response(429, headers={"Retry-After": "7"}), ok())
    completion = make(server, sleeps=sleeps)
    assert completion.complete(system="规则", user=PROMPT) == ANSWER
    assert sleeps == [7]
    assert outcomes(completion) == ["rate_limited", "ok"]
    assert [record.attempt for record in completion.ledger.records] == [1, 2]


def test_retry_after_is_capped() -> None:
    sleeps: list[float] = []
    make(Server(httpx.Response(429, headers={"Retry-After": "600"}), ok()), sleeps=sleeps).complete(
        system="规则", user=PROMPT,
    )
    assert sleeps == [60]


def test_server_errors_back_off_and_stop_at_max_attempts() -> None:
    sleeps: list[float] = []
    server = Server(*(httpx.Response(503) for _ in range(3)), ok())
    completion = make(server, sleeps=sleeps, max_attempts=3)
    with pytest.raises(ModelUnavailable):
        completion.complete(system="规则", user=PROMPT)
    assert len(server.requests) == 3
    assert sleeps == [1, 2]
    assert outcomes(completion) == ["server_error"] * 3


def test_timeouts_are_retried_and_recorded() -> None:
    completion = make(Server("timeout", ok()))
    assert completion.complete(system="规则", user=PROMPT) == ANSWER
    assert outcomes(completion) == ["timeout", "ok"]
    assert completion.ledger.sent == 2


def test_other_client_errors_fail_immediately() -> None:
    sleeps: list[float] = []
    server = Server(httpx.Response(400, json={"error": {"message": PROMPT}}), ok())
    completion = make(server, sleeps=sleeps)
    with pytest.raises(ModelHTTPError):
        completion.complete(system="规则", user=PROMPT)
    assert (len(server.requests), sleeps) == (1, [])
    assert outcomes(completion) == ["http_error"]


# --- limits ------------------------------------------------------------------


def test_oversize_input_is_refused_before_sending() -> None:
    server = Server(ok())
    completion = make(server, max_input_chars=len("规则") + len(PROMPT) - 1)
    with pytest.raises(InputTooLarge):
        completion.complete(system="规则", user=PROMPT)
    assert server.requests == []
    assert outcomes(completion) == ["input_too_large"]
    assert completion.ledger.sent == 0


def test_shared_ledger_enforces_a_run_wide_send_limit() -> None:
    ledger = CallLedger(max_sent=1)
    first_server, second_server = Server(ok()), Server(ok())
    make(first_server, ledger=ledger).complete(system="规则", user=PROMPT)
    second = make(second_server, ledger=ledger)
    with pytest.raises(ModelBudgetExceeded):
        second.complete(system="规则", user=PROMPT)
    assert second_server.requests == []
    assert [record.outcome for record in ledger.records] == ["ok", "budget_exceeded"]
    assert ledger.sent == 1


def test_retries_also_respect_the_send_limit() -> None:
    ledger = CallLedger(max_sent=2)
    server = Server(httpx.Response(503), httpx.Response(503), ok())
    completion = make(server, ledger=ledger, max_attempts=5)
    with pytest.raises(ModelBudgetExceeded):
        completion.complete(system="规则", user=PROMPT)
    assert len(server.requests) == 2
    assert outcomes(completion) == ["server_error", "server_error", "budget_exceeded"]


# --- secrecy and integration -------------------------------------------------


@pytest.mark.parametrize("response", [
    httpx.Response(401, text=f"bad key {KEY} for {PROMPT}"),
    ok(content=PROMPT, finish="length"),
])
def test_errors_and_records_never_contain_key_prompt_or_output(response: httpx.Response) -> None:
    completion = make(Server(response))
    with pytest.raises(ModelCallError) as caught:
        completion.complete(system="规则", user=PROMPT)
    message = str(caught.value)
    records = json.dumps([record.model_dump(mode="json") for record in completion.ledger.records],
                         ensure_ascii=False)
    for secret in (KEY, PROMPT):
        assert secret not in message
        assert secret not in records


def test_completion_plugs_into_the_field_compiler() -> None:
    completion = make(Server())
    SchemaFieldsCompiler(completion, batch_size=25, max_calls=1)
    completion.close()
