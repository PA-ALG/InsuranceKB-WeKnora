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
