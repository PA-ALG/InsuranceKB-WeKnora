"""Real PostgreSQL + WeKnora V1→V2→rollback gate for OpenSpec 018 R6.4."""

import os
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.config import HarnessSettings
from insurance_harness.db import models as _db_models  # noqa: F401
from insurance_harness.db.base import Base
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.knowledge.publisher import ReleasePublisher
from insurance_harness.knowledge.reader import SnapshotFactsResult, SnapshotReader
from insurance_harness.knowledge.tables import Claim, ClaimRevision
from tests.kbhelpers import seed_bound_scope, seed_product
from tests.support.live import AsyncCleanup, run_cleanups_preserving_failure
from tests.support.release_018 import NOW, release_claim

_REQUIRED = (
    "HARNESS_LIVE_BASE_URL",
    "HARNESS_LIVE_API_KEY",
    "HARNESS_LIVE_DB_URL",
    "HARNESS_LIVE_SPACE_ID",
    "HARNESS_LIVE_KB_ID",
)


def _connect_args(schema: str | None = None) -> dict[str, object]:
    options = ["-cstatement_timeout=30000", "-clock_timeout=5000"]
    if schema is not None:
        options.append(f"-csearch_path={schema},public")
    return {"connect_timeout": 10, "options": " ".join(options)}


def _factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        expire_on_commit=False,
        future=True,
    )


def _revise(factory: Callable[[], Session], claim_id: str) -> None:
    with factory() as session:
        claim = session.get(Claim, claim_id)
        assert claim is not None
        claim.current_revision = 2
        claim.value = {"text": "180天"}
        session.add(
            ClaimRevision(
                claim_id=claim.id,
                revision_no=2,
                before={"value": {"text": "90天"}},
                after={"value": claim.value},
                actor="live-018",
                at=NOW,
            )
        )
        session.commit()


@pytest.mark.live
async def test_r6_4_live_release_v1_v2_rollback_roundtrip() -> None:
    if any(not os.environ.get(name) for name in _REQUIRED):
        pytest.skip(f"缺 live 环境变量：{_REQUIRED}")
    database_url = os.environ["HARNESS_LIVE_DB_URL"]
    if make_url(database_url).get_backend_name() != "postgresql":
        raise AssertionError("018 live release requires PostgreSQL")
    schema = f"release_live_018_{uuid.uuid4().hex}"
    admin_engine = create_engine(
        database_url,
        future=True,
        connect_args=_connect_args(),
    )
    engine: Engine | None = None
    schema_created = False
    client = WeKnoraClient(
        HarnessSettings(
            weknora_base_url=os.environ["HARNESS_LIVE_BASE_URL"],
            weknora_api_key=os.environ["HARNESS_LIVE_API_KEY"],
        ),
        harness_job_id="release-live-018",
    )
    cleanup_slug: str | None = None
    primary_error: BaseException | None = None
    cleanup_errors: list[BaseException] = []
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        schema_created = True
        engine = create_engine(
            database_url,
            future=True,
            connect_args=_connect_args(schema),
        )
        Base.metadata.create_all(engine)
        factory = _factory(engine)
        suffix = uuid.uuid4().hex[:10]
        with factory() as session:
            scope: KnowledgeScope = seed_bound_scope(
                session,
                tenant_id=f"tenant-live-018-{suffix}",
                raw_kb_id=f"raw-live-018-{suffix}",
                wiki_kb_id=os.environ["HARNESS_LIVE_KB_ID"],
            )
            product, version = seed_product(
                session,
                scope=scope,
                code=f"LIVE018{suffix}",
                name="Release live 018",
                version_label="V1",
            )
            claim, _evidence = release_claim(
                session,
                scope,
                version,
                claim_id=f"claim-live-018-{suffix}",
                predicate="waiting_period",
            )
            session.commit()
            version_id = version.id
            claim_id = claim.id
            cleanup_slug = f"product/{product.product_code}/V1/overview"

        publisher = ReleasePublisher(factory, client)
        v1 = await publisher.publish_product_version(
            scope,
            product_version_id=version_id,
            label=f"live-018-v1-{suffix}",
        )
        _revise(factory, claim_id)
        v2 = await publisher.publish_product_version(
            scope,
            product_version_id=version_id,
            label=f"live-018-v2-{suffix}",
        )
        assert v2.snapshot_id != v1.snapshot_id
        rollback = await publisher.rollback_to_snapshot(
            scope, snapshot_id=v1.snapshot_id, actor="live-018"
        )

        fetched = await client.get_wiki_page(scope.wiki_kb_id, cleanup_slug)
        metadata = fetched.page_metadata
        assert metadata is not None
        assert metadata["managed_by"] == "insurance-harness"
        assert metadata["space_id"] == scope.space_id
        assert metadata["snapshot_id"] == v1.snapshot_id
        assert rollback.pages[0].content == fetched.content
        readback = SnapshotReader(factory).current(scope)
        assert isinstance(readback, SnapshotFactsResult)
        assert readback.snapshot_id == v1.snapshot_id
        assert readback.facts[0].value == {"text": "90天"}
        assert readback.facts[0].evidence[0].quote.endswith("=90天")
    except BaseException as error:
        primary_error = error
        raise
    finally:
        async_cleanups: list[AsyncCleanup] = [client.aclose]
        if cleanup_slug is not None:
            registered_slug = cleanup_slug

            async def delete_test_page() -> None:
                await client.delete_wiki_page(
                    os.environ["HARNESS_LIVE_KB_ID"], registered_slug
                )

            async_cleanups.insert(0, delete_test_page)
        try:
            await run_cleanups_preserving_failure(
                async_cleanups,
                primary_error=primary_error,
            )
        except BaseException as cleanup_error:
            cleanup_errors.append(cleanup_error)
        if engine is not None:
            try:
                engine.dispose()
            except BaseException as cleanup_error:
                cleanup_errors.append(cleanup_error)
        if schema_created:
            try:
                with admin_engine.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            except BaseException as cleanup_error:
                cleanup_errors.append(cleanup_error)
        try:
            admin_engine.dispose()
        except BaseException as cleanup_error:
            cleanup_errors.append(cleanup_error)
        if cleanup_errors:
            if primary_error is not None:
                for recorded_error in cleanup_errors:
                    primary_error.add_note(
                        f"live cleanup failed with {type(recorded_error).__name__}"
                    )
            else:
                first_error = cleanup_errors[0]
                for recorded_error in cleanup_errors[1:]:
                    first_error.add_note(
                        f"additional cleanup failure: {type(recorded_error).__name__}"
                    )
                raise first_error
