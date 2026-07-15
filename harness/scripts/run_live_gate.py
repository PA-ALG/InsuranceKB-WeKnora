"""Run the frozen WeKnora live collection and verify exact JUnit evidence."""

from __future__ import annotations

import argparse
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path

FROZEN_LIVE_NODES = (
    "tests/test_knowledge_publisher.py::test_k5_5_live_publish_and_rollback_roundtrip",
    "tests/test_live.py::test_live_knowledge_endpoint_shape",
    "tests/test_live.py::test_live_wiki_page_crud_roundtrip",
    (
        "tests/test_release_snapshot_live_018.py::"
        "test_r6_4_live_release_v1_v2_rollback_roundtrip"
    ),
    (
        "tests/test_source_bridge_live_017.py::"
        "test_live_source_bridge_compiler_import_evidence_backlink"
    ),
)
JunitDetails = tuple[int, int, int, int, tuple[tuple[str, str], ...]]


def require_exact_node_set(
    label: str,
    actual: Sequence[str],
    expected: Sequence[str] = FROZEN_LIVE_NODES,
) -> None:
    """Reject count-only matches, duplicates, replacements, and omissions."""

    if len(actual) != len(expected) or set(actual) != set(expected):
        raise ValueError(f"{label} does not equal frozen live node set")


def load_frozen_nodes(path: Path) -> tuple[str, ...]:
    """Load and attest the checked-in manifest against the frozen contract."""

    nodes = tuple(line.strip() for line in path.read_text().splitlines() if line.strip())
    try:
        require_exact_node_set("manifest", nodes)
    except ValueError as error:
        raise ValueError("manifest is not the exact frozen live node set") from error
    return nodes


def _collected_nodes(output: str) -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in output.splitlines()
        if line.startswith("tests/") and "::" in line
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _raw_junit_details(
    path: Path,
) -> JunitDetails:
    root = ET.parse(path).getroot()
    if _local_name(root.tag) == "testsuite":
        suites = [root]
    else:
        suites = [child for child in root if _local_name(child.tag) == "testsuite"]
    if not suites:
        raise ValueError("raw JUnit has no test suites")

    totals = [0, 0, 0, 0]
    for suite in suites:
        counts = (
            int(suite.attrib.get("tests", "0")),
            int(suite.attrib.get("skipped", "0")),
            int(suite.attrib.get("failures", "0")),
            int(suite.attrib.get("errors", "0")),
        )
        if any(count < 0 for count in counts) or sum(counts[1:]) > counts[0]:
            raise ValueError("raw JUnit has invalid counts")
        for index, count in enumerate(counts):
            totals[index] += count

    identities: list[tuple[str, str]] = []
    for element in root.iter():
        if _local_name(element.tag) != "testcase":
            continue
        class_name = element.attrib.get("classname")
        test_name = element.attrib.get("name")
        if class_name is None or test_name is None:
            raise ValueError("raw JUnit testcase has no identity")
        identities.append((class_name, test_name))
    return totals[0], totals[1], totals[2], totals[3], tuple(identities)


def sanitize_junit_report(
    raw_path: Path,
    sanitized_path: Path,
    expected_nodes: Sequence[str] = FROZEN_LIVE_NODES,
) -> JunitDetails:
    """Write an identity-and-count-only JUnit report, or no report on failure."""

    sanitized_path.unlink(missing_ok=True)
    temporary_path = sanitized_path.with_name(f".{sanitized_path.name}.tmp")
    temporary_path.unlink(missing_ok=True)
    try:
        details = _raw_junit_details(raw_path)
        tests, skipped, failures, errors, identities = details
        nodes = tuple(
            f"{class_name.replace('.', '/')}.py::{test_name}"
            for class_name, test_name in identities
        )
        require_exact_node_set("raw JUnit", nodes, expected_nodes)

        root = ET.Element("testsuites")
        suite = ET.SubElement(
            root,
            "testsuite",
            {
                "name": "pytest-sanitized",
                "tests": str(tests),
                "skipped": str(skipped),
                "failures": str(failures),
                "errors": str(errors),
            },
        )
        for class_name, test_name in identities:
            ET.SubElement(
                suite,
                "testcase",
                {"classname": class_name, "name": test_name},
            )
        temporary_path.touch(mode=0o600)
        ET.ElementTree(root).write(
            temporary_path,
            encoding="utf-8",
            xml_declaration=True,
        )
        temporary_path.replace(sanitized_path)
        return details
    except Exception:
        temporary_path.unlink(missing_ok=True)
        sanitized_path.unlink(missing_ok=True)
        raise


def require_exact_junit_details(
    details: JunitDetails,
    expected_nodes: Sequence[str] = FROZEN_LIVE_NODES,
) -> None:
    """Reject any non-exact outcome using only parent-process memory."""

    tests, skipped, failures, errors, identities = details
    nodes = tuple(
        f"{class_name.replace('.', '/')}.py::{test_name}"
        for class_name, test_name in identities
    )
    require_exact_node_set("JUnit", nodes, expected_nodes)
    if (
        tests != len(expected_nodes)
        or len(expected_nodes) != 5
        or skipped != 0
        or failures != 0
        or errors != 0
    ):
        raise ValueError("JUnit outcomes are not the exact passing live set")


def _run(
    arguments: Sequence[str],
    *,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(arguments),
        check=False,
        capture_output=capture_output,
        text=True,
    )


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("live-nodes.txt"))
    parser.add_argument("--report", type=Path, default=Path("reports/live.xml"))
    args = parser.parse_args(arguments)

    try:
        nodes = load_frozen_nodes(args.manifest)
    except (OSError, ValueError) as error:
        print(f"live gate: {error}", file=sys.stderr)
        return 2

    collection = _run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", "live"],
        capture_output=True,
    )
    if collection.returncode != 0:
        sys.stdout.write(collection.stdout)
        sys.stderr.write(collection.stderr)
        return collection.returncode
    try:
        require_exact_node_set("collection", _collected_nodes(collection.stdout), nodes)
    except ValueError as error:
        print(f"live gate: {error}", file=sys.stderr)
        return 1

    args.report.parent.mkdir(parents=True, exist_ok=True)
    raw_report = args.report.with_name(f".{args.report.name}.raw.xml")
    args.report.unlink(missing_ok=True)
    raw_report.unlink(missing_ok=True)
    raw_report.touch(mode=0o600)
    executed = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *nodes,
            f"--junitxml={raw_report}",
        ]
    )
    try:
        junit_details = sanitize_junit_report(raw_report, args.report, nodes)
    except (ET.ParseError, OSError, ValueError):
        print("live gate: raw JUnit could not be sanitized", file=sys.stderr)
        sanitize_status = 2
    else:
        sanitize_status = 0
    finally:
        raw_report.unlink(missing_ok=True)

    if executed.returncode != 0:
        return executed.returncode
    if sanitize_status != 0:
        return sanitize_status
    try:
        require_exact_junit_details(junit_details, nodes)
    except ValueError as error:
        print(f"live gate: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
