"""Keep provenance indexes attached to real PDF fragments after cross-page projection."""

from __future__ import annotations

import importlib
from dataclasses import replace
from typing import Any

import pytest

from insurance_harness.knowledge_compiler.concept_compile_830_g2 import CompileOutput
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import FreeWikiPage, evidence_for
from tests.product_ingestion.test_source_geometry import native_snapshot

pytest_plugins = ("tests.product_ingestion.test_platform",)


def sample(snapshot: Any) -> tuple[Any, Any]:
    decoded = native_snapshot(snapshot)
    block = decoded.blocks[0]
    evidence = evidence_for(block, 0, len(block.text))
    generated = "\n可结合材料用途阅读。"
    page = FreeWikiPage.model_validate(
        {
            "space_id": block.space_id,
            "entity_id": "entity",
            "entity_version": "v1",
            "stable_key": "reading",
            "title": "资料阅读",
            "body": block.text + generated,
            "concept_ids": [],
            "conditions": [],
            "exceptions": [],
            "valid_time": "",
            "evidence": [evidence],
            "content_provenance": {
                "contract": "knowledge-content-provenance.830.v1",
                "segments": [
                    {"text": block.text, "origin": "SOURCE_SUPPORTED", "evidence_indexes": [0]},
                    {"text": generated, "origin": "MODEL_GENERATED", "evidence_indexes": []},
                ],
            },
        }
    )
    return decoded, CompileOutput(
        request_hash="1" * 64, fields=(), pages=(page,), transformation="SYNTHESIZE"
    )


def locate(output: Any, sources: Any) -> Any:
    module = importlib.import_module("insurance_harness.product_ingestion.native_evidence")
    return module.locate_native_evidence(output, sources)


def test_cross_page_references_remap_provenance_without_changing_text(snapshot: Any) -> None:
    decoded, output = sample(snapshot)
    result = locate(output, {decoded.blocks[0].knowledge_id: decoded})
    page = result.output.pages[0]
    assert len(page.evidence) == 2
    assert page.body == output.pages[0].body
    assert page.content_provenance.segments[0].evidence_indexes == (0, 1)
    assert page.content_provenance.segments[1] == output.pages[0].content_provenance.segments[1]
    assert [p["actual_page_number"] for p in result.locations[0]["parts"]] == [1, 2]
    assert len(output.pages[0].evidence) == 1


def test_source_supported_text_with_missing_geometry_is_not_relabeled(snapshot: Any) -> None:
    decoded, output = sample(snapshot)
    broken = replace(decoded, snapshot={**decoded.snapshot, "chunk_page_mappings": []})
    with pytest.raises(ValueError, match="LOCATION_MISSING"):
        locate(output, {decoded.blocks[0].knowledge_id: broken})
    assert output.pages[0].content_provenance.segments[0].origin == "SOURCE_SUPPORTED"


def test_pure_generated_knowledge_needs_no_pdf_geometry(snapshot: Any) -> None:
    _decoded, output = sample(snapshot)
    payload = output.pages[0].model_dump(mode="json")
    segment = payload["content_provenance"]["segments"][1]
    payload.update(body=segment["text"], evidence=[])
    payload["content_provenance"]["segments"] = [segment]
    output = output.model_copy(update={"pages": (FreeWikiPage.model_validate(payload),)})
    result = locate(output, {})
    assert result.output == output
    assert result.locations == ()


@pytest.mark.parametrize("reverse", [False, True])
def test_overlapping_original_quotes_share_projected_page_fragment(
    snapshot: Any, reverse: bool
) -> None:
    decoded, output = sample(snapshot)
    block = decoded.blocks[0]
    second_page_start = decoded.snapshot["chunk_page_mappings"][0]["page_spans"][1][
        "block_codepoint_start"
    ]
    second = evidence_for(block, second_page_start, len(block.text))
    payload = output.pages[0].model_dump(mode="json")
    payload["evidence"].append(second.model_dump(mode="json"))
    if reverse:
        payload["evidence"].reverse()
    payload["content_provenance"]["segments"][0]["evidence_indexes"] = [0, 1]
    output = output.model_copy(update={"pages": (FreeWikiPage.model_validate(payload),)})
    result = locate(output, {block.knowledge_id: decoded})
    page = result.output.pages[0]
    assert len(page.evidence) == 2
    assert page.content_provenance.segments[0].evidence_indexes == (0, 1)
    assert [row["evidence_indexes"] for row in result.locations] == (
        [[0], [1, 0]] if reverse else [[0, 1], [1]]
    )
    assert page.body == output.pages[0].body
