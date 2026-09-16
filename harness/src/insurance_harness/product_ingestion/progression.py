"""Short durable stages advanced by outbox delivery and crash reconciliation."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from insurance_harness.jobs import JobState, JobStore
from insurance_harness.jobs.models import ErrorClass
from insurance_harness.product_ingestion.checkpoints import STAGE_ORDER as STAGES  # noqa: F401
from insurance_harness.product_ingestion.checkpoints import stage_order
from insurance_harness.product_ingestion.models import (
    ProductRunState,
    ProductScope,
    WindowTaskSpec,
)
from insurance_harness.product_ingestion.store import ProductIngestionStore

_GOOD = {"succeeded", "partial_success"}
_BAD = {"failed", "blocked", "dead_letter"}
_FINAL = {
    ProductRunState.SUCCEEDED,
    ProductRunState.PARTIAL_SUCCESS,
    ProductRunState.FAILED,
    ProductRunState.NEEDS_CONFIRMATION,
}


@dataclass(frozen=True)
class PlannedWindow:
    window_key: str
    dependency_sha256: str
    tasks: tuple[WindowTaskSpec, ...]


def admit_uploads(store: ProductIngestionStore, scope: ProductScope, run_id: str):
    """Admission is a short stage, never a waiting root/finalizer."""
    digest = hashlib.sha256(("product-uploads.v1\0" + run_id).encode()).hexdigest()
    return store.enqueue_stage(
        scope=scope,
        run_id=run_id,
        stage_key="uploads",
        dependency_sha256=digest,
        idempotency_key=f"{run_id}:uploads:{digest}",
    )


class ProductProgression:
    def __init__(
        self,
        *,
        store: ProductIngestionStore,
        jobs: JobStore,
        read_window_plan: Callable[[ProductScope, str], Sequence[PlannedWindow]],
        read_window_plan_identity: Callable[[ProductScope, str], object] | None = None,
    ):
        self.store, self.jobs, self.read_window_plan = store, jobs, read_window_plan
        self.read_window_plan_identity = read_window_plan_identity
        # One compact completed fanout per scope. Never retain field/source bodies.
        # A restart reconstructs this only through the normal durable reconciliation.
        self._fanouts: dict[str, tuple[object, tuple[str, ...]]] = {}

    def _stage_failure(self, scope, stages):
        for stage in stages:
            if stage.state not in _BAD:
                continue
            job = self.jobs.get_job(space_id=scope.space_id, job_id=stage.job_id)
            if (
                job.state is JobState.BLOCKED
                and job.error_class is ErrorClass.CAPACITY_BLOCKED
                and "needs_confirmation:" in (job.error_summary or "")
            ):
                return ProductRunState.NEEDS_CONFIRMATION
            return ProductRunState.FAILED
        return None

    def advance(self, scope: ProductScope, run_id: str) -> None:
        run = self.store.get_run(scope=scope, run_id=run_id)
        if run.state in _FINAL:
            return
        rows = self.store.list_stages(scope=scope, run_id=run_id)
        if self._stage_failure(scope, rows) is not None:
            self.store.enqueue_root(
                scope=scope, run_id=run_id, idempotency_key="product-root:" + run_id
            )
            return
        stages = {stage.stage_key: stage for stage in rows}
        checkpoint = self.store.checkpoint_plan(scope=scope, run_id=run_id)
        receipt = self.store.checkpoint_receipt(scope=scope, run_id=run_id)
        if checkpoint is not None and receipt is None:
            return
        if receipt is not None:
            stages.update({stage.stage_key: stage for stage in receipt.reused_stages})
        order = stage_order(run.workflow_version)
        for key in order:
            stage = stages.get(key)
            if stage is not None:
                if stage.state not in _GOOD:
                    return
                continue
            if key == "uploads":
                admit_uploads(self.store, scope, run_id)
                return
            if key == "extract":
                window_jobs = self._window_jobs(scope, run_id)
                states = [
                    self.jobs.get_job(space_id=scope.space_id, job_id=job_id).state
                    for job_id in window_jobs
                ]
                if any(
                    state not in {JobState.SUCCEEDED, JobState.BLOCKED, JobState.DEAD_LETTER}
                    for state in states
                ):
                    return
                # The aggregate stage handles terminal failed windows explicitly.
                # A missing ordinary field does not itself make a product fail.
            parent = stages[order[order.index(key) - 1]]
            digest = hashlib.sha256(
                (run_id + "\0" + key + "\0" + parent.dependency_sha256).encode()
            ).hexdigest()
            self.store.enqueue_stage(
                scope=scope,
                run_id=run_id,
                stage_key=key,
                dependency_sha256=digest,
                idempotency_key=f"{run_id}:{key}:{digest}",
                parent_job_id=parent.job_id,
            )
            return
        self.store.enqueue_root(
            scope=scope, run_id=run_id, idempotency_key="product-root:" + run_id
        )

    def _window_jobs(self, scope: ProductScope, run_id: str) -> tuple[str, ...]:
        identity_reader = self.read_window_plan_identity
        identity = identity_reader(scope, run_id) if identity_reader is not None else None
        key = (scope, run_id, identity)
        cached = self._fanouts.get(scope.space_id)
        if identity_reader is not None and cached is not None and cached[0] == key:
            return cached[1]
        plan = tuple(self.read_window_plan(scope, run_id))
        if len({item.window_key for item in plan}) != len(plan):
            raise ValueError("field plan must contain unique sealed windows")
        field_keys = [(task.entity_id, task.field_key) for item in plan for task in item.tasks]
        if len(field_keys) != len(set(field_keys)):
            raise ValueError("field plan contains duplicate field tasks")
        # Reconcile every expected window after a restart or interrupted fanout.
        # Publish the compact cache only when all durable registrations succeeded.
        job_ids = tuple(
            self.store.enqueue_window(
                scope=scope,
                run_id=run_id,
                stage_key="extract",
                window_key=item.window_key,
                dependency_sha256=item.dependency_sha256,
                tasks=item.tasks,
            ).job_id
            for item in plan
        )
        if identity_reader is not None:
            if identity_reader(scope, run_id) != identity:
                raise ValueError("field plan identity changed during fanout")
            self._fanouts[scope.space_id] = (key, job_ids)
        return job_ids

    def final_state(self, scope: ProductScope, run_id: str) -> ProductRunState:
        rows = self.store.list_stages(scope=scope, run_id=run_id)
        failure = self._stage_failure(scope, rows)
        if failure is not None:
            return failure
        stages = {stage.stage_key: stage for stage in rows}
        receipt = self.store.checkpoint_receipt(scope=scope, run_id=run_id)
        if receipt is not None:
            stages.update({stage.stage_key: stage for stage in receipt.reused_stages})
        run = self.store.get_run(scope=scope, run_id=run_id)
        if any(
            key not in stages or stages[key].state not in _GOOD
            for key in stage_order(run.workflow_version)
        ):
            raise ValueError("product publication barrier is not complete")
        return (
            ProductRunState.PARTIAL_SUCCESS
            if run.failure_count
            or run.missing_count
            or any(stage.state == "partial_success" for stage in stages.values())
            else ProductRunState.SUCCEEDED
        )
