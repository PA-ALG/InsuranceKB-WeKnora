"""Compiler navigation carry is part of immutable manifest construction."""

import typing

import pytest

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import batch_json_bytes_830_g3
from insurance_harness.product_ingestion.compilation import published_navigation_assignments
from tests.product_ingestion.test_pipeline_runtime import _base_snapshot_with_navigation


def test_assembly_preserves_typed_navigation_and_unchanged_default_wire() -> None:
    _, parent = _base_snapshot_with_navigation()
    before = batch_json_bytes_830_g3(parent)
    projection = {
        "navigation_assignments": [r.model_dump(mode="json") for r in parent.navigation_assignments]
    }
    navigation = published_navigation_assignments({"published_projection": projection})
    assert navigation == parent.navigation_assignments
    carried = compiler.assemble_candidate_bundle(
        parent.request,
        parent.model_compile_result,
        parent.compile_result,
        parent.review_result,
        parent.admission,
        navigation_assignments=navigation,
    )
    assert batch_json_bytes_830_g3(carried) == before
    legacy = compiler.assemble_candidate_bundle(
        parent.request,
        parent.model_compile_result,
        parent.compile_result,
        parent.review_result,
        parent.admission,
    )
    explicit_empty = compiler.assemble_candidate_bundle(
        parent.request,
        parent.model_compile_result,
        parent.compile_result,
        parent.review_result,
        parent.admission,
        navigation_assignments=(),
    )
    assert batch_json_bytes_830_g3(legacy) == batch_json_bytes_830_g3(explicit_empty)
    assert b'"navigation_assignments"' not in batch_json_bytes_830_g3(legacy)
    assert batch_json_bytes_830_g3(parent) == before


def test_assembly_rejects_navigation_for_an_absent_entity() -> None:
    _, parent = _base_snapshot_with_navigation()
    original = parent.navigation_assignments[0]
    data = original.model_dump(exclude={"assignment_sha256"})
    data["entity_id"] = "entity-absent"
    row = compiler.NavigationAssignment830G3V1.model_validate(
        {**data, "assignment_sha256": compiler._batch_sha256(original.contract, data)}
    )
    with pytest.raises(ValueError, match="NAVIGATION_ENTITY_INVALID"):
        compiler.assemble_candidate_bundle(
            parent.request,
            parent.model_compile_result,
            parent.compile_result,
            parent.review_result,
            parent.admission,
            navigation_assignments=(row,),
        )


def test_empty_published_navigation_accepts_go_null_and_omitted_collection() -> None:
    projections: tuple[dict[str, typing.Any], ...] = (
        {},
        {"navigation_assignments": None},
        {"navigation_assignments": []},
    )
    for projection in projections:
        assert published_navigation_assignments({"published_projection": projection}) == ()
    with pytest.raises(ValueError):
        published_navigation_assignments({"published_projection": {"navigation_assignments": [{}]}})
