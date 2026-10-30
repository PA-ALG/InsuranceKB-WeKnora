"""P1.1 第 10 条 / P1.10 过期 lease 回收与 retry 到期提升（S7f-2c 自 store.py 拆出）。

只在调用方开启的事务内执行；行锁 SKIP LOCKED，批量受 `limit` 约束（review I4）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from insurance_harness.jobs.models import (
    ErrorClass,
    JobRuntimeConfig,
    JobState,
    ReclaimReport,
    ensure_transition,
)
from insurance_harness.jobs.tables import WikiJob

ACTIVE_STATES = (JobState.LEASED.value, JobState.RUNNING.value)
# 回收诊断沿用拆分前的 logger 名，日志订阅方不受影响。
_LOG = logging.getLogger("insurance_harness.jobs.store")


def count_active(session: Session, *, scope: tuple[str, ...] | None) -> int:
    """P1.8 限额分母：全部 `leased | running` 行，不按 lease 是否过期缩小。"""
    conditions = [WikiJob.state.in_(ACTIVE_STATES)]
    if scope is not None:
        conditions.insert(0, WikiJob.space_id.in_(scope))
    return int(
        session.scalar(select(func.count()).select_from(WikiJob).where(*conditions)) or 0
    )

def reclaim_expired(
    session: Session,
    scope: tuple[str, ...] | None,
    now: datetime,
    *,
    limit: int,
    config: JobRuntimeConfig,
) -> ReclaimReport:
    """回收已过期 lease：记 `lease_expired` retryable 并按 `max_attempts`
    路由（P1.4）；每次回收使 generation 单调 +1，被逐出 worker 的写入立即
    stale（review C2）。行锁 SKIP LOCKED，批量受 `limit` 约束（review I4）。

    `scope=None` 表示**不带 Space 过滤**（P1.10 回收可达性合同，
    D-2026-07-27-16）：回收是存储层维护动作，不读写领域数据、不向调用方
    返回任何跨 Space 内容，因此不构成 P1.8 跨 Space fail-closed 的例外。
    """
    conditions = [
        WikiJob.state.in_(ACTIVE_STATES),
        WikiJob.lease_expires_at <= now,
    ]
    if scope is not None:
        conditions.insert(0, WikiJob.space_id.in_(scope))
    expired_rows = (
        session.execute(
            select(WikiJob)
            .where(*conditions)
            .order_by(WikiJob.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    requeued: list[str] = []
    dead_lettered: list[str] = []
    for row in expired_rows:
        if row.lease_expires_at is None:
            raise ValueError("expired job lease timestamp is missing")
        diagnostic = {
            "event": "job_lease_reclaimed", "job_id": row.id,
            "space_id": row.space_id, "generation": row.lease_generation,
            "expired_at": row.lease_expires_at.isoformat(),
            "reclaimed_at": now.isoformat(), "attempt": row.attempt,
        }
        policy = config.policy_for(row.job_type)
        if JobState(row.state) is JobState.LEASED:
            # P1.1 第 10 条（D-2026-07-27-16）：本次投递从未进入 running，
            # worker 未能自报 start，attempt 必须由回收记入——否则
            # claim→start 之间崩溃的任务永不推进 attempt、无界重排队。
            # running 行的 attempt 已由 start 计入，不重复计数。
            row.attempt += 1
        target = JobState.DEAD_LETTER if row.attempt >= policy.max_attempts else JobState.QUEUED
        ensure_transition(JobState(row.state), target, row.id, storage_layer=True)
        row.state = target.value
        row.worker_id = None
        row.lease_expires_at = None
        row.lease_generation += 1
        row.error_class = ErrorClass.RETRYABLE.value
        row.error_summary = "lease_expired"
        if target is JobState.DEAD_LETTER:
            row.finished_at = now
            dead_lettered.append(row.id)
        else:
            row.available_at = now
            requeued.append(row.id)
        # This records the attempted transaction transition; DB state remains
        # authoritative if a later statement/commit fails.
        _LOG.warning(json.dumps(diagnostic), extra=diagnostic)
    return ReclaimReport(
        requeued_job_ids=tuple(requeued), dead_lettered_job_ids=tuple(dead_lettered)
    )

def promote_due_retries(
    session: Session, scope: tuple[str, ...], now: datetime, *, limit: int
) -> None:
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
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    for row in due_rows:
        ensure_transition(JobState(row.state), JobState.QUEUED, row.id, storage_layer=True)
        row.state = JobState.QUEUED.value
