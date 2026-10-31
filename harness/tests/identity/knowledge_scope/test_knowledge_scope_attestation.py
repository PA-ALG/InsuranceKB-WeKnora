"""KnowledgeScope (016 S1.2): database attestation, copies, engine lifetime and mappers."""

import gc
import weakref
from pathlib import Path
from typing import Protocol

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
    load_scope,
)
from tests.identity.knowledge_scope.helpers import BoundSpaceFactory


class BoundScopeFactory(Protocol):
    def __call__(
        self, *, tenant_id: str, raw_kb_id: str, wiki_kb_id: str
    ) -> KnowledgeScope: ...


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
