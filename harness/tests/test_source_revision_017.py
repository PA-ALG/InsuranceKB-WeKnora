"""OpenSpec 017 T7: source revision, recompile and scoped retract."""

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from pydantic import ValidationError
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from insurance_harness.compiler.models import PredRecord
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.goldenset.records import Evidence
from insurance_harness.knowledge import (
    MergePolicy,
    import_pred_records,
    retract_source,
)
from insurance_harness.knowledge import source_revision as revision_service
from insurance_harness.knowledge.models import ProposedClaim, SourceImportIdentity
from insurance_harness.knowledge.source_revision import SourceRevisionReport
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    ClaimEvidence,
    Conflict,
    CurrentRelease,
    ReleaseSnapshot,
    SnapshotClaim,
)
from tests.kbhelpers import pred, seed_bound_scope, seed_product

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
EARLIER = datetime(2026, 7, 14, 7, 0, tzinfo=UTC)


def _count(session: Session, table: type) -> int:
    return session.scalar(select(func.count()).select_from(table)) or 0


def _scope(session: Session, suffix: str = "a") -> KnowledgeScope:
    return seed_bound_scope(
        session,
        tenant_id=f"tenant-{suffix}",
        raw_kb_id=f"raw-{suffix}",
        wiki_kb_id=f"wiki-{suffix}",
    )


def _identity(
    scope: KnowledgeScope,
    *,
    knowledge_id: str = "knowledge-1",
    revision_char: str = "a",
) -> SourceImportIdentity:
    return SourceImportIdentity(
        knowledge_id=knowledge_id,
        raw_kb_id=scope.raw_kb_id,
        source_revision=revision_char * 64,
        file_hash=revision_char * 32,
        original_digest=revision_char * 64,
        parser_version="pdfplumber@0.11:text-v1",
    )


def _claim_with_evidence(
    session: Session,
    scope: KnowledgeScope,
    *,
    predicate: str,
    identities: list[SourceImportIdentity],
) -> tuple[Claim, list[ClaimEvidence]]:
    _, version = seed_product(
        session,
        scope=scope,
        code=f"P-{predicate}",
        name=f"Product {predicate}",
    )
    claim = Claim(
        space_id=scope.space_id,
        product_version_id=version.id,
        subject_type="product_version",
        predicate=predicate,
        value_state="present",
        value={"text": predicate},
        status="published",
        confidence=0.9,
        extraction_method="llm",
        schema_version="v1",
        current_revision=1,
        pending_judge=False,
    )
    session.add(claim)
    session.flush()
    rows = [
        ClaimEvidence(
            claim_id=claim.id,
            knowledge_id=identity.knowledge_id,
            chunk_id=None,
            quote=f"{predicate}:{identity.knowledge_id}",
            page=1,
            authority_level=1,
            doc_role="terms",
            extraction_method="llm",
            extracted_at=NOW,
            raw_kb_id=identity.raw_kb_id,
            source_revision=identity.source_revision,
            file_hash=identity.file_hash,
            original_digest=identity.original_digest,
            parser_version=identity.parser_version,
            chunk_hash=None,
            lineage_status="page_only",
            stale_at=None,
        )
        for identity in identities
    ]
    session.add_all(rows)
    session.flush()
    return claim, rows


def _source_record(
    identity: SourceImportIdentity,
    *,
    doc: str = "new.pdf",
) -> PredRecord:
    record = pred(
        "grace_period",
        value="60天",
        doc=doc,
        quote="宽限期为60日",
    )
    return record.model_copy(
        update={
            "evidence": [
                Evidence(
                    page=2,
                    quote="宽限期为60日",
                    **identity.model_dump(mode="python"),
                    lineage_status="page_only",
                )
            ]
        }
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
    scope = _scope(kb_session)
    identity = _identity(scope)
    _, evidence = _claim_with_evidence(
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
    assert _count(kb_session, ChangeSet) == 0


def test_t7_new_revision_marks_only_scoped_matching_source_aware_evidence_stale(
    kb_session: Session,
) -> None:
    scope_a = _scope(kb_session, "a")
    scope_b = _scope(kb_session, "b")
    old_a = _identity(scope_a, revision_char="a")
    other_a = _identity(scope_a, knowledge_id="knowledge-other", revision_char="c")
    old_b = _identity(scope_b, revision_char="a")
    _, rows_a = _claim_with_evidence(
        kb_session,
        scope_a,
        predicate="waiting_period-a",
        identities=[old_a, other_a],
    )
    _, rows_b = _claim_with_evidence(
        kb_session,
        scope_b,
        predicate="waiting_period-b",
        identities=[old_b],
    )
    new_a = _identity(scope_a, revision_char="b")

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
    scope = _scope(kb_session)
    old = _identity(scope, revision_char="a")
    _claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    new = _identity(scope, revision_char="b")

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
    assert _count(kb_session, ChangeSet) == 1


def test_t7_notification_rejects_raw_kb_mismatch_before_query_or_mutation(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    forged = _identity(scope).model_copy(update={"raw_kb_id": "raw-other"})
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
    assert _count(kb_session, ChangeSet) == 0
    assert _count(kb_session, ClaimEvidence) == 0


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
    scope = _scope(kb_session)
    old = _identity(scope, revision_char="a")
    _, evidence = _claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    new = _identity(scope, revision_char="b")
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
    baseline = (_count(kb_session, ChangeSet), _count(kb_session, ChangeItem))
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
    assert (_count(kb_session, ChangeSet), _count(kb_session, ChangeItem)) == baseline


def test_t7_notification_rejects_document_recompile_ambiguity(kb_session: Session) -> None:
    scope = _scope(kb_session)
    old = _identity(scope, revision_char="a")
    _, evidence = _claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    new = _identity(scope, revision_char="b")
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
    assert _count(kb_session, ChangeSet) == 2


@pytest.mark.parametrize(
    "knowledge_ids",
    [None, ["knowledge-other"], ["knowledge-1", "knowledge-other"]],
)
def test_t7_notification_rejects_malformed_recompile_knowledge_ids_without_stale_leak(
    kb_session: Session,
    knowledge_ids: list[str] | None,
) -> None:
    scope = _scope(kb_session)
    old = _identity(scope, revision_char="a")
    _, evidence = _claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    new = _identity(scope, revision_char="b")
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
    assert _count(kb_session, ChangeSet) == 1
    assert _count(kb_session, ChangeItem) == 0


def test_t7_notification_flush_failure_rolls_back_stale_and_changeset(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    old = _identity(scope, revision_char="a")
    _, evidence = _claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    new = _identity(scope, revision_char="b")
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
    assert _count(kb_session, ChangeSet) == 0


def test_t7_duplicate_key_race_rereads_exact_pending_winner(
    kb_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope(kb_session)
    old = _identity(scope, revision_char="a")
    _, evidence = _claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    new = _identity(scope, revision_char="b")

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
    assert _count(kb_session, ChangeSet) == 1
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
    scope = _scope(kb_session)
    old = _identity(scope, revision_char="a")
    _, evidence = _claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    evidence_id = evidence[0].id
    new = _identity(scope, revision_char="b")

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
    assert _count(kb_session, ChangeSet) == 0
    assert _count(kb_session, ChangeItem) == 0


def test_t7_unrelated_integrity_error_is_not_misclassified_as_recompile_race(
    kb_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope(kb_session)
    old = _identity(scope, revision_char="a")
    _, evidence = _claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    evidence_id = evidence[0].id
    new = _identity(scope, revision_char="b")
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
    assert _count(kb_session, ChangeSet) == 1


def test_t7_t6_importer_populates_pending_recompile_without_document_changeset(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    old = _identity(scope, revision_char="a")
    _claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-T7",
        name="Import T7",
    )
    new = _identity(scope, revision_char="b")
    notification = revision_service.notify_source_revision(
        kb_session,
        scope,
        new,
        observed_at=NOW,
    )

    report = import_pred_records(
        kb_session,
        [_source_record(new)],
        scope=scope,
        product_id=product.product_code,
        product_version_id=version.id,
        source_context={
            "space_id": scope.space_id,
            "tenant_id": scope.tenant_id,
            "raw_kb_id": scope.raw_kb_id,
            "documents": {"new.pdf": new.model_dump(mode="python")},
        },
        policy=MergePolicy(auto_apply_add=True),
    )

    assert report.change_set_id == notification.change_set_id
    assert report.partitions[0].source_kind == "recompile"
    change_sets = list(kb_session.scalars(select(ChangeSet)))
    assert len(change_sets) == 1 and change_sets[0].source_kind == "recompile"
    assert _count(kb_session, ChangeItem) == 1


@pytest.mark.parametrize("status", ["pending", "applied"])
@pytest.mark.parametrize(
    "knowledge_ids",
    [None, ["knowledge-other"], ["knowledge-1", "knowledge-other"]],
)
def test_t7_importer_rejects_malformed_source_changeset_knowledge_ids_before_writes(
    kb_session: Session,
    status: str,
    knowledge_ids: list[str] | None,
) -> None:
    scope = _scope(kb_session)
    product, version = seed_product(
        kb_session,
        scope=scope,
        code=f"IMPORT-T7-MALFORMED-{status}-{len(knowledge_ids or [])}",
        name="Import T7 malformed source ChangeSet",
    )
    identity = _identity(scope, revision_char="b")
    blocked = ChangeSet(
        space_id=scope.space_id,
        source_kind="recompile" if status == "pending" else "document",
        knowledge_ids=knowledge_ids,
        external_record_id=identity.knowledge_id,
        source_revision=identity.source_revision,
        status=status,
        created_by="test",
    )
    kb_session.add(blocked)
    kb_session.flush()

    with pytest.raises(ScopeViolation, match="aggregate mismatch"):
        import_pred_records(
            kb_session,
            [_source_record(identity)],
            scope=scope,
            product_id=product.product_code,
            product_version_id=version.id,
            source_context={
                "space_id": scope.space_id,
                "tenant_id": scope.tenant_id,
                "raw_kb_id": scope.raw_kb_id,
                "documents": {
                    "new.pdf": identity.model_dump(mode="python")
                },
            },
            policy=MergePolicy(auto_apply_add=True),
        )

    kb_session.commit()
    assert _count(kb_session, ChangeSet) == 1
    assert _count(kb_session, ChangeItem) == 0
    assert _count(kb_session, Claim) == 0
    assert _count(kb_session, ClaimEvidence) == 0
    assert kb_session.scalar(select(func.count()).select_from(ChangeSet)) == 1


def test_t7_importer_rejects_applied_duplicate_with_cross_scope_item_claim(
    kb_session: Session,
) -> None:
    scope_a = _scope(kb_session, "duplicate-item-a")
    scope_b = _scope(kb_session, "duplicate-item-b")
    product_a, version_a = seed_product(
        kb_session,
        scope=scope_a,
        code="IMPORT-T7-DUPLICATE-ITEM-A",
        name="Import T7 duplicate item A",
    )
    claim_b, _ = _claim_with_evidence(
        kb_session,
        scope_b,
        predicate="cross_scope_duplicate_item",
        identities=[_identity(scope_b, revision_char="c")],
    )
    identity = _identity(scope_a, revision_char="b")
    applied = ChangeSet(
        space_id=scope_a.space_id,
        source_kind="document",
        knowledge_ids=[identity.knowledge_id],
        external_record_id=identity.knowledge_id,
        source_revision=identity.source_revision,
        status="applied",
        created_by="test",
    )
    kb_session.add(applied)
    kb_session.flush()
    kb_session.add(
        ChangeItem(
            change_set_id=applied.id,
            action="add",
            claim_id=claim_b.id,
            proposed={"claim": {"space_id": scope_b.space_id}},
            decision="auto_applied",
        )
    )
    kb_session.flush()
    baseline = {
        table: _count(kb_session, table)
        for table in (ChangeSet, ChangeItem, Claim, ClaimEvidence)
    }

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        import_pred_records(
            kb_session,
            [_source_record(identity)],
            scope=scope_a,
            product_id=product_a.product_code,
            product_version_id=version_a.id,
            source_context={
                "space_id": scope_a.space_id,
                "tenant_id": scope_a.tenant_id,
                "raw_kb_id": scope_a.raw_kb_id,
                "documents": {"new.pdf": identity.model_dump(mode="python")},
            },
            policy=MergePolicy(auto_apply_add=True),
        )

    kb_session.commit()
    assert {
        table: _count(kb_session, table) for table in baseline
    } == baseline
    assert kb_session.scalar(select(func.count()).select_from(ChangeSet)) == 1


def test_t7_importer_rejects_applied_duplicate_with_cross_scope_conflict_refs(
    kb_session: Session,
) -> None:
    scope_a = _scope(kb_session, "duplicate-conflict-a")
    scope_b = _scope(kb_session, "duplicate-conflict-b")
    product_a, version_a = seed_product(
        kb_session,
        scope=scope_a,
        code="IMPORT-T7-DUPLICATE-CONFLICT-A",
        name="Import T7 duplicate conflict A",
    )
    claim_b, _ = _claim_with_evidence(
        kb_session,
        scope_b,
        predicate="cross_scope_duplicate_conflict",
        identities=[_identity(scope_b, revision_char="c")],
    )
    assert claim_b.product_version_id is not None
    proposed = ProposedClaim(
        space_id=scope_b.space_id,
        product_version_id=claim_b.product_version_id,
        predicate=claim_b.predicate,
        field_name=claim_b.predicate,
        value_state="present",
        value="different value",
        confidence=0.8,
        extraction_method="llm",
        schema_version="v1",
        evidence=[],
    ).model_dump(mode="json")
    identity = _identity(scope_a, revision_char="b")
    applied = ChangeSet(
        space_id=scope_a.space_id,
        source_kind="document",
        knowledge_ids=[identity.knowledge_id],
        external_record_id=identity.knowledge_id,
        source_revision=identity.source_revision,
        status="applied",
        created_by="test",
    )
    kb_session.add(applied)
    kb_session.flush()
    item = ChangeItem(
        change_set_id=applied.id,
        action="conflict",
        claim_id=None,
        proposed={"claim": proposed, "existing_claim_id": claim_b.id},
        decision="auto_applied",
        decision_basis={"authority_cmp": "existing wins"},
    )
    kb_session.add(item)
    kb_session.flush()
    kb_session.add(
        Conflict(
            change_item_id=item.id,
            existing_claim_id=claim_b.id,
            proposed=proposed,
            decision_basis={"authority_cmp": "existing wins"},
            status="resolved",
        )
    )
    kb_session.flush()
    baseline = {
        table: _count(kb_session, table)
        for table in (ChangeSet, ChangeItem, Conflict, Claim, ClaimEvidence)
    }

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        import_pred_records(
            kb_session,
            [_source_record(identity)],
            scope=scope_a,
            product_id=product_a.product_code,
            product_version_id=version_a.id,
            source_context={
                "space_id": scope_a.space_id,
                "tenant_id": scope_a.tenant_id,
                "raw_kb_id": scope_a.raw_kb_id,
                "documents": {"new.pdf": identity.model_dump(mode="python")},
            },
            policy=MergePolicy(auto_apply_add=True),
        )

    kb_session.commit()
    assert {
        table: _count(kb_session, table) for table in baseline
    } == baseline
    assert kb_session.scalar(select(func.count()).select_from(ChangeSet)) == 1


def test_t7_importer_accepts_applied_duplicate_with_scoped_winner_existing_conflict(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session, "duplicate-valid-conflict")
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-T7-DUPLICATE-VALID-CONFLICT",
        name="Import T7 valid duplicate conflict",
    )
    existing = Claim(
        space_id=scope.space_id,
        product_version_id=version.id,
        subject_type="product_version",
        predicate="grace_period",
        value_state="present",
        value={"text": "60天"},
        status="published",
        confidence=0.9,
        extraction_method="llm",
        schema_version="v1",
        current_revision=1,
        pending_judge=False,
    )
    kb_session.add(existing)
    kb_session.flush()
    proposed = ProposedClaim(
        space_id=scope.space_id,
        product_version_id=version.id,
        predicate=existing.predicate,
        field_name=existing.predicate,
        value_state="present",
        value="90天",
        confidence=0.8,
        extraction_method="llm",
        schema_version="v1",
        evidence=[],
    ).model_dump(mode="json")
    identity = _identity(scope, revision_char="b")
    applied = ChangeSet(
        space_id=scope.space_id,
        source_kind="document",
        knowledge_ids=[identity.knowledge_id],
        external_record_id=identity.knowledge_id,
        source_revision=identity.source_revision,
        status="applied",
        created_by="test",
    )
    kb_session.add(applied)
    kb_session.flush()
    item = ChangeItem(
        change_set_id=applied.id,
        action="conflict",
        claim_id=None,
        proposed={"claim": proposed, "existing_claim_id": existing.id},
        decision="auto_applied",
        decision_basis={"authority_cmp": "existing wins"},
    )
    kb_session.add(item)
    kb_session.flush()
    kb_session.add(
        Conflict(
            change_item_id=item.id,
            existing_claim_id=existing.id,
            proposed=proposed,
            decision_basis={"authority_cmp": "existing wins"},
            status="resolved",
        )
    )
    kb_session.flush()
    baseline = {
        table: _count(kb_session, table)
        for table in (ChangeSet, ChangeItem, Conflict, Claim, ClaimEvidence)
    }

    report = import_pred_records(
        kb_session,
        [_source_record(identity)],
        scope=scope,
        product_id=product.product_code,
        product_version_id=version.id,
        source_context={
            "space_id": scope.space_id,
            "tenant_id": scope.tenant_id,
            "raw_kb_id": scope.raw_kb_id,
            "documents": {"new.pdf": identity.model_dump(mode="python")},
        },
        policy=MergePolicy(auto_apply_add=True),
    )

    assert report.duplicate_batch is True
    assert report.change_set_id == applied.id
    assert {
        table: _count(kb_session, table) for table in baseline
    } == baseline
    assert kb_session.scalar(select(func.count()).select_from(ChangeSet)) == 1


def test_t7_notification_and_import_failure_roll_back_as_one_caller_transaction(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    old = _identity(scope, revision_char="a")
    _, evidence = _claim_with_evidence(
        kb_session,
        scope,
        predicate="waiting_period",
        identities=[old],
    )
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-T7-ROLLBACK",
        name="Import T7 rollback",
    )
    new = _identity(scope, revision_char="b")
    evidence_id = evidence[0].id

    with pytest.raises(ScopeViolation, match="mismatch"):
        with kb_session.begin_nested():
            revision_service.notify_source_revision(
                kb_session,
                scope,
                new,
                observed_at=NOW,
            )
            import_pred_records(
                kb_session,
                [_source_record(new)],
                scope=scope,
                product_id=product.product_code,
                product_version_id=version.id,
                source_context={
                    "space_id": scope.space_id,
                    "tenant_id": scope.tenant_id,
                    "raw_kb_id": "raw-forged",
                    "documents": {
                        "new.pdf": new.model_dump(mode="python")
                    },
                },
                policy=MergePolicy(auto_apply_add=True),
            )

    kb_session.commit()
    restored = kb_session.get(ClaimEvidence, evidence_id)
    assert restored is not None and restored.stale_at is None
    assert _count(kb_session, ChangeSet) == 0
    assert _count(kb_session, ChangeItem) == 0


def test_t7_empty_tombstone_rejects_late_import_of_the_same_source_revision(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-T7-TOMBSTONE",
        name="Import T7 tombstone",
    )
    identity = _identity(scope, revision_char="a")
    tombstone = retract_source(kb_session, scope, identity)

    with pytest.raises(ScopeViolation, match="tombstone"):
        import_pred_records(
            kb_session,
            [_source_record(identity)],
            scope=scope,
            product_id=product.product_code,
            product_version_id=version.id,
            source_context={
                "space_id": scope.space_id,
                "tenant_id": scope.tenant_id,
                "raw_kb_id": scope.raw_kb_id,
                "documents": {
                    "new.pdf": identity.model_dump(mode="python")
                },
            },
            policy=MergePolicy(auto_apply_add=True),
        )

    kb_session.commit()
    assert _count(kb_session, ChangeSet) == 1
    assert kb_session.get(ChangeSet, tombstone.change_set_id) is not None
    assert _count(kb_session, ChangeItem) == 0
    assert _count(kb_session, Claim) == 0
    assert _count(kb_session, ClaimEvidence) == 0


def test_t7_legacy_retract_cannot_delete_a_normal_source_aware_import(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-T7-LEGACY-CONFLICT",
        name="Import T7 legacy conflict",
    )
    identity = _identity(scope, revision_char="a")
    imported = import_pred_records(
        kb_session,
        [_source_record(identity)],
        scope=scope,
        product_id=product.product_code,
        product_version_id=version.id,
        source_context={
            "space_id": scope.space_id,
            "tenant_id": scope.tenant_id,
            "raw_kb_id": scope.raw_kb_id,
            "documents": {
                "new.pdf": identity.model_dump(mode="python")
            },
        },
        policy=MergePolicy(auto_apply_add=True),
    )
    baseline = {
        table: _count(kb_session, table)
        for table in (ChangeSet, ChangeItem, Claim, ClaimEvidence)
    }

    with pytest.raises(ScopeViolation, match="source mode conflict"):
        retract_source(
            kb_session,
            scope,
            identity.knowledge_id,
            legacy_replay=True,
        )

    kb_session.commit()
    assert {
        table: _count(kb_session, table) for table in baseline
    } == baseline
    change_set = kb_session.get(ChangeSet, imported.change_set_id)
    assert change_set is not None and change_set.status == "applied"
    assert _count(kb_session, ClaimEvidence) == 1
    assert kb_session.scalar(select(func.count()).select_from(Claim)) == 1


@pytest.mark.parametrize(
    "corruption",
    [
        "pending",
        "rejected",
        "wrong_knowledge_ids",
        "wrong_action",
        "wrong_proposed_knowledge",
        "foreign_claim",
        "wrong_decision",
        "proposed_list",
        "proposed_string",
        "proposed_null",
        "removed_missing",
        "removed_bool",
        "removed_zero",
        "removed_negative",
        "removed_string",
        "duplicate_claim",
    ],
)
def test_t7_late_import_fails_closed_on_malformed_source_tombstone(
    kb_session: Session,
    corruption: str,
) -> None:
    scope = _scope(kb_session, "tombstone-a")
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-T7-TOMBSTONE-MALFORMED",
        name="Import T7 malformed tombstone",
    )
    identity = _identity(scope, revision_char="a")
    report = retract_source(kb_session, scope, identity)
    tombstone = kb_session.get(ChangeSet, report.change_set_id)
    assert tombstone is not None
    if corruption in {"pending", "rejected"}:
        tombstone.status = corruption
    elif corruption == "wrong_knowledge_ids":
        tombstone.knowledge_ids = ["knowledge-other"]
    else:
        claim_scope = scope
        claim_version = version
        if corruption == "foreign_claim":
            claim_scope = _scope(kb_session, "tombstone-b")
            _, claim_version = seed_product(
                kb_session,
                scope=claim_scope,
                code="IMPORT-T7-TOMBSTONE-FOREIGN",
                name="Import T7 foreign tombstone",
            )
        claim = Claim(
            space_id=claim_scope.space_id,
            product_version_id=claim_version.id,
            subject_type="product_version",
            predicate=f"tombstone-{corruption}",
            value_state="present",
            value={"text": corruption},
            status="draft",
            confidence=0.5,
            extraction_method="llm",
            schema_version="v1",
            current_revision=0,
            pending_judge=False,
        )
        kb_session.add(claim)
        kb_session.flush()
        proposed: object = {
            "knowledge_id": (
                "knowledge-other"
                if corruption == "wrong_proposed_knowledge"
                else identity.knowledge_id
            ),
            "removed_evidence": 1,
        }
        if corruption == "proposed_list":
            proposed = ["not-an-object"]
        elif corruption == "proposed_string":
            proposed = "not-an-object"
        elif corruption == "proposed_null":
            proposed = None
        elif corruption == "removed_missing":
            proposed = {"knowledge_id": identity.knowledge_id}
        elif corruption == "removed_bool":
            proposed = {
                "knowledge_id": identity.knowledge_id,
                "removed_evidence": True,
            }
        elif corruption == "removed_zero":
            proposed = {
                "knowledge_id": identity.knowledge_id,
                "removed_evidence": 0,
            }
        elif corruption == "removed_negative":
            proposed = {
                "knowledge_id": identity.knowledge_id,
                "removed_evidence": -1,
            }
        elif corruption == "removed_string":
            proposed = {
                "knowledge_id": identity.knowledge_id,
                "removed_evidence": "1",
            }
        item = ChangeItem(
            change_set_id=tombstone.id,
            action="add" if corruption == "wrong_action" else "retract",
            claim_id=claim.id,
            proposed=cast(dict[str, Any], proposed),
            decision=(
                "needs_review"
                if corruption == "wrong_decision"
                else "auto_applied"
            ),
        )
        kb_session.add(item)
        if corruption == "duplicate_claim":
            kb_session.add(
                ChangeItem(
                    change_set_id=tombstone.id,
                    action="retract",
                    claim_id=claim.id,
                    proposed={
                        "knowledge_id": identity.knowledge_id,
                        "removed_evidence": 1,
                    },
                    decision="auto_applied",
                )
            )
    kb_session.flush()
    baseline = {
        table: _count(kb_session, table)
        for table in (ChangeSet, ChangeItem, Claim, ClaimEvidence)
    }

    with pytest.raises(ScopeViolation, match="source tombstone is invalid"):
        retract_source(kb_session, scope, identity)

    with pytest.raises(ScopeViolation, match="source tombstone is invalid"):
        import_pred_records(
            kb_session,
            [_source_record(identity)],
            scope=scope,
            product_id=product.product_code,
            product_version_id=version.id,
            source_context={
                "space_id": scope.space_id,
                "tenant_id": scope.tenant_id,
                "raw_kb_id": scope.raw_kb_id,
                "documents": {
                    "new.pdf": identity.model_dump(mode="python")
                },
            },
            policy=MergePolicy(auto_apply_add=True),
        )

    kb_session.commit()
    assert {
        table: _count(kb_session, table) for table in baseline
    } == baseline
    assert kb_session.scalar(select(func.count()).select_from(ChangeSet)) == 1


def test_t7_notification_ignores_legacy_and_other_source_rows_on_mixed_claim(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    old = _identity(scope, revision_char="a")
    other = _identity(scope, knowledge_id="knowledge-other", revision_char="c")
    claim, rows = _claim_with_evidence(
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
        _identity(scope, revision_char="b"),
        observed_at=NOW,
    )

    assert report.stale_count == 1
    assert rows[0].stale_at == NOW
    assert rows[1].stale_at is None
    assert legacy.stale_at is None


def test_t7_notification_does_not_mutate_release_pointer_or_snapshot(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    old = _identity(scope, revision_char="a")
    claim, _ = _claim_with_evidence(
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
        _identity(scope, revision_char="b"),
        observed_at=NOW,
    )

    kb_session.refresh(snapshot)
    kb_session.refresh(pointer)
    kb_session.refresh(membership)
    assert snapshot.rendered_pages == rendered_pages
    assert pointer.snapshot_id == snapshot.id
    assert membership.claim_id == claim.id
    assert _count(kb_session, ReleaseSnapshot) == 1
    assert _count(kb_session, SnapshotClaim) == 1
    assert _count(kb_session, CurrentRelease) == 1


def test_t7_stale_write_is_a_scoped_conditional_null_to_timestamp_update(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session)
    old = _identity(scope, revision_char="a")
    _claim_with_evidence(
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
            _identity(scope, revision_char="b"),
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
    scope = _scope(kb_session)
    active = _identity(scope, revision_char="a")
    prior = _identity(scope, revision_char="c")
    _, rows = _claim_with_evidence(
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
        _identity(scope, revision_char="b"),
        observed_at=NOW,
    )

    assert report.stale_count == 1
    assert rows[0].stale_at == NOW
    assert rows[1].stale_at == EARLIER
