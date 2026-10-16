"""S4g acceptance: the platform client submits, decides, activates and reads back (Spec §2.3).

Protected file: written by Claude. The client never approves on its own, refuses redirects and
ambiguous JSON, maps platform failures to caller-safe codes, and checks that the activated release
carries exactly the member digests that were submitted.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from insurance_harness.bundle.canonical import member_digest
from insurance_harness.bundle.client import DecisionInput, PlatformClient, PlatformError, publish
from insurance_harness.contracts.bundle import BundleMember, CandidateBundle

BASE = "https://weknora.test"
SPACE = "space-1"
PAYLOAD = {"claim_id": "1828/waiting_period", "state": "present", "value": "90日"}
MEMBER = {
    "kind": "claim",
    "logical_slug": "1828/waiting_period",
    "payload": PAYLOAD,
    "member_digest": member_digest(PAYLOAD),
    "evidence_refs": [],
    "access_scope": "space",
}
BUNDLE = CandidateBundle(
    contract_version="1",
    origin="compile",
    compiler_identity="harness/schema_fields@test",
    members=[BundleMember.model_validate(MEMBER)],
)
APPROVE = DecisionInput(outcome="approve", mode="human", reason="spot-checked")
CANDIDATE = {"id": "cand_1", "status": "created", "bundle_digest": "d" * 64, "space_id": SPACE}
DECISION = {"id": "dec_1", "candidate_id": "cand_1", "outcome": "approve", "digest": "e" * 64}
RELEASE = {
    "id": "rel_1",
    "epoch": 1,
    "base_release_id": "",
    "candidate_id": "cand_1",
    "decision_digest": "e" * 64,
    "members": [MEMBER],
}


def ok(data: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"success": True, "data": data})


def failure(status: int, code: str | None) -> httpx.Response:
    body: dict[str, object] = {"success": False, "error": "detail must not leak"}
    if code is not None:
        body["code"] = code
    return httpx.Response(status, json=body)


Handler = Callable[[httpx.Request], httpx.Response]


def platform(routes: dict[tuple[str, str], httpx.Response]) -> tuple[Handler, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return routes.get((request.method, request.url.path), failure(404, "RELEASE_NOT_FOUND"))

    return handle, seen


def client(handler: Handler) -> PlatformClient:
    return PlatformClient(BASE, "key-123", transport=httpx.MockTransport(handler))


PREFIX = f"/api/v1/enterprise/spaces/{SPACE}"
HAPPY = {
    ("POST", f"{PREFIX}/candidates"): ok(CANDIDATE, 201),
    ("POST", f"{PREFIX}/candidates/cand_1/decisions"): ok(DECISION),
    ("POST", f"{PREFIX}/candidates/cand_1/activations"): ok(RELEASE),
    ("GET", f"{PREFIX}/releases/rel_1"): ok(RELEASE),
}


def body(request: httpx.Request) -> Any:
    return json.loads(request.content.decode("utf-8"))


def test_publish_submits_decides_activates_and_reads_back() -> None:
    handler, seen = platform(HAPPY)
    result = publish(client(handler), SPACE, BUNDLE, decision=APPROVE, activate=True)
    assert (result.candidate.id, result.decision and result.decision.id) == ("cand_1", "dec_1")
    assert result.release is not None and (result.release.id, result.release.epoch) == ("rel_1", 1)
    assert [(r.method, r.url.path) for r in seen] == list(HAPPY)
    assert all(r.headers["X-API-Key"] == "key-123" for r in seen)
    assert body(seen[0])["members"][0]["member_digest"] == member_digest(PAYLOAD)
    assert body(seen[1]) == {"outcome": "approve", "mode": "human", "reason": "spot-checked"}
    assert body(seen[2]) == {"decision_id": "dec_1"}


def test_without_an_explicit_decision_nothing_is_decided_or_activated() -> None:
    handler, seen = platform(HAPPY)
    result = publish(client(handler), SPACE, BUNDLE)
    assert result.decision is None and result.release is None
    assert [(r.method, r.url.path) for r in seen] == [("POST", f"{PREFIX}/candidates")]


@pytest.mark.parametrize(
    "decision",
    [None, DecisionInput(outcome="reject", mode="human", reason="wrong product")],
)
def test_activation_requires_an_approving_decision_before_any_request(
    decision: DecisionInput | None,
) -> None:
    handler, seen = platform(HAPPY)
    with pytest.raises(PlatformError) as caught:
        publish(client(handler), SPACE, BUNDLE, decision=decision, activate=True)
    assert caught.value.code == "INVALID_REQUEST" and seen == []


def test_a_release_that_does_not_carry_the_submitted_digests_is_refused() -> None:
    tampered = {**RELEASE, "members": [{**MEMBER, "member_digest": "f" * 64}]}
    routes = {**HAPPY, ("GET", f"{PREFIX}/releases/rel_1"): ok(tampered)}
    handler, _ = platform(routes)
    with pytest.raises(PlatformError) as caught:
        publish(client(handler), SPACE, BUNDLE, decision=APPROVE, activate=True)
    assert caught.value.code == "RELEASE_MISMATCH"


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (failure(409, "NEEDS_REBASE"), "NEEDS_REBASE"),
        (failure(400, "CANDIDATE_INVALID"), "CANDIDATE_INVALID"),
        (failure(401, None), "UNAUTHENTICATED"),
        (failure(403, None), "RELEASE_ACCESS_DENIED"),
        (failure(500, "SOMETHING_NEW"), "SERVICE_UNAVAILABLE"),
        (
            httpx.Response(307, headers={"Location": "https://elsewhere.test/"}),
            "SERVICE_UNAVAILABLE",
        ),
        (
            httpx.Response(201, content=b'{"success":true,"data":{"id":"a","id":"b"}}'),
            "INVALID_RESPONSE",
        ),
    ],
)
def test_failures_become_caller_safe_codes(response: httpx.Response, code: str) -> None:
    handler, _ = platform({("POST", f"{PREFIX}/candidates"): response})
    with pytest.raises(PlatformError) as caught:
        client(handler).submit(SPACE, BUNDLE)
    assert caught.value.code == code
    assert "leak" not in str(caught.value)


def test_no_active_release_reads_as_none() -> None:
    handler, _ = platform({})
    assert client(handler).active(SPACE) is None


@pytest.mark.parametrize("url", ["ftp://weknora.test", "https://u:p@weknora.test", f"{BASE}?x=1"])
def test_unsafe_base_urls_are_rejected(url: str) -> None:
    with pytest.raises(PlatformError) as caught:
        PlatformClient(url, "key-123")
    assert caught.value.code == "INVALID_REQUEST"
