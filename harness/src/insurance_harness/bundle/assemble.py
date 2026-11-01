"""Claims and their product page as a candidate bundle (S4g Spec §2.2, S3d-2 Spec §3.3).

Generic over the content: each claim becomes one ``kind=claim`` member keyed by its logical key,
with the source references its evidence cites; each entity and presentation profile becomes one
member keyed by its id under ``entity/`` and ``presentation/``, citing nothing. Every member
carries the platform's member digest, and a slug names one member across all kinds. Built
through the contract model itself, so the structure satisfies
contracts/candidate_bundle.schema.json; the size limit is the platform's.
"""

import json
from collections.abc import Collection, Sequence
from typing import Any

from insurance_harness.bundle.canonical import member_digest
from insurance_harness.bundle.client import MAX_BUNDLE_BYTES, Head, Release
from insurance_harness.contracts.bundle import BundleMember, CandidateBundle, ReviewPlan
from insurance_harness.contracts.enums import Origin
from insurance_harness.contracts.knowledge import (
    Claim,
    ConceptSummary,
    Entity,
    PresentationProfile,
    WikiPage,
)
from insurance_harness.contracts.navigation import NavigationProfile

ACCESS_SCOPE = "space"


class BundleError(ValueError):
    """The bundle cannot be published as it stands.

    Carries a stable reason code and, when one field is at fault, its position in the compile
    output: never the field key or any other input text, which may be arbitrary.
    """

    def __init__(self, reason: str, field_index: int | None = None) -> None:
        self.reason, self.field_index = reason, field_index
        super().__init__(reason)


def assemble(
    claims: Sequence[Claim],
    *,
    compiler_identity: str,
    base: Head | None = None,
    entities: Sequence[Entity] = (),
    profiles: Sequence[PresentationProfile] = (),
    review_plan: Sequence[ReviewPlan] = (),
    removals: Sequence[str] = (),
    navigations: Sequence[NavigationProfile] = (),
    concepts: Sequence[ConceptSummary] = (),
    wiki_pages: Sequence[WikiPage] = (),
) -> CandidateBundle:
    """Entity, profile and claim members on the given Head (None before the first release).

    `removals` names base members the activation drops (S5a): a candidate is a delta, so a claim
    the new compile no longer yields stays unless it is removed explicitly. Concept summaries
    (S3e-3) become ``concept/<key>`` members; they cite claims, not sources.
    """
    members = [
        *(_member("entity", f"entity/{entity.entity_id}", entity) for entity in entities),
        *(
            _member("presentation_profile", f"presentation/{profile.profile_id}", profile)
            for profile in profiles
        ),
        *(
            _member("navigation", f"navigation/{navigation.navigation_id}", navigation)
            for navigation in navigations
        ),
        *(_member("concept", f"concept/{item.concept_key}", item) for item in concepts),
        *(
            _member(
                "wiki_page",
                f"wiki/{entity}/{page.page_key}",
                page,
                sorted({item.source_ref for item in page.evidence}),
            )
            for page in wiki_pages
            for entity in page.entity_refs
        ),
        *(
            _member(
                "claim",
                claim.logical_key,
                claim,
                sorted({item.source_ref for item in claim.evidence}),
            )
            for claim in claims
        ),
    ]
    slugs = [member.logical_slug for member in members]
    if len(set(slugs)) != len(slugs):
        raise BundleError("DUPLICATE_LOGICAL_KEY")
    removed = list(removals)
    if (
        any(not slug.strip() for slug in removed)
        or len(set(removed)) != len(removed)
        or set(removed) & set(slugs)
    ):
        raise BundleError("REMOVAL_OVERLAP")
    bundle = CandidateBundle(
        contract_version="1",
        base_release_id=base.release_id if base else None,
        base_epoch=base.epoch if base else None,
        origin=Origin.COMPILE,
        members=members,
        removals=removed,
        review_plan=list(review_plan),
        compiler_identity=compiler_identity,
    )
    raw = json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_BUNDLE_BYTES:
        raise BundleError("SIZE_LIMIT")
    return bundle


def _member(
    kind: str,
    slug: str,
    content: Entity | PresentationProfile | NavigationProfile | ConceptSummary | Claim | WikiPage,
    refs: list[str] | None = None,
) -> BundleMember:
    payload: dict[str, Any] = content.model_dump(mode="json")
    return BundleMember(
        kind=kind,
        logical_slug=slug,
        payload=payload,
        member_digest=member_digest(payload),
        evidence_refs=refs or [],
        access_scope=ACCESS_SCOPE,
    )


def retired_claims(active: Release | None, entity_id: str, keep: Collection[str]) -> list[str]:
    """This product's claims in the active release that the new compile no longer yields."""
    if active is None:
        return []
    return sorted(
        member.logical_slug
        for member in active.members
        if member.kind == "claim"
        and isinstance(member.payload, dict)
        and member.payload.get("subject_ref") == entity_id
        and member.logical_slug not in keep
    )
