"""Versioned checkpoint rebase contracts preserve historical wire bytes."""

# ruff: noqa: F811 -- fixture imports are intentionally reused by pytest.

import json

import httpx
import pytest
from sqlalchemy import select

from insurance_harness.db.base import Base, make_session_factory
from insurance_harness.jobs import JobStore, NonRetryableJobError
from insurance_harness.product_ingestion.artifact_tables import (
    ProductArtifact,
    ProductStageModelCall,
)
from insurance_harness.product_ingestion.checkpoints import CheckpointPlan, CheckpointReceipt
from insurance_harness.product_ingestion.models import ProductRunState
from insurance_harness.product_ingestion.progression import admit_uploads
from tests.product_ingestion.test_checkpoint_contract import _child
from tests.product_ingestion.test_pipeline_runtime import (
    SCOPE,
    FixtureModel,
    FixturePlatform,
    _base_snapshot_with_navigation,
    _compose,
    _finish,
    _published_snapshot,
    _settings,
    _sqlite_engine,
)
from tests.product_ingestion.test_platform import snapshot  # noqa: F401
from tests.product_ingestion.test_routing import catalog  # noqa: F401
from tests.product_ingestion.test_stages import stage_runtime  # noqa: F401


def test_v6_is_workflow_three_and_keeps_old_wire(stage_runtime, monkeypatch):
    scope, store, artifacts, _, child = _child(stage_runtime, monkeypatch)
    old = store.checkpoint_plan(scope=scope, run_id=child.run_id)
    old_bytes = old.encoded()
    rebased = CheckpointPlan.model_validate(
        {**old.model_dump(), "contract": "product-stage-checkpoint-plan.830.v6"}
    )
    assert rebased.workflow_version == 3
    assert rebased.resume_stage == "routing"
    assert old.encoded() == old_bytes
    receipt = CheckpointReceipt.model_validate(
        {
            **artifacts.verify_checkpoint(scope=scope, run_id=child.run_id).model_dump(),
            "contract": "product-stage-checkpoint-receipt.830.v6",
        }
    )
    assert receipt.plan_sha256 == old.digest()


@pytest.mark.asyncio
async def test_changed_head_rebases_only_current_inputs_after_full_old_validation(tmp_path):
    base, parent = _base_snapshot_with_navigation()
    settings = _settings(tmp_path, parent)
    engine = _sqlite_engine(tmp_path / "rebase.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    jobs = JobStore(factory, settings.job_runtime_config())
    platform, model = FixturePlatform(base), FixtureModel()
    runtime, context, model_client = await _compose(settings, factory, platform, model)
    service = context.bindings[SCOPE.space_id]
    original_create = service.platform.create_preparation

    async def fail_preparation(*args, **kwargs):
        raise NonRetryableJobError("PREPARATION_TEST_LIMIT")

    service.platform.create_preparation = fail_preparation
    try:
        origin = context.store.create_run(
            scope=SCOPE, idempotency_key="rebase-origin", expected_upload_count=3
        )
        admit_uploads(context.store, SCOPE, origin.run_id)
        failed = await _finish(runtime, context, jobs, origin.run_id)
        assert failed.state is ProductRunState.FAILED
        old_request = context.artifacts.get_artifact(
            scope=SCOPE, run_id=origin.run_id,
            artifact_kind="compile_request", artifact_key="product",
        ).payload
        field_calls = len(model.field_requests)
        assert context.store.can_retry_processing(scope=SCOPE, run_id=origin.run_id)
        new_base = _published_snapshot(parent, release_id="unrelated-release", activation_epoch=10)
        platform.base = new_base
        platform.current = {"release_id": "unrelated-release", "activation_epoch": 10}
        child = context.store.retry_processing(
            scope=SCOPE, run_id=origin.run_id, expected_version=failed.version
        )
        plan = context.store.checkpoint_plan(scope=SCOPE, run_id=child.run_id)
        assert plan.contract_version == "6"
        second_failure = await _finish(runtime, context, jobs, child.run_id)
        assert second_failure.state is ProductRunState.FAILED
        receipt = context.store.checkpoint_receipt(scope=SCOPE, run_id=child.run_id)
        assert receipt.rebased_base_sha256 is not None
        assert receipt.reused_stages[-1].stage_key == "synthesis"
        new_request = context.artifacts.get_rebased_artifact(
            scope=SCOPE, run_id=child.run_id, artifact_kind="rebased_compile_request"
        ).payload
        assert new_request != old_request
        platform.base = _published_snapshot(
            parent, release_id="second-unrelated-release", activation_epoch=11
        )
        platform.current = {
            "release_id": "second-unrelated-release", "activation_epoch": 11,
        }
        grandchild = context.store.retry_processing(
            scope=SCOPE, run_id=child.run_id, expected_version=second_failure.version
        )
        grandplan = context.store.checkpoint_plan(scope=SCOPE, run_id=grandchild.run_id)
        assert {row.artifact_kind for row in grandplan.prior_rebase_artifacts} == {
            "rebased_base_snapshot", "rebased_compile_request",
            "rebased_identity", "rebased_compile_delta",
        }
        service.platform.create_preparation = original_create
        result = await _finish(runtime, context, jobs, grandchild.run_id)
        assert result.state in {ProductRunState.SUCCEEDED, ProductRunState.PARTIAL_SUCCESS}, (
            result.terminal_reason, runtime.issues
        )
        assert context.store.checkpoint_receipt(
            scope=SCOPE, run_id=grandchild.run_id
        ).rebased_base_sha256 is not None
        assert len(model.field_requests) == field_calls
    finally:
        await runtime.close()
        await model_client.aclose()
        engine.dispose()


@pytest.mark.asyncio
async def test_changed_head_does_not_resend_a_discovery_with_unknown_outcome(tmp_path):
    base, parent = _base_snapshot_with_navigation()
    settings = _settings(tmp_path, parent)
    engine = _sqlite_engine(tmp_path / "unknown-discovery.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    jobs = JobStore(factory, settings.job_runtime_config())
    platform, model = FixturePlatform(base), FixtureModel()
    runtime, context, model_client = await _compose(settings, factory, platform, model)
    service = context.bindings[SCOPE.space_id]

    async def fail_preparation(*args, **kwargs):
        raise NonRetryableJobError("PREPARATION_TEST_LIMIT")

    service.platform.create_preparation = fail_preparation
    try:
        origin = context.store.create_run(
            scope=SCOPE, idempotency_key="unknown-discovery", expected_upload_count=3
        )
        admit_uploads(context.store, SCOPE, origin.run_id)
        failed = await _finish(runtime, context, jobs, origin.run_id)
        assert failed.state is ProductRunState.FAILED
        with factory() as session, session.begin():
            recorded = session.scalar(select(ProductStageModelCall).where(
                ProductStageModelCall.run_id == origin.run_id,
                ProductStageModelCall.stage_key == "discovery",
            ))
            assert recorded is not None and recorded.state == "recorded"
            values = {column.name: getattr(recorded, column.name)
                      for column in ProductStageModelCall.__table__.columns}
            values.update(
                id="unknown-discovery-record", call_id="unknown-discovery-call",
                operation_key="unknown-discovery-window", state="interrupted",
                raw=None, raw_sha256=None, recorded_at=None, diagnostic=None,
                usage={},
            )
            session.add(ProductStageModelCall(**values))
        assert context.store.can_retry_processing(scope=SCOPE, run_id=origin.run_id)
        platform.base = _published_snapshot(
            parent, release_id="unrelated-unknown-release", activation_epoch=10
        )
        platform.current = {
            "release_id": "unrelated-unknown-release", "activation_epoch": 10,
        }
        before = len(model.discovery_requests)
        child = context.store.retry_processing(
            scope=SCOPE, run_id=origin.run_id, expected_version=failed.version
        )
        result = await _finish(runtime, context, jobs, child.run_id)
        assert result.state is ProductRunState.NEEDS_CONFIRMATION
        assert result.terminal_reason == "CHECKPOINT_INVALID"
        assert len(model.discovery_requests) == before
    finally:
        await runtime.close()
        await model_client.aclose()
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["PENDING", "REJECTED"])
async def test_changed_head_preserves_nonpass_discovery_without_model_retry(
    tmp_path, decision, monkeypatch
):
    base, parent = _base_snapshot_with_navigation()
    settings = _settings(tmp_path, parent)
    engine = _sqlite_engine(tmp_path / f"{decision}.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    jobs = JobStore(factory, settings.job_runtime_config())
    platform, model = FixturePlatform(base), FixtureModel()
    runtime, context, model_client = await _compose(settings, factory, platform, model)
    service = context.bindings[SCOPE.space_id]
    original_create = service.platform.create_preparation

    async def fail_preparation(*args, **kwargs):
        raise NonRetryableJobError("PREPARATION_TEST_LIMIT")

    service.platform.create_preparation = fail_preparation
    try:
        origin = context.store.create_run(
            scope=SCOPE, idempotency_key="nonpass-" + decision, expected_upload_count=3
        )
        admit_uploads(context.store, SCOPE, origin.run_id)
        failed = await _finish(runtime, context, jobs, origin.run_id)
        with factory() as session, session.begin():
            row = session.scalar(select(ProductArtifact).where(
                ProductArtifact.run_id == origin.run_id,
                ProductArtifact.artifact_kind == "discovery_final_summary",
            ))
            summary = json.loads(row.payload)
            summary.update(state=decision, reason_codes=["DISCOVERY_" + decision])
            row.payload = json.dumps(
                summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
            import hashlib
            row.payload_sha256 = hashlib.sha256(row.payload).hexdigest()
        platform.base = _published_snapshot(
            parent, release_id="nonpass-new-release", activation_epoch=10
        )
        platform.current = {"release_id": "nonpass-new-release", "activation_epoch": 10}
        before = (len(model.discovery_requests), len(model.discovery_review_requests))
        child = context.store.retry_processing(
            scope=SCOPE, run_id=origin.run_id, expected_version=failed.version
        )
        service.platform.create_preparation = original_create
        if decision == "PENDING":
            from insurance_harness.product_ingestion import compilation

            assemble = compilation.assemble_platform_candidate

            def fail_after_checkpoint(*args, **kwargs):
                raise ValueError("fixture compilation interruption after rebased disposition")

            monkeypatch.setattr(compilation, "assemble_platform_candidate", fail_after_checkpoint)
            interrupted = await _finish(runtime, context, jobs, child.run_id)
            assert interrupted.state is ProductRunState.FAILED
            grandchild = context.store.retry_processing(
                scope=SCOPE, run_id=child.run_id, expected_version=interrupted.version
            )
            inherited = context.store.checkpoint_plan(
                scope=SCOPE, run_id=grandchild.run_id
            ).prior_rebase_artifacts
            assert "rebased_discovery_disposition" in {
                row.artifact_kind for row in inherited
            }
            monkeypatch.setattr(compilation, "assemble_platform_candidate", assemble)
            result = await _finish(runtime, context, jobs, grandchild.run_id)
            result_run_id = grandchild.run_id
        else:
            result = await _finish(runtime, context, jobs, child.run_id)
            result_run_id = child.run_id
        assert result.state is ProductRunState.PARTIAL_SUCCESS, (
            result.terminal_reason, runtime.issues
        )
        assert (len(model.discovery_requests), len(model.discovery_review_requests)) == before
        disposition = context.artifacts.get_artifact(
            scope=SCOPE, run_id=result_run_id,
            artifact_kind="rebased_discovery_disposition", artifact_key="product",
        )
        assert json.loads(disposition.payload)["state"] == decision
        final = context.artifacts.get_artifact(
            scope=SCOPE, run_id=result_run_id,
            artifact_kind="discovery_final_summary", artifact_key="product",
        )
        assert json.loads(final.payload)["state"] == decision
    finally:
        await runtime.close()
        await model_client.aclose()
        engine.dispose()


@pytest.mark.asyncio
async def test_final_discovery_failure_resumes_compilation_without_generation(tmp_path):
    class ReviewFailsOnce(FixtureModel):
        broken = True

        def __call__(self, request):
            envelope = json.loads(request.content)
            content = json.loads(envelope["messages"][1]["content"])
            if content.get("contract") == "product-discovery-context.830.v3":
                from tests.product_ingestion.test_independent_discovery import _proposal

                self.discovery_requests.append(envelope)
                return httpx.Response(200, json={
                    "choices": [{"message": {"content": json.dumps(
                        _proposal(content), ensure_ascii=False
                    )}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                })
            if content.get("contract") == "product-discovery-review-context.830.v3":
                self.discovery_review_requests.append(envelope)
                if self.broken:
                    response = {"invalid": True}
                else:
                    score = dict(business_value=25, reuse=20, evidence_quality=20,
                                 definability=15, novel_identity=10, name_stability=10)
                    response = {
                        "contract": "product-discovery-review.830.v1",
                        "review": {
                            "contract": "concept-review-output.830.g2.v1",
                            "request_hash": content["request_hash"],
                            "output_hash": content["output_hash"],
                            "decision": "PASS", "reasons": ["Original evidence verified"],
                            "page_scores": {key: score for key in content["review_member_ids"]},
                        },
                        "disposition_checks": [
                            {"candidate_id": row["candidate_id"], "decision": "ACCEPT",
                             "reason": "Unique useful process"}
                            for row in content["dispositions"]
                        ],
                    }
                return httpx.Response(200, json={
                    "choices": [{"message": {"content": json.dumps(
                        response, ensure_ascii=False
                    )}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                })
            return super().__call__(request)

    base, parent = _base_snapshot_with_navigation()
    settings = _settings(tmp_path, parent)
    engine = _sqlite_engine(tmp_path / "final-review-recovery.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    jobs = JobStore(factory, settings.job_runtime_config())
    platform, model = FixturePlatform(base), ReviewFailsOnce()
    runtime, context, model_client = await _compose(settings, factory, platform, model)
    try:
        origin = context.store.create_run(
            scope=SCOPE, idempotency_key="final-review-failure", expected_upload_count=3
        )
        admit_uploads(context.store, SCOPE, origin.run_id)
        finished = await _finish(runtime, context, jobs, origin.run_id)
        assert finished.state is ProductRunState.PARTIAL_SUCCESS
        final = context.artifacts.get_artifact(
            scope=SCOPE, run_id=origin.run_id,
            artifact_kind="discovery_final_summary", artifact_key="product",
        )
        assert json.loads(final.payload)["state"] == "FAILED"
        assert context.store.can_retry_processing(scope=SCOPE, run_id=origin.run_id)
        calls = context.artifacts.list_stage_calls(scope=SCOPE, run_id=origin.run_id)
        review = next(row for row in calls if row.stage_key == "compilation")
        with factory() as session, session.begin():
            row = session.scalar(select(ProductStageModelCall).where(
                ProductStageModelCall.call_id == review.call_id
            ))
            saved = (row.state, row.raw, row.raw_sha256)
            row.state, row.raw, row.raw_sha256 = "dispatched", None, None
        assert not context.store.can_retry_processing(scope=SCOPE, run_id=origin.run_id)
        with factory() as session, session.begin():
            row = session.scalar(select(ProductStageModelCall).where(
                ProductStageModelCall.call_id == review.call_id
            ))
            row.state, row.raw, row.raw_sha256 = saved
        # Hold the same signed base for this branch; changed-head rebasing is
        # exercised separately above.
        platform.current = {
            "release_id": base["snapshot"]["release_id"],
            "activation_epoch": base["snapshot"]["activation_epoch"],
        }
        platform.base = base
        before_generation = len(model.discovery_requests)
        child = context.store.retry_processing(
            scope=SCOPE, run_id=origin.run_id, expected_version=finished.version
        )
        plan = context.store.checkpoint_plan(scope=SCOPE, run_id=child.run_id)
        assert plan.contract_version == "6" and plan.resume_stage == "compilation"
        model.broken = False
        result = await _finish(runtime, context, jobs, child.run_id)
        assert result.state in {ProductRunState.SUCCEEDED, ProductRunState.PARTIAL_SUCCESS}, (
            result.terminal_reason, runtime.issues
        )
        assert len(model.discovery_requests) == before_generation
        assert len(model.discovery_review_requests) == 2
    finally:
        await runtime.close()
        await model_client.aclose()
        engine.dispose()
