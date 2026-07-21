"""Space-scoped durable feedback-flywheel repository (OpenSpec 015 F3.3).

Public entry points accept a loader-attested ``KnowledgeScope`` and never commit:
the caller owns the transaction. ``apply_pull`` serializes one Space before reading
checkpoint/gap state, writes the processed ledger and aggregates, then advances the
checkpoint last. A caller rollback therefore removes the whole batch.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.models import KnowledgeSpace, ProductVersion
from insurance_harness.db.scope import KnowledgeScope, require_current_scope
from insurance_harness.knowledge.tables import Claim
from insurance_harness.product.routing import MatchIndex

from .gaps import AlignedEntity, GapStatus, KnowledgeGap
from .models import SignalConfig, SignalType, Trace
from .pull import PullResult, TraceEvaluation, run_pull
from .signals import DEFAULT_CONFIG, ClaimLookup
from .tables import FlywheelCheckpoint, FlywheelObservation, KnowledgeGapRow


class FlywheelRepositoryError(ValueError):
    """The durable pull request violates the repository contract."""


def preview_pull(
    session: Session,
    scope: KnowledgeScope,
    source_id: str,
    traces: Sequence[Trace],
    *,
    config: SignalConfig = DEFAULT_CONFIG,
    field_names: Mapping[str, str] | None = None,
) -> PullResult:
    """Evaluate against durable state without modifying any database row."""
    require_current_scope(session, scope)
    _validate_source_id(source_id)
    checkpoint = session.scalar(
        select(FlywheelCheckpoint).where(
            FlywheelCheckpoint.space_id == scope.space_id,
            FlywheelCheckpoint.source_id == source_id,
        )
    )
    gaps = _load_gaps(session, scope)
    index = MatchIndex.from_session(session, scope)
    return run_pull(
        traces,
        index,
        config=config,
        field_names=field_names,
        claim_lookup=_claim_lookup(session, scope),
        cursor=checkpoint.cursor if checkpoint is not None else None,
        existing_gaps=gaps,
    )


def apply_pull(
    session: Session,
    scope: KnowledgeScope,
    source_id: str,
    traces: Sequence[Trace],
    *,
    config: SignalConfig = DEFAULT_CONFIG,
    field_names: Mapping[str, str] | None = None,
) -> PullResult:
    """Stage one atomic durable pull inside the caller-owned transaction.

    A Space-row lock is the cross-process serialization boundary. This is broader
    than a source-row lock by design: gaps aggregate demand across all sources in the
    same Space, so two different sources must not race their shared hit counters.
    """
    require_current_scope(session, scope)
    _validate_source_id(source_id)
    if session.get_transaction() is None:
        raise FlywheelRepositoryError("apply_pull requires a caller-owned transaction")

    locked_space = session.scalar(
        select(KnowledgeSpace)
        .where(KnowledgeSpace.id == scope.space_id)
        .with_for_update()
    )
    if locked_space is None:
        raise FlywheelRepositoryError("knowledge space is unavailable")

    checkpoint = session.scalar(
        select(FlywheelCheckpoint)
        .where(
            FlywheelCheckpoint.space_id == scope.space_id,
            FlywheelCheckpoint.source_id == source_id,
        )
        .with_for_update()
    )
    existing_rows = {
        row.gap_key: row
        for row in session.scalars(
            select(KnowledgeGapRow)
            .where(KnowledgeGapRow.space_id == scope.space_id)
            .with_for_update()
        )
    }
    index = MatchIndex.from_session(session, scope)
    result = run_pull(
        traces,
        index,
        config=config,
        field_names=field_names,
        claim_lookup=_claim_lookup(session, scope),
        cursor=checkpoint.cursor if checkpoint is not None else None,
        existing_gaps=[_gap_from_row(row) for row in existing_rows.values()],
    )

    gap_rows = _persist_gap_rows(session, scope, result.gaps, existing_rows)
    session.flush()  # gap IDs/FKs exist before the immutable ledger is staged
    _persist_evaluations(session, scope, source_id, result.evaluations, gap_rows)
    session.flush()

    if result.next_cursor is not None:
        if checkpoint is None:
            checkpoint = FlywheelCheckpoint(
                space_id=scope.space_id,
                source_id=source_id,
                cursor=result.next_cursor,
            )
            session.add(checkpoint)
        else:
            checkpoint.cursor = result.next_cursor
        session.flush()  # checkpoint is deliberately the last write in the UoW
    return result


def list_unaligned_observations(
    session: Session,
    scope: KnowledgeScope,
    *,
    source_id: str | None = None,
) -> tuple[FlywheelObservation, ...]:
    """Return the consumable unaligned queue for one Space, optionally one source."""
    require_current_scope(session, scope)
    statement = select(FlywheelObservation).where(
        FlywheelObservation.space_id == scope.space_id,
        FlywheelObservation.alignment_reason != "aligned",
    )
    if source_id is not None:
        _validate_source_id(source_id)
        statement = statement.where(FlywheelObservation.source_id == source_id)
    return tuple(
        session.scalars(
            statement.order_by(
                FlywheelObservation.trace_timestamp,
                FlywheelObservation.trace_id,
            )
        )
    )


def _validate_source_id(source_id: str) -> None:
    if (
        not source_id
        or source_id != source_id.strip()
        or len(source_id) > 128
        or any(unicodedata.category(character).startswith("C") for character in source_id)
    ):
        raise FlywheelRepositoryError("source_id is invalid")


def _load_gaps(session: Session, scope: KnowledgeScope) -> list[KnowledgeGap]:
    return [
        _gap_from_row(row)
        for row in session.scalars(
            select(KnowledgeGapRow).where(KnowledgeGapRow.space_id == scope.space_id)
        )
    ]


def _gap_from_row(row: KnowledgeGapRow) -> KnowledgeGap:
    return KnowledgeGap(
        gap_key=row.gap_key,
        entity=AlignedEntity(
            product_id=row.product_id,
            field_id=row.field_id,
            concept_id=row.concept_id,
        ),
        signal_types=tuple(cast(list[SignalType], row.signal_types)),
        hit_count=row.hit_count,
        sample_trace_ids=tuple(row.sample_trace_ids),
        sample_questions=tuple(row.sample_questions),
        status=cast(GapStatus, row.status),  # database check constraint narrows it
        first_seen=_iso(row.first_seen),
        last_seen=_iso(row.last_seen),
        resolved_at=_iso(row.resolved_at),
    )


def _persist_gap_rows(
    session: Session,
    scope: KnowledgeScope,
    gaps: Sequence[KnowledgeGap],
    existing: Mapping[str, KnowledgeGapRow],
) -> dict[str, KnowledgeGapRow]:
    rows = dict(existing)
    for gap in gaps:
        row = rows.get(gap.gap_key)
        if row is None:
            row = KnowledgeGapRow(space_id=scope.space_id, gap_key=gap.gap_key)
            session.add(row)
            rows[gap.gap_key] = row
        row.product_id = gap.entity.product_id
        row.field_id = gap.entity.field_id
        row.concept_id = gap.entity.concept_id
        row.signal_types = list(gap.signal_types)
        row.hit_count = gap.hit_count
        row.sample_trace_ids = list(gap.sample_trace_ids)
        row.sample_questions = list(gap.sample_questions)
        row.status = gap.status
        row.first_seen = _datetime(gap.first_seen)
        row.last_seen = _datetime(gap.last_seen)
        row.resolved_at = _datetime(gap.resolved_at)
    return rows


def _persist_evaluations(
    session: Session,
    scope: KnowledgeScope,
    source_id: str,
    evaluations: Sequence[TraceEvaluation],
    gaps: Mapping[str, KnowledgeGapRow],
) -> None:
    for evaluation in evaluations:
        entity = evaluation.entity
        gap = gaps.get(evaluation.gap_key) if evaluation.gap_key is not None else None
        session.add(
            FlywheelObservation(
                space_id=scope.space_id,
                source_id=source_id,
                trace_id=evaluation.trace_id,
                trace_timestamp=_datetime(evaluation.timestamp),
                question=evaluation.question,
                signal_types=list(evaluation.signal_types),
                alignment_reason=evaluation.reason,
                product_id=entity.product_id if entity is not None else None,
                field_id=entity.field_id if entity is not None else None,
                concept_id=entity.concept_id if entity is not None else None,
                gap_id=gap.id if gap is not None else None,
            )
        )


def _claim_lookup(session: Session, scope: KnowledgeScope) -> ClaimLookup:
    def has_published_claim(gap_key: str) -> bool:
        parts = gap_key.split("|")
        if len(parts) != 3:
            return False
        product_id, field_id, concept_id = parts
        statement = select(Claim.id).where(
            Claim.space_id == scope.space_id,
            Claim.status == "published",
        )
        if product_id:
            statement = statement.join(
                ProductVersion,
                (ProductVersion.id == Claim.product_version_id)
                & (ProductVersion.space_id == Claim.space_id),
            ).where(
                ProductVersion.space_id == scope.space_id,
                ProductVersion.product_id == product_id,
            )
        if field_id:
            statement = statement.where(Claim.predicate == field_id)
        if concept_id:
            statement = statement.where(Claim.concept_id == concept_id)
        return session.scalar(statement.limit(1)) is not None

    return has_published_claim


def _datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
