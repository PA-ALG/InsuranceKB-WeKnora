"""Durable non-field artifacts and model-call checkpoints for product stages."""

from __future__ import annotations

import hashlib
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
                job = self._products._active_job(session, scope, job_id, generation)
                self._require_job_binding(job.payload, run_id=run_id, stage_key=stage_key)
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
            return StageCallMetrics(
                model_call_count=len(rows),
                usage=usage,
                unsettled_call_count=sum(
                    row.state != StageCallState.RECORDED.value for row in rows
                ),
            )

    def _call(
        self,
        session: Session,
        scope: ProductScope,
        call_id: str,
        *,
        lock: bool = False,
    ) -> ProductStageModelCall:
        statement = select(ProductStageModelCall).where(
            ProductStageModelCall.space_id == scope.space_id,
            ProductStageModelCall.call_id == call_id,
        )
        if lock:
            statement = statement.with_for_update()
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
