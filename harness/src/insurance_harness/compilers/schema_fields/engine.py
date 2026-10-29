"""Field compilation orchestration for the two-step pointer protocol (S4d Spec §3).

Ported from V5 llm_plugin.py / ingest.py; legacy originals retire in S7. Step one asks
each batch of fields for segment ids; step two asks for values from only the selected
segments. Evidence is cut from page text by SegmentedSource, never copied by the model.
The caller owns transport and retries; this engine invokes the completion port once
per request, within a per-compile budget that covers both steps. The port must reject
interrupted/truncated completions before returning text.
"""

from collections.abc import Mapping, Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from insurance_harness.catalog.trust_policy import TrustPolicy, load_trust_policy
from insurance_harness.compilers.schema_fields.cards import cards_version
from insurance_harness.compilers.schema_fields.carry import CarriedQuote
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition, NonBlank
from insurance_harness.compilers.schema_fields.parse import CompileError as CompileError
from insurance_harness.compilers.schema_fields.parse import parse_selection, parse_value_rows
from insurance_harness.compilers.schema_fields.prompt import (
    VALUE_PROTOCOL_VERSION,
    JudgeLikeRequest,
    build_selection_request,
    build_value_request,
)
from insurance_harness.compilers.schema_fields.values import normalize_field_value
from insurance_harness.evidence.quote_verification import PageTextLike, VerifiedQuote
from insurance_harness.evidence.segments import Segment, SegmentedSource


class CompletionPort(Protocol):
    @property
    def model(self) -> str: ...

    def complete(self, *, system: str, user: str) -> str: ...


class CompileBudgetExceeded(CompileError):
    """No further completion can be sent within this compile's call budget."""


# Step-one draws the production compile takes per batch. S12c-6 sent the same request twice so a
# field present in the first draw also received the segments a later draw added; under production
# conditions (with S12c-4 carry) that showed no gain while doubling step one, so production is back
# to one draw (S12c-6b Spec §4). The engine still takes more draws when asked.
SELECTION_DRAWS = 1


class FieldResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    field_key: NonBlank
    state: Literal["present", "absent_explicitly", "unknown"]
    value: str | None = None
    evidence: list[VerifiedQuote] = Field(default_factory=list)
    # Step-one selection in reading order (S4f); outputs written before S4f load as [].
    segment_ids: list[str] = Field(default_factory=list)
    # Reviewed segments carried into this recompile that step two used (S12c-4 §2.3); evidence
    # is cut from segment_ids plus these. Never overlaps segment_ids; [] before S12c-4.
    carried_segment_ids: list[str] = Field(default_factory=list)
    # Segments a later step-one draw added that step two used (S12c-6 §4); evidence is cut from
    # segment_ids, carried_segment_ids and these. Overlaps neither; [] before S12c-6.
    recalled_segment_ids: list[str] = Field(default_factory=list)


class CompileOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    pack_id: str
    entity_id: NonBlank
    model: NonBlank
    fields: list[FieldResult] = Field(default_factory=list)
    calls: int = Field(default=0, ge=0)
    # Refs that named no segment, and fields lost because no valid segment or no value remained.
    dropped_refs: int = Field(default=0, ge=0)
    dropped_fields: list[str] = Field(default_factory=list)
    # The field card version the requests were built from (S4g); None in outputs written earlier.
    cards_version: str | None = None
    # Actual input document identities; earlier outputs cannot be reused without them (S8a).
    materials: list[str] | None = None
    # The step-two protocol the values were written under (S12c-1); None before S12c-1.
    value_protocol: str | None = None
    # Each `materials` identity's effective role (S5b-6); None in outputs written earlier.
    material_roles: dict[str, str] | None = None
    # The Active release reviewed quotes were carried from, and their identity (S12c-4 §2.4);
    # None when nothing was carried, and in outputs written before S12c-4.
    carry_release: str | None = None
    carry_digest: str | None = None


def reusable(
    output: CompileOutput, materials: list[str], roles: Mapping[str, str] | None = None
) -> bool:
    """An output may stand in for a compile only if its materials, their effective roles (S5b-6),
    the cards and the value protocol all match. Roles are part of the identity: an output written
    without them matches only a caller that has none either, so role-aware callers recompile it."""
    return (
        output.materials is not None
        and output.materials == materials
        and output.material_roles == (dict(roles) if roles is not None else None)
        and output.cards_version == cards_version()
        and output.value_protocol == VALUE_PROTOCOL_VERSION
    )


def _forbidden(
    source: SegmentedSource, policy: TrustPolicy, ids: Sequence[str], field_key: str,
) -> set[str]:
    """Header segments the field may not use: a restricted header serves only its fields."""
    return {
        segment.id for segment in source.ordered(ids)
        if (role := source.header_role(segment.document)) is not None
        and field_key not in policy.header_fields(role)
    }


def _value_batches(
    items: list[tuple[FieldDefinition, list[Segment]]],
    limit: int,
) -> list[list[tuple[FieldDefinition, list[Segment]]]]:
    """Consecutive fields while their selected text fits; an oversized field goes alone."""
    batches: list[list[tuple[FieldDefinition, list[Segment]]]] = []
    size = 0
    for item in items:
        chars = sum(len(segment.text) for segment in item[1])
        if batches and batches[-1] and size + chars <= limit:
            batches[-1].append(item)
            size += chars
        else:
            batches.append([item])
            size = chars
    return batches


class SchemaFieldsCompiler:
    def __init__(
        self,
        completion: CompletionPort,
        *,
        batch_size: int = 25,
        max_calls: int = 10,
        value_batch_chars: int = 60000,
        selection_draws: int = 1,
    ):
        if type(batch_size) is not int or batch_size < 1:
            raise CompileError("batch_size must be a positive integer")
        if type(max_calls) is not int or max_calls < 0:
            raise CompileError("max_calls must be a nonnegative integer")
        if type(value_batch_chars) is not int or value_batch_chars < 1:
            raise CompileError("value_batch_chars must be a positive integer")
        if type(selection_draws) is not int or selection_draws < 1:
            raise CompileError("selection_draws must be a positive integer")
        if not isinstance(completion.model, str) or not completion.model.strip():
            raise CompileError("completion must declare its model")
        self._completion = completion
        self._batch_size = batch_size
        self._max_calls = max_calls
        self._value_batch_chars = value_batch_chars
        self._selection_draws = selection_draws

    def _prepare(
        self,
        entity_id: str,
        definitions: Sequence[FieldDefinition],
        pages: Sequence[PageTextLike],
        *,
        table_headers: Mapping[str, Sequence[PageTextLike]] | None = None,
    ) -> tuple[tuple[FieldDefinition, ...], SegmentedSource]:
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
            source = SegmentedSource(pages, table_headers=table_headers)
        except ValueError as exc:
            raise CompileError("invalid or ambiguous source pages") from exc
        if fields and not source.segments:
            raise CompileError("source text is required")
        return fields, source

    def _batches(self, fields: tuple[FieldDefinition, ...]) -> list[tuple[FieldDefinition, ...]]:
        return [
            fields[offset : offset + self._batch_size]
            for offset in range(0, len(fields), self._batch_size)
        ]

    def build_requests(
        self,
        entity_id: str,
        definitions: Sequence[FieldDefinition],
        pages: Sequence[PageTextLike],
        *,
        table_headers: Mapping[str, Sequence[PageTextLike]] | None = None,
    ) -> list[JudgeLikeRequest]:
        """Step-one requests; step two depends on the answers and is built during compile."""
        fields, source = self._prepare(entity_id, definitions, pages, table_headers=table_headers)
        listing = source.listing()
        return [
            build_selection_request(entity_id, batch, listing) for batch in self._batches(fields)
        ]

    def compile(
        self,
        entity_id: str,
        definitions: Sequence[FieldDefinition],
        pages: Sequence[PageTextLike],
        *,
        table_headers: Mapping[str, Sequence[PageTextLike]] | None = None,
        carry: Mapping[str, Sequence[CarriedQuote]] | None = None,
        roles: Mapping[str, str | None] | None = None,
    ) -> CompileOutput:
        """carry: reviewed quotes per field a recompile hands to step two (S12c-4 Spec §2.2).
        roles: each document's material role, shown to step two by segment-id prefix (S12c-7)."""
        fields, source = self._prepare(entity_id, definitions, pages, table_headers=table_headers)
        documents = {
            source.document_ids[document]: role
            for document, role in (roles or {}).items()
            if role is not None and document in source.document_ids
        }
        policy = load_trust_policy()
        calls = 0

        def send(request: JudgeLikeRequest) -> str:
            nonlocal calls
            if calls >= self._max_calls:
                raise CompileBudgetExceeded(f"compile call budget exhausted after {calls} calls")
            calls += 1
            return self._completion.complete(system=request.system, user=request.user)

        listing = source.listing()
        selected: dict[str, tuple[str, list[str]]] = {}
        later: dict[str, set[str]] = {}
        dropped_refs = 0
        dropped_fields: list[str] = []
        for batch in self._batches(fields):
            request = build_selection_request(entity_id, batch, listing)
            for draw in range(self._selection_draws):
                for row in parse_selection(send(request), batch):
                    ids, dropped = source.resolve(row.segments)
                    forbidden = _forbidden(source, policy, ids, row.field_key)
                    ids = [sid for sid in ids if sid not in forbidden]
                    if draw:
                        # A later draw only adds segments to a field it also finds present; the
                        # first draw's states and selection stand (S12c-6 Spec §4.2).
                        if row.state == "present":
                            later.setdefault(row.field_key, set()).update(ids)
                        continue
                    dropped_refs += len(dropped) + len(forbidden)
                    if row.state != "unknown" and not ids:
                        dropped_fields.append(row.field_key)
                        continue
                    selected[row.field_key] = (row.state, ids)

        # Only a field step one found present takes carried quotes: step one's unknown or
        # absent stands. A quote that is not found exactly once on its page carries nothing.
        carried: dict[str, list[str]] = {}
        for key, quotes in (carry or {}).items():
            state, ids = selected.get(key, ("", []))
            if state != "present":
                continue
            located = set().union(*(source.locate(q.document, q.page, q.quote) for q in quotes))
            added = located - set(ids) - _forbidden(source, policy, list(located), key)
            if added:
                carried[key] = [segment.id for segment in source.ordered(list(added))]
        recalled: dict[str, list[str]] = {}
        for key, found in later.items():
            state, ids = selected.get(key, ("", []))
            added = found - set(ids) - set(carried.get(key, []))
            if state == "present" and added:
                recalled[key] = [segment.id for segment in source.ordered(list(added))]
        present = [
            (d, source.ordered([*selected[d.field_key][1], *carried.get(d.field_key, []),
                                *recalled.get(d.field_key, [])]))
            for d in fields
            if selected.get(d.field_key, ("", []))[0] == "present"
        ]
        values: dict[str, str | None] = {}
        used: dict[str, list[str]] = {}
        for items in _value_batches(present, self._value_batch_chars):
            answer = send(build_value_request(entity_id, items, documents))
            rows = parse_value_rows(answer, [definition for definition, _ in items])
            for key, (written, cited) in rows.items():
                values[key], used[key] = written, cited

        results: list[FieldResult] = []
        for definition in fields:
            if definition.field_key not in selected:
                continue
            state, ids = selected[definition.field_key]
            if state == "unknown":
                results.append(FieldResult(field_key=definition.field_key, state="unknown"))
                continue
            value = None
            if state == "present":
                if definition.field_key not in values:
                    dropped_fields.append(definition.field_key)
                    continue
                written = values[definition.field_key]
                if written is None:
                    # Step two found none of the field in its segments: the same result as a
                    # step-one unknown, with no value and no evidence (S12c-1 §3).
                    results.append(FieldResult(field_key=definition.field_key, state="unknown"))
                    continue
                value = normalize_field_value(definition, written)
            cited = used.get(definition.field_key, [])
            offered = [*carried.get(definition.field_key, []),
                       *recalled.get(definition.field_key, [])]
            extra = _used_carried(source, ids, offered, cited)
            kept_carried = [sid for sid in carried.get(definition.field_key, []) if sid in extra]
            kept_recalled = [sid for sid in recalled.get(definition.field_key, []) if sid in extra]
            results.append(
                FieldResult(
                    field_key=definition.field_key,
                    state=state,  # type: ignore[arg-type]
                    value=value,
                    evidence=source.evidence([*ids, *extra]),
                    segment_ids=[segment.id for segment in source.ordered(ids)],
                    carried_segment_ids=kept_carried,
                    recalled_segment_ids=kept_recalled,
                )
            )
        return CompileOutput(
            pack_id=fields[0].pack_id if fields else "",
            entity_id=entity_id,
            model=self._completion.model,
            fields=results,
            calls=calls,
            dropped_refs=dropped_refs,
            dropped_fields=dropped_fields,
            cards_version=cards_version(),
            value_protocol=VALUE_PROTOCOL_VERSION,
        )


def _used_carried(
    source: SegmentedSource, selected: Sequence[str], carried: list[str], cited: Sequence[str],
) -> list[str]:
    """The carried segments that become evidence (S12c-4 Spec §2.3): those step two cited, or all
    of them when it cited no segment it was given; the step-one selection is never shrunk."""
    if not carried:
        return []
    offered = {*selected, *carried}
    named, _ = source.resolve(list(cited))
    named = [sid for sid in named if sid in offered]
    return carried if not named else [sid for sid in carried if sid in named]


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
