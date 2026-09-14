"""Durable non-field artifacts and model-call checkpoints for product stages."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.models import _uuid
from insurance_harness.jobs import DomainWriteSpec, SpaceScopeError, StaleGenerationError
from insurance_harness.jobs.store import (
    _aware,
    database_now,
    validated_limit,
    validated_text,
)
from insurance_harness.product_ingestion.artifact_models import (
    ArtifactDraft,
    ArtifactOrigin,
    ArtifactSnapshot,
    StageCallAction,
    StageCallMetrics,
    StageCallReservation,
    StageCallSnapshot,
    StageCallState,
)
from insurance_harness.product_ingestion.artifact_tables import (
    ProductArtifact,
    ProductStageModelCall,
)
from insurance_harness.product_ingestion.models import ProductScope
from insurance_harness.product_ingestion.recovery import (
    RecordedIdentityRecoveryPlan,
    material_references,
    recorded_identity_reference,
)
from insurance_harness.product_ingestion.store import ProductIngestionStore

SessionFactory = Callable[[], Session]


class ProductArtifactStore:
    """Store exact non-field outputs without weakening Task1 field contracts."""

    def __init__(
        self,
        session_factory: SessionFactory,
        product_store: ProductIngestionStore,
    ) -> None:
        self._session_factory = session_factory
        self._products = product_store

    def prepare_artifact_writes(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        stage_key: str,
        job_id: str,
        generation: int,
        drafts: tuple[ArtifactDraft, ...],
    ) -> tuple[DomainWriteSpec, ...]:
        if not drafts:
            raise ValueError("artifact drafts must not be empty")
        validated_text(stage_key, "stage_key", max_length=128)
        identities = [(item.artifact_kind, item.artifact_key) for item in drafts]
        if len(identities) != len(set(identities)):
            raise ValueError("artifact drafts must have unique identities")
        with self._session_factory() as session:
            with session.begin():
                run = self._products._run(session, scope, run_id)
                self._products._ensure_unfinished(session, run)
                replay_call = (
                    self._identity_replay_call(session, scope, run_id, read_lock=True)
                    if any(draft.origin is ArtifactOrigin.MODEL_REPLAY for draft in drafts)
                    else None
                )
                now = database_now(session)
                writes: list[DomainWriteSpec] = []
                for draft in drafts:
                    if draft.origin is ArtifactOrigin.MODEL:
                        call = self._call(session, scope, draft.origin_call_id or "")
                        if call.dependency_sha256 != draft.dependency_sha256:
                            raise ValueError(
                                "model artifact dependency does not match its recorded call"
                            )
                        if (
                            call.run_id != run_id
                            or call.stage_key != stage_key
                            or call.state != StageCallState.RECORDED.value
                            or not call.raw
                        ):
                            raise ValueError(
                                "model artifact requires a same-run recorded raw model call"
                            )
                    elif draft.origin is ArtifactOrigin.MODEL_REPLAY:
                        call = replay_call
                        assert call is not None
                        if stage_key != "identity" or draft.origin_call_id != call.call_id:
                            raise ValueError("model replay artifact does not match recovery call")
                        marker = session.scalar(
                            select(ProductArtifact).where(
                                ProductArtifact.run_id == run_id,
                                ProductArtifact.artifact_kind == "model_replay_receipt",
                                ProductArtifact.artifact_key == call.call_id,
                            )
                        )
                        if (
                            draft.artifact_kind == "model_replay_receipt"
                            or marker is None
                            or marker.origin != ArtifactOrigin.MODEL_REPLAY.value
                            or marker.origin_call_id != call.call_id
                            or hashlib.sha256(marker.payload).hexdigest() != marker.payload_sha256
                        ):
                            raise ValueError(
                                "model replay requires its durable verification checkpoint"
                            )
                        from insurance_harness.product_ingestion.tables import ProductStage

                        stage = session.scalar(
                            select(ProductStage).where(
                                ProductStage.run_id == run_id,
                                ProductStage.stage_key == stage_key,
                            )
                        )
                        if stage is None or stage.dependency_sha256 != draft.dependency_sha256:
                            raise ValueError("model replay artifact dependency changed")
                    existing = session.execute(
                        select(ProductArtifact).where(
                            ProductArtifact.run_id == run_id,
                            ProductArtifact.artifact_kind == draft.artifact_kind,
                            ProductArtifact.artifact_key == draft.artifact_key,
                        )
                    ).scalar_one_or_none()
                    if existing is not None:
                        if not self._artifact_matches(existing, stage_key, draft):
                            raise ValueError("artifact is immutable; conflicting replay")
                        continue
                    writes.append(
                        DomainWriteSpec(
                            table=ProductArtifact.__tablename__,
                            values={
                                "id": _uuid(),
                                "run_id": run_id,
                                "space_id": scope.space_id,
                                "stage_key": stage_key,
                                "artifact_kind": draft.artifact_kind,
                                "artifact_key": draft.artifact_key,
                                "contract_name": draft.contract_name,
                                "contract_version": draft.contract_version,
                                "dependency_sha256": draft.dependency_sha256,
                                "payload": bytes(draft.payload),
                                "payload_sha256": draft.payload_sha256,
                                "origin": draft.origin.value,
                                "origin_call_id": draft.origin_call_id,
                                "producer_job_id": job_id,
                                "producer_generation": generation,
                                "created_at": now,
                            },
                        )
                    )
                # Source/plan/call rows stay FOR SHARE locked until this transaction
                # ends. Only the final job fence holds the heartbeat's row lock.
                self._products._ensure_unfinished(session, run)
                job = self._products._active_job(session, scope, job_id, generation)
                self._require_job_binding(job.payload, run_id=run_id, stage_key=stage_key)
                return tuple(writes)

    def get_artifact(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        artifact_kind: str,
        artifact_key: str,
    ) -> ArtifactSnapshot:
        with self._session_factory() as session:
            self._products._run(session, scope, run_id)
            row = session.execute(
                select(ProductArtifact).where(
                    ProductArtifact.run_id == run_id,
                    ProductArtifact.space_id == scope.space_id,
                    ProductArtifact.artifact_kind == artifact_kind,
                    ProductArtifact.artifact_key == artifact_key,
                )
            ).scalar_one_or_none()
            if row is None:
                raise SpaceScopeError()
            return self._artifact_snapshot(row)

    def list_artifacts(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        artifact_kind: str | None = None,
        limit: int = 1000,
    ) -> tuple[ArtifactSnapshot, ...]:
        validated_limit(limit, "limit")
        with self._session_factory() as session:
            self._products._run(session, scope, run_id)
            statement = select(ProductArtifact).where(
                ProductArtifact.run_id == run_id,
                ProductArtifact.space_id == scope.space_id,
            )
            if artifact_kind is not None:
                statement = statement.where(ProductArtifact.artifact_kind == artifact_kind)
            rows = session.scalars(
                statement.order_by(ProductArtifact.created_at, ProductArtifact.id).limit(limit)
            ).all()
            return tuple(self._artifact_snapshot(row) for row in rows)

    def reserve_stage_call(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        stage_key: str,
        operation_key: str,
        dependency_sha256: str,
        job_id: str,
        generation: int,
        attempt: int,
        call_id: str,
        input_sha256: str,
        model_policy_sha256: str,
        prompt_policy_sha256: str,
    ) -> StageCallReservation:
        hashes = (
            dependency_sha256,
            input_sha256,
            model_policy_sha256,
            prompt_policy_sha256,
        )
        invalid_hash = any(
            len(item) != 64 or any(char not in "0123456789abcdef" for char in item)
            for item in hashes
        )
        if invalid_hash:
            raise ValueError("stage call hashes must be lowercase sha256")
        validated_text(stage_key, "stage_key", max_length=128)
        validated_text(operation_key, "operation_key", max_length=128)
        validated_text(call_id, "call_id", max_length=128)
        with self._session_factory() as session:
            with session.begin():
                run = self._products._run(session, scope, run_id)
                self._products._ensure_unfinished(session, run)
                job = self._products._active_job(session, scope, job_id, generation)
                self._require_job_binding(job.payload, run_id=run_id, stage_key=stage_key)
                if job.attempt != attempt:
                    raise ValueError("stage call attempt does not match the active job")
                call = session.execute(
                    select(ProductStageModelCall)
                    .where(
                        ProductStageModelCall.run_id == run_id,
                        ProductStageModelCall.stage_key == stage_key,
                        ProductStageModelCall.operation_key == operation_key,
                    )
                    .with_for_update()
                ).scalar_one_or_none()
                if call is not None:
                    expected = (
                        job_id,
                        dependency_sha256,
                        input_sha256,
                        model_policy_sha256,
                        prompt_policy_sha256,
                    )
                    actual = (
                        call.job_id,
                        call.dependency_sha256,
                        call.input_sha256,
                        call.model_policy_sha256,
                        call.prompt_policy_sha256,
                    )
                    if actual != expected:
                        raise ValueError("stage call identity is immutable")
                    if call.state == StageCallState.DISPATCHED.value:
                        call.state = StageCallState.INTERRUPTED.value
                        call.diagnostic = "provider_call_interrupted"
                        call.recorded_at = database_now(session)
                        action = StageCallAction.INTERRUPTED
                    elif call.state == StageCallState.INTERRUPTED.value:
                        action = StageCallAction.INTERRUPTED
                    elif call.state == StageCallState.RECORDED.value:
                        action = StageCallAction.RECORDED
                    else:
                        call.generation = generation
                        call.attempt = attempt
                        action = StageCallAction.DISPATCH
                    return StageCallReservation(
                        action=action,
                        call=self._call_snapshot(call),
                    )
                now = database_now(session)
                call = ProductStageModelCall(
                    call_id=call_id,
                    run_id=run_id,
                    space_id=scope.space_id,
                    stage_key=stage_key,
                    operation_key=operation_key,
                    job_id=job_id,
                    generation=generation,
                    attempt=attempt,
                    dependency_sha256=dependency_sha256,
                    input_sha256=input_sha256,
                    model_policy_sha256=model_policy_sha256,
                    prompt_policy_sha256=prompt_policy_sha256,
                    state=StageCallState.RESERVED.value,
                    request_sha256=None,
                    request_bytes=None,
                    raw=None,
                    raw_sha256=None,
                    raw_ref=f"product-stage-call:{call_id}",
                    diagnostic=None,
                    usage={},
                    reserved_at=now,
                    dispatched_at=None,
                    recorded_at=None,
                )
                session.add(call)
                session.flush()
                return StageCallReservation(
                    action=StageCallAction.DISPATCH,
                    call=self._call_snapshot(call),
                )

    def begin_stage_call(
        self,
        *,
        scope: ProductScope,
        call_id: str,
        job_id: str,
        generation: int,
        request_sha256: str,
        request_bytes: bytes,
    ) -> StageCallSnapshot:
        if hashlib.sha256(request_bytes).hexdigest() != request_sha256:
            raise ValueError("request bytes do not match request_sha256")
        with self._session_factory() as session:
            with session.begin():
                self._products._active_job(session, scope, job_id, generation)
                call = self._call(session, scope, call_id, lock=True)
                if call.job_id != job_id or call.generation != generation:
                    raise StaleGenerationError(
                        expected=call.generation,
                        actual=generation,
                        job_id=job_id,
                    )
                if call.state == StageCallState.DISPATCHED.value:
                    if (
                        call.request_sha256 == request_sha256
                        and call.request_bytes == request_bytes
                    ):
                        return self._call_snapshot(call)
                    raise ValueError("dispatched request is immutable")
                if call.state != StageCallState.RESERVED.value:
                    raise ValueError("only a reserved stage call can dispatch")
                call.request_sha256 = request_sha256
                call.request_bytes = bytes(request_bytes)
                call.state = StageCallState.DISPATCHED.value
                call.dispatched_at = database_now(session)
                return self._call_snapshot(call)

    def record_stage_call_result(
        self,
        *,
        scope: ProductScope,
        call_id: str,
        job_id: str,
        generation: int,
        request_sha256: str,
        raw: bytes | None,
        diagnostic: str | None,
        usage: Mapping[str, int],
    ) -> StageCallSnapshot:
        safe_usage = self._validated_usage(usage)
        if raw is None and not (diagnostic or "").strip():
            raise ValueError("a missing raw response requires a diagnostic")
        with self._session_factory() as session:
            with session.begin():
                self._products._active_job(session, scope, job_id, generation)
                call = self._call(session, scope, call_id, lock=True)
                if call.job_id != job_id or call.generation != generation:
                    raise StaleGenerationError(
                        expected=call.generation,
                        actual=generation,
                        job_id=job_id,
                    )
                if call.request_sha256 != request_sha256:
                    raise ValueError("recorded response request_sha256 mismatch")
                if call.state == StageCallState.RECORDED.value:
                    if (
                        call.raw == raw
                        and call.diagnostic == diagnostic
                        and call.usage == safe_usage
                    ):
                        return self._call_snapshot(call)
                    raise ValueError("recorded stage call is immutable; conflicting replay")
                if call.state != StageCallState.DISPATCHED.value:
                    raise ValueError("only a dispatched stage call can record a result")
                call.raw = bytes(raw) if raw is not None else None
                call.raw_sha256 = hashlib.sha256(raw).hexdigest() if raw is not None else None
                call.diagnostic = diagnostic
                call.usage = safe_usage
                call.state = StageCallState.RECORDED.value
                call.recorded_at = database_now(session)
                return self._call_snapshot(call)

    def get_stage_call(
        self,
        *,
        scope: ProductScope,
        call_id: str,
    ) -> StageCallSnapshot:
        with self._session_factory() as session:
            return self._call_snapshot(self._call(session, scope, call_id))

    def list_stage_calls(
        self,
        *,
        scope: ProductScope,
        run_id: str,
    ) -> tuple[StageCallSnapshot, ...]:
        with self._session_factory() as session:
            self._products._run(session, scope, run_id)
            rows = session.scalars(
                select(ProductStageModelCall)
                .where(
                    ProductStageModelCall.run_id == run_id,
                    ProductStageModelCall.space_id == scope.space_id,
                )
                .order_by(ProductStageModelCall.reserved_at, ProductStageModelCall.id)
            ).all()
            return tuple(self._call_snapshot(row) for row in rows)

    def get_stage_call_metrics(
        self,
        *,
        scope: ProductScope,
        run_id: str,
    ) -> StageCallMetrics:
        """Count real dispatches and sum the usage recorded for those calls."""
        with self._session_factory() as session:
            self._products._run(session, scope, run_id)
            rows = session.execute(
                select(ProductStageModelCall.state, ProductStageModelCall.usage).where(
                    ProductStageModelCall.run_id == run_id,
                    ProductStageModelCall.space_id == scope.space_id,
                    ProductStageModelCall.dispatched_at.is_not(None),
                )
            ).all()
            usage: dict[str, int] = {}
            for row in rows:
                for key, value in row.usage.items():
                    usage[key] = usage.get(key, 0) + int(value)
            replay_ids = set(
                session.scalars(
                    select(ProductArtifact.origin_call_id).where(
                        ProductArtifact.run_id == run_id,
                        ProductArtifact.space_id == scope.space_id,
                        ProductArtifact.origin == ArtifactOrigin.MODEL_REPLAY.value,
                    )
                ).all()
            )
            reused_usage = {}
            if replay_ids:
                replay_call = self._identity_replay_metrics_call(session, scope, run_id)
                if replay_ids != {replay_call.call_id}:
                    raise ValueError("recorded identity replay provenance changed")
                reused_usage = dict(replay_call.usage)
            return StageCallMetrics(
                model_call_count=len(rows),
                reused_model_call_count=len(replay_ids),
                reused_usage=reused_usage,
                usage=usage,
                unsettled_call_count=sum(
                    row.state != StageCallState.RECORDED.value for row in rows
                ),
            )

    def _identity_replay_metrics_call(self, session, scope, run_id):
        """Read recorded accounting provenance, never an execution authorization proof."""
        plan = self._products.processing_recovery_plan(scope=scope, run_id=run_id, session=session)
        if not isinstance(plan, RecordedIdentityRecoveryPlan):
            raise ValueError("recorded identity recovery plan required")
        call = self._call(session, scope, plan.identity_call.call_id)
        if recorded_identity_reference(call) != plan.identity_call:
            raise ValueError("recorded identity replay provenance changed")
        marker = session.scalar(
            select(ProductArtifact).where(
                ProductArtifact.run_id == run_id,
                ProductArtifact.space_id == scope.space_id,
                ProductArtifact.artifact_kind == "model_replay_receipt",
                ProductArtifact.artifact_key == call.call_id,
            )
        )
        expected = {
            "contract": "product-model-replay-receipt.v1",
            "run_id": run_id,
            "origin_run_id": call.run_id,
            "origin_call_id": call.call_id,
            "recovery_plan_sha256": plan.digest(),
            "identity_call": plan.identity_call.model_dump(mode="json"),
            "new_dispatch_count": 0,
        }
        if (
            marker is None
            or marker.origin != ArtifactOrigin.MODEL_REPLAY.value
            or marker.origin_call_id != call.call_id
            or hashlib.sha256(marker.payload).hexdigest() != marker.payload_sha256
            or json.loads(marker.payload) != expected
        ):
            raise ValueError("recorded identity replay checkpoint changed")
        return call

    def _identity_replay_call(self, session, scope, run_id, *, read_lock=False):
        plan = self._products.processing_recovery_plan(
            scope=scope, run_id=run_id, session=session, read_lock=read_lock
        )
        if not isinstance(plan, RecordedIdentityRecoveryPlan):
            raise ValueError("recorded identity recovery plan required")
        origin = self._products._run_snapshot(
            session, self._products._run(session, scope, plan.origin_run_id), scope
        )
        if (
            origin.version != plan.origin_version
            or material_references(origin) != plan.materials
            or self._products._recovery_source_refs(session, scope, origin, read_lock=read_lock)
            != plan.source_snapshots
        ):
            raise ValueError("recorded identity origin source binding changed")
        call = self._call(session, scope, plan.identity_call.call_id, read_lock=read_lock)
        if (
            self._products._recorded_identity_ref(session, scope, origin, read_lock=read_lock)
            != plan.identity_call
            or recorded_identity_reference(call) != plan.identity_call
        ):
            raise ValueError("recorded identity origin changed")
        run = self._products._run_snapshot(
            session, self._products._run(session, scope, run_id), scope
        )
        if (
            self._products._recovery_source_refs(session, scope, run, read_lock=read_lock)
            != plan.source_snapshots
        ):
            raise ValueError("recorded identity sources changed")
        return call

    def get_identity_replay_call(self, *, scope, run_id, job_id, generation, dependency_sha256):
        with self._session_factory() as session:
            run = self._products._run(session, scope, run_id)
            self._products._ensure_unfinished(session, run)
            call = self._call_snapshot(
                self._identity_replay_call(session, scope, run_id, read_lock=True)
            )
            job = self._products._active_job(session, scope, job_id, generation)
            self._require_job_binding(job.payload, run_id=run_id, stage_key="identity")
            from insurance_harness.product_ingestion.tables import ProductStage

            stage = session.scalar(
                select(ProductStage).where(
                    ProductStage.run_id == run_id,
                    ProductStage.stage_key == "identity",
                )
            )
            if stage is None or stage.dependency_sha256 != dependency_sha256:
                raise ValueError("recorded identity recovery dependency changed")
            return call

    def record_identity_replay(self, *, scope, run_id, job_id, generation, dependency_sha256):
        """Durable replay checkpoint fenced by the actual consuming job, not a dispatch row."""
        from insurance_harness.product_ingestion.tables import ProductStage

        with self._session_factory() as session, session.begin():
            run = self._products._run(session, scope, run_id)
            self._products._ensure_unfinished(session, run)
            call = self._identity_replay_call(session, scope, run_id, read_lock=True)
            plan = self._products.processing_recovery_plan(
                scope=scope, run_id=run_id, session=session, read_lock=True
            )
            job = self._products._active_job(session, scope, job_id, generation)
            self._require_job_binding(job.payload, run_id=run_id, stage_key="identity")
            stage = session.scalar(
                select(ProductStage).where(
                    ProductStage.run_id == run_id,
                    ProductStage.stage_key == "identity",
                )
            )
            if stage is None or stage.dependency_sha256 != dependency_sha256:
                raise ValueError("recorded identity replay dependency changed")
            payload = json.dumps(
                {
                    "contract": "product-model-replay-receipt.v1",
                    "run_id": run_id,
                    "origin_run_id": call.run_id,
                    "origin_call_id": call.call_id,
                    "recovery_plan_sha256": plan.digest(),
                    "identity_call": plan.identity_call.model_dump(mode="json"),
                    "new_dispatch_count": 0,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            draft = ArtifactDraft(
                artifact_kind="model_replay_receipt",
                artifact_key=call.call_id,
                contract_name="product-model-replay-receipt.v1",
                contract_version="1",
                dependency_sha256=dependency_sha256,
                payload=payload,
                payload_sha256=hashlib.sha256(payload).hexdigest(),
                origin=ArtifactOrigin.MODEL_REPLAY,
                origin_call_id=call.call_id,
            )
            existing = session.scalar(
                select(ProductArtifact).where(
                    ProductArtifact.run_id == run_id,
                    ProductArtifact.artifact_kind == draft.artifact_kind,
                    ProductArtifact.artifact_key == draft.artifact_key,
                )
            )
            if existing is not None:
                if not self._artifact_matches(existing, "identity", draft):
                    raise ValueError("recorded identity replay checkpoint changed")
                return self._artifact_snapshot(existing)
            row = ProductArtifact(
                id=_uuid(),
                run_id=run_id,
                space_id=scope.space_id,
                stage_key="identity",
                **draft.model_dump(mode="python"),
                producer_job_id=job_id,
                producer_generation=generation,
                created_at=database_now(session),
            )
            session.add(row)
            session.flush()
            return self._artifact_snapshot(row)

    def _call(
        self,
        session: Session,
        scope: ProductScope,
        call_id: str,
        *,
        lock: bool = False,
        read_lock: bool = False,
    ) -> ProductStageModelCall:
        statement = select(ProductStageModelCall).where(
            ProductStageModelCall.space_id == scope.space_id,
            ProductStageModelCall.call_id == call_id,
        )
        if lock or read_lock:
            statement = statement.with_for_update(read=read_lock and not lock)
        row = session.execute(statement).scalar_one_or_none()
        if row is None:
            raise SpaceScopeError()
        self._products._run(session, scope, row.run_id)
        return row

    @staticmethod
    def _require_job_binding(payload: Mapping[str, object], *, run_id: str, stage_key: str) -> None:
        if payload.get("run_id") != run_id or payload.get("stage_key") != stage_key:
            raise ValueError("active job payload does not match the artifact stage")

    @staticmethod
    def _validated_usage(usage: Mapping[str, int]) -> dict[str, int]:
        answer: dict[str, int] = {}
        for key, value in usage.items():
            if not key or "\x00" in key or not isinstance(value, int) or isinstance(value, bool):
                raise ValueError("usage must contain named integer counters")
            if value < 0:
                raise ValueError("usage counters must not be negative")
            answer[key] = value
        return answer

    @staticmethod
    def _artifact_matches(
        row: ProductArtifact,
        stage_key: str,
        draft: ArtifactDraft,
    ) -> bool:
        return (
            row.stage_key,
            row.contract_name,
            row.contract_version,
            row.dependency_sha256,
            row.payload,
            row.payload_sha256,
            row.origin,
            row.origin_call_id,
        ) == (
            stage_key,
            draft.contract_name,
            draft.contract_version,
            draft.dependency_sha256,
            draft.payload,
            draft.payload_sha256,
            draft.origin.value,
            draft.origin_call_id,
        )

    @staticmethod
    def _artifact_snapshot(row: ProductArtifact) -> ArtifactSnapshot:
        created_at = _aware(row.created_at)
        assert created_at is not None
        return ArtifactSnapshot(
            artifact_id=row.id,
            run_id=row.run_id,
            stage_key=row.stage_key,
            artifact_kind=row.artifact_kind,
            artifact_key=row.artifact_key,
            contract_name=row.contract_name,
            contract_version=row.contract_version,
            dependency_sha256=row.dependency_sha256,
            payload=row.payload,
            payload_sha256=row.payload_sha256,
            origin=ArtifactOrigin(row.origin),
            origin_call_id=row.origin_call_id,
            producer_job_id=row.producer_job_id,
            producer_generation=row.producer_generation,
            created_at=created_at,
        )

    @staticmethod
    def _call_snapshot(row: ProductStageModelCall) -> StageCallSnapshot:
        reserved_at = _aware(row.reserved_at)
        assert reserved_at is not None
        return StageCallSnapshot(
            call_id=row.call_id,
            run_id=row.run_id,
            stage_key=row.stage_key,
            operation_key=row.operation_key,
            job_id=row.job_id,
            generation=row.generation,
            attempt=row.attempt,
            dependency_sha256=row.dependency_sha256,
            input_sha256=row.input_sha256,
            model_policy_sha256=row.model_policy_sha256,
            prompt_policy_sha256=row.prompt_policy_sha256,
            state=StageCallState(row.state),
            request_sha256=row.request_sha256,
            request_bytes=row.request_bytes,
            raw=row.raw,
            raw_sha256=row.raw_sha256,
            raw_ref=row.raw_ref,
            diagnostic=row.diagnostic,
            usage=dict(row.usage),
            reserved_at=reserved_at,
            dispatched_at=_aware(row.dispatched_at),
            recorded_at=_aware(row.recorded_at),
        )
