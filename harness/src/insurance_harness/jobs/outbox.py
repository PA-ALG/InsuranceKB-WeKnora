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
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from insurance_harness.jobs.errors import (
    DuplicateEventError,
    IllegalTransitionError,
    InvalidJobInputError,
    SpaceScopeError,
    StaleGenerationError,
)
from insurance_harness.jobs.models import (
    DispatchReport,
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
    validated_payload,
    validated_text,
)
from insurance_harness.jobs.tables import WikiJob, WikiOutboxEvent

MAX_EVENT_TYPE_LENGTH = 128
MAX_EVENT_ID_LENGTH = 36


def _view(row: WikiOutboxEvent) -> OutboxEventView:
    created_at = _aware(row.created_at)
    assert created_at is not None
    return OutboxEventView(
        id=row.id,
        event_id=row.event_id,
        space_id=row.space_id,
        event_type=row.event_type,
        payload=dict(row.payload),
        created_at=created_at,
        dispatched_at=_aware(row.dispatched_at),
        dispatch_attempts=row.dispatch_attempts,
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
    row = WikiOutboxEvent(
        space_id=space_id,
        event_type=draft.event_type,
        payload=payload,
        created_at=now if now is not None else database_now(session),
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
    """按有序 id 升序扫描未投递行并 at-least-once 投递（P1.6）。

    `max_dispatch_attempts` 只是环境默认值，由部署配置注入：投递失败按行
    持久累计，达上限即 park（不再进入扫描窗口，也不伪装已投递），由运维
    经 `read_parked` 处置（review I10）。
    """

    def __init__(self, session_factory: SessionFactory, *, max_dispatch_attempts: int = 5) -> None:
        if max_dispatch_attempts < 1:
            raise InvalidJobInputError("max_dispatch_attempts must be >= 1")
        self._session_factory = session_factory
        self._max_dispatch_attempts = max_dispatch_attempts

    def read_pending(self, *, space_id: str, limit: int = 100) -> tuple[OutboxEventView, ...]:
        """Space scope 内按 id 升序读取未标记投递、未 park 的已提交行。"""
        validated_text(space_id, "space_id", max_length=MAX_SPACE_ID_LENGTH)
        return self._read(space_ids=(space_id,), limit=limit)

    def read_pending_all_spaces(self, *, limit: int = 100) -> tuple[OutboxEventView, ...]:
        """显式命名的全局扫描入口（P1.8：全局聚合不作为默认）。"""
        return self._read(space_ids=None, limit=limit)

    def read_parked(self, *, space_id: str, limit: int = 100) -> tuple[OutboxEventView, ...]:
        """达投递上限被 park 的毒性事件（未投递、待人工处置）。"""
        validated_text(space_id, "space_id", max_length=MAX_SPACE_ID_LENGTH)
        with self._session_factory() as session:
            rows = (
                session.execute(
                    select(WikiOutboxEvent)
                    .where(
                        WikiOutboxEvent.space_id == space_id,
                        WikiOutboxEvent.dispatched_at.is_(None),
                        WikiOutboxEvent.dispatch_attempts >= self._max_dispatch_attempts,
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
        statement = (
            select(WikiOutboxEvent)
            .where(
                WikiOutboxEvent.dispatched_at.is_(None),
                WikiOutboxEvent.dispatch_attempts < self._max_dispatch_attempts,
            )
            .order_by(WikiOutboxEvent.id)
            .limit(limit)
        )
        if space_ids is not None:
            statement = statement.where(WikiOutboxEvent.space_id.in_(space_ids))
        with self._session_factory() as session:
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
        消费端以 event_id 幂等去重。deliver 抛错不再阻塞本轮后续事件
        （分配序本就不构成语义顺序）：失败按行持久累计
        `dispatch_attempts`，达上限即 park（review I10）。
        """
        validated_text(space_id, "space_id", max_length=MAX_SPACE_ID_LENGTH)
        delivered: list[str] = []
        failed: list[str] = []
        parked: list[str] = []
        cursor = 0
        for _ in range(limit):
            with self._session_factory() as session:
                with session.begin():
                    row = session.execute(
                        select(WikiOutboxEvent)
                        .where(
                            WikiOutboxEvent.space_id == space_id,
                            WikiOutboxEvent.dispatched_at.is_(None),
                            WikiOutboxEvent.dispatch_attempts < self._max_dispatch_attempts,
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
                        if row.dispatch_attempts >= self._max_dispatch_attempts:
                            parked.append(event.event_id)
                        else:
                            failed.append(event.event_id)
                        continue
                    row.dispatched_at = database_now(session)
                    delivered.append(event.event_id)
        return DispatchReport(
            delivered_event_ids=tuple(delivered),
            failed_event_ids=tuple(failed),
            parked_event_ids=tuple(parked),
        )
