"""Client for the platform's enterprise publishing API (S4g Spec §2.3).

Submits candidate bundles, records explicit decisions, activates approved candidates and reads
releases back. Failures surface as caller-safe codes: response bodies and transport diagnostics
never reach the exception. The client never approves anything on its own.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

# Re-exported: callers use the confirmation models through the client.
from insurance_harness.bundle.confirmation_items import ConfirmationAnswer as ConfirmationAnswer
from insurance_harness.bundle.confirmation_items import ConfirmationClosure as ConfirmationClosure
from insurance_harness.bundle.confirmation_items import ConfirmationInput as ConfirmationInput
from insurance_harness.bundle.confirmation_items import ConfirmationItem as ConfirmationItem
from insurance_harness.bundle.confirmation_items import ConfirmationOption as ConfirmationOption
from insurance_harness.contracts.bundle import CandidateBundle

MAX_BUNDLE_BYTES = 2 << 20  # the platform's limit (release.MaxBundleBytes)
MAX_RESPONSE_BYTES = 32 << 20
MAX_CONFIRMATIONS = 200  # the platform's limit on items per submission (S5b-3a)
MAX_CONFIRMATION_BYTES = 512 << 10  # its limit on a submission body (maxConfirmationsBody)
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


class _Response(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)


class Head(_Response):
    release_id: str = Field(min_length=1)
    epoch: int = Field(ge=1)


class DecisionInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    outcome: Literal["approve", "reject", "manual"]
    mode: Literal["machine", "human"]
    policy_ref: str | None = None
    score: str | None = None
    reason: str | None = None


class Candidate(_Response):
    id: str = Field(min_length=1)
    status: str


class Decision(_Response):
    id: str = Field(min_length=1)
    candidate_id: str
    outcome: str
    digest: str


class ReleaseMember(_Response):
    kind: str
    logical_slug: str
    member_digest: str
    payload: Any = None
    evidence_refs: list[str] = Field(default_factory=list)
    access_scope: str = ""


class Release(_Response):
    id: str = Field(min_length=1)
    epoch: int = Field(ge=1)
    base_release_id: str = ""
    candidate_id: str = ""
    decision_digest: str = ""
    retired_at: str | None = None
    members: list[ReleaseMember] = Field(default_factory=list)

    @property
    def head(self) -> Head:
        return Head(release_id=self.id, epoch=self.epoch)


class Verdict(_Response):
    id: str = Field(min_length=1)
    sample_id: str
    outcome: Literal["correct", "incomplete", "wrong"]
    note: str = ""
    reviewer: str
    decided_at: str


class Sample(_Response):
    """A spot-check sample of one release member (RV4), with its latest verdict if any."""

    id: str = Field(min_length=1)
    space_id: str = Field(min_length=1)
    release_id: str = Field(min_length=1)
    logical_slug: str = Field(min_length=1)
    member_digest: str
    stratum: str
    created_by: str
    created_at: str
    verdict: Verdict | None = None


class _Samples(_Response):
    samples: list[Sample]


class _Confirmations(_Response):
    items: list[ConfirmationItem]


class _Closure(_Response):
    closure: ConfirmationClosure


class PlatformClient:
    def __init__(
        self, base_url: str, api_key: str, transport: httpx.BaseTransport | None = None
    ) -> None:
        try:
            url = httpx.URL(base_url)
        except httpx.InvalidURL:
            raise PlatformError("INVALID_REQUEST") from None
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.userinfo
            or url.query
            or url.fragment
            or not api_key.strip()
        ):
            raise PlatformError("INVALID_REQUEST")
        self._base_url = str(url).rstrip("/")
        self._api_key = api_key
        self._transport = transport

    def active(self, space_id: str) -> Release | None:
        """The active release of the Space, or None before the first activation."""
        try:
            return self.release(space_id, "")
        except PlatformError as error:
            if error.code == "RELEASE_NOT_FOUND":
                return None
            raise

    def submit(self, space_id: str, bundle: CandidateBundle) -> Candidate:
        raw = json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")
        if len(raw) > MAX_BUNDLE_BYTES:
            raise PlatformError("INVALID_REQUEST")
        return _parse(Candidate, self._send("POST", space_id, ["candidates"], raw))

    def decide(self, space_id: str, candidate_id: str, decision: DecisionInput) -> Decision:
        raw = json.dumps(decision.model_dump(exclude_none=True), ensure_ascii=False).encode()
        path = ["candidates", candidate_id, "decisions"]
        return _parse(Decision, self._send("POST", space_id, path, raw))

    def activate(self, space_id: str, candidate_id: str, decision_id: str) -> Release:
        _identifier(decision_id)
        raw = json.dumps({"decision_id": decision_id}).encode()
        path = ["candidates", candidate_id, "activations"]
        return _parse(Release, self._send("POST", space_id, path, raw))

    def submit_samples(
        self, space_id: str, release_id: str, picks: list[tuple[str, str]]
    ) -> list[Sample]:
        """Submit (slug, stratum) samples of one release; the platform keeps existing ones."""
        _identifier(release_id)
        body = {"samples": [{"slug": slug, "stratum": stratum} for slug, stratum in picks]}
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        path = ["releases", release_id, "samples"]
        return _parse(_Samples, self._send("POST", space_id, path, raw)).samples

    def samples(
        self, space_id: str, *, status: str | None = None, release_id: str | None = None
    ) -> list[Sample]:
        query = {
            key: value
            for key, value in (("status", status), ("release", release_id))
            if value is not None
        }
        for value in query.values():
            _identifier(value)
        return _parse(_Samples, self._send("GET", space_id, ["samples"], None, query)).samples

    def submit_confirmations(
        self, space_id: str, items: Sequence[ConfirmationInput]
    ) -> list[ConfirmationItem]:
        """Submit items; the platform keeps existing ones and returns them all in input order.

        Each returned item must be the one asked for at its position (review R5); the caller splits
        batches by count and by the encoded body size (`confirmation_body`).
        """
        raw = confirmation_body(items)
        if not 1 <= len(items) <= MAX_CONFIRMATIONS or len(raw) > MAX_CONFIRMATION_BYTES:
            raise PlatformError("INVALID_REQUEST")
        stored = _parse(_Confirmations, self._send("POST", space_id, ["confirmations"], raw)).items
        if len(stored) != len(items) or any(
            not _owns(item, space_id) or _asked(item) != _asked(question)
            for item, question in zip(stored, items, strict=False)
        ):
            raise PlatformError("INVALID_RESPONSE")
        return stored

    def confirmations(
        self, space_id: str, status: Literal["open", "closed"]
    ) -> list[ConfirmationItem]:
        if status not in {"open", "closed"}:
            raise PlatformError("INVALID_REQUEST")
        data = self._send("GET", space_id, ["confirmations"], None, {"status": status})
        listed = _parse(_Confirmations, data).items
        if any(not _owns(i, space_id) or (i.closure is None) != (status == "open") for i in listed):
            raise PlatformError("INVALID_RESPONSE")
        return listed

    def close_confirmation(
        self,
        space_id: str,
        item_id: str,
        reason: Literal["applied", "obsolete"],
        answer_id: str | None = None,
    ) -> ConfirmationClosure:
        """Close once: applied names the latest answer, obsolete names none.

        The receipt must confirm exactly this closure: it is the commit point of a decision.
        """
        if reason not in {"applied", "obsolete"} or (reason == "applied") != (
            answer_id is not None
        ):
            raise PlatformError("INVALID_REQUEST")
        body: dict[str, str] = {"reason": reason}
        if answer_id is not None:
            _identifier(answer_id)
            body["answer_id"] = answer_id
        path = ["confirmations", item_id, "closure"]
        data = self._send("POST", space_id, path, json.dumps(body).encode())
        closure = _parse(_Closure, data).closure
        if (closure.reason, closure.answer_id or None) != (reason, answer_id):
            raise PlatformError("INVALID_RESPONSE")
        return closure

    def release(self, space_id: str, release_id: str) -> Release:
        path = ["releases", release_id] if release_id else ["releases", "active"]
        return _parse(Release, self._send("GET", space_id, path, None))

    def _send(
        self,
        method: str,
        space_id: str,
        path: list[str],
        body: bytes | None,
        query: dict[str, str] | None = None,
    ) -> object:
        for part in [space_id, *path]:
            _identifier(part)
        url = f"{self._base_url}/api/v1/enterprise/spaces/{'/'.join([space_id, *path])}"
        if query:
            url = str(httpx.URL(url, params=query))
        headers = {"X-API-Key": self._api_key}
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            with (
                httpx.Client(
                    transport=self._transport,
                    timeout=30.0,
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
                client.stream(method, url, headers=headers, content=body) as response,
            ):
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE_BYTES:
                        raise PlatformError("INVALID_RESPONSE")
                status = response.status_code
        except httpx.HTTPError:
            raise PlatformError("SERVICE_UNAVAILABLE") from None
        if not 200 <= status < 300:
            raise PlatformError(_failure_code(status, bytes(content)))
        document = _strict_json(bytes(content))
        if not isinstance(document, dict) or document.get("success") is not True:
            raise PlatformError("INVALID_RESPONSE")
        return document.get("data")


@dataclass(frozen=True)
class PublishResult:
    candidate: Candidate
    decision: Decision | None
    release: Release | None


def publish(
    client: PlatformClient,
    space_id: str,
    bundle: CandidateBundle,
    *,
    decision: DecisionInput | None = None,
    activate: bool = False,
) -> PublishResult:
    """Submit, then decide and activate only when the caller says so explicitly.

    Activation needs an approving decision in the same call. The activated release is read
    back and must carry exactly the submitted member digests.
    """
    if activate and (decision is None or decision.outcome != "approve"):
        raise PlatformError("INVALID_REQUEST")
    candidate = client.submit(space_id, bundle)
    if decision is None:
        return PublishResult(candidate, None, None)
    recorded = client.decide(space_id, candidate.id, decision)
    if not activate:
        return PublishResult(candidate, recorded, None)
    activated = client.activate(space_id, candidate.id, recorded.id)
    published = client.release(space_id, activated.id)
    digests = {m.logical_slug: m.member_digest for m in published.members}
    if published.id != activated.id or any(
        digests.get(m.logical_slug) != m.member_digest for m in bundle.members
    ):
        raise PlatformError("RELEASE_MISMATCH")
    return PublishResult(candidate, recorded, published)


def confirmation_body(items: Sequence[ConfirmationInput]) -> bytes:
    """The request body submitting these items, as sent."""
    body = {"items": [item.model_dump() for item in items]}
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def _asked(item: ConfirmationInput | ConfirmationItem) -> tuple[object, ...]:
    options = tuple((o.key, o.label) for o in item.options)
    return (item.subject, item.revision, item.title, item.detail, options, item.source_ref or "")


def _owns(item: ConfirmationItem, space_id: str) -> bool:
    """The item is in the Space asked about, its answer is its own, and its closure agrees with
    that answer: applied names it, obsolete names none (review R5)."""
    if item.space_id != space_id or (item.answer is not None and item.answer.item_id != item.id):
        return False
    closure = item.closure
    if closure is None:
        return True
    if closure.reason == "applied":
        return item.answer is not None and closure.answer_id == item.answer.id
    return not closure.answer_id


def _identifier(part: str) -> None:
    if not isinstance(part, str) or not _IDENTIFIER.fullmatch(part):
        raise PlatformError("INVALID_REQUEST")


def _failure_code(status: int, content: bytes) -> str:
    try:
        document = _strict_json(content)
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


def _strict_json(content: bytes) -> object:
    try:
        return json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (ValueError, UnicodeError, RecursionError):
        raise PlatformError("INVALID_RESPONSE") from None


def _parse[T: _Response](model: type[T], data: object) -> T:
    try:
        return model.model_validate(data)
    except ValidationError:
        raise PlatformError("INVALID_RESPONSE") from None
