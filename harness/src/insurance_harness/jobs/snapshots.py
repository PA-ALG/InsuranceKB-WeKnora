"""WikiJob 行 → typed `JobSnapshot` / `EnqueueResult`（S7f-2c 自 store.py 拆出）。"""

from __future__ import annotations

from insurance_harness.jobs.models import (
    TERMINAL_STATES,
    EnqueueResult,
    ErrorClass,
    JobSnapshot,
    JobState,
)
from insurance_harness.jobs.store_rules import aware_utc
from insurance_harness.jobs.tables import WikiJob


def job_snapshot(row: WikiJob) -> JobSnapshot:
    available_at = aware_utc(row.available_at)
    enqueued_at = aware_utc(row.enqueued_at)
    assert available_at is not None and enqueued_at is not None
    return JobSnapshot(
        id=row.id,
        space_id=row.space_id,
        job_type=row.job_type,
        idempotency_key=row.idempotency_key,
        payload=dict(row.payload),
        state=JobState(row.state),
        attempt=row.attempt,
        lease_generation=row.lease_generation,
        worker_id=row.worker_id,
        available_at=available_at,
        lease_expires_at=aware_utc(row.lease_expires_at),
        enqueued_at=enqueued_at,
        started_at=aware_utc(row.started_at),
        finished_at=aware_utc(row.finished_at),
        error_class=ErrorClass(row.error_class) if row.error_class else None,
        error_summary=row.error_summary,
    )


def enqueue_result(row: WikiJob, *, deduplicated: bool) -> EnqueueResult:
    snapshot = job_snapshot(row)
    return EnqueueResult(
        job=snapshot,
        deduplicated=deduplicated,
        terminal=snapshot.state in TERMINAL_STATES,
    )
