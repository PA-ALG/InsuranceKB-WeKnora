"""Synchronous, stage-configured completion with one bounded retry owner."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx

from .config import StageModelConfig
from .errors import (
    InputTooLarge,
    ModelBudgetExceeded,
    ModelCallError,
    ModelConfigError,
    ModelHTTPError,
    ModelUnavailable,
    TruncatedCompletion,
)
from .ledger import CallLedger, CallRecord, Outcome


@dataclass
class _Response:
    outcome: Outcome = "http_error"
    content: str | None = None  # the answer of an "ok" response
    text: str | None = None  # the answer text the response carried, a cut-off one too
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    served_model: str | None = None


_SERVED_MODEL = re.compile(r"[A-Za-z0-9._:/-]{1,128}")


def _tokens(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _parse_response(response: httpx.Response) -> _Response:
    parsed = _Response()
    try:
        body = response.json()
    except ValueError:
        return parsed
    if not isinstance(body, dict):
        return parsed
    served = body.get("model")
    # Only a plain identifier may enter the ledger; arbitrary text could echo inputs.
    if isinstance(served, str) and _SERVED_MODEL.fullmatch(served):
        parsed.served_model = served
    usage = body.get("usage")
    if isinstance(usage, dict):
        parsed.prompt_tokens = _tokens(usage.get("prompt_tokens"))
        parsed.completion_tokens = _tokens(usage.get("completion_tokens"))
        details = usage.get("completion_tokens_details")
        if isinstance(details, dict):
            parsed.reasoning_tokens = _tokens(details.get("reasoning_tokens"))
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return parsed
    choice = choices[0]
    finish = choice.get("finish_reason")
    # Only protocol values may enter the ledger; unknown text could echo inputs.
    if isinstance(finish, str) and finish in {
        "stop", "length", "content_filter", "tool_calls", "function_call",
        "insufficient_system_resource", "aborted",
    }:
        parsed.finish_reason = finish
    if finish == "insufficient_system_resource":
        # A provider-side capacity shortage is transient, unlike a budget truncation.
        parsed.outcome = "server_error"
        return parsed
    message = choice.get("message")
    if not isinstance(message, dict):
        return parsed
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        return parsed
    parsed.text = content or None
    # Blueprint §7.1 rejects every non-stop finish, not only length exhaustion.
    if finish != "stop" or content is None or not content.strip():
        parsed.outcome = "truncated"
    else:
        parsed.outcome, parsed.content = "ok", content
    return parsed


def request_body(config: StageModelConfig, *, system: str, user: str) -> bytes:
    """The exact chat request body the client sends for this stage and these messages."""
    payload: dict[str, object] = {
        "model": config.model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": config.max_tokens, "temperature": config.temperature,
    }
    if config.thinking is not None:
        thinking: dict[str, str] = {"type": config.thinking}
        if config.reasoning_effort is not None:
            thinking["reasoning_effort"] = config.reasoning_effort
        payload["thinking"] = thinking
    if config.response_format is not None:
        payload["response_format"] = {"type": config.response_format}
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def request_sha256(config: StageModelConfig, *, system: str, user: str) -> str:
    """The request digest the ledger records for this request, computed without sending it."""
    return hashlib.sha256(request_body(config, system=system, user=user)).hexdigest()


def _retry_delay(header: str | None, attempt: int) -> float:
    if header is not None:
        try:
            seconds = float(header)
            if math.isfinite(seconds) and seconds >= 0:
                return min(seconds, 60.0)
        except ValueError:
            pass
    return float(min(2 ** (attempt - 1), 30))


class OpenAICompatibleCompletion:
    """The transport performs no automatic retries; this adapter owns all attempts.

    `keep`, when given, receives every answer text a response carries (a cut-off one too) before
    the call returns or raises, after its attempt record has been appended: a caller keeping raw
    output in its private run root sees what a truncation discarded. Errors never carry it.
    """

    def __init__(
        self, config: StageModelConfig, *, environ: Mapping[str, str] | None = None,
        ledger: CallLedger | None = None, transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep, keep: Callable[[str], None] | None = None,
    ) -> None:
        self._config, self._keep = config, keep
        key = (os.environ if environ is None else environ).get(config.api_key_env, "")
        if not key.strip() or not key.isascii() or any(char.isspace() for char in key):
            raise self._error(ModelConfigError, "config_error")
        self._ledger = ledger if ledger is not None else CallLedger()
        self._sleep = sleep
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=config.timeout_s, trust_env=False, transport=transport, follow_redirects=False,
        )

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def ledger(self) -> CallLedger:
        return self._ledger

    def _error(
        self, kind: type[ModelCallError], outcome: str, status_code: int | None = None,
    ) -> ModelCallError:
        return kind(outcome, stage=self._config.stage, model=self.model, status_code=status_code)

    def _record(
        self, digest: str, attempt: int, result: _Response, *, status_code: int | None = None,
        latency_ms: int = 0,
    ) -> CallRecord:
        record = CallRecord(
            stage=self._config.stage, model=self.model, policy_version=self._config.policy_version,
            request_sha256=digest, attempt=attempt, outcome=result.outcome, status_code=status_code,
            latency_ms=latency_ms, prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens, reasoning_tokens=result.reasoning_tokens,
            finish_reason=result.finish_reason, served_model=result.served_model,
            response_sha256=(
                hashlib.sha256(result.content.encode("utf-8")).hexdigest()
                if result.outcome == "ok" and result.content is not None else None
            ),
        )
        self._ledger.append(record)
        return record

    def _send(self, body: bytes, digest: str, attempt: int) -> tuple[_Response, int | None, float]:
        started = time.monotonic()
        result = _Response(outcome="transport_error")
        status_code: int | None = None
        retry_after: str | None = None
        try:
            response = self._client.post(
                f"{self._config.base_url.rstrip('/')}/chat/completions", content=body,
            )
            status_code = response.status_code
            retry_after = response.headers.get("Retry-After")
            if status_code == 200:
                result = _parse_response(response)
            elif status_code == 429:
                result.outcome = "rate_limited"
            elif 500 <= status_code <= 599:
                result.outcome = "server_error"
            else:
                result.outcome = "http_error"
        except httpx.TimeoutException:
            result.outcome = "timeout"
        except httpx.RequestError:
            result.outcome = "transport_error"
        except Exception:
            # Unexpected local transport errors must not expose credentials or retry blindly.
            raise self._error(ModelUnavailable, "transport_error") from None
        finally:
            self._record(
                digest, attempt, result, status_code=status_code,
                latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            )
        return result, status_code, _retry_delay(retry_after, attempt)

    def complete(self, *, system: str, user: str) -> str:
        config = self._config
        body = request_body(config, system=system, user=user)
        digest = hashlib.sha256(body).hexdigest()
        if config.max_input_chars is not None and len(system) + len(user) > config.max_input_chars:
            self._record(digest, 1, _Response(outcome="input_too_large"))
            raise self._error(InputTooLarge, "input_too_large")
        if self._client.is_closed:
            raise self._error(ModelConfigError, "config_error")
        for attempt in range(1, config.max_attempts + 1):
            if not self._ledger.reserve_send():
                self._record(digest, attempt, _Response(outcome="budget_exceeded"))
                raise self._error(ModelBudgetExceeded, "budget_exceeded")
            result, status, delay = self._send(body, digest, attempt)
            if result.text is not None and self._keep is not None:
                self._keep(result.text)
            if result.outcome == "ok":
                assert result.content is not None
                return result.content
            if result.outcome == "truncated":
                raise self._error(TruncatedCompletion, result.outcome, status)
            if result.outcome == "http_error":
                raise self._error(ModelHTTPError, result.outcome, status)
            if attempt == config.max_attempts:
                raise self._error(ModelUnavailable, result.outcome, status)
            self._sleep(delay)
        raise AssertionError("validated attempt bound is positive")

    def close(self) -> None:
        self._client.close()
