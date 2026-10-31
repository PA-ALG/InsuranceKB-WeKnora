"""OpenSpec 021 L2/L5/L6 PostgreSQL migration acceptance: shared database and snapshot helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

HARNESS_ROOT = Path(__file__).resolve().parents[3]
TEST_POSTGRES_ENV = "HARNESS_TEST_POSTGRES_URL"
LIFECYCLE_TABLES = {
    "source_heads",
    "source_events",
    "source_lifecycle_backfill_issues",
}
APPEND_ONLY_FUNCTION = "guard_source_events_append_only_021"
PARENT_SCOPE_UNIQUES = {
    "knowledge_spaces": "uq_knowledge_spaces_scope_raw",
    "change_sets": "uq_change_sets_space_id",
    "change_items": "uq_change_items_change_set_id",
}
CONNECT_ARGS: dict[str, Any] = {
    "connect_timeout": 10,
    "options": "-cstatement_timeout=30000 -clock_timeout=15000",
}


@dataclass(frozen=True)
class PostgresMigrationDb:
    """A random disposable database and its secret-bearing in-process URL."""

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


def _database_url(admin_url: URL, database_name: str) -> URL:
    """Carry hard timeouts into Alembic's own independently-created connections."""
    return admin_url.set(database=database_name).update_query_dict(
        {
            "application_name": "insurancekb_021_migration_test",
            "connect_timeout": "10",
            "options": "-cstatement_timeout=30000 -clock_timeout=15000",
        }
    )


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
