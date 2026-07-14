"""Enterprise knowledge spaces and scoped aggregate roots (change 016).

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-13
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from alembic.util.exc import CommandError

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

LEGACY_SPACE_ID = "legacy-default"
SCOPED_TABLES = (
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
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
}


def _create_knowledge_spaces() -> None:
    op.create_table(
        "knowledge_spaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(255)),
        sa.Column("raw_kb_id", sa.String(255)),
        sa.Column("wiki_kb_id", sa.String(255)),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("binding_status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(binding_status = 'unbound' "
            "AND tenant_id IS NULL AND raw_kb_id IS NULL AND wiki_kb_id IS NULL) "
            "OR (binding_status = 'bound' "
            "AND tenant_id IS NOT NULL AND raw_kb_id IS NOT NULL AND wiki_kb_id IS NOT NULL)",
            name="ck_knowledge_spaces_binding_shape",
        ),
        sa.UniqueConstraint(
            "tenant_id", "raw_kb_id", name="uq_knowledge_spaces_tenant_raw_kb"
        ),
        sa.UniqueConstraint(
            "tenant_id", "wiki_kb_id", name="uq_knowledge_spaces_tenant_wiki_kb"
        ),
    )


def _add_nullable_space_columns() -> None:
    for table in SCOPED_TABLES:
        with op.batch_alter_table(table, naming_convention=NAMING_CONVENTION) as batch:
            batch.add_column(sa.Column("space_id", sa.String(36), nullable=True))


def _has_historical_rows() -> bool:
    connection = op.get_bind()
    return any(
        connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None
        for table in SCOPED_TABLES
    )


def _backfill_legacy_space() -> None:
    if not _has_historical_rows():
        return

    now = datetime.now(UTC)
    spaces = sa.table(
        "knowledge_spaces",
        sa.column("id", sa.String(36)),
        sa.column("tenant_id", sa.String(255)),
        sa.column("raw_kb_id", sa.String(255)),
        sa.column("wiki_kb_id", sa.String(255)),
        sa.column("name", sa.String(255)),
        sa.column("binding_status", sa.String(16)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        spaces,
        [
            {
                "id": LEGACY_SPACE_ID,
                "tenant_id": None,
                "raw_kb_id": None,
                "wiki_kb_id": None,
                "name": "Legacy Default",
                "binding_status": "unbound",
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    for table in SCOPED_TABLES:
        op.execute(
            sa.text(f"UPDATE {table} SET space_id = :space_id WHERE space_id IS NULL").bindparams(
                space_id=LEGACY_SPACE_ID
            )
        )


def _scope_product_tables() -> None:
    with op.batch_alter_table(
        "insurance_products", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.alter_column("space_id", existing_type=sa.String(36), nullable=False)
        batch.drop_constraint("uq_product_code", type_="unique")
        batch.create_unique_constraint("uq_product_code", ["space_id", "product_code"])
        batch.create_unique_constraint(
            "uq_insurance_products_space_id", ["space_id", "id"]
        )
        batch.create_foreign_key(
            "fk_insurance_products_space",
            "knowledge_spaces",
            ["space_id"],
            ["id"],
        )

    with op.batch_alter_table(
        "product_versions", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.alter_column("space_id", existing_type=sa.String(36), nullable=False)
        batch.drop_constraint("uq_version_per_product", type_="unique")
        batch.create_unique_constraint(
            "uq_version_per_product", ["space_id", "product_id", "version_label"]
        )
        batch.create_unique_constraint("uq_product_versions_space_id", ["space_id", "id"])
        batch.create_foreign_key(
            "fk_product_versions_space", "knowledge_spaces", ["space_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_product_versions_space_product",
            "insurance_products",
            ["space_id", "product_id"],
            ["space_id", "id"],
        )

    with op.batch_alter_table(
        "product_documents", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.alter_column("space_id", existing_type=sa.String(36), nullable=False)
        batch.drop_constraint("uq_doc_sha_per_product", type_="unique")
        batch.create_unique_constraint(
            "uq_doc_sha_per_product", ["space_id", "product_id", "sha256"]
        )
        batch.create_foreign_key(
            "fk_product_documents_space", "knowledge_spaces", ["space_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_product_documents_space_product",
            "insurance_products",
            ["space_id", "product_id"],
            ["space_id", "id"],
        )
        batch.create_foreign_key(
            "fk_product_documents_space_version",
            "product_versions",
            ["space_id", "version_id"],
            ["space_id", "id"],
        )

    with op.batch_alter_table(
        "unassigned_pool", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.alter_column("space_id", existing_type=sa.String(36), nullable=False)
        batch.create_foreign_key(
            "fk_unassigned_pool_space", "knowledge_spaces", ["space_id"], ["id"]
        )


def _scope_knowledge_tables() -> None:
    op.drop_index("uq_claims_published", table_name="claims")
    with op.batch_alter_table("claims", naming_convention=NAMING_CONVENTION) as batch:
        batch.alter_column("space_id", existing_type=sa.String(36), nullable=False)
        batch.create_unique_constraint("uq_claims_space_id", ["space_id", "id"])
        batch.create_foreign_key(
            "fk_claims_space", "knowledge_spaces", ["space_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_claims_space_product_version",
            "product_versions",
            ["space_id", "product_version_id"],
            ["space_id", "id"],
        )
        batch.create_foreign_key(
            "fk_claims_space_superseded_by",
            "claims",
            ["space_id", "superseded_by"],
            ["space_id", "id"],
        )
    op.create_index(
        "uq_claims_published",
        "claims",
        ["space_id", "product_version_id", "concept_id", "predicate", "effective_from"],
        unique=True,
        sqlite_where=sa.text("status = 'published'"),
        postgresql_where=sa.text("status = 'published'"),
    )

    with op.batch_alter_table("change_sets", naming_convention=NAMING_CONVENTION) as batch:
        batch.alter_column("space_id", existing_type=sa.String(36), nullable=False)
        batch.drop_constraint("uq_changeset_source", type_="unique")
        batch.create_unique_constraint(
            "uq_changeset_source",
            ["space_id", "source_kind", "external_record_id", "source_revision"],
        )
        batch.create_foreign_key(
            "fk_change_sets_space", "knowledge_spaces", ["space_id"], ["id"]
        )

    with op.batch_alter_table("review_items", naming_convention=NAMING_CONVENTION) as batch:
        batch.alter_column("space_id", existing_type=sa.String(36), nullable=False)
        batch.drop_constraint("uq_review_key", type_="unique")
        batch.create_unique_constraint("uq_review_key", ["space_id", "review_key"])
        batch.create_foreign_key(
            "fk_review_items_space", "knowledge_spaces", ["space_id"], ["id"]
        )

    with op.batch_alter_table(
        "release_snapshots", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.alter_column("space_id", existing_type=sa.String(36), nullable=False)
        batch.drop_constraint("uq_snapshot_label", type_="unique")
        batch.create_unique_constraint("uq_snapshot_label", ["space_id", "label"])
        batch.create_unique_constraint("uq_release_snapshots_space_id", ["space_id", "id"])
        batch.create_foreign_key(
            "fk_release_snapshots_space", "knowledge_spaces", ["space_id"], ["id"]
        )

    with op.batch_alter_table(
        "snapshot_claims", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.alter_column("space_id", existing_type=sa.String(36), nullable=False)
        batch.drop_constraint("uq_snapshot_claim", type_="unique")
        batch.create_unique_constraint(
            "uq_snapshot_claim", ["space_id", "snapshot_id", "claim_id"]
        )
        batch.create_foreign_key(
            "fk_snapshot_claims_space", "knowledge_spaces", ["space_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_snapshot_claims_space_snapshot",
            "release_snapshots",
            ["space_id", "snapshot_id"],
            ["space_id", "id"],
        )
        batch.create_foreign_key(
            "fk_snapshot_claims_space_claim",
            "claims",
            ["space_id", "claim_id"],
            ["space_id", "id"],
        )

    primary_key_name = _primary_key_name("current_release")
    with op.batch_alter_table(
        "current_release", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.alter_column("space_id", existing_type=sa.String(36), nullable=False)
        batch.drop_constraint(primary_key_name, type_="primary")
        batch.create_primary_key("pk_current_release", ["space_id", "id"])
        batch.create_unique_constraint("uq_current_release_space", ["space_id"])
        batch.create_foreign_key(
            "fk_current_release_space", "knowledge_spaces", ["space_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_current_release_space_snapshot",
            "release_snapshots",
            ["space_id", "snapshot_id"],
            ["space_id", "id"],
        )


def _primary_key_name(table: str) -> str:
    name = sa.inspect(op.get_bind()).get_pk_constraint(table).get("name")
    return str(name) if name else f"pk_{table}"


def upgrade() -> None:
    _create_knowledge_spaces()
    _add_nullable_space_columns()
    _backfill_legacy_space()
    _scope_product_tables()
    _scope_knowledge_tables()


def _downgrade_conflicts() -> list[str]:
    connection = op.get_bind()
    checks = (
        (
            "insurance_products.product_code",
            ("product_code",),
            "SELECT product_code, count(*) AS conflict_count FROM insurance_products "
            "GROUP BY product_code HAVING count(*) > 1",
        ),
        (
            "product_versions(product_id, version_label)",
            ("product_id", "version_label"),
            "SELECT product_id, version_label, count(*) AS conflict_count "
            "FROM product_versions GROUP BY product_id, version_label HAVING count(*) > 1",
        ),
        (
            "product_documents(product_id, sha256)",
            ("product_id", "sha256"),
            "SELECT product_id, sha256, count(*) AS conflict_count FROM product_documents "
            "GROUP BY product_id, sha256 HAVING count(*) > 1",
        ),
        (
            "claims published key",
            ("product_version_id", "concept_id", "predicate", "effective_from"),
            "SELECT product_version_id, concept_id, predicate, effective_from, "
            "count(*) AS conflict_count FROM claims WHERE status = 'published' "
            "AND product_version_id IS NOT NULL AND concept_id IS NOT NULL "
            "AND predicate IS NOT NULL AND effective_from IS NOT NULL "
            "GROUP BY product_version_id, concept_id, predicate, effective_from "
            "HAVING count(*) > 1",
        ),
        (
            "change_sets(source_kind, external_record_id, source_revision)",
            ("source_kind", "external_record_id", "source_revision"),
            "SELECT source_kind, external_record_id, source_revision, "
            "count(*) AS conflict_count FROM change_sets "
            "WHERE external_record_id IS NOT NULL AND source_revision IS NOT NULL "
            "GROUP BY source_kind, external_record_id, source_revision HAVING count(*) > 1",
        ),
        (
            "review_items.review_key",
            ("review_key",),
            "SELECT review_key, count(*) AS conflict_count FROM review_items "
            "GROUP BY review_key HAVING count(*) > 1",
        ),
        (
            "release_snapshots.label",
            ("label",),
            "SELECT label, count(*) AS conflict_count FROM release_snapshots "
            "GROUP BY label HAVING count(*) > 1",
        ),
        (
            "snapshot_claims(snapshot_id, claim_id)",
            ("snapshot_id", "claim_id"),
            "SELECT snapshot_id, claim_id, count(*) AS conflict_count FROM snapshot_claims "
            "GROUP BY snapshot_id, claim_id HAVING count(*) > 1",
        ),
    )
    conflicts = []
    for label, key_columns, query in checks:
        rows = connection.execute(sa.text(query)).mappings()
        conflicts.extend(
            f"{label}({', '.join(f'{column}={row[column]!r}' for column in key_columns)}, "
            f"count={row['conflict_count']})"
            for row in rows
        )

    pointers = connection.execute(
        sa.text("SELECT id, space_id FROM current_release ORDER BY id, space_id")
    ).all()
    if len(pointers) > 1:
        conflicts.append(f"current_release singleton(rows={pointers!r}, count={len(pointers)})")
    return conflicts


def _validate_downgrade() -> None:
    connection = op.get_bind()
    space_ids = list(
        connection.scalars(sa.text("SELECT id FROM knowledge_spaces ORDER BY id"))
    )
    if space_ids != [LEGACY_SPACE_ID]:
        raise CommandError(
            "cannot downgrade 0003 before DDL: expected exactly one knowledge space "
            f"named {LEGACY_SPACE_ID!r}; found {space_ids!r}"
        )
    conflicts = _downgrade_conflicts()
    if conflicts:
        raise CommandError(
            "cannot downgrade 0003 before DDL: global business-key conflicts: "
            + "; ".join(conflicts)
        )


def _un_scope_knowledge_tables() -> None:
    with op.batch_alter_table(
        "snapshot_claims", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.drop_constraint("fk_snapshot_claims_space_snapshot", type_="foreignkey")
        batch.drop_constraint("fk_snapshot_claims_space_claim", type_="foreignkey")
        batch.drop_constraint("fk_snapshot_claims_space", type_="foreignkey")
        batch.drop_constraint("uq_snapshot_claim", type_="unique")
        batch.create_unique_constraint("uq_snapshot_claim", ["snapshot_id", "claim_id"])
        batch.drop_column("space_id")

    with op.batch_alter_table(
        "current_release", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.drop_constraint("fk_current_release_space_snapshot", type_="foreignkey")
        batch.drop_constraint("fk_current_release_space", type_="foreignkey")
        batch.drop_constraint("uq_current_release_space", type_="unique")
        batch.drop_constraint(_primary_key_name("current_release"), type_="primary")
        batch.create_primary_key("pk_current_release", ["id"])
        batch.drop_column("space_id")

    with op.batch_alter_table(
        "release_snapshots", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.drop_constraint("fk_release_snapshots_space", type_="foreignkey")
        batch.drop_constraint("uq_release_snapshots_space_id", type_="unique")
        batch.drop_constraint("uq_snapshot_label", type_="unique")
        batch.create_unique_constraint("uq_snapshot_label", ["label"])
        batch.drop_column("space_id")

    with op.batch_alter_table("review_items", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("fk_review_items_space", type_="foreignkey")
        batch.drop_constraint("uq_review_key", type_="unique")
        batch.create_unique_constraint("uq_review_key", ["review_key"])
        batch.drop_column("space_id")

    with op.batch_alter_table("change_sets", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("fk_change_sets_space", type_="foreignkey")
        batch.drop_constraint("uq_changeset_source", type_="unique")
        batch.create_unique_constraint(
            "uq_changeset_source", ["source_kind", "external_record_id", "source_revision"]
        )
        batch.drop_column("space_id")

    op.drop_index("uq_claims_published", table_name="claims")
    with op.batch_alter_table("claims", naming_convention=NAMING_CONVENTION) as batch:
        batch.drop_constraint("fk_claims_space_superseded_by", type_="foreignkey")
        batch.drop_constraint("fk_claims_space_product_version", type_="foreignkey")
        batch.drop_constraint("fk_claims_space", type_="foreignkey")
        batch.drop_constraint("uq_claims_space_id", type_="unique")
        batch.drop_column("space_id")
    op.create_index(
        "uq_claims_published",
        "claims",
        ["product_version_id", "concept_id", "predicate", "effective_from"],
        unique=True,
        sqlite_where=sa.text("status = 'published'"),
        postgresql_where=sa.text("status = 'published'"),
    )


def _un_scope_product_tables() -> None:
    with op.batch_alter_table(
        "product_documents", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.drop_constraint("fk_product_documents_space_version", type_="foreignkey")
        batch.drop_constraint("fk_product_documents_space_product", type_="foreignkey")
        batch.drop_constraint("fk_product_documents_space", type_="foreignkey")
        batch.drop_constraint("uq_doc_sha_per_product", type_="unique")
        batch.create_unique_constraint("uq_doc_sha_per_product", ["product_id", "sha256"])
        batch.drop_column("space_id")

    with op.batch_alter_table(
        "product_versions", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.drop_constraint("fk_product_versions_space_product", type_="foreignkey")
        batch.drop_constraint("fk_product_versions_space", type_="foreignkey")
        batch.drop_constraint("uq_product_versions_space_id", type_="unique")
        batch.drop_constraint("uq_version_per_product", type_="unique")
        batch.create_unique_constraint("uq_version_per_product", ["product_id", "version_label"])
        batch.drop_column("space_id")

    with op.batch_alter_table(
        "unassigned_pool", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.drop_constraint("fk_unassigned_pool_space", type_="foreignkey")
        batch.drop_column("space_id")

    with op.batch_alter_table(
        "insurance_products", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.drop_constraint("fk_insurance_products_space", type_="foreignkey")
        batch.drop_constraint("uq_insurance_products_space_id", type_="unique")
        batch.drop_constraint("uq_product_code", type_="unique")
        batch.create_unique_constraint("uq_product_code", ["product_code"])
        batch.drop_column("space_id")


def downgrade() -> None:
    _validate_downgrade()
    _un_scope_knowledge_tables()
    _un_scope_product_tables()
    op.drop_table("knowledge_spaces")
