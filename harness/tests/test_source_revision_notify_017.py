"""Source revision notification and race contracts."""

import pytest
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.knowledge import source_revision as revision_service
from insurance_harness.knowledge.models import SourceImportIdentity
from insurance_harness.knowledge.source_revision import SourceRevisionReport
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    ClaimEvidence,
    CurrentRelease,
    ReleaseSnapshot,
    SnapshotClaim,
)
from tests.support.source_revision import (
    EARLIER,
    NOW,
    bound_scope,
    claim_with_evidence,
    count_rows,
    source_identity,
)


def test_t7_source_revision_report_is_frozen_and_strict() -> None:
    report = SourceRevisionReport(
        same_revision=False,
        created=True,
        reused=False,
        stale_count=2,
        change_set_id="change-set-1",
    )

    assert report.model_dump() == {
        "same_revision": False,
        "created": True,
        "reused": False,
        "stale_count": 2,
        "change_set_id": "change-set-1",
    }
    with pytest.raises(ValidationError):
        report.stale_count = 3
    with pytest.raises(ValidationError):
        SourceRevisionReport(
            same_revision=True,
            created=False,
            reused=False,
            stale_count=0,
            change_set_id=None,
            unexpected=True,  # type: ignore[call-arg]
        )


def test_t7_same_active_revision_is_a_noop(kb_session: Session) -> None:
    scope = bound_scope(kb_session)
    identity = source_identity(scope)
    _, evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[identity],
    )

    report = revision_service.notify_source_revision(
        kb_session,
        scope,
        identity,
        observed_at=NOW,
    )

    assert report == SourceRevisionReport(
        same_revision=True,
        created=False,
        reused=False,
        stale_count=0,
        change_set_id=None,
    )
    assert evidence[0].stale_at is None
    assert count_rows(kb_session, ChangeSet) == 0


def test_t7_new_revision_marks_only_scoped_matching_source_aware_evidence_stale(
    kb_session: Session,
) -> None:
    scope_a = bound_scope(kb_session, "a")
    scope_b = bound_scope(kb_session, "b")
    old_a = source_identity(scope_a, revision_char="a")
    other_a = source_identity(scope_a, knowledge_id="knowledge-other", revision_char="c")
    old_b = source_identity(scope_b, revision_char="a")
    _, rows_a = claim_with_evidence(
        kb_session,
        scope_a,
        predicate="waiting_period-a",
        identities=[old_a, other_a],
    )
    _, rows_b = claim_with_evidence(
        kb_session,
        scope_b,
        predicate="waiting_period-b",
        identities=[old_b],
    )
    new_a = source_identity(scope_a, revision_char="b")

    report = revision_service.notify_source_revision(
        kb_session,
        scope_a,
        new_a,
        observed_at=NOW,
    )

    assert report.same_revision is False
    assert report.created is True
    assert report.reused is False
    assert report.stale_count == 1
    assert report.change_set_id is not None
    assert rows_a[0].stale_at == NOW
    assert rows_a[1].stale_at is None
    assert rows_b[0].stale_at is None
    change_set = kb_session.get(ChangeSet, report.change_set_id)
    assert change_set is not None
    assert (
        change_set.space_id,
        change_set.source_kind,
        change_set.external_record_id,
        change_set.source_revision,
        change_set.status,
    ) == (scope_a.space_id, "recompile", "knowledge-1", "b" * 64, "pending")


def test_t7_repeated_new_revision_notification_reuses_one_pending_recompile(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session)
    old = source_identity(scope, revision_char="a")
    claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    new = source_identity(scope, revision_char="b")

    first = revision_service.notify_source_revision(
        kb_session, scope, new, observed_at=NOW
    )
    second = revision_service.notify_source_revision(
        kb_session, scope, new, observed_at=NOW
    )

    assert first.created is True and first.reused is False
    assert second.created is False and second.reused is True
    assert second.stale_count == 0
    assert first.change_set_id == second.change_set_id
    assert count_rows(kb_session, ChangeSet) == 1


def test_t7_notification_rejects_raw_kb_mismatch_before_query_or_mutation(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session)
    forged = source_identity(scope).model_copy(update={"raw_kb_id": "raw-other"})
    statements: list[str] = []
    bind = kb_session.get_bind()

    def capture_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(bind, "before_cursor_execute", capture_statement)
    try:
        with pytest.raises(ScopeViolation, match="scope mismatch"):
            revision_service.notify_source_revision(kb_session, scope, forged)
    finally:
        event.remove(bind, "before_cursor_execute", capture_statement)

    assert statements == []
    assert count_rows(kb_session, ChangeSet) == 0
    assert count_rows(kb_session, ClaimEvidence) == 0


@pytest.mark.parametrize(
    ("status", "with_item"),
    [
        ("pending", True),
        ("rejected", False),
        ("applied", False),
        ("partially_applied", False),
    ],
)
def test_t7_notification_rejects_nonempty_or_nonpending_recompile_without_stale_leak(
    kb_session: Session,
    status: str,
    with_item: bool,
) -> None:
    scope = bound_scope(kb_session)
    old = source_identity(scope, revision_char="a")
    _, evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    new = source_identity(scope, revision_char="b")
    blocked = ChangeSet(
        space_id=scope.space_id,
        source_kind="recompile",
        knowledge_ids=[new.knowledge_id],
        external_record_id=new.knowledge_id,
        source_revision=new.source_revision,
        status=status,
        created_by="test",
    )
    kb_session.add(blocked)
    kb_session.flush()
    if with_item:
        kb_session.add(
            ChangeItem(
                change_set_id=blocked.id,
                action="add",
                proposed={"interrupted": True},
                decision="needs_review",
            )
        )
        kb_session.flush()
    baseline = (count_rows(kb_session, ChangeSet), count_rows(kb_session, ChangeItem))
    evidence_id = evidence[0].id

    with pytest.raises(ScopeViolation, match="source change set cannot be replayed"):
        revision_service.notify_source_revision(
            kb_session,
            scope,
            new,
            observed_at=NOW,
        )

    kb_session.commit()
    assert kb_session.get(ClaimEvidence, evidence_id).stale_at is None  # type: ignore[union-attr]
    assert (count_rows(kb_session, ChangeSet), count_rows(kb_session, ChangeItem)) == baseline


def test_t7_notification_rejects_document_recompile_ambiguity(kb_session: Session) -> None:
    scope = bound_scope(kb_session)
    old = source_identity(scope, revision_char="a")
    _, evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    new = source_identity(scope, revision_char="b")
    kb_session.add_all(
        [
            ChangeSet(
                space_id=scope.space_id,
                source_kind=kind,
                knowledge_ids=[new.knowledge_id],
                external_record_id=new.knowledge_id,
                source_revision=new.source_revision,
                status="pending",
                created_by="test",
            )
            for kind in ("document", "recompile")
        ]
    )
    kb_session.flush()
    evidence_id = evidence[0].id

    with pytest.raises(ScopeViolation, match="ambiguous|source change set"):
        revision_service.notify_source_revision(
            kb_session,
            scope,
            new,
            observed_at=NOW,
        )

    kb_session.commit()
    assert kb_session.get(ClaimEvidence, evidence_id).stale_at is None  # type: ignore[union-attr]
    assert count_rows(kb_session, ChangeSet) == 2


@pytest.mark.parametrize(
    "knowledge_ids",
    [None, ["knowledge-other"], ["knowledge-1", "knowledge-other"]],
)
def test_t7_notification_rejects_malformed_recompile_knowledge_ids_without_stale_leak(
    kb_session: Session,
    knowledge_ids: list[str] | None,
) -> None:
    scope = bound_scope(kb_session)
    old = source_identity(scope, revision_char="a")
    _, evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    new = source_identity(scope, revision_char="b")
    blocked = ChangeSet(
        space_id=scope.space_id,
        source_kind="recompile",
        knowledge_ids=knowledge_ids,
        external_record_id=new.knowledge_id,
        source_revision=new.source_revision,
        status="pending",
        created_by="test",
    )
    kb_session.add(blocked)
    kb_session.flush()
    evidence_id = evidence[0].id

    with pytest.raises(ScopeViolation, match="aggregate mismatch"):
        revision_service.notify_source_revision(
            kb_session,
            scope,
            new,
            observed_at=NOW,
        )

    kb_session.commit()
    restored = kb_session.get(ClaimEvidence, evidence_id)
    assert restored is not None and restored.stale_at is None
    assert count_rows(kb_session, ChangeSet) == 1
    assert count_rows(kb_session, ChangeItem) == 0


def test_t7_notification_flush_failure_rolls_back_stale_and_changeset(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session)
    old = source_identity(scope, revision_char="a")
    _, evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    new = source_identity(scope, revision_char="b")
    evidence_id = evidence[0].id

    def fail_recompile_flush(session: Session, _context: object, _instances: object) -> None:
        if any(
            isinstance(row, ChangeSet) and row.source_kind == "recompile"
            for row in session.new
        ):
            raise RuntimeError("injected recompile flush failure")

    event.listen(kb_session, "before_flush", fail_recompile_flush)
    try:
        with pytest.raises(RuntimeError, match="injected recompile flush failure"):
            revision_service.notify_source_revision(
                kb_session,
                scope,
                new,
                observed_at=NOW,
            )
    finally:
        event.remove(kb_session, "before_flush", fail_recompile_flush)

    kb_session.commit()
    assert kb_session.get(ClaimEvidence, evidence_id).stale_at is None  # type: ignore[union-attr]
    assert count_rows(kb_session, ChangeSet) == 0


def test_t7_duplicate_key_race_rereads_exact_pending_winner(
    kb_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = bound_scope(kb_session)
    old = source_identity(scope, revision_char="a")
    _, evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    new = source_identity(scope, revision_char="b")

    def race_factory(
        session: Session,
        factory_scope: KnowledgeScope,
        factory_identity: SourceImportIdentity,
        created_by: str,
    ) -> ChangeSet:
        winner = ChangeSet(
            space_id=factory_scope.space_id,
            source_kind="recompile",
            knowledge_ids=[factory_identity.knowledge_id],
            external_record_id=factory_identity.knowledge_id,
            source_revision=factory_identity.source_revision,
            status="pending",
            created_by="racing-session",
        )
        session.add(winner)
        session.flush()
        return ChangeSet(
            space_id=factory_scope.space_id,
            source_kind="recompile",
            knowledge_ids=[factory_identity.knowledge_id],
            external_record_id=factory_identity.knowledge_id,
            source_revision=factory_identity.source_revision,
            status="pending",
            created_by=created_by,
        )

    monkeypatch.setattr(
        revision_service,
        "_new_recompile_change_set",
        race_factory,
        raising=False,
    )

    report = revision_service.notify_source_revision(
        kb_session,
        scope,
        new,
        observed_at=NOW,
    )

    assert report.created is False and report.reused is True
    assert report.stale_count == 1
    assert count_rows(kb_session, ChangeSet) == 1
    winner = kb_session.get(ChangeSet, report.change_set_id)
    assert winner is not None and winner.created_by == "racing-session"
    assert evidence[0].stale_at == NOW


@pytest.mark.parametrize(("winner_status", "with_item"), [("rejected", False), ("pending", True)])
def test_t7_duplicate_key_race_rejects_invalid_winner_and_rolls_back_stale(
    kb_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    winner_status: str,
    with_item: bool,
) -> None:
    scope = bound_scope(kb_session)
    old = source_identity(scope, revision_char="a")
    _, evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    evidence_id = evidence[0].id
    new = source_identity(scope, revision_char="b")

    def invalid_race_factory(
        session: Session,
        factory_scope: KnowledgeScope,
        factory_identity: SourceImportIdentity,
        created_by: str,
    ) -> ChangeSet:
        winner = ChangeSet(
            space_id=factory_scope.space_id,
            source_kind="recompile",
            knowledge_ids=[factory_identity.knowledge_id],
            external_record_id=factory_identity.knowledge_id,
            source_revision=factory_identity.source_revision,
            status=winner_status,
            created_by="racing-session",
        )
        session.add(winner)
        session.flush()
        if with_item:
            session.add(
                ChangeItem(
                    change_set_id=winner.id,
                    action="add",
                    proposed={"raced": True},
                    decision="needs_review",
                )
            )
            session.flush()
        return ChangeSet(
            space_id=factory_scope.space_id,
            source_kind="recompile",
            knowledge_ids=[factory_identity.knowledge_id],
            external_record_id=factory_identity.knowledge_id,
            source_revision=factory_identity.source_revision,
            status="pending",
            created_by=created_by,
        )

    monkeypatch.setattr(
        revision_service,
        "_new_recompile_change_set",
        invalid_race_factory,
        raising=False,
    )

    with pytest.raises(ScopeViolation, match="source change set cannot be replayed"):
        revision_service.notify_source_revision(
            kb_session,
            scope,
            new,
            observed_at=NOW,
        )

    kb_session.commit()
    assert kb_session.get(ClaimEvidence, evidence_id).stale_at is None  # type: ignore[union-attr]
    assert count_rows(kb_session, ChangeSet) == 0
    assert count_rows(kb_session, ChangeItem) == 0


def test_t7_unrelated_integrity_error_is_not_misclassified_as_recompile_race(
    kb_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = bound_scope(kb_session)
    old = source_identity(scope, revision_char="a")
    _, evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    evidence_id = evidence[0].id
    new = source_identity(scope, revision_char="b")
    collision = ChangeSet(
        id="collision-id",
        space_id=scope.space_id,
        source_kind="manual_edit",
        knowledge_ids=None,
        external_record_id="unrelated",
        source_revision="unrelated",
        status="pending",
        created_by="test",
    )
    kb_session.add(collision)
    kb_session.flush()
    kb_session.expunge(collision)

    def colliding_factory(
        _session: Session,
        factory_scope: KnowledgeScope,
        factory_identity: SourceImportIdentity,
        created_by: str,
    ) -> ChangeSet:
        return ChangeSet(
            id="collision-id",
            space_id=factory_scope.space_id,
            source_kind="recompile",
            knowledge_ids=[factory_identity.knowledge_id],
            external_record_id=factory_identity.knowledge_id,
            source_revision=factory_identity.source_revision,
            status="pending",
            created_by=created_by,
        )

    monkeypatch.setattr(
        revision_service,
        "_new_recompile_change_set",
        colliding_factory,
        raising=False,
    )

    with pytest.raises(IntegrityError):
        revision_service.notify_source_revision(
            kb_session,
            scope,
            new,
            observed_at=NOW,
        )

    kb_session.commit()
    assert kb_session.get(ClaimEvidence, evidence_id).stale_at is None  # type: ignore[union-attr]
    assert count_rows(kb_session, ChangeSet) == 1


def test_t7_notification_ignores_legacy_and_other_source_rows_on_mixed_claim(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session)
    old = source_identity(scope, revision_char="a")
    other = source_identity(scope, knowledge_id="knowledge-other", revision_char="c")
    claim, rows = claim_with_evidence(
        kb_session,
        scope,
        predicate="mixed",
        identities=[old, other],
    )
    legacy = ClaimEvidence(
        claim_id=claim.id,
        knowledge_id=old.knowledge_id,
        chunk_id="legacy-chunk",
        quote="legacy",
        page=3,
        authority_level=6,
        doc_role="external",
        extraction_method="llm",
        extracted_at=NOW,
    )
    kb_session.add(legacy)
    kb_session.flush()

    report = revision_service.notify_source_revision(
        kb_session,
        scope,
        source_identity(scope, revision_char="b"),
        observed_at=NOW,
    )

    assert report.stale_count == 1
    assert rows[0].stale_at == NOW
    assert rows[1].stale_at is None
    assert legacy.stale_at is None


def test_t7_notification_does_not_mutate_release_pointer_or_snapshot(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session)
    old = source_identity(scope, revision_char="a")
    claim, _ = claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    rendered_pages = [{"slug": "product", "content": "published"}]
    snapshot = ReleaseSnapshot(
        space_id=scope.space_id,
        label="release-1",
        rendered_pages=rendered_pages,
        published_at=NOW,
        published_by="publisher",
    )
    kb_session.add(snapshot)
    kb_session.flush()
    membership = SnapshotClaim(
        space_id=scope.space_id,
        snapshot_id=snapshot.id,
        claim_id=claim.id,
        revision_no=claim.current_revision,
    )
    pointer = CurrentRelease(
        space_id=scope.space_id,
        id="current",
        snapshot_id=snapshot.id,
    )
    kb_session.add_all([membership, pointer])
    kb_session.flush()

    revision_service.notify_source_revision(
        kb_session,
        scope,
        source_identity(scope, revision_char="b"),
        observed_at=NOW,
    )

    kb_session.refresh(snapshot)
    kb_session.refresh(pointer)
    kb_session.refresh(membership)
    assert snapshot.rendered_pages == rendered_pages
    assert pointer.snapshot_id == snapshot.id
    assert membership.claim_id == claim.id
    assert count_rows(kb_session, ReleaseSnapshot) == 1
    assert count_rows(kb_session, SnapshotClaim) == 1
    assert count_rows(kb_session, CurrentRelease) == 1


def test_t7_stale_write_is_a_scoped_conditional_null_to_timestamp_update(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session)
    old = source_identity(scope, revision_char="a")
    claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    updates: list[str] = []
    bind = kb_session.get_bind()

    def capture_update(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("UPDATE CLAIM_EVIDENCE"):
            updates.append(" ".join(statement.upper().split()))

    event.listen(bind, "before_cursor_execute", capture_update)
    try:
        report = revision_service.notify_source_revision(
            kb_session,
            scope,
            source_identity(scope, revision_char="b"),
            observed_at=NOW,
        )
    finally:
        event.remove(bind, "before_cursor_execute", capture_update)

    assert report.stale_count == 1
    assert len(updates) == 1
    assert "STALE_AT IS NULL" in updates[0]
    assert "CLAIMS.SPACE_ID" in updates[0]
    assert "KNOWLEDGE_ID" in updates[0]


def test_t7_notification_never_overwrites_an_existing_stale_timestamp(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session)
    active = source_identity(scope, revision_char="a")
    prior = source_identity(scope, revision_char="c")
    _, rows = claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[active, prior],
    )
    rows[1].stale_at = EARLIER
    kb_session.flush()

    report = revision_service.notify_source_revision(
        kb_session,
        scope,
        source_identity(scope, revision_char="b"),
        observed_at=NOW,
    )

    assert report.stale_count == 1
    assert rows[0].stale_at == NOW
    assert rows[1].stale_at == EARLIER
