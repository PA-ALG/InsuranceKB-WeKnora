"""One pinned version with verified ownership rows and selective member reads."""

import json
from collections.abc import Iterable, Iterator

from insurance_harness.bundle.canonical import member_digest
from insurance_harness.bundle.client import PlatformClient, PlatformError, Release, ReleaseMember
from insurance_harness.bundle.platform_response import require_identifier
from insurance_harness.bundle.release_reads import FixedHeader, MemberIndexRow
from insurance_harness.bundle.request_budget import ReleaseReadBudget


class FixedRelease:
    def __init__(
        self,
        client: PlatformClient,
        space: str,
        budget: ReleaseReadBudget,
        release_id: str,
        header: FixedHeader | None = None,
    ) -> None:
        require_identifier(release_id)
        if release_id == "active":
            raise PlatformError("INVALID_RESPONSE")
        index = client.member_index(space, release_id, budget)
        if index.id != release_id or header is not None and index.identity != header.identity:
            raise PlatformError("RELEASE_MISMATCH")
        if index.base_release_id:
            require_identifier(index.base_release_id)
        rows = {r.logical_slug: r for r in index.members}
        if len(rows) != len(index.members):
            raise PlatformError("INVALID_RESPONSE")
        self.header = FixedHeader.model_validate(index.model_dump(exclude={"members"}))
        self.rows = rows
        self._client, self._space, self._budget = client, space, budget
        self._bodies: dict[str, ReleaseMember] = {}

    @classmethod
    def active(
        cls, client: PlatformClient, space: str, budget: ReleaseReadBudget
    ) -> "FixedRelease | None":
        header = client.active_summary(space, budget)
        return None if header is None else cls(client, space, budget, header.id, header)

    def claims_for(self, subjects: Iterable[str]) -> list[str]:
        entities = set(subjects)
        return [
            slug
            for slug, row in self.rows.items()
            if row.kind == "claim" and row.subject_ref in entities
        ]

    def members(self, slugs: Iterable[str]) -> list[ReleaseMember]:
        requested = list(dict.fromkeys(slugs))
        missing = [s for s in requested if s in self.rows and s not in self._bodies]
        for batch in _lookup_batches(missing):
            self._fetch(batch)
        return [self._bodies[s] for s in requested if s in self._bodies]

    def _fetch(self, requested: list[str]) -> None:
        result = self._client.member_lookup(self._space, self.header.id, requested, self._budget)
        expected = set(requested)
        found = {member.logical_slug: member for member in result.members}
        if (
            result.identity != self.header.identity
            or len(found) != len(result.members)
            or found.keys() != expected
            or result.missing
        ):
            raise PlatformError("RELEASE_MISMATCH")
        for slug, member in found.items():
            if not _agrees(member, self.rows[slug]):
                raise PlatformError("RELEASE_MISMATCH")
        self._bodies.update(found)

    def complete_view(self, bodies: Iterable[str]) -> Release:
        """Keep all slug/key reservations while loading the requested authoritative Claim bodies."""
        self.members(bodies)
        members = [
            self._bodies[slug] if slug in self._bodies else _projected(row)
            for slug, row in self.rows.items()
        ]
        return Release(**self.header.model_dump(), members=members)

    def body_view(self, bodies: Iterable[str]) -> Release:
        found = {member.logical_slug: member for member in self.members(bodies)}
        return Release(
            **self.header.model_dump(), members=[found[s] for s in self.rows if s in found]
        )


def _projected(row: MemberIndexRow) -> ReleaseMember:
    return ReleaseMember(
        kind=row.kind,
        logical_slug=row.logical_slug,
        member_digest=row.member_digest,
        payload={"subject_ref": row.subject_ref, "logical_key": row.logical_key},
    )


def _agrees(member: ReleaseMember, row: MemberIndexRow) -> bool:
    if member.kind != row.kind or member.member_digest != row.member_digest:
        return False
    try:
        if member_digest(member.payload) != row.member_digest:
            return False
    except (ValueError, RecursionError):
        return False
    payload = member.payload if isinstance(member.payload, dict) else {}
    if row.kind == "claim":
        return _text(payload.get("subject_ref")) == row.subject_ref and (
            _text(payload.get("logical_key")) == row.logical_key
        )
    return row.kind != "entity" or _text(payload.get("entity_id")) == row.entity_id


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _lookup_batches(slugs: Iterable[str]) -> Iterator[list[str]]:
    overhead = len(b'{"slugs": []}')
    batch: list[str] = []
    size = overhead
    for slug in slugs:
        width = len(json.dumps(slug, ensure_ascii=False).encode())
        if overhead + width > 64 << 10:
            raise PlatformError("RELEASE_READ_LIMIT")
        if len(batch) == 256 or size + width + 2 > 64 << 10:
            yield batch
            batch, size = [], overhead
        size += width + (2 if batch else 0)
        batch.append(slug)
    if batch:
        yield batch
