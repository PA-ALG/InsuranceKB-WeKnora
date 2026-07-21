"""OpenSpec 029 RA2: release manifest/approval migration contract."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
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
from sqlalchemy.exc import DBAPIError, IntegrityError

HARNESS_ROOT = Path(__file__).resolve().parents[1]
TABLES = {
    "release_manifests",
    "release_approvals",
    "release_activation_audits",
    "release_alerts",
}
GUARDS = {
    "trg_release_manifests_update_guard_029",
    "trg_release_manifests_delete_guard_029",
    "trg_release_approvals_update_guard_029",
    "trg_release_approvals_delete_guard_029",
    "trg_release_activation_audits_update_guard_029",
    "trg_release_activation_audits_delete_guard_029",
    "trg_release_alerts_update_guard_029",
    "trg_release_alerts_delete_guard_029",
}


@dataclass(frozen=True)
class Postgres029Schema:
    url: str
    engine: Engine
    schema_name: str


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
        "role",
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
    assert {"ck_release_approvals_actor_type", "ck_release_approvals_role"} <= {
        item["name"] for item in inspector.get_check_constraints("release_approvals")
    }
    assert {
        "id",
        "space_id",
        "kind",
        "from_snapshot_id",
        "target_snapshot_id",
        "manifest_hash",
        "approval_id",
        "actor",
        "reason",
        "activated_at",
        "created_at",
    } == {item["name"] for item in inspector.get_columns("release_activation_audits")}
    assert {
        "id",
        "space_id",
        "snapshot_id",
        "manifest_hash",
        "code",
        "severity",
        "safe_details",
        "detected_at",
        "created_at",
    } == {item["name"] for item in inspector.get_columns("release_alerts")}


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
                (id, space_id, snapshot_id, manifest_hash, actor, actor_type, role,
                 authorization_receipt, reason, approved_at, created_at)
                VALUES ('approval-1', :space, :snapshot, :hash, 'alice', 'human',
                        'release_approver',
                        'receipt', 'reviewed', :now, :now)"""
            ),
            {"space": space_id, "snapshot": snapshot_id, "hash": "a" * 64, "now": now},
        )
        connection.execute(
            text(
                """INSERT INTO release_activation_audits
                (id, space_id, kind, from_snapshot_id, target_snapshot_id, manifest_hash,
                 approval_id, actor, reason, activated_at, created_at)
                VALUES ('audit-1', :space, 'promote', NULL, :snapshot, :hash,
                        'approval-1', 'alice', 'activate', :now, :now)"""
            ),
            {"space": space_id, "snapshot": snapshot_id, "hash": "a" * 64, "now": now},
        )
        connection.execute(
            text(
                """INSERT INTO release_alerts
                (id, space_id, snapshot_id, manifest_hash, code, severity,
                 safe_details, detected_at, created_at)
                VALUES ('alert-1', :space, :snapshot, :hash, 'manifest_tamper',
                        'critical', :details, :now, :now)"""
            ),
            {
                "space": space_id,
                "snapshot": snapshot_id,
                "hash": "a" * 64,
                "details": json.dumps({"stage": "test"}),
                "now": now,
            },
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
            "UPDATE release_activation_audits SET reason='changed'",
            "DELETE FROM release_activation_audits",
            "UPDATE release_alerts SET severity='low'",
            "DELETE FROM release_alerts",
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
                    (id, space_id, snapshot_id, manifest_hash, actor, actor_type, role,
                     authorization_receipt, reason, approved_at, created_at)
                    VALUES ('bad', :space, :snapshot, :hash, 'model-x', 'model',
                            'release_approver',
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
                    (id, space_id, snapshot_id, manifest_hash, actor, actor_type, role,
                     authorization_receipt, reason, approved_at, created_at)
                    VALUES ('cross-space', :space, :snapshot, :hash, 'alice', 'human',
                            'release_approver',
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
                    (id, space_id, snapshot_id, manifest_hash, actor, actor_type, role,
                     authorization_receipt, reason, approved_at, created_at)
                    VALUES ('anonymous', :space, :snapshot, :hash, '', 'human',
                            'release_approver',
                            'receipt', 'reviewed', :now, :now)"""
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
                    (id, space_id, snapshot_id, manifest_hash, actor, actor_type, role,
                     authorization_receipt, reason, approved_at, created_at)
                    VALUES ('wrong-role', :space, :snapshot, :hash, 'alice', 'human',
                            'viewer', 'receipt', 'reviewed', :now, :now)"""
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


@pytest.fixture
def postgres_029_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Postgres029Schema]:
    raw_url = os.getenv("HARNESS_TEST_POSTGRES_URL")
    if not raw_url:
        pytest.skip("HARNESS_TEST_POSTGRES_URL is required for real PostgreSQL RA2")
    monkeypatch.delenv("HARNESS_DB_URL", raising=False)
    parsed_url = make_url(raw_url)
    if parsed_url.get_backend_name() != "postgresql":
        pytest.fail("HARNESS_TEST_POSTGRES_URL must use PostgreSQL")
    admin_url = parsed_url.set(drivername="postgresql+psycopg")
    schema_name = f"ikb_029_{uuid.uuid4().hex}"
    admin = create_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 10},
    )
    test_engine: Engine | None = None
    schema_created = False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')
        schema_created = True
        options = (
            f"-csearch_path={schema_name} "
            "-cstatement_timeout=30000 -clock_timeout=15000"
        )
        test_url = admin_url.update_query_dict(
            {
                "application_name": "insurancekb_029_migration_test",
                "connect_timeout": "10",
                "options": options,
            }
        )
        test_engine = create_engine(
            test_url,
            connect_args={"connect_timeout": 10, "options": options},
            pool_pre_ping=True,
        )
        rendered_url = test_url.render_as_string(hide_password=False)
        command.upgrade(_cfg(rendered_url), "head")
        yield Postgres029Schema(
            url=rendered_url,
            engine=test_engine,
            schema_name=schema_name,
        )
    finally:
        if test_engine is not None:
            test_engine.dispose()
        if schema_created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        admin.dispose()


def _seed_postgresql_release_authority(engine: Engine) -> tuple[str, str, str]:
    from insurance_harness.knowledge.release_manifest import build_release_manifest

    manifest = build_release_manifest(
        schema_version="insurance-knowledge-v1",
        space_id="space-pg-029",
        snapshot_id="snapshot-pg-029",
        read_model_version=1,
        template_hashes=("a" * 64,),
        model_plan_hash="b" * 64,
        facts=(),
        rendered_pages=(),
        directory_entries=(),
        relationships=(),
    )
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                """INSERT INTO knowledge_spaces
                (id, tenant_id, raw_kb_id, wiki_kb_id, name, binding_status,
                 created_at, updated_at)
                VALUES (:space, 'tenant-pg-029', 'raw-pg-029', 'wiki-pg-029',
                        'PostgreSQL 029', 'bound', :now, :now)"""
            ),
            {"space": manifest.space_id, "now": now},
        )
        connection.execute(
            text(
                """INSERT INTO release_snapshots
                (id, space_id, label, rendered_pages, status, read_model_version,
                 projection_frozen_at, published_at, published_by, notes,
                 created_at, updated_at)
                VALUES (:snapshot, :space, :snapshot, CAST(:pages AS JSON),
                        'published', 1, :now, :now, 'pg-test', NULL, :now, :now)"""
            ),
            {
                "snapshot": manifest.snapshot_id,
                "space": manifest.space_id,
                "pages": json.dumps([]),
                "now": now,
            },
        )
        connection.execute(
            text(
                """INSERT INTO release_manifests
                (id, space_id, snapshot_id, manifest_hash, payload, created_at, updated_at)
                VALUES ('manifest-pg-029', :space, :snapshot, :hash,
                        CAST(:payload AS JSON), :now, :now)"""
            ),
            {
                "space": manifest.space_id,
                "snapshot": manifest.snapshot_id,
                "hash": manifest.manifest_sha256,
                "payload": json.dumps(manifest.model_dump(mode="json")),
                "now": now,
            },
        )
        connection.execute(
            text(
                """INSERT INTO release_approvals
                (id, space_id, snapshot_id, manifest_hash, actor, actor_type, role,
                 authorization_receipt, reason, approved_at, created_at)
                VALUES ('approval-pg-029', :space, :snapshot, :hash,
                        'alice@example.com', 'human', 'release_approver',
                        'iam:alice:release-approver:029', 'reviewed exact manifest',
                        :now, :now)"""
            ),
            {
                "space": manifest.space_id,
                "snapshot": manifest.snapshot_id,
                "hash": manifest.manifest_sha256,
                "now": now,
            },
        )
        connection.execute(
            text(
                """INSERT INTO release_activation_audits
                (id, space_id, kind, from_snapshot_id, target_snapshot_id, manifest_hash,
                 approval_id, actor, reason, activated_at, created_at)
                VALUES ('audit-pg-029', :space, 'promote', NULL, :snapshot, :hash,
                        'approval-pg-029', 'alice@example.com', 'activate exact manifest',
                        :now, :now)"""
            ),
            {
                "space": manifest.space_id,
                "snapshot": manifest.snapshot_id,
                "hash": manifest.manifest_sha256,
                "now": now,
            },
        )
        connection.execute(
            text(
                """INSERT INTO release_alerts
                (id, space_id, snapshot_id, manifest_hash, code, severity,
                 safe_details, detected_at, created_at)
                VALUES ('alert-pg-029', :space, :snapshot, :hash, 'manifest_tamper',
                        'critical', CAST(:details AS JSON), :now, :now)"""
            ),
            {
                "space": manifest.space_id,
                "snapshot": manifest.snapshot_id,
                "hash": manifest.manifest_sha256,
                "details": json.dumps({"stage": "migration-test"}),
                "now": now,
            },
        )
    return manifest.space_id, manifest.snapshot_id, manifest.manifest_sha256


def _postgresql_029_triggers(engine: Engine) -> tuple[str, ...]:
    with engine.connect() as connection:
        return tuple(
            connection.scalars(
                text(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE NOT tgisinternal AND tgname LIKE '%_029' ORDER BY tgname"
                )
            )
        )


def _assert_postgresql_error(
    error: pytest.ExceptionInfo[DBAPIError],
    *,
    sqlstate: str,
    constraint: str | None = None,
    message: str | None = None,
) -> None:
    original = error.value.orig
    assert getattr(original, "sqlstate", None) == sqlstate
    if constraint is not None:
        diagnostic = getattr(original, "diag", None)
        assert getattr(diagnostic, "constraint_name", None) == constraint
    if message is not None:
        assert message in str(original)


@pytest.mark.integration_postgres
def test_ra2_0013_real_postgresql_guards_reject_mutation_and_recover_savepoint(
    postgres_029_schema: Postgres029Schema,
) -> None:
    engine = postgres_029_schema.engine
    space_id, snapshot_id, manifest_hash = _seed_postgresql_release_authority(engine)
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                """INSERT INTO release_snapshots
                (id, space_id, label, rendered_pages, status, read_model_version,
                 projection_frozen_at, published_at, published_by, notes,
                 created_at, updated_at)
                VALUES ('snapshot-pg-role', :space, 'snapshot-pg-role',
                        CAST('[]' AS JSON), 'published', 1, :now, :now,
                        'pg-test', NULL, :now, :now)"""
            ),
            {"space": space_id, "now": now},
        )
        connection.execute(
            text(
                """INSERT INTO release_manifests
                (id, space_id, snapshot_id, manifest_hash, payload, created_at, updated_at)
                VALUES ('manifest-pg-role', :space, 'snapshot-pg-role', :hash,
                        CAST(:payload AS JSON), :now, :now)"""
            ),
            {
                "space": space_id,
                "hash": "c" * 64,
                "payload": json.dumps({"manifest_sha256": "c" * 64}),
                "now": now,
            },
        )
        connection.execute(
            text(
                """INSERT INTO knowledge_spaces
                (id, tenant_id, raw_kb_id, wiki_kb_id, name, binding_status,
                 created_at, updated_at)
                VALUES ('space-pg-other', 'tenant-pg-other', 'raw-pg-other',
                        'wiki-pg-other', 'Other PG Space', 'bound', :now, :now)"""
            ),
            {"now": now},
        )
    assert TABLES <= set(inspect(engine).get_table_names())
    assert GUARDS <= set(_postgresql_029_triggers(engine))

    mutations = (
        (
            "UPDATE release_manifests SET manifest_hash='" + "c" * 64 + "'",
            "release manifests are immutable",
        ),
        ("DELETE FROM release_manifests", "release manifests are immutable"),
        (
            "UPDATE release_approvals SET reason='tampered'",
            "release approvals are append-only",
        ),
        ("DELETE FROM release_approvals", "release approvals are append-only"),
        (
            "UPDATE release_activation_audits SET reason='tampered'",
            "release activation audits are append-only",
        ),
        (
            "DELETE FROM release_activation_audits",
            "release activation audits are append-only",
        ),
        (
            "UPDATE release_alerts SET severity='low'",
            "release alerts are append-only",
        ),
        ("DELETE FROM release_alerts", "release alerts are append-only"),
    )
    with engine.connect() as connection:
        outer = connection.begin()
        for statement, expected_message in mutations:
            with pytest.raises(DBAPIError) as error:
                with connection.begin_nested():
                    connection.execute(text(statement))
            _assert_postgresql_error(
                error,
                sqlstate="23514",
                message=expected_message,
            )
            assert connection.scalar(text("SELECT 1")) == 1
            assert connection.scalar(text("SELECT count(*) FROM release_manifests")) == 2
            assert connection.scalar(text("SELECT count(*) FROM release_approvals")) == 1
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM release_activation_audits")
                )
                == 1
            )
            assert connection.scalar(text("SELECT count(*) FROM release_alerts")) == 1
        invalid_approvals = (
            (
                """INSERT INTO release_approvals
                (id, space_id, snapshot_id, manifest_hash, actor, actor_type, role,
                 authorization_receipt, reason, approved_at, created_at)
                VALUES ('approval-wrong-role', :space, 'snapshot-pg-role', :role_hash,
                        'alice@example.com', 'human', 'viewer', 'receipt-role',
                        'wrong role', :now, :now)""",
                {"space": space_id, "role_hash": "c" * 64, "now": now},
                "23514",
                "ck_release_approvals_role",
            ),
            (
                """INSERT INTO release_approvals
                (id, space_id, snapshot_id, manifest_hash, actor, actor_type, role,
                 authorization_receipt, reason, approved_at, created_at)
                VALUES ('approval-wrong-hash', :space, :snapshot, :wrong_hash,
                        'alice@example.com', 'human', 'release_approver', 'receipt-hash',
                        'wrong hash', :now, :now)""",
                {
                    "space": space_id,
                    "snapshot": snapshot_id,
                    "wrong_hash": "d" * 64,
                    "now": now,
                },
                "23503",
                "fk_release_approvals_exact_manifest",
            ),
            (
                """INSERT INTO release_approvals
                (id, space_id, snapshot_id, manifest_hash, actor, actor_type, role,
                 authorization_receipt, reason, approved_at, created_at)
                VALUES ('approval-cross-space', 'space-pg-other', :snapshot, :hash,
                        'alice@example.com', 'human', 'release_approver', 'receipt-space',
                        'cross space', :now, :now)""",
                {"snapshot": snapshot_id, "hash": manifest_hash, "now": now},
                "23503",
                "fk_release_approvals_exact_manifest",
            ),
        )
        for statement, parameters, expected_state, expected_constraint in invalid_approvals:
            with pytest.raises(DBAPIError) as error:
                with connection.begin_nested():
                    connection.execute(text(statement), parameters)
            _assert_postgresql_error(
                error,
                sqlstate=expected_state,
                constraint=expected_constraint,
            )
            assert connection.scalar(text("SELECT 1")) == 1
            assert connection.scalar(text("SELECT count(*) FROM release_manifests")) == 2
            assert connection.scalar(text("SELECT count(*) FROM release_approvals")) == 1
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM release_activation_audits")
                )
                == 1
            )
            assert connection.scalar(text("SELECT count(*) FROM release_alerts")) == 1
        outer.rollback()


@pytest.mark.integration_postgres
def test_ra2_0013_real_postgresql_nonempty_downgrade_fails_before_any_ddl(
    postgres_029_schema: Postgres029Schema,
) -> None:
    engine = postgres_029_schema.engine
    _seed_postgresql_release_authority(engine)
    with engine.connect() as connection:
        before_version = connection.scalar(text("SELECT version_num FROM alembic_version"))
        before_rows = (
            tuple(
                connection.execute(
                    text(
                        "SELECT id, space_id, snapshot_id, manifest_hash, payload::text "
                        "FROM release_manifests ORDER BY id"
                    )
                )
            ),
            tuple(
                connection.execute(
                    text(
                        "SELECT id, space_id, snapshot_id, manifest_hash, actor, actor_type, "
                        "role, authorization_receipt, reason, approved_at, created_at "
                        "FROM release_approvals ORDER BY id"
                    )
                )
            ),
            tuple(
                connection.execute(
                    text(
                        "SELECT id, space_id, kind, from_snapshot_id, target_snapshot_id, "
                        "manifest_hash, approval_id, actor, reason, activated_at, created_at "
                        "FROM release_activation_audits ORDER BY id"
                    )
                )
            ),
            tuple(
                connection.execute(
                    text(
                        "SELECT id, space_id, snapshot_id, manifest_hash, code, severity, "
                        "safe_details::text, detected_at, created_at "
                        "FROM release_alerts ORDER BY id"
                    )
                )
            ),
        )
    before_tables = tuple(sorted(inspect(engine).get_table_names()))
    before_triggers = _postgresql_029_triggers(engine)

    with pytest.raises(RuntimeError, match="0013 downgrade refused before DDL"):
        command.downgrade(_cfg(postgres_029_schema.url), "0006")

    assert tuple(sorted(inspect(engine).get_table_names())) == before_tables
    assert _postgresql_029_triggers(engine) == before_triggers
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            before_version
        ) == "0013"
        after_rows = (
            tuple(
                connection.execute(
                    text(
                        "SELECT id, space_id, snapshot_id, manifest_hash, payload::text "
                        "FROM release_manifests ORDER BY id"
                    )
                )
            ),
            tuple(
                connection.execute(
                    text(
                        "SELECT id, space_id, snapshot_id, manifest_hash, actor, actor_type, "
                        "role, authorization_receipt, reason, approved_at, created_at "
                        "FROM release_approvals ORDER BY id"
                    )
                )
            ),
            tuple(
                connection.execute(
                    text(
                        "SELECT id, space_id, kind, from_snapshot_id, target_snapshot_id, "
                        "manifest_hash, approval_id, actor, reason, activated_at, created_at "
                        "FROM release_activation_audits ORDER BY id"
                    )
                )
            ),
            tuple(
                connection.execute(
                    text(
                        "SELECT id, space_id, snapshot_id, manifest_hash, code, severity, "
                        "safe_details::text, detected_at, created_at "
                        "FROM release_alerts ORDER BY id"
                    )
                )
            ),
        )
    assert after_rows == before_rows
