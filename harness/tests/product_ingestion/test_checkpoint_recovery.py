"""Checkpoint continuation reuses actual prior stage results, including ordinary failures."""

from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy import event

from insurance_harness.db.base import Base, make_session_factory
from insurance_harness.jobs import JobStore, NonRetryableJobError
from insurance_harness.product_ingestion.models import FieldOutcomeKind, ProductRunState
from insurance_harness.product_ingestion.progression import admit_uploads
from tests.product_ingestion.test_checkpoint_contract import _enqueue_control
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


@pytest.mark.asyncio
@pytest.mark.parametrize("response_lost", [False, True])
@pytest.mark.parametrize("derived_failure", [False, True])
async def test_real_pipeline_compile_checkpoint_resumes_without_any_model_or_source_resend(
    tmp_path,
    monkeypatch,
    response_lost,
    derived_failure,
):
    if derived_failure:
        from insurance_harness.product_ingestion import field_validation
        from insurance_harness.product_ingestion.checkpoints import field_digest

        validate = field_validation.validate_field_attempts

        def nonempty_validation(**kwargs):
            report = validate(**kwargs)
            row = next(r for r in kwargs["attempts"] if r.outcome is FieldOutcomeKind.NOT_PROVIDED)
            counts = dict(report.counts)
            counts["not_provided"] -= 1
            counts["extraction_failed"] += 1
            return report.model_copy(
                update={
                    "counts": counts,
                    "changes": {
                        **report.changes,
                        row.attempt_id: field_validation.FieldValidationChange(
                            original_digest=field_digest(row),
                            raw_ref=row.raw_ref,
                            outcome=FieldOutcomeKind.EXTRACTION_FAILED,
                            reason="EVIDENCE_CHARACTER_LOCATION_MISSING",
                            validated_result=None,
                        ),
                    },
                }
            )

        monkeypatch.setattr(field_validation, "validate_field_attempts", nonempty_validation)
    base, parent = _base_snapshot_with_navigation()
    settings = _settings(tmp_path, parent)
    engine = _sqlite_engine(tmp_path / "checkpoint.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    jobs = JobStore(factory, settings.job_runtime_config())
    platform, model = FixturePlatform(base), FixtureModel()
    runtime, context, model_client = await _compose(settings, factory, platform, model)
    service = context.bindings[SCOPE.space_id]
    original_create = service.platform.create_preparation
    submissions = []

    async def transfer_limit(*args, **kwargs):
        submissions.append((args[1], args[2]))
        if response_lost:
            await original_create(*args, **kwargs)
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
        assert stage_states["compilation"] == "succeeded"
        assert stage_states["preparation"] == "dead_letter"
        saved_candidate = context.artifacts.get_artifact(
            scope=SCOPE, run_id=origin.run_id, artifact_kind="candidate", artifact_key="product"
        )
        assert saved_candidate.payload == submissions[0][1]
        assert json.loads(saved_candidate.payload).get("navigation_assignments") == [
            row.model_dump(mode="json") for row in parent.navigation_assignments
        ], "incremental compilation must preserve the published navigation"

        _enqueue_control(context.store, SCOPE, failed)
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
        assert plan.resume_stage == "preparation"
        assert len(plan.encoded()) < 128 * 1024
        assert all(ref.artifact_id for ref in plan.artifacts)
        assert [
            row.stage_key for row in context.store.list_stages(scope=SCOPE, run_id=child.run_id)
        ] == ["checkpoint"]
        child_rows = context.artifacts.list_artifacts(scope=SCOPE, run_id=child.run_id)
        assert not any(
            row.artifact_kind
            in {"source_snapshot", "compile_request", "compile_delta", "candidate"}
            for row in child_rows
        )

        from insurance_harness.product_ingestion import compilation

        def no_reassembly(*args, **kwargs):
            raise AssertionError("completed candidate must not be assembled again")

        monkeypatch.setattr(compilation, "assemble_platform_candidate", no_reassembly)

        async def record_submission(*args, **kwargs):
            submissions.append((args[1], args[2]))
            return await original_create(*args, **kwargs)

        service.platform.create_preparation = record_submission
        result = await _finish(runtime, context, jobs, child.run_id)
        assert result.state is ProductRunState.PARTIAL_SUCCESS, (
            result.terminal_reason,
            runtime.issues,
        )
        assert submissions == [submissions[0], submissions[0]], (
            "recovery must use the same preparation identity and canonical candidate bytes"
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
        if derived_failure:
            report = json.loads(old_bytes["field_validation", "product"])
            assert report["changes"], "regression must exercise a genuinely changed effective view"
            assert receipt.field_sha256 == report["input_digests"]
            assert any(
                receipt.field_sha256[r.attempt_id] != field_digest(r) for r in before_attempts
            )
        assert [row.stage_key for row in receipt.reused_stages] == [
            "uploads",
            "source",
            "routing",
            "identity",
            "field_plan",
            "extract",
            "synthesis",
            "compilation",
        ]
        for kind in ("compile_request", "compile_delta", "candidate"):
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
            row.stage_key not in {"source", "identity", "extract", "synthesis", "compilation"}
            for row in context.store.list_stages(
                scope=SCOPE,
                run_id=child.run_id,
            )
        )
    finally:
        await runtime.close()
        await model_client.aclose()
        engine.dispose()
