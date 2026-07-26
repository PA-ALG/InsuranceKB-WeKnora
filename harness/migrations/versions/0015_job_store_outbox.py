"""P1 Job Store + 事务性 Outbox：wiki_jobs 与 wiki_outbox_events（OpenSpec 035）。

Revision ID: 0015
Revises: 0006
Create Date: 2026-07-27

P1.11：本迁移只创建 `wiki_jobs`/`wiki_outbox_events` 两表及其索引与约束；
`down_revision` 指向合入时 `origin/main` 真实 head（0006，实际链
`0012 → 0006 → 0015`）。编号从台账首个未被旧路线预留的号（0015）占用：
0007–0011 旧预分配与 superseded 0013/0014 一律不复用（22号 §4/24号 §3）。
两表不外键任何遗留域表；Space 绑定由 NOT NULL `space_id` 与存储层
fail-closed scope 校验承担（P1.8）。

downgrade 沿用仓库既有不变量「被拒绝的降级零 DDL」：当目的地越过 0006
的破坏性 preflight 领地时，先复用 0006 模块的同一套只读检查（跳过其
alembic_version 拓扑自检——此刻版本是 0015），任一拒绝发生在本迁移第一条
DDL 之前；历史迁移文件零修改。
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic import context, op

revision = "0015"
down_revision = "0006"
branch_labels = None
depends_on = None

# 0006 的 downgrade 会在这些目的地执行（含 base=None）；届时其 preflight
# 必须在本迁移 DDL 之前先行判定。
_DESTINATIONS_CROSSING_0006 = {"0001", "0002", "0003", "0004", "0005", "0012"}

_JOB_STATES = (
    "'queued', 'leased', 'running', 'succeeded', "
    "'retry_wait', 'awaiting_human', 'blocked', 'dead_letter'"
)
_ERROR_CLASSES = "'retryable', 'non_retryable', 'capacity_blocked', 'human_required'"


def upgrade() -> None:
    op.create_table(
        "wiki_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("space_id", sa.String(36), nullable=False),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("lease_generation", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(128), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_class", sa.String(32), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "space_id", "job_type", "idempotency_key", name="uq_wiki_jobs_idempotency"
        ),
        sa.CheckConstraint(f"state IN ({_JOB_STATES})", name="ck_wiki_jobs_state"),
        sa.CheckConstraint("attempt >= 0", name="ck_wiki_jobs_attempt"),
        sa.CheckConstraint("lease_generation >= 0", name="ck_wiki_jobs_generation"),
        sa.CheckConstraint(
            f"error_class IS NULL OR error_class IN ({_ERROR_CLASSES})",
            name="ck_wiki_jobs_error_class",
        ),
        sa.CheckConstraint(
            "state NOT IN ('leased', 'running') "
            "OR (worker_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_wiki_jobs_lease_shape",
        ),
    )
    op.create_index("ix_wiki_jobs_claim", "wiki_jobs", ["space_id", "state", "available_at"])
    op.create_index("ix_wiki_jobs_reclaim", "wiki_jobs", ["state", "lease_expires_at"])

    op.create_table(
        "wiki_outbox_events",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("space_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("event_id", name="uq_wiki_outbox_events_event_id"),
    )
    op.create_index(
        "ix_wiki_outbox_events_undispatched",
        "wiki_outbox_events",
        ["id"],
        sqlite_where=sa.text("dispatched_at IS NULL"),
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )
    op.create_index("ix_wiki_outbox_events_space", "wiki_outbox_events", ["space_id", "id"])


def _load_0006_module() -> ModuleType:
    path = Path(__file__).resolve().parent / "0006_source_lifecycle_ordering.py"
    spec = importlib.util.spec_from_file_location("migration_0006_for_0015_preflight", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _destination_crosses_0006() -> bool:
    destination = context.get_revision_argument()
    if destination is None:
        return True
    if isinstance(destination, tuple):
        return any(revision_id in _DESTINATIONS_CROSSING_0006 for revision_id in destination)
    return destination in _DESTINATIONS_CROSSING_0006


def _validate_downgrade_before_ddl() -> None:
    """在本迁移任何 DDL 之前重放 0006 聚合 preflight（除拓扑自检）。"""
    if not _destination_crosses_0006():
        return
    module = _load_0006_module()
    connection = op.get_bind()
    unsafe_lifecycle = {
        name: count for name, count in module._lifecycle_state_counts().items() if count
    }
    if unsafe_lifecycle:
        raise RuntimeError(
            "0015 downgrade refused before DDL: durable source lifecycle data exists "
            f"{unsafe_lifecycle}"
        )
    observed, _tombstones = module._observed_historical_revisions(connection)
    if observed:
        raise RuntimeError(
            "0015 downgrade refused before DDL: source-aware provenance cannot be "
            f"preserved by 0012 ({len(observed)} scoped source(s))"
        )
    if module._destination_crosses(module._PRE_SCOPE_REVISIONS):
        module._validate_enterprise_scope_downgrade()
    if module._destination_crosses(module._PRE_RELEASE_REVISIONS):
        unsafe_release = {
            name: count for name, count in module._release_state_counts().items() if count
        }
        if unsafe_release:
            raise RuntimeError(
                f"0005 downgrade refused: release read-model data exists {unsafe_release}"
            )
    if module._destination_crosses(module._PRE_FLYWHEEL_REVISIONS):
        unsafe_flywheel = {
            name: count for name, count in module._flywheel_state_counts().items() if count
        }
        if unsafe_flywheel:
            raise RuntimeError(
                f"0012 downgrade refused: durable flywheel data exists {unsafe_flywheel}"
            )


def downgrade() -> None:
    _validate_downgrade_before_ddl()
    op.drop_index("ix_wiki_outbox_events_space", table_name="wiki_outbox_events")
    op.drop_index("ix_wiki_outbox_events_undispatched", table_name="wiki_outbox_events")
    op.drop_table("wiki_outbox_events")
    op.drop_index("ix_wiki_jobs_reclaim", table_name="wiki_jobs")
    op.drop_index("ix_wiki_jobs_claim", table_name="wiki_jobs")
    op.drop_table("wiki_jobs")
