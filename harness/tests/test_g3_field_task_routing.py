from __future__ import annotations

from insurance_harness.knowledge_compiler import g3_bounded_model_execution as runtime
from insurance_harness.knowledge_compiler.g3_field_tasks import (
    DiscoveryFieldProposalV1,
    adapt_discovery_field_tasks,
)
from tests.test_batch_entity_resolution_830_g3 import _entry


def test_routing_is_bounded_preserves_offsets_and_prefers_field_guidance():
    assert hasattr(runtime, "route_field_task_sources"), "runtime has no shared field routing"
    entry = _entry(
        material_id="route-a",
        text="无关内容。" * 3000 + "\n等待期\n本合同等待期为九十日。\n" + "附录。" * 3000,
    )
    tasks = adapt_discovery_field_tasks(
        entity_id="entity-a",
        entity_version="v1",
        material_ids=("route-a",),
        proposals=(
            DiscoveryFieldProposalV1(
                field_key="waiting_period", short_title="等待期", source_guidance="等待期"
            ),
        ),
        discovery_protocol_version="discovery.v1",
    )
    rows = runtime.route_field_task_sources(
        tasks, {"s1": entry.blocks[0]}, max_source_chars=1200, max_span_chars=600
    )
    assert sum(len(span["quote"]) for row in rows for span in row["spans"]) <= 1200
    assert any("本合同等待期为九十日" in span["quote"] for row in rows for span in row["spans"])
    for row in rows:
        assert row["source"]["source_hash"] == entry.blocks[0].source_hash
        for span in row["spans"]:
            assert entry.blocks[0].text[span["start"] : span["end"]] == span["quote"]
    assert rows == runtime.route_field_task_sources(
        tasks, {"s1": entry.blocks[0]}, max_source_chars=1200, max_span_chars=600
    )


def test_schema_and_discovery_route_through_same_bounded_contract():
    assert hasattr(runtime, "route_field_task_sources"), "runtime has no shared field routing"
    assert hasattr(runtime, "adapt_catalog_field_tasks"), (
        "runtime bypasses shared FieldTask adapter"
    )


def test_runtime_bounded_scheduler_continues_siblings_and_keeps_order():
    import asyncio

    assert hasattr(runtime, "_run_bounded_call_tasks"), "runtime has no bounded call scheduler"
    active = peak = 0
    completed = []

    async def one(value):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.01 if value != 1 else 0.002)
            if value == 1:
                raise ValueError("local invalid output")
            completed.append(value)
            return value
        finally:
            active -= 1

    result = asyncio.run(runtime._run_bounded_call_tasks(tuple(range(4)), one, worker_limit=2))
    assert peak == 2
    assert completed == [0, 2, 3]
    assert result[0] == 0 and isinstance(result[1], ValueError) and result[2:] == (2, 3)


def test_projector_rejects_quotes_outside_offered_source_spans():
    import pytest

    assert hasattr(runtime, "validate_routed_selections"), "projector does not enforce routed spans"
    offered = [{"source_ref": "a", "spans": [{"start": 10, "end": 17, "quote": "等待期为九十日"}]}]
    runtime.validate_routed_selections((("a", "九十日"),), offered)
    with pytest.raises(ValueError, match="offered"):
        runtime.validate_routed_selections((("a", "未展示的原文"),), offered)
    with pytest.raises(ValueError, match="offered"):
        runtime.validate_routed_selections((("other", "九十日"),), offered)


def test_unrelated_history_is_not_segmented(monkeypatch):
    from insurance_harness.knowledge_compiler import g3_field_task_routing as routing
    from insurance_harness.knowledge_compiler.g3_field_tasks import FieldTaskSourceV1

    current = _entry(material_id="current", text="等待期九十日。")
    history = _entry(material_id="history", text="无关历史条款。" * 10000)
    block = current.blocks[0]
    tasks = adapt_discovery_field_tasks(
        entity_id="entity-a", entity_version="v1", material_ids=("current",),
        proposals=(DiscoveryFieldProposalV1(field_key="waiting", short_title="等待期"),),
        discovery_protocol_version="discovery.v1",
        allowed_sources=(FieldTaskSourceV1(material_id="current", revision_id=block.revision_id,
            block_id=block.block_id, source_hash=block.source_hash,
            parser_identity=block.parser_identity),),
    )
    expected = routing.route_field_task_sources(tasks, {"current": block})
    original = routing._spans
    visited = []

    def observe(text, limit):
        visited.append(text)
        return original(text, limit)

    monkeypatch.setattr(routing, "_spans", observe)
    assert routing.route_field_task_sources(
        tasks, {"current": block, "history": history.blocks[0]}
    ) == expected
    assert visited == [block.text], "unrelated history adds document segmentation work"
