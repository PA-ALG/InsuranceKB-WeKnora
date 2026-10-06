"""Field compilation orchestration, ported from V5 llm_plugin.py / ingest.py.

Legacy originals retire in S7. The caller owns transport and retries; this
engine invokes the completion port once per batch, with a per-compile budget.
The port must reject interrupted/truncated completions before returning text.
"""

from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from insurance_harness.compilers.schema_fields.definitions import FieldDefinition, NonBlank
from insurance_harness.compilers.schema_fields.parse import CompileError as CompileError
from insurance_harness.compilers.schema_fields.parse import parse_response
from insurance_harness.compilers.schema_fields.prompt import JudgeLikeRequest, build_request
from insurance_harness.compilers.schema_fields.values import normalize_field_value
from insurance_harness.evidence.quote_verification import PageTextLike, QuoteVerifier, VerifiedQuote


class CompletionPort(Protocol):
    @property
    def model(self) -> str: ...

    def complete(self, *, system: str, user: str) -> str: ...


class CompileBudgetExceeded(CompileError):
    """No further completion can be sent within this compile's call budget."""


class FieldResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    field_key: NonBlank
    state: Literal["present", "absent_explicitly", "unknown"]
    value: str | None = None
    evidence: list[VerifiedQuote] = Field(default_factory=list)


class CompileOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    pack_id: str
    entity_id: NonBlank
    model: NonBlank
    fields: list[FieldResult] = Field(default_factory=list)
    calls: int = Field(default=0, ge=0)


class SchemaFieldsCompiler:
    def __init__(self, completion: CompletionPort, *, batch_size: int = 25, max_calls: int = 10):
        if type(batch_size) is not int or batch_size < 1:
            raise CompileError("batch_size must be a positive integer")
        if type(max_calls) is not int or max_calls < 0:
            raise CompileError("max_calls must be a nonnegative integer")
        if not isinstance(completion.model, str) or not completion.model.strip():
            raise CompileError("completion must declare its model")
        self._completion = completion
        self._batch_size = batch_size
        self._max_calls = max_calls

    def _prepare(
        self,
        entity_id: str,
        definitions: Sequence[FieldDefinition],
        pages: Sequence[PageTextLike],
    ) -> tuple[tuple[FieldDefinition, ...], QuoteVerifier]:
        if not isinstance(entity_id, str) or not entity_id.strip():
            raise CompileError("entity_id must not be blank")
        fields = tuple(definitions)
        keys = [field.field_key for field in fields]
        ordinals = [field.ordinal for field in fields]
        if len(set(keys)) != len(keys) or any(
            a >= b for a, b in zip(ordinals[:-1], ordinals[1:], strict=True)
        ):
            raise CompileError("definitions must have unique keys and increasing ordinals")
        if len({field.pack_id for field in fields}) > 1:
            raise CompileError("definitions must belong to one pack")
        try:
            verifier = QuoteVerifier(pages)
        except ValueError as exc:
            raise CompileError("invalid or ambiguous source pages") from exc
        if fields and not any(page.text.strip() for page in verifier.pages):
            raise CompileError("source text is required")
        return fields, verifier

    def build_requests(
        self,
        entity_id: str,
        definitions: Sequence[FieldDefinition],
        pages: Sequence[PageTextLike],
    ) -> list[JudgeLikeRequest]:
        fields, verifier = self._prepare(entity_id, definitions, pages)
        return [
            build_request(entity_id, fields[offset : offset + self._batch_size], verifier.pages)
            for offset in range(0, len(fields), self._batch_size)
        ]

    def compile(
        self,
        entity_id: str,
        definitions: Sequence[FieldDefinition],
        pages: Sequence[PageTextLike],
    ) -> CompileOutput:
        fields, verifier = self._prepare(entity_id, definitions, pages)
        results: list[FieldResult] = []
        calls = 0
        for offset in range(0, len(fields), self._batch_size):
            batch = fields[offset : offset + self._batch_size]
            request = build_request(entity_id, batch, verifier.pages)
            if calls >= self._max_calls:
                raise CompileBudgetExceeded(f"compile call budget exhausted after {calls} calls")
            calls += 1
            raw = self._completion.complete(system=request.system, user=request.user)
            parsed = parse_response(raw, batch)
            for definition, row in zip(batch, parsed, strict=True):
                verified = [verifier.verify(reference) for reference in row.evidence]
                if any(reference is None for reference in verified):
                    continue
                results.append(
                    FieldResult(
                        field_key=row.field_key,
                        state=row.state,
                        value=normalize_field_value(definition, row.value),
                        evidence=[reference for reference in verified if reference is not None],
                    )
                )
        return CompileOutput(
            pack_id=fields[0].pack_id if fields else "",
            entity_id=entity_id,
            model=self._completion.model,
            fields=results,
            calls=calls,
        )


def to_candidate(
    output: CompileOutput,
    *,
    display_name: str,
    schema_pack_id: str,
) -> dict[str, object]:
    """Adapt to the existing candidate reader without importing evaluation code."""
    if not display_name.strip() or not schema_pack_id.strip():
        raise CompileError("display name and pack identity are required")
    if output.pack_id and output.pack_id != schema_pack_id:
        raise CompileError("candidate pack identity does not match compilation")
    return {
        "request": {
            "entity_bindings": [
                {
                    "entity_id": output.entity_id,
                    "display_name": display_name,
                    "schema_pack_id": schema_pack_id,
                }
            ]
        },
        "compile_result": {
            "output": {
                "fields": [
                    {"entity_id": output.entity_id, **field.model_dump(mode="json")}
                    for field in output.fields
                ]
            }
        },
    }
