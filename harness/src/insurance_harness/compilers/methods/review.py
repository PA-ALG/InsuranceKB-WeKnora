"""SK-5's point admission: current policy, original support and no product-information signal.

This checks the structure/identity of evidence already cut from fixed RAW paragraphs by claims.py;
it neither guesses original text nor replaces the platform's publication verification. Selection
happens after change decisions; labels describe the candidate route, never an invented approval.
"""

from collections.abc import Collection, Sequence
from typing import Literal

from insurance_harness.bundle.assemble import ACCESS_SCOPE
from insurance_harness.catalog.method_cards import METHOD_ROLE, MethodCards, load_method_cards
from insurance_harness.catalog.review_policy import ReviewPolicy, load_review_policy
from insurance_harness.catalog.trust_policy import load_trust_policy
from insurance_harness.changes.types import Verdict
from insurance_harness.contracts.enums import (
    ClaimState,
    EvidenceMatch,
    LocatorKind,
    ReviewMode,
    SourceClass,
)
from insurance_harness.contracts.knowledge import Claim, Review, quote_digest
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.ingest.method_registry import MethodLink
from insurance_harness.review.routing import Route

ReviewSelection = Literal["all", "machine", "human"]
PRODUCT_INFO = "CONTAINS_PRODUCT_INFO"


class MethodReviewError(ValueError):
    """A review-selection refusal, distinct from a malformed candidate."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def claim_route(
    claim: Claim,
    *,
    cards: MethodCards,
    policy: ReviewPolicy,
    links: Sequence[MethodLink],
    verdict: Verdict,
    signals: Collection[str],
) -> Route:
    """Deterministic per-point eligibility; old/custom policies never silently gain admission."""
    reasons = set()
    if policy != load_review_policy() or cards != load_method_cards():
        reasons.add("ADMISSION_POLICY_MISMATCH")
    if (
        not policy.admitted(cards.review_pack)
        or cards.review_pack not in policy.source_supported_packs
    ):
        reasons.add("PACK_NOT_ADMITTED")
    if signals:
        reasons.add(PRODUCT_INFO)
    if claim.expert_lock or verdict in {Verdict.CONFLICT, Verdict.RETRACT}:
        reasons.add("MANUAL_CHANGE")
    if verdict == Verdict.UPGRADE and claim.state == ClaimState.UNKNOWN:
        reasons.add("UPGRADE_UNKNOWN")
    if not _supported(claim, links):
        reasons.add("SOURCE_SUPPORT_INVALID")
    return Route(
        mode=ReviewMode.HUMAN if reasons else ReviewMode.MACHINE,
        policy_ref=None if reasons else policy.policy_ref,
        reasons=tuple(sorted(reasons)),
    )


def _supported(claim: Claim, links: Sequence[MethodLink]) -> bool:
    if (
        claim.origin != SourceClass.SOURCE_SUPPORTED
        or claim.predicate not in load_trust_policy().restricted_fields(METHOD_ROLE)
    ):
        return False
    if claim.state == ClaimState.UNKNOWN:
        return claim.value is None and not claim.evidence and claim.unknown_reason is not None
    if claim.state != ClaimState.PRESENT or claim.unknown_reason is not None:
        return False
    values = claim.value if isinstance(claim.value, list) else [claim.value]
    if not values or any(not isinstance(value, str) or not value.strip() for value in values):
        return False
    if not claim.evidence or (isinstance(claim.value, list) and len(claim.evidence) != len(values)):
        return False
    sources = {
        SourceRevision(link.knowledge_id, link.parse_attempt).ref(link.sha256): link.sha256
        for link in links
    }
    return all(
        sources.get(e.source_ref) == e.file_sha256.lower()
        and e.quote_sha256.lower() == quote_digest({"quote": e.quote})
        and e.locator.kind != LocatorKind.EXPERT_REVISION
        and e.match == EvidenceMatch.EXACT
        and e.access_scope == ACCESS_SCOPE
        for e in claim.evidence
    )


def reviewed_claim(claim: Claim, route: Route) -> Claim:
    """No fake judge score/time: the eventual platform Decision supplies approval identity."""
    return claim.model_copy(update={"review": Review(mode=route.mode, reviewer=route.policy_ref)})


def selected(route: Route, selection: ReviewSelection) -> bool:
    return selection == "all" or route.mode.value == selection
