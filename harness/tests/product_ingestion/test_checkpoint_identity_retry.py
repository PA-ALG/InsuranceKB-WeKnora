"""Explicit public checkpoint recovery of recorded semantic identity failure."""

from __future__ import annotations

# ruff: noqa: F811 -- imported pytest fixtures
import hashlib
import json

import pytest

from tests.product_ingestion.test_identity_recovery import (  # noqa: F401
    catalog,
    recorded_origin,
    snapshot,
    stage_runtime,
)


def test_public_checkpoint_retries_recorded_identity_without_cloning_success(
    stage_runtime, recorded_origin
):
    scope, store, artifacts, _, _ = stage_runtime
    origin, original, _, _, sent = recorded_origin
    before = artifacts.list_stage_calls(scope=scope, run_id=origin.run_id)
    assert store.can_retry_processing(scope=scope, run_id=origin.run_id)
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    assert (
        store.retry_processing(
            scope=scope, run_id=origin.run_id, expected_version=origin.version
        ).run_id
        == child.run_id
    )
    plan = store.checkpoint_plan(scope=scope, run_id=child.run_id)
    assert plan.contract.endswith(".v5") and plan.workflow_version == 3
    assert plan.resume_stage == "identity"
    assert [s.stage_key for s in plan.reused_stages] == ["uploads", "source", "routing"]
    from sqlalchemy import select

    from insurance_harness.product_ingestion.artifact_tables import ProductArtifact

    with store._session_factory() as session:
        row = session.scalar(
            select(ProductArtifact).where(
                ProductArtifact.run_id == child.run_id,
                ProductArtifact.artifact_kind == "checkpoint_plan",
            )
        )
        assert row.contract_version == "5"
    assert not plan.calls and len(plan.retry_calls) == 1
    assert plan.retry_calls[0].proof.call_id == original.call_id
    receipt = artifacts.verify_checkpoint(scope=scope, run_id=child.run_id)
    assert receipt.contract.endswith(".v5")
    assert receipt.retry_calls == plan.retry_calls
    assert not receipt.reused_call_ids and not receipt.reused_usage
    assert len(sent) == 1  # admission and verification do not send
    assert artifacts.list_stage_calls(scope=scope, run_id=origin.run_id) == before
    assert store.get_run(scope=scope, run_id=origin.run_id) == origin


@pytest.mark.parametrize("contract", ["v1", "v2", "v3", "v4"])
def test_old_checkpoint_wire_bytes_remain_exact(stage_runtime, recorded_origin, contract):
    from insurance_harness.product_ingestion.checkpoints import CheckpointPlan

    scope, store, *_ = stage_runtime
    origin = recorded_origin[0]
    # Construct the old completed source prefix from the actual fixture rows.
    stages = store.list_stages(scope=scope, run_id=origin.run_id)
    payload = dict(
        contract="product-stage-checkpoint-plan.830." + contract,
        scope=scope.model_dump(mode="json"),
        origin_run_id=origin.run_id,
        origin_version=origin.version,
        upload_run_id=origin.run_id,
        resume_stage="identity",
        materials=[m.model_dump(mode="json") for m in origin.materials],
        reused_stages=[
            s.model_dump(mode="json")
            for s in stages
            if s.stage_key in {"uploads", "source", "routing"}
        ],
        artifacts=[],
        calls=[],
        fields=[],
    )
    if contract in {"v3", "v4"}:
        payload["retry_calls"] = []
    if contract == "v4":
        payload["failed_calls"] = []
    wire = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    plan = CheckpointPlan.model_validate_json(wire)
    assert plan.encoded() == wire
    assert plan.digest() == hashlib.sha256(wire).hexdigest()
    assert ("retry_calls" in plan.model_dump(mode="json")) == (contract in {"v3", "v4"})
    from insurance_harness.product_ingestion.checkpoints import CheckpointReceipt

    data = dict(
        contract="product-stage-checkpoint-receipt.830." + contract,
        scope=payload["scope"],
        run_id="child",
        plan_sha256=plan.digest(),
        reused_stages=payload["reused_stages"],
        field_sha256={},
        reused_call_ids=[],
        reused_usage={},
        unsettled_call_count=0,
    )
    if contract in {"v3", "v4"}:
        data["retry_calls"] = []
    if contract == "v4":
        data["failed_calls"] = []
    encoded = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
    receipt = CheckpointReceipt.model_validate_json(encoded)
    assert receipt.encoded() == encoded and receipt.digest() == hashlib.sha256(encoded).hexdigest()


@pytest.mark.parametrize(
    "change",
    [
        "raw",
        "request",
        "generation",
        "dependency",
        "active",
        "unknown",
        "diagnostic",
        "scope",
        "failure_reason",
    ],
)
@pytest.mark.parametrize("after_admission", [False, True])
def test_recorded_identity_retry_rejects_changed_proof(
    stage_runtime, recorded_origin, change, after_admission
):
    from sqlalchemy import select

    from insurance_harness.jobs import SpaceScopeError
    from insurance_harness.jobs.tables import WikiJob
    from insurance_harness.product_ingestion.artifact_tables import ProductStageModelCall

    scope, store, artifacts, *_ = stage_runtime
    origin = recorded_origin[0]
    child = (
        store.retry_processing(scope=scope, run_id=origin.run_id, expected_version=origin.version)
        if after_admission
        else None
    )
    with store._session_factory() as session, session.begin():
        call = session.scalar(
            select(ProductStageModelCall).where(ProductStageModelCall.run_id == origin.run_id)
        )
        job = session.get(WikiJob, call.job_id)
        if change == "raw":
            call.raw = b"changed"
        elif change == "request":
            call.request_bytes = b"changed"
        elif change == "generation":
            call.generation += 1
        elif change == "dependency":
            call.dependency_sha256 = "f" * 64
        elif change == "active":
            job.state = "queued"
        elif change == "unknown":
            call.state = "interrupted"
        elif change == "diagnostic":
            call.diagnostic = "bad format capture"
        elif change == "scope":
            call.space_id = "other"
        else:
            job.error_summary = "needs_confirmation:UNRELATED_FAILURE"
    if child:
        with pytest.raises((ValueError, SpaceScopeError)):
            artifacts.verify_checkpoint(scope=scope, run_id=child.run_id)
    else:
        assert not store.can_retry_processing(scope=scope, run_id=origin.run_id)


def test_failed_checkpoint_retains_single_recorded_retry_reference(stage_runtime, recorded_origin):
    from insurance_harness.jobs.tables import WikiJob
    from tests.product_ingestion.test_recovery import finish_failed_source

    scope, store, artifacts, *_ = stage_runtime
    origin = recorded_origin[0]
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    old = store.checkpoint_plan(scope=scope, run_id=child.run_id)
    stage = store.list_stages(scope=scope, run_id=child.run_id)[0]
    with store._session_factory() as session, session.begin():
        row = session.get(WikiJob, stage.job_id)
        row.state = "blocked"
    finish_failed_source(store, scope, child.run_id)
    failed = store.get_run(scope=scope, run_id=child.run_id)
    next_run = store.retry_processing(
        scope=scope, run_id=child.run_id, expected_version=failed.version
    )
    plan = store.checkpoint_plan(scope=scope, run_id=next_run.run_id)
    assert plan.retry_calls == old.retry_calls
    assert (
        artifacts.verify_checkpoint(scope=scope, run_id=next_run.run_id).retry_calls
        == old.retry_calls
    )


@pytest.mark.asyncio
async def test_real_worker_retries_identity_once_and_reuses_all_sources(tmp_path):
    from insurance_harness.db.base import Base, make_session_factory
    from insurance_harness.jobs import JobStore
    from insurance_harness.product_ingestion.models import ProductRunState
    from insurance_harness.product_ingestion.progression import admit_uploads
    from tests.product_ingestion.test_pipeline_runtime import (
        SCOPE,
        FixtureModel,
        FixturePlatform,
        _base_snapshot_with_navigation,
        _compose,
        _finish,
        _settings,
        _sqlite_engine,
    )

    class Model(FixtureModel):
        bad_identity = True

        def _identity(self, content):
            output = super()._identity(content)
            if self.bad_identity:
                for material in output["materials"]:
                    for entity in material["entities"]:
                        entity["version_label"] = None
                        entity["filing_or_registration"] = None
                        entity["product_code"] = None
            return output

    base, parent = _base_snapshot_with_navigation()
    settings = _settings(tmp_path, parent)
    engine = _sqlite_engine(tmp_path / "identity-checkpoint.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    jobs = JobStore(factory, settings.job_runtime_config())
    platform, model = FixturePlatform(base), Model()
    runtime, context, model_client = await _compose(settings, factory, platform, model)
    try:
        origin = context.store.create_run(
            scope=SCOPE, idempotency_key="identity-checkpoint", expected_upload_count=3
        )
        admit_uploads(context.store, SCOPE, origin.run_id)
        failed = await _finish(runtime, context, jobs, origin.run_id)
        assert failed.state is ProductRunState.NEEDS_CONFIRMATION
        assert failed.terminal_reason.startswith("PRODUCT_IDENTITY_UNRESOLVED:")
        assert len(model.identity_requests) == 1 and not model.field_requests
        captures = platform.source_captures
        before = context.artifacts.list_stage_calls(scope=SCOPE, run_id=origin.run_id)
        model.bad_identity = False
        child = context.store.retry_processing(
            scope=SCOPE, run_id=origin.run_id, expected_version=failed.version
        )
        final = await _finish(runtime, context, jobs, child.run_id)
        assert final.state is ProductRunState.PARTIAL_SUCCESS
        assert len(model.identity_requests) == 2 and platform.source_captures == captures
        assert model.discovery_requests
        assert any(
            stage.stage_key == "discovery" and stage.state == "succeeded"
            for stage in context.store.list_stages(scope=SCOPE, run_id=child.run_id)
        )
        assert platform.activations == 1
        assert context.artifacts.list_stage_calls(scope=SCOPE, run_id=origin.run_id) == before
        assert context.store.get_run(scope=SCOPE, run_id=origin.run_id) == failed
        receipt = context.store.checkpoint_receipt(scope=SCOPE, run_id=child.run_id)
        assert not receipt.reused_call_ids and len(receipt.retry_calls) == 1
        new = context.artifacts.list_stage_calls(scope=SCOPE, run_id=child.run_id)
        identity = [call for call in new if call.stage_key == "identity"]
        assert len(identity) == 1 and identity[0].call_id != before[0].call_id
    finally:
        await runtime.close()
        await model_client.aclose()
        engine.dispose()


def test_recorded_identity_http_recovery_is_explicit_and_idempotent(stage_runtime, recorded_origin):
    from fastapi.testclient import TestClient

    from insurance_harness.service_shell.cli import build_api_app
    from insurance_harness.service_shell.config import ShellSettings
    from insurance_harness.service_shell.health import Lifecycle, ReadinessChecker
    from tests.product_ingestion.test_api import RECORDS

    scope, store, _, _, _ = stage_runtime
    from tests.product_ingestion.test_api import PATH, auth

    origin = recorded_origin[0]
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    readiness = ReadinessChecker(
        lifecycle=lifecycle, probe=lambda: None, timeout_seconds=0.1, freshness_seconds=1
    )
    settings = ShellSettings(
        postgres_dsn="postgresql://fixture@localhost/fixture",
        principal_records_json=json.dumps(RECORDS),
        principal_space_ids=(scope.space_id,),
        product_ingestion_enabled=True,
        product_ingestion_scopes_json=json.dumps([scope.model_dump()]),
    )
    app = build_api_app(
        settings=settings,
        lifecycle=lifecycle,
        readiness=readiness,
        session_factory=store._session_factory,
    )
    with TestClient(app) as client:
        path = PATH + "/" + origin.run_id
        before = client.get(path, headers=auth()).json()["data"]
        assert before["can_retry_processing"] and before["state"] == "needs_confirmation"
        response = client.post(
            path + "/retry-processing", headers=auth(), json={"expected_version": origin.version}
        )
        assert response.status_code == 201, response.text
        child = response.json()["data"]
        assert child["retry_of_run_id"] == origin.run_id and not child["can_retry_processing"]
        again = client.post(
            path + "/retry-processing", headers=auth(), json={"expected_version": origin.version}
        )
        assert again.json()["data"]["run_id"] == child["run_id"]
        assert (
            client.post(
                path + "/retry-processing",
                headers=auth(),
                json={"expected_version": origin.version + 1},
            ).status_code
            == 409
        )
        assert client.get(path, headers=auth()).json()["data"] == before
