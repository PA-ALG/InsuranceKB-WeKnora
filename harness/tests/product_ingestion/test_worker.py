from __future__ import annotations

# ruff: noqa: F811 -- pytest resolves the imported source fixture by argument name.
import asyncio
import hashlib
import importlib
import json
import typing
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from pydantic import HttpUrl, SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from insurance_harness.db.base import Base
from insurance_harness.jobs import ClaimedJob, JobStore
from insurance_harness.product_ingestion import models, tables  # noqa: F401
from insurance_harness.product_ingestion.store import ProductIngestionStore
from insurance_harness.service_shell.config import ShellSettings
from insurance_harness.service_shell.health import Lifecycle
from insurance_harness.service_shell.worker import HandlerRegistry, WorkerLoop
from tests.product_ingestion.test_extraction import response, row, source, tasks  # noqa: F401


def worker_module() -> typing.Any:
    try:
        return importlib.import_module("insurance_harness.product_ingestion.worker")
    except ModuleNotFoundError:
        pytest.fail("durable product extraction worker is not registered")


@pytest.fixture
def runtime(tmp_path: Path, source: typing.Any) -> Iterator[tuple[typing.Any, ...]]:
    engine = create_engine(
        f"sqlite:///{tmp_path}/worker.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = ShellSettings(
        postgres_dsn=SecretStr("postgresql://fixture@localhost/fixture"),
        worker_id="worker",
        worker_space_ids=("space-1",),
    )
    jobs = JobStore(factory, settings.job_runtime_config())
    store = ProductIngestionStore(factory, jobs)
    scope = models.ProductScope(
        tenant_id="1",
        space_id="space-1",
        raw_knowledge_base_id="raw-1",
        wiki_knowledge_base_id="wiki-1",
    )
    selected = tasks(source)
    specs = tuple(
        models.WindowTaskSpec(
            entity_id=task.entity_id,
            field_key=task.field_key,
            task_sha256=task.task_sha256,
            cache_identity=models.FieldCacheIdentity(
                product_identity_sha256="a" * 64,
                entity_id=task.entity_id,
                field_key=task.field_key,
                source_dependencies=(
                    models.SourceDependency(
                        source_revision_id=source.revision_id, source_sha256=source.source_hash
                    ),
                ),
                schema_adapter_id="fixture",
                schema_adapter_sha256="b" * 64,
                schema_version="1",
            ),
            validation_version="1",
            model_policy_sha256="c" * 64,
            prompt_policy_sha256="d" * 64,
            task_payload=task.model_dump(mode="json"),
        )
        for task in selected
    )
    yield store, jobs, scope, specs, selected, settings
    engine.dispose()


def test_real_worker_commits_mixed_window_and_reuses_success_after_recomposition(
    runtime: typing.Any, source: typing.Any
) -> None:
    store, jobs, scope, specs, selected, settings = runtime
    calls = []

    async def load_sources(_scope: object, _run_id: object) -> tuple[typing.Any, ...]:
        return (source,)

    async def transport(request: typing.Any) -> bytes:
        calls.append(request)
        payload = json.loads(request)
        semantic = response(
            [row(selected[0], payload), row(selected[1], payload, value=None, state="unknown")]
        )
        return json.dumps(
            {
                "choices": [{"message": {"content": semantic.decode()}}],
                "usage": {"prompt_tokens": 37, "completion_tokens": 12},
            }
        ).encode()

    def loop() -> WorkerLoop:
        registry = HandlerRegistry()
        worker_module().register_extraction_worker(
            registry,
            store=store,
            scopes={scope.space_id: scope},
            load_sources=load_sources,
            transport=transport,
            decode_response=lambda raw: json.loads(raw)["choices"][0]["message"][
                "content"
            ].encode(),
        )
        return WorkerLoop(
            store=jobs,
            registry=registry,
            settings=settings,
            lifecycle=Lifecycle(),
            worker_id="worker",
        )

    def execute_run(key: str) -> tuple[typing.Any, ...]:
        run = store.create_run(scope=scope, idempotency_key=key)
        store.enqueue_window(
            scope=scope,
            run_id=run.run_id,
            stage_key="extract",
            window_key="one",
            dependency_sha256="e" * 64,
            tasks=specs,
        )
        claimed = jobs.claim(space_ids=(scope.space_id,), worker_id="worker")
        assert isinstance(claimed, ClaimedJob)
        asyncio.run(loop().process_job(claimed.job))
        return run, store.list_field_attempts(scope=scope, run_id=run.run_id)

    run, outcomes = execute_run("initial")
    assert {item.field_key: item.outcome.value for item in outcomes} == {
        "benefit": "verified",
        "duration": "not_provided",
    }
    assert len(calls) == 1
    recorded = store.list_calls(scope=scope, run_id=run.run_id)
    assert recorded[0].raw and recorded[0].request_bytes == calls[0]
    assert store.get_run(scope=scope, run_id=run.run_id).usage == {
        "prompt_tokens": 37,
        "completion_tokens": 12,
    }
    _, reused = execute_run("later-upload")
    assert len(calls) == 1
    assert {item.reused_from_attempt_id for item in reused} == {
        item.attempt_id for item in outcomes
    }


def test_recorded_response_is_projected_without_redispatch(
    runtime: typing.Any, source: typing.Any
) -> None:
    store, jobs, scope, specs, selected, settings = runtime
    run = store.create_run(scope=scope, idempotency_key="recorded")
    window = store.enqueue_window(
        scope=scope,
        run_id=run.run_id,
        stage_key="extract",
        window_key="one",
        dependency_sha256="e" * 64,
        tasks=specs,
    )
    claimed = jobs.claim(space_ids=(scope.space_id,), worker_id="worker")
    job = jobs.start(
        space_id=scope.space_id, job_id=window.job_id, generation=claimed.job.lease_generation
    )
    from insurance_harness.product_ingestion.extraction import render_window_request

    request = render_window_request(
        selected,
        (source,),
        tenant_id=1,
        space_id=scope.space_id,
        raw_kb_id=scope.raw_knowledge_base_id,
    )
    sha = hashlib.sha256(request).hexdigest()
    store.reserve_window(
        scope=scope,
        run_id=run.run_id,
        job_id=job.id,
        generation=job.lease_generation,
        attempt=job.attempt,
        call_id="recorded-call",
        window_key="one",
        tasks=specs,
    )
    store.begin_call(
        scope=scope,
        call_id="recorded-call",
        job_id=job.id,
        generation=job.lease_generation,
        request_sha256=sha,
        request_bytes=request,
    )
    store.record_call_result(
        scope=scope,
        call_id="recorded-call",
        job_id=job.id,
        generation=job.lease_generation,
        request_sha256=sha,
        raw=response([row(t, json.loads(request)) for t in selected]),
        diagnostic=None,
    )

    async def load_sources(_scope: object, _run_id: object) -> tuple[typing.Any, ...]:
        return (source,)

    async def transport(_request: bytes) -> bytes:
        pytest.fail("recorded call must not be sent again")

    registry = HandlerRegistry()
    worker_module().register_extraction_worker(
        registry,
        store=store,
        scopes={scope.space_id: scope},
        load_sources=load_sources,
        transport=transport,
    )
    handler = registry.get("product_extraction_window")
    assert handler is not None

    async def invoke_handler() -> typing.Any:
        return await handler(job)

    result = asyncio.run(invoke_handler())
    jobs.report_success(
        space_id=scope.space_id,
        job_id=job.id,
        generation=job.lease_generation,
        domain_writes=result.domain_writes,
        events=result.events,
    )
    assert len(store.list_field_attempts(scope=scope, run_id=run.run_id)) == 2


def test_uncertain_dispatch_settles_failed_without_loading_sources_or_sending_again(
    runtime: typing.Any,
) -> None:
    store, jobs, scope, specs, _, _ = runtime
    run = store.create_run(scope=scope, idempotency_key="interrupted")
    window = store.enqueue_window(
        scope=scope,
        run_id=run.run_id,
        stage_key="extract",
        window_key="one",
        dependency_sha256="e" * 64,
        tasks=specs,
    )
    claim = jobs.claim(space_ids=(scope.space_id,), worker_id="worker")
    job = jobs.start(
        space_id=scope.space_id, job_id=window.job_id, generation=claim.job.lease_generation
    )
    request = b"original request"
    store.reserve_window(
        scope=scope,
        run_id=run.run_id,
        job_id=job.id,
        generation=job.lease_generation,
        attempt=job.attempt,
        call_id="interrupted-call",
        window_key="one",
        tasks=specs,
    )
    store.begin_call(
        scope=scope,
        call_id="interrupted-call",
        job_id=job.id,
        generation=job.lease_generation,
        request_sha256=hashlib.sha256(request).hexdigest(),
        request_bytes=request,
    )

    async def forbidden_sources(*_args: object) -> tuple[typing.Any, ...]:
        pytest.fail("uncertain dispatch cannot invoke source or provider again")

    async def forbidden_transport(_request: bytes) -> bytes:
        pytest.fail("uncertain dispatch cannot invoke source or provider again")

    registry = HandlerRegistry()
    worker_module().register_extraction_worker(
        registry,
        store=store,
        scopes={scope.space_id: scope},
        load_sources=forbidden_sources,
        transport=forbidden_transport,
    )
    handler = registry.get("product_extraction_window")
    assert handler is not None

    async def invoke_handler() -> typing.Any:
        return await handler(job)

    result = asyncio.run(invoke_handler())
    jobs.report_success(
        space_id=scope.space_id,
        job_id=job.id,
        generation=job.lease_generation,
        domain_writes=result.domain_writes,
        events=result.events,
    )
    outcomes = store.list_field_attempts(scope=scope, run_id=run.run_id)
    assert len(outcomes) == 2
    assert all(
        item.outcome.value == "extraction_failed"
        and item.validated_result is None
        and item.reason == "provider_call_interrupted"
        for item in outcomes
    )


def test_configured_transport_persists_full_endpoint_envelope(
    runtime: typing.Any, source: typing.Any
) -> None:
    from datetime import UTC, datetime, timedelta

    from pydantic import SecretStr

    from insurance_harness.product_ingestion.model_execution import ConfiguredModelExecutor
    from insurance_harness.product_ingestion.model_settings import (
        ModelTemplatePolicy,
        ProductModelSettings,
    )

    store, jobs, scope, specs, selected, settings = runtime
    field_prompt = b"Extract only the requested fields."
    policy = ProductModelSettings(
        scope=scope,
        endpoint=HttpUrl("https://gateway.invalid/v1/chat/completions"),
        api_key=SecretStr("fixture-secret"),
        model="gemini-3.7-flash-medium",
        policy_version="g3-user-gemini-gateway-v1",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        templates=(
            ModelTemplatePolicy(
                template_id="field-window-v1",
                role="extract",
                purpose="g3-field-extraction",
                run_schema_version="830-g3-v1",
                prompt_sha256=hashlib.sha256(field_prompt).hexdigest(),
                max_context_bytes=16_384,
                max_output_tokens=1024,
            ),
        ),
        field_template_id="field-window-v1",
        max_request_bytes=32_768,
        max_response_bytes=32_768,
        timeout_seconds=5,
    )
    specs = tuple(
        spec.model_copy(update={"model_policy_sha256": policy.policy_sha256}) for spec in specs
    )
    sent = []

    def provider(request: typing.Any) -> typing.Any:
        sent.append(request)
        envelope = json.loads(request.content)
        semantic = json.loads(envelope["messages"][1]["content"])
        projected = response([row(task, semantic) for task in selected])
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": projected.decode()}}],
                "usage": {"prompt_tokens": 23, "completion_tokens": 7},
            },
        )

    boundary = ConfiguredModelExecutor(
        settings_provider=lambda: policy,
        client=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
    )
    run = store.create_run(scope=scope, idempotency_key="configured-field")
    window = store.enqueue_window(
        scope=scope,
        run_id=run.run_id,
        stage_key="extract",
        window_key="configured",
        dependency_sha256="e" * 64,
        tasks=specs,
    )
    registry = HandlerRegistry()
    worker_module().register_extraction_worker(
        registry,
        store=store,
        scopes={scope.space_id: scope},
        load_sources=lambda *_: asyncio.sleep(0, result=(source,)),
        transport_factory=lambda configured_scope, run_id, job: boundary.field_transport(
            configured_scope, run_id, job, prompt=field_prompt
        ),
    )
    loop = WorkerLoop(
        store=jobs,
        registry=registry,
        settings=settings,
        lifecycle=Lifecycle(),
        worker_id="configured-field",
    )
    claim = jobs.claim(space_ids=(scope.space_id,), worker_id="configured-field")
    assert isinstance(claim, ClaimedJob)

    asyncio.run(loop.process_job(claim.job))

    assert len(sent) == 1
    call = store.list_calls(scope=scope, run_id=run.run_id)[0]
    assert call.request_bytes == sent[0].content
    assert json.loads(call.request_bytes)["model"] == "gemini-3.7-flash-medium"
    assert call.request_bytes != json.loads(call.request_bytes)["messages"][1]["content"].encode()
    assert jobs.get_job(space_id=scope.space_id, job_id=window.job_id).state.value == "succeeded"
    assert store.get_run(scope=scope, run_id=run.run_id).usage == {
        "prompt_tokens": 23,
        "completion_tokens": 7,
    }

    mismatched = tuple(
        spec.model_copy(
            update={
                "model_policy_sha256": "f" * 64,
                "cache_identity": spec.cache_identity.model_copy(
                    update={"product_identity_sha256": "9" * 64}
                ),
            }
        )
        for spec in specs
    )
    denied_run = store.create_run(scope=scope, idempotency_key="configured-field-denied")
    denied_window = store.enqueue_window(
        scope=scope,
        run_id=denied_run.run_id,
        stage_key="extract",
        window_key="configured-denied",
        dependency_sha256="e" * 64,
        tasks=mismatched,
    )
    denied_claim = jobs.claim(space_ids=(scope.space_id,), worker_id="configured-field")
    assert isinstance(denied_claim, ClaimedJob)
    asyncio.run(loop.process_job(denied_claim.job))
    assert len(sent) == 1
    assert (
        jobs.get_job(space_id=scope.space_id, job_id=denied_window.job_id).state.value
        == "retry_wait"
    )
