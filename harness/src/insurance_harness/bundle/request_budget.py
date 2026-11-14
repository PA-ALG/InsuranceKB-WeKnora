"""Timeout and decoded response size budgets for publishing requests."""

import os
import re
from dataclasses import dataclass
from enum import Enum, auto

import httpx

DEFAULT_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 32 << 20
RECEIPT_RESPONSE_BYTES = 64 << 10
ACTIVATION_TIMEOUT_ENV = "HARNESS_WEKNORA_ACTIVATION_READ_TIMEOUT_SECONDS"
RELEASE_LIMIT_ENV = "HARNESS_WEKNORA_RELEASE_MAX_RESPONSE_MIB"


class RequestType(Enum):
    CONTROL = auto()
    FULL_RELEASE = auto()
    ACTIVATE = auto()
    ACTIVATE_RECEIPT = auto()
    RECEIPT = auto()


@dataclass(frozen=True)
class RequestBudgets:
    activate_read_seconds: int
    release_max_bytes: int

    @classmethod
    def from_env(cls) -> "RequestBudgets":
        return cls(
            _setting(ACTIVATION_TIMEOUT_ENV, 30, 180),
            _setting(RELEASE_LIMIT_ENV, 32, 128) << 20,
        )

    def timeout(self, request_type: RequestType) -> httpx.Timeout:
        read = (
            self.activate_read_seconds
            if request_type in {RequestType.ACTIVATE, RequestType.ACTIVATE_RECEIPT}
            else DEFAULT_TIMEOUT_SECONDS
        )
        return httpx.Timeout(DEFAULT_TIMEOUT_SECONDS, read=read)

    def response_limit(self, request_type: RequestType) -> int:
        if request_type in {RequestType.FULL_RELEASE, RequestType.ACTIVATE}:
            return self.release_max_bytes
        if request_type in {RequestType.ACTIVATE_RECEIPT, RequestType.RECEIPT}:
            return RECEIPT_RESPONSE_BYTES
        return MAX_RESPONSE_BYTES


def _setting(name: str, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return minimum
    if not re.fullmatch(r"[1-9][0-9]{0,2}", raw):
        raise ValueError("invalid publishing request budget")
    number = int(raw)
    if not minimum <= number <= maximum:
        raise ValueError("invalid publishing request budget")
    return number
