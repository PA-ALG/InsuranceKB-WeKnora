"""OpenSpec 029 RA2: release manifest/approval migration contract."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

HARNESS_ROOT = Path(__file__).resolve().parents[1]
TABLES = {"release_manifests", "release_approvals"}
GUARDS = {
    "trg_release_manifests_update_guard_029",
    "trg_release_manifests_delete_guard_029",
    "trg_release_approvals_update_guard_029",
    "trg_release_approvals_delete_guard_029",
}


def _cfg(url: str, *, output: StringIO | None = None) -> Config:
    config = Config(str(HARNESS_ROOT / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(HARNESS_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def _db(tmp_path: Path, name: str) -> tuple[str, Engine]:
    url = f"sqlite:///{tmp_path}/{name}.db"
    return url, create_engine(url)


def _seed_scope_snapshot(connection: Any, suffix: str) -> tuple[str, str]:
    now = datetime.now(UTC)
    space_id = f"space-{suffix}"
    snapshot_id = f"snapshot-{suffix}"
    connection.execute(
        text(
            """INSERT INTO knowledge_spaces
            (id, tenant_id, raw_kb_id, wiki_kb_id, name, binding_status, created_at, updated_at)
            VALUES (:space, :tenant, :raw, :wiki, :name, 'bound', :now, :now)"""
        ),
        {
            "space": space_id,
            "tenant": f"tenant-{suffix}",
            "raw": f"raw-{suffix}",
            "wiki": f"wiki-{suffix}",
            "name": suffix,
            "now": now,
        },
    )
    connection.execute(
        text(
            """INSERT INTO release_snapshots
            (id, space_id, label, rendered_pages, status, read_model_version,
             projection_frozen_at, published_at, published_by, notes, created_at, updated_at)
            VALUES (:snapshot, :space, :label, :pages, 'published', 1,
                    :now, :now, 'test', NULL, :now, :now)"""
        ),
        {
            "snapshot": snapshot_id,
            "space": space_id,
            "label": snapshot_id,
            "pages": json.dumps([]),
            "now": now,
        },
    )
    return space_id, snapshot_id


def _insert_manifest(
    connection: Any,
    *,
    space_id: str,
    snapshot_id: str,
    manifest_hash: str = "a" * 64,
) -> None:
    now = datetime.now(UTC)
    connection.execute(
        text(
            """INSERT INTO release_manifests
            (id, space_id, snapshot_id, manifest_hash, payload, created_at, updated_at)
            VALUES (:id, :space, :snapshot, :hash, :payload, :now, :now)"""
        ),
        {
            "id": str(uuid.uuid4()),
            "space": space_id,
            "snapshot": snapshot_id,
            "hash": manifest_hash,
            "payload": json.dumps({"manifest_sha256": manifest_hash}),
            "now": now,
        },
    )


def test_ra2_0013_is_single_head_and_creates_exact_schema(tmp_path: Path) -> None:
    url, engine = _db(tmp_path, "schema")
    command.upgrade(_cfg(url), "head")
    inspector = inspect(engine)

    assert ScriptDirectory.from_config(_cfg(url)).get_heads() == ["0013"]
    assert TABLES <= set(inspector.get_table_names())
    assert {
        "id",
        "space_id",
        "snapshot_id",
        "manifest_hash",
        "payload",
        "created_at",
        "updated_at",
    } == {item["name"] for item in inspector.get_columns("release_manifests")}
    assert {
        "id",
        "space_id",
        "snapshot_id",
        "manifest_hash",
        "actor",
        "actor_type",
        "authorization_receipt",
        "reason",
        "approved_at",
        "created_at",
    } == {item["name"] for item in inspector.get_columns("release_approvals")}
    manifest_uniques = {
        item["name"] for item in inspector.get_unique_constraints("release_manifests")
    }
    assert {
        "uq_release_manifests_space_snapshot",
        "uq_release_manifests_space_hash",
        "uq_release_manifests_exact",
    } <= manifest_uniques
    approval_fks = {
        item["name"] for item in inspector.get_foreign_keys("release_approvals")
    }
    assert "fk_release_approvals_exact_manifest" in approval_fks
    assert "ck_release_approvals_actor_type" in {
        item["name"] for item in inspector.get_check_constraints("release_approvals")
    }


def test_ra2_0013_guards_manifest_immutable_and_approval_append_only(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "guards")
    command.upgrade(_cfg(url), "head")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        space_id, snapshot_id = _seed_scope_snapshot(connection, "guard")
        _insert_manifest(connection, space_id=space_id, snapshot_id=snapshot_id)
        now = datetime.now(UTC)
        connection.execute(
            text(
                """INSERT INTO release_approvals
                (id, space_id, snapshot_id, manifest_hash, actor, actor_type,
                 authorization_receipt, reason, approved_at, created_at)
                VALUES ('approval-1', :space, :snapshot, :hash, 'alice', 'human',
                        'receipt', 'reviewed', :now, :now)"""
            ),
            {"space": space_id, "snapshot": snapshot_id, "hash": "a" * 64, "now": now},
        )

    with engine.connect() as connection:
        assert GUARDS <= set(
            connection.scalars(
                text("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE '%_029'")
            )
        )
        for statement in (
            "UPDATE release_manifests SET manifest_hash='" + "b" * 64 + "'",
            "DELETE FROM release_manifests",
            "UPDATE release_approvals SET reason='changed'",
            "DELETE FROM release_approvals",
        ):
            with pytest.raises(IntegrityError):
                connection.execute(text(statement))


def test_ra2_0013_rejects_cross_space_manifest_and_nonhuman_approval(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "constraints")
    command.upgrade(_cfg(url), "head")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        space_a, snapshot_a = _seed_scope_snapshot(connection, "a")
        space_b, _snapshot_b = _seed_scope_snapshot(connection, "b")
        with pytest.raises(IntegrityError):
            _insert_manifest(
                connection,
                space_id=space_b,
                snapshot_id=snapshot_a,
            )
        _insert_manifest(connection, space_id=space_a, snapshot_id=snapshot_a)
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """INSERT INTO release_approvals
                    (id, space_id, snapshot_id, manifest_hash, actor, actor_type,
                     authorization_receipt, reason, approved_at, created_at)
                    VALUES ('bad', :space, :snapshot, :hash, 'model-x', 'model',
                            'receipt', 'automated', :now, :now)"""
                ),
                {
                    "space": space_a,
                    "snapshot": snapshot_a,
                    "hash": "a" * 64,
                    "now": datetime.now(UTC),
                },
            )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """INSERT INTO release_approvals
                    (id, space_id, snapshot_id, manifest_hash, actor, actor_type,
                     authorization_receipt, reason, approved_at, created_at)
                    VALUES ('cross-space', :space, :snapshot, :hash, 'alice', 'human',
                            'receipt', 'reviewed', :now, :now)"""
                ),
                {
                    "space": space_b,
                    "snapshot": snapshot_a,
                    "hash": "a" * 64,
                    "now": datetime.now(UTC),
                },
            )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """INSERT INTO release_approvals
                    (id, space_id, snapshot_id, manifest_hash, actor, actor_type,
                     authorization_receipt, reason, approved_at, created_at)
                    VALUES ('anonymous', :space, :snapshot, :hash, '', 'human',
                            'receipt', 'reviewed', :now, :now)"""
                ),
                {
                    "space": space_a,
                    "snapshot": snapshot_a,
                    "hash": "a" * 64,
                    "now": datetime.now(UTC),
                },
            )


def test_ra2_0013_nonempty_downgrade_refuses_before_any_ddl(tmp_path: Path) -> None:
    url, engine = _db(tmp_path, "unsafe-downgrade")
    command.upgrade(_cfg(url), "head")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        space_id, snapshot_id = _seed_scope_snapshot(connection, "durable")
        _insert_manifest(connection, space_id=space_id, snapshot_id=snapshot_id)
    before_tables = set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        before_triggers = set(
            connection.scalars(
                text("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE '%_029'")
            )
        )

    with pytest.raises(RuntimeError, match="0013 downgrade refused before DDL"):
        command.downgrade(_cfg(url), "0006")

    assert set(inspect(engine).get_table_names()) == before_tables
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0013"
        assert set(
            connection.scalars(
                text("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE '%_029'")
            )
        ) == before_triggers


def test_ra2_0013_empty_downgrade_and_rollforward_are_safe(tmp_path: Path) -> None:
    url, engine = _db(tmp_path, "empty-downgrade")
    command.upgrade(_cfg(url), "head")
    command.downgrade(_cfg(url), "0006")

    assert TABLES.isdisjoint(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0006"
    command.upgrade(_cfg(url), "head")
    command.check(_cfg(url))
    assert TABLES <= set(inspect(engine).get_table_names())


def test_ra2_0013_postgresql_offline_ddl_contains_guards_and_exact_fk() -> None:
    output = StringIO()
    command.upgrade(
        _cfg("postgresql://user:password@localhost/insurance", output=output),
        "0006:0013",
        sql=True,
    )

    ddl = output.getvalue().lower()
    assert TABLES <= {table for table in TABLES if table in ddl}
    assert all(guard in ddl for guard in GUARDS)
    assert "fk_release_approvals_exact_manifest" in ddl
    assert "guard_release_manifests_immutable_029" in ddl
    assert "guard_release_approvals_append_only_029" in ddl


@pytest.mark.integration_postgres
def test_ra2_0013_real_postgresql_schema_and_guards() -> None:
    raw_url = os.getenv("HARNESS_TEST_POSTGRES_URL")
    if not raw_url:
        pytest.skip("HARNESS_TEST_POSTGRES_URL is required for real PostgreSQL RA2")
    admin_url = make_url(raw_url).set(drivername="postgresql+psycopg")
    database_name = f"ikb_029_{uuid.uuid4().hex}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    test_engine: Engine | None = None
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        test_url = admin_url.set(database=database_name)
        test_engine = create_engine(test_url)
        command.upgrade(_cfg(test_url.render_as_string(hide_password=False)), "head")
        assert TABLES <= set(inspect(test_engine).get_table_names())
        with test_engine.connect() as connection:
            assert GUARDS <= set(
                connection.scalars(
                    text(
                        "SELECT tgname FROM pg_trigger "
                        "WHERE NOT tgisinternal AND tgname LIKE '%_029'"
                    )
                )
            )
    finally:
        if test_engine is not None:
            test_engine.dispose()
        with admin.connect() as connection:
            connection.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                     "WHERE datname=:name AND pid<>pg_backend_pid()"),
                {"name": database_name},
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
        admin.dispose()
