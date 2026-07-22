"""Exact release manifests and append-only named-human approval (OpenSpec 029).

Revision ID: 0013
Revises: 0006
Create Date: 2026-07-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0006"
branch_labels = None
depends_on = None

SQLITE_CREATE_GUARDS = (
    """CREATE TRIGGER trg_release_manifests_update_guard_029
    BEFORE UPDATE ON release_manifests FOR EACH ROW
    BEGIN SELECT RAISE(ABORT, 'release manifests are immutable'); END""",
    """CREATE TRIGGER trg_release_manifests_delete_guard_029
    BEFORE DELETE ON release_manifests FOR EACH ROW
    BEGIN SELECT RAISE(ABORT, 'release manifests are immutable'); END""",
    """CREATE TRIGGER trg_release_approvals_update_guard_029
    BEFORE UPDATE ON release_approvals FOR EACH ROW
    BEGIN SELECT RAISE(ABORT, 'release approvals are append-only'); END""",
    """CREATE TRIGGER trg_release_approvals_delete_guard_029
    BEFORE DELETE ON release_approvals FOR EACH ROW
    BEGIN SELECT RAISE(ABORT, 'release approvals are append-only'); END""",
    """CREATE TRIGGER trg_release_activation_audits_update_guard_029
    BEFORE UPDATE ON release_activation_audits FOR EACH ROW
    BEGIN SELECT RAISE(ABORT, 'release activation audits are append-only'); END""",
    """CREATE TRIGGER trg_release_activation_audits_delete_guard_029
    BEFORE DELETE ON release_activation_audits FOR EACH ROW
    BEGIN SELECT RAISE(ABORT, 'release activation audits are append-only'); END""",
    """CREATE TRIGGER trg_release_alerts_update_guard_029
    BEFORE UPDATE ON release_alerts FOR EACH ROW
    BEGIN SELECT RAISE(ABORT, 'release alerts are append-only'); END""",
    """CREATE TRIGGER trg_release_alerts_delete_guard_029
    BEFORE DELETE ON release_alerts FOR EACH ROW
    BEGIN SELECT RAISE(ABORT, 'release alerts are append-only'); END""",
)
SQLITE_DROP_GUARDS = (
    "DROP TRIGGER IF EXISTS trg_release_alerts_delete_guard_029",
    "DROP TRIGGER IF EXISTS trg_release_alerts_update_guard_029",
    "DROP TRIGGER IF EXISTS trg_release_activation_audits_delete_guard_029",
    "DROP TRIGGER IF EXISTS trg_release_activation_audits_update_guard_029",
    "DROP TRIGGER IF EXISTS trg_release_approvals_delete_guard_029",
    "DROP TRIGGER IF EXISTS trg_release_approvals_update_guard_029",
    "DROP TRIGGER IF EXISTS trg_release_manifests_delete_guard_029",
    "DROP TRIGGER IF EXISTS trg_release_manifests_update_guard_029",
)
POSTGRESQL_CREATE_GUARDS = (
    """CREATE FUNCTION guard_release_manifests_immutable_029() RETURNS trigger
    LANGUAGE plpgsql AS $guard$ BEGIN
    RAISE EXCEPTION 'release manifests are immutable' USING ERRCODE = '23514';
    END; $guard$""",
    """CREATE TRIGGER trg_release_manifests_update_guard_029
    BEFORE UPDATE ON release_manifests FOR EACH ROW
    EXECUTE FUNCTION guard_release_manifests_immutable_029()""",
    """CREATE TRIGGER trg_release_manifests_delete_guard_029
    BEFORE DELETE ON release_manifests FOR EACH ROW
    EXECUTE FUNCTION guard_release_manifests_immutable_029()""",
    """CREATE FUNCTION guard_release_approvals_append_only_029() RETURNS trigger
    LANGUAGE plpgsql AS $guard$ BEGIN
    RAISE EXCEPTION 'release approvals are append-only' USING ERRCODE = '23514';
    END; $guard$""",
    """CREATE TRIGGER trg_release_approvals_update_guard_029
    BEFORE UPDATE ON release_approvals FOR EACH ROW
    EXECUTE FUNCTION guard_release_approvals_append_only_029()""",
    """CREATE TRIGGER trg_release_approvals_delete_guard_029
    BEFORE DELETE ON release_approvals FOR EACH ROW
    EXECUTE FUNCTION guard_release_approvals_append_only_029()""",
    """CREATE FUNCTION guard_release_activation_audits_append_only_029()
    RETURNS trigger LANGUAGE plpgsql AS $guard$ BEGIN
    RAISE EXCEPTION 'release activation audits are append-only'
    USING ERRCODE = '23514'; END; $guard$""",
    """CREATE TRIGGER trg_release_activation_audits_update_guard_029
    BEFORE UPDATE ON release_activation_audits FOR EACH ROW
    EXECUTE FUNCTION guard_release_activation_audits_append_only_029()""",
    """CREATE TRIGGER trg_release_activation_audits_delete_guard_029
    BEFORE DELETE ON release_activation_audits FOR EACH ROW
    EXECUTE FUNCTION guard_release_activation_audits_append_only_029()""",
    """CREATE FUNCTION guard_release_alerts_append_only_029()
    RETURNS trigger LANGUAGE plpgsql AS $guard$ BEGIN
    RAISE EXCEPTION 'release alerts are append-only'
    USING ERRCODE = '23514'; END; $guard$""",
    """CREATE TRIGGER trg_release_alerts_update_guard_029
    BEFORE UPDATE ON release_alerts FOR EACH ROW
    EXECUTE FUNCTION guard_release_alerts_append_only_029()""",
    """CREATE TRIGGER trg_release_alerts_delete_guard_029
    BEFORE DELETE ON release_alerts FOR EACH ROW
    EXECUTE FUNCTION guard_release_alerts_append_only_029()""",
)
POSTGRESQL_DROP_GUARDS = (
    "DROP TRIGGER IF EXISTS trg_release_alerts_delete_guard_029 ON release_alerts",
    "DROP TRIGGER IF EXISTS trg_release_alerts_update_guard_029 ON release_alerts",
    "DROP TRIGGER IF EXISTS trg_release_activation_audits_delete_guard_029 "
    "ON release_activation_audits",
    "DROP TRIGGER IF EXISTS trg_release_activation_audits_update_guard_029 "
    "ON release_activation_audits",
    "DROP TRIGGER IF EXISTS trg_release_approvals_delete_guard_029 ON release_approvals",
    "DROP TRIGGER IF EXISTS trg_release_approvals_update_guard_029 ON release_approvals",
    "DROP TRIGGER IF EXISTS trg_release_manifests_delete_guard_029 ON release_manifests",
    "DROP TRIGGER IF EXISTS trg_release_manifests_update_guard_029 ON release_manifests",
    "DROP FUNCTION IF EXISTS guard_release_approvals_append_only_029()",
    "DROP FUNCTION IF EXISTS guard_release_alerts_append_only_029()",
    "DROP FUNCTION IF EXISTS guard_release_activation_audits_append_only_029()",
    "DROP FUNCTION IF EXISTS guard_release_manifests_immutable_029()",
)


def _guard_statements(*, create: bool) -> Sequence[str]:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        return SQLITE_CREATE_GUARDS if create else SQLITE_DROP_GUARDS
    if dialect == "postgresql":
        return POSTGRESQL_CREATE_GUARDS if create else POSTGRESQL_DROP_GUARDS
    raise RuntimeError(f"unsupported release authority dialect: {dialect}")


def _create_guards() -> None:
    for statement in _guard_statements(create=True):
        op.execute(sa.text(statement))


def _drop_guards() -> None:
    for statement in _guard_statements(create=False):
        op.execute(sa.text(statement))


def upgrade() -> None:
    op.create_table(
        "release_manifests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "space_id",
            sa.String(36),
            sa.ForeignKey("knowledge_spaces.id", name="fk_release_manifests_space"),
            nullable=False,
        ),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "space_id", "snapshot_id", name="uq_release_manifests_space_snapshot"
        ),
        sa.UniqueConstraint(
            "space_id", "manifest_hash", name="uq_release_manifests_space_hash"
        ),
        sa.UniqueConstraint(
            "space_id",
            "snapshot_id",
            "manifest_hash",
            name="uq_release_manifests_exact",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "snapshot_id"],
            ["release_snapshots.space_id", "release_snapshots.id"],
            name="fk_release_manifests_space_snapshot",
        ),
        sa.CheckConstraint(
            "length(manifest_hash) = 64 AND manifest_hash = lower(manifest_hash)",
            name="ck_release_manifests_hash",
        ),
    )
    op.create_table(
        "release_approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "space_id",
            sa.String(36),
            sa.ForeignKey("knowledge_spaces.id", name="fk_release_approvals_space"),
            nullable=False,
        ),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("authorization_receipt", sa.String(512), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "space_id", "manifest_hash", name="uq_release_approvals_space_manifest"
        ),
        sa.UniqueConstraint("space_id", "id", name="uq_release_approvals_space_id"),
        sa.UniqueConstraint(
            "space_id",
            "snapshot_id",
            "manifest_hash",
            "id",
            name="uq_release_approvals_exact_id",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "snapshot_id", "manifest_hash"],
            [
                "release_manifests.space_id",
                "release_manifests.snapshot_id",
                "release_manifests.manifest_hash",
            ],
            name="fk_release_approvals_exact_manifest",
        ),
        sa.CheckConstraint(
            "actor_type IN ('human', 'principal')",
            name="ck_release_approvals_actor_type",
        ),
        sa.CheckConstraint(
            "role = 'release_approver'",
            name="ck_release_approvals_role",
        ),
        sa.CheckConstraint(
            "length(trim(actor)) > 0 AND length(trim(authorization_receipt)) > 0 "
            "AND length(trim(reason)) > 0",
            name="ck_release_approvals_named_attestation",
        ),
    )
    op.create_table(
        "release_activation_audits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "space_id",
            sa.String(36),
            sa.ForeignKey(
                "knowledge_spaces.id", name="fk_release_activation_audits_space"
            ),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("from_snapshot_id", sa.String(36), nullable=True),
        sa.Column("target_snapshot_id", sa.String(36), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("approval_id", sa.String(36), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["space_id", "from_snapshot_id"],
            ["release_snapshots.space_id", "release_snapshots.id"],
            name="fk_release_activation_audits_from_snapshot",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "target_snapshot_id", "manifest_hash"],
            [
                "release_manifests.space_id",
                "release_manifests.snapshot_id",
                "release_manifests.manifest_hash",
            ],
            name="fk_release_activation_audits_exact_manifest",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "target_snapshot_id", "manifest_hash", "approval_id"],
            [
                "release_approvals.space_id",
                "release_approvals.snapshot_id",
                "release_approvals.manifest_hash",
                "release_approvals.id",
            ],
            name="fk_release_activation_audits_exact_approval",
        ),
        sa.CheckConstraint(
            "kind IN ('promote', 'rollback')",
            name="ck_release_activation_audits_kind",
        ),
        sa.CheckConstraint(
            "length(trim(actor)) > 0 AND length(trim(reason)) > 0",
            name="ck_release_activation_audits_attestation",
        ),
    )
    op.create_table(
        "release_alerts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "space_id",
            sa.String(36),
            sa.ForeignKey("knowledge_spaces.id", name="fk_release_alerts_space"),
            nullable=False,
        ),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("safe_details", sa.JSON(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["space_id", "snapshot_id", "manifest_hash"],
            [
                "release_manifests.space_id",
                "release_manifests.snapshot_id",
                "release_manifests.manifest_hash",
            ],
            name="fk_release_alerts_exact_manifest",
        ),
        sa.CheckConstraint(
            "code = 'manifest_tamper'",
            name="ck_release_alerts_code",
        ),
        sa.CheckConstraint(
            "severity = 'critical'",
            name="ck_release_alerts_severity",
        ),
    )
    _create_guards()


def _validate_empty_before_downgrade() -> None:
    connection = op.get_bind()
    counts = {
        table: int(connection.scalar(sa.text(f"SELECT count(*) FROM {table}")) or 0)
        for table in (
            "release_manifests",
            "release_approvals",
            "release_activation_audits",
            "release_alerts",
        )
    }
    durable = {table: count for table, count in counts.items() if count}
    if durable:
        raise RuntimeError(
            "0013 downgrade refused before DDL: durable release authority data exists "
            f"{durable}"
        )


def downgrade() -> None:
    _validate_empty_before_downgrade()
    _drop_guards()
    op.drop_table("release_alerts")
    op.drop_table("release_activation_audits")
    op.drop_table("release_approvals")
    op.drop_table("release_manifests")
