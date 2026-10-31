"""021 source lifecycle (SQLite): chain downgrades mirror earlier preflights before 0006 DDL."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.util.exc import CommandError
from sqlalchemy import Engine, inspect, text

from insurance_harness.db import models as _db_models  # noqa: F401
from insurance_harness.knowledge import tables as _knowledge_tables  # noqa: F401
from tests.ingest.source_lifecycle_migration.helpers import (
    LIFECYCLE_TABLES,
    PARENT_SCOPE_UNIQUES,
    _alembic_version,
    _cfg,
    _db,
    _first_ddl_signature,
    _seed_bound_space,
    _seed_space,
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
