"""Derived validation uses the same durable view for display, counts and retries."""

from __future__ import annotations

import typing

# ruff: noqa: F811
import pytest
from sqlalchemy import select

from insurance_harness.product_ingestion.artifact_tables import ProductArtifact
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.checkpoints import field_digest
from insurance_harness.product_ingestion.field_validation import (
    FieldValidationChange,
    FieldValidationReport,
)
from insurance_harness.product_ingestion.models import FieldOutcomeKind
from insurance_harness.product_ingestion.stages import artifact
from tests.product_ingestion.test_store import (
    _make_store,
    _reserve_and_record,
    _run_with_uploads,
    _scope,
    _start_window,
    _task,
    _verified,
    api,  # noqa: F401
    factory,  # noqa: F401
)


def saved_validation(api: typing.Any, factory: typing.Any) -> tuple[typing.Any, ...]:
    store, jobs = _make_store(api, factory)
    scope = _scope(api)
    run, _ = _run_with_uploads(api, store)
    task = _task(api, "benefit")
    _, running = _start_window(api, store, jobs, run_id=run.run_id, window_key="one", tasks=(task,))
    call = _reserve_and_record(
        api,
        store,
        running,
        run_id=run.run_id,
        window_key="one",
        tasks=(task,),
        raw=b"original response",
    )
    store.settle_window(
        scope=scope,
        run_id=run.run_id,
        job_id=running.id,
        generation=running.lease_generation,
        outcomes=(_verified(api, task, raw_ref=call.raw_ref),),
    )
    original = store.list_field_attempts(scope=scope, run_id=run.run_id)[0]
    report = FieldValidationReport(
        source_snapshot_digests={},
        input_digests={original.attempt_id: field_digest(original)},
        counts={"verified": 0, "not_provided": 0, "extraction_failed": 1},
        changes={
            original.attempt_id: FieldValidationChange(
                original_digest=field_digest(original),
                raw_ref=original.raw_ref,
                outcome=FieldOutcomeKind.EXTRACTION_FAILED,
                reason="EVIDENCE_CHARACTER_LOCATION_MISSING",
                validated_result=None,
            )
        },
    )
    stage = store.enqueue_stage(
        scope=scope,
        run_id=run.run_id,
        stage_key="synthesis",
        dependency_sha256="a" * 64,
        idempotency_key="validate",
    )
    claimed = jobs.claim(space_ids=(scope.space_id,), worker_id="validator")
    running = jobs.start(
        space_id=scope.space_id, job_id=claimed.job.id, generation=claimed.job.lease_generation
    )
    assert running.id == stage.job_id
    artifacts = ProductArtifactStore(factory, store)
    writes = artifacts.prepare_artifact_writes(
        scope=scope,
        run_id=run.run_id,
        stage_key="synthesis",
        job_id=running.id,
        generation=running.lease_generation,
        drafts=(
            artifact("field_validation", "product", report.model_dump_json().encode(), "a" * 64),
        ),
    )
    settlement = store.prepare_stage_settlement(
        scope=scope,
        run_id=run.run_id,
        stage_id=stage.stage_id,
        job_id=running.id,
        generation=running.lease_generation,
        state=api.ProductRunState.SUCCEEDED,
    )
    jobs.report_success(
        space_id=scope.space_id,
        job_id=running.id,
        generation=running.lease_generation,
        domain_writes=writes + settlement.domain_writes,
        events=settlement.events,
    )
    return scope, run, original, call


def test_restart_counts_filter_retry_and_original_custody(
    api: typing.Any, factory: typing.Any
) -> None:
    scope, run, original, call = saved_validation(api, factory)
    store, _ = _make_store(api, factory)
    effective = store.list_field_attempts(scope=scope, run_id=run.run_id, field_keys=("benefit",))[
        0
    ]
    assert effective.outcome is FieldOutcomeKind.EXTRACTION_FAILED
    assert effective.validated_result is None and effective.raw_ref == original.raw_ref
    assert store.list_original_field_attempts(scope=scope, run_id=run.run_id) == (original,)
    loaded = store.get_run(scope=scope, run_id=run.run_id)
    assert (loaded.success_count, loaded.failure_count) == (0, 1)
    assert store.get_call(scope=scope, call_id=call.call_id).raw == b"original response"
    child = store.retry_fields(
        scope=scope,
        run_id=run.run_id,
        failed_attempt_ids=(original.attempt_id,),
        idempotency_key="field-retry",
    )
    assert child.retry_field_keys == ("benefit",)
    task = _task(api, "benefit")
    _, running = _start_window(
        api, store, store._jobs, run_id=child.run_id, window_key="explicit-retry", tasks=(task,)
    )
    reservation = store.reserve_window(
        scope=scope,
        run_id=child.run_id,
        job_id=running.id,
        generation=running.lease_generation,
        attempt=running.attempt,
        call_id="retry-call",
        window_key="explicit-retry",
        tasks=(task,),
    )
    assert reservation.action is api.WindowReservationAction.DISPATCH


def test_corrupt_validation_never_falls_back_to_verified(
    api: typing.Any, factory: typing.Any
) -> None:
    scope, run, _, _ = saved_validation(api, factory)
    with factory() as session, session.begin():
        row = session.scalar(select(ProductArtifact).where(ProductArtifact.run_id == run.run_id))
        row.payload = b"{}"
    store, _ = _make_store(api, factory)
    with pytest.raises(ValueError, match="artifact bytes changed"):
        store.list_field_attempts(scope=scope, run_id=run.run_id)
