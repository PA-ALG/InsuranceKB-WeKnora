from __future__ import annotations

# ruff: noqa: F811 -- imported pytest fixtures.
import asyncio
import hashlib
import json

import httpx
import pytest

from insurance_harness.jobs import ClaimedJob, ErrorClass, JobFailure, JobState
from insurance_harness.product_ingestion import tables
from insurance_harness.product_ingestion.artifact_models import ArtifactOrigin
from insurance_harness.product_ingestion.stages import artifact
from tests.product_ingestion.test_model_execution import PROMPT, configured, executor
from tests.product_ingestion.test_platform import snapshot  # noqa: F401
from tests.product_ingestion.test_routing import catalog  # noqa: F401
from tests.product_ingestion.test_stages import stage_runtime  # noqa: F401

CONTENT = json.dumps(
    {
        "materials": ["source-a"],
        "base_identity": {
            "release_id": "head9",
            "activation_epoch": 9,
            "snapshot_sha256": "b" * 64,
        },
    },
    sort_keys=True,
    separators=(",", ":"),
).encode()


def start_identity(store, scope, run):
    stage = store.enqueue_stage(
        scope=scope,
        run_id=run.run_id,
        stage_key="identity",
        dependency_sha256="a" * 64,
        idempotency_key="identity:" + run.run_id,
    )
    claim = store._jobs.claim(space_ids=(scope.space_id,), worker_id="identity")
    assert isinstance(claim, ClaimedJob) and claim.job.id == stage.job_id
    return store._jobs.start(
        space_id=scope.space_id, job_id=claim.job.id, generation=claim.job.lease_generation
    )


def call_args(artifacts, scope, run, job, content=CONTENT):
    return dict(
        store=artifacts,
        scope=scope,
        run_id=run.run_id,
        job=job,
        stage_key="identity",
        operation_key="current-product-identity",
        dependency_sha256="a" * 64,
        input_sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        prompt=PROMPT,
        template_id="classification-v1",
    )


@pytest.fixture
def recorded_origin(stage_runtime):
    scope, store, artifacts, platform, execute = stage_runtime
    run = store.create_run(scope=scope, idempotency_key="recorded-failure", expected_upload_count=3)
    for _ in range(3):
        assert execute(run).state is JobState.SUCCEEDED
    job = start_identity(store, scope, run)
    settings = configured(scope)
    sent = []

    def respond(request):
        sent.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
        )

    boundary = executor(lambda: settings, respond)
    original = asyncio.run(boundary.execute_stage_call(**call_args(artifacts, scope, run, job)))
    store._jobs.report_failure(
        space_id=scope.space_id,
        job_id=job.id,
        generation=job.lease_generation,
        failure=JobFailure(
            error_class=ErrorClass.CAPACITY_BLOCKED,
            summary="needs_confirmation:IDENTITY_RESPONSE_INVALID:ValueError",
        ),
    )
    with store._session_factory() as session, session.begin():
        session.get(tables.ProductRun, run.run_id).root_job_id = job.id
    origin = store.get_run(scope=scope, run_id=run.run_id)
    yield origin, original, boundary, settings, sent
    asyncio.run(boundary._client.aclose())


def test_recorded_identity_recovery_replays_original_receipts_and_provenance(
    stage_runtime, recorded_origin
):
    scope, store, artifacts, platform, execute = stage_runtime
    origin, original, boundary, _, sent = recorded_origin
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
    assert plan.mode == "REPLAY_RECORDED_IDENTITY"
    for _ in range(3):
        assert execute(child).state is JobState.SUCCEEDED
    job = start_identity(store, scope, child)
    replay = asyncio.run(boundary.replay_stage_call(**call_args(artifacts, scope, child, job)))
    assert replay == original and len(sent) == 1 and platform.calls == 3
    assert not artifacts.list_stage_calls(scope=scope, run_id=child.run_id)
    # Replay usage survives a downstream adapter failure before stage output.
    assert (
        artifacts.get_stage_call_metrics(scope=scope, run_id=child.run_id).reused_model_call_count
        == 1
    )
    draft = artifact(
        "identity",
        "product",
        b'{"fixture":true}',
        "a" * 64,
        origin=ArtifactOrigin.MODEL_REPLAY,
        call_id=replay.call_id,
    )
    writes = artifacts.prepare_artifact_writes(
        scope=scope,
        run_id=child.run_id,
        stage_key="identity",
        job_id=job.id,
        generation=job.lease_generation,
        drafts=(draft,),
    )
    store._jobs.report_success(
        space_id=scope.space_id,
        job_id=job.id,
        generation=job.lease_generation,
        domain_writes=writes,
    )
    metrics = artifacts.get_stage_call_metrics(scope=scope, run_id=child.run_id)
    assert metrics.model_call_count == 0 and metrics.reused_model_call_count == 1
    assert metrics.reused_usage == original.usage
    assert store.get_run(scope=scope, run_id=origin.run_id) == origin


@pytest.mark.parametrize(
    "change", ["input", "base", "prompt", "policy", "raw", "source", "scope", "lease"]
)
def test_recorded_identity_replay_drift_never_redispatches(stage_runtime, recorded_origin, change):
    from sqlalchemy import select

    from insurance_harness.jobs import SpaceScopeError, StaleGenerationError
    from insurance_harness.product_ingestion.artifact_tables import (
        ProductArtifact,
        ProductStageModelCall,
    )
    from insurance_harness.product_ingestion.model_execution import ModelPolicyDenied

    scope, store, artifacts, _, execute = stage_runtime
    origin, original, boundary, settings, sent = recorded_origin
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    for _ in range(3):
        assert execute(child).state is JobState.SUCCEEDED
    job = start_identity(store, scope, child)
    args = call_args(artifacts, scope, child, job)
    if change in {"input", "base"}:
        content = json.loads(CONTENT)
        if change == "input":
            content["materials"].append("changed")
        else:
            content["base_identity"]["activation_epoch"] += 1
        raw = json.dumps(content).encode()
        args.update(content=raw, input_sha256=hashlib.sha256(raw).hexdigest())
    elif change == "prompt":
        args["prompt"] += b" changed"
    elif change == "policy":
        boundary._settings_provider = lambda: settings.model_copy(
            update={"policy_version": "changed"}
        )
    elif change == "scope":
        args["scope"] = scope.model_copy(update={"tenant_id": "other"})
    elif change == "lease":
        from dataclasses import replace

        args["job"] = replace(job, lease_generation=job.lease_generation + 1)
    else:
        with store._session_factory() as session, session.begin():
            if change == "raw":
                call = session.scalar(
                    select(ProductStageModelCall).where(
                        ProductStageModelCall.call_id == original.call_id
                    )
                )
                call.raw += b" "
                call.raw_sha256 = hashlib.sha256(call.raw).hexdigest()
            else:
                row = session.scalar(
                    select(ProductArtifact).where(
                        ProductArtifact.run_id == child.run_id,
                        ProductArtifact.artifact_kind == "source_snapshot",
                    )
                )
                row.payload += b" "
                row.payload_sha256 = hashlib.sha256(row.payload).hexdigest()
    with pytest.raises((ValueError, ModelPolicyDenied, SpaceScopeError, StaleGenerationError)):
        asyncio.run(boundary.replay_stage_call(**args))
    assert len(sent) == 1
    assert not artifacts.list_stage_calls(scope=scope, run_id=child.run_id)
    assert not artifacts.list_artifacts(
        scope=scope, run_id=child.run_id, artifact_kind="model_replay_receipt"
    )


def test_recorded_replay_checkpoint_is_stable_and_same_run_model_origin_stays_strict(
    stage_runtime, recorded_origin
):
    scope, store, artifacts, _, execute = stage_runtime
    origin, original, boundary, _, sent = recorded_origin
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    for _ in range(3):
        assert execute(child).state is JobState.SUCCEEDED
    job = start_identity(store, scope, child)
    draft = artifact(
        "identity",
        "product",
        b"{}",
        "a" * 64,
        origin=ArtifactOrigin.MODEL_REPLAY,
        call_id=original.call_id,
    )
    args = dict(
        scope=scope,
        run_id=child.run_id,
        stage_key="identity",
        job_id=job.id,
        generation=job.lease_generation,
    )
    with pytest.raises(ValueError, match="checkpoint"):
        artifacts.prepare_artifact_writes(**args, drafts=(draft,))
    first = asyncio.run(boundary.replay_stage_call(**call_args(artifacts, scope, child, job)))
    saved = artifacts.list_artifacts(
        scope=scope, run_id=child.run_id, artifact_kind="model_replay_receipt"
    )
    assert (
        asyncio.run(boundary.replay_stage_call(**call_args(artifacts, scope, child, job))) == first
    )
    assert saved == artifacts.list_artifacts(
        scope=scope, run_id=child.run_id, artifact_kind="model_replay_receipt"
    )
    assert (
        saved[0].producer_job_id == job.id and saved[0].producer_generation == job.lease_generation
    )
    assert len(sent) == 1
    forged = draft.model_copy(update={"origin": ArtifactOrigin.MODEL})
    with pytest.raises(ValueError, match="same-run"):
        artifacts.prepare_artifact_writes(**args, drafts=(forged,))


@pytest.mark.asyncio
async def test_recorded_identity_recovery_real_worker_reaches_publication_without_classify_resend(
    tmp_path, monkeypatch
):
    from insurance_harness.db.base import Base, make_session_factory
    from insurance_harness.jobs import JobStore
    from insurance_harness.knowledge_compiler import g3_bounded_model_execution as semantic_adapter
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
    engine = _sqlite_engine(tmp_path / "recorded-recovery.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    jobs = JobStore(factory, settings.job_runtime_config())
    platform, model = FixturePlatform(base), FixtureModel()

    def projection_failure(**kwargs):
        raise ValueError("wrong-purpose identity evidence")

    with monkeypatch.context() as patch:
        patch.setattr(semantic_adapter, "assemble_c_semantic_response", projection_failure)
        runtime, context, model_client = await _compose(settings, factory, platform, model)
        origin = context.store.create_run(
            scope=SCOPE, idempotency_key="recorded-identity", expected_upload_count=3
        )
        admit_uploads(context.store, SCOPE, origin.run_id)
        failed = await _finish(runtime, context, jobs, origin.run_id)
    assert failed.terminal_reason == "IDENTITY_RESPONSE_INVALID:ValueError"
    assert len(model.identity_requests) == 1 and not model.field_requests
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
        assert platform.source_captures == 3 and platform.activations == 1
        metrics = context.artifacts.get_stage_call_metrics(scope=SCOPE, run_id=child.run_id)
        assert metrics.reused_model_call_count == 1
        assert context.store.get_run(scope=SCOPE, run_id=origin.run_id) == failed
    finally:
        await runtime.close()
        await model_client.aclose()
        engine.dispose()


@pytest.mark.parametrize(
    "change", ["diagnostic", "interrupted", "second_call", "reason", "source_missing"]
)
def test_recorded_identity_recovery_admission_is_narrow(stage_runtime, recorded_origin, change):
    from sqlalchemy import select

    from insurance_harness.jobs.tables import WikiJob
    from insurance_harness.product_ingestion.artifact_tables import (
        ProductArtifact,
        ProductStageModelCall,
    )

    scope, store, _, _, _ = stage_runtime
    origin, original, _, _, sent = recorded_origin
    with store._session_factory() as session, session.begin():
        call = session.scalar(
            select(ProductStageModelCall).where(ProductStageModelCall.call_id == original.call_id)
        )
        if change == "diagnostic":
            call.diagnostic = "provider_http_status"
        elif change == "interrupted":
            call.state = "interrupted"
        elif change == "second_call":
            values = {
                column.name: getattr(call, column.name)
                for column in ProductStageModelCall.__table__.columns
            }
            values.update(id="second-id", call_id="second-call", operation_key="different")
            session.add(ProductStageModelCall(**values))
        elif change == "reason":
            session.get(
                WikiJob, call.job_id
            ).error_summary = (
                "needs_confirmation:PRODUCT_IDENTITY_UNRESOLVED:IDENTITY_ANCHOR_CONFLICT"
            )
        else:
            source = session.scalar(
                select(ProductArtifact).where(
                    ProductArtifact.run_id == origin.run_id,
                    ProductArtifact.artifact_kind == "source_snapshot",
                )
            )
            session.delete(source)
    assert not store.can_retry_processing(scope=scope, run_id=origin.run_id)
    with pytest.raises(ValueError):
        store.retry_processing(scope=scope, run_id=origin.run_id, expected_version=origin.version)
    assert len(sent) == 1


def test_source_recovery_v2_wire_bytes_are_unchanged():
    from insurance_harness.product_ingestion.recovery import SealedSourceRecoveryPlan

    raw = (
        b'{"contract":"product-processing-recovery-plan.830.v2","mode":"REUSE_SEALED_SOURCES",'
        b'"scope":{"tenant_id":"1","space_id":"space","raw_knowledge_base_id":"raw",'
        b'"wiki_knowledge_base_id":"wiki"},"origin_run_id":"old","origin_version":1,'
        b'"upload_run_id":"upload","materials":[{"knowledge_id":"k",'
        b'"original_filename":"file.pdf","upload_ordinal":0}],"source_snapshots":['
        b'{"knowledge_id":"k","payload_sha256":"' + b"a" * 64 + b'"}]}'
    )
    plan = SealedSourceRecoveryPlan.model_validate_json(raw)
    assert plan.encoded() == raw and plan.digest() == hashlib.sha256(raw).hexdigest()
