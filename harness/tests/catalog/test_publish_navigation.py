"""QA3 acceptance (protected, written by Claude): a navigation version reaches the Head on its own.

Spec docs/design/slices/QA3-字段按问法匹配.md §3.2: product publishes add the navigation only when
the Head has none, so a new navigation version needs its own candidate. It holds exactly the
navigation member, is decided by the machine with the navigation version as its policy, and
carries no facts. Offline over a fake platform. RED until QA3.
"""

from __future__ import annotations

import json
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
        self.active = {"id": "rel_base", "epoch": 7, "members": members}
        self.seen: list[tuple[str, str, Any]] = []

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
            return _ok({"id": "rel_nav", "epoch": 8, "members": []}, 201)
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
