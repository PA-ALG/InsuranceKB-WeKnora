"""ORM metadata must describe the PostgreSQL schema shipped by the migrations."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, cast

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, DateTime, Table, create_mock_engine
from sqlalchemy.schema import CreateTable

from insurance_harness.db.base import Base
from insurance_harness.product_ingestion import artifact_tables, tables  # noqa: F401


def test_product_timestamps_match_migrated_postgresql_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrated: dict[str, Table] = {}

    def capture(statement: Any, *_args: Any, **_kwargs: Any) -> None:
        if isinstance(statement, CreateTable):
            migrated[statement.element.name] = statement.element

    engine = create_mock_engine("postgresql://", capture)
    # Alembic uses only the mock connection's supported DDL execution boundary here.
    operations = Operations(
        MigrationContext.configure(connection=cast(Connection, engine.connect()))
    )
    root = Path(__file__).parents[2] / "migrations" / "versions"
    for name in ("0016_product_ingestion.py", "0017_product_artifacts.py"):
        spec = importlib.util.spec_from_file_location("timestamp_migration", root / name)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        monkeypatch.setattr(module, "op", operations)
        module.upgrade()

    checked = []
    for name, table in migrated.items():
        for column in table.columns:
            if not isinstance(column.type, DateTime):
                continue
            current = Base.metadata.tables[name].columns[column.name]
            assert current.type.compile(dialect=engine.dialect) == column.type.compile(
                dialect=engine.dialect
            ), (name, column.name)
            assert current.nullable == column.nullable
            checked.append((name, column.name))
    assert checked, "the migration comparison must execute timestamp-bearing tables"
