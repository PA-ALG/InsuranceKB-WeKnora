"""OpenSpec 039 wiki-worker 进程外壳：共用的任务、记录型 JobStore 与设置辅助。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from insurance_harness.jobs import (
    ClaimedJob,
    JobFailure,
    JobSnapshot,
    JobState,
    NoClaimableJob,
)
from insurance_harness.service_shell.config import ShellSettings


def _job(number: int, *, job_type: str = "known") -> JobSnapshot:
    now = datetime.now(UTC)
    return JobSnapshot(
        id=f"job-{number}",
        space_id="space-a",
        job_type=job_type,
        idempotency_key=f"key-{number}",
        payload={"number": number},
        state=JobState.LEASED,
        attempt=0,
        lease_generation=1,
        worker_id="worker-a",
        available_at=now,
        lease_expires_at=now,
        enqueued_at=now,
        started_at=None,
        finished_at=None,
        error_class=None,
        error_summary=None,
    )


class RecordingStore:
    def __init__(self, outcomes: list[Any] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.calls: list[tuple[str, str]] = []
        self.failures: list[JobFailure] = []
        self.jobs = {
            outcome.job.id: outcome.job
            for outcome in self.outcomes
            if isinstance(outcome, ClaimedJob)
        }

    def claim(self, *, space_ids: tuple[str, ...], worker_id: str) -> Any:
        self.calls.append(("claim", worker_id))
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        return NoClaimableJob(reason="empty")

    def start(self, *, space_id: str, job_id: str, generation: int) -> JobSnapshot:
        self.calls.append(("start", job_id))
        return self.jobs[job_id]

    def heartbeat(self, *, space_id: str, job_id: str, generation: int) -> JobSnapshot:
        self.calls.append(("heartbeat", job_id))
        return _job(int(job_id.split("-")[1]))

    def report_success(self, **kwargs: Any) -> JobSnapshot:
        job_id = str(kwargs["job_id"])
        self.calls.append(("success", job_id))
        return _job(int(job_id.split("-")[1]))

    def report_failure(
        self,
        *,
        space_id: str,
        job_id: str,
        generation: int,
        failure: JobFailure,
    ) -> JobSnapshot:
        self.calls.append(("failure", job_id))
        self.failures.append(failure)
        return _job(int(job_id.split("-")[1]))


def _store(outcomes: list[Any] | None = None) -> RecordingStore:
    return RecordingStore(outcomes)


def _settings(**overrides: Any) -> ShellSettings:
    values: dict[str, Any] = {
        "postgres_dsn": "postgresql+psycopg://wiki:secret@db/wiki",
        "worker_space_ids": ("space-a",),
        "heartbeat_interval_seconds": 0.01,
        "lease_seconds": 1,
        "claim_poll_interval_seconds": 0.01,
        "transient_backoff_seconds": (0.01, 0.02),
        "drain_deadline_seconds": 0.2,
        "total_shutdown_timeout_seconds": 0.3,
    }
    values.update(overrides)
    return ShellSettings(**values)
