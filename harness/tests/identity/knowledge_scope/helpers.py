"""016 S1/S3: KnowledgeSpace binding and fail-closed scope loading — shared factory protocols."""

from typing import Protocol

from sqlalchemy.orm import Session

from insurance_harness.db.models import KnowledgeSpace


class BoundSpaceFactory(Protocol):
    def __call__(
        self, *, tenant_id: str, raw_kb_id: str, wiki_kb_id: str
    ) -> KnowledgeSpace: ...


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
