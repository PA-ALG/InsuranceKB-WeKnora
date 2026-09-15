"""Persist the product workflow version without rewriting historical runs.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_ingestion_runs",
        sa.Column("workflow_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("product_ingestion_runs", "workflow_version")
