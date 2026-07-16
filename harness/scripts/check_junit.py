"""Fail CI unless JUnit proves the required executions and outcomes."""

import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _junit_details(path: Path) -> tuple[int, int, int, int, tuple[str, ...]]:
    root = ET.parse(path).getroot()
    if _local_name(root.tag) == "testsuite":
        suites = [root]
    else:
        suites = [child for child in root if _local_name(child.tag) == "testsuite"]
    if not suites:
        raise ValueError("JUnit report has no test suites")
    tests = 0
    skipped = 0
    failures = 0
    errors = 0
    for suite in suites:
        suite_tests = int(suite.attrib.get("tests", "0"))
        suite_skipped = int(suite.attrib.get("skipped", "0"))
        suite_failures = int(suite.attrib.get("failures", "0"))
        suite_errors = int(suite.attrib.get("errors", "0"))
        outcomes = (suite_skipped, suite_failures, suite_errors)
        if suite_tests < 0 or any(count < 0 for count in outcomes):
            raise ValueError("JUnit suite has invalid counts")
        if sum(outcomes) > suite_tests:
            raise ValueError("JUnit suite has invalid counts")
        tests += suite_tests
        skipped += suite_skipped
        failures += suite_failures
        errors += suite_errors

    identities: list[str] = []
    for element in root.iter():
        if _local_name(element.tag) != "testcase":
            continue
        class_name = element.attrib.get("classname")
        test_name = element.attrib.get("name")
        if class_name is None or test_name is None:
            raise ValueError("JUnit testcase has no identity")
        file_name = class_name.replace(".", "/") + ".py"
        identities.append(f"{file_name}::{test_name}")
    return tests, skipped, failures, errors, tuple(identities)


def _manifest_nodes(path: Path) -> tuple[str, ...]:
    nodes = tuple(line.strip() for line in path.read_text().splitlines() if line.strip())
    if not nodes or len(nodes) != len(set(nodes)):
        raise ValueError("manifest is not an exact node set")
    return nodes


def main(arguments: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if arguments is None else arguments)
    if len(args) not in {1, 2}:
        print("junit counts: tests=unknown skipped=unknown", file=sys.stderr)
        return 2
    try:
        tests, skipped, failures, errors, identities = _junit_details(Path(args[0]))
        expected = _manifest_nodes(Path(args[1])) if len(args) == 2 else None
    except (ET.ParseError, OSError, ValueError):
        print("junit counts: tests=unknown skipped=unknown", file=sys.stderr)
        return 2

    if expected is None:
        message = f"junit counts: tests={tests} skipped={skipped}"
        if tests <= 0 or skipped != 0:
            print(message, file=sys.stderr)
            return 1
        print(message)
        return 0

    message = (
        f"junit counts: tests={tests} skipped={skipped} "
        f"failures={failures} errors={errors}"
    )
    exact_identities = len(identities) == len(expected) and set(identities) == set(expected)
    exact_counts = (
        tests == len(expected) == 5
        and skipped == 0
        and failures == 0
        and errors == 0
    )
    if not exact_identities:
        print(
            f"{message}; JUnit identities are not the exact frozen live node set",
            file=sys.stderr,
        )
        return 1
    if not exact_counts:
        print(message, file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
