"""RV7 acceptance, review round 1 (protected, written by Claude): publish records and recovery.

Spec docs/design/slices/RV7-模型评审批次命令.md §2.3 (review R1, R5). The fake platform has the real
idempotent semantics: candidates are kept by bundle digest, the same decision input returns the
same decision, a repeated activation returns the release it made, and samples keep existing ones.
A lost response means the platform committed the step but the caller never heard back.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from insurance_harness.bundle.canonical import member_digest
from insurance_harness.bundle.client import PlatformClient
from insurance_harness.ingest.judge_batch import ingest
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.ingest.test_judge_batch import (  # noqa: F401
    approve_all,
    prepared,
    publish,
    world,
)

PREFIX = "/api/v1/enterprise/spaces/space-1/"
_ATTEMPT = re.compile(r"attempt-(\d+)\.json")


def ok(data: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"success": True, "data": data})


class LedgerPlatform:
    def __init__(self, active: dict[str, Any]) -> None:
        self.active = {**active, "candidate_id": ""}
        self.releases: dict[str, dict[str, Any]] = {self.active["id"]: self.active}
        self.candidates: dict[str, dict[str, Any]] = {}
        self.decisions: dict[str, str] = {}
        self.activated: dict[str, str] = {}
        self.samples: dict[str, dict[str, dict[str, Any]]] = {}
        self.seen: list[tuple[str, str, Any]] = []
        self.lose: set[str] = set()
        self.move_head = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path.removeprefix(PREFIX)
        self.seen.append((request.method, path, body))
        step, response = self.handle(request.method, path, body)
        if step in self.lose:
            self.lose.discard(step)
            return httpx.Response(503, json={"success": False, "code": "SERVICE_UNAVAILABLE"})
        return response

    def handle(self, method: str, path: str, body: Any) -> tuple[str, httpx.Response]:
        parts = path.split("/")
        if method == "GET" and path == "releases/active":
            return "active", ok(self.active)
        if method == "GET" and parts[0] == "releases":
            return "read_back", ok(self.releases[parts[1]])
        if method == "POST" and path == "candidates":
            canonical = json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
            digest = hashlib.sha256(canonical).hexdigest()
            candidate = f"cand_{digest[:12]}"
            status = "existing" if candidate in self.candidates else "created"
            self.candidates.setdefault(candidate, body)
            data = {"id": candidate, "status": status, "bundle_digest": digest}
            return "submit", ok(data, 201 if status == "created" else 200)
        if method == "POST" and parts[-1] == "decisions":
            key = parts[1] + json.dumps(body, sort_keys=True)
            decision = "dec_" + hashlib.sha256(key.encode()).hexdigest()[:12]
            self.decisions[decision] = parts[1]
            data = {"id": decision, "candidate_id": parts[1], "outcome": body["outcome"]}
            return "decide", ok({**data, "digest": "e" * 64})
        if method == "POST" and parts[-1] == "activations":
            return "activate", self.activate(parts[1], body["decision_id"])
        if method == "POST" and parts[-1] == "samples":
            return "samples", self.sample(parts[1], body["samples"])
        raise AssertionError(f"unexpected {method} {path}")

    def activate(self, candidate: str, decision: str) -> httpx.Response:
        assert self.decisions.get(decision) == candidate
        if candidate in self.activated:
            return ok(self.releases[self.activated[candidate]])
        if self.move_head:  # someone else activated first
            self.move_head = False
            epoch = self.active["epoch"] + 1
            moved = {**self.active, "id": "rel_other", "epoch": epoch, "candidate_id": "cand_x"}
            self.active = self.releases["rel_other"] = moved
        bundle = self.candidates[candidate]
        if bundle["base_release_id"] != self.active["id"]:
            return httpx.Response(409, json={"success": False, "code": "NEEDS_REBASE"})
        replaced = {m["logical_slug"] for m in bundle["members"]} | set(bundle["removals"])
        kept = [m for m in self.active["members"] if m["logical_slug"] not in replaced]
        release = {
            "id": f"rel_{len(self.releases) + 1}",
            "epoch": self.active["epoch"] + 1,
            "candidate_id": candidate,
            "base_release_id": self.active["id"],
            "members": kept + bundle["members"],
        }
        self.releases[release["id"]] = self.active = release
        self.activated[candidate] = release["id"]
        return ok(release)

    def sample(self, release: str, picks: list[dict[str, str]]) -> httpx.Response:
        kept = self.samples.setdefault(release, {})
        digests = {m["logical_slug"]: m["member_digest"] for m in self.releases[release]["members"]}
        for pick in picks:
            kept.setdefault(
                pick["slug"],
                {
                    "id": f"smp_{len(kept) + 1}",
                    "space_id": "space-1",
                    "release_id": release,
                    "logical_slug": pick["slug"],
                    "member_digest": digests[pick["slug"]],
                    "stratum": pick["stratum"],
                    "created_by": "service",
                    "created_at": "2026-10-28T00:00:00Z",
                },
            )
        return ok({"samples": [kept[pick["slug"]] for pick in picks]})


@pytest.fixture
def ledger(world: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    """Everything approved and ingested; every machine claim is sampled."""
    server = LedgerPlatform(world["server"].active)
    world["server"] = server
    world["client"] = PlatformClient(
        "https://weknora.test", "key-123", transport=httpx.MockTransport(server)
    )
    policy = {"version": "test", "default": {"rate": 1.0, "minimum": 1, "target": 0.99}}
    world["spot"].write_text(json.dumps(policy))
    prepared(world)
    approve_all(world)
    ingest(world["run_root"])
    return world


def attempts(case: dict[str, Any]) -> list[Path]:
    found = [
        path
        for path in (case["run_root"] / "publish" / "1828").iterdir()
        if _ATTEMPT.fullmatch(path.name)
    ]
    return sorted(found, key=lambda path: int(_ATTEMPT.fullmatch(path.name).group(1)))  # type: ignore[union-attr]


def record(case: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(attempts(case)[-1].read_text(encoding="utf-8"))
    return data


def posts(case: dict[str, Any]) -> list[tuple[str, Any]]:
    return [(path, body) for method, path, body in case["server"].seen if method == "POST"]


@pytest.mark.parametrize("step", ["submit", "decide", "activate", "read_back", "samples"])
def test_a_lost_response_is_reconciled_and_the_run_finishes(
    ledger: dict[str, Any], step: str
) -> None:
    server = ledger["server"]
    server.lose = {step}
    first = publish(ledger, live=True)
    assert first["stopped"] == {"product": "1828", "code": "SERVICE_UNAVAILABLE"}
    second = publish(ledger, live=True)
    assert second["stopped"] is None
    assert second["products"]["1828"]["status"] == "published"
    bodies = [body for path, body in posts(ledger) if path == "candidates"]
    assert len(server.candidates) == 1, "one frozen candidate, never a regenerated one"
    assert all(body == bodies[0] for body in bodies)
    done = record(ledger)
    release = server.active["id"]
    assert done["stage"] == "sampled" and done["release"] == release
    assert done["candidate"] == server.active["candidate_id"]
    assert sorted(server.samples[release]) == sorted(ledger["keys"]) and done["samples"] == 2


def test_a_completed_record_is_never_rewritten(ledger: dict[str, Any]) -> None:
    first = publish(ledger, live=True)["products"]["1828"]
    path = attempts(ledger)[-1]
    before = path.read_bytes()
    sent = len(posts(ledger))
    again = publish(ledger, live=True)["products"]["1828"]
    assert again["status"] == "already_published"
    assert (again["candidate"], again["release"]) == (first["candidate"], first["release"])
    assert path.read_bytes() == before and len(posts(ledger)) == sent


def test_needs_rebase_proves_nothing_went_live_and_the_next_run_starts_a_new_attempt(
    ledger: dict[str, Any],
) -> None:
    server = ledger["server"]
    server.move_head = True
    first = publish(ledger, live=True)
    assert first["stopped"] == {"product": "1828", "code": "NEEDS_REBASE"}
    second = publish(ledger, live=True)
    assert second["stopped"] is None
    files = attempts(ledger)
    assert len(files) == 2
    assert json.loads(files[0].read_text(encoding="utf-8"))["status"] == "needs_rebase"
    assert record(ledger)["stage"] == "sampled"
    assert server.active["candidate_id"] == record(ledger)["candidate"]


def test_a_changed_frozen_bundle_is_refused(ledger: dict[str, Any]) -> None:
    ledger["server"].lose = {"decide"}
    publish(ledger, live=True)
    frozen = next(attempts(ledger)[-1].parent.glob("attempt-1.bundle.json"))
    data = json.loads(frozen.read_text(encoding="utf-8"))
    data["compiler_identity"] = "someone-else"
    frozen.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    sent = len(posts(ledger))
    again = publish(ledger, live=True)
    assert again["stopped"] == {"product": "1828", "code": "RECORD_INVALID"}
    assert len(posts(ledger)) == sent


def _revalued(member: dict[str, Any], value: str) -> dict[str, Any]:
    payload = {**member["payload"], "value": value}
    return {**member, "payload": payload, "member_digest": member_digest(payload)}


def test_already_published_needs_the_judged_content_to_be_live(ledger: dict[str, Any]) -> None:
    publish(ledger, live=True)
    server, slug = ledger["server"], ledger["keys"][0]
    members = [
        _revalued(m, "180日") if m["logical_slug"] == slug else m for m in server.active["members"]
    ]
    later = {**server.active, "id": "rel_later", "epoch": 9, "members": members}
    server.active = server.releases["rel_later"] = later
    again = publish(ledger, live=True)
    assert again["stopped"] == {"product": "1828", "code": "CONTENT_CHANGED"}


def test_a_live_value_changed_after_judging_is_not_taken_as_published(
    ledger: dict[str, Any],
) -> None:
    server, slug = ledger["server"], ledger["keys"][0]
    judged = next(c for c in ledger["claims"] if c.logical_key == slug)
    payload = {**judged.model_dump(mode="json"), "value": "180日"}  # same citations
    members = [
        {**m, "payload": payload, "member_digest": member_digest(payload)}
        if m["logical_slug"] == slug
        else m
        for m in server.active["members"]
    ]
    server.active = {**server.active, "members": members}
    result = publish(ledger, live=True)
    assert result["stopped"] == {"product": "1828", "code": "CONTENT_CHANGED"}
    assert posts(ledger) == []
