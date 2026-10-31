"""016 T2 migration: published claim keys and the legacy data round trip."""

from pathlib import Path
from typing import Any

import pytest
from alembic import command
from sqlalchemy import inspect, text

from tests.identity.knowledge_scope_migration.helpers import (
    LEGACY_SPACE_ID,
    _alembic_cfg,
    _alembic_head,
    _assert_scoped_schema,
    _database,
    _insert_knowledge_rows,
    _insert_product_rows,
    _insert_space,
    _space_ids,
    _timestamps,
)


@pytest.mark.parametrize(
    ("product_version_id", "concept_id", "effective_from"),
    [
        (None, "concept-shared", "2026-01-01"),
        ("version-shared", None, "2026-01-01"),
        ("version-shared", "concept-shared", None),
    ],
)
def test_s3_4_downgrade_allows_published_claim_key_with_null_component(
    tmp_path: Path,
    product_version_id: str | None,
    concept_id: str | None,
    effective_from: str | None,
) -> None:
    url, engine = _database(
        tmp_path,
        "downgrade-null-claim-"
        f"{product_version_id or 'null'}-{concept_id or 'null'}-{effective_from or 'null'}",
    )
    command.upgrade(_alembic_cfg(url), "head")
    parameters: dict[str, Any] = _timestamps()
    parameters.update(
        {
            "product_version_id": product_version_id,
            "concept_id": concept_id,
            "effective_from": effective_from,
        }
    )
    with engine.begin() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 0
        _insert_space(connection, LEGACY_SPACE_ID)
        connection.execute(
            text(
                """
                INSERT INTO claims
                    (id, space_id, subject_type, product_version_id, concept_id, predicate,
                     value_state, effective_from, status, confidence, extraction_method,
                     schema_version, current_revision, pending_judge, created_at, updated_at)
                VALUES
                    ('claim-a', 'orphan-a', 'product_version', :product_version_id,
                     :concept_id, 'benefit', 'present', :effective_from, 'published', 0.9,
                     'manual', 'v1', 1, 0, :created_at, :updated_at),
                    ('claim-b', 'orphan-b', 'product_version', :product_version_id,
                     :concept_id, 'benefit', 'present', :effective_from, 'published', 0.9,
                     'manual', 'v1', 1, 0, :created_at, :updated_at)
                """
            ),
            parameters,
        )

    command.downgrade(_alembic_cfg(url), "0002")

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0002"
        assert connection.scalar(text("SELECT count(*) FROM claims")) == 2


def test_s3_4_legacy_data_round_trips_head_to_0002_and_back_to_head(
    tmp_path: Path,
) -> None:
    url, engine = _database(tmp_path, "downgrade-legacy")
    command.upgrade(_alembic_cfg(url), "0002")
    with engine.begin() as connection:
        _insert_product_rows(connection)
        _insert_knowledge_rows(connection)
    command.upgrade(_alembic_cfg(url), "head")

    _assert_scoped_schema(engine)
    command.downgrade(_alembic_cfg(url), "0002")

    inspector = inspect(engine)
    assert "knowledge_spaces" not in inspector.get_table_names()
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
        assert "space_id" not in {column["name"] for column in inspector.get_columns(table)}
    product_uniques = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("insurance_products")
    }
    assert ("product_code",) in product_uniques
    document_fks = {
        tuple(foreign_key["constrained_columns"]): tuple(
            foreign_key["referred_columns"]
        )
        for foreign_key in inspector.get_foreign_keys("product_documents")
    }
    claim_fks = {
        tuple(foreign_key["constrained_columns"]): tuple(
            foreign_key["referred_columns"]
        )
        for foreign_key in inspector.get_foreign_keys("claims")
    }
    assert document_fks[("version_id",)] == ("id",)
    assert claim_fks[("superseded_by",)] == ("id",)
    assert ("space_id", "version_id") not in document_fks
    assert ("space_id", "superseded_by") not in claim_fks
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM insurance_products")) == 1
        assert connection.scalar(text("SELECT count(*) FROM claims")) == 1
        assert connection.scalar(text("SELECT count(*) FROM snapshot_claims")) == 1
        assert connection.scalar(text("SELECT id FROM current_release")) == "current"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0002"

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
        assert connection.scalar(text("SELECT count(*) FROM insurance_products")) == 1
        assert connection.scalar(text("SELECT count(*) FROM claims")) == 1
        assert connection.scalar(text("SELECT count(*) FROM snapshot_claims")) == 1
        assert connection.scalar(text("SELECT id FROM current_release")) == "current"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            _alembic_head(url)
        )

    scoped_product_uniques = {
        tuple(constraint["column_names"])
        for constraint in inspect(engine).get_unique_constraints("insurance_products")
    }
    assert ("space_id", "product_code") in scoped_product_uniques
    scoped_document_fks = {
        tuple(foreign_key["constrained_columns"]): tuple(
            foreign_key["referred_columns"]
        )
        for foreign_key in inspect(engine).get_foreign_keys("product_documents")
    }
    scoped_claim_fks = {
        tuple(foreign_key["constrained_columns"]): tuple(
            foreign_key["referred_columns"]
        )
        for foreign_key in inspect(engine).get_foreign_keys("claims")
    }
    assert scoped_document_fks[("space_id", "version_id")] == ("space_id", "id")
    assert scoped_claim_fks[("space_id", "superseded_by")] == ("space_id", "id")
