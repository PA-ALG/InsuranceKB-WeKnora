"""Plan only missing FieldTasks after custody-verified projection reuse."""

from .g3_field_task_recovery import (
    derive_g3_field_recovery_window,
    project_g3_field_recovery_response,
    render_g3_field_recovery_context,
)
from .g3_field_tasks import adapt_catalog_field_tasks


def derive_recovery_windows(request, manifest) -> tuple[dict[str, object], ...]:
    from .g3_bounded_model_execution import derive_gemini_d_compile_windows

    tasks = adapt_catalog_field_tasks(request)
    required = {(task.entity_id, task.field_key) for task in tasks}
    reused = set()
    synthesis = set()
    entities = {binding.entity_id for binding in request.entity_bindings}
    for entry in manifest.entries:
        if entry.entity_id not in entities:
            raise ValueError("reused projection belongs to a foreign entity")
        for field_key in entry.field_keys:
            key = (entry.entity_id, field_key)
            if key not in required or key in reused:
                raise ValueError("reused field is foreign or duplicated")
            reused.add(key)
        if entry.include_synthesis:
            if entry.entity_id in synthesis:
                raise ValueError("reused synthesis is duplicated")
            synthesis.add(entry.entity_id)
    grouped = {}
    for entity, key in sorted(required - reused):
        grouped.setdefault(entity, []).append(key)
    windows = []
    for entity, keys in sorted(grouped.items()):
        for start in range(0, len(keys), 10):
            windows.append(derive_g3_field_recovery_window(
                request, entity_id=entity, field_keys=keys[start:start + 10],
            ))
    windows.extend(
        row for row in derive_gemini_d_compile_windows(request)
        if row["kind"] == "ENTITY_SYNTHESIS" and row["entity_id"] not in synthesis
    )
    return tuple(windows)


def render_recovery_context(identity, request, window):
    from .g3_bounded_model_execution import render_gemini_d_compile_window_context

    if window.get("recovery_contract"):
        context = render_g3_field_recovery_context(identity, request, window)
        context = {**context, "correction_instructions": (
            "Only return the requested fields; previous valid fields are already retained.",
            "Field windows must use transformation EXTRACT.",
            "Unknown is not explicit absence. Use unknown with null value if no direct evidence "
            "establishes a responsibility or its explicit exclusion.",
            "Do not infer explicit absence from unrelated conditions, duration, or missing text.",
            "Each quote must exactly preserve characters and line breaks in an offered span. "
            "Use a longer unique quotation if the short quote occurs more than once.",
            "Never infer a general rule from an incomplete list or fabricate a quote. "
            "If the offered text is insufficient, record unknown.",
        )}
    else:
        context = render_gemini_d_compile_window_context(identity, request, window)
    schema = context["response_schema"]
    properties = schema["properties"]
    return {**context, "response_schema": {
        **schema, "properties": {**properties, "transformation": {
            **properties["transformation"],
            "enum": ["EXTRACT"] if window["kind"] == "FIELDS" else ["EXTRACT", "SYNTHESIZE"],
        }},
    }}


def project_recovery_response(raw, request, window):
    from .g3_bounded_model_execution import project_gemini_d_compile_window_response

    if window.get("recovery_contract"):
        return project_g3_field_recovery_response(raw, request, window)
    return project_gemini_d_compile_window_response(raw, request, window)
