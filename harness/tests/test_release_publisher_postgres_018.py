"""PostgreSQL integration for OpenSpec 018 R3.6 service-owned Sessions."""

import os
import uuid

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from insurance_harness.adapters.weknora import (
    WeKnoraClientError,
    WeKnoraWikiPage,
)
from insurance_harness.db import models as _db_models  # noqa: F401
from insurance_harness.db.base import Base
from insurance_harness.db.models import InsuranceProduct
from insurance_harness.knowledge.publisher import ReleasePublisher
from insurance_harness.knowledge.tables import (
    CurrentRelease,
    ReleaseOperation,
    ReleaseSnapshot,
    SnapshotFact,
)
from tests.support.release_018 import (
    NOW,
    release_claim,
    release_product,
    release_scope,
)

TEST_POSTGRES_URL = os.getenv("HARNESS_TEST_POSTGRES_URL")


def _connect_args(schema: str | None = None) -> dict[str, object]:
    options = ["-cstatement_timeout=15000", "-clock_timeout=5000"]
    if schema is not None:
        options.append(f"-csearch_path={schema}")
    return {"connect_timeout": 10, "options": " ".join(options)}


def test_r6_4_postgresql_schema_does_not_fallback_to_public() -> None:
    options = _connect_args("release_018_test")["options"]

    assert isinstance(options, str)
    assert "search_path=release_018_test" in options
    assert "search_path=release_018_test,public" not in options


class _PostgresWiki:
    def __init__(self) -> None:
        self.pages: dict[tuple[str, str], WeKnoraWikiPage] = {}

    async def get_wiki_page(self, kb_id: str, slug: str) -> WeKnoraWikiPage:
        page = self.pages.get((kb_id, slug))
        if page is None:
            raise WeKnoraClientError(404, "missing")
        return page

    async def create_wiki_page(
        self, kb_id: str, page: WeKnoraWikiPage
    ) -> WeKnoraWikiPage:
        self.pages[(kb_id, page.slug)] = page
        return page

    async def update_wiki_page(
        self, kb_id: str, page: WeKnoraWikiPage
    ) -> WeKnoraWikiPage:
        self.pages[(kb_id, page.slug)] = page
        return page

    async def delete_wiki_page(self, kb_id: str, slug: str) -> None:
        self.pages.pop((kb_id, slug), None)


def _assert_postgresql_guard_rejects(
    factory: sessionmaker[Session],
    statement: str,
    parameters: dict[str, object],
) -> None:
    with factory() as session:
        with pytest.raises(IntegrityError):
            session.execute(text(statement), parameters)
            session.commit()
        session.rollback()


@pytest.mark.integration_postgres
async def test_r3_6_postgresql_release_never_commits_caller_transaction() -> None:
    if not TEST_POSTGRES_URL:
        pytest.fail("HARNESS_TEST_POSTGRES_URL is required for integration_postgres")
    assert TEST_POSTGRES_URL.startswith(
        ("postgresql://", "postgresql+psycopg://")
    )
    schema = f"release_018_{uuid.uuid4().hex}"
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
        Base.metadata.create_all(engine)
        factory: sessionmaker[Session] = sessionmaker(
            bind=engine,
            expire_on_commit=False,
            future=True,
        )
        with factory() as seed_session:
            scope = release_scope(seed_session, "postgres-018")
            _, version = release_product(
                seed_session, scope, code="POSTGRES-018"
            )
            release_claim(
                seed_session,
                scope,
                version,
                claim_id="claim-postgres-018",
                predicate="waiting_period",
            )
            seed_session.commit()
            version_id = version.id

        caller = factory()
        uncommitted_product_id = str(uuid.uuid4())
        try:
            caller.add(
                InsuranceProduct(
                    id=uncommitted_product_id,
                    space_id=scope.space_id,
                    product_code="CALLER-UNCOMMITTED",
                    canonical_name="caller uncommitted",
                    category="life",
                    status="在售",
                    meta=None,
                )
            )
            caller.flush()

            result = await ReleasePublisher(
                factory, _PostgresWiki(), now=lambda: NOW
            ).publish_product_version(
                scope,
                product_version_id=version_id,
                label="release-postgres-018",
            )

            assert caller.in_transaction()
            caller.rollback()
        finally:
            caller.close()

        with factory() as verification:
            assert verification.get(
                InsuranceProduct, uncommitted_product_id
            ) is None
            pointer = verification.scalar(
                select(CurrentRelease).where(
                    CurrentRelease.space_id == scope.space_id
                )
            )
            assert pointer is not None
            assert pointer.snapshot_id == result.snapshot_id
            operation_id = verification.scalar(
                select(ReleaseOperation.id).where(
                    ReleaseOperation.space_id == scope.space_id,
                    ReleaseOperation.kind == "publish",
                )
            )
            fact_id = verification.scalar(
                select(SnapshotFact.id).where(
                    SnapshotFact.space_id == scope.space_id,
                    SnapshotFact.snapshot_id == result.snapshot_id,
                )
            )
            assert operation_id is not None and fact_id is not None

        unfrozen_snapshot_id = str(uuid.uuid4())
        with factory() as guard_seed:
            guard_seed.add(
                ReleaseSnapshot(
                    id=unfrozen_snapshot_id,
                    space_id=scope.space_id,
                    label="postgres-guard-unfrozen",
                    rendered_pages=[],
                    status="published",
                    read_model_version=1,
                    projection_frozen_at=None,
                    published_at=NOW,
                    published_by="postgres-guard",
                )
            )
            guard_seed.commit()

        _assert_postgresql_guard_rejects(
            factory,
            "UPDATE current_release SET snapshot_id=:snapshot_id "
            "WHERE space_id=:space_id",
            {
                "snapshot_id": unfrozen_snapshot_id,
                "space_id": scope.space_id,
            },
        )
        _assert_postgresql_guard_rejects(
            factory,
            "UPDATE snapshot_facts SET value=CAST(:value AS json) WHERE id=:id",
            {"value": "{}", "id": fact_id},
        )
        _assert_postgresql_guard_rejects(
            factory,
            "DELETE FROM snapshot_facts WHERE id=:id",
            {"id": fact_id},
        )
        _assert_postgresql_guard_rejects(
            factory,
            "UPDATE release_operations SET publish_plan=CAST(:plan AS json) "
            "WHERE id=:id",
            {"plan": "{}", "id": operation_id},
        )
        _assert_postgresql_guard_rejects(
            factory,
            "UPDATE release_snapshots SET rendered_pages=CAST(:pages AS json) "
            "WHERE id=:id",
            {"pages": "[]", "id": result.snapshot_id},
        )
    finally:
        if engine is not None:
            engine.dispose()
        if schema_created:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
