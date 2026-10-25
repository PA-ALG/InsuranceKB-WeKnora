"""Argument validation and review routing shared by first and incremental publishing."""

import argparse
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
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
from insurance_harness.catalog.trust_policy import TrustedPages
from insurance_harness.contracts.knowledge import Claim
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.ingest.registry import load_registry
from insurance_harness.ingest.source_map import PageReader, SourceMap, load_trusted_pages
from insurance_harness.review.routing import HUMAN_DECISION, Route, Scores, route

Score = Annotated[float, Field(strict=True, ge=0.0, le=1.0, allow_inf_nan=False)]
NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]


class PublishParser(argparse.ArgumentParser):
    """Malformed arguments become the stable INVALID_ARGUMENTS code, not usage text."""

    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


def source_options(parser: argparse.ArgumentParser, *, required: bool) -> None:
    """Choose one fixed source authority; compilation also allows local dataset inputs."""
    sources = parser.add_mutually_exclusive_group(required=required)
    sources.add_argument("--source-map", type=Path, help="read the map's fixed WeKnora revisions")
    sources.add_argument("--registry", type=Path, help="read registered facts and fixed revisions")


def registry_inputs(
    path: Path, products: Sequence[str],
) -> tuple[SourceMap, dict[str, tuple[str, str]]]:
    """Snapshot selected facts and sources, rejecting unknown products before remote reads."""
    registry = load_registry(path)
    facts = {product: registry.facts(product) for product in products}
    return registry.source_map(), {
        product: (fact.name, fact.schema_pack_id) for product, fact in facts.items()
    }


def fixed_revision_pages(
    source_map: SourceMap, reader: PageReader,
) -> Callable[[str], tuple[TrustedPages[PageText], dict[str, SourceRevision]]]:
    """Read pages and their revision labels in the same canonical order as compilation."""
    def read(product: str) -> tuple[TrustedPages[PageText], dict[str, SourceRevision]]:
        entries = sorted(source_map.entries(product),
                         key=lambda entry: (entry.knowledge_id, entry.parse_attempt))
        return load_trusted_pages(reader, source_map.space_id, entries)

    return read


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
