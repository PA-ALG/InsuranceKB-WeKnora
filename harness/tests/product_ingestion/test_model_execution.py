from __future__ import annotations

import hashlib
import json
import typing
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import HttpUrl, SecretStr, ValidationError

from insurance_harness.db.base import Base, make_engine, make_session_factory
from insurance_harness.jobs import ClaimedJob, ErrorClass, JobFailure, JobRuntimeConfig, JobStore
from insurance_harness.product_ingestion import artifact_tables, tables  # noqa: F401
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.model_execution import ConfiguredModelExecutor
from insurance_harness.product_ingestion.model_settings import (
    ModelTemplatePolicy,
    ProductModelSettings,
)
from insurance_harness.product_ingestion.models import ProductScope
from insurance_harness.product_ingestion.store import ProductIngestionStore

PROMPT = b"Return the approved classification JSON only."
CONTENT = b'{"materials":["source-a"]}'


def configured(
    scope: ProductScope,
    *,
    key: str = "secret-a",
    expires_at: datetime | None = None,
    max_context_bytes: int = 4096,
) -> ProductModelSettings:
    return ProductModelSettings(
        scope=scope,
        endpoint=HttpUrl("https://gateway.invalid/v1/chat/completions"),
        api_key=SecretStr(key),
        model="gemini-3.7-flash-medium",
        policy_version="g3-user-gemini-gateway-v1",
        expires_at=expires_at or datetime.now(UTC) + timedelta(hours=1),
        templates=(
            ModelTemplatePolicy(
                template_id="classification-v1",
                role="classify",
                purpose="g3-batch-resolution",
                run_schema_version="830-g3-v1",
                prompt_sha256=hashlib.sha256(PROMPT).hexdigest(),
                max_context_bytes=max_context_bytes,
                max_output_tokens=512,
            ),
            ModelTemplatePolicy(
                template_id="field-window-v1",
                role="extract",
                purpose="g3-field-extraction",
                run_schema_version="830-g3-v1",
                prompt_sha256=hashlib.sha256(b"field prompt").hexdigest(),
                max_context_bytes=4096,
                max_output_tokens=1024,
            ),
        ),
        field_template_id="field-window-v1",
        max_request_bytes=16_384,
        max_response_bytes=16_384,
        timeout_seconds=5,
    )


@pytest.fixture
def runtime(tmp_path: Path) -> Iterator[tuple[typing.Any, ...]]:
    engine = make_engine(f"sqlite:///{tmp_path}/model.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    job_config = JobRuntimeConfig(
        lease_seconds=300,
        heartbeat_interval_seconds=30,
        max_attempts=3,
        backoff_seconds=(0,),
        per_space_concurrency_limit=8,
        global_concurrency_limit=16,
    )
    jobs = JobStore(factory, job_config)
    products = ProductIngestionStore(factory, jobs)
    artifacts = ProductArtifactStore(factory, products)
    scope = ProductScope(
        tenant_id="tenant-a",
        space_id="space-a",
        raw_knowledge_base_id="raw-a",
        wiki_knowledge_base_id="wiki-a",
    )
    run = products.create_run(scope=scope, idempotency_key="model-run")
    stage = products.enqueue_stage(
        scope=scope,
        run_id=run.run_id,
        stage_key="identity",
        dependency_sha256="a" * 64,
        idempotency_key="identity",
    )
    claim = jobs.claim(space_ids=(scope.space_id,), worker_id="model")
    assert isinstance(claim, ClaimedJob)
    job = jobs.start(
        space_id=scope.space_id,
        job_id=stage.job_id,
        generation=claim.job.lease_generation,
    )
    yield products, artifacts, jobs, scope, run, job
    engine.dispose()


def executor(settings_provider: typing.Any, handler: typing.Any) -> ConfiguredModelExecutor:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    return ConfiguredModelExecutor(settings_provider=settings_provider, client=client)


@pytest.mark.asyncio
async def test_stage_call_persists_exact_request_receipts_usage_and_replays(
    runtime: typing.Any,
) -> None:
    _products, artifacts, jobs, scope, run, job = runtime
    settings = configured(scope)
    sent = []

    def handler(request: typing.Any) -> typing.Any:
        sent.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"proposals":[]}'}}],
                "usage": {"prompt_tokens": 17, "completion_tokens": 3},
            },
        )

    boundary = executor(lambda: settings, handler)
    kwargs = dict(
        store=artifacts,
        scope=scope,
        run_id=run.run_id,
        job=job,
        stage_key="identity",
        operation_key="classification",
        dependency_sha256="a" * 64,
        input_sha256=hashlib.sha256(CONTENT).hexdigest(),
        content=CONTENT,
        prompt=PROMPT,
        template_id="classification-v1",
    )
    first = await boundary.execute_stage_call(call_id="call-first", **kwargs)
    jobs.report_failure(
        space_id=scope.space_id,
        job_id=job.id,
        generation=job.lease_generation,
        failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="restart_after_record"),
    )
    reclaimed = jobs.claim(space_ids=(scope.space_id,), worker_id="model-restart")
    assert isinstance(reclaimed, ClaimedJob)
    restarted = jobs.start(
        space_id=scope.space_id,
        job_id=job.id,
        generation=reclaimed.job.lease_generation,
    )
    replay = await boundary.execute_stage_call(
        call_id="fresh-after-restart", **{**kwargs, "job": restarted}
    )

    assert len(sent) == 1
    assert json.loads(sent[0].content)["max_tokens"] == 512
    persisted = artifacts.get_stage_call(scope=scope, call_id="call-first")
    assert persisted.request_bytes == sent[0].content
    assert persisted.request_sha256 == hashlib.sha256(sent[0].content).hexdigest()
    assert persisted.raw == first.raw
    assert persisted.usage == {"prompt_tokens": 17, "completion_tokens": 3}
    assert first.state == "recorded" and first.diagnostic is None
    assert first.policy_receipt is not None
    assert first.policy_receipt.decision == "ALLOW"
    assert first.policy_receipt.purpose == "g3-batch-resolution"
    assert first.policy_receipt.run_schema_version == "830-g3-v1"
    assert first.policy_receipt_raw is not None
    assert first.policy_receipt_raw_sha256 == hashlib.sha256(first.policy_receipt_raw).hexdigest()
    assert first.execution_receipt.raw_sha256 == persisted.raw_sha256
    assert replay.execution_receipt_sha256 == first.execution_receipt_sha256
    assert replay.call_id == "call-first"


@pytest.mark.asyncio
async def test_denial_capacity_drift_and_interrupted_calls_never_dispatch(
    runtime: typing.Any,
) -> None:
    _products, artifacts, _jobs, scope, run, job = runtime
    settings = configured(scope, max_context_bytes=len(CONTENT))
    current = [settings]
    calls = []

    def handler(request: typing.Any) -> typing.Any:
        calls.append(request)
        return httpx.Response(200, json={"choices": []})

    boundary = executor(lambda: current[0], handler)
    common = dict(
        store=artifacts,
        scope=scope,
        run_id=run.run_id,
        job=job,
        stage_key="identity",
        operation_key="classification",
        dependency_sha256="a" * 64,
        prompt=PROMPT,
        template_id="classification-v1",
    )
    from insurance_harness.product_ingestion.model_execution import ModelPolicyDenied

    with pytest.raises(ModelPolicyDenied, match="scope"):
        await boundary.execute_stage_call(
            call_id="wrong-scope",
            input_sha256=hashlib.sha256(CONTENT).hexdigest(),
            content=CONTENT,
            **{**common, "scope": scope.model_copy(update={"raw_knowledge_base_id": "other"})},
        )
    with pytest.raises(ModelPolicyDenied, match="capacity"):
        await boundary.execute_stage_call(
            call_id="too-large",
            input_sha256=hashlib.sha256(CONTENT + b"x").hexdigest(),
            content=CONTENT + b"x",
            **common,
        )
    expired = configured(scope, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    with pytest.raises(ModelPolicyDenied, match="expired"):
        await executor(lambda: expired, handler).execute_stage_call(
            call_id="expired",
            input_sha256=hashlib.sha256(CONTENT).hexdigest(),
            content=CONTENT,
            **{**common, "operation_key": "expired"},
        )
    assert calls == []

    # The first settings read permits reservation; the pre-send read observes drift.
    drifted = configured(scope).model_copy(update={"endpoint": "https://other.invalid/v1/chat"})
    reads = 0

    def drifting() -> typing.Any:
        nonlocal reads
        reads += 1
        return settings if reads == 1 else drifted

    drift_boundary = executor(drifting, handler)
    result = await drift_boundary.execute_stage_call(
        call_id="drift",
        input_sha256=hashlib.sha256(CONTENT).hexdigest(),
        content=CONTENT,
        **{**common, "operation_key": "drift"},
    )
    assert result.state == "recorded"
    assert result.raw is None and result.diagnostic == "policy_changed_before_dispatch"
    assert calls == []

    request = b'{"model":"gemini-3.7-flash-medium"}'
    reserved = artifacts.reserve_stage_call(
        scope=scope,
        run_id=run.run_id,
        stage_key="identity",
        operation_key="interrupted",
        dependency_sha256="a" * 64,
        job_id=job.id,
        generation=job.lease_generation,
        attempt=job.attempt,
        call_id="interrupted-original",
        input_sha256=hashlib.sha256(CONTENT).hexdigest(),
        model_policy_sha256=settings.policy_sha256,
        prompt_policy_sha256=hashlib.sha256(PROMPT).hexdigest(),
    )
    artifacts.begin_stage_call(
        scope=scope,
        call_id=reserved.call.call_id,
        job_id=job.id,
        generation=job.lease_generation,
        request_sha256=hashlib.sha256(request).hexdigest(),
        request_bytes=request,
    )
    interrupted = await boundary.execute_stage_call(
        call_id="fresh-interrupted",
        operation_key="interrupted",
        input_sha256=hashlib.sha256(CONTENT).hexdigest(),
        content=CONTENT,
        **{key: value for key, value in common.items() if key != "operation_key"},
    )
    assert interrupted.state == "interrupted"
    assert interrupted.call_id == "interrupted-original"
    assert calls == []


def test_policy_hash_excludes_key_and_settings_reject_bad_limits(runtime: typing.Any) -> None:
    _products, _artifacts, _jobs, scope, _run, _job = runtime
    expiry = datetime.now(UTC) + timedelta(hours=1)
    assert (
        configured(scope, key="one", expires_at=expiry).policy_sha256
        == configured(scope, key="two", expires_at=expiry).policy_sha256
    )
    from insurance_harness.product_ingestion.model_settings import ProductModelSettings

    values = configured(scope).model_dump(mode="python")
    values["max_response_bytes"] = 0
    with pytest.raises(ValidationError):
        ProductModelSettings.model_validate(values)
