"""016 T2: enterprise knowledge-space migration and database isolation."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import Connection, Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

HARNESS_ROOT = Path(__file__).resolve().parents[1]
LEGACY_SPACE_ID = "legacy-default"


def _alembic_cfg(db_url: str) -> Config:
    cfg = Config(str(HARNESS_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(HARNESS_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _alembic_head(db_url: str) -> str:
    head = ScriptDirectory.from_config(_alembic_cfg(db_url)).get_current_head()
    assert head is not None
    return head


def _database(tmp_path: Path, name: str) -> tuple[str, Engine]:
    url = f"sqlite:///{tmp_path}/{name}.db"
    return url, create_engine(url)


def _assert_scoped_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    assert "knowledge_spaces" in inspector.get_table_names()
    assert "space_id" in {column["name"] for column in inspector.get_columns("claims")}


def _timestamps() -> dict[str, datetime]:
    now = datetime.now(UTC)
    return {"created_at": now, "updated_at": now}


def _insert_product_rows(connection: Connection) -> None:
    timestamps = _timestamps()
    connection.execute(
        text(
            """
            INSERT INTO insurance_products
                (id, product_code, canonical_name, category, status, created_at, updated_at)
            VALUES
                ('product-1', 'shared-code', 'Legacy Product', 'life', 'active',
                 :created_at, :updated_at)
            """
        ),
        timestamps,
    )
    connection.execute(
        text(
            """
            INSERT INTO product_versions
                (id, product_id, version_label, created_at, updated_at)
            VALUES
                ('version-1', 'product-1', 'v1', :created_at, :updated_at)
            """
        ),
        timestamps,
    )
    connection.execute(
        text(
            """
            INSERT INTO product_documents
                (id, product_id, version_id, file_name, doc_type, sha256, source_path,
                 created_at, updated_at)
            VALUES
                ('document-1', 'product-1', 'version-1', 'terms.pdf', 'terms',
                 'abc123', '/legacy/terms.pdf', :created_at, :updated_at)
            """
        ),
        timestamps,
    )
    connection.execute(
        text(
            """
            INSERT INTO unassigned_pool
                (id, doc_ref, excerpt, reason, status, created_at, updated_at)
            VALUES
                ('unassigned-1', '/legacy/unknown.pdf', 'unknown', 'no match', 'open',
                 :created_at, :updated_at)
            """
        ),
        timestamps,
    )


def _insert_knowledge_rows(connection: Connection) -> None:
    timestamps = _timestamps()
    connection.execute(
        text(
            """
            INSERT INTO claims
                (id, subject_type, product_version_id, predicate, value_state, status,
                 confidence, extraction_method, schema_version, current_revision,
                 pending_judge, created_at, updated_at)
            VALUES
                ('claim-1', 'product_version', 'version-1', 'benefit', 'present', 'draft',
                 0.9, 'manual', 'v1', 1, 0, :created_at, :updated_at)
            """
        ),
        timestamps,
    )
    connection.execute(
        text(
            """
            INSERT INTO change_sets
                (id, source_kind, external_record_id, source_revision, status, created_by,
                 created_at, updated_at)
            VALUES
                ('changeset-1', 'document', 'record-1', 'r1', 'applied', 'migration-test',
                 :created_at, :updated_at)
            """
        ),
        timestamps,
    )
    connection.execute(
        text(
            """
            INSERT INTO review_items
                (id, review_key, type, subject, allowed_actions, status, risk_level,
                 created_at, updated_at)
            VALUES
                ('review-1', 'review-key', 'claim', '{}', '[]', 'open', 'low',
                 :created_at, :updated_at)
            """
        ),
        timestamps,
    )
    connection.execute(
        text(
            """
            INSERT INTO release_snapshots
                (id, label, published_at, published_by, created_at, updated_at)
            VALUES
                ('snapshot-1', 'release-1', :created_at, 'migration-test',
                 :created_at, :updated_at)
            """
        ),
        timestamps,
    )
    connection.execute(
        text(
            """
            INSERT INTO snapshot_claims
                (id, snapshot_id, claim_id, revision_no, created_at, updated_at)
            VALUES
                ('snapshot-claim-1', 'snapshot-1', 'claim-1', 1,
                 :created_at, :updated_at)
            """
        ),
        timestamps,
    )
    connection.execute(
        text(
            """
            INSERT INTO current_release
                (id, snapshot_id, created_at, updated_at)
            VALUES
                ('current', 'snapshot-1', :created_at, :updated_at)
            """
        ),
        timestamps,
    )


def _insert_space(
    connection: Connection,
    space_id: str,
    *,
    tenant_id: str | None = None,
    raw_kb_id: str | None = None,
    wiki_kb_id: str | None = None,
) -> None:
    timestamps: dict[str, Any] = _timestamps()
    timestamps.update(
        {
            "id": space_id,
            "name": space_id,
            "binding_status": "bound" if tenant_id is not None else "unbound",
            "tenant_id": tenant_id,
            "raw_kb_id": raw_kb_id,
            "wiki_kb_id": wiki_kb_id,
        }
    )
    connection.execute(
        text(
            """
            INSERT INTO knowledge_spaces
                (id, tenant_id, raw_kb_id, wiki_kb_id, name, binding_status,
                 created_at, updated_at)
            VALUES
                (:id, :tenant_id, :raw_kb_id, :wiki_kb_id, :name, :binding_status,
                 :created_at, :updated_at)
            """
        ),
        timestamps,
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


def _space_ids(connection: Connection, table: str) -> set[str]:
    return set(connection.scalars(text(f"SELECT space_id FROM {table}")))  # noqa: S608


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
