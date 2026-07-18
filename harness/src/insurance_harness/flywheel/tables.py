"""OpenSpec 015 durable feedback-flywheel ORM (migration 0012)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from insurance_harness.db.base import Base
from insurance_harness.db.models import TimestampMixin, _uuid


class FlywheelCheckpoint(TimestampMixin, Base):
    """Completed safe-watermark for one normalized trace source in one Space."""

    __tablename__ = "flywheel_checkpoints"
    __table_args__ = (
        UniqueConstraint("space_id", "source_id", name="uq_flywheel_checkpoint_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_flywheel_checkpoint_space")
    )
    source_id: Mapped[str] = mapped_column(String(128))
    cursor: Mapped[str] = mapped_column(String(512))


class KnowledgeGapRow(TimestampMixin, Base):
    """Space-scoped durable aggregate for one aligned knowledge-gap key."""

    __tablename__ = "knowledge_gaps"
    __table_args__ = (
        UniqueConstraint("space_id", "gap_key", name="uq_knowledge_gap_key"),
        UniqueConstraint("space_id", "id", name="uq_knowledge_gaps_space_id"),
        ForeignKeyConstraint(
            ["space_id", "product_id"],
            ["insurance_products.space_id", "insurance_products.id"],
            name="fk_knowledge_gap_space_product",
        ),
        CheckConstraint("hit_count >= 0", name="ck_knowledge_gap_hit_count"),
        CheckConstraint(
            "status IN ('open', 'resolved', 'reopened')",
            name="ck_knowledge_gap_status",
        ),
        Index("ix_knowledge_gaps_space_status", "space_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_knowledge_gaps_space")
    )
    gap_key: Mapped[str] = mapped_column(String(512))
    product_id: Mapped[str | None] = mapped_column(String(36))
    field_id: Mapped[str | None] = mapped_column(String(128))
    concept_id: Mapped[str | None] = mapped_column(String(36))
    signal_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    sample_trace_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    sample_questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="open")
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FlywheelObservation(TimestampMixin, Base):
    """Processed-trace ledger and Space-scoped unaligned observation queue."""

    __tablename__ = "flywheel_observations"
    __table_args__ = (
        UniqueConstraint(
            "space_id", "source_id", "trace_id", name="uq_flywheel_observation_trace"
        ),
        ForeignKeyConstraint(
            ["space_id", "gap_id"],
            ["knowledge_gaps.space_id", "knowledge_gaps.id"],
            name="fk_flywheel_observation_space_gap",
        ),
        ForeignKeyConstraint(
            ["space_id", "product_id"],
            ["insurance_products.space_id", "insurance_products.id"],
            name="fk_flywheel_observation_space_product",
        ),
        CheckConstraint(
            "alignment_reason IN "
            "('aligned', 'no_actionable_match', 'multi_product_ambiguity')",
            name="ck_flywheel_observation_alignment_reason",
        ),
        Index(
            "ix_flywheel_observations_unaligned",
            "space_id",
            "alignment_reason",
            "trace_timestamp",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_spaces.id", name="fk_flywheel_observation_space")
    )
    source_id: Mapped[str] = mapped_column(String(128))
    trace_id: Mapped[str] = mapped_column(String(255))
    trace_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    question: Mapped[str] = mapped_column(Text)
    signal_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    alignment_reason: Mapped[str] = mapped_column(String(32))
    product_id: Mapped[str | None] = mapped_column(String(36))
    field_id: Mapped[str | None] = mapped_column(String(128))
    concept_id: Mapped[str | None] = mapped_column(String(36))
    gap_id: Mapped[str | None] = mapped_column(String(36))
