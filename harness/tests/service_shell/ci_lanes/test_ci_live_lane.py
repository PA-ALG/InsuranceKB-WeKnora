"""CI lanes: live workflow freeze and the zero-skip JUnit guard."""

import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from tests.service_shell.ci_lanes.helpers import (
    HARNESS_ROOT,
    REPO_ROOT,
    _mapping,
    _named_step,
    _string,
    _workflow,
)

LIVE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "harness-live.yml"
JUNIT_GUARD = HARNESS_ROOT / "scripts" / "check_junit.py"
LIVE_VARIABLES = {
    "HARNESS_LIVE_BASE_URL",
    "HARNESS_LIVE_API_KEY",
    "HARNESS_LIVE_DB_URL",
    "HARNESS_LIVE_SPACE_ID",
    "HARNESS_LIVE_KNOWLEDGE_ID",
    "HARNESS_LIVE_PARSER_FINGERPRINT",
    "HARNESS_LIVE_KB_ID",
}
LIVE_ACTIONS = {
    "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5",
    "astral-sh/setup-uv@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86",
    "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
}


def test_p0_3_live_workflow_freezes_environment_and_zero_skip_gate() -> None:
    workflow = _workflow(LIVE_WORKFLOW)
    triggers = _mapping(workflow["on"])
    assert set(triggers) == {"workflow_dispatch"}
    jobs = _mapping(workflow["jobs"])
    live = _mapping(jobs["live"])
    assert live["environment"] == "harness-live"
    assert "env" not in live

    def assert_frozen_live_environment(step: Mapping[str, object]) -> None:
        environment = _mapping(step["env"])
        assert set(environment) == LIVE_VARIABLES
        assert environment["HARNESS_LIVE_API_KEY"] == (
            "${{ secrets.HARNESS_LIVE_API_KEY }}"
        )
        assert environment["HARNESS_LIVE_DB_URL"] == (
            "${{ secrets.HARNESS_LIVE_DB_URL }}"
        )
        for name in LIVE_VARIABLES - {
            "HARNESS_LIVE_API_KEY",
            "HARNESS_LIVE_DB_URL",
        }:
            assert environment[name] == f"${{{{ vars.{name} }}}}"

    preflight = _named_step(live, "Preflight live environment")
    assert_frozen_live_environment(preflight)
    preflight_command = _string(preflight["run"])
    assert all(name in preflight_command for name in LIVE_VARIABLES)
    assert 'missing+=("$name")' in preflight_command
    assert "${missing[@]}" in preflight_command
    assert "printenv" not in preflight_command
    assert "set -x" not in preflight_command

    test_step = _named_step(live, "Tests (WeKnora live)")
    assert_frozen_live_environment(test_step)
    assert "trusted-workflow/harness/scripts/run_live_gate.py" in _string(test_step["run"])
    assert "--report reports/live.sanitized.xml" in _string(test_step["run"])
    upload = _named_step(live, "Upload live JUnit")
    assert upload["if"] == "always()"
    assert _mapping(upload["with"])["path"] == "harness/reports/live.sanitized.xml"
    steps = live["steps"]
    assert isinstance(steps, list)
    test_index = steps.index(test_step)
    assert steps[test_index + 1 :] == [upload]
    for raw_step in steps:
        step = _mapping(raw_step)
        if step.get("name") not in {
            "Preflight live environment",
            "Tests (WeKnora live)",
        }:
            assert "env" not in step
    action_steps = [_mapping(raw_step) for raw_step in steps if "uses" in _mapping(raw_step)]
    assert {_string(step["uses"]) for step in action_steps} == LIVE_ACTIONS
    setup_uv = next(step for step in action_steps if "setup-uv@" in _string(step["uses"]))
    assert _mapping(setup_uv["with"])["version"] == "0.9.26"
    install = _named_step(live, "Install dependencies")
    assert install["run"] == "uv sync --locked"


@pytest.mark.parametrize(
    ("tests", "skipped", "expected_returncode"),
    [(1, 0, 0), (0, 0, 1), (4, 1, 1), (1, -1, 2)],
)
def test_p0_junit_guard_requires_executed_zero_skip_tests(
    tmp_path: Path,
    tests: int,
    skipped: int,
    expected_returncode: int,
) -> None:
    report = tmp_path / "junit.xml"
    report.write_text(
        f'<testsuites><testsuite tests="{tests}" skipped="{skipped}" /></testsuites>'
    )

    result = subprocess.run(
        [sys.executable, str(JUNIT_GUARD), str(report)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == expected_returncode
    counts = f"junit counts: tests={tests} skipped={skipped}\n"
    if expected_returncode == 0:
        assert result.stdout == counts
        assert result.stderr == ""
    elif expected_returncode == 1:
        assert result.stdout == ""
        assert result.stderr == counts
    else:
        assert result.stdout == ""
        assert result.stderr == "junit counts: tests=unknown skipped=unknown\n"


def test_p0_junit_guard_rejects_invalid_suite_before_aggregation(
    tmp_path: Path,
) -> None:
    report = tmp_path / "junit.xml"
    report.write_text(
        '<testsuites><testsuite tests="1" skipped="1" />'
        '<testsuite tests="1" skipped="-1" /></testsuites>'
    )

    result = subprocess.run(
        [sys.executable, str(JUNIT_GUARD), str(report)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "junit counts: tests=unknown skipped=unknown\n"
