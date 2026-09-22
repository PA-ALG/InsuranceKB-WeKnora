"""Legacy workflow-2 rebasing keeps execution semantics explicit and immutable."""

# ruff: noqa: F811 -- fixture imports are intentionally reused by pytest.

import json
import typing
from pathlib import Path

import pytest
from pydantic import ValidationError

from insurance_harness.db.base import Base, make_session_factory
from insurance_harness.jobs import JobStore, NonRetryableJobError
from insurance_harness.product_ingestion.checkpoints import CheckpointPlan
from insurance_harness.product_ingestion.models import ProductRunState
from insurance_harness.product_ingestion.progression import admit_uploads
from insurance_harness.product_ingestion.tables import ProductRun
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


def test_v7_explicitly_rebases_workflow_two_without_changing_v2_wire(
    stage_runtime: typing.Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope, store, _, _, child = _child(stage_runtime, monkeypatch)
    current = store.checkpoint_plan(scope=scope, run_id=child.run_id)
    old = CheckpointPlan.model_validate_json(
        json.dumps(
            {**current.model_dump(mode="json"), "contract": "product-stage-checkpoint-plan.830.v2"}
        )
    )
    assert old.contract == "product-stage-checkpoint-plan.830.v2"
    old_bytes = old.encoded()
    data = old.model_dump(mode="json")
    data.update(
        contract="product-stage-checkpoint-plan.830.v7",
        execution_workflow_version=2,
    )

    plan = CheckpointPlan.model_validate_json(json.dumps(data))

    assert plan.workflow_version == 2
    assert plan.supports_rebase
    assert b'"execution_workflow_version":2' in plan.encoded()
    assert old.encoded() == old_bytes
    assert b"execution_workflow_version" not in old_bytes

    data.pop("execution_workflow_version")
    with pytest.raises(ValidationError, match="execution_workflow_version"):
        CheckpointPlan.model_validate_json(json.dumps(data))


@pytest.mark.asyncio
async def test_changed_head_rebases_legacy_workflow_two_without_discovery_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, parent = _base_snapshot_with_navigation()
    settings = _settings(tmp_path, parent)
    engine = _sqlite_engine(tmp_path / "legacy-rebase.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    jobs = JobStore(factory, settings.job_runtime_config())
    platform, model = FixturePlatform(base), FixtureModel()
    runtime, context, model_client = await _compose(settings, factory, platform, model)
    service = context.bindings[SCOPE.space_id]
    original_create = service.platform.create_preparation

    async def fail_preparation(*args: object, **kwargs: object) -> None:
        raise NonRetryableJobError("PREPARATION_TEST_LIMIT")

    service.platform.create_preparation = fail_preparation
    try:
        origin = context.store.create_run(
            scope=SCOPE, idempotency_key="legacy-rebase-origin", expected_upload_count=3
        )
        with factory() as session, session.begin():
            row = session.get(ProductRun, origin.run_id)
            assert row is not None
            row.workflow_version = 2
        admit_uploads(context.store, SCOPE, origin.run_id)
        failed = await _finish(runtime, context, jobs, origin.run_id)
        assert failed.state is ProductRunState.FAILED

        legacy = context.store.retry_processing(
            scope=SCOPE, run_id=origin.run_id, expected_version=failed.version
        )
        legacy_plan = context.store.checkpoint_plan(scope=SCOPE, run_id=legacy.run_id)
        assert legacy_plan.contract == "product-stage-checkpoint-plan.830.v2"
        legacy_bytes = legacy_plan.encoded()

        platform.base = _published_snapshot(
            parent, release_id="legacy-current-release", activation_epoch=13
        )
        platform.current = {
            "release_id": "legacy-current-release",
            "activation_epoch": 13,
        }
        blocked = await _finish(runtime, context, jobs, legacy.run_id)
        assert blocked.state is ProductRunState.NEEDS_CONFIRMATION
        assert blocked.terminal_reason == "CHECKPOINT_BASE_CHANGED_UNSUPPORTED_WORKFLOW"

        child = context.store.retry_processing(
            scope=SCOPE, run_id=legacy.run_id, expected_version=blocked.version
        )
        plan = context.store.checkpoint_plan(scope=SCOPE, run_id=child.run_id)
        assert plan.contract == "product-stage-checkpoint-plan.830.v7"
        assert plan.execution_workflow_version == 2
        assert "synthesis" in {stage.stage_key for stage in plan.reused_stages}
        assert (
            context.store.checkpoint_plan(scope=SCOPE, run_id=legacy.run_id).encoded()
            == legacy_bytes
        )

        from insurance_harness.product_ingestion import compilation

        assemble = compilation.assemble_platform_candidate
        reviews = []

        def observe_review(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
            reviews.append(kwargs["independent_review"])
            return assemble(*args, **kwargs)

        monkeypatch.setattr(compilation, "assemble_platform_candidate", observe_review)
        before = (
            len(model.identity_requests),
            len(model.field_requests),
            len(model.discovery_requests),
            len(model.discovery_review_requests),
        )
        interrupted = await _finish(runtime, context, jobs, child.run_id)

        assert interrupted.state is ProductRunState.FAILED
        assert interrupted.terminal_reason == "PRODUCT_STAGE_FAILED:preparation"
        assert reviews == [None]
        assert (
            len(model.identity_requests),
            len(model.field_requests),
            len(model.discovery_requests),
            len(model.discovery_review_requests),
        ) == before
        assert "discovery" not in {
            row.stage_key for row in context.store.list_stages(scope=SCOPE, run_id=child.run_id)
        }
        receipt = context.store.checkpoint_receipt(scope=SCOPE, run_id=child.run_id)
        assert receipt.rebased_base_sha256 is not None
        assert receipt.reused_stages[-1].stage_key == "synthesis"

        grandchild = context.store.retry_processing(
            scope=SCOPE, run_id=child.run_id, expected_version=interrupted.version
        )
        grandplan = context.store.checkpoint_plan(scope=SCOPE, run_id=grandchild.run_id)
        assert grandplan.contract == "product-stage-checkpoint-plan.830.v7"
        assert {row.artifact_kind for row in grandplan.prior_rebase_artifacts} == {
            "rebased_base_snapshot",
            "rebased_compile_request",
            "rebased_identity",
            "rebased_compile_delta",
        }
        service.platform.create_preparation = original_create
        result = await _finish(runtime, context, jobs, grandchild.run_id)
        assert result.state in {ProductRunState.SUCCEEDED, ProductRunState.PARTIAL_SUCCESS}, (
            result.terminal_reason,
            runtime.issues,
        )
        assert reviews == [None]
        assert (
            len(model.identity_requests),
            len(model.field_requests),
            len(model.discovery_requests),
            len(model.discovery_review_requests),
        ) == before
    finally:
        await runtime.close()
        await model_client.aclose()
        engine.dispose()
