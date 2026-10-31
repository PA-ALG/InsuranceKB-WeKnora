"""021 source lifecycle (PostgreSQL): 0012→0006 schema, guards and historical backfill."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import DBAPIError

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

APPEND_ONLY_TRIGGERS = {
    "trg_source_events_update_guard_021",
    "trg_source_events_delete_guard_021",
}


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
