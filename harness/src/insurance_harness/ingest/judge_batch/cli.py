"""Command line of the model-judge batch (RV7 Spec §1).

    python -m insurance_harness.ingest.judge_batch prepare --registry R --compile-root C \\
        --run-root J --policy-ref P --reviewer NAME --model M [--products …]
    python -m insurance_harness.ingest.judge_batch ingest --run-root J
    python -m insurance_harness.ingest.judge_batch publish --registry R --compile-root C \\
        --run-root J --issue N [--live] [--products …]
    python -m insurance_harness.ingest.judge_batch close --run-root J --product P \\
        --candidate ID --candidate-bundle FILE --issue N [--live]

Platform reads use HARNESS_WEKNORA_BASE_URL / HARNESS_WEKNORA_API_KEY. Failures print a stable code
only, never paths or input text.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from insurance_harness.bundle.client import PlatformClient, PlatformError
from insurance_harness.compilers.schema_fields.publish import REPO
from insurance_harness.evidence.weknora_pages import SourcePagesError
from insurance_harness.ingest.judge_batch.closing import close_points
from insurance_harness.ingest.judge_batch.points import JudgeBatchError
from insurance_harness.ingest.judge_batch.publishing import publish_batch
from insurance_harness.ingest.judge_batch.sessions import prepare
from insurance_harness.ingest.judge_batch.verdicts import ingest
from insurance_harness.ingest.registry import RegistryError
from insurance_harness.ingest.source_map import (
    API_KEY_ENV,
    BASE_URL_ENV,
    SourceMapError,
    reader_from_env,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    first = commands.add_parser("prepare")
    for sub in (first, commands.add_parser("publish")):
        sub.add_argument("--registry", type=Path, required=True)
        sub.add_argument("--compile-root", type=Path, required=True)
        sub.add_argument("--run-root", type=Path, required=True)
        sub.add_argument("--products", nargs="+")
        sub.add_argument("--repo", type=Path, default=REPO)
    first.add_argument("--policy-ref", required=True)
    first.add_argument("--reviewer", required=True)
    first.add_argument("--model", required=True)
    first.add_argument("--points-per-session", type=int, default=40)
    first.add_argument("--points-per-request", type=int, default=12)
    commands.add_parser("ingest").add_argument("--run-root", type=Path, required=True)
    publish = commands.choices["publish"]
    publish.add_argument("--issue", type=int, required=True)
    publish.add_argument("--spot-check-policy", type=Path)
    publish.add_argument("--live", action="store_true")
    close = commands.add_parser("close")
    close.add_argument("--run-root", type=Path, required=True)
    close.add_argument("--product", required=True)
    close.add_argument("--candidate", required=True)
    close.add_argument("--candidate-bundle", type=Path, required=True)
    close.add_argument("--issue", type=int, required=True)
    close.add_argument("--live", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "ingest":
            return _emit(ingest(args.run_root))
        base_url, api_key = os.environ.get(BASE_URL_ENV, ""), os.environ.get(API_KEY_ENV, "")
        if not base_url or not api_key:
            print("CONFIGURATION_MISSING", file=sys.stderr)
            return 2
        client = PlatformClient(base_url, api_key)
        if args.command == "close":
            return _emit(
                close_points(
                    args.run_root,
                    client=client,
                    product=args.product,
                    candidate=args.candidate,
                    candidate_bundle=args.candidate_bundle,
                    issue=args.issue,
                    live=args.live,
                )
            )
        reader = reader_from_env()
        if args.command == "prepare":
            return _emit(
                prepare(
                    args.run_root,
                    registry=args.registry,
                    compile_root=args.compile_root,
                    products=args.products
                    or sorted(path.parent.name for path in args.compile_root.glob("*/output.json")),
                    reader=reader,
                    client=client,
                    policy_ref=args.policy_ref,
                    reviewer=args.reviewer,
                    model=args.model,
                    points_per_session=args.points_per_session,
                    points_per_request=args.points_per_request,
                    repo=args.repo,
                )
            )
        result = publish_batch(
            args.run_root,
            registry=args.registry,
            compile_root=args.compile_root,
            reader=reader,
            client=client,
            issue=args.issue,
            live=args.live,
            spot_check_policy=args.spot_check_policy,
            repo=args.repo,
            products=args.products,
        )
        _emit(result)
        return 1 if result["stopped"] else 0
    except (
        JudgeBatchError,
        PlatformError,
        RegistryError,
        SourceMapError,
        SourcePagesError,
    ) as error:
        print(error.code, file=sys.stderr)
        return 1


def _emit(data: object) -> int:
    print(json.dumps(data, ensure_ascii=False))
    return 0
