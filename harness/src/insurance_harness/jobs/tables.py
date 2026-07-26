"""OpenSpec 035 P1 ORM：`wiki_jobs` 与 `wiki_outbox_events`（迁移 0015）。

`wiki_` 前缀与既有 harness 遗留域表明确区分；两表都 NOT NULL 绑定
`space_id`（P1.8），不外键遗留域表。schema 变更先改迁移 0015 再改此处，
ORM 与迁移由 alembic check 保持零漂移。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from insurance_harness.db.base import Base
from insurance_harness.db.models import _uuid

_JOB_STATES = (
    "'queued', 'leased', 'running', 'succeeded', "
    "'retry_wait', 'awaiting_human', 'blocked', 'dead_letter'"
)
_ERROR_CLASSES = "'retryable', 'non_retryable', 'capacity_blocked', 'human_required'"


class WikiJob(Base):
    """一行一个 at-least-once 任务；状态与 lease 只经 JobStore 写入。"""

    __tablename__ = "wiki_jobs"
    __table_args__ = (
        UniqueConstraint(
            "space_id", "job_type", "idempotency_key", name="uq_wiki_jobs_idempotency"
        ),
        CheckConstraint(f"state IN ({_JOB_STATES})", name="ck_wiki_jobs_state"),
        CheckConstraint("attempt >= 0", name="ck_wiki_jobs_attempt"),
        CheckConstraint("lease_generation >= 0", name="ck_wiki_jobs_generation"),
        CheckConstraint(
            f"error_class IS NULL OR error_class IN ({_ERROR_CLASSES})",
            name="ck_wiki_jobs_error_class",
        ),
        CheckConstraint(
            "state NOT IN ('leased', 'running') "
            "OR (worker_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_wiki_jobs_lease_shape",
        ),
        Index("ix_wiki_jobs_claim", "space_id", "state", "available_at"),
        Index("ix_wiki_jobs_reclaim", "state", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(String(36))
    job_type: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(16))
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    lease_generation: Mapped[int] = mapped_column(Integer, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(128))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enqueued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_class: Mapped[str | None] = mapped_column(String(32))
    error_summary: Mapped[str | None] = mapped_column(Text)


class WikiOutboxEvent(Base):
    """事务性 outbox 行；id 只表示分配顺序，投递以持久 dispatched_at 为准。"""

    __tablename__ = "wiki_outbox_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_wiki_outbox_events_event_id"),
        Index(
            "ix_wiki_outbox_events_undispatched",
            "id",
            sqlite_where=text("dispatched_at IS NULL"),
            postgresql_where=text("dispatched_at IS NULL"),
        ),
        Index("ix_wiki_outbox_events_space", "space_id", "id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    event_id: Mapped[str] = mapped_column(String(36), default=_uuid)
    space_id: Mapped[str] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
