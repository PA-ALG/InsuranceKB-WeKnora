"""Route one publish to machine review or the human queue, and label its claims (RV1 Spec §3.2).

One publish (one product with its claims) is the unit: it goes live as machine review only when its
pack is admitted and every claim with content (present or absent_explicitly) has an independent
score at or above its field's threshold; otherwise the whole product waits for people, with every
applicable reason code. Unknown claims publish no fact, so they are neither scored nor blocking
(RV2a Spec §3.4, user ruling 2026-10-17): a wrong unknown only costs recall, which sampling after
release covers. The exception is a compiler upgrade to unknown, which removes a published fact:
it always goes to people (S12c-1b). Splitting a product into machine and human parts needs the
platform to rebase activations (S5) and is not done here. Reason codes never carry field keys
or other input text.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from insurance_harness.changes.types import Verdict
from insurance_harness.contracts.enums import ClaimState, ReviewMode
from insurance_harness.contracts.knowledge import Claim, Review


@dataclass(frozen=True)
class Scores:
    """Independent review scores of one publish, keyed by claim logical key, in [0, 1]."""

    reviewer: str
    reviewed_at: str
    by_key: Mapping[str, float]


@dataclass(frozen=True)
class Route:
    mode: ReviewMode
    policy_ref: str | None
    reasons: tuple[str, ...]


# A person decided explicitly: no policy, nothing to explain.
HUMAN_DECISION = Route(mode=ReviewMode.HUMAN, policy_ref=None, reasons=())


def _upgrade(claim: Claim) -> bool:
    return claim.maintenance.reason == Verdict.UPGRADE.value


def _reviewed(claim: Claim) -> bool:
    """Claims with content are scored and gate machine review; so does a compiler upgrade, which
    may replace a published fact (S12c-1b). Other unknowns publish no fact (RV2a)."""
    return claim.state != ClaimState.UNKNOWN or _upgrade(claim)


def route(
    claims: Sequence[Claim],
    *,
    admitted: bool,
    threshold: Callable[[str], float | None],
    scores: Scores | None,
    policy_ref: str,
) -> Route:
    reviewed = [claim for claim in claims if _reviewed(claim)]
    reasons: set[str] = set()
    # Replacing a published fact with unknown removes it, and the reviewer only judges
    # present/absent values against quotes: people decide, whatever the scores (S12c-1b).
    if any(claim.state == ClaimState.UNKNOWN and _upgrade(claim) for claim in claims):
        reasons.add("UPGRADE_TO_UNKNOWN")
    if not reviewed:
        reasons.add("NO_CLAIMS")
    if not admitted:
        reasons.add("PACK_NOT_ADMITTED")
    if scores is None:
        reasons.add("SCORES_MISSING")
    for claim in reviewed:
        limit = threshold(claim.predicate)
        if limit is None:
            reasons.add("THRESHOLD_MISSING")
        if scores is None:
            continue
        score = scores.by_key.get(claim.logical_key)
        if score is None:
            reasons.add("SCORE_MISSING")
        elif limit is not None and score < limit:
            reasons.add("BELOW_THRESHOLD")
    if reasons:
        return Route(mode=ReviewMode.HUMAN, policy_ref=None, reasons=tuple(sorted(reasons)))
    return Route(mode=ReviewMode.MACHINE, policy_ref=policy_ref, reasons=())


def labelled(claims: Sequence[Claim], route: Route, scores: Scores | None) -> list[Claim]:
    """New claims whose review says who reviewed them; the input claims are not changed."""
    by_key = scores.by_key if scores is not None else {}
    if route.mode == ReviewMode.MACHINE:
        if scores is None or any(
            claim.logical_key not in by_key for claim in claims if _reviewed(claim)
        ):
            raise ValueError("machine review needs a score for every claim with content")
        # The same review released the ordinary unknown claims too; they carry no score.
        return [
            claim.model_copy(
                update={
                    "review": Review(
                        mode=ReviewMode.MACHINE,
                        score=by_key[claim.logical_key] if _reviewed(claim) else None,
                        reviewer=scores.reviewer,
                        reviewed_at=scores.reviewed_at,
                    )
                }
            )
            for claim in claims
        ]
    # People decide (now or from the queue); the decision record names who and when.
    return [
        claim.model_copy(
            update={"review": Review(mode=ReviewMode.HUMAN, score=by_key.get(claim.logical_key))}
        )
        for claim in claims
    ]
