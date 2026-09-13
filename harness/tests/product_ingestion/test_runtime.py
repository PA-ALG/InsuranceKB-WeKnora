from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from insurance_harness.db.base import Base, make_engine, make_session_factory
from insurance_harness.jobs import (
    ClaimedJob,
    ErrorClass,
    JobFailure,
    JobRuntimeConfig,
    JobState,
    JobStore,
    OutboxDispatcher,
    OutboxEventDraft,
)
from insurance_harness.product_ingestion import tables  # noqa: F401
from insurance_harness.product_ingestion.models import ProductRunState, ProductScope
from insurance_harness.product_ingestion.store import ProductIngestionStore
from insurance_harness.service_shell.config import ShellSettings
from insurance_harness.service_shell.health import Lifecycle
from insurance_harness.service_shell.worker import HandlerRegistry, WorkerLoop


@pytest.fixture
def environment(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/runtime.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    config = JobRuntimeConfig(
        lease_seconds=300,
        heartbeat_interval_seconds=30,
        max_attempts=3,
        backoff_seconds=(0,),
        per_space_concurrency_limit=16,
        global_concurrency_limit=32,
    )
    jobs = JobStore(factory, config)
    store = ProductIngestionStore(factory, jobs)
    scope = ProductScope(
        tenant_id="tenant-a",
        space_id="space-a",
        raw_knowledge_base_id="raw-a",
        wiki_knowledge_base_id="wiki-a",
    )
    yield SimpleNamespace(
        engine=engine,
        factory=factory,
        jobs=jobs,
        store=store,
        scope=scope,
        outbox=OutboxDispatcher(factory, config),
    )
    engine.dispose()


def runtime_module():
    try:
        return importlib.import_module("insurance_harness.product_ingestion.runtime")
    except ModuleNotFoundError:
        pytest.fail("bounded product runtime is not implemented")


def emit(environment, *, event_id: str, event_type: str, run_id: str) -> None:
    queued = environment.jobs.enqueue(
        space_id=environment.scope.space_id,
        job_type="fixture_event",
        idempotency_key="fixture:" + event_id,
        payload={},
    )
    claimed = environment.jobs.claim(space_ids=(environment.scope.space_id,), worker_id="fixture")
    assert isinstance(claimed, ClaimedJob)
    running = environment.jobs.start(
        space_id=environment.scope.space_id,
        job_id=queued.job.id,
        generation=claimed.job.lease_generation,
    )
    environment.jobs.report_success(
        space_id=environment.scope.space_id,
        job_id=running.id,
        generation=running.lease_generation,
        events=(
            OutboxEventDraft(
                event_id=event_id,
                event_type=event_type,
                payload={"run_id": run_id},
            ),
        ),
    )


class RecordingProgression:
    def __init__(self, *, bad_run_id: str | None = None, final=ProductRunState.SUCCEEDED):
        self.bad_run_id = bad_run_id
        self.final = final
        self.advanced: list[str] = []
        self.finalized: list[str] = []

    def advance(self, _scope, run_id):
        self.advanced.append(run_id)
        if run_id == self.bad_run_id:
            raise ValueError("bad persisted run")

    def final_state(self, _scope, run_id):
        self.finalized.append(run_id)
        return self.final


@pytest.mark.asyncio
async def test_tick_acks_only_product_events_and_isolates_each_run(environment) -> None:
    module = runtime_module()
    bad = environment.store.create_run(scope=environment.scope, idempotency_key="bad")
    good = environment.store.create_run(scope=environment.scope, idempotency_key="good")
    emit(environment, event_id="foreign", event_type="another.domain", run_id=good.run_id)
    emit(
        environment,
        event_id="bad-product",
        event_type="product.stage.settled",
        run_id=bad.run_id,
    )
    emit(
        environment,
        event_id="good-product",
        event_type="product.window.settled",
        run_id=good.run_id,
    )
    progression = RecordingProgression(bad_run_id=bad.run_id)
    pump = module.ProductRuntimePump(
        store=environment.store,
        jobs=environment.jobs,
        outbox=environment.outbox,
        progression=progression,
        scopes={environment.scope.space_id: environment.scope},
        page_size=2,
        event_limit=10,
    )

    await pump.tick()

    pending = environment.outbox.read_pending(space_id=environment.scope.space_id, limit=10)
    assert {row.event_id for row in pending} == {"foreign", "bad-product"}
    assert good.run_id in progression.advanced
    assert any(issue.run_id == bad.run_id and issue.phase == "event" for issue in pump.issues)


@pytest.mark.asyncio
async def test_keyset_repair_rotates_past_terminal_or_bad_old_runs(environment) -> None:
    module = runtime_module()
    runs = tuple(
        environment.store.create_run(scope=environment.scope, idempotency_key=f"repair-{index}")
        for index in range(4)
    )
    ordered = tuple(sorted(runs, key=lambda row: (row.created_at, row.run_id)))
    progression = RecordingProgression(bad_run_id=ordered[0].run_id)
    pump = module.ProductRuntimePump(
        store=environment.store,
        jobs=environment.jobs,
        outbox=environment.outbox,
        progression=progression,
        scopes={environment.scope.space_id: environment.scope},
        page_size=1,
    )

    for _ in runs:
        await pump.tick()

    assert ordered[-1].run_id in progression.advanced
    assert len(pump.issues) >= 1


@pytest.mark.asyncio
async def test_run_ticks_until_shared_lifecycle_drains(environment) -> None:
    module = runtime_module()
    run = environment.store.create_run(scope=environment.scope, idempotency_key="long-lived")
    progression = RecordingProgression()
    lifecycle = Lifecycle()
    lifecycle.mark_serving()

    async def drain(_seconds):
        lifecycle.begin_drain()

    pump = module.ProductRuntimePump(
        store=environment.store,
        jobs=environment.jobs,
        outbox=environment.outbox,
        progression=progression,
        scopes={environment.scope.space_id: environment.scope},
        sleeper=drain,
    )
    await pump.run(lifecycle)

    assert run.run_id in progression.advanced


def worker_loop(environment, registry):
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    return WorkerLoop(
        store=environment.jobs,
        registry=registry,
        settings=ShellSettings(
            postgres_dsn="postgresql://unused/test",
            worker_space_ids=(environment.scope.space_id,),
            heartbeat_interval_seconds=30,
            lease_seconds=300,
        ),
        lifecycle=lifecycle,
        worker_id="finalizer",
    )


@pytest.mark.asyncio
async def test_registered_finalizer_uses_worker_loop_single_success(environment) -> None:
    module = runtime_module()
    run = environment.store.create_run(scope=environment.scope, idempotency_key="final")
    root = environment.store.enqueue_root(
        scope=environment.scope,
        run_id=run.run_id,
        idempotency_key="root:" + run.run_id,
    )
    claim = environment.jobs.claim(space_ids=(environment.scope.space_id,), worker_id="finalizer")
    assert isinstance(claim, ClaimedJob)
    progression = RecordingProgression(final=ProductRunState.SUCCEEDED)
    registry = HandlerRegistry()
    module.register_finalizer(
        registry,
        store=environment.store,
        jobs=environment.jobs,
        progression=progression,
        scopes={environment.scope.space_id: environment.scope},
    )

    await worker_loop(environment, registry).process_job(claim.job)

    assert (
        environment.jobs.get_job(space_id=environment.scope.space_id, job_id=root.job_id).state
        is JobState.SUCCEEDED
    )
    assert (
        environment.store.get_run(scope=environment.scope, run_id=run.run_id).state
        is ProductRunState.SUCCEEDED
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", [ProductRunState.NEEDS_CONFIRMATION, ProductRunState.FAILED])
async def test_finalizer_preserves_typed_child_confirmation_reason(environment, terminal) -> None:
    module = runtime_module()
    run = environment.store.create_run(scope=environment.scope, idempotency_key="confirm")
    stage = environment.store.enqueue_stage(
        scope=environment.scope,
        run_id=run.run_id,
        stage_key="identity",
        dependency_sha256="a" * 64,
        idempotency_key="identity:" + run.run_id,
    )
    child_claim = environment.jobs.claim(space_ids=(environment.scope.space_id,), worker_id="child")
    assert isinstance(child_claim, ClaimedJob)
    child = environment.jobs.start(
        space_id=environment.scope.space_id,
        job_id=stage.job_id,
        generation=child_claim.job.lease_generation,
    )
    environment.jobs.report_failure(
        space_id=environment.scope.space_id,
        job_id=child.id,
        generation=child.lease_generation,
        failure=JobFailure(
            error_class=(
                ErrorClass.CAPACITY_BLOCKED
                if terminal is ProductRunState.NEEDS_CONFIRMATION
                else ErrorClass.NON_RETRYABLE
            ),
            summary=(
                "needs_confirmation:ACTUAL_PRODUCT_VERSION_CONFLICT"
                if terminal is ProductRunState.NEEDS_CONFIRMATION
                else "PLATFORM_RESPONSE_INVALID"
            ),
        ),
    )
    root = environment.store.enqueue_root(
        scope=environment.scope,
        run_id=run.run_id,
        idempotency_key="root:" + run.run_id,
    )
    root_claim = environment.jobs.claim(
        space_ids=(environment.scope.space_id,), worker_id="finalizer"
    )
    assert isinstance(root_claim, ClaimedJob)
    progression = RecordingProgression(final=terminal)
    registry = HandlerRegistry()
    module.register_finalizer(
        registry,
        store=environment.store,
        jobs=environment.jobs,
        progression=progression,
        scopes={environment.scope.space_id: environment.scope},
    )

    await worker_loop(environment, registry).process_job(root_claim.job)

    assert environment.jobs.get_job(
        space_id=environment.scope.space_id, job_id=root.job_id
    ).state is (
        JobState.BLOCKED if terminal is ProductRunState.NEEDS_CONFIRMATION else JobState.SUCCEEDED
    )
    snapshot = environment.store.get_run(scope=environment.scope, run_id=run.run_id)
    assert snapshot.state is terminal
    assert snapshot.terminal_reason == (
        "ACTUAL_PRODUCT_VERSION_CONFLICT"
        if terminal is ProductRunState.NEEDS_CONFIRMATION
        else "PLATFORM_RESPONSE_INVALID"
    )
