"""PostgreSQL contract coverage for OpenSpec 017 T7 source notifications."""

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy import Table, create_engine, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable

from insurance_harness.db import models as _db_models  # noqa: F401
from insurance_harness.db.base import Base
from insurance_harness.db.scope import KnowledgeScope, load_scope
from insurance_harness.knowledge.models import SourceImportIdentity
from insurance_harness.knowledge.source_revision import (
    SourceRevisionReport,
    notify_source_revision,
)
from insurance_harness.knowledge.tables import ChangeSet, Claim, ClaimEvidence
from tests.kbhelpers import seed_bound_scope, seed_product

NOW = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
TEST_POSTGRES_URL = os.getenv("HARNESS_TEST_POSTGRES_URL")
POSTGRES_FUTURE_TIMEOUT_S = 30


def _live_connect_args(schema: str | None = None) -> dict[str, object]:
    options = ["-cstatement_timeout=15000", "-clock_timeout=5000"]
    if schema is not None:
        options.append(f"-csearch_path={schema},public")
    return {
        "connect_timeout": 10,
        "options": " ".join(options),
    }


def _identity(scope: KnowledgeScope, revision_char: str) -> SourceImportIdentity:
    return SourceImportIdentity(
        knowledge_id="knowledge-concurrent",
        raw_kb_id=scope.raw_kb_id,
        source_revision=revision_char * 64,
        file_hash=revision_char * 32,
        original_digest=revision_char * 64,
        parser_version="pdfplumber@0.11:text-v1",
    )


def test_t7_postgresql_ddl_keeps_scoped_source_idempotency_constraint() -> None:
    ddl = " ".join(
        str(
            CreateTable(cast(Table, ChangeSet.__table__)).compile(
                dialect=postgresql.dialect()  # type: ignore[no-untyped-call]
            )
        )
        .lower()
        .split()
    )

    assert "constraint uq_changeset_source" in ddl
    assert (
        "unique (space_id, source_kind, external_record_id, source_revision)"
        in ddl
    )
    connect_args = _live_connect_args("t7_test_schema")
    assert connect_args["connect_timeout"] == 10
    options = connect_args["options"]
    assert isinstance(options, str)
    assert "statement_timeout=15000" in options
    assert "lock_timeout=5000" in options
    assert "search_path=t7_test_schema,public" in options
    assert POSTGRES_FUTURE_TIMEOUT_S == 30


@pytest.mark.integration_postgres
def test_t7_live_postgresql_concurrent_notifications_create_one_recompile() -> None:
    if not TEST_POSTGRES_URL:
        pytest.fail("HARNESS_TEST_POSTGRES_URL is required for integration_postgres")
    assert TEST_POSTGRES_URL.startswith(("postgresql://", "postgresql+psycopg://"))
    schema = f"t7_source_revision_{uuid.uuid4().hex}"
    admin_engine = create_engine(
        TEST_POSTGRES_URL,
        future=True,
        connect_args=_live_connect_args(),
    )
    engine = None
    schema_created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        schema_created = True
        engine = create_engine(
            TEST_POSTGRES_URL,
            future=True,
            connect_args=_live_connect_args(schema),
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        with factory() as seed_session:
            scope = seed_bound_scope(
                seed_session,
                tenant_id="tenant-live-t7",
                raw_kb_id="raw-live-t7",
                wiki_kb_id="wiki-live-t7",
            )
            _, version = seed_product(
                seed_session,
                scope=scope,
                code="LIVE-T7",
                name="Live T7",
            )
            claim = Claim(
                space_id=scope.space_id,
                product_version_id=version.id,
                subject_type="product_version",
                predicate="waiting_period",
                value_state="present",
                value={"text": "90天"},
                status="published",
                confidence=0.9,
                extraction_method="llm",
                schema_version="v1",
                current_revision=1,
                pending_judge=False,
            )
            seed_session.add(claim)
            seed_session.flush()
            old = _identity(scope, "a")
            evidence = ClaimEvidence(
                claim_id=claim.id,
                knowledge_id=old.knowledge_id,
                chunk_id=None,
                quote="等待期为90天",
                page=1,
                authority_level=1,
                doc_role="terms",
                extraction_method="llm",
                extracted_at=NOW,
                raw_kb_id=old.raw_kb_id,
                source_revision=old.source_revision,
                file_hash=old.file_hash,
                original_digest=old.original_digest,
                parser_version=old.parser_version,
                chunk_hash=None,
                lineage_status="page_only",
                stale_at=None,
            )
            seed_session.add(evidence)
            seed_session.commit()
            scope_id = scope.space_id
        barrier = threading.Barrier(2)

        def notify_from_separate_session() -> SourceRevisionReport:
            with factory() as worker_session:
                worker_scope = load_scope(worker_session, scope_id)
                barrier.wait(timeout=10)
                report = notify_source_revision(
                    worker_session,
                    worker_scope,
                    _identity(worker_scope, "b"),
                    observed_at=NOW,
                )
                worker_session.commit()
                return report

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(notify_from_separate_session)
                for _index in range(2)
            ]
            reports = [
                future.result(timeout=POSTGRES_FUTURE_TIMEOUT_S)
                for future in futures
            ]

        assert sorted((report.created, report.reused) for report in reports) == [
            (False, True),
            (True, False),
        ]
        assert {report.change_set_id for report in reports} == {
            reports[0].change_set_id
        }
        assert sorted(report.stale_count for report in reports) == [0, 1]
        with factory() as verify_session:
            assert (
                verify_session.scalar(
                    select(func.count())
                    .select_from(ChangeSet)
                    .where(ChangeSet.source_kind == "recompile")
                )
                == 1
            )
            stale_at = verify_session.scalar(select(ClaimEvidence.stale_at))
            assert stale_at is not None
    finally:
        try:
            if engine is not None:
                engine.dispose()
        finally:
            try:
                if schema_created:
                    with admin_engine.begin() as connection:
                        connection.execute(
                            text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                        )
            finally:
                admin_engine.dispose()
