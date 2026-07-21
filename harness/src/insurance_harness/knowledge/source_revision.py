"""Source revision notifications and source-scoped lifecycle operations (017 T7)."""

from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from insurance_harness.db.base import utcnow
from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
    require_current_scope,
)
from insurance_harness.knowledge.models import SourceImportIdentity
from insurance_harness.knowledge.source_aggregates import (
    validate_applied_source_change_set as validate_applied_source_change_set,
)
from insurance_harness.knowledge.source_aggregates import (
    validate_retract_tombstone as validate_retract_tombstone,
)
from insurance_harness.knowledge.source_aggregates import (
    validate_source_change_set_aggregate as validate_source_change_set_aggregate,
)
from insurance_harness.knowledge.source_keys import (
    derive_retract_event_key as derive_retract_event_key,
)
from insurance_harness.knowledge.source_lifecycle import (
    LifecycleBusinessOutcome,
    LifecycleDecisionResult,
    coordinate_source_lifecycle,
)
from insurance_harness.knowledge.tables import ChangeSet, Claim, ClaimEvidence


class SourceRevisionReport(BaseModel):
    """Outcome of one source-revision notification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    same_revision: bool
    created: bool
    reused: bool
    stale_count: int = Field(ge=0)
    change_set_id: str | None


def _validated_identity(
    identity: SourceImportIdentity,
    scope: KnowledgeScope,
) -> SourceImportIdentity:
    try:
        validated = SourceImportIdentity.model_validate(identity.model_dump(mode="python"))
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ScopeViolation("scope mismatch") from exc
    if validated.raw_kb_id != scope.raw_kb_id:
        raise ScopeViolation("scope mismatch")
    return validated


def _validated_observed_at(value: datetime | None) -> datetime:
    observed_at = value or utcnow()
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ScopeViolation("scope mismatch")
    return observed_at.astimezone(UTC)


def _existing_recompile(
    session: Session,
    scope: KnowledgeScope,
    identity: SourceImportIdentity,
) -> ChangeSet | None:
    rows = list(
        session.scalars(
            select(ChangeSet).where(
                ChangeSet.space_id == scope.space_id,
                ChangeSet.source_kind.in_(("document", "recompile")),
                ChangeSet.external_record_id == identity.knowledge_id,
                ChangeSet.source_revision == identity.source_revision,
            )
        )
    )
    if not rows:
        return None
    if len(rows) != 1 or rows[0].source_kind != "recompile":
        raise ScopeViolation("source change set is ambiguous")
    change_set = rows[0]
    item_count = validate_source_change_set_aggregate(
        session,
        scope,
        identity,
        change_set,
        allowed_source_kinds=("recompile",),
    )
    if change_set.status != "pending" or item_count != 0:
        raise ScopeViolation("source change set cannot be replayed")
    return change_set


def _existing_zero_evidence_source_change_set(
    session: Session,
    scope: KnowledgeScope,
    identity: SourceImportIdentity,
) -> tuple[ChangeSet | None, bool]:
    """Classify one same-identity source aggregate when no active evidence exists."""
    rows = list(
        session.scalars(
            select(ChangeSet).where(
                ChangeSet.space_id == scope.space_id,
                ChangeSet.source_kind.in_(("document", "recompile")),
                ChangeSet.external_record_id == identity.knowledge_id,
                ChangeSet.source_revision == identity.source_revision,
            )
        )
    )
    if not rows:
        return None, False
    if len(rows) != 1:
        raise ScopeViolation("source change set is ambiguous")
    change_set = rows[0]
    if change_set.status == "applied":
        validate_applied_source_change_set(
            session,
            scope,
            identity,
            change_set,
            allowed_source_kinds=("document", "recompile"),
        )
        # Local import avoids the merge -> source_revision module cycle.
        from insurance_harness.knowledge.merge import (
            validate_scoped_change_set_items,
        )

        try:
            validate_scoped_change_set_items(session, scope, change_set)
        except ScopeViolation:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise ScopeViolation(
                "source change set cannot be replayed"
            ) from exc
        return change_set, True
    item_count = validate_source_change_set_aggregate(
        session,
        scope,
        identity,
        change_set,
        allowed_source_kinds=("document", "recompile"),
    )
    if (
        change_set.source_kind == "recompile"
        and change_set.status == "pending"
        and item_count == 0
    ):
        return change_set, False
    raise ScopeViolation("source change set cannot be replayed")


def _new_recompile_change_set(
    _session: Session,
    scope: KnowledgeScope,
    identity: SourceImportIdentity,
    created_by: str,
) -> ChangeSet:
    return ChangeSet(
        space_id=scope.space_id,
        source_kind="recompile",
        knowledge_ids=[identity.knowledge_id],
        external_record_id=identity.knowledge_id,
        source_revision=identity.source_revision,
        status="pending",
        created_by=created_by,
    )


def _insert_recompile_or_reread(
    session: Session,
    scope: KnowledgeScope,
    identity: SourceImportIdentity,
    *,
    created_by: str,
) -> tuple[ChangeSet, bool]:
    candidate = _new_recompile_change_set(session, scope, identity, created_by)
    try:
        with session.begin_nested():
            session.add(candidate)
            session.flush()
    except IntegrityError:
        winner = _existing_recompile(session, scope, identity)
        if winner is None:
            raise
        return winner, False
    return candidate, True


def _active_source_revisions(
    session: Session,
    scope: KnowledgeScope,
    identity: SourceImportIdentity,
) -> set[str]:
    return set(
        session.scalars(
            select(ClaimEvidence.source_revision)
            .join(Claim, Claim.id == ClaimEvidence.claim_id)
            .where(
                Claim.space_id == scope.space_id,
                ClaimEvidence.knowledge_id == identity.knowledge_id,
                ClaimEvidence.raw_kb_id == scope.raw_kb_id,
                ClaimEvidence.lineage_status.is_not(None),
                ClaimEvidence.source_revision.is_not(None),
                ClaimEvidence.stale_at.is_(None),
            )
        )
    )


def _source_revision_business_outcome(
    session: Session,
    scope: KnowledgeScope,
    identity: SourceImportIdentity,
    stale_timestamp: datetime,
    created_by: str,
    decision: LifecycleDecisionResult,
) -> LifecycleBusinessOutcome:
    """Apply notify business state after the lifecycle decision is durable."""

    active_revisions = _active_source_revisions(session, scope, identity)
    if decision.decision == "idempotent":
        if active_revisions and active_revisions != {identity.source_revision}:
            raise ScopeViolation("source revision state is ambiguous")
        change_set, applied_same_revision = (
            _existing_zero_evidence_source_change_set(
                session,
                scope,
                identity,
            )
        )
        active_same_revision = active_revisions == {identity.source_revision}
        reused_pending = (
            change_set is not None
            and not applied_same_revision
            and not active_same_revision
        )
        linked_change_set_id = (
            change_set.id if change_set is not None else None
        )
        return LifecycleBusinessOutcome(
            payload=SourceRevisionReport(
                same_revision=not reused_pending,
                created=False,
                reused=reused_pending,
                stale_count=0,
                change_set_id=(linked_change_set_id if reused_pending else None),
            ),
            aggregate_kind=(
                "source_revision" if linked_change_set_id is not None else None
            ),
            change_set_id=linked_change_set_id,
        )
    if active_revisions == {identity.source_revision}:
        change_set, _applied = _existing_zero_evidence_source_change_set(
            session,
            scope,
            identity,
        )
        return LifecycleBusinessOutcome(
            payload=SourceRevisionReport(
                same_revision=True,
                created=False,
                reused=False,
                stale_count=0,
                change_set_id=None,
            ),
            aggregate_kind=(
                "source_revision" if change_set is not None else None
            ),
            change_set_id=(change_set.id if change_set is not None else None),
        )
    if identity.source_revision in active_revisions:
        raise ScopeViolation("source revision state is ambiguous")

    if active_revisions:
        change_set = _existing_recompile(session, scope, identity)
        applied_same_revision = False
    else:
        change_set, applied_same_revision = (
            _existing_zero_evidence_source_change_set(
                session,
                scope,
                identity,
            )
        )
    if applied_same_revision:
        assert change_set is not None
        return LifecycleBusinessOutcome(
            payload=SourceRevisionReport(
                same_revision=True,
                created=False,
                reused=False,
                stale_count=0,
                change_set_id=None,
            ),
            aggregate_kind="source_revision",
            change_set_id=change_set.id,
        )
    if change_set is None:
        change_set, created = _insert_recompile_or_reread(
            session,
            scope,
            identity,
            created_by=created_by,
        )
    else:
        created = False
    target_ids = (
        select(ClaimEvidence.id)
        .join(Claim, Claim.id == ClaimEvidence.claim_id)
        .where(
            Claim.space_id == scope.space_id,
            ClaimEvidence.knowledge_id == identity.knowledge_id,
            ClaimEvidence.raw_kb_id == scope.raw_kb_id,
            ClaimEvidence.lineage_status.is_not(None),
            ClaimEvidence.source_revision.is_not(None),
            ClaimEvidence.source_revision != identity.source_revision,
            ClaimEvidence.stale_at.is_(None),
        )
    )
    stale_result = cast(
        CursorResult[Any],
        session.execute(
            update(ClaimEvidence)
            .where(
                ClaimEvidence.id.in_(target_ids),
                ClaimEvidence.stale_at.is_(None),
            )
            .values(stale_at=stale_timestamp)
            .execution_options(synchronize_session="fetch")
        ),
    )
    stale_count = stale_result.rowcount or 0
    return LifecycleBusinessOutcome(
        payload=SourceRevisionReport(
            same_revision=False,
            created=created,
            reused=not created,
            stale_count=stale_count,
            change_set_id=change_set.id,
        ),
        aggregate_kind="source_revision",
        change_set_id=change_set.id,
    )


def notify_source_revision(
    session: Session,
    scope: KnowledgeScope,
    identity: SourceImportIdentity,
    *,
    observed_at: datetime | None = None,
    created_by: str = "source-change",
) -> SourceRevisionReport:
    """Mark an older source revision stale and stage one scoped recompile."""
    identity = _validated_identity(identity, scope)
    require_current_scope(session, scope)
    stale_timestamp = _validated_observed_at(observed_at)
    lifecycle = coordinate_source_lifecycle(
        session,
        scope,
        identity,
        "active",
        actor=created_by,
        apply_business=lambda callback_session, decision: (
            _source_revision_business_outcome(
                callback_session,
                scope,
                identity,
                stale_timestamp,
                created_by,
                decision,
            )
        ),
    )
    if lifecycle.business_payload is None:
        return SourceRevisionReport(
            same_revision=lifecycle.decision == "blocked_deleted",
            created=False,
            reused=False,
            stale_count=0,
            change_set_id=None,
        )
    return SourceRevisionReport.model_validate(lifecycle.business_payload)
