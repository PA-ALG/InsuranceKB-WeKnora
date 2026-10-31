"""021 source lifecycle (SQLite): downgrade refusals and the empty round trip."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

from insurance_harness.db import models as _db_models  # noqa: F401
from insurance_harness.knowledge import tables as _knowledge_tables  # noqa: F401
from tests.ingest.source_lifecycle_migration.helpers import (
    LIFECYCLE_TABLES,
    PARENT_SCOPE_UNIQUES,
    _alembic_version,
    _assert_current_migration_topology,
    _cfg,
    _db,
    _first_ddl_signature,
    _insert_event,
    _insert_generation_head,
    _parent_unique_signature,
    _seed_bound_space,
    _seed_claim,
    _seed_evidence,
    _seed_space,
    _sqlite_lifecycle_ddl,
)


def _lifecycle_schema_signature(engine: Engine) -> dict[str, object]:
    inspector = inspect(engine)
    tables: dict[str, object] = {}
    for table in sorted(LIFECYCLE_TABLES):
        tables[table] = {
            "columns": sorted(
                (
                    column["name"],
                    str(column["type"]),
                    column["nullable"],
                    column.get("default"),
                    column.get("primary_key", 0),
                )
                for column in inspector.get_columns(table)
            ),
            "uniques": sorted(
                (
                    item["name"],
                    tuple(item["column_names"]),
                )
                for item in inspector.get_unique_constraints(table)
            ),
            "foreign_keys": sorted(
                (
                    item["name"],
                    tuple(item["constrained_columns"]),
                    item["referred_table"],
                    tuple(item["referred_columns"]),
                )
                for item in inspector.get_foreign_keys(table)
            ),
            "checks": sorted(
                (
                    item["name"],
                    " ".join(str(item["sqltext"]).split()),
                )
                for item in inspector.get_check_constraints(table)
            ),
            "indexes": sorted(
                (
                    item["name"],
                    tuple(item["column_names"]),
                    item["unique"],
                )
                for item in inspector.get_indexes(table)
            ),
        }
    with engine.connect() as connection:
        triggers = sorted(
            connection.scalars(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='trigger' AND name LIKE '%_021'"
                )
            )
        )
    return {"tables": tables, "triggers": triggers}


def _insert_backfill_issue(
    engine: Engine,
    *,
    now: datetime,
    status: str,
) -> None:
    resolved = status == "resolved"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO source_lifecycle_backfill_issues "
                "(id, space_id, tenant_id, raw_kb_id, knowledge_id, "
                "observed_revisions, reason, status, resolved_revision, "
                "resolved_ordering_kind, resolved_processed_at, resolved_generation, "
                "expected_state, resolved_by, resolution_reason, resolved_at, "
                "created_at, updated_at) VALUES "
                "('issue-a', 'space-a', 'tenant-a', 'raw-a', 'knowledge-a', "
                ":revisions, 'manual-resolution-required', :status, "
                ":resolved_revision, :resolved_kind, NULL, :resolved_generation, "
                ":expected_state, :resolved_by, :resolution_reason, :resolved_at, "
                ":now, :now)"
            ),
            {
                "revisions": json.dumps(["a" * 64]),
                "status": status,
                "resolved_revision": "a" * 64 if resolved else None,
                "resolved_kind": "generation" if resolved else None,
                "resolved_generation": 1 if resolved else None,
                "expected_state": "active" if resolved else None,
                "resolved_by": "admin" if resolved else None,
                "resolution_reason": "verified source order" if resolved else None,
                "resolved_at": now if resolved else None,
                "now": now,
            },
        )


@pytest.mark.parametrize(
    "durable_state",
    ["head", "event", "open_issue", "resolved_issue"],
)
def test_l5_downgrade_refuses_any_durable_lifecycle_state_before_first_ddl(
    tmp_path: Path,
    durable_state: str,
) -> None:
    url, engine = _db(tmp_path, f"downgrade-{durable_state}")
    command.upgrade(_cfg(url), "0006")
    now = _seed_bound_space(engine)
    if durable_state in {"head", "event"}:
        _insert_generation_head(engine, now=now)
    if durable_state == "event":
        _insert_event(engine, now=now)
    if durable_state in {"open_issue", "resolved_issue"}:
        _insert_backfill_issue(
            engine,
            now=now,
            status="resolved" if durable_state == "resolved_issue" else "open",
        )

    before_ddl = _first_ddl_signature(engine)
    before_counts: dict[str, int] = {}
    with engine.connect() as connection:
        for table in LIFECYCLE_TABLES:
            before_counts[table] = int(
                connection.scalar(text(f"SELECT count(*) FROM {table}")) or 0  # noqa: S608
            )

    with pytest.raises(RuntimeError, match="0006 downgrade refused"):
        command.downgrade(_cfg(url), "0012")

    assert _first_ddl_signature(engine) == before_ddl
    assert _alembic_version(engine) == "0006"
    with engine.connect() as connection:
        for table, expected_count in before_counts.items():
            assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == expected_count  # noqa: S608


def test_l5_downgrade_refuses_source_aware_provenance_without_ledger_before_first_ddl(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "downgrade-provenance")
    command.upgrade(_cfg(url), "0006")
    now = datetime(2026, 7, 19, tzinfo=UTC)
    _seed_space(
        engine,
        space_id="space-a",
        tenant_id="tenant-a",
        raw_kb_id="raw-a",
        now=now,
    )
    _seed_claim(engine, claim_id="claim-a", space_id="space-a", now=now)
    _seed_evidence(
        engine,
        evidence_id="evidence-a",
        claim_id="claim-a",
        knowledge_id="knowledge-a",
        raw_kb_id="raw-a",
        revision="a" * 64,
        extracted_at=now,
    )
    before_ddl = _first_ddl_signature(engine)

    with pytest.raises(RuntimeError, match="0006 downgrade refused.*provenance"):
        command.downgrade(_cfg(url), "0012")

    assert _first_ddl_signature(engine) == before_ddl
    assert _alembic_version(engine) == "0006"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM claim_evidence")) == 1


def test_l5_downgrade_allows_legacy_evidence_without_source_provenance(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "downgrade-legacy-evidence")
    command.upgrade(_cfg(url), "0006")
    now = datetime(2026, 7, 19, tzinfo=UTC)
    _seed_space(
        engine,
        space_id="space-a",
        tenant_id="tenant-a",
        raw_kb_id="raw-a",
        now=now,
    )
    _seed_claim(engine, claim_id="claim-a", space_id="space-a", now=now)
    _seed_evidence(
        engine,
        evidence_id="legacy-evidence-a",
        claim_id="claim-a",
        knowledge_id="legacy-knowledge-a",
        raw_kb_id=None,
        revision=None,
        extracted_at=now,
        source_aware=False,
    )

    command.downgrade(_cfg(url), "0012")

    assert LIFECYCLE_TABLES.isdisjoint(inspect(engine).get_table_names())
    assert _alembic_version(engine) == "0012"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM claim_evidence")) == 1


def test_l5_empty_downgrade_removes_0006_objects_and_roll_forward_is_equivalent(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "empty-roll-forward")
    command.upgrade(_cfg(url), "0006")
    before_schema = {
        "lifecycle": _lifecycle_schema_signature(engine),
        "parent_uniques": _parent_unique_signature(engine),
    }

    command.downgrade(_cfg(url), "0012")

    assert LIFECYCLE_TABLES.isdisjoint(inspect(engine).get_table_names())
    assert _sqlite_lifecycle_ddl(engine) == []
    for table, unique_name in PARENT_SCOPE_UNIQUES.items():
        assert unique_name not in {
            item["name"] for item in inspect(engine).get_unique_constraints(table)
        }
    assert _alembic_version(engine) == "0012"

    command.upgrade(_cfg(url), "0006")

    assert {
        "lifecycle": _lifecycle_schema_signature(engine),
        "parent_uniques": _parent_unique_signature(engine),
    } == before_schema
    # 本测试固定校验 0006 段的往返等价，同时核对当前完整迁移链。
    _assert_current_migration_topology(ScriptDirectory.from_config(_cfg(url)))
    assert _alembic_version(engine) == "0006"
