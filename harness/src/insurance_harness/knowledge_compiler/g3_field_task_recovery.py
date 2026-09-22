"""Explicit bounded field recovery and immutable recorded-response projections.

These pure functions create no admission, provider call or SUCCESS receipt. A
caller must bind a recorded selection to its original response and call custody.
Selection never rewrites captured bytes; recorded field subsets use only closed,
deterministic wire adaptations before strict projection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from insurance_harness.model_policy import ModelIdentity
from insurance_harness.run_admission.g3_models import canonical_json

from .batch_canonical_830_g3 import batch_json_bytes_830_g3
from .g3_field_tasks import adapt_catalog_field_tasks

if TYPE_CHECKING:
    from .batch_concept_compile_830_g3 import BatchConceptCompileRequest830G3V1
    from .concept_compile_830_g2 import CompileOutput
    from .g3_bounded_model_execution import (
        G3DCompileReferenceResponseV1,
        G3DFieldTarget,
        G3DOutputWindow,
        G3DRecoveryWindow,
    )

RECOVERY_VERSION = "g3-field-task-recovery.830.v1"


def derive_g3_field_recovery_window(
    request: BatchConceptCompileRequest830G3V1,
    *,
    entity_id: str,
    field_keys: Sequence[str] = (),
    field_refs: Sequence[str] = (),
) -> G3DRecoveryWindow:
    """Select one same-entity 1–10 task window, with code-owned refs and budget."""
    from . import g3_bounded_model_execution as runtime

    if bool(field_keys) == bool(field_refs):
        raise ValueError("recovery requires exactly one nonempty field selector")
    selector = tuple(field_keys or field_refs)
    if len(selector) > 10 or len(selector) != len(set(selector)):
        raise ValueError("recovery field selection must be unique and at most ten")
    slots = [row for row in runtime._g3_d_entity_slots(request) if row[0].entity_id == entity_id]
    if len(slots) != 1:
        raise ValueError("recovery entity is not currently bound")
    binding, primary_material_id, entity_slot = slots[0]
    entity_refs = runtime._g3_d_entity_refs(request)
    target_rows = [
        row
        for row in runtime._g3_d_field_targets(request, entity_refs)
        if row["entity_id"] == entity_id
    ]
    selected = (
        [row for row in target_rows if row["field_key"] in selector]
        if field_keys
        else [row for row in target_rows if row["field_ref"] in selector]
    )
    selected_values = {row["field_key"] if field_keys else row["field_ref"] for row in selected}
    if selected_values != set(selector):
        raise ValueError("recovery contains foreign or unbound field targets")
    selected_keys = tuple(str(row["field_key"]) for row in selected)
    tasks = [
        task
        for task in adapt_catalog_field_tasks(request)
        if task.entity_id == entity_id and task.field_key in selected_keys
    ]
    if len(tasks) != len(selected):
        raise ValueError("recovery FieldTask coverage mismatch")
    value = {
        "recovery_contract": RECOVERY_VERSION,
        "primary_material_id": primary_material_id,
        "material_ids": binding.source_material_ids,
        "entity_slot": entity_slot,
        "entity_id": entity_id,
        "entity_ref": entity_refs[entity_id],
        "kind": "FIELDS",
        "field_refs": tuple(str(row["field_ref"]) for row in selected),
        "field_keys": selected_keys,
        "task_sha256s": tuple(task.task_sha256 for task in tasks),
    }
    return {
        "recovery_contract": RECOVERY_VERSION,
        "primary_material_id": primary_material_id,
        "material_ids": binding.source_material_ids,
        "entity_slot": entity_slot,
        "entity_id": entity_id,
        "entity_ref": entity_refs[entity_id],
        "kind": "FIELDS",
        "field_refs": tuple(str(row["field_ref"]) for row in selected),
        "field_keys": selected_keys,
        "task_sha256s": tuple(task.task_sha256 for task in tasks),
        "window_id": runtime._g3_d_ref(
            "window",
            request.request_sha256,
            {"extraction_policy": runtime.gemini_d_extraction_policy(), **value},
        ),
    }


def _exact_recovery_window(
    request: BatchConceptCompileRequest830G3V1, window: Mapping[str, object]
) -> G3DRecoveryWindow:
    entity_id = window.get("entity_id")
    field_refs = window.get("field_refs", ())
    if (
        not isinstance(entity_id, str)
        or not isinstance(field_refs, (tuple, list))
        or not all(isinstance(item, str) for item in field_refs)
    ):
        raise ValueError("recovery window must be an exact mapping")
    exact = derive_g3_field_recovery_window(
        request,
        entity_id=entity_id,
        field_refs=field_refs,
    )
    if batch_json_bytes_830_g3(exact) != batch_json_bytes_830_g3(window):
        raise ValueError("recovery window scope or policy mismatch")
    return exact


def render_g3_field_recovery_context(
    identity: ModelIdentity,
    request: BatchConceptCompileRequest830G3V1,
    window: Mapping[str, object],
) -> dict[str, Any]:
    from . import g3_bounded_model_execution as runtime

    if not runtime._is_g3_gemini_d_identity("D_COMPILE", identity):
        raise ValueError("recovery requires Gemini extract identity")
    exact = _exact_recovery_window(request, window)
    context = runtime._render_gemini_d_compile_window_context(identity, request, exact)
    policy = runtime.gemini_d_extraction_policy()
    max_source_chars = policy["max_source_chars"]
    max_source_span_chars = policy["max_source_span_chars"]
    if not isinstance(max_source_chars, int) or not isinstance(max_source_span_chars, int):
        raise RuntimeError("invalid recovery source policy")
    spans = [span for source in context["source_options"] for span in source["spans"]]
    if sum(len(span["quote"]) for span in spans) > max_source_chars or any(
        len(span["quote"]) > max_source_span_chars for span in spans
    ):
        raise ValueError("recovery source budget exceeded")
    return dict(context)


def _parse_semantic(raw: bytes) -> G3DCompileReferenceResponseV1:
    from . import g3_bounded_model_execution as runtime

    response = runtime.G3DCompileReferenceResponseV1.model_validate(runtime._unique_json_bytes(raw))
    if canonical_json(response.model_dump(mode="json", round_trip=True)) != raw:
        raise ValueError("D compile semantic wire mismatch")
    return response


def _identity() -> ModelIdentity:
    return ModelIdentity(
        provider="g3-user-gateway",
        family="gemini",
        deployment_id="gemini-3.7-flash-medium",
        role="extract",
        policy_version="g3-user-gemini-gateway-v1",
    )


def project_g3_field_recovery_response(
    raw: bytes,
    request: BatchConceptCompileRequest830G3V1,
    window: Mapping[str, object],
) -> CompileOutput:
    """Project a new response under the exact subset and bounded offered evidence."""
    from . import g3_bounded_model_execution as runtime

    exact = _exact_recovery_window(request, window)
    context = render_g3_field_recovery_context(_identity(), request, exact)
    return runtime._project_gemini_d_compile_response_with_context(
        _parse_semantic(raw),
        request,
        exact,
        context,
    )


def _parse_recorded_field_subset(
    raw: bytes,
    exact: G3DRecoveryWindow,
    context: Mapping[str, Any],
    field_keys: Sequence[str],
) -> tuple[G3DCompileReferenceResponseV1, list[G3DFieldTarget]]:
    """Validate the original envelope, then adapt and parse only selected fields."""
    from . import g3_bounded_model_execution as runtime

    value = runtime._unique_json_bytes(raw)
    envelope_keys = {"contract", "transformation", "definitions", "fields", "pages"}
    if (
        not isinstance(value, dict)
        or set(value) != envelope_keys
        or value.get("contract") != "g3-d-compile-semantic-references.local.v1"
        or value.get("definitions") != []
        or value.get("pages") != []
        or not isinstance(value.get("fields"), list)
    ):
        raise ValueError("recorded field response envelope mismatch")
    object_fields = []
    for row in value["fields"]:
        if row is None:
            continue
        if not isinstance(row, dict) or not isinstance(row.get("field_ref"), str):
            raise ValueError("recorded field response contains non-null member noise")
        object_fields.append(row)
    refs = tuple(row["field_ref"] for row in object_fields)
    if len(refs) != len(set(refs)) or set(refs) != set(exact["field_refs"]):
        raise ValueError("recorded origin field reference coverage mismatch")
    targets = [row for row in context["field_targets"] if row["field_key"] in field_keys]
    if {row["field_key"] for row in targets} != set(field_keys):
        raise ValueError("recorded selection contains foreign field keys")
    chosen = {row["field_ref"] for row in targets}
    selected = []
    for original in object_fields:
        if original["field_ref"] not in chosen:
            continue
        row = dict(original)
        if "valid_time" in row and row["valid_time"] is None:
            row["valid_time"] = ""
        if (
            "evidence" not in row
            and row.get("state") == "unknown"
            and "value" in row
            and row["value"] is None
            and isinstance(row.get("unknown_reason"), str)
            and row["unknown_reason"].strip()
        ):
            row["evidence"] = []
        concept_refs = row.get("concept_refs")
        if isinstance(concept_refs, list):
            row["concept_refs"] = [
                item["concept_ref"]
                if (
                    isinstance(item, dict)
                    and set(item) == {"concept_ref"}
                    and isinstance(item["concept_ref"], str)
                )
                else item
                for item in concept_refs
            ]
        selected.append(row)
    derived = {**value, "fields": selected}
    response = runtime.G3DCompileReferenceResponseV1.model_validate(derived)
    if canonical_json(response.model_dump(mode="json", round_trip=True)) != (
        canonical_json(derived)
    ):
        raise ValueError("recorded selected field wire mismatch")
    return response, targets


def project_g3_recorded_compile_subset(
    raw: bytes,
    request: BatchConceptCompileRequest830G3V1,
    origin_window: G3DRecoveryWindow,
    *,
    field_keys: Sequence[str] = (),
    include_synthesis: bool = False,
    origin_context: Mapping[str, object] | None = None,
) -> CompileOutput:
    """Reproduce only explicit manifest members, using the ORIGINAL offered spans."""
    from . import g3_bounded_model_execution as runtime

    if origin_window.get("recovery_contract"):
        exact = _exact_recovery_window(request, origin_window)
        context = validate_recorded_recovery_context(request, exact, origin_context)
    else:
        if origin_context is not None:
            raise ValueError("full recorded window does not accept an alternate context")
        exact = runtime._exact_gemini_d_window(request, origin_window)
        context = runtime.render_gemini_d_compile_window_context(_identity(), request, exact)
    if include_synthesis:
        response = _parse_semantic(raw)
        if field_keys or exact["kind"] != "ENTITY_SYNTHESIS":
            raise ValueError("recorded synthesis selection exceeds origin scope")
    else:
        if exact["kind"] != "FIELDS" or not field_keys or len(field_keys) != len(set(field_keys)):
            raise ValueError("recorded field selection must be an explicit unique subset")
        response, targets = _parse_recorded_field_subset(raw, exact, context, tuple(field_keys))
        context = {**context, "field_targets": targets}
    return runtime._project_gemini_d_compile_response_with_context(
        response,
        request,
        exact,
        context,
    )


def validate_recorded_recovery_context(
    request: BatchConceptCompileRequest830G3V1,
    window: G3DRecoveryWindow,
    origin_context: Mapping[str, object] | None,
) -> Mapping[str, object]:
    """Require the captured routing scope, allowing only non-routing prompt metadata."""
    if origin_context is None:
        raise ValueError("recorded recovery requires its original signed context")
    expected = render_g3_field_recovery_context(_identity(), request, window)
    ignored = {"response_schema", "correction_instructions"}
    actual_scope = {key: value for key, value in origin_context.items() if key not in ignored}
    expected_scope = {key: value for key, value in expected.items() if key not in ignored}
    if batch_json_bytes_830_g3(actual_scope) != batch_json_bytes_830_g3(expected_scope):
        raise ValueError("recorded recovery context routing/source scope mismatch")
    return origin_context


def aggregate_g3_recovered_compile_outputs(
    request: BatchConceptCompileRequest830G3V1,
    outputs: Sequence[CompileOutput],
) -> CompileOutput:
    """Require an exact complete delta after custody-verified reuse plus new tasks."""
    from . import g3_bounded_model_execution as runtime

    targets = {
        (row["entity_id"], row["field_key"]): row["field_ref"]
        for row in runtime._g3_d_field_targets(request, runtime._g3_d_entity_refs(request))
    }
    windows: list[G3DOutputWindow] = []
    for output in outputs:
        if output.fields and (output.definitions or output.pages):
            raise ValueError("recovered output mixes field and synthesis scopes")
        try:
            refs = tuple(targets[(row.entity_id, row.field_key)] for row in output.fields)
        except KeyError as exc:
            raise ValueError("recovered output contains foreign field") from exc
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate recovered field")
        windows.append(
            {"kind": "FIELDS" if output.fields else "ENTITY_SYNTHESIS", "field_refs": refs}
        )
    return runtime._aggregate_gemini_d_compile_outputs(request, windows, outputs)
