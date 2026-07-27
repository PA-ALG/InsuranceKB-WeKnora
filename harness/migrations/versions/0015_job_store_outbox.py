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

downgrade 沿用仓库既有不变量「被拒绝的降级零 DDL」：先做本迁移自有数据
preflight——存在**非终态任务行或未投递 outbox 行**即拒绝（review I9）；当
目的地（含相对参数，review M13：先经 ScriptDirectory 解析再判定）越过
0006 的破坏性 preflight 领地时，再复用 0006 模块的同一套只读检查（跳过其
alembic_version 拓扑自检——此刻版本是 0015）。任一拒绝发生在本迁移第一条
DDL 之前；历史迁移文件零修改。
"""

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic import context, op
from alembic.script import ScriptDirectory

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
_LIVE_JOB_STATES = "'queued', 'leased', 'running', 'retry_wait', 'awaiting_human'"
_RELATIVE_DESTINATION = re.compile(r"^-\d+$")


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
        # P1.7 判据不可变（D-2026-07-27-16）：首次 Decision 唤醒成功时写入，
        # 此后不再修改。duplicate/not_awaiting 的判定读它，而不是可被回收与
        # 失败上报覆写的 `error_class`。
        sa.Column("human_decision_resumed_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index(
        "ix_wiki_jobs_claim_order", "wiki_jobs", ["space_id", "state", "enqueued_at", "id"]
    )
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
        sa.Column(
            "dispatch_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        # 持久退避（P1.6 投递可恢复性合同，D-2026-07-27-16）：扫描条件为
        # `dispatched_at IS NULL AND next_dispatch_at <= now`。失败只推迟
        # 不出局，取代原先"失败 N 次即永久移出扫描窗口"的硬上限。
        sa.Column("next_dispatch_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "space_id", "event_id", name="uq_wiki_outbox_events_space_event"
        ),
        sa.CheckConstraint(
            "dispatch_attempts >= 0", name="ck_wiki_outbox_events_attempts"
        ),
    )
    op.create_index(
        "ix_wiki_outbox_events_undispatched",
        "wiki_outbox_events",
        ["next_dispatch_at", "id"],
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


def _resolved_destinations() -> tuple[str, ...] | None:
    """把降级目的地解析为具体 revision id；base/未知形式按「越过」处理。

    相对形式（`-N`）沿 down_revision 链自 0015 逐步解析（review M13）；
    解析失败时保守返回 None（视为 base，触发 preflight，宁拒绝不半降）。
    """
    destination = context.get_revision_argument()
    if destination is None:
        return None
    raw_values = destination if isinstance(destination, tuple) else (destination,)
    resolved: list[str] = []
    for raw in raw_values:
        value = str(raw)
        if value in {"base", ""}:
            return None
        if _RELATIVE_DESTINATION.fullmatch(value):
            steps = int(value[1:])
            current: str | None = revision
            script = ScriptDirectory.from_config(context.config)
            for _ in range(steps):
                if current is None:
                    return None
                node = script.get_revision(current)
                down = node.down_revision
                if isinstance(down, (tuple, list)):
                    down = down[0] if down else None
                current = down
            if current is None:
                return None
            resolved.append(current)
            continue
        if not re.fullmatch(r"[0-9a-zA-Z_]+", value):
            return None  # 未知寻址形式：保守按 base 处理
        resolved.append(value)
    return tuple(resolved)


def _destination_crosses_0006() -> bool:
    destinations = _resolved_destinations()
    if destinations is None:
        return True
    return any(revision_id in _DESTINATIONS_CROSSING_0006 for revision_id in destinations)


def _validate_own_rows_before_ddl() -> None:
    """本迁移自有数据 preflight：活跃任务、未投递事件或 DLQ 取证存在即拒绝。

    `dead_letter` 行同样受保护（D-2026-07-27-16）：P1.4 明确要求 dead_letter
    保留 space_id、幂等键、attempt、错误分类与最后错误摘要——DLQ 正是降级时
    最不该无声消失的东西。`succeeded` 保持可丢弃，否则任何跑过任务的库都
    无法降级。
    """
    connection = op.get_bind()
    live_jobs = int(
        connection.scalar(
            sa.text(f"SELECT count(*) FROM wiki_jobs WHERE state IN ({_LIVE_JOB_STATES})")
        )
        or 0
    )
    dead_letter_jobs = int(
        connection.scalar(
            sa.text("SELECT count(*) FROM wiki_jobs WHERE state = 'dead_letter'")
        )
        or 0
    )
    undispatched = int(
        connection.scalar(
            sa.text("SELECT count(*) FROM wiki_outbox_events WHERE dispatched_at IS NULL")
        )
        or 0
    )
    if live_jobs or dead_letter_jobs or undispatched:
        raise RuntimeError(
            "0015 downgrade refused before DDL: durable job runtime data exists "
            f"{{'live_jobs': {live_jobs}, 'dead_letter_jobs': {dead_letter_jobs}, "
            f"'undispatched_outbox_events': {undispatched}}}; drain or archive jobs "
            "and dispatch outbox rows first"
        )


def _validate_downgrade_before_ddl() -> None:
    """在本迁移任何 DDL 之前重放 0006 聚合 preflight（除拓扑自检）。"""
    if context.is_offline_mode():
        # 本迁移的降级 preflight 需要真实连接读自有数据（I9/D-16）。offline
        # `--sql` 模式无连接可用：把偶然的 fail-closed（原先抛 AttributeError）
        # 变成**声明的** fail-closed，避免生成可执行的 DROP 脚本。
        raise RuntimeError(
            "0015 downgrade requires an online connection for its pre-DDL data "
            "preflight; offline `--sql` downgrade is not supported"
        )
    _validate_own_rows_before_ddl()
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
    op.drop_index("ix_wiki_jobs_claim_order", table_name="wiki_jobs")
    op.drop_index("ix_wiki_jobs_claim", table_name="wiki_jobs")
    op.drop_table("wiki_jobs")
