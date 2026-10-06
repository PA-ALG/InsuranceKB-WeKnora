"""Closed completion contract, ported from V5 llm_plugin.py / contracts.py.

Legacy originals retire in S7. Unlike the preview's fallback behavior, any
malformed envelope, row, state or evidence shape rejects the entire batch.
"""

import json
from collections.abc import Sequence
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from insurance_harness.compilers.schema_fields.definitions import FieldDefinition, NonBlank
from insurance_harness.evidence.quote_verification import QuoteReference


class CompileError(ValueError):
    """Input or completion violates the field compiler's contract."""


class ParsedField(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    ordinal: int = Field(ge=0)
    field_key: NonBlank
    state: Literal["present", "absent_explicitly", "unknown"]
    value: NonBlank | None
    evidence: list[QuoteReference]

    @model_validator(mode="after")
    def check_state(self) -> Self:
        if self.state == "present" and (self.value is None or not self.evidence):
            raise ValueError("present requires value and evidence")
        if self.state == "absent_explicitly" and (self.value is not None or not self.evidence):
            raise ValueError("absent_explicitly requires evidence and no value")
        if self.state == "unknown" and (self.value is not None or self.evidence):
            raise ValueError("unknown requires neither value nor evidence")
        return self


class _Response(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    fields: list[ParsedField]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CompileError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise CompileError("non-finite JSON number")


def parse_response(raw: str, definitions: Sequence[FieldDefinition]) -> list[ParsedField]:
    """Validate all rows before returning any; keep diagnostics free of raw content."""
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (TypeError, json.JSONDecodeError) as exc:
        raise CompileError("completion is not a JSON object") from exc
    try:
        result = _Response.model_validate(payload)
    except ValidationError as exc:
        raise CompileError("completion has an invalid field, evidence or state shape") from exc
    expected = [(field.ordinal, field.field_key) for field in definitions]
    actual = [(field.ordinal, field.field_key) for field in result.fields]
    if actual != expected:
        keys = ", ".join(field.field_key for field in definitions)
        raise CompileError(f"completion field order/count/identity mismatch; expected: {keys}")
    return result.fields
