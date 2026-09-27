from __future__ import annotations

import hashlib

# ruff: noqa: F811 -- imported pytest fixtures.
import json
import typing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from insurance_harness.jobs import JobSnapshot, JobState, NonRetryableJobError
from insurance_harness.jobs.tables import WikiJob
from insurance_harness.product_ingestion import tables
from insurance_harness.product_ingestion.composition import ProductCompositionContext
from tests.product_ingestion.test_api import PATH, auth, environment  # noqa: F401
from tests.product_ingestion.test_platform import snapshot  # noqa: F401
from tests.product_ingestion.test_routing import catalog  # noqa: F401
from tests.product_ingestion.test_stages import stage_runtime  # noqa: F401


@pytest.fixture
def legacy_stage_runtime(stage_runtime: typing.Any, monkeypatch: typing.Any) -> typing.Any:
    """Construct previously persisted v1/v2/v3 recovery records for read compatibility.

    Only this fixture selects the historical adapter; production API admission
    remains the checkpoint owner. Worker/custody validation is not mocked.
    """
    store = stage_runtime[1]
    monkeypatch.setattr(store, "can_retry_processing", store._legacy_can_retry_processing)
    monkeypatch.setattr(store, "retry_processing", store._legacy_retry_processing)
    return stage_runtime


def finish_failed_source(store: typing.Any, scope: typing.Any, run_id: str) -> None:
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


def failed_capture(stage_runtime: typing.Any) -> typing.Any:
    scope, store, artifacts, platform, execute = stage_runtime
    run = store.create_run(scope=scope, idempotency_key="capture-failed", expected_upload_count=3)
    assert execute(run).state is JobState.SUCCEEDED
    capture = platform.capture_source

    async def unavailable(*_: object) -> None:
        raise NonRetryableJobError("PLATFORM_REJECTED_HTTP_409")

    platform.capture_source = unavailable
    assert execute(run).state is JobState.DEAD_LETTER
    finish_failed_source(store, scope, run.run_id)
    platform.capture_source = capture
    return store.get_run(scope=scope, run_id=run.run_id)


def title_unavailable(
    stage_runtime: typing.Any,
    monkeypatch: typing.Any,
    reason: typing.Any = "FIRST_PAGE_PRODUCT_NAME_UNAVAILABLE",
) -> typing.Any:
    from insurance_harness.product_ingestion import stages

    scope, store, _, _, execute = stage_runtime
    run = store.create_run(
        scope=scope, idempotency_key="title-unavailable", expected_upload_count=3
    )
    assert execute(run).state is JobState.SUCCEEDED
    assert execute(run).state is JobState.SUCCEEDED

    def unavailable(*args: object, **kwargs: object) -> None:
        raise ValueError(reason)

    with monkeypatch.context() as patch:
        patch.setattr(stages, "prepare_identity_routing", unavailable)
        blocked = execute(run)
    assert blocked.state is JobState.BLOCKED
    # Fixture root points to the actual blocked terminal receipt.
    with store._session_factory() as session, session.begin():
        session.get(tables.ProductRun, run.run_id).root_job_id = blocked.id
    return store.get_run(scope=scope, run_id=run.run_id)


def test_legacy_title_recovery_reuses_exact_sources_and_keeps_original_terminal(
    legacy_stage_runtime: typing.Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage_runtime = legacy_stage_runtime
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
def test_legacy_v2_reason_policy_is_preserved_for_historical_records(
    legacy_stage_runtime: typing.Any, monkeypatch: pytest.MonkeyPatch, reason: typing.Any
) -> None:
    stage_runtime = legacy_stage_runtime
    scope, store, _, _, _ = stage_runtime
    origin = title_unavailable(stage_runtime, monkeypatch, reason)
    assert not store.can_retry_processing(scope=scope, run_id=origin.run_id)
    with pytest.raises(ValueError):
        store.retry_processing(scope=scope, run_id=origin.run_id, expected_version=origin.version)


@pytest.mark.parametrize("change", ["missing", "corrupt", "binding", "attempt"])
def test_legacy_title_recovery_source_changes_fail_closed(
    legacy_stage_runtime: typing.Any, monkeypatch: pytest.MonkeyPatch, change: typing.Any
) -> None:
    stage_runtime = legacy_stage_runtime
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
        # The display hint checks references only; the action validates payload bytes.
        assert store.can_retry_processing(scope=scope, run_id=origin.run_id) is (
            change == "corrupt"
        )
        with pytest.raises(ValueError):
            store.retry_processing(
                scope=scope, run_id=origin.run_id, expected_version=origin.version
            )
        return
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    lookup = platform.lookup_upload

    async def changed(scope: typing.Any, run_id: str, ordinal: int) -> typing.Any:
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


def test_recovery_v1_wire_bytes_are_unchanged() -> None:
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


def test_legacy_title_recovery_rejects_existing_semantic_call(
    legacy_stage_runtime: typing.Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage_runtime = legacy_stage_runtime
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


def test_legacy_title_recovery_snapshot_mutation_after_admission_is_rejected(
    legacy_stage_runtime: typing.Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage_runtime = legacy_stage_runtime
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


def test_legacy_processing_recovery_atomic_idempotent_and_real_source_worker(
    legacy_stage_runtime: typing.Any,
) -> None:
    stage_runtime = legacy_stage_runtime
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


def test_legacy_recovery_rechecks_completed_before_any_capture(
    legacy_stage_runtime: typing.Any,
) -> None:
    stage_runtime = legacy_stage_runtime
    scope, store, _, platform, execute = stage_runtime
    origin = failed_capture(stage_runtime)
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    platform.failed = True
    assert execute(child).state is JobState.SUCCEEDED
    assert execute(child).state is JobState.DEAD_LETTER
    assert platform.calls == 0


def test_processing_retry_api_strict_request_and_capability(environment: typing.Any) -> None:
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
        "NonRetryableJobError: ORIGINAL_UPLOAD_BINDING_CHANGED",
        "needs_confirmation:IDENTITY_CONFLICT",
    ],
)
def test_legacy_v1_reason_policy_is_preserved_for_historical_records(
    legacy_stage_runtime: typing.Any, reason: typing.Any
) -> None:
    stage_runtime = legacy_stage_runtime
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


def test_processing_retry_scope_and_atomic_crash_replay(
    stage_runtime: typing.Any, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    def lost_response(**kwargs: typing.Any) -> None:
        enqueue(**kwargs)
        raise RuntimeError("API response lost after atomic commit")

    monkeypatch.setattr(store._jobs, "enqueue", lost_response)
    with pytest.raises(RuntimeError):
        store.retry_processing(scope=scope, run_id=origin.run_id, expected_version=origin.version)
    monkeypatch.setattr(store._jobs, "enqueue", enqueue)
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    assert store.checkpoint_plan(scope=scope, run_id=child.run_id)
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


def test_recovery_http_positive_and_version_conflict(stage_runtime: typing.Any) -> None:
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
        postgres_dsn=SecretStr("postgresql://fixture@localhost/fixture"),
        principal_records_json=SecretStr(json.dumps(RECORDS)),
        principal_space_ids=(scope.space_id,),
        product_ingestion_enabled=True,
        product_ingestion_scopes_json=SecretStr(json.dumps([scope.model_dump()])),
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


def test_recovery_plan_and_upload_binding_fail_closed(stage_runtime: typing.Any) -> None:
    from insurance_harness.product_ingestion.artifact_tables import ProductArtifact

    scope, store, _, platform, execute = stage_runtime
    origin = failed_capture(stage_runtime)
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    with store._session_factory() as session, session.begin():
        plan = session.scalar(select(ProductArtifact).where(ProductArtifact.run_id == child.run_id))
        plan.payload = b"{}"
    with pytest.raises(ValueError, match="checkpoint"):
        store.checkpoint_plan(scope=scope, run_id=child.run_id)
    assert platform.calls == 0


def test_legacy_completed_sources_count_fourteen_historical_calls_not_new(
    legacy_stage_runtime: typing.Any, snapshot: typing.Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage_runtime = legacy_stage_runtime
    from insurance_harness.product_ingestion import stages
    from tests.product_ingestion.test_processing_receipts import receipt, sealed

    scope, store, artifacts, platform, execute = stage_runtime
    origin = failed_capture(stage_runtime)
    capture = platform.capture_source
    sign = snapshot[2]

    async def with_history(scope: typing.Any, knowledge_id: str, attempt: int) -> typing.Any:
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

    def unavailable(*args: object, **kwargs: object) -> None:
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_stage: typing.Any
) -> None:
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

    async def unavailable(*_: object) -> None:
        raise NonRetryableJobError("snapshot HTTP 409")

    with monkeypatch.context() as patch:
        if failed_stage == "source":
            patch.setattr(context.bindings[SCOPE.space_id].platform, "capture_source", unavailable)
        else:

            def unavailable_title(*args: object, **kwargs: object) -> None:
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


def failed_parse_source(stage_runtime: typing.Any, reason: typing.Any) -> typing.Any:
    """Real worker failure before source capture; no reparse or model fixture port."""
    scope, store, _, platform, execute = stage_runtime
    run = store.create_run(
        scope=scope, idempotency_key="parse-failure:" + reason, expected_upload_count=3
    )
    assert execute(run).state is JobState.SUCCEEDED
    if reason == "failed":
        platform.failed = True
        terminal = execute(run)
        platform.failed = False
        expected = "SOURCE_PARSE_FAILED"
    else:
        terminal = execute(run, now=lambda: run.source_deadline_at + timedelta(seconds=1))
        expected = "SOURCE_PARSE_DEADLINE_EXCEEDED"
    assert terminal.state is JobState.DEAD_LETTER and expected in terminal.error_summary
    assert platform.calls == 0
    finish_failed_source(store, scope, run.run_id)
    return store.get_run(scope=scope, run_id=run.run_id)


@pytest.mark.parametrize("reason", ["failed", "deadline"])
def test_legacy_explicit_source_revalidation_recovers_completed_parse(
    legacy_stage_runtime: typing.Any, reason: typing.Any
) -> None:
    stage_runtime = legacy_stage_runtime
    from insurance_harness.jobs import SpaceScopeError

    scope, store, artifacts, platform, execute = stage_runtime
    origin = failed_parse_source(stage_runtime, reason)
    assert origin.terminal_reason == "PRODUCT_STAGE_FAILED:source"
    assert store.can_retry_processing(scope=scope, run_id=origin.run_id)
    with pytest.raises(ValueError):
        store.retry_processing(
            scope=scope, run_id=origin.run_id, expected_version=origin.version + 1
        )
    with pytest.raises(SpaceScopeError):
        store.retry_processing(
            scope=scope.model_copy(update={"tenant_id": "foreign"}),
            run_id=origin.run_id,
            expected_version=origin.version,
        )
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    assert child.run_id != origin.run_id and child.retry_of_run_id == origin.run_id
    assert child.source_deadline_at > child.started_at
    assert (
        child.run_id
        == store.retry_processing(
            scope=scope, run_id=origin.run_id, expected_version=origin.version
        ).run_id
    )
    assert platform.calls == 0  # Admission itself never reparses or captures.
    for _ in range(3):
        assert execute(child).state is JobState.SUCCEEDED
    assert platform.calls == 3  # Only capture each already completed source once.
    assert not artifacts.list_stage_calls(scope=scope, run_id=child.run_id)
    assert store.get_run(scope=scope, run_id=origin.run_id) == origin


@pytest.mark.parametrize("current_state", ["failed", "processing", "binding_changed"])
def test_legacy_explicit_source_revalidation_does_not_reparse_unready_sources(
    legacy_stage_runtime: typing.Any, current_state: typing.Any
) -> None:
    stage_runtime = legacy_stage_runtime
    scope, store, artifacts, platform, execute = stage_runtime
    origin = failed_parse_source(stage_runtime, "failed")
    assert store.can_retry_processing(scope=scope, run_id=origin.run_id)
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    lookup = platform.lookup_upload

    async def current(scope: typing.Any, run_id: str, ordinal: int) -> typing.Any:
        value = await lookup(scope, run_id, ordinal)
        if current_state == "binding_changed":
            value["knowledge_id"] = "replacement-knowledge"
        else:
            value["parse_status"] = current_state
        return value

    platform.lookup_upload = current
    assert execute(child).state is JobState.SUCCEEDED
    failed = execute(child)
    assert failed.state is JobState.DEAD_LETTER
    expected = {
        "failed": "SOURCE_PARSE_FAILED",
        "processing": "RECOVERY_SOURCE_NOT_COMPLETED",
        "binding_changed": "ORIGINAL_UPLOAD_BINDING_CHANGED",
    }[current_state]
    assert expected in failed.error_summary
    assert platform.calls == 0
    assert not artifacts.list_stage_calls(scope=scope, run_id=child.run_id)
    assert not artifacts.list_artifacts(
        scope=scope, run_id=child.run_id, artifact_kind="source_snapshot"
    )
    assert store.get_run(scope=scope, run_id=origin.run_id) == origin


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["knowledge_binding", "parse_version"])
async def test_checkpoint_worker_revalidates_current_source_identity_and_version(
    stage_runtime: typing.Any,
    snapshot: typing.Any,
    catalog: typing.Any,
    monkeypatch: pytest.MonkeyPatch,
    change: typing.Any,
) -> None:
    """Reject actual platform metadata drift, independent of terminal error wording."""
    from types import SimpleNamespace

    from insurance_harness.jobs import CapacityBlockedJobError
    from insurance_harness.product_ingestion.pipeline import IDENTITY_PROMPT, build_product_pipeline
    from tests.test_batch_entity_resolution_830_g3 import _policy

    scope, store, artifacts, platform, _ = stage_runtime
    # The phase fixture uses synchronous worker steps, run off this async test's loop.
    import asyncio

    origin = await asyncio.to_thread(title_unavailable, stage_runtime, monkeypatch)
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    stage = store.list_stages(scope=scope, run_id=child.run_id)[0]
    configuration = SimpleNamespace(
        source_public_keys=snapshot[3],
        model=SimpleNamespace(
            templates=[
                SimpleNamespace(
                    role="classify",
                    purpose="g3-batch-resolution",
                    template_id="fixture-identity",
                    prompt_sha256=hashlib.sha256(IDENTITY_PROMPT).hexdigest(),
                )
            ]
        ),
    )
    context = SimpleNamespace(
        store=store,
        artifacts=artifacts,
        catalog=catalog,
        resolution_policy_json=_policy().model_dump_json().encode(),
        bindings={
            scope.space_id: SimpleNamespace(
                scope=scope,
                platform=platform,
                configuration=configuration,
            )
        },
    )
    handler = build_product_pipeline(
        typing.cast(ProductCompositionContext, context)
    ).stage_handlers["checkpoint"]
    lookup = platform.lookup_upload

    async def changed(current_scope: typing.Any, run_id: str, ordinal: int) -> typing.Any:
        value = await lookup(current_scope, run_id, ordinal)
        if change == "knowledge_binding":
            value["knowledge_id"] = "replacement-knowledge"
        else:
            value["parse_attempt"] += 1
        return value

    platform.lookup_upload = changed
    from insurance_harness.jobs import NonRetryableJobError

    expected_error, expected_reason = (
        (NonRetryableJobError, "ORIGINAL_UPLOAD_BINDING_CHANGED")
        if change == "knowledge_binding"
        else (CapacityBlockedJobError, "CHECKPOINT_SOURCE_SNAPSHOT_INVALID")
    )
    with pytest.raises(expected_error, match=expected_reason):
        await handler(scope, child, stage, typing.cast(JobSnapshot, SimpleNamespace()))
    assert platform.calls == 3
    assert not artifacts.list_stage_calls(scope=scope, run_id=child.run_id)
    assert store.checkpoint_receipt(scope=scope, run_id=child.run_id) is None
    assert store.get_run(scope=scope, run_id=origin.run_id) == origin
