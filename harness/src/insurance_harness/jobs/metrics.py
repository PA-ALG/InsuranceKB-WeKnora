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
from insurance_harness.jobs.store import MAX_SPACE_ID_LENGTH, database_now, validated_text
from insurance_harness.jobs.tables import WikiJob

_SCHEDULABLE_STATES = (JobState.QUEUED.value, JobState.RETRY_WAIT.value)
#: 过期 lease 指标的定义域：卡死形态落在活跃态（P1.9，D-2026-07-27-16）。
_ACTIVE_STATES = (JobState.LEASED.value, JobState.RUNNING.value)


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
    #: 过期但未回收的行数（P1.9，D-2026-07-27-16）：卡死形态落在
    #: `leased | running`，而可调度年龄的定义域是 `{queued, retry_wait}`，
    #: 缺此维度时"整个 Space 卡在过期 lease"与"系统健康"不可区分。
    expired_lease_count: int
    oldest_expired_lease_age_seconds: float | None


@dataclass(frozen=True, slots=True)
class GlobalJobMetrics:
    """显式命名的全局聚合入口；不是任何 Space 查询的默认行为。"""

    state_counts: Mapping[JobState, int]
    queue_depth: int
    retry_wait_count: int
    dead_letter_count: int
    attempt_total: int
    oldest_schedulable_age_seconds: float | None
    expired_lease_count: int
    oldest_expired_lease_age_seconds: float | None


@dataclass(frozen=True, slots=True)
class _Collected:
    """`_collect` 的内部聚合结果（同一事务、同一数据库时钟）。"""

    state_counts: dict[JobState, int]
    attempt_total: int
    oldest_schedulable_age_seconds: float | None
    expired_lease_count: int
    oldest_expired_lease_age_seconds: float | None


def _age_seconds(session: Session, value: object, now: datetime) -> float | None:
    """把 min() 结果规范化为相对数据库时钟的秒数（SQLite 返回原始字符串）。"""
    if value is None:
        return None
    moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    assert isinstance(moment, datetime)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return (now - moment).total_seconds()


def _collect(session: Session, condition: ColumnElement[bool] | None) -> _Collected:
    count_statement = select(WikiJob.state, func.count()).group_by(WikiJob.state)
    attempt_statement = select(func.coalesce(func.sum(WikiJob.attempt), 0))
    oldest_statement = select(func.min(WikiJob.enqueued_at)).where(
        WikiJob.state.in_(_SCHEDULABLE_STATES)
    )
    now = database_now(session)
    expired_condition = (
        WikiJob.state.in_(_ACTIVE_STATES),
        WikiJob.lease_expires_at <= now,
    )
    expired_count_statement = (
        select(func.count()).select_from(WikiJob).where(*expired_condition)
    )
    oldest_expired_statement = select(func.min(WikiJob.lease_expires_at)).where(
        *expired_condition
    )
    if condition is not None:
        count_statement = count_statement.where(condition)
        attempt_statement = attempt_statement.where(condition)
        oldest_statement = oldest_statement.where(condition)
        expired_count_statement = expired_count_statement.where(condition)
        oldest_expired_statement = oldest_expired_statement.where(condition)

    state_counts = {state: 0 for state in JobState}
    for state_value, count in session.execute(count_statement).all():
        state_counts[JobState(state_value)] = int(count)
    attempt_total = int(session.execute(attempt_statement).scalar_one())

    return _Collected(
        state_counts=state_counts,
        attempt_total=attempt_total,
        oldest_schedulable_age_seconds=_age_seconds(
            session, session.execute(oldest_statement).scalar_one_or_none(), now
        ),
        expired_lease_count=int(session.execute(expired_count_statement).scalar_one()),
        oldest_expired_lease_age_seconds=_age_seconds(
            session, session.execute(oldest_expired_statement).scalar_one_or_none(), now
        ),
    )


def space_job_metrics(session: Session, *, space_id: str) -> SpaceJobMetrics:
    """P1.8 scope 规则下的单 Space 指标；只读、零副作用。

    输入合同与写路径一致（P1.9 读路径输入合同，D-2026-07-27-16）：走同一
    `validated_text` 原语，typed `invalid_input`，不泄漏原始驱动异常，也不为
    写路径会拒绝的标识符静默返回"健康"读数。
    """
    validated_text(space_id, "space_id", max_length=MAX_SPACE_ID_LENGTH)
    collected = _collect(session, WikiJob.space_id == space_id)
    return SpaceJobMetrics(
        space_id=space_id,
        state_counts=collected.state_counts,
        queue_depth=collected.state_counts[JobState.QUEUED],
        retry_wait_count=collected.state_counts[JobState.RETRY_WAIT],
        dead_letter_count=collected.state_counts[JobState.DEAD_LETTER],
        attempt_total=collected.attempt_total,
        oldest_schedulable_age_seconds=collected.oldest_schedulable_age_seconds,
        expired_lease_count=collected.expired_lease_count,
        oldest_expired_lease_age_seconds=collected.oldest_expired_lease_age_seconds,
    )


def global_job_metrics(session: Session) -> GlobalJobMetrics:
    """全局聚合的显式独立入口（P1.9）。"""
    collected = _collect(session, None)
    return GlobalJobMetrics(
        state_counts=collected.state_counts,
        queue_depth=collected.state_counts[JobState.QUEUED],
        retry_wait_count=collected.state_counts[JobState.RETRY_WAIT],
        dead_letter_count=collected.state_counts[JobState.DEAD_LETTER],
        attempt_total=collected.attempt_total,
        oldest_schedulable_age_seconds=collected.oldest_schedulable_age_seconds,
        expired_lease_count=collected.expired_lease_count,
        oldest_expired_lease_age_seconds=collected.oldest_expired_lease_age_seconds,
    )
