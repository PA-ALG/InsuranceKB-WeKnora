"""Real PostgreSQL migration acceptance for OpenSpec 021 L2/L5/L6.

This lane deliberately migrates a disposable PostgreSQL database through Alembic.
It must never be replaced with an ORM metadata shortcut because migration DDL,
PostgreSQL triggers, downgrade preflight, and revision topology are the SUT.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError, DBAPIError

HARNESS_ROOT = Path(__file__).resolve().parents[1]
TEST_POSTGRES_ENV = "HARNESS_TEST_POSTGRES_URL"
LIFECYCLE_TABLES = {
    "source_heads",
    "source_events",
    "source_lifecycle_backfill_issues",
}
APPEND_ONLY_TRIGGERS = {
    "trg_source_events_update_guard_021",
    "trg_source_events_delete_guard_021",
}
APPEND_ONLY_FUNCTION = "guard_source_events_append_only_021"
PARENT_SCOPE_UNIQUES = {
    "knowledge_spaces": "uq_knowledge_spaces_scope_raw",
    "change_sets": "uq_change_sets_space_id",
    "change_items": "uq_change_items_change_set_id",
}
MIGRATION_SCHEMA_TABLES = tuple(sorted(LIFECYCLE_TABLES | set(PARENT_SCOPE_UNIQUES)))
DOWNGRADE_DATA_TABLES = (
    "knowledge_spaces",
    "claims",
    "claim_evidence",
    "change_sets",
    "change_items",
    "source_heads",
    "source_events",
    "source_lifecycle_backfill_issues",
)
CONNECT_ARGS: dict[str, Any] = {
    "connect_timeout": 10,
    "options": "-cstatement_timeout=30000 -clock_timeout=15000",
}


@dataclass(frozen=True)
class PostgresMigrationDb:
    """A random disposable database and its secret-bearing in-process URL."""

    url: str
    engine: Engine


@dataclass(frozen=True)
class PostgresSchemaSnapshot:
    """Normalized 0006 DDL surface that must not change on refused downgrade."""

    alembic_version: tuple[str, ...]
    tables: tuple[str, ...]
    columns: tuple[object, ...]
    foreign_keys: tuple[object, ...]
    checks: tuple[object, ...]
    indexes: tuple[object, ...]
    uniques: tuple[object, ...]
    triggers: tuple[object, ...]
    functions: tuple[object, ...]


@dataclass(frozen=True)
class DowngradeSnapshot:
    schema: PostgresSchemaSnapshot
    data: tuple[object, ...]


def _sync_postgresql_url(raw_url: str) -> URL:
    try:
        url = make_url(raw_url)
    except ArgumentError:
        pytest.fail(f"{TEST_POSTGRES_ENV} must be a valid PostgreSQL URL")
    if url.get_backend_name() != "postgresql":
        pytest.fail(f"{TEST_POSTGRES_ENV} must use PostgreSQL")
    return url.set(drivername="postgresql+psycopg")


def _database_url(admin_url: URL, database_name: str) -> URL:
    """Carry hard timeouts into Alembic's own independently-created connections."""
    return admin_url.set(database=database_name).update_query_dict(
        {
            "application_name": "insurancekb_021_migration_test",
            "connect_timeout": "10",
            "options": "-cstatement_timeout=30000 -clock_timeout=15000",
        }
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


def _cfg(url: str) -> Config:
    config = Config(str(HARNESS_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(HARNESS_ROOT / "migrations"))
    # ConfigParser treats percent-encoded URL components as interpolation tokens.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def _version_rows(engine: Engine) -> tuple[str, ...]:
    with engine.connect() as connection:
        return tuple(
            connection.scalars(
                text("SELECT version_num FROM alembic_version ORDER BY version_num")
            )
        )


def _named_constraints(engine: Engine, table: str, kind: str) -> set[str]:
    inspector = inspect(engine)
    if kind == "unique":
        return {
            str(item["name"])
            for item in inspector.get_unique_constraints(table)
            if item.get("name") is not None
        }
    if kind == "foreign_key":
        return {
            str(item["name"])
            for item in inspector.get_foreign_keys(table)
            if item.get("name") is not None
        }
    if kind == "check":
        return {
            str(item["name"])
            for item in inspector.get_check_constraints(table)
            if item.get("name") is not None
        }
    raise ValueError(f"unsupported constraint kind: {kind}")


def _guard_names(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.scalars(
                text(
                    "SELECT trigger.tgname "
                    "FROM pg_trigger AS trigger "
                    "JOIN pg_class AS relation ON relation.oid = trigger.tgrelid "
                    "JOIN pg_namespace AS namespace "
                    "ON namespace.oid = relation.relnamespace "
                    "WHERE namespace.nspname = current_schema() "
                    "AND relation.relname = 'source_events' "
                    "AND NOT trigger.tgisinternal"
                )
            )
        )


def _guard_function_names(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.scalars(
                text(
                    "SELECT procedure.proname "
                    "FROM pg_proc AS procedure "
                    "JOIN pg_namespace AS namespace "
                    "ON namespace.oid = procedure.pronamespace "
                    "WHERE namespace.nspname = current_schema() "
                    "AND procedure.proname = :function_name"
                ),
                {"function_name": APPEND_ONLY_FUNCTION},
            )
        )


def _guard_definitions(engine: Engine) -> tuple[tuple[object, ...], ...]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT trigger.tgname, pg_get_triggerdef(trigger.oid, true) "
                "FROM pg_trigger AS trigger "
                "JOIN pg_class AS relation ON relation.oid = trigger.tgrelid "
                "JOIN pg_namespace AS namespace "
                "ON namespace.oid = relation.relnamespace "
                "WHERE namespace.nspname = current_schema() "
                "AND relation.relname = 'source_events' "
                "AND NOT trigger.tgisinternal "
                "ORDER BY trigger.tgname"
            )
        )
        return tuple(tuple(row) for row in rows)


def _guard_function_definitions(engine: Engine) -> tuple[tuple[object, ...], ...]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT procedure.proname, "
                "pg_get_function_identity_arguments(procedure.oid), "
                "pg_get_function_result(procedure.oid), procedure.prosrc "
                "FROM pg_proc AS procedure "
                "JOIN pg_namespace AS namespace "
                "ON namespace.oid = procedure.pronamespace "
                "WHERE namespace.nspname = current_schema() "
                "AND procedure.proname = :function_name "
                "ORDER BY procedure.proname"
            ),
            {"function_name": APPEND_ONLY_FUNCTION},
        )
        return tuple(tuple(row) for row in rows)


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value)


def _mapping_tuple(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict):
        return ()
    return tuple(sorted((str(key), repr(item)) for key, item in value.items()))


def _schema_snapshot(engine: Engine) -> PostgresSchemaSnapshot:
    inspector = inspect(engine)
    tables = tuple(
        table for table in MIGRATION_SCHEMA_TABLES if inspector.has_table(table)
    )
    columns = tuple(
        (
            table,
            tuple(
                (
                    str(item["name"]),
                    str(item["type"]),
                    bool(item["nullable"]),
                    repr(item.get("default")),
                    repr(item.get("computed")),
                    repr(item.get("identity")),
                )
                for item in inspector.get_columns(table)
            ),
        )
        for table in tables
    )
    foreign_keys = tuple(
        (
            table,
            tuple(
                sorted(
                    (
                        str(item.get("name")),
                        _string_tuple(item.get("constrained_columns")),
                        str(item.get("referred_schema")),
                        str(item.get("referred_table")),
                        _string_tuple(item.get("referred_columns")),
                        _mapping_tuple(item.get("options")),
                    )
                    for item in inspector.get_foreign_keys(table)
                )
            ),
        )
        for table in tables
    )
    checks = tuple(
        (
            table,
            tuple(
                sorted(
                    (
                        str(item.get("name")),
                        str(item.get("sqltext")),
                        _mapping_tuple(item.get("dialect_options")),
                    )
                    for item in inspector.get_check_constraints(table)
                )
            ),
        )
        for table in tables
    )
    indexes = tuple(
        (
            table,
            tuple(
                sorted(
                    (
                        str(item.get("name")),
                        _string_tuple(item.get("column_names")),
                        _string_tuple(item.get("expressions")),
                        bool(item.get("unique")),
                        str(item.get("duplicates_constraint")),
                        _string_tuple(item.get("include_columns")),
                        _mapping_tuple(item.get("dialect_options")),
                    )
                    for item in inspector.get_indexes(table)
                )
            ),
        )
        for table in tables
    )
    uniques = tuple(
        (
            table,
            tuple(
                sorted(
                    (
                        str(item.get("name")),
                        _string_tuple(item.get("column_names")),
                        str(item.get("duplicates_index")),
                        _mapping_tuple(item.get("dialect_options")),
                    )
                    for item in inspector.get_unique_constraints(table)
                )
            ),
        )
        for table in tables
    )
    return PostgresSchemaSnapshot(
        alembic_version=_version_rows(engine),
        tables=tables,
        columns=columns,
        foreign_keys=foreign_keys,
        checks=checks,
        indexes=indexes,
        uniques=uniques,
        triggers=_guard_definitions(engine),
        functions=_guard_function_definitions(engine),
    )


def _data_snapshot(engine: Engine) -> tuple[object, ...]:
    inspector = inspect(engine)
    with engine.connect() as connection:
        return tuple(
            (
                table,
                tuple(
                    tuple(row)
                    for row in connection.execute(
                        text(f'SELECT * FROM "{table}" ORDER BY id')
                    )
                ),
            )
            for table in DOWNGRADE_DATA_TABLES
            if inspector.has_table(table)
        )


def _downgrade_snapshot(engine: Engine) -> DowngradeSnapshot:
    return DowngradeSnapshot(
        schema=_schema_snapshot(engine),
        data=_data_snapshot(engine),
    )


def _seed_space(
    engine: Engine,
    *,
    space_id: str,
    tenant_id: str,
    raw_kb_id: str,
    now: datetime,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge_spaces "
                "(id, tenant_id, raw_kb_id, wiki_kb_id, name, binding_status, "
                "created_at, updated_at) VALUES "
                "(:space_id, :tenant_id, :raw_kb_id, :wiki_kb_id, :name, "
                "'bound', :now, :now)"
            ),
            {
                "space_id": space_id,
                "tenant_id": tenant_id,
                "raw_kb_id": raw_kb_id,
                "wiki_kb_id": f"wiki-{space_id}",
                "name": space_id,
                "now": now,
            },
        )


def _seed_claim(engine: Engine, *, claim_id: str, space_id: str, now: datetime) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO claims "
                "(id, space_id, subject_type, product_version_id, concept_id, "
                "predicate, value_state, value, effective_from, effective_to, status, "
                "confidence, extraction_method, schema_version, current_revision, "
                "superseded_by, pending_judge, created_at, updated_at) VALUES "
                "(:id, :space_id, 'product_version', NULL, NULL, :predicate, "
                "'present', NULL, NULL, NULL, 'draft', 0.5, 'llm', 'v1', 0, "
                "NULL, FALSE, :now, :now)"
            ),
            {
                "id": claim_id,
                "space_id": space_id,
                "predicate": f"predicate-{claim_id}",
                "now": now,
            },
        )


def _seed_evidence(
    engine: Engine,
    *,
    evidence_id: str,
    claim_id: str,
    knowledge_id: str,
    raw_kb_id: str,
    revision: str,
    now: datetime,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO claim_evidence "
                "(id, claim_id, knowledge_id, chunk_id, quote, page, section, "
                "table_ref, timestamp_ms, authority_level, doc_role, extraction_method, "
                "extracted_at, raw_kb_id, source_revision, file_hash, original_digest, "
                "parser_version, chunk_hash, lineage_status, stale_at, created_at, "
                "updated_at) VALUES "
                "(:id, :claim_id, :knowledge_id, NULL, :quote, 1, NULL, NULL, NULL, "
                "1, 'terms', 'llm', :now, :raw_kb_id, :revision, :file_hash, "
                ":original_digest, :parser_version, NULL, 'page_only', NULL, "
                ":now, :now)"
            ),
            {
                "id": evidence_id,
                "claim_id": claim_id,
                "knowledge_id": knowledge_id,
                "quote": evidence_id,
                "now": now,
                "raw_kb_id": raw_kb_id,
                "revision": revision,
                "file_hash": "f" * 32,
                "original_digest": "e" * 64,
                "parser_version": "pdfplumber@0.11:text-v1",
            },
        )


def _seed_change_set(
    engine: Engine,
    *,
    change_set_id: str,
    space_id: str,
    knowledge_id: str,
    revision: str,
    now: datetime,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO change_sets "
                "(id, space_id, source_kind, knowledge_ids, external_record_id, "
                "source_revision, status, created_by, created_at, updated_at) VALUES "
                "(:id, :space_id, 'document', CAST(:knowledge_ids AS JSON), "
                ":knowledge_id, :revision, 'applied', 'historical-test', :now, :now)"
            ),
            {
                "id": change_set_id,
                "space_id": space_id,
                "knowledge_ids": json.dumps([knowledge_id]),
                "knowledge_id": knowledge_id,
                "revision": revision,
                "now": now,
            },
        )


def _seed_generation_head(engine: Engine, *, now: datetime) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO source_heads "
                "(id, space_id, tenant_id, raw_kb_id, knowledge_id, head_revision, "
                "ordering_kind, ordering_processed_at, ordering_generation, state, "
                "version, last_event_id, actor, head_updated_at, created_at, updated_at) "
                "VALUES ('head-a', 'space-a', 'tenant-a', 'raw-a', 'knowledge-a', "
                ":revision, 'generation', NULL, 1, 'active', 1, NULL, 'tester', "
                ":now, :now, :now)"
            ),
            {"revision": "a" * 64, "now": now},
        )


def _seed_event(engine: Engine, *, now: datetime) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO source_events "
                "(id, space_id, tenant_id, raw_kb_id, knowledge_id, input_revision, "
                "ordering_kind, ordering_processed_at, ordering_generation, desired_state, "
                "decision, before_head, after_head, causation_id, actor, decided_at, "
                "change_set_id, tombstone_change_item_id, created_at) VALUES "
                "('event-a', 'space-a', 'tenant-a', 'raw-a', 'knowledge-a', :revision, "
                "'generation', NULL, 1, 'active', 'accepted_create', NULL, "
                "CAST(:after_head AS JSON), 'cause-a', 'tester', :now, NULL, NULL, :now)"
            ),
            {"revision": "a" * 64, "after_head": "{}", "now": now},
        )


def _seed_backfill_issue(engine: Engine, *, now: datetime) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO source_lifecycle_backfill_issues "
                "(id, space_id, tenant_id, raw_kb_id, knowledge_id, "
                "observed_revisions, reason, status, created_at, updated_at) VALUES "
                "('issue-a', 'space-a', 'tenant-a', 'raw-a', 'knowledge-a', "
                "CAST(:observed_revisions AS JSON), :reason, 'open', :now, :now)"
            ),
            {
                "observed_revisions": json.dumps(["a" * 64]),
                "reason": "historical ordering unavailable",
                "now": now,
            },
        )


def _leave_source_event_as_only_lifecycle_row(engine: Engine) -> None:
    """Restore the event FK as NOT VALID so an orphan can exercise event-only guard."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE source_events "
                "DROP CONSTRAINT fk_source_events_scoped_head"
            )
        )
        connection.execute(text("DELETE FROM source_heads"))
        connection.execute(
            text(
                "ALTER TABLE source_events "
                "ADD CONSTRAINT fk_source_events_scoped_head "
                "FOREIGN KEY (space_id, tenant_id, raw_kb_id, knowledge_id) "
                "REFERENCES source_heads "
                "(space_id, tenant_id, raw_kb_id, knowledge_id) NOT VALID"
            )
        )


def _lifecycle_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table: int(
                connection.scalar(text(f'SELECT count(*) FROM "{table}"')) or 0
            )
            for table in sorted(LIFECYCLE_TABLES)
        }


def _seed_downgrade_guard_state(
    engine: Engine,
    guard_state: Literal[
        "source_head",
        "source_event",
        "backfill_issue",
        "historical_provenance",
    ],
) -> dict[str, int]:
    now = datetime.now(UTC)
    _seed_space(
        engine,
        space_id="space-a",
        tenant_id="tenant-a",
        raw_kb_id="raw-a",
        now=now,
    )
    if guard_state == "source_head":
        _seed_generation_head(engine, now=now)
    elif guard_state == "source_event":
        _seed_generation_head(engine, now=now)
        _seed_event(engine, now=now)
        _leave_source_event_as_only_lifecycle_row(engine)
    elif guard_state == "backfill_issue":
        _seed_backfill_issue(engine, now=now)
    else:
        _seed_claim(engine, claim_id="claim-a", space_id="space-a", now=now)
        _seed_evidence(
            engine,
            evidence_id="evidence-a",
            claim_id="claim-a",
            knowledge_id="knowledge-a",
            raw_kb_id="raw-a",
            revision="a" * 64,
            now=now,
        )

    expected = {
        "source_head": {
            "source_heads": 1,
            "source_events": 0,
            "source_lifecycle_backfill_issues": 0,
        },
        "source_event": {
            "source_heads": 0,
            "source_events": 1,
            "source_lifecycle_backfill_issues": 0,
        },
        "backfill_issue": {
            "source_heads": 0,
            "source_events": 0,
            "source_lifecycle_backfill_issues": 1,
        },
        "historical_provenance": {
            "source_heads": 0,
            "source_events": 0,
            "source_lifecycle_backfill_issues": 0,
        },
    }[guard_state]
    assert _lifecycle_counts(engine) == expected
    return expected


@pytest.mark.integration_postgres
def test_l5_0012_to_0006_installs_postgresql_schema_constraints_and_append_only_guards(
    postgres_migration_db: PostgresMigrationDb,
) -> None:
    config = _cfg(postgres_migration_db.url)
    command.upgrade(config, "0012")
    assert _version_rows(postgres_migration_db.engine) == ("0012",)
    command.upgrade(config, "0006")

    engine = postgres_migration_db.engine
    inspector = inspect(engine)
    assert LIFECYCLE_TABLES <= set(inspector.get_table_names())
    assert {
        "uq_source_heads_space_knowledge",
        "uq_source_heads_scoped_source",
    } <= _named_constraints(engine, "source_heads", "unique")
    assert {"uq_source_events_source_id"} <= _named_constraints(
        engine, "source_events", "unique"
    )
    assert {"uq_source_lifecycle_issues_space_knowledge"} <= _named_constraints(
        engine, "source_lifecycle_backfill_issues", "unique"
    )
    assert {
        "fk_source_heads_scope_raw",
        "fk_source_heads_last_event",
    } <= _named_constraints(engine, "source_heads", "foreign_key")
    assert {
        "fk_source_events_scope_raw",
        "fk_source_events_scoped_head",
        "fk_source_events_space_change_set",
        "fk_source_events_tombstone_item",
    } <= _named_constraints(engine, "source_events", "foreign_key")
    assert {"fk_source_lifecycle_issues_scope_raw"} <= _named_constraints(
        engine, "source_lifecycle_backfill_issues", "foreign_key"
    )
    assert {
        "ck_source_heads_ordering_shape",
        "ck_source_heads_state",
        "ck_source_heads_version",
    } <= _named_constraints(engine, "source_heads", "check")
    assert {
        "ck_source_events_ordering_shape",
        "ck_source_events_desired_state",
        "ck_source_events_decision",
        "ck_source_events_tombstone_link",
    } <= _named_constraints(engine, "source_events", "check")
    for table, unique_name in PARENT_SCOPE_UNIQUES.items():
        assert unique_name in _named_constraints(engine, table, "unique")
    assert APPEND_ONLY_TRIGGERS <= _guard_names(engine)
    assert APPEND_ONLY_FUNCTION in _guard_function_names(engine)

    now = datetime.now(UTC)
    _seed_space(
        engine,
        space_id="space-a",
        tenant_id="tenant-a",
        raw_kb_id="raw-a",
        now=now,
    )
    _seed_generation_head(engine, now=now)
    _seed_event(engine, now=now)

    with pytest.raises(DBAPIError, match="source events are append-only"):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE source_events SET actor='mutator' WHERE id='event-a'")
            )
    with pytest.raises(DBAPIError, match="source events are append-only"):
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM source_events WHERE id='event-a'"))
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT actor, decision FROM source_events WHERE id='event-a'")
        ).one() == ("tester", "accepted_create")


@pytest.mark.integration_postgres
def test_l5_historical_0012_rows_create_zero_heads_and_one_open_issue_per_source(
    postgres_migration_db: PostgresMigrationDb,
) -> None:
    config = _cfg(postgres_migration_db.url)
    command.upgrade(config, "0012")
    engine = postgres_migration_db.engine
    now = datetime(2026, 7, 19, tzinfo=UTC)
    _seed_space(
        engine,
        space_id="space-a",
        tenant_id="tenant-a",
        raw_kb_id="raw-a",
        now=now,
    )
    _seed_space(
        engine,
        space_id="space-b",
        tenant_id="tenant-b",
        raw_kb_id="raw-b",
        now=now,
    )
    _seed_claim(engine, claim_id="claim-a", space_id="space-a", now=now)
    _seed_claim(engine, claim_id="claim-b", space_id="space-b", now=now)
    _seed_evidence(
        engine,
        evidence_id="evidence-a-a",
        claim_id="claim-a",
        knowledge_id="knowledge-a",
        raw_kb_id="raw-a",
        revision="a" * 64,
        now=now,
    )
    _seed_evidence(
        engine,
        evidence_id="evidence-a-b",
        claim_id="claim-a",
        knowledge_id="knowledge-a",
        raw_kb_id="raw-a",
        revision="b" * 64,
        now=now,
    )
    _seed_evidence(
        engine,
        evidence_id="evidence-b-c",
        claim_id="claim-b",
        knowledge_id="knowledge-a",
        raw_kb_id="raw-b",
        revision="c" * 64,
        now=now,
    )
    # Duplicate one Evidence observation through ChangeSet and add a ChangeSet-only source.
    _seed_change_set(
        engine,
        change_set_id="changeset-a-b",
        space_id="space-a",
        knowledge_id="knowledge-a",
        revision="b" * 64,
        now=now,
    )
    _seed_change_set(
        engine,
        change_set_id="changeset-a-d",
        space_id="space-a",
        knowledge_id="knowledge-c",
        revision="d" * 64,
        now=now,
    )

    command.upgrade(config, "0006")

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM source_heads")) == 0
        issue_rows = connection.execute(
            text(
                "SELECT space_id, tenant_id, raw_kb_id, knowledge_id, "
                "observed_revisions, status "
                "FROM source_lifecycle_backfill_issues "
                "ORDER BY space_id, knowledge_id"
            )
        ).mappings().all()
        duplicate_open_sources = connection.execute(
            text(
                "SELECT space_id, knowledge_id "
                "FROM source_lifecycle_backfill_issues "
                "WHERE status = 'open' "
                "GROUP BY space_id, knowledge_id HAVING count(*) <> 1"
            )
        ).all()

    assert duplicate_open_sources == []
    assert [
        (
            row["space_id"],
            row["tenant_id"],
            row["raw_kb_id"],
            row["knowledge_id"],
            row["observed_revisions"],
            row["status"],
        )
        for row in issue_rows
    ] == [
        ("space-a", "tenant-a", "raw-a", "knowledge-a", ["a" * 64, "b" * 64], "open"),
        ("space-a", "tenant-a", "raw-a", "knowledge-c", ["d" * 64], "open"),
        ("space-b", "tenant-b", "raw-b", "knowledge-a", ["c" * 64], "open"),
    ]


@pytest.mark.integration_postgres
@pytest.mark.parametrize(
    "guard_state",
    ["source_head", "source_event", "backfill_issue", "historical_provenance"],
)
def test_l5_nonempty_lifecycle_or_provenance_downgrade_fails_before_any_ddl(
    postgres_migration_db: PostgresMigrationDb,
    guard_state: Literal[
        "source_head",
        "source_event",
        "backfill_issue",
        "historical_provenance",
    ],
) -> None:
    config = _cfg(postgres_migration_db.url)
    command.upgrade(config, "0006")
    engine = postgres_migration_db.engine
    expected_counts = _seed_downgrade_guard_state(engine, guard_state)
    before = _downgrade_snapshot(engine)

    with pytest.raises(RuntimeError, match="0006 downgrade refused before DDL"):
        command.downgrade(config, "0012")

    assert _downgrade_snapshot(engine) == before
    assert before.schema.alembic_version == ("0006",)
    assert _lifecycle_counts(engine) == expected_counts


@pytest.mark.integration_postgres
def test_l5_empty_0006_to_0012_to_0006_round_trip_restores_postgresql_schema(
    postgres_migration_db: PostgresMigrationDb,
) -> None:
    config = _cfg(postgres_migration_db.url)
    command.upgrade(config, "0006")
    engine = postgres_migration_db.engine
    before_schema = _schema_snapshot(engine)

    command.downgrade(config, "0012")
    assert _version_rows(engine) == ("0012",)
    assert LIFECYCLE_TABLES.isdisjoint(inspect(engine).get_table_names())
    assert _guard_names(engine) == set()
    assert _guard_function_names(engine) == set()

    command.upgrade(config, "0006")
    assert _version_rows(engine) == ("0006",)
    assert _schema_snapshot(engine) == before_schema


@pytest.mark.integration_postgres
def test_l5_alembic_check_passes_and_revision_topology_has_single_0006_head(
    postgres_migration_db: PostgresMigrationDb,
) -> None:
    config = _cfg(postgres_migration_db.url)
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["0006"]

    command.upgrade(config, "0012")
    command.upgrade(config, "0006")
    assert _version_rows(postgres_migration_db.engine) == ("0006",)
    command.check(config)
