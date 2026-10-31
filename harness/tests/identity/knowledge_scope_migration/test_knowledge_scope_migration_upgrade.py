"""016 T2 migration: backfills, empty installs and cross-space database isolation."""

from pathlib import Path
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Connection, inspect, text
from sqlalchemy.exc import IntegrityError

from tests.identity.knowledge_scope_migration.helpers import (
    LEGACY_SPACE_ID,
    _alembic_cfg,
    _assert_scoped_schema,
    _database,
    _insert_knowledge_rows,
    _insert_product_rows,
    _insert_space,
    _space_ids,
    _timestamps,
)


def _insert_scoped_product(
    connection: Connection, product_id: str, space_id: str, product_code: str
) -> None:
    parameters: dict[str, Any] = _timestamps()
    parameters.update({"id": product_id, "space_id": space_id, "product_code": product_code})
    connection.execute(
        text(
            """
            INSERT INTO insurance_products
                (id, space_id, product_code, canonical_name, category, status,
                 created_at, updated_at)
            VALUES
                (:id, :space_id, :product_code, :product_code, 'life', 'active',
                 :created_at, :updated_at)
            """
        ),
        parameters,
    )


def test_s3_1_upgrade_from_0001_backfills_product_rows(tmp_path: Path) -> None:
    url, engine = _database(tmp_path, "from-0001")
    command.upgrade(_alembic_cfg(url), "0001")
    with engine.begin() as connection:
        _insert_product_rows(connection)

    command.upgrade(_alembic_cfg(url), "head")

    _assert_scoped_schema(engine)
    with engine.connect() as connection:
        legacy = connection.execute(
            text(
                """
                SELECT binding_status, tenant_id, raw_kb_id, wiki_kb_id
                FROM knowledge_spaces WHERE id = :space_id
                """
            ),
            {"space_id": LEGACY_SPACE_ID},
        ).one()
        assert tuple(legacy) == ("unbound", None, None, None)
        for table in (
            "insurance_products",
            "product_versions",
            "product_documents",
            "unassigned_pool",
        ):
            assert _space_ids(connection, table) == {LEGACY_SPACE_ID}


def test_s3_1_upgrade_from_0002_backfills_product_and_knowledge_rows(
    tmp_path: Path,
) -> None:
    url, engine = _database(tmp_path, "from-0002")
    command.upgrade(_alembic_cfg(url), "0002")
    with engine.begin() as connection:
        _insert_product_rows(connection)
        _insert_knowledge_rows(connection)

    command.upgrade(_alembic_cfg(url), "head")

    _assert_scoped_schema(engine)
    with engine.connect() as connection:
        for table in (
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
        ):
            assert _space_ids(connection, table) == {LEGACY_SPACE_ID}


def test_s3_3_empty_install_does_not_create_default_space(tmp_path: Path) -> None:
    url, engine = _database(tmp_path, "empty")
    command.upgrade(_alembic_cfg(url), "head")

    _assert_scoped_schema(engine)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM knowledge_spaces")) == 0


def test_s3_3_empty_install_round_trips_0003_to_0002(tmp_path: Path) -> None:
    url, engine = _database(tmp_path, "empty-downgrade")
    command.upgrade(_alembic_cfg(url), "0003")

    _assert_scoped_schema(engine)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM knowledge_spaces")) == 0

    command.downgrade(_alembic_cfg(url), "0002")

    inspector = inspect(engine)
    assert "knowledge_spaces" not in inspector.get_table_names()
    assert "space_id" not in {
        column["name"] for column in inspector.get_columns("insurance_products")
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0002"


def test_s1_1_bound_space_requires_all_three_bindings(tmp_path: Path) -> None:
    url, engine = _database(tmp_path, "binding-shape")
    command.upgrade(_alembic_cfg(url), "head")

    _assert_scoped_schema(engine)
    with engine.begin() as connection, pytest.raises(IntegrityError):
        _insert_space(
            connection,
            "incomplete-bound",
            tenant_id="tenant-1",
            raw_kb_id="raw-1",
        )


def test_s2_4_same_product_code_is_unique_only_within_space(tmp_path: Path) -> None:
    url, engine = _database(tmp_path, "product-unique")
    command.upgrade(_alembic_cfg(url), "head")

    _assert_scoped_schema(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys = ON")
        _insert_space(
            connection,
            "space-a",
            tenant_id="tenant-a",
            raw_kb_id="raw-a",
            wiki_kb_id="wiki-a",
        )
        _insert_space(
            connection,
            "space-b",
            tenant_id="tenant-b",
            raw_kb_id="raw-b",
            wiki_kb_id="wiki-b",
        )
        _insert_scoped_product(connection, "product-a", "space-a", "same-code")
        _insert_scoped_product(connection, "product-b", "space-b", "same-code")
        with pytest.raises(IntegrityError):
            _insert_scoped_product(connection, "product-a2", "space-a", "same-code")


def test_s2_2_product_document_rejects_cross_space_product(tmp_path: Path) -> None:
    url, engine = _database(tmp_path, "document-scope")
    command.upgrade(_alembic_cfg(url), "head")

    _assert_scoped_schema(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys = ON")
        _insert_space(connection, "space-a")
        _insert_space(connection, "space-b")
        _insert_scoped_product(connection, "product-a", "space-a", "product-a")
        with pytest.raises(IntegrityError):
            parameters: dict[str, Any] = _timestamps()
            parameters.update({"space_id": "space-b", "product_id": "product-a"})
            connection.execute(
                text(
                    """
                    INSERT INTO product_documents
                        (id, space_id, product_id, file_name, doc_type, sha256, source_path,
                         created_at, updated_at)
                    VALUES
                        ('document-b', :space_id, :product_id, 'terms.pdf', 'terms', 'sha-b',
                         '/terms.pdf', :created_at, :updated_at)
                    """
                ),
                parameters,
            )


def test_s2_2_product_document_rejects_cross_space_version(tmp_path: Path) -> None:
    url, engine = _database(tmp_path, "document-version-scope")
    command.upgrade(_alembic_cfg(url), "head")

    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys = ON")
        _insert_space(connection, "space-a")
        _insert_space(connection, "space-b")
        _insert_scoped_product(connection, "product-a", "space-a", "product-a")
        _insert_scoped_product(connection, "product-b", "space-b", "product-b")
        timestamps = _timestamps()
        connection.execute(
            text(
                """
                INSERT INTO product_versions
                    (id, space_id, product_id, version_label, created_at, updated_at)
                VALUES
                    ('version-a', 'space-a', 'product-a', 'v1', :created_at, :updated_at),
                    ('version-b', 'space-b', 'product-b', 'v1', :created_at, :updated_at)
                """
            ),
            timestamps,
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO product_documents
                        (id, space_id, product_id, version_id, file_name, doc_type, sha256,
                         source_path, created_at, updated_at)
                    VALUES
                        ('document-a', 'space-a', 'product-a', 'version-b', 'terms.pdf',
                         'terms', 'sha-a', '/terms.pdf', :created_at, :updated_at)
                    """
                ),
                timestamps,
            )


def test_s2_2_claim_rejects_cross_space_product_version(tmp_path: Path) -> None:
    url, engine = _database(tmp_path, "claim-scope")
    command.upgrade(_alembic_cfg(url), "head")

    _assert_scoped_schema(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys = ON")
        _insert_space(connection, "space-a")
        _insert_space(connection, "space-b")
        _insert_scoped_product(connection, "product-a", "space-a", "product-a")
        timestamps = _timestamps()
        connection.execute(
            text(
                """
                INSERT INTO product_versions
                    (id, space_id, product_id, version_label, created_at, updated_at)
                VALUES
                    ('version-a', 'space-a', 'product-a', 'v1', :created_at, :updated_at)
                """
            ),
            timestamps,
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO claims
                        (id, space_id, subject_type, product_version_id, predicate, value_state,
                         status, confidence, extraction_method, schema_version, current_revision,
                         pending_judge, created_at, updated_at)
                    VALUES
                        ('claim-b', 'space-b', 'product_version', 'version-a', 'benefit',
                         'present', 'draft', 0.9, 'manual', 'v1', 1, 0,
                         :created_at, :updated_at)
                    """
                ),
                timestamps,
            )


def test_s2_2_claim_rejects_cross_space_superseded_by(tmp_path: Path) -> None:
    url, engine = _database(tmp_path, "claim-superseded-scope")
    command.upgrade(_alembic_cfg(url), "head")

    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys = ON")
        _insert_space(connection, "space-a")
        _insert_space(connection, "space-b")
        timestamps = _timestamps()
        connection.execute(
            text(
                """
                INSERT INTO claims
                    (id, space_id, subject_type, predicate, value_state, status, confidence,
                     extraction_method, schema_version, current_revision, pending_judge,
                     created_at, updated_at)
                VALUES
                    ('claim-a', 'space-a', 'concept', 'benefit', 'present', 'superseded', 0.9,
                     'manual', 'v1', 1, 0, :created_at, :updated_at)
                """
            ),
            timestamps,
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO claims
                        (id, space_id, subject_type, predicate, value_state, status,
                         confidence, extraction_method, schema_version, current_revision,
                         superseded_by, pending_judge, created_at, updated_at)
                    VALUES
                        ('claim-b', 'space-b', 'concept', 'benefit', 'present', 'superseded',
                         0.9, 'manual', 'v1', 1, 'claim-a', 0, :created_at, :updated_at)
                    """
                ),
                timestamps,
            )


def test_s2_2_snapshot_claim_rejects_cross_space_claim(tmp_path: Path) -> None:
    url, engine = _database(tmp_path, "snapshot-claim-scope")
    command.upgrade(_alembic_cfg(url), "head")

    _assert_scoped_schema(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys = ON")
        _insert_space(connection, "space-a")
        _insert_space(connection, "space-b")
        timestamps = _timestamps()
        connection.execute(
            text(
                """
                INSERT INTO claims
                    (id, space_id, subject_type, predicate, value_state, status, confidence,
                     extraction_method, schema_version, current_revision, pending_judge,
                     created_at, updated_at)
                VALUES
                    ('claim-a', 'space-a', 'concept', 'benefit', 'present', 'draft', 0.9,
                     'manual', 'v1', 1, 0, :created_at, :updated_at)
                """
            ),
            timestamps,
        )
        connection.execute(
            text(
                """
                INSERT INTO release_snapshots
                    (id, space_id, label, published_at, published_by, created_at, updated_at)
                VALUES
                    ('snapshot-b', 'space-b', 'release-b', :created_at, 'tester',
                     :created_at, :updated_at)
                """
            ),
            timestamps,
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO snapshot_claims
                        (id, space_id, snapshot_id, claim_id, revision_no,
                         created_at, updated_at)
                    VALUES
                        ('snapshot-claim-b', 'space-b', 'snapshot-b', 'claim-a', 1,
                         :created_at, :updated_at)
                    """
                ),
                timestamps,
            )
