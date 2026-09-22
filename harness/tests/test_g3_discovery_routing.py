from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from typing import Any

import pytest

from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import SourceBlock

MODULE = "insurance_harness.knowledge_compiler.g3_discovery_routing"


def _route(sources: dict[str, SourceBlock], **kwargs: object) -> dict[str, Any]:
    assert importlib.util.find_spec(MODULE) is not None, "bounded discovery routing is missing"
    result: dict[str, Any] = importlib.import_module(MODULE).route_discovery_sources(
        sources, **kwargs
    )
    return result


def _source(material: str, text: str, *, block: str = "block-1", page: int = 1) -> SourceBlock:
    return SourceBlock(
        tenant_id=7,
        space_id="space",
        raw_kb_id="raw",
        knowledge_id=material,
        parse_attempt=1,
        revision_id="revision-" + material,
        source_hash=hashlib.sha256(material.encode()).hexdigest(),
        parse_hash=hashlib.sha256((material + "-parse").encode()).hexdigest(),
        parser_identity="parser",
        block_id=block,
        page_number=page,
        text=text,
        source_type="DOCUMENT",
    )


def test_later_independent_knowledge_is_offered_without_schema_terms() -> None:
    text = "普通说明甲" * 400 + "\n附录\n独立知识：专属家庭联络流程需要提前确认接听时间。"
    result = _route({"a": _source("manual-a", text)}, max_source_chars=200, max_span_chars=100)
    offered = "".join(s["quote"] for r in result["source_options"] for s in r["spans"])
    assert "专属家庭联络流程" in offered
    assert text[:100] in offered
    assert not result["coverage"]["complete"]
    assert result["coverage"]["offered_chars"] <= 200


def test_material_round_robin_does_not_reward_many_blocks() -> None:
    sources = {
        **{
            f"a-{i}": _source("material-a", "甲" * 100, block=f"block-{i}", page=i + 1)
            for i in range(10)
        },
        "b": _source("material-b", "乙" * 1000),
    }
    result = _route(sources, max_source_chars=400, max_span_chars=100)
    counts: dict[str, int] = {}
    for row in result["source_options"]:
        key = row["source"]["knowledge_id"]
        counts[key] = counts.get(key, 0) + sum(len(s["quote"]) for s in row["spans"])
    assert counts == {"material-a": 200, "material-b": 200}
    assert result["coverage"]["represented_material_count"] == 2
    assert any(row["source"]["page_number"] == 10 for row in result["source_options"])


def test_original_offsets_metadata_and_complete_partition_are_preserved() -> None:
    text = "第一章\r\n A😀 e\u0301。\n" + "内部未展示的正文甲" * 100 + "\n尾部独立知识。"
    sources = {"source-a": _source("manual", text)}
    result = _route(sources, max_source_chars=100, max_span_chars=50)
    row = result["source_options"][0]
    assert row["source"] == sources["source-a"].model_dump(exclude={"text"})
    for span in row["spans"]:
        assert text[span["start"] : span["end"]] == span["quote"]
        assert len(span["quote"]) <= 50
    coverage = result["coverage"]
    record = coverage["sources"][0]
    ranges = sorted(record["offered_ranges"] + record["omitted_ranges"], key=lambda r: r["start"])
    assert ranges[0]["start"] == 0
    assert ranges[-1]["end"] == len(text)
    assert all(a["end"] == b["start"] for a, b in zip(ranges, ranges[1:], strict=False))
    offered = sum(r["end"] - r["start"] for r in record["offered_ranges"])
    omitted = sum(r["end"] - r["start"] for r in record["omitted_ranges"])
    assert offered == record["offered_chars"] == coverage["offered_chars"]
    assert omitted == record["omitted_chars"] == coverage["omitted_chars"]
    assert offered + omitted == record["total_chars"] == coverage["total_chars"] == len(text)
    assert (
        coverage["total_span_count"]
        == coverage["offered_span_count"] + coverage["omitted_span_count"]
    )
    assert "内部未展示的正文" not in json.dumps(coverage, ensure_ascii=False)
    assert not any(key in r for r in ranges for key in ("quote", "text", "heading"))
    assert coverage["offset_unit"] == "UNICODE_CODE_POINT"


def test_order_uses_page_and_is_independent_of_input_mapping_order() -> None:
    sources = {
        "aaa-page9": _source("manual", "后" * 100, block="a", page=9),
        "zzz-page1": _source("manual", "前" * 100, block="z", page=1),
    }
    first = _route(sources, max_source_chars=100, max_span_chars=100)
    assert first["source_options"][0]["source_ref"] == "zzz-page1"
    assert first == _route(
        dict(reversed(list(sources.items()))), max_source_chars=100, max_span_chars=100
    )


def test_small_budget_reports_unrepresented_materials_without_partial_quotes() -> None:
    sources = {name: _source(name, name * 100) for name in ("a", "b", "c")}
    result = _route(sources, max_source_chars=100, max_span_chars=100)
    coverage = result["coverage"]
    assert coverage["material_count"] == 3
    assert coverage["represented_material_count"] == 1
    assert coverage["offered_chars"] == 100
    assert coverage["omitted_chars"] == 200
    assert len(coverage["sources"]) == 3


def test_short_and_empty_inputs_have_truthful_full_coverage() -> None:
    short = _route({"a": _source("a", "全部内容。")})
    assert short["coverage"]["complete"]
    assert short["coverage"]["omitted_chars"] == 0
    assert short["coverage"]["sources"][0]["omitted_ranges"] == []
    empty = _route({})
    assert empty["source_options"] == []
    assert empty["coverage"]["complete"]
    assert empty["coverage"]["total_chars"] == empty["coverage"]["material_count"] == 0


@pytest.mark.parametrize(
    "budget,span",
    [
        (0, 1),
        (-1, 1),
        (10, 0),
        (10, -1),
        (10, 11),
        (True, 1),
        (100, False),
        (100.0, 10),
        (100, "10"),
    ],
)
def test_invalid_budgets_are_rejected(budget: bool | float | int, span: bool | int | str) -> None:
    with pytest.raises(ValueError, match="budget"):
        _route({}, max_source_chars=budget, max_span_chars=span)


def test_duplicate_block_aliases_do_not_inflate_material_coverage() -> None:
    source = _source("a", "同一个来源块")
    with pytest.raises(ValueError, match="duplicate"):
        _route({"a": source, "alias": source})
