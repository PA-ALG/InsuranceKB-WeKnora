"""Native parse journals grow while their product source stage polls."""

from __future__ import annotations

import copy

# ruff: noqa: F811 -- imported pytest fixtures.
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from insurance_harness.jobs import JobState
from insurance_harness.jobs.tables import WikiJob
from insurance_harness.product_ingestion import tables
from tests.product_ingestion.test_platform import snapshot  # noqa: F401
from tests.product_ingestion.test_processing_receipts import receipt, sealed
from tests.product_ingestion.test_routing import catalog  # noqa: F401
from tests.product_ingestion.test_stages import stage_runtime  # noqa: F401


def _ready_again(store, run):
    with store._session_factory() as session, session.begin():
        stage = session.scalar(
            select(tables.ProductStage).where(
                tables.ProductStage.run_id == run.run_id,
                tables.ProductStage.stage_key == "source",
            )
        )
        session.get(WikiJob, stage.job_id).available_at = datetime(2020, 1, 1, tzinfo=UTC)


def _processing(ordinal, complete):
    value = receipt()
    value["knowledge_id"] = f"knowledge-{ordinal}"
    value["parse_attempt"] = 1
    if complete:
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
        value["counts"].update(attempts=1, confirmed=1)
    return sealed(value)


def test_source_poll_accepts_growing_journal_and_preserves_each_snapshot(stage_runtime):
    scope, store, artifacts, platform, execute = stage_runtime
    lookup = platform.lookup_upload
    complete = False

    async def observed(scope, run_id, ordinal):
        item = await lookup(scope, run_id, ordinal)
        item.update(
            parse_status="completed" if complete else "processing",
            processing_receipt=_processing(ordinal, complete),
            processing_receipt_parse_attempt=1,
        )
        return item

    platform.lookup_upload = observed
    run = store.create_run(scope=scope, idempotency_key="growing-journal", expected_upload_count=3)
    assert execute(run).state is JobState.SUCCEEDED
    assert execute(run).state is JobState.RETRY_WAIT
    initial = artifacts.list_artifacts(
        scope=scope, run_id=run.run_id, artifact_kind="source_processing_attempt"
    )
    initial_bytes = {item.artifact_id: item.payload for item in initial}
    assert len(initial) == 3
    complete = True
    _ready_again(store, run)
    outcome = execute(run)
    assert outcome.state is JobState.SUCCEEDED, outcome.error_summary
    saved = artifacts.list_artifacts(
        scope=scope, run_id=run.run_id, artifact_kind="source_processing_attempt"
    )
    assert len(saved) == 6
    assert all(
        item.payload == initial_bytes[item.artifact_id]
        for item in saved
        if item.artifact_id in initial_bytes
    )
    assert sum(json.loads(item.payload)["counts"]["attempts"] for item in saved) == 3


def test_conflicting_terminal_source_receipt_stops_without_wait_retry(stage_runtime):
    scope, store, _artifacts, platform, execute = stage_runtime
    lookup = platform.lookup_upload
    changed = False

    async def observed(scope, run_id, ordinal):
        item = await lookup(scope, run_id, ordinal)
        value = _processing(ordinal, True)
        if changed:
            value["calls"][0]["http_status"] = 500
        item.update(
            parse_status="processing",
            processing_receipt=sealed(value),
            processing_receipt_parse_attempt=1,
        )
        return item

    platform.lookup_upload = observed
    run = store.create_run(scope=scope, idempotency_key="changed-terminal", expected_upload_count=3)
    assert execute(run).state is JobState.SUCCEEDED
    assert execute(run).state is JobState.RETRY_WAIT
    changed = True
    _ready_again(store, run)
    outcome = execute(run)
    assert outcome.state is JobState.DEAD_LETTER
    assert "SOURCE_PROCESSING_RECEIPT_CONFLICT" in outcome.error_summary


def test_processing_attempts_share_dispatch_accounting_without_losing_audits():
    from insurance_harness.product_ingestion.processing_audit import (
        latest_attempts,
        source_accounting,
    )

    first = _processing(0, True)
    second = copy.deepcopy(first)
    second["processing_attempt"] += 1
    second["journal_marker_sha256"] = "c" * 64
    second["calls"].append({**second["calls"][0], "dispatch_id": "new-call"})
    second["counts"].update(attempts=2, confirmed=2)
    second = sealed(second)
    assert len(latest_attempts([first, second])) == 2
    summary = source_accounting(None, [first, second])
    assert summary["recorded_model_call_count"] == 2
    assert summary["model_call_count"] is None


def test_uncertain_dispatch_can_gain_matching_late_response_but_not_change_request():
    from insurance_harness.jobs import NonRetryableJobError
    from insurance_harness.product_ingestion.processing_audit import latest_attempts

    known = _processing(0, True)
    unknown = copy.deepcopy(known)
    call = unknown["calls"][0]
    call.pop("http_status")
    call.update(state="INTERRUPTED", outcome="DISPATCH_UNCERTAIN")
    unknown["counts"].update(confirmed=0, interrupted=1)
    unknown = sealed(unknown)
    assert latest_attempts([unknown, known]) == (known,)
    assert latest_attempts([known, unknown]) == (known,)
    changed = copy.deepcopy(known)
    changed["calls"][0]["request_sha256"] = "d" * 64
    with pytest.raises(NonRetryableJobError, match="SOURCE_PROCESSING_RECEIPT_CONFLICT"):
        latest_attempts([unknown, sealed(changed)])


def test_reindexed_completed_phase_occurrences_preserve_prior_facts():
    from insurance_harness.product_ingestion.processing_audit import latest_attempts

    first = _processing(0, False)
    phase = first["phases"][-1]
    phase["recorded"] = True
    later = dict(
        occurrence=0,
        status="done",
        started_at_unix_ms=2000,
        finished_at_unix_ms=2100,
        duration_ms=100,
    )
    phase["occurrences"] = [later]
    first = sealed(first)
    second = copy.deepcopy(first)
    second["phases"][-1]["occurrences"] = [
        dict(
            occurrence=0,
            status="done",
            started_at_unix_ms=1000,
            finished_at_unix_ms=2200,
            duration_ms=1200,
        ),
        {**later, "occurrence": 1},
    ]
    second = sealed(second)
    assert latest_attempts([first, second]) == (second,)


def test_completed_summary_adds_only_distinct_previous_attempt_dispatches():
    from insurance_harness.product_ingestion.processing_audit import source_accounting
    from insurance_harness.product_ingestion.processing_receipts import processing_summary

    first = _processing(0, True)
    final = copy.deepcopy(first)
    final["parse_attempt"] = 2
    final["processing_attempt"] += 1
    final["journal_marker_sha256"] = "d" * 64
    final["calls"] = [{**final["calls"][0], "dispatch_id": "new-call"}]
    final = sealed(final)
    summary = processing_summary([("knowledge-0", final, False)])
    result = source_accounting(summary, [_processing(0, False), first, final])
    assert result["recorded_model_call_count"] == 2
    assert result["model_call_count_complete"] is True
    assert len(result["prior_attempts"]) == 1
    assert summary["recorded_model_call_count"] == 1


def test_unknown_legacy_summary_identity_never_guesses_or_double_counts():
    from insurance_harness.product_ingestion.processing_audit import source_accounting
    from insurance_harness.product_ingestion.processing_receipts import processing_summary

    final = _processing(0, True)
    summary = processing_summary([("knowledge-0", final, False)])
    summary["materials"][0]["receipt_sha256"] = "f" * 64
    result = source_accounting(summary, [final])
    assert result["recorded_model_call_count"] == 1
    assert result["model_call_count"] is None
    assert result["model_call_count_complete"] is False


def test_completed_summary_uses_late_response_without_mutating_original_summary():
    from insurance_harness.product_ingestion.processing_audit import source_accounting
    from insurance_harness.product_ingestion.processing_receipts import processing_summary

    final = _processing(0, True)
    uncertain = copy.deepcopy(final)
    uncertain["calls"][0].pop("http_status")
    uncertain["calls"][0].update(state="INTERRUPTED", outcome="DISPATCH_UNCERTAIN")
    uncertain["counts"].update(confirmed=0, interrupted=1)
    uncertain = sealed(uncertain)
    summary = processing_summary([("knowledge-0", uncertain, False)])
    before = copy.deepcopy(summary)
    result = source_accounting(summary, [uncertain, final])
    assert result["model_call_count_complete"] is True
    assert result["interrupted_count"] == 0
    assert result["model_call_count"] == 1
    assert result["materials"][0]["receipt_sha256"] == final["receipt_sha256"]
    assert summary == before


def test_deduplicated_total_preserves_exact_material_receipt_counts():
    from insurance_harness.product_ingestion.processing_audit import source_accounting

    first = _processing(0, True)
    second = copy.deepcopy(first)
    second["processing_attempt"] += 1
    second["journal_marker_sha256"] = "d" * 64
    second = sealed(second)
    result = source_accounting(None, [first, second])
    assert result["recorded_model_call_count"] == 1
    originals = {row["receipt_sha256"]: row for row in (first, second)}
    for row in result["materials"]:
        assert row["counts"] == originals[row["receipt_sha256"]]["counts"]
