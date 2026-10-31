"""bind_space (016 S3.2): savepoints, caller transactions and identifier validation."""

from collections.abc import Sequence
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope import (
    ScopeBindingError,
    bind_space,
    load_scope,
)
from tests.identity.knowledge_scope.helpers import _assert_unbound, _unbound_space


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
