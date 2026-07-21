"""OpenSpec 015 F3.3: durable flywheel migration 0012 contract."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError
from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError

HARNESS_ROOT = Path(__file__).resolve().parents[1]
TABLES = {"flywheel_checkpoints", "flywheel_observations", "knowledge_gaps"}


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


def test_f3_3_0012_creates_space_scoped_flywheel_tables(tmp_path: Path) -> None:
    url, engine = _db(tmp_path, "schema")
    command.upgrade(_cfg(url), "0012")
    inspector = inspect(engine)

    assert TABLES <= set(inspector.get_table_names())
    assert {"space_id", "source_id", "cursor"} <= {
        column["name"] for column in inspector.get_columns("flywheel_checkpoints")
    }
    assert {
        "space_id",
        "source_id",
        "trace_id",
        "trace_timestamp",
        "question",
        "signal_types",
        "alignment_reason",
        "product_id",
        "field_id",
        "concept_id",
        "gap_id",
    } <= {column["name"] for column in inspector.get_columns("flywheel_observations")}
    assert {
        "space_id",
        "gap_key",
        "product_id",
        "field_id",
        "concept_id",
        "signal_types",
        "hit_count",
        "sample_trace_ids",
        "sample_questions",
        "status",
        "first_seen",
        "last_seen",
        "resolved_at",
    } <= {column["name"] for column in inspector.get_columns("knowledge_gaps")}

    checkpoint_uqs = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("flywheel_checkpoints")
    }
    observation_uqs = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("flywheel_observations")
    }
    gap_uqs = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("knowledge_gaps")
    }
    assert ("space_id", "source_id") in checkpoint_uqs
    assert ("space_id", "source_id", "trace_id") in observation_uqs
    assert ("space_id", "gap_key") in gap_uqs
    assert ("space_id", "id") in gap_uqs


def test_f3_3_0012_rejects_cross_space_observation_gap_reference(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "cross-space")
    command.upgrade(_cfg(url), "0012")
    now = datetime.now(UTC)
    with engine.begin() as connection:
        for suffix in ("a", "b"):
            connection.execute(
                text(
                    "INSERT INTO knowledge_spaces "
                    "(id, tenant_id, raw_kb_id, wiki_kb_id, name, binding_status, "
                    "created_at, updated_at) VALUES "
                    "(:id, :tenant, :raw, :wiki, :name, 'bound', :now, :now)"
                ),
                {
                    "id": f"space-{suffix}",
                    "tenant": f"tenant-{suffix}",
                    "raw": f"raw-{suffix}",
                    "wiki": f"wiki-{suffix}",
                    "name": suffix,
                    "now": now,
                },
            )
        connection.execute(
            text(
                "INSERT INTO knowledge_gaps "
                "(id, space_id, gap_key, signal_types, hit_count, sample_trace_ids, "
                "sample_questions, status, created_at, updated_at) VALUES "
                "('gap-a', 'space-a', 'product-a||', '[]', 1, '[]', '[]', "
                "'open', :now, :now)"
            ),
            {"now": now},
        )

    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO flywheel_observations "
                "(id, space_id, source_id, trace_id, trace_timestamp, question, "
                "signal_types, alignment_reason, gap_id, created_at, updated_at) VALUES "
                "('obs-b', 'space-b', 'source', 'trace', :now, 'q', '[]', "
                "'aligned', 'gap-a', :now, :now)"
            ),
            {"now": now},
        )


def test_f3_3_0012_downgrade_removes_only_flywheel_tables(tmp_path: Path) -> None:
    url, engine = _db(tmp_path, "downgrade")
    command.upgrade(_cfg(url), "0012")
    command.downgrade(_cfg(url), "0005")

    tables = set(inspect(engine).get_table_names())
    assert TABLES.isdisjoint(tables)
    assert "knowledge_spaces" in tables


def test_f3_3_0012_postgresql_offline_ddl_compiles() -> None:
    output = StringIO()
    command.upgrade(
        _cfg("postgresql://user:password@localhost/insurance", output=output),
        "0005:0012",
        sql=True,
    )

    ddl = output.getvalue()
    assert "CREATE TABLE flywheel_checkpoints" in ddl
    assert "CREATE TABLE flywheel_observations" in ddl
    assert "CREATE TABLE knowledge_gaps" in ddl


def test_f3_3_0012_chain_downgrade_preflights_0003_before_any_ddl(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "chain-preflight")
    command.upgrade(_cfg(url), "0012")
    now = datetime.now(UTC)
    with engine.begin() as connection:
        for suffix in ("a", "b"):
            connection.execute(
                text(
                    "INSERT INTO knowledge_spaces "
                    "(id, tenant_id, raw_kb_id, wiki_kb_id, name, binding_status, "
                    "created_at, updated_at) VALUES "
                    "(:id, :tenant, :raw, :wiki, :name, 'bound', :now, :now)"
                ),
                {
                    "id": f"space-{suffix}",
                    "tenant": f"tenant-{suffix}",
                    "raw": f"raw-{suffix}",
                    "wiki": f"wiki-{suffix}",
                    "name": suffix,
                    "now": now,
                },
            )
    before_tables = set(inspect(engine).get_table_names())

    with pytest.raises(CommandError, match="multiple|exactly one|legacy-default"):
        command.downgrade(_cfg(url), "0002")

    assert set(inspect(engine).get_table_names()) == before_tables
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0012"


def test_f3_3_0012_downgrade_refuses_to_drop_durable_state(tmp_path: Path) -> None:
    url, engine = _db(tmp_path, "durable-state")
    command.upgrade(_cfg(url), "0012")
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge_spaces "
                "(id, tenant_id, raw_kb_id, wiki_kb_id, name, binding_status, "
                "created_at, updated_at) VALUES "
                "('space-a', 'tenant-a', 'raw-a', 'wiki-a', 'a', 'bound', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO flywheel_checkpoints "
                "(id, space_id, source_id, cursor, created_at, updated_at) VALUES "
                "('checkpoint-a', 'space-a', 'source-a', 'cursor-a', :now, :now)"
            ),
            {"now": now},
        )

    with pytest.raises(RuntimeError, match="0012 downgrade refused"):
        command.downgrade(_cfg(url), "0005")

    assert TABLES <= set(inspect(engine).get_table_names())
