"""Checkpoint repository on the existing product/artifact/job tables."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from insurance_harness.jobs import DomainWriteSpec, JobStore
from insurance_harness.jobs.store import database_now
from insurance_harness.jobs.tables import WikiJob
from insurance_harness.product_ingestion.artifact_tables import (
    ProductArtifact,
    ProductStageModelCall,
)
from insurance_harness.product_ingestion.checkpoints import (
    CURRENT_ARTIFACT_CONTRACTS,
    PLAN_KIND,
    RECEIPT_KIND,
    ArtifactReference,
    CallReference,
    CheckpointPlan,
    CheckpointReceipt,
    ConfirmedFailureReference,
    FieldReference,
    IdentityRetryReference,
    is_checkpoint_reusable_artifact,
    required_outputs,
    stage_order,
)
from insurance_harness.product_ingestion.models import (
    ProductRunSnapshot,
    ProductRunState,
    ProductScope,
    StageSnapshot,
)
from insurance_harness.product_ingestion.recovery import recorded_identity_reference
from insurance_harness.product_ingestion.tables import (
    ProductFieldAttempt,
    ProductMaterial,
    ProductModelCall,
    ProductRun,
    ProductStage,
    ProductStageSettlement,
    ProductWindow,
)

if TYPE_CHECKING:
    pass


def _ref(row: Any) -> ArtifactReference:
    return ArtifactReference(
        **{
            key: getattr(row, "id" if key == "artifact_id" else key)
            for key in ArtifactReference.model_fields
        }
    )


def _small_artifact(session: Session, run_id: str, kind: str) -> ProductArtifact | None:
    identity = session.scalar(
        select(ProductArtifact.id).where(
            ProductArtifact.run_id == run_id,
            ProductArtifact.artifact_kind == kind,
            ProductArtifact.artifact_key == "product",
        )
    )
    payload_length = (
        session.scalar(
            select(func.length(ProductArtifact.payload)).where(ProductArtifact.id == identity)
        )
        if identity
        else None
    )
    if payload_length is not None and payload_length > 131072:
        raise ValueError("checkpoint metadata capacity exceeded")
    row = session.get(ProductArtifact, identity) if identity else None
    if row is not None and hashlib.sha256(row.payload).hexdigest() != row.payload_sha256:
        raise ValueError("checkpoint metadata digest changed")
    return row


class CheckpointStore:
    if TYPE_CHECKING:
        _session_factory: Callable[[], Session]
        _jobs: JobStore

        def _run(
            self,
            session: Session,
            scope: ProductScope,
            run_id: str,
            *,
            lock: bool = False,
        ) -> ProductRun: ...

        def _run_snapshot(
            self,
            session: Session,
            row: ProductRun,
            scope: ProductScope,
        ) -> ProductRunSnapshot: ...

        def _stage_snapshot(self, session: Session, row: ProductStage) -> StageSnapshot: ...

        def get_run(self, *, scope: ProductScope, run_id: str) -> ProductRunSnapshot: ...

    def _confirmed_failure_reference(
        self,
        session: Session,
        scope: ProductScope,
        record_id: str,
        *,
        read_lock: bool = False,
    ) -> ConfirmedFailureReference:
        """Bind a provider response, not an uncertain dispatch or a new send."""
        statement = select(ProductStageModelCall).where(ProductStageModelCall.id == record_id)
        if read_lock:
            statement = statement.with_for_update(read=True)
        call = session.scalar(statement)
        if call is None or call.space_id != scope.space_id:
            raise ValueError("confirmed failure call unavailable")
        origin = self._run(session, scope, call.run_id)
        snapshot = self._run_snapshot(session, origin, scope)
        stage = session.scalar(
            select(ProductStage).where(
                ProductStage.run_id == call.run_id,
                ProductStage.stage_key == "identity",
            )
        )
        job = session.get(WikiJob, call.job_id)
        if (
            call.stage_key != "identity"
            or call.operation_key != "current-product-identity"
            or call.state != "recorded"
            or call.diagnostic != "provider_http_status"
            or not call.raw
            or not call.request_bytes
            or not call.raw_sha256
            or not call.request_sha256
            or hashlib.sha256(call.raw).hexdigest() != call.raw_sha256
            or hashlib.sha256(call.request_bytes).hexdigest() != call.request_sha256
            or call.dispatched_at is None
            or call.recorded_at is None
            or stage is None
            or stage.space_id != scope.space_id
            or stage.job_id != call.job_id
            or stage.dependency_sha256 != call.dependency_sha256
            or job is None
            or job.space_id != scope.space_id
            or job.lease_generation != call.generation
            or job.state not in {"blocked", "dead_letter"}
            or job.finished_at is None
            or snapshot.finished_at is None
            or snapshot.state not in {ProductRunState.FAILED, ProductRunState.NEEDS_CONFIRMATION}
            or session.scalar(
                select(func.count())
                .select_from(ProductStageModelCall)
                .where(ProductStageModelCall.run_id == call.run_id)
            ) != 1
        ):
            raise ValueError("identity call is not a confirmed terminal HTTP rejection")
        return ConfirmedFailureReference(
            record_id=call.id,
            run_id=call.run_id,
            call_id=call.call_id,
            job_id=call.job_id,
            generation=call.generation,
            request_sha256=call.request_sha256,
            raw_sha256=call.raw_sha256,
            diagnostic="provider_http_status",
        )

    def checkpoint_plan(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        session: Session | None = None,
    ) -> CheckpointPlan | None:
        if session is None:
            with self._session_factory() as session:
                return self.checkpoint_plan(scope=scope, run_id=run_id, session=session)
        run = self._run(session, scope, run_id)
        row = _small_artifact(session, run_id, PLAN_KIND)
        if row is None:
            return None
        plan = CheckpointPlan.model_validate_json(row.payload)
        if (
            row.space_id != scope.space_id
            or plan.scope != scope
            or run.retry_of_run_id != plan.origin_run_id
        ):
            raise ValueError("checkpoint scope or origin changed")
        if run.workflow_version != plan.workflow_version:
            raise ValueError("checkpoint workflow changed")
        return plan

    def checkpoint_receipt(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        session: Session | None = None,
    ) -> CheckpointReceipt | None:
        if session is None:
            with self._session_factory() as session:
                return self.checkpoint_receipt(scope=scope, run_id=run_id, session=session)
        self._run(session, scope, run_id)
        row = _small_artifact(session, run_id, RECEIPT_KIND)
        if row is None:
            return None
        receipt = CheckpointReceipt.model_validate_json(row.payload)
        plan = self.checkpoint_plan(scope=scope, run_id=run_id, session=session)
        stage = session.scalar(
            select(ProductStage).where(
                ProductStage.run_id == run_id, ProductStage.stage_key == "checkpoint"
            )
        )
        job = session.get(WikiJob, row.producer_job_id)
        settlement = (
            session.scalar(
                select(ProductStageSettlement).where(ProductStageSettlement.stage_id == stage.id)
            )
            if stage
            else None
        )
        rebased_rows = (
            session.execute(select(
                ProductArtifact.artifact_kind,
                ProductArtifact.payload_sha256,
                ProductArtifact.producer_job_id,
                ProductArtifact.producer_generation,
                ProductArtifact.dependency_sha256,
            ).where(
                ProductArtifact.run_id == run_id,
                ProductArtifact.space_id == scope.space_id,
                ProductArtifact.artifact_kind.in_((
                    "rebased_base_snapshot", "rebased_compile_request",
                    "rebased_identity", "rebased_compile_delta",
                    "rebased_discovery_disposition",
                )),
            )).all()
            if receipt.rebased_base_sha256 is not None else ()
        )
        valid_rebase = receipt.rebased_base_sha256 is None or (
            stage is not None and job is not None
            and
            {row.artifact_kind for row in rebased_rows} == {
                "rebased_base_snapshot", "rebased_compile_request",
                "rebased_identity", "rebased_compile_delta",
            } | (
                {"rebased_discovery_disposition"}
                if receipt.rebased_discovery_disposition_sha256 is not None else set()
            )
            and next(row.payload_sha256 for row in rebased_rows
                     if row.artifact_kind == "rebased_base_snapshot")
            == receipt.rebased_base_sha256
            and (
                receipt.rebased_discovery_disposition_sha256 is None
                or next(
                    row.payload_sha256 for row in rebased_rows
                    if row.artifact_kind == "rebased_discovery_disposition"
                ) == receipt.rebased_discovery_disposition_sha256
            )
            and all(
                row.producer_job_id == stage.job_id
                and row.producer_generation == job.lease_generation
                and row.dependency_sha256 == stage.dependency_sha256
                for row in rebased_rows
            )
        )
        if (
            plan is None
            or receipt.contract != plan.contract.replace("-plan.", "-receipt.")
            or receipt.scope != scope
            or receipt.run_id != run_id
            or receipt.plan_sha256 != plan.digest()
            or not valid_rebase
            or (
                receipt.reused_stages != plan.reused_stages
                and not (
                    plan.supports_rebase
                    and receipt.rebased_base_sha256 is not None
                    and receipt.reused_stages in (
                        plan.reused_stages[:stage_order(3).index("discovery")],
                        plan.reused_stages[:stage_order(3).index("compilation")],
                    )
                )
            )
            or (receipt.rebased_base_sha256 is not None and not plan.supports_rebase)
            or receipt.retry_calls != plan.retry_calls
            or receipt.failed_calls != plan.failed_calls
            or row.space_id != scope.space_id
            or stage is None
            or stage.job_id != row.producer_job_id
            or job is None
            or job.state != "succeeded"
            or job.lease_generation != row.producer_generation
            or settlement is None
            or settlement.state != "succeeded"
        ):
            raise ValueError("checkpoint receipt execution binding changed")
        return receipt

    def _identity_retry_reference(
        self,
        session: Session,
        scope: ProductScope,
        record_id: str,
        *,
        read_lock: bool = False,
    ) -> IdentityRetryReference:
        """Bind a completed failed call; this never authorizes automatic dispatch."""

        call_statement = select(ProductStageModelCall).where(
            ProductStageModelCall.id == record_id
        )
        if read_lock:
            call_statement = call_statement.with_for_update(read=True)
        call = session.scalar(call_statement)
        if call is None or call.space_id != scope.space_id:
            raise ValueError("retry identity call unavailable")
        origin = self._run(session, scope, call.run_id)
        snapshot = self._run_snapshot(session, origin, scope)
        stage_statement = select(ProductStage).where(
            ProductStage.run_id == call.run_id,
            ProductStage.stage_key == "identity",
        )
        if read_lock:
            stage_statement = stage_statement.with_for_update(read=True)
        stage = session.scalar(stage_statement)
        job_statement = select(WikiJob).where(WikiJob.id == call.job_id)
        if read_lock:
            job_statement = job_statement.with_for_update(read=True)
        job = session.scalar(job_statement)
        if (
            stage is None
            or job is None
            or stage.space_id != scope.space_id
            or job.space_id != scope.space_id
            or stage.job_id != call.job_id
            or stage.dependency_sha256 != call.dependency_sha256
            or job.lease_generation != call.generation
            or job.state not in {"blocked", "dead_letter"}
            or job.finished_at is None
            or snapshot.finished_at is None
            or snapshot.state not in {ProductRunState.FAILED, ProductRunState.NEEDS_CONFIRMATION}
            or job.error_class != "capacity_blocked"
            or not (job.error_summary or "")
            .partition("needs_confirmation:")[2]
            .startswith(
                (
                    "PRODUCT_IDENTITY_UNRESOLVED:",
                    "IDENTITY_RESPONSE_INVALID:",
                )
            )
            or session.scalar(
                select(func.count())
                .select_from(ProductStageModelCall)
                .where(ProductStageModelCall.run_id == call.run_id)
            )
            != 1
        ):
            raise ValueError("identity retry producer is not an intact terminal semantic failure")
        return IdentityRetryReference(
            record_id=call.id,
            stage=self._stage_snapshot(session, stage),
            generation=call.generation,
            proof=recorded_identity_reference(call),
        )

    def _checkpoint_candidate(
        self,
        session: Session,
        scope: ProductScope,
        origin: ProductRun,
    ) -> CheckpointPlan | None:
        run = self._run_snapshot(session, origin, scope)
        if (
            run.state not in {
                ProductRunState.FAILED,
                ProductRunState.NEEDS_CONFIRMATION,
                ProductRunState.PARTIAL_SUCCESS,
            }
            or run.finished_at is None
            or not origin.uploads_sealed
        ):
            return None
        if len(run.materials) != origin.expected_upload_count:
            return None
        for execution in (ProductStage, ProductWindow):
            active = session.scalar(
                select(execution.id)
                .join(WikiJob, WikiJob.id == execution.job_id)
                .where(
                    execution.run_id == origin.id,
                    WikiJob.state.not_in(("succeeded", "blocked", "dead_letter")),
                )
                .limit(1)
            )
            if active is not None:
                return None
        # Metadata only. An authorized reference is fully validated by the new worker.
        old_plan = self.checkpoint_plan(scope=scope, run_id=origin.id, session=session)
        old_receipt = (
            self.checkpoint_receipt(scope=scope, run_id=origin.id, session=session)
            if old_plan else None
        )
        # A failed verifier may be retried by reference too. This is only an
        # admission plan, never a substitute for the next worker's full proof.
        inherited = old_plan
        inherited_stages = (
            old_receipt.reused_stages if old_receipt is not None
            else inherited.reused_stages if inherited else ()
        )
        inherited_keys = {stage.stage_key for stage in inherited_stages}
        stages = {s.stage_key: s for s in inherited_stages}
        for row in session.scalars(
            select(ProductStage).where(ProductStage.run_id == origin.id)
        ).all():
            if row.stage_key != "checkpoint":
                stages[row.stage_key] = self._stage_snapshot(session, row)
        columns = [
            getattr(ProductArtifact, "id" if k == "artifact_id" else k)
            for k in ArtifactReference.model_fields
        ]
        artifact_refs: dict[tuple[str, str], ArtifactReference] = (
            {
                (r.artifact_kind, r.artifact_key): r
                for r in inherited.artifacts
                if r.producer_generation > 0
                and r.stage_key in inherited_keys
                and is_checkpoint_reusable_artifact(r.artifact_kind)
            }
            if inherited
            else {}
        )
        # Enqueue control inputs have generation zero. Only outputs produced by
        # a claimed execution can satisfy a completed stage, including on retry
        # of a verifier whose older plan accidentally included control inputs.
        for artifact_row in session.execute(
            select(*columns).where(
                ProductArtifact.run_id == origin.id,
                ProductArtifact.space_id == scope.space_id,
                ProductArtifact.producer_generation > 0,
            )
        ).all():
            if is_checkpoint_reusable_artifact(artifact_row.artifact_kind):
                artifact_refs[(artifact_row.artifact_kind, artifact_row.artifact_key)] = _ref(
                    artifact_row
                )

        failed_discovery_artifact = None
        failed_discovery_stage = None
        if run.state is ProductRunState.PARTIAL_SUCCESS:
            if origin.workflow_version != 3:
                return None
            for kind, stage_key in (
                ("discovery_summary", "discovery"),
                ("discovery_final_summary", "compilation"),
            ):
                summary_ref = artifact_refs.get((kind, "product"))
                discovery_stage = stages.get(stage_key)
                if summary_ref is None or discovery_stage is None:
                    continue
                summary_row = _small_artifact(session, summary_ref.run_id, kind)
                if summary_row is None or _ref(summary_row) != summary_ref:
                    return None
                try:
                    summary = json.loads(summary_row.payload)
                except (TypeError, ValueError):
                    return None
                if (
                    summary.get("state") == "FAILED"
                    and discovery_stage.state == "partial_success"
                    and summary_ref.stage_key == stage_key
                    and summary_ref.run_id == discovery_stage.run_id
                ):
                    failed_discovery_artifact = summary_ref
                    failed_discovery_stage = discovery_stage
                    break
            if failed_discovery_artifact is None:
                return None

        def current_contract(ref: ArtifactReference) -> bool:
            expected = CURRENT_ARTIFACT_CONTRACTS.get(ref.artifact_kind)
            return expected is None or (ref.contract_name, ref.contract_version) == expected

        # Only a still-valid completed v1 combined stage may retain its draft.
        # An obsolete candidate resumes at compilation using the split workflow.
        compiled = stages.get("compilation")
        compiled_refs = tuple(
            r for r in artifact_refs.values() if r.stage_key == "compilation"
        )
        compiled_current = any(r.artifact_kind == "candidate" for r in compiled_refs) and all(
            current_contract(r) for r in compiled_refs
        )
        if origin.workflow_version not in {1, 2, 3}:
            return None
        workflow_version = cast(Literal[1, 2, 3], origin.workflow_version)
        if workflow_version == 1 and (
            compiled is None
            or compiled.state not in {"succeeded", "partial_success"}
            or not compiled_current
        ):
            workflow_version = 2
        order = stage_order(workflow_version)
        outputs = required_outputs(workflow_version)
        prefix: list[StageSnapshot] = []
        for key in order:
            stage = stages.get(key)
            if stage is None or stage.state not in {"succeeded", "partial_success"}:
                break
            stage_refs = tuple(r for r in artifact_refs.values() if r.stage_key == key)
            kinds = {r.artifact_kind for r in stage_refs}
            if not set(outputs[key]).issubset(kinds) or not all(
                current_contract(r) for r in stage_refs
            ):
                break
            prefix.append(stage)
        if not prefix or len(prefix) == len(order):
            if not failed_discovery_artifact:
                return None
        resume = order[len(prefix)] if len(prefix) < len(order) else "discovery"
        legacy_rebase = (
            workflow_version == 2
            and inherited is not None
            and inherited.contract_version in {"2", "7"}
        )
        rebase = (
            (workflow_version == 3 or legacy_rebase)
            and "synthesis" in {s.stage_key for s in prefix}
        )
        if rebase and run.state is ProductRunState.PARTIAL_SUCCESS:
            if failed_discovery_artifact is not None and (
                failed_discovery_artifact.artifact_kind == "discovery_final_summary"
                and "discovery" in {s.stage_key for s in prefix}
            ):
                prefix = prefix[: order.index("compilation")]
                resume = "compilation"
            else:
                prefix = prefix[: order.index("discovery")]
                resume = "discovery"
        if run.state is ProductRunState.PARTIAL_SUCCESS and not (
            failed_discovery_artifact and rebase
        ):
            return None
        if resume == "verify":
            # A published-head verification retry requires the new publication
            # receipt as its current-head baseline; not the prepublication base.
            return None
        prefix_keys = {s.stage_key for s in prefix}
        refs = tuple(
            sorted(
                (r for r in artifact_refs.values() if r.stage_key in prefix_keys),
                key=lambda r: (r.artifact_kind, r.artifact_key),
            )
        )
        if "source" in prefix_keys and {
            r.artifact_key for r in refs if r.artifact_kind == "source_snapshot"
        } != {m.knowledge_id for m in run.materials}:
            return None
        retry_calls: tuple[IdentityRetryReference, ...] = (
            inherited.retry_calls if inherited and resume == "identity" else ()
        )
        # Each explicit child is a new attempt. Historical failed calls stay in
        # their immutable ancestor plan; only this origin's failure is bound here.
        failed_calls: tuple[ConfirmedFailureReference, ...] = ()
        if (
            retry_calls
            and session.scalar(
                select(ProductStage.id).where(
                    ProductStage.run_id == origin.id, ProductStage.stage_key == "identity"
                )
            )
            is None
        ):
            try:
                if (
                    self._identity_retry_reference(session, scope, retry_calls[0].record_id)
                    != retry_calls[0]
                ):
                    return None
            except ValueError:
                return None
        else:
            retry_calls = ()
        calls: dict[tuple[Literal["field", "stage"], str], CallReference] = {}
        audited_calls: dict[
            tuple[Literal["field", "stage"], str], CallReference
        ] = (
            {(c.kind, c.record_id): c for c in inherited.audited_calls}
            if inherited and rebase else {}
        )
        if inherited:
            for inherited_call in inherited.calls:
                if inherited_call.kind == "field":
                    call_stage_key = "extract"
                else:
                    inherited_stage_key = session.scalar(
                        select(ProductStageModelCall.stage_key).where(
                            ProductStageModelCall.id == inherited_call.record_id,
                            ProductStageModelCall.run_id == inherited_call.run_id,
                            ProductStageModelCall.space_id == scope.space_id,
                        )
                    )
                    if inherited_stage_key is None:
                        return None
                    call_stage_key = inherited_stage_key
                if call_stage_key in inherited_keys:
                    calls[(inherited_call.kind, inherited_call.record_id)] = inherited_call
                elif (
                    rebase
                    and inherited_call.kind == "stage"
                    and call_stage_key in {"discovery", "compilation"}
                ):
                    if inherited_call.state != "recorded":
                        return None
                    audited_calls[(inherited_call.kind, inherited_call.record_id)] = inherited_call
                else:
                    return None
        for raw_kind, table in (
            ("field", ProductModelCall),
            ("stage", ProductStageModelCall),
        ):
            kind = cast(Literal["field", "stage"], raw_kind)
            if (
                session.scalar(
                    select(table.id)
                    .where(table.run_id == origin.id, table.space_id != scope.space_id)
                    .limit(1)
                )
                is not None
            ):
                return None
            call_columns: tuple[Any, ...] = (
                table.id,
                table.run_id,
                table.call_id,
                table.state,
                table.request_sha256,
                table.raw_sha256,
                table.dispatched_at,
            )
            if kind == "stage":
                call_columns += (cast(Any, table).stage_key,)
            for call_row in session.execute(
                select(*call_columns).where(
                    table.run_id == origin.id,
                    table.space_id == scope.space_id,
                )
            ):
                call_stage_key = "extract" if kind == "field" else call_row.stage_key
                # Unsettled or already executed work outside the reusable prefix
                # cannot be dispatched under a new identity. Reconcile separately.
                if call_stage_key not in prefix_keys:
                    if call_row.dispatched_at is not None:
                        if (
                            rebase
                            and kind == "stage"
                            and call_stage_key in {"discovery", "compilation"}
                        ):
                            if call_row.state != "recorded" or call_row.raw_sha256 is None:
                                return None
                            audited_calls[(kind, call_row.id)] = CallReference(
                                kind=kind, record_id=call_row.id, run_id=call_row.run_id,
                                call_id=call_row.call_id, state=call_row.state,
                                request_sha256=call_row.request_sha256,
                                raw_sha256=call_row.raw_sha256,
                            )
                            continue
                        if (
                            kind != "stage"
                            or call_stage_key != "identity"
                            or resume != "identity"
                            or retry_calls
                            or failed_calls
                            or any(
                                k not in {"uploads", "source", "routing", "identity"}
                                for k in stages
                            )
                        ):
                            return None
                        try:
                            retry_calls = (
                                self._identity_retry_reference(session, scope, call_row.id),
                            )
                        except ValueError:
                            try:
                                failed_calls = (
                                    self._confirmed_failure_reference(
                                        session, scope, call_row.id
                                    ),
                                )
                            except ValueError:
                                return None
                    continue
                if call_row.state not in {"recorded", "interrupted"}:
                    return None
                calls[(kind, call_row.id)] = CallReference(
                    kind=kind,
                    record_id=call_row.id,
                    run_id=call_row.run_id,
                    call_id=call_row.call_id,
                    state=call_row.state,
                    request_sha256=call_row.request_sha256,
                    raw_sha256=call_row.raw_sha256,
                )
        # MODEL_REPLAY artifacts retain their original call, even when that call
        # belongs to an ancestor rather than the finished current run.
        for artifact_ref in refs:
            if artifact_ref.origin_call_id is None:
                continue
            table = ProductStageModelCall
            replay_row = session.execute(
                select(
                    table.id,
                    table.run_id,
                    table.call_id,
                    table.state,
                    table.request_sha256,
                    table.raw_sha256,
                ).where(
                    table.call_id == artifact_ref.origin_call_id,
                    table.space_id == scope.space_id,
                )
            ).one_or_none()
            if replay_row is None or replay_row.state != "recorded":
                return None
            self._run(session, scope, replay_row.run_id)
            calls[("stage", replay_row.id)] = CallReference(
                kind="stage",
                record_id=replay_row.id,
                run_id=replay_row.run_id,
                call_id=replay_row.call_id,
                state=replay_row.state,
                request_sha256=replay_row.request_sha256,
                raw_sha256=replay_row.raw_sha256,
            )
        field_refs: dict[str, FieldReference] = (
            {f.attempt_id: f for f in inherited.fields}
            if inherited and "extract" in prefix_keys
            else {}
        )
        if "extract" in prefix_keys:
            for field_row in session.execute(
                select(
                    ProductFieldAttempt.id,
                    ProductFieldAttempt.run_id,
                    ProductFieldAttempt.entity_id,
                    ProductFieldAttempt.field_key,
                    ProductFieldAttempt.task_sha256,
                    ProductFieldAttempt.outcome,
                    ProductFieldAttempt.call_id,
                ).where(
                    ProductFieldAttempt.run_id == origin.id,
                    ProductFieldAttempt.space_id == scope.space_id,
                )
            ):
                field_refs[field_row.id] = FieldReference(
                    attempt_id=field_row.id,
                    run_id=field_row.run_id,
                    entity_id=field_row.entity_id,
                    field_key=field_row.field_key,
                    task_sha256=field_row.task_sha256,
                    outcome=field_row.outcome,
                    call_id=field_row.call_id,
                )
        if resume == "extract" and session.scalar(
            select(ProductWindow.id).where(ProductWindow.run_id == origin.id).limit(1)
        ):
            # Partial window continuation requires its original claim/call fence;
            # never clone these windows into an unrelated run or fill unknowns.
            return None
        upload = origin
        seen: set[str] = set()
        while upload.retry_of_run_id:
            if upload.id in seen or len(seen) >= 64:
                raise ValueError("checkpoint ancestry is cyclic or exceeds capacity")
            seen.add(upload.id)
            upload = self._run(session, scope, upload.retry_of_run_id)
        prior_rebase_artifacts = inherited.prior_rebase_artifacts if inherited else ()
        if rebase:
            prior_receipt = self.checkpoint_receipt(
                scope=scope, run_id=origin.id, session=session
            )
            if prior_receipt is not None and prior_receipt.rebased_base_sha256 is not None:
                rows = session.execute(select(*columns).where(
                    ProductArtifact.run_id == origin.id,
                    ProductArtifact.space_id == scope.space_id,
                    ProductArtifact.artifact_kind.in_((
                        "rebased_base_snapshot", "rebased_compile_request",
                        "rebased_identity", "rebased_compile_delta",
                        "rebased_discovery_disposition",
                    )),
                )).all()
                prior_rebase_artifacts = tuple(sorted(
                    (_ref(row) for row in rows), key=lambda row: row.artifact_kind
                ))
                expected = 5 if prior_receipt.rebased_discovery_disposition_sha256 else 4
                if len(prior_rebase_artifacts) != expected:
                    return None
        if legacy_rebase:
            contract_version = 7
        elif workflow_version == 3:
            contract_version = 6 if rebase else 5
        elif failed_calls:
            contract_version = 4
        elif retry_calls:
            contract_version = 3
        else:
            contract_version = workflow_version
        contract = cast(
            Literal[
                "product-stage-checkpoint-plan.830.v1",
                "product-stage-checkpoint-plan.830.v2",
                "product-stage-checkpoint-plan.830.v3",
                "product-stage-checkpoint-plan.830.v4",
                "product-stage-checkpoint-plan.830.v5",
                "product-stage-checkpoint-plan.830.v6",
                "product-stage-checkpoint-plan.830.v7",
            ],
            f"product-stage-checkpoint-plan.830.v{contract_version}",
        )
        return CheckpointPlan(
            contract=contract,
            execution_workflow_version=2 if contract_version == 7 else None,
            scope=scope,
            origin_run_id=origin.id,
            origin_version=origin.version,
            upload_run_id=upload.id,
            resume_stage=resume,
            materials=run.materials,
            reused_stages=tuple(prefix),
            artifacts=refs,
            calls=tuple(sorted(calls.values(), key=lambda c: (c.kind, c.record_id))),
            fields=tuple(sorted(field_refs.values(), key=lambda f: f.attempt_id)),
            retry_calls=retry_calls,
            failed_calls=failed_calls,
            audited_calls=tuple(
                sorted(audited_calls.values(), key=lambda c: (c.kind, c.record_id))
            ),
            prior_rebase_artifacts=prior_rebase_artifacts if rebase else (),
            failed_discovery_artifact=failed_discovery_artifact,
            failed_discovery_stage=failed_discovery_stage,
        )

    def can_retry_processing(self, *, scope: ProductScope, run_id: str) -> bool:
        with self._session_factory() as session:
            return (
                self._checkpoint_candidate(session, scope, self._run(session, scope, run_id))
                is not None
            )

    def retry_processing(
        self,
        *,
        scope: ProductScope,
        run_id: str,
        expected_version: int,
    ) -> ProductRunSnapshot:
        if type(expected_version) is not int or expected_version <= 0:
            raise ValueError("expected_version must be a positive integer")
        with self._session_factory() as session:
            origin = self._run(session, scope, run_id)
            if origin.version != expected_version:
                raise ValueError("checkpoint origin version changed")
            plan = self._checkpoint_candidate(session, scope, origin)
            if plan is None:
                raise ValueError("no safe completed checkpoint is available")
            identity = "checkpoint:" + plan.digest()
            existing = session.scalar(
                select(ProductRun).where(
                    ProductRun.tenant_id == scope.tenant_id,
                    ProductRun.space_id == scope.space_id,
                    ProductRun.idempotency_key == identity,
                )
            )
            if existing:
                return self._run_snapshot(session, existing, scope)
            child = str(uuid5(NAMESPACE_URL, identity))
            stage_id = str(
                uuid5(NAMESPACE_URL, f"product-stage:{scope.space_id}:{child}:checkpoint")
            )
            dependency = plan.digest()
            job_id = str(uuid5(NAMESPACE_URL, f"product-stage-job:{stage_id}:{dependency}"))
            now = database_now(session)
            writes = [
                DomainWriteSpec(
                    table=ProductRun.__tablename__,
                    values={
                        "id": child,
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
                        "source_deadline_at": now + timedelta(hours=1),
                        "uploads_sealed_at": now,
                        "uploads_sealed": True,
                        "state": ProductRunState.AWAITING_SOURCES.value,
                        "version": 1,
                        "workflow_version": plan.workflow_version,
                        "created_at": now,
                        "started_at": now,
                        "root_job_id": None,
                    },
                )
            ]
            source_keys = (
                "source_revision_id",
                "source_sha256",
                "file_sha256",
                "native_manifest_sha256",
                "page_count",
                "inferred_material_role",
                "product_identity_sha256",
            )
            material_rows = session.scalars(
                select(ProductMaterial).where(ProductMaterial.run_id == run_id)
            ).all()
            for m in material_rows:
                writes.append(
                    DomainWriteSpec(
                        table=ProductMaterial.__tablename__,
                        values={
                            "id": str(
                                uuid5(
                                    NAMESPACE_URL,
                                    f"checkpoint-material:{child}:{m.upload_ordinal}",
                                )
                            ),
                            "run_id": child,
                            "tenant_id": scope.tenant_id,
                            "space_id": scope.space_id,
                            "knowledge_id": m.knowledge_id,
                            "original_filename": m.original_filename,
                            "upload_ordinal": m.upload_ordinal,
                            **{k: getattr(m, k) for k in source_keys},
                        },
                    )
                )
            writes.extend(
                (
                    DomainWriteSpec(
                        table=ProductStage.__tablename__,
                        values={
                            "id": stage_id,
                            "run_id": child,
                            "space_id": scope.space_id,
                            "stage_key": "checkpoint",
                            "dependency_sha256": dependency,
                            "job_id": job_id,
                            "parent_job_id": None,
                            "created_at": now,
                        },
                    ),
                    DomainWriteSpec(
                        table=ProductArtifact.__tablename__,
                        values={
                            "id": str(uuid5(NAMESPACE_URL, "checkpoint-plan:" + child)),
                            "run_id": child,
                            "space_id": scope.space_id,
                            "stage_key": "checkpoint",
                            "artifact_kind": PLAN_KIND,
                            "artifact_key": "product",
                            "contract_name": plan.contract,
                            "contract_version": plan.contract_version,
                            "dependency_sha256": dependency,
                            "payload": plan.encoded(),
                            "payload_sha256": dependency,
                            "origin": "rule",
                            "origin_call_id": None,
                            "producer_job_id": job_id,
                            "producer_generation": 0,
                            "created_at": now,
                        },
                    ),
                )
            )
        self._jobs.enqueue(
            space_id=scope.space_id,
            job_type="product_stage_checkpoint",
            idempotency_key=f"{child}:checkpoint:{dependency}",
            job_id=job_id,
            payload={"run_id": child, "stage_key": "checkpoint"},
            domain_writes=tuple(writes),
        )
        return self.get_run(scope=scope, run_id=child)

    def checkpoint_field_references(
        self,
        session: Session,
        scope: ProductScope,
        run_id: str,
    ) -> tuple[tuple[FieldReference, ...], CheckpointReceipt | None]:
        receipt = self.checkpoint_receipt(scope=scope, run_id=run_id, session=session)
        if receipt is None:
            return (), None
        plan = self.checkpoint_plan(scope=scope, run_id=run_id, session=session)
        if plan is None:
            raise ValueError("checkpoint receipt is missing its plan")
        return plan.fields, receipt
