"""Checkpoint recovery keeps source call audits without reusing them as stage outputs."""

from __future__ import annotations

# ruff: noqa: F811 -- imported pytest fixtures.
import json
from datetime import UTC, datetime

from sqlalchemy import select

from insurance_harness.jobs import JobState
from insurance_harness.jobs.tables import WikiJob
from insurance_harness.product_ingestion import stages, tables
from insurance_harness.product_ingestion.artifact_tables import ProductArtifact
from insurance_harness.product_ingestion.checkpoint_store import _ref
from tests.product_ingestion.test_platform import snapshot  # noqa: F401
from tests.product_ingestion.test_processing_receipts import receipt, sealed
from tests.product_ingestion.test_recovery import finish_failed_source
from tests.product_ingestion.test_routing import catalog  # noqa: F401
from tests.product_ingestion.test_stages import stage_runtime  # noqa: F401


def _finish_source_after_wait_with_processing_audits(stage_runtime, monkeypatch):
    scope, store, artifacts, platform, execute = stage_runtime
    original_lookup = platform.lookup_upload
    reparsed = False

    def processing(ordinal):
        value = receipt()
        value["knowledge_id"] = f"knowledge-{ordinal}"
        value["parse_attempt"] = 1
        value["calls"] = [
            {
                "contract": "knowledge-model-dispatch-receipt.830.v1",
                "dispatch_id": f"call-{ordinal}",
                "operation": "embedding",
                "purpose": "document_embedding",
                "model_id": "embed",
                "model_name": "qwen",
                "request_sha256": "b" * 64,
                "transport_retry_index": 0,
                "state": "RECORDED",
                "outcome": "HTTP_RESPONSE",
                "http_status": 200,
                "started_at_unix_ms": 1000,
                "finished_at_unix_ms": 1020,
                "duration_ms": 20,
            }
        ]
        value["counts"]["attempts"] = 1
        value["counts"]["confirmed"] = 1
        return sealed(value)

    async def lookup(_scope, run_id, ordinal):
        item = await original_lookup(_scope, run_id, ordinal)
        if ordinal < 2:
            item["processing_receipt"] = processing(ordinal)
            item["processing_receipt_parse_attempt"] = 1
        if ordinal == 2:
            item["parse_status"] = "completed" if reparsed else "failed"
            item["parse_attempt"] = 2 if reparsed else 1
        return item

    async def no_receipt(*_args):
        return None

    async def reparse(_scope, run_id, ordinal, attempt, recovery_key, deadline):
        nonlocal reparsed
        reparsed = True
        return {
            "contract": "g3-platform-bound-reparse.830.v1",
            "run_id": run_id,
            "ordinal": ordinal,
            "knowledge_id": "knowledge-2",
            "expected_parse_attempt": attempt,
            "parse_attempt": attempt + 1,
            "recovery_key": recovery_key,
            "deadline_at": deadline.isoformat(),
            "dispatch_state": "enqueued",
            "queue_task_id": "task-2",
            "parse_status": "processing",
        }

    platform.lookup_upload = lookup
    platform.get_reparse_receipt = no_receipt
    platform.reparse_upload = reparse
    run = store.create_run(
        scope=scope, idempotency_key="checkpoint-audit-lifecycle", expected_upload_count=3
    )
    assert execute(run).state is JobState.SUCCEEDED
    assert execute(run).state is JobState.RETRY_WAIT
    audits = artifacts.list_artifacts(
        scope=scope, run_id=run.run_id, artifact_kind="source_processing_attempt"
    )
    assert len(audits) == 2
    audit_generation = {row.producer_generation for row in audits}
    assert len(audit_generation) == 1
    with store._session_factory() as session, session.begin():
        source_stage = session.scalar(
            select(tables.ProductStage).where(
                tables.ProductStage.run_id == run.run_id,
                tables.ProductStage.stage_key == "source",
            )
        )
        session.get(WikiJob, source_stage.job_id).available_at = datetime(2020, 1, 1, tzinfo=UTC)

    source_job = execute(run)
    assert source_job.state is JobState.SUCCEEDED
    assert all(row.producer_generation < source_job.lease_generation for row in audits)

    def unavailable(*_args, **_kwargs):
        raise ValueError("FIRST_PAGE_PRODUCT_NAME_UNAVAILABLE")

    with monkeypatch.context() as patch:
        patch.setattr(stages, "prepare_identity_routing", unavailable)
        blocked = execute(run)
    assert blocked.state is JobState.BLOCKED
    with store._session_factory() as session, session.begin():
        session.get(tables.ProductRun, run.run_id).root_job_id = blocked.id
    return scope, store, artifacts, store.get_run(scope=scope, run_id=run.run_id), audits


def test_recovery_excludes_earlier_generation_source_audits_but_keeps_parent_rows(
    stage_runtime, monkeypatch
):
    scope, store, artifacts, origin, audits = _finish_source_after_wait_with_processing_audits(
        stage_runtime, monkeypatch
    )
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    plan = store.checkpoint_plan(scope=scope, run_id=child.run_id)

    assert all(ref.artifact_kind != "source_processing_attempt" for ref in plan.artifacts)
    assert len(
        artifacts.list_artifacts(
            scope=scope,
            run_id=origin.run_id,
            artifact_kind="source_processing_attempt",
        )
    ) == len(audits)
    assert (
        artifacts.verify_checkpoint(scope=scope, run_id=child.run_id).plan_sha256
        == plan.digest()
    )


def test_retry_of_old_failed_checkpoint_drops_inherited_source_audit_reference(
    stage_runtime, monkeypatch
):
    scope, store, artifacts, origin, audits = _finish_source_after_wait_with_processing_audits(
        stage_runtime, monkeypatch
    )
    child = store.retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    plan = store.checkpoint_plan(scope=scope, run_id=child.run_id)
    checkpoint_stage = store.list_stages(scope=scope, run_id=child.run_id)[0]

    with store._session_factory() as session, session.begin():
        audit = session.get(ProductArtifact, audits[0].artifact_id)
        reusable = tuple(
            ref for ref in plan.artifacts if ref.artifact_kind != "source_processing_attempt"
        )
        legacy = plan.model_copy(update={"artifacts": (*reusable, _ref(audit))})
        saved = session.scalar(
            select(ProductArtifact).where(
                ProductArtifact.run_id == child.run_id,
                ProductArtifact.artifact_kind == "checkpoint_plan",
            )
        )
        saved.payload = legacy.encoded()
        saved.payload_sha256 = legacy.digest()
        checkpoint_job = session.get(WikiJob, checkpoint_stage.job_id)
        checkpoint_job.state = "dead_letter"
        checkpoint_job.error_class = "non_retryable"
        checkpoint_job.error_summary = "CHECKPOINT_INVALID"
        checkpoint_job.finished_at = datetime.now(UTC)
    finish_failed_source(store, scope, child.run_id)
    failed = store.get_run(scope=scope, run_id=child.run_id)

    grandchild = store.retry_processing(
        scope=scope, run_id=child.run_id, expected_version=failed.version
    )
    inherited = store.checkpoint_plan(scope=scope, run_id=grandchild.run_id)

    assert all(ref.artifact_kind != "source_processing_attempt" for ref in inherited.artifacts)
    assert artifacts.verify_checkpoint(
        scope=scope, run_id=grandchild.run_id
    ).plan_sha256 == inherited.digest()
    assert json.loads(audits[0].payload)["knowledge_id"] in {"knowledge-0", "knowledge-1"}
