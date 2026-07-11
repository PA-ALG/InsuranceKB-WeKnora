"""P1：迁移与表结构。"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

HARNESS_ROOT = Path(__file__).resolve().parents[1]

TABLES = {
    "insurance_products",
    "product_aliases",
    "product_versions",
    "product_documents",
    "unassigned_pool",
}


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
    command.downgrade(_alembic_cfg(migrated_db), "base")
    inspector = inspect(create_engine(migrated_db))
    assert not (TABLES & set(inspector.get_table_names()))


def test_p1_2_unique_constraints(migrated_db: str) -> None:
    inspector = inspect(create_engine(migrated_db))

    def uq_columns(table: str) -> set[tuple[str, ...]]:
        return {tuple(u["column_names"]) for u in inspector.get_unique_constraints(table)}

    assert ("product_code",) in uq_columns("insurance_products")
    assert ("product_id", "alias") in uq_columns("product_aliases")
    assert ("product_id", "version_label") in uq_columns("product_versions")
    assert ("product_id", "sha256") in uq_columns("product_documents")
