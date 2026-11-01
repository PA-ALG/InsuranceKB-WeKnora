"""First publish of a product's schema fields (S4g, S8a).

Products already having Claims in Active must use
insurance_harness.compilers.schema_fields.publish_changes.

usage: python -m insurance_harness.compilers.schema_fields.publish --run-root <dir> --product <id>
       (--source-map <file> | --registry <file>) [--decide human --reason <text> [--activate]
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

import json
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from insurance_harness.bundle.assemble import BundleError
from insurance_harness.bundle.client import (
    DecisionInput,
    PlatformClient,
    PlatformError,
    Release,
    publish,
)
from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.catalog.navigation import NavigationError, load_navigation
from insurance_harness.catalog.spot_check import (
    SpotCheckPolicy,
    SpotCheckPolicyError,
    load_spot_check_policy,
)
from insurance_harness.changes.options import (
    PublishParser,
    decision_input,
    registry_inputs,
    review_claims,
    review_inputs,
    source_options,
)
from insurance_harness.changes.options import ScoresFile as _ScoresFile  # noqa: F401
from insurance_harness.changes.sources import publication_entries
from insurance_harness.compilers.schema_fields.claims import (
    candidate_bundle,
    claims_from,
    require_cards_version,
)
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.compilers.schema_fields.page import product_page
from insurance_harness.contracts.enums import ReviewMode
from insurance_harness.eval.product_sources import check_product_id, display_name, source_directory
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.weknora_pages import SourcePagesError
from insurance_harness.ingest.registry import RegistryError
from insurance_harness.ingest.source_map import (
    API_KEY_ENV,
    BASE_URL_ENV,
    SourceMapError,
    load_source_map,
    load_trusted_pages,
    reader_from_env,
)
from insurance_harness.ingest.version_metadata import registry_metadata
from insurance_harness.review.spot_check import sample

# Existing review-artifact readers use this same score-file type.
__all__ = ["main", "_ScoresFile"]

REPO = Path(__file__).resolve().parents[5]


def main(argv: list[str] | None = None) -> int:
    parser = PublishParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--product", required=True)
    source_options(parser, required=True)
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
        decision = decision_input(args.decide, args.reason)
        policy, scores = review_inputs(args, decision)
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
    registry_map, registered, metadata = None, None, None
    if args.registry:
        try:
            registry_map, facts = registry_inputs(args.registry, [args.product])
            registered = facts[args.product]
            metadata = registry_metadata(args.registry, args.product)
        except RegistryError as error:
            return _stop(error.code)
        if output.pack_id != registered[1]:
            return _stop("OUTPUT_MISMATCH")
    try:
        # Written before outputs recorded their card version (or blank): publishing it under
        # today's cards would misstate how it was compiled. Same rule as candidate_bundle.
        version = require_cards_version(output)
    except BundleError as error:
        return _stop(error.reason)
    # The page is local data: read it before anything is sent, with the compile's own rule.
    try:
        name = (registered[0] if registered else
                display_name(source_directory(args.repo, args.product)))
    except (OSError, ValueError):
        return _stop("PRODUCT_META_MISSING")
    try:
        page = product_page(
            args.repo / SCHEMA_PACK_CATALOG,
            output.pack_id,
            entity_id=output.entity_id,
            name=name,
            metadata=metadata,
        )
    except BundleError as error:
        return _stop("BUNDLE_INVALID", reason=error.reason)
    try:
        navigation = load_navigation()  # local data too
    except NavigationError as error:
        return _stop(error.code)
    try:
        source_map = registry_map if registry_map is not None else load_source_map(args.source_map)
        reader = reader_from_env()
        client = PlatformClient(os.environ[BASE_URL_ENV], os.environ[API_KEY_ENV])
        active = client.active(source_map.space_id)
        if active is not None and any(
            member.kind == "claim"
            and isinstance(member.payload, dict)
            and member.payload.get("subject_ref") == args.product
            for member in active.members
        ):
            return _stop("ALREADY_PUBLISHED")
        pages, sources = load_trusted_pages(
            reader, source_map.space_id,
            publication_entries(source_map.entries(args.product), output.materials),
        )
        segmented = SegmentedSource(pages.evidence, table_headers=pages.table_headers)
        review = review_claims(
            policy, output.pack_id, claims_from(output, segmented, sources), scores
        )
        activate = args.activate
        if review.mode == ReviewMode.MACHINE:
            decision = DecisionInput(
                outcome="approve", mode="machine", policy_ref=review.policy_ref
            )
            activate = True
        bundle = candidate_bundle(
            output,
            segmented,
            sources,
            compiler_identity=f"harness/schema_fields@{version}",
            base=active.head if active else None,
            page=page,
            review=(review, scores),
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


if __name__ == "__main__":
    sys.exit(main())
