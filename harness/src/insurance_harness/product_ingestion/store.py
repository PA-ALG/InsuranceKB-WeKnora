"""Durable, Space-scoped storage port for platform product ingestion."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, load_only

from insurance_harness.jobs import (
    CapacityBlockedJobError,
    DomainWriteSpec,
    JobStore,
    OutboxEventDraft,
    SpaceScopeError,
    StaleGenerationError,
)
from insurance_harness.jobs.models import ErrorClass, JobFailure, JobState
from insurance_harness.jobs.store import database_now, require_active_lease
from insurance_harness.jobs.tables import WikiJob
from insurance_harness.product_ingestion.artifact_tables import (
    ProductArtifact,
    ProductStageModelCall,
)
from insurance_harness.product_ingestion.checkpoint_store import CheckpointStore
from insurance_harness.product_ingestion.models import (
    CallSnapshot,
    CallState,
    FieldAttemptSnapshot,
    FieldCacheIdentity,
    FieldOutcomeKind,
    FieldOutcomeWrite,
    MaterialSnapshot,
    OriginalKnowledgeRef,
    ProductRunScanEntry,
    ProductRunSnapshot,
    ProductRunState,
    ProductScope,
    SealedSourceRef,
    StageSnapshot,
    WindowReservation,
    WindowReservationAction,
    WindowSettlement,
    WindowSnapshot,
    WindowTaskSpec,
)
from insurance_harness.product_ingestion.recovery import (
    RECOVERY_KIND,
    RECOVERY_PREFIX,
    RECOVERY_V2_PREFIX,
    RECOVERY_V3_PREFIX,
    ProcessingRecoveryPlan,
    RecordedIdentityRecoveryPlan,
    RecordedIdentityReference,
    SealedSourceRecoveryPlan,
    SourceSnapshotReference,
    material_references,
    recorded_identity_reference,
)
from insurance_harness.product_ingestion.tables import (
    ProductFieldAttempt,
    ProductMaterial,
    ProductModelCall,
    ProductRun,
    ProductRunFinalization,
    ProductStage,
    ProductStageSettlement,
    ProductWindow,
    ProductWindowSettlement,
)
from insurance_harness.product_ingestion.upload_admission import (
    read_upload_manifest,
    save_upload_manifest,
)
from insurance_harness.product_ingestion.upload_manifest import UploadManifest
from insurance_harness.service_shell.worker import HandlerResult

if TYPE_CHECKING:
    from insurance_harness.product_ingestion.field_validation import FieldValidationReport

SessionFactory = Callable[[], Session]
_CACHEABLE = (FieldOutcomeKind.VERIFIED.value, FieldOutcomeKind.NOT_PROVIDED.value)
_NEEDS_CONFIRMATION_PREFIX = "needs_confirmation:"


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _uuid() -> str:
    return str(uuid4())


def needs_confirmation_error(reason: str) -> CapacityBlockedJobError:
    """Create the typed failure a WorkerLoop handler raises for this terminal."""
    if not reason.strip():
        raise ValueError("needs_confirmation requires a reason")
    return CapacityBlockedJobError(_NEEDS_CONFIRMATION_PREFIX + reason)


class ProductIngestionStore(CheckpointStore):
    """Service-facing store. All worker mutations are fenced by a P1 job lease."""

    def __init__(self, session_factory: SessionFactory, job_store: JobStore) -> None:
        self._session_factory = session_factory
        self._jobs = job_store

    def create_run(
        self,
        *,
        scope: ProductScope,
        idempotency_key: str,
        expected_upload_count: int = 1,
        upload_manifest: UploadManifest | None = None,
        upload_deadline_at: datetime | None = None,
        source_deadline_at: datetime | None = None,
    ) -> ProductRunSnapshot:
        if not idempotency_key:
            raise ValueError("idempotency_key must be non-empty")
        if expected_upload_count < 1:
            raise ValueError("expected_upload_count must be positive")
        if (
            upload_manifest is not None
            and upload_manifest.expected_upload_count != expected_upload_count
        ):
            raise ValueError("upload manifest count mismatch")
        with self._session_factory() as session:
            with session.begin():
                row = session.execute(
                    select(ProductRun).where(
                        ProductRun.tenant_id == scope.tenant_id,
                        ProductRun.space_id == scope.space_id,
                        ProductRun.idempotency_key == idempotency_key,
                    )
                ).scalar_one_or_none()
                if row is None:
                    now = database_now(session)
                    upload_deadline = upload_deadline_at or now + timedelta(hours=1)
                    source_deadline = source_deadline_at or upload_deadline + timedelta(hours=1)
                    if upload_deadline <= now or source_deadline <= upload_deadline:
                        raise ValueError("run deadlines must be ordered in the future")
                    row = ProductRun(
                        tenant_id=scope.tenant_id,
                        space_id=scope.space_id,
                        raw_knowledge_base_id=scope.raw_knowledge_base_id,
                        wiki_knowledge_base_id=scope.wiki_knowledge_base_id,
                        idempotency_key=idempotency_key,
                        retry_of_run_id=None,
                        attempt=1,
                        retry_field_keys=[],
                        expected_upload_count=expected_upload_count,
                        upload_deadline_at=upload_deadline,
                        uploads_sealed_at=None,
                        source_deadline_at=source_deadline,
                        state=ProductRunState.ACCEPTING_UPLOADS.value,
                        version=1,
                        workflow_version=3,
                        uploads_sealed=False,
                        created_at=now,
                        started_at=None,
                        root_job_id=None,
                    )
                    session.add(row)
                    session.flush()
                    if upload_manifest is not None:
                        save_upload_manifest(session, row, upload_manifest)
                else:
                    self._check_scope(row, scope)
                    if read_upload_manifest(session, row) != upload_manifest:
                        raise ValueError("idempotent upload manifest changed")
                    if row.expected_upload_count != expected_upload_count:
                        raise ValueError("idempotent run parameters changed")
                    if upload_deadline_at is not None and _aware(row.upload_deadline_at) != _aware(
                        upload_deadline_at
                    ):
                        raise ValueError("idempotent upload deadline changed")
                    if source_deadline_at is not None and _aware(row.source_deadline_at) != _aware(
                        source_deadline_at
                    ):
                        raise ValueError("idempotent source deadline changed")
                return self._run_snapshot(session, row, scope)

    def get_upload_manifest(self, *, scope: ProductScope, run_id: str) -> UploadManifest | None:
        with self._session_factory() as session:
            row = self._run(session, scope, run_id)
            visited = set()
            while row.retry_of_run_id:
                if row.id in visited:
                    raise ValueError("upload admission lineage cycle")
                visited.add(row.id)
                row = self._run(session, scope, row.retry_of_run_id)
            return read_upload_manifest(session, row)

    def get_run(self, *, scope: ProductScope, run_id: str) -> ProductRunSnapshot:
        with self._session_factory() as session:
            row = self._run(session, scope, run_id)
            return self._run_snapshot(session, row, scope)

    def list_runs(self, *, scope: ProductScope, limit: int = 50) -> tuple[ProductRunSnapshot, ...]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        with self._session_factory() as session:
            rows = session.scalars(
                select(ProductRun)
                .where(
                    ProductRun.tenant_id == scope.tenant_id,
                    ProductRun.space_id == scope.space_id,
                    ProductRun.raw_knowledge_base_id == scope.raw_knowledge_base_id,
                    ProductRun.wiki_knowledge_base_id == scope.wiki_knowledge_base_id,
                )
                .order_by(ProductRun.created_at.desc(), ProductRun.id.desc())
                .limit(limit)
            ).all()
            return tuple(self._run_snapshot(session, row, scope) for row in rows)

    def list_status_summaries(
        self,
        *,
        scope: ProductScope,
        limit: int = 30,
    ) -> tuple[dict[str, Any], ...]:
        """Read the displayed run heads without opening field, source or model audits."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with self._session_factory() as session:
            rows = session.execute(
                select(ProductRun, ProductRunFinalization, WikiJob)
                .outerjoin(ProductRunFinalization, ProductRunFinalization.run_id == ProductRun.id)
                .outerjoin(WikiJob, WikiJob.id == ProductRun.root_job_id)
                .where(
                    ProductRun.tenant_id == scope.tenant_id,
                    ProductRun.space_id == scope.space_id,
                    ProductRun.raw_knowledge_base_id == scope.raw_knowledge_base_id,
                    ProductRun.wiki_knowledge_base_id == scope.wiki_knowledge_base_id,
                )
                .order_by(ProductRun.created_at.desc(), ProductRun.id.desc())
                .limit(limit)
            ).all()
            if not rows:
                return ()
            ids = [run.id for run, _final, _root in rows]
            active_stage: dict[str, str] = {}
            for run_id, key, job_finished, settlement_finished in session.execute(
                select(
                    ProductStage.run_id, ProductStage.stage_key,
                    WikiJob.finished_at, ProductStageSettlement.finished_at,
                )
                .join(WikiJob, WikiJob.id == ProductStage.job_id)
                .outerjoin(
                    ProductStageSettlement, ProductStageSettlement.stage_id == ProductStage.id
                )
                .where(ProductStage.run_id.in_(ids), ProductStage.space_id == scope.space_id)
                .order_by(ProductStage.created_at, ProductStage.id)
            ):
                if job_finished is None and settlement_finished is None:
                    active_stage.setdefault(run_id, key)
            for run_id, key, job_finished in session.execute(
                select(ProductWindow.run_id, ProductWindow.stage_key, WikiJob.finished_at)
                .join(WikiJob, WikiJob.id == ProductWindow.job_id)
                .where(ProductWindow.run_id.in_(ids), ProductWindow.space_id == scope.space_id)
                .order_by(ProductWindow.created_at, ProductWindow.id)
            ):
                if job_finished is None:
                    active_stage.setdefault(run_id, key)
            result = []
            for run, final, root in rows:
                state = final.state if final is not None else run.state
                finished_at = _aware(final.finished_at) if final is not None else None
                reason = None
                if final is None and root is not None and root.state in {
                    JobState.BLOCKED.value, JobState.DEAD_LETTER.value,
                }:
                    finished_at = _aware(root.finished_at)
                    summary = root.error_summary or root.state
                    if (
                        root.state == JobState.BLOCKED.value
                        and root.error_class == ErrorClass.CAPACITY_BLOCKED.value
                        and _NEEDS_CONFIRMATION_PREFIX in summary
                    ):
                        state = ProductRunState.NEEDS_CONFIRMATION.value
                        reason = summary.partition(_NEEDS_CONFIRMATION_PREFIX)[2]
                    else:
                        state = ProductRunState.FAILED.value
                        reason = (
                            summary if re.fullmatch(r"[A-Z][A-Z0-9_:.-]{0,199}", summary)
                            else "PRODUCT_STAGE_FAILED"
                        )
                counts = (
                    {
                        "success_count": final.success_count,
                        "missing_count": final.missing_count,
                        "failure_count": final.failure_count,
                    }
                    if final is not None else
                    {"success_count": None, "missing_count": None, "failure_count": None}
                )
                result.append({
                    "run_id": run.id,
                    "scope": scope.model_dump(mode="json"),
                    "wiki_knowledge_base_id": scope.wiki_knowledge_base_id,
                    "version": run.version,
                    "state": state,
                    "stage": active_stage.get(run.id),
                    "created_at": _aware(run.created_at),
                    "started_at": _aware(final.started_at if final is not None else run.started_at),
                    "finished_at": finished_at,
                    "reason": reason,
                    "counts": counts,
                    "model_call_count": None,
                    "model_call_count_complete": False,
                })
            return tuple(result)

    def scan_runs(
        self,
        *,
        scope: ProductScope,
        after: tuple[datetime, str] | None = None,
        limit: int = 50,
    ) -> tuple[ProductRunScanEntry, ...]:
        """Select reconcilable identities without hydrating terminal history."""
        if limit < 1:
            raise ValueError("limit must be >= 1")
        terminal_states = (
            ProductRunState.SUCCEEDED.value,
            ProductRunState.PARTIAL_SUCCESS.value,
            ProductRunState.FAILED.value,
            ProductRunState.NEEDS_CONFIRMATION.value,
        )
        final = (
            select(ProductRunFinalization.id)
            .where(
                ProductRunFinalization.run_id == ProductRun.id,
                ProductRunFinalization.state.in_(terminal_states),
            )
            .exists()
        )
        failed_root = (
            select(WikiJob.id)
            .where(
                WikiJob.id == ProductRun.root_job_id,
                WikiJob.state.in_((JobState.BLOCKED.value, JobState.DEAD_LETTER.value)),
            )
            .exists()
        )
        statement = select(ProductRun.id, ProductRun.created_at).where(
            ProductRun.state.not_in(terminal_states),
            ~final,
            ~failed_root,
            ProductRun.tenant_id == scope.tenant_id,
            ProductRun.space_id == scope.space_id,
            ProductRun.raw_knowledge_base_id == scope.raw_knowledge_base_id,
            ProductRun.wiki_knowledge_base_id == scope.wiki_knowledge_base_id,
        )
        if after is not None:
            created_at, run_id = after
            if created_at.tzinfo is None or not run_id:
                raise ValueError("run scan cursor must contain an aware time and run id")
            statement = statement.where(
                or_(
                    ProductRun.created_at > created_at,
                    and_(ProductRun.created_at == created_at, ProductRun.id > run_id),
                )
            )
        with self._session_factory() as session:
            rows = session.execute(
                statement.order_by(ProductRun.created_at, ProductRun.id).limit(limit)
            ).all()
            result: list[ProductRunScanEntry] = []
            for run_id, created_at in rows:
                aware_created = _aware(created_at)
                if aware_created is None:
                    raise ValueError("run scan row has no creation time")
                result.append(ProductRunScanEntry(run_id=run_id, created_at=aware_created))
            return tuple(result)

    def attach_original(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        expected_version: int,
        original: OriginalKnowledgeRef,
    ) -> ProductRunSnapshot:
        with self._session_factory() as session:
            with session.begin():
                row = self._run(session, scope, run_id, lock=True)
                self._mutable_run(row, expected_version)
                existing = session.execute(
                    select(ProductMaterial).where(
                        ProductMaterial.run_id == run_id,
                        ProductMaterial.knowledge_id == original.knowledge_id,
                    )
                ).scalar_one_or_none()
                if existing is None:
                    session.add(
                        ProductMaterial(
                            run_id=run_id,
                            tenant_id=scope.tenant_id,
                            space_id=scope.space_id,
                            knowledge_id=original.knowledge_id,
                            original_filename=original.original_filename,
                            upload_ordinal=original.upload_ordinal,
                        )
                    )
                    row.version += 1
                    session.flush()
                elif (
                    existing.original_filename != original.original_filename
                    or existing.upload_ordinal != original.upload_ordinal
                ):
                    raise ValueError("original attachment is immutable")
                return self._run_snapshot(session, row, scope)

    def seal_uploads(
        self, *, scope: ProductScope, run_id: str, expected_version: int
    ) -> ProductRunSnapshot:
        with self._session_factory() as session:
            with session.begin():
                row = self._run(session, scope, run_id, lock=True)
                if row.uploads_sealed:
                    return self._run_snapshot(session, row, scope)
                self._mutable_run(row, expected_version)
                material_count = session.scalar(
                    select(func.count())
                    .select_from(ProductMaterial)
                    .where(ProductMaterial.run_id == run_id)
                )
                if material_count != row.expected_upload_count:
                    raise ValueError("cannot seal until expected originals are attached")
                now = database_now(session)
                row.uploads_sealed = True
                row.uploads_sealed_at = now
                row.started_at = now
                row.state = ProductRunState.AWAITING_SOURCES.value
                row.version += 1
                return self._run_snapshot(session, row, scope)

    def seal_material_source(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        material_id: str,
        source: SealedSourceRef,
    ) -> ProductRunSnapshot:
        with self._session_factory() as session:
            with session.begin():
                run = self._run(session, scope, run_id, lock=True)
                self._ensure_unfinished(session, run)
                material = session.execute(
                    select(ProductMaterial)
                    .where(
                        ProductMaterial.id == material_id,
                        ProductMaterial.run_id == run_id,
                    )
                    .with_for_update()
                ).scalar_one_or_none()
                if material is None or material.space_id != scope.space_id:
                    raise SpaceScopeError()
                if source.knowledge_id != material.knowledge_id:
                    raise ValueError("source knowledge_id must match the original")
                proposed = source.model_dump()
                current = {key: getattr(material, key) for key in proposed if key != "knowledge_id"}
                if material.source_revision_id is not None and current != {
                    key: value for key, value in proposed.items() if key != "knowledge_id"
                }:
                    raise ValueError("sealed source is immutable")
                if material.source_revision_id is not None:
                    return self._run_snapshot(session, run, scope)
                for key, value in proposed.items():
                    if key != "knowledge_id":
                        setattr(material, key, value)
                run.version += 1
                sealed = session.scalar(
                    select(func.count())
                    .select_from(ProductMaterial)
                    .where(
                        ProductMaterial.run_id == run_id,
                        ProductMaterial.source_revision_id.is_not(None),
                    )
                )
                total = session.scalar(
                    select(func.count())
                    .select_from(ProductMaterial)
                    .where(ProductMaterial.run_id == run_id)
                )
                if run.uploads_sealed and sealed == total:
                    run.state = ProductRunState.RUNNING.value
                    run.started_at = run.started_at or database_now(session)
                session.flush()
                return self._run_snapshot(session, run, scope)

    def enqueue_root(
        self, *, scope: ProductScope, run_id: str, idempotency_key: str
    ) -> WindowSnapshot:
        job_id = str(uuid5(NAMESPACE_URL, f"product-root:{scope.space_id}:{run_id}"))
        # Bind before publishing the deterministic job. If admission crashes, the
        # pump can re-enqueue this same ID; a claim can never precede its binding.
        with self._session_factory() as session:
            with session.begin():
                run = self._run(session, scope, run_id, lock=True)
                if run.root_job_id not in (None, job_id):
                    raise ValueError("root job is already bound")
                run.root_job_id = job_id
        result = self._jobs.enqueue(
            space_id=scope.space_id,
            job_type="product_ingestion_root",
            idempotency_key=idempotency_key,
            job_id=job_id,
            payload={"run_id": run_id, "tenant_id": scope.tenant_id},
        )
        return WindowSnapshot(
            window_id="root",
            job_id=result.job.id,
            run_id=run_id,
            stage_key="root",
            window_key="root",
            tasks=(),
        )

    def enqueue_stage(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        stage_key: str,
        dependency_sha256: str,
        idempotency_key: str,
        parent_job_id: str | None = None,
    ) -> StageSnapshot:
        stage_id = str(uuid5(NAMESPACE_URL, f"product-stage:{scope.space_id}:{run_id}:{stage_key}"))
        job_id = str(uuid5(NAMESPACE_URL, f"product-stage-job:{stage_id}:{dependency_sha256}"))
        with self._session_factory() as session:
            self._run(session, scope, run_id)
            row = session.get(ProductStage, stage_id)
            if row is not None:
                if (
                    row.dependency_sha256 != dependency_sha256
                    or row.parent_job_id != parent_job_id
                    or row.job_id != job_id
                ):
                    raise ValueError("stage identity is immutable")
                return self._stage_snapshot(session, row)
            now = database_now(session)
        self._jobs.enqueue(
            space_id=scope.space_id,
            job_type=f"product_stage_{stage_key}",
            idempotency_key=idempotency_key,
            job_id=job_id,
            payload={"run_id": run_id, "stage_key": stage_key},
            domain_writes=(
                DomainWriteSpec(
                    table=ProductStage.__tablename__,
                    values={
                        "id": stage_id,
                        "run_id": run_id,
                        "space_id": scope.space_id,
                        "stage_key": stage_key,
                        "dependency_sha256": dependency_sha256,
                        "job_id": job_id,
                        "parent_job_id": parent_job_id,
                        "created_at": now,
                    },
                ),
            ),
        )
        return self.get_stage(scope=scope, run_id=run_id, stage_id=stage_id)

    def get_stage(self, *, scope: ProductScope, run_id: str, stage_id: str) -> StageSnapshot:
        with self._session_factory() as session:
            self._run(session, scope, run_id)
            row = session.execute(
                select(ProductStage).where(
                    ProductStage.id == stage_id, ProductStage.run_id == run_id
                )
            ).scalar_one_or_none()
            if row is None or row.space_id != scope.space_id:
                raise SpaceScopeError()
            return self._stage_snapshot(session, row)

    def list_stages(self, *, scope: ProductScope, run_id: str) -> tuple[StageSnapshot, ...]:
        with self._session_factory() as session:
            self._run(session, scope, run_id)
            rows = session.scalars(
                select(ProductStage)
                .where(
                    ProductStage.run_id == run_id,
                    ProductStage.space_id == scope.space_id,
                )
                .order_by(ProductStage.created_at, ProductStage.id)
            ).all()
            return tuple(self._stage_snapshot(session, row) for row in rows)

    def stage_wall_starts(self, *, scope: ProductScope, run_id: str) -> dict[str, datetime]:
        """First durable registration, including queue waits and later attempts."""
        with self._session_factory() as session:
            self._run(session, scope, run_id)
            starts = {
                key: aware_created
                for key, created in session.execute(
                    select(ProductStage.stage_key, ProductStage.created_at).where(
                        ProductStage.run_id == run_id,
                        ProductStage.space_id == scope.space_id,
                    )
                )
                if (aware_created := _aware(created)) is not None
            }
            for key, created in session.execute(
                select(ProductWindow.stage_key, func.min(ProductWindow.created_at))
                .where(ProductWindow.run_id == run_id, ProductWindow.space_id == scope.space_id)
                .group_by(ProductWindow.stage_key)
            ):
                current = starts.get(key)
                earliest = _aware(created)
                if earliest is not None and (current is None or earliest < current):
                    starts[key] = earliest
            return starts

    def stage_last_attempt_starts(
        self, *, scope: ProductScope, run_id: str
    ) -> dict[str, datetime]:
        """Latest P1 start per stage, separate from the full stage wall clock."""
        with self._session_factory() as session:
            self._run(session, scope, run_id)
            starts = {
                key: aware_started
                for key, started in session.execute(
                    select(ProductStage.stage_key, WikiJob.started_at)
                    .join(WikiJob, WikiJob.id == ProductStage.job_id)
                    .where(
                        ProductStage.run_id == run_id,
                        ProductStage.space_id == scope.space_id,
                        WikiJob.started_at.is_not(None),
                    )
                )
                if (aware_started := _aware(started)) is not None
            }
            for key, started in session.execute(
                select(ProductWindow.stage_key, func.max(WikiJob.started_at))
                .join(WikiJob, WikiJob.id == ProductWindow.job_id)
                .where(
                    ProductWindow.run_id == run_id,
                    ProductWindow.space_id == scope.space_id,
                    WikiJob.started_at.is_not(None),
                )
                .group_by(ProductWindow.stage_key)
            ):
                current = starts.get(key)
                latest = _aware(started)
                if latest is not None and (current is None or latest > current):
                    starts[key] = latest
            return starts

    def list_status_stages(self, *, scope: ProductScope, run_id: str) -> tuple[StageSnapshot, ...]:
        """Display window execution as part of extraction, never as an orchestration barrier."""
        stages = {row.stage_key: row for row in self.list_stages(scope=scope, run_id=run_id)}
        with self._session_factory() as session:
            self._run(session, scope, run_id)
            windows = session.execute(
                select(ProductWindow, WikiJob)
                .options(
                    load_only(
                        ProductWindow.id,
                        ProductWindow.stage_key,
                        ProductWindow.dependency_sha256,
                    )
                )
                .join(WikiJob, WikiJob.id == ProductWindow.job_id)
                .where(
                    ProductWindow.run_id == run_id,
                    ProductWindow.space_id == scope.space_id,
                )
            ).all()
            for key in sorted({window.stage_key for window, _job in windows}):
                group = [(window, job) for window, job in windows if window.stage_key == key]
                ids = [window.id for window, _job in group]
                settlements = session.scalars(
                    select(ProductWindowSettlement).where(
                        ProductWindowSettlement.window_id.in_(ids)
                    )
                ).all()
                dispatched = session.scalar(
                    select(func.count(ProductModelCall.id)).where(
                        ProductModelCall.window_id.in_(ids),
                        ProductModelCall.dispatched_at.is_not(None),
                    )
                )
                aggregate = stages.get(key)
                starts = [
                    started_value
                    for _window, job in group
                    if (started_value := _aware(job.started_at)) is not None
                ]
                if aggregate and aggregate.started_at:
                    starts.append(aggregate.started_at)
                failures = [
                    job for _window, job in group if job.state in {"blocked", "dead_letter"}
                ]
                finished = aggregate.finished_at if aggregate else None
                state = aggregate.state if aggregate else ("running" if starts else "queued")
                if failures and all(job.finished_at for _window, job in group):
                    state = "failed"
                    finished_values = [
                        finished_value
                        for _window, job in group
                        if (finished_value := _aware(job.finished_at)) is not None
                    ]
                    finished = max(finished_values)
                usage: dict[str, int] = {}
                for settlement in settlements:
                    for usage_key, usage_value in settlement.usage.items():
                        usage[usage_key] = usage.get(usage_key, 0) + usage_value
                started_at = min(starts) if starts else None
                stages[key] = StageSnapshot(
                    stage_id=aggregate.stage_id if aggregate else "window-phase:" + key,
                    run_id=run_id,
                    stage_key=key,
                    dependency_sha256=aggregate.dependency_sha256
                    if aggregate
                    else group[0][0].dependency_sha256,
                    job_id=aggregate.job_id if aggregate else group[0][1].id,
                    parent_job_id=aggregate.parent_job_id if aggregate else None,
                    state=state,
                    success_count=sum(row.success_count for row in settlements),
                    missing_count=sum(row.missing_count for row in settlements),
                    failure_count=sum(row.failure_count for row in settlements),
                    model_call_count=dispatched or 0,
                    usage=usage,
                    started_at=started_at,
                    finished_at=finished,
                )
        order = (
            "uploads",
            "source",
            "routing",
            "identity",
            "field_plan",
            "extract",
            "synthesis",
            "compilation",
            "preparation",
            "review",
            "publish",
            "verify",
        )
        return tuple(
            sorted(
                stages.values(),
                key=lambda row: (
                    order.index(row.stage_key) if row.stage_key in order else len(order)
                ),
            )
        )

    def settle_stage(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        stage_id: str,
        job_id: str,
        generation: int,
        state: ProductRunState,
    ) -> StageSnapshot:
        result = self.prepare_stage_settlement(
            scope=scope,
            run_id=run_id,
            stage_id=stage_id,
            job_id=job_id,
            generation=generation,
            state=state,
        )
        self._jobs.report_success(
            space_id=scope.space_id,
            job_id=job_id,
            generation=generation,
            domain_writes=result.domain_writes,
            events=result.events,
        )
        return self.get_stage(scope=scope, run_id=run_id, stage_id=stage_id)

    def prepare_stage_settlement(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        stage_id: str,
        job_id: str,
        generation: int,
        state: ProductRunState,
    ) -> HandlerResult:
        if state not in {
            ProductRunState.SUCCEEDED,
            ProductRunState.PARTIAL_SUCCESS,
            ProductRunState.FAILED,
        }:
            raise ValueError("stage settlement requires a handled terminal state")
        with self._session_factory() as session:
            with session.begin():
                self._active_job(session, scope, job_id, generation)
            self._run(session, scope, run_id)
            stage = session.execute(
                select(ProductStage).where(
                    ProductStage.id == stage_id,
                    ProductStage.run_id == run_id,
                    ProductStage.job_id == job_id,
                )
            ).scalar_one_or_none()
            if stage is None or stage.space_id != scope.space_id:
                raise SpaceScopeError()
            windows = session.scalars(
                select(ProductWindow).where(
                    ProductWindow.run_id == run_id,
                    ProductWindow.stage_key == stage.stage_key,
                )
            ).all()
            window_ids = tuple(item.id for item in windows)
            settlements = (
                session.scalars(
                    select(ProductWindowSettlement).where(
                        ProductWindowSettlement.window_id.in_(window_ids)
                    )
                ).all()
                if window_ids
                else []
            )
            counts = (
                sum(item.success_count for item in settlements),
                sum(item.missing_count for item in settlements),
                sum(item.failure_count for item in settlements),
            )
            call_count = (
                int(
                    session.scalar(
                        select(func.count())
                        .select_from(ProductModelCall)
                        .where(
                            ProductModelCall.window_id.in_(window_ids),
                            ProductModelCall.dispatched_at.is_not(None),
                        )
                    )
                    or 0
                )
                if window_ids
                else 0
            )
            usage = self._sum_usage(settlements)
            now = database_now(session)
        return HandlerResult(
            domain_writes=(
                DomainWriteSpec(
                    table=ProductStageSettlement.__tablename__,
                    values={
                        "id": _uuid(),
                        "stage_id": stage_id,
                        "run_id": run_id,
                        "space_id": scope.space_id,
                        "state": state.value,
                        "success_count": counts[0],
                        "missing_count": counts[1],
                        "failure_count": counts[2],
                        "model_call_count": call_count,
                        "usage": usage,
                        "finished_at": now,
                    },
                ),
            ),
            events=(
                OutboxEventDraft(
                    event_id=_uuid(),
                    event_type="product.stage.settled",
                    payload={
                        "run_id": run_id,
                        "stage_id": stage_id,
                        "state": state.value,
                    },
                ),
            ),
        )

    def enqueue_window(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        stage_key: str,
        window_key: str,
        dependency_sha256: str,
        tasks: tuple[WindowTaskSpec, ...],
    ) -> WindowSnapshot:
        if not tasks:
            raise ValueError("window tasks must not be empty")
        window_id = str(
            uuid5(
                NAMESPACE_URL,
                f"product-window:{scope.space_id}:{run_id}:{stage_key}:{window_key}",
            )
        )
        job_id = str(uuid5(NAMESPACE_URL, f"product-window-job:{window_id}:{dependency_sha256}"))
        task_values = [task.model_dump(mode="json") for task in tasks]
        with self._session_factory() as session:
            self._run(session, scope, run_id)
            row = session.get(ProductWindow, window_id)
            if row is not None:
                if (
                    row.dependency_sha256 != dependency_sha256
                    or row.tasks != task_values
                    or row.job_id != job_id
                ):
                    raise ValueError("window identity is immutable")
                return self._window_snapshot(row)
            now = database_now(session)
        self._jobs.enqueue(
            space_id=scope.space_id,
            job_type="product_extraction_window",
            job_id=job_id,
            idempotency_key=f"{run_id}:{stage_key}:{window_key}:{dependency_sha256}",
            payload={
                "run_id": run_id,
                "stage_key": stage_key,
                "window_key": window_key,
            },
            domain_writes=(
                DomainWriteSpec(
                    table=ProductWindow.__tablename__,
                    values={
                        "id": window_id,
                        "run_id": run_id,
                        "space_id": scope.space_id,
                        "stage_key": stage_key,
                        "window_key": window_key,
                        "dependency_sha256": dependency_sha256,
                        "tasks": task_values,
                        "job_id": job_id,
                        "created_at": now,
                    },
                ),
            ),
        )
        return self.get_window(scope=scope, run_id=run_id, window_id=window_id)

    def get_window(self, *, scope: ProductScope, run_id: str, window_id: str) -> WindowSnapshot:
        with self._session_factory() as session:
            self._run(session, scope, run_id)
            row = session.execute(
                select(ProductWindow).where(
                    ProductWindow.id == window_id,
                    ProductWindow.run_id == run_id,
                    ProductWindow.space_id == scope.space_id,
                )
            ).scalar_one_or_none()
            if row is None:
                raise SpaceScopeError()
            return self._window_snapshot(row)

    def get_window_for_job(
        self, *, scope: ProductScope, run_id: str, job_id: str
    ) -> WindowSnapshot:
        with self._session_factory() as session:
            return self._window_snapshot(self._window_for_job(session, scope, run_id, job_id))

    def list_windows(
        self, *, scope: ProductScope, run_id: str, stage_key: str | None = None
    ) -> tuple[WindowSnapshot, ...]:
        with self._session_factory() as session:
            self._run(session, scope, run_id)
            query = select(ProductWindow).where(
                ProductWindow.run_id == run_id,
                ProductWindow.space_id == scope.space_id,
            )
            if stage_key is not None:
                query = query.where(ProductWindow.stage_key == stage_key)
            rows = session.scalars(query.order_by(ProductWindow.created_at, ProductWindow.id)).all()
            return tuple(self._window_snapshot(row) for row in rows)

    def reserve_window(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        job_id: str,
        generation: int,
        attempt: int,
        call_id: str,
        window_key: str,
        request_sha256: str | None = None,
        tasks: tuple[WindowTaskSpec, ...],
    ) -> WindowReservation:
        task_values = [task.model_dump(mode="json") for task in tasks]
        with self._session_factory() as session:
            with session.begin():
                # This lock precedes the job fence and is compatible with FK KEY SHARE.
                window = self._window_for_job(session, scope, run_id, job_id, reserve_lock=True)
                if window.window_key != window_key or window.tasks != task_values:
                    raise ValueError("window reservation does not match its sealed task set")
                if window.selected_field_keys is None:
                    cached = self._lookup_cache(
                        session, scope, [task.cache_identity for task in tasks]
                    )
                    run = self._run(session, scope, run_id)
                    # An explicit failed-field retry requests a fresh extraction.
                    # Its original attempt may remain VERIFIED for custody while
                    # a checkpoint child's location validation marked it failed.
                    forced = set(run.retry_field_keys or ())
                    cached = {
                        key: row for key, row in cached.items() if row.field_key not in forced
                    }
                    selected = tuple(
                        task for task in tasks if task.cache_identity.cache_key not in cached
                    )
                else:
                    selected_keys = {tuple(item) for item in window.selected_field_keys}
                    selected = tuple(
                        task for task in tasks if (task.entity_id, task.field_key) in selected_keys
                    )
                    cached = self._attempts_by_id(
                        session, scope, tuple(window.cached_attempt_ids or ())
                    )
                # Complete task hydration/comparison and cache selection run without
                # holding WikiJob. No selection/call mutation occurs before this fence.
                self._active_job(session, scope, job_id, generation)
                if window.selected_field_keys is None:
                    window.selected_field_keys = [
                        [task.entity_id, task.field_key] for task in selected
                    ]
                    window.cached_attempt_ids = [item.attempt_id for item in cached.values()]
                    window.reservation_generation = generation
                    window.reserved_at = database_now(session)
                if not selected:
                    return WindowReservation(
                        action=WindowReservationAction.ALL_CACHED,
                        call=None,
                        dispatch_tasks=(),
                        cached=tuple(cached.values()),
                    )
                call = session.execute(
                    select(ProductModelCall)
                    .where(ProductModelCall.window_id == window.id)
                    .with_for_update()
                ).scalar_one_or_none()
                if call is not None:
                    if (
                        call.run_id != run_id
                        or call.job_id != job_id
                        or (
                            call.request_sha256 is not None
                            and request_sha256 is not None
                            and call.request_sha256 != request_sha256
                        )
                    ):
                        raise ValueError("call identity is immutable")
                    if call.state in {
                        CallState.DISPATCHING.value,
                        CallState.INTERRUPTED.value,
                    }:
                        if call.state == CallState.DISPATCHING.value:
                            call.state = CallState.INTERRUPTED.value
                            call.diagnostic = "provider_call_interrupted"
                            call.recorded_at = database_now(session)
                        failures = tuple(
                            FieldOutcomeWrite(
                                entity_id=task.entity_id,
                                field_key=task.field_key,
                                task_sha256=task.task_sha256,
                                cache_identity=task.cache_identity,
                                outcome=FieldOutcomeKind.EXTRACTION_FAILED,
                                reason="provider_call_interrupted",
                                validated_result=None,
                                raw_ref=call.raw_ref,
                            )
                            for task in selected
                        )
                        return WindowReservation(
                            action=WindowReservationAction.INTERRUPTED,
                            call=self._call_snapshot(call),
                            dispatch_tasks=(),
                            cached=tuple(cached.values()),
                            outcomes=failures,
                        )
                    if call.state == CallState.RESERVED.value:
                        call.generation = generation
                        call.attempt = attempt
                        action = WindowReservationAction.DISPATCH
                    else:
                        action = WindowReservationAction.RECORDED
                    return WindowReservation(
                        action=action,
                        call=self._call_snapshot(call),
                        dispatch_tasks=(
                            selected if action is WindowReservationAction.DISPATCH else ()
                        ),
                        cached=tuple(cached.values()),
                    )
                now = database_now(session)
                call = ProductModelCall(
                    call_id=call_id,
                    run_id=run_id,
                    window_id=window.id,
                    space_id=scope.space_id,
                    job_id=job_id,
                    generation=generation,
                    attempt=attempt,
                    state=CallState.RESERVED.value,
                    request_sha256=request_sha256,
                    request_bytes=None,
                    raw=None,
                    raw_sha256=None,
                    raw_ref=f"product-call:{call_id}",
                    diagnostic=None,
                    reserved_at=now,
                    dispatched_at=None,
                    recorded_at=None,
                    selected_field_keys=[[task.entity_id, task.field_key] for task in selected],
                    cached_attempt_ids=list(window.cached_attempt_ids or ()),
                )
                session.add(call)
                session.flush()
                return WindowReservation(
                    action=WindowReservationAction.DISPATCH,
                    call=self._call_snapshot(call),
                    dispatch_tasks=selected,
                    cached=tuple(cached.values()),
                )

    def begin_call(
        self,
        *,
        scope: ProductScope,
        call_id: str,
        job_id: str,
        generation: int,
        request_sha256: str,
        request_bytes: bytes,
    ) -> CallSnapshot:
        if hashlib.sha256(request_bytes).hexdigest() != request_sha256:
            raise ValueError("request bytes do not match request_sha256")
        with self._session_factory() as session:
            with session.begin():
                self._active_job(session, scope, job_id, generation)
                call = self._call(session, scope, call_id, lock=True)
                if call.job_id != job_id or call.generation != generation:
                    raise StaleGenerationError(
                        expected=call.generation, actual=generation, job_id=job_id
                    )
                if call.state == CallState.DISPATCHING.value:
                    if (
                        call.request_sha256 == request_sha256
                        and call.request_bytes == request_bytes
                    ):
                        return self._call_snapshot(call)
                    raise ValueError("dispatching request is immutable")
                if call.state != CallState.RESERVED.value:
                    raise ValueError("only a reserved call can begin dispatch")
                if call.request_sha256 is not None and call.request_sha256 != request_sha256:
                    raise ValueError("request_sha256 changed after reservation")
                call.request_sha256 = request_sha256
                call.request_bytes = bytes(request_bytes)
                call.state = CallState.DISPATCHING.value
                call.dispatched_at = database_now(session)
                return self._call_snapshot(call)

    def record_call_result(
        self,
        *,
        scope: ProductScope,
        call_id: str,
        job_id: str,
        generation: int,
        request_sha256: str,
        raw: bytes | None,
        diagnostic: str | None,
    ) -> CallSnapshot:
        if raw is None and not (diagnostic or "").strip():
            raise ValueError("a missing raw response requires a diagnostic")
        with self._session_factory() as session:
            with session.begin():
                self._active_job(session, scope, job_id, generation)
                call = self._call(session, scope, call_id, lock=True)
                if call.job_id != job_id or call.generation != generation:
                    raise StaleGenerationError(
                        expected=call.generation, actual=generation, job_id=job_id
                    )
                if call.request_sha256 != request_sha256:
                    raise ValueError("recorded response request_sha256 mismatch")
                if call.state == CallState.RECORDED.value:
                    same_raw = call.raw == raw
                    same_diagnostic = call.diagnostic == diagnostic
                    if same_raw and same_diagnostic:
                        return self._call_snapshot(call)
                    raise ValueError("recorded call result is immutable; conflicting replay")
                if call.state != CallState.DISPATCHING.value:
                    raise ValueError("only a dispatching call can record a result")
                call.raw = bytes(raw) if raw is not None else None
                call.raw_sha256 = hashlib.sha256(raw).hexdigest() if raw is not None else None
                call.diagnostic = diagnostic
                call.state = CallState.RECORDED.value
                call.recorded_at = database_now(session)
                return self._call_snapshot(call)

    def get_call(self, *, scope: ProductScope, call_id: str) -> CallSnapshot:
        with self._session_factory() as session:
            return self._call_snapshot(self._call(session, scope, call_id))

    def unsettled_dispatch_count(self, *, scope: ProductScope, run_id: str) -> int:
        """Metadata-only accounting; never load raw responses for progress polls."""
        with self._session_factory() as session:
            self._run(session, scope, run_id)
            return int(
                session.scalar(
                    select(func.count(ProductModelCall.id)).where(
                        ProductModelCall.run_id == run_id,
                        ProductModelCall.space_id == scope.space_id,
                        ProductModelCall.dispatched_at.is_not(None),
                        ProductModelCall.state != CallState.RECORDED.value,
                    )
                )
                or 0
            )

    def list_calls(self, *, scope: ProductScope, run_id: str) -> tuple[CallSnapshot, ...]:
        with self._session_factory() as session:
            self._run(session, scope, run_id)
            rows = session.scalars(
                select(ProductModelCall)
                .where(
                    ProductModelCall.run_id == run_id,
                    ProductModelCall.space_id == scope.space_id,
                )
                .order_by(ProductModelCall.reserved_at, ProductModelCall.id)
            ).all()
            return tuple(self._call_snapshot(row) for row in rows)

    def settle_window(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        job_id: str,
        generation: int,
        outcomes: tuple[FieldOutcomeWrite, ...],
        usage: Mapping[str, int] | None = None,
    ) -> WindowSettlement:
        result, settlement = self.prepare_window_settlement(
            scope=scope,
            run_id=run_id,
            job_id=job_id,
            generation=generation,
            outcomes=outcomes,
            usage=usage,
        )
        self._jobs.report_success(
            space_id=scope.space_id,
            job_id=job_id,
            generation=generation,
            domain_writes=result.domain_writes,
            events=result.events,
        )
        return settlement

    def prepare_window_settlement(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        job_id: str,
        generation: int,
        outcomes: tuple[FieldOutcomeWrite, ...],
        usage: Mapping[str, int] | None = None,
    ) -> tuple[HandlerResult, WindowSettlement]:
        """Return the sole declarative completion payload for WorkerLoop."""
        # Preserve the P1 fencing error as the primary contract even for malformed
        # or empty worker output. The eventual write is fenced again atomically by
        # JobStore.report_success below.
        with self._session_factory() as fence_session:
            with fence_session.begin():
                active_job = self._active_job(fence_session, scope, job_id, generation)
                execution_attempt = active_job.attempt
        with self._session_factory() as session:
            window = self._window_for_job(session, scope, run_id, job_id)
            tasks = tuple(WindowTaskSpec.model_validate(item) for item in window.tasks)
            task_by_field = {(task.entity_id, task.field_key): task for task in tasks}
            outcome_keys = {
                (item.entity_id or item.cache_identity.entity_id, item.field_key)
                for item in outcomes
            }
            if len(outcome_keys) != len(outcomes) or not outcome_keys.issubset(task_by_field):
                raise ValueError("outcomes must be unique members of the sealed window")
            if window.selected_field_keys is None:
                raise ValueError("window must be reserved before settlement")
            selected_keys = {tuple(item) for item in window.selected_field_keys}
            cached_by_id = self._attempts_by_id(
                session, scope, tuple(window.cached_attempt_ids or ())
            )
            cached = {item.cache_identity.cache_key: item for item in cached_by_id.values()}
            if outcome_keys != selected_keys:
                raise ValueError("outcomes must exactly cover every non-cached window field")
            outcome_by_key = {
                (item.entity_id or item.cache_identity.entity_id, item.field_key): item
                for item in outcomes
            }
            calls = session.scalars(
                select(ProductModelCall).where(ProductModelCall.window_id == window.id)
            ).all()
            call_by_ref = {call.raw_ref: call for call in calls}
            now = database_now(session)
        writes: list[DomainWriteSpec] = []
        materialized_outcomes: list[FieldOutcomeWrite] = []
        call_id_by_key: dict[tuple[str, str], str] = {}
        for task_key, task in task_by_field.items():
            outcome = outcome_by_key.get(task_key)
            if outcome is None:
                reused = cached[task.cache_identity.cache_key]
                outcome = FieldOutcomeWrite(
                    entity_id=task.entity_id,
                    field_key=task.field_key,
                    task_sha256=reused.task_sha256,
                    cache_identity=reused.cache_identity,
                    outcome=reused.outcome,
                    reason=reused.reason,
                    validated_result=reused.validated_result,
                    raw_ref=reused.raw_ref,
                )
                call_id_by_key[task_key] = reused.call_id
            else:
                call = call_by_ref.get(outcome.raw_ref)
                if call is None:
                    raise ValueError("outcome raw_ref is not owned by the window")
                call_id_by_key[task_key] = call.call_id
            materialized_outcomes.append(outcome)
            writes.append(
                DomainWriteSpec(
                    table=ProductFieldAttempt.__tablename__,
                    values={
                        "id": _uuid(),
                        "run_id": run_id,
                        "window_id": window.id,
                        "call_id": call_id_by_key[task_key],
                        "tenant_id": scope.tenant_id,
                        "space_id": scope.space_id,
                        "entity_id": task.entity_id,
                        "field_key": task.field_key,
                        "task_sha256": (
                            reused.task_sha256
                            if outcome_by_key.get(task_key) is None
                            else task.task_sha256
                        ),
                        "cache_key": outcome.cache_identity.cache_key,
                        "cache_identity": outcome.cache_identity.model_dump(mode="json"),
                        "validation_version": (
                            reused.validation_version
                            if outcome_by_key.get(task_key) is None
                            else task.validation_version
                        ),
                        "model_policy_sha256": (
                            reused.model_policy_sha256
                            if outcome_by_key.get(task_key) is None
                            else task.model_policy_sha256
                        ),
                        "prompt_policy_sha256": (
                            reused.prompt_policy_sha256
                            if outcome_by_key.get(task_key) is None
                            else task.prompt_policy_sha256
                        ),
                        "outcome": outcome.outcome.value,
                        "reason": outcome.reason,
                        "validated_result": outcome.validated_result,
                        "raw_ref": outcome.raw_ref,
                        "attempt": execution_attempt,
                        "created_at": now,
                        "reused_from_attempt_id": (
                            reused.attempt_id if outcome_by_key.get(task_key) is None else None
                        ),
                    },
                )
            )
        success = sum(item.outcome is FieldOutcomeKind.VERIFIED for item in materialized_outcomes)
        missing = sum(
            item.outcome is FieldOutcomeKind.NOT_PROVIDED for item in materialized_outcomes
        )
        failed = sum(
            item.outcome is FieldOutcomeKind.EXTRACTION_FAILED for item in materialized_outcomes
        )
        writes.append(
            DomainWriteSpec(
                table=ProductWindowSettlement.__tablename__,
                values={
                    "id": _uuid(),
                    "window_id": window.id,
                    "run_id": run_id,
                    "space_id": scope.space_id,
                    "success_count": success,
                    "missing_count": missing,
                    "failure_count": failed,
                    "usage": dict(usage or {}),
                    "finished_at": now,
                },
            )
        )
        result = HandlerResult(
            domain_writes=tuple(writes),
            events=(
                OutboxEventDraft(
                    event_id=_uuid(),
                    event_type="product.window.settled",
                    payload={
                        "run_id": run_id,
                        "window_id": window.id,
                        "success_count": success,
                        "missing_count": missing,
                        "failure_count": failed,
                    },
                ),
            ),
        )
        return (
            result,
            WindowSettlement(success_count=success, missing_count=missing, failure_count=failed),
        )

    def list_field_attempts(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        field_keys: Sequence[str] | None = None,
    ) -> tuple[FieldAttemptSnapshot, ...]:
        from insurance_harness.product_ingestion.field_validation import apply_field_validation

        originals = self.list_original_field_attempts(scope=scope, run_id=run_id)
        report = self._field_validation_report(scope, run_id)
        effective = apply_field_validation(originals, report) if report is not None else originals
        return tuple(row for row in effective if field_keys is None or row.field_key in field_keys)

    def _field_validation_report(
        self,
        scope: ProductScope,
        run_id: str,
    ) -> FieldValidationReport | None:
        from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
        from insurance_harness.product_ingestion.field_validation import FieldValidationReport

        rows = ProductArtifactStore(self._session_factory, self).list_effective_artifacts(
            scope=scope, run_id=run_id, artifact_kind="field_validation"
        )
        if not rows:
            return None
        if len(rows) != 1 or (
            rows[0].artifact_key,
            rows[0].contract_name,
            rows[0].contract_version,
        ) != ("product", "product-field_validation.v1", "1"):
            raise ValueError("field validation artifact contract mismatch")
        return FieldValidationReport.model_validate_json(rows[0].payload)

    def list_original_field_attempts(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        field_keys: Sequence[str] | None = None,
    ) -> tuple[FieldAttemptSnapshot, ...]:
        with self._session_factory() as session:
            self._run(session, scope, run_id)
            query = select(ProductFieldAttempt).where(
                ProductFieldAttempt.tenant_id == scope.tenant_id,
                ProductFieldAttempt.space_id == scope.space_id,
                ProductFieldAttempt.run_id == run_id,
            )
            if field_keys is not None:
                query = query.where(ProductFieldAttempt.field_key.in_(tuple(field_keys)))
            rows = session.scalars(
                query.order_by(ProductFieldAttempt.created_at, ProductFieldAttempt.id)
            ).all()
            result = [self._field_snapshot(row) for row in rows]
            refs, receipt = self.checkpoint_field_references(session, scope, run_id)
            if refs:
                if receipt is None:
                    raise ValueError("checkpoint field receipt is missing")
                from insurance_harness.product_ingestion.checkpoints import field_digest

                for ref in refs:
                    if field_keys is not None and ref.field_key not in field_keys:
                        continue
                    row = session.get(ProductFieldAttempt, ref.attempt_id)
                    if (
                        row is None
                        or row.tenant_id != scope.tenant_id
                        or row.space_id != scope.space_id
                    ):
                        raise ValueError("referenced field is missing or foreign")
                    value = self._field_snapshot(row)
                    if field_digest(value) != receipt.field_sha256[ref.attempt_id]:
                        raise ValueError("referenced field changed after verification")
                    result.append(value)
            return tuple(sorted(result, key=lambda row: (row.created_at, row.attempt_id)))

    def lookup_cached_fields(
        self, *, scope: ProductScope, identities: Sequence[FieldCacheIdentity]
    ) -> dict[str, FieldAttemptSnapshot]:
        with self._session_factory() as session:
            return self._lookup_cache(session, scope, identities)

    def _can_retry_processing(
        self,
        session: Session,
        scope: ProductScope,
        row: ProductRun,
        *,
        verify_sources: bool = True,
    ) -> bool:
        run = self._run_snapshot(session, row, scope)
        title_retry = (
            run.state is ProductRunState.NEEDS_CONFIRMATION
            and run.terminal_reason == "FIRST_PAGE_PRODUCT_NAME_UNAVAILABLE"
        )
        identity_retry = run.state is ProductRunState.NEEDS_CONFIRMATION and (
            run.terminal_reason or ""
        ).startswith("IDENTITY_RESPONSE_INVALID:")
        plan_retry = (
            run.state is ProductRunState.FAILED
            and run.terminal_reason == "PRODUCT_STAGE_FAILED:field_plan"
        )
        replay_retry = (
            run.state is ProductRunState.FAILED
            and run.terminal_reason == "PRODUCT_STAGE_FAILED:identity"
            and row.idempotency_key.startswith(RECOVERY_V3_PREFIX)
        )
        extract_retry = run.state is ProductRunState.FAILED and run.terminal_reason in {
            "PRODUCT_STAGE_FAILED:extract",
            "FIELD_WINDOW_TERMINAL_RESULTS_INCOMPLETE",
        }
        if (
            not (title_retry or identity_retry or plan_retry or replay_retry or extract_retry)
            and (
                run.state is not ProductRunState.FAILED
                or run.terminal_reason != "PRODUCT_STAGE_FAILED:source"
            )
            or run.finished_at is None
            or run.uploads_sealed_at is None
            or len(run.materials) != run.expected_upload_count
            or tuple(m.upload_ordinal for m in run.materials)
            != tuple(range(run.expected_upload_count))
            or (
                any(m.source is None for m in run.materials)
                if plan_retry
                else not (replay_retry or extract_retry)
                and any(m.source is not None for m in run.materials)
            )
        ):
            return False
        stages = session.execute(
            select(ProductStage.stage_key, WikiJob.state, WikiJob.error_summary)
            .join(WikiJob, WikiJob.id == ProductStage.job_id)
            .where(ProductStage.run_id == row.id, ProductStage.space_id == scope.space_id)
        ).all()
        expected_stages = {"uploads", "source", "routing"} if title_retry else {"uploads", "source"}
        if identity_retry or replay_retry:
            expected_stages = {"uploads", "source", "routing", "identity"}
        if plan_retry:
            expected_stages = {"uploads", "source", "routing", "identity", "field_plan"}
        if extract_retry:
            expected_stages = {
                "uploads",
                "source",
                "routing",
                "identity",
                "field_plan",
                "extract",
            }
        if {stage.stage_key for stage in stages} != expected_stages:
            return False
        source = next(stage for stage in stages if stage.stage_key == "source")
        if plan_retry or replay_retry or extract_retry:
            by_stage = {stage.stage_key: stage for stage in stages}
            failed_stage = (
                "extract" if extract_retry else "field_plan" if plan_retry else "identity"
            )
            if (
                any(by_stage[key].state != "succeeded" for key in expected_stages - {failed_stage})
                or by_stage[failed_stage].state != "dead_letter"
                or self._recovery_source_refs(session, scope, run, verify_payloads=verify_sources)
                is None
                or self._recorded_identity_ref(session, scope, run, verify_sources=verify_sources)
                is None
            ):
                return False
            if extract_retry and (
                not (by_stage["extract"].error_summary or "").endswith(
                    "FIELD_WINDOW_TERMINAL_RESULTS_INCOMPLETE"
                )
                or not self._undispatched_failed_windows(session, scope, run.run_id)
            ):
                return False
        elif identity_retry:
            by_stage = {stage.stage_key: stage for stage in stages}
            if (
                source.state != "succeeded"
                or by_stage["routing"].state != "succeeded"
                or by_stage["identity"].state != "blocked"
                or "needs_confirmation:IDENTITY_RESPONSE_INVALID:"
                not in (by_stage["identity"].error_summary or "")
                or self._recovery_source_refs(session, scope, run, verify_payloads=verify_sources)
                is None
                or self._recorded_identity_ref(session, scope, run, verify_sources=verify_sources)
                is None
            ):
                return False
        elif title_retry:
            routing = next(stage for stage in stages if stage.stage_key == "routing")
            if (
                source.state != "succeeded"
                or routing.state != "blocked"
                or not routing.error_summary
                or not routing.error_summary.endswith(
                    "needs_confirmation:FIRST_PAGE_PRODUCT_NAME_UNAVAILABLE"
                )
                or self._recovery_source_refs(session, scope, run, verify_payloads=verify_sources)
                is None
            ):
                return False
        elif (
            source.state != "dead_letter"
            or not source.error_summary
            or any(
                code in source.error_summary
                for code in (
                    "ORIGINAL_UPLOAD_BINDING_CHANGED",
                    "needs_confirmation:",
                )
            )
        ):
            return False
        for table in (ProductStageModelCall, ProductWindow, ProductFieldAttempt):
            if (
                identity_retry or plan_retry or replay_retry or extract_retry
            ) and table is ProductStageModelCall:
                continue
            if extract_retry and table is ProductWindow:
                continue
            if session.scalar(select(table.id).where(table.run_id == row.id).limit(1)):
                return False
        return True

    @staticmethod
    def _undispatched_failed_windows(
        session: Session,
        scope: ProductScope,
        run_id: str,
    ) -> bool:
        """Only abandon wholly unstarted field work; never replay uncertain calls."""
        windows = session.execute(
            select(
                ProductWindow.id.label("window_id"),
                ProductWindow.window_key,
                ProductWindow.space_id,
                ProductWindow.stage_key,
                ProductWindow.job_id,
                WikiJob.space_id.label("job_space"),
                WikiJob.state,
                WikiJob.job_type,
                WikiJob.payload,
            )
            .outerjoin(WikiJob, WikiJob.id == ProductWindow.job_id)
            .where(ProductWindow.run_id == run_id)
        ).all()
        if not windows or any(
            row.space_id != scope.space_id
            or row.job_space != scope.space_id
            or row.stage_key != "extract"
            or row.state not in {"dead_letter", "blocked"}
            or row.job_type != "product_extraction_window"
            or not isinstance(row.payload, dict)
            or row.payload.get("run_id") != run_id
            or row.payload.get("stage_key") != row.stage_key
            or row.payload.get("window_key") != row.window_key
            for row in windows
        ):
            return False
        bindings = {row.window_id: row.job_id for row in windows}
        if session.scalar(
            select(ProductFieldAttempt.id)
            .where(
                or_(
                    ProductFieldAttempt.run_id == run_id,
                    ProductFieldAttempt.window_id.in_(tuple(bindings)),
                )
            )
            .limit(1)
        ):
            return False
        calls = session.execute(
            select(
                ProductModelCall.run_id,
                ProductModelCall.window_id,
                ProductModelCall.job_id,
                ProductModelCall.space_id,
                ProductModelCall.state,
                ProductModelCall.dispatched_at,
                ProductModelCall.recorded_at,
                ProductModelCall.request_sha256,
                ProductModelCall.raw_sha256,
                ProductModelCall.raw.is_not(None).label("has_raw"),
                ProductModelCall.request_bytes.is_not(None).label("has_request"),
            ).where(
                or_(
                    ProductModelCall.run_id == run_id,
                    ProductModelCall.window_id.in_(tuple(bindings)),
                    ProductModelCall.job_id.in_(tuple(bindings.values())),
                )
            )
        ).all()
        return all(
            row.run_id == run_id
            and row.space_id == scope.space_id
            and bindings.get(row.window_id) == row.job_id
            and row.state == "reserved"
            and row.dispatched_at is None
            and row.recorded_at is None
            and row.request_sha256 is None
            and row.raw_sha256 is None
            and not row.has_raw
            and not row.has_request
            for row in calls
        )

    def _recorded_identity_ref(
        self,
        session: Session,
        scope: ProductScope,
        run: ProductRunSnapshot,
        *,
        read_lock: bool = False,
        verify_sources: bool = True,
    ) -> RecordedIdentityReference | None:
        """Resolve only an intact recorded call through verified recovery ancestry."""
        seen = set()
        expected_refs: list[RecordedIdentityReference] = []
        try:
            while run.run_id not in seen:
                seen.add(run.run_id)
                statement = (
                    select(ProductStageModelCall)
                    .where(
                        ProductStageModelCall.run_id == run.run_id,
                        ProductStageModelCall.space_id == scope.space_id,
                    )
                    .order_by(ProductStageModelCall.id)
                )
                if read_lock:
                    statement = statement.with_for_update(read=True)
                calls = session.scalars(statement).all()
                if calls:
                    # Recorded-identity recoveries may only replay their bound
                    # ancestor. A new call on such a run cannot replace it.
                    replay_run = self._run(session, scope, run.run_id)
                    if len(calls) != 1 or replay_run.idempotency_key.startswith(RECOVERY_V3_PREFIX):
                        return None
                    reference = recorded_identity_reference(calls[0])
                    return reference if all(row == reference for row in expected_refs) else None
                plan = self.processing_recovery_plan(
                    scope=scope, run_id=run.run_id, session=session, read_lock=read_lock
                )
                if not isinstance(plan, RecordedIdentityRecoveryPlan):
                    return None
                origin = self._run_snapshot(
                    session, self._run(session, scope, plan.origin_run_id), scope
                )
                if (
                    origin.version != plan.origin_version
                    or material_references(origin) != plan.materials
                    or self._recovery_source_refs(
                        session,
                        scope,
                        run,
                        read_lock=read_lock,
                        verify_payloads=verify_sources,
                    )
                    != plan.source_snapshots
                    or self._recovery_source_refs(
                        session,
                        scope,
                        origin,
                        read_lock=read_lock,
                        verify_payloads=verify_sources,
                    )
                    != plan.source_snapshots
                ):
                    return None
                expected_refs.append(plan.identity_call)
                run = origin
        except (ValueError, TypeError):
            return None
        return None

    @staticmethod
    def _recovery_source_refs(
        session: Session,
        scope: ProductScope,
        run: ProductRunSnapshot,
        *,
        read_lock: bool = False,
        verify_payloads: bool = True,
    ) -> tuple[SourceSnapshotReference, ...] | None:
        columns = (
            (ProductArtifact,)
            if verify_payloads
            else (ProductArtifact.artifact_key, ProductArtifact.payload_sha256)
        )
        statement = (
            select(*columns)
            .where(
                ProductArtifact.run_id == run.run_id,
                ProductArtifact.space_id == scope.space_id,
                ProductArtifact.artifact_kind == "source_snapshot",
            )
            .order_by(ProductArtifact.id)
        )
        if read_lock:
            statement = statement.with_for_update(read=True)
        saved = (
            session.scalars(statement) if verify_payloads else session.execute(statement)
        ).all()
        by_key = {item.artifact_key: item for item in saved}
        if len(saved) != len(run.materials) or set(by_key) != {
            m.knowledge_id for m in run.materials
        }:
            return None
        if verify_payloads and any(
            hashlib.sha256(item.payload).hexdigest() != item.payload_sha256 for item in saved
        ):
            return None
        return tuple(
            SourceSnapshotReference(
                knowledge_id=m.knowledge_id,
                payload_sha256=by_key[m.knowledge_id].payload_sha256,
            )
            for m in run.materials
        )

    def _legacy_can_retry_processing(self, *, scope: ProductScope, run_id: str) -> bool:
        """Lightweight display hint; retry_processing and the worker fully revalidate."""
        with self._session_factory() as session:
            return self._can_retry_processing(
                session, scope, self._run(session, scope, run_id), verify_sources=False
            )

    def processing_recovery_plan(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        session: Session | None = None,
        read_lock: bool = False,
    ) -> ProcessingRecoveryPlan | SealedSourceRecoveryPlan | RecordedIdentityRecoveryPlan | None:
        if session is None:
            with self._session_factory() as owned_session:
                return self.processing_recovery_plan(
                    scope=scope,
                    run_id=run_id,
                    session=owned_session,
                    read_lock=read_lock,
                )
        row = self._run(session, scope, run_id)
        v2 = row.idempotency_key.startswith(RECOVERY_V2_PREFIX)
        v3 = row.idempotency_key.startswith(RECOVERY_V3_PREFIX)
        if not (v2 or v3) and not row.idempotency_key.startswith(RECOVERY_PREFIX):
            return None
        statement = select(ProductArtifact).where(
            ProductArtifact.run_id == run_id,
            ProductArtifact.space_id == scope.space_id,
            ProductArtifact.artifact_kind == RECOVERY_KIND,
            ProductArtifact.artifact_key == "product",
        )
        if read_lock:
            statement = statement.with_for_update(read=True)
        saved = session.scalar(statement)
        if saved is None or hashlib.sha256(saved.payload).hexdigest() != saved.payload_sha256:
            raise ValueError("processing recovery plan unavailable")
        plan_type = (
            RecordedIdentityRecoveryPlan
            if v3
            else SealedSourceRecoveryPlan
            if v2
            else ProcessingRecoveryPlan
        )
        prefix = RECOVERY_V3_PREFIX if v3 else RECOVERY_V2_PREFIX if v2 else RECOVERY_PREFIX
        plan = plan_type.model_validate_json(saved.payload)
        run = self._run_snapshot(session, row, scope)
        if (
            plan.scope != scope
            or plan.origin_run_id != row.retry_of_run_id
            or row.idempotency_key != prefix + plan.digest()
            or plan.materials != material_references(run)
            or (
                isinstance(plan, (SealedSourceRecoveryPlan, RecordedIdentityRecoveryPlan))
                and tuple(r.knowledge_id for r in plan.source_snapshots)
                != tuple(m.knowledge_id for m in plan.materials)
            )
        ):
            raise ValueError("processing recovery plan binding changed")
        return plan

    def _legacy_retry_processing(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        expected_version: int,
    ) -> ProductRunSnapshot:
        if type(expected_version) is not int or expected_version <= 0:
            raise ValueError("expected_version must be a positive integer")
        with self._session_factory() as session, session.begin():
            origin = self._run(session, scope, run_id, lock=True)
            if origin.version != expected_version or not self._can_retry_processing(
                session, scope, origin
            ):
                raise ValueError("source recovery is unavailable or version changed")
            upload_origin = origin
            seen = {origin.id}
            while upload_origin.retry_of_run_id:
                if upload_origin.retry_of_run_id in seen:
                    raise ValueError("recovery ancestry cycle")
                upload_origin = self._run(session, scope, upload_origin.retry_of_run_id)
                seen.add(upload_origin.id)
            origin_run = self._run_snapshot(session, origin, scope)
            title_retry = origin_run.state is ProductRunState.NEEDS_CONFIRMATION
            identity_retry = (origin_run.terminal_reason or "").startswith(
                "IDENTITY_RESPONSE_INVALID:"
            ) or origin_run.terminal_reason in {
                "PRODUCT_STAGE_FAILED:field_plan",
                "PRODUCT_STAGE_FAILED:identity",
                "PRODUCT_STAGE_FAILED:extract",
                "FIELD_WINDOW_TERMINAL_RESULTS_INCOMPLETE",
            }
            if identity_retry:
                source_refs = self._recovery_source_refs(session, scope, origin_run)
                identity_ref = self._recorded_identity_ref(session, scope, origin_run)
                if source_refs is None or identity_ref is None:
                    raise ValueError("identity recovery inputs are unavailable")
                plan: (
                    ProcessingRecoveryPlan
                    | SealedSourceRecoveryPlan
                    | RecordedIdentityRecoveryPlan
                )
                plan = RecordedIdentityRecoveryPlan(
                    scope=scope,
                    origin_run_id=run_id,
                    origin_version=expected_version,
                    upload_run_id=upload_origin.id,
                    materials=material_references(origin_run),
                    source_snapshots=source_refs,
                    identity_call=identity_ref,
                )
            elif title_retry:
                source_refs = self._recovery_source_refs(session, scope, origin_run)
                if source_refs is None:
                    raise ValueError("sealed source recovery inputs are unavailable")
                plan = SealedSourceRecoveryPlan(
                    scope=scope,
                    origin_run_id=run_id,
                    origin_version=expected_version,
                    upload_run_id=upload_origin.id,
                    materials=material_references(origin_run),
                    source_snapshots=source_refs,
                )
            else:
                plan = ProcessingRecoveryPlan(
                    scope=scope,
                    origin_run_id=run_id,
                    origin_version=expected_version,
                    upload_run_id=upload_origin.id,
                    materials=material_references(origin_run),
                )
            prefix = (
                RECOVERY_V3_PREFIX
                if identity_retry
                else RECOVERY_V2_PREFIX
                if title_retry
                else RECOVERY_PREFIX
            )
            identity = prefix + plan.digest()
            existing = session.scalar(
                select(ProductRun).where(
                    ProductRun.tenant_id == scope.tenant_id,
                    ProductRun.space_id == scope.space_id,
                    ProductRun.idempotency_key == identity,
                )
            )
            if existing is not None:
                self._check_scope(existing, scope)
                return self._run_snapshot(session, existing, scope)
            child_id = str(uuid5(NAMESPACE_URL, identity))
            stage_id = str(
                uuid5(NAMESPACE_URL, f"product-stage:{scope.space_id}:{child_id}:uploads")
            )
            dependency = hashlib.sha256(("product-uploads.v1\0" + child_id).encode()).hexdigest()
            job_id = str(uuid5(NAMESPACE_URL, f"product-stage-job:{stage_id}:{dependency}"))
            now = database_now(session)
            aware_source_deadline = _aware(origin.source_deadline_at)
            aware_upload_deadline = _aware(origin.upload_deadline_at)
            if aware_source_deadline is None or aware_upload_deadline is None:
                raise ValueError("recovery origin deadlines are incomplete")
            duration = aware_source_deadline - aware_upload_deadline
            if duration <= timedelta(0):
                duration = timedelta(hours=1)
            values = {
                "id": child_id,
                "tenant_id": scope.tenant_id,
                "space_id": scope.space_id,
                "raw_knowledge_base_id": scope.raw_knowledge_base_id,
                "wiki_knowledge_base_id": scope.wiki_knowledge_base_id,
                "idempotency_key": identity,
                "retry_of_run_id": run_id,
                "attempt": origin.attempt + 1,
                "retry_field_keys": [],
                "expected_upload_count": origin.expected_upload_count,
                "upload_deadline_at": now + timedelta(minutes=1),
                "source_deadline_at": now + timedelta(minutes=1) + duration,
                "uploads_sealed_at": now,
                "uploads_sealed": True,
                "state": ProductRunState.AWAITING_SOURCES.value,
                "version": 1,
                "workflow_version": origin.workflow_version,
                "created_at": now,
                "started_at": now,
                "root_job_id": None,
            }
            writes = [DomainWriteSpec(table=ProductRun.__tablename__, values=values)]
            for material in plan.materials:
                writes.append(
                    DomainWriteSpec(
                        table=ProductMaterial.__tablename__,
                        values={
                            "id": str(
                                uuid5(
                                    NAMESPACE_URL,
                                    f"recovery-material:{child_id}:{material.upload_ordinal}",
                                )
                            ),
                            "run_id": child_id,
                            "tenant_id": scope.tenant_id,
                            "space_id": scope.space_id,
                            **material.model_dump(),
                        },
                    )
                )
            writes.extend(
                (
                    DomainWriteSpec(
                        table=ProductStage.__tablename__,
                        values={
                            "id": stage_id,
                            "run_id": child_id,
                            "space_id": scope.space_id,
                            "stage_key": "uploads",
                            "dependency_sha256": dependency,
                            "job_id": job_id,
                            "parent_job_id": None,
                            "created_at": now,
                        },
                    ),
                    DomainWriteSpec(
                        table=ProductArtifact.__tablename__,
                        values={
                            "id": str(uuid5(NAMESPACE_URL, "recovery-plan:" + child_id)),
                            "run_id": child_id,
                            "space_id": scope.space_id,
                            "stage_key": "uploads",
                            "artifact_kind": RECOVERY_KIND,
                            "artifact_key": "product",
                            "contract_name": plan.contract,
                            "contract_version": "3"
                            if identity_retry
                            else "2"
                            if title_retry
                            else "1",
                            "dependency_sha256": plan.digest(),
                            "payload": plan.encoded(),
                            "payload_sha256": plan.digest(),
                            "origin": "rule",
                            "origin_call_id": None,
                            "producer_job_id": job_id,
                            "producer_generation": 0,
                            "created_at": now,
                        },
                    ),
                )
            )
        # Terminal origins cannot be mutated through the store. Admission intent,
        # references and the claimable job commit together through the P1 port.
        self._jobs.enqueue(
            space_id=scope.space_id,
            job_type="product_stage_uploads",
            idempotency_key=f"{child_id}:uploads:{dependency}",
            job_id=job_id,
            payload={"run_id": child_id, "stage_key": "uploads"},
            domain_writes=tuple(writes),
        )
        return self.get_run(scope=scope, run_id=child_id)

    def retry_fields(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        failed_attempt_ids: Sequence[str],
        idempotency_key: str,
    ) -> ProductRunSnapshot:
        if not failed_attempt_ids:
            raise ValueError("failed_attempt_ids must not be empty")
        attempts = tuple(
            item
            for item in self.list_field_attempts(scope=scope, run_id=run_id)
            if item.attempt_id in failed_attempt_ids
        )
        if len(attempts) != len(set(failed_attempt_ids)) or any(
            item.outcome is not FieldOutcomeKind.EXTRACTION_FAILED for item in attempts
        ):
            raise ValueError("only extraction_failed field attempts may be retried")
        with self._session_factory() as session:
            with session.begin():
                origin = self._run(session, scope, run_id, lock=True)
                existing = session.execute(
                    select(ProductRun).where(
                        ProductRun.tenant_id == scope.tenant_id,
                        ProductRun.space_id == scope.space_id,
                        ProductRun.idempotency_key == idempotency_key,
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    self._check_scope(existing, scope)
                    return self._run_snapshot(session, existing, scope)
                now = database_now(session)
                origin_created = _aware(origin.created_at)
                origin_upload = _aware(origin.upload_deadline_at)
                origin_source = _aware(origin.source_deadline_at)
                assert origin_created is not None
                assert origin_upload is not None
                assert origin_source is not None
                upload_duration = origin_upload - origin_created
                source_duration = origin_source - origin_upload
                if upload_duration <= timedelta(0):
                    upload_duration = timedelta(hours=1)
                if source_duration <= timedelta(0):
                    source_duration = timedelta(hours=1)
                retry_upload_deadline = now + upload_duration
                retry_source_deadline = retry_upload_deadline + source_duration
                retry = ProductRun(
                    tenant_id=scope.tenant_id,
                    space_id=scope.space_id,
                    raw_knowledge_base_id=scope.raw_knowledge_base_id,
                    wiki_knowledge_base_id=scope.wiki_knowledge_base_id,
                    idempotency_key=idempotency_key,
                    retry_of_run_id=run_id,
                    attempt=origin.attempt + 1,
                    retry_field_keys=sorted({item.field_key for item in attempts}),
                    expected_upload_count=origin.expected_upload_count,
                    upload_deadline_at=retry_upload_deadline,
                    uploads_sealed_at=now,
                    source_deadline_at=retry_source_deadline,
                    state=ProductRunState.RUNNING.value,
                    version=1,
                    workflow_version=origin.workflow_version,
                    uploads_sealed=True,
                    created_at=now,
                    started_at=now,
                    root_job_id=None,
                )
                session.add(retry)
                session.flush()
                for material in session.scalars(
                    select(ProductMaterial).where(ProductMaterial.run_id == run_id)
                ):
                    session.add(
                        ProductMaterial(
                            run_id=retry.id,
                            tenant_id=material.tenant_id,
                            space_id=material.space_id,
                            knowledge_id=material.knowledge_id,
                            original_filename=material.original_filename,
                            upload_ordinal=material.upload_ordinal,
                            source_revision_id=material.source_revision_id,
                            source_sha256=material.source_sha256,
                            file_sha256=material.file_sha256,
                            native_manifest_sha256=material.native_manifest_sha256,
                            page_count=material.page_count,
                            inferred_material_role=material.inferred_material_role,
                            product_identity_sha256=material.product_identity_sha256,
                        )
                    )
                session.flush()
                return self._run_snapshot(session, retry, scope)

    def finalize_run(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        job_id: str,
        generation: int,
        terminal_state: ProductRunState,
    ) -> ProductRunSnapshot:
        result = self.prepare_run_finalization(
            scope=scope,
            run_id=run_id,
            job_id=job_id,
            generation=generation,
            terminal_state=terminal_state,
        )
        self._jobs.report_success(
            space_id=scope.space_id,
            job_id=job_id,
            generation=generation,
            domain_writes=result.domain_writes,
            events=result.events,
        )
        return self.get_run(scope=scope, run_id=run_id)

    def prepare_run_finalization(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        job_id: str,
        generation: int,
        terminal_state: ProductRunState,
    ) -> HandlerResult:
        if terminal_state not in {
            ProductRunState.SUCCEEDED,
            ProductRunState.PARTIAL_SUCCESS,
            ProductRunState.FAILED,
        }:
            raise ValueError("needs_confirmation must terminate through P1 BLOCKED")
        with self._session_factory() as session:
            with session.begin():
                self._active_job(session, scope, job_id, generation)
            run = self._run(session, scope, run_id)
            if run.root_job_id != job_id:
                raise ValueError("finalization job is not the run root")
            existing = session.execute(
                select(ProductRunFinalization).where(ProductRunFinalization.run_id == run_id)
            ).scalar_one_or_none()
            if existing is not None:
                raise ValueError("finished run is immutable")
            counts = self._counts(session, run_id)
            settlements = session.scalars(
                select(ProductWindowSettlement).where(ProductWindowSettlement.run_id == run_id)
            ).all()
            model_call_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(ProductModelCall)
                    .where(
                        ProductModelCall.run_id == run_id,
                        ProductModelCall.dispatched_at.is_not(None),
                    )
                )
                or 0
            )
            usage = self._sum_usage(settlements)
            now = database_now(session)
            started = _aware(run.started_at) or _aware(run.created_at)
            assert started is not None
        return HandlerResult(
            domain_writes=(
                DomainWriteSpec(
                    table=ProductRunFinalization.__tablename__,
                    values={
                        "id": _uuid(),
                        "run_id": run_id,
                        "space_id": scope.space_id,
                        "state": terminal_state.value,
                        "success_count": counts[0],
                        "missing_count": counts[1],
                        "failure_count": counts[2],
                        "model_call_count": model_call_count,
                        "usage": usage,
                        "started_at": started,
                        "finished_at": now,
                    },
                ),
            ),
            events=(
                OutboxEventDraft(
                    event_id=_uuid(),
                    event_type="product.run.finished",
                    payload={"run_id": run_id, "state": terminal_state.value},
                ),
            ),
        )

    def finalize_needs_confirmation(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        job_id: str,
        generation: int,
        reason: str,
    ) -> ProductRunSnapshot:
        if not reason.strip():
            raise ValueError("needs_confirmation requires a reason")
        run = self.get_run(scope=scope, run_id=run_id)
        if run.state is ProductRunState.NEEDS_CONFIRMATION:
            if run.terminal_reason == reason:
                return run
            raise ValueError("needs_confirmation reason is immutable")
        with self._session_factory() as session:
            row = self._run(session, scope, run_id)
            if row.root_job_id != job_id:
                raise ValueError("confirmation job is not the run root")
        self._jobs.report_failure(
            space_id=scope.space_id,
            job_id=job_id,
            generation=generation,
            failure=JobFailure(
                error_class=ErrorClass.CAPACITY_BLOCKED,
                summary=_NEEDS_CONFIRMATION_PREFIX + reason,
            ),
        )
        return self.get_run(scope=scope, run_id=run.run_id)

    def _run(
        self, session: Session, scope: ProductScope, run_id: str, *, lock: bool = False
    ) -> ProductRun:
        query = select(ProductRun).where(ProductRun.id == run_id)
        if lock:
            query = query.with_for_update()
        row = session.execute(query).scalar_one_or_none()
        if row is None:
            raise SpaceScopeError()
        self._check_scope(row, scope)
        return row

    @staticmethod
    def _check_scope(row: ProductRun, scope: ProductScope) -> None:
        actual = (
            row.tenant_id,
            row.space_id,
            row.raw_knowledge_base_id,
            row.wiki_knowledge_base_id,
        )
        expected = (
            scope.tenant_id,
            scope.space_id,
            scope.raw_knowledge_base_id,
            scope.wiki_knowledge_base_id,
        )
        if actual != expected:
            raise SpaceScopeError()

    @staticmethod
    def _mutable_run(row: ProductRun, expected_version: int) -> None:
        if row.version != expected_version:
            raise ValueError("run version changed")
        if row.uploads_sealed:
            raise ValueError("uploads are already sealed")

    @staticmethod
    def _ensure_unfinished(session: Session, row: ProductRun) -> None:
        finished = session.scalar(
            select(ProductRunFinalization.id).where(ProductRunFinalization.run_id == row.id)
        )
        if finished is not None:
            raise ValueError("finished run is immutable")

    def _run_snapshot(
        self, session: Session, row: ProductRun, scope: ProductScope
    ) -> ProductRunSnapshot:
        materials = session.scalars(
            select(ProductMaterial)
            .where(ProductMaterial.run_id == row.id)
            .order_by(ProductMaterial.upload_ordinal)
        ).all()
        final = session.execute(
            select(ProductRunFinalization).where(ProductRunFinalization.run_id == row.id)
        ).scalar_one_or_none()
        material_snapshots = tuple(self._material_snapshot(item) for item in materials)
        if final is not None:
            state = ProductRunState(final.state)
            success, missing, failure = (
                final.success_count,
                final.missing_count,
                final.failure_count,
            )
            model_call_count = final.model_call_count
            usage = dict(final.usage)
            started_at = _aware(final.started_at)
            finished_at = _aware(final.finished_at)
            terminal_reason = None
            if state is ProductRunState.FAILED:
                failed = session.execute(
                    select(ProductStage.stage_key, WikiJob.error_summary)
                    .join(WikiJob, WikiJob.id == ProductStage.job_id)
                    .where(
                        ProductStage.run_id == row.id,
                        ProductStage.space_id == scope.space_id,
                        WikiJob.state.in_(("blocked", "dead_letter")),
                    )
                    .order_by(ProductStage.created_at, ProductStage.id)
                    .limit(1)
                ).first()
                if failed is not None:
                    key, summary = failed
                    # Unexpected exception text can contain model input. Publish
                    # only a stable reason code; full diagnostics stay in P1.
                    terminal_reason = (
                        summary
                        if summary and re.fullmatch(r"[A-Z][A-Z0-9_:.-]{0,199}", summary)
                        else "PRODUCT_STAGE_FAILED:" + key
                    )
        else:
            state = ProductRunState(row.state)
            success, missing, failure = self._counts(session, row.id)
            settlements = session.scalars(
                select(ProductWindowSettlement).where(ProductWindowSettlement.run_id == row.id)
            ).all()
            model_call_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(ProductModelCall)
                    .where(
                        ProductModelCall.run_id == row.id,
                        ProductModelCall.dispatched_at.is_not(None),
                    )
                )
                or 0
            )
            usage = self._sum_usage(settlements)
            started_at = _aware(row.started_at)
            finished_at = None
            terminal_reason = None
            if row.root_job_id is not None:
                root_job = session.get(WikiJob, row.root_job_id)
                if root_job is not None and root_job.state in {
                    JobState.BLOCKED.value,
                    JobState.DEAD_LETTER.value,
                }:
                    finished_at = _aware(root_job.finished_at)
                    summary = root_job.error_summary or root_job.state
                    if (
                        root_job.state == JobState.BLOCKED.value
                        and root_job.error_class == ErrorClass.CAPACITY_BLOCKED.value
                        and _NEEDS_CONFIRMATION_PREFIX in summary
                    ):
                        state = ProductRunState.NEEDS_CONFIRMATION
                        terminal_reason = summary.partition(_NEEDS_CONFIRMATION_PREFIX)[2]
                    else:
                        state = ProductRunState.FAILED
                        terminal_reason = summary
        created_at = _aware(row.created_at)
        upload_deadline_at = _aware(row.upload_deadline_at)
        source_deadline_at = _aware(row.source_deadline_at)
        if created_at is None or upload_deadline_at is None or source_deadline_at is None:
            raise ValueError("run timestamps are incomplete")
        if row.workflow_version not in {1, 2, 3}:
            raise ValueError("unsupported product workflow version")
        workflow_version = cast(Literal[1, 2, 3], row.workflow_version)
        return ProductRunSnapshot(
            run_id=row.id,
            scope=scope,
            state=state,
            version=row.version,
            workflow_version=workflow_version,
            retry_of_run_id=row.retry_of_run_id,
            attempt=row.attempt,
            retry_field_keys=tuple(row.retry_field_keys),
            expected_upload_count=row.expected_upload_count,
            upload_deadline_at=upload_deadline_at,
            uploads_sealed_at=_aware(row.uploads_sealed_at),
            source_deadline_at=source_deadline_at,
            materials=material_snapshots,
            success_count=success,
            missing_count=missing,
            failure_count=failure,
            model_call_count=model_call_count,
            usage=usage,
            terminal_reason=terminal_reason,
            created_at=created_at,
            started_at=started_at,
            finished_at=finished_at,
        )

    @staticmethod
    def _material_snapshot(row: ProductMaterial) -> MaterialSnapshot:
        source = None
        if row.source_revision_id is not None:
            sealed_values = (
                row.source_sha256,
                row.file_sha256,
                row.native_manifest_sha256,
                row.page_count,
                row.inferred_material_role,
                row.product_identity_sha256,
            )
            if any(value is None for value in sealed_values):
                raise ValueError("sealed material metadata is incomplete")
            source = SealedSourceRef(
                knowledge_id=row.knowledge_id,
                source_revision_id=row.source_revision_id,
                source_sha256=cast(str, row.source_sha256),
                file_sha256=cast(str, row.file_sha256),
                native_manifest_sha256=cast(str, row.native_manifest_sha256),
                page_count=cast(int, row.page_count),
                inferred_material_role=cast(str, row.inferred_material_role),
                product_identity_sha256=cast(str, row.product_identity_sha256),
            )
        return MaterialSnapshot(
            material_id=row.id,
            knowledge_id=row.knowledge_id,
            original_filename=row.original_filename,
            upload_ordinal=row.upload_ordinal,
            source=source,
        )

    @staticmethod
    def _window_snapshot(row: ProductWindow) -> WindowSnapshot:
        return WindowSnapshot(
            window_id=row.id,
            job_id=row.job_id,
            run_id=row.run_id,
            stage_key=row.stage_key,
            window_key=row.window_key,
            tasks=tuple(WindowTaskSpec.model_validate(item) for item in row.tasks),
        )

    @staticmethod
    def _stage_snapshot(session: Session, row: ProductStage) -> StageSnapshot:
        settlement = session.execute(
            select(ProductStageSettlement).where(ProductStageSettlement.stage_id == row.id)
        ).scalar_one_or_none()
        job = session.get(WikiJob, row.job_id)
        if job is None:
            raise SpaceScopeError("stage job is missing")
        if settlement is None:
            state = job.state
            success = missing = failure = calls = 0
            usage: dict[str, int] = {}
            finished_at = _aware(job.finished_at)
        else:
            state = settlement.state
            success = settlement.success_count
            missing = settlement.missing_count
            failure = settlement.failure_count
            calls = settlement.model_call_count
            usage = dict(settlement.usage)
            finished_at = _aware(settlement.finished_at)
        return StageSnapshot(
            stage_id=row.id,
            run_id=row.run_id,
            stage_key=row.stage_key,
            dependency_sha256=row.dependency_sha256,
            job_id=row.job_id,
            parent_job_id=row.parent_job_id,
            state=state,
            success_count=success,
            missing_count=missing,
            failure_count=failure,
            model_call_count=calls,
            usage=usage,
            started_at=_aware(job.started_at),
            finished_at=finished_at,
        )

    @staticmethod
    def _call_snapshot(row: ProductModelCall) -> CallSnapshot:
        reserved_at = _aware(row.reserved_at)
        if reserved_at is None:
            raise ValueError("model call reservation time is missing")
        return CallSnapshot(
            call_id=row.call_id,
            run_id=row.run_id,
            job_id=row.job_id,
            generation=row.generation,
            attempt=row.attempt,
            state=CallState(row.state),
            request_sha256=row.request_sha256,
            request_bytes=row.request_bytes,
            raw=row.raw,
            raw_sha256=row.raw_sha256,
            raw_ref=row.raw_ref,
            diagnostic=row.diagnostic,
            reserved_at=reserved_at,
            dispatched_at=_aware(row.dispatched_at),
            recorded_at=_aware(row.recorded_at),
            selected_field_keys=tuple(
                cast(tuple[str, str], tuple(item)) for item in row.selected_field_keys
            ),
            cached_attempt_ids=tuple(row.cached_attempt_ids),
        )

    @staticmethod
    def _field_snapshot(row: ProductFieldAttempt) -> FieldAttemptSnapshot:
        created_at = _aware(row.created_at)
        if created_at is None:
            raise ValueError("field attempt creation time is missing")
        return FieldAttemptSnapshot(
            attempt_id=row.id,
            run_id=row.run_id,
            window_id=row.window_id,
            call_id=row.call_id,
            entity_id=row.entity_id,
            field_key=row.field_key,
            task_sha256=row.task_sha256,
            cache_identity=FieldCacheIdentity.model_validate(row.cache_identity),
            validation_version=row.validation_version,
            model_policy_sha256=row.model_policy_sha256,
            prompt_policy_sha256=row.prompt_policy_sha256,
            outcome=FieldOutcomeKind(row.outcome),
            reason=row.reason,
            validated_result=row.validated_result,
            raw_ref=row.raw_ref,
            attempt=row.attempt,
            created_at=created_at,
            reused_from_attempt_id=row.reused_from_attempt_id,
        )

    def _lookup_cache(
        self,
        session: Session,
        scope: ProductScope,
        identities: Sequence[FieldCacheIdentity],
    ) -> dict[str, FieldAttemptSnapshot]:
        keys = tuple(dict.fromkeys(item.cache_key for item in identities))
        if not keys:
            return {}
        rows = session.scalars(
            select(ProductFieldAttempt)
            .join(ProductRun, ProductRun.id == ProductFieldAttempt.run_id)
            .where(
                ProductFieldAttempt.tenant_id == scope.tenant_id,
                ProductFieldAttempt.space_id == scope.space_id,
                ProductRun.raw_knowledge_base_id == scope.raw_knowledge_base_id,
                ProductRun.wiki_knowledge_base_id == scope.wiki_knowledge_base_id,
                ProductRun.tenant_id == scope.tenant_id,
                ProductRun.space_id == scope.space_id,
                ProductFieldAttempt.cache_key.in_(keys),
                ProductFieldAttempt.outcome.in_(_CACHEABLE),
            )
            .order_by(ProductFieldAttempt.created_at.desc(), ProductFieldAttempt.id.desc())
        ).all()
        answer: dict[str, FieldAttemptSnapshot] = {}
        for row in rows:
            answer.setdefault(row.cache_key, self._field_snapshot(row))
        return answer

    def _attempts_by_id(
        self,
        session: Session,
        scope: ProductScope,
        attempt_ids: Sequence[str],
    ) -> dict[str, FieldAttemptSnapshot]:
        if not attempt_ids:
            return {}
        rows = session.scalars(
            select(ProductFieldAttempt)
            .join(ProductRun, ProductRun.id == ProductFieldAttempt.run_id)
            .where(
                ProductFieldAttempt.id.in_(tuple(attempt_ids)),
                ProductFieldAttempt.tenant_id == scope.tenant_id,
                ProductFieldAttempt.space_id == scope.space_id,
                ProductRun.raw_knowledge_base_id == scope.raw_knowledge_base_id,
                ProductRun.wiki_knowledge_base_id == scope.wiki_knowledge_base_id,
                ProductRun.tenant_id == scope.tenant_id,
                ProductRun.space_id == scope.space_id,
            )
        ).all()
        if len(rows) != len(set(attempt_ids)):
            raise SpaceScopeError("cached field attempt is outside the product scope")
        return {row.id: self._field_snapshot(row) for row in rows}

    def _counts(self, session: Session, run_id: str) -> tuple[int, int, int]:
        rows = session.execute(
            select(ProductFieldAttempt.outcome, func.count())
            .where(ProductFieldAttempt.run_id == run_id)
            .group_by(ProductFieldAttempt.outcome)
        ).all()
        counts = {name: int(count) for name, count in rows}
        row = session.get(ProductRun, run_id)
        if row is None:
            raise SpaceScopeError("product run is unavailable")
        scope = ProductScope(
            tenant_id=row.tenant_id,
            space_id=row.space_id,
            raw_knowledge_base_id=row.raw_knowledge_base_id,
            wiki_knowledge_base_id=row.wiki_knowledge_base_id,
        )
        refs, receipt = self.checkpoint_field_references(session, scope, run_id)
        # Creation has no committed run yet, and no field validation can exist
        # before there are local or checkpoint-referenced extraction attempts.
        report = self._field_validation_report(scope, run_id) if counts or refs else None
        if report is not None:
            from insurance_harness.product_ingestion.field_validation import apply_field_validation

            effective = apply_field_validation(
                self.list_original_field_attempts(scope=scope, run_id=run_id), report
            )
            return (
                sum(item.outcome is FieldOutcomeKind.VERIFIED for item in effective),
                sum(item.outcome is FieldOutcomeKind.NOT_PROVIDED for item in effective),
                sum(item.outcome is FieldOutcomeKind.EXTRACTION_FAILED for item in effective),
            )
        for ref in refs:
            counts[ref.outcome] = counts.get(ref.outcome, 0) + 1
        return (
            counts.get(FieldOutcomeKind.VERIFIED.value, 0),
            counts.get(FieldOutcomeKind.NOT_PROVIDED.value, 0),
            counts.get(FieldOutcomeKind.EXTRACTION_FAILED.value, 0),
        )

    @staticmethod
    def _sum_usage(rows: Sequence[ProductWindowSettlement]) -> dict[str, int]:
        answer: dict[str, int] = {}
        for row in rows:
            for key, value in row.usage.items():
                answer[key] = answer.get(key, 0) + int(value)
        return answer

    @staticmethod
    def _active_job(session: Session, scope: ProductScope, job_id: str, generation: int) -> WikiJob:
        row = session.execute(
            select(WikiJob).where(WikiJob.id == job_id).with_for_update()
        ).scalar_one_or_none()
        if row is None or row.space_id != scope.space_id:
            raise SpaceScopeError()
        if row.lease_generation != generation:
            raise StaleGenerationError(
                expected=row.lease_generation, actual=generation, job_id=job_id
            )
        if row.state != JobState.RUNNING.value:
            raise ValueError("product worker mutation requires a running job")
        require_active_lease(session, row, now=database_now(session))
        return row

    def _window_for_job(
        self,
        session: Session,
        scope: ProductScope,
        run_id: str,
        job_id: str,
        *,
        reserve_lock: bool = False,
    ) -> ProductWindow:
        self._run(session, scope, run_id)
        statement = select(ProductWindow).where(ProductWindow.job_id == job_id)
        if reserve_lock:
            statement = statement.with_for_update(key_share=True)
        row = session.execute(statement).scalar_one_or_none()
        if row is None or row.space_id != scope.space_id or row.run_id != run_id:
            raise SpaceScopeError()
        return row

    def _call(
        self,
        session: Session,
        scope: ProductScope,
        call_id: str,
        *,
        lock: bool = False,
    ) -> ProductModelCall:
        query = select(ProductModelCall).where(
            ProductModelCall.space_id == scope.space_id,
            ProductModelCall.call_id == call_id,
        )
        if lock:
            query = query.with_for_update()
        row = session.execute(query).scalar_one_or_none()
        if row is None or row.space_id != scope.space_id:
            raise SpaceScopeError()
        self._run(session, scope, row.run_id)
        return row
