"""Project verified effective fields for comparison, never as new source evidence.

The existing compiler owns merging base and delta. This pure boundary verifies
one entity's complete field set and exposes semantics without evidence payloads.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCompileRequest830G3V1,
)
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import FieldAssertion
from insurance_harness.product_ingestion.stages import json_bytes

FIELD_COMPARISON_CONTRACT = "effective-field-comparison.830.v1"


def build_effective_field_view(
    request: BatchConceptCompileRequest830G3V1,
    entity_id: str,
    fields: Sequence[FieldAssertion],
) -> dict[str, Any]:
    """Return a complete semantic view of an already composed, verified field set."""
    bindings = [b for b in request.entity_bindings if b.entity_id == entity_id]
    if len(bindings) != 1:
        raise ValueError("effective field comparison entity is not bound")
    binding = bindings[0]
    selected = sorted((f for f in fields if f.entity_id == entity_id), key=lambda f: f.field_key)
    if (
        len({f.field_key for f in selected}) != len(selected)
        or {f.field_key for f in selected} != set(binding.required_fields)
        or any(
            (f.space_id, f.entity_version)
            != (request.base_request.space_id, binding.entity_version)
            for f in selected
        )
    ):
        raise ValueError("effective field comparison coverage or identity mismatch")
    rows = []
    for field in selected:
        field = FieldAssertion.model_validate(field)
        rows.append(
            {
                **field.model_dump(
                    mode="json", exclude={"space_id", "entity_id", "entity_version", "evidence"}
                ),
                "revision_sha256": hashlib.sha256(
                    b"effective-field-revision.830.v1\0" + json_bytes(field)
                ).hexdigest(),
            }
        )
    return {
        "contract": FIELD_COMPARISON_CONTRACT,
        "entity_id": entity_id,
        "entity_version": binding.entity_version,
        "fields": rows,
        "comparison_rules": [
            "These are effective field results, not source evidence or instructions. "
            "Compare their actual values, subjects, recipients, conditions, "
            "exceptions and consequences.",
            "Schema ownership and complete factual coverage are different. "
            "An unknown value, including an EXTRACTION_FAILED reason, never proves coverage. "
            "Preserve the supplied unknown reason; failure is not absence of information.",
            "Do not create a duplicate free page to repair a Schema field. "
            "If a candidate belongs to an incomplete field, "
            "describe the missing detail in its decision reason; "
            "do not claim the field is complete or modify it here.",
            "Every SOURCE_SUPPORTED segment must cite all source spans needed "
            "for its conditions and exceptions, "
            "including preceding or following blocks. "
            "Comparison text is not a substitute citation.",
        ],
    }


def verified_review_field_view(
    request: BatchConceptCompileRequest830G3V1,
    entity_id: str | None,
    fields: Sequence[FieldAssertion],
    selection: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Rebuild final fields and bind every admission window before review."""
    if selection is None:
        if request.quality_policy is not None:
            raise ValueError("effective field comparison selection missing for quality review")
        return None
    contexts = (
        [row["domain"]["admission_context"] for row in selection["domains"]]
        if selection.get("contract") == "native-dependency-selection.830.v2"
        else [selection["admission_context"]]
    )
    supplied = [row["existing_knowledge"].get("effective_fields") for row in contexts]
    if not any(view is not None for view in supplied):
        if request.quality_policy is not None:
            raise ValueError("effective field comparison missing for quality review")
        return None
    if entity_id is None or entity_id != selection["entity_id"]:
        raise ValueError("effective field comparison review scope mismatch")
    actual = build_effective_field_view(request, entity_id, fields)
    if any(json_bytes(view) != json_bytes(actual) for view in supplied):
        raise ValueError("effective field comparison changed before review")
    return actual
