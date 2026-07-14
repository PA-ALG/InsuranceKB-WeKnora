"""OpenSpec 016 S2：Claim 导入、合并、审核与撤回强制 KnowledgeScope。"""

from collections.abc import Callable
from typing import Literal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import insurance_harness.knowledge.merge as merge_module
from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.knowledge import (
    ConflictJudgement,
    MergeEngine,
    MergePolicy,
    ProposedClaim,
    ProposedEvidence,
    apply_change_item,
    apply_conflict_judgements,
    ensure_review_item,
    get_review_item,
    import_pred_records,
    overturn_review,
    publish_claim,
    reject_change_item,
    resolve_review,
    retract_source,
)
from insurance_harness.knowledge.merge import claim_evidence
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    ClaimEvidence,
    Conflict,
    ReviewItem,
)
from tests.kbhelpers import allow_all_gate, pred, seed_bound_scope, seed_product

_GATE, _FP = allow_all_gate()  # fail-closed 后自动发布须过 gate；发布仍需 auto_apply 位


def _scope(session: Session, label: str) -> KnowledgeScope:
    return seed_bound_scope(
        session,
        tenant_id=f"tenant-{label}",
        raw_kb_id=f"raw-{label}",
        wiki_kb_id=f"wiki-{label}",
    )


def _proposal(
    scope: KnowledgeScope,
    product_version_id: str,
    *,
    predicate: str = "waiting_period",
    value: str = "90天",
    knowledge_id: str = "knowledge-brochure",
) -> ProposedClaim:
    return ProposedClaim(
        space_id=scope.space_id,
        product_version_id=product_version_id,
        predicate=predicate,
        field_name=predicate,
        value_state="present",
        value=value,
        confidence=0.9,
        evidence=[
            ProposedEvidence(
                knowledge_id=knowledge_id,
                quote=f"{predicate}={value}",
                page=1,
                doc_role="official_desc",
                authority_level=2,
            )
        ],
    )


def _apply(
    engine: MergeEngine,
    proposal: ProposedClaim,
    *,
    external_record_id: str,
) -> str:
    change_set, created = engine.open_change_set(
        source_kind="document",
        external_record_id=external_record_id,
        source_revision="r1",
    )
    assert created
    report = engine.apply_batch(change_set, [proposal])
    return report.review_keys[0] if report.review_keys else ""


def _count(session: Session, table: type) -> int:
    return session.execute(select(func.count()).select_from(table)).scalar_one()


def _assert_generic_scope_error(call: Callable[[], object]) -> None:
    with pytest.raises(ScopeViolation) as exc_info:
        call()
    assert str(exc_info.value) == "scope mismatch"


def _pending_conflict(
    session: Session,
    scope: KnowledgeScope,
    label: str,
) -> tuple[Conflict, ChangeItem, Claim, Claim]:
    _, version = seed_product(session, scope=scope, code=f"CODE-{label}")
    engine = MergeEngine(session, scope=scope, policy=MergePolicy(auto_apply_add=True),
        quality_gate=_GATE, run_fingerprint=_FP)
    _apply(
        engine,
        _proposal(scope, version.id, value="90天"),
        external_record_id=f"base-{label}",
    )
    _apply(
        engine,
        _proposal(scope, version.id, value="180天"),
        external_record_id=f"conflict-{label}",
    )
    conflict = session.execute(
        select(Conflict)
        .join(ChangeItem, ChangeItem.id == Conflict.change_item_id)
        .join(ChangeSet, ChangeSet.id == ChangeItem.change_set_id)
        .where(ChangeSet.space_id == scope.space_id)
    ).scalar_one()
    item = session.get(ChangeItem, conflict.change_item_id)
    assert item is not None and item.claim_id is not None
    candidate = session.get(Claim, item.claim_id)
    existing = session.get(Claim, conflict.existing_claim_id)
    assert candidate is not None and existing is not None
    return conflict, item, candidate, existing


def _same_scope_review_mismatch(
    session: Session,
    scope: KnowledgeScope,
    label: str,
) -> tuple[ReviewItem, ChangeItem, Claim, Conflict, Claim]:
    conflict, _, conflict_claim, _ = _pending_conflict(
        session, scope, f"{label}-conflict"
    )
    _, version = seed_product(session, scope=scope, code=f"CODE-{label}-review")
    review_key = _apply(
        MergeEngine(session, scope=scope),
        _proposal(scope, version.id, predicate="grace_period"),
        external_record_id=f"{label}-review",
    )
    review = get_review_item(session, scope, review_key)
    assert review is not None
    item = session.get(ChangeItem, review.subject["change_item_id"])
    assert item is not None and item.claim_id is not None
    claim = session.get(Claim, item.claim_id)
    assert claim is not None
    return review, item, claim, conflict, conflict_claim


def test_s2_4_changeset_idempotency_tuple_is_scoped(session: Session) -> None:
    scope_a = _scope(session, "a")
    scope_b = _scope(session, "b")
    engine_a = MergeEngine(session, scope=scope_a)
    engine_b = MergeEngine(session, scope=scope_b)

    change_a, created_a = engine_a.open_change_set(
        source_kind="document",
        external_record_id="same-batch",
        source_revision="same-revision",
    )
    change_b, created_b = engine_b.open_change_set(
        source_kind="document",
        external_record_id="same-batch",
        source_revision="same-revision",
    )
    again_a, created_again_a = engine_a.open_change_set(
        source_kind="document",
        external_record_id="same-batch",
        source_revision="same-revision",
    )

    assert created_a and created_b and not created_again_a
    assert change_a.id == again_a.id and change_b.id != change_a.id
    assert {change_a.space_id, change_b.space_id} == {scope_a.space_id, scope_b.space_id}
    assert _count(session, ChangeSet) == 2


def test_knowledge_mutation_rejects_forged_unbound_scope_before_write(
    session: Session,
) -> None:
    legacy = KnowledgeSpace(name="legacy", binding_status="unbound")
    session.add(legacy)
    session.flush()
    forged = KnowledgeScope(
        space_id=legacy.id,
        tenant_id="forged-tenant",
        raw_kb_id="forged-raw",
        wiki_kb_id="forged-wiki",
    )
    before = _count(session, ChangeSet)

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        engine = MergeEngine(session, scope=forged)
        engine.open_change_set(
            source_kind="document",
            external_record_id="forged-write",
            source_revision="r1",
        )

    assert _count(session, ChangeSet) == before
    assert session.is_active


def test_s2_5_merge_active_claims_and_actions_are_scoped(session: Session) -> None:
    scope_a = _scope(session, "a")
    scope_b = _scope(session, "b")
    _, version_a = seed_product(session, scope=scope_a)
    _, version_b = seed_product(session, scope=scope_b)
    policy = MergePolicy(auto_apply_add=True, auto_apply_enrich=True)
    engine_a = MergeEngine(session, scope=scope_a, policy=policy,
                           quality_gate=_GATE, run_fingerprint=_FP)
    engine_b = MergeEngine(session, scope=scope_b, policy=policy,
                           quality_gate=_GATE, run_fingerprint=_FP)

    _apply(engine_b, _proposal(scope_b, version_b.id), external_record_id="batch-b")
    assert engine_a._active_claim(version_b.id, "waiting_period") is None
    _apply(engine_a, _proposal(scope_a, version_a.id), external_record_id="batch-a")

    claims = session.execute(select(Claim).order_by(Claim.space_id)).scalars().all()
    assert len(claims) == 2
    assert {claim.space_id for claim in claims} == {scope_a.space_id, scope_b.space_id}
    assert {claim.status for claim in claims} == {"published"}
    assert {item.action for item in session.execute(select(ChangeItem)).scalars()} == {"add"}


def test_s2_4_review_key_and_lookup_are_scoped(session: Session) -> None:
    scope_a = _scope(session, "a")
    scope_b = _scope(session, "b")

    item_a, created_a = ensure_review_item(
        session,
        scope=scope_a,
        review_key="same-review-key",
        type_="low_confidence",
        subject={"same": "content"},
    )
    again_a, created_again_a = ensure_review_item(
        session,
        scope=scope_a,
        review_key="same-review-key",
        type_="low_confidence",
        subject={"same": "content"},
    )
    item_b, created_b = ensure_review_item(
        session,
        scope=scope_b,
        review_key="same-review-key",
        type_="low_confidence",
        subject={"same": "content"},
    )

    assert created_a and created_b and not created_again_a
    assert again_a.id == item_a.id and item_b.id != item_a.id
    assert get_review_item(session, scope_a, "same-review-key") == item_a
    assert get_review_item(session, scope_b, "same-review-key") == item_b
    assert _count(session, ReviewItem) == 2


def test_s2_3_resolve_review_hides_cross_scope_item(session: Session) -> None:
    scope_a = _scope(session, "a")
    scope_b = _scope(session, "b")
    _, version_b = seed_product(session, scope=scope_b)
    engine_b = MergeEngine(session, scope=scope_b)
    review_key_b = _apply(
        engine_b,
        _proposal(scope_b, version_b.id),
        external_record_id="batch-b",
    )
    review_b = get_review_item(session, scope_b, review_key_b)
    assert review_b is not None
    claim_b = session.execute(select(Claim)).scalar_one()

    _assert_generic_scope_error(
        lambda: resolve_review(session, scope_a, review_key_b, "approve", actor="intruder")
    )

    session.refresh(review_b)
    session.refresh(claim_b)
    assert review_b.status == "open" and review_b.resolution is None
    assert claim_b.status == "candidate"


def test_s2_3_overturn_review_hides_cross_scope_item(session: Session) -> None:
    scope_a = _scope(session, "a")
    scope_b = _scope(session, "b")
    _, version_b = seed_product(session, scope=scope_b)
    engine_b = MergeEngine(session, scope=scope_b)
    review_key_b = _apply(
        engine_b,
        _proposal(scope_b, version_b.id),
        external_record_id="batch-b",
    )
    resolve_review(session, scope_b, review_key_b, "approve", actor="reviewer-b")
    changes_before = _count(session, ChangeSet)
    claim_b = session.execute(select(Claim)).scalar_one()

    _assert_generic_scope_error(
        lambda: overturn_review(
            session,
            scope_a,
            review_key_b,
            "reject",
            actor="intruder",
            reason="must not reveal B",
        )
    )

    session.refresh(claim_b)
    assert claim_b.status == "published"
    assert _count(session, ChangeSet) == changes_before


def test_s2_3_retract_source_hides_cross_scope_source_with_scoped_tombstone(
    session: Session,
) -> None:
    scope_a = _scope(session, "a")
    scope_b = _scope(session, "b")
    _, version_b = seed_product(session, scope=scope_b)
    engine_b = MergeEngine(session, scope=scope_b, policy=MergePolicy(auto_apply_add=True),
        quality_gate=_GATE, run_fingerprint=_FP)
    _apply(
        engine_b,
        _proposal(scope_b, version_b.id, knowledge_id="knowledge-only-in-b"),
        external_record_id="batch-b",
    )
    claim_b = session.execute(select(Claim)).scalar_one()
    evidence_before = _count(session, ClaimEvidence)
    changes_before = _count(session, ChangeSet)

    first = retract_source(
        session,
        scope_a,
        "knowledge-only-in-b",
        legacy_replay=True,
    )
    second = retract_source(
        session,
        scope_a,
        "knowledge-only-in-b",
        legacy_replay=True,
    )

    session.refresh(claim_b)
    assert first == second
    assert first.actions == {}
    assert claim_b.status == "published"
    assert _count(session, ClaimEvidence) == evidence_before
    assert _count(session, ChangeSet) == changes_before + 1
    tombstone = session.get(ChangeSet, first.change_set_id)
    assert tombstone is not None and tombstone.space_id == scope_a.space_id


def test_s2_3_retract_source_records_tombstone_when_source_does_not_exist(
    session: Session,
) -> None:
    scope_a = _scope(session, "a")
    changes_before = _count(session, ChangeSet)

    first = retract_source(
        session,
        scope_a,
        "knowledge-nowhere",
        legacy_replay=True,
    )
    second = retract_source(
        session,
        scope_a,
        "knowledge-nowhere",
        legacy_replay=True,
    )

    assert first == second
    assert first.actions == {}
    assert _count(session, ClaimEvidence) == 0
    assert _count(session, ChangeSet) == changes_before + 1


def test_s2_3_mismatched_proposal_rejected_before_batch_writes(session: Session) -> None:
    scope_a = _scope(session, "a")
    scope_b = _scope(session, "b")
    _, version_a = seed_product(session, scope=scope_a)
    _, version_b = seed_product(session, scope=scope_b)
    engine_a = MergeEngine(session, scope=scope_a)
    change_set_a, _ = engine_a.open_change_set(
        source_kind="document",
        external_record_id="batch-a",
    )
    counts_before = {
        table: _count(session, table)
        for table in (ChangeSet, Claim, ChangeItem, ReviewItem)
    }

    _assert_generic_scope_error(
        lambda: engine_a.apply_batch(
            change_set_a,
            [
                _proposal(scope_a, version_a.id, predicate="waiting_period"),
                _proposal(scope_b, version_b.id, predicate="grace_period"),
            ],
        )
    )

    assert {
        table: _count(session, table)
        for table in (ChangeSet, Claim, ChangeItem, ReviewItem)
    } == counts_before
    session.refresh(change_set_a)
    assert change_set_a.status == "pending"


def test_s2_3_importer_rejects_cross_scope_product_inputs_before_writes(
    session: Session,
) -> None:
    scope_a = _scope(session, "a")
    scope_b = _scope(session, "b")
    product_a, version_a = seed_product(session, scope=scope_a)
    product_b, version_b = seed_product(session, scope=scope_b)
    records = [pred("waiting_period", value="90天", quote="等待期为90天")]

    _assert_generic_scope_error(
        lambda: import_pred_records(
            session,
            records,
            scope=scope_a,
            product_id=product_a.product_code,
            product_version_id=version_b.id,
            legacy_replay=True,
        )
    )
    _assert_generic_scope_error(
        lambda: import_pred_records(
            session,
            records,
            scope=scope_a,
            product_id=product_b.id,
            product_version_id=version_a.id,
            legacy_replay=True,
        )
    )

    assert _count(session, ChangeSet) == 0
    assert _count(session, Claim) == 0
    assert _count(session, ChangeItem) == 0
    assert _count(session, ReviewItem) == 0


def test_s2_5_importer_batch_and_record_idempotency_are_scoped(session: Session) -> None:
    scope_a = _scope(session, "a")
    scope_b = _scope(session, "b")
    product_a, version_a = seed_product(session, scope=scope_a)
    product_b, version_b = seed_product(session, scope=scope_b)
    records = [pred("waiting_period", value="90天", quote="等待期为90天")]

    report_a = import_pred_records(
        session,
        records,
        scope=scope_a,
        product_id=product_a.product_code,
        product_version_id=version_a.id,
        source_revision="r1",
        legacy_replay=True,
    )
    report_b = import_pred_records(
        session,
        records,
        scope=scope_b,
        product_id=product_b.product_code,
        product_version_id=version_b.id,
        source_revision="r1",
        legacy_replay=True,
    )
    duplicate_a = import_pred_records(
        session,
        records,
        scope=scope_a,
        product_id=product_a.product_code,
        product_version_id=version_a.id,
        source_revision="r1",
        legacy_replay=True,
    )
    record_duplicate_a = import_pred_records(
        session,
        records,
        scope=scope_a,
        product_id=product_a.product_code,
        product_version_id=version_a.id,
        source_revision="r2",
        legacy_replay=True,
    )

    assert report_a.imported == report_b.imported == 1
    assert report_a.change_set_id != report_b.change_set_id
    assert duplicate_a.duplicate_batch is True
    assert record_duplicate_a.skipped_duplicates == 1
    assert _count(session, Claim) == 2
    assert _count(session, ChangeSet) == 3


def test_s2_2_child_operations_validate_scoped_parent_and_claims(session: Session) -> None:
    scope_a = _scope(session, "a")
    scope_b = _scope(session, "b")
    _, version_a = seed_product(session, scope=scope_a)
    _, version_b = seed_product(session, scope=scope_b)
    engine_a = MergeEngine(session, scope=scope_a)
    engine_b = MergeEngine(session, scope=scope_b)
    _apply(engine_b, _proposal(scope_b, version_b.id), external_record_id="batch-b")
    claim_b = session.execute(
        select(Claim).where(Claim.space_id == scope_b.space_id)
    ).scalar_one()

    change_set_a, _ = engine_a.open_change_set(
        source_kind="manual_edit",
        external_record_id="malicious-a",
    )
    malicious_item = ChangeItem(
        change_set_id=change_set_a.id,
        action="add",
        claim_id=claim_b.id,
        proposed={"claim": {"value": "must-not-apply"}},
        decision="needs_review",
    )
    session.add(malicious_item)
    session.flush()
    _assert_generic_scope_error(
        lambda: apply_change_item(session, scope_a, malicious_item, actor="intruder")
    )
    _assert_generic_scope_error(
        lambda: reject_change_item(session, scope_a, malicious_item, actor="intruder")
    )

    review_key_a = _apply(
        engine_a,
        _proposal(scope_a, version_a.id),
        external_record_id="batch-a",
    )
    review_a = get_review_item(session, scope_a, review_key_a)
    assert review_a is not None
    item_a = session.get(ChangeItem, review_a.subject["change_item_id"])
    assert item_a is not None
    item_a.proposed = {**item_a.proposed, "existing_claim_id": claim_b.id}
    conflict_a = Conflict(
        change_item_id=item_a.id,
        existing_claim_id=claim_b.id,
        proposed={"value": "malicious cross-space old claim"},
        status="pending_judge",
    )
    session.add(conflict_a)
    session.flush()
    _assert_generic_scope_error(
        lambda: apply_conflict_judgements(
            session,
            scope_a,
            [
                ConflictJudgement(
                    conflict_id=conflict_a.id,
                    winner="proposed",
                    reasoning="must not execute",
                )
            ],
        )
    )

    session.refresh(claim_b)
    session.refresh(item_a)
    session.refresh(conflict_a)
    assert claim_b.status == "candidate"
    assert item_a.decision == "needs_review"
    assert conflict_a.status == "pending_judge"


def test_s2_2_publish_claim_rejects_cross_scope_change_item_lineage(
    session: Session,
) -> None:
    scope_a = _scope(session, "a")
    scope_b = _scope(session, "b")
    _, version_a = seed_product(session, scope=scope_a)
    _, version_b = seed_product(session, scope=scope_b)
    engine_a = MergeEngine(session, scope=scope_a)
    engine_b = MergeEngine(session, scope=scope_b)
    review_key_a = _apply(
        engine_a,
        _proposal(scope_a, version_a.id),
        external_record_id="batch-a",
    )
    review_key_b = _apply(
        engine_b,
        _proposal(scope_b, version_b.id),
        external_record_id="batch-b",
    )
    review_a = get_review_item(session, scope_a, review_key_a)
    review_b = get_review_item(session, scope_b, review_key_b)
    assert review_a is not None and review_b is not None
    claim_a = session.execute(
        select(Claim).where(Claim.space_id == scope_a.space_id)
    ).scalar_one()
    item_b = session.get(ChangeItem, review_b.subject["change_item_id"])
    assert item_b is not None
    revision_before = claim_a.current_revision

    _assert_generic_scope_error(
        lambda: publish_claim(
            session,
            scope_a,
            claim_a,
            change_item_id=item_b.id,
            actor="intruder",
        )
    )

    session.refresh(claim_a)
    assert claim_a.status == "candidate"
    assert claim_a.current_revision == revision_before


def test_s2_3_claim_evidence_rejects_cross_scope_bare_claim_id(
    session: Session,
) -> None:
    scope_a = _scope(session, "a")
    scope_b = _scope(session, "b")
    _, version_b = seed_product(session, scope=scope_b)
    engine_b = MergeEngine(session, scope=scope_b, policy=MergePolicy(auto_apply_add=True),
        quality_gate=_GATE, run_fingerprint=_FP)
    _apply(
        engine_b,
        _proposal(scope_b, version_b.id),
        external_record_id="batch-b",
    )
    claim_b = session.execute(
        select(Claim).where(Claim.space_id == scope_b.space_id)
    ).scalar_one()
    assert _count(session, ClaimEvidence) == 1

    _assert_generic_scope_error(
        lambda: claim_evidence(session, scope_a, claim_b.id)
    )


def test_s2_2_ensure_review_validates_all_known_subject_references(
    session: Session,
) -> None:
    scope_a = _scope(session, "review-a")
    scope_b = _scope(session, "review-b")
    conflict_b, item_b, claim_b, _ = _pending_conflict(session, scope_b, "review-b")
    reviews_before = _count(session, ReviewItem)
    invalid_subjects = [
        {"change_item_id": item_b.id},
        {"new_claim_id": claim_b.id},
        {"conflict_id": conflict_b.id},
        {"change_item_id": "missing-item"},
    ]

    for index, subject in enumerate(invalid_subjects):
        def call(
            current_index: int = index,
            current_subject: dict[str, str] = subject,
        ) -> None:
            ensure_review_item(
                session,
                scope=scope_a,
                review_key=f"invalid-review-{current_index}",
                type_="low_confidence",
                subject=current_subject,
            )

        _assert_generic_scope_error(call)

    assert _count(session, ReviewItem) == reviews_before


def test_s2_2_resolve_review_revalidates_entire_subject_before_mutation(
    session: Session,
) -> None:
    scope_a = _scope(session, "resolve-a")
    scope_b = _scope(session, "resolve-b")
    _, version_a = seed_product(session, scope=scope_a, code="RESOLVE-A")
    engine_a = MergeEngine(session, scope=scope_a)
    review_key_a = _apply(
        engine_a,
        _proposal(scope_a, version_a.id),
        external_record_id="resolve-a",
    )
    review_a = get_review_item(session, scope_a, review_key_a)
    assert review_a is not None
    item_a = session.get(ChangeItem, review_a.subject["change_item_id"])
    assert item_a is not None and item_a.claim_id is not None
    claim_a = session.get(Claim, item_a.claim_id)
    assert claim_a is not None
    conflict_b, _, claim_b, _ = _pending_conflict(session, scope_b, "resolve-b")
    review_a.subject = {
        **review_a.subject,
        "new_claim_id": claim_b.id,
        "conflict_id": conflict_b.id,
    }
    session.flush()
    revision_before = claim_a.current_revision

    _assert_generic_scope_error(
        lambda: resolve_review(
            session,
            scope_a,
            review_key_a,
            "approve",
            actor="intruder",
        )
    )

    session.refresh(review_a)
    session.refresh(item_a)
    session.refresh(claim_a)
    assert review_a.status == "open" and review_a.resolution is None
    assert item_a.decision == "needs_review"
    assert claim_a.status == "candidate"
    assert claim_a.current_revision == revision_before


def test_s2_2_overturn_review_revalidates_entire_subject_before_mutation(
    session: Session,
) -> None:
    scope_a = _scope(session, "overturn-a")
    scope_b = _scope(session, "overturn-b")
    _, version_a = seed_product(session, scope=scope_a, code="OVERTURN-A")
    engine_a = MergeEngine(session, scope=scope_a)
    review_key_a = _apply(
        engine_a,
        _proposal(scope_a, version_a.id),
        external_record_id="overturn-a",
    )
    resolve_review(session, scope_a, review_key_a, "approve", actor="reviewer-a")
    review_a = get_review_item(session, scope_a, review_key_a)
    assert review_a is not None
    item_a = session.get(ChangeItem, review_a.subject["change_item_id"])
    assert item_a is not None and item_a.claim_id is not None
    claim_a = session.get(Claim, item_a.claim_id)
    assert claim_a is not None
    conflict_b, _, claim_b, _ = _pending_conflict(session, scope_b, "overturn-b")
    review_a.subject = {
        **review_a.subject,
        "new_claim_id": claim_b.id,
        "conflict_id": conflict_b.id,
    }
    session.flush()
    changes_before = _count(session, ChangeSet)
    revision_before = claim_a.current_revision

    _assert_generic_scope_error(
        lambda: overturn_review(
            session,
            scope_a,
            review_key_a,
            "reject",
            actor="intruder",
            reason="must fail closed",
        )
    )

    session.refresh(review_a)
    session.refresh(claim_a)
    assert review_a.resolution is not None
    assert review_a.resolution["action"] == "approve"
    assert claim_a.status == "published"
    assert claim_a.current_revision == revision_before
    assert _count(session, ChangeSet) == changes_before


def test_s2_2_ensure_review_rejects_same_scope_mismatched_subject_aggregate(
    session: Session,
) -> None:
    scope = _scope(session, "ensure-aggregate")
    _, item, _, conflict, conflict_claim = _same_scope_review_mismatch(
        session, scope, "ensure-aggregate"
    )
    reviews_before = _count(session, ReviewItem)

    _assert_generic_scope_error(
        lambda: ensure_review_item(
            session,
            scope=scope,
            review_key="same-scope-mismatched-subject",
            type_="low_confidence",
            subject={
                "change_item_id": item.id,
                "new_claim_id": conflict_claim.id,
                "conflict_id": conflict.id,
            },
        )
    )

    assert _count(session, ReviewItem) == reviews_before


@pytest.mark.parametrize("ref_name", ["new_claim_id", "conflict_id"])
def test_s2_2_ensure_review_requires_change_item_anchor_for_child_reference(
    session: Session,
    ref_name: str,
) -> None:
    scope = _scope(session, f"review-anchor-{ref_name}")
    conflict, _, candidate, _ = _pending_conflict(
        session, scope, f"review-anchor-{ref_name}"
    )
    child_id = candidate.id if ref_name == "new_claim_id" else conflict.id
    reviews_before = _count(session, ReviewItem)

    _assert_generic_scope_error(
        lambda: ensure_review_item(
            session,
            scope=scope,
            review_key=f"missing-anchor-{ref_name}",
            type_="low_confidence",
            subject={ref_name: child_id},
        )
    )

    assert _count(session, ReviewItem) == reviews_before


def test_s2_2_resolve_review_rejects_same_scope_mismatched_subject_aggregate(
    session: Session,
) -> None:
    scope = _scope(session, "resolve-aggregate")
    review, item, claim, conflict, conflict_claim = _same_scope_review_mismatch(
        session, scope, "resolve-aggregate"
    )
    review.subject = {
        **review.subject,
        "new_claim_id": conflict_claim.id,
        "conflict_id": conflict.id,
    }
    session.flush()
    revision_before = claim.current_revision

    _assert_generic_scope_error(
        lambda: resolve_review(
            session,
            scope,
            review.review_key,
            "approve",
            actor="intruder",
        )
    )

    session.refresh(review)
    session.refresh(item)
    session.refresh(claim)
    assert review.status == "open" and review.resolution is None
    assert item.decision == "needs_review"
    assert claim.status == "candidate"
    assert claim.current_revision == revision_before


def test_s2_2_overturn_review_rejects_same_scope_mismatched_subject_aggregate(
    session: Session,
) -> None:
    scope = _scope(session, "overturn-aggregate")
    review, _, claim, conflict, conflict_claim = _same_scope_review_mismatch(
        session, scope, "overturn-aggregate"
    )
    resolve_review(session, scope, review.review_key, "approve", actor="reviewer")
    review.subject = {
        **review.subject,
        "new_claim_id": conflict_claim.id,
        "conflict_id": conflict.id,
    }
    session.flush()
    changes_before = _count(session, ChangeSet)
    revision_before = claim.current_revision

    _assert_generic_scope_error(
        lambda: overturn_review(
            session,
            scope,
            review.review_key,
            "reject",
            actor="intruder",
            reason="must fail closed",
        )
    )

    session.refresh(review)
    session.refresh(claim)
    assert review.resolution is not None
    assert review.resolution["action"] == "approve"
    assert claim.status == "published"
    assert claim.current_revision == revision_before
    assert _count(session, ChangeSet) == changes_before


@pytest.mark.parametrize("operation", ["apply", "reject"])
def test_s2_2_change_item_validates_all_conflicts_before_claim_mutation(
    session: Session,
    operation: str,
) -> None:
    scope_a = _scope(session, f"item-a-{operation}")
    scope_b = _scope(session, f"item-b-{operation}")
    _, version_a = seed_product(session, scope=scope_a, code=f"ITEM-A-{operation}")
    engine_a = MergeEngine(session, scope=scope_a)
    review_key_a = _apply(
        engine_a,
        _proposal(scope_a, version_a.id),
        external_record_id=f"item-a-{operation}",
    )
    review_a = get_review_item(session, scope_a, review_key_a)
    assert review_a is not None
    item_a = session.get(ChangeItem, review_a.subject["change_item_id"])
    assert item_a is not None and item_a.claim_id is not None
    claim_a = session.get(Claim, item_a.claim_id)
    assert claim_a is not None
    _, _, claim_b, _ = _pending_conflict(session, scope_b, f"item-b-{operation}")
    malicious_conflict = Conflict(
        change_item_id=item_a.id,
        existing_claim_id=claim_b.id,
        proposed={"space_id": scope_a.space_id, "value": "malicious"},
        status="pending_judge",
    )
    session.add(malicious_conflict)
    session.flush()
    revision_before = claim_a.current_revision

    def call() -> None:
        if operation == "apply":
            apply_change_item(session, scope_a, item_a, actor="intruder")
        else:
            reject_change_item(session, scope_a, item_a, actor="intruder")

    _assert_generic_scope_error(call)

    session.refresh(item_a)
    session.refresh(claim_a)
    session.refresh(malicious_conflict)
    assert item_a.decision == "needs_review"
    assert claim_a.status == "candidate"
    assert claim_a.current_revision == revision_before
    assert malicious_conflict.status == "pending_judge"


@pytest.mark.parametrize("operation", ["apply", "reject"])
@pytest.mark.parametrize("corruption", ["existing_claim", "proposed_version"])
def test_s2_2_change_item_rejects_same_scope_conflict_parent_mismatch(
    session: Session,
    operation: str,
    corruption: str,
) -> None:
    scope = _scope(session, f"conflict-parent-{operation}-{corruption}")
    conflict, item, candidate, existing = _pending_conflict(
        session, scope, f"conflict-parent-{operation}-{corruption}"
    )
    _, other_version = seed_product(
        session,
        scope=scope,
        code=f"OTHER-{operation}-{corruption}",
    )
    _apply(
        MergeEngine(session, scope=scope, policy=MergePolicy(auto_apply_add=True),
        quality_gate=_GATE, run_fingerprint=_FP),
        _proposal(scope, other_version.id, predicate="grace_period"),
        external_record_id=f"other-{operation}-{corruption}",
    )
    unrelated = session.execute(
        select(Claim).where(Claim.product_version_id == other_version.id)
    ).scalar_one()
    if corruption == "existing_claim":
        conflict.existing_claim_id = unrelated.id
    else:
        conflict.proposed = {
            **conflict.proposed,
            "product_version_id": other_version.id,
        }
    session.flush()
    candidate_revision = candidate.current_revision
    existing_revision = existing.current_revision
    unrelated_revision = unrelated.current_revision

    def call() -> None:
        if operation == "apply":
            apply_change_item(session, scope, item, actor="intruder")
        else:
            reject_change_item(session, scope, item, actor="intruder")

    _assert_generic_scope_error(call)

    session.refresh(conflict)
    session.refresh(item)
    session.refresh(candidate)
    session.refresh(existing)
    session.refresh(unrelated)
    assert conflict.status == "pending_judge"
    assert item.decision == "needs_review"
    assert candidate.status == "candidate"
    assert existing.status == unrelated.status == "published"
    assert candidate.current_revision == candidate_revision
    assert existing.current_revision == existing_revision
    assert unrelated.current_revision == unrelated_revision


def test_s2_2_conflict_existing_winner_rejects_jointly_tampered_old_subject(
    session: Session,
) -> None:
    scope = _scope(session, "conflict-joint-old")
    conflict, item, candidate, existing = _pending_conflict(
        session, scope, "conflict-joint-old"
    )
    assert candidate.product_version_id is not None
    _apply(
        MergeEngine(session, scope=scope, policy=MergePolicy(auto_apply_add=True),
        quality_gate=_GATE, run_fingerprint=_FP),
        _proposal(
            scope,
            candidate.product_version_id,
            predicate="grace_period",
        ),
        external_record_id="conflict-joint-old-unrelated",
    )
    unrelated = session.execute(
        select(Claim).where(
            Claim.product_version_id == candidate.product_version_id,
            Claim.predicate == "grace_period",
        )
    ).scalar_one()
    item.proposed = {**item.proposed, "existing_claim_id": unrelated.id}
    conflict.existing_claim_id = unrelated.id
    session.flush()
    candidate_revision = candidate.current_revision
    existing_revision = existing.current_revision
    unrelated_revision = unrelated.current_revision

    _assert_generic_scope_error(
        lambda: apply_conflict_judgements(
            session,
            scope,
            [
                ConflictJudgement(
                    conflict_id=conflict.id,
                    winner="existing",
                    reasoning="tampered old must fail closed",
                )
            ],
        )
    )

    session.refresh(conflict)
    session.refresh(item)
    session.refresh(candidate)
    session.refresh(existing)
    session.refresh(unrelated)
    assert conflict.status == "pending_judge"
    assert item.decision == "needs_review"
    assert candidate.status == "candidate"
    assert existing.status == unrelated.status == "published"
    assert candidate.current_revision == candidate_revision
    assert existing.current_revision == existing_revision
    assert unrelated.current_revision == unrelated_revision


@pytest.mark.parametrize("winner", ["proposed", "existing"])
@pytest.mark.parametrize("field", ["value", "value_state"])
def test_s2_2_conflict_judgement_rejects_tampered_proposed_fact(
    session: Session,
    winner: Literal["proposed", "existing"],
    field: str,
) -> None:
    scope = _scope(session, f"conflict-fact-{winner}-{field}")
    conflict, item, candidate, existing = _pending_conflict(
        session, scope, f"conflict-fact-{winner}-{field}"
    )
    conflict.proposed = {
        **conflict.proposed,
        field: "tampered" if field == "value" else "absent_explicitly",
    }
    session.flush()
    candidate_revision = candidate.current_revision
    existing_revision = existing.current_revision

    _assert_generic_scope_error(
        lambda: apply_conflict_judgements(
            session,
            scope,
            [
                ConflictJudgement(
                    conflict_id=conflict.id,
                    winner=winner,
                    reasoning="tampered fact must fail closed",
                )
            ],
        )
    )

    session.refresh(conflict)
    session.refresh(item)
    session.refresh(candidate)
    session.refresh(existing)
    assert conflict.status == "pending_judge"
    assert item.decision == "needs_review"
    assert candidate.status == "candidate"
    assert existing.status == "published"
    assert candidate.current_revision == candidate_revision
    assert existing.current_revision == existing_revision


def test_s2_2_conflict_judgement_closes_jointly_tampered_proposal_to_claim(
    session: Session,
) -> None:
    scope = _scope(session, "conflict-joint-proposal")
    conflict, item, candidate, existing = _pending_conflict(
        session, scope, "conflict-joint-proposal"
    )
    item_claim = item.proposed["claim"]
    assert isinstance(item_claim, dict)
    item.proposed = {
        **item.proposed,
        "claim": {**item_claim, "value": "jointly tampered"},
    }
    conflict.proposed = {**conflict.proposed, "value": "jointly tampered"}
    session.flush()
    candidate_revision = candidate.current_revision
    existing_revision = existing.current_revision

    _assert_generic_scope_error(
        lambda: apply_conflict_judgements(
            session,
            scope,
            [
                ConflictJudgement(
                    conflict_id=conflict.id,
                    winner="proposed",
                    reasoning="two JSON copies cannot override the Claim",
                )
            ],
        )
    )

    session.refresh(conflict)
    session.refresh(item)
    session.refresh(candidate)
    session.refresh(existing)
    assert conflict.status == "pending_judge"
    assert item.decision == "needs_review"
    assert candidate.status == "candidate"
    assert existing.status == "published"
    assert candidate.current_revision == candidate_revision
    assert existing.current_revision == existing_revision


def test_s2_2_publish_claim_must_match_change_item_claim(session: Session) -> None:
    scope_a = _scope(session, "publish-claim")
    _, version_a = seed_product(session, scope=scope_a, code="PUBLISH-CLAIM")
    engine_a = MergeEngine(session, scope=scope_a)
    waiting_key = _apply(
        engine_a,
        _proposal(scope_a, version_a.id, predicate="waiting_period"),
        external_record_id="publish-waiting",
    )
    grace_key = _apply(
        engine_a,
        _proposal(scope_a, version_a.id, predicate="grace_period"),
        external_record_id="publish-grace",
    )
    waiting_review = get_review_item(session, scope_a, waiting_key)
    grace_review = get_review_item(session, scope_a, grace_key)
    assert waiting_review is not None and grace_review is not None
    waiting_item = session.get(ChangeItem, waiting_review.subject["change_item_id"])
    grace_item = session.get(ChangeItem, grace_review.subject["change_item_id"])
    assert waiting_item is not None and grace_item is not None
    assert grace_item.claim_id is not None
    grace_claim = session.get(Claim, grace_item.claim_id)
    assert grace_claim is not None
    revision_before = grace_claim.current_revision

    _assert_generic_scope_error(
        lambda: publish_claim(
            session,
            scope_a,
            grace_claim,
            change_item_id=waiting_item.id,
            actor="intruder",
        )
    )

    session.refresh(grace_claim)
    assert grace_claim.status == "candidate"
    assert grace_claim.current_revision == revision_before


def test_s2_2_publish_add_rejects_unexpected_superseding_claim(
    session: Session,
) -> None:
    scope_a = _scope(session, "publish-semantics")
    _, version_a = seed_product(session, scope=scope_a, code="PUBLISH-SEMANTICS")
    engine_a = MergeEngine(session, scope=scope_a)
    waiting_key = _apply(
        engine_a,
        _proposal(scope_a, version_a.id, predicate="waiting_period"),
        external_record_id="semantics-waiting",
    )
    grace_key = _apply(
        engine_a,
        _proposal(scope_a, version_a.id, predicate="grace_period"),
        external_record_id="semantics-grace",
    )
    waiting_review = get_review_item(session, scope_a, waiting_key)
    grace_review = get_review_item(session, scope_a, grace_key)
    assert waiting_review is not None and grace_review is not None
    waiting_item = session.get(ChangeItem, waiting_review.subject["change_item_id"])
    grace_item = session.get(ChangeItem, grace_review.subject["change_item_id"])
    assert waiting_item is not None and grace_item is not None
    assert waiting_item.claim_id is not None and grace_item.claim_id is not None
    waiting_claim = session.get(Claim, waiting_item.claim_id)
    grace_claim = session.get(Claim, grace_item.claim_id)
    assert waiting_claim is not None and grace_claim is not None
    waiting_revision = waiting_claim.current_revision
    grace_revision = grace_claim.current_revision

    _assert_generic_scope_error(
        lambda: publish_claim(
            session,
            scope_a,
            waiting_claim,
            change_item_id=waiting_item.id,
            actor="intruder",
            superseding=grace_claim,
        )
    )

    session.refresh(waiting_claim)
    session.refresh(grace_claim)
    assert waiting_claim.status == grace_claim.status == "candidate"
    assert waiting_claim.current_revision == waiting_revision
    assert grace_claim.current_revision == grace_revision


@pytest.mark.parametrize("mismatch", ["predicate", "version"])
def test_s2_2_publish_rejects_same_scope_superseding_subject_mismatch(
    session: Session,
    mismatch: str,
) -> None:
    scope = _scope(session, f"publish-subject-{mismatch}")
    conflict, item, candidate, existing = _pending_conflict(
        session, scope, f"publish-subject-{mismatch}"
    )
    assert candidate.product_version_id is not None
    if mismatch == "predicate":
        unrelated_version_id = candidate.product_version_id
        unrelated_predicate = "grace_period"
    else:
        _, unrelated_version = seed_product(
            session,
            scope=scope,
            code="PUBLISH-OTHER-VERSION",
        )
        unrelated_version_id = unrelated_version.id
        unrelated_predicate = candidate.predicate
    _apply(
        MergeEngine(session, scope=scope, policy=MergePolicy(auto_apply_add=True),
        quality_gate=_GATE, run_fingerprint=_FP),
        _proposal(
            scope,
            unrelated_version_id,
            predicate=unrelated_predicate,
        ),
        external_record_id=f"publish-unrelated-{mismatch}",
    )
    unrelated = session.execute(
        select(Claim).where(
            Claim.product_version_id == unrelated_version_id,
            Claim.predicate == unrelated_predicate,
        )
    ).scalar_one()
    item.proposed = {**item.proposed, "existing_claim_id": unrelated.id}
    conflict.existing_claim_id = unrelated.id
    session.flush()
    candidate_revision = candidate.current_revision
    existing_revision = existing.current_revision
    unrelated_revision = unrelated.current_revision

    _assert_generic_scope_error(
        lambda: publish_claim(
            session,
            scope,
            candidate,
            change_item_id=item.id,
            actor="intruder",
            superseding=unrelated,
        )
    )

    session.refresh(conflict)
    session.refresh(candidate)
    session.refresh(existing)
    session.refresh(unrelated)
    assert conflict.status == "pending_judge"
    assert candidate.status == "candidate"
    assert existing.status == unrelated.status == "published"
    assert candidate.current_revision == candidate_revision
    assert existing.current_revision == existing_revision
    assert unrelated.current_revision == unrelated_revision


def test_s2_3_conflict_judgements_prevalidate_entire_batch(session: Session) -> None:
    scope_a = _scope(session, "judge-a")
    scope_b = _scope(session, "judge-b")
    conflict_a, item_a, candidate_a, existing_a = _pending_conflict(
        session, scope_a, "judge-a"
    )
    conflict_b, _, _, _ = _pending_conflict(session, scope_b, "judge-b")
    candidate_revision = candidate_a.current_revision
    existing_revision = existing_a.current_revision

    _assert_generic_scope_error(
        lambda: apply_conflict_judgements(
            session,
            scope_a,
            [
                ConflictJudgement(
                    conflict_id=conflict_a.id,
                    winner="proposed",
                    reasoning="valid A",
                ),
                ConflictJudgement(
                    conflict_id=conflict_b.id,
                    winner="proposed",
                    reasoning="invalid B",
                ),
            ],
        )
    )

    session.refresh(conflict_a)
    session.refresh(item_a)
    session.refresh(candidate_a)
    session.refresh(existing_a)
    assert conflict_a.status == "pending_judge"
    assert item_a.decision == "needs_review"
    assert candidate_a.status == "candidate"
    assert existing_a.status == "published"
    assert candidate_a.current_revision == candidate_revision
    assert existing_a.current_revision == existing_revision


@pytest.mark.parametrize(
    "name",
    ["create_claim", "write_revision", "supersede_claim", "retract_claim"],
)
def test_s2_3_merge_module_does_not_expose_bare_mutation_helpers(name: str) -> None:
    assert not hasattr(merge_module, name)


def test_s2_4_importer_normalizes_product_code_and_uuid_for_batch_key(
    session: Session,
) -> None:
    scope_a = _scope(session, "canonical-import")
    product_a, version_a = seed_product(
        session,
        scope=scope_a,
        code="CANONICAL-IMPORT",
    )
    records = [pred("waiting_period", value="90天", quote="等待期为90天")]
    first = import_pred_records(
        session,
        records,
        scope=scope_a,
        product_id=product_a.product_code,
        product_version_id=version_a.id,
        source_revision="same-revision",
        legacy_replay=True,
    )
    second = import_pred_records(
        session,
        records,
        scope=scope_a,
        product_id=product_a.id,
        product_version_id=version_a.id,
        source_revision="same-revision",
        legacy_replay=True,
    )

    assert second.duplicate_batch is True
    assert second.change_set_id == first.change_set_id
    assert _count(session, ChangeSet) == 1
