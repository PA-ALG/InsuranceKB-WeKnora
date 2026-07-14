"""P1/016：产品域迁移与作用域表结构。"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

HARNESS_ROOT = Path(__file__).resolve().parents[1]

TABLES = {
    "knowledge_spaces",
    "insurance_products",
    "product_aliases",
    "product_versions",
    "product_documents",
    "unassigned_pool",
}


def _insert_legacy_space(db_url: str) -> None:
    now = datetime.now(UTC)
    with create_engine(db_url).begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO knowledge_spaces
                    (id, name, binding_status, created_at, updated_at)
                VALUES
                    ('legacy-default', 'Legacy Default', 'unbound', :now, :now)
                """
            ),
            {"now": now},
        )


def _alembic_cfg(db_url: str) -> Config:
    cfg = Config(str(HARNESS_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(HARNESS_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.fixture()
def migrated_db(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path}/harness.db"
    command.upgrade(_alembic_cfg(url), "head")
    return url


def test_p1_1_upgrade_creates_tables(migrated_db: str) -> None:
    inspector = inspect(create_engine(migrated_db))
    assert TABLES <= set(inspector.get_table_names())


def test_p1_1_downgrade_base_clean(migrated_db: str) -> None:
    _insert_legacy_space(migrated_db)
    command.downgrade(_alembic_cfg(migrated_db), "base")
    inspector = inspect(create_engine(migrated_db))
    assert not (TABLES & set(inspector.get_table_names()))


def test_p1_2_unique_constraints(migrated_db: str) -> None:
    inspector = inspect(create_engine(migrated_db))

    def uq_columns(table: str) -> set[tuple[str, ...]]:
        return {tuple(u["column_names"]) for u in inspector.get_unique_constraints(table)}

    assert ("space_id", "product_code") in uq_columns("insurance_products")
    assert ("product_code",) not in uq_columns("insurance_products")
    assert ("product_id", "alias") in uq_columns("product_aliases")
    assert ("space_id", "product_id", "version_label") in uq_columns("product_versions")
    assert ("space_id", "product_id", "sha256") in uq_columns("product_documents")


def test_p1_3_scoped_product_columns(migrated_db: str) -> None:
    inspector = inspect(create_engine(migrated_db))
    for table in (
        "insurance_products",
        "product_versions",
        "product_documents",
        "unassigned_pool",
    ):
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        assert "space_id" in columns
        assert not columns["space_id"]["nullable"]

    space_uniques = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("knowledge_spaces")
    }
    assert ("tenant_id", "raw_kb_id") in space_uniques
    assert ("tenant_id", "wiki_kb_id") in space_uniques

    document_fks = {
        tuple(foreign_key["constrained_columns"]): tuple(
            foreign_key["referred_columns"]
        )
        for foreign_key in inspector.get_foreign_keys("product_documents")
    }
    assert document_fks[("space_id", "version_id")] == ("space_id", "id")
