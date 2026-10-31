"""OpenSpec 021 source lifecycle migration contracts: shared Alembic, seeding and schema helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import cast

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event, inspect, text

from insurance_harness.db import models as _db_models  # noqa: F401
from insurance_harness.knowledge import tables as _knowledge_tables  # noqa: F401

HARNESS_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = HARNESS_ROOT / "migrations" / "versions" / "0006_source_lifecycle_ordering.py"
LIFECYCLE_TABLES = {
    "source_heads",
    "source_events",
    "source_lifecycle_backfill_issues",
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


def _assert_current_migration_topology(script: ScriptDirectory) -> None:
    assert script.get_heads() == ["0018"]
    for revision_id, down_revision in (
        ("0018", "0017"),
        ("0017", "0016"),
        ("0016", "0015"),
        ("0015", "0006"),
        ("0006", "0012"),
    ):
        revision = script.get_revision(revision_id)
        assert revision is not None
        assert revision.down_revision == down_revision
