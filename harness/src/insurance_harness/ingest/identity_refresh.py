"""The metadata publish path (PV-4 Spec §3.3, PV-0 appendix A §2).

The fact path cannot carry version identity: an unchanged value is UNCHANGED and an entity
already in Active is not resent. This path publishes it separately, as `identity_refresh`
bundles the platform checks against the whole target Release. From Active and a v2 registry it
changes only the registered version entities (identifiers, sale period, family) and their
claims (`product_version_ref`), adds the `supersedes` relation of every unique predecessor and
removes stale ones; every other member is left exactly as it is.

A version is an entity of a versioned product type (the types the catalog's packs compile
product entities with) under a registered ID that no entity of another type shares; only
`supersedes` relations between two versions are this registry's to add or remove (#510 R2).

A run plans on the Active of each step, so an interruption or a moved Head is recovered by
running again: there is no local receipt to trust.
"""

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from insurance_harness.bundle.assemble import BundleError
from insurance_harness.bundle.canonical import member_digest
from insurance_harness.bundle.client import (
    MAX_BUNDLE_BYTES,
    DecisionInput,
    Head,
    PlatformClient,
    PlatformError,
    Release,
    ReleaseMember,
    publish,
)
from insurance_harness.compilers.schema_fields.page import EntityMetadata, catalog_entity_types
from insurance_harness.contracts.bundle import BundleMember, CandidateBundle
from insurance_harness.contracts.enums import Origin
from insurance_harness.contracts.knowledge import SUPERSEDES, Relation, supersedes_relation_id
from insurance_harness.ingest.registry import V2, ProductRegistry
from insurance_harness.ingest.version_metadata import entity_metadata

COMPILER_IDENTITY = "harness/identity_refresh"
IDENTITY_KEYS = ("product_code", "version_key", "filing_no")
_MARGIN = 512  # JSON separators and rounding, well inside the platform's limit


class RefreshError(ValueError):
    """A caller-safe code; never a payload."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RefreshPlan:
    members: tuple[BundleMember, ...]
    removals: tuple[str, ...]
    groups: Mapping[str, str]  # slug (member or removal) -> the product it belongs to
    counts: Mapping[str, int]

    @property
    def noop(self) -> bool:
        return not self.members and not self.removals


def product_types(catalog_path: str | Path) -> frozenset[str]:
    """The versioned product types: those the catalog's packs compile product entities with."""
    try:
        return catalog_entity_types(catalog_path)
    except BundleError:
        raise RefreshError("CATALOG_UNREADABLE") from None


def plan_refresh(
    active: Release, registry: ProductRegistry, entity_types: Collection[str]
) -> RefreshPlan:
    """What Active needs so that every registered version carries its published identity."""
    if registry.contract != V2 or registry.metadata_basis is None:
        raise RefreshError("REGISTRY_NOT_V2")
    products, basis = registry.products, registry.metadata_basis
    present = _versions(active, products, entity_types)
    members: list[BundleMember] = []
    groups: dict[str, str] = {}
    counts = {"entities": 0, "claims": 0, "relations_added": 0, "relations_removed": 0}
    existing: dict[str, ReleaseMember] = {}
    for m in active.members:
        payload = m.payload if isinstance(m.payload, dict) else {}
        if m.kind == "entity" and payload.get("entity_id") in present:
            eid = payload["entity_id"]
            meta = entity_metadata(eid, products[eid], basis)
            new = _entity_payload(payload, meta)
            group, counted = eid, "entities"
        elif m.kind == "claim" and payload.get("subject_ref") in present:
            new = {**payload, "product_version_ref": payload["subject_ref"]}
            group, counted = payload["subject_ref"], "claims"
        else:
            if (
                m.kind == "relation"
                and payload.get("predicate") == SUPERSEDES
                and payload.get("from") in present
                and payload.get("to") in present
            ):
                existing[m.logical_slug] = m
            continue
        if member_digest(new) != member_digest(payload):
            members.append(_changed(m, new))
            groups[m.logical_slug] = group
            counts[counted] += 1
    desired = _relations(registry, present)
    for slug, (newer, payload) in desired.items():
        if slug not in existing:
            members.append(_new_relation(slug, payload))
            groups[slug] = newer
            counts["relations_added"] += 1
    removals = sorted(slug for slug in existing if slug not in desired)
    for slug in removals:
        stale = existing[slug].payload
        source = stale.get("from") if isinstance(stale, dict) else None
        groups[slug] = source if isinstance(source, str) else ""
    counts["relations_removed"] = len(removals)
    return RefreshPlan(tuple(members), tuple(removals), groups, counts)


def refresh_bundles(
    plan: RefreshPlan,
    base: Head,
    *,
    compiler_identity: str = COMPILER_IDENTITY,
    max_bytes: int = MAX_BUNDLE_BYTES,
) -> list[CandidateBundle]:
    """The plan in bundles under the size limit: a product's entity, relations and removals
    together and first, its claims after them, a product's members kept in one bundle when they
    fit."""
    if plan.noop:
        return []
    empty = _bundle([], [], base, compiler_identity)
    budget = max_bytes - _size(empty) - _MARGIN
    chunks: list[tuple[list[BundleMember], list[str]]] = [([], [])]
    used = 0
    for head, removals, claims in _grouped(plan):
        head_size = sum(_item(m) for m in head) + sum(_text(s) for s in removals)
        if head_size > budget:
            raise RefreshError("BUNDLE_TOO_LARGE")
        if used + head_size > budget:
            chunks.append(([], []))
            used = 0
        chunks[-1][0].extend(head)
        chunks[-1][1].extend(removals)
        used += head_size
        for claim in claims:
            size = _item(claim)
            if size > budget:
                raise RefreshError("BUNDLE_TOO_LARGE")
            if used + size > budget:
                chunks.append(([], []))
                used = 0
            chunks[-1][0].append(claim)
            used += size
    bundles = [_bundle(m, r, base, compiler_identity) for m, r in chunks if m or r]
    if any(_size(bundle) > max_bytes for bundle in bundles):
        raise RefreshError("BUNDLE_TOO_LARGE")
    return bundles


def run_refresh(
    client: PlatformClient,
    registry: ProductRegistry,
    *,
    entity_types: Collection[str],
    live: bool,
    max_bytes: int = MAX_BUNDLE_BYTES,
    max_bundles: int | None = None,
) -> dict[str, Any]:
    """Plan, and only when `live` publish one bundle at a time, replanning on each new Active.

    Each bundle is decided by machine under `identity_refresh@<commit>` and activated; a
    platform error stops the run with its code, and a run never publishes more than
    `max_bundles` (default: the bundles planned at the start, plus two).
    """
    if registry.contract != V2 or registry.metadata_basis is None:
        raise RefreshError("REGISTRY_NOT_V2")  # before any remote read
    space = registry.space_id
    active = client.active(space)
    if active is None:
        raise RefreshError("NO_ACTIVE_RELEASE")
    plan = plan_refresh(active, registry, entity_types)
    chunks = refresh_bundles(plan, active.head, max_bytes=max_bytes)
    summary: dict[str, Any] = {
        "dry_run": not live,
        "base_release_id": active.id,
        "noop": plan.noop,
        "bundles": len(chunks),
        **plan.counts,
    }
    if not live or plan.noop:
        return summary
    decision = DecisionInput(
        outcome="approve",
        mode="machine",
        policy_ref=f"identity_refresh@{registry.metadata_basis.commit}",
        reason="identity_refresh",
    )
    limit = max_bundles if max_bundles is not None else len(chunks) + 2
    releases: list[str] = []
    try:
        while chunks:
            if len(releases) >= limit:
                summary["stopped"] = "MAX_BUNDLES"
                break
            result = publish(client, space, chunks[0], decision=decision, activate=True)
            assert result.release is not None  # activate=True reads the release back
            releases.append(result.release.id)
            active = client.active(space)
            if active is None:
                raise RefreshError("NO_ACTIVE_RELEASE")
            plan = plan_refresh(active, registry, entity_types)
            chunks = refresh_bundles(plan, active.head, max_bytes=max_bytes)
    except PlatformError as error:
        summary["stopped"] = error.code
    summary["releases"] = releases
    return summary


def _versions(
    active: Release, products: Mapping[str, object], entity_types: Collection[str]
) -> set[str]:
    """Registered IDs whose entities in Active are all of a versioned product type."""
    versioned: set[str] = set()
    other: set[str] = set()
    for m in active.members:
        payload = m.payload if isinstance(m.payload, dict) else {}
        eid = payload.get("entity_id")
        if m.kind == "entity" and isinstance(eid, str):
            (versioned if payload.get("entity_type") in entity_types else other).add(eid)
    return {eid for eid in versioned - other if eid in products}


def _entity_payload(payload: dict[str, Any], meta: EntityMetadata) -> dict[str, Any]:
    new = dict(payload)
    identifiers = payload.get("identifiers")
    kept = {k: v for k, v in (identifiers if isinstance(identifiers, dict) else {}).items()
            if k not in IDENTITY_KEYS}
    new["identifiers"] = {**kept, **meta.identifiers}
    for key, value in (("lifecycle", meta.lifecycle), ("product_family", meta.family)):
        if value is None:
            new.pop(key, None)
        else:
            new[key] = value.model_dump(mode="json")
    return new


def _relations(
    registry: ProductRegistry, present: set[str]
) -> dict[str, tuple[str, dict[str, Any]]]:
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    for pid, entry in sorted(registry.products.items()):
        older = entry.version.predecessor if entry.version is not None else None
        if older is None or pid not in present or older not in present:
            continue
        rid = supersedes_relation_id(pid, older)
        relation = Relation.model_validate(
            {"relation_id": rid, "predicate": SUPERSEDES, "from": pid, "to": older}
        )
        out[f"relation/{rid}"] = (pid, relation.model_dump(mode="json"))
    return out


def _changed(old: ReleaseMember, payload: dict[str, Any]) -> BundleMember:
    return BundleMember(
        kind=old.kind,
        logical_slug=old.logical_slug,
        payload=payload,
        member_digest=member_digest(payload),
        evidence_refs=list(old.evidence_refs),
        access_scope=old.access_scope,
    )


def _new_relation(slug: str, payload: dict[str, Any]) -> BundleMember:
    return BundleMember(
        kind="relation",
        logical_slug=slug,
        payload=payload,
        member_digest=member_digest(payload),
        access_scope="space",
    )


def _grouped(
    plan: RefreshPlan,
) -> list[tuple[list[BundleMember], list[str], list[BundleMember]]]:
    """Per product, in product order: entity and relations, its removals, then its claims."""
    order: dict[str, tuple[list[BundleMember], list[str], list[BundleMember]]] = {}
    for member in plan.members:
        head, _, claims = order.setdefault(plan.groups[member.logical_slug], ([], [], []))
        (claims if member.kind == "claim" else head).append(member)
    for slug in plan.removals:
        order.setdefault(plan.groups[slug], ([], [], []))[1].append(slug)
    for head, _, _ in order.values():
        head.sort(key=lambda m: (m.kind != "entity", m.logical_slug))
    return [order[key] for key in sorted(order)]


def _bundle(
    members: Sequence[BundleMember], removals: Sequence[str], base: Head, identity: str
) -> CandidateBundle:
    return CandidateBundle(
        contract_version="1",
        base_release_id=base.release_id,
        base_epoch=base.epoch,
        origin=Origin.IDENTITY_REFRESH,
        members=list(members),
        removals=list(removals),
        review_plan=[],
        compiler_identity=identity,
    )


def _size(bundle: CandidateBundle) -> int:
    return len(json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False).encode("utf-8"))


def _item(member: BundleMember) -> int:
    return _text(member.model_dump(mode="json"))


def _text(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8")) + 2  # separator and slack
