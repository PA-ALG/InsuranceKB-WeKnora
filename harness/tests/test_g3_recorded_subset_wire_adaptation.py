from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from insurance_harness.knowledge_compiler import g3_bounded_model_execution as bounded
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    validate_batch_candidate,
)
from insurance_harness.run_admission.g3_models import canonical_json
from tests.test_g3_bounded_model_execution_830 import (
    _gemini_compile_reference_wire,
    _gemini_identity,
)


@pytest.fixture(scope="module")
def recorded_fixture():
    candidate = validate_batch_candidate(
        (
            Path(__file__).parent
            / "fixtures/batch_concept_compile_830_g3/candidate.json"
        ).read_bytes()
    )
    targets = bounded._g3_d_field_targets(
        candidate.request, bounded._g3_d_entity_refs(candidate.request)
    )
    by_key = {
        row["field_ref"]: row["field_key"]
        for row in targets
    }
    full = json.loads(_gemini_compile_reference_wire(candidate))
    by_ref = {row["field_ref"]: row for row in full["fields"]}
    windows = tuple(
        row
        for row in bounded.derive_gemini_d_compile_windows(candidate.request)
        if row["kind"] == "FIELDS"
    )
    return candidate, by_key, by_ref, windows


def _raw(fields, **updates) -> bytes:
    value = {
        "contract": "g3-d-compile-semantic-references.local.v1",
        "transformation": "EXTRACT",
        "definitions": [],
        "fields": list(fields),
        "pages": [],
    }
    value.update(updates)
    return canonical_json(value)


def _all_unknown_window(recorded_fixture):
    candidate, by_key, by_ref, windows = recorded_fixture
    window = next(
        row
        for row in windows
        if all(by_ref[ref]["state"] == "unknown" for ref in row["field_refs"])
    )
    rows = [copy.deepcopy(by_ref[ref]) for ref in window["field_refs"]]
    return candidate, by_key, window, rows


def test_selected_fields_adapt_only_unambiguous_recorded_wire(recorded_fixture) -> None:
    from insurance_harness.knowledge_compiler import g3_field_task_recovery as module

    candidate, by_key, window, rows = _all_unknown_window(recorded_fixture)
    context = bounded.render_gemini_d_compile_window_context(
        _gemini_identity("extract"), candidate.request, window
    )
    concept = context["existing_concept_refs"][0]
    rows[0].pop("evidence")
    rows[1]["valid_time"] = None
    rows[2]["concept_refs"] = [{"concept_ref": concept["concept_ref"]}]
    rows[3]["valid_time"] = {"unselected": "invalid"}
    fields = [item for row in rows for item in (row, None)]
    raw = _raw(fields)
    selected = [by_key[rows[index]["field_ref"]] for index in range(3)]

    first = module.project_g3_recorded_compile_subset(
        raw, candidate.request, window, field_keys=selected
    )
    second = module.project_g3_recorded_compile_subset(
        raw, candidate.request, window, field_keys=selected
    )

    assert first == second
    assert {row.field_key for row in first.fields} == set(selected)
    assert next(row for row in first.fields if row.field_key == selected[0]).evidence == ()
    assert next(row for row in first.fields if row.field_key == selected[1]).valid_time == ""
    assert next(row for row in first.fields if row.field_key == selected[2]).concept_ids == (
        concept["concept_id"],
    )
    assert raw == _raw(fields)


def test_selected_present_without_evidence_is_not_adapted(recorded_fixture) -> None:
    from insurance_harness.knowledge_compiler import g3_field_task_recovery as module

    candidate, by_key, by_ref, windows = recorded_fixture
    window = next(
        row for row in windows if any(by_ref[ref]["evidence"] for ref in row["field_refs"])
    )
    rows = [copy.deepcopy(by_ref[ref]) for ref in window["field_refs"]]
    present = next(row for row in rows if row["state"] == "present" and row["evidence"])
    present.pop("evidence")

    with pytest.raises(ValueError):
        module.project_g3_recorded_compile_subset(
            _raw(rows),
            candidate.request,
            window,
            field_keys=[by_key[present["field_ref"]]],
        )


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "foreign", "non_null_noise"])
def test_original_field_reference_coverage_stays_exact(recorded_fixture, mutation) -> None:
    from insurance_harness.knowledge_compiler import g3_field_task_recovery as module

    candidate, by_key, window, rows = _all_unknown_window(recorded_fixture)
    selected = [by_key[rows[0]["field_ref"]]]
    if mutation == "missing":
        rows = rows[:-1]
    elif mutation == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif mutation == "foreign":
        rows[-1]["field_ref"] = "field_" + "f" * 64
    else:
        rows.append("not literal null")

    with pytest.raises(ValueError):
        module.project_g3_recorded_compile_subset(
            _raw(rows), candidate.request, window, field_keys=selected
        )


def test_invalid_wrappers_and_unknown_shape_remain_rejected(recorded_fixture) -> None:
    from insurance_harness.knowledge_compiler import g3_field_task_recovery as module

    candidate, by_key, window, rows = _all_unknown_window(recorded_fixture)
    context = bounded.render_gemini_d_compile_window_context(
        _gemini_identity("extract"), candidate.request, window
    )
    concept_ref = context["existing_concept_refs"][0]["concept_ref"]
    selected = [by_key[rows[0]["field_ref"]]]
    rows[0]["concept_refs"] = [{"concept_ref": concept_ref, "extra": concept_ref}]
    with pytest.raises(ValueError):
        module.project_g3_recorded_compile_subset(
            _raw(rows), candidate.request, window, field_keys=selected
        )

    rows[0]["concept_refs"] = []
    rows[0].pop("evidence")
    rows[0]["unknown_reason"] = "   "
    with pytest.raises(ValueError):
        module.project_g3_recorded_compile_subset(
            _raw(rows), candidate.request, window, field_keys=selected
        )


def test_original_envelope_must_be_unique_and_canonical(recorded_fixture) -> None:
    from insurance_harness.knowledge_compiler import g3_field_task_recovery as module

    candidate, by_key, window, rows = _all_unknown_window(recorded_fixture)
    selected = [by_key[rows[0]["field_ref"]]]
    raw = _raw(rows)
    duplicate = raw.replace(
        b'{"contract":',
        b'{"contract":"g3-d-compile-semantic-references.local.v1","contract":',
        1,
    )
    for invalid in (duplicate, raw + b"\n", _raw(rows, extra="foreign")):
        with pytest.raises(ValueError):
            module.project_g3_recorded_compile_subset(
                invalid, candidate.request, window, field_keys=selected
            )
