"""产品域首批表（change 003，docs/insurance-kb/03 §8 产品子集 + unassigned_pool）

Revision ID: 0001
Revises:
Create Date: 2026-07-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "insurance_products",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("product_code", sa.String(64), nullable=False),
        sa.Column("canonical_name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("filing_no", sa.String(128)),
        sa.Column("owner", sa.String(128)),
        sa.Column("meta", sa.JSON()),
        *_timestamps(),
        sa.UniqueConstraint("product_code", name="uq_product_code"),
    )
    op.create_index("ix_products_name", "insurance_products", ["canonical_name"])

    op.create_table(
        "product_aliases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "product_id", sa.String(36), sa.ForeignKey("insurance_products.id"), nullable=False
        ),
        sa.Column("alias", sa.String(255), nullable=False),
        sa.Column("alias_type", sa.String(32), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("product_id", "alias", name="uq_alias_per_product"),
    )
    op.create_index("ix_aliases_alias", "product_aliases", ["alias"])
    op.create_index("ix_aliases_product", "product_aliases", ["product_id"])

    op.create_table(
        "product_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "product_id", sa.String(36), sa.ForeignKey("insurance_products.id"), nullable=False
        ),
        sa.Column("version_label", sa.String(64), nullable=False),
        sa.Column("terms_revision", sa.String(64)),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_to", sa.Date()),
        sa.Column("channels", sa.JSON()),
        sa.Column("regions", sa.JSON()),
        *_timestamps(),
        sa.UniqueConstraint("product_id", "version_label", name="uq_version_per_product"),
    )
    op.create_index("ix_version_effective", "product_versions", ["product_id", "effective_from"])
    op.create_index("ix_versions_product", "product_versions", ["product_id"])

    op.create_table(
        "product_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "product_id", sa.String(36), sa.ForeignKey("insurance_products.id"), nullable=False
        ),
        sa.Column("version_id", sa.String(36), sa.ForeignKey("product_versions.id")),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("doc_type", sa.String(32), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("source_path", sa.String(1024), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("product_id", "sha256", name="uq_doc_sha_per_product"),
    )
    op.create_index("ix_documents_product", "product_documents", ["product_id"])

    op.create_table(
        "unassigned_pool",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("doc_ref", sa.String(1024), nullable=False),
        sa.Column("section_ref", sa.String(255)),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("candidates", sa.JSON()),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_unassigned_status", "unassigned_pool", ["status"])


def downgrade() -> None:
    op.drop_index("ix_unassigned_status", table_name="unassigned_pool")
    op.drop_table("unassigned_pool")
    op.drop_index("ix_documents_product", table_name="product_documents")
    op.drop_table("product_documents")
    op.drop_index("ix_versions_product", table_name="product_versions")
    op.drop_index("ix_version_effective", table_name="product_versions")
    op.drop_table("product_versions")
    op.drop_index("ix_aliases_product", table_name="product_aliases")
    op.drop_index("ix_aliases_alias", table_name="product_aliases")
    op.drop_table("product_aliases")
    op.drop_index("ix_products_name", table_name="insurance_products")
    op.drop_table("insurance_products")
