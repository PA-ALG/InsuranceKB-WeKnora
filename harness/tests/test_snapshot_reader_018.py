"""OpenSpec 018 T3: current SnapshotFact Reader and typed gaps."""

import re
from datetime import date

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from insurance_harness.db.base import make_session_factory
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.knowledge import (
    CoverageGap,
    SnapshotFactsResult,
    SnapshotReader,
    build_snapshot_facts,
)
from tests.support.release_018 import (
    persist_release_snapshot,
    release_claim,
    release_product,
    release_scope,
)


def _reader(session: Session) -> SnapshotReader:
    bind = session.get_bind()
    assert isinstance(bind, Engine)
    return SnapshotReader(make_session_factory(bind))


def test_r2_1_current_reads_only_detached_snapshot_facts(
    kb_session: Session,
) -> None:
    scope = release_scope(kb_session)
    _, version_a = release_product(kb_session, scope, code="A")
    _, version_b = release_product(kb_session, scope, code="B")
    claim_a, _ = release_claim(
        kb_session,
        scope,
        version_a,
        claim_id="claim-a",
        predicate="waiting_period",
    )
    release_claim(
        kb_session,
        scope,
        version_b,
        claim_id="claim-b",
        predicate="hesitation_period",
    )
    facts = build_snapshot_facts(kb_session, scope, snapshot_id="snapshot-1")
    persist_release_snapshot(
        kb_session, scope, snapshot_id="snapshot-1", facts=facts
    )
    statements: list[str] = []
    bind = kb_session.get_bind()

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement.lower())

    event.listen(bind, "before_cursor_execute", record_statement)
    try:
        result = _reader(kb_session).current(scope)
    finally:
        event.remove(bind, "before_cursor_execute", record_statement)

    assert isinstance(result, SnapshotFactsResult)
    assert result.snapshot_id == "snapshot-1"
    assert {fact.claim_id for fact in result.facts} == {"claim-a", "claim-b"}
    sort_keys = [
        (
            fact.product_id,
            fact.product_version_id,
            fact.predicate,
            fact.effective_from or date.min,
            fact.effective_to or date.max,
            fact.claim_id,
            fact.revision_no,
        )
        for fact in result.facts
    ]
    assert sort_keys == sorted(sort_keys)
    assert all(fact.snapshot_id == "snapshot-1" for fact in result.facts)
    sql = "\n".join(statements)
    assert re.search(r"\bclaims\b", sql) is None
    assert "claim_evidence" not in sql

    claim_a.value = {"text": "180天"}
    kb_session.commit()
    frozen_a = next(fact for fact in result.facts if fact.claim_id == "claim-a")
    assert frozen_a.value == {"text": "90天"}


def test_r2_4_no_release_and_legacy_release_return_fixed_gaps(
    kb_session: Session,
) -> None:
    empty_scope = release_scope(kb_session, "empty")
    kb_session.commit()
    no_release = _reader(kb_session).current(empty_scope)
    assert no_release == CoverageGap(code="no_release", snapshot_id=None)

    legacy_scope = release_scope(kb_session, "legacy")
    snapshot = persist_release_snapshot(
        kb_session,
        legacy_scope,
        snapshot_id="snapshot-legacy",
    )
    snapshot.read_model_version = 0
    kb_session.commit()

    legacy = _reader(kb_session).current(legacy_scope)
    assert legacy == CoverageGap(
        code="legacy_release", snapshot_id="snapshot-legacy"
    )


def test_r2_2_filters_have_exact_gap_precedence_and_inclusive_date_bounds(
    kb_session: Session,
) -> None:
    scope = release_scope(kb_session)
    product, version = release_product(kb_session, scope, code="A")
    release_claim(
        kb_session,
        scope,
        version,
        claim_id="claim-open-start",
        predicate="waiting_period",
        effective_from=None,
        effective_to=date(2026, 1, 15),
    )
    release_claim(
        kb_session,
        scope,
        version,
        claim_id="claim-open-end",
        predicate="waiting_period",
        effective_from=date(2026, 1, 15),
        effective_to=None,
    )
    release_claim(
        kb_session,
        scope,
        version,
        claim_id="claim-limited",
        predicate="limited_period",
        effective_from=date(2026, 1, 10),
        effective_to=date(2026, 1, 20),
    )
    facts = build_snapshot_facts(kb_session, scope, snapshot_id="snapshot-1")
    persist_release_snapshot(
        kb_session, scope, snapshot_id="snapshot-1", facts=facts
    )
    absent_product, absent_version = release_product(kb_session, scope, code="B")
    kb_session.commit()
    reader = _reader(kb_session)

    overlap = reader.current(
        scope,
        product_id=product.id,
        product_version_id=version.id,
        predicate="waiting_period",
        effective_on=date(2026, 1, 15),
    )
    assert isinstance(overlap, SnapshotFactsResult)
    assert [fact.claim_id for fact in overlap.facts] == [
        "claim-open-start",
        "claim-open-end",
    ]
    assert reader.current(scope, product_id=absent_product.id) == CoverageGap(
        code="product_not_found", snapshot_id="snapshot-1"
    )
    assert reader.current(
        scope, product_version_id=absent_version.id
    ) == CoverageGap(code="product_not_found", snapshot_id="snapshot-1")
    assert reader.current(scope, predicate="missing") == CoverageGap(
        code="predicate_not_found", snapshot_id="snapshot-1"
    )
    assert reader.current(
        scope,
        predicate="limited_period",
        effective_on=date(2026, 2, 1),
    ) == CoverageGap(code="effective_date_miss", snapshot_id="snapshot-1")


def test_r2_4_explicit_foreign_or_unknown_entity_and_forged_scope_fail_closed(
    kb_session: Session,
) -> None:
    scope = release_scope(kb_session)
    _, version = release_product(kb_session, scope, code="A")
    release_claim(
        kb_session,
        scope,
        version,
        claim_id="claim-a",
        predicate="waiting_period",
    )
    facts = build_snapshot_facts(kb_session, scope, snapshot_id="snapshot-1")
    persist_release_snapshot(
        kb_session, scope, snapshot_id="snapshot-1", facts=facts
    )
    other_scope = release_scope(kb_session, "other")
    other_product, other_version = release_product(
        kb_session, other_scope, code="B"
    )
    kb_session.commit()
    reader = _reader(kb_session)

    for product_id, product_version_id in (
        (other_product.id, None),
        (None, other_version.id),
        ("missing", None),
        (None, "missing"),
    ):
        with pytest.raises(ScopeViolation, match="^scope mismatch$"):
            reader.current(
                scope,
                product_id=product_id,
                product_version_id=product_version_id,
            )

    forged = KnowledgeScope(**scope.model_dump())
    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        reader.current(forged)


def test_r2_4_empty_version_one_snapshot_returns_product_gap(
    kb_session: Session,
) -> None:
    scope = release_scope(kb_session)
    persist_release_snapshot(kb_session, scope, snapshot_id="snapshot-empty")

    assert _reader(kb_session).current(scope) == CoverageGap(
        code="product_not_found", snapshot_id="snapshot-empty"
    )
