"""Process-local shared send budget and immutable attempt records."""

from __future__ import annotations

from threading import Lock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Outcome = Literal[
    "ok", "truncated", "http_error", "rate_limited", "server_error", "timeout",
    "transport_error", "input_too_large", "budget_exceeded",
]


class CallRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    stage: str
    model: str
    policy_version: str
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempt: int = Field(ge=1)
    outcome: Outcome
    status_code: int | None = None
    latency_ms: int = Field(default=0, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    finish_reason: str | None = None
    # Floating model aliases resolve server-side; quality numbers must name the served version.
    served_model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:/-]{1,128}$")
    # The digest of the answer an "ok" call returned, never the answer: a caller that keeps the
    # answer can show it is the one this call received (SK-2c).
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CallLedger:
    """Reserve immediately before transport entry so concurrent callers cannot overspend.

    Records are appended on completion, so concurrent completion order can differ
    from send order. Persistence and recovery belong to the calling run owner.
    """

    def __init__(self, *, max_sent: int | None = None) -> None:
        if max_sent is not None and (type(max_sent) is not int or max_sent < 0):
            raise ValueError("max_sent must be a non-negative integer")
        self._max_sent = max_sent
        self._sent = 0
        self._records: list[CallRecord] = []
        self._lock = Lock()

    @property
    def max_sent(self) -> int | None:
        return self._max_sent

    @property
    def records(self) -> tuple[CallRecord, ...]:
        with self._lock:
            return tuple(self._records)

    @property
    def sent(self) -> int:
        with self._lock:
            return self._sent

    def reserve_send(self) -> bool:
        with self._lock:
            if self._max_sent is not None and self._sent >= self._max_sent:
                return False
            self._sent += 1
            return True

    def append(self, record: CallRecord) -> None:
        with self._lock:
            self._records.append(record)
