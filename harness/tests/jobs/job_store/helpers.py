"""OpenSpec 035 deterministic lane：JobStore 存储层合同（SQLite 单线程）的共用配置与行辅助。

真实并发/一致性证据只来自 `integration_postgres` lane（P1.12，见 jobs/job_store_postgres）；
本目录只验证单线程可判定的存储层行为：幂等、状态机路由、fencing、配置化策略、
Decision 幂等与指标查询。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from insurance_harness.jobs import (
    ClaimedJob,
    ErrorClass,
    JobFailure,
    JobRuntimeConfig,
    JobSnapshot,
    JobStore,
    database_now,
)
from insurance_harness.jobs.tables import WikiJob

SessionFactory = Callable[[], Session]


def make_config(**overrides: object) -> JobRuntimeConfig:
    values: dict[str, object] = {
        "lease_seconds": 300.0,
        "heartbeat_interval_seconds": 30.0,
        "max_attempts": 3,
        "backoff_seconds": (0.0,),
        "per_space_concurrency_limit": 8,
        "global_concurrency_limit": 32,
    }
    values.update(overrides)
    return JobRuntimeConfig.model_validate(values)


def make_store(factory: SessionFactory, **overrides: object) -> JobStore:
    return JobStore(factory, make_config(**overrides))


def job_count(factory: SessionFactory) -> int:
    with factory() as session:
        return int(session.scalar(select(func.count()).select_from(WikiJob)) or 0)


def force_expire(factory: SessionFactory, *job_ids: str) -> None:
    """把指定任务的 lease 回拨到过去，模拟 worker 停滞超过 lease 时长。

    D-2026-07-27-16 起 `lease_seconds` 必须严格为正且大于 heartbeat 间隔，
    因此过期场景不再用 `lease_seconds=0`（那会使每个 lease 出生即过期，
    静默作废并发限额）。所有过期脚手架统一走本函数：只回拨 lease，不改
    state/attempt/generation，与真实停滞的可观测状态一致。
    """
    with factory() as session:
        with session.begin():
            for job_id in job_ids:
                session.execute(
                    text(
                        "UPDATE wiki_jobs SET lease_expires_at = "
                        "'2000-01-01 00:00:00.000000+00:00' WHERE id = :job_id"
                    ),
                    {"job_id": job_id},
                )


# --- T5：heartbeat、数据库时钟过期回收与 fencing ---


def _claimed(store: JobStore, space_id: str, worker_id: str = "worker-1") -> JobSnapshot:
    outcome = store.claim(space_ids=(space_id,), worker_id=worker_id)
    assert isinstance(outcome, ClaimedJob)
    return outcome.job


# --- T6：完成事务 = 领域写 + outbox + 状态转换，原子且至多成功一次 ---


def _running_job(store: JobStore, space_id: str = "space-a", key: str = "job-1") -> JobSnapshot:
    store.enqueue(space_id=space_id, job_type="compile", idempotency_key=key)
    claimed = _claimed(store, space_id)
    return store.start(space_id=space_id, job_id=claimed.id, generation=claimed.lease_generation)


# --- T7：backoff/max_attempts 只由配置决定；retry_wait 到期由存储层 requeue ---


def _db_now(factory: SessionFactory) -> datetime:
    with factory() as session:
        return database_now(session)


def _fail_retryable(store: JobStore, job: JobSnapshot, summary: str = "boom") -> JobSnapshot:
    return store.report_failure(
        space_id=job.space_id,
        job_id=job.id,
        generation=job.lease_generation,
        failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary=summary),
    )
