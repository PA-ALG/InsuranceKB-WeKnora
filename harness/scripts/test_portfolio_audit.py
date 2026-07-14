"""Report tests whose production-line coverage contexts substantially overlap.

Overlap is an advisory review signal. It is deliberately not a deletion decision or
CI failure: callers must still compare public boundaries, side effects, and failure
surfaces before consolidating tests.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from itertools import combinations
from pathlib import PurePosixPath
from typing import TextIO

LineIdentity = tuple[str, int]
TestLineSets = dict[str, set[LineIdentity]]

_PRODUCTION_PREFIX = "src/insurance_harness/"
_EXCLUDED_COMPONENTS = frozenset(
    {"tests", "migrations", "generated", "_generated", "site-packages"}
)
_PYTEST_PHASES = frozenset({"setup", "run", "teardown"})


@dataclass(frozen=True, slots=True)
class OverlapCandidate:
    """One deterministically ordered pair of potentially redundant tests."""

    test_a: str
    test_b: str
    shared_lines: int
    union_lines: int
    jaccard: float


def _canonical_production_file(raw_path: str) -> str | None:
    normalized = raw_path.replace("\\", "/").removeprefix("./")
    if any(component in {".", ".."} for component in normalized.split("/")):
        return None
    marker = "/src/insurance_harness/"
    if normalized.startswith(_PRODUCTION_PREFIX):
        canonical = normalized
    elif marker in normalized:
        canonical = "src/insurance_harness/" + normalized.split(marker, maxsplit=1)[1]
    else:
        return None

    relative_components = PurePosixPath(canonical).parts[2:]
    if not relative_components or _EXCLUDED_COMPONENTS.intersection(relative_components):
        return None
    if PurePosixPath(canonical).suffix != ".py":
        return None
    return canonical


def _normalize_test_context(raw_context: str) -> str | None:
    context = raw_context.strip()
    if not context or context == "default" or "::" not in context:
        return None
    identity, separator, phase = context.rpartition("|")
    if separator and phase in _PYTEST_PHASES:
        context = identity
    return context or None


def build_test_line_sets(
    coverage_payload: Mapping[str, object],
) -> tuple[TestLineSets, set[LineIdentity]]:
    """Invert coverage.py JSON contexts into production-line sets per pytest test."""

    raw_files = coverage_payload.get("files")
    if not isinstance(raw_files, Mapping):
        raise ValueError("coverage JSON must contain an object-valued 'files' field")

    test_lines: TestLineSets = {}
    production_lines: set[LineIdentity] = set()
    for raw_file, raw_record in raw_files.items():
        if not isinstance(raw_file, str):
            raise ValueError("coverage file paths must be strings")
        production_file = _canonical_production_file(raw_file)
        if production_file is None:
            continue
        if not isinstance(raw_record, Mapping):
            raise ValueError(f"coverage record for {raw_file!r} must be an object")
        raw_contexts = raw_record.get("contexts")
        if raw_contexts is None:
            continue
        if not isinstance(raw_contexts, Mapping):
            raise ValueError(f"coverage contexts for {raw_file!r} must be an object")

        for raw_line, contexts in raw_contexts.items():
            try:
                line_number = int(raw_line)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid coverage line number {raw_line!r}") from exc
            if line_number <= 0 or not isinstance(contexts, list):
                raise ValueError(f"invalid coverage contexts at {raw_file}:{raw_line}")

            line_identity = (production_file, line_number)
            accepted = False
            for raw_context in contexts:
                if not isinstance(raw_context, str):
                    raise ValueError(f"coverage context at {raw_file}:{raw_line} must be a string")
                test_context = _normalize_test_context(raw_context)
                if test_context is None:
                    continue
                test_lines.setdefault(test_context, set()).add(line_identity)
                accepted = True
            if accepted:
                production_lines.add(line_identity)

    return test_lines, production_lines


def find_overlap_candidates(
    test_line_sets: Mapping[str, set[LineIdentity]],
    *,
    threshold: float,
    minimum_shared_lines: int,
) -> list[OverlapCandidate]:
    """Return stable pairwise candidates meeting inclusive overlap thresholds."""

    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1 inclusive")
    if minimum_shared_lines < 1:
        raise ValueError("minimum_shared_lines must be at least 1")

    candidates: list[OverlapCandidate] = []
    for test_a, test_b in combinations(sorted(test_line_sets), 2):
        lines_a = test_line_sets[test_a]
        lines_b = test_line_sets[test_b]
        shared_lines = len(lines_a & lines_b)
        if shared_lines < minimum_shared_lines:
            continue
        union_lines = len(lines_a | lines_b)
        if union_lines == 0:
            continue
        jaccard = shared_lines / union_lines
        if jaccard < threshold:
            continue
        candidates.append(
            OverlapCandidate(
                test_a=test_a,
                test_b=test_b,
                shared_lines=shared_lines,
                union_lines=union_lines,
                jaccard=jaccard,
            )
        )

    return sorted(
        candidates,
        key=lambda item: (-item.jaccard, -item.shared_lines, item.test_a, item.test_b),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report pairwise pytest coverage-context overlap in production code."
    )
    parser.add_argument("coverage_json", help="coverage json --show-contexts output")
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--minimum-shared-lines", type=int, default=5)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Run the advisory audit; malformed or empty evidence fails closed."""

    try:
        args = _build_parser().parse_args(argv)
        with open(args.coverage_json, encoding="utf-8") as coverage_file:
            payload = json.load(coverage_file)
        if not isinstance(payload, Mapping):
            raise ValueError("coverage JSON root must be an object")
        test_lines, production_lines = build_test_line_sets(payload)
        if not test_lines:
            raise ValueError("coverage input contains no effective pytest contexts")
        if not production_lines:
            raise ValueError("coverage input contains no contextualized production lines")
        candidates = find_overlap_candidates(
            test_lines,
            threshold=args.threshold,
            minimum_shared_lines=args.minimum_shared_lines,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        stderr.write(f"error: {exc}\n")
        return 2

    report = {
        "summary": {
            "candidate_count": len(candidates),
            "context_count": len(test_lines),
            "minimum_shared_lines": args.minimum_shared_lines,
            "production_line_count": len(production_lines),
            "threshold": args.threshold,
        },
        "candidates": [asdict(candidate) for candidate in candidates],
    }
    json.dump(report, stdout, ensure_ascii=False, indent=2, sort_keys=True)
    stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
