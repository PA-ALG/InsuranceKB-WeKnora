"""OpenSpec 018 T4: service-owned publish saga, retry, and recovery."""

import asyncio
import inspect
from collections.abc import Callable
from datetime import timedelta

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

import insurance_harness.knowledge as knowledge_api
import insurance_harness.knowledge.publisher as publisher_module
from insurance_harness.adapters.weknora import (
    WeKnoraClientError,
    WeKnoraTransientError,
    WeKnoraWikiPage,
)
from insurance_harness.db.base import make_session_factory
from insurance_harness.db.models import ProductVersion
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.knowledge.publisher import PublishResult, ReleasePublisher
from insurance_harness.knowledge.tables import (
    Claim,
    CurrentRelease,
    PublishAttempt,
    ReconciliationJob,
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


def test_r3_6_package_publish_api_requires_service_owned_session() -> None:
    assert knowledge_api.ReleasePublisher is ReleasePublisher
    assert not hasattr(knowledge_api, "publish_product_version")
    assert "publish_product_version" not in knowledge_api.__all__
    assert set(knowledge_api.__all__) <= vars(knowledge_api).keys()
    assert not hasattr(publisher_module, "_legacy_publish_product_version")


def test_r4_1_package_rollback_api_requires_release_publisher() -> None:
    assert knowledge_api.ReleasePublisher is ReleasePublisher
    assert not hasattr(knowledge_api, "rollback_to_snapshot")
    assert "rollback_to_snapshot" not in knowledge_api.__all__
    assert not hasattr(publisher_module, "_legacy_rollback_to_snapshot")


class _SagaWiki:
    def __init__(self) -> None:
        self.pages: dict[tuple[str, str], WeKnoraWikiPage] = {}
        self.fail_slug: str | None = None
        self.on_mutation: Callable[[str], None] | None = None

    async def get_wiki_page(self, kb_id: str, slug: str) -> WeKnoraWikiPage:
        page = self.pages.get((kb_id, slug))
        if page is None:
            raise WeKnoraClientError(404, "missing")
        return page

    async def create_wiki_page(
        self, kb_id: str, page: WeKnoraWikiPage
    ) -> WeKnoraWikiPage:
        if self.on_mutation is not None:
            self.on_mutation(page.slug)
        if page.slug == self.fail_slug:
            raise WeKnoraTransientError("planned write failure")
        self.pages[(kb_id, page.slug)] = page
        return page

    async def update_wiki_page(
        self, kb_id: str, page: WeKnoraWikiPage
    ) -> WeKnoraWikiPage:
        if self.on_mutation is not None:
            self.on_mutation(page.slug)
        if page.slug == self.fail_slug:
            raise WeKnoraTransientError("planned write failure")
        self.pages[(kb_id, page.slug)] = page
        return page

    async def delete_wiki_page(self, kb_id: str, slug: str) -> None:
        if self.on_mutation is not None:
            self.on_mutation(slug)
        if slug == self.fail_slug:
            raise WeKnoraTransientError("planned write failure")
        self.pages.pop((kb_id, slug), None)


class _ConcurrentWiki(_SagaWiki):
    def __init__(self) -> None:
        super().__init__()
        self.in_flight = 0
        self.max_in_flight = 0

    async def _pause(self) -> None:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.02)
        self.in_flight -= 1

    async def create_wiki_page(
        self, kb_id: str, page: WeKnoraWikiPage
    ) -> WeKnoraWikiPage:
        await self._pause()
        return await super().create_wiki_page(kb_id, page)

    async def update_wiki_page(
        self, kb_id: str, page: WeKnoraWikiPage
    ) -> WeKnoraWikiPage:
        await self._pause()
        return await super().update_wiki_page(kb_id, page)

    async def delete_wiki_page(self, kb_id: str, slug: str) -> None:
        await self._pause()
        await super().delete_wiki_page(kb_id, slug)


class _LeaseWiki(_SagaWiki):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def create_wiki_page(
        self, kb_id: str, page: WeKnoraWikiPage
    ) -> WeKnoraWikiPage:
        self.started.set()
        await self.release.wait()
        return await super().create_wiki_page(kb_id, page)


class _WrongReadbackWiki(_SagaWiki):
    async def create_wiki_page(
        self, kb_id: str, page: WeKnoraWikiPage
    ) -> WeKnoraWikiPage:
        result = await super().create_wiki_page(kb_id, page)
        stored = self.pages[(kb_id, page.slug)]
        metadata = dict(stored.page_metadata or {})
        metadata["snapshot_id"] = "wrong-snapshot"
        self.pages[(kb_id, page.slug)] = stored.model_copy(
            update={"page_metadata": metadata}
        )
        return result


class _FinalCommitFailingSession(Session):
    fail_final_commit = False

    def commit(self) -> None:
        has_pointer_change = any(
            isinstance(row, CurrentRelease) for row in (*self.new, *self.dirty)
        )
        if type(self).fail_final_commit and has_pointer_change:
            type(self).fail_final_commit = False
            self.rollback()
            raise RuntimeError("planned final commit failure")
        super().commit()


def _factory(session: Session) -> Callable[[], Session]:
    bind = session.get_bind()
    assert isinstance(bind, Engine)
    return make_session_factory(bind)


def _seed_two_products(
    session: Session,
) -> tuple[KnowledgeScope, ProductVersion, ProductVersion]:
    scope = release_scope(session)
    _, version_a = release_product(session, scope, code="A")
    _, version_b = release_product(session, scope, code="B")
    release_claim(
        session,
        scope,
        version_a,
        claim_id="claim-a",
        predicate="waiting_period",
    )
    release_claim(
        session,
        scope,
        version_b,
        claim_id="claim-b",
        predicate="hesitation_period",
    )
    session.commit()
    return scope, version_a, version_b


def test_r3_6_release_publisher_public_saga_does_not_accept_session_or_kb_id() -> None:
    parameters = inspect.signature(ReleasePublisher.publish_product_version).parameters
    assert "session" not in parameters
    assert "kb_id" not in parameters


async def test_r3_2_r3_3_success_freezes_full_space_and_moves_pointer_last(
    kb_session: Session,
) -> None:
    scope, _version_a, version_b = _seed_two_products(kb_session)
    factory = _factory(kb_session)
    wiki = _SagaWiki()
    observed: list[tuple[str | None, str]] = []

    def observe(slug: str) -> None:
        del slug
        with factory() as session:
            pointer = session.scalar(
                select(CurrentRelease.snapshot_id).where(
                    CurrentRelease.space_id == scope.space_id
                )
            )
            status = session.scalar(select(ReleaseSnapshot.status))
            assert status is not None
            observed.append((pointer, status))

    wiki.on_mutation = observe
    publisher = ReleasePublisher(factory, wiki, now=lambda: NOW)

    result = await publisher.publish_product_version(
        scope,
        product_version_id=version_b.id,
        label="release-1",
    )

    assert [page.slug for page in result.pages] == [
        "product/A/V1/overview",
        "product/B/V1/overview",
    ]
    assert observed == [(None, "publishing"), (None, "publishing")]
    kb_session.expire_all()
    pointer = kb_session.get(CurrentRelease, (scope.space_id, "current"))
    assert pointer is not None and pointer.snapshot_id == result.snapshot_id
    assert kb_session.scalar(select(func.count()).select_from(SnapshotFact)) == 2
    operation = kb_session.scalar(select(ReleaseOperation))
    assert operation is not None and operation.status == "succeeded"
    assert operation.plan_digest
    assert operation.plan_frozen_at == NOW.replace(tzinfo=None)
    assert kb_session.scalar(select(func.count()).select_from(PublishAttempt)) == 2


async def test_r3_4_failed_second_page_is_durable_and_same_plan_retry_succeeds(
    kb_session: Session,
) -> None:
    scope, _version_a, version_b = _seed_two_products(kb_session)
    factory = _factory(kb_session)
    wiki = _SagaWiki()
    wiki.fail_slug = "product/B/V1/overview"
    publisher = ReleasePublisher(factory, wiki, now=lambda: NOW)

    with pytest.raises(WeKnoraTransientError, match="planned write failure"):
        await publisher.publish_product_version(
            scope,
            product_version_id=version_b.id,
            label="release-failed",
        )

    kb_session.expire_all()
    assert kb_session.get(CurrentRelease, (scope.space_id, "current")) is None
    operation = kb_session.scalar(select(ReleaseOperation))
    snapshot = kb_session.scalar(select(ReleaseSnapshot))
    assert operation is not None and operation.status == "failed"
    assert snapshot is not None and snapshot.status == "failed"
    assert kb_session.scalar(select(func.count()).select_from(PublishAttempt)) == 2
    failed_attempt = kb_session.scalar(
        select(PublishAttempt).where(PublishAttempt.status == "failed")
    )
    assert failed_attempt is not None and failed_attempt.created_new is None
    job = kb_session.scalar(select(ReconciliationJob))
    assert job is not None and job.source_operation_id == operation.id
    original_digest = operation.plan_digest

    wiki.fail_slug = None
    retry = await publisher.retry_operation(scope, operation_id=operation.id)

    kb_session.expire_all()
    retried_operation = kb_session.get(ReleaseOperation, operation.id)
    assert retry.snapshot_id == snapshot.id
    assert retried_operation is not None
    assert retried_operation.status == "succeeded"
    assert retried_operation.retry_no == 1
    assert retried_operation.plan_digest == original_digest
    assert kb_session.scalar(select(func.count()).select_from(ReleaseSnapshot)) == 1
    assert kb_session.scalar(select(func.count()).select_from(PublishAttempt)) == 4
    pointer = kb_session.get(CurrentRelease, (scope.space_id, "current"))
    assert pointer is not None and pointer.snapshot_id == snapshot.id


async def test_r3_5_wrong_upsert_readback_fails_before_pointer_and_creates_job(
    kb_session: Session,
) -> None:
    scope, _version_a, version_b = _seed_two_products(kb_session)
    publisher = ReleasePublisher(
        _factory(kb_session), _WrongReadbackWiki(), now=lambda: NOW
    )

    with pytest.raises(RuntimeError, match="wiki write verification failed"):
        await publisher.publish_product_version(
            scope,
            product_version_id=version_b.id,
            label="release-wrong-readback",
        )

    kb_session.expire_all()
    assert kb_session.get(CurrentRelease, (scope.space_id, "current")) is None
    operation = kb_session.scalar(select(ReleaseOperation))
    snapshot = kb_session.scalar(select(ReleaseSnapshot))
    attempt = kb_session.scalar(select(PublishAttempt))
    assert operation is not None and operation.status == "failed"
    assert snapshot is not None and snapshot.status == "failed"
    assert attempt is not None and attempt.created_new is True
    assert kb_session.scalar(select(func.count()).select_from(ReconciliationJob)) == 1


async def test_r3_4_final_pointer_commit_failure_is_durable_and_reconcilable(
    kb_session: Session,
) -> None:
    scope, _version_a, version_b = _seed_two_products(kb_session)
    bind = kb_session.get_bind()
    assert isinstance(bind, Engine)

    def factory() -> Session:
        return _FinalCommitFailingSession(bind=bind, expire_on_commit=False)

    _FinalCommitFailingSession.fail_final_commit = True
    publisher = ReleasePublisher(factory, _SagaWiki(), now=lambda: NOW)

    with pytest.raises(RuntimeError, match="planned final commit failure"):
        await publisher.publish_product_version(
            scope,
            product_version_id=version_b.id,
            label="release-final-commit-failed",
        )

    kb_session.expire_all()
    assert kb_session.get(CurrentRelease, (scope.space_id, "current")) is None
    operation = kb_session.scalar(select(ReleaseOperation))
    snapshot = kb_session.scalar(select(ReleaseSnapshot))
    assert operation is not None and operation.status == "failed"
    assert snapshot is not None and snapshot.status == "failed"
    job = kb_session.scalar(select(ReconciliationJob))
    assert job is not None and job.source_operation_id == operation.id


async def test_r3_2_zero_fact_release_deletes_old_pages_and_is_current(
    kb_session: Session,
) -> None:
    scope, _version_a, version_b = _seed_two_products(kb_session)
    factory = _factory(kb_session)
    wiki = _SagaWiki()
    publisher = ReleasePublisher(factory, wiki, now=lambda: NOW)
    first = await publisher.publish_product_version(
        scope,
        product_version_id=version_b.id,
        label="release-1",
    )
    assert len(wiki.pages) == 2
    with factory() as session:
        for claim in session.scalars(select(Claim)):
            claim.status = "retracted"
        session.commit()

    empty = await publisher.publish_product_version(
        scope,
        product_version_id=version_b.id,
        label="release-empty",
    )

    assert empty.snapshot_id != first.snapshot_id
    assert empty.pages == []
    assert wiki.pages == {}
    kb_session.expire_all()
    pointer = kb_session.get(CurrentRelease, (scope.space_id, "current"))
    assert pointer is not None and pointer.snapshot_id == empty.snapshot_id
    assert (
        kb_session.scalar(
            select(func.count())
            .select_from(SnapshotFact)
            .where(SnapshotFact.snapshot_id == empty.snapshot_id)
        )
        == 0
    )


async def test_r3_1_recovery_distinguishes_pre_io_building_from_running(
    kb_session: Session,
) -> None:
    scope = release_scope(kb_session)
    factory = _factory(kb_session)
    for suffix, status in (("building", "building"), ("running", "publishing")):
        snapshot = ReleaseSnapshot(
            id=f"snapshot-{suffix}",
            space_id=scope.space_id,
            label=f"release-{suffix}",
            rendered_pages=[],
            status=status,
            read_model_version=1,
            projection_frozen_at=NOW,
            published_at=None,
            published_by="test",
        )
        operation = ReleaseOperation(
            id=f"operation-{suffix}",
            space_id=scope.space_id,
            kind="publish",
            status="building" if suffix == "building" else "running",
            target_snapshot_id=snapshot.id,
            publish_plan={
                "base_snapshot_id": None,
                "target_snapshot_id": snapshot.id,
                "actions": [],
                "compensation_actions": [],
            },
            plan_digest="a" * 64,
            plan_frozen_at=NOW,
            retry_no=0,
            lease_expires_at=NOW - timedelta(seconds=1),
            heartbeat_at=NOW - timedelta(seconds=2),
            actor="test",
        )
        kb_session.add_all([snapshot, operation])
    kb_session.commit()
    publisher = ReleasePublisher(factory, _SagaWiki(), now=lambda: NOW)

    recovered = await publisher.recover_expired(scope)

    assert set(recovered) == {"operation-building", "operation-running"}
    kb_session.expire_all()
    assert all(
        operation.status == "failed"
        for operation in kb_session.scalars(select(ReleaseOperation))
    )
    assert all(
        snapshot.status == "failed"
        for snapshot in kb_session.scalars(select(ReleaseSnapshot))
    )
    jobs = list(kb_session.scalars(select(ReconciliationJob)))
    assert [job.source_operation_id for job in jobs] == ["operation-running"]


async def test_r4_5_two_publishers_share_engine_space_wiki_lock(
    kb_session: Session,
) -> None:
    scope, _version_a, version_b = _seed_two_products(kb_session)
    factory = _factory(kb_session)
    wiki = _ConcurrentWiki()
    first = ReleasePublisher(factory, wiki, now=lambda: NOW)
    second = ReleasePublisher(factory, wiki, now=lambda: NOW)

    results = await asyncio.gather(
        first.publish_product_version(
            scope,
            product_version_id=version_b.id,
            label="release-concurrent-a",
        ),
        second.publish_product_version(
            scope,
            product_version_id=version_b.id,
            label="release-concurrent-b",
        ),
        return_exceptions=True,
    )

    assert wiki.max_in_flight == 1
    successes = [result for result in results if isinstance(result, PublishResult)]
    assert len(successes) == 2
    with factory() as session:
        pointer = session.get(CurrentRelease, (scope.space_id, "current"))
        assert pointer is not None
        current_snapshot_id = pointer.snapshot_id
    assert {
        page.page_metadata["snapshot_id"]
        for page in wiki.pages.values()
        if page.page_metadata is not None
    } == {current_snapshot_id}


async def test_r3_1_recovery_waits_for_same_engine_space_plan_lock(
    kb_session: Session,
) -> None:
    scope, _version_a, version_b = _seed_two_products(kb_session)
    clock = [NOW]
    wiki = _LeaseWiki()
    publisher = ReleasePublisher(
        _factory(kb_session), wiki, now=lambda: clock[0]
    )
    publishing = asyncio.create_task(
        publisher.publish_product_version(
            scope,
            product_version_id=version_b.id,
            label="release-held",
        )
    )
    await wiki.started.wait()
    clock[0] = NOW + timedelta(minutes=10)

    recovering = asyncio.create_task(publisher.recover_expired(scope))
    await asyncio.sleep(0)
    assert not recovering.done()

    wiki.release.set()
    await publishing
    assert await recovering == ()
