"""Legacy staging/test-only WeKnora publisher (changes 007/016/018).

This module preserves the 018 recovery state machine for characterization, staging,
and tests. It is not a production release authority and must not be package-exported.
Production release requires OpenSpec 029 approval/CAS serving contracts and the P-1
capability boundary.
"""

import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.adapters.weknora.errors import WeKnoraClientError
from insurance_harness.adapters.weknora.models import WeKnoraWikiPage
from insurance_harness.db.base import utcnow
from insurance_harness.db.models import InsuranceProduct, ProductVersion
from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
    require_current_scope,
)
from insurance_harness.knowledge.pages import (
    RenderedPage,
    render_snapshot_pages,
)
from insurance_harness.knowledge.reconcile import ReconcileResult
from insurance_harness.knowledge.release_plan import (
    LegacyPageOwnership,
    PageOwnershipCollision,
    PublishAction,
    PublishPlan,
    ReleasePlanExecutor,
    WikiPageClient,
)
from insurance_harness.knowledge.snapshots import (
    SnapshotFactView,
    build_snapshot_facts,
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
    SnapshotClaim,
    SnapshotFact,
)
from insurance_harness.schemas import SchemaRegistry


class PublishResult(BaseModel):
    snapshot_id: str
    snapshot_label: str
    pages: list[RenderedPage] = Field(default_factory=list)


class RollbackResult(BaseModel):
    snapshot_id: str
    change_set_id: str
    pages: list[RenderedPage] = Field(default_factory=list)


def _page_to_wiki(page: RenderedPage) -> WeKnoraWikiPage:
    return WeKnoraWikiPage(
        slug=page.slug,
        title=page.title,
        status="published",  # 只发布 published；候选/草稿不出 Harness（03 §7）
        content=page.content,
        source_refs=page.source_refs,
        chunk_refs=page.chunk_refs,
        page_metadata=page.page_metadata,
    )


async def _upsert_page(
    client: WeKnoraClient,
    scope: KnowledgeScope,
    page: RenderedPage,
) -> None:
    """已存在 → update，404 → create（上游 last-write-wins，客户端 slug 串行化兜底）。"""
    wiki_page = _page_to_wiki(page)
    try:
        await client.get_wiki_page(scope.wiki_kb_id, page.slug)
    except WeKnoraClientError as exc:
        if exc.status_code != 404:
            raise
        await client.create_wiki_page(scope.wiki_kb_id, wiki_page)
        return
    await client.update_wiki_page(scope.wiki_kb_id, wiki_page)


def _validate_scope(session: Session, scope: KnowledgeScope) -> None:
    require_current_scope(session, scope)


def _require_scoped_product_version(
    session: Session,
    scope: KnowledgeScope,
    product_version_id: str,
) -> tuple[ProductVersion, InsuranceProduct]:
    row = session.execute(
        select(ProductVersion, InsuranceProduct)
        .join(
            InsuranceProduct,
            (InsuranceProduct.id == ProductVersion.product_id)
            & (InsuranceProduct.space_id == ProductVersion.space_id),
        )
        .where(
            ProductVersion.id == product_version_id,
            ProductVersion.space_id == scope.space_id,
            InsuranceProduct.space_id == scope.space_id,
        )
    ).one_or_none()
    if row is None:
        raise ScopeViolation("scope mismatch")
    return row[0], row[1]


def _require_scoped_snapshot(
    session: Session,
    scope: KnowledgeScope,
    snapshot_id: str,
) -> ReleaseSnapshot:
    snapshot = session.execute(
        select(ReleaseSnapshot).where(
            ReleaseSnapshot.id == snapshot_id,
            ReleaseSnapshot.space_id == scope.space_id,
        )
    ).scalar_one_or_none()
    if snapshot is None:
        raise ScopeViolation("scope mismatch")
    return snapshot


def _require_label_available(
    session: Session,
    scope: KnowledgeScope,
    label: str,
) -> None:
    existing = session.execute(
        select(ReleaseSnapshot.id).where(
            ReleaseSnapshot.space_id == scope.space_id,
            ReleaseSnapshot.label == label,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError("release label is unavailable")


def _validate_text(value: str, *, max_length: int, error: str) -> None:
    if not value.strip() or len(value) > max_length:
        raise ValueError(error)


def _validate_publish_metadata(label: str, published_by: str) -> None:
    _validate_text(label, max_length=128, error="publish metadata is unavailable")
    _validate_text(
        published_by,
        max_length=128,
        error="publish metadata is unavailable",
    )


def _validate_rollback_metadata(actor: str, reason: str) -> None:
    _validate_text(actor, max_length=128, error="rollback metadata is unavailable")
    _validate_text(reason, max_length=64, error="rollback metadata is unavailable")


def current_snapshot_id(session: Session, scope: KnowledgeScope) -> str | None:
    _validate_scope(session, scope)
    pointer = session.get(CurrentRelease, (scope.space_id, "current"))
    if pointer is None:
        return None
    snapshot_id = session.execute(
        select(ReleaseSnapshot.id).where(
            ReleaseSnapshot.space_id == scope.space_id,
            ReleaseSnapshot.id == pointer.snapshot_id,
        )
    ).scalar_one_or_none()
    if snapshot_id is None:
        raise ScopeViolation("scope mismatch")
    return snapshot_id


def snapshot_claim_set(
    session: Session,
    scope: KnowledgeScope,
    snapshot_id: str,
) -> list[tuple[str, int]]:
    _validate_scope(session, scope)
    _require_scoped_snapshot(session, scope, snapshot_id)
    rows = list(
        session.execute(
            select(SnapshotClaim).where(
                SnapshotClaim.space_id == scope.space_id,
                SnapshotClaim.snapshot_id == snapshot_id,
            )
        ).scalars()
    )
    claim_ids = {row.claim_id for row in rows}
    scoped_claim_ids = (
        set(
            session.execute(
                select(Claim.id).where(
                    Claim.space_id == scope.space_id,
                    Claim.id.in_(claim_ids),
                )
            ).scalars()
        )
        if claim_ids
        else set()
    )
    revision_pairs = (
        set(
            session.execute(
                select(ClaimRevision.claim_id, ClaimRevision.revision_no)
                .join(Claim, Claim.id == ClaimRevision.claim_id)
                .where(
                    Claim.space_id == scope.space_id,
                    ClaimRevision.claim_id.in_(claim_ids),
                )
            ).all()
        )
        if claim_ids
        else set()
    )
    if scoped_claim_ids != claim_ids or any(
        (row.claim_id, row.revision_no) not in revision_pairs for row in rows
    ):
        raise ScopeViolation("scope mismatch")
    return [(r.claim_id, r.revision_no) for r in rows]


def default_snapshot_label(session: Session, scope: KnowledgeScope) -> str:
    """如 2026-07-15-r1（03 §5.2 示例）；同日多次发布递增 rN。"""
    _validate_scope(session, scope)
    today = utcnow().date().isoformat()
    existing = session.execute(
        select(ReleaseSnapshot.label).where(
            ReleaseSnapshot.space_id == scope.space_id,
            ReleaseSnapshot.label.like(f"{today}-r%"),
        )
    ).scalars().all()
    revisions = [
        int(label.removeprefix(f"{today}-r"))
        for label in existing
        if label.removeprefix(f"{today}-r").isdigit()
    ]
    return f"{today}-r{max(revisions, default=0) + 1}"


class ReleasePublisher:
    """Legacy staging/test-only 018 service-owned, pointer-last release saga."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        wiki_client: WikiPageClient,
        *,
        lease_duration: timedelta = timedelta(minutes=5),
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._session_factory = session_factory
        with session_factory() as session:
            lock_namespace = session.get_bind()
        self._executor = ReleasePlanExecutor(
            wiki_client, lock_namespace=lock_namespace
        )
        self._lease_duration = lease_duration
        self._now = now

    @staticmethod
    def _current_id(session: Session, space_id: str) -> str | None:
        return session.scalar(
            select(CurrentRelease.snapshot_id).where(
                CurrentRelease.space_id == space_id
            )
        )

    @staticmethod
    def _pages(snapshot: ReleaseSnapshot | None) -> tuple[RenderedPage, ...]:
        if snapshot is None:
            return ()
        try:
            return tuple(
                RenderedPage.model_validate(raw)
                for raw in (snapshot.rendered_pages or [])
            )
        except (TypeError, ValidationError) as exc:
            raise ScopeViolation("scope mismatch") from exc

    @staticmethod
    def _plan(
        *,
        base_snapshot_id: str | None,
        target_snapshot_id: str,
        current_pages: tuple[RenderedPage, ...],
        target_pages: tuple[RenderedPage, ...],
    ) -> PublishPlan:
        old_by_slug = {page.slug: page for page in current_pages}
        new_by_slug = {page.slug: page for page in target_pages}
        actions = tuple(
            PublishAction(kind="upsert", slug=slug, page=new_by_slug[slug])
            for slug in sorted(new_by_slug)
        ) + tuple(
            PublishAction(kind="delete", slug=slug)
            for slug in sorted(set(old_by_slug) - set(new_by_slug))
        )
        compensation = tuple(
            PublishAction(kind="upsert", slug=slug, page=old_by_slug[slug])
            for slug in sorted(old_by_slug)
        ) + tuple(
            PublishAction(kind="delete", slug=slug)
            for slug in sorted(set(new_by_slug) - set(old_by_slug))
        )
        return PublishPlan(
            base_snapshot_id=base_snapshot_id,
            target_snapshot_id=target_snapshot_id,
            actions=actions,
            compensation_actions=compensation,
        )

    @staticmethod
    def _snapshot_fact(row: SnapshotFactView) -> SnapshotFact:
        return SnapshotFact(
            id=str(uuid.uuid4()),
            space_id=row.space_id,
            snapshot_id=row.snapshot_id,
            claim_id=row.claim_id,
            revision_no=row.revision_no,
            product_id=row.product_id,
            product_version_id=row.product_version_id,
            product_code=row.product_code,
            product_name=row.product_name,
            version_label=row.version_label,
            predicate=row.predicate,
            field_name=row.field_name,
            field_group=row.field_group,
            value_state=row.value_state,
            value=row.value,
            effective_from=row.effective_from,
            effective_to=row.effective_to,
            confidence=row.confidence,
            schema_version=row.schema_version,
            evidence=[evidence.model_dump(mode="json") for evidence in row.evidence],
        )

    def _build_operation(
        self,
        scope: KnowledgeScope,
        *,
        product_version_id: str,
        label: str,
        published_by: str,
        notes: str | None,
        registry: SchemaRegistry | None,
        field_names: Mapping[str, str] | None,
        doc_titles: Mapping[str, str] | None,
    ) -> str:
        _validate_publish_metadata(label, published_by)
        now = self._now()
        with self._session_factory() as session:
            require_current_scope(session, scope)
            _require_scoped_product_version(session, scope, product_version_id)
            _require_label_available(session, scope, label)
            snapshot_id = str(uuid.uuid4())
            facts = build_snapshot_facts(
                session,
                scope,
                snapshot_id=snapshot_id,
                registry=registry,
                field_names=field_names,
                doc_titles=doc_titles,
            )
            pages = render_snapshot_pages(
                facts,
                space_id=scope.space_id,
                snapshot_id=snapshot_id,
                compiled_at=now,
            )
            base_snapshot_id = self._current_id(session, scope.space_id)
            base_snapshot = (
                session.scalar(
                    select(ReleaseSnapshot).where(
                        ReleaseSnapshot.id == base_snapshot_id,
                        ReleaseSnapshot.space_id == scope.space_id,
                    )
                )
                if base_snapshot_id is not None
                else None
            )
            if base_snapshot_id is not None and base_snapshot is None:
                raise ScopeViolation("scope mismatch")
            current_pages = self._pages(base_snapshot)
            plan = self._plan(
                base_snapshot_id=base_snapshot_id,
                target_snapshot_id=snapshot_id,
                current_pages=current_pages,
                target_pages=pages,
            )
            snapshot = ReleaseSnapshot(
                id=snapshot_id,
                space_id=scope.space_id,
                label=label,
                rendered_pages=[page.model_dump(mode="json") for page in pages],
                status="building",
                read_model_version=1,
                projection_frozen_at=None,
                published_at=None,
                published_by=published_by,
                notes=notes,
            )
            session.add(snapshot)
            session.flush()
            session.add_all(
                [self._snapshot_fact(fact) for fact in facts]
            )
            operation = ReleaseOperation(
                id=str(uuid.uuid4()),
                space_id=scope.space_id,
                kind="publish",
                status="building",
                base_snapshot_id=base_snapshot_id,
                target_snapshot_id=snapshot.id,
                publish_plan=plan.model_dump(mode="json"),
                plan_digest=plan.digest,
                plan_frozen_at=None,
                retry_no=0,
                lease_expires_at=now + self._lease_duration,
                heartbeat_at=now,
                actor=published_by,
                reason=notes,
            )
            session.add(operation)
            session.flush()
            snapshot.projection_frozen_at = now
            operation.plan_frozen_at = now
            session.commit()
            return operation.id

    def _load_operation(
        self, session: Session, scope: KnowledgeScope, operation_id: str
    ) -> tuple[ReleaseOperation, ReleaseSnapshot, PublishPlan]:
        require_current_scope(session, scope)
        operation = session.scalar(
            select(ReleaseOperation).where(
                ReleaseOperation.id == operation_id,
                ReleaseOperation.space_id == scope.space_id,
            )
        )
        if operation is None or operation.target_snapshot_id is None:
            raise ScopeViolation("scope mismatch")
        snapshot = session.scalar(
            select(ReleaseSnapshot).where(
                ReleaseSnapshot.id == operation.target_snapshot_id,
                ReleaseSnapshot.space_id == scope.space_id,
            )
        )
        if snapshot is None or operation.publish_plan is None:
            raise ScopeViolation("scope mismatch")
        try:
            plan = PublishPlan.model_validate(operation.publish_plan)
        except ValidationError as exc:
            raise ScopeViolation("scope mismatch") from exc
        if operation.plan_digest != plan.digest:
            raise ScopeViolation("scope mismatch")
        return operation, snapshot, plan

    def _activate(self, scope: KnowledgeScope, operation_id: str) -> PublishPlan:
        now = self._now()
        with self._session_factory() as session:
            operation, snapshot, plan = self._load_operation(
                session, scope, operation_id
            )
            snapshot_ready = (
                snapshot.status == "building"
                if operation.kind == "publish"
                else snapshot.status == "published"
                and snapshot.read_model_version == 1
            )
            if operation.status != "building" or not snapshot_ready:
                raise ScopeViolation("release operation unavailable")
            if self._current_id(session, scope.space_id) != operation.base_snapshot_id:
                operation.status = "failed"
                if operation.kind == "publish":
                    snapshot.status = "failed"
                session.commit()
                raise ScopeViolation("release base changed")
            operation.status = "running"
            operation.heartbeat_at = now
            operation.lease_expires_at = now + self._lease_duration
            if operation.kind == "publish":
                snapshot.status = "publishing"
            session.commit()
            return plan

    def _legacy_ownership(
        self, scope: KnowledgeScope, base_snapshot_id: str | None
    ) -> LegacyPageOwnership | None:
        if base_snapshot_id is None:
            return None
        with self._session_factory() as session:
            require_current_scope(session, scope)
            snapshot = session.scalar(
                select(ReleaseSnapshot).where(
                    ReleaseSnapshot.id == base_snapshot_id,
                    ReleaseSnapshot.space_id == scope.space_id,
                )
            )
            if snapshot is None or snapshot.read_model_version != 0:
                return None
            return LegacyPageOwnership(
                snapshot_id=snapshot.id,
                slugs=frozenset(page.slug for page in self._pages(snapshot)),
            )

    def _attempt_started(
        self,
        scope: KnowledgeScope,
        operation_id: str,
        retry_no: int,
        action_no: int,
        action: PublishAction,
    ) -> None:
        now = self._now()
        with self._session_factory() as session:
            operation, _snapshot, _plan = self._load_operation(
                session, scope, operation_id
            )
            session.add(
                PublishAttempt(
                    id=str(uuid.uuid4()),
                    space_id=scope.space_id,
                    operation_id=operation.id,
                    retry_no=retry_no,
                    action_no=action_no,
                    operation=action.kind,
                    status="started",
                    error=None,
                    snapshot_id=operation.target_snapshot_id,
                    slug=action.slug,
                    created_new=None,
                    started_at=now,
                    finished_at=None,
                )
            )
            operation.heartbeat_at = now
            operation.lease_expires_at = now + self._lease_duration
            session.commit()

    def _attempt_finished(
        self,
        scope: KnowledgeScope,
        operation_id: str,
        retry_no: int,
        action_no: int,
        created_new: bool | None,
        error: str | None,
    ) -> None:
        now = self._now()
        with self._session_factory() as session:
            operation, _snapshot, _plan = self._load_operation(
                session, scope, operation_id
            )
            attempt = session.scalar(
                select(PublishAttempt).where(
                    PublishAttempt.space_id == scope.space_id,
                    PublishAttempt.operation_id == operation.id,
                    PublishAttempt.retry_no == retry_no,
                    PublishAttempt.action_no == action_no,
                )
            )
            if attempt is None or attempt.status != "started":
                raise ScopeViolation("release attempt unavailable")
            attempt.status = (
                "succeeded"
                if error is None
                else "collision"
                if error == "page ownership collision"
                else "failed"
            )
            attempt.error = error
            attempt.created_new = created_new
            attempt.finished_at = now
            operation.heartbeat_at = now
            operation.lease_expires_at = now + self._lease_duration
            session.commit()

    def _mark_failed(
        self,
        scope: KnowledgeScope,
        operation_id: str,
        *,
        reconciliation_required: bool,
    ) -> None:
        with self._session_factory() as session:
            operation, snapshot, _plan = self._load_operation(
                session, scope, operation_id
            )
            if operation.status == "succeeded":
                return
            operation.status = "failed"
            if operation.kind == "publish" and snapshot.status != "published":
                snapshot.status = "failed"
            if reconciliation_required:
                existing = session.scalar(
                    select(ReconciliationJob).where(
                        ReconciliationJob.space_id == scope.space_id,
                        ReconciliationJob.source_operation_id == operation.id,
                    )
                )
                if existing is None:
                    session.add(
                        ReconciliationJob(
                            id=str(uuid.uuid4()),
                            space_id=scope.space_id,
                            source_operation_id=operation.id,
                            source_plan_digest=operation.plan_digest or "",
                            reconcile_operation_id=None,
                            status="pending",
                            last_error=None,
                        )
                    )
            if operation.kind == "rollback":
                change_set = session.scalar(
                    select(ChangeSet).where(
                        ChangeSet.space_id == scope.space_id,
                        ChangeSet.source_kind == "rollback",
                        ChangeSet.external_record_id == operation.id,
                    )
                )
                if change_set is not None and change_set.status != "applied":
                    change_set.status = "partially_applied"
            session.commit()

    def _operation_may_have_mutated(
        self,
        scope: KnowledgeScope,
        operation_id: str,
    ) -> bool:
        with self._session_factory() as session:
            require_current_scope(session, scope)
            attempts = session.scalars(
                select(PublishAttempt).where(
                    PublishAttempt.space_id == scope.space_id,
                    PublishAttempt.operation_id == operation_id,
                )
            )
            return any(attempt.status != "collision" for attempt in attempts)

    def _finalize(
        self, scope: KnowledgeScope, operation_id: str
    ) -> PublishResult:
        now = self._now()
        with self._session_factory() as session:
            operation, snapshot, _plan = self._load_operation(
                session, scope, operation_id
            )
            snapshot_ready = (
                snapshot.status == "publishing"
                if operation.kind == "publish"
                else snapshot.status == "published"
                and snapshot.read_model_version == 1
            )
            if operation.status != "running" or not snapshot_ready:
                raise ScopeViolation("release operation unavailable")
            if self._current_id(session, scope.space_id) != operation.base_snapshot_id:
                raise ScopeViolation("release base changed")
            if operation.kind == "publish":
                snapshot.status = "published"
                snapshot.published_at = now
            operation.status = "succeeded"
            operation.heartbeat_at = now
            operation.lease_expires_at = None
            jobs = session.scalars(
                select(ReconciliationJob).where(
                    ReconciliationJob.space_id == scope.space_id,
                    ReconciliationJob.source_operation_id == operation.id,
                )
            )
            for job in jobs:
                job.status = "succeeded"
                job.last_error = None
            if operation.kind == "rollback":
                change_set = session.scalar(
                    select(ChangeSet).where(
                        ChangeSet.space_id == scope.space_id,
                        ChangeSet.source_kind == "rollback",
                        ChangeSet.external_record_id == operation.id,
                    )
                )
                if change_set is None:
                    raise ScopeViolation("release operation unavailable")
                change_set.status = "applied"
            session.flush()
            pointer = session.get(CurrentRelease, (scope.space_id, "current"))
            if pointer is None:
                session.add(
                    CurrentRelease(
                        space_id=scope.space_id,
                        id="current",
                        snapshot_id=snapshot.id,
                    )
                )
            else:
                pointer.snapshot_id = snapshot.id
            pages = list(self._pages(snapshot))
            session.commit()
            return PublishResult(
                snapshot_id=snapshot.id,
                snapshot_label=snapshot.label,
                pages=pages,
            )

    async def _execute_active(
        self,
        scope: KnowledgeScope,
        operation_id: str,
        plan: PublishPlan,
        retry_no: int,
    ) -> PublishResult:
        await self._executor._execute_locked(
            scope,
            plan,
            attempt_started=lambda action_no, action: self._attempt_started(
                scope, operation_id, retry_no, action_no, action
            ),
            attempt_finished=lambda action_no, _action, created_new, error: (
                self._attempt_finished(
                    scope,
                    operation_id,
                    retry_no,
                    action_no,
                    created_new,
                    error,
                )
            ),
            legacy_ownership=self._legacy_ownership(
                scope, plan.base_snapshot_id
            ),
        )
        return self._finalize(scope, operation_id)

    async def publish_product_version(
        self,
        scope: KnowledgeScope,
        *,
        product_version_id: str,
        label: str,
        published_by: str = "publisher",
        registry: SchemaRegistry | None = None,
        field_names: Mapping[str, str] | None = None,
        doc_titles: Mapping[str, str] | None = None,
        notes: str | None = None,
    ) -> PublishResult:
        async with self._executor.space_lock(scope):
            return await self._publish_product_version_locked(
                scope,
                product_version_id=product_version_id,
                label=label,
                published_by=published_by,
                registry=registry,
                field_names=field_names,
                doc_titles=doc_titles,
                notes=notes,
            )

    async def _publish_product_version_locked(
        self,
        scope: KnowledgeScope,
        *,
        product_version_id: str,
        label: str,
        published_by: str,
        registry: SchemaRegistry | None,
        field_names: Mapping[str, str] | None,
        doc_titles: Mapping[str, str] | None,
        notes: str | None,
    ) -> PublishResult:
        operation_id = self._build_operation(
            scope,
            product_version_id=product_version_id,
            label=label,
            published_by=published_by,
            notes=notes,
            registry=registry,
            field_names=field_names,
            doc_titles=doc_titles,
        )
        plan: PublishPlan | None = None
        try:
            plan = self._activate(scope, operation_id)
            return await self._execute_active(scope, operation_id, plan, 0)
        except BaseException as exc:
            self._mark_failed(
                scope,
                operation_id,
                reconciliation_required=(
                    self._operation_may_have_mutated(scope, operation_id)
                    if isinstance(exc, PageOwnershipCollision)
                    else bool(plan and plan.actions)
                ),
            )
            raise

    async def retry_operation(
        self, scope: KnowledgeScope, *, operation_id: str
    ) -> PublishResult:
        async with self._executor.space_lock(scope):
            return await self._retry_operation_locked(
                scope, operation_id=operation_id
            )

    async def _retry_operation_locked(
        self, scope: KnowledgeScope, *, operation_id: str
    ) -> PublishResult:
        now = self._now()
        with self._session_factory() as session:
            operation, snapshot, plan = self._load_operation(
                session, scope, operation_id
            )
            snapshot_retryable = (
                snapshot.status == "failed"
                if operation.kind == "publish"
                else snapshot.status == "published"
                and snapshot.read_model_version == 1
            )
            if (
                operation.kind not in ("publish", "rollback")
                or operation.status != "failed"
                or not snapshot_retryable
                or self._current_id(session, scope.space_id)
                != operation.base_snapshot_id
            ):
                raise ScopeViolation("release operation unavailable")
            operation.retry_no += 1
            retry_no = operation.retry_no
            operation.status = "running"
            operation.heartbeat_at = now
            operation.lease_expires_at = now + self._lease_duration
            if operation.kind == "publish":
                snapshot.status = "publishing"
            session.commit()
        try:
            return await self._execute_active(
                scope, operation_id, plan, retry_no
            )
        except BaseException as exc:
            self._mark_failed(
                scope,
                operation_id,
                reconciliation_required=(
                    self._operation_may_have_mutated(scope, operation_id)
                    if isinstance(exc, PageOwnershipCollision)
                    else bool(plan.actions)
                ),
            )
            raise

    def _build_rollback_operation(
        self,
        scope: KnowledgeScope,
        *,
        snapshot_id: str,
        actor: str,
        reason: str,
    ) -> str:
        _validate_rollback_metadata(actor, reason)
        now = self._now()
        with self._session_factory() as session:
            require_current_scope(session, scope)
            base_snapshot_id = self._current_id(session, scope.space_id)
            if base_snapshot_id is None:
                raise ScopeViolation("release target unavailable")
            target = session.scalar(
                select(ReleaseSnapshot).where(
                    ReleaseSnapshot.id == snapshot_id,
                    ReleaseSnapshot.space_id == scope.space_id,
                    ReleaseSnapshot.status == "published",
                    ReleaseSnapshot.read_model_version == 1,
                )
            )
            current = session.scalar(
                select(ReleaseSnapshot).where(
                    ReleaseSnapshot.id == base_snapshot_id,
                    ReleaseSnapshot.space_id == scope.space_id,
                    ReleaseSnapshot.status == "published",
                )
            )
            if target is None or current is None:
                raise ScopeViolation("release target unavailable")
            plan = self._plan(
                base_snapshot_id=base_snapshot_id,
                target_snapshot_id=target.id,
                current_pages=self._pages(current),
                target_pages=self._pages(target),
            )
            operation = ReleaseOperation(
                id=str(uuid.uuid4()),
                space_id=scope.space_id,
                kind="rollback",
                status="building",
                base_snapshot_id=base_snapshot_id,
                target_snapshot_id=target.id,
                publish_plan=plan.model_dump(mode="json"),
                plan_digest=plan.digest,
                plan_frozen_at=now,
                retry_no=0,
                lease_expires_at=now + self._lease_duration,
                heartbeat_at=now,
                actor=actor,
                reason=reason,
            )
            session.add(operation)
            session.flush()
            session.add(
                ChangeSet(
                    space_id=scope.space_id,
                    source_kind="rollback",
                    knowledge_ids=None,
                    external_record_id=operation.id,
                    source_revision=reason,
                    status="pending",
                    created_by=actor,
                )
            )
            session.commit()
            return operation.id

    async def rollback_to_snapshot(
        self,
        scope: KnowledgeScope,
        *,
        snapshot_id: str,
        actor: str = "publisher",
        reason: str = "rollback",
    ) -> RollbackResult:
        async with self._executor.space_lock(scope):
            return await self._rollback_to_snapshot_locked(
                scope,
                snapshot_id=snapshot_id,
                actor=actor,
                reason=reason,
            )

    async def _rollback_to_snapshot_locked(
        self,
        scope: KnowledgeScope,
        *,
        snapshot_id: str,
        actor: str,
        reason: str,
    ) -> RollbackResult:
        operation_id = self._build_rollback_operation(
            scope,
            snapshot_id=snapshot_id,
            actor=actor,
            reason=reason,
        )
        plan: PublishPlan | None = None
        try:
            plan = self._activate(scope, operation_id)
            result = await self._execute_active(scope, operation_id, plan, 0)
        except BaseException as exc:
            self._mark_failed(
                scope,
                operation_id,
                reconciliation_required=(
                    self._operation_may_have_mutated(scope, operation_id)
                    if isinstance(exc, PageOwnershipCollision)
                    else bool(plan and plan.actions)
                ),
            )
            raise
        with self._session_factory() as session:
            require_current_scope(session, scope)
            change_set_id = session.scalar(
                select(ChangeSet.id).where(
                    ChangeSet.space_id == scope.space_id,
                    ChangeSet.source_kind == "rollback",
                    ChangeSet.external_record_id == operation_id,
                    ChangeSet.status == "applied",
                )
            )
            if change_set_id is None:
                raise ScopeViolation("release operation unavailable")
        return RollbackResult(
            snapshot_id=result.snapshot_id,
            change_set_id=change_set_id,
            pages=result.pages,
        )

    def _prepare_reconcile(
        self,
        scope: KnowledgeScope,
        source_operation_id: str,
    ) -> tuple[str, PublishPlan, int, tuple[RenderedPage, ...], bool]:
        now = self._now()
        with self._session_factory() as session:
            require_current_scope(session, scope)
            source = session.scalar(
                select(ReleaseOperation)
                .where(
                    ReleaseOperation.id == source_operation_id,
                    ReleaseOperation.space_id == scope.space_id,
                    ReleaseOperation.status == "failed",
                )
                .with_for_update()
            )
            job = session.scalar(
                select(ReconciliationJob)
                .where(
                    ReconciliationJob.space_id == scope.space_id,
                    ReconciliationJob.source_operation_id == source_operation_id,
                )
                .with_for_update()
            )
            if (
                source is None
                or source.publish_plan is None
                or source.target_snapshot_id is None
                or job is None
                or job.source_plan_digest != source.plan_digest
            ):
                raise ScopeViolation("reconciliation unavailable")
            try:
                source_plan = PublishPlan.model_validate(source.publish_plan)
            except ValidationError as exc:
                raise ScopeViolation("reconciliation unavailable") from exc
            current_id = self._current_id(session, scope.space_id)
            current = (
                session.scalar(
                    select(ReleaseSnapshot).where(
                        ReleaseSnapshot.id == current_id,
                        ReleaseSnapshot.space_id == scope.space_id,
                        ReleaseSnapshot.status == "published",
                    )
                )
                if current_id is not None
                else None
            )
            if current_id is not None and current is None:
                raise ScopeViolation("reconciliation unavailable")
            current_pages = self._pages(current)

            previous = (
                session.get(ReleaseOperation, job.reconcile_operation_id)
                if job.reconcile_operation_id is not None
                else None
            )
            if (
                previous is not None
                and previous.status == "succeeded"
                and job.status == "succeeded"
            ):
                plan = PublishPlan.model_validate(previous.publish_plan)
                recovered = (
                    session.scalar(
                        select(ReleaseSnapshot).where(
                            ReleaseSnapshot.id == plan.base_snapshot_id,
                            ReleaseSnapshot.space_id == scope.space_id,
                            ReleaseSnapshot.status == "published",
                        )
                    )
                    if plan.base_snapshot_id is not None
                    else None
                )
                if plan.base_snapshot_id is not None and recovered is None:
                    raise ScopeViolation("reconciliation unavailable")
                return (
                    previous.id,
                    plan,
                    previous.retry_no,
                    self._pages(recovered),
                    True,
                )
            if (
                previous is not None
                and previous.status == "failed"
                and previous.base_snapshot_id == current_id
            ):
                plan = PublishPlan.model_validate(previous.publish_plan)
                if previous.plan_digest != plan.digest:
                    raise ScopeViolation("reconciliation unavailable")
                previous.retry_no += 1
                previous.status = "running"
                previous.heartbeat_at = now
                previous.lease_expires_at = now + self._lease_duration
                job.status = "running"
                job.last_error = None
                session.commit()
                return previous.id, plan, previous.retry_no, current_pages, False
            if previous is not None and previous.status != "failed":
                raise ScopeViolation("reconciliation unavailable")

            current_by_slug = {page.slug: page for page in current_pages}
            touched_slugs = {action.slug for action in source_plan.actions}
            actions = tuple(
                PublishAction(
                    kind="upsert", slug=slug, page=current_by_slug[slug]
                )
                for slug in sorted(current_by_slug)
            ) + tuple(
                PublishAction(kind="delete", slug=slug)
                for slug in sorted(touched_slugs - set(current_by_slug))
            )
            target_id = current_id or source.target_snapshot_id
            plan = PublishPlan(
                base_snapshot_id=current_id,
                target_snapshot_id=target_id,
                actions=actions,
                compensation_actions=actions,
            )
            child = ReleaseOperation(
                id=str(uuid.uuid4()),
                space_id=scope.space_id,
                kind="reconcile",
                status="running",
                base_snapshot_id=current_id,
                target_snapshot_id=target_id,
                parent_operation_id=source.id,
                previous_operation_id=previous.id if previous is not None else None,
                publish_plan=plan.model_dump(mode="json"),
                plan_digest=plan.digest,
                plan_frozen_at=now,
                retry_no=0,
                lease_expires_at=now + self._lease_duration,
                heartbeat_at=now,
                actor="reconciler",
                reason="restore execution-time current",
            )
            session.add(child)
            session.flush()
            job.reconcile_operation_id = child.id
            job.status = "running"
            job.last_error = None
            session.commit()
            return child.id, plan, 0, current_pages, False

    def _fail_reconcile(
        self,
        scope: KnowledgeScope,
        operation_id: str,
        error: BaseException,
    ) -> None:
        with self._session_factory() as session:
            operation, _snapshot, _plan = self._load_operation(
                session, scope, operation_id
            )
            if operation.kind != "reconcile" or operation.parent_operation_id is None:
                raise ScopeViolation("reconciliation unavailable")
            operation.status = "failed"
            job = session.scalar(
                select(ReconciliationJob).where(
                    ReconciliationJob.space_id == scope.space_id,
                    ReconciliationJob.source_operation_id
                    == operation.parent_operation_id,
                )
            )
            if job is None:
                raise ScopeViolation("reconciliation unavailable")
            job.status = "failed"
            job.last_error = str(error)
            session.commit()

    def _finalize_reconcile(
        self,
        scope: KnowledgeScope,
        operation_id: str,
    ) -> ReconcileResult:
        now = self._now()
        with self._session_factory() as session:
            operation, _snapshot, _plan = self._load_operation(
                session, scope, operation_id
            )
            if (
                operation.kind != "reconcile"
                or operation.status != "running"
                or operation.parent_operation_id is None
                or self._current_id(session, scope.space_id)
                != operation.base_snapshot_id
            ):
                raise ScopeViolation("reconciliation unavailable")
            job = session.scalar(
                select(ReconciliationJob).where(
                    ReconciliationJob.space_id == scope.space_id,
                    ReconciliationJob.source_operation_id
                    == operation.parent_operation_id,
                    ReconciliationJob.reconcile_operation_id == operation.id,
                )
            )
            if job is None:
                raise ScopeViolation("reconciliation unavailable")
            current = (
                session.scalar(
                    select(ReleaseSnapshot).where(
                        ReleaseSnapshot.id == operation.base_snapshot_id,
                        ReleaseSnapshot.space_id == scope.space_id,
                    )
                )
                if operation.base_snapshot_id is not None
                else None
            )
            pages = self._pages(current)
            operation.status = "succeeded"
            operation.heartbeat_at = now
            operation.lease_expires_at = None
            job.status = "succeeded"
            job.last_error = None
            session.commit()
            return ReconcileResult(
                source_operation_id=operation.parent_operation_id,
                operation_id=operation.id,
                current_snapshot_id=operation.base_snapshot_id,
                pages=pages,
            )

    async def reconcile_operation(
        self,
        scope: KnowledgeScope,
        *,
        source_operation_id: str,
    ) -> ReconcileResult:
        async with self._executor.space_lock(scope):
            return await self._reconcile_operation_locked(
                scope, source_operation_id=source_operation_id
            )

    async def _reconcile_operation_locked(
        self,
        scope: KnowledgeScope,
        *,
        source_operation_id: str,
    ) -> ReconcileResult:
        operation_id, plan, retry_no, current_pages, succeeded = (
            self._prepare_reconcile(scope, source_operation_id)
        )
        if succeeded:
            return ReconcileResult(
                source_operation_id=source_operation_id,
                operation_id=operation_id,
                current_snapshot_id=plan.base_snapshot_id,
                pages=current_pages,
            )
        try:
            await self._executor._execute_locked(
                scope,
                plan,
                attempt_started=lambda action_no, action: self._attempt_started(
                    scope, operation_id, retry_no, action_no, action
                ),
                attempt_finished=lambda action_no, _action, created_new, error: (
                    self._attempt_finished(
                        scope,
                        operation_id,
                        retry_no,
                        action_no,
                        created_new,
                        error,
                    )
                ),
                legacy_ownership=self._legacy_ownership(
                    scope, plan.base_snapshot_id
                ),
            )
            return self._finalize_reconcile(scope, operation_id)
        except BaseException as exc:
            self._fail_reconcile(scope, operation_id, exc)
            raise

    async def recover_expired(self, scope: KnowledgeScope) -> tuple[str, ...]:
        async with self._executor.space_lock(scope):
            return self._recover_expired_locked(scope)

    def _recover_expired_locked(
        self, scope: KnowledgeScope
    ) -> tuple[str, ...]:
        now = self._now()
        recovered: list[str] = []
        with self._session_factory() as session:
            require_current_scope(session, scope)
            operations = list(
                session.scalars(
                    select(ReleaseOperation)
                    .where(
                        ReleaseOperation.space_id == scope.space_id,
                        ReleaseOperation.status.in_(("building", "running")),
                        ReleaseOperation.lease_expires_at.is_not(None),
                        ReleaseOperation.lease_expires_at < now,
                    )
                    .order_by(ReleaseOperation.id)
                )
            )
            for operation in operations:
                started_attempts = list(
                    session.scalars(
                        select(PublishAttempt).where(
                            PublishAttempt.space_id == scope.space_id,
                            PublishAttempt.operation_id == operation.id,
                            PublishAttempt.status == "started",
                        )
                    )
                )
                reconciliation_required = (
                    operation.status == "running" or bool(started_attempts)
                )
                for attempt in started_attempts:
                    attempt.status = "failed"
                    attempt.error = "operation lease expired"
                    attempt.finished_at = now
                operation.status = "failed"
                if operation.kind == "publish" and operation.target_snapshot_id:
                    snapshot = session.scalar(
                        select(ReleaseSnapshot).where(
                            ReleaseSnapshot.id == operation.target_snapshot_id,
                            ReleaseSnapshot.space_id == scope.space_id,
                        )
                    )
                    if snapshot is not None and snapshot.status != "published":
                        snapshot.status = "failed"
                if operation.kind == "rollback":
                    change_set = session.scalar(
                        select(ChangeSet).where(
                            ChangeSet.space_id == scope.space_id,
                            ChangeSet.source_kind == "rollback",
                            ChangeSet.external_record_id == operation.id,
                        )
                    )
                    if change_set is not None and change_set.status != "applied":
                        change_set.status = "partially_applied"
                if reconciliation_required:
                    if operation.kind == "reconcile":
                        existing = session.scalar(
                            select(ReconciliationJob).where(
                                ReconciliationJob.space_id == scope.space_id,
                                ReconciliationJob.reconcile_operation_id
                                == operation.id,
                            )
                        )
                        if existing is None:
                            raise ScopeViolation("reconciliation unavailable")
                        existing.status = "failed"
                        existing.last_error = "operation lease expired"
                    else:
                        existing = session.scalar(
                            select(ReconciliationJob).where(
                                ReconciliationJob.space_id == scope.space_id,
                                ReconciliationJob.source_operation_id == operation.id,
                            )
                        )
                        if existing is None:
                            session.add(
                                ReconciliationJob(
                                    id=str(uuid.uuid4()),
                                    space_id=scope.space_id,
                                    source_operation_id=operation.id,
                                    source_plan_digest=operation.plan_digest or "",
                                    reconcile_operation_id=None,
                                    status="pending",
                                    last_error="operation lease expired",
                                )
                            )
                recovered.append(operation.id)
            session.commit()
        return tuple(recovered)


# Explicit compatibility name for direct-module 018 characterization only.
LegacyStagingReleasePublisher = ReleasePublisher
