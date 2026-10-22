"""Revert command over the real platform client (httpx MockTransport): the #294 review cases.

R2 a retired target is refused before any write; R3 source and evidence failures keep their
codes; R4 an older member whose slug another entity now uses is refused; R5 a live revert keeps
its release identity when the read-back fails; R6 stale concepts follow actual member slugs.
"""

import json
from typing import Any

import httpx
import pytest

from insurance_harness.bundle.client import PlatformClient, Release
from insurance_harness.changes import revert as command
from insurance_harness.changes.revert import RevertError, revert_bundle

PREFIX = "/api/v1/enterprise/spaces/s/"


def member(kind: str, slug: str, payload: dict[str, Any], digest: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "logical_slug": slug,
        "member_digest": digest,
        "payload": payload,
        "evidence_refs": [],
        "access_scope": "space",
    }


def claim(slug: str, subject: str, value: str, digest: str) -> dict[str, Any]:
    payload = {"subject_ref": subject, "logical_key": f"{subject}/f1", "value": value}
    return member("claim", slug, payload, digest)


def release(rid: str, epoch: int, members: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"id": rid, "epoch": epoch, "members": members, **extra}


OLD = release("rel-1", 1, [claim("legacy/field", "A", "v1", "1" * 64)])
ACTIVE = release(
    "rel-2",
    2,
    [
        claim("legacy/field", "A", "v2", "2" * 64),
        member("concept", "concept/one", {"based_on": {"legacy/field": "2" * 64}}, "3" * 64),
    ],
)


class Server:
    def __init__(self, releases: dict[str, dict[str, Any]], failures: dict[str, Any]) -> None:
        self.releases, self.failures = releases, failures
        self.writes: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix(PREFIX)
        key = f"{request.method} {path}"
        if key in self.failures:
            status, code = self.failures[key]
            return httpx.Response(status, json={"success": False, "code": code})
        if request.method == "POST":
            self.writes.append(path)
        if key == "GET releases/active":
            return httpx.Response(200, json={"success": True, "data": self.releases["rel-2"]})
        if key.startswith("GET releases/"):
            rid = path.split("/")[1]
            if rid not in self.releases:
                return httpx.Response(404, json={"success": False, "code": "RELEASE_NOT_FOUND"})
            return httpx.Response(200, json={"success": True, "data": self.releases[rid]})
        if key == "POST candidates":
            return httpx.Response(
                201, json={"success": True, "data": {"id": "c-1", "status": "created"}}
            )
        if key == "POST candidates/c-1/decisions":
            body = {"id": "d-1", "candidate_id": "c-1", "outcome": "approve", "digest": "x"}
            return httpx.Response(201, json={"success": True, "data": body})
        if key == "POST candidates/c-1/activations":
            data = release("rel-3", 3, [claim("legacy/field", "A", "v1", "1" * 64)])
            return httpx.Response(201, json={"success": True, "data": data})
        return httpx.Response(500, json={"success": False, "code": "INTERNAL_ERROR"})


def run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: Server,
    *extra: str,
) -> tuple[int, dict[str, Any]]:
    monkeypatch.setattr(
        command,
        "PlatformClient",
        lambda base, key: PlatformClient(base, key, transport=httpx.MockTransport(server)),
    )
    monkeypatch.setenv("HARNESS_WEKNORA_BASE_URL", "http://platform.test")
    monkeypatch.setenv("HARNESS_WEKNORA_API_KEY", "test-key")
    argv = ["--space", "s", "--entity", "A", "--to-release", "rel-1", "--reason", "回退"]
    code = command.main([*argv, *extra])
    return code, json.loads(capsys.readouterr().out)


def test_r2_a_retired_target_is_refused_before_any_write(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    retired = {**OLD, "retired_at": "2026-10-20T00:00:00Z"}
    server = Server({"rel-1": retired, "rel-2": ACTIVE}, {})
    code, report = run(monkeypatch, capsys, server, "--activate")
    assert (code, report["stopped"]) == (2, "RELEASE_RETIRED")
    assert server.writes == []


@pytest.mark.parametrize("failure", ["SOURCE_UNAVAILABLE", "EVIDENCE_UNVERIFIABLE"])
def test_r3_source_failures_keep_their_codes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: str
) -> None:
    server = Server({"rel-1": OLD, "rel-2": ACTIVE}, {"POST candidates": (422, failure)})
    code, report = run(monkeypatch, capsys, server)
    assert (code, report["stopped"]) == (2, failure)


def test_r4_an_old_slug_now_owned_by_another_entity_is_refused() -> None:
    old = Release.model_validate(release("rel-1", 1, [claim("shared/slug", "A", "v1", "1" * 64)]))
    active = Release.model_validate(release("rel-2", 2, [claim("shared/slug", "B", "b", "4" * 64)]))
    with pytest.raises(RevertError) as raised:
        revert_bundle(active, old, "A", compiler_identity="t")
    assert raised.value.code == "SLUG_COLLISION"


def test_r4_a_kind_change_on_the_same_slug_is_refused() -> None:
    entity = member("entity", "x/1", {"entity_id": "A"}, "5" * 64)
    old = Release.model_validate(release("rel-1", 1, [entity]))
    active_claim = claim("x/1", "A", "v", "6" * 64)
    active = Release.model_validate(release("rel-2", 2, [active_claim]))
    with pytest.raises(RevertError):
        revert_bundle(active, old, "A", compiler_identity="t")


def test_r5_a_live_revert_keeps_its_identity_when_the_read_back_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = Server(
        {"rel-1": OLD, "rel-2": ACTIVE}, {"GET releases/rel-3": (503, "SERVICE_UNAVAILABLE")}
    )
    code, report = run(monkeypatch, capsys, server, "--activate")
    assert code == 2 and report["stopped"] == "SERVICE_UNAVAILABLE"
    assert (report["release_id"], report["epoch"]) == ("rel-3", 3)


def test_r6_stale_concepts_follow_the_actual_member_slugs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = Server({"rel-1": OLD, "rel-2": ACTIVE}, {})
    code, report = run(monkeypatch, capsys, server, "--dry-run")
    assert code == 0
    assert report["members"] == ["legacy/field"]
    assert report["stale_concepts"] == ["concept/one"]
    assert server.writes == []
