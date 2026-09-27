"""Bounded field worker CPU and source custody must leave the lease loop runnable."""

from __future__ import annotations

# ruff: noqa: F401,F811 -- fixture imports.
import asyncio
import hashlib
import json
import threading
import typing
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState

from insurance_harness.knowledge_compiler.g3_field_tasks import FieldTaskV1
from insurance_harness.product_ingestion import extraction, stages, worker
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.composition import ProductScopeServices
from insurance_harness.product_ingestion.model_execution import (
    ConfiguredFieldTransport,
    PreparedModelRequest,
)
from insurance_harness.product_ingestion.models import WindowTaskSpec
from insurance_harness.service_shell.worker import HandlerRegistry
from tests.product_ingestion.test_extraction import (
    Port,
    many_source_tasks,
    response,
    row,
    source,
    tasks,
)
from tests.product_ingestion.test_platform import snapshot
from tests.product_ingestion.test_worker import runtime


async def live_loop_while_slow(factory: typing.Any, release: typing.Any) -> typing.Any:
    task = asyncio.create_task(factory())
    await asyncio.sleep(0.01)
    release.set()
    return await task


@pytest.mark.parametrize("boundary", ["read", "decode"])
def test_production_field_loader_keeps_loop_alive(
    snapshot: typing.Any, monkeypatch: pytest.MonkeyPatch, boundary: typing.Any
) -> None:
    scope, body, sign, keys = snapshot
    raw = sign(body)
    artifact = SimpleNamespace(payload=raw, artifact_key=body["receipt"]["knowledge_id"])
    store = SimpleNamespace(list_effective_artifacts=lambda **kw: (artifact,))
    owner, name = (
        (store, "list_effective_artifacts")
        if boundary == "read"
        else (stages, "decode_source_snapshot")
    )
    original = getattr(owner, name)
    release = threading.Event()
    main = threading.get_ident()
    observed = []

    def slow(*args: typing.Any, **kw: typing.Any) -> typing.Any:
        observed.append(threading.get_ident())
        assert release.wait(1), "field source custody blocked event loop"
        return original(*args, **kw)

    monkeypatch.setattr(owner, name, slow)
    result = asyncio.run(
        live_loop_while_slow(
            lambda: stages.load_source_blocks(
                typing.cast(ProductArtifactStore, store), scope, "fixture", public_keys=keys
            ),
            release,
        )
    )
    assert result and all(value != main for value in observed)


@pytest.mark.parametrize("boundary", ["_source_index", "render_window_request", "_project"])
def test_field_cpu_keeps_loop_and_io_callbacks_alive(
    source: typing.Any, monkeypatch: pytest.MonkeyPatch, boundary: typing.Any
) -> None:
    selected = tasks(source)
    port = Port(lambda request: response([row(task, request) for task in selected]))
    main = threading.get_ident()
    release = threading.Event()
    cpu_threads, io_threads = [], []
    original = getattr(extraction, boundary)

    def slow(*args: typing.Any, **kw: typing.Any) -> typing.Any:
        cpu_threads.append(threading.get_ident())
        assert release.wait(1), "field pure computation blocked event loop"
        return original(*args, **kw)

    def on_loop(callback: typing.Any) -> typing.Any:
        async def wrapped(*args: typing.Any) -> typing.Any:
            io_threads.append(threading.get_ident())
            return await callback(*args)

        return wrapped

    monkeypatch.setattr(extraction, boundary, slow)
    result = asyncio.run(
        live_loop_while_slow(
            lambda: extraction.execute_window(
                call_id="field-loop",
                tasks=selected,
                sources=(source,),
                tenant_id=1,
                space_id="space-1",
                raw_kb_id="raw-1",
                transport=on_loop(port.transport),
                begin_call=on_loop(port.begin),
                persist_raw=on_loop(port.persist),
            ),
            release,
        )
    )
    assert {item.outcome for item in result} == {"verified"}
    assert cpu_threads and all(value != main for value in cpu_threads)
    assert io_threads == [main, main, main] and port.events == ["begin", "transport", "persist"]


def start_window(runtime: typing.Any, specs: typing.Any = None) -> tuple[typing.Any, ...]:
    store, jobs, scope, defaults, selected, settings = runtime
    specs = defaults if specs is None else specs
    run = store.create_run(scope=scope, idempotency_key="heartbeat-window")
    window = store.enqueue_window(
        scope=scope,
        run_id=run.run_id,
        stage_key="extract",
        window_key="one",
        dependency_sha256="e" * 64,
        tasks=specs,
    )
    claim = jobs.claim(space_ids=(scope.space_id,), worker_id="worker")
    job = jobs.start(
        space_id=scope.space_id, job_id=window.job_id, generation=claim.job.lease_generation
    )
    return store, scope, run, job, window


@pytest.mark.parametrize("boundary", ["tasks", "prepare"])
def test_worker_restore_and_configured_prepare_are_off_loop(
    runtime: typing.Any, source: typing.Any, monkeypatch: pytest.MonkeyPatch, boundary: typing.Any
) -> None:
    store, scope, run, job, _ = start_window(runtime)
    selected = runtime[4]
    registry = HandlerRegistry()
    release = threading.Event()
    main = threading.get_ident()
    cpu_threads, send_threads = [], []

    def slow() -> None:
        cpu_threads.append(threading.get_ident())
        assert release.wait(1), "field worker restore/prepare blocked event loop"

    if boundary == "tasks":
        original = FieldTaskV1.model_validate

        def validate(_cls: object, *args: typing.Any, **kw: typing.Any) -> typing.Any:
            slow()
            return original(*args, **kw)

        monkeypatch.setattr(FieldTaskV1, "model_validate", classmethod(validate))

    class Configured(ConfiguredFieldTransport):
        def __init__(self) -> None:
            pass

        @property
        def model_policy_sha256(self) -> str:
            return "c" * 64

        def prepare(self, content: bytes) -> PreparedModelRequest:
            if boundary == "prepare":
                slow()
            return PreparedModelRequest(content, content, hashlib.sha256(content).hexdigest())

        async def send(self, prepared: PreparedModelRequest) -> bytes:
            send_threads.append(threading.get_ident())
            context = json.loads(prepared.semantic_request)
            return response([row(task, context) for task in selected])

        @staticmethod
        def decode_response(raw: bytes) -> bytes:
            return raw

    async def sources(*args: object) -> tuple[typing.Any, ...]:
        return (source,)

    worker.register_extraction_worker(
        registry,
        store=store,
        scopes={scope.space_id: scope},
        load_sources=sources,
        transport_factory=lambda *args: Configured(),
    )
    handler = registry.get("product_extraction_window")
    assert handler is not None
    result = asyncio.run(
        live_loop_while_slow(
            lambda: handler(job),
            release,
        )
    )
    assert result.domain_writes and send_threads == [main]
    assert cpu_threads and all(value != main for value in cpu_threads)


def test_reservation_hydrates_and_compares_full_large_tasks_before_job_fence(
    runtime: typing.Any, many_source_tasks: typing.Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, selected = many_source_tasks
    prototype = runtime[3][0]
    specs = tuple(
        WindowTaskSpec(
            **{
                **prototype.model_dump(),
                "field_key": task.field_key,
                "task_sha256": task.task_sha256,
                "task_payload": task.model_dump(mode="json"),
                "cache_identity": prototype.cache_identity.model_copy(
                    update={"field_key": task.field_key}
                ),
            },
        )
        for task in selected
    )
    store, scope, run, job, window = start_window(runtime, specs)
    fenced, task_reads, comparisons = set(), [], []
    original_fence, original_dump = store._active_job, WindowTaskSpec.model_dump

    def fence(session: typing.Any, *args: typing.Any, **kw: typing.Any) -> typing.Any:
        fenced.add(id(session))
        return original_fence(session, *args, **kw)

    def observe(state: ORMExecuteState) -> None:
        if not state.is_select:
            return
        statement = typing.cast(typing.Any, state.statement)
        names = {getattr(item, "name", "") for item in statement.get_final_froms()}
        if "product_ingestion_windows" in names and any(
            getattr(col, "name", "") == "tasks" for col in statement.selected_columns
        ):
            task_reads.append(id(state.session))
            lock = statement._for_update_arg
            assert lock is not None and lock.key_share and not lock.read
            assert id(state.session) not in fenced, "full sealed task JSON hydrated under job lock"

    def dump(self: WindowTaskSpec, *args: typing.Any, **kw: typing.Any) -> typing.Any:
        comparisons.append(True)
        assert not fenced, "full task comparison serialized under job lock"
        return original_dump(self, *args, **kw)

    monkeypatch.setattr(store, "_active_job", fence)
    monkeypatch.setattr(WindowTaskSpec, "model_dump", dump)
    event.listen(store._session_factory.class_, "do_orm_execute", observe)
    try:
        reservation = store.reserve_window(
            scope=scope,
            run_id=run.run_id,
            job_id=job.id,
            generation=job.lease_generation,
            attempt=job.attempt,
            call_id="bounded-reserve",
            window_key=window.window_key,
            tasks=specs,
        )
    finally:
        event.remove(store._session_factory.class_, "do_orm_execute", observe)
    assert reservation.call is not None and task_reads and comparisons and fenced


def test_scoped_loader_gate_waits_for_cancelled_read_to_finish(
    snapshot: typing.Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from insurance_harness.product_ingestion import composition

    scope, _, _, keys = snapshot
    entered, finish = threading.Event(), threading.Event()
    starts = []

    def read(run_id: str) -> tuple[typing.Any, ...]:
        starts.append(run_id)
        if run_id == "first":
            entered.set()
            assert finish.wait(2), "fixture read release missing"
        return (run_id,)

    async def load(_artifacts: object, _scope: object, run_id: str, **kw: object) -> typing.Any:
        return await asyncio.to_thread(read, run_id)

    monkeypatch.setattr(composition, "load_source_blocks", load)
    service = SimpleNamespace(scope=scope, configuration=SimpleNamespace(source_public_keys=keys))
    artifacts = SimpleNamespace(list_effective_artifact_references=lambda **kw: (kw["run_id"],))
    loader = typing.cast(
        typing.Callable[[object, str], typing.Awaitable[tuple[str, ...]]],
        composition._scoped_source_loader(
            typing.cast(ProductArtifactStore, artifacts),
            {scope.space_id: typing.cast(ProductScopeServices, service)},
        ),
    )

    async def run() -> None:
        async def load_run(run_id: str) -> tuple[str, ...]:
            return await loader(scope, run_id)

        first = asyncio.create_task(load_run("first"))
        assert await asyncio.to_thread(entered.wait, 1)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(load_run("second"))
        await asyncio.sleep(0.03)
        assert starts == ["first"], "cancelled waiter released a still-running source read"
        queued = asyncio.create_task(load_run("cancelled-before-read"))
        await asyncio.sleep(0)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        finish.set()
        assert await second == ("second",)
        assert starts == ["first", "second"]
        with pytest.raises(ValueError, match="scope"):
            await loader(scope.model_copy(update={"tenant_id": "wrong"}), "foreign")

    asyncio.run(run())


def test_generation_change_during_render_prevents_provider_dispatch(
    runtime: typing.Any, source: typing.Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import update

    from insurance_harness.jobs import StaleGenerationError
    from insurance_harness.jobs.tables import WikiJob

    store, scope, run, job, _ = start_window(runtime)
    registry = HandlerRegistry()
    original = extraction.render_window_request
    sent = []

    def changed_generation(*args: typing.Any, **kw: typing.Any) -> typing.Any:
        request = original(*args, **kw)
        with store._session_factory() as session, session.begin():
            session.execute(
                update(WikiJob)
                .where(WikiJob.id == job.id)
                .values(
                    lease_generation=job.lease_generation + 1,
                )
            )
        return request

    async def sources(*args: object) -> tuple[typing.Any, ...]:
        return (source,)

    async def transport(raw: bytes) -> bytes:
        sent.append(raw)
        raise AssertionError("stale worker must not dispatch")

    monkeypatch.setattr(extraction, "render_window_request", changed_generation)
    worker.register_extraction_worker(
        registry,
        store=store,
        scopes={scope.space_id: scope},
        load_sources=sources,
        transport=transport,
    )
    handler = registry.get("product_extraction_window")
    assert handler is not None

    async def invoke_handler() -> typing.Any:
        return await handler(job)

    with pytest.raises(StaleGenerationError):
        asyncio.run(invoke_handler())
    assert not sent
    call = store.list_calls(scope=scope, run_id=run.run_id)[0]
    assert call.state.value == "reserved" and call.dispatched_at is None and call.raw is None


def test_scoped_loader_reuses_verified_blocks_until_snapshot_identity_changes(
    snapshot: typing.Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from insurance_harness.product_ingestion import composition

    scope, _, _, keys = snapshot
    refs = ["snapshot-v1"]
    reads = []

    class Artifacts:
        def list_effective_artifact_references(self, **kwargs: object) -> typing.Any:
            return tuple(refs)

    async def load(*args: object, **kwargs: object) -> typing.Any:
        reads.append(tuple(refs))
        return tuple(refs)

    monkeypatch.setattr(composition, "load_source_blocks", load)
    service = SimpleNamespace(scope=scope, configuration=SimpleNamespace(source_public_keys=keys))
    loader = typing.cast(
        typing.Callable[[object, str], typing.Awaitable[tuple[str, ...]]],
        composition._scoped_source_loader(
            typing.cast(ProductArtifactStore, Artifacts()),
            {scope.space_id: typing.cast(ProductScopeServices, service)},
        ),
    )

    async def run() -> None:
        assert await loader(scope, "run") == ("snapshot-v1",)
        assert await loader(scope, "run") == ("snapshot-v1",)
        assert len(reads) == 1, "each field window reopens the full source geometry"
        refs[0] = "snapshot-v2"
        assert await loader(scope, "run") == ("snapshot-v2",)
        assert len(reads) == 2
        await loader(scope, "other-run")
        assert len(reads) == 3, "cache must not cross a run's immutable references"

    asyncio.run(run())


def test_expired_job_reclaim_records_old_lease_and_generation(
    runtime: typing.Any, caplog: typing.Any
) -> None:
    import logging
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from insurance_harness.jobs.tables import WikiJob

    store, scope, run, job, _ = start_window(runtime)
    expired = datetime.now(UTC) - timedelta(seconds=60)
    with store._session_factory() as session, session.begin():
        session.execute(
            update(WikiJob).where(WikiJob.id == job.id).values(lease_expires_at=expired)
        )
    jobs = runtime[1]
    with caplog.at_level(logging.WARNING):
        jobs.reclaim_expired_leases(space_ids=(scope.space_id,))
    records = [r for r in caplog.records if getattr(r, "event", "") == "job_lease_reclaimed"]
    assert records, "lost lease has no durable-context diagnostic"
    assert records[0].job_id == job.id
    assert records[0].generation == job.lease_generation
    assert records[0].expired_at and records[0].reclaimed_at
