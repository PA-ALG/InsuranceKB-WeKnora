"""016 T2 migration: downgrade preflights refuse unsafe scope before any DDL."""

from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from alembic.util.exc import CommandError
from sqlalchemy import inspect, text

from tests.identity.knowledge_scope_migration.helpers import (
    LEGACY_SPACE_ID,
    _alembic_cfg,
    _alembic_head,
    _assert_scoped_schema,
    _database,
    _insert_space,
    _timestamps,
)


def test_s3_4_downgrade_rejects_multiple_spaces_before_ddl(tmp_path: Path) -> None:
    url, engine = _database(tmp_path, "downgrade-multiple")
    command.upgrade(_alembic_cfg(url), "head")

    _assert_scoped_schema(engine)
    with engine.begin() as connection:
        _insert_space(connection, LEGACY_SPACE_ID)
        _insert_space(connection, "space-b")
    before_tables = set(inspect(engine).get_table_names())
    before_product_columns = {
        column["name"] for column in inspect(engine).get_columns("insurance_products")
    }

    with pytest.raises(CommandError, match="multiple|exactly one|legacy-default"):
        command.downgrade(_alembic_cfg(url), "0002")

    assert set(inspect(engine).get_table_names()) == before_tables
    assert {
        column["name"] for column in inspect(engine).get_columns("insurance_products")
    } == before_product_columns
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            _alembic_head(url)
        )


def test_s3_4_downgrade_rejects_single_non_legacy_space(tmp_path: Path) -> None:
    url, engine = _database(tmp_path, "downgrade-non-legacy")
    command.upgrade(_alembic_cfg(url), "head")

    _assert_scoped_schema(engine)
    with engine.begin() as connection:
        _insert_space(connection, "space-a")
    before_tables = set(inspect(engine).get_table_names())

    with pytest.raises(CommandError, match="legacy-default"):
        command.downgrade(_alembic_cfg(url), "0002")

    assert set(inspect(engine).get_table_names()) == before_tables
    assert "space_id" in {
        column["name"] for column in inspect(engine).get_columns("insurance_products")
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            _alembic_head(url)
        )


@pytest.mark.parametrize("starting_revision", ["0018", "0017", "0016"])
def test_s3_4_partial_g3_head_rejects_unsafe_scope_before_any_ddl(
    tmp_path: Path,
    starting_revision: str,
) -> None:
    url, engine = _database(tmp_path, f"downgrade-from-{starting_revision}")
    command.upgrade(_alembic_cfg(url), starting_revision)
    with engine.begin() as connection:
        _insert_space(connection, LEGACY_SPACE_ID)
        _insert_space(connection, "space-b")
    before_tables = set(inspect(engine).get_table_names())

    with pytest.raises(CommandError, match="multiple|exactly one|legacy-default"):
        command.downgrade(_alembic_cfg(url), "0002")

    assert set(inspect(engine).get_table_names()) == before_tables
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            starting_revision
        )


def test_s3_4_relative_downgrade_rejects_unsafe_scope_before_any_ddl(
    tmp_path: Path,
) -> None:
    url, engine = _database(tmp_path, "downgrade-relative-to-0002")
    command.upgrade(_alembic_cfg(url), "head")
    with engine.begin() as connection:
        _insert_space(connection, LEGACY_SPACE_ID)
        _insert_space(connection, "space-b")
    before_tables = set(inspect(engine).get_table_names())

    with pytest.raises(CommandError, match="multiple|exactly one|legacy-default"):
        command.downgrade(_alembic_cfg(url), "-9")

    assert set(inspect(engine).get_table_names()) == before_tables
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0018"


@pytest.mark.parametrize("destination", ["0006", "-4"])
def test_s3_4_downgrade_does_not_apply_scope_preflight_before_scope_territory(
    tmp_path: Path,
    destination: str,
) -> None:
    url, engine = _database(tmp_path, f"downgrade-to-0006-{destination}")
    command.upgrade(_alembic_cfg(url), "head")
    with engine.begin() as connection:
        _insert_space(connection, LEGACY_SPACE_ID)
        _insert_space(connection, "space-b")

    command.downgrade(_alembic_cfg(url), destination)

    assert "knowledge_spaces" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0006"
        assert connection.scalar(text("SELECT count(*) FROM knowledge_spaces")) == 2


def test_s3_4_offline_downgrade_refuses_before_emitting_ddl() -> None:
    output = StringIO()
    config = _alembic_cfg("sqlite://")
    config.output_buffer = output

    with pytest.raises(RuntimeError, match="offline.*preflight|preflight.*offline"):
        command.downgrade(config, "0018:0002", sql=True)

    assert "DROP " not in output.getvalue().upper()


@pytest.mark.parametrize(
    ("table", "seed_sql", "conflict_key"),
    [
        (
            "product_versions",
            """
            INSERT INTO product_versions
                (id, space_id, product_id, version_label, created_at, updated_at)
            VALUES
                ('version-a', 'orphan-a', 'product-shared', 'version-shared',
                 :created_at, :updated_at),
                ('version-b', 'orphan-b', 'product-shared', 'version-shared',
                 :created_at, :updated_at)
            """,
            ("product-shared", "version-shared"),
        ),
        (
            "product_documents",
            """
            INSERT INTO product_documents
                (id, space_id, product_id, file_name, doc_type, sha256, source_path,
                 created_at, updated_at)
            VALUES
                ('document-a', 'orphan-a', 'product-shared', 'a.pdf', 'terms',
                 'sha-shared', '/a.pdf', :created_at, :updated_at),
                ('document-b', 'orphan-b', 'product-shared', 'b.pdf', 'terms',
                 'sha-shared', '/b.pdf', :created_at, :updated_at)
            """,
            ("product-shared", "sha-shared"),
        ),
        (
            "claims",
            """
            INSERT INTO claims
                (id, space_id, subject_type, product_version_id, concept_id, predicate,
                 value_state, effective_from, status, confidence, extraction_method,
                 schema_version, current_revision, pending_judge, created_at, updated_at)
            VALUES
                ('claim-a', 'orphan-a', 'product_version', 'version-shared',
                 'concept-shared', 'benefit', 'present', '2026-01-01', 'published', 0.9,
                 'manual', 'v1', 1, 0, :created_at, :updated_at),
                ('claim-b', 'orphan-b', 'product_version', 'version-shared',
                 'concept-shared', 'benefit', 'present', '2026-01-01', 'published', 0.9,
                 'manual', 'v1', 1, 0, :created_at, :updated_at)
            """,
            ("version-shared", "concept-shared", "benefit", "2026-01-01"),
        ),
        (
            "snapshot_claims",
            """
            INSERT INTO snapshot_claims
                (id, space_id, snapshot_id, claim_id, revision_no, created_at, updated_at)
            VALUES
                ('snapshot-claim-a', 'orphan-a', 'snapshot-shared', 'claim-shared', 1,
                 :created_at, :updated_at),
                ('snapshot-claim-b', 'orphan-b', 'snapshot-shared', 'claim-shared', 1,
                 :created_at, :updated_at)
            """,
            ("snapshot-shared", "claim-shared"),
        ),
    ],
)
def test_s3_4_downgrade_lists_global_key_conflicts_before_ddl(
    tmp_path: Path,
    table: str,
    seed_sql: str,
    conflict_key: tuple[str, ...],
) -> None:
    url, engine = _database(tmp_path, f"downgrade-conflict-{table}")
    command.upgrade(_alembic_cfg(url), "head")
    with engine.begin() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 0
        _insert_space(connection, LEGACY_SPACE_ID)
        connection.execute(text(seed_sql), _timestamps())

    before_inspector = inspect(engine)
    before_tables = set(before_inspector.get_table_names())
    before_space_columns = {
        scoped_table: "space_id"
        in {column["name"] for column in before_inspector.get_columns(scoped_table)}
        for scoped_table in (
            "insurance_products",
            "product_versions",
            "product_documents",
            "unassigned_pool",
            "claims",
            "change_sets",
            "review_items",
            "release_snapshots",
            "snapshot_claims",
            "current_release",
        )
    }
    with engine.connect() as connection:
        before_rows = connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).all()

    with pytest.raises(CommandError) as error:
        command.downgrade(_alembic_cfg(url), "0002")

    message = str(error.value)
    assert table in message
    for value in conflict_key:
        assert value in message
    assert "count=2" in message
    after_inspector = inspect(engine)
    assert set(after_inspector.get_table_names()) == before_tables
    assert {
        scoped_table: "space_id"
        in {column["name"] for column in after_inspector.get_columns(scoped_table)}
        for scoped_table in before_space_columns
    } == before_space_columns
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            _alembic_head(url)
        )
        assert connection.scalar(text("SELECT count(*) FROM knowledge_spaces")) == 1
        assert connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).all() == before_rows
