"""RV7 review round 2, R3: close binds the candidate's content as the platform holds it.

Spec docs/design/slices/RV7-模型评审批次命令.md §2.4. What the leftover proposes is read from the
platform's review detail (RV6e), so no file of the same shape can stand for content the judge never
saw. The two counterexamples of the review run through the public CLI: a same-shape leftover
proposing 180日 where the judge saw 90日, before and after this batch published 90日. A read that
fails or a detail that cannot be bound sends nothing.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from insurance_harness.bundle.client import PlatformClient
from insurance_harness.ingest.judge_batch import JudgeBatchError, close_points, ingest
from insurance_harness.ingest.judge_batch import cli as command
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.ingest.test_judge_batch import (  # noqa: F401
    answer,
    leftover,
    prepared,
    publish,
    world,
)


def judged(case: dict[str, Any], first: str, second: str, *, published: bool) -> None:
    prepared(case)
    keys = case["keys"]
    verdicts = {"approve": ("approve", "通过"), "reject": ("reject", "值有误")}
    answer(case, {keys[0]: verdicts[first], keys[1]: verdicts[second]})
    ingest(case["run_root"])
    if published:
        assert publish(case, live=True)["stopped"] is None


def run_close(
    case: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, dict[str, Any] | str]:
    monkeypatch.setattr(command, "PlatformClient", lambda *_: case["client"])
    argv = ["close", "--run-root", str(case["run_root"]), "--product", "1828"]
    code = command.main([*argv, "--candidate", "cand_old", "--issue", "384", "--live"])
    out, err = capsys.readouterr()
    return code, json.loads(out) if code == 0 else err.strip()


def proposing_180(case: dict[str, Any]) -> None:
    """A leftover of the same shape as the judged change: same slugs, sizes and base."""
    claims = case["claims"]
    leftover(case, [claims[0].model_copy(update={"value": "180日"}), claims[1]])


def test_a_same_shape_leftover_proposing_other_content_is_not_closed(
    world: dict[str, Any],  # noqa: F811
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judged(world, "reject", "reject", published=False)
    proposing_180(world)
    code, result = run_close(world, capsys, monkeypatch)
    first, second = world["keys"]
    assert code == 0 and isinstance(result, dict)
    assert [body["slugs"] for body in world["server"].rejections] == [[second]]
    assert result["skipped"] == {first: "content_differs"}
    assert result["closed"] == {second: "rejected"}


def test_publishing_90_does_not_supersede_a_leftover_proposing_180(
    world: dict[str, Any],  # noqa: F811
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judged(world, "approve", "approve", published=True)
    proposing_180(world)
    code, result = run_close(world, capsys, monkeypatch)
    first, second = world["keys"]
    assert code == 0 and isinstance(result, dict)
    assert result["supersede"] == [second] and result["skipped"] == {first: "content_differs"}
    assert [body["slugs"] for body in world["server"].rejections] == [[second]]


def test_the_judged_content_closes_through_the_cli(
    world: dict[str, Any],  # noqa: F811
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judged(world, "approve", "reject", published=True)
    leftover(world, world["claims"])
    code, result = run_close(world, capsys, monkeypatch)
    first, second = world["keys"]
    assert code == 0 and isinstance(result, dict)
    assert result["supersede"] == [first] and result["reject"] == [second]
    assert result["closed"] == {first: "rejected", second: "rejected"}
    assert [body["slugs"] for body in world["server"].rejections] == [[first], [second]]


def test_supersede_needs_the_very_member_this_batch_published(
    world: dict[str, Any],  # noqa: F811
) -> None:
    judged(world, "approve", "approve", published=True)
    leftover(world, world["claims"])
    server, first = world["server"], world["keys"][0]
    server.active = {
        **server.active,
        "members": [
            {**m, "member_digest": "e" * 64} if m["logical_slug"] == first else m
            for m in server.active["members"]
        ],
    }
    result = close_points(
        world["run_root"], client=world["client"], product="1828", candidate="cand_old", issue=384
    )
    assert result["supersede"] == [world["keys"][1]]
    assert result["skipped"] == {first: "not_live"}


def test_a_pending_point_the_batch_never_judged_stays_open(
    world: dict[str, Any],  # noqa: F811
) -> None:
    judged(world, "reject", "reject", published=False)
    leftover(world, world["claims"])
    world["server"].leftovers["cand_old"]["removals"] = ["1828/gone"]
    result = close_points(
        world["run_root"],
        client=world["client"],
        product="1828",
        candidate="cand_old",
        issue=384,
        live=True,
    )
    assert result["unreviewed"] == ["1828/gone"]
    sent = [body["slugs"] for body in world["server"].rejections]
    assert sent == [[key] for key in sorted(world["keys"])]


def _status(detail: dict[str, Any]) -> dict[str, Any]:
    return {**detail, "status": "rejected"}


def _subjects(detail: dict[str, Any]) -> dict[str, Any]:
    return {**detail, "subjects": ["594"]}


def _payload(detail: dict[str, Any]) -> dict[str, Any]:
    members = [{**m, "payload": {"claim_id": "x"}} for m in detail["bundle_members"]]
    return {**detail, "bundle_members": members}


def _slug(detail: dict[str, Any]) -> dict[str, Any]:
    """Members and points agree on a slug that is not the claim's own key."""
    members = [{**m, "logical_slug": f"{m['logical_slug']}-x"} for m in detail["bundle_members"]]
    points = [{**p, "slug": f"{p['slug']}-x"} for p in detail["points"]]
    return {**detail, "bundle_members": members, "points": points}


def _orphan_point(detail: dict[str, Any]) -> dict[str, Any]:
    return {**detail, "bundle_members": detail["bundle_members"][1:]}


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (_status, "CANDIDATE_NOT_PENDING"),
        (_subjects, "CANDIDATE_NOT_PENDING"),
        (_payload, "CANDIDATE_CONTENT_INVALID"),
        (_slug, "CANDIDATE_CONTENT_INVALID"),
        (_orphan_point, "CANDIDATE_CONTENT_INVALID"),
    ],
)
def test_a_detail_that_cannot_be_bound_sends_nothing(
    world: dict[str, Any],  # noqa: F811
    change: Callable[[dict[str, Any]], dict[str, Any]],
    code: str,
) -> None:
    judged(world, "reject", "reject", published=False)
    leftover(world, world["claims"])
    server = world["server"]
    detail = server.detail
    server.detail = lambda candidate: change(detail(candidate))
    with pytest.raises(JudgeBatchError) as refused:
        close_points(
            world["run_root"],
            client=world["client"],
            product="1828",
            candidate="cand_old",
            issue=384,
            live=True,
        )
    assert refused.value.code == code
    assert server.rejections == [] and not (world["run_root"] / "close-1828.json").exists()


def test_a_failed_detail_read_sends_nothing(
    world: dict[str, Any],  # noqa: F811
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judged(world, "reject", "reject", published=False)
    leftover(world, world["claims"])
    server = world["server"]

    def unavailable(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and "/candidates/" in request.url.path:
            return httpx.Response(503, json={"success": False, "code": "SERVICE_UNAVAILABLE"})
        answered: httpx.Response = server(request)
        return answered

    world["client"] = PlatformClient(
        "https://weknora.test", "key-123", transport=httpx.MockTransport(unavailable)
    )
    code, error = run_close(world, capsys, monkeypatch)
    assert (code, error) == (1, "SERVICE_UNAVAILABLE")
    assert server.rejections == []
