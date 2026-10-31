"""016 S1: KnowledgeSpace binding shape and which spaces build a scope.

This module keeps its path: the digest-pinned plugin contract
(deploy/upstream/weknora-plugin-contract.yaml) and the trusted local-live image workflow name
one of its tests. The other 016 scope contracts live in identity/knowledge_scope/.
"""

import pytest
from pydantic import ValidationError
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope import (
    UnboundKnowledgeSpace,
    load_scope,
)
from tests.identity.knowledge_scope.helpers import BoundSpaceFactory


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
