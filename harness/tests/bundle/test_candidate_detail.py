"""RV6e acceptance (protected, written by Claude): the platform client reads one candidate's detail.

Spec docs/design/slices/RV6e-服务密钥读取候选明细.md §3: the API-key route, strict parsing of the
bundle members, removals and review points, and caller-safe codes.
"""

from collections.abc import Callable

import httpx
import pytest

from insurance_harness.bundle.client import CandidateDetail, PlatformClient, PlatformError

BASE = "https://weknora.test"
SPACE = "space-1"
CANDIDATE = "cand-1"
PATH = f"/api/v1/enterprise/spaces/{SPACE}/candidates/{CANDIDATE}"
MEMBER = {
    "kind": "claim",
    "logical_slug": "P/waiting",
    "payload": {"claim_id": "P/waiting", "state": "present", "value": "180日"},
    "member_digest": "d" * 64,
    "evidence_refs": ["source:k-1"],
    "access_scope": "space",
}
PENDING = {
    "slug": "P/waiting",
    "kind": "claim",
    "status": "pending",
    "decision": None,
    "release_id": None,
    "blocker": "",
}
REJECTED = {
    "slug": "P/old",
    "kind": "removal",
    "status": "rejected",
    "decision": {
        "outcome": "reject",
        "reason": "评委拒绝（policy_ref: rv-judge:test）",
        "subject": "service:1",
        "created_at": "2026-10-27T08:00:01Z",
    },
    "release_id": None,
    "blocker": "",
}
DETAIL = {
    "candidate_id": CANDIDATE,
    "status": "pending",
    "point_count": 2,
    "pending_points": 1,
    "created_at": "2026-10-27T08:00:00Z",
    "created_by": "service:1",
    "base_release_id": "release-1",
    "subjects": ["P"],
    "members": 1,
    "removals": 1,
    "decision": None,
    "release_id": None,
    "head_release_id": "release-1",
    "blocker": "CANDIDATE_DECIDED",
    "bundle_members": [MEMBER],
    "bundle_removals": ["P/old"],
    "points": [REJECTED, PENDING],
}


def client(
    handler: Callable[[httpx.Request], httpx.Response], seen: list[httpx.Request]
) -> PlatformClient:
    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return PlatformClient(BASE, "key-123", transport=httpx.MockTransport(record))


def ok(data: object) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "data": data})


def test_reading_a_candidate_gets_its_members_removals_and_points() -> None:
    seen: list[httpx.Request] = []
    detail = client(lambda _: ok(DETAIL), seen).review_detail(SPACE, CANDIDATE)

    assert isinstance(detail, CandidateDetail)
    [request] = seen
    assert (request.method, request.url.path) == ("GET", PATH)
    assert request.headers["X-API-Key"] == "key-123" and request.content == b""
    assert (detail.candidate_id, detail.status, detail.blocker) == (
        CANDIDATE,
        "pending",
        "CANDIDATE_DECIDED",
    )
    assert (detail.head_release_id, detail.point_count, detail.pending_points) == (
        "release-1",
        2,
        1,
    )
    [member] = detail.bundle_members
    assert (member.kind, member.logical_slug, member.member_digest) == (
        "claim",
        "P/waiting",
        "d" * 64,
    )
    assert member.payload == MEMBER["payload"]
    assert detail.bundle_removals == ["P/old"]
    points = {point.slug: point for point in detail.points}
    assert points["P/waiting"].status == "pending" and points["P/waiting"].decision is None
    rejected = points["P/old"]
    assert (rejected.kind, rejected.status) == ("removal", "rejected")
    assert rejected.decision is not None and rejected.decision.outcome == "reject"
    assert rejected.decision.reason == "评委拒绝（policy_ref: rv-judge:test）"


def test_lists_the_platform_leaves_null_read_as_empty() -> None:
    data = DETAIL | {"bundle_members": None, "bundle_removals": None, "head_release_id": None}
    detail = client(lambda _: ok(data), []).review_detail(SPACE, CANDIDATE)
    assert (detail.bundle_members, detail.bundle_removals, detail.head_release_id) == ([], [], None)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(DETAIL | {"candidate_id": "cand-2"}, id="another candidate"),
        pytest.param(DETAIL | {"bundle_members": [MEMBER, MEMBER]}, id="duplicate member slug"),
        pytest.param(DETAIL | {"points": [PENDING, PENDING]}, id="duplicate point slug"),
        pytest.param(DETAIL | {"point_count": "2"}, id="count as text"),
        pytest.param(DETAIL | {"points": None}, id="points null"),
        pytest.param(
            DETAIL | {"bundle_members": [MEMBER | {"member_digest": 1}]}, id="digest type"
        ),
        pytest.param(DETAIL | {"points": [PENDING | {"decision": "reject"}]}, id="decision type"),
        pytest.param({k: v for k, v in DETAIL.items() if k != "candidate_id"}, id="no candidate"),
        pytest.param([DETAIL], id="not an object"),
    ],
)
def test_malformed_details_are_invalid_responses(data: object) -> None:
    with pytest.raises(PlatformError) as caught:
        client(lambda _: ok(data), []).review_detail(SPACE, CANDIDATE)
    assert caught.value.code == "INVALID_RESPONSE"


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (
            httpx.Response(404, json={"success": False, "code": "CANDIDATE_NOT_FOUND"}),
            "CANDIDATE_NOT_FOUND",
        ),
        (httpx.Response(403), "RELEASE_ACCESS_DENIED"),
        (httpx.Response(401), "UNAUTHENTICATED"),
        (
            httpx.Response(503, json={"success": False, "code": "SERVICE_UNAVAILABLE"}),
            "SERVICE_UNAVAILABLE",
        ),
    ],
)
def test_platform_failures_become_caller_safe_codes(response: httpx.Response, code: str) -> None:
    with pytest.raises(PlatformError) as caught:
        client(lambda _: response, []).review_detail(SPACE, CANDIDATE)
    assert caught.value.code == code


@pytest.mark.parametrize("candidate_id", ["", "../release", "cand 1", "候选"])
def test_unsafe_candidate_ids_send_nothing(candidate_id: str) -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(PlatformError) as caught:
        client(lambda _: ok(DETAIL), seen).review_detail(SPACE, candidate_id)
    assert caught.value.code == "INVALID_REQUEST" and seen == []
