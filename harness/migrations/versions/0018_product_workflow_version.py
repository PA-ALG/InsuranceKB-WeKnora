"""Persist the product workflow version without rewriting historical runs.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-15
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def _load_0015_module() -> ModuleType:
    path = Path(__file__).resolve().parent / "0015_job_store_outbox.py"
    spec = importlib.util.spec_from_file_location("migration_0015_for_0018_preflight", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    op.add_column(
        "product_ingestion_runs",
        sa.Column("workflow_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    _load_0015_module()._validate_downgrade_plan_before_ddl(revision)
    op.drop_column("product_ingestion_runs", "workflow_version")
