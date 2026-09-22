"""Independent discovery is a persisted stage and a complete checkpoint dependency."""

from __future__ import annotations

import typing

# ruff: noqa: F811 -- imported pytest fixtures
from sqlalchemy import select

from insurance_harness.product_ingestion.artifact_tables import ProductArtifact
from insurance_harness.product_ingestion.checkpoints import (
    CURRENT_ARTIFACT_CONTRACTS,
    required_outputs,
    stage_order,
)
from insurance_harness.product_ingestion.tables import ProductRun
from tests.product_ingestion.test_checkpoint_artifact_version import _metadata_origin
from tests.product_ingestion.test_store import (
    _make_store,
    _scope,
    api,  # noqa: F401
    factory,  # noqa: F401
)


def test_new_run_uses_v3_without_changing_older_stage_orders(
    api: typing.Any, factory: typing.Any
) -> None:
    store, _jobs = _make_store(api, factory)
    run = store.create_run(scope=_scope(api), idempotency_key="workflow-v3")
    assert run.workflow_version == 3
    assert stage_order(1) == (
        "uploads",
        "source",
        "routing",
        "identity",
        "field_plan",
        "extract",
        "synthesis",
        "compilation",
        "review",
        "publish",
        "verify",
    )
    assert stage_order(2) == (
        "uploads",
        "source",
        "routing",
        "identity",
        "field_plan",
        "extract",
        "synthesis",
        "compilation",
        "preparation",
        "review",
        "publish",
        "verify",
    )
    assert stage_order(3) == (
        "uploads",
        "source",
        "routing",
        "identity",
        "field_plan",
        "extract",
        "synthesis",
        "discovery",
        "compilation",
        "preparation",
        "review",
        "publish",
        "verify",
    )
    assert required_outputs(3)["synthesis"] == ("compile_delta", "field_validation")
    assert required_outputs(3)["discovery"] == (
        "discovery_candidates",
        "discovery_delta",
        "discovery_summary",
    )
    for kind in (
        "discovery_context",
        "discovery_window_audit",
        "discovery_window_replay_receipt",
        "discovery_response",
        "discovery_proposal",
        "discovery_review_context",
        "discovery_review_response",
        "discovery_review_proof",
        "reviewed_discovery_delta",
        "discovery_final_summary",
        "composite_review",
    ):
        assert CURRENT_ARTIFACT_CONTRACTS[kind] == (f"product-{kind}.v1", "1")


def test_v3_checkpoint_reuses_complete_discovery_then_resumes_compilation(
    api: typing.Any, factory: typing.Any
) -> None:
    scope, store, origin, _ = _metadata_origin(
        api,
        factory,
        workflow=3,
        candidate_contract=("product-candidate.v2", "2"),
        failed_stage="compilation",
    )
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    plan = store.checkpoint_plan(scope=scope, run_id=child.run_id)
    assert child.workflow_version == plan.workflow_version == 3
    assert plan.contract == "product-stage-checkpoint-plan.830.v6"
    assert plan.supports_rebase and not plan.field_only_rebase
    assert plan.audited_calls == () and plan.prior_rebase_artifacts == ()
    assert plan.resume_stage == "compilation"
    assert plan.encoded() == type(plan).model_validate_json(plan.encoded()).encoded()
    assert {row.artifact_kind for row in plan.artifacts if row.stage_key == "discovery"} == {
        "discovery_candidates",
        "discovery_delta",
        "discovery_summary",
    }


def test_v3_checkpoint_does_not_skip_missing_discovery_output(
    api: typing.Any, factory: typing.Any
) -> None:
    scope, store, origin, _ = _metadata_origin(
        api,
        factory,
        workflow=3,
        candidate_contract=("product-candidate.v2", "2"),
        failed_stage="compilation",
    )
    with factory() as session, session.begin():
        row = session.scalar(
            select(ProductArtifact).where(
                ProductArtifact.run_id == origin.run_id,
                ProductArtifact.artifact_kind == "discovery_delta",
            )
        )
        session.delete(row)
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    plan = store.checkpoint_plan(scope=scope, run_id=child.run_id)
    assert plan.resume_stage == "discovery"
    assert all(ref.stage_key != "discovery" for ref in plan.artifacts)
    with factory() as session:
        assert session.get(ProductRun, origin.run_id).workflow_version == 3
