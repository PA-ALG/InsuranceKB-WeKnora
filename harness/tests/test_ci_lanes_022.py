"""OpenSpec 022 P0.2-P0.4: CI lane and zero-skip evidence contracts."""

import os
import shlex
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_ROOT = REPO_ROOT / "harness"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "harness-ci.yml"
LIVE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "harness-live.yml"
JUNIT_GUARD = HARNESS_ROOT / "scripts" / "check_junit.py"

POSTGRES_NODE = (
    "tests/test_source_revision_postgres_017.py::"
    "test_t7_live_postgresql_concurrent_notifications_create_one_recompile"
)
WEKNORA_NODES = {
    "tests/test_knowledge_publisher.py::test_k5_5_live_publish_and_rollback_roundtrip",
    "tests/test_live.py::test_live_knowledge_endpoint_shape",
    "tests/test_live.py::test_live_wiki_page_crud_roundtrip",
    (
        "tests/test_source_bridge_live_017.py::"
        "test_live_source_bridge_compiler_import_evidence_backlink"
    ),
}
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
CHECKOUT_ACTION = "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5"
SETUP_UV_ACTION = "astral-sh/setup-uv@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86"
UPLOAD_ACTION = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"


def _pytest(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("HARNESS_TEST_POSTGRES_URL", None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", *arguments],
        cwd=HARNESS_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _collect(marker_expression: str | None) -> set[str]:
    arguments = ["--collect-only", "-q"]
    if marker_expression is not None:
        arguments.extend(("-m", marker_expression))
    result = _pytest(*arguments)
    assert result.returncode == 0, result.stdout + result.stderr
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if line.startswith("tests/") and "::" in line
    }


def _workflow(path: Path) -> Mapping[str, object]:
    document = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    return document


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, dict)
    return value


def _string(value: object) -> str:
    assert isinstance(value, str)
    return value


def _named_step(job: Mapping[str, object], name: str) -> Mapping[str, object]:
    steps = job["steps"]
    assert isinstance(steps, list)
    for step in steps:
        if isinstance(step, dict) and step.get("name") == name:
            return step
    raise AssertionError(f"workflow step is missing: {name}")


def _level_two_section(document: str, title: str) -> str:
    lines = document.splitlines()
    start = lines.index(f"## {title}") + 1
    end = next(
        (index for index in range(start, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _bash_blocks(section: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] | None = None
    for line in section.splitlines():
        if line == "```bash":
            assert current is None
            current = []
        elif line == "```" and current is not None:
            blocks.append("\n".join(current))
            current = None
        elif current is not None:
            current.append(line)
    assert current is None
    return blocks


def _shell_segments(script: str) -> list[list[str]]:
    segments: list[list[str]] = []
    for line in script.splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars="&|;")
        lexer.whitespace_split = True
        current: list[str] = []
        for token in lexer:
            if token in {"&&", "||", ";"}:
                if current:
                    segments.append(current)
                    current = []
            else:
                current.append(token)
        if current:
            segments.append(current)
    return segments


def _pytest_commands(section: str) -> list[list[str]]:
    return [
        segment
        for block in _bash_blocks(section)
        for segment in _shell_segments(block)
        if "pytest" in segment
    ]


def _prose_text(section: str) -> str:
    lines: list[str] = []
    in_fence = False
    for line in section.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        elif not in_fence:
            lines.append(line)
    return " ".join(" ".join(lines).split())


def _terms_in_order(text: str, *terms: str) -> bool:
    offset = 0
    for term in terms:
        position = text.find(term, offset)
        if position < 0:
            return False
        offset = position + len(term)
    return True


def test_rh6_1_claude_default_gate_selects_only_deterministic_lane() -> None:
    section = _level_two_section((REPO_ROOT / "CLAUDE.md").read_text(), "门禁（交付定义）")

    assert _pytest_commands(section) == [
        ["uv", "run", "pytest", "-m", "not live and not integration_postgres", "-q"]
    ]

    prose = _prose_text(section)
    assert _terms_in_order(prose, "默认", "deterministic")
    assert _terms_in_order(
        prose,
        "`integration_postgres`",
        "`.github/workflows/harness-ci.yml`",
        "PostgreSQL 16",
    )
    assert _terms_in_order(
        prose,
        "`live`",
        "`.github/workflows/harness-live.yml`",
        "`NOT RUN`",
    )


@pytest.mark.parametrize(
    ("separator", "alternative"),
    [
        ("\n", "pytest -q"),
        (" && ", "python -m pytest -q"),
        ("\n", "uv run python -m pytest -q"),
    ],
)
def test_rh6_1_parser_detects_alternative_pytest_invocation(
    separator: str,
    alternative: str,
) -> None:
    canonical = 'uv run pytest -m "not live and not integration_postgres" -q'
    section = f"```bash\n{canonical}{separator}{alternative}\n```"

    assert _pytest_commands(section) == [
        shlex.split(canonical),
        shlex.split(alternative),
    ]


def test_rh6_1_prose_pairing_tolerates_markdown_line_wrapping() -> None:
    section = """
PostgreSQL `integration_postgres`
由 `.github/workflows/harness-ci.yml` 的 PostgreSQL 16 job 验证。
"""

    assert _terms_in_order(
        _prose_text(section),
        "`integration_postgres`",
        "`.github/workflows/harness-ci.yml`",
        "PostgreSQL 16",
    )


def test_p0_2_integration_marker_is_registered() -> None:
    configuration = tomllib.loads((HARNESS_ROOT / "pyproject.toml").read_text())
    markers = configuration["tool"]["pytest"]["ini_options"]["markers"]

    assert any(marker.startswith("integration_postgres:") for marker in markers)


def test_p0_2_explicit_postgres_without_url_fails_instead_of_skipping() -> None:
    result = _pytest(POSTGRES_NODE, "-q", "-rs")

    assert result.returncode != 0
    assert "HARNESS_TEST_POSTGRES_URL is required" in result.stdout


def test_p0_4_three_collections_are_disjoint_exhaustive_and_precise() -> None:
    full = _collect(None)
    deterministic = _collect("not live and not integration_postgres")
    integration = _collect("integration_postgres")
    live = _collect("live")

    assert deterministic.isdisjoint(integration)
    assert deterministic.isdisjoint(live)
    assert integration.isdisjoint(live)
    assert deterministic | integration | live == full
    assert integration == {POSTGRES_NODE}
    assert live == WEKNORA_NODES


def test_p0_2_postgres_ci_has_service_preflight_and_junit_evidence() -> None:
    workflow = _workflow(CI_WORKFLOW)
    assert _mapping(workflow["permissions"]) == {"contents": "read"}
    triggers = _mapping(workflow["on"])
    for event in ("push", "pull_request"):
        event_configuration = _mapping(triggers[event])
        paths = event_configuration["paths"]
        assert isinstance(paths, list)
        assert ".github/workflows/harness-live.yml" in paths
    jobs = _mapping(workflow["jobs"])
    deterministic = _mapping(jobs["deterministic"])
    postgres = _mapping(jobs["integration-postgres"])

    for job, expected_actions in (
        (deterministic, {CHECKOUT_ACTION, SETUP_UV_ACTION}),
        (postgres, {CHECKOUT_ACTION, SETUP_UV_ACTION, UPLOAD_ACTION}),
    ):
        steps = job["steps"]
        assert isinstance(steps, list)
        action_steps = [
            _mapping(raw_step)
            for raw_step in steps
            if "uses" in _mapping(raw_step)
        ]
        assert {_string(step["uses"]) for step in action_steps} == expected_actions
        setup_uv = next(
            step for step in action_steps if "setup-uv@" in _string(step["uses"])
        )
        assert _mapping(setup_uv["with"])["version"] == "0.9.26"
        install = _named_step(job, "Install dependencies")
        assert install["run"] == "uv sync --locked"

    deterministic_test = _named_step(deterministic, "Tests (deterministic)")
    assert deterministic_test["run"] == (
        'uv run pytest -m "not live and not integration_postgres" -q'
    )

    services = _mapping(postgres["services"])
    service = _mapping(services["postgres"])
    assert service["image"] == "postgres:16"
    assert "pg_isready" in _string(service["options"])

    environment = _mapping(postgres["env"])
    assert _string(environment["HARNESS_TEST_POSTGRES_URL"]).startswith(
        "postgresql+psycopg://"
    )

    preflight = _named_step(postgres, "Preflight PostgreSQL")
    assert 'test -n "$HARNESS_TEST_POSTGRES_URL"' in _string(preflight["run"])
    assert "pg_isready" in _string(preflight["run"])
    test_step = _named_step(postgres, "Tests (PostgreSQL integration)")
    assert "pytest -m integration_postgres" in _string(test_step["run"])
    assert "--junitxml=reports/postgres.xml" in _string(test_step["run"])
    guard = _named_step(postgres, "Require executed zero-skip PostgreSQL tests")
    assert guard["run"] == "uv run python scripts/check_junit.py reports/postgres.xml"
    upload = _named_step(postgres, "Upload PostgreSQL JUnit")
    assert upload["if"] == "always()"
    assert _mapping(upload["with"])["path"] == "harness/reports/postgres.xml"


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
    assert "pytest -m live" in _string(test_step["run"])
    assert "--junitxml=reports/live.xml" in _string(test_step["run"])
    guard = _named_step(live, "Require executed zero-skip live tests")
    assert guard["run"] == "uv run python scripts/check_junit.py reports/live.xml"
    upload = _named_step(live, "Upload live JUnit")
    assert upload["if"] == "always()"
    assert _mapping(upload["with"])["path"] == "harness/reports/live.xml"
    steps = live["steps"]
    assert isinstance(steps, list)
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
