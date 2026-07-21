"""Source-aware delete lifecycle contracts for OpenSpec 021 L3/L4."""

from typing import Literal

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from insurance_harness.db.scope import ScopeViolation
from insurance_harness.knowledge import MergePolicy, import_pred_records, retract_source
from insurance_harness.knowledge import source_lifecycle as lifecycle_service
from insurance_harness.knowledge import source_revision as revision_service
from insurance_harness.knowledge.snapshots import SnapshotFactView
from insurance_harness.knowledge.source_keys import derive_retract_event_key
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    ClaimEvidence,
    ClaimRevision,
    CurrentRelease,
    ReleaseSnapshot,
    ReviewItem,
    SnapshotFact,
    SourceEvent,
    SourceHead,
    SourceLifecycleBackfillIssue,
)
from tests.kbhelpers import allow_all_gate
from tests.support.release_018 import (
    persist_release_snapshot,
    release_claim,
    release_product,
    release_scope,
)
from tests.support.source_revision import (
    bound_scope,
    claim_with_evidence,
    source_identity,
    source_record,
)

_GATE, _FP = allow_all_gate()


def _count(session: Session, table: type[object]) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)


def _tombstone(
    session: Session,
    *,
    space_id: str,
    knowledge_id: str,
    event_revision: str,
) -> ChangeSet | None:
    return session.scalar(
        select(ChangeSet).where(
            ChangeSet.space_id == space_id,
            ChangeSet.source_kind == "document",
            ChangeSet.external_record_id == knowledge_id,
            ChangeSet.source_revision
            == derive_retract_event_key(knowledge_id, event_revision),
        )
    )


def test_l3_delete_first_event_without_evidence_creates_empty_linked_tombstone(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session, "021-delete-first")
    incoming = source_identity(scope, revision_char="a")

    report = retract_source(kb_session, scope, incoming)

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
    tombstone = _tombstone(
        kb_session,
        space_id=scope.space_id,
        knowledge_id=incoming.knowledge_id,
        event_revision=incoming.source_revision,
    )
    assert report.actions == {}
    assert head is not None
    assert head.state == "deleted" and head.head_revision == incoming.source_revision
    assert tombstone is not None and tombstone.status == "applied"
    assert report.change_set_id == tombstone.id
    assert _count(kb_session, ChangeSet) == 1
    assert _count(kb_session, ChangeItem) == 0
    assert event is not None and event.decision == "accepted_delete"
    assert event.change_set_id == tombstone.id
    assert event.tombstone_change_item_id is None


def test_l3_delete_active_equal_wins_and_replay_reuses_exact_tombstone(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session, "021-delete-equal")
    incoming = source_identity(scope, revision_char="b", ordering_offset=2)
    lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        incoming,
        "active",
        actor="head-seed",
    )
    _, first_evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate="021_delete_equal_first",
        identities=[incoming],
    )
    _, second_evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate="021_delete_equal_second",
        identities=[incoming],
    )
    evidence_ids = {first_evidence[0].id, second_evidence[0].id}

    first = retract_source(kb_session, scope, incoming)
    tombstone = kb_session.get(ChangeSet, first.change_set_id)
    assert tombstone is not None
    item_ids = set(
        kb_session.scalars(
            select(ChangeItem.id).where(ChangeItem.change_set_id == tombstone.id)
        )
    )
    second = retract_source(kb_session, scope, incoming)

    assert first == second
    assert first.actions == {"retract": 2}
    assert all(kb_session.get(ClaimEvidence, row_id) is None for row_id in evidence_ids)
    assert _count(kb_session, ChangeSet) == 1
    assert _count(kb_session, ChangeItem) == 2
    assert set(
        kb_session.scalars(
            select(ChangeItem.id).where(ChangeItem.change_set_id == tombstone.id)
        )
    ) == item_ids
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
    assert [row.decision for row in events] == [
        "accepted_create",
        "accepted_delete",
        "idempotent",
    ]
    assert [row.change_set_id for row in events[1:]] == [tombstone.id, tombstone.id]
    assert all(row.tombstone_change_item_id is None for row in events[1:])


def test_l4_delete_rejects_existing_empty_tombstone_with_live_evidence(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session, "021-delete-existing-empty")
    incoming = source_identity(scope, revision_char="b", ordering_offset=2)
    initial = lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        incoming,
        "active",
        actor="head-seed",
    )
    claim, evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate="021_delete_existing_empty",
        identities=[incoming],
    )
    tombstone = ChangeSet(
        space_id=scope.space_id,
        source_kind="document",
        knowledge_ids=[incoming.knowledge_id],
        external_record_id=incoming.knowledge_id,
        source_revision=derive_retract_event_key(
            incoming.knowledge_id,
            incoming.source_revision,
        ),
        status="applied",
        created_by="race-winner",
    )
    kb_session.add(tombstone)
    kb_session.flush()

    with pytest.raises(ScopeViolation, match="live evidence"):
        retract_source(kb_session, scope, incoming)

    head = kb_session.scalar(
        select(SourceHead).where(
            SourceHead.space_id == scope.space_id,
            SourceHead.knowledge_id == incoming.knowledge_id,
        )
    )
    assert head is not None
    assert head.state == "active" and head.version == 1
    assert head.last_event_id == initial.event_id
    assert kb_session.get(Claim, claim.id).status == "published"  # type: ignore[union-attr]
    assert kb_session.get(ClaimEvidence, evidence[0].id) is evidence[0]
    assert kb_session.get(ChangeSet, tombstone.id) is tombstone
    assert _count(kb_session, ChangeItem) == 0
    assert _count(kb_session, ClaimRevision) == 0
    assert _count(kb_session, SourceEvent) == 1
    assert kb_session.scalar(select(func.count()).select_from(ClaimEvidence)) == 1


def test_l3_delete_older_revision_is_stale_audit_without_business_writes(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session, "021-delete-stale")
    late = source_identity(scope, revision_char="b", ordering_offset=2)
    current = source_identity(scope, revision_char="c", ordering_offset=3)
    initial = lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        current,
        "active",
        actor="head-seed",
    )
    baseline = {
        table: _count(kb_session, table)
        for table in (ChangeSet, ChangeItem, Claim, ClaimEvidence)
    }

    report = retract_source(kb_session, scope, late)

    assert report.change_set_id == ""
    assert report.actions == {}
    assert {
        table: _count(kb_session, table)
        for table in (ChangeSet, ChangeItem, Claim, ClaimEvidence)
    } == baseline
    head = kb_session.scalar(
        select(SourceHead).where(
            SourceHead.space_id == scope.space_id,
            SourceHead.knowledge_id == current.knowledge_id,
        )
    )
    assert head is not None
    assert head.head_revision == current.source_revision
    assert head.last_event_id == initial.event_id
    events = list(
        kb_session.scalars(
            select(SourceEvent).where(SourceEvent.space_id == scope.space_id)
        )
    )
    assert len(events) == 2
    stale = next(row for row in events if row.decision == "stale")
    assert stale.input_revision == late.source_revision
    assert stale.change_set_id is None


@pytest.mark.parametrize("initial_state", ["active", "deleted"])
def test_l3_delete_newer_revision_advances_head_and_uses_new_identity_tombstone(
    kb_session: Session,
    initial_state: Literal["active", "deleted"],
) -> None:
    scope = bound_scope(kb_session, f"021-delete-newer-{initial_state}")
    old = source_identity(scope, revision_char="b", ordering_offset=2)
    incoming = source_identity(scope, revision_char="c", ordering_offset=3)
    old_item_ids: set[str] = set()
    if initial_state == "active":
        lifecycle_service.coordinate_source_lifecycle(
            kb_session,
            scope,
            old,
            "active",
            actor="head-seed",
        )
    else:
        _, old_evidence = claim_with_evidence(
            kb_session,
            scope,
            predicate="021_delete_newer_old",
            identities=[old],
        )
        old_report = retract_source(kb_session, scope, old)
        old_item_ids = set(
            kb_session.scalars(
                select(ChangeItem.id).where(
                    ChangeItem.change_set_id == old_report.change_set_id
                )
            )
        )
        assert len(old_item_ids) == 1
        assert kb_session.get(ClaimEvidence, old_evidence[0].id) is None
    incoming_claim, incoming_evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate=f"021_delete_newer_incoming_{initial_state}",
        identities=[incoming],
    )
    baseline_change_sets = _count(kb_session, ChangeSet)

    report = retract_source(kb_session, scope, incoming)

    head = kb_session.scalar(
        select(SourceHead).where(
            SourceHead.space_id == scope.space_id,
            SourceHead.knowledge_id == incoming.knowledge_id,
        )
    )
    tombstone = kb_session.get(ChangeSet, report.change_set_id)
    new_item_ids = set(
        kb_session.scalars(
            select(ChangeItem.id).where(ChangeItem.change_set_id == report.change_set_id)
        )
    )
    assert head is not None
    assert head.state == "deleted"
    assert head.head_revision == incoming.source_revision
    assert head.version == 2
    assert tombstone is not None
    assert tombstone.source_revision == derive_retract_event_key(
        incoming.knowledge_id,
        incoming.source_revision,
    )
    assert _count(kb_session, ChangeSet) == baseline_change_sets + 1
    assert len(new_item_ids) == 1
    assert new_item_ids.isdisjoint(old_item_ids)
    assert kb_session.get(ClaimEvidence, incoming_evidence[0].id) is None
    lifecycle_event = kb_session.scalar(
        select(SourceEvent).where(
            SourceEvent.space_id == scope.space_id,
            SourceEvent.input_revision == incoming.source_revision,
            SourceEvent.decision == "accepted_delete",
        )
    )
    assert lifecycle_event is not None
    assert lifecycle_event.change_set_id == tombstone.id
    assert lifecycle_event.tombstone_change_item_id == next(iter(new_item_ids))
    revision = kb_session.scalar(
        select(ClaimRevision).where(ClaimRevision.claim_id == incoming_claim.id)
    )
    assert revision is not None
    assert revision.change_item_id == next(iter(new_item_ids))


def test_l4_delete_event_failure_rolls_back_business_but_keeps_caller_work(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session, "021-delete-rollback")
    incoming = source_identity(scope, revision_char="b", ordering_offset=2)
    claim, evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate="021_delete_rollback",
        identities=[incoming],
    )
    caller_row = ReviewItem(
        space_id=scope.space_id,
        review_key="caller-before-delete-021",
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
            raise RuntimeError("injected delete event flush failure")

    event.listen(kb_session, "before_flush", fail_event_flush)
    try:
        with pytest.raises(RuntimeError, match="delete event flush failure"):
            retract_source(kb_session, scope, incoming)
    finally:
        event.remove(kb_session, "before_flush", fail_event_flush)

    restored_claim = kb_session.get(Claim, claim.id)
    assert restored_claim is not None and restored_claim.status == "published"
    assert kb_session.get(ClaimEvidence, evidence[0].id) is not None
    assert kb_session.get(ReviewItem, caller_row.id) is caller_row
    assert _count(kb_session, ChangeSet) == 0
    assert _count(kb_session, ChangeItem) == 0
    assert _count(kb_session, ClaimRevision) == 0
    assert _count(kb_session, SourceHead) == 0
    assert _count(kb_session, SourceEvent) == 0
    assert kb_session.scalar(select(func.count()).select_from(ReviewItem)) == 1


def test_l4_delete_retracts_all_scoped_revisions_and_preserves_other_evidence(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session, "021-delete-scope")
    foreign_scope = bound_scope(kb_session, "021-delete-scope-foreign")
    old = source_identity(scope, revision_char="a", ordering_offset=1)
    incoming = source_identity(scope, revision_char="b", ordering_offset=2)
    foreign = source_identity(
        foreign_scope,
        knowledge_id=incoming.knowledge_id,
        revision_char="b",
        ordering_offset=2,
    )
    retained_claim, matched = claim_with_evidence(
        kb_session,
        scope,
        predicate="021_delete_scope_retained",
        identities=[old, incoming],
    )
    removed_claim, removed_only = claim_with_evidence(
        kb_session,
        scope,
        predicate="021_delete_scope_removed",
        identities=[old],
    )
    _, foreign_evidence = claim_with_evidence(
        kb_session,
        foreign_scope,
        predicate="021_delete_scope_foreign",
        identities=[foreign],
    )
    legacy = ClaimEvidence(
        claim_id=retained_claim.id,
        knowledge_id=incoming.knowledge_id,
        chunk_id="legacy-chunk",
        quote="legacy evidence",
        page=1,
        authority_level=1,
        doc_role="terms",
        extraction_method="manual",
        lineage_status=None,
    )
    wrong_raw = ClaimEvidence(
        claim_id=retained_claim.id,
        knowledge_id=incoming.knowledge_id,
        chunk_id=None,
        quote="other raw evidence",
        page=1,
        authority_level=1,
        doc_role="terms",
        extraction_method="llm",
        raw_kb_id=foreign_scope.raw_kb_id,
        source_revision=foreign.source_revision,
        file_hash=foreign.file_hash,
        original_digest=foreign.original_digest,
        parser_version=foreign.parser_version,
        chunk_hash=None,
        lineage_status="page_only",
    )
    kb_session.add_all([legacy, wrong_raw])
    kb_session.flush()

    report = retract_source(kb_session, scope, incoming)

    assert report.actions == {"retract": 2}
    assert all(kb_session.get(ClaimEvidence, row.id) is None for row in matched)
    assert kb_session.get(ClaimEvidence, removed_only[0].id) is None
    assert kb_session.get(ClaimEvidence, legacy.id) is legacy
    assert kb_session.get(ClaimEvidence, wrong_raw.id) is wrong_raw
    assert kb_session.get(ClaimEvidence, foreign_evidence[0].id) is not None
    assert kb_session.get(Claim, retained_claim.id).status == "published"  # type: ignore[union-attr]
    assert kb_session.get(Claim, removed_claim.id).status == "retracted"  # type: ignore[union-attr]
    retained_revisions = list(
        kb_session.scalars(
            select(ClaimRevision).where(ClaimRevision.claim_id == retained_claim.id)
        )
    )
    removed_revisions = list(
        kb_session.scalars(
            select(ClaimRevision).where(ClaimRevision.claim_id == removed_claim.id)
        )
    )
    assert retained_revisions == []
    assert len(removed_revisions) == 1
    item_ids = set(
        kb_session.scalars(
            select(ChangeItem.id).where(ChangeItem.change_set_id == report.change_set_id)
        )
    )
    assert removed_revisions[0].change_item_id in item_ids
    lifecycle_event = kb_session.scalar(
        select(SourceEvent).where(SourceEvent.change_set_id == report.change_set_id)
    )
    assert lifecycle_event is not None
    assert lifecycle_event.tombstone_change_item_id is None


@pytest.mark.parametrize("root_kind", ["head", "issue"])
def test_l4_delete_legacy_replay_rejects_source_lifecycle_root(
    kb_session: Session,
    root_kind: str,
) -> None:
    scope = bound_scope(kb_session, f"021-delete-legacy-{root_kind}")
    incoming = source_identity(scope, revision_char="a")
    if root_kind == "head":
        lifecycle_service.coordinate_source_lifecycle(
            kb_session,
            scope,
            incoming,
            "active",
            actor="head-seed",
        )
    else:
        kb_session.add(
            SourceLifecycleBackfillIssue(
                space_id=scope.space_id,
                tenant_id=scope.tenant_id,
                raw_kb_id=scope.raw_kb_id,
                knowledge_id=incoming.knowledge_id,
                observed_revisions=[incoming.source_revision],
                reason="ambiguous ordering",
                status="open",
            )
        )
        kb_session.flush()
    baseline = {
        table: _count(kb_session, table)
        for table in (SourceHead, SourceEvent, SourceLifecycleBackfillIssue)
    }

    with pytest.raises(ScopeViolation, match="source mode conflict"):
        retract_source(
            kb_session,
            scope,
            incoming.knowledge_id,
            legacy_replay=True,
        )

    assert _count(kb_session, ChangeSet) == 0
    assert {
        table: _count(kb_session, table)
        for table in (SourceHead, SourceEvent, SourceLifecycleBackfillIssue)
    } == baseline


def test_l4_notify_delete_blocked_import_reactivate_preserves_release_snapshot(
    kb_session: Session,
) -> None:
    scope = release_scope(kb_session, "021-delete-chain")
    product, version = release_product(
        kb_session,
        scope,
        code="DELETE-021-CHAIN",
    )
    claim, _ = release_claim(
        kb_session,
        scope,
        version,
        claim_id="021-delete-chain",
        predicate="waiting_period",
    )
    snapshot_id = "snapshot-delete-021-chain"
    persist_release_snapshot(
        kb_session,
        scope,
        snapshot_id=snapshot_id,
        facts=[
            SnapshotFactView(
                space_id=scope.space_id,
                snapshot_id=snapshot_id,
                claim_id=claim.id,
                revision_no=1,
                product_id=product.id,
                product_version_id=version.id,
                product_code=product.product_code,
                product_name=product.canonical_name,
                version_label=version.version_label,
                predicate=claim.predicate,
                field_name=claim.predicate,
                field_group="terms",
                value_state="present",
                value={"text": "90天"},
                effective_from=None,
                effective_to=None,
                confidence=0.9,
                schema_version="v1",
                evidence=(),
            )
        ],
    )
    snapshot = kb_session.get(ReleaseSnapshot, snapshot_id)
    fact = kb_session.scalar(
        select(SnapshotFact).where(SnapshotFact.snapshot_id == snapshot_id)
    )
    pointer = kb_session.get(CurrentRelease, (scope.space_id, "current"))
    assert snapshot is not None and fact is not None and pointer is not None
    fingerprint = (
        snapshot.status,
        snapshot.rendered_pages,
        fact.id,
        fact.claim_id,
        fact.revision_no,
        fact.value,
        fact.evidence,
        pointer.snapshot_id,
    )
    notified = source_identity(
        scope,
        knowledge_id="knowledge-021-delete-chain",
        revision_char="b",
        ordering_offset=2,
    )
    newer = source_identity(
        scope,
        knowledge_id=notified.knowledge_id,
        revision_char="c",
        ordering_offset=3,
    )

    revision_service.notify_source_revision(kb_session, scope, notified)
    retract_source(kb_session, scope, notified)
    blocked = import_pred_records(
        kb_session,
        [source_record(notified)],
        scope=scope,
        product_id=product.product_code,
        product_version_id=version.id,
        source_context={
            "space_id": scope.space_id,
            "tenant_id": scope.tenant_id,
            "raw_kb_id": scope.raw_kb_id,
            "documents": {"new.pdf": notified.model_dump(mode="python")},
        },
        policy=MergePolicy(auto_apply_add=True),
        quality_gate=_GATE,
        run_fingerprint=_FP,
    )
    reactivated = import_pred_records(
        kb_session,
        [source_record(newer)],
        scope=scope,
        product_id=product.product_code,
        product_version_id=version.id,
        source_context={
            "space_id": scope.space_id,
            "tenant_id": scope.tenant_id,
            "raw_kb_id": scope.raw_kb_id,
            "documents": {"new.pdf": newer.model_dump(mode="python")},
        },
        policy=MergePolicy(auto_apply_add=True),
        quality_gate=_GATE,
        run_fingerprint=_FP,
    )

    assert blocked.partitions[0].lifecycle_decision == "blocked_deleted"
    assert blocked.partitions[0].change_set_id is None
    assert reactivated.partitions[0].lifecycle_decision == "accepted_reactivate"
    assert reactivated.partitions[0].change_set_id is not None
    decisions = list(
        kb_session.scalars(
            select(SourceEvent.decision)
            .where(
                SourceEvent.space_id == scope.space_id,
                SourceEvent.knowledge_id == notified.knowledge_id,
            )
            .order_by(SourceEvent.created_at, SourceEvent.id)
        )
    )
    assert decisions == [
        "accepted_create",
        "accepted_delete",
        "blocked_deleted",
        "accepted_reactivate",
    ]
    kb_session.refresh(snapshot)
    kb_session.refresh(fact)
    kb_session.refresh(pointer)
    assert (
        snapshot.status,
        snapshot.rendered_pages,
        fact.id,
        fact.claim_id,
        fact.revision_no,
        fact.value,
        fact.evidence,
        pointer.snapshot_id,
    ) == fingerprint
