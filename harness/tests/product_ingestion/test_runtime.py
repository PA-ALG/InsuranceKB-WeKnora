from __future__ import annotations

import importlib
import typing
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

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
def environment(tmp_path: Path) -> Iterator[SimpleNamespace]:
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


def runtime_module() -> typing.Any:
    try:
        return importlib.import_module("insurance_harness.product_ingestion.runtime")
    except ModuleNotFoundError:
        pytest.fail("bounded product runtime is not implemented")


def emit(environment: typing.Any, *, event_id: str, event_type: str, run_id: str) -> None:
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
    def __init__(
        self, *, bad_run_id: str | None = None, final: typing.Any = ProductRunState.SUCCEEDED
    ) -> None:
        self.bad_run_id = bad_run_id
        self.final = final
        self.advanced: list[str] = []
        self.finalized: list[str] = []

    def advance(self, _scope: object, run_id: str) -> None:
        self.advanced.append(run_id)
        if run_id == self.bad_run_id:
            raise ValueError("bad persisted run")

    def final_state(self, _scope: object, run_id: str) -> typing.Any:
        self.finalized.append(run_id)
        return self.final


@pytest.mark.asyncio
async def test_tick_acks_only_product_events_and_isolates_each_run(environment: typing.Any) -> None:
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
async def test_keyset_repair_rotates_past_terminal_or_bad_old_runs(environment: typing.Any) -> None:
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
async def test_run_ticks_until_shared_lifecycle_drains(environment: typing.Any) -> None:
    module = runtime_module()
    run = environment.store.create_run(scope=environment.scope, idempotency_key="long-lived")
    progression = RecordingProgression()
    lifecycle = Lifecycle()
    lifecycle.mark_serving()

    async def drain(_seconds: object) -> None:
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


def worker_loop(environment: typing.Any, registry: typing.Any) -> WorkerLoop:
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    return WorkerLoop(
        store=environment.jobs,
        registry=registry,
        settings=ShellSettings(
            postgres_dsn=SecretStr("postgresql://unused/test"),
            worker_space_ids=(environment.scope.space_id,),
            heartbeat_interval_seconds=30,
            lease_seconds=300,
        ),
        lifecycle=lifecycle,
        worker_id="finalizer",
    )


@pytest.mark.asyncio
async def test_registered_finalizer_uses_worker_loop_single_success(
    environment: typing.Any,
) -> None:
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
async def test_finalizer_preserves_typed_child_confirmation_reason(
    environment: typing.Any, terminal: typing.Any
) -> None:
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


@pytest.mark.asyncio
async def test_expired_identity_is_reconciled_to_durable_failed_without_model_calls(
    environment: typing.Any,
) -> None:
    from datetime import UTC, datetime

    from sqlalchemy import update

    from insurance_harness.jobs.tables import WikiJob
    from insurance_harness.product_ingestion.progression import ProductProgression

    scope, store, jobs = environment.scope, environment.store, environment.jobs
    run = store.create_run(scope=scope, idempotency_key="expired-identity")
    stage = store.enqueue_stage(
        scope=scope,
        run_id=run.run_id,
        stage_key="identity",
        dependency_sha256="a" * 64,
        idempotency_key="identity:" + run.run_id,
    )
    for _attempt in range(3):
        claim = jobs.claim(space_ids=(scope.space_id,), worker_id="expired-worker")
        assert isinstance(claim, ClaimedJob) and claim.job.id == stage.job_id
        jobs.start(
            space_id=scope.space_id, job_id=stage.job_id, generation=claim.job.lease_generation
        )
        # Test-only SQLite clock setup; exercise the real lease reclaimer afterward.
        with environment.factory() as session, session.begin():
            session.execute(
                update(WikiJob)
                .where(WikiJob.id == stage.job_id)
                .values(
                    lease_expires_at=datetime(2020, 1, 1, tzinfo=UTC),
                )
            )
        jobs.reclaim_expired_leases(space_ids=(scope.space_id,))
    assert jobs.get_job(space_id=scope.space_id, job_id=stage.job_id).state is JobState.DEAD_LETTER
    progression = ProductProgression(store=store, jobs=jobs, read_window_plan=lambda *_: ())
    module = runtime_module()
    pump = module.ProductRuntimePump(
        store=store,
        jobs=jobs,
        outbox=environment.outbox,
        progression=progression,
        scopes={scope.space_id: scope},
    )
    await pump.tick()
    claim = jobs.claim(space_ids=(scope.space_id,), worker_id="finalizer")
    assert isinstance(claim, ClaimedJob)
    assert claim.job.job_type == "product_ingestion_root"
    registry = HandlerRegistry()
    module.register_finalizer(
        registry,
        store=store,
        jobs=jobs,
        progression=progression,
        scopes={scope.space_id: scope},
    )
    await worker_loop(environment, registry).process_job(claim.job)
    final = store.get_run(scope=scope, run_id=run.run_id)
    assert final.state is ProductRunState.FAILED
    assert final.terminal_reason == "PRODUCT_STAGE_FAILED:identity"
    assert final.finished_at is not None and final.model_call_count == 0


@pytest.mark.asyncio
async def test_repair_selects_live_identities_without_loading_terminal_evidence(
    environment: typing.Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from sqlalchemy import event

    from insurance_harness.jobs.tables import WikiJob

    scope, store = environment.scope, environment.store
    terminals = ("succeeded", "partial_success", "failed", "needs_confirmation")
    runs = {}
    for key in [
        *(f"row-{s}" for s in terminals),
        *(f"final-{s}" for s in terminals),
        "root-blocked",
        "root-dead_letter",
        "active",
        "failed-child",
        "successful-root-without-final",
        "missing-root",
    ]:
        runs[key] = store.create_run(scope=scope, idempotency_key=key)
    foreign_scope = scope.model_copy(update={"wiki_knowledge_base_id": "other-wiki"})
    foreign = store.create_run(scope=foreign_scope, idempotency_key="foreign")
    root_jobs = {}
    for key in ("root-blocked", "root-dead_letter", "successful-root-without-final"):
        root_jobs[key] = store.enqueue_root(
            scope=scope, run_id=runs[key].run_id, idempotency_key=key
        )
    child = store.enqueue_stage(
        scope=scope,
        run_id=runs["failed-child"].run_id,
        stage_key="source",
        dependency_sha256="a" * 64,
        idempotency_key="failed-child",
    )
    now = datetime.now(UTC)
    with environment.factory() as session, session.begin():
        for index, (key, run) in enumerate(runs.items()):
            row = session.get(tables.ProductRun, run.run_id)
            row.created_at = now + timedelta(seconds=index)
            if key.startswith("row-"):
                row.state = key.removeprefix("row-")
            if key.startswith("final-"):
                session.add(
                    tables.ProductRunFinalization(
                        id=str(uuid4()),
                        run_id=run.run_id,
                        space_id=scope.space_id,
                        state=key.removeprefix("final-"),
                        success_count=1,
                        missing_count=0,
                        failure_count=0,
                        model_call_count=1,
                        usage={},
                        started_at=now,
                        finished_at=now,
                    )
                )
        for key, root in root_jobs.items():
            job = session.get(WikiJob, root.job_id)
            job.state = "succeeded" if key.startswith("successful") else key.removeprefix("root-")
            job.finished_at = now
        session.get(WikiJob, child.job_id).state = "dead_letter"
        session.get(tables.ProductRun, runs["missing-root"].run_id).root_job_id = str(uuid4())
        # Historical payload remains available to explicit readers, never to the scan.
        session.add(
            tables.ProductFieldAttempt(
                id=str(uuid4()),
                run_id=runs["root-blocked"].run_id,
                window_id=str(uuid4()),
                call_id="historical-call",
                tenant_id=scope.tenant_id,
                space_id=scope.space_id,
                entity_id="product",
                field_key="coverage",
                task_sha256="a" * 64,
                cache_key="b" * 64,
                cache_identity={},
                validation_version="v1",
                model_policy_sha256="c" * 64,
                prompt_policy_sha256="d" * 64,
                outcome="verified",
                reason=None,
                validated_result={
                    "value": "original",
                    "evidence": [{"quote": "retained original evidence", "page": 3}],
                },
                raw_ref="original-response",
                attempt=1,
                created_at=now,
                reused_from_attempt_id=None,
            )
        )
    old = store.get_run(scope=scope, run_id=runs["root-blocked"].run_id)
    assert old.state is ProductRunState.FAILED and old.success_count == 1
    statements = []

    def capture(
        _conn: object,
        _cursor: object,
        statement: typing.Any,
        _parameters: object,
        _context: object,
        _many: object,
    ) -> None:
        statements.append(statement.lower())

    event.listen(environment.engine, "before_cursor_execute", capture)
    progression = RecordingProgression()
    pump = runtime_module().ProductRuntimePump(
        store=store,
        jobs=environment.jobs,
        outbox=environment.outbox,
        progression=progression,
        scopes={scope.space_id: scope},
        page_size=1,
    )
    try:
        with monkeypatch.context() as patch:

            def forbidden(*_args: object, **_kwargs: object) -> None:
                pytest.fail("repair scan hydrated a full run before selecting work")

            patch.setattr(store, "_run_snapshot", forbidden)
            for _ in range(5):
                await pump._repair(scope)
        assert not pump.issues
        assert progression.advanced == [
            runs[key].run_id
            for key in ("active", "failed-child", "successful-root-without-final", "missing-root")
        ]
        assert foreign.run_id not in progression.advanced
        assert not any(
            "product_ingestion_field_attempts" in q
            or "product_ingestion_artifacts" in q
            or "product_ingestion_materials" in q
            for q in statements
        )
        assert len(statements) == 5
        assert pump._cursors[scope.space_id] is None
    finally:
        event.remove(environment.engine, "before_cursor_execute", capture)
    # Selection has no business effects and does not hide terminal history.
    assert store.get_run(scope=scope, run_id=old.run_id) == old
    assert old.run_id in {run.run_id for run in store.list_runs(scope=scope)}
