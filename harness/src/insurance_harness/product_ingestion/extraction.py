"""One durable field window, with injected I/O and independently validated facts.

The store owns reservations, lease fences, dependency-cache lookup and settlement.
Callbacks must commit before returning. Nothing in this module retries a provider,
opens a database, changes a release, or turns an unvalidated value into a fact.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import (
    batch_json_bytes_830_g3,
)
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    SourceBlock,
    verify_evidence,
)
from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (
    G3DCompileReferenceResponseV1,
    G3DFieldReferenceV1,
    _resolve_g3_d_evidence,
)
from insurance_harness.knowledge_compiler.g3_field_task_routing import (
    route_field_task_sources,
)
from insurance_harness.knowledge_compiler.g3_field_tasks import (
    FieldTaskEvidenceResultV1,
    FieldTaskV1,
)

LEGACY_REQUEST_CONTRACT = "product-field-window-request.v1"
REQUEST_CONTRACT = "product-field-window-request.v2"
RESPONSE_CONTRACT = "g3-d-compile-semantic-references.local.v1"
VALIDATION_VERSION = "product-field-outcome.v1"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

Transport = Callable[[bytes], Awaitable[bytes]]
BeginCall = Callable[[str, str, bytes], Awaitable[None]]
PersistRaw = Callable[[str, str, bytes | None, str | None], Awaitable[str]]
Outcome = Literal["verified", "not_provided", "extraction_failed"]
CallState = Literal["reserved", "dispatching", "recorded", "interrupted"]


@dataclass(frozen=True)
class FieldOutcome:
    task_sha256: str
    entity_id: str
    field_key: str
    outcome: Outcome
    reason: str
    validated_result: FieldTaskEvidenceResultV1 | None
    raw_ref: str | None

    def __post_init__(self) -> None:
        if self.outcome not in {"verified", "not_provided", "extraction_failed"}:
            raise ValueError("invalid field outcome")
        if not self.reason.strip():
            raise ValueError("field outcome reason is required")
        result = self.validated_result
        if self.outcome == "extraction_failed":
            if result is not None:
                raise ValueError("failed outcome cannot expose a value")
        elif (
            result is None
            or result.task_sha256 != self.task_sha256
            or hashlib.sha256(result.canonical_bytes()).hexdigest() != result.result_sha256
            or (self.outcome == "not_provided") != (result.state == "unknown")
            or not self.raw_ref
        ):
            raise ValueError("validated field outcome artifact mismatch")
        elif self.outcome == "verified" and (
            result.value is None
            or not result.value.strip()
            or not result.evidence
            or result.unknown_reason is not None
        ):
            raise ValueError("verified result requires value and evidence")
        elif self.outcome == "not_provided" and (
            result.value is not None
            or result.evidence
            or not result.unknown_reason
            or not result.unknown_reason.strip()
        ):
            raise ValueError("validated unknown must not expose a value")

    def to_dict(self) -> dict[str, object]:
        """The store port accepts JSON; no dependency on concurrent store DTOs."""
        return {
            "task_sha256": self.task_sha256,
            "entity_id": self.entity_id,
            "field_key": self.field_key,
            "outcome": self.outcome,
            "reason": self.reason,
            "validated_result": self.validated_result.model_dump(mode="json")
            if self.validated_result is not None
            else None,
            "raw_ref": self.raw_ref,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> FieldOutcome:
        raw = dict(value)
        if raw.get("validated_result") is not None:
            raw["validated_result"] = FieldTaskEvidenceResultV1.model_validate(
                raw["validated_result"]
            )
        return cls(**raw)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(raw: bytes) -> object:
    """Accept bare JSON or one complete JSON fence; keep strict JSON validation."""
    if type(raw) is not bytes or not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("invalid response bytes")
    semantic = raw.strip()
    if semantic.startswith(b"```"):
        lines = semantic.splitlines()
        if len(lines) < 3 or lines[0] != b"```json" or lines[-1] != b"```":
            raise ValueError("invalid response JSON fence")
        semantic = b"\n".join(lines[1:-1])

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    def invalid_constant(value):
        raise ValueError("non-JSON constant")

    return json.loads(semantic, object_pairs_hook=unique, parse_constant=invalid_constant)


def _source_index(
    tasks: Sequence[FieldTaskV1],
    sources: Sequence[SourceBlock],
    *,
    tenant_id: int,
    space_id: str,
    raw_kb_id: str,
) -> dict[str, SourceBlock]:
    if not tasks or len({(t.entity_id, t.field_key) for t in tasks}) != len(tasks):
        raise ValueError("field window must have unique tasks")
    # This boundary needs bounded, valid tasks, not a serialized batch envelope
    # whose hash would be immediately discarded (including all source refs).
    if len(tasks) > 10 or len({task.task_sha256 for task in tasks}) != len(tasks):
        raise ValueError("executor accepts one bounded field window")
    index: dict[str, SourceBlock] = {}
    keys = {}
    for original in sources:
        source = SourceBlock.model_validate(original)
        if (source.tenant_id, source.space_id, source.raw_kb_id) != (
            tenant_id,
            space_id,
            raw_kb_id,
        ):
            raise ValueError("source tenant/space/RAW scope mismatch")
        key = (source.revision_id, source.block_id)
        if key in keys:
            raise ValueError("duplicate source revision/block")
        keys[key] = source
        ref = "source_" + _sha(batch_json_bytes_830_g3(source.model_dump(exclude={"text"})))
        index[ref] = source
    for original in tasks:
        task = FieldTaskV1.model_validate(original)
        if not task.allowed_sources:
            raise ValueError("field task requires immutable source scope")
        for allowed in task.allowed_sources:
            source = keys.get((allowed.revision_id, allowed.block_id))
            if source is None or (source.source_hash, source.parser_identity) != (
                allowed.source_hash,
                allowed.parser_identity,
            ):
                raise ValueError("field task source dependency mismatch")
    return index


def _compact_field_target(task: FieldTaskV1, offered_refs, index) -> dict:
    """Keep full dependency scope local; expose only this call's usable refs."""
    allowed = {(source.revision_id, source.block_id) for source in task.allowed_sources}
    return {
        **task.model_dump(mode="json", exclude={"allowed_sources"}),
        "field_ref": task.task_sha256,
        "allowed_source_refs": sorted(
            ref
            for ref in set(offered_refs)
            if ref in index and (index[ref].revision_id, index[ref].block_id) in allowed
        ),
    }


def render_window_request(
    tasks: Sequence[FieldTaskV1],
    sources: Sequence[SourceBlock],
    *,
    tenant_id: int,
    space_id: str,
    raw_kb_id: str,
) -> bytes:
    """Render the exact bounded context; transport supplies its configured envelope."""
    index = _source_index(
        tasks, sources, tenant_id=tenant_id, space_id=space_id, raw_kb_id=raw_kb_id
    )
    offered = route_field_task_sources(tasks, index)
    offered_refs = tuple(row["source_ref"] for row in offered)
    targets = [_compact_field_target(task, offered_refs, index) for task in tasks]
    return batch_json_bytes_830_g3(
        {
            "contract": REQUEST_CONTRACT,
            "field_targets": targets,
            "source_options": offered,
            "response_schema": G3DCompileReferenceResponseV1.model_json_schema(),
            "instructions": [
                "Return only the requested field_refs; transformation EXTRACT, "
                "definitions/pages empty.",
                "Use direct statements about the requested field, "
                "not an inferred customer profile.",
                "present and absent_explicitly require nonempty values and direct evidence; "
                "absent_explicitly means an explicit exclusion, never missing text.",
                "When not stated, return unknown with null value, empty evidence and a specific "
                "unknown_reason. Never invent a value or quote.",
                "Quotes must be unchanged contiguous fragments within offered spans. Prefer short "
                "sufficient original single-line fragments; never join lines or add punctuation. "
                "Repeated exact fragments retain all offered locations. Return each source/quote "
                "pair once. Preserve original characters and line breaks.",
                "Use only the requested field's allowed_source_refs from source_options; "
                "the full local dependency scope is bound by its task_sha256.",
                "concept_refs may contain only the requested task's concept_ids.",
            ],
        }
    )


def _recorded_context(raw: bytes, tasks, pending, index):
    value = _json(raw)
    if (
        not isinstance(value, dict)
        or value.get("contract") not in {LEGACY_REQUEST_CONTRACT, REQUEST_CONTRACT}
        or not isinstance(value.get("field_targets"), list)
        or not isinstance(value.get("source_options"), list)
    ):
        raise ValueError("recorded request task scope mismatch")
    legacy = value["contract"] == LEGACY_REQUEST_CONTRACT
    offered_refs = tuple(
        row["source_ref"]
        for row in value["source_options"]
        if isinstance(row, dict) and isinstance(row.get("source_ref"), str)
    )
    task_index = {t.task_sha256: t for t in tasks}
    called = []
    for target in value["field_targets"]:
        ref = target.get("field_ref") if isinstance(target, dict) else None
        task = task_index.get(ref) if isinstance(ref, str) else None
        if (
            task is None
            or task in called
            or target
            != (
                {**task.model_dump(mode="json"), "field_ref": task.task_sha256}
                if legacy
                else _compact_field_target(task, offered_refs, index)
            )
        ):
            raise ValueError("recorded request task scope mismatch")
        called.append(task)
    if not {t.task_sha256 for t in pending}.issubset(t.task_sha256 for t in called):
        raise ValueError("recorded request omits pending task")
    allowed_keys = {
        (source.revision_id, source.block_id) for task in called for source in task.allowed_sources
    }
    seen = set()
    for offered in value["source_options"]:
        if not isinstance(offered, dict):
            raise ValueError("recorded source scope mismatch")
        ref = offered.get("source_ref")
        source = index.get(ref) if isinstance(ref, str) else None
        if (
            source is None
            or (not legacy and (source.revision_id, source.block_id) not in allowed_keys)
            or ref in seen
            or offered.get("source") != source.model_dump(mode="json", exclude={"text"})
            or not isinstance(offered.get("spans"), list)
        ):
            raise ValueError("recorded source scope mismatch")
        seen.add(ref)
        for span in offered["spans"]:
            if not isinstance(span, dict):
                raise ValueError("recorded source span mismatch")
            start, end = span.get("start"), span.get("end")
            if (
                type(start) is not int
                or type(end) is not int
                or start < 0
                or end <= start
                or end > len(source.text)
                or span.get("quote") != source.text[start:end]
            ):
                raise ValueError("recorded source span mismatch")
    return value, tuple(called)


def _failure(task, reason, raw_ref):
    return FieldOutcome(
        task.task_sha256,
        task.entity_id,
        task.field_key,
        "extraction_failed",
        reason,
        None,
        raw_ref,
    )


def _project(raw, tasks, index, context, raw_ref):
    try:
        value = _json(raw)
        if (
            not isinstance(value, dict)
            or set(value) != {"contract", "transformation", "definitions", "fields", "pages"}
            or value["contract"] != RESPONSE_CONTRACT
            or value["transformation"] != "EXTRACT"
            or value["definitions"] != []
            or value["pages"] != []
            or not isinstance(value["fields"], list)
        ):
            raise ValueError("invalid response envelope")
        grouped = {t.task_sha256: [] for t in tasks}
        for row in value["fields"]:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("field_ref"), str)
                or row["field_ref"] not in grouped
            ):
                raise ValueError("foreign field reference")
            grouped[row["field_ref"]].append(row)
    except (ValueError, TypeError, UnicodeError):
        return tuple(_failure(t, "INVALID_RESPONSE_ENVELOPE", raw_ref) for t in tasks)
    outcomes = []
    for task in tasks:
        rows = grouped[task.task_sha256]
        if len(rows) != 1:
            outcomes.append(_failure(task, "DUPLICATE_FIELD" if rows else "MISSING_FIELD", raw_ref))
            continue
        try:
            row = G3DFieldReferenceV1.model_validate(rows[0])
            if (row.value is not None and not row.value.strip()) or (
                row.unknown_reason is not None and not row.unknown_reason.strip()
            ):
                raise ValueError("blank field value/reason")
            if len(row.concept_refs) != len(set(row.concept_refs)) or not set(
                row.concept_refs
            ).issubset(task.concept_ids):
                raise ValueError("foreign concept reference")
            allowed_keys = {(s.revision_id, s.block_id) for s in task.allowed_sources}
            evidence = _resolve_g3_d_evidence(
                row.evidence,
                index,
                allowed={
                    ref for ref, s in index.items() if (s.revision_id, s.block_id) in allowed_keys
                },
                offered_sources=context["source_options"],
            )
            # Source blocks are mandatory here: .create() without them skips quote verification.
            result = FieldTaskEvidenceResultV1.create(
                task=task,
                state=row.state,
                value=row.value,
                evidence=evidence,
                unknown_reason=row.unknown_reason,
                concept_ids=row.concept_refs,
                conditions=row.conditions,
                exceptions=row.exceptions,
                valid_time=row.valid_time,
                source_blocks=tuple(index.values()),
            )
            outcome = "not_provided" if result.state == "unknown" else "verified"
            outcomes.append(
                FieldOutcome(
                    task.task_sha256,
                    task.entity_id,
                    task.field_key,
                    outcome,
                    result.unknown_reason or "VALIDATED",
                    result,
                    raw_ref,
                )
            )
        except (ValueError, TypeError):
            outcomes.append(_failure(task, "FIELD_VALIDATION_FAILED", raw_ref))
    return tuple(outcomes)


def _verified_cached_outcomes(tasks, cached, index):
    known = {}
    for task in tasks:
        key = (task.entity_id, task.field_key)
        hit = (cached or {}).get(key)
        if hit is None:
            continue
        hit = FieldOutcome.from_dict(hit) if isinstance(hit, Mapping) else hit
        if (hit.entity_id, hit.field_key) != key or hit.outcome == "extraction_failed":
            raise ValueError("invalid success cache result")
        for evidence in hit.validated_result.evidence:
            verify_evidence(evidence, tuple(index.values()))
        known[key] = hit
    return known


async def execute_window(
    *,
    call_id: str,
    tasks: Sequence[FieldTaskV1],
    sources: Sequence[SourceBlock],
    tenant_id: int,
    space_id: str,
    raw_kb_id: str,
    transport: Transport,
    begin_call: BeginCall,
    persist_raw: PersistRaw,
    cached: Mapping[tuple[str, str], FieldOutcome | Mapping[str, object]] | None = None,
    call_state: CallState = "reserved",
    recorded_request_bytes: bytes | None = None,
    recorded_raw: bytes | None = None,
    recorded_raw_ref: str | None = None,
    decode_response: Callable[[bytes], bytes] | None = None,
) -> tuple[FieldOutcome, ...]:
    """Execute/replay once. Store callbacks bind scope, job ID and active generation.

    A cache hit is supplied by the scoped store's source/Schema dependency query.
    Its original task/model/prompt/validator provenance is preserved, not re-keyed.
    Recorded request/raw bytes must come from the same fenced call audit row.
    """
    if not call_id or call_state not in {
        "reserved",
        "dispatching",
        "recorded",
        "interrupted",
    }:
        raise ValueError("invalid call identity/state")
    tasks = tuple(tasks)
    index = await asyncio.to_thread(
        _source_index, tasks, sources, tenant_id=tenant_id, space_id=space_id, raw_kb_id=raw_kb_id
    )
    known = await asyncio.to_thread(_verified_cached_outcomes, tasks, cached, index)
    pending = tuple(t for t in tasks if (t.entity_id, t.field_key) not in known)
    if not pending:
        return tuple(known[t.entity_id, t.field_key] for t in tasks)
    if call_state in {"dispatching", "interrupted"}:
        outcomes = tuple(_failure(t, "CALL_INTERRUPTED", recorded_raw_ref) for t in pending)
    else:
        projection_tasks = pending
        if call_state == "recorded":
            if recorded_request_bytes is None or not recorded_raw_ref:
                raise ValueError("recorded call requires original request and raw reference")
            context, projection_tasks = await asyncio.to_thread(
                _recorded_context, recorded_request_bytes, tasks, pending, index
            )
            raw, raw_ref = recorded_raw, recorded_raw_ref
        else:
            request = await asyncio.to_thread(
                render_window_request,
                pending,
                tuple(index.values()),
                tenant_id=tenant_id,
                space_id=space_id,
                raw_kb_id=raw_kb_id,
            )
            context = _json(request)
            request_hash = _sha(request)
            await begin_call(call_id, request_hash, request)
            diagnostic = None
            try:
                raw = await transport(request)
                if type(raw) is not bytes:
                    raise TypeError("transport must return raw bytes")
            except Exception as error:
                raw = None
                diagnostic = "transport:" + type(error).__name__
            # Outside transport catch: failed persistence must not be mistaken for provider failure.
            raw_ref = await persist_raw(call_id, request_hash, raw, diagnostic)
            if not isinstance(raw_ref, str) or not raw_ref:
                raise ValueError("raw persistence returned no audit reference")
        if raw is None:
            outcomes = tuple(_failure(t, "TRANSPORT_ERROR", raw_ref) for t in pending)
        else:
            try:
                semantic = (
                    await asyncio.to_thread(decode_response, raw)
                    if decode_response is not None
                    else raw
                )
            except Exception:
                outcomes = tuple(_failure(t, "RESPONSE_DECODE_FAILED", raw_ref) for t in pending)
            else:
                outcomes = await asyncio.to_thread(
                    _project, semantic, projection_tasks, index, context, raw_ref
                )
    known.update(
        {(o.entity_id, o.field_key): o for o in outcomes if (o.entity_id, o.field_key) not in known}
    )
    return tuple(known[t.entity_id, t.field_key] for t in tasks)
