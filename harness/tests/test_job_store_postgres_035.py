"""OpenSpec 035 P1.12：JobStore/Outbox 在真实 PostgreSQL 16 的并发合同。

覆盖 033 §16.2 对 P1 的义务：多 worker 并发单领、lease 过期接管、迟到
（旧 generation）worker 全写路径拒绝、完成事务 + outbox 原子性（含崩溃/
中断模拟），以及限额、跨 Space fail closed、毒性任务回收有界、Decision
幂等与指标查询。
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from insurance_harness.jobs import (
    OWNED_TABLES,
    ClaimedJob,
    DomainWriteSpec,
    DomainWriteViolationError,
    ErrorClass,
    IllegalTransitionError,
    InvalidJobInputError,
    JobFailure,
    JobRuntimeConfig,
    JobState,
    JobStore,
    LeaseExpiredError,
    NoClaimableJob,
    OutboxDispatcher,
    OutboxEventDraft,
    SpaceScopeError,
    StaleGenerationError,
    database_now,
    global_job_metrics,
    space_job_metrics,
)

# `append_job_event` 已不在公共出口（P1.6 事件追加边界，D-2026-07-27-16）：
# 只能在完成事务内追加。测试直接引内部模块以验证该内部合同。
from insurance_harness.jobs.outbox import append_job_event
from insurance_harness.jobs.tables import WikiJob, WikiOutboxEvent

HARNESS_ROOT = Path(__file__).resolve().parents[1]
TEST_POSTGRES_ENV = "HARNESS_TEST_POSTGRES_URL"
FUTURE_TIMEOUT_S = 30
CONNECT_ARGS: dict[str, object] = {
    "connect_timeout": 10,
    "options": "-cstatement_timeout=20000 -clock_timeout=10000",
}

SessionFactory = Callable[[], Session]


@dataclass(frozen=True)
class PostgresRuntime:
    engine: Engine
    factory: sessionmaker[Session]


def _alembic_config(url: URL) -> Config:
    config = Config(str(HARNESS_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(HARNESS_ROOT / "migrations"))
    rendered = url.update_query_dict(
        {
            "connect_timeout": "10",
            "options": "-cstatement_timeout=20000 -clock_timeout=10000",
        }
    ).render_as_string(hide_password=False)
    config.set_main_option("sqlalchemy.url", rendered.replace("%", "%%"))
    return config


def _fresh_runtime() -> Iterator[PostgresRuntime]:
    configured_url = os.getenv(TEST_POSTGRES_ENV)
    if not configured_url:
        pytest.fail(f"{TEST_POSTGRES_ENV} is required for integration_postgres")
    base_url = make_url(configured_url).set(drivername="postgresql+psycopg")
    database_name = f"insurancekb_035_{uuid.uuid4().hex}"
    database_url = base_url.set(database=database_name)
    admin_engine = create_engine(
        base_url, future=True, isolation_level="AUTOCOMMIT", connect_args=CONNECT_ARGS
    )
    engine: Engine | None = None
    database_created = False
    had_override = "HARNESS_DB_URL" in os.environ
    previous_override = os.environ.pop("HARNESS_DB_URL", None)
    try:
        with admin_engine.connect() as connection:
            version = connection.exec_driver_sql("SHOW server_version_num").scalar_one()
            assert str(version).startswith("16")
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}" TEMPLATE template0')
        database_created = True
        command.upgrade(_alembic_config(database_url), "head")
        engine = create_engine(database_url, future=True, connect_args=CONNECT_ARGS)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0015"
        yield PostgresRuntime(
            engine=engine,
            factory=sessionmaker(bind=engine, expire_on_commit=False, future=True),
        )
    finally:
        if had_override:
            assert previous_override is not None
            os.environ["HARNESS_DB_URL"] = previous_override
        if engine is not None:
            engine.dispose()
        if database_created:
            with admin_engine.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                    ),
                    {"database_name": database_name},
                )
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
        admin_engine.dispose()


@pytest.fixture(scope="module")
def postgres_runtime() -> Iterator[PostgresRuntime]:
    yield from _fresh_runtime()


@pytest.fixture
def isolated_postgres_runtime() -> Iterator[PostgresRuntime]:
    """函数级独立数据库：供依赖全局计数（全局限额）的断言使用。"""
    yield from _fresh_runtime()


def _config(**overrides: object) -> JobRuntimeConfig:
    values: dict[str, object] = {
        "lease_seconds": 300.0,
        "heartbeat_interval_seconds": 30.0,
        "max_attempts": 3,
        "backoff_seconds": (0.0,),
        "per_space_concurrency_limit": 64,
        "global_concurrency_limit": 256,
    }
    values.update(overrides)
    return JobRuntimeConfig.model_validate(values)


def _store(runtime: PostgresRuntime, **overrides: object) -> JobStore:
    return JobStore(runtime.factory, _config(**overrides))


def _force_expire(runtime: PostgresRuntime, *job_ids: str) -> None:
    """把指定任务的 lease 回拨到过去，模拟 worker 停滞超过 lease 时长。

    D-2026-07-27-16 起 `lease_seconds` 必须严格为正且大于 heartbeat 间隔
    （`0` 会使每个 lease 出生即过期、静默作废并发限额），因此过期脚手架
    统一走本函数：只回拨 lease，不改 state/attempt/generation。
    """
    with runtime.factory() as session:
        with session.begin():
            for job_id in job_ids:
                session.execute(
                    text(
                        "UPDATE wiki_jobs SET lease_expires_at = "
                        "timestamptz '2000-01-01 00:00:00+00' WHERE id = :job_id"
                    ),
                    {"job_id": job_id},
                )


def _space(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _job_states(runtime: PostgresRuntime, space_id: str) -> dict[str, str]:
    with runtime.factory() as session:
        rows = session.execute(
            select(WikiJob.id, WikiJob.state).where(WikiJob.space_id == space_id)
        ).all()
    return {job_id: state for job_id, state in rows}


# --- T3：并发幂等 enqueue 与 ≥8 连接并发单领 ---


@pytest.mark.integration_postgres
def test_p1_5_concurrent_duplicate_enqueue_creates_exactly_one_row(
    postgres_runtime: PostgresRuntime,
) -> None:
    store = _store(postgres_runtime)
    space_id = _space("dedup")
    barrier = threading.Barrier(8)

    def race() -> bool:
        barrier.wait(timeout=10)
        return store.enqueue(
            space_id=space_id,
            job_type="compile",
            idempotency_key="revision-1",
        ).deduplicated

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = [
            future.result(timeout=FUTURE_TIMEOUT_S)
            for future in [executor.submit(race) for _ in range(8)]
        ]

    assert outcomes.count(False) == 1
    assert outcomes.count(True) == 7
    with postgres_runtime.factory() as session:
        count = session.scalar(
            select(func.count()).select_from(WikiJob).where(WikiJob.space_id == space_id)
        )
    assert count == 1


@pytest.mark.integration_postgres
def test_p1_2_eight_workers_claim_each_job_exactly_once_until_typed_empty(
    postgres_runtime: PostgresRuntime,
) -> None:
    store = _store(postgres_runtime)
    space_id = _space("claim")
    total_jobs = 24
    for index in range(total_jobs):
        store.enqueue(space_id=space_id, job_type="compile", idempotency_key=f"job-{index}")

    barrier = threading.Barrier(8)

    def drain(worker_index: int) -> list[tuple[str, int]]:
        claims: list[tuple[str, int]] = []
        barrier.wait(timeout=10)
        while True:
            outcome = store.claim(space_ids=(space_id,), worker_id=f"worker-{worker_index}")
            if isinstance(outcome, NoClaimableJob):
                assert outcome.reason == "empty"
                return claims
            claims.append((outcome.job.id, outcome.job.lease_generation))

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(drain, index) for index in range(8)]
        results = [future.result(timeout=FUTURE_TIMEOUT_S) for future in futures]

    claimed = [claim for chunk in results for claim in chunk]
    assert len(claimed) == total_jobs
    assert len({job_id for job_id, _generation in claimed}) == total_jobs
    assert all(generation == 1 for _job_id, generation in claimed)
    assert all(state == "leased" for state in _job_states(postgres_runtime, space_id).values())


@pytest.mark.integration_postgres
def test_p1_2_claim_skips_externally_locked_row_without_blocking(
    postgres_runtime: PostgresRuntime,
) -> None:
    store = _store(postgres_runtime)
    space_id = _space("skip")
    first = store.enqueue(space_id=space_id, job_type="compile", idempotency_key="job-1").job
    second = store.enqueue(space_id=space_id, job_type="compile", idempotency_key="job-2").job

    with postgres_runtime.factory() as blocker:
        locked = blocker.execute(
            select(WikiJob.id).where(WikiJob.id == first.id).with_for_update()
        ).scalar_one()
        assert locked == first.id

        outcome = store.claim(space_ids=(space_id,), worker_id="worker-b")
        assert isinstance(outcome, ClaimedJob)
        assert outcome.job.id == second.id
        assert outcome.job.state is JobState.LEASED
        blocker.rollback()


# --- T4：并发下 per-Space 限额不被突破，饱和 Space 不阻塞其他 Space ---


@pytest.mark.integration_postgres
def test_p1_8_concurrent_claims_never_exceed_per_space_limit(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("limit")
    store = _store(postgres_runtime, per_space_concurrency_limit=2)
    for index in range(6):
        store.enqueue(space_id=space_id, job_type="compile", idempotency_key=f"job-{index}")

    barrier = threading.Barrier(8)

    def race(worker_index: int) -> int:
        barrier.wait(timeout=10)
        outcome = store.claim(space_ids=(space_id,), worker_id=f"worker-{worker_index}")
        return 1 if isinstance(outcome, ClaimedJob) else 0

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(race, index) for index in range(8)]
        wins = sum(future.result(timeout=FUTURE_TIMEOUT_S) for future in futures)

    assert wins == 2
    states = list(_job_states(postgres_runtime, space_id).values())
    assert states.count("leased") == 2
    assert states.count("queued") == 4


@pytest.mark.integration_postgres
def test_p1_8_saturated_space_does_not_block_sibling_space(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_a = _space("sat-a")
    space_b = _space("sat-b")
    store = _store(postgres_runtime, per_space_concurrency_limit=1)
    store.enqueue(space_id=space_a, job_type="compile", idempotency_key="a-0")
    store.enqueue(space_id=space_a, job_type="compile", idempotency_key="a-1")
    store.enqueue(space_id=space_b, job_type="compile", idempotency_key="b-0")

    first = store.claim(space_ids=(space_a, space_b), worker_id="worker-1")
    assert isinstance(first, ClaimedJob)
    assert first.job.space_id == space_a

    second = store.claim(space_ids=(space_a, space_b), worker_id="worker-1")
    assert isinstance(second, ClaimedJob)
    assert second.job.space_id == space_b

    third = store.claim(space_ids=(space_a, space_b), worker_id="worker-1")
    assert isinstance(third, NoClaimableJob)
    assert _job_states(postgres_runtime, space_a)[
        store.enqueue(space_id=space_a, job_type="compile", idempotency_key="a-1").job.id
    ] == "queued"


# --- T5：lease 过期接管与旧 generation heartbeat/转换拒绝 ---


def _claim_one(store: JobStore, space_id: str, worker_id: str) -> str:
    outcome = store.claim(space_ids=(space_id,), worker_id=worker_id)
    assert isinstance(outcome, ClaimedJob)
    return outcome.job.id


@pytest.mark.integration_postgres
def test_p1_3_expired_lease_is_reclaimed_and_retaken_with_greater_generation(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("takeover")
    expiring = _store(postgres_runtime)
    healthy = _store(postgres_runtime, lease_seconds=300.0)
    expiring.enqueue(space_id=space_id, job_type="compile", idempotency_key="job-1")

    stale = expiring.claim(space_ids=(space_id,), worker_id="worker-a")
    assert isinstance(stale, ClaimedJob)
    expiring.start(
        space_id=space_id, job_id=stale.job.id, generation=stale.job.lease_generation
    )
    _force_expire(postgres_runtime, stale.job.id)

    takeover = healthy.claim(space_ids=(space_id,), worker_id="worker-b")
    assert isinstance(takeover, ClaimedJob)
    assert takeover.job.id == stale.job.id
    assert takeover.job.lease_generation > stale.job.lease_generation
    assert takeover.job.worker_id == "worker-b"
    assert takeover.job.error_summary == "lease_expired"

    with pytest.raises(StaleGenerationError):
        healthy.heartbeat(
            space_id=space_id, job_id=stale.job.id, generation=stale.job.lease_generation
        )
    with pytest.raises(StaleGenerationError):
        healthy.start(
            space_id=space_id, job_id=stale.job.id, generation=stale.job.lease_generation
        )

    current = healthy.get_job(space_id=space_id, job_id=stale.job.id)
    assert current.state is JobState.LEASED
    assert current.lease_generation == takeover.job.lease_generation
    assert current.worker_id == "worker-b"


# --- T6：完成事务 + outbox 原子性（含注入中断）与重复完成拒绝 ---


def _outbox_count(runtime: PostgresRuntime, space_id: str) -> int:
    with runtime.factory() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(WikiOutboxEvent)
                .where(WikiOutboxEvent.space_id == space_id)
            )
            or 0
        )


def _start_running(store: JobStore, space_id: str, key: str, worker_id: str) -> tuple[str, int]:
    store.enqueue(space_id=space_id, job_type="compile", idempotency_key=key)
    outcome = store.claim(space_ids=(space_id,), worker_id=worker_id)
    assert isinstance(outcome, ClaimedJob)
    job = store.start(
        space_id=space_id, job_id=outcome.job.id, generation=outcome.job.lease_generation
    )
    return job.id, job.lease_generation


@pytest.mark.integration_postgres
def test_p1_6_completion_interrupt_before_commit_leaves_neither_row(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("atomic")
    domain_table = f"domain_{uuid.uuid4().hex[:12]}"
    with postgres_runtime.engine.begin() as connection:
        connection.exec_driver_sql(
            f'CREATE TABLE "{domain_table}" (job_id TEXT PRIMARY KEY)'
        )
    store = _store(postgres_runtime)
    job_id, generation = _start_running(store, space_id, "job-1", "worker-a")

    # 声明式领域写（P1.5，D-2026-07-27-16）：存储层自己执行，调用方无句柄。
    domain_writes = (DomainWriteSpec(table=domain_table, values={"job_id": job_id}),)

    def interrupt(_session: Session) -> None:
        raise RuntimeError("inject-commit-crash-035")

    sqlalchemy_event.listen(postgres_runtime.factory, "before_commit", interrupt)
    try:
        with pytest.raises(RuntimeError, match="inject-commit-crash-035"):
            store.report_success(
                space_id=space_id,
                job_id=job_id,
                generation=generation,
                events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
                domain_writes=domain_writes,
            )
    finally:
        sqlalchemy_event.remove(postgres_runtime.factory, "before_commit", interrupt)

    with postgres_runtime.factory() as session:
        assert session.scalar(text(f'SELECT count(*) FROM "{domain_table}"')) == 0
    assert _outbox_count(postgres_runtime, space_id) == 0
    assert store.get_job(space_id=space_id, job_id=job_id).state is JobState.RUNNING

    # 重放同一完成事务：领域行与 outbox 事件各恰好出现一次。
    replay = store.report_success(
        space_id=space_id,
        job_id=job_id,
        generation=generation,
        events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
        domain_writes=domain_writes,
    )
    assert replay.state is JobState.SUCCEEDED
    with postgres_runtime.factory() as session:
        assert session.scalar(text(f'SELECT count(*) FROM "{domain_table}"')) == 1
    assert _outbox_count(postgres_runtime, space_id) == 1

    with pytest.raises(IllegalTransitionError):
        store.report_success(
            space_id=space_id,
            job_id=job_id,
            generation=generation,
            events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
            domain_writes=domain_writes,
        )
    with postgres_runtime.factory() as session:
        assert session.scalar(text(f'SELECT count(*) FROM "{domain_table}"')) == 1
    assert _outbox_count(postgres_runtime, space_id) == 1


@pytest.mark.integration_postgres
def test_p1_3_late_worker_every_write_path_is_fenced_after_takeover(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("fence")
    expiring = _store(postgres_runtime)
    healthy = _store(postgres_runtime, lease_seconds=300.0)
    job_id, old_generation = _start_running(expiring, space_id, "job-1", "worker-a")
    _force_expire(postgres_runtime, job_id)

    takeover = healthy.claim(space_ids=(space_id,), worker_id="worker-b")
    assert isinstance(takeover, ClaimedJob)
    assert takeover.job.id == job_id
    new_generation = takeover.job.lease_generation
    assert new_generation > old_generation

    with pytest.raises(StaleGenerationError):
        healthy.heartbeat(space_id=space_id, job_id=job_id, generation=old_generation)
    with pytest.raises(StaleGenerationError):
        healthy.start(space_id=space_id, job_id=job_id, generation=old_generation)
    with pytest.raises(StaleGenerationError):
        healthy.report_success(
            space_id=space_id,
            job_id=job_id,
            generation=old_generation,
            events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
        )
    with pytest.raises(StaleGenerationError):
        healthy.report_failure(
            space_id=space_id,
            job_id=job_id,
            generation=old_generation,
            failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="late"),
        )
    with postgres_runtime.factory() as session:
        with session.begin():
            with pytest.raises(StaleGenerationError):
                append_job_event(
                    session,
                    space_id=space_id,
                    job_id=job_id,
                    generation=old_generation,
                    draft=OutboxEventDraft(event_type="job.custom", payload={}),
                )

    assert _outbox_count(postgres_runtime, space_id) == 0
    current = healthy.get_job(space_id=space_id, job_id=job_id)
    assert current.state is JobState.LEASED
    assert current.lease_generation == new_generation
    assert current.worker_id == "worker-b"


# --- T7：retryable → retry_wait → queued 与 max_attempts → dead_letter（配置驱动） ---


@pytest.mark.integration_postgres
def test_p1_4_retry_loop_reaches_dead_letter_only_via_configured_policy(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("retry")
    store = _store(postgres_runtime, backoff_seconds=(0.0,), max_attempts=2)
    job_id, generation = _start_running(store, space_id, "job-1", "worker-a")

    first_failure = store.report_failure(
        space_id=space_id,
        job_id=job_id,
        generation=generation,
        failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="first failure"),
    )
    assert first_failure.state is JobState.RETRY_WAIT

    retaken = store.claim(space_ids=(space_id,), worker_id="worker-b")
    assert isinstance(retaken, ClaimedJob)
    assert retaken.job.id == job_id
    running = store.start(
        space_id=space_id, job_id=job_id, generation=retaken.job.lease_generation
    )
    assert running.attempt == 2

    dead = store.report_failure(
        space_id=space_id,
        job_id=job_id,
        generation=retaken.job.lease_generation,
        failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="final failure"),
    )
    assert dead.state is JobState.DEAD_LETTER
    assert dead.attempt == 2
    assert dead.error_class is ErrorClass.RETRYABLE
    assert dead.error_summary == "final failure"

    slow_space = _space("retry-slow")
    slow_store = _store(postgres_runtime, backoff_seconds=(3600.0,))
    slow_job, slow_generation = _start_running(slow_store, slow_space, "job-1", "worker-a")
    slow_store.report_failure(
        space_id=slow_space,
        job_id=slow_job,
        generation=slow_generation,
        failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="wait"),
    )
    waiting = slow_store.claim(space_ids=(slow_space,), worker_id="worker-b")
    assert isinstance(waiting, NoClaimableJob)
    assert slow_store.get_job(space_id=slow_space, job_id=slow_job).state is JobState.RETRY_WAIT


# --- T8：awaiting_human 释放额度 + 并发重复 Decision 恰好唤醒一次 ---


@pytest.mark.integration_postgres
def test_p1_7_concurrent_duplicate_decisions_requeue_exactly_once(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("decide")
    store = _store(postgres_runtime, per_space_concurrency_limit=1)
    job_id, generation = _start_running(store, space_id, "job-1", "worker-a")
    store.enqueue(space_id=space_id, job_type="compile", idempotency_key="job-next")
    saturated = store.claim(space_ids=(space_id,), worker_id="worker-b")
    assert isinstance(saturated, NoClaimableJob)

    waiting = store.report_failure(
        space_id=space_id,
        job_id=job_id,
        generation=generation,
        failure=JobFailure(error_class=ErrorClass.HUMAN_REQUIRED, summary="needs review"),
    )
    assert waiting.state is JobState.AWAITING_HUMAN

    # awaiting_human 同事务释放 lease：额度立即归还，下一个任务可领取。
    freed = store.claim(space_ids=(space_id,), worker_id="worker-b")
    assert isinstance(freed, ClaimedJob)
    assert freed.job.idempotency_key == "job-next"

    barrier = threading.Barrier(4)

    def decide() -> str:
        barrier.wait(timeout=10)
        return store.resume_after_decision(space_id=space_id, job_id=job_id).status

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(decide) for _ in range(4)]
        statuses = [future.result(timeout=FUTURE_TIMEOUT_S) for future in futures]

    assert statuses.count("resumed") == 1
    assert statuses.count("duplicate") == 3
    assert store.get_job(space_id=space_id, job_id=job_id).state is JobState.QUEUED


# --- T9：dispatcher 扫描基于持久标记；较小 id 晚提交不被永久跳过 ---


@pytest.mark.integration_postgres
def test_p1_6_late_committed_smaller_id_is_still_dispatched(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("outbox")
    store = _store(postgres_runtime)
    dispatcher = OutboxDispatcher(postgres_runtime.factory, _config())
    early_job, early_generation = _start_running(store, space_id, "job-early", "worker-a")
    late_job, late_generation = _start_running(store, space_id, "job-late", "worker-b")

    delivered: list[str] = []
    with postgres_runtime.factory() as slow_session:
        with slow_session.begin():
            # 先分配较小的有序 id，但保持事务未提交（提交晚于较大 id）。
            early_row = append_job_event(
                slow_session,
                space_id=space_id,
                job_id=early_job,
                generation=early_generation,
                draft=OutboxEventDraft(event_type="job.custom", payload={}, event_id="early-035"),
            )
            early_id = early_row.id

            store.report_success(
                space_id=space_id,
                job_id=late_job,
                generation=late_generation,
                events=(
                    OutboxEventDraft(
                        event_type="job.succeeded", payload={}, event_id="late-035"
                    ),
                ),
            )
            first_round = dispatcher.dispatch_pending(
                space_id=space_id, deliver=lambda event: delivered.append(event.event_id)
            )
            # 未提交的较小 id 尚不可见：本轮只投递已提交的较大 id。
            assert first_round.delivered_event_ids == ("late-035",)

    second_round = dispatcher.dispatch_pending(
        space_id=space_id, deliver=lambda event: delivered.append(event.event_id)
    )
    assert second_round.delivered_event_ids == ("early-035",)
    assert delivered == ["late-035", "early-035"]

    with postgres_runtime.factory() as session:
        rows = session.execute(
            select(WikiOutboxEvent.id, WikiOutboxEvent.event_id, WikiOutboxEvent.dispatched_at)
            .where(WikiOutboxEvent.space_id == space_id)
            .order_by(WikiOutboxEvent.id)
        ).all()
    assert [row.event_id for row in rows] == ["early-035", "late-035"]
    assert rows[0].id == early_id
    assert rows[0].id < rows[1].id  # 分配序与提交/投递序解耦（P1.6 caveat）
    assert all(row.dispatched_at is not None for row in rows)


# --- T10：崩溃接管端到端恰好一份领域结果；毒性任务循环有界 ---


@pytest.mark.integration_postgres
def test_p1_10_forced_kill_takeover_yields_exactly_one_domain_result(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("crash")
    domain_table = f"domain_{uuid.uuid4().hex[:12]}"
    application_name = f"worker_a_{uuid.uuid4().hex[:8]}"
    with postgres_runtime.engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE TABLE "{domain_table}" (job_id TEXT PRIMARY KEY)')

    # worker A 使用独立连接池，便于用 pg_terminate_backend 强制终止。
    crash_engine = create_engine(
        postgres_runtime.engine.url,
        future=True,
        connect_args={**CONNECT_ARGS, "application_name": application_name},
    )
    crash_factory: sessionmaker[Session] = sessionmaker(
        bind=crash_engine, expire_on_commit=False, future=True
    )
    try:
        worker_a = JobStore(crash_factory, _config())
        job_id, generation_a = _start_running(worker_a, space_id, "job-1", "worker-a")
        _force_expire(postgres_runtime, job_id)

        # 强制终止 A 的全部后端连接：不执行任何清理（P1.10）。
        with postgres_runtime.factory() as session:
            session.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE application_name = :application_name AND pid <> pg_backend_pid()"
                ),
                {"application_name": application_name},
            )
            session.commit()

        worker_b = _store(postgres_runtime, lease_seconds=300.0)
        takeover = worker_b.claim(space_ids=(space_id,), worker_id="worker-b")
        assert isinstance(takeover, ClaimedJob)
        assert takeover.job.id == job_id
        generation_b = takeover.job.lease_generation
        assert generation_b > generation_a
        worker_b.start(space_id=space_id, job_id=job_id, generation=generation_b)

        domain_writes = (DomainWriteSpec(table=domain_table, values={"job_id": job_id}),)

        done = worker_b.report_success(
            space_id=space_id,
            job_id=job_id,
            generation=generation_b,
            events=(OutboxEventDraft(event_type="job.succeeded", payload={"job": job_id}),),
            domain_writes=domain_writes,
        )
        assert done.state is JobState.SUCCEEDED

        # A「苏醒」（新连接的同进程重放）：旧 generation 提交被 fencing 拒绝。
        revived_a = _store(postgres_runtime)
        with pytest.raises(StaleGenerationError):
            revived_a.report_success(
                space_id=space_id,
                job_id=job_id,
                generation=generation_a,
                events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
                domain_writes=domain_writes,
            )

        with postgres_runtime.factory() as session:
            assert session.scalar(text(f'SELECT count(*) FROM "{domain_table}"')) == 1
        assert _outbox_count(postgres_runtime, space_id) == 1
    finally:
        crash_engine.dispose()


@pytest.mark.integration_postgres
def test_p1_10_poison_task_crash_loop_is_bounded_by_max_attempts(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("poison")
    store = _store(postgres_runtime, max_attempts=3)
    store.enqueue(space_id=space_id, job_type="compile", idempotency_key="poison")

    generations: list[int] = []
    for _round in range(3):
        outcome = store.claim(space_ids=(space_id,), worker_id="worker-a")
        assert isinstance(outcome, ClaimedJob)
        generations.append(outcome.job.lease_generation)
        running = store.start(
            space_id=space_id,
            job_id=outcome.job.id,
            generation=outcome.job.lease_generation,
        )
        assert running.attempt == _round + 1
        # worker 随即「崩溃」：不 heartbeat、不提交任何结果，lease 自然过期。
        _force_expire(postgres_runtime, outcome.job.id)

    final = store.claim(space_ids=(space_id,), worker_id="worker-b")
    assert isinstance(final, NoClaimableJob)  # 回收路由进 dead_letter，不再 requeue

    job_id = generations and store.enqueue(
        space_id=space_id, job_type="compile", idempotency_key="poison"
    ).job.id
    assert isinstance(job_id, str)
    dead = store.get_job(space_id=space_id, job_id=job_id)
    assert dead.state is JobState.DEAD_LETTER
    assert dead.attempt == 3
    assert dead.error_class is ErrorClass.RETRYABLE
    assert dead.error_summary == "lease_expired"
    # C2 修复后每次回收也 +1：三次「回收+领取」共 6 个 generation，仍有界。
    assert dead.lease_generation == 6
    assert generations == [1, 3, 5]


# --- T11：指标查询与预置分布精确一致（per-Space 精确 + 全局按增量精确） ---


@pytest.mark.integration_postgres
def test_p1_9_metrics_match_seeded_distribution_on_postgres(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_a = _space("metrics-a")
    space_b = _space("metrics-b")
    with postgres_runtime.factory() as session:
        global_before = global_job_metrics(session)

    store = _store(postgres_runtime, backoff_seconds=(3600.0,))
    oldest_id, oldest_generation = _start_running(store, space_a, "retrying", "worker-a")
    retry_row = store.report_failure(
        space_id=space_a,
        job_id=oldest_id,
        generation=oldest_generation,
        failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="wait"),
    )
    for key in ("dead-1", "dead-2"):
        job_id, generation = _start_running(store, space_a, key, "worker-a")
        store.report_failure(
            space_id=space_a,
            job_id=job_id,
            generation=generation,
            failure=JobFailure(error_class=ErrorClass.NON_RETRYABLE, summary="fatal"),
        )
    _start_running(store, space_a, "running-1", "worker-a")
    for key in ("queued-1", "queued-2", "queued-3"):
        store.enqueue(space_id=space_a, job_type="compile", idempotency_key=key)
    store.enqueue(space_id=space_b, job_type="compile", idempotency_key="b-queued")
    # 回拨最老可调度行（retry_wait）的 enqueued_at，锁定精确年龄下界。
    backdated = retry_row.enqueued_at - timedelta(hours=1)
    with postgres_runtime.factory() as session:
        session.execute(
            text("UPDATE wiki_jobs SET enqueued_at = :backdated WHERE id = :id"),
            {"backdated": backdated, "id": oldest_id},
        )
        session.commit()

    with postgres_runtime.factory() as session:
        before = database_now(session)
        metrics_a = space_job_metrics(session, space_id=space_a)
        metrics_b = space_job_metrics(session, space_id=space_b)
        global_after = global_job_metrics(session)
        after = database_now(session)

    assert metrics_a.state_counts == {
        JobState.QUEUED: 3,
        JobState.LEASED: 0,
        JobState.RUNNING: 1,
        JobState.SUCCEEDED: 0,
        JobState.RETRY_WAIT: 1,
        JobState.AWAITING_HUMAN: 0,
        JobState.BLOCKED: 0,
        JobState.DEAD_LETTER: 2,
    }
    assert metrics_a.queue_depth == 3
    assert metrics_a.retry_wait_count == 1
    assert metrics_a.dead_letter_count == 2
    assert metrics_a.attempt_total == 4
    # 最老可调度年龄由回拨的 retry_wait 行精确决定（覆盖 retry_wait，非仅 queued）。
    assert metrics_a.oldest_schedulable_age_seconds is not None
    lower = (before - backdated).total_seconds()
    upper = (after - backdated).total_seconds()
    assert lower <= metrics_a.oldest_schedulable_age_seconds <= upper
    assert metrics_a.oldest_schedulable_age_seconds >= 3600.0
    assert metrics_b.state_counts[JobState.QUEUED] == 1
    assert metrics_b.attempt_total == 0

    # 全局入口按增量精确：共享库中其余 Space 的行保持不变。
    delta = {
        state: global_after.state_counts[state] - global_before.state_counts[state]
        for state in JobState
    }
    assert delta == {
        JobState.QUEUED: 4,
        JobState.LEASED: 0,
        JobState.RUNNING: 1,
        JobState.SUCCEEDED: 0,
        JobState.RETRY_WAIT: 1,
        JobState.AWAITING_HUMAN: 0,
        JobState.BLOCKED: 0,
        JobState.DEAD_LETTER: 2,
    }
    assert global_after.attempt_total - global_before.attempt_total == 4
    assert retry_row.state is JobState.RETRY_WAIT


# --- C1：scope 外过期 lease 不得永久占用全局限额（独立数据库） ---


@pytest.mark.integration_postgres
def test_c1_expired_foreign_lease_does_not_consume_global_limit(
    isolated_postgres_runtime: PostgresRuntime,
) -> None:
    runtime = isolated_postgres_runtime
    space_dead = _space("dead")
    space_live = _space("live")
    crasher = _store(runtime, global_concurrency_limit=1)
    crasher.enqueue(space_id=space_dead, job_type="compile", idempotency_key="k")
    dead = crasher.claim(space_ids=(space_dead,), worker_id="worker-crash")
    assert isinstance(dead, ClaimedJob)
    _force_expire(runtime, dead.job.id)

    healthy = _store(runtime, lease_seconds=300.0, global_concurrency_limit=1)
    healthy.enqueue(space_id=space_live, job_type="compile", idempotency_key="k")

    outcome = healthy.claim(space_ids=(space_live,), worker_id="worker-live")

    # C1 的反饥饿意图保留；机制按 D-2026-07-27-16 改为「饱和时先做无 Space
    # 过滤的有界回收再重算」——因此 scope 外过期行会被 fenced（generation +1），
    # 不再断言"scope 外零变更"。保住的是：不永久饥饿 + 调用方拿不到跨 Space
    # 任务内容 + 过期持有者即刻失去写权威。
    assert isinstance(outcome, ClaimedJob)  # 修复前：永远 global_concurrency_limit
    assert outcome.job.space_id == space_live
    reclaimed = healthy.get_job(space_id=space_dead, job_id=dead.job.id)
    assert reclaimed.state is JobState.QUEUED
    assert reclaimed.lease_generation == dead.job.lease_generation + 1
    with pytest.raises(StaleGenerationError):
        crasher.start(
            space_id=space_dead,
            job_id=dead.job.id,
            generation=dead.job.lease_generation,
        )
    # 有效（未过期）lease 已达全局限额：下一个 claim 被全局限额挡住。
    healthy.enqueue(space_id=space_live, job_type="compile", idempotency_key="k2")
    blocked = healthy.claim(space_ids=(space_live,), worker_id="worker-live")
    assert isinstance(blocked, NoClaimableJob)
    assert blocked.reason == "global_concurrency_limit"


# --- I3：advisory 锁等待不吞噬 lease 时长（clock_timestamp 语义） ---


@pytest.mark.integration_postgres
def test_i3_lease_duration_survives_advisory_lock_wait(
    postgres_runtime: PostgresRuntime,
) -> None:
    from insurance_harness.jobs.store import _CLAIM_LOCK_KEY

    space_id = _space("clockwait")
    # lease 必须大于 heartbeat 间隔（D-2026-07-27-16），短 lease 场景同步调小。
    store = _store(postgres_runtime, lease_seconds=5.0, heartbeat_interval_seconds=1.0)
    store.enqueue(space_id=space_id, job_type="compile", idempotency_key="k")
    lock_held = threading.Event()

    def hold_claim_lock() -> None:
        with postgres_runtime.factory() as session:
            with session.begin():
                session.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"), {"key": _CLAIM_LOCK_KEY}
                )
                lock_held.set()
                time.sleep(1.5)

    thread = threading.Thread(target=hold_claim_lock)
    thread.start()
    assert lock_held.wait(timeout=10)
    outcome = store.claim(space_ids=(space_id,), worker_id="worker-a")
    thread.join(timeout=FUTURE_TIMEOUT_S)
    assert isinstance(outcome, ClaimedJob)

    with postgres_runtime.factory() as session:
        remaining = session.execute(
            text(
                "SELECT extract(epoch FROM (lease_expires_at - clock_timestamp())) "
                "FROM wiki_jobs WHERE id = :id"
            ),
            {"id": outcome.job.id},
        ).scalar_one()
    # 修复前：lease 锚定事务开始时刻，等待 1.5s 后仅剩 ~3.5s 甚至立即过期。
    assert float(remaining) > 3.5

    thief = _store(postgres_runtime, lease_seconds=5.0, heartbeat_interval_seconds=1.0)
    stolen = thief.claim(space_ids=(space_id,), worker_id="thief")
    assert isinstance(stolen, NoClaimableJob)  # 新 lease 未过期，不可被立即接管
    current = store.get_job(space_id=space_id, job_id=outcome.job.id)
    assert current.worker_id == "worker-a"
    assert current.lease_generation == outcome.job.lease_generation


# --- P1.8：跨 Space 写入与 outbox 读取在 PG 全部 fail closed ---


@pytest.mark.integration_postgres
def test_p1_8_cross_space_writes_and_outbox_reads_fail_closed_on_postgres(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_a = _space("iso-a")
    space_b = _space("iso-b")
    store = _store(postgres_runtime)
    job_id, generation = _start_running(store, space_a, "job-1", "worker-a")

    with pytest.raises(SpaceScopeError):
        store.heartbeat(space_id=space_b, job_id=job_id, generation=generation)
    with pytest.raises(SpaceScopeError):
        store.start(space_id=space_b, job_id=job_id, generation=generation)
    with pytest.raises(SpaceScopeError):
        store.report_success(space_id=space_b, job_id=job_id, generation=generation)
    with pytest.raises(SpaceScopeError):
        store.report_failure(
            space_id=space_b,
            job_id=job_id,
            generation=generation,
            failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="cross"),
        )
    with pytest.raises(SpaceScopeError):
        store.resume_after_decision(space_id=space_b, job_id=job_id)
    with pytest.raises(SpaceScopeError):
        store.get_job(space_id=space_b, job_id=job_id)

    done = store.report_success(
        space_id=space_a,
        job_id=job_id,
        generation=generation,
        events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
    )
    assert done.state is JobState.SUCCEEDED
    dispatcher = OutboxDispatcher(postgres_runtime.factory, _config())
    event_id = dispatcher.read_pending(space_id=space_a)[0].event_id
    assert dispatcher.read_pending(space_id=space_b) == ()  # 零行返回
    with pytest.raises(SpaceScopeError):
        dispatcher.mark_dispatched(space_id=space_b, event_id=event_id)
    current = store.get_job(space_id=space_a, job_id=job_id)
    assert current.state is JobState.SUCCEEDED  # 目标行零变更


# --- M19：并发 dispatcher 行级锁互斥，正常路径零重复投递 ---


@pytest.mark.integration_postgres
def test_m19_concurrent_dispatchers_do_not_double_deliver(
    postgres_runtime: PostgresRuntime,
) -> None:
    space_id = _space("dupdisp")
    store = _store(postgres_runtime)
    for index in range(6):
        job_id, generation = _start_running(store, space_id, f"job-{index}", "worker-a")
        store.report_success(
            space_id=space_id,
            job_id=job_id,
            generation=generation,
            events=(OutboxEventDraft(event_type="job.succeeded", payload={"i": index}),),
        )

    seen: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def run_dispatcher() -> None:
        dispatcher = OutboxDispatcher(postgres_runtime.factory, _config())
        barrier.wait(timeout=10)

        def deliver(event: object) -> None:
            time.sleep(0.05)
            with lock:
                seen.append(event.event_id)  # type: ignore[attr-defined]

        dispatcher.dispatch_pending(space_id=space_id, deliver=deliver)

    threads = [threading.Thread(target=run_dispatcher) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=FUTURE_TIMEOUT_S)

    assert len(seen) == 6
    assert len(set(seen)) == 6  # 行级 SKIP LOCKED：无双投递
    dispatcher = OutboxDispatcher(postgres_runtime.factory, _config())
    assert dispatcher.read_pending(space_id=space_id) == ()


# --- D-2026-07-27-16 边界冻结：PostgreSQL 侧强制验收节点 ---


@pytest.mark.integration_postgres
def test_q15_expired_lease_holder_has_no_write_authority_on_postgres(
    postgres_runtime: PostgresRuntime,
) -> None:
    """P1.3 写权威合同：过期未回收的持有者四条写路径全部 typed 拒绝、零变更。"""
    space_id = _space("authority")
    store = _store(postgres_runtime)
    job_id, generation = _start_running(store, space_id, "job-1", "worker-a")
    _force_expire(postgres_runtime, job_id)

    with pytest.raises(LeaseExpiredError):
        store.report_success(
            space_id=space_id,
            job_id=job_id,
            generation=generation,
            events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
        )
    with pytest.raises(LeaseExpiredError):
        store.report_failure(
            space_id=space_id,
            job_id=job_id,
            generation=generation,
            failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="late"),
        )
    with pytest.raises(LeaseExpiredError):
        store.heartbeat(space_id=space_id, job_id=job_id, generation=generation)
    with pytest.raises(LeaseExpiredError):
        with postgres_runtime.factory() as session:
            with session.begin():
                append_job_event(
                    session,
                    space_id=space_id,
                    job_id=job_id,
                    generation=generation,
                    draft=OutboxEventDraft(event_type="job.progress", payload={}),
                )

    current = store.get_job(space_id=space_id, job_id=job_id)
    assert current.state is JobState.RUNNING
    assert current.lease_generation == generation
    assert _outbox_count(postgres_runtime, space_id) == 0


@pytest.mark.integration_postgres
def test_q16_stalled_expired_leases_never_exceed_limits_on_postgres(
    isolated_postgres_runtime: PostgresRuntime,
) -> None:
    """P1.8 限额会计：停滞的过期 lease 不得抬高 leased|running 行数上限。"""
    runtime = isolated_postgres_runtime
    store = _store(runtime, per_space_concurrency_limit=1, global_concurrency_limit=2)
    spaces = [_space(f"stall-{index}") for index in range(6)]
    for space_id in spaces:
        store.enqueue(space_id=space_id, job_type="compile", idempotency_key="job")

    for space_id in spaces:
        outcome = store.claim(space_ids=(space_id,), worker_id=f"worker-{space_id}")
        if isinstance(outcome, ClaimedJob):
            _force_expire(runtime, outcome.job.id)
        with runtime.factory() as session:
            active = int(
                session.scalar(
                    select(func.count())
                    .select_from(WikiJob)
                    .where(
                        WikiJob.state.in_(
                            (JobState.LEASED.value, JobState.RUNNING.value)
                        )
                    )
                )
                or 0
            )
        assert active <= 2, f"越限：{active} > 2"


@pytest.mark.integration_postgres
def test_q17_unenumerated_space_converges_via_global_reclaim_on_postgres(
    postgres_runtime: PostgresRuntime,
) -> None:
    """P1.10 回收可达性：无人枚举的 Space 经显式全局入口收敛。"""
    space_id = _space("orphan")
    store = _store(postgres_runtime, max_attempts=1)
    store.enqueue(space_id=space_id, job_type="compile", idempotency_key="job")
    outcome = store.claim(space_ids=(space_id,), worker_id="worker-gone")
    assert isinstance(outcome, ClaimedJob)
    _force_expire(postgres_runtime, outcome.job.id)

    report = store.reclaim_expired_leases_all_spaces()

    assert outcome.job.id in report.dead_lettered_job_ids
    dead = store.get_job(space_id=space_id, job_id=outcome.job.id)
    assert dead.state is JobState.DEAD_LETTER
    assert dead.error_summary == "lease_expired"


@pytest.mark.integration_postgres
def test_q19_declarative_domain_write_channel_on_postgres(
    postgres_runtime: PostgresRuntime,
) -> None:
    """P1.5 领域写通道（D-2026-07-27-16 第二轮修订）在真实 PG 上的合同。

    上一版把可执行回调放进完成事务再试图进程内沙箱它，被第二轮评审以公共
    属性 `Result.connection` 一行击破（领域行落库 + 任务仍 running + outbox
    空 ⇒ 重放产生第二份领域结果）。通道已改为声明式：调用方交表标识 + 列值，
    存储层自己执行，没有任何句柄可泄漏。本节点断言三件事：① 自有表被拒；
    ② 同前缀的其他域表不被误拦；③ 合法声明式写与状态、outbox 同事务原子。
    """
    space_id = _space("channel")
    domain_table = f"domain_{uuid.uuid4().hex[:12]}"
    foreign_wiki_table = f"wiki_page_revisions_{uuid.uuid4().hex[:8]}"
    with postgres_runtime.engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE TABLE "{domain_table}" (job_id TEXT PRIMARY KEY)')
        connection.exec_driver_sql(
            f'CREATE TABLE "{foreign_wiki_table}" (id TEXT PRIMARY KEY, note TEXT)'
        )
    store = _store(postgres_runtime)
    job_id, generation = _start_running(store, space_id, "job-1", "worker-a")

    # ① P1 自有表：在执行任何领域语句之前 typed 拒绝，整个完成事务回滚。
    for owned in sorted(OWNED_TABLES):
        with pytest.raises(DomainWriteViolationError):
            store.report_success(
                space_id=space_id,
                job_id=job_id,
                generation=generation,
                domain_writes=(
                    DomainWriteSpec(table=domain_table, values={"job_id": job_id}),
                    DomainWriteSpec(table=owned, values={"space_id": space_id}),
                ),
            )
    with postgres_runtime.engine.begin() as connection:
        leaked = connection.exec_driver_sql(
            f'SELECT count(*) FROM "{domain_table}"'
        ).scalar_one()
    assert leaked == 0, "被拒绝的完成事务不得留下领域行"
    current = store.get_job(space_id=space_id, job_id=job_id)
    assert current.state is JobState.RUNNING
    assert current.lease_generation == generation
    assert _outbox_count(postgres_runtime, space_id) == 0

    # ②③ 同前缀的其他域表不被误拦；含事务控制关键字的字面量同样不被误拦。
    done = store.report_success(
        space_id=space_id,
        job_id=job_id,
        generation=generation,
        events=(OutboxEventDraft(event_type="job.succeeded", payload={}),),
        domain_writes=(
            DomainWriteSpec(table=domain_table, values={"job_id": job_id}),
            DomainWriteSpec(
                table=foreign_wiki_table,
                values={"id": job_id, "note": "do not touch; call center; period begin"},
            ),
        ),
    )
    assert done.state is JobState.SUCCEEDED
    with postgres_runtime.engine.begin() as connection:
        assert (
            connection.exec_driver_sql(f'SELECT count(*) FROM "{domain_table}"').scalar_one() == 1
        )
        assert (
            connection.exec_driver_sql(
                f'SELECT count(*) FROM "{foreign_wiki_table}"'
            ).scalar_one()
            == 1
        )
    assert _outbox_count(postgres_runtime, space_id) == 1


@pytest.mark.integration_postgres
def test_q30_owned_table_check_is_normalized_on_postgres(
    postgres_runtime: PostgresRuntime,
) -> None:
    """P1.5：自有表校验的规范化在真实 PG 上同样成立（第三轮自攻 BLOCKER）。

    SQLite 上 `table="WIKI_JOBS"` 曾过校验并真的写进 `wiki_jobs`；PG 上同一
    输入是 `NoSuchTableError`。护栏的正确性**不得取决于方言**——两条 lane 都
    必须给出同一族 typed 拒绝，且零自有表变更。
    """
    space_id = _space("norm")
    store = _store(postgres_runtime)
    job_id, generation = _start_running(store, space_id, "job-1", "worker-a")
    variants = (
        "WIKI_JOBS",
        "Wiki_Jobs",
        "WIKI_OUTBOX_EVENTS",
        "public.wiki_jobs",
        '"wiki_jobs"',
        " wiki_jobs",
        "wiki_jobs--x",
    )

    with postgres_runtime.factory() as session:
        before = int(
            session.scalar(select(func.count()).select_from(WikiJob)) or 0
        )

    for variant in variants:
        with pytest.raises((DomainWriteViolationError, InvalidJobInputError)):
            store.report_success(
                space_id=space_id,
                job_id=job_id,
                generation=generation,
                domain_writes=(
                    DomainWriteSpec(table=variant, values={"space_id": "other"}),
                ),
            )

    with postgres_runtime.factory() as session:
        after = int(session.scalar(select(func.count()).select_from(WikiJob)) or 0)
    assert after == before, "规范化变体写进了 P1 自有表"
    current = store.get_job(space_id=space_id, job_id=job_id)
    assert current.state is JobState.RUNNING
    assert current.lease_generation == generation


@pytest.mark.integration_postgres
def test_q25_delivered_but_unmarked_crash_converges_on_postgres(
    postgres_runtime: PostgresRuntime,
) -> None:
    """P1.6 at-least-once（Contract Card 清单第 11 项的 (PG) 覆盖）。

    投递成功但标记前崩溃 ⇒ 该行下一轮被重投，消费端以 event_id 幂等去重
    收敛为恰好一次可观测效果，且最终被持久标记。
    """
    space_id = _space("atleastonce")
    store = _store(postgres_runtime)
    job_id, generation = _start_running(store, space_id, "job-1", "worker-a")
    store.report_success(
        space_id=space_id,
        job_id=job_id,
        generation=generation,
        events=(OutboxEventDraft(event_type="job.succeeded", payload={}, event_id="evt-1"),),
    )
    dispatcher = OutboxDispatcher(postgres_runtime.factory, _config())
    seen: list[str] = []

    def deliver_then_crash(event: object) -> None:
        seen.append(event.event_id)  # type: ignore[attr-defined]
        raise RuntimeError("crash after delivery, before marking")

    first = dispatcher.dispatch_pending(space_id=space_id, deliver=deliver_then_crash)
    assert first.delivered_event_ids == ()
    assert first.failed_event_ids == ("evt-1",)
    with postgres_runtime.factory() as session:
        undispatched = session.scalar(
            select(func.count())
            .select_from(WikiOutboxEvent)
            .where(
                WikiOutboxEvent.space_id == space_id,
                WikiOutboxEvent.dispatched_at.is_(None),
            )
        )
    assert undispatched == 1  # 未标记 ⇒ 仍待投递，不丢

    def deliver(event: object) -> None:
        seen.append(event.event_id)  # type: ignore[attr-defined]

    second = dispatcher.dispatch_pending(space_id=space_id, deliver=deliver)
    assert second.delivered_event_ids == ("evt-1",)
    assert seen == ["evt-1", "evt-1"]  # at-least-once：两次投递
    assert len(set(seen)) == 1  # 同一 event_id：消费端幂等可折叠
    assert dispatcher.read_pending(space_id=space_id) == ()
