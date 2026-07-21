"""Source-aware import lifecycle contracts for OpenSpec 021 L3/L4."""

from typing import Any, Literal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.knowledge import MergePolicy, import_pred_records
from insurance_harness.knowledge import importer as importer_service
from insurance_harness.knowledge import source_lifecycle as lifecycle_service
from insurance_harness.knowledge import source_revision as revision_service
from insurance_harness.knowledge.models import (
    ImportPartitionReport,
    SourceImportIdentity,
)
from insurance_harness.knowledge.snapshots import SnapshotFactView
from insurance_harness.knowledge.source_keys import derive_retract_event_key
from insurance_harness.knowledge.source_lifecycle import SourceLifecycleBlocked
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    ClaimEvidence,
    CurrentRelease,
    ReleaseSnapshot,
    ReviewItem,
    SnapshotFact,
    SourceEvent,
    SourceHead,
    SourceLifecycleBackfillIssue,
)
from tests.kbhelpers import allow_all_gate, seed_product
from tests.support.release_018 import (
    persist_release_snapshot,
    release_claim,
    release_product,
    release_scope,
)
from tests.support.source_revision import (
    NOW,
    bound_scope,
    claim_with_evidence,
    source_identity,
    source_record,
)

_GATE, _FP = allow_all_gate()


def _count(session: Session, table: type[object]) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)


def _context(
    scope: KnowledgeScope,
    identity: SourceImportIdentity,
) -> dict[str, object]:
    return {
        "space_id": scope.space_id,
        "tenant_id": scope.tenant_id,
        "raw_kb_id": scope.raw_kb_id,
        "documents": {"new.pdf": identity.model_dump(mode="python")},
    }


def _multi_context(
    scope: KnowledgeScope,
    documents: dict[str, SourceImportIdentity],
) -> dict[str, object]:
    return {
        "space_id": scope.space_id,
        "tenant_id": scope.tenant_id,
        "raw_kb_id": scope.raw_kb_id,
        "documents": {
            name: identity.model_dump(mode="python")
            for name, identity in documents.items()
        },
    }


def _applied_tombstone(
    session: Session,
    scope: KnowledgeScope,
    identity: SourceImportIdentity,
) -> lifecycle_service.LifecycleBusinessOutcome:
    knowledge_id = identity.knowledge_id
    source_revision = identity.source_revision
    row = ChangeSet(
        space_id=scope.space_id,
        source_kind="document",
        knowledge_ids=[knowledge_id],
        external_record_id=knowledge_id,
        source_revision=derive_retract_event_key(knowledge_id, source_revision),
        status="applied",
        created_by="retractor",
    )
    session.add(row)
    session.flush()
    return lifecycle_service.LifecycleBusinessOutcome(
        payload=None,
        aggregate_kind="tombstone",
        change_set_id=row.id,
    )


def test_l3_import_first_active_creates_head_and_event_linked_to_actual_changeset(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session, "021-import-first")
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-021-FIRST",
        name="Import 021 first",
    )
    incoming = source_identity(scope, revision_char="a")

    report = import_pred_records(
        kb_session,
        [source_record(incoming)],
        scope=scope,
        product_id=product.product_code,
        product_version_id=version.id,
        source_context=_context(scope, incoming),
        policy=MergePolicy(auto_apply_add=True),
        quality_gate=_GATE,
        run_fingerprint=_FP,
    )

    part = report.partitions[0]
    assert part.lifecycle_decision == "accepted_create"
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
    assert head is not None and head.head_revision == incoming.source_revision
    assert event is not None and event.decision == "accepted_create"
    assert event.change_set_id == part.change_set_id


def test_l3_import_consumes_pending_notify_aggregate_on_idempotent_lifecycle(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session, "021-import-pending")
    old = source_identity(scope, revision_char="a")
    incoming = source_identity(scope, revision_char="b", ordering_offset=1)
    claim_with_evidence(
        kb_session,
        scope,
        predicate="021_import_pending_old",
        identities=[old],
    )
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-021-PENDING",
        name="Import 021 pending",
    )
    notification = revision_service.notify_source_revision(
        kb_session,
        scope,
        incoming,
        observed_at=NOW,
    )

    report = import_pred_records(
        kb_session,
        [source_record(incoming)],
        scope=scope,
        product_id=product.product_code,
        product_version_id=version.id,
        source_context=_context(scope, incoming),
        policy=MergePolicy(auto_apply_add=True),
        quality_gate=_GATE,
        run_fingerprint=_FP,
    )

    part = report.partitions[0]
    assert part.lifecycle_decision == "idempotent"
    assert part.duplicate_batch is False
    assert part.change_set_id == notification.change_set_id
    aggregate = kb_session.get(ChangeSet, notification.change_set_id)
    assert aggregate is not None and aggregate.status == "applied"
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
        notification.change_set_id,
        notification.change_set_id,
    ]


def test_l3_import_late_older_revision_returns_stale_partition_without_business_writes(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session, "021-import-stale")
    late = source_identity(scope, revision_char="b", ordering_offset=2)
    current = source_identity(scope, revision_char="c", ordering_offset=3)
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-021-STALE",
        name="Import 021 stale",
    )
    revision_service.notify_source_revision(kb_session, scope, current)
    baseline = {
        table: _count(kb_session, table)
        for table in (ChangeSet, ChangeItem, Claim, ClaimEvidence)
    }
    baseline_events = _count(kb_session, SourceEvent)

    report = import_pred_records(
        kb_session,
        [source_record(late)],
        scope=scope,
        product_id=product.product_code,
        product_version_id=version.id,
        source_context=_context(scope, late),
        policy=MergePolicy(auto_apply_add=True),
        quality_gate=_GATE,
        run_fingerprint=_FP,
    )

    part = report.partitions[0]
    assert part.lifecycle_decision == "stale"
    assert part.source_kind is None
    assert part.change_set_id is None
    assert report.change_set_id is None
    assert report.change_set_ids == []
    assert {
        table: _count(kb_session, table)
        for table in (ChangeSet, ChangeItem, Claim, ClaimEvidence)
    } == baseline
    assert _count(kb_session, SourceEvent) == baseline_events + 1


def test_l4_import_idempotent_without_exact_aggregate_fails_closed(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session, "021-import-idempotent-missing")
    incoming = source_identity(scope, revision_char="b", ordering_offset=2)
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-021-IDEMPOTENT-MISSING",
        name="Import 021 idempotent missing",
    )
    initial = lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        incoming,
        "active",
        actor="head-seed",
    )

    with pytest.raises(ScopeViolation, match="exact aggregate"):
        import_pred_records(
            kb_session,
            [source_record(incoming)],
            scope=scope,
            product_id=product.product_code,
            product_version_id=version.id,
            source_context=_context(scope, incoming),
            policy=MergePolicy(auto_apply_add=True),
            quality_gate=_GATE,
            run_fingerprint=_FP,
        )

    assert _count(kb_session, ChangeSet) == 0
    assert _count(kb_session, Claim) == 0
    assert _count(kb_session, ClaimEvidence) == 0
    assert _count(kb_session, SourceEvent) == 1
    head = kb_session.scalar(
        select(SourceHead).where(
            SourceHead.space_id == scope.space_id,
            SourceHead.knowledge_id == incoming.knowledge_id,
        )
    )
    assert head is not None and head.last_event_id == initial.event_id
    assert kb_session.get(SourceHead, head.id) is head


def test_l4_import_idempotent_rejects_foreign_active_evidence_before_consuming(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session, "021-import-idempotent-evidence")
    incoming = source_identity(scope, revision_char="b", ordering_offset=2)
    foreign = source_identity(scope, revision_char="c", ordering_offset=3)
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-021-IDEMPOTENT-EVIDENCE",
        name="Import 021 idempotent evidence",
    )
    initial = lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        incoming,
        "active",
        actor="head-seed",
    )
    pending = ChangeSet(
        space_id=scope.space_id,
        source_kind="recompile",
        knowledge_ids=[incoming.knowledge_id],
        external_record_id=incoming.knowledge_id,
        source_revision=incoming.source_revision,
        status="pending",
        created_by="notify",
    )
    kb_session.add(pending)
    _, evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate="021_import_idempotent_foreign",
        identities=[foreign],
    )
    kb_session.flush()
    evidence_id = evidence[0].id

    with pytest.raises(ScopeViolation, match="ambiguous"):
        import_pred_records(
            kb_session,
            [source_record(incoming)],
            scope=scope,
            product_id=product.product_code,
            product_version_id=version.id,
            source_context=_context(scope, incoming),
            policy=MergePolicy(auto_apply_add=True),
            quality_gate=_GATE,
            run_fingerprint=_FP,
        )

    restored_pending = kb_session.get(ChangeSet, pending.id)
    restored_evidence = kb_session.get(ClaimEvidence, evidence_id)
    assert restored_pending is not None and restored_pending.status == "pending"
    assert _count(kb_session, ChangeItem) == 0
    assert restored_evidence is not None and restored_evidence.stale_at is None
    assert _count(kb_session, SourceEvent) == 1
    head = kb_session.scalar(
        select(SourceHead).where(
            SourceHead.space_id == scope.space_id,
            SourceHead.knowledge_id == incoming.knowledge_id,
        )
    )
    assert head is not None and head.last_event_id == initial.event_id
    assert kb_session.get(SourceHead, head.id) is head


@pytest.mark.parametrize(
    ("decision", "source_kind", "change_set_id"),
    [
        ("stale", "document", "change-set"),
        ("blocked_deleted", "recompile", "change-set"),
        ("accepted_create", None, None),
        ("idempotent", None, None),
    ],
)
def test_l3_import_partition_report_rejects_lifecycle_aggregate_shape_mismatch(
    decision: str,
    source_kind: str | None,
    change_set_id: str | None,
) -> None:
    with pytest.raises(ValueError, match="lifecycle aggregate"):
        ImportPartitionReport(
            knowledge_id="knowledge-1",
            source_revision="a" * 64,
            lifecycle_decision=decision,  # type: ignore[arg-type]
            source_kind=source_kind,
            change_set_id=change_set_id,
        )


def test_l4_import_multi_partition_failure_rolls_back_all_and_keeps_caller_work(
    kb_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = bound_scope(kb_session, "021-import-multi-rollback")
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-021-MULTI",
        name="Import 021 multi",
    )
    first = source_identity(
        scope,
        knowledge_id="knowledge-a",
        revision_char="a",
        ordering_offset=1,
    )
    blocked = source_identity(
        scope,
        knowledge_id="knowledge-z",
        revision_char="b",
        ordering_offset=1,
    )
    malformed = ChangeSet(
        space_id=scope.space_id,
        source_kind="recompile",
        knowledge_ids=[blocked.knowledge_id],
        external_record_id=blocked.knowledge_id,
        source_revision=blocked.source_revision,
        status="pending",
        created_by="malformed",
    )
    caller_row = ReviewItem(
        space_id=scope.space_id,
        review_key="caller-before-import-021",
        type="conflict",
        subject={"kind": "caller"},
        allowed_actions=["defer"],
        status="open",
        risk_level="low",
    )
    kb_session.add_all([malformed, caller_row])
    kb_session.flush()
    kb_session.add(
        ChangeItem(
            change_set_id=malformed.id,
            action="add",
            proposed={"malformed": True},
            decision="needs_review",
        )
    )
    kb_session.flush()
    baseline = {
        table: _count(kb_session, table)
        for table in (ChangeSet, ChangeItem, Claim, ClaimEvidence)
    }
    coordinator_order: list[str] = []
    original_coordinator = lifecycle_service.coordinate_source_lifecycle

    def record_coordinator_order(*args: Any, **kwargs: Any) -> Any:
        identity = args[2]
        assert isinstance(identity, SourceImportIdentity)
        coordinator_order.append(identity.knowledge_id)
        return original_coordinator(*args, **kwargs)

    monkeypatch.setattr(
        importer_service,
        "coordinate_source_lifecycle",
        record_coordinator_order,
    )

    with pytest.raises(ScopeViolation, match="cannot be replayed"):
        import_pred_records(
            kb_session,
            [
                source_record(blocked, doc="z.pdf"),
                source_record(first, doc="a.pdf"),
            ],
            scope=scope,
            product_id=product.product_code,
            product_version_id=version.id,
            source_context=_multi_context(
                scope,
                {"z.pdf": blocked, "a.pdf": first},
            ),
            policy=MergePolicy(auto_apply_add=True),
            quality_gate=_GATE,
            run_fingerprint=_FP,
        )

    assert coordinator_order == ["knowledge-a", "knowledge-z"]
    assert {
        table: _count(kb_session, table)
        for table in (ChangeSet, ChangeItem, Claim, ClaimEvidence)
    } == baseline
    assert _count(kb_session, SourceHead) == 0
    assert _count(kb_session, SourceEvent) == 0
    assert kb_session.get(ChangeSet, malformed.id) is malformed
    assert kb_session.get(ReviewItem, caller_row.id) is caller_row


def test_l4_import_ordering_collision_fails_without_legacy_fallback(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session, "021-import-collision")
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-021-COLLISION",
        name="Import 021 collision",
    )
    current = source_identity(scope, revision_char="b", ordering_offset=2)
    colliding = source_identity(scope, revision_char="c", ordering_offset=2)
    initial = lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        current,
        "active",
        actor="head-seed",
    )

    with pytest.raises(ValueError, match="ordering collision"):
        import_pred_records(
            kb_session,
            [source_record(colliding)],
            scope=scope,
            product_id=product.product_code,
            product_version_id=version.id,
            source_context=_context(scope, colliding),
            policy=MergePolicy(auto_apply_add=True),
            quality_gate=_GATE,
            run_fingerprint=_FP,
        )

    assert _count(kb_session, ChangeSet) == 0
    assert _count(kb_session, Claim) == 0
    assert _count(kb_session, SourceEvent) == 1
    head = kb_session.scalar(
        select(SourceHead).where(SourceHead.space_id == scope.space_id)
    )
    assert head is not None and head.last_event_id == initial.event_id


def test_l4_import_open_backfill_issue_blocks_without_legacy_fallback(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session, "021-import-open-issue")
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-021-ISSUE",
        name="Import 021 issue",
    )
    incoming = source_identity(scope, revision_char="a")
    issue = SourceLifecycleBackfillIssue(
        space_id=scope.space_id,
        tenant_id=scope.tenant_id,
        raw_kb_id=scope.raw_kb_id,
        knowledge_id=incoming.knowledge_id,
        observed_revisions=[incoming.source_revision],
        reason="legacy ordering is unknown",
        status="open",
    )
    kb_session.add(issue)
    kb_session.flush()

    with pytest.raises(SourceLifecycleBlocked, match="backfill issue"):
        import_pred_records(
            kb_session,
            [source_record(incoming)],
            scope=scope,
            product_id=product.product_code,
            product_version_id=version.id,
            source_context=_context(scope, incoming),
            policy=MergePolicy(auto_apply_add=True),
            quality_gate=_GATE,
            run_fingerprint=_FP,
        )

    assert _count(kb_session, ChangeSet) == 0
    assert _count(kb_session, Claim) == 0
    assert _count(kb_session, SourceHead) == 0
    assert _count(kb_session, SourceEvent) == 0
    assert kb_session.get(SourceLifecycleBackfillIssue, issue.id) is issue


@pytest.mark.parametrize(
    ("initial_state", "expected_decision"),
    [("active", "accepted_advance"), ("deleted", "accepted_reactivate")],
)
def test_l3_import_newer_revision_stales_prior_scoped_active_evidence(
    kb_session: Session,
    initial_state: Literal["active", "deleted"],
    expected_decision: Literal["accepted_advance", "accepted_reactivate"],
) -> None:
    scope = bound_scope(kb_session, f"021-import-{initial_state}")
    old = source_identity(scope, revision_char="b", ordering_offset=2)
    incoming = source_identity(scope, revision_char="c", ordering_offset=3)
    product, version = seed_product(
        kb_session,
        scope=scope,
        code=f"IMPORT-021-{initial_state.upper()}",
        name=f"Import 021 {initial_state}",
    )
    _, evidence = claim_with_evidence(
        kb_session,
        scope,
        predicate=f"021_import_old_{initial_state}",
        identities=[old],
    )
    lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        old,
        initial_state,
        actor="head-seed",
        apply_business=(
            (
                lambda session, _decision: _applied_tombstone(
                    session,
                    scope,
                    old,
                )
            )
            if initial_state == "deleted"
            else None
        ),
    )

    report = import_pred_records(
        kb_session,
        [source_record(incoming)],
        scope=scope,
        product_id=product.product_code,
        product_version_id=version.id,
        source_context=_context(scope, incoming),
        policy=MergePolicy(auto_apply_add=True),
        quality_gate=_GATE,
        run_fingerprint=_FP,
    )

    part = report.partitions[0]
    assert part.lifecycle_decision == expected_decision
    kb_session.refresh(evidence[0])
    assert evidence[0].stale_at is not None
    incoming_evidence = list(
        kb_session.scalars(
            select(ClaimEvidence).where(
                ClaimEvidence.knowledge_id == incoming.knowledge_id,
                ClaimEvidence.source_revision == incoming.source_revision,
            )
        )
    )
    assert len(incoming_evidence) == 1
    assert incoming_evidence[0].stale_at is None
    lifecycle_event = kb_session.scalar(
        select(SourceEvent).where(
            SourceEvent.space_id == scope.space_id,
            SourceEvent.knowledge_id == incoming.knowledge_id,
            SourceEvent.decision == expected_decision,
        )
    )
    assert lifecycle_event is not None
    assert lifecycle_event.change_set_id == part.change_set_id


def test_l4_import_preserves_snapshot_fact_and_current_release_fingerprint(
    kb_session: Session,
) -> None:
    scope = release_scope(kb_session, "021-import-snapshot")
    product, version = release_product(
        kb_session,
        scope,
        code="IMPORT-021-SNAPSHOT",
    )
    claim, _ = release_claim(
        kb_session,
        scope,
        version,
        claim_id="claim-import-021-snapshot",
        predicate="waiting_period",
    )
    snapshot_id = "snapshot-import-021"
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
    before_fingerprint = (
        snapshot.status,
        snapshot.rendered_pages,
        fact.id,
        fact.claim_id,
        fact.revision_no,
        fact.value,
        fact.evidence,
        pointer.snapshot_id,
    )
    incoming = source_identity(
        scope,
        knowledge_id="knowledge-import-021-snapshot",
        revision_char="b",
        ordering_offset=2,
    )

    import_pred_records(
        kb_session,
        [source_record(incoming)],
        scope=scope,
        product_id=product.product_code,
        product_version_id=version.id,
        source_context=_context(scope, incoming),
        policy=MergePolicy(auto_apply_add=True),
        quality_gate=_GATE,
        run_fingerprint=_FP,
    )

    kb_session.refresh(snapshot)
    kb_session.refresh(fact)
    kb_session.refresh(pointer)
    after_fingerprint = (
        snapshot.status,
        snapshot.rendered_pages,
        fact.id,
        fact.claim_id,
        fact.revision_no,
        fact.value,
        fact.evidence,
        pointer.snapshot_id,
    )
    assert after_fingerprint == before_fingerprint


@pytest.mark.parametrize(
    ("action", "decision"),
    [("unsupported", "auto_applied"), ("add", "needs_review")],
)
def test_l4_import_applied_exact_duplicate_rejects_nonterminal_child_semantics(
    kb_session: Session,
    action: str,
    decision: str,
) -> None:
    scope = bound_scope(
        kb_session,
        f"021-import-applied-{action}-{decision}",
    )
    product, version = seed_product(
        kb_session,
        scope=scope,
        code=f"IMPORT-021-APPLIED-{action}-{decision}",
        name="Import 021 malformed applied duplicate",
    )
    incoming = source_identity(scope, revision_char="a")
    claim = Claim(
        space_id=scope.space_id,
        product_version_id=version.id,
        subject_type="product_version",
        predicate="021_import_applied_duplicate",
        value_state="present",
        value={"text": "existing"},
        status="draft",
        confidence=0.5,
        schema_version="test",
        current_revision=0,
    )
    applied = ChangeSet(
        space_id=scope.space_id,
        source_kind="document",
        knowledge_ids=[incoming.knowledge_id],
        external_record_id=incoming.knowledge_id,
        source_revision=incoming.source_revision,
        status="applied",
        created_by="malformed",
    )
    kb_session.add_all([claim, applied])
    kb_session.flush()
    kb_session.add(
        ChangeItem(
            change_set_id=applied.id,
            action=action,
            claim_id=claim.id,
            proposed={},
            decision=decision,
        )
    )
    kb_session.flush()
    baseline = {
        table: _count(kb_session, table)
        for table in (ChangeSet, ChangeItem, Claim, ClaimEvidence)
    }

    with pytest.raises(ScopeViolation, match="cannot be replayed"):
        import_pred_records(
            kb_session,
            [source_record(incoming)],
            scope=scope,
            product_id=product.product_code,
            product_version_id=version.id,
            source_context=_context(scope, incoming),
            policy=MergePolicy(auto_apply_add=True),
            quality_gate=_GATE,
            run_fingerprint=_FP,
        )

    assert {
        table: _count(kb_session, table)
        for table in (ChangeSet, ChangeItem, Claim, ClaimEvidence)
    } == baseline
    assert _count(kb_session, SourceHead) == 0
    assert _count(kb_session, SourceEvent) == 0
    assert kb_session.get(ChangeSet, applied.id) is applied
    assert kb_session.get(Claim, claim.id) is claim


def test_l3_import_deleted_equal_returns_blocked_partition_without_legacy_fallback(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session, "021-import-blocked")
    incoming = source_identity(scope, revision_char="b", ordering_offset=2)
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-021-BLOCKED",
        name="Import 021 blocked",
    )
    lifecycle_service.coordinate_source_lifecycle(
        kb_session,
        scope,
        incoming,
        "deleted",
        actor="retractor",
        apply_business=lambda session, _decision: _applied_tombstone(
            session,
            scope,
            incoming,
        ),
    )
    baseline = {
        table: _count(kb_session, table)
        for table in (ChangeSet, ChangeItem, Claim, ClaimEvidence)
    }
    baseline_events = _count(kb_session, SourceEvent)

    report = import_pred_records(
        kb_session,
        [source_record(incoming)],
        scope=scope,
        product_id=product.product_code,
        product_version_id=version.id,
        source_context=_context(scope, incoming),
        policy=MergePolicy(auto_apply_add=True),
        quality_gate=_GATE,
        run_fingerprint=_FP,
    )

    part = report.partitions[0]
    assert part.lifecycle_decision == "blocked_deleted"
    assert part.source_kind is None
    assert part.change_set_id is None
    assert report.change_set_ids == []
    assert {
        table: _count(kb_session, table)
        for table in (ChangeSet, ChangeItem, Claim, ClaimEvidence)
    } == baseline
    assert _count(kb_session, SourceEvent) == baseline_events + 1
