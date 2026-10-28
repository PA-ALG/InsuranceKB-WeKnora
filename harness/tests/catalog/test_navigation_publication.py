"""QA3 acceptance (protected, written by Claude): a navigation version reaches the Head on its own.

Spec docs/design/slices/QA3-字段按问法匹配.md §3.2: product publishes add the navigation only when
the Head has none, so a new navigation version needs its own candidate. It holds exactly the
navigation member, is decided by the machine with the navigation version as its policy, and
carries no facts. Offline over a fake platform. RED until QA3.

2026-10-28 (#414 review R1/R4, Owner rulings, Spec §3.2 amended): the command takes --space and
reads the activated release back. Only a release of this candidate holding the navigation with the
target digest is "published"; a mismatch or an unreadable release is "unknown", with no write after
the activation. The fake platform now serves that read-back.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from insurance_harness.bundle.canonical import member_digest
from insurance_harness.bundle.client import PlatformClient
from insurance_harness.catalog import publish_navigation as command
from insurance_harness.catalog.navigation import load_navigation
from insurance_harness.ingest.source_map import API_KEY_ENV, BASE_URL_ENV

SPACE = "space-1"


def _ok(data: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"success": True, "data": data})


class Platform:
    def __init__(self, navigation_payload: dict[str, Any] | None) -> None:
        members: list[dict[str, Any]] = [
            {"kind": "claim", "logical_slug": "1828/waiting_period", "member_digest": "a" * 64},
        ]
        if navigation_payload is not None:
            members.append(
                {
                    "kind": "navigation",
                    "logical_slug": f"navigation/{navigation_payload['navigation_id']}",
                    "member_digest": member_digest(navigation_payload),
                }
            )
        self.active: dict[str, Any] = {"id": "rel_base", "epoch": 7, "members": members}
        self.seen: list[tuple[str, str, Any]] = []
        self.receipt: dict[str, Any] = {
            "id": "rel_nav",
            "epoch": 8,
            "candidate_id": "cand_nav",
            "members": [],
        }
        # Edits the activated release before it is read back: a dict, a response, or a raise.
        self.readback: Callable[[dict[str, Any]], dict[str, Any] | httpx.Response] = lambda r: r

    def _activated(self) -> dict[str, Any]:
        [submit] = [body for method, path, body in self.seen if path == "candidates"]
        added = {member["logical_slug"]: member for member in submit["members"]}
        kept = [m for m in self.active["members"] if m["logical_slug"] not in added]
        members = kept + [
            {k: m[k] for k in ("kind", "logical_slug", "member_digest")} for m in added.values()
        ]
        return {
            "id": "rel_nav",
            "epoch": 8,
            "base_release_id": "rel_base",
            "candidate_id": "cand_nav",
            "members": members,
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.split(f"/spaces/{SPACE}/", 1)[1]
        body = json.loads(request.content) if request.content else None
        self.seen.append((request.method, path, body))
        if path == "releases/active":
            return _ok(self.active)
        if path == "candidates":
            return _ok({"id": "cand_nav", "status": "pending"}, 201)
        if path == "candidates/cand_nav/decisions":
            assert body is not None
            return _ok(
                {
                    "id": "dec_nav",
                    "candidate_id": "cand_nav",
                    "outcome": body["outcome"],
                    "digest": "d" * 64,
                },
                201,
            )
        if path == "candidates/cand_nav/activations":
            return _ok(self.receipt, 201)
        if path == "releases/rel_nav" and request.method == "GET":
            release = self.readback(self._activated())
            return release if isinstance(release, httpx.Response) else _ok(release)
        return httpx.Response(404, json={"success": False, "code": "NOT_FOUND"})


def _run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: Platform,
    *extra: str,
) -> tuple[int, dict[str, Any]]:
    monkeypatch.setenv(BASE_URL_ENV, "http://platform.test")
    monkeypatch.setenv(API_KEY_ENV, "test-key")
    monkeypatch.setattr(
        command,
        "PlatformClient",
        lambda base, key: PlatformClient(base, key, transport=httpx.MockTransport(server)),
    )
    code = command.main(["--space", SPACE, *extra])
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    return code, json.loads(lines[-1])


def test_a_new_navigation_version_is_published_alone_by_the_machine(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    current = load_navigation()
    old = {**current.model_dump(mode="json"), "navigation_version": "older"}
    server = Platform(old)
    code, report = _run(monkeypatch, capsys, server)
    assert code == 0
    assert report["status"] == "published"
    assert report["navigation_version"] == current.navigation_version
    assert report["release_id"] == "rel_nav"
    [submit] = [body for method, path, body in server.seen if path == "candidates"]
    assert submit["base_release_id"] == "rel_base"
    assert submit["removals"] == []
    [member] = submit["members"]
    assert member["kind"] == "navigation"
    assert member["logical_slug"] == f"navigation/{current.navigation_id}"
    assert member["payload"] == current.model_dump(mode="json")
    assert member["member_digest"] == member_digest(member["payload"])
    [decision] = [body for method, path, body in server.seen if path.endswith("/decisions")]
    assert decision["outcome"] == "approve"
    assert decision["mode"] == "machine"
    assert decision["policy_ref"] == f"navigation:{current.navigation_version}"
    assert any(path.endswith("/activations") for _, path, _ in server.seen)
    # Reported published only after the activated release was read back.
    assert server.seen[-1][:2] == ("GET", "releases/rel_nav")


def _writes_after_activation(server: Platform) -> list[str]:
    paths = [(method, path) for method, path, _ in server.seen]
    activation = paths.index(("POST", "candidates/cand_nav/activations"))
    return [path for method, path in paths[activation + 1 :] if method != "GET"]


def _assert_unknown(code: int, report: dict[str, Any], server: Platform, stopped: str) -> None:
    assert code == 2
    assert report["status"] == "unknown"
    assert report["stopped"] == stopped
    assert [m for m, path, _ in server.seen if path == "candidates"] == ["POST"]
    assert _writes_after_activation(server) == []


def _without_navigation(release: dict[str, Any]) -> dict[str, Any]:
    members = [m for m in release["members"] if m["kind"] != "navigation"]
    return {**release, "members": members}


def _other_digest(release: dict[str, Any]) -> dict[str, Any]:
    members = [
        {**m, "member_digest": "b" * 64} if m["kind"] == "navigation" else m
        for m in release["members"]
    ]
    return {**release, "members": members}


@pytest.mark.parametrize(
    "readback",
    [
        _without_navigation,
        _other_digest,
        lambda release: {**release, "candidate_id": "cand_other"},
        lambda release: {**release, "id": "rel_other"},
    ],
    ids=["navigation missing", "other digest", "other candidate", "other release"],
)
def test_a_release_that_does_not_hold_this_navigation_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    readback: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    server = Platform({**load_navigation().model_dump(mode="json"), "navigation_version": "older"})
    server.readback = readback
    code, report = _run(monkeypatch, capsys, server)
    _assert_unknown(code, report, server, "RELEASE_MISMATCH")


def test_an_activation_receipt_for_another_candidate_is_unknown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = Platform({**load_navigation().model_dump(mode="json"), "navigation_version": "older"})
    server.receipt = {**server.receipt, "candidate_id": "cand_other"}
    code, report = _run(monkeypatch, capsys, server)
    _assert_unknown(code, report, server, "RELEASE_MISMATCH")


def _connection_lost(release: dict[str, Any]) -> dict[str, Any]:
    raise httpx.ConnectError("connection lost")


@pytest.mark.parametrize(
    ("readback", "stopped"),
    [
        (lambda _: httpx.Response(503, text="busy"), "SERVICE_UNAVAILABLE"),
        (
            lambda _: httpx.Response(404, json={"success": False, "code": "RELEASE_NOT_FOUND"}),
            "RELEASE_NOT_FOUND",
        ),
        (lambda _: httpx.Response(200, text="not json"), "INVALID_RESPONSE"),
        (_connection_lost, "SERVICE_UNAVAILABLE"),
    ],
    ids=["unavailable", "not found", "malformed", "connection lost"],
)
def test_an_unreadable_activated_release_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    readback: Callable[[dict[str, Any]], dict[str, Any] | httpx.Response],
    stopped: str,
) -> None:
    server = Platform({**load_navigation().model_dump(mode="json"), "navigation_version": "older"})
    server.readback = readback
    code, report = _run(monkeypatch, capsys, server)
    _assert_unknown(code, report, server, stopped)
    assert server.seen[-1][:2] == ("GET", "releases/rel_nav")


def test_a_current_navigation_publishes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = Platform(load_navigation().model_dump(mode="json"))
    code, report = _run(monkeypatch, capsys, server)
    assert code == 0
    assert report["status"] == "current"
    assert [path for _, path, _ in server.seen] == ["releases/active"]


def test_a_dry_run_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = Platform({**load_navigation().model_dump(mode="json"), "navigation_version": "older"})
    code, report = _run(monkeypatch, capsys, server, "--dry-run")
    assert code == 0
    assert report["status"] == "dry_run"
    assert [method for method, _, _ in server.seen] == ["GET"]
