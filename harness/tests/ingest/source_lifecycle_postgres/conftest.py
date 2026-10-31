"""OpenSpec 021 L2/L5/L6 PostgreSQL migration acceptance: shared database and snapshot helpers."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text

from tests.ingest.source_lifecycle_postgres.helpers import (
    CONNECT_ARGS,
    TEST_POSTGRES_ENV,
    PostgresMigrationDb,
    _database_url,
    _sync_postgresql_url,
)


@pytest.fixture
def postgres_migration_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[PostgresMigrationDb]:
    raw_url = os.getenv(TEST_POSTGRES_ENV)
    if not raw_url:
        pytest.fail(f"{TEST_POSTGRES_ENV} is required for integration_postgres")

    # migrations/env.py gives HARNESS_DB_URL precedence over Config. Removing that
    # fallback ensures this lane can only touch the explicitly managed test server.
    monkeypatch.delenv("HARNESS_DB_URL", raising=False)
    admin_url = _sync_postgresql_url(raw_url)
    database_name = f"ikb_021_{uuid.uuid4().hex}"
    admin_engine = create_engine(
        admin_url,
        connect_args=CONNECT_ARGS,
        future=True,
        pool_pre_ping=True,
    )
    database_created = False
    test_engine: Engine | None = None
    try:
        with admin_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        database_created = True

        test_url = _database_url(admin_url, database_name)
        rendered_url = test_url.render_as_string(hide_password=False)
        test_engine = create_engine(
            test_url,
            connect_args=CONNECT_ARGS,
            future=True,
            pool_pre_ping=True,
        )
        yield PostgresMigrationDb(url=rendered_url, engine=test_engine)
    finally:
        if test_engine is not None:
            test_engine.dispose()
        if database_created:
            with admin_engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) "
                        "FROM pg_stat_activity "
                        "WHERE datname = :database_name "
                        "AND pid <> pg_backend_pid()"
                    ),
                    {"database_name": database_name},
                )
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
        admin_engine.dispose()
