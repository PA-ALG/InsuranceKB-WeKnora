"""OpenSpec 035 P1.6 事务性 Outbox：同事务追加 + 持久标记 at-least-once 投递。

领域写与事件行只能在同一个调用方事务内出现，存储层不提供绕过事务的
直接外发入口（无双写）。有序 id 只表示分配顺序：较小 id 的行可能在较大
id 已投递后才提交可见，系统不提供跨事务投递顺序保证；消费端只能以
`(space_id, event_id)` 幂等去重。dispatcher 扫描只基于持久化
`dispatched_at` 标记，已提交行不会因内存水位丢失而永不投递；投递时对行
持 `FOR UPDATE SKIP LOCKED`，并发 dispatcher 正常路径零双投递（review
M19），崩溃在标记前仍会重投（at-least-once）。投递失败按持久
`dispatch_attempts` 计数，达上限的毒性事件移出扫描窗口（review I10）。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from insurance_harness.jobs.errors import (
    DuplicateEventError,
    IllegalTransitionError,
    SpaceScopeError,
    StaleGenerationError,
)
from insurance_harness.jobs.models import (
    DispatchReport,
    JobRuntimeConfig,
    JobState,
    OutboxEventDraft,
    OutboxEventView,
)
from insurance_harness.jobs.store import (
    MAX_JOB_ID_LENGTH,
    MAX_SPACE_ID_LENGTH,
    SessionFactory,
    _aware,
    database_now,
    require_active_lease,
    validated_limit,
    validated_payload,
    validated_text,
)
from insurance_harness.jobs.tables import WikiJob, WikiOutboxEvent

MAX_EVENT_TYPE_LENGTH = 128
MAX_EVENT_ID_LENGTH = 36


def _view(row: WikiOutboxEvent) -> OutboxEventView:
    created_at = _aware(row.created_at)
    assert created_at is not None
    next_dispatch_at = _aware(row.next_dispatch_at)
    assert next_dispatch_at is not None
    return OutboxEventView(
        id=row.id,
        event_id=row.event_id,
        space_id=row.space_id,
        event_type=row.event_type,
        payload=dict(row.payload),
        created_at=created_at,
        dispatched_at=_aware(row.dispatched_at),
        dispatch_attempts=row.dispatch_attempts,
        next_dispatch_at=next_dispatch_at,
    )


def append_job_event(
    session: Session,
    *,
    space_id: str,
    job_id: str,
    generation: int,
    draft: OutboxEventDraft,
    now: datetime | None = None,
) -> WikiOutboxEvent:
    """在调用方事务内追加任务事件；scope、generation 与状态三重 fenced。

    行随调用方事务一起提交或回滚（P1.6）；旧 generation typed
    `stale_generation` 拒绝；任务不处于 `running`（含终态与回收后的
    queued）一律 typed 拒绝——事件只能产生于完成事务所在的执行期
    （review C2）。同一 Space 重复 event_id typed `duplicate_event_id`。
    """
    validated_text(space_id, "space_id", max_length=MAX_SPACE_ID_LENGTH)
    validated_text(job_id, "job_id", max_length=MAX_JOB_ID_LENGTH)
    validated_text(draft.event_type, "event_type", max_length=MAX_EVENT_TYPE_LENGTH)
    if draft.event_id is not None:
        validated_text(draft.event_id, "event_id", max_length=MAX_EVENT_ID_LENGTH)
    payload = validated_payload(draft.payload, "event payload")
    job = session.execute(
        select(WikiJob).where(WikiJob.id == job_id, WikiJob.space_id == space_id).with_for_update()
    ).scalar_one_or_none()
    if job is None:
        raise SpaceScopeError()
    if generation != job.lease_generation:
        raise StaleGenerationError(expected=job.lease_generation, actual=generation, job_id=job.id)
    state = JobState(job.state)
    if state is not JobState.RUNNING:
        raise IllegalTransitionError(state, state, job.id)
    require_active_lease(session, job)
    created_at = now if now is not None else database_now(session)
    row = WikiOutboxEvent(
        space_id=space_id,
        event_type=draft.event_type,
        payload=payload,
        created_at=created_at,
        # 新事件立即可投（P1.6）：退避只在失败后推迟。
        next_dispatch_at=created_at,
    )
    if draft.event_id is not None:
        row.event_id = draft.event_id
    session.add(row)
    try:
        session.flush()
    except IntegrityError as error:
        raise DuplicateEventError(
            f"event_id already exists in this space: {row.event_id!r}"
        ) from error
    return row


class OutboxDispatcher:
    """按有序 id 升序扫描到期未投递行并 at-least-once 投递（P1.6）。

    投递让位机制是**持久退避**（P1.6 投递可恢复性合同，D-2026-07-27-16）：
    失败时递增持久 `dispatch_attempts` 并按配置化 `dispatch_backoff_seconds`
    推迟 `next_dispatch_at`；扫描条件为 `dispatched_at IS NULL AND
    next_dispatch_at <= 数据库当前时间`。已提交行**永不**因失败计数被移出
    扫描窗口——瞬时消费端不可用与永久毒性负载在该计数上不可区分，硬上限会
    把前者误判为后者并静默丢弃健康事件。毒性事件的熔断/隔离/人工处置属消费方
    reconciliation（proposal 非目标），不在 P1 内实现为"永不再投"的终态。
    退避参数只来自 `JobRuntimeConfig`，不硬编码于本构造函数。
    """

    def __init__(self, session_factory: SessionFactory, config: JobRuntimeConfig) -> None:
        self._session_factory = session_factory
        self._config = config

    def read_pending(self, *, space_id: str, limit: int = 100) -> tuple[OutboxEventView, ...]:
        """Space scope 内按 id 升序读取未投递且退避已到期的已提交行。"""
        validated_text(space_id, "space_id", max_length=MAX_SPACE_ID_LENGTH)
        return self._read(space_ids=(space_id,), limit=limit)

    def read_pending_all_spaces(self, *, limit: int = 100) -> tuple[OutboxEventView, ...]:
        """显式命名的全局扫描入口（P1.8：全局聚合不作为默认）。"""
        return self._read(space_ids=None, limit=limit)

    def read_backed_off(
        self, *, space_id: str, min_attempts: int = 1, limit: int = 100
    ) -> tuple[OutboxEventView, ...]:
        """运维视图：已失败 ≥ `min_attempts` 次、仍未投递的行。

        它是**可观测面**而非坟墓：这些行仍在扫描集合内、退避到期后继续重投。
        取代原 `read_parked`（后者语义是"永不再投"，违反 P1.6）。
        """
        validated_text(space_id, "space_id", max_length=MAX_SPACE_ID_LENGTH)
        validated_limit(min_attempts, "min_attempts")
        validated_limit(limit, "limit")
        with self._session_factory() as session:
            rows = (
                session.execute(
                    select(WikiOutboxEvent)
                    .where(
                        WikiOutboxEvent.space_id == space_id,
                        WikiOutboxEvent.dispatched_at.is_(None),
                        WikiOutboxEvent.dispatch_attempts >= min_attempts,
                    )
                    .order_by(WikiOutboxEvent.id)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return tuple(_view(row) for row in rows)

    def _read(
        self, *, space_ids: tuple[str, ...] | None, limit: int
    ) -> tuple[OutboxEventView, ...]:
        validated_limit(limit, "limit")
        with self._session_factory() as session:
            now = database_now(session)
            statement = (
                select(WikiOutboxEvent)
                .where(
                    WikiOutboxEvent.dispatched_at.is_(None),
                    WikiOutboxEvent.next_dispatch_at <= now,
                )
                .order_by(WikiOutboxEvent.id)
                .limit(limit)
            )
            if space_ids is not None:
                statement = statement.where(WikiOutboxEvent.space_id.in_(space_ids))
            rows = session.execute(statement).scalars().all()
            return tuple(_view(row) for row in rows)

    def mark_dispatched(self, *, space_id: str, event_id: str) -> OutboxEventView:
        """持久标记投递完成；重复标记幂等返回既有标记（at-least-once）。"""
        validated_text(space_id, "space_id", max_length=MAX_SPACE_ID_LENGTH)
        validated_text(event_id, "event_id", max_length=MAX_EVENT_ID_LENGTH)
        with self._session_factory() as session:
            with session.begin():
                row = session.execute(
                    select(WikiOutboxEvent)
                    .where(
                        WikiOutboxEvent.event_id == event_id,
                        WikiOutboxEvent.space_id == space_id,
                    )
                    .with_for_update()
                ).scalar_one_or_none()
                if row is None:
                    raise SpaceScopeError()
                if row.dispatched_at is None:
                    row.dispatched_at = database_now(session)
                return _view(row)

    def dispatch_pending(
        self,
        *,
        space_id: str,
        deliver: Callable[[OutboxEventView], None],
        limit: int = 100,
    ) -> DispatchReport:
        """投递一批未标记行：逐行「锁定 → 投递 → 持久标记」各自一个事务。

        行锁（FOR UPDATE SKIP LOCKED）使并发 dispatcher 正常路径零双投递
        （review M19）；投递成功与标记之间崩溃 ⇒ 行未标记、下一轮重投，
        消费端以 event_id 幂等去重。deliver 抛错不阻塞本轮后续事件（分配序
        本就不构成语义顺序）：失败递增持久 `dispatch_attempts` 并按配置化
        退避推迟 `next_dispatch_at`——**只让位，不出局**（P1.6，D-16）。
        """
        validated_text(space_id, "space_id", max_length=MAX_SPACE_ID_LENGTH)
        validated_limit(limit, "limit")
        delivered: list[str] = []
        failed: list[str] = []
        cursor = 0
        for _ in range(limit):
            with self._session_factory() as session:
                with session.begin():
                    now = database_now(session)
                    row = session.execute(
                        select(WikiOutboxEvent)
                        .where(
                            WikiOutboxEvent.space_id == space_id,
                            WikiOutboxEvent.dispatched_at.is_(None),
                            WikiOutboxEvent.next_dispatch_at <= now,
                            WikiOutboxEvent.id > cursor,
                        )
                        .order_by(WikiOutboxEvent.id)
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    ).scalar_one_or_none()
                    if row is None:
                        break
                    cursor = row.id
                    event = _view(row)
                    try:
                        deliver(event)
                    except Exception:
                        row.dispatch_attempts += 1
                        row.next_dispatch_at = now + timedelta(
                            seconds=self._config.dispatch_backoff_delay(
                                attempts=row.dispatch_attempts
                            )
                        )
                        failed.append(event.event_id)
                        continue
                    row.dispatched_at = now
                    delivered.append(event.event_id)
        return DispatchReport(
            delivered_event_ids=tuple(delivered),
            failed_event_ids=tuple(failed),
        )
