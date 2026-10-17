"""RV1 acceptance: one publish goes live as machine review only when every claim passes (Spec §3.2).

Protected file: written by Claude. A pack not yet quality-admitted, missing scores, a claim without
a score or threshold, a score below its threshold, or nothing to review sends the whole product to
the human queue with every applicable reason code. Labels record who reviewed and never rewrite the
input claims.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from insurance_harness.contracts import Claim
from insurance_harness.contracts.enums import ClaimState, ReviewMode, SourceClass, UnknownReason
from insurance_harness.review.routing import HUMAN_DECISION, Route, Scores, labelled, route

REVIEWER = "deepseek-flash@review-v1"
AT = "2026-10-17T12:00:00Z"


def claim(predicate: str) -> Claim:
    key = f"P1/{predicate}"
    return Claim(
        claim_id=key,
        logical_key=key,
        subject_ref="P1",
        predicate=predicate,
        state=ClaimState.UNKNOWN,
        origin=SourceClass.SOURCE_SUPPORTED,
        unknown_reason=UnknownReason.NOT_IN_MATERIAL,
    )


CLAIMS = [claim("term_a"), claim("term_b")]
SCORES = Scores(reviewer=REVIEWER, reviewed_at=AT, by_key={"P1/term_a": 0.97, "P1/term_b": 0.91})


def limits(**by_field: float) -> Callable[[str], float | None]:
    return lambda predicate: by_field.get(predicate)


def test_every_claim_passing_in_an_admitted_pack_goes_live_as_machine_review() -> None:
    result = route(
        CLAIMS,
        admitted=True,
        threshold=limits(term_a=0.9, term_b=0.91),  # equal to the threshold passes
        scores=SCORES,
        policy_ref="review-policy@3",
    )
    assert result == Route(mode=ReviewMode.MACHINE, policy_ref="review-policy@3", reasons=())


PARTIAL = Scores(reviewer=REVIEWER, reviewed_at=AT, by_key={"P1/term_a": 0.97})
CASES: list[tuple[str, bool, Scores | None, dict[str, float], tuple[str, ...]]] = [
    ("pack not admitted", False, SCORES, {"term_a": 0.9, "term_b": 0.9}, ("PACK_NOT_ADMITTED",)),
    ("no scores", True, None, {"term_a": 0.9, "term_b": 0.9}, ("SCORES_MISSING",)),
    ("a claim unscored", True, PARTIAL, {"term_a": 0.9, "term_b": 0.9}, ("SCORE_MISSING",)),
    ("a field without threshold", True, SCORES, {"term_a": 0.9}, ("THRESHOLD_MISSING",)),
    (
        "a score below threshold",
        True,
        SCORES,
        {"term_a": 0.9, "term_b": 0.95},
        ("BELOW_THRESHOLD",),
    ),
    (
        "everything missing",
        False,
        None,
        {},
        ("PACK_NOT_ADMITTED", "SCORES_MISSING", "THRESHOLD_MISSING"),
    ),
]


@pytest.mark.parametrize(
    ("case", "admitted", "scores", "thresholds", "reasons"), CASES, ids=[c[0] for c in CASES]
)
def test_anything_short_of_that_sends_the_whole_product_to_people(
    case: str,
    admitted: bool,
    scores: Scores | None,
    thresholds: dict[str, float],
    reasons: tuple[str, ...],
) -> None:
    result = route(
        CLAIMS,
        admitted=admitted,
        threshold=limits(**thresholds),
        scores=scores,
        policy_ref="review-policy@3",
    )
    assert result == Route(mode=ReviewMode.HUMAN, policy_ref=None, reasons=reasons), case


def test_a_publish_without_claims_is_never_machine_reviewed() -> None:
    result = route(
        [], admitted=True, threshold=limits(), scores=SCORES, policy_ref="review-policy@3"
    )
    assert result == Route(mode=ReviewMode.HUMAN, policy_ref=None, reasons=("NO_CLAIMS",))


def test_machine_labels_carry_score_reviewer_and_time_without_touching_the_input() -> None:
    before = [c.model_dump(mode="json") for c in CLAIMS]
    out = labelled(CLAIMS, Route(ReviewMode.MACHINE, "review-policy@3", ()), SCORES)
    assert [c.review.model_dump(mode="json") for c in out] == [
        {"mode": "machine", "score": 0.97, "reviewer": REVIEWER, "reviewed_at": AT},
        {"mode": "machine", "score": 0.91, "reviewer": REVIEWER, "reviewed_at": AT},
    ]
    assert [c.model_dump(mode="json", exclude={"review"}) for c in out] == [
        {k: v for k, v in item.items() if k != "review"} for item in before
    ]
    assert [c.model_dump(mode="json") for c in CLAIMS] == before


def test_human_labels_name_no_reviewer_and_keep_known_scores() -> None:
    decided = labelled(CLAIMS, HUMAN_DECISION, None)
    assert [c.review.model_dump(mode="json") for c in decided] == [
        {"mode": "human", "score": None, "reviewer": None, "reviewed_at": None},
        {"mode": "human", "score": None, "reviewer": None, "reviewed_at": None},
    ]
    queued = labelled(CLAIMS, Route(ReviewMode.HUMAN, None, ("BELOW_THRESHOLD",)), PARTIAL)
    assert [(c.review.mode, c.review.score, c.review.reviewer) for c in queued] == [
        (ReviewMode.HUMAN, 0.97, None),
        (ReviewMode.HUMAN, None, None),
    ]


def test_a_machine_route_without_a_score_for_every_claim_is_refused() -> None:
    with pytest.raises(ValueError):
        labelled(CLAIMS, Route(ReviewMode.MACHINE, "review-policy@3", ()), PARTIAL)
    with pytest.raises(ValueError):
        labelled(CLAIMS, Route(ReviewMode.MACHINE, "review-policy@3", ()), None)
