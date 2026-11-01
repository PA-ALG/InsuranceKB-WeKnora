"""Shared SK-2c test data (written by Claude): a fake model provider behind the real client.

The provider answers the OpenAI-compatible chat request the real completion client sends, so the
tests exercise the real ledger, budget and attempt accounting; only the network is fake. Answers
come from the SK-2 helpers' invented materials; no private sample text is used.
"""

import json
from collections.abc import Callable, Mapping
from typing import Any

import httpx
import pytest

from insurance_harness.compilers.methods import values as values_module
from insurance_harness.models import OpenAICompatibleCompletion, StageModelConfig

KEY_ENV = "TEST_METHOD_MODEL_KEY"
SERVED = "served-model-1"

# A method name maps to an answer function of the request payload, or to one of these behaviours.
TRUNCATED, SERVER_ERROR = "truncated", "server_error"
Behaviour = Callable[[dict[str, Any]], dict[str, Any]] | str


def stage_config(**override: Any) -> StageModelConfig:
    fields: dict[str, Any] = {
        "stage": "methods",
        "provider": "test",
        "base_url": "https://model.invalid/v1",
        "model": "test-model",
        "api_key_env": KEY_ENV,
        "max_tokens": 1000,
        "max_attempts": 1,
        "response_format": "json_object",
        "policy_version": "method-test.1",
    }
    fields.update(override)
    return StageModelConfig.model_validate(fields)


class FakeProvider:
    """Answers each method's request by its name; a method without an entry gets non-JSON text."""

    def __init__(self, answers: Mapping[str, Behaviour], served: str = SERVED) -> None:
        self.answers = dict(answers)
        self.served = served
        self.calls: list[str] = []  # the method names sent, in order
        self.bodies: list[bytes] = []  # the request bodies, in order

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(request.content)
        body = json.loads(request.content)
        payload = json.loads(body["messages"][1]["content"])
        name = payload["method"]["name"]
        self.calls.append(name)
        behaviour = self.answers.get(name)
        if behaviour == SERVER_ERROR:
            return httpx.Response(500)
        finish = "length" if behaviour == TRUNCATED else "stop"
        if callable(behaviour):
            content = json.dumps(behaviour(payload), ensure_ascii=False)
        else:
            content = "not json" if behaviour is None else TRUNCATED_TEXT
        return httpx.Response(
            200,
            json={
                "model": self.served,
                "choices": [{"finish_reason": finish, "message": {"content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )


def install(monkeypatch: pytest.MonkeyPatch, provider: FakeProvider | None) -> list[int]:
    """Route the value stage's model client to `provider`; with None, creating one fails the test.

    Returns a list that gains one entry per client created.
    """
    created: list[int] = []

    def factory(config: StageModelConfig, *, ledger: Any, keep: Any = None) -> Any:
        assert provider is not None, "no model client may be created"
        created.append(1)
        return OpenAICompatibleCompletion(  # the real client; a second install must not wrap
            config,
            ledger=ledger,
            keep=keep,
            environ={KEY_ENV: "test-only"},
            transport=httpx.MockTransport(provider),
            sleep=lambda _: None,
        )

    monkeypatch.setattr(values_module, "OpenAICompatibleCompletion", factory)
    return created


TRUNCATED_TEXT = "{"  # what FakeProvider returns, cut off, for a TRUNCATED method


def answered(
    monkeypatch: pytest.MonkeyPatch,
    world: Any,
    items: Any,
    root: Any,
    answers: Mapping[str, Behaviour],
    **provider: Any,
) -> dict[str, Any]:
    """A value directory written the way the pilot writes it: `methods values` on a (fake) model."""
    from tests.compilers.methods.helpers import candidates_of

    install(monkeypatch, FakeProvider(answers, **provider))
    return values_module.method_values(
        world.registry,
        candidates_of(world, items),
        pages=world.reader,
        root=root,
        config=stage_config(),
        max_sent=10,
    )
