"""Source revision notification and race contracts."""

from typing import Any, cast

import pytest
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from insurance_harness.db.models import InsuranceProduct, ProductVersion
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.knowledge import MergePolicy, import_pred_records
from insurance_harness.knowledge import source_revision as revision_service
from insurance_harness.knowledge.models import SourceImportContext, SourceImportIdentity
from insurance_harness.knowledge.source_revision import SourceRevisionReport
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    ClaimEvidence,
    ClaimRevision,
    CurrentRelease,
    ReleaseSnapshot,
    SnapshotClaim,
    SnapshotFact,
)
from insurance_harness.sources import ProcessedAtOrdering
from tests.kbhelpers import pred, seed_product
from tests.support.source_revision import (
    EARLIER,
    NOW,
    bound_scope,
    claim_with_evidence,
    count_rows,
    source_identity,
)


def test_l1_source_identity_fixture_keeps_default_a_before_b(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session, "fixture-ordering")
    revision_a = source_identity(scope, revision_char="a")
    revision_b = source_identity(scope, revision_char="b")

    assert isinstance(revision_a.ordering, ProcessedAtOrdering)
    assert isinstance(revision_b.ordering, ProcessedAtOrdering)
    assert revision_a.ordering.value < revision_b.ordering.value


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


@pytest.mark.parametrize("source_kind", ["document", "recompile"])
def test_rh2_1_applied_unknown_only_revision_is_same_revision_without_evidence(
    kb_session: Session,
    source_kind: str,
) -> None:
    scope = bound_scope(kb_session, f"rh2-1-{source_kind}")
    product, version = seed_product(
        kb_session,
        scope=scope,
        code=f"RH2-1-{source_kind}",
        name=f"RH2.1 {source_kind}",
    )
    identity = source_identity(scope, revision_char="a")
    document_name = f"unknown-{source_kind}.pdf"
    context = SourceImportContext(
        space_id=scope.space_id,
        tenant_id=scope.tenant_id,
        raw_kb_id=scope.raw_kb_id,
        documents={document_name: identity},
    )
    record = pred(
        "unknown_only_revision",
        value=None,
        tri_state="unknown",
        doc=document_name,
    )
    assert record.evidence == []

    if source_kind == "recompile":
        pending = revision_service.notify_source_revision(
            kb_session,
            scope,
            identity,
            observed_at=NOW,
        )
        assert pending.created is True
        assert pending.change_set_id is not None

    imported = import_pred_records(
        kb_session,
        [record],
        scope=scope,
        product_id=product.product_code,
        product_version_id=version.id,
        source_context=context,
        policy=MergePolicy(auto_apply_add=True),
    )

    aggregate = kb_session.get(ChangeSet, imported.change_set_id)
    assert aggregate is not None
    assert aggregate.source_kind == source_kind
    assert aggregate.status == "applied"
    items = list(
        kb_session.scalars(
            select(ChangeItem).where(ChangeItem.change_set_id == aggregate.id)
        )
    )
    assert len(items) == 1
    assert items[0].proposed.get("mode") == "unknown_placeholder"
    placeholder = kb_session.get(Claim, items[0].claim_id)
    assert placeholder is not None
    assert placeholder.value_state == "unknown"
    assert placeholder.status == "draft"
    assert count_rows(kb_session, ClaimEvidence) == 0
    baseline_change_sets = count_rows(kb_session, ChangeSet)

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
    assert count_rows(kb_session, ChangeSet) == baseline_change_sets


def test_rh2_2_zero_evidence_new_revision_creates_then_reuses_one_recompile(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session, "rh2-2-new-revision")
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="RH2-2-NEW-REVISION",
        name="RH2.2 new revision",
    )
    revision_a = source_identity(scope, revision_char="a")
    document_name = "unknown-revision-a.pdf"
    imported_a = import_pred_records(
        kb_session,
        [
            pred(
                "unknown_only_revision",
                value=None,
                tri_state="unknown",
                doc=document_name,
            )
        ],
        scope=scope,
        product_id=product.product_code,
        product_version_id=version.id,
        source_context=SourceImportContext(
            space_id=scope.space_id,
            tenant_id=scope.tenant_id,
            raw_kb_id=scope.raw_kb_id,
            documents={document_name: revision_a},
        ),
        policy=MergePolicy(auto_apply_add=True),
    )
    applied_a = kb_session.get(ChangeSet, imported_a.change_set_id)
    assert applied_a is not None
    assert applied_a.status == "applied"
    assert applied_a.source_revision == revision_a.source_revision
    assert count_rows(kb_session, ClaimEvidence) == 0

    revision_b = source_identity(scope, revision_char="b", ordering_offset=1)
    first = revision_service.notify_source_revision(
        kb_session,
        scope,
        revision_b,
        observed_at=NOW,
    )
    second = revision_service.notify_source_revision(
        kb_session,
        scope,
        revision_b,
        observed_at=NOW,
    )

    assert first.created is True and first.reused is False
    assert second.created is False and second.reused is True
    assert first.stale_count == second.stale_count == 0
    assert first.change_set_id == second.change_set_id
    pending_b = list(
        kb_session.scalars(
            select(ChangeSet).where(
                ChangeSet.space_id == scope.space_id,
                ChangeSet.source_kind == "recompile",
                ChangeSet.external_record_id == revision_b.knowledge_id,
                ChangeSet.source_revision == revision_b.source_revision,
                ChangeSet.status == "pending",
            )
        )
    )
    assert len(pending_b) == 1
    assert pending_b[0].id == first.change_set_id
    assert count_rows(kb_session, ChangeSet) == 2


@pytest.mark.parametrize(
    "corruption",
    [
        "malformed_parent",
        "malformed_child",
        "conflicting_document_recompile",
        "illegal_status",
        "nonempty_pending",
        "illegal_action",
        "applied_needs_review",
        "non_object_proposed",
    ],
)
def test_rh2_2_zero_evidence_malformed_or_conflicting_aggregate_fails_closed_without_mutation(
    kb_session: Session,
    corruption: str,
) -> None:
    scope = bound_scope(kb_session, f"rh2-2-fail-closed-{corruption}")
    control_identity = source_identity(
        scope,
        knowledge_id="knowledge-control",
        revision_char="c",
    )
    claim_with_evidence(
        kb_session,
        scope,
        predicate=f"control_{corruption}",
        identities=[control_identity],
    )
    product, version = seed_product(
        kb_session,
        scope=scope,
        code=f"RH2-2-FAIL-{corruption}",
        name=f"RH2.2 fail closed {corruption}",
    )
    revision_a = source_identity(scope, revision_char="a")
    document_name = f"unknown-{corruption}.pdf"
    import_pred_records(
        kb_session,
        [
            pred(
                "unknown_only_revision",
                value=None,
                tri_state="unknown",
                doc=document_name,
            )
        ],
        scope=scope,
        product_id=product.product_code,
        product_version_id=version.id,
        source_context=SourceImportContext(
            space_id=scope.space_id,
            tenant_id=scope.tenant_id,
            raw_kb_id=scope.raw_kb_id,
            documents={document_name: revision_a},
        ),
        policy=MergePolicy(auto_apply_add=True),
    )
    revision_b = source_identity(scope, revision_char="b", ordering_offset=1)

    def blocked_change_set(
        source_kind: str,
        status: str,
        *,
        knowledge_ids: list[str] | None = None,
    ) -> ChangeSet:
        return ChangeSet(
            space_id=scope.space_id,
            source_kind=source_kind,
            knowledge_ids=(
                [revision_b.knowledge_id]
                if knowledge_ids is None
                else knowledge_ids
            ),
            external_record_id=revision_b.knowledge_id,
            source_revision=revision_b.source_revision,
            status=status,
            created_by="test",
        )

    if corruption == "malformed_parent":
        kb_session.add(
            blocked_change_set(
                "recompile",
                "pending",
                knowledge_ids=["knowledge-other"],
            )
        )
    elif corruption == "malformed_child":
        blocked = blocked_change_set("document", "applied")
        kb_session.add(blocked)
        kb_session.flush()
        placeholder = kb_session.scalar(
            select(Claim).where(
                Claim.space_id == scope.space_id,
                Claim.predicate == "unknown_only_revision",
            )
        )
        assert placeholder is not None
        kb_session.add(
            ChangeItem(
                change_set_id=blocked.id,
                action="add",
                claim_id=placeholder.id,
                proposed={"claim": {"space_id": scope.space_id}},
                decision="auto_applied",
            )
        )
    elif corruption == "conflicting_document_recompile":
        kb_session.add_all(
            [
                blocked_change_set("document", "applied"),
                blocked_change_set("recompile", "pending"),
            ]
        )
    elif corruption == "illegal_status":
        kb_session.add(blocked_change_set("recompile", "rejected"))
    elif corruption in {"illegal_action", "applied_needs_review"}:
        blocked = blocked_change_set("document", "applied")
        kb_session.add(blocked)
        kb_session.flush()
        source_item = kb_session.scalar(
            select(ChangeItem)
            .join(ChangeSet, ChangeSet.id == ChangeItem.change_set_id)
            .where(
                ChangeSet.space_id == scope.space_id,
                ChangeSet.external_record_id == revision_a.knowledge_id,
                ChangeSet.source_revision == revision_a.source_revision,
            )
        )
        assert source_item is not None
        assert source_item.claim_id is not None
        kb_session.add(
            ChangeItem(
                change_set_id=blocked.id,
                action=(
                    "illegal_action" if corruption == "illegal_action" else "add"
                ),
                claim_id=source_item.claim_id,
                proposed=dict(source_item.proposed),
                decision=(
                    "auto_applied"
                    if corruption == "illegal_action"
                    else "needs_review"
                ),
            )
        )
    elif corruption == "non_object_proposed":
        blocked = blocked_change_set("document", "applied")
        kb_session.add(blocked)
        kb_session.flush()
        kb_session.add(
            ChangeItem(
                change_set_id=blocked.id,
                action="add",
                proposed=cast(dict[str, Any], []),
                decision="auto_applied",
            )
        )
    else:
        blocked = blocked_change_set("recompile", "pending")
        kb_session.add(blocked)
        kb_session.flush()
        kb_session.add(
            ChangeItem(
                change_set_id=blocked.id,
                action="add",
                proposed={"interrupted": True},
                decision="needs_review",
            )
        )
    kb_session.flush()
    baseline_counts = {
        table: count_rows(kb_session, table)
        for table in (ChangeSet, ChangeItem, Claim, ClaimEvidence)
    }
    baseline_stale = [
        (row.id, row.stale_at)
        for row in kb_session.scalars(
            select(ClaimEvidence).order_by(ClaimEvidence.id)
        )
    ]

    with pytest.raises(ScopeViolation):
        revision_service.notify_source_revision(
            kb_session,
            scope,
            revision_b,
            observed_at=NOW,
        )

    kb_session.commit()
    assert {
        table: count_rows(kb_session, table) for table in baseline_counts
    } == baseline_counts
    assert [
        (row.id, row.stale_at)
        for row in kb_session.scalars(
            select(ClaimEvidence).order_by(ClaimEvidence.id)
        )
    ] == baseline_stale
    assert count_rows(kb_session, ChangeSet) == baseline_counts[ChangeSet]


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
    new_a = source_identity(scope_a, revision_char="b", ordering_offset=1)

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
    ) == (
        scope_a.space_id,
        "recompile",
        "knowledge-1",
        new_a.source_revision,
        "pending",
    )


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
    new = source_identity(scope, revision_char="b", ordering_offset=1)

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
    new = source_identity(scope, revision_char="b", ordering_offset=1)
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
    new = source_identity(scope, revision_char="b", ordering_offset=1)
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
    new = source_identity(scope, revision_char="b", ordering_offset=1)
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
    new = source_identity(scope, revision_char="b", ordering_offset=1)
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
    new = source_identity(scope, revision_char="b", ordering_offset=1)

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
    new = source_identity(scope, revision_char="b", ordering_offset=1)

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
    new = source_identity(scope, revision_char="b", ordering_offset=1)
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
        source_identity(scope, revision_char="b", ordering_offset=1),
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
    assert claim.product_version_id is not None
    version = kb_session.get(ProductVersion, claim.product_version_id)
    assert version is not None
    product = kb_session.get(InsuranceProduct, version.product_id)
    assert product is not None
    kb_session.add(
        ClaimRevision(
            claim_id=claim.id,
            revision_no=claim.current_revision,
            before=None,
            after={"value": claim.value},
            actor="test",
        )
    )
    rendered_pages = [{"slug": "product", "content": "published"}]
    snapshot = ReleaseSnapshot(
        space_id=scope.space_id,
        label="release-1",
        rendered_pages=rendered_pages,
        status="building",
        read_model_version=1,
        projection_frozen_at=None,
        published_at=None,
        published_by="publisher",
    )
    kb_session.add(snapshot)
    kb_session.flush()
    fact = SnapshotFact(
        space_id=scope.space_id,
        snapshot_id=snapshot.id,
        claim_id=claim.id,
        revision_no=claim.current_revision,
        product_id=product.id,
        product_version_id=version.id,
        product_code=product.product_code,
        product_name=product.canonical_name,
        version_label=version.version_label,
        predicate=claim.predicate,
        field_name=claim.predicate,
        field_group="terms",
        value_state="present",
        value=dict(claim.value or {}),
        confidence=claim.confidence,
        schema_version=claim.schema_version,
        evidence=[{"knowledge_id": old.knowledge_id}],
    )
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
    kb_session.add_all([fact, membership])
    kb_session.flush()
    snapshot.status = "published"
    snapshot.projection_frozen_at = NOW
    snapshot.published_at = NOW
    kb_session.flush()
    kb_session.add(pointer)
    kb_session.flush()

    before_fingerprint = (
        snapshot.id,
        snapshot.status,
        tuple((page["slug"], page["content"]) for page in rendered_pages),
        fact.id,
        fact.claim_id,
        fact.revision_no,
        fact.value,
        tuple(item["knowledge_id"] for item in fact.evidence),
        membership.claim_id,
        membership.revision_no,
        pointer.snapshot_id,
    )

    revision_service.notify_source_revision(
        kb_session,
        scope,
        source_identity(scope, revision_char="b", ordering_offset=1),
        observed_at=NOW,
    )

    kb_session.refresh(snapshot)
    kb_session.refresh(pointer)
    kb_session.refresh(membership)
    kb_session.refresh(fact)
    after_fingerprint = (
        snapshot.id,
        snapshot.status,
        tuple(
            (page["slug"], page["content"])
            for page in (snapshot.rendered_pages or [])
        ),
        fact.id,
        fact.claim_id,
        fact.revision_no,
        fact.value,
        tuple(item["knowledge_id"] for item in fact.evidence),
        membership.claim_id,
        membership.revision_no,
        pointer.snapshot_id,
    )
    assert after_fingerprint == before_fingerprint
    assert snapshot.rendered_pages == rendered_pages
    assert pointer.snapshot_id == snapshot.id
    assert membership.claim_id == claim.id
    assert count_rows(kb_session, ReleaseSnapshot) == 1
    assert count_rows(kb_session, SnapshotClaim) == 1
    assert count_rows(kb_session, SnapshotFact) == 1
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
            source_identity(scope, revision_char="b", ordering_offset=1),
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
    active = source_identity(scope, revision_char="a", ordering_offset=1)
    prior = source_identity(scope, revision_char="c", ordering_offset=0)
    incoming = source_identity(scope, revision_char="b", ordering_offset=2)
    assert isinstance(active.ordering, ProcessedAtOrdering)
    assert isinstance(prior.ordering, ProcessedAtOrdering)
    assert isinstance(incoming.ordering, ProcessedAtOrdering)
    assert prior.ordering.value < active.ordering.value < incoming.ordering.value
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
        incoming,
        observed_at=NOW,
    )

    assert report.stale_count == 1
    assert rows[0].stale_at == NOW
    assert rows[1].stale_at == EARLIER
