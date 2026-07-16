"""OpenSpec 023 R4.2: exact live-node and JUnit identity gates."""

import importlib.util
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType

import pytest

HARNESS_ROOT = Path(__file__).resolve().parents[1]
LIVE_MANIFEST = HARNESS_ROOT / "live-nodes.txt"
LIVE_GATE = HARNESS_ROOT / "scripts" / "run_live_gate.py"
JUNIT_GUARD = HARNESS_ROOT / "scripts" / "check_junit.py"

FROZEN_NODES = (
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


def _live_gate_module() -> ModuleType:
    assert LIVE_GATE.is_file(), "R4.2 live gate script is missing"
    spec = importlib.util.spec_from_file_location("run_live_gate", LIVE_GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _junit_report(
    path: Path,
    nodes: tuple[str, ...],
    *,
    skipped: int = 0,
    failures: int = 0,
    errors: int = 0,
) -> None:
    cases: list[str] = []
    for node in nodes:
        file_name, test_name = node.split("::", 1)
        class_name = file_name.removesuffix(".py").replace("/", ".")
        cases.append(f'<testcase classname="{class_name}" name="{test_name}" />')
    path.write_text(
        '<testsuites><testsuite name="pytest" '
        f'tests="{len(nodes)}" skipped="{skipped}" failures="{failures}" errors="{errors}">'
        + "".join(cases)
        + "</testsuite></testsuites>"
    )


def test_r4_2_manifest_is_the_frozen_five_node_identity_set() -> None:
    module = _live_gate_module()

    assert module.load_frozen_nodes(LIVE_MANIFEST) == FROZEN_NODES


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "replacement"])
def test_r4_2_manifest_rejects_missing_duplicate_or_replacement(
    tmp_path: Path,
    mutation: str,
) -> None:
    nodes = list(FROZEN_NODES)
    if mutation == "missing":
        nodes.pop()
    elif mutation == "duplicate":
        nodes[-1] = nodes[0]
    else:
        nodes[-1] = "tests/test_live.py::test_replacement"
    manifest = tmp_path / "live-nodes.txt"
    manifest.write_text("\n".join(nodes) + "\n")

    with pytest.raises(ValueError, match="exact frozen live node set"):
        _live_gate_module().load_frozen_nodes(manifest)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "replacement"])
def test_r4_2_collection_requires_exact_set_equality(mutation: str) -> None:
    nodes = list(FROZEN_NODES)
    if mutation == "missing":
        nodes.pop()
    elif mutation == "duplicate":
        nodes[-1] = nodes[0]
    else:
        nodes[-1] = "tests/test_live.py::test_replacement"

    with pytest.raises(ValueError, match="collection does not equal frozen live node set"):
        _live_gate_module().require_exact_node_set("collection", nodes, FROZEN_NODES)


def test_r4_2_junit_accepts_exact_five_identities(tmp_path: Path) -> None:
    report = tmp_path / "live.xml"
    _junit_report(report, FROZEN_NODES)

    result = subprocess.run(
        [sys.executable, str(JUNIT_GUARD), str(report), str(LIVE_MANIFEST)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "junit counts: tests=5 skipped=0 failures=0 errors=0\n"


def test_r4_2_sanitized_junit_contains_only_counts_and_exact_identities(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw.xml"
    sanitized = tmp_path / "sanitized.xml"
    _junit_report(raw, FROZEN_NODES, failures=1)
    raw.write_text(
        raw.read_text()
        .replace(
            " />",
            (
                "><failure>db-secret at https://private.example/v1</failure>"
                "<system-out>token=db-secret</system-out></testcase>"
            ),
            1,
        )
    )

    _live_gate_module().sanitize_junit_report(raw, sanitized, FROZEN_NODES)

    serialized = sanitized.read_text()
    assert "db-secret" not in serialized
    assert "https://" not in serialized
    root = ET.parse(sanitized).getroot()
    assert {_local.tag for _local in root.iter()} == {
        "testsuites",
        "testsuite",
        "testcase",
    }
    suite = next(element for element in root.iter() if element.tag == "testsuite")
    assert suite.attrib == {
        "name": "pytest-sanitized",
        "tests": "5",
        "skipped": "0",
        "failures": "1",
        "errors": "0",
    }
    cases = [element for element in root.iter() if element.tag == "testcase"]
    assert all(set(case.attrib) == {"classname", "name"} for case in cases)
    assert all(element.text is None for element in root.iter())


@pytest.mark.parametrize(
    ("failures", "expected_returncode"),
    [(0, 0), (1, 1)],
)
def test_r4_2_gate_uses_startup_memory_after_trusted_files_are_tampered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failures: int,
    expected_returncode: int,
) -> None:
    module = _live_gate_module()
    manifest = tmp_path / "live-nodes.txt"
    manifest.write_text("\n".join(FROZEN_NODES) + "\n")
    gate_script = tmp_path / "run_live_gate.py"
    gate_script.write_text("# trusted at startup\n")
    sibling_guard = tmp_path / "check_junit.py"
    sibling_guard.write_text("# trusted at startup\n")
    module.__file__ = str(gate_script)
    calls: list[tuple[str, ...]] = []

    def fake_run(
        arguments: tuple[str, ...] | list[str], *, capture_output: bool = False
    ) -> subprocess.CompletedProcess[str]:
        command = tuple(arguments)
        calls.append(command)
        if "--collect-only" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="\n".join(FROZEN_NODES) + "\n",
                stderr="",
            )
        raw_arguments = [part for part in command if part.startswith("--junitxml=")]
        if not raw_arguments:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raw_argument = raw_arguments[0]
        _junit_report(
            Path(raw_argument.partition("=")[2]),
            FROZEN_NODES,
            failures=failures,
        )
        manifest.write_text("tests/test_live.py::test_replacement\n")
        sibling_guard.write_text("raise SystemExit(0)\n")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(module, "_run", fake_run)

    returncode = module.main(
        [
            "--manifest",
            str(manifest),
            "--report",
            str(tmp_path / "live.sanitized.xml"),
        ]
    )

    assert returncode == expected_returncode
    assert len(calls) == 2
    assert sibling_guard.read_text() == "raise SystemExit(0)\n"


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "replacement"])
def test_r4_2_junit_rejects_identity_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    nodes = list(FROZEN_NODES)
    if mutation == "missing":
        nodes.pop()
    elif mutation == "duplicate":
        nodes[-1] = nodes[0]
    else:
        nodes[-1] = "tests/test_live.py::test_replacement"
    report = tmp_path / "live.xml"
    _junit_report(report, tuple(nodes))

    result = subprocess.run(
        [sys.executable, str(JUNIT_GUARD), str(report), str(LIVE_MANIFEST)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "exact frozen live node set" in result.stderr


@pytest.mark.parametrize(
    ("skipped", "failures", "errors"),
    [(1, 0, 0), (0, 1, 0), (0, 0, 1)],
)
def test_r4_2_junit_rejects_nonzero_outcome_count(
    tmp_path: Path,
    skipped: int,
    failures: int,
    errors: int,
) -> None:
    report = tmp_path / "live.xml"
    _junit_report(
        report,
        FROZEN_NODES,
        skipped=skipped,
        failures=failures,
        errors=errors,
    )

    result = subprocess.run(
        [sys.executable, str(JUNIT_GUARD), str(report), str(LIVE_MANIFEST)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "tests=5" in result.stderr
