from __future__ import annotations

import importlib
import json
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from insurance_harness.knowledge_compiler import g3_bounded_model_execution as bounded
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCandidateBundle830G3V1,
    validate_batch_candidate,
)
from insurance_harness.run_admission.g3_models import canonical_json
from tests.test_g3_bounded_model_execution_830 import _gemini_compile_reference_wire


def _module() -> ModuleType:
    return importlib.import_module("insurance_harness.knowledge_compiler.g3_field_task_recovery")


@pytest.fixture(scope="module")
def fixture() -> tuple[
    BatchConceptCandidateBundle830G3V1, list[bounded.G3DFieldTarget], dict[str, Any]
]:
    candidate = validate_batch_candidate(
        (
            Path(__file__).parent / "fixtures/batch_concept_compile_830_g3/candidate.json"
        ).read_bytes()
    )
    targets = bounded._g3_d_field_targets(
        candidate.request, bounded._g3_d_entity_refs(candidate.request)
    )
    wire = json.loads(_gemini_compile_reference_wire(candidate))
    return candidate, targets, {row["field_ref"]: row for row in wire["fields"]}


def _response(fields: Sequence[dict[str, Any]] = (), transformation: str = "EXTRACT") -> bytes:
    return canonical_json(
        {
            "contract": "g3-d-compile-semantic-references.local.v1",
            "transformation": transformation,
            "definitions": [],
            "fields": list(fields),
            "pages": [],
        }
    )


def test_recovery_window_is_exact_bounded_subset_and_rejects_foreign_scope(
    fixture: tuple[
        BatchConceptCandidateBundle830G3V1, list[bounded.G3DFieldTarget], dict[str, Any]
    ],
) -> None:
    module = _module()
    candidate, targets, by_ref = fixture
    entity = targets[0]["entity_id"]
    selected = [row for row in targets if row["entity_id"] == entity][:5]
    window = module.derive_g3_field_recovery_window(
        candidate.request, entity_id=entity, field_keys=[row["field_key"] for row in selected]
    )
    assert set(window["field_refs"]) == {row["field_ref"] for row in selected}
    output = module.project_g3_field_recovery_response(
        _response([by_ref[ref] for ref in window["field_refs"]]), candidate.request, window
    )
    assert {row.field_key for row in output.fields} == {row["field_key"] for row in selected}
    for keys in (
        [],
        ["foreign"],
        [selected[0]["field_key"]] * 2,
        [row["field_key"] for row in targets if row["entity_id"] == entity][:11],
    ):
        with pytest.raises(ValueError):
            module.derive_g3_field_recovery_window(
                candidate.request, entity_id=entity, field_keys=keys
            )
    with pytest.raises(ValueError):
        module.derive_g3_field_recovery_window(
            candidate.request,
            entity_id=entity,
            field_refs=[next(row["field_ref"] for row in targets if row["entity_id"] != entity)],
        )
    with pytest.raises(ValueError):
        module.project_g3_field_recovery_response(
            _response(),
            candidate.request,
            {**window, "field_refs": tuple(window["field_refs"])[:-1]},
        )
    with pytest.raises(ValueError, match="coverage"):
        module.project_g3_field_recovery_response(_response(), candidate.request, window)


def test_recorded_subset_keeps_raw_and_rejects_selected_bad_evidence(
    fixture: tuple[
        BatchConceptCandidateBundle830G3V1, list[bounded.G3DFieldTarget], dict[str, Any]
    ],
) -> None:
    module = _module()
    candidate, targets, by_ref = fixture
    window = next(
        w
        for w in bounded.derive_gemini_d_compile_windows(candidate.request)
        if w["field_refs"] and any(by_ref[r]["evidence"] for r in w["field_refs"])
    )
    fields = json.loads(_response([by_ref[ref] for ref in window["field_refs"]]))["fields"]
    bad = next(row for row in fields if row["evidence"])
    bad["evidence"][0]["quote"] = "not actually supplied as source"
    raw = _response(fields)
    keys = {row["field_ref"]: row["field_key"] for row in targets}
    chosen = [keys[row["field_ref"]] for row in fields if row is not bad]
    output = module.project_g3_recorded_compile_subset(
        raw, candidate.request, window, field_keys=chosen
    )
    assert len(output.fields) == len(chosen)
    assert raw == _response(fields)
    with pytest.raises(ValueError, match="offered"):
        module.project_g3_recorded_compile_subset(
            raw, candidate.request, window, field_keys=[keys[bad["field_ref"]]]
        )
    with pytest.raises(ValueError):
        module.project_g3_recorded_compile_subset(
            raw, candidate.request, window, field_keys=["foreign"]
        )


def test_synthesis_label_survives_full_and_recovery_aggregation(
    fixture: tuple[
        BatchConceptCandidateBundle830G3V1, list[bounded.G3DFieldTarget], dict[str, Any]
    ],
) -> None:
    module = _module()
    candidate, targets, by_ref = fixture
    outputs = []
    for window in bounded.derive_gemini_d_compile_windows(candidate.request):
        raw = _response(
            [by_ref[ref] for ref in window["field_refs"]],
            "SYNTHESIZE" if window["kind"] == "ENTITY_SYNTHESIS" else "EXTRACT",
        )
        output = bounded.project_gemini_d_compile_window_response(raw, candidate.request, window)
        if window["kind"] == "ENTITY_SYNTHESIS":
            assert (
                module.project_g3_recorded_compile_subset(
                    raw, candidate.request, window, include_synthesis=True
                ).transformation
                == "SYNTHESIZE"
            )
        outputs.append(output)
    assert (
        bounded.aggregate_gemini_d_compile_window_outputs(candidate.request, outputs).transformation
        == "SYNTHESIZE"
    )
    assert (
        module.aggregate_g3_recovered_compile_outputs(candidate.request, outputs).transformation
        == "SYNTHESIZE"
    )
    with pytest.raises(ValueError, match="duplicate"):
        module.aggregate_g3_recovered_compile_outputs(
            candidate.request, [*outputs, next(row for row in outputs if row.fields)]
        )
    with pytest.raises(ValueError, match="coverage"):
        module.aggregate_g3_recovered_compile_outputs(
            candidate.request, [row for row in outputs if not row.fields]
        )
