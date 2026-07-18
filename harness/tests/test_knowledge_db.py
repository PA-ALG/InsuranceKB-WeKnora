"""K1/016：知识域表、迁移与作用域约束。"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

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
    "snapshot_facts",
    "snapshot_claims",
    "current_release",
    "release_operations",
    "publish_attempts",
    "reconciliation_jobs",
}
PRODUCT_TABLES = {"insurance_products", "product_versions"}


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


def test_k1_1_upgrade_creates_knowledge_tables(migrated_db: str) -> None:
    inspector = inspect(create_engine(migrated_db))
    tables = set(inspector.get_table_names())
    assert KNOWLEDGE_TABLES <= tables
    assert PRODUCT_TABLES <= tables  # 0001 仍在
    assert "knowledge_spaces" in tables


def test_k1_1_downgrade_to_0001_clean(migrated_db: str) -> None:
    _insert_legacy_space(migrated_db)
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
    assert (
        "space_id",
        "source_kind",
        "external_record_id",
        "source_revision",
    ) in uq_columns("change_sets")
    assert ("space_id", "review_key") in uq_columns("review_items")
    assert ("space_id", "snapshot_id", "claim_id") in uq_columns("snapshot_claims")
    assert (
        "space_id",
        "snapshot_id",
        "claim_id",
        "revision_no",
    ) in uq_columns("snapshot_facts")
    assert ("space_id", "label") in uq_columns("release_snapshots")
    assert ("space_id",) in uq_columns("current_release")
    assert ("review_key",) not in uq_columns("review_items")
    assert ("label",) not in uq_columns("release_snapshots")

    published_idx = [
        idx for idx in inspector.get_indexes("claims") if idx["name"] == "uq_claims_published"
    ]
    assert published_idx and published_idx[0]["unique"]  # 发布态部分唯一索引存在
    assert published_idx[0]["column_names"][0] == "space_id"


def test_k1_3_claim_columns(migrated_db: str) -> None:
    inspector = inspect(create_engine(migrated_db))
    columns = {c["name"] for c in inspector.get_columns("claims")}
    assert {
        "space_id",
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


def test_k1_4_scoped_knowledge_columns(migrated_db: str) -> None:
    inspector = inspect(create_engine(migrated_db))
    for table in (
        "claims",
        "change_sets",
        "review_items",
        "release_snapshots",
        "snapshot_facts",
        "snapshot_claims",
        "current_release",
        "release_operations",
        "publish_attempts",
        "reconciliation_jobs",
    ):
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        assert "space_id" in columns
        assert not columns["space_id"]["nullable"]

    assert inspector.get_pk_constraint("current_release")["constrained_columns"] == [
        "space_id",
        "id",
    ]

    claim_fks = {
        tuple(foreign_key["constrained_columns"]): tuple(
            foreign_key["referred_columns"]
        )
        for foreign_key in inspector.get_foreign_keys("claims")
    }
    assert claim_fks[("space_id", "superseded_by")] == ("space_id", "id")


def test_t6_claim_evidence_source_lineage_columns_and_indexes(
    migrated_db: str,
) -> None:
    inspector = inspect(create_engine(migrated_db))
    columns = {column["name"]: column for column in inspector.get_columns("claim_evidence")}

    assert {
        "raw_kb_id",
        "source_revision",
        "file_hash",
        "original_digest",
        "parser_version",
        "chunk_hash",
        "lineage_status",
        "stale_at",
    } <= set(columns)
    assert all(
        columns[name]["nullable"]
        for name in (
            "raw_kb_id",
            "source_revision",
            "file_hash",
            "original_digest",
            "parser_version",
            "chunk_hash",
            "lineage_status",
            "stale_at",
        )
    )
    indexes = {
        tuple(index["column_names"])
        for index in inspector.get_indexes("claim_evidence")
    }
    assert ("knowledge_id", "source_revision") in indexes
    assert any("stale_at" in index for index in indexes)
