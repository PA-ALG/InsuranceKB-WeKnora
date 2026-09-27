"""Exact binding policy, complete rejection and immutable input boundaries."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest

from insurance_harness.knowledge_compiler.evidence_occurrences import exact_quote_occurrences
from insurance_harness.product_ingestion.native_admission_context import (
    render_native_admission_context,
)
from insurance_harness.product_ingestion.native_admission_preflight import (
    preflight_native_admission_response,
)
from insurance_harness.product_ingestion.stages import json_bytes
from tests.product_ingestion.test_native_admission import inputs, response

pytest_plugins = ("tests.product_ingestion.test_discovery",)


def sample(
    case: Any, *, text: str = "中文\r\n🙂前言。唯一引文。结尾", legacy: bool = False
) -> tuple[Any, ...]:
    request, entity, snapshot, source = inputs(case)
    block = source.blocks[0].model_copy(update={"text": text})
    request = request.model_copy(
        update={
            "base_request": request.base_request.model_copy(
                update={
                    "sources": tuple(
                        block if s.block_id == block.block_id else s
                        for s in request.base_request.sources
                    )
                }
            )
        }
    )
    source = replace(source, blocks=(block,))
    ctx = render_native_admission_context(
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        dependency_policy=None if legacy else "candidate-dependencies.830.v1",
        isolation_enabled=not legacy,
    )
    payload = response(ctx, supported=True)
    quote = "唯一引文"
    page = payload["pages"][0]
    page["body"] = page["content_provenance"]["segments"][0]["text"] = quote
    page["evidence"][0].update(start=0, quote=quote)
    if not legacy:
        payload["contract"] = "native-knowledge-admission.830.v2"
        payload["decisions"][0]["depends_on"] = []
    return request, entity, snapshot, source, ctx, payload


def run(values: tuple[Any, ...]) -> Any:
    request, entity, snapshot, source, ctx, payload = values
    before = json_bytes(payload)
    outcome = preflight_native_admission_response(
        raw=before, request=request, entity_id=entity, snapshot=snapshot, source=source, context=ctx
    )
    assert json_bytes(payload) == before
    return outcome


def test_unicode_offset_keeps_provenance_and_exact_text(case: Any) -> None:
    values = sample(case)
    outcome = run(values)
    assert outcome.failure is None
    page = outcome.projection.output.pages[0]
    assert page.evidence[0].start == values[3].blocks[0].text.index("唯一引文")
    canonical = deepcopy(values[-1])
    canonical["pages"][0]["evidence"][0]["start"] = page.evidence[0].start
    assert outcome.canonical == json_bytes(canonical)
    assert len(outcome.receipt["changes"]) == 1
    assert page.content_provenance.segments[0].origin == "SOURCE_SUPPORTED"


@pytest.mark.parametrize("fault", ["absent", "repeated", "foreign", "tampered", "legacy"])
def test_nonunique_or_unbound_evidence_never_projects(case: Any, fault: str) -> None:
    values = sample(case, legacy=fault == "legacy")
    if fault == "absent":
        values[-1]["pages"][0]["evidence"][0]["quote"] = "不存在"
    elif fault == "repeated":
        values = sample(case, text="前唯一引文后唯一引文")
    elif fault == "foreign":
        values[-1]["pages"][0]["evidence"][0]["source_ref"] = "other-source"
    elif fault == "tampered":
        values[-2]["source_options"][0]["spans"][0]["quote"] += "篡改"
    outcome = run(values)
    assert outcome.projection is None and outcome.failure
    assert outcome.receipt["status"] == "REJECTED"
    assert outcome.receipt["changes"] == []


def test_correct_offset_disambiguates_repeated_quote(case: Any) -> None:
    values = sample(case, text="前唯一引文后唯一引文")
    values[-1]["pages"][0]["evidence"][0]["start"] = 6
    outcome = run(values)
    assert outcome.projection is not None
    assert outcome.receipt["changes"] == []
    assert outcome.canonical == json_bytes(values[-1])


@pytest.mark.parametrize(
    "fault", ["none", "orphan", "duplicate_sense", "page_collision", "unknown"]
)
def test_concept_binding_never_changes_members_or_guesses_sense(case: Any, fault: str) -> None:
    values = sample(case)
    payload = values[-1]
    page = payload["pages"][0]
    definition = {
        k: deepcopy(v)
        for k, v in page.items()
        if k not in {"stable_key", "concept_refs", "conditions", "exceptions", "valid_time"}
    }
    definition.update(member_ref="d1", canonical_key="reading", sense_key="sense1", aliases=[])
    payload["definitions"] = [definition]
    payload["decisions"][0]["member_refs"].append("d1")
    page["concept_refs"] = ["reading"]
    if fault == "orphan":
        page["concept_refs"] = []
    elif fault == "duplicate_sense":
        second = deepcopy(definition)
        second.update(member_ref="d2", sense_key="sense2")
        payload["definitions"].append(second)
        payload["decisions"][0]["member_refs"].append("d2")
    elif fault == "page_collision":
        definition["canonical_key"] = page["member_ref"]
        page["concept_refs"] = [page["member_ref"]]
    elif fault == "unknown":
        page["concept_refs"] = ["not-offered"]
    outcome = run(values)
    assert (outcome.projection is not None) == (fault == "none")
    if fault == "orphan":
        assert "definition lacks page use" in outcome.failure
        assert outcome.receipt["strict_projection"] == "REJECTED"
    if fault == "none":
        assert outcome.projection.output.pages[0].concept_ids == (
            outcome.projection.output.definitions[0].concept_id,
        )
        assert [c["path"] for c in outcome.receipt["changes"]] == [
            "/definitions/0/evidence/0/start",
            "/pages/0/evidence/0/start",
            "/pages/0/concept_refs/0",
        ]


def test_occurrence_primitive_preserves_overlap_and_offered_spans() -> None:
    assert exact_quote_occurrences("🙂哈哈哈\r\n哈哈", "哈哈", [(0, 7), (1, 4)]) == (1, 2)
    assert exact_quote_occurrences("a\r\nb", "a\nb", [(0, 4)]) == ()
    assert exact_quote_occurrences("xxx", "x", [(1, 2)]) == (1,)
    with pytest.raises(ValueError):
        exact_quote_occurrences("abc", "", [(0, 3)])
