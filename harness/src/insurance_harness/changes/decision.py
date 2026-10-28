"""Ordered S8a decisions over contract Claims, without publishing or I/O."""

import hashlib
import json
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError

from insurance_harness.bundle.client import Release
from insurance_harness.changes.normalize import values_equal
from insurance_harness.changes.types import ChangeItem, ChangeSet, Verdict
from insurance_harness.contracts.compile import ReviewItem
from insurance_harness.contracts.enums import (
    ChangedBy,
    ClaimState,
    LocatorKind,
    ReviewKind,
    ReviewStatus,
)
from insurance_harness.contracts.knowledge import Claim, Maintenance

_SOURCE_REF = re.compile(r"source:v1:([^:\s]+):[1-9][0-9]*:([a-fA-F0-9]{64})")
# What the platform writes for an expert revision (internal/enterprise/expert, S9a §2).
_EXPERT_REF = re.compile(r"expert:v1:[^:\s]+:([a-fA-F0-9]{64})")
_DOCUMENT_ID = re.compile(r"[^:\s]+")
_PUBLISH = {Verdict.ADD, Verdict.FILL, Verdict.SUPERSEDE, Verdict.REFRESH, Verdict.UPGRADE}


@dataclass(frozen=True)
class _Base:
    claim: Claim
    slug: str
    documents: frozenset[str]


def _documents(claim: Claim) -> frozenset[str]:
    """The source documents a Claim rests on. An expert revision cites its revision record, not a
    material, so it adds none: withdrawing materials never retracts it (S9d)."""
    documents = set()
    for evidence in claim.evidence:
        if evidence.locator.kind == LocatorKind.EXPERT_REVISION:
            expert = _EXPERT_REF.fullmatch(evidence.source_ref)
            if expert is None or expert[1].lower() != evidence.file_sha256.lower():
                raise ValueError("invalid source_ref")
            continue
        match = _SOURCE_REF.fullmatch(evidence.source_ref)
        if match is None or match[2].lower() != evidence.file_sha256.lower():
            raise ValueError("invalid source_ref")
        documents.add(match[1])
    return frozenset(documents)


def _base_claims(
    active: Release | None, entity_id: str,
) -> tuple[dict[str, _Base], set[str], dict[str, str | None]]:
    selected: dict[str, _Base] = {}
    slug_owners: dict[str, str | None] = {}
    keys: set[str] = set()
    foreign: set[str] = set()
    if active is None:
        return selected, foreign, slug_owners
    for member in active.members:
        if member.logical_slug in slug_owners:
            raise ValueError("duplicate active member slug")
        payload = member.payload if isinstance(member.payload, dict) else {}
        raw_key = payload.get("logical_key") if member.kind == "claim" else None
        key = raw_key if isinstance(raw_key, str) and raw_key.strip() else None
        # Every active slug is reserved, even when its payload belongs to an older
        # contract. Only this product's claims need current contract validation.
        slug_owners[member.logical_slug] = key
        if key is not None:
            if key in keys:
                raise ValueError("duplicate active claim logical_key")
            keys.add(key)
        if member.kind != "claim" or payload.get("subject_ref") != entity_id:
            if key is not None:
                foreign.add(key)
            continue
        try:
            claim = Claim.model_validate(payload)
        except ValidationError:
            raise ValueError("invalid active claim") from None
        selected[claim.logical_key] = _Base(claim, member.logical_slug, _documents(claim))
    return selected, foreign, slug_owners


def _quote_hashes(claim: Claim) -> set[str]:
    """SHA-256 identity is independent of the contract's permitted hex casing."""
    return {item.quote_sha256.lower() for item in claim.evidence}


def _equivalent(base: Claim, incoming: Claim) -> bool:
    if base.state != incoming.state:
        return False
    old_hashes, new_hashes = _quote_hashes(base), _quote_hashes(incoming)
    return values_equal(base.value, incoming.value) or bool(old_hashes and old_hashes == new_hashes)


def _identity(claim: Claim) -> tuple[str, str]:
    return claim.provenance.compiler, claim.provenance.compiler_version


def _verdict(base: _Base | None, incoming: Claim | None,
             incoming_documents: frozenset[str], current: set[str], new: set[str]) -> Verdict:
    if base is None:
        return Verdict.ADD
    withdrawn = bool(base.documents) and not base.documents & current
    if incoming is None:
        return Verdict.RETRACT if withdrawn and not base.claim.expert_lock else Verdict.KEEP
    equivalent = _equivalent(base.claim, incoming)
    if base.claim.expert_lock and not equivalent:
        return Verdict.CONFLICT
    if equivalent:
        return Verdict.REFRESH if withdrawn else Verdict.UNCHANGED
    if base.claim.state == ClaimState.UNKNOWN:
        return Verdict.FILL
    if withdrawn:
        return Verdict.SUPERSEDE
    fresh = bool(incoming_documents & new)
    # The KEEP rules below absorb model churn on unchanged materials (S8). A compiler upgrade is
    # not churn: the new value is published for review instead of silently kept (S12c-1b).
    if not fresh and _identity(base.claim) != _identity(incoming):
        return Verdict.UPGRADE
    if incoming.state == ClaimState.UNKNOWN:
        return Verdict.KEEP
    if not fresh:
        return Verdict.KEEP
    return Verdict.CONFLICT


def _member(incoming: Claim, base: _Base | None, verdict: Verdict, changed_at: str) -> Claim:
    revision = 0 if base is None else base.claim.maintenance.revision_no
    if verdict in {Verdict.FILL, Verdict.SUPERSEDE, Verdict.UPGRADE}:
        revision += 1
    maintenance = Maintenance(
        revision_no=revision,
        first_release_id=base.claim.maintenance.first_release_id if base else None,
        changed_by=ChangedBy.COMPILE,
        changed_at=changed_at,
        reason=verdict.value,
    )
    # An equivalent compile may refresh evidence, but only an expert may release
    # a lock. Compiler defaults must not silently make the next update overwritable.
    return incoming.model_copy(update={
        "maintenance": maintenance,
        "expert_lock": incoming.expert_lock or bool(base and base.claim.expert_lock),
    }, deep=True)


def _review(base: _Base, incoming: Claim) -> ReviewItem:
    value = incoming.value
    # ReviewItem has a string candidate slot. Typed Claim values retain their JSON type
    # inside that slot, rather than Python repr (notably booleans and string lists).
    candidate = value if value is None or isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    )
    hashes = sorted(_quote_hashes(base.claim) | _quote_hashes(incoming))
    identity = json.dumps([base.slug, incoming.logical_key, hashes, candidate],
                          ensure_ascii=False, separators=(",", ":"))
    return ReviewItem(
        item_id="conflict-" + hashlib.sha256(identity.encode()).hexdigest(),
        kind=ReviewKind.CONFLICT,
        target=base.slug,
        evidence=hashes,
        status=ReviewStatus.OPEN,
        resolution_candidate=candidate,
    )


def decide_changes(
    active: Release | None,
    entity_id: str,
    incoming: Sequence[Claim],
    current_knowledge: Collection[str],
) -> ChangeSet:
    """Apply the ten first-match rules to one product, failing closed on ambiguity.

    A missing active release has no base members. Documents are knowledge
    identities, independent of a source's parse attempt. A
    document is new only if no base claim of this product referenced it previously.
    """
    if not isinstance(entity_id, str) or not entity_id.strip():
        raise ValueError("invalid entity_id")
    if isinstance(current_knowledge, str) or any(
        not isinstance(item, str) or _DOCUMENT_ID.fullmatch(item) is None
        for item in current_knowledge
    ):
        raise ValueError("invalid current_knowledge")
    current = set(current_knowledge)
    base, foreign, slug_owners = _base_claims(active, entity_id)
    incoming_by_key: dict[str, Claim] = {}
    incoming_documents: dict[str, frozenset[str]] = {}
    for claim in incoming:
        if claim.subject_ref != entity_id:
            raise ValueError("incoming subject_ref mismatch")
        if claim.logical_key in foreign:
            raise ValueError("incoming subject_ref ownership collision")
        if claim.logical_key in incoming_by_key:
            raise ValueError("duplicate incoming claim logical_key")
        incoming_by_key[claim.logical_key] = claim
        incoming_documents[claim.logical_key] = _documents(claim)
    known = {document for item in base.values() for document in item.documents}
    new = current - known
    changed_at = datetime.now(UTC).isoformat()
    items: list[ChangeItem] = []
    members: list[Claim] = []
    removals: list[str] = []
    reviews: list[ReviewItem] = []
    for key in sorted(base.keys() | incoming_by_key.keys()):
        old, compiled = base.get(key), incoming_by_key.get(key)
        verdict = _verdict(old, compiled, incoming_documents.get(key, frozenset()), current, new)
        items.append(ChangeItem(key, verdict, old.slug if old else None, verdict.value))
        if verdict in _PUBLISH:
            assert compiled is not None
            # Assembly addresses claims by logical_key. An old alias would remain
            # live instead of being replaced, so reject that ambiguous replacement.
            if old is not None and old.slug != key:
                raise ValueError("BASE_SLUG_MISMATCH")
            if key in slug_owners and slug_owners[key] != key:
                raise ValueError("ACTIVE_SLUG_OWNERSHIP_COLLISION")
            members.append(_member(compiled, old, verdict, changed_at))
        elif verdict == Verdict.RETRACT:
            assert old is not None
            removals.append(old.slug)
        elif verdict == Verdict.CONFLICT:
            assert old is not None and compiled is not None
            reviews.append(_review(old, compiled))
    return ChangeSet(tuple(items), tuple(members), tuple(removals), tuple(reviews))
