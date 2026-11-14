"""Strict JSON and caller-safe failures for the platform response boundary."""

import json
import re

from pydantic import BaseModel, ValidationError

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_PLATFORM_CODES = frozenset(
    {
        "CANDIDATE_INVALID",
        "CANDIDATE_NOT_FOUND",
        "CANDIDATE_NOT_APPROVED",
        "DECISION_INVALID",
        "DECISION_NOT_FOUND",
        "NEEDS_REBASE",
        "RELEASE_ACCESS_DENIED",
        "RELEASE_CONFLICT",
        "RELEASE_NOT_FOUND",
        "SERVICE_UNAVAILABLE",
        "INTERNAL_ERROR",
        # Evidence and source checks a candidate or activation can fail on
        "EVIDENCE_MISMATCH",
        "EVIDENCE_NOT_FOUND",
        "EVIDENCE_UNSUPPORTED",
        "EVIDENCE_UNVERIFIABLE",
        "SOURCE_UNAVAILABLE",
        "RELEASE_ACTIVE",
        "RETIREMENT_INVALID",
        # RV4 spot checks
        "MEMBER_NOT_FOUND",
        "SAMPLE_INVALID",
        "SAMPLE_NOT_FOUND",
        "VERDICT_INVALID",
        # S5b-3a confirmation items
        "CONFIRMATION_INVALID",
        "CONFIRMATION_NOT_FOUND",
        "ANSWER_INVALID",
        "CONFIRMATION_CLOSED",
        "ANSWER_STALE",
        # RV6 point review
        "CANDIDATE_DECIDED",
        "MEMBER_DECIDED",
    }
)
_CLIENT_CODES = frozenset(
    {
        "INVALID_REQUEST",
        "INVALID_RESPONSE",
        "RELEASE_MISMATCH",
        "UNAUTHENTICATED",
        # S8b revert preconditions, checked before any write
        "RELEASE_RETIRED",
        "SLUG_COLLISION",
    }
)


class PlatformError(ValueError):
    """A caller-safe failure code; unknown platform codes read as SERVICE_UNAVAILABLE."""

    def __init__(self, code: str) -> None:
        known = code in _PLATFORM_CODES or code in _CLIENT_CODES
        self.code = code if known else "SERVICE_UNAVAILABLE"
        super().__init__(self.code)


def require_identifier(part: str) -> None:
    if not isinstance(part, str) or not _IDENTIFIER.fullmatch(part):
        raise PlatformError("INVALID_REQUEST")


def failure_code(status: int, content: bytes) -> str:
    try:
        document = strict_json(content)
    except PlatformError:
        document = None
    if isinstance(document, dict) and isinstance(document.get("code"), str):
        return str(document["code"])
    if status == 401:
        return "UNAUTHENTICATED"
    if status == 403:
        return "RELEASE_ACCESS_DENIED"
    return "SERVICE_UNAVAILABLE"


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate key")
        document[key] = value
    return document


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite number {value}")


def strict_json(content: bytes) -> object:
    try:
        return json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (ValueError, UnicodeError, RecursionError):
        raise PlatformError("INVALID_RESPONSE") from None


def parse_response[T: BaseModel](model: type[T], data: object) -> T:
    try:
        return model.model_validate(data)
    except ValidationError:
        raise PlatformError("INVALID_RESPONSE") from None
