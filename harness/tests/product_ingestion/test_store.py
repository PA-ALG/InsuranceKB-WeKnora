"""G3-AUTO durable product-ingestion store contract.

This is the RED contract for Task 1.  It deliberately loads the not-yet-created
package from a fixture so pytest reports a focused assertion failure instead of a
collection error while the implementation review is still pending.
"""

from __future__ import annotations

import hashlib
import importlib
import typing
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from insurance_harness.db.base import Base, make_engine, make_session_factory
from insurance_harness.jobs import (
    ClaimedJob,
    ErrorClass,
    JobFailure,
    JobRuntimeConfig,
    JobStore,
    SpaceScopeError,
    StaleGenerationError,
)
from insurance_harness.jobs.tables import WikiJob, WikiOutboxEvent
from insurance_harness.service_shell.config import ShellSettings
from insurance_harness.service_shell.health import Lifecycle
from insurance_harness.service_shell.worker import HandlerRegistry, HandlerResult, WorkerLoop

SessionFactory = Callable[[], Session]
REQUEST_BYTES = b'{"request":"exact"}'
REQUEST_SHA256 = hashlib.sha256(REQUEST_BYTES).hexdigest()


@pytest.fixture(scope="module")
def api() -> SimpleNamespace:
    """Load the intended public contract without turning RED into import noise."""
    try:
        models = importlib.import_module("insurance_harness.product_ingestion.models")
        importlib.import_module("insurance_harness.product_ingestion.tables")
        store = importlib.import_module("insurance_harness.product_ingestion.store")
    except ModuleNotFoundError as error:
        pytest.fail(f"RED: durable product-ingestion store is not implemented: {error}")

    names = (
        "CallState",
        "FieldCacheIdentity",
        "FieldOutcomeKind",
        "FieldOutcomeWrite",
        "OriginalKnowledgeRef",
        "ProductRunState",
        "ProductScope",
        "SealedSourceRef",
        "WindowReservationAction",
        "WindowTaskSpec",
    )
    missing = [name for name in names if not hasattr(models, name)]
    if not hasattr(store, "ProductIngestionStore"):
        missing.append("ProductIngestionStore")
    assert not missing, f"RED: product-ingestion public contract missing {missing}"
    return SimpleNamespace(
        **{name: getattr(models, name) for name in names},
        ProductIngestionStore=store.ProductIngestionStore,
    )


@pytest.fixture
def factory(tmp_path: Path, api: SimpleNamespace) -> Iterator[SessionFactory]:
    del api  # importing tables above registers their metadata with the shared Base
    engine = make_engine(f"sqlite:///{tmp_path}/product-ingestion.db")
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    yield session_factory
    engine.dispose()


def _job_store(factory: SessionFactory) -> JobStore:
    return JobStore(
        factory,
        JobRuntimeConfig(
            lease_seconds=300,
            heartbeat_interval_seconds=30,
            max_attempts=3,
            backoff_seconds=(0,),
            per_space_concurrency_limit=16,
            global_concurrency_limit=32,
        ),
    )


def _scope(api: SimpleNamespace, space_id: str = "space-a") -> Any:
    return api.ProductScope(
        tenant_id="tenant-a",
        space_id=space_id,
        raw_knowledge_base_id="raw-a",
        wiki_knowledge_base_id="wiki-a",
    )


def _source(api: SimpleNamespace, knowledge_id: str, ordinal: int = 0) -> Any:
    return api.SealedSourceRef(
        knowledge_id=knowledge_id,
        source_revision_id=f"revision-{ordinal}",
        source_sha256=f"{'a' * 63}{ordinal}",
        file_sha256=f"{'b' * 63}{ordinal}",
        native_manifest_sha256=f"{'c' * 63}{ordinal}",
        page_count=ordinal + 1,
        inferred_material_role="terms",
        product_identity_sha256="d" * 64,
    )


def _identity(api: SimpleNamespace, *, source_sha: str = "1" * 64, task_sha: str = "2" * 64) -> Any:
    return api.FieldCacheIdentity(
        product_identity_sha256="0" * 64,
        entity_id="entity-1820",
        field_key="alpha",
        source_dependencies=(
            {
                "source_revision_id": "revision-1",
                "source_sha256": source_sha,
            },
        ),
        schema_adapter_id="catalog-1820",
        schema_adapter_sha256="3" * 64,
        schema_version="catalog-2026-09",
    )


def _task(api: Any, field_key: str, *, source_sha: str = "1" * 64) -> Any:
    identity = api.FieldCacheIdentity(
        **{
            **_identity(api, source_sha=source_sha).model_dump(exclude={"field_key"}),
            "field_key": field_key,
        }
    )
    return api.WindowTaskSpec(
        entity_id="entity-1820",
        field_key=field_key,
        task_sha256=field_key[0] * 64,
        cache_identity=identity,
        validation_version="g3-field-validation.v1",
        model_policy_sha256="4" * 64,
        prompt_policy_sha256="5" * 64,
        task_payload={"field_key": field_key},
    )


def _make_store(api: SimpleNamespace, factory: SessionFactory) -> Any:
    jobs = _job_store(factory)
    return api.ProductIngestionStore(factory, jobs), jobs


def _run_with_uploads(
    api: SimpleNamespace,
    store: Any,
    *,
    count: int = 1,
    idempotency_key: str = "browser-upload-1",
) -> tuple[Any, list[str]]:
    scope = _scope(api)
    run = store.create_run(
        scope=scope,
        idempotency_key=idempotency_key,
        expected_upload_count=count,
    )
    material_ids: list[str] = []
    for ordinal in range(count):
        run = store.attach_original(
            scope=scope,
            run_id=run.run_id,
            expected_version=run.version,
            original=api.OriginalKnowledgeRef(
                knowledge_id=f"knowledge-{ordinal}",
                original_filename=f"original-{ordinal}.pdf",
                upload_ordinal=ordinal,
            ),
        )
        material_ids.append(run.materials[-1].material_id)
    run = store.seal_uploads(
        scope=scope,
        run_id=run.run_id,
        expected_version=run.version,
    )
    for ordinal, material_id in enumerate(material_ids):
        run = store.seal_material_source(
            scope=scope,
            run_id=run.run_id,
            material_id=material_id,
            source=_source(api, f"knowledge-{ordinal}", ordinal),
        )
    return run, material_ids


def _start_window(
    api: SimpleNamespace,
    store: Any,
    jobs: JobStore,
    *,
    run_id: str,
    window_key: str,
    tasks: tuple[Any, ...],
) -> tuple[Any, Any]:
    window = store.enqueue_window(
        scope=_scope(api),
        run_id=run_id,
        stage_key="extract",
        window_key=window_key,
        dependency_sha256="9" * 64,
        tasks=tasks,
    )
    claimed = jobs.claim(space_ids=("space-a",), worker_id=f"worker-{window_key}")
    assert isinstance(claimed, ClaimedJob)
    assert claimed.job.id == window.job_id
    running = jobs.start(
        space_id="space-a",
        job_id=claimed.job.id,
        generation=claimed.job.lease_generation,
    )
    return window, running


def _reserve_and_record(
    api: SimpleNamespace,
    store: Any,
    running: Any,
    *,
    run_id: str,
    window_key: str,
    tasks: tuple[Any, ...],
    raw: bytes,
) -> Any:
    reservation = store.reserve_window(
        scope=_scope(api),
        run_id=run_id,
        job_id=running.id,
        generation=running.lease_generation,
        attempt=running.attempt,
        call_id=f"call-{window_key}",
        window_key=window_key,
        request_sha256=REQUEST_SHA256,
        tasks=tasks,
    )
    assert reservation.action is api.WindowReservationAction.DISPATCH
    store.begin_call(
        scope=_scope(api),
        call_id=reservation.call.call_id,
        job_id=running.id,
        generation=running.lease_generation,
        request_sha256=REQUEST_SHA256,
        request_bytes=REQUEST_BYTES,
    )
    return store.record_call_result(
        scope=_scope(api),
        call_id=reservation.call.call_id,
        job_id=running.id,
        generation=running.lease_generation,
        request_sha256=REQUEST_SHA256,
        raw=raw,
        diagnostic=None,
    )


def _verified(api: SimpleNamespace, task: Any, *, raw_ref: str) -> Any:
    return api.FieldOutcomeWrite(
        field_key=task.field_key,
        task_sha256=task.task_sha256,
        cache_identity=task.cache_identity,
        outcome=api.FieldOutcomeKind.VERIFIED,
        reason=None,
        validated_result={
            "field_ref": task.field_key,
            "value_state": "present",
            "value": "covered",
            "evidence": [{"quote": "covered", "start": 0, "end": 7}],
        },
        raw_ref=raw_ref,
    )


def _failed(api: SimpleNamespace, task: Any, *, raw_ref: str, reason: str) -> Any:
    return api.FieldOutcomeWrite(
        field_key=task.field_key,
        task_sha256=task.task_sha256,
        cache_identity=task.cache_identity,
        outcome=api.FieldOutcomeKind.EXTRACTION_FAILED,
        reason=reason,
        validated_result=None,
        raw_ref=raw_ref,
    )


def test_restart_retains_unbounded_originals_sources_raw_and_validated_result(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    store, jobs = _make_store(api, factory)
    run, material_ids = _run_with_uploads(api, store, count=4)
    task = _task(api, "benefit")
    window, running = _start_window(
        api, store, jobs, run_id=run.run_id, window_key="window-1", tasks=(task,)
    )
    call = _reserve_and_record(
        api,
        store,
        running,
        run_id=run.run_id,
        window_key="window-1",
        tasks=(task,),
        raw=b'{"wire":"exact"}\n',
    )
    settled = store.settle_window(
        scope=_scope(api),
        run_id=run.run_id,
        job_id=running.id,
        generation=running.lease_generation,
        outcomes=(_verified(api, task, raw_ref=call.raw_ref),),
    )
    assert settled.success_count == 1

    restarted = api.ProductIngestionStore(factory, _job_store(factory))
    loaded = restarted.get_run(scope=_scope(api), run_id=run.run_id)
    assert len(loaded.materials) == 4
    assert [material.material_id for material in loaded.materials] == material_ids
    assert all(material.source is not None for material in loaded.materials)
    loaded_call = restarted.get_call(scope=_scope(api), call_id=call.call_id)
    assert loaded_call.raw == b'{"wire":"exact"}\n'
    assert loaded_call.raw_sha256 is not None
    outcomes = restarted.list_field_attempts(scope=_scope(api), run_id=run.run_id)
    assert outcomes[0].validated_result["value"] == "covered"
    assert outcomes[0].raw_ref == call.raw_ref
    assert (
        restarted.get_window_for_job(scope=_scope(api), run_id=run.run_id, job_id=running.id)
        == window
    )


def test_completed_window_is_atomic_and_survives_later_window_failure(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    store, jobs = _make_store(api, factory)
    run, _ = _run_with_uploads(api, store)
    first = _task(api, "alpha")
    second = _task(api, "beta")

    _window1, running1 = _start_window(
        api, store, jobs, run_id=run.run_id, window_key="one", tasks=(first,)
    )
    call1 = _reserve_and_record(
        api,
        store,
        running1,
        run_id=run.run_id,
        window_key="one",
        tasks=(first,),
        raw=b'{"alpha":"ok"}',
    )
    store.settle_window(
        scope=_scope(api),
        run_id=run.run_id,
        job_id=running1.id,
        generation=running1.lease_generation,
        outcomes=(_verified(api, first, raw_ref=call1.raw_ref),),
    )

    _window2, running2 = _start_window(
        api, store, jobs, run_id=run.run_id, window_key="two", tasks=(second,)
    )
    call2 = _reserve_and_record(
        api,
        store,
        running2,
        run_id=run.run_id,
        window_key="two",
        tasks=(second,),
        raw=b'{"beta":"bad quote"}',
    )
    store.settle_window(
        scope=_scope(api),
        run_id=run.run_id,
        job_id=running2.id,
        generation=running2.lease_generation,
        outcomes=(_failed(api, second, raw_ref=call2.raw_ref, reason="quote_not_in_source"),),
    )

    attempts = store.list_field_attempts(scope=_scope(api), run_id=run.run_id)
    assert [(item.field_key, item.outcome) for item in attempts] == [
        ("alpha", api.FieldOutcomeKind.VERIFIED),
        ("beta", api.FieldOutcomeKind.EXTRACTION_FAILED),
    ]
    with factory() as session:
        assert session.scalar(select(WikiJob.state).where(WikiJob.id == running1.id)) == "succeeded"
        events = session.scalars(
            select(WikiOutboxEvent).where(WikiOutboxEvent.event_type == "product.window.settled")
        ).all()
    assert len(events) == 2


def test_cache_depends_on_source_and_schema_but_not_model_prompt_or_task_provenance(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    store, jobs = _make_store(api, factory)
    run, _ = _run_with_uploads(api, store)
    original = _task(api, "alpha")
    _window, running = _start_window(
        api, store, jobs, run_id=run.run_id, window_key="cache", tasks=(original,)
    )
    call = _reserve_and_record(
        api,
        store,
        running,
        run_id=run.run_id,
        window_key="cache",
        tasks=(original,),
        raw=b'{"alpha":"ok"}',
    )
    store.settle_window(
        scope=_scope(api),
        run_id=run.run_id,
        job_id=running.id,
        generation=running.lease_generation,
        outcomes=(_verified(api, original, raw_ref=call.raw_ref),),
    )

    exact = store.lookup_cached_fields(scope=_scope(api), identities=(original.cache_identity,))
    changed_source = api.FieldCacheIdentity(
        **{
            **original.cache_identity.model_dump(exclude={"source_dependencies"}),
            "source_dependencies": (
                {"source_revision_id": "revision-1", "source_sha256": "6" * 64},
            ),
        }
    )
    changed_schema = api.FieldCacheIdentity(
        **{
            **original.cache_identity.model_dump(exclude={"schema_version"}),
            "schema_version": "catalog-2026-10",
        }
    )
    assert exact[original.cache_identity.cache_key].field_key == "alpha"
    assert store.lookup_cached_fields(scope=_scope(api), identities=(changed_source,)) == {}
    assert store.lookup_cached_fields(scope=_scope(api), identities=(changed_schema,)) == {}
    changed_provenance = original.model_copy(
        update={
            "task_sha256": "7" * 64,
            "model_policy_sha256": "6" * 64,
            "prompt_policy_sha256": "8" * 64,
            "validation_version": "g3-field-validation.v2",
        }
    )
    reused = store.lookup_cached_fields(
        scope=_scope(api), identities=(changed_provenance.cache_identity,)
    )
    assert reused[original.cache_identity.cache_key].field_key == "alpha"

    second_run, _ = _run_with_uploads(api, store, idempotency_key="browser-upload-cache-reuse")
    changed_provenance_window = store.enqueue_window(
        scope=_scope(api),
        run_id=second_run.run_id,
        stage_key="extract",
        window_key="all-cached",
        dependency_sha256="9" * 64,
        tasks=(changed_provenance,),
    )
    claimed = jobs.claim(space_ids=("space-a",), worker_id="cache-worker")
    assert isinstance(claimed, ClaimedJob)
    running = jobs.start(
        space_id="space-a",
        job_id=claimed.job.id,
        generation=claimed.job.lease_generation,
    )
    reservation = store.reserve_window(
        scope=_scope(api),
        run_id=second_run.run_id,
        job_id=changed_provenance_window.job_id,
        generation=running.lease_generation,
        attempt=running.attempt,
        call_id="must-not-dispatch",
        window_key="all-cached",
        request_sha256=REQUEST_SHA256,
        tasks=(changed_provenance,),
    )
    assert reservation.action is api.WindowReservationAction.ALL_CACHED
    assert reservation.call is None
    assert reservation.dispatch_tasks == ()
    settled = store.settle_window(
        scope=_scope(api),
        run_id=second_run.run_id,
        job_id=running.id,
        generation=running.lease_generation,
        outcomes=(),
    )
    assert settled.success_count == 1
    reused_attempt = store.list_field_attempts(scope=_scope(api), run_id=second_run.run_id)[0]
    assert (
        reused_attempt.reused_from_attempt_id == exact[original.cache_identity.cache_key].attempt_id
    )
    assert reused_attempt.task_sha256 == original.task_sha256
    assert (
        reused_attempt.validation_version
        == exact[original.cache_identity.cache_key].validation_version
    )
    assert (
        reused_attempt.model_policy_sha256
        == exact[original.cache_identity.cache_key].model_policy_sha256
    )
    assert (
        reused_attempt.prompt_policy_sha256
        == exact[original.cache_identity.cache_key].prompt_policy_sha256
    )


def test_all_product_reads_and_mutations_fail_closed_across_spaces(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    store, _jobs = _make_store(api, factory)
    run = store.create_run(scope=_scope(api), idempotency_key="scope-test")
    wrong_scope = _scope(api, "space-b")

    with pytest.raises(SpaceScopeError):
        store.get_run(scope=wrong_scope, run_id=run.run_id)
    with pytest.raises(SpaceScopeError):
        store.attach_original(
            scope=wrong_scope,
            run_id=run.run_id,
            expected_version=run.version,
            original=api.OriginalKnowledgeRef(
                knowledge_id="knowledge-x",
                original_filename="x.pdf",
                upload_ordinal=0,
            ),
        )


def test_same_space_different_raw_or_wiki_scope_cannot_read_calls_or_reuse_cache(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    store, jobs = _make_store(api, factory)
    run, _ = _run_with_uploads(api, store)
    task = _task(api, "alpha")
    window, running = _start_window(
        api, store, jobs, run_id=run.run_id, window_key="scope-kb", tasks=(task,)
    )
    call = _reserve_and_record(
        api,
        store,
        running,
        run_id=run.run_id,
        window_key="scope-kb",
        tasks=(task,),
        raw=b'{"alpha":"ok"}',
    )
    store.settle_window(
        scope=_scope(api),
        run_id=run.run_id,
        job_id=running.id,
        generation=running.lease_generation,
        outcomes=(_verified(api, task, raw_ref=call.raw_ref),),
    )
    wrong = api.ProductScope(
        tenant_id="tenant-a",
        space_id="space-a",
        raw_knowledge_base_id="raw-other",
        wiki_knowledge_base_id="wiki-other",
    )
    with pytest.raises(SpaceScopeError):
        store.get_call(scope=wrong, call_id=call.call_id)
    with pytest.raises(SpaceScopeError):
        store.get_window(scope=wrong, run_id=run.run_id, window_id=window.window_id)
    assert store.lookup_cached_fields(scope=wrong, identities=(task.cache_identity,)) == {}


def test_dispatch_reservation_uses_same_transaction_job_fence_and_stale_writes_refuse(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    store, jobs = _make_store(api, factory)
    run, _ = _run_with_uploads(api, store)
    task = _task(api, "alpha")
    _window, first = _start_window(
        api, store, jobs, run_id=run.run_id, window_key="fenced", tasks=(task,)
    )
    reservation = store.reserve_window(
        scope=_scope(api),
        run_id=run.run_id,
        job_id=first.id,
        generation=first.lease_generation,
        attempt=first.attempt,
        call_id="call-fenced",
        window_key="fenced",
        request_sha256=REQUEST_SHA256,
        tasks=(task,),
    )
    store.begin_call(
        scope=_scope(api),
        call_id=reservation.call.call_id,
        job_id=first.id,
        generation=first.lease_generation,
        request_sha256=REQUEST_SHA256,
        request_bytes=REQUEST_BYTES,
    )
    uncertain = store.reserve_window(
        scope=_scope(api),
        run_id=run.run_id,
        job_id=first.id,
        generation=first.lease_generation,
        attempt=first.attempt,
        call_id="a-different-call-id-cannot-trigger-redispatch",
        window_key="fenced",
        request_sha256=REQUEST_SHA256,
        tasks=(task,),
    )
    assert uncertain.action is api.WindowReservationAction.INTERRUPTED
    assert uncertain.dispatch_tasks == ()

    with factory() as session:
        with session.begin():
            session.execute(
                text(
                    "UPDATE wiki_jobs SET lease_expires_at = "
                    "'2000-01-01 00:00:00.000000+00:00' WHERE id = :job_id"
                ),
                {"job_id": first.id},
            )
    jobs.reclaim_expired_leases(space_ids=("space-a",))
    claimed = jobs.claim(space_ids=("space-a",), worker_id="worker-new")
    assert isinstance(claimed, ClaimedJob)
    second = jobs.start(
        space_id="space-a",
        job_id=claimed.job.id,
        generation=claimed.job.lease_generation,
    )
    assert second.lease_generation > first.lease_generation

    with pytest.raises(StaleGenerationError):
        store.record_call_result(
            scope=_scope(api),
            call_id="call-fenced",
            job_id=first.id,
            generation=first.lease_generation,
            request_sha256=REQUEST_SHA256,
            raw=b"late",
            diagnostic=None,
        )
    with pytest.raises(StaleGenerationError):
        store.settle_window(
            scope=_scope(api),
            run_id=run.run_id,
            job_id=first.id,
            generation=first.lease_generation,
            outcomes=(),
        )


def test_dispatching_call_is_interrupted_after_reclaim_and_never_redispatched(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    store, jobs = _make_store(api, factory)
    run, _ = _run_with_uploads(api, store)
    task = _task(api, "alpha")
    _window, first = _start_window(
        api, store, jobs, run_id=run.run_id, window_key="interrupt", tasks=(task,)
    )
    reservation = store.reserve_window(
        scope=_scope(api),
        run_id=run.run_id,
        job_id=first.id,
        generation=first.lease_generation,
        attempt=first.attempt,
        call_id="call-interrupt",
        window_key="interrupt",
        request_sha256=REQUEST_SHA256,
        tasks=(task,),
    )
    store.begin_call(
        scope=_scope(api),
        call_id=reservation.call.call_id,
        job_id=first.id,
        generation=first.lease_generation,
        request_sha256=REQUEST_SHA256,
        request_bytes=REQUEST_BYTES,
    )
    with factory() as session:
        with session.begin():
            session.execute(
                text(
                    "UPDATE wiki_jobs SET lease_expires_at = "
                    "'2000-01-01 00:00:00.000000+00:00' WHERE id = :job_id"
                ),
                {"job_id": first.id},
            )
    jobs.reclaim_expired_leases(space_ids=("space-a",))
    claimed = jobs.claim(space_ids=("space-a",), worker_id="worker-recovery")
    assert isinstance(claimed, ClaimedJob)
    second = jobs.start(
        space_id="space-a",
        job_id=claimed.job.id,
        generation=claimed.job.lease_generation,
    )

    recovered = store.reserve_window(
        scope=_scope(api),
        run_id=run.run_id,
        job_id=second.id,
        generation=second.lease_generation,
        attempt=second.attempt,
        call_id="call-interrupt",
        window_key="interrupt",
        request_sha256=REQUEST_SHA256,
        tasks=(task,),
    )
    assert recovered.action is api.WindowReservationAction.INTERRUPTED
    assert recovered.dispatch_tasks == ()
    assert recovered.call.state is api.CallState.INTERRUPTED
    assert recovered.outcomes[0].outcome is api.FieldOutcomeKind.EXTRACTION_FAILED
    assert recovered.outcomes[0].reason == "provider_call_interrupted"


def test_recorded_call_checkpoint_is_exactly_idempotent_and_conflicts_on_change(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    store, jobs = _make_store(api, factory)
    run, _ = _run_with_uploads(api, store)
    task = _task(api, "alpha")
    _window, running = _start_window(
        api, store, jobs, run_id=run.run_id, window_key="record-idempotent", tasks=(task,)
    )
    first = _reserve_and_record(
        api,
        store,
        running,
        run_id=run.run_id,
        window_key="record-idempotent",
        tasks=(task,),
        raw=b"same-raw",
    )
    repeated = store.record_call_result(
        scope=_scope(api),
        call_id=first.call_id,
        job_id=running.id,
        generation=running.lease_generation,
        request_sha256=REQUEST_SHA256,
        raw=b"same-raw",
        diagnostic=None,
    )
    assert repeated == first
    with pytest.raises(ValueError, match="immutable|conflict"):
        store.record_call_result(
            scope=_scope(api),
            call_id=first.call_id,
            job_id=running.id,
            generation=running.lease_generation,
            request_sha256=REQUEST_SHA256,
            raw=b"different-raw",
            diagnostic=None,
        )


def test_reservation_freezes_selected_fields_before_request_and_later_cache_cannot_change_it(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    store, jobs = _make_store(api, factory)
    first_run, _ = _run_with_uploads(api, store, idempotency_key="selection-first")
    task = _task(api, "delta")
    first_window, first_job = _start_window(
        api, store, jobs, run_id=first_run.run_id, window_key="selection", tasks=(task,)
    )
    reservation = store.reserve_window(
        scope=_scope(api),
        run_id=first_run.run_id,
        job_id=first_job.id,
        generation=first_job.lease_generation,
        attempt=first_job.attempt,
        call_id="call-selection-first",
        window_key="selection",
        request_sha256=None,
        tasks=(task,),
    )
    assert reservation.dispatch_tasks == (task,)
    assert reservation.call.request_sha256 is None
    assert reservation.call.selected_field_keys == ((task.entity_id, task.field_key),)

    second_run, _ = _run_with_uploads(api, store, idempotency_key="selection-second")
    _second_window, second_job = _start_window(
        api, store, jobs, run_id=second_run.run_id, window_key="selection-cache", tasks=(task,)
    )
    second_call = _reserve_and_record(
        api,
        store,
        second_job,
        run_id=second_run.run_id,
        window_key="selection-cache",
        tasks=(task,),
        raw=b'{"delta":"ok"}',
    )
    store.settle_window(
        scope=_scope(api),
        run_id=second_run.run_id,
        job_id=second_job.id,
        generation=second_job.lease_generation,
        outcomes=(_verified(api, task, raw_ref=second_call.raw_ref),),
    )

    request = b'{"request":"selected-delta"}'
    request_sha = hashlib.sha256(request).hexdigest()
    begun = store.begin_call(
        scope=_scope(api),
        call_id=reservation.call.call_id,
        job_id=first_job.id,
        generation=first_job.lease_generation,
        request_sha256=request_sha,
        request_bytes=request,
    )
    assert (
        store.begin_call(
            scope=_scope(api),
            call_id=reservation.call.call_id,
            job_id=first_job.id,
            generation=first_job.lease_generation,
            request_sha256=request_sha,
            request_bytes=request,
        )
        == begun
    )
    different_request = b'{"request":"different"}'
    with pytest.raises(ValueError, match="immutable"):
        store.begin_call(
            scope=_scope(api),
            call_id=reservation.call.call_id,
            job_id=first_job.id,
            generation=first_job.lease_generation,
            request_sha256=hashlib.sha256(different_request).hexdigest(),
            request_bytes=different_request,
        )
    first_call = store.record_call_result(
        scope=_scope(api),
        call_id=reservation.call.call_id,
        job_id=first_job.id,
        generation=first_job.lease_generation,
        request_sha256=request_sha,
        raw=b'{"delta":"also-ok"}',
        diagnostic=None,
    )
    prepared, counts = store.prepare_window_settlement(
        scope=_scope(api),
        run_id=first_run.run_id,
        job_id=first_job.id,
        generation=first_job.lease_generation,
        outcomes=(_verified(api, task, raw_ref=first_call.raw_ref),),
    )
    assert counts.success_count == 1
    assert prepared.domain_writes
    assert first_window.job_id == first_job.id


def test_failed_field_retry_is_new_attempt_and_cannot_replace_success(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    store, jobs = _make_store(api, factory)
    run, _ = _run_with_uploads(api, store)
    good = _task(api, "alpha")
    bad = _task(api, "beta")
    _window, running = _start_window(
        api, store, jobs, run_id=run.run_id, window_key="retry-origin", tasks=(good, bad)
    )
    call = _reserve_and_record(
        api,
        store,
        running,
        run_id=run.run_id,
        window_key="retry-origin",
        tasks=(good, bad),
        raw=b'{"mixed":true}',
    )
    store.settle_window(
        scope=_scope(api),
        run_id=run.run_id,
        job_id=running.id,
        generation=running.lease_generation,
        outcomes=(
            _verified(api, good, raw_ref=call.raw_ref),
            _failed(api, bad, raw_ref=call.raw_ref, reason="missing_evidence"),
        ),
    )

    retry = store.retry_fields(
        scope=_scope(api),
        run_id=run.run_id,
        failed_attempt_ids=(
            store.list_field_attempts(scope=_scope(api), run_id=run.run_id, field_keys=("beta",))[
                0
            ].attempt_id,
        ),
        idempotency_key="user-retry-1",
    )
    assert retry.retry_of_run_id == run.run_id
    assert retry.run_id != run.run_id
    assert retry.attempt == 2
    assert retry.retry_field_keys == ("beta",)
    assert retry.uploads_sealed_at == retry.started_at
    assert retry.started_at is not None
    assert run.started_at is not None
    assert retry.started_at >= run.started_at
    good_attempt = store.list_field_attempts(
        scope=_scope(api), run_id=run.run_id, field_keys=("alpha",)
    )[0]
    with pytest.raises(ValueError, match="only extraction_failed"):
        store.retry_fields(
            scope=_scope(api),
            run_id=run.run_id,
            failed_attempt_ids=(good_attempt.attempt_id,),
            idempotency_key="invalid-retry",
        )
    foreign_scope = api.ProductScope(
        tenant_id="tenant-a",
        space_id="space-a",
        raw_knowledge_base_id="raw-foreign",
        wiki_knowledge_base_id="wiki-foreign",
    )
    store.create_run(scope=foreign_scope, idempotency_key="foreign-retry-key")
    with pytest.raises(SpaceScopeError):
        store.retry_fields(
            scope=_scope(api),
            run_id=run.run_id,
            failed_attempt_ids=(
                store.list_field_attempts(
                    scope=_scope(api), run_id=run.run_id, field_keys=("beta",)
                )[0].attempt_id,
            ),
            idempotency_key="foreign-retry-key",
        )


def test_failed_field_retry_renews_expired_source_deadlines_without_changing_materials(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    store, jobs = _make_store(api, factory)
    run, material_ids = _run_with_uploads(api, store)
    bad = _task(api, "expired-beta")
    _window, running = _start_window(
        api,
        store,
        jobs,
        run_id=run.run_id,
        window_key="expired-retry-origin",
        tasks=(bad,),
    )
    call = _reserve_and_record(
        api,
        store,
        running,
        run_id=run.run_id,
        window_key="expired-retry-origin",
        tasks=(bad,),
        raw=b'{"expired":true}',
    )
    store.settle_window(
        scope=_scope(api),
        run_id=run.run_id,
        job_id=running.id,
        generation=running.lease_generation,
        outcomes=(_failed(api, bad, raw_ref=call.raw_ref, reason="missing_evidence"),),
    )
    old_upload = datetime(2020, 1, 1, 1, tzinfo=UTC)
    old_source = datetime(2020, 1, 1, 2, tzinfo=UTC)
    with factory() as session:
        with session.begin():
            session.execute(
                text(
                    "UPDATE product_ingestion_runs "
                    "SET upload_deadline_at=:upload, source_deadline_at=:source WHERE id=:run_id"
                ),
                {"upload": old_upload, "source": old_source, "run_id": run.run_id},
            )
    origin = store.get_run(scope=_scope(api), run_id=run.run_id)
    failed = store.list_field_attempts(
        scope=_scope(api), run_id=run.run_id, field_keys=("expired-beta",)
    )[0]

    retry = store.retry_fields(
        scope=_scope(api),
        run_id=run.run_id,
        failed_attempt_ids=(failed.attempt_id,),
        idempotency_key="expired-deadline-retry",
    )

    assert origin.upload_deadline_at == old_upload
    assert origin.source_deadline_at == old_source
    assert retry.started_at is not None
    assert retry.upload_deadline_at > retry.started_at
    assert retry.source_deadline_at > retry.upload_deadline_at
    assert tuple(item.material_id for item in retry.materials) != tuple(material_ids)
    assert [
        (
            item.knowledge_id,
            item.upload_ordinal,
            item.source.source_revision_id,
            item.source.source_sha256,
        )
        for item in retry.materials
    ] == [
        (
            item.knowledge_id,
            item.upload_ordinal,
            item.source.source_revision_id,
            item.source.source_sha256,
        )
        for item in origin.materials
    ]


def test_terminal_aggregate_and_listing_are_stable_after_restart(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    store, jobs = _make_store(api, factory)
    run, _ = _run_with_uploads(api, store)
    good = _task(api, "alpha")
    bad = _task(api, "beta")
    _window, running = _start_window(
        api, store, jobs, run_id=run.run_id, window_key="terminal", tasks=(good, bad)
    )
    call = _reserve_and_record(
        api,
        store,
        running,
        run_id=run.run_id,
        window_key="terminal",
        tasks=(good, bad),
        raw=b'{"mixed":true}',
    )
    store.settle_window(
        scope=_scope(api),
        run_id=run.run_id,
        job_id=running.id,
        generation=running.lease_generation,
        outcomes=(
            _verified(api, good, raw_ref=call.raw_ref),
            _failed(api, bad, raw_ref=call.raw_ref, reason="missing_evidence"),
        ),
        usage={"input_tokens": 101, "output_tokens": 17},
    )
    root_job = store.enqueue_root(
        scope=_scope(api), run_id=run.run_id, idempotency_key="finalize-root"
    )
    claimed = jobs.claim(space_ids=("space-a",), worker_id="root-worker")
    assert isinstance(claimed, ClaimedJob)
    assert claimed.job.id == root_job.job_id
    running_root = jobs.start(
        space_id="space-a",
        job_id=claimed.job.id,
        generation=claimed.job.lease_generation,
    )
    finished = store.finalize_run(
        scope=_scope(api),
        run_id=run.run_id,
        job_id=running_root.id,
        generation=running_root.lease_generation,
        terminal_state=api.ProductRunState.PARTIAL_SUCCESS,
    )
    assert finished.success_count == 1
    assert finished.missing_count == 0
    assert finished.failure_count == 1
    assert finished.model_call_count == 1
    assert finished.usage == {"input_tokens": 101, "output_tokens": 17}
    assert finished.started_at is not None
    assert finished.finished_at is not None
    assert finished.finished_at >= finished.started_at

    restarted = api.ProductIngestionStore(factory, _job_store(factory))
    reloaded = restarted.get_run(scope=_scope(api), run_id=run.run_id)
    assert reloaded == finished
    assert restarted.list_runs(scope=_scope(api), limit=10) == (finished,)
    assert restarted.list_runs(scope=_scope(api, "space-b"), limit=10) == ()


def test_models_reject_unscoped_or_mutable_dependency_identity(api: SimpleNamespace) -> None:
    with pytest.raises(ValueError):
        api.ProductScope(
            tenant_id="",
            space_id="space-a",
            raw_knowledge_base_id="raw-a",
            wiki_knowledge_base_id="wiki-a",
        )
    with pytest.raises(ValueError):
        api.FieldCacheIdentity(
            product_identity_sha256="0" * 64,
            entity_id="entity-1820",
            field_key="alpha",
            source_dependencies=(),
            schema_adapter_id="catalog-1820",
            schema_adapter_sha256="3" * 64,
            schema_version="catalog-2026-09",
        )
    identity = _identity(api)
    with pytest.raises((AttributeError, TypeError, ValidationError)):
        identity.schema_version = "catalog-2026-10"


def test_run_timestamps_are_database_values_not_caller_values(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    store, _jobs = _make_store(api, factory)
    before = datetime.now(UTC)
    run = store.create_run(scope=_scope(api), idempotency_key="db-clock")
    after = datetime.now(UTC)
    assert before <= run.created_at <= after
    assert run.started_at is None
    assert run.finished_at is None
    assert run.expected_upload_count == 1
    assert run.upload_deadline_at < run.source_deadline_at


def test_upload_seal_starts_acceptance_clock_before_source_parsing_finishes(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    store, _jobs = _make_store(api, factory)
    scope = _scope(api)
    run = store.create_run(scope=scope, idempotency_key="upload-clock", expected_upload_count=2)
    material_ids = []
    for ordinal in range(2):
        run = store.attach_original(
            scope=scope,
            run_id=run.run_id,
            expected_version=run.version,
            original=api.OriginalKnowledgeRef(
                knowledge_id=f"clock-{ordinal}",
                original_filename=f"clock-{ordinal}.pdf",
                upload_ordinal=ordinal,
            ),
        )
        material_ids.append(run.materials[-1].material_id)
    sealed = store.seal_uploads(scope=scope, run_id=run.run_id, expected_version=run.version)
    assert sealed.started_at is not None
    assert sealed.uploads_sealed_at == sealed.started_at

    after_one_source = store.seal_material_source(
        scope=scope,
        run_id=run.run_id,
        material_id=material_ids[0],
        source=_source(api, "clock-0", 0),
    )
    assert after_one_source.started_at == sealed.started_at
    after_all_sources = store.seal_material_source(
        scope=scope,
        run_id=run.run_id,
        material_id=material_ids[1],
        source=_source(api, "clock-1", 1),
    )
    assert after_all_sources.started_at == sealed.started_at


def test_needs_confirmation_is_a_finished_run_backed_by_p1_blocked(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    store, jobs = _make_store(api, factory)
    run, _ = _run_with_uploads(api, store)
    root_job = store.enqueue_root(
        scope=_scope(api), run_id=run.run_id, idempotency_key="identity-conflict-root"
    )
    claimed = jobs.claim(space_ids=("space-a",), worker_id="identity-worker")
    assert isinstance(claimed, ClaimedJob)
    running = jobs.start(
        space_id="space-a",
        job_id=claimed.job.id,
        generation=claimed.job.lease_generation,
    )

    finished = store.finalize_needs_confirmation(
        scope=_scope(api),
        run_id=run.run_id,
        job_id=root_job.job_id,
        generation=running.lease_generation,
        reason="product_identity_conflict",
    )

    assert finished.state is api.ProductRunState.NEEDS_CONFIRMATION
    assert finished.terminal_reason == "product_identity_conflict"
    assert finished.finished_at is not None
    assert jobs.get_job(space_id="space-a", job_id=root_job.job_id).state.value == "blocked"


@pytest.mark.parametrize(
    ("error_class", "reason"),
    [
        (ErrorClass.NON_RETRYABLE, "source_deadline_exceeded"),
        (ErrorClass.CAPACITY_BLOCKED, "configured_capacity_blocked"),
    ],
)
def test_non_confirmation_root_terminal_never_leaves_domain_run_running(
    api: SimpleNamespace,
    factory: SessionFactory,
    error_class: ErrorClass,
    reason: str,
) -> None:
    store, jobs = _make_store(api, factory)
    run, _ = _run_with_uploads(api, store)
    root_job = store.enqueue_root(
        scope=_scope(api), run_id=run.run_id, idempotency_key=f"failed-root-{reason}"
    )
    claimed = jobs.claim(space_ids=("space-a",), worker_id="failed-root-worker")
    assert isinstance(claimed, ClaimedJob)
    assert claimed.job.id == root_job.job_id
    running = jobs.start(
        space_id="space-a",
        job_id=claimed.job.id,
        generation=claimed.job.lease_generation,
    )
    jobs.report_failure(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        failure=JobFailure(error_class=error_class, summary=reason),
    )

    failed = store.get_run(scope=_scope(api), run_id=run.run_id)
    assert failed.state is api.ProductRunState.FAILED
    assert failed.terminal_reason == reason
    assert failed.finished_at is not None


@pytest.mark.asyncio
async def test_worker_loop_commits_prepared_window_once_without_double_completion(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    store, jobs = _make_store(api, factory)
    run, _ = _run_with_uploads(api, store)
    task = _task(api, "alpha")
    window = store.enqueue_window(
        scope=_scope(api),
        run_id=run.run_id,
        stage_key="extract",
        window_key="worker-loop",
        dependency_sha256="9" * 64,
        tasks=(task,),
    )
    claimed = jobs.claim(space_ids=("space-a",), worker_id="worker-loop")
    assert isinstance(claimed, ClaimedJob)
    assert claimed.job.id == window.job_id
    registry = HandlerRegistry()

    async def handler(job: Any) -> HandlerResult:
        reservation = store.reserve_window(
            scope=_scope(api),
            run_id=run.run_id,
            job_id=job.id,
            generation=job.lease_generation,
            attempt=job.attempt,
            call_id="call-worker-loop",
            window_key="worker-loop",
            request_sha256=REQUEST_SHA256,
            tasks=(task,),
        )
        store.begin_call(
            scope=_scope(api),
            call_id=reservation.call.call_id,
            job_id=job.id,
            generation=job.lease_generation,
            request_sha256=REQUEST_SHA256,
            request_bytes=REQUEST_BYTES,
        )
        call = store.record_call_result(
            scope=_scope(api),
            call_id=reservation.call.call_id,
            job_id=job.id,
            generation=job.lease_generation,
            request_sha256=REQUEST_SHA256,
            raw=b'{"alpha":"ok"}',
            diagnostic=None,
        )
        result, counts = store.prepare_window_settlement(
            scope=_scope(api),
            run_id=run.run_id,
            job_id=job.id,
            generation=job.lease_generation,
            outcomes=(_verified(api, task, raw_ref=call.raw_ref),),
        )
        assert counts.success_count == 1
        return typing.cast(HandlerResult, result)

    registry.register("product_extraction_window", handler)
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    worker = WorkerLoop(
        store=jobs,
        registry=registry,
        settings=ShellSettings(
            postgres_dsn=SecretStr("postgresql://unused/test"),
            heartbeat_interval_seconds=30,
            lease_seconds=300,
        ),
        lifecycle=lifecycle,
        worker_id="worker-loop",
    )
    await worker.process_job(claimed.job)

    assert jobs.get_job(space_id="space-a", job_id=window.job_id).state.value == "succeeded"
    attempts = store.list_field_attempts(scope=_scope(api), run_id=run.run_id)
    assert [(item.field_key, item.outcome) for item in attempts] == [
        ("alpha", api.FieldOutcomeKind.VERIFIED)
    ]


def test_stage_is_an_independent_p1_job_with_stable_terminal_aggregate(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    store, jobs = _make_store(api, factory)
    run, _ = _run_with_uploads(api, store)
    stage = store.enqueue_stage(
        scope=_scope(api),
        run_id=run.run_id,
        stage_key="classification",
        dependency_sha256="6" * 64,
        idempotency_key="classification-stage",
    )
    claimed = jobs.claim(space_ids=("space-a",), worker_id="stage-worker")
    assert isinstance(claimed, ClaimedJob)
    assert claimed.job.id == stage.job_id
    running = jobs.start(
        space_id="space-a",
        job_id=claimed.job.id,
        generation=claimed.job.lease_generation,
    )
    settled = store.settle_stage(
        scope=_scope(api),
        run_id=run.run_id,
        stage_id=stage.stage_id,
        job_id=running.id,
        generation=running.lease_generation,
        state=api.ProductRunState.SUCCEEDED,
    )
    assert settled.state == "succeeded"
    assert settled.started_at is not None
    assert settled.finished_at is not None
    assert store.list_stages(scope=_scope(api), run_id=run.run_id) == (settled,)


def test_recent_runs_and_rotating_keyset_scan_have_distinct_ordering(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    store, _jobs = _make_store(api, factory)
    created = tuple(
        store.create_run(scope=_scope(api), idempotency_key=f"scan-{index}") for index in range(4)
    )
    ascending = tuple(sorted(created, key=lambda row: (row.created_at, row.run_id)))

    assert store.list_runs(scope=_scope(api), limit=3) == tuple(reversed(ascending))[:3]

    seen = []
    cursor = None
    while True:
        page = store.scan_runs(scope=_scope(api), after=cursor, limit=2)
        if not page:
            break
        seen.extend(page)
        cursor = (page[-1].created_at, page[-1].run_id)
    assert tuple((row.run_id, row.created_at) for row in seen) == tuple(
        (row.run_id, row.created_at) for row in ascending
    )


@pytest.mark.parametrize("kind", ["stage", "window", "root"])
def test_admission_commit_never_exposes_an_unbound_job(
    api: typing.Any, factory: typing.Any, monkeypatch: pytest.MonkeyPatch, kind: typing.Any
) -> None:
    from insurance_harness.product_ingestion.tables import ProductRun, ProductStage, ProductWindow

    jobs = _job_store(factory)
    store = api.ProductIngestionStore(factory, jobs)
    scope = _scope(api)
    run = store.create_run(scope=scope, idempotency_key="atomic-admission")
    original_enqueue = jobs.enqueue

    def crash_after_commit(**kwargs: typing.Any) -> None:
        result = original_enqueue(**kwargs)
        with factory() as session:
            if kind == "root":
                bound = session.get(ProductRun, run.run_id).root_job_id == result.job.id
            else:
                table = ProductStage if kind == "stage" else ProductWindow
                bound = (
                    session.scalar(select(table).where(table.job_id == result.job.id)) is not None
                )
        assert bound, "queued job became visible before its domain binding"
        raise RuntimeError("fixture process crash after enqueue commit")

    monkeypatch.setattr(jobs, "enqueue", crash_after_commit)
    with pytest.raises(RuntimeError, match="fixture process crash"):
        if kind == "root":
            store.enqueue_root(scope=scope, run_id=run.run_id, idempotency_key="root")
        elif kind == "stage":
            store.enqueue_stage(
                scope=scope,
                run_id=run.run_id,
                stage_key="identity",
                dependency_sha256="a" * 64,
                idempotency_key="identity",
            )
        else:
            store.enqueue_window(
                scope=scope,
                run_id=run.run_id,
                stage_key="extract",
                window_key="window",
                dependency_sha256="a" * 64,
                tasks=(_task(api, "alpha"),),
            )
