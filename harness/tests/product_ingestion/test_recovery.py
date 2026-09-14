from __future__ import annotations

import hashlib

# ruff: noqa: F811 -- imported pytest fixtures.
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from insurance_harness.jobs import JobState, NonRetryableJobError
from insurance_harness.jobs.tables import WikiJob
from insurance_harness.product_ingestion import tables
from tests.product_ingestion.test_api import PATH, auth, environment  # noqa: F401
from tests.product_ingestion.test_platform import snapshot  # noqa: F401
from tests.product_ingestion.test_routing import catalog  # noqa: F401
from tests.product_ingestion.test_stages import stage_runtime  # noqa: F401


def finish_failed_source(store, scope, run_id):
    """Fixture-only terminal receipt, equivalent to the production root finalizer."""
    now = datetime.now(UTC)
    with store._session_factory() as session, session.begin():
        session.add(
            tables.ProductRunFinalization(
                id=str(uuid4()),
                run_id=run_id,
                space_id=scope.space_id,
                state="failed",
                success_count=0,
                missing_count=0,
                failure_count=0,
                model_call_count=0,
                usage={},
                started_at=now,
                finished_at=now,
            )
        )


def failed_capture(stage_runtime):
    scope, store, artifacts, platform, execute = stage_runtime
    run = store.create_run(scope=scope, idempotency_key="capture-failed", expected_upload_count=3)
    assert execute(run).state is JobState.SUCCEEDED
    capture = platform.capture_source

    async def unavailable(*_):
        raise NonRetryableJobError("PLATFORM_REJECTED_HTTP_409")

    platform.capture_source = unavailable
    assert execute(run).state is JobState.DEAD_LETTER
    finish_failed_source(store, scope, run.run_id)
    platform.capture_source = capture
    return store.get_run(scope=scope, run_id=run.run_id)


def title_unavailable(stage_runtime, monkeypatch, reason="FIRST_PAGE_PRODUCT_NAME_UNAVAILABLE"):
    from insurance_harness.product_ingestion import stages

    scope, store, _, _, execute = stage_runtime
    run = store.create_run(
        scope=scope, idempotency_key="title-unavailable", expected_upload_count=3
    )
    assert execute(run).state is JobState.SUCCEEDED
    assert execute(run).state is JobState.SUCCEEDED

    def unavailable(*args, **kwargs):
        raise ValueError(reason)

    with monkeypatch.context() as patch:
        patch.setattr(stages, "prepare_identity_routing", unavailable)
        blocked = execute(run)
    assert blocked.state is JobState.BLOCKED
    # Fixture root points to the actual blocked terminal receipt.
    with store._session_factory() as session, session.begin():
        session.get(tables.ProductRun, run.run_id).root_job_id = blocked.id
    return store.get_run(scope=scope, run_id=run.run_id)


def test_title_recovery_reuses_exact_sources_and_keeps_original_terminal(
    stage_runtime, monkeypatch
):
    scope, store, artifacts, platform, execute = stage_runtime
    origin = title_unavailable(stage_runtime, monkeypatch)
    assert origin.state.value == "needs_confirmation"
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
    plan = store.processing_recovery_plan(scope=scope, run_id=child.run_id)
    assert plan.contract == "product-processing-recovery-plan.830.v2"
    assert plan.mode == "REUSE_SEALED_SOURCES"
    assert len(plan.source_snapshots) == 3
    for _ in range(3):
        assert execute(child).state is JobState.SUCCEEDED
    assert platform.calls == 3
    for old in artifacts.list_artifacts(
        scope=scope, run_id=origin.run_id, artifact_kind="source_snapshot"
    ):
        new = artifacts.get_artifact(
            scope=scope,
            run_id=child.run_id,
            artifact_kind="source_snapshot",
            artifact_key=old.artifact_key,
        )
        assert new.payload == old.payload
    assert store.get_run(scope=scope, run_id=origin.run_id) == origin


@pytest.mark.parametrize(
    "reason", ["PRODUCT_IDENTITY_OR_VERSION_CONFLICT", "SOURCE_REVISION_CHANGED"]
)
def test_title_recovery_does_not_allow_real_conflicts(stage_runtime, monkeypatch, reason):
    scope, store, _, _, _ = stage_runtime
    origin = title_unavailable(stage_runtime, monkeypatch, reason)
    assert not store.can_retry_processing(scope=scope, run_id=origin.run_id)
    with pytest.raises(ValueError):
        store.retry_processing(scope=scope, run_id=origin.run_id, expected_version=origin.version)


@pytest.mark.parametrize("change", ["missing", "corrupt", "binding", "attempt"])
def test_title_recovery_source_changes_fail_closed(stage_runtime, monkeypatch, change):
    from insurance_harness.product_ingestion.artifact_tables import ProductArtifact

    scope, store, _, platform, execute = stage_runtime
    origin = title_unavailable(stage_runtime, monkeypatch)
    if change in {"missing", "corrupt"}:
        with store._session_factory() as session, session.begin():
            saved = session.scalar(
                select(ProductArtifact).where(
                    ProductArtifact.run_id == origin.run_id,
                    ProductArtifact.artifact_kind == "source_snapshot",
                )
            )
            if change == "missing":
                session.delete(saved)
            else:
                saved.payload = b"{}"
        assert not store.can_retry_processing(scope=scope, run_id=origin.run_id)
        return
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    lookup = platform.lookup_upload

    async def changed(scope, run_id, ordinal):
        item = await lookup(scope, run_id, ordinal)
        if change == "binding":
            item["knowledge_id"] = "different"
        else:
            item["parse_attempt"] += 1
        return item

    platform.lookup_upload = changed
    assert execute(child).state is JobState.SUCCEEDED
    assert execute(child).state is JobState.DEAD_LETTER
    assert platform.calls == 3


def test_recovery_v1_wire_bytes_are_unchanged():
    from insurance_harness.product_ingestion.models import OriginalKnowledgeRef, ProductScope
    from insurance_harness.product_ingestion.recovery import ProcessingRecoveryPlan

    raw = (
        b'{"contract":"product-processing-recovery-plan.830.v1",'
        b'"mode":"RECAPTURE_COMPLETED_SOURCES",'
        b'"scope":{"tenant_id":"1","space_id":"space","raw_knowledge_base_id":"raw",'
        b'"wiki_knowledge_base_id":"wiki"},"origin_run_id":"old","origin_version":1,'
        b'"upload_run_id":"upload","materials":[{"knowledge_id":"k",'
        b'"original_filename":"file.pdf","upload_ordinal":0}]}'
    )
    plan = ProcessingRecoveryPlan(
        scope=ProductScope(
            tenant_id="1",
            space_id="space",
            raw_knowledge_base_id="raw",
            wiki_knowledge_base_id="wiki",
        ),
        origin_run_id="old",
        origin_version=1,
        upload_run_id="upload",
        materials=(
            OriginalKnowledgeRef(knowledge_id="k", original_filename="file.pdf", upload_ordinal=0),
        ),
    )
    assert plan.encoded() == raw
    assert (
        ProcessingRecoveryPlan.model_validate_json(raw).digest() == hashlib.sha256(raw).hexdigest()
    )


def test_title_recovery_rejects_existing_semantic_call(stage_runtime, monkeypatch):
    from insurance_harness.product_ingestion.artifact_tables import ProductStageModelCall

    scope, store, _, _, _ = stage_runtime
    origin = title_unavailable(stage_runtime, monkeypatch)
    with store._session_factory() as session, session.begin():
        session.add(
            ProductStageModelCall(
                id=str(uuid4()),
                call_id="already-reserved",
                run_id=origin.run_id,
                space_id=scope.space_id,
                stage_key="routing",
                operation_key="route",
                job_id="fixture-job",
                generation=1,
                attempt=1,
                dependency_sha256="0" * 64,
                input_sha256="0" * 64,
                model_policy_sha256="0" * 64,
                prompt_policy_sha256="0" * 64,
                state="RESERVED",
                raw_ref="fixture",
                usage={},
                reserved_at=datetime.now(UTC),
            )
        )
    assert not store.can_retry_processing(scope=scope, run_id=origin.run_id)


def test_title_recovery_snapshot_mutation_after_admission_is_rejected(stage_runtime, monkeypatch):
    from insurance_harness.product_ingestion.artifact_tables import ProductArtifact

    scope, store, _, platform, execute = stage_runtime
    origin = title_unavailable(stage_runtime, monkeypatch)
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    with store._session_factory() as session, session.begin():
        saved = session.scalar(
            select(ProductArtifact).where(
                ProductArtifact.run_id == origin.run_id,
                ProductArtifact.artifact_kind == "source_snapshot",
            )
        )
        saved.payload += b" "
        saved.payload_sha256 = hashlib.sha256(saved.payload).hexdigest()
    assert execute(child).state is JobState.SUCCEEDED
    assert execute(child).state is JobState.DEAD_LETTER
    assert platform.calls == 3


def test_processing_recovery_atomic_idempotent_and_real_source_worker(stage_runtime):
    scope, store, artifacts, platform, execute = stage_runtime
    origin = failed_capture(stage_runtime)
    assert origin.terminal_reason == "PRODUCT_STAGE_FAILED:source"
    assert store.can_retry_processing(scope=scope, run_id=origin.run_id)
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    again = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    assert child.run_id == again.run_id and child.retry_of_run_id == origin.run_id
    assert child.materials and [m.knowledge_id for m in child.materials] == [
        m.knowledge_id for m in origin.materials
    ]
    plan = artifacts.get_artifact(
        scope=scope,
        run_id=child.run_id,
        artifact_kind="processing_recovery_plan",
        artifact_key="product",
    )
    assert json.loads(plan.payload)["contract"] == "product-processing-recovery-plan.830.v1"
    with store._session_factory() as session:
        jobs = session.scalars(
            select(WikiJob).where(WikiJob.payload["run_id"].as_string() == child.run_id)
        ).all()
        assert len(jobs) == 1 and jobs[0].state == "queued"
    # Reconstructing the worker for each stage simulates process restart.
    for _ in range(3):
        assert execute(child).state is JobState.SUCCEEDED
    summary = json.loads(
        artifacts.get_artifact(
            scope=scope,
            run_id=child.run_id,
            artifact_kind="source_processing_summary",
            artifact_key="product",
        ).payload
    )
    assert all(row["reused"] for row in summary["materials"])
    assert summary["recorded_model_call_count"] == 0
    assert store.get_run(scope=scope, run_id=origin.run_id) == origin
    assert platform.calls == 3  # snapshot-only port; no parse/model port exists.
    with pytest.raises(ValueError):
        store.retry_processing(
            scope=scope, run_id=origin.run_id, expected_version=origin.version + 1
        )


def test_recovery_rechecks_completed_before_any_capture(stage_runtime):
    scope, store, _, platform, execute = stage_runtime
    origin = failed_capture(stage_runtime)
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    platform.failed = True
    assert execute(child).state is JobState.SUCCEEDED
    assert execute(child).state is JobState.DEAD_LETTER
    assert platform.calls == 0


def test_processing_retry_api_strict_request_and_capability(environment):
    client, *_ = environment
    run = client.post(
        PATH, headers=auth(), json={"idempotency_key": "running", "expected_upload_count": 3}
    ).json()["data"]
    assert run["can_retry_processing"] is False
    path = PATH + "/" + run["run_id"] + "/retry-processing"
    for value in (
        {},
        {"expected_version": 0},
        {"expected_version": True},
        {"expected_version": "1"},
        {"expected_version": 1, "field_keys": []},
    ):
        assert client.post(path, headers=auth(), json=value).status_code == 422
    assert (
        client.post(path, headers=auth(), json={"expected_version": run["version"]}).status_code
        == 409
    )
    assert (
        client.post(path, headers=auth("fixture-reader"), json={"expected_version": 1}).status_code
        == 403
    )


@pytest.mark.parametrize(
    "reason",
    [
        "SOURCE_PARSE_FAILED:费率.pdf",
        "SOURCE_PARSE_DEADLINE_EXCEEDED",
        "needs_confirmation:IDENTITY_CONFLICT",
    ],
)
def test_parser_failures_cannot_masquerade_as_snapshot_recovery(stage_runtime, reason):
    scope, store, _, _, _ = stage_runtime
    origin = failed_capture(stage_runtime)
    with store._session_factory() as session, session.begin():
        source = session.scalar(
            select(tables.ProductStage).where(
                tables.ProductStage.run_id == origin.run_id,
                tables.ProductStage.stage_key == "source",
            )
        )
        session.get(WikiJob, source.job_id).error_summary = reason
    assert not store.can_retry_processing(scope=scope, run_id=origin.run_id)
    with pytest.raises(ValueError):
        store.retry_processing(scope=scope, run_id=origin.run_id, expected_version=origin.version)


def test_processing_retry_scope_and_atomic_crash_replay(stage_runtime, monkeypatch):
    from insurance_harness.jobs import SpaceScopeError

    scope, store, _, _, _ = stage_runtime
    origin = failed_capture(stage_runtime)
    with pytest.raises(SpaceScopeError):
        store.retry_processing(
            scope=scope.model_copy(update={"tenant_id": "other"}),
            run_id=origin.run_id,
            expected_version=origin.version,
        )
    enqueue = store._jobs.enqueue

    def lost_response(**kwargs):
        enqueue(**kwargs)
        raise RuntimeError("API response lost after atomic commit")

    monkeypatch.setattr(store._jobs, "enqueue", lost_response)
    with pytest.raises(RuntimeError):
        store.retry_processing(scope=scope, run_id=origin.run_id, expected_version=origin.version)
    monkeypatch.setattr(store._jobs, "enqueue", enqueue)
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    assert store.processing_recovery_plan(scope=scope, run_id=child.run_id)
    with store._session_factory() as session:
        assert (
            len(
                session.scalars(
                    select(tables.ProductRun).where(
                        tables.ProductRun.retry_of_run_id == origin.run_id
                    )
                ).all()
            )
            == 1
        )


def test_recovery_http_positive_and_version_conflict(stage_runtime):
    from fastapi.testclient import TestClient

    from insurance_harness.service_shell.cli import build_api_app
    from insurance_harness.service_shell.config import ShellSettings
    from insurance_harness.service_shell.health import Lifecycle, ReadinessChecker
    from tests.product_ingestion.test_api import RECORDS

    scope, store, _, _, _ = stage_runtime
    origin = failed_capture(stage_runtime)
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
        assert before["can_retry_processing"] and before["state"] == "failed"
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


def test_recovery_plan_and_upload_binding_fail_closed(stage_runtime):
    from insurance_harness.product_ingestion.artifact_tables import ProductArtifact

    scope, store, _, platform, execute = stage_runtime
    origin = failed_capture(stage_runtime)
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    with store._session_factory() as session, session.begin():
        plan = session.scalar(select(ProductArtifact).where(ProductArtifact.run_id == child.run_id))
        plan.payload = b"{}"
    with pytest.raises(ValueError, match="recovery plan"):
        store.processing_recovery_plan(scope=scope, run_id=child.run_id)
    assert platform.calls == 0


def test_completed_sources_count_fourteen_historical_calls_not_new(
    stage_runtime, snapshot, monkeypatch
):
    from insurance_harness.product_ingestion import stages
    from tests.product_ingestion.test_processing_receipts import receipt, sealed

    scope, store, artifacts, platform, execute = stage_runtime
    origin = failed_capture(stage_runtime)
    capture = platform.capture_source
    sign = snapshot[2]

    async def with_history(scope, knowledge_id, attempt):
        envelope = json.loads(await capture(scope, knowledge_id, attempt))
        body = envelope["snapshot"]
        value = receipt()
        value.update(knowledge_id=knowledge_id, parse_attempt=attempt)
        count = (5, 5, 4)[int(knowledge_id[-1])]
        value["calls"] = [
            {
                "contract": "knowledge-model-dispatch-receipt.830.v1",
                "dispatch_id": f"call-{i}",
                "operation": "embedding",
                "purpose": "document_embedding",
                "model_id": "fixture",
                "model_name": "fixture",
                "request_sha256": hashlib.sha256(str(i).encode()).hexdigest(),
                "transport_retry_index": 0,
                "state": "RECORDED",
                "outcome": "HTTP_RESPONSE",
                "http_status": 200,
                "started_at_unix_ms": 1,
                "finished_at_unix_ms": 2,
                "duration_ms": 1,
            }
            for i in range(count)
        ]
        value["counts"].update(attempts=count, confirmed=count)
        body["processing_receipt"] = sealed(value)
        return sign(body)

    platform.capture_source = with_history
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    assert execute(child).state is JobState.SUCCEEDED
    assert execute(child).state is JobState.SUCCEEDED
    summary = json.loads(
        artifacts.get_artifact(
            scope=scope,
            run_id=child.run_id,
            artifact_kind="source_processing_summary",
            artifact_key="product",
        ).payload
    )
    assert summary["recorded_model_call_count"] == summary["model_call_count"] == 0
    assert summary["recorded_reused_model_call_count"] == summary["reused_model_call_count"] == 14

    def unavailable(*args, **kwargs):
        raise ValueError("FIRST_PAGE_PRODUCT_NAME_UNAVAILABLE")

    with monkeypatch.context() as patch:
        patch.setattr(stages, "prepare_identity_routing", unavailable)
        blocked = execute(child)
    assert blocked.state is JobState.BLOCKED
    with store._session_factory() as session, session.begin():
        session.get(tables.ProductRun, child.run_id).root_job_id = blocked.id
    origin = store.get_run(scope=scope, run_id=child.run_id)
    recovered = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    for _ in range(3):
        assert execute(recovered).state is JobState.SUCCEEDED
    summary = json.loads(
        artifacts.get_artifact(
            scope=scope,
            run_id=recovered.run_id,
            artifact_kind="source_processing_summary",
            artifact_key="product",
        ).payload
    )
    assert summary["model_call_count"] == summary["recorded_model_call_count"] == 0
    assert summary["reused_model_call_count"] == summary["recorded_reused_model_call_count"] == 14
    assert platform.calls == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_stage", ["source", "routing"])
async def test_recovery_runs_normal_identity_fields_discovery_and_publication(
    tmp_path, monkeypatch, failed_stage
):
    from insurance_harness.db.base import Base, make_session_factory
    from insurance_harness.jobs import JobStore
    from insurance_harness.product_ingestion import stages
    from insurance_harness.product_ingestion.progression import admit_uploads
    from tests.product_ingestion.test_pipeline_runtime import (
        SCOPE,
        FixtureModel,
        FixturePlatform,
        _base_snapshot,
        _compose,
        _finish,
        _settings,
        _sqlite_engine,
    )

    base, candidate = _base_snapshot()
    settings = _settings(tmp_path, candidate)
    engine = _sqlite_engine(tmp_path / "recovery-runtime.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    jobs = JobStore(factory, settings.job_runtime_config())
    platform, model = FixturePlatform(base), FixtureModel()
    runtime, context, model_client = await _compose(settings, factory, platform, model)
    origin = context.store.create_run(
        scope=SCOPE, idempotency_key="failed-source", expected_upload_count=3
    )

    async def unavailable(*_):
        raise NonRetryableJobError("snapshot HTTP 409")

    with monkeypatch.context() as patch:
        if failed_stage == "source":
            patch.setattr(context.bindings[SCOPE.space_id].platform, "capture_source", unavailable)
        else:

            def unavailable_title(*args, **kwargs):
                raise ValueError("FIRST_PAGE_PRODUCT_NAME_UNAVAILABLE")

            patch.setattr(stages, "prepare_identity_routing", unavailable_title)
        admit_uploads(context.store, SCOPE, origin.run_id)
        failed = await _finish(runtime, context, jobs, origin.run_id)
    assert failed.terminal_reason == (
        "PRODUCT_STAGE_FAILED:source"
        if failed_stage == "source"
        else "FIRST_PAGE_PRODUCT_NAME_UNAVAILABLE"
    )
    assert not model.identity_requests and not model.field_requests
    child = context.store.retry_processing(
        scope=SCOPE, run_id=origin.run_id, expected_version=failed.version
    )
    await runtime.close()
    await model_client.aclose()
    runtime, context, model_client = await _compose(settings, factory, platform, model)
    try:
        terminal = await _finish(runtime, context, jobs, child.run_id)
        assert terminal.state.value == "partial_success", (terminal.terminal_reason, runtime.issues)
        assert len(model.identity_requests) == 1 and model.field_requests
        assert platform.activations == 1 and platform.source_captures == 3
        summary = json.loads(
            context.artifacts.get_artifact(
                scope=SCOPE,
                run_id=child.run_id,
                artifact_kind="discovery_summary",
                artifact_key="product",
            ).payload
        )
        assert not summary["reused"] and summary["call_ids"]
        assert context.store.get_run(scope=SCOPE, run_id=origin.run_id) == failed
    finally:
        await runtime.close()
        await model_client.aclose()
        engine.dispose()
