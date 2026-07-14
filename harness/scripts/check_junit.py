"""Fail CI unless a JUnit report proves executed tests with zero skips."""

import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _junit_counts(path: Path) -> tuple[int, int]:
    root = ET.parse(path).getroot()
    if _local_name(root.tag) == "testsuite":
        suites = [root]
    else:
        suites = [child for child in root if _local_name(child.tag) == "testsuite"]
    if not suites:
        raise ValueError("JUnit report has no test suites")
    tests = 0
    skipped = 0
    for suite in suites:
        suite_tests = int(suite.attrib.get("tests", "0"))
        suite_skipped = int(suite.attrib.get("skipped", "0"))
        if suite_tests < 0 or suite_skipped < 0 or suite_skipped > suite_tests:
            raise ValueError("JUnit suite has invalid counts")
        tests += suite_tests
        skipped += suite_skipped
    return tests, skipped


def main(arguments: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if arguments is None else arguments)
    if len(args) != 1:
        print("junit counts: tests=unknown skipped=unknown", file=sys.stderr)
        return 2
    try:
        tests, skipped = _junit_counts(Path(args[0]))
    except (ET.ParseError, OSError, ValueError):
        print("junit counts: tests=unknown skipped=unknown", file=sys.stderr)
        return 2

    message = f"junit counts: tests={tests} skipped={skipped}"
    if tests <= 0 or skipped != 0:
        print(message, file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
