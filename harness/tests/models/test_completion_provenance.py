"""SK-2c Spec r3 §3.1, §5 (RED, written by Claude, review #526 R1, R4): what the completion client
records and hands back so a caller can bind a kept answer to its call.

- `request_sha256(config, system, user)` is the digest the ledger records for that exact request
  body, so a caller can find the record of a request without sending it again;
- an answered call's record holds the digest of the answer it returned (`response_sha256`), never
  the answer;
- `keep` receives every answer text a response carried, a cut-off one too, before the call returns
  or raises; nothing else ever sees it (errors stay metadata-only).
"""

import hashlib

import httpx
import pytest

from insurance_harness.models import (
    CallLedger,
    ModelHTTPError,
    OpenAICompatibleCompletion,
    StageModelConfig,
    TruncatedCompletion,
)
from insurance_harness.models.openai_compatible import request_sha256

KEY = "sk-test-SECRET-123"
ANSWER = '{"predicates": []}'


def config(**overrides: object) -> StageModelConfig:
    data: dict[str, object] = {
        "stage": "methods", "provider": "example", "base_url": "https://api.example.com",
        "model": "example-model", "api_key_env": "TEST_MODEL_KEY", "max_tokens": 1000,
        "max_attempts": 1, "policy_version": "test.1",
    }
    return StageModelConfig.model_validate({**data, **overrides})


def reply(content: str = ANSWER, finish: str = "stop") -> httpx.Response:
    return httpx.Response(200, json={
        "model": "example-model-2026",
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
    })


def client(
    response: httpx.Response, kept: list[str] | None = None, **overrides: object
) -> OpenAICompatibleCompletion:
    return OpenAICompatibleCompletion(
        config(**overrides), environ={"TEST_MODEL_KEY": KEY}, ledger=CallLedger(),
        transport=httpx.MockTransport(lambda _: response), sleep=lambda _: None,
        keep=None if kept is None else kept.append,
    )


def test_the_recorded_request_digest_can_be_recomputed_without_sending() -> None:
    completion = client(reply(), temperature=0.5, response_format="json_object")
    completion.complete(system="系统", user="用户")
    (record,) = completion.ledger.records
    expected = request_sha256(
        config(temperature=0.5, response_format="json_object"), system="系统", user="用户"
    )
    assert record.request_sha256 == expected
    assert request_sha256(config(temperature=0.6), system="系统", user="用户") != expected


def test_an_answered_record_holds_the_digest_of_its_answer_only() -> None:
    completion = client(reply())
    assert completion.complete(system="s", user="u") == ANSWER
    (record,) = completion.ledger.records
    assert record.response_sha256 == hashlib.sha256(ANSWER.encode("utf-8")).hexdigest()
    assert ANSWER not in record.model_dump_json()


def test_keep_receives_every_answer_text_a_cut_off_one_too() -> None:
    kept: list[str] = []
    assert client(reply(), kept).complete(system="s", user="u") == ANSWER
    with pytest.raises(TruncatedCompletion) as raised:
        client(reply('{"predicates": [', finish="length"), kept).complete(system="s", user="u")
    assert kept == [ANSWER, '{"predicates": [']
    assert "predicates" not in str(raised.value)  # errors stay metadata-only


def test_keep_sees_nothing_without_an_answer_text() -> None:
    kept: list[str] = []
    with pytest.raises(ModelHTTPError):
        client(httpx.Response(400), kept).complete(system="s", user="u")
    assert kept == []
