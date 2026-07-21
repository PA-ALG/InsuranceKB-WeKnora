"""PostgreSQL concurrency acceptance for OpenSpec 015 F3.3/F4."""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from insurance_harness.db import models as _db_models  # noqa: F401
from insurance_harness.db.base import Base
from insurance_harness.db.models import InsuranceProduct, KnowledgeSpace
from insurance_harness.db.scope import load_scope
from insurance_harness.flywheel.models import Trace
from insurance_harness.flywheel.repository import apply_pull
from insurance_harness.flywheel.tables import (
    FlywheelCheckpoint,
    FlywheelObservation,
    KnowledgeGapRow,
)
from insurance_harness.knowledge import tables as _knowledge_tables  # noqa: F401

TEST_POSTGRES_URL = os.getenv("HARNESS_TEST_POSTGRES_URL")
FUTURE_TIMEOUT_S = 30


def _connect_args(schema: str | None = None) -> dict[str, object]:
    options = ["-cstatement_timeout=20000", "-clock_timeout=15000"]
    if schema is not None:
        options.append(f"-csearch_path={schema}")
    return {"connect_timeout": 10, "options": " ".join(options)}


@pytest.mark.integration_postgres
def test_f3_3_live_postgresql_two_sessions_apply_same_trace_exactly_once() -> None:
    if not TEST_POSTGRES_URL:
        pytest.fail("HARNESS_TEST_POSTGRES_URL is required for integration_postgres")
    assert TEST_POSTGRES_URL.startswith(("postgresql://", "postgresql+psycopg://"))

    schema = f"flywheel_015_{uuid.uuid4().hex}"
    admin_engine = create_engine(
        TEST_POSTGRES_URL,
        future=True,
        connect_args=_connect_args(),
    )
    engine: Engine | None = None
    schema_created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        schema_created = True
        engine = create_engine(
            TEST_POSTGRES_URL,
            future=True,
            connect_args=_connect_args(schema),
        )
        Base.metadata.create_all(engine, checkfirst=False)
        factory: sessionmaker[Session] = sessionmaker(
            bind=engine,
            expire_on_commit=False,
            future=True,
        )
        with factory.begin() as seed_session:
            space = KnowledgeSpace(
                name="flywheel-postgres",
                binding_status="bound",
                tenant_id="tenant-flywheel-postgres",
                raw_kb_id="raw-flywheel-postgres",
                wiki_kb_id="wiki-flywheel-postgres",
            )
            seed_session.add(space)
            seed_session.flush()
            product = InsuranceProduct(
                space_id=space.id,
                product_code="FW-PG-015",
                canonical_name="并发反馈飞轮终身寿险",
                category="whole-life",
                status="在售",
                meta=None,
            )
            seed_session.add(product)
            seed_session.flush()
            space_id = space.id

        trace = Trace(
            trace_id="same-trace",
            timestamp="2026-07-18T10:00:00Z",
            question="并发反馈飞轮终身寿险的等待期？",
            answer="抱歉，无法确定。",
        )
        barrier = threading.Barrier(2)

        def apply_from_separate_session() -> int:
            with factory.begin() as worker_session:
                scope = load_scope(worker_session, space_id)
                barrier.wait(timeout=10)
                return apply_pull(
                    worker_session,
                    scope,
                    "shared-export",
                    [trace],
                ).processed

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(apply_from_separate_session) for _ in range(2)]
            processed = [future.result(timeout=FUTURE_TIMEOUT_S) for future in futures]

        assert sorted(processed) == [0, 1]
        with factory() as verify_session:
            assert verify_session.scalar(
                select(func.count()).select_from(FlywheelCheckpoint)
            ) == 1
            assert verify_session.scalar(
                select(func.count()).select_from(FlywheelObservation)
            ) == 1
            gap = verify_session.scalar(select(KnowledgeGapRow))
            assert gap is not None and gap.hit_count == 1
    finally:
        if engine is not None:
            engine.dispose()
        if schema_created:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
