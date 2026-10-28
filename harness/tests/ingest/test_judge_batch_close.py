"""RV7 acceptance, review round 1 (protected, written by Claude): close carries a verdict over only
to the content the judge saw.

Spec docs/design/slices/RV7-模型评审批次命令.md §2.4 (review R3). The candidate's content is read
from the platform's review detail (RV6e) before any point is closed, and each point must propose
exactly the judged content.
"""

from __future__ import annotations

from typing import Any

import pytest

from insurance_harness.ingest.judge_batch import JudgeBatchError, close_points, ingest
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.ingest.test_judge_batch import (  # noqa: F401
    answer,
    approve_all,
    leftover,
    prepared,
    publish,
    world,
)


def close(case: dict[str, Any], *, live: bool) -> dict[str, Any]:
    return close_points(
        case["run_root"],
        client=case["client"],
        product="1828",
        candidate="cand_old",
        issue=384,
        live=live,
    )


def test_a_leftover_proposing_other_content_keeps_its_point(
    world: dict[str, Any],  # noqa: F811
) -> None:
    prepared(world)
    first, second = world["keys"]
    answer(world, {first: ("reject", "值有误"), second: ("approve", "通过")})
    ingest(world["run_root"])
    publish(world, live=True)
    claims = world["claims"]
    other = claims[0].model_copy(update={"value": "180日"})  # the judge never saw 180日
    leftover(world, [other, claims[1]])
    result = close(world, live=True)
    assert [body["slugs"] for body in world["server"].rejections] == [[second]]
    assert result["skipped"] == {first: "content_differs"}
    assert result["closed"] == {second: "rejected"}


def test_a_detail_that_is_not_the_target_candidate_sends_nothing(
    world: dict[str, Any],  # noqa: F811
) -> None:
    prepared(world)
    approve_all(world)
    ingest(world["run_root"])
    publish(world, live=True)
    leftover(world, world["claims"])
    server = world["server"]
    detail = server.detail
    server.detail = lambda candidate: {**detail(candidate), "candidate_id": "cand_elsewhere"}
    with pytest.raises(JudgeBatchError) as refused:
        close(world, live=True)
    assert refused.value.code == "INVALID_RESPONSE"
    assert world["server"].rejections == []


def test_a_leftover_outside_the_pending_queue_sends_nothing(
    world: dict[str, Any],  # noqa: F811
) -> None:
    prepared(world)
    approve_all(world)
    ingest(world["run_root"])
    publish(world, live=True)
    leftover(world, world["claims"])
    world["server"].leftovers.clear()
    with pytest.raises(JudgeBatchError) as refused:
        close(world, live=True)
    assert refused.value.code == "CANDIDATE_NOT_PENDING"
    assert world["server"].rejections == []


def test_supersede_needs_the_judged_content_live_and_a_completed_record(
    world: dict[str, Any],  # noqa: F811
) -> None:
    prepared(world)
    approve_all(world)
    ingest(world["run_root"])
    leftover(world, world["claims"])
    unpublished = close(world, live=False)
    assert unpublished["supersede"] == [] and unpublished["reject"] == []
    assert set(unpublished["skipped"].values()) == {"not_live"}
    publish(world, live=True)
    server, slug = world["server"], world["keys"][0]
    server.active = {
        **server.active,
        "members": [m for m in server.active["members"] if m["logical_slug"] != slug],
    }
    result = close(world, live=False)
    assert result["supersede"] == [world["keys"][1]]
    assert result["skipped"] == {slug: "not_live"}
