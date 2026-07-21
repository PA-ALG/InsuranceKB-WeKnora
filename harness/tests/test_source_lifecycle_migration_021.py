"""OpenSpec 021 source lifecycle migration contracts."""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import Connection, Engine, create_engine, event, inspect, text
from sqlalchemy.engine.interfaces import ReflectedForeignKeyConstraint
from sqlalchemy.exc import IntegrityError

from insurance_harness.db import models as _db_models  # noqa: F401
from insurance_harness.db.base import Base
from insurance_harness.knowledge import tables as _knowledge_tables  # noqa: F401

HARNESS_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = HARNESS_ROOT / "migrations" / "versions" / "0006_source_lifecycle_ordering.py"
LIFECYCLE_TABLES = {
    "source_heads",
    "source_events",
    "source_lifecycle_backfill_issues",
}
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
PARENT_SCOPE_UNIQUES = {
    "knowledge_spaces": "uq_knowledge_spaces_scope_raw",
    "change_sets": "uq_change_sets_space_id",
    "change_items": "uq_change_items_change_set_id",
}


def _cfg(url: str, *, output: StringIO | None = None) -> Config:
    config = Config(str(HARNESS_ROOT / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(HARNESS_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _db(tmp_path: Path, name: str) -> tuple[str, Engine]:
    url = f"sqlite:///{tmp_path}/{name}.db"
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return url, engine


def _seed_bound_space(engine: Engine) -> datetime:
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge_spaces "
                "(id, tenant_id, raw_kb_id, wiki_kb_id, name, binding_status, "
                "created_at, updated_at) VALUES "
                "('space-a', 'tenant-a', 'raw-a', 'wiki-a', 'Space A', "
                "'bound', :now, :now)"
            ),
            {"now": now},
        )
    return now


def _insert_generation_head(engine: Engine, *, now: datetime) -> None:
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


def _insert_event(engine: Engine, *, now: datetime) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO source_events "
                "(id, space_id, tenant_id, raw_kb_id, knowledge_id, input_revision, "
                "ordering_kind, ordering_processed_at, ordering_generation, desired_state, "
                "decision, before_head, after_head, causation_id, actor, decided_at, "
                "change_set_id, tombstone_change_item_id, created_at) VALUES "
                "('event-a', 'space-a', 'tenant-a', 'raw-a', 'knowledge-a', :revision, "
                "'generation', NULL, 1, 'active', 'accepted_create', NULL, :after_head, "
                "'cause-a', 'tester', :now, NULL, NULL, :now)"
            ),
            {"revision": "a" * 64, "after_head": "{}", "now": now},
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


def _seed_claim(
    engine: Engine,
    *,
    claim_id: str,
    space_id: str,
    now: datetime,
) -> None:
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
                "NULL, 0, :now, :now)"
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
    raw_kb_id: str | None,
    revision: str | None,
    extracted_at: datetime,
    source_aware: bool = True,
) -> None:
    lineage = "page_only" if source_aware else None
    file_hash = "a" * 32 if source_aware else None
    original_digest = "b" * 64 if source_aware else None
    parser_version = "pdfplumber@0.11:text-v1" if source_aware else None
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
                "1, 'terms', 'llm', :extracted_at, :raw_kb_id, :revision, :file_hash, "
                ":original_digest, :parser_version, NULL, :lineage, NULL, "
                ":extracted_at, :extracted_at)"
            ),
            {
                "id": evidence_id,
                "claim_id": claim_id,
                "knowledge_id": knowledge_id,
                "quote": evidence_id,
                "extracted_at": extracted_at,
                "raw_kb_id": raw_kb_id,
                "revision": revision,
                "file_hash": file_hash,
                "original_digest": original_digest,
                "parser_version": parser_version,
                "lineage": lineage,
            },
        )


def _seed_change_set(
    engine: Engine,
    *,
    change_set_id: str,
    space_id: str,
    source_kind: str,
    knowledge_ids: list[str],
    external_record_id: str,
    revision: str,
    created_at: datetime,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO change_sets "
                "(id, space_id, source_kind, knowledge_ids, external_record_id, "
                "source_revision, status, created_by, created_at, updated_at) VALUES "
                "(:id, :space_id, :source_kind, :knowledge_ids, :external_record_id, "
                ":revision, 'applied', 'historical-test', :created_at, :created_at)"
            ),
            {
                "id": change_set_id,
                "space_id": space_id,
                "source_kind": source_kind,
                "knowledge_ids": json.dumps(knowledge_ids),
                "external_record_id": external_record_id,
                "revision": revision,
                "created_at": created_at,
            },
        )


def _seed_historical_017_sources(
    engine: Engine,
    *,
    reverse_timestamps: bool = False,
) -> None:
    early = datetime(2025, 1, 1, tzinfo=UTC)
    late = datetime(2026, 7, 19, tzinfo=UTC)
    if reverse_timestamps:
        early, late = late, early
    _seed_space(
        engine,
        space_id="space-a",
        tenant_id="tenant-a",
        raw_kb_id="raw-a",
        now=early,
    )
    _seed_space(
        engine,
        space_id="space-b",
        tenant_id="tenant-b",
        raw_kb_id="raw-b",
        now=early,
    )
    for claim_id, space_id in (
        ("claim-evidence", "space-a"),
        ("claim-both", "space-a"),
        ("claim-legacy", "space-a"),
        ("claim-wrong-raw", "space-a"),
        ("claim-foreign", "space-b"),
    ):
        _seed_claim(engine, claim_id=claim_id, space_id=space_id, now=early)

    # Evidence-only: deliberately make the lexical-small revision newer by time.
    _seed_evidence(
        engine,
        evidence_id="evidence-a-f",
        claim_id="claim-evidence",
        knowledge_id="knowledge-a",
        raw_kb_id="raw-a",
        revision="f" * 64,
        extracted_at=early,
    )
    _seed_evidence(
        engine,
        evidence_id="evidence-a-0",
        claim_id="claim-evidence",
        knowledge_id="knowledge-a",
        raw_kb_id="raw-a",
        revision="0" * 64,
        extracted_at=late,
    )
    # Evidence + ChangeSet duplicate for the same source/revision.
    _seed_evidence(
        engine,
        evidence_id="evidence-c-a",
        claim_id="claim-both",
        knowledge_id="knowledge-c",
        raw_kb_id="raw-a",
        revision="a" * 64,
        extracted_at=late,
    )
    # Same knowledge_id in another Space must remain independently scoped.
    _seed_evidence(
        engine,
        evidence_id="evidence-b-a",
        claim_id="claim-foreign",
        knowledge_id="knowledge-a",
        raw_kb_id="raw-b",
        revision="b" * 64,
        extracted_at=early,
    )
    # Legacy and malformed cross-raw Evidence are not trustworthy 017 identities.
    _seed_evidence(
        engine,
        evidence_id="evidence-legacy",
        claim_id="claim-legacy",
        knowledge_id="knowledge-legacy",
        raw_kb_id=None,
        revision=None,
        extracted_at=late,
        source_aware=False,
    )
    _seed_evidence(
        engine,
        evidence_id="evidence-wrong-raw",
        claim_id="claim-wrong-raw",
        knowledge_id="knowledge-wrong-raw",
        raw_kb_id="raw-b",
        revision="9" * 64,
        extracted_at=late,
    )

    # ChangeSet-only: reverse lexical and created_at order; no latest is selected.
    _seed_change_set(
        engine,
        change_set_id="changeset-b-e",
        space_id="space-a",
        source_kind="document",
        knowledge_ids=["knowledge-b"],
        external_record_id="knowledge-b",
        revision="e" * 64,
        created_at=early,
    )
    _seed_change_set(
        engine,
        change_set_id="changeset-b-1",
        space_id="space-a",
        source_kind="recompile",
        knowledge_ids=["knowledge-b"],
        external_record_id="knowledge-b",
        revision="1" * 64,
        created_at=late,
    )
    _seed_change_set(
        engine,
        change_set_id="changeset-c-a",
        space_id="space-a",
        source_kind="document",
        knowledge_ids=["knowledge-c"],
        external_record_id="knowledge-c",
        revision="a" * 64,
        created_at=early,
    )
    _seed_change_set(
        engine,
        change_set_id="changeset-c-c",
        space_id="space-a",
        source_kind="recompile",
        knowledge_ids=["knowledge-c"],
        external_record_id="knowledge-c",
        revision="c" * 64,
        created_at=late,
    )
    _seed_change_set(
        engine,
        change_set_id="changeset-c-tombstone",
        space_id="space-a",
        source_kind="document",
        knowledge_ids=["knowledge-c"],
        external_record_id="knowledge-c",
        revision="retract:" + "D" * 56,
        created_at=late,
    )

    # 017 legacy retract and malformed/non-source aggregates must be ignored.
    _seed_change_set(
        engine,
        change_set_id="changeset-legacy-retract",
        space_id="space-a",
        source_kind="document",
        knowledge_ids=["legacy-empty"],
        external_record_id="legacy:" + "d" * 57,
        revision="retract:" + "e" * 56,
        created_at=late,
    )
    _seed_change_set(
        engine,
        change_set_id="changeset-malformed",
        space_id="space-a",
        source_kind="document",
        knowledge_ids=["knowledge-other"],
        external_record_id="knowledge-malformed",
        revision="7" * 64,
        created_at=late,
    )
    _seed_change_set(
        engine,
        change_set_id="changeset-manual",
        space_id="space-a",
        source_kind="manual_edit",
        knowledge_ids=["knowledge-manual"],
        external_record_id="knowledge-manual",
        revision="8" * 64,
        created_at=late,
    )


def _load_0006_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0006_021", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _issue_rows(engine: Engine) -> list[tuple[object, ...]]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT id, space_id, tenant_id, raw_kb_id, knowledge_id, "
                    "observed_revisions, reason, status, resolved_revision, "
                    "created_at, updated_at FROM source_lifecycle_backfill_issues "
                    "ORDER BY space_id, knowledge_id"
                )
            ).tuples()
        )


def _sqlite_lifecycle_ddl(engine: Engine) -> list[tuple[str, str, str]]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT type, name, sql FROM sqlite_master "
                    "WHERE name IN ('source_heads', 'source_events', "
                    "'source_lifecycle_backfill_issues', "
                    "'trg_source_events_update_guard_021', "
                    "'trg_source_events_delete_guard_021') "
                    "ORDER BY type, name"
                )
            ).tuples()
        )


def _sqlite_schema_ddl(engine: Engine) -> list[tuple[str, str, str, str | None]]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT type, name, tbl_name, sql FROM sqlite_master "
                    "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
                )
            ).tuples()
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


def _parent_unique_signature(engine: Engine) -> dict[str, object]:
    inspector = inspect(engine)
    return {
        table: sorted(
            (
                item["name"],
                tuple(item["column_names"]),
            )
            for item in inspector.get_unique_constraints(table)
        )
        for table in sorted(PARENT_SCOPE_UNIQUES)
    }


def _first_ddl_signature(engine: Engine) -> dict[str, object]:
    return {
        "lifecycle_ddl": _sqlite_lifecycle_ddl(engine),
        "parent_uniques": _parent_unique_signature(engine),
    }


def _alembic_version(engine: Engine) -> str:
    with engine.connect() as connection:
        return cast(
            str,
            connection.scalar(text("SELECT version_num FROM alembic_version")),
        )


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


def _foreign_key_shape(
    item: ReflectedForeignKeyConstraint,
) -> tuple[tuple[str, ...], str, tuple[str, ...]]:
    return (
        tuple(item["constrained_columns"]),
        str(item["referred_table"]),
        tuple(item["referred_columns"]),
    )


def test_l5_schema_0006_is_the_only_head_and_revises_actual_0012() -> None:
    assert MIGRATION_PATH.is_file()
    script = ScriptDirectory.from_config(_cfg("sqlite://"))

    assert script.get_heads() == ["0006"]
    revision = script.get_revision("0006")
    assert revision is not None
    assert revision.down_revision == "0012"


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


def test_l5_backfill_017_historical_sources_creates_only_scoped_open_issues(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "historical-backfill")
    command.upgrade(_cfg(url), "0012")
    _seed_historical_017_sources(engine)

    command.upgrade(_cfg(url), "0006")

    rows = _issue_rows(engine)
    assert [
        (
            row[1],
            row[2],
            row[3],
            row[4],
            json.loads(cast(str, row[5])),
            row[6],
            row[7],
            row[8],
        )
        for row in rows
    ] == [
        (
            "space-a",
            "tenant-a",
            "raw-a",
            "knowledge-a",
            ["0" * 64, "f" * 64],
            "historical_017_source_ordering_unavailable",
            "open",
            None,
        ),
        (
            "space-a",
            "tenant-a",
            "raw-a",
            "knowledge-b",
            ["1" * 64, "e" * 64],
            "historical_017_source_ordering_unavailable",
            "open",
            None,
        ),
        (
            "space-a",
            "tenant-a",
            "raw-a",
            "knowledge-c",
            ["a" * 64, "c" * 64, "retract:" + "d" * 56],
            "historical_017_source_ordering_unavailable_with_tombstone_event",
            "open",
            None,
        ),
        (
            "space-b",
            "tenant-b",
            "raw-b",
            "knowledge-a",
            ["b" * 64],
            "historical_017_source_ordering_unavailable",
            "open",
            None,
        ),
    ]
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM source_heads")) == 0
        assert connection.scalar(text("SELECT count(*) FROM source_events")) == 0


def test_l5_backfill_is_idempotent_and_never_uses_time_or_hash_as_latest(
    tmp_path: Path,
) -> None:
    snapshots: list[list[tuple[object, ...]]] = []
    engines: list[Engine] = []
    for name, reverse_timestamps in (("normal-time", False), ("reversed-time", True)):
        url, engine = _db(tmp_path, name)
        engines.append(engine)
        command.upgrade(_cfg(url), "0012")
        _seed_historical_017_sources(
            engine,
            reverse_timestamps=reverse_timestamps,
        )
        command.upgrade(_cfg(url), "0006")
        snapshots.append(_issue_rows(engine))

    # IDs and observed sets are deterministic; creation timestamps may differ by run.
    assert [tuple(row[:9]) for row in snapshots[0]] == [
        tuple(row[:9]) for row in snapshots[1]
    ]
    before_rerun = snapshots[0]
    module = _load_0006_migration()
    backfill = cast(
        Callable[[Connection], None],
        module._backfill_historical_017_sources,
    )
    with engines[0].begin() as connection:
        backfill(connection)

    assert _issue_rows(engines[0]) == before_rerun
    for engine in engines:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM source_heads")) == 0
            assert connection.scalar(text("SELECT count(*) FROM source_events")) == 0


def test_l5_backfill_source_aware_tombstone_only_creates_open_issue_but_legacy_retract_does_not(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "tombstone-only-backfill")
    command.upgrade(_cfg(url), "0012")
    now = datetime(2026, 7, 19, tzinfo=UTC)
    _seed_space(
        engine,
        space_id="space-a",
        tenant_id="tenant-a",
        raw_kb_id="raw-a",
        now=now,
    )
    source_tombstone = "retract:" + "A" * 56
    _seed_change_set(
        engine,
        change_set_id="changeset-source-tombstone",
        space_id="space-a",
        source_kind="document",
        knowledge_ids=["knowledge-tombstone"],
        external_record_id="knowledge-tombstone",
        revision=source_tombstone,
        created_at=now,
    )
    _seed_change_set(
        engine,
        change_set_id="changeset-legacy-tombstone",
        space_id="space-a",
        source_kind="document",
        knowledge_ids=["legacy-empty"],
        external_record_id="legacy:" + "b" * 57,
        revision="retract:" + "C" * 56,
        created_at=now,
    )

    command.upgrade(_cfg(url), "0006")

    rows = _issue_rows(engine)
    assert len(rows) == 1
    assert rows[0][1:8] == (
        "space-a",
        "tenant-a",
        "raw-a",
        "knowledge-tombstone",
        json.dumps([source_tombstone.lower()]),
        "historical_017_source_ordering_unavailable_with_tombstone_event",
        "open",
    )
    before_rerun = rows
    module = _load_0006_migration()
    backfill = cast(
        Callable[[Connection], None],
        module._backfill_historical_017_sources,
    )
    with engine.begin() as connection:
        backfill(connection)

    assert _issue_rows(engine) == before_rerun
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM source_heads")) == 0
        assert connection.scalar(text("SELECT count(*) FROM source_events")) == 0


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
    assert ScriptDirectory.from_config(_cfg(url)).get_heads() == ["0006"]
    assert _alembic_version(engine) == "0006"


def test_l5_chain_downgrade_mirrors_flywheel_preflight_before_0006_ddl(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "chain-flywheel")
    command.upgrade(_cfg(url), "0006")
    now = _seed_bound_space(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO flywheel_checkpoints "
                "(id, space_id, source_id, cursor, created_at, updated_at) VALUES "
                "('checkpoint-a', 'space-a', 'source-a', 'cursor-a', :now, :now)"
            ),
            {"now": now},
        )
    before_ddl = _first_ddl_signature(engine)

    with pytest.raises(RuntimeError, match="0012 downgrade refused"):
        command.downgrade(_cfg(url), "0005")

    assert _first_ddl_signature(engine) == before_ddl
    assert _alembic_version(engine) == "0006"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM flywheel_checkpoints")) == 1


def test_l5_chain_downgrade_mirrors_release_preflight_before_0006_ddl(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "chain-release")
    command.upgrade(_cfg(url), "0006")
    now = _seed_bound_space(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO release_snapshots "
                "(id, space_id, label, rendered_pages, published_at, published_by, "
                "notes, status, read_model_version, projection_frozen_at, "
                "created_at, updated_at) VALUES "
                "('snapshot-a', 'space-a', 'release-a', '[]', NULL, 'tester', NULL, "
                "'building', 1, NULL, :now, :now)"
            ),
            {"now": now},
        )
    before_ddl = _first_ddl_signature(engine)

    with pytest.raises(RuntimeError, match="0005 downgrade refused"):
        command.downgrade(_cfg(url), "0004")

    assert _first_ddl_signature(engine) == before_ddl
    assert _alembic_version(engine) == "0006"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM release_snapshots")) == 1


def test_l5_chain_downgrade_mirrors_enterprise_scope_preflight_before_0006_ddl(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "chain-enterprise-scope")
    command.upgrade(_cfg(url), "0006")
    _seed_bound_space(engine)
    before_ddl = _first_ddl_signature(engine)

    with pytest.raises(CommandError, match="legacy-default"):
        command.downgrade(_cfg(url), "0002")

    assert _first_ddl_signature(engine) == before_ddl
    assert _alembic_version(engine) == "0006"
    with engine.connect() as connection:
        assert list(connection.scalars(text("SELECT id FROM knowledge_spaces"))) == [
            "space-a"
        ]


def test_l5_chain_downgrade_base_mirrors_flywheel_before_0006_ddl(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "chain-base-flywheel")
    command.upgrade(_cfg(url), "0006")
    now = datetime(2026, 7, 19, tzinfo=UTC)
    _seed_space(
        engine,
        space_id="legacy-default",
        tenant_id="tenant-legacy",
        raw_kb_id="raw-legacy",
        now=now,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO flywheel_checkpoints "
                "(id, space_id, source_id, cursor, created_at, updated_at) VALUES "
                "('checkpoint-a', 'legacy-default', 'source-a', 'cursor-a', :now, :now)"
            ),
            {"now": now},
        )
    before_ddl = _first_ddl_signature(engine)

    with pytest.raises(RuntimeError, match="0012 downgrade refused"):
        command.downgrade(_cfg(url), "base")

    assert _first_ddl_signature(engine) == before_ddl
    assert _alembic_version(engine) == "0006"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM flywheel_checkpoints")) == 1


def test_l5_chain_downgrade_base_mirrors_release_before_0006_ddl(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "chain-base-release")
    command.upgrade(_cfg(url), "0006")
    now = datetime(2026, 7, 19, tzinfo=UTC)
    _seed_space(
        engine,
        space_id="legacy-default",
        tenant_id="tenant-legacy",
        raw_kb_id="raw-legacy",
        now=now,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO release_snapshots "
                "(id, space_id, label, rendered_pages, published_at, published_by, "
                "notes, status, read_model_version, projection_frozen_at, "
                "created_at, updated_at) VALUES "
                "('snapshot-a', 'legacy-default', 'release-a', '[]', NULL, "
                "'tester', NULL, 'building', 1, NULL, :now, :now)"
            ),
            {"now": now},
        )
    before_ddl = _first_ddl_signature(engine)

    with pytest.raises(RuntimeError, match="0005 downgrade refused"):
        command.downgrade(_cfg(url), "base")

    assert _first_ddl_signature(engine) == before_ddl
    assert _alembic_version(engine) == "0006"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM release_snapshots")) == 1


@pytest.mark.parametrize("bad_version_state", ["unexpected", "multiple_heads"])
def test_l5_topology_failure_is_reported_before_0006_ddl(
    tmp_path: Path,
    bad_version_state: str,
) -> None:
    url, engine = _db(tmp_path, f"topology-{bad_version_state}")
    command.upgrade(_cfg(url), "0006")
    before_ddl = _first_ddl_signature(engine)
    with engine.begin() as connection:
        if bad_version_state == "unexpected":
            connection.execute(
                text("UPDATE alembic_version SET version_num='unexpected-base'")
            )
        else:
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES ('0012')")
            )
        before_versions = list(
            connection.scalars(text("SELECT version_num FROM alembic_version ORDER BY 1"))
        )

    with pytest.raises(
        (CommandError, RuntimeError),
        match="unexpected-base|0006 downgrade refused.*topology",
    ):
        command.downgrade(_cfg(url), "0012")

    assert _first_ddl_signature(engine) == before_ddl
    with engine.connect() as connection:
        assert list(
            connection.scalars(text("SELECT version_num FROM alembic_version ORDER BY 1"))
        ) == before_versions


@pytest.mark.parametrize("destination", ["0006", "head"])
@pytest.mark.parametrize("bad_version_state", ["unknown", "multiple_heads"])
def test_l5_upgrade_topology_characterization_fails_before_any_0006_ddl(
    tmp_path: Path,
    destination: str,
    bad_version_state: str,
) -> None:
    """Alembic itself rejects invalid upgrade topology before invoking 0006."""
    url, engine = _db(
        tmp_path,
        f"upgrade-topology-{bad_version_state}-{destination}",
    )
    command.upgrade(_cfg(url), "0012")
    with engine.begin() as connection:
        if bad_version_state == "unknown":
            connection.execute(
                text("UPDATE alembic_version SET version_num='unexpected-base'")
            )
        else:
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES ('0005')")
            )
        before_versions = list(
            connection.scalars(text("SELECT version_num FROM alembic_version ORDER BY 1"))
        )
    before_schema = _sqlite_schema_ddl(engine)

    with pytest.raises(CommandError):
        command.upgrade(_cfg(url), destination)

    assert _sqlite_schema_ddl(engine) == before_schema
    with engine.connect() as connection:
        assert list(
            connection.scalars(text("SELECT version_num FROM alembic_version ORDER BY 1"))
        ) == before_versions
    assert LIFECYCLE_TABLES.isdisjoint(inspect(engine).get_table_names())
    for table, unique_name in PARENT_SCOPE_UNIQUES.items():
        assert unique_name not in {
            item["name"] for item in inspect(engine).get_unique_constraints(table)
        }
