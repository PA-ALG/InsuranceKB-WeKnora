"""Checkpoint continuation reuses actual prior stage results, including ordinary failures."""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import event

from insurance_harness.db.base import Base, make_session_factory
from insurance_harness.jobs import JobStore, NonRetryableJobError
from insurance_harness.product_ingestion.models import FieldOutcomeKind, ProductRunState
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


@pytest.mark.asyncio
async def test_real_pipeline_compile_checkpoint_resumes_without_any_model_or_source_resend(
    tmp_path,
):
    base, parent = _base_snapshot()
    settings = _settings(tmp_path, parent)
    engine = _sqlite_engine(tmp_path / "checkpoint.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    jobs = JobStore(factory, settings.job_runtime_config())
    platform, model = FixturePlatform(base), FixtureModel()
    runtime, context, model_client = await _compose(settings, factory, platform, model)
    service = context.bindings[SCOPE.space_id]
    original_create = service.platform.create_preparation

    async def transfer_limit(*args, **kwargs):
        raise NonRetryableJobError("PLATFORM_CANDIDATE_LIMIT_EXCEEDED")

    service.platform.create_preparation = transfer_limit
    try:
        origin = context.store.create_run(
            scope=SCOPE,
            idempotency_key="compile-capacity-fixture",
            expected_upload_count=3,
        )
        admit_uploads(context.store, SCOPE, origin.run_id)
        failed = await _finish(runtime, context, jobs, origin.run_id)
        assert failed.state is ProductRunState.FAILED
        stage_states = {
            row.stage_key: row.state
            for row in context.store.list_stages(
                scope=SCOPE,
                run_id=origin.run_id,
            )
        }
        assert stage_states["synthesis"] in {"succeeded", "partial_success"}
        assert stage_states["compilation"] == "dead_letter"
        before_attempts = context.store.list_field_attempts(scope=SCOPE, run_id=origin.run_id)
        assert any(row.outcome is FieldOutcomeKind.EXTRACTION_FAILED for row in before_attempts)
        old_artifacts = context.artifacts.list_artifacts(scope=SCOPE, run_id=origin.run_id)
        old_bytes = {(row.artifact_kind, row.artifact_key): row.payload for row in old_artifacts}
        before_calls = tuple(
            len(getattr(model, name))
            for name in (
                "identity_requests",
                "field_requests",
                "discovery_requests",
                "discovery_review_requests",
            )
        )
        calls = context.store.list_calls(scope=SCOPE, run_id=origin.run_id)
        old_raw = {row.call_id: (row.raw, row.raw_sha256) for row in calls}
        captures = platform.source_captures
        assert context.store.can_retry_processing(scope=SCOPE, run_id=origin.run_id), (
            "recovery must follow valid completed checkpoints, not error-string allowlists"
        )

        def no_payload_on_admission(state):
            if not state.is_select:
                return
            names = {getattr(item, "name", "") for item in state.statement.get_final_froms()}
            if names & {
                "product_ingestion_artifacts",
                "product_ingestion_stage_calls",
                "product_ingestion_model_calls",
            }:
                columns = {getattr(col, "name", "") for col in state.statement.selected_columns}
                assert not columns & {"payload", "raw", "request_bytes"}, (
                    "admission eagerly reads historical bytes"
                )

        event.listen(factory.class_, "do_orm_execute", no_payload_on_admission)
        try:
            child = context.store.retry_processing(
                scope=SCOPE,
                run_id=origin.run_id,
                expected_version=failed.version,
            )
            duplicate = context.store.retry_processing(
                scope=SCOPE,
                run_id=origin.run_id,
                expected_version=failed.version,
            )
            assert duplicate.run_id == child.run_id
        finally:
            event.remove(factory.class_, "do_orm_execute", no_payload_on_admission)
        plan = context.store.checkpoint_plan(scope=SCOPE, run_id=child.run_id)
        assert plan.origin_run_id == origin.run_id
        assert plan.resume_stage == "compilation"
        assert len(plan.encoded()) < 128 * 1024
        assert all(ref.artifact_id for ref in plan.artifacts)
        assert [
            row.stage_key for row in context.store.list_stages(scope=SCOPE, run_id=child.run_id)
        ] == ["checkpoint"]
        child_rows = context.artifacts.list_artifacts(scope=SCOPE, run_id=child.run_id)
        assert not any(
            row.artifact_kind in {"source_snapshot", "compile_request", "compile_delta"}
            for row in child_rows
        )

        service.platform.create_preparation = original_create
        result = await _finish(runtime, context, jobs, child.run_id)
        assert result.state is ProductRunState.PARTIAL_SUCCESS, (
            result.terminal_reason,
            runtime.issues,
        )
        assert (
            tuple(
                len(getattr(model, name))
                for name in (
                    "identity_requests",
                    "field_requests",
                    "discovery_requests",
                    "discovery_review_requests",
                )
            )
            == before_calls
        )
        assert platform.source_captures == captures and platform.activations == 1
        assert context.store.get_run(scope=SCOPE, run_id=origin.run_id) == failed
        assert (
            context.store.list_field_attempts(scope=SCOPE, run_id=child.run_id) == before_attempts
        )
        assert {
            row.call_id: (row.raw, row.raw_sha256)
            for row in context.store.list_calls(
                scope=SCOPE,
                run_id=origin.run_id,
            )
        } == old_raw
        receipt = context.store.checkpoint_receipt(scope=SCOPE, run_id=child.run_id)
        assert [row.stage_key for row in receipt.reused_stages] == [
            "uploads",
            "source",
            "routing",
            "identity",
            "field_plan",
            "extract",
            "synthesis",
        ]
        for kind in ("compile_request", "compile_delta"):
            inherited = context.artifacts.get_effective_artifact(
                scope=SCOPE,
                run_id=child.run_id,
                artifact_kind=kind,
                artifact_key="product",
            )
            assert inherited.payload == old_bytes[kind, "product"]
            assert inherited.run_id == origin.run_id
            assert hashlib.sha256(inherited.payload).hexdigest() == inherited.payload_sha256
        assert all(
            row.stage_key not in {"source", "identity", "extract", "synthesis"}
            for row in context.store.list_stages(
                scope=SCOPE,
                run_id=child.run_id,
            )
        )
    finally:
        await runtime.close()
        await model_client.aclose()
        engine.dispose()
