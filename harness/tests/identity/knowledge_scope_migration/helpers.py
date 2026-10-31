"""016 T2 enterprise knowledge-space migration: shared Alembic and row-seeding helpers."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, create_engine, inspect, text

HARNESS_ROOT = Path(__file__).resolve().parents[3]
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


def _space_ids(connection: Connection, table: str) -> set[str]:
    return set(connection.scalars(text(f"SELECT space_id FROM {table}")))  # noqa: S608
