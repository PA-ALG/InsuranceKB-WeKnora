from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.test_portfolio_audit import (
    build_test_line_sets,
    find_overlap_candidates,
    main,
)

HARNESS_ROOT = Path(__file__).resolve().parents[1]


def _coverage_payload() -> dict[str, object]:
    return {
        "meta": {"show_contexts": True},
        "files": {
            "src/insurance_harness/knowledge/scope.py": {
                "contexts": {
                    "10": ["tests/test_scope.py::test_a|run", ""],
                    "11": [
                        "tests/test_scope.py::test_a|setup",
                        "tests/test_scope.py::test_b|run",
                    ],
                    "12": ["tests/test_scope.py::test_a|teardown"],
                }
            },
            "tests/support/scope.py": {
                "contexts": {"99": ["tests/test_scope.py::test_a|run"]}
            },
            "migrations/versions/example.py": {
                "contexts": {"1": ["tests/test_scope.py::test_a|run"]}
            },
            "src/insurance_harness/../external.py": {
                "contexts": {"13": ["tests/test_scope.py::test_a|run"]}
            },
        },
    }


def test_p3_1_inverts_only_production_contexts_and_normalizes_phase() -> None:
    test_lines, production_lines = build_test_line_sets(_coverage_payload())

    production_file = "src/insurance_harness/knowledge/scope.py"
    assert test_lines == {
        "tests/test_scope.py::test_a": {
            (production_file, 10),
            (production_file, 11),
            (production_file, 12),
        },
        "tests/test_scope.py::test_b": {(production_file, 11)},
    }
    assert production_lines == {
        (production_file, 10),
        (production_file, 11),
        (production_file, 12),
    }


def test_p3_2_overlap_includes_exact_threshold_and_is_stably_sorted() -> None:
    line_sets = {
        "test_c": {("scope.py", 1), ("scope.py", 2), ("scope.py", 5)},
        "test_a": {("scope.py", 1), ("scope.py", 2), ("scope.py", 3)},
        "test_b": {("scope.py", 1), ("scope.py", 2), ("scope.py", 4)},
    }

    candidates = find_overlap_candidates(
        line_sets,
        threshold=0.5,
        minimum_shared_lines=2,
    )

    assert [(item.test_a, item.test_b) for item in candidates] == [
        ("test_a", "test_b"),
        ("test_a", "test_c"),
        ("test_b", "test_c"),
    ]
    assert all(item.jaccard == 0.5 for item in candidates)
    assert find_overlap_candidates(
        line_sets,
        threshold=0.500_001,
        minimum_shared_lines=2,
    ) == []
    assert find_overlap_candidates(
        line_sets,
        threshold=0.5,
        minimum_shared_lines=3,
    ) == []


def test_p3_3_cli_reports_candidates_without_failing(tmp_path: Path) -> None:
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(json.dumps(_coverage_payload()), encoding="utf-8")
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            str(coverage_path),
            "--threshold",
            "0.3",
            "--minimum-shared-lines",
            "1",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    report = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert report["summary"] == {
        "candidate_count": 1,
        "context_count": 2,
        "minimum_shared_lines": 1,
        "production_line_count": 3,
        "threshold": 0.3,
    }


def test_p3_3_cli_rejects_malformed_or_empty_context_input(tmp_path: Path) -> None:
    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text("{", encoding="utf-8")
    empty_path = tmp_path / "empty.json"
    empty_path.write_text(
        json.dumps(
            {
                "files": {
                    "src/insurance_harness/knowledge/scope.py": {
                        "contexts": {"10": [""]}
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    for path in (malformed_path, empty_path):
        stdout = io.StringIO()
        stderr = io.StringIO()
        assert main([str(path)], stdout=stdout, stderr=stderr) == 2
        assert stdout.getvalue() == ""
        assert "error:" in stderr.getvalue()


def test_p3_1_real_pytest_cov_artifact_is_nonempty_and_consumable(
    tmp_path: Path,
) -> None:
    coverage_data = tmp_path / ".coverage"
    coverage_json = tmp_path / "coverage-contexts.json"
    environment = os.environ.copy()
    environment["COVERAGE_FILE"] = str(coverage_data)

    pytest_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_live_support_022.py",
            "-q",
            "--cov=insurance_harness",
            "--cov-context=test",
            "--cov-report=",
        ],
        cwd=HARNESS_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr

    json_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "json",
            "--show-contexts",
            "-o",
            str(coverage_json),
        ],
        cwd=HARNESS_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert json_result.returncode == 0, json_result.stdout + json_result.stderr

    stdout = io.StringIO()
    stderr = io.StringIO()
    assert main([str(coverage_json)], stdout=stdout, stderr=stderr) == 0
    assert stderr.getvalue() == ""
    summary = json.loads(stdout.getvalue())["summary"]
    assert summary["context_count"] > 0
    assert summary["production_line_count"] > 0
