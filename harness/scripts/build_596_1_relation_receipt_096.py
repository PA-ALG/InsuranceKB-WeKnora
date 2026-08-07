#!/usr/bin/env python3
"""Thin private CLI for the 096 derived relation receipt bridge."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from insurance_harness.compiler.parsed_documents import ParsedDocumentV1, ParseManifestV1
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    CaptureIntakeError,
    intake_mineru_capture_bundle_596_1,
)
from insurance_harness.knowledge_compiler.relation_receipt_bridge_596_1 import (
    RelationReceiptBridgeError,
    build_relation_receipt_596_1,
    publish_relation_receipt_596_1,
)


def _json(path: Path) -> object:
    return json.loads(path.read_bytes())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the private 596-1 derived relation receipt")
    parser.add_argument("--terms-capture", type=Path, required=True)
    parser.add_argument("--brochure-capture", type=Path, required=True)
    parser.add_argument("--rate-capture", type=Path, required=True)
    parser.add_argument("--terms-document", type=Path, required=True)
    parser.add_argument("--terms-manifest", type=Path, required=True)
    parser.add_argument("--rate-document", type=Path, required=True)
    parser.add_argument("--rate-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        bundle = intake_mineru_capture_bundle_596_1(
            (
                args.terms_capture.read_bytes(),
                args.brochure_capture.read_bytes(),
                args.rate_capture.read_bytes(),
            )
        )
        receipt = build_relation_receipt_596_1(
            bundle,
            ParsedDocumentV1.model_validate(_json(args.terms_document)),
            ParseManifestV1.model_validate(_json(args.terms_manifest)),
            ParsedDocumentV1.model_validate(_json(args.rate_document)),
            ParseManifestV1.model_validate(_json(args.rate_manifest)),
        )
        output = publish_relation_receipt_596_1(receipt, args.output_root)
    except (CaptureIntakeError, RelationReceiptBridgeError, ValidationError, OSError, ValueError):
        print("BLOCKED_ON_CROSS_PAGE_BINDING", file=sys.stderr)
        return 2
    print(f"DERIVED_RELATION_RECEIPT_VERIFIED {output.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
