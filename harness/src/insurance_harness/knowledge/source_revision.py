"""Source revision notifications and source-scoped lifecycle operations (017 T7)."""

import hashlib
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select, update
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
from insurance_harness.knowledge.tables import ChangeItem, ChangeSet, Claim, ClaimEvidence


class SourceRevisionReport(BaseModel):
    """Outcome of one source-revision notification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    same_revision: bool
    created: bool
    reused: bool
    stale_count: int = Field(ge=0)
    change_set_id: str | None


def derive_retract_event_key(knowledge_id: str, event_revision: str) -> str:
    """Return the reserved 64-character revision for one deletion event."""
    digest = hashlib.sha256(
        f"{knowledge_id}\0{event_revision}".encode()
    ).hexdigest()
    return f"retract:{digest[:56]}"


def validate_retract_tombstone(
    session: Session,
    scope: KnowledgeScope,
    change_set: ChangeSet,
    *,
    knowledge_id: str,
) -> int:
    """Validate a scoped applied retract aggregate and return its item count."""
    if (
        change_set.space_id != scope.space_id
        or change_set.source_kind != "document"
        or change_set.status != "applied"
        or change_set.knowledge_ids != [knowledge_id]
    ):
        raise ScopeViolation("source tombstone is invalid")
    items = list(
        session.scalars(
            select(ChangeItem).where(ChangeItem.change_set_id == change_set.id)
        )
    )
    scoped_items = list(
        session.scalars(
            select(ChangeItem)
            .join(Claim, Claim.id == ChangeItem.claim_id)
            .where(
                ChangeItem.change_set_id == change_set.id,
                Claim.space_id == scope.space_id,
            )
        )
    )
    if len(scoped_items) != len(items):
        raise ScopeViolation("source tombstone is invalid")
    seen_claim_ids: set[str] = set()
    for item in scoped_items:
        proposed = item.proposed
        removed_evidence = (
            proposed.get("removed_evidence")
            if isinstance(proposed, dict)
            else None
        )
        if (
            item.claim_id is None
            or item.claim_id in seen_claim_ids
            or item.action != "retract"
            or item.decision != "auto_applied"
            or not isinstance(proposed, dict)
            or proposed.get("knowledge_id") != knowledge_id
            or type(removed_evidence) is not int
            or removed_evidence <= 0
        ):
            raise ScopeViolation("source tombstone is invalid")
        seen_claim_ids.add(item.claim_id)
    return len(items)


def validate_source_change_set_aggregate(
    session: Session,
    scope: KnowledgeScope,
    identity: SourceImportIdentity,
    change_set: ChangeSet,
    *,
    allowed_source_kinds: tuple[str, ...],
) -> int:
    """Validate immutable source identity fields and return the child item count."""
    if (
        change_set.space_id != scope.space_id
        or change_set.source_kind not in allowed_source_kinds
        or change_set.external_record_id != identity.knowledge_id
        or change_set.source_revision != identity.source_revision
        or change_set.knowledge_ids != [identity.knowledge_id]
    ):
        raise ScopeViolation("source change set aggregate mismatch")
    return session.scalar(
        select(func.count())
        .select_from(ChangeItem)
        .where(ChangeItem.change_set_id == change_set.id)
    ) or 0


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

    with session.begin_nested():
        active_revisions = set(
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
        if active_revisions == {identity.source_revision}:
            return SourceRevisionReport(
                same_revision=True,
                created=False,
                reused=False,
                stale_count=0,
                change_set_id=None,
            )
        if identity.source_revision in active_revisions:
            raise ScopeViolation("source revision state is ambiguous")

        change_set = _existing_recompile(session, scope, identity)
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
            )
        )
        stale_count = stale_result.rowcount or 0
        session.flush()
        return SourceRevisionReport(
            same_revision=False,
            created=created,
            reused=not created,
            stale_count=stale_count,
            change_set_id=change_set.id,
        )
