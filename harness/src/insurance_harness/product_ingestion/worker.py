"""Platform job handlers: durable call audit and one atomic P1 completion."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence

from insurance_harness.jobs import JobSnapshot
from insurance_harness.jobs.errors import SpaceScopeError
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import SourceBlock
from insurance_harness.knowledge_compiler.g3_field_tasks import FieldTaskV1
from insurance_harness.product_ingestion.extraction import Transport, execute_window
from insurance_harness.product_ingestion.model_execution import (
    ConfiguredFieldTransport,
    PreparedModelRequest,
)
from insurance_harness.product_ingestion.models import (
    FieldOutcomeWrite,
    ProductScope,
    WindowReservationAction,
)
from insurance_harness.product_ingestion.store import ProductIngestionStore
from insurance_harness.service_shell.worker import HandlerRegistry, HandlerResult

SourceLoader = Callable[[ProductScope, str], Awaitable[Sequence[SourceBlock]]]
FieldTransportFactory = Callable[[ProductScope, str, JobSnapshot], ConfiguredFieldTransport]


def provider_usage(raw: bytes | None) -> dict[str, int]:
    """Read only usage actually reported in the persisted provider response.

    An absent/malformed usage object remains unavailable, rather than an estimate.
    Nested token details are retained in the original response artifact.
    """
    if raw is None:
        return {}
    try:
        usage = json.loads(raw).get("usage")
    except (ValueError, AttributeError, UnicodeError):
        return {}
    if not isinstance(usage, dict):
        return {}
    return {
        key: value
        for key, value in usage.items()
        if key
        in {"input_tokens", "output_tokens", "prompt_tokens", "completion_tokens", "total_tokens"}
        and type(value) is int
        and value >= 0
    }


def _restore_field_tasks(selected):
    field_tasks = tuple(FieldTaskV1.model_validate(task.task_payload) for task in selected)
    for spec, task in zip(selected, field_tasks, strict=True):
        if (spec.entity_id, spec.field_key, spec.task_sha256) != (
            task.entity_id,
            task.field_key,
            task.task_sha256,
        ):
            raise ValueError("persisted task identity mismatch")
    return field_tasks


def register_extraction_worker(
    registry: HandlerRegistry,
    *,
    store: ProductIngestionStore,
    scopes: Mapping[str, ProductScope],
    load_sources: SourceLoader,
    transport: Transport | None = None,
    transport_factory: FieldTransportFactory | None = None,
    decode_response: Callable[[bytes], bytes] | None = None,
) -> None:
    """Install the field worker using configured platform ports, never browser values.

    load_sources reads immutable platform checkpoints. It must not trigger parsing
    or rebuild a source from a model response. The transport performs a single
    configured provider request and supplies the original response bytes.
    """

    if (transport is None) == (transport_factory is None):
        raise ValueError("configure exactly one extraction transport port")
    if transport_factory is not None and decode_response is not None:
        raise ValueError("configured field transport owns response decoding")

    async def handle(job: JobSnapshot) -> HandlerResult:
        scope = scopes.get(job.space_id)
        if scope is None:
            raise SpaceScopeError()
        run_id = job.payload["run_id"]
        window = await asyncio.to_thread(
            store.get_window_for_job,
            scope=scope,
            run_id=run_id,
            job_id=job.id,
        )
        reservation = await asyncio.to_thread(
            store.reserve_window,
            scope=scope,
            run_id=run_id,
            job_id=job.id,
            generation=job.lease_generation,
            attempt=job.attempt,
            call_id=str(uuid.uuid4()),
            window_key=window.window_key,
            tasks=window.tasks,
        )
        outcomes = reservation.outcomes
        raw_for_usage = reservation.call.raw if reservation.call else None
        if reservation.action in {
            WindowReservationAction.DISPATCH,
            WindowReservationAction.RECORDED,
        }:
            call = reservation.call
            assert call is not None
            # Persisted selection is authoritative on replay even if another task
            # has populated the success cache since the original request.
            keys = set(call.selected_field_keys)
            selected = tuple(
                task for task in window.tasks if (task.entity_id, task.field_key) in keys
            )
            field_tasks = await asyncio.to_thread(_restore_field_tasks, selected)
            configured = (
                transport_factory(scope, run_id, job) if transport_factory is not None else None
            )
            if configured is not None and any(
                spec.model_policy_sha256 != configured.model_policy_sha256 for spec in selected
            ):
                raise ValueError("field task model policy is not current")
            sources = await load_sources(scope, run_id)
            prepared: PreparedModelRequest | None = None
            exact_request_sha256: str | None = None

            async def begin(call_id, request_sha256, request_bytes):
                nonlocal prepared, exact_request_sha256
                if configured is not None:
                    prepared = await asyncio.to_thread(configured.prepare, request_bytes)
                    request_bytes = prepared.request_bytes
                    request_sha256 = prepared.request_sha256
                    exact_request_sha256 = request_sha256
                await asyncio.to_thread(
                    store.begin_call,
                    scope=scope,
                    call_id=call_id,
                    job_id=job.id,
                    generation=job.lease_generation,
                    request_sha256=request_sha256,
                    request_bytes=request_bytes,
                )

            async def persist(call_id, request_sha256, raw, diagnostic):
                nonlocal raw_for_usage
                if configured is not None:
                    if exact_request_sha256 is None:
                        raise ValueError("configured model request was not durably begun")
                    request_sha256 = exact_request_sha256
                record = await asyncio.to_thread(
                    store.record_call_result,
                    scope=scope,
                    call_id=call_id,
                    job_id=job.id,
                    generation=job.lease_generation,
                    request_sha256=request_sha256,
                    raw=raw,
                    diagnostic=diagnostic,
                )
                raw_for_usage = record.raw
                return record.raw_ref

            async def configured_send(request_bytes: bytes) -> bytes:
                if configured is None or prepared is None:
                    raise ValueError("configured model request is not prepared")
                if request_bytes != prepared.semantic_request:
                    raise ValueError("configured model semantic request changed")
                return await configured.send(prepared)

            recorded_request_bytes = call.request_bytes
            if configured is not None and reservation.action is WindowReservationAction.RECORDED:
                if recorded_request_bytes is None:
                    raise ValueError("recorded field call has no endpoint request")
                recorded_request_bytes = await asyncio.to_thread(
                    configured.semantic_request, recorded_request_bytes
                )

            projected = await execute_window(
                call_id=call.call_id,
                tasks=field_tasks,
                sources=sources,
                tenant_id=int(scope.tenant_id),
                space_id=scope.space_id,
                raw_kb_id=scope.raw_knowledge_base_id,
                transport=configured_send if configured is not None else transport,
                begin_call=begin,
                persist_raw=persist,
                call_state=(
                    "recorded"
                    if reservation.action is WindowReservationAction.RECORDED
                    else "reserved"
                ),
                recorded_request_bytes=recorded_request_bytes,
                recorded_raw=call.raw,
                recorded_raw_ref=call.raw_ref,
                decode_response=(
                    configured.decode_response if configured is not None else decode_response
                ),
            )
            by_key = {(spec.entity_id, spec.field_key): spec for spec in selected}
            outcomes = tuple(
                FieldOutcomeWrite(
                    **outcome.to_dict(),
                    cache_identity=by_key[outcome.entity_id, outcome.field_key].cache_identity,
                )
                for outcome in projected
            )
        result, _counts = await asyncio.to_thread(
            store.prepare_window_settlement,
            scope=scope,
            run_id=run_id,
            job_id=job.id,
            generation=job.lease_generation,
            outcomes=outcomes,
            usage=provider_usage(raw_for_usage),
        )
        # WorkerLoop alone commits the field attempts and completion event with
        # the P1 terminal transition. No double completion from this handler.
        return result

    registry.register("product_extraction_window", handle)
