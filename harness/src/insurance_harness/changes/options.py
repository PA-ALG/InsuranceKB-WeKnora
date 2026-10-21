"""Argument validation and review routing shared by first and incremental publishing."""

import argparse
from datetime import datetime
from typing import Annotated, NoReturn

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from insurance_harness.bundle.client import DecisionInput
from insurance_harness.catalog.review_policy import ReviewPolicy, load_review_policy
from insurance_harness.contracts.knowledge import Claim
from insurance_harness.review.routing import HUMAN_DECISION, Route, Scores, route

Score = Annotated[float, Field(strict=True, ge=0.0, le=1.0, allow_inf_nan=False)]
NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]


class PublishParser(argparse.ArgumentParser):
    """Malformed arguments become the stable INVALID_ARGUMENTS code, not usage text."""

    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


class ScoresFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reviewer: NonBlank
    reviewed_at: NonBlank
    scores: dict[NonBlank, Score]

    @field_validator("reviewed_at")
    @classmethod
    def iso_8601_with_offset(cls, value: str) -> str:
        # The label records when the review happened: a full date-time with its offset.
        if "T" not in value or datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("reviewed_at must be an ISO 8601 date-time with an offset")
        return value


def decision_input(mode: str | None, reason: str | None) -> DecisionInput | None:
    """Only a person decides explicitly; a machine decision comes from --route alone (RV1)."""
    if mode is None:
        if reason:
            raise ValueError("--reason needs --decide")
        return None
    if mode != "human" or not (reason and reason.strip()):
        raise ValueError("an explicit decision is a human one with a reason")
    return DecisionInput(outcome="approve", mode="human", reason=reason)


def review_inputs(
    args: argparse.Namespace, decision: DecisionInput | None
) -> tuple[ReviewPolicy | None, Scores | None]:
    """The policy and scores --route reads, before anything is sent."""
    if not args.route:
        if args.review_policy is not None or args.scores is not None:
            raise ValueError("--review-policy and --scores need --route")
        return None, None
    if decision is not None or args.activate:
        raise ValueError("--route decides and activates by itself")
    policy = load_review_policy(args.review_policy)
    if args.scores is None:
        return policy, None
    try:
        document = ScoresFile.model_validate_json(args.scores.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise ValueError("scores unreadable or malformed") from error
    return policy, Scores(document.reviewer, document.reviewed_at, dict(document.scores))


def review_claims(
    policy: ReviewPolicy | None, pack_id: str, claims: list[Claim], scores: Scores | None
) -> Route:
    if policy is None:
        return HUMAN_DECISION
    return route(
        claims,
        admitted=policy.admitted(pack_id),
        threshold=lambda predicate: policy.threshold(pack_id, predicate),
        scores=scores,
        policy_ref=policy.policy_ref,
    )
