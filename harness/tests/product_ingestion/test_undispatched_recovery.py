from __future__ import annotations

# ruff: noqa: F401,F811 -- imported pytest fixtures.
import asyncio

import pytest

from insurance_harness.jobs import ClaimedJob, ErrorClass, JobFailure, JobState
from insurance_harness.jobs.tables import WikiJob
from insurance_harness.product_ingestion import models, tables
from tests.product_ingestion.test_identity_recovery import (
    call_args,
    catalog,
    recorded_origin,
    snapshot,
    stage_runtime,
    start_identity,
)
from tests.product_ingestion.test_store import _task


def start(store, scope):
    claim = store._jobs.claim(space_ids=(scope.space_id,), worker_id="undispatched-test")
    assert isinstance(claim, ClaimedJob)
    return store._jobs.start(
        space_id=scope.space_id, job_id=claim.job.id, generation=claim.job.lease_generation
    )


@pytest.fixture
def failed_windows(stage_runtime, recorded_origin):
    scope, store, artifacts, _, execute = stage_runtime
    origin, _, boundary, _, _ = recorded_origin
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    for _ in range(3):
        assert execute(child).state is JobState.SUCCEEDED
    job = start_identity(store, scope, child)
    asyncio.run(boundary.replay_stage_call(**call_args(artifacts, scope, child, job)))
    store._jobs.report_success(
        space_id=scope.space_id, job_id=job.id, generation=job.lease_generation
    )
    store.enqueue_stage(
        scope=scope,
        run_id=child.run_id,
        stage_key="field_plan",
        dependency_sha256="b" * 64,
        idempotency_key="plan:" + child.run_id,
    )
    job = start(store, scope)
    store._jobs.report_success(
        space_id=scope.space_id, job_id=job.id, generation=job.lease_generation
    )
    refs = []
    for key in ("a", "b"):
        tasks = (_task(models, key),)
        window = store.enqueue_window(
            scope=scope,
            run_id=child.run_id,
            stage_key="extract",
            window_key=key,
            dependency_sha256=key * 64,
            tasks=tasks,
        )
        job = start(store, scope)
        assert job.id == window.job_id
        reservation = store.reserve_window(
            scope=scope,
            run_id=child.run_id,
            job_id=job.id,
            generation=job.lease_generation,
            attempt=job.attempt,
            call_id="unstarted-" + key,
            window_key=key,
            tasks=tasks,
        )
        store._jobs.report_failure(
            space_id=scope.space_id,
            job_id=job.id,
            generation=job.lease_generation,
            failure=JobFailure(error_class=ErrorClass.NON_RETRYABLE, summary="lease_expired"),
        )
        refs.append((window, reservation.call))
    store.enqueue_stage(
        scope=scope,
        run_id=child.run_id,
        stage_key="extract",
        dependency_sha256="c" * 64,
        idempotency_key="extract:" + child.run_id,
    )
    job = start(store, scope)
    store._jobs.report_failure(
        space_id=scope.space_id,
        job_id=job.id,
        generation=job.lease_generation,
        failure=JobFailure(
            error_class=ErrorClass.NON_RETRYABLE,
            summary="FIELD_WINDOW_TERMINAL_RESULTS_INCOMPLETE",
        ),
    )
    with store._session_factory() as session, session.begin():
        session.get(tables.ProductRun, child.run_id).root_job_id = job.id
    return store.get_run(scope=scope, run_id=child.run_id), refs


def test_undispatched_failed_windows_recover_without_reclassifying(
    stage_runtime, recorded_origin, failed_windows
):
    scope, store, artifacts, platform, execute = stage_runtime
    failed, _ = failed_windows
    _, original, boundary, _, sent = recorded_origin
    assert store.can_retry_processing(scope=scope, run_id=failed.run_id)
    child = store.retry_processing(
        scope=scope, run_id=failed.run_id, expected_version=failed.version
    )
    assert (
        store.retry_processing(
            scope=scope, run_id=failed.run_id, expected_version=failed.version
        ).run_id
        == child.run_id
    )
    plan = store.processing_recovery_plan(scope=scope, run_id=child.run_id)
    assert plan.identity_call.call_id == original.call_id
    for _ in range(3):
        assert execute(child).state is JobState.SUCCEEDED
    job = start_identity(store, scope, child)
    assert (
        asyncio.run(boundary.replay_stage_call(**call_args(artifacts, scope, child, job)))
        == original
    )
    assert len(sent) == 1 and platform.calls == 3
    assert store.get_run(scope=scope, run_id=failed.run_id) == failed


@pytest.mark.parametrize(
    "drift",
    [
        "active",
        "dispatched",
        "recorded",
        "foreign_call",
        "foreign_run",
        "wrong_job",
        "payload_stage",
        "payload_window",
        "call_job_only",
    ],
)
def test_undispatched_recovery_rejects_nonempty_or_mismatched_work(
    stage_runtime, failed_windows, drift
):
    from sqlalchemy import select

    scope, store, _, _, _ = stage_runtime
    failed, refs = failed_windows
    window, call = refs[0]
    with store._session_factory() as session, session.begin():
        job = session.get(WikiJob, window.job_id)
        row = session.scalar(
            select(tables.ProductModelCall).where(tables.ProductModelCall.call_id == call.call_id)
        )
        if drift == "active":
            job.state = "queued"
        elif drift == "dispatched":
            row.state = "dispatching"
            row.dispatched_at = row.reserved_at
        elif drift == "recorded":
            row.state = "recorded"
            row.raw = b"{}"
            row.recorded_at = row.reserved_at
        elif drift == "foreign_call":
            row.space_id = "foreign"
        elif drift == "foreign_run":
            row.run_id = "foreign-run"
        elif drift == "payload_stage":
            job.payload = {**job.payload, "stage_key": "identity"}
        elif drift == "payload_window":
            job.payload = {**job.payload, "window_key": "another-window"}
        elif drift == "call_job_only":
            row.run_id = "foreign-run"
            row.window_id = "foreign-window"
        else:
            row.job_id = "foreign-job"
    assert not store.can_retry_processing(scope=scope, run_id=failed.run_id)
    with pytest.raises(ValueError):
        store.retry_processing(scope=scope, run_id=failed.run_id, expected_version=failed.version)
