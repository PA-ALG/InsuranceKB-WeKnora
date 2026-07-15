"""Source import, tombstone and aggregate contracts."""

from typing import Any, cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from insurance_harness.db.scope import ScopeViolation
from insurance_harness.knowledge import MergePolicy, import_pred_records, retract_source
from insurance_harness.knowledge import source_revision as revision_service
from insurance_harness.knowledge.models import ProposedClaim
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    ClaimEvidence,
    Conflict,
)
from tests.kbhelpers import allow_all_gate, seed_product
from tests.support.source_revision import (
    NOW,
    bound_scope,
    claim_with_evidence,
    count_rows,
    source_identity,
    source_record,
)

_GATE, _FP = allow_all_gate()  # fail-closed 后自动发布须过 gate；发布仍需 auto_apply 位


def test_t7_t6_importer_populates_pending_recompile_without_document_changeset(
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
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-T7",
        name="Import T7",
    )
    new = source_identity(scope, revision_char="b")
    notification = revision_service.notify_source_revision(
        kb_session,
        scope,
        new,
        observed_at=NOW,
    )

    report = import_pred_records(
        kb_session,
        [source_record(new)],
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
    assert count_rows(kb_session, ChangeItem) == 1


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
    scope = bound_scope(kb_session)
    product, version = seed_product(
        kb_session,
        scope=scope,
        code=f"IMPORT-T7-MALFORMED-{status}-{len(knowledge_ids or [])}",
        name="Import T7 malformed source ChangeSet",
    )
    identity = source_identity(scope, revision_char="b")
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
            [source_record(identity)],
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
    assert count_rows(kb_session, ChangeSet) == 1
    assert count_rows(kb_session, ChangeItem) == 0
    assert count_rows(kb_session, Claim) == 0
    assert count_rows(kb_session, ClaimEvidence) == 0
    assert kb_session.scalar(select(func.count()).select_from(ChangeSet)) == 1


def test_t7_importer_rejects_applied_duplicate_with_cross_scope_item_claim(
    kb_session: Session,
) -> None:
    scope_a = bound_scope(kb_session, "duplicate-item-a")
    scope_b = bound_scope(kb_session, "duplicate-item-b")
    product_a, version_a = seed_product(
        kb_session,
        scope=scope_a,
        code="IMPORT-T7-DUPLICATE-ITEM-A",
        name="Import T7 duplicate item A",
    )
    claim_b, _ = claim_with_evidence(
        kb_session,
        scope_b,
        predicate="cross_scope_duplicate_item",
        identities=[source_identity(scope_b, revision_char="c")],
    )
    identity = source_identity(scope_a, revision_char="b")
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
        table: count_rows(kb_session, table)
        for table in (ChangeSet, ChangeItem, Claim, ClaimEvidence)
    }

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        import_pred_records(
            kb_session,
            [source_record(identity)],
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
        table: count_rows(kb_session, table) for table in baseline
    } == baseline
    assert kb_session.scalar(select(func.count()).select_from(ChangeSet)) == 1


def test_t7_importer_rejects_applied_duplicate_with_cross_scope_conflict_refs(
    kb_session: Session,
) -> None:
    scope_a = bound_scope(kb_session, "duplicate-conflict-a")
    scope_b = bound_scope(kb_session, "duplicate-conflict-b")
    product_a, version_a = seed_product(
        kb_session,
        scope=scope_a,
        code="IMPORT-T7-DUPLICATE-CONFLICT-A",
        name="Import T7 duplicate conflict A",
    )
    claim_b, _ = claim_with_evidence(
        kb_session,
        scope_b,
        predicate="cross_scope_duplicate_conflict",
        identities=[source_identity(scope_b, revision_char="c")],
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
    identity = source_identity(scope_a, revision_char="b")
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
        table: count_rows(kb_session, table)
        for table in (ChangeSet, ChangeItem, Conflict, Claim, ClaimEvidence)
    }

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        import_pred_records(
            kb_session,
            [source_record(identity)],
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
        table: count_rows(kb_session, table) for table in baseline
    } == baseline
    assert kb_session.scalar(select(func.count()).select_from(ChangeSet)) == 1


def test_t7_importer_accepts_applied_duplicate_with_scoped_winner_existing_conflict(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session, "duplicate-valid-conflict")
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
    identity = source_identity(scope, revision_char="b")
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
        table: count_rows(kb_session, table)
        for table in (ChangeSet, ChangeItem, Conflict, Claim, ClaimEvidence)
    }

    report = import_pred_records(
        kb_session,
        [source_record(identity)],
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
        table: count_rows(kb_session, table) for table in baseline
    } == baseline
    assert kb_session.scalar(select(func.count()).select_from(ChangeSet)) == 1


def test_t7_notification_and_import_failure_roll_back_as_one_caller_transaction(
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
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-T7-ROLLBACK",
        name="Import T7 rollback",
    )
    new = source_identity(scope, revision_char="b")
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
                [source_record(new)],
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
    assert count_rows(kb_session, ChangeSet) == 0
    assert count_rows(kb_session, ChangeItem) == 0


def test_t7_empty_tombstone_rejects_late_import_of_the_same_source_revision(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session)
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-T7-TOMBSTONE",
        name="Import T7 tombstone",
    )
    identity = source_identity(scope, revision_char="a")
    tombstone = retract_source(kb_session, scope, identity)

    with pytest.raises(ScopeViolation, match="tombstone"):
        import_pred_records(
            kb_session,
            [source_record(identity)],
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
    assert count_rows(kb_session, ChangeSet) == 1
    assert kb_session.get(ChangeSet, tombstone.change_set_id) is not None
    assert count_rows(kb_session, ChangeItem) == 0
    assert count_rows(kb_session, Claim) == 0
    assert count_rows(kb_session, ClaimEvidence) == 0


def test_t7_legacy_retract_cannot_delete_a_normal_source_aware_import(
    kb_session: Session,
) -> None:
    scope = bound_scope(kb_session)
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-T7-LEGACY-CONFLICT",
        name="Import T7 legacy conflict",
    )
    identity = source_identity(scope, revision_char="a")
    imported = import_pred_records(
        kb_session,
        [source_record(identity)],
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
        quality_gate=_GATE,
        run_fingerprint=_FP,
    )
    baseline = {
        table: count_rows(kb_session, table)
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
        table: count_rows(kb_session, table) for table in baseline
    } == baseline
    change_set = kb_session.get(ChangeSet, imported.change_set_id)
    assert change_set is not None and change_set.status == "applied"
    assert count_rows(kb_session, ClaimEvidence) == 1
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
    scope = bound_scope(kb_session, "tombstone-a")
    product, version = seed_product(
        kb_session,
        scope=scope,
        code="IMPORT-T7-TOMBSTONE-MALFORMED",
        name="Import T7 malformed tombstone",
    )
    identity = source_identity(scope, revision_char="a")
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
            claim_scope = bound_scope(kb_session, "tombstone-b")
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
        table: count_rows(kb_session, table)
        for table in (ChangeSet, ChangeItem, Claim, ClaimEvidence)
    }

    with pytest.raises(ScopeViolation, match="source tombstone is invalid"):
        retract_source(kb_session, scope, identity)

    with pytest.raises(ScopeViolation, match="source tombstone is invalid"):
        import_pred_records(
            kb_session,
            [source_record(identity)],
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
        table: count_rows(kb_session, table) for table in baseline
    } == baseline
    assert kb_session.scalar(select(func.count()).select_from(ChangeSet)) == 1
