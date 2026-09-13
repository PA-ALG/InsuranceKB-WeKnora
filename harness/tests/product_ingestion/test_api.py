from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from insurance_harness.db.base import Base
from insurance_harness.jobs.tables import WikiJob
from insurance_harness.product_ingestion import tables as product_tables  # noqa: F401
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.service_shell.cli import build_api_app
from insurance_harness.service_shell.config import ShellSettings
from insurance_harness.service_shell.health import Lifecycle, ReadinessChecker

PATH = "/product-ingestion/v1/spaces/space/runs"
SCOPE = {
    "tenant_id": "10003",
    "space_id": "space",
    "raw_knowledge_base_id": "raw",
    "wiki_knowledge_base_id": "wiki",
}
RECORDS = {
    "fixture-platform": {
        "kind": "service",
        "service": "product_ingestion",
        "space_ids": ["space"],
        "capabilities": ["manage_product_ingestion", "read_product_ingestion"],
    },
    "fixture-reader": {
        "kind": "service",
        "service": "product_ingestion",
        "space_ids": ["space"],
        "capabilities": ["read_product_ingestion"],
    },
}


@pytest.fixture
def environment(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path}/api.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    lifecycle = Lifecycle()
    lifecycle.mark_serving()
    readiness = ReadinessChecker(
        lifecycle=lifecycle, probe=lambda: None, timeout_seconds=0.1, freshness_seconds=1
    )
    settings = ShellSettings(
        postgres_dsn="postgresql://fixture@localhost/fixture",
        principal_records_json=json.dumps(RECORDS),
        principal_space_ids=("space",),
        product_ingestion_enabled=True,
        product_ingestion_scopes_json=json.dumps([SCOPE]),
    )
    app = build_api_app(
        settings=settings, lifecycle=lifecycle, readiness=readiness, session_factory=factory
    )
    with TestClient(app) as client:
        yield client, factory, settings, lifecycle, readiness
    engine.dispose()


def auth(token="fixture-platform"):
    return {"Authorization": "Bearer " + token}


def test_real_api_composition_admits_durable_job_without_inline_processing(environment):
    client, factory, *_ = environment
    payload = {"idempotency_key": "browser-batch", "expected_upload_count": 3}
    response = client.post(PATH, headers=auth(), json=payload)
    assert response.status_code == 201, response.text
    run = response.json()["data"]
    assert run["state"] == "accepting_uploads"
    assert run["expected_upload_count"] == 3
    assert run["model_call_count"] == 0
    assert run["counts"] == {"success_count": 0, "missing_count": 0, "failure_count": 0}
    assert run["wiki_knowledge_base_id"] == "wiki"
    with factory() as session:
        jobs = list(session.scalars(select(WikiJob)))
        assert len(jobs) == 1
        assert jobs[0].state == "queued"
        assert jobs[0].job_type == "product_stage_uploads"
    again = client.post(PATH, headers=auth(), json=payload)
    assert again.json()["data"]["run_id"] == run["run_id"]
    assert (
        client.get(PATH + "/" + run["run_id"], headers=auth()).json()["data"]["run_id"]
        == run["run_id"]
    )


def test_api_authentication_scope_and_read_only_capability(environment):
    client, *_ = environment
    payload = {"idempotency_key": "browser-batch", "expected_upload_count": 3}
    assert client.post(PATH, json=payload).status_code == 401
    assert client.post(PATH, headers=auth("fixture-reader"), json=payload).status_code == 403
    assert client.get(PATH.replace("/space/", "/other/"), headers=auth()).status_code == 403
    assert client.get(PATH, headers=auth("fixture-reader")).status_code == 200


def test_user_cannot_inject_candidate_or_unverified_fields(environment):
    client, factory, *_ = environment
    response = client.post(
        PATH,
        headers=auth(),
        json={
            "idempotency_key": "bad-batch",
            "expected_upload_count": 3,
            "candidate": {"fields": [{"value": "unverified"}]},
        },
    )
    assert response.status_code == 422
    with factory() as session:
        assert list(session.scalars(select(WikiJob))) == []


def test_run_is_visible_after_api_process_recomposition(environment):
    client, factory, settings, lifecycle, readiness = environment
    first = client.post(
        PATH,
        headers=auth(),
        json={
            "idempotency_key": "restart-batch",
            "expected_upload_count": 3,
        },
    )
    assert first.status_code == 201
    second_app = build_api_app(
        settings=settings, lifecycle=lifecycle, readiness=readiness, session_factory=factory
    )
    with TestClient(second_app) as second_client:
        listing = second_client.get(PATH, headers=auth()).json()["data"]["runs"]
    assert listing[0]["run_id"] == first.json()["data"]["run_id"]


def test_failed_field_retry_creates_a_linked_run_and_preserves_original(environment):
    import hashlib
    from types import SimpleNamespace

    from insurance_harness.jobs import ClaimedJob, JobStore
    from insurance_harness.product_ingestion import models
    from insurance_harness.product_ingestion.store import ProductIngestionStore
    from tests.product_ingestion.test_store import _task

    client, factory, *_ = environment
    scope = models.ProductScope.model_validate(SCOPE)
    jobs = JobStore(
        factory,
        ShellSettings(postgres_dsn="postgresql://fixture@localhost/fixture").job_runtime_config(),
    )
    store = ProductIngestionStore(factory, jobs)
    run = store.create_run(scope=scope, idempotency_key="failed-field-run")
    task = _task(SimpleNamespace(**vars(models)), "alpha")
    window = store.enqueue_window(
        scope=scope,
        run_id=run.run_id,
        stage_key="extract",
        window_key="window",
        dependency_sha256="9" * 64,
        tasks=(task,),
    )
    claim = jobs.claim(space_ids=("space",), worker_id="fixture-worker")
    assert isinstance(claim, ClaimedJob)
    active = jobs.start(
        space_id="space", job_id=window.job_id, generation=claim.job.lease_generation
    )
    request = b'{"fixture":"request"}'
    request_sha = hashlib.sha256(request).hexdigest()
    reservation = store.reserve_window(
        scope=scope,
        run_id=run.run_id,
        job_id=active.id,
        generation=active.lease_generation,
        attempt=1,
        call_id="fixture-call",
        window_key="window",
        request_sha256=request_sha,
        tasks=(task,),
    )
    store.begin_call(
        scope=scope,
        call_id=reservation.call.call_id,
        job_id=active.id,
        generation=active.lease_generation,
        request_sha256=request_sha,
        request_bytes=request,
    )
    raw = store.record_call_result(
        scope=scope,
        call_id=reservation.call.call_id,
        job_id=active.id,
        generation=active.lease_generation,
        request_sha256=request_sha,
        raw=b"{bad format}",
        diagnostic=None,
    )
    settlement = store.settle_window(
        scope=scope,
        run_id=run.run_id,
        job_id=active.id,
        generation=active.lease_generation,
        outcomes=(
            models.FieldOutcomeWrite(
                entity_id=task.entity_id,
                field_key=task.field_key,
                task_sha256=task.task_sha256,
                cache_identity=task.cache_identity,
                outcome=models.FieldOutcomeKind.EXTRACTION_FAILED,
                reason="INVALID_RESPONSE_ENVELOPE",
                validated_result=None,
                raw_ref=raw.raw_ref,
            ),
        ),
    )
    assert len(store.list_field_attempts(scope=scope, run_id=run.run_id)) == 1, settlement
    response = client.post(
        PATH + "/" + run.run_id + "/retry-fields", headers=auth(), json={"field_keys": ["alpha"]}
    )
    assert response.status_code == 201, response.text
    retry = response.json()["data"]
    assert retry["retry_of_run_id"] == run.run_id
    assert retry["run_id"] != run.run_id
    assert store.get_run(scope=scope, run_id=run.run_id).failure_count == 1


def test_status_includes_non_field_model_calls_without_exposing_raw_response(environment):
    import hashlib

    from insurance_harness.jobs import JobStore
    from insurance_harness.product_ingestion.models import ProductScope
    from insurance_harness.product_ingestion.store import ProductIngestionStore

    client, factory, settings, *_ = environment
    scope = ProductScope.model_validate(SCOPE)
    jobs = JobStore(factory, settings.job_runtime_config())
    store = ProductIngestionStore(factory, jobs)
    artifacts = ProductArtifactStore(factory, store)
    run = store.create_run(scope=scope, idempotency_key="model-count")
    stage = store.enqueue_stage(
        scope=scope,
        run_id=run.run_id,
        stage_key="identity",
        dependency_sha256="a" * 64,
        idempotency_key="identity",
    )
    claim = jobs.claim(space_ids=("space",), worker_id="worker")
    job = jobs.start(space_id="space", job_id=stage.job_id, generation=claim.job.lease_generation)
    artifacts.reserve_stage_call(
        scope=scope,
        run_id=run.run_id,
        stage_key="identity",
        operation_key="identity",
        dependency_sha256="a" * 64,
        job_id=job.id,
        generation=job.lease_generation,
        attempt=job.attempt,
        call_id="fixture-identity",
        input_sha256="b" * 64,
        model_policy_sha256="c" * 64,
        prompt_policy_sha256="d" * 64,
    )
    request = b"fixture model request"
    artifacts.begin_stage_call(
        scope=scope,
        call_id="fixture-identity",
        job_id=job.id,
        generation=job.lease_generation,
        request_sha256=hashlib.sha256(request).hexdigest(),
        request_bytes=request,
    )
    assert (
        artifacts.get_stage_call_metrics(scope=scope, run_id=run.run_id).unsettled_call_count == 1
    )
    artifacts.record_stage_call_result(
        scope=scope,
        call_id="fixture-identity",
        job_id=job.id,
        generation=job.lease_generation,
        request_sha256=hashlib.sha256(request).hexdigest(),
        raw=b"private model response",
        diagnostic=None,
        usage={"input_tokens": 37},
    )
    assert (
        artifacts.get_stage_call_metrics(scope=scope, run_id=run.run_id).unsettled_call_count == 0
    )
    result = client.get(PATH + "/" + run.run_id, headers=auth())
    assert result.status_code == 200
    assert result.json()["data"]["model_call_count"] == 1
    assert result.json()["data"]["usage"]["input_tokens"] == 37
    assert "private model response" not in result.text


def test_extraction_status_tracks_windows_before_aggregate_exists(environment):
    from types import SimpleNamespace

    from insurance_harness.jobs import JobStore
    from insurance_harness.product_ingestion import models
    from insurance_harness.product_ingestion.store import ProductIngestionStore
    from tests.product_ingestion.test_store import _task

    client, factory, settings, *_ = environment
    scope = models.ProductScope.model_validate(SCOPE)
    jobs = JobStore(factory, settings.job_runtime_config())
    store = ProductIngestionStore(factory, jobs)
    run = store.create_run(scope=scope, idempotency_key="live-extract")
    task = _task(SimpleNamespace(**vars(models)), "alpha")
    window = store.enqueue_window(
        scope=scope,
        run_id=run.run_id,
        stage_key="extract",
        window_key="window",
        dependency_sha256="9" * 64,
        tasks=(task,),
    )
    claim = jobs.claim(space_ids=("space",), worker_id="fixture-worker")
    active = jobs.start(
        space_id="space",
        job_id=window.job_id,
        generation=claim.job.lease_generation,
    )
    result = client.get(PATH + "/" + run.run_id, headers=auth()).json()["data"]
    assert result["stage"] == "extract"
    stage = next(row for row in result["stages"] if row["name"] == "extract")
    assert stage["state"] == "running"
    assert stage["started_at"] == active.started_at.isoformat().replace("+00:00", "Z")
    assert stage["finished_at"] is None
    # Display projection must never create the aggregate job used by progression.
    assert store.list_stages(scope=scope, run_id=run.run_id) == ()


def test_complete_model_count_requires_terminal_run_and_retains_source_totals(environment):
    import hashlib

    from insurance_harness.jobs import JobStore
    from insurance_harness.product_ingestion.artifact_models import ArtifactDraft, ArtifactOrigin
    from insurance_harness.product_ingestion.models import ProductRunState, ProductScope
    from insurance_harness.product_ingestion.processing_receipts import processing_summary
    from insurance_harness.product_ingestion.store import ProductIngestionStore
    from tests.product_ingestion.test_processing_receipts import receipt

    client, factory, settings, *_ = environment
    scope = ProductScope.model_validate(SCOPE)
    jobs = JobStore(factory, settings.job_runtime_config())
    store = ProductIngestionStore(factory, jobs)
    artifacts = ProductArtifactStore(factory, store)
    run = store.create_run(scope=scope, idempotency_key="accounting-terminal")
    stage = store.enqueue_stage(
        scope=scope,
        run_id=run.run_id,
        stage_key="sources",
        dependency_sha256="a" * 64,
        idempotency_key="sources",
    )
    claim = jobs.claim(space_ids=("space",), worker_id="worker")
    job = jobs.start(space_id="space", job_id=stage.job_id, generation=claim.job.lease_generation)
    payload = json.dumps(processing_summary([("knowledge", receipt(), False)])).encode()
    writes = artifacts.prepare_artifact_writes(
        scope=scope,
        run_id=run.run_id,
        stage_key="sources",
        job_id=job.id,
        generation=job.lease_generation,
        drafts=(
            ArtifactDraft(
                artifact_kind="source_processing_summary",
                artifact_key="sources",
                contract_name="source-processing-summary",
                contract_version="v1",
                dependency_sha256="a" * 64,
                payload=payload,
                payload_sha256=hashlib.sha256(payload).hexdigest(),
                origin=ArtifactOrigin.PLATFORM_SOURCE,
            ),
        ),
    )
    jobs.report_success(
        space_id="space", job_id=job.id, generation=job.lease_generation, domain_writes=writes
    )
    current = client.get(PATH + "/" + run.run_id, headers=auth()).json()["data"]
    assert current["source_model_call_count"] == 0
    assert current["recorded_source_model_call_count"] == 0
    # No in-flight calls does not mean later stages have made all their calls.
    assert current["model_call_count_complete"] is False
    root = store.enqueue_root(scope=scope, run_id=run.run_id, idempotency_key="root")
    claim = jobs.claim(space_ids=("space",), worker_id="worker")
    active = jobs.start(space_id="space", job_id=root.job_id, generation=claim.job.lease_generation)
    store.finalize_run(
        scope=scope,
        run_id=run.run_id,
        job_id=active.id,
        generation=active.lease_generation,
        terminal_state=ProductRunState.SUCCEEDED,
    )
    final = client.get(PATH + "/" + run.run_id, headers=auth()).json()["data"]
    assert final["model_call_count_complete"] is True
    assert final["source_processing"]["materials"][0]["counts"]["attempts"] == 0
