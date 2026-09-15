from __future__ import annotations

# ruff: noqa: F811 -- imported integration fixtures are injected by pytest.
import importlib

import pytest

from insurance_harness.jobs import ClaimedJob
from insurance_harness.product_ingestion.models import ProductRunState
from tests.product_ingestion.test_extraction import source  # noqa: F401
from tests.product_ingestion.test_worker import runtime  # noqa: F401


def module():
    try:
        return importlib.import_module("insurance_harness.product_ingestion.progression")
    except ModuleNotFoundError:
        pytest.fail("short-stage product progression is not implemented")


def test_reused_partial_discovery_remains_partial_with_no_field_gaps():
    from types import SimpleNamespace

    progress_module = module()
    inherited = tuple(
        SimpleNamespace(
            stage_key=key,
            state="partial_success" if key == "synthesis" else "succeeded",
        )
        for key in progress_module.STAGES[:7]
    )
    local = tuple(
        SimpleNamespace(stage_key=key, state="succeeded") for key in progress_module.STAGES[7:]
    )
    store = SimpleNamespace(
        list_stages=lambda **_: local,
        checkpoint_receipt=lambda **_: SimpleNamespace(reused_stages=inherited),
        get_run=lambda **_: SimpleNamespace(failure_count=0, missing_count=0, workflow_version=2),
    )
    progress = progress_module.ProductProgression(
        store=store, jobs=None, read_window_plan=lambda *_: ()
    )
    assert progress.final_state(None, "recovered") == ProductRunState.PARTIAL_SUCCESS


def finish_next(store, jobs, scope, run, state=ProductRunState.SUCCEEDED):
    claim = jobs.claim(space_ids=(scope.space_id,), worker_id="worker")
    assert isinstance(claim, ClaimedJob)
    job = jobs.start(
        space_id=scope.space_id, job_id=claim.job.id, generation=claim.job.lease_generation
    )
    stages = store.list_stages(scope=scope, run_id=run.run_id)
    stage = next(stage for stage in stages if stage.job_id == job.id)
    result = store.prepare_stage_settlement(
        scope=scope,
        run_id=run.run_id,
        stage_id=stage.stage_id,
        job_id=job.id,
        generation=job.lease_generation,
        state=state,
    )
    jobs.report_success(
        space_id=scope.space_id,
        job_id=job.id,
        generation=job.lease_generation,
        events=result.events,
        domain_writes=result.domain_writes,
    )
    return stage.stage_key


def test_admission_and_repeated_advance_enqueue_one_short_stage_no_waiting_root(runtime):
    store, jobs, scope, *_ = runtime
    progress = module().ProductProgression(store=store, jobs=jobs, read_window_plan=lambda *_: ())
    runs = [store.create_run(scope=scope, idempotency_key=f"upload-{i}") for i in range(8)]
    for run in runs:
        progress.advance(scope, run.run_id)
        progress.advance(scope, run.run_id)
        stages = store.list_stages(scope=scope, run_id=run.run_id)
        assert [stage.stage_key for stage in stages] == ["uploads"]
        assert (
            jobs.get_job(space_id=scope.space_id, job_id=stages[0].job_id).job_type
            == "product_stage_uploads"
        )
    # Every claimed coordinator completes rather than occupying capacity waiting for children.
    for run in runs:
        assert finish_next(store, jobs, scope, run) == "uploads"
    for run in runs:
        progress.advance(scope, run.run_id)
        assert [stage.stage_key for stage in store.list_stages(scope=scope, run_id=run.run_id)] == [
            "uploads",
            "source",
        ]


def test_failed_stage_repair_schedules_only_finalizer(runtime):
    store, jobs, scope, *_ = runtime
    progress = module().ProductProgression(store=store, jobs=jobs, read_window_plan=lambda *_: ())
    run = store.create_run(scope=scope, idempotency_key="failed-upload")
    progress.advance(scope, run.run_id)
    finish_next(store, jobs, scope, run, ProductRunState.FAILED)
    progress.advance(scope, run.run_id)
    progress.advance(scope, run.run_id)
    claim = jobs.claim(space_ids=(scope.space_id,), worker_id="worker")
    assert isinstance(claim, ClaimedJob)
    assert claim.job.job_type == "product_ingestion_root"
    assert progress.final_state(scope, run.run_id) == ProductRunState.FAILED
    assert len(store.list_stages(scope=scope, run_id=run.run_id)) == 1


def test_field_plan_is_idempotently_fanned_out_before_aggregate(runtime):
    store, jobs, scope, specs, *_ = runtime
    plan = module().PlannedWindow(window_key="one", dependency_sha256="f" * 64, tasks=specs)
    progress = module().ProductProgression(
        store=store, jobs=jobs, read_window_plan=lambda *_: (plan,)
    )
    run = store.create_run(scope=scope, idempotency_key="window-fanout")
    for expected in ("uploads", "source", "routing", "identity", "field_plan"):
        progress.advance(scope, run.run_id)
        assert finish_next(store, jobs, scope, run) == expected
    progress.advance(scope, run.run_id)
    progress.advance(scope, run.run_id)
    assert len(store.list_windows(scope=scope, run_id=run.run_id)) == 1
    assert "extract" not in [
        stage.stage_key for stage in store.list_stages(scope=scope, run_id=run.run_id)
    ]
    with pytest.raises(ValueError, match="barrier"):
        progress.final_state(scope, run.run_id)


def test_valid_empty_incremental_plan_advances_without_model_windows(runtime):
    store, jobs, scope, *_ = runtime
    progress = module().ProductProgression(store=store, jobs=jobs, read_window_plan=lambda *_: ())
    run = store.create_run(scope=scope, idempotency_key="fully-carried-product")
    for expected in ("uploads", "source", "routing", "identity", "field_plan"):
        progress.advance(scope, run.run_id)
        assert finish_next(store, jobs, scope, run) == expected
    progress.advance(scope, run.run_id)
    assert store.list_windows(scope=scope, run_id=run.run_id) == ()
    assert finish_next(store, jobs, scope, run) == "extract"
    progress.advance(scope, run.run_id)
    assert finish_next(store, jobs, scope, run) == "synthesis"


def test_identity_conflict_remains_needs_confirmation_in_finalizer(runtime):
    from insurance_harness.jobs import classify_failure
    from insurance_harness.product_ingestion.store import needs_confirmation_error

    store, jobs, scope, *_ = runtime
    progress = module().ProductProgression(store=store, jobs=jobs, read_window_plan=lambda *_: ())
    run = store.create_run(scope=scope, idempotency_key="identity-conflict")
    progress.advance(scope, run.run_id)
    claim = jobs.claim(space_ids=(scope.space_id,), worker_id="worker")
    job = jobs.start(
        space_id=scope.space_id, job_id=claim.job.id, generation=claim.job.lease_generation
    )
    jobs.report_failure(
        space_id=scope.space_id,
        job_id=job.id,
        generation=job.lease_generation,
        failure=classify_failure(needs_confirmation_error("PRODUCT_VERSION_CONFLICT")),
    )
    progress.advance(scope, run.run_id)
    assert progress.final_state(scope, run.run_id) == ProductRunState.NEEDS_CONFIRMATION


def test_confirmation_words_in_an_untyped_failure_do_not_change_its_terminal(runtime):
    from insurance_harness.jobs import JobFailure
    from insurance_harness.jobs.models import ErrorClass

    store, jobs, scope, *_ = runtime
    progress = module().ProductProgression(store=store, jobs=jobs, read_window_plan=lambda *_: ())
    run = store.create_run(scope=scope, idempotency_key="untyped-message")
    progress.advance(scope, run.run_id)
    claim = jobs.claim(space_ids=(scope.space_id,), worker_id="worker")
    job = jobs.start(
        space_id=scope.space_id, job_id=claim.job.id, generation=claim.job.lease_generation
    )
    jobs.report_failure(
        space_id=scope.space_id,
        job_id=job.id,
        generation=job.lease_generation,
        failure=JobFailure(
            error_class=ErrorClass.NON_RETRYABLE,
            summary="needs_confirmation: this is only diagnostic text",
        ),
    )
    assert progress.final_state(scope, run.run_id) == ProductRunState.FAILED


def test_field_plan_rejects_duplicate_fields_across_windows_before_any_dispatch(runtime):
    store, jobs, scope, specs, *_ = runtime
    plan = tuple(
        module().PlannedWindow(window_key=str(i), dependency_sha256="f" * 64, tasks=specs)
        for i in range(2)
    )
    progress = module().ProductProgression(store=store, jobs=jobs, read_window_plan=lambda *_: plan)
    run = store.create_run(scope=scope, idempotency_key="duplicate-field")
    for _ in range(5):
        progress.advance(scope, run.run_id)
        finish_next(store, jobs, scope, run)
    with pytest.raises(ValueError, match="duplicate field"):
        progress.advance(scope, run.run_id)
    assert store.list_windows(scope=scope, run_id=run.run_id) == ()


@pytest.mark.parametrize("workflow_version", [1, 2])
def test_preparation_barrier_depends_on_persisted_workflow(workflow_version):
    from types import SimpleNamespace

    legacy = (
        "uploads",
        "source",
        "routing",
        "identity",
        "field_plan",
        "extract",
        "synthesis",
        "compilation",
        "review",
        "publish",
        "verify",
    )
    rows = tuple(SimpleNamespace(stage_key=k, state="succeeded") for k in legacy)
    store = SimpleNamespace(
        list_stages=lambda **_: rows,
        checkpoint_receipt=lambda **_: None,
        get_run=lambda **_: SimpleNamespace(
            workflow_version=workflow_version, failure_count=0, missing_count=0
        ),
    )
    progress = module().ProductProgression(store=store, jobs=None, read_window_plan=lambda *_: ())
    if workflow_version == 1:
        assert progress.final_state(None, "legacy") == ProductRunState.SUCCEEDED
    else:
        with pytest.raises(ValueError, match="barrier"):
            progress.final_state(None, "current")
