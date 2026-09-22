"""Authorized direct reference reads and complete local checkpoint verification."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import defer

from insurance_harness.jobs import SpaceScopeError
from insurance_harness.jobs.tables import WikiJob
from insurance_harness.product_ingestion.artifact_tables import (
    ProductArtifact,
    ProductStageModelCall,
)
from insurance_harness.product_ingestion.checkpoint_store import _ref
from insurance_harness.product_ingestion.checkpoints import (
    CURRENT_ARTIFACT_CONTRACTS,
    CheckpointReceipt,
    field_digest,
)
from insurance_harness.product_ingestion.tables import (
    ProductFieldAttempt,
    ProductModelCall,
    ProductStage,
    ProductWindowSettlement,
)


class CheckpointArtifacts:
    def get_rebased_artifact(self, *, scope, run_id, artifact_kind):
        """All four rebased inputs are one fenced checkpoint output, or none is visible."""
        kinds = {
            "rebased_base_snapshot", "rebased_compile_request",
            "rebased_identity", "rebased_compile_delta",
        }
        if artifact_kind not in kinds:
            raise ValueError("invalid rebased input")
        with self._session_factory() as session:
            receipt = self._products.checkpoint_receipt(
                scope=scope, run_id=run_id, session=session
            )
            if receipt is None or not receipt.supports_rebase:
                return None
            stage = session.scalar(select(ProductStage).where(
                ProductStage.run_id == run_id, ProductStage.stage_key == "checkpoint"
            ))
            job = session.get(WikiJob, stage.job_id) if stage else None
            rows = session.scalars(select(ProductArtifact).where(
                ProductArtifact.run_id == run_id,
                ProductArtifact.space_id == scope.space_id,
                ProductArtifact.artifact_kind.in_(kinds),
            )).all()
            if not rows:
                return None
            if len(rows) != len(kinds) or {row.artifact_kind for row in rows} != kinds:
                raise ValueError("partial checkpoint rebase is unavailable")
            for row in rows:
                if (
                    row.artifact_key != "product"
                    or row.stage_key != "checkpoint"
                    or row.producer_job_id != stage.job_id
                    or row.producer_generation != job.lease_generation
                    or row.dependency_sha256 != stage.dependency_sha256
                    or (row.contract_name, row.contract_version)
                    != CURRENT_ARTIFACT_CONTRACTS[row.artifact_kind]
                    or hashlib.sha256(row.payload).hexdigest() != row.payload_sha256
                ):
                    raise ValueError("checkpoint rebase custody changed")
            return self._artifact_snapshot(
                next(row for row in rows if row.artifact_kind == artifact_kind)
            )

    def get_effective_artifact(self, *, scope, run_id, artifact_kind, artifact_key="product"):
        rows = self.list_effective_artifacts(
            scope=scope, run_id=run_id, artifact_kind=artifact_kind
        )
        selected = [r for r in rows if r.artifact_key == artifact_key]
        if len(selected) != 1:
            raise SpaceScopeError("authorized artifact is unavailable")
        return selected[0]

    def list_effective_artifacts(self, *, scope, run_id, artifact_kind=None, limit=1000):
        return self._effective_artifacts(
            scope=scope, run_id=run_id, artifact_kind=artifact_kind,
            limit=limit, include_payload=True,
        )

    def list_effective_artifact_references(self, *, scope, run_id, artifact_kind=None,
                                          limit=1000):
        """Current authorized identities; no large payload or geometry hydration."""
        return self._effective_artifacts(
            scope=scope, run_id=run_id, artifact_kind=artifact_kind,
            limit=limit, include_payload=False,
        )

    def _effective_artifacts(self, *, scope, run_id, artifact_kind, limit, include_payload):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("invalid effective artifact read capacity")
        with self._session_factory() as session:
            self._products._run(session, scope, run_id)
            # Resolve small authorization metadata before metadata-only rows can
            # install raiseload payload attributes in this Session identity map.
            receipt = self._products.checkpoint_receipt(scope=scope, run_id=run_id, session=session)
            plan = (self._products.checkpoint_plan(scope=scope, run_id=run_id, session=session)
                    if receipt is not None else None)
            options = () if include_payload else (defer(ProductArtifact.payload, raiseload=True),)
            query = select(ProductArtifact).options(*options).where(
                ProductArtifact.run_id == run_id, ProductArtifact.space_id == scope.space_id
            )
            if artifact_kind is not None:
                query = query.where(ProductArtifact.artifact_kind == artifact_kind)
            local = session.scalars(query.order_by(ProductArtifact.created_at,
                                                  ProductArtifact.id).limit(limit + 1)).all()
            inherited = []
            if plan is not None:
                effective_keys = {stage.stage_key for stage in receipt.reused_stages}
                refs = [r for r in plan.artifacts
                        if r.stage_key in effective_keys
                        and (artifact_kind is None or r.artifact_kind == artifact_kind)]
                if receipt.rebased_base_sha256 is not None:
                    refs = [
                        ref for ref in refs
                        if plan.artifact_is_effective_after_rebase(ref.artifact_kind)
                    ]
                for ref in refs:
                    row = session.scalar(select(ProductArtifact).options(*options).where(
                        ProductArtifact.id == ref.artifact_id))
                    if row is None or row.space_id != scope.space_id or _ref(row) != ref:
                        raise ValueError("referenced artifact is missing or changed")
                    self._products._run(session, scope, ref.run_id)
                    inherited.append(row)
            if len(local) + len(inherited) > limit:
                raise ValueError("effective artifact read capacity exceeded")
            values = {}
            for row in (*inherited, *local):
                identity = (row.artifact_kind, row.artifact_key)
                if identity in values and values[identity].artifact_id != row.id:
                    raise ValueError("recovered output may not overwrite a completed checkpoint")
                if include_payload:
                    if hashlib.sha256(row.payload).hexdigest() != row.payload_sha256:
                        raise ValueError("artifact bytes changed")
                    value = self._artifact_snapshot(row)
                else:
                    value = _ref(row)
                values[identity] = value
            return tuple(values.values())

    def read_checkpoint_artifact(self, *, scope, run_id, artifact_kind, artifact_key="product"):
        """Pre-receipt verifier read: only plan-authorized references, never business use."""
        with self._session_factory() as session:
            plan = self._products.checkpoint_plan(scope=scope, run_id=run_id, session=session)
            refs = (
                [
                    r
                    for r in plan.artifacts
                    if (r.artifact_kind, r.artifact_key) == (artifact_kind, artifact_key)
                ]
                if plan
                else []
            )
            if len(refs) != 1:
                raise ValueError("checkpoint input missing")
            row = session.get(ProductArtifact, refs[0].artifact_id)
            if (
                row is None
                or row.space_id != scope.space_id
                or _ref(row) != refs[0]
                or hashlib.sha256(row.payload).hexdigest() != refs[0].payload_sha256
            ):
                raise ValueError("checkpoint artifact bytes changed")
            self._products._run(session, scope, row.run_id)
            return self._artifact_snapshot(row)

    def read_checkpoint_field_attempts(self, *, scope, run_id):
        """Read only field rows named by a plan already verified by this worker."""
        with self._session_factory() as session:
            plan = self._products.checkpoint_plan(scope=scope, run_id=run_id, session=session)
            if plan is None:
                raise ValueError("checkpoint plan missing")
            values = []
            for ref in plan.fields:
                row = session.get(ProductFieldAttempt, ref.attempt_id)
                self._products._run(session, scope, ref.run_id)
                if (
                    row is None or row.space_id != scope.space_id
                    or any(getattr(row, key) != getattr(ref, key) for key in (
                        "run_id", "entity_id", "field_key", "task_sha256", "outcome", "call_id"
                    ))
                ):
                    raise ValueError("checkpoint field custody changed")
                values.append(self._products._field_snapshot(row))
            return tuple(values)

    def read_checkpoint_discovery_disposition(self, *, scope, run_id):
        with self._session_factory() as session:
            plan = self._products.checkpoint_plan(scope=scope, run_id=run_id, session=session)
            refs = [ref for ref in plan.artifacts
                    if ref.artifact_kind == "discovery_final_summary"
                    and ref.artifact_key == "product"]
            if not refs:
                refs = [ref for ref in plan.prior_rebase_artifacts
                        if ref.artifact_kind == "rebased_discovery_disposition"]
            if len(refs) != 1:
                return None
            ref = refs[0]
            row = session.get(ProductArtifact, ref.artifact_id)
            if (
                row is None or row.space_id != scope.space_id or _ref(row) != ref
                or hashlib.sha256(row.payload).hexdigest() != ref.payload_sha256
            ):
                raise ValueError("checkpoint discovery disposition changed")
            summary = json.loads(row.payload)
            if ref.artifact_kind == "rebased_discovery_disposition":
                marker = summary
                summary = marker.get("original_summary", {})
                request_refs = [
                    item for item in plan.prior_rebase_artifacts
                    if item.artifact_kind == "rebased_compile_request"
                ]
                if (
                    len(request_refs) != 1
                    or marker.get("rebased_request_sha256")
                    != request_refs[0].payload_sha256
                    or marker.get("original_payload_sha256")
                    != hashlib.sha256(
                        json.dumps(
                            summary, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), allow_nan=False,
                        ).encode()
                    ).hexdigest()
                ):
                    raise ValueError("prior discovery disposition binding changed")
            if summary.get("state") not in {"PENDING", "REJECTED"}:
                return None
            return self._artifact_snapshot(row)

    def read_prior_rebase_artifact(self, *, scope, run_id, artifact_kind):
        with self._session_factory() as session:
            plan = self._products.checkpoint_plan(scope=scope, run_id=run_id, session=session)
            refs = [r for r in plan.prior_rebase_artifacts if r.artifact_kind == artifact_kind]
            if len(refs) != 1:
                raise ValueError("prior checkpoint rebase input missing")
            row = session.get(ProductArtifact, refs[0].artifact_id)
            self._products._run(session, scope, refs[0].run_id)
            if (
                row is None or row.space_id != scope.space_id or _ref(row) != refs[0]
                or hashlib.sha256(row.payload).hexdigest() != row.payload_sha256
            ):
                raise ValueError("prior checkpoint rebase changed")
            return self._artifact_snapshot(row)

    def verify_discarded_stage_calls(self, *, scope, run_id, stage_keys):
        """A changed base cannot hide an unknown send by changing its input hash."""
        with self._session_factory() as session, session.begin():
            plan = self._products.checkpoint_plan(scope=scope, run_id=run_id, session=session)
            if plan is None or not plan.supports_rebase:
                raise ValueError("checkpoint call audit requires rebase support")
            refs = (*(ref for ref in plan.calls if ref.kind == "stage"),
                    *plan.audited_calls)
            for ref in refs:
                row = session.scalar(select(ProductStageModelCall).where(
                    ProductStageModelCall.id == ref.record_id
                ).with_for_update(read=True))
                self._products._run(session, scope, ref.run_id)
                if row is None or row.space_id != scope.space_id:
                    raise ValueError("checkpoint stage call disappeared")
                if row.stage_key not in stage_keys or row.dispatched_at is None:
                    continue
                if (
                    row.state != "recorded"
                    or row.raw is None or row.request_bytes is None
                    or row.raw_sha256 != hashlib.sha256(row.raw).hexdigest()
                    or row.request_sha256 != hashlib.sha256(row.request_bytes).hexdigest()
                ):
                    raise ValueError("discarded discovery call outcome is unknown")

    def verify_checkpoint(self, *, scope, run_id, effective_stage_keys=None):
        """Expensive worker-only validation. No job row lock and no provider effects."""
        with self._session_factory() as session, session.begin():
            plan = self._products.checkpoint_plan(scope=scope, run_id=run_id, session=session)
            if plan is None:
                raise ValueError("checkpoint plan missing")
            if effective_stage_keys is not None:
                expected = tuple(s.stage_key for s in plan.reused_stages)
                if (
                    not plan.supports_rebase
                    or tuple(effective_stage_keys) != expected[:len(effective_stage_keys)]
                    or not effective_stage_keys
                ):
                    raise ValueError("invalid effective checkpoint prefix")
            effective_keys = set(
                effective_stage_keys if effective_stage_keys is not None
                else (s.stage_key for s in plan.reused_stages)
            )
            origin = self._products._run(session, scope, plan.origin_run_id)
            original = self._products._run_snapshot(session, origin, scope)
            if (
                origin.version != plan.origin_version
                or original.materials != plan.materials
                or original.finished_at is None
            ):
                raise ValueError("checkpoint origin identity changed")
            child = self._products._run_snapshot(
                session, self._products._run(session, scope, run_id), scope
            )

            def canonical_materials(rows):
                return tuple(
                    (m.knowledge_id, m.original_filename, m.upload_ordinal, m.source) for m in rows
                )

            if canonical_materials(child.materials) != canonical_materials(plan.materials):
                raise ValueError("checkpoint current material binding changed")
            stage_bindings = {(s.run_id, s.stage_key): s for s in plan.reused_stages}
            if plan.prior_rebase_artifacts:
                parent_runs = {ref.run_id for ref in plan.prior_rebase_artifacts}
                if len(parent_runs) != 1:
                    raise ValueError("prior checkpoint rebase is not one execution")
                parent_run_id = next(iter(parent_runs))
                parent_receipt = self._products.checkpoint_receipt(
                    scope=scope, run_id=parent_run_id, session=session
                )
                if parent_receipt is None or parent_receipt.rebased_base_sha256 is None:
                    raise ValueError("prior checkpoint rebase receipt missing")
                parent_stage = session.scalar(select(ProductStage).where(
                    ProductStage.run_id == parent_run_id,
                    ProductStage.stage_key == "checkpoint",
                ))
                parent_job = session.get(WikiJob, parent_stage.job_id) if parent_stage else None
                for ref in plan.prior_rebase_artifacts:
                    row = session.get(ProductArtifact, ref.artifact_id)
                    if (
                        row is None or parent_job is None
                        or row.space_id != scope.space_id or _ref(row) != ref
                        or row.producer_job_id != parent_stage.job_id
                        or row.producer_generation != parent_job.lease_generation
                        or row.dependency_sha256 != parent_stage.dependency_sha256
                        or hashlib.sha256(row.payload).hexdigest() != ref.payload_sha256
                    ):
                        raise ValueError("prior checkpoint rebase custody changed")
                    if (
                        ref.artifact_kind == "rebased_discovery_disposition"
                        and parent_receipt.rebased_discovery_disposition_sha256
                        != ref.payload_sha256
                    ):
                        raise ValueError("prior discovery disposition receipt changed")
            for stage in plan.reused_stages:
                row = session.get(ProductStage, stage.stage_id)
                job = session.get(WikiJob, stage.job_id)
                self._products._run(session, scope, stage.run_id)
                if (
                    row is None
                    or row.space_id != scope.space_id
                    or self._products._stage_snapshot(session, row) != stage
                    or job is None
                    or job.state != "succeeded"
                ):
                    raise ValueError("checkpoint producer did not complete successfully")
            if plan.failed_discovery_artifact is not None:
                stage = plan.failed_discovery_stage
                ref = plan.failed_discovery_artifact
                stage_row = session.get(ProductStage, stage.stage_id)
                job = session.get(WikiJob, stage.job_id)
                row = session.get(ProductArtifact, ref.artifact_id)
                self._products._run(session, scope, ref.run_id)
                if (
                    stage_row is None or job is None or row is None
                    or job.state != "succeeded"
                    or self._products._stage_snapshot(session, stage_row) != stage
                    or row.space_id != scope.space_id or _ref(row) != ref
                    or row.producer_job_id != stage.job_id
                    or row.producer_generation != job.lease_generation
                    or row.dependency_sha256 != stage.dependency_sha256
                    or hashlib.sha256(row.payload).hexdigest() != ref.payload_sha256
                ):
                    raise ValueError("discovery failure proof changed")
                summary = json.loads(row.payload)
                if (
                    summary.get("state") != "FAILED"
                    or stage.state != "partial_success"
                    or (ref.artifact_kind, stage.stage_key) not in {
                        ("discovery_summary", "discovery"),
                        ("discovery_final_summary", "compilation"),
                    }
                ):
                    raise ValueError("discovery failure proof is not technical")
            # Stable artifacts/calls are held FOR SHARE during their complete read.
            # Active job fencing happens only after this pure verification returns.
            by_kind = {}
            for ref in sorted(plan.artifacts, key=lambda r: r.artifact_id):
                row = session.scalar(
                    select(ProductArtifact)
                    .where(ProductArtifact.id == ref.artifact_id)
                    .with_for_update(read=True)
                )
                self._products._run(session, scope, ref.run_id)
                if (
                    row is None
                    or row.space_id != scope.space_id
                    or _ref(row) != ref
                    or hashlib.sha256(row.payload).hexdigest() != ref.payload_sha256
                ):
                    raise ValueError("checkpoint artifact custody changed")
                producing_stage = stage_bindings.get((row.run_id, row.stage_key))
                if (
                    producing_stage is None
                    or producing_stage.job_id != row.producer_job_id
                    or producing_stage.dependency_sha256 != row.dependency_sha256
                ):
                    raise ValueError("checkpoint artifact is not output of its bound stage")
                producer = session.get(WikiJob, row.producer_job_id)
                if (
                    producer is None
                    or producer.state != "succeeded"
                    or producer.lease_generation != row.producer_generation
                ):
                    raise ValueError("checkpoint artifact producer fence changed")
                # Do not retain large native/source bytes after validation.
                if ref.artifact_kind in {
                    "field_plan",
                    "field_validation",
                    "compile_delta",
                    "compile_request",
                }:
                    by_kind[ref.artifact_kind] = json.loads(row.payload)
                session.expunge(row)
            for ref in plan.retry_calls:
                if (
                    self._products._identity_retry_reference(
                        session, scope, ref.record_id, read_lock=True
                    )
                    != ref
                ):
                    raise ValueError("checkpoint retry identity proof changed")
            for ref in plan.failed_calls:
                if (
                    self._products._confirmed_failure_reference(
                        session, scope, ref.record_id, read_lock=True
                    )
                    != ref
                ):
                    raise ValueError("checkpoint confirmed failure proof changed")
            usage = {}
            call_ids = []
            for ref in plan.calls:
                table = ProductModelCall if ref.kind == "field" else ProductStageModelCall
                row = session.scalar(
                    select(table).where(table.id == ref.record_id).with_for_update(read=True)
                )
                self._products._run(session, scope, ref.run_id)
                if (
                    row is None
                    or row.space_id != scope.space_id
                    or any(
                        getattr(row, k) != getattr(ref, k)
                        for k in (
                            "run_id",
                            "call_id",
                            "state",
                            "request_sha256",
                            "raw_sha256",
                        )
                    )
                ):
                    raise ValueError("checkpoint call identity changed")
                for key, sha_key in (
                    ("raw", "raw_sha256"),
                    ("request_bytes", "request_sha256"),
                ):
                    raw = getattr(row, key)
                    sha = getattr(row, sha_key)
                    if (
                        (raw is None) != (sha is None)
                        or raw is not None
                        and hashlib.sha256(raw).hexdigest() != sha
                    ):
                        raise ValueError("checkpoint recorded call bytes changed")
                if row.state == "recorded" and (row.raw is None or row.request_bytes is None):
                    raise ValueError("recorded checkpoint call is incomplete")
                call_stage = "extract" if ref.kind == "field" else row.stage_key
                if row.dispatched_at is not None and call_stage in effective_keys:
                    call_ids.append(row.call_id)
                    if ref.kind == "stage":
                        recorded_usage = row.usage
                    else:
                        settlement = session.scalar(
                            select(ProductWindowSettlement).where(
                                ProductWindowSettlement.window_id == row.window_id
                            )
                        )
                        if settlement is None:
                            raise ValueError("field window settlement missing")
                        recorded_usage = settlement.usage
                    for key, value in recorded_usage.items():
                        usage[key] = usage.get(key, 0) + value
            for ref in plan.audited_calls:
                row = session.scalar(
                    select(ProductStageModelCall)
                    .where(ProductStageModelCall.id == ref.record_id)
                    .with_for_update(read=True)
                )
                self._products._run(session, scope, ref.run_id)
                if (
                    ref.kind != "stage" or row is None
                    or row.space_id != scope.space_id
                    or row.stage_key not in {"discovery", "compilation"}
                    or row.dispatched_at is None or row.state != "recorded"
                    or any(getattr(row, key) != getattr(ref, key) for key in (
                        "run_id", "call_id", "state", "request_sha256", "raw_sha256"
                    ))
                    or row.request_bytes is None or row.raw is None
                    or hashlib.sha256(row.request_bytes).hexdigest() != row.request_sha256
                    or hashlib.sha256(row.raw).hexdigest() != row.raw_sha256
                ):
                    raise ValueError("audited discovery call changed or was not settled")
            fields = {}
            keys = set()
            field_snapshots = []
            for ref in plan.fields:
                row = session.scalar(
                    select(ProductFieldAttempt)
                    .where(ProductFieldAttempt.id == ref.attempt_id)
                    .with_for_update(read=True)
                )
                if (
                    row is None
                    or row.space_id != scope.space_id
                    or row.tenant_id != scope.tenant_id
                    or any(
                        getattr(row, k) != getattr(ref, k)
                        for k in (
                            "run_id",
                            "entity_id",
                            "field_key",
                            "task_sha256",
                            "outcome",
                            "call_id",
                        )
                    )
                ):
                    raise ValueError("checkpoint field identity changed")
                snapshot = self._products._field_snapshot(row)
                field_snapshots.append(snapshot)
                fields[row.id] = field_digest(snapshot)
                keys.add((row.entity_id, row.field_key))
            if "extract" in {s.stage_key for s in plan.reused_stages}:
                expected = {
                    (t["entity_id"], t["field_key"])
                    for w in by_kind["field_plan"]["windows"]
                    for t in w["tasks"]
                }
                if keys != expected:
                    raise ValueError("checkpoint field completion coverage changed")
            if "compile_delta" in by_kind:
                from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
                    BatchConceptCompileRequest830G3V1,
                )
                from insurance_harness.product_ingestion.compilation import project_field_attempts

                request = BatchConceptCompileRequest830G3V1.model_validate(
                    by_kind["compile_request"]
                )
                from insurance_harness.product_ingestion.field_validation import (
                    FieldValidationReport,
                    apply_field_validation,
                )

                if "field_validation" not in by_kind:
                    raise ValueError("checkpoint field validation is missing")
                # The authenticated report derives the compile view; the receipt
                # above continues to bind the immutable original field rows.
                effective = apply_field_validation(
                    tuple(field_snapshots),
                    FieldValidationReport.model_validate(by_kind["field_validation"]),
                )
                delta_ref = next(r for r in plan.artifacts if r.artifact_kind == "compile_delta")
                projection = project_field_attempts(
                    request=request, attempts=effective, run_id=delta_ref.run_id
                )
                actual = {
                    (f["entity_id"], f["field_key"]): f
                    for f in by_kind["compile_delta"]["output"]["fields"]
                }
                for field in projection.output.fields:
                    expected = field.model_dump(mode="json")
                    if actual.get((field.entity_id, field.field_key)) != expected:
                        raise ValueError("checkpoint fields differ from the recorded compile delta")
            if len(call_ids) != len(set(call_ids)):
                raise ValueError("duplicate original call identity")
            return CheckpointReceipt(
                contract=plan.contract.replace("-plan.", "-receipt."),
                execution_workflow_version=plan.execution_workflow_version,
                scope=scope,
                run_id=run_id,
                plan_sha256=plan.digest(),
                reused_stages=tuple(
                    stage for stage in plan.reused_stages if stage.stage_key in effective_keys
                ),
                field_sha256=fields,
                reused_call_ids=tuple(sorted(call_ids)),
                reused_usage=usage,
                unsettled_call_count=sum(c.state != "recorded" for c in plan.calls),
                retry_calls=plan.retry_calls,
                failed_calls=plan.failed_calls,
            )
