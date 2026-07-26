"""OpenSpec 035 P1.6 事务性 Outbox：同事务追加 + 持久标记 at-least-once 投递。

领域写与事件行只能在同一个调用方事务内出现，存储层不提供绕过事务的
直接外发入口（无双写）。有序 id 只表示分配顺序：较小 id 的行可能在较大
id 已投递后才提交可见，系统不提供跨事务投递顺序保证；消费端只能以
`event_id` 幂等去重。dispatcher 扫描只基于持久化 `dispatched_at` 标记，
已提交行不会因内存水位丢失而永不投递。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.jobs.errors import SpaceScopeError, StaleGenerationError
from insurance_harness.jobs.models import DispatchReport, OutboxEventDraft, OutboxEventView
from insurance_harness.jobs.store import SessionFactory, _aware, database_now
from insurance_harness.jobs.tables import WikiJob, WikiOutboxEvent


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
    """在调用方事务内追加任务事件；scope 与 generation 双重 fenced。

    行随调用方事务一起提交或回滚（P1.6）；旧 generation 一律 typed
    `stale_generation` 拒绝且零行追加（P1.3）。
    """
    job = session.execute(
        select(WikiJob).where(WikiJob.id == job_id, WikiJob.space_id == space_id).with_for_update()
    ).scalar_one_or_none()
    if job is None:
        raise SpaceScopeError()
    if generation != job.lease_generation:
        raise StaleGenerationError(expected=job.lease_generation, actual=generation, job_id=job.id)
    row = WikiOutboxEvent(
        space_id=space_id,
        event_type=draft.event_type,
        payload=dict(draft.payload),
        created_at=now if now is not None else database_now(session),
    )
    if draft.event_id is not None:
        row.event_id = draft.event_id
    session.add(row)
    session.flush()
    return row


class OutboxDispatcher:
    """按有序 id 升序扫描未投递行并 at-least-once 投递（P1.6）。"""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def read_pending(self, *, space_id: str, limit: int = 100) -> tuple[OutboxEventView, ...]:
        """Space scope 内按 id 升序读取未标记投递的已提交行。"""
        if not space_id:
            raise SpaceScopeError("space_id must be a non-empty string")
        return self._read(space_ids=(space_id,), limit=limit)

    def read_pending_all_spaces(self, *, limit: int = 100) -> tuple[OutboxEventView, ...]:
        """显式命名的全局扫描入口（P1.8：全局聚合不作为默认）。"""
        return self._read(space_ids=None, limit=limit)

    def _read(
        self, *, space_ids: tuple[str, ...] | None, limit: int
    ) -> tuple[OutboxEventView, ...]:
        statement = (
            select(WikiOutboxEvent)
            .where(WikiOutboxEvent.dispatched_at.is_(None))
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
        """投递一批未标记行：先投递、成功后各自持久标记。

        投递与标记之间崩溃 ⇒ 行保持未标记、下一轮重投；消费端以
        `event_id` 幂等去重。deliver 抛错即停止本轮，其余行留待重试。
        """
        delivered: list[str] = []
        for event in self.read_pending(space_id=space_id, limit=limit):
            try:
                deliver(event)
            except Exception:
                return DispatchReport(
                    delivered_event_ids=tuple(delivered), failed_event_id=event.event_id
                )
            self.mark_dispatched(space_id=space_id, event_id=event.event_id)
            delivered.append(event.event_id)
        return DispatchReport(delivered_event_ids=tuple(delivered), failed_event_id=None)
