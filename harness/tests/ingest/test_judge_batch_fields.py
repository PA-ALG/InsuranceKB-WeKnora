"""RV7 review round 2, R4: the field definitions a request showed the judge are bound.

Spec docs/design/slices/RV7-模型评审批次命令.md §2.1, §2.3. A changed definition, source guidance or
title changes the question the judge answered, so publishing an approval given to the old question
must stop with INPUTS_CHANGED before anything is sent. Fields no approved point relies on may
change freely.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.ingest.judge_batch import ingest
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.ingest.test_judge_batch import (  # noqa: F401
    answer,
    approve_all,
    prepared,
    publish,
    submitted,
    world,
)


def edit_field(case: dict[str, Any], field_key: str, **changes: str) -> None:
    path = case["repo"] / SCHEMA_PACK_CATALOG
    catalog = json.loads(path.read_text(encoding="utf-8"))
    for entry in catalog["entries"]:
        for field in entry["pack"]["fields"]:
            if field["field_key"] == field_key:
                field.update(changes)
    path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize(
    "changes",
    [
        {"description": "仅意外责任，排除疾病等待期"},
        {"source_guidance": "只看意外伤害条款"},
        {"short_title": "意外等待期"},
    ],
)
def test_a_field_definition_changed_after_judging_stops_publishing(
    world: dict[str, Any],  # noqa: F811
    changes: dict[str, str],
) -> None:
    prepared(world)
    approve_all(world)
    ingest(world["run_root"])
    edit_field(world, "waiting_period", **changes)
    result = publish(world, live=True)
    assert result["stopped"] == {"product": "1828", "code": "INPUTS_CHANGED"}
    assert submitted(world) == []
    assert not (world["run_root"] / "publish").exists()


def test_the_plan_binds_exactly_the_fields_the_requests_showed(
    world: dict[str, Any],  # noqa: F811
) -> None:
    plan = prepared(world)
    assert sorted(plan["fields"]["1828"]) == ["premium_grace_period", "waiting_period"]
    assert all(len(digest) == 64 for digest in plan["fields"]["1828"].values())


def test_a_field_no_approved_point_relies_on_may_change(
    world: dict[str, Any],  # noqa: F811
) -> None:
    prepared(world)
    waiting, grace = world["keys"]
    answer(world, {waiting: ("approve", "通过"), grace: ("reject", "属于其他字段")})
    ingest(world["run_root"])
    edit_field(world, "premium_grace_period", description="另一种说法")
    result = publish(world, live=True)
    assert result["stopped"] is None
    assert result["products"]["1828"]["status"] == "published"
    assert result["products"]["1828"]["slugs"] == [waiting]
