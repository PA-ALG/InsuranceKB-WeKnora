"""Real PostgreSQL 16 concurrency contracts for OpenSpec 021 L2/L3/L6."""

from __future__ import annotations

import os
import queue
import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from insurance_harness.db.scope import KnowledgeScope, load_scope
from insurance_harness.knowledge import (
    MergePolicy,
    import_pred_records,
    retract_source,
)
from insurance_harness.knowledge.models import SourceImportIdentity
from insurance_harness.knowledge.source_keys import derive_retract_event_key
from insurance_harness.knowledge.source_lifecycle import (
    BackfillResolutionResult,
    resolve_source_lifecycle_backfill_issue,
    source_lifecycle_lock_key,
)
from insurance_harness.knowledge.source_revision import (
    SourceRevisionReport,
    notify_source_revision,
)
from insurance_harness.knowledge.tables import (
    ChangeSet,
    Claim,
    ClaimEvidence,
    ReviewItem,
    SourceEvent,
    SourceHead,
    SourceLifecycleBackfillIssue,
)
from insurance_harness.sources import GenerationOrdering, SourceRevision
from tests.kbhelpers import allow_all_gate, seed_bound_scope, seed_product
from tests.support.source_revision import source_record

HARNESS_ROOT = Path(__file__).resolve().parents[1]
FUTURE_TIMEOUT_S = 30
WAIT_OBSERVATION_TIMEOUT_S = 10
NOW = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)
_GATE, _FP = allow_all_gate()


def _connect_args() -> dict[str, object]:
    return {
        "connect_timeout": 10,
        "options": "-cstatement_timeout=15000 -clock_timeout=5000",
    }


def _alembic_config(url: URL) -> Config:
    config = Config(str(HARNESS_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(HARNESS_ROOT / "migrations"))
    migration_url = url.update_query_dict(
        {
            "connect_timeout": "10",
            "options": "-cstatement_timeout=15000 -clock_timeout=5000",
        }
    ).render_as_string(hide_password=False)
    config.set_main_option("sqlalchemy.url", migration_url.replace("%", "%%"))
    return config


def _upgrade_random_database(url: URL) -> None:
    had_override = "HARNESS_DB_URL" in os.environ
    previous_override = os.environ.pop("HARNESS_DB_URL", None)
    try:
        command.upgrade(_alembic_config(url), "0006")
    finally:
        if had_override:
            assert previous_override is not None
            os.environ["HARNESS_DB_URL"] = previous_override
        else:
            os.environ.pop("HARNESS_DB_URL", None)


@dataclass(frozen=True)
class _PostgresRuntime:
    engine: Engine
    factory: sessionmaker[Session]


def test_l6_alembic_upgrade_ignores_process_database_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    poison_url = "postgresql+psycopg://poison.invalid/forbidden"
    monkeypatch.setenv("HARNESS_DB_URL", poison_url)
    calls: list[str] = []

    def capture_upgrade(_config: Config, revision: str) -> None:
        assert "HARNESS_DB_URL" not in os.environ
        calls.append(revision)

    monkeypatch.setattr(command, "upgrade", capture_upgrade)
    _upgrade_random_database(
        URL.create(
            "postgresql+psycopg",
            username="test",
            password="not-logged",
            host="127.0.0.1",
            port=5442,
            database="random-test-database",
        )
    )

    assert calls == ["0006"]
    assert os.environ["HARNESS_DB_URL"] == poison_url


@pytest.fixture(scope="module")
def postgres_runtime() -> Iterator[_PostgresRuntime]:
    configured_url = os.getenv("HARNESS_TEST_POSTGRES_URL")
    if not configured_url:
        pytest.fail("HARNESS_TEST_POSTGRES_URL is required for integration_postgres")
    base_url = make_url(configured_url)
    if base_url.drivername not in {"postgresql", "postgresql+psycopg"}:
        pytest.fail("HARNESS_TEST_POSTGRES_URL must use PostgreSQL")
    database_name = f"insurancekb_021_{uuid.uuid4().hex}"
    database_url = base_url.set(database=database_name)
    admin_engine = create_engine(
        base_url,
        future=True,
        isolation_level="AUTOCOMMIT",
        connect_args=_connect_args(),
    )
    engine: Engine | None = None
    database_created = False
    try:
        with admin_engine.connect() as connection:
            version = connection.exec_driver_sql("SHOW server_version_num").scalar_one()
            assert str(version).startswith("16")
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}" TEMPLATE template0')
        database_created = True
        _upgrade_random_database(database_url)
        engine = create_engine(
            database_url,
            future=True,
            connect_args=_connect_args(),
        )
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0006"
        yield _PostgresRuntime(
            engine=engine,
            factory=sessionmaker(
                bind=engine,
                expire_on_commit=False,
                future=True,
            ),
        )
    finally:
        if engine is not None:
            engine.dispose()
        if database_created:
            with admin_engine.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                    ),
                    {"database_name": database_name},
                )
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
        admin_engine.dispose()


def _seed_scope(
    runtime: _PostgresRuntime,
    suffix: str,
) -> tuple[str, str]:
    with runtime.factory() as session:
        scope = seed_bound_scope(
            session,
            tenant_id=f"tenant-{suffix}",
            raw_kb_id=f"raw-{suffix}",
            wiki_kb_id=f"wiki-{suffix}",
        )
        session.commit()
        return scope.space_id, scope.raw_kb_id


def _identity(
    scope: KnowledgeScope,
    *,
    knowledge_id: str,
    generation: int,
    revision_char: str,
) -> SourceImportIdentity:
    revision = SourceRevision(
        file_hash=revision_char * 32,
        ordering=GenerationOrdering(value=generation),
        parser_fingerprint="pdfplumber@0.11:text-v1",
    )
    return SourceImportIdentity(
        knowledge_id=knowledge_id,
        raw_kb_id=scope.raw_kb_id,
        source_revision=revision.value,
        ordering=revision.ordering,
        file_hash=revision.file_hash,
        original_digest=revision_char * 64,
        parser_version=revision.parser_fingerprint,
    )


def _source_context(
    scope: KnowledgeScope,
    identity: SourceImportIdentity,
) -> dict[str, object]:
    return {
        "space_id": scope.space_id,
        "tenant_id": scope.tenant_id,
        "raw_kb_id": scope.raw_kb_id,
        "documents": {"new.pdf": identity.model_dump(mode="python")},
    }


def _exact_tombstone_count(
    session: Session,
    scope_id: str,
    identity: SourceImportIdentity,
) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(ChangeSet)
            .where(
                ChangeSet.space_id == scope_id,
                ChangeSet.source_kind == "document",
                ChangeSet.external_record_id == identity.knowledge_id,
                ChangeSet.source_revision
                == derive_retract_event_key(
                    identity.knowledge_id,
                    identity.source_revision,
                ),
            )
        )
        or 0
    )


def _wait_for_advisory_lock_wait(
    runtime: _PostgresRuntime,
    backend_pid: int,
) -> None:
    deadline = time.monotonic() + WAIT_OBSERVATION_TIMEOUT_S
    poll_gate = threading.Event()
    while time.monotonic() < deadline:
        with runtime.engine.connect() as connection:
            wait_state = connection.execute(
                text(
                    "SELECT wait_event_type, wait_event FROM pg_stat_activity "
                    "WHERE pid = :backend_pid"
                ),
                {"backend_pid": backend_pid},
            ).one_or_none()
        if wait_state is not None and wait_state[0] == "Lock" and wait_state[1] == "advisory":
            return
        poll_gate.wait(0.02)
    pytest.fail("worker did not block on the source advisory lock")


def _wait_for_row_lock_wait(
    runtime: _PostgresRuntime,
    backend_pid: int,
) -> None:
    deadline = time.monotonic() + WAIT_OBSERVATION_TIMEOUT_S
    poll_gate = threading.Event()
    while time.monotonic() < deadline:
        with runtime.engine.connect() as connection:
            wait_state = connection.execute(
                text(
                    "SELECT wait_event_type, wait_event FROM pg_stat_activity "
                    "WHERE pid = :backend_pid"
                ),
                {"backend_pid": backend_pid},
            ).one_or_none()
        if (
            wait_state is not None
            and wait_state[0] == "Lock"
            and wait_state[1] in {"transactionid", "tuple"}
        ):
            return
        poll_gate.wait(0.02)
    pytest.fail("worker did not block on the winner source-head row lock")


@pytest.mark.integration_postgres
def test_l6_postgresql_same_first_identity_creates_one_business_aggregate(
    postgres_runtime: _PostgresRuntime,
) -> None:
    runtime = postgres_runtime
    suffix = f"same-first-{uuid.uuid4().hex}"
    scope_id, _raw_kb_id = _seed_scope(runtime, suffix)
    knowledge_id = f"knowledge-{suffix}"
    worker_pid: queue.Queue[int] = queue.Queue(maxsize=1)
    worker_started = threading.Event()

    def notify_worker() -> SourceRevisionReport:
        with runtime.factory() as session:
            worker_pid.put(int(session.scalar(text("SELECT pg_backend_pid()"))))
            scope = load_scope(session, scope_id)
            identity = _identity(
                scope,
                knowledge_id=knowledge_id,
                generation=1,
                revision_char="a",
            )
            worker_started.set()
            report = notify_source_revision(
                session,
                scope,
                identity,
                observed_at=NOW,
            )
            session.commit()
            return report

    with runtime.factory() as first_session:
        first_scope = load_scope(first_session, scope_id)
        identity = _identity(
            first_scope,
            knowledge_id=knowledge_id,
            generation=1,
            revision_char="a",
        )
        first_session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": source_lifecycle_lock_key(scope_id, knowledge_id)},
        )
        first_report = notify_source_revision(
            first_session,
            first_scope,
            identity,
            observed_at=NOW,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(notify_worker)
            assert worker_started.wait(WAIT_OBSERVATION_TIMEOUT_S)
            pid = worker_pid.get(timeout=WAIT_OBSERVATION_TIMEOUT_S)
            _wait_for_advisory_lock_wait(runtime, pid)
            assert future.done() is False
            first_session.commit()
            second_report = future.result(timeout=FUTURE_TIMEOUT_S)

    assert first_report.created is True and first_report.reused is False
    assert second_report.created is False and second_report.reused is True
    assert first_report.change_set_id == second_report.change_set_id
    with runtime.factory() as session:
        head = session.scalar(
            select(SourceHead).where(
                SourceHead.space_id == scope_id,
                SourceHead.knowledge_id == knowledge_id,
            )
        )
        events = list(
            session.scalars(
                select(SourceEvent)
                .where(
                    SourceEvent.space_id == scope_id,
                    SourceEvent.knowledge_id == knowledge_id,
                )
                .order_by(SourceEvent.created_at, SourceEvent.id)
            )
        )
        business_count = session.scalar(
            select(func.count())
            .select_from(ChangeSet)
            .where(
                ChangeSet.space_id == scope_id,
                ChangeSet.external_record_id == knowledge_id,
            )
        )
    assert head is not None and head.version == 1 and head.state == "active"
    assert [row.decision for row in events] == ["accepted_create", "idempotent"]
    assert business_count == 1


@pytest.mark.integration_postgres
@pytest.mark.parametrize("first_revision", ["b", "c"])
def test_l6_postgresql_b_c_lock_orders_redecide_to_c(
    postgres_runtime: _PostgresRuntime,
    first_revision: Literal["b", "c"],
) -> None:
    runtime = postgres_runtime
    suffix = f"bc-{first_revision}-{uuid.uuid4().hex}"
    scope_id, _raw_kb_id = _seed_scope(runtime, suffix)
    knowledge_id = f"knowledge-{suffix}"
    second_revision: Literal["b", "c"] = "c" if first_revision == "b" else "b"
    generation = {"b": 2, "c": 3}
    worker_pid: queue.Queue[int] = queue.Queue(maxsize=1)
    worker_started = threading.Event()

    def second_worker() -> SourceRevisionReport:
        with runtime.factory() as session:
            worker_pid.put(int(session.scalar(text("SELECT pg_backend_pid()"))))
            scope = load_scope(session, scope_id)
            worker_started.set()
            report = notify_source_revision(
                session,
                scope,
                _identity(
                    scope,
                    knowledge_id=knowledge_id,
                    generation=generation[second_revision],
                    revision_char=second_revision,
                ),
                observed_at=NOW,
            )
            session.commit()
            return report

    with runtime.factory() as first_session:
        first_scope = load_scope(first_session, scope_id)
        first_identity = _identity(
            first_scope,
            knowledge_id=knowledge_id,
            generation=generation[first_revision],
            revision_char=first_revision,
        )
        first_session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {
                "lock_key": source_lifecycle_lock_key(
                    scope_id,
                    knowledge_id,
                )
            },
        )
        notify_source_revision(
            first_session,
            first_scope,
            first_identity,
            observed_at=NOW,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(second_worker)
            assert worker_started.wait(WAIT_OBSERVATION_TIMEOUT_S)
            pid = worker_pid.get(timeout=WAIT_OBSERVATION_TIMEOUT_S)
            _wait_for_advisory_lock_wait(runtime, pid)
            assert future.done() is False
            first_session.commit()
            future.result(timeout=FUTURE_TIMEOUT_S)

    with runtime.factory() as session:
        verify_scope = load_scope(session, scope_id)
        expected_c_revision = _identity(
            verify_scope,
            knowledge_id=knowledge_id,
            generation=3,
            revision_char="c",
        ).source_revision
        head = session.scalar(
            select(SourceHead).where(
                SourceHead.space_id == scope_id,
                SourceHead.knowledge_id == knowledge_id,
            )
        )
        events = list(
            session.scalars(
                select(SourceEvent)
                .where(
                    SourceEvent.space_id == scope_id,
                    SourceEvent.knowledge_id == knowledge_id,
                )
                .order_by(SourceEvent.created_at, SourceEvent.id)
            )
        )
        business_count = session.scalar(
            select(func.count())
            .select_from(ChangeSet)
            .where(
                ChangeSet.space_id == scope_id,
                ChangeSet.external_record_id == knowledge_id,
            )
        )
    assert head is not None
    assert head.head_revision == expected_c_revision
    expected_second = "accepted_advance" if first_revision == "b" else "stale"
    assert [row.decision for row in events] == ["accepted_create", expected_second]
    assert events[0].change_set_id is not None
    if first_revision == "b":
        assert business_count == 2
        assert events[1].change_set_id is not None
        assert events[1].change_set_id != events[0].change_set_id
    else:
        assert business_count == 1
        assert events[1].change_set_id is None


@pytest.mark.integration_postgres
def test_l6_postgresql_resolver_and_normal_event_share_one_source_lock(
    postgres_runtime: _PostgresRuntime,
) -> None:
    runtime = postgres_runtime
    suffix = f"resolver-{uuid.uuid4().hex}"
    scope_id, _raw_kb_id = _seed_scope(runtime, suffix)
    knowledge_id = f"knowledge-{suffix}"
    with runtime.factory() as seed_session:
        seed_scope = load_scope(seed_session, scope_id)
        chosen = _identity(
            seed_scope,
            knowledge_id=knowledge_id,
            generation=2,
            revision_char="b",
        )
        issue = SourceLifecycleBackfillIssue(
            space_id=scope_id,
            tenant_id=seed_scope.tenant_id,
            raw_kb_id=seed_scope.raw_kb_id,
            knowledge_id=knowledge_id,
            observed_revisions=[chosen.source_revision],
            reason="historical ordering unavailable",
            status="open",
        )
        seed_session.add(issue)
        seed_session.commit()
        issue_id = issue.id
    worker_pid: queue.Queue[int] = queue.Queue(maxsize=1)
    worker_started = threading.Event()

    def normal_worker() -> SourceRevisionReport:
        with runtime.factory() as session:
            worker_pid.put(int(session.scalar(text("SELECT pg_backend_pid()"))))
            scope = load_scope(session, scope_id)
            worker_started.set()
            report = notify_source_revision(
                session,
                scope,
                _identity(
                    scope,
                    knowledge_id=knowledge_id,
                    generation=3,
                    revision_char="c",
                ),
                observed_at=NOW,
            )
            session.commit()
            return report

    resolved: BackfillResolutionResult
    with runtime.factory() as resolver_session:
        resolver_scope = load_scope(resolver_session, scope_id)
        resolver_identity = _identity(
            resolver_scope,
            knowledge_id=knowledge_id,
            generation=2,
            revision_char="b",
        )
        resolver_session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": source_lifecycle_lock_key(scope_id, knowledge_id)},
        )
        resolved = resolve_source_lifecycle_backfill_issue(
            resolver_session,
            resolver_scope,
            issue_id=issue_id,
            identity=resolver_identity,
            desired_state="active",
            actor="administrator",
            reason="attested source record",
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(normal_worker)
            assert worker_started.wait(WAIT_OBSERVATION_TIMEOUT_S)
            pid = worker_pid.get(timeout=WAIT_OBSERVATION_TIMEOUT_S)
            _wait_for_advisory_lock_wait(runtime, pid)
            assert future.done() is False
            resolver_session.commit()
            advanced = future.result(timeout=FUTURE_TIMEOUT_S)
    assert advanced.created is True

    with runtime.factory() as retry_session:
        retry_scope = load_scope(retry_session, scope_id)
        baseline_events = retry_session.scalar(
            select(func.count())
            .select_from(SourceEvent)
            .where(
                SourceEvent.space_id == scope_id,
                SourceEvent.knowledge_id == knowledge_id,
            )
        )
        retry = resolve_source_lifecycle_backfill_issue(
            retry_session,
            retry_scope,
            issue_id=issue_id,
            identity=_identity(
                retry_scope,
                knowledge_id=knowledge_id,
                generation=2,
                revision_char="b",
            ),
            desired_state="active",
            actor="administrator",
            reason="attested source record",
        )
        assert retry == resolved
        assert (
            retry_session.scalar(
                select(func.count())
                .select_from(SourceEvent)
                .where(
                    SourceEvent.space_id == scope_id,
                    SourceEvent.knowledge_id == knowledge_id,
                )
            )
            == baseline_events
        )
        head = retry_session.scalar(
            select(SourceHead).where(
                SourceHead.space_id == scope_id,
                SourceHead.knowledge_id == knowledge_id,
            )
        )
        events = list(
            retry_session.scalars(
                select(SourceEvent)
                .where(
                    SourceEvent.space_id == scope_id,
                    SourceEvent.knowledge_id == knowledge_id,
                )
                .order_by(SourceEvent.created_at, SourceEvent.id)
            )
        )
    assert head is not None and head.version == 2 and head.state == "active"
    assert [row.decision for row in events] == [
        "accepted_create",
        "accepted_advance",
    ]


@pytest.mark.integration_postgres
def test_l6_postgresql_first_event_delete_creates_durable_empty_tombstone(
    postgres_runtime: _PostgresRuntime,
) -> None:
    runtime = postgres_runtime
    suffix = f"first-delete-{uuid.uuid4().hex}"
    scope_id, _raw_kb_id = _seed_scope(runtime, suffix)
    knowledge_id = f"knowledge-{suffix}"
    with runtime.factory() as session:
        scope = load_scope(session, scope_id)
        identity = _identity(
            scope,
            knowledge_id=knowledge_id,
            generation=1,
            revision_char="a",
        )
        report = retract_source(session, scope, identity)
        session.commit()

    with runtime.factory() as session:
        head = session.scalar(
            select(SourceHead).where(
                SourceHead.space_id == scope_id,
                SourceHead.knowledge_id == knowledge_id,
            )
        )
        lifecycle_event = session.scalar(
            select(SourceEvent).where(
                SourceEvent.space_id == scope_id,
                SourceEvent.knowledge_id == knowledge_id,
            )
        )
        item_count = session.scalar(
            select(func.count())
            .select_from(ChangeSet)
            .where(
                ChangeSet.id == report.change_set_id,
                ChangeSet.status == "applied",
            )
        )
        change_item_count = session.scalar(
            text("SELECT count(*) FROM change_items WHERE change_set_id = :change_set_id"),
            {"change_set_id": report.change_set_id},
        )
    assert head is not None and head.state == "deleted" and head.version == 1
    assert lifecycle_event is not None
    assert lifecycle_event.decision == "accepted_delete"
    assert lifecycle_event.change_set_id == report.change_set_id
    assert item_count == 1 and change_item_count == 0


@pytest.mark.integration_postgres
@pytest.mark.parametrize("initial_state", ["active", "deleted"])
def test_l6_postgresql_newer_delete_advances_active_or_deleted_head(
    postgres_runtime: _PostgresRuntime,
    initial_state: Literal["active", "deleted"],
) -> None:
    runtime = postgres_runtime
    suffix = f"newer-delete-{initial_state}-{uuid.uuid4().hex}"
    scope_id, _raw_kb_id = _seed_scope(runtime, suffix)
    knowledge_id = f"knowledge-{suffix}"
    with runtime.factory() as session:
        scope = load_scope(session, scope_id)
        old = _identity(
            scope,
            knowledge_id=knowledge_id,
            generation=2,
            revision_char="b",
        )
        incoming = _identity(
            scope,
            knowledge_id=knowledge_id,
            generation=3,
            revision_char="c",
        )
        if initial_state == "active":
            notify_source_revision(session, scope, old, observed_at=NOW)
        else:
            retract_source(session, scope, old)
        retract_source(session, scope, incoming)
        session.commit()

    with runtime.factory() as session:
        verify_scope = load_scope(session, scope_id)
        incoming = _identity(
            verify_scope,
            knowledge_id=knowledge_id,
            generation=3,
            revision_char="c",
        )
        head = session.scalar(
            select(SourceHead).where(
                SourceHead.space_id == scope_id,
                SourceHead.knowledge_id == knowledge_id,
            )
        )
        decisions = list(
            session.scalars(
                select(SourceEvent.decision)
                .where(
                    SourceEvent.space_id == scope_id,
                    SourceEvent.knowledge_id == knowledge_id,
                )
                .order_by(SourceEvent.created_at, SourceEvent.id)
            )
        )
        incoming_tombstones = _exact_tombstone_count(
            session,
            scope_id,
            incoming,
        )
    assert head is not None
    assert head.state == "deleted" and head.version == 2
    assert head.head_revision == incoming.source_revision
    assert decisions == [
        "accepted_create" if initial_state == "active" else "accepted_delete",
        "accepted_delete",
    ]
    assert incoming_tombstones == 1


@pytest.mark.integration_postgres
def test_l6_postgresql_same_revision_delete_beats_concurrent_notify(
    postgres_runtime: _PostgresRuntime,
) -> None:
    runtime = postgres_runtime
    suffix = f"delete-notify-{uuid.uuid4().hex}"
    scope_id, _raw_kb_id = _seed_scope(runtime, suffix)
    knowledge_id = f"knowledge-{suffix}"
    with runtime.factory() as seed_session:
        scope = load_scope(seed_session, scope_id)
        identity = _identity(
            scope,
            knowledge_id=knowledge_id,
            generation=2,
            revision_char="b",
        )
        notify_source_revision(seed_session, scope, identity, observed_at=NOW)
        seed_session.commit()
    worker_pid: queue.Queue[int] = queue.Queue(maxsize=1)
    worker_started = threading.Event()

    def notify_worker() -> SourceRevisionReport:
        with runtime.factory() as session:
            worker_pid.put(int(session.scalar(text("SELECT pg_backend_pid()"))))
            scope = load_scope(session, scope_id)
            worker_started.set()
            report = notify_source_revision(
                session,
                scope,
                _identity(
                    scope,
                    knowledge_id=knowledge_id,
                    generation=2,
                    revision_char="b",
                ),
                observed_at=NOW,
            )
            session.commit()
            return report

    with runtime.factory() as delete_session:
        delete_scope = load_scope(delete_session, scope_id)
        delete_identity = _identity(
            delete_scope,
            knowledge_id=knowledge_id,
            generation=2,
            revision_char="b",
        )
        delete_session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": source_lifecycle_lock_key(scope_id, knowledge_id)},
        )
        retract_source(delete_session, delete_scope, delete_identity)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(notify_worker)
            assert worker_started.wait(WAIT_OBSERVATION_TIMEOUT_S)
            pid = worker_pid.get(timeout=WAIT_OBSERVATION_TIMEOUT_S)
            _wait_for_advisory_lock_wait(runtime, pid)
            assert future.done() is False
            delete_session.commit()
            notify_report = future.result(timeout=FUTURE_TIMEOUT_S)

    assert notify_report.same_revision is True
    assert notify_report.created is False
    assert notify_report.reused is False
    assert notify_report.change_set_id is None

    with runtime.factory() as session:
        scope = load_scope(session, scope_id)
        identity = _identity(
            scope,
            knowledge_id=knowledge_id,
            generation=2,
            revision_char="b",
        )
        head = session.scalar(
            select(SourceHead).where(
                SourceHead.space_id == scope_id,
                SourceHead.knowledge_id == knowledge_id,
            )
        )
        decisions = list(
            session.scalars(
                select(SourceEvent.decision)
                .where(
                    SourceEvent.space_id == scope_id,
                    SourceEvent.knowledge_id == knowledge_id,
                )
                .order_by(SourceEvent.created_at, SourceEvent.id)
            )
        )
        tombstones = _exact_tombstone_count(session, scope_id, identity)
    assert head is not None and head.state == "deleted" and head.version == 2
    assert decisions == ["accepted_create", "accepted_delete", "blocked_deleted"]
    assert tombstones == 1


@pytest.mark.integration_postgres
def test_l6_postgresql_same_revision_delete_beats_concurrent_import(
    postgres_runtime: _PostgresRuntime,
) -> None:
    runtime = postgres_runtime
    suffix = f"delete-import-{uuid.uuid4().hex}"
    scope_id, _raw_kb_id = _seed_scope(runtime, suffix)
    knowledge_id = f"knowledge-{suffix}"
    with runtime.factory() as seed_session:
        scope = load_scope(seed_session, scope_id)
        product, version = seed_product(
            seed_session,
            scope=scope,
            code=f"PG-021-{uuid.uuid4().hex[:10]}",
            name="PostgreSQL 021 race",
        )
        identity = _identity(
            scope,
            knowledge_id=knowledge_id,
            generation=2,
            revision_char="b",
        )
        notify_source_revision(seed_session, scope, identity, observed_at=NOW)
        seed_session.commit()
        product_code = product.product_code
        version_id = version.id
    worker_pid: queue.Queue[int] = queue.Queue(maxsize=1)
    worker_started = threading.Event()

    def import_worker() -> tuple[str, str | None]:
        with runtime.factory() as session:
            worker_pid.put(int(session.scalar(text("SELECT pg_backend_pid()"))))
            scope = load_scope(session, scope_id)
            identity = _identity(
                scope,
                knowledge_id=knowledge_id,
                generation=2,
                revision_char="b",
            )
            worker_started.set()
            report = import_pred_records(
                session,
                [source_record(identity)],
                scope=scope,
                product_id=product_code,
                product_version_id=version_id,
                source_context=_source_context(scope, identity),
                policy=MergePolicy(auto_apply_add=True),
                quality_gate=_GATE,
                run_fingerprint=_FP,
            )
            session.commit()
            partition = report.partitions[0]
            return partition.lifecycle_decision, partition.change_set_id

    with runtime.factory() as delete_session:
        delete_scope = load_scope(delete_session, scope_id)
        delete_identity = _identity(
            delete_scope,
            knowledge_id=knowledge_id,
            generation=2,
            revision_char="b",
        )
        delete_session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": source_lifecycle_lock_key(scope_id, knowledge_id)},
        )
        retract_source(delete_session, delete_scope, delete_identity)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(import_worker)
            assert worker_started.wait(WAIT_OBSERVATION_TIMEOUT_S)
            pid = worker_pid.get(timeout=WAIT_OBSERVATION_TIMEOUT_S)
            _wait_for_advisory_lock_wait(runtime, pid)
            assert future.done() is False
            delete_session.commit()
            import_decision, import_change_set_id = future.result(
                timeout=FUTURE_TIMEOUT_S
            )

    assert import_decision == "blocked_deleted"
    assert import_change_set_id is None

    with runtime.factory() as session:
        scope = load_scope(session, scope_id)
        identity = _identity(
            scope,
            knowledge_id=knowledge_id,
            generation=2,
            revision_char="b",
        )
        head = session.scalar(
            select(SourceHead).where(
                SourceHead.space_id == scope_id,
                SourceHead.knowledge_id == knowledge_id,
            )
        )
        remaining_evidence = session.scalar(
            select(func.count())
            .select_from(ClaimEvidence)
            .join(Claim, Claim.id == ClaimEvidence.claim_id)
            .where(
                Claim.space_id == scope_id,
                ClaimEvidence.knowledge_id == knowledge_id,
                ClaimEvidence.raw_kb_id == scope.raw_kb_id,
                ClaimEvidence.lineage_status.is_not(None),
            )
        )
        tombstones = _exact_tombstone_count(session, scope_id, identity)
        decisions = list(
            session.scalars(
                select(SourceEvent.decision)
                .where(
                    SourceEvent.space_id == scope_id,
                    SourceEvent.knowledge_id == knowledge_id,
                )
                .order_by(SourceEvent.created_at, SourceEvent.id)
            )
        )
        business_count = session.scalar(
            select(func.count())
            .select_from(ChangeSet)
            .where(
                ChangeSet.space_id == scope_id,
                ChangeSet.external_record_id == knowledge_id,
            )
        )
    assert head is not None and head.state == "deleted" and head.version == 2
    assert remaining_evidence == 0 and tombstones == 1
    assert decisions == ["accepted_create", "accepted_delete", "blocked_deleted"]
    assert business_count == 2


@pytest.mark.integration_postgres
def test_l6_postgresql_strictly_newer_notify_reactivates_deleted_head(
    postgres_runtime: _PostgresRuntime,
) -> None:
    runtime = postgres_runtime
    suffix = f"reactivate-{uuid.uuid4().hex}"
    scope_id, _raw_kb_id = _seed_scope(runtime, suffix)
    knowledge_id = f"knowledge-{suffix}"
    with runtime.factory() as session:
        scope = load_scope(session, scope_id)
        deleted = _identity(
            scope,
            knowledge_id=knowledge_id,
            generation=2,
            revision_char="b",
        )
        newer = _identity(
            scope,
            knowledge_id=knowledge_id,
            generation=3,
            revision_char="c",
        )
        retract_source(session, scope, deleted)
        report = notify_source_revision(session, scope, newer, observed_at=NOW)
        session.commit()

    with runtime.factory() as session:
        head = session.scalar(
            select(SourceHead).where(
                SourceHead.space_id == scope_id,
                SourceHead.knowledge_id == knowledge_id,
            )
        )
        decisions = list(
            session.scalars(
                select(SourceEvent.decision)
                .where(
                    SourceEvent.space_id == scope_id,
                    SourceEvent.knowledge_id == knowledge_id,
                )
                .order_by(SourceEvent.created_at, SourceEvent.id)
            )
        )
    assert report.created is True
    assert head is not None and head.state == "active" and head.version == 2
    assert head.head_revision == newer.source_revision
    assert decisions == ["accepted_delete", "accepted_reactivate"]


@pytest.mark.integration_postgres
def test_l6_postgresql_c_then_late_b_stays_on_c_without_business_write(
    postgres_runtime: _PostgresRuntime,
) -> None:
    runtime = postgres_runtime
    suffix = f"late-b-{uuid.uuid4().hex}"
    scope_id, _raw_kb_id = _seed_scope(runtime, suffix)
    knowledge_id = f"knowledge-{suffix}"
    with runtime.factory() as session:
        scope = load_scope(session, scope_id)
        current = _identity(
            scope,
            knowledge_id=knowledge_id,
            generation=3,
            revision_char="c",
        )
        late = _identity(
            scope,
            knowledge_id=knowledge_id,
            generation=2,
            revision_char="b",
        )
        current_report = notify_source_revision(session, scope, current, observed_at=NOW)
        late_report = notify_source_revision(session, scope, late, observed_at=NOW)
        session.commit()

    with runtime.factory() as session:
        head = session.scalar(
            select(SourceHead).where(
                SourceHead.space_id == scope_id,
                SourceHead.knowledge_id == knowledge_id,
            )
        )
        decisions = list(
            session.scalars(
                select(SourceEvent.decision)
                .where(
                    SourceEvent.space_id == scope_id,
                    SourceEvent.knowledge_id == knowledge_id,
                )
                .order_by(SourceEvent.created_at, SourceEvent.id)
            )
        )
        business_count = session.scalar(
            select(func.count())
            .select_from(ChangeSet)
            .where(
                ChangeSet.space_id == scope_id,
                ChangeSet.external_record_id == knowledge_id,
            )
        )
    assert current_report.created is True
    assert late_report.created is False and late_report.change_set_id is None
    assert head is not None and head.head_revision == current.source_revision
    assert head.version == 1 and decisions == ["accepted_create", "stale"]
    assert business_count == 1


@pytest.mark.integration_postgres
def test_l6_postgresql_controlled_cas_loser_rereads_before_business(
    postgres_runtime: _PostgresRuntime,
) -> None:
    runtime = postgres_runtime
    suffix = f"cas-reread-{uuid.uuid4().hex}"
    scope_id, _raw_kb_id = _seed_scope(runtime, suffix)
    knowledge_id = f"knowledge-{suffix}"
    with runtime.factory() as seed_session:
        scope = load_scope(seed_session, scope_id)
        initial = _identity(
            scope,
            knowledge_id=knowledge_id,
            generation=1,
            revision_char="b",
        )
        notify_source_revision(seed_session, scope, initial, observed_at=NOW)
        seed_session.commit()

    worker_pid: queue.Queue[int] = queue.Queue(maxsize=1)
    worker_started = threading.Event()

    def loser_worker() -> SourceRevisionReport:
        with runtime.factory() as session:
            worker_pid.put(int(session.scalar(text("SELECT pg_backend_pid()"))))
            scope = load_scope(session, scope_id)
            incoming = _identity(
                scope,
                knowledge_id=knowledge_id,
                generation=3,
                revision_char="d",
            )
            worker_started.set()
            report = notify_source_revision(
                session,
                scope,
                incoming,
                observed_at=NOW,
                created_by="cas-loser",
            )
            session.commit()
            return report

    with runtime.factory() as winner_session:
        winner_scope = load_scope(winner_session, scope_id)
        winner = _identity(
            winner_scope,
            knowledge_id=knowledge_id,
            generation=2,
            revision_char="c",
        )
        winner_version = winner_session.scalar(
            text(
                "UPDATE source_heads SET "
                "head_revision = :head_revision, "
                "ordering_kind = 'generation', "
                "ordering_processed_at = NULL, "
                "ordering_generation = :ordering_generation, "
                "state = 'active', version = 2, "
                "actor = 'out-of-band-winner', "
                "head_updated_at = :head_updated_at "
                "WHERE space_id = :space_id "
                "AND knowledge_id = :knowledge_id "
                "AND version = 1 "
                "RETURNING version"
            ),
            {
                "head_revision": winner.source_revision,
                "ordering_generation": winner.ordering.value,
                "head_updated_at": NOW,
                "space_id": scope_id,
                "knowledge_id": knowledge_id,
            },
        )
        assert winner_version == 2

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(loser_worker)
            assert worker_started.wait(WAIT_OBSERVATION_TIMEOUT_S)
            pid = worker_pid.get(timeout=WAIT_OBSERVATION_TIMEOUT_S)
            _wait_for_row_lock_wait(runtime, pid)
            assert future.done() is False
            winner_session.commit()
            loser_report = future.result(timeout=FUTURE_TIMEOUT_S)

    assert loser_report.created is True
    assert loser_report.reused is False
    assert loser_report.change_set_id is not None

    with runtime.factory() as session:
        verify_scope = load_scope(session, scope_id)
        incoming = _identity(
            verify_scope,
            knowledge_id=knowledge_id,
            generation=3,
            revision_char="d",
        )
        head = session.scalar(
            select(SourceHead).where(
                SourceHead.space_id == scope_id,
                SourceHead.knowledge_id == knowledge_id,
            )
        )
        events = list(
            session.scalars(
                select(SourceEvent)
                .where(
                    SourceEvent.space_id == scope_id,
                    SourceEvent.knowledge_id == knowledge_id,
                )
                .order_by(SourceEvent.created_at, SourceEvent.id)
            )
        )
        business_count = session.scalar(
            select(func.count())
            .select_from(ChangeSet)
            .where(
                ChangeSet.space_id == scope_id,
                ChangeSet.external_record_id == knowledge_id,
            )
        )
    assert head is not None and head.version == 3
    assert head.head_revision == incoming.source_revision
    assert [event.decision for event in events] == [
        "accepted_create",
        "accepted_advance",
    ]
    loser_event = events[1]
    assert loser_event.actor == "cas-loser"
    assert loser_event.before_head is not None
    assert loser_event.after_head is not None
    assert loser_event.before_head["source_revision"] == winner.source_revision
    assert loser_event.before_head["version"] == 2
    assert loser_event.after_head["source_revision"] == incoming.source_revision
    assert loser_event.after_head["version"] == 3
    assert business_count == 2


@pytest.mark.integration_postgres
def test_l6_postgresql_event_failure_rolls_back_unit_and_keeps_caller_session(
    postgres_runtime: _PostgresRuntime,
) -> None:
    runtime = postgres_runtime
    suffix = f"failure-{uuid.uuid4().hex}"
    scope_id, _raw_kb_id = _seed_scope(runtime, suffix)
    knowledge_id = f"knowledge-{suffix}"
    with runtime.factory() as session:
        scope = load_scope(session, scope_id)
        caller_row = ReviewItem(
            space_id=scope_id,
            review_key=f"caller-before-{uuid.uuid4().hex}",
            type="conflict",
            subject={"kind": "caller"},
            allowed_actions=["defer"],
            status="open",
            risk_level="low",
        )
        session.add(caller_row)
        session.flush()

        def fail_event_flush(
            candidate_session: Session,
            _context: object,
            _instances: object,
        ) -> None:
            if any(isinstance(row, SourceEvent) for row in candidate_session.new):
                raise RuntimeError("injected PostgreSQL event failure")

        sqlalchemy_event.listen(session, "before_flush", fail_event_flush)
        try:
            with pytest.raises(RuntimeError, match="PostgreSQL event failure"):
                notify_source_revision(
                    session,
                    scope,
                    _identity(
                        scope,
                        knowledge_id=knowledge_id,
                        generation=2,
                        revision_char="b",
                    ),
                    observed_at=NOW,
                )
        finally:
            sqlalchemy_event.remove(session, "before_flush", fail_event_flush)

        assert session.get(ReviewItem, caller_row.id) is caller_row
        assert (
            session.scalar(
                select(func.count())
                .select_from(SourceHead)
                .where(
                    SourceHead.space_id == scope_id,
                    SourceHead.knowledge_id == knowledge_id,
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(SourceEvent)
                .where(
                    SourceEvent.space_id == scope_id,
                    SourceEvent.knowledge_id == knowledge_id,
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ChangeSet)
                .where(
                    ChangeSet.space_id == scope_id,
                    ChangeSet.external_record_id == knowledge_id,
                )
            )
            == 0
        )
        session.add(
            ReviewItem(
                space_id=scope_id,
                review_key=f"caller-after-{uuid.uuid4().hex}",
                type="conflict",
                subject={"kind": "caller"},
                allowed_actions=["defer"],
                status="open",
                risk_level="low",
            )
        )
        session.flush()
        assert (
            session.scalar(
                select(func.count()).select_from(ReviewItem).where(ReviewItem.space_id == scope_id)
            )
            == 2
        )
        session.commit()
