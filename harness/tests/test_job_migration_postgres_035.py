"""OpenSpec 035 T2/P1.11：唯一迁移 0015 与两表 schema 合同（PostgreSQL 16）。

真实 Alembic 迁移是被测对象：单 head、`down_revision=0006`、只建
`wiki_jobs`/`wiki_outbox_events` 及其索引约束、ORM 与 head 零漂移。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError, IntegrityError

HARNESS_ROOT = Path(__file__).resolve().parents[1]
TEST_POSTGRES_ENV = "HARNESS_TEST_POSTGRES_URL"
P1_TABLES = {"wiki_jobs", "wiki_outbox_events"}
CONNECT_ARGS: dict[str, Any] = {
    "connect_timeout": 10,
    "options": "-cstatement_timeout=30000 -clock_timeout=15000",
}


@dataclass(frozen=True)
class PostgresMigrationDb:
    url: str
    engine: Engine


def _sync_postgresql_url(raw_url: str) -> URL:
    try:
        url = make_url(raw_url)
    except ArgumentError:
        pytest.fail(f"{TEST_POSTGRES_ENV} must be a valid PostgreSQL URL")
    if url.get_backend_name() != "postgresql":
        pytest.fail(f"{TEST_POSTGRES_ENV} must use PostgreSQL")
    return url.set(drivername="postgresql+psycopg")


@pytest.fixture
def postgres_migration_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[PostgresMigrationDb]:
    raw_url = os.getenv(TEST_POSTGRES_ENV)
    if not raw_url:
        pytest.fail(f"{TEST_POSTGRES_ENV} is required for integration_postgres")

    monkeypatch.delenv("HARNESS_DB_URL", raising=False)
    admin_url = _sync_postgresql_url(raw_url)
    database_name = f"ikb_035_{uuid.uuid4().hex}"
    admin_engine = create_engine(
        admin_url, connect_args=CONNECT_ARGS, future=True, pool_pre_ping=True
    )
    database_created = False
    test_engine: Engine | None = None
    try:
        with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        database_created = True
        test_url = admin_url.set(database=database_name).update_query_dict(
            {
                "application_name": "insurancekb_035_migration_test",
                "connect_timeout": "10",
                "options": "-cstatement_timeout=30000 -clock_timeout=15000",
            }
        )
        test_engine = create_engine(
            test_url, connect_args=CONNECT_ARGS, future=True, pool_pre_ping=True
        )
        yield PostgresMigrationDb(
            url=test_url.render_as_string(hide_password=False), engine=test_engine
        )
    finally:
        if test_engine is not None:
            test_engine.dispose()
        if database_created:
            with admin_engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                    ),
                    {"database_name": database_name},
                )
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
        admin_engine.dispose()


def _cfg(url: str) -> Config:
    config = Config(str(HARNESS_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(HARNESS_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def _version_rows(engine: Engine) -> tuple[str, ...]:
    with engine.connect() as connection:
        return tuple(
            connection.scalars(text("SELECT version_num FROM alembic_version ORDER BY version_num"))
        )


@pytest.mark.integration_postgres
def test_p1_11_single_new_migration_from_real_head_0006(
    postgres_migration_db: PostgresMigrationDb,
) -> None:
    config = _cfg(postgres_migration_db.url)
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["0015"]
    revision = scripts.get_revision("0015")
    assert revision is not None
    assert revision.down_revision == "0006"

    command.upgrade(config, "0006")
    baseline = set(inspect(postgres_migration_db.engine).get_table_names())
    assert P1_TABLES.isdisjoint(baseline)

    command.upgrade(config, "head")
    assert _version_rows(postgres_migration_db.engine) == ("0015",)
    after = set(inspect(postgres_migration_db.engine).get_table_names())
    assert after - baseline == P1_TABLES

    command.check(config)

    command.downgrade(config, "0006")
    assert _version_rows(postgres_migration_db.engine) == ("0006",)
    assert set(inspect(postgres_migration_db.engine).get_table_names()) == baseline


@pytest.mark.integration_postgres
def test_p1_11_wiki_jobs_columns_not_null_space_and_idempotency_unique(
    postgres_migration_db: PostgresMigrationDb,
) -> None:
    command.upgrade(_cfg(postgres_migration_db.url), "head")
    inspector = inspect(postgres_migration_db.engine)

    columns = {column["name"]: column for column in inspector.get_columns("wiki_jobs")}
    assert set(columns) == {
        "id",
        "space_id",
        "job_type",
        "idempotency_key",
        "payload",
        "state",
        "attempt",
        "lease_generation",
        "worker_id",
        "available_at",
        "lease_expires_at",
        "enqueued_at",
        "started_at",
        "finished_at",
        "error_class",
        "error_summary",
    }
    for required in (
        "space_id",
        "job_type",
        "idempotency_key",
        "payload",
        "state",
        "attempt",
        "lease_generation",
        "available_at",
        "enqueued_at",
    ):
        assert columns[required]["nullable"] is False, required

    uniques = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("wiki_jobs")
    }
    assert uniques["uq_wiki_jobs_idempotency"] == ("space_id", "job_type", "idempotency_key")

    indexes = {
        index["name"]: tuple(index["column_names"]) for index in inspector.get_indexes("wiki_jobs")
    }
    # I5：claim 的 ORDER BY (enqueued_at, id) 有匹配索引，避免外部排序。
    assert indexes["ix_wiki_jobs_claim_order"] == ("space_id", "state", "enqueued_at", "id")

    with postgres_migration_db.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO wiki_jobs (id, space_id, job_type, idempotency_key, payload,"
                " state, attempt, lease_generation, available_at, enqueued_at)"
                " VALUES (:id, 'space-a', 'compile', 'batch-1', '{}', 'queued', 0, 0,"
                " now(), now())"
            ),
            {"id": str(uuid.uuid4())},
        )
    with pytest.raises(IntegrityError, match="uq_wiki_jobs_idempotency"):
        with postgres_migration_db.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO wiki_jobs (id, space_id, job_type, idempotency_key, payload,"
                    " state, attempt, lease_generation, available_at, enqueued_at)"
                    " VALUES (:id, 'space-a', 'compile', 'batch-1', '{}', 'queued', 0, 0,"
                    " now(), now())"
                ),
                {"id": str(uuid.uuid4())},
            )
    with pytest.raises(IntegrityError, match="ck_wiki_jobs_state"):
        with postgres_migration_db.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO wiki_jobs (id, space_id, job_type, idempotency_key, payload,"
                    " state, attempt, lease_generation, available_at, enqueued_at)"
                    " VALUES (:id, 'space-a', 'compile', 'batch-2', '{}', 'paused', 0, 0,"
                    " now(), now())"
                ),
                {"id": str(uuid.uuid4())},
            )


@pytest.mark.integration_postgres
def test_p1_11_outbox_ordered_id_event_id_unique_and_not_null_space(
    postgres_migration_db: PostgresMigrationDb,
) -> None:
    command.upgrade(_cfg(postgres_migration_db.url), "head")
    inspector = inspect(postgres_migration_db.engine)

    columns = {column["name"]: column for column in inspector.get_columns("wiki_outbox_events")}
    assert set(columns) == {
        "id",
        "event_id",
        "space_id",
        "event_type",
        "payload",
        "created_at",
        "dispatched_at",
        "dispatch_attempts",
    }
    for required in (
        "event_id",
        "space_id",
        "event_type",
        "payload",
        "created_at",
        "dispatch_attempts",
    ):
        assert columns[required]["nullable"] is False, required
    assert columns["id"]["type"].__class__.__name__ == "BIGINT"

    uniques = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("wiki_outbox_events")
    }
    # I7：event_id 幂等键按 Space 隔离，跨 Space 允许同名。
    assert uniques["uq_wiki_outbox_events_space_event"] == ("space_id", "event_id")

    insert = text(
        "INSERT INTO wiki_outbox_events (event_id, space_id, event_type, payload, created_at)"
        " VALUES (:event_id, 'space-a', 'job.succeeded', '{}', now()) RETURNING id"
    )
    with postgres_migration_db.engine.begin() as connection:
        first = connection.execute(insert, {"event_id": str(uuid.uuid4())}).scalar_one()
        second = connection.execute(insert, {"event_id": str(uuid.uuid4())}).scalar_one()
    assert second > first

    duplicate_event = str(uuid.uuid4())
    with postgres_migration_db.engine.begin() as connection:
        connection.execute(insert, {"event_id": duplicate_event})
    with pytest.raises(IntegrityError, match="uq_wiki_outbox_events_space_event"):
        with postgres_migration_db.engine.begin() as connection:
            connection.execute(insert, {"event_id": duplicate_event})


@pytest.mark.integration_postgres
def test_i9_downgrade_with_live_rows_is_refused_before_any_ddl(
    postgres_migration_db: PostgresMigrationDb,
) -> None:
    config = _cfg(postgres_migration_db.url)
    command.upgrade(config, "head")
    with postgres_migration_db.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO wiki_jobs (id, space_id, job_type, idempotency_key, payload,"
                " state, attempt, lease_generation, available_at, enqueued_at)"
                " VALUES (:id, 'space-a', 'compile', 'live-1', '{}', 'queued', 0, 0,"
                " now(), now())"
            ),
            {"id": str(uuid.uuid4())},
        )
        connection.execute(
            text(
                "INSERT INTO wiki_outbox_events (event_id, space_id, event_type, payload,"
                " created_at) VALUES (:event_id, 'space-a', 'job.succeeded', '{}', now())"
            ),
            {"event_id": str(uuid.uuid4())},
        )

    # 活跃任务 + 未投递事件：降级必须在任何 DDL 之前拒绝（含相对参数）。
    for destination in ("0006", "-1"):
        with pytest.raises(Exception, match="0015 downgrade refused"):
            command.downgrade(config, destination)
        tables = set(inspect(postgres_migration_db.engine).get_table_names())
        assert P1_TABLES <= tables  # 零 DDL
        assert _version_rows(postgres_migration_db.engine) == ("0015",)

    # 任务收敛为终态且事件均已投递后，同一降级即可通过。
    with postgres_migration_db.engine.begin() as connection:
        connection.execute(text("UPDATE wiki_jobs SET state = 'succeeded', finished_at = now()"))
        connection.execute(text("UPDATE wiki_outbox_events SET dispatched_at = now()"))
    command.downgrade(config, "0006")
    assert _version_rows(postgres_migration_db.engine) == ("0006",)
    assert P1_TABLES.isdisjoint(inspect(postgres_migration_db.engine).get_table_names())
