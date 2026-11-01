"""One method run: admission, values, change decisions and one candidate bundle (Spec §4–§6).

Admission updates the methods section in memory; every method still in force (not suppressed, at
least one valid link) is then compiled from its original paragraphs, and its Claims go through the
same change decisions as a product's (same-slug replacement, conflicts to a person). A method that
left (suppressed, or no valid link) takes all of its published Claims and its entity out of the
Active release; its registry entry stays. Nothing is written here: the caller writes the plan and
then the registry (cli.py), so a failed bundle leaves both unchanged.
"""

import hashlib
import json
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Any

from insurance_harness.bundle.assemble import assemble, retired_claims
from insurance_harness.bundle.client import Release
from insurance_harness.catalog.method_cards import MethodCards, load_method_cards
from insurance_harness.catalog.review_policy import ReviewPolicy, load_review_policy
from insurance_harness.catalog.sales_taxonomy import SalesTaxonomy, Term, load_sales_taxonomy
from insurance_harness.changes import decide_changes
from insurance_harness.changes.types import ChangeSet, Verdict
from insurance_harness.compilers.methods.admission import Admission, CandidateFile, admit
from insurance_harness.compilers.methods.claims import (
    COMPILER,
    claim_signals,
    compiler_version,
    method_content,
    method_entity,
)
from insurance_harness.compilers.methods.paragraphs import (
    MaterialCache,
    MethodParagraphs,
    ParagraphsError,
)
from insurance_harness.compilers.methods.parse import MethodResponseError, parse_method_response
from insurance_harness.compilers.methods.profile import method_profile, profile_needed
from insurance_harness.compilers.methods.prompt import build_method_request, offered_labels
from insurance_harness.compilers.methods.responses import ResponseMissing
from insurance_harness.compilers.schema_fields.engine import CompletionPort
from insurance_harness.compilers.schema_fields.prompt import JudgeLikeRequest
from insurance_harness.contracts.bundle import CandidateBundle, ReviewPlan
from insurance_harness.contracts.compile import ReviewItem
from insurance_harness.contracts.enums import ReviewKind, ReviewMode, ReviewStatus
from insurance_harness.contracts.knowledge import Claim, Entity
from insurance_harness.evidence.weknora_pages import SourcePagesError
from insurance_harness.ingest.method_registry import MethodEntry, MethodLink, valid_links
from insurance_harness.ingest.registry import V2, ProductRegistry, RegistryError
from insurance_harness.ingest.source_map import PageReader
from insurance_harness.review.routing import Route, labelled, route

PRODUCT_INFO = "CONTAINS_PRODUCT_INFO"


@dataclass(frozen=True)
class MethodRun:
    registry: ProductRegistry  # with the admitted methods section, to be written after the plan
    bundle: CandidateBundle | None  # None when nothing changes
    report: dict[str, Any]  # codes and counts only
    review_items: tuple[ReviewItem, ...]  # conflicts and product-information lint items


@dataclass
class _Run:
    """What one run reads and what its methods add to the one bundle."""

    registry: ProductRegistry
    active: Release | None
    port: CompletionPort
    cards: MethodCards
    policy: ReviewPolicy
    taxonomy: SalesTaxonomy
    cache: MaterialCache
    claims: list[Claim] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    removals: list[str] = field(default_factory=list)
    reviews: list[ReviewItem] = field(default_factory=list)


def compile_methods(
    registry: ProductRegistry,
    candidates: CandidateFile,
    *,
    pages: PageReader,
    port: CompletionPort,
    active: Release | None,
    cards: MethodCards | None = None,
    policy: ReviewPolicy | None = None,
    taxonomy: SalesTaxonomy | None = None,
) -> MethodRun:
    """Admit the candidates and compile every method of a v2 registry against `active`."""
    updated, admission = admitted_registry(registry, candidates)
    run = _Run(
        registry=updated,
        active=active,
        port=port,
        cards=cards or load_method_cards(),
        policy=policy or load_review_policy(),
        taxonomy=taxonomy or load_sales_taxonomy(),
        cache=MaterialCache(pages, updated.space_id, updated.method_uses),
    )
    reports = [_method(run, method) for method in updated.methods]
    bundle = None
    if run.claims or run.entities or run.removals:
        # Readers know methods only from their profile (SK-3 §1): it goes with the first method
        # members and whenever the cards change it; a removal-only candidate needs none.
        profile = method_profile(run.cards)
        carried = (run.claims or run.entities) and profile_needed(profile, active)
        bundle = assemble(
            run.claims,
            compiler_identity=f"{COMPILER}@{compiler_version(run.cards)}",
            base=active.head if active else None,
            entities=run.entities,
            profiles=[profile] if carried else [],
            review_plan=[ReviewPlan(mode=ReviewMode.HUMAN, policy_ref=None)],
            removals=sorted(run.removals),
        )
    report = {
        "candidates": _admission_report(admission),
        "methods": reports,
        "members": len(bundle.members) if bundle else 0,
        "removals": len(bundle.removals) if bundle else 0,
        "no_changes": bundle is None,
    }
    return MethodRun(updated, bundle, report, tuple(run.reviews))


def admitted_registry(
    registry: ProductRegistry, candidates: CandidateFile
) -> tuple[ProductRegistry, Admission]:
    """The v2 registry with the candidates admitted into its methods section, validated again
    as a whole; the value stage (values.py) admits the same way, so both make the same requests."""
    if registry.contract != V2:
        raise RegistryError("REGISTRY_NOT_V2")
    admission = admit(registry.methods, registry.method_uses, candidates)
    admitted = registry.model_copy(update={"methods": list(admission.methods)})
    return ProductRegistry.model_validate_json(admitted.model_dump_json()), admission


def method_request(
    method: MethodEntry,
    links: Sequence[MethodLink],
    cache: MaterialCache,
    cards: MethodCards,
    taxonomy: SalesTaxonomy,
) -> tuple[MethodParagraphs, tuple[Term, ...], JudgeLikeRequest]:
    """A method's paragraphs, the labels on offer and its value request (Spec §4.1–§4.2)."""
    paragraphs = MethodParagraphs(links, cache)
    labels = offered_labels(taxonomy)
    request = build_method_request(
        method.names[0], cards, labels, paragraphs.listing(), paragraphs.materials()
    )
    return paragraphs, labels, request


def _admission_report(admission: Admission) -> dict[str, Any]:
    return {
        "dropped": admission.dropped,
        "created": len(admission.created),
        "merged": len(admission.merged),
        "possible_duplicates": [list(pair) for pair in admission.duplicates],
    }


def _method(run: _Run, method: MethodEntry) -> dict[str, Any]:
    entry: dict[str, Any] = {"method_id": method.method_id, "status": "skipped", "code": None}
    links = valid_links(method, run.registry.method_uses)
    if method.suppressed or not links:
        removals = published_members(run.active, method.method_id)
        run.removals.extend(removals)
        return {**entry, "status": "retired", "removals": len(removals)}
    try:
        paragraphs, labels, request = method_request(
            method, links, run.cache, run.cards, run.taxonomy
        )
        raw = run.port.complete(system=request.system, user=request.user)
        response = parse_method_response(raw, run.cards)
    except ResponseMissing:
        return {**entry, "code": "RESPONSE_MISSING"}
    except (MethodResponseError, ParagraphsError, SourcePagesError) as error:
        return {**entry, "code": error.code}
    names = sorted({name for product in run.registry.products.values() for name in product.names})
    content = method_content(
        method.method_id,
        response,
        paragraphs,
        run.cards,
        {term.label for term in labels},
        names,
        run.port.model,
    )
    changes = decide_changes(
        run.active, method.method_id, content.claims, {link.knowledge_id for link in links}
    )
    # The notice and the routing follow what Active shows once this delta is activated: a kept or
    # conflicting old Claim stays published, and so does its product information (#516 R1).
    signals = claim_signals(_in_force(run.active, method.method_id, changes), run.cards, names)
    records = {use.triple: use for use in run.registry.method_uses}
    categories = {label for link in links for label in records[link.triple].categories}
    entity = method_entity(method, categories, content.labels, bool(signals), run.cards)
    review = _route(run, changes.members, bool(signals))
    run.claims.extend(labelled(changes.members, review, None))
    run.removals.extend(changes.removals)
    if _changed(run.active, entity):
        run.entities.append(entity)
    run.reviews.extend(changes.review_items)
    run.reviews.extend(
        _lint(claim, signals[claim.logical_key])
        for claim in changes.members
        if claim.logical_key in signals
    )
    counts = Counter(item.verdict.value for item in changes.items)
    return {
        **entry,
        "status": "compiled",
        "predicates": {claim.predicate: claim.state.value for claim in content.claims},
        "dropped": content.dropped,
        "labels": len(content.labels),
        "product_info": bool(signals),
        "counts": {verdict.value: counts[verdict.value] for verdict in Verdict},
        "conflicts": [i.logical_key for i in changes.items if i.verdict == Verdict.CONFLICT],
        "reasons": list(review.reasons),
        "removals": len(changes.removals),
    }


def _route(run: _Run, claims: Sequence[Claim], product_info: bool) -> Route:
    """People decide: the pack is not admitted (SK-0 §5.2 (5)), and a method showing product
    information never goes live unattended, whatever a future admission says (§4.5)."""
    pack = run.cards.review_pack
    routed = route(
        claims,
        admitted=run.policy.admitted(pack),
        threshold=lambda predicate: run.policy.threshold(pack, predicate),
        scores=None,  # SK-2a has no independent review; machine review needs one
        policy_ref=run.policy.policy_ref,
    )
    reasons = {*routed.reasons, *([PRODUCT_INFO] if product_info else [])}
    return Route(mode=ReviewMode.HUMAN, policy_ref=None, reasons=tuple(sorted(reasons)))


def _in_force(active: Release | None, method_id: str, changes: ChangeSet) -> list[Claim]:
    """The method's Claims once the delta is activated: Active's, replaced by the members,
    without the removals (decide_changes has already validated every Active payload)."""
    claims = {
        member.logical_slug: Claim.model_validate(member.payload)
        for member in (active.members if active else [])
        if member.kind == "claim"
        and isinstance(member.payload, dict)
        and member.payload.get("subject_ref") == method_id
    }
    claims.update({claim.logical_key: claim for claim in changes.members})
    for slug in changes.removals:
        claims.pop(slug, None)
    return list(claims.values())


def published_members(active: Release | None, method_id: str) -> list[str]:
    """The slugs of every published Claim of a method (unknown ones too: they cite no source, so no
    change decision would retract them) and of its entity: what leaves when it retires."""
    slugs = retired_claims(active, method_id, keep=())
    entity = f"entity/{method_id}"
    if active is not None and any(m.logical_slug == entity for m in active.members):
        slugs.append(entity)
    return slugs


def _changed(active: Release | None, entity: Entity) -> bool:
    slug = f"entity/{entity.entity_id}"
    members = active.members if active else []
    published = next((m.payload for m in members if m.logical_slug == slug), None)
    return published != entity.model_dump(mode="json")


def _lint(claim: Claim, signals: Collection[str]) -> ReviewItem:
    """A lint item asking people to look at a Claim showing product information (§4.5)."""
    hashes = sorted({item.quote_sha256.lower() for item in claim.evidence})
    identity = json.dumps([claim.logical_key, sorted(signals), hashes], separators=(",", ":"))
    return ReviewItem(
        item_id="lint-" + hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        kind=ReviewKind.LINT,
        target=claim.logical_key,
        evidence=hashes,
        status=ReviewStatus.OPEN,
    )
