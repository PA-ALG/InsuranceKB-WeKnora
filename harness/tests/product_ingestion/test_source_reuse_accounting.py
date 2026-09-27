"""Historical source receipts must not inflate a newly admitted run's cost."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from typing import Any

import pytest

from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.processing_audit import source_accounting
from insurance_harness.product_ingestion.processing_receipts import processing_summary
from tests.product_ingestion.test_api import PATH, auth, environment  # noqa: F401
from tests.product_ingestion.test_processing_audit_lifecycle import _processing
from tests.product_ingestion.test_processing_receipts import sealed


def test_api_reclassifies_exact_historical_receipt_without_rewriting_it(
    environment: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, *_ = environment
    run = client.post(
        PATH,
        headers=auth(),
        json={
            "idempotency_key": "historical-source",
            "expected_upload_count": 1,
        },
    ).json()["data"]
    receipt = _processing(0, True)
    original = processing_summary([("knowledge-0", receipt, False)])
    original_bytes = json.dumps(original).encode()
    monkeypatch.setattr(
        ProductArtifactStore,
        "list_artifacts",
        lambda _self, **kw: (
            (SimpleNamespace(payload=json.dumps(receipt).encode()),)
            if kw["artifact_kind"] == "source_processing_attempt"
            else ()
        ),
    )
    monkeypatch.setattr(
        ProductArtifactStore,
        "list_effective_artifacts",
        lambda _self, **kw: (
            (SimpleNamespace(run_id=run["run_id"], payload=original_bytes),)
            if kw["artifact_kind"] == "source_processing_summary"
            else ()
        ),
    )
    status = client.get(PATH + "/" + run["run_id"], headers=auth()).json()["data"]
    assert status["model_call_count"] == 0
    assert status["recorded_source_model_call_count"] == 0
    assert status["source_processing"]["recorded_reused_model_call_count"] == 1
    material = status["source_processing"]["materials"][0]
    assert material["reused"] is True
    assert material["receipt_sha256"] == receipt["receipt_sha256"]
    assert material["counts"] == receipt["counts"]
    assert json.dumps(original).encode() == original_bytes


def test_mixed_attempts_count_each_dispatch_once_and_keep_original_audits() -> None:
    historical = _processing(0, True)
    current = copy.deepcopy(historical)
    current["processing_attempt"] += 1
    current["journal_marker_sha256"] = "d" * 64
    current["calls"].append(
        {
            **current["calls"][0],
            "dispatch_id": "new-call",
            "started_at_unix_ms": 2000,
            "finished_at_unix_ms": 2020,
        }
    )
    current["counts"].update(attempts=2, confirmed=2)
    current = sealed(current)
    summary = processing_summary([("knowledge-0", current, False)])
    before = copy.deepcopy((summary, historical, current))
    result = source_accounting(summary, [historical, current], admitted_at_unix_ms=1500)
    assert result is not None
    assert result["recorded_model_call_count"] == 1
    assert result["recorded_reused_model_call_count"] == 1
    assert result["materials"][0]["reused"] is False
    assert result["prior_attempts"][0]["reused"] is True
    assert (summary, historical, current) == before


@pytest.mark.parametrize(
    "cutoff,uncertain,opaque,expected",
    [
        (1020, False, False, 1),
        (1021, False, False, 0),
        (1500, True, False, 1),
        (1500, False, True, 1),
    ],
)
def test_history_requires_exact_confirmed_completion(
    cutoff: int,
    uncertain: bool,
    opaque: bool,
    expected: int,
) -> None:
    receipt = _processing(0, True)
    if uncertain:
        receipt["calls"][0].pop("http_status")
        receipt["calls"][0].update(state="INTERRUPTED", outcome="DISPATCH_UNCERTAIN")
        receipt["counts"].update(confirmed=0, interrupted=1)
        receipt = sealed(receipt)
    summary = processing_summary([("knowledge-0", receipt, False)])
    assert summary is not None
    if opaque:
        summary["materials"][0]["receipt_sha256"] = "f" * 64
    result = source_accounting(summary, [receipt], admitted_at_unix_ms=cutoff)
    assert result is not None
    assert result["recorded_model_call_count"] == expected
    assert result["recorded_reused_model_call_count"] == 1 - expected
    assert result["materials"][0]["reused"] is (expected == 0)
    if uncertain or opaque:
        assert result["model_call_count_complete"] is False


@pytest.mark.parametrize("reverse", [False, True])
def test_explicit_reuse_wins_for_shared_dispatch_independent_of_order(reverse: bool) -> None:
    first = _processing(0, True)
    second = copy.deepcopy(first)
    second["processing_attempt"] += 1
    second["journal_marker_sha256"] = "d" * 64
    second = sealed(second)
    rows = [("knowledge-0", first, False), ("knowledge-0", second, True)]
    if reverse:
        rows.reverse()
    result = source_accounting(processing_summary(rows), [first, second], admitted_at_unix_ms=0)
    assert result is not None
    assert result["recorded_model_call_count"] == 0
    assert result["recorded_reused_model_call_count"] == 1


@pytest.mark.parametrize("not_dispatched", [False, True])
def test_no_dispatch_is_not_inferred_as_historical(not_dispatched: bool) -> None:
    receipt = _processing(0, not_dispatched)
    if not_dispatched:
        receipt["calls"][0].pop("http_status")
        receipt["calls"][0].update(state="INTERRUPTED", outcome="NOT_DISPATCHED")
        receipt["counts"].update(attempts=0, confirmed=0, not_dispatched=1)
        receipt = sealed(receipt)
    result = source_accounting(
        processing_summary([("knowledge-0", receipt, False)]), [receipt], admitted_at_unix_ms=1500
    )
    assert result is not None
    assert result["materials"][0]["reused"] is False
    assert result["recorded_model_call_count"] == 0
    assert result["recorded_reused_model_call_count"] == 0
