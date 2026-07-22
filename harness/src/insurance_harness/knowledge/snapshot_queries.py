"""Read-only release snapshot queries retained for legacy query compatibility."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.base import utcnow
from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
    require_current_scope,
)
from insurance_harness.knowledge.tables import (
    Claim,
    ClaimRevision,
    CurrentRelease,
    ReleaseSnapshot,
    SnapshotClaim,
)


def _require_scoped_snapshot(
    session: Session,
    scope: KnowledgeScope,
    snapshot_id: str,
) -> ReleaseSnapshot:
    snapshot = session.execute(
        select(ReleaseSnapshot).where(
            ReleaseSnapshot.id == snapshot_id,
            ReleaseSnapshot.space_id == scope.space_id,
        )
    ).scalar_one_or_none()
    if snapshot is None:
        raise ScopeViolation("scope mismatch")
    return snapshot


def current_snapshot_id(session: Session, scope: KnowledgeScope) -> str | None:
    require_current_scope(session, scope)
    pointer = session.get(CurrentRelease, (scope.space_id, "current"))
    if pointer is None:
        return None
    snapshot_id = session.execute(
        select(ReleaseSnapshot.id).where(
            ReleaseSnapshot.space_id == scope.space_id,
            ReleaseSnapshot.id == pointer.snapshot_id,
        )
    ).scalar_one_or_none()
    if snapshot_id is None:
        raise ScopeViolation("scope mismatch")
    return snapshot_id


def snapshot_claim_set(
    session: Session,
    scope: KnowledgeScope,
    snapshot_id: str,
) -> list[tuple[str, int]]:
    require_current_scope(session, scope)
    _require_scoped_snapshot(session, scope, snapshot_id)
    rows = list(
        session.execute(
            select(SnapshotClaim).where(
                SnapshotClaim.space_id == scope.space_id,
                SnapshotClaim.snapshot_id == snapshot_id,
            )
        ).scalars()
    )
    claim_ids = {row.claim_id for row in rows}
    scoped_claim_ids = (
        set(
            session.execute(
                select(Claim.id).where(
                    Claim.space_id == scope.space_id,
                    Claim.id.in_(claim_ids),
                )
            ).scalars()
        )
        if claim_ids
        else set()
    )
    revision_pairs = (
        set(
            session.execute(
                select(ClaimRevision.claim_id, ClaimRevision.revision_no)
                .join(Claim, Claim.id == ClaimRevision.claim_id)
                .where(
                    Claim.space_id == scope.space_id,
                    ClaimRevision.claim_id.in_(claim_ids),
                )
            ).all()
        )
        if claim_ids
        else set()
    )
    if scoped_claim_ids != claim_ids or any(
        (row.claim_id, row.revision_no) not in revision_pairs for row in rows
    ):
        raise ScopeViolation("scope mismatch")
    return [(row.claim_id, row.revision_no) for row in rows]


def default_snapshot_label(session: Session, scope: KnowledgeScope) -> str:
    """Return the next space-scoped release label for the current UTC day."""

    require_current_scope(session, scope)
    today = utcnow().date().isoformat()
    existing = session.execute(
        select(ReleaseSnapshot.label).where(
            ReleaseSnapshot.space_id == scope.space_id,
            ReleaseSnapshot.label.like(f"{today}-r%"),
        )
    ).scalars().all()
    revisions = [
        int(label.removeprefix(f"{today}-r"))
        for label in existing
        if label.removeprefix(f"{today}-r").isdigit()
    ]
    return f"{today}-r{max(revisions, default=0) + 1}"
