"""Neutral validators for durable source ChangeSet aggregates."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.knowledge.models import SourceImportIdentity
from insurance_harness.knowledge.tables import ChangeItem, ChangeSet, Claim, Conflict

_APPLIED_SOURCE_ITEM_ACTIONS = frozenset(
    {"add", "enrich", "supersede", "conflict", "retract"}
)
_APPLIED_SOURCE_ITEM_DECISIONS = frozenset({"auto_applied", "approved"})


def _has_foreign_explicit_space_id(payload: Any, expected_space_id: str) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "space_id" and value != expected_space_id:
                return True
            if _has_foreign_explicit_space_id(value, expected_space_id):
                return True
    elif isinstance(payload, list):
        return any(
            _has_foreign_explicit_space_id(value, expected_space_id)
            for value in payload
        )
    return False


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
    items = list(
        session.scalars(
            select(ChangeItem).where(ChangeItem.change_set_id == change_set.id)
        )
    )
    claim_ids = {item.claim_id for item in items if item.claim_id is not None}
    if claim_ids:
        scoped_claim_ids = set(
            session.scalars(
                select(Claim.id).where(
                    Claim.id.in_(claim_ids),
                    Claim.space_id == scope.space_id,
                )
            )
        )
        if scoped_claim_ids != claim_ids:
            raise ScopeViolation("scope mismatch")
    if any(
        _has_foreign_explicit_space_id(item.proposed, scope.space_id)
        or _has_foreign_explicit_space_id(item.decision_basis, scope.space_id)
        for item in items
    ):
        raise ScopeViolation("scope mismatch")

    conflicts = list(
        session.scalars(
            select(Conflict)
            .join(ChangeItem, ChangeItem.id == Conflict.change_item_id)
            .where(ChangeItem.change_set_id == change_set.id)
        )
    )
    existing_claim_ids = {
        conflict.existing_claim_id
        for conflict in conflicts
        if conflict.existing_claim_id is not None
    }
    if existing_claim_ids:
        scoped_existing_ids = set(
            session.scalars(
                select(Claim.id).where(
                    Claim.id.in_(existing_claim_ids),
                    Claim.space_id == scope.space_id,
                )
            )
        )
        if scoped_existing_ids != existing_claim_ids:
            raise ScopeViolation("scope mismatch")
    if any(
        _has_foreign_explicit_space_id(conflict.proposed, scope.space_id)
        or _has_foreign_explicit_space_id(
            conflict.decision_basis,
            scope.space_id,
        )
        for conflict in conflicts
    ):
        raise ScopeViolation("scope mismatch")
    return session.scalar(
        select(func.count())
        .select_from(ChangeItem)
        .where(ChangeItem.change_set_id == change_set.id)
    ) or 0


def validate_applied_source_change_set(
    session: Session,
    scope: KnowledgeScope,
    identity: SourceImportIdentity,
    change_set: ChangeSet,
    *,
    allowed_source_kinds: tuple[str, ...],
) -> int:
    """Validate one terminal applied source aggregate and its item semantics."""

    item_count = validate_source_change_set_aggregate(
        session,
        scope,
        identity,
        change_set,
        allowed_source_kinds=allowed_source_kinds,
    )
    if change_set.status != "applied":
        raise ScopeViolation("source change set cannot be replayed")
    items = tuple(
        session.scalars(
            select(ChangeItem).where(ChangeItem.change_set_id == change_set.id)
        )
    )
    if any(
        item.action not in _APPLIED_SOURCE_ITEM_ACTIONS
        or item.decision not in _APPLIED_SOURCE_ITEM_DECISIONS
        for item in items
    ):
        raise ScopeViolation("source change set cannot be replayed")
    return item_count
