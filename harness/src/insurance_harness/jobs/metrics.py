"""OpenSpec 035 P1.9 只读指标查询：确定性、Space scope、不建第二存储。

最老可调度年龄覆盖 `state ∈ {queued, retry_wait}`，以数据库时钟按
`enqueued_at` 计算；失败率/重试率由计数在采样间隔内推导（消费方职责）。
全局聚合是显式命名的独立入口（P1.8）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from insurance_harness.jobs.models import JobState
from insurance_harness.jobs.store import database_now
from insurance_harness.jobs.tables import WikiJob

_SCHEDULABLE_STATES = (JobState.QUEUED.value, JobState.RETRY_WAIT.value)


@dataclass(frozen=True, slots=True)
class SpaceJobMetrics:
    """单一 Space 的确定性任务指标（P1.9）。"""

    space_id: str
    state_counts: Mapping[JobState, int]
    queue_depth: int
    retry_wait_count: int
    dead_letter_count: int
    attempt_total: int
    oldest_schedulable_age_seconds: float | None


@dataclass(frozen=True, slots=True)
class GlobalJobMetrics:
    """显式命名的全局聚合入口；不是任何 Space 查询的默认行为。"""

    state_counts: Mapping[JobState, int]
    queue_depth: int
    retry_wait_count: int
    dead_letter_count: int
    attempt_total: int
    oldest_schedulable_age_seconds: float | None


def _collect(
    session: Session, condition: ColumnElement[bool] | None
) -> tuple[dict[JobState, int], int, float | None]:
    count_statement = select(WikiJob.state, func.count()).group_by(WikiJob.state)
    attempt_statement = select(func.coalesce(func.sum(WikiJob.attempt), 0))
    oldest_statement = select(func.min(WikiJob.enqueued_at)).where(
        WikiJob.state.in_(_SCHEDULABLE_STATES)
    )
    if condition is not None:
        count_statement = count_statement.where(condition)
        attempt_statement = attempt_statement.where(condition)
        oldest_statement = oldest_statement.where(condition)

    state_counts = {state: 0 for state in JobState}
    for state_value, count in session.execute(count_statement).all():
        state_counts[JobState(state_value)] = int(count)
    attempt_total = int(session.execute(attempt_statement).scalar_one())

    oldest_enqueued = session.execute(oldest_statement).scalar_one_or_none()
    age_seconds: float | None = None
    if oldest_enqueued is not None:
        if isinstance(oldest_enqueued, str):  # SQLite min() 返回原始字符串
            oldest_enqueued = datetime.fromisoformat(oldest_enqueued)
        if oldest_enqueued.tzinfo is None:
            oldest_enqueued = oldest_enqueued.replace(tzinfo=UTC)
        age_seconds = (database_now(session) - oldest_enqueued).total_seconds()
    return state_counts, attempt_total, age_seconds


def space_job_metrics(session: Session, *, space_id: str) -> SpaceJobMetrics:
    """P1.8 scope 规则下的单 Space 指标；只读、零副作用。"""
    if not space_id:
        raise ValueError("space_id must be a non-empty string")
    state_counts, attempt_total, age_seconds = _collect(
        session, WikiJob.space_id == space_id
    )
    return SpaceJobMetrics(
        space_id=space_id,
        state_counts=state_counts,
        queue_depth=state_counts[JobState.QUEUED],
        retry_wait_count=state_counts[JobState.RETRY_WAIT],
        dead_letter_count=state_counts[JobState.DEAD_LETTER],
        attempt_total=attempt_total,
        oldest_schedulable_age_seconds=age_seconds,
    )


def global_job_metrics(session: Session) -> GlobalJobMetrics:
    """全局聚合的显式独立入口（P1.9）。"""
    state_counts, attempt_total, age_seconds = _collect(session, None)
    return GlobalJobMetrics(
        state_counts=state_counts,
        queue_depth=state_counts[JobState.QUEUED],
        retry_wait_count=state_counts[JobState.RETRY_WAIT],
        dead_letter_count=state_counts[JobState.DEAD_LETTER],
        attempt_total=attempt_total,
        oldest_schedulable_age_seconds=age_seconds,
    )
