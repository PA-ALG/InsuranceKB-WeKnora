"""Closed completion contracts for the two-step pointer protocol (S4d Spec §3.2–§3.3).

Ported from V5 llm_plugin.py / contracts.py; legacy originals retire in S7. Step one
answers segment ids per field and any malformed envelope, row or state rejects the
whole batch. Step two answers one value or unknown per field (S12c-1): unrequested,
duplicate or malformed rows reject the batch, while a missing row only loses that field's value.
"""

import json
from collections.abc import Sequence
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from insurance_harness.compilers.schema_fields.definitions import FieldDefinition, NonBlank


class CompileError(ValueError):
    """Input or completion violates the field compiler's contract."""


class SelectedField(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    ordinal: int = Field(ge=0)
    field_key: NonBlank
    state: Literal["present", "absent_explicitly", "unknown"]
    # Refs are resolved against the segment listing later; a non-string ref is dropped there.
    segments: list[Any]

    @model_validator(mode="after")
    def check_state(self) -> Self:
        if (self.state == "unknown") != (not self.segments):
            raise ValueError("unknown requires no segments; other states require segments")
        return self


class _Selection(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    fields: list[SelectedField]


class _ValueRow(BaseModel):
    """One step-two answer (S12c-1 §2): a value, or unknown when the segments hold none."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    ordinal: int = Field(ge=0)
    field_key: NonBlank
    state: Literal["present", "unknown"] = "present"  # omitted in answers before S12c-1
    value: str | None = None
    # The model's own working list; never evidence: shrinking the evidence to it cost 0.14
    # segment recall in the #390 ablation, so evidence stays the step-one selection.
    used_segments: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_state(self) -> Self:
        if self.state == "unknown":
            # Decided by key presence: an explicit "value": null is a format error too.
            if "value" in self.model_fields_set:
                raise ValueError("unknown takes no value key")
        elif self.value is None or not self.value.strip():
            raise ValueError("present requires a nonblank value")
        return self


class _Values(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    fields: list[_ValueRow]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CompileError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise CompileError("non-finite JSON number")


def _load(raw: str) -> object:
    try:
        return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (TypeError, json.JSONDecodeError) as exc:
        raise CompileError("completion is not a JSON object") from exc


def parse_selection(raw: str, definitions: Sequence[FieldDefinition]) -> list[SelectedField]:
    """Validate all rows before returning any; keep diagnostics free of raw content."""
    try:
        result = _Selection.model_validate(_load(raw))
    except ValidationError as exc:
        raise CompileError("selection has an invalid field, segment or state shape") from exc
    expected = [(field.ordinal, field.field_key) for field in definitions]
    actual = [(field.ordinal, field.field_key) for field in result.fields]
    if actual != expected:
        keys = ", ".join(field.field_key for field in definitions)
        raise CompileError(f"selection field order/count/identity mismatch; expected: {keys}")
    return result.fields


def parse_values(raw: str, definitions: Sequence[FieldDefinition]) -> dict[str, str | None]:
    """Values by field_key, None for unknown; a requested field may be missing, nothing else
    may differ."""
    return {key: value for key, (value, _) in parse_value_rows(raw, definitions).items()}


def parse_value_rows(
    raw: str, definitions: Sequence[FieldDefinition],
) -> dict[str, tuple[str | None, list[str]]]:
    """As parse_values, with each row's used_segments: the engine decides which carried
    segments step two used (S12c-4 Spec §2.3); this step-one selection is never shrunk."""
    try:
        result = _Values.model_validate(_load(raw))
    except ValidationError as exc:
        raise CompileError("value step has an invalid row shape") from exc
    expected = {field.field_key: field.ordinal for field in definitions}
    keys = [row.field_key for row in result.fields]
    if len(keys) != len(set(keys)) or any(
        expected.get(row.field_key) != row.ordinal for row in result.fields
    ):
        raise CompileError("value step has a duplicate, unrequested or misnumbered field")
    return {row.field_key: (row.value, list(row.used_segments)) for row in result.fields}
