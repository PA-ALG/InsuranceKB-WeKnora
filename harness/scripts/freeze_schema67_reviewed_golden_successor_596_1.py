#!/usr/bin/env python3
"""Materialize the exact provider-zero reviewed Schema67 successor artifact set."""

from __future__ import annotations

import argparse
from pathlib import Path

from insurance_harness.goldenset.schema67_reviewed_golden_successor_596_1 import (
    build_schema67_reviewed_golden_successor_596_1,
    canonical_schema67_reviewed_golden_artifact_files,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old60", type=Path, required=True)
    parser.add_argument("--latest71", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    successor = build_schema67_reviewed_golden_successor_596_1(
        old60_bytes=args.old60.read_bytes(),
        latest71_bytes=args.latest71.read_bytes(),
    )
    files = canonical_schema67_reviewed_golden_artifact_files(successor)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, payload in files.items():
        (args.output / name).write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
