from __future__ import annotations

import threading

import pytest
from pydantic import SecretStr

from insurance_harness.service_shell.config import (
    ShellConfigError,
    ShellSettings,
    load_settings,
)
from insurance_harness.service_shell.health import (
    Lifecycle,
    MigrationHeadMismatch,
    ProcessState,
    ReadinessChecker,
    evaluate_revision_heads,
    liveness,
)


def test_t2_settings_use_only_the_wiki_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARNESS_POSTGRES_DSN", "postgresql+psycopg://ignored:secret@db/wiki")
    monkeypatch.delenv("WIKI_POSTGRES_DSN", raising=False)
    with pytest.raises(ShellConfigError) as caught:
        load_settings()
    assert caught.value.keys == ("postgres_dsn",)

    monkeypatch.setenv("WIKI_POSTGRES_DSN", "postgresql+psycopg://wiki:secret@db/wiki")
    settings = load_settings()
    assert settings.postgres_dsn.get_secret_value().startswith("postgresql+psycopg://")


def test_t2_startup_error_aggregates_keys_without_secret_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WIKI_POSTGRES_DSN", raising=False)
    monkeypatch.setenv("WIKI_WORKER_LOCAL_CONCURRENCY", "0")
    with pytest.raises(ShellConfigError) as caught:
        load_settings()
    assert set(caught.value.keys) == {"postgres_dsn", "worker_local_concurrency"}
    assert "postgres_dsn" in str(caught.value)
    assert "worker_local_concurrency" in str(caught.value)

    secret = "do-not-print-this"
    monkeypatch.setenv(
        "WIKI_POSTGRES_DSN",
        f"mysql://wiki:{secret}@db/wiki",
    )
    monkeypatch.delenv("WIKI_WORKER_LOCAL_CONCURRENCY")
    with pytest.raises(ShellConfigError) as invalid:
        load_settings()
    assert secret not in str(invalid.value)
    assert invalid.value.keys == ("postgres_dsn",)


def test_t2_secrets_are_redacted_from_settings_text() -> None:
    password = "ultra-secret-password"
    credential = "static-service-credential"
    settings = ShellSettings(
        postgres_dsn=SecretStr(f"postgresql+psycopg://wiki:{password}@db/wiki"),
        principal_records_json=SecretStr(
            f'{{"{credential}":{{"kind":"service","service":"source_reader",'
            '"space_ids":["space-a"],"capabilities":["read_raw_knowledge"]}}}'
        ),
    )
    rendered = f"{settings!r} {settings!s}"
    assert password not in rendered
    assert credential not in rendered
    assert "**********" in rendered


def test_t2_two_configurations_change_runtime_values() -> None:
    first = ShellSettings(
        postgres_dsn=SecretStr("postgresql+psycopg://wiki:secret@db/wiki"),
        worker_local_concurrency=1,
        claim_poll_interval_seconds=0.1,
        drain_deadline_seconds=1,
    )
    second = ShellSettings(
        postgres_dsn=SecretStr("postgresql+psycopg://wiki:secret@db/wiki"),
        worker_local_concurrency=4,
        claim_poll_interval_seconds=2,
        drain_deadline_seconds=8,
    )
    assert (
        first.worker_local_concurrency,
        first.claim_poll_interval_seconds,
        first.drain_deadline_seconds,
    ) == (1, 0.1, 1)
    assert (
        second.worker_local_concurrency,
        second.claim_poll_interval_seconds,
        second.drain_deadline_seconds,
    ) == (4, 2, 8)


def test_t2_p1_limits_and_retry_policy_come_from_wiki_configuration() -> None:
    settings = ShellSettings(
        postgres_dsn=SecretStr("postgresql+psycopg://wiki:secret@db/wiki"),
        job_max_attempts=7,
        job_backoff_seconds=(2.0, 9.0),
        job_per_space_concurrency_limit=11,
        job_global_concurrency_limit=23,
        job_maintenance_batch_size=41,
    )
    runtime = settings.job_runtime_config()
    assert runtime.max_attempts == 7
    assert runtime.backoff_seconds == (2.0, 9.0)
    assert runtime.per_space_concurrency_limit == 11
    assert runtime.global_concurrency_limit == 23
    assert runtime.maintenance_batch_size == 41


def test_t2_heartbeat_must_be_strictly_shorter_than_lease() -> None:
    for heartbeat, lease in ((10, 10), (11, 10)):
        with pytest.raises(ValueError, match="heartbeat_interval_seconds"):
            ShellSettings(
                postgres_dsn=SecretStr("postgresql+psycopg://wiki:secret@db/wiki"),
                heartbeat_interval_seconds=heartbeat,
                lease_seconds=lease,
            )


def test_t3_liveness_has_no_external_dependency() -> None:
    lifecycle = Lifecycle()
    assert liveness(lifecycle).model_dump() == {
        "ok": True,
        "status": "live",
        "reason": None,
    }
    lifecycle.mark_serving()
    assert liveness(lifecycle).ok is True
    lifecycle.begin_drain()
    assert liveness(lifecycle).ok is True


def test_t3_readiness_starts_not_ready_then_checks_db_and_uses_fresh_cache() -> None:
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    now = [100.0]
    calls: list[str] = []

    def probe() -> None:
        calls.append("checked")

    checker = ReadinessChecker(
        lifecycle=lifecycle,
        probe=probe,
        timeout_seconds=0.1,
        freshness_seconds=5,
        monotonic=lambda: now[0],
    )
    assert checker.current().reason == "readiness_not_checked"
    assert checker.check().model_dump() == {"ok": True, "status": "ready", "reason": None}
    assert checker.check().ok is True
    assert calls == ["checked"]

    now[0] += 6
    assert checker.check().ok is True
    assert calls == ["checked", "checked"]


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (OSError("database offline"), "database_unavailable"),
        (MigrationHeadMismatch(), "migration_head_mismatch"),
    ],
)
def test_t3_readiness_fails_closed_with_typed_reason(
    failure: Exception,
    reason: str,
) -> None:
    lifecycle = Lifecycle()
    lifecycle.mark_serving()

    def probe() -> None:
        raise failure

    checker = ReadinessChecker(
        lifecycle=lifecycle,
        probe=probe,
        timeout_seconds=0.1,
        freshness_seconds=0,
    )
    result = checker.check()
    assert result.ok is False
    assert result.reason == reason
    assert "offline" not in str(result.model_dump())


def test_t3_readiness_timeout_and_draining_are_fail_closed() -> None:
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    release = threading.Event()

    def slow_probe() -> None:
        release.wait(timeout=0.2)

    checker = ReadinessChecker(
        lifecycle=lifecycle,
        probe=slow_probe,
        timeout_seconds=0.01,
        freshness_seconds=0,
    )
    try:
        assert checker.check().reason == "readiness_check_timeout"
    finally:
        release.set()

    lifecycle.begin_drain()
    assert lifecycle.state is ProcessState.DRAINING
    assert checker.check().reason == "draining"


@pytest.mark.parametrize(
    "current_heads",
    [(), ("0014",), ("0015", "other"), ("0016",)],
)
def test_t3_migration_head_must_be_one_exact_match(
    current_heads: tuple[str, ...],
) -> None:
    with pytest.raises(MigrationHeadMismatch):
        evaluate_revision_heads(current_heads=current_heads, expected_head="0015")
    evaluate_revision_heads(current_heads=("0015",), expected_head="0015")
