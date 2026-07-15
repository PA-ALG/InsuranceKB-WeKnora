"""OpenSpec 018 T7: pointer-last rollback and reconciliation lineage."""

from collections.abc import Callable
from datetime import timedelta

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from insurance_harness.adapters.weknora import (
    WeKnoraClientError,
    WeKnoraTransientError,
    WeKnoraWikiPage,
)
from insurance_harness.db.base import make_session_factory
from insurance_harness.db.models import ProductVersion
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.knowledge.pages import RenderedPage
from insurance_harness.knowledge.publisher import ReleasePublisher
from insurance_harness.knowledge.reader import SnapshotFactsResult, SnapshotReader
from insurance_harness.knowledge.release_guard_ddl_018 import (
    SQLITE_CREATE_GUARDS,
    SQLITE_DROP_GUARDS,
)
from insurance_harness.knowledge.tables import (
    ChangeSet,
    Claim,
    ClaimRevision,
    CurrentRelease,
    PublishAttempt,
    ReconciliationJob,
    ReleaseOperation,
    ReleaseSnapshot,
)
from tests.support.release_018 import (
    NOW,
    release_claim,
    release_product,
    release_scope,
)


class _RollbackWiki:
    def __init__(self) -> None:
        self.pages: dict[tuple[str, str], WeKnoraWikiPage] = {}
        self.fail_slug: str | None = None
        self.mutations = 0

    async def get_wiki_page(self, kb_id: str, slug: str) -> WeKnoraWikiPage:
        page = self.pages.get((kb_id, slug))
        if page is None:
            raise WeKnoraClientError(404, "missing")
        return page

    async def create_wiki_page(
        self, kb_id: str, page: WeKnoraWikiPage
    ) -> WeKnoraWikiPage:
        self.mutations += 1
        if page.slug == self.fail_slug:
            raise WeKnoraTransientError("rollback page failure")
        self.pages[(kb_id, page.slug)] = page
        return page

    async def update_wiki_page(
        self, kb_id: str, page: WeKnoraWikiPage
    ) -> WeKnoraWikiPage:
        self.mutations += 1
        if page.slug == self.fail_slug:
            raise WeKnoraTransientError("rollback page failure")
        self.pages[(kb_id, page.slug)] = page
        return page

    async def delete_wiki_page(self, kb_id: str, slug: str) -> None:
        self.mutations += 1
        if slug == self.fail_slug:
            raise WeKnoraTransientError("rollback page failure")
        self.pages.pop((kb_id, slug), None)


def _factory(session: Session) -> Callable[[], Session]:
    bind = session.get_bind()
    assert isinstance(bind, Engine)
    return make_session_factory(bind)


def _seed(session: Session) -> tuple[KnowledgeScope, ProductVersion]:
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
    return scope, version_b


def _revise_claims(factory: Callable[[], Session]) -> None:
    with factory() as session:
        for claim in session.scalars(select(Claim).order_by(Claim.id)):
            claim.current_revision = 2
            claim.value = {"text": "180天"}
            session.add(
                ClaimRevision(
                    claim_id=claim.id,
                    revision_no=2,
                    before={"value": {"text": "90天"}},
                    after={"value": claim.value},
                    actor="test",
                    at=NOW,
                )
            )
        session.commit()


async def _published_v1_v2(
    session: Session,
) -> tuple[KnowledgeScope, _RollbackWiki, ReleasePublisher, str, str]:
    scope, version_b = _seed(session)
    factory = _factory(session)
    wiki = _RollbackWiki()
    publisher = ReleasePublisher(factory, wiki, now=lambda: NOW)
    v1 = await publisher.publish_product_version(
        scope,
        product_version_id=version_b.id,
        label="release-v1",
    )
    _revise_claims(factory)
    v2 = await publisher.publish_product_version(
        scope,
        product_version_id=version_b.id,
        label="release-v2",
    )
    return scope, wiki, publisher, v1.snapshot_id, v2.snapshot_id


async def test_r4_1_r6_1_version_one_rollback_restores_reader_and_wiki(
    kb_session: Session,
) -> None:
    scope, wiki, publisher, v1_id, v2_id = await _published_v1_v2(kb_session)

    result = await publisher.rollback_to_snapshot(scope, snapshot_id=v1_id)

    assert result.snapshot_id == v1_id
    assert all(
        page.page_metadata and page.page_metadata["snapshot_id"] == v1_id
        for page in wiki.pages.values()
    )
    kb_session.expire_all()
    pointer = kb_session.get(CurrentRelease, (scope.space_id, "current"))
    assert pointer is not None and pointer.snapshot_id == v1_id
    snapshots = list(kb_session.scalars(select(ReleaseSnapshot)))
    assert len(snapshots) == 2
    assert {row.id for row in snapshots} == {v1_id, v2_id}
    assert all(row.status == "published" for row in snapshots)
    rollback = kb_session.scalar(
        select(ReleaseOperation).where(ReleaseOperation.kind == "rollback")
    )
    assert rollback is not None and rollback.status == "succeeded"
    assert kb_session.scalar(select(func.count()).select_from(ChangeSet)) == 1
    readback = SnapshotReader(_factory(kb_session)).current(scope)
    assert isinstance(readback, SnapshotFactsResult)
    assert readback.snapshot_id == v1_id
    assert {fact.product_code for fact in readback.facts} == {"A", "B"}
    assert all(fact.value == {"text": "90天"} for fact in readback.facts)
    assert all(
        fact.evidence and fact.evidence[0].quote.endswith("=90天")
        for fact in readback.facts
    )


async def test_r4_2_failed_rollback_keeps_current_and_retry_reuses_operation(
    kb_session: Session,
) -> None:
    scope, wiki, publisher, v1_id, v2_id = await _published_v1_v2(kb_session)
    wiki.fail_slug = "product/B/V1/overview"

    with pytest.raises(WeKnoraTransientError, match="rollback page failure"):
        await publisher.rollback_to_snapshot(scope, snapshot_id=v1_id)

    kb_session.expire_all()
    pointer = kb_session.get(CurrentRelease, (scope.space_id, "current"))
    assert pointer is not None and pointer.snapshot_id == v2_id
    operation = kb_session.scalar(
        select(ReleaseOperation).where(ReleaseOperation.kind == "rollback")
    )
    assert operation is not None and operation.status == "failed"
    original_digest = operation.plan_digest
    snapshot = kb_session.get(ReleaseSnapshot, v1_id)
    assert snapshot is not None and snapshot.status == "published"
    assert kb_session.scalar(select(func.count()).select_from(ReconciliationJob)) == 1
    change_set = kb_session.scalar(
        select(ChangeSet).where(ChangeSet.source_kind == "rollback")
    )
    assert change_set is not None and change_set.status != "applied"

    wiki.fail_slug = None
    retried = await publisher.retry_operation(scope, operation_id=operation.id)

    assert retried.snapshot_id == v1_id
    kb_session.expire_all()
    operation = kb_session.get(ReleaseOperation, operation.id)
    assert operation is not None and operation.status == "succeeded"
    assert operation.retry_no == 1 and operation.plan_digest == original_digest
    assert kb_session.scalar(select(func.count()).select_from(ReleaseSnapshot)) == 2
    pointer = kb_session.get(CurrentRelease, (scope.space_id, "current"))
    assert pointer is not None and pointer.snapshot_id == v1_id


async def test_r1_4_legacy_rollback_rejected_before_wiki_or_operation(
    kb_session: Session,
) -> None:
    scope, wiki, publisher, v1_id, _v2_id = await _published_v1_v2(kb_session)
    with _factory(kb_session)() as session:
        snapshot = session.get(ReleaseSnapshot, v1_id)
        assert snapshot is not None
        snapshot.read_model_version = 0
        session.commit()
    calls_before = wiki.mutations

    with pytest.raises(ScopeViolation, match="release target unavailable"):
        await publisher.rollback_to_snapshot(scope, snapshot_id=v1_id)

    assert wiki.mutations == calls_before
    kb_session.expire_all()
    assert (
        kb_session.scalar(
            select(func.count())
            .select_from(ReleaseOperation)
            .where(ReleaseOperation.kind == "rollback")
        )
        == 0
    )


async def test_r4_3_no_current_reconciliation_cleans_only_source_plan_slugs(
    kb_session: Session,
) -> None:
    scope, version_b = _seed(kb_session)
    wiki = _RollbackWiki()
    wiki.fail_slug = "product/B/V1/overview"
    publisher = ReleasePublisher(_factory(kb_session), wiki, now=lambda: NOW)
    with pytest.raises(WeKnoraTransientError):
        await publisher.publish_product_version(
            scope,
            product_version_id=version_b.id,
            label="release-failed",
        )
    kb_session.expire_all()
    source = kb_session.scalar(
        select(ReleaseOperation).where(ReleaseOperation.kind == "publish")
    )
    assert source is not None and source.status == "failed"
    assert len(wiki.pages) == 1
    wiki.fail_slug = None

    result = await publisher.reconcile_operation(
        scope, source_operation_id=source.id
    )

    assert result.current_snapshot_id is None
    assert wiki.pages == {}
    kb_session.expire_all()
    child = kb_session.get(ReleaseOperation, result.operation_id)
    assert child is not None and child.kind == "reconcile"
    assert child.parent_operation_id == source.id and child.status == "succeeded"
    job = kb_session.scalar(select(ReconciliationJob))
    assert job is not None and job.status == "succeeded"
    await publisher.publish_product_version(
        scope,
        product_version_id=version_b.id,
        label="release-after-reconcile",
    )
    kb_session.expire_all()
    operation_count = kb_session.scalar(
        select(func.count()).select_from(ReleaseOperation)
    )
    mutations = wiki.mutations

    repeated = await publisher.reconcile_operation(
        scope, source_operation_id=source.id
    )
    assert repeated.operation_id == result.operation_id
    assert repeated.current_snapshot_id == result.current_snapshot_id is None
    assert repeated.pages == result.pages == ()
    assert wiki.mutations == mutations
    assert (
        kb_session.scalar(select(func.count()).select_from(ReleaseOperation))
        == operation_count
    )


async def test_r4_3_failed_reconcile_reuses_child_plan_then_replays_current(
    kb_session: Session,
) -> None:
    scope, wiki, publisher, _v1_id, v2_id = await _published_v1_v2(kb_session)
    wiki.fail_slug = "product/B/V1/overview"
    with _factory(kb_session)() as session:
        version_b_id = session.scalar(
            select(Claim.product_version_id).where(Claim.id == "claim-b")
        )
        assert version_b_id is not None
    with pytest.raises(WeKnoraTransientError):
        await publisher.publish_product_version(
            scope,
            product_version_id=version_b_id,
            label="release-v3-failed",
        )
    kb_session.expire_all()
    source = kb_session.scalar(
        select(ReleaseOperation)
        .where(ReleaseOperation.kind == "publish", ReleaseOperation.status == "failed")
        .order_by(ReleaseOperation.created_at.desc())
    )
    assert source is not None

    with pytest.raises(WeKnoraTransientError, match="rollback page failure"):
        await publisher.reconcile_operation(
            scope, source_operation_id=source.id
        )
    kb_session.expire_all()
    child = kb_session.scalar(
        select(ReleaseOperation).where(ReleaseOperation.kind == "reconcile")
    )
    assert child is not None and child.status == "failed"
    child_id = child.id
    digest = child.plan_digest

    wiki.fail_slug = None
    result = await publisher.reconcile_operation(
        scope, source_operation_id=source.id
    )

    assert result.operation_id == child_id
    assert result.current_snapshot_id == v2_id
    assert all(
        page.page_metadata and page.page_metadata["snapshot_id"] == v2_id
        for page in wiki.pages.values()
    )
    kb_session.expire_all()
    child = kb_session.get(ReleaseOperation, child_id)
    assert child is not None and child.status == "succeeded"
    assert child.retry_no == 1 and child.plan_digest == digest
    pointer = kb_session.get(CurrentRelease, (scope.space_id, "current"))
    assert pointer is not None and pointer.snapshot_id == v2_id


async def test_r3_1_r3_3_expired_reconcile_child_requeues_original_job_only(
    kb_session: Session,
) -> None:
    scope, version_b = _seed(kb_session)
    wiki = _RollbackWiki()
    wiki.fail_slug = "product/B/V1/overview"
    publisher = ReleasePublisher(_factory(kb_session), wiki, now=lambda: NOW)
    with pytest.raises(WeKnoraTransientError):
        await publisher.publish_product_version(
            scope,
            product_version_id=version_b.id,
            label="release-source-failed",
        )
    kb_session.expire_all()
    source = kb_session.scalar(
        select(ReleaseOperation).where(ReleaseOperation.kind == "publish")
    )
    assert source is not None

    wiki.fail_slug = "product/A/V1/overview"
    with pytest.raises(WeKnoraTransientError):
        await publisher.reconcile_operation(
            scope, source_operation_id=source.id
        )
    with _factory(kb_session)() as session:
        child = session.scalar(
            select(ReleaseOperation).where(ReleaseOperation.kind == "reconcile")
        )
        job = session.scalar(select(ReconciliationJob))
        assert child is not None and job is not None
        child.status = "running"
        child.lease_expires_at = NOW - timedelta(seconds=1)
        job.status = "running"
        session.commit()
        child_id = child.id
        job_id = job.id

    assert await publisher.recover_expired(scope) == (child_id,)

    kb_session.expire_all()
    jobs = list(kb_session.scalars(select(ReconciliationJob)))
    assert [job.id for job in jobs] == [job_id]
    assert jobs[0].source_operation_id == source.id
    assert jobs[0].reconcile_operation_id == child_id
    assert jobs[0].status == "failed"

    wiki.fail_slug = None
    result = await publisher.reconcile_operation(
        scope, source_operation_id=source.id
    )
    assert result.operation_id == child_id


async def test_r4_3_r4_4_first_018_failure_restores_exact_legacy_current(
    kb_session: Session,
) -> None:
    scope, version_b = _seed(kb_session)
    legacy_page = RenderedPage(
        slug="product/A/V1/overview",
        title="legacy A",
        content="# legacy A",
        page_metadata={"snapshot_id": "snapshot-legacy"},
    )
    for ddl in SQLITE_DROP_GUARDS:
        kb_session.execute(text(ddl))
    kb_session.add(
        ReleaseSnapshot(
            id="snapshot-legacy",
            space_id=scope.space_id,
            label="legacy-release",
            rendered_pages=[legacy_page.model_dump(mode="json")],
            status="published",
            read_model_version=0,
            published_by="legacy",
        )
    )
    kb_session.flush()
    kb_session.add(
        CurrentRelease(
            space_id=scope.space_id,
            id="current",
            snapshot_id="snapshot-legacy",
        )
    )
    kb_session.commit()
    for ddl in SQLITE_CREATE_GUARDS:
        kb_session.execute(text(ddl))
    kb_session.commit()
    wiki = _RollbackWiki()
    wiki.pages[(scope.wiki_kb_id, legacy_page.slug)] = WeKnoraWikiPage(
        **legacy_page.model_dump(mode="python")
    )
    wiki.fail_slug = "product/B/V1/overview"
    publisher = ReleasePublisher(_factory(kb_session), wiki, now=lambda: NOW)

    with pytest.raises(WeKnoraTransientError):
        await publisher.publish_product_version(
            scope,
            product_version_id=version_b.id,
            label="release-first-018-failed",
        )
    kb_session.expire_all()
    source = kb_session.scalar(
        select(ReleaseOperation).where(ReleaseOperation.kind == "publish")
    )
    assert source is not None and source.status == "failed"

    wiki.fail_slug = None
    result = await publisher.reconcile_operation(
        scope, source_operation_id=source.id
    )

    assert result.current_snapshot_id == "snapshot-legacy"
    assert set(wiki.pages) == {(scope.wiki_kb_id, legacy_page.slug)}
    restored = wiki.pages[(scope.wiki_kb_id, legacy_page.slug)]
    assert restored.page_metadata == {"snapshot_id": "snapshot-legacy"}


async def test_r3_3_changed_current_creates_reconcile_successor_child(
    kb_session: Session,
) -> None:
    scope, wiki, publisher, v1_id, v2_id = await _published_v1_v2(kb_session)
    with _factory(kb_session)() as session:
        version_b_id = session.scalar(
            select(Claim.product_version_id).where(Claim.id == "claim-b")
        )
        assert version_b_id is not None
    wiki.fail_slug = "product/B/V1/overview"
    with pytest.raises(WeKnoraTransientError):
        await publisher.publish_product_version(
            scope,
            product_version_id=version_b_id,
            label="release-successor-source",
        )
    kb_session.expire_all()
    source = kb_session.scalar(
        select(ReleaseOperation).where(
            ReleaseOperation.kind == "publish",
            ReleaseOperation.status == "failed",
        )
    )
    assert source is not None
    with pytest.raises(WeKnoraTransientError):
        await publisher.reconcile_operation(
            scope, source_operation_id=source.id
        )
    kb_session.expire_all()
    first_child = kb_session.scalar(
        select(ReleaseOperation).where(ReleaseOperation.kind == "reconcile")
    )
    assert first_child is not None and first_child.base_snapshot_id == v2_id

    wiki.fail_slug = None
    await publisher.rollback_to_snapshot(scope, snapshot_id=v1_id)
    result = await publisher.reconcile_operation(
        scope, source_operation_id=source.id
    )

    assert result.operation_id != first_child.id
    assert result.current_snapshot_id == v1_id
    kb_session.expire_all()
    successor = kb_session.get(ReleaseOperation, result.operation_id)
    assert successor is not None and successor.status == "succeeded"
    assert successor.parent_operation_id == source.id
    assert successor.previous_operation_id == first_child.id
    old_child = kb_session.get(ReleaseOperation, first_child.id)
    assert old_child is not None and old_child.status == "failed"
    job = kb_session.scalar(select(ReconciliationJob))
    assert job is not None and job.reconcile_operation_id == successor.id


async def test_r4_3_failed_plan_removes_new_and_historical_noncurrent_slugs(
    kb_session: Session,
) -> None:
    scope = release_scope(kb_session)
    _, version_a = release_product(kb_session, scope, code="A")
    _, version_b = release_product(kb_session, scope, code="B")
    _, version_c = release_product(kb_session, scope, code="C")
    release_claim(
        kb_session,
        scope,
        version_a,
        claim_id="claim-a",
        predicate="waiting_period",
    )
    kb_session.commit()
    factory = _factory(kb_session)
    wiki = _RollbackWiki()
    publisher = ReleasePublisher(factory, wiki, now=lambda: NOW)
    v1 = await publisher.publish_product_version(
        scope,
        product_version_id=version_a.id,
        label="release-current-a",
    )
    with factory() as session:
        stored_b = session.get(ProductVersion, version_b.id)
        stored_c = session.get(ProductVersion, version_c.id)
        assert stored_b is not None and stored_c is not None
        release_claim(
            session,
            scope,
            stored_b,
            claim_id="claim-b",
            predicate="hesitation_period",
        )
        release_claim(
            session,
            scope,
            stored_c,
            claim_id="claim-c",
            predicate="coverage_limit",
        )
        session.commit()
    historical_slug = "product/B/V1/overview"
    wiki.pages[(scope.wiki_kb_id, historical_slug)] = WeKnoraWikiPage(
        slug=historical_slug,
        title="historical B",
        content="# historical B",
        page_metadata={
            "managed_by": "insurance-harness",
            "space_id": scope.space_id,
            "snapshot_id": "historical-noncurrent",
        },
    )
    wiki.fail_slug = "product/C/V1/overview"
    with pytest.raises(WeKnoraTransientError):
        await publisher.publish_product_version(
            scope,
            product_version_id=version_c.id,
            label="release-failed-abc",
        )
    kb_session.expire_all()
    source = kb_session.scalar(
        select(ReleaseOperation).where(
            ReleaseOperation.kind == "publish",
            ReleaseOperation.status == "failed",
        )
    )
    assert source is not None

    wiki.fail_slug = None
    result = await publisher.reconcile_operation(
        scope, source_operation_id=source.id
    )

    assert result.current_snapshot_id == v1.snapshot_id
    assert set(wiki.pages) == {
        (scope.wiki_kb_id, "product/A/V1/overview")
    }


async def test_r6_3_same_label_and_slug_are_isolated_across_spaces(
    kb_session: Session,
) -> None:
    scope_a = release_scope(kb_session, "a")
    scope_b = release_scope(kb_session, "b")
    _, version_a = release_product(kb_session, scope_a, code="SAME")
    _, version_b = release_product(kb_session, scope_b, code="SAME")
    release_claim(
        kb_session,
        scope_a,
        version_a,
        claim_id="claim-space-a",
        predicate="waiting_period",
    )
    release_claim(
        kb_session,
        scope_b,
        version_b,
        claim_id="claim-space-b",
        predicate="waiting_period",
    )
    kb_session.commit()
    factory = _factory(kb_session)
    wiki = _RollbackWiki()
    publisher = ReleasePublisher(factory, wiki, now=lambda: NOW)
    v1_a = await publisher.publish_product_version(
        scope_a, product_version_id=version_a.id, label="same-v1"
    )
    await publisher.publish_product_version(
        scope_b, product_version_id=version_b.id, label="same-v1"
    )
    _revise_claims(factory)
    await publisher.publish_product_version(
        scope_a, product_version_id=version_a.id, label="same-v2"
    )
    v2_b = await publisher.publish_product_version(
        scope_b, product_version_id=version_b.id, label="same-v2"
    )
    with factory() as session:
        b_attempts_before = session.scalar(
            select(func.count())
            .select_from(PublishAttempt)
            .where(PublishAttempt.space_id == scope_b.space_id)
        )
        b_jobs_before = session.scalar(
            select(func.count())
            .select_from(ReconciliationJob)
            .where(ReconciliationJob.space_id == scope_b.space_id)
        )
    slug = "product/SAME/V1/overview"
    b_page_before = wiki.pages[(scope_b.wiki_kb_id, slug)]

    await publisher.rollback_to_snapshot(scope_a, snapshot_id=v1_a.snapshot_id)

    with factory() as session:
        pointer_b = session.get(CurrentRelease, (scope_b.space_id, "current"))
        assert pointer_b is not None and pointer_b.snapshot_id == v2_b.snapshot_id
        assert (
            session.scalar(
                select(func.count())
                .select_from(PublishAttempt)
                .where(PublishAttempt.space_id == scope_b.space_id)
            )
            == b_attempts_before
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ReconciliationJob)
                .where(ReconciliationJob.space_id == scope_b.space_id)
            )
            == b_jobs_before
        )
    assert wiki.pages[(scope_b.wiki_kb_id, slug)] == b_page_before
    b_metadata = wiki.pages[(scope_b.wiki_kb_id, slug)].page_metadata
    assert b_metadata is not None
    assert b_metadata["snapshot_id"] == v2_b.snapshot_id


async def test_r6_2_reconcile_then_same_plan_retry_publishes_original_target(
    kb_session: Session,
) -> None:
    scope, version_b = _seed(kb_session)
    factory = _factory(kb_session)
    wiki = _RollbackWiki()
    publisher = ReleasePublisher(factory, wiki, now=lambda: NOW)
    v1 = await publisher.publish_product_version(
        scope, product_version_id=version_b.id, label="release-r6-v1"
    )
    _revise_claims(factory)
    wiki.fail_slug = "product/B/V1/overview"
    with pytest.raises(WeKnoraTransientError):
        await publisher.publish_product_version(
            scope,
            product_version_id=version_b.id,
            label="release-r6-v2-failed",
        )
    kb_session.expire_all()
    source = kb_session.scalar(
        select(ReleaseOperation).where(
            ReleaseOperation.kind == "publish",
            ReleaseOperation.status == "failed",
        )
    )
    assert source is not None
    target_id = source.target_snapshot_id
    digest = source.plan_digest
    assert target_id is not None

    wiki.fail_slug = None
    reconciled = await publisher.reconcile_operation(
        scope, source_operation_id=source.id
    )
    assert reconciled.current_snapshot_id == v1.snapshot_id
    assert all(
        page.page_metadata and page.page_metadata["snapshot_id"] == v1.snapshot_id
        for page in wiki.pages.values()
    )

    retried = await publisher.retry_operation(scope, operation_id=source.id)

    assert retried.snapshot_id == target_id
    kb_session.expire_all()
    source = kb_session.get(ReleaseOperation, source.id)
    assert source is not None and source.status == "succeeded"
    assert source.retry_no == 1 and source.plan_digest == digest
    pointer = kb_session.get(CurrentRelease, (scope.space_id, "current"))
    assert pointer is not None and pointer.snapshot_id == target_id
