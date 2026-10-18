"""Publish one product's schema-field compile output to the platform (S4g Spec §2.4).

usage: python -m insurance_harness.compilers.schema_fields.publish --run-root <dir> --product <id>
       --source-map <file> [--decide human --reason <text> [--activate]
       | --route [--review-policy <file>] [--scores <file>] [--spot-check-policy <file>]]
       [--repo <dir>]

Reads <run-root>/<product>/output.json and, from --repo (default: this checkout), the catalog and
the product's metadata for its page (S3d-2): an entity named by the filed clause name, with its
pack's presentation profile. Then re-reads the same page text from the WeKnora revisions the
source map names (HARNESS_WEKNORA_BASE_URL / HARNESS_WEKNORA_API_KEY), builds the candidate bundle
on the Space's active release and submits it. A person decides with --decide human (and may
--activate); --route applies the versioned review policy and independent scores instead (RV1):
an admitted, fully passing product goes live as machine review, anything else is only submitted
and waits in the human queue with reason codes. Claims are labelled with who reviewed them.
A machine publish then submits its spot-check sample (RV4): the claims it brought live, drawn by
the versioned spot-check policy against the active release it read before. A failed submission
never undoes the publish; it is reported as "samples": {"stopped": <code>} so the report command
can submit later.
Prints one JSON line; exit 2 means stopped, with a caller-safe code.
"""

import argparse
import json
import os
import sys
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

from insurance_harness.bundle.assemble import BundleError, retired_claims
from insurance_harness.bundle.client import (
    DecisionInput,
    PlatformClient,
    PlatformError,
    Release,
    publish,
)
from insurance_harness.catalog.navigation import NavigationError, load_navigation
from insurance_harness.catalog.review_policy import ReviewPolicy, load_review_policy
from insurance_harness.catalog.spot_check import (
    SpotCheckPolicy,
    SpotCheckPolicyError,
    load_spot_check_policy,
)
from insurance_harness.compilers.schema_fields.claims import (
    candidate_bundle,
    claims_from,
    require_cards_version,
)
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.compilers.schema_fields.page import product_page
from insurance_harness.compilers.schema_fields.review_items import logical_key
from insurance_harness.contracts.enums import ReviewMode
from insurance_harness.contracts.knowledge import Claim
from insurance_harness.eval.product_sources import check_product_id, display_name, source_directory
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.weknora_pages import SourcePagesError
from insurance_harness.ingest.source_map import (
    API_KEY_ENV,
    BASE_URL_ENV,
    SourceMapError,
    load_source_map,
    load_trusted_pages,
    reader_from_env,
)
from insurance_harness.review.routing import HUMAN_DECISION, Route, Scores, route
from insurance_harness.review.spot_check import sample

REPO = Path(__file__).resolve().parents[5]
CATALOG = "internal/handler/schema_pack_catalog_830_g3.generated.json"


class _Parser(argparse.ArgumentParser):
    """Malformed arguments become the stable INVALID_ARGUMENTS code, not usage text."""

    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


# Strict: a JSON boolean is not a score (true would silently become 1.0).
Score = Annotated[float, Field(strict=True, ge=0.0, le=1.0, allow_inf_nan=False)]
NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]


class _ScoresFile(BaseModel):
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


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--source-map", type=Path, required=True)
    parser.add_argument("--decide")
    parser.add_argument("--reason")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--route", action="store_true")
    parser.add_argument("--review-policy", type=Path)
    parser.add_argument("--scores", type=Path)
    parser.add_argument("--spot-check-policy", type=Path)
    parser.add_argument("--repo", type=Path, default=REPO)
    # Every failure prints a stable code (and at most a field key): never exception text,
    # local paths or input content, which may carry material.
    try:
        args = parser.parse_args(argv)
        check_product_id(args.product)
        decision = _decision(args.decide, args.reason)
        policy, scores = _routing(args, decision)
    except ValueError:
        return _stop("INVALID_ARGUMENTS")
    if args.activate and decision is None:
        return _stop("INVALID_REQUEST")  # activation needs an approving decision
    spot_check: SpotCheckPolicy | None = None
    if args.route:
        try:
            spot_check = load_spot_check_policy(args.spot_check_policy)
        except SpotCheckPolicyError as error:
            return _stop(error.code)
    try:
        output = CompileOutput.model_validate_json(
            (args.run_root / args.product / "output.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError, ValidationError):
        return _stop("OUTPUT_UNREADABLE")
    if output.entity_id != args.product:
        return _stop("OUTPUT_MISMATCH")
    try:
        # Written before outputs recorded their card version (or blank): publishing it under
        # today's cards would misstate how it was compiled. Same rule as candidate_bundle.
        version = require_cards_version(output)
    except BundleError as error:
        return _stop(error.reason)
    # The page is local data: read it before anything is sent, with the compile's own rule.
    try:
        name = display_name(source_directory(args.repo, args.product))
    except (OSError, ValueError):
        return _stop("PRODUCT_META_MISSING")
    try:
        page = product_page(
            args.repo / CATALOG, output.pack_id, entity_id=output.entity_id, name=name
        )
    except BundleError as error:
        return _stop("BUNDLE_INVALID", reason=error.reason)
    try:
        navigation = load_navigation()  # local data too
    except NavigationError as error:
        return _stop(error.code)
    try:
        source_map = load_source_map(args.source_map)
        pages, sources = load_trusted_pages(
            reader_from_env(), source_map.space_id, source_map.entries(args.product)
        )
        client = PlatformClient(os.environ[BASE_URL_ENV], os.environ[API_KEY_ENV])
        active = client.active(source_map.space_id)
        segmented = SegmentedSource(pages.evidence, table_headers=pages.table_headers)
        review = _route(policy, output.pack_id, claims_from(output, segmented, sources), scores)
        activate = args.activate
        if review.mode == ReviewMode.MACHINE:
            decision = DecisionInput(
                outcome="approve", mode="machine", policy_ref=review.policy_ref
            )
            activate = True
        # A candidate is a delta: claims of this product the new output no longer has are
        # removed explicitly, or the previous release's values would stay on the page (S5a).
        retired = retired_claims(
            active,
            output.entity_id,
            {logical_key(output.entity_id, f.field_key) for f in output.fields},
        )
        bundle = candidate_bundle(
            output,
            segmented,
            sources,
            compiler_identity=f"harness/schema_fields@{version}",
            base=active.head if active else None,
            page=page,
            review=(review, scores),
            removals=retired,
            navigation=navigation,
        )
        result = publish(client, source_map.space_id, bundle, decision=decision, activate=activate)
        samples: int | dict[str, str] | None = None
        if review.mode == ReviewMode.MACHINE and result.release and spot_check is not None:
            samples = _submit_sample(
                client, source_map.space_id, result.release, active, spot_check
            )
    except (PlatformError, SourcePagesError, SourceMapError) as error:
        return _stop(error.code)
    except BundleError as error:
        return _stop("BUNDLE_INVALID", reason=error.reason, field_index=error.field_index)
    except (ValidationError, ValueError):
        # Anything else the conversion rejects: still a code, never the exception text.
        return _stop("BUNDLE_INVALID", reason="CONVERSION_FAILED")
    print(
        json.dumps(
            {
                "product": args.product,
                "space_id": source_map.space_id,
                "cards_version": version,
                "members": len(bundle.members),
                "candidate_id": result.candidate.id,
                "candidate_status": result.candidate.status,
                "decision_id": result.decision.id if result.decision else None,
                "release_id": result.release.id if result.release else None,
                "epoch": result.release.epoch if result.release else None,
                "review": review.mode.value,
                **({"reasons": list(review.reasons)} if review.reasons else {}),
                **({"retired": len(retired)} if retired else {}),
                **({"samples": samples} if samples is not None else {}),
            },
            ensure_ascii=False,
        )
    )
    return 0


SAMPLES_PER_CALL = 500  # the platform's batch limit


def _submit_sample(
    client: PlatformClient,
    space_id: str,
    released: Release,
    base: Release | None,
    policy: SpotCheckPolicy,
) -> int | dict[str, str]:
    """Sample what this publish brought live and submit it; a failure is reported, not raised."""
    picks = [(pick.slug, pick.stratum) for pick in sample(released, base, policy)]
    submitted = 0
    try:
        for start in range(0, len(picks), SAMPLES_PER_CALL):
            batch = picks[start : start + SAMPLES_PER_CALL]
            submitted += len(client.submit_samples(space_id, released.id, batch))
    except PlatformError as error:
        return {"stopped": error.code}
    return submitted


def _stop(code: str, **detail: str | int | None) -> int:
    print(json.dumps({"stopped": code, **detail}, ensure_ascii=False))
    return 2


def _decision(mode: str | None, reason: str | None) -> DecisionInput | None:
    """Only a person decides explicitly; a machine decision comes from --route alone (RV1)."""
    if mode is None:
        if reason:
            raise ValueError("--reason needs --decide")
        return None
    if mode != "human" or not (reason and reason.strip()):
        raise ValueError("an explicit decision is a human one with a reason")
    return DecisionInput(outcome="approve", mode="human", reason=reason)


def _routing(
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
        document = _ScoresFile.model_validate_json(args.scores.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise ValueError("scores unreadable or malformed") from error
    return policy, Scores(document.reviewer, document.reviewed_at, dict(document.scores))


def _route(
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


if __name__ == "__main__":
    sys.exit(main())
