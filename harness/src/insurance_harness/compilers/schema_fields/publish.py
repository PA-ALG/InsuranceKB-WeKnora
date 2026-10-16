"""Publish one product's schema-field compile output to the platform (S4g Spec §2.4).

usage: python -m insurance_harness.compilers.schema_fields.publish --run-root <dir> --product <id>
       --source-map <file> [--decide human --reason <text> | --decide machine --policy-ref <id>]
       [--activate]

Reads <run-root>/<product>/output.json, re-reads the same page text from the WeKnora revisions the
source map names (HARNESS_WEKNORA_BASE_URL / HARNESS_WEKNORA_API_KEY), builds the candidate bundle
on the Space's active release and submits it. A decision is recorded only when given explicitly,
and activation needs an approving one: nothing is approved automatically. Prints one JSON line;
exit 2 means stopped, with a caller-safe code.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from insurance_harness.bundle.assemble import BundleError
from insurance_harness.bundle.client import DecisionInput, PlatformClient, PlatformError, publish
from insurance_harness.compilers.schema_fields.claims import candidate_bundle, require_cards_version
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.eval.product_sources import check_product_id
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.weknora_pages import SourcePagesError
from insurance_harness.ingest.source_map import (
    API_KEY_ENV,
    BASE_URL_ENV,
    SourceMapError,
    load_pages,
    load_source_map,
    reader_from_env,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--source-map", type=Path, required=True)
    parser.add_argument("--decide", choices=("human", "machine"))
    parser.add_argument("--reason")
    parser.add_argument("--policy-ref")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args(argv)
    # Every failure prints a stable code (and at most a field key): never exception text,
    # local paths or input content, which may carry material.
    try:
        check_product_id(args.product)
        decision = _decision(args.decide, args.reason, args.policy_ref)
    except ValueError:
        return _stop("INVALID_ARGUMENTS")
    if args.activate and decision is None:
        return _stop("INVALID_REQUEST")  # activation needs an approving decision
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
    try:
        source_map = load_source_map(args.source_map)
        pages, sources = load_pages(
            reader_from_env(), source_map.space_id, source_map.entries(args.product)
        )
        client = PlatformClient(os.environ[BASE_URL_ENV], os.environ[API_KEY_ENV])
        active = client.active(source_map.space_id)
        bundle = candidate_bundle(
            output,
            SegmentedSource(pages),
            sources,
            compiler_identity=f"harness/schema_fields@{version}",
            base=active.head if active else None,
        )
        result = publish(
            client, source_map.space_id, bundle, decision=decision, activate=args.activate
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
            },
            ensure_ascii=False,
        )
    )
    return 0


def _stop(code: str, **detail: str | int | None) -> int:
    print(json.dumps({"stopped": code, **detail}, ensure_ascii=False))
    return 2


def _decision(mode: str | None, reason: str | None, policy_ref: str | None) -> DecisionInput | None:
    if mode is None:
        if reason or policy_ref:
            raise ValueError("--reason and --policy-ref need --decide")
        return None
    if mode == "human" and not (reason and reason.strip()):
        raise ValueError("a human decision needs --reason")
    if mode == "machine" and not (policy_ref and policy_ref.strip()):
        raise ValueError("a machine decision needs --policy-ref")
    reviewer: Literal["human", "machine"] = "human" if mode == "human" else "machine"
    return DecisionInput(outcome="approve", mode=reviewer, policy_ref=policy_ref, reason=reason)


if __name__ == "__main__":
    sys.exit(main())
