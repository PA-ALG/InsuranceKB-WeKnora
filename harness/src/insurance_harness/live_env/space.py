"""Harness-owned ``KnowledgeSpace`` provisioning adapter.

The existing table has no ownership-marker column.  Local-live ownership is
therefore encoded in a deterministic UUID derived from the environment marker
and stable space name.  A same-name row with any other identifier is exposed as
unowned so the domain provisioner fails closed instead of adopting it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.live_env.provision import (
    DesiredResource,
    OwnedResource,
    OwnershipMismatch,
)


class HarnessSpaceBackend:
    """Persist the local-live raw/wiki binding in the Harness database."""

    def __init__(self, factory: sessionmaker[Session], *, marker: str) -> None:
        if not marker:
            raise ValueError("space ownership marker must not be empty")
        self._factory = factory
        self._marker = marker

    def _owned_id(self, name: str) -> str:
        identity = f"insurancekb-local-live:{self._marker}:{name}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, identity))

    def _resource(self, row: KnowledgeSpace) -> OwnedResource:
        owned = row.id == self._owned_id(row.name)
        bound = (
            row.binding_status == "bound"
            and row.tenant_id is not None
            and row.raw_kb_id is not None
            and row.wiki_kb_id is not None
        )
        knowledge_base_ids: tuple[str, ...] = ()
        if bound:
            assert row.raw_kb_id is not None
            assert row.wiki_kb_id is not None
            knowledge_base_ids = (row.raw_kb_id, row.wiki_kb_id)
        return OwnedResource(
            id=row.id,
            kind="space",
            name=row.name,
            tenant_id=row.tenant_id or "",
            marker=self._marker if owned else "",
            role="bound" if bound else row.binding_status,
            knowledge_base_ids=knowledge_base_ids,
        )

    async def list_resources(self, kind: str) -> Sequence[OwnedResource]:
        if kind != "space":
            return ()
        with self._factory() as session:
            rows = session.scalars(
                select(KnowledgeSpace).order_by(KnowledgeSpace.name, KnowledgeSpace.id)
            ).all()
            return tuple(self._resource(row) for row in rows)

    async def create_resource(self, desired: DesiredResource) -> OwnedResource:
        if (
            desired.kind != "space"
            or desired.marker != self._marker
            or desired.role != "bound"
            or not desired.tenant_id
            or desired.dimension is not None
            or desired.capabilities
            or len(desired.knowledge_base_ids) != 2
            or not all(desired.knowledge_base_ids)
        ):
            raise OwnershipMismatch("space create request mismatch")

        row = KnowledgeSpace(
            id=self._owned_id(desired.name),
            name=desired.name,
            binding_status="bound",
            tenant_id=desired.tenant_id,
            raw_kb_id=desired.knowledge_base_ids[0],
            wiki_kb_id=desired.knowledge_base_ids[1],
        )
        try:
            with self._factory() as session:
                session.add(row)
                session.commit()
        except IntegrityError:
            raise OwnershipMismatch("space ownership mismatch") from None
        return self._resource(row)
