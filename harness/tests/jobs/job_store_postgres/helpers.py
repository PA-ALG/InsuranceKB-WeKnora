"""OpenSpec 035 P1.12：JobStore/Outbox 在真实 PostgreSQL 16 的并发合同——共用运行时、配置与行辅助。

覆盖 033 §16.2 对 P1 的义务：多 worker 并发单领、lease 过期接管、迟到
（旧 generation）worker 全写路径拒绝、完成事务 + outbox 原子性（含崩溃/
中断模拟），以及限额、跨 Space fail closed、毒性任务回收有界、Decision
幂等与指标查询。`service_shell/worker` 复用这里的 PostgreSQL 运行时。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from insurance_harness.jobs import (
    ClaimedJob,
    JobRuntimeConfig,
    JobStore,
)
from insurance_harness.jobs.tables import WikiOutboxEvent

HARNESS_ROOT = Path(__file__).resolve().parents[3]
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
        alembic_config = _alembic_config(database_url)
        expected_head = ScriptDirectory.from_config(alembic_config).get_current_head()
        assert expected_head is not None
        command.upgrade(alembic_config, "head")
        engine = create_engine(database_url, future=True, connect_args=CONNECT_ARGS)
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version")) == expected_head
            )
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


# --- T5：lease 过期接管与旧 generation heartbeat/转换拒绝 ---


def _claim_one(store: JobStore, space_id: str, worker_id: str) -> str:
    outcome = store.claim(space_ids=(space_id,), worker_id=worker_id)
    assert isinstance(outcome, ClaimedJob)
    return outcome.job.id


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
