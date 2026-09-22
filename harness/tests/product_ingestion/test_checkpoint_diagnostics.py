"""Checkpoint failures identify the failed boundary without exposing provider/config data."""

import typing
from pathlib import Path
from types import SimpleNamespace

import pytest

from insurance_harness.db.base import Base, make_session_factory
from insurance_harness.jobs import CapacityBlockedJobError, JobSnapshot, NonRetryableJobError
from insurance_harness.product_ingestion.composition import ProductCompositionContext
from insurance_harness.product_ingestion.models import ProductRunSnapshot, StageSnapshot
from insurance_harness.product_ingestion.pipeline import build_product_pipeline
from tests.product_ingestion.test_pipeline_runtime import (
    SCOPE,
    FixtureModel,
    FixturePlatform,
    _base_snapshot_with_navigation,
    _compose,
    _json,
    _settings,
    _sqlite_engine,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        ("local_proof", "CHECKPOINT_LOCAL_PROOF_INVALID"),
        ("base_changed", "CHECKPOINT_BASE_CHANGED_UNSUPPORTED_WORKFLOW"),
    ],
)
async def test_pipeline_reports_safe_checkpoint_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: typing.Any, reason: typing.Any
) -> None:
    base, parent = _base_snapshot_with_navigation()
    settings = _settings(tmp_path, parent)
    engine = _sqlite_engine(tmp_path / "checkpoint-diagnostic.db")
    Base.metadata.create_all(engine)
    platform = FixturePlatform(base)
    runtime, context, model_client = await _compose(
        settings, make_session_factory(engine), platform, FixtureModel()
    )
    plan = SimpleNamespace(
        contract_version="2",
        supports_rebase=False,
        materials=(),
        prior_rebase_artifacts=(),
        reused_stages=(),
        artifacts=(SimpleNamespace(artifact_kind="base_snapshot"),),
    )
    monkeypatch.setattr(context.store, "checkpoint_plan", lambda **_: plan)
    monkeypatch.setattr(context.store, "get_upload_manifest", lambda **_: None)

    def verify(**_: object) -> SimpleNamespace:
        if failure == "local_proof":
            raise ValueError("checkpoint artifact producer fence changed; secret-canary")
        return SimpleNamespace()

    monkeypatch.setattr(context.artifacts, "verify_checkpoint", verify)
    monkeypatch.setattr(
        context.artifacts,
        "read_checkpoint_artifact",
        lambda **_: SimpleNamespace(payload=_json(base)),
    )
    platform.current = {"release_id": "new-current-release", "activation_epoch": 13}
    try:
        handler = build_product_pipeline(context).stage_handlers["checkpoint"]
        with pytest.raises(CapacityBlockedJobError) as caught:
            await handler(
                SCOPE,
                typing.cast(ProductRunSnapshot, SimpleNamespace(run_id="diagnostic")),
                typing.cast(StageSnapshot, SimpleNamespace()),
                typing.cast(JobSnapshot, None),
            )
        assert str(caught.value) == "needs_confirmation:" + reason
        assert "secret-canary" not in str(caught.value)
        assert platform.activations == 0 and platform.source_captures == 0
    finally:
        await runtime.close()
        await model_client.aclose()
        engine.dispose()


@pytest.mark.asyncio
async def test_pipeline_rejects_registry_binding_scope_mismatch() -> None:
    from insurance_harness.product_ingestion.checkpoint_validation import validate_checkpoint

    context = SimpleNamespace(
        bindings={SCOPE.space_id: SimpleNamespace(scope=SCOPE)},
    )
    mismatched = SCOPE.model_copy(update={"raw_knowledge_base_id": "other-raw"})
    with pytest.raises(NonRetryableJobError, match="^PRODUCT_PIPELINE_SCOPE_MISMATCH$"):
        await validate_checkpoint(
            typing.cast(ProductCompositionContext, context),
            mismatched,
            typing.cast(ProductRunSnapshot, SimpleNamespace(run_id="scope-mismatch")),
            typing.cast(StageSnapshot, SimpleNamespace()),
        )
