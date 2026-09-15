"""Metadata selection only: obsolete candidates cannot satisfy completed compilation."""

from __future__ import annotations

# ruff: noqa: F811 -- imported pytest fixtures.
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from insurance_harness.jobs.tables import WikiJob
from insurance_harness.product_ingestion.artifact_tables import ProductArtifact
from insurance_harness.product_ingestion.checkpoints import (
    CURRENT_ARTIFACT_CONTRACTS,
    required_outputs,
    stage_order,
)
from insurance_harness.product_ingestion.tables import ProductRun
from tests.product_ingestion.test_recovery import finish_failed_source
from tests.product_ingestion.test_store import (
    _make_store,
    _run_with_uploads,
    _scope,
    api,  # noqa: F401
    factory,  # noqa: F401
)


def _metadata_origin(api, factory, *, workflow, candidate_contract, failed_stage):
    """Small local persisted metadata, not a fabricated business candidate or worker proof."""
    store, _ = _make_store(api, factory)
    scope = _scope(api)
    origin, _ = _run_with_uploads(api, store)
    with factory() as session, session.begin():
        session.get(ProductRun, origin.run_id).workflow_version = workflow
    snapshots = []
    for key in stage_order(workflow):
        stage = store.enqueue_stage(
            scope=scope,
            run_id=origin.run_id,
            stage_key=key,
            dependency_sha256=hashlib.sha256(key.encode()).hexdigest(),
            idempotency_key=f"fixture:{key}",
        )
        now = datetime.now(UTC)
        with factory() as session, session.begin():
            job = session.get(WikiJob, stage.job_id)
            job.state = "dead_letter" if key == failed_stage else "succeeded"
            job.lease_generation = 1
            job.started_at = job.finished_at = now
            if key != failed_stage:
                for kind in required_outputs(workflow)[key]:
                    contract = (
                        candidate_contract
                        if kind == "candidate"
                        else CURRENT_ARTIFACT_CONTRACTS.get(kind, (f"fixture-{kind}.v1", "1"))
                    )
                    payload = json.dumps({"fixture_kind": kind}).encode()
                    artifact = ProductArtifact(
                        id=str(uuid4()),
                        run_id=origin.run_id,
                        space_id=scope.space_id,
                        stage_key=key,
                        artifact_kind=kind,
                        artifact_key="knowledge-0" if kind == "source_snapshot" else "product",
                        contract_name=contract[0],
                        contract_version=contract[1],
                        dependency_sha256=stage.dependency_sha256,
                        payload=payload,
                        payload_sha256=hashlib.sha256(payload).hexdigest(),
                        origin="rule",
                        origin_call_id=None,
                        producer_job_id=stage.job_id,
                        producer_generation=1,
                        created_at=now,
                    )
                    session.add(artifact)
                    snapshots.append((artifact.id, payload, artifact.payload_sha256))
        if key == failed_stage:
            break
    finish_failed_source(store, scope, origin.run_id)
    return scope, store, store.get_run(scope=scope, run_id=origin.run_id), snapshots


@pytest.mark.parametrize(
    "contract",
    [
        ("product-candidate.v1", "1"),
        ("product-candidate.v2", "1"),
        ("other-candidate.v2", "2"),
    ],
)
def test_obsolete_candidate_truncates_compilation_and_all_downstream(api, factory, contract):
    scope, store, origin, before = _metadata_origin(
        api, factory, workflow=2, candidate_contract=contract, failed_stage="publish"
    )
    statements = []
    engine = factory.kw["bind"] if hasattr(factory, "kw") else None
    with factory() as session:
        engine = session.get_bind()

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with factory() as session:
            plan = store._checkpoint_candidate(
                session, scope, session.get(ProductRun, origin.run_id)
            )
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert plan.resume_stage == "compilation"
    assert plan.workflow_version == 2
    assert tuple(s.stage_key for s in plan.reused_stages) == stage_order(2)[:7]
    assert {r.artifact_kind for r in plan.artifacts} == {
        "source_snapshot",
        "routing",
        "identity",
        "base_snapshot",
        "compile_request",
        "field_plan",
        "compile_delta",
        "field_validation",
    }
    assert not any(
        "product_ingestion_artifacts.payload " in sql.lower()
        or "product_ingestion_artifacts.payload," in sql.lower()
        for sql in statements
    )
    with factory() as session:
        after = {
            row.id: (row.payload, row.payload_sha256)
            for row in session.scalars(select(ProductArtifact))
        }
    assert all(after[identity] == (raw, sha) for identity, raw, sha in before)
    assert store.get_run(scope=scope, run_id=origin.run_id) == origin


def test_old_synthesis_resumes_validation_without_replaying_extraction(api, factory):
    scope, store, origin, _ = _metadata_origin(
        api,
        factory,
        workflow=2,
        candidate_contract=("product-candidate.v2", "2"),
        failed_stage="preparation",
    )
    with factory() as session, session.begin():
        for row in session.scalars(
            select(ProductArtifact).where(ProductArtifact.run_id == origin.run_id)
        ):
            if row.artifact_kind == "field_validation":
                session.delete(row)
            elif row.artifact_kind == "compile_delta":
                row.contract_name, row.contract_version = "product-compile_delta.v1", "1"
    with factory() as session:
        plan = store._checkpoint_candidate(session, scope, session.get(ProductRun, origin.run_id))
    assert plan.resume_stage == "synthesis"
    assert tuple(row.stage_key for row in plan.reused_stages) == stage_order(2)[:6]


def test_obsolete_legacy_combined_compilation_upgrades_to_split_workflow(api, factory):
    scope, store, origin, _ = _metadata_origin(
        api,
        factory,
        workflow=1,
        candidate_contract=("product-candidate.v1", "1"),
        failed_stage="review",
    )
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    plan = store.checkpoint_plan(scope=scope, run_id=child.run_id)
    assert child.workflow_version == plan.workflow_version == 2
    assert plan.resume_stage == "compilation"
    assert all(r.stage_key != "compilation" for r in plan.artifacts)
    assert store.get_run(scope=scope, run_id=origin.run_id).workflow_version == 1


@pytest.mark.parametrize("workflow,failed_stage", [(2, "preparation"), (1, "review")])
def test_current_candidate_keeps_successful_compilation_and_legacy_order(
    api, factory, workflow, failed_stage
):
    scope, store, origin, _ = _metadata_origin(
        api,
        factory,
        workflow=workflow,
        candidate_contract=("product-candidate.v2", "2"),
        failed_stage=failed_stage,
    )
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    plan = store.checkpoint_plan(scope=scope, run_id=child.run_id)
    assert plan.resume_stage == failed_stage
    assert plan.workflow_version == child.workflow_version == workflow
    assert any(r.artifact_kind == "candidate" for r in plan.artifacts)
    if workflow == 1:
        assert any(
            r.artifact_kind == "preparation" and r.stage_key == "compilation"
            for r in plan.artifacts
        )
