"""RV1 acceptance: one publish goes live as machine review only when every claim passes (Spec §3.2).

Protected file: written by Claude. A pack not yet quality-admitted, missing scores, a claim without
a score or threshold, a score below its threshold, or nothing to review sends the whole product to
the human queue with every applicable reason code. Labels record who reviewed and never rewrite the
input claims.

Updated by RV2a (Spec §3.4, §4; user ruling 2026-10-17): unknown claims publish no fact, so they are
neither scored nor blocking. The cases use evidence-bearing present/absent_explicitly claims, and
three cases pin unknown: it needs no score or threshold, a publish of only unknown claims has
nothing to review, and under machine review it is labelled machine without a score.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from insurance_harness.contracts import Claim
from insurance_harness.contracts.enums import (
    ClaimState,
    LocatorKind,
    ReviewMode,
    SourceClass,
    UnknownReason,
)
from insurance_harness.contracts.knowledge import Evidence, Locator
from insurance_harness.review.routing import HUMAN_DECISION, Route, Scores, labelled, route

REVIEWER = "deepseek-flash@review-v1"
AT = "2026-10-17T12:00:00Z"


EVIDENCE = Evidence(
    source_ref="source:v1:k-1:2:" + "ab" * 32,
    file_sha256="ab" * 32,
    locator=Locator(kind=LocatorKind.PDF_TEXT_SPAN, page=1, start=0, end=6),
    quote="本合同所述内容",
    access_scope="space",
)


def claim(predicate: str, state: ClaimState = ClaimState.PRESENT) -> Claim:
    key = f"P1/{predicate}"
    known = state != ClaimState.UNKNOWN
    return Claim(
        claim_id=key,
        logical_key=key,
        subject_ref="P1",
        predicate=predicate,
        state=state,
        value="90日" if state == ClaimState.PRESENT else None,
        evidence=[EVIDENCE] if known else [],
        origin=SourceClass.SOURCE_SUPPORTED,
        unknown_reason=None if known else UnknownReason.NOT_IN_MATERIAL,
    )


CLAIMS = [claim("term_a"), claim("term_b", ClaimState.ABSENT_EXPLICITLY)]
UNKNOWN = claim("term_c", ClaimState.UNKNOWN)
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


# --- unknown claims (RV2a Spec §3.4; user ruling 2026-10-17) -------------------------------


def test_unknown_claims_need_no_score_or_threshold() -> None:
    result = route(
        [*CLAIMS, UNKNOWN],
        admitted=True,
        threshold=limits(term_a=0.9, term_b=0.9),  # none for term_c
        scores=SCORES,  # no score for term_c
        policy_ref="review-policy@3",
    )
    assert result == Route(mode=ReviewMode.MACHINE, policy_ref="review-policy@3", reasons=())


def test_a_publish_of_only_unknown_claims_has_nothing_to_review() -> None:
    result = route(
        [UNKNOWN, claim("term_d", ClaimState.UNKNOWN)],
        admitted=True,
        threshold=limits(term_c=0.9, term_d=0.9),
        scores=SCORES,
        policy_ref="review-policy@3",
    )
    assert result == Route(mode=ReviewMode.HUMAN, policy_ref=None, reasons=("NO_CLAIMS",))


def test_unknown_claims_under_machine_review_are_labelled_without_a_score() -> None:
    out = labelled([*CLAIMS, UNKNOWN], Route(ReviewMode.MACHINE, "review-policy@3", ()), SCORES)
    assert [c.review.model_dump(mode="json") for c in out] == [
        {"mode": "machine", "score": 0.97, "reviewer": REVIEWER, "reviewed_at": AT},
        {"mode": "machine", "score": 0.91, "reviewer": REVIEWER, "reviewed_at": AT},
        {"mode": "machine", "score": None, "reviewer": REVIEWER, "reviewed_at": AT},
    ]
