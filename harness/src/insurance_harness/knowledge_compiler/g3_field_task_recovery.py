"""Explicit bounded field recovery and immutable recorded-response projections.

These pure functions create no admission, provider call or SUCCESS receipt. A
caller must bind a recorded selection to its original response and call custody.
The original response is parsed intact; selection never rewrites captured bytes.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from insurance_harness.model_policy import ModelIdentity

    from .batch_concept_compile_830_g3 import BatchConceptCompileRequest830G3V1
    from .concept_compile_830_g2 import CompileOutput

RECOVERY_VERSION = "g3-field-task-recovery.830.v1"


def _runtime():
    from . import g3_bounded_model_execution

    return g3_bounded_model_execution


def derive_g3_field_recovery_window(
    request: BatchConceptCompileRequest830G3V1,
    *,
    entity_id: str,
    field_keys: Sequence[str] = (),
    field_refs: Sequence[str] = (),
) -> dict[str, object]:
    """Select one same-entity 1–10 task window, with code-owned refs and budget."""
    runtime = _runtime()
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
    selector_key = "field_key" if field_keys else "field_ref"
    selected = [row for row in target_rows if row[selector_key] in selector]
    if {row[selector_key] for row in selected} != set(selector):
        raise ValueError("recovery contains foreign or unbound field targets")
    selected_keys = tuple(str(row["field_key"]) for row in selected)
    tasks = [
        task
        for task in runtime.adapt_catalog_field_tasks(request)
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
        **value,
        "window_id": runtime._g3_d_ref(
            "window",
            request.request_sha256,
            {"extraction_policy": runtime.gemini_d_extraction_policy(), **value},
        ),
    }


def _exact_recovery_window(request, window):
    runtime = _runtime()
    if not isinstance(window, dict):
        raise ValueError("recovery window must be an exact mapping")
    exact = derive_g3_field_recovery_window(
        request,
        entity_id=window.get("entity_id"),
        field_refs=window.get("field_refs", ()),
    )
    if runtime.batch_json_bytes_830_g3(exact) != runtime.batch_json_bytes_830_g3(window):
        raise ValueError("recovery window scope or policy mismatch")
    return exact


def render_g3_field_recovery_context(
    identity: ModelIdentity,
    request: BatchConceptCompileRequest830G3V1,
    window: dict[str, object],
) -> dict[str, object]:
    runtime = _runtime()
    if not runtime._is_g3_gemini_d_identity("D_COMPILE", identity):
        raise ValueError("recovery requires Gemini extract identity")
    exact = _exact_recovery_window(request, window)
    context = runtime._render_gemini_d_compile_window_context(identity, request, exact)
    policy = runtime.gemini_d_extraction_policy()
    spans = [span for source in context["source_options"] for span in source["spans"]]
    if sum(len(span["quote"]) for span in spans) > policy["max_source_chars"] or any(
        len(span["quote"]) > policy["max_source_span_chars"] for span in spans
    ):
        raise ValueError("recovery source budget exceeded")
    return context


def _parse_semantic(raw: bytes):
    runtime = _runtime()
    response = runtime.G3DCompileReferenceResponseV1.model_validate(runtime._unique_json_bytes(raw))
    if runtime.canonical_json(response.model_dump(mode="json", round_trip=True)) != raw:
        raise ValueError("D compile semantic wire mismatch")
    return response


def _identity():
    return _runtime().ModelIdentity(
        provider="g3-user-gateway",
        family="gemini",
        deployment_id="gemini-3.7-flash-medium",
        role="extract",
        policy_version="g3-user-gemini-gateway-v1",
    )


def project_g3_field_recovery_response(
    raw: bytes,
    request: BatchConceptCompileRequest830G3V1,
    window: dict[str, object],
) -> CompileOutput:
    """Project a new response under the exact subset and bounded offered evidence."""
    runtime = _runtime()
    exact = _exact_recovery_window(request, window)
    context = render_g3_field_recovery_context(_identity(), request, exact)
    return runtime._project_gemini_d_compile_response_with_context(
        _parse_semantic(raw),
        request,
        exact,
        context,
    )


def project_g3_recorded_compile_subset(
    raw: bytes,
    request: BatchConceptCompileRequest830G3V1,
    origin_window: dict[str, object],
    *,
    field_keys: Sequence[str] = (),
    include_synthesis: bool = False,
    origin_context: dict[str, object] | None = None,
) -> CompileOutput:
    """Reproduce only explicit manifest members, using the ORIGINAL offered spans."""
    runtime = _runtime()
    if origin_window.get("recovery_contract"):
        exact = _exact_recovery_window(request, origin_window)
        context = validate_recorded_recovery_context(request, exact, origin_context)
    else:
        if origin_context is not None:
            raise ValueError("full recorded window does not accept an alternate context")
        exact = runtime._exact_gemini_d_window(request, origin_window)
        context = runtime.render_gemini_d_compile_window_context(_identity(), request, exact)
    response = _parse_semantic(raw)
    if include_synthesis:
        if field_keys or exact["kind"] != "ENTITY_SYNTHESIS":
            raise ValueError("recorded synthesis selection exceeds origin scope")
    else:
        if exact["kind"] != "FIELDS" or not field_keys or len(field_keys) != len(set(field_keys)):
            raise ValueError("recorded field selection must be an explicit unique subset")
        if response.definitions or response.pages:
            raise ValueError("D field window cannot create definitions or pages")
        refs = tuple(row.field_ref for row in response.fields)
        if len(refs) != len(set(refs)) or set(refs) != set(exact["field_refs"]):
            raise ValueError("recorded origin field reference coverage mismatch")
        targets = [row for row in context["field_targets"] if row["field_key"] in field_keys]
        if {row["field_key"] for row in targets} != set(field_keys):
            raise ValueError("recorded selection contains foreign field keys")
        chosen = {row["field_ref"] for row in targets}
        # A derived in-memory view, never a replacement raw response or call receipt.
        response = response.model_copy(
            update={"fields": tuple(row for row in response.fields if row.field_ref in chosen)}
        )
        context = {**context, "field_targets": targets}
    return runtime._project_gemini_d_compile_response_with_context(
        response,
        request,
        exact,
        context,
    )


def validate_recorded_recovery_context(request, window, origin_context):
    """Require the captured routing scope, allowing only non-routing prompt metadata."""
    runtime = _runtime()
    if not isinstance(origin_context, dict):
        raise ValueError("recorded recovery requires its original signed context")
    expected = render_g3_field_recovery_context(_identity(), request, window)
    ignored = {"response_schema", "correction_instructions"}
    actual_scope = {key: value for key, value in origin_context.items() if key not in ignored}
    expected_scope = {key: value for key, value in expected.items() if key not in ignored}
    if runtime.batch_json_bytes_830_g3(actual_scope) != runtime.batch_json_bytes_830_g3(
        expected_scope
    ):
        raise ValueError("recorded recovery context routing/source scope mismatch")
    return origin_context


def aggregate_g3_recovered_compile_outputs(
    request: BatchConceptCompileRequest830G3V1,
    outputs: Sequence[CompileOutput],
) -> CompileOutput:
    """Require an exact complete delta after custody-verified reuse plus new tasks."""
    runtime = _runtime()
    targets = {
        (row["entity_id"], row["field_key"]): row["field_ref"]
        for row in runtime._g3_d_field_targets(request, runtime._g3_d_entity_refs(request))
    }
    windows = []
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
