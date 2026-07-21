"""Pure lifecycle-state-machine contracts for OpenSpec 021 L3."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Never

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation, load_scope
from insurance_harness.knowledge import source_lifecycle as lifecycle_service
from insurance_harness.knowledge import source_revision as revision_service
from insurance_harness.knowledge.models import SourceImportIdentity
from insurance_harness.knowledge.source_lifecycle import (
    LifecycleDecisionResult,
    LifecycleHeadIdentity,
    decide_source_lifecycle,
)
from insurance_harness.knowledge.source_revision import derive_retract_event_key
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    ClaimEvidence,
    ReviewItem,
    SourceEvent,
    SourceHead,
    SourceLifecycleBackfillIssue,
)
from insurance_harness.sources import (
    GenerationOrdering,
    ProcessedAtOrdering,
    SourceOrdering,
    SourceRevision,
)

OrderingKind = Literal["processed_at", "generation"]
HeadState = Literal["active", "deleted"]
DesiredState = Literal["active", "deleted"]
Relation = Literal["first", "older", "equal", "newer"]


@dataclass(frozen=True)
class _MatrixCase:
    name: str
    head_state: HeadState | None
    relation: Relation
    desired_state: DesiredState
    decision: str
    business_intent: str
    head_changed: bool
    next_state: HeadState


_MATRIX: tuple[_MatrixCase, ...] = (
    _MatrixCase(
        "absent_first_active",
        None,
        "first",
        "active",
        "accepted_create",
        "create_active",
        True,
        "active",
    ),
    _MatrixCase(
        "absent_first_deleted",
        None,
        "first",
        "deleted",
        "accepted_delete",
        "create_tombstone",
        True,
        "deleted",
    ),
    _MatrixCase(
        "active_older_active",
        "active",
        "older",
        "active",
        "stale",
        "audit_noop",
        False,
        "active",
    ),
    _MatrixCase(
        "active_older_deleted",
        "active",
        "older",
        "deleted",
        "stale",
        "audit_noop",
        False,
        "active",
    ),
    _MatrixCase(
        "active_equal_active",
        "active",
        "equal",
        "active",
        "idempotent",
        "reuse",
        False,
        "active",
    ),
    _MatrixCase(
        "active_equal_deleted",
        "active",
        "equal",
        "deleted",
        "accepted_delete",
        "create_tombstone",
        True,
        "deleted",
    ),
    _MatrixCase(
        "active_newer_active",
        "active",
        "newer",
        "active",
        "accepted_advance",
        "advance_active",
        True,
        "active",
    ),
    _MatrixCase(
        "active_newer_deleted",
        "active",
        "newer",
        "deleted",
        "accepted_delete",
        "create_tombstone",
        True,
        "deleted",
    ),
    _MatrixCase(
        "deleted_older_active",
        "deleted",
        "older",
        "active",
        "stale",
        "audit_noop",
        False,
        "deleted",
    ),
    _MatrixCase(
        "deleted_older_deleted",
        "deleted",
        "older",
        "deleted",
        "stale",
        "audit_noop",
        False,
        "deleted",
    ),
    _MatrixCase(
        "deleted_equal_active",
        "deleted",
        "equal",
        "active",
        "blocked_deleted",
        "audit_noop",
        False,
        "deleted",
    ),
    _MatrixCase(
        "deleted_equal_deleted",
        "deleted",
        "equal",
        "deleted",
        "idempotent",
        "reuse",
        False,
        "deleted",
    ),
    _MatrixCase(
        "deleted_newer_active",
        "deleted",
        "newer",
        "active",
        "accepted_reactivate",
        "reactivate",
        True,
        "active",
    ),
    _MatrixCase(
        "deleted_newer_deleted",
        "deleted",
        "newer",
        "deleted",
        "accepted_delete",
        "create_tombstone",
        True,
        "deleted",
    ),
)


def _ordering(kind: OrderingKind, position: int) -> SourceOrdering:
    if kind == "processed_at":
        return ProcessedAtOrdering(
            value=datetime(2026, 7, 19, 8, 0, tzinfo=UTC)
            + timedelta(seconds=position)
        )
    return GenerationOrdering(value=position)


def _identity(
    kind: OrderingKind,
    position: int,
    *,
    revision_char: str,
) -> SourceImportIdentity:
    revision = SourceRevision(
        file_hash=revision_char * 32,
        ordering=_ordering(kind, position),
        parser_fingerprint="pdfplumber@0.11:text-v1",
    )
    return SourceImportIdentity(
        knowledge_id="knowledge-1",
        raw_kb_id="raw-1",
        source_revision=revision.value,
        ordering=revision.ordering,
        file_hash=revision.file_hash,
        original_digest=revision_char * 64,
        parser_version=revision.parser_fingerprint,
    )


def _identity_set(
    kind: OrderingKind,
) -> tuple[SourceImportIdentity, SourceImportIdentity, SourceImportIdentity]:
    return (
        _identity(kind, 9, revision_char="a"),
        _identity(kind, 10, revision_char="b"),
        _identity(kind, 11, revision_char="c"),
    )


@pytest.mark.parametrize("ordering_kind", ["processed_at", "generation"])
@pytest.mark.parametrize("case", _MATRIX, ids=lambda case: case.name)
def test_l3_decision_matrix_is_exhaustive_for_each_ordering_kind(
    ordering_kind: OrderingKind,
    case: _MatrixCase,
) -> None:
    older, equal, newer = _identity_set(ordering_kind)
    by_relation = {"older": older, "equal": equal, "newer": newer}
    incoming = equal if case.relation == "first" else by_relation[case.relation]
    head = (
        None
        if case.head_state is None
        else LifecycleHeadIdentity(
            source_revision=equal.source_revision,
            ordering=equal.ordering,
            state=case.head_state,
            version=7,
        )
    )

    result = decide_source_lifecycle(head, incoming, case.desired_state)

    assert result.decision == case.decision
    assert result.business_intent == case.business_intent
    assert result.head_changed is case.head_changed
    assert result.next_head.state == case.next_state
    if head is None:
        assert result.next_head.version == 1
        assert result.next_head.source_revision == incoming.source_revision
        assert result.next_head.ordering == incoming.ordering
    elif case.head_changed:
        assert result.next_head.version == head.version + 1
        assert result.next_head.source_revision == incoming.source_revision
        assert result.next_head.ordering == incoming.ordering
    else:
        assert result.next_head == head


@pytest.mark.parametrize(
    ("head_kind", "incoming_kind"),
    [("processed_at", "generation"), ("generation", "processed_at")],
)
def test_l3_decision_rejects_existing_head_ordering_kind_mismatch(
    head_kind: OrderingKind,
    incoming_kind: OrderingKind,
) -> None:
    head_identity = _identity(head_kind, 10, revision_char="a")
    incoming = _identity(incoming_kind, 11, revision_char="b")
    head = LifecycleHeadIdentity(
        source_revision=head_identity.source_revision,
        ordering=head_identity.ordering,
        state="active",
        version=3,
    )

    with pytest.raises(ValueError, match="ordering kind"):
        decide_source_lifecycle(head, incoming, "active")


@pytest.mark.parametrize("ordering_kind", ["processed_at", "generation"])
def test_l3_decision_rejects_same_ordering_with_different_revision(
    ordering_kind: OrderingKind,
) -> None:
    current = _identity(ordering_kind, 10, revision_char="a")
    incoming = _identity(ordering_kind, 10, revision_char="b")
    head = LifecycleHeadIdentity(
        source_revision=current.source_revision,
        ordering=current.ordering,
        state="active",
        version=3,
    )

    with pytest.raises(ValueError, match="ordering collision"):
        decide_source_lifecycle(head, incoming, "active")


@pytest.mark.parametrize("ordering_kind", ["processed_at", "generation"])
@pytest.mark.parametrize("head_position", [9, 11], ids=["incoming_newer", "incoming_older"])
def test_l3_decision_rejects_same_revision_with_different_ordering(
    ordering_kind: OrderingKind,
    head_position: int,
) -> None:
    incoming = _identity(ordering_kind, 10, revision_char="a")
    head = LifecycleHeadIdentity(
        source_revision=incoming.source_revision,
        ordering=_ordering(ordering_kind, head_position),
        state="active",
        version=3,
    )

    with pytest.raises(ValueError, match="revision.*ordering"):
        decide_source_lifecycle(head, incoming, "active")


def test_l3_decision_revalidates_illegal_desired_state() -> None:
    incoming = _identity("generation", 10, revision_char="a")

    with pytest.raises(ValueError, match="desired state"):
        decide_source_lifecycle(None, incoming, "archived")  # type: ignore[arg-type]


def test_l3_decision_revalidates_forged_head_state() -> None:
    incoming = _identity("generation", 10, revision_char="a")
    head = LifecycleHeadIdentity.model_construct(
        source_revision=incoming.source_revision,
        ordering=incoming.ordering,
        state="archived",
        version=1,
    )

    with pytest.raises(ValueError):
        decide_source_lifecycle(head, incoming, "active")


def test_l3_decision_revalidates_forged_nested_head_ordering() -> None:
    incoming = _identity("processed_at", 10, revision_char="a")
    head = LifecycleHeadIdentity.model_construct(
        source_revision=incoming.source_revision,
        ordering=ProcessedAtOrdering.model_construct(
            value=datetime(2026, 7, 19, 8, 0)
        ),
        state="active",
        version=1,
    )

    with pytest.raises(ValueError):
        decide_source_lifecycle(head, incoming, "active")


def test_l3_decision_revalidates_forged_incoming_identity() -> None:
    valid = _identity("generation", 10, revision_char="a")
    head = LifecycleHeadIdentity(
        source_revision=valid.source_revision,
        ordering=valid.ordering,
        state="active",
        version=1,
    )
    forged = SourceImportIdentity.model_construct(
        **{
            **valid.model_dump(mode="python"),
            "ordering": GenerationOrdering.model_construct(value=True),
        }
    )

    with pytest.raises(ValueError):
        decide_source_lifecycle(head, forged, "active")


def _decision_result_payload(
    decision: str,
    **overrides: object,
) -> dict[str, object]:
    contracts: dict[str, tuple[str, bool, HeadState, int]] = {
        "accepted_create": ("create_active", True, "active", 1),
        "accepted_advance": ("advance_active", True, "active", 2),
        "accepted_delete": ("create_tombstone", True, "deleted", 1),
        "accepted_reactivate": ("reactivate", True, "active", 2),
        "idempotent": ("reuse", False, "active", 1),
        "stale": ("audit_noop", False, "active", 1),
        "blocked_deleted": ("audit_noop", False, "deleted", 1),
    }
    intent, changed, state, version = contracts[decision]
    identity = _identity("generation", version, revision_char="d")
    payload: dict[str, object] = {
        "decision": decision,
        "next_head": LifecycleHeadIdentity(
            source_revision=identity.source_revision,
            ordering=identity.ordering,
            state=state,
            version=version,
        ),
        "business_intent": intent,
        "head_changed": changed,
    }
    next_head_updates = overrides.pop("next_head_updates", None)
    if next_head_updates is not None:
        current = payload["next_head"]
        assert isinstance(current, LifecycleHeadIdentity)
        assert isinstance(next_head_updates, dict)
        payload["next_head"] = current.model_copy(update=next_head_updates)
    payload.update(overrides)
    return payload


_INCONSISTENT_RESULT_CASES: tuple[tuple[str, dict[str, object]], ...] = (
    *(
        (
            f"{decision}_wrong_intent",
            _decision_result_payload(decision, business_intent="reuse"),
        )
        for decision in (
            "accepted_create",
            "accepted_advance",
            "accepted_delete",
            "accepted_reactivate",
            "stale",
            "blocked_deleted",
        )
    ),
    (
        "idempotent_wrong_intent",
        _decision_result_payload("idempotent", business_intent="audit_noop"),
    ),
    *(
        (
            f"{decision}_unchanged",
            _decision_result_payload(decision, head_changed=False),
        )
        for decision in (
            "accepted_create",
            "accepted_advance",
            "accepted_delete",
            "accepted_reactivate",
        )
    ),
    *(
        (
            f"{decision}_changed",
            _decision_result_payload(decision, head_changed=True),
        )
        for decision in ("idempotent", "stale", "blocked_deleted")
    ),
    (
        "accepted_create_deleted",
        _decision_result_payload(
            "accepted_create", next_head_updates={"state": "deleted"}
        ),
    ),
    (
        "accepted_create_later_version",
        _decision_result_payload(
            "accepted_create", next_head_updates={"version": 2}
        ),
    ),
    (
        "accepted_advance_deleted",
        _decision_result_payload(
            "accepted_advance", next_head_updates={"state": "deleted"}
        ),
    ),
    (
        "accepted_reactivate_deleted",
        _decision_result_payload(
            "accepted_reactivate", next_head_updates={"state": "deleted"}
        ),
    ),
    (
        "accepted_advance_initial_version",
        _decision_result_payload(
            "accepted_advance", next_head_updates={"version": 1}
        ),
    ),
    (
        "accepted_reactivate_initial_version",
        _decision_result_payload(
            "accepted_reactivate", next_head_updates={"version": 1}
        ),
    ),
    (
        "accepted_delete_active",
        _decision_result_payload(
            "accepted_delete", next_head_updates={"state": "active"}
        ),
    ),
    (
        "blocked_deleted_active",
        _decision_result_payload(
            "blocked_deleted", next_head_updates={"state": "active"}
        ),
    ),
)


@pytest.mark.parametrize(
    ("case_name", "payload"),
    _INCONSISTENT_RESULT_CASES,
    ids=[case_name for case_name, _ in _INCONSISTENT_RESULT_CASES],
)
def test_l3_decision_result_rejects_inconsistent_contract(
    case_name: str,
    payload: dict[str, object],
) -> None:
    assert case_name
    with pytest.raises(ValueError, match="lifecycle decision result"):
        LifecycleDecisionResult.model_validate(payload)


def test_l3_decision_result_deeply_revalidates_model_construct() -> None:
    payload = _decision_result_payload("accepted_create")
    head = payload["next_head"]
    assert isinstance(head, LifecycleHeadIdentity)
    forged = LifecycleDecisionResult.model_construct(
        decision="accepted_create",
        next_head=head,
        business_intent="create_active",
        head_changed=False,
    )

    with pytest.raises(ValueError, match="lifecycle decision result"):
        LifecycleDecisionResult.model_validate(forged)


def test_l3_decision_result_deeply_revalidates_nested_head() -> None:
    payload = _decision_result_payload("accepted_create")
    head = payload["next_head"]
    assert isinstance(head, LifecycleHeadIdentity)
    forged_head = LifecycleHeadIdentity.model_construct(
        **{**head.model_dump(mode="python"), "state": "archived"}
    )
    forged = LifecycleDecisionResult.model_construct(
        decision="accepted_create",
        next_head=forged_head,
        business_intent="create_active",
        head_changed=True,
    )

    with pytest.raises(ValueError):
        LifecycleDecisionResult.model_validate(forged)


def _row_count(session: Session, table: type[object]) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)


def _persisted_scope(
    session: Session,
    *,
    suffix: str,
) -> KnowledgeScope:
    row = KnowledgeSpace(
        name=f"scope-{suffix}",
        binding_status="bound",
        tenant_id=f"tenant-{suffix}",
        raw_kb_id=f"raw-{suffix}",
        wiki_kb_id=f"wiki-{suffix}",
    )
    session.add(row)
    session.flush()
    return load_scope(session, row.id)


def _scoped_identity(
    scope: KnowledgeScope,
    position: int,
    *,
    revision_char: str,
    ordering_kind: OrderingKind = "generation",
) -> SourceImportIdentity:
    identity = _identity(ordering_kind, position, revision_char=revision_char)
    return identity.model_copy(update={"raw_kb_id": scope.raw_kb_id})


def _open_backfill_issue(
    session: Session,
    scope: KnowledgeScope,
    identity: SourceImportIdentity,
    *,
    observed_revisions: list[str] | None = None,
) -> SourceLifecycleBackfillIssue:
    issue = SourceLifecycleBackfillIssue(
        space_id=scope.space_id,
        tenant_id=scope.tenant_id,
        raw_kb_id=scope.raw_kb_id,
        knowledge_id=identity.knowledge_id,
        observed_revisions=(
            observed_revisions
            if observed_revisions is not None
            else [identity.source_revision]
        ),
        reason="historical ordering unavailable",
        status="open",
    )
    session.add(issue)
    session.flush()
    return issue


def test_l3_notify_late_older_revision_only_appends_stale_event(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-notify-late")
    revision_a = _scoped_identity(scope, 1, revision_char="a")
    revision_b = _scoped_identity(scope, 2, revision_char="b")
    revision_c = _scoped_identity(scope, 3, revision_char="c")
    from tests.support.source_revision import claim_with_evidence

    claim_with_evidence(
        kb_session,
        scope,
        predicate="021_notify_late",
        identities=[revision_a],
    )

    accepted = revision_service.notify_source_revision(
        kb_session,
        scope,
        revision_c,
        observed_at=datetime(2026, 7, 19, 8, 0, tzinfo=UTC),
    )
    late = revision_service.notify_source_revision(
        kb_session,
        scope,
        revision_b,
        observed_at=datetime(2026, 7, 19, 8, 1, tzinfo=UTC),
    )

    assert accepted.created is True
    assert late.model_dump() == {
        "same_revision": False,
        "created": False,
        "reused": False,
        "stale_count": 0,
        "change_set_id": None,
    }
    events = list(
        kb_session.scalars(
            select(SourceEvent)
            .where(
                SourceEvent.space_id == scope.space_id,
                SourceEvent.knowledge_id == revision_a.knowledge_id,
            )
            .order_by(SourceEvent.created_at, SourceEvent.id)
        )
    )
    assert [row.decision for row in events] == ["accepted_create", "stale"]
    recompiles = list(
        kb_session.scalars(
            select(ChangeSet).where(
                ChangeSet.space_id == scope.space_id,
                ChangeSet.source_kind == "recompile",
            )
        )
    )
    assert len(recompiles) == 1
    assert recompiles[0].source_revision == revision_c.source_revision


def test_l3_notify_same_identity_reuses_one_recompile_and_links_idempotent_event(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-notify-idempotent")
    incoming = _scoped_identity(scope, 2, revision_char="b")

    first = revision_service.notify_source_revision(kb_session, scope, incoming)
    second = revision_service.notify_source_revision(kb_session, scope, incoming)

    assert first.created is True and first.reused is False
    assert second.created is False and second.reused is True
    assert first.change_set_id == second.change_set_id
    assert _row_count(kb_session, ChangeSet) == 1
    events = list(
        kb_session.scalars(
            select(SourceEvent)
            .where(
                SourceEvent.space_id == scope.space_id,
                SourceEvent.knowledge_id == incoming.knowledge_id,
            )
            .order_by(SourceEvent.created_at, SourceEvent.id)
        )
    )
    assert [row.decision for row in events] == ["accepted_create", "idempotent"]
    assert [row.change_set_id for row in events] == [
        first.change_set_id,
        first.change_set_id,
    ]


def test_l3_notify_event_failure_rolls_back_callback_and_keeps_session_usable(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-notify-rollback")
    old = _scoped_identity(scope, 1, revision_char="a")
    incoming = _scoped_identity(scope, 2, revision_char="b")
    from tests.support.source_revision import claim_with_evidence

    _, evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate="021_notify_rollback",
        identities=[old],
    )
    evidence_id = evidence[0].id

    def fail_event_flush(
        session: Session,
        _context: object,
        _instances: object,
    ) -> None:
        if any(isinstance(row, SourceEvent) for row in session.new):
            raise RuntimeError("injected source event flush failure")

    sqlalchemy_event.listen(kb_session, "before_flush", fail_event_flush)
    try:
        with pytest.raises(RuntimeError, match="source event flush failure"):
            revision_service.notify_source_revision(
                kb_session,
                scope,
                incoming,
            )
    finally:
        sqlalchemy_event.remove(kb_session, "before_flush", fail_event_flush)

    restored = kb_session.get(ClaimEvidence, evidence_id)
    assert restored is not None and restored.stale_at is None
    assert _row_count(kb_session, ChangeSet) == 0
    assert _row_count(kb_session, SourceHead) == 0
    assert _row_count(kb_session, SourceEvent) == 0
    assert kb_session.get(KnowledgeSpace, scope.space_id) is not None


def test_l3_notify_legacy_same_revision_creates_head_event_with_stable_report(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-notify-legacy-same")
    incoming = _scoped_identity(scope, 1, revision_char="a")
    from tests.support.source_revision import claim_with_evidence

    claim_with_evidence(
        kb_session,
        scope,
        predicate="021_notify_legacy_same",
        identities=[incoming],
    )

    report = revision_service.notify_source_revision(kb_session, scope, incoming)

    assert report.model_dump() == {
        "same_revision": True,
        "created": False,
        "reused": False,
        "stale_count": 0,
        "change_set_id": None,
    }
    head = kb_session.scalar(
        select(SourceHead).where(
            SourceHead.space_id == scope.space_id,
            SourceHead.knowledge_id == incoming.knowledge_id,
        )
    )
    source_event = kb_session.scalar(
        select(SourceEvent).where(
            SourceEvent.space_id == scope.space_id,
            SourceEvent.knowledge_id == incoming.knowledge_id,
        )
    )
    assert head is not None and head.head_revision == incoming.source_revision
    assert source_event is not None
    assert source_event.decision == "accepted_create"
    assert source_event.change_set_id is None


def test_l3_notify_applied_zero_evidence_links_actual_aggregate_only_in_event(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-notify-applied")
    incoming = _scoped_identity(scope, 1, revision_char="a")
    applied = ChangeSet(
        space_id=scope.space_id,
        source_kind="document",
        knowledge_ids=[incoming.knowledge_id],
        external_record_id=incoming.knowledge_id,
        source_revision=incoming.source_revision,
        status="applied",
        created_by="importer",
    )
    kb_session.add(applied)
    kb_session.flush()

    report = revision_service.notify_source_revision(kb_session, scope, incoming)

    assert report.same_revision is True
    assert report.change_set_id is None
    source_event = kb_session.scalar(
        select(SourceEvent).where(
            SourceEvent.space_id == scope.space_id,
            SourceEvent.knowledge_id == incoming.knowledge_id,
        )
    )
    assert source_event is not None
    assert source_event.decision == "accepted_create"
    assert source_event.change_set_id == applied.id


def test_l3_notify_blocked_deleted_skips_business_then_newer_reactivates(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-notify-reactivate")
    deleted = _scoped_identity(scope, 2, revision_char="b")
    lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        deleted,
        "deleted",
        actor="retractor",
        apply_business=lambda session, _decision: _tombstone_outcome(
            session,
            scope,
            deleted,
            status="applied",
        ),
    )
    baseline_change_sets = _row_count(kb_session, ChangeSet)

    blocked = revision_service.notify_source_revision(kb_session, scope, deleted)

    assert blocked.model_dump() == {
        "same_revision": True,
        "created": False,
        "reused": False,
        "stale_count": 0,
        "change_set_id": None,
    }
    assert _row_count(kb_session, ChangeSet) == baseline_change_sets
    newer = _scoped_identity(scope, 3, revision_char="c")

    reactivated = revision_service.notify_source_revision(kb_session, scope, newer)

    assert reactivated.created is True
    events = list(
        kb_session.scalars(
            select(SourceEvent)
            .where(
                SourceEvent.space_id == scope.space_id,
                SourceEvent.knowledge_id == deleted.knowledge_id,
            )
            .order_by(SourceEvent.created_at, SourceEvent.id)
        )
    )
    assert [row.decision for row in events] == [
        "accepted_delete",
        "blocked_deleted",
        "accepted_reactivate",
    ]
    assert events[1].change_set_id is None
    assert events[2].change_set_id == reactivated.change_set_id


def test_l4_notify_cross_scope_aggregate_rolls_back_lifecycle_writes(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-notify-scope")
    foreign_scope = _persisted_scope(
        kb_session,
        suffix="021-notify-scope-foreign",
    )
    incoming = _scoped_identity(scope, 1, revision_char="a")
    foreign_claim = Claim(
        space_id=foreign_scope.space_id,
        product_version_id=None,
        subject_type="product_version",
        predicate="021_notify_foreign",
        value_state="present",
        value={"text": "foreign"},
        status="draft",
        confidence=0.5,
        schema_version="test",
        current_revision=0,
    )
    malformed = ChangeSet(
        space_id=scope.space_id,
        source_kind="document",
        knowledge_ids=[incoming.knowledge_id],
        external_record_id=incoming.knowledge_id,
        source_revision=incoming.source_revision,
        status="applied",
        created_by="malformed",
    )
    kb_session.add_all([foreign_claim, malformed])
    kb_session.flush()
    kb_session.add(
        ChangeItem(
            change_set_id=malformed.id,
            action="add",
            claim_id=foreign_claim.id,
            proposed={"space_id": foreign_scope.space_id},
            decision="auto_applied",
        )
    )
    kb_session.flush()

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        revision_service.notify_source_revision(kb_session, scope, incoming)

    assert _row_count(kb_session, SourceHead) == 0
    assert _row_count(kb_session, SourceEvent) == 0
    assert _row_count(kb_session, ChangeSet) == 1
    assert kb_session.get(ChangeSet, malformed.id) is malformed


def test_l4_notify_idempotent_rejects_foreign_active_revision_without_mutation(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-notify-idempotent-guard")
    head_identity = _scoped_identity(scope, 2, revision_char="b")
    foreign_active = _scoped_identity(scope, 3, revision_char="c")
    initial = lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        head_identity,
        "active",
        actor="legacy-backfill",
    )
    from tests.support.source_revision import claim_with_evidence

    _, evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate="021_notify_idempotent_guard",
        identities=[foreign_active],
    )
    evidence_id = evidence[0].id
    baseline_events = _row_count(kb_session, SourceEvent)

    with pytest.raises(ScopeViolation, match="ambiguous"):
        revision_service.notify_source_revision(
            kb_session,
            scope,
            head_identity,
        )

    restored = kb_session.get(ClaimEvidence, evidence_id)
    assert restored is not None and restored.stale_at is None
    assert _row_count(kb_session, ChangeSet) == 0
    assert _row_count(kb_session, SourceEvent) == baseline_events
    head = kb_session.scalar(
        select(SourceHead).where(
            SourceHead.space_id == scope.space_id,
            SourceHead.knowledge_id == head_identity.knowledge_id,
        )
    )
    assert head is not None
    assert head.version == 1
    assert head.last_event_id == initial.event_id
    assert kb_session.get(KnowledgeSpace, scope.space_id) is not None


def test_l2_persistence_first_active_creates_one_head_and_append_only_event(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-create")
    incoming = _scoped_identity(scope, 1, revision_char="a")

    result = lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        incoming,
        "active",
        actor="test-actor",
    )

    head = kb_session.scalar(
        select(SourceHead).where(
            SourceHead.space_id == scope.space_id,
            SourceHead.knowledge_id == incoming.knowledge_id,
        )
    )
    event = kb_session.scalar(
        select(SourceEvent).where(
            SourceEvent.space_id == scope.space_id,
            SourceEvent.knowledge_id == incoming.knowledge_id,
        )
    )
    assert result.decision == "accepted_create"
    assert head is not None and event is not None
    assert head.version == 1 and head.last_event_id == event.id
    assert event.before_head is None
    assert event.after_head == result.head.model_dump(mode="json")
    assert _row_count(kb_session, SourceHead) == 1
    assert _row_count(kb_session, SourceEvent) == 1


def test_l3_persistence_stale_adds_event_without_mutating_any_head_field(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-stale")
    newer = _scoped_identity(scope, 2, revision_char="b")
    older = _scoped_identity(scope, 1, revision_char="a")
    lifecycle_service.coordinate_source_lifecycle(
        kb_session, scope, newer, "active", actor="creator"
    )
    head = kb_session.scalar(
        select(SourceHead).where(SourceHead.space_id == scope.space_id)
    )
    assert head is not None
    before = {
        column.name: getattr(head, column.name)
        for column in SourceHead.__table__.columns
    }

    result = lifecycle_service.coordinate_source_lifecycle(
        kb_session, scope, older, "deleted", actor="late-delete"
    )

    kb_session.refresh(head)
    after = {
        column.name: getattr(head, column.name)
        for column in SourceHead.__table__.columns
    }
    assert result.decision == "stale"
    assert after == before
    assert _row_count(kb_session, SourceEvent) == 2


def test_l2_persistence_open_backfill_issue_blocks_before_callback_or_writes(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-open")
    incoming = _scoped_identity(scope, 1, revision_char="a")
    kb_session.add(
        SourceLifecycleBackfillIssue(
            space_id=scope.space_id,
            tenant_id=scope.tenant_id,
            raw_kb_id=scope.raw_kb_id,
            knowledge_id=incoming.knowledge_id,
            observed_revisions=[incoming.source_revision],
            reason="historical ordering unavailable",
            status="open",
        )
    )
    kb_session.flush()
    called = False

    def apply_business(
        _session: Session,
        _decision: LifecycleDecisionResult,
    ) -> lifecycle_service.LifecycleBusinessOutcome:
        nonlocal called
        called = True
        return lifecycle_service.LifecycleBusinessOutcome(payload=None)

    with pytest.raises(
        lifecycle_service.SourceLifecycleBlocked,
        match="backfill issue",
    ):
        lifecycle_service.coordinate_source_lifecycle(
            kb_session,
            scope,
            incoming,
            "active",
            actor="normal-entry",
            apply_business=apply_business,
        )

    assert called is False
    assert _row_count(kb_session, SourceHead) == 0
    assert _row_count(kb_session, SourceEvent) == 0


def test_l3_transaction_callback_failure_rolls_back_unit_and_preserves_caller_work(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-failure")
    incoming = _scoped_identity(scope, 1, revision_char="a")
    caller_row = ReviewItem(
        space_id=scope.space_id,
        review_key="caller-before-lifecycle",
        type="conflict",
        subject={"kind": "test"},
        allowed_actions=["defer"],
        status="open",
        risk_level="low",
    )
    kb_session.add(caller_row)
    kb_session.flush()

    def fail_after_business_write(
        session: Session,
        _decision: LifecycleDecisionResult,
    ) -> Never:
        session.add(
            ChangeSet(
                space_id=scope.space_id,
                source_kind="recompile",
                knowledge_ids=[incoming.knowledge_id],
                external_record_id=incoming.knowledge_id,
                source_revision=incoming.source_revision,
                status="pending",
                created_by="callback",
            )
        )
        session.flush()
        raise RuntimeError("injected callback failure")

    with pytest.raises(RuntimeError, match="injected callback failure"):
        lifecycle_service.coordinate_source_lifecycle(
            kb_session,
            scope,
            incoming,
            "active",
            actor="test-actor",
            apply_business=fail_after_business_write,
        )

    assert kb_session.get(ReviewItem, caller_row.id) is not None
    assert _row_count(kb_session, SourceHead) == 0
    assert _row_count(kb_session, SourceEvent) == 0
    assert _row_count(kb_session, ChangeSet) == 0
    kb_session.add(
        ReviewItem(
            space_id=scope.space_id,
            review_key="caller-after-lifecycle",
            type="conflict",
            subject={"kind": "test"},
            allowed_actions=["defer"],
            status="open",
            risk_level="low",
        )
    )
    kb_session.flush()
    assert _row_count(kb_session, ReviewItem) == 2


def test_l3_event_callback_result_persists_links_once_and_returns_payload(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-links")
    incoming = _scoped_identity(scope, 1, revision_char="a")

    def apply_business(
        session: Session,
        _decision: LifecycleDecisionResult,
    ) -> lifecycle_service.LifecycleBusinessOutcome:
        change_set = ChangeSet(
            space_id=scope.space_id,
            source_kind="recompile",
            knowledge_ids=[incoming.knowledge_id],
            external_record_id=incoming.knowledge_id,
            source_revision=incoming.source_revision,
            status="pending",
            created_by="callback",
        )
        session.add(change_set)
        session.flush()
        return lifecycle_service.LifecycleBusinessOutcome(
            payload={"report": "created"},
            aggregate_kind="source_revision",
            change_set_id=change_set.id,
        )

    result = lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        incoming,
        "active",
        actor="test-actor",
        causation_id="notify:1",
        apply_business=apply_business,
    )

    event = kb_session.get(SourceEvent, result.event_id)
    assert event is not None
    assert event.change_set_id == result.links.change_set_id
    assert result.links.aggregate_kind == "source_revision"
    assert event.tombstone_change_item_id is None
    assert event.causation_id == "notify:1"
    assert result.business_payload == {"report": "created"}
    assert _row_count(kb_session, ChangeSet) == 1


def test_l4_scope_raw_kb_mismatch_fails_before_callback_or_lifecycle_writes(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-scope")
    incoming = _scoped_identity(scope, 1, revision_char="a").model_copy(
        update={"raw_kb_id": "raw-other"}
    )
    called = False

    def apply_business(
        _session: Session,
        _decision: LifecycleDecisionResult,
    ) -> lifecycle_service.LifecycleBusinessOutcome:
        nonlocal called
        called = True
        return lifecycle_service.LifecycleBusinessOutcome(payload=None)

    with pytest.raises(ValueError, match="scope mismatch"):
        lifecycle_service.coordinate_source_lifecycle(
            kb_session,
            scope,
            incoming,
            "active",
            actor="test-actor",
            apply_business=apply_business,
        )

    assert called is False
    assert _row_count(kb_session, SourceHead) == 0
    assert _row_count(kb_session, SourceEvent) == 0


@pytest.mark.parametrize(
    ("head_kind", "incoming_kind"),
    [("processed_at", "generation"), ("generation", "processed_at")],
)
def test_l3_transaction_ordering_kind_mismatch_preserves_head_and_session(
    kb_session: Session,
    head_kind: OrderingKind,
    incoming_kind: OrderingKind,
) -> None:
    scope = _persisted_scope(
        kb_session,
        suffix=f"021-kind-{head_kind}",
    )
    current = _scoped_identity(
        scope,
        1,
        revision_char="a",
        ordering_kind=head_kind,
    )
    incoming = _scoped_identity(
        scope,
        2,
        revision_char="b",
        ordering_kind=incoming_kind,
    )
    lifecycle_service.coordinate_source_lifecycle(
        kb_session, scope, current, "active", actor="creator"
    )
    head = kb_session.scalar(
        select(SourceHead).where(SourceHead.space_id == scope.space_id)
    )
    assert head is not None
    before = {
        column.name: getattr(head, column.name)
        for column in SourceHead.__table__.columns
    }
    caller_row = ReviewItem(
        space_id=scope.space_id,
        review_key=f"caller-{head_kind}",
        type="conflict",
        subject={"kind": "test"},
        allowed_actions=["defer"],
        status="open",
        risk_level="low",
    )
    kb_session.add(caller_row)
    kb_session.flush()

    with pytest.raises(ValueError, match="ordering kind"):
        lifecycle_service.coordinate_source_lifecycle(
            kb_session,
            scope,
            incoming,
            "active",
            actor="test-actor",
        )

    kb_session.refresh(head)
    assert {
        column.name: getattr(head, column.name)
        for column in SourceHead.__table__.columns
    } == before
    assert _row_count(kb_session, SourceEvent) == 1
    assert kb_session.get(ReviewItem, caller_row.id) is not None
    kb_session.add(
        ReviewItem(
            space_id=scope.space_id,
            review_key=f"caller-after-{head_kind}",
            type="conflict",
            subject={"kind": "test"},
            allowed_actions=["defer"],
            status="open",
            risk_level="low",
        )
    )
    kb_session.flush()


def test_l2_lock_key_is_stable_signed_int64_and_includes_full_space_source() -> None:
    first = lifecycle_service.source_lifecycle_lock_key("space-a", "knowledge-1")
    repeated = lifecycle_service.source_lifecycle_lock_key(
        "space-a", "knowledge-1"
    )
    other_space = lifecycle_service.source_lifecycle_lock_key(
        "space-b", "knowledge-1"
    )

    assert first == repeated
    assert -(2**63) <= first < 2**63
    assert first != other_space


def test_l3_transaction_lock_failure_rolls_back_unit_and_keeps_session_usable(
    kb_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-lock-failure")
    incoming = _scoped_identity(scope, 1, revision_char="a")
    caller_row = ReviewItem(
        space_id=scope.space_id,
        review_key="caller-before-lock",
        type="conflict",
        subject={"kind": "test"},
        allowed_actions=["defer"],
        status="open",
        risk_level="low",
    )
    kb_session.add(caller_row)
    kb_session.flush()

    def fail_lock(
        session: Session,
        *,
        space_id: str,
        knowledge_id: str,
    ) -> None:
        session.add(
            ChangeSet(
                space_id=space_id,
                source_kind="recompile",
                knowledge_ids=[knowledge_id],
                external_record_id=knowledge_id,
                source_revision=incoming.source_revision,
                status="pending",
                created_by="lock-fault",
            )
        )
        session.flush()
        raise RuntimeError("injected advisory lock failure")

    monkeypatch.setattr(lifecycle_service, "_acquire_source_lock", fail_lock)
    with pytest.raises(RuntimeError, match="injected advisory lock failure"):
        lifecycle_service.coordinate_source_lifecycle(
            kb_session,
            scope,
            incoming,
            "active",
            actor="test-actor",
        )

    assert kb_session.get(ReviewItem, caller_row.id) is not None
    assert _row_count(kb_session, ChangeSet) == 0
    assert _row_count(kb_session, SourceHead) == 0
    assert _row_count(kb_session, SourceEvent) == 0
    kb_session.add(
        ReviewItem(
            space_id=scope.space_id,
            review_key="caller-after-lock",
            type="conflict",
            subject={"kind": "test"},
            allowed_actions=["defer"],
            status="open",
            risk_level="low",
        )
    )
    kb_session.flush()
    assert _row_count(kb_session, ReviewItem) == 2


def test_l3_cas_loser_rereads_redecides_before_calling_business_once(
    kb_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-cas")
    current = _scoped_identity(scope, 1, revision_char="a")
    incoming = _scoped_identity(scope, 2, revision_char="b")
    lifecycle_service.coordinate_source_lifecycle(
        kb_session, scope, current, "active", actor="creator"
    )
    original_cas = getattr(lifecycle_service, "_cas_existing_head", None)
    original_decide = lifecycle_service.decide_source_lifecycle
    cas_calls = 0
    decide_calls = 0
    callback_calls = 0

    def controlled_cas(*args: object, **kwargs: object) -> bool:
        nonlocal cas_calls
        cas_calls += 1
        if cas_calls == 1:
            return False
        assert callable(original_cas)
        return bool(original_cas(*args, **kwargs))

    def counted_decide(
        head: LifecycleHeadIdentity | None,
        identity: SourceImportIdentity,
        desired_state: DesiredState,
    ) -> LifecycleDecisionResult:
        nonlocal decide_calls
        decide_calls += 1
        return original_decide(head, identity, desired_state)

    def apply_business(
        session: Session,
        _decision: LifecycleDecisionResult,
    ) -> lifecycle_service.LifecycleBusinessOutcome:
        nonlocal callback_calls
        callback_calls += 1
        change_set = ChangeSet(
            space_id=scope.space_id,
            source_kind="recompile",
            knowledge_ids=[incoming.knowledge_id],
            external_record_id=incoming.knowledge_id,
            source_revision=incoming.source_revision,
            status="pending",
            created_by="callback",
        )
        session.add(change_set)
        session.flush()
        return lifecycle_service.LifecycleBusinessOutcome(
            payload="advanced",
            aggregate_kind="source_revision",
            change_set_id=change_set.id,
        )

    monkeypatch.setattr(
        lifecycle_service,
        "_cas_existing_head",
        controlled_cas,
        raising=False,
    )
    monkeypatch.setattr(lifecycle_service, "decide_source_lifecycle", counted_decide)
    result = lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        incoming,
        "active",
        actor="advancer",
        apply_business=apply_business,
    )

    head = kb_session.scalar(
        select(SourceHead).where(SourceHead.space_id == scope.space_id)
    )
    assert result.decision == "accepted_advance"
    assert head is not None and head.version == 2
    assert cas_calls == 2
    assert decide_calls == 2
    assert callback_calls == 1
    assert _row_count(kb_session, SourceHead) == 1
    assert _row_count(kb_session, SourceEvent) == 2
    assert _row_count(kb_session, ChangeSet) == 1


def test_l2_cas_initial_conflict_retries_before_calling_business_once(
    kb_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-first-conflict")
    incoming = _scoped_identity(scope, 1, revision_char="a")
    original_insert = getattr(lifecycle_service, "_insert_initial_head", None)
    insert_calls = 0
    callback_calls = 0

    def controlled_insert(
        *args: object,
        **kwargs: object,
    ) -> IntegrityError | None:
        nonlocal insert_calls
        insert_calls += 1
        if insert_calls == 1:
            return _initial_unique_conflict_error()
        assert callable(original_insert)
        result = original_insert(*args, **kwargs)
        assert result is None or isinstance(result, IntegrityError)
        return result

    def apply_business(
        session: Session,
        _decision: LifecycleDecisionResult,
    ) -> lifecycle_service.LifecycleBusinessOutcome:
        nonlocal callback_calls
        callback_calls += 1
        change_set = ChangeSet(
            space_id=scope.space_id,
            source_kind="recompile",
            knowledge_ids=[incoming.knowledge_id],
            external_record_id=incoming.knowledge_id,
            source_revision=incoming.source_revision,
            status="pending",
            created_by="callback",
        )
        session.add(change_set)
        session.flush()
        return lifecycle_service.LifecycleBusinessOutcome(
            payload="created",
            aggregate_kind="source_revision",
            change_set_id=change_set.id,
        )

    monkeypatch.setattr(
        lifecycle_service,
        "_insert_initial_head",
        controlled_insert,
        raising=False,
    )
    result = lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        incoming,
        "active",
        actor="creator",
        apply_business=apply_business,
    )

    assert result.decision == "accepted_create"
    assert insert_calls == 2
    assert callback_calls == 1
    assert _row_count(kb_session, SourceHead) == 1
    assert _row_count(kb_session, SourceEvent) == 1
    assert _row_count(kb_session, ChangeSet) == 1


def _initial_unique_conflict_error() -> IntegrityError:
    return IntegrityError(
        "INSERT INTO source_heads ...",
        {},
        sqlite3.IntegrityError(
            "UNIQUE constraint failed: "
            "source_heads.space_id, source_heads.knowledge_id"
        ),
    )


def test_l2_cas_initial_conflict_without_winner_reraises_original_integrity_error(
    kb_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-no-winner")
    incoming = _scoped_identity(scope, 1, revision_char="a")
    conflict = _initial_unique_conflict_error()
    callback_calls = 0

    def no_winner(*_args: object, **_kwargs: object) -> IntegrityError:
        return conflict

    def apply_business(
        _session: Session,
        _decision: LifecycleDecisionResult,
    ) -> lifecycle_service.LifecycleBusinessOutcome:
        nonlocal callback_calls
        callback_calls += 1
        return lifecycle_service.LifecycleBusinessOutcome(payload=None)

    monkeypatch.setattr(lifecycle_service, "_insert_initial_head", no_winner)
    with pytest.raises(IntegrityError) as raised:
        lifecycle_service.coordinate_source_lifecycle(
            kb_session,
            scope,
            incoming,
            "active",
            actor="creator",
            apply_business=apply_business,
        )

    assert raised.value is conflict
    assert callback_calls == 0
    assert _row_count(kb_session, SourceHead) == 0
    assert _row_count(kb_session, SourceEvent) == 0
    kb_session.add(
        ReviewItem(
            space_id=scope.space_id,
            review_key="after-no-winner",
            type="conflict",
            subject={"kind": "test"},
            allowed_actions=["defer"],
            status="open",
            risk_level="low",
        )
    )
    kb_session.flush()


def _tombstone_outcome(
    session: Session,
    scope: KnowledgeScope,
    incoming: SourceImportIdentity,
    *,
    status: str,
) -> lifecycle_service.LifecycleBusinessOutcome:
    change_set = ChangeSet(
        space_id=scope.space_id,
        source_kind="document",
        knowledge_ids=[incoming.knowledge_id],
        external_record_id=incoming.knowledge_id,
        source_revision=derive_retract_event_key(
            incoming.knowledge_id,
            incoming.source_revision,
        ),
        status=status,
        created_by="retractor",
    )
    session.add(change_set)
    session.flush()
    return lifecycle_service.LifecycleBusinessOutcome(
        payload={"tombstone": status},
        aggregate_kind="tombstone",
        change_set_id=change_set.id,
    )


def test_l3_event_accepts_exact_applied_empty_tombstone_aggregate(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-tombstone")
    incoming = _scoped_identity(scope, 1, revision_char="a")

    result = lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        incoming,
        "deleted",
        actor="retractor",
        apply_business=lambda session, _decision: _tombstone_outcome(
            session,
            scope,
            incoming,
            status="applied",
        ),
    )

    event = kb_session.get(SourceEvent, result.event_id)
    assert result.decision == "accepted_delete"
    assert result.head.state == "deleted"
    assert result.links.aggregate_kind == "tombstone"
    assert event is not None and event.change_set_id == result.links.change_set_id
    assert event.tombstone_change_item_id is None


def test_l3_event_rejects_pending_tombstone_and_rolls_back_entire_unit(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-pending-tombstone")
    incoming = _scoped_identity(scope, 1, revision_char="a")

    with pytest.raises(ValueError, match="aggregate mismatch"):
        lifecycle_service.coordinate_source_lifecycle(
            kb_session,
            scope,
            incoming,
            "deleted",
            actor="retractor",
            apply_business=lambda session, _decision: _tombstone_outcome(
                session,
                scope,
                incoming,
                status="pending",
            ),
        )

    assert _row_count(kb_session, SourceHead) == 0
    assert _row_count(kb_session, SourceEvent) == 0
    assert _row_count(kb_session, ChangeSet) == 0


@pytest.mark.parametrize("mode", ["missing", "wrong_kind"])
def test_l3_event_accepted_delete_requires_exact_tombstone_aggregate(
    kb_session: Session,
    mode: str,
) -> None:
    scope = _persisted_scope(kb_session, suffix=f"021-delete-{mode}")
    incoming = _scoped_identity(scope, 1, revision_char="a")
    callback: object = None
    if mode == "wrong_kind":

        def wrong_kind(
            session: Session,
            _decision: LifecycleDecisionResult,
        ) -> lifecycle_service.LifecycleBusinessOutcome:
            change_set = ChangeSet(
                space_id=scope.space_id,
                source_kind="document",
                knowledge_ids=[incoming.knowledge_id],
                external_record_id=incoming.knowledge_id,
                source_revision=incoming.source_revision,
                status="applied",
                created_by="wrong-kind",
            )
            session.add(change_set)
            session.flush()
            return lifecycle_service.LifecycleBusinessOutcome(
                payload=None,
                aggregate_kind="source_revision",
                change_set_id=change_set.id,
            )

        callback = wrong_kind

    with pytest.raises(
        lifecycle_service.SourceLifecycleError,
        match="tombstone",
    ):
        lifecycle_service.coordinate_source_lifecycle(
            kb_session,
            scope,
            incoming,
            "deleted",
            actor="retractor",
            apply_business=callback,  # type: ignore[arg-type]
        )

    assert _row_count(kb_session, SourceHead) == 0
    assert _row_count(kb_session, SourceEvent) == 0
    assert _row_count(kb_session, ChangeSet) == 0
    kb_session.add(
        ReviewItem(
            space_id=scope.space_id,
            review_key=f"after-delete-{mode}",
            type="conflict",
            subject={"kind": "test"},
            allowed_actions=["defer"],
            status="open",
            risk_level="low",
        )
    )
    kb_session.flush()


def test_l3_event_deleted_idempotent_reuse_requires_tombstone_callback(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-delete-reuse")
    incoming = _scoped_identity(scope, 1, revision_char="a")
    first = lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        incoming,
        "deleted",
        actor="retractor",
        apply_business=lambda session, _decision: _tombstone_outcome(
            session,
            scope,
            incoming,
            status="applied",
        ),
    )

    with pytest.raises(
        lifecycle_service.SourceLifecycleError,
        match="tombstone",
    ):
        lifecycle_service.coordinate_source_lifecycle(
            kb_session,
            scope,
            incoming,
            "deleted",
            actor="replayer",
        )

    head = kb_session.scalar(
        select(SourceHead).where(SourceHead.space_id == scope.space_id)
    )
    assert head is not None and head.last_event_id == first.event_id
    assert _row_count(kb_session, SourceHead) == 1
    assert _row_count(kb_session, SourceEvent) == 1
    assert _row_count(kb_session, ChangeSet) == 1


def test_l3_cas_retry_exhaustion_is_typed_and_preserves_caller_session(
    kb_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-cas-exhaust")
    current = _scoped_identity(scope, 1, revision_char="a")
    incoming = _scoped_identity(scope, 2, revision_char="b")
    lifecycle_service.coordinate_source_lifecycle(
        kb_session, scope, current, "active", actor="creator"
    )
    head = kb_session.scalar(
        select(SourceHead).where(SourceHead.space_id == scope.space_id)
    )
    assert head is not None
    before = {
        column.name: getattr(head, column.name)
        for column in SourceHead.__table__.columns
    }
    callback_calls = 0
    cas_calls = 0

    def always_lose(*_args: object, **_kwargs: object) -> bool:
        nonlocal cas_calls
        cas_calls += 1
        return False

    def apply_business(
        _session: Session,
        _decision: LifecycleDecisionResult,
    ) -> lifecycle_service.LifecycleBusinessOutcome:
        nonlocal callback_calls
        callback_calls += 1
        return lifecycle_service.LifecycleBusinessOutcome(payload=None)

    monkeypatch.setattr(lifecycle_service, "_cas_existing_head", always_lose)
    with pytest.raises(
        lifecycle_service.SourceLifecycleContention,
        match="retry budget",
    ):
        lifecycle_service.coordinate_source_lifecycle(
            kb_session,
            scope,
            incoming,
            "active",
            actor="advancer",
            apply_business=apply_business,
        )

    kb_session.refresh(head)
    assert {
        column.name: getattr(head, column.name)
        for column in SourceHead.__table__.columns
    } == before
    assert cas_calls == 3
    assert callback_calls == 0
    assert _row_count(kb_session, SourceEvent) == 1
    kb_session.add(
        ReviewItem(
            space_id=scope.space_id,
            review_key="caller-after-cas-exhaust",
            type="conflict",
            subject={"kind": "test"},
            allowed_actions=["defer"],
            status="open",
            risk_level="low",
        )
    )
    kb_session.flush()


def test_l2_event_accepted_snapshots_replay_the_durable_head(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-replay")
    first = _scoped_identity(scope, 1, revision_char="a")
    second = _scoped_identity(scope, 2, revision_char="b")
    lifecycle_service.coordinate_source_lifecycle(
        kb_session, scope, first, "active", actor="creator"
    )
    lifecycle_service.coordinate_source_lifecycle(
        kb_session, scope, second, "active", actor="advancer"
    )
    lifecycle_service.coordinate_source_lifecycle(
        kb_session, scope, first, "deleted", actor="late-delete"
    )
    final = lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        second,
        "deleted",
        actor="retractor",
        apply_business=lambda session, _decision: _tombstone_outcome(
            session,
            scope,
            second,
            status="applied",
        ),
    )

    events = list(
        kb_session.scalars(
            select(SourceEvent).where(SourceEvent.space_id == scope.space_id)
        )
    )
    accepted = sorted(
        (
            event.after_head
            for event in events
            if event.decision.startswith("accepted")
        ),
        key=lambda snapshot: int(snapshot["version"]),  # type: ignore[index]
    )
    head = kb_session.scalar(
        select(SourceHead).where(SourceHead.space_id == scope.space_id)
    )
    assert head is not None
    assert [snapshot["version"] for snapshot in accepted] == [1, 2, 3]  # type: ignore[index]
    assert accepted[-1] == final.head.model_dump(mode="json")
    assert head.head_revision == final.head.source_revision
    assert head.version == final.head.version
    assert head.state == final.head.state
    assert head.last_event_id == final.event_id
    assert len(events) == 4


def test_l3_tombstone_key_has_one_neutral_implementation_without_cycle() -> None:
    from insurance_harness.knowledge.source_keys import (
        derive_retract_event_key as neutral_derive,
    )

    assert derive_retract_event_key is neutral_derive
    assert lifecycle_service.derive_retract_event_key is neutral_derive
    assert neutral_derive("knowledge-1", "a" * 64).startswith("retract:")


def test_l3_persistence_idempotent_reuses_aggregate_and_never_moves_head(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-idempotent")
    incoming = _scoped_identity(scope, 1, revision_char="a")

    def create_or_reuse(
        session: Session,
        _decision: LifecycleDecisionResult,
    ) -> lifecycle_service.LifecycleBusinessOutcome:
        change_set = session.scalar(
            select(ChangeSet).where(
                ChangeSet.space_id == scope.space_id,
                ChangeSet.external_record_id == incoming.knowledge_id,
                ChangeSet.source_revision == incoming.source_revision,
            )
        )
        if change_set is None:
            change_set = ChangeSet(
                space_id=scope.space_id,
                source_kind="recompile",
                knowledge_ids=[incoming.knowledge_id],
                external_record_id=incoming.knowledge_id,
                source_revision=incoming.source_revision,
                status="pending",
                created_by="callback",
            )
            session.add(change_set)
            session.flush()
        return lifecycle_service.LifecycleBusinessOutcome(
            payload=change_set.id,
            aggregate_kind="source_revision",
            change_set_id=change_set.id,
        )

    first = lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        incoming,
        "active",
        actor="creator",
        apply_business=create_or_reuse,
    )
    head = kb_session.scalar(
        select(SourceHead).where(SourceHead.space_id == scope.space_id)
    )
    assert head is not None
    before = {
        column.name: getattr(head, column.name)
        for column in SourceHead.__table__.columns
    }
    replay = lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        incoming,
        "active",
        actor="replayer",
        apply_business=create_or_reuse,
    )

    kb_session.refresh(head)
    assert replay.decision == "idempotent"
    assert replay.links == first.links
    assert replay.business_payload == first.business_payload
    assert {
        column.name: getattr(head, column.name)
        for column in SourceHead.__table__.columns
    } == before
    assert _row_count(kb_session, ChangeSet) == 1
    assert _row_count(kb_session, SourceEvent) == 2


def test_l3_persistence_blocked_deleted_is_audit_only_and_skips_callback(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-blocked")
    incoming = _scoped_identity(scope, 1, revision_char="a")
    first = lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        incoming,
        "deleted",
        actor="retractor",
        apply_business=lambda session, _decision: _tombstone_outcome(
            session,
            scope,
            incoming,
            status="applied",
        ),
    )
    called = False

    def apply_business(
        _session: Session,
        _decision: LifecycleDecisionResult,
    ) -> lifecycle_service.LifecycleBusinessOutcome:
        nonlocal called
        called = True
        return lifecycle_service.LifecycleBusinessOutcome(payload=None)

    result = lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        incoming,
        "active",
        actor="late-active",
        apply_business=apply_business,
    )

    head = kb_session.scalar(
        select(SourceHead).where(SourceHead.space_id == scope.space_id)
    )
    assert result.decision == "blocked_deleted"
    assert called is False
    assert head is not None and head.last_event_id == first.event_id
    assert head.version == 1 and head.state == "deleted"
    assert _row_count(kb_session, SourceEvent) == 2


def test_l2_backfill_resolver_active_resolves_issue_and_stales_incompatible_evidence(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-resolve-active")
    old = _scoped_identity(scope, 1, revision_char="a")
    chosen = _scoped_identity(scope, 2, revision_char="b")
    from tests.support.source_revision import claim_with_evidence

    _, evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate="021_resolve_active",
        identities=[old, chosen],
    )
    issue = _open_backfill_issue(
        kb_session,
        scope,
        chosen,
        observed_revisions=[old.source_revision],
    )
    with pytest.raises(ValueError, match="actor"):
        lifecycle_service.resolve_source_lifecycle_backfill_issue(
            kb_session,
            scope,
            issue_id=issue.id,
            identity=chosen,
            desired_state="active",
            actor="",
            reason="attested source record",
        )
    with pytest.raises(ValueError, match="reason"):
        lifecycle_service.resolve_source_lifecycle_backfill_issue(
            kb_session,
            scope,
            issue_id=issue.id,
            identity=chosen,
            desired_state="active",
            actor="administrator",
            reason=" ",
        )

    result = lifecycle_service.resolve_source_lifecycle_backfill_issue(
        kb_session,
        scope,
        issue_id=issue.id,
        identity=chosen,
        desired_state="active",
        actor="administrator",
        reason="attested source record",
    )

    kb_session.refresh(issue)
    assert issue.status == "resolved"
    assert issue.resolved_revision == chosen.source_revision
    assert issue.resolved_ordering_kind == "generation"
    assert issue.resolved_generation == 2
    assert issue.resolved_processed_at is None
    assert issue.expected_state == "active"
    assert issue.resolved_by == "administrator"
    assert issue.resolution_reason == "attested source record"
    assert issue.resolved_at is not None
    head = kb_session.get(SourceHead, result.head_id)
    lifecycle_event = kb_session.get(SourceEvent, result.event_id)
    assert head is not None and lifecycle_event is not None
    assert result.head.state == "active"
    assert head.head_revision == chosen.source_revision and head.version == 1
    assert head.last_event_id == lifecycle_event.id
    assert lifecycle_event.decision == "accepted_create"
    assert lifecycle_event.causation_id == f"backfill:{issue.id}"
    assert lifecycle_event.change_set_id is None
    assert evidence[0].stale_at is not None
    assert evidence[1].stale_at is None


def test_l2_backfill_resolver_deleted_creates_tombstone_and_retracts_evidence(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-resolve-deleted")
    chosen = _scoped_identity(scope, 2, revision_char="b")
    from tests.support.source_revision import claim_with_evidence

    claim, evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate="021_resolve_deleted",
        identities=[chosen],
    )
    issue = _open_backfill_issue(kb_session, scope, chosen)

    result = lifecycle_service.resolve_source_lifecycle_backfill_issue(
        kb_session,
        scope,
        issue_id=issue.id,
        identity=chosen,
        desired_state="deleted",
        actor="administrator",
        reason="source was deleted upstream",
    )

    kb_session.refresh(issue)
    assert issue.status == "resolved" and issue.expected_state == "deleted"
    head = kb_session.get(SourceHead, result.head_id)
    lifecycle_event = kb_session.get(SourceEvent, result.event_id)
    tombstone = kb_session.get(ChangeSet, result.links.change_set_id)
    assert head is not None and lifecycle_event is not None and tombstone is not None
    assert result.head.state == "deleted"
    assert head.state == "deleted" and head.head_revision == chosen.source_revision
    assert lifecycle_event.decision == "accepted_delete"
    assert lifecycle_event.causation_id == f"backfill:{issue.id}"
    assert lifecycle_event.change_set_id == tombstone.id
    assert lifecycle_service.validate_retract_tombstone(
        kb_session,
        scope,
        tombstone,
        knowledge_id=chosen.knowledge_id,
    ) == 1
    assert kb_session.get(ClaimEvidence, evidence[0].id) is None
    restored_claim = kb_session.get(Claim, claim.id)
    assert restored_claim is not None and restored_claim.status == "retracted"


def test_l2_backfill_resolver_exact_retry_is_idempotent_and_conflicts_fail_closed(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-resolve-retry")
    chosen = _scoped_identity(scope, 2, revision_char="b")
    conflicting = _scoped_identity(scope, 3, revision_char="c")
    issue = _open_backfill_issue(kb_session, scope, chosen)

    first = lifecycle_service.resolve_source_lifecycle_backfill_issue(
        kb_session,
        scope,
        issue_id=issue.id,
        identity=chosen,
        desired_state="active",
        actor="administrator",
        reason="attested source record",
    )
    baseline = {
        table: _row_count(kb_session, table)
        for table in (SourceLifecycleBackfillIssue, SourceHead, SourceEvent, ChangeSet)
    }
    retry = lifecycle_service.resolve_source_lifecycle_backfill_issue(
        kb_session,
        scope,
        issue_id=issue.id,
        identity=chosen,
        desired_state="active",
        actor="administrator",
        reason="attested source record",
    )

    assert retry == first
    assert {
        table: _row_count(kb_session, table) for table in baseline
    } == baseline
    with pytest.raises(ScopeViolation, match="resolution conflict"):
        lifecycle_service.resolve_source_lifecycle_backfill_issue(
            kb_session,
            scope,
            issue_id=issue.id,
            identity=conflicting,
            desired_state="active",
            actor="administrator",
            reason="attested source record",
        )
    with pytest.raises(ScopeViolation, match="resolution conflict"):
        lifecycle_service.resolve_source_lifecycle_backfill_issue(
            kb_session,
            scope,
            issue_id=issue.id,
            identity=chosen,
            desired_state="deleted",
            actor="administrator",
            reason="attested source record",
        )
    assert {
        table: _row_count(kb_session, table) for table in baseline
    } == baseline


def test_l3_backfill_resolver_event_failure_rolls_back_and_keeps_session_usable(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-resolve-rollback")
    old = _scoped_identity(scope, 1, revision_char="a")
    chosen = _scoped_identity(scope, 2, revision_char="b")
    from tests.support.source_revision import claim_with_evidence

    _, evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate="021_resolve_rollback",
        identities=[old, chosen],
    )
    issue = _open_backfill_issue(kb_session, scope, chosen)
    caller_row = ReviewItem(
        space_id=scope.space_id,
        review_key="caller-before-backfill-resolution",
        type="conflict",
        subject={"kind": "caller"},
        allowed_actions=["defer"],
        status="open",
        risk_level="low",
    )
    kb_session.add(caller_row)
    kb_session.flush()

    def fail_event_flush(
        session: Session,
        _context: object,
        _instances: object,
    ) -> None:
        if any(isinstance(row, SourceEvent) for row in session.new):
            raise RuntimeError("injected backfill event failure")

    sqlalchemy_event.listen(kb_session, "before_flush", fail_event_flush)
    try:
        with pytest.raises(RuntimeError, match="backfill event failure"):
            lifecycle_service.resolve_source_lifecycle_backfill_issue(
                kb_session,
                scope,
                issue_id=issue.id,
                identity=chosen,
                desired_state="active",
                actor="administrator",
                reason="attested source record",
            )
    finally:
        sqlalchemy_event.remove(kb_session, "before_flush", fail_event_flush)

    kb_session.refresh(issue)
    assert issue.status == "open"
    assert issue.resolved_revision is None and issue.expected_state is None
    assert issue.resolved_by is None and issue.resolution_reason is None
    assert all(row.stale_at is None for row in evidence)
    assert _row_count(kb_session, SourceHead) == 0
    assert _row_count(kb_session, SourceEvent) == 0
    assert _row_count(kb_session, ChangeSet) == 0
    assert _row_count(kb_session, ChangeItem) == 0
    assert kb_session.get(ReviewItem, caller_row.id) is caller_row
    kb_session.add(
        ReviewItem(
            space_id=scope.space_id,
            review_key="caller-after-backfill-resolution-failure",
            type="conflict",
            subject={"kind": "caller"},
            allowed_actions=["defer"],
            status="open",
            risk_level="low",
        )
    )
    kb_session.flush()
    assert _row_count(kb_session, ReviewItem) == 2


def test_l2_backfill_resolution_unblocks_strictly_newer_normal_event(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-resolve-unblock")
    chosen = _scoped_identity(scope, 2, revision_char="b")
    newer = _scoped_identity(scope, 3, revision_char="c")
    issue = _open_backfill_issue(kb_session, scope, chosen)
    resolved = lifecycle_service.resolve_source_lifecycle_backfill_issue(
        kb_session,
        scope,
        issue_id=issue.id,
        identity=chosen,
        desired_state="active",
        actor="administrator",
        reason="attested source record",
    )

    advanced = revision_service.notify_source_revision(
        kb_session,
        scope,
        newer,
        observed_at=datetime(2026, 7, 19, 9, 0, tzinfo=UTC),
    )

    kb_session.refresh(issue)
    head = kb_session.get(SourceHead, resolved.head_id)
    assert issue.status == "resolved"
    assert issue.resolved_revision == chosen.source_revision
    assert head is not None and head.head_revision == newer.source_revision
    assert head.state == "active" and head.version == 2
    assert advanced.created is True and advanced.change_set_id is not None
    events = list(
        kb_session.scalars(
            select(SourceEvent)
            .where(
                SourceEvent.space_id == scope.space_id,
                SourceEvent.knowledge_id == chosen.knowledge_id,
            )
            .order_by(SourceEvent.created_at, SourceEvent.id)
        )
    )
    assert [row.decision for row in events] == [
        "accepted_create",
        "accepted_advance",
    ]
    assert events[0].causation_id == f"backfill:{issue.id}"
    assert events[1].causation_id is None
    baseline = {
        table: _row_count(kb_session, table)
        for table in (SourceLifecycleBackfillIssue, SourceHead, SourceEvent, ChangeSet)
    }
    for field, value in {
        "status": "open",
        "resolved_revision": None,
        "resolved_ordering_kind": None,
        "resolved_processed_at": None,
        "resolved_generation": None,
        "expected_state": None,
        "resolved_by": None,
        "resolution_reason": None,
        "resolved_at": None,
    }.items():
        set_committed_value(issue, field, value)
    assert issue.status == "open" and issue not in kb_session.dirty

    retry = lifecycle_service.resolve_source_lifecycle_backfill_issue(
        kb_session,
        scope,
        issue_id=issue.id,
        identity=chosen,
        desired_state="active",
        actor="administrator",
        reason="attested source record",
    )

    assert retry == resolved
    assert {
        table: _row_count(kb_session, table) for table in baseline
    } == baseline


def test_l4_backfill_resolver_rejects_cross_space_issue_without_mutation(
    kb_session: Session,
) -> None:
    scope_a = _persisted_scope(kb_session, suffix="021-resolve-space-a")
    scope_b = _persisted_scope(kb_session, suffix="021-resolve-space-b")
    identity_a = _scoped_identity(scope_a, 2, revision_char="b")
    identity_b = _scoped_identity(scope_b, 2, revision_char="b")
    issue = _open_backfill_issue(kb_session, scope_a, identity_a)

    with pytest.raises(ScopeViolation, match="unavailable"):
        lifecycle_service.resolve_source_lifecycle_backfill_issue(
            kb_session,
            scope_b,
            issue_id=issue.id,
            identity=identity_b,
            desired_state="active",
            actor="administrator",
            reason="attested source record",
        )

    kb_session.refresh(issue)
    assert issue.status == "open" and issue.resolved_revision is None
    assert _row_count(kb_session, SourceHead) == 0
    assert _row_count(kb_session, SourceEvent) == 0
    assert _row_count(kb_session, ChangeSet) == 0
    assert kb_session.get(KnowledgeSpace, scope_b.space_id) is not None


def test_l2_persistence_resolved_issue_allows_normal_first_event(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-resolved")
    incoming = _scoped_identity(scope, 1, revision_char="a")
    kb_session.add(
        SourceLifecycleBackfillIssue(
            space_id=scope.space_id,
            tenant_id=scope.tenant_id,
            raw_kb_id=scope.raw_kb_id,
            knowledge_id=incoming.knowledge_id,
            observed_revisions=[incoming.source_revision],
            reason="historical ordering unavailable",
            status="resolved",
            resolved_revision=incoming.source_revision,
            resolved_ordering_kind="generation",
            resolved_generation=1,
            expected_state="active",
            resolved_by="administrator",
            resolution_reason="attested source record",
            resolved_at=datetime.now(UTC),
        )
    )
    kb_session.flush()

    result = lifecycle_service.coordinate_source_lifecycle(
        kb_session, scope, incoming, "active", actor="normal-entry"
    )

    assert result.decision == "accepted_create"
    assert _row_count(kb_session, SourceHead) == 1
    assert _row_count(kb_session, SourceEvent) == 1


def test_l4_scope_same_knowledge_id_has_independent_heads_and_events(
    kb_session: Session,
) -> None:
    scope_a = _persisted_scope(kb_session, suffix="021-space-a")
    scope_b = _persisted_scope(kb_session, suffix="021-space-b")
    source_a = _scoped_identity(scope_a, 1, revision_char="a")
    source_b = _scoped_identity(scope_b, 1, revision_char="a")

    lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope_a,
        source_a,
        "deleted",
        actor="a",
        apply_business=lambda session, _decision: _tombstone_outcome(
            session,
            scope_a,
            source_a,
            status="applied",
        ),
    )
    lifecycle_service.coordinate_source_lifecycle(
        kb_session, scope_b, source_b, "active", actor="b"
    )

    heads = list(kb_session.scalars(select(SourceHead)))
    assert len(heads) == 2
    assert {row.space_id: row.state for row in heads} == {
        scope_a.space_id: "deleted",
        scope_b.space_id: "active",
    }
    assert _row_count(kb_session, SourceEvent) == 2
    assert lifecycle_service.source_lifecycle_lock_key(
        scope_a.space_id, source_a.knowledge_id
    ) != lifecycle_service.source_lifecycle_lock_key(
        scope_b.space_id, source_b.knowledge_id
    )


@pytest.mark.parametrize(
    "collision",
    ["same_ordering", "same_revision"],
)
def test_l3_transaction_identity_collision_has_zero_writes_and_session_survives(
    kb_session: Session,
    collision: str,
) -> None:
    scope = _persisted_scope(kb_session, suffix=f"021-collision-{collision}")
    current = _scoped_identity(scope, 1, revision_char="a")
    lifecycle_service.coordinate_source_lifecycle(
        kb_session, scope, current, "active", actor="creator"
    )
    if collision == "same_ordering":
        incoming = _scoped_identity(scope, 1, revision_char="b")
    else:
        incoming = current.model_copy(
            update={"ordering": GenerationOrdering(value=2)}
        )
    head = kb_session.scalar(
        select(SourceHead).where(SourceHead.space_id == scope.space_id)
    )
    assert head is not None
    before = {
        column.name: getattr(head, column.name)
        for column in SourceHead.__table__.columns
    }

    with pytest.raises(ValueError, match="ordering|revision mismatch"):
        lifecycle_service.coordinate_source_lifecycle(
            kb_session, scope, incoming, "active", actor="collision"
        )

    kb_session.refresh(head)
    assert {
        column.name: getattr(head, column.name)
        for column in SourceHead.__table__.columns
    } == before
    assert _row_count(kb_session, SourceEvent) == 1
    kb_session.add(
        ReviewItem(
            space_id=scope.space_id,
            review_key=f"after-{collision}",
            type="conflict",
            subject={"kind": "test"},
            allowed_actions=["defer"],
            status="open",
            risk_level="low",
        )
    )
    kb_session.flush()


def test_l2_lock_postgres_shape_uses_transaction_advisory_full_key() -> None:
    statements: list[tuple[str, dict[str, int]]] = []

    class _Dialect:
        name = "postgresql"

    class _Bind:
        dialect = _Dialect()

    class _Session:
        def get_bind(self) -> _Bind:
            return _Bind()

        def execute(
            self,
            statement: object,
            parameters: dict[str, int],
        ) -> None:
            statements.append((str(statement), parameters))

    fake_session = _Session()
    lifecycle_service._acquire_source_lock(  # noqa: SLF001
        fake_session,  # type: ignore[arg-type]
        space_id="space-a",
        knowledge_id="knowledge-1",
    )

    assert statements == [
        (
            "SELECT pg_advisory_xact_lock(:lock_key)",
            {
                "lock_key": lifecycle_service.source_lifecycle_lock_key(
                    "space-a", "knowledge-1"
                )
            },
        )
    ]


def test_l2_cas_initial_insert_does_not_hide_non_unique_integrity_errors(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-insert-check")
    invalid = SourceHead(
        space_id=scope.space_id,
        tenant_id=scope.tenant_id,
        raw_kb_id=scope.raw_kb_id,
        knowledge_id="knowledge-1",
        head_revision="a" * 64,
        ordering_kind="generation",
        ordering_generation=1,
        state="archived",
        version=1,
        actor="test",
        head_updated_at=datetime.now(UTC),
    )

    with pytest.raises(IntegrityError, match="CHECK constraint failed"):
        lifecycle_service._insert_initial_head(kb_session, invalid)  # noqa: SLF001


def test_l4_scope_event_link_rejects_multi_knowledge_source_aggregate(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-multi-knowledge")
    incoming = _scoped_identity(scope, 1, revision_char="a")

    def apply_business(
        session: Session,
        _decision: LifecycleDecisionResult,
    ) -> lifecycle_service.LifecycleBusinessOutcome:
        change_set = ChangeSet(
            space_id=scope.space_id,
            source_kind="recompile",
            knowledge_ids=[incoming.knowledge_id, "foreign-knowledge"],
            external_record_id=incoming.knowledge_id,
            source_revision=incoming.source_revision,
            status="pending",
            created_by="callback",
        )
        session.add(change_set)
        session.flush()
        return lifecycle_service.LifecycleBusinessOutcome(
            payload=None,
            aggregate_kind="source_revision",
            change_set_id=change_set.id,
        )

    with pytest.raises(ValueError, match="aggregate mismatch"):
        lifecycle_service.coordinate_source_lifecycle(
            kb_session,
            scope,
            incoming,
            "active",
            actor="creator",
            apply_business=apply_business,
        )

    assert _row_count(kb_session, SourceHead) == 0
    assert _row_count(kb_session, SourceEvent) == 0
    assert _row_count(kb_session, ChangeSet) == 0


def test_l4_scope_tombstone_rejects_cross_space_claim_child_and_rolls_back(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-tombstone-scope")
    other_scope = _persisted_scope(kb_session, suffix="021-tombstone-foreign")
    incoming = _scoped_identity(scope, 1, revision_char="a")
    foreign_claim = Claim(
        space_id=other_scope.space_id,
        subject_type="product_version",
        product_version_id=None,
        predicate="foreign",
        value_state="present",
        value={"value": "foreign"},
        status="draft",
        confidence=0.5,
        schema_version="test",
        current_revision=0,
    )
    kb_session.add(foreign_claim)
    kb_session.flush()

    def apply_business(
        session: Session,
        _decision: LifecycleDecisionResult,
    ) -> lifecycle_service.LifecycleBusinessOutcome:
        outcome = _tombstone_outcome(
            session,
            scope,
            incoming,
            status="applied",
        )
        assert outcome.change_set_id is not None
        session.add(
            ChangeItem(
                change_set_id=outcome.change_set_id,
                action="retract",
                claim_id=foreign_claim.id,
                proposed={
                    "knowledge_id": incoming.knowledge_id,
                    "removed_evidence": 1,
                },
                decision="auto_applied",
            )
        )
        session.flush()
        return outcome

    with pytest.raises(ValueError, match="aggregate mismatch|tombstone"):
        lifecycle_service.coordinate_source_lifecycle(
            kb_session,
            scope,
            incoming,
            "deleted",
            actor="retractor",
            apply_business=apply_business,
        )

    assert kb_session.get(Claim, foreign_claim.id) is not None
    assert _row_count(kb_session, SourceHead) == 0
    assert _row_count(kb_session, SourceEvent) == 0
    assert _row_count(kb_session, ChangeSet) == 0
    assert _row_count(kb_session, ChangeItem) == 0
    kb_session.add(
        ReviewItem(
            space_id=scope.space_id,
            review_key="after-cross-claim",
            type="conflict",
            subject={"kind": "test"},
            allowed_actions=["defer"],
            status="open",
            risk_level="low",
        )
    )
    kb_session.flush()


def test_l3_source_aggregate_validators_have_one_neutral_implementation() -> None:
    from insurance_harness.knowledge.source_aggregates import (
        validate_retract_tombstone as neutral_tombstone,
    )
    from insurance_harness.knowledge.source_aggregates import (
        validate_source_change_set_aggregate as neutral_source,
    )
    from insurance_harness.knowledge.source_revision import (
        validate_retract_tombstone as revision_tombstone,
    )
    from insurance_harness.knowledge.source_revision import (
        validate_source_change_set_aggregate as revision_source,
    )

    assert revision_tombstone is neutral_tombstone
    assert revision_source is neutral_source
    assert lifecycle_service.validate_retract_tombstone is neutral_tombstone
    assert lifecycle_service.validate_source_change_set_aggregate is neutral_source


def test_l4_scope_source_aggregate_rejects_foreign_claim_child_and_rolls_back(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-source-child")
    other_scope = _persisted_scope(kb_session, suffix="021-source-child-foreign")
    incoming = _scoped_identity(scope, 1, revision_char="a")
    foreign_claim = Claim(
        space_id=other_scope.space_id,
        subject_type="product_version",
        product_version_id=None,
        predicate="foreign-source-child",
        value_state="present",
        value={"value": "foreign"},
        status="draft",
        confidence=0.5,
        schema_version="test",
        current_revision=0,
    )
    kb_session.add(foreign_claim)
    kb_session.flush()

    def apply_business(
        session: Session,
        _decision: LifecycleDecisionResult,
    ) -> lifecycle_service.LifecycleBusinessOutcome:
        change_set = ChangeSet(
            space_id=scope.space_id,
            source_kind="document",
            knowledge_ids=[incoming.knowledge_id],
            external_record_id=incoming.knowledge_id,
            source_revision=incoming.source_revision,
            status="applied",
            created_by="callback",
        )
        session.add(change_set)
        session.flush()
        session.add(
            ChangeItem(
                change_set_id=change_set.id,
                action="add",
                claim_id=foreign_claim.id,
                proposed={
                    "space_id": other_scope.space_id,
                    "predicate": "foreign-source-child",
                },
                decision="auto_applied",
            )
        )
        session.flush()
        return lifecycle_service.LifecycleBusinessOutcome(
            payload=None,
            aggregate_kind="source_revision",
            change_set_id=change_set.id,
        )

    with pytest.raises(ValueError, match="scope mismatch"):
        lifecycle_service.coordinate_source_lifecycle(
            kb_session,
            scope,
            incoming,
            "active",
            actor="creator",
            apply_business=apply_business,
        )

    assert kb_session.get(Claim, foreign_claim.id) is not None
    assert _row_count(kb_session, SourceHead) == 0
    assert _row_count(kb_session, SourceEvent) == 0
    assert _row_count(kb_session, ChangeSet) == 0
    assert _row_count(kb_session, ChangeItem) == 0
    kb_session.add(
        ReviewItem(
            space_id=scope.space_id,
            review_key="after-foreign-source-child",
            type="conflict",
            subject={"kind": "test"},
            allowed_actions=["defer"],
            status="open",
            risk_level="low",
        )
    )
    kb_session.flush()


def test_l3_cas_cached_stale_head_is_refreshed_before_redecision(
    kb_session: Session,
) -> None:
    scope = _persisted_scope(kb_session, suffix="021-cached-head")
    current = _scoped_identity(scope, 1, revision_char="a")
    incoming = _scoped_identity(scope, 2, revision_char="b")
    first = lifecycle_service.coordinate_source_lifecycle(
        kb_session, scope, current, "active", actor="creator"
    )
    head = kb_session.scalar(
        select(SourceHead).where(SourceHead.space_id == scope.space_id)
    )
    assert head is not None and head.version == 1
    current_head = LifecycleHeadIdentity(
        source_revision=current.source_revision,
        ordering=current.ordering,
        state="active",
        version=1,
    )
    winner_head = decide_source_lifecycle(
        current_head,
        incoming,
        "active",
    ).next_head
    winner_event = SourceEvent(
        space_id=scope.space_id,
        tenant_id=scope.tenant_id,
        raw_kb_id=scope.raw_kb_id,
        knowledge_id=incoming.knowledge_id,
        input_revision=incoming.source_revision,
        ordering_kind="generation",
        ordering_generation=2,
        desired_state="active",
        decision="accepted_advance",
        before_head=current_head.model_dump(mode="json"),
        after_head=winner_head.model_dump(mode="json"),
        actor="concurrent-winner",
    )
    kb_session.add(winner_event)
    kb_session.flush()
    updated = kb_session.execute(
        update(SourceHead)
        .where(SourceHead.id == head.id, SourceHead.version == 1)
        .values(
            head_revision=incoming.source_revision,
            ordering_kind="generation",
            ordering_processed_at=None,
            ordering_generation=2,
            state="active",
            version=2,
            last_event_id=winner_event.id,
            actor="concurrent-winner",
            head_updated_at=datetime.now(UTC),
        )
        .execution_options(synchronize_session=False)
    )
    assert isinstance(updated, CursorResult)
    assert updated.rowcount == 1
    assert head.version == 1
    assert head.last_event_id == first.event_id

    result = lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        incoming,
        "active",
        actor="replayer",
    )

    assert result.decision == "idempotent"
    kb_session.refresh(head)
    assert head.version == 2
    assert head.last_event_id == winner_event.id
    assert _row_count(kb_session, SourceEvent) == 3
