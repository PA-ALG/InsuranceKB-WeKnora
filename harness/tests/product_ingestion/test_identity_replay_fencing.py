"""Replay payload validation must not starve heartbeat or hold the job fence."""

from __future__ import annotations

# ruff: noqa: F401,F811 -- shared actual recorded-call fixtures.
import asyncio
import threading

import pytest
from sqlalchemy import event

from insurance_harness.product_ingestion.artifact_models import ArtifactOrigin
from insurance_harness.product_ingestion.stages import artifact
from tests.product_ingestion.test_identity_recovery import (
    call_args,
    recorded_origin,
    start_identity,
)
from tests.product_ingestion.test_platform import snapshot
from tests.product_ingestion.test_routing import catalog
from tests.product_ingestion.test_stages import stage_runtime


def child_identity(stage_runtime, recorded_origin):
    scope, store, artifacts, _, execute = stage_runtime
    origin, _, boundary, _, _ = recorded_origin
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    for _ in range(3):
        execute(child)
    job = start_identity(store, scope, child)
    return scope, store, artifacts, child, job, boundary


def test_replay_full_validation_runs_off_event_loop(stage_runtime, recorded_origin, monkeypatch):
    scope, _, artifacts, child, job, boundary = child_identity(stage_runtime, recorded_origin)
    original = artifacts._identity_replay_call
    main_thread = threading.get_ident()
    observations = []
    released = threading.Event()

    def validate(*args, **kwargs):
        observations.append(threading.get_ident())
        # A live event loop releases the controlled read; no long wall-clock fixture.
        assert released.wait(1), "full replay validation blocked the event loop"
        return original(*args, **kwargs)

    monkeypatch.setattr(artifacts, "_identity_replay_call", validate)

    async def run():
        replay = asyncio.create_task(
            boundary.replay_stage_call(**call_args(artifacts, scope, child, job))
        )
        await asyncio.sleep(0.01)
        released.set()
        return await replay

    result = asyncio.run(run())
    assert result.raw == recorded_origin[1].raw
    assert observations and all(thread_id != main_thread for thread_id in observations)
    assert len(recorded_origin[4]) == 1


@pytest.mark.parametrize("method", ["get_identity_replay_call", "record_identity_replay"])
def test_replay_verifies_full_sources_before_job_fence(
    stage_runtime, recorded_origin, monkeypatch, method
):
    scope, store, artifacts, child, job, _ = child_identity(stage_runtime, recorded_origin)
    original_fence = store._active_job
    original_sources = store._recovery_source_refs
    fenced_sessions = set()
    reads = []

    def fence(session, *args, **kwargs):
        fenced_sessions.add(id(session))
        return original_fence(session, *args, **kwargs)

    def sources(session, *args, **kwargs):
        assert id(session) not in fenced_sessions, "large source payload read under WikiJob lock"
        reads.append(id(session))
        return original_sources(session, *args, **kwargs)

    monkeypatch.setattr(store, "_active_job", fence)
    monkeypatch.setattr(store, "_recovery_source_refs", sources)
    getattr(artifacts, method)(
        scope=scope,
        run_id=child.run_id,
        job_id=job.id,
        generation=job.lease_generation,
        dependency_sha256="a" * 64,
    )
    assert reads and fenced_sessions == {reads[0]}
    assert set(reads) == fenced_sessions


def test_replay_payload_rows_have_shared_locks_until_fence(stage_runtime, recorded_origin):
    scope, store, artifacts, child, job, _ = child_identity(stage_runtime, recorded_origin)
    observed = []
    session_class = store._session_factory.class_

    def on_select(state):
        if not state.is_select:
            return
        statement = state.statement
        tables = {item.name for item in statement.get_final_froms() if hasattr(item, "name")}
        if tables & {"product_ingestion_artifacts", "product_ingestion_stage_calls"}:
            lock = statement._for_update_arg
            observed.append((tables, lock is not None and lock.read))

    event.listen(session_class, "do_orm_execute", on_select)
    try:
        artifacts.record_identity_replay(
            scope=scope,
            run_id=child.run_id,
            job_id=job.id,
            generation=job.lease_generation,
            dependency_sha256="a" * 64,
        )
    finally:
        event.remove(session_class, "do_orm_execute", on_select)
    # Receipt existence query is short and may use an ordinary read; every source,
    # plan, and original-call query is locked. At least the call and source/plan
    # tables must be present (SQLite cannot emulate PostgreSQL lock contention).
    assert any("product_ingestion_stage_calls" in tables and locked for tables, locked in observed)
    assert sum(locked for _, locked in observed) >= 3


def test_replay_artifact_batch_validates_once_before_fence(
    stage_runtime, recorded_origin, monkeypatch
):
    scope, store, artifacts, child, job, boundary = child_identity(stage_runtime, recorded_origin)
    replay = asyncio.run(boundary.replay_stage_call(**call_args(artifacts, scope, child, job)))
    original = artifacts._identity_replay_call
    original_fence = store._active_job
    validations = []
    fenced = set()

    def fence(session, *args, **kwargs):
        fenced.add(id(session))
        return original_fence(session, *args, **kwargs)

    def validate(session, *args, **kwargs):
        assert id(session) not in fenced, "replay drafts validate full payloads under job lock"
        validations.append(id(session))
        return original(session, *args, **kwargs)

    monkeypatch.setattr(store, "_active_job", fence)
    monkeypatch.setattr(artifacts, "_identity_replay_call", validate)
    drafts = tuple(
        artifact(
            kind,
            "product",
            b'{"fixture":true}',
            "a" * 64,
            origin=ArtifactOrigin.MODEL_REPLAY,
            call_id=replay.call_id,
        )
        for kind in ("identity", "resolved_routing", "identity_adaptation")
    )
    writes = artifacts.prepare_artifact_writes(
        scope=scope,
        run_id=child.run_id,
        stage_key="identity",
        job_id=job.id,
        generation=job.lease_generation,
        drafts=drafts,
    )
    assert len(writes) == 3 and len(validations) == 1
    assert fenced == set(validations)


def test_replay_rejects_changed_source_bytes_even_with_same_stored_sha(
    stage_runtime, recorded_origin
):
    from sqlalchemy import select

    from insurance_harness.product_ingestion.artifact_tables import ProductArtifact

    scope, store, artifacts, child, job, boundary = child_identity(stage_runtime, recorded_origin)
    with store._session_factory() as session, session.begin():
        source = session.scalar(
            select(ProductArtifact).where(
                ProductArtifact.run_id == child.run_id,
                ProductArtifact.artifact_kind == "source_snapshot",
            )
        )
        source.payload += b"changed-without-updating-the-digest"
    with pytest.raises(ValueError, match="sources changed"):
        asyncio.run(boundary.replay_stage_call(**call_args(artifacts, scope, child, job)))
    assert len(recorded_origin[4]) == 1
    assert not artifacts.list_artifacts(
        scope=scope, run_id=child.run_id, artifact_kind="model_replay_receipt"
    )


def test_replay_metrics_use_recorded_identity_not_large_sources(
    stage_runtime, recorded_origin, monkeypatch
):
    scope, store, artifacts, child, job, boundary = child_identity(stage_runtime, recorded_origin)
    replay = asyncio.run(boundary.replay_stage_call(**call_args(artifacts, scope, child, job)))

    def no_source_read(*args, **kwargs):
        pytest.fail("metrics must not reread source snapshot payloads")

    monkeypatch.setattr(store, "_recovery_source_refs", no_source_read)
    metrics = artifacts.get_stage_call_metrics(scope=scope, run_id=child.run_id)
    assert metrics.model_call_count == 0
    assert metrics.reused_model_call_count == 1
    assert metrics.reused_usage == replay.usage
    assert len(recorded_origin[4]) == 1


@pytest.mark.parametrize("boundary_name", ["read", "decode", "routing"])
def test_reused_source_read_and_verification_do_not_block_loop(
    stage_runtime, recorded_origin, snapshot, catalog, monkeypatch, boundary_name
):
    from types import SimpleNamespace

    from insurance_harness.product_ingestion import stages

    scope, store, artifacts, platform, execute = stage_runtime
    origin = recorded_origin[0]
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    execute(child)  # Existing uploaded-source identities are restored first.
    if boundary_name == "routing":
        execute(child)  # Routing consumes the actual durable source checkpoint.
    child = store.get_run(scope=scope, run_id=child.run_id)
    handlers = {}
    monkeypatch.setattr(
        stages, "register_stage_handlers", lambda *a, **kw: handlers.update(kw["handlers"])
    )
    stages.register_source_stages(
        None,
        store=store,
        artifacts=artifacts,
        scopes={scope.space_id: scope},
        platform=platform,
        public_keys=snapshot[3],
        catalog=catalog,
    )
    owner, name = (
        (artifacts, "list_artifacts")
        if boundary_name == "read"
        else (stages, "decode_source_snapshot")
    )
    if boundary_name == "routing":
        owner, name = stages, "read_source_snapshots"
    original = getattr(owner, name)
    released = threading.Event()
    threads = []
    main_thread = threading.get_ident()

    def slow(*args, **kwargs):
        threads.append(threading.get_ident())
        assert released.wait(1), "source checkpoint work blocked the event loop"
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, name, slow)

    async def run():
        task = asyncio.create_task(
            handlers["routing" if boundary_name == "routing" else "source"](
                scope,
                child,
                SimpleNamespace(dependency_sha256="a" * 64),
                None,
            )
        )
        await asyncio.sleep(0.01)
        released.set()
        return await task

    result = asyncio.run(run())
    assert len(result.drafts) == (1 if boundary_name == "routing" else 4)
    assert platform.calls == 3
    assert threads and all(value != main_thread for value in threads)
