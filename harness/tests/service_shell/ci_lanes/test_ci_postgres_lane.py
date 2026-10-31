"""CI lanes: PostgreSQL integration collection, preflight and JUnit evidence."""

import os
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tests.service_shell.ci_lanes.helpers import (
    CI_WORKFLOW,
    HARNESS_ROOT,
    _mapping,
    _named_step,
    _string,
    _workflow,
)

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
    f"tests/jobs/job_store_postgres/{module}::{node}"
    for module, nodes in (
        (
            "test_job_store_postgres_claims.py",
            (
                "test_p1_5_concurrent_duplicate_enqueue_creates_exactly_one_row",
                "test_p1_2_eight_workers_claim_each_job_exactly_once_until_typed_empty",
                "test_p1_2_claim_skips_externally_locked_row_without_blocking",
                "test_p1_8_concurrent_claims_never_exceed_per_space_limit",
                "test_p1_8_saturated_space_does_not_block_sibling_space",
                "test_p1_3_expired_lease_is_reclaimed_and_retaken_with_greater_generation",
                "test_p1_13_active_fence_uses_postgres_clock_and_never_mutates_job",
            ),
        ),
        (
            "test_job_store_postgres_completion.py",
            (
                "test_p1_6_completion_interrupt_before_commit_leaves_neither_row",
                "test_p1_3_late_worker_every_write_path_is_fenced_after_takeover",
                "test_p1_4_retry_loop_reaches_dead_letter_only_via_configured_policy",
                "test_p1_7_concurrent_duplicate_decisions_requeue_exactly_once",
                "test_p1_6_late_committed_smaller_id_is_still_dispatched",
            ),
        ),
        (
            "test_job_store_postgres_recovery.py",
            (
                "test_p1_10_forced_kill_takeover_yields_exactly_one_domain_result",
                "test_p1_10_poison_task_crash_loop_is_bounded_by_max_attempts",
                "test_p1_9_metrics_match_seeded_distribution_on_postgres",
                "test_c1_expired_foreign_lease_does_not_consume_global_limit",
                "test_i3_lease_duration_survives_advisory_lock_wait",
                "test_p1_8_cross_space_writes_and_outbox_reads_fail_closed_on_postgres",
            ),
        ),
        (
            "test_job_store_postgres_guards.py",
            (
                "test_m19_concurrent_dispatchers_do_not_double_deliver",
                # D-2026-07-27-16 边界冻结的强制验收节点（tasks 清单 15/16/19/21/27）。
                "test_q15_expired_lease_holder_has_no_write_authority_on_postgres",
                "test_q16_stalled_expired_leases_never_exceed_limits_on_postgres",
                "test_q17_unenumerated_space_converges_via_global_reclaim_on_postgres",
                "test_q19_declarative_domain_write_channel_on_postgres",
                "test_q30_owned_table_check_is_normalized_on_postgres",
                "test_q31_values_may_not_smuggle_sql_on_postgres",
                "test_q25_delivered_but_unmarked_crash_converges_on_postgres",
            ),
        ),
    )
    for node in nodes
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
SERVICE_SHELL_POSTGRES_NODES = {
    f"tests/service_shell/worker/test_worker_postgres.py::{node}"
    for node in (
        "test_t5_postgres_two_workers_single_result_and_unknown_type_budget",
        "test_t6_postgres_drain_reclaims_with_higher_generation_and_one_result",
    )
}
# S7c removed the legacy knowledge chain and its PostgreSQL tests (source revision 017,
# release publisher 018, workbench 008, source lifecycle 021).
POSTGRES_NODES = (
    SOURCE_LIFECYCLE_MIGRATION_POSTGRES_NODES
    | JOB_STORE_POSTGRES_NODES
    | JOB_MIGRATION_POSTGRES_NODES
    | SERVICE_SHELL_POSTGRES_NODES
)
WEKNORA_NODES = {
    "tests/test_live.py::test_live_knowledge_endpoint_shape",
    "tests/test_live.py::test_live_wiki_page_crud_roundtrip",
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


def test_p0_4_private_artifact_replays_do_not_skip_postgres_collection(
    tmp_path: Path,
) -> None:
    junit_path = tmp_path / "postgres-collection.xml"
    environment = os.environ.copy()
    for name in (
        "WEKNORA_EC01_REVISION_SET_ROOT",
        "WEKNORA_C5_TEST_C3_ROOT",
        "WEKNORA_C5_TEST_C3_NEW_ROOT",
        "WEKNORA_C5_TEST_C3_ABSENT_ROOT",
        "WEKNORA_C5_TEST_C3_HYDRATION_SUCCESSOR_ROOT",
        "WEKNORA_C5_TEST_REVISION_SET_ROOT",
    ):
        environment.pop(name, None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-m",
            "integration_postgres",
            "-q",
            f"--junitxml={junit_path}",
        ],
        cwd=HARNESS_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    suites = ET.parse(junit_path).getroot().findall("testsuite")  # noqa: S314
    assert sum(int(suite.attrib["skipped"]) for suite in suites) == 0


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
