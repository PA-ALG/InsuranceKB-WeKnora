"""OpenSpec 017 T7: source-aware, scoped and idempotent source retract."""

import hashlib
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.knowledge import retract_source
from insurance_harness.knowledge.models import SourceImportIdentity
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    ClaimEvidence,
    ClaimRevision,
    CurrentRelease,
    ReleaseSnapshot,
    SnapshotClaim,
)
from tests.kbhelpers import seed_bound_scope, seed_product

NOW = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
EARLIER = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)


def _count(session: Session, table: type) -> int:
    return session.scalar(select(func.count()).select_from(table)) or 0


def _scope(session: Session, suffix: str) -> KnowledgeScope:
    return seed_bound_scope(
        session,
        tenant_id=f"tenant-retract-{suffix}",
        raw_kb_id=f"raw-retract-{suffix}",
        wiki_kb_id=f"wiki-retract-{suffix}",
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


def _claim(
    session: Session,
    scope: KnowledgeScope,
    *,
    predicate: str,
    identities: list[tuple[SourceImportIdentity, datetime | None]],
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
    evidence = [
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
            stale_at=stale_at,
        )
        for identity, stale_at in identities
    ]
    session.add_all(evidence)
    session.flush()
    return claim, evidence


def _expected_retract_key(identity: SourceImportIdentity) -> str:
    digest = hashlib.sha256(
        f"{identity.knowledge_id}\0{identity.source_revision}".encode()
    ).hexdigest()
    return f"retract:{digest[:56]}"


def test_t7_source_aware_retract_is_scoped_deletes_all_target_evidence_and_preserves_release(
    kb_session: Session,
) -> None:
    scope_a = _scope(kb_session, "a")
    scope_b = _scope(kb_session, "b")
    target_a = _identity(scope_a)
    target_a_old = _identity(scope_a, revision_char="b")
    target_b = _identity(scope_b)
    other_active = _identity(
        scope_a, knowledge_id="knowledge-other-active", revision_char="c"
    )
    other_stale = _identity(
        scope_a, knowledge_id="knowledge-other-stale", revision_char="d"
    )
    only_target, _ = _claim(
        kb_session,
        scope_a,
        predicate="only-target",
        identities=[(target_a, None), (target_a_old, EARLIER)],
    )
    active_survivor, active_rows = _claim(
        kb_session,
        scope_a,
        predicate="active-survivor",
        identities=[(target_a, None), (other_active, None)],
    )
    stale_survivor, stale_rows = _claim(
        kb_session,
        scope_a,
        predicate="stale-survivor",
        identities=[(target_a, None), (other_stale, EARLIER)],
    )
    foreign_claim, foreign_rows = _claim(
        kb_session,
        scope_b,
        predicate="foreign",
        identities=[(target_b, None)],
    )
    rendered_pages = [{"slug": "product", "content": "published"}]
    snapshot = ReleaseSnapshot(
        space_id=scope_a.space_id,
        label="release-before-retract",
        rendered_pages=rendered_pages,
        published_at=NOW,
        published_by="publisher",
    )
    kb_session.add(snapshot)
    kb_session.flush()
    membership = SnapshotClaim(
        space_id=scope_a.space_id,
        snapshot_id=snapshot.id,
        claim_id=only_target.id,
        revision_no=only_target.current_revision,
    )
    pointer = CurrentRelease(
        space_id=scope_a.space_id,
        id="current",
        snapshot_id=snapshot.id,
    )
    kb_session.add_all([membership, pointer])
    kb_session.flush()

    report = retract_source(kb_session, scope_a, target_a)

    assert report.actions == {"retract": 3}
    assert report.change_set_id
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
        "document",
        target_a.knowledge_id,
        _expected_retract_key(target_a),
        "applied",
    )
    assert len(change_set.source_revision or "") == 64
    assert (
        kb_session.scalar(
            select(func.count())
            .select_from(ClaimEvidence)
            .join(Claim, Claim.id == ClaimEvidence.claim_id)
            .where(
                Claim.space_id == scope_a.space_id,
                ClaimEvidence.knowledge_id == target_a.knowledge_id,
            )
        )
        == 0
    )
    kb_session.refresh(only_target)
    kb_session.refresh(active_survivor)
    kb_session.refresh(stale_survivor)
    kb_session.refresh(foreign_claim)
    assert only_target.status == "retracted"
    assert active_survivor.status == "published"
    assert stale_survivor.status == "retracted"
    assert active_rows[1].stale_at is None
    assert stale_rows[1].stale_at == EARLIER
    assert foreign_claim.status == "published"
    assert foreign_rows[0] in kb_session
    assert _count(kb_session, ChangeItem) == 3
    kb_session.refresh(snapshot)
    kb_session.refresh(membership)
    kb_session.refresh(pointer)
    assert snapshot.rendered_pages == rendered_pages
    assert membership.claim_id == only_target.id
    assert pointer.snapshot_id == snapshot.id
    assert _count(kb_session, ReleaseSnapshot) == 1
    assert _count(kb_session, SnapshotClaim) == 1
    assert _count(kb_session, CurrentRelease) == 1


def test_t7_retract_exact_event_is_idempotent_after_evidence_is_gone(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session, "idempotent")
    identity = _identity(scope)
    _claim(
        kb_session,
        scope,
        predicate="waiting-period",
        identities=[(identity, None)],
    )

    first = retract_source(kb_session, scope, identity)
    baseline = {
        ChangeSet: _count(kb_session, ChangeSet),
        ChangeItem: _count(kb_session, ChangeItem),
        ClaimRevision: _count(kb_session, ClaimRevision),
    }
    second = retract_source(kb_session, scope, identity)

    assert second == first
    assert {
        table: _count(kb_session, table) for table in baseline
    } == baseline


def test_t7_source_aware_empty_retract_records_and_replays_one_tombstone(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session, "empty-source-aware")
    identity = _identity(scope)

    first = retract_source(kb_session, scope, identity)
    second = retract_source(kb_session, scope, identity)

    assert first == second
    assert first.actions == {}
    assert first.change_set_id
    change_set = kb_session.get(ChangeSet, first.change_set_id)
    assert change_set is not None
    assert (
        change_set.space_id,
        change_set.source_kind,
        change_set.external_record_id,
        change_set.source_revision,
        change_set.status,
    ) == (
        scope.space_id,
        "document",
        identity.knowledge_id,
        _expected_retract_key(identity),
        "applied",
    )
    assert _count(kb_session, ChangeSet) == 1
    assert _count(kb_session, ChangeItem) == 0


def test_t7_explicit_legacy_empty_retract_records_and_replays_one_tombstone(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session, "empty-legacy")
    knowledge_id = "legacy-empty-knowledge"

    first = retract_source(
        kb_session,
        scope,
        knowledge_id,
        legacy_replay=True,
    )
    second = retract_source(
        kb_session,
        scope,
        knowledge_id,
        legacy_replay=True,
    )

    assert first == second
    assert first.actions == {}
    assert first.change_set_id
    change_set = kb_session.get(ChangeSet, first.change_set_id)
    assert change_set is not None
    expected_digest = hashlib.sha256(
        f"{knowledge_id}\0legacy-replay".encode()
    ).hexdigest()
    assert change_set.source_revision == f"retract:{expected_digest[:56]}"
    assert _count(kb_session, ChangeSet) == 1
    assert _count(kb_session, ChangeItem) == 0


def test_t7_retract_reuploaded_new_revision_creates_a_new_event_key(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session, "reupload")
    first_identity = _identity(scope, revision_char="a")
    claim, _ = _claim(
        kb_session,
        scope,
        predicate="waiting-period",
        identities=[(first_identity, None)],
    )
    first = retract_source(kb_session, scope, first_identity)
    new_identity = _identity(scope, revision_char="b")
    claim.status = "published"
    kb_session.add(
        ClaimEvidence(
            claim_id=claim.id,
            knowledge_id=new_identity.knowledge_id,
            chunk_id=None,
            quote="reuploaded",
            page=2,
            authority_level=1,
            doc_role="terms",
            extraction_method="llm",
            extracted_at=NOW,
            raw_kb_id=new_identity.raw_kb_id,
            source_revision=new_identity.source_revision,
            file_hash=new_identity.file_hash,
            original_digest=new_identity.original_digest,
            parser_version=new_identity.parser_version,
            chunk_hash=None,
            lineage_status="page_only",
            stale_at=None,
        )
    )
    kb_session.flush()

    second = retract_source(kb_session, scope, new_identity)

    assert second.change_set_id != first.change_set_id
    keys = set(
        kb_session.scalars(
            select(ChangeSet.source_revision).where(
                ChangeSet.external_record_id == new_identity.knowledge_id
            )
        )
    )
    assert keys == {
        _expected_retract_key(first_identity),
        _expected_retract_key(new_identity),
    }
    assert _count(kb_session, ChangeSet) == 2
    assert _count(kb_session, ChangeItem) == 2


def test_t7_legacy_retract_requires_explicit_replay_flag_before_any_sql(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session, "legacy")
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
            retract_source(kb_session, scope, "legacy-knowledge")
    finally:
        event.remove(bind, "before_cursor_execute", capture_statement)

    assert statements == []


def test_t7_source_identity_with_legacy_flag_is_rejected_before_any_sql(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session, "legacy-identity-conflict")
    identity = _identity(scope)
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
            retract_source(
                kb_session,
                scope,
                identity,
                legacy_replay=True,
            )
    finally:
        event.remove(bind, "before_cursor_execute", capture_statement)

    assert statements == []


@pytest.mark.parametrize(
    "source_aware_state",
    ["evidence", "document_changeset", "recompile_changeset"],
)
def test_t7_legacy_retract_fails_closed_on_any_source_aware_state(
    kb_session: Session,
    source_aware_state: str,
) -> None:
    scope = _scope(kb_session, f"legacy-conflict-{source_aware_state}")
    identity = _identity(scope)
    claim, rows = _claim(
        kb_session,
        scope,
        predicate=f"legacy-conflict-{source_aware_state}",
        identities=[(identity, None)],
    )
    if source_aware_state != "evidence":
        rows[0].raw_kb_id = None
        rows[0].source_revision = None
        rows[0].file_hash = None
        rows[0].original_digest = None
        rows[0].parser_version = None
        rows[0].lineage_status = None
        kb_session.add(
            ChangeSet(
                space_id=scope.space_id,
                source_kind=(
                    "document"
                    if source_aware_state == "document_changeset"
                    else "recompile"
                ),
                knowledge_ids=[identity.knowledge_id],
                external_record_id=identity.knowledge_id,
                source_revision=identity.source_revision,
                status=(
                    "applied"
                    if source_aware_state == "document_changeset"
                    else "pending"
                ),
                created_by="source-aware-test",
            )
        )
    else:
        kb_session.add(
            ClaimEvidence(
                claim_id=claim.id,
                knowledge_id=identity.knowledge_id,
                chunk_id="legacy-chunk",
                quote="legacy row must also survive",
                page=3,
                authority_level=6,
                doc_role="external",
                extraction_method="llm",
                extracted_at=NOW,
            )
        )
    kb_session.flush()
    baseline = {
        table: _count(kb_session, table)
        for table in (
            ChangeSet,
            ChangeItem,
            Claim,
            ClaimEvidence,
            ClaimRevision,
        )
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
    restored = kb_session.get(Claim, claim.id)
    assert restored is not None and restored.status == "published"
    assert kb_session.scalar(select(func.count()).select_from(Claim)) == 1


def test_t7_legacy_retract_works_only_through_explicit_replay_sentinel(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session, "legacy-explicit")
    identity = _identity(scope, knowledge_id="legacy-knowledge")
    claim, evidence = _claim(
        kb_session,
        scope,
        predicate="legacy-claim",
        identities=[(identity, None)],
    )
    for row in evidence:
        row.raw_kb_id = None
        row.source_revision = None
        row.file_hash = None
        row.original_digest = None
        row.parser_version = None
        row.lineage_status = None
    kb_session.flush()

    first = retract_source(
        kb_session,
        scope,
        identity.knowledge_id,
        legacy_replay=True,
    )
    second = retract_source(
        kb_session,
        scope,
        identity.knowledge_id,
        legacy_replay=True,
    )

    assert first == second
    assert first.change_set_id
    kb_session.refresh(claim)
    assert claim.status == "retracted"
    change_set = kb_session.get(ChangeSet, first.change_set_id)
    assert change_set is not None
    assert change_set.source_kind == "document"
    assert change_set.external_record_id == (
        "legacy:"
        + hashlib.sha256(identity.knowledge_id.encode()).hexdigest()[:57]
    )
    assert (change_set.source_revision or "").startswith("retract:")


def test_t7_retract_rejects_constructed_raw_scope_mismatch_before_any_sql(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session, "forged")
    forged = SourceImportIdentity.model_construct(
        knowledge_id="knowledge-1",
        raw_kb_id="raw-other",
        source_revision="a" * 64,
        file_hash="a" * 32,
        original_digest="a" * 64,
        parser_version="pdfplumber@0.11:text-v1",
    )
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
            retract_source(kb_session, scope, forged)
    finally:
        event.remove(bind, "before_cursor_execute", capture_statement)

    assert statements == []


def test_t7_retract_failure_rolls_back_all_mutations_and_session_remains_usable(
    kb_session: Session,
) -> None:
    scope = _scope(kb_session, "failure")
    identity = _identity(scope)
    claim, evidence = _claim(
        kb_session,
        scope,
        predicate="waiting-period",
        identities=[(identity, None)],
    )
    claim_id = claim.id
    evidence_id = evidence[0].id
    baseline = {
        ChangeSet: _count(kb_session, ChangeSet),
        ChangeItem: _count(kb_session, ChangeItem),
        ClaimRevision: _count(kb_session, ClaimRevision),
    }

    def fail_item_flush(session: Session, _context: object, _instances: object) -> None:
        if any(isinstance(row, ChangeItem) for row in session.new):
            raise RuntimeError("injected retract item failure")

    event.listen(kb_session, "before_flush", fail_item_flush)
    try:
        with pytest.raises(RuntimeError, match="injected retract item failure"):
            retract_source(kb_session, scope, identity)
    finally:
        event.remove(kb_session, "before_flush", fail_item_flush)

    kb_session.commit()
    restored_claim = kb_session.get(Claim, claim_id)
    assert restored_claim is not None and restored_claim.status == "published"
    assert kb_session.get(ClaimEvidence, evidence_id) is not None
    assert {
        table: _count(kb_session, table) for table in baseline
    } == baseline
    assert kb_session.scalar(select(func.count()).select_from(Claim)) == 1
