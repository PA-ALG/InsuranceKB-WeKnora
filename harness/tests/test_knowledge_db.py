"""K1：知识域表与迁移（specs/mainchain.md）。"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

HARNESS_ROOT = Path(__file__).resolve().parents[1]

KNOWLEDGE_TABLES = {
    "claims",
    "claim_evidence",
    "claim_revisions",
    "change_sets",
    "change_items",
    "conflicts",
    "review_items",
    "release_snapshots",
    "snapshot_claims",
    "current_release",
}
PRODUCT_TABLES = {"insurance_products", "product_versions"}


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


def test_k1_1_upgrade_creates_knowledge_tables(migrated_db: str) -> None:
    inspector = inspect(create_engine(migrated_db))
    tables = set(inspector.get_table_names())
    assert KNOWLEDGE_TABLES <= tables
    assert PRODUCT_TABLES <= tables  # 0001 仍在


def test_k1_1_downgrade_to_0001_clean(migrated_db: str) -> None:
    command.downgrade(_alembic_cfg(migrated_db), "0001")
    inspector = inspect(create_engine(migrated_db))
    tables = set(inspector.get_table_names())
    assert not (KNOWLEDGE_TABLES & tables)
    assert PRODUCT_TABLES <= tables  # 只回退 0002


def test_k1_2_constraints(migrated_db: str) -> None:
    inspector = inspect(create_engine(migrated_db))

    def uq_columns(table: str) -> set[tuple[str, ...]]:
        return {tuple(u["column_names"]) for u in inspector.get_unique_constraints(table)}

    assert ("claim_id", "revision_no") in uq_columns("claim_revisions")
    assert ("source_kind", "external_record_id", "source_revision") in uq_columns("change_sets")
    assert ("review_key",) in uq_columns("review_items")
    assert ("snapshot_id", "claim_id") in uq_columns("snapshot_claims")
    assert ("label",) in uq_columns("release_snapshots")

    published_idx = [
        idx for idx in inspector.get_indexes("claims") if idx["name"] == "uq_claims_published"
    ]
    assert published_idx and published_idx[0]["unique"]  # 发布态部分唯一索引存在


def test_k1_3_claim_columns(migrated_db: str) -> None:
    inspector = inspect(create_engine(migrated_db))
    columns = {c["name"] for c in inspector.get_columns("claims")}
    assert {
        "subject_type",
        "product_version_id",
        "concept_id",
        "predicate",
        "value_state",
        "value",
        "effective_from",
        "effective_to",
        "status",
        "confidence",
        "extraction_method",
        "schema_version",
        "current_revision",
        "superseded_by",
        "pending_judge",
    } <= columns
