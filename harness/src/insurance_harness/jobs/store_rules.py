"""JobStore 存储层共享规则（S7f-2c 自 store.py 拆出）：数据库时钟、输入合同与写权威门。

store、outbox 与 metrics 共用这些规则；过期与调度判定只用数据库时钟（P1.3）。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from insurance_harness.jobs.errors import (
    InvalidJobInputError,
    LeaseExpiredError,
    SpaceScopeError,
    StaleGenerationError,
)
from insurance_harness.jobs.tables import WikiJob

SessionFactory = Callable[[], Session]

_SQLITE_NOW = text("SELECT strftime('%Y-%m-%d %H:%M:%f', 'now')")
_POSTGRES_NOW = text("SELECT clock_timestamp()")


# 输入合同上限与列宽一致；越界在存储层前置 typed 拒绝，不泄漏 DataError。
MAX_SPACE_ID_LENGTH = 36
MAX_JOB_ID_LENGTH = 36
MAX_JOB_TYPE_LENGTH = 64
MAX_IDEMPOTENCY_KEY_LENGTH = 255
MAX_WORKER_ID_LENGTH = 128


def database_now(session: Session) -> datetime:
    """读数据库时钟（UTC）；过期与调度判定不得使用 worker 本地时钟。

    PostgreSQL 用 `clock_timestamp()`（语句时刻）：在 advisory 锁等待之后
    读取的时刻仍然新鲜，签发的 lease 不会「出生即过期」（review I3）。
    """
    bind = session.get_bind()
    if bind.dialect.name == "sqlite":
        raw = session.execute(_SQLITE_NOW).scalar_one()
        return datetime.fromisoformat(str(raw)).replace(tzinfo=UTC)
    value = session.execute(_POSTGRES_NOW).scalar_one()
    assert isinstance(value, datetime)
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def aware_utc(value: datetime | None) -> datetime | None:
    """SQLite 存储丢失 offset；所有列值均按 UTC 写入，读回补齐 tzinfo。"""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)



def validated_text(value: str, name: str, *, max_length: int) -> str:
    """输入合同：非空、无 NUL、长度受限；违规 typed 拒绝（review I6/M16）。"""
    if not isinstance(value, str) or not value:
        raise InvalidJobInputError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise InvalidJobInputError(f"{name} must not contain NUL characters")
    if len(value) > max_length:
        raise InvalidJobInputError(f"{name} must be at most {max_length} characters")
    return value


def validated_limit(value: int, name: str) -> int:
    """只读入口的分页/批量上限校验（P1.9 读路径输入合同，D-2026-07-27-16）。

    `limit = 0` 会产生与"无事可做"完全不可区分的空结果，`limit < 0` 会泄漏
    原始驱动异常；两者一律 typed `invalid_input`。
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidJobInputError(f"{name} must be an integer")
    if value < 1:
        raise InvalidJobInputError(f"{name} must be >= 1")
    return value


def require_active_lease(session: Session, row: WikiJob, *, now: datetime | None = None) -> None:
    """写权威过期门（P1.3 写权威合同，D-2026-07-27-16）。

    写权威 = 当前 generation ∧ lease 未过期。本函数是**唯一**执法点，
    heartbeat/start/结果提交/失败上报/outbox 追加共用它——四条路径不得
    各自实现或省略过期判定，否则"被计入并发上限的集合"与"仍能写的集合"
    会不一致（C1 的窄计数 + 宽写权威即由此裂开）。判定只用数据库时钟。
    """
    current = database_now(session) if now is None else now
    expires_at = aware_utc(row.lease_expires_at)
    if expires_at is None or expires_at <= current:
        raise LeaseExpiredError(job_id=row.id)


def validated_payload(payload: Mapping[str, Any] | None, name: str = "payload") -> dict[str, Any]:
    """payload 必须是可 JSON 序列化的映射；违规 typed 拒绝（review I6）。"""
    materialized = dict(payload or {})
    try:
        json.dumps(materialized)
    except (TypeError, ValueError) as error:
        raise InvalidJobInputError(f"{name} must be JSON-serializable: {error}") from error
    return materialized


# --- fenced write guard（S7f-2c 自 JobStore 移出）---


def locked_job(session: Session, space_id: str, job_id: str) -> WikiJob:
    """FOR UPDATE 锁定并校验 scope；不一致/不存在 fail closed（P1.8）。"""
    validated_text(space_id, "space_id", max_length=MAX_SPACE_ID_LENGTH)
    validated_text(job_id, "job_id", max_length=MAX_JOB_ID_LENGTH)
    row = session.execute(
        select(WikiJob)
        .where(WikiJob.id == job_id, WikiJob.space_id == space_id)
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise SpaceScopeError()
    return row

def check_generation(row: WikiJob, generation: int) -> None:
    """generation 不等于当前值的写入一律 typed `stale_generation`。"""
    if generation != row.lease_generation:
        raise StaleGenerationError(
            expected=row.lease_generation, actual=generation, job_id=row.id
        )
