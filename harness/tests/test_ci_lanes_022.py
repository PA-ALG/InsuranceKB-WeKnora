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
SOURCE_LIFECYCLE_POSTGRES_NODES = {
    f"tests/test_source_lifecycle_postgres_021.py::{node}"
    for node in (
        "test_l6_postgresql_same_first_identity_creates_one_business_aggregate",
        "test_l6_postgresql_b_c_lock_orders_redecide_to_c[b]",
        "test_l6_postgresql_b_c_lock_orders_redecide_to_c[c]",
        "test_l6_postgresql_resolver_and_normal_event_share_one_source_lock",
        "test_l6_postgresql_first_event_delete_creates_durable_empty_tombstone",
        "test_l6_postgresql_newer_delete_advances_active_or_deleted_head[active]",
        "test_l6_postgresql_newer_delete_advances_active_or_deleted_head[deleted]",
        "test_l6_postgresql_same_revision_delete_beats_concurrent_notify",
        "test_l6_postgresql_same_revision_delete_beats_concurrent_import",
        "test_l6_postgresql_strictly_newer_notify_reactivates_deleted_head",
        "test_l6_postgresql_c_then_late_b_stays_on_c_without_business_write",
        "test_l6_postgresql_controlled_cas_loser_rereads_before_business",
        "test_l6_postgresql_event_failure_rolls_back_unit_and_keeps_caller_session",
    )
}
SOURCE_LIFECYCLE_MIGRATION_POSTGRES_NODES = {
    f"tests/test_source_lifecycle_migration_postgres_021.py::{node}"
    for node in (
        "test_l5_0012_to_0006_installs_postgresql_schema_constraints_and_append_only_guards",
        "test_l5_historical_0012_rows_create_zero_heads_and_one_open_issue_per_source",
        "test_l5_nonempty_lifecycle_or_provenance_downgrade_fails_before_any_ddl[source_head]",
        "test_l5_nonempty_lifecycle_or_provenance_downgrade_fails_before_any_ddl[source_event]",
        "test_l5_nonempty_lifecycle_or_provenance_downgrade_fails_before_any_ddl[backfill_issue]",
        "test_l5_nonempty_lifecycle_or_provenance_downgrade_fails_before_any_ddl[historical_provenance]",
        "test_l5_empty_0006_to_0012_to_0006_round_trip_restores_postgresql_schema",
        "test_l5_alembic_check_passes_and_revision_topology_keeps_single_head",
    )
}
JOB_STORE_POSTGRES_NODES = {
    f"tests/test_job_store_postgres_035.py::{node}"
    for node in (
        "test_p1_5_concurrent_duplicate_enqueue_creates_exactly_one_row",
        "test_p1_2_eight_workers_claim_each_job_exactly_once_until_typed_empty",
        "test_p1_2_claim_skips_externally_locked_row_without_blocking",
        "test_p1_8_concurrent_claims_never_exceed_per_space_limit",
        "test_p1_8_saturated_space_does_not_block_sibling_space",
        "test_p1_3_expired_lease_is_reclaimed_and_retaken_with_greater_generation",
        "test_p1_6_completion_interrupt_before_commit_leaves_neither_row",
        "test_p1_3_late_worker_every_write_path_is_fenced_after_takeover",
        "test_p1_4_retry_loop_reaches_dead_letter_only_via_configured_policy",
        "test_p1_7_concurrent_duplicate_decisions_requeue_exactly_once",
        "test_p1_6_late_committed_smaller_id_is_still_dispatched",
        "test_p1_10_forced_kill_takeover_yields_exactly_one_domain_result",
        "test_p1_10_poison_task_crash_loop_is_bounded_by_max_attempts",
        "test_p1_9_metrics_match_seeded_distribution_on_postgres",
        "test_c1_expired_foreign_lease_does_not_consume_global_limit",
        "test_i3_lease_duration_survives_advisory_lock_wait",
        "test_p1_8_cross_space_writes_and_outbox_reads_fail_closed_on_postgres",
        "test_m19_concurrent_dispatchers_do_not_double_deliver",
        # D-2026-07-27-16 边界冻结的强制验收节点（tasks 清单 15/16/19/21/27）。
        "test_q15_expired_lease_holder_has_no_write_authority_on_postgres",
        "test_q16_stalled_expired_leases_never_exceed_limits_on_postgres",
        "test_q17_unenumerated_space_converges_via_global_reclaim_on_postgres",
        "test_q19_declarative_domain_write_channel_on_postgres",
        "test_q25_delivered_but_unmarked_crash_converges_on_postgres",
    )
}
JOB_MIGRATION_POSTGRES_NODES = {
    f"tests/test_job_migration_postgres_035.py::{node}"
    for node in (
        "test_p1_11_single_new_migration_from_real_head_0006",
        "test_p1_11_wiki_jobs_columns_not_null_space_and_idempotency_unique",
        "test_p1_11_outbox_ordered_id_event_id_unique_and_not_null_space",
        "test_i9_downgrade_with_live_rows_is_refused_before_any_ddl",
        # D-2026-07-27-16：降级 crossing 分支、DLQ 取证保护、offline 显式拒绝。
        "test_q26_downgrade_relative_destination_crossing_0006_is_resolved",
        "test_q26_downgrade_refuses_while_dead_letter_forensics_exist",
        "test_q26_offline_sql_downgrade_is_explicitly_refused",
    )
}
POSTGRES_NODES = (
    {
        POSTGRES_NODE,
        (
            "tests/test_flywheel_postgres_015.py::"
            "test_f3_3_live_postgresql_two_sessions_apply_same_trace_exactly_once"
        ),
        (
            "tests/test_release_publisher_postgres_018.py::"
            "test_r3_6_postgresql_release_never_commits_caller_transaction"
        ),
        (
            "tests/test_workbench_concurrency_008.py::"
            "test_w1_4_live_postgresql_two_sessions_single_apply"
        ),
    }
    | SOURCE_LIFECYCLE_POSTGRES_NODES
    | SOURCE_LIFECYCLE_MIGRATION_POSTGRES_NODES
    | JOB_STORE_POSTGRES_NODES
    | JOB_MIGRATION_POSTGRES_NODES
)
WEKNORA_NODES = {
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
    section = _level_two_section((REPO_ROOT / "CLAUDE.md").read_text(), "默认验证")

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


@pytest.mark.parametrize("node", sorted(POSTGRES_NODES))
def test_p0_2_explicit_postgres_without_url_fails_instead_of_skipping(
    node: str,
) -> None:
    result = _pytest(node, "-q", "-rs")

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
    assert integration == POSTGRES_NODES
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
