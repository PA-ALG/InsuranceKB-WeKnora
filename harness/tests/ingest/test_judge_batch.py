"""RV7 acceptance (protected, written by Claude): the model-judge batch command.

Spec docs/design/slices/RV7-模型评审批次命令.md §2, §5. A compile's changes against Active are put
to an independent judge through hash-checked files; approved points are published as machine review
with the judge's policy and reviewer, never as a person's decision; leftovers of a human-queue
candidate are closed through the RV6d machine route. Offline: fake HTTP, fake judge answers, and the
files of test_publish_cli / test_claim_changes_publish.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest

from insurance_harness.bundle.client import PlatformClient
from insurance_harness.compilers.schema_fields.claims import claims_from
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.eval.judge_files import stored_requests
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.ingest.judge_batch import (
    JudgeBatchError,
    close_points,
    ingest,
    prepare,
    publish_batch,
)
from tests.changes.test_claim_changes_publish import DeltaPlatform, active
from tests.compilers.schema_fields.test_publish_cli import SOURCE, Reader
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.compilers.schema_fields.test_publish_registry import registry_file

POLICY = "rv-judge:test:2026-10-28"
REVIEWER = "judge-test-xhigh"
PROTOCOL = "2026-10-27.1"


class JudgePlatform(DeltaPlatform):
    """Activation makes the submitted claims Active, so a rerun sees them as published."""

    def __init__(self, active_release: dict[str, Any]) -> None:
        super().__init__(active_release)
        self.rejections: list[dict[str, Any]] = []
        self.decided: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1/enterprise/spaces/space-1/")
        if path.endswith("/points/decisions"):
            body = json.loads(request.content)
            self.rejections.append(body)
            if set(body["slugs"]) & self.decided:
                return httpx.Response(409, json={"success": False, "code": "MEMBER_DECIDED"})
            self.decided |= set(body["slugs"])
            points = [{"slug": slug, "status": "rejected"} for slug in body["slugs"]]
            data = {"status": "pending", "release_id": None, "epoch": None, "points": points}
            return httpx.Response(201, json={"success": True, "data": data})
        response = super().__call__(request)
        if path.endswith("/activations") and response.status_code == 200:
            submitted = {m["logical_slug"]: m for m in self.members}
            kept = [m for m in self.active["members"] if m["logical_slug"] not in submitted]
            self.active = {"id": "rel_1", "epoch": 4, "members": kept + list(submitted.values())}
        return response


@pytest.fixture
def world(tmp_path: Path, request: pytest.FixtureRequest) -> dict[str, Any]:
    """Active holds the old compiler's waiting period ("旧值") and lacks the grace period, so the
    upgraded compile yields one UPGRADE and one ADD point."""
    request.getfixturevalue("prepared_files")
    output_path = tmp_path / "1828/output.json"
    raw = json.loads(output_path.read_text())
    old = claims_from(
        CompileOutput.model_validate(raw), SOURCE, {"保险条款.pdf": SourceRevision("k-1", 2)}
    )
    quote = (
        old[0]
        .evidence[0]
        .model_copy(
            update={"quote": "旧值", "quote_sha256": hashlib.sha256("旧值".encode()).hexdigest()}
        )
    )
    server = JudgePlatform(
        active([old[0].model_copy(update={"value": "旧值", "evidence": [quote]})])
    )
    raw["value_protocol"] = PROTOCOL
    output_path.write_text(json.dumps(raw))
    client = PlatformClient(
        "https://weknora.test", "key-123", transport=httpx.MockTransport(server)
    )
    spot = tmp_path / "spot.json"
    spot.write_text(
        json.dumps({"version": "test", "default": {"rate": 0.0, "minimum": 0, "target": 0.99}})
    )
    run_root = tmp_path / "judge-run"
    return {
        "server": server,
        "client": client,
        "registry": registry_file(tmp_path),
        "compile_root": tmp_path,
        "run_root": run_root,
        "reader": Reader("https://weknora.test", "key-123"),
        "repo": tmp_path / "repo",
        "spot": spot,
        "keys": [claim.logical_key for claim in old],
    }


def prepared(world: dict[str, Any]) -> dict[str, Any]:
    return prepare(
        world["run_root"],
        registry=world["registry"],
        compile_root=world["compile_root"],
        products=["1828"],
        reader=world["reader"],
        client=world["client"],
        policy_ref=POLICY,
        reviewer=REVIEWER,
        model="judge-test",
        repo=world["repo"],
    )


def answer(world: dict[str, Any], verdicts: dict[str, tuple[str, str]]) -> Path:
    """Write the judge's answer for the single request, in the request's slug order."""
    session: Path = world["run_root"] / "sessions" / "s01"
    question = json.loads("\n".join(stored_requests(session)[0].user.split("\n")))
    points = [
        {
            "slug": p["slug"],
            "verdict": verdicts[p["slug"]][0],
            "category": verdicts[p["slug"]][1],
            "reason": "依据条款第1页",
        }
        for p in question["points"]
    ]
    path = session / "responses" / "001.json"
    path.write_text(json.dumps({"points": points}, ensure_ascii=False), encoding="utf-8")
    return path


def approve_all(world: dict[str, Any]) -> None:
    answer(world, {key: ("approve", "通过") for key in world["keys"]})


def test_prepare_puts_only_changed_points_to_the_judge_and_never_calls_codex(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_: Any, **__: Any) -> None:
        raise AssertionError("prepare must not start processes")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    plan = prepared(world)
    run = world["run_root"]
    changes = json.loads((run / "data" / "changes-1828.json").read_text(encoding="utf-8"))
    kinds = {p["slug"]: p["change"] for p in changes["points"]}
    assert kinds == {world["keys"][0]: "upgrade", world["keys"][1]: "add"}
    upgrade = next(p for p in changes["points"] if p["change"] == "upgrade")
    assert upgrade["live"]["value"] == "旧值" and upgrade["new"]["value"] == "90日"
    assert plan["policy_ref"] == POLICY and plan["reviewer"] == REVIEWER
    assert plan["sessions"] == {"s01": {"products": ["1828"], "slugs": sorted(kinds)}}
    session = run / "sessions" / "s01"
    requests = stored_requests(session)
    assert len(requests) == 1
    stored = json.loads((session / "requests" / "001.json").read_text(encoding="utf-8"))
    assert stored["request_sha256"] == requests[0].sha256
    assert (session / "AGENTS.md").read_text(encoding="utf-8").strip()
    assert any((session / "sources" / "1828").glob("*.txt"))
    script = (run / "run.sh").read_text(encoding="utf-8")
    assert "codex exec" in script and "sessions/s01" in script and "judge-test" in script
    with pytest.raises(JudgeBatchError) as again:
        prepared(world)
    assert again.value.code == "RUN_EXISTS"


def test_a_run_root_inside_a_git_repository_is_refused(world: dict[str, Any]) -> None:
    inside = world["compile_root"] / "checkout"
    (inside / ".git").mkdir(parents=True)
    world["run_root"] = inside / "run"
    with pytest.raises(JudgeBatchError) as refused:
        prepared(world)
    assert refused.value.code == "RUN_ROOT_IN_GIT"


def test_ingest_writes_verdicts_and_a_summary(world: dict[str, Any]) -> None:
    prepared(world)
    first, second = world["keys"]
    answer(world, {first: ("approve", "通过"), second: ("reject", "属于其他字段")})
    summary = ingest(world["run_root"])
    assert summary["products"]["1828"]["approve"] == 1
    assert summary["products"]["1828"]["reject_by"] == {"属于其他字段": 1}
    assert summary["ingested_at"]
    rows = json.loads((world["run_root"] / "verdicts" / "1828.json").read_text(encoding="utf-8"))
    assert {row["slug"]: row["verdict"] for row in rows} == {first: "approve", second: "reject"}
    assert ingest(world["run_root"])["products"] == summary["products"], "re-runnable"


@pytest.mark.parametrize(
    ("damage", "code"),
    [
        ("missing", "ANSWER_INVALID"),
        ("extra", "ANSWER_INVALID"),
        ("duplicate", "ANSWER_INVALID"),
        ("category", "ANSWER_INVALID"),
        ("mismatch", "ANSWER_INVALID"),
        ("blank", "ANSWER_INVALID"),
        ("request", "REQUEST_CHANGED"),
        ("no-answer", "ANSWER_MISSING"),
    ],
)
def test_ingest_refuses_bad_answers_and_writes_nothing(
    world: dict[str, Any], damage: str, code: str
) -> None:
    prepared(world)
    path = answer(world, {key: ("approve", "通过") for key in world["keys"]})
    data = json.loads(path.read_text(encoding="utf-8"))
    points = data["points"]
    if damage == "missing":
        points.pop()
    elif damage == "extra":
        points.append({**points[0], "slug": "1828/unknown_field"})
    elif damage == "duplicate":
        points[1] = dict(points[0])
    elif damage == "category":
        points[0].update(verdict="reject", category="不喜欢")
    elif damage == "mismatch":
        points[0].update(verdict="reject", category="通过")
    elif damage == "blank":
        points[0]["reason"] = "  "
    elif damage == "request":
        request = path.parents[1] / "requests" / "001.json"
        stored = json.loads(request.read_text(encoding="utf-8"))
        stored["user_lines"][0] += " "
        request.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
    elif damage == "no-answer":
        path.unlink()
    if damage not in {"request", "no-answer"}:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(JudgeBatchError) as refused:
        ingest(world["run_root"])
    assert refused.value.code == code
    assert not (world["run_root"] / "verdicts").exists()
    assert not (world["run_root"] / "summary.json").exists()


def publish(world: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return publish_batch(
        world["run_root"],
        registry=world["registry"],
        compile_root=world["compile_root"],
        reader=world["reader"],
        client=world["client"],
        issue=403,
        repo=world["repo"],
        spot_check_policy=world["spot"],
        **extra,
    )


def submitted(world: dict[str, Any]) -> list[Any]:
    return [body for method, path, body in world["server"].seen if method == "POST"]


def test_the_dry_run_builds_a_machine_candidate_of_approved_points_and_sends_nothing(
    world: dict[str, Any],
) -> None:
    prepared(world)
    first, second = world["keys"]
    answer(world, {first: ("approve", "通过"), second: ("reject", "遗漏关键内容")})
    ingest(world["run_root"])
    result = publish(world)
    row = result["products"]["1828"]
    assert result["stopped"] is None and row["claims"] == 1 and row["changes"] == {"upgrade": 1}
    assert submitted(world) == []
    dry = json.loads((world["run_root"] / "publish-dry.json").read_text(encoding="utf-8"))
    assert dry["products"]["1828"]["claims"] == 1


def test_live_publishes_as_machine_review_and_a_rerun_skips_what_is_already_live(
    world: dict[str, Any],
) -> None:
    prepared(world)
    approve_all(world)
    ingest(world["run_root"])
    result = publish(world, live=True)
    row = result["products"]["1828"]
    assert result["stopped"] is None and row["release"] == "rel_1" and row["claims"] == 2
    posts = {path: body for method, path, body in world["server"].seen if method == "POST"}
    claims = [m for m in posts["candidates"]["members"] if m["kind"] == "claim"]
    assert {m["logical_slug"] for m in claims} == set(world["keys"])
    for member in claims:
        review = member["payload"]["review"]
        assert review["mode"] == "machine" and "policy_ref" not in review
        assert review["reviewer"] == REVIEWER
    decision = posts["candidates/cand_1/decisions"]
    assert decision["mode"] == "machine" and decision["policy_ref"] == POLICY
    assert decision["outcome"] == "approve" and "403" in decision["reason"]
    before = len(submitted(world))
    again = publish(world, live=True)
    assert again["products"]["1828"]["status"] == "already_published"
    assert len(submitted(world)) == before, "nothing is submitted twice"


def test_a_compile_changed_after_judging_stops_the_batch(world: dict[str, Any]) -> None:
    prepared(world)
    approve_all(world)
    ingest(world["run_root"])
    path = world["compile_root"] / "1828/output.json"
    raw = json.loads(path.read_text())
    raw["fields"][0]["value"] = "100日"
    path.write_text(json.dumps(raw))
    result = publish(world, live=True)
    assert result["stopped"] == {"product": "1828", "code": "CONTENT_CHANGED"}
    assert submitted(world) == []


def test_a_platform_refusal_stops_at_the_first_product_and_is_recorded(
    world: dict[str, Any],
) -> None:
    prepared(world)
    approve_all(world)
    ingest(world["run_root"])
    world["server"].fail_activation = True
    result = publish(world, live=True)
    assert result["stopped"] == {"product": "1828", "code": "NEEDS_REBASE"}
    recorded = json.loads((world["run_root"] / "publish-live.json").read_text(encoding="utf-8"))
    assert recorded["stopped"] == {"product": "1828", "code": "NEEDS_REBASE"}


def test_close_rejects_judge_rejected_and_superseded_points_one_by_one(
    world: dict[str, Any],
) -> None:
    prepared(world)
    first, second = world["keys"]
    answer(world, {first: ("approve", "通过"), second: ("reject", "值有误")})
    ingest(world["run_root"])
    publish(world, live=True)
    dry = close_points(
        world["run_root"], client=world["client"], product="1828", candidate="cand_old", issue=384
    )
    assert world["server"].rejections == []
    assert dry["reject"] == [second] and dry["supersede"] == [first]
    world["server"].decided.add(second)  # someone already closed it
    result = close_points(
        world["run_root"],
        client=world["client"],
        product="1828",
        candidate="cand_old",
        issue=384,
        live=True,
    )
    assert [body["slugs"] for body in world["server"].rejections] == [[first], [second]]
    for body in world["server"].rejections:
        assert set(body) == {"slugs", "outcome", "reason", "policy_ref"}
        assert body["outcome"] == "reject" and body["policy_ref"] == POLICY
    assert "cand_1" in world["server"].rejections[0]["reason"]
    assert result["closed"] == {first: "rejected", second: "already_decided"}


def test_the_client_lists_the_review_queue_and_rejects_points() -> None:
    seen: list[tuple[str, str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, str(request.url), body))
        if request.method == "GET":
            items = [
                {
                    "candidate_id": "cand_9",
                    "subjects": ["594"],
                    "point_count": 2,
                    "pending_points": 2,
                    "status": "pending",
                }
            ]
            return httpx.Response(200, json={"success": True, "data": {"items": items}})
        data = {
            "status": "rejected",
            "release_id": None,
            "epoch": None,
            "points": [{"slug": "594/a", "status": "rejected"}],
        }
        return httpx.Response(201, json={"success": True, "data": data})

    client = PlatformClient(
        "https://weknora.test", "key-123", transport=httpx.MockTransport(handler)
    )
    queue = client.review_queue("space-1", "pending")
    assert [(item.candidate_id, item.subjects, item.pending_points) for item in queue] == [
        ("cand_9", ["594"], 2)
    ]
    assert client.reject_points("space-1", "cand_9", ["594/a"], "理由", "policy@1") == "rejected"
    assert seen[0][1].endswith("/spaces/space-1/candidates?status=pending")
    assert seen[1][1].endswith("/spaces/space-1/candidates/cand_9/points/decisions")
    assert seen[1][2] == {
        "slugs": ["594/a"],
        "outcome": "reject",
        "reason": "理由",
        "policy_ref": "policy@1",
    }
