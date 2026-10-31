"""bind_space (016 S3.2): command-then-commit, pending binds, input and tenant rules."""

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope import (
    ScopeBindingError,
    UnboundKnowledgeSpace,
    bind_space,
    load_scope,
)
from tests.identity.knowledge_scope.helpers import (
    BoundSpaceFactory,
    _assert_unbound,
    _unbound_space,
)


def test_s3_2_bind_space_is_command_then_commit_and_reload_returns_attested_scope(
    session: Session,
) -> None:
    from insurance_harness.db.scope import is_database_bound_scope

    row = _unbound_space(session)

    result = bind_space(  # type: ignore[func-returns-value]
        session,
        row.id,
        tenant_id="tenant-a",
        raw_kb_id="raw-a",
        wiki_kb_id="wiki-a",
    )

    assert result is None
    assert session.in_transaction()
    session.commit()
    session.expire_all()
    scope = load_scope(session, row.id)
    assert is_database_bound_scope(scope)
    assert scope.model_dump() == {
        "space_id": row.id,
        "tenant_id": "tenant-a",
        "raw_kb_id": "raw-a",
        "wiki_kb_id": "wiki-a",
    }


def test_s3_2_bind_space_does_not_commit_the_callers_transaction(
    session: Session,
) -> None:
    row = _unbound_space(session)
    space_id = row.id
    session.commit()
    # SQLite legacy transaction control does not emit a physical BEGIN for a
    # SAVEPOINT. Establish the caller-owned outer transaction explicitly.
    session.execute(text("BEGIN"))

    result = bind_space(  # type: ignore[func-returns-value]
        session,
        space_id,
        tenant_id="tenant-a",
        raw_kb_id="raw-a",
        wiki_kb_id="wiki-a",
    )
    assert result is None
    session.rollback()

    reloaded = session.get(KnowledgeSpace, space_id)
    assert reloaded is not None
    _assert_unbound(reloaded)


def test_s3_2_load_scope_rejects_pending_bind_until_outer_commit(
    session: Session,
) -> None:
    from insurance_harness.db.scope import is_database_bound_scope

    row = _unbound_space(session, space_id="pending-bind-commit")
    space_id = row.id
    session.commit()
    # SQLite legacy transaction control needs an explicit physical outer BEGIN
    # before bind_space creates its nested SAVEPOINT.
    session.execute(text("BEGIN"))
    bind_space(
        session,
        space_id,
        tenant_id="tenant-pending-commit",
        raw_kb_id="raw-pending-commit",
        wiki_kb_id="wiki-pending-commit",
    )
    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append(statement)

    bind = session.get_bind(mapper=KnowledgeSpace)
    event.listen(bind, "before_cursor_execute", record_statement)
    try:
        with pytest.raises(UnboundKnowledgeSpace, match="unavailable"):
            load_scope(session, space_id)
    finally:
        event.remove(bind, "before_cursor_execute", record_statement)

    assert statements == []
    session.commit()

    scope = load_scope(session, space_id)

    assert is_database_bound_scope(scope)
    assert scope.raw_kb_id == "raw-pending-commit"


def test_s3_2_load_scope_rejects_pending_bind_and_rollback_remains_unbound(
    session: Session,
) -> None:
    row = _unbound_space(session, space_id="pending-bind-rollback")
    space_id = row.id
    session.commit()
    session.execute(text("BEGIN"))
    bind_space(
        session,
        space_id,
        tenant_id="tenant-pending-rollback",
        raw_kb_id="raw-pending-rollback",
        wiki_kb_id="wiki-pending-rollback",
    )

    with pytest.raises(UnboundKnowledgeSpace, match="unavailable"):
        load_scope(session, space_id)

    session.rollback()

    with pytest.raises(UnboundKnowledgeSpace, match="unavailable"):
        load_scope(session, space_id)
    reloaded = session.get(KnowledgeSpace, space_id)
    assert reloaded is not None
    _assert_unbound(reloaded)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("tenant_id", None),
        ("tenant_id", ""),
        ("tenant_id", "   "),
        ("tenant_id", "t" * 256),
        ("raw_kb_id", None),
        ("raw_kb_id", ""),
        ("raw_kb_id", "   "),
        ("raw_kb_id", "r" * 256),
        ("wiki_kb_id", None),
        ("wiki_kb_id", ""),
        ("wiki_kb_id", "   "),
        ("wiki_kb_id", "w" * 256),
    ],
)
def test_s3_2_bind_space_rejects_partial_blank_or_oversized_input_before_mutation(
    session: Session,
    field: str,
    invalid_value: str | None,
) -> None:
    row = _unbound_space(session)
    values: dict[str, str | None] = {
        "tenant_id": "tenant-a",
        "raw_kb_id": "raw-a",
        "wiki_kb_id": "wiki-a",
    }
    values[field] = invalid_value

    with pytest.raises(ScopeBindingError, match="binding failed") as error:
        bind_space(
            session,
            row.id,
            tenant_id=values["tenant_id"],  # type: ignore[arg-type]
            raw_kb_id=values["raw_kb_id"],  # type: ignore[arg-type]
            wiki_kb_id=values["wiki_kb_id"],  # type: ignore[arg-type]
        )

    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    _assert_unbound(row)


def test_s3_2_bind_space_missing_and_already_bound_fail_closed_without_values(
    session: Session,
    bound_space: BoundSpaceFactory,
) -> None:
    existing = bound_space(
        tenant_id="private-tenant",
        raw_kb_id="private-raw",
        wiki_kb_id="private-wiki",
    )

    for space_id in ("missing-space", existing.id):
        with pytest.raises(ScopeBindingError) as error:
            bind_space(
                session,
                space_id,
                tenant_id="private-tenant",
                raw_kb_id="private-raw",
                wiki_kb_id="private-wiki",
            )
        message = str(error.value)
        assert message == "knowledge space binding failed"
        assert existing.id not in message
        assert "private" not in message

    assert existing.binding_status == "bound"


@pytest.mark.parametrize(
    ("target_raw", "target_wiki"),
    [("raw-taken", "wiki-new"), ("raw-new", "wiki-taken")],
)
def test_s3_2_bind_space_rejects_same_tenant_mapping_conflicts_without_partial_write(
    session: Session,
    bound_space: BoundSpaceFactory,
    target_raw: str,
    target_wiki: str,
) -> None:
    bound_space(
        tenant_id="tenant-a",
        raw_kb_id="raw-taken",
        wiki_kb_id="wiki-taken",
    )
    row = _unbound_space(session)

    with pytest.raises(ScopeBindingError, match="binding failed"):
        bind_space(
            session,
            row.id,
            tenant_id="tenant-a",
            raw_kb_id=target_raw,
            wiki_kb_id=target_wiki,
        )

    _assert_unbound(row)


def test_s3_2_bind_space_allows_same_kb_ids_in_a_different_tenant(
    session: Session,
    bound_space: BoundSpaceFactory,
) -> None:
    bound_space(
        tenant_id="tenant-a",
        raw_kb_id="raw-shared",
        wiki_kb_id="wiki-shared",
    )
    row = _unbound_space(session)

    result = bind_space(  # type: ignore[func-returns-value]
        session,
        row.id,
        tenant_id="tenant-b",
        raw_kb_id="raw-shared",
        wiki_kb_id="wiki-shared",
    )
    assert result is None
    session.commit()

    assert load_scope(session, row.id).tenant_id == "tenant-b"
