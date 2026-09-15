"""Small checkpoint custody controls; no model, network, or full candidate setup."""

from __future__ import annotations

# ruff: noqa: F811 -- imported pytest fixtures.
import pytest
from sqlalchemy import select

from insurance_harness.jobs import SpaceScopeError
from insurance_harness.product_ingestion.artifact_tables import ProductArtifact
from tests.product_ingestion.test_platform import snapshot  # noqa: F401
from tests.product_ingestion.test_recovery import title_unavailable
from tests.product_ingestion.test_routing import catalog  # noqa: F401
from tests.product_ingestion.test_stages import stage_runtime  # noqa: F401


def _child(stage_runtime, monkeypatch):
    scope, store, artifacts, _, _ = stage_runtime
    origin = title_unavailable(stage_runtime, monkeypatch, reason="any-new-diagnostic-text")
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    return scope, store, artifacts, origin, child


def test_checkpoint_selection_uses_outputs_not_failure_text(stage_runtime, monkeypatch):
    scope, store, artifacts, origin, child = _child(stage_runtime, monkeypatch)
    plan = store.checkpoint_plan(scope=scope, run_id=child.run_id)
    assert plan.resume_stage == "routing"
    receipt = artifacts.verify_checkpoint(scope=scope, run_id=child.run_id)
    assert tuple(s.stage_key for s in receipt.reused_stages) == ("uploads", "source")
    assert len(plan.artifacts) == 4
    assert store.get_run(scope=scope, run_id=origin.run_id) == origin
    assert store.checkpoint_receipt(scope=scope, run_id=child.run_id) is None
    # A computed in-memory proof is not yet a committed job receipt.
    with pytest.raises(SpaceScopeError):
        artifacts.get_effective_artifact(
            scope=scope,
            run_id=child.run_id,
            artifact_kind="source_snapshot",
            artifact_key=plan.materials[0].knowledge_id,
        )


@pytest.mark.parametrize("change", ["bytes", "missing", "foreign", "generation", "dependency"])
def test_checkpoint_worker_rejects_changed_original_asset(stage_runtime, monkeypatch, change):
    scope, store, artifacts, _, child = _child(stage_runtime, monkeypatch)
    plan = store.checkpoint_plan(scope=scope, run_id=child.run_id)
    ref = next(r for r in plan.artifacts if r.artifact_kind == "source_snapshot")
    with store._session_factory() as session, session.begin():
        row = session.get(ProductArtifact, ref.artifact_id)
        if change == "bytes":
            row.payload = b"{}"  # Keep the stored digest unchanged.
        elif change == "missing":
            session.delete(row)
        elif change == "foreign":
            row.space_id = "foreign-space"
        elif change == "generation":
            row.producer_generation += 1
        else:
            row.dependency_sha256 = "f" * 64
    with pytest.raises((ValueError, SpaceScopeError)):
        artifacts.verify_checkpoint(scope=scope, run_id=child.run_id)
    assert store.checkpoint_receipt(scope=scope, run_id=child.run_id) is None


def test_checkpoint_unknown_dispatch_cannot_become_new_identity_call(stage_runtime, monkeypatch):
    from datetime import UTC, datetime

    from insurance_harness.product_ingestion.artifact_tables import ProductStageModelCall

    scope, store, _, origin, _ = _child(stage_runtime, monkeypatch)
    # An unresolved dispatch is audit evidence, not permission for another send.
    with store._session_factory() as session, session.begin():
        session.add(
            ProductStageModelCall(
                id="unknown",
                call_id="unknown",
                run_id=origin.run_id,
                space_id=scope.space_id,
                stage_key="identity",
                operation_key="current-product-identity",
                job_id="original-job",
                generation=1,
                attempt=0,
                dependency_sha256="a" * 64,
                input_sha256="a" * 64,
                model_policy_sha256="a" * 64,
                prompt_policy_sha256="a" * 64,
                state="dispatched",
                request_sha256="a" * 64,
                request_bytes=b"original",
                raw_ref="original-raw",
                usage={},
                reserved_at=datetime.now(UTC),
                dispatched_at=datetime.now(UTC),
            )
        )
    assert not store.can_retry_processing(scope=scope, run_id=origin.run_id)


def test_missing_observer_summary_does_not_invalidate_source_checkpoint(stage_runtime, monkeypatch):
    scope, store, artifacts, origin, _ = _child(stage_runtime, monkeypatch)
    with store._session_factory() as session, session.begin():
        row = session.scalar(
            select(ProductArtifact).where(
                ProductArtifact.run_id == origin.run_id,
                ProductArtifact.artifact_kind == "source_processing_summary",
            )
        )
        session.delete(row)
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    plan = store.checkpoint_plan(scope=scope, run_id=child.run_id)
    assert plan.resume_stage == "routing" and len(plan.artifacts) == 3
    assert len(artifacts.verify_checkpoint(scope=scope, run_id=child.run_id).reused_stages) == 2


def test_failed_verifier_recovery_flattens_refs_without_faking_success(stage_runtime, monkeypatch):
    from datetime import UTC, datetime

    from insurance_harness.jobs.tables import WikiJob
    from tests.product_ingestion.test_recovery import finish_failed_source

    scope, store, artifacts, origin, child = _child(stage_runtime, monkeypatch)
    assert not store.can_retry_processing(scope=scope, run_id=child.run_id)
    stage = store.list_stages(scope=scope, run_id=child.run_id)[0]
    with store._session_factory() as session, session.begin():
        row = session.get(WikiJob, stage.job_id)
        row.state = "dead_letter"
        row.finished_at = datetime.now(UTC)
    finish_failed_source(store, scope, child.run_id)
    failed = store.get_run(scope=scope, run_id=child.run_id)
    resumed = store.retry_processing(
        scope=scope, run_id=child.run_id, expected_version=failed.version
    )
    plan = store.checkpoint_plan(scope=scope, run_id=resumed.run_id)
    assert plan.origin_run_id == child.run_id
    assert all(ref.run_id == origin.run_id for ref in plan.artifacts)
    assert all(s.run_id == origin.run_id for s in plan.reused_stages)
    assert (
        artifacts.verify_checkpoint(scope=scope, run_id=resumed.run_id).plan_sha256 == plan.digest()
    )


def _enqueue_control(store, scope, origin):
    """Old recovery admission stored a control input before the source job claim."""
    import hashlib

    with store._session_factory() as session, session.begin():
        source = session.scalar(
            select(ProductArtifact)
            .where(
                ProductArtifact.run_id == origin.run_id,
                ProductArtifact.artifact_kind == "source_snapshot",
            )
            .limit(1)
        )
        values = {c.name: getattr(source, c.name) for c in ProductArtifact.__table__.columns}
        values.update(
            id="enqueue-control",
            artifact_kind="processing_recovery_plan",
            payload=b"{}",
            payload_sha256=hashlib.sha256(b"{}").hexdigest(),
            dependency_sha256="f" * 64,
            producer_generation=0,
        )
        session.add(ProductArtifact(**values))


def test_checkpoint_excludes_enqueue_control_input(stage_runtime, monkeypatch):
    scope, store, artifacts, origin, _ = _child(stage_runtime, monkeypatch)
    _enqueue_control(store, scope, origin)
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    plan = store.checkpoint_plan(scope=scope, run_id=child.run_id)
    assert all(ref.producer_generation > 0 for ref in plan.artifacts)
    assert len([r for r in plan.artifacts if r.artifact_kind == "source_snapshot"]) == 3
    assert (
        artifacts.verify_checkpoint(scope=scope, run_id=child.run_id).plan_sha256 == plan.digest()
    )
    assert store.get_run(scope=scope, run_id=origin.run_id) == origin


def test_retry_failed_checkpoint_excludes_inherited_control_without_rewriting_plan(
    stage_runtime, monkeypatch
):
    from datetime import UTC, datetime

    from insurance_harness.jobs.tables import WikiJob
    from insurance_harness.product_ingestion.checkpoint_store import _ref
    from tests.product_ingestion.test_recovery import finish_failed_source

    scope, store, artifacts, origin, child = _child(stage_runtime, monkeypatch)
    _enqueue_control(store, scope, origin)
    plan = store.checkpoint_plan(scope=scope, run_id=child.run_id)
    stage = store.list_stages(scope=scope, run_id=child.run_id)[0]
    # Reproduce the persisted plan admitted by the old deployed selector.
    with store._session_factory() as session, session.begin():
        control = session.get(ProductArtifact, "enqueue-control")
        old_plan = plan.model_copy(update={"artifacts": (*plan.artifacts, _ref(control))})
        saved = session.scalar(
            select(ProductArtifact).where(
                ProductArtifact.run_id == child.run_id,
                ProductArtifact.artifact_kind == "checkpoint_plan",
            )
        )
        saved.payload, saved.payload_sha256 = old_plan.encoded(), old_plan.digest()
        job = session.get(WikiJob, stage.job_id)
        job.state, job.finished_at = "dead_letter", datetime.now(UTC)
    finish_failed_source(store, scope, child.run_id)
    failed = store.get_run(scope=scope, run_id=child.run_id)
    resumed = store.retry_processing(
        scope=scope, run_id=child.run_id, expected_version=failed.version
    )
    new_plan = store.checkpoint_plan(scope=scope, run_id=resumed.run_id)
    assert all(ref.producer_generation > 0 for ref in new_plan.artifacts)
    assert (
        artifacts.verify_checkpoint(scope=scope, run_id=resumed.run_id).plan_sha256
        == new_plan.digest()
    )
    assert store.checkpoint_plan(scope=scope, run_id=child.run_id).encoded() == old_plan.encoded()
    assert store.get_run(scope=scope, run_id=child.run_id) == failed


def test_zero_generation_artifact_cannot_satisfy_required_output(stage_runtime, monkeypatch):
    scope, store, _, origin, _ = _child(stage_runtime, monkeypatch)
    with store._session_factory() as session, session.begin():
        for row in session.scalars(
            select(ProductArtifact).where(
                ProductArtifact.run_id == origin.run_id,
                ProductArtifact.artifact_kind == "source_snapshot",
            )
        ):
            row.producer_generation = 0
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    plan = store.checkpoint_plan(scope=scope, run_id=child.run_id)
    assert plan.resume_stage == "source"
    assert tuple(s.stage_key for s in plan.reused_stages) == ("uploads",)


def test_checkpoint_contract_is_bound_to_child_workflow(stage_runtime, monkeypatch):
    from insurance_harness.product_ingestion.tables import ProductRun

    scope, store, _, _, child = _child(stage_runtime, monkeypatch)
    plan = store.checkpoint_plan(scope=scope, run_id=child.run_id)
    assert plan.contract == "product-stage-checkpoint-plan.830.v2"
    assert child.workflow_version == 2
    with store._session_factory() as session, session.begin():
        session.get(ProductRun, child.run_id).workflow_version = 1
    with pytest.raises(ValueError, match="workflow"):
        store.checkpoint_plan(scope=scope, run_id=child.run_id)


def test_legacy_checkpoint_bytes_keep_original_contract(stage_runtime, monkeypatch):
    from insurance_harness.product_ingestion.checkpoints import CheckpointPlan

    scope, store, _, _, child = _child(stage_runtime, monkeypatch)
    plan = store.checkpoint_plan(scope=scope, run_id=child.run_id)
    data = plan.model_dump(mode="json")
    data["contract"] = "product-stage-checkpoint-plan.830.v1"
    import json

    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
    legacy = CheckpointPlan.model_validate_json(raw)
    assert legacy.encoded() == raw
    assert legacy.workflow_version == 1
