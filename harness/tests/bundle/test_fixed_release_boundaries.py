"""Narrow responses must account for every requested row within one version and budget."""

import json

import httpx
import pytest

from insurance_harness.bundle.canonical import member_digest
from insurance_harness.bundle.client import PlatformClient, PlatformError
from insurance_harness.bundle.fixed_release import FixedRelease
from insurance_harness.bundle.request_budget import ReleaseReadBudget


@pytest.mark.parametrize("fault", ["duplicate-index", "missing", "digest", "budget", "none"])
def test_fixed_release_stops_on_damaged_or_oversized_responses(fault: str) -> None:
    identity = {
        "id": "release-1",
        "epoch": 1,
        "base_release_id": "",
        "candidate_id": "candidate",
        "decision_digest": "a" * 64,
    }
    payload = {"subject_ref": "p", "logical_key": "p/key", "value": "old"}
    row = {k: payload[k] for k in ("subject_ref", "logical_key")}
    row.update(kind="claim", logical_slug="legacy/alias", member_digest=member_digest(payload))
    calls = []

    def dispatch(req: httpx.Request) -> httpx.Response:
        route = req.url.path.rsplit("/", 1)[-1]
        calls.append(route)
        if route == "summary":
            return httpx.Response(200, json={"success": True, "data": identity})
        if route == "member-index":
            members = [row, row] if fault == "duplicate-index" else [row]
            return httpx.Response(
                200, json={"success": True, "data": identity | {"members": members}}
            )
        assert route == "member-lookup"
        assert json.loads(req.content) == {"slugs": ["legacy/alias"]}
        lookup: dict[str, object]
        if fault == "missing":
            lookup = {"members": [], "missing": ["legacy/alias"]}
        else:
            fields = {k: row[k] for k in ("kind", "logical_slug", "member_digest")}
            body = payload | {"value": "damaged"} if fault == "digest" else payload
            lookup = {"members": [fields | {"payload": body}], "missing": []}
        return httpx.Response(200, json={"success": True, "data": identity | lookup})

    client = PlatformClient("https://platform.test", "key", httpx.MockTransport(dispatch))
    budget = ReleaseReadBudget(700) if fault == "budget" else ReleaseReadBudget()
    if fault == "duplicate-index":
        with pytest.raises(PlatformError, match="INVALID_RESPONSE"):
            FixedRelease.active(client, "space", budget)
        assert calls == ["summary", "member-index"]
        return
    fixed = FixedRelease.active(client, "space", budget)
    assert fixed is not None
    selected = fixed.claims_for(["p"])
    if fault == "none":
        assert [m.payload for m in fixed.members(selected)] == [payload]
    else:
        code = "RELEASE_READ_LIMIT" if fault == "budget" else "RELEASE_MISMATCH"
        with pytest.raises(PlatformError, match=code):
            fixed.members(selected)
    assert calls == ["summary", "member-index", "member-lookup"]
