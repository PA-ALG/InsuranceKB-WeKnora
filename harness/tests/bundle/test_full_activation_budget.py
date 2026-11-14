"""Full activation responses use the configured budget through the public client."""

import json

import httpx
import pytest

from insurance_harness.bundle.client import PlatformClient, PlatformError


@pytest.mark.parametrize(("limit", "succeeds"), [(None, False), ("33", True), ("32", False)])
def test_activate_reads_full_release_within_configured_budget(
    monkeypatch: pytest.MonkeyPatch, limit: str | None, succeeds: bool
) -> None:
    env = "HARNESS_WEKNORA_RELEASE_MAX_RESPONSE_MIB"
    if limit is None:
        monkeypatch.delenv(env, raising=False)
    else:
        monkeypatch.setenv(env, limit)
    monkeypatch.setenv("HARNESS_WEKNORA_ACTIVATION_READ_TIMEOUT_SECONDS", "180")
    members = [
        {
            "kind": "claim",
            "logical_slug": f"item/{i}",
            "member_digest": "a" * 64,
            "payload": {"text": "a" * 4000},
        }
        for i in range(8200)
    ]
    active = {"id": "rel-1", "epoch": 2, "candidate_id": "cand", "members": members}
    raw = json.dumps({"success": True, "data": active}).encode()
    assert (32 << 20) < len(raw) < (33 << 20)
    sent = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        assert request.method == "POST"
        assert request.url.query == b""
        assert request.extensions["timeout"]["read"] == 180
        return httpx.Response(200, content=raw)

    client = PlatformClient("https://platform.test", "key", httpx.MockTransport(respond))
    if succeeds:
        released = client.activate("space", "cand", "dec")
        assert released.id == "rel-1"
        assert len(released.members) == len(members)
        assert released.members[-1].payload == members[-1]["payload"]
    else:
        with pytest.raises(PlatformError, match="INVALID_RESPONSE"):
            client.activate("space", "cand", "dec")
    assert len(sent) == 1


def test_receipt_budget_stays_small_when_release_budget_is_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_WEKNORA_RELEASE_MAX_RESPONSE_MIB", "128")
    receipt = {
        "id": "rel-1",
        "epoch": 1,
        "base_release_id": "",
        "candidate_id": "cand",
        "decision_id": "dec",
        "decision_digest": "a" * 64,
    }
    body = json.dumps({"success": True, "data": receipt}).encode()
    responses = iter([body.ljust(64 << 10), body.ljust((64 << 10) + 1)])

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.params["response"] == "receipt"
        return httpx.Response(200, content=next(responses))

    client = PlatformClient("https://platform.test", "key", httpx.MockTransport(respond))
    assert client.activate_receipt("space", "cand", "dec", "a" * 64).id == "rel-1"
    with pytest.raises(PlatformError, match="INVALID_RESPONSE"):
        client.activate_receipt("space", "cand", "dec", "a" * 64)
