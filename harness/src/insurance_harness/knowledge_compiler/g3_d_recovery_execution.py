"""Plan only missing FieldTasks after custody-verified projection reuse."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from insurance_harness.model_policy import ModelIdentity

from .batch_concept_compile_830_g3 import BatchConceptCompileRequest830G3V1
from .concept_compile_830_g2 import CompileOutput
from .g3_d_projection_reuse import G3DProjectionReuseManifestV1
from .g3_field_task_recovery import (
    derive_g3_field_recovery_window,
    project_g3_field_recovery_response,
    render_g3_field_recovery_context,
)
from .g3_field_tasks import adapt_catalog_field_tasks

if TYPE_CHECKING:
    from .g3_bounded_model_execution import G3DCompileWindow, G3DRecoveryWindow


def normalize_projection_reuse(value: object) -> tuple[G3DProjectionReuseManifestV1, ...]:
    """Normalize one or multiple manifests without granting historical custody."""
    items = value if isinstance(value, (tuple, list)) else (value,)
    if not items:
        raise ValueError("projection reuse manifests must not be empty")
    manifests = tuple(G3DProjectionReuseManifestV1.model_validate(item) for item in items)
    if len({item.manifest_sha256 for item in manifests}) != len(manifests):
        raise ValueError("projection reuse manifest is duplicated")
    if len({item.current_request_sha256 for item in manifests}) != 1:
        raise ValueError("projection reuse manifests bind different current requests")
    return manifests


def derive_recovery_windows(
    request: BatchConceptCompileRequest830G3V1, manifest: object
) -> tuple[G3DRecoveryWindow, ...]:
    from .g3_bounded_model_execution import derive_gemini_d_compile_windows

    manifests = normalize_projection_reuse(manifest)
    if any(row.current_request_sha256 != request.request_sha256 for row in manifests):
        raise ValueError("projection reuse current request mismatch")
    tasks = adapt_catalog_field_tasks(request)
    required = {(task.entity_id, task.field_key) for task in tasks}
    reused = set()
    synthesis = set()
    entities = {binding.entity_id for binding in request.entity_bindings}
    for entry in (entry for item in manifests for entry in item.entries):
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
    grouped: dict[str, list[str]] = {}
    for entity_id, field_key in sorted(required - reused):
        grouped.setdefault(entity_id, []).append(field_key)
    windows: list[G3DRecoveryWindow] = []
    for entity_id, keys in sorted(grouped.items()):
        for start in range(0, len(keys), 10):
            windows.append(
                derive_g3_field_recovery_window(
                    request,
                    entity_id=entity_id,
                    field_keys=keys[start : start + 10],
                )
            )
    windows.extend(
        row
        for row in derive_gemini_d_compile_windows(request)
        if row["kind"] == "ENTITY_SYNTHESIS" and row["entity_id"] not in synthesis
    )
    return tuple(windows)


def render_recovery_context(
    identity: ModelIdentity,
    request: BatchConceptCompileRequest830G3V1,
    window: G3DCompileWindow,
) -> dict[str, Any]:
    from .g3_bounded_model_execution import render_gemini_d_compile_window_context

    context: dict[str, Any]
    if window.get("recovery_contract"):
        context = render_g3_field_recovery_context(identity, request, window)
        context = {
            **context,
            "correction_instructions": (
                "Only return the requested fields; previous valid fields are already retained.",
                "Field windows must use transformation EXTRACT.",
                "Unknown is not explicit absence. Use unknown with null value "
                "if no direct evidence "
                "establishes a responsibility or its explicit exclusion.",
                "Do not infer explicit absence from unrelated conditions, duration, "
                "or missing text.",
                "Each quote must be an unchanged contiguous fragment of an offered span. "
                "Prefer a short supporting fragment within one original line; never join "
                "text across a PDF line break or insert spaces or punctuation. A complete "
                "sentence is not required. Repeated exact fragments are allowed: the "
                "runtime retains all offered exact locations.",
                "EXTRACT requires a direct statement about the requested field. Do not "
                "infer a target customer profile solely from general benefits or the "
                "permitted insured age range. If the source does not state that profile, "
                "use unknown with null value, empty evidence and a specific unknown_reason.",
                "Never infer a general rule from an incomplete list or fabricate a quote. "
                "If the offered text is insufficient, record unknown.",
            ),
        }
    else:
        context = dict(render_gemini_d_compile_window_context(identity, request, window))
    schema = context["response_schema"]
    properties = schema["properties"]
    return {
        **context,
        "response_schema": {
            **schema,
            "properties": {
                **properties,
                "transformation": {
                    **properties["transformation"],
                    "enum": ["EXTRACT"]
                    if window["kind"] == "FIELDS"
                    else ["EXTRACT", "SYNTHESIZE"],
                },
            },
        },
    }


def project_recovery_response(
    raw: bytes,
    request: BatchConceptCompileRequest830G3V1,
    window: G3DCompileWindow,
) -> CompileOutput:
    from .g3_bounded_model_execution import project_gemini_d_compile_window_response

    if window.get("recovery_contract"):
        return project_g3_field_recovery_response(raw, request, window)
    return project_gemini_d_compile_window_response(raw, request, window)
