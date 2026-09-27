"""Independent discovery depends on local source/schema inputs, not field refreshes."""

from __future__ import annotations

import typing

import pytest

from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    compile_output_hash_g3,
    compile_request_hash_g3,
)
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import free_page_id
from insurance_harness.product_ingestion import discovery
from tests.product_ingestion.test_independent_discovery import _proposal

pytest_plugins = ("tests.product_ingestion.test_discovery",)


def _contexts(request: typing.Any, entity: str) -> tuple[dict[str, typing.Any], ...]:
    return discovery.render_independent_discovery_contexts(
        request=request,
        entity_id=entity,
        exclusion_index=discovery.build_discovery_exclusion_index(request, entity),
    )


def test_field_refresh_request_identity_does_not_invalidate_independent_generation(
    case: typing.Any,
) -> None:
    request, _delta, entity = case
    changed = request.model_copy(
        update={
            "request_sha256": "1" * 64,
            "base_request": request.base_request.model_copy(update={"request_id": "field-refresh"}),
        }
    )
    original = _contexts(request, entity)
    assert _contexts(changed, entity) == original
    raw = discovery._bytes(_proposal(original[0]))
    projected = discovery.project_independent_discovery_response(
        raw=raw,
        request=changed,
        entity_id=entity,
        exclusion_index=discovery.build_discovery_exclusion_index(changed, entity),
        context=original[0],
    )
    assert projected.output.pages
    assert projected.raw == raw
    assert projected.output.request_hash == compile_request_hash_g3(changed.base_request)


@pytest.mark.parametrize("field", ["entity_version", "profile_sha256", "schema_pack_sha256"])
def test_binding_dependency_changes_invalidate_generation(case: typing.Any, field: str) -> None:
    request, _delta, entity = case
    original = _contexts(request, entity)
    binding = next(row for row in request.entity_bindings if row.entity_id == entity)
    changed_binding = binding.model_copy(update={field: "changed"})
    changed = request.model_copy(
        update={
            "entity_bindings": tuple(
                changed_binding if row.entity_id == entity else row
                for row in request.entity_bindings
            )
        }
    )
    if field == "schema_pack_sha256":
        with pytest.raises(ValueError, match="catalog binding mismatch"):
            _contexts(changed, entity)
    else:
        assert _contexts(changed, entity) != original


@pytest.mark.parametrize(
    "field", ["text", "parse_hash", "source_hash", "page_number", "parser_identity"]
)
def test_full_source_identity_changes_invalidate_generation(case: typing.Any, field: str) -> None:
    request, _delta, entity = case
    original = _contexts(request, entity)
    binding = next(row for row in request.entity_bindings if row.entity_id == entity)
    source = next(iter(discovery._discovery_sources(request, binding).values()))
    value = source.page_number + 1 if field == "page_number" else "changed"
    changed_source = source.model_copy(update={field: value})
    base = request.base_request.model_copy(
        update={
            "sources": tuple(
                changed_source if row == source else row for row in request.base_request.sources
            )
        }
    )
    assert _contexts(request.model_copy(update={"base_request": base}), entity) != original


@pytest.mark.parametrize("field", ["body", "title", "aliases"])
def test_full_existing_concept_changes_invalidate_generation(case: typing.Any, field: str) -> None:
    request, _delta, entity = case
    original = _contexts(request, entity)
    first, *rest = request.base_request.existing_definitions
    value = ("changed",) if field == "aliases" else "changed"
    base = request.base_request.model_copy(
        update={"existing_definitions": (first.model_copy(update={field: value}), *rest)}
    )
    assert _contexts(request.model_copy(update={"base_request": base}), entity) != original


def test_legacy_v3_remains_projectable_and_is_distinct_from_v4(case: typing.Any) -> None:
    request, _delta, entity = case
    index = discovery.build_discovery_exclusion_index(request, entity)
    legacy = discovery.render_independent_discovery_contexts(
        request=request, entity_id=entity, exclusion_index=index, context_version="v3"
    )[0]
    assert legacy["contract"] == "product-discovery-context.830.v3"
    assert legacy != _contexts(request, entity)[0]
    proposal = _proposal(legacy)
    assert discovery.project_independent_discovery_response(
        raw=discovery._bytes(proposal),
        request=request,
        entity_id=entity,
        exclusion_index=index,
        context=legacy,
    ).output.pages


def test_v4_projects_existing_concept_links_without_mutating_original_raw(case: typing.Any) -> None:
    request, _delta, entity = case
    context = _contexts(request, entity)[0]
    proposal = _proposal(context)
    concept = context["existing_concept_refs"][0]
    proposal["proposal"]["pages"][0]["concept_refs"] = [concept["concept_ref"]]
    raw = discovery._bytes(proposal)
    projected = discovery.project_independent_discovery_response(
        raw=raw,
        request=request,
        entity_id=entity,
        exclusion_index=discovery.build_discovery_exclusion_index(request, entity),
        context=context,
    )
    assert projected.raw == raw
    assert projected.output.pages[0].concept_ids == (concept["concept_id"],)
    proposal["proposal"]["pages"][0]["entity_ref"] = "foreign-entity"
    with pytest.raises(ValueError, match="entity reference mismatch"):
        discovery.project_independent_discovery_response(
            raw=discovery._bytes(proposal),
            request=request,
            entity_id=entity,
            exclusion_index=discovery.build_discovery_exclusion_index(request, entity),
            context=context,
        )


def test_published_discovery_changes_exclusion_and_cannot_be_replayed_as_new(
    case: typing.Any,
) -> None:
    request, _delta, entity = case
    context = _contexts(request, entity)[0]
    result = discovery.project_independent_discovery_response(
        raw=discovery._bytes(_proposal(context)),
        request=request,
        entity_id=entity,
        exclusion_index=discovery.build_discovery_exclusion_index(request, entity),
        context=context,
    )
    base = request.base_request.model_copy(update={"existing_pages": result.output.pages})
    changed = request.model_copy(update={"base_request": base})
    assert _contexts(changed, entity) != (context,)
    with pytest.raises(ValueError, match="exclusion index mismatch"):
        discovery.project_independent_discovery_response(
            raw=result.raw,
            request=changed,
            entity_id=entity,
            exclusion_index=discovery.build_discovery_exclusion_index(changed, entity),
            context=context,
        )


def test_create_to_match_admission_receipts_do_not_change_generation(case: typing.Any) -> None:
    request, _delta, entity = case
    binding = next(row for row in request.entity_bindings if row.entity_id == entity)
    matched = binding.model_copy(
        update={
            "resolution_disposition": "MATCH",
            "resolution_refs": (),
            "candidate_id": None,
            "entity_candidate_sha256": None,
            "binding_sha256": "f" * 64,
        }
    )
    changed = request.model_copy(
        update={
            "entity_bindings": tuple(
                matched if row.entity_id == entity else row for row in request.entity_bindings
            )
        }
    )
    assert _contexts(changed, entity) == _contexts(request, entity)


@pytest.mark.parametrize(
    "field", ["body", "conditions", "exceptions", "entity_version", "valid_time", "evidence"]
)
def test_existing_page_semantic_revision_invalidates_discovery(
    case: typing.Any, field: str
) -> None:
    request, _delta, entity = case
    context = _contexts(request, entity)[0]
    page = discovery.project_independent_discovery_response(
        raw=discovery._bytes(_proposal(context)),
        request=request,
        entity_id=entity,
        exclusion_index=discovery.build_discovery_exclusion_index(request, entity),
        context=context,
    ).output.pages[0]
    baseline = request.model_copy(
        update={"base_request": request.base_request.model_copy(update={"existing_pages": (page,)})}
    )
    changes = {
        "body": page.body + " 补充办理条件。",
        "conditions": ("仅限本合同有效期",),
        "exceptions": ("不含已终止合同",),
        "entity_version": page.entity_version + "-next",
        "valid_time": "2026-09-23",
        "evidence": (page.evidence[0].model_copy(update={"parser_identity": "next-parser"}),),
    }
    changed = baseline.model_copy(
        update={
            "base_request": baseline.base_request.model_copy(
                update={"existing_pages": (page.model_copy(update={field: changes[field]}),)}
            )
        }
    )
    assert _contexts(changed, entity) != _contexts(baseline, entity)


def test_generation_can_compare_existing_page_body_and_scope(case: typing.Any) -> None:
    request, _delta, entity = case
    context = _contexts(request, entity)[0]
    page = discovery.project_independent_discovery_response(
        raw=discovery._bytes(_proposal(context)),
        request=request,
        entity_id=entity,
        exclusion_index=discovery.build_discovery_exclusion_index(request, entity),
        context=context,
    ).output.pages[0]
    request = request.model_copy(
        update={"base_request": request.base_request.model_copy(update={"existing_pages": (page,)})}
    )
    current = _contexts(request, entity)[0]
    assert current["contract"] == "product-discovery-context.830.v5"
    view = current["existing_knowledge"]["pages"][0]
    assert view["body"] == page.body
    assert view["entity_id"] == page.entity_id
    assert view["entity_version"] == page.entity_version
    assert view["conditions"] == list(page.conditions)
    assert view["exceptions"] == list(page.exceptions)
    assert len(view["revision_sha256"]) == 64
    assert "evidence" not in view
    definition = current["existing_knowledge"]["definitions"][0]
    assert definition["body"]
    assert definition["sense_key"]


def test_current_comparison_includes_schema_meaning_without_field_values(case: typing.Any) -> None:
    request, _delta, entity = case
    context = _contexts(request, entity)[0]
    binding = next(row for row in request.entity_bindings if row.entity_id == entity)
    pack = next(
        row.pack
        for row in request.catalog.entries
        if row.pack.schema_pack_sha256 == binding.schema_pack_sha256
    )
    actual = context["existing_knowledge"]["schema_fields"]
    assert actual == [
        {
            "field_key": row.field_key,
            "short_title": row.short_title,
            "description": row.description,
            "value_spec": row.value_spec,
            "knowledge_role": row.knowledge_role,
        }
        for row in sorted(pack.fields, key=lambda row: row.field_key)
    ]


def _review_case(case: typing.Any) -> tuple[typing.Any, ...]:
    request, _delta, entity = case
    context = _contexts(request, entity)[0]
    candidate = discovery.project_independent_discovery_response(
        raw=discovery._bytes(_proposal(context)),
        request=request,
        entity_id=entity,
        exclusion_index=discovery.build_discovery_exclusion_index(request, entity),
        context=context,
    )
    page = candidate.output.pages[0]
    disposition = candidate.proposal.dispositions[0].model_dump(mode="json")
    disposition["member_id"] = free_page_id(page)
    return (
        request,
        entity,
        page,
        candidate.output,
        {
            "output": candidate.output.model_dump(mode="json"),
            "dispositions": [disposition],
            "sources": context["source_options"],
        },
    )


@pytest.mark.parametrize("all_entities", [False, True])
def test_review_sees_candidate_identity_and_existing_semantic_revisions(
    case: typing.Any,
    all_entities: bool,
) -> None:
    request, entity, page, output, candidates = _review_case(case)
    old_page = page.model_copy(update={"stable_key": "existing-rule", "body": "已有办理规则"})
    request = request.model_copy(
        update={
            "base_request": request.base_request.model_copy(update={"existing_pages": (old_page,)})
        }
    )

    def render(current: typing.Any, **options: typing.Any) -> typing.Any:
        selected = None if all_entities else entity
        index = (
            {
                row.entity_id: discovery.build_discovery_exclusion_index(current, row.entity_id)
                for row in current.entity_bindings
            }
            if all_entities
            else discovery.build_discovery_exclusion_index(current, entity)
        )
        return discovery.render_independent_discovery_review_context(
            request=current,
            entity_id=selected,
            exclusion_index=index,
            discovery_candidates=candidates,
            final_composed_output=output,
            final_composed_output_hash=compile_output_hash_g3(output),
            **options,
        )

    context = render(request)
    assert context["contract"] == "product-discovery-review-context.830.v4"
    assert context["existing_knowledge"]["pages"][0]["body"] == old_page.body
    member = context["candidate_members"][0]
    for key in ("entity_id", "stable_key", "entity_version", "concept_ids"):
        assert member[key] == page.model_dump(mode="json")[key]
    assert member["member_type"] == "free_page"
    if all_entities:
        assert {row["entity_id"] for row in context["existing_knowledge"]["schema_fields"]} == {
            row.entity_id for row in request.entity_bindings
        }
    for update in (
        {"body": "已有办理规则已修改"},
        {
            "evidence": (
                old_page.evidence[0].model_copy(update={"parser_identity": "revised-parser"}),
            )
        },
    ):
        revised = request.model_copy(
            update={
                "base_request": request.base_request.model_copy(
                    update={"existing_pages": (old_page.model_copy(update=update),)}
                )
            }
        )
        assert discovery._bytes(render(revised)) != discovery._bytes(context)
    legacy = render(request, context_version="product-discovery-review-context.830.v3")
    assert "existing_knowledge" not in legacy
    assert "member_type" not in legacy["candidate_members"][0]
    with pytest.raises(ValueError, match="context budget exceeded"):
        render(request, max_context_bytes=len(discovery._bytes(context)) // 2)


def test_unrelated_page_revision_does_not_invalidate_entity_generation(case: typing.Any) -> None:
    request, entity, page, _output, _candidates = _review_case(case)
    other = next(row for row in request.entity_bindings if row.entity_id != entity)
    page = page.model_copy(update={"entity_id": other.entity_id})
    revised = request.model_copy(
        update={"base_request": request.base_request.model_copy(update={"existing_pages": (page,)})}
    )
    assert _contexts(revised, entity) == _contexts(request, entity)


def test_semantic_view_rejects_mismatched_catalog_binding(case: typing.Any) -> None:
    request, _delta, entity = case
    bindings = tuple(
        row.model_copy(update={"schema_pack_id": "wrong-pack"}) if row.entity_id == entity else row
        for row in request.entity_bindings
    )
    with pytest.raises(ValueError, match="discovery catalog binding mismatch"):
        discovery.build_discovery_knowledge_view(
            request.model_copy(update={"entity_bindings": bindings}), entity
        )


def test_review_preserves_candidate_concept_sense_and_origin(case: typing.Any) -> None:
    request, entity, _page, output, candidates = _review_case(case)
    definition = request.base_request.existing_definitions[0]
    output = output.model_copy(update={"definitions": (definition,)})
    candidates["output"] = output.model_dump(mode="json")
    candidates["dispositions"].append(
        {
            **candidates["dispositions"][0],
            "candidate_id": "concept-comparison-fixture",
            "member_id": definition.concept_id,
        }
    )
    context = discovery.render_independent_discovery_review_context(
        request=request,
        entity_id=entity,
        exclusion_index=discovery.build_discovery_exclusion_index(request, entity),
        discovery_candidates=candidates,
        final_composed_output=output,
        final_composed_output_hash=compile_output_hash_g3(output),
    )
    member = next(
        row for row in context["candidate_members"] if row["member_id"] == definition.concept_id
    )
    assert member["member_type"] == "concept_definition"
    for key in ("canonical_key", "sense_key", "aliases", "origin"):
        assert member[key] == definition.model_dump(mode="json")[key]
