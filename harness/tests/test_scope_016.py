"""016 S1: KnowledgeSpace binding and fail-closed scope loading."""

import gc
import weakref
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import pytest
from pydantic import ValidationError
from sqlalchemy import event, insert, select, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeBindingError,
    ScopeViolation,
    UnboundKnowledgeSpace,
    bind_space,
    load_scope,
)


class BoundSpaceFactory(Protocol):
    def __call__(
        self, *, tenant_id: str, raw_kb_id: str, wiki_kb_id: str
    ) -> KnowledgeSpace: ...


class BoundScopeFactory(Protocol):
    def __call__(
        self, *, tenant_id: str, raw_kb_id: str, wiki_kb_id: str
    ) -> KnowledgeScope: ...


def test_s1_1_unbound_space_keeps_all_bindings_null(session: Session) -> None:
    row = KnowledgeSpace(name="legacy", binding_status="unbound")
    session.add(row)
    session.flush()

    assert row.tenant_id is None
    assert row.raw_kb_id is None
    assert row.wiki_kb_id is None


@pytest.mark.parametrize(
    ("binding_status", "tenant_id", "raw_kb_id", "wiki_kb_id"),
    [
        ("unbound", "100", None, None),
        ("bound", "100", "raw-a", None),
    ],
)
def test_s1_1_database_rejects_inconsistent_binding_shape(
    session: Session,
    binding_status: str,
    tenant_id: str | None,
    raw_kb_id: str | None,
    wiki_kb_id: str | None,
) -> None:
    session.add(
        KnowledgeSpace(
            name="inconsistent",
            binding_status=binding_status,
            tenant_id=tenant_id,
            raw_kb_id=raw_kb_id,
            wiki_kb_id=wiki_kb_id,
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize(
    ("raw_kb_id", "wiki_kb_id"),
    [("raw-a", "wiki-b"), ("raw-b", "wiki-a")],
)
def test_s1_1_bound_kb_bindings_are_unique_within_tenant(
    session: Session,
    bound_space: BoundSpaceFactory,
    raw_kb_id: str,
    wiki_kb_id: str,
) -> None:
    bound_space(
        tenant_id="100",
        raw_kb_id="raw-a",
        wiki_kb_id="wiki-a",
    )
    session.add(
        KnowledgeSpace(
            name="duplicate",
            binding_status="bound",
            tenant_id="100",
            raw_kb_id=raw_kb_id,
            wiki_kb_id=wiki_kb_id,
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()


def test_s1_2_only_bound_space_builds_scope(session: Session) -> None:
    row = KnowledgeSpace(name="legacy", binding_status="unbound")
    session.add(row)
    session.flush()

    with pytest.raises(UnboundKnowledgeSpace):
        load_scope(session, row.id)


def test_s1_2_bound_space_builds_immutable_scope(
    session: Session, bound_space: BoundSpaceFactory
) -> None:
    row = bound_space(
        tenant_id="100",
        raw_kb_id="raw-a",
        wiki_kb_id="wiki-a",
    )

    scope = load_scope(session, row.id)

    assert scope.model_dump() == {
        "space_id": row.id,
        "tenant_id": "100",
        "raw_kb_id": "raw-a",
        "wiki_kb_id": "wiki-a",
    }
    with pytest.raises(ValidationError):
        scope.tenant_id = "200"


def test_s1_2_missing_and_unbound_spaces_fail_closed_without_disclosure(
    session: Session,
) -> None:
    row = KnowledgeSpace(name="legacy", binding_status="unbound")
    session.add(row)
    session.flush()

    with pytest.raises(UnboundKnowledgeSpace) as unbound_error:
        load_scope(session, row.id)
    with pytest.raises(UnboundKnowledgeSpace) as missing_error:
        load_scope(session, "missing-space")

    assert str(unbound_error.value) == str(missing_error.value)


def test_s1_2_loader_rejects_incomplete_bound_row(session: Session) -> None:
    session.execute(text("PRAGMA ignore_check_constraints = ON"))
    session.execute(
        insert(KnowledgeSpace).values(
            id="incomplete-bound",
            name="incomplete",
            binding_status="bound",
            tenant_id="100",
            raw_kb_id="raw-a",
            wiki_kb_id=None,
        )
    )

    with pytest.raises(UnboundKnowledgeSpace):
        load_scope(session, "incomplete-bound")


def test_bound_scope_fixture_loads_persisted_binding(
    session: Session, bound_scope: BoundScopeFactory
) -> None:
    scope = bound_scope(
        tenant_id="200",
        raw_kb_id="raw-b",
        wiki_kb_id="wiki-b",
    )
    row = session.get(KnowledgeSpace, scope.space_id)

    assert row is not None
    assert scope.model_dump() == {
        "space_id": row.id,
        "tenant_id": "200",
        "raw_kb_id": "raw-b",
        "wiki_kb_id": "wiki-b",
    }


def test_s1_2_database_scope_attestation_is_private_and_not_semantic(
    session: Session,
    bound_space: BoundSpaceFactory,
) -> None:
    from insurance_harness.db.scope import is_database_bound_scope

    row = bound_space(
        tenant_id="300",
        raw_kb_id="raw-c",
        wiki_kb_id="wiki-c",
    )
    loaded = load_scope(session, row.id)
    direct = KnowledgeScope(
        space_id=row.id,
        tenant_id="300",
        raw_kb_id="raw-c",
        wiki_kb_id="wiki-c",
    )

    assert is_database_bound_scope(loaded)
    assert not is_database_bound_scope(direct)
    assert loaded == direct
    assert loaded.model_dump() == direct.model_dump()
    assert "attestation" not in repr(loaded).lower()


def test_s1_2_model_copy_cannot_move_database_attestation_to_new_binding(
    session: Session,
    bound_space: BoundSpaceFactory,
) -> None:
    from insurance_harness.db.scope import is_database_bound_scope

    row = bound_space(
        tenant_id="400",
        raw_kb_id="raw-d",
        wiki_kb_id="wiki-d",
    )
    loaded = load_scope(session, row.id)

    assert is_database_bound_scope(loaded.model_copy())
    assert not is_database_bound_scope(
        loaded.model_copy(update={"raw_kb_id": "raw-forged"})
    )


def test_s1_2_complete_constructed_scopes_are_not_database_attested() -> None:
    from insurance_harness.db.scope import is_database_bound_scope

    direct = KnowledgeScope(
        space_id="missing-space",
        tenant_id="tenant-forged",
        raw_kb_id="raw-forged",
        wiki_kb_id="wiki-forged",
    )
    constructed = KnowledgeScope.model_construct(
        space_id="missing-space",
        tenant_id="tenant-forged",
        raw_kb_id="raw-forged",
        wiki_kb_id="wiki-forged",
    )

    assert not is_database_bound_scope(direct)
    assert not is_database_bound_scope(constructed)


def test_s1_2_current_scope_accepts_same_engine_other_session_and_unchanged_copy(
    session: Session,
    bound_space: BoundSpaceFactory,
) -> None:
    from insurance_harness.db.scope import require_current_scope

    row = bound_space(
        tenant_id="same-engine",
        raw_kb_id="raw-same-engine",
        wiki_kb_id="wiki-same-engine",
    )
    scope = load_scope(session, row.id)
    session.commit()

    with Session(session.get_bind()) as other_session:
        require_current_scope(other_session, scope)
        require_current_scope(other_session, scope.model_copy())


def test_s1_2_deep_model_copy_is_safe_and_keeps_loader_provenance(
    session: Session,
    bound_space: BoundSpaceFactory,
) -> None:
    from insurance_harness.db.scope import (
        is_database_bound_scope,
        require_current_scope,
    )

    row = bound_space(
        tenant_id="deep-copy",
        raw_kb_id="raw-deep-copy",
        wiki_kb_id="wiki-deep-copy",
    )
    scope = load_scope(session, row.id)

    copied = scope.model_copy(deep=True)

    assert copied == scope
    assert is_database_bound_scope(copied)
    require_current_scope(session, copied)


def test_s1_2_scope_does_not_keep_engine_alive_and_expired_ref_fails_closed(
    tmp_path: Path,
) -> None:
    from insurance_harness.adapters.weknora.scope import require_bound_scope
    from insurance_harness.db.base import Base, make_engine
    from insurance_harness.db.scope import is_database_bound_scope

    def issue_scope() -> tuple[KnowledgeScope, weakref.ReferenceType[object]]:
        engine = make_engine(f"sqlite:///{tmp_path}/scope-gc.db")
        Base.metadata.create_all(engine)
        with Session(engine) as local_session:
            row = KnowledgeSpace(
                id="gc-space",
                name="gc-space",
                binding_status="bound",
                tenant_id="gc-tenant",
                raw_kb_id="gc-raw",
                wiki_kb_id="gc-wiki",
            )
            local_session.add(row)
            local_session.commit()
            scope = load_scope(local_session, row.id)
        engine_reference: weakref.ReferenceType[object] = weakref.ref(engine)
        engine.dispose()
        return scope, engine_reference

    scope, engine_reference = issue_scope()
    gc.collect()

    assert engine_reference() is None
    assert not is_database_bound_scope(scope)
    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        require_bound_scope(scope)


def test_s1_2_mapper_only_session_can_load_and_validate_scope(tmp_path: Path) -> None:
    from insurance_harness.db.base import Base, make_engine
    from insurance_harness.db.scope import require_current_scope

    engine = make_engine(f"sqlite:///{tmp_path}/mapper-only.db")
    Base.metadata.create_all(engine)
    try:
        with Session(binds={KnowledgeSpace: engine}) as mapper_session:
            row = KnowledgeSpace(
                id="mapper-only-space",
                name="mapper-only",
                binding_status="bound",
                tenant_id="mapper-tenant",
                raw_kb_id="mapper-raw",
                wiki_kb_id="mapper-wiki",
            )
            mapper_session.add(row)
            mapper_session.commit()
            scope = load_scope(mapper_session, row.id)
        with Session(binds={KnowledgeSpace: engine}) as other_session:
            require_current_scope(other_session, scope)
    finally:
        engine.dispose()


def test_s1_2_mapper_bind_identity_rejects_other_mapper_engine_before_query(
    tmp_path: Path,
) -> None:
    from insurance_harness.db.base import Base, make_engine
    from insurance_harness.db.scope import require_current_scope

    default_engine = make_engine(f"sqlite:///{tmp_path}/default.db")
    engine_b = make_engine(f"sqlite:///{tmp_path}/mapper-b.db")
    engine_c = make_engine(f"sqlite:///{tmp_path}/mapper-c.db")
    for engine in (engine_b, engine_c):
        Base.metadata.create_all(engine)
        with Session(engine) as seed_session:
            seed_session.add(
                KnowledgeSpace(
                    id="shared-mapper-space",
                    name="shared",
                    binding_status="bound",
                    tenant_id="shared-tenant",
                    raw_kb_id="shared-raw",
                    wiki_kb_id="shared-wiki",
                )
            )
            seed_session.commit()
    with Session(
        default_engine,
        binds={KnowledgeSpace: engine_b},
    ) as issuer_session:
        scope = load_scope(issuer_session, "shared-mapper-space")

    default_statements: list[str] = []
    mapper_statements: list[str] = []

    def record_default(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        default_statements.append(statement)

    def record_mapper(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        mapper_statements.append(statement)

    event.listen(default_engine, "before_cursor_execute", record_default)
    event.listen(engine_c, "before_cursor_execute", record_mapper)
    try:
        with Session(
            default_engine,
            binds={KnowledgeSpace: engine_c},
        ) as consumer_session:
            with pytest.raises(ScopeViolation, match="^scope mismatch$"):
                require_current_scope(consumer_session, scope)
    finally:
        event.remove(default_engine, "before_cursor_execute", record_default)
        event.remove(engine_c, "before_cursor_execute", record_mapper)
        default_engine.dispose()
        engine_b.dispose()
        engine_c.dispose()

    assert default_statements == []
    assert mapper_statements == []


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


def _unbound_space(session: Session, *, space_id: str = "space-to-bind") -> KnowledgeSpace:
    row = KnowledgeSpace(
        id=space_id,
        name="pending binding",
        binding_status="unbound",
    )
    session.add(row)
    session.flush()
    return row


def _assert_unbound(row: KnowledgeSpace) -> None:
    assert row.binding_status == "unbound"
    assert row.tenant_id is None
    assert row.raw_kb_id is None
    assert row.wiki_kb_id is None


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


def test_s3_2_bind_space_concurrent_unique_failure_rolls_back_savepoint_and_keeps_session_usable(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _unbound_space(session)
    real_flush = session.flush
    calls = 0

    def race_on_binding_flush(objects: Sequence[Any] | None = None) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise IntegrityError("statement", {}, Exception("private database value"))
        real_flush(objects)

    monkeypatch.setattr(session, "flush", race_on_binding_flush)
    with pytest.raises(ScopeBindingError) as error:
        bind_space(
            session,
            row.id,
            tenant_id="tenant-race",
            raw_kb_id="raw-race",
            wiki_kb_id="wiki-race",
        )
    monkeypatch.setattr(session, "flush", real_flush)

    assert calls == 2
    assert str(error.value) == "knowledge space binding failed"
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    session.expire_all()
    target = session.scalar(select(KnowledgeSpace).where(KnowledgeSpace.id == row.id))
    assert target is not None
    _assert_unbound(target)

    safe = KnowledgeSpace(id="safe-space", name="safe", binding_status="unbound")
    session.add(safe)
    session.commit()
    assert session.get(KnowledgeSpace, safe.id) is not None


def test_s3_2_bind_space_rejects_dirty_unit_of_work_before_savepoint_preflush(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _unbound_space(session)
    invalid_pending = KnowledgeSpace(
        id="invalid-pending",
        name="invalid",
        binding_status="bound",
    )
    session.add(invalid_pending)
    real_flush = session.flush
    flush_calls = 0

    def counting_flush(objects: Sequence[Any] | None = None) -> None:
        nonlocal flush_calls
        flush_calls += 1
        real_flush(objects)

    monkeypatch.setattr(session, "flush", counting_flush)
    with pytest.raises(ScopeBindingError) as error:
        bind_space(
            session,
            target.id,
            tenant_id="tenant-a",
            raw_kb_id="raw-a",
            wiki_kb_id="wiki-a",
        )

    assert flush_calls == 0
    assert str(error.value) == "knowledge space binding failed"
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert session.is_active
    assert invalid_pending in session.new
    queried = session.scalar(
        select(KnowledgeSpace)
        .where(KnowledgeSpace.id == target.id)
        .execution_options(autoflush=False)
    )
    assert queried is not None
    _assert_unbound(queried)


def test_s3_2_bind_space_requires_an_existing_caller_transaction(
    session: Session,
) -> None:
    target = _unbound_space(session)
    space_id = target.id
    session.commit()
    assert not session.in_transaction()

    with pytest.raises(ScopeBindingError, match="binding failed"):
        bind_space(
            session,
            space_id,
            tenant_id="tenant-a",
            raw_kb_id="raw-a",
            wiki_kb_id="wiki-a",
        )

    assert session.is_active
    assert not session.in_transaction()
    reloaded = session.get(KnowledgeSpace, space_id)
    assert reloaded is not None
    _assert_unbound(reloaded)


def test_s3_2_bind_space_rejects_inactive_session_without_hiding_the_caller_error(
    session: Session,
) -> None:
    session.add(
        KnowledgeSpace(
            id="invalid-row",
            name="invalid",
            binding_status="bound",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    assert not session.is_active

    with pytest.raises(ScopeBindingError) as error:
        bind_space(
            session,
            "space-to-bind",
            tenant_id="tenant-a",
            raw_kb_id="raw-a",
            wiki_kb_id="wiki-a",
        )

    assert str(error.value) == "knowledge space binding failed"
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert not session.is_active


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("space_id", ""),
        ("space_id", "s" * 37),
        ("space_id", " space-to-bind"),
        ("space_id", "space-to-bind "),
        ("space_id", "space\u200bto-bind"),
        ("tenant_id", " tenant-a"),
        ("tenant_id", "tenant-a\n"),
        ("tenant_id", "tenant\ue000"),
        ("raw_kb_id", "raw-a "),
        ("raw_kb_id", "raw\x00a"),
        ("raw_kb_id", "raw\u0378a"),
        ("wiki_kb_id", "wiki\u200ba"),
        ("wiki_kb_id", "wiki\ud800a"),
    ],
)
def test_s3_2_bind_space_rejects_boundary_whitespace_and_unicode_category_c(
    session: Session,
    field: str,
    invalid_value: str,
) -> None:
    target = _unbound_space(
        session,
        space_id=invalid_value if field == "space_id" else "space-to-bind",
    )
    values = {
        "space_id": target.id,
        "tenant_id": "tenant-a",
        "raw_kb_id": "raw-a",
        "wiki_kb_id": "wiki-a",
    }
    values[field] = invalid_value

    with pytest.raises(ScopeBindingError, match="binding failed"):
        bind_space(
            session,
            values["space_id"],
            tenant_id=values["tenant_id"],
            raw_kb_id=values["raw_kb_id"],
            wiki_kb_id=values["wiki_kb_id"],
        )

    _assert_unbound(target)


def test_s3_2_bind_space_accepts_normal_unicode_and_opaque_identifiers(
    session: Session,
) -> None:
    target = _unbound_space(session, space_id="空间-甲")

    result = bind_space(  # type: ignore[func-returns-value]
        session,
        target.id,
        tenant_id="租户-甲",
        raw_kb_id="raw:%2F:原始库-α",
        wiki_kb_id="知识库-🛡️",
    )
    assert result is None
    session.commit()

    scope = load_scope(session, target.id)
    assert scope.tenant_id == "租户-甲"
    assert scope.raw_kb_id == "raw:%2F:原始库-α"
    assert scope.wiki_kb_id == "知识库-🛡️"
