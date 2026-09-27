"""Native admission keeps source provenance and exact update identities."""

from __future__ import annotations

import importlib
from copy import deepcopy
from typing import Any

import pytest

from insurance_harness.product_ingestion.native_discovery import NativeDiscoverySnapshot
from insurance_harness.product_ingestion.platform import DecodedSourceSnapshot
from insurance_harness.product_ingestion.stages import json_bytes
from tests.product_ingestion.test_discovery_local_dependencies import _review_case

pytest_plugins = ("tests.product_ingestion.test_discovery",)


def inputs(case: Any) -> tuple[Any, ...]:
    request, entity, page, _, _ = _review_case(case)
    e = page.evidence[0]
    block = next(
        s
        for s in request.base_request.sources
        if (s.revision_id, s.block_id) == (e.revision_id, e.block_id)
    )
    source = DecodedSourceSnapshot(
        {
            "snapshot_sha256": "a" * 64,
            "receipt": {"knowledge_id": block.knowledge_id, "parse_attempt": block.parse_attempt},
        },
        (block,),
        {},
        (),
        b"",
    )
    snapshot = NativeDiscoverySnapshot.model_validate(
        {
            "contract": "g3-platform-native-discovery-snapshot.830.v1",
            "scope": {
                "tenant_id": block.tenant_id,
                "space_id": block.space_id,
                "raw_kb_id": block.raw_kb_id,
                "wiki_kb_id": request.base_request.wiki_kb_id,
            },
            "knowledge_id": block.knowledge_id,
            "parse_attempt": block.parse_attempt,
            "source_snapshot_sha256": "a" * 64,
            "policy_sha256": "b" * 64,
            "request_sha256": "c" * 64,
            "phase": "snapshot",
            "window_count": 1,
            "windows": [
                {
                    "window_id": 0,
                    "chunk_ids": [block.block_id],
                    "prompt": "",
                    "prompt_sha256": "d" * 64,
                }
            ],
            "candidates": [
                {
                    "content_origin": "MODEL_GENERATED",
                    "kind": "concept",
                    "name": "资料阅读流程",
                    "slug": "concept/reading",
                    "aliases": [],
                    "description": "可按材料用途整理阅读。",
                    "details": "模型补充",
                    "source_chunks": [block.block_id],
                    "has_source_chunks": True,
                }
            ],
            "discovery_raw_sha256": "e" * 64,
            "citation_raw_sha256": "f" * 64,
            "snapshot_sha256": "1" * 64,
        }
    )
    return request, entity, snapshot, source


def api() -> Any:
    return importlib.import_module("insurance_harness.product_ingestion.native_admission")


def context(values: tuple[Any, ...]) -> dict[str, Any]:
    request, entity, snapshot, source = values
    value = api().render_native_admission_context(
        request=request, entity_id=entity, snapshot=snapshot, source=source
    )
    assert isinstance(value, dict)
    return value


def response(ctx: dict[str, Any], *, supported: bool = False) -> dict[str, Any]:
    quote = ctx["source_options"][0]["spans"][0]["quote"][:12]
    body = quote if supported else "可按资料用途整理阅读顺序，便于理解。"
    return {
        "contract": "native-knowledge-admission.830.v1",
        "definitions": [],
        "pages": [
            {
                "member_ref": "p1",
                "action": "NEW",
                "expected_revision_sha256": None,
                "stable_key": "native-reading",
                "title": "资料阅读流程",
                "body": body,
                "concept_refs": [],
                "conditions": [],
                "exceptions": [],
                "valid_time": "",
                "evidence": [{"source_ref": "s1", "start": 0, "quote": quote}] if supported else [],
                "content_provenance": {
                    "contract": "knowledge-content-provenance.830.v1",
                    "segments": [
                        {
                            "text": body,
                            "origin": "SOURCE_SUPPORTED" if supported else "MODEL_GENERATED",
                            "evidence_indexes": [0] if supported else [],
                        }
                    ],
                },
                "audit_reason": "有独立资料阅读用途",
            }
        ],
        "decisions": [
            {
                "candidate_ref": "c1",
                "decision": "NEW",
                "member_refs": ["p1"],
                "existing_target": None,
                "reason": "有独立阅读用途",
            }
        ],
    }


def project(values: tuple[Any, ...], ctx: dict[str, Any], payload: dict[str, Any]) -> Any:
    request, entity, snapshot, source = values
    return api().project_native_admission_response(
        raw=json_bytes(payload),
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        context=ctx,
    )


@pytest.mark.parametrize("supported", [False, True])
def test_native_admission_preserves_explicit_content_origins(case: Any, supported: bool) -> None:
    values = inputs(case)
    ctx = context(values)
    result = project(values, ctx, response(ctx, supported=supported))
    assert result.output.fields == ()
    page = result.output.pages[0]
    assert bool(page.evidence) == supported
    assert page.content_provenance.segments[0].origin == (
        "SOURCE_SUPPORTED" if supported else "MODEL_GENERATED"
    )
    assert result.output.transformation == "SYNTHESIZE"
    assert ctx["native_candidates"][0]["content_origin"] == "MODEL_GENERATED"


@pytest.mark.parametrize(
    "fault", ["missing_origin", "uncovered_candidate", "unknown_member", "wrong_offset"]
)
def test_native_admission_rejects_unbound_or_forged_output(case: Any, fault: str) -> None:
    values = inputs(case)
    ctx = context(values)
    payload = response(ctx, supported=True)
    if fault == "missing_origin":
        del payload["pages"][0]["content_provenance"]
    if fault == "uncovered_candidate":
        payload["decisions"] = []
    if fault == "unknown_member":
        payload["decisions"][0]["member_refs"] = ["other"]
    if fault == "wrong_offset":
        payload["pages"][0]["evidence"][0]["start"] = 1
    with pytest.raises(ValueError):
        project(values, ctx, payload)


def test_native_admission_update_requires_exact_existing_revision_and_policy(case: Any) -> None:
    values = inputs(case)
    ctx = context(values)
    first = project(values, ctx, response(ctx)).output.pages[0]
    request, entity, snapshot, source = values
    request = request.model_copy(
        update={
            "base_request": request.base_request.model_copy(update={"existing_pages": (first,)})
        }
    )
    values = (request, entity, snapshot, source)
    ctx = context(values)
    payload = response(ctx)
    with pytest.raises(ValueError):
        project(values, ctx, payload)
    payload["pages"][0].update(
        action="UPDATE",
        expected_revision_sha256=ctx["existing_knowledge"]["pages"][0]["revision_sha256"],
    )
    payload["decisions"][0]["decision"] = "UPDATE"
    with pytest.raises(ValueError):
        project(values, ctx, payload)
    request = request.model_copy(
        update={"knowledge_update_policy": "explicit-same-identity.830.v1"}
    )
    values = (request, entity, snapshot, source)
    ctx = context(values)
    updated = "可按材料用途分类，并记录阅读疑问。"
    payload["pages"][0]["body"] = updated
    payload["pages"][0]["content_provenance"]["segments"][0]["text"] = updated
    result = project(values, ctx, payload)
    assert result.output.audit[0].disposition == "update"
    bad = deepcopy(payload)
    bad["pages"][0]["expected_revision_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        project(values, ctx, bad)


@pytest.mark.parametrize("supported", [False, True])
def test_native_projection_joins_existing_compiler_and_provenance_review(
    case: Any, supported: bool
) -> None:
    from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
    from insurance_harness.product_ingestion import discovery
    from insurance_harness.product_ingestion.discovery_composition import merge_discovery_delta

    values = inputs(case)
    request, entity, _snapshot, _source = values
    ctx = context(values)
    projection = project(values, ctx, response(ctx, supported=supported))
    delta = merge_discovery_delta(
        request=request, field_delta=case[1], free_output=projection.output, run_id="native-join"
    )
    composed = compiler.compose_batch_output(request, delta)
    assert composed.fields == compiler.compose_batch_output(request, case[1]).fields
    review = discovery.render_independent_discovery_review_context(
        request=request,
        entity_id=entity,
        exclusion_index=discovery.build_discovery_exclusion_index(request, entity),
        discovery_candidates={
            "output": projection.output.model_dump(mode="json"),
            "dispositions": projection.dispositions,
            "sources": ctx["source_options"],
        },
        final_composed_output=composed,
        final_composed_output_hash=compiler.compile_output_hash_g3(composed),
    )
    assert review["contract"] == "product-discovery-review-context.830.v5"
    assert review["candidate_members"][0]["content_provenance"] == (
        projection.output.pages[0].content_provenance.model_dump(mode="json")
    )
    assert bool(review["candidate_source_options"]) == supported


@pytest.mark.parametrize("collision", ["page_title", "definition_title", "canonical_key", "alias"])
def test_schema_name_collision_keeps_distinct_meaning_for_semantic_review(
    case: Any, collision: str
) -> None:
    from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
    from insurance_harness.product_ingestion import discovery
    from insurance_harness.product_ingestion.discovery_composition import merge_discovery_delta

    values = inputs(case)
    request, entity, _snapshot, _source = values
    ctx = context(values)
    field = next(
        f for f in ctx["existing_knowledge"]["schema_fields"] if f["field_key"] == "product_code"
    )
    payload = response(ctx)
    page = payload["pages"][0]
    body = "阅读资料时，可用险种代码核对不同材料是否属于同一产品，不能仅凭名称相近判断。"
    page.update(body=body, title="险种代码的阅读用途")
    page["content_provenance"]["segments"][0]["text"] = body
    if collision == "page_title":
        page["title"] = field["short_title"]
    else:
        definition = {
            key: deepcopy(page[key])
            for key in ("body", "evidence", "content_provenance", "audit_reason")
        }
        definition.update(
            member_ref="d1",
            action="NEW",
            expected_revision_sha256=None,
            title=field["short_title"] if collision == "definition_title" else "产品标识核对",
            canonical_key=field["field_key"] if collision == "canonical_key" else "产品标识核对",
            sense_key="阅读时跨材料核对方法",
            aliases=[field["short_title"]] if collision == "alias" else [],
        )
        payload["definitions"] = [definition]
        page["concept_refs"] = ["d1"]
        payload["decisions"][0]["member_refs"].append("d1")
    projected = project(values, ctx, payload)
    delta = merge_discovery_delta(
        request=request, field_delta=case[1], free_output=projected.output, run_id="same-name"
    )
    composed = compiler.compose_batch_output(request, delta)
    assert composed.fields == compiler.compose_batch_output(request, case[1]).fields
    review = discovery.render_independent_discovery_review_context(
        request=request,
        entity_id=entity,
        exclusion_index=discovery.build_discovery_exclusion_index(request, entity),
        discovery_candidates={
            "output": projected.output.model_dump(mode="json"),
            "dispositions": projected.dispositions,
            "sources": ctx["source_options"],
        },
        final_composed_output=composed,
        final_composed_output_hash=compiler.compile_output_hash_g3(composed),
    )
    assert field in review["existing_knowledge"]["schema_fields"]
    assert all(m["rendered_content"] == body for m in review["candidate_members"])
    assert all(m["content_provenance"] for m in review["candidate_members"])
    assert len(review["review_member_ids"]) == len(projected.output.pages) + len(
        projected.output.definitions
    )


def test_candidate_chunk_subset_does_not_hide_other_bound_window_evidence(case: Any) -> None:
    request, entity, snapshot, source = inputs(case)
    candidate = snapshot.candidates[0].model_copy(
        update={"source_chunks": [], "has_source_chunks": False}
    )
    snapshot = snapshot.model_copy(update={"candidates": [candidate]})
    values = request, entity, snapshot, source
    ctx = context(values)
    payload = response(ctx, supported=True)
    result = project(values, ctx, payload)
    assert result.output.pages[0].evidence[0].block_id == source.blocks[0].block_id
    payload["pages"][0]["evidence"][0]["source_ref"] = "outside-window"
    with pytest.raises(ValueError, match="quote/offset mismatch"):
        project(values, ctx, payload)


def test_native_admission_cannot_return_schema_field_output(case: Any) -> None:
    values = inputs(case)
    ctx = context(values)
    payload = response(ctx)
    payload["fields"] = [{"field_key": "product_code", "value": "invented"}]
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        project(values, ctx, payload)


def test_update_page_with_new_concept_keeps_each_member_action_through_review(case: Any) -> None:
    from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
    from insurance_harness.product_ingestion import discovery
    from insurance_harness.product_ingestion.discovery_composition import merge_discovery_delta

    values = inputs(case)
    ctx = context(values)
    old = project(values, ctx, response(ctx)).output.pages[0]
    request, entity, snapshot, source = values
    from tests.test_batch_concept_compile_830_g3_incremental import (
        PORTABLE_PARENT,
        _published_base,
    )

    published = _published_base(compiler, PORTABLE_PARENT)
    request = request.model_copy(
        update={
            "knowledge_update_policy": "explicit-same-identity.830.v1",
            "unknown_field_key_alignments": (),
            "base_request": published.model_copy(
                update={
                    "existing_pages": (*published.existing_pages, old),
                }
            ),
        }
    )
    values = (request, entity, snapshot, source)
    ctx = context(values)
    payload = response(ctx)
    page = payload["pages"][0]
    page.update(
        action="UPDATE",
        expected_revision_sha256=(
            next(
                r["revision_sha256"]
                for r in ctx["existing_knowledge"]["pages"]
                if r["stable_key"] == old.stable_key
            )
        ),
        concept_refs=["d1"],
    )
    definition = {
        key: deepcopy(page[key])
        for key in ("title", "body", "evidence", "content_provenance", "audit_reason")
    }
    definition.update(
        member_ref="d1",
        action="NEW",
        expected_revision_sha256=None,
        canonical_key="资料阅读流程",
        sense_key="阅读组织方法",
        aliases=[],
    )
    payload["definitions"] = [definition]
    payload["decisions"][0].update(decision="UPDATE", member_refs=["p1", "d1"])
    projection = project(values, ctx, payload)
    assert {row.disposition for row in projection.output.audit} == {"update", "new_page"}
    assert [row["disposition"] for row in projection.dispositions] == ["UPDATE", "NEW"]
    from insurance_harness.knowledge_compiler.concept_compile_830_g2 import CompileOutput

    field_output = CompileOutput(
        request_hash=compiler.compile_request_hash_g3(request.base_request),
        fields=(),
    )
    field_delta = compiler.record_model_compile(
        request,
        field_output,
        run_id="field-new-base",
        implementation="test-fields",
        raw=json_bytes(field_output).decode(),
    )
    merged = merge_discovery_delta(
        request=request,
        field_delta=field_delta,
        free_output=projection.output,
        run_id="update-with-concept",
    )
    composed = compiler.compose_batch_output(request, merged)
    review = discovery.render_independent_discovery_review_context(
        request=request,
        entity_id=entity,
        exclusion_index=discovery.build_discovery_exclusion_index(request, entity),
        discovery_candidates={
            "output": projection.output.model_dump(mode="json"),
            "dispositions": projection.dispositions,
            "sources": ctx["source_options"],
        },
        final_composed_output=composed,
        final_composed_output_hash=compiler.compile_output_hash_g3(composed),
    )
    assert len(review["candidate_members"]) == 2
    assert review["contract"] == "product-discovery-review-context.830.v5"
    payload["decisions"][0]["decision"] = "NEW"
    with pytest.raises(ValueError, match="action mismatch"):
        project(values, ctx, payload)


def test_reference_current_entity_does_not_create_or_update_members(case: Any) -> None:
    request, entity, snapshot, source = inputs(case)
    native = snapshot.model_dump(mode="json")
    native["candidates"][0].update(
        kind="entity", name=context((request, entity, snapshot, source))["entity"]["display_name"]
    )
    snapshot = NativeDiscoverySnapshot.model_validate(native)
    values = request, entity, snapshot, source
    ctx = context(values)
    payload = response(ctx)
    payload["pages"] = []
    payload["decisions"][0].update(decision="REFERENCE", member_refs=[], existing_target=values[1])
    result = project(values, ctx, payload)
    assert not result.output.pages and not result.output.definitions and not result.output.audit
    assert result.dispositions[0]["existing_target"] == values[1]
    assert result.dispositions[0]["disposition"] == "REFERENCE"
    payload["decisions"][0]["existing_target"] = "unoffered-entity"
    with pytest.raises(ValueError, match="audit-only decision invalid"):
        project(values, ctx, payload)


@pytest.mark.parametrize("kind", ["concept", "entity"])
def test_current_entity_reference_rejects_different_candidate_identity(
    case: Any, kind: str
) -> None:
    request, entity, snapshot, source = inputs(case)
    native = snapshot.model_dump(mode="json")
    native["candidates"][0]["kind"] = kind
    if kind == "concept":
        native["candidates"][0]["name"] = context((request, entity, snapshot, source))["entity"][
            "display_name"
        ]
    # The other entity keeps a different name, even if its model-proposed alias matches.
    native["candidates"][0]["aliases"] = [
        context((request, entity, snapshot, source))["entity"]["display_name"]
    ]
    values = request, entity, NativeDiscoverySnapshot.model_validate(native), source
    ctx = context(values)
    payload = response(ctx)
    payload["pages"] = []
    payload["decisions"][0].update(decision="REFERENCE", member_refs=[], existing_target=entity)
    with pytest.raises(ValueError, match="current entity candidate identity mismatch"):
        project(values, ctx, payload)
