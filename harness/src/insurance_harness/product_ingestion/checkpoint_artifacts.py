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
                refs = [r for r in plan.artifacts
                        if artifact_kind is None or r.artifact_kind == artifact_kind]
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

    def verify_checkpoint(self, *, scope, run_id):
        """Expensive worker-only validation. No job row lock and no provider effects."""
        with self._session_factory() as session, session.begin():
            plan = self._products.checkpoint_plan(scope=scope, run_id=run_id, session=session)
            if plan is None:
                raise ValueError("checkpoint plan missing")
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
                if row.dispatched_at is not None:
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
                scope=scope,
                run_id=run_id,
                plan_sha256=plan.digest(),
                reused_stages=plan.reused_stages,
                field_sha256=fields,
                reused_call_ids=tuple(sorted(call_ids)),
                reused_usage=usage,
                unsettled_call_count=sum(c.state != "recorded" for c in plan.calls),
                retry_calls=plan.retry_calls,
                failed_calls=plan.failed_calls,
            )
