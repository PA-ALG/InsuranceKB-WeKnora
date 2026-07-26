"""OpenSpec 035 P1 JobStore：任务状态与 lease 的唯一存储层写入口。

事务边界（tasks Contract Card）：enqueue、claim、heartbeat、单次状态
转换、「完成 + 领域写 + outbox 追加」各为一个 PostgreSQL 事务。过期判定
只用数据库时钟（P1.3），写权威只看 lease generation；SQLite 仅
deterministic 测试用，真实并发证据只来自 PG lane（P1.12）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from insurance_harness.jobs.errors import (
    IllegalTransitionError,
    SpaceScopeError,
    StaleGenerationError,
)
from insurance_harness.jobs.models import (
    ClaimedJob,
    ClaimOutcome,
    DecisionOutcome,
    EnqueueResult,
    ErrorClass,
    JobFailure,
    JobRuntimeConfig,
    JobSnapshot,
    JobState,
    NoClaimableJob,
    OutboxEventDraft,
    ReclaimReport,
    ensure_transition,
    route_failure,
)
from insurance_harness.jobs.tables import WikiJob

SessionFactory = Callable[[], Session]

_SQLITE_NOW = text("SELECT strftime('%Y-%m-%d %H:%M:%f', 'now')")
_ACTIVE_STATES = (JobState.LEASED.value, JobState.RUNNING.value)
# 稳定 64 位 claim 序列化锁键（pg_advisory_xact_lock；SQLite 单写者无需）。
_CLAIM_LOCK_KEY = int.from_bytes(b"ikb035cl", "big", signed=True)


def database_now(session: Session) -> datetime:
    """读数据库时钟（UTC）；过期与调度判定不得使用 worker 本地时钟。"""
    bind = session.get_bind()
    if bind.dialect.name == "sqlite":
        raw = session.execute(_SQLITE_NOW).scalar_one()
        return datetime.fromisoformat(str(raw)).replace(tzinfo=UTC)
    value = session.execute(select(func.now())).scalar_one()
    assert isinstance(value, datetime)
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite 存储丢失 offset；所有列值均按 UTC 写入，读回补齐 tzinfo。"""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _snapshot(row: WikiJob) -> JobSnapshot:
    available_at = _aware(row.available_at)
    enqueued_at = _aware(row.enqueued_at)
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
        lease_expires_at=_aware(row.lease_expires_at),
        enqueued_at=enqueued_at,
        started_at=_aware(row.started_at),
        finished_at=_aware(row.finished_at),
        error_class=ErrorClass(row.error_class) if row.error_class else None,
        error_summary=row.error_summary,
    )


def _require_text(value: str, name: str) -> str:
    if not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


class JobStore:
    """P1 任务存储层单一入口；调用方不得绕过本类直接改行（P1.1）。"""

    def __init__(self, session_factory: SessionFactory, config: JobRuntimeConfig) -> None:
        self._session_factory = session_factory
        self._config = config

    @property
    def config(self) -> JobRuntimeConfig:
        return self._config

    # --- P1.5 幂等 enqueue ---

    def enqueue(
        self,
        *,
        space_id: str,
        job_type: str,
        idempotency_key: str,
        payload: dict[str, Any] | None = None,
    ) -> EnqueueResult:
        """插入新任务或返回 typed dedup；键由消费方按批次/裁决铸造。"""
        _require_text(space_id, "space_id")
        _require_text(job_type, "job_type")
        _require_text(idempotency_key, "idempotency_key")
        with self._session_factory() as session:
            try:
                with session.begin():
                    now = database_now(session)
                    row = WikiJob(
                        space_id=space_id,
                        job_type=job_type,
                        idempotency_key=idempotency_key,
                        payload=dict(payload or {}),
                        state=JobState.QUEUED.value,
                        attempt=0,
                        lease_generation=0,
                        available_at=now,
                        enqueued_at=now,
                    )
                    session.add(row)
                return EnqueueResult(job=_snapshot(row), deduplicated=False)
            except IntegrityError:
                with session.begin():
                    existing = session.execute(
                        select(WikiJob).where(
                            WikiJob.space_id == space_id,
                            WikiJob.job_type == job_type,
                            WikiJob.idempotency_key == idempotency_key,
                        )
                    ).scalar_one_or_none()
                    if existing is None:
                        raise
                    return EnqueueResult(job=_snapshot(existing), deduplicated=True)

    # --- P1.2 claim（FOR UPDATE SKIP LOCKED） ---

    def claim(self, *, space_ids: Sequence[str], worker_id: str) -> ClaimOutcome:
        """在声明 scope 内领取一个任务；无可领取返回 typed 空结果。"""
        if not space_ids:
            raise ValueError("space_ids must not be empty")
        _require_text(worker_id, "worker_id")
        scope = tuple(dict.fromkeys(space_ids))
        with self._session_factory() as session:
            with session.begin():
                now = database_now(session)
                # 限额检查与领取必须原子；PostgreSQL 以事务级 advisory 锁
                # 串行化「计数 → 领取」，行级仍用 SKIP LOCKED 不互相阻塞。
                if session.get_bind().dialect.name == "postgresql":
                    session.execute(
                        text("SELECT pg_advisory_xact_lock(:key)"), {"key": _CLAIM_LOCK_KEY}
                    )
                # P1.2「或满足 P1.3 的过期回收条件」：claim 先在同事务回收
                # scope 内已过期 lease，被 requeue 的任务随即可领取。
                self._reclaim_locked(session, scope, now)
                # P1.1 第 5 条：backoff 到期的 retry_wait 由存储层按数据库
                # 时钟 requeue（仅此入口，调用方无直接转换 API）。
                self._promote_due_retries(session, scope, now)
                global_active = int(
                    session.scalar(
                        select(func.count())
                        .select_from(WikiJob)
                        .where(WikiJob.state.in_(_ACTIVE_STATES))
                    )
                    or 0
                )
                if global_active >= self._config.global_concurrency_limit:
                    return NoClaimableJob(reason="global_concurrency_limit")
                active_by_space: dict[str, int] = {
                    row_space_id: int(row_count)
                    for row_space_id, row_count in session.execute(
                        select(WikiJob.space_id, func.count())
                        .where(
                            WikiJob.space_id.in_(scope),
                            WikiJob.state.in_(_ACTIVE_STATES),
                        )
                        .group_by(WikiJob.space_id)
                    ).tuples()
                }
                eligible = tuple(
                    space_id
                    for space_id in scope
                    if active_by_space.get(space_id, 0)
                    < self._config.per_space_concurrency_limit
                )
                if not eligible:
                    return NoClaimableJob(reason="empty")
                candidate = session.execute(
                    select(WikiJob)
                    .where(
                        WikiJob.space_id.in_(eligible),
                        WikiJob.state == JobState.QUEUED.value,
                        WikiJob.available_at <= now,
                    )
                    .order_by(WikiJob.enqueued_at, WikiJob.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                ).scalar_one_or_none()
                if candidate is None:
                    return NoClaimableJob(reason="empty")
                ensure_transition(JobState.QUEUED, JobState.LEASED, candidate.id)
                candidate.state = JobState.LEASED.value
                candidate.worker_id = worker_id
                candidate.lease_generation += 1
                candidate.lease_expires_at = now + timedelta(
                    seconds=self._config.lease_seconds
                )
                claimed = _snapshot(candidate)
        return ClaimedJob(job=claimed)

    # --- P1.3 lease、heartbeat 与 fencing ---

    def heartbeat(self, *, space_id: str, job_id: str, generation: int) -> JobSnapshot:
        """延长 lease；仅当 generation 等于当前值且状态 leased|running。"""
        with self._session_factory() as session:
            with session.begin():
                row = self._locked_job(session, space_id, job_id)
                self._check_generation(row, generation)
                state = JobState(row.state)
                if state not in (JobState.LEASED, JobState.RUNNING):
                    raise IllegalTransitionError(state, state, row.id)
                now = database_now(session)
                row.lease_expires_at = now + timedelta(seconds=self._config.lease_seconds)
                return _snapshot(row)

    def start(self, *, space_id: str, job_id: str, generation: int) -> JobSnapshot:
        """`leased → running`：同 generation 的 worker 开始执行，attempt +1。"""
        with self._session_factory() as session:
            with session.begin():
                row = self._locked_job(session, space_id, job_id)
                self._check_generation(row, generation)
                ensure_transition(JobState(row.state), JobState.RUNNING, row.id)
                now = database_now(session)
                row.state = JobState.RUNNING.value
                row.attempt += 1
                row.started_at = now
                return _snapshot(row)

    # --- P1.5/P1.6 完成事务与 P1.4 失败路由 ---

    def report_success(
        self,
        *,
        space_id: str,
        job_id: str,
        generation: int,
        events: Sequence[OutboxEventDraft] = (),
        domain_write: Callable[[Session], None] | None = None,
    ) -> JobSnapshot:
        """完成事务：领域写 + outbox 追加 + `running → succeeded` 同事务。

        本方法是任务领域结果的唯一写入口；fencing + 终态保证至多成功一
        次，重复完成 typed 拒绝且零领域写、零 outbox 追加（P1.5/P1.6）。
        """
        from insurance_harness.jobs.outbox import append_job_event

        with self._session_factory() as session:
            with session.begin():
                row = self._locked_job(session, space_id, job_id)
                self._check_generation(row, generation)
                ensure_transition(JobState(row.state), JobState.SUCCEEDED, row.id)
                now = database_now(session)
                if domain_write is not None:
                    domain_write(session)
                for draft in events:
                    append_job_event(
                        session,
                        space_id=space_id,
                        job_id=job_id,
                        generation=generation,
                        draft=draft,
                        now=now,
                    )
                row.state = JobState.SUCCEEDED.value
                row.worker_id = None
                row.lease_expires_at = None
                row.finished_at = now
                return _snapshot(row)

    def report_failure(
        self, *, space_id: str, job_id: str, generation: int, failure: JobFailure
    ) -> JobSnapshot:
        """按封闭错误分类确定性路由失败（P1.4）；同事务释放 lease。"""
        with self._session_factory() as session:
            with session.begin():
                row = self._locked_job(session, space_id, job_id)
                self._check_generation(row, generation)
                policy = self._config.policy_for(row.job_type)
                target = route_failure(
                    failure.error_class, attempt=row.attempt, max_attempts=policy.max_attempts
                )
                ensure_transition(JobState(row.state), target, row.id)
                now = database_now(session)
                row.state = target.value
                row.worker_id = None
                row.lease_expires_at = None
                row.error_class = failure.error_class.value
                row.error_summary = failure.summary
                if target is JobState.RETRY_WAIT:
                    row.available_at = now + timedelta(
                        seconds=policy.backoff_delay(attempt=row.attempt)
                    )
                if target in (JobState.DEAD_LETTER, JobState.BLOCKED):
                    row.finished_at = now
                return _snapshot(row)

    # --- P1.7 人工 Decision 幂等唤醒 ---

    def resume_after_decision(self, *, space_id: str, job_id: str) -> DecisionOutcome:
        """`awaiting_human → queued` 的唯一入口：当且仅当当前处于
        awaiting_human 才 requeue；重复提交返回 typed duplicate、零行变更。"""
        with self._session_factory() as session:
            with session.begin():
                row = self._locked_job(session, space_id, job_id)
                if JobState(row.state) is not JobState.AWAITING_HUMAN:
                    return DecisionOutcome(job_id=row.id, status="duplicate")
                ensure_transition(JobState.AWAITING_HUMAN, JobState.QUEUED, row.id)
                row.state = JobState.QUEUED.value
                row.available_at = database_now(session)
                return DecisionOutcome(job_id=row.id, status="resumed")

    # --- P1.1 第 10 条 / P1.10：过期 lease 回收 ---

    def reclaim_expired_leases(self, *, space_ids: Sequence[str]) -> ReclaimReport:
        """任何实例可执行的回收：只依赖 PostgreSQL 持久状态与数据库时钟。"""
        if not space_ids:
            raise ValueError("space_ids must not be empty")
        scope = tuple(dict.fromkeys(space_ids))
        with self._session_factory() as session:
            with session.begin():
                now = database_now(session)
                return self._reclaim_locked(session, scope, now)

    def _reclaim_locked(
        self, session: Session, scope: tuple[str, ...], now: datetime
    ) -> ReclaimReport:
        """回收 scope 内已过期 lease：记 `lease_expired` retryable 并按
        `max_attempts` 路由（P1.4）；行锁用 SKIP LOCKED 避免互相阻塞。"""
        expired_rows = (
            session.execute(
                select(WikiJob)
                .where(
                    WikiJob.space_id.in_(scope),
                    WikiJob.state.in_(_ACTIVE_STATES),
                    WikiJob.lease_expires_at <= now,
                )
                .order_by(WikiJob.id)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        requeued: list[str] = []
        dead_lettered: list[str] = []
        for row in expired_rows:
            policy = self._config.policy_for(row.job_type)
            target = (
                JobState.DEAD_LETTER if row.attempt >= policy.max_attempts else JobState.QUEUED
            )
            ensure_transition(JobState(row.state), target, row.id)
            row.state = target.value
            row.worker_id = None
            row.lease_expires_at = None
            row.error_class = ErrorClass.RETRYABLE.value
            row.error_summary = "lease_expired"
            if target is JobState.DEAD_LETTER:
                row.finished_at = now
                dead_lettered.append(row.id)
            else:
                row.available_at = now
                requeued.append(row.id)
        return ReclaimReport(
            requeued_job_ids=tuple(requeued), dead_lettered_job_ids=tuple(dead_lettered)
        )

    @staticmethod
    def _promote_due_retries(session: Session, scope: tuple[str, ...], now: datetime) -> None:
        """`retry_wait → queued`：仅当配置化 backoff 按数据库时钟已到期。"""
        due_rows = (
            session.execute(
                select(WikiJob)
                .where(
                    WikiJob.space_id.in_(scope),
                    WikiJob.state == JobState.RETRY_WAIT.value,
                    WikiJob.available_at <= now,
                )
                .order_by(WikiJob.id)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        for row in due_rows:
            ensure_transition(JobState(row.state), JobState.QUEUED, row.id)
            row.state = JobState.QUEUED.value

    # --- P1.8 scope 化读取 ---

    def get_job(self, *, space_id: str, job_id: str) -> JobSnapshot:
        """按声明 Space 读取任务；不一致或不存在一律 fail closed。"""
        _require_text(space_id, "space_id")
        _require_text(job_id, "job_id")
        with self._session_factory() as session:
            with session.begin():
                row = session.execute(
                    select(WikiJob).where(WikiJob.id == job_id, WikiJob.space_id == space_id)
                ).scalar_one_or_none()
                if row is None:
                    raise SpaceScopeError()
                return _snapshot(row)

    # --- 内部：fenced write guard ---

    def _locked_job(self, session: Session, space_id: str, job_id: str) -> WikiJob:
        """FOR UPDATE 锁定并校验 scope；不一致/不存在 fail closed（P1.8）。"""
        _require_text(space_id, "space_id")
        _require_text(job_id, "job_id")
        row = session.execute(
            select(WikiJob)
            .where(WikiJob.id == job_id, WikiJob.space_id == space_id)
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            raise SpaceScopeError()
        return row

    @staticmethod
    def _check_generation(row: WikiJob, generation: int) -> None:
        """generation 不等于当前值的写入一律 typed `stale_generation`。"""
        if generation != row.lease_generation:
            raise StaleGenerationError(
                expected=row.lease_generation, actual=generation, job_id=row.id
            )
