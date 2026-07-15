"""OpenSpec 018 T1b: 0005 release read-model migration contract."""

import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text

HARNESS_ROOT = Path(__file__).resolve().parents[1]
NEW_TABLES = {
    "snapshot_facts",
    "release_operations",
    "publish_attempts",
    "reconciliation_jobs",
}
RELEASE_GUARD_TRIGGERS = {
    "trg_current_release_insert_guard_018",
    "trg_current_release_update_guard_018",
    "trg_release_operations_plan_guard_018",
    "trg_release_snapshots_projection_guard_018",
    "trg_snapshot_facts_delete_guard_018",
    "trg_snapshot_facts_insert_guard_018",
    "trg_snapshot_facts_update_guard_018",
}


def _cfg(url: str, *, output: StringIO | None = None) -> Config:
    config = Config(str(HARNESS_ROOT / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(HARNESS_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _db(tmp_path: Path, name: str) -> tuple[str, Engine]:
    url = f"sqlite:///{tmp_path}/{name}.db"
    return url, create_engine(url)


def _seed_legacy_snapshot(engine: Engine) -> None:
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO knowledge_spaces
                    (id, tenant_id, raw_kb_id, wiki_kb_id, name, binding_status,
                     created_at, updated_at)
                VALUES ('space-1', 'tenant-1', 'raw-1', 'wiki-1', 'Space', 'bound',
                        :now, :now)
                """
            ),
            {"now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO release_snapshots
                    (id, space_id, label, rendered_pages, published_at, published_by,
                     notes, created_at, updated_at)
                VALUES ('snapshot-legacy', 'space-1', 'legacy-v1', :pages, :now,
                        'legacy-publisher', NULL, :now, :now)
                """
            ),
            {
                "now": now,
                "pages": json.dumps([{"slug": "product/P/V1/overview", "content": "legacy"}]),
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO current_release
                    (space_id, id, snapshot_id, created_at, updated_at)
                VALUES ('space-1', 'current', 'snapshot-legacy', :now, :now)
                """
            ),
            {"now": now},
        )


def test_r1_1_0005_creates_release_read_model_tables_and_columns(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "schema")
    command.upgrade(_cfg(url), "head")
    inspector = inspect(engine)

    assert NEW_TABLES <= set(inspector.get_table_names())
    snapshot_columns = {
        column["name"]: column for column in inspector.get_columns("release_snapshots")
    }
    assert {"status", "read_model_version", "projection_frozen_at"} <= set(snapshot_columns)
    assert snapshot_columns["published_at"]["nullable"]
    assert {
        "space_id",
        "snapshot_id",
        "claim_id",
        "revision_no",
        "product_id",
        "product_version_id",
        "product_code",
        "product_name",
        "version_label",
        "field_name",
        "field_group",
        "predicate",
        "value_state",
        "value",
        "effective_from",
        "effective_to",
        "confidence",
        "schema_version",
        "evidence",
    } <= {column["name"] for column in inspector.get_columns("snapshot_facts")}


def test_r1_2_0005_installs_release_immutability_guards(tmp_path: Path) -> None:
    url, engine = _db(tmp_path, "release-guards")
    command.upgrade(_cfg(url), "head")

    with engine.connect() as connection:
        triggers = set(
            connection.scalars(
                text("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE '%_018'")
            )
        )

    assert RELEASE_GUARD_TRIGGERS <= triggers


def test_r1_4_0004_to_0005_preserves_legacy_pointer_without_fact_backfill(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "legacy-upgrade")
    command.upgrade(_cfg(url), "0004")
    _seed_legacy_snapshot(engine)

    command.upgrade(_cfg(url), "0005")

    with engine.connect() as connection:
        snapshot = connection.execute(
            text(
                "SELECT status, read_model_version, published_at "
                "FROM release_snapshots WHERE id='snapshot-legacy'"
            )
        ).one()
        pointer = connection.scalar(
            text("SELECT snapshot_id FROM current_release WHERE space_id='space-1'")
        )
        fact_count = connection.scalar(text("SELECT count(*) FROM snapshot_facts"))

    assert snapshot.status == "published"
    assert snapshot.read_model_version == 0
    assert snapshot.published_at is not None
    assert pointer == "snapshot-legacy"
    assert fact_count == 0


def test_r1_4_0005_downgrade_preserves_inherited_legacy_rows(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "legacy-downgrade")
    command.upgrade(_cfg(url), "0004")
    _seed_legacy_snapshot(engine)
    command.upgrade(_cfg(url), "0005")

    command.downgrade(_cfg(url), "0004")

    inspector = inspect(engine)
    assert NEW_TABLES.isdisjoint(inspector.get_table_names())
    assert "status" not in {column["name"] for column in inspector.get_columns("release_snapshots")}
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT snapshot_id FROM current_release WHERE space_id='space-1'")
            )
            == "snapshot-legacy"
        )
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0004"


def test_r1_4_0005_downgrade_refuses_version_one_release_data(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "unsafe-downgrade")
    command.upgrade(_cfg(url), "0004")
    _seed_legacy_snapshot(engine)
    command.upgrade(_cfg(url), "0005")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE release_snapshots SET read_model_version=1 WHERE id='snapshot-legacy'")
        )

    with pytest.raises(RuntimeError, match="0005 downgrade refused"):
        command.downgrade(_cfg(url), "0004")

    assert set(inspect(engine).get_table_names()) >= NEW_TABLES
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0005"


def test_r3_1_post_migration_raw_snapshot_defaults_to_building_version_one(
    tmp_path: Path,
) -> None:
    url, engine = _db(tmp_path, "new-default")
    command.upgrade(_cfg(url), "head")
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO knowledge_spaces
                    (id, tenant_id, raw_kb_id, wiki_kb_id, name, binding_status,
                     created_at, updated_at)
                VALUES ('space-1', 'tenant-1', 'raw-1', 'wiki-1', 'Space', 'bound',
                        :now, :now)
                """
            ),
            {"now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO release_snapshots
                    (id, space_id, label, rendered_pages, published_at, published_by,
                     notes, created_at, updated_at)
                VALUES ('snapshot-new', 'space-1', 'new-v1', '[]', :now,
                        'publisher', NULL, :now, :now)
                """
            ),
            {"now": now},
        )
        snapshot = connection.execute(
            text(
                "SELECT status, read_model_version, projection_frozen_at "
                "FROM release_snapshots "
                "WHERE id='snapshot-new'"
            )
        ).one()

    assert snapshot.status == "building"
    assert snapshot.read_model_version == 1
    assert snapshot.projection_frozen_at is None
    with pytest.raises(RuntimeError, match="0005 downgrade refused"):
        command.downgrade(_cfg(url), "0004")


def test_r1_4_0005_metadata_matches_head_and_alembic_check(tmp_path: Path) -> None:
    url, _engine = _db(tmp_path, "alembic-check")
    command.upgrade(_cfg(url), "head")
    command.check(_cfg(url))


def test_r1_4_0005_postgresql_offline_ddl_compiles() -> None:
    output = StringIO()
    command.upgrade(
        _cfg("postgresql://user:password@localhost/insurance", output=output),
        "0004:0005",
        sql=True,
    )

    ddl = output.getvalue().lower()
    assert all(table in ddl for table in NEW_TABLES)
    assert "read_model_version" in ddl and "projection_frozen_at" in ddl
    assert "uq_snapshot_fact_claim_revision" in ddl
    assert "ck_release_operations_status" in ddl
    assert all(trigger in ddl for trigger in RELEASE_GUARD_TRIGGERS)
