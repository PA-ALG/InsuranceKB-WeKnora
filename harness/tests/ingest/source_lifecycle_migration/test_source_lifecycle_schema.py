"""021 source lifecycle (SQLite): 0006 topology, ORM roots and schema guards."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine.interfaces import ReflectedForeignKeyConstraint
from sqlalchemy.exc import IntegrityError

from insurance_harness.db import models as _db_models  # noqa: F401
from insurance_harness.db.base import Base
from insurance_harness.knowledge import tables as _knowledge_tables  # noqa: F401
from tests.ingest.source_lifecycle_migration.helpers import (
    LIFECYCLE_TABLES,
    MIGRATION_PATH,
    _assert_current_migration_topology,
    _cfg,
    _db,
    _insert_event,
    _insert_generation_head,
    _seed_bound_space,
)

SOURCE_EVENT_DECISIONS = {
    "accepted_create",
    "accepted_advance",
    "accepted_delete",
    "accepted_reactivate",
    "idempotent",
    "stale",
    "blocked_deleted",
}
APPEND_ONLY_TRIGGERS = {
    "trg_source_events_update_guard_021",
    "trg_source_events_delete_guard_021",
}


def _foreign_key_shape(
    item: ReflectedForeignKeyConstraint,
) -> tuple[tuple[str, ...], str, tuple[str, ...]]:
    return (
        tuple(item["constrained_columns"]),
        str(item["referred_table"]),
        tuple(item["referred_columns"]),
    )


def test_l5_schema_0006_revises_actual_0012_and_chain_keeps_single_head() -> None:
    assert MIGRATION_PATH.is_file()
    script = ScriptDirectory.from_config(_cfg("sqlite://"))

    # 实际链 0012 → 0006 → 0015 → 0016 → 0017 → 0018 只有一个 head。
    _assert_current_migration_topology(script)


def test_l2_orm_declares_durable_lifecycle_roots_and_scope_closure() -> None:
    assert LIFECYCLE_TABLES <= set(Base.metadata.tables)

    heads = Base.metadata.tables["source_heads"]
    events = Base.metadata.tables["source_events"]
    issues = Base.metadata.tables["source_lifecycle_backfill_issues"]

    assert {
        "space_id",
        "tenant_id",
        "raw_kb_id",
        "knowledge_id",
        "head_revision",
        "ordering_kind",
        "ordering_processed_at",
        "ordering_generation",
        "state",
        "version",
        "last_event_id",
        "actor",
        "head_updated_at",
    } <= set(heads.c.keys())
    assert {
        "input_revision",
        "desired_state",
        "decision",
        "before_head",
        "after_head",
        "causation_id",
        "change_set_id",
        "tombstone_change_item_id",
    } <= set(events.c.keys())
    assert {
        "observed_revisions",
        "reason",
        "status",
        "resolved_revision",
        "resolved_ordering_kind",
        "resolved_processed_at",
        "resolved_generation",
        "expected_state",
        "resolved_by",
        "resolution_reason",
        "resolved_at",
    } <= set(issues.c.keys())


def test_l2_schema_creates_scoped_roots_strict_checks_and_indexes(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "schema")
    command.upgrade(_cfg(url), "0006")
    inspector = inspect(engine)

    assert LIFECYCLE_TABLES <= set(inspector.get_table_names())
    assert ("space_id", "knowledge_id") in {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints("source_heads")
    }
    assert ("space_id", "knowledge_id") in {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints("source_lifecycle_backfill_issues")
    }

    head_fks = {
        _foreign_key_shape(item) for item in inspector.get_foreign_keys("source_heads")
    }
    event_fks = {
        _foreign_key_shape(item) for item in inspector.get_foreign_keys("source_events")
    }
    issue_fks = {
        _foreign_key_shape(item)
        for item in inspector.get_foreign_keys("source_lifecycle_backfill_issues")
    }
    scope_fk = (
        ("space_id", "tenant_id", "raw_kb_id"),
        "knowledge_spaces",
        ("id", "tenant_id", "raw_kb_id"),
    )
    assert scope_fk in head_fks
    assert scope_fk in event_fks
    assert scope_fk in issue_fks
    assert (
        ("space_id", "tenant_id", "raw_kb_id", "knowledge_id"),
        "source_heads",
        ("space_id", "tenant_id", "raw_kb_id", "knowledge_id"),
    ) in event_fks

    head_checks = {item["name"] for item in inspector.get_check_constraints("source_heads")}
    event_checks = {item["name"] for item in inspector.get_check_constraints("source_events")}
    issue_checks = {
        item["name"]
        for item in inspector.get_check_constraints("source_lifecycle_backfill_issues")
    }
    assert {
        "ck_source_heads_ordering_shape",
        "ck_source_heads_state",
        "ck_source_heads_version",
    } <= head_checks
    assert {
        "ck_source_events_ordering_shape",
        "ck_source_events_desired_state",
        "ck_source_events_decision",
        "ck_source_events_tombstone_link",
    } <= event_checks
    assert {
        "ck_source_lifecycle_issues_status",
        "ck_source_lifecycle_issues_resolution_shape",
    } <= issue_checks

    index_names = {
        item["name"]
        for table in LIFECYCLE_TABLES
        for item in inspector.get_indexes(table)
    }
    assert {
        "ix_source_heads_scope_state",
        "ix_source_events_source_time",
        "ix_source_events_scope_decision",
        "ix_source_lifecycle_issues_scope_status",
    } <= index_names


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"ordering_generation": -1}, "ck_source_heads_ordering_shape"),
        (
            {
                "ordering_kind": "processed_at",
                "ordering_generation": None,
                "ordering_processed_at": None,
            },
            "ck_source_heads_ordering_shape",
        ),
        ({"state": "unknown"}, "ck_source_heads_state"),
        ({"version": 0}, "ck_source_heads_version"),
    ],
)
def test_l2_schema_rejects_invalid_head_shapes(
    tmp_path: Path,
    overrides: dict[str, object],
    constraint: str,
) -> None:
    url, engine = _db(tmp_path, constraint)
    command.upgrade(_cfg(url), "0006")
    now = _seed_bound_space(engine)
    values: dict[str, object] = {
        "id": "bad-head",
        "space_id": "space-a",
        "tenant_id": "tenant-a",
        "raw_kb_id": "raw-a",
        "knowledge_id": "knowledge-a",
        "head_revision": "a" * 64,
        "ordering_kind": "generation",
        "ordering_processed_at": None,
        "ordering_generation": 1,
        "state": "active",
        "version": 1,
        "last_event_id": None,
        "actor": "tester",
        "head_updated_at": now,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)

    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO source_heads "
                "(id, space_id, tenant_id, raw_kb_id, knowledge_id, head_revision, "
                "ordering_kind, ordering_processed_at, ordering_generation, state, "
                "version, last_event_id, actor, head_updated_at, created_at, updated_at) "
                "VALUES (:id, :space_id, :tenant_id, :raw_kb_id, :knowledge_id, "
                ":head_revision, :ordering_kind, :ordering_processed_at, "
                ":ordering_generation, :state, :version, :last_event_id, :actor, "
                ":head_updated_at, :created_at, :updated_at)"
            ),
            values,
        )


def test_l2_schema_rejects_cross_scope_head(tmp_path: Path) -> None:
    url, engine = _db(tmp_path, "cross-scope")
    command.upgrade(_cfg(url), "0006")
    now = _seed_bound_space(engine)

    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO source_heads "
                "(id, space_id, tenant_id, raw_kb_id, knowledge_id, head_revision, "
                "ordering_kind, ordering_generation, state, version, actor, "
                "head_updated_at, created_at, updated_at) VALUES "
                "('head-a', 'space-a', 'tenant-b', 'raw-a', 'knowledge-a', :revision, "
                "'generation', 1, 'active', 1, 'tester', :now, :now, :now)"
            ),
            {"revision": "a" * 64, "now": now},
        )


def test_l2_append_only_schema_rejects_source_event_update_and_delete(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "append-only")
    command.upgrade(_cfg(url), "0006")
    now = _seed_bound_space(engine)
    _insert_generation_head(engine, now=now)
    _insert_event(engine, now=now)

    with engine.begin() as connection, pytest.raises(IntegrityError, match="append-only"):
        connection.execute(
            text("UPDATE source_events SET actor='mutator' WHERE id='event-a'")
        )
    with engine.begin() as connection, pytest.raises(IntegrityError, match="append-only"):
        connection.execute(text("DELETE FROM source_events WHERE id='event-a'"))

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT actor, decision FROM source_events WHERE id='event-a'")
        ).one() == ("tester", "accepted_create")


def test_l2_schema_rejects_unknown_event_decision(tmp_path: Path) -> None:
    url, engine = _db(tmp_path, "decision-enum")
    command.upgrade(_cfg(url), "0006")
    now = _seed_bound_space(engine)
    _insert_generation_head(engine, now=now)

    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO source_events "
                "(id, space_id, tenant_id, raw_kb_id, knowledge_id, input_revision, "
                "ordering_kind, ordering_generation, desired_state, decision, "
                "actor, decided_at, created_at) VALUES "
                "('event-bad', 'space-a', 'tenant-a', 'raw-a', 'knowledge-a', "
                ":revision, 'generation', 1, 'active', 'accepted_magic', "
                "'tester', :now, :now)"
            ),
            {"revision": "a" * 64, "now": now},
        )


def test_l2_append_only_schema_installs_dialect_guards(tmp_path: Path) -> None:
    url, engine = _db(tmp_path, "guard-shape")
    command.upgrade(_cfg(url), "0006")

    with engine.connect() as connection:
        sqlite_triggers = set(
            connection.scalars(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='trigger' AND name LIKE '%_021'"
                )
            )
        )
    assert APPEND_ONLY_TRIGGERS <= sqlite_triggers

    output = StringIO()
    command.upgrade(
        _cfg("postgresql://user:password@localhost/insurance", output=output),
        "0012:0006",
        sql=True,
    )
    ddl = output.getvalue().lower()
    assert LIFECYCLE_TABLES <= {table for table in LIFECYCLE_TABLES if table in ddl}
    assert all(decision in ddl for decision in SOURCE_EVENT_DECISIONS)
    assert all(trigger in ddl for trigger in APPEND_ONLY_TRIGGERS)
    assert "returns trigger" in ddl and "source events are append-only" in ddl
