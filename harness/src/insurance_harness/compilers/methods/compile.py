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
from insurance_harness.changes.types import Verdict
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
from insurance_harness.compilers.methods.review import (
    PRODUCT_INFO,
    MethodReviewError,
    ReviewSelection,
    claim_route,
    reviewed_claim,
    selected,
)
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
    selection: ReviewSelection
    claims: list[Claim] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    removals: list[str] = field(default_factory=list)
    reviews: list[ReviewItem] = field(default_factory=list)
    manual_metadata: bool = False


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
    review_route: ReviewSelection = "all",
) -> MethodRun:
    """Admit the candidates and compile every method of a v2 registry against `active`."""
    if review_route not in {"all", "machine", "human"}:
        raise MethodReviewError("REVIEW_SELECTION_INVALID")
    updated, admission = admitted_registry(registry, candidates)
    run = _Run(
        registry=updated,
        active=active,
        port=port,
        cards=cards or load_method_cards(),
        policy=policy or load_review_policy(),
        taxonomy=taxonomy or load_sales_taxonomy(),
        cache=MaterialCache(pages, updated.space_id, updated.method_uses),
        selection=review_route,
    )
    reports = [_method(run, method) for method in updated.methods]
    bundle = None
    if run.claims or run.entities or run.removals:
        # Readers know methods only from their profile (SK-3 §1): it goes with the first method
        # members and whenever the cards change it; a removal-only candidate needs none.
        profile = method_profile(run.cards)
        carried = (run.claims or run.entities) and profile_needed(profile, active)
        human = (
            run.manual_metadata
            or bool(run.removals)
            or any(claim.review.mode == ReviewMode.HUMAN for claim in run.claims)
        )
        bundle = assemble(
            run.claims,
            compiler_identity=f"{COMPILER}@{compiler_version(run.cards)}",
            base=active.head if active else None,
            entities=run.entities,
            profiles=[profile] if carried else [],
            review_plan=[
                ReviewPlan(
                    mode=ReviewMode.HUMAN if human else ReviewMode.MACHINE,
                    policy_ref=None if human else run.policy.policy_ref,
                )
            ],
            removals=sorted(run.removals),
        )
    report = {
        "candidates": _admission_report(admission),
        "methods": reports,
        "members": len(bundle.members) if bundle else 0,
        "removals": len(bundle.removals) if bundle else 0,
        "no_changes": bundle is None,
        "review_route": review_route,
        "policy_ref": run.policy.policy_ref,
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
        retired = published_members(run.active, method.method_id)
        if run.selection != "machine":
            run.removals.extend(retired)
        return {
            **entry,
            "status": "retired",
            "removals": len(retired) if run.selection != "machine" else 0,
        }
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
    # First route the planned in-force set (including KEEP/CONFLICT old facts), then project only
    # selected changes. A human fact excluded from the machine phase must not enter its entity.
    proposed = _in_force(run.active, method.method_id, changes.members, changes.removals)
    proposed_signals = claim_signals(proposed, run.cards, names)
    verdicts = {item.logical_key: item.verdict for item in changes.items}
    routes = {
        claim.logical_key: claim_route(
            claim,
            cards=run.cards,
            policy=run.policy,
            links=links,
            verdict=verdicts[claim.logical_key],
            signals=proposed_signals.get(claim.logical_key, ()),
        )
        for claim in proposed
    }
    members = [
        reviewed_claim(claim, routes[claim.logical_key])
        for claim in changes.members
        if selected(routes[claim.logical_key], run.selection)
    ]
    removals = changes.removals if run.selection != "machine" else ()
    effective = _in_force(run.active, method.method_id, members, removals)
    signals = claim_signals(effective, run.cards, names)
    records = {use.triple: use for use in run.registry.method_uses}
    categories = {label for link in links for label in records[link.triple].categories}
    entity = method_entity(method, categories, content.labels, bool(signals), run.cards)
    run.claims.extend(members)
    run.removals.extend(removals)
    metadata_only = not changes.members and not changes.removals and run.selection != "machine"
    if (members or removals or metadata_only) and _changed(run.active, entity):
        run.entities.append(entity)
        run.manual_metadata |= metadata_only
    if run.selection != "machine":
        run.reviews.extend(changes.review_items)
    run.reviews.extend(
        _lint(claim, signals[claim.logical_key])
        for claim in members
        if claim.logical_key in signals
    )
    counts = Counter(item.verdict.value for item in changes.items)
    reasons = {reason for route in routes.values() for reason in route.reasons}
    if signals:
        reasons.add(PRODUCT_INFO)
    return {
        **entry,
        "status": "compiled",
        "predicates": {claim.predicate: claim.state.value for claim in content.claims},
        "dropped": content.dropped,
        "labels": len(content.labels),
        "product_info": bool(signals),
        "counts": {verdict.value: counts[verdict.value] for verdict in Verdict},
        "conflicts": [i.logical_key for i in changes.items if i.verdict == Verdict.CONFLICT],
        "reasons": sorted(reasons),
        "removals": len(removals),
        "proposed_points": [
            {
                "logical_key": claim.logical_key,
                "mode": routes[claim.logical_key].mode.value,
                "reasons": list(routes[claim.logical_key].reasons),
                "signals": sorted(proposed_signals.get(claim.logical_key, ())),
                "selected": any(m.logical_key == claim.logical_key for m in members),
            }
            for claim in proposed
        ],
        "effective_points": [
            {
                "logical_key": claim.logical_key,
                "state": claim.state.value,
                "signals": sorted(signals.get(claim.logical_key, ())),
            }
            for claim in effective
        ],
        "effective_counts": {
            **dict(Counter(c.state.value for c in effective)),
            "product_info": len(signals),
        },
    }


def _in_force(
    active: Release | None, method_id: str, members: Sequence[Claim], removals: Sequence[str]
) -> list[Claim]:
    """The method's Claims once the delta is activated: Active's, replaced by the members,
    without the removals (decide_changes has already validated every Active payload)."""
    claims = {
        member.logical_slug: Claim.model_validate(member.payload)
        for member in (active.members if active else [])
        if member.kind == "claim"
        and isinstance(member.payload, dict)
        and member.payload.get("subject_ref") == method_id
    }
    claims.update({claim.logical_key: claim for claim in members})
    for slug in removals:
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
