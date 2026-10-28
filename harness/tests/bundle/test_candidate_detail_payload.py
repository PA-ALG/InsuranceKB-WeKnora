"""RV6e #420 review R1: a member payload that is missing or not a JSON object is invalid."""

import copy
from typing import Any

import httpx
import pytest

from insurance_harness.bundle.client import CandidateDetail, PlatformClient, PlatformError

BASE = "https://weknora.test"
MEMBER: dict[str, Any] = {
    "kind": "claim",
    "logical_slug": "P/waiting",
    "payload": {"claim_id": "P/waiting", "state": "present", "value": "180日"},
    "member_digest": "d" * 64,
    "evidence_refs": ["source:k-1"],
    "access_scope": "space",
}
DETAIL: dict[str, Any] = {
    "candidate_id": "cand-1",
    "status": "pending",
    "point_count": 0,
    "pending_points": 0,
    "base_release_id": "release-1",
    "head_release_id": "release-1",
    "blocker": "",
    "bundle_members": [MEMBER],
    "bundle_removals": [],
    "points": [],
}
MISSING = object()
NOT_OBJECTS = [None, False, 42, 4.5, "text", [], [{"claim_id": "P/waiting"}], MISSING]


def read(data: dict[str, Any]) -> CandidateDetail:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"success": True, "data": data})
    )
    client = PlatformClient(BASE, "key-123", transport=transport)
    return client.review_detail("space-1", "cand-1")


def test_an_object_payload_with_generic_content_is_accepted() -> None:
    detail = copy.deepcopy(DETAIL)
    detail["bundle_members"][0]["payload"] = {"nested": {"any": [1, "two", None]}}
    assert read(detail).bundle_members[0].payload == {"nested": {"any": [1, "two", None]}}


@pytest.mark.parametrize("payload", NOT_OBJECTS)
def test_a_missing_or_non_object_payload_is_an_invalid_response(payload: object) -> None:
    detail = copy.deepcopy(DETAIL)
    if payload is MISSING:
        del detail["bundle_members"][0]["payload"]
    else:
        detail["bundle_members"][0]["payload"] = payload
    with pytest.raises(PlatformError) as caught:
        read(detail)
    assert caught.value.code == "INVALID_RESPONSE"
