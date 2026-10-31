"""021 source lifecycle (PostgreSQL): downgrade refusals, round trip and Alembic check."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

from tests.ingest.source_lifecycle_postgres.helpers import (
    APPEND_ONLY_FUNCTION,
    LIFECYCLE_TABLES,
    PARENT_SCOPE_UNIQUES,
    PostgresMigrationDb,
    _cfg,
    _guard_function_names,
    _guard_names,
    _seed_claim,
    _seed_event,
    _seed_evidence,
    _seed_generation_head,
    _seed_space,
    _version_rows,
)

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
def test_l5_alembic_check_passes_and_revision_topology_keeps_single_head(
    postgres_migration_db: PostgresMigrationDb,
) -> None:
    config = _cfg(postgres_migration_db.url)
    scripts = ScriptDirectory.from_config(config)
    # 0006 之后由 035 的 0015 续接，G3 产品迁移再顺序续接到 0018。
    # 实际链 0012 → 0006 → 0015 → 0016 → 0017 → 0018 仍只有一个 head。
    assert scripts.get_heads() == ["0018"]
    for revision_id, down_revision in (
        ("0018", "0017"),
        ("0017", "0016"),
        ("0016", "0015"),
        ("0015", "0006"),
    ):
        revision = scripts.get_revision(revision_id)
        assert revision is not None
        assert revision.down_revision == down_revision

    command.upgrade(config, "0012")
    command.upgrade(config, "0006")
    assert _version_rows(postgres_migration_db.engine) == ("0006",)
    command.upgrade(config, "head")
    assert _version_rows(postgres_migration_db.engine) == ("0018",)
    command.check(config)
