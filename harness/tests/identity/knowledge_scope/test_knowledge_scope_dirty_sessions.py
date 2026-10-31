"""KnowledgeScope (016 S1.2): forged values and dirty / new / deleted rows fail closed."""

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.orm import Session

from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
    UnboundKnowledgeSpace,
    load_scope,
)
from tests.identity.knowledge_scope.helpers import BoundSpaceFactory


def test_s1_2_current_scope_rejects_forged_matching_values_without_query(
    session: Session,
    bound_space: BoundSpaceFactory,
) -> None:
    from insurance_harness.db.scope import require_current_scope

    row = bound_space(
        tenant_id="matching",
        raw_kb_id="raw-matching",
        wiki_kb_id="wiki-matching",
    )
    forged = KnowledgeScope(
        space_id=row.id,
        tenant_id="matching",
        raw_kb_id="raw-matching",
        wiki_kb_id="wiki-matching",
    )

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        require_current_scope(session, forged)


def test_s1_2_current_scope_rejects_dirty_space_without_mutating_caller_uow(
    session: Session,
    bound_space: BoundSpaceFactory,
) -> None:
    from insurance_harness.db.scope import require_current_scope

    row = bound_space(
        tenant_id="dirty-space",
        raw_kb_id="raw-dirty-space",
        wiki_kb_id="wiki-dirty-space",
    )
    scope = load_scope(session, row.id)
    row.name = "caller-pending-name"
    assert row in session.dirty

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        require_current_scope(session, scope)

    assert row.name == "caller-pending-name"
    assert row in session.dirty
    assert session.is_active


def test_s1_2_loader_rejects_dirty_binding_without_flush_or_refresh(
    session: Session,
    bound_space: BoundSpaceFactory,
) -> None:
    row = bound_space(
        tenant_id="dirty-binding",
        raw_kb_id="raw-before",
        wiki_kb_id="wiki-dirty-binding",
    )
    space_id = row.id
    session.commit()
    reloaded = session.get(KnowledgeSpace, space_id)
    assert reloaded is not None
    reloaded.raw_kb_id = "raw-pending"

    with pytest.raises(UnboundKnowledgeSpace, match="unavailable"):
        load_scope(session, space_id)

    assert reloaded.raw_kb_id == "raw-pending"
    assert reloaded in session.dirty
    assert session.connection().scalar(
        text("SELECT raw_kb_id FROM knowledge_spaces WHERE id = :space_id"),
        {"space_id": space_id},
    ) == "raw-before"


def test_s1_2_loader_rejects_dirty_primary_key_by_identity_without_flush(
    session: Session,
    bound_space: BoundSpaceFactory,
) -> None:
    row = bound_space(
        tenant_id="dirty-pk",
        raw_kb_id="raw-dirty-pk",
        wiki_kb_id="wiki-dirty-pk",
    )
    original_id = row.id
    session.commit()
    reloaded = session.get(KnowledgeSpace, original_id)
    assert reloaded is not None
    assert sa_inspect(reloaded).identity == (original_id,)
    reloaded.id = "dirty-pk-new"

    for requested_id in (original_id, "dirty-pk-new"):
        with pytest.raises(UnboundKnowledgeSpace, match="unavailable"):
            load_scope(session, requested_id)

    assert reloaded.id == "dirty-pk-new"
    assert reloaded in session.dirty
    assert session.connection().scalar(
        text("SELECT count(*) FROM knowledge_spaces WHERE id = :space_id"),
        {"space_id": original_id},
    ) == 1
    assert session.connection().scalar(
        text("SELECT count(*) FROM knowledge_spaces WHERE id = 'dirty-pk-new'")
    ) == 0


def test_s1_2_loader_rejects_new_space_without_autoflush(session: Session) -> None:
    row = KnowledgeSpace(
        id="new-pending-space",
        name="new-pending",
        binding_status="bound",
        tenant_id="new-tenant",
        raw_kb_id="new-raw",
        wiki_kb_id="new-wiki",
    )
    session.add(row)

    with pytest.raises(UnboundKnowledgeSpace, match="unavailable"):
        load_scope(session, row.id)

    assert row in session.new
    assert session.connection().scalar(
        text("SELECT count(*) FROM knowledge_spaces WHERE id = 'new-pending-space'")
    ) == 0


def test_s1_2_loader_rejects_deleted_space_without_autoflush(
    session: Session,
    bound_space: BoundSpaceFactory,
) -> None:
    row = bound_space(
        tenant_id="deleted-space",
        raw_kb_id="raw-deleted-space",
        wiki_kb_id="wiki-deleted-space",
    )
    space_id = row.id
    session.commit()
    reloaded = session.get(KnowledgeSpace, space_id)
    assert reloaded is not None
    session.delete(reloaded)

    with pytest.raises(UnboundKnowledgeSpace, match="unavailable"):
        load_scope(session, space_id)

    assert reloaded in session.deleted
    assert session.connection().scalar(
        text("SELECT count(*) FROM knowledge_spaces WHERE id = :space_id"),
        {"space_id": space_id},
    ) == 1
