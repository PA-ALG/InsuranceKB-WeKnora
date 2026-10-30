"""P1.8 并发限额准入（S7f-2c 自 store.py 拆出）：claim 在串行化事务内决定可领取的 Space。

计数包含**全部** `leased | running` 行，不按 lease 是否过期缩小分母（P1.8 限额会计合同，
D-2026-07-27-16）；饱和且存在过期行时先做一次有界、无 Space 过滤的回收再重算。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from insurance_harness.jobs.lease_reclaim import ACTIVE_STATES, count_active, reclaim_expired
from insurance_harness.jobs.models import JobRuntimeConfig, NoClaimableJob
from insurance_harness.jobs.tables import WikiJob


def reclaim_when_saturated(session: Session, now: datetime, config: JobRuntimeConfig) -> bool:
    """限额饱和时的反饥饿动作：无 Space 过滤的一次有界回收。

    返回是否确实回收了行（决定调用方是否值得重算计数）。批量受
    `maintenance_batch_size` 约束，因此不会在串行段内产生无界工作。
    """
    report = reclaim_expired(
        session, None, now, limit=config.maintenance_batch_size, config=config
    )
    return bool(report.requeued_job_ids or report.dead_lettered_job_ids)


def _eligible_spaces(
    session: Session, scope: tuple[str, ...], config: JobRuntimeConfig
) -> tuple[str, ...]:
    active_by_space: dict[str, int] = {
        row_space_id: int(row_count)
        for row_space_id, row_count in session.execute(
            select(WikiJob.space_id, func.count())
            .where(
                WikiJob.space_id.in_(scope),
                WikiJob.state.in_(ACTIVE_STATES),
            )
            .group_by(WikiJob.space_id)
        ).tuples()
    }
    return tuple(
        space_id
        for space_id in scope
        if active_by_space.get(space_id, 0) < config.per_space_concurrency_limit
    )


def admit_spaces(
    session: Session, scope: tuple[str, ...], now: datetime, config: JobRuntimeConfig
) -> tuple[str, ...] | NoClaimableJob:
    """返回限额内可领取的 Space；全局或 scope 内全部饱和时返回 typed 拒绝。"""
    global_active = count_active(session, scope=None)
    if global_active >= config.global_concurrency_limit:
        # P1.8 限额会计合同（D-2026-07-27-16）：计数包含过期但未
        # 回收的行——它们的持有者可能仍存活并消耗外部资源。为避免
        # 因此永久饥饿（C1 的动机），饱和时先做一次无 Space 过滤
        # 的有界回收（使过期行被 fenced）再重算，仍饱和才拒绝。
        if reclaim_when_saturated(session, now, config):
            global_active = count_active(session, scope=None)
        if global_active >= config.global_concurrency_limit:
            return NoClaimableJob(reason="global_concurrency_limit")
    eligible = _eligible_spaces(session, scope, config)
    if not eligible:
        # per-Space 饱和同样先尝试有界回收再重算（同上合同）。
        if reclaim_when_saturated(session, now, config):
            eligible = _eligible_spaces(session, scope, config)
    if not eligible:
        # scope 内全部 Space 饱和：不是空队列（review I12）。
        return NoClaimableJob(reason="per_space_concurrency_limit")
    return eligible
