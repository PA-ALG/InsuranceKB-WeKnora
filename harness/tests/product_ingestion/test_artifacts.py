"""Focused contract tests for non-field product artifacts and model calls."""

from __future__ import annotations

import hashlib
import importlib
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from insurance_harness.db.base import Base, make_engine, make_session_factory
from insurance_harness.jobs import (
    ClaimedJob,
    ErrorClass,
    JobFailure,
    JobRuntimeConfig,
    JobStore,
    SpaceScopeError,
    StaleGenerationError,
)
from insurance_harness.product_ingestion.models import ProductRunState, ProductScope
from insurance_harness.product_ingestion.store import ProductIngestionStore

SessionFactory = Callable[[], Session]
REQUEST = b'{"operation":"identity"}'
REQUEST_SHA = hashlib.sha256(REQUEST).hexdigest()
RAW = b'{"proposals":[]}'


@pytest.fixture(scope="module")
def api() -> SimpleNamespace:
    try:
        models = importlib.import_module(
            "insurance_harness.product_ingestion.artifact_models"
        )
        importlib.import_module("insurance_harness.product_ingestion.artifact_tables")
        artifacts = importlib.import_module("insurance_harness.product_ingestion.artifacts")
    except ModuleNotFoundError as error:
        pytest.fail(f"RED: non-field artifact store is not implemented: {error}")
    names = (
        "ArtifactDraft",
        "ArtifactOrigin",
        "StageCallAction",
        "StageCallState",
    )
    missing = [name for name in names if not hasattr(models, name)]
    if not hasattr(artifacts, "ProductArtifactStore"):
        missing.append("ProductArtifactStore")
    assert not missing, f"RED: artifact public contract missing {missing}"
    return SimpleNamespace(
        **{name: getattr(models, name) for name in names},
        ProductArtifactStore=artifacts.ProductArtifactStore,
    )


@pytest.fixture
def factory(tmp_path: Path, api: SimpleNamespace) -> Iterator[SessionFactory]:
    del api
    engine = make_engine(f"sqlite:///{tmp_path}/artifacts.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    yield factory
    engine.dispose()


def _jobs(factory: SessionFactory) -> JobStore:
    return JobStore(
        factory,
        JobRuntimeConfig(
            lease_seconds=300,
            heartbeat_interval_seconds=30,
            max_attempts=3,
            backoff_seconds=(0,),
            per_space_concurrency_limit=16,
            global_concurrency_limit=32,
        ),
    )


def _scope(*, raw: str = "raw-a", wiki: str = "wiki-a") -> ProductScope:
    return ProductScope(
        tenant_id="tenant-a",
        space_id="space-a",
        raw_knowledge_base_id=raw,
        wiki_knowledge_base_id=wiki,
    )


def _stores(api: SimpleNamespace, factory: SessionFactory) -> tuple[Any, Any, JobStore]:
    jobs = _jobs(factory)
    products = ProductIngestionStore(factory, jobs)
    artifacts = api.ProductArtifactStore(factory, products)
    return artifacts, products, jobs


def _start_stage(
    api: SimpleNamespace,
    factory: SessionFactory,
    *,
    run_key: str = "run-a",
    stage_key: str = "route",
) -> tuple[Any, Any, JobStore, Any, Any]:
    artifacts, products, jobs = _stores(api, factory)
    run = products.create_run(scope=_scope(), idempotency_key=run_key)
    stage = products.enqueue_stage(
        scope=_scope(),
        run_id=run.run_id,
        stage_key=stage_key,
        dependency_sha256="a" * 64,
        idempotency_key=f"{run_key}:{stage_key}",
    )
    claimed = jobs.claim(space_ids=("space-a",), worker_id=f"worker-{stage_key}")
    assert isinstance(claimed, ClaimedJob)
    running = jobs.start(
        space_id="space-a",
        job_id=claimed.job.id,
        generation=claimed.job.lease_generation,
    )
    assert running.id == stage.job_id
    return artifacts, products, jobs, run, running


def _rule_draft(api: SimpleNamespace, payload: bytes = b'{"route":"1820"}') -> Any:
    return api.ArtifactDraft(
        artifact_kind="rule-routing-record",
        artifact_key="product-a",
        contract_name="g3-rule-routing-record",
        contract_version="v1",
        dependency_sha256="b" * 64,
        payload=payload,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        origin=api.ArtifactOrigin.RULE,
    )


def _reserve(
    api: SimpleNamespace,
    artifacts: Any,
    run: Any,
    running: Any,
    *,
    call_id: str = "call-route-1",
) -> Any:
    return artifacts.reserve_stage_call(
        scope=_scope(),
        run_id=run.run_id,
        stage_key="route",
        operation_key="identity",
        dependency_sha256="b" * 64,
        job_id=running.id,
        generation=running.lease_generation,
        attempt=running.attempt,
        call_id=call_id,
        input_sha256="c" * 64,
        model_policy_sha256="d" * 64,
        prompt_policy_sha256="e" * 64,
    )


def test_artifact_dto_rejects_false_model_origin_and_payload_hash(api: SimpleNamespace) -> None:
    with pytest.raises(ValidationError):
        api.ArtifactDraft(
            artifact_kind="c-proposals",
            artifact_key="product-a",
            contract_name="proposal-batch",
            contract_version="v1",
            dependency_sha256="b" * 64,
            payload=b"{}",
            payload_sha256=hashlib.sha256(b"{}").hexdigest(),
            origin=api.ArtifactOrigin.MODEL,
        )
    with pytest.raises(ValidationError):
        api.ArtifactDraft(
            artifact_kind="rule-routing-record",
            artifact_key="product-a",
            contract_name="g3-rule-routing-record",
            contract_version="v1",
            dependency_sha256="b" * 64,
            payload=b"different",
            payload_sha256="0" * 64,
            origin=api.ArtifactOrigin.RULE,
        )


def test_rule_artifact_commits_with_stage_once_and_survives_restart(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    artifacts, products, jobs, run, running = _start_stage(api, factory)
    draft = _rule_draft(api)
    writes = artifacts.prepare_artifact_writes(
        scope=_scope(),
        run_id=run.run_id,
        stage_key="route",
        job_id=running.id,
        generation=running.lease_generation,
        drafts=(draft,),
    )
    stage = products.list_stages(scope=_scope(), run_id=run.run_id)[0]
    settlement = products.prepare_stage_settlement(
        scope=_scope(),
        run_id=run.run_id,
        stage_id=stage.stage_id,
        job_id=running.id,
        generation=running.lease_generation,
        state=ProductRunState.SUCCEEDED,
    )
    jobs.report_success(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        domain_writes=writes + settlement.domain_writes,
        events=settlement.events,
    )

    restarted = api.ProductArtifactStore(factory, ProductIngestionStore(factory, jobs))
    saved = restarted.get_artifact(
        scope=_scope(),
        run_id=run.run_id,
        artifact_kind=draft.artifact_kind,
        artifact_key=draft.artifact_key,
    )
    assert saved.payload == draft.payload
    assert saved.payload_sha256 == draft.payload_sha256
    assert saved.origin is api.ArtifactOrigin.RULE
    assert saved.origin_call_id is None


def test_existing_artifact_is_exact_idempotent_and_changed_body_conflicts(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    artifacts, products, jobs, run, running = _start_stage(api, factory)
    draft = _rule_draft(api)
    writes = artifacts.prepare_artifact_writes(
        scope=_scope(),
        run_id=run.run_id,
        stage_key="route",
        job_id=running.id,
        generation=running.lease_generation,
        drafts=(draft,),
    )
    jobs.report_success(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        domain_writes=writes,
    )
    replay = jobs.enqueue(
        space_id="space-a",
        job_type="product_artifact_replay",
        idempotency_key="artifact-replay",
        payload={"run_id": run.run_id, "stage_key": "route"},
    )
    claimed = jobs.claim(space_ids=("space-a",), worker_id="replay")
    assert isinstance(claimed, ClaimedJob)
    replaying = jobs.start(
        space_id="space-a",
        job_id=replay.job.id,
        generation=claimed.job.lease_generation,
    )
    assert artifacts.prepare_artifact_writes(
        scope=_scope(),
        run_id=run.run_id,
        stage_key="route",
        job_id=replaying.id,
        generation=replaying.lease_generation,
        drafts=(draft,),
    ) == ()
    with pytest.raises(ValueError, match="immutable"):
        artifacts.prepare_artifact_writes(
            scope=_scope(),
            run_id=run.run_id,
            stage_key="route",
            job_id=replaying.id,
            generation=replaying.lease_generation,
            drafts=(_rule_draft(api, b'{"route":"1818"}'),),
        )


def test_recorded_model_call_owns_raw_and_validated_artifact(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    artifacts, products, jobs, run, running = _start_stage(api, factory)
    reserved = _reserve(api, artifacts, run, running)
    assert reserved.action is api.StageCallAction.DISPATCH
    assert artifacts.get_stage_call_metrics(
        scope=_scope(), run_id=run.run_id
    ).model_call_count == 0
    dispatched = artifacts.begin_stage_call(
        scope=_scope(),
        call_id=reserved.call.call_id,
        job_id=running.id,
        generation=running.lease_generation,
        request_sha256=REQUEST_SHA,
        request_bytes=REQUEST,
    )
    assert dispatched.state is api.StageCallState.DISPATCHED
    assert artifacts.begin_stage_call(
        scope=_scope(),
        call_id=reserved.call.call_id,
        job_id=running.id,
        generation=running.lease_generation,
        request_sha256=REQUEST_SHA,
        request_bytes=REQUEST,
    ) == dispatched
    with pytest.raises(ValueError, match="immutable"):
        artifacts.begin_stage_call(
            scope=_scope(),
            call_id=reserved.call.call_id,
            job_id=running.id,
            generation=running.lease_generation,
            request_sha256=hashlib.sha256(b"changed").hexdigest(),
            request_bytes=b"changed",
        )
    recorded = artifacts.record_stage_call_result(
        scope=_scope(),
        call_id=reserved.call.call_id,
        job_id=running.id,
        generation=running.lease_generation,
        request_sha256=REQUEST_SHA,
        raw=RAW,
        diagnostic=None,
        usage={"input_tokens": 11, "output_tokens": 5},
    )
    assert recorded.state is api.StageCallState.RECORDED
    assert recorded.raw == RAW
    assert recorded.raw_sha256 == hashlib.sha256(RAW).hexdigest()
    assert artifacts.get_stage_call_metrics(
        scope=_scope(), run_id=run.run_id
    ).model_dump() == {
        "model_call_count": 1,
        "reused_model_call_count": 0,
        "reused_usage": {},
        "unsettled_call_count": 0,
        "usage": {"input_tokens": 11, "output_tokens": 5},
    }
    assert artifacts.record_stage_call_result(
        scope=_scope(),
        call_id=reserved.call.call_id,
        job_id=running.id,
        generation=running.lease_generation,
        request_sha256=REQUEST_SHA,
        raw=RAW,
        diagnostic=None,
        usage={"input_tokens": 11, "output_tokens": 5},
    ) == recorded
    with pytest.raises(ValueError, match="immutable"):
        artifacts.record_stage_call_result(
            scope=_scope(),
            call_id=reserved.call.call_id,
            job_id=running.id,
            generation=running.lease_generation,
            request_sha256=REQUEST_SHA,
            raw=b'{"different":true}',
            diagnostic=None,
            usage={"input_tokens": 11, "output_tokens": 5},
        )

    payload = b'{"validated_proposals":[]}'
    draft = api.ArtifactDraft(
        artifact_kind="c-proposals",
        artifact_key="product-a",
        contract_name="proposal-batch",
        contract_version="v1",
        dependency_sha256="b" * 64,
        payload=payload,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        origin=api.ArtifactOrigin.MODEL,
        origin_call_id=recorded.call_id,
    )
    with pytest.raises(ValueError, match="dependency"):
        artifacts.prepare_artifact_writes(
            scope=_scope(),
            run_id=run.run_id,
            stage_key="route",
            job_id=running.id,
            generation=running.lease_generation,
            drafts=(draft.model_copy(update={"dependency_sha256": "f" * 64}),),
        )
    writes = artifacts.prepare_artifact_writes(
        scope=_scope(),
        run_id=run.run_id,
        stage_key="route",
        job_id=running.id,
        generation=running.lease_generation,
        drafts=(draft,),
    )
    jobs.report_success(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        domain_writes=writes,
    )
    saved = artifacts.get_artifact(
        scope=_scope(),
        run_id=run.run_id,
        artifact_kind="c-proposals",
        artifact_key="product-a",
    )
    assert saved.origin_call_id == recorded.call_id
    assert saved.payload == payload
    assert artifacts.get_stage_call(scope=_scope(), call_id=recorded.call_id) == recorded


def test_call_and_artifact_paths_enforce_full_scope_and_generation(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    artifacts, _products, _jobs, run, running = _start_stage(api, factory)
    reserved = _reserve(api, artifacts, run, running)
    with pytest.raises(StaleGenerationError):
        artifacts.begin_stage_call(
            scope=_scope(),
            call_id=reserved.call.call_id,
            job_id=running.id,
            generation=running.lease_generation + 1,
            request_sha256=REQUEST_SHA,
            request_bytes=REQUEST,
        )
    with pytest.raises(StaleGenerationError):
        artifacts.prepare_artifact_writes(
            scope=_scope(),
            run_id=run.run_id,
            stage_key="route",
            job_id=running.id,
            generation=running.lease_generation + 1,
            drafts=(_rule_draft(api),),
        )
    foreign = _scope(raw="raw-other", wiki="wiki-other")
    with pytest.raises(SpaceScopeError):
        artifacts.get_stage_call(scope=foreign, call_id=reserved.call.call_id)
    with pytest.raises(SpaceScopeError):
        artifacts.prepare_artifact_writes(
            scope=foreign,
            run_id=run.run_id,
            stage_key="route",
            job_id=running.id,
            generation=running.lease_generation,
            drafts=(_rule_draft(api),),
        )


def test_dispatched_call_becomes_interrupted_after_retry_without_resend(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    artifacts, _products, jobs, run, running = _start_stage(api, factory)
    reserved = _reserve(api, artifacts, run, running)
    artifacts.begin_stage_call(
        scope=_scope(),
        call_id=reserved.call.call_id,
        job_id=running.id,
        generation=running.lease_generation,
        request_sha256=REQUEST_SHA,
        request_bytes=REQUEST,
    )
    jobs.report_failure(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="worker_crashed"),
    )
    claimed = jobs.claim(space_ids=("space-a",), worker_id="recovery")
    assert isinstance(claimed, ClaimedJob)
    recovered = jobs.start(
        space_id="space-a",
        job_id=claimed.job.id,
        generation=claimed.job.lease_generation,
    )
    second = _reserve(
        api,
        artifacts,
        run,
        recovered,
        call_id="fresh-random-id-after-interruption",
    )
    assert second.action is api.StageCallAction.INTERRUPTED
    assert second.call.call_id == reserved.call.call_id
    assert second.call.state is api.StageCallState.INTERRUPTED
    assert second.call.diagnostic == "provider_call_interrupted"


def test_recorded_call_recovery_returns_raw_without_new_dispatch(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    artifacts, _products, jobs, run, running = _start_stage(api, factory)
    reserved = _reserve(api, artifacts, run, running)
    artifacts.begin_stage_call(
        scope=_scope(),
        call_id=reserved.call.call_id,
        job_id=running.id,
        generation=running.lease_generation,
        request_sha256=REQUEST_SHA,
        request_bytes=REQUEST,
    )
    artifacts.record_stage_call_result(
        scope=_scope(),
        call_id=reserved.call.call_id,
        job_id=running.id,
        generation=running.lease_generation,
        request_sha256=REQUEST_SHA,
        raw=RAW,
        diagnostic=None,
        usage={},
    )
    jobs.report_failure(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        failure=JobFailure(error_class=ErrorClass.RETRYABLE, summary="crash_after_raw"),
    )
    claimed = jobs.claim(space_ids=("space-a",), worker_id="recovery")
    assert isinstance(claimed, ClaimedJob)
    recovered = jobs.start(
        space_id="space-a",
        job_id=claimed.job.id,
        generation=claimed.job.lease_generation,
    )
    replay = _reserve(
        api,
        artifacts,
        run,
        recovered,
        call_id="fresh-random-id-after-recording",
    )
    assert replay.action is api.StageCallAction.RECORDED
    assert replay.call.call_id == reserved.call.call_id
    assert replay.call.raw == RAW


def test_model_artifact_rejects_unrecorded_call(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    artifacts, _products, _jobs, run, running = _start_stage(api, factory)
    reserved = _reserve(api, artifacts, run, running)
    payload = b'{"validated":true}'
    draft = api.ArtifactDraft(
        artifact_kind="c-proposals",
        artifact_key="product-a",
        contract_name="proposal-batch",
        contract_version="v1",
        dependency_sha256="b" * 64,
        payload=payload,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        origin=api.ArtifactOrigin.MODEL,
        origin_call_id=reserved.call.call_id,
    )
    with pytest.raises(ValueError, match="recorded raw"):
        artifacts.prepare_artifact_writes(
            scope=_scope(),
            run_id=run.run_id,
            stage_key="route",
            job_id=running.id,
            generation=running.lease_generation,
            drafts=(draft,),
        )


def test_model_artifact_rejects_foreign_run_and_diagnostic_only_call(
    api: SimpleNamespace,
    factory: SessionFactory,
) -> None:
    artifacts, _products, _jobs, first_run, first_job = _start_stage(
        api, factory, run_key="origin-run"
    )
    first = _reserve(api, artifacts, first_run, first_job, call_id="call-origin")
    artifacts.begin_stage_call(
        scope=_scope(),
        call_id=first.call.call_id,
        job_id=first_job.id,
        generation=first_job.lease_generation,
        request_sha256=REQUEST_SHA,
        request_bytes=REQUEST,
    )
    artifacts.record_stage_call_result(
        scope=_scope(),
        call_id=first.call.call_id,
        job_id=first_job.id,
        generation=first_job.lease_generation,
        request_sha256=REQUEST_SHA,
        raw=RAW,
        diagnostic=None,
        usage={},
    )

    artifacts, _products, _jobs, second_run, second_job = _start_stage(
        api, factory, run_key="consumer-run"
    )
    payload = b'{"validated":true}'
    foreign = api.ArtifactDraft(
        artifact_kind="c-proposals",
        artifact_key="foreign",
        contract_name="proposal-batch",
        contract_version="v1",
        dependency_sha256="b" * 64,
        payload=payload,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        origin=api.ArtifactOrigin.MODEL,
        origin_call_id=first.call.call_id,
    )
    with pytest.raises(ValueError, match="same-run recorded raw"):
        artifacts.prepare_artifact_writes(
            scope=_scope(),
            run_id=second_run.run_id,
            stage_key="route",
            job_id=second_job.id,
            generation=second_job.lease_generation,
            drafts=(foreign,),
        )

    second = _reserve(
        api,
        artifacts,
        second_run,
        second_job,
        call_id="call-diagnostic-only",
    )
    artifacts.begin_stage_call(
        scope=_scope(),
        call_id=second.call.call_id,
        job_id=second_job.id,
        generation=second_job.lease_generation,
        request_sha256=REQUEST_SHA,
        request_bytes=REQUEST,
    )
    artifacts.record_stage_call_result(
        scope=_scope(),
        call_id=second.call.call_id,
        job_id=second_job.id,
        generation=second_job.lease_generation,
        request_sha256=REQUEST_SHA,
        raw=None,
        diagnostic="transport_timeout",
        usage={},
    )
    diagnostic_only = foreign.model_copy(
        update={
            "artifact_key": "diagnostic-only",
            "origin_call_id": second.call.call_id,
        }
    )
    with pytest.raises(ValueError, match="same-run recorded raw"):
        artifacts.prepare_artifact_writes(
            scope=_scope(),
            run_id=second_run.run_id,
            stage_key="route",
            job_id=second_job.id,
            generation=second_job.lease_generation,
            drafts=(diagnostic_only,),
        )
