"""Independent discovery depends on local source/schema inputs, not field refreshes."""

from __future__ import annotations

import typing

import pytest

from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    compile_request_hash_g3,
)
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
